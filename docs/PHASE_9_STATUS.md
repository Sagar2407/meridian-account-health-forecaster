# Phase 9 status: the React application

Status: **Complete; exit gate passed on 2026-09-01**

Everything the system does was reachable only through JSON until now. Phase 9
gives it a face: five pages, a streamed progress view, a clickable evidence
drawer, and a review queue where a person can actually override a released
answer and see the regression record it files.

## Deliverables

| Plan task | Status | Evidence |
| --- | --- | --- |
| Portfolio page (20.1) | PASS | Summary cards, sortable table, segment/region/renewal filters, assess and scan actions, synthetic banner |
| Account page (20.2) | PASS | Sanitized profile, 104-week trajectory with cutoff marker, nine indicators, recent activity, prior assessments, question box with presets |
| Live assessment page (20.3) | PASS | SSE timeline, parallel lane markers, retry notice, conflict and Tree-of-Thought badges |
| Forecast decision card (20.4) | PASS | Outcome or abstention, confidence gauge, four-class distribution, route, drivers, evidence, counterevidence, drawer, limitations, next action |
| Review queue (20.5) | PASS | Red-first ordering, full card, four actions, override blocked without a reason code and note |
| Evaluation page (20.6) | PASS | Published artifacts per dimension; an unrun harness says so and names its command |
| Responsive and accessibility checks | PASS | Skip link, one `h1` and one `main` per page, named figures, no horizontal scroll at 1280 and 834 px |
| E2E browser tests | PASS | 24 Playwright tests across desktop and tablet, `make e2e` |
| Screenshots | PASS | `docs/screenshots/`, captured by `make screenshots` from the running build |

## Exit gate

| Criterion | Result | Evidence |
| --- | --- | --- |
| All core user journeys pass Playwright tests | PASS | **24 passed, 0 skipped** across chromium and tablet |
| No hidden reasoning or forbidden field is visible in browser responses | PASS | A journey subscribes to every `/api/` response and fails on any of 11 latent fields or 7 prompt keys |

The leakage test is a response listener, not a page assertion. It walks the
portfolio, an assessment, the review queue, a decision card, and the evaluation
page, reads the body of every API response the browser actually received, and
fails on the first occurrence. A test that only checked rendered text would
pass while the field sat in the JSON one `JSON.stringify` away.

`make phase0-verify` covers the unit side and passed on the locked images:
formatting over 130 files, ruff, strict mypy over 129 source files, **541
backend container tests with 6 expected skips at 94.79% coverage**, **85
frontend tests** at 90% statements, 83% branches, 88% functions, and 92% lines
against an 80% floor, the production frontend build, the repository policy scan
over 280 files, and both application health checks.

## What the E2E found that the unit tests could not

Three defects, all from tests that were skipping rather than failing.

### An abstention silently dropped its evidence

The citation-drawer journey kept skipping with "this account produced no
citation to inspect". The account had **seven** citations. `DecisionCard`
rendered them for a `ForecastDecision` and not for an
`InsufficientEvidenceDecision` — so on precisely the runs where a reviewer most
needs to see what the system read before it declined to label, the card showed
none of it. The abstention branch now renders the same list through the same
drawer, and three unit tests hold it there.

### Two journeys were skipping themselves into a green gate

`test.skip(true, ...)` inside a journey turns "the thing I was testing was not
there" into a pass. The review-override journey skipped whenever the queue
happened to be empty, which meant the exit gate could go green without ever
exercising an override. It now reads the review case id from the finished run
page and acts on *that* case. It still skips in one honest circumstance — the
run was auto-released, so there is no case — and that is a condition about the
system, not about the test's luck.

### The DOM was never cleaned between unit tests

`@testing-library/react` registers its automatic cleanup only when the runner
exposes `afterEach` as a global, and this project runs Vitest without
`globals: true`. Every render in a file accumulated in one document. The first
test in each file passed and the rest would have failed with "found multiple
elements" — or worse, passed against the previous test's markup. `tests/setup.ts`
now calls `cleanup` explicitly.

## Decisions worth recording

### The charts are hand-drawn SVG

Every figure here is a line, a bar, or an arc. A charting library would add more
to the bundle than the whole application currently weighs, on a deployment
target where image size affects cold start (ADR 0005). Hand-drawn markup also
made the accessible names straightforward: the usage chart's name states its
range, its peak, and the cutoff it stops at, which is the sentence a screen
reader user needs and the one a tooltip cannot give them.

