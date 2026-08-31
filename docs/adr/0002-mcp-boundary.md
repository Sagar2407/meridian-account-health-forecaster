# ADR 0002: Use MCP as a typed tool and resource boundary

- Status: Accepted
- Date: 2026-08-31
- Deciders: Project owner and implementation agent

## Context

The system needs reusable, discoverable access to account facts, metrics, retrieval, memory, and
evaluation resources. These interfaces must remain read-only, account-scoped, and point-in-time
safe. MCP is an interoperability boundary, not an orchestration engine or shared-memory model.

## Decision

Implement business services first, then expose selected operations through the official MCP Python
SDK. Every tool has a strict input/output schema, explicit account and cutoff arguments, a read-only
contract, and audit metadata. LangGraph nodes call the same underlying services. Shared workflow
state stays in LangGraph and durable application state stays in repositories.

## Consequences

Tools can be tested without transport and reused by other MCP clients. The separation adds adapter
code but avoids coupling core logic to MCP or leaking protocol objects into graph state.

## Alternatives considered

- Direct graph-to-database calls would reduce adapter code but weaken reuse and policy enforcement.
- Passing shared state through MCP would confuse protocol and orchestration responsibilities.
- A custom tool protocol would avoid an SDK dependency but lose standard discovery and interoperability.
