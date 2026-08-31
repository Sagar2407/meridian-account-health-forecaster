# Data Dictionary — Meridian Account-Health Dataset

> All data is synthetic. `account_name`, `csm_name`, and `exec_sponsor_name` are
> procedurally generated from generic word/name components; any resemblance to a
> real company or person is coincidental. Product/module names are generic
> category descriptors, not real products.

Conventions: dates are ISO-8601 strings (`YYYY-MM-DD`). Sentiment is a float in
`[-1, 1]`. ⚠️ marks **latent ground-truth fields that must NOT be used as model
features** (they encode the answer).

---

## `data/accounts.csv` — one row per account (dimension)

| Column | Type | Description |
|---|---|---|
| `account_id` | str | Primary key, e.g. `ACC-1042`. Joins to every other table. |
| `account_name` | str | Fictional company name. |
| `segment` | str | `Strategic` / `Enterprise` / `Mid-Market`. |
| `industry` | str | One of 10 industries (drives seasonality). |
| `region` | str | `NA` / `EMEA` / `APAC` / `LATAM`. |
| `country` | str | Country within region. |
| `employees` | int | Approximate headcount of the customer company. |
| `licensed_seats` | int | Seats licensed across Meridian products. |
| `acv_usd` | float | Annual contract value (USD). |
| `contract_term_months` | int | 12 / 24 / 36. |
| `contract_start_date` | date | Initial contract start (drives tenure & onboarding timing). |
| `renewal_date` | date | Upcoming renewal decision date. |
| `forecast_as_of_date` | date | `renewal_date − 90 days`. **Use only data on/before this date as features** (capped at `AS_OF_DATE = 2026-06-28`). |
| `products_owned` | str | Semicolon-separated module list (e.g. `Content Management;Analytics`). |
| `num_products` | int | Count of owned products (stickiness signal). |
| `primary_product` | str | The lead product for the account. |
| `csm_name` | str | Assigned customer success manager (fictional). |
| `exec_sponsor_name` | str | Executive sponsor / champion (fictional). |
| `sponsor_status` | str | `strong` / `stable` / `new` / `lost` (relationship signal). |
| `onboarding_completed` | bool | Whether onboarding was completed. |
| `advanced_adoption_target` | float | 0–1 latent propensity for advanced-feature depth (shapes usage). |
| `usage_cliff_date` | date/"" | For `sharp_drop` accounts, the week of the usage cliff; empty otherwise. |
| `health_archetype` | str | ⚠️ Latent archetype (7 classes). Ground truth only. |
| `health_band` | str | ⚠️ Coarse band derived from archetype (thriving/steady/slipping/at_risk/stalled/recovering). |

---

## `data/usage_weekly.csv` — weekly telemetry (fact)

Grain: one row per `account_id` × `product` × `week_start` (104 weeks).

| Column | Type | Description |
|---|---|---|
| `account_id` | str | FK → accounts. |
| `week_start` | date | Monday-anchored week start. |
| `product` | str | Product/module name. |
| `active_users` | int | Weekly active users (≤ licensed seats). |
| `sessions` | int | Sessions in the week. |
| `feature_events` | int | Count of feature actions (depth of use). |
| `api_calls` | int | API calls (programmatic usage). |
| `storage_gb` | float | Storage consumed (GB). |
| `advanced_feature_adoption_pct` | float | 0–100; share of usage in advanced features. |

Derived signal: mean weekly engagement across a account's products underlies the
`adoption_level_last_q` and `adoption_trend_13w` features.

---

## `data/support_tickets.csv` — support interactions (fact, with text)

| Column | Type | Description |
|---|---|---|
| `ticket_id` | str | Primary key, e.g. `TCK-100123`. |
| `account_id` | str | FK → accounts. |
| `created_date` | date | When the ticket was opened. |
| `channel` | str | `Support Portal` / `Email` / `In-app` / `CSM-logged`. |
| `category` | str | 8 categories incl. `Escalation`, `Bug / Defect`, `Feature Request`. |
| `priority` | str | `P1`–`P4`. |
| `status` | str | `Resolved` / `Closed` / `Open` / `Pending Customer`. |
| `product` | str | Product the ticket concerns. |
| `subject` | str | Short subject line. |
| `body` | str | Full ticket text (tone conditioned on account health). |
| `sentiment` | float | −1..1 sentiment of the ticket. |
| `csat` | int/NaN | 1–5 satisfaction for closed tickets; NaN if unresolved. |
| `resolution_hours` | float/NaN | Time to resolve; NaN if unresolved. |

---

## `data/csm_notes.csv` — CSM notes & QBRs (fact, with text) — RAG gold

