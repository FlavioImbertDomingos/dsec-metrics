"""Report packages, auditor links, the audit room and the audit log."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from dsec_metrics import audit
from dsec_metrics.api.policy import (
    AdminDep,
    AuthorDep,
    DbDep,
    Principal,
    PrincipalDep,
    SettingsDep,
)
from dsec_metrics.api.routes.auth import client_address
from dsec_metrics.auth.users import find_user
from dsec_metrics.config import Settings
from dsec_metrics.db.models import AuditEvent, AuditorGrant, ReportPackage, User
from dsec_metrics.reports import access
from dsec_metrics.reports.builder import generate
from dsec_metrics.reports.data import ReportError, ReportRequest
from dsec_metrics.reports.signing import SigningKey, SigningKeyError, load_private, public_pem

router = APIRouter(tags=["reports"])

PackageId = Annotated[UUID, Path()]
MAX_LINK_DAYS = 90


class ReportOut(BaseModel):
    """A stored package, without its bytes."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    report_type: str
    title: str
    scope: dict[str, Any]
    period_start: date
    period_end: date
    frameworks: list[str]
    manifest_sha256: str
    key_fingerprint: str
    pdf_rendered: bool
    generated_by: str
    generated_at: datetime
    size: int


class LinkRequest(BaseModel):
    """Who the link is for and how long it lasts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    days: int = Field(default=7, ge=1, le=MAX_LINK_DAYS)


class LinkOut(BaseModel):
    """A new link. The token is in the URL and is shown only this once."""

    model_config = ConfigDict(frozen=True)

    url: str
    expires_at: datetime
    username: str


class PublicKeyOut(BaseModel):
    """The key auditors check package signatures against."""

    model_config = ConfigDict(frozen=True)

    algorithm: str
    fingerprint: str
    pem: str


class GrantOut(BaseModel):
    """An auditor grant."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    username: str
    frameworks: list[str]
    period_start: date
    period_end: date
    expires_at: datetime


class EventOut(BaseModel):
    """One audit log entry."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    seq: int
    occurred_at: datetime
    actor: str
    action: str
    target: str
    details: dict[str, Any]
    prev_hash: str
    hash: str


class AuditRoomOut(BaseModel):
    """The auditor's landing page."""

    model_config = ConfigDict(frozen=True)

    auditor: bool
    grants: list[GrantOut]
    packages: list[ReportOut]
    access_log: list[EventOut]


class ChainOut(BaseModel):
    """Result of checking the audit chain."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    checked: int
    broken_at: int | None
    reason: str | None
    head: str


def _key(settings: Settings) -> SigningKey:
    if settings.report_signing_key_file is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Report signing is not set up")
    try:
        return load_private(settings.report_signing_key_file)
    except SigningKeyError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Report signing key cannot be read"
        ) from None


def _viewer(principal: Principal) -> None:
    """Staff and auditors only; other roles (or none) get nothing here."""
    if not principal.is_staff and "auditor" not in principal.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")


def _grants(db: DbDep, principal: Principal) -> list[AuditorGrant]:
    return access.active_grants(db, principal.user_id, datetime.now(UTC))


def _package(db: DbDep, principal: Principal, package_id: UUID) -> ReportPackage:
    _viewer(principal)
    package = db.get(ReportPackage, package_id)
    if package is None or not access.visible(package, principal.is_staff, _grants(db, principal)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    return package


def _filename(package: ReportPackage) -> str:
    kind = re.sub(r"[^a-z0-9-]", "-", package.report_type)
    return f"dsec-{kind}-{package.period_end.isoformat()}-{str(package.id)[:8]}.zip"


def _download(
    db: DbDep, request: Request, principal: Principal, package: ReportPackage, via: str
) -> Response:
    audit.record(
        db,
        principal.username,
        "report.download",
        f"report:{package.id}",
        {
            "via": via,
            "source": client_address(request),
            "manifest_sha256": package.manifest_sha256,
            "auditor": not principal.is_staff,
        },
    )
    db.commit()
    return Response(
        content=package.content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{_filename(package)}"'},
    )


@router.get("/reports")
def list_reports(db: DbDep, principal: PrincipalDep) -> list[ReportOut]:
    """Packages the caller may see: all for staff, granted ones for auditors."""
    _viewer(principal)
    grants = _grants(db, principal)
    return [
        ReportOut.model_validate(p)
        for p in access.list_packages(db)
        if access.visible(p, principal.is_staff, grants)
    ]


@router.post("/reports", status_code=status.HTTP_201_CREATED)
def create_report(
    body: ReportRequest, db: DbDep, principal: AuthorDep, settings: SettingsDep
) -> ReportOut:
    """Build, sign and store a package from stored data."""
    key = _key(settings)
    try:
        generated = generate(db, body, key, principal.username)
    except ReportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    db.commit()
    return ReportOut.model_validate(generated.row)


@router.get("/reports/public-key")
def public_key(principal: PrincipalDep, settings: SettingsDep) -> PublicKeyOut:
    """The Ed25519 public key that signs packages, for pinning."""
    _viewer(principal)
    key = _key(settings)
    return PublicKeyOut(
        algorithm="Ed25519", fingerprint=key.fingerprint, pem=public_pem(key.public)
    )


@router.get("/reports/{package_id}")
def get_report(package_id: PackageId, db: DbDep, principal: PrincipalDep) -> ReportOut:
    """One package's metadata."""
    return ReportOut.model_validate(_package(db, principal, package_id))


