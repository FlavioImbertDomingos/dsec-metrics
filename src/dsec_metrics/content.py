"""Load and validate the ``content/`` directory: definitions as code.

Layout: ``frameworks/``, ``metrics/``, ``controls/``, ``dashboards/`` and ``collectors/``,
each holding YAML files with one definition, or a list of definitions. YAML is parsed
with ``safe_load`` semantics and duplicate keys are errors.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from dsec_metrics.core.definitions import (
    KINDS,
    REF_PATTERN,
    CollectorInstance,
    Control,
    Dashboard,
    Framework,
    Metric,
    Strict,
)

MAX_FILE_BYTES = 1024 * 1024
DIRECTORIES: dict[str, str] = {
    "frameworks": "framework",
    "metrics": "metric",
    "controls": "control",
    "dashboards": "dashboard",
    "collectors": "collector",
}


class UniqueKeyLoader(yaml.SafeLoader):  # type: ignore[misc]
    """SafeLoader that rejects duplicate mapping keys."""


def _construct_mapping(loader: Any, node: Any, deep: bool = False) -> Any:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return loader.construct_mapping(node, deep=deep)


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


@dataclass(frozen=True)
class Problem:
    """One validation problem, tied to a file when there is one."""

    source: str
    message: str

    def __str__(self) -> str:
        return f"{self.source}: {self.message}"


@dataclass
class Content:
    """Every definition, keyed by id, plus where each came from."""

    frameworks: dict[str, Framework] = field(default_factory=dict)
    metrics: dict[str, Metric] = field(default_factory=dict)
    controls: dict[str, Control] = field(default_factory=dict)
    dashboards: dict[str, Dashboard] = field(default_factory=dict)
    collectors: dict[str, CollectorInstance] = field(default_factory=dict)
    sources: dict[tuple[str, str], str] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)

    def by_kind(self, kind: str) -> dict[str, Any]:
        """The mapping for a definition kind."""
        stores: dict[str, dict[str, Any]] = {
            "framework": self.frameworks,
            "metric": self.metrics,
            "control": self.controls,
            "dashboard": self.dashboards,
            "collector": self.collectors,
        }
        return stores[kind]

    def items(self) -> Iterable[tuple[str, str, Strict]]:
        """(kind, id, definition) for every definition, in a stable order."""
        for kind in ("framework", "collector", "metric", "control", "dashboard"):
            for def_id, definition in sorted(self.by_kind(kind).items()):
                yield kind, def_id, definition

    @property
    def ok(self) -> bool:
        """True when there are no problems."""
        return not self.problems


def _read_yaml(path: Path) -> Any:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"file is larger than {MAX_FILE_BYTES} bytes")
    with path.open(encoding="utf-8") as fh:
        # Same steps as yaml.safe_load, with the duplicate-key check added.
        loader = UniqueKeyLoader(fh)
        try:
            return loader.get_single_data()
        finally:
            loader.dispose()


def _format_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err["loc"])
        parts.append(f"{loc}: {err['msg']}" if loc else err["msg"])
    more = len(exc.errors()) - 5
    return "; ".join(parts) + (f"; and {more} more" if more > 0 else "")


def load_content(root: Path) -> Content:
    """Parse and validate every definition file under ``root``. Never raises for bad content."""
    content = Content()
    if not root.is_dir():
        content.problems.append(Problem(str(root), "content directory not found"))
        return content
    for directory, kind in DIRECTORIES.items():
        model = KINDS[kind]
        for path in sorted((root / directory).glob("*.y*ml")):
            rel = str(path.relative_to(root))
            try:
                data = _read_yaml(path)
            except (OSError, ValueError, yaml.YAMLError) as exc:
                content.problems.append(Problem(rel, f"cannot parse: {exc}"))
                continue
            docs = data if isinstance(data, list) else [data]
            for i, doc in enumerate(docs):
                where = rel if len(docs) == 1 else f"{rel}[{i}]"
                if not isinstance(doc, dict):
                    content.problems.append(Problem(where, "expected a mapping"))
                    continue
                try:
                    definition = model.model_validate(doc)
                except ValidationError as exc:
                    content.problems.append(Problem(where, _format_error(exc)))
                    continue
                def_id = str(getattr(definition, "id"))  # noqa: B009
                store = content.by_kind(kind)
                if def_id in store:
                    content.problems.append(Problem(where, f"duplicate {kind} id {def_id}"))
                    continue
                store[def_id] = definition
                content.sources[(kind, def_id)] = where
    return content


QueryLister = Callable[[CollectorInstance], list[str] | None]


def cross_check(content: Content, queries_for: QueryLister) -> list[Problem]:
    """Reference checks across definitions. ``queries_for`` returns an instance's
    queries, or ``None`` when its plugin is not installed."""
    problems: list[Problem] = []
    requirements = {
        f"{fw.id}:{req.ref}" for fw in content.frameworks.values() for req in fw.requirements
    }

    def src(kind: str, def_id: str) -> str:
        return content.sources.get((kind, def_id), f"{kind} {def_id}")

    def check_refs(kind: str, def_id: str, refs: list[str]) -> None:
        for ref in refs:
            match = REF_PATTERN.match(ref)
            pack = match.group("pack") if match else ""
            if ref in requirements:
                continue
            # A pack-level or category reference like nist-csf-2.0:GV.RM is allowed when
            # some requirement in that pack starts with it.
            if any(r.startswith((ref + "-", ref + ".")) for r in requirements):
                continue
            if pack not in content.frameworks:
                problems.append(Problem(src(kind, def_id), f"unknown framework pack in {ref}"))
            else:
                problems.append(Problem(src(kind, def_id), f"unknown requirement {ref}"))

    instance_queries: dict[str, list[str] | None] = {
        cid: queries_for(inst) for cid, inst in content.collectors.items()
    }
    for cid, qs in instance_queries.items():
        if qs is None:
            problems.append(
                Problem(
                    src("collector", cid),
                    f"plugin {content.collectors[cid].plugin!r} is not installed",
                )
            )

    for mid, metric in content.metrics.items():
        check_refs("metric", mid, metric.frameworks)
        inst = metric.source.collector
        if inst not in content.collectors:
            problems.append(Problem(src("metric", mid), f"unknown collector instance {inst!r}"))
        else:
            qs = instance_queries.get(inst)
            if qs is not None and metric.source.query not in qs:
                problems.append(
                    Problem(
                        src("metric", mid),
                        f"collector {inst!r} has no query {metric.source.query!r}",
                    )
                )
    for cid, control in content.controls.items():
        check_refs("control", cid, control.requirements)
        for m in control.metrics:
            if m not in content.metrics:
                problems.append(Problem(src("control", cid), f"unknown metric {m}"))
        for ev in control.evidence:
            qs = instance_queries.get(ev.collector, [])
            if ev.collector not in content.collectors:
                problems.append(
                    Problem(src("control", cid), f"unknown collector instance {ev.collector!r}")
                )
            elif qs is not None and ev.query not in qs:
                problems.append(
                    Problem(
                        src("control", cid), f"collector {ev.collector!r} has no query {ev.query!r}"
                    )
                )
    for did, dash in content.dashboards.items():
        for widget in dash.layout:
            for m in widget.metric_ids():
                if m not in content.metrics:
                    problems.append(Problem(src("dashboard", did), f"unknown metric {m}"))
    return problems
