"""The health contract, checked without the dataset present.

This module deliberately does not use the offline graph fixture. `test_health.py`
runs in the backend container, where the raw archive is excluded by design, and
its job is to prove the health endpoint answers *honestly* there: `degraded`,
with the missing subsystem named, rather than `ok` on a container that could not
serve a single assessment.

The full served surface is covered in `test_api_service.py`, which needs the
dataset; the OpenAPI assertion here is the one that must hold everywhere.
"""

from fastapi.testclient import TestClient

from meridian.api.main import app
from meridian.api.routes.health import HealthResponse

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
    }
