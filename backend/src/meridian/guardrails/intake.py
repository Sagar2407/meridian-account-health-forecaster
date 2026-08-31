"""Intake guardrails (plan section 16.2).

Nine rules, each one a bullet from section 16.2, each carrying a rule id and a
reason code. The reason codes are the same vocabulary the packaged guardrail
evaluation set uses for its expected behaviours, so Phase 7 can compare a
decision with an expected behaviour directly instead of through a translation
table that could quietly disagree with both.

Not every rule blocks. Three of the plan's categories are advisory: a request
that asks the system to treat a rumour as fact, or that demands a definitive
one-word answer, is answerable -- what must not happen is that the system
complies with the framing. Those rules pass the request through carrying a
reason code, and the adjudicator turns each one into a stated limitation.

Every pattern here matches a *shape of request*, not a topic. "Churn" is a
perfectly ordinary word in this domain and blocking it would make the system
useless; asking for the stored `health_band` field is a different thing, and
that is what the leakage rule looks for.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from meridian.contracts import AssessmentRequest, GuardrailDecision
from meridian.data.constants import DATASET_AS_OF_DATE
from meridian.data.repository import RuntimeRepository, UnknownAccountError
from meridian.retrieval.documents import forbidden_field_mentions

IntakeOutcome = Literal["pass", "block", "review", "clarify"]

#: Terms that make a question recognisably about account health. A question with
#: none of these and no other signal is materially underspecified.
TOPIC_TERMS: frozenset[str] = frozenset(
    {
        "account",
        "adoption",
        "assess",
        "assessment",
        "churn",
        "contract",
        "csat",
        "engagement",
        "escalation",
        "expand",
        "expansion",
        "forecast",
        "health",
        "outlook",
        "renew",
        "renewal",
        "risk",
        "sentiment",
        "sponsor",
        "support",
        "ticket",
        "usage",
    }
)
MINIMUM_SPECIFIC_WORDS = 4

#: Metrics a reader might reasonably expect that this dataset does not contain.
#: This is a denylist and therefore incomplete by construction: a question about
#: an absent field that is not listed here is not caught at intake and instead
#: surfaces downstream as a coverage gap and an abstention, which is the safe
#: failure rather than a confident invention.
UNSUPPORTED_FIELD_TERMS: tuple[str, ...] = (
    r"net promoter",
    r"\bnps\b",
    r"credit rating",
    r"cash runway",
    r"\bburn rate\b",
    r"competitor(?:s)? spend",
    r"spend with (?:our )?competitors",
    r"marketing (?:department|budget|spend)",
    r"(?:department|team) (?:headcount|size)",
    r"stock price",
    r"share price",
    r"market cap",
    r"profit margin",
    r"balance sheet",
)


@dataclass(frozen=True)
class IntakeRule:
    """One intake rule: what it looks for, and what happens when it matches."""

    rule_id: str
    reason_code: str
    outcome: IntakeOutcome
    message: str
    patterns: tuple[re.Pattern[str], ...]

    def matches(self, text: str) -> bool:
        """Return whether any of this rule's patterns fires on `text`."""

        return any(pattern.search(text) for pattern in self.patterns)


def _compile(*expressions: str) -> tuple[re.Pattern[str], ...]:
    """Return case-insensitive patterns for a rule."""

    return tuple(re.compile(expression, re.IGNORECASE) for expression in expressions)


