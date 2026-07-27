"""Natural placement of values into documents of each scenario type.

Two scenarios - small customer records and small support tickets - have had
dedicated builders that put values where they would actually appear. Every other
scenario listed a document's sensitive values in the body as
`validation_rule_1: <value>`, one numbered line each.

That is not a document anybody would ever process, and it makes a corpus that
cannot answer the question it exists to answer: a value labelled
`validation_rule_7` is trivially separable from the text around it, so nothing
about finding it resembles finding a credential inside a log line, an address in
an email thread, or an account number in a payment description. Real sensitive
data arrives unannounced and in context, which is the entire reason scanning for
it is a product.

Placement depends on two things, and both matter. **The document type** decides
the voice: a log file does not write in sentences and an agent transcript does
not write in log lines. **The kind of value** decides where in that document it
plausibly appears: a hostname turns up in a connection line, a token in an
authentication failure, a home address in a payload the application should not
have been logging in the first place. Getting only the first right produces
documents that read like a log file listing street addresses as principals.

Governed values and ungoverned ones are rendered through the same templates,
because in a real document you cannot tell from the surrounding text whether a
value happens to be on somebody's list.

Nothing here decides what the expected output is. Expected results are computed
by scanning the finished document against the full catalog, so placement affects
only where values sit, never what should happen to them.
"""
from __future__ import annotations

import random
from typing import Any, Mapping, Protocol, Sequence


class PlaceableRule(Protocol):
    category_id: str
    pattern_id: str
    variant: str


