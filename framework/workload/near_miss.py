"""Text that almost matches a governed value, but does not.

A policy governs a list of exact strings. Real documents are full of text that
comes very close to those strings without being them - the same identifier with
the last digit different, the same token cut short by a log field width, the
same card number with everything but the last group masked. `hello` is governed;
the document contains `hell`.

This is the ordinary case in production and there are only mundane reasons for
it. Identifiers are issued in sequence, so the record next to a watched one
differs in its final character. Logging and CSV exports truncate long fields.
Systems mask values before writing them down, keeping a prefix. People quote the
first half of a reference in a note. None of this is unusual; it is what a body
of business records looks like.

A corpus without it is describing something production never does. Every
identifier-shaped string in such a corpus either matches a rule exactly or looks
nothing like one, and there is nothing present that *could* be wrongly matched,
so a run over it cannot say anything about false positives at all.

Values here are derived from the catalog itself - shortened, or altered near the
end - which is what makes them near misses rather than merely different values.
A different customer's ID shares only the `CUST-` prefix; a truncated one shares
everything but its tail. Every candidate is checked against the full catalog
before use, so a value returned from here is known not to be governed.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from framework.policy.word_reduction import PLAINER_WORDS, stem


class CatalogMatcher(Protocol):
    """The subset of `LiteralMatcher` this module needs."""

    def find_all(self, text: str) -> list: ...


@dataclass(frozen=True)
class NearMiss:
    """One string that resembles a governed value without being one.

    `kind` records how it came to look that way, because that determines where it
    plausibly appears: a masked card number belongs in a receipt line, a value
    cut short belongs in a log field or a spreadsheet column.
    """

    pattern_id: str
    value: str
    kind: str


# The shortest useful near miss. Below this the value no longer resembles the
# one it came from and is just a fragment of text.
_MINIMUM_LENGTH = 6

# A masked value has to keep enough to identify what it was, which is more than
# a truncated one needs - truncation is an accident of field width, masking is a
# deliberate act with a purpose.
_MASK_KEEP_MINIMUM = 8

# How much of the original a truncated value keeps. Real truncation is imposed
# by a field width rather than chosen, so it lands anywhere in this range.
_TRUNCATION_KEEP = (0.55, 0.92)

# Attempts before a strategy gives up on one source value. Failure means the
# derived string turned out to be some other governed value - common with
# sequential identifiers, where the neighbour of a watched record is often also
# watched - and the caller simply tries a different source.
_MAX_ATTEMPTS = 6

_DIGITS = "0123456789"
_LOWER = "abcdefghijklmnopqrstuvwxyz"
_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

_MASK_SUFFIXES = ("****", "...", "XXXX", "…")


def _substitute_character(character: str, rng: random.Random) -> str:
    """A different character of the same class, so the shape is preserved."""

    for alphabet in (_DIGITS, _LOWER, _UPPER):
        if character in alphabet:
            replacement = rng.choice(alphabet)
            while replacement == character and len(alphabet) > 1:
                replacement = rng.choice(alphabet)
            return replacement
    return character


class NearMissFactory:
    """Derives almost-matching text from the governed values themselves.

    Deriving from the catalog rather than generating independently is what makes
    these near misses. An unrelated customer ID shares a five-character prefix
    with a watched one; the record issued immediately after it differs only in
    its final digit, and that is the case worth having in a corpus.
    """

    __slots__ = ("_matcher", "_literals", "_pattern_by_literal")

    def __init__(
        self,
        matcher: CatalogMatcher,
        literals_by_pattern: Mapping[str, Sequence[str]],
    ) -> None:
        self._matcher = matcher
        self._literals: list[str] = []
        self._pattern_by_literal: dict[str, str] = {}
        for pattern_id, literals in sorted(literals_by_pattern.items()):
            for literal in literals:
                if len(literal) > _MINIMUM_LENGTH:
                    self._literals.append(literal)
                    self._pattern_by_literal[literal] = pattern_id
        self._literals.sort()

    def __len__(self) -> int:
        return len(self._literals)

    def _accept(self, source: str, candidate: str, kind: str) -> NearMiss | None:
        if len(candidate) < _MINIMUM_LENGTH or candidate == source:
            return None
        # The check that makes this a near miss rather than a match. Truncating
        # or altering one governed value can land exactly on another - most
        # easily where identifiers are issued in sequence.
        if self._matcher.find_all(candidate):
            return None
        return NearMiss(
            pattern_id=self._pattern_by_literal.get(source, ""),
            value=candidate,
            kind=kind,
        )

    def truncated(self, source: str, rng: random.Random) -> NearMiss | None:
        """The value as a field too narrow for it would have recorded it."""

        low, high = _TRUNCATION_KEEP
        keep = int(len(source) * rng.uniform(low, high))
        keep = max(_MINIMUM_LENGTH, min(keep, len(source) - 1))
        return self._accept(source, source[:keep], "truncated")

    def altered_tail(self, source: str, rng: random.Random) -> NearMiss | None:
        """The neighbouring record: identical until its last character or two."""

        characters = list(source)
        for offset in range(1, rng.randint(1, 2) + 1):
            position = len(characters) - offset
            if position < 0:
                break
            characters[position] = _substitute_character(characters[position], rng)
        return self._accept(source, "".join(characters), "altered_tail")

    def masked(self, source: str, rng: random.Random) -> NearMiss | None:
        """The value as an upstream system wrote it down after masking it.

        Masking keeps enough of the value to be recognisable - that is the point
        of it. A card number masked down to its first four characters would not
        identify anything, so nobody masks that hard.
        """
        keep = int(len(source) * rng.uniform(0.45, 0.7))
        if keep < _MASK_KEEP_MINIMUM or keep >= len(source):
            return None
        return self._accept(
            source, source[:keep] + rng.choice(_MASK_SUFFIXES), "masked"
        )

    def word_variant(self, source: str, rng: random.Random) -> NearMiss | None:
        """The same thing, written the way somebody else would write it.

        Where a governed value contains words rather than only digits - a
        project codename, a product, a person - the text around it will not use
        one settled form. People drop the qualifier, shorten the phrase, swap a
        formal word for a plain one, or write the singular where the list has
        the plural. This is the oldest problem in list-based detection: the
        policy holds "Acme Corporation" and the document says "Acme Corp".
        """
        words = source.split()
        if not any(character.isalpha() for character in source):
            return None

        options: list[str] = []
        if len(words) > 1:
            # Dropping the trailing qualifier, and keeping only the head, are
            # both how people shorten a name in running text.
            options.append(" ".join(words[:-1]))
            options.append(words[0])
        for position, word in enumerate(words):
            plain = PLAINER_WORDS.get(word.lower())
            if plain is not None:
                rewritten = list(words)
                rewritten[position] = plain.capitalize() if word[:1].isupper() else plain
                options.append(" ".join(rewritten))
            shorter = stem(word)
            if shorter is not None:
                rewritten = list(words)
                rewritten[position] = shorter
                options.append(" ".join(rewritten))

        options = [option for option in options if option and option != source]
        if not options:
            return None
        return self._accept(source, rng.choice(options), "word_variant")

    # How often each way of almost-matching turns up. Sequential neighbours and
    # truncation are the common ones; masking is deliberate and rarer. Word
    # variants only apply to values with words in them, and fall through to the
    # others when they do not.
    _STRATEGY_WEIGHTS = (
        ("altered_tail", 32),
        ("truncated", 32),
        ("word_variant", 22),
        ("masked", 14),
    )

    def derive(self, rng: random.Random) -> NearMiss | None:
        """One near miss from a randomly chosen governed value."""

        if not self._literals:
            return None
        names = [name for name, _ in self._STRATEGY_WEIGHTS]
        weights = [weight for _, weight in self._STRATEGY_WEIGHTS]
        for _ in range(_MAX_ATTEMPTS):
            source = rng.choice(self._literals)
            strategy = rng.choices(names, weights=weights, k=1)[0]
            near_miss = getattr(self, strategy)(source, rng)
            if near_miss is not None:
                return near_miss
        return None

    def build_pool(self, size: int, rng: random.Random) -> tuple[NearMiss, ...]:
        """The population of almost-matching text a corpus draws on.

        Built once and shared across documents, because the same near misses
        recur in a real corpus for the same reason the governed values do: the
        same truncating log format runs everywhere, and the record next to a
        watched one is referenced as often as the watched one is.
        """
        pool: list[NearMiss] = []
        seen: set[str] = set()
        for _ in range(max(0, size)):
            near_miss = self.derive(rng)
            if near_miss is None or near_miss.value in seen:
                continue
            seen.add(near_miss.value)
            pool.append(near_miss)
        return tuple(pool)


class NearMissSupply:
    """A per-document budget of ungoverned values, drawn on demand.

    A record does not decide up front how many other parties it will mention -
    they accumulate as it is written and as its history grows. Callers draw from
    this as they compose, and whatever is left is absorbed by the parts of the
    document that grow over time.
    """

    __slots__ = ("_pool", "_by_pattern", "_rng", "_remaining", "_used")

    def __init__(
        self,
        pool: Sequence[NearMiss],
        rng: random.Random,
        budget: int,
    ) -> None:
        self._pool = tuple(pool)
        self._by_pattern: dict[str, list[NearMiss]] = {}
        for near_miss in self._pool:
            self._by_pattern.setdefault(near_miss.pattern_id, []).append(near_miss)
        self._rng = rng
        self._remaining = max(0, int(budget)) if self._pool else 0
        self._used = 0

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int:
        return self._remaining

    def take(self, count: int = 1, pattern_id: str | None = None) -> list[NearMiss]:
        """Up to `count` values, fewer if the document's budget is exhausted."""

        if not self._pool or count <= 0:
            return []
        candidates = (
            self._by_pattern.get(pattern_id, ()) if pattern_id is not None else self._pool
        )
        if not candidates:
            candidates = self._pool
        drawn: list[NearMiss] = []
        while len(drawn) < count and self._remaining > 0:
            self._remaining -= 1
            self._used += 1
            drawn.append(self._rng.choice(candidates))
        return drawn

    def take_one(self, pattern_id: str | None = None) -> NearMiss | None:
        drawn = self.take(1, pattern_id)
        return drawn[0] if drawn else None


