"""``dsec_metrics.core`` must stay pure: no project imports outside core, no I/O."""

from __future__ import annotations

import ast
from pathlib import Path

import dsec_metrics.core

CORE_DIR = Path(dsec_metrics.core.__file__).parent
FORBIDDEN_TOP_LEVEL = {
    "alembic",
    "asyncio",
    "fastapi",
    "http",
    "httpx",
    "os",
    "psycopg",
    "requests",
    "shutil",
    "socket",
    "sqlalchemy",
    "ssl",
    "subprocess",
    "urllib",
}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def violations(root: Path) -> list[str]:
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for name in _imports(path):
            top = name.split(".")[0]
            outside_core = top == "dsec_metrics" and not name.startswith("dsec_metrics.core")
            if outside_core or top in FORBIDDEN_TOP_LEVEL:
                found.append(f"{path.name}: imports {name}")
    return found


def test_core_is_pure() -> None:
    assert violations(CORE_DIR) == []


def test_checker_catches_violations(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(
        "import socket\nfrom dsec_metrics.api import app\nfrom dsec_metrics.core import x\n",
        encoding="utf-8",
    )
    assert violations(tmp_path) == [
        "bad.py: imports socket",
        "bad.py: imports dsec_metrics.api",
    ]
