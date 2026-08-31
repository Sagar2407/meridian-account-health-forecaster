"""
build_knowledge_base.py
=======================
Authors the Meridian general-knowledge corpus (playbooks, health-scoring
methodology, metric glossaries, product one-pagers, segment/industry guides, and
policy docs) and writes:

  * knowledge_base/<slug>.md            (human-readable, repo-quality)
  * rag_corpus/knowledge_base.jsonl     (RAG-ready)
  * rag_corpus/corpus_with_kb.jsonl     (account records + knowledge base, combined)

These documents are DELIBERATELY distinct from the per-account notes/tickets:
they encode reusable domain knowledge a health/renewal agent should retrieve.
They use the same metric names, health bands, products, segments, and event
types as the rest of the dataset so retrieval genuinely connects general
guidance to specific accounts. All content is invented.

Run from repo root:  python3 build_knowledge_base.py
"""

import json, os, re

os.makedirs("knowledge_base", exist_ok=True)
os.makedirs("rag_corpus", exist_ok=True)


def slug(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:60]


# Each doc: (subtype, title, tags, body)
KB = [
    # ================================ PLAYBOOKS ================================
    ("playbook", "Save Play: Rescuing an At-Risk Account",
     ["save-play", "at_risk", "churn", "retention"],
     """Use this play when an account enters the **at_risk** or **slipping** band, especially after a sharp drop in `adoption_score` or a spike in `support_escalation_rate`.

**Trigger signals.** A negative `adoption_trend_13w`, `avg_sentiment` below about -0.2, two or more escalations in a quarter, a `sponsor_status` of `lost`, or an adverse external event (layoffs, leadership change, acquisition) in the last two quarters.

**The play, week by week.**
1. Diagnose within 48 hours. Pull the usage trajectory, the last three QBRs, open escalations, and any external events. Separate a product problem from a relationship problem from an external-disruption problem — the response differs.
2. Secure an internal executive sponsor on our side and assemble a cross-functional pod (CSM, support lead, solutions engineer).
3. Get an executive-to-executive meeting on the customer side within two weeks. If the champion is gone, multi-thread to find a new one.
4. Agree a written get-well plan with concrete, dated milestones tied to business outcomes, not feature usage.
5. Track leading indicators weekly (weekly active users, feature depth, escalation closure) and reassess renewal posture at 30 days.

**What good looks like.** Usage stabilizes, escalations close, and a renewed sponsor is willing to commit. A recovering account often shows the classic V-shape: a dip, an intervention, then a climb back. If leading indicators do not move in 30 days, escalate the commercial posture and prepare a right-sized fallback offer to protect the renewal."""),

    ("playbook", "Onboarding Playbook: The First 90 Days",
     ["onboarding", "adoption", "time-to-value", "kickoff"],
     """The first 90 days set the trajectory for the entire relationship. Accounts that stall in onboarding (the **stalled** band) rarely recover their `adoption_score` before renewal, so treat early ramp as the single highest-leverage moment.

**Days 0-14.** Run a kickoff with the executive sponsor present. Align on two or three measurable success criteria expressed in the customer's language (e.g., "cut campaign build time," not "use Campaign"). Name an internal owner on the customer side and confirm the admin team has bandwidth.

**Days 15-45.** Enablement and first production use. Get the primary product into real daily use; a single live use case beats broad shallow exploration. Watch for the two most common blockers: a lean admin team with competing priorities, and an unclear first use case.

**Days 46-90.** Drive depth. Introduce one advanced capability relevant to the success criteria. Establish the QBR cadence. By day 90 the account should show a rising `adoption_trend_13w` and `onboarding_completed = true`.

**Red flags.** Flat or near-zero usage past week six, no named owner, or repeated rescheduling of enablement. If two of these appear, escalate to the Onboarding-Stall Recovery play before the pattern hardens."""),

    ("playbook", "Renewal Playbook: Securing the Renewal",
     ["renewal", "commercial", "forecast", "outcome"],
     """Renewal work starts at the `forecast_as_of_date`, roughly 90 days before `renewal_date` — not the month before. By then you should already know which of the four outcomes you are steering toward: **Renewed, Expanded, Contracted, or Churned.**

**90 days out.** Assess health honestly. Lead with value realized on the primary product, quantified against the original success criteria. Identify the decision-maker and confirm budget authority.

**60 days out.** Address risks head-on. For a **slipping** account, offer a right-sized package to keep them in the fold rather than defending an untenable price. For a **thriving** account, build the expansion case (see the Expansion play).

**30 days out.** Get commercial alignment internally, send the quote, and pressure-test objections. Time-to-renewal matters: less runway on a shaky account raises risk.

**Posture by band.** Thriving → propose a multi-year uplift with an expansion module. Steady → hold price while nudging deeper adoption. Slipping → right-size to retain. At-risk → protect the renewal even if it means a short-term concession. Stalled → consider a reset offer tied to a fresh implementation plan. Recovering → convert the recovery into a firm multi-year commitment."""),

    ("playbook", "Expansion Playbook: Finding and Landing Upsell",
     ["expansion", "upsell", "cross-sell", "growth"],
     """Expansion candidates are accounts in the **thriving** band with a rising `adoption_trend_13w`, deep advanced-feature adoption, and an engaged, well-connected champion. `num_products` below the segment norm is an opening for cross-sell; high seat utilization is an opening for seat expansion.

**Qualify.** Look for three things: strong current value (they can articulate ROI), a business initiative you can attach to (often visible in favorable external events like a funding round or new-market launch), and an executive sponsor who will advocate internally.

**Motion.**
1. Anchor on outcomes already delivered, then map an adjacent use case to a product they don't yet own.
2. Run a value-realization review to quantify impact and build the business case.
3. Introduce the sponsor to our product leadership to signal partnership and de-risk the bet.
4. Time the proposal to the renewal for a multi-year uplift, or land a mid-term add-on if momentum is strong.

**Common expansions.** Adding Analytics or Personalization to a Content Management footprint; extending Campaign to a new business unit; upgrading to a higher tier. Do not push expansion on an account whose usage is merely steady — deepen adoption first."""),

    ("playbook", "Escalation Handling Playbook",
     ["escalation", "support", "P1", "trust"],
     """A single mishandled escalation can undo a year of goodwill; a well-handled one can strengthen the relationship. Escalations show up in the data as `category = Escalation` tickets, elevated `support_escalation_rate`, and negative `avg_sentiment`.

**Immediate response (first hours).** Acknowledge, assign an owner, and set expectations on cadence. For a P1 blocking a launch, engage a senior engineer the same day. Do not let the customer chase you for updates — proactive communication is the single biggest driver of recovered trust.

**Stabilize.** Provide a workaround if a fix will take time. Keep the CSM in the loop so the relationship layer and the technical layer stay aligned.

**Close the loop.** After resolution, hold a brief retrospective with the customer. Confirm `csat` recovered and document the root cause. Repeated escalations of the same type signal a systemic product or enablement gap — route that to the account plan, not just the ticket queue.

**When to escalate internally.** Any executive escalation, any P1 affecting a Strategic account, or a second escalation within 45 days. These often coincide with a usage cliff and should trigger an at-risk review."""),

    ("playbook", "QBR Playbook: Running an Effective Business Review",
     ["qbr", "business-review", "cadence", "stakeholder"],
     """The Quarterly Business Review is where you convert usage into perceived value and surface risk early. Every healthy account should have a QBR roughly every 13 weeks; a lapsed QBR cadence is itself a risk signal.

**Structure a QBR around five sections** (the same structure used in account notes): an executive summary of health; an adoption review (trend, level, and depth of advanced features); a stakeholder and relationship update; a support-experience summary; and external context that may affect the account. Close with dated action items and an explicit renewal outlook.

**Make it outcome-led.** Open with progress against the customer's original success criteria, not a feature-usage dump. Bring one insight they don't already have — a benchmark, an unused capability tied to their goal, or a risk you've spotted.

**Read the room.** A sponsor who is disengaged or newly arrived, or a practitioner team that has gone quiet, matters more than any single metric. Record stakeholder changes; a `sponsor_status` shift to `new` or `lost` should change your plan immediately.

**Output.** A crisp health call (band + trajectory), a short action list, and a renewal posture you'd be comfortable defending to leadership."""),

    ("playbook", "Adoption Playbook: Driving Depth of Usage",
     ["adoption", "feature-depth", "engagement", "value"],
     """Logins are not adoption. The metric that predicts renewal is *depth* — captured by `advanced_feature_adoption_pct` and sustained `feature_events`, not raw active-user counts. Many **steady** accounts plateau with shallow usage and are quietly at risk.

**Diagnose the plateau.** Compare the account's advanced-feature adoption to peers in the same segment and product. Shallow usage usually traces to one of three causes: the team never learned the advanced capabilities, the initial use case was too narrow, or an internal owner left.

**Drive depth.**
1. Pick one advanced capability tied to a business goal (e.g., Personalization's audience segmentation, Analytics' attribution modeling, Content Management's workflow automation).
2. Run a focused enablement session with the practitioner team, not just admins.
3. Set a 30-day usage target and review it.
4. Capture the win in the next QBR to build momentum.

**Why it matters.** Depth compounds: accounts using advanced features are stickier, churn less, and expand more. A rising `adoption_trend_13w` driven by advanced-feature usage is the strongest single positive signal in the health model."""),

    ("playbook", "Sponsor-Change Playbook: When Your Champion Leaves",
     ["sponsor", "champion", "relationship", "multi-thread"],
     """A `sponsor_status` of `lost` is one of the most reliable churn precursors in the data, because relationship equity does not transfer automatically. A change to `new` is a risk-and-opportunity moment.

**When the champion leaves (`lost`).** Treat it as urgent. The prior sponsor's belief in the product left with them, and decisions will stall. Multi-thread immediately: identify everyone who touches the product and map their influence. Find a rising practitioner or an executive whose goals your product serves, and rebuild from there.

**When a new sponsor arrives (`new`).** Assume you are starting from a lower base of credibility than before. Book an introductory value review early. Do not lead with history they don't share; lead with the outcomes you can deliver for *their* agenda.

**Prevention.** Never rely on a single point of contact, even in a **thriving** account. The healthiest structure is a champion who is well-connected to an engaged practitioner team. Record every stakeholder change in the account notes — the health model treats sponsor change as a material negative driver for good reason."""),

    ("playbook", "At-Risk Triage: Early-Warning Signs and Response",
     ["at_risk", "early-warning", "triage", "signals"],
     """Triage is about catching decline before it becomes a cliff. The earliest reliable signals, in rough order of importance: a sustained negative `adoption_trend_13w`; a falling `adoption_level_last_q` concentrated in previously strong teams; rising `support_escalation_rate` with negative `avg_sentiment`; a `sponsor_status` change to `new` or `lost`; and adverse external events.

**Triage tiers.**
- *Watch* (slipping): trend turning down but level still adequate. Action: a candid check-in with the sponsor and a usage diagnostic.
- *At-risk*: a clear drop, elevated escalations, or a lost sponsor. Action: open a Save Play.
- *Critical*: usage cliff plus a shaken relationship plus renewal inside 90 days. Action: executive engagement now and a get-well plan.

**Distinguish signal from seasonality.** A dip that matches the industry's seasonal pattern (see the Industry Seasonality Guide) is not decline. Always read the trend against the account's industry profile before raising an alarm.

**Escalate to a human reviewer** whenever a high-ACV or Strategic account is at-risk, or when signals conflict (e.g., strong usage but a lost sponsor). Those are exactly the cases an automated forecast should not resolve alone."""),

    ("playbook", "Executive Engagement Playbook",
     ["executive", "sponsor", "strategic", "relationship"],
     """Executive relationships are what carry an account through disruption. Accounts with an engaged, senior sponsor survive adverse external events far better than those without.

**Establish.** In onboarding, get the executive sponsor to state the vision and the success criteria themselves — ownership they articulate is ownership they defend. Introduce our executives early for thriving accounts.

**Sustain.** Bring executives a point of view, not a status update: industry benchmarks, a strategic risk, or an expansion thesis tied to their business. Reserve executive time for moments that matter — QBRs with a decision, save plays, and renewals with an uplift.

**Deploy in a crisis.** When an account goes at-risk, an executive-to-executive meeting within two weeks is often the difference between a save and a churn. It signals seriousness and unlocks decisions the working team cannot make.

**Read executive signals.** A sponsor who stops taking QBRs, delegates downward, or goes silent is a leading indicator that outranks most usage metrics. Record it and act."""),

    ("playbook", "Onboarding-Stall Recovery Playbook",
     ["onboarding", "stalled", "reset", "recovery"],
     """Use this play for accounts in the **stalled** band — usage stuck near zero, `onboarding_completed = false`, often months after the contract start. Left alone, these accounts churn for "never operationalized" reasons.

**Reset, don't nudge.** A stalled deployment rarely un-stalls on its own. Run a formal reset: revisit the original success criteria, confirm they still hold, and rescope to a single achievable first use case.

**Fix the ownership gap.** Stalls almost always have a missing or overloaded internal owner. Identify a new owner with the authority and bandwidth to drive the rollout; without one, nothing else works.

**Consider services.** For a Strategic or Enterprise account, a short services engagement to stand up the first production use case is usually worth it — it converts a likely churn into a possible renewal.

**Set a hard checkpoint.** Agree a 30-day milestone for first production value. If it is not met, be honest in the renewal forecast: a stalled account without a reset is a poor renewal bet, and a right-sized reset offer may be the only path to retention."""),

    # ============================== METHODOLOGY ===============================
    ("methodology", "Account Health Scoring Methodology",
     ["health-score", "methodology", "drivers", "index"],
     """Account health is summarized by a **health index** and a derived **churn probability**. The index is a weighted combination of *observable* signals; higher means healthier. It is designed so that a forecast can be justified by the same features a human would cite.

**Driver families and direction.**
- *Adoption* (strong positive): `adoption_trend_13w` (the single largest weight) and `adoption_level_last_q`. Trajectory matters more than absolute level.
- *Depth* (positive): `advanced_feature_depth`.
- *Breadth* (positive): `product_breadth` — more products means more stickiness.
- *Support* (negative): `support_escalation_rate`; *sentiment/CSAT* (positive): `avg_sentiment`, `avg_csat`.
- *External* (negative): `adverse_events_2q`.
- *Relationship* (negative): `sponsor_change` / sponsor lost.
- *Onboarding* (negative): `onboarding_incomplete`.
- *Runway* (slight positive): more `days_to_renewal`.

**How to read it.** No single feature decides an outcome; the index balances them, and an irreducible noise term means outcomes are probabilistic, not deterministic. Two accounts with similar indices can differ in outcome — which is why calibrated probability and human review on borderline cases matter.

**Do not use the latent labels.** `health_archetype` and `health_band` are generative ground truth for analysis and are NOT valid model inputs. A forecast must be built from the observable feature columns and the retrieved evidence, or it is leaking the answer."""),

    ("methodology", "Health Bands Reference",
     ["health-band", "thriving", "at_risk", "reference"],
     """Health bands are a coarse, human-readable summary of an account's state. Each maps to a default posture. Bands are descriptive; always pair a band with the trajectory (improving vs worsening).

- **thriving** — high, rising adoption; deep feature use; engaged sponsor; light, enhancement-oriented support. Posture: expand; reference-candidate.
- **steady** — consistent, healthy usage but often shallow depth; supportive but less hands-on sponsor. Posture: drive depth; protect; find an expansion angle.
- **slipping** — adoption drifting down over one or two quarters; cooling engagement; renewal not guaranteed. Posture: candid check-in; usage diagnostic; watch closely.
- **at_risk** — sharp usage drop and/or strained relationship; elevated escalations. Posture: open a Save Play; executive engagement.
- **stalled** — never operationalized; usage near zero; onboarding incomplete. Posture: reset the implementation; fix ownership.
- **recovering** — dipped, then climbing back after an intervention. Posture: sustain the save cadence; convert to a firm renewal.

**Boundary cases** (e.g., steady-but-shallow, or recovering-but-fragile) are where forecasts are least certain and human review is most valuable."""),

    ("methodology", "Reading the Adoption Trend",
     ["adoption-trend", "trajectory", "seasonality", "interpretation"],
     """`adoption_trend_13w` is the slope of an account's weekly `adoption_score` over roughly the last quarter, ending at the `forecast_as_of_date`. It is the most predictive single feature, but it is easy to misread.

**Slope vs level.** A high but flat trajectory is healthy; a high but falling one is a warning even if the current level looks fine. Conversely, a low but rising trajectory (a recovering account) can be a good renewal bet. Always read slope and level together.

**Control for seasonality.** Some industries have strong seasonal swings — retail peaks in Q4, education dips over summer, travel peaks mid-year. A seasonal dip is not decline. Compare the trend to the account's industry seasonal profile before drawing a conclusion; the healthiest seasonal accounts show amplified swings around a stable baseline.

**Watch for cliffs.** A sudden week-over-week collapse (rather than a gentle slope) usually has an external cause — a reorg, an acquisition, or a lost champion. Cliffs often coincide with an adverse external event in the prior month; check `external_events` when you see one.

**Depth check.** A trend driven by advanced-feature usage is more durable than one driven by basic logins. Cross-reference `advanced_feature_adoption_pct`."""),

    ("methodology", "Renewal Outcome Definitions",
     ["outcome", "churn", "expansion", "definitions"],
     """The forecast target is one of four mutually exclusive outcomes recorded at `renewal_date`:

- **Renewed** — the account renews at roughly the same value. The baseline healthy outcome.
- **Expanded** — the account renews with an uplift: added seats, an added product, a tier upgrade, or a multi-year commitment. Driven by strong, deep, rising usage and an engaged sponsor.
- **Contracted** — the account renews but at reduced value: fewer seats or a dropped module. Usually a "keep them in the fold" outcome under budget pressure or partial disengagement.
- **Churned** — the account does not renew. Driven by some combination of declining adoption, lost sponsor, budget cuts, competitive switch, or a failed onboarding.

**Probability vs label.** `churn_probability` expresses confidence on a 0-1 scale; the label is the realized outcome. For borderline accounts the probability is the honest answer — a hard label overstates certainty.

**Reasons.** Each non-renewal carries an `outcome_reason` (e.g., "Executive sponsor departed," "Consolidating onto another platform"). A good forecast predicts not just the outcome but the reason, and grounds it in retrieved evidence."""),

    ("methodology", "External Signals Interpretation Guide",
     ["external", "news", "market", "events", "signals"],
     """External events are company-level news and market signals with a `polarity`: headwind (-1), tailwind (+1), or neutral (0). In production these come from live news and market feeds; here they are provided in `external_events`. They rarely decide an outcome alone but they shift risk and explain cliffs.

**Headwinds** (raise churn risk): leadership change (especially CxO), layoffs or restructuring, earnings miss, being acquired, cost-cutting initiatives, and regulatory issues. These tend to freeze discretionary spend and disrupt sponsors — assume tighter scrutiny at renewal.

**Tailwinds** (support renewal/expansion): earnings beats, funding rounds, acquiring a competitor, new-market launches, and hiring a digital/CX executive. Treat these as openings to attach an expansion thesis to the customer's growth agenda.

**How to weigh them.** A tailwind does not save an account whose usage has collapsed, and a healthy account can absorb one headwind. Look for *coincidence*: an adverse event shortly before a usage cliff is a strong causal story; scattered neutral events are noise.

**In a forecast.** Cite the specific event, not just its existence, and connect it to the mechanism (e.g., "layoffs preceded the drop in weekly active users, consistent with a reduced team")."""),

    # ================================ GLOSSARY ================================
    ("glossary", "Metric Glossary: Usage and Engagement",
     ["glossary", "usage", "metrics", "engagement"],
     """Definitions for the usage metrics in `usage_weekly` and the derived engagement features.

- **active_users** — weekly active users on a product; capped at `licensed_seats`. Breadth of use.
- **sessions** — distinct usage sessions in the week.
- **feature_events** — count of meaningful feature actions; the primary measure of *depth* of use, not just presence.
- **api_calls** — programmatic usage; high values indicate integration into the customer's workflow (stickier).
- **storage_gb** — data stored; grows with genuine production use, especially for Digital Asset Management.
- **advanced_feature_adoption_pct** — share of usage in advanced capabilities (0-100). The clearest depth signal.
- **adoption_score** — 0-100 composite of weekly engagement across an account's products; the series underlying trend and level.
- **adoption_level_last_q** — mean adoption score over the last ~13 weeks.
- **adoption_trend_13w** — slope of adoption score over the last ~13 weeks; the top predictive feature.

Rule of thumb: depth (feature_events, advanced adoption) predicts retention better than breadth (active_users) alone."""),

    ("glossary", "Metric Glossary: Support and Sentiment",
     ["glossary", "support", "sentiment", "csat"],
     """Definitions for support and sentiment signals from `support_tickets` and the derived features.

- **category** — ticket type. `Escalation` and `Performance / Outage` are negative signals; `Feature Request` and `How-to / Usage` from a healthy account are neutral-to-positive (an engaged team).
- **priority** — P1 (critical) to P4 (low). P1 escalations demand same-day senior engagement.
- **sentiment** — per-ticket tone on a -1 to +1 scale, inferred from the ticket text.
- **csat** — 1-5 satisfaction on closed tickets; blank if unresolved.
- **resolution_hours** — time to resolve; long times on high-priority tickets erode trust.
- **support_escalation_rate** — escalations per active week over the last ~26 weeks; a key negative health driver.
- **avg_sentiment** — mean recent ticket sentiment; a key positive/negative driver.
- **avg_csat** — mean recent CSAT on closed tickets.

Interpretation: a *rising escalation rate with falling sentiment* is a stronger risk signal than raw ticket volume, which can simply reflect an engaged, active team."""),

    ("glossary", "Metric Glossary: Commercial and Account",
     ["glossary", "commercial", "account", "acv", "segment"],
     """Definitions for account and commercial fields in `accounts` and `renewal_outcomes`.

- **segment** — `Strategic`, `Enterprise`, or `Mid-Market`; drives ACV, seat, and product-count norms and the level of white-glove attention.
- **acv_usd** — annual contract value. High ACV raises the stakes and the bar for human review on risk.
- **licensed_seats** — seats licensed across products; utilization vs this cap is an expansion signal.
- **contract_term_months** — 12/24/36; longer terms correlate with commitment.
- **contract_start_date** — initial start; drives tenure and onboarding timing.
- **renewal_date** — the upcoming renewal decision date.
- **forecast_as_of_date** — `renewal_date` minus 90 days; the cutoff for feature computation (respect it to avoid leakage).
- **num_products / product_breadth** — count of owned modules; more breadth is stickier.
- **sponsor_status** — `strong` / `stable` / `new` / `lost`; a core relationship signal.
- **health_index / churn_probability / outcome** — the latent score, its probability form, and the realized label."""),

    # ============================= PRODUCT ONE-PAGERS =========================
    ("product", "Product One-Pager: Content Management (CMS)",
     ["product", "cms", "content-management"],
     """**What it is.** Meridian's Content Management module (CMS) is the foundation for authoring, managing, and publishing digital content across web and app channels. It is the most commonly owned module and often the primary product.

**Core capabilities.** Structured authoring, multi-channel publishing, and editorial workflow.

**Advanced features (depth signals).** Headless delivery, workflow automation, multi-site management, content reuse/fragments, and a localization pipeline. Adoption of these correlates strongly with retention.

**Adoption milestones.** First content published (onboarding), editorial workflow live (steady), headless or multi-site in production (thriving).

**Common blockers.** A lean editorial team, an unclear content model, or attempting broad rollout before a first use case lands. Shallow usage (basic publishing only) is a quiet plateau risk.

**Expansion adjacencies.** CMS footprints expand naturally into Digital Asset Management (to manage the media in content) and Analytics (to measure content performance)."""),

    ("product", "Product One-Pager: Digital Asset Management (DAM)",
     ["product", "dam", "digital-asset-management"],
     """**What it is.** The Digital Asset Management module (DAM) is the single source of truth for images, video, and brand assets, with governance and delivery at scale.

**Core capabilities.** Central asset library, metadata and search, and versioning.

**Advanced features (depth signals).** Smart AI tagging, dynamic media rendering, rights management, bulk metadata operations, and a brand portal.

**Adoption milestones.** Assets migrated (onboarding), search and metadata in daily use (steady), dynamic rendering or a brand portal live (thriving).

**Common blockers.** Incomplete asset migration, inconsistent metadata standards, and storage growth without governance. DAM shows the highest `storage_gb` of any module, so storage trends are a useful engagement proxy here.

**Expansion adjacencies.** DAM pairs with Content Management (assets feed content) and Commerce (product imagery)."""),

    ("product", "Product One-Pager: Analytics",
     ["product", "analytics", "measurement"],
     """**What it is.** The Analytics module measures digital experience performance across channels and turns behavioral data into decisions.

**Core capabilities.** Event tracking, dashboards, and standard reporting.

**Advanced features (depth signals).** Custom funnels, cohort analysis, attribution modeling, anomaly alerts, and data-warehouse export. High `api_calls` are typical for integrated Analytics deployments.

**Adoption milestones.** Tracking live and first dashboards (onboarding), custom funnels/cohorts in regular use (steady), attribution or warehouse export powering decisions (thriving).

**Common blockers.** Tracking gaps, dashboards that no one owns, and data trust issues. Analytics that is set up but not consulted is a classic shallow-adoption plateau.

**Expansion adjacencies.** Analytics is the natural gateway to Personalization (act on the segments Analytics reveals) and strengthens the value story for every other module."""),

    ("product", "Product One-Pager: Personalization",
     ["product", "personalization", "experimentation"],
     """**What it is.** The Personalization module tailors experiences to audiences in real time and runs experimentation programs.

**Core capabilities.** Audience targeting, content variation, and experiment management.

**Advanced features (depth signals).** A/B/n testing, audience segmentation, real-time decisioning, ML recommendations, and journey orchestration. Personalization is a high-value, lower-attach module — owning it signals a mature account.

**Adoption milestones.** First test live (onboarding), a steady experimentation cadence (steady), ML recommendations or real-time decisioning in production (thriving).

**Common blockers.** Insufficient traffic for statistical significance, no experimentation culture, and dependence on Analytics data quality. It requires the most enablement of any module.

**Expansion adjacencies.** Personalization depends on Analytics upstream and amplifies Campaign and Commerce downstream."""),

    ("product", "Product One-Pager: Campaign",
     ["product", "campaign", "marketing-automation"],
     """**What it is.** The Campaign module orchestrates multi-channel marketing journeys — email and beyond — with automation and deliverability tooling.

**Core capabilities.** Campaign build, audience management, and scheduling.

**Advanced features (depth signals).** Multi-channel journeys, triggered sends, dynamic content blocks, send-time optimization, and deliverability tooling.

**Adoption milestones.** First campaign sent (onboarding), triggered/automated journeys live (steady), multi-channel orchestration at scale (thriving).

**Common blockers.** Deliverability issues, thin audience data, and manual one-off sends instead of automation. A team stuck on single batch sends is under-adopting.

**Expansion adjacencies.** Campaign draws on Personalization for targeting and Content Management/DAM for content and assets; it is a frequent add-on to a CMS footprint."""),

    ("product", "Product One-Pager: Commerce",
     ["product", "commerce", "e-commerce"],
     """**What it is.** The Commerce module powers digital storefronts and transactions, from catalog to checkout.

**Core capabilities.** Catalog management, cart and checkout, and order handling.

**Advanced features (depth signals).** Headless storefront, promotion engine, inventory sync, subscription billing, and marketplace connectors. Commerce shows the highest `api_calls` of any module.

**Adoption milestones.** Storefront live (onboarding), promotions and inventory sync in use (steady), headless or subscription/marketplace in production (thriving).

**Common blockers.** Integration complexity (ERP, payments), catalog data quality, and seasonal load. Commerce accounts are the most seasonality-sensitive — read their trends against the retail/consumer calendar.

**Expansion adjacencies.** Commerce pairs with DAM (product media), Personalization (merchandising), and Analytics (conversion measurement)."""),

    # ============================ SEGMENT / INDUSTRY ==========================
    ("segment_guide", "Segment Playbook: Strategic Accounts",
     ["segment", "strategic", "enterprise", "white-glove"],
     """Strategic accounts are the largest and highest-ACV relationships (often multi-year, multi-product). They warrant white-glove, executive-led engagement and the lowest tolerance for unmanaged risk.

**Engagement model.** Named team, executive sponsor on both sides, frequent QBRs with decisions, and a joint success plan. Multi-threading is mandatory — never single-threaded, even when thriving.

**Risk posture.** Any at-risk Strategic account should trigger immediate executive engagement and human review of the forecast; the downside is too large to leave to an automated call. Protect these renewals aggressively, including short-term concessions when needed.

**Expansion.** Strategic accounts carry the most expansion potential — additional products, new business units, and multi-year uplifts. Attach expansion theses to their strategic initiatives (often visible in favorable external events).

**Data note.** Strategic accounts tend toward higher `product_breadth`, longer terms, and higher renew/expand rates — but when they churn, the ACV impact is outsized, which is why they dominate human-review criteria."""),

    ("segment_guide", "Segment Playbook: Enterprise and Mid-Market",
     ["segment", "enterprise", "mid-market", "scale"],
     """Enterprise and Mid-Market accounts are managed at greater scale, so playbooks and automation matter more and per-account executive time is scarcer.

**Enterprise.** Meaningful ACV and 2-4 products typical. A named CSM, quarterly QBRs, and selective executive engagement for renewals and saves. Drive depth and cross-sell; watch for single-threaded relationships, which are common and risky.

**Mid-Market.** Smaller ACV, often 1-3 products and shorter (frequently 12-month) terms. Efficient, largely digital-led engagement with QBRs focused on adoption and value. Onboarding quality is decisive here — with leaner customer teams, stalls are common and time-to-value is everything.

**Where to spend attention.** Use the health model to triage: concentrate human effort on slipping/at-risk accounts and high-potential expansion candidates, and let steady accounts run on a lighter-touch cadence. Mid-Market shows a wider spread of outcomes (more churn *and* more expansion) than Strategic, so segmentation of effort pays off most here."""),

    ("segment_guide", "Industry Seasonality Guide",
     ["industry", "seasonality", "interpretation", "trend"],
     """Usage naturally rises and falls with each industry's calendar. Reading a trend without controlling for seasonality produces false alarms (a seasonal dip mistaken for decline) and missed risks (real decline masked by a seasonal peak).

**Typical patterns.**
- *Retail & E-commerce* and *Consumer Goods*: strong Q4 peak, January trough. Judge health on year-over-year and de-seasonalized trend, not raw Q4→Q1 change.
- *Travel & Hospitality*: mid-year (summer) peak.
- *Public Sector & Education*: summer trough (July-August), autumn ramp.
- *Manufacturing*: mid-summer dip.
- *Financial Services*: quarter-end and year-end bumps.
- *Media & Entertainment* and *Technology*: milder, event-driven variation.

**How to apply it.** Before flagging a `slipping` trend, ask whether the movement matches the account's industry profile. A healthy seasonal account shows amplified swings around a stable baseline; a declining one shows a downward baseline regardless of season. Commerce-heavy accounts are the most seasonal — always de-seasonalize before forecasting them."""),

    # =============================== POLICY / PROCESS =========================
    ("policy", "Renewal Process and Timeline",
     ["policy", "renewal", "process", "timeline"],
     """The renewal motion runs on a 90-day clock anchored to `forecast_as_of_date` (renewal minus 90 days).

**T-90:** Health assessment and forecast. Classify the likely outcome and record the rationale. Confirm decision-maker and budget authority. High-risk or high-ACV accounts enter human review here.
**T-60:** Value review with the customer; surface and address risks; for healthy accounts, develop the expansion case.
**T-30:** Commercial alignment internally; issue the quote; handle objections.
**T-14:** Confirm paperwork and close. Escalate any slippage.
**T-0 (renewal_date):** Outcome realized and recorded (Renewed/Expanded/Contracted/Churned) with a reason.

**Guardrail.** Never compute or present a forecast using data after the `forecast_as_of_date` — doing so leaks the future into the prediction. Features in `account_features` already respect this cutoff.

**Escalation.** If an account is unhealthy at T-90 or slips at any checkpoint, trigger the appropriate play (Save Play, At-Risk Triage) and, for Strategic/high-ACV accounts, human executive engagement."""),

    ("policy", "Commercial and Discount Guidance",
     ["policy", "commercial", "discount", "pricing"],
     """Commercial posture should follow account health, not habit. This guidance frames how to think about price and terms at renewal; final commercial decisions require the account owner and, above thresholds, management approval.

**By health band.** Thriving/expanding: hold price and pursue an uplift or multi-year term. Steady: hold price; trade minor concessions only for a longer term or a reference. Slipping: consider a right-sized package (fewer seats or modules) to retain the relationship rather than lose it. At-risk: protect the renewal, and a short-term concession can be justified to buy time for a recovery. Stalled: a reset offer tied to a fresh implementation plan may be the only viable path.

**Principles.** Discounts should be exchanged for something (term length, expansion, advocacy), not given to plug a value gap that adoption work should fix. Contraction is preferable to churn when budget pressure is genuine. Multi-year uplifts are the highest-quality outcome and should be the default ask for healthy accounts.

**The agent's role.** A forecasting agent may *recommend* a posture and quantify risk, but it must not autonomously commit commercial terms — that requires a human."""),

    ("policy", "Escalation SLA and Support Tiers",
     ["policy", "sla", "support", "escalation"],
     """Support priority levels and their response expectations (the basis for `priority` and `resolution_hours`).

- **P1 (Critical):** production down or a launch blocked. Same-day senior engagement; frequent proactive updates. P1s on Strategic accounts auto-escalate internally.
- **P2 (High):** major feature impaired, workaround possible. Rapid response, hours-to-a-day resolution target.
- **P3 (Medium):** limited impact, routine defects and how-to. Resolution within a few days.
- **P4 (Low):** minor issues and feature requests. Handled in normal queue.

**Escalation triggers.** Any executive escalation; any P1 on a Strategic account; a second escalation on the same account within 45 days; or negative sentiment persisting after resolution. These frequently coincide with a usage cliff and should trigger an at-risk review, not just a ticket response.

**Trust recovery.** Proactive communication cadence is the biggest driver of recovered `csat`. After any escalation, confirm sentiment has recovered and log the root cause for the account plan."""),

    ("policy", "Data Handling, Privacy, and Agent Scope Policy",
     ["policy", "privacy", "safety", "agent-scope", "guardrails"],
     """This policy defines what the account-health agent may do with data and where it must stop. It is the reference for the agent's guardrails.

**In scope.** Reasoning over the provided account data — attributes, usage, tickets, notes, external events, features — to assess health, forecast the renewal outcome with a calibrated probability, explain the drivers with cited evidence, and recommend plays.

**Out of scope — decline or defer.** The agent must NOT: invent data it was not given (e.g., NPS, headcount by department, credit ratings, competitor spend, or personal contact details are not in this dataset); assess accounts that do not exist; answer questions unrelated to account health; commit commercial terms; or make employment/HR judgments about named people (CSMs, sponsors).

**Grounding and honesty.** Every factual claim about an account must be supported by retrieved evidence. When evidence is absent, the correct answer is to say so, not to guess. Do not present the latent `health_archetype`/`health_band` as the basis for a forecast — reason from observable features.

**Uncertainty and human handoff.** On borderline accounts (churn probability near the middle of the range), express uncertainty rather than asserting a hard label. Escalate to a human reviewer when: the account is Strategic or high-ACV and at-risk; signals conflict materially; history is too short to judge; or a request falls outside the scope above.

**Privacy.** Treat account and personal data as confidential. Do not expose personal identifiers beyond what a task legitimately requires, and never fabricate them."""),
]


