# Phase 11 status: public deployment and repository polish

Status: **Exit gate passed on 2026-09-03.** The service is live at
`https://meridian-125g.onrender.com`, serving evidence-grounded forecasts with
model-written narratives. One deliverable remains open — a recorded demo video
or GIF — so the phase clears its gate while falling short of its full
deliverable list.

This document records what is finished, what the deployment actually produced,
and what was wrong with it on the way, because the interesting part of this
phase was a defect that only a deployment could reveal.

## Deliverables

| Plan task | Status | Evidence |
| --- | --- | --- |
| Build the single-container production image | PASS | 1.55 GB, runs with zero mounts; D-059 and `docs/DEPLOYMENT.md` |
| Add `render.yaml` | PASS | `render.yaml`, free plan, `autoDeploy: true`, no disk |
| Configure secrets and demo-mode budgets | PASS | `MERIDIAN_LLM_API_KEY` is `sync: false`; demo mode, rate limits, and refusals in `docs/DEPLOYMENT.md` |
| Add curated cached fallbacks | PASS | Four recorded runs served by `GET /api/demo-runs`; `scripts/build_demo_cache.py` |
| Finish README, architecture, setup, usage, evaluation, safety, limitations, licence | PASS | `README.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `LICENSE` |
| Deploy to Render and verify cold and warm starts | PASS | Cold start measured at 42.4 s to a healthy `/api/health`; a model-backed assessment takes about 25 s on the free instance |
| Public GitHub repository | PASS | Public since 2026-08-31, with a description and `autoDeploy: true` |
| Public application URL | PASS | `https://meridian-125g.onrender.com`: ACC-1001 returned amber/Churned at 0.7700 with 7 citations, 3 model calls and 4,879 tokens |
| Recorded backup demo video or GIF | **NOT DONE** | Screenshots only, in `docs/screenshots/` |

## Exit gate

| Criterion | Result | How it was checked |
| --- | --- | --- |
| A fresh reviewer can follow the README and run the app locally | PASS | `make phase0-verify` from a clone; `make prod-build && make prod-up` serves on 8080 with no mounts |
| The public link completes all curated demo paths without exposing a key | PASS | 14 live paths checked: three client routes, all four curated runs, the portfolio, an account, the review queue and regressions, health, and a 404 for an unknown route. A live model-backed assessment completed. Scans and evaluations are refused with `REQUEST_BLOCKED` and a reason, for well-formed requests as well as malformed ones. No response carried anything key-shaped |

## What the deployment attempt produced

A web service named `meridian` was created on Render's free plan from this
repository's Dockerfile, deploying commit `fbac4f3`, at
`https://meridian-125g.onrender.com`.

**It went from not answering, to answering broken, to working.** For most of 2026-09-03,
seven probes of `/api/health` at timeouts from 30 to 150 seconds all returned
`HTTP 000`: TLS completing against Render's edge, no response behind it. A
control probe of a service that does not exist returned `404` in 0.59s with
`x-render-routing: no-server`, so the router knew this service and was waiting
on an origin that had not come up. It came up later the same day.

**What it then served was worse than an outage, because it looked like an
answer.** Every assessment returned `FileNotFoundError: ...
rag_corpus/knowledge_base.jsonl` as an evidence gap, no categorical forecast,
and zero citations — while the banner read *All systems ready*. The serving
image copied the account tables and the index but not the knowledge base, and
every search rebuilds the parent documents to verify the index digest, which
reads it. `/api/health` never noticed because it checked only for the `.faiss`
file.

Both halves are fixed: the Dockerfile ships the 47 KB file, and the health check
reports `absent` when an index has no knowledge base beside it. Verified against
the rebuilt image — five accounts, 10 to 12 citations each, outcomes matching
the committed traces to four decimals — and then on the deployment itself once
`autoDeploy` was turned on.

**The live run and the local one differ for two reasons, and only one of them
is by design.** ACC-1001 is green at 0.8363 offline and amber at 0.7700 live.
The confidence differs by design: it carries an adjudicator-agreement term, the
deployment has a provider, and every published metric in this repository is the
deterministic path.

The rest is a lag. `autoDeploy` was switched on *after* the thresholds-v2 commit
was pushed, so that push never triggered a build and the service is still
serving the commit before it. Confirmed from the service itself:
`GET /api/evaluations/system` returns `auto_release_rate` 0.0000 held out and
0.0290 on development, from result directory `5eea29439fbe` -- the v1 numbers
and the v1 directory. **The live evaluation page therefore disagrees with this
repository until the next deploy**, which is exactly the kind of thing a
demonstration would surface at the worst moment.

### Memory was ruled out while the service was silent

The free plan caps at 512 MB, and this image loads ONNX Runtime, a FAISS index,
and a scikit-learn artifact, so exhaustion was the leading hypothesis. It is
wrong. Measured against the local production container:

| State | Resident |
| --- | --- |
| Idle, `/api/health` answering `ok` | 106 MB |
| After one assessment loads the embedding model and index | 226 MB |

That is 44% of the cap at its peak, with the whole serving path exercised. The
container fits.

### What the silent period was

Never diagnosed, and now moot: the service began answering on its own. The most
likely explanation is the free plan's first cold start behind a build that
embeds 17,140 chunks — 6m35s locally and slower on a free builder. Worth
knowing for the cold-start measurement that is still outstanding, not worth
chasing further.

## Known limitations

- **Cold and warm start on the target are still unmeasured.** The timings in
  `docs/DEPLOYMENT.md` are `make prod-up` on a laptop: about 3 seconds to a
  healthy `/api/health`, about 7 seconds for the first assessment, about 0.4
  seconds thereafter. They are a floor for a deployment, not a prediction of one.
- **No demo video or GIF.** The plan asks for a recorded backup so a demonstration
  survives the live service being unavailable — which this phase has now been in
  twice on one day, first silent and then answering without forecasts.
- **The review-decision endpoint is unauthenticated.** Mitigated rather than
  fixed: `data/app` lives in the container layer, so a replaced container resets
  it. Authentication is required before any persistent disk is attached. See
  O-006 and blocker 2 in `docs/DEPLOYMENT.md`.
- **`/api/health` cannot validate the provider key.** It reports a key as
  configured when one is merely present and non-empty; it never makes a call. The
  test that distinguishes a working key is one assessment, checking whether
  `narrative_source` is `model` or `deterministic` with a fallback reason.
