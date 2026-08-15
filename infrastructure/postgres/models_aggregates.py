"""Nightly price aggregates (spec §57).

`cabin`/`fare_family` are non-nullable empty-string, not NULL, when the
source doesn't state them — a deliberate choice distinct from spec P3's
AVAILABLE/UNAVAILABLE/UNKNOWN rule, which governs externally-sourced facts
shown to a user. This is a grouping key for an internal aggregate row, not a
displayed value, and Postgres composite uniqueness can't be enforced across
a nullable column without a partial-index workaround uglier than an empty
string sentinel.
"""

from __future__ import annotations

import uuid
from datetime import date as date_
from datetime import datetime

from sqlalchemy import Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.postgres.base import Base


class FlightPriceDaily(Base):
    __tablename__ = "flight_price_daily"
    __table_args__ = (
        UniqueConstraint(
            "aggregate_date",
            "route",
            "cabin",
            "fare_family",
            "source",
            "currency",
            name="uq_flight_price_daily_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    aggregate_date: Mapped[date_] = mapped_column(Date)
    route: Mapped[str] = mapped_column(String(9))  # "MXP-NRT"
    cabin: Mapped[str] = mapped_column(String(32), default="")
    fare_family: Mapped[str] = mapped_column(String(64), default="")
    source: Mapped[str] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3))

    minimum_price_minor: Mapped[int] = mapped_column(Integer)
    median_price_minor: Mapped[int] = mapped_column(Integer)
    maximum_price_minor: Mapped[int] = mapped_column(Integer)
    observation_count: Mapped[int] = mapped_column(Integer)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
