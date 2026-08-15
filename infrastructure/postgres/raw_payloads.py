"""Raw payload compression and storage (spec §4, §55).

Kept separate from models_raw.py so the model stays a plain schema
declaration and this module owns the encode/decode policy — the same split
already used between models_search.py and domain/flight/serialization.py.
"""

from __future__ import annotations

import gzip
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.postgres.models_raw import RawPayload


async def store_raw_payload(
    db: AsyncSession,
    *,
    source: str,
    request_key: str,
    payload: dict[str, Any],
    retrieved_at: datetime,
) -> None:
    """Compress and stage a raw payload for insert on the given session.

    Callers should commit this in its own transaction, separate from any
    normalization that follows — normalization can legitimately fail on a
    payload that is nonetheless worth having kept (spec §4's whole point).
    """
    compressed = gzip.compress(json.dumps(payload).encode("utf-8"))
    db.add(
        RawPayload(
            id=uuid.uuid4(),
            source=source,
            request_key=request_key,
            content_encoding="gzip",
            payload=compressed,
            retrieved_at=retrieved_at,
        )
    )


def load_raw_payload(raw: RawPayload) -> dict[str, Any]:
    if raw.content_encoding != "gzip":
        raise ValueError(f"unsupported content_encoding: {raw.content_encoding!r}")
    decoded: dict[str, Any] = json.loads(gzip.decompress(raw.payload).decode("utf-8"))
    return decoded