#: Ordered because precedence matters: a request that is both a privacy request
#: and vague is a privacy refusal, not a clarification.
INTAKE_RULES: tuple[IntakeRule, ...] = (
    IntakeRule(
        rule_id="INTAKE-PRIVACY",
        reason_code="refuse_privacy",
        outcome="block",
        message=(
            "This system reports on account health from business records. It does not "
            "return personal contact details for any individual."
        ),
        patterns=_compile(
            r"\b(?:home|personal|residential)\s+address",
            r"\b(?:cell|mobile|phone|telephone)\s*(?:phone\s*)?number",
            r"\bpersonal\s+(?:email|number|phone|contact)",
            r"\bdate of birth\b|\bsocial security\b|\bssn\b",
            r"\bwhere does\b.{0,40}\blive\b",
        ),
    ),
    IntakeRule(
        rule_id="INTAKE-HR",
        reason_code="refuse_hr_judgment",
        outcome="block",
        message=(
            "This system does not evaluate the performance of named employees. It can "
            "report what the account's records show without attributing them to a person."
        ),
        patterns=_compile(
            r"\bwhich one to fire\b|\bwho (?:should we|to) fire\b|\bshould .{0,40}be fired\b",
            r"\brank (?:our |the )?csms?\b",
            r"\b(?:is|are)\b.{0,40}\bdoing a (?:bad|poor|good|great) job\b",
            r"\bperformance review\b|\bunderperform(?:ing|er)\b",
            r"\b(?:fire|demote|promote|discipline|replace)\s+(?:the\s+)?(?:csm|sponsor|rep)\b",
        ),
    ),
    IntakeRule(
        rule_id="INTAKE-LABEL-LEAK",
        reason_code="refuse_leakage",
        outcome="block",
        message=(
            "The stored outcome and health-label fields are evaluation-only and are not "
            "available to a forecast. The assessment is computed from observable "
            "telemetry, support history, and documented evidence instead."
        ),
        patterns=_compile(
            r"\b(?:true|actual|real|known|stored)\s+(?:label|outcome|answer)\b",
            r"\bground truth\b",
            r"\bwhat (?:really|actually) happened\b",
            r"\bdid (?:they|it|the account) (?:actually )?churn\b",
            r"\bskip the analysis\b",
        ),
    ),
    IntakeRule(
        rule_id="INTAKE-INJECTION",
        reason_code="refuse_leakage",
        outcome="block",
        message=(
            "This request asks the system to change its own instructions or expose its "
            "configuration. The assessment interface only answers account-health questions."
        ),
        patterns=_compile(
            r"\bignore (?:all |any |the )?(?:previous|prior|above|earlier) "
            r"(?:instruction|prompt|rule)",
            r"\bdisregard (?:all |any |the )?(?:previous|prior|above|earlier)\b",
            r"\b(?:system|developer)\s+prompt\b",
            r"\breveal|print|show\b.{0,20}\b(?:your )?(?:instructions|prompt|rules|tools)\b",
            r"\byou are now\b|\bact as\b.{0,30}\b(?:unrestricted|jailbroken|dan)\b",
        ),
    ),
    IntakeRule(
        rule_id="INTAKE-COMMERCIAL",
        reason_code="refuse_commercial_action",
        outcome="block",
        message=(
            "This system is read-only and advisory. It cannot approve pricing, send "
            "documents, or change any record. It can recommend an action for a person to take."
        ),
        patterns=_compile(
            r"\b(?:approve|authorise|authorize|grant|issue|apply|waive|offer)\b"
            r".{0,30}\b(?:discount|refund|credit|concession|extension|renewal)\b",
            r"\b(?:send|email|deliver|share)\b.{0,30}\b(?:contract|quote|proposal|invoice|them)\b",
            r"\b(?:sign|countersign|execute)\b.{0,20}\b(?:the )?contract\b",
            r"\b(?:update|change|edit|delete|write)\b.{0,20}"
            r"\b(?:the )?(?:crm|record|field|account)\b",
        ),
    ),
    IntakeRule(
        rule_id="INTAKE-DOMAIN",
        reason_code="decline_out_of_scope",
        outcome="block",
        message=(
            "This system answers questions about the health of accounts in its own "
            "portfolio. That request is outside its scope."
        ),
        patterns=_compile(
            r"\bweather\b|\bforecast the weather\b",
            r"\b(?:write|compose)\s+(?:me\s+)?(?:a|an)\s+"
            r"(?:haiku|poem|song|joke|story|essay|limerick)\b",
            r"\b(?:stock|share)\s+price\b|\bmarket cap\b",
            r"\btranslate\b.{0,30}\binto\b",
            r"\b(?:recipe|sports score|horoscope)\b",
        ),
    ),
    IntakeRule(
        rule_id="INTAKE-UNSUPPORTED-FIELD",
        reason_code="decline_missing_data",
        outcome="block",
        message=(
            "That measure is not in this system's sources. It reports usage telemetry, "
            "support history, CSM notes, external events, and contract terms."
        ),
        patterns=_compile(*UNSUPPORTED_FIELD_TERMS),
    ),
    IntakeRule(
        rule_id="INTAKE-AUTONOMOUS-ACTION",
        reason_code="escalate_to_human",
        outcome="review",
        message=(
            "A renewal action is a human decision. The assessment is produced as an "
            "advisory recommendation and routed for review rather than executed."
        ),
        patterns=_compile(
            r"\bauto-?decide\b",
            r"\bwithout (?:human )?review\b|\bwithout (?:my |any )?approval\b",
            r"\bexecute it\b|\band execute\b",
            r"\b(?:decide|act) (?:on|for) (?:me|us)\b",
        ),
    ),
    IntakeRule(
        rule_id="INTAKE-UNVERIFIED-CLAIM",
        reason_code="flag_unverified",
        outcome="pass",
        message=(
            "The request supplies an unverified claim. It is recorded as unverified and "
            "excluded from the evidence the forecast is computed from."
        ),
        patterns=_compile(
            r"\bi (?:heard|was told|read)\b",
            r"\brumou?r(?:ed|s)?\b",
            r"\b(?:treat|factor|take) (?:this|that|it) (?:in )?as (?:a )?fact\b",
            r"\bassume (?:that )?(?:they|it|the account) (?:will|is|has)\b",
        ),
    ),
    IntakeRule(
        rule_id="INTAKE-OVERCONFIDENCE",
        reason_code="express_uncertainty",
        outcome="pass",
        message=(
            "The request asks for more certainty than the evidence can support. The "
            "answer reports a calibrated distribution and its confidence instead."
        ),
        patterns=_compile(
            r"\bdefinitive\b|\bone-?word\b|\bjust (?:say )?yes or no\b",
            r"\bwith high confidence\b|\bbe confident\b|\bconfident yes\/no\b",
            r"\bguarantee\b|\bcertain(?:ty)?\b.{0,20}\b(?:answer|call)\b",
            r"\bgive me a (?:confident|definite)\b",
        ),
    ),
)


