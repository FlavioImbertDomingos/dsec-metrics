from __future__ import annotations

import datetime as dt
import http.client
import json
import ssl
import threading
from collections.abc import Iterator
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from dsec_metrics.config import get_settings
from dsec_metrics.plugins.sdk.base import CollectorError, ConnectionResult, RecordBatch
from dsec_metrics.plugins.sdk.http import (
    HttpClient,
    HttpCollector,
    HttpCollectorConfig,
    HttpRequest,
    HttpResponse,
    default_policy,
    dig,
    next_link,
    socket_transport,
)
from dsec_metrics.plugins.sdk.secrets import SecretResolver
from dsec_metrics.plugins.sdk.ssrf import OutboundPolicy, Target
from dsec_metrics.plugins.sdk.testing import FixtureTransport, fixture_policy

POLICY = fixture_policy("api.example.test")
BASE = "https://api.example.test"


class Scripted:
    """A transport that answers from a list and records what it was asked."""

    def __init__(self, *replies: HttpResponse | Exception) -> None:
        self.replies = list(replies)
        self.requests: list[tuple[HttpRequest, Target]] = []

    def __call__(self, request: HttpRequest, target: Target, timeout: float) -> HttpResponse:
        del timeout
        self.requests.append((request, target))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def ok(body: Any = None, status: int = 200, **headers: str) -> HttpResponse:
    return HttpResponse(status, headers, json.dumps(body if body is not None else {}).encode())


def client(transport: Scripted, **kwargs: Any) -> tuple[HttpClient, list[float]]:
    slept: list[float] = []
    return HttpClient(POLICY, transport=transport, sleep=slept.append, **kwargs), slept


def test_get_sends_defaults_and_params() -> None:
    t = Scripted(ok({"a": 1}))
    c, _ = client(t)
    assert c.get_json(f"{BASE}/x?fixed=1", params={"q": "a b", "list": [1, 2]}) == {"a": 1}
    request, target = t.requests[0]
    assert request.url == f"{BASE}/x?fixed=1&q=a+b&list=1&list=2"
    assert target.address == "203.0.113.10"
    assert request.headers["Accept"] == "application/json"
    assert request.headers["User-Agent"].startswith("dsec-metrics/")


def test_given_headers_replace_defaults_whatever_their_case() -> None:
    t = Scripted(ok())
    c, _ = client(t)
    c.request("GET", BASE, headers={"accept": "application/vnd.x+json"})
    headers = t.requests[0][0].headers
    assert [k for k in headers if k.lower() == "accept"] == ["accept"]


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def test_write_methods_are_refused_before_sending(method: str) -> None:
    t = Scripted()
    c, _ = client(t)
    with pytest.raises(CollectorError, match="read-only"):
        c.request(method, BASE)
    assert t.requests == []


def test_post_only_for_declared_read_actions() -> None:
    t = Scripted(ok({"Keys": []}))
    c, _ = client(t, read_only_posts=frozenset({"Svc.List"}))
    with pytest.raises(CollectorError, match="declared read actions"):
        c.request("POST", BASE, body=b"{}")
    with pytest.raises(CollectorError, match="declared read actions"):
        c.request("POST", BASE, body=b"{}", action="Svc.Delete")
    assert c.request("POST", BASE, body=b"{}", action="Svc.List").json() == {"Keys": []}
    assert t.requests[0][0].action == "Svc.List"


def test_blocked_urls_never_reach_the_transport() -> None:
    t = Scripted()
    c, _ = client(t)
    with pytest.raises(CollectorError, match=r"blocked: .*allowlist"):
        c.request("GET", "https://elsewhere.example.test/")
    assert t.requests == []


def test_retries_transient_failures_with_backoff() -> None:
    t = Scripted(
        OSError("reset"),
        ok(status=503),
        ok(status=429, **{"retry-after": "7"}),
        ok(status=403, **{"x-ratelimit-remaining": "0"}),
        ok({"done": True}),
    )
    c, slept = client(t, retries=4, backoff=0.5)
    assert c.get_json(BASE) == {"done": True}
    assert c.requests_sent == 5
    assert 0.5 <= slept[0] <= 0.75
    assert 1.0 <= slept[1] <= 1.5
    assert slept[2] == 7
    assert 4.0 <= slept[3] <= 6.0


def test_retry_after_is_capped_and_dates_are_ignored() -> None:
    t = Scripted(ok(status=429, **{"retry-after": "9999"}), ok(status=429, **{"retry-after": "x"}))
    t.replies.append(ok())
    c, slept = client(t, retries=2, backoff=1)
    c.get_json(BASE)
    assert slept[0] == 300
    assert 2 <= slept[1] <= 3


