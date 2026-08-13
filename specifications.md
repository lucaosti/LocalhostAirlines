# LocalhostAirlines — Technical and Functional Specification

**Version:** 2.0
**Date:** 13 August 2026
**Scope:** Flights only
**Status:** Design agreed, implementation not started

---

## How to read this document

This is the compass of the project. It defines **what** the system is and **why** it is built
that way. It does not track work — that lives in GitHub issues — and it does not enumerate
API details, which live in dedicated companion documents.

| Document | Holds |
|---|---|
| `specifications.md` | Purpose, domain model, architecture, rules, rationale |
| `docs/providers.md` | Every external source: auth, endpoints, limits, capabilities, fragility |
| `docs/api.md` | The system's own REST contract, schemas, error codes, SSE events |
| `docs/adr/` | Individual architecture decisions with their alternatives and consequences |
| `CLAUDE.md` | How we work: process, issue conventions, code standards, stack |

Sections are numbered and those numbers are **stable anchors**. Issues, pull requests and
code comments reference them (`spec §47`). Renumbering breaks every existing reference, so
new material is appended within its part rather than inserted, and obsolete sections are
marked withdrawn rather than deleted.

Version 2.0 supersedes version 1.0 following a full design review. The decisions that changed
are recorded in `docs/adr/` with their reasoning; §170 summarises what moved and why.

---

# PART I — PURPOSE AND PRINCIPLES

## 1. What this system is

LocalhostAirlines is a private, self-hosted, multi-user flight intelligence platform.

It is deliberately **not** a flight search engine. Search engines answer:

> Which flight is cheapest?

This system answers a different and much harder question:

> Which flight is the best option **for this specific traveller**, given cash price, award
> availability, transferable points, elite status, alliance benefits, baggage, cabin, airport
> preferences, travel-document requirements, historical market position, and the traveller's
> actual current balances?

The difference is that the second question cannot be answered by inventory alone. It requires
a model of the traveller, a model of the loyalty ecosystem, and — critically — a memory of
what prices and award availability have looked like over time.

## 2. What it is not

Explicitly out of scope, permanently for the initial architecture:

hotels, car rental, trains, restaurants, activities, travel packages, AI trip planning,
general-purpose conversational agents, automated booking.

The system is flight-centric. No other travel product may influence the data model. This is a
constraint on design, not merely a statement of current priorities: a schema that anticipates
hotels will be worse at flights.

## 3. Core principles

These are load-bearing. Every design decision in this document traces back to one of them.

**P1 — No mutable business fact may exist as a code constant.**
Transfer ratios, elite thresholds, benefit entitlements, alliance membership, visa rules,
baggage allowances: all of these change. They live in the database with provenance, version
and timestamp, regardless of whether they arrived from an API, from a curated seed file, or
from manual entry. Code contains logic; data contains facts. See §46.

**P2 — Every externally-sourced value carries its provenance.**
`source`, `retrieved_at`, freshness state and confidence travel with the value all the way to
the interface. A number without provenance is not displayable. See §44.

**P3 — "Unavailable" and "absent" are different states and must never collapse.**
"No award seats exist" and "we could not check award seats" are opposite facts. Conflating
them is the single most damaging error this system could make, because it silently converts
ignorance into false confidence. See §45.

**P4 — Explicit uncertainty over false precision.**
Where the system does not know, it says so. Where its confidence is low, it shows the
confidence. It never dresses a weak inference in a precise-looking number. See §123.

**P5 — History over snapshots.**
A price is meaningless without its distribution. The system's central differentiator is that
it remembers, and can therefore say whether €742 is good — not merely that it is €742.

**P6 — Deterministic rules over inference.**
Filters, thresholds and explicit scoring, not natural-language interpretation. Every ranking
decision must be explainable as arithmetic over named inputs. No AI dependency exists in this
architecture.

**P7 — Sources are scarce and fragile; storage is abundant.**
See §4. This principle inverts a decision made in version 1.0 and now shapes the entire data
strategy.

## 4. The resource model

Version 1.0 targeted a Raspberry Pi consuming official APIs, and concluded that recomputing a
search was preferable to storing its results. Two decisions invalidated that reasoning: the
deployment target became an ordinary machine with abundant storage, and the data sources
became largely unofficial, because no usable official source is available at zero cost (§30).

The trade-off therefore inverts:

> **Access to sources is the scarce resource. Storage is not.**
> Cache aggressively. Re-fetch as rarely as correctness allows. Persist raw payloads so that
> history can be re-normalized without contacting the source again.

That last clause matters more than it appears. When a parser breaks — and parsers for
unofficial sources break routinely — the raw payloads already collected can be reprocessed
against the fixed parser. Without them, every parsing bug is permanent data loss on sources
that cannot be queried retroactively. Retaining raw payloads converts a class of
unrecoverable failures into a recoverable one. See §55.

## 5. Architectural layering

Five stages, enforced as module boundaries rather than described as a diagram:

```
DISCOVERY  →  NORMALIZATION  →  ENRICHMENT  →  EVALUATION  →  PRESENTATION
```

- **Discovery** talks to the outside world. It knows about HTTP, HTML, rate limits and
  authentication. It knows nothing about loyalty programmes or ranking.
- **Normalization** is the only layer aware of any provider's payload shape. It converts
  provider data into the canonical model (§14) and nothing else.
- **Enrichment** attaches loyalty, award, travel-requirement and historical context to
  canonical itineraries. It never performs I/O against providers.
- **Evaluation** applies hard filters, computes scores and orders results. Pure functions
  over enriched data; no I/O at all, which makes it exhaustively unit-testable.
- **Presentation** serves the web API and the Telegram interface.

Dependencies point in one direction only. Provider adapters never import domain rules; domain
rules never import provider clients. A violation of this ordering is a review blocker, not a
style preference — the layering is what allows a source to be swapped or lost without
cascading changes.

## 6. Deployment model

A single ordinary machine — 8–16 GB RAM, SSD, x86_64 or arm64 — running Docker Compose.
Reachable from trusted devices on the local network. No cloud dependency for any core
function.

Extreme portability is a design goal: nothing is installed on the host. No Python, no Node,
no package manager. Development and production differ only by Compose profile. Images are
built multi-arch for `linux/amd64` and `linux/arm64` so identical images run on an Apple
Silicon development machine and on an x86 production host.