| Column | Type | Description |
|---|---|---|
| `note_id` | str | Primary key, e.g. `NOTE-200456`. |
| `account_id` | str | FK → accounts. |
| `note_date` | date | Date of the note. |
| `note_type` | str | `Onboarding Kickoff` / `Monthly Touchpoint` / `Quarterly Business Review` / `Escalation / Save Play` / `Renewal Prep` / `Expansion Discussion`. |
| `author` | str | CSM (matches `accounts.csm_name`). |
| `sentiment` | float | −1..1 overall tone of the note. |
| `body` | str | Multi-section narrative (exec summary, adoption, stakeholder, support, external context, action items, renewal outlook). |

---

## `data/external_events.csv` — synthetic news/market signals

| Column | Type | Description |
|---|---|---|
| `account_id` | str | FK → accounts. |
| `event_date` | date | When the event occurred. |
| `event_type` | str | 13 types (leadership change, layoffs, earnings, acquisition, funding, …). |
| `polarity` | int | `+1` tailwind / `−1` headwind / `0` neutral. |
| `source` | str | Fictional source label. |
| `headline` | str | One-line synthetic headline. |

> In production this table is replaced by live GNews/Firecrawl + Alpha Vantage
> tool calls; keep the same columns to preserve compatibility.

---

## `data/account_features.csv` — engineered observable features (per account)

Computed strictly from data on/before each account's `forecast_as_of_date`.
**These are the intended model inputs.**

| Column | Type | Description |
|---|---|---|
| `account_id` | str | FK → accounts. |
| `adoption_trend_13w` | float | Slope of weekly adoption over the last ~quarter (strongest driver). |
| `adoption_level_last_q` | float | Mean adoption score (0–100) over the last ~quarter. |
| `advanced_feature_depth` | float | 0–100 depth of advanced-feature adoption. |
| `product_breadth` | int | Number of products owned. |
| `support_escalation_rate` | float | Escalations per active week (last 26 weeks). |
| `avg_sentiment` | float | Mean ticket sentiment (last 26 weeks). |
| `avg_csat` | float | Mean CSAT of closed tickets (last 26 weeks; 3.5 if none). |
| `adverse_events_2q` | int | Count of headwind external events (last 26 weeks). |
| `favorable_events_2q` | int | Count of tailwind external events (last 26 weeks). |
| `sponsor_change` | int | 1 if sponsor `new` or `lost`. |
| `sponsor_lost` | int | 1 if sponsor `lost`. |
| `onboarding_incomplete` | int | 1 if onboarding not completed. |
| `days_to_renewal` | int | Days from `forecast_as_of_date` to `renewal_date`. |

---

## `data/renewal_outcomes.csv` — the target

| Column | Type | Description |
|---|---|---|
| `account_id` | str | FK → accounts. |
| `health_index` | float | Latent weighted health score (higher = healthier), pre-noise. |
| `churn_probability` | float | 0–1; `sigmoid(−index_noised)`. Use for regression/ranking tasks. |
| `outcome` | str | **Label**: `Churned` / `Contracted` / `Renewed` / `Expanded`. |
| `outcome_reason` | str | Reason consistent with the outcome (empty for `Renewed`). |
| `outcome_date` | date | Equals `renewal_date`. |

---

## `rag_corpus/corpus.jsonl` (+ `notes.jsonl`, `tickets.jsonl`)

One JSON object per line, retrieval-ready:

| Field | Type | Description |
|---|---|---|
| `doc_id` | str | `NOTE-*` or `TCK-*`. |
| `account_id` | str | FK → accounts (use as a retrieval filter). |
| `account_name` | str | Company name. |
| `doc_type` | str | `csm_note` / `support_ticket`. |
| `subtype` | str | Note type or ticket category. |
| `date` | date | Document date. |
| `segment`, `industry`, `primary_product` | str | Account metadata for filtered retrieval. |
| `sentiment` | float | Document sentiment. |
| `text` | str | Header line + body (embed this). |

---

## `eval/ground_truth_drivers.json` — per-account truth (list of 260)

| Field | Type | Description |
|---|---|---|
| `account_id` | str | FK → accounts. |
| `health_index` / `health_index_noised` | float | Pre- and post-noise health scores. |
| `churn_probability` | float | Same as in `renewal_outcomes`. |
| `outcome` | str | Label. |
| `top_negative_drivers` | list | Up to 3 `{driver, contribution}` with the most negative contributions. |
| `top_positive_drivers` | list | Up to 3 most positive contributions. |

Use this to score whether the agent's stated reasoning matches the true drivers.

---

## `eval/golden_qa.jsonl` — golden evaluation questions (23 items)

| Field | Type | Description |
|---|---|---|
| `id` | str | Question id (e.g. `Q1_portfolio_risk`, `Qacc_ACC-1089`). |
| `question` | str | Natural-language prompt to pose to the agent. |
| `answer_type` | str | `ranked_list` / `list` / `table` / `assessment`. |
| `ground_truth` | obj/list | The correct answer derived from the data. |

Covers: portfolio risk ranking, usage-cliff/external-event coincidence, expansion
candidates, outcome distribution by segment and by industry, and per-account
health assessments across every health band.
