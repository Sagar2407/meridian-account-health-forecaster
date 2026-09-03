# Phase 11 status: public deployment and repository polish

Status: **Incomplete; exit gate not passed.** The service is deployed and
answering at `https://meridian-125g.onrender.com`, and the build it is serving
is broken: it cannot retrieve, so every assessment degrades to verified
telemetry with no forecast. The fix is committed and needs a redeploy. Until a
deployment answers *correctly*, the second exit criterion is not met.

This document records what is finished, what the deployment attempt actually
produced, and which causes have been ruled out, so the next attempt starts from
measurements rather than from guesses.

## Deliverables

| Plan task | Status | Evidence |
| --- | --- | --- |
| Build the single-container production image | PASS | 1.55 GB, runs with zero mounts; D-059 and `docs/DEPLOYMENT.md` |
| Add `render.yaml` | PASS | `render.yaml`, free plan, `autoDeploy: false`, no disk |
| Configure secrets and demo-mode budgets | PASS | `MERIDIAN_LLM_API_KEY` is `sync: false`; demo mode, rate limits, and refusals in `docs/DEPLOYMENT.md` |
| Add curated cached fallbacks | PASS | Four recorded runs served by `GET /api/demo-runs`; `scripts/build_demo_cache.py` |
| Finish README, architecture, setup, usage, evaluation, safety, limitations, licence | PASS | `README.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `LICENSE` |
| Deploy to Render and verify cold and warm starts | **FAIL** | The URL answers, but the deployed build cannot retrieve; cold and warm starts still unmeasured |
| Public GitHub repository | PASS | Public since 2026-08-31 |
| Public application URL | **PARTIAL** | `https://meridian-125g.onrender.com` answers, serving a build that returns no forecasts. Redeploy pending |
| Recorded backup demo video or GIF | **NOT DONE** | Screenshots only, in `docs/screenshots/` |

## Exit gate

| Criterion | Result | How it was checked |
| --- | --- | --- |
| A fresh reviewer can follow the README and run the app locally | PASS | `make phase0-verify` from a clone; `make prod-build && make prod-up` serves on 8080 with no mounts |
| The public link completes all curated demo paths without exposing a key | **FAIL** | The link is reachable and one real run was exercised on it: `RUN-e6fb1cbe125e` on ACC-1077 returned no forecast, naming a missing knowledge base as the gap. No key was exposed. Re-check after the redeploy |

## What the deployment attempt produced

A web service named `meridian` was created on Render's free plan from this
repository's Dockerfile, deploying commit `fbac4f3`, at
`https://meridian-125g.onrender.com`.

**It went from not answering to answering broken.** For most of 2026-09-03,
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
the committed traces to four decimals. **The deployment needs a redeploy to pick
this up.**

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