# --------------------------------------------------------------------------
# Natural phrasing
#
# Outside a log file, these values arrive inside sentences somebody wrote: an
# agent explaining what they checked, a reviewer recording who else was
# involved. Phrasing varies by the kind of value, because the reason a hostname
# appears in a note is not the reason a person's name does.
# --------------------------------------------------------------------------

_ROLE_BY_PATTERN = {
    "person_name": "contact",
    "email_address": "contact",
    "phone_number": "contact",
    "street_address": "personal",
    "social_security_number": "personal",
    "date_of_birth": "personal",
    "api_key": "credential",
    "access_token": "credential",
    "bearer_token": "credential",
    "password": "credential",
    "private_key_marker": "credential",
    "connection_string": "credential",
    "credit_card_number": "financial",
    "bank_account_number": "financial",
    "routing_number": "financial",
    "iban": "financial",
    "invoice_number": "financial",
    "ipv4_address": "infrastructure",
    "ipv6_address": "infrastructure",
    "hostname": "infrastructure",
    "internal_url": "infrastructure",
    "cloud_resource_id": "infrastructure",
    "database_uri": "infrastructure",
    "patient_id": "reference",
    "member_id": "reference",
    "claim_number": "reference",
    "medical_record_number": "reference",
    "customer_id": "reference",
    "employee_id": "reference",
    "support_case_id": "reference",
    "contract_number": "reference",
    "project_codename": "business",
    "internal_product_name": "business",
}

