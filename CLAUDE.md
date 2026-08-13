# LocalhostAirlines — Working Agreement

Operational rules for any session working on this repository. Read together with
`specifications.md`, which is the single source of truth for *what* the system is.
This file covers *how* we work on it.

---

## 1. Source of truth

- **`specifications.md`** — the compass. Architecture, data model, domain rules, rationale.
  Numbered sections are stable anchors: reference them, never copy them.
- **GitHub issues** — the work. What must be done, in what order, by which acceptance criteria.
- **This file** — the process and the technical conventions.

The rule that keeps these three from drifting:

> Issues describe **work**. The specification describes **design**.
> An issue must never restate a design decision — it links to the section that holds it.

When an issue's implementation reveals that the spec is wrong, the spec is updated
**in the same pull request** as the code. A PR that changes behaviour described in
`specifications.md` without touching it is incomplete.

A person who has never seen this project must be able to pick up any issue and act on it
using only that issue plus the spec sections it links. If that is not true, the issue is
badly written — fix it before starting work.

---

## 2. Everything is tracked in GitHub

No work happens outside an issue. This is what makes progress legible across chats,
sessions and machines.

### Milestones

One milestone per delivery phase. A milestone is closed only when every issue in it is
closed. Milestones map to the phased plan in the specification, not to calendar dates.

### Issues

Issues are **precise and short**. Target: under 20 lines. Structure:

```markdown
<one sentence: what this delivers>

Spec: specifications.md §<n>, §<m>

## Acceptance criteria
- [ ] <observable, checkable outcome>
- [ ] <observable, checkable outcome>

## Notes
<only genuinely non-obvious constraints; omit the section otherwise>
```

Rules:

- Title in the imperative: "Add provider capability matrix", not "Provider capabilities".
- Acceptance criteria are **observable**. "Endpoint returns 422 on unknown airport code",
  not "handle errors properly".
- No design rationale in the issue body. That lives in the spec.
- No copied tables, schemas or field lists. Link the section.
- If an issue cannot be finished in one focused sitting, it is too big — split it into
  sub-issues.

### Sub-issues

Use GitHub's native sub-issue relationship (not markdown checklists) for decomposition.
Parent issues carry the goal and the acceptance criteria for the whole unit; sub-issues
carry one deliverable each. Parents close automatically only once all children are closed.

### Labels

| Prefix | Values |
|---|---|
| `area:` | `api`, `web`, `worker`, `db`, `provider`, `infra`, `docs`, `telegram` |
| `type:` | `feat`, `fix`, `chore`, `spike`, `refactor`, `test` |
| `prio:` | `p0`, `p1`, `p2` |

`type:spike` means time-boxed investigation whose deliverable is a written answer —
usually an update to the spec or an ADR — not code.

### Decisions

Any decision that changes the architecture is recorded as an ADR in `docs/adr/` and
referenced from the relevant spec section. Issues do not hold decisions; they consume them.

---

## 3. Branch, PR and merge workflow

- Branch from `main`: `<type>/<issue-number>-<short-slug>` (e.g. `feat/42-query-budget`).
- Never commit directly to `main`. Never merge locally.
- PR body references the issue with `Closes #<n>` so it closes on merge.
- All CI checks must pass before merge.
- Merge with a merge commit, preserving topology: `gh pr merge <n> --merge --delete-branch`.
- No orphaned branches, no issues left open after their PR merged.
- Ask which branch to use before any git operation unless it was already specified.

---

## 4. Language and tone

- Code, comments, identifiers, commit messages, issues, PRs, documentation: **English**.
- Chat: Italian.
- No emoji anywhere in the repository.
- No mention of AI tooling in commits, comments, documentation or issue text.
  All work is attributed solely to the repository owner.

---

## 5. Code standards

### Comments

Comment the **why**, never the **what**. The code already says what it does.

```python
# Bad:  increment the counter
# Good: seats.aero counts a cached bulk fetch as one call regardless of route count,
#       so the budget is charged once per fetch, not per route returned.
```

Every module carries a short docstring stating its responsibility and its position in the
DISCOVERY → NORMALIZATION → ENRICHMENT → EVALUATION → PRESENTATION pipeline. Any
non-obvious algorithmic choice, and every deviation from the specification, carries an
inline comment naming the spec section it relates to.

### Layering

The pipeline stages in the specification are enforced as module boundaries, not suggestions.
Provider adapters never import domain rules. Domain rules never import provider clients.
Normalization is the only place that knows a provider's payload shape.

