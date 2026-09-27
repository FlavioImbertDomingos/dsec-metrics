"""Helpers for collector contract tests. CI never calls live services."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode

from dsec_metrics.plugins.sdk.base import Collector, RecordBatch
from dsec_metrics.plugins.sdk.http import HttpRequest, HttpResponse
from dsec_metrics.plugins.sdk.ssrf import OutboundPolicy, Target


def check_collector_class(cls: type[Collector]) -> None:
    """Assert the class declares everything the platform and the docs rely on."""
    for attr in ("name", "version", "config_model", "queries", "required_permissions"):
        if not hasattr(cls, attr):
            raise AssertionError(f"{cls.__name__} is missing {attr}")
    if not cls.queries:
        raise AssertionError(f"{cls.__name__} declares no queries")
    for description in cls.queries.values():
        if not description.strip():
            raise AssertionError(f"{cls.__name__} has a query without a description")


def collect_all(collector: Collector, query: str, as_of: date, **params: Any) -> list[RecordBatch]:
    """Run a query and check every batch is JSON-serializable and labelled correctly."""
    batches = list(collector.collect(query, dict(params), as_of))
    for batch in batches:
        if batch.query != query:
            raise AssertionError(f"batch labelled {batch.query!r}, expected {query!r}")
        json.dumps(batch.records, allow_nan=False)
    return batches


FixtureBody = Path | bytes | dict[str, Any] | list[Any]
FixtureReply = (
    FixtureBody | tuple[FixtureBody, Mapping[str, str]] | tuple[int, FixtureBody, Mapping[str, str]]
)
FixtureRoute = FixtureReply | Callable[[HttpRequest], FixtureReply]


def _route_key(method: str, path_and_query: str, action: str | None = None) -> str:
    path, _, query = path_and_query.partition("?")
    pairs = sorted(parse_qsl(query, keep_blank_values=True))
    key = f"{method.upper()} {path}" + (f"?{urlencode(pairs)}" if pairs else "")
    return f"{key} {action}" if action else key


class FixtureTransport:
    """Replays recorded HTTP responses for contract tests, so CI never calls a live service.

    Keys are ``"METHOD /path?query"``, with query order ignored. Requests sent with a
    read action (AWS JSON APIs, which POST to ``/``) add it: ``"POST / TrentService.ListKeys"``.
    A value is a body (a path to a fixture file, bytes, or JSON data), ``(body, headers)``,
    ``(status, body, headers)``, or a function of the request returning one of those.
    A request with no recorded response fails the test. Every request is kept in
    ``requests``.
    """

    def __init__(self, routes: Mapping[str, FixtureRoute]) -> None:
        self.routes: dict[str, FixtureRoute] = {}
        for key, route in routes.items():
            method, _, rest = key.partition(" ")
            path, _, action = rest.partition(" ")
            self.routes[_route_key(method, path, action or None)] = route
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest, target: Target, timeout: float) -> HttpResponse:
        del timeout
        self.requests.append(request)
        key = _route_key(request.method, target.path, request.action)
        if key not in self.routes:
            raise AssertionError(f"no recorded response for {key}")
        route = self.routes[key]
        reply = route(request) if callable(route) else route
        status: int = 200
        headers: Mapping[str, str] = {}
        body: FixtureBody
        if isinstance(reply, tuple) and len(reply) == 3:
            status, body, headers = reply
        elif isinstance(reply, tuple):
            body, headers = reply
        else:
            body = reply
        if isinstance(body, Path):
            data = body.read_bytes()
        elif isinstance(body, bytes):
            data = body
        else:
            data = json.dumps(body).encode("utf-8")
        return HttpResponse(status, {k.lower(): v for k, v in headers.items()}, data)


def fixture_policy(*hosts: str, address: str = "203.0.113.10") -> OutboundPolicy:
    """An outbound policy for contract tests: the given hosts, resolved to a documentation
    address without touching DNS."""
    return OutboundPolicy(allowed_hosts=hosts, resolver=lambda _host, _port: [address])
