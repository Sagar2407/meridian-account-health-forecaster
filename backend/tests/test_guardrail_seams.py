"""The guardrail seams must not be reachable from anything the system serves.

`GraphNodes` exposes three methods a subclass can override to remove a guardrail
layer -- `validate_intake`, `screen`, and `verify` -- because section 22.4's
second ablation cannot be run without them. That is a deliberate hole, and a
deliberate hole needs a test that it stays where it was put.

Two properties are checked. Each seam actually calls the real check, so a future
refactor cannot leave a seam that guards nothing while the tests still pass. And
no served module supplies its own nodes to `build_graph`, so nothing reachable
from the API or the CLI can weaken a guardrail by passing one.

The complementary rule -- that no served module may import `meridian_eval`,
where the only ablated subclass lives -- is `test_import_boundary.py`.
"""

import ast
from pathlib import Path

import pytest

from meridian.data.paths import repository_root
from meridian.graph.nodes import GraphNodes

SEAMS = ("validate_intake", "screen", "verify")
#: The real check each seam must call. A seam that stopped calling its check
#: would be a guardrail removed in production, not a seam.
REQUIRED_CALL = {
    "validate_intake": "evaluate_intake",
    "screen": "screen_evidence",
    "verify": "verify_output",
}
SERVED_ROOTS = (
    repository_root() / "backend" / "src" / "meridian",
    repository_root() / "scripts",
)


def seam_source(name: str) -> str:
    """Return the source of one seam method."""

    import inspect

    return inspect.getsource(getattr(GraphNodes, name))


@pytest.mark.parametrize("name", SEAMS)
def test_each_seam_calls_the_real_guardrail(name: str) -> None:
    """A seam that no longer calls its check has removed a guardrail."""

    required = REQUIRED_CALL[name]
    assert required in seam_source(name), (
        f"GraphNodes.{name} no longer calls {required}. The seam exists so the "
        f"ablation can override it, not so the shipped graph can skip the check."
    )


def build_graph_calls(path: Path) -> list[ast.Call]:
    """Return every `build_graph(...)` call in one file."""

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_graph"
    ]


def test_no_served_module_supplies_its_own_nodes() -> None:
    """Passing `nodes=` is how a guardrail gets removed; nothing served may."""

    offenders: list[str] = []
    for root in SERVED_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            for call in build_graph_calls(path):
                if any(keyword.arg == "nodes" for keyword in call.keywords):
                    offenders.append(f"{path.relative_to(repository_root())}:{call.lineno}")
    assert not offenders, (
        "these served modules pass their own nodes to build_graph, which is how "
        f"a guardrail layer is removed: {offenders}"
    )
