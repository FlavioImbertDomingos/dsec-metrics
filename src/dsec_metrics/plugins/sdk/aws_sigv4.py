"""AWS Signature Version 4, standard library only.

Covers what the ``aws`` collector sends: GET with a query string (Query APIs such as
IAM) and POST with a JSON body (JSON APIs such as KMS). Reference:
https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_sigv-create-signed-request.html
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote, unquote_plus, urlsplit

ALGORITHM = "AWS4-HMAC-SHA256"


@dataclass(frozen=True)
class Credentials:
    """An access key. ``session_token`` is set for temporary credentials."""

    access_key_id: str
    secret_access_key: str
    session_token: str | None = None


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _uri_encode(value: str, safe: str = "-_.~") -> str:
    return quote(value, safe=safe)


def canonical_query(query: str) -> str:
    """Sort parameters by name then value, each URI-encoded."""
    if not query:
        return ""
    pairs = []
    for part in query.split("&"):
        name, _, value = part.partition("=")
        pairs.append((_uri_encode(_unquote(name)), _uri_encode(_unquote(value))))
    return "&".join(f"{n}={v}" for n, v in sorted(pairs))


def _unquote(value: str) -> str:
    return unquote_plus(value)


def _host_header(scheme: str, hostname: str, port: int | None) -> str:
    """The Host header http.client sends: lower case, no default port."""
    host = hostname.lower().rstrip(".")
    if ":" in host:
        host = f"[{host}]"
    default = 443 if scheme.lower() == "https" else 80
    return host if port in (None, default) else f"{host}:{port}"


def sign(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    credentials: Credentials,
    region: str,
    service: str,
    now: datetime | None = None,
) -> dict[str, str]:
    """Return the headers to send, with ``Authorization`` and the date headers added."""
    when = (now or datetime.now(UTC)).astimezone(UTC)
    amz_date = when.strftime("%Y%m%dT%H%M%SZ")
    day = when.strftime("%Y%m%d")
    parts = urlsplit(url)
    host = _host_header(parts.scheme, parts.hostname or "", parts.port)
    out = {**headers, "host": host, "x-amz-date": amz_date}
    if credentials.session_token:
        out["x-amz-security-token"] = credentials.session_token
    lowered = {k.lower().strip(): " ".join(str(v).split()) for k, v in out.items()}
    signed = sorted(lowered)
    canonical_headers = "".join(f"{k}:{lowered[k]}\n" for k in signed)
    signed_headers = ";".join(signed)
    path = _uri_encode(parts.path or "/", safe="/-_.~")
    payload_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join(
        [
            method.upper(),
            path,
            canonical_query(parts.query),
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(
        [ALGORITHM, amz_date, scope, hashlib.sha256(canonical.encode("utf-8")).hexdigest()]
    )
    key = _hmac(("AWS4" + credentials.secret_access_key).encode("utf-8"), day)
    for piece in (region, service, "aws4_request"):
        key = _hmac(key, piece)
    signature = hmac.new(key, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    result = {k: v for k, v in out.items() if k != "host"}
    result["Authorization"] = (
        f"{ALGORITHM} Credential={credentials.access_key_id}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return result
