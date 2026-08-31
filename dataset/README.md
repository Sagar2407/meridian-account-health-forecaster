# Meridian Account-Health Forecaster — Synthetic Dataset

A fully synthetic, causally-grounded dataset for building and evaluating an
**Enterprise Account-Health / Renewal-Risk Forecaster** agent. It provides the
four data modalities such an agent reasons over — structured attributes,
time-series telemetry, unstructured text, and external signals — plus a labeled
target and ground-truth explanations for evaluation.

> **Compliance.** Everything here is invented. No real company, person, product,
> or customer data is used, and none of the vendor's own products, customers, or
> internal systems are referenced. "Meridian" is a fictional B2B
> digital-experience-platform vendor, and its module names (Content Management,
> Digital Asset Management, Analytics, Personalization, Campaign, Commerce) are
> generic category descriptors, not any real product. Company and person names are
> procedurally generated from generic word components; any resemblance to a real
> organization or individual is coincidental. The dataset is generated
> deterministically from a documented causal model (`RANDOM_SEED = 20260721`), so
> it is fully reproducible and safe to publish.

---

## 1. Why this is generated (and why that's a feature)

Real account data can't be used for a public coursework project, and no single
public dataset carries usage telemetry **and** account metadata **and** CSM notes
in one coherent world. So this dataset is generated from an explicit causal model
in which the true churn drivers are **known**. That yields two things a
downloaded dataset can't:

1. **Learnable signal you can trust.** Renewal outcomes are a function of the
   *observable* feature columns plus irreducible noise — not random labels.
2. **Gradeable explanations.** `eval/ground_truth_drivers.json` records the true
   driver contribution behind every account's outcome, so you can score whether
   the agent's *reasoning* is right, not just its label.

The schema is intentionally identical to what a Kaggle-seed → SDV → Faker →
live-news pipeline would produce, so you can swap those in locally with no rework
(see §7).

---

## 2. Quick start

```bash
# regenerate everything (deterministic)
python3 build_dataset.py

# load in Python
import pandas as pd, json
accounts = pd.read_csv("data/accounts.csv")
usage    = pd.read_csv("data/usage_weekly.csv", parse_dates=["week_start"])
tickets  = pd.read_csv("data/support_tickets.csv", parse_dates=["created_date"])
notes    = pd.read_csv("data/csm_notes.csv", parse_dates=["note_date"])
events   = pd.read_csv("data/external_events.csv", parse_dates=["event_date"])
features = pd.read_csv("data/account_features.csv")
outcomes = pd.read_csv("data/renewal_outcomes.csv")

# RAG corpus (one JSON object per line)
corpus = [json.loads(l) for l in open("rag_corpus/corpus.jsonl")]
```

Requirements: Python 3.10+, `numpy`, `pandas`, `matplotlib` (only for the sanity
plot). No network access and no external services required.

---

## 3. What's in the box

| File | Rows (approx.) | What it is |
|---|---|---|
| `data/accounts.csv` | 260 | One row per enterprise account (attributes, contract, renewal, latent labels) |
| `data/usage_weekly.csv` | ~67k | Weekly product-usage telemetry, per account × product × week (104 weeks) |
| `data/support_tickets.csv` | ~6.4k | Support tickets with full text, category, priority, sentiment, CSAT |
| `data/csm_notes.csv` | ~6.4k | CSM notes and QBRs — rich multi-section narratives (the RAG gold) |
| `data/external_events.csv` | ~600 | Synthetic news/market events per account (stand-in for live signals) |
| `data/account_features.csv` | 260 | Pre-computed observable features as of each account's forecast date |
| `data/renewal_outcomes.csv` | 260 | **Target**: outcome (Churned/Contracted/Renewed/Expanded), churn probability, reason |
| `rag_corpus/corpus.jsonl` | ~12.8k | Retrieval-ready docs (notes + tickets) with metadata for filtering |
| `rag_corpus/notes.jsonl` / `tickets.jsonl` | — | The same corpus split by source |
| `eval/golden_qa.jsonl` | 23 | Golden questions with ground-truth answers (portfolio + per-account) |
| `eval/ground_truth_drivers.json` | 260 | True driver attribution behind every account's outcome |
| `eval/validation_report.md` | — | Class balance and signal sanity checks |
| `eval/sanity_trajectories.png` | — | Example usage trajectory per health archetype |
| `knowledge_base/*.md` | 32 | Domain knowledge docs (playbooks, methodology, glossaries, product one-pagers, policies) |
| `rag_corpus/knowledge_base.jsonl` | 32 | The knowledge base, retrieval-ready |
| `rag_corpus/corpus_with_kb.jsonl` | ~12.9k | Account records **+** knowledge base combined, for a single embedding index |
| `eval/guardrail_eval.jsonl` | 36 | Labeled safety test cases (out-of-scope, privacy, leakage, conflicting-signal, overconfidence, human-review) |

