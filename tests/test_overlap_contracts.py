"""The two transformation contracts a literal engine can implement.

A literal replacement engine has to decide what happens when two matches share a
byte, and there are two self-consistent answers. Either a byte is consumed by at
most one match, or every match fires and the shared bytes are consumed once.

Both are defensible and the engines in this evaluation do not agree: measured on
500 real business emails under a policy of space-delimited common words, Aergia
reproduced the one-byte-one-match contract on 500 of 500 documents and Themis
reproduced it on 15. Themis was not corrupting anything - it was applying the
other contract.

This matters to the framework because validating an engine against the contract
it does not implement reports failures that are not failures, on almost every
document, as soon as a policy contains literals that can overlap.
"""
from __future__ import annotations

import unittest

from framework.policy.matching import (
    LiteralMatcher,
    apply_leftmost_longest,
    apply_overlap_aware,
)


def _apply(text: str, rules: dict[str, str]) -> tuple[str, str]:
    found = LiteralMatcher(rules).find_all(text)
    return (
        apply_leftmost_longest(text, found, rules),
        apply_overlap_aware(text, found, rules),
    )


class ContractsAgreeWhenNothingOverlapsTests(unittest.TestCase):
    """Disjoint matches are the common case, and both contracts must agree."""

    def test_single_match(self) -> None:
        one, every = _apply("a CUST-000123 b", {"CUST-000123": "[C]"})
        self.assertEqual(one, "a [C] b")
        self.assertEqual(every, one)

    def test_several_disjoint_matches(self) -> None:
        rules = {"alpha": "[A]", "beta": "[B]"}
        one, every = _apply("x alpha y beta z", rules)
        self.assertEqual(one, "x [A] y [B] z")
        self.assertEqual(every, one)

    def test_adjacent_but_not_overlapping(self) -> None:
        """Touching is not overlapping: no byte is shared."""

        rules = {"AAAA": "[P]", "BBBB": "[Q]"}
        one, every = _apply("x AAAABBBB y", rules)
        self.assertEqual(one, "x [P][Q] y")
        self.assertEqual(every, one)

    def test_no_match_leaves_text_alone(self) -> None:
        one, every = _apply("nothing here", {"absent": "[X]"})
        self.assertEqual(one, "nothing here")
        self.assertEqual(every, "nothing here")


class ContractsDivergeOnSharedBytesTests(unittest.TestCase):
    def test_partial_overlap(self) -> None:
        """The case the two engines answer differently.

        `ABCD` and `DEFG` share the `D`. One contract gives the shared byte to
        the first match and the second never fires; the other fires both.
        """
        rules = {"ABCD": "[P]", "DEFG": "[Q]"}
        one, every = _apply("x ABCDEFG y", rules)
        self.assertEqual(one, "x [P]EFG y")
        self.assertEqual(every, "x [P][Q] y")

    def test_shared_delimiter_between_words(self) -> None:
        """Why a policy of words overlaps constantly.

        Space-delimited rules must claim the spaces on both sides, so two
        reducible words in a row compete for the space between them. English is
        full of such pairs, which is why the contracts diverge on almost every
        sentence rather than on a rare edge case.
        """
        rules = {" to ": " ", " me ": " ", " be ": " "}
        one, every = _apply("There seem to me to be two questions", rules)
        self.assertEqual(one, "There seem me be two questions")
        self.assertEqual(every, "There seem    two questions")

    def test_overlap_aware_consumes_shared_input_once(self) -> None:
        """Both replacements are emitted; the shared bytes are not duplicated."""

        rules = {"ABCDEF": "[P]", "DEFGHI": "[Q]"}
        _one, every = _apply("x ABCDEFGHI y", rules)
        self.assertEqual(every, "x [P][Q] y")
        self.assertNotIn("GHI", every)


class ContainmentTests(unittest.TestCase):
    """A match wholly inside another is dropped under both contracts."""

    def test_same_start_longest_wins(self) -> None:
        rules = {"Elena Chen 1327": "[FULL]", "Elena Chen": "[PART]"}
        one, every = _apply("name: Elena Chen 1327, done", rules)
        self.assertEqual(one, "name: [FULL], done")
        self.assertEqual(every, one)

    def test_contained_in_the_middle(self) -> None:
        rules = {"abcdef": "[OUT]", "cd": "[IN]"}
        one, every = _apply("x abcdef y", rules)
        self.assertEqual(one, "x [OUT] y")
        self.assertEqual(every, one)


class DeterminismTests(unittest.TestCase):
    def test_result_does_not_depend_on_match_order(self) -> None:
        """Both contracts sort internally, so caller ordering cannot matter."""

        rules = {" to ": " ", " me ": " ", " be ": " "}
        text = "There seem to me to be two questions"
        found = LiteralMatcher(rules).find_all(text)
        for ordering in (found, list(reversed(found))):
            self.assertEqual(
                apply_leftmost_longest(text, ordering, rules),
                "There seem me be two questions",
            )
            self.assertEqual(
                apply_overlap_aware(text, ordering, rules),
                "There seem    two questions",
            )


if __name__ == "__main__":
    unittest.main()
