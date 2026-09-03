# Deployment runbook

Everything here has been verified against the production image on this machine.
The repository is public and the service is live at
`https://meridian-125g.onrender.com`, serving forecasts with model-written
narratives. `autoDeploy: true`, so a push to `main` deploys. `docs/PHASE_11_STATUS.md`
tracks what is left.

Read the two blockers at the bottom before you start.

## What the production image is

One container, built from `Dockerfile` at the repository root. It is not the
development image:

| | `backend/Dockerfile` | `Dockerfile` |
| --- | --- | --- |
| Purpose | Runs the quality gate | Serves the application |
| Python extras | `--extra dev` (pytest, ruff, mypy) | none |
| Evaluation package | copied, so the gate can check it | **omitted** |
| Browser bundle | not built | built and served from `/` |
| Size | 2.75 GB | 1.55 GB |

The evaluation package reads outcome labels. It is absent from the serving
image entirely, so a served process could not import it even if a future
mistake asked it to.

## Verify it locally first

```bash
make bootstrap        # data, index, model, curated demo runs
make prod-build       # build the single-container image
make prod-up          # run it on http://localhost:8080 the way Render will
```

Then check the five things that have actually broken during development:

```bash
curl -s localhost:8080/api/health | jq '.status, .subsystems'
curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/            # 200, the shell
curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/review      # 200, client route
curl -s localhost:8080/api/nope                                     # {"code": ...}
curl -s localhost:8080/api/demo-runs | jq '.[].kind'                # four kinds
```

Then run one real assessment, because the five checks above are all reads and a
deployment can pass every one of them while being unable to write:

```bash
RUN=$(curl -s -X POST localhost:8080/api/assessments \
  -H 'content-type: application/json' \
  -d '{"account_id":"ACC-1042","question":"renewal risk","requester_role":"csm"}' \
  | jq -r .run_id)
sleep 15 && curl -s localhost:8080/api/assessments/$RUN | jq '.status, .route, .error'
```

It must end `"completed"`, never `"failed"`. The first one takes about seven
seconds because it loads the embedding model; later ones take under half a
second.

`make prod-down` stops it.

**The image needs no mounts.** It carries the source tables, the retrieval
index, the derived tables, the account split, and the calibrated forecaster --
about 80 MB, listed in `.dockerignore` with the reason for each inclusion. That
is what makes `make prod-up` a rehearsal of a deployment rather than a local
convenience: a hosting platform has no equivalent of a bind mount from your
laptop, so anything the image does not carry is simply absent there.

`data/app`, the one directory the application writes, is deliberately *not* in
the image. It is created on first write inside the container's own layer, so
every fresh container starts with an empty assessment history.

## Deploying to Render

1. **Make the repository public**, or connect Render to a private repository
   (Render supports this on paid plans; the free plan needs a public repo).
   Nothing in this repository is ready to be published until you have read the
   blockers below.
2. In Render, **New → Blueprint**, and point it at the repository. It reads
   `render.yaml`; you should not need to configure anything in the dashboard.
3. Render will prompt once for `MERIDIAN_LLM_API_KEY`, which is declared
   `sync: false` so it is never written to the repository. **Leave it empty**
   unless you want the demo spending your OpenRouter budget: the system
   completes without a provider and says so in its own limitations, and the
   four curated runs need no key at all.
4. First deploy takes a while — the image is 1.55 GB and the free plan builds
   slowly. `autoDeploy: true`, so a push to `main` deploys; the gate runs on
   every push, which is what makes that safe.
5. Check `/api/health` on the live URL. `status: "degraded"` with
   `dataset: absent` means the data volume is missing, which is the failure
   discussed under blockers.

### What `render.yaml` already decides

Demo mode on, scans and evaluations refused, 20 runs per client per hour, 200
per day service-wide, concurrency 2, scheduler off, CORS restricted to the
service's own hostname. Those are in the file so the deployment's cost and
safety posture is reviewable in the repository rather than in a dashboard
nobody else can see.

## Cold starts

A Render free instance sleeps after inactivity and takes roughly 50 seconds to
wake. **Measured on this deployment: 42.4 seconds** from a cold request to
`/api/health` answering `ok` with all five subsystems ready. That is a property
of the plan, not of this application. The README says so, and the app's health
pill shows what is and is not ready while it comes up.

A model-backed assessment on the free instance takes **about 25 seconds** end to
end -- ACC-1001 completed in 17 events with 3 model calls and 4,879 tokens. The
same account offline on a laptop takes about half a second. Almost all of the
difference is the provider, not the plan.

## Blockers: two closed, one mitigated

### 1. ~~The dataset is not in the image~~ -- closed

