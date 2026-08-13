# 0007 — Observation volume estimate and default query budget

**Status:** Accepted
**Date:** 13 August 2026

## Context

ADR 0003 set retention policy on an admitted guess — "single-digit GB per year at personal
volumes" — and deferred the real number to a spike (`specifications.md §89` item 5, tracked
as issue #6). Two things were still unspecified and blocking that estimate: how many calls a
persistent watch spends per day (`spec §28` shows `budget.calls: 200` only as one query's
example, not a system default), and how many watches a personal deployment realistically
runs. Without both, "observation volume" has no number to attach to.

This spike cannot measure real payload sizes — that requires a live Travelpayouts token,
which is not yet provisioned (blocks issue #22). The estimate below is therefore a documented
calculation from the architecture's own numbers (`spec §28`, `§56`, `§57`), not a live
measurement, and is flagged for re-verification once real traffic exists.

## Calculation

**Assumptions, chosen and made explicit rather than left implicit:**

- 10 persistent watches — a plausible ceiling for a single household (a handful of travellers,
  a handful of recurring routes each).
- Default daily budget: **100 calls/watch/day**, set as `config/`'s default
  `DAILY_WATCH_BUDGET`. Half of the `budget.calls: 200` used in the one-off search example in
  `spec §28`, since a recurring watch accumulates coverage over days (`spec §28`, final
  paragraph) and does not need to exhaust a route's space in a single run.
- Each Travelpayouts price-calendar call returns on the order of 30 days of prices for one
  route/cabin pair (`docs/providers.md` "What it provides").
- Material-change rate: most repeat polls of an already-observed date return the same cached
  upstream value (Travelpayouts itself only refreshes every 2–7 days per `docs/providers.md`
  "Critical limitation"), so most polls extend `last_seen_at` rather than opening a new
  observation row (`spec §56`). Estimated 20% of touched date/cabin points produce a new row
  on a given day — deliberately pessimistic (i.e. overestimates volume) given the 2–7 day
  upstream refresh window would predict closer to 15–50%.

**Resulting daily volume:**

```
calls/day        = 10 watches × 100 calls/watch           = 1,000 calls/day
date points/day   = 1,000 calls × 30 days/call             = 30,000 touched points/day
new obs. rows/day = 30,000 × 20% material-change rate      = 6,000 rows/day
```

**Annualized:**

```
observation rows/year   ≈ 6,000 × 365                       ≈ 2,190,000 rows/year
normalized storage/year ≈ 2.19M rows × ~250 B/row (incl. indexes)  ≈ 550 MB/year
raw payloads/year        ≈ 1,000 calls/day × 20 KB/call avg × 365 ≈ 7.3 GB/year uncompressed
raw payloads, compressed ≈ 7.3 GB × ~20% (gzip on repetitive JSON) ≈ 1.5 GB/year
```

`flight_price_daily` aggregates (`spec §57`) are bounded by distinct
`(date, route, cabin, fare_family, source)` combinations actually touched — a strict subset of
observations, so they add negligible additional volume on top of the above.

## Decision

Adopt **100 calls/watch/day** as the default daily budget allocation for persistent searches
(`spec §28`), configurable per-watch. Adopt the volume estimate above as the working number
for ADR 0003's retention policy: raw payload growth on the order of **1–2 GB/year**,
normalized-observation growth on the order of **0.5 GB/year**, at the assumed 10-watch
personal scale. Both fall well inside "storage is abundant" (`CLAUDE.md §6`) for any
reasonable home-server disk, including multi-year retention beyond the current 12-month raw
window if that is ever revisited.

## Consequences

**Retention policy (ADR 0003) is confirmed, not just guessed.** The twelve-month raw / indefinite
normalized split costs low single-digit GB even after several years at this scale.

**The 20% material-change assumption is deliberately conservative** (i.e. it overstates
volume) relative to Travelpayouts' own 2–7 day refresh cadence, so the real number is more
likely to run lower than this estimate, not higher.

**This estimate is unverified against live traffic** — payload size (20 KB/call) and the
material-change rate are both architectural estimates, not measurements. Issue #22 (walking
skeleton) is the first point real Travelpayouts traffic exists; **once it runs for at least a
week, this ADR should be revisited with real numbers** and either confirmed or superseded.
That follow-up is tracked as a note on issue #22, not a new spike — it does not block M1.

**A single default budget number is a starting point, not a final tuning.** Different watches
have very different space sizes (one route/cabin vs. multi-origin/multi-cabin); per-watch
budget override already exists in the query model (`spec §28`) precisely so this default can
be overridden case by case rather than needing to be right for every watch at once.

Implemented by `spec §28` (default budget), `spec §55` (retention, confirmed by this ADR).
