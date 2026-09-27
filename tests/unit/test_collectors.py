from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from dsec_metrics.plugins.collectors.file import FileCollector, FileConfig
from dsec_metrics.plugins.collectors.sample import (
    CONTROL_IDS,
    SampleCollector,
    SampleConfig,
    month_ends,
)
from dsec_metrics.plugins.sdk import CollectorError, SecretError, SecretResolver
from dsec_metrics.plugins.sdk.registry import (
    COLLECTORS,
    RENDERERS,
    PluginError,
    collector_class,
    default_secret_resolver,
    plugin_names,
    renderer_class,
)
from dsec_metrics.plugins.sdk.testing import check_collector_class, collect_all
from dsec_metrics.plugins.secrets.env import EnvSecretProvider
from dsec_metrics.plugins.secrets.file import FileSecretProvider

AS_OF = date(2026, 9, 30)
NO_SECRETS = SecretResolver({})


def sample() -> SampleCollector:
    return SampleCollector(SampleConfig(), NO_SECRETS)


def test_registry() -> None:
    assert set(plugin_names(COLLECTORS)) == {
        "aws",
        "file",
        "github",
        "jira",
        "rest",
        "sample",
        "servicenow",
        "vault",
    }
    assert collector_class("sample") is SampleCollector
    with pytest.raises(PluginError):
        collector_class("nope")
    assert default_secret_resolver().schemes == ["env", "file"]
    assert plugin_names(RENDERERS) == ["csv", "html", "json", "pdf", "xlsx"]
    assert renderer_class("xlsx").name == "xlsx"
    with pytest.raises(PluginError):
        renderer_class("docx")


@pytest.mark.parametrize("cls", [SampleCollector, FileCollector])
def test_contract(cls: type) -> None:
    check_collector_class(cls)


@pytest.mark.parametrize("query", sorted(SampleCollector.queries))
def test_sample_queries_are_deterministic(query: str) -> None:
    first = collect_all(sample(), query, AS_OF)
    again = collect_all(sample(), query, AS_OF)
    assert json.dumps([b.records for b in first]) == json.dumps([b.records for b in again])
    assert first[0].records
    other = collect_all(SampleCollector(SampleConfig(seed=7), NO_SECRETS), query, AS_OF)
    assert other[0].query == query


def test_sample_story_and_dimensions() -> None:
    c = sample()
    ends = month_ends(date(2026, 9, 30))
    assert ends[0] == date(2025, 10, 31)
    assert ends[-1] == date(2026, 9, 30)
    assert c.month_index(date(2025, 1, 1)) == 0
    assert c.month_index(date(2026, 9, 30)) == 11
    keys = collect_all(c, "crypto_keys", date(2026, 3, 31))[0].records
    assert sum(1 for k in keys if k["past_cryptoperiod"] and k["environment"] == "prod") == 12
    evidence = collect_all(c, "control_evidence", AS_OF)[0].records
    assert {r["control_id"] for r in evidence} == set(CONTROL_IDS)
    assert len(CONTROL_IDS) == 40
    scans = collect_all(c, "card_data_scans", AS_OF)[0].records
    assert any("sample_match" in r for r in scans)


def test_sample_rejects_unknown_query() -> None:
    with pytest.raises(CollectorError):
        list(sample().collect("nope", {}, AS_OF))
    assert sample().test_connection().ok


def file_collector(tmp_path: Path, files: dict[str, str]) -> FileCollector:
    return FileCollector(FileConfig(base_dir=tmp_path, files=files), NO_SECRETS)


def test_file_collector_csv_and_json(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_text("id,count,ratio,note\n1,5,0.5,\nx,,1e3,hi\n", encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({"records": [{"id": 1}]}), encoding="utf-8")
    c = file_collector(tmp_path, {"a": "a.csv", "b": "b.json"})
    assert c.test_connection().ok
    assert c.query_names == ["a", "b"]
    rows = collect_all(c, "a", AS_OF)[0].records
    assert rows == [
        {"id": 1, "count": 5, "ratio": 0.5, "note": None},
        {"id": "x", "count": None, "ratio": 1000.0, "note": "hi"},
    ]
    assert collect_all(c, "b", AS_OF)[0].records == [{"id": 1}]


def test_file_collector_refuses_bad_paths_and_content(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        FileConfig(base_dir=tmp_path, files={"a": "../etc/passwd.csv"})
    with pytest.raises(ValidationError):
        FileConfig(base_dir=tmp_path, files={"a": "/etc/x.json"})
    with pytest.raises(ValidationError):
        FileConfig(base_dir=tmp_path, files={"a": "x.txt"})
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "obj.json").write_text('{"a": 1}', encoding="utf-8")
    c = file_collector(tmp_path, {"bad": "bad.json", "obj": "obj.json", "gone": "gone.csv"})
    assert not c.test_connection().ok
    for q in ("bad", "obj", "gone", "unknown"):
        with pytest.raises(CollectorError):
            list(c.collect(q, {}, AS_OF))


def test_file_collector_refuses_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.json").write_text("[]", encoding="utf-8")
    base = tmp_path / "base"
    base.mkdir()
    (base / "link.json").symlink_to(outside / "x.json")
    with pytest.raises(CollectorError, match="escapes"):
        list(file_collector(base, {"x": "link.json"}).collect("x", {}, AS_OF))


def test_secret_providers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    resolver = SecretResolver({"env": EnvSecretProvider(), "file": FileSecretProvider()})
    monkeypatch.setenv("DSEC_TEST_TOKEN", "t0ken")
    assert resolver.resolve("env://DSEC_TEST_TOKEN").get_secret_value() == "t0ken"
    secret = tmp_path / "s"
    secret.write_text("from-file\n", encoding="utf-8")
    assert resolver.resolve(f"file://{secret}").get_secret_value() == "from-file"
    for bad in (
        "plain-value",
        "env://lower",
        "env://DSEC_UNSET_VAR",
        "vault://kv/x",
        f"file://{tmp_path}/none",
    ):
        with pytest.raises(SecretError):
            resolver.resolve(bad)
    (tmp_path / "empty").write_text("", encoding="utf-8")
    with pytest.raises(SecretError, match="empty"):
        resolver.resolve(f"file://{tmp_path}/empty")


def test_secrets_with_control_characters_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = SecretResolver({"env": EnvSecretProvider(), "file": FileSecretProvider()})
    monkeypatch.setenv("TEST_NEWLINE", "token-value\n")
    with pytest.raises(SecretError, match="control characters") as info:
        resolver.resolve("env://TEST_NEWLINE")
    assert "token-value" not in str(info.value)
    crlf = tmp_path / "crlf"
    crlf.write_bytes(b"token-value\r\n")
    assert resolver.resolve(f"file://{crlf}").get_secret_value() == "token-value"
    inner = tmp_path / "inner"
    inner.write_bytes(b"token\r\nvalue\n")
    with pytest.raises(SecretError, match="control characters"):
        resolver.resolve(f"file://{inner}")
