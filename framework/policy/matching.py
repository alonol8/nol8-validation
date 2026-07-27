"""Multi-pattern literal matching over documents.

The validation framework needs to answer two questions about a document that a
per-rule scan cannot answer efficiently:

1. Which catalog literals occur in it? Computing expected output from only the
   rules the generator *intended* to inject is wrong - unrelated generated
   values collide with catalog literals in practice.
2. Do any of those matches overlap? Overlapping matches trigger ISSUE-004, so
   a corpus containing them cannot produce trustworthy validation results.

A naive scan is O(rules x documents): 5,000 rules over 10,000 documents is 50
million substring searches. Aho-Corasick finds every occurrence of every
literal in a single pass over each document, after one build of the automaton.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class Match:
    """One literal occurrence, as a half-open byte range [start, end)."""

    start: int
    end: int
    literal: str

    @property
    def length(self) -> int:
        return self.end - self.start


class LiteralMatcher:
    """Aho-Corasick automaton over a fixed set of literals.

    Build once per catalog, then scan many documents.
    """

    __slots__ = ("_goto", "_fail", "_output", "_literal_count")

    def __init__(self, literals: Iterable[str]) -> None:
        # Node 0 is the root. _goto[node] maps character -> node.
        self._goto: list[dict[str, int]] = [{}]
        # Literals terminating at each node.
        self._output: list[list[str]] = [[]]
        unique = {literal for literal in literals if literal}
        self._literal_count = len(unique)

        for literal in sorted(unique):
            node = 0
            for character in literal:
                next_node = self._goto[node].get(character)
                if next_node is None:
                    next_node = len(self._goto)
                    self._goto.append({})
                    self._output.append([])
                    self._goto[node][character] = next_node
                node = next_node
            self._output[node].append(literal)

        self._fail: list[int] = [0] * len(self._goto)
        queue: deque[int] = deque()
        for node in self._goto[0].values():
            queue.append(node)
        while queue:
            node = queue.popleft()
            for character, target in self._goto[node].items():
                queue.append(target)
                fallback = self._fail[node]
                while fallback and character not in self._goto[fallback]:
                    fallback = self._fail[fallback]
                self._fail[target] = (
                    self._goto[fallback].get(character, 0)
                    if fallback or character in self._goto[0]
                    else 0
                )
                if self._fail[target] == target:
                    self._fail[target] = 0
                # Inherit outputs so a literal contained in another is still
                # reported at every position where it occurs.
                self._output[target].extend(self._output[self._fail[target]])

    def __len__(self) -> int:
        return self._literal_count

    def find_all(self, text: str) -> list[Match]:
        """Every occurrence of every literal, ordered by start then length."""
        matches: list[Match] = []
        node = 0
        for index, character in enumerate(text):
            while node and character not in self._goto[node]:
                node = self._fail[node]
            node = self._goto[node].get(character, 0)
            if self._output[node]:
                end = index + 1
                for literal in self._output[node]:
                    matches.append(Match(end - len(literal), end, literal))
        matches.sort(key=lambda match: (match.start, -match.length))
        return matches


def overlapping_matches(matches: Sequence[Match]) -> list[tuple[Match, Match]]:
    """Pairs of matches that share at least one character.

    Adjacency is not overlap: a match ending at index n and another starting at
    index n share no characters, and Themis renders that correctly.
    """
    ordered = sorted(matches, key=lambda match: (match.start, match.end))
    pairs: list[tuple[Match, Match]] = []
    for index, current in enumerate(ordered):
        for other in ordered[index + 1:]:
            if other.start >= current.end:
                break  # ordered by start, so nothing later can overlap either
            pairs.append((current, other))
    return pairs


def resolve_non_overlapping(matches: Sequence[Match]) -> list[Match]:
    """Leftmost-longest selection of non-overlapping matches.

    One of two transformation contracts a literal engine can implement, and the
    one where a byte of input is consumed by at most one match. Where matches do
    not overlap, both contracts agree and this is simply the correct answer.

    See `apply_overlap_aware` for the other. An engine that overlaps must be
    adjudicated against BOTH contracts (Themis reproduces every-match-fires,
    Aergia reproduces one-byte-one-match); validating either engine against a
    single contract reports failures that are not failures.
    """
    selected: list[Match] = []
    cursor = 0
    for match in sorted(matches, key=lambda item: (item.start, -item.length)):
        if match.start < cursor:
            continue
        selected.append(match)
        cursor = match.end
    return selected


# ---------------------------------------------------------------------------
# Two transformation contracts. PORTED from Alon's PR (framework/policy/
# matching.py, apply_leftmost_longest / apply_overlap_aware) so the customer-
# facing surfaces can adjudicate against both without waiting on the merge.
# These should collapse to his versions when the PR lands; do not diverge them.
# ---------------------------------------------------------------------------
def apply_leftmost_longest(
    text: str, matches: Sequence[Match], replacements: Mapping[str, str]
) -> str:
    """Transform `text` under the one-byte-one-match contract (Aergia's)."""
    out: list[str] = []
    cursor = 0
    for match in resolve_non_overlapping(matches):
        out.append(text[cursor:match.start])
        out.append(replacements[match.literal])
        cursor = match.end
    out.append(text[cursor:])
    return "".join(out)


def apply_overlap_aware(
    text: str, matches: Sequence[Match], replacements: Mapping[str, str]
) -> str:
    """Transform `text` under the every-match-fires contract (Themis's).

    A match whose start has already been consumed by an earlier one still fires:
    it emits its full replacement, and only the input bytes not already consumed
    are taken. Matches fully contained in an earlier one are dropped.

    The two contracts agree whenever matches are disjoint and diverge whenever
    they share a byte. Overlaps are rare in a policy of identifiers (this
    framework's generator excludes them) but unavoidable in a policy of
    space-delimited words, where " of " and " the " both want a shared space.
    Neither contract is wrong in the abstract; they are different definitions of
    what a literal replacement engine does.
    """
    out: list[str] = []
    cursor = 0
    # Start ascending, end descending: at a shared start the longest match leads,
    # so shorter ones sharing it fall to the contained-drop rule below.
    for match in sorted(matches, key=lambda item: (item.start, -item.end)):
        if match.end <= cursor:
            continue  # wholly inside a match already applied
        if match.start >= cursor:
            out.append(text[cursor:match.start])
        out.append(replacements[match.literal])
        cursor = match.end
    out.append(text[cursor:])
    return "".join(out)
