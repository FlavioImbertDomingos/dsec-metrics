"""``sample`` collector: deterministic synthetic data for demos and tests.

Everything is generated from a seeded ``random.Random``, so the same seed and ``as_of``
always produce the same records. The story covers twelve month-ends ending at
``anchor`` (default 2026-09-30) across three business units, and includes an audit in
month nine with a spike of evidence requests before it, a key-rotation backlog that
turns red and recovers, and slow improvement in coverage metrics.

None of this is real data. Host names use ``example.test``; card numbers are the
well-known test numbers and exist to exercise redaction.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar

from pydantic import Field

from dsec_metrics.plugins.sdk.base import Collector, CollectorConfig, ConnectionResult, RecordBatch

BUSINESS_UNITS = ("cards", "payments", "retail")
APPLICATIONS: dict[str, tuple[str, ...]] = {
    "cards": ("card-issuing", "card-vault", "fraud-scoring"),
    "payments": ("payment-gateway", "settlement", "merchant-portal"),
    "retail": ("loyalty", "ecommerce", "store-pos"),
}
REGIONS: dict[str, str] = {"cards": "amer", "payments": "emea", "retail": "apac"}
BU_WEIGHT: dict[str, float] = {"cards": 0.45, "payments": 0.35, "retail": 0.20}

# Test card numbers published by card brands for testing. Not real accounts.
TEST_PANS = ("4111 1111 1111 1111", "5555-5555-5555-4444", "378282246310005", "6011111111111117")

CONTROL_FAMILIES: dict[str, int] = {
    "KM": 6,
    "CM": 3,
    "SM": 3,
    "EN": 4,
    "AC": 6,
    "DL": 4,
    "TK": 3,
    "VM": 4,
    "EX": 3,
    "AU": 4,
}
CONTROL_IDS: tuple[str, ...] = tuple(
    f"DS-{family}-{n:02d}"
    for family, count in CONTROL_FAMILIES.items()
    for n in range(1, count + 1)
)


def month_ends(anchor: date, months: int = 12) -> list[date]:
    """The last day of each of ``months`` months ending with ``anchor``'s month."""
    out = []
    year, month = anchor.year, anchor.month
    for _ in range(months):
        first_next = date(year + (month == 12), month % 12 + 1, 1)
        out.append(first_next - timedelta(days=1))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return sorted(out)


def _curve(points: tuple[float, ...], m: int) -> float:
    return points[max(0, min(len(points) - 1, m))]


class SampleConfig(CollectorConfig):
    """Seed and time window."""

    seed: int = 42
    anchor: date = date(2026, 9, 30)
    months: int = Field(default=12, ge=1, le=36)


