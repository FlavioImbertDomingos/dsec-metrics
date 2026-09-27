"""Enforce per-package coverage floors from a coverage.py JSON report.

Usage: python scripts/coverage_gates.py coverage.json

A package with no statements yet (for example ``core`` before M1) passes and is
reported as empty, so the gate is live from the first commit that adds code there.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

GATES: dict[str, float] = {
    "src/dsec_metrics/core/": 90.0,
    "src/dsec_metrics/": 80.0,
}


def main(report_path: str) -> int:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    files: dict[str, dict[str, dict[str, int]]] = report["files"]
    failed = False
    for prefix, floor in GATES.items():
        covered = total = 0
        for name, data in files.items():
            if name.replace("\\", "/").startswith(prefix):
                summary = data["summary"]
                covered += summary["covered_lines"] + summary.get("covered_branches", 0)
                total += summary["num_statements"] + summary.get("num_branches", 0)
        if total == 0:
            print(f"{prefix}: no statements yet, gate {floor:.0f}% passes")
            continue
        percent = 100.0 * covered / total
        ok = percent >= floor
        failed = failed or not ok
        print(f"{prefix}: {percent:.1f}% (floor {floor:.0f}%) {'ok' if ok else 'FAIL'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "coverage.json"))
