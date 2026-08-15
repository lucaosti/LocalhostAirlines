"""M1 walking-skeleton search: one source, one route (docs/api.md §5, §7).

Deliberately not the full search resource from docs/api.md §5 — no
multi-origin/destination expansion, no query budget, no SSE. Those are the
M3 extension of this same resource (docs/api.md §5's own "extended through
M3" tag), built once the search engine that needs them exists. This is the
thin M1 slice: one origin, one destination, one month, one source.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from arq import ArqRedis
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.dependencies import get_current_user
from apps.api.dependencies import get_arq_pool, get_session
from apps.api.errors import NotFoundProblem
from domain.flight.serialization import offer_from_dict
from infrastructure.postgres.models import User
from infrastructure.postgres.models_search import CashObservation, Search, SearchState
from infrastructure.schema import UtcDatetime

router = APIRouter(prefix="/searches", tags=["searches"])

_IATA = re.compile(r"^[A-Z]{3}$")
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class SearchIn(BaseModel):
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    depart_month: str

    @field_validator("origin", "destination")
    @classmethod
    def iata_uppercase(cls, v: str) -> str:
        v = v.upper()
        if not _IATA.match(v):
            raise ValueError(f"'{v}' is not a 3-letter IATA code")
        return v

    @field_validator("depart_month")
    @classmethod
    def month_shape(cls, v: str) -> str:
        if not _MONTH.match(v):
            raise ValueError(f"'{v}' is not a YYYY-MM month")
        return v


class SearchResponse(BaseModel):
    id: str
    state: str
    origin: str
    destination: str
    depart_month: str
    failure_reason: str | None
    created_at: UtcDatetime
    completed_at: UtcDatetime | None


def _to_response(search: Search) -> SearchResponse:
    return SearchResponse(
        id=str(search.id),
        state=search.state.value,
        origin=search.origin,
        destination=search.destination,
        depart_month=search.depart_month,
        failure_reason=search.failure_reason,
        created_at=search.created_at,
        completed_at=search.completed_at,
    )


@router.post("", status_code=202, response_model=SearchResponse)
async def create_search(
    body: SearchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    arq_pool: ArqRedis = Depends(get_arq_pool),
) -> SearchResponse:
    search = Search(
        id=uuid.uuid4(),
        user_id=user.id,
        origin=body.origin,
        destination=body.destination,
        depart_month=body.depart_month,
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

    return _to_response(search)


@router.get("/{search_id}", response_model=SearchResponse)
async def get_search(
    search_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> SearchResponse:
    search = await _get_owned_search(db, search_id, user)
    return _to_response(search)


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

    # Queried by route, not by search_id: an observation's identity is
    # (itinerary_id, source) and it outlives any one Search — a scheduled
    # re-collection extends the same row rather than creating a fresh one
    # tied to its own run. "This search's results" means "this route's
    # current observations".
    rows = (
        (
            await db.execute(
                select(CashObservation).where(
                    CashObservation.origin == search.origin,
                    CashObservation.destination == search.destination,
                    CashObservation.depart_month == search.depart_month,
                )
            )
        )
        .scalars()
        .all()
    )

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
