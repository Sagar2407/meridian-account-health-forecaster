# Account Health Scoring Methodology

Account health is summarized by a **health index** and a derived **churn probability**. The index is a weighted combination of *observable* signals; higher means healthier. It is designed so that a forecast can be justified by the same features a human would cite.

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

**Do not use the latent labels.** `health_archetype` and `health_band` are generative ground truth for analysis and are NOT valid model inputs. A forecast must be built from the observable feature columns and the retrieved evidence, or it is leaking the answer.
