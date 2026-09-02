"""Every published evaluation must name a file its own command writes.

`GET /api/evaluations/{name}` reads a path and reports `not_run` when it is
absent. That is the correct behaviour for an evaluation nobody has run, and it
is indistinguishable from an endpoint pointing at a file **no command ever
writes** -- which is what happened: the retrieval entry named
`retrieval_benchmark.json` while `scripts/evaluate_retrieval.py` wrote only
CSVs, so the deployed page reported that evaluation as never run for as long as
it existed.

An absent artifact cannot be the signal, because a fresh checkout legitimately
has none. So this checks the producing script's source instead: whatever the
endpoint promises, the command it names must at least mention writing it.

`scripts/` is not copied into the runtime image -- the served application never
runs them -- so this module skips there and runs on a developer checkout and in
CI, which is where a mismatch would be introduced.
"""

from pathlib import Path

import pytest

from meridian.api.routes.evaluations import ARTIFACTS
from meridian.data.paths import repository_root

SCRIPTS = repository_root() / "scripts"
HARNESS = repository_root() / "evaluation"

pytestmark = pytest.mark.skipif(
    not SCRIPTS.is_dir(),
    reason=(
        "scripts/ is absent, so this is not a source checkout. The runtime image "
        "excludes it by design; this check runs on a developer checkout and in CI."
    ),
)


def producing_script(command: str) -> Path:
    """Return the script behind a `make evaluate-x` command."""

    target = command.removeprefix("make ").strip()
    return SCRIPTS / f"{target.replace('-', '_')}.py"


@pytest.mark.parametrize("name", sorted(ARTIFACTS))
def test_the_named_command_writes_the_artifact_the_endpoint_reads(name: str) -> None:
    """A published evaluation whose file nothing writes reports `not_run` forever."""

    relative, command, _ = ARTIFACTS[name]
    script = producing_script(command)
    assert script.is_file(), f"{name}: `{command}` maps to {script.name}, which does not exist"

    filename = Path(relative).name
    # The script, then the harness package it drives. A script that delegates
    # the write to `meridian_eval` is still a command that produces the file;
    # only a filename nothing anywhere writes is the defect being caught.
    searched = [script, *sorted(HARNESS.rglob("*.py"))]
    assert any(filename in path.read_text(encoding="utf-8") for path in searched), (
        f"{name}: the endpoint reads {relative}, but neither {script.name} nor the "
        f"evaluation harness ever mentions {filename}. Either nothing writes it -- "
        f"in which case the endpoint reports `not_run` permanently -- or the path "
        f"is stale."
    )


@pytest.mark.parametrize("name", sorted(ARTIFACTS))
def test_the_artifact_path_stays_inside_the_artifacts_directory(name: str) -> None:
    """The endpoint reads published results, not arbitrary repository files."""

    relative, _, _ = ARTIFACTS[name]
    path = Path(relative)
    assert not path.is_absolute(), f"{name}: {relative} is absolute"
    assert path.parts[0] == "artifacts", f"{name}: {relative} is outside artifacts/"
    assert ".." not in path.parts, f"{name}: {relative} escapes its directory"
