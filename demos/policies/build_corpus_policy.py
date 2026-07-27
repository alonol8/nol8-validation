#!/usr/bin/env python3
"""Build a token-reduction policy from the words a corpus actually contains.

The hand-written vocabulary in `framework/policy/word_reduction.py` is a guess
about what business text looks like, and on real English it earns 0.3 matches/KB
in its conservative form: correct, and almost never fired. A policy derived from
the corpus it will run against does not have to guess.

Two sources of rules, and they behave differently:

**Known-safe vocabulary, ranked by what it earns here.** The curated tables say
which substitutions are safe; the corpus says which are worth their place. A rule
that never fires costs deploy capacity and buys nothing, so entries below a
contribution threshold are left out rather than shipped for completeness.

**Boilerplate discovered in the corpus itself.** The phrases a body of writing
repeats - sign-offs, disclaimers, standing instructions - are formulaic by
definition and carry nothing a retrieval index needs. These are the entries no
hand-written table could contain, because they are specific to the customer.
The selection signal is *document* frequency, not raw count: a phrase repeated
across thousands of different documents is a formula, while one repeated inside a
single document is that document's content.

    python demos/policies/build_corpus_policy.py \\
        --corpus demos/benchmark/datapoint4/results/enron.jsonl \\
        --target-density 30 --out demos/policies/enron-reduction.nol

Rules are space-delimited throughout - the engine matches substrings and has no
notion of a word, so an undelimited " the " fires inside "theme". Negations are
never removed: a model repairs broken grammar from context and cannot recover a
"not" that was deleted.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from framework.policy.matching import (  # noqa: E402
    LiteralMatcher,
    apply_leftmost_longest,
)
from framework.policy.word_reduction import reduction_rules  # noqa: E402

MAX_REPLACEMENT_LENGTH = 15

# Never removed or rewritten, whatever the corpus statistics say. Deleting a
# negation does not shorten a sentence, it reverses it.
PROTECTED = frozenset({
    "not", "no", "nor", "never", "none", "cannot", "without", "except",
    "unless", "neither", "only",
})

_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")


def load_documents(path: Path, limit: int | None = None) -> list[str]:
    documents: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        text = record.get("message") or record.get("text")
        if isinstance(text, str) and text.strip():
            documents.append(text)
        if limit and len(documents) >= limit:
            break
    if not documents:
        raise SystemExit(f"no documents found in {path}")
    return documents


# ---------------------------------------------------------------- boilerplate

def frequent_phrases(
    documents: list[str],
    min_document_fraction: float,
    min_words: int,
    max_words: int,
) -> dict[tuple[str, ...], int]:
    """Word sequences appearing in at least `min_document_fraction` of documents.

    Grown a level at a time: an n-gram can only be frequent if its leading
    (n-1)-gram is, so each level only counts extensions of what survived the
    last. Without that, counting every 8-gram in a 36 MB corpus means tens of
    millions of distinct keys.
    """
    threshold = max(2, int(len(documents) * min_document_fraction))
    # Split on whitespace and keep punctuation attached, so a phrase rebuilt
    # with single spaces is a literal substring of the text it came from. A
    # word regex would strip the full stop off "details." and produce a rule
    # that never fires - the policy has to match the corpus exactly as written.
    tokenised = [doc.lower().split() for doc in documents]

    frequent: dict[tuple[str, ...], int] = {}
    previous: set[tuple[str, ...]] = set()

    for size in range(min_words, max_words + 1):
        counts: Counter[tuple[str, ...]] = Counter()
        for words in tokenised:
            if len(words) < size:
                continue
            # Once per document: we are measuring how many documents share a
            # phrase, not how often one document repeats it.
            seen: set[tuple[str, ...]] = set()
            for index in range(len(words) - size + 1):
                gram = tuple(words[index:index + size])
                if size > min_words and gram[:-1] not in previous:
                    continue
                if gram in seen:
                    continue
                seen.add(gram)
                counts[gram] += 1
        surviving = {gram: n for gram, n in counts.items() if n >= threshold}
        if not surviving:
            break
        frequent.update(surviving)
        previous = set(surviving)

    return frequent


# A longer phrase only supersedes a shorter one it contains when it occurs
# nearly as often. Length alone is the wrong test: "please let me know if you
# have any questions" in 68% of documents should not be displaced by a 16-word
# window around it that appears in 2%, and a rule that fires 2% of the time
# removes almost nothing however long it is.
_SUPERSEDE_RATIO = 0.8


def maximal_phrases(frequent: dict[tuple[str, ...], int]) -> list[tuple[str, int]]:
    """Keep the longest form of each phrase that is still about as common."""

    by_length = sorted(frequent, key=len, reverse=True)
    kept: list[tuple[str, ...]] = []
    for gram in by_length:
        joined = " ".join(gram)
        superseded = any(
            joined in " ".join(longer)
            and frequent[longer] >= frequent[gram] * _SUPERSEDE_RATIO
            for longer in kept
        )
        if not superseded:
            kept.append(gram)
    return [(" ".join(gram), frequent[gram]) for gram in kept]


# ---------------------------------------------------------------- selection

def occurrences_per_kb(text: str, literal: str, kilobytes: float) -> float:
    return text.count(literal) / kilobytes if kilobytes else 0.0


_OVERLAP_WINDOW = 4


def _windows(literal: str) -> set[tuple[str, ...]]:
    """The word windows a phrase covers, for detecting near-duplicate rules.

    Empty for anything shorter than the window, so single words and short
    substitutions are never suppressed by this - they overlap everything and
    suppressing them would remove the vocabulary the phrases sit in.
    """
    words = literal.split()
    if len(words) < _OVERLAP_WINDOW:
        return set()
    return {
        tuple(words[index:index + _OVERLAP_WINDOW])
        for index in range(len(words) - _OVERLAP_WINDOW + 1)
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    # Rules are ranked by bytes removed, so a stopping condition expressed in
    # match density stops on a different quantity than the one being optimised:
    # " the " alone is 23 matches/KB, so a density target is met by a handful of
    # common words before any discovered phrase is reached. Rule count is the
    # honest default; the two targets are there when a run needs a specific
    # shape - density for a benchmark corpus, reduction for a deployment.
    parser.add_argument("--max-rules", type=int, default=500)
    parser.add_argument("--target-density", type=float, default=None,
                        help="stop once the corpus reaches this many matches/KB")
    parser.add_argument("--target-reduction", type=float, default=None,
                        help="stop once projected byte reduction reaches this %%")
    parser.add_argument("--sample", type=int, default=4000,
                        help="documents sampled for phrase discovery")
    parser.add_argument("--phrase-doc-fraction", type=float, default=0.02,
                        help="a phrase must appear in this fraction of documents")
    parser.add_argument("--min-phrase-words", type=int, default=3)
    parser.add_argument("--max-phrase-words", type=int, default=16,
                        help="a formula shorter than the cap is captured by one "
                             "rule; one longer than it arrives as overlapping "
                             "windows, and only the first survives de-duplication")
    parser.add_argument("--min-per-kb", type=float, default=0.05,
                        help="drop rules contributing less than this; a rule "
                             "that never fires costs capacity and buys nothing")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    documents = load_documents(args.corpus)
    text = "\n".join(documents)
    lowered = text.lower()
    kilobytes = len(text.encode("utf-8")) / 1024
    print(f"Corpus: {args.corpus.name} - {len(documents)} documents, "
          f"{kilobytes / 1024:.1f} MB")

    sample = documents
    if len(documents) > args.sample:
        sample = random.Random(args.seed).sample(documents, args.sample)
    print(f"Discovering repeated phrases in {len(sample)} sampled documents "
          f"(present in >= {args.phrase_doc_fraction:.0%} of them) ...")
    discovered = maximal_phrases(frequent_phrases(
        sample, args.phrase_doc_fraction, args.min_phrase_words,
        args.max_phrase_words,
    ))
    print(f"  {len(discovered)} phrases")

    # literal, replacement, matches/KB, bytes saved/KB, origin
    candidates: list[tuple[str, str, float, float, str]] = []

    def consider(literal: str, replacement: str, origin: str) -> None:
        rate = occurrences_per_kb(lowered, literal, kilobytes)
        if rate < args.min_per_kb:
            return
        saved = rate * max(0, len(literal) - len(replacement))
        candidates.append((literal, replacement, rate, saved, origin))

    for phrase, _documents_seen in discovered:
        if any(word in PROTECTED for word in phrase.split()):
            continue
        consider(f" {phrase} ", " ", "discovered")

    for literal, replacement in reduction_rules("aggressive"):
        if literal.strip() in PROTECTED:
            continue
        consider(literal, replacement, "curated")

    # Ranked by bytes removed per KB, not by how often a rule fires. Those are
    # different objectives and only one of them is the point: " the " fires 23
    # times per KB and removes four bytes each time, while a sign-off fires
    # twice and removes forty. Ranking by match count buries every phrase the
    # corpus discovery exists to find.
    candidates.sort(key=lambda item: (-item[3], -len(item[0])))

    selected: list[tuple[str, str, float, float, str]] = []
    density = 0.0
    saved_per_kb = 0.0
    seen_literals: set[str] = set()
    covered: set[tuple[str, ...]] = set()

    for literal, replacement, rate, saved, origin in candidates:
        if literal in seen_literals or len(selected) >= args.max_rules:
            continue
        if len(replacement) > MAX_REPLACEMENT_LENGTH:
            continue
        # Discovery yields every window over a repeated sentence, so a twelve
        # word formula arrives as three overlapping ten-grams. Only the first is
        # worth a rule: the rest cover the same text, cannot fire once it has,
        # and would have their contribution counted again in the projection.
        windows = _windows(literal)
        if windows:
            if len(windows & covered) > len(windows) / 2:
                continue
            covered |= windows
        seen_literals.add(literal)
        selected.append((literal, replacement, rate, saved, origin))
        density += rate
        saved_per_kb += saved
        if args.target_density is not None and density >= args.target_density:
            break
        if (args.target_reduction is not None
                and 100 * saved_per_kb / 1024 >= args.target_reduction):
            break

    if not selected:
        raise SystemExit("no rule cleared the thresholds; lower --min-per-kb")

    _write_policy(args.out, selected, args.corpus.name, density)

    discovered_count = sum(1 for entry in selected if entry[4] == "discovered")
    print(f"\nWrote {args.out}: {len(selected)} rules "
          f"({discovered_count} discovered, {len(selected) - discovered_count} curated)")
    print(f"  projected: {density:.1f} matches/KB, {saved_per_kb:.0f} bytes/KB "
          f"removed ({100 * saved_per_kb / 1024:.1f}%)")

    print("\n  top contributors (by bytes removed):")
    for literal, replacement, rate, saved, origin in selected[:12]:
        action = "remove" if not replacement.strip() else f"-> {replacement.strip()!r}"
        shown = literal if len(literal) <= 44 else literal[:41] + "..."
        print(f"    {saved:7.1f} B/KB {rate:6.2f}/KB  {origin:10s} {shown!r:46s} {action}")

    rules = {literal: replacement for literal, replacement, _, _, _ in selected}
    found = LiteralMatcher(rules).find_all(text)
    reduced = apply_leftmost_longest(text, found, rules)
    before_tokens, after_tokens = len(text.split()), len(reduced.split())
    print(f"\n  measured on the corpus: {len(found) / kilobytes:.1f} candidate "
          f"matches/KB")
    print(f"  tokens {before_tokens:,} -> {after_tokens:,} "
          f"({100 * (before_tokens - after_tokens) / before_tokens:.1f}% fewer)")
    print(f"  bytes  {len(text):,} -> {len(reduced):,} "
          f"({100 * (len(text) - len(reduced)) / len(text):.1f}% fewer)")
    return 0


def _write_policy(
    path: Path,
    selected: list[tuple[str, str, float, float, str]],
    corpus_name: str,
    target: float,
) -> None:
    lines = [
        f"# Token-reduction policy derived from {corpus_name}.",
        "# Generated by demos/policies/build_corpus_policy.py.",
        "#",
        "# Rules are space-delimited: the engine matches substrings and has no",
        "# notion of a word, so an undelimited \" the \" would fire inside \"theme\".",
        "#",
        f"# Ranked by bytes removed per KB; this corpus reaches ~{target:.0f}",
        "# matches/KB. Rules discovered in the corpus are phrases it repeats across",
        "# many documents - formulaic by definition. Curated rules come from the",
        "# vocabulary in framework/policy/word_reduction.py, included only where",
        "# this corpus actually fires them.",
        "",
    ]
    for origin in ("discovered", "curated"):
        entries = [item for item in selected if item[4] == origin]
        if not entries:
            continue
        lines.append(f"# --- {origin} ({len(entries)}) ---")
        for literal, replacement, _rate, _saved, _origin in entries:
            escaped_literal = literal.replace("\\", "\\\\").replace('"', '\\"')
            escaped_replacement = replacement.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'"{escaped_literal}" -> "{escaped_replacement}";')
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