Container topology and the full stack are specified in `CLAUDE.md §6`, which is the
authoritative record; it is not duplicated here.

---

# PART II — DOMAIN MODEL

## 7. Users and travellers

The system is multi-user even when used by one person. Every search, watchlist and balance
belongs to a user. This costs almost nothing now and avoids a painful migration later.

```
User
 ├── Traveller profiles (one or more)
 ├── Loyalty accounts
 ├── Preferences
 ├── Saved searches and presets
 ├── Watchlists
 └── Telegram identity (linked, never implicit)
```

## 8. Traveller profile

```
traveller_id
display_name
passport_country          ISO 3166-1 alpha-2, may be multiple
residence_country         modelled independently from nationality
home_airports             ordered, weighted
preferred_airports        ordered, weighted
preferred_airlines
preferred_alliances
excluded_airlines         hard exclusion
preferred_cabins
maximum_stops
maximum_trip_duration
```

Nationality and residence are separate fields because they answer different questions: the
travel-requirement engine (§85) needs the passport; some fare and residency rules need the
residence. Conflating them produces wrong visa answers for anyone living abroad.

A traveller may hold more than one passport. The requirement engine evaluates each and
reports the most favourable, naming which passport it assumed.

## 9. Companions

A companion is a second traveller whose points, status and passport can participate in an
evaluation. The relationship explicitly records how the companion's points may be used:

```
INDIVIDUALLY_USABLE     each balance redeems separately
TRANSFERABLE            points can move between the two accounts
SHAREABLE               the programme permits pooling or household accounts
NOT_COMBINABLE          balances cannot contribute to one redemption
```

**The system must never assume two people's balances can be combined into one redemption.**
Most programmes forbid it; some permit it under conditions; the default is `NOT_COMBINABLE`
until a curated rule says otherwise. Getting this wrong produces recommendations the user
cannot act on, which is worse than no recommendation.

## 10. Search profiles

Every search runs against an explicitly selected profile — `Primary`, `Primary + Companion`,
`Award Hunting`, and so on. The profile determines passenger count, passports, statuses,
available points, and all preference weights.

A result is never evaluated against an anonymous default traveller unless the user
deliberately selects that mode. "Best flight" is meaningless without naming the traveller it
is best for.

## 11. Itinerary hierarchy

```
Search
  └── Itinerary          one logical journey
        └── Slice        one directional leg (outbound, inbound, ...)
              └── Segment    one flight number
```

This shape supports one-way, return, open-jaw, multi-city and any number of stops without
special cases.

## 12. Segment

```
origin, destination              IATA
departure_local, arrival_local   with IANA timezone of the respective airport
departure_utc, arrival_utc       authoritative for all arithmetic
duration                         computed from UTC only
marketing_carrier, flight_number
operating_carrier                displayed prominently where it differs
aircraft
booking_class, cabin
```

**Time handling is a correctness requirement, not a formatting concern.** All instants are
stored as `timestamptz` in UTC. Local times are stored alongside the airport's IANA timezone
for display. Durations, connection times and sorting are computed exclusively from UTC.
Deriving a duration from two local times is wrong across any timezone change, which is to say
across most interesting flights.

Where an operating carrier differs from the marketing carrier, it is shown on the first
screen presenting the offer — a regulatory expectation in the EU and a contractual
requirement of several providers.

## 13. Cabins and fare families

Cabin and fare brand are independent dimensions.

```
Cabin:       Economy | Premium Economy | Business | First
Fare brand:  Economy Light, Economy Flex, Business Classic, ...
```

Comparing "Business" to "Business" without the brand compares a non-refundable
no-baggage-no-seat fare to a fully flexible one. Fare family data carries baggage, seat
selection, meal, change policy, refund policy and upgrade eligibility, so that total value is
comparable rather than just the cabin label.

## 14. Canonical flight model

Every provider normalizes into one shape. No provider's model is the canonical model —
including whichever provider happens to be the best source at any moment.

```
FlightOffer
    offer_id
    itinerary_id            fingerprint, see §15
    source                  which adapter produced it
    source_offer_id
    price_minor             integer minor units
    taxes_minor
    currency                ISO 4217
    validating_carrier
    cabin, fare_brand
    slices[]                → segments[]
    baggage
    changeability, refundability
    booking_link
    retrieved_at, expires_at
    freshness, confidence
```

**Money is always integer minor units plus an ISO-4217 code. Never a float.** Cross-currency
comparison uses a versioned FX rate table sourced from the European Central Bank, and the
rate's own date is recorded on every converted value — a converted price is itself a derived
fact and carries provenance like any other (P2).

## 15. Itinerary identity and deduplication

The same physical journey arrives from several sources at different prices. The interface
must present one itinerary with several observations, not several unrelated flights.

The canonical fingerprint is a hash of the ordered tuple, per segment:

```
(marketing_carrier, flight_number, departure_date_local, origin, destination)
```

Price, operating carrier, fare brand and booking class are deliberately excluded: they vary
between sources describing the same journey, which is precisely what deduplication must see
through.

Codeshares of one physical flight sold under different marketing numbers are a harder problem
and are **out of scope for now**. The operating carrier and its flight number are recorded on
every segment so that codeshare collapsing can be layered on later without re-collecting
data — a deliberate hook rather than an oversight.

## 16. Provider observations

Deduplication merges identity, never evidence.

```
Itinerary  (one)
   ├── Observation from source A: €1,742 at 10:31:02
   ├── Observation from source B: €1,748 at 10:31:14
   └── Observation from source C: €1,756 at 10:31:20
```

Preserving each observation enables source comparison, per-source accuracy tracking over
time, anomaly detection, and honest presentation when sources disagree (§48).

---

# PART III — SOURCES AND ACQUISITION

## 17. The zero-budget constraint

The project operates at zero recurring cost. This is a hard constraint, and it has a
consequence that must be stated plainly rather than discovered during implementation:

> **No usable official flight-search API is available at zero cost.**

As of August 2026: Skyscanner's Flights Live Prices API is partner-only behind a commercial
agreement; Amadeus decommissioned its Self-Service tier on 17 July 2026; Kiwi's Tequila is
invitation-only; Duffel is self-serve but prices both bookings and excess searches, and its
free tier returns synthetic data from a sandbox airline.

