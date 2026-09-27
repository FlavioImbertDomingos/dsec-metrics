"""HTTP for collectors: timeouts, retries with backoff, pagination, size limits, and the
outbound policy on every request (see :mod:`dsec_metrics.plugins.sdk.ssrf`).

Standard library only. Connections go to the address the policy checked, with the host
name used for TLS verification and SNI. Redirects are never followed.

Read-only by construction: :class:`HttpClient` sends GET, and POST only for the named
read actions a collector declares (some APIs, such as AWS's JSON APIs, use POST for reads).
"""

from __future__ import annotations

import http.client
import json
import random
import socket
import ssl
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar
from urllib.parse import quote, urlencode, urljoin, urlsplit

from pydantic import Field

from dsec_metrics.__about__ import __version__
from dsec_metrics.config import get_settings
from dsec_metrics.plugins.sdk.base import Collector, CollectorConfig, CollectorError
from dsec_metrics.plugins.sdk.secrets import SecretResolver
from dsec_metrics.plugins.sdk.ssrf import BlockedURL, OutboundPolicy, Target

MAX_BYTES = 20 * 1024 * 1024
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# A whole request must finish within this many times the per-read timeout.
DEADLINE_FACTOR = 4
CHUNK = 64 * 1024

# Headers a collector may not set: they change where a request is routed, how it is
# framed, or which method a server applies. The client sets Host from the checked URL.
FORBIDDEN_HEADERS = frozenset(
    {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "te",
        "upgrade",
        "forwarded",
        "x-original-url",
        "x-rewrite-url",
        "x-http-method",
        "x-http-method-override",
        "x-method-override",
    }
)


def forbidden_header(name: str) -> bool:
    """Whether a collector may not set this header."""
    lowered = name.strip().lower()
    return lowered in FORBIDDEN_HEADERS or lowered.startswith("x-forwarded-")


@dataclass(frozen=True)
class HttpRequest:
    """What is sent. ``headers`` may hold credentials; it is never logged."""

    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None = None
    action: str | None = None


@dataclass(frozen=True)
class HttpResponse:
    """What came back. Header names are lower case."""

    status: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CollectorError("response is not JSON") from None


Transport = Callable[[HttpRequest, Target, float], HttpResponse]


