# ADR 0004: Isolate LLM providers behind an internal adapter

- Status: Accepted
- Date: 2026-08-31
- Deciders: Project owner and implementation agent

## Context

The graph needs structured generation and optional model-assisted grading, but the repository must
remain runnable without a paid provider and must not bind orchestration code to one vendor. Model
availability, APIs, budgets, and deployment credentials can change independently of business logic.

## Decision

Define a provider-neutral internal interface for structured generation, usage metadata, timeouts,
and deterministic test doubles. The first hosted implementation will use the OpenAI Responses API.
Optional Azure OpenAI, Anthropic, and Ollama adapters may follow. Provider credentials are loaded
only from environment variables or deployment secrets; no key is required for Phase 0.

## Consequences

Graph nodes and tests remain portable and offline tests can use deterministic fakes. Provider-specific
features require explicit adapter capabilities and compatibility tests instead of leaking vendor SDK
objects into domain schemas.

## Alternatives considered

- Calling one provider SDK from graph nodes would be faster initially but create vendor coupling.
- A third-party universal gateway would reduce adapter work but add another external dependency and
  obscure provider-specific safety and usage metadata.
- Fully local inference avoids hosted cost but is not a reliable default for every reviewer machine.
