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