class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to a fixed address, verifying the certificate against the host name."""

    def __init__(self, target: Target, timeout: float, context: ssl.SSLContext) -> None:
        super().__init__(target.host, target.port, timeout=timeout, context=context)
        self._address = target.address
        self._ctx = context

    def connect(self) -> None:
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._ctx.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTP(http.client.HTTPConnection):
    """Plain HTTP to a fixed address (only for hosts the operator allows)."""

    def __init__(self, target: Target, timeout: float) -> None:
        super().__init__(target.host, target.port, timeout=timeout)
        self._address = target.address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._address, self.port), self.timeout)


def socket_transport(request: HttpRequest, target: Target, timeout: float) -> HttpResponse:
    """The real network transport."""
    conn: http.client.HTTPConnection
    if target.scheme == "https":
        conn = _PinnedHTTPS(target, timeout, ssl.create_default_context())
    else:
        conn = _PinnedHTTP(target, timeout)
    deadline = time.monotonic() + timeout * DEADLINE_FACTOR
    try:
        conn.request(request.method, target.path, body=request.body, headers=dict(request.headers))
        response = conn.getresponse()
        chunks: list[bytes] = []
        size = 0
        while size <= MAX_BYTES:
            if time.monotonic() > deadline:
                raise TimeoutError("response took longer than the request deadline")
            chunk = response.read1(CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        headers = {k.lower(): v for k, v in response.getheaders()}
        return HttpResponse(response.status, headers, b"".join(chunks))
    finally:
        conn.close()


def _transient(response: HttpResponse) -> bool:
    """Worth retrying: 429, gateway errors, and 403 with an exhausted rate limit."""
    if response.status in RETRY_STATUSES:
        return True
    return response.status == 403 and response.headers.get("x-ratelimit-remaining") == "0"


def _retry_after(value: str | None) -> float | None:
    text = (value or "").strip()
    if text.isascii() and text.isdigit():
        return min(float(text), 300.0)
    return None


@dataclass
class HttpClient:
    """Requests with the outbound policy, timeouts, retries and limits."""

    policy: OutboundPolicy
    transport: Transport | None = None  # None: the real network, looked up at call time
    timeout: float = 30.0
    retries: int = 3
    backoff: float = 1.0
    max_bytes: int = MAX_BYTES
    read_only_posts: frozenset[str] = frozenset()
    sleep: Callable[[float], None] = time.sleep
    user_agent: str = f"dsec-metrics/{__version__}"
    requests_sent: int = field(default=0, init=False)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        action: str | None = None,
    ) -> HttpResponse:
        """Send one request, retrying transient failures. Raises CollectorError."""
        method = method.upper()
        if method == "POST":
            if action is None or action not in self.read_only_posts:
                raise CollectorError(
                    f"POST is allowed only for declared read actions, not {action}"
                )
        elif method != "GET":
            raise CollectorError(f"{method} is not allowed: collectors are read-only")
        for name, value in (headers or {}).items():
            if forbidden_header(name):
                raise CollectorError(f"header {name} cannot be set by a collector")
            if name.lower() == "x-amz-target" and value != action:
                raise CollectorError("x-amz-target must match the declared read action")
        if params:
            url = url + ("&" if "?" in url else "?") + urlencode(params, doseq=True)
        given = dict(headers or {})
        names = {k.lower() for k in given}
        defaults = {"User-Agent": self.user_agent, "Accept": "application/json"}
        all_headers = {k: v for k, v in defaults.items() if k.lower() not in names} | given
        transport = self.transport or socket_transport
        where = urlsplit(url)
        label = f"{where.hostname}{where.path}"
        for attempt in range(self.retries + 1):
            try:
                target = self.policy.check(url)
            except BlockedURL as exc:
                raise CollectorError(f"blocked: {exc}") from None
            try:
                self.requests_sent += 1
                response = transport(
                    HttpRequest(method, url, all_headers, body, action), target, self.timeout
                )
            except (OSError, http.client.HTTPException) as exc:
                # Certificate errors are OSErrors (and ValueErrors); they come first.
                if attempt == self.retries:
                    raise CollectorError(f"{label}: {type(exc).__name__}") from None
                self.sleep(self._delay(attempt, None))
                continue
            except ValueError:
                # http.client rejects control characters in headers with a message that
                # quotes the header, which may hold a secret. Say nothing about it.
                raise CollectorError(f"{label}: invalid request header") from None
            if len(response.body) > self.max_bytes:
                raise CollectorError(f"{label}: response larger than {self.max_bytes} bytes")
            if _transient(response) and attempt < self.retries:
                self.sleep(self._delay(attempt, response.headers.get("retry-after")))
                continue
            if 300 <= response.status < 400:
                raise CollectorError(f"{label}: HTTP {response.status}; redirects are not followed")
            if response.status >= 400:
                raise CollectorError(f"{label}: HTTP {response.status}")
            return response
        raise AssertionError("unreachable")  # pragma: no cover

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        asked = _retry_after(retry_after)
        if asked is not None:
            return asked
        return self.backoff * (2.0**attempt) * (1 + random.random() / 2)  # noqa: S311 (jitter)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        """GET and parse JSON."""
        return self.request("GET", url, **kwargs).json()


def next_link(link_header: str | None) -> str | None:
    """The ``rel="next"`` URL from an RFC 8288 Link header."""
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.split(";")
        if len(section) < 2:
            continue
        url = section[0].strip()
        if (
            url.startswith("<")
            and url.endswith(">")
            and any(s.strip().replace(" ", "") in ('rel="next"', "rel=next") for s in section[1:])
        ):
            return url[1:-1]
    return None


def dig(value: Any, path: str) -> Any:
    """Follow a dotted path (``data.items``) into parsed JSON; empty path returns ``value``."""
    for key in [p for p in path.split(".") if p]:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


class HttpCollectorConfig(CollectorConfig):
    """Settings every HTTP collector has."""

    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_pages: int = Field(default=100, ge=1)
    max_records: int = Field(default=100_000, ge=1)
    sensitive_fields: list[str] = Field(
        default_factory=list, description="More fields for redaction to drop"
    )


def default_policy() -> OutboundPolicy:
    """The operator's policy from settings."""
    settings = get_settings()
    return OutboundPolicy(
        allowed_hosts=settings.collector_allowed_host_list,
        allow_http_hosts=settings.collector_http_host_list,
    )


