"""Who may see which package: staff see all; auditors see what an unexpired grant covers."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from dsec_metrics.db.models import AuditorGrant, ReportLink, ReportPackage

TOKEN_BYTES = 32


def active_grants(db: Session, user_id: UUID, now: datetime) -> list[AuditorGrant]:
    """Grants for a user that have not expired."""
    return list(
        db.scalars(
            select(AuditorGrant)
            .where(AuditorGrant.user_id == user_id, AuditorGrant.expires_at > now)
            .order_by(AuditorGrant.period_start)
        )
    )


def covers(grant: AuditorGrant, package: ReportPackage) -> bool:
    """The grant names one of the package's frameworks and its period contains the
    package's period."""
    return (
        bool(set(grant.frameworks) & set(package.frameworks))
        and grant.period_start <= package.period_start
        and package.period_end <= grant.period_end
    )


def visible(package: ReportPackage, staff: bool, grants: Sequence[AuditorGrant]) -> bool:
    """Whether a caller may see a package."""
    return staff or any(covers(g, package) for g in grants)


def list_packages(db: Session) -> list[ReportPackage]:
    """Every package, newest first, without the ZIP bytes."""
    return list(
        db.scalars(
            select(ReportPackage)
            .options(defer(ReportPackage.content))
            .order_by(ReportPackage.generated_at.desc())
        )
    )


def hash_token(token: str) -> bytes:
    """Links store only the SHA-256 of their token."""
    return hashlib.sha256(token.encode("ascii", "replace")).digest()


def new_link(
    db: Session,
    package: ReportPackage,
    user_id: UUID,
    expires_at: datetime,
    created_by: str,
) -> tuple[str, ReportLink]:
    """Create a link and return the token. The token is shown once and not stored."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    link = ReportLink(
        package_id=package.id,
        user_id=user_id,
        token_hash=hash_token(token),
        expires_at=expires_at,
        created_by=created_by,
    )
    db.add(link)
    db.flush()
    return token, link


def find_link(db: Session, token: str) -> ReportLink | None:
    """The link for a token, if there is one."""
    return db.scalars(select(ReportLink).where(ReportLink.token_hash == hash_token(token))).first()
