"""Raw payload retention (issue #52; spec §4, §55).

Raw payloads are the reprocessing safety net: "when a parser breaks — and
parsers for unofficial sources break routinely — the raw payloads already
collected can be reprocessed against the fixed parser" (spec §4). Compressed
at rest since raw JSON is repetitive and compresses well (empirically
estimated ~5:1 in docs/adr/0007-observation-volume-estimate.md).

Source-agnostic shape (not Travelpayouts-specific) so #14/#15's adapters can
adopt the same table later without a schema change, even though issue #52
only wires up Travelpayouts for now.

Retention (12 months, spec §55) is enforced by a scheduled job dropping old
rows/partitions (issue #53), not implemented in this module — this is
storage and retrieval only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.postgres.base import Base


class RawPayload(Base):
    __tablename__ = "raw_payloads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    source: Mapped[str] = mapped_column(String(64))
    # Identifies what request produced this payload, e.g. "MXP-NRT:2026-10"
    # for a Travelpayouts price-calendar fetch — not a foreign key, since a
    # scheduled collection run (issue #56) may have no Search row at all.
    request_key: Mapped[str] = mapped_column(String(256))

    content_encoding: Mapped[str] = mapped_column(String(16), default="gzip")
    payload: Mapped[bytes] = mapped_column(LargeBinary)

    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
