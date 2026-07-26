# ISSUE-005 token truncation — which engine, at what length (2026-07-26)

Controlled reproduction to settle the attribution ISSUE-005 asserts. Companion raw
data: `issue-005-truncation-20260726.json`. Repro script:
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

## Conclusion

- **The truncating engine is Aergia (the RE2 comparison baseline), not Themis.**
  ISSUE-005 states "Component: Themis runtime" — that attribution is **wrong**. Its own
  reproduction never pinned the port (`https://<tenant-host>/v1/process`), so the
  Themis label was an assumption; this controlled run contradicts it.
- Each engine has exactly one defect in this pair: **Themis corrupts overlapping
  matches (ISSUE-004); Aergia truncates long tokens (ISSUE-005).** They do not share
  either.
- Implication for our own framework: we have been budgeting replacement tokens to 15
  characters (`_token_for` in the BYO POC and console; the qualification generator's
  abbreviations) to accommodate a limit that belongs to the comparison baseline, not to
  Themis. That constraint should be re-examined — see the blast-radius list in the
  review status.

**Not yet actioned:** ISSUE-005 is not rewritten pending a decision on re-attribution
and the blast radius. This file is the evidence that decision rests on.