_PHRASINGS = {
    "contact": (
        "Also spoke with {value} while confirming the account details.",
        "Left a message for {value} before escalating.",
        "Copied {value} on the follow-up so both parties have the summary.",
        "The earlier conversation was handled by {value}.",
        "Callback was arranged with {value} for the following morning.",
    ),
    "personal": (
        "The address on file at the time of the request was {value}.",
        "Verification used the details recorded previously: {value}.",
        "Record from the prior application still shows {value}.",
        "The submitted form listed {value}, which did not match the account.",
    ),
    "credential": (
        "The integration test environment uses its own credential, {value}, which is not in scope here.",
        "A rotated value, {value}, was retired last quarter and should no longer appear.",
        "The sandbox tenant issues {value} for the same workflow.",
        "Engineering confirmed the staging value {value} is unrelated to this account.",
    ),
    "financial": (
        "The related settlement was raised against {value}.",
        "An earlier statement referenced {value} for the same period.",
        "Finance cross-checked {value} before releasing the adjustment.",
        "The reversal was applied to {value} rather than this account.",
    ),
    "infrastructure": (
        "Traffic originated from {value} during the affected window.",
        "The request was served by {value} before the failover.",
        "Health checks against {value} were green throughout.",
        "Logs for the same period are retained on {value}.",
        "The retry path routes through {value}.",
    ),
    "reference": (
        "Linked to prior case {value}.",
        "Superseded by {value}, which tracks the same request.",
        "Cross-referenced against {value} during triage.",
        "A duplicate was opened as {value} and closed without action.",
        "The original request is recorded under {value}.",
    ),
    "business": (
        "The same workflow supports {value}.",
        "Scoped alongside {value} in the current planning cycle.",
        "This does not affect {value}, which uses a separate pipeline.",
    ),
}

