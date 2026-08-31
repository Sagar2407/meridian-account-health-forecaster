# ADR 0006: Use SQLite behind repository interfaces

- Status: Accepted
- Date: 2026-08-31
- Deciders: Project owner and implementation agent

## Context

The local application needs durable metadata, assessments, review cases, audit events, graph
checkpoints, and retrieval parent documents. The portfolio should run without a database service but
must retain a credible path to a multi-user public deployment.

## Decision

Use SQLite for local persistence and hide database access behind typed repository interfaces. Keep
runtime tables physically separate from evaluation-only data. Define migrations and transaction
boundaries explicitly. Add a PostgreSQL implementation only when public deployment requirements
justify it; domain and graph code must depend on repositories, not SQLAlchemy sessions or SQL text.

## Alternatives considered

- PostgreSQL everywhere provides production concurrency but makes the local grader setup heavier.
- In-memory state is easy to test but cannot support review queues, audit history, or restarts.
- Persisting graph and domain objects directly to files would create ad hoc consistency and migration
  problems.

## Consequences

Local development stays self-contained and deterministic. SQLite concurrency and ephemeral-host disk
constraints must be measured before deployment. Repository contracts and migrations add initial work
but make a PostgreSQL adapter and isolated tests practical.
