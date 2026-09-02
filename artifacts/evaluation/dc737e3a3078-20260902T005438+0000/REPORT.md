# Meridian evaluation report

Commit `dc737e3a3078` (working-tree state not determined), split **development**, provider **none (deterministic)**, generated 2026-09-02T00:54:38+00:00.

Thresholds `5e23d7f9d9fef896` (v1), dataset `absent`, model `logistic_regression` / `isotonic`.

Every number in this report is read from `results.json` in this same directory. Nothing here is typed by hand.

## Release targets (plan section 22.6)

These are targets, not claimed results.

| Measure | Target | Measured | Met |
| --- | --- | ---: | :---: |
| Macro F1 | at least 0.7 | 0.8468 | yes |
| Exact numeric agreement | at least 1.0 | 1.0000 | yes |
| Supported-claim rate | at least 0.95 | 1.0000 | yes |
| Wrong-account citations | at most 0.0 | 0 | yes |
| Post-cutoff citations | at most 0.0 | 0 | yes |
| Expected calibration error | at most 0.1 | 0.1568 | **no** |
| Exhausted-retrieval safe fallback | at least 1.0 | 1.0000 | yes |


**Not met:** Expected calibration error (0.1568).

## 22.1 Forecast correctness

137 released, 70 abstained, 0 blocked.

| Measure | Value |
| --- | ---: |
| Macro F1 | 0.8468 |
| Accuracy | 0.9197 |
| Majority baseline (Renewed) | 0.4891 |
| Beats majority | yes |

| Class | Precision | Recall | F1 | Support |
| --- | ---: | ---: | ---: | ---: |
| Churned | 0.9189 | 0.9714 | 0.9444 | 35 |
| Contracted | 0.7000 | 0.5833 | 0.6364 | 12 |
| Renewed | 0.9429 | 0.9851 | 0.9635 | 67 |
| Expanded | 1.0000 | 0.8696 | 0.9302 | 23 |

Confusion matrix (rows are truth, columns are prediction):

| | Churned | Contracted | Expanded | Renewed |
| --- | ---: | ---: | ---: | ---: |
| **Churned** | 34 | 1 | 0 | 0 |
| **Contracted** | 3 | 7 | 2 | 0 |
| **Expanded** | 0 | 1 | 66 | 0 |
| **Renewed** | 0 | 1 | 2 | 20 |

## 22.2 Grounded explanation

| Measure | Value | Over |
| --- | ---: | ---: |
| Supported-claim rate | 1.0000 | 137 |
| Verified on first attempt | 1.0000 | 137 |
| Exact numeric agreement | 1.0000 | 137 |
| Citation precision | 1.0000 | 137 |
| Driver overlap with ground truth | 0.4526 | 137 |
| Counterevidence on conflicting cases | 0.6757 | 37 |
| Wrong-account citations | 0 | — |
| Post-cutoff citations | 0 | — |

Section 22.2 permits an LLM judge score only after validation against a double-reviewed human sample. No such sample exists, so no judge metric is reported. Every measure above is deterministic.

## 22.3 Calibration

| Measure | Value |
| --- | ---: |
| Expected calibration error | 0.1568 |
| Multiclass Brier | 0.0500 |
| Log loss | 0.3711 |
| Auto-release rate | 0.0290 |

Error rate inside each review band -- what a reviewer is implicitly promised:

| Band | Runs | Errors | Error rate | Auto-released |
| --- | ---: | ---: | ---: | :---: |
| green | 6 | 0 | 0.0000 | yes |
| amber | 68 | 2 | 0.0294 | **no** |
| red | 63 | 8 | 0.1270 | **no** |

## 22.5 Operational reliability

| Measure | Value |
| --- | ---: |
| Completion rate | 1.0000 |
| Release rate | 0.6618 |
| Abstention rate | 0.3382 |
| Escalation rate | 0.6425 |
| Retrieval retry rate | 0.0918 |
| Output regeneration rate | 0.0000 |
| Node errors | 0 |
| Total tokens | 0 |
| Model calls | 0 |

| Path | Runs | p50 | p95 |
| --- | ---: | ---: | ---: |
| fast | 100 | 162.0000 ms | 329.0000 ms |
| tree_of_thought | 37 | 164.9000 ms | 234.0000 ms |
| abstained | 70 | 169.5000 ms | 323.9000 ms |
| blocked | 0 | not measured ms | not measured ms |
| **overall** | 207 | 165.4000 ms | 312.5000 ms |

## Threshold study (plan section 22.6)

Measured on the **development** split over 207 accounts. Section 22.7 forbids tuning on held-out outcomes, so this sweep never touches the test split.

At the frozen bands (green 0.85, amber 0.7, digest `5e23d7f9d9fef896`): **6 of 207 auto-released** (0.0290), 0 of them wrong.

The most permissive band measured (green 0.6, amber 0.5) would auto-release 69 (0.3333) with 4 wrong (0.0580 of what it released). The full sweep is in `threshold_study.csv`.

## Artifacts in this directory

| File | What it holds |
| --- | --- |
| `results.json` | Every number in this report |
| `runs.csv` | One row per assessed account |
| `threshold_study.csv` | The full band sweep |
| `confusion_matrix.png` | Section 22.1's confusion matrix |
| `reliability.png` | Section 22.3's reliability diagram |
| `REPORT.md` | This file |

