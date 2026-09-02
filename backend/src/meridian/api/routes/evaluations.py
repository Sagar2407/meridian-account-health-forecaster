"""Evaluation results over HTTP (plan section 19.1).

Section 19.1 lists `POST /api/evaluations` and `GET /api/evaluations/{eval_id}`,
and the obvious reading -- start a harness in-process and return its metrics --
is the one thing this service must not do.

Every harness lives in `meridian_eval`, which reads outcome labels. Plan section
8.4 makes that boundary structural: no module inside `meridian` may import that
package, and `test_import_boundary.py` fails the build if one does. A route that
ran an evaluation in-process would put label-reading code one HTTP call away
from an unauthenticated caller, which is precisely the leak the boundary exists
to prevent. A lazy import inside the handler would not change that; it would
only hide it from a reader.

So the split is: harnesses run from the command line, where a person chooses to
spend the time and (for the paid arms) the money, and they write versioned
artifacts. This module **reads those artifacts** and nothing else. `POST`
therefore refuses, and says which command to run; `GET` serves what the last run
recorded, or reports plainly that it has not been run.
"""

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from meridian.api.dependencies import SettingsDependency
from meridian.api.errors import ApiError
from meridian.data.paths import repository_root

router = APIRouter(tags=["evaluations"])

#: The published evaluations, and how each is produced. The identifier in the
#: URL is the evaluation's name, not a per-run id: these are reproducible
#: artifacts tied to a commit, so there is exactly one current result each.
EvaluationName = Literal["guardrails", "tot", "retrieval", "system"]

ARTIFACTS: dict[str, tuple[str, str, bool]] = {
    # name: (artifact path relative to the repository root, command, costs money)
    "guardrails": ("artifacts/safety/guardrail_eval.json", "make evaluate-guardrails", False),
    "tot": ("artifacts/tot/tot_ablation.json", "make evaluate-tot", False),
    "retrieval": (
        "artifacts/retrieval/retrieval_benchmark.json",
        "make evaluate-retrieval",
        False,
    ),
    # Plan section 20.6's first three bullets -- correctness, calibration, and
    # grounding -- plus its last. Result directories are named for a commit and
    # a moment, so this reads the summary every run republishes rather than
    # globbing for the newest directory from inside the served application.
    "system": ("artifacts/evaluation/summary.json", "make evaluate-system", False),
}


class StartEvaluationRequest(BaseModel):
    """Which evaluation a caller asked to start."""

    kind: EvaluationName = "guardrails"
    limit: int | None = Field(default=None, ge=1, le=500)


class EvaluationResult(BaseModel):
    """One published evaluation and where it came from."""

    eval_id: str
    status: Literal["published", "not_run"]
    command: str
    artifact: str
    metrics: dict[str, Any] | None = None
    detail: str = ""


@router.post(
    "/evaluations",
    response_model=EvaluationResult,
    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    summary="Evaluations are command-line harnesses, not HTTP calls",
)
def start_evaluation(
    body: StartEvaluationRequest, settings: SettingsDependency
) -> EvaluationResult:
    """Refuse to run an evaluation in-process, and say how to run it.

    Raises:
        ApiError: Always. `REQUEST_BLOCKED`, naming the command to run.
    """

    known = ARTIFACTS.get(body.kind)
    command = known[1] if known else "make evaluate-guardrails"
    _ = settings
    raise ApiError(
        "REQUEST_BLOCKED",
        "Evaluations are not run over HTTP. Every harness reads outcome labels, and "
        "no served module may import the evaluation package (plan section 8.4), so "
        f"they are command-line tools: run `{command}`, then read the result from "
        f"GET /api/evaluations/{body.kind}.",
        detail={"command": command, "evaluation": body.kind},
    )


@router.get(
    "/evaluations/{eval_id}",
    response_model=EvaluationResult,
    summary="Metrics and artifact link for one published evaluation",
)
def read_evaluation(eval_id: str) -> EvaluationResult:
    """Return the metrics the last run of this evaluation recorded.

    Raises:
        ApiError: `ACCOUNT_NOT_FOUND` when the name is not a published evaluation.
    """

    known = ARTIFACTS.get(eval_id)
    if known is None:
        raise ApiError(
            "ACCOUNT_NOT_FOUND",
            f"There is no evaluation named {eval_id}. Published evaluations: {sorted(ARTIFACTS)}.",
            http_status=status.HTTP_404_NOT_FOUND,
        )

    relative, command, _paid = known
    path: Path = repository_root() / relative
    if not path.is_file():
        return EvaluationResult(
            eval_id=eval_id,
            status="not_run",
            command=command,
            artifact=relative,
            detail=(
                "This evaluation has not been run in this checkout. The published "
                f"results are committed under `artifacts/`; regenerate with `{command}`."
            ),
        )

    try:
        metrics = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return EvaluationResult(
            eval_id=eval_id,
            status="not_run",
            command=command,
            artifact=relative,
            detail=f"The artifact could not be read; re-run `{command}`.",
        )

    return EvaluationResult(
        eval_id=eval_id,
        status="published",
        command=command,
        artifact=relative,
        metrics=metrics if isinstance(metrics, dict) else {"result": metrics},
    )


__all__ = [
    "ARTIFACTS",
    "EvaluationName",
    "EvaluationResult",
    "StartEvaluationRequest",
    "router",
]
