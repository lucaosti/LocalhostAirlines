"""Full multi-origin/destination search resource (docs/api.md §5, §7; spec
§27, §29, §31, §32).

Creation only expands the search space and computes its size (`space_total`)
synchronously — the source calls themselves are enqueued, never run inline
(CLAUDE.md §6: "no user request ever blocks on a browser [or source call]").
The actual expansion -> batching -> budget -> fetch -> gate -> filter pipeline
runs in apps/worker/jobs/travelpayouts_search.py.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime

from arq import ArqRedis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.dependencies import get_current_user
from apps.api.dependencies import get_arq_pool, get_session
from apps.api.errors import NotFoundProblem
from domain.flight.serialization import offer_from_dict
from domain.search.expansion import SearchQuery, WeightedLocation, expand
from infrastructure.postgres.models import User
from infrastructure.postgres.models_search import CashObservation, Search, SearchState
from infrastructure.schema import UtcDatetime
from infrastructure.settings import get_settings

router = APIRouter(prefix="/searches", tags=["searches"])

_IATA = re.compile(r"^[A-Z]{3}$")


class LocationIn(BaseModel):
    code: str = Field(min_length=3, max_length=3)
    weight: int = Field(default=0, ge=0, le=100)

    @field_validator("code")
    @classmethod
    def iata_uppercase(cls, v: str) -> str:
        v = v.upper()
        if not _IATA.match(v):
            raise ValueError(f"'{v}' is not a 3-letter IATA code")
        return v


class BudgetIn(BaseModel):
    calls: int = Field(gt=0)


class SearchIn(BaseModel):
    traveller_profile_id: str | None = None
    origins: list[LocationIn] = Field(min_length=1)
    destinations: list[LocationIn] = Field(min_length=1)
    date_start: date
    date_end: date
    min_nights: int = Field(ge=0)
    max_nights: int = Field(ge=0)
    cabins: list[str] = Field(min_length=1)
    max_stops: int | None = Field(default=None, ge=0)
    hard_filters: dict = Field(default_factory=dict)
    budget: BudgetIn | None = None

    @model_validator(mode="after")
    def date_range_is_ordered(self) -> SearchIn:
        if self.date_end < self.date_start:
            raise ValueError("date_end must not be before date_start")
        return self

    @model_validator(mode="after")
    def nights_range_is_ordered(self) -> SearchIn:
        if self.max_nights < self.min_nights:
            raise ValueError("max_nights must not be less than min_nights")
        return self


class SpaceOut(BaseModel):
    total: int
    explored: int
    not_explored: int


class BudgetOut(BaseModel):
    calls: int
    spent: int
    remaining: int


class SourceOut(BaseModel):
    source: str
    state: str
    results: int
    reason: dict | None = None


class SearchResponse(BaseModel):
    id: str
    state: str
    created_at: UtcDatetime
    completed_at: UtcDatetime | None
    space: SpaceOut
    budget: BudgetOut
    sources: list[SourceOut]
    result_count: int
    failure_reason: str | None


def _to_response(search: Search, *, result_count: int) -> SearchResponse:
    return SearchResponse(
        id=str(search.id),
        state=search.state.value,
        created_at=search.created_at,
        completed_at=search.completed_at,
        space=SpaceOut(
            total=search.space_total,
            explored=search.space_explored,
            not_explored=search.space_total - search.space_explored,
        ),
        budget=BudgetOut(
            calls=search.budget_calls,
            spent=search.budget_spent,
            remaining=search.budget_calls - search.budget_spent,
        ),
        sources=[SourceOut(**source) for source in search.sources],
        result_count=result_count,
        failure_reason=search.failure_reason,
    )


@router.post("", status_code=202, response_model=SearchResponse)
async def create_search(
    body: SearchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> SearchResponse:
    budget_calls = body.budget.calls if body.budget else get_settings().default_search_budget_calls

    query = SearchQuery(
        origins=tuple(WeightedLocation(loc.code, loc.weight) for loc in body.origins),
        destinations=tuple(WeightedLocation(loc.code, loc.weight) for loc in body.destinations),
        date_start=body.date_start,
        date_end=body.date_end,
        min_nights=body.min_nights,
        max_nights=body.max_nights,
        cabins=tuple(body.cabins),
    )
    space_total = len(expand(query))

    traveller_profile_uuid = None
    if body.traveller_profile_id is not None:
        try:
            traveller_profile_uuid = uuid.UUID(body.traveller_profile_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid traveller_profile_id") from exc

    search = Search(
        id=uuid.uuid4(),
        user_id=user.id,
        traveller_profile_id=traveller_profile_uuid,
        origins=[{"code": loc.code, "weight": loc.weight} for loc in body.origins],
        destinations=[{"code": loc.code, "weight": loc.weight} for loc in body.destinations],
        date_start=body.date_start,
        date_end=body.date_end,
        min_nights=body.min_nights,
        max_nights=body.max_nights,
        cabins=list(body.cabins),
        max_stops=body.max_stops,
        hard_filters=body.hard_filters,
        budget_calls=budget_calls,
        budget_spent=0,
        space_total=space_total,
        space_explored=0,
        sources=[],
        state=SearchState.PENDING,
        created_at=datetime.now(UTC),
    )
    db.add(search)
    await db.commit()

    # Enqueued, never run inline — no user request ever blocks on a source
    # call (CLAUDE.md §6, "Headless jobs are enqueued only by the scheduler
    # or an explicit verification request — never synchronously from an HTTP
    # handler"; a search trigger is exactly that explicit request).
    await arq_pool.enqueue_job("run_travelpayouts_search", str(search.id))

    return _to_response(search, result_count=0)


@router.get("/{search_id}", response_model=SearchResponse)
async def get_search(
    search_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> SearchResponse:
    search = await _get_owned_search(db, search_id, user)
    result_count = await _count_results(db, search)
    return _to_response(search, result_count=result_count)


class ObservationResponse(BaseModel):
    itinerary_id: str
    source: str
    price: dict
    freshness: str
    confidence: str
    retrieved_at: UtcDatetime
    slices: list[dict]
    limitations: list[str]


@router.get("/{search_id}/results", response_model=list[ObservationResponse])
async def get_search_results(
    search_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[ObservationResponse]:
    search = await _get_owned_search(db, search_id, user)  # 404/403 before leaking results
    rows = await _fetch_result_rows(db, search)

    results = []
    for row in rows:
        offer = offer_from_dict(row.offer)
        results.append(
            ObservationResponse(
                itinerary_id=offer.itinerary_id,
                source=offer.source,
                # docs/api.md §3 provenance envelope, applied to price: the
                # source stated this value directly (AVAILABLE), so `state`
                # is fixed here rather than modelled as a field — the other
                # three states arise from a source failing to answer at all,
                # which for a stored observation already happened upstream
                # (the row would simply not exist).
                price={
                    "value": {"amount_minor": offer.price_minor, "currency": offer.currency},
                    "state": "AVAILABLE",
                    "freshness": offer.freshness.value,
                    "confidence": offer.confidence.value,
                    "source": offer.source,
                    "retrieved_at": offer.retrieved_at.isoformat().replace("+00:00", "Z"),
                },
                freshness=offer.freshness.value,
                confidence=offer.confidence.value,
                retrieved_at=offer.retrieved_at,
                slices=[
                    {
                        "segments": [
                            {
                                "origin": seg.origin,
                                "destination": seg.destination,
                                "departure_utc": seg.departure_utc.isoformat().replace(
                                    "+00:00", "Z"
                                ),
                                "arrival_utc": (
                                    seg.arrival_utc.isoformat().replace("+00:00", "Z")
                                    if seg.arrival_utc
                                    else None
                                ),
                                "marketing_carrier": seg.marketing_carrier,
                                "flight_number": seg.flight_number,
                            }
                            for seg in slice_.segments
                        ]
                    }
                    for slice_ in offer.slices
                ],
                limitations=list(offer.limitations),
            )
        )
    return results


def _route_pairs(search: Search) -> list[tuple[str, str]]:
    return [
        (origin["code"], destination["code"])
        for origin in search.origins
        for destination in search.destinations
    ]


def _month_range(search: Search) -> list[str]:
    months = []
    year, month = search.date_start.year, search.date_start.month
    end_year, end_month = search.date_end.year, search.date_end.month
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


async def _fetch_result_rows(db: AsyncSession, search: Search) -> list[CashObservation]:
    # An observation's identity is (itinerary_id, source), not this search
    # (spec §56) — it outlives any one search, and a scheduled re-collection
    # extends the same row rather than creating a fresh one. "This search's
    # results" means "this search's routes' current observations" within its
    # own date range.
    routes = _route_pairs(search)
    months = _month_range(search)
    if not routes or not months:
        return []

    rows = (
        (await db.execute(select(CashObservation).where(CashObservation.depart_month.in_(months))))
        .scalars()
        .all()
    )
    route_set = set(routes)
    return [row for row in rows if (row.origin, row.destination) in route_set]


async def _count_results(db: AsyncSession, search: Search) -> int:
    return len(await _fetch_result_rows(db, search))


async def _get_owned_search(db: AsyncSession, search_id: str, user: User) -> Search:
    try:
        search_uuid = uuid.UUID(search_id)
    except ValueError as exc:
        raise NotFoundProblem(f"no such search {search_id}") from exc

    search = await db.get(Search, search_uuid)
    if search is None:
        raise NotFoundProblem(f"no such search {search_id}")
    if search.user_id != user.id:
        # 404, not 403 — same "don't confirm existence to a non-owner"
        # posture already established for traveller profiles.
        raise NotFoundProblem(f"no such search {search_id}")
    return search
