"""Common-word reductions: the vocabulary behind the token-reduction use case.

Text sent to an embedding pipeline or a model is billed by the token, and a
large fraction of any business corpus is words that carry no retrieval value or
that have a shorter equivalent. "In order to" is three tokens that mean "to".
"Approximately" is a long word meaning "about". "The", "of" and "and" are pure
structure. Rewriting and dropping them deterministically, before the text
reaches the expensive stage, reduces what is billed without changing what the
text says.

This is literal replacement, which is what the engine does: a fixed list of
strings, each mapped to a shorter string or to nothing. No parsing, no grammar,
no model - which is why it can run at line rate in front of a pipeline.

The same table serves a second purpose. A policy built from it is a policy whose
values are ordinary English words, and ordinary English text is full of words
that *nearly* match those - "hen" against "hence", "there" against "the",
"requirement" against "require". Governed words and near misses are the same
vocabulary, so a corpus of plain business prose exercises both without anything
being planted in it.

**Matching is plain substring matching - there are no word boundaries.** A rule
on "hell" fires inside "hello". Every entry is therefore rendered into the policy
with a leading and trailing space, so " the " cannot fire inside "theme",
"further" or "the­orem". This is not a detail: without it, a token-reduction
policy does not shorten text, it corrupts it.

Two consequences follow from doing it that way, and both are accepted rather than
worked around:

* **A word next to punctuation is not reduced.** " the." does not contain
  " the ". Reductions land on words surrounded by spaces, which is most of them.
* **Two reducible words in a row - "for the purpose" - reduce only the first.**
  The delimiting spaces are shared, and a byte already consumed by one match
  cannot begin the next. The output is correct, just slightly less short.

Both cost a little reduction and neither can produce wrong text, which is the
right side to err on. Word-boundary matching would remove both; until it exists,
this is the honest mechanism.
"""
from __future__ import annotations

# Longer word -> shorter word meaning the same thing.
#
# Every entry has to survive substitution *anywhere* it appears, because the
# engine has no grammar and will apply it everywhere. That rules out a lot of
# otherwise reasonable pairs, and the discipline is worth stating:
#
#   "following"  -> "after"    breaks "the following week"
#   "previously" -> "before"   breaks "was previously flagged"
#   "concerning" -> "about"    breaks "a concerning trend"
#   "however"    -> "but"      breaks ", however, the team"
#   "rather"     -> removed    breaks "rather than"
#
# Each of those produces text that is shorter and wrong, which is worse than
# text that is longer and right. The entries below were kept only where no
# common construction breaks: they work as a verb and a noun, at the start of a
# clause and in the middle of one.
PLAINER_WORDS: dict[str, str] = {
    "additionally": "also",
    "approximately": "about",
    "assistance": "help",
    "commence": "start",
    "commenced": "started",
    "consequently": "so",
    "demonstrate": "show",
    "demonstrated": "showed",
    "endeavour": "try",
    "furthermore": "also",
    "hence": "so",
    "individual": "person",
    "initiate": "start",
    "modification": "change",
    "modifications": "changes",
    "nevertheless": "still",
    "notwithstanding": "despite",
    "obtain": "get",
    "participate": "take part",
    "purchase": "buy",
    "regarding": "about",
    "remainder": "rest",
    "requirement": "need",
    "requirements": "needs",
    "subsequently": "later",
    "sufficient": "enough",
    "terminate": "end",
    "therefore": "so",
    "utilise": "use",
    "utilised": "used",
    "utilize": "use",
    "utilized": "used",
    "whether": "if",
}

# Multi-word phrases that reduce to one or two tokens. These are the highest
# value entries in the table: four tokens becoming one saves more than any
# single-word substitution, and business writing is built out of them.
#
# The same rule applies, and it bites harder here because a phrase carries its
# own grammar. "the majority of" -> "most" reads correctly in "the majority of
# requests" and wrong in "the majority of these requests"; either replacement
# breaks one of the two, so the phrase is left alone.
PLAINER_PHRASES: dict[str, str] = {
    "at the present time": "now",
    "at this point in time": "now",
    "due to the fact that": "because",
    "in accordance with": "under",
    "in order to": "to",
    "in the event that": "if",
    "in the near future": "soon",
    "is able to": "can",
    "on a regular basis": "often",
    "prior to": "before",
    "subsequent to": "after",
    "take into consideration": "consider",
    "with reference to": "about",
    "with regard to": "about",
}

# Words and openers carrying no retrieval value once the text is embedded.
# Removed rather than shortened. Same test: each has to be removable wherever it
# occurs, which is why "rather" is absent - it would strip "rather than".
STOPWORDS: tuple[str, ...] = (
    "actually",
    "basically",
    "certainly",
    "essentially",
    "generally",
    "it should be noted that",
    "obviously",
    "particularly",
    "please note that",
    "quite",
    "really",
    "simply",
    "specifically",
    "typically",
    "very",
)


def reduction_rules() -> list[tuple[str, str]]:
    """Every reduction as a (literal, replacement) pair, space-delimited.

    Sorted longest-first so a reader of the generated policy sees the phrases
    before the words they contain. The engine resolves overlaps leftmost-longest
    regardless of file order, so " in order to " wins over the " to " inside it -
    which is the intended result, and the reason phrases are worth having.
    """
    pairs: list[tuple[str, str]] = []
    for phrase, replacement in PLAINER_PHRASES.items():
        pairs.append((f" {phrase} ", f" {replacement} "))
    for word, replacement in PLAINER_WORDS.items():
        pairs.append((f" {word} ", f" {replacement} "))
    for word in STOPWORDS:
        pairs.append((f" {word} ", " "))
    pairs.sort(key=lambda pair: (-len(pair[0]), pair[0]))
    return pairs


def stem(word: str) -> str | None:
    """A shorter form of `word` that a writer might have used instead.

    Used when generating text that nearly matches a governed word. Returns None
    where no plausible shorter form exists.
    """
    lowered = word.lower()
    for suffix in ("ements", "ement", "ingly", "ation", "ings", "ness", "ing", "ers", "ed", "es", "ly", "s"):
        if lowered.endswith(suffix) and len(lowered) - len(suffix) >= 4:
            trimmed = word[: len(word) - len(suffix)]
            return trimmed if trimmed.lower() != lowered else None
    return None
