# Meridian Account-Health Dataset - Validation Report

- Accounts: **260**
- Weekly usage rows: **67,223**
- Support tickets: **6,408**
- CSM notes / QBRs: **6,420**
- External events: **595**
- RAG corpus documents: **12,828**
- Golden eval items: **23**

## Outcome distribution
- Churned: 47 (18.1%)
- Contracted: 26 (10.0%)
- Renewed: 135 (51.9%)
- Expanded: 52 (20.0%)

## Sanity checks (causal signal is present & correctly signed)
- corr(adoption_trend_13w, churn_probability) = **-0.342**  (expect negative)
- corr(avg_sentiment, churn_probability)     = **-0.692**  (expect negative)

## Mean churn probability by latent archetype (expect sensible ordering)
- onboarding_stall: 0.992
- sharp_drop: 0.904
- slow_decline: 0.806
- recovered: 0.475
- seasonal_healthy: 0.246
- stable_healthy: 0.161
- expanding: 0.03

> The latent `health_archetype` / `health_band` columns are ground truth for analysis only and must NOT be used as model features. Outcomes are a function of the observable feature columns plus irreducible noise.