### Non-negotiables

These come straight from the spec's core principles and are checked in review:

- No mutable business fact as a code constant. Ratios, thresholds, benefits, visa rules and
  alliance membership live in the database with provenance, version and timestamp.
- Every externally-sourced value carries `source`, `retrieved_at`, freshness state and confidence.
- "Unavailable" and "not found" are distinct states and must never collapse into one.
- All timestamps are `timestamptz` in UTC. Local times are stored alongside an IANA timezone.
  Durations are computed from UTC only.
- Money is integer minor units plus an ISO-4217 code. Never floats.
- An adapter that meets an unexpected payload shape fails loudly. It never returns
  partially-normalized data.

### Testing

Domain logic (date expansion, budget allocation, points conversion, percentiles, ranking,
deduplication, risk) is unit-tested and must not require a database. Provider adapters are
tested against recorded fixtures. Contract tests detect upstream schema drift.

---

## 6. Technology stack

| Layer | Choice | Version |
|---|---|---|
| Frontend | Vite + React + TypeScript, static SPA | Node 22 LTS (build only) |
| Frontend data | TanStack Query (server state), TanStack Router (typed routing) | |
| Backend | Python + FastAPI, REST + SSE | Python 3.13 |
| Async HTTP | httpx + asyncio | |
| Headless browser | Playwright (Chromium), isolated container | |
| Database | PostgreSQL | 17 |
| Cache / queue | Redis | 7 |
| Jobs + scheduling | ARQ (asyncio-native, Redis-backed, built-in cron) | |
| Migrations | Alembic | |
| Lint / format / types | Ruff, mypy (strict on `domain/`), tsc | |
| Reverse proxy | Caddy (also serves the static frontend build) | 2 |
| Orchestration | Docker Compose, multi-arch via buildx | |
| Notifications | Telegram Bot API (long polling) | |

Versions are pinned in `docker-compose.yml` and the lockfiles, and upgraded deliberately.
`latest` appears nowhere.

### Containers

```
caddy      reverse proxy, serves the static frontend build
api        FastAPI: REST + SSE
worker     ARQ: default queue, cron schedules, Telegram polling
scraper    ARQ: `scraping` queue only, Playwright/Chromium, hard memory cap
postgres
redis
```

The scheduler and the Telegram bot are asyncio loops inside `worker`; they do not warrant
separate processes.

`scraper` **is an ARQ worker**, not a browser service the others call. It consumes a dedicated
`scraping` queue at concurrency 1–3 with a hard memory limit. This avoids exposing a browser
control protocol between containers, and gives back-pressure for free: when the queue is full,
jobs wait instead of the browser thrashing.

Headless jobs are enqueued **only** by the scheduler or by an explicit verification request —
never synchronously from an HTTP handler. No user request ever blocks on a browser.

### Cross-container coordination

| Concern | Mechanism | Why |
|---|---|---|
| Job dispatch | Redis, via ARQ | |
| Search progress → SSE | Redis pub/sub, channel per search id | `worker` produces, `api` streams (`spec §30`) |
| Search state | PostgreSQL | Survives a Redis loss (`spec §82`) |
| Sessions | PostgreSQL | Redis loss must not log everyone out (`spec §78`) |
| Telegram update offset | PostgreSQL | Must survive a worker restart without replaying or skipping |

### Continuous integration

GitHub Actions on every pull request: Ruff, mypy, tsc, unit tests, adapter contract tests
against fixtures, an Alembic migration round-trip against a seeded database, and a build of
every image.

**CI never touches an external source.** Contract tests run against recorded fixtures only
(`spec §21`). A test suite that depends on a scraped source would fail for reasons unrelated to
the change under review, and would train everyone to ignore red builds.

### Docker is the only runtime

Nothing is installed on the host — no Python, no Node, no package managers. Production is
`docker-compose.yml` alone (`make up`). Development additionally loads `docker-compose.dev.yml`
plus `--profile dev` (`make dev`), which bind-mounts source and enables hot reload for `api` and
the Vite dev server. The dev file is deliberately not named `docker-compose.override.yml`:
that filename auto-merges into every `docker compose` invocation, which would make a bare
`docker compose up -d` on a production host silently pick up dev behaviour whenever the file
happened to be present. It also tags the dev builds under a distinct image name — reusing the
production tag let Compose skip rebuilding on `up` and silently serve the production binary
under a "dev" invocation, caught the first time the setup was actually run end to end.

