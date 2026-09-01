# Evaluation results

Each directory is one run of `make evaluate-system`, named `<commit>-<timestamp>`.
The directory name does not say which split it holds; the first line of its
`REPORT.md` does.

| Directory | Split | Accounts |
| --- | --- | ---: |
| `6d148a7e504a-20260901T234800+0000` | development | 207 |
| `6d148a7e504a-20260901T234822+0000` | test (held out) | 53 |

Both were produced offline at zero tokens against the frozen thresholds
(digest `5e23d7f9d9fef896`, v1), which were fixed before the held-out split was
first evaluated and have not changed since.

## These reproduce an earlier run

The same two splits were evaluated at commit `befdf982fc06` during Phase 10.
Comparing the two result sets value by value, **every release-target metric is
identical** — macro F1 0.8468 / 0.7490, ECE 0.1568 / 0.1712, supported-claim
1.0000, exact numeric agreement 1.0000, zero wrong-account and zero post-cutoff
citations.

Two groups of values did move, and neither is a headline result:

- **Latency percentiles.** Wall-clock timings on a shared machine; they are
  reported as diagnostics, not as targets.
- **The embedded safety-routing block.** Exact-disposition match went 0.5833 to
  0.6944 as four behavioural cases (GE-020, GE-023, GE-024, GE-026) began
  verifying and releasing instead of failing verification and routing red — a
  consequence of the Tree-of-Thought citation fix made after Phase 10 ran. The
  Phase 10 directories carried the superseded block, so they were replaced
  rather than kept beside these.

## Files in each directory

| File | What it holds |
| --- | --- |
| `REPORT.md` | The generated report; every number is read from `results.json` |
| `results.json` | Every metric the run computed |
| `runs.csv` | One row per assessed account |
| `threshold_study.csv` | The band sweep (development split only, per plan §22.7) |
| `confusion_matrix.png`, `reliability.png` | Plots for the report |
