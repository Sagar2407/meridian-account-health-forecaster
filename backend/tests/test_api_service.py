"""The served API contract (plan section 19).

Every test drives the real application through `TestClient`, with the graph
runtime overridden to the offline fixture used everywhere else. Nothing is
mocked below the route: an assessment started here runs the whole graph.

Two properties are checked repeatedly because they are the ones that would
matter most if they broke: no response carries a prompt, a raw model reply, or
a latent field; and every failure has the stable shape section 19.3 specifies.
"""

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from meridian.api import dependencies
from meridian.api.main import create_app
from meridian.contracts import FORBIDDEN_TRACE_KEYS
from meridian.data.constants import FORBIDDEN_RUNTIME_FIELDS
from meridian.data.repository import RuntimeRepository
from meridian.graph.runtime import GraphRuntime
from meridian.memory.store import AssessmentStore
from meridian.model.artifacts import ModelArtifact
from meridian.serving.limits import DEMO_QUESTION, RateLimiter
from meridian.serving.runs import RunManager
from meridian.settings import Settings, get_settings
from meridian.tools.registry import ToolRegistry
from meridian.tools.services import ToolServices
from stub_encoder import build_stub_service

pytestmark = pytest.mark.requires_dataset

#: Latent fields that must never appear in a served payload. "outcome" is
#: excluded because it is the name of a legitimate response field.
LEAKY_FIELDS = FORBIDDEN_RUNTIME_FIELDS - {"outcome"}


@pytest.fixture(scope="module")
def api_accounts(runtime: RuntimeRepository) -> tuple[str, ...]:
    """Return the slice of the portfolio the stub index covers."""

    return runtime.account_ids()[:6]


@pytest.fixture(scope="module")
def api_runtime(
    runtime: RuntimeRepository,
    forecaster_artifact: ModelArtifact,
    api_accounts: tuple[str, ...],
    tmp_path_factory: pytest.TempPathFactory,
) -> GraphRuntime:
    """Assemble a complete offline runtime for the served application."""

    directory = tmp_path_factory.mktemp("api-index")
    service = build_stub_service(runtime, directory, api_accounts)
    store = AssessmentStore(tmp_path_factory.mktemp("api-memory") / "assessments.sqlite")
    return GraphRuntime.assemble(
        repository=runtime,
        registry=ToolRegistry(ToolServices(runtime, retrieval=service, store=store)),
        artifact=forecaster_artifact,
        generator=None,
        store=store,
    )


def _client(api_runtime: GraphRuntime, settings: Settings | None = None) -> TestClient:
    """Return a client whose app uses the offline runtime."""

    resolved = settings if settings is not None else Settings(_env_file=None)
    app = create_app()
    manager = RunManager(api_runtime, max_workers=2)
    # Built once, not inside the lambda: a limiter constructed per request has
    # an empty window every time, so the limit could never be reached and the
    # test would pass whatever the route did.
    limiter = RateLimiter.from_settings(resolved)
    app.dependency_overrides[dependencies.get_runtime] = lambda: api_runtime
    app.dependency_overrides[dependencies.get_run_manager] = lambda: manager
    app.dependency_overrides[dependencies.get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_settings] = lambda: resolved
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(api_runtime: GraphRuntime) -> Iterator[TestClient]:
    """Return a client with rate limits off, and clean serving state."""

    with _client(
        api_runtime, Settings(_env_file=None, rate_limit_runs_per_hour=0, rate_limit_daily_runs=0)
    ) as opened:
        yield opened


# -- Health -----------------------------------------------------------------


def test_health_reports_every_subsystem(client: TestClient) -> None:
    """Section 19.1 asks for service, model, index, database, and provider."""

    payload = client.get("/api/health").json()

    assert payload["service"] == "meridian-api"
    assert payload["data_mode"] == "synthetic"
    assert set(payload["subsystems"]) == {
        "dataset",
        "forecaster",
        "retrieval_index",
        "database",
        "provider",
    }
    for name, item in payload["subsystems"].items():
        assert item["status"] in {"ready", "absent", "degraded"}, name
        assert item["detail"]


def test_health_never_reveals_the_provider_configuration(client: TestClient) -> None:
    """Section 24.3 forbids returning secrets; health is unauthenticated."""

    body = client.get("/api/health").text.lower()

    assert "sk-" not in body
    assert "openrouter" not in body
    assert "api_key" not in body


