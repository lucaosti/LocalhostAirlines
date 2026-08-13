"""Reference data: airports, airlines, and derived airport groups (spec §124,
issue #14).

Kept separate from models.py — a distinct concern (provider-sourced reference
data refreshed on a schedule) from the user/traveller domain. Both modules
register on the same `Base.metadata`; alembic/env.py imports both.

`icao_code` is the primary key rather than a synthetic UUID: it is the
real-world stable identity OurAirports and OpenFlights both index by, so a
monthly refresh can UPDATE an existing row in place (preserving any future
foreign key referencing it) instead of juggling a separate natural-key lookup
around a meaningless surrogate.
"""

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.postgres.base import Base


class TimezoneResolution(enum.StrEnum):
    OPENFLIGHTS = "OPENFLIGHTS"
    COORDINATES = "COORDINATES"
    UNRESOLVED = "UNRESOLVED"


class Airport(Base):
    __tablename__ = "airports"

    icao_code: Mapped[str] = mapped_column(String(4), primary_key=True)
    iata_code: Mapped[str] = mapped_column(String(3), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    airport_type: Mapped[str] = mapped_column(String(32))
    municipality: Mapped[str] = mapped_column(String(128))
    iso_country: Mapped[str] = mapped_column(String(2), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)

    # Nullable: an UNRESOLVED airport has no timezone value at all, not a
    # guessed one (spec §36 — the quality gate rejects itineraries touching
    # it rather than risk a silently wrong duration).
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timezone_resolution: Mapped[TimezoneResolution] = mapped_column()

    # Soft delete: a code that disappears from upstream is deactivated, never
    # hard-deleted, so historical rows referencing it stay valid (issue #14
    # acceptance criterion: "codes disappearing... are logged, not silently
    # dropped").
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    source: Mapped[str] = mapped_column(String(32))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Airline(Base):
    __tablename__ = "airlines"

    icao_code: Mapped[str] = mapped_column(String(3), primary_key=True)
    iata_code: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    country: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # OpenFlights' own active flag, distinct from `active` below — a source
    # can mark an airline defunct without the row disappearing from the feed
    # entirely, which is a different fact from "no longer present upstream
    # at all". Both are worth keeping separately rather than collapsing into
    # one boolean that would lose the distinction.
    active_in_source: Mapped[bool] = mapped_column(Boolean)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    source: Mapped[str] = mapped_column(String(32))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # OpenFlights is never authoritative for alliance membership (spec §49);
    # that stays CURATED data, modelled separately when loyalty (M5) lands.


class AirportGroup(Base):
    """A derived metro-area cluster (spec §27, §34) — e.g. Milan grouping
    MXP/LIN/BGY. Recomputed wholesale on every ingestion run rather than
    diffed incrementally: it's cheap derived data, not a source of truth.
    """

    __tablename__ = "airport_groups"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    anchor_icao_code: Mapped[str] = mapped_column(
        ForeignKey("airports.icao_code", ondelete="CASCADE")
    )

    members: Mapped[list["AirportGroupMember"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class AirportGroupMember(Base):
    __tablename__ = "airport_group_members"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("airport_groups.id", ondelete="CASCADE"), primary_key=True
    )
    airport_icao_code: Mapped[str] = mapped_column(
        ForeignKey("airports.icao_code", ondelete="CASCADE"), primary_key=True
    )

    group: Mapped[AirportGroup] = relationship(back_populates="members")
