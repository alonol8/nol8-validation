"""Common-word reductions: the vocabulary behind the token-reduction use case.

Text sent to an embedding pipeline or a model is billed by the token, and some
of any business corpus is words with a shorter equivalent or no retrieval value
at all. "In order to" is three tokens that mean "to". "Approximately" is a long
word meaning "about". "Best regards" is courtesy. Rewriting and dropping those
deterministically, before the text reaches the expensive stage, reduces what is
billed without changing what the text says.

**The bar is that the meaning survives, and it is not negotiable.** An earlier
version of this table also deleted function words - "the", "to", "of", "and" -
on the theory that a model reads around the damage. It does not: prepositions
carry argument structure, and "send the report to Bob" becoming "send report
Bob" loses who receives it. That version reported 16-24% token savings, which
were savings from destroying text, and they are withdrawn. What is left saves
far less and says the same thing afterwards.

Expect a small number. Measured on 196 KB of real English this table earns
around 0.3 matches/KB, because substitutions that are safe in every context are
genuinely rare. The honest saving on business email comes mostly from the
boilerplate entries.

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


# Contractions. Two tokens become one and the meaning is untouched, which makes
# these the cheapest entries in the table - and unusually valuable, because they
# are the only safe way to shorten a negation. " do not " must not lose its
# "not", but " don't " keeps it while saving the token.
CONTRACTIONS: dict[str, str] = {
    "are not": "aren't",
    "cannot": "can't",
    "could not": "couldn't",
    "did not": "didn't",
    "do not": "don't",
    "does not": "doesn't",
    "had not": "hadn't",
    "has not": "hasn't",
    "have not": "haven't",
    "i am": "I'm",
    "i have": "I've",
    "i will": "I'll",
    "is not": "isn't",
    "it is": "it's",
    "should not": "shouldn't",
    "that is": "that's",
    "there is": "there's",
    "they are": "they're",
    "was not": "wasn't",
    "we are": "we're",
    "we have": "we've",
    "we will": "we'll",
    "were not": "weren't",
    "will not": "won't",
    "would not": "wouldn't",
    "you are": "you're",
    "you will": "you'll",
}

# The formulae that open and close business email. They are pure courtesy: a
# reader needs them and a retrieval index does not, and in a corpus of
# correspondence they are both long and constant. This is the same idea as the
# repeated-sentence stripping in the pre-index demo, generalised - that found
# boilerplate by counting repeats in one corpus, and these are the phrases that
# repeat in all of them.
EMAIL_BOILERPLATE: tuple[str, ...] = (
    "as per our conversation",
    "at your earliest convenience",
    "best regards",
    "feel free to",
    "i hope this email finds you well",
    "kind regards",
    "looking forward to hearing from you",
    "please do not hesitate to contact me",
    "please find attached",
    "please let me know if you have any questions",
    "thank you for your time",
    "thanks in advance",
    "warm regards",
)

# Standard business shorthand. A model expands these without being told, and
# they are common enough in correspondence to be worth their place.
ABBREVIATIONS: dict[str, str] = {
    "account": "acct",
    "agreement": "agmt",
    "attachment": "attach",
    "average": "avg",
    "company": "co",
    "corporation": "corp",
    "customer": "cust",
    "customers": "custs",
    "department": "dept",
    "estimate": "est",
    "including": "incl",
    "maximum": "max",
    "message": "msg",
    "minimum": "min",
    "number": "no",
    "quantity": "qty",
    "quarter": "Q",
    "received": "rcvd",
    "reference": "ref",
    "response": "resp",
    "schedule": "sched",
    "transaction": "txn",
    "transactions": "txns",
    "versus": "vs",
    "without": "w/o",
}


def reduction_rules() -> list[tuple[str, str]]:
    """Every reduction as a (literal, replacement) pair, space-delimited.

    Sorted longest-first so a reader of the generated policy sees the phrases
    before the words they contain. The engine resolves overlaps leftmost-longest
    regardless of file order, so " in order to " wins over the " to " inside it -
    which is the intended result, and the reason phrases are worth having.
    """
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(source: str, replacement: str) -> None:
        literal = f" {source} "
        if literal not in seen:
            pairs.append((literal, replacement))
            seen.add(literal)

    for phrase in EMAIL_BOILERPLATE:
        add(phrase, " ")
    for phrase, replacement in PLAINER_PHRASES.items():
        add(phrase, f" {replacement} ")
    for phrase, replacement in CONTRACTIONS.items():
        add(phrase, f" {replacement} ")
    for word, replacement in PLAINER_WORDS.items():
        add(word, f" {replacement} ")
    for word, replacement in ABBREVIATIONS.items():
        add(word, f" {replacement} ")
    for word in STOPWORDS:
        add(word, " ")

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