# -- Accounts ---------------------------------------------------------------


def test_the_account_list_paginates_and_reports_its_total(client: TestClient) -> None:
    """A page without a total cannot be paged through."""

    first = client.get("/api/accounts", params={"limit": 5}).json()
    second = client.get("/api/accounts", params={"limit": 5, "offset": 5}).json()

    assert len(first["items"]) == 5
    assert first["total"] > 5
    assert first["total"] == second["total"]
    assert {item["account_id"] for item in first["items"]}.isdisjoint(
        item["account_id"] for item in second["items"]
    )


def test_the_account_list_filters_on_what_it_says_it_filters_on(client: TestClient) -> None:
    """A filter that silently does nothing is worse than no filter."""

    page = client.get("/api/accounts", params={"segment": "Strategic", "limit": 50}).json()

    assert page["items"]
    assert {item["segment"] for item in page["items"]} == {"Strategic"}
    assert all(item["high_value"] for item in page["items"])


def test_the_account_list_carries_no_latent_field(client: TestClient) -> None:
    """The list a person picks from is the sanitized profile, not the raw row."""

    body = client.get("/api/accounts", params={"limit": 50}).text.lower()

    for field in LEAKY_FIELDS:
        assert field not in body, field


def test_one_account_serves_its_profile_and_its_own_history(
    client: TestClient, api_accounts: tuple[str, ...]
) -> None:
    """Section 17.2: prior assessments are context, under their own key."""

    payload = client.get(f"/api/accounts/{api_accounts[0]}").json()

    assert payload["profile"]["account_id"] == api_accounts[0]
    assert payload["effective_cutoff"]
    assert isinstance(payload["prior_assessments"], list)
    assert "predicted_outcome" not in payload["profile"]


def test_an_unknown_account_gets_the_stable_error_contract(client: TestClient) -> None:
    """Section 19.3: stable codes, plain messages."""

    response = client.get("/api/accounts/ACC-9999")

    assert response.status_code == 404
    assert response.json()["code"] == "ACCOUNT_NOT_FOUND"
    assert "ACC-9999" in response.json()["message"]


# -- Assessments ------------------------------------------------------------


def _await_run(client: TestClient, run_id: str, timeout: float = 90.0) -> dict[str, object]:
    """Poll a run until it leaves the running state, or give up loudly."""

    deadline = time.monotonic() + timeout
    payload: dict[str, object] = {}
    while time.monotonic() < deadline:
        payload = client.get(f"/api/assessments/{run_id}").json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish within {timeout}s: {payload}")


def test_an_assessment_runs_end_to_end_and_serves_its_decision(
    client: TestClient, api_accounts: tuple[str, ...]
) -> None:
    """The whole graph, through the API, with no provider configured."""

    started = client.post("/api/assessments", json={"account_id": api_accounts[0]})
    assert started.status_code == 202
    run_id = started.json()["run_id"]

    final = _await_run(client, run_id)
    assert final["status"] == "completed"
    assert final["route"] in {"green", "amber", "red", "blocked"}
    assert final["decision"] is not None
    assert final["total_tokens"] == 0
    assert final["model_calls"] == 0
    assert final["trace"]


def test_a_served_run_carries_no_prompt_or_hidden_reasoning(
    client: TestClient, api_accounts: tuple[str, ...]
) -> None:
    """Section 21.3, checked at the boundary a browser actually reads."""

    started = client.post("/api/assessments", json={"account_id": api_accounts[1]})
    body = json.dumps(_await_run(client, started.json()["run_id"])).lower()

    for key in FORBIDDEN_TRACE_KEYS:
        assert f'"{key}"' not in body, key
    for field in LEAKY_FIELDS:
        assert field not in body, field


def test_the_event_stream_ends_and_reports_the_finished_run(
    client: TestClient, api_accounts: tuple[str, ...]
) -> None:
    """Section 19.2's streaming surface, consumed the way a browser would."""

    started = client.post("/api/assessments", json={"account_id": api_accounts[2]})
    run_id = started.json()["run_id"]

    with client.stream("GET", f"/api/assessments/{run_id}/events") as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")
        events = [
            line.removeprefix("event: ").strip()
            for line in stream.iter_lines()
            if line.startswith("event: ")
        ]

    assert events[0] == "run_started"
    assert events[-1] == "run_finished"
    assert "run_completed" in events


