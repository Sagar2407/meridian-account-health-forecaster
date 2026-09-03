# Phase 4 status: MCP tools and the provider adapter

Status: **Complete; exit gate passed on 2026-08-31**

This phase still needs no API key. The eight tools are deterministic by
construction, and the language-model layer is an interface plus adapters that
report precisely why they cannot run when no credential is present. A single
opt-in test calls a real provider; everything else in the suite is offline.

## Deliverables

| Plan task | Status | Evidence |
| --- | --- | --- |
| Typed service functions | PASS | `meridian.tools.services`; eight plain methods, no transport, no event loop |
| Read-only services wrapped in the official MCP SDK | PASS | `meridian.tools.server`, `mcp` 1.29.1 |
| Local MCP client adapter | PASS | `meridian.tools.client`, in-memory session; no subprocess or port |
| Base LLM interface and OpenAI adapter | PASS | `meridian.llm.base`, `meridian.llm.openai_compatible` |
| Optional adapter skeletons that fail clearly | PASS | `meridian.llm.providers`; Anthropic, Azure, Ollama, disabled |
| Structured outputs and retries | PASS | `generate_structured`; strict JSON Schema, exactly one repair attempt |
| MCP contract tests | PASS | `backend/tests/test_tools_mcp.py` |
| Provider-independent structured-generation tests | PASS | `backend/tests/test_llm_structured.py` |

## Exit gate

| Criterion | Result | Evidence |
| --- | --- | --- |
| Tools enforce cutoff and forbidden-field rules under malicious arguments | PASS | 48 registry tests; see below |
| Graph code imports provider interfaces, not provider SDKs directly | PASS | `test_only_the_named_adapter_may_import_a_provider_sdk` |

235 tests passing at 93.7% coverage, ruff and mypy strict clean across 76 files.
102 of those tests are new in this phase.

### What "malicious arguments" means here

The gate is only worth something if the arguments are genuinely hostile, so the
suite supplies them and asserts the call fails before any service runs:

| Attack | Result |
| --- | --- |
| `../../etc/passwd`, `ACC-1042; DROP TABLE accounts`, `ACC-1042 OR 1=1`, `ACC-*` as an account id | Refused by pattern |
| `file:///etc/passwd`, `https://example.com/leak` in a sub-goal | Refused as a URL |
| `` risk `whoami` ``, `risk $(cat /etc/passwd)`, `renewal risk; rm -rf /` | Refused as shell substitution or a command chain |
| `SELECT * FROM renewal_outcomes` in a sub-goal | Refused as SQL |
| A payload naming its own `role` | Ignored; the caller's role is authoritative |
| `window_weeks` at the maximum, or beyond it | Bounded, and measured backwards from the cutoff |
| `as_of` past the dataset horizon | Refused rather than silently clamped |
| An unknown argument such as `include_labels` | Refused, not dropped |
| A well-formed but non-existent account | `not_found`, never an empty answer |

Two things are checked on the way out as well as the way in: no response may
carry a forbidden field, and every response carries the cutoff it was computed
at, so a reviewer can confirm point-in-time safety from the answer itself
rather than from a log.

## The eight tools and who may call them

Section 12.3 requires a per-role allowlist. It is derived from section 13's
agent definitions rather than invented, and the notable case is the
Adjudicator: section 13.4 says "no new tool calls", so its allowlist is empty
and its MCP session advertises nothing at all.

| Tool | Orchestrator | Quantitative Analyst | Evidence Retriever | Adjudicator |
| --- | :---: | :---: | :---: | :---: |
| `get_account_profile` | ✓ | ✓ | ✓ | |
| `get_prior_assessments` | ✓ | | | |
| `compute_account_metrics` | | ✓ | | |
| `get_usage_series` | | ✓ | | |
| `get_support_summary` | | ✓ | | |
| `get_external_events` | | ✓ | | |
| `retrieve_account_evidence` | | | ✓ | |
| `retrieve_knowledge` | | | ✓ | |

The Orchestrator is deliberately thin: section 13.1 forbids it from doing
arithmetic or retrieving directly, so it can read identity and its own history
and nothing else.

## Three decisions worth recording

### The advertised schema omits `role`

