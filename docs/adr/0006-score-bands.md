# 0006 — Bands and breakdown instead of a numeric score

**Status:** Accepted
**Date:** 13 August 2026

## Context

Version 1.0 presented results with `SCORE 94` out of 100, and elsewhere compared results as
94, 92 and 86.

That conflicts with the document's own principles. P4 states "explicit uncertainty over false
precision". Old §137 stated that confidence is deterministic metadata, not a score. Yet the
headline number is two significant figures over a weighted sum of heterogeneous dimensions —
cash value, comfort, directness, airport preference, risk — with weights the user configures
freely.

The difference between 94 and 92 carries no meaning. The weights are arbitrary personal
settings; the components are measured in incomparable units and normalized by convention. But
a two-digit score communicates a precision that the underlying computation does not possess,
and users reasonably act on that apparent precision.

The problem compounds across searches. Two searches with different weight presets and
different candidate sets produce scores with no shared scale, yet nothing about the display
discourages comparing them.

## Options

**Keep the number, add confidence alongside.** Immediately legible, easy to compare at a
glance, and preserves the apparent precision that is the actual problem.

**Bands plus breakdown, ordering preserved.**

**Rank and breakdown only, no score at all.** Maximum epistemic honesty; loses the user's
sense of whether the top result clearly leads or barely edges out the next.

## Decision

The additive computation is unchanged and still determines ordering. **The number is not
displayed.** Results show a band with the contributing factors:

```
EXCELLENT   Best overall for this profile

  + Exceptional historical price      9th percentile, high confidence
  + Strong award value                3.1 cents per point
  + Elite status benefits apply       Flying Blue Gold
  + Preferred airport                 MXP
  − Connection risk                   1h05 at CDG, below comfortable
```

Bands: `EXCELLENT | GOOD | FAIR | WEAK`. Three rules attach:

1. Bands are **never compared across searches.**
2. A result whose key inputs are `UNKNOWN` or `STALE` is marked low confidence and **cannot
   occupy the top band** regardless of arithmetic — a high score computed from missing data is
   the most dangerous output this system could produce.
3. Every result explains both its own position and what separates it from the one above.

The score is not exposed through the API either (`docs/api.md §7`). Exposing it would invite
clients to reconstruct exactly the comparison this decision prohibits.

## Consequences

**Precision is no longer implied where it does not exist**, and the interface stops
contradicting the specification's stated philosophy.

**A band boundary is itself a discontinuity.** Two adjacent results can land either side of
one. Mitigated by always showing rank order and the breakdown, so the band is a summary rather
than the whole answer.

**"How much better is #1?" becomes harder to answer at a glance.** This is the intended
trade: the honest answer to that question is usually "not by a measurable amount", and the
breakdown conveys it better than a two-point gap did.

**Rule 2 requires confidence to propagate through the ranking pipeline**, not merely to be
computed for display. A derived value is never more confident than its least confident input
(`spec §43`).

Supersedes old §107–§108. Implemented by `spec §71`.