@router.get("/reports/{package_id}/download")
def download_report(
    package_id: PackageId, request: Request, db: DbDep, principal: PrincipalDep
) -> Response:
    """The ZIP. Every download is written to the audit log."""
    package = _package(db, principal, package_id)
    return _download(db, request, principal, package, "direct")


@router.post("/reports/{package_id}/links", status_code=status.HTTP_201_CREATED)
def create_link(
    package_id: PackageId, body: LinkRequest, db: DbDep, principal: AuthorDep
) -> LinkOut:
    """A time-limited link for one auditor. It never outlives the auditor's grant."""
    package = _package(db, principal, package_id)
    user: User | None = find_user(db, body.username)
    now = datetime.now(UTC)
    grants = access.active_grants(db, user.id, now) if user else []
    covering = [g for g in grants if access.covers(g, package)]
    if user is None or "auditor" not in (user.roles or []) or not covering:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "That user is not an auditor with a current grant covering this report",
        )
    expires = min(now + timedelta(days=body.days), max(g.expires_at for g in covering))
    token, link = access.new_link(db, package, user.id, expires, principal.username)
    audit.record(
        db,
        principal.username,
        "report.link",
        f"report:{package.id}",
        {"for": user.username, "link_id": str(link.id), "expires_at": expires.isoformat()},
    )
    db.commit()
    return LinkOut(url=f"/api/links/{token}", expires_at=expires, username=user.username)


@router.get("/links/{token}")
def follow_link(
    token: Annotated[str, Path(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")],
    request: Request,
    db: DbDep,
    principal: PrincipalDep,
) -> Response:
    """Download through a link. Only the named auditor, and only before it expires."""
    link = access.find_link(db, token)
    now = datetime.now(UTC)
    if link is None or link.user_id != principal.user_id or link.expires_at <= now:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found or expired")
    package = db.get(ReportPackage, link.package_id)
    grants = access.active_grants(db, principal.user_id, now)
    if package is None or not access.visible(package, principal.is_staff, grants):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found or expired")
    return _download(db, request, principal, package, f"link:{link.id}")


@router.get("/audit-room")
def audit_room(db: DbDep, principal: PrincipalDep) -> AuditRoomOut:
    """Grants, packages and downloads. Auditors see only their own."""
    _viewer(principal)
    auditor = not principal.is_staff
    now = datetime.now(UTC)
    stmt = select(AuditorGrant, User.username).join(User, User.id == AuditorGrant.user_id)
    if auditor:
        stmt = stmt.where(AuditorGrant.user_id == principal.user_id, AuditorGrant.expires_at > now)
    grants = [
        GrantOut(
            id=g.id,
            username=name,
            frameworks=g.frameworks,
            period_start=g.period_start,
            period_end=g.period_end,
            expires_at=g.expires_at,
        )
        for g, name in db.execute(stmt.order_by(AuditorGrant.expires_at.desc())).all()
    ]
    active = access.active_grants(db, principal.user_id, now)
    packages = [
        ReportOut.model_validate(p)
        for p in access.list_packages(db)
        if access.visible(p, principal.is_staff, active)
    ]
    log_stmt = select(AuditEvent).where(AuditEvent.action == "report.download")
    if auditor:
        log_stmt = log_stmt.where(AuditEvent.actor == principal.username)
    downloads = db.scalars(log_stmt.order_by(AuditEvent.seq.desc()).limit(200)).all()
    return AuditRoomOut(
        auditor=auditor,
        grants=grants,
        packages=packages,
        access_log=[EventOut.model_validate(e) for e in downloads],
    )


@router.get("/audit/events")
def audit_events(
    db: DbDep,
    principal: AdminDep,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    action: Annotated[str | None, Query(pattern=r"^[a-z_.]{1,64}$")] = None,
) -> list[EventOut]:
    """The audit log, newest first, a page at a time."""
    del principal
    stmt = select(AuditEvent)
    if before is not None:
        stmt = stmt.where(AuditEvent.seq < before)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    rows = db.scalars(stmt.order_by(AuditEvent.seq.desc()).limit(limit)).all()
    return [EventOut.model_validate(e) for e in rows]


@router.get("/audit/verify")
def audit_verify(db: DbDep, principal: AdminDep) -> ChainOut:
    """Recompute the chain and report the first broken link."""
    del principal
    result = audit.verify_chain(db)
    return ChainOut(
        ok=result.ok,
        checked=result.checked,
        broken_at=result.broken_at,
        reason=result.reason,
        head=result.head,
    )
