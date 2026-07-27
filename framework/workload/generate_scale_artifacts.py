"""Generate canonical validation artifacts from a scale workload definition."""

from __future__ import annotations

import json
import os
import random
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from framework.policy.matching import (
    LiteralMatcher,
    overlapping_matches,
    resolve_non_overlapping,
)
from framework.policy.overlap import find_contained_literals
from framework.scenarios.placement import place_rules
from framework.scenarios.support_ticket import build_support_ticket
from framework.workload import near_miss as near_miss_module
from framework.workload import prose
from framework.workload.generate_workload import (
    _generate_field_value,
    _pad_document,
    _serialize_record,
    _weighted_item,
    load_workload,
)
from framework.workload.near_miss import (
    NearMiss,
    NearMissFactory,
    NearMissSupply,
    reference_sentence,
)


@dataclass(frozen=True)
class ScaleRule:
    rule_id: str
    category_id: str
    pattern_id: str
    variant: str
    replacement: str


ScaleProgressCallback = Callable[[str, int, int], None]


def _report_progress(
    callback: ScaleProgressCallback | None,
    event: str,
    completed: int,
    total: int,
) -> None:
    if callback is not None:
        callback(event, completed, total)


def is_scale_workload(config: Mapping[str, Any]) -> bool:
    """Return whether a loaded configuration uses the workload schema."""

    return all(key in config for key in ("name", "seed", "policy", "documents"))


# Themis truncates replacement strings to 15 characters at runtime (KB-001),
# and comparison normalises expected values to match. Truncation is not
# injective, so two replacement tokens sharing a 15-character prefix become
# indistinguishable and the framework cannot tell whether the runtime applied
# the right rule. Category names are abbreviated to keep tokens distinct inside
# that budget.
REPLACEMENT_TRUNCATION_LIMIT = 15

# How many distinct unwatched values a corpus draws on, at minimum. Small
# policies still sit in a world containing many more parties than they list.
_NEAR_MISS_POOL_MINIMUM = 2000

_CATEGORY_ABBREVIATIONS = {
    "business_terms": "BIZ",
    "credentials": "CRED",
    "financial": "FIN",
    "healthcare": "HEALTH",
    "infrastructure": "INFRA",
}

# Patterns whose names share a long prefix and would otherwise collide inside
# the truncation budget - "internal_url" and "internal_product_name" both
# reduce to "INTERNAL_" once a category prefix is applied.
_PATTERN_ABBREVIATIONS = {
    "internal_url": "URL",
    "internal_product_name": "PRODUCT",
}


def _replacement_token(category_id: str, pattern_id: str) -> str:
    category = _CATEGORY_ABBREVIATIONS.get(category_id, category_id.upper())
    pattern = _PATTERN_ABBREVIATIONS.get(pattern_id, pattern_id.upper())
    return f"[{category}:{pattern}]"


def _assert_replacements_distinct_when_truncated(rules: list[ScaleRule]) -> None:
    """Every replacement must survive KB-001 truncation distinguishably.

    Without this, `compare --replacement-max-length 15` silently scores a
    wrong-rule application as PASS. Three [BUSINESS_TERMS:*] tokens previously
    collapsed to "[BUSINESS_TERMS", covering 4,755 transformations in a
    qualification run that reported 100%.
    """
    collapsed: dict[str, set[str]] = {}
    for rule in rules:
        key = rule.replacement[:REPLACEMENT_TRUNCATION_LIMIT]
        collapsed.setdefault(key, set()).add(rule.replacement)

    collisions = {
        key: sorted(values)
        for key, values in collapsed.items()
        if len(values) > 1
    }
    if collisions:
        detail = "; ".join(
            f"{key!r} <- {values}" for key, values in sorted(collisions.items())
        )
        raise ValueError(
            f"Replacement tokens collide when truncated to "
            f"{REPLACEMENT_TRUNCATION_LIMIT} characters, so validation cannot "
            f"distinguish which rule the runtime applied: {detail}"
        )


