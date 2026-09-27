from __future__ import annotations

from dsec_metrics.auth.tokens import new_token, token_hash, tokens_equal


def test_tokens_are_long_and_unique() -> None:
    tokens = {new_token() for _ in range(100)}
    assert len(tokens) == 100
    assert all(len(t) >= 43 for t in tokens)


def test_token_hash_is_sha256() -> None:
    assert len(token_hash("abc")) == 32
    assert token_hash("abc") == token_hash("abc")
    assert token_hash("abc") != token_hash("abd")


def test_tokens_equal() -> None:
    assert tokens_equal("same", "same")
    assert not tokens_equal("same", "diff")
