"""SigV4 against AWS's published test suite and documentation examples."""

from __future__ import annotations

from datetime import UTC, datetime

from dsec_metrics.plugins.sdk.aws_sigv4 import Credentials, canonical_query, sign

# The example credentials from the AWS SigV4 test suite (not a real key).
SUITE = Credentials("AKIDEXAMPLE", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY")
WHEN = datetime(2015, 8, 30, 12, 36, tzinfo=UTC)


def signature(headers: dict[str, str]) -> str:
    return headers["Authorization"].rsplit("Signature=", 1)[1]


def test_get_vanilla() -> None:
    out = sign(
        "GET", "https://example.amazonaws.com/", {}, b"", SUITE, "us-east-1", "service", WHEN
    )
    assert out["x-amz-date"] == "20150830T123600Z"
    assert out["Authorization"].startswith(
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
        "SignedHeaders=host;x-amz-date, "
    )
    assert signature(out) == "5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
    assert "host" not in out


def test_get_vanilla_query_order_key_case() -> None:
    out = sign(
        "GET",
        "https://example.amazonaws.com/?Param2=value2&Param1=value1",
        {},
        b"",
        SUITE,
        "us-east-1",
        "service",
        WHEN,
    )
    assert signature(out) == "b97d918cfa904a5beff61c982a1b6f458b799221646efd99d3219ec94cdf2500"


def test_iam_list_users_documentation_example() -> None:
    out = sign(
        "GET",
        "https://iam.amazonaws.com/?Action=ListUsers&Version=2010-05-08",
        {"content-type": "application/x-www-form-urlencoded; charset=utf-8"},
        b"",
        SUITE,
        "us-east-1",
        "iam",
        WHEN,
    )
    assert "SignedHeaders=content-type;host;x-amz-date," in out["Authorization"]
    assert signature(out) == "5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7"


def test_session_token_is_sent_and_signed() -> None:
    temporary = Credentials("AKIDEXAMPLE", SUITE.secret_access_key, "session-token-example")
    out = sign("POST", "https://kms.test/", {}, b"{}", temporary, "eu-west-1", "kms", WHEN)
    assert out["x-amz-security-token"] == "session-token-example"
    assert "SignedHeaders=host;x-amz-date;x-amz-security-token," in out["Authorization"]


def test_canonical_query_sorts_and_encodes() -> None:
    assert canonical_query("") == ""
    assert canonical_query("b=2&a=1&a=0") == "a=0&a=1&b=2"
    assert canonical_query("Marker=a%2Fb+c&x=~_-.") == "Marker=a%2Fb%20c&x=~_-."
    assert canonical_query("flag") == "flag="


def test_signature_changes_with_every_input() -> None:
    def sig(
        body: bytes = b"{}",
        region: str = "eu-west-1",
        service: str = "kms",
        target: str = "A",
    ) -> str:
        headers = {"x-amz-target": target}
        return signature(
            sign("POST", "https://kms.test/", headers, body, SUITE, region, service, WHEN)
        )

    first = sig()
    assert first == sig()
    assert len({first, sig(body=b"{ }"), sig(region="eu-west-2"), sig(service="acm")}) == 4
    assert sig(target="B") != first


def test_host_is_signed_as_http_client_sends_it() -> None:
    vanilla = signature(
        sign("GET", "https://example.amazonaws.com/", {}, b"", SUITE, "us-east-1", "service", WHEN)
    )
    for url in ("https://Example.AmazonAWS.com:443/", "https://example.amazonaws.com./"):
        out = sign("GET", url, {}, b"", SUITE, "us-east-1", "service", WHEN)
        assert signature(out) == vanilla
    other_port = sign("GET", "http://localstack.test:4566/", {}, b"", SUITE, "r", "s", WHEN)
    assert other_port["Authorization"] != vanilla