def _normalise(text: str) -> str:
    """Return text with collapsed whitespace, for stable pattern matching."""

    return " ".join(text.split())


def _horizon_reason(question: str, requested_as_of: date | None) -> str | None:
    """Return why a request reaches past the observable horizon, if it does.

    Two distinct mistakes are caught: an as-of date after the dataset's
    observation horizon, and a question about a year far enough ahead that no
    evidence in the system could speak to it.
    """

    if requested_as_of is not None and requested_as_of > DATASET_AS_OF_DATE:
        return (
            f"the requested as-of date {requested_as_of.isoformat()} is after the "
            f"observation horizon {DATASET_AS_OF_DATE.isoformat()}"
        )
    for match in re.finditer(r"\b(20\d{2})\b", question):
        year = int(match.group(1))
        if year > DATASET_AS_OF_DATE.year + 1:
            return (
                f"the question asks about {year}, beyond any horizon this system's "
                "evidence can support"
            )
    return None


def _is_underspecified(question: str) -> bool:
    """Return whether a question is too vague to act on."""

    words = re.findall(r"[a-z0-9']+", question.lower())
    if any(word in TOPIC_TERMS for word in words):
        return False
    return len(words) < MINIMUM_SPECIFIC_WORDS


def evaluate_intake(
    request: AssessmentRequest, repository: RuntimeRepository | None = None
) -> GuardrailDecision:
    """Return the intake verdict for one request (plan section 16.2).

    Args:
        request: The validated request.
        repository: Used only to confirm the account exists. When absent, the
            existence check is skipped and the context-load node reports an
            unknown account instead, so this function stays usable in a unit
            test without a dataset.

    Returns:
        A decision whose outcome is `block`, `review`, `clarify`, or `pass`. A
        passing decision may still carry advisory rule ids and reason codes.
    """

    question = _normalise(request.question)

    leaked = forbidden_field_mentions(question)
    if leaked:
        return GuardrailDecision(
            stage="intake",
            outcome="block",
            rule_ids=("INTAKE-LABEL-LEAK",),
            reason_codes=("refuse_leakage",),
            message=(
                "The request names evaluation-only fields "
                f"({', '.join(leaked)}), which are never available to a forecast. "
                "The assessment is computed from observable evidence instead."
            ),
        )

    for rule in INTAKE_RULES:
        if rule.outcome == "block" and rule.matches(question):
            return GuardrailDecision(
                stage="intake",
                outcome="block",
                rule_ids=(rule.rule_id,),
                reason_codes=(rule.reason_code,),
                message=rule.message,
            )

    horizon = _horizon_reason(question, request.requested_as_of)
    if horizon is not None:
        return GuardrailDecision(
            stage="intake",
            outcome="block",
            rule_ids=("INTAKE-HORIZON",),
            reason_codes=("decline_out_of_horizon",),
            message=f"This request cannot be answered because {horizon}.",
        )

    if repository is not None:
        try:
            repository.profile(request.account_id)
        except UnknownAccountError:
            return GuardrailDecision(
                stage="intake",
                outcome="block",
                rule_ids=("INTAKE-ACCOUNT-EXISTS",),
                reason_codes=("state_no_such_account",),
                message=f"There is no account {request.account_id} in this portfolio.",
            )

    advisories = tuple(
        rule for rule in INTAKE_RULES if rule.outcome == "pass" and rule.matches(question)
    )
    review = next(
        (rule for rule in INTAKE_RULES if rule.outcome == "review" and rule.matches(question)),
        None,
    )
    if review is not None:
        return GuardrailDecision(
            stage="intake",
            outcome="review",
            rule_ids=(review.rule_id, *(rule.rule_id for rule in advisories)),
            reason_codes=(review.reason_code, *(rule.reason_code for rule in advisories)),
            message=review.message,
        )

    if not advisories and _is_underspecified(question):
        return GuardrailDecision(
            stage="intake",
            outcome="clarify",
            rule_ids=("INTAKE-SPECIFICITY",),
            reason_codes=("request_clarification",),
            message=(
                "Say what you would like to know about this account -- renewal outlook, "
                "adoption, support health, or relationship risk."
            ),
        )

    return GuardrailDecision(
        stage="intake",
        outcome="pass",
        rule_ids=tuple(rule.rule_id for rule in advisories),
        reason_codes=tuple(rule.reason_code for rule in advisories),
        message=" ".join(rule.message for rule in advisories),
    )


__all__ = ["INTAKE_RULES", "TOPIC_TERMS", "IntakeRule", "evaluate_intake"]
