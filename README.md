# LocalhostAirlines

Self-hosted flight search that knows who you are.

Ordinary flight search answers "which flight is cheapest". This answers a different question:

> Which flight is the best option **for this traveller**, given cash price, award
> availability, transferable points, elite status, baggage, airport preferences, visa
> requirements, and — the part nobody else does — where today's price sits in that route's
> own history?

Runs on one machine on your LAN. No cloud, no subscriptions, no AI.

---

## Status

**M0 (foundations) in progress.** Docker Compose, CI, the database schema, and the API and SPA
skeletons run for real. Domain features (search, loyalty, awards, travel requirements) start at
M1 and don't exist yet — see [Roadmap](#roadmap).

This README describes commands that work today unless a section says otherwise.

---

## The idea

Three things make this different from a metasearch site:

**It remembers.** Every price and award observation is kept. When a fare shows €742, the
system can say whether that is the 9th percentile of what this route has done, or the 70th.
A price without its distribution is not information.

**It knows your position.** Your points balances, your elite status, your passport, your
companion's balances and status, your airport preferences. A €742 fare that earns you the
status you're chasing, from your preferred airport, redeemable with points you actually hold,
is not the same offer as a €742 fare that does none of that.

**It says when it doesn't know.** Every value carries its source, its age and its confidence.
"No award seats available" and "we couldn't check award seats" are shown as different
answers, because they are different answers. This matters more than it sounds — see
[Honest limitations](#honest-limitations).

What it does *not* do: hotels, cars, trains, packages, trip planning, chat. Flights only, on
purpose. A schema that anticipates hotels is worse at flights.

---

## Honest limitations

Read this before deciding whether the project is for you.

**There is no free flight API worth having.** As of August 2026, Skyscanner is partner-only,
Amadeus shut down its self-service tier in July 2026, Kiwi is invitation-only, and Duffel
charges per search and per booking. IATA Timatic, the authoritative source for entry
requirements, is enterprise-only.

The project runs at zero recurring cost, so it uses what remains: one genuinely free API
(Travelpayouts, whose data is cached 2–7 days old), open datasets, undocumented endpoints that
airline frontends use, and scraping. That has consequences worth stating plainly:

- **Cash prices in search results are not live.** They are cached and labelled as such, with
  their real age. Live verification runs on demand, against one itinerary you've selected, and
  only from the fragile sources — which is what keeps those sources working.
- **Sources break.** Undocumented endpoints and scrapers fail without warning. The system is
  built to notice, open a circuit, and report `UNKNOWN` rather than guess. The design assumes
  breakage instead of hoping against it.
- **Entry requirements are travel guidance, not boarding compliance.** Without Timatic, the
  system cross-references Wikipedia and the Italian foreign ministry. Check the official source
  before you fly. The interface says so and won't let you dismiss it.
- **Loyalty balances are entered by hand.** Automating logins into your real airline accounts
  risks locking you out of them. Not worth it.
- **CAPTCHAs are never bypassed.** A source that gates on one is out of scope.

If your budget isn't zero, roughly €9/month for seats.aero plus occasional Duffel search costs
would turn the two weakest areas — live cash verification and award availability — into the
strongest. Both are ordinary adapters behind capability flags; adopting them needs no
architectural change. See [`docs/providers.md`](docs/providers.md).

---

## How it works

Five layers, enforced as module boundaries rather than drawn as a diagram:

```
DISCOVERY       talks to sources. Knows HTTP, HTML, rate limits.
                Knows nothing about loyalty or ranking.
      ↓
NORMALIZATION   the only layer aware of any source's payload shape.
      ↓
ENRICHMENT      attaches loyalty, awards, visa requirements, history.
                Performs no I/O against sources.
      ↓
EVALUATION      hard filters, scoring, ordering. Pure functions,
                no I/O at all — so it is exhaustively testable.
      ↓
PRESENTATION    REST + SSE, and the Telegram bot.
```

Dependencies point one way only. Adapters never import domain rules; domain rules never import
adapters. That is what lets a source be swapped or lost without cascading changes — which,
given the sources available, is not a hypothetical.

Two design choices carry most of the weight:

**Raw payloads are kept for 12 months.** When a scraper's parser breaks — and they do — the
fix can reprocess history without re-contacting the source. Sources can't be queried about the
past, so without this every parsing bug is permanent data loss.

**Every search has a call budget.** Three origins × four destinations × a month of dates ×
three trip lengths is ~2,200 queries, which no source tolerates. The orchestrator ranks
candidate queries by how much new information each would produce, spends the budget on the best
ones, and marks the rest `NOT_EXPLORED` — never as "no results". A cheap search must not look
as thorough as an exhaustive one.

---

## Stack

| | |
|---|---|
| Frontend | Vite + React + TypeScript, static SPA, TanStack Query + Router |
| Backend | Python 3.13, FastAPI, REST + SSE |
| Jobs | ARQ (asyncio, Redis-backed, built-in cron) |
| Scraping | Playwright/Chromium in an isolated worker, hard memory cap |
| Database | PostgreSQL 17, monthly partitioning for observations |
| Cache / queue | Redis 7 |
| Proxy | Caddy, also serves the frontend build |
| Deployment | Docker Compose, multi-arch images |

Six containers: `caddy`, `api`, `worker`, `scraper`, `postgres`, `redis`.

**Nothing is installed on the host.** No Python, no Node, no package manager. `make up` runs
production; `make dev` layers on hot reload and hands you the same six services plus a
Vite dev server. Images build for `linux/amd64` and `linux/arm64`, so the same images run on an
Apple Silicon laptop and an x86 server — verified, not assumed: Chromium included.

Only PostgreSQL is a hard dependency. Lose Redis and the system goes read-only rather than
down: sessions survive, history stays readable, jobs queue until it returns.

---

## Requirements

- Docker and Docker Compose
- 8 GB RAM (16 GB comfortable — Chromium is the hungry part)
- SSD with room to grow
- A free [Travelpayouts](https://travelpayouts.com) token
- Optional: a Telegram bot token, for alerts and remote control

---

## Running it

```bash
git clone https://github.com/lucaosti/LocalhostAirlines.git
cd LocalhostAirlines
cp .env.example .env
```

Fill in `.env` — at minimum `POSTGRES_PASSWORD`, `SECRET_KEY` and `TRAVELPAYOUTS_TOKEN`. Then:

```bash
make up
```

The interface is on `http://localhost` — or wherever you point Caddy on your LAN. The `api`
container migrates the database on its own startup before serving traffic.

Development, with hot reload for both API and frontend:

```bash
make dev
```

This loads `docker-compose.dev.yml` on top of the base file and adds the Vite dev server
(`http://localhost:5173`) alongside the six core services. It's a separate file rather than
the Compose-auto-merged `docker-compose.override.yml` on purpose: that convention would make a
bare `make up` on a production host silently run in dev mode too. See the file's header for the
full reasoning.

Back up nightly. The accumulated history is the whole point of the project and cannot be
re-fetched retroactively:

```bash
BACKUP_TARGET=/path/to/backups make backup
```

Restore it somewhere at least once. A backup you've never restored is a hypothesis.

---

## Documentation

| File | Contents |
|---|---|
| [`specifications.md`](specifications.md) | The compass. Domain model, architecture, rules, and the reasoning behind them |
| [`docs/providers.md`](docs/providers.md) | Every external source: access, limits, capabilities, how each one fails |
| [`docs/api.md`](docs/api.md) | REST contract, schemas, error model, SSE events |
| [`docs/adr/`](docs/adr/) | Architecture decisions, with the alternatives that were rejected and why |
| [`CLAUDE.md`](CLAUDE.md) | Working agreement: process, issue conventions, code standards, stack detail |

Specification sections are numbered and those numbers are stable. Issues, pull requests and
code comments reference them (`spec §47`) instead of restating them, so design lives in exactly
one place.

---

## Roadmap

| | | |
|---|---|---|
| **M0** | Foundations | Compose, CI, database, skeletons, auth, reference data |
| **M1** | Walking skeleton | One source, one route, end to end through every layer |
| **M2** | Collection | Scheduler, retention, partitioning, aggregates, source health |
| **M3** | Search engine | Multi-origin, flexible dates, budget, deduplication, streaming |
| **M4** | Historical intelligence | Percentiles, comparison scope, confidence |
| **M5** | Loyalty | Programmes, balances, transfer rules, status benefits |
| **M6** | Awards | Award observations, history, cash-versus-points |
| **M7** | Travel requirements | Visa engine, transit evaluation, readiness |
| **M8** | Watchlists and Telegram | Persistent searches, alerts, bot |
| **M9** | Ranking and interface | Score bands, comparison views, charts |

Collection sits at M2, well before the search engine that will eventually feed it. That's
deliberate: history is the only capability that needs calendar time to become useful. Build the
percentile engine in month seven with an empty table and it stays useless until month ten;
start collecting in week three and it works the day it ships.

Progress is tracked entirely in GitHub issues and milestones.

---

## Contributing

Not open to outside contributions — it's a personal project. The documentation is written to be
readable by someone who has never seen it, because that someone is usually me in four months.

If you're reading it for ideas, the parts most worth stealing are the provenance envelope in
[`docs/api.md`](docs/api.md) and the query budget in `spec §28`.

---

## License

None. All rights reserved.
