"""Search and cash-observation persistence (issues #43, #54; spec §5, §29, §56).

Deliberately thin for the M1 walking skeleton: a `Search` targets exactly one
origin/destination/month against exactly one source (Travelpayouts), not the
multi-origin/destination/date-range/budget model in docs/api.md §5 — that
richer shape is explicitly the M3 extension of this same resource, not
something to guess at before the search engine that needs it exists.

`CashObservation` stores the normalized offer as JSONB rather than a full
relational segment schema. Committing to relational segment columns before a
second source has exercised the shape would be guessing at spec §57's real
aggregate schema before it exists. JSONB here is a deliberate simplification,
not the final storage shape.

Issue #54 moved this to the real spec §56 shape: a row is a period during
which a value held (`first_seen_at`/`last_seen_at`/`poll_count`), not one row
per fetch. Its identity is `(itinerary_id, source)`, not the `Search` that
happened to produce it — a scheduled re-collection run (issue #56) creates a
*new* `Search` row every day for the same route, and must extend the same
observation period rather than starting a new one each time. `last_search_id`
keeps a pointer to whichever search most recently touched the row, for
provenance/debugging only; it carries no identity meaning.

`origin`/`destination`/`depart_month` are denormalized onto the observation
(available on `Search` already, and duplicated here) so the results endpoint
can query "this route's current observations" directly — matching the
dimensions spec §57's `flight_price_daily` aggregate will need anyway,
rather than reaching through a `Search` join that no longer has 1:1 meaning.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.postgres.base import Base


class SearchState(enum.StrEnum):
    """Minimal subset of spec §29's full state machine — enough for one
    source, one route. RUNNING/PARTIAL/READY distinctions and per-source
    state (docs/api.md §5 "Retrieve") are an M3 concern."""

    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class Search(Base):
    __tablename__ = "searches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    origin: Mapped[str] = mapped_column(String(4))
    destination: Mapped[str] = mapped_column(String(4))
    depart_month: Mapped[str] = mapped_column(String(7))  # "YYYY-MM" — this endpoint's own grain

    state: Mapped[SearchState] = mapped_column(default=SearchState.PENDING)
    # Populated only when state == FAILED — the error classification (spec
    # §26) from the job that ran this search, so a client can distinguish a
    # transient RATE_LIMIT from a durable SCHEMA_CHANGE without re-running it.
    failure_reason: Mapped[str | None] = mapped_column(String(64), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class CashObservation(Base):
    __tablename__ = "cash_observations"

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
    # poll_count instead of writing a new row (issue #54,
    # domain/collection/material_change.py).
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    poll_count: Mapped[int] = mapped_column(Integer, default=1)

    # Provenance only (module docstring) — nullable because a row can outlive
    # the Search that first created it, and a future non-interactive source
    # (issue #56's scheduler creates one per run, but a later source might
    # not go through Search at all).
    last_search_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("searches.id"), nullable=True
    )