def _rule_catalog(workload: Mapping[str, Any]) -> list[ScaleRule]:
    policy = workload.get("policy")
    if not isinstance(policy, Mapping):
        raise ValueError("'policy' must be a mapping.")

    rule_count = int(policy.get("rule_count", 0))
    families = policy.get("families")
    if rule_count < 1:
        raise ValueError("'policy.rule_count' must be at least 1.")
    if not isinstance(families, Mapping) or not families:
        raise ValueError("'policy.families' must be a non-empty mapping.")

    rng = random.Random(int(workload["seed"]))
    rules: list[ScaleRule] = []
    used_variants: set[str] = set()
    for index in range(1, rule_count + 1):
        category_id, family = _weighted_item(families, rng)
        patterns = family.get("patterns")
        if not isinstance(patterns, list) or not patterns:
            raise ValueError(
                f"'policy.families.{category_id}.patterns' must be a non-empty list."
            )
        pattern_id = str(patterns[(index - 1) % len(patterns)])
        rule_id = f"rule-{index:06d}"
        variant = _unique_rule_value(
            pattern_id,
            index,
            used_variants,
            rule_count,
        )
        used_variants.add(variant)
        replacement = _replacement_token(str(category_id), pattern_id)
        rules.append(
            ScaleRule(
                rule_id=rule_id,
                category_id=str(category_id),
                pattern_id=pattern_id,
                variant=variant,
                replacement=replacement,
            )
        )
    _assert_replacements_distinct_when_truncated(rules)
    return rules


def _unique_rule_value(
    pattern_id: str,
    index: int,
    used_variants: set[str],
    rule_count: int,
) -> str:
    """Return the first deterministic, unused literal for a catalog rule."""

    for offset in range(rule_count + 1):
        variant = _realistic_rule_value(pattern_id, index + offset)
        if variant not in used_variants:
            return variant
    raise ValueError(
        f"Unable to generate a unique policy value for pattern '{pattern_id}'."
    )


