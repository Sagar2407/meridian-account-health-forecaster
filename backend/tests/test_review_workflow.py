"""Human-review persistence and API, end to end (plan section 16.6)."""

import json
import sqlite3
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from meridian.api.main import create_app
from meridian.api.routes.review import get_store
from meridian.contracts import ReviewerDecision
from meridian.memory.store import AssessmentStore, AssessmentStoreError


@pytest.fixture
def review_store(tmp_path: Path) -> Iterator[tuple[AssessmentStore, str]]:
    """Return a store with one red decision waiting for a person."""

    store = AssessmentStore(tmp_path / "assessments.sqlite")
    assessment = store.record_assessment(
        account_id="ACC-1042",
        cutoff=date(2026, 6, 28),
        predicted_outcome="Contracted",
        confidence=0.61,
        decision="red",
        summary="The evidence was materially conflicted.",
        question="What is the renewal outlook?",
        card={"outcome": "Contracted", "confidence": 0.61},
    )
    case = store.open_review_case(
        assessment.assessment_id,
        "an unresolved severe conflict",
        reason_codes=("evidence_conflict",),
    )
    yield store, case.case_id


def _override(case_id: str) -> ReviewerDecision:
    """Return a valid reviewer override."""

    return ReviewerDecision(
        case_id=case_id,
        reviewer="reviewer@example.test",
        action="override",
        reason_code="evidence_contradicts_outcome",
        note="The signed renewal order was not present in the indexed evidence.",
        corrected_outcome="Renewed",
    )


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"corrected_outcome": None}, "must name the outcome"),
        ({"reason_code": "other"}, "specific reason code"),
        ({"note": ""}, "must carry a note"),
    ],
)
def test_an_override_requires_a_supported_outcome_reason_and_note(
    updates: dict[str, Any], message: str
) -> None:
    """An untraceable correction is rejected before persistence."""

    values: dict[str, Any] = {
        "case_id": "CASE-1",
        "reviewer": "reviewer@example.test",
        "action": "override",
        "reason_code": "evidence_contradicts_outcome",
        "note": "The account has already renewed.",
        "corrected_outcome": "Renewed",
    }
    with pytest.raises(ValidationError, match=message):
        ReviewerDecision(**{**values, **updates})


def test_a_data_request_names_the_exact_source() -> None:
    """The request-data action cannot degrade into a generic complaint."""

    with pytest.raises(ValidationError, match="at least one source"):
        ReviewerDecision(
            case_id="CASE-1",
            reviewer="reviewer@example.test",
            action="request_data",
            reason_code="coverage_insufficient",
        )


def test_an_override_resolves_the_case_and_creates_one_linked_regression(
    review_store: tuple[AssessmentStore, str], tmp_path: Path
) -> None:
    """The Phase 7 exit gate is enforced by one atomic store operation."""

    store, case_id = review_store
    resolved, regression = store.resolve_review_case(
        _override(case_id), resolved_at="2026-08-31T12:00:00+00:00"
    )

    assert resolved.status == "resolved"
    assert resolved.action == "override"
    assert regression is not None
    assert regression.case_id == case_id
    assert regression.assessment_id == resolved.assessment_id
    assert regression.origin == "reviewer_override"
    assert regression.system_outcome == "Contracted"
    assert regression.reviewer_outcome == "Renewed"
    assert regression.reason_code == "evidence_contradicts_outcome"

    target = tmp_path / "regressions.jsonl"
    assert store.export_regression_cases(target) == 1
    exported = json.loads(target.read_text(encoding="utf-8"))
    assert exported["regression_id"] == regression.regression_id
    assert exported["case_id"] == case_id

    with pytest.raises(AssessmentStoreError, match="already resolved"):
        store.resolve_review_case(_override(case_id))


