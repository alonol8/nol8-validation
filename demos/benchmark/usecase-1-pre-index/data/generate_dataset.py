import argparse
import json
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REFERENCE_LIST_DIR = ROOT / "reference_lists"


def load_list(name: str) -> list[str]:
    path = REFERENCE_LIST_DIR / name
    with path.open() as handle:
        return [line.strip() for line in handle if line.strip() and not line.startswith("#")]


CUSTOMERS = load_list("customers.txt")
BAD_IPS = load_list("bad_ips.txt")
DENIED_ENTITIES = load_list("denied_entities.txt")
COMPROMISED_ACCOUNTS = load_list("compromised_accounts.txt")
PAYMENT_CARDS = load_list("payment_cards.txt")
INTERNAL_PROJECTS = load_list("internal_projects.txt")
REGULATED_DATASETS = load_list("regulated_datasets.txt")

TECHNICAL_LINES = [
    "The analyst assistant should prioritize incident timelines, account context, and remediation notes over boilerplate.",
    "Retrieval quality improves when onboarding summaries and fraud-review notes are normalized before indexing.",
    "Security operations wants embedding spend focused on high-value investigative content rather than repetitive status traffic.",
    "The AI search workflow is only useful if customer-risk context is preserved while low-value noise is suppressed early.",
    "Governance teams want deterministic pre-index controls so sensitive text does not land in embeddings by default.",
]

SUPPORT_LINES = [
    "Tier-2 support escalated the case after the customer reported repeated sign-in failures from a new device profile.",
    "The payments team attached an investigation summary covering disputed transactions, refund notes, and fraud indicators.",
    "A compliance analyst documented the onboarding review and recommended manual verification before account activation.",
    "Customer operations added a short note explaining that the account requires special handling during after-hours support.",
    "The fraud queue contains a mix of confirmed abuse, false positives, and cases awaiting additional context.",
]

BOILERPLATE_LINES = [
    "Welcome to Acme Corp Internal Portal",
    "Navigation: Home | Products | Support | About | Contact",
    "Footer: Example Incorporated. All rights reserved.",
    "Legal Disclaimer: This document is confidential and intended only for internal use.",
    "Cookie Notice: By continuing to use this site you agree to our use of cookies.",
]

SENSITIVE_PATTERNS = [
    "Contact: john.doe@acme.com",
    "Backup Contact: jane.smith@partner.example",
    "SSN: 123-45-6789",
    "Phone: 704-555-0199",
    "Account ID: ACC-4582-9917",
]

TAGGING_LINES = [
    "Classification: internal_only",
    "Classification: regulated_data",
    "Classification: high_priority_review",
]


def build_keep(i: int) -> dict:
    parts = random.sample(TECHNICAL_LINES, k=2) + random.sample(SUPPORT_LINES, k=1)
    return {"id": f"chunk-{i+1:07d}", "category": "keep", "text": "\n".join(parts)}


def build_regex_sensitive(i: int) -> dict:
    parts = random.sample(SENSITIVE_PATTERNS, k=random.randint(1, 2))
    parts += random.sample(TECHNICAL_LINES, k=1)
    if random.random() < 0.7:
        parts.insert(0, random.choice(BOILERPLATE_LINES))
    if random.random() < 0.4:
        parts.append(random.choice(SUPPORT_LINES))
    return {"id": f"chunk-{i+1:07d}", "category": "regex_sensitive", "text": "\n".join(parts)}


def build_customer_watchlist(i: int) -> dict:
    customer = random.choice(CUSTOMERS)
    project = random.choice(INTERNAL_PROJECTS)
    parts = [
        f"Customer review: {customer} requested accelerated enablement for the {project} workflow.",
        random.choice(SUPPORT_LINES),
        random.choice(TECHNICAL_LINES),
    ]
    return {"id": f"chunk-{i+1:07d}", "category": "customer_watchlist", "text": "\n".join(parts)}


