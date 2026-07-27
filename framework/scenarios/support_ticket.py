"""Build realistic deterministic support-ticket records."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence


class SupportTicketRule(Protocol):
    category_id: str
    pattern_id: str
    variant: str


@dataclass(frozen=True)
class RulePlacement:
    rule: SupportTicketRule
    field_path: str


@dataclass(frozen=True)
class SupportTicketBuild:
    record: dict[str, Any]
    placements: tuple[RulePlacement, ...]


def build_support_ticket(
    document_id: str,
    scenario_config: Mapping[str, Any],
    random_source: random.Random,
    selected_rules: Sequence[SupportTicketRule],
    catalog_values: set[str],
    near_miss_supply: Any = None,
) -> SupportTicketBuild:
    """Return a coherent record and exact evidence for every placed rule.

    `near_miss_supply`, when given, is drawn on for identifier-shaped values
    that are *not* in the catalog - linked cases, other participants in the
    thread, hosts named while troubleshooting. A real ticket is full of them and
    almost none of them are governed; see `framework/workload/near_miss.py`.
    """

    priorities = ("low", "normal", "high", "urgent")
    subjects = (
        "Unable to complete account verification",
        "Billing profile update requires assistance",
        "Customer portal access needs review",
        "Account contact details could not be updated",
    )
    suffix = document_id.rsplit("-", 1)[-1]
    record: dict[str, Any] = {
        "document_id": document_id,
        "scenario": "support_ticket",
        "ticket_id": f"DEMO-CASE-{suffix}",
        "customer_id": f"DEMO-CUSTOMER-{suffix}",
        "customer_name": random_source.choice(
            ("Jordan Ellis", "Morgan Brooks", "Casey Rivera", "Taylor Monroe")
        ),
        "requester_email": f"requester-{suffix}@example.invalid",
        "customer_contact": {"phone_number": f"+1-980-555-{int(suffix) % 10000:04d}"},
        "priority": random_source.choice(priorities),
        "status": "open",
        "subject": random_source.choice(subjects),
        "issue_description": (
            "Customer reported a verification issue after updating account "
            "information through the self-service portal."
        ),
        "conversation_history": [
            {
                "timestamp": "2100-01-15T10:32:00Z",
                "author": "support-agent",
                "message": "Verification details were reviewed with the customer.",
            }
        ],
        "internal_notes": "Account ownership checks are pending final review.",
        "security_notes": [],
        "payment_notes": [],
    }

    direct_fields = {
        "support_case_id": "ticket_id",
        "customer_id": "customer_id",
        "person_name": "customer_name",
        "email_address": "requester_email",
    }
    occupied: set[str] = set()
    placements: list[RulePlacement] = []

    for rule in selected_rules:
        direct_field = direct_fields.get(rule.pattern_id)
        if direct_field is not None and direct_field not in occupied:
            record[direct_field] = rule.variant
            occupied.add(direct_field)
            placements.append(RulePlacement(rule, direct_field))
            continue

        if rule.pattern_id == "phone_number" and "customer_contact.phone_number" not in occupied:
            record["customer_contact"]["phone_number"] = rule.variant
            occupied.add("customer_contact.phone_number")
            placements.append(RulePlacement(rule, "customer_contact.phone_number"))
            continue

        if rule.category_id == "credentials":
            record["security_notes"].append(
                f"Troubleshooting reference for {rule.pattern_id.replace('_', ' ')}: {rule.variant}."
            )
            field_path = f"security_notes[{len(record['security_notes']) - 1}]"
        elif rule.category_id == "financial":
            record["payment_notes"].append(
                f"Billing discussion referenced {rule.pattern_id.replace('_', ' ')}: {rule.variant}."
            )
            field_path = f"payment_notes[{len(record['payment_notes']) - 1}]"
        elif rule.pattern_id in {"person_name", "email_address", "phone_number"}:
            record["conversation_history"].append(
                {
                    "timestamp": "2100-01-15T10:41:00Z",
                    "author": "customer",
                    "message": (
                        f"Customer supplied {rule.pattern_id.replace('_', ' ')} "
                        f"{rule.variant} for verification."
                    ),
                }
            )
            field_path = (
                f"conversation_history[{len(record['conversation_history']) - 1}].message"
            )
        else:
            record["internal_notes"] += (
                f" Ticket metadata referenced {rule.pattern_id.replace('_', ' ')}: "
                f"{rule.variant}."
            )
            field_path = "internal_notes"
        placements.append(RulePlacement(rule, field_path))

    _add_ticket_context(record, random_source, near_miss_supply)

    if not selected_rules:
        _separate_ticket_from_catalog(record, catalog_values)

    return SupportTicketBuild(record=record, placements=tuple(placements))


def _add_ticket_context(
    record: dict[str, Any],
    random_source: random.Random,
    supply: Any,
) -> None:
    """Add the references a real ticket carries that are not governed values.

    Tickets are cross-referenced: a duplicate was raised, an earlier case
    covered the same fault, another agent picked it up overnight, the failure
    was traced to a particular host. These are ordinary content. Placing them
    here rather than in a dedicated block keeps them mixed in with the governed
    values, which is where they occur.
    """
    if supply is None:
        return

    from framework.workload.near_miss import reference_sentence

    linked = [near_miss.value for near_miss in supply.take(
        random_source.randint(0, 3), pattern_id="support_case_id"
    )]
    if linked:
        record["linked_cases"] = linked

    for near_miss in supply.take(random_source.randint(0, 2)):
        record["conversation_history"].append(
            {
                "timestamp": "2100-01-15T11:04:00Z",
                "author": random_source.choice(("support-agent", "customer", "reviewer")),
                "message": reference_sentence(near_miss, random_source),
            }
        )

    for near_miss in supply.take(random_source.randint(0, 2), pattern_id="hostname"):
        record["security_notes"].append(reference_sentence(near_miss, random_source))

    trailing = supply.take(random_source.randint(0, 2))
    if trailing:
        record["internal_notes"] += " " + " ".join(
            reference_sentence(near_miss, random_source) for near_miss in trailing
        )


def _separate_ticket_from_catalog(
    record: dict[str, Any], catalog_values: set[str]
) -> None:
    """Move generated ticket values outside the policy domain.

    This previously raised when a clean ticket contained a catalog literal,
    which aborted generation entirely at realistic rule counts - the value it
    tripped on was the generator's own identifier. It passed only because the
    test fixture used a rule count small enough to select no colliding rule.

    Expected output is now computed by scanning the full catalog, so a stray
    literal no longer corrupts the expected result; it only mislabels a record
    as clean. Generation reports the count, so repairing quietly here does not
    hide the condition. Aborting a 10,000 document run over one identifier
    collision is strictly worse.
    """
    rewritable = ("ticket_id", "customer_id", "requester_email")
    for attempt in range(1, 101):
        serialized = json.dumps(record, sort_keys=True)
        collisions = {value for value in catalog_values if value in serialized}
        if not collisions:
            return

        changed = False
        for field_name in rewritable:
            value = record.get(field_name)
            if not isinstance(value, str):
                continue
            if not any(collision in value for collision in collisions):
                continue
            record[field_name] = f"{field_name.upper()}-SYNTHETIC-{attempt:03d}-" + (
                str(record["document_id"]).rsplit("-", 1)[-1]
            )
            changed = True

        if not changed:
            # The collision is in a field this function does not own. Leave the
            # record intact; generation records it as carrying literals.
            return