def _realistic_rule_value(pattern_id: str, index: int) -> str:
    first_names = (
        "Sandra", "James", "Alicia", "Marcus", "Priya", "Daniel", "Elena",
        "Thomas", "Naomi", "Victor", "Caroline", "Anthony", "Maya", "Robert",
        "Linda", "Samuel", "Diana", "Joseph", "Rachel", "William",
    )
    last_names = (
        "Hernandez", "Lee", "Patel", "Bennett", "Ramirez", "Morgan", "Chen",
        "Williams", "Johnson", "Davis", "Taylor", "Martin", "Clark", "Lewis",
        "Walker", "Young", "King", "Wright", "Scott", "Green",
    )
    domains = (
        "brightline.co", "workhub.org", "northstar.dev", "riverbend.net",
        "cloudpeak.io", "granitehq.com", "summitworks.net", "silverline.org",
    )
    first = first_names[(index - 1) % len(first_names)]
    last = last_names[((index - 1) // len(first_names)) % len(last_names)]
    suffix = f"{index:06d}"
    generators: dict[str, Callable[[], str]] = {
        # Every variable component below is fixed width. A variable-width index
        # lets one literal sit inside another - "Elena Chen" inside "Elena Chen
        # 1327" - and overlapping matches silently corrupt Themis output
        # (ISSUE-004), so a catalog containing them cannot validate anything
        # else.
        "person_name": lambda: f"{first} {last} {index:05d}",
        "email_address": lambda: (
            f"{first}.{last}{index}@{domains[index % len(domains)]}"
        ),
        "phone_number": lambda: f"+1-704-{200 + index % 800:03d}-{index % 10000:04d}",
        "street_address": lambda: (
            f"{100000 + index} Cedar Avenue, Charlotte NC"
        ),
        "social_security_number": lambda: (
            f"{100 + index % 800:03d}-{10 + index % 90:02d}-{index % 10000:04d}"
        ),
        "date_of_birth": lambda: f"{1950 + index % 55:04d}-{1 + index % 12:02d}-{1 + index % 28:02d}",
        "api_key": lambda: f"sk_test_enterprise_{suffix}",
        "access_token": lambda: f"access_{suffix}_synthetic_demo",
        "bearer_token": lambda: f"Bearer demo.{suffix}.signature",
        "password": lambda: f"DemoPass-{suffix}!",
        "private_key_marker": lambda: f"-----BEGIN PRIVATE KEY----- DEMO-{suffix}",
        "connection_string": lambda: f"postgresql://demo{index}:safe@db-{index}.internal/customer",
        "credit_card_number": lambda: f"4111-1111-{index % 10000:04d}-{(index * 7) % 10000:04d}",
        "bank_account_number": lambda: f"{100000000000 + index}",
        "routing_number": lambda: f"{100000000 + index % 899999999:09d}",
        "iban": lambda: f"GB{10 + index % 90:02d}DEMO{index:014d}",
        "invoice_number": lambda: f"INV-{20260000 + index}",
        "ipv4_address": lambda: (
            f"10.{index % 250:03d}.{(index // 250) % 250:03d}"
            f".{1 + index % 249:03d}"
        ),
        "ipv6_address": lambda: f"2001:db8::{index:04x}",
        "hostname": lambda: f"customer-app-{index:04d}.internal.example",
        "internal_url": lambda: f"https://portal.internal.example/customers/{suffix}",
        "cloud_resource_id": lambda: f"arn:aws:s3:::synthetic-customer-{suffix}",
        "database_uri": lambda: f"postgresql://readonly@db.internal/customer_{suffix}",
        "patient_id": lambda: f"PAT-{suffix}",
        "member_id": lambda: f"MEM-{suffix}",
        "claim_number": lambda: f"CLM-{suffix}",
        "medical_record_number": lambda: f"MRN-{suffix}",
        "customer_id": lambda: f"CUST-{suffix}",
        "employee_id": lambda: f"EMP-{suffix}",
        "project_codename": lambda: f"Project Cedar-{index:05d}",
        "internal_product_name": lambda: f"Northstar Suite {index:05d}",
        "support_case_id": lambda: f"CASE-{suffix}",
        "contract_number": lambda: f"CTR-{suffix}",
    }
    if _SUPPORTED_PATTERNS is None:
        _remember_supported_patterns(tuple(sorted(generators)))
    try:
        return generators[pattern_id]()
    except KeyError as error:
        raise ValueError(f"Unsupported policy pattern: {pattern_id}") from error


_SUPPORTED_PATTERNS: tuple[str, ...] | None = None


def _remember_supported_patterns(patterns: tuple[str, ...]) -> None:
    global _SUPPORTED_PATTERNS
    _SUPPORTED_PATTERNS = patterns


def supported_patterns() -> tuple[str, ...]:
    """Every pattern id `_realistic_rule_value` can generate.

    Derived from the generator table itself so a new pattern cannot be added
    without the overlap tests covering it.
    """
    if _SUPPORTED_PATTERNS is None:
        _realistic_rule_value("person_name", 1)
    return _SUPPORTED_PATTERNS or ()


def _write_policy(path: Path, rules: list[ScaleRule]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for rule in sorted(rules, key=lambda item: (-len(item.variant), item.variant)):
            variant = rule.variant.replace("\\", "\\\\").replace('"', '\\"')
            replacement = rule.replacement.replace("\\", "\\\\").replace(
                '"', '\\"'
            )
            handle.write(f'"{variant}" -> "{replacement}";\n')
    os.replace(temporary, path)


def _deterministic_record(
    document_id: str,
    scenario_name: str,
    fields: list[str],
    rng: random.Random,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "document_id": document_id,
        "scenario": scenario_name,
        "generated_at": "2000-01-01T00:00:00Z",
    }
    for field_name in fields:
        if field_name == "timestamp":
            record[field_name] = "2000-01-01T00:00:00Z"
        else:
            record[field_name] = _generate_field_value(field_name, rng)
    return record


def _inject_rules(
    record: dict[str, Any],
    rules: list[ScaleRule],
    supply: NearMissSupply | None = None,
    rng: random.Random | None = None,
    scenario_name: str = "",
    target_size: int | None = None,
) -> None:
    """Place values into a document of this scenario's type.

    Delegates to `framework/scenarios/placement.py`, which knows where each
    document type carries free text and what that text sounds like.
    """
    place_rules(
        record,
        scenario_name,
        rules,
        rng if rng is not None else random.Random(0),
        supply,
        target_size,
    )


def _build_realistic_customer_record(
    document_id: str,
    fields: list[str],
    selected_rules: list[ScaleRule],
    catalog_values: set[str],
    rng: random.Random,
    supply: NearMissSupply | None = None,
) -> dict[str, Any]:
    record = _deterministic_record(document_id, "customer_record", fields, rng)
    _separate_customer_record_from_catalog(record, catalog_values)
    direct_fields = {
        "customer_id": "customer_id",
        "person_name": "person_name",
        "email_address": "email_address",
        "phone_number": "phone_number",
        "street_address": "street_address",
    }
    occupied: set[str] = set()
    notes = [str(record.get("internal_notes", "Account reviewed by customer care."))]
    # Accounts reference other accounts - joint holders, prior owners, the party
    # who made the referral. Whether any of them is watched is incidental.
    related = _related_accounts(supply, rng)
    if related:
        record["related_accounts"] = related
    note_templates = {
        "pii": "Identity verification recorded {pattern}: {value}.",
        "credentials": "Security review referenced {pattern}: {value}.",
        "financial": "Billing review referenced {pattern}: {value}.",
        "infrastructure": "Recent account access included {pattern}: {value}.",
        "healthcare": "Customer supplied benefit reference {pattern}: {value}.",
        "business_terms": "Account servicing referenced {pattern}: {value}.",
    }
    for rule in selected_rules:
        field_name = direct_fields.get(rule.pattern_id)
        if field_name in record and field_name not in occupied:
            record[field_name] = rule.variant
            occupied.add(field_name)
            continue
        template = note_templates.get(
            rule.category_id,
            "Customer record referenced {pattern}: {value}.",
        )
        notes.append(
            template.format(
                pattern=rule.pattern_id.replace("_", " "),
                value=rule.variant,
            )
        )
    # Servicing notes name whoever was involved, watched or not.
    if supply is not None:
        for near_miss in supply.take(rng.randint(1, 4)):
            notes.insert(
                rng.randrange(1, len(notes) + 1),
                reference_sentence(near_miss, rng),
            )
    record["internal_notes"] = " ".join(notes)

    if not selected_rules:
        serialized = json.dumps(record, sort_keys=True)
        collisions = [value for value in catalog_values if value in serialized]
        if collisions:
            raise ValueError("Clean customer record unexpectedly contains a policy value.")
    return record


def _separate_customer_record_from_catalog(
    record: dict[str, Any], catalog_values: set[str]
) -> None:
    """Move naturally generated customer values outside the policy domain.

    Values are left unchanged unless they collide with a configured detection
    literal. This keeps existing small deterministic artifacts stable while
    ensuring large catalogs cannot introduce untracked matches.
    """

    protected_fields = {"document_id", "scenario"}
    for attempt in range(1, 101):
        serialized = json.dumps(record, sort_keys=True)
        collisions = {value for value in catalog_values if value in serialized}
        if not collisions:
            return

        changed = False
        for field_name, field_value in tuple(record.items()):
            if field_name in protected_fields:
                continue
            serialized_value = json.dumps(field_value, sort_keys=True)
            if not any(value in serialized_value for value in collisions):
                continue
            record[field_name] = _disjoint_customer_value(
                field_name,
                str(record["document_id"]),
                attempt,
            )
            changed = True

        if not changed:
            break

    raise ValueError(
        "Customer record baseline could not be separated from policy values."
    )


def _disjoint_customer_value(
    field_name: str, document_id: str, attempt: int
) -> str:
    """Build a deterministic customer value in a non-policy namespace."""

    suffix = document_id.removeprefix("document-")
    values = {
        "generated_at": f"2100-01-{1 + (attempt - 1) % 28:02d}T00:00:00Z",
        "timestamp": f"2100-02-{1 + (attempt - 1) % 28:02d}T12:00:00Z",
        "customer_id": f"ACCOUNT-{suffix}-{attempt:02d}",
        "person_name": f"Quinn Okafor {suffix} {attempt}",
        "email_address": f"customer-{suffix}-{attempt}@example.invalid",
        "phone_number": f"+1-980-555-{(int(suffix) + attempt) % 10000:04d}",
        "street_address": f"{50000 + int(suffix)} Juniper Boulevard, Raleigh NC",
        "date_of_birth": f"2100-03-{1 + (attempt - 1) % 28:02d}",
        "internal_notes": (
            f"Customer service review {suffix}-{attempt} completed normally."
        ),
    }
    return values.get(
        field_name,
        f"Customer record {suffix} {field_name} value {attempt}",
    )


def _related_accounts(
    supply: NearMissSupply | None, rng: random.Random
) -> list[dict[str, str]]:
    """Other parties linked to this account, none of them on the policy list."""

    if supply is None:
        return []
    relationships = (
        "authorised contact",
        "prior account holder",
        "billing contact",
        "referred by",
        "shared household",
        "successor account",
    )
    entries: list[dict[str, str]] = []
    for near_miss in supply.take(rng.randint(0, 3), pattern_id="person_name"):
        entry = {
            "name": near_miss.value,
            "relationship": rng.choice(relationships),
        }
        reference = supply.take_one(pattern_id="customer_id")
        if reference is not None:
            entry["account_reference"] = reference.value
        entries.append(entry)
    return entries


def _expand_customer_record(
    record: dict[str, Any],
    target_size: int,
    rng: random.Random,
    supply: NearMissSupply | None = None,
) -> None:
    """Grow a record toward its size target the way a real one grows.

    A large account record is large because it has a long servicing history: many
    short entries, written at different times, each naming whoever and whatever
    was involved. Growing it that way rather than by repeating filler keeps a
    large document a plausible document.
    """
    history: list[dict[str, str]] = []
    actions = (
        "Account preferences reviewed",
        "Customer contact information confirmed",
        "Billing inquiry resolved",
        "Support follow-up scheduled",
        "Consent preferences verified",
        "Statement delivery method changed",
        "Identity documents re-verified",
        "Dispute closed without adjustment",
        "Marketing preferences updated",
        "Service tier confirmed",
    )
    channels = (
        "customer portal",
        "support desk",
        "billing team",
        "mobile app",
        "branch visit",
        "inbound call",
        "secure message",
    )
    outcomes = ("completed", "completed", "completed", "no action required", "deferred")
    desired_content_size = max(0, target_size - 256)
    while len(json.dumps(record, sort_keys=True).encode("utf-8")) < desired_content_size:
        sequence = len(history) + 1
        event = {
            "event_id": f"EVT-{sequence:04d}",
            "summary": rng.choice(actions),
            "channel": rng.choice(channels),
            "outcome": rng.choice(outcomes),
            "note": prose.sentence(rng),
        }
        near_miss = supply.take_one() if supply is not None else None
        if near_miss is not None:
            event["note"] = f"{event['note']} {reference_sentence(near_miss, rng)}"
        history.append(event)
        record["account_history"] = history


def _expected_result(
    message: str,
    matcher: LiteralMatcher,
    rules_by_variant: Mapping[str, ScaleRule],
) -> tuple[str, list[dict[str, str]], int]:
    """Compute expected output by scanning the FULL catalog.

    Computing expected output from only the rules the generator intended to
    inject is wrong: unrelated generated values collide with catalog literals
    in practice, so Themis correctly redacts a value the expected file says
    should survive and is scored as a failure.

    Returns the expected message, the match evidence, and the number of
    overlapping match pairs. A document with overlapping matches triggers
    ISSUE-004, so no expected value for it is correct; the count is surfaced
    rather than silently folded into the result.
    """
    found = matcher.find_all(message)
    overlap_count = len(overlapping_matches(found))
    selected = resolve_non_overlapping(found)

    # Apply replacements right to left so earlier offsets stay valid.
    expected = message
    for match in sorted(selected, key=lambda item: item.start, reverse=True):
        rule = rules_by_variant[match.literal]
        expected = expected[:match.start] + rule.replacement + expected[match.end:]

    matches = [
        {
            "category_id": rules_by_variant[match.literal].category_id,
            "case_id": rules_by_variant[match.literal].pattern_id,
            "variant": match.literal,
            "replacement": rules_by_variant[match.literal].replacement,
        }
        for match in sorted(selected, key=lambda item: item.start)
    ]
    return expected, matches, overlap_count


def _input_profile(
    *,
    payload_bytes_total: int,
    expected_total: int,
    near_miss_total: int,
    distinct_rules_matched: int,
    rule_count: int,
    near_miss_density: tuple[float, float] | None,
) -> dict[str, Any]:
    """The content characteristics of the generated corpus.

    Two corpora with the same record and rule counts can still be very different
    bodies of text - one where a handful of values recur constantly, one where
    thousands appear once each. Recording the difference means a result taken on
    a corpus can be read against the corpus that produced it, and two runs can be
    compared on something more than their record count.
    """
    kilobytes = payload_bytes_total / 1024.0 if payload_bytes_total else 0.0
    return {
        "matches_per_kb": round(expected_total / kilobytes, 3) if kilobytes else 0.0,
        "near_misses_per_kb": round(near_miss_total / kilobytes, 3) if kilobytes else 0.0,
        "near_miss_total": near_miss_total,
        "near_miss_configured": near_miss_density is not None,
        "near_miss_per_kb_range": (
            list(near_miss_density) if near_miss_density is not None else None
        ),
        "distinct_rules_matched": distinct_rules_matched,
        # How much of the deployed policy this corpus actually reaches. A
        # deployed rule that no document ever contains is not being validated.
        "rule_coverage": (
            round(distinct_rules_matched / rule_count, 4) if rule_count else 0.0
        ),
        "filler_mode": "per_document",
    }


def generate_scale_artifacts(
    workload_path: Path,
    output_dir: Path,
    *,
    document_count: int | None = None,
    progress_callback: ScaleProgressCallback | None = None,
) -> dict[str, Any]:
    """Generate policy, input, expected, and metadata artifacts for a workload."""

    workload = load_workload(workload_path)
    if not is_scale_workload(workload):
        raise ValueError("Configuration is not an enterprise workload schema.")
    _report_progress(
        progress_callback,
        "configuration_loaded",
        int(workload["policy"]["rule_count"]),
        int(workload["documents"]["count"]),
    )

    documents = workload["documents"]
    requested_rules = int(workload["policy"]["rule_count"])
    _report_progress(progress_callback, "rules_started", 0, requested_rules)
    rules = _rule_catalog(workload)
    # A catalog containing literals that sit inside one another cannot validate
    # transformation correctness: every document carrying the outer literal
    # also matches the inner one, and overlapping matches corrupt Themis output
    # silently. Fail here rather than produce a corpus that cannot answer the
    # question it was generated to answer.
    contained_literals = find_contained_literals(rule.variant for rule in rules)
    if contained_literals:
        examples = "; ".join(
            f"{inner!r} inside {outer!r}"
            for inner, outer in contained_literals[:3]
        )
        raise ValueError(
            f"Rule catalog contains {len(contained_literals)} literal pair(s) "
            f"where one literal occurs inside another, which triggers ISSUE-004 "
            f"and makes transformation results meaningless. Examples: {examples}"
        )
    _report_progress(
        progress_callback, "rules_completed", len(rules), requested_rules
    )
    requested_records = int(documents["count"])
    realized_records = (
        requested_records if document_count is None else int(document_count)
    )
    if realized_records < 1:
        raise ValueError("Document count must be at least 1.")
    progress_interval = int(documents.get("progress_interval_records", 1000))
    if progress_interval < 1:
        raise ValueError("'documents.progress_interval_records' must be at least 1.")

    output_dir.mkdir(parents=True, exist_ok=True)
    policy_path = output_dir / "scale-policy.nol"
    input_path = output_dir / "input.jsonl"
    expected_path = output_dir / "expected.jsonl"
    manifest_path = output_dir / "manifest.json"
    input_temporary = input_path.with_name(f".{input_path.name}.tmp")
    expected_temporary = expected_path.with_name(f".{expected_path.name}.tmp")

    _write_policy(policy_path, rules)
    rng = random.Random(int(workload["seed"]))
    clean_count = 0
    dirty_count = 0
    expected_total = 0
    scenario_counts: Counter[str] = Counter()
    format_counts: Counter[str] = Counter()
    match_profile_counts: Counter[str] = Counter()
    size_profile_counts: Counter[str] = Counter()
    payload_bytes_total = 0
    payload_bytes_min: int | None = None
    payload_bytes_max = 0
    padding_bytes_total = 0
    padded_document_count = 0
    generation_mode_counts: Counter[str] = Counter()
    documents_with_overlaps = 0
    overlap_examples: list[str] = []
    intended_clean_with_literals = 0

    # Built once, scanned per document. A per-rule scan would be
    # rules x documents substring searches - 50 million for the 5,000 rule
    # by 10,000 document qualification.
    rules_by_variant = {rule.variant: rule for rule in rules}
    literal_matcher = LiteralMatcher(rules_by_variant)

    # Values of the same kinds as the catalog that are not on it. Absent from
    # the workload config means disabled, so a workload written before this
    # option existed produces byte-identical artifacts to before.
    near_miss_density = near_miss_module.parse_density(
        documents.get("near_miss_distribution")
    )
    near_miss_pool: tuple[NearMiss, ...] = ()
    if near_miss_density is not None:
        literals_by_pattern: dict[str, list[str]] = {}
        for rule in rules:
            literals_by_pattern.setdefault(rule.pattern_id, []).append(rule.variant)
        near_miss_factory = NearMissFactory(
            matcher=literal_matcher,
            literals_by_pattern=literals_by_pattern,
        )
        # The almost-matching text a corpus draws on, sized against the catalog
        # so a large policy is surrounded by correspondingly varied text, with a
        # floor so a small policy is not surrounded by three strings.
        near_miss_pool = near_miss_factory.build_pool(
            max(_NEAR_MISS_POOL_MINIMUM, len(rules)),
            random.Random(int(workload["seed"]) + 1),
        )
    near_miss_total = 0
    matched_variants: set[str] = set()

    _report_progress(
        progress_callback, "documents_started", 0, realized_records
    )
    _report_progress(
        progress_callback, "expected_started", 0, realized_records
    )

    try:
        with input_temporary.open("w", encoding="utf-8") as input_handle, \
                expected_temporary.open("w", encoding="utf-8") as expected_handle:
            for index in range(1, realized_records + 1):
                document_id = f"document-{index:06d}"
                scenario_name, scenario = _weighted_item(documents["scenarios"], rng)
                format_name, _ = _weighted_item(documents["formats"], rng)
                match_profile_name, match_profile = _weighted_item(
                    documents["match_distribution"], rng
                )
                size_profile_name, size_profile = _weighted_item(
                    documents["size_distribution"], rng
                )
                match_range = match_profile["matches_per_document"]
                match_count = rng.randint(
                    int(match_range["minimum"]), int(match_range["maximum"])
                )
                selected_rules = rng.sample(rules, k=min(match_count, len(rules)))

                target_size = rng.randint(
                    int(size_profile["minimum_bytes"]),
                    int(size_profile["maximum_bytes"]),
                )

                # Sized from the document, not from how many of its identifiers
                # happen to be watched: the share of a record that looks like an
                # identifier is a property of the record.
                near_miss_supply = NearMissSupply(
                    near_miss_pool,
                    rng,
                    near_miss_module.density_budget(
                        target_size, near_miss_density, rng
                    )
                    if near_miss_density is not None
                    else 0,
                )

                realistic_scenario = (
                    size_profile_name == "small"
                    and (
                        (
                            scenario_name == "customer_record"
                            and format_name in {"json", "csv"}
                        )
                        or (
                            scenario_name == "support_ticket"
                            and format_name == "json"
                        )
                    )
                )
                if (
                    scenario_name == "customer_record"
                    and format_name in {"json", "csv"}
                    and size_profile_name == "small"
                ):
                    record = _build_realistic_customer_record(
                        document_id,
                        list(scenario["fields"]),
                        selected_rules,
                        {rule.variant for rule in rules},
                        rng,
                        near_miss_supply,
                    )
                    _expand_customer_record(
                        record, target_size, rng, near_miss_supply
                    )
                elif (
                    scenario_name == "support_ticket"
                    and format_name == "json"
                    and size_profile_name == "small"
                ):
                    support_ticket = build_support_ticket(
                        document_id,
                        scenario,
                        rng,
                        selected_rules,
                        {rule.variant for rule in rules},
                        near_miss_supply,
                    )
                    record = support_ticket.record
                    selected_rules = [
                        placement.rule for placement in support_ticket.placements
                    ]
                else:
                    record = _deterministic_record(
                        document_id,
                        scenario_name,
                        list(scenario["fields"]),
                        rng,
                    )
                    _inject_rules(
                        record,
                        selected_rules,
                        near_miss_supply,
                        rng,
                        scenario_name,
                        target_size,
                    )
                message = _serialize_record(
                    record=record,
                    format_name=format_name,
                    scenario_name=scenario_name,
                )
                unpadded_size = len(message.encode("utf-8"))
                if (
                    bool(size_profile.get("pad_to_target", False))
                    and not realistic_scenario
                ):
                    message = _pad_document(
                        content=message,
                        target_size=target_size,
                        format_name=format_name,
                        random_source=rng,
                    )
                padding_bytes = max(0, len(message.encode("utf-8")) - unpadded_size)
                padding_bytes_total += padding_bytes
                padded_document_count += padding_bytes > 0
                generation_mode_counts[
                    "realistic" if realistic_scenario else "scale"
                ] += 1
                if index % progress_interval == 0 or index == realized_records:
                    _report_progress(
                        progress_callback,
                        "documents_progress",
                        index,
                        realized_records,
                    )

                # Scan the full catalog, not just the injected rules. Values
                # generated for unrelated fields collide with catalog literals
                # in practice, and attributing those to the product produces
                # false failures.
                expected_message, expected_matches, overlap_count = _expected_result(
                    message, literal_matcher, rules_by_variant
                )
                kind = "dirty" if expected_matches else "clean"
                near_miss_total += near_miss_supply.used
                matched_variants.update(match["variant"] for match in expected_matches)

                if overlap_count:
                    documents_with_overlaps += 1
                    if len(overlap_examples) < 5:
                        overlap_examples.append(document_id)
                if not selected_rules and expected_matches:
                    # Intended to be a clean record but carries catalog
                    # literals anyway. Surfaced rather than silently rewritten.
                    intended_clean_with_literals += 1

                input_handle.write(
                    json.dumps(
                        {"record_id": document_id, "kind": kind, "message": message},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                expected_handle.write(
                    json.dumps(
                        {
                            "record_id": document_id,
                            "kind": kind,
                            "expected_message": expected_message,
                            "expected_match_count": len(expected_matches),
                            "expected_matches": expected_matches,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                scenario_counts[scenario_name] += 1
                format_counts[format_name] += 1
                match_profile_counts[match_profile_name] += 1
                size_profile_counts[size_profile_name] += 1
                message_size = len(message.encode("utf-8"))
                payload_bytes_total += message_size
                payload_bytes_min = (
                    message_size
                    if payload_bytes_min is None
                    else min(payload_bytes_min, message_size)
                )
                payload_bytes_max = max(payload_bytes_max, message_size)
                expected_total += len(expected_matches)
                if kind == "dirty":
                    dirty_count += 1
                else:
                    clean_count += 1
                if index % progress_interval == 0 or index == realized_records:
                    _report_progress(
                        progress_callback,
                        "expected_progress",
                        index,
                        realized_records,
                    )
        _report_progress(progress_callback, "artifacts_started", 0, 0)
        os.replace(input_temporary, input_path)
        os.replace(expected_temporary, expected_path)
    except Exception:
        input_temporary.unlink(missing_ok=True)
        expected_temporary.unlink(missing_ok=True)
        raise

    manifest = {
        "generator_version": 1,
        "generator_schema": "enterprise-dlp-scale",
        "workload_name": workload["name"],
        "workload_version": workload.get("version"),
        "seed": workload["seed"],
        "requested_records": requested_records,
        "realized_records": realized_records,
        "requested_rules": requested_rules,
        "realized_rules": len(rules),
        "clean_record_count": clean_count,
        "dirty_record_count": dirty_count,
        "scenario_distribution": dict(sorted(scenario_counts.items())),
        "format_distribution": dict(sorted(format_counts.items())),
        "match_profile_distribution": dict(sorted(match_profile_counts.items())),
        "size_profile_distribution": dict(sorted(size_profile_counts.items())),
        "payload_bytes_total": payload_bytes_total,
        "payload_bytes_minimum": payload_bytes_min or 0,
        "payload_bytes_maximum": payload_bytes_max,
        "payload_bytes_average": round(
            payload_bytes_total / realized_records, 3
        ),
        "padding_bytes_total": padding_bytes_total,
        "padded_document_count": padded_document_count,
        "generation_mode_distribution": dict(
            sorted(generation_mode_counts.items())
        ),
        # ISSUE-004 exposure. Documents whose matches overlap cannot produce a
        # correct expected value, because the runtime corrupts them. Recorded
        # so a qualification run cannot silently include them.
        "overlapping_match_documents": documents_with_overlaps,
        "overlapping_match_examples": overlap_examples,
        "intended_clean_with_literals": intended_clean_with_literals,
        # What this corpus actually contains, as distinct from what was asked
        # for. Any result quoted from a run should be quoted with it.
        "input_profile": _input_profile(
            payload_bytes_total=payload_bytes_total,
            expected_total=expected_total,
            near_miss_total=near_miss_total,
            distinct_rules_matched=len(matched_variants),
            rule_count=len(rules),
            near_miss_density=near_miss_density,
        ),
        "requested_scale": {
            "rule_count": requested_rules,
            "record_count": requested_records,
            "policy_families": deepcopy(workload["policy"]["families"]),
            "scenarios": deepcopy(documents["scenarios"]),
            "formats": deepcopy(documents["formats"]),
            "match_distribution": deepcopy(documents["match_distribution"]),
            "size_distribution": deepcopy(documents["size_distribution"]),
        },
        "realized_scale": {
            "rule_count": len(rules),
            "record_count": realized_records,
            "policy_family_distribution": dict(
                sorted(Counter(rule.category_id for rule in rules).items())
            ),
            "scenario_distribution": dict(sorted(scenario_counts.items())),
            "format_distribution": dict(sorted(format_counts.items())),
            "match_profile_distribution": dict(
                sorted(match_profile_counts.items())
            ),
            "size_profile_distribution": dict(sorted(size_profile_counts.items())),
            "payload_bytes": {
                "total": payload_bytes_total,
                "minimum": payload_bytes_min or 0,
                "maximum": payload_bytes_max,
                "average": round(payload_bytes_total / realized_records, 3),
            },
            "padding_bytes_total": padding_bytes_total,
            "padded_document_count": padded_document_count,
            "generation_mode_distribution": dict(
                sorted(generation_mode_counts.items())
            ),
        },
        "expected_total_matches": expected_total,
        "rule_catalog": [
            {
                "rule_id": rule.rule_id,
                "category_id": rule.category_id,
                "pattern_id": rule.pattern_id,
                "variant": rule.variant,
                "replacement": rule.replacement,
            }
            for rule in rules
        ],
        "artifacts": {
            "policy": "scale-policy.nol",
            "input": "input.jsonl",
            "expected": "expected.jsonl",
        },
    }
    temporary_manifest = manifest_path.with_name(f".{manifest_path.name}.tmp")
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_manifest, manifest_path)
    _report_progress(progress_callback, "complete", realized_records, realized_records)
    return manifest
