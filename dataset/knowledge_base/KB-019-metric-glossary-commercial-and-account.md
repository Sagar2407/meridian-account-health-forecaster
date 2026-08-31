# Metric Glossary: Commercial and Account

Definitions for account and commercial fields in `accounts` and `renewal_outcomes`.

- **segment** — `Strategic`, `Enterprise`, or `Mid-Market`; drives ACV, seat, and product-count norms and the level of white-glove attention.
- **acv_usd** — annual contract value. High ACV raises the stakes and the bar for human review on risk.
- **licensed_seats** — seats licensed across products; utilization vs this cap is an expansion signal.
- **contract_term_months** — 12/24/36; longer terms correlate with commitment.
- **contract_start_date** — initial start; drives tenure and onboarding timing.
- **renewal_date** — the upcoming renewal decision date.
- **forecast_as_of_date** — `renewal_date` minus 90 days; the cutoff for feature computation (respect it to avoid leakage).
- **num_products / product_breadth** — count of owned modules; more breadth is stickier.
- **sponsor_status** — `strong` / `stable` / `new` / `lost`; a core relationship signal.
- **health_index / churn_probability / outcome** — the latent score, its probability form, and the realized label.
