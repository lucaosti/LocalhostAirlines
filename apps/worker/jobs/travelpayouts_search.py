"""Runs one full multi-origin/destination search end to end: expand -> batch
-> score by information gain -> spend budget -> fetch -> retain raw ->
normalize -> quality gate -> hard-filter -> persist (spec §27-§32, §56).

Still targets Travelpayouts only — the only adopted cash source (spec §20).
Travelpayouts' price-calendar endpoint answers one (origin, destination,
month) combination per call regardless of cabin or trip length
(domain/search/orchestration.py's FetchGroup is built around exactly that),
so the fetch granularity here is coarser than the logical search space the
budget scores against.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from domain.ranking.filters import apply_hard_filters, arrive_before_filter, max_stops_filter
from domain.search.budget import GainWeights, ObservationState, rank_tasks, score_task
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.flight.model import FlightOffer
from domain.quality.gates import QualityGateContext, QualityGateFailure, check_itinerary
from domain.search.expansion import SearchQuery, WeightedLocation, collapse_batchable, expand
from domain.search.orchestration import FetchGroup, collapse_to_fetch_groups, count_space
from infrastructure.postgres.database import session_scope
from infrastructure.postgres.models_reference import Airline, Airport
from infrastructure.postgres.models_search import CashObservation, Search, SearchState
from infrastructure.postgres.observations import write_observation
from infrastructure.postgres.raw_payloads import store_raw_payload
from infrastructure.postgres.source_health import may_call, record_failure, record_success
from infrastructure.settings import get_settings
from normalization.travelpayouts import normalize_price_calendar
from providers.errors import SourceError, SourceErrorKind
from providers.travelpayouts.client import PriceCalendarRequest, fetch_price_calendar

SOURCE_ID = "travelpayouts"

# How far back a route's last observation still counts as "recently seen"
# for the staleness term of the gain formula (domain/search/budget.py).
# Beyond this, a route scores exactly like one observed at the edge of the
# window — a configured shape, not a hardcoded business fact (CLAUDE.md §5),
# chosen to match the same horizon docs/adr/0007's volume estimate assumes.
_MAX_STALENESS_DAYS = 90

_CIRCUIT_RELEVANT = frozenset(
    {
        SourceErrorKind.RATE_LIMIT,
        SourceErrorKind.BLOCKED,
        SourceErrorKind.UPSTREAM_ERROR,
        SourceErrorKind.TIMEOUT,
    }
)

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
        await _run(search_id, _fetch)
    except SourceError as exc:
        # A pre-flight failure — no resolved origin timezone, no token, or
        # the circuit already open before a single call was attempted. The
        # search itself never got to explore anything, which is what
        # SearchState.FAILED means (as opposed to a source that ran and
        # failed partway, recorded in `sources` instead — see _execute).
        logger.warning("travelpayouts search %s failed before running: %s", search_id, exc)
        async with session_scope() as db:
            await record_failure(db, exc.source_id, exc.kind)
            search = await _get_search(db, search_id)
            search.state = SearchState.FAILED
            search.failure_reason = exc.kind.value
            search.completed_at = datetime.now(UTC)
        return


async def _get_search(db: AsyncSession, search_id: str) -> Search:
    search = await db.get(Search, uuid.UUID(search_id))
    if search is None:
        raise RuntimeError(f"search {search_id} disappeared mid-run")
    return search


def _build_query(search: Search) -> SearchQuery:
    return SearchQuery(
        origins=tuple(
            WeightedLocation(loc["code"], loc.get("weight", 0)) for loc in search.origins
        ),
        destinations=tuple(
            WeightedLocation(loc["code"], loc.get("weight", 0)) for loc in search.destinations
        ),
        date_start=search.date_start,
        date_end=search.date_end,
        min_nights=search.min_nights,
        max_nights=search.max_nights,
        cabins=tuple(search.cabins),
    )


async def _run(search_id: str, fetch: Any) -> None:
    async with session_scope() as db:
        search = await _get_search(db, search_id)
        query = _build_query(search)
        all_tasks = expand(query)
        fetch_groups = collapse_to_fetch_groups(collapse_batchable(all_tasks))

        origin_weights = {loc["code"]: loc.get("weight", 0) for loc in search.origins}
        destination_weights = {loc["code"]: loc.get("weight", 0) for loc in search.destinations}

        # One resolved timezone per origin, looked up once for the whole
        # run — same fail-loudly posture as before: a guessed timezone
        # risks a wrong itinerary fingerprint silently (spec §36).
        origin_codes = {group.origin for group in fetch_groups}
        timezones = await _resolve_timezones(db, origin_codes)

        # Checked once, inside the same session as the lookups above, so a
        # currently-open circuit is rejected before a token check or any
        # fetch is even attempted.
        if not await may_call(db, SOURCE_ID):
            raise SourceError(
                SourceErrorKind.BLOCKED,
                "circuit open — recent failures exceeded threshold",
                source_id=SOURCE_ID,
            )

        known_airports = frozenset((await db.execute(select(Airport.iata_code))).scalars().all())
        known_carriers = frozenset(
            code
            for code in (await db.execute(select(Airline.iata_code))).scalars().all()
            if code is not None
        )

        observation_state_by_route = await _lookup_observation_states(
            db, {(group.origin, group.destination) for group in fetch_groups}
        )

        today = datetime.now(UTC).date()
        ranked_groups = _rank_fetch_groups(
            fetch_groups,
            origin_weights=origin_weights,
            destination_weights=destination_weights,
            observation_state_by_route=observation_state_by_route,
            reference_date=today,
        )

        remaining_budget = max(search.budget_calls - search.budget_spent, 0)
        to_attempt = ranked_groups[:remaining_budget]

    token = get_settings().travelpayouts_token
    if not token:
        raise SourceError(
            SourceErrorKind.AUTHENTICATION,
            "TRAVELPAYOUTS_TOKEN is not configured",
            source_id=SOURCE_ID,
        )

    gate_ctx = QualityGateContext(known_airports=known_airports, known_carriers=known_carriers)
    attempted, results, failure_reason = await _execute(
        to_attempt, fetch=fetch, token=token, timezones=timezones, gate_ctx=gate_ctx
    )

    async with session_scope() as db:
        search = await _get_search(db, search_id)
        survivors = _apply_hard_filters(results, search)

        now = datetime.now(UTC)
        for offer, origin, destination, month in survivors:
            # Material-change dedup (spec §56): extends the existing period
            # for this itinerary+source if the price is unchanged, rather
            # than writing a new row per poll — required for percentile
            # correctness once a scheduled re-collection polls the same
            # route daily.
            await write_observation(
                db,
                offer=offer,
                origin=origin,
                destination=destination,
                depart_month=month,
                retrieved_at=offer.retrieved_at,
                search_id=search.id,
            )

        space = count_space(expand(_build_query(search)), attempted)
        search.space_explored = space.explored
        search.budget_spent = search.budget_spent + len(attempted)

        source_state = "failed" if failure_reason else "completed"
        search.sources = [
            {
                "source": SOURCE_ID,
                "state": source_state,
                "results": len(survivors),
                "reason": {"code": failure_reason} if failure_reason else None,
            }
        ]
        search.state = SearchState.READY
        search.completed_at = now

    if failure_reason:
        async with session_scope() as db:
            await record_failure(db, SOURCE_ID, SourceErrorKind(failure_reason))
    else:
        async with session_scope() as db:
            await record_success(db, SOURCE_ID)

    logger.info(
        "travelpayouts search %s: %d/%d fetch groups attempted, %d offers stored",
        search_id,
        len(attempted),
        len(to_attempt),
        len(survivors),
    )


async def _resolve_timezones(db: AsyncSession, origin_codes: set[str]) -> dict[str, str]:
    if not origin_codes:
        return {}
    rows = (
        await db.execute(
            select(Airport.iata_code, Airport.timezone).where(Airport.iata_code.in_(origin_codes))
        )
    ).all()
    timezones = {code: tz for code, tz in rows if tz is not None}
    missing = origin_codes - timezones.keys()
    if missing:
        # Can't proceed correctly for these origins — the itinerary
        # fingerprint needs the origin's local departure date (spec §15),
        # and a guessed timezone risks a wrong one silently (spec §36).
        raise SourceError(
            SourceErrorKind.NOT_AVAILABLE,
            f"no resolved timezone for origin airport(s): {sorted(missing)}",
            source_id=SOURCE_ID,
        )
    return timezones


async def _lookup_observation_states(
    db: AsyncSession, routes: set[tuple[str, str]]
) -> dict[tuple[str, str], ObservationState]:
    """Most recent `last_seen_at` per route, for the budget's staleness term
    (domain/search/budget.py) — the "never observed" case is simply a route
    absent from this dict. Scored at route granularity, not itinerary
    granularity: the itineraries a fetch group would return are not known
    until after it runs, so the best available novelty signal beforehand is
    "have we ever looked at this route at all"."""
    if not routes:
        return {}

    rows = (
        await db.execute(
            select(
                CashObservation.origin,
                CashObservation.destination,
                func.max(CashObservation.last_seen_at),
            )
            .where(CashObservation.source == SOURCE_ID)
            .group_by(CashObservation.origin, CashObservation.destination)
        )
    ).all()
    return {
        (origin, destination): ObservationState(last_observed_at=last_seen.date())
        for origin, destination, last_seen in rows
        if (origin, destination) in routes
    }


def _rank_fetch_groups(
    fetch_groups: list[FetchGroup],
    *,
    origin_weights: dict[str, int],
    destination_weights: dict[str, int],
    observation_state_by_route: dict[tuple[str, str], ObservationState],
    reference_date: date,
    weights: GainWeights = GainWeights(),
) -> list[FetchGroup]:
    # rank_tasks reorders the same ScoredTask objects it is given rather
    # than constructing new ones, so mapping back to their FetchGroup by
    # Python object identity after sorting is safe.
    scored_by_id = {}
    scored_list = []
    for group in fetch_groups:
        task = group.representative_task
        observation = observation_state_by_route.get(
            (group.origin, group.destination), ObservationState(last_observed_at=None)
        )
        scored = score_task(
            task,
            observation,
            origin_weight=origin_weights.get(group.origin, 0),
            destination_weight=destination_weights.get(group.destination, 0),
            reference_date=reference_date,
            max_staleness_days=_MAX_STALENESS_DAYS,
            weights=weights,
        )
        scored_by_id[id(scored)] = group
        scored_list.append(scored)

    ranked = rank_tasks(scored_list, weights)
    return [scored_by_id[id(scored)] for scored in ranked]


async def _execute(
    fetch_groups: list[FetchGroup],
    *,
    fetch: Any,
    token: str,
    timezones: dict[str, str],
    gate_ctx: QualityGateContext,
) -> tuple[list[FetchGroup], list[tuple[FlightOffer, str, str, str]], str | None]:
    """Runs each fetch group's Travelpayouts call in ranked order, stopping
    early on a circuit-relevant or authentication failure rather than
    hammering further calls right after one (spec §21/§25). Returns the
    groups actually attempted (for space/budget accounting — "attempted"
    means "asked", regardless of whether it succeeded), the surviving
    offers with the route/month they came from, and a failure reason.

    The failure reason is set in two cases: the run stopped early (circuit
    or auth), or it ran to completion but produced zero offers with at
    least one route-specific error along the way — surfacing that as
    `sources[].state = "failed"` rather than `"completed"` with a silent
    empty result, which would collapse "errored" and "genuinely nothing
    found" into the same shape (spec P3). A partial success (some offers,
    some route-specific errors) is reported as completed; per-route error
    detail beyond the last one seen is not modelled yet — a single string
    field, not the richer per-fetch-group breakdown this would need to do
    properly with more than one source contributing.
    """
    attempted: list[FetchGroup] = []
    offers: list[tuple[FlightOffer, str, str, str]] = []
    last_route_error: str | None = None

    for group in fetch_groups:
        attempted.append(group)
        request = PriceCalendarRequest(
            origin=group.origin, destination=group.destination, depart_date=group.month
        )
        try:
            retrieved_at = datetime.now(UTC)
            raw = await fetch(request, token)
        except SourceError as exc:
            logger.warning(
                "travelpayouts fetch %s-%s %s failed: %s",
                group.origin,
                group.destination,
                group.month,
                exc,
            )
            if exc.kind is SourceErrorKind.AUTHENTICATION or exc.kind in _CIRCUIT_RELEVANT:
                return attempted, offers, exc.kind.value
            # Route-specific failure (BAD_REQUEST, SCHEMA_CHANGE,
            # NOT_AVAILABLE) — this fetch group yielded nothing, but the
            # rest are still worth trying.
            last_route_error = exc.kind.value
            continue

        request_key = f"{group.origin}-{group.destination}:{group.month}"
        async with session_scope() as db:
            await store_raw_payload(
                db,
                source=SOURCE_ID,
                request_key=request_key,
                payload=raw,
                retrieved_at=retrieved_at,
            )

        try:
            normalized = normalize_price_calendar(
                raw,
                origin_timezone=timezones[group.origin],
                currency=get_settings().base_currency,
                retrieved_at=retrieved_at,
            )
        except SourceError as exc:
            logger.warning(
                "travelpayouts normalize %s-%s %s failed: %s",
                group.origin,
                group.destination,
                group.month,
                exc,
            )
            last_route_error = exc.kind.value
            continue

        for offer in normalized:
            try:
                check_itinerary(offer, gate_ctx)
            except QualityGateFailure as failure:
                logger.info("quality gate rejected %s: %s", offer.offer_id, failure.reason)
                continue
            offers.append((offer, group.origin, group.destination, group.month))

    failure_reason = last_route_error if not offers else None
    return attempted, offers, failure_reason


def _apply_hard_filters(
    results: list[tuple[FlightOffer, str, str, str]], search: Search
) -> list[tuple[FlightOffer, str, str, str]]:
    """Applies the search's max_stops and arrive_before_local hard filters
    (domain/ranking/filters.py, spec §37). `no_self_transfer` is accepted in
    the request but not enforced — the canonical model has no field to tell
    a through-ticketed connection from a self-transfer (documented in
    domain/ranking/filters.py itself); silently ignoring it here rather than
    rejecting the request keeps the request shape stable for when a
    provider eventually normalizes that field in."""
    if not results:
        return results

    filters = []
    if search.max_stops is not None:
        filters.append(max_stops_filter(search.max_stops))
    arrive_before_local = search.hard_filters.get("arrive_before_local")
    if arrive_before_local:
        filters.append(arrive_before_filter(time.fromisoformat(arrive_before_local)))

    if not filters:
        return results

    offers_by_id = {
        offer.offer_id: (offer, origin, destination, month)
        for offer, origin, destination, month in results
    }
    result = apply_hard_filters([offer for offer, *_ in results], filters)
    return [offers_by_id[offer.offer_id] for offer in result.survivors]