def build_bad_ip(i: int) -> dict:
    ip = random.choice(BAD_IPS)
    parts = [
        f"SOC alert: repeated failed sign-ins from {ip} hit the customer support portal during the same 20-minute window.",
        "The fraud analyst linked the traffic to password-spray behavior and recommended immediate suppression from downstream AI search.",
        random.choice(TECHNICAL_LINES),
    ]
    return {"id": f"chunk-{i+1:07d}", "category": "bad_ip", "text": "\n".join(parts)}


def build_denied_entity(i: int) -> dict:
    entity = random.choice(DENIED_ENTITIES)
    dataset = random.choice(REGULATED_DATASETS)
    parts = [
        f"Compliance screening note: {entity} appeared in a manual sanctions review tied to the {dataset} data feed.",
        "The case should be routed for approval rather than embedded into the general analyst index.",
        random.choice(SUPPORT_LINES),
    ]
    return {"id": f"chunk-{i+1:07d}", "category": "denied_entity", "text": "\n".join(parts)}


def build_compromised_account(i: int) -> dict:
    account = random.choice(COMPROMISED_ACCOUNTS)
    parts = [
        f"Fraud operations escalated account {account} after device telemetry and impossible-travel signals suggested compromise.",
        "The case record should be dropped from general-purpose embedding until the investigation is complete.",
        random.choice(SUPPORT_LINES),
    ]
    return {"id": f"chunk-{i+1:07d}", "category": "compromised_account", "text": "\n".join(parts)}


def build_payment_card(i: int) -> dict:
    card = random.choice(PAYMENT_CARDS)
    parts = [
        f"Chargeback investigation note: the caller provided test card {card} during payment validation.",
        random.choice(SUPPORT_LINES),
        random.choice(TECHNICAL_LINES),
    ]
    return {"id": f"chunk-{i+1:07d}", "category": "payment_card", "text": "\n".join(parts)}


def build_mixed(i: int) -> dict:
    customer = random.choice(CUSTOMERS)
    ip = random.choice(BAD_IPS)
    parts = [
        random.choice(BOILERPLATE_LINES),
        f"{customer} opened a support case after suspicious access from {ip} triggered a fraud review.",
        random.choice(SENSITIVE_PATTERNS),
        random.choice(TAGGING_LINES),
        random.choice(TECHNICAL_LINES),
    ]
    if random.random() < 0.5:
        parts.append(random.choice(BOILERPLATE_LINES))
    return {"id": f"chunk-{i+1:07d}", "category": "mixed", "text": "\n".join(parts)}


def build_near_miss(i: int) -> dict:
    customer = random.choice(CUSTOMERS) + " Advisory"
    account = "ACC-1000-2000"
    parts = [
        f"Partner outreach note: {customer} requested pricing guidance for a future pilot.",
        f"Temporary review account {account} was created for a demo environment and cleared during QA.",
        random.choice(TECHNICAL_LINES),
    ]
    return {"id": f"chunk-{i+1:07d}", "category": "near_miss", "text": "\n".join(parts)}


def build_boilerplate(i: int) -> dict:
    parts = random.sample(BOILERPLATE_LINES, k=random.randint(2, 3))
    if random.random() < 0.4:
        parts.append(random.choice(TECHNICAL_LINES))
    return {"id": f"chunk-{i+1:07d}", "category": "boilerplate", "text": "\n".join(parts)}


BUILDERS = [
    (build_keep, 24),
    (build_regex_sensitive, 16),
    (build_customer_watchlist, 15),
    (build_bad_ip, 10),
    (build_denied_entity, 8),
    (build_compromised_account, 8),
    (build_payment_card, 6),
    (build_mixed, 7),
    (build_boilerplate, 4),
    (build_near_miss, 2),
]


def choose_builder():
    funcs = [entry[0] for entry in BUILDERS]
    weights = [entry[1] for entry in BUILDERS]
    return random.choices(funcs, weights=weights, k=1)[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    random.seed(args.seed)
    output_path = Path(args.output)
    with output_path.open("w") as handle:
        for i in range(args.count):
            builder = choose_builder()
            handle.write(json.dumps(builder(i)) + "\n")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
