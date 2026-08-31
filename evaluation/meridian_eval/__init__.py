"""Evaluation-only access to labels and ground truth (plan section 8.4).

This package is deliberately outside `meridian`. It holds outcomes, health
indices, driver contributions, and the golden question set — everything the
agent is graded against and must never see at runtime.

`backend/tests/test_import_boundary.py` fails the build if any module under
`meridian` imports this package.
"""

from meridian_eval.repository import EvaluationRepository, GoldenQuestion

__all__ = ["EvaluationRepository", "GoldenQuestion"]
