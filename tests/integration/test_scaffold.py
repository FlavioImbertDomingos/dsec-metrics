"""Acceptance for M4: a plugin made with the scaffold installs and runs without changes
to the core.

"Installs" here means what ``pip install`` leaves behind that the platform relies on: the
package importable and a ``dist-info`` directory with its entry points on ``sys.path``
(plan decision 4). The shared test environment is not modified.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from dsec_metrics.cli.main import app
from dsec_metrics.config import get_settings
from dsec_metrics.content import load_content
from dsec_metrics.core.definitions import CollectorInstance
from dsec_metrics.db.engine import transaction
from dsec_metrics.db.models import RecordBatchRow
from dsec_metrics.pipeline import instance_queries, run_collection
from dsec_metrics.plugins import scaffold
from dsec_metrics.plugins.sdk import http as sdk_http
from dsec_metrics.plugins.sdk.registry import (
    COLLECTORS,
    collector_class,
    default_secret_resolver,
    plugin_names,
)
from dsec_metrics.plugins.sdk.testing import FixtureTransport, fixture_policy

pytestmark = pytest.mark.integration
runner = CliRunner()
NAME = "asset_inventory"


def install(root: Path) -> Path:
    """Write the metadata pip would write, next to the source, and return the path entry."""
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    src = root / "src"
    dist = src / f"{project['name'].replace('-', '_')}-{project['version']}.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        f"Metadata-Version: 2.3\nName: {project['name']}\nVersion: {project['version']}\n",
        encoding="utf-8",
    )
    lines = ["[dsec_metrics.collectors]"]
    for name, target in project["entry-points"]["dsec_metrics.collectors"].items():
        lines.append(f"{name} = {target}")
    (dist / "entry_points.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return src


@pytest.fixture
def plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    result = runner.invoke(app, ["plugin", "new", "collector", NAME, "--directory", str(tmp_path)])
    assert result.exit_code == 0, result.output
    root = tmp_path / "dsec-metrics-asset-inventory"
    assert f"created {root}" in result.output
    src = install(root)
    monkeypatch.syspath_prepend(str(src))
    importlib.invalidate_caches()
    yield root
    for module in [m for m in sys.modules if m.startswith("dsec_metrics_asset_inventory")]:
        del sys.modules[module]
    importlib.invalidate_caches()


def test_scaffolded_collector_is_discovered_and_runs_through_the_pipeline(
    plugin: Path, session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert NAME in plugin_names(COLLECTORS)
    cls = collector_class(NAME)
    assert cls.__name__ == "AssetInventoryCollector"
    instance = CollectorInstance(
        id="inventory",
        plugin=NAME,
        config={"base_url": "https://api.example.test", "token": "env://ASSET_INVENTORY_TOKEN"},
    )
    assert instance_queries(instance) == ["items"]

    fixtures = plugin / "tests" / "fixtures"
    transport = FixtureTransport(
        {
            "GET /items?per_page=100": (
                fixtures / "items-page-1.json",
                {"link": '<https://api.example.test/items?page=2>; rel="next"'},
            ),
            "GET /items?page=2": fixtures / "items-page-2.json",
        }
    )
    monkeypatch.setenv("ASSET_INVENTORY_TOKEN", "test-token")
    monkeypatch.setattr(sdk_http, "socket_transport", transport)
    monkeypatch.setattr(sdk_http, "default_policy", lambda: fixture_policy("api.example.test"))
    with transaction(session_factory) as db:
        result = run_collection(
            db, instance, "items", date(2026, 9, 30), default_secret_resolver(), actor="test"
        )
    assert result.status == "succeeded", result.error
    assert result.records == 3
    assert transport.requests[0].headers["Authorization"] == "Bearer test-token"
    with session_factory() as db:
        row = db.scalars(select(RecordBatchRow).where(RecordBatchRow.collector == NAME)).one()
        assert row.collector_version == "0.1.0"
        assert [r["id"] for r in row.records] == [1, 2, 3]
        assert all("owner_email" not in r for r in row.records)
        assert row.redaction["fields_dropped"] == {"owner_email": 3}


def test_scaffolded_package_passes_its_own_tests_and_linters(plugin: Path) -> None:
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(plugin / "src"), *sys.path]),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    tests = subprocess.run(  # noqa: S603 (fixed arguments, our own interpreter)
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(plugin / "tests")],
        cwd=plugin,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert tests.returncode == 0, tests.stdout + tests.stderr
    assert "2 passed" in tests.stdout
    lint = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "."],
        cwd=plugin,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert lint.returncode == 0, lint.stdout + lint.stderr
    types = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-incremental", "src", "tests"],
        cwd=plugin,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert types.returncode == 0, types.stdout + types.stderr


def test_scaffold_refuses_bad_names_and_existing_directories(tmp_path: Path) -> None:
    for bad in ("Bad", "1abc", "a", "has-dash", "x" * 40):
        result = runner.invoke(app, ["plugin", "new", "collector", bad, "-d", str(tmp_path)])
        assert result.exit_code == 1
        assert "name must start with a letter" in result.output
    assert (
        runner.invoke(app, ["plugin", "new", "collector", "dup", "-d", str(tmp_path)]).exit_code
        == 0
    )
    again = runner.invoke(app, ["plugin", "new", "collector", "dup", "-d", str(tmp_path)])
    assert again.exit_code == 1
    assert "already exists" in again.output
    files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert "dsec-metrics-dup/src/dsec_metrics_dup/collector.py" in files
    assert json.loads((tmp_path / "dsec-metrics-dup/tests/fixtures/items-page-2.json").read_text())
    assert scaffold.NAME.match("dup")


def test_plugin_list_shows_queries_and_permissions() -> None:
    result = runner.invoke(app, ["plugin", "list"])
    assert result.exit_code == 0
    assert "aws 1.0.0" in result.output
    assert "  query kms_key_rotation:" in result.output
    assert "  needs kms:GetKeyRotationStatus" in result.output
    assert "rest 1.0.0" in result.output


def test_test_connection_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_settings: object
) -> None:
    del db_settings
    content = tmp_path / "content"
    source = Path(__file__).parents[2] / "content"
    for sub in source.iterdir():
        target = content / sub.name
        target.mkdir(parents=True)
        for file in sub.iterdir():
            (target / file.name).write_bytes(file.read_bytes())
    (content / "collectors" / "inventory.yaml").write_text(
        "id: inventory\nplugin: rest\nconfig:\n  base_url: https://inventory.example.test\n"
        "  queries:\n    assets: {path: /assets, records_path: items}\n",
        encoding="utf-8",
    )
    assert load_content(content).ok
    monkeypatch.setenv("DSEC_MODE", "development")
    monkeypatch.setenv("DSEC_DB_SSLMODE", "disable")
    monkeypatch.setenv("DSEC_PUBLIC_ORIGIN", "https://localhost")
    get_settings.cache_clear()
    try:
        monkeypatch.setattr(
            sdk_http,
            "socket_transport",
            FixtureTransport({"GET /assets": {"items": [{"id": 1}]}}),
        )
        monkeypatch.setattr(
            sdk_http, "default_policy", lambda: fixture_policy("inventory.example.test")
        )
        ok = runner.invoke(app, ["test-connection", "inventory", "--content", str(content)])
        assert ok.exit_code == 0, ok.output
        assert "ok: query assets readable" in ok.output
        monkeypatch.setattr(sdk_http, "default_policy", lambda: fixture_policy("other.test"))
        blocked = runner.invoke(app, ["test-connection", "inventory", "--content", str(content)])
        assert blocked.exit_code == 1
        assert "failed: blocked: inventory.example.test is not in the collector host allowlist" in (
            blocked.output
        )
        unknown = runner.invoke(app, ["test-connection", "nope", "--content", str(content)])
        assert unknown.exit_code == 1
        assert "unknown collector instance" in unknown.output
    finally:
        get_settings.cache_clear()
