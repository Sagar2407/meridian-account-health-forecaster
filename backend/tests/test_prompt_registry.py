"""Every prompt the system sends must be one an artifact can account for (ER-007).

ER-007 requires each claimed result to be tied to an artifact naming the commit,
the data, the model, the prompt, and the environment. The evaluation manifest
records `prompts.version`, and that version is only worth anything if it covers
every instruction actually sent.

So this checks the registry against the source: any module-level constant whose
name ends in `_INSTRUCTIONS` must appear in `PROMPTS`. Adding a fourth prompt
somewhere and forgetting to register it would otherwise leave a result whose
prompt cannot be identified afterwards, while every test still passed.
"""

import ast
from importlib import import_module
from pathlib import Path

from meridian.data.paths import repository_root
from meridian.prompts import PROMPTS, prompt_digests, prompt_manifest, prompt_version

SOURCE = repository_root() / "backend" / "src" / "meridian"
SUFFIX = "_INSTRUCTIONS"


def module_name(relative: str) -> str:
    """Return the importable name for a path under `backend/src`."""

    return Path(relative).relative_to("backend/src").with_suffix("").as_posix().replace("/", ".")


def declared_instruction_constants() -> dict[str, str]:
    """Return every `*_INSTRUCTIONS` constant in the served package, by module."""

    found: dict[str, str] = {}
    for path in sorted(SOURCE.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
                if isinstance(node, ast.AnnAssign)
                else []
            )
            for target in targets:
                if isinstance(target, ast.Name) and target.id.endswith(SUFFIX):
                    found[target.id] = str(path.relative_to(repository_root()))
    return found


def test_every_instruction_constant_is_registered() -> None:
    """A prompt outside the registry is a prompt no artifact can account for."""

    registered = set(PROMPTS.values())
    declared = declared_instruction_constants()
    assert declared, "no *_INSTRUCTIONS constant was found; the scan is looking in the wrong place"

    # Resolved from the module that declares it, not from `meridian.prompts`.
    # Looking it up there would find only what is already imported, so a prompt
    # added elsewhere and never registered -- the case this test exists for --
    # would come back missing and be skipped.
    unregistered = []
    for name, where in sorted(declared.items()):
        module = import_module(module_name(where))
        if getattr(module, name) not in registered:
            unregistered.append(f"{name} ({where})")
    assert not unregistered, (
        "these prompts are sent to a provider but are not in `PROMPTS`, so no "
        f"evaluation artifact can say which version produced its numbers: {unregistered}"
    )


def test_the_registry_matches_what_is_declared() -> None:
    """The count in the manifest must match the constants that exist."""

    declared = declared_instruction_constants()
    assert len(PROMPTS) == len(declared), (
        f"{len(declared)} instruction constant(s) exist but {len(PROMPTS)} are registered: "
        f"{sorted(declared)} against {sorted(PROMPTS)}"
    )


def test_the_version_changes_when_a_prompt_does() -> None:
    """A version that survived an edit would date every artifact wrongly."""

    before = prompt_version()
    original = PROMPTS["planner"]
    try:
        PROMPTS["planner"] = original + " One more sentence."
        assert prompt_version() != before
        assert prompt_digests()["planner"] != _digest_of(original)
    finally:
        PROMPTS["planner"] = original
    assert prompt_version() == before, "the version did not return to its original value"


def _digest_of(text: str) -> str:
    """Return the digest the registry would compute for one prompt."""

    from meridian.prompts import _digest

    return _digest(text)


def test_the_manifest_carries_a_digest_for_every_prompt() -> None:
    """The manifest is what an artifact stores, so it must be complete."""

    payload = prompt_manifest()
    assert payload["count"] == len(PROMPTS)
    assert set(payload["digests"]) == set(PROMPTS)
    assert payload["version"] == prompt_version()