def test_gives_up_after_the_last_attempt() -> None:
    c, _ = client(Scripted(ok(status=502), ok(status=502)), retries=1)
    with pytest.raises(CollectorError, match="HTTP 502"):
        c.get_json(BASE)
    c, _ = client(Scripted(TimeoutError(), http.client.RemoteDisconnected("closed")), retries=1)
    with pytest.raises(CollectorError, match="RemoteDisconnected"):
        c.get_json(BASE)


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (ok(status=302, location="https://elsewhere.example.test/"), "redirects are not followed"),
        (ok(status=404), "HTTP 404"),
        (ok(status=403), "HTTP 403"),
        (HttpResponse(200, {}, b"<html>"), "not JSON"),
        (HttpResponse(200, {}, b"x" * 101), "larger than 100 bytes"),
    ],
)
def test_errors_do_not_retry(reply: HttpResponse, message: str) -> None:
    t = Scripted(reply)
    c, _ = client(t, max_bytes=100)
    with pytest.raises(CollectorError, match=message):
        c.get_json(f"{BASE}/secret-path?token=abc")
    assert len(t.requests) == 1


def test_error_messages_leave_out_the_query_string() -> None:
    c, _ = client(Scripted(ok(status=401)))
    with pytest.raises(CollectorError) as info:
        c.get_json(f"{BASE}/items?api_key=abc")
    assert "abc" not in str(info.value)
    assert "api.example.test/items" in str(info.value)


def test_next_link_and_dig() -> None:
    header = '<https://a.test/p?page=3>; rel="last", <https://a.test/p?page=2>; rel="next"'
    assert next_link(header) == "https://a.test/p?page=2"
    assert next_link("<https://a.test/n>; rel=next") == "https://a.test/n"
    assert next_link('<https://a.test/p>; rel="prev"') is None
    assert next_link("garbage") is None
    assert next_link(None) is None
    assert dig({"a": {"b": [1]}}, "a.b") == [1]
    assert dig({"a": 1}, "") == {"a": 1}
    assert dig({"a": 1}, "a.b") is None


# The collector base class.


class DemoConfig(HttpCollectorConfig):
    pass


class Demo(HttpCollector):
    name = "demo"
    version = "1.0.0"
    config_model = DemoConfig
    queries: ClassVar[dict[str, str]] = {"x": "x"}
    required_permissions: ClassVar[list[str]] = ["read"]

    def test_connection(self) -> ConnectionResult:
        return ConnectionResult(ok=True)

    def collect(self, query: str, params: dict[str, Any], as_of: date) -> Iterator[RecordBatch]:
        raise NotImplementedError


def demo(routes: dict[str, Any], **config: Any) -> tuple[Demo, FixtureTransport]:
    collector = Demo(DemoConfig(**config), SecretResolver({}))
    transport = FixtureTransport(routes)
    collector.use_transport(transport, POLICY)
    return collector, transport


def test_default_client_uses_the_operator_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DSEC_COLLECTOR_ALLOWED_HOSTS", "api.example.test, *.corp.example.test,")
    monkeypatch.setenv("DSEC_COLLECTOR_ALLOW_HTTP_HOSTS", "localstack.test")
    get_settings.cache_clear()
    try:
        policy = default_policy()
        collector = Demo(DemoConfig(timeout_seconds=5), SecretResolver({}))
    finally:
        get_settings.cache_clear()
    assert policy.allowed_hosts == ("api.example.test", "*.corp.example.test")
    assert policy.allow_http_hosts == ("localstack.test",)
    assert collector.http.timeout == 5
    assert collector.http.transport is None


def test_link_pagination_stays_on_the_host() -> None:
    collector, transport = demo(
        {
            "GET /items?state=open": (
                {"data": [{"n": 1}]},
                {"Link": '</items?page=2>; rel="next"'},
            ),
            "GET /items?page=2": {"data": [{"n": 2}]},
        }
    )
    pages = list(collector.pages_by_link(f"{BASE}/items", "data", params={"state": "open"}))
    assert pages == [[{"n": 1}], [{"n": 2}]]
    assert len(transport.requests) == 2

    collector, _ = demo(
        {"GET /items": ([], {"link": '<https://elsewhere.example.test/items>; rel="next"'})}
    )
    with pytest.raises(CollectorError, match="another host"):
        list(collector.pages_by_link(f"{BASE}/items"))


def test_offset_pagination() -> None:
    collector, _ = demo(
        {
            "GET /t?q=1&offset=0&limit=2": {"rows": [{"i": 0}, {"i": 1}], "total": 3},
            "GET /t?q=1&offset=2&limit=2": {"rows": [{"i": 2}], "total": 3},
        }
    )
    pages = collector.pages_by_offset(
        f"{BASE}/t", "rows", offset_param="offset", limit_param="limit", page_size=2,
        params={"q": 1}, total_path="total",
    )  # fmt: skip
    assert [len(p) for p in pages] == [2, 1]
    collector, _ = demo(
        {
            "GET /t?offset=0&limit=1": {"rows": [{"i": 0}], "total": 2},
            "GET /t?offset=1&limit=1": {"rows": [{"i": 1}], "total": 2},
        }
    )
    pages = collector.pages_by_offset(
        f"{BASE}/t", "rows", offset_param="offset", limit_param="limit", page_size=1,
        total_path="total",
    )  # fmt: skip
    assert [len(p) for p in pages] == [1, 1]


