"""Roles, auditor grants, report packages and links, and the audit log.

The audit log is append-only: a trigger rejects UPDATE, DELETE and TRUNCATE.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "roles",
            ARRAY(sa.String(32)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
    )
    op.create_table(
        "auditor_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("frameworks", ARRAY(sa.String(64)), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auditor_grants_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auditor_grants")),
    )
    op.create_index(op.f("ix_auditor_grants_user_id"), "auditor_grants", ["user_id"])
    op.create_table(
        "report_packages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("scope", JSONB(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("frameworks", ARRAY(sa.String(64)), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("key_fingerprint", sa.String(64), nullable=False),
        sa.Column("pdf_rendered", sa.Boolean(), nullable=False),
        sa.Column("generated_by", sa.String(64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_packages")),
    )
    op.create_table(
        "report_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("package_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["report_packages.id"],
            name=op.f("fk_report_links_package_id_report_packages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_report_links_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_links")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_report_links_token_hash")),
    )
    op.create_index(op.f("ix_report_links_package_id"), "report_links", ["package_id"])
    op.create_table(
        "audit_events",
        sa.Column("seq", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target", sa.String(256), nullable=False),
        sa.Column("details", JSONB(), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_audit_events")),
        sa.UniqueConstraint("hash", name=op.f("uq_audit_events_hash")),
    )
    op.execute(
        """
        CREATE FUNCTION audit_events_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'audit_events is append-only (% rejected)', TG_OP
            USING ERRCODE = 'insufficient_privilege';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_change BEFORE UPDATE OR DELETE ON audit_events"
        " FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events"
        " FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE audit_events")
    op.execute("DROP FUNCTION audit_events_append_only()")
    op.drop_table("report_links")
    op.drop_table("report_packages")
    op.drop_index(op.f("ix_auditor_grants_user_id"), table_name="auditor_grants")
    op.drop_table("auditor_grants")
    op.drop_column("users", "roles")
