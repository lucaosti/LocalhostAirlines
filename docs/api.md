# System API

Companion to `specifications.md`. This document defines the contract between the backend and
its clients — the web SPA, the Telegram bot, and anything added later.

The specification defines the domain. This document defines how that domain is exposed over
HTTP. Where the two appear to disagree, the specification wins and this document is wrong.

**Status:** design. Nothing below is implemented. Endpoints are introduced by the milestone
that needs them (`spec §86`); the milestone is noted on each resource group.

---

## 1. Conventions

| | |
|---|---|
| Base path | `/api/v1` |
| Transport | HTTPS behind Caddy on the LAN |
| Encoding | JSON, UTF-8 |
| Instants | RFC 3339, always UTC, always `Z`-suffixed |
| Dates | `YYYY-MM-DD`, calendar dates with no timezone |
| Money | integer minor units plus ISO-4217 code, never a decimal |
| Durations | integer seconds |
| Identifiers | opaque strings; clients never parse them |
| Naming | `snake_case` fields, plural resource collections |

Versioning is in the path. A breaking change means `/api/v2`; additive fields are not
breaking, and clients must ignore unknown fields.

### Why money is never a JSON number

```json
{ "amount_minor": 74200, "currency": "EUR" }   // €742.00
```

IEEE-754 doubles cannot represent monetary decimals exactly, and JSON numbers are doubles in
most parsers. This shape is used everywhere without exception, including inside nested
history and aggregate structures.

---

## 2. Authentication

Session-based, using an httpOnly, `SameSite=Strict`, secure cookie backed by Redis. No
bearer tokens, no client-side token storage, no hand-rolled JWT (`spec §78`).

```http
POST /api/v1/auth/login       { "username": ..., "password": ... }  → Set-Cookie
POST /api/v1/auth/logout
GET  /api/v1/auth/session     → current user and permissions
```

Passwords are hashed with Argon2id. Failed attempts are rate-limited per account and per
source address.

The Telegram bot authenticates as the linked user's session, never as an anonymous caller.
Linking is explicit (`spec §76`):

```http
POST /api/v1/telegram/link            → { "code": "ABC123", "expires_at": ... }
GET  /api/v1/telegram/link/status
DELETE /api/v1/telegram/link
```

---

## 3. The provenance envelope

**The single most important convention in this API.**

The specification requires that every externally-sourced value carry its provenance all the
way to the interface (P2), that ignorance be distinguishable from absence (P3), and that
uncertainty be explicit (P4). None of that survives if the API returns bare values.

Therefore any field whose value originated outside the system is wrapped:

```json
{
  "value": { "amount_minor": 74200, "currency": "EUR" },
  "state": "AVAILABLE",
  "freshness": "CACHED",
  "confidence": "MEDIUM",
  "source": "travelpayouts",
  "source_reference": "tp:MXP-NRT:2026-10-18",
  "retrieved_at": "2026-08-13T10:31:20Z",
  "age_seconds": 21600
}
```

`state` is the three-state model of `spec §45` and governs how `value` must be read:

| `state` | `value` | Meaning |
|---|---|---|
| `AVAILABLE` | present | The source stated this |
| `UNAVAILABLE` | `null` | The source stated there is none |
| `UNKNOWN` | `null` | The source could not be consulted — `reason` explains |
| `CONFLICTING` | best estimate | Sources disagree; `alternatives[]` carries the others |

When `state` is `UNKNOWN`, a `reason` field carries the error classification (`spec §26`) and,
where relevant, the circuit state:

```json
{
  "value": null,
  "state": "UNKNOWN",
  "reason": { "code": "BLOCKED", "source": "google_flights", "circuit": "OPEN" }
}
```

**Clients must never render `null` as zero, absent, or "none".** A `Valued<T>` type in the SPA
enforces this at compile time: the value is unreachable without narrowing on `state`, which
makes the distinction impossible to lose by accident rather than merely discouraged.

`freshness` and `confidence` take the values defined in `spec §42` and `§43`.

---

## 4. Errors

RFC 9457 problem details, `Content-Type: application/problem+json`:

```json
{
  "type": "https://localhostairlines.local/problems/budget-exhausted",
  "title": "Search budget exhausted",
  "status": 409,
  "detail": "Budget of 200 calls spent; 1,847 of 2,200 combinations unexplored.",
  "instance": "/api/v1/searches/srch_01J8X",
  "unexplored_count": 1847
}
```

| Status | Used for |
|---|---|
| `400` | Malformed request |
| `401` | No valid session |
| `403` | Authenticated but not permitted |
| `404` | No such resource |
| `409` | Valid request, conflicting state |
| `422` | Well-formed but semantically invalid — unknown airport, `date_end` before `date_start` |
| `429` | Client rate limit |
| `503` | A hard dependency is unavailable |