Full field-level definitions are in **`DATA_DICTIONARY.md`**.

---

## 4. The four data modalities → your agent's inputs

| Agent input | Dataset source | Notes |
|---|---|---|
| **Structured attributes** | `accounts.csv`, `account_features.csv` | Segment, ACV, seats, products, renewal date, engineered features |
| **Time-series telemetry** | `usage_weekly.csv` | Weekly WAU, sessions, feature events, API calls, storage, advanced-feature adoption |
| **Unstructured knowledge (RAG)** | `csm_notes.csv`, `support_tickets.csv`, `knowledge_base/`, `rag_corpus/*.jsonl` | Account records (QBRs, tickets) **plus** general knowledge (playbooks, methodology, product docs) — chunk & embed |
| **External signals** | `external_events.csv` | Synthetic here; swap for live GNews/Firecrawl + Alpha Vantage in prod (§7) |

---

## 5. The causal generative process

Each account is assigned a latent **health archetype** that shapes its entire
history. Everything downstream is derived so the modalities *agree* with each
other (a declining account has falling usage, angrier tickets, worried QBRs, and
often an adverse external event).

```
account (archetype, segment, industry, products, sponsor, onboarding)
   │
   ├─▶ weekly usage trajectory        growth / flat / decay / cliff / stall / v-shape / seasonal
   ├─▶ external events                 adverse or favorable; cliffs are often preceded by a shock
   ├─▶ support tickets                 volume, category mix, and tone conditioned on health + events
   ├─▶ CSM notes / QBRs                narrative conditioned on adoption trend, sponsor, support, events
   │
   ├─▶ OBSERVABLE FEATURES             adoption trend & level, advanced-feature depth, product breadth,
   │                                   escalation rate, sentiment, CSAT, adverse events, sponsor change,
   │                                   onboarding status, days-to-renewal
   │
   └─▶ RENEWAL OUTCOME                 health_index = Σ(weightᵢ · zscore(featureᵢ)) + noise
                                       → quantile split into Churned / Contracted / Renewed / Expanded
                                       + ground-truth driver contributions
```

**The seven archetypes** (weights in `config.py`):
`expanding`, `stable_healthy`, `seasonal_healthy`, `slow_decline`, `sharp_drop`
(usage cliff tied to an external shock), `onboarding_stall`, `recovered`
(V-shape after a save play).

**Important:** the latent `health_archetype` and `health_band` columns are ground
truth for analysis only. **Do not use them as model features** — the outcome is
designed to be recoverable from the *observable* feature columns.

Validation (from the last run):
- Outcome mix ≈ 18% Churned / 10% Contracted / 52% Renewed / 20% Expanded
- `corr(adoption_trend, churn_probability) < 0` and `corr(sentiment, churn_probability) < 0` (correctly signed)
- Mean churn probability orders correctly across archetypes (stall/sharp_drop highest → expanding lowest)

---

## 6. How it exercises the six capstone concepts

- **Tool calling** — wrap the CSVs behind tools: `get_account`, `get_usage_series`,
  `list_tickets`, `rank_portfolio_by_risk`, `get_external_events`. The agent calls
  these instead of being handed a blob.
- **Reasoning (ReAct + Chain-of-Thought)** — the agent interleaves *thought →
  tool call → observation* to assemble a health picture and reason to a forecast.
- **Knowledge & memory (RAG)** — embed `rag_corpus/corpus_with_kb.jsonl`, which
  combines account records with a 32-doc domain knowledge base (playbooks,
  health-scoring methodology, glossaries, product one-pagers). Retrieve relevant
  QBRs/tickets to ground account judgments *and* general knowledge to answer
  "how do I run a save play?" — the mix needed for a domain-specific RAG agent
  and for testing hallucination against `ground_truth_drivers.json`.