Images are built for `linux/amd64` and `linux/arm64` so the same images run on an Apple
Silicon development machine and on an x86 production host. All state lives in named volumes.
Configuration comes from `.env` only; no secret is ever baked into an image or committed.

### Resource model

Storage is abundant; **the scarce resource is access to the sources.** Scraped and
unofficial endpoints are fragile, rate-limited and ban-prone. Therefore:

- Cache aggressively; re-fetch as rarely as correctness allows.
- Persist raw payloads compressed, retained 12 months, so a parser fix can **re-normalize
  history without contacting the source again**. Normalized observations and daily
  aggregates are retained indefinitely.
- Global concurrency is bounded by politeness toward each source, not by host capacity.

This inverts the original Raspberry Pi assumption recorded in `specifications.md` §64.

### Source classification

Every provider declares which class it belongs to; the class governs volume limits,
expected reliability, retention and how freshness is presented in the UI.

| Class | Meaning |
|---|---|
| `OFFICIAL_API` | Documented, authorized API with a key |
| `PUBLIC_DATA` | Open dataset (OurAirports, OpenFlights, ECB rates) |
| `UNOFFICIAL_ENDPOINT` | Undocumented JSON endpoint used by a vendor's own frontend |
| `SCRAPED` | HTML parsing, optionally requiring headless rendering |

The last two classes are expected to break without warning. Contract tests against recorded
fixtures, per-source health tracking and circuit breakers are therefore **P0, not optional**.
A broken source must degrade to `UNKNOWN` with an open circuit — never to a wrong value.

Two hard limits: we do not bypass CAPTCHAs, and we do not automate logins into personal
loyalty accounts. Loyalty balances and status are entered manually, which the specification
already treats as a first-class path.

---

## 7. Repository layout

```
apps/
  api/            FastAPI application
  web/            Vite + React SPA
  worker/         ARQ jobs, schedules, Telegram bot
domain/           pure domain logic, no I/O, no framework imports
  flight/ loyalty/ award/ travel_rules/ search/ history/ ranking/ users/
providers/        source adapters (DISCOVERY layer)
normalization/    payload → canonical model, one module per source
infrastructure/
  postgres/ redis/ docker/ caddy/
config/           source capabilities, freshness windows, ranking presets
seeds/            CURATED reference data under version control
tests/
docs/
  providers.md  api.md  adr/
```

`domain/` is the layer that must stay pure. It imports no HTTP client, no ORM session and no
framework. That is what makes the evaluation pipeline exhaustively testable without a database
or a network, and it is the boundary most likely to erode under time pressure.

## 8. Milestones

One GitHub milestone each, matching `specifications.md §86`. The specification holds what each
contains; this is the index.

| Milestone | Delivers |
|---|---|
| **M0** Foundations | Compose, CI, Postgres + Alembic, API and SPA skeletons, auth, users, traveller profiles, reference data |
| **M1** Walking skeleton | One source, one route, end to end through every layer |
| **M2** Collection | Scheduler, raw retention, partitioning, aggregates, source health, circuit breakers |
| **M3** Search engine | Multi-origin and destination, flexible dates, query budget, deduplication, SSE |
| **M4** Historical intelligence | Percentiles, comparison scope, confidence floors, assessments |
| **M5** Loyalty | Programmes, manual balances and status, curated transfer rules, benefits |
| **M6** Awards | Award adapters and observations, cash-versus-award, reverse search |
| **M7** Travel requirements | Requirement engine, transit evaluation, readiness, map |
| **M8** Watchlists and Telegram | Persistent searches, events, notification aggregation, bot |
| **M9** Ranking and interface | Score components, bands, comparison and freshness views, charts |

Two sequencing rules that are easy to violate and expensive to correct:

- **M2 before M3.** The historical clock starts at M2, and history is the only capability that
  needs calendar time to become useful (ADR 0005).
- **Quality gates and partitioning are complete at M2**, not deferred. Real data starts
  flowing there, and bad rows written into history are effectively permanent — the source
  cannot be re-queried for the past.

## 9. Current state

Design agreed, implementation not started. Before the first line of code:

1. Create the milestones and the M0 issues.
2. Open the `type:spike` issues for the open questions in `specifications.md §89` — they gate
   which adapters are worth building, and answering them changes what M1 targets.
3. Do not scaffold beyond what an M0 issue asks for.