**A failing external source is not an API error.** Source failure is a domain outcome and is
reported inside the response as `UNKNOWN` state on affected fields, with the search still
returning `200`. A `503` means PostgreSQL is unreachable — nothing else (`spec §82`).

---

## 5. Searches

**Milestone M1, extended through M3.**

### Create

```http
POST /api/v1/searches
```

```json
{
  "traveller_profile_id": "prof_01J8X",
  "origins":      [{ "code": "MXP", "weight": 100 }, { "code": "LIN", "weight": 90 }],
  "destinations": [{ "code": "NRT" }, { "code": "HND" }],
  "date_start": "2026-10-01",
  "date_end":   "2026-10-31",
  "min_nights": 3,
  "max_nights": 5,
  "cabins": ["business"],
  "max_stops": 1,
  "hard_filters": { "no_self_transfer": true, "arrive_before_local": "18:00" },
  "budget": { "calls": 200 }
}
```

`202 Accepted` with the search resource. Work is asynchronous from the start; there is no
synchronous search endpoint, because a synchronous one would either lie about completeness or
block for minutes.

Omitting `budget` applies the profile default. Weights influence ranking, never filtering
(`spec §27`).

### Retrieve

```http
GET /api/v1/searches/{id}
```

```json
{
  "id": "srch_01J8X",
  "state": "PARTIAL",
  "created_at": "2026-08-13T10:31:02Z",
  "space": { "total": 2200, "explored": 353, "not_explored": 1847 },
  "budget": { "calls": 200, "spent": 200, "remaining": 0 },
  "sources": [
    { "source": "travelpayouts",  "state": "COMPLETED",   "results": 187 },
    { "source": "google_flights", "state": "RUNNING",     "results": 41 },
    { "source": "award_scraper",  "state": "UNAVAILABLE",
      "reason": { "code": "BLOCKED", "circuit": "OPEN" } }
  ],
  "result_count": 228
}
```

`space` and `sources` together implement `spec §31` and `§32`. A client can always tell what
was searched, what was not, and which sources contributed. **`not_explored` must be surfaced
in the interface** — it is not diagnostic detail. Without it a cheap search looks as thorough
as an exhaustive one.

### Results

```http
GET /api/v1/searches/{id}/results
    ?mode=best_overall&limit=50&cursor=...
    &cabin=business&max_stops=1&historical_percentile_max=20
```

Cursor-paginated. `mode` selects a ranking preset (`spec §72`). Filters applied here are
post-search refinements over retrieved results; they do not trigger new source calls.

### Other operations

```http
POST   /api/v1/searches/{id}/refresh      re-run within a fresh budget allocation
DELETE /api/v1/searches/{id}              cancel; in-flight work is abandoned
GET    /api/v1/searches                   the user's searches, filterable by state
```

---

## 6. Progressive results over SSE

**Milestone M3.**

```http
GET /api/v1/searches/{id}/stream
Accept: text/event-stream
```

Results stream as they arrive, per source, so the client can render before the search is
complete (`spec §30`). SSE rather than WebSockets: the flow is one-directional and SSE
reconnects on its own.

```
event: state
data: {"state":"RUNNING"}

event: results
data: {"source":"travelpayouts","added":37,"total":37}

event: source
data: {"source":"award_scraper","state":"UNAVAILABLE",
       "reason":{"code":"BLOCKED","circuit":"OPEN"}}

event: progress
data: {"explored":353,"total":2200,"budget_remaining":0}

event: state
data: {"state":"READY","result_count":228,"not_explored":1847}
```

| Event | Meaning |
|---|---|
| `state` | Search state transition (`spec §29`) |
| `results` | New results available; client refetches the results page |
| `source` | A source completed, failed or had its circuit open |
| `progress` | Space and budget counters |
| `error` | Fatal to the search only |

`results` deliberately carries counts rather than payloads. Result objects are large, the
client already paginates and caches them through TanStack Query, and duplicating them into
the stream would mean two divergent representations of the same data.

Streams carry a heartbeat comment every 15 seconds. Reconnection uses `Last-Event-ID`;
events are retained server-side briefly to make replay possible.

---

## 7. Results and itineraries

**Milestone M1, extended through M9.**

