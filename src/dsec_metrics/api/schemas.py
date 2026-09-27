"""Request and response models. Every field is validated; unknown fields are rejected."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base for API models: reject unknown fields, strip whitespace on strings."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)


class HealthResponse(StrictModel):
    """Liveness or readiness result."""

    status: str


class MetaResponse(StrictModel):
    """Product identity for the front end."""

    product_name: str
    version: str
    mode: str


class LoginRequest(StrictModel):
    """Development-mode sign-in."""

    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=1, max_length=256)


class MeResponse(StrictModel):
    """The signed-in user and the CSRF token for unsafe requests."""

    username: str
    display_name: str
    csrf_token: str
    roles: list[str] = Field(default_factory=list)


class ErrorResponse(StrictModel):
    """Error body. Messages are generic on purpose."""

    detail: str