class HttpCollector(Collector):
    """Base for collectors that read HTTP APIs."""

    read_only_posts: ClassVar[frozenset[str]] = frozenset()

    config: HttpCollectorConfig

    def __init__(
        self,
        config: CollectorConfig,
        secrets: SecretResolver,
        http: HttpClient | None = None,
    ) -> None:
        super().__init__(config, secrets)
        self.http = http or HttpClient(
            default_policy(),
            timeout=getattr(config, "timeout_seconds", 30.0),
            read_only_posts=self.read_only_posts,
        )

    def use_transport(self, transport: Transport, policy: OutboundPolicy | None = None) -> None:
        """Swap the transport (tests replay fixtures through this)."""
        self.http = HttpClient(
            policy or self.http.policy,
            transport=transport,
            timeout=self.http.timeout,
            read_only_posts=self.read_only_posts,
            sleep=lambda _s: None,
        )

    # Pagination.

    def _check_limits(self, pages: int, records: int) -> None:
        if pages > self.config.max_pages:
            raise CollectorError(f"{self.name}: more than {self.config.max_pages} pages")
        if records > self.config.max_records:
            raise CollectorError(f"{self.name}: more than {self.config.max_records} records")

    def pages_by_link(
        self,
        url: str,
        records_path: str = "",
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[list[dict[str, Any]]]:
        """Follow ``Link: rel="next"`` headers. Next links must stay on the same host;
        ``params`` go on the first request only, since next links carry their own."""
        origin = _origin(url)
        pages = records = 0
        next_url: str | None = url
        query = params
        while next_url:
            response = self.http.request("GET", next_url, params=query, headers=headers)
            query = None
            items = _records(dig(response.json(), records_path))
            pages += 1
            records += len(items)
            self._check_limits(pages, records)
            yield items
            following = next_link(response.headers.get("link"))
            next_url = urljoin(next_url, following) if following else None
            if next_url and _origin(next_url) != origin:
                raise CollectorError(f"{self.name}: next page is on another host or port")

    def pages_by_offset(
        self,
        url: str,
        records_path: str,
        *,
        offset_param: str,
        limit_param: str,
        page_size: int,
        params: Mapping[str, Any] | None = None,
        total_path: str | None = None,
        headers: Mapping[str, str] | None = None,
        start: int = 0,
    ) -> Iterator[list[dict[str, Any]]]:
        """Offset and limit paging, stopping on a short page or at ``total_path``."""
        offset = start
        pages = records = 0
        while True:
            data = self.http.get_json(
                url,
                params={**(params or {}), offset_param: offset, limit_param: page_size},
                headers=headers,
            )
            items = _records(dig(data, records_path))
            pages += 1
            records += len(items)
            self._check_limits(pages, records)
            yield items
            total = dig(data, total_path) if total_path else None
            offset += len(items)
            done = len(items) < page_size or (isinstance(total, int) and offset - start >= total)
            if done or not items:
                return

    def pages_by_cursor(
        self,
        url: str,
        records_path: str,
        *,
        cursor_path: str,
        cursor_param: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[list[dict[str, Any]]]:
        """Cursor paging: the response names the next cursor; stop when it is empty."""
        cursor: str | None = None
        pages = records = 0
        while True:
            query = dict(params or {})
            if cursor:
                query[cursor_param] = cursor
            data = self.http.get_json(url, params=query, headers=headers)
            items = _records(dig(data, records_path))
            pages += 1
            records += len(items)
            self._check_limits(pages, records)
            yield items
            nxt = dig(data, cursor_path)
            if not nxt or nxt == cursor:
                return
            cursor = str(nxt)


def path_segment(value: Any) -> str:
    """A value from a response, made safe to put in a URL path as one segment."""
    text = str(value)
    if text in {"", ".", ".."}:
        raise CollectorError("a path segment from the response is empty or a dot segment")
    return quote(text, safe="")


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError:
        port = None
    return scheme, (parts.hostname or "").rstrip("."), port


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise CollectorError("expected a list of objects in the response")
    return value
