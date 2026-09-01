# Module 7 submission checklist

Derived from `docs/source/MODULE_7_CAPSTONE_REQUIREMENTS.md`. Split by who can
finish each item: the repository can carry evidence, but it cannot record a
video, publish itself, or submit anything.

## Done in the repository

| Item | State | Where |
| --- | --- | --- |
| README explains project, architecture, setup, usage | Done | `README.md` |
| Main code | Done | `backend/`, `frontend/`, `evaluation/`, `dataset/` |
| Evaluation artifacts committed and citable | Done | `artifacts/` (now tracked) |
| Sample outputs a reviewer can read without running anything | Done | `artifacts/traces/TRACES.md`, `artifacts/evaluation/*/REPORT.md` |
| Clear instructions for running or reviewing | Done | `README.md` quick start, `make help`, `AGENTS.md` |
| Repository organised for an outside reader | Done | `docs/` map; one status document per phase |
| Report section to evidence map | Done | `docs/CAPSTONE_EVIDENCE.md` |
| Design evolution across Modules 1–6 | Done | `docs/DESIGN_EVOLUTION.md` |
| Final architecture diagram, verified against the code | Done | `docs/ARCHITECTURE.md` |
| UI screenshots | Done | `docs/screenshots/` (6 captures) |
| Representative traces: fast, ToT, degraded, human review | Done | `artifacts/traces/` |
| Evaluation results, limitations, next steps | Done | `docs/CAPSTONE_EVIDENCE.md`, `docs/PHASE_10_STATUS.md` |
| Licence | Done | Apache-2.0, `LICENSE` |
| Deployment configuration and runbook | Done | `Dockerfile`, `render.yaml`, `docs/DEPLOYMENT.md` |

## Needs a decision or an action outside the repository

| Item | Blocked on | Notes |
| --- | --- | --- |
| Repository is **public** | You | Currently private by your decision. Module 7 requires public; Render's free plan does too. |
| Public repository **link** in the report | The above | |
| Live application URL | Deployment choice | `docs/DEPLOYMENT.md` — pick how data, model, and index reach the image first. |
| Final report as PDF or DOCX | You | Content is sourced; the document itself is yours to write. |
| 8–10 minute recorded presentation | You | Cover problem, goal, architecture, decisions, evaluation, repo, strengths, limitations, next steps. |
| Video hosted with working sharing permissions | You | YouTube, Vimeo, or Loom. |
| Video-link document with a 2–3 sentence summary | You | Submitted alongside the report. |
| Optional 90-second elevator pitch | You | Only needed for showcase consideration. |
| Confirm the deadline | You | The Canvas text says `Sep 7 by 4:29pm` with no year or timezone. |

## Content the report can lift directly

Nothing below needs rewriting from scratch — it is already assembled and
verified:

- **Problem, user, and scope** — `docs/PROJECT_CONTEXT.md`
- **Architecture and the four agents** — `docs/ARCHITECTURE.md`, `README.md`
- **Design evolution** — `docs/DESIGN_EVOLUTION.md`, structured as held / changed / not built
- **Evaluation numbers with their artifacts** — `docs/CAPSTONE_EVIDENCE.md`
- **Safety and oversight** — `artifacts/safety/SAFETY_REPORT.md`, `docs/PHASE_7_STATUS.md`
- **Limitations** — `docs/CAPSTONE_EVIDENCE.md`, and the known-limitations section of each phase document
- **Decisions worth narrating** — `docs/DECISIONS.md`, `docs/adr/`

## Four claims worth leading with

These are the ones the evidence actually supports, and they are more specific
than "we built an agentic system":

1. **The system can decline.** Abstention is a separate result type with no
   outcome field, so the degraded path cannot emit a label even by mistake.
   `artifacts/traces/degraded.json` shows a real retrieval outage returning 21
   verified metrics and no forecast.
2. **Thresholds were frozen before the held-out split was touched**, with a
   digest a test pins. The threshold sweep runs on development data only.
3. **Every published number is generated, not typed.** The report renderer
   formats from the result dictionary and contains no literal metrics.
4. **The result that missed its target is reported as missed.** ECE is 0.1712
   against a 0.10 target, printed as **not met** in the generated report.

## What to say about the parts that are not finished

Say them plainly; each is defensible:

- **Calibration misses its target.** The fix belongs on development data with a
  re-freeze before the test split is touched again, and doing that properly was
  out of scope for the build window.
- **Auto-release is near zero at the frozen bands.** The threshold study shows
  what loosening would buy and cost — 70 of 207 released with 4 wrong at the most
  permissive band measured — and that trade is a business decision, not an
  engineering one.
- **No live-provider evaluation.** Every metric comes from the deterministic
  path at zero tokens. That makes the results reproducible for free; it also
  means the model-written narrative is not what was scored.