```json
{
  "itinerary_id": "itin_8f3a…",
  "fingerprint": "8f3a2b…",
  "slices": [ { "segments": [ {
    "origin": "MXP", "destination": "CDG",
    "departure_local": "2026-10-18T10:20:00", "departure_timezone": "Europe/Rome",
    "departure_utc":   "2026-10-18T08:20:00Z",
    "arrival_local":   "2026-10-18T12:05:00", "arrival_timezone":  "Europe/Paris",
    "arrival_utc":     "2026-10-18T10:05:00Z",
    "duration_seconds": 6300,
    "marketing_carrier": "AF", "flight_number": "1233",
    "operating_carrier": "AF",
    "aircraft": "A220-300", "cabin": "business", "booking_class": "J"
  } ] } ],

  "observations": [
    { "source": "travelpayouts", "price": { … envelope … }, "booking_link": null },
    { "source": "google_flights", "price": { … envelope … }, "booking_link": "https://…" }
  ],

  "enrichment": {
    "award":       { … envelope … },
    "transfer":    { … envelope … },
    "status":      { … envelope … },
    "requirements":{ … envelope … },
    "history":     { … envelope … },
    "risk":        { "level": "LOW", "factors": [] }
  },

  "evaluation": {
    "band": "EXCELLENT",
    "rank": 1,
    "confidence": "MEDIUM",
    "breakdown": [
      { "component": "historical_value",  "direction": "positive",
        "label": "Exceptional historical price", "detail": "9th percentile, high confidence" },
      { "component": "risk", "direction": "negative",
        "label": "Connection risk", "detail": "1h05 at CDG, below comfortable" }
    ]
  }
}
```

Three structural points, each enforcing a specification rule:

**Both local and UTC times are always sent.** UTC is authoritative for arithmetic and
ordering; local plus its IANA zone is for display. Clients never convert between them
(`spec §12`).

**`observations` is an array.** Deduplication merges identity, never evidence, so every
source's price is preserved and comparable (`spec §16`).

**`evaluation` carries no numeric score.** A band, a rank and a breakdown — `spec §71`. The
underlying number exists server-side and determines `rank`; it is not exposed, because
exposing it invites exactly the false-precision comparison the specification prohibits.

### Verification

```http
POST /api/v1/itineraries/{id}/verify
```

Runs the verification tier (`spec §23`) against live sources for this one itinerary: price
refresh, award refresh, transfer rule refresh, requirement refresh — each where supported.

The response reports each check with its outcome and freshness. It **never asserts that a
price is guaranteed**; the field is `latest_verified`, and the interface wording follows it.
Even a just-refreshed offer can disappear before booking, and claiming otherwise would be the
one place this system actively misleads.

---

## 8. Travellers and profiles

**Milestone M0.**

```http
GET    /api/v1/travellers
POST   /api/v1/travellers
GET    /api/v1/travellers/{id}
PATCH  /api/v1/travellers/{id}
DELETE /api/v1/travellers/{id}

GET    /api/v1/travellers/{id}/companions
POST   /api/v1/travellers/{id}/companions     { companion_id, points_relationship }

GET    /api/v1/search-profiles
POST   /api/v1/search-profiles
```

`points_relationship` takes the values of `spec §9` and defaults to `NOT_COMBINABLE`. The API
requires it explicitly on creation — there is no way to create a companion relationship
without stating how points may be used, because the safe default must be a decision rather
than an accident.

---

## 9. Loyalty

**Milestone M5.**

```http
GET  /api/v1/loyalty/programs
GET  /api/v1/loyalty/accounts
POST /api/v1/loyalty/accounts
PUT  /api/v1/loyalty/accounts/{id}/balance   { "points": 42000, "as_of": "2026-08-13" }
PUT  /api/v1/loyalty/accounts/{id}/status    { "tier": "GOLD", "qualifying": 142 }
GET  /api/v1/loyalty/accounts/{id}/history
```

Balance and status writes record `USER_ENTERED` provenance with the actor and channel — web
or Telegram (`spec §41`). Every write is audited (`spec §84`) and previous values are retained,
so a balance history exists without extra bookkeeping.

### Transfers

```http
GET  /api/v1/transfers/rules?source=amex_mr
POST /api/v1/transfers/calculate
```

```json
{
  "source_program": "amex_mr",
  "target_program": "flying_blue",
  "target_points_required": 55000,
  "current_source_balance": 184230,
  "current_target_balance": 0
}
```

```json
{
  "feasible": true,
  "source_points_required": 82500,
  "rule": {
    "ratio": { "source": 3, "target": 2 },
    "minimum": 1000, "increment": 1000,
    "estimated_transfer_time": "1-2 business days",
    "provenance": "CURATED", "verified_at": "2026-08-11T09:14:00Z",
    "freshness": "RECENT", "confidence": "HIGH"
  },
  "warnings": []
}
```