# What kind of thing a value is, which decides where it plausibly appears. A
# person, an address and a phone number are all "contact" in the broad sense and
# are written about completely differently - you copy somebody on a thread, you
# do not copy a phone number on a thread - so the precise kind is kept and only
# falls back to the broad one when a document type has nothing specific to say.
_ROLE_BY_PATTERN = {
    "person_name": "person",
    "email_address": "email",
    "phone_number": "phone",
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

# A value belongs in a field of its own name where the document has one. This is
# how the data actually arrives: an employee record has an employee_id column,
# and that is where the employee ID is.
_DIRECT_FIELD_BY_PATTERN = {
    "person_name": ("person_name", "manager", "customer_name"),
    "email_address": ("email_address", "sender"),
    "phone_number": ("phone_number",),
    "street_address": ("street_address",),
    "customer_id": ("customer_id",),
    "employee_id": ("employee_id",),
    "support_case_id": ("support_case_id",),
    "claim_number": ("claim_number",),
    "patient_id": ("patient_id",),
    "member_id": ("member_id",),
    "date_of_birth": ("date_of_birth",),
    "bank_account_number": ("bank_account_number",),
    "routing_number": ("routing_number",),
    "hostname": ("hostname",),
    "ipv4_address": ("ipv4_address",),
}

# Where the remainder goes: the part of each document type that carries free
# text. Ordered, so a document with several narrative fields spreads its content
# across them rather than piling everything into the first.
_NARRATIVE_FIELDS = {
    "customer_record": ("internal_notes",),
    "employee_record": ("internal_notes",),
    "support_ticket": ("issue_description", "internal_notes"),
    "email_message": ("message_body", "quoted_thread"),
    "application_log": ("message", "stack_trace"),
    "api_transaction": ("request_body", "response_body"),
    "financial_transaction": ("description",),
    "healthcare_claim": ("diagnosis_description",),
    "ai_interaction": (
        "user_prompt",
        "retrieved_context",
        "tool_output",
        "model_response",
    ),
}

_FALLBACK_FIELD = "internal_notes"

# When a document type has nothing specific to say about a precise kind of
# value, widen to the general one before giving up on a default.
_ROLE_FALLBACK = {
    "person": "contact",
    "email": "contact",
    "phone": "contact",
}

# Document types whose free text is written by a person, and so carries ordinary
# narrative between the parts that matter. Log lines and JSON bodies do not.
_PROSE_SCENARIOS = frozenset(
    {
        "customer_record",
        "employee_record",
        "support_ticket",
        "email_message",
        "financial_transaction",
        "healthcare_claim",
        "ai_interaction",
    }
)

# scenario -> role -> lines. "default" covers roles a document type has no
# particular place for; a value still has to go somewhere, and in a real
# document it lands in whatever free text is available.
_TEMPLATES: dict[str, dict[str, tuple[str, ...]]] = {
    "customer_record": {
        "contact": (
            "The customer asked us to copy {value} on future correspondence.",
            "Contact details confirmed on the call: {value}.",
        ),
        "personal": (
            "Identity verification used the details on file: {value}.",
            "The customer corrected their record to {value}.",
        ),
        "credential": (
            "Portal access was reset after the customer shared {value} in a chat window.",
            "Support recorded {value} while reproducing the login fault.",
        ),
        "financial": (
            "Billing review referenced {value}.",
            "The refund was applied against {value}.",
        ),
        "infrastructure": (
            "The customer's last successful session came from {value}.",
            "Portal errors were traced to {value}.",
        ),
        "reference": (
            "Cross-referenced against {value}.",
            "This account is linked to {value}.",
        ),
        "default": ("Servicing note: the account review referenced {value}.",),
    },
    "employee_record": {
        "contact": (
            "Manager correspondence goes to {value}.",
            "Emergency contact on file is {value}.",
        ),
        "personal": (
            "HR holds {value} for payroll purposes.",
            "The onboarding form recorded {value}.",
        ),
        "credential": (
            "Access review flagged {value} still provisioned to this profile.",
            "The offboarding checklist has not yet revoked {value}.",
        ),
        "financial": ("Expense reimbursement was paid to {value}.",),
        "infrastructure": ("Assigned workstation reports as {value}.",),
        "reference": ("Personnel file cross-references {value}.",),
        "default": ("HR review referenced {value}.",),
    },
    "support_ticket": {
        "contact": (
            "The customer provided {value} while we were on the call.",
            "Please follow up with {value} once the fix ships.",
        ),
        "personal": (
            "Verification details supplied by the customer: {value}.",
            "The customer read out {value} to confirm identity.",
        ),
        "credential": (
            "The customer pasted {value} into the chat before we could stop them.",
            "Reproduced the fault using {value} from the sandbox tenant.",
        ),
        "financial": (
            "The disputed charge was against {value}.",
            "Billing confirmed the invoice as {value}.",
        ),
        "infrastructure": (
            "The failure reproduces against {value}.",
            "Customer traffic is arriving from {value}.",
        ),
        "reference": ("Related to {value}.",),
        "default": ("Agent notes from the earlier contact mention {value}.",),
    },
    "email_message": {
        "person": (
            "Copying {value} so they have the full thread.",
            "{value} picked this up while I was out.",
            "I've asked {value} to take a look before we reply.",
            "This came to us via {value} originally.",
        ),
        "email": (
            "Could you confirm {value} is still the right address for them?",
            "Bouncing back from {value} - can somebody check that?",
            "I've cc'd {value} on this.",
            "Replies should go to {value} rather than the shared box.",
        ),
        "phone": (
            "Best number for them is {value} if it's easier to call.",
            "They left {value} as a callback.",
            "Tried {value} twice this morning with no answer.",
        ),
        "personal": (
            "For the file, the details we hold are {value}.",
            "> The original request listed {value}",
            "They've asked us to correct it to {value}.",
        ),
        "credential": (
            "Sandbox credentials are {value} - please don't circulate this thread.",
            "Pasting the config here since the attachment bounced: {value}",
            "The old value {value} should have been rotated last month.",
            "Support sent over {value}, which I'd rather not have in email.",
        ),
        "financial": (
            "The invoice reference is {value}.",
            "Payment went out against {value} this morning.",
            "Finance have queried {value}.",
            "Can you check whether {value} was ever settled?",
        ),
        "infrastructure": (
            "It's still failing on {value}.",
            "Logs are on {value} if you want to look.",
            "We moved that workload to {value} last week.",
            "The alert points at {value}.",
        ),
        "reference": (
            "This is all under {value}.",
            "Tracking it as {value} for now.",
            "Same root cause as {value}, I think.",
        ),
        "business": (
            "Same thing we hit on {value}.",
            "Worth flagging to whoever owns {value}.",
        ),
        "default": ("Forwarding for your records: {value}.",),
    },
    "application_log": {
        "person": ("{ts} INFO  session opened user={value}",),
        "email": (
            "{ts} INFO  session opened user={value}",
            "{ts} WARN  notification delivery failed recipient={value}",
        ),
        "phone": ("{ts} DEBUG contact record serialised msisdn={value}",),
        "personal": (
            "{ts} DEBUG profile payload serialised field={value}",
            "{ts} WARN  pii detected in request body value={value}",
        ),
        "credential": (
            "{ts} ERROR authentication rejected token={value}",
            "{ts} WARN  credential rotation overdue key={value}",
        ),
        "financial": ("{ts} DEBUG payment payload account={value}",),
        "infrastructure": (
            "{ts} INFO  upstream connection established peer={value}",
            "{ts} WARN  retry scheduled target={value}",
            "    at com.example.transport.Channel.connect({value})",
        ),
        "reference": (
            "{ts} INFO  request completed reference={value}",
            "{ts} DEBUG cache lookup key={value}",
        ),
        "business": ("{ts} INFO  feature scope evaluated scope={value}",),
        "default": ("{ts} INFO  context={value}",),
    },
    "api_transaction": {
        "contact": ('  "email": "{value}",',),
        "personal": ('  "address": "{value}",', '  "date_of_birth": "{value}",'),
        "credential": (
            '  "authorization": "{value}",',
            '  "api_key": "{value}",',
        ),
        "financial": ('  "account": "{value}",', '  "instrument": "{value}",'),
        "infrastructure": ('  "host": "{value}",', '  "callback_url": "{value}",'),
        "reference": ('  "reference": "{value}",', '  "correlation_id": "{value}",'),
        "business": ('  "product": "{value}",',),
        "default": ('  "value": "{value}",',),
    },
    "financial_transaction": {
        "financial": (
            "Settlement reference {value}.",
            "Funds drawn from {value}.",
        ),
        "contact": ("Payer contact recorded as {value}.",),
        "personal": ("Beneficiary details on the instruction: {value}.",),
        "reference": ("Reconciliation matched against {value}.",),
        "infrastructure": ("Instruction submitted from {value}.",),
        "credential": ("The batch was signed using {value}.",),
        "default": ("Adjustment raised in respect of {value}.",),
    },
    "healthcare_claim": {
        "reference": (
            "Prior episode recorded under {value}.",
            "Benefit checks completed against {value}.",
        ),
        "contact": ("Correspondence was sent to {value}.",),
        "personal": ("The submitting provider listed {value} on the form.",),
        "financial": ("Reimbursement was routed to {value}.",),
        "infrastructure": ("Claim was submitted through {value}.",),
        "default": ("Clinical note references {value}.",),
    },
    "ai_interaction": {
        "contact": (
            "Can you pull up everything we have for {value}?",
            "The customer on this thread is {value}.",
        ),
        "personal": (
            "The retrieved record shows {value}.",
            "Source document says {value} - should that be in the summary?",
        ),
        "credential": (
            "The connector config still has {value} in it.",
            "Tool call failed; the trace includes {value}.",
        ),
        "financial": ("The charge was made against {value}.",),
        "infrastructure": ("Context retrieved from {value}.",),
        "reference": ("This relates to {value}.",),
        "business": ("Scoped under {value}.",),
        "default": ("Retrieved context: {value}.",),
    },
}

_GENERIC_TEMPLATES: dict[str, tuple[str, ...]] = {
    "default": (
        "Reference recorded during processing: {value}.",
        "The record carries {value}.",
    )
}

# Some text is shorter than the value it came from because something shortened
# it, and that something is visible in the sentence. A masked card number
# appears where a receipt was quoted; a value cut short appears where a field
# was too narrow. Placing them through the ordinary templates would read wrong -
# nobody copies a truncated identifier onto an email thread.
_SHORTENED_TEMPLATES: dict[str, tuple[str, ...]] = {
    "masked": (
        "The receipt shows {value}.",
        "Statement line reads {value}.",
        "The customer could only quote {value} over the phone.",
        "Confirmation email showed {value}.",
        "Only {value} is visible in the portal.",
    ),
    "truncated": (
        "The export column shows {value}.",
        "Search was run on {value} with no result.",
        "The reference was recorded as {value} before the field ran out.",
        "Log line shows {value}, cut off at the field width.",
        "Ticket quotes {value} without the rest of it.",
    ),
}

# In a log or an API body the shortening needs no explanation - the field simply
# holds what fits.
_STRUCTURED_SCENARIOS = frozenset({"application_log", "api_transaction"})


def narrative_line(
    scenario_name: str,
    value: str,
    rng: random.Random,
    pattern_id: str = "",
    sequence: int = 0,
    kind: str = "",
) -> str:
    """One line of `scenario_name`'s document type carrying `value`."""

    if kind in _SHORTENED_TEMPLATES and scenario_name not in _STRUCTURED_SCENARIOS:
        return rng.choice(_SHORTENED_TEMPLATES[kind]).format(value=value)

    scenario_templates = _TEMPLATES.get(scenario_name, _GENERIC_TEMPLATES)
    role = _ROLE_BY_PATTERN.get(pattern_id, "default")
    templates = (
        scenario_templates.get(role)
        or scenario_templates.get(_ROLE_FALLBACK.get(role, ""), ())
        or scenario_templates.get("default", _GENERIC_TEMPLATES["default"])
    )
    return rng.choice(templates).format(value=value, ts=_timestamp(sequence))


def _timestamp(sequence: int) -> str:
    """A log timestamp that advances down the file, as a real one does.

    Year 2100 for the same reason the rest of the generator uses an implausible
    one: a generated record must never be mistakable for a real one, and a
    wall-clock value leaking into output should be obvious on sight.
    """
    total = 37_931 + sequence * 7
    return (
        f"2100-01-15T{(total // 3600) % 24:02d}:"
        f"{(total // 60) % 60:02d}:{total % 60:02d}Z"
    )


def place_rules(
    record: dict[str, Any],
    scenario_name: str,
    rules: Sequence[PlaceableRule],
    rng: random.Random,
    near_miss_supply: Any = None,
    byte_budget: int | None = None,
) -> None:
    """Put every value in `rules` somewhere a real document would put it.

    Almost-matching text from `near_miss_supply`, when given, is placed through
    the same templates and interleaved with the governed values. A document does
    not group its references by whether they are watched.

    `byte_budget` is the size this document is meant to come out at. Governed
    values are always placed - they are what the document is for - and the rest
    of the content fills whatever room is left, so a record stays the size its
    profile says it is.
    """
    from framework.workload import prose

    occupied: set[str] = set()
    remaining: list[PlaceableRule] = []

    for rule in rules:
        field = _direct_field_for(record, rule.pattern_id, occupied)
        if field is None:
            remaining.append(rule)
            continue
        record[field] = rule.variant
        occupied.add(field)

    lines: list[str] = [
        narrative_line(scenario_name, rule.variant, rng, rule.pattern_id, sequence)
        for sequence, rule in enumerate(remaining)
    ]
    room = _remaining_room(record, lines, byte_budget)

    if near_miss_supply is not None:
        weave_prose = scenario_name in _PROSE_SCENARIOS
        sequence = len(lines)
        while room > 0:
            near_miss = near_miss_supply.take_one()
            if near_miss is None:
                break
            line = narrative_line(
                scenario_name,
                near_miss.value,
                rng,
                near_miss.pattern_id,
                sequence,
                near_miss.kind,
            )
            sequence += 1
            # Slotted in among the governed values rather than appended after
            # them: nothing sorts a note by whether its references are watched.
            lines.insert(rng.randrange(len(lines) + 1), line)
            room -= len(line.encode("utf-8")) + 1
            if weave_prose and room > 0 and rng.random() < 0.45:
                filler = prose.sentence(rng)
                lines.insert(rng.randrange(len(lines) + 1), filler)
                room -= len(filler.encode("utf-8")) + 1

    if lines:
        _append_narrative(record, scenario_name, lines)


def _remaining_room(
    record: Mapping[str, Any],
    lines: Sequence[str],
    byte_budget: int | None,
) -> int:
    """How many more bytes of content this document has room for."""

    if byte_budget is None:
        return 1 << 30
    import json

    used = len(json.dumps(record, sort_keys=True).encode("utf-8"))
    used += sum(len(line.encode("utf-8")) + 1 for line in lines)
    return byte_budget - used


def _direct_field_for(
    record: Mapping[str, Any], pattern_id: str, occupied: set[str]
) -> str | None:
    for field in _DIRECT_FIELD_BY_PATTERN.get(pattern_id, ()):
        if field in record and field not in occupied:
            return field
    return None


def _append_narrative(
    record: dict[str, Any],
    scenario_name: str,
    lines: Sequence[str],
) -> None:
    """Spread `lines` across whichever narrative fields the document has."""

    candidates = [
        field
        for field in _NARRATIVE_FIELDS.get(scenario_name, (_FALLBACK_FIELD,))
        if field in record
    ]
    if not candidates:
        candidates = [
            field
            for field in (_FALLBACK_FIELD, "description", "message", "notes")
            if field in record
        ] or [_FALLBACK_FIELD]

    buckets: dict[str, list[str]] = {field: [] for field in candidates}
    for position, line in enumerate(lines):
        buckets[candidates[position % len(candidates)]].append(line)

    for field, field_lines in buckets.items():
        if not field_lines:
            continue
        existing = record.get(field, "")
        if isinstance(existing, (dict, list)):
            # A structured field - API headers, for example - keeps its shape.
            # The narrative goes alongside it rather than flattening it.
            record[f"{field}_text"] = "\n".join(field_lines)
            continue
        existing_text = str(existing).strip()
        record[field] = "\n".join(
            [part for part in (existing_text, *field_lines) if part]
        )
