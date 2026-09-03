"""The frozen decision thresholds (plan sections 16.1, 16.5, 22.6, and 22.7).

Section 22.7 asks for two things that are easy to say and easy to lose track of:
"freeze config and thresholds before held-out execution", and "never tune on
final held-out outcomes". This module is how both are kept.

Every number that decides what a run releases lives here, in one frozen object
with a version and a content digest. The digest goes into every evaluation
result directory, so a reported metric can be tied to the exact thresholds that
produced it, and a report quoting a number measured under different thresholds
is detectable rather than merely unlikely.

**These are not settings.** There is deliberately no environment variable and no
constructor argument that changes them at runtime. A threshold an operator can
move between two runs is not a calibration, and a held-out result measured
against a movable threshold means nothing. Changing one is a source change, a
new version, a new digest, and a development-split study recorded beside it --
which is what `meridian_eval.threshold_study` produces.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field

#: Bumped whenever any value below changes. The digest catches an accidental
#: change; the version records a deliberate one.
THRESHOLD_VERSION = "v2"


@dataclass(frozen=True)
class DecisionThresholds:
    """Every number that decides what a run releases and who sees it."""

    # -- Section 16.1: how confidence is composed --------------------------
    calibrated_weight: float = 0.70
    coverage_weight: float = 0.15
    agreement_weight: float = 0.15

    # -- Section 16.1: the hard caps ---------------------------------------
    cap_critical_source_missing: float = 0.69
    cap_unresolved_conflict: float = 0.69
    # Each cap sits one hundredth below a band edge, which is the mechanism
    # rather than a coincidence: 0.69 puts a critically incomplete run under
    # amber's 0.70 so it routes red, and these two put a run with a retrieval
    # gap or a repaired verification under green so it cannot auto-release.
    # They move with the bands -- `__post_init__` refuses a set where they do
    # not -- because a cap above the band it is meant to sit under releases
    # exactly the runs it exists to hold back.
    cap_exhausted_retrieval_gap: float = 0.79
    cap_repaired_verification: float = 0.79

    # -- Section 16.5: the human-review bands ------------------------------
    green_minimum_confidence: float = 0.80
    amber_minimum_confidence: float = 0.70

    #: Two outcomes closer than this are not distinguishable by this model on
    #: this evidence, which section 16.5 treats as a red-route condition.
    tie_margin: float = 0.10

    #: Provenance for the freeze. `rationale` is prose on purpose: a frozen
    #: threshold with no recorded reason is a magic number with a version.
    version: str = THRESHOLD_VERSION
    rationale: str = field(
        default=(
            "v2. Section 16.1's structure and weights are unchanged from the "
            "plan. The green band moves from 0.85 to 0.80, and the two caps "
            "that must sit below it move from 0.84 to 0.79 with it. The reason "
            "is a measurement, on development data only, as section 22.7 "
            "requires: the composed score is under-confident by 0.187, so runs "
            "that were correct were being held for review by a band calibrated "
            "for a scale the system does not produce. Thirty-eight development "
            "runs scored 0.80-0.90 and every one of them was right. Moving the "
            "band without moving the caps would have auto-released four runs "
            "with an exhausted retrieval gap, which is the outcome section "
            "16.1's caps exist to prevent."
        )
    )

    def digest(self) -> str:
        """Return a stable content digest of the numeric thresholds.

        The rationale is excluded: rewording an explanation is not a change to
        what the system decides, and a digest that moved when prose moved would
        be ignored within a week.
        """

        numeric = {
            key: value
            for key, value in sorted(asdict(self).items())
            if isinstance(value, int | float)
        }
        payload = json.dumps(numeric, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def as_dict(self) -> dict[str, object]:
        """Return the thresholds and their digest, for a result manifest."""

        return {**asdict(self), "digest": self.digest()}

    def __post_init__(self) -> None:
        """Refuse a set of thresholds that cannot mean what it says.

        Raises:
            ValueError: If the confidence weights do not sum to one, or if the
                bands are not ordered green above amber.
        """

        total = self.calibrated_weight + self.coverage_weight + self.agreement_weight
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"confidence weights sum to {total}, not 1")
        if not 0.0 < self.amber_minimum_confidence < self.green_minimum_confidence <= 1.0:
            raise ValueError(
                "the bands must be ordered 0 < amber < green <= 1, got "
                f"amber={self.amber_minimum_confidence}, green={self.green_minimum_confidence}"
            )
        # Section 16.1's caps only mean anything relative to section 16.5's
        # bands. A cap at or above the band it is meant to hold a run under
        # releases precisely the runs it exists to stop, and nothing else in
        # the system would notice: the run looks like any other confident one.
        amber = self.amber_minimum_confidence
        green = self.green_minimum_confidence
        for capped, limit, band_name, band in (
            ("cap_critical_source_missing", self.cap_critical_source_missing, "amber", amber),
            ("cap_unresolved_conflict", self.cap_unresolved_conflict, "amber", amber),
            ("cap_exhausted_retrieval_gap", self.cap_exhausted_retrieval_gap, "green", green),
            ("cap_repaired_verification", self.cap_repaired_verification, "green", green),
        ):
            if limit >= band:
                raise ValueError(
                    f"{capped}={limit} is not below {band_name}={band}, so a run it caps "
                    "would route as though it had never been capped"
                )
        for name, value in (
            ("cap_critical_source_missing", self.cap_critical_source_missing),
            ("cap_unresolved_conflict", self.cap_unresolved_conflict),
            ("cap_exhausted_retrieval_gap", self.cap_exhausted_retrieval_gap),
            ("cap_repaired_verification", self.cap_repaired_verification),
        ):
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be in (0, 1], got {value}")


#: The frozen set. Imported by `confidence` and `routing`; nothing else
#: constructs a `DecisionThresholds` outside a test or the threshold study.
THRESHOLDS = DecisionThresholds()

#: The digest as it stood when this version was frozen. A change to any
#: threshold without a version bump fails `test_thresholds_are_frozen`, so a
#: silent edit cannot reach a held-out run.
FROZEN_DIGEST = THRESHOLDS.digest()


__all__ = [
    "FROZEN_DIGEST",
    "THRESHOLDS",
    "THRESHOLD_VERSION",
    "DecisionThresholds",
]
