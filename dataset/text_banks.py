"""
text_banks.py
=============
Phrase and template banks used by generators.py to assemble contextually rich
support tickets and CSM notes. Text is conditioned on:

  * ticket "tone"    : positive | neutral | frustrated | urgent
  * account "band"   : thriving | steady | slipping | at_risk | stalled | recovering

Slots use {curly} placeholders filled in by the generator with account-specific
values ({product}, {feature}, {company}, {csm}, {sponsor}, {industry}, {metric}).
All content is invented.
"""

# =========================================================================== #
# SUPPORT TICKETS
# =========================================================================== #

TICKET_SUBJECTS = {
    "How-to / Usage": [
        "How do we configure {feature} in {product}?",
        "Best practice for {feature} rollout across teams",
        "Question on {product} {feature} setup",
        "Guidance requested: enabling {feature}",
        "Clarification on {product} publishing workflow",
    ],
    "Bug / Defect": [
        "{feature} not saving changes in {product}",
        "Unexpected error when using {feature}",
        "{product} rendering incorrectly after last update",
        "Data mismatch in {product} {feature}",
        "{feature} intermittently failing since Tuesday",
    ],
    "Feature Request": [
        "Feature request: extend {feature} to support bulk actions",
        "Enhancement idea for {product} {feature}",
        "Can {feature} support additional export formats?",
        "Roadmap question: native {feature} integration",
        "Request: granular permissions for {feature}",
    ],
    "Integration / API": [
        "{product} API returning 429s under load",
        "Help connecting {product} to our data warehouse",
        "Webhook payload question for {feature}",
        "SSO / SCIM configuration for {product}",
        "API rate limits blocking our nightly sync",
    ],
    "Billing / Licensing": [
        "Seat count discrepancy on latest invoice",
        "Question about {product} license entitlements",
        "Adding seats mid-term — process?",
        "Clarification on overage charges",
        "Renewal quote line-item question",
    ],
    "Performance / Outage": [
        "{product} slow to load this morning",
        "Elevated latency on {feature}",
        "Partial outage affecting {product} publishing",
        "Timeouts when running {feature}",
        "Degraded performance across {product}",
    ],
    "Escalation": [
        "ESCALATION: {product} blocking our campaign launch",
        "Urgent: repeated failures impacting go-live",
        "Executive escalation — {product} reliability concerns",
        "Blocking issue ahead of {industry} launch window",
        "Escalating: unresolved {feature} defect impacting business",
    ],
    "Onboarding / Enablement": [
        "Scheduling enablement session for {product}",
        "Onboarding checklist — where are we?",
        "Requesting admin training for {feature}",
        "Kickoff follow-ups for {product} rollout",
        "Sandbox access for our implementation team",
    ],
}

TICKET_BODY_OPENERS = {
    "positive": [
        "Hi team, things are going well with {product} and we're looking to go further.",
        "Hello, we've had a great experience so far and have a quick question.",
        "Hi, the team is really happy with {product}. One thing we'd like to explore:",
        "Thanks for the recent help — following up as we expand our usage.",
    ],
    "neutral": [
        "Hi, we have a question about {product}.",
        "Hello, hoping you can help us with the following.",
        "Hi team, reaching out regarding {product}.",
        "Quick one for the support team:",
    ],
    "frustrated": [
        "Hi, we've raised this before and it's still not resolved.",
        "This is becoming a recurring problem and it's affecting the team.",
        "We're pretty frustrated — this keeps happening with {product}.",
        "Following up again since we haven't had a workable answer.",
    ],
    "urgent": [
        "We need help urgently — this is blocking work right now.",
        "This is time-sensitive and impacting a live deliverable.",
        "Flagging this as urgent; we have a deadline this week.",
        "Priority issue: this is holding up our {industry} launch.",
    ],
}

