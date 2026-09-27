"""Definitions, collector instances, collection runs, record batches, measurements and
the worker's schedules.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "definitions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("def_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("body", JSONB(), nullable=False),
        sa.Column("source", sa.String(512), nullable=True),
        sa.Column("current", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_definitions")),
        sa.UniqueConstraint("kind", "def_id", "version", name="uq_definitions_kind_version"),
        sa.UniqueConstraint("kind", "def_id", "sha256", name="uq_definitions_kind_sha256"),
    )
    op.create_table(
        "collector_instances",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("plugin", sa.String(64), nullable=False),
        sa.Column("plugin_version", sa.String(32), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("schedule", sa.String(64), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collector_instances")),
    )
    op.create_table(
        "schedules",
        sa.Column("id", sa.String(128), nullable=False),
        sa.Column("job", sa.String(64), nullable=False),
        sa.Column("args", JSONB(), nullable=False),
        sa.Column("cron", sa.String(64), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(16), nullable=True),
        sa.Column("last_error", sa.String(2000), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedules")),
    )
    op.create_index(op.f("ix_schedules_next_run_at"), "schedules", ["next_run_at"])
    op.create_table(
        "collection_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("instance_id", sa.String(64), nullable=False),
        sa.Column("query", sa.String(64), nullable=False),
        sa.Column("params", JSONB(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(2000), nullable=True),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["collector_instances.id"],
            name=op.f("fk_collection_runs_instance_id_collector_instances"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_runs")),
    )
    op.create_index(op.f("ix_collection_runs_instance_id"), "collection_runs", ["instance_id"])
    op.create_index(op.f("ix_collection_runs_as_of"), "collection_runs", ["as_of"])
    op.create_table(
        "record_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("instance_id", sa.String(64), nullable=False),
        sa.Column("collector", sa.String(64), nullable=False),
        sa.Column("collector_version", sa.String(32), nullable=False),
        sa.Column("query", sa.String(64), nullable=False),
        sa.Column("params", JSONB(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("redaction", JSONB(), nullable=False),
        sa.Column("storage_ref", sa.String(128), nullable=False),
        sa.Column("records", JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["collection_runs.id"],
            name=op.f("fk_record_batches_run_id_collection_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_record_batches")),
    )
    op.create_index(op.f("ix_record_batches_run_id"), "record_batches", ["run_id"])
    op.create_index(op.f("ix_record_batches_sha256"), "record_batches", ["sha256"])
    op.create_index("ix_record_batches_source", "record_batches", ["instance_id", "query", "as_of"])
    op.create_table(
        "measurements",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("metric_id", sa.String(32), nullable=False),
        sa.Column("definition_id", sa.BigInteger(), nullable=False),
        sa.Column("definition_sha256", sa.String(64), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("dims_key", sa.String(512), nullable=False),
        sa.Column("dimensions", JSONB(), nullable=False),
        sa.Column("value", sa.Double(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input_batch_hashes", JSONB(), nullable=False),
        sa.Column("delta_previous", sa.Double(), nullable=True),
        sa.Column("delta_baseline", sa.Double(), nullable=True),
        sa.Column("distance_to_target", sa.Double(), nullable=True),
        sa.Column("calculation", JSONB(), nullable=False),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["definitions.id"],
            name=op.f("fk_measurements_definition_id_definitions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_measurements")),
        sa.UniqueConstraint(
            "metric_id",
            "definition_sha256",
            "as_of",
            "dims_key",
            name=op.f("uq_measurements_metric_id"),
        ),
    )
    op.create_index("ix_measurements_lookup", "measurements", ["metric_id", "as_of"])


def downgrade() -> None:
    op.drop_table("measurements")
    op.drop_table("record_batches")
    op.drop_table("collection_runs")
    op.drop_table("collector_instances")
    op.drop_index(op.f("ix_schedules_next_run_at"), table_name="schedules")
    op.drop_table("schedules")
    op.drop_table("definitions")
