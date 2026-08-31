# Renewal Outcome Definitions

The forecast target is one of four mutually exclusive outcomes recorded at `renewal_date`:

- **Renewed** — the account renews at roughly the same value. The baseline healthy outcome.
- **Expanded** — the account renews with an uplift: added seats, an added product, a tier upgrade, or a multi-year commitment. Driven by strong, deep, rising usage and an engaged sponsor.
- **Contracted** — the account renews but at reduced value: fewer seats or a dropped module. Usually a "keep them in the fold" outcome under budget pressure or partial disengagement.
- **Churned** — the account does not renew. Driven by some combination of declining adoption, lost sponsor, budget cuts, competitive switch, or a failed onboarding.

**Probability vs label.** `churn_probability` expresses confidence on a 0-1 scale; the label is the realized outcome. For borderline accounts the probability is the honest answer — a hard label overstates certainty.

**Reasons.** Each non-renewal carries an `outcome_reason` (e.g., "Executive sponsor departed," "Consolidating onto another platform"). A good forecast predicts not just the outcome but the reason, and grounds it in retrieved evidence.
