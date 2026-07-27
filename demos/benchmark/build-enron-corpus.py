#!/usr/bin/env python3
"""Build a load corpus from the Enron email corpus - real business writing.

The demo corpora in this repository are synthetic. `sample_chunks.jsonl` is
templated filler with a generated vocabulary - 1,287 occurrences of "the" and
zero of "with", "as" or "it" - which no real text resembles, and a policy of
English words scores zero matches against it.

Enron is the standard public corpus of genuine business email: half a million
real messages written by people doing their jobs. That matters for two separate
things this framework measures.

* **Token reduction.** Natural function-word density, natural sentence
  structure, and natural near misses - a policy holding " the " is entered and
  abandoned by every "there", "their" and "them" in the text. None of that has
  to be manufactured.
* **Detection.** Real names, addresses, phone numbers and account references
  appear in it as they appear in production traffic: unannounced, in context,
  and mixed in with text that merely resembles them.

It also carries a claim the synthetic corpora cannot: results were measured on
the corpus the industry already uses, not on data we generated for ourselves.

    curl -O https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz
    tar xzf enron_mail_20150507.tar.gz          # -> maildir/
    python demos/benchmark/build-enron-corpus.py --maildir maildir \\
        --docs 20000 --out demos/benchmark/datapoint4/results/enron.jsonl

Headers are stripped and the body kept. Quoted reply chains are kept - they are
part of what a real message contains, and they are where a lot of the repeated
text in business email lives.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from email import policy
from email.parser import BytesParser
from pathlib import Path

# Lines that are routing furniture rather than anything a person wrote. Dropping
# them keeps the corpus text rather than metadata; the quoted chain stays.
_NOISE_LINE = re.compile(
    r"^\s*(-{3,}\s*Forwarded by|-{5,}\s*Original Message|"
    r"(To|From|Cc|Bcc|Sent|Subject|Date):\s|"
    r"\*{5,}|={5,})",
    re.IGNORECASE,
)


def message_body(path: Path) -> str:
    """The human-written part of one message, or "" if there isn't one."""

    try:
        with path.open("rb") as handle:
            message = BytesParser(policy=policy.default).parse(handle)
    except Exception:
        return ""
    try:
        body = message.get_body(preferencelist=("plain",))
        text = body.get_content() if body is not None else ""
    except Exception:
        return ""

    kept = [line.rstrip() for line in text.splitlines() if not _NOISE_LINE.match(line)]
    # Collapse the runs of blank lines that stripping leaves behind.
    out: list[str] = []
    for line in kept:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def iter_messages(maildir: Path, seed: int):
    """Message paths in a deterministic shuffled order.

    Shuffled because the maildir is grouped by employee and then by folder: read
    in order, the first thousand documents would all be one person's sent mail,
    which is a much narrower sample of language than the corpus contains.
    """
    paths = sorted(p for p in maildir.rglob("*") if p.is_file())
    random.Random(seed).shuffle(paths)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--maildir", type=Path, required=True,
                        help="the extracted maildir/ directory")
    parser.add_argument("--docs", type=int, default=20000)
    parser.add_argument("--min-bytes", type=int, default=600,
                        help="skip messages shorter than this; one-line replies "
                             "are real but carry almost no text to process")
    parser.add_argument("--max-bytes", type=int, default=4000,
                        help="truncate longer messages at a line boundary, so "
                             "documents stay inside the driver's small band")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if not args.maildir.is_dir():
        raise SystemExit(f"not a directory: {args.maildir}")

    written = 0
    scanned = 0
    total_bytes = 0
    args.out.parent.mkdir(parents=True, exist_ok=True)

    with args.out.open("w", encoding="utf-8") as handle:
        for path in iter_messages(args.maildir, args.seed):
            if written >= args.docs:
                break
            scanned += 1
            text = message_body(path)
            if len(text.encode("utf-8")) < args.min_bytes:
                continue
            if len(text.encode("utf-8")) > args.max_bytes:
                text = _truncate_at_line(text, args.max_bytes)
            handle.write(json.dumps(
                {"record_id": f"enron-{written:06d}", "kind": "dirty", "message": text},
                ensure_ascii=False,
            ) + "\n")
            written += 1
            total_bytes += len(text.encode("utf-8"))
            if written % 2000 == 0:
                print(f"\r  {written} documents from {scanned} messages",
                      end="", flush=True)

    if not written:
        raise SystemExit("no messages passed the size filter; check --maildir")

    print()
    print(f"wrote {args.out}: {written} documents from {scanned} messages scanned, "
          f"{total_bytes/1e6:.1f} MB, avg {total_bytes//written} bytes")
    return 0


def _truncate_at_line(text: str, limit: int) -> str:
    out: list[str] = []
    size = 0
    for line in text.splitlines():
        encoded = len(line.encode("utf-8")) + 1
        if size + encoded > limit:
            break
        out.append(line)
        size += encoded
    return "\n".join(out) if out else text[:limit]


if __name__ == "__main__":
    raise SystemExit(main())
