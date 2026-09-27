from __future__ import annotations

from pathlib import Path

import pytest

from dsec_metrics.content import cross_check, load_content
from dsec_metrics.pipeline import instance_queries
from tests.conftest import CONTENT_DIR


def test_default_content_is_valid_and_complete() -> None:
    content = load_content(CONTENT_DIR)
    assert content.problems == []
    assert cross_check(content, instance_queries) == []
    assert len(content.metrics) == 16
    assert len(content.controls) == 40
    assert set(content.dashboards) == {"team-operations", "management", "risk-committee"}
    assert set(content.frameworks) == {
        "nist-csf-2.0",
        "pci-dss-4.0.1",
        "soc2-tsc",
        "iso-27001-2022",
    }
    assert {m.type.value for m in content.metrics.values()} == {"kpi", "kri", "kci"}


def test_no_copyrighted_requirement_text() -> None:
    content = load_content(CONTENT_DIR)
    for fw in content.frameworks.values():
        if not fw.public_domain:
            assert all(r.text is None for r in fw.requirements)


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_duplicate_keys_and_bad_yaml_are_reported(tmp_path: Path) -> None:
    write(tmp_path, "collectors/a.yaml", "id: a\nplugin: sample\nid: b\n")
    write(tmp_path, "collectors/b.yaml", "id: [unclosed\n")
    write(tmp_path, "collectors/c.yaml", "- just a string\n")
    content = load_content(tmp_path)
    messages = " ".join(str(p) for p in content.problems)
    assert "duplicate key 'id'" in messages
    assert "cannot parse" in messages
    assert "expected a mapping" in messages


def test_yaml_cannot_construct_python_objects(tmp_path: Path) -> None:
    write(tmp_path, "collectors/a.yaml", "!!python/object/apply:os.system ['true']\n")
    content = load_content(tmp_path)
    assert content.problems
    assert "cannot parse" in str(content.problems[0])


def test_missing_directory() -> None:
    assert not load_content(Path("/nonexistent/content")).ok


def test_cross_reference_problems(tmp_path: Path) -> None:
    for sub in ("frameworks", "metrics", "controls", "dashboards", "collectors"):
        (tmp_path / sub).mkdir()
    for src in (CONTENT_DIR / "metrics").glob("kri-03.yaml"):
        write(tmp_path, "metrics/kri-03.yaml", src.read_text(encoding="utf-8"))
    write(
        tmp_path,
        "controls/x.yaml",
        "id: DS-XX-01\nname: Example\nowner: someone\nrequirements: ['pci-dss-4.0.1:99.9']\n"
        "metrics: [KRI-77]\nevidence: [{collector: nope, query: q, retain_days: 10}]\n",
    )
    write(
        tmp_path,
        "dashboards/d.yaml",
        "id: d\ntitle: D\naudience: management\nrefresh: monthly\n"
        "layout: [{widget: stat, metric: KPI-99}]\n",
    )
    write(tmp_path, "collectors/ghost.yaml", "id: ghost\nplugin: not-installed\n")
    content = load_content(tmp_path)
    assert content.problems == []
    messages = [str(p) for p in cross_check(content, instance_queries)]
    joined = " | ".join(messages)
    assert "unknown collector instance 'sample'" in joined
    assert "unknown framework pack in nist-csf-2.0:GV.RM" in joined
    assert "unknown framework pack in pci-dss-4.0.1:99.9" in joined
    assert "unknown metric KRI-77" in joined
    assert "unknown metric KPI-99" in joined
    assert "unknown collector instance 'nope'" in joined
    assert "plugin 'not-installed' is not installed" in joined


def test_duplicate_ids_are_reported(tmp_path: Path) -> None:
    body = (CONTENT_DIR / "metrics" / "kri-03.yaml").read_text(encoding="utf-8")
    write(tmp_path, "metrics/a.yaml", body)
    write(tmp_path, "metrics/b.yaml", body)
    content = load_content(tmp_path)
    assert any("duplicate metric id KRI-03" in str(p) for p in content.problems)


@pytest.mark.parametrize("query", ["findings", "missing_query"])
def test_unknown_query_is_reported(tmp_path: Path, query: str) -> None:
    body = (CONTENT_DIR / "metrics" / "kri-01.yaml").read_text(encoding="utf-8")
    write(tmp_path, "metrics/kri-01.yaml", body.replace("query: findings", f"query: {query}"))
    write(tmp_path, "collectors/sample.yaml", "id: sample\nplugin: sample\n")
    content = load_content(tmp_path)
    problems = [str(p) for p in cross_check(content, instance_queries)]
    has = any("has no query 'missing_query'" in p for p in problems)
    assert has is (query == "missing_query")
