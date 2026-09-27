from __future__ import annotations

import socket

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dsec_metrics.plugins.sdk.ssrf import (
    BlockedURL,
    OutboundPolicy,
    address_allowed,
    host_matches,
    system_resolver,
)


def policy(address: str | list[str] = "203.0.113.10", **kwargs: tuple[str, ...]) -> OutboundPolicy:
    addresses = [address] if isinstance(address, str) else address
    return OutboundPolicy(
        allowed_hosts=kwargs.get("allowed", ("api.example.test", "*.corp.example.test")),
        allow_http_hosts=kwargs.get("http", ()),
        resolver=lambda _host, _port: addresses,
    )


def test_allowed_url_is_pinned_to_the_checked_address() -> None:
    target = policy().check("https://API.example.test./v1/items?page=2")
    assert (target.scheme, target.host, target.port) == ("https", "api.example.test", 443)
    assert target.address == "203.0.113.10"
    assert target.path == "/v1/items?page=2"
    assert policy().check("https://api.example.test").path == "/"
    assert policy().check("https://api.example.test:8443/x").port == 8443


def test_private_ranges_are_allowed_because_internal_apis_live_there() -> None:
    for address in ("10.1.2.3", "172.16.0.5", "192.168.1.1", "fd12:3456::1"):
        assert policy(address).check("https://api.example.test/").address == address


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("https://other.example.test/", "not in the collector host allowlist"),
        ("https://corp.example.test/", "not in the collector host allowlist"),
        ("http://api.example.test/", "plain HTTP"),
        ("ftp://api.example.test/", "scheme ftp"),
        ("file:///etc/passwd", "no host"),
        ("//api.example.test/", "scheme none"),
        ("https://user:pw@api.example.test/", "credentials in URLs"),
        ("https://api.example.test:99999/", "invalid port"),
        ("https://metadata.google.internal/", "metadata endpoint"),
        ("https://169.254.169.254/latest/", "metadata endpoint"),
    ],
)
def test_refusals(url: str, reason: str) -> None:
    with pytest.raises(BlockedURL, match=reason):
        policy().check(url)


def test_metadata_names_are_refused_even_when_allowlisted() -> None:
    p = policy(allowed=("metadata.google.internal",))
    with pytest.raises(BlockedURL, match="metadata"):
        p.check("https://metadata.google.internal/computeMetadata/v1/")


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "127.9.9.9",
        "::1",
        "169.254.169.254",
        "169.254.1.1",
        "fe80::1",
        "fe80::1%eth0",
        "0.0.0.0",  # noqa: S104 (an address under test, not a bind)
        "0.1.2.3",
        "::",
        "224.0.0.1",
        "ff02::1",
        "240.0.0.1",
        "255.255.255.255",
        "100.64.0.1",
        "100.100.100.200",
        "fd00:ec2::254",
        "fec0::1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "2002:7f00:1::",
        "2002:a9fe:a9fe::1",
        "64:ff9b::a9fe:a9fe",
        "64:ff9b::7f00:1",
        "2001:0:4136:e378:8000:63bf:80ff:fffe",
    ],
)
def test_blocked_addresses(address: str) -> None:
    assert not address_allowed(address)
    with pytest.raises(BlockedURL, match="blocked address"):
        policy(address).check("https://api.example.test/")


def test_one_bad_address_among_several_blocks_the_name() -> None:
    with pytest.raises(BlockedURL, match="blocked address"):
        policy(["203.0.113.10", "127.0.0.1"]).check("https://api.example.test/")


def test_resolution_failures() -> None:
    with pytest.raises(BlockedURL, match="cannot resolve"):
        policy([]).check("https://api.example.test/")
    with pytest.raises(BlockedURL, match="not an address"):
        policy("not-an-ip").check("https://api.example.test/")


def test_plain_http_only_for_named_hosts() -> None:
    p = policy(http=("localstack.test",), allowed=("localstack.test",))
    target = p.check("http://localstack.test:4566/")
    assert (target.scheme, target.port) == ("http", 4566)
    assert (
        policy(allowed=("a.example.test",), http=("a.example.test",))
        .check("http://a.example.test/")
        .port
        == 80
    )


def test_empty_allowlist_allows_nothing() -> None:
    with pytest.raises(BlockedURL, match="allowlist"):
        OutboundPolicy(resolver=lambda _h, _p: ["203.0.113.10"]).check("https://a.example.test/")


def test_host_patterns() -> None:
    patterns = ["api.example.test", "*.corp.example.test", " ", "Upper.Example.Test."]
    assert host_matches("api.example.test", patterns)
    assert host_matches("a.b.corp.example.test", patterns)
    assert host_matches("upper.example.test", patterns)
    assert not host_matches("corp.example.test", patterns)
    assert not host_matches("evilcorp.example.test", patterns)
    assert not host_matches("api.example.test.evil.test", patterns)
    assert not host_matches("anything", [])


@given(st.ip_addresses())
def test_address_check_never_raises_for_real_addresses(ip: object) -> None:
    assert isinstance(address_allowed(str(ip)), bool)


def test_system_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(host: str, port: int, **_kwargs: object) -> list[tuple[object, ...]]:
        assert (host, port) == ("api.example.test", 443)
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.10", 443)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.10", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    assert system_resolver("api.example.test", 443) == ["2001:db8::1", "203.0.113.10"]

    def fails(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        raise socket.gaierror("no such name")

    monkeypatch.setattr(socket, "getaddrinfo", fails)
    with pytest.raises(BlockedURL, match="cannot resolve"):
        system_resolver("nothing.example.test", 443)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test\\.api.example.test/",
        "https://api.example.test%2f/",
        "https://[fe80::1%25eth0]/",
        "https://api example.test/",
    ],
)
def test_odd_host_names_are_refused(url: str) -> None:
    with pytest.raises(BlockedURL):
        policy(allowed=("*.example.test", "api.example.test")).check(url)


def test_underscores_in_internal_names_are_allowed() -> None:
    assert policy(allowed=("svc_a.corp.example.test",)).check("https://svc_a.corp.example.test/")


def test_legacy_metadata_address_is_blocked() -> None:
    assert not address_allowed("192.0.0.192")