The image now builds everything the served application reads, so a deployment
starts `ok` rather than `degraded`. Verified by running it with no mounts and
`HF_HUB_OFFLINE=1`: all four data subsystems ready, 15 endpoint checks green,
and assessments returning forecasts with 10 to 12 citations each. Under
thresholds v2 (D-061): ACC-1001 **green**/Churned at 0.8363, ACC-1042
amber/Churned at 0.7991, ACC-1002 amber/Renewed at 0.9207, ACC-1000 red/Renewed
at 0.6395, ACC-1089 red with no label on an unresolved conflict -- matching the
committed traces to four decimals.

Two of those are worth reading together. ACC-1042 misses the green band by
0.0009, and ACC-1002 clears it by 0.12 and is still held: confidence is one of
section 16.5's conditions, and ACC-1002 fails a different one, stale sources. A
band is not the whole router.

**That verification names forecasts and citations, and it is worded that way
because the first version of it said "assessments completing and opening review
cases" -- which was true, and hid a broken deployment.** They completed by
degrading: every run returned verified telemetry with no forecast and zero
citations, because the runtime stage copied the account tables but not
`rag_corpus/knowledge_base.jsonl`. Every search calls `load_verified_index`,
which rebuilds the parent documents to check the index digest against the
corpus this code produces today, and building parents reads the knowledge base.
The file is 47 KB; without it the product does not work at all.

`/api/health` reported the index ready throughout, because it looked only for
the `.faiss` file. It now checks the knowledge base beside it, and
`backend/tests/test_health.py` pins both halves: the readiness check, and a
reading of this Dockerfile asserting the runtime stage still copies the file.
An assertion that a run *completed* is not an assertion that it answered.

**It builds the data rather than copying it, and that distinction is the whole
answer.** The obvious implementation -- add `COPY data/indexes` and friends --
works on a machine that has run `make bootstrap` and fails everywhere else,
because `.gitignore` excludes those paths. A hosting platform builds from a
clone. `git archive HEAD` shows exactly what Render would get:

| Path | In a fresh clone |
| --- | --- |
| `meridian-account-health.zip` | present, 4.2 MB |
| `data/splits` | present, 8 KB |
| `data/raw`, `data/processed`, `data/indexes`, `models` | **absent** |

So the `databuild` stage extracts the committed archive and runs the same three
commands a developer runs, and the serving stage copies only their outputs.
`.dockerignore` excludes `data` and `models` from the build context entirely,
which is what stops the host's copies from quietly satisfying a `COPY` and
hiding the problem until the first deploy.

The stage is separate for a second reason: `build_data.py` and `train_model.py`
import `meridian_eval`, which reads outcome labels, and D-056 says no served
process may be able to import it. Building there and copying only the outputs
keeps that true -- the serving image still has no evaluation package.

| Step | Time |
| --- | --- |
| Extract the archive | under a second |
| `build_data.py` | 2.8 s |
| `train_model.py` | 15 s |
| `build_index.py` -- embeds 17,140 chunks | **6 min 35 s** |

Effectively all of it is the index. It is one Docker layer, so it is rebuilt
only when the archive or the build code changes; Render's build machines are
slower than a laptop, so budget noticeably more for the first deploy. The index
is reproducible: the in-image build produced corpus digest
`a4e8b5c570708b89...`, byte-identical to a local `make index`.

The image went from 1.47 GB to **1.55 GB**. The earlier estimate here said this
option would push it "past 2.5 GB", which was wrong twice over: it predated the
640 MB of uv cache being removed, and it assumed shipping the whole extracted
archive. Two large things turn out not to be needed at run time -- the 28 MB
`rag_corpus`, because its text is already inside `metadata.sqlite`, and the
4.2 MB archive itself once the tables are extracted.

One thing to be aware of rather than alarmed by: `renewal_outcomes.csv` is among
the extracted tables, because `load_raw_dataset` loads every table.
`RuntimeRepository` strips latent fields before anything is served and the
browser suite asserts that no response carries one, so it cannot leave through
the API -- and the same file is already published in
`meridian-account-health.zip` in this public repository, so it is no new
exposure.

(`artifacts/` used to be excluded too, and no longer is. It is committed, under
a megabyte, and `GET /api/evaluations/{name}` reads it, so excluding it made the
deployed evaluation page report every evaluation as never run.)

**The embedding model was a fourth missing piece, and is also baked in.**
`fastembed` fetches `qdrant/bge-small-en-v1.5-onnx-q` from the HuggingFace Hub
the first time anything retrieves. Left to run time that is a 65 MB download
inside the request that triggers it, it needs outbound network access from the
serving container, and it is subject to the Hub's anonymous rate limit. It is
pre-populated in the shared dependency stage, so the index build uses it too
rather than downloading the same model twice.

### 2. The review queue is writable by anyone who can reach the demo -- mitigated, not fixed

`POST /api/review-cases/{case_id}/decision` has no authentication, and demo mode
does not cover it. Demo mode restricts which accounts can be assessed, replaces
free-text questions, and refuses portfolio scans -- but a visitor can resolve a
review case. Verified against the production image: an anonymous request with
`{"action": "approve", "reviewer": "anon"}` returned 200 and marked the case
resolved.

