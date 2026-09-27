"""SQLAlchemy models."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base with a constraint naming convention for stable migrations."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class User(Base):
    """A person who can sign in. Local password hashes exist only in development mode."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str | None] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class UserSession(Base):
    """A server-side browser session. Only the SHA-256 of the cookie token is stored."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_address: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="sessions")


class AuthFailure(Base):
    """One failed sign-in attempt, kept for the throttling window."""

    __tablename__ = "auth_failures"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    source_address: Mapped[str] = mapped_column(String(64), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RateLimitWindow(Base):
    """Request count for one key in one fixed window. Unlogged: losing it on a crash only
    resets the counters."""

    __tablename__ = "rate_limits"
    __table_args__ = {"prefixes": ["UNLOGGED"]}  # noqa: RUF012 (SQLAlchemy convention)

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)


class DefinitionVersion(Base):
    """One version of one definition. New content creates a new row; nothing is updated
    except the ``current`` flag."""

    __tablename__ = "definitions"
    __table_args__ = (
        UniqueConstraint("kind", "def_id", "version", name="uq_definitions_kind_version"),
        UniqueConstraint("kind", "def_id", "sha256", name="uq_definitions_kind_sha256"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    def_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source: Mapped[str | None] = mapped_column(String(512))
    current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CollectorInstanceRow(Base):
    """A configured collector. ``config`` holds secret references, never values."""

    __tablename__ = "collector_instances"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plugin: Mapped[str] = mapped_column(String(64))
    plugin_version: Mapped[str] = mapped_column(String(32))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    schedule: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScheduleRow(Base):
    """A recurring job. ``job`` names an entry in a fixed registry and ``args`` holds plain
    JSON strings; nothing stored here is ever imported or deserialized into objects."""

    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job: Mapped[str] = mapped_column(String(64))
    args: Mapped[dict[str, Any]] = mapped_column(JSONB)
    cron: Mapped[str] = mapped_column(String(64))
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(16))
    last_error: Mapped[str | None] = mapped_column(String(2000))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CollectionRun(Base):
    """One execution of one query on one collector instance."""

    __tablename__ = "collection_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[str] = mapped_column(ForeignKey("collector_instances.id"), index=True)
    query: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    as_of: Mapped[date] = mapped_column(Date, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(2000))


class RecordBatchRow(Base):
    """Redacted records from one query in one run, with their SHA-256."""

    __tablename__ = "record_batches"
    __table_args__ = (Index("ix_record_batches_source", "instance_id", "query", "as_of"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collection_runs.id"), index=True)
    instance_id: Mapped[str] = mapped_column(String(64))
    collector: Mapped[str] = mapped_column(String(64))
    collector_version: Mapped[str] = mapped_column(String(32))
    query: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    as_of: Mapped[date] = mapped_column(Date)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    record_count: Mapped[int] = mapped_column(Integer)
    redaction: Mapped[dict[str, Any]] = mapped_column(JSONB)
    storage_ref: Mapped[str] = mapped_column(String(128))
    records: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)


class MeasurementRow(Base):
    """A metric value for one period and one dimension slice. Insert-only."""

    __tablename__ = "measurements"
    __table_args__ = (
        UniqueConstraint("metric_id", "definition_sha256", "as_of", "dims_key"),
        Index("ix_measurements_lookup", "metric_id", "as_of"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    metric_id: Mapped[str] = mapped_column(String(32))
    definition_id: Mapped[int] = mapped_column(ForeignKey("definitions.id"))
    definition_sha256: Mapped[str] = mapped_column(String(64))
    definition_version: Mapped[int] = mapped_column(Integer)
    as_of: Mapped[date] = mapped_column(Date)
    dims_key: Mapped[str] = mapped_column(String(512))
    dimensions: Mapped[dict[str, str]] = mapped_column(JSONB)
    value: Mapped[float | None] = mapped_column(Double)
    status: Mapped[str] = mapped_column(String(16))
    input_batch_hashes: Mapped[list[str]] = mapped_column(JSONB)
    delta_previous: Mapped[float | None] = mapped_column(Double)
    delta_baseline: Mapped[float | None] = mapped_column(Double)
    distance_to_target: Mapped[float | None] = mapped_column(Double)
    calculation: Mapped[dict[str, Any]] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