def test_cursor_pagination_stops_on_empty_or_repeated_cursor() -> None:
    collector, _ = demo(
        {
            "GET /c": {"items": [{"i": 1}], "next": "abc"},
            "GET /c?cursor=abc": {"items": [{"i": 2}], "next": "abc"},
        }
    )
    pages = list(
        collector.pages_by_cursor(f"{BASE}/c", "items", cursor_path="next", cursor_param="cursor")
    )
    assert pages == [[{"i": 1}], [{"i": 2}]]


def test_page_and_record_limits() -> None:
    routes = {
        "GET /c": {"items": [{"i": 1}, {"i": 2}], "next": "p2"},
        "GET /c?cursor=p2": {"items": [{"i": 3}], "next": "p3"},
    }
    collector, _ = demo(routes, max_pages=1)
    with pytest.raises(CollectorError, match="more than 1 pages"):
        list(
            collector.pages_by_cursor(
                f"{BASE}/c", "items", cursor_path="next", cursor_param="cursor"
            )
        )
    collector, _ = demo(routes, max_records=2)
    with pytest.raises(CollectorError, match="more than 2 records"):
        list(
            collector.pages_by_cursor(
                f"{BASE}/c", "items", cursor_path="next", cursor_param="cursor"
            )
        )


def test_records_must_be_a_list_of_objects() -> None:
    collector, _ = demo({"GET /c": {"items": [1, 2]}})
    with pytest.raises(CollectorError, match="list of objects"):
        list(
            collector.pages_by_cursor(
                f"{BASE}/c", "items", cursor_path="next", cursor_param="cursor"
            )
        )
    collector, _ = demo({"GET /c": {}})
    assert list(
        collector.pages_by_cursor(f"{BASE}/c", "items", cursor_path="n", cursor_param="c")
    ) == [[]]


def test_fixture_transport(tmp_path: Path) -> None:
    body = tmp_path / "b.json"
    body.write_text('{"from": "file"}', encoding="utf-8")
    transport = FixtureTransport(
        {
            "GET /f": body,
            "GET /b": b'{"raw": true}',
            "GET /s": (500, {"e": 1}, {"X-A": "1"}),
            "POST / Svc.Get": lambda request: {"echo": json.loads(request.body or b"{}")},
        }
    )
    c = HttpClient(POLICY, transport=transport, retries=0, read_only_posts=frozenset({"Svc.Get"}))
    assert c.get_json(f"{BASE}/f") == {"from": "file"}
    assert c.get_json(f"{BASE}/b") == {"raw": True}
    with pytest.raises(CollectorError, match="HTTP 500"):
        c.get_json(f"{BASE}/s")
    assert c.request("POST", BASE, body=b'{"k": 1}', action="Svc.Get").json() == {"echo": {"k": 1}}
    with pytest.raises(AssertionError, match="no recorded response for GET /missing"):
        c.get_json(f"{BASE}/missing")


# The real transport, against local servers.


class Handler(BaseHTTPRequestHandler):
    seen: ClassVar[list[tuple[str, str, str | None]]] = []

    def do_GET(self) -> None:
        Handler.seen.append((self.command, self.path, self.headers.get("Host")))
        payload = b'{"hello": "world"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        del format, args


@pytest.fixture
def server() -> Iterator[HTTPServer]:
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_socket_transport_connects_to_the_checked_address(server: HTTPServer) -> None:
    port = server.server_address[1]
    target = Target("http", "api.example.test", port, "127.0.0.1", "/v1/x?y=1")
    request = HttpRequest("GET", "http://api.example.test/v1/x?y=1", {"Accept": "application/json"})
    response = socket_transport(request, target, 5)
    assert response.status == 200
    assert response.json() == {"hello": "world"}
    assert response.headers["content-type"] == "application/json"
    assert Handler.seen[-1] == ("GET", "/v1/x?y=1", f"api.example.test:{port}")


def test_https_verifies_the_certificate_against_the_host_name(tmp_path: Path) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "api.example.test")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("api.example.test")]), False)
        .sign(key, hashes.SHA256())
    )
    (tmp_path / "c.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "k.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / "c.pem", tmp_path / "k.pem")
    srv.socket = context.wrap_socket(srv.socket, server_side=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        target = Target("https", "api.example.test", srv.server_address[1], "127.0.0.1", "/")
        request = HttpRequest("GET", "https://api.example.test/", {})
        with pytest.raises(ssl.SSLCertVerificationError):
            socket_transport(request, target, 5)
        # The client's own error handling turns it into a CollectorError without retrying.
        c = HttpClient(
            OutboundPolicy(("api.example.test",), resolver=lambda _h, _p: ["203.0.113.10"]),
            transport=lambda r, _t, timeout: socket_transport(r, target, timeout),
            retries=0,
        )
        with pytest.raises(CollectorError, match="SSLCertVerificationError"):
            c.get_json("https://api.example.test/")
    finally:
        srv.shutdown()
        srv.server_close()
