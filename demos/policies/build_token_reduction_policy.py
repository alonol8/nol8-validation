#!/usr/bin/env python3
"""Build a TOKEN REDUCTION policy - shrink text before it is billed by the token.

The pre-index demo already strips whole repeated sentences
(`build_optimization_policy.py`). That works only where boilerplate repeats
verbatim, so it reaches the framing sentences in a corpus and nothing else.

This is the general form of the same use case. Text sent to an embedding
pipeline or a model is billed by the token, and some of any business corpus is
words with a shorter equivalent or no retrieval value at all:

    "in order to"    -> "to"          three tokens become one
    "approximately"  -> "about"       a long word becomes a short one
    "actually"       -> (removed)     no retrieval value

Applied to every document rather than to the handful that share boilerplate,
this reduces what reaches the expensive stage across the whole corpus. It is
plain literal replacement - a fixed list of strings, each mapped to a shorter
string or to nothing - which is why it runs in front of a pipeline at line rate
instead of becoming another model in the path.

WORD BOUNDARIES
---------------
The engine matches substrings; it has no notion of a word. A rule on "hell"
fires inside "hello". Every rule here is therefore written with a leading and
trailing space, so " the " cannot fire inside "theme" or "further". Without
that, this policy would not shorten text, it would corrupt it.

Two consequences, both accepted rather than worked around:

  * a word next to punctuation is not reduced - " the." is not " the "
  * two reducible words in a row reduce only the first, because the delimiting
    spaces are shared and a consumed byte cannot begin the next match

Both cost a little reduction; neither can produce wrong text. Word-boundary
matching would remove both, and is not available today.

WHAT TO EXPECT
--------------
A single-digit percentage. Every substitution here survives any context it can
land in, and substitutions that safe are rare - around 0.3 matches/KB on real
English, with most of the saving coming from the boilerplate entries. An earlier
version also deleted function words and reported 16-24%; that was measuring
destroyed text, and it was removed.

    python demos/policies/build_token_reduction_policy.py
    -> demos/policies/token-reduction.nol
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from framework.policy.matching import LiteralMatcher, resolve_non_overlapping  # noqa: E402
from framework.policy.word_reduction import (  # noqa: E402
    ABBREVIATIONS,
    CONTRACTIONS,
    EMAIL_BOILERPLATE,
    PLAINER_PHRASES,
    PLAINER_WORDS,
    STOPWORDS,
    reduction_rules,
)

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "token-reduction.nol"

MAX_REPLACEMENT_LENGTH = 15

# Ordinary business prose, used to report what the policy actually achieves
# rather than asserting a figure. Deliberately unremarkable: if the reduction
# only shows up on text written to flatter it, it is not a real reduction.
SAMPLE = """
In order to complete the review, the servicing team will need to obtain
additional documentation from the customer prior to the next statement run.
It should be noted that the majority of these requests are actually resolved
on a regular basis without escalation; however, in the event that the customer
does not respond within the agreed period, we will subsequently terminate the
request and provide a summary of the outcome.

Please note that the account was previously flagged for review due to the fact
that the contact details were quite obviously out of date. Consequently, the
team will facilitate a further check with regard to the address on file, and
will endeavour to determine whether any additional action is necessary.

