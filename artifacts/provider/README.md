# Running the system against a real language model, for nothing

Every published metric in this repository was produced offline, with no provider
configured. That is deliberate -- it makes the numbers reproducible by anyone,
with no key and no bill -- but it leaves a fair question unanswered: does the
model-backed path actually work, or is it only tested against fakes?

This directory answers it with one real run, on a 2.6B open-weight model, at
zero cost.

## The run

`open_weight_run.json` is a complete assessment of ACC-1042 with a provider
configured, captured with:

```bash
MERIDIAN_LLM_MODEL="liquid/lfm-2.5-2.6b:free" \
  ./scripts/python_in_docker.sh python scripts/assess_account.py ACC-1042 --json
```

| | |
| --- | --- |
| Model | `liquid/lfm-2.5-2.6b:free` (2.6B parameters, OpenRouter free tier) |
| `narrative_source` | `model` -- the explanation was written by the model, not the deterministic fallback |
| Planner | `source: model`, no fallback |
| Adjudicator | `narrative_source: model`, no fallback |
| Output verification | passed on the first attempt |
| Structured-output mode | `json_schema`, enforced server-side |
| Tokens | 7,382 |
| Cost | 0.00 USD |

Both model-backed nodes ran on the model, and the narrative survived output
verification -- which replays every number and citation against the evidence --
without a repair attempt.

## Swapping the model

The provider, model, base URL, and structured-output mode are all configuration.
`scripts/python_in_docker.sh` forwards them, so a single run can name its own
model without editing `.env`:

```bash
# A 2.6B open-weight model, free
MERIDIAN_LLM_MODEL="liquid/lfm-2.5-2.6b:free" make assess ACCOUNT=ACC-1042

# A frontier model, billed to your account
MERIDIAN_LLM_MODEL="anthropic/claude-sonnet-4.5" make assess ACCOUNT=ACC-1042

# No model at all: deterministic, offline, free
make assess ACCOUNT=ACC-1042 OFFLINE=1
```

Nothing else changes. The graph, the guardrails, the evidence screening, and
the output verification are identical in all three; only the wording of the
narrative differs, and where it came from is recorded on the decision as
`narrative_source`.

## What a 2.6B model is and is not good for

It is enough to demonstrate that the path works end to end. It is not enough to
produce the quality of explanation a frontier model writes, and the numbers in
this repository are not measured on it. Use a larger model for real output; the
only thing that changes is `MERIDIAN_LLM_MODEL`.

## Two things worth knowing before you rely on the free tier

**Free slugs are rate-limited, and the system treats that as a provider
failure -- correctly.** During capture, one earlier run hit the limit and the
adjudicator fell back to the deterministic narrative, recording it honestly in
its own limitations:

> Analysis narrative unavailable: the language-model provider failed, so this
> explanation is generated deterministically from verified values.

That is the designed behaviour and it is worth seeing: the run still completed,
still routed, still cited real evidence, and said plainly which parts were not
model-written. A demo that hits a rate limit degrades rather than breaks.

**Not every small model can do it.** Of four free slugs probed with the same
schema, one succeeded on the first attempt, two were rate-limited, and one
produced JSON that failed validation twice and was rejected. Structured output
is the constraint that matters when picking a small model, not general quality.
