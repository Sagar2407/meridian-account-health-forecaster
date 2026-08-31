# Project Context

## Course and final objective

This repository supports the final capstone for the CMU Agentic AI Program. Module 7 requires an integrated autonomous system that addresses a genuine problem and can be explained, evaluated, and demonstrated to a technical audience.

The final submission must tell a cohesive design story rather than concatenate six weekly checkpoint assignments. It must show how the architecture evolved, how the components work together, what was implemented, what the evaluation demonstrates, and where limitations remain.

## Problem

Customer Success Managers, Field Engineers, Technical Account Managers, and Customer Success leaders manage portfolios containing more accounts than they can examine deeply and consistently. Renewal triage commonly requires combining time-series usage, support history, CSM notes, QBRs, external signals, contract context, and domain playbooks.

A prompt-only language model is insufficient because it lacks the private account evidence, performs arithmetic unreliably, can invent plausible drivers, and cannot safely decide when to abstain or escalate.

## Proposed system

The Enterprise Account Health Forecaster evaluates a fictional Meridian account and returns:

- One of four renewal outcomes when evidence supports a label: churn, contraction, flat renewal, or expansion.
- A calibrated confidence and four-class distribution.
- Exact quantitative drivers with metric windows and provenance.
- Supporting qualitative evidence and counterevidence with citations.
- Coverage limitations.
- A bounded recommended action.
- A green, amber, red, or blocked route.

When evidence is insufficient, the system returns verified telemetry, describes the gap, requests the missing information, and omits an unsupported categorical outcome.

## Intended users

- Customer Success Managers
- Field Engineers
- Technical Account Managers
- Customer Success leaders
- Human reviewers responsible for consequential or uncertain cases

## Dataset

The system operates only on the synthetic Meridian Account-Health dataset. The package was generated deterministically with seed `20260721` and dataset as-of date `2026-06-28`.

The dataset combines structured account attributes, weekly telemetry, support tickets, CSM notes and QBRs, external events, a knowledge base, renewal labels, known generative drivers, golden questions, and guardrail cases.

The synthetic design allows the public project to demonstrate realistic data modalities and evaluate driver explanations without using proprietary or personal organizational data.

## Design evolution across checkpoints

### Checkpoint 1.1 — Problem and initial agent

Defined the Forecaster problem, intended users, four outcome classes, evidence-grounding requirement, deterministic calculations, and the need to decline or escalate when evidence is inadequate.

### Checkpoint 2.1 — ReAct, memory, and tools

Introduced a ReAct-style evidence loop, working and long-term memory, a deterministic computation tool, a qualitative retrieval tool, coverage flags, and reconcile-or-escalate behavior.

### Checkpoint 3.1 — Retrieval design

Separated deterministic quantitative evidence from semantic qualitative retrieval. Added account and date filters, parent-child chunking, top-k retrieval, MMR/reranking, citation requirements, and the sourced-but-wrong evidence failure mode.

### Checkpoint 4.1 — Bounded Tree-of-Thought

Restricted Tree-of-Thought to conflict adjudication. Established four root hypotheses, depth two, beam width two, hard deterministic pruning, soft critic scoring, and tie-to-human escalation.

### Checkpoint 5.1 — Multi-agent architecture

Finalized four logical agents, a compiled LangGraph workflow, parallel quantitative and retrieval lanes, shared typed state, and deterministic structural transitions.

### Checkpoint 6.1 — Safety and human oversight

Extended safety across intake, data access, tool execution, adjudication, output, runtime tracing, confidence routing, and human review. Defined five evaluation dimensions and fail-soft retrieval behavior.

### Module 7 — Integration and communication

Requires a complete, cohesive system; actual evaluation results; a public and understandable repository; a final report; and an 8–10 minute technical presentation.

## Final architectural interpretation

The latest implementation plan resolves earlier framework ambiguity:

- LangGraph owns orchestration and per-run state.
- MCP standardizes typed tools and resources.
- CrewAI is not required in version 1.
- Generator and critic capabilities live inside the Forecast Adjudicator's LangGraph subgraph.
- Hidden chain-of-thought is never persisted or shown.

## Autonomy boundary

The system is autonomous in reversible analysis: planning, evidence gathering, computation, retrieval, verification, confidence calculation, routing, internal review-case creation, and bounded portfolio scanning.

It is not autonomous in consequential action. It must not contact customers, change source records, make HR judgments, approve discounts, send contracts, or make commercial commitments.

## Submission status

Available:

- Six checkpoint documents
- Dataset archive, README, data dictionary, generator, and evaluation artifacts
- Detailed implementation plan
- Module 7 assignment instructions

Still needed:

- A confirmed public GitHub repository URL
- A confirmed live-demo hosting decision and URL
- Implemented application and actual evaluation results
- Final report, presentation, video, and submission-link document

Deferred by the user and excluded from current planning:

- Official final-report template
- Official presentation-planning outline
- Any separate detailed grading rubric

The Module 7 text lists a due date of September 7 at 4:29 PM but does not include a year in the pasted source. Confirm the deadline directly in Canvas.
