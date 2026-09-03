"""The health contract, checked without the dataset present.

This module deliberately does not use the offline graph fixture. `test_health.py`
runs in the backend container, where the raw archive is excluded by design, and
its job is to prove the health endpoint answers *honestly* there: `degraded`,
with the missing subsystem named, rather than `ok` on a container that could not
serve a single assessment.

The full served surface is covered in `test_api_service.py`, which needs the
dataset; the OpenAPI assertion here is the one that must hold everywhere.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meridian.api.main import app
from meridian.api.routes import health
from meridian.api.routes.health import HealthResponse
from meridian.retrieval.index import INDEX_FILENAME

client = TestClient(app)

#: Section 19.1: "service, model, index, database, and provider readiness".
EXPECTED_SUBSYSTEMS = {"dataset", "forecaster", "retrieval_index", "database", "provider"}


def test_health_reports_each_subsystem_separately() -> None:
    """A single `ok` cannot distinguish a ready service from an empty one."""

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = HealthResponse.model_validate(response.json())
    assert payload.service == "meridian-api"
    assert payload.data_mode == "synthetic"
    assert set(payload.subsystems) == EXPECTED_SUBSYSTEMS
    assert all(item.detail for item in payload.subsystems.values())


def test_the_overall_status_follows_the_dataset() -> None:
    """The dataset is the one subsystem nothing degrades around.

    Without it there is no account to assess, so the endpoint must say
    `degraded`. Everything else has a documented weaker answer.
    """

    payload = HealthResponse.model_validate(client.get("/api/health").json())

    if payload.subsystems["dataset"].status == "ready":
        assert payload.status in {"ok", "degraded"}
    else:
        assert payload.status == "degraded"


def test_health_never_returns_provider_configuration() -> None:
    """Section 24.3 forbids returning secrets, and health is unauthenticated."""

    body = client.get("/api/health").text.lower()

    assert "sk-" not in body
    assert "openrouter" not in body
    assert "api_key" not in body
    assert "base_url" not in body


def test_openapi_is_section_19s_endpoint_table() -> None:
    """Every served route is one the plan names, and every named route is served."""

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert set(response.json()["paths"]) == {
        "/api/health",
        "/api/accounts",
        "/api/accounts/{account_id}",
        "/api/assessments",
        "/api/assessments/{run_id}",
        "/api/assessments/{run_id}/events",
        "/api/portfolio-scans",
        "/api/portfolio-scans/{scan_id}",
        "/api/review-cases",
        "/api/review-cases/{case_id}",
        "/api/review-cases/{case_id}/decision",
        "/api/review-regressions",
        "/api/evaluations",
        "/api/evaluations/{eval_id}",
        "/api/demo-runs",
        "/api/demo-runs/{kind}",
    }


def test_an_index_without_its_knowledge_base_is_not_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Shipping the index without the corpus it verifies against is not readiness.

    This is the production failure this assertion exists for. The serving image
    copied the index and the account tables but not `rag_corpus/`, so every
    search raised `FileNotFoundError` inside `load_verified_index`, every
    assessment degraded to telemetry with no forecast -- and `/api/health` went
    on reporting the index ready, because it only looked for the `.faiss` file.
    A health check that cannot see the difference is what let it deploy.
    """

    indexes = tmp_path / "indexes"
    indexes.mkdir()
    (indexes / INDEX_FILENAME).write_bytes(b"")
    monkeypatch.setattr(health, "indexes_directory", lambda: indexes)
    monkeypatch.setattr(health, "knowledge_base_path", lambda: tmp_path / "absent.jsonl")

    absent = health._index()
    assert absent.status == "absent"
    assert "knowledge base" in absent.detail

    present = tmp_path / "knowledge_base.jsonl"
    present.write_text("", encoding="utf-8")
    monkeypatch.setattr(health, "knowledge_base_path", lambda: present)

    assert health._index().status == "ready"


DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"


@pytest.mark.skipif(
    not DOCKERFILE.is_file(),
    reason=(
        "the Dockerfile is absent, so this is not a source checkout. The backend "
        "image does not copy it; this check runs on a developer checkout and in CI."
    ),
)
def test_the_serving_image_ships_what_the_serving_code_reads() -> None:
    """The runtime stage must copy the knowledge base, not only the index.

    A unit test cannot catch a file missing from an image, and building one to
    find out costs minutes. Reading the Dockerfile is the cheap half: it pins
    the copy that was absent, so removing it fails here rather than in a
    deployment.
    """

    runtime = DOCKERFILE.read_text(encoding="utf-8").split("AS runtime", 1)[1]
    assert "rag_corpus/knowledge_base.jsonl" in runtime
