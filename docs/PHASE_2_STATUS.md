# Phase 2 status: deterministic analytics and calibrated model

Status: **Complete; exit gate passed on 2026-08-31**

No language model is involved anywhere in this phase. Train with `make train`,
forecast one account with `make predict ACCOUNT=ACC-1042`.

## Deliverables

| Item | Status | Evidence |
| --- | --- | --- |
| Feature computation at arbitrary cutoff | PASS | `meridian.features.builder`, 21 features across 5 families |
| Coverage reporting | PASS | `FeatureCoverage` on every forecast |
| Baselines and candidate models | PASS | 5 candidates including majority and a documented rule baseline |
| Calibrated selected model | PASS | Logistic regression with isotonic calibration |
| Versioned artifact and model card | PASS | `models/forecaster.joblib`, `docs/MODEL_CARD.md` |
| Deterministic prediction CLI | PASS | `scripts/predict_account.py`, no LLM |

## Exit gate

| Criterion | Result | Evidence |
| --- | --- | --- |
| Metrics reproduce exactly from the same data and cutoff | PASS | `test_prediction_is_deterministic`, `test_feature_computation_is_deterministic` |
| Model beats the documented baseline on development validation | PASS | Macro F1 0.7423 against 0.7302 rule baseline and 0.1731 majority |
| No forbidden feature enters training or inference | PASS | `test_forecast_exposes_no_forbidden_field`, allowlist repository, import boundary |

66 tests passing at 96% coverage, ruff and mypy strict clean across 39 files.

## Validation results (51 accounts)

| metric | calibrated | uncalibrated |
| --- | ---: | ---: |
| macro F1 | 0.7423 | 0.7244 |
| accuracy | 0.8431 | 0.7451 |
| log loss | 0.5389 | 0.6165 |
| Brier | 0.0777 | 0.1015 |
| expected calibration error | 0.1481 | 0.1346 |

Confidence bands behave monotonically, which is what makes confidence-based
human-review routing defensible in Phase 7:

| band | accounts | error rate |
| --- | ---: | ---: |
| high (>= 0.75) | 19 | 5.3% |
| medium (0.50-0.75) | 30 | 20.0% |
| low (< 0.50) | 2 | 50.0% |

## Two decisions that departed from the plan

### Model selection is not pure macro F1

The rule baseline scores highest on cross-validated macro F1 (0.759) but its log
loss is 2.30: the probabilities are badly miscalibrated. Plan section 16 routes
human review on confidence, so an uncalibrated model cannot be served whatever
its F1. Selection therefore applies a one-standard-error rule — among candidates
statistically indistinguishable on macro F1, take the lowest log loss. That
picks logistic regression, which then beats the rule baseline on validation
macro F1 anyway (0.7423 against 0.7302) with a quarter of the log loss.

### Calibration is isotonic, not sigmoid

Plan section 10.4 prefers sigmoid "unless validation demonstrates enough data
for isotonic". Validation demonstrated the reverse. Sigmoid was the worst option
in every configuration tested, collapsing macro F1 from 0.72 to about 0.51: at
156 training accounts, a 5-fold sigmoid calibrator sees roughly three
`Contracted` examples per fold and flattens the minority classes. Isotonic at 3
folds improves macro F1, accuracy, log loss, and Brier over no calibration at
all. The full grid is in `artifacts/model/calibration_study.csv`.

## Feature findings

Recomputing features from observable telemetry rather than reading
`account_features.csv` matters, and the numbers show why. Against the packaged
columns, the six features that should agree match exactly (r = 1.000), while the
four the plan requires be recomputed diverge as expected:

| feature | correlation with packaged | why it differs |
| --- | ---: | --- |
| `advanced_feature_depth` | 0.962 | Archive derives it from the latent `advanced_adoption_target`; this recomputes from telemetry |
| `support_escalation_rate` | 0.920 | Archive divides by the whole observed history, not the 26-week window |
| `adoption_trend_13w` | 0.979 | Observable seat-ratio proxy rather than the generator's internal series |
| `adoption_level_last_q` | 0.991 | Same |

Permutation importance ranks `adoption_level_last_q`, `avg_note_sentiment_26w`,
and `advanced_feature_depth` highest, consistent with the documented health
methodology in KB-012.

## Known limitations

- The validation split holds 51 accounts. Differences under roughly five points
  are not meaningful, and the confidence-band error rates rest on 2, 30, and 19
  accounts respectively.
- Expected calibration error is 0.148. Calibration improves discrimination and
  log loss but does not make the model well calibrated in absolute terms.
- The 53-account test split has not been read. It is reserved for the final
  evaluation in Phase 10.
