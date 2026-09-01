"""The browser's types must match what the API actually sends.

Three defects have now come from this seam, and none of them could fail a
type-checker on either side: TypeScript checked the browser's *assumption*
against itself, and Pydantic checked the server's model against itself. Nothing
compared the two.

* `Citation.signal` is `adverse | favorable | neutral`; the browser said
  `positive | negative | neutral`, so the evidence drawer's label rendered blank
  and every citation fell into the "other context" column.
* `Driver.direction` is `supports | opposes`; the browser said
  `positive | negative`, so every driver rendered as "raises risk".
* `Driver.feature` was read as `driver.name`, which is `undefined`.

The decision card is the exposed surface: the API serves it as
`dict[str, Any]`, so it has no OpenAPI schema for a generator to check. This
module parses `frontend/src/api.ts` and compares the field names and literal
unions it declares against the Pydantic models they mirror.

It is a text comparison, and that is a real limitation -- it checks names and
literals, not nesting or optionality. It catches the three defects above, which
is what it exists for.
"""

import re

import pytest
from pydantic import BaseModel

from meridian.contracts import (
    Citation,
    ConfidenceBreakdown,
    Driver,
    ForecastDecision,
    GuardrailDecision,
    InsufficientEvidenceDecision,
    MetricObservation,
    RequestedData,
    TraceEvent,
)
from meridian.data.paths import repository_root

API_CLIENT = repository_root() / "frontend" / "src" / "api.ts"

pytestmark = pytest.mark.skipif(
    not API_CLIENT.is_file(),
    reason="the browser client is absent; the runtime image excludes frontend/",
)

#: Browser type name -> the Pydantic model it mirrors. Only the models the
#: decision card and the run projection actually render: a type the browser
#: never receives cannot drift in a way anybody notices.
MIRRORED: dict[str, type[BaseModel]] = {
    "Citation": Citation,
    "Driver": Driver,
    "ConfidenceBreakdown": ConfidenceBreakdown,
    "MetricObservation": MetricObservation,
    "RequestedData": RequestedData,
    "ForecastDecision": ForecastDecision,
    "InsufficientEvidenceDecision": InsufficientEvidenceDecision,
    "GuardrailDecision": GuardrailDecision,
    "TraceEvent": TraceEvent,
}


def _declared_types(source: str) -> dict[str, str]:
    """Return each `export type Name = { ... }` body, keyed by name.

    Brace-matched rather than regex-spanned. A lazy `\{(.*?)\n\}` looks right
    and is wrong: a type written on one line has no closing brace on its own
    line, so the match runs on into the *next* declaration and attributes its
    fields to the wrong type. That is how this parser first reported
    `RequestedData` as declaring eighteen fields belonging to `ForecastDecision`.
    """

    declared: dict[str, str] = {}
    for match in re.finditer(r"export type (\w+) = \{", source):
        name = match.group(1)
        depth = 0
        start = match.end() - 1
        for index in range(start, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    declared[name] = source[start + 1 : index]
                    break
    return declared


def _fields(body: str) -> set[str]:
    """Return the field names a TypeScript object type declares.

    Only the body's own fields: a nested object literal is indented further, and
    matching it would attribute a child's fields to its parent.
    """

    single_line = set(re.findall(r"(?:^|[{;])\s*(\w+)\??:", body)) if "\n" not in body else set()
    return single_line or set(re.findall(r"^\s{2}(\w+)\??:", body, re.M))


def _literals(body: str, field: str) -> set[str]:
    """Return the string literals a field's union declares, if it is one."""

    match = re.search(rf"(?:^\s{{2}}|[{{;]\s*){field}\??:\s*([^\n;}}]+)", body, re.M)
    if match is None:
        return set()
    return set(re.findall(r"'([^']+)'", match.group(1)))


@pytest.fixture(scope="module")
def declared() -> dict[str, str]:
    """Return the browser's declared object types."""

    return _declared_types(API_CLIENT.read_text(encoding="utf-8"))


def test_the_client_declares_the_types_this_suite_checks(
    declared: dict[str, str],
) -> None:
    """Guard against the parse silently finding nothing."""

    assert len(declared) >= 15
    for name in MIRRORED:
        assert name in declared, f"the browser no longer declares {name}"


@pytest.mark.parametrize("name", sorted(MIRRORED))
def test_every_mirrored_type_declares_the_fields_the_model_sends(
    name: str, declared: dict[str, str]
) -> None:
    """A field the browser does not know about is a field it cannot render."""

    model = MIRRORED[name]
    sent = set(model.model_fields)
    known = _fields(declared[name])
    missing = sorted(sent - known)

    assert not missing, (
        f"{name} in api.ts is missing {missing}, which "
        f"{model.__name__} sends. The browser cannot render a field it has no name for."
    )


@pytest.mark.parametrize("name", sorted(MIRRORED))
def test_no_mirrored_type_invents_a_field_the_model_never_sends(
    name: str, declared: dict[str, str]
) -> None:
    """A field the API never sends is `undefined` at runtime, silently."""

    model = MIRRORED[name]
    sent = set(model.model_fields)
    invented = sorted(_fields(declared[name]) - sent)

    assert not invented, (
        f"{name} in api.ts declares {invented}, which {model.__name__} does not send. "
        "That reads as `undefined` in the browser with no error anywhere."
    )


#: The literal unions that have actually gone wrong, and their source of truth.
LITERAL_FIELDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Citation", "signal", ("adverse", "favorable", "neutral")),
    ("Driver", "direction", ("supports", "opposes")),
    ("ForecastDecision", "narrative_source", ("model", "deterministic")),
    ("ForecastDecision", "selected_by", ("linear", "tree_of_thought")),
)


@pytest.mark.parametrize(("type_name", "field", "expected"), LITERAL_FIELDS)
def test_literal_unions_match_the_vocabulary_the_api_sends(
    type_name: str, field: str, expected: tuple[str, ...], declared: dict[str, str]
) -> None:
    """The exact failure that made every driver render as "raises risk"."""

    body = declared[type_name]
    literals = _literals(body, field)

    if not literals:
        # The field is declared as a named alias rather than an inline union;
        # resolve the alias's own definition.
        alias = re.search(rf"^\s{{2}}{field}\??:\s*(\w+)$", body, re.M)
        assert alias, f"{type_name}.{field} is neither a literal union nor an alias"
        source = API_CLIENT.read_text(encoding="utf-8")
        definition = re.search(rf"export type {alias.group(1)} =([^\n]+)", source)
        assert definition, f"{alias.group(1)} is not declared in api.ts"
        literals = set(re.findall(r"'([^']+)'", definition.group(1)))

    assert literals == set(expected), (
        f"{type_name}.{field} declares {sorted(literals)}; the API sends {sorted(expected)}"
    )


def test_the_review_case_type_knows_about_requested_data(
    declared: dict[str, str],
) -> None:
    """The stored case carries what a reviewer asked for; the queue should show it."""

    assert "requested_data" in _fields(declared["ReviewCase"])
