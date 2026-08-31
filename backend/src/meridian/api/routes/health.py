from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from meridian.settings import get_settings

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Stable contract used by people, containers, and deployment probes."""

    status: Literal["ok"]
    service: str
    version: str
    environment: str
    data_mode: Literal["synthetic"]


@router.get("/health", response_model=HealthResponse, summary="Service health")
def health() -> HealthResponse:
    """Report liveness without touching data or external providers."""

    settings = get_settings()
    return HealthResponse(
        status="ok",
        service="meridian-api",
        version=settings.app_version,
        environment=settings.environment,
        data_mode="synthetic",
    )
