"""Curated cached runs for the public demo (plan section 24.3).

Section 24.3 asks for two things that pull against each other: cache curated
fast-path, conflict, insufficient-evidence, and guardrail runs, and "if the live
budget is unavailable, show a clearly labeled cached run rather than pretending
it is live."

The second sentence is the whole design. A cached answer is not a lesser live
answer; it is a *different kind of thing*, and a demo that blurs the two is
misleading in exactly the way this project spends ten phases refusing to be. So
every cached run carries `is_cached`, the moment it was recorded, and the commit
it was recorded at, and the browser is expected to say so on the page.

The cache is read-only at serving time. It is built by `scripts/build_demo_cache.py`
from real runs against the real graph -- there are no hand-written decisions in
it, because a hand-written decision card is a mock-up, not a demonstration.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meridian.data.paths import repository_root

#: Where the curated runs live. Committed, unlike `artifacts/`: the demo needs
#: them present in the image, and they are small.
DEMO_CACHE_PATH = repository_root() / "config" / "demo_cache.json"

#: The four paths section 24.3 asks to have cached, in the order a visitor
#: should meet them.
CuratedKind = str

CURATED_KINDS: tuple[str, ...] = (
    "fast_path",
    "conflict",
    "insufficient_evidence",
    "guardrail_refusal",
)

#: What each curated run is meant to show, in the words the page uses.
KIND_LABELS: dict[str, str] = {
    # Says what the slot selects for -- a forecast reached without the conflict
    # search -- and nothing about the route. The previous wording called it
    # "a straightforward account" while the recorded run was red at 0.64
    # confidence, which is the first thing a visitor to the public demo read.
    "fast_path": (
        "An account whose evidence agrees, so the run takes the fast path without "
        "the Tree-of-Thought search. What it routes to still depends on the "
        "confidence it earns."
    ),
    "conflict": (
        "An account whose evidence disagrees with itself, so the bounded "
        "Tree-of-Thought search runs."
    ),
    "insufficient_evidence": (
        "An account the system declines to label, reporting verified telemetry "
        "and what it would need instead."
    ),
    "guardrail_refusal": "A request an intake guardrail refuses outright.",
}


@dataclass(frozen=True)
class CachedRun:
    """One recorded run, and everything needed to say it is not live."""

    kind: str
    label: str
    account_id: str
    question: str
    recorded_at: str
    commit: str
    route: str
    payload: dict[str, Any]

    @property
    def is_cached(self) -> bool:
        """Always true. The field exists so a caller cannot forget to check."""

        return True

    def as_dict(self) -> dict[str, Any]:
        """Return the JSON view, with the cached marker impossible to omit."""

        return {
            "kind": self.kind,
            "label": self.label,
            "account_id": self.account_id,
            "question": self.question,
            "recorded_at": self.recorded_at,
            "commit": self.commit,
            "route": self.route,
            "is_cached": True,
            "cached_note": (
                "This is a recorded run, not a live one. It was produced by the "
                f"real graph at commit {self.commit[:12]} on {self.recorded_at} and "
                "is replayed here so the demo works without spending a model budget."
            ),
            "state": self.payload,
        }


def load_cache(path: Path | None = None) -> dict[str, CachedRun]:
    """Return the curated runs, keyed by kind.

    A missing or unreadable cache is not an error. The demo degrades to live
    runs, which is the better failure: an empty cache means visitors see the
    real thing, while a crash at import means they see nothing.
    """

    target = path or DEMO_CACHE_PATH
    if not target.is_file():
        return {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}

    runs: dict[str, CachedRun] = {}
    for kind, entry in raw.get("runs", {}).items():
        if not isinstance(entry, dict):
            continue
        runs[kind] = CachedRun(
            kind=kind,
            label=str(entry.get("label", KIND_LABELS.get(kind, kind))),
            account_id=str(entry.get("account_id", "")),
            question=str(entry.get("question", "")),
            recorded_at=str(entry.get("recorded_at", "")),
            commit=str(entry.get("commit", "unknown")),
            route=str(entry.get("route", "unknown")),
            payload=entry.get("state") or {},
        )
    return runs


def write_cache(runs: list[CachedRun], commit: str, path: Path | None = None) -> Path:
    """Write the curated runs, replacing whatever was there."""

    target = path or DEMO_CACHE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": commit,
        "note": (
            "Recorded runs for the public demo (plan section 24.3). Every entry "
            "was produced by the real graph; none is hand-written. Regenerate "
            "with `make bootstrap` or `scripts/build_demo_cache.py`."
        ),
        "runs": {
            run.kind: {
                "label": run.label,
                "account_id": run.account_id,
                "question": run.question,
                "recorded_at": run.recorded_at,
                "commit": run.commit,
                "route": run.route,
                "state": run.payload,
            }
            for run in runs
        },
    }
    target.write_text(
        json.dumps(document, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return target


__all__ = [
    "CURATED_KINDS",
    "DEMO_CACHE_PATH",
    "KIND_LABELS",
    "CachedRun",
    "load_cache",
    "write_cache",
]
