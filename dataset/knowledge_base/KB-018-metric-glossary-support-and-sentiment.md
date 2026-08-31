# Metric Glossary: Support and Sentiment

Definitions for support and sentiment signals from `support_tickets` and the derived features.

- **category** — ticket type. `Escalation` and `Performance / Outage` are negative signals; `Feature Request` and `How-to / Usage` from a healthy account are neutral-to-positive (an engaged team).
- **priority** — P1 (critical) to P4 (low). P1 escalations demand same-day senior engagement.
- **sentiment** — per-ticket tone on a -1 to +1 scale, inferred from the ticket text.
- **csat** — 1-5 satisfaction on closed tickets; blank if unresolved.
- **resolution_hours** — time to resolve; long times on high-priority tickets erode trust.
- **support_escalation_rate** — escalations per active week over the last ~26 weeks; a key negative health driver.
- **avg_sentiment** — mean recent ticket sentiment; a key positive/negative driver.
- **avg_csat** — mean recent CSAT on closed tickets.

Interpretation: a *rising escalation rate with falling sentiment* is a stronger risk signal than raw ticket volume, which can simply reflect an engaged, active team.
