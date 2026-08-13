# External Sources

Companion to `specifications.md`. This document holds the operational detail of every
external source the system consumes: how to reach it, what it can answer, what it costs, how
it fails, and how much to trust it.

The specification defines *why* sources are classified and how the system behaves when one
breaks (`spec §17–§26`). This document defines *what each one actually is*.

**Accuracy discipline.** Endpoint shapes and limits for `UNOFFICIAL_ENDPOINT` and `SCRAPED`
sources are not contractual and change without notice. Every entry states its verification
status. An entry marked `UNVERIFIED` has not yet been confirmed against the live source and
must be validated by a `type:spike` issue before an adapter is written against it. Do not
treat anything here as guaranteed — treat it as the current best understanding, to be
corrected in place as reality is discovered.

---

## Source register

| Source | Class | Role | Cost | Status |
|---|---|---|---|---|
| [Travelpayouts Data API](#travelpayouts-data-api) | `OFFICIAL_API` | Cash prices, discovery | Free | Planned, M1 |
| [OurAirports](#ourairports) | `PUBLIC_DATA` | Airport reference | Free | Planned, M0 |
| [OpenFlights](#openflights) | `PUBLIC_DATA` | Airline reference | Free | Planned, M0 |
| [ECB reference rates](#ecb-reference-rates) | `PUBLIC_DATA` | FX conversion | Free | Planned, M0 |
| [Airline open endpoints](#airline-open-endpoints) | `UNOFFICIAL_ENDPOINT` | Cash, live | Free | Rejected — no adapter (issue #2) |
| [Google Flights](#google-flights) | `UNOFFICIAL_ENDPOINT` | Cash, broad coverage | Free | Spike required |
| [Amex Italy partners](#amex-italy-transfer-partners) | `SCRAPED` | Transfer rules | Free | Planned, M5 |
| [Visa requirements](#visa-requirements) | `SCRAPED` | Entry requirements | Free | Planned, M7 |
| [Award availability](#award-availability) | `SCRAPED` | Award space | Free | Spike required, M6 |
| [Deferred sources](#deferred-sources) | — | Not adopted | Paid or gated | Documented for reference |

---

## Adapter contract

Every adapter, regardless of class, implements the same interface and declares the same
metadata. Nothing above the normalization layer knows which class a source belongs to.

```python
class SourceAdapter(Protocol):
    """One external source. Lives in the DISCOVERY layer (spec §5).

    Adapters know HTTP, HTML, rate limits and authentication.
    They know nothing about loyalty programmes, ranking or the traveller.
    """

    source_id: str
    source_class: SourceClass          # spec §18
    capabilities: Capabilities         # spec §22

    async def health(self) -> HealthReport: ...

    async def search_cash(
        self, query: CashQuery, budget: Budget,
    ) -> AsyncIterator[RawPayload]: ...

    async def search_award(
        self, query: AwardQuery, budget: Budget,
    ) -> AsyncIterator[RawPayload]: ...

    async def refresh(self, reference: SourceReference) -> RawPayload: ...
```

Three rules bind every adapter:

1. **It yields raw payloads, never canonical models.** Normalization is a separate layer with
   its own tests, so that a parser can be fixed and re-run against retained payloads
   (`spec §4`, `§55`).
2. **It fails loudly on an unrecognised shape.** `SCHEMA_CHANGE` is raised; partial data is
   never returned. A missing field becomes `UNKNOWN`, never `0`, `false` or `[]`
   (`spec §21`, `§45`).
3. **It charges the budget it was given** and stops when exhausted, reporting what it did not
   explore rather than implying it found nothing (`spec §28`).

### Capability declaration

```yaml
capabilities:
  search_cash: true
  search_award: false
  refresh_price: false
  batch_query: true        # answers many routes in one call — see spec §28
  baggage: false
  fare_brand: false
  booking_link: true
  aircraft: false
```

`batch_query` deserves attention: a source answering a whole month of dates in one call
collapses the search-space explosion and is worth preferring even when its data is older.

---

## Travelpayouts Data API

**Class** `OFFICIAL_API` · **Cost** free · **Verification** documented by vendor · **Tier** discovery

The backbone of cash-price collection. A genuine, documented, free API with a self-service
token — the only such source available to this project.

### Access

Register at travelpayouts.com; the token appears under the API section of the profile. It is
an affiliate programme: no per-call charge, revenue would come from bookings we do not make.
Registration is free and imposes no traffic minimum for the Data API.

Token supplied via `TRAVELPAYOUTS_TOKEN` in `.env`, never committed.

### What it provides

Cheapest fares per route and date, month-level price calendars, cheapest-day discovery,
popular destinations, and reference lookups for airlines, airports, cities and countries.

### Critical limitation

**Data is cached and aggregated, not live.** Values are 2–7 days old depending on endpoint.
The genuinely live search API requires 50,000 monthly active users and is out of reach.

This is acceptable and well-matched to our primary use. Building the historical record
(`spec` P5) needs breadth and consistency across time far more than freshness in seconds.
Everything sourced here is presented as `CACHED` with its true age (`spec §42`) — never as
live.

### Rate limits

Per-endpoint, approximately 300 requests/minute on price calendars and 30 requests/minute on
statistics queries. Our own limiter is set well below these: the constraint that binds is
politeness and the freshness window, not the ceiling.

### Failure modes

| Condition | Classification |
|---|---|
| Invalid or expired token | `AUTHENTICATION` |
| Limit exceeded | `RATE_LIMIT` — back off, do not retry harder |
| Empty result for a valid route | `NOT_AVAILABLE` — a genuine absence, not an error |
| Response shape changed | `SCHEMA_CHANGE` — fail loudly |

The third row matters: this source answers "no cached price for that route" legitimately, and
that is `UNAVAILABLE`, distinct from `UNKNOWN` (`spec §45`).

### Retention

Standard: raw 12 months, normalized indefinitely (`spec §55`).

---

## OurAirports

**Class** `PUBLIC_DATA` · **Cost** free · **Licence** public domain · **Verification** stable

Airport reference data: IATA and ICAO codes, names, municipality, country, coordinates,
elevation and type. Distributed as CSV.

### Timezone resolution

OurAirports does **not** publish a timezone column. Since every duration and connection
calculation in the system depends on knowing each airport's IANA zone (`spec §12`), the zone
is resolved in this order:

1. **OpenFlights `airports.dat`**, which carries an Olson timezone column.
2. **`timezonefinder`**, resolving OurAirports coordinates offline, for airports absent from
   OpenFlights or carrying a blank zone.
3. Otherwise the airport is marked `timezone_unresolved` and any itinerary touching it fails
   the quality gate (`spec §36`) rather than being stored with a guessed zone.

Step 3 is the important one. A wrong timezone produces a plausible-looking duration that is
silently hours off, which is worse than a rejected itinerary.

Refreshed monthly by a scheduled job. Changes are diffed and applied; a code disappearing is
logged rather than silently dropped, since itineraries in history may reference it.

Also the authority for the airport-group feature (`spec §27`): Milan resolving to MXP, LIN and
BGY is derived from municipality and distance, not hardcoded.

---

## OpenFlights

**Class** `PUBLIC_DATA` · **Cost** free · **Licence** open database · **Verification** stable, but ageing

Airline reference: IATA and ICAO codes, names, country, active status. Also historical route
data, and the Olson timezone column used as the primary source for airport zones (see
[OurAirports](#ourairports)).

**Known weakness:** OpenFlights is not actively maintained at the pace airlines change. It is
adequate for resolving codes to names, but must **not** be treated as authoritative for
alliance membership, which is versioned `CURATED` data instead (`spec §49`). Alliances change,
and a stale dataset would silently produce wrong benefit calculations.

Refreshed monthly. Codes present in provider payloads but absent here are flagged for review
rather than discarded.

---

## ECB reference rates

**Class** `PUBLIC_DATA` · **Cost** free · **Verification** stable, published on a fixed schedule

Daily euro foreign-exchange reference rates, published as XML by the European Central Bank
each working day around 16:00 CET.

Used for every cross-currency comparison. Per `spec §14`, a converted value carries the date
of the rate used, because a conversion is a derived fact and needs provenance like any other.

Rates are stored as a versioned table, never overwritten: reprocessing a historical
observation must use the rate that applied on the observation's date, not today's. No rate is
published on weekends and holidays; the most recent preceding rate is used and its actual
date is recorded, so the gap is visible rather than hidden.

---

## Airline open endpoints

**Class** `UNOFFICIAL_ENDPOINT` · **Cost** free · **Verification** spike complete — **rejected, no adapter** (issue #2)

Several carriers expose unauthenticated JSON endpoints consumed by their own web frontends.
Where these exist they are the highest-quality free live data available: structured, fast, and
without the fragility of HTML parsing. Coverage skews strongly toward low-cost carriers, which
limits usefulness for the long-haul premium cabins this project cares most about — and, as
the spike below found, that ceiling turns out not to matter, because neither of the two
carriers this document previously named as candidates clears the ToS bar regardless of
coverage.

### Required spike — resolved, both candidates rejected

**Ryanair** — rejected on terms of use (criterion 4). Ryanair's own Terms of Use explicitly
prohibit automated data extraction, name APIs specifically, and are not limited to a
"commercial use" carve-out for the broader automation clause:

> "Use of any automated system or software ... to extract any data from this website for
> commercial purposes ('screen scraping') is strictly prohibited," and separately, use of the
> site — including "its underlying computer programs (including [APIs])" — is restricted to
> "private, non-commercial purposes."

This is not a theoretical restriction: Ryanair has litigated and won on it (*Ryanair v PR
Aviation*, CJEU; a further UK High Court injunction against a screen-scraper). A personal,
non-commercial deployment plausibly falls inside "private, non-commercial purposes" for
*browsing* the site, but the automated-extraction clause is not qualified the same way and
Ryanair's litigation history shows it enforces against automation specifically, not only
against commercial resale. Given `spec §19`'s own instruction to access sources politely and
respect their terms, and this spike's own rule (adopt only if positive on **all** five
points), this is a clean reject — checking the other four points would not change the
outcome, so the spike stops here for this carrier.

**Wizz Air** — rejected on reachability grounds (criterion 1/2). The site actively blocked a
standard, honestly-identified HTTP fetch at the edge (`405 Method Not Allowed`) before any
endpoint-specific probing was attempted, and its terms of use could not be retrieved through
normal means for the same reason. This is itself the answer to "is it reachable without
extra measures": no, not without impersonation techniques this project does not use (spec
§19's requirement to identify honestly rules out disguising the client to get past this).
Combined with Ryanair's outcome, coverage from this category would in any case be limited to
carriers whose premium long-haul relevance is already low.

**Verdict: no adapter is built in this category.** Both currently-known candidates fail a
required criterion outright; no adapter, no fixture, no contract test. If a future carrier is
found to expose an endpoint under genuinely permissive terms, it re-enters through a fresh
spike rather than reopening this one.

### Handling

Not applicable — no adapter exists in this category.

---

## Google Flights

**Class** `UNOFFICIAL_ENDPOINT` · **Cost** free · **Verification** `UNVERIFIED` — spike required

The broadest free cash coverage available, reachable at low volume through the interface its
own frontend uses. Its official partner programme is invite-only under confidentiality and is
not a path available to this project.

### Expected characteristics

Broad carrier and route coverage, prices much closer to live than Travelpayouts, and a query
encoding that is compact but undocumented and periodically changed.

### Expected fragility — high

This is the adapter most likely to break, and to break without warning. It is therefore:

- kept behind a capability flag and disabled by default until the spike confirms it works;
- restricted to **low volume**, discovery tier only;
- never a dependency for any feature — its loss degrades coverage, never function;
- excluded from any request-path work.

Anti-bot measures may escalate at any time. If a CAPTCHA appears, the source is dropped
(`spec §19`). Repeated `BLOCKED` classifications reduce the access rate automatically rather
than triggering retries.

### Required spike

Establish current query encoding and response shape; measure the volume at which blocking
begins; assess the maintenance cost realistically over a few weeks. Adopt only if it survives
that observation period.

---

## Amex Italy transfer partners

**Class** `SCRAPED` · **Cost** free · **Verification** page is public and stable · **Tier** curated refresh

American Express Italy publishes its Membership Rewards airline partners with transfer
ratios, minimum transfer amounts, increments and estimated transfer times on a public
marketing page.

### Why this is scraped rather than curated by hand

The data underlies irreversible user decisions (`spec §51`) and changes occasionally without
announcement. The page is static, public and small; fetching it weekly is negligible load and
carries little risk.

### Interaction with `CURATED` provenance

The scraper does not own the data. It keeps a `CURATED` record fresh (`spec §40`). This
distinction is what makes the source's fragility tolerable:

- Scrape succeeds and matches → `verified_at` updated, `review_due_at` extended.
- Scrape succeeds and differs → new versioned record, `TransferRuleChanged` event, the user
  is notified because a ratio change is materially important.
- Scrape fails → the record **does not become wrong.** It becomes overdue for review, the
  freshness state degrades, and the user is asked to confirm against the official page.

A transfer rule is never deleted. Superseded versions are retained with their effective dates
so historical evaluations remain reproducible (`spec §46`).

### Schedule and fragility

Weekly. Ratios are parsed as integer pairs, never decimals (`spec §50`). A parse failure never
overwrites a good record — it raises `SCHEMA_CHANGE` and leaves the last verified value
standing with degraded freshness. Marketing pages are restructured periodically, so this is
expected behaviour rather than an incident.

---

## Visa requirements

**Class** `SCRAPED` · **Cost** free · **Verification** verified — table shape (issue #5); parser still unwritten · **Tier** curated refresh

### Sources

**Wikipedia — "Visa requirements for \<nationality\> citizens".** Maintained, structured as
tables, licensed CC BY-SA, and covering essentially every passport and destination pair.
Community-maintained, so accuracy varies by destination popularity.

**Viaggiare Sicuro (Italian Ministry of Foreign Affairs).** Authoritative for Italian
passport holders and the cross-reference against Wikipedia.

### Honest positioning — mandatory in the interface

IATA Timatic is the authoritative source for boarding compliance and is an enterprise product
unavailable to this project. Consequently:

> The system provides **travel planning guidance, not boarding compliance.**

This disclaimer is not dismissible on any result where a requirement affects feasibility
(`spec §64`). Where the two sources disagree, both are shown with their provenance and the
value is marked `CONFLICTING` (`spec §48`) — the system does not adjudicate between a
government ministry and an encyclopaedia.

### Parsing

**Resolved by spike (issue #5, `spec §89` item 4).** Checked against `Category:Visa
requirements by nationality` (~216 articles, essentially every UN member state plus a handful
of disputed/special entities) and sampled across a major passport (Italian), a mid-size one
with sparser coverage (Malagasy) and a micro-state (Tuvaluan). Verdict: **the table shape is
consistent enough for one generic parser, with no per-country special-casing** — every page
sampled used the same four columns, in the same order:

```
Country/Region | Visa requirement | Allowed stay | Notes (excluding departure fees)
```

What varies is not structure but **cell completeness**: less-documented passports (Malagasy
sampled) leave `Allowed stay` or `Notes` blank for some rows, where a major-passport page
(Italian) fills them consistently. A blank or ambiguous cell yields `UNKNOWN` for that
pair, never a guess — this was already the designed behaviour (`spec P3`) and the sparseness
found here is exactly the case it exists for, not a surprise it needs to accommodate.

Footnotes appear as inline superscript references resolving to cited prose (fees, validity
requirements, exemptions) and must be captured, not discarded — confirmed present and in the
same anchor-link form across all three sampled pages.

### Transit

`spec §65` requires evaluating every transit point, not just the destination. **Confirmed by
the same spike:** none of the three sampled pages carries a separate transit-specific
section or table — a dedicated `Transit without visa` article does not exist on English
Wikipedia (returns 404) — so transit information, when present at all, is folded into a
destination's own `Notes` cell and is frequently simply absent. This means transit readiness
will resolve to `UNKNOWN` for a meaningful share of itineraries at launch — not a bug to fix,
but the correct outcome of `spec §65`'s own rule: a one-stop itinerary that looks cheap
because its transit visa was never checked is the specific failure that rule exists to
prevent, and Wikipedia alone does not give enough evidence to clear it for most transit
points. Viaggiare Sicuro is the fallback cross-reference; where both are silent on a transit
point, the itinerary carries `UNKNOWN` transit readiness, exactly as designed.

### Schedule

Weekly per passport country configured on a traveller profile, plus on demand when an
itinerary is evaluated against an uncached country pair.

---

## Award availability

**Class** `SCRAPED` · **Cost** free · **Verification** `UNVERIFIED` — spike required · **Milestone** M6

The hardest category, and the one where the zero-budget constraint costs most.

### What is excluded and why

**Airline award search pages** (Flying Blue, British Airways Executive Club, and similar)
require authenticated sessions and carry serious bot protection. Automating them means
handling real credentials and risking lockout of the user's actual accounts. Excluded under
`spec §19`.

**seats.aero** is the highest-quality award data available and offers a partner API at
roughly €9/month covering 24 mileage programmes with a 1,000-call daily allowance. Scraping
it instead of subscribing would directly circumvent the business model of a small vendor, and
would be blocked. **Excluded on principle, not merely on feasibility.**

If the zero-budget constraint is ever relaxed, seats.aero is the single highest-value
purchase available to this project, and the adapter should be written against its documented
API rather than against anything else.

### What remains

Award-space sources that are publicly readable without authentication. What qualifies must be
established by spike before M6 — this section is currently a statement of intent, not of
capability.

### Consequence if nothing qualifies

The award engine, transfer calculation and reverse search from a points balance are all built
regardless: they are pure domain logic, fully unit-testable against fixtures, and they are a
substantial part of what distinguishes this project. They simply operate on manually entered
award observations until an automated source exists.

**Manual award entry is therefore a first-class feature, not a stopgap** — consistent with how
`spec §41` already treats loyalty balances. The user who checks an award on an airline site
can record what they saw, and it enters the historical record with `USER_ENTERED` provenance
like any other observation.

---

## Deferred sources

Documented so the reasoning is not re-litigated, and so the decision can be revisited if
circumstances change.

| Source | Status as of August 2026 | Would provide | Revisit when |
|---|---|---|---|
| **Skyscanner Flights Live Prices** | Partner-only; business review plus commercial agreement | Live multi-source cash search, nearby airports, itinerary refresh | Never, realistically — the programme targets travel businesses |
| **Amadeus Self-Service** | Decommissioned 17 July 2026; Enterprise only | Was the standard free flight-search API | Not returning |
| **Duffel** | Self-serve, but production charges per booking and per excess search; free tier returns synthetic sandbox data | Genuine live fares, bookable offers, offer refresh | If budget allows: ideal for the verification tier (`spec §23`), where volume is low by design |
| **Kiwi Tequila** | Invitation-only for new partners | Broad inventory including virtual interlining | If an invitation becomes available |
| **seats.aero** | ~€9/month, 1,000 calls/day, non-commercial use permitted | Award availability across 24 programmes | **Highest-value purchase if budget is ever relaxed** |
| **IATA Timatic** | Enterprise product | Authoritative entry requirements | Not available at any accessible tier |

The Duffel and seats.aero rows describe a coherent paid upgrade path: roughly €9/month plus
occasional per-search cost would convert the two weakest areas of the system — live cash
verification and award availability — into their strongest. Nothing in the architecture needs
to change to adopt them; both are ordinary adapters behind capability flags (`spec §22`).

---

## Adding a source

1. Open a `type:spike` issue. Establish reachability, response shape, limits, blocking
   behaviour, terms of use, and coverage. **The spike's deliverable is an entry in this
   document**, not code.
2. Record the entry with its class, capabilities and expected fragility.
3. Capture fixtures and write contract tests **before** the adapter.
4. Implement the adapter against the contract in this document.
5. Implement normalization separately, with its own tests.
6. Register capabilities, rate limits and circuit-breaker thresholds in configuration.
7. Enable behind a capability flag, disabled by default. Enable in production only after
   observing health for a meaningful period.

Steps 3 and 7 are the ones that get skipped under time pressure, and they are the two that
determine whether a fragile source is an asset or a liability.
