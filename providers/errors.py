"""Shared error classification for provider adapters (spec §26).

Every external failure is classified once, at the DISCOVERY boundary, so retry
policy and user-facing messaging can be decided from the classification
rather than re-derived downstream from opaque, provider-specific exceptions.
"""

from __future__ import annotations

import enum


class SourceErrorKind(enum.StrEnum):
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    UPSTREAM_ERROR = "upstream_error"
    BAD_REQUEST = "bad_request"
    SCHEMA_CHANGE = "schema_change"
    BLOCKED = "blocked"
    NOT_AVAILABLE = "not_available"


class SourceError(Exception):
    """Raised by a provider adapter for any external failure (spec §26).

    NOT_AVAILABLE is not exceptional in the usual sense — a source legitimately
    answering "nothing for this query" is a genuine result (spec §45), distinct
    from a combination the system never explored (spec §28) — but it still
    needs to interrupt normal flow so a caller cannot mistake it for a
    successful payload and normalize garbage from an empty response.
    """

    def __init__(self, kind: SourceErrorKind, message: str, *, source_id: str) -> None:
        super().__init__(f"[{source_id}] {kind.value}: {message}")
        self.kind = kind
        self.source_id = source_id
        self.detail = message
