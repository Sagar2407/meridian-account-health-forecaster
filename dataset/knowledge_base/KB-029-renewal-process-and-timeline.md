# Renewal Process and Timeline

The renewal motion runs on a 90-day clock anchored to `forecast_as_of_date` (renewal minus 90 days).

**T-90:** Health assessment and forecast. Classify the likely outcome and record the rationale. Confirm decision-maker and budget authority. High-risk or high-ACV accounts enter human review here.
**T-60:** Value review with the customer; surface and address risks; for healthy accounts, develop the expansion case.
**T-30:** Commercial alignment internally; issue the quote; handle objections.
**T-14:** Confirm paperwork and close. Escalate any slippage.
**T-0 (renewal_date):** Outcome realized and recorded (Renewed/Expanded/Contracted/Churned) with a reason.

**Guardrail.** Never compute or present a forecast using data after the `forecast_as_of_date` — doing so leaks the future into the prediction. Features in `account_features` already respect this cutoff.

**Escalation.** If an account is unhealthy at T-90 or slips at any checkpoint, trigger the appropriate play (Save Play, At-Risk Triage) and, for Strategic/high-ACV accounts, human executive engagement.