def main():
    kb_records = []
    for i, (subtype, title, tags, body) in enumerate(KB, start=1):
        doc_id = f"KB-{i:03d}"
        text = f"# {title}\n\n{body}"
        # write markdown file
        with open(f"knowledge_base/{doc_id}-{slug(title)}.md", "w") as fh:
            fh.write(text + "\n")
        # jsonl record (schema-compatible with rag_corpus/corpus.jsonl)
        kb_records.append({
            "doc_id": doc_id,
            "account_id": None,
            "account_name": None,
            "doc_type": "knowledge_base",
            "subtype": subtype,
            "date": None,
            "segment": None,
            "industry": None,
            "primary_product": None,
            "tags": tags,
            "sentiment": None,
            "text": text,
        })

    with open("rag_corpus/knowledge_base.jsonl", "w") as fh:
        for r in kb_records:
            fh.write(json.dumps(r) + "\n")

    # combined corpus (account records + knowledge base) for a single index
    combined = []
    if os.path.exists("rag_corpus/corpus.jsonl"):
        with open("rag_corpus/corpus.jsonl") as fh:
            for line in fh:
                combined.append(json.loads(line))
    combined.extend(kb_records)
    with open("rag_corpus/corpus_with_kb.jsonl", "w") as fh:
        for r in combined:
            fh.write(json.dumps(r) + "\n")

    # summary
    from collections import Counter
    by_type = Counter(r["subtype"] for r in kb_records)
    print(f"Knowledge base documents written: {len(kb_records)}")
    for k, v in sorted(by_type.items()):
        print(f"  {k:14s} {v}")
    print(f"Combined corpus (account + KB) documents: {len(combined):,}")
    print("Wrote: knowledge_base/*.md, rag_corpus/knowledge_base.jsonl, rag_corpus/corpus_with_kb.jsonl")


if __name__ == "__main__":
    main()
