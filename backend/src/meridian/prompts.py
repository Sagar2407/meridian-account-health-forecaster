"""Every instruction the system sends a model, and a version for it (ER-007).

Requirement ER-007 asks that each claimed result be tied to an artifact naming
the commit, the data, the model, the **prompt**, and the environment it came
from. The first four were recorded; this supplies the fifth.

Prompts are not frozen the way thresholds are. A threshold digest is pinned by a
test because changing one after seeing a held-out number is the thing section
22.7 exists to prevent. A prompt is allowed to improve -- what must not happen
is a result whose prompt cannot be identified afterwards. So this records a
version rather than enforcing one, and the digest simply changes when an
instruction does.

The registry is assembled here rather than in the evaluation package because the
evaluation must not be the only thing that knows what the system says to a
model: `GET /api/health` and the trace manifest can name the same version.
"""

import hashlib
from typing import TypedDict

from meridian.agents.forecast_adjudicator import (
    ADJUDICATOR_INSTRUCTIONS,
    CANDIDATE_INSTRUCTIONS,
)
from meridian.agents.orchestrator import PLANNER_INSTRUCTIONS
from meridian.tools.server import SERVER_INSTRUCTIONS

#: Every instruction this system authors that shapes what a model does, by the
#: role that carries it. Three go to a provider directly. The fourth is the MCP
#: server's own `instructions` field, which this system does not put in a
#: prompt -- its client is in-process -- but which any other MCP client would
#: read into a model's context, so it is versioned with the rest rather than
#: carved out by an exclusion nobody would revisit.
#:
#: A prompt absent from this mapping is a prompt no artifact can account for, so
#: `test_prompt_registry.py` fails the build when one is added elsewhere.
PROMPTS: dict[str, str] = {
    "planner": PLANNER_INSTRUCTIONS,
    "adjudicator": ADJUDICATOR_INSTRUCTIONS,
    "candidate": CANDIDATE_INSTRUCTIONS,
    "mcp_server": SERVER_INSTRUCTIONS,
}


def _digest(text: str) -> str:
    """Return a short, stable digest of one instruction."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def prompt_digests() -> dict[str, str]:
    """Return a digest per prompt, so a change points at which one moved."""

    return {name: _digest(text) for name, text in sorted(PROMPTS.items())}


def prompt_version() -> str:
    """Return one digest covering every prompt, for a manifest line.

    Names are included in the hash, not just bodies: renaming a role while
    keeping its text is a change to what the system does with it.
    """

    joined = "\n".join(f"{name}:{text}" for name, text in sorted(PROMPTS.items()))
    return _digest(joined)


class PromptManifest(TypedDict):
    """What an evaluation artifact records about the prompts it used."""

    version: str
    count: int
    digests: dict[str, str]


def prompt_manifest() -> PromptManifest:
    """Return what an evaluation artifact records about the prompts it used."""

    return {
        "version": prompt_version(),
        "count": len(PROMPTS),
        "digests": prompt_digests(),
    }


__all__ = [
    "PROMPTS",
    "PromptManifest",
    "prompt_digests",
    "prompt_manifest",
    "prompt_version",
]