TICKET_BODY_CORE = {
    "How-to / Usage": [
        "We want to roll out {feature} to a wider group and aren't sure of the recommended configuration. "
        "Could you point us to the right setup steps or a reference implementation?",
        "Our team is trying to standardize how we use {feature} across regions. What does Meridian recommend for governance here?",
        "We can see {feature} in the admin panel but are unsure how it interacts with our existing workflow. Some guidance would help.",
    ],
    "Bug / Defect": [
        "When we use {feature} in {product}, changes appear to save but revert after refresh. Steps to reproduce are attached.",
        "We're seeing an error code we don't recognize when running {feature}. It started after the most recent release.",
        "{feature} produces inconsistent results between our staging and production environments. This is confusing our editors.",
    ],
    "Feature Request": [
        "It would help enormously if {feature} supported bulk operations — right now our team does this one item at a time.",
        "Could {feature} be extended to cover our use case? Happy to share detail on the workflow we're trying to support.",
        "We'd love to see tighter integration between {feature} and the rest of {product}. Is this on the roadmap?",
    ],
    "Integration / API": [
        "Our nightly sync into the data warehouse is hitting rate limits on the {product} API. Can we raise the ceiling or batch differently?",
        "We're wiring {product} into our internal tooling and need clarity on the webhook payload for {feature}.",
        "SSO is configured but SCIM provisioning isn't creating users as expected. Logs attached.",
    ],
    "Billing / Licensing": [
        "The latest invoice shows a different seat count than we have provisioned. Can we reconcile this before month-end?",
        "We're planning to add seats mid-term for a new team and want to understand the process and pricing.",
        "There's a line item on the renewal quote we don't recognize — could you clarify the entitlement?",
    ],
    "Performance / Outage": [
        "{product} has been noticeably slow this morning and {feature} is timing out for several users.",
        "We're seeing elevated latency that's affecting our editors' ability to publish on schedule.",
        "There appears to be a partial outage on {feature}. Can you confirm status and ETA?",
    ],
    "Escalation": [
        "This defect in {feature} is now blocking our campaign launch and we've lost confidence in the timeline. We need a senior engineer engaged today.",
        "We've had repeated failures with {product} in the run-up to go-live. Leadership is asking hard questions and we need a recovery plan.",
        "The unresolved issue with {feature} is materially impacting the business. Please treat this as an executive escalation.",
    ],
    "Onboarding / Enablement": [
        "We'd like to schedule enablement for {product} — several admins are still not confident with {feature}.",
        "Our rollout has stalled and the team isn't sure of next steps. Can we get a working session to unblock onboarding?",
        "Requesting sandbox access and admin training so our implementation team can make progress on {product}.",
    ],
}

TICKET_BODY_CLOSERS = {
    "positive": [
        "Thanks so much — really appreciate the partnership.",
        "No rush at all; whenever the team has a moment. Thank you!",
        "Appreciate the help as always.",
    ],
    "neutral": [
        "Thanks in advance.",
        "Let us know what you need from our side.",
        "Appreciate any pointers.",
    ],
    "frustrated": [
        "We'd really like this taken seriously this time.",
        "Please escalate if needed — we can't keep working around it.",
        "A clear answer would go a long way here.",
    ],
    "urgent": [
        "Please respond as soon as possible.",
        "We need an update today if at all possible.",
        "Flagging to our CSM {csm} as well given the impact.",
    ],
}

# =========================================================================== #
# CSM NOTES  (assembled into multi-section narratives by the generator)
# =========================================================================== #

# ---- Executive-summary openers by band ---- #
NOTE_EXEC_SUMMARY = {
    "thriving": [
        "{company} continues to be a standout account. Adoption of {product} is strong and still climbing, and the relationship is healthy across both practitioner and executive levels.",
        "Momentum at {company} is excellent. The team has moved well beyond baseline usage and is actively pulling us into new use cases.",
        "This is one of the healthiest accounts in the book. {company} treats Meridian as strategic infrastructure and engagement keeps deepening.",
    ],
    "steady": [
        "{company} is a stable, healthy account. Usage of {product} is consistent and the core team is engaged, though there's untapped room to grow.",
        "The relationship with {company} is in good shape — dependable adoption, no major fires, and a receptive sponsor.",
        "{company} remains solid. Nothing alarming; the opportunity is to convert steady usage into deeper adoption.",
    ],
    "slipping": [
        "I have growing concerns about {company}. Usage of {product} has been drifting down over the past couple of quarters and engagement from the core team has cooled.",
        "{company} is trending the wrong way. Adoption is softening and it's getting harder to get time with the right people.",
        "This account needs attention. The decline at {company} isn't a cliff, but the trajectory is clearly negative and renewal is not a given.",
    ],
    "at_risk": [
        "{company} is at serious risk. Usage of {product} dropped sharply and the relationship has become strained. This is a red account heading into renewal.",
        "Red flag on {company}. Something changed on their side and adoption fell off a cliff; we are firefighting.",
        "{company} is in trouble. The combination of a usage collapse and a shaken sponsor relationship puts the renewal in real jeopardy.",
    ],
    "stalled": [
        "{company} never really got off the ground. The implementation stalled after kickoff and {product} has seen only minimal usage since.",
        "Onboarding at {company} has not landed. Adoption is stuck near zero and the team hasn't operationalized {product}.",
        "{company} is a stalled deployment. Without a reset, this account is unlikely to see value before renewal.",
    ],
    "recovering": [
        "{company} is recovering. We hit a rough patch mid-contract, but the save play is working and usage of {product} has climbed back.",
        "Encouraging turn at {company}. After a dip and an escalation, engagement is rebuilding and the sponsor is re-engaged.",
        "{company} looks to be back on track. The intervention stabilized the account and the trend is now positive again.",
    ],
}

