# 0001 — Zero-budget source strategy and source classification

**Status:** Accepted
**Date:** 13 August 2026

## Context

Version 1.0 of the specification was built on Skyscanner, Duffel, an unnamed award provider
and IATA Timatic, and forbade scraping as a core dependency (old §171). A review of actual
availability in August 2026 found that none of the assumed sources is obtainable at zero cost:

- **Skyscanner Flights Live Prices** is partner-only, requiring a business review and a
  commercial agreement aimed at travel businesses.
- **Amadeus Self-Service**, the standard free fallback, was decommissioned on 17 July 2026.
- **Kiwi Tequila** is invitation-only for new partners.
- **Duffel** is self-serve but charges per booking and per excess search, and its free tier
  returns synthetic data from a sandbox airline.
- **IATA Timatic** is an enterprise product.
- **seats.aero** offers the best award data at roughly €9/month — real, but not zero.

The project constraint is a zero recurring budget. The old specification therefore described
a system that could not be built, and the contradiction between "no hardcoded mutable facts"
and "no scraping" had no resolution: no API exists for Amex transfer ratios or entry
requirements at any accessible tier.

## Options

**Pay for a minimal set.** Roughly €9/month for seats.aero plus per-search Duffel costs would
make the two weakest areas the strongest. Rejected: violates the budget constraint.

**Free official sources only.** Travelpayouts and curated data. Zero ambiguity about terms,
but no award availability at all — which removes the award engine, transfer calculation and
reverse search from a points balance, i.e. most of what distinguishes this project from a
price tracker.

**Maximum obtainable coverage.** Free official APIs, open datasets, unofficial JSON endpoints
and scraping including headless rendering, with hard ethical limits.

## Decision

Maximum obtainable coverage, with a formal **source classification** replacing the blanket
scraping prohibition:

| Class | Expected reliability |
|---|---|
| `OFFICIAL_API` | High; breaks with notice |
| `PUBLIC_DATA` | Very high; changes slowly |
| `UNOFFICIAL_ENDPOINT` | Moderate; breaks without notice |
| `SCRAPED` | Low; breaks frequently |

Two limits are absolute and not configurable: **CAPTCHAs are never bypassed**, and **personal
loyalty account logins are never automated.** The risk of locking the user out of their real
accounts is not worth the convenience, and manual balance entry was already a first-class
path.

A third class of provenance, `CURATED`, resolves the P1/scraping contradiction: facts with no
API live as versioned database records seeded from files under version control, carrying
`verified_at` and `review_due_at`. A scraper may keep them fresh; if it breaks, the record
does not become wrong — it becomes overdue for review.

## Consequences

**The reliability engineering moves from optional to P0.** Contract tests against fixtures,
per-source health tracking, circuit breakers and fail-loud parsing are now load-bearing rather
than hardening. Without them a scraper-based system produces wrong data instead of absent
data.

**The specification's epistemics become the safety mechanism.** P3 and P4 already required
distinguishing ignorance from absence and expressing uncertainty explicitly. That is exactly
what makes fragile sources tolerable: a broken source degrades to `UNKNOWN` behind an open
circuit, and the interface says so.

**Maintenance is the real cost, not money.** An unattended scraper is broken most of the time.
The system must remain useful while degraded, and source health becomes the primary
operational signal.

**Travel requirements are guidance, not compliance.** Without Timatic, the system says so in
the interface, non-dismissibly, wherever a requirement affects feasibility.

**The paid path stays open.** seats.aero and Duffel are ordinary adapters behind capability
flags. Adopting them later requires no architectural change, and they remain documented in
`docs/providers.md` for that reason.

Supersedes old §171. Implemented by `spec §17`–`§26`, `§40`.
