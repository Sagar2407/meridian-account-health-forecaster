# ADR 0005: Use Render for the public demonstration

- Status: Accepted
- Date: 2026-08-31
- Deciders: Project owner and implementation agent

## Context

The capstone needs a public, portfolio-grade demonstration with simple reviewer access and a small
operational footprint. Local development uses two containers, while public deployment benefits from
one web service and tightly controlled synthetic demo data.

## Decision

Target Render for the public deployment. A later phase will add one multi-stage production image
that builds the React client, installs the Python service, serves static assets through FastAPI, and
binds to Render's `PORT`. `render.yaml` will capture infrastructure configuration. Demo mode will
enforce bounded account selection, request limits, concurrency limits, and provider budgets.

## Consequences

The public demo has a straightforward deployment story and a single origin. The final image must
package all required local artifacts, avoid writable-local-disk assumptions, and keep credentials in
Render's secret store. Deployment implementation is intentionally deferred to its planned phase.

## Alternatives considered

- Separate static hosting and API hosting could optimize each tier but complicates CORS and review setup.
- A large cloud platform offers more controls but adds infrastructure disproportionate to the capstone.
- A local-only demo is cheapest but does not satisfy the desired public portfolio experience.
