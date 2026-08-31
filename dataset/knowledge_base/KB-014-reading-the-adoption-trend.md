# Reading the Adoption Trend

`adoption_trend_13w` is the slope of an account's weekly `adoption_score` over roughly the last quarter, ending at the `forecast_as_of_date`. It is the most predictive single feature, but it is easy to misread.

**Slope vs level.** A high but flat trajectory is healthy; a high but falling one is a warning even if the current level looks fine. Conversely, a low but rising trajectory (a recovering account) can be a good renewal bet. Always read slope and level together.

**Control for seasonality.** Some industries have strong seasonal swings — retail peaks in Q4, education dips over summer, travel peaks mid-year. A seasonal dip is not decline. Compare the trend to the account's industry seasonal profile before drawing a conclusion; the healthiest seasonal accounts show amplified swings around a stable baseline.

**Watch for cliffs.** A sudden week-over-week collapse (rather than a gentle slope) usually has an external cause — a reorg, an acquisition, or a lost champion. Cliffs often coincide with an adverse external event in the prior month; check `external_events` when you see one.

**Depth check.** A trend driven by advanced-feature usage is more durable than one driven by basic logins. Cross-reference `advanced_feature_adoption_pct`.
