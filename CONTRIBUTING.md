# Contributing to Meridian

Meridian is developed in phase-sized changes with explicit exit gates. Read `AGENTS.md`, the
active phase in `docs/Meridian_Autonomous_System_Implementation_Plan.md`, and the safety rules in
`docs/DATA_SAFETY.md` before changing code.

## Local workflow

1. Use Python 3.11 or 3.12, Node.js 22, pnpm, and Docker with Compose.
2. Copy `.env.example` to `.env`; never put real credentials in a tracked file.
3. Run `make setup` once, then `make check` before opening a pull request.
4. Keep raw data immutable and write derived artifacts only to ignored output directories.
5. Add tests for every behavior change, especially time cutoffs, evidence scope, and safety routes.

## Pull requests

Keep a pull request within one implementation phase. Include the requirement IDs affected, the
commands run, and any known validation gaps. Architectural changes require an ADR in `docs/adr/`.

All product behavior is advisory, read-only, and limited to the synthetic Meridian dataset.
