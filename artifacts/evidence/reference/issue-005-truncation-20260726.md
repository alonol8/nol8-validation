# ISSUE-005 token truncation — which engine, at what length (2026-07-26)

Controlled reproduction of the truncation behaviour across token lengths, on both
engines, as a dated observation. It does NOT settle ISSUE-005's attribution — see the
Observation section below; that is a question for engineering. Companion raw data:
`issue-005-truncation-20260726.json`. Repro script:
`demos/benchmark/datapoint4/truncation_repro.py`.

## Method

One policy with four rules, each a distinct non-overlapping literal mapped to a token
of a controlled length (15, 16, 20, 29 chars). Deployed to both engines; a document
containing each literal sent to each engine; the emitted token and its length
recorded. Same policy, same input, both engines — only the engine differs.

## Result — token length sent → emitted

| token len sent | Themis (:443) | Aergia (:444) |
|---|---|---|
| 15 | 15 · full `[LEN15XXXXXXXX]` | 15 · full `[LEN15XXXXXXXX]` |
| 16 | **16 · full** `[LEN16XXXXXXXXX]` | **15 · trunc** `[LEN16XXXXXXXXX` |
| 20 | **20 · full** `[LEN20XXXXXXXXXXXXX]` | **15 · trunc** `[LEN20XXXXXXXXX` |
| 29 | **29 · full** `[LEN29XXXXXXXXXXXXXXXXXXXXXX]` | **15 · trunc** `[LEN29XXXXXXXXX` |

**Themis emits the full token at every length. Aergia truncates every token longer
than 15 characters to its first 15.** The limit is exactly 15, and it is
engine-specific.

## Engine identity — confirmed independently, not assumed

The result above depends on `config/demo.env` labelling :443 = Themis and :444 =
Aergia. Because it inverts a filed issue, identity was confirmed with a behaviour that
does not rely on that label: the ISSUE-004 overlap-corruption fingerprint. Policy
`"ABCD"→"[P]"`, `"DEFG"→"[Q]"`, input `x ABCDEFG y`:

- **:443 → `x [P][Q] y`** — both overlapping rules fire, destroying the `EFG`. This is
  the ISSUE-004 corruption; only Themis does this. → **:443 is Themis.**
- **:444 → `x [P]EFG y`** — correct leftmost-longest, no corruption. → **:444 is Aergia.**

(Correct output is `x [P]EFG y`. Themis's own report, ISSUE-004, shows the same
overlap-fires-both signature.)

## Observation (NOT a conclusion — a question for engineering)

In this single controlled run, on the current tenant, under the `config/demo.env`
port labelling confirmed via the ISSUE-004 fingerprint: the `:443` engine emitted
full tokens at every length and the `:444` engine truncated to 15.

**This is a dated observation, not a re-attribution.** It contradicts ISSUE-005's
"Component: Themis" attribution, and whether ISSUE-005 is wrong, stale, or measured
under different conditions cannot be settled from one experiment — that depends on
history the repo does not record (what was tested when ISSUE-005 was filed, and what
has changed on either path since). Per the review standard, a result that contradicts
a filed issue is raised with engineering, not concluded here.

Accordingly:

- **ISSUE-005 and THM-5 are NOT changed.** No re-attribution.
- The 15-character token budgeting in the framework (`_token_for`, generator
  abbreviations) is **left as-is** — do not loosen it on the strength of this run.
- The open questions go to engineering, appended to
  `docs/aergia-8k-collapse-question.md`: which component applies the limit, and whether
  anything changed on the FPGA path since ISSUE-005 was filed.

This file exists to preserve the observation, dated, so engineering's answer can be
checked against it. It is evidence, not a verdict.
