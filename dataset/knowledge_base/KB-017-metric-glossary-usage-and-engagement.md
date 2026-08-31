# Metric Glossary: Usage and Engagement

Definitions for the usage metrics in `usage_weekly` and the derived engagement features.

- **active_users** — weekly active users on a product; capped at `licensed_seats`. Breadth of use.
- **sessions** — distinct usage sessions in the week.
- **feature_events** — count of meaningful feature actions; the primary measure of *depth* of use, not just presence.
- **api_calls** — programmatic usage; high values indicate integration into the customer's workflow (stickier).
- **storage_gb** — data stored; grows with genuine production use, especially for Digital Asset Management.
- **advanced_feature_adoption_pct** — share of usage in advanced capabilities (0-100). The clearest depth signal.
- **adoption_score** — 0-100 composite of weekly engagement across an account's products; the series underlying trend and level.
- **adoption_level_last_q** — mean adoption score over the last ~13 weeks.
- **adoption_trend_13w** — slope of adoption score over the last ~13 weeks; the top predictive feature.

Rule of thumb: depth (feature_events, advanced adoption) predicts retention better than breadth (active_users) alone.
