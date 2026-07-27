"""_normalize_expected_replacements truncates replacements at their ACTUAL
positions, not with a global str.replace (findings 016 item 6).

A global replace also truncates a replacement token that happens to appear as
ordinary document text. The positional walk (matches are ordered, and the
expected output contains their replacements in that order) truncates only the
real replacements and leaves coincidental text alone.
"""
from __future__ import annotations

import unittest

from framework.cli.main import _normalize_expected_replacements


class NormalizeTruncationTests(unittest.TestCase):
    def test_common_case_matches_global_replace(self) -> None:
        # Every occurrence is a real replacement -> same as the old behaviour.
        msg = "a [TOKEN_LONG] b [TOKEN_LONG] c"
        matches = [{"replacement": "[TOKEN_LONG]"}, {"replacement": "[TOKEN_LONG]"}]
        self.assertEqual(
            _normalize_expected_replacements(msg, matches, 5),
            "a [TOKE b [TOKE c",
        )

    def test_ordinary_text_token_is_not_truncated(self) -> None:
        # Two occurrences of the token, but only ONE is a real replacement (one
        # match). The other is ordinary document text and must survive intact.
        msg = "real [TOKEN_LONG] then literal [TOKEN_LONG] in prose"
        matches = [{"replacement": "[TOKEN_LONG]"}]  # only the first is a replacement
        out = _normalize_expected_replacements(msg, matches, 5)
        self.assertEqual(out, "real [TOKE then literal [TOKEN_LONG] in prose")
        # The old global replace would have truncated the second one too:
        self.assertIn("[TOKEN_LONG] in prose", out)

    def test_no_max_length_is_identity(self) -> None:
        msg = "x [TOKEN_LONG] y"
        self.assertEqual(_normalize_expected_replacements(msg, [{"replacement": "[TOKEN_LONG]"}], None), msg)

    def test_no_matches_is_identity(self) -> None:
        msg = "text that happens to contain [TOKEN_LONG] as prose"
        self.assertEqual(_normalize_expected_replacements(msg, [], 5), msg)

    def test_short_replacement_untouched(self) -> None:
        # A replacement already within the limit is unchanged.
        msg = "a [X] b"
        self.assertEqual(_normalize_expected_replacements(msg, [{"replacement": "[X]"}], 15), msg)


if __name__ == "__main__":
    unittest.main()