class SampleCollector(Collector):
    """Synthetic data security telemetry. Has no connection to anything."""

    name = "sample"
    version = "1.0.0"
    config_model = SampleConfig
    required_permissions: ClassVar[list[str]] = ["none: generates data locally"]
    sensitive_fields: ClassVar[tuple[str, ...]] = ("card_holder_name",)
    queries: ClassVar[dict[str, str]] = {
        "findings": "Open findings, plus findings closed in the month ending as_of.",
        "open_exceptions": "Exception register entries that are approved, pending or expired.",
        "review_activity": "Control reviews and the exceptions they granted, in the month.",
        "crypto_keys": "Key inventory across Vault, KMS and HSMs with rotation state.",
        "certificates": "Server certificates with days to expiry.",
        "secrets_inventory": "Secret metadata (never values) with rotation state.",
        "data_stores": "In-scope data stores and whether they are encrypted at rest.",
        "admin_accounts": "Administrator accounts on in-scope systems and their MFA state.",
        "access_reviews": "Privileged access reviews due in the month.",
        "card_data_scans": "Data discovery scan results, including stray card numbers.",
        "payment_apps": "Applications that handle card numbers and whether they tokenize.",
        "audit_requests": "Audit evidence requests received in the month.",
        "design_reviews": "Security design reviews completed in the month.",
        "control_evidence": "Each control and whether its evidence is collected automatically.",
    }

    config: SampleConfig

    def test_connection(self) -> ConnectionResult:
        return ConnectionResult(ok=True, detail="sample data needs no connection")

    def month_index(self, as_of: date) -> int:
        """Position of ``as_of`` in the story: 0 is the first month, 11 the last."""
        ends = month_ends(self.config.anchor, self.config.months)
        if as_of <= ends[0]:
            return 0
        return sum(1 for e in ends if e <= as_of) - 1

    def _rng(self, query: str, as_of: date) -> random.Random:
        return random.Random(f"{self.config.seed}:{query}:{as_of.isoformat()}")  # noqa: S311

    def collect(self, query: str, params: dict[str, Any], as_of: date) -> Iterator[RecordBatch]:
        self._check_query(query)
        m = self.month_index(as_of)
        rng = self._rng(query, as_of)
        generator: Callable[[random.Random, int, date], list[dict[str, Any]]] = getattr(
            self, f"_q_{query}"
        )
        records = generator(rng, m, as_of)
        collected = datetime.combine(as_of, datetime.min.time(), tzinfo=UTC) + timedelta(hours=23)
        yield RecordBatch(query=query, params=params, records=records, collected_at=collected)

    # Helpers.

    @staticmethod
    def _dims(rng: random.Random, bu: str | None = None) -> dict[str, str]:
        unit = bu or rng.choices(BUSINESS_UNITS, weights=[BU_WEIGHT[b] for b in BUSINESS_UNITS])[0]
        return {
            "business_unit": unit,
            "application": rng.choice(APPLICATIONS[unit]),
            "environment": "prod" if rng.random() < 0.7 else "nonprod",
            "region": REGIONS[unit],
        }

    @staticmethod
    def _split(total: int, rng: random.Random) -> dict[str, int]:
        counts = dict.fromkeys(BUSINESS_UNITS, 0)
        for _ in range(total):
            counts[
                rng.choices(BUSINESS_UNITS, weights=[BU_WEIGHT[b] for b in BUSINESS_UNITS])[0]
            ] += 1
        return counts

    @staticmethod
    def _iso(d: date) -> str:
        return d.isoformat()

    # Queries.

    def _q_findings(self, rng: random.Random, m: int, as_of: date) -> list[dict[str, Any]]:
        past_due_high = (4, 5, 6, 5, 7, 9, 8, 6, 5, 4, 5, 6)
        repeat = (6, 6, 5, 5, 5, 4, 4, 4, 3, 3, 2, 2)
        on_time_pct = (78, 80, 81, 83, 79, 76, 80, 84, 86, 88, 90, 91)
        records: list[dict[str, Any]] = []
        n_open = 60 + rng.randint(-5, 5)
        for i in range(n_open):
            severity = rng.choices(["critical", "high", "medium", "low"], weights=[1, 4, 8, 6])[0]
            opened = as_of - timedelta(days=rng.randint(5, 300))
            due = opened + timedelta(
                days={"critical": 15, "high": 30, "medium": 90, "low": 180}[severity]
            )
            records.append(
                {
                    "finding_id": f"F-{as_of:%y%m}-{i:03d}",
                    "severity": severity,
                    "status": "open",
                    "source": rng.choice(
                        ["internal_audit", "pci_qsa", "pentest", "self_assessment"]
                    ),
                    "control_id": rng.choice(CONTROL_IDS),
                    "opened": self._iso(opened),
                    "due_date": self._iso(due),
                    "days_past_due": 0,
                    "repeat": False,
                    **self._dims(rng),
                }
            )
        # Make the story counts exact: past-due high/critical and repeat findings.
        high = [r for r in records if r["severity"] in ("critical", "high")]
        for r in high[: int(_curve(past_due_high, m))]:
            r["days_past_due"] = rng.randint(1, 90)
        for r in records[-int(_curve(repeat, m)) :]:
            r["repeat"] = True
        closed_total = 20 + rng.randint(0, 6)
        on_time = round(closed_total * _curve(on_time_pct, m) / 100)
        for i in range(closed_total):
            closed = as_of - timedelta(days=rng.randint(0, 27))
            records.append(
                {
                    "finding_id": f"F-{as_of:%y%m}-C{i:02d}",
                    "severity": rng.choice(["high", "medium", "low"]),
                    "status": "closed",
                    "source": "internal_audit",
                    "control_id": rng.choice(CONTROL_IDS),
                    "opened": self._iso(closed - timedelta(days=rng.randint(10, 120))),
                    "closed": self._iso(closed),
                    "closed_this_period": True,
                    "closed_on_time": i < on_time,
                    "days_past_due": 0,
                    "repeat": False,
                    **self._dims(rng),
                }
            )
        return records

    def _q_open_exceptions(self, rng: random.Random, m: int, as_of: date) -> list[dict[str, Any]]:
        over_180 = (22, 21, 19, 18, 16, 15, 13, 12, 10, 9, 7, 6)
        records: list[dict[str, Any]] = []
        target = int(_curve(over_180, m))
        split = self._split(target, rng)
        # Keep cards above its tighter red line for the first half of the year.
        if m < 6 and split["cards"] <= 8:
            move = min(9 - split["cards"], split["retail"] + split["payments"])
            take_retail = min(move, split["retail"])
            split["cards"] += move
            split["retail"] -= take_retail
            split["payments"] -= move - take_retail
        n = 0
        for bu, count in split.items():
            for _ in range(count):
                records.append(self._exception(rng, as_of, n, bu, rng.randint(181, 600)))
                n += 1
        for _ in range(35 + rng.randint(-4, 4)):
            records.append(self._exception(rng, as_of, n, None, rng.randint(0, 180)))
            n += 1
        return records

    def _exception(
        self, rng: random.Random, as_of: date, n: int, bu: str | None, age: int
    ) -> dict[str, Any]:
        approved = as_of - timedelta(days=age)
        status = (
            rng.choices(["approved", "pending", "expired"], weights=[20, 2, 1])[0]
            if bu is None
            else "approved"
        )
        return {
            "exception_id": f"EX-{n:04d}",
            "status": status,
            "control_id": rng.choice(CONTROL_IDS),
            "reason": "Legacy system cannot meet the control until migration completes.",
            "compensating_controls": "Network segmentation and enhanced monitoring.",
            "risk_rating": rng.choice(["low", "medium", "high"]),
            "owner": f"owner-{rng.randint(1, 12):02d}",
            "root_cause": rng.choice(
                ["legacy_platform", "vendor_dependency", "resource_constraint", "design_gap"]
            ),
            "approved_at": self._iso(approved),
            "expires_at": self._iso(approved + timedelta(days=rng.choice([90, 180, 365]))),
            "days_since_approval": age,
            **self._dims(rng, bu),
        }

    def _q_review_activity(self, rng: random.Random, m: int, as_of: date) -> list[dict[str, Any]]:
        per_100 = (8.5, 8.2, 8.0, 7.6, 7.4, 7.0, 6.8, 6.4, 6.0, 5.7, 5.4, 5.1)
        reviews = 180 + rng.randint(-15, 15)
        granted = round(reviews * _curve(per_100, m) / 100)
        out: list[dict[str, Any]] = []
        for i in range(reviews):
            out.append({"record_type": "review", "review_id": f"R-{i:04d}", **self._dims(rng)})
        for i in range(granted):
            out.append({"record_type": "exception", "review_id": f"R-{i:04d}", **self._dims(rng)})
        return out

    def _q_crypto_keys(self, rng: random.Random, m: int, as_of: date) -> list[dict[str, Any]]:
        overdue = (2, 1, 3, 2, 9, 12, 10, 3, 2, 1, 1, 0)
        out: list[dict[str, Any]] = []
        n_overdue = int(_curve(overdue, m))
        for i in range(140):
            store = rng.choice(["vault-transit", "cloud-kms", "hsm"])
            period = rng.choice([90, 180, 365])
            late = i < n_overdue
            age = period + rng.randint(1, 60) if late else rng.randint(0, period - 1)
            dims = self._dims(rng, "cards" if late and i % 3 != 2 else None)
            dims["environment"] = "prod" if late else dims["environment"]
            out.append(
                {
                    "key_id": f"key-{i:03d}",
                    "store": store,
                    "algorithm": rng.choice(["AES-256-GCM", "RSA-3072", "ECDSA-P256"]),
                    "cryptoperiod_days": period,
                    "last_rotated": self._iso(as_of - timedelta(days=age)),
                    "days_since_rotation": age,
                    "past_cryptoperiod": late,
                    **dims,
                }
            )
        return out

    def _q_certificates(self, rng: random.Random, m: int, as_of: date) -> list[dict[str, Any]]:
        expiring = (3, 2, 4, 3, 2, 3, 5, 4, 11, 4, 2, 2)
        n_exp = int(_curve(expiring, m))
        out: list[dict[str, Any]] = []
        for i in range(90):
            days = rng.randint(0, 30) if i < n_exp else rng.randint(31, 397)
            dims = self._dims(rng)
            out.append(
                {
                    "certificate_id": f"cert-{i:03d}",
                    "subject": f"{dims['application']}.{dims['business_unit']}.example.test",
                    "issuer": "Example Internal CA",
                    "not_after": self._iso(as_of + timedelta(days=days)),
                    "days_to_expiry": days,
                    **dims,
                }
            )
        return out

    def _q_secrets_inventory(self, rng: random.Random, m: int, as_of: date) -> list[dict[str, Any]]:
        overdue = (6, 6, 5, 5, 4, 4, 3, 5, 10, 4, 5, 7)
        n = int(_curve(overdue, m))
        out: list[dict[str, Any]] = []
        for i in range(120):
            policy = rng.choice([30, 90, 180])
            late = i < n
            age = policy + rng.randint(1, 45) if late else rng.randint(0, policy - 1)
            dims = self._dims(rng)
            out.append(
                {
                    "secret_path": (
                        f"kv/{dims['business_unit']}/{dims['application']}/secret-{i:03d}"
                    ),
                    "engine": rng.choice(["vault-kv", "cloud-secrets-manager"]),
                    "rotation_policy_days": policy,
                    "days_since_rotation": age,
                    "overdue": late,
                    **dims,
                }
            )
        return out

    def _coverage(
        self,
        rng: random.Random,
        m: int,
        pct_curve: tuple[float, ...],
        total: int,
        make: Callable[[int, bool, dict[str, str]], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        good = round(total * _curve(pct_curve, m) / 100)
        return [make(i, i < good, self._dims(rng)) for i in range(total)]

    def _q_data_stores(self, rng: random.Random, m: int, as_of: date) -> list[dict[str, Any]]:
        pct = (97.0, 97.2, 97.5, 97.9, 98.2, 98.4, 98.7, 99.0, 99.2, 99.4, 99.5, 99.6)
        return self._coverage(
            rng,
            m,
            pct,
            480,
            lambda i, ok, d: {
                "store_id": f"ds-{i:04d}",
                "store_type": ("postgres", "object-store", "mainframe-dataset", "nosql")[i % 4],
                "in_scope": True,
                "encrypted_at_rest": ok,
                **d,
            },
        )

    def _q_admin_accounts(self, rng: random.Random, m: int, as_of: date) -> list[dict[str, Any]]:
        pct = (93.0, 94.0, 95.0, 95.5, 96.0, 97.0, 97.5, 98.0, 98.5, 99.0, 99.3, 98.5)
        return self._coverage(
            rng,
            m,
            pct,
            320,
            lambda i, ok, d: {
                "account_ref": f"adm-{i:04d}",
                "system": d["application"],
                "in_scope": True,
                "mfa_enabled": ok,
                **d,
            },
        )

    def _q_access_reviews(self, rng: random.Random, m: int, as_of: date) -> list[dict[str, Any]]:
        pct = (88, 89, 90, 91, 90, 70, 86, 92, 94, 95, 96, 96)
        return self._coverage(
            rng,
            m,
            pct,
            50,
            lambda i, ok, d: {
                "review_id": f"par-{i:03d}",
                "system": d["application"],
                "due_date": self._iso(as_of - timedelta(days=i % 25)),
                "completed_date": self._iso(
                    as_of - timedelta(days=i % 25) + timedelta(days=0 if ok else 9)
                ),
                "on_time": ok,
                **d,
            },
        )

    def _q_card_data_scans(self, rng: random.Random, m: int, as_of: date) -> list[dict[str, Any]]:
        outside = (5, 4, 4, 14, 6, 4, 3, 3, 2, 2, 1, 1)
        total_outside = int(_curve(outside, m))
        out: list[dict[str, Any]] = []
        for i in range(40):
            approved_store = i >= 8
            count = 0
            if not approved_store:
                count = total_outside // 8 + (1 if i < total_outside % 8 else 0)
            record: dict[str, Any] = {
                "scan_id": f"scan-{as_of:%y%m}-{i:02d}",
                "location": f"share-{i:02d}.files.example.test",
                "approved_store": approved_store,
                "finding_count": count if not approved_store else rng.randint(50, 500),
                **self._dims(rng),
            }
            if count:
                # Scanner output often echoes what it found. Redaction masks these.
                record["sample_match"] = f"match: {TEST_PANS[i % len(TEST_PANS)]}"
                record["card_holder_name"] = "TEST CARDHOLDER"
            out.append(record)
        return out

    def _q_payment_apps(self, rng: random.Random, m: int, as_of: date) -> list[dict[str, Any]]:
        pct = (60, 62, 64, 66, 68, 70, 73, 76, 78, 80, 83, 85)
        return self._coverage(
            rng,
            m,
            pct,
            40,
            lambda i, ok, d: {
                "app": f"{d['application']}-{i:02d}",
                "handles_pan": True,
                "tokenized": ok,
                **d,
            },
        )

    def _q_audit_requests(self, rng: random.Random, m: int, as_of: date) -> list[dict[str, Any]]:
        volume = (30, 28, 32, 30, 35, 40, 90, 140, 60, 30, 28, 30)
        on_time_pct = (97, 96, 97, 96, 95, 94, 85, 79, 90, 96, 97, 98)
        total = int(_curve(volume, m))
        on_time = round(total * _curve(on_time_pct, m) / 100)
        out = []
        for i in range(total):
            received = as_of - timedelta(days=rng.randint(0, 27))
            due = received + timedelta(days=10)
            answered = (
                due - timedelta(days=rng.randint(0, 5))
                if i < on_time
                else due + timedelta(days=rng.randint(1, 10))
            )
            out.append(
                {
                    "request_id": f"AR-{as_of:%y%m}-{i:03d}",
                    "audit": "PCI DSS assessment" if 5 <= m <= 8 else "Internal audit",
                    "received": self._iso(received),
                    "due": self._iso(due),
                    "answered": self._iso(answered),
                    "on_time": i < on_time,
                    **self._dims(rng),
                }
            )
        return out

    def _q_design_reviews(self, rng: random.Random, m: int, as_of: date) -> list[dict[str, Any]]:
        median_days = (14, 14, 13, 13, 12, 12, 11, 11, 10, 10, 9, 11)
        center = int(_curve(median_days, m))
        out = []
        for i in range(21):
            cycle = max(1, center + (i - 10) + rng.randint(-1, 1) * (i % 2))
            cycle = center if i == 10 else cycle
            completed = as_of - timedelta(days=rng.randint(0, 27))
            out.append(
                {
                    "review_id": f"DR-{as_of:%y%m}-{i:02d}",
                    "requested": self._iso(completed - timedelta(days=cycle)),
                    "completed": self._iso(completed),
                    "cycle_days": cycle,
                    **self._dims(rng),
                }
            )
        return out

    def _q_control_evidence(self, rng: random.Random, m: int, as_of: date) -> list[dict[str, Any]]:
        pct = (45, 47, 50, 52, 55, 57, 60, 62, 64, 66, 68, 70)
        automated = round(len(CONTROL_IDS) * _curve(pct, m) / 100)
        out = []
        for i, control_id in enumerate(CONTROL_IDS):
            for bu in BUSINESS_UNITS:
                out.append(
                    {
                        "control_id": control_id,
                        "automated": i < automated,
                        "evidence_fresh": rng.random() > 0.08,
                        "business_unit": bu,
                        "region": REGIONS[bu],
                    }
                )
        return out
