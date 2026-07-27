# Report Interpretation

## Purpose

This document explains how to interpret the benchmark report for Data Point 1.

It is especially important because the current report contains both:
- measured software baseline results
- simulated Nol8 behavior used only to represent control semantics

## Mode meanings

### `nofilter`

The do-nothing baseline.

Meaning:
- all chunks are forwarded
- no pre-index control is applied

### `re2`

Measured incumbent software baseline using Go `regexp` / RE2 syntax.

Meaning:
- real measured software filtering behavior
- valid for software-baseline performance discussion

### `listmatch`

Measured first-pass enterprise benchmark using known reference lists.

Meaning:
- real measured software list-driven control
- current first practical enterprise use case for this benchmark pack

### `nol8sim`

Behavior placeholder for Nol8-style control semantics.

Meaning:
- useful for action vocabulary and target behavior
- not a measured production Nol8 result
- not valid for product-performance claims

## Measured vs simulated

The key rule is:

Measured software modes can support statements about the current benchmarked software path.

Simulated Nol8 modes cannot support statements about real Nol8 production efficiency.

That means the current report can support claims like:
- "`re2` and `listmatch` are measured software baselines."
- "`listmatch` governed a large share of the corpus before embedding."
- "Software list-driven control consumes CPU to enforce these decisions."

The current report cannot support claims like:
- "Nol8 is X times faster than software."
- "Nol8 proved FPGA savings."
- "The simulation demonstrates real product efficiency."

## How to read the CPU table

### User CPU sec

Time spent in benchmark code.

### System CPU sec

Kernel/OS work on behalf of the benchmark process.

### Total CPU sec

User plus system CPU time.

This can exceed elapsed wall-clock time because CPU work can accumulate across cores.

### CPU cores used

Approximate average number of fully utilized CPU cores during the run.

### Max RSS KB

Peak resident memory used by the benchmark process.

## How to read the top-level listmatch story

For the current first-pass use case, the most important questions are:
- how much content was prevented from reaching embedding
- how much of the corpus was governed by enterprise controls
- how much CPU the software path used to enforce those controls

That is why the current report emphasizes:
- token reduction
- prevented-from-embedding percentage
- governed share
- CPU multiple versus `re2`

## Current safe interpretation

The current benchmark proves:
- the workload exists
- software baselines can be measured
- enterprise watchlists and indicators can materially affect what reaches embedding
- software enforcement has a real CPU cost

The current benchmark does not yet prove:
- real Nol8 production efficiency
- real Nol8 accelerator savings
- measured product advantage versus the software baseline

## Next step

The next step after this report is:

Run the same benchmark contract against a real Nol8 implementation and return measured results in the same artifact format.

See:
- `docs/08_external_nol8_execution.md`