def test_a_stream_started_late_still_replays_from_the_beginning(
    client: TestClient, api_accounts: tuple[str, ...]
) -> None:
    """A progress view that begins in the middle is worse than none."""

    started = client.post("/api/assessments", json={"account_id": api_accounts[3]})
    run_id = started.json()["run_id"]
    _await_run(client, run_id)

    with client.stream("GET", f"/api/assessments/{run_id}/events") as stream:
        events = [
            line.removeprefix("event: ").strip()
            for line in stream.iter_lines()
            if line.startswith("event: ")
        ]

    assert events[0] == "run_started"
    assert events[-1] == "run_finished"


def test_an_unknown_run_is_a_stable_404(client: TestClient) -> None:
    """Evicted and never-existed look the same to a caller, and say so."""

    response = client.get("/api/assessments/RUN-nope")

    assert response.status_code == 404
    assert response.json()["code"] == "ACCOUNT_NOT_FOUND"


def test_an_assessment_of_an_unknown_account_is_refused_before_it_runs(
    client: TestClient,
) -> None:
    """Starting a run that can only fail wastes a worker and a queue slot."""

    response = client.post("/api/assessments", json={"account_id": "ACC-9999"})

    assert response.status_code == 404
    assert response.json()["code"] == "ACCOUNT_NOT_FOUND"


