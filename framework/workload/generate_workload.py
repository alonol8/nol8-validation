"""Synthetic workload document generation.

This module reads a workload definition and creates deterministic synthetic
documents for validation runs. It does not create run directories, execute
engines, or write the run manifest. Those responsibilities belong to the CLI
and orchestration layers.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from xml.etree.ElementTree import Element, SubElement, tostring

import yaml

from framework.workload import prose


@dataclass(frozen=True)
class GeneratedDocument:
    """Metadata describing one generated document."""

    document_id: str
    filename: str
    relative_path: str
    scenario: str
    document_format: str
    match_profile: str
    size_profile: str
    expected_matches: int
    size_bytes: int
    sha256: str


def load_workload(workload_path: str | Path) -> dict[str, Any]:
    """Load and minimally validate a workload YAML file."""

    path = Path(workload_path)

    if not path.is_file():
        raise FileNotFoundError(f"Workload file does not exist: {path}")

    with path.open("r", encoding="utf-8") as handle:
        workload = yaml.safe_load(handle)

    if not isinstance(workload, dict):
        raise ValueError("Workload YAML must contain a top-level mapping.")

    required_sections = ("name", "seed", "documents")
    missing = [section for section in required_sections if section not in workload]

    if missing:
        raise ValueError(
            f"Workload is missing required sections: {', '.join(missing)}"
        )

    documents = workload["documents"]

    if not isinstance(documents, dict):
        raise ValueError("'documents' must be a mapping.")

    for required in (
        "count",
        "scenarios",
        "formats",
        "match_distribution",
        "size_distribution",
    ):
        if required not in documents:
            raise ValueError(f"'documents.{required}' is required.")

    return workload


def generate_workload(
    workload_path: str | Path,
    output_directory: str | Path,
    *,
    document_count: int | None = None,
) -> list[GeneratedDocument]:
    """Generate synthetic documents from a workload definition.

    Args:
        workload_path:
            Path to the workload YAML file.
        output_directory:
            Directory in which the generated document files will be written.
        document_count:
            Optional override used for smoke tests and smaller validation runs.

    Returns:
        Metadata for each generated document.
    """

    workload = load_workload(workload_path)
    document_config = workload["documents"]

    configured_count = int(document_config["count"])
    count = configured_count if document_count is None else int(document_count)

    if count < 1:
        raise ValueError("Document count must be at least 1.")

    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)

    random_source = random.Random(int(workload["seed"]))
    generated: list[GeneratedDocument] = []

    for index in range(1, count + 1):
        document_id = f"document-{index:06d}"

        scenario_name, scenario_config = _weighted_item(
            document_config["scenarios"],
            random_source,
        )
        format_name, _ = _weighted_item(
            document_config["formats"],
            random_source,
        )
        match_profile, match_config = _weighted_item(
            document_config["match_distribution"],
            random_source,
        )
        size_profile, size_config = _weighted_item(
            document_config["size_distribution"],
            random_source,
        )

        expected_match_count = random_source.randint(
            int(match_config["matches_per_document"]["minimum"]),
            int(match_config["matches_per_document"]["maximum"]),
        )

        record, expected_values = _build_record(
            document_id=document_id,
            scenario_name=scenario_name,
            fields=scenario_config["fields"],
            expected_match_count=expected_match_count,
            random_source=random_source,
        )

        serialized = _serialize_record(
            record=record,
            format_name=format_name,
            scenario_name=scenario_name,
        )

        target_size = random_source.randint(
            int(size_config["minimum_bytes"]),
            int(size_config["maximum_bytes"]),
        )

        serialized = _pad_document(
            content=serialized,
            target_size=target_size,
            format_name=format_name,
            random_source=random_source,
        )

        extension = _extension_for_format(format_name)
        filename = f"{document_id}.{extension}"
        file_path = output_path / filename
        encoded = serialized.encode("utf-8")

        file_path.write_bytes(encoded)

        digest = hashlib.sha256(encoded).hexdigest()

        generated.append(
            GeneratedDocument(
                document_id=document_id,
                filename=filename,
                relative_path=filename,
                scenario=scenario_name,
                document_format=format_name,
                match_profile=match_profile,
                size_profile=size_profile,
                expected_matches=len(expected_values),
                size_bytes=len(encoded),
                sha256=digest,
            )
        )

    return generated


def generated_documents_as_dicts(
    documents: Sequence[GeneratedDocument],
) -> list[dict[str, Any]]:
    """Convert generated document metadata into JSON-serializable mappings."""

    return [asdict(document) for document in documents]


# Generated corpora must be reproducible from the seed alone, so timestamps use
# a fixed synthetic epoch rather than wall-clock time. The year is deliberately
# implausible so a synthetic record is never mistaken for a real one.
FALLBACK_TIMESTAMP = "2100-01-01T00:00:00+00:00"


def _deterministic_timestamp(random_source: random.Random) -> str:
    """A seed-derived timestamp. Varied across records, stable across runs."""
    return (
        f"2100-{1 + random_source.randrange(12):02d}"
        f"-{1 + random_source.randrange(28):02d}"
        f"T{random_source.randrange(24):02d}"
        f":{random_source.randrange(60):02d}:00+00:00"
    )


def _weighted_item(
    items: Mapping[str, Mapping[str, Any]],
    random_source: random.Random,
) -> tuple[str, Mapping[str, Any]]:
    # Sort the names into a canonical order before drawing (FW-7). random.choices
    # walks names in the order given, so a bare list(items.keys()) makes the
    # selection depend on YAML key order: two semantically identical configs
    # that differ only in key order, or one re-serialized with sorted keys,
    # would yield a different catalog for the same seed. Sorting makes the draw
    # depend on the seed and the map's contents alone.
    names = sorted(items.keys())
    weights = [int(items[name]["weight"]) for name in names]

    selected_name = random_source.choices(names, weights=weights, k=1)[0]
    return selected_name, items[selected_name]


def _build_record(
    *,
    document_id: str,
    scenario_name: str,
    fields: Sequence[str],
    expected_match_count: int,
    random_source: random.Random,
) -> tuple[dict[str, Any], list[str]]:
    record: dict[str, Any] = {
        "document_id": document_id,
        "scenario": scenario_name,
        "generated_at": _deterministic_timestamp(random_source),
    }

    for field_name in fields:
        record[field_name] = _generate_field_value(field_name, random_source)

    expected_values: list[str] = []

    for match_index in range(expected_match_count):
        field_name, value = _generate_sensitive_value(
            match_index=match_index,
            random_source=random_source,
        )
        expected_values.append(value)

        injection_field = _select_injection_field(record)
        existing_value = str(record.get(injection_field, ""))

        record[injection_field] = (
            f"{existing_value}\n"
            f"validation_marker_{match_index + 1}: "
            f"{field_name}={value}"
        ).strip()

    return record, expected_values


def _select_injection_field(record: Mapping[str, Any]) -> str:
    preferred_fields = (
        "internal_notes",
        "issue_description",
        "message_body",
        "message",
        "request_body",
        "response_body",
        "description",
        "retrieved_context",
        "tool_output",
        "model_response",
        "user_prompt",
    )

    for field_name in preferred_fields:
        if field_name in record:
            return field_name

    return "validation_content"


def _generate_sensitive_value(
    *,
    match_index: int,
    random_source: random.Random,
) -> tuple[str, str]:
    generators = (
        ("email_address", _email_address),
        ("phone_number", _phone_number),
        ("social_security_number", _social_security_number),
        ("credit_card_number", _credit_card_number),
        ("api_key", _api_key),
        ("ipv4_address", _ipv4_address),
        ("customer_id", _customer_id),
        ("employee_id", _employee_id),
        ("patient_id", _patient_id),
        ("bank_account_number", _bank_account_number),
    )

    field_name, generator = generators[match_index % len(generators)]
    return field_name, generator(random_source)


def _generate_field_value(
    field_name: str,
    random_source: random.Random,
) -> Any:
    generators = {
        "account_status": lambda rng: rng.choice(
            ["active", "pending", "suspended", "closed"]
        ),
        "amount": lambda rng: f"{rng.uniform(10.0, 25000.0):.2f}",
        "api_key": _api_key,
        "bank_account_number": _bank_account_number,
        "claim_number": lambda rng: f"CLM-{rng.randint(10000000, 99999999)}",
        "connection_string": lambda rng: (
            f"postgresql://service:{_token(rng, 16)}"
            f"@db.internal.example:5432/customer"
        ),
        "currency": lambda rng: rng.choice(["USD", "EUR", "GBP", "CAD"]),
        "customer_id": _customer_id,
        "date_of_birth": lambda rng: (
            f"{rng.randint(1945, 2004):04d}-"
            f"{rng.randint(1, 12):02d}-"
            f"{rng.randint(1, 28):02d}"
        ),
        "department": lambda rng: rng.choice(
            [
                "Engineering",
                "Finance",
                "Field Operations",
                "Human Resources",
                "Legal",
                "Support",
            ]
        ),
        "diagnosis_description": lambda rng: rng.choice(
            [
                "Routine outpatient evaluation",
                "Diagnostic imaging follow-up",
                "Physical therapy consultation",
                "Preventive care examination",
            ]
        ),
        "email_address": _email_address,
        "employee_id": _employee_id,
        "endpoint": lambda rng: rng.choice(
            [
                "/api/v1/customers",
                "/api/v1/claims",
                "/api/v1/payments",
                "/api/v1/sessions",
            ]
        ),
        "headers": lambda rng: {
            "authorization": f"Bearer {_token(rng, 32)}",
            "content-type": "application/json",
            "x-request-id": _request_id(rng),
        },
        "hostname": lambda rng: (
            f"app-{rng.randint(1, 99):02d}.internal.example"
        ),
        "internal_notes": lambda rng: rng.choice(
            [
                "Record reviewed by operations.",
                "Customer requested expedited follow-up.",
                "Internal review remains pending.",
                "No additional action is currently required.",
            ]
        ),
        "ipv4_address": _ipv4_address,
        "issue_description": lambda rng: (
            "The user reported intermittent access failures during a "
            "standard business workflow."
        ),
        "issue_summary": lambda rng: rng.choice(
            [
                "Authentication failure",
                "Unexpected response latency",
                "Incorrect account status",
                "Unable to retrieve requested record",
            ]
        ),
        "log_level": lambda rng: rng.choice(
            ["DEBUG", "INFO", "WARNING", "ERROR"]
        ),
        "manager": _person_name,
        "member_id": lambda rng: f"MEM-{rng.randint(1000000, 9999999)}",
        "message": lambda rng: (
            "Request completed with validation metadata attached."
        ),
        "message_body": lambda rng: (
            "Please review the attached account details and confirm the "
            "requested changes."
        ),
        "model_response": lambda rng: (
            "The requested information was processed using the supplied context."
        ),
        "patient_id": _patient_id,
        "person_name": _person_name,
        "phone_number": _phone_number,
        "provider": lambda rng: rng.choice(
            [
                "Pine Valley Medical Group",
                "Central Health Partners",
                "Lakeside Family Practice",
                "Metro Diagnostic Center",
            ]
        ),
        "quoted_thread": lambda rng: (
            "On the previous business day, the requester asked for an update."
        ),
        "recipients": lambda rng: [
            _email_address(rng),
            _email_address(rng),
        ],
        "request_body": lambda rng: {
            "operation": "lookup",
            "reference": _customer_id(rng),
        },
        "request_id": _request_id,
        "response_body": lambda rng: {
            "status": "accepted",
            "processed": True,
        },
        "response_status": lambda rng: rng.choice([200, 201, 400, 404, 500]),
        "retrieved_context": lambda rng: (
            "Internal account context retrieved for validation."
        ),
        "routing_number": lambda rng: f"{rng.randint(100000000, 999999999)}",
        "sender": _email_address,
        "session_id": lambda rng: f"session-{_token(rng, 20)}",
        "signature": lambda rng: f"Regards,\n{_person_name(rng)}",
        "stack_trace": lambda rng: (
            "ValidationError: generated synthetic exception\n"
            "  at workload.processor:42"
        ),
        "street_address": lambda rng: (
            f"{rng.randint(100, 9999)} "
            f"{rng.choice(['Oak', 'Maple', 'Cedar', 'Lake', 'Hill'])} "
            f"{rng.choice(['Street', 'Road', 'Avenue', 'Drive'])}"
        ),
        "subject": lambda rng: rng.choice(
            [
                "Account review requested",
                "Support case update",
                "Transaction confirmation",
                "Internal validation notice",
            ]
        ),
        "support_case_id": lambda rng: (
            f"CASE-{rng.randint(100000, 999999)}"
        ),
        "system_prompt": lambda rng: (
            "Process the supplied enterprise record according to policy."
        ),
        "timestamp": lambda rng: _deterministic_timestamp(rng),
        "tool_output": lambda rng: (
            '{"status":"success","source":"synthetic-enterprise-system"}'
        ),
        "transaction_id": lambda rng: (
            f"TXN-{rng.randint(100000000, 999999999)}"
        ),
        "user_prompt": lambda rng: (
            "Summarize the retrieved customer information."
        ),
    }

    generator = generators.get(field_name)

    if generator is not None:
        return generator(random_source)

    return f"synthetic_{field_name}_{_token(random_source, 12)}"


def _serialize_record(
    *,
    record: Mapping[str, Any],
    format_name: str,
    scenario_name: str,
) -> str:
    serializers = {
        "json": _serialize_json,
        "xml": _serialize_xml,
        "html": _serialize_html,
        "text": _serialize_text,
        "email": _serialize_email,
        "log": _serialize_log,
        "csv": _serialize_csv,
    }

    try:
        serializer = serializers[format_name]
    except KeyError as error:
        raise ValueError(
            f"Unsupported document format: {format_name}"
        ) from error

    return serializer(record, scenario_name)


def _serialize_json(
    record: Mapping[str, Any],
    _: str,
) -> str:
    return json.dumps(record, indent=2, sort_keys=True, default=str) + "\n"


def _serialize_xml(
    record: Mapping[str, Any],
    scenario_name: str,
) -> str:
    root = Element("enterprise_record")
    root.set("scenario", scenario_name)

    for key, value in record.items():
        child = SubElement(root, _xml_tag(key))
        child.text = (
            json.dumps(value, sort_keys=True)
            if isinstance(value, (dict, list))
            else str(value)
        )

    return tostring(root, encoding="unicode") + "\n"


def _serialize_html(
    record: Mapping[str, Any],
    scenario_name: str,
) -> str:
    rows = []

    for key, value in record.items():
        formatted = (
            json.dumps(value, sort_keys=True)
            if isinstance(value, (dict, list))
            else str(value)
        )
        rows.append(
            "<tr>"
            f"<th>{escape(key)}</th>"
            f"<td>{escape(formatted)}</td>"
            "</tr>"
        )

    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        f"  <title>{escape(scenario_name)}</title>\n"
        "</head>\n"
        "<body>\n"
        f"  <h1>{escape(scenario_name)}</h1>\n"
        "  <table>\n"
        f"    {''.join(rows)}\n"
        "  </table>\n"
        "</body>\n"
        "</html>\n"
    )


def _serialize_text(
    record: Mapping[str, Any],
    scenario_name: str,
) -> str:
    lines = [f"scenario: {scenario_name}"]

    for key, value in record.items():
        formatted = (
            json.dumps(value, sort_keys=True)
            if isinstance(value, (dict, list))
            else str(value)
        )
        lines.append(f"{key}: {formatted}")

    return "\n".join(lines) + "\n"


def _serialize_email(
    record: Mapping[str, Any],
    scenario_name: str,
) -> str:
    message = EmailMessage()
    message["From"] = str(record.get("sender", "sender@example.test"))

    recipients = record.get("recipients", ["recipient@example.test"])
    if isinstance(recipients, list):
        message["To"] = ", ".join(str(value) for value in recipients)
    else:
        message["To"] = str(recipients)

    message["Subject"] = str(
        record.get("subject", f"Synthetic {scenario_name} record")
    )
    message["X-Document-ID"] = str(record.get("document_id", "unknown"))

    body_parts = []

    for key, value in record.items():
        if key not in {"sender", "recipients", "subject"}:
            body_parts.append(f"{key}: {value}")

    message.set_content("\n".join(body_parts))
    return message.as_string() + "\n"


def _serialize_log(
    record: Mapping[str, Any],
    _: str,
) -> str:
    # No seeded source is available here, so fall back to the fixed synthetic
    # epoch rather than wall-clock time. Wall-clock made roughly 9% of
    # enterprise-dlp documents differ between runs of the same seed, breaking
    # the reproducibility guarantee the manifest implies.
    timestamp = record.get("timestamp", FALLBACK_TIMESTAMP)
    level = record.get("log_level", "INFO")
    hostname = record.get("hostname", "unknown-host")
    request_id = record.get("request_id", "unknown-request")

    details = json.dumps(record, sort_keys=True, default=str)

    return (
        f"{timestamp} level={level} host={hostname} "
        f"request_id={request_id} record={details}\n"
    )


def _serialize_csv(
    record: Mapping[str, Any],
    _: str,
) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(record.keys()))
    writer.writeheader()

    normalized = {
        key: (
            json.dumps(value, sort_keys=True)
            if isinstance(value, (dict, list))
            else value
        )
        for key, value in record.items()
    }

    writer.writerow(normalized)
    return output.getvalue()


def _pad_document(
    *,
    content: str,
    target_size: int,
    format_name: str,
    random_source: random.Random,
) -> str:
    if target_size < 0:
        raise ValueError("Document target size cannot be negative.")

    encoded_size = len(content.encode("utf-8"))

    if encoded_size >= target_size:
        return content

    remaining = target_size - encoded_size

    # Composed per document rather than repeated from a constant: a long record
    # is long because many separate things were written into it over time. See
    # framework/workload/prose.py.
    chunks: list[str] = []
    filler_size = 0
    sequence = 1

    while filler_size < remaining:
        chunk = (
            f"{prose.paragraph(random_source, sentences=2)} "
            f"sequence={sequence} "
            f"token={_token(random_source, 16)}\n"
        )
        chunks.append(chunk)
        filler_size += len(chunk.encode("utf-8"))
        sequence += 1

    filler = "".join(chunks)

    if format_name == "json":
        return _append_json_filler(content, filler, target_size)

    if format_name == "xml":
        return _append_xml_filler(content, filler, target_size)

    if format_name == "html":
        return _append_html_filler(content, filler, target_size)

    return content + _truncate_utf8(filler, remaining)


def _append_json_filler(
    content: str,
    filler: str,
    target_size: int,
) -> str:
    data = json.loads(content)
    data["_synthetic_padding"] = ""
    empty = json.dumps(data, indent=2, sort_keys=True) + "\n"
    available = target_size - len(empty.encode("utf-8"))
    if available < 0:
        return content

    data["_synthetic_padding"] = _prefix_for_encoded_budget(
        filler,
        available,
        _json_character_size,
    )
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _append_xml_filler(
    content: str,
    filler: str,
    target_size: int,
) -> str:
    closing_tag = "</enterprise_record>\n"
    if not content.endswith(closing_tag):
        return content

    prefix = content[: -len(closing_tag)]
    empty = prefix + "<synthetic_padding></synthetic_padding>" + closing_tag
    available = target_size - len(empty.encode("utf-8"))
    if available < 0:
        return content

    fitted = _prefix_for_encoded_budget(filler, available, _xml_character_size)
    return (
        prefix
        + f"<synthetic_padding>{escape(fitted)}</synthetic_padding>"
        + closing_tag
    )


def _append_html_filler(
    content: str,
    filler: str,
    target_size: int,
) -> str:
    if "</body>" not in content:
        return content

    empty = content.replace("</body>", "<pre></pre>\n</body>", 1)
    available = target_size - len(empty.encode("utf-8"))
    if available < 0:
        return content

    fitted = _prefix_for_encoded_budget(filler, available, _xml_character_size)
    insertion = f"<pre>{escape(fitted)}</pre>\n"
    return content.replace("</body>", insertion + "</body>", 1)


def _prefix_for_encoded_budget(
    value: str,
    byte_budget: int,
    character_size: Callable[[str], int],
) -> str:
    used = 0
    end = 0
    for end, character in enumerate(value, start=1):
        encoded_size = character_size(character)
        if used + encoded_size > byte_budget:
            return value[: end - 1]
        used += encoded_size
    return value[:end]


def _json_character_size(character: str) -> int:
    if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
        return 2
    if ord(character) < 0x20:
        return 6
    if ord(character) > 0x7F:
        return len(json.dumps(character).encode("utf-8")) - 2
    return 1


def _xml_character_size(character: str) -> int:
    return len(escape(character).encode("utf-8"))


def _truncate_utf8(content: str, target_size: int) -> str:
    encoded = content.encode("utf-8")

    if len(encoded) <= target_size:
        return content

    return encoded[:target_size].decode("utf-8", errors="ignore")


def _extension_for_format(format_name: str) -> str:
    extensions = {
        "json": "json",
        "xml": "xml",
        "html": "html",
        "text": "txt",
        "email": "eml",
        "log": "log",
        "csv": "csv",
    }

    try:
        return extensions[format_name]
    except KeyError as error:
        raise ValueError(
            f"Unsupported document format: {format_name}"
        ) from error


def _xml_tag(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", value)

    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"field_{cleaned}"

    return cleaned


def _token(random_source: random.Random, length: int) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(random_source.choice(alphabet) for _ in range(length))


def _person_name(random_source: random.Random) -> str:
    first_names = (
        "Alex",
        "Cameron",
        "Jordan",
        "Morgan",
        "Riley",
        "Taylor",
    )
    last_names = (
        "Bennett",
        "Carter",
        "Hayes",
        "Morgan",
        "Parker",
        "Reed",
    )

    return (
        f"{random_source.choice(first_names)} "
        f"{random_source.choice(last_names)}"
    )


def _email_address(random_source: random.Random) -> str:
    name = _person_name(random_source).lower().replace(" ", ".")
    return f"{name}{random_source.randint(10, 999)}@example.test"


def _phone_number(random_source: random.Random) -> str:
    return (
        f"+1-704-{random_source.randint(200, 999):03d}-"
        f"{random_source.randint(1000, 9999):04d}"
    )


def _social_security_number(random_source: random.Random) -> str:
    return (
        f"{random_source.randint(100, 899):03d}-"
        f"{random_source.randint(10, 99):02d}-"
        f"{random_source.randint(1000, 9999):04d}"
    )


def _credit_card_number(random_source: random.Random) -> str:
    return "4111-" + "-".join(
        f"{random_source.randint(0, 9999):04d}" for _ in range(3)
    )


def _api_key(random_source: random.Random) -> str:
    return f"sk_test_{_token(random_source, 32)}"


def _ipv4_address(random_source: random.Random) -> str:
    return (
        f"10.{random_source.randint(0, 255)}."
        f"{random_source.randint(0, 255)}."
        f"{random_source.randint(1, 254)}"
    )


def _customer_id(random_source: random.Random) -> str:
    return f"CUST-{random_source.randint(100000, 999999)}"


def _employee_id(random_source: random.Random) -> str:
    return f"EMP-{random_source.randint(100000, 999999)}"


def _patient_id(random_source: random.Random) -> str:
    return f"PAT-{random_source.randint(100000, 999999)}"


def _bank_account_number(random_source: random.Random) -> str:
    return f"{random_source.randint(1000000000, 999999999999)}"


def _request_id(random_source: random.Random) -> str:
    return f"req-{_token(random_source, 24)}"
