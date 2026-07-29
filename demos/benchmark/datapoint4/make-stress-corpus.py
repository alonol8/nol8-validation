#!/usr/bin/env python3
"""Generate a policy and corpus with the properties that cost a matcher most.

The workload generators in this repository produce data shaped like production:
sequential identifiers, prose or table rows, no overlapping literals. That is the
right default and it is why the density sweep is credible. It also happens to be
gentle on a software matcher in four specific ways, and this tool inverts all
four so the cost of each can be measured rather than assumed.

  1. HIGH-ENTROPY LITERALS. Sequential values (CUST-000001, CUST-000002, ...)
     share long prefixes and collapse into one trie branch. Random values - a
     UUID, a hex MAC, a random digit run - share almost nothing, so N literals
     become close to N distinct branches. Automaton size, not rule count, is what
     a software matcher pays for.

  2. VARIABLE AND SHORT LENGTHS. A 6-character code raises the achievable match
     density: density is capped at roughly 1024/literal-length per KB, so 20-byte
     identifiers cannot exceed ~50/KB however hard you try, and 6-byte ones can
     reach 170.

  3. FRAGMENTS. Text that matches a literal most of the way and then fails. The
     matcher walks in to full depth and discards the work. A corpus where every
     identifier-shaped string either matches immediately or looks nothing like a
     literal never exercises that path.

  4. ADJACENCY AND NESTING. Literals that abut, share bytes, or contain one
     another, so several candidates are live at once.

Every one of these occurs in real data - random tokens, short codes, truncated
log fields, and value lists that contain both "Acme Corp" and "Acme
Corporation". What is artificial here is the *concentration*: all four at once,
at maximum. Treat a result from this as a characterised worst case, labelled as
such, not as a workload anybody's traffic resembles. It answers "how bad can it
get and why", which is a different and legitimate question from "what will we
see in production".

    python demos/benchmark/datapoint4/make-stress-corpus.py \\
        --rules 8000 --docs 20000 --doc-bytes 4000

Writes a run directory the existing tooling accepts, so:

    bash demos/benchmark/datapoint4/verified-run.sh --run <printed id>

NOTE ON OVERLAPS. With --overlap-share above zero the corpus contains
overlapping matches, and the two engines implement different contracts for those
(ENGINE-SEMANTICS.md, ES-1) - so they will legitimately return different bytes.
expected-digests.py emits a digest per contract and the driver accepts either, so
verification still works; a parity claim does not. Use --overlap-share 0 if you
want the engines to be directly comparable byte for byte.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import string
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from framework.policy.matching import LiteralMatcher  # noqa: E402

# The alphabet noise is drawn from. Deliberately includes every punctuation
# character the literals below use: with a narrow alphabet the matcher can skip
# most bytes without entering its automaton at all, which is most of why prose is
# cheap to scan.
NOISE_ALPHABET = (
    string.ascii_letters + string.digits + " -_{}\\/\"'!@#$%^&*()+=`~|?<>,.;[]"
)

_FIRST = ("james", "mary", "john", "patricia", "robert", "jennifer", "michael",
          "linda", "william", "barbara", "alice", "bob", "charlie", "diana")
_LAST = ("wilson", "johnson", "smith", "brown", "jones", "garcia", "miller",
         "davis", "martinez", "hernandez", "taylor", "anderson", "thomas")
_DOMAINS = ("gmail.com", "yahoo.com", "outlook.com", "example.com",
            "company.org", "corp.net", "mail.io", "protonmail.com")
_HOSTWORDS = ("prod", "dev", "staging", "api", "web", "db", "cache", "auth",
              "proxy", "gateway", "worker", "monitor", "queue", "vault")
_ZONES = ("internal", "local", "corp", "example.com", "company.org", "infra.net")
_REGIONS = ("us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1")
_BANKS = ("DEUT", "COBA", "BARC", "HSBC", "BNPA", "UBSW", "CITI", "JPMO")
_COUNTRIES = ("DE", "GB", "FR", "US", "NL", "CH", "JP", "SG")
_DRUGS = ("Amoxicillin", "Ibuprofen", "Metformin", "Lisinopril", "Atorvastatin",
          "Omeprazole", "Amlodipine", "Metoprolol", "Albuterol", "Losartan")
_VERBS = ("get", "set", "fetch", "update", "delete", "create", "process",
          "handle", "compute", "validate", "parse", "encode", "build", "render")
_NOUNS = ("User", "Order", "Payment", "Token", "Session", "Config", "Record",
          "Report", "Message", "Event", "Request", "Response", "Context")
_IBAN_LENGTHS = {"DE": 22, "GB": 22, "FR": 27, "NL": 18, "ES": 24, "IT": 27}


def _digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


# Each returns (value, token). Lengths span 6 to 40 bytes and almost every value
# is random rather than sequential, which is the point of the exercise.
def _email(rng):
    f, l, d = rng.choice(_FIRST), rng.choice(_LAST), rng.choice(_DOMAINS)
    return rng.choice([
        f"{f}.{l}@{d}", f"{f}_{l}@{d}", f"{f}.{l}{rng.randint(1,9999)}@{d}",
        f"{f[0]}.{l}@{d}", f"{f}+{l}@{d}", f"{f}{rng.randint(1,9999)}@{d}",
    ]), "EMAIL"


def _card(rng):
    prefix = rng.choice(["4", "51", "52", "53", "54", "55", "34", "37", "6011"])
    amex = prefix in ("34", "37")
    number = prefix + _digits(rng, (15 if amex else 16) - len(prefix))
    if amex:
        return f"{number[:4]}-{number[4:10]}-{number[10:]}", "CC"
    return f"{number[:4]}-{number[4:8]}-{number[8:12]}-{number[12:]}", "CC"


def _ssn(rng):
    area = rng.randint(1, 899)
    return f"{667 if area == 666 else area:03d}-{rng.randint(1,99):02d}-{rng.randint(1,9999):04d}", "SSN"


def _phone(rng):
    d3 = lambda: f"{rng.randint(2,9)}{rng.randint(0,9)}{rng.randint(0,9)}"
    a, b, c = d3(), d3(), f"{rng.randint(0,9999):04d}"
    return rng.choice([
        f"({a}) {b}-{c}", f"{a}-{b}-{c}", f"{a}.{b}.{c}",
        f"+1{a}{b}{c}", f"+1 {a} {b} {c}",
    ]), "PHONE"


def _name(rng):
    f, l = rng.choice(_FIRST).capitalize(), rng.choice(_LAST).capitalize()
    return rng.choice([
        f"{f} {l}", f"{f} {rng.choice('ABCDEJKLMRST')}. {l}",
        f"{f} {l} {rng.choice(('Jr.', 'Sr.', 'III', 'IV'))}",
        f"{l}, {f}", f"{f[0]}. {l}",
    ]), "NAME"


def _ipv4(rng):
    ip = f"{rng.randint(1,254)}.{rng.randint(0,255)}.{rng.randint(0,255)}.{rng.randint(0,255)}"
    return rng.choice([ip, f"{ip}:443", f"{ip}:8080"]), "IP"


def _mac(rng):
    return ":".join(f"{rng.randint(0,255):02X}" for _ in range(6)), "MAC"


def _uuid(rng):
    h = lambda n: "".join(rng.choice("0123456789abcdef") for _ in range(n))
    return f"{h(8)}-{h(4)}-4{h(3)}-{rng.choice('89ab')}{h(3)}-{h(12)}", "UUID"


def _hostname(rng):
    w, n = rng.choice(_HOSTWORDS), rng.randint(1, 99)
    return rng.choice([
        f"{w}{n}.{rng.choice(_ZONES)}", f"{w}-{n}.{rng.choice(_ZONES)}",
        f"{w}.{rng.choice(_REGIONS)}.{rng.choice(_ZONES)}",
        f"{w}{n}.{rng.choice(_REGIONS)}.internal",
    ]), "HOST"


def _iban(rng):
    country = rng.choice(list(_IBAN_LENGTHS))
    return country + _digits(rng, _IBAN_LENGTHS[country] - 2), "IBAN"


def _swift(rng):
    a = string.ascii_uppercase
    return f"{rng.choice(_BANKS)}{rng.choice(_COUNTRIES)}{rng.choice(a)}{rng.choice(a)}XXX", "SWIFT"


def _icd(rng):
    # The short one. Six bytes, which is what lifts the density ceiling.
    return f"{rng.choice(string.ascii_uppercase)}{rng.randint(0,99):02d}.{rng.randint(0,9)}", "ICD"


def _drug(rng):
    return rng.choice(_DRUGS), "DRUG"


def _func(rng):
    return f"{rng.choice(_VERBS)}{rng.choice(_NOUNS)}{rng.randint(1,99)}", "FUNC"


GENERATORS = (_email, _card, _ssn, _phone, _name, _ipv4, _mac, _uuid,
              _hostname, _iban, _swift, _icd, _drug, _func)

# Low-entropy families, for isolating entropy from the other three properties.
# Fixed prefix, fixed width, sequential index - so thousands of literals collapse
# into a handful of trie branches, which is what the production-shaped generators
# produce and what makes them cheap to scan.
_SEQUENTIAL_FAMILIES = (
    ("CUST-", "CUST"), ("PAT-", "PATIENT"), ("EMP-", "EMP"), ("CASE-", "CASE"),
    ("INV-", "INVOICE"), ("MRN-", "MRN"), ("CTR-", "CONTRACT"), ("MEM-", "MEMBER"),
    ("CLM-", "CLAIM"), ("ACCT-", "ACCT"),
)


# How much of the noise alphabet the literals draw from. This is the share of
# noise bytes that can begin - or continue - a match attempt at all: with a
# narrow literal alphabet most of the stream is skipped without the matcher
# entering its automaton, and with a wide one almost every byte is a candidate.
LITERAL_ALPHABETS = {
    "narrow": string.ascii_lowercase + string.digits,          # 36 of 94
    "medium": string.ascii_letters + string.digits,            # 62 of 94
    "wide": NOISE_ALPHABET.replace(" ", ""),                   # ~93 of 94
}


def build_family_catalog(
    count: int, families: int, length: int, rng: random.Random,
    alphabet: str = "narrow",
) -> list[tuple[str, str]]:
    """Literals of one fixed length drawn from exactly `families` openings.

    The controlled experiment. The entropy and sequential modes differ in rule
    count, literal length and match density all at once, so a comparison between
    them cannot say which one the cost tracks. Here rule count, length and
    therefore density are all held constant and only the number of distinct
    openings varies - so a sweep over `families` isolates automaton width.

    A smooth curve means ordinary cache pressure. A knee means a budget being
    exhausted, which is a different and more interesting claim.
    """
    chars = LITERAL_ALPHABETS[alphabet]
    prefixes: list[str] = []
    seen_prefix: set[str] = set()
    while len(prefixes) < families:
        candidate = "".join(rng.choice(chars) for _ in range(4))
        if candidate not in seen_prefix:
            seen_prefix.add(candidate)
            prefixes.append(candidate)

    catalog: list[tuple[str, str]] = []
    seen: set[str] = set()
    attempts = 0
    while len(catalog) < count and attempts < count * 64:
        attempts += 1
        tail = "".join(rng.choice(chars) for _ in range(max(1, length - 4)))
        value = prefixes[len(catalog) % families] + tail
        if value in seen:
            continue
        seen.add(value)
        catalog.append((value, f"[F-{len(catalog)}]"[:15]))
    rng.shuffle(catalog)
    return catalog


def build_sequential_catalog(count: int) -> list[tuple[str, str]]:
    """Sequential fixed-width literals: the low-entropy control.

    Deliberately deterministic and unshuffled by value - the point is maximum
    prefix sharing, so every literal in a family differs only in its trailing
    digits.
    """
    catalog: list[tuple[str, str]] = []
    per_family = -(-count // len(_SEQUENTIAL_FAMILIES))
    for prefix, kind in _SEQUENTIAL_FAMILIES:
        for index in range(1, per_family + 1):
            if len(catalog) >= count:
                break
            token = f"[{kind}-{len(catalog)}]"
            catalog.append((f"{prefix}{index:06d}", token[:15]))
    return catalog


def build_catalog(count: int, rng: random.Random) -> list[tuple[str, str]]:
    """Literals and their replacement tokens.

    Nested and prefix-sharing literals are kept - only exact duplicates are
    rejected. A real value list contains both "Acme Corp" and "Acme
    Corporation", and refusing them is what makes the ordinary catalogs
    prefix-free and therefore cheap.

    Tokens stay inside 15 bytes so neither engine truncates them
    (ENGINE-SEMANTICS.md, ES-2) and one expectation serves both.
    """
    seen: set[str] = set()
    catalog: list[tuple[str, str]] = []
    attempts = 0
    while len(catalog) < count and attempts < count * 64:
        attempts += 1
        value, kind = rng.choice(GENERATORS)(rng)
        if value in seen or not value:
            continue
        seen.add(value)
        token = f"[{kind}-{len(catalog)}]"
        if len(token) > 15:
            token = f"[{kind[:4]}-{len(catalog)}]"[:15]
        catalog.append((value, token))
    rng.shuffle(catalog)
    return catalog


def _fragment(literal: str, rng: random.Random) -> str:
    """Part of a literal, so the matcher walks in and finds nothing."""

    if len(literal) < 3:
        return literal
    style = rng.randrange(3)
    if style == 0:                                  # prefix
        return literal[:rng.randint(1, len(literal) - 1)]
    if style == 1:                                  # suffix
        return literal[-rng.randint(1, len(literal) - 1):]
    length = rng.randint(1, len(literal) - 1)       # middle
    start = rng.randint(0, len(literal) - length)
    return literal[start:start + length]


def _overlap_pair(first: str, second: str, rng: random.Random) -> str:
    """Two literals sharing bytes, so both are candidates at once."""

    limit = min(len(first), len(second) - 1)
    if limit < 1:
        return first + second
    return first + second[rng.randint(1, limit):]


def build_document(
    literals: list[str],
    start: int,
    segments: int,
    doc_bytes: int,
    rng: random.Random,
    fragment_share: float,
    adjacency_share: float,
    overlap_share: float,
    noise_min: int,
    noise_max: int,
) -> tuple[str, int]:
    """One document, and how many whole literals it plants."""

    parts: list[str] = []
    planted = 0
    for offset in range(segments):
        literal = literals[(start + offset) % len(literals)]
        following = literals[(start + offset + 1) % len(literals)]
        draw = rng.random()
        if draw < fragment_share:
            parts.append(_fragment(literal, rng))
        elif draw < fragment_share + adjacency_share:
            parts.append(literal + following)
            planted += 2
        elif draw < fragment_share + adjacency_share + overlap_share:
            parts.append(_overlap_pair(literal, following, rng))
            planted += 1
        else:
            parts.append(literal)
            planted += 1
        parts.append("".join(
            rng.choice(NOISE_ALPHABET)
            for _ in range(rng.randint(noise_min, noise_max))
        ))
    text = "".join(parts)
    return text[:doc_bytes] if len(text) > doc_bytes else text, planted


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--rules", type=int, default=8000)
    parser.add_argument("--docs", type=int, default=20000)
    parser.add_argument("--doc-bytes", type=int, default=4000)
    parser.add_argument("--noise-min", type=int, default=4)
    parser.add_argument("--noise-max", type=int, default=32,
                        help="bytes of noise between segments; the smaller this "
                             "is the denser the corpus")
    parser.add_argument("--fragment-share", type=float, default=0.43,
                        help="share of segments that are partial literals - "
                             "matcher walks in, finds nothing")
    parser.add_argument("--adjacency-share", type=float, default=0.14,
                        help="share that are two literals abutting")
    parser.add_argument("--overlap-share", type=float, default=0.14,
                        help="share that are two literals sharing bytes. Above "
                             "zero the engines legitimately differ (ES-1)")
    parser.add_argument(
        "--literals", choices=("entropy", "sequential", "families"), default="entropy",
        help="entropy: random values sharing almost no prefix, so N literals "
             "become close to N trie branches. sequential: fixed-width values "
             "in a few families, collapsing into a handful of branches - the "
             "control for isolating entropy from fragments and overlap. "
             "families: fixed length drawn from exactly --prefix-families "
             "openings, holding rule count, length and therefore density "
             "constant so a sweep isolates automaton width",
    )
    parser.add_argument("--prefix-families", type=int, default=64,
                        help="distinct 4-byte openings, with --literals families")
    parser.add_argument("--literal-length", type=int, default=12,
                        help="literal length in bytes, with --literals families")
    parser.add_argument("--literal-alphabet", choices=tuple(LITERAL_ALPHABETS),
                        default="narrow",
                        help="how much of the noise alphabet the literals use, "
                             "with --literals families. This is the share of "
                             "noise bytes that can begin or continue a match "
                             "attempt: narrow 36/94, medium 62/94, wide 93/94")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--runs-dir", type=Path,
                        default=REPO_ROOT / "artifacts" / "runs")
    args = parser.parse_args()

    if args.fragment_share + args.adjacency_share + args.overlap_share > 1.0:
        raise SystemExit("the three shares must sum to at most 1.0")

    rng = random.Random(args.seed)
    print(f"building a {args.rules}-rule {args.literals} catalog")
    if args.literals == "sequential":
        catalog = build_sequential_catalog(args.rules)
    elif args.literals == "families":
        catalog = build_family_catalog(
            args.rules, args.prefix_families, args.literal_length, rng,
            args.literal_alphabet)
    else:
        catalog = build_catalog(args.rules, rng)
    literals = [value for value, _ in catalog]
    lengths = sorted(len(v) for v in literals)
    print(f"  {len(catalog)} literals, length {lengths[0]}-{lengths[-1]} "
          f"(median {lengths[len(lengths)//2]})")

    # A proxy for automaton width: how many distinct four-byte openings the
    # literals present. A matcher branches on those, so it is the difference
    # between one trie branch and thousands - and it is the number that separates
    # the two catalog modes.
    openings = len({value[:4] for value in literals})
    print(f"  {openings} distinct 4-byte openings "
          f"({100 * openings / max(1, len(literals)):.1f}% of literals)")

    # How much of the catalog contains another entry. The ordinary generators
    # refuse this; here it is expected, and worth reporting because it is what
    # makes several candidates live at once.
    matcher = LiteralMatcher(literals)
    nested = sum(
        1 for value in literals
        if any(m.literal != value for m in matcher.find_all(value))
    )
    print(f"  {nested} literals contain another entry "
          f"({100 * nested / max(1, len(literals)):.1f}%)")

    # Every parameter that affects the corpus goes into the id, via a digest of
    # all of them rather than a hand-written list. Two arms of an ablation must
    # never land in the same directory: the second overwrites the first, the
    # comparison still looks fine, and both numbers describe one corpus. That has
    # already cost two sweeps here - once on the literal mode, once on the shares
    # - and a hand-maintained list drifts the moment a flag is added, so the
    # digest covers whatever the parser holds.
    #
    # The readable part carries what a person needs to recognise an arm; the
    # digest guarantees separation. Because a digest alone is opaque, the full
    # parameter set is written beside the corpus so any run can be decoded and
    # reproduced.
    settings = {
        key: value for key, value in sorted(vars(args).items())
        if key != "runs_dir"        # where it is written does not change what it is
    }
    digest = hashlib.sha1(
        json.dumps(settings, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:8]
    readable = f"{args.literals}-{args.rules}r-{args.docs}d"
    if args.literals == "families":
        readable += (f"-p{args.prefix_families}-l{args.literal_length}"
                     f"-{args.literal_alphabet}")
    run_id = f"stress-{readable}-{digest}"

    generated = args.runs_dir / run_id / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    (args.runs_dir / run_id / "stress-params.json").write_text(
        json.dumps(settings, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )

    policy_path = generated / "scale-policy.nol"
    with policy_path.open("w", encoding="utf-8") as handle:
        handle.write(f"# High-entropy stress catalog. seed={args.seed}\n")
        handle.write("# Nested and prefix-sharing literals are deliberate.\n")
        for value, token in catalog:
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            handle.write(f'"{escaped}" -> "{token}";\n')

    segments = max(1, round(args.doc_bytes / (
        sum(lengths) / len(lengths) + (args.noise_min + args.noise_max) / 2)))
    print(f"writing {args.docs} documents of ~{args.doc_bytes} bytes "
          f"({segments} segments each)")

    corpus_path = generated / "input.jsonl"
    total_bytes = 0
    total_planted = 0
    cursor = 0
    with corpus_path.open("w", encoding="utf-8") as handle:
        for index in range(args.docs):
            text, planted = build_document(
                literals, cursor, segments, args.doc_bytes, rng,
                args.fragment_share, args.adjacency_share, args.overlap_share,
                args.noise_min, args.noise_max,
            )
            cursor += segments
            total_bytes += len(text.encode("utf-8"))
            total_planted += planted
            handle.write(json.dumps(
                {"record_id": f"stress-{index:06d}", "kind": "dirty",
                 "message": text},
                ensure_ascii=False,
            ) + "\n")

    # What the oracle actually finds, which is the number that matters - planted
    # counts are intent, and fragments plant nothing.
    kilobytes = total_bytes / 1024
    sample = [json.loads(line)["message"]
              for line in corpus_path.read_text(encoding="utf-8").splitlines()[:200]]
    sample_bytes = sum(len(t.encode("utf-8")) for t in sample) / 1024
    found = sum(len(matcher.find_all(text)) for text in sample)

    print()
    print(f"  {total_bytes / 1e6:.0f} MB, {kilobytes:.0f} KB total")
    print(f"  planted whole literals: {total_planted / kilobytes:.1f}/KB")
    print(f"  oracle candidate matches: {found / sample_bytes:.1f}/KB "
          f"(sampled over {len(sample)} documents)")
    print()
    print(f"run id: {run_id}")
    print("verify and measure with:")
    print(f"  bash demos/benchmark/datapoint4/verified-run.sh --run {run_id}")
    if args.overlap_share > 0:
        print()
        print("  overlap-share > 0, so the engines will legitimately return")
        print("  different bytes (ES-1). Digests carry both contracts; a parity")
        print("  claim does not hold. Use --overlap-share 0 for byte parity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
