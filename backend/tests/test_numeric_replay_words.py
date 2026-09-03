"""Numeric replay reads number words, not only numerals (plan section 16.4).

Section 16.4 replays every number a narrative states against the values the
system actually computed. Until now the replay recognised numerals only, so a
sentence that wrote "five of six drivers" instead of "5 of 6" made the same
claim and escaped the same check.

The vocabulary is deliberately bounded, and `one` and `zero` are deliberately
read only inside a ratio. Every occurrence of those two words in this project's
own generated text is idiomatic -- "quick one for the support team", "roughly
one quarter out", "stuck near zero" -- so reading them as counts everywhere
would fail sound narratives on English usage rather than on arithmetic. The
tests below hold both halves of that: the claims are caught, and the idioms are
not.
"""

import pytest

from meridian.agents.forecast_adjudicator import (
    is_verified,
    written_number_words,
    written_numbers,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("five of six drivers point the same way", (5.0, 6.0)),
        ("one of six drivers", (1.0, 6.0)),
        ("zero of four escalations closed", (0.0, 4.0)),
        ("5 of six drivers", (6.0,)),
        ("five of 6 drivers", (5.0,)),
        ("twelve open tickets", (12.0,)),
        ("twenty-one escalations in the window", (21.0,)),
        ("twenty one escalations in the window", (21.0,)),
        ("ninety-nine accounts", (99.0,)),
        ("thirty accounts renewed", (30.0,)),
    ],
)
def test_a_claim_written_as_words_is_read_as_a_number(
    text: str, expected: tuple[float, ...]
) -> None:
    """The whole point: a spelled-out count is still a count."""

    assert written_number_words(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Quick one for the support team",
        "timeline is roughly one quarter out",
        "the evidence required to support one was not available",
        "Rank our CSMs and tell me which one to fire",
        "Adoption is stuck near zero",
        "no one has reviewed this account",
    ],
)
def test_the_idiomatic_uses_of_one_and_zero_are_not_claims(text: str) -> None:
    """Every one of these is drawn from this project's own generated text."""

    assert written_number_words(text) == ()


@pytest.mark.parametrize(
    "text",
    [
        "ACC-1042 and KB-0007 at P1",
        "the outcome was Renewed",
        "someone confirmed the renewal",
        "the tone was neutral",
    ],
)
def test_identifiers_and_ordinary_prose_state_no_numbers(text: str) -> None:
    """A word merely containing a number word is not a number.

    "someone" contains "one" and "neutral" does not, but both must come back
    empty: the first because the word boundary excludes it, the second because
    it was never a candidate.
    """

    assert written_number_words(text) == ()


def test_the_two_written_forms_replay_identically() -> None:
    """The regression this exists to prevent."""

    words = written_numbers("five of six drivers point the same way")
    numerals = written_numbers("5 of 6 drivers point the same way")
    assert sorted(words) == sorted(numerals) == [5.0, 6.0]


def test_a_spelled_out_fabrication_is_now_caught() -> None:
    """A number the system never computed fails the replay in either form."""

    allowed = [5.0, 6.0]
    assert all(is_verified(value, allowed) for value in written_numbers("five of six"))
    assert not all(is_verified(value, allowed) for value in written_numbers("eleven of twelve"))


def test_a_word_read_as_half_of_a_ratio_is_not_counted_twice() -> None:
    """`five of six` yields two values, not four."""

    assert written_number_words("five of six") == (5.0, 6.0)
    assert len(written_numbers("five of six")) == 2
