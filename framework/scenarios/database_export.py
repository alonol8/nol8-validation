"""Bulk table exports - the workload where governed values are the content.

Every realistic slice in this framework so far has been prose: a support ticket,
an account note, an email. Sensitive values appear in them the way they appear
in writing - a few per document, surrounded by ordinary language. That is one
real workload and it is inherently sparse, a handful of matches per kilobyte.

It is not the only one, and it is not the demanding one. The other place a
scanner gets pointed is bulk data: a customer table exported to CSV, a payment
ledger, a nightly claims batch, an access log. There the governed values are not
sprinkled through the content - they *are* the content. A single row

    CUST-000123,Sandra Hernandez 00042,s.hernandez@example.net,+1-704-383-0183

is about 90 bytes carrying four values a policy governs, and a file of them runs
at thirty to fifty matches per kilobyte without anything being contrived.

Both workloads are real and they behave completely differently, which is the
point of having both. An inline guardrail on correspondence is sparse work; a
bulk scan before a table leaves the building is dense work, and it is the one
that decides whether an engine can keep up.

Rows for parties that are not on the policy list come for free and are not
optional: a real export contains every customer, of whom the watched ones are a
minority. Those rows are what a scanner has to read and reject, and a corpus
where every row is a hit would not resemble any table anybody exports.
"""
from __future__ import annotations

import csv
import io
import random
from dataclasses import dataclass
from typing import Any, Protocol, Sequence


class ExportRule(Protocol):
    category_id: str
    pattern_id: str
    variant: str


@dataclass(frozen=True)
class ExportBuild:
    text: str
    placed: tuple[ExportRule, ...]
    rows: int


# One schema per document, because an export is a dump of one table. Each entry
# is (column name, pattern id or None), where None is an ordinary column that no
# policy governs - status flags, timestamps, amounts. Real exports are mostly
# governed columns with a few of these, which is exactly why they are dense.
SCHEMAS: dict[str, tuple[tuple[str, str | None], ...]] = {
    "customer_master": (
        ("customer_id", "customer_id"),
        ("full_name", "person_name"),
        ("email", "email_address"),
        ("phone", "phone_number"),
        ("address", "street_address"),
        ("status", None),
        ("updated_at", None),
    ),
    "payment_ledger": (
        ("txn_ref", None),
        ("customer_id", "customer_id"),
        ("account_number", "bank_account_number"),
        ("routing", "routing_number"),
        ("invoice", "invoice_number"),
        ("amount", None),
        ("posted_at", None),
    ),
    "employee_directory": (
        ("employee_id", "employee_id"),
        ("full_name", "person_name"),
        ("email", "email_address"),
        ("phone", "phone_number"),
        ("department", None),
        ("status", None),
    ),
    "claims_batch": (
        ("claim_number", "claim_number"),
        ("patient_id", "patient_id"),
        ("member_id", "member_id"),
        ("subscriber", "person_name"),
        ("date_of_birth", "date_of_birth"),
        ("provider", None),
        ("amount", None),
    ),
    "access_log": (
        ("event_at", None),
        ("employee_id", "employee_id"),
        ("source_ip", "ipv4_address"),
        ("host", "hostname"),
        ("action", None),
    ),
}

_STATUS = ("active", "pending", "suspended", "closed", "review")
_DEPARTMENT = ("Finance", "Legal", "Support", "Engineering", "Operations")
_ACTION = ("login", "export", "update", "read", "delete")
_PROVIDER = ("Northgate Clinic", "Riverside Health", "Summit Medical")


def build_export(
    document_id: str,
    random_source: random.Random,
    catalog: Sequence[ExportRule],
    match_budget: int,
    target_bytes: int,
    near_miss_supply: Any = None,
) -> ExportBuild:
    """One export file: a header row and as many data rows as fit `target_bytes`.

    Rules are drawn from the whole `catalog` rather than from a pre-sampled
    selection, because a schema uses a handful of the pattern kinds a catalog
    contains - a customer table has no column for an API key. Sampling across
    every pattern first and then filtering to the five a schema needs leaves
    almost nothing, and the export ends up full of unlisted parties.

    `match_budget` is how many governed values the document should carry. It
    decides how many *rows* belong to watched parties; the rest belong to
    everybody else, which is the ordinary composition of a real table.
    """
    schema_name = random_source.choice(sorted(SCHEMAS))
    columns = SCHEMAS[schema_name]
    governed_columns = [pattern for _, pattern in columns if pattern is not None]

    by_pattern: dict[str, list[ExportRule]] = {}
    for rule in catalog:
        by_pattern.setdefault(rule.pattern_id, []).append(rule)
    # Drawn without replacement so one document does not list the same watched
    # customer on three rows.
    cursors = {
        pattern: random_source.sample(rules, k=len(rules))
        for pattern, rules in by_pattern.items()
        if pattern in set(governed_columns)
    }

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([name for name, _ in columns])

    placed: list[ExportRule] = []
    remaining = max(0, match_budget)
    rows = 0
    sequence = 0
    while buffer.tell() < target_bytes and rows < 10_000:
        sequence += 1
        # A row belongs to a watched party only while the budget covers a whole
        # row of them; a half-governed row would be an odd thing for a table to
        # contain.
        governed_row = remaining >= len(governed_columns)
        row: list[str] = []
        for name, pattern_id in columns:
            if pattern_id is None:
                row.append(_ordinary_value(name, sequence, random_source))
                continue
            available = cursors.get(pattern_id)
            if governed_row and available:
                rule = available.pop()
                placed.append(rule)
                remaining -= 1
                row.append(rule.variant)
                continue
            row.append(_unlisted_value(pattern_id, near_miss_supply, sequence))
        writer.writerow(row)
        rows += 1

    return ExportBuild(text=buffer.getvalue(), placed=tuple(placed), rows=rows)


def _ordinary_value(column: str, sequence: int, rng: random.Random) -> str:
    """A column no policy governs. Present because real tables have them."""

    if column == "status":
        return rng.choice(_STATUS)
    if column == "department":
        return rng.choice(_DEPARTMENT)
    if column == "action":
        return rng.choice(_ACTION)
    if column == "provider":
        return rng.choice(_PROVIDER)
    if column == "amount":
        return f"{rng.randint(15, 99999)}.{rng.randint(0, 99):02d}"
    if column == "txn_ref":
        return f"TXN-{sequence:07d}"
    # Timestamps use an implausible year, as the rest of the generator does, so
    # a generated record can never be mistaken for a real one.
    return f"2100-01-{1 + sequence % 28:02d}T{sequence % 24:02d}:00:00Z"


def _unlisted_value(pattern_id: str, supply: Any, sequence: int) -> str:
    """A value of the right kind for a party the policy does not list."""

    if supply is not None:
        near_miss = supply.take_one(pattern_id=pattern_id)
        if near_miss is not None:
            return near_miss.value
    # The supply is exhausted or disabled; fall back to something clearly
    # outside the catalog's namespace rather than risking an untracked match.
    return f"UNLISTED-{pattern_id.upper()}-{sequence:06d}"
