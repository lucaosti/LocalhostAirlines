# 0003 — Raw payloads 12 months, normalized data indefinitely

**Status:** Accepted
**Date:** 13 August 2026

## Context

ADR 0002 established that storage is cheap and source access is scarce, and that retaining raw
payloads makes parser bugs recoverable. That raises the question of how long, since "forever"
and "not at all" are both defensible and have very different costs.

The asymmetry is what matters. Normalized observations are small, structured and are the
actual analytical asset. Raw payloads are large, unstructured, and useful for exactly one
purpose: reprocessing when a parser is fixed or improved.

## Options

**Keep everything indefinitely.** Maximum recoverability; unbounded growth, largely of data
whose only use is a reprocessing that becomes less likely as time passes.

**Keep raw payloads 12 months; keep normalized data and aggregates indefinitely.**

**Per-source retention policies.** Most precise and best aligned to individual terms of use,
but adds a configuration dimension to maintain, and gets it wrong in exactly the cases that
matter — the fragile sources whose parsers break.

## Decision

```
Raw payloads             compressed    12 months
Normalized observations                indefinite
Daily aggregates         derived       indefinite
```

The twelve-month window is a **reprocessing window**: a parser fix within a year can
re-normalize the affected history. Beyond a year, the probability of a useful reprocessing
falls sharply, while storage cost continues to accumulate.

Per-source override remains available through `retention_override` in the source capability
record, for sources whose terms require shorter retention. The default is uniform; deviation
is explicit.

Retention is enforced by **detaching and dropping monthly partitions**, not by `DELETE`. This
is O(1), avoids table bloat, and imposes no vacuum pressure.

## Consequences

**Storage growth is bounded and predictable.** Raw payloads reach a steady state after twelve
months; normalized data grows slowly because a repeat poll returning identical values updates
`last_seen_at` rather than writing a row.

**A parser bug older than twelve months is unrecoverable** for the affected period. Mitigated
by contract tests, which are designed to catch shape changes at the point they occur rather
than months later.

**Partitioning is required from M2**, not retrofitted. Adding partitioning to a populated
table later is a migration nobody enjoys, and doing it early costs almost nothing.

**Actual growth is unmeasured.** The estimate is modest — single-digit GB per year at personal
volumes — but it is an estimate. Measuring real growth is an open question (`spec §89`) and
the policy is revisited once there is data rather than argued further now.

Implemented by `spec §55`, `§56`.