# ---- Adoption narrative by trend direction ---- #
NOTE_ADOPTION = {
    "up": [
        "Weekly active users on {product} are up materially, and the team has adopted advanced capabilities like {feature}. Depth of usage — not just logins — is what stands out.",
        "Adoption metrics are trending up across the board. {feature} in particular has become part of their daily workflow.",
        "Usage has grown steadily; they've graduated from basic publishing into {feature} and are asking about even more advanced patterns.",
    ],
    "flat": [
        "Usage of {product} is steady but flat. The core team is active, though adoption of advanced features such as {feature} remains shallow.",
        "Adoption has plateaued. They use {product} reliably for the essentials but haven't pushed into {feature} or other higher-value capabilities.",
        "Metrics are stable quarter over quarter. There's a clear opportunity to drive depth via {feature}, which they've barely touched.",
    ],
    "down": [
        "Weekly active users have declined and session depth is thinning. Advanced features like {feature} have been effectively abandoned.",
        "Adoption is eroding. Logins are down, and the drop is concentrated in the teams that were previously our strongest users.",
        "The usage trend is clearly negative — fewer active users, shorter sessions, and no meaningful use of {feature}.",
    ],
}

# ---- Stakeholder / relationship narrative ---- #
NOTE_STAKEHOLDER = {
    "strong": [
        "Our executive sponsor, {sponsor}, remains a strong champion and is vocal internally about the value they're getting.",
        "{sponsor} continues to sponsor the relationship actively and has been a reference for us with peers.",
        "The champion, {sponsor}, is engaged and well-connected to the practitioner team — a healthy structure.",
    ],
    "stable": [
        "{sponsor} is our main sponsor and remains supportive, if less hands-on than earlier in the relationship.",
        "Sponsorship under {sponsor} is stable. We should deepen relationships beyond a single point of contact.",
        "{sponsor} continues to sign off on the relationship, though engagement is more transactional lately.",
    ],
    "new": [
        "There's been a sponsor change: {sponsor} has taken over ownership. Early signals are cautiously positive but the relationship needs rebuilding.",
        "New sponsor, {sponsor}, is now the decision-maker. We're working to establish credibility from a lower base than before.",
        "Leadership on their side shifted to {sponsor}. This is a risk and an opportunity — the prior relationship equity is gone.",
    ],
    "lost": [
        "We've lost our executive sponsor, and no clear replacement has emerged. This is a significant relationship gap heading into renewal.",
        "The departure of our champion has left us without an internal advocate. Multi-threading is now urgent.",
        "Our primary sponsor left the company and the vacuum is hurting us — decisions are stalling and access has narrowed.",
    ],
}

# ---- Support-experience narrative ---- #
NOTE_SUPPORT = {
    "light": [
        "Support load is light and healthy — mostly how-to and feature-request tickets, which is a good sign of an engaged team.",
        "Their tickets skew toward enhancement ideas rather than problems, consistent with a maturing deployment.",
    ],
    "normal": [
        "Support volume is normal. A mix of usage questions and the occasional defect, nothing systemic.",
        "Nothing unusual in support — steady stream of routine tickets, all resolved within SLA.",
    ],
    "heavy": [
        "Support load has been heavy, with several escalations and a couple of P1s. Sentiment in recent tickets has been notably negative.",
        "We're seeing elevated ticket volume and repeated escalations; the team's frustration is showing up clearly in their tone.",
        "Support has been a pain point — multiple unresolved defects and an executive escalation that dented trust.",
    ],
}

# ---- External-context narrative (ties to synthetic events) ---- #
NOTE_EXTERNAL = {
    "headwind": [
        "Externally, there are headwinds: {event}. This is almost certainly affecting their bandwidth and budget for our program.",
        "Worth flagging the external context — {event}. That kind of disruption tends to freeze discretionary projects like ours.",
        "Macro context matters here: {event}. We should assume tighter scrutiny on spend at renewal.",
    ],
    "tailwind": [
        "The external picture is favorable — {event} — which should support continued and possibly expanded investment.",
        "Good tailwind: {event}. This is a moment to align our value story to their growth agenda.",
        "Positive external signal — {event} — gives us an opening to talk expansion.",
    ],
    "none": [
        "No notable external events on their side this period.",
        "Nothing material in the market or news to flag for this account right now.",
    ],
}

# ---- Expansion narrative ---- #
NOTE_EXPANSION = [
    "There's a live expansion opportunity: they've asked about {feature} and a rollout to an additional business unit. I'm scoping a proposal.",
    "Expansion is in play — interest in adding a module and extending seats to a new team. Worth prioritizing.",
    "They've signaled appetite for more: an upsell around {feature} plus a possible multi-year uplift at renewal.",
]