The remainder of the file is essentially complete. We will proceed to close the
case immediately, and it is generally sufficient for the reviewer to indicate
that the requirement has been met at this point in time.
""".strip()


def check_safe(pairs: list[tuple[str, str]]) -> None:
    """Refuse a policy that cannot behave."""

    for literal, replacement in pairs:
        if len(replacement) > MAX_REPLACEMENT_LENGTH:
            raise ValueError(
                f"Replacement {replacement!r} exceeds {MAX_REPLACEMENT_LENGTH} "
                "characters and would be truncated at runtime (ISSUE-005)."
            )
        # Delimiting is what makes a rule safe, not length. " it is " cannot
        # fire inside a longer word because both spaces have to be there; an
        # undelimited rule would.
        if not literal.startswith(" ") or not literal.endswith(" "):
            raise ValueError(
                f"Rule {literal!r} is not space-delimited; without word "
                "boundaries it would fire inside longer words."
            )
        if not literal.strip():
            raise ValueError("A rule cannot be only whitespace.")

    literals = [literal for literal, _ in pairs]
    if len(set(literals)) != len(literals):
        raise ValueError("Duplicate rules; each literal must appear once.")


def render(pairs: list[tuple[str, str]]) -> str:
    lines = [
        "# Token-reduction policy - shrink text before it is billed",
        "# by the token. Generated by build_token_reduction_policy.py.",
        "#",
        "# Every rule is space-delimited. The engine matches substrings and has no",
        "# notion of a word, so an undelimited rule on \" the \" would fire inside",
        "# \"theme\" and corrupt the text rather than shorten it.",
        "#",
        "# Phrases are listed before the words they contain. The engine resolves",
        "# overlaps leftmost-longest, so \" in order to \" wins over the \" to \"",
        "# inside it regardless of file order; the ordering is for the reader.",
        "",
        f"# --- Phrases ({len(PLAINER_PHRASES)}) ---",
    ]
    phrase_literals = {f" {phrase} " for phrase in PLAINER_PHRASES}
    word_literals = {f" {word} " for word in PLAINER_WORDS}

    for literal, replacement in pairs:
        if literal in phrase_literals:
            lines.append(f'"{literal}" -> "{replacement}";')
    lines.extend(["", f"# --- Words ({len(PLAINER_WORDS)}) ---"])
    for literal, replacement in pairs:
        if literal in word_literals:
            lines.append(f'"{literal}" -> "{replacement}";')
    removed = [p for p in pairs if p[0] not in phrase_literals and p[0] not in word_literals]
    lines.extend(["", f"# --- Removed entirely ({len(removed)}) ---"])
    for literal, replacement in removed:
        lines.append(f'"{literal}" -> "{replacement}";')
    lines.append("")
    return "\n".join(lines)


def apply_policy(text: str, pairs: list[tuple[str, str]]) -> str:
    """What a correct engine produces: leftmost-longest, non-overlapping."""

    replacements = dict(pairs)
    matcher = LiteralMatcher(replacements)
    selected = resolve_non_overlapping(matcher.find_all(text))
    out: list[str] = []
    cursor = 0
    for match in selected:
        out.append(text[cursor:match.start])
        out.append(replacements[match.literal])
        cursor = match.end
    out.append(text[cursor:])
    return "".join(out)


def approximate_tokens(text: str) -> int:
    """Whitespace tokens - a stand-in, and stated as one.

    A real tokenizer splits differently, so this is a proxy for the direction
    and rough size of the change, not a billing figure.
    """
    return len(text.split())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show-sample",
        action="store_true",
        help="print the reduced sample text alongside the figures",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        help="optional JSONL of {text} or {message} records to measure against, "
             "instead of the built-in sample",
    )
    args = parser.parse_args()

    corpus_text = _load_corpus(args.corpus) if args.corpus else SAMPLE
    label = str(args.corpus) if args.corpus else "the built-in sample of business prose"

    pairs = reduction_rules()
    check_safe(pairs)
    OUTPUT.write_text(render(pairs))

    reduced = apply_policy(corpus_text, pairs)
    before_tokens = approximate_tokens(corpus_text)
    after_tokens = approximate_tokens(reduced)
    before_bytes = len(corpus_text.encode("utf-8"))
    after_bytes = len(reduced.encode("utf-8"))
    matches = len(resolve_non_overlapping(
        LiteralMatcher(dict(pairs)).find_all(corpus_text)
    ))
    kilobytes = before_bytes / 1024

    print(f"Wrote {OUTPUT.name}: {len(pairs)} rules "
          f"({len(PLAINER_PHRASES)} phrases, {len(CONTRACTIONS)} contractions, "
          f"{len(PLAINER_WORDS)} words, {len(ABBREVIATIONS)} abbreviations, "
          f"{len(STOPWORDS) + len(EMAIL_BOILERPLATE)} removed).")
    print(f"  measured on {label} ({kilobytes:.0f} KB)")
    print(f"  tokens (whitespace proxy): {before_tokens} -> {after_tokens} "
          f"({(before_tokens - after_tokens) / max(1, before_tokens) * 100:.1f}% fewer)")
    print(f"  bytes:                     {before_bytes} -> {after_bytes} "
          f"({(before_bytes - after_bytes) / max(1, before_bytes) * 100:.1f}% fewer)")
    print(f"  match density:             {matches / kilobytes:.1f} matches/KB")
    print()

    if args.show_sample:
        print("--- reduced ---")
        print(reduced[:1200])
        print()

    print("Measured by applying the policy through the framework's own matcher,")
    print("not asserted. Deploy it and the engine should reproduce this exactly;")
    print("demos/benchmark/verify-oracle.py adjudicates that.")


def _load_corpus(path: Path) -> str:
    """Concatenate a JSONL corpus of {text} or {message} records."""

    import json

    parts: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        value = record.get("text") or record.get("message")
        if isinstance(value, str):
            parts.append(value)
    if not parts:
        raise SystemExit(f"no text found in {path}")
    return "\n".join(parts)


if __name__ == "__main__":
    main()
