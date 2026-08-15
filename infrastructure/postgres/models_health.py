"""Per-source health persistence (spec §21, §25).

One row per source, updated in place — health is current state, not a
history (the observation/raw-payload tables already are the history, per
spec §55).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.postgres.base import Base


class SourceHealth(Base):
    __tablename__ = "source_health"

    source: Mapped[str] = mapped_column(String(64), primary_key=True)

    state: Mapped[str] = mapped_column(
        String(16)
    )  # domain.reliability.circuit_breaker.CircuitState
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # spec §26 error kind — lets an operator (or later, the docs/api.md §5
    # "Retrieve" per-source state) see *why* a source is degraded, not just
    # that it is.
    last_failure_reason: Mapped[str | None] = mapped_column(String(32), default=None)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
