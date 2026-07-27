"""Per-document business prose.

Documents that need to reach a size target used to reach it by repeating one
fixed sentence. A long account note is long because a lot of different things
happened to the account - dozens of small entries written by different people
over months - not because one sentence was pasted three hundred times. Composing
each sentence from clause banks gets closer to that for the cost of a little
vocabulary.

Nothing here contains an identifier shape. These sentences sit alongside catalog
values and ungoverned ones, both of which come from generators that check
themselves against the policy; this module deliberately knows nothing about the
policy, so it can never introduce a value the expected results do not account
for.
"""
from __future__ import annotations

import random

_OPENERS = (
    "The account was reviewed",
    "A follow-up was scheduled",
    "The request was acknowledged",
    "Servicing notes were updated",
    "The case was reassigned",
    "A verification step was repeated",
    "The escalation was withdrawn",
    "Contact preferences were confirmed",
    "The billing cycle was re-checked",
    "An audit sample was pulled",
    "The retention schedule was applied",
    "A consent record was refreshed",
    "The onboarding checklist was completed",
    "Entitlements were re-evaluated",
    "The support tier was confirmed",
)

_QUALIFIERS = (
    "during the routine servicing window",
    "after the customer called back",
    "as part of the quarterly review",
    "once the earlier hold was released",
    "before the change was published",
    "while the account was in a pending state",
    "following the scheduled maintenance",
    "under the standard four-eyes process",
    "at the request of the servicing team",
    "ahead of the next statement run",
    "in line with the retention policy",
    "after the duplicate was closed",
)

_OUTCOMES = (
    "and no further action was required",
    "and the outcome was recorded against the account",
    "and the customer was notified through their preferred channel",
    "and the original request was closed as resolved",
    "and the change took effect the same day",
    "and the file was returned to the servicing queue",
    "and a note was added for the next reviewer",
    "and the correction was applied without adjustment",
    "and the reviewer signed off without exception",
    "and the entry was left open pending confirmation",
)

_STANDALONE = (
    "No exceptions were raised during the review.",
    "The supporting documentation was already on file.",
    "Processing completed within the expected service window.",
    "The record was checked against the retention schedule and retained.",
    "Nothing in this entry requires customer contact.",
    "The prior correction remains in force.",
    "This entry is informational and carries no financial impact.",
    "The queue was cleared without escalation.",
    "A second reviewer confirmed the outcome.",
    "The summary below reflects the state at the time of review.",
    "Handling followed the standard path with no deviations.",
    "The originating channel was the self-service portal.",
)

_CONNECTORS = (" ", " ", " ", "\n")


def sentence(rng: random.Random) -> str:
    """One varied business sentence."""

    if rng.random() < 0.3:
        return rng.choice(_STANDALONE)
    opener = rng.choice(_OPENERS)
    qualifier = rng.choice(_QUALIFIERS)
    outcome = rng.choice(_OUTCOMES)
    return f"{opener} {qualifier}, {outcome}."


def paragraph(rng: random.Random, sentences: int = 3) -> str:
    return " ".join(sentence(rng) for _ in range(max(1, sentences)))


def text_of_at_least(rng: random.Random, minimum_bytes: int) -> str:
    """Varied prose of at least `minimum_bytes` when UTF-8 encoded.

    Callers that need an exact budget truncate the result; producing a little
    more than asked keeps this function free of the caller's encoding rules.
    """
    if minimum_bytes <= 0:
        return ""
    parts: list[str] = []
    size = 0
    while size < minimum_bytes:
        part = sentence(rng)
        parts.append(part)
        size += len(part.encode("utf-8")) + 1
        parts.append(rng.choice(_CONNECTORS))
    return "".join(parts)
