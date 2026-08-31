# Data Safety

## Policy objective

Prevent point-in-time leakage, target leakage, cross-account evidence contamination, source mutation, and unsupported claims. Data safety must be implemented before modeling, retrieval, or agent orchestration.

## Canonical dataset

- Archive SHA-256: `0b6a82d8dbb3b62b29cad0e24c7025ff99ed3d5114e427016ffb6543efa7d26f`
- Random seed: `20260721`
- Dataset as-of date: `2026-06-28`
- Forecast horizon: 90 days
- Accounts: 260
- Raw extracted location: `data/raw/meridian-account-health/`

The unchanged ZIP remains at the repository root. Extracted raw files are immutable inputs.

## Point-in-time rule

For each account:

```text
effective_cutoff(account) = min(account.forecast_as_of_date, 2026-06-28)
```

Every row, document, metric window, model feature, citation, and prior assessment used at runtime must be available on or before that cutoff.

This cannot be left to prompting. It must be enforced and tested in the data repository, tools, index builder, retriever, and output verifier.

## Verified raw-data exposure

The source package intentionally contains records after per-account effective cutoffs:

| Source | Rows after effective cutoff |
| --- | ---: |
| Weekly usage | 14,931 |
| Support tickets | 1,506 |
| CSM notes and QBRs | 1,376 |
| External events | 114 |

The external-event table also contains two records after the dataset-wide as-of date, with a maximum date of `2026-07-02`.

Therefore raw CSVs and the packaged corpus must not be queried directly by runtime code.

## Runtime/evaluation separation

Runtime must never expose or use:

- `health_archetype`
- `health_band`
- Generated `usage_cliff_date` when it represents latent truth rather than a computed event
- `advanced_adoption_target`
- `health_index`
- Packaged `churn_probability`
- `outcome`
- `outcome_reason`
- Ground-truth driver contributions

Evaluation-only repositories may use these fields after predictions are frozen. Runtime packages must not be able to import the evaluation repository accidentally.

## Loader requirements

Create one central data-loader package that:

- Loads `accounts.csv` with `keep_default_na=False` so region `NA` remains North America. The dataset contains 116 such rows.
- Parses each documented date explicitly.
- Validates primary keys, foreign keys, fact-grain uniqueness, categories, and numeric ranges.
- Rejects unknown accounts and malformed dates.
- Applies effective cutoffs before returning runtime records.
- Returns immutable frames or repository objects.
- Records file hashes, dataset version, seed, and as-of date.

Do not scatter raw `pandas.read_csv()` calls through application code.

## Feature restrictions

- Recompute runtime features from permitted point-in-time rows.
- Do not trust packaged `account_features.csv` without reproducing and validating each formula.
- Keep `days_to_renewal` for display but exclude it from prediction because it is always 90 in this package.
- Recompute advanced-feature depth from `usage_weekly.advanced_feature_adoption_pct`.
- Recompute escalation rate using observed active weeks within the 26-week window.
- Use explicit ticket and note sentiment names; do not silently merge their meanings.
- Every metric must include window, cutoff, source row count, coverage, and calculation version.

## Retrieval restrictions

- Build a sanitized index; do not use `rag_corpus/corpus_with_kb.jsonl` directly at runtime.
- Exclude target, latent, and post-cutoff content.
- Add external events as sanitized documents or retrieve them through a deterministic exact tool.
- Enforce `account_id` and cutoff before accepting account evidence.
- Search account documents and the general knowledge base as separate lanes.
- Post-validate every citation's account, date, source, parent, and authorization.
- Wrong-account and post-cutoff citation rates must be zero.

## Source immutability

The application may write only generated artifacts and internal application state, including:

- Sanitized processed data
- Deterministic splits and manifests
- Model artifacts and model cards
- FAISS indexes and metadata stores
- Assessment snapshots
- Review cases and reviewer feedback
- Structured traces
- Evaluation results

It may never update the packaged Meridian source files.

## Validation exit gate

Data ingestion is not complete until tests prove:

- No orphaned foreign keys
- No duplicate primary or fact-grain keys
- No runtime records after effective cutoff
- No forbidden fields in sanitized profiles or indexes
- Reproducible row counts and non-image artifacts
- Correct handling of permitted missing values
- Exactly 116 `NA` region rows survive parsing
- `days_to_renewal` zero variance is documented and excluded from modeling
- The two post-dataset-as-of external events are excluded
- Runtime code cannot import outcome labels or ground-truth drivers

## Logging and public-demo safety

- Never log secrets or hidden reasoning.
- Preserve only evidence excerpts needed for audit.
- Keep synthetic-data and decision-support disclaimers visible.
- Restrict public requests to synthetic accounts and the account-health domain.
- Cache demonstration runs when live model access is unavailable; label cached output honestly.