_GENERIC_PHRASINGS = (
    "Additional context recorded during review: {value}.",
    "Noted for completeness: {value}.",
    "Related reference captured at the time: {value}.",
)


def reference_sentence(near_miss: NearMiss, rng: random.Random) -> str:
    """A natural sentence carrying one ungoverned value."""

    role = _ROLE_BY_PATTERN.get(near_miss.pattern_id)
    phrasings = _PHRASINGS.get(role, _GENERIC_PHRASINGS) if role else _GENERIC_PHRASINGS
    return rng.choice(phrasings).format(value=near_miss.value)


def reference_sentences(near_misses: Sequence[NearMiss], rng: random.Random) -> list[str]:
    return [reference_sentence(near_miss, rng) for near_miss in near_misses]


def density_budget(
    target_bytes: int,
    per_kilobyte: tuple[float, float],
    rng: random.Random,
) -> int:
    """How many ungoverned identifiers a document of this size carries.

    A density rather than a ratio to the governed matches. How much of a record
    is made up of names, IDs and hosts depends on what kind of record it is; how
    many of those are on a watch list is a separate and unrelated fact about the
    policy. Tying the two together would make a document's shape change when a
    rule was added to the policy, which is not how documents work.
    """
    minimum, maximum = per_kilobyte
    if maximum < minimum:
        minimum, maximum = maximum, minimum
    if maximum <= 0 or target_bytes <= 0:
        return 0
    rate = rng.uniform(minimum, maximum)
    return max(0, round(rate * target_bytes / 1024.0))


def parse_density(config: object) -> tuple[float, float] | None:
    """Read `near_miss_distribution.per_kilobyte` from a workload mapping.

    Absent means disabled, so a workload written before this option existed
    generates exactly what it generated before.
    """
    if not isinstance(config, dict):
        return None
    per_kilobyte = config.get("per_kilobyte")
    if not isinstance(per_kilobyte, dict):
        raise ValueError(
            "'near_miss_distribution.per_kilobyte' must be a mapping with "
            "'minimum' and 'maximum'."
        )
    try:
        minimum = float(per_kilobyte["minimum"])
        maximum = float(per_kilobyte["maximum"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            "'near_miss_distribution.per_kilobyte' requires numeric 'minimum' "
            "and 'maximum'."
        ) from error
    if minimum < 0 or maximum < 0:
        raise ValueError(
            "'near_miss_distribution.per_kilobyte' values must not be negative."
        )
    return (minimum, maximum)