The ratio is two integers, never a decimal (`spec §50`). Rounding is always against the user.
When the rule's freshness is `STALE`, `warnings` carries an explicit entry and the interface
must show it before the user acts — a points transfer is irreversible, which makes this the
highest-stakes provenance in the system (`spec §51`).

---

## 10. Awards, requirements and history

**Milestones M6, M7, M4.**

```http
GET  /api/v1/awards/search?origin=MXP&destination=NRT&date=2026-10-18&cabin=business
POST /api/v1/awards/observations          manually recorded award sighting
GET  /api/v1/awards/history?route=MXP-NRT&cabin=business&program=flying_blue

GET  /api/v1/requirements
     ?passport=IT&destination=JP&transit=SG&date=2026-10-18

GET  /api/v1/history/routes/{route}?cabin=business&window=90d
GET  /api/v1/history/itineraries/{id}
```

Award seat counts distinguish `1` from `2+` explicitly rather than reducing both to
"available" (`spec §52`), since one seat is not a feasible award for two travellers.

`POST /awards/observations` exists because manual award entry is a first-class path while no
automated source qualifies (`docs/providers.md`). Manually entered observations enter history
with `USER_ENTERED` provenance and are statistically indistinguishable from automated ones
except by that field.

History responses always carry their comparison scope and confidence (`spec §59`, `§60`).
Below the confidence floor the percentile is **omitted entirely** rather than sent with a
caveat — an absent field cannot be rendered misleadingly, whereas a caveated one can:

```json
{
  "current": { "amount_minor": 74200, "currency": "EUR" },
  "scope": { "route": "MXP-NRT", "cabin": "business", "window_days": 90, "sources": ["travelpayouts"] },
  "observations": 5,
  "confidence": "LOW",
  "range": { "min_minor": 71100, "max_minor": 124000 },
  "percentile": null,
  "percentile_omitted_reason": "INSUFFICIENT_OBSERVATIONS"
}
```

---

## 11. Watchlists and notifications

**Milestone M8.**

```http
GET    /api/v1/watchlists
POST   /api/v1/watchlists
PATCH  /api/v1/watchlists/{id}
DELETE /api/v1/watchlists/{id}

GET    /api/v1/notifications?unread=true
POST   /api/v1/notifications/{id}/dismiss
```

A watchlist wraps a search definition with conditions and a recurring daily budget allocation
(`spec §33`):

```json
{
  "search": { … search definition … },
  "conditions": [
    { "type": "price_below",            "amount_minor": 90000, "currency": "EUR" },
    { "type": "price_drop_percent",     "value": 10 },
    { "type": "award_available",        "program": "flying_blue", "max_points": 55000 },
    { "type": "historical_percentile_below", "value": 15 }
  ],
  "daily_budget": { "calls": 50 },
  "until": "2026-10-31",
  "quiet_hours": { "from": "22:00", "to": "08:00", "timezone": "Europe/Rome" }
}
```

---

## 12. Administration

**Milestone M2 onward. Requires `ADMIN`.**

```http
GET  /api/v1/admin/sources                    health, circuit state, limits, last success
POST /api/v1/admin/sources/{id}/enable
POST /api/v1/admin/sources/{id}/disable
POST /api/v1/admin/sources/{id}/circuit/reset

GET  /api/v1/admin/curated/{type}             transfer rules, benefits, alliances
PUT  /api/v1/admin/curated/{type}/{id}        creates a new version, never overwrites
GET  /api/v1/admin/curated/review-due         records past review_due_at

POST /api/v1/admin/overrides                  requires reason and expiry
GET  /api/v1/admin/audit
GET  /api/v1/admin/health                     containers, database size, queue depth
```

`PUT` on a curated record creates a new version with effective dates; it never mutates the
existing one, so historical evaluations stay reproducible (`spec §46`). Overrides require both
a reason and an expiry — an override without expiry is a code constant in disguise
(`spec §47`).

---

## 13. Rules for clients

1. **Never render a wrapped value without narrowing on `state`.** The SPA's `Valued<T>` type
   makes this a compile error rather than a convention.
2. **Never treat `null` as zero, false or empty.**
3. **Always surface freshness** where the specification requires it — prices, awards, transfer
   rules, requirements.
4. **Always surface `not_explored`.** Suppressing it makes an incomplete search look complete.
5. **Never compare evaluation bands across searches.** Different weights, different candidate
   sets, no shared meaning.
6. **Never cache a `LIVE` value as if it were fresh.** TanStack Query staleness must be
   configured from the value's own freshness window, not a global default.

Rules 1 through 4 exist because they are the points where an ordinary, reasonable client
implementation would silently violate the specification's core principles. They are enforced
in types and in review, not left to discipline.
