"""Travelpayouts Data API adapter (spec §20, §89 item 1; docs/providers.md).

DISCOVERY layer only: knows HTTP, auth and this source's failure modes.
Knows nothing about the canonical flight model — that split is
normalization's job (spec §5), kept separate so a parser fix can be re-run
against retained raw payloads without recontacting the source (spec §4).

Endpoint contract (`GET /v1/prices/calendar`) confirmed against the vendor's
own published API reference before writing this, not assumed — same
practice as every other adapter in this project.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from providers.errors import SourceError, SourceErrorKind

SOURCE_ID = "travelpayouts"
CALENDAR_URL = "https://api.travelpayouts.com/v1/prices/calendar"


@dataclass(frozen=True)
class PriceCalendarRequest:
    origin: str
    destination: str
    depart_date: (
        str  # "YYYY-MM" — this endpoint answers a whole month at once (spec §28 batch_query)
    )
    currency: str = "eur"


async def fetch_price_calendar(
    request: PriceCalendarRequest,
    token: str,
    *,
    _transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """Raw fetch only — returns the parsed JSON body untouched.

    Callers get a raw payload; normalization is the only layer that
    interprets its fields, per the adapter contract's first rule
    (docs/providers.md "Adapter contract").

    `_transport` is keyword-only and defaults to real network access — tests
    substitute an `httpx.MockTransport` here instead of monkeypatching, the
    same injectable-dependency pattern used by the worker jobs.
    """
    params = {
        "origin": request.origin,
        "destination": request.destination,
        "depart_date": request.depart_date,
        "calendar_type": "departure_date",
        "currency": request.currency,
    }
    headers = {"x-access-token": token}

    async with httpx.AsyncClient(timeout=30.0, transport=_transport) as client:
        try:
            response = await client.get(CALENDAR_URL, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise SourceError(SourceErrorKind.TIMEOUT, str(exc), source_id=SOURCE_ID) from exc
        except httpx.ConnectError as exc:
            raise SourceError(
                SourceErrorKind.UPSTREAM_ERROR, str(exc), source_id=SOURCE_ID
            ) from exc

    _raise_for_status(response)
    return _parse_body(response)


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status in (401, 403):
        raise SourceError(SourceErrorKind.AUTHENTICATION, f"HTTP {status}", source_id=SOURCE_ID)
    if status == 429:
        raise SourceError(SourceErrorKind.RATE_LIMIT, f"HTTP {status}", source_id=SOURCE_ID)
    if status == 400:
        raise SourceError(SourceErrorKind.BAD_REQUEST, f"HTTP {status}", source_id=SOURCE_ID)
    if status >= 500:
        raise SourceError(SourceErrorKind.UPSTREAM_ERROR, f"HTTP {status}", source_id=SOURCE_ID)
    if status >= 400:
        # Any other 4xx on a documented endpoint is unexpected — treat it as
        # a contract change rather than guessing at a cause (spec §21).
        raise SourceError(SourceErrorKind.SCHEMA_CHANGE, f"HTTP {status}", source_id=SOURCE_ID)


def _parse_body(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError as exc:
        raise SourceError(
            SourceErrorKind.SCHEMA_CHANGE, "response was not valid JSON", source_id=SOURCE_ID
        ) from exc

    if not isinstance(body, dict) or "success" not in body or "data" not in body:
        shape = sorted(body.keys()) if isinstance(body, dict) else type(body).__name__
        raise SourceError(
            SourceErrorKind.SCHEMA_CHANGE,
            f"unrecognised response shape: {shape}",
            source_id=SOURCE_ID,
        )

    if body["success"] is not True:
        # A structurally valid response the API itself flags unsuccessful is
        # a genuine "no data for this query", not malformed — spec §45
        # requires this stay distinct from an error or an unexplored gap.
        raise SourceError(
            SourceErrorKind.NOT_AVAILABLE, "API reported success=false", source_id=SOURCE_ID
        )

    return body