def test_an_approval_resolves_without_filing_a_regression(
    review_store: tuple[AssessmentStore, str],
) -> None:
    """Agreement is audit history, not a failure added to the regression set."""

    store, case_id = review_store
    decision = ReviewerDecision(
        case_id=case_id,
        reviewer="reviewer@example.test",
        action="approve",
        reason_code="agrees_with_evidence",
        note="The evidence supports the proposed answer.",
    )
    resolved, regression = store.resolve_review_case(decision)
    assert resolved.action == "approve"
    assert regression is None
    assert store.regression_cases() == ()


def test_review_resolution_rolls_back_if_regression_insertion_fails(
    review_store: tuple[AssessmentStore, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrected answer cannot commit without its regression record."""

    store, case_id = review_store

    def explode(**_: Any) -> Any:
        raise sqlite3.OperationalError("simulated regression write failure")

    monkeypatch.setattr(AssessmentStore, "_insert_regression", staticmethod(explode))
    with pytest.raises(sqlite3.OperationalError, match="simulated"):
        store.resolve_review_case(_override(case_id))

    unchanged = store.review_case(case_id)
    assert unchanged is not None
    assert unchanged.status == "open"
    assert unchanged.reviewer is None
    assert store.regression_cases() == ()


def test_the_queue_validates_its_filter(review_store: tuple[AssessmentStore, str]) -> None:
    """Store callers get the same finite status vocabulary as HTTP callers."""

    store, _ = review_store
    with pytest.raises(AssessmentStoreError, match="status must be"):
        store.review_queue("waiting")


@pytest.mark.requires_dataset
def test_the_review_api_serves_the_card_and_persists_an_override(
    review_store: tuple[AssessmentStore, str],
) -> None:
    """A reviewer can discover and resolve the stored case over HTTP.

    Marked because `GET /api/review-cases` joins each row against the account
    repository for the ACV and renewal date its ordering needs, so the endpoint
    resolves a runtime and reads the raw tables even though this test overrides
    the store. Overriding `get_store` alone is not enough to make it portable.
    """

    store, case_id = review_store
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app)

    queue = client.get("/api/review-cases")
    assert queue.status_code == 200
    assert [row["case_id"] for row in queue.json()] == [case_id]

    card = client.get(f"/api/review-cases/{case_id}")
    assert card.status_code == 200
    assert card.json()["question"] == "What is the renewal outlook?"
    assert card.json()["decision"]["outcome"] == "Contracted"

    response = client.post(
        f"/api/review-cases/{case_id}/decision",
        json={
            "reviewer": "reviewer@example.test",
            "action": "override",
            "reason_code": "evidence_contradicts_outcome",
            "note": "A signed renewal order was missing from the evidence.",
            "corrected_outcome": "Renewed",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["case"]["status"] == "resolved"
    assert payload["regression"]["origin"] == "reviewer_override"
    assert payload["regression"]["case_id"] == case_id

    duplicate = client.post(
        f"/api/review-cases/{case_id}/decision",
        json={
            "reviewer": "reviewer@example.test",
            "action": "approve",
            "reason_code": "agrees_with_evidence",
        },
    )
    assert duplicate.status_code == 409
    assert client.get("/api/review-cases?status=open").json() == []
    assert client.get("/api/review-cases?status=resolved").json()[0]["case_id"] == case_id
    assert client.get("/api/review-regressions").json()[0]["case_id"] == case_id


def test_the_review_api_rejects_missing_cases_and_invalid_actions(
    review_store: tuple[AssessmentStore, str],
) -> None:
    """HTTP errors distinguish a missing case from an invalid decision."""

    store, case_id = review_store
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app)

    assert client.get("/api/review-cases/CASE-missing").status_code == 404
    assert (
        client.post(
            "/api/review-cases/CASE-missing/decision",
            json={
                "reviewer": "reviewer@example.test",
                "action": "approve",
                "reason_code": "agrees_with_evidence",
            },
        ).status_code
        == 404
    )
    invalid = client.post(
        f"/api/review-cases/{case_id}/decision",
        json={
            "reviewer": "reviewer@example.test",
            "action": "override",
            "reason_code": "other",
            "note": "",
        },
    )
    assert invalid.status_code == 422
