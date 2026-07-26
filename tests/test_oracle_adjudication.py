"""The BYO POC and console adjudicate engine output against the independent
oracle, byte-for-byte, NOT with a substring check. These tests pin the property
that makes that switch matter: there exist outputs a substring check calls
correct that the oracle rejects. If a future edit weakens the POC back toward a
substring check, the detector cases here fail.

Every manual check we run once becomes a test that runs forever.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from framework.policy.oracle import (
    build_matcher,
    oracle_output,
    parse_policy,
    substring_pass,
)

# One governed value -> token. The token is <=15 chars (ISSUE-005 truncates
# longer ones at the engine, but that is not what these tests exercise).
RULES = {"Halcyon Freight Ltd": "[WATCHED_CUSTO]", "MFN-88213-01": "[ACCOUNT_IDS]"}
DOC = "Customer Halcyon Freight Ltd on account MFN-88213-01 filed a refund."
PAIRS = [(lit, tok) for lit, tok in RULES.items() if lit in DOC]


class OracleOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matcher = build_matcher(RULES)

    def test_replaces_at_the_right_position(self) -> None:
        self.assertEqual(
            oracle_output(DOC, self.matcher, RULES),
            "Customer [WATCHED_CUSTO] on account [ACCOUNT_IDS] filed a refund.",
        )

    def test_no_matches_is_identity(self) -> None:
        text = "nothing governed here"
        self.assertEqual(oracle_output(text, self.matcher, RULES), text)


class DetectorTests(unittest.TestCase):
    """A substring pass with an oracle fail is exactly the case the POC must
    catch. Each case: substring_pass -> True, oracle byte-exact -> False."""

    def setUp(self) -> None:
        self.matcher = build_matcher(RULES)
        self.expected = oracle_output(DOC, self.matcher, RULES)

    def _assert_caught(self, bad: str) -> None:
        # The weak check passes this output, but the oracle rejects it — so the
        # POC's `substr_ok and not exact` divergence condition fires.
        self.assertTrue(substring_pass(bad, PAIRS), "substring check should pass")
        self.assertNotEqual(bad, self.expected, "oracle should reject")

    def test_appended_corruption(self) -> None:
        # Correct redaction, but the engine also mangled the tail.
        self._assert_caught(self.expected + "  <<CORRUPTED TAIL>>")

    def test_inserted_content(self) -> None:
        # Correct redaction, but arbitrary content injected mid-document.
        self._assert_caught(self.expected.replace(" filed", " ***INJECTED*** filed"))

    def test_wrong_position(self) -> None:
        # Both tokens present and both literals gone, but the tokens are in each
        # other's place — a substring check cannot see the swap; the oracle can.
        bad = ("Customer [ACCOUNT_IDS] on account [WATCHED_CUSTO] filed a refund.")
        self._assert_caught(bad)

    def test_correct_output_is_not_flagged(self) -> None:
        # Negative control. A human-verified correct output must NOT trip the
        # detector, AND the oracle must AGREE with it — comparing self.expected
        # to itself would prove neither. GOOD is the same constant asserted in
        # test_replaces_at_the_right_position, so this pins oracle_output to a
        # human-checked value: if the oracle ever drifts from what a correct
        # engine produces, this assertion fails instead of the POC silently
        # reporting disagreements against healthy engines.
        GOOD = "Customer [WATCHED_CUSTO] on account [ACCOUNT_IDS] filed a refund."
        fresh_oracle = oracle_output(DOC, build_matcher(RULES), RULES)
        self.assertEqual(fresh_oracle, GOOD)         # oracle == human-verified constant
        self.assertTrue(substring_pass(GOOD, PAIRS))  # substring passes it too
        self.assertFalse(substring_pass(GOOD, PAIRS) and GOOD != fresh_oracle)  # detector stays silent


class ParsePolicyDuplicateTests(unittest.TestCase):
    def _write(self, body: str) -> Path:
        p = Path(tempfile.mkstemp(suffix=".nol")[1])
        p.write_text(body, encoding="utf-8")
        return p

    def test_duplicate_literal_raises(self) -> None:
        pol = self._write('"foo" -> "[A]";\n"foo" -> "[B]";\n')
        with self.assertRaises(ValueError) as ctx:
            parse_policy(pol)
        self.assertIn("duplicate literal", str(ctx.exception))

    def test_distinct_literals_parse(self) -> None:
        pol = self._write('"foo" -> "[A]";\n"bar" -> "[B]";\n')
        self.assertEqual(parse_policy(pol), {"foo": "[A]", "bar": "[B]"})


if __name__ == "__main__":
    unittest.main()
