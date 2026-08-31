# ADR 0003: Use FAISS with SQLite for local retrieval

- Status: Accepted
- Date: 2026-08-31
- Deciders: Project owner and implementation agent

## Context

Meridian has roughly twelve thousand synthetic corpus records plus a small knowledge base. The
portfolio demo must be reproducible and usable locally without a managed vector database. Retrieval
must enforce account scope, document visibility dates, and provenance.

## Decision

Use FAISS for the local vector index and SQLite for document metadata, parent text, visibility dates,
and provenance. Build indexes only from sanitized, runtime-safe documents. Apply metadata filters
before evidence can enter an assessment and return stable citation identifiers with every hit.

## Consequences

The demo has low infrastructure cost and deterministic local assets. FAISS does not supply metadata
governance or multi-user durability, so those responsibilities live in the retrieval service and
SQLite repository. A hosted vector adapter may be added later without changing retrieval contracts.

## Alternatives considered

- Chroma offers integrated metadata but adds another persistence abstraction for this dataset size.
- A hosted vector database improves managed scaling but adds credentials, cost, and network dependence.
- Brute-force embedding similarity is adequate for experiments but is a weaker portfolio deployment path.
