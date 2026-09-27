"""Product identity for the front end."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from dsec_metrics.__about__ import PRODUCT_NAME, __version__
from dsec_metrics.api.policy import SettingsDep, public
from dsec_metrics.api.schemas import MetaResponse

router = APIRouter(tags=["meta"])


@router.get(
    "/meta",
    dependencies=[Depends(public("sign-in page shows the product name and mode"))],
)
def meta(settings: SettingsDep) -> MetaResponse:
    """Product name, version and run mode."""
    return MetaResponse(product_name=PRODUCT_NAME, version=__version__, mode=settings.mode)
