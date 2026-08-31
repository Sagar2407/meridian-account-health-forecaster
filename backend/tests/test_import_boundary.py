"""The evaluation boundary is structural, not advisory (plan section 8.4).

Labels, health indices, and driver contributions live in `meridian_eval`. If any
runtime module could import that package, the boundary would rest on reviewer
vigilance. This test makes it a build failure instead.
"""

import ast
from pathlib import Path

import meridian

RUNTIME_PACKAGE_ROOT = Path(meridian.__file__).resolve().parent
FORBIDDEN_IMPORT_ROOT = "meridian_eval"


def _runtime_modules() -> list[Path]:
    """Return every Python module shipped inside the runtime package."""

    return sorted(RUNTIME_PACKAGE_ROOT.rglob("*.py"))


def _imported_roots(module: Path) -> set[str]:
    """Return the top-level package names `module` imports."""

    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_runtime_package_has_modules_to_check() -> None:
    """Guard against the scan silently passing because it found nothing."""

    assert len(_runtime_modules()) >= 5


def test_no_runtime_module_imports_the_evaluation_package() -> None:
    """Application code must not be able to reach labels or ground truth."""

    offenders = [
        module.relative_to(RUNTIME_PACKAGE_ROOT).as_posix()
        for module in _runtime_modules()
        if FORBIDDEN_IMPORT_ROOT in _imported_roots(module)
    ]
    assert not offenders, f"runtime modules import {FORBIDDEN_IMPORT_ROOT}: {offenders}"


#: Vendor SDKs that must not leak past the one adapter allowed to use them.
#: ADR 0004 keeps orchestration portable by making the interface the dependency
#: rather than the vendor, and the Phase 4 exit gate states it plainly: "Graph
#: code imports provider interfaces, not provider SDKs directly."
PROVIDER_SDK_ROOTS = frozenset({"openai", "anthropic", "azure", "cohere", "google", "ollama"})
PROVIDER_ADAPTER_MODULES = frozenset({"llm/openai_compatible.py"})


def test_only_the_named_adapter_may_import_a_provider_sdk() -> None:
    """A vendor SDK anywhere else would make ADR 0004's portability a fiction."""

    offenders: list[str] = []
    for module in _runtime_modules():
        relative = module.relative_to(RUNTIME_PACKAGE_ROOT).as_posix()
        if relative in PROVIDER_ADAPTER_MODULES:
            continue
        leaked = sorted(_imported_roots(module) & PROVIDER_SDK_ROOTS)
        if leaked:
            offenders.append(f"{relative}: {leaked}")
    assert not offenders, f"provider SDKs imported outside the adapter: {offenders}"


def test_the_adapter_boundary_is_not_vacuous() -> None:
    """The rule above only means something if the adapter really uses the SDK.

    If the import were ever removed or renamed, the test above would keep
    passing while enforcing nothing at all.
    """

    adapter = RUNTIME_PACKAGE_ROOT / "llm" / "openai_compatible.py"
    assert adapter.is_file(), "the named provider adapter no longer exists"
    assert "openai" in adapter.read_text(encoding="utf-8")


def test_the_tool_layer_does_not_depend_on_a_language_model() -> None:
    """Section 12's tools are deterministic; none may reach a model to answer."""

    tool_modules = sorted((RUNTIME_PACKAGE_ROOT / "tools").rglob("*.py"))
    assert tool_modules, "no tool modules found; this scan would pass vacuously"
    offenders = [
        module.relative_to(RUNTIME_PACKAGE_ROOT).as_posix()
        for module in tool_modules
        if _imported_roots(module) & PROVIDER_SDK_ROOTS
        or "meridian.llm" in module.read_text(encoding="utf-8")
    ]
    assert not offenders, f"tool modules reach a language model: {offenders}"


def test_the_mcp_sdk_stays_inside_the_transport_modules() -> None:
    """Services must stay testable without a transport, per plan section 12."""

    transport = {"tools/server.py", "tools/client.py"}
    offenders: list[str] = []
    for module in _runtime_modules():
        relative = module.relative_to(RUNTIME_PACKAGE_ROOT).as_posix()
        if relative in transport:
            continue
        if "mcp" in _imported_roots(module):
            offenders.append(relative)
    assert not offenders, f"the MCP SDK is imported outside the transport modules: {offenders}"
