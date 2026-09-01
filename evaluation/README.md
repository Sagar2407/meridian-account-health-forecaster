# Evaluation boundary

Forecasting, retrieval, orchestration, safety, calibration, latency, and ablation
evaluation code lives here. Evaluation-only labels and artifacts remain
physically separate from runtime inputs; `backend/tests/test_import_boundary.py`
enforces that direction.

Phase 7's `meridian_eval.guardrail_eval` runs all 36 packaged cases through the
real graph and grades hard refusals separately from answerable behavioural
checks. Reproduce its JSON, CSV, and Markdown artifacts without a provider or
API key with:

```bash
make evaluate-guardrails
```