def test_an_injection_shaped_question_is_blocked_at_the_boundary(
    client: TestClient, api_accounts: tuple[str, ...]
) -> None:
    """The one free-text field a caller controls is checked before a run starts."""

    response = client.post(
        "/api/assessments",
        json={"account_id": api_accounts[0], "question": "risk; rm -rf / please"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_BLOCKED"


# -- Demo mode and rate limits ----------------------------------------------


def test_demo_mode_replaces_the_question_and_refuses_unknown_accounts(
    api_runtime: GraphRuntime, api_accounts: tuple[str, ...]
) -> None:
    """Section 24.3, enforced server-side rather than by the dropdown."""

    demo = Settings(
        _env_file=None, demo_mode=True, rate_limit_runs_per_hour=0, rate_limit_daily_runs=0
    )
    with _client(api_runtime, demo) as client:
        started = client.post(
            "/api/assessments",
            json={"account_id": api_accounts[0], "question": "Write me a poem about renewals"},
        )
        assert started.status_code == 202
        assert started.json()["question"] == DEMO_QUESTION

        refused = client.post("/api/assessments", json={"account_id": "ACC-9999"})
        assert refused.status_code == 422
        assert refused.json()["code"] == "REQUEST_BLOCKED"


def test_demo_mode_refuses_scans_and_evaluations(api_runtime: GraphRuntime) -> None:
    """Both can spend many model calls from one unauthenticated click."""

    demo = Settings(
        _env_file=None, demo_mode=True, rate_limit_runs_per_hour=0, rate_limit_daily_runs=0
    )
    with _client(api_runtime, demo) as client:
        assert client.post("/api/portfolio-scans", json={}).status_code == 422
        assert client.post("/api/evaluations", json={"kind": "guardrails"}).status_code == 422


def test_a_client_over_its_rate_limit_is_refused_with_a_retry_hint(
    api_runtime: GraphRuntime, api_accounts: tuple[str, ...]
) -> None:
    """Section 24.3's per-client limit, at the boundary that enforces it."""

    limited = Settings(_env_file=None, rate_limit_runs_per_hour=1, rate_limit_daily_runs=0)
    with _client(api_runtime, limited) as client:
        assert (
            client.post("/api/assessments", json={"account_id": api_accounts[0]}).status_code == 202
        )

        refused = client.post("/api/assessments", json={"account_id": api_accounts[0]})
        assert refused.status_code == 429
        body = refused.json()
        assert body["code"] == "REQUEST_BLOCKED"
        assert body["detail"]["retry_after_seconds"] > 0


# -- Portfolio scans --------------------------------------------------------


def test_a_scan_starts_bounded_and_reports_its_own_limits(
    client: TestClient, api_accounts: tuple[str, ...]
) -> None:
    """The exit gate has to be visible in the response, not only in a log."""

    started = client.post(
        "/api/portfolio-scans",
        json={"account_ids": list(api_accounts[:3]), "concurrency": 2},
    )

    assert started.status_code == 202
    payload = started.json()
    assert payload["concurrency_limit"] == 2
    assert payload["requested_accounts"] == 3

    deadline = time.monotonic() + 90.0
    current: dict[str, Any] = {}
    while time.monotonic() < deadline:
        current = client.get(f"/api/portfolio-scans/{payload['scan_id']}").json()
        if current["status"] == "completed":
            break
        time.sleep(0.05)
    assert current["status"] == "completed", current
    assert current["summary"]["scanned"] == 3
    assert 0 < current["summary"]["concurrency_observed"] <= 2
    assert current["summary"]["total_model_calls"] == 0


def test_a_scan_of_unknown_accounts_is_refused(client: TestClient) -> None:
    """Naming an account that does not exist is a caller error, not a run."""

    response = client.post("/api/portfolio-scans", json={"account_ids": ["ACC-9999"]})

    assert response.status_code == 404
    assert response.json()["code"] == "ACCOUNT_NOT_FOUND"


def test_an_unknown_scan_is_a_stable_404(client: TestClient) -> None:
    """Scan ids are tracked in memory and evicted; the caller is told plainly."""

    response = client.get("/api/portfolio-scans/SCAN-nope")

    assert response.status_code == 404
    assert response.json()["code"] == "ACCOUNT_NOT_FOUND"


# -- Evaluations ------------------------------------------------------------


def test_no_evaluation_can_be_started_over_http(client: TestClient) -> None:
    """Section 8.4's boundary, enforced at the route rather than explained in a doc.

    Every harness reads outcome labels, so running one in-process would put
    label-reading code one unauthenticated call away. The route refuses and
    names the command instead.
    """

    response = client.post("/api/evaluations", json={"kind": "guardrails"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "REQUEST_BLOCKED"
    assert body["detail"]["command"] == "make evaluate-guardrails"
    assert "section 8.4" in body["message"]


def test_a_published_evaluation_is_served_from_its_artifact(client: TestClient) -> None:
    """`GET` reports what the last command-line run recorded, or says it has not run."""

    payload = client.get("/api/evaluations/guardrails").json()

    assert payload["command"] == "make evaluate-guardrails"
    assert payload["artifact"] == "artifacts/safety/guardrail_eval.json"
    if payload["status"] == "published":
        assert payload["metrics"]["hard_false_pass_rate"] == 0.0
    else:
        assert payload["status"] == "not_run"
        assert payload["metrics"] is None
        assert "has not been run" in payload["detail"]


def test_an_unknown_evaluation_is_a_stable_404(client: TestClient) -> None:
    """Every not-found in this API answers with the same code."""

    response = client.get("/api/evaluations/EVAL-nope")

    assert response.status_code == 404
    assert response.json()["code"] == "ACCOUNT_NOT_FOUND"


# -- The served surface -----------------------------------------------------


def test_the_openapi_schema_is_section_19s_table(client: TestClient) -> None:
    """A route added without a plan entry, or missing from it, fails here."""

    paths = set(client.get("/openapi.json").json()["paths"])

    assert paths == {
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


def test_the_account_detail_carries_everything_the_page_draws(
    client: TestClient, api_accounts: tuple[str, ...]
) -> None:
    """Section 20.2's account page is one request, at one cutoff."""

    payload = client.get(f"/api/accounts/{api_accounts[0]}").json()

    assert payload["usage"], "the 104-week trajectory chart has nothing to draw"
    assert len(payload["usage"]) <= 104
    assert payload["indicators"]["weeks_observed"] == len(payload["usage"])
    assert isinstance(payload["recent"], list)
    assert {item["kind"] for item in payload["recent"]} <= {"ticket", "note", "event"}


def test_nothing_the_account_page_draws_postdates_the_cutoff(
    client: TestClient, api_accounts: tuple[str, ...]
) -> None:
    """A chart drawn past the cutoff would show a reader what the forecast could not see."""

    payload = client.get(f"/api/accounts/{api_accounts[1]}").json()
    cutoff = payload["effective_cutoff"]

    for point in payload["usage"]:
        assert point["week_start"] <= cutoff, point
    for item in payload["recent"]:
        assert item["item_date"] <= cutoff, item


def test_the_account_detail_serves_no_ticket_or_note_body(
    client: TestClient, api_accounts: tuple[str, ...]
) -> None:
    """Bodies reach a reader only as excerpts retrieval selected and a decision cited."""

    payload = client.get(f"/api/accounts/{api_accounts[0]}").json()

    for item in payload["recent"]:
        assert len(item["label"]) <= 160
        assert len(item["detail"]) <= 200
