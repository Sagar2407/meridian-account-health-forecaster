# Representative traces

Four runs, one per path through the assessment graph. They are captured by
`make traces` (`scripts/capture_traces.py`), which runs offline: no provider is
called, so re-capturing costs nothing and the narratives are the deterministic
ones. Accounts are found by scanning, not pinned, so a trace labelled *conflict*
is one the conflict gate actually fired on.

Captured at commit `d1f12cafc5a2`.

| Path | Account | Route | Outcome | Confidence | Nodes | Events |
| --- | --- | --- | --- | --- | --- | --- |
| fast_path | `ACC-1001` | green | Churned | 0.8363 | 11 | 15 |
| tot | `ACC-1002` | amber | Renewed | 0.9207 | 11 | 17 |
| degraded | `ACC-1000` | red | none | -- | 8 | 12 |
| human_review | `ACC-1000` | red | Churned | 0.6395 | 12 | 17 |

## fast_path

Aligned evidence, single adjudication. Account `ACC-1001`, `artifacts/traces/fast_path.json`.

```text
validate_request -> load_context -> plan_sub_goals -> quantitative_lane -> retrieval_lane -> merge_evidence -> conflict_gate -> fast_adjudication -> verify_output -> assign_route -> persist
```

| Field | Value |
| --- | --- |
| Route | green |
| Outcome | Churned |
| Confidence | 0.8363 |
| Model calls | 0 |
| Tokens | 0 |
| Guardrail stages | intake, execution, evidence, execution, output, routing |
| Citations | TCK-100011, NOTE-200031, NOTE-200030, NOTE-200036, NOTE-200029, NOTE-200041, NOTE-200027, TCK-100025, NOTE-200054, KB-001, KB-029 |

## tot

Conflicting evidence, bounded Tree-of-Thought. Account `ACC-1002`, `artifacts/traces/tot.json`.

```text
validate_request -> load_context -> plan_sub_goals -> quantitative_lane -> retrieval_lane -> merge_evidence -> conflict_gate -> tot_adjudication -> verify_output -> assign_route -> persist
```

| Field | Value |
| --- | --- |
| Route | amber |
| Outcome | Renewed |
| Confidence | 0.9207 |
| Model calls | 0 |
| Tokens | 0 |
| Guardrail stages | intake, execution, evidence, execution, output, routing |
| Citations | EVT-ACC-1002-2024-08-30-d03c83801aec, EVT-ACC-1002-2025-05-04-2f860af6fbe9, NOTE-200058, NOTE-200065, NOTE-200056, NOTE-200059, NOTE-200057, NOTE-200055, NOTE-200070, KB-001, KB-029 |

## degraded

Retrieval unavailable, verified telemetry only. Account `ACC-1000`, `artifacts/traces/degraded.json`.

```text
validate_request -> load_context -> plan_sub_goals -> retrieval_lane -> quantitative_lane -> merge_evidence -> degraded_result -> persist
```

| Field | Value |
| --- | --- |
| Route | red |
| Outcome | none (no categorical label) |
| Confidence | -- |
| Model calls | 0 |
| Tokens | 0 |
| Guardrail stages | intake, execution, evidence, output, routing |
| Gaps | retrieval unavailable: the retrieval index is unavailable (captured deliberately for the degraded-path trace); build it with `make index` |
| Verified metrics returned | 21 |
| Review case | `CASE-ACC-1000-0049-01` |

## human_review

Red route, paused for a reviewer, resumed by an override. Account `ACC-1000`, `artifacts/traces/human_review.json`.

```text
validate_request -> load_context -> plan_sub_goals -> quantitative_lane -> retrieval_lane -> merge_evidence -> conflict_gate -> fast_adjudication -> verify_output -> assign_route -> persist -> await_review
```

| Field | Value |
| --- | --- |
| Route | red |
| Outcome | Churned |
| Confidence | 0.6395 |
| Model calls | 0 |
| Tokens | 0 |
| Guardrail stages | intake, execution, evidence, execution, output, routing |
| Citations | NOTE-200008, NOTE-200006, NOTE-200023, NOTE-200007, NOTE-200005, NOTE-200002, TCK-100007, NOTE-200001, NOTE-200026, NOTE-200003, KB-001, KB-029 |
| Reviewer action | override (evidence_contradicts_outcome) |
| Corrected outcome | Churned |
| Review case | `CASE-ACC-1000-0050-01` |
