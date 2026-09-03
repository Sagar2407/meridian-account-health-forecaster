# Data lineage

How the Meridian dataset travels from the generated archive to the sanitized
tables the application is allowed to read, and what was found along the way.

All records are synthetic. See `docs/DATA_SAFETY.md` for the policy this
implements and plan section 8 for the requirements.

## Provenance

| Property | Value |
| --- | --- |
| Source archive | `meridian-account-health.zip`, dated 2026-07-21 |
| Extracted, unmodified, to | `data/raw/meridian-account-health/` (git-ignored) |
| Generator | `build_dataset.py` with `config.py`, `generators.py`, `text_banks.py` |
| Random seed | `20260721` (`config.RANDOM_SEED`) |
| Observation horizon | `2026-06-28` (`config.AS_OF_DATE`) |
| Accounts | 260 |

The raw archive is never written to. Every artifact this project produces is
written under `data/processed/` or `data/splits/`.

## Pipeline

```text
data/raw/meridian-account-health/data/*.csv
  -> meridian.data.loader        read + coerce + validate (schema, keys, categoricals)
  -> meridian.data.sanitize      drop latent columns, drop post-cutoff rows
  -> data/processed/*.parquet    sanitized runtime tables
  -> data/processed/dataset_manifest.json   version, per-file SHA-256, row counts, seed
  -> data/splits/account_split.json         deterministic 60/20/20, stratified by outcome
```

Rebuild everything with `make data`. Verify it with `make validate-data`.

## Where each section 8 rule is enforced

| Rule | Enforced in | Proven by |
| --- | --- | --- |
| 8.1 `keep_default_na=False` keeps region `NA` | `loader._read_table` | `test_region_na_is_north_america_not_null` |
| 8.1 Explicit date parsing, no silent `NaT` | `loader._read_table` | `test_malformed_date_is_rejected` |
| 8.1 Primary and foreign key validation | `loader`, `schemas` | `test_no_orphaned_foreign_keys`, `test_no_duplicate_primary_or_grain_keys` |
| 8.1 Allowed categorical values | `schemas` | schema validation on every load |
| 8.1 Version, hashes, seed, as-of date recorded | `manifest` | `test_manifest_records_every_source_table` |
| 8.2 `min(forecast_as_of_date, AS_OF_DATE)` | `cutoff`, `repository`, `sanitize` | `test_no_runtime_record_postdates_its_account_cutoff` |
| 8.4 Sanitized runtime profile | `constants.RUNTIME_PROFILE_FIELDS` (allowlist) | `test_profile_exposes_no_forbidden_field` |
| 8.4 Evaluation labels unreachable from runtime | `meridian_eval` as a separate package | `test_no_runtime_module_imports_the_evaluation_package` |
| 8.5 Deterministic stratified split | `meridian_eval.splits` | `test_split_is_reproducible` |
| 8.6 Reproducibility of generated artifacts | `numpy` version ceiling | `test_generator_is_deterministic`, `test_every_table_reproduces_the_shipped_archive` |

The runtime profile is an **allowlist**, not a denylist, so a column added to the
archive later is excluded by default rather than leaked by omission.

## What the cutoff actually removes

Filtering to each account's effective cutoff drops **17,927 rows**, about 20% of
the fact data. This is not a formality:

| Table | Raw rows | Runtime rows | Removed |
| --- | ---: | ---: | ---: |
| `usage_weekly` | 67,223 | 52,292 | 14,931 |
| `support_tickets` | 6,408 | 4,902 | 1,506 |
| `csm_notes` | 6,420 | 5,044 | 1,376 |
| `external_events` | 595 | 481 | 114 |

## Findings in the generated archive

Four issues were found while building this pipeline. Each is handled
deliberately rather than worked around.

### 1. Byte-exact reproduction requires `numpy < 2.5` (new finding)

The archive **is** fully reproducible. Re-running the generator at seed
`20260721` reproduces all seven CSVs byte for byte, and repeated runs are
identical to each other.

That holds only under **numpy 2.4.x**. Under numpy 2.5.2, with Python, pandas
and the seed held constant, the generator alters exactly one record:

- `NOTE-204709` (account `ACC-1191`, 2025-03-19, Monthly Touchpoint)
- Only the `body` text differs, 197 characters versus 173
- Every other column of that row, and all 6,419 other rows, are unaffected
- `notes.jsonl` and `corpus.jsonl` inherit the change because they embed it

So `numpy>=2,<2.5` in `pyproject.toml` is **load-bearing for reproducibility**,
not a stylistic pin. (It is independently required for Python 3.11 support,
because numpy 2.5's type stubs need 3.12.)
`test_numpy_is_constrained_for_reproducibility` asserts the ceiling so it cannot
be widened silently, and `test_every_table_reproduces_the_shipped_archive`
verifies the byte-exact property itself.

This was found the hard way: an initial resolution picked up numpy 2.5.2, the
single-note difference appeared, and it was misread as a flaw in the archive's
provenance before the dependency was isolated as the cause.

### 2. `adoption_level_last_q` exceeds its documented range (new finding)

The data dictionary documents this feature as 0–100. The archive reaches
**109.04**. The observed scale is treated as authoritative and the schema bound
is a corruption guard, not the documented range. Any model or narrative that
describes this feature as a percentage would be wrong.

### 3. `days_to_renewal` has zero variance (plan section 8.3)

Confirmed: every account has exactly `90`, because `forecast_as_of_date` is
defined as `renewal_date - 90 days`. It is kept for display and must be excluded
from predictive features in Phase 2.

### 4. External events run past the horizon (plan section 8.3)

The archive contains events through **2026-07-02**, after the `2026-06-28`
horizon. 114 event rows are removed by cutoff filtering and must never reach a
rebuilt retrieval index.

## Permitted missing values

These four are legitimately absent and are preserved as nulls, not imputed at
load time:

| Field | Missing | Meaning |
| --- | ---: | --- |
| `support_tickets.csat` | 575 | Ticket not resolved |
| `support_tickets.resolution_hours` | 575 | Ticket not resolved |
| `renewal_outcomes.outcome_reason` | 135 | Outcome is `Renewed` |
| `accounts.usage_cliff_date` | 231 | Account is not a `sharp_drop` archetype |

CSAT and resolution time are missing on exactly the same rows, which is asserted
rather than assumed.

## The deterministic split

Stratified by outcome across 260 accounts at seed `20260721`:

| Outcome | Total | Train | Validation | Test |
| --- | ---: | ---: | ---: | ---: |
| Churned | 47 | 28 | 9 | 10 |
| Contracted | 26 | 16 | 5 | 5 |
| Expanded | 52 | 31 | 10 | 11 |
| Renewed | 135 | 81 | 27 | 27 |
| **All** | **260** | **156** | **51** | **53** |

`data/splits/account_split.json` is committed. It holds account ids only, never
labels, so a reviewer can reproduce any reported metric without the raw archive.
Generating it requires labels, which is why generation lives in `meridian_eval`
while runtime reads it back through `meridian.data.splits`.
