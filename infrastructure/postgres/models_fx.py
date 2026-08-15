"""FX rate persistence (spec §82).

ECB never revises a published daily rate, so a row here is an immutable
historical fact once written: ingestion is insert-or-skip, never update
(spec P2/P3 — every externally-sourced value carries provenance and is never
silently overwritten). The natural key is (quote_currency, rate_date); the
base currency is always EUR, since that is the only base ECB publishes.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.postgres.base import Base


class FxRate(Base):
    __tablename__ = "fx_rates"

    quote_currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)

    # ECB base currency is always EUR; kept as a column rather than hardcoded
    # in queries so a future non-ECB source doesn't require a schema change.
    base_currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")

    # NUMERIC, never float (spec money-precision principle) — an FX rate is a
    # ratio applied to money and must round the same way every time it's used.
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 6))

    source: Mapped[str] = mapped_column(String(64), default="ecb", server_default="ecb")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
