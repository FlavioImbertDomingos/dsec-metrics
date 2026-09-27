from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from dsec_metrics.core.canonical import canonical_hash, canonical_json
from dsec_metrics.core.definitions import (
    Band,
    CollectorInstance,
    Control,
    Dashboard,
    Filter,
    Framework,
    definition_hash,
)
from tests.core.factories import metric

BRIEF_EXAMPLE = {
    "id": "KRI-03",
    "name": "Exceptions open more than 180 days",
    "type": "kri",
    "question": "Are exceptions staying temporary?",
    "owner": "data-security-exceptions-lead",
    "audience": ["risk_committee", "management"],
    "source": {"collector": "grc_exceptions", "query": "open_exceptions"},
    "evaluation": {
        "kind": "count",
        "filters": [
            {"field": "status", "op": "eq", "value": "approved"},
            {"field": "days_since_approval", "op": "gt", "value": 180},
        ],
        "group_by": ["business_unit"],
    },
    "frequency": "monthly",
    "thresholds": {
        "green": {"max": 5},
        "amber": {"max": 15},
        "red": {"above": 15},
        "overrides": [{"dimension": {"business_unit": "cards"}, "red": {"above": 8}}],
    },
    "action_when_red": "Escalate owners to the business unit CIO.",
    "frameworks": ["nist-csf-2.0:GV.RM"],
    "baseline": {"value": 22, "method": "manual count from register", "date": "2026-10-31"},
    "approved_by": ["manager", "technology_risk", "internal_audit"],
    "review_by": "2027-04-30",
}


def test_brief_metric_example_validates() -> None:
    from dsec_metrics.core.definitions import Metric

    m = Metric.model_validate(BRIEF_EXAMPLE)
    assert m.evaluation.kind == "count"
    assert m.thresholds.overrides[0].red is not None


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        metric({"kind": "count"}, colour="blue")


def test_unknown_evaluation_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        metric({"kind": "eval", "expression": "__import__('os')"})


@pytest.mark.parametrize(
    "bad",
    [
        {"field": "x", "op": "in", "value": 1},
        {"field": "x", "op": "eq", "value": [1]},
        {"field": "x", "op": "exists", "value": 1},
        {"field": "x", "op": "matches", "value": ".*"},
    ],
)
def test_filter_value_shape(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Filter.model_validate(bad)


def test_group_by_only_known_dimensions() -> None:
    with pytest.raises(ValidationError):
        metric({"kind": "count", "group_by": ["owner"]})


def test_band_needs_a_bound() -> None:
    with pytest.raises(ValidationError):
        Band()
    assert Band(min=1, below=5).contains(1)
    assert not Band(min=1, below=5).contains(5)
    assert Band(above=2).contains(2.5)
    assert not Band(above=2).contains(2)


def test_override_dimension_must_be_known() -> None:
    with pytest.raises(ValidationError):
        metric(
            {"kind": "count"},
            thresholds={"green": {"max": 1}, "overrides": [{"dimension": {"team": "x"}}]},
        )


def test_framework_refs_are_checked() -> None:
    with pytest.raises(ValidationError):
        metric({"kind": "count"}, frameworks=["PCI 3.7.4"])


def test_framework_text_only_for_public_domain() -> None:
    body: dict[str, Any] = {
        "id": "pci-dss-4.0.1",
        "name": "PCI DSS",
        "version": "4.0.1",
        "source_url": "https://www.pcisecuritystandards.org/",
        "requirements": [{"ref": "3.7.4", "short_title": "Key changes", "text": "copied"}],
    }
    with pytest.raises(ValidationError, match="public-domain"):
        Framework.model_validate(body)
    body["public_domain"] = True
    assert Framework.model_validate(body).public_domain


def test_duplicate_requirement_refs() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        Framework.model_validate(
            {
                "id": "x",
                "name": "X",
                "version": "1",
                "source_url": "https://example.test/",
                "requirements": [
                    {"ref": "1", "short_title": "One"},
                    {"ref": "1", "short_title": "Again"},
                ],
            }
        )


def test_control_dashboard_collector_models() -> None:
    c = Control.model_validate(
        {
            "id": "DS-KM-04",
            "name": "Keys rotate",
            "owner": "crypto-services-lead",
            "requirements": ["pci-dss-4.0.1:3.7.4"],
            "metrics": ["KRI-04"],
            "evidence": [{"collector": "aws", "query": "kms_key_rotation", "retain_days": 400}],
        }
    )
    assert c.evidence[0].retain_days == 400
    d = Dashboard.model_validate(
        {
            "id": "risk-committee",
            "title": "Risk committee",
            "audience": "risk_committee",
            "refresh": "monthly",
            "layout": [
                {"widget": "rag_list", "metrics": ["KRI-01", "KRI-03"], "width": 12},
                {"widget": "trend", "metric": "KRI-03", "periods": 12, "width": 6},
            ],
        }
    )
    assert d.layout[1].metric_ids() == ["KRI-03"]
    with pytest.raises(ValidationError, match="cron"):
        CollectorInstance.model_validate({"id": "s", "plugin": "sample", "schedule": "daily"})


def test_definition_hash_ignores_key_order_and_changes_with_content() -> None:
    a = metric({"kind": "count"})
    b = metric({"kind": "count"})
    assert definition_hash(a) == definition_hash(b)
    c = metric({"kind": "count"}, action_when_red="Escalate to the CIO.")
    assert definition_hash(a) != definition_hash(c)


def test_canonical_json() -> None:
    assert canonical_json({"b": 1, "a": [1.5, "é"]}) == '{"a":[1.5,"é"],"b":1}'
    assert canonical_hash({"a": 1}) == canonical_hash({"a": 1})
    with pytest.raises(ValueError, match="JSON compliant"):
        canonical_json(float("nan"))
