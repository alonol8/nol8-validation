"""Independent literal-replacement oracle.

The engines (Themis, Aergia) do deterministic literal replacement. To adjudicate
whether an engine's output is CORRECT — not merely plausible — we need the one
correct answer computed independently of either engine. That answer is:
leftmost-longest, non-overlapping literal replacement, applied byte-for-byte.

This is the oracle. It reuses the framework's Aho-Corasick matcher (written and
tested for corpus validation, so it did not learn the answer from any engine),
and lives here so every caller shares ONE parser and ONE oracle rather than
each reimplementing a substring approximation.

  engine output == oracle output  -> correct
  engine output != oracle output  -> a real defect (wrong position, corrupted
                                     surrounding text, inserted content, a missed
                                     or duplicated replacement) — a substring
                                     check cannot see any of these.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from .matching import LiteralMatcher, resolve_non_overlapping

# "literal" -> "replacement";  (both strings may contain \" and \\ escapes)
_RULE = re.compile(r'^"((?:[^"\\]|\\.)*)"\s*->\s*"((?:[^"\\]|\\.)*)";\s*$')


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\\\", "\\")


def parse_policy(path: Path) -> dict[str, str]:
    """Parse a literal .nol policy into {literal: replacement}.

    Full-line `#` comments and blank lines are ignored. A trailing inline comment
    after a rule is a parse error in the real engine, so we treat it as one here.

    A literal appearing twice is an error, not a silent last-wins overwrite: the
    engine's own resolution of a duplicated literal is undefined, so a policy that
    contains one cannot be adjudicated. We collect every duplicate and raise with
    all of them, rather than dropping the earlier rules quietly.
    """
    rules: dict[str, str] = {}
    seen_line: dict[str, int] = {}
    dupes: list[str] = []
    for lineno, raw in enumerate(Path(path).read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _RULE.match(line)
        if not m:
            raise ValueError(f"{path}:{lineno}: not a rule: {raw!r}")
        literal = _unescape(m.group(1))
        if literal in rules:
            dupes.append(f"{path}:{lineno}: duplicate literal {literal!r} "
                         f"(first at line {seen_line[literal]})")
            continue
        rules[literal] = _unescape(m.group(2))
        seen_line[literal] = lineno
    if dupes:
        raise ValueError("duplicate literals in policy:\n  " + "\n  ".join(dupes))
    return rules


def build_matcher(rules: dict[str, str]) -> LiteralMatcher:
    """Aho-Corasick automaton over the policy's literals."""
    return LiteralMatcher(rules.keys())


def oracle_output(text: str, matcher: LiteralMatcher, rules: dict[str, str]) -> str:
    """Correct literal-replacement output: leftmost-longest, non-overlapping."""
    selected = resolve_non_overlapping(matcher.find_all(text))
    out: list[str] = []
    cursor = 0
    for match in selected:
        out.append(text[cursor:match.start])
        out.append(rules[match.literal])
        cursor = match.end
    out.append(text[cursor:])
    return "".join(out)


def substring_pass(processed: str, pairs: Sequence[tuple[str, str]]) -> bool:
    """The WEAK correctness check the oracle replaces: for every in-scope
    (literal, token) pair, the literal is gone and the token appears somewhere.

    It is vacuously true when nothing is in scope, and blind to position,
    corruption of the surrounding text, and inserted content — so it can report
    "correct" for output the oracle rejects. Exposed only so the POC can show
    where the two verdicts diverge, and so that divergence is a tested property.
    """
    return all(lit not in processed and tok in processed for lit, tok in pairs)