A client never supplies its role. The session it is connected to determines it,
and the registry injects it. Advertising `role` in the input schema would invite
a client to send one, and a client that can name its own role makes the
allowlist advisory rather than enforced. This was found by the MCP contract
test, which failed with `'role' is a required property` when the schema was
published unmodified.

### The injection filter rejects shapes, not characters

The first version refused any of ``` ` $ ; | & < > ``` in a sub-goal. That also
refuses "low adoption & open tickets", "adoption < 50%", and "R&D spend" —
ordinary business language. A filter that makes the tool useless is not a
safety measure, so the rule now matches substitutions (`` ` ``, `$(`, `${`) and
separators followed by a command name (`; rm`, `&& curl`), and SQL keywords in
statement position. `test_ordinary_sub_goals_still_pass` exists specifically to
stop the filter drifting back toward strictness that costs more than it buys.

### Application memory is physically separate from source data

Plan section 12.2 allows internal writes — assessment snapshots and review
cases — while Meridian's own data stays immutable. `AssessmentStore` refuses at
construction to open a database anywhere under `data/raw/`, so a misconfigured
path fails at startup rather than after a write.

## Language-model layer

Nothing outside `meridian/llm/openai_compatible.py` may import a vendor SDK, and
the boundary test checks both directions: that no other module imports one, and
that the adapter still does. A rule guarding a dependency that has since been
removed would keep passing while enforcing nothing.

Structured output is enforced twice. The adapter asks the provider for
`response_format: json_schema` with `strict: true`, and `generate_structured`
validates the reply against the Pydantic model regardless of what the provider
promised. A reply that fails gets exactly one repair attempt, with the
validation error fed back verbatim, and then the call fails — an unbounded
repair loop turns one bad reply into an unbounded bill.

The provider is configured, not compiled in:

```bash
MERIDIAN_LLM_PROVIDER=openai_compatible
MERIDIAN_LLM_MODEL=anthropic/claude-sonnet-4.5
MERIDIAN_LLM_BASE_URL=https://openrouter.ai/api/v1
MERIDIAN_LLM_API_KEY=
```

Anthropic's models are reached through OpenRouter's OpenAI-compatible endpoint
rather than a separate adapter, because the wire format is identical and only
the base URL and model slug differ. `OPENAI_API_KEY` is still accepted as a
second name for the key, for continuity with earlier phases; the base URL, not
the variable name, decides which service is called.

## Known limitations

- **The adapter has not been run against a live provider in this phase.**
  The offline suite proves its shape, not that the shape is the one a given
  provider expects — strict `json_schema` support varies. One opt-in test
  covers it and is skipped by default because it spends money and sends a
  prompt to a third party:

  ```bash
  MERIDIAN_LLM_LIVE=1 ./scripts/python_in_docker.sh pytest backend/tests/test_llm_live.py -s
  ```

- **The tool timeout bounds the wait, not the work.** Python cannot safely kill
  a running thread, so a genuinely stuck call still occupies its worker. The
  services are local and CPU-bound, so this covers the realistic failure — a
  slow index load, a locked database — without claiming cancellation the
  runtime does not offer.
- **`save_assessment_snapshot` and `create_review_case` are not exposed as
  tools.** Section 12.2 says they should normally be deterministic graph
  operations rather than free-choice model tools, so they exist on
  `AssessmentStore` and will be called by the graph in Phase 7 rather than
  advertised over MCP.
- **The backend image is now 2.64 GB.** (It is 2.75 GB as of the latest
  measurement, and the separate serving image built by the root `Dockerfile` is
  1.47 GB; see `docs/DEPLOYMENT.md`.) Most of that arrived with Phase 3
  (faiss, onnxruntime, fastembed, scikit-learn, pandas); `mcp` and `openai` add
  little. It is not a problem locally, but ADR 0005 targets Render, where image
  size affects cold start and the free tier's disk. Phase 11 should measure it
  and consider a slimmer serving image that omits the training and evaluation
  dependencies.
- **Only an in-process MCP transport exists.** Stdio and HTTP transports are
  available in the SDK and add nothing to test today; `LocalToolClient` is the
  single place a later phase changes to use one.