Section 24.3 anticipates this and gives one mitigation: *keep review and
assessment storage ephemeral in the free public demo*. Choosing to bake the data
into the image (blocker 1) delivers exactly that, for free. `data/app` is not in
the image; it is created on first write inside the container's own layer.

**The precise claim, because the imprecise one is wrong.** State survives a
restart of the same container -- measured: two cases before a `docker restart`,
two after. It is gone when the container is *replaced*, which a fresh container
from the same image demonstrates: zero cases. On a free plan that spins an idle
service down and starts a new container on the next request, and on every
deploy, those amount to the same thing. Do not describe it as "resets on
restart"; describe it as "resets whenever the container is replaced".

So the exposure is bounded rather than removed. What remains true:

- A visitor can resolve cases, and other visitors will see them resolved until
  the container is replaced.
- Nothing they can do reaches the source data, which is read-only in the image
  and immutable by policy.
- Attaching a persistent disk would remove the mitigation entirely. If you ever
  do, add authentication or refuse review writes in demo mode first;
  `enforce_demo_mode` in `backend/src/meridian/serving/limits.py` is where the
  other demo restrictions live, and `scans.py` shows the one-line refusal
  pattern.

Nothing here affects a local run: `make prod-up` binds to localhost.

### 3. ~~The repository is private and unlicensed~~ -- closed

The licence is Apache-2.0 (`LICENSE`, `NOTICE`), which closed O-003, and the
repository is now public, which unblocks Render's free plan.

The history was checked before publication rather than after: `.env` appears in
no commit, and no OpenRouter or Anthropic key pattern appears anywhere in the
23-commit history. The only credential-shaped files tracked are `.env.example`
and `config/app.example.env`, both with empty values. Re-check at any time with:

```bash
git log --all --full-history -- .env          # should print nothing
make security                                  # scans the working tree
```

Publishing does not by itself expose anything served: `make prod-up` binds to
localhost, and no deployment answers. Blocker 2 is about a deployment, not about
the repository.

## Verified

`make phase0-verify` on the locked images: formatting over 152 files, ruff,
strict mypy over 151 source files, 660 backend container tests with 42 expected
skips at 94.86% coverage, 98 frontend tests, the production frontend build, the
repository policy scan over 343 files, and both application health checks.

Separately, against the production image itself (`make prod-build`,
`make prod-up`):

| Check | Result |
| --- | --- |
| `/api/health` | `ok`, all five subsystems ready |
| `/` and `/review` | 200, the compiled shell |
| `/assets/index-*.js` | 200, `text/javascript` |
| `/api/nope` | 404 with `{"code": "ACCOUNT_NOT_FOUND", ...}` |
| `/api/demo-runs` | four kinds, each `is_cached: true` |
| Demo mode on a free-text question | replaced with the curated question |
| Demo mode on a portfolio scan | `REQUEST_BLOCKED` |
| A live assessment | completed, routed red, 0 tokens, all five guardrail stages |
| An assessment that persists | `completed` with an `assessment_id`, proving `data/app` is writable |
| A conflict the search cannot resolve | no outcome asserted, a review case opened, routed red |

Measured on the production image on an Apple-silicon laptop, with the dataset,
model, and index bind-mounted:

| Phase | Time |
| --- | --- |
| Container start to `/api/health` answering `ok` | about 3 seconds |
| First assessment, which loads the embedding model | about 7 seconds |
| Every later assessment | about 0.4 seconds |

These are local numbers on warm page cache and a fast disk. They are a floor for
a deployment, not a prediction of one: Render's free plan adds image pull, cold
container start, and -- unless the model is baked in as blocker 1 describes --
the 65 MB download on the first request after every idle spin-down.

## What is not done

- **A deploy has been attempted and does not answer.** A Render free-plan
  service was created from this Dockerfile at `meridian-125g.onrender.com` on
  commit `fbac4f3`. Seven probes of `/api/health` on 2026-09-03, at timeouts
  from 30 to 150 seconds, all returned `HTTP 000`: the TLS handshake completes
  against Render's edge and no response follows. That is not spin-down, which
  answers slowly rather than never. Memory is ruled out — the local production
  container peaks at 226 MB against the plan's 512 MB cap — and the remaining
  candidates are a failed or timed-out build, a container not binding `$PORT`,
  and a deploy stuck mid-roll. The plan's "public application URL" deliverable
  stays open; `docs/PHASE_11_STATUS.md` records the detail.
- **No demo video or GIF.** The plan asks for a recorded backup; screenshots
  are in `docs/screenshots/`.
- **Cold and warm start timings are measured locally but not on a deployment.**
  The table above is `make prod-up` on a laptop. What a Render cold start costs
  is still unknown, and it is the number that matters for a public demo.
