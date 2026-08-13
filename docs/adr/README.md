# Architecture Decision Records

Each ADR records one decision: its context, the alternatives considered, what was chosen, and
what that costs. ADRs are immutable once accepted — a decision that changes gets a new ADR
that supersedes the old one, rather than an edit. The record of what we believed and why is
as valuable as the conclusion.

Issues do not hold decisions; they consume them. When an issue's implementation reveals that
a decision was wrong, the correction is a new ADR plus an update to `specifications.md` in the
same pull request.

| # | Decision | Status |
|---|---|---|
| [0001](0001-zero-budget-source-strategy.md) | Zero-budget source strategy and source classification | Accepted |
| [0002](0002-generic-host-inverted-resource-model.md) | Generic containerized host; storage over source access | Accepted |
| [0003](0003-retention-policy.md) | Raw payloads 12 months, normalized data indefinitely | Accepted |
| [0004](0004-vite-spa-over-nextjs.md) | Vite SPA instead of Next.js | Accepted |
| [0005](0005-collection-before-evaluation.md) | Historical collection precedes historical evaluation | Accepted |
| [0006](0006-score-bands.md) | Bands and breakdown instead of a numeric score | Accepted |
| [0007](0007-observation-volume-estimate.md) | Observation volume estimate and default query budget | Accepted |

## Format

```markdown
# NNNN — Title

**Status:** Proposed | Accepted | Superseded by NNNN
**Date:** YYYY-MM-DD

## Context
What forced a decision. Facts, not preferences.

## Options
What was genuinely considered, with the case for each.

## Decision
What was chosen.

## Consequences
What this costs, what it forecloses, and what must now be true.
```