# ---- Action items by band ---- #
NOTE_ACTIONS = {
    "thriving": [
        "Draft an expansion proposal around {feature}.",
        "Line {company} up as a reference / case study candidate.",
        "Introduce the executive sponsor to our product leadership.",
    ],
    "steady": [
        "Build an adoption plan to drive depth on {feature}.",
        "Schedule a value-realization review to quantify ROI.",
        "Multi-thread beyond the current sponsor.",
    ],
    "slipping": [
        "Book a candid check-in with {sponsor} to understand the pullback.",
        "Run a usage diagnostic and share a re-engagement plan.",
        "Escalate internally for a renewal risk review.",
    ],
    "at_risk": [
        "Open a formal save play with cross-functional support.",
        "Secure an executive-to-executive meeting this month.",
        "Prepare a get-well plan with concrete milestones before renewal.",
    ],
    "stalled": [
        "Reset the implementation with a fresh onboarding plan.",
        "Identify a new internal owner for the rollout.",
        "Consider a services engagement to operationalize {product}.",
    ],
    "recovering": [
        "Sustain the save-play cadence and track leading indicators.",
        "Convert the recovery into a renewal commitment.",
        "Re-establish a regular QBR rhythm now that things have stabilized.",
    ],
}

# ---- Renewal outlook by band ---- #
NOTE_RENEWAL_OUTLOOK = {
    "thriving":   "Renewal outlook: strong, with clear expansion potential.",
    "steady":     "Renewal outlook: likely, assuming we maintain engagement.",
    "slipping":   "Renewal outlook: uncertain — this could go either way without intervention.",
    "at_risk":    "Renewal outlook: at risk. Realistically a coin flip or worse as things stand.",
    "stalled":    "Renewal outlook: poor unless we can demonstrate value quickly.",
    "recovering": "Renewal outlook: cautiously positive following the recovery.",
}

# ---- Short monthly-touchpoint templates (assembled from 1-2 sentences) ---- #
NOTE_TOUCHPOINT_OPENERS = {
    "thriving":   ["Quick monthly note — {company} continues to look great.",
                   "Monthly check-in: all green at {company}."],
    "steady":     ["Monthly touchpoint — {company} steady as she goes.",
                   "Routine check-in with {company}; no surprises."],
    "slipping":   ["Monthly note — keeping an eye on {company}; still drifting.",
                   "Touchpoint: {company} not improving; watching closely."],
    "at_risk":    ["Monthly note — {company} still red; firefighting continues.",
                   "Touchpoint: {company} remains a serious concern."],
    "stalled":    ["Monthly note — {company} rollout still stuck.",
                   "Touchpoint: little movement at {company}."],
    "recovering": ["Monthly note — {company} continuing to recover.",
                   "Touchpoint: {company} trending back up, slowly."],
}

# ---- Onboarding kickoff template pieces ---- #
NOTE_ONBOARDING = [
    "Kickoff completed with {company}. Sponsor {sponsor} set the vision; we aligned on success criteria for {product} and a 90-day adoption plan. "
    "Primary use case is {industry}-focused. Risks noted: competing priorities on their side and a lean admin team.",
    "Onboarding kickoff for {company} went well. We scoped the {product} rollout, assigned an internal owner, and agreed on enablement dates. "
    "{sponsor} is bought in; the open question is whether the practitioner team has the bandwidth to ramp quickly.",
]

# ---- Escalation / save-play template pieces ---- #
NOTE_ESCALATION = [
    "Opened a save play for {company}. Trigger: {event_or_issue}. We've assembled a cross-functional team, secured an exec sponsor on our side, "
    "and committed to a get-well plan with weekly checkpoints. {sponsor} is engaged and the mood is tense but workable.",
    "Escalation logged for {company}. The core issue is {event_or_issue}, compounded by eroding confidence. Action plan agreed with {sponsor}; "
    "we are tracking leading indicators weekly and will reassess renewal posture in 30 days.",
]

# ---- Renewal-prep template pieces ---- #
NOTE_RENEWAL_PREP = [
    "Renewal prep for {company}. {outlook_line} Strategy: lead with value realized on {product}, address the risks head-on, and {play}. "
    "Decision-maker is {sponsor}; timeline is roughly one quarter out.",
    "Prepping the {company} renewal. {outlook_line} We'll frame the business case around {feature} adoption and {play}. Aligning internally on commercial posture.",
]

RENEWAL_PLAYS = {
    "thriving":   "propose a multi-year uplift with an expansion module",
    "steady":     "hold the line on price while nudging toward deeper adoption",
    "slipping":   "offer a right-sized package to keep them in the fold",
    "at_risk":    "protect the renewal even if it means a short-term concession",
    "stalled":    "consider a reset offer tied to a fresh implementation plan",
    "recovering": "convert the recovery into a firm multi-year commitment",
}
