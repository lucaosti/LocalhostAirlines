"""Shared Pydantic building blocks that enforce docs/api.md §1 conventions.

Pydantic's default datetime serialization emits `+00:00` for UTC; the API
contract requires `Z`-suffixed RFC 3339 (docs/api.md §1). `UtcDatetime` is the
one type every response schema uses for an instant field, so the convention is
structural rather than something each schema has to remember to apply.
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import PlainSerializer


def _serialize_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError(
            "naive datetime passed to UtcDatetime field; spec §12 requires timestamptz"
        )
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


UtcDatetime = Annotated[datetime, PlainSerializer(_serialize_utc, return_type=str)]
