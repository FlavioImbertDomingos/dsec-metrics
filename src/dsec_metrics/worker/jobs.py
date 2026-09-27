"""Scheduled jobs. The scheduler looks jobs up by name in ``JOBS`` and passes string
arguments stored as plain JSON."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from dsec_metrics.config import get_settings
from dsec_metrics.content import cross_check, load_content
from dsec_metrics.db.engine import make_engine, make_session_factory, transaction
from dsec_metrics.pipeline import (
    evaluate_all,
    instance_queries,
    run_collection,
    sources_needed,
    sync_definitions,
)
from dsec_metrics.plugins.sdk.registry import default_secret_resolver

log = logging.getLogger(__name__)


def run_instance(instance_id: str) -> dict[str, int]:
    """Collect every query the content needs from one instance, then re-evaluate the
    metrics that read from it. Runs for today's date in UTC."""
    settings = get_settings()
    content = load_content(settings.content_dir)
    problems = [*content.problems, *cross_check(content, instance_queries)]
    if problems:
        log.error(
            "content is invalid; skipping run",
            extra={"event": "content_invalid", "problems": len(problems)},
        )
        return {"runs": 0, "failed_runs": 0, "measurements": 0}
    instance = content.collectors[instance_id]
    queries = sorted(sources_needed(content).get(instance_id, set()))
    as_of = datetime.now(UTC).date()
    engine = make_engine(settings)
    secrets = default_secret_resolver()
    failed = 0
    try:
        with transaction(make_session_factory(engine)) as db:
            current = sync_definitions(db, content, "system:worker")
            for query in queries:
                failed += (
                    run_collection(
                        db, instance, query, as_of, secrets, actor="system:worker"
                    ).status
                    != "succeeded"
                )
            metric_ids = [
                m.id for m in content.metrics.values() if m.source.collector == instance_id
            ]
            count = evaluate_all(db, content, current, as_of, metric_ids)
    finally:
        engine.dispose()
    return {"runs": len(queries), "failed_runs": failed, "measurements": count}


JOBS: dict[str, Callable[..., Mapping[str, Any]]] = {"collect": run_instance}
