# Phase 8 status: API and the autonomous portfolio workflow

Status: **Complete; exit gate passed on 2026-09-01**

Phases 5 to 7 built a graph that assesses one account and routes what it is
unsure of to a person. Phase 8 makes that reachable: a served API for the whole
section 19.1 table, a streaming surface for one run, and the bounded portfolio
scan that is the reason the plan calls this system autonomous.

Section 18 is careful about what that word means, and so is the code. The system
chooses which accounts to assess and runs the whole graph on each without a
person picking tools or routes. It takes **no action** on any customer, and
nothing it is unsure of reaches a user unreviewed.

## Deliverables

| Plan task | Status | Evidence |
| --- | --- | --- |
| Complete FastAPI routes and OpenAPI schema | PASS | All 14 endpoints of section 19.1; `test_openapi_is_section_19s_endpoint_table` asserts the set exactly |
| SSE events | PASS | `GET /api/assessments/{run_id}/events`; the vocabulary is section 19.2's |
| Portfolio scan with bounded concurrency | PASS | `meridian.serving.scan`; peak concurrency measured by the work itself |
| Optional scheduler | PASS | `meridian.serving.scheduler`; off unless `enable_scheduler` **and** not `demo_mode` |
| CLI | PASS | `scripts/scan_portfolio.py`, `make scan` |
| Rate limiting and demo mode | PASS | `meridian.serving.limits`; per-client and service-wide windows, curated question |
| Full API integration suite | PASS | `backend/tests/test_api_service.py`, 24 tests through the real graph |
| Portfolio scan summary | PASS | `artifacts/portfolio/portfolio_scan.json` and its per-account CSV |

## Exit gate

| Criterion | Result | Evidence |
| --- | --- | --- |
| A scan completes without exceeding configured concurrency | PASS | `concurrency_observed` is a peak counted by the runs themselves; asserted at 3, 2, and exactly 1 |
| A scan completes without exceeding its model-call budget | PASS | A zero budget scans nothing at all; an offline scan spends 0 of 200 |

The bound is measured, not reported. A scan that returned the value it was
configured with would pass this gate whatever it actually did, so
`_ConcurrencyMeter` is incremented by the work inside the pool and its peak is
what the summary publishes. `scripts/scan_portfolio.py` exits non-zero if either
bound is breached, so the gate is enforced by the command rather than by
someone reading the output.

**The budget is checked before dispatch and never mid-run.** A run that has
already begun is allowed to finish: abandoning it halfway would leave a
half-written assessment and no review case, which is a worse failure than
overspending by one run. Each account reserves the per-run ceiling
(`MAX_MODEL_CALLS`) before starting and returns what it did not use, so the
pool's width cannot let several workers pass the same check at once.

## What the scan actually found

`make scan LIMIT=6 CONCURRENCY=3`, offline:

| Measure | Value |
| --- | ---: |
| Scanned | 6 |
| Completed | 6 |
| Auto-released (green) | **0** |
| Queued for review | 6 (3 amber, 3 red) |
| Abstentions | 1 |
| Model calls | 0 of 200 |
| Peak concurrency | 3 of 3 |

**Nothing was auto-released.** That is the Phase 7 threshold finding showing up
as an operational number rather than an evaluation one: the routing bands are
conservative enough that a portfolio scan currently produces a review queue and
nothing else. A scan whose entire output is review load does not save a CS team
any work, which is the thing this feature exists to do.

It is not a defect in the scan -- the routing is doing exactly what section 16.5
specifies -- and it is not fixed here, because section 22.7 forbids tuning
thresholds outside a development-split measurement. Phase 10 freezes them, and
this is the second measurement saying that choice matters.

## Verification

The full suite passes with **543 tests passed, 1 intentionally skipped, and
94.82% coverage** on the host. 66 of those tests are new in this phase.

`make phase0-verify` rebuilt both locked images and passed: formatting on 130
files, ruff, strict mypy over 129 source files, **538 backend container tests
with 6 expected skips at 94.84% coverage**, 7 frontend tests, the production
frontend build, the repository policy scan over 259 files, and both application
health checks becoming healthy.

## Decisions worth recording

### Evaluations are not run over HTTP

Section 19.1 lists `POST /api/evaluations`, and the obvious implementation --
start the harness in-process -- is the one thing this service must not do. Every
harness lives in `meridian_eval`, which reads outcome labels, and section 8.4
makes that boundary structural: `test_import_boundary.py` fails the build if any
served module imports it.

A lazy import inside the handler would not change that. It would only hide it
from a reader, and it would still put label-reading code one unauthenticated
call away. So `POST` refuses and names the command to run, and `GET` serves the
artifact the last command-line run recorded. This was found by the boundary test
after the first implementation did exactly the wrong thing.

### The rate limiter is a dependency, not a module global

The first version read the limiter from the process cache inside
`enforce_rate_limit`. That works, and it cannot be substituted -- which meant
the test asserting that a client over its limit is refused passed while the
limit was never enforced. A safety control that cannot be overridden in a test
is a control nobody has checked. It now arrives through `Depends`.

### Eligibility is measured against each account's own forecast date

Not against wall-clock today. The synthetic dataset never moves, so a
"today"-based horizon would select a different portfolio every day from
identical data and make two scans incomparable. Sorting by renewal date then id
means two scans of one portfolio queue the same work in the same order.

### The scheduler refuses rather than degrades

Section 18.2 allows a scheduled worker; section 24.3 says to disable unattended
scheduled spending in the public deployment by default. Both conditions are
required -- `enable_scheduler` on **and** `demo_mode` off -- and the worker
raises rather than starting in a reduced form. A scheduler that silently
downgrades itself is worse than one that will not start, because the operator
believes scans are happening.

The permission is re-checked on every tick, not only at start, so a
configuration reload cannot leave a running scheduler spending in a mode that
forbids it.

## Known limitations

- **Run state is in memory and per process.** Live runs, scans, and rate-limit
  windows do not survive a restart and are not shared between replicas. That is
  correct for the single free-tier container ADR 0005 targets, and it is stated
  rather than hidden: a horizontally scaled deployment needs a shared counter
  and a real job store. Finished assessments and review cases are already
  durable in application memory, so nothing that matters is lost on a restart.
- **`client_key` is the peer address**, which behind a proxy is the proxy.
  `X-Forwarded-For` is deliberately not trusted: an unauthenticated caller can
  set it to anything and would then have an unlimited allowance. On a
  single-container deployment behind one proxy this makes the per-client limit
  effectively a second global limit.
- **The SSE endpoint holds a worker for the life of the stream.** With the
  default pool that bounds concurrent watchers. Section 19.2's event set is
  small and runs are seconds long, so this has not been a constraint locally.
- **No authentication.** Section 24.3 treats the public demo as anonymous and
  bounds it with rate limits, demo mode, and per-run budgets instead. Every
  write the API has is a reviewer decision on an existing case; there is no
  endpoint that mutates Meridian source data.
- **The scan has not been run with a provider.** The structure is what these
  bounds govern, and the offline arm exercises all of it at zero cost. A
  provider-backed scan of 50 accounts would cost real money and has not been
  billed; `--use-provider` exists and is not assumed.