### The cutoff marker is the point of the usage chart

The API filters the series to the account's effective cutoff, so the boundary is
already true. Drawing it makes it *visible* rather than something a reader has
to take on trust, and the figure's accessible name says it too.

### The account page is one request

`GET /api/accounts/{id}` grew to carry the trajectory, the indicators, and the
recent activity alongside the profile. Five requests would have let a page
render a chart from one point in time beside indicators from another; one
request at one cutoff cannot. It also kept the served surface exactly equal to
the plan's endpoint table, which a test asserts.

### Evaluations are read, never run, from the browser

The page shows what the command-line harnesses wrote. That follows Phase 8's
boundary decision rather than restating it: every harness reads outcome labels,
and no served module may import them.

## Known limitations

- **No confusion matrix or calibration curve yet.** Section 20.6 lists both.
  The evaluation page renders whatever metrics an artifact contains, and the
  guardrail and ablation artifacts are scalar; the modelling artifacts that
  hold per-class matrices are written by Phase 10's full evaluation run. The
  page names each unrun dimension and its command rather than drawing an empty
  chart, which would imply a measurement nobody made.

  **Resolved in Phase 12.** Phase 10's evaluation ran, and Phase 12 published
  its results as `artifacts/evaluation/summary.json`. The page now renders the
  release targets, the per-class table, the confusion matrix, and the error
  rate inside each review band, for either split.
- **The review queue orders by route then age, not by ACV or renewal
  proximity.** Section 20.5 asks for all four. The queue's rows carry the case,
  not the account's commercial terms, so the other two would need either a join
  in the API or a request per row. It is a small API change and is deliberately
  not smuggled in here.

  **Resolved.** `GET /api/review-cases` now joins each case to its account
  profile and orders by all four keys, and the rows carry `acv_usd`,
  `renewal_date`, and `days_to_renewal` so a reviewer can see why a case sits
  where it does. Two things were wrong beyond the missing keys. The ordering ran
  in the browser, so it only ever reordered the `limit` rows the server had
  already chosen by recency -- the oldest untouched red case on the largest
  account could not appear at all; `limit` is now applied after ordering. And
  the client sort would have silently discarded the two new keys, so it is gone
  and the page renders the order it is given.
- **The E2E suite shares one database with the developer's own runs.** The
  compose override bind-mounts `data/` read-write, because the review journey
  has to record an assessment and open a case. A run therefore adds rows to
  `data/app/assessments.sqlite`. That is application memory, git-ignored, and
  the same file `make assess` writes to.
- **No visual-regression testing.** The screenshots are a deliverable, not a
  gate; nothing fails if the layout shifts.

  **Resolved.** `frontend/e2e/layout.spec.ts` compares rendered pixels against
  committed baselines on both viewports, so an accidental change to a shared
  token, grid, or spacing scale fails the suite. It covers only pages whose
  content is fixed -- the portfolio, a curated demo run, and the not-found page
  -- because the review queue grows with every assessment and the evaluation
  page renders whatever the last evaluation wrote, and a baseline that fails on
  correct changes gets ignored. The captures are the viewport rather than the
  full page: a full-page capture of a 260-row table was a megabyte of PNG that
  moves with the data, which buys length rather than coverage. Accept an
  intended change with `./scripts/run_e2e.sh --update-snapshots`, which now
  forwards its arguments to Playwright.
- **Accessibility is checked structurally, not audited.** Skip link, landmarks,
  heading counts, accessible names, and horizontal overflow are asserted. That
  is not the same as an axe or WCAG audit, and no such audit has been run.

  **Resolved.** `frontend/e2e/accessibility.spec.ts` runs axe-core against every
  route at WCAG 2.0/2.1 A and AA, on both viewports, and fails on any violation.
  It found one rule broken on every page, which is exactly the class of defect
  the hand-written checks could not see: nothing about the markup was wrong.
  `--ink-faint`, the colour of every timestamp, latency, eyebrow, and citation
  source, was 4.09:1 on white and 3.82:1 on the sunken surface against a 4.5:1
  requirement, and the green status pill was 4.43:1 against its own background.
  Both were darkened until they clear AA on every surface they are used on. The
  suite is now 36 tests: 24 journeys and 12 audits.
