"""Shared parameters for the read routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Query, status

from dsec_metrics.api.policy import DbDep, StaffDep
from dsec_metrics.api.queries import EVERYTHING, Catalog, Scope, load_catalog

NAME = r"^[A-Za-z0-9][A-Za-z0-9 _.:-]{0,63}$"
DimensionParam = Annotated[str | None, Query(max_length=64, pattern=NAME)]


def dimension_filters(
    business_unit: DimensionParam = None,
    application: DimensionParam = None,
    environment: DimensionParam = None,
    region: DimensionParam = None,
) -> dict[str, str]:
    """The four measurement dimensions as optional filters."""
    given = {
        "business_unit": business_unit,
        "application": application,
        "environment": environment,
        "region": region,
    }
    return {k: v for k, v in given.items() if v}


FiltersDep = Annotated[dict[str, str], Depends(dimension_filters)]


def caller_scope(principal: StaffDep) -> Scope:
    """Business units the caller may see. Staff only: auditors use the audit room.
    Everything until M5 adds business-unit grants."""
    del principal
    return EVERYTHING


ScopeDep = Annotated[Scope, Depends(caller_scope)]


def catalog(db: DbDep) -> Catalog:
    """Current definitions for this request."""
    return load_catalog(db)


CatalogDep = Annotated[Catalog, Depends(catalog)]


def not_found(what: str) -> HTTPException:
    """A 404 that does not echo the requested id."""
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")
