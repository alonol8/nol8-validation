"""The DP4 deploy probe picks literals UNIQUE to the just-deployed policy, skips
any that collide (as substrings) with the previous policy, spreads across the new
set, and adjudicates the response BYTE-FOR-BYTE against the oracle. These tests pin
the selection logic and the reason byte-for-byte replaced the substring check (the
stale-substring exploit from review/findings/006). The network call is exercised
live, not here.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demos" / "benchmark" / "datapoint4"))
from deploy_probe import probe_plan  # noqa: E402
from framework.policy.oracle import build_matcher, oracle_output, substring_pass  # noqa: E402


class ProbePlanTests(unittest.TestCase):
    def test_prefers_literals_unique_to_current(self) -> None:
        prev = {"aaaa": "[A]", "bbbb": "[B]"}
        cur = {"aaaa": "[A]", "bbbb": "[B]", "cccc": "[C]", "dddd": "[D]"}
        picks, new_count = probe_plan(cur, prev, count=4)
        self.assertEqual(new_count, 2)
        lits = {lit for lit, _ in picks}
        self.assertTrue(lits <= {"cccc", "dddd"})       # only unique-to-N literals
        self.assertTrue(all(cur[lit] == tok for lit, tok in picks))

    def test_skips_substring_collision_with_prev(self) -> None:
        # prev holds "1000020"; a probe literal that contains it could be partially
        # matched by the stale policy — exactly the finding-006 exploit. Skip it.
        prev = {"1000020": "[X]"}
        cur = {"1000020": "[X]", "100002023": "[Y]", "77": "[P]", "88": "[Q]"}
        picks, _ = probe_plan(cur, prev, count=4)
        lits = {lit for lit, _ in picks}
        self.assertNotIn("100002023", lits)             # collides with prev "1000020"
        self.assertTrue(lits <= {"77", "88"})

    def test_multi_literal_spread(self) -> None:
        cur = {f"lit{n:02d}": f"[{n}]" for n in range(10)}
        picks, _ = probe_plan(cur, {}, count=4)
        self.assertEqual(len(picks), 4)
        self.assertEqual(len({lit for lit, _ in picks}), 4)  # distinct

    def test_single_count_picks_longest(self) -> None:
        cur = {"mmmm": "[M]", "cc": "[C]", "dddddd": "[D]"}
        picks, _ = probe_plan(cur, {}, count=1)
        self.assertEqual(picks, [("dddddd", "[D]")])     # longest, least collision-prone

    def test_no_prev_falls_back_to_any(self) -> None:
        cur = {"zzz": "[Z]", "yy": "[Y]"}
        picks, new_count = probe_plan(cur, {}, count=4)
        self.assertEqual(new_count, 2)
        self.assertEqual({lit for lit, _ in picks}, {"zzz", "yy"})

    def test_empty_policy_returns_nothing(self) -> None:
        picks, new_count = probe_plan({}, {}, count=4)
        self.assertEqual(picks, [])
        self.assertEqual(new_count, 0)


class ByteForByteDefeatsStaleSubstringTests(unittest.TestCase):
    """The finding-006 exploit: a stale policy whose literal is a substring of the
    probe literal, with a token sharing the 15-char prefix, passes a substring check
    but must fail byte-for-byte."""

    def test_stale_substring_passes_substring_but_fails_oracle(self) -> None:
        cur = {"100002023": "[FIN:ROUTING_NUMBER]"}
        doc = "deploy probe: 100002023 .end"
        pairs = [("100002023", "[FIN:ROUTING_NUMBER]")]
        expected = oracle_output(doc, build_matcher(cur), cur)
        # A stale policy holding "1000020" -> a token sharing the 15-char prefix
        # produces the token plus a leftover "23" fragment.
        stale_resp = "deploy probe: [FIN:ROUTING_NUMBER]23 .end"
        # The OLD substring check PASSES this stale output (literal absent, token
        # present) — that is the danger finding-006 identified.
        self.assertTrue(substring_pass(stale_resp, pairs))
        # Byte-for-byte REJECTS it — the whole document does not equal the oracle.
        self.assertNotEqual(stale_resp, expected)
        # And the correct output would pass byte-for-byte.
        self.assertEqual(expected, "deploy probe: [FIN:ROUTING_NUMBER] .end")


if __name__ == "__main__":
    unittest.main()
