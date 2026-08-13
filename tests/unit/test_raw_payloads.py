"""infrastructure/postgres/raw_payloads.py — encode/decode round-trip, no
database (the compression/decompression logic itself is pure)."""

import gzip
import json

import pytest

from infrastructure.postgres.models_raw import RawPayload
from infrastructure.postgres.raw_payloads import load_raw_payload


def test_load_raw_payload_decompresses_and_parses_json() -> None:
    original = {"success": True, "data": {"2026-10-01": {"price": 612}}}
    compressed = gzip.compress(json.dumps(original).encode("utf-8"))
    raw = RawPayload(
        id=None,  # not persisted in this test — load_raw_payload only reads fields
        source="travelpayouts",
        request_key="MXP-NRT:2026-10",
        content_encoding="gzip",
        payload=compressed,
        retrieved_at=None,
    )

    assert load_raw_payload(raw) == original


def test_load_raw_payload_rejects_unsupported_encoding() -> None:
    raw = RawPayload(
        id=None,
        source="travelpayouts",
        request_key="MXP-NRT:2026-10",
        content_encoding="br",  # not implemented
        payload=b"whatever",
        retrieved_at=None,
    )

    with pytest.raises(ValueError, match="unsupported content_encoding"):
        load_raw_payload(raw)
