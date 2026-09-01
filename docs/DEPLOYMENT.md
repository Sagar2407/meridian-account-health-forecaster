# Deployment runbook

Everything here has been verified against the production image on this machine.
What has **not** happened is the deploy itself: that needs your Render account,
and the repository is still private, so Render cannot see it yet.

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
| Size | 2.64 GB | 2.2 GB |

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

`make prod-down` stops it.

The image mounts `data/` read-write, because the application writes its own
assessment history to `data/app`. Everything else it reads is baked in.

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
4. First deploy takes a while — the image is 2.2 GB and the free plan builds
   slowly. `autoDeploy: false` is set deliberately, so a push does not
   redeploy without you.
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

A Render free instance sleeps after inactivity and takes roughly **50 seconds**
to wake. That is a property of the plan, not of this application. The README
says so, and the app's health pill shows what is and is not ready while it
comes up.

## Two blockers before this can go live

### 1. The dataset is not in the image

`.dockerignore` excludes `data/` and `models/`, and the production image
inherits that. It is the right default — the archive is 25 MB and the model is a
build output — but it means a Render deployment starts with **no dataset, no
forecaster, and no retrieval index**, and `/api/health` will say `degraded` with
three subsystems absent.

(`artifacts/` used to be excluded too, and no longer is. It is committed, under
a megabyte, and `GET /api/evaluations/{name}` reads it, so excluding it made the
deployed evaluation page report every evaluation as never run.)

Three ways forward, in the order I would consider them:

- **Bake the runtime data into the image.** Add `COPY data/processed`,
  `COPY data/indexes`, and `COPY models` to `Dockerfile`, and drop those paths
  from `.dockerignore`. Simplest, entirely reproducible, and pushes the image
  past 2.5 GB.
- **Build them during the image build.** Run `make data`, `make index`, and
  `make train` as a build stage. Keeps the image self-contained and honest, and
  makes the build slow enough that Render's free tier may time out.
- **Attach a Render disk and bootstrap once.** Cheapest image, but the free
  plan has no persistent disk, so this needs a paid plan.

I have not chosen one, because the choice is about what you are willing to pay
for and how long you are willing to wait, and the trade is yours. The local
`make prod-up` path mounts the directories instead, which is why the
verification above works.

### 2. The repository is private and unlicensed until you say otherwise

The licence is now Apache-2.0 (`LICENSE`, `NOTICE`), which closes O-003. The
repository is still private, by your decision. Render's free plan requires a
public repository, so publishing is a prerequisite for the free path and not
for the paid one.

Once public, the whole history is public with it. `.env` has never been
committed and the policy scan checks every file for secrets and machine paths
on every gate run, but "no secret was ever committed" is a claim worth checking
yourself before you flip the switch:

```bash
git log --all --full-history -- .env          # should print nothing
make security                                  # scans the working tree
```

## Verified

`make phase0-verify` on the locked images: formatting over 143 files, ruff,
strict mypy over 142 source files, 606 backend container tests with 30 expected
skips at 94.78% coverage, 94 frontend tests, the production frontend build, the
repository policy scan over 304 files, and both application health checks.

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

## What is not done

- **No deploy has happened.** No live URL exists, so the plan's "public
  application URL" deliverable is open.
- **No demo video or GIF.** The plan asks for a recorded backup; screenshots
  are in `docs/screenshots/`.
- **Cold and warm start timings are unmeasured**, because there is nothing to
  measure them against yet.
