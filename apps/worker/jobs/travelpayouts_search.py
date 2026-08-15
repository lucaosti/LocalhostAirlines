"""Runs one M1 walking-skeleton search: fetch -> retain raw -> normalize ->
persist.

fetch (providers.travelpayouts.client), guarded by a per-source circuit
breaker (spec §21/§25 — repeated source-side failures stop further calls
rather than retrying harder) -> raw retention (spec §4/§55) -> normalize
(normalization.travelpayouts) -> quality gate -> write with material-change
dedup (spec §56's real write order).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models_reference import Airport
from infrastructure.postgres.models_search import Search, SearchState
from infrastructure.postgres.observations import write_observation
from infrastructure.postgres.raw_payloads import store_raw_payload
from infrastructure.postgres.source_health import may_call, record_failure, record_success
from infrastructure.settings import get_settings
from normalization.travelpayouts import normalize_price_calendar
from providers.errors import SourceError, SourceErrorKind
from providers.travelpayouts.client import PriceCalendarRequest, fetch_price_calendar

SOURCE_ID = "travelpayouts"

logger = logging.getLogger(__name__)


async def run_travelpayouts_search(
    ctx: dict[str, Any],
    search_id: str,
    *,
    _fetch: Any = fetch_price_calendar,
) -> None:
    """`_fetch` is the same injectable-dependency pattern as every other job
    in this project — tests substitute a fixture-backed stub, production
    takes the default and hits the real API."""
    async with session_scope() as db:
        search = await db.get(Search, uuid.UUID(search_id))
        if search is None:
            logger.error("travelpayouts search job: search %s not found", search_id)
            return

        search.state = SearchState.RUNNING

    try:
        offers = await _run(search_id, _fetch)
    except SourceError as exc:
        logger.warning("travelpayouts search %s failed: %s", search_id, exc)
        async with session_scope() as db:
            await record_failure(db, exc.source_id, exc.kind)
            search = await _get_search(db, search_id)
            search.state = SearchState.FAILED
            search.failure_reason = exc.kind.value
            search.completed_at = datetime.now(UTC)
        return

    async with session_scope() as db:
        await record_success(db, SOURCE_ID)
        search = await _get_search(db, search_id)
        now = datetime.now(UTC)
        for offer in offers:
            # Material-change dedup (spec §56): extends the existing period
            # for this itinerary+source if the price is unchanged, rather
            # than writing a new row per poll — required for percentile
            # correctness once a scheduled re-collection polls the same
            # route daily.
            await write_observation(
                db,
                offer=offer,
                origin=search.origin,
                destination=search.destination,
                depart_month=search.depart_month,
                retrieved_at=offer.retrieved_at,
                search_id=search.id,
            )
        search.state = SearchState.READY
        search.completed_at = now

    logger.info("travelpayouts search %s: %d offers stored", search_id, len(offers))


async def _get_search(db: AsyncSession, search_id: str) -> Search:
    """The job's own None-check has already run in run_travelpayouts_search
    before any of these later lookups happen — a row deleted mid-run would be
    a genuinely exceptional state, not a normal control-flow case, so this
    raises rather than silently no-op-ing on a vanished row."""
    search = await db.get(Search, uuid.UUID(search_id))
    if search is None:
        raise RuntimeError(f"search {search_id} disappeared mid-run")
    return search


async def _run(search_id: str, fetch: Any) -> list:
    async with session_scope() as db:
        search = await _get_search(db, search_id)
        origin, destination, depart_month = search.origin, search.destination, search.depart_month

        airport = (
            await db.execute(select(Airport).where(Airport.iata_code == origin))
        ).scalar_one_or_none()
        if airport is None or airport.timezone is None:
            # Genuinely can't proceed correctly — the itinerary fingerprint
            # needs the origin's local departure date (spec §15), and a
            # guessed timezone risks a wrong one silently (spec §36). Same
            # posture as the reference-data quality gate.
            raise SourceError(
                SourceErrorKind.NOT_AVAILABLE,
                f"no resolved timezone for origin airport {origin}",
                source_id=SOURCE_ID,
            )
        origin_timezone = airport.timezone

        # Checked inside the same session as the lookups above so a
        # currently-open circuit is rejected before a token check or fetch
        # is even attempted.
        if not await may_call(db, SOURCE_ID):
            raise SourceError(
                SourceErrorKind.BLOCKED,
                "circuit open — recent failures exceeded threshold",
                source_id=SOURCE_ID,
            )

    token = get_settings().travelpayouts_token
    if not token:
        raise SourceError(
            SourceErrorKind.AUTHENTICATION,
            "TRAVELPAYOUTS_TOKEN is not configured",
            source_id=SOURCE_ID,
        )

    retrieved_at = datetime.now(UTC)
    raw = await fetch(
        PriceCalendarRequest(origin=origin, destination=destination, depart_date=depart_month),
        token,
    )

    # Committed in its own transaction, before normalization runs: a
    # SCHEMA_CHANGE or other normalization failure below must not roll back
    # the raw payload along with it — an unparseable payload today is
    # exactly the case spec §4's reprocessing guarantee exists for (issue
    # #52).
    request_key = f"{origin}-{destination}:{depart_month}"
    async with session_scope() as db:
        await store_raw_payload(
            db,
            source="travelpayouts",
            request_key=request_key,
            payload=raw,
            retrieved_at=retrieved_at,
        )

    return normalize_price_calendar(
        raw, origin_timezone=origin_timezone, currency="eur", retrieved_at=retrieved_at
    )
