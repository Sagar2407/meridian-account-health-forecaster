# Phase 11 status: public deployment and repository polish

Status: **Incomplete; exit gate not passed.** Five of the six tasks are done and
verified. The sixth — deploy and verify cold and warm starts — has been
attempted against Render and the service does not answer, so the plan's public
application URL deliverable stays open and the second exit criterion cannot be
evaluated.

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
| Deploy to Render and verify cold and warm starts | **FAIL** | Service does not answer; see below |
| Public GitHub repository | PASS | Public since 2026-08-31 |
| Public application URL | **BLOCKED** | No URL answers |
| Recorded backup demo video or GIF | **NOT DONE** | Screenshots only, in `docs/screenshots/` |

## Exit gate

| Criterion | Result | How it was checked |
| --- | --- | --- |
| A fresh reviewer can follow the README and run the app locally | PASS | `make phase0-verify` from a clone; `make prod-build && make prod-up` serves on 8080 with no mounts |
| The public link completes all curated demo paths without exposing a key | **BLOCKED** | There is no reachable public link to exercise |

## What the deployment attempt produced

A web service named `meridian` was created on Render's free plan from this
repository's Dockerfile, deploying commit `fbac4f3`, at
`https://meridian-125g.onrender.com`.

**It accepts connections and never answers.** Seven probes of `/api/health` on
2026-09-03, with per-request timeouts from 30 to 150 seconds, all returned
`HTTP 000`. The TLS handshake completes against Render's edge — valid
`*.onrender.com` certificate, HTTP/2 negotiated — and no response follows. That
is not the free plan's spin-down behaviour, which answers slowly rather than not
at all.

### Memory has been ruled out as the cause

The free plan caps at 512 MB, and this image loads ONNX Runtime, a FAISS index,
and a scikit-learn artifact, so exhaustion was the leading hypothesis. It is
wrong. Measured against the local production container:

| State | Resident |
| --- | --- |
| Idle, `/api/health` answering `ok` | 106 MB |
| After one assessment loads the embedding model and index | 226 MB |

That is 44% of the cap at its peak, with the whole serving path exercised. The
container fits.

### What has not been ruled out

- **A failed or timed-out build.** The image builds its own data, and the index
  step embeds 17,140 chunks — 6m35s locally and slower on a free builder. This
  is the leading remaining hypothesis and the Render build log settles it.
- **The container not binding `$PORT`.**
- **A deploy stuck mid-roll.**

Diagnosing these needs the Render dashboard's Events and Logs, which are outside
this repository.

## Known limitations

- **Cold and warm start on the target are still unmeasured.** The timings in
  `docs/DEPLOYMENT.md` are `make prod-up` on a laptop: about 3 seconds to a
  healthy `/api/health`, about 7 seconds for the first assessment, about 0.4
  seconds thereafter. They are a floor for a deployment, not a prediction of one.
- **No demo video or GIF.** The plan asks for a recorded backup so a demonstration
  survives the live service being down — which is exactly the situation this
  phase is in.
- **The review-decision endpoint is unauthenticated.** Mitigated rather than
  fixed: `data/app` lives in the container layer, so a replaced container resets
  it. Authentication is required before any persistent disk is attached. See
  O-006 and blocker 2 in `docs/DEPLOYMENT.md`.
- **`/api/health` cannot validate the provider key.** It reports a key as
  configured when one is merely present and non-empty; it never makes a call. The
  test that distinguishes a working key is one assessment, checking whether
  `narrative_source` is `model` or `deterministic` with a fallback reason.
