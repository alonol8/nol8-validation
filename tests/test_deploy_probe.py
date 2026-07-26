"""The DP4 deploy probe picks a literal UNIQUE to the just-deployed policy so a
stale policy cannot pass, and reports the set-difference size so an empty diff
surfaces as a finding. These tests pin that selection logic (the network call is
exercised live, not here).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demos" / "benchmark" / "datapoint4"))
from deploy_probe import probe_plan  # noqa: E402


class ProbePlanTests(unittest.TestCase):
    def test_prefers_a_literal_unique_to_current(self) -> None:
        prev = {"aaaa": "[A]", "bbbb": "[B]"}
        cur = {"aaaa": "[A]", "bbbb": "[B]", "cccc": "[C]"}
        lit, tok, new_count = probe_plan(cur, prev)
        # Must pick the literal that prev never had — the whole point of staleness detection.
        self.assertEqual(lit, "cccc")
        self.assertEqual(tok, "[C]")
        self.assertEqual(new_count, 1)

    def test_no_prev_falls_back_to_any_literal(self) -> None:
        cur = {"zzz": "[Z]", "yy": "[Y]"}
        lit, tok, new_count = probe_plan(cur, {})
        # First cell: everything is "new vs nothing"; still returns a usable literal.
        self.assertIn(lit, cur)
        self.assertEqual(tok, cur[lit])
        self.assertEqual(new_count, 2)

    def test_empty_diff_is_reported_and_still_probes(self) -> None:
        # A later cell whose ruleset did not change from the previous one: the
        # difference is 0 (the finding), but we still probe with some literal.
        cur = {"aaaa": "[A]", "bbbb": "[B]"}
        lit, tok, new_count = probe_plan(cur, dict(cur))
        self.assertEqual(new_count, 0)
        self.assertIn(lit, cur)

    def test_empty_policy_returns_none(self) -> None:
        lit, tok, new_count = probe_plan({}, {})
        self.assertIsNone(lit)
        self.assertIsNone(tok)
        self.assertEqual(new_count, 0)

    def test_selection_is_deterministic(self) -> None:
        cur = {"mmmm": "[M]", "cc": "[C]", "dd": "[D]"}
        # shortest-then-lexicographic: "cc" beats "dd" (same length) and "mmmm".
        self.assertEqual(probe_plan(cur, {})[0], "cc")


if __name__ == "__main__":
    unittest.main()
