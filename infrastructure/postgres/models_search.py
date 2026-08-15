"""Search and cash-observation persistence (spec §5, §27, §29, §56).

`Search` carries the full multi-origin/destination/date-range/budget model
from docs/api.md §5 "Create": `origins`/`destinations` are JSON arrays of
`{code, weight}` (weights rank, never filter — spec §27), `cabins` and
`hard_filters` are JSON since their shape is defined by domain/ranking/filters.py
and domain/search/expansion.py, not by this persistence layer. `space_total`/
`space_explored` are computed once at creation from the full expansion and
updated as the orchestrator (apps/worker/jobs/travelpayouts_search.py) spends
budget — `not_explored` is derived (`space_total - space_explored`), never
stored, so the two numbers cannot drift apart.

`sources` is a JSON array of per-source state (docs/api.md §5 "Retrieve"
`sources` field) rather than a child table — with exactly one adopted source
(Travelpayouts, spec §20) a relational table would be pure ceremony; it
becomes worth normalizing once a second source exists to justify querying
across sources independently of their parent search.

`CashObservation` stores the normalized offer as JSONB rather than a full
relational segment schema. Committing to relational segment columns before a
second source has exercised the shape would be guessing at spec §57's real
aggregate schema before it exists. JSONB here is a deliberate simplification,
not the final storage shape.

A row is a period during which a value held (`first_seen_at`/`last_seen_at`/
`poll_count`), not one row per fetch (spec §56) — one row per poll would let
polling frequency masquerade as market volatility once percentiles are
computed over it. Its identity is `(itinerary_id, source)`, not the `Search`
that happened to produce it — a scheduled re-collection run creates a *new*
`Search` row every day for the same route, and must extend the same
observation period rather than starting a new one each time. `last_search_id`
keeps a pointer to whichever search most recently touched the row, for
provenance/debugging only; it carries no identity meaning.

`origin`/`destination`/`depart_month` live on the observation itself, not
just on whichever `Search` produced it — a `Search` now spans many routes
and a whole date range, so there is no single matching field to denormalize
from. Storing them here lets the results endpoint query "this route's
current observations" directly, matching the dimensions spec §57's
`flight_price_daily` aggregate will need anyway, without reconstructing
which of a search's many routes a given observation belongs to.

`cash_observations` is declaratively partitioned by month on
`first_seen_at` (spec §55). Postgres requires every unique/primary key on a
partitioned table to include the partition column, so the primary key is
the composite `(id, first_seen_at)` rather than `id` alone —
`first_seen_at` is never written again after insert (write_observation's
"extend" path only ever updates `last_seen_at`/`poll_count`/detail fields),
so a row never needs to move partitions. Partitions themselves are runtime
objects created by infrastructure/postgres/partitions.py's maintenance job,
not represented in migrations (spec §55's own stated split).
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.postgres.base import Base


class SearchState(enum.StrEnum):
    """spec §29's state machine, the subset reachable before ENRICHING/
    EVALUATING/STALE/EXPIRED exist (M4/M9/M8 concerns respectively — adding
    them now would be states nothing could ever transition into). PARTIAL is
    included for the multi-source case docs/api.md §5 "Retrieve" shows, even
    though with exactly one adopted source (Travelpayouts) a search currently
    moves straight from RUNNING to READY/FAILED and never rests in PARTIAL —
    it exists so a second source does not need a state-machine migration to
    use it."""

    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    READY = "ready"
    FAILED = "failed"


class SourceState(enum.StrEnum):
    """One source's contribution to a search (docs/api.md §5 "Retrieve"
    `sources[].state`) — distinct from `SearchState`, which is the search as
    a whole. `UNAVAILABLE` covers a source the circuit breaker rejected
    outright (spec §21/§25); `FAILED` covers one that was called and errored."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class Search(Base):
    __tablename__ = "searches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # Nullable: a search does not require a saved profile (docs/api.md §5's
    # example includes one, but nothing in spec §27 makes it mandatory — the
    # traveller-specific rules it would drive, e.g. loyalty or visa, are M5/M7
    # concerns this search resource does not yet act on).
    traveller_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("traveller_profiles.id"), nullable=True
    )

    # [{"code": "MXP", "weight": 100}, ...] — domain.search.expansion.WeightedLocation's
    # own shape, JSON because this table has no reason to know it beyond
    # passing it through to that module.
    origins: Mapped[list] = mapped_column(JSON)
    destinations: Mapped[list] = mapped_column(JSON)

    date_start: Mapped[date] = mapped_column(Date)
    date_end: Mapped[date] = mapped_column(Date)
    min_nights: Mapped[int] = mapped_column(Integer)
    max_nights: Mapped[int] = mapped_column(Integer)
    cabins: Mapped[list] = mapped_column(JSON)  # list[str]
    max_stops: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # domain.ranking.filters' concrete filter names/params, e.g.
    # {"no_self_transfer": true, "arrive_before_local": "18:00"} — this table
    # stores the request verbatim; only the orchestrator interprets it.
    hard_filters: Mapped[dict] = mapped_column(JSON, default=dict)

    budget_calls: Mapped[int] = mapped_column(Integer)
    budget_spent: Mapped[int] = mapped_column(Integer, default=0)

    # Computed once at creation from the full expansion (domain/search/
    # expansion.py's expand()) and increased as the orchestrator spends
    # budget. not_explored is deliberately NOT a column — see module
    # docstring for why storing it separately would risk drift.
    space_total: Mapped[int] = mapped_column(Integer, default=0)
    space_explored: Mapped[int] = mapped_column(Integer, default=0)

    # [{"source": "travelpayouts", "state": "completed", "results": 187,
    #   "reason": {"code": "BLOCKED", "circuit": "OPEN"} | null}, ...]
    sources: Mapped[list] = mapped_column(JSON, default=list)

    state: Mapped[SearchState] = mapped_column(default=SearchState.PENDING)
    # Whole-search failure only (e.g. no configured source could even start —
    # missing token, no resolved origin timezone). A single source's own
    # failure is recorded in `sources`, not here; the two are distinct
    # because a search with one failed source among several is PARTIAL/READY,
    # not FAILED.
    failure_reason: Mapped[str | None] = mapped_column(String(64), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class CashObservation(Base):
    __tablename__ = "cash_observations"
    __table_args__ = ({"postgresql_partition_by": "RANGE (first_seen_at)"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    # Identity for material-change dedup (spec §56) — NOT a foreign key to
    # any single Search. See module docstring.
    itinerary_id: Mapped[str] = mapped_column(String(64), index=True)  # domain.flight.identity
    source: Mapped[str] = mapped_column(String(64), index=True)

    # Denormalized route, so results can be queried without assuming a
    # 1:1 Search relationship (module docstring).
    origin: Mapped[str] = mapped_column(String(4))
    destination: Mapped[str] = mapped_column(String(4))
    depart_month: Mapped[str] = mapped_column(String(7))

    price_minor: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3))

    freshness: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[str] = mapped_column(String(16))

    # The full FlightOffer, JSON-serialized (see module docstring). Read back
    # through the same dataclass shape at the API layer rather than
    # duplicated into columns. Reflects the *latest* poll's offer detail —
    # not versioned per poll, since the identity fields above plus
    # first_seen_at/last_seen_at already capture the period.
    offer: Mapped[dict] = mapped_column(JSON)

    # spec §56: a row is a period during which a value held, not one row per
    # poll. An unchanged repeat poll extends last_seen_at and increments
    # poll_count instead of writing a new row (decided in
    # domain/collection/material_change.py).
    #
    # Part of the primary key — Postgres requires the partition column on
    # every unique constraint of a partitioned table. Never rewritten after
    # insert, so this does not mean a row can move partitions during its life.
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    poll_count: Mapped[int] = mapped_column(Integer, default=1)

    # Provenance only (module docstring) — nullable because a row can outlive
    # the Search that first created it, and a future non-interactive source
    # (the scheduler creates one Search per run, but a later source might
    # not go through Search at all).
    last_search_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("searches.id"), nullable=True
    )