- **Further reasoning (Tree of Thought)** — enumerate competing renewal
  hypotheses (renew vs contract vs churn), score each against the evidence, and
  select — ideal for the borderline accounts near the class boundaries.
- **Multi-agent coordination** — a natural split: a *Usage Analyst* (time-series),
  a *Relationship Analyst* (RAG over notes/tickets), an *External-Signal Agent*
  (events / live news), and an *Orchestrator* that synthesizes a forecast.
- **Safety** — the agent must (a) never fabricate account facts not supported by
  retrieved evidence, (b) express calibrated uncertainty on borderline accounts,
  (c) escalate high-value/at-risk cases to a human, and (d) treat data as
  sensitive. Test all of this with **`eval/guardrail_eval.jsonl`** (36 labeled
  cases): out-of-scope and unanswerable questions, privacy and target-leakage
  traps, real conflicting-signal accounts, overconfidence traps at the class
  boundary, and human-review-required cases — each with an `expected_behavior`
  label. The policy the guardrails should enforce is documented in
  `knowledge_base/KB-032-*` (Data Handling, Privacy & Agent Scope).

---

## 7. Local upgrade path (SDV / Faker / live news)

The schema is stable, so you can raise fidelity locally without touching the agent:

- **Faker** → replace the built-in name banks in `config.py`/`generators.py`
  with `Faker()` providers for `account_name`, `csm_name`, `exec_sponsor_name`,
  addresses, etc.
- **SDV** → treat `data/accounts.csv` + `data/usage_weekly.csv` as the seed;
  fit `sdv` `GaussianCopulaSynthesizer` (tabular) or `PARSynthesizer`
  (time-series) to emit larger, statistically-matched populations. Keep the
  archetype labels as a conditioning column.
- **Kaggle seed (TechFlow)** → map its `Daily_Usage_Mins`, `Account_Age_Days`,
  `Last_Support_Ticket`, and `Churn` fields onto `usage_weekly`, `accounts`,
  `support_tickets.body`, and `renewal_outcomes.outcome` respectively, then
  expand with SDV.
- **Live external signals** → replace `external_events.csv` with runtime calls:
  GNews or Firecrawl for company news, Alpha Vantage (via its MCP server) for
  market data. Point them at `account_name` (or a mapped ticker) and cache
  responses in the same `external_events` shape.

---

## 8. Files & modules

```
meridian-account-health/
├── config.py                 # world constants, archetypes, products, causal weights, name banks
├── text_banks.py             # tone/health-conditioned phrase banks for tickets & notes
├── generators.py             # accounts, usage, events, tickets, notes, features, outcomes
├── build_dataset.py          # orchestrator: writes core artifacts, validation, sanity plot
├── build_knowledge_base.py   # authors the 32-doc knowledge base (md + jsonl)
├── build_guardrail_eval.py   # builds the guardrail/safety eval set from the data
├── README.md
├── DATA_DICTIONARY.md
├── data/                     # 7 CSVs (structured + time-series + text + labels)
├── knowledge_base/           # 32 domain knowledge markdown docs
├── rag_corpus/               # account corpus + knowledge_base + combined (JSONL)
└── eval/                     # golden QA, ground-truth drivers, guardrail eval, validation, plot
```

To regenerate everything: `python3 build_dataset.py && python3 build_knowledge_base.py && python3 build_guardrail_eval.py`

## 9. Known properties & caveats

- Class balance is enforced by quantile assignment on the (noised) health index,
  so proportions are stable across seeds; the noise term keeps classes non-trivially
  separable (a strong model should land well above baseline but not at 100%).
- Extreme accounts saturate `churn_probability` near 0 or 1 (as real risk scores do);
  the informative spread is in the middle of the distribution.
- Renewal dates span roughly 2025-11 → 2026-12; features are computed only from
  data available up to each account's `forecast_as_of_date` (renewal − 90 days),
  capped at the dataset's `AS_OF_DATE` (2026-06-28). Respect this cutoff to avoid
  target leakage.
- `external_events.csv` is a synthetic stand-in; in production it becomes a live
  tool call, not a static table.
