# ADR 0001: Use LangGraph for orchestration

- Status: Accepted
- Date: 2026-08-31
- Deciders: Project owner and implementation agent

## Context

The capstone needs explicit routing, parallel analysis and retrieval, bounded retry behavior,
checkpointed state, human-review interrupts, and traceable execution. The submitted design evolved
from a single ReAct loop into four collaborating logical agents and a conflict-gated Tree-of-Thought
subgraph.

## Decision

Use LangGraph as the only runtime orchestrator. Represent workflow state with strict typed schemas;
keep quantitative, retrieval, policy, and adjudication logic in ordinary services; and invoke those
services from small graph nodes. Tree-of-Thought runs only when the evidence-conflict gate fires and
is bounded to four initial candidates, depth two, and beam width two.

## Consequences

The control flow remains inspectable and testable, retries and interrupts are explicit, and graph
state can be checkpointed. LangGraph becomes a core dependency, so business logic must remain
framework-independent and no second orchestration framework may be introduced without a new ADR.

## Alternatives considered

- A hand-written state machine would reduce dependencies but would recreate checkpointing, fan-out,
  interrupts, and trace support.
- CrewAI would demonstrate another multi-agent framework but would duplicate orchestration ownership.
- An unconstrained ReAct loop would be simpler initially but would not provide the required bounded,
  reviewable control flow.
