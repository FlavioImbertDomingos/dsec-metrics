from __future__ import annotations

import json

from hypothesis import given
from hypothesis import strategies as st

from dsec_metrics.core.redaction import luhn_valid, mask_pan, redact_records

# Well-known test card numbers (not real accounts).
VISA = "4111111111111111"
AMEX = "378282246310005"
MC = "5555555555554444"


def make_luhn(prefix: str, length: int) -> str:
    body = prefix + "0" * (length - len(prefix) - 1)
    for check in "0123456789":
        if luhn_valid(body + check):
            return body + check
    raise AssertionError


def test_luhn() -> None:
    assert luhn_valid(VISA)
    assert luhn_valid(AMEX)
    assert not luhn_valid("4111111111111112")


def test_masks_in_text_numbers_and_nested_values() -> None:
    records = [
        {
            "note": f"card {VISA} and {AMEX[:4]} {AMEX[4:10]} {AMEX[10:]} on file",
            "pan": int(MC),
            "nested": {"list": [f"x-{MC}-y", {"deep": VISA}]},
            "order_id": "20260101000000123",  # 17 digits, fails Luhn: kept
        }
    ]
    out, summary = redact_records(records)
    text = json.dumps(out)
    for pan in (VISA, AMEX, MC):
        assert pan not in text
    assert "411111******1111" in text
    assert "378282*****0005" in text
    assert out[0]["pan"] == "555555******4444"
    assert out[0]["order_id"] == "20260101000000123"
    assert summary.pans_masked == 5
    assert records[0]["pan"] == int(MC)  # input untouched


def test_drops_sensitive_fields_global_and_collector_specific() -> None:
    out, summary = redact_records(
        [{"CVV": "123", "Track-2": "x", "api_token": "t", "keep": 1}],
        sensitive_fields=["api_token"],
    )
    assert out == [{"keep": 1}]
    assert summary.as_dict()["fields_dropped"] == {"CVV": 1, "Track-2": 1, "api_token": 1}


def test_short_and_long_digit_runs_are_kept() -> None:
    twelve = make_luhn("4", 12)
    twenty = make_luhn("4", 20)
    out, summary = redact_records([{"a": twelve, "b": twenty, "c": True}])
    assert out == [{"a": twelve, "b": twenty, "c": True}]
    assert summary.pans_masked == 0


@given(
    length=st.integers(min_value=13, max_value=19),
    prefix=st.sampled_from(["4", "51", "37", "6011", "35"]),
    sep=st.sampled_from(["", " ", "-"]),
    before=st.text(alphabet="abc ,:", max_size=5),
    after=st.text(alphabet="abc ,:", max_size=5),
)
def test_any_luhn_valid_pan_is_masked(
    length: int, prefix: str, sep: str, before: str, after: str
) -> None:
    pan = make_luhn(prefix, length)
    shown = sep.join(pan[i : i + 4] for i in range(0, len(pan), 4))
    out, summary = redact_records([{"v": f"{before}{shown}{after}"}])
    assert pan not in json.dumps(out).replace(" ", "").replace("-", "")
    assert mask_pan(pan) in out[0]["v"]
    assert summary.pans_masked == 1


def test_masks_keys_and_whole_number_floats() -> None:
    records, summary = redact_records(
        [{"by_card": {VISA: {"seen": 2}}, "amount": float(MC), "ratio": 0.5}]
    )
    assert records == [
        {"by_card": {"411111******1111": {"seen": 2}}, "amount": "555555******4444", "ratio": 0.5}
    ]
    assert summary.pans_masked == 2
