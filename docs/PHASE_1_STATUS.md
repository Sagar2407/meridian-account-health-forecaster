# Phase 1 status: dataset ingestion, validation, and sanitization

Status: **Complete; exit gate passed on 2026-08-31**

Plan section 25 defines the Phase 1 exit gate as "all leakage, cutoff, key, and
reproducibility tests pass". They do. Run them with `make validate-data`.

## Deliverables

| Item | Status | Evidence |
| --- | --- | --- |
| Central loader | PASS | `meridian.data.loader`, the only reader of the raw CSVs |
| Section 8 hardening rules | PASS | Mapped rule-by-rule in `docs/DATA_LINEAGE.md` |
| Runtime / evaluation boundary | PASS | `meridian_eval` is a separate package; enforced by an import test |
| Deterministic splits | PASS | `data/splits/account_split.json`, 60/20/20 stratified by outcome |
| Hash and provenance manifest | PASS | `data/processed/dataset_manifest.json` |
| Sanitized runtime tables | PASS | Five Parquet tables under `data/processed/` |
| `make data` and `make validate-data` | PASS | Both run in Docker via `scripts/python_in_docker.sh` |
| Data-lineage documentation | PASS | `docs/DATA_LINEAGE.md` |

## Exit gate

| Criterion | Result | Evidence |
| --- | --- | --- |
| Zero orphaned foreign keys | PASS | `test_no_orphaned_foreign_keys` |
| Zero duplicate primary or fact-grain keys | PASS | `test_no_duplicate_primary_or_grain_keys` |
| Zero runtime records after their effective cutoff | PASS | `test_no_runtime_record_postdates_its_account_cutoff` |
| Zero forbidden fields in sanitized output | PASS | `test_profile_exposes_no_forbidden_field`, `test_runtime_tables_expose_no_forbidden_field` |
| Exact reproducibility of generated artifacts | PASS | `test_every_table_reproduces_the_shipped_archive` |
| Explicit handling of permitted missing values | PASS | `test_permitted_missing_values_are_explicit` |

Quality gates: 49 tests passing at 96.6% coverage, ruff clean, mypy strict clean
across 29 source files, repository policy scan clean across 100 files.

## What the gate actually caught

Cutoff filtering removes **17,927 fact rows**, about 20% of the fact data,
including 14,931 usage-weeks. Without section 8.2 enforcement that volume of
post-cutoff data would reach the model and the retrieval index.

## Findings recorded

Four issues in the supplied archive are documented in `docs/DATA_LINEAGE.md`,
two of them new:

1. Byte-exact reproduction requires `numpy < 2.5`; numpy 2.5.2 alters one note
   body. The version ceiling is load-bearing and asserted by a test.
2. `adoption_level_last_q` reaches 109.04, contradicting its documented 0–100
   range. The observed scale is authoritative.
3. `days_to_renewal` has zero variance at 90 and must be excluded from Phase 2
   predictive features.
4. External events run to 2026-07-02, past the 2026-06-28 horizon; 114 rows are
   removed by cutoff filtering.

## Known limitation

GitHub Actions cannot exercise the data layer. The synthetic archive is
git-ignored by policy, so the 34 dataset-dependent tests skip in CI and its
coverage threshold is disabled there. The authoritative data gate is
`make validate-data`, which sets `MERIDIAN_REQUIRE_DATASET=1` so a missing
dataset is an error rather than a silent skip. `make phase0-verify` mounts the
archive read-only into the backend container and applies the same flag.

## Carried into Phase 2

- Exclude `days_to_renewal` from training features (zero variance).
- Never use the packaged `churn_probability`; train and calibrate a model.
- Recompute `support_escalation_rate` over observed active weeks, and advanced
  depth from `usage_weekly`, rather than trusting the packaged columns
  (plan section 8.3). Feature computation is Phase 2's responsibility.
