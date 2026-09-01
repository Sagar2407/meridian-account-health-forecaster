# Meridian evaluation report

Commit `6d148a7e504a` (working-tree state not determined), split **test**, provider **none (deterministic)**, generated 2026-09-01T23:48:22+00:00.

Thresholds `5e23d7f9d9fef896` (v1), dataset `absent`, model `logistic_regression` / `isotonic`.

Every number in this report is read from `results.json` in this same directory. Nothing here is typed by hand.

## Release targets (plan section 22.6)

These are targets, not claimed results.

| Measure | Target | Measured | Met |
| --- | --- | ---: | :---: |
| Macro F1 | at least 0.7 | 0.7490 | yes |
| Exact numeric agreement | at least 1.0 | 1.0000 | yes |
| Supported-claim rate | at least 0.95 | 1.0000 | yes |
| Wrong-account citations | at most 0.0 | 0 | yes |
| Post-cutoff citations | at most 0.0 | 0 | yes |
| Expected calibration error | at most 0.1 | 0.1712 | **no** |
| Exhausted-retrieval safe fallback | at least 1.0 | not measured | not measured |


**Not met:** Expected calibration error (0.1712).
**Not measured in this run:** Exhausted-retrieval safe fallback.

## 22.1 Forecast correctness

37 released, 16 abstained, 0 blocked.

| Measure | Value |
| --- | ---: |
| Macro F1 | 0.7490 |
| Accuracy | 0.8649 |
| Majority baseline (Renewed) | 0.4595 |
| Beats majority | yes |

| Class | Precision | Recall | F1 | Support |
| --- | ---: | ---: | ---: | ---: |
| Churned | 0.8571 | 0.6667 | 0.7500 | 9 |
| Contracted | 0.2000 | 0.5000 | 0.2857 | 2 |
| Renewed | 0.9412 | 0.9412 | 0.9412 | 17 |
| Expanded | 1.0000 | 0.8889 | 0.9412 | 9 |

Confusion matrix (rows are truth, columns are prediction):

| | Churned | Contracted | Expanded | Renewed |
| --- | ---: | ---: | ---: | ---: |
| **Churned** | 6 | 3 | 0 | 0 |
| **Contracted** | 1 | 1 | 0 | 0 |
| **Expanded** | 0 | 1 | 16 | 0 |
| **Renewed** | 0 | 0 | 1 | 8 |

## 22.2 Grounded explanation

| Measure | Value | Over |
| --- | ---: | ---: |
| Supported-claim rate | 1.0000 | 37 |
| Verified on first attempt | 1.0000 | 37 |
| Exact numeric agreement | 1.0000 | 37 |
| Citation precision | 1.0000 | 37 |
| Driver overlap with ground truth | 0.4279 | 37 |
| Counterevidence on conflicting cases | 0.4667 | 15 |
| Wrong-account citations | 0 | — |
| Post-cutoff citations | 0 | — |

Section 22.2 permits an LLM judge score only after validation against a double-reviewed human sample. No such sample exists, so no judge metric is reported. Every measure above is deterministic.

## 22.3 Calibration

| Measure | Value |
| --- | ---: |
| Expected calibration error | 0.1712 |
| Multiclass Brier | 0.0671 |
| Log loss | 0.4585 |
| Auto-release rate | 0.0000 |

Error rate inside each review band -- what a reviewer is implicitly promised:

| Band | Runs | Errors | Error rate | Auto-released |
| --- | ---: | ---: | ---: | :---: |
| green | 0 | 0 | not measured | yes |
| amber | 19 | 2 | 0.1053 | **no** |
| red | 18 | 4 | 0.2222 | **no** |

## 22.5 Operational reliability

| Measure | Value |
| --- | ---: |
| Completion rate | 1.0000 |
| Release rate | 0.6981 |
| Abstention rate | 0.3019 |
| Escalation rate | 0.6415 |
| Retrieval retry rate | 0.1132 |
| Output regeneration rate | 0.0000 |
| Node errors | 0 |
| Total tokens | 0 |
| Model calls | 0 |

| Path | Runs | p50 | p95 |
| --- | ---: | ---: | ---: |
| fast | 22 | 185.5000 ms | 331.4000 ms |
| tree_of_thought | 15 | 179.1000 ms | 202.0000 ms |
| abstained | 16 | 170.1000 ms | 210.5000 ms |
| blocked | 0 | not measured ms | not measured ms |
| **overall** | 53 | 179.8000 ms | 291.2000 ms |

## Threshold study (plan section 22.6)

Measured on the **test** split over 53 accounts. Section 22.7 forbids tuning on held-out outcomes, so this sweep never touches the test split.

At the frozen bands (green 0.85, amber 0.7, digest `5e23d7f9d9fef896`): **0 of 53 auto-released** (0.0000), 0 of them wrong.

The most permissive band measured (green 0.6, amber 0.5) would auto-release 18 (0.3396) with 3 wrong (0.1667 of what it released). The full sweep is in `threshold_study.csv`.

## Artifacts in this directory

| File | What it holds |
| --- | --- |
| `results.json` | Every number in this report |
| `runs.csv` | One row per assessed account |
| `threshold_study.csv` | The full band sweep |
| `confusion_matrix.png` | Section 22.1's confusion matrix |
| `reliability.png` | Section 22.3's reliability diagram |
| `REPORT.md` | This file |

