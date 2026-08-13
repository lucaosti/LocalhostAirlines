# 0005 — Historical collection precedes historical evaluation

**Status:** Accepted
**Date:** 13 August 2026

## Context

Version 1.0 sequenced work as: infrastructure, flight search, search engine, loyalty, awards,
travel requirements, **historical intelligence (phase 7)**, watchlists and Telegram, UI.

That ordering is coherent as a dependency graph — each phase builds on the last — and it is
the ordering most people would choose. It also has a flaw that the dependency graph cannot
show.

Every capability in this system works on the day it is finished. Historical intelligence does
not. Percentiles, medians and confidence require observations, and observations require
**calendar time**. A collection pipeline reaching production in month seven produces
percentiles that remain statistically worthless until month ten.

Historical intelligence is also the project's primary differentiator (P5). Anyone can show a
price; this system exists to say whether the price is good.

## Options

**Keep the original ordering.** Each phase is complete in itself and dependencies flow
naturally. The differentiating feature is unusable for months after it is built.

**Split collection from evaluation, and move collection early.**

**Collect from M0, before the walking skeleton.** A throwaway script writing raw observations
from day one. Maximum accumulated data, at the cost of writing something that must then be
rebuilt inside the real architecture — and of collecting data whose schema has not yet been
validated end to end.

## Decision

Split the concern in two and move collection to M2, immediately after the walking skeleton:

```
M2  Collection    scheduler, raw retention, partitioning, aggregates,
                  source health, circuit breakers      ← the historical clock starts
M4  Evaluation    percentiles, comparison scope, confidence, assessments
```

Collection runs against one source and a modest route set. It does not need the full search
engine, multi-origin expansion or ranking, all of which arrive at M3.

Rejected collecting from M0: the walking skeleton at M1 exists precisely to prove that real
data survives every layer, and collecting before that validation risks accumulating months of
data with a defect baked in.

## Consequences

**The historical clock starts in week two or three** rather than month seven. When M4 builds
percentiles it operates on real accumulated data instead of an empty table.

**Collection ships before the search engine that will eventually feed it.** M2's collection is
deliberately narrow — a scheduled job over a fixed route set — and is generalized at M3. This
is accepted duplication of effort, and it is small.

**Partitioning and retention must be right at M2**, since real data starts flowing
immediately. Consistent with ADR 0003.

**Quality gates must be right at M2 too.** Bad data written into history is effectively
permanent: history is the one store where a bad write cannot be casually corrected, because
the source cannot be re-queried for the past. `spec §36` is therefore a hard M2 requirement
rather than a later refinement.

Supersedes old §201–§210. Implemented by `spec §85`, `§86`.
