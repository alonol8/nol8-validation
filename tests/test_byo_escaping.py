"""render_policy must escape backslashes, not just quotes (findings 016 item 1).

A customer value containing a backslash (a Windows path, anything with escaped
content) must round-trip: render_policy -> .nol rule -> parse_policy recovers the
original value byte-for-byte. Escaping quotes only emitted a malformed rule and
the value was silently counted out of scope. This pins the round-trip.
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from framework.policy.oracle import parse_policy

# byo_poc.py lives in a hyphenated dir (not an importable package name), so load
# it by path to exercise the real render_policy / _escape_literal.
_BYO_PATH = Path(__file__).resolve().parents[1] / "demos/showcase/byo-poc/byo_poc.py"
_spec = importlib.util.spec_from_file_location("byo_poc_under_test", _BYO_PATH)
byo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(byo)


class RenderEscapingTests(unittest.TestCase):
    def _round_trip(self, value: str) -> None:
        # Render a one-value policy, parse it back, assert the literal is recovered.
        cats = [("[T]", "Cat", [value])]
        policy_text = byo.render_policy(cats)
        p = Path(tempfile.mkstemp(suffix=".nol")[1])
        p.write_text(policy_text, encoding="utf-8")
        rules = parse_policy(p)
        self.assertIn(value, rules, f"{value!r} did not survive render->parse; got {list(rules)!r}")
        self.assertEqual(rules[value], "[T]")

    def test_backslash_round_trips(self) -> None:
        self._round_trip(r"C:\Users\acme\secret.txt")

    def test_quote_round_trips(self) -> None:
        self._round_trip('he said "hello"')

    def test_backslash_and_quote_together(self) -> None:
        self._round_trip(r'path\to\"quoted"')

    def test_trailing_backslash(self) -> None:
        self._round_trip("share\\")

    def test_escape_order_is_backslash_then_quote(self) -> None:
        # The specific bug: a lone backslash must become \\ (not be left bare,
        # which would make the following char an escape and corrupt the rule).
        self.assertEqual(byo._escape_literal("a\\b"), "a\\\\b")
        self.assertEqual(byo._escape_literal('a"b'), 'a\\"b')


if __name__ == "__main__":
    unittest.main()