Version 1.0 of this document was built on the assumption that Skyscanner and Duffel would be
available. They are not. The architecture below is what remains achievable, and it is
achievable — but it rests on sources that are unofficial and therefore fragile. Everything in
this part follows from that.

## 18. Source classification

Every source declares its class. The class governs volume limits, expected reliability,
retention and how freshness is presented.

| Class | Meaning | Expected reliability |
|---|---|---|
| `OFFICIAL_API` | Documented, authorized, key-based | High; breaks with notice |
| `PUBLIC_DATA` | Open dataset with a licence | Very high; changes slowly |
| `UNOFFICIAL_ENDPOINT` | Undocumented JSON used by a vendor's own frontend | Moderate; breaks without notice |
| `SCRAPED` | HTML parsing, possibly requiring headless rendering | Low; breaks frequently |

**This supersedes version 1.0 §171**, which forbade scraping as a core dependency. That
position is incompatible with the zero-budget constraint, and pretending otherwise would have
left the specification describing a system that could not be built. Scraping is now a
first-class acquisition strategy, explicitly classified, with the reliability engineering
that entails (§21).

## 19. Ethical and practical limits

Two limits are absolute and not subject to configuration:

- **CAPTCHAs are never bypassed.** A source that gates on a CAPTCHA is out of scope.
- **Personal loyalty account logins are never automated.** Balances and status are entered
  manually, which §41 already treats as a first-class path. The risk of account lockout on
  the user's real accounts is not worth the convenience.

Beyond those, sources are accessed politely: conservative rates, honest identification,
caching over re-fetching, and a per-source record of terms of use (§22). Volume restraint is
not only ethical here — it is also what keeps a source working.

## 20. Planned sources

Detailed contracts for each are in `docs/providers.md`. Summary:

| Source | Class | Provides |
|---|---|---|
| Travelpayouts Data API | `OFFICIAL_API` | Cash prices, aggregated, 2–7 days old. Free token. |
| OurAirports | `PUBLIC_DATA` | Airports, IATA/ICAO, coordinates, timezones |
| OpenFlights | `PUBLIC_DATA` | Airlines, routes |
| European Central Bank | `PUBLIC_DATA` | Daily FX reference rates |
| ~~Airline open endpoints~~ | `UNOFFICIAL_ENDPOINT` | Rejected — no candidate carrier clears ToS/reachability (issue #2) |
| Google Flights | `UNOFFICIAL_ENDPOINT` | Broad cash coverage, closer to live |
| Amex Italy partners page | `SCRAPED` | Transfer ratios, minimums, increments, times |
| Wikipedia + Farnesina | `SCRAPED` | Visa and entry requirements by passport |
| ~~Award sources~~ | `SCRAPED` | Rejected — no qualifying source; manual entry only (issue #4) |

Travelpayouts returns cached rather than live prices. That is acceptable and even
well-matched to the primary purpose: building the historical record (P5) needs breadth and
consistency over time far more than it needs freshness measured in seconds.

## 21. Reliability engineering for fragile sources

Because most sources are `UNOFFICIAL_ENDPOINT` or `SCRAPED`, the following are **P0
requirements**, not later hardening:

1. **Contract tests against recorded fixtures.** Every adapter has fixtures; a shape change
   fails the test suite loudly rather than corrupting data quietly.
2. **Per-source health tracking.** Success rate, latency, last success, consecutive failures.
3. **Circuit breakers** (§25).
4. **Fail loud on unexpected shape.** An adapter that meets a payload it does not recognise
   raises. It never returns partially-normalized data. A missing field is `UNKNOWN`, never
   zero, never false, never an empty list.
5. **Raw payload retention** (§55), so parser fixes can reprocess history.

The system is already designed to express ignorance (P3, P4). That is what makes a
scraper-based architecture tolerable: a broken source degrades to `UNKNOWN` behind an open
circuit, and the interface says so. It does not degrade to a wrong number.

## 22. Source capability and terms record

Each source declares, in configuration:

```
class                        see §18
capabilities                 search_cash, search_award, refresh_price, baggage,
                             fare_brand, booking_link, aircraft, batch_query
rate_limits                  requests per interval, concurrency
terms_reference              link to the applicable terms
storage_permitted            whether observations may be retained
redisplay_permitted          whether values may be shown to the user
retention_override           per-source deviation from §55
expected_reliability         drives UI treatment and alert thresholds
```

The application reads capabilities at runtime and never assumes a source can do something.
`batch_query` matters disproportionately: a source that answers many routes in one call
collapses the search-space problem of §28 and is worth preferring even when its data is older.

## 23. The two-tier acquisition model

Sources divide by cost and freshness into two tiers with different roles:

```
DISCOVERY      cheap, cached, high volume, breadth
               Travelpayouts, and any batch-capable source
               drives search results, watchlists, and the historical record

VERIFICATION   fragile or rate-sensitive, live, low volume, on demand
               Google Flights, airline open endpoints, award scrapers
               runs only against an itinerary the user has already selected
```

The tier assignment is a property of each source, declared in configuration (§22), not a
property of the request. Under the zero-budget constraint the verification tier is composed
entirely of `UNOFFICIAL_ENDPOINT` and `SCRAPED` sources — which is precisely why they belong
there: restricting them to on-demand use against a single itinerary is what keeps their
request volume low enough to remain viable.

This resolves three problems at once. Rate limits are respected because high-volume work runs
against tolerant sources. Fragile sources are exercised rarely, so they are less likely to be
blocked and their breakage affects less. And the freshness shown in the interface becomes
structurally honest: discovery results genuinely are cached and are labelled `CACHED — 6h`,
while a verified itinerary genuinely is live and is labelled `LIVE — 12s`.

## 24. Rate limiting and concurrency

Concurrency is bounded by politeness toward each source, not by host capacity. Each source
has an independent limiter; a global ceiling prevents the sum from becoming aggressive.

Headless browser work is constrained further: it runs in an isolated container with a hard
memory cap, at concurrency 1–3, and **only from the scheduler — never on an HTTP request
path.** No user request ever waits for a browser to start.

## 25. Circuit breakers

```
HEALTHY  →  DEGRADED  →  OPEN  →  (cooldown)  →  HALF_OPEN  →  HEALTHY | OPEN
```

While a circuit is open the source is not contacted; everything depending on it reports
`UNKNOWN` with the reason. Other sources continue unaffected. Recovery is probed with a
single test request after cooldown.

## 26. Error classification

Every external failure is classified, because the classification determines both the retry
policy and what the user is told:

```
AUTHENTICATION | RATE_LIMIT | TIMEOUT | UPSTREAM_ERROR
BAD_REQUEST | SCHEMA_CHANGE | BLOCKED | NOT_AVAILABLE
```

`SCHEMA_CHANGE` and `BLOCKED` are the characteristic failures of unofficial sources and are
tracked separately: repeated `BLOCKED` means the access pattern is too aggressive and must be
reduced, not retried harder.

---

# PART IV — SEARCH ENGINE

## 27. Search query model

Structured, never natural language (P6):

```json
{
  "origins": ["MXP", "LIN", "FCO"],
  "destinations": ["NRT", "HND"],
  "date_start": "2026-10-01",
  "date_end": "2026-10-31",
  "min_nights": 3,
  "max_nights": 5,
  "cabins": ["business", "economy"],
  "max_stops": 1,
  "traveller_profile": "primary",
  "budget": { "calls": 200 }
}
```

Origins and destinations carry preference weights (MXP 100, LIN 90, FCO 65). Weights
influence ranking; they do not filter. Hard exclusion is a separate, explicit mechanism (§37).

## 28. Search-space expansion and the budget

The naive expansion is `origins × destinations × departure dates × trip lengths × cabins`.
For the query above that is roughly 2,200 combinations — far beyond any source's tolerance.
Version 1.0 acknowledged this in prose but specified no mechanism. This is that mechanism.

**The query budget is a first-class domain object.** Every search declares how many source
calls it may spend. The orchestrator:

1. expands the full logical search space;
2. collapses combinations answerable by a single batch call (§22);
3. scores each remaining task by **expected information gain** — a deterministic weighted sum,
   not an inference:

   ```
   gain =  w_novelty     × (1 if never observed, else 0)
         + w_staleness   × normalized_age_since_last_observation
         + w_preference  × origin_weight × destination_weight
         + w_proximity   × normalized_closeness_of_departure_date
   ```

   Weights are configured, and the whole function is pure and unit-testable. Never observed
   therefore outranks stale, which outranks recently observed, with user preference and date
   proximity breaking ties;
4. executes the highest-scoring tasks until the budget is exhausted;
5. marks everything unexecuted as `NOT_EXPLORED`.

Point 5 is the one that matters for correctness. **`NOT_EXPLORED` is not "no results".** A
combination the system chose not to spend budget on is unknown, and the interface says so
(P3). Reporting it as empty would make the cheapest search look like the most thorough one.

Persistent watches receive a recurring daily allocation and spend it across their space over
time, so coverage accumulates rather than repeating the same probes. Default allocation and
the resulting volume estimate: `docs/adr/0007-observation-volume-estimate.md`.

## 29. Search state machine

```
CREATED → QUEUED → RUNNING → PARTIAL → ENRICHING → EVALUATING → READY
                                                                  ↓
                                                          STALE → EXPIRED
```

Searches live in the backend. Closing the browser does not stop one. A search started from
Telegram and a search started from the web are the same object in the same state machine.

## 30. Progressive results

Results stream to the client via SSE as they arrive, per source. The optimised metric is
**time to first useful result**, not time until every source finishes. A slow or dead source
delays completeness, never the first result.

The work happens in `worker`; the SSE connection terminates in `api`. They are separate
containers, so progress must cross a boundary: **the worker publishes search events to a
Redis pub/sub channel keyed by search id, and `api` subscribes and relays them to connected
clients.** This is the one place Redis sits on a user-visible path — acceptable because its
loss degrades the stream to polling (`GET /searches/{id}`), which the client already
implements as its reconnection fallback. The search itself continues regardless, since its
state lives in PostgreSQL.

## 31. Completion semantics

A search is `READY` only when every configured source has completed, failed or timed out
**and the system knows which sources did not contribute**. The interface reports that
explicitly:

```
236 results
Travelpayouts    ok
Google Flights   ok
Award source     unavailable — circuit open
Airline direct   not explored — budget exhausted
```

## 32. The meaning of "all flights"

"All flights" means: all offers returned by the configured sources for the explored portion of
the requested search space, subject to their coverage, freshness, rate limits and technical
limitations. It cannot honestly mean every flight sold anywhere. The interface never implies
otherwise.

## 33. Persistent searches and watchlists

A search can be marked `WATCHED` and re-run on a schedule within its budget allocation.

Watch conditions:

```
price below absolute threshold
price drop of at least X, absolute or percentage
award becomes available
award below points threshold
price enters a favourable historical percentile
schedule change on a watched itinerary
```

Lifecycle: `ACTIVE → RUNNING → UPDATED → NOTIFIED → ACTIVE`, terminating at `STOPPED`,
`EXPIRED`, `BOOKED` or `DISMISSED`.

## 34. Change detection and thresholds

A material change creates an event (§35). Insignificant noise does not: a €3 fluctuation is
not an event. Thresholds are configurable, per watch, with sensible defaults, and are applied
both to event creation and to notification aggregation (§101).

## 35. Domain events

```
PriceChanged | PriceDropped | PriceReachedThreshold
AwardAppeared | AwardDisappeared | AwardPriceChanged
HistoricalOpportunityFound
ScheduleChanged
TravelRequirementChanged | TransferRuleChanged
SourceDegraded | SourceRecovered
WatchCompleted
```

Events are the integration point between the search engine and every notification channel.
Adding a channel means consuming events, never modifying the search engine.

## 36. Data quality gates

Every normalized itinerary must pass before persistence:

```
arrival after departure, in UTC
airports resolve against reference data
every airport has a resolved IANA timezone
carrier resolves against reference data
currency is valid ISO 4217
segment continuity: segment N destination = segment N+1 origin,
    unless an explicit airport change is represented
stop count matches segment count
connection times are non-negative and above a configured floor
```

The connection floor is a configured minimum, not a real minimum connection time: authoritative
MCT data is an airport-by-airport commercial dataset this project does not have. The gate
therefore rejects the impossible, and leaves the merely tight to the risk engine (§67), which
flags it rather than discarding it.

A failed gate is logged with the raw payload retained and the itinerary discarded. Bad data
never reaches history, because history is the one store where a bad write is effectively
permanent.

## 37. Hard filters versus preferences

```
Hard filters (eliminate)      Preferences (reorder)
Business only                 Prefer MXP over FCO
Maximum 1 stop                Prefer SkyTeam
No self-transfer              Prefer direct
Arrive before 18:00           Prefer morning departure
Visa obtainable in time       Prefer Air France
```

The distinction is presented explicitly in the interface. A user who sees zero results must
be able to tell which hard filter caused it, and the interface names the filter and how many
results it removed.

---

# PART V — PROVENANCE, FRESHNESS AND CONFIDENCE

## 38. Why this part exists

Parts III and IV acquire data of wildly varying trustworthiness: an open dataset updated
monthly, a cached price from last Tuesday, a scraped award result from a source that may be
silently broken. Presenting these identically would be the system's most consequential
failure. This part defines the metadata that keeps them distinguishable all the way to the
screen.

## 39. Provenance record

Every externally-sourced value carries:

```
value
source
source_reference        the specific offer, page or record
provenance              see §40
retrieved_at
effective_from, effective_until     for versioned rules
freshness               see §42
confidence              see §43
```

## 40. Provenance classes

```
AUTOMATIC     fetched by an adapter from a source
CURATED       versioned record seeded from repository files, admin-editable
USER_ENTERED  entered by a user through the web UI or Telegram
IMPORTED      bulk-loaded from a dataset
UNKNOWN       no value established
```

`CURATED` resolves what would otherwise be a contradiction between P1 and §19. Amex transfer
ratios must not be code constants, yet no Amex API exists and account automation is
forbidden. The resolution: the ratio is a versioned database record, seeded from a file under
version control, carrying `verified_at` and `review_due_at`. When it goes stale the system
raises a review task and messages the user with a link to the official page.

This satisfies the real intent of P1 — no magic constants, versioned, timestamped,
auditable — without pretending an API exists that does not. A scraper may keep a `CURATED`
record fresh automatically; if it breaks, the record does not become wrong, it becomes
overdue for review.

## 41. Manual entry is first-class

Loyalty balances, status and qualifying activity are entered by hand, and this is a designed
path rather than a fallback. Nothing downstream may behave differently based on how a value
was obtained. Every consumer sees a `LoyaltySnapshot` with provenance attached and treats it
uniformly.

The interface distinguishes the two clearly, because the user's trust should differ:

```
Flying Blue balance   42,000     Entered by you · 3 days ago
Flying Blue balance   42,000     Synchronized · 12 minutes ago
```

## 42. Freshness states

```
LIVE          retrieved seconds ago, on demand, from a live source
FRESH         within the value's configured freshness window
RECENT        beyond the window but comfortably usable
CACHED        deliberately served from cache; age shown
STALE         beyond usable age; shown with a warning
UNKNOWN       no value; the reason is carried alongside
CONFLICTING   sources disagree beyond tolerance (§48)
```

Freshness windows are per data type, configured, and are **refresh policies — not the values
themselves**:

```yaml
freshness:
  flight_price_live: 300      # seconds
  flight_price_cached: 604800
  award: 3600
  transfer_rule: 604800
  travel_requirement: 86400
  reference_data: 2592000
```

## 43. Confidence

Deterministic metadata, not an inferred score. Computed from source authority (§18 class),
freshness, corroboration across sources, and directness — whether the value was stated by the
source or derived by the system.

`HIGH | MEDIUM | LOW | NONE`.

Confidence propagates: a derived value is never more confident than its least confident
input. A cash-versus-award recommendation resting on a stale transfer ratio is itself low
confidence, and says so.

## 44. Data lineage

Any displayed value can be traced to what produced it: source, source reference, retrieval
time, normalization time, and the rule version applied if it was computed. The interface
exposes this on demand for every value in a result.

## 45. Absence versus unavailability

Restating P3 as a mechanical requirement because it is the easiest principle to violate by
accident:

```
AVAILABLE     the source stated a value
UNAVAILABLE   the source stated there is none
UNKNOWN       the source could not be consulted
```

Boolean `true`/`false` is forbidden for any externally-sourced fact, because a boolean cannot
represent the third state. This applies to award availability, seat counts, baggage
allowances, benefit entitlements and visa requirements alike.

## 46. Versioned rules

Every rule — status qualification, benefit entitlement, transfer ratio, visa requirement —
carries `version`, `effective_from`, `effective_until`, `source` and `retrieved_at`.

Historical evaluation uses the rule version **in effect at the relevant date**, not the
current one. Without this, reviewing last year's trip silently applies this year's rules and
the analysis becomes irreproducible.

## 47. Manual overrides

An administrator may override any value when a source is wrong or unavailable, supplying a
reason. Overrides are marked as such wherever displayed, carry an expiry, and are fully
audited (§111). An override that never expires is a code constant wearing a disguise, so
expiry is mandatory.

## 48. Conflicting sources

When two sources disagree beyond tolerance, the system does not silently choose. The value is
marked `CONFLICTING`, both observations are retained and shown with their provenance, and the
ranking engine uses the more conservative one. Persistent disagreement between two sources is
itself a signal, tracked as a source-quality metric.

---

# PART VI — ENRICHMENT

## 49. Loyalty model

```
loyalty_program        programme identity and its operator
loyalty_account        a traveller's membership
loyalty_status         tier, qualifying progress, validity period
loyalty_balance        point-in-time snapshot with provenance
loyalty_rule           versioned: qualification, earning, redemption
loyalty_benefit        versioned: what a tier entitles the holder to
alliance_membership    versioned: airline in alliance, with effective dates
```

Alliance membership is versioned data, not a constant. Airlines join and leave alliances, and
a historical evaluation must use the membership that applied at the time.

## 50. Transfer rules

```
source_program, target_program
source_points, target_points      the ratio, as two integers
minimum_transfer
increment
maximum_transfer                  where one applies
estimated_transfer_time
effective_from, effective_until
provenance, verified_at, review_due_at
```

The ratio is expressed as two integers, never a decimal, because 3:2 is exact and 0.667 is
not. Rounding errors on a points transfer are not acceptable: the user acts on this number.

## 51. Transfer calculation

Given a required award amount and current balances, the engine computes the necessary
transfer applying the **current rule**: ratio, minimum, increment, rounding, maximum, and the
user's actual balance. The rounding direction is always against the user — the system reports
the transfer that will certainly suffice, never one that might fall short by one increment.

The calculation is code; the ratio is data (P1). The engine never contains a ratio.

Where the transfer rule is `STALE`, the result carries that freshness through to the
interface, which warns before the user acts. A points transfer is irreversible, so this
warning is one of the highest-value pieces of provenance in the system.

## 52. Award model

```
AwardSearch       a query for award space
AwardOffer        programme, route, date, cabin, points, taxes, seats
AwardObservation  a timestamped record of an offer's state
```

Availability uses the three-state model of §45. Seat count matters and is preserved: one
available seat is not a feasible award for two travellers, and the interface distinguishes
"1 seat" from "2+ seats" rather than reducing both to "available".

## 53. Companion strategy evaluation

With multiple travellers selected, the engine evaluates the feasible strategies — primary
only, companion only, each transferring separately, pooling where the programme genuinely
permits it — subject to §9. Infeasible strategies are shown as infeasible with the reason,
not hidden, because knowing why a plan fails is useful.

## 54. Status benefits and qualification

From traveller, itinerary and status, the engine derives lounge access, baggage allowance,
priority services, earning, upgrade eligibility and seat selection — every one of them from a
versioned rule (§46), none from a constant.

It also projects status progress: current qualifying total, the contribution of the itinerary
under evaluation, the projected total, and whether it reaches the next tier.

---

# PART VII — HISTORICAL INTELLIGENCE

## 55. Storage tiers and retention

```
Raw payloads          compressed          retained 12 months
Normalized observations                   retained indefinitely
Daily aggregates      derived             retained indefinitely
```

The twelve-month raw window is the reprocessing window: a parser fix within a year can
re-normalize the affected history without contacting the source. Normalized observations and
aggregates are small and are the actual analytical asset, so they are kept permanently.

Observation and raw-payload tables use **declarative monthly partitioning by observation
date**. Retention is enforced by detaching and dropping whole partitions rather than by
`DELETE`: O(1), no table bloat, no vacuum pressure.

Partitions are created and dropped by a scheduled job in the worker, which maintains a
rolling window of future partitions. No PostgreSQL extension is required — `pg_partman` is
deliberately avoided to keep the database image stock. One consequence to respect: Alembic
manages the partitioned parent table and its indexes, while individual partitions are runtime
objects created by the job and are **not** represented in migrations.

## 56. Observation writes

```
fetch → normalize → quality gate → detect material change → write
```

An observation row represents a **period during which a value held**, not a single poll:

```
observation
    itinerary_id, source, cabin, fare_family
    price_minor, currency, availability
    first_seen_at, last_seen_at, poll_count
```

A material change — price, availability, cabin, fare, schedule, award points or award
availability — closes the current row and opens a new one. An identical repeat poll extends
`last_seen_at` and increments `poll_count` instead of writing a row.

This is not merely a space optimisation; it is required for percentile correctness. If every
poll wrote a row, a route polled hourly would contribute twenty-four times the statistical
weight of one polled daily, and the resulting percentiles would describe polling frequency
rather than the market.

## 57. Aggregates

```
flight_price_daily
    date, route, cabin, fare_family, source
    minimum, median, maximum, observation_count
```

Computed nightly from observations. A day is covered by every observation whose
`[first_seen_at, last_seen_at]` interval intersects it, so a price that held for a week
contributes to all seven days exactly once each — which is what "the price on that day" means.

Percentile queries read aggregates; detail queries read observations.

## 58. Historical evaluation

A current price is positioned against its own history: minimum, maximum, median, mean,
percentile, recent median and seasonal baseline.

## 59. Comparison scope

A comparison is meaningless without stating what it compares against. Every historical
statement names its scope: route, cabin, fare family, source, time window, day of week,
season. A Business fare is never compared against Economy; a scraped source's prices are not
pooled with a cached source's without noting it.

## 60. Historical confidence

Percentiles from thin data are misleading in a specific and dangerous way: with five
observations, "9th percentile" is arithmetically true and epistemically worthless.

Confidence derives from observation count, time span covered, and recency. It is displayed
alongside every historical claim, and below a floor the percentile is not shown at all — only
the raw range. Refusing to state a number is sometimes the most accurate available output
(P4).

## 61. Award history and redemption value

Award observations are historical in the same way, enabling statements like "45k has appeared
7 times, 55k has appeared 22 times" for a route and cabin.

Redemption value is `(cash equivalent − award taxes) / points required`, tracked over time.
The user configures personal thresholds for poor, acceptable, good and excellent value; these
are **personal configuration, not universal truths**, and the interface presents them as the
user's own thresholds.

## 62. Cash versus award recommendation

Combining cash percentile, award percentile, redemption value, transfer friction, balances,
status earning and the user's opportunity-cost settings, the engine recommends `USE POINTS`,
`PAY CASH` or `EITHER`, always with its reasoning and always with the confidence of its
weakest input (§43).

---

# PART VIII — TRAVEL REQUIREMENTS

## 63. Scope

Passport country, destination, transit countries, travel date, visa requirement and type,
visa on arrival, eVisa, ETA, registration, fee, processing time, passport validity rules and
special documentation.

## 64. Sources and their honest limits

IATA Timatic is the authoritative source and is an enterprise product not available to this
project. The system uses Wikipedia's structured visa-requirement tables cross-referenced
against the Italian Foreign Ministry's Viaggiare Sicuri.

This must be stated in the interface. The system provides **travel planning guidance, not
boarding compliance**. Where sources disagree, both are shown (§48). The user is directed to
the official source before travelling, and this disclaimer is not dismissible on any result
where a requirement affects feasibility.

## 65. Transit requirements

Transit rules frequently differ from destination rules, which is precisely what makes
one-stop itineraries risky in ways a price comparison cannot show. The engine evaluates the
passport against destination **and every transit point**, and a transit requirement can make
an otherwise cheaper itinerary infeasible.

## 66. Travel readiness

Per itinerary and traveller: `READY`, `ACTION_REQUIRED` (with the action, its cost, and its
processing time against the departure date), `NOT_READY`, or `UNKNOWN` when requirements
could not be verified — never silently `READY`.

## 67. Risk engine

Independent of documents, each itinerary is assessed on: stop count, connection duration,
airport change, terminal change, self-transfer, separate tickets, overnight connection,
minimum connection time at the airport, and schedule reliability. Output `LOW`, `MEDIUM` or
`HIGH` with the contributing factors named.

## 68. Self-transfer and positioning flights

Separate tickets are never rendered to look like one protected itinerary. Where an itinerary
combines tickets, the interface states it prominently, shows the connection buffer, and
explains that a missed connection is not the airline's responsibility. Positioning flights
are supported and marked with the same explicitness.

---

# PART IX — EVALUATION AND PRESENTATION

## 69. Ranking pipeline

```
Hard filters → Feasibility → Value → Preferences
    → Status benefits → Historical value → Risk → Ordering
```

Deterministic and pure. Given the same inputs it produces the same output, which makes it
fully unit-testable without a database or a network.

## 70. Score components

```
cash_value | award_value | comfort | directness
airline_preference | airport_preference | status_value
points_efficiency | historical_value | visa_ease | risk
```

Weights are user-configurable per search profile.

## 71. Score presentation

The additive computation determines ordering. **The numeric score is not presented as a
number.**

Version 1.0 displayed `SCORE 94`, which conflicts with P4: two significant figures over a
weighted sum of heterogeneous dimensions with user-configurable weights implies a precision
that does not exist. The difference between 94 and 92 is not meaningful, but the display
communicates that it is.

Instead:

```
EXCELLENT   Best overall for this profile

  + Exceptional historical price      9th percentile, high confidence
  + Strong award value                3.1 cents per point
  + Elite status benefits apply       Flying Blue Gold
  + Preferred airport                 MXP
  − Connection risk                   1h05 at CDG, below comfortable
```

Bands are `EXCELLENT | GOOD | FAIR | WEAK`. Rules:

- Scores are **never compared across different searches.** Weights and candidate sets differ,
  so the comparison is meaningless.
- A result whose **key inputs** are `UNKNOWN` or `STALE` is marked low confidence and cannot
  occupy the top band regardless of arithmetic. A key input is defined mechanically: the cash
  price, plus any component contributing more than 15% of the absolute score magnitude for
  that result. This is computed, not judged, so the rule is testable.
- Every result can explain both why it ranked where it did and what separates it from the one
  above.

## 72. Ranking modes

`Best Overall`, `Best Cash`, `Best Points`, `Best Award`, `Best Status`, `Best Comfort`,
`Best Historical Value`, `Lowest Risk`. Each is the same pipeline with a different weight
preset, not a different algorithm.

## 73. Interface philosophy

Dense, restrained, fast, readable. The reference is a high-quality financial dashboard, not a
marketing site. Information is never removed to look minimal — it is layered: summary row,
expandable detail, full source panel.

Every information category carries an icon, a label, a status and — where it applies —
freshness. The freshness indicator is not decoration; it is the mechanism by which P2 and P4
reach the user.

## 74. Result presentation

A result card shows itinerary, carriers, routing, stops, duration, cabin, cash price with
freshness, award with freshness, required transfer, applicable status benefits, travel
readiness, historical position with confidence, risk, and the band with its breakdown.

A detail panel adds: segments, fare rules, baggage, aircraft, full transfer calculation,
benefit derivation with rule versions, requirement detail per transit point, price and award
history charts, and the complete source matrix with timestamps.

## 75. Comparison and freshness views

Multiple itineraries compare side by side across every dimension. A dedicated freshness view
shows the age of each data category at a glance, communicating directly how much the current
result can be trusted.

## 76. Telegram interface

Optional but first-class, for notification and control. Long polling rather than webhooks, so
no inbound public HTTPS endpoint is required.

Telegram identity is never application identity. Linking is explicit: the web UI generates a
code, the user sends `/link <code>`, the backend associates the Telegram user ID. Commands
carry permission levels (`USER`, `ADMIN`). Interaction is driven by inline keyboards rather
than free text, consistent with P6.

Telegram and web operate on the same backend state. There is no separate Telegram store, and
a balance updated from Telegram is visible in the web UI immediately.

## 77. Notification aggregation

Four consecutive one-euro drops are one notification, not four. Notifications aggregate by
watch and by time window, reporting net change since the last notification. Thresholds and
quiet hours are configurable. A notification channel that cries wolf gets muted by the user,
at which point the entire watch system has failed.

---

# PART X — OPERATIONS

## 78. Security

Authentication, authorization and session management are required even on a trusted LAN;
personal balances and travel plans are not for anyone who reaches the network.

Sessions use httpOnly, `SameSite=Strict` cookies whose server-side state lives **in
PostgreSQL, not in Redis**. Redis is a cache and a queue; per §82 its loss must be
survivable, and putting sessions there would mean a Redis restart logs every user out. Only
PostgreSQL is a hard dependency, and session state is the one piece of "cache-shaped" data
that must respect that.

Passwords use Argon2id. No hand-rolled JWT scheme. External credentials come from environment
variables or Docker secrets, never from the database and never from an image.

## 79. Privacy and logging

The profile stores passport **country**, not passport number — the requirement engine needs
only the former. Logs never contain passwords, tokens, account numbers or personal data;
identifiers are masked. Logging is structured.

## 80. Monitoring

Host and container resources, database size and growth, queue depth, and per-source health:
success rate, latency, error classification breakdown, circuit state, last success. Source
health is the operationally interesting signal, because sources are the fragile part.

## 81. Backup

**Nightly `pg_dump` to a location outside the machine, with restore verified periodically.**

Version 1.0 did not mention backup at all. For a system whose entire value is an accumulated
historical record that cannot be re-fetched retroactively, an unverified backup is the most
likely route to total project loss. A backup that has never been restored is a hypothesis.

## 82. Graceful degradation

A source failure degrades that source's contribution to `UNKNOWN`; everything else continues.
A Telegram failure leaves the web application unaffected. Only PostgreSQL is a hard
dependency.

A Redis failure specifically: sessions survive (§78), stored searches and history remain
readable, and the SSE stream degrades to client polling (§30). What stops is job execution and
caching — new searches queue in PostgreSQL and run when Redis returns. The system becomes
read-only rather than unavailable, and says so.

## 83. Testing

Domain logic — date expansion, budget allocation, transfer calculation, percentiles, ranking,
deduplication, risk, requirement evaluation — is unit-tested and requires no database.
Adapters are tested against recorded fixtures. Contract tests detect upstream drift.
Integration tests cover orchestration, persistence and the SSE stream. Migrations are tested
forward and backward against a seeded database.

## 84. Audit

Recorded for balances, status, rules, preferences, watches, overrides and source
configuration: actor, action, timestamp, previous value, new value, reason.

---

# PART XI — ROADMAP

## 85. Sequencing rationale

Version 1.0 placed historical intelligence at phase 7, after search, loyalty, awards and
travel requirements. That ordering is a mistake worth naming explicitly, because it is
tempting and expensive.

Every other capability works the day it is finished. **History does not: it requires calendar
time to accumulate.** A collection pipeline reaching production in month seven leaves
percentiles unusable until month ten. The same pipeline in month one — crude, one source,
few routes — means the evaluation engine has months of real data on the day it is written.
The cost of moving it early is close to zero; the cost of leaving it late is paid in months.

Collection is therefore separated from evaluation, and collection comes early.

## 86. Milestones

Each maps to one GitHub milestone.

**M0 — Foundations.** Docker Compose for development and production, CI, PostgreSQL with
Alembic, FastAPI skeleton, Vite SPA skeleton, authentication, users, traveller profiles.
Reference data ingestion: OurAirports, OpenFlights, ECB rates.

**M1 — Walking skeleton.** One source, one route, end to end: search, normalize, quality
gate, persist observation, display. Deliberately thin, no optimization. Its purpose is to run
real data through every layer and prove the boundaries hold.

**M2 — Collection.** Scheduler, raw payload retention, partitioning, daily aggregates,
per-source health and circuit breakers. **The historical clock starts here.**

**M3 — Search engine.** Multi-origin, multi-destination, flexible dates, trip length ranges,
query budget, deduplication, progressive results over SSE, hard filters.

**M4 — Historical intelligence.** Percentiles, comparison scope, confidence floors,
assessments. Operating on real accumulated data.

**M5 — Loyalty.** Programmes, accounts, manual balances and status, curated transfer rules,
transfer calculation, status benefits and qualification projection.

**M6 — Awards.** Award adapters, award observations, award history, cash-versus-award
evaluation, reverse search from a points balance.

**M7 — Travel requirements.** Requirement engine, transit evaluation, readiness, world map.

**M8 — Watchlists and Telegram.** Persistent searches, watch conditions, event pipeline,
notification aggregation, Telegram linking, commands and inline keyboards.

**M9 — Ranking and interface.** Full score components, bands and explanations, comparison
view, freshness view, charts, refinement.

## 87. What is deliberately not built

Microservices, Kafka, Elasticsearch, Kubernetes, a data warehouse, cloud deployment, an AI
assistant, automated booking, hotels, and any non-flight travel product.

Each adds complexity out of proportion to its value here, and several would actively harm the
design.

---

# PART XII — DOCUMENT HISTORY

## 88. Changes from version 1.0

| Area | v1.0 | v2.0 | Rationale |
|---|---|---|---|
| Providers | Skyscanner, Duffel, Timatic assumed available | None are obtainable at zero cost; source classification introduced | §17, §18 |
| Scraping | Forbidden as core dependency (old §171) | First-class, classified, with reliability requirements | §18, §21 |
| Host | Raspberry Pi with tight resource limits | Ordinary machine, fully containerized, multi-arch | §6 |
| Resource model | Recompute rather than store | Store aggressively; sources are the scarce resource | §4 |
| Raw payloads | Temporary, optional, short-lived | Retained 12 months as a reprocessing window | §55 |
| Frontend | Next.js | Vite + React SPA, static | ADR 0004 |
| Score | `SCORE 94` | Bands plus breakdown; ordering preserved | §71 |
| History | Phase 7 | Collection at M2, evaluation at M4 | §85 |
| Budget | Search-space explosion acknowledged only in prose | Query budget as a domain object, `NOT_EXPLORED` state | §28 |
| Time and money | Unspecified | UTC `timestamptz` plus IANA zones; integer minor units | §12, §14 |
| Deduplication | Undefined | Explicit segment fingerprint | §15 |
| Backup | Absent | Nightly verified dump, mandatory | §81 |
| Naming | "Personal Flight Intelligence Platform" | LocalhostAirlines | — |

## 89. Open questions

Carried deliberately, to be resolved by time-boxed `type:spike` issues:

1. ~~Which airlines expose usable unprotected endpoints, and with what coverage.~~ Resolved:
   neither candidate qualifies. Ryanair's terms of use explicitly prohibit automated
   extraction, including via API, with real enforcement history; Wizz Air's site blocks
   standard automated access at the edge before reachability could even be assessed. No
   adapter is built in this category (`docs/providers.md` "Airline open endpoints", issue #2).
2. Whether Google Flights access is stable enough at low volume to be worth its maintenance.
3. ~~Which award sources are reachable without account automation, and at what quality.~~
   Resolved: none qualify. Guest-accessible airline award search either carries an explicit
   scraping prohibition with real enforcement history (American Airlines, matching Ryanair's
   pattern in item 1) or has been actively closed specifically to block aggregators (United,
   Air Canada) — an industry-wide posture, not a gap expected to reverse. The award engine is
   built regardless, operating on manually entered observations (`docs/providers.md` "Award
   availability", issue #4).
4. ~~Whether Wikipedia's visa tables are structured consistently enough for reliable parsing
   across all destinations, or only for a subset.~~ Resolved: yes, one generic parser
   suffices — table shape is consistent across sampled major, mid-size and micro-state
   passport pages; what varies is cell completeness, already handled by the existing
   `UNKNOWN`-over-guess rule (`docs/providers.md` "Visa requirements" § Parsing, issue #5).
5. ~~Realistic observation volume per day, and therefore actual storage growth.~~ Resolved by
   calculation: `docs/adr/0007-observation-volume-estimate.md` (issue #6). Flagged there for
   re-verification against live Travelpayouts traffic once issue #22 has run for a week —
   that follow-up does not reopen this question, since it revisits an accepted estimate rather
   than an unanswered one.
