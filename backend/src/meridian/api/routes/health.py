"""Readiness for every subsystem a run depends on (plan section 19.1).

Section 19.1 asks health to report "service, model, index, database, and
provider readiness". A liveness probe that only proves the process is running
would say `ok` on a container with no forecaster and no index, which is exactly
the deployment that fails on its first real request.

So each subsystem is reported separately and the overall status is derived. Two
of them are allowed to be absent -- the system degrades rather than fails
without a forecaster or a provider -- and the response says `degraded` rather
than `ok` so that a deployment check can tell the difference.

Nothing here builds anything. Probing readiness by loading the index would make
the health check the most expensive endpoint in the service.
"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from meridian.data.paths import application_directory, raw_tables_directory
from meridian.memory.store import STORE_FILENAME
from meridian.model.artifacts import models_directory
from meridian.retrieval.documents import knowledge_base_path
from meridian.retrieval.index import INDEX_FILENAME, indexes_directory
from meridian.settings import get_settings

router = APIRouter(tags=["system"])

Readiness = Literal["ready", "absent", "degraded"]


class SubsystemHealth(BaseModel):
    """One dependency's readiness and why."""

    status: Readiness
    detail: str


class HealthResponse(BaseModel):
    """Stable contract used by people, containers, and deployment probes."""

    status: Literal["ok", "degraded"]
    service: str
    version: str
    environment: str
    data_mode: Literal["synthetic"]
    demo_mode: bool
    subsystems: dict[str, SubsystemHealth]


def _dataset() -> SubsystemHealth:
    """Report whether the sanitized source tables are present."""

    if (raw_tables_directory() / "accounts.csv").is_file():
        return SubsystemHealth(status="ready", detail="source tables are present")
    return SubsystemHealth(
        status="absent",
        detail="the extracted archive is not mounted; no assessment can run",
    )


def _forecaster() -> SubsystemHealth:
    """Report whether the calibrated artifact is on disk."""

    if any(models_directory().glob("*.joblib")):
        return SubsystemHealth(status="ready", detail="a calibrated artifact is available")
    return SubsystemHealth(
        status="absent",
        detail="no forecaster artifact; runs degrade to verified telemetry with no label",
    )


def _index() -> SubsystemHealth:
    """Report whether retrieval can actually run.

    Two files, not one. Every search calls `load_verified_index`, which rebuilds
    the parent documents to check the index against the corpus this code
    produces today, and that reads the knowledge base. An index file with no
    knowledge base beside it is a container where retrieval raises on the first
    request while this endpoint says it is ready -- which is exactly how it
    reached a deployment.
    """

    if not (indexes_directory() / INDEX_FILENAME).is_file():
        return SubsystemHealth(
            status="absent", detail="no retrieval index; build it with `make index`"
        )
    if not knowledge_base_path().is_file():
        return SubsystemHealth(
            status="absent",
            detail="an index is present but the knowledge base it is verified against is missing",
        )
    return SubsystemHealth(status="ready", detail="a retrieval index is present")


def _database() -> SubsystemHealth:
    """Report whether application memory is writable."""

    directory = application_directory()
    if (directory / STORE_FILENAME).is_file():
        return SubsystemHealth(status="ready", detail="application memory exists")
    if directory.parent.is_dir():
        return SubsystemHealth(
            status="ready", detail="application memory will be created on first write"
        )
    return SubsystemHealth(status="absent", detail="the application directory is not writable")


def _provider() -> SubsystemHealth:
    """Report whether a language-model provider is configured.

    Never returns the key, the base URL, or a provider error message: section
    24.3 forbids returning secrets, and a health endpoint is unauthenticated.
    """

    settings = get_settings()
    if settings.llm_is_configured:
        return SubsystemHealth(status="ready", detail=f"provider {settings.llm_provider}")
    return SubsystemHealth(
        status="absent",
        detail="no provider configured; narratives are generated deterministically",
    )


@router.get("/health", response_model=HealthResponse, summary="Service health")
def health() -> HealthResponse:
    """Report readiness without touching data or calling a provider."""

    settings = get_settings()
    subsystems = {
        "dataset": _dataset(),
        "forecaster": _forecaster(),
        "retrieval_index": _index(),
        "database": _database(),
        "provider": _provider(),
    }
    # Only the dataset is load-bearing. Everything else degrades to a documented
    # weaker answer, which is a state to report rather than a failure to hide.
    overall: Literal["ok", "degraded"] = (
        "ok" if subsystems["dataset"].status == "ready" else "degraded"
    )
    if any(item.status == "absent" for name, item in subsystems.items() if name != "provider"):
        overall = "degraded" if overall == "ok" else overall
    return HealthResponse(
        status=overall,
        service="meridian-api",
        version=settings.app_version,
        environment=settings.environment,
        data_mode="synthetic",
        demo_mode=settings.demo_mode,
        subsystems=subsystems,
    )


__all__ = ["HealthResponse", "SubsystemHealth", "router"]
