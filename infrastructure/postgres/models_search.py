"""Search and cash-observation persistence (issue #43; spec §5, §29, §56).

Deliberately thin for the M1 walking skeleton: a `Search` targets exactly one
origin/destination/month against exactly one source (Travelpayouts), not the
multi-origin/destination/date-range/budget model in docs/api.md §5 — that
richer shape is explicitly the M3 extension of this same resource, not
something to guess at before the search engine that needs it exists.

`CashObservation` stores the normalized offer as JSONB rather than a full
relational segment schema. Committing to relational segment columns before a
second source has exercised the shape would be guessing at a schema that
spec §56's real (M2) observation table — with its material-change dedup and
partitioning — is the actual, considered design for. JSONB here is a
deliberate M1 simplification, not the final storage shape.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
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
    search_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("searches.id"), nullable=False
    )

    itinerary_id: Mapped[str] = mapped_column(String(64))  # domain.flight.identity.fingerprint()
    source: Mapped[str] = mapped_column(String(64))

    price_minor: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3))

    freshness: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[str] = mapped_column(String(16))

    # The full FlightOffer, JSON-serialized (see module docstring). Read back
    # through the same dataclass shape at the API layer rather than
    # duplicated into columns.
    offer: Mapped[dict] = mapped_column(JSON)

    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
