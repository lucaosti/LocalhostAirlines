"""Traveller profiles and companion relationships (spec §8, §9; docs/api.md §8).

Every traveller profile belongs to the authenticated user; there is no
cross-user visibility at this stage. `search-profiles` (spec §10, saved
search presets) is deliberately not implemented here — it is closely enough
tied to the search engine itself that modelling it before M3 exists would be
guessing at a shape, not building one.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth.dependencies import get_current_user
from apps.api.dependencies import get_session
from apps.api.errors import ConflictProblem, NotFoundProblem, UnprocessableProblem
from infrastructure.postgres.models import (
    PointsRelationship,
    TravellerProfile,
    TravellerRelationship,
    User,
)
from infrastructure.schema import UtcDatetime

router = APIRouter(prefix="/travellers", tags=["travellers"])


class WeightedAirport(BaseModel):
    code: str = Field(min_length=3, max_length=4)
    weight: int = Field(default=0, ge=0, le=100)


class TravellerProfileIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=128)
    # Nationality and residence are independent fields (spec §8): the
    # requirement engine needs the passport, some fare/residency rules need
    # residence, and conflating them produces wrong visa answers for anyone
    # living abroad.
    passport_countries: list[str] = Field(min_length=1)
    residence_country: str | None = None
    home_airports: list[WeightedAirport] = Field(default_factory=list)
    preferred_airports: list[WeightedAirport] = Field(default_factory=list)
    preferred_airlines: list[str] = Field(default_factory=list)
    preferred_alliances: list[str] = Field(default_factory=list)
    excluded_airlines: list[str] = Field(default_factory=list)
    preferred_cabins: list[str] = Field(default_factory=list)
    maximum_stops: int | None = Field(default=None, ge=0)
    maximum_trip_duration_days: int | None = Field(default=None, ge=1)

    @field_validator("passport_countries")
    @classmethod
    def passport_codes_are_alpha2(cls, v: list[str]) -> list[str]:
        for code in v:
            if len(code) != 2 or not code.isalpha():
                raise ValueError(f"'{code}' is not an ISO 3166-1 alpha-2 country code")
        return [c.upper() for c in v]


class TravellerProfileResponse(BaseModel):
    id: str
    user_id: str
    display_name: str
    passport_countries: list[str]
    residence_country: str | None
    home_airports: list[WeightedAirport]
    preferred_airports: list[WeightedAirport]
    preferred_airlines: list[str]
    preferred_alliances: list[str]
    excluded_airlines: list[str]
    preferred_cabins: list[str]
    maximum_stops: int | None
    maximum_trip_duration_days: int | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


def _to_response(t: TravellerProfile) -> TravellerProfileResponse:
    return TravellerProfileResponse(
        id=str(t.id),
        user_id=str(t.user_id),
        display_name=t.display_name,
        passport_countries=t.passport_countries,
        residence_country=t.residence_country,
        home_airports=[WeightedAirport(**a) for a in t.home_airports],
        preferred_airports=[WeightedAirport(**a) for a in t.preferred_airports],
        preferred_airlines=t.preferred_airlines,
        preferred_alliances=t.preferred_alliances,
        excluded_airlines=t.excluded_airlines,
        preferred_cabins=t.preferred_cabins,
        maximum_stops=t.maximum_stops,
        maximum_trip_duration_days=t.maximum_trip_duration_days,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


async def _get_owned_traveller(db: AsyncSession, traveller_id: str, user: User) -> TravellerProfile:
    try:
        parsed_id = uuid.UUID(traveller_id)
    except ValueError as exc:
        raise NotFoundProblem("no such traveller profile") from exc

    traveller = await db.get(TravellerProfile, parsed_id)
    # 404, not 403, for both "doesn't exist" and "not yours" — the
    # distinction would let one user enumerate another's traveller ids.
    if traveller is None or traveller.user_id != user.id:
        raise NotFoundProblem("no such traveller profile")
    return traveller


@router.get("", response_model=list[TravellerProfileResponse])
async def list_travellers(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[TravellerProfileResponse]:
    result = await db.execute(select(TravellerProfile).where(TravellerProfile.user_id == user.id))
    return [_to_response(t) for t in result.scalars().all()]


@router.post("", response_model=TravellerProfileResponse, status_code=201)
async def create_traveller(
    body: TravellerProfileIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TravellerProfileResponse:
    now = datetime.now(UTC)
    traveller = TravellerProfile(
        id=uuid.uuid4(),
        user_id=user.id,
        display_name=body.display_name,
        passport_countries=body.passport_countries,
        residence_country=body.residence_country,
        home_airports=[a.model_dump() for a in body.home_airports],
        preferred_airports=[a.model_dump() for a in body.preferred_airports],
        preferred_airlines=body.preferred_airlines,
        preferred_alliances=body.preferred_alliances,
        excluded_airlines=body.excluded_airlines,
        preferred_cabins=body.preferred_cabins,
        maximum_stops=body.maximum_stops,
        maximum_trip_duration_days=body.maximum_trip_duration_days,
        created_at=now,
        updated_at=now,
    )
    db.add(traveller)
    await db.commit()
    await db.refresh(traveller)
    return _to_response(traveller)


@router.get("/{traveller_id}", response_model=TravellerProfileResponse)
async def get_traveller(
    traveller_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TravellerProfileResponse:
    traveller = await _get_owned_traveller(db, traveller_id, user)
    return _to_response(traveller)


@router.patch("/{traveller_id}", response_model=TravellerProfileResponse)
async def update_traveller(
    traveller_id: str,
    body: TravellerProfileIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TravellerProfileResponse:
    traveller = await _get_owned_traveller(db, traveller_id, user)
    traveller.display_name = body.display_name
    traveller.passport_countries = body.passport_countries
    traveller.residence_country = body.residence_country
    traveller.home_airports = [a.model_dump() for a in body.home_airports]
    traveller.preferred_airports = [a.model_dump() for a in body.preferred_airports]
    traveller.preferred_airlines = body.preferred_airlines
    traveller.preferred_alliances = body.preferred_alliances
    traveller.excluded_airlines = body.excluded_airlines
    traveller.preferred_cabins = body.preferred_cabins
    traveller.maximum_stops = body.maximum_stops
    traveller.maximum_trip_duration_days = body.maximum_trip_duration_days
    traveller.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(traveller)
    return _to_response(traveller)


@router.delete("/{traveller_id}", status_code=204)
async def delete_traveller(
    traveller_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    traveller = await _get_owned_traveller(db, traveller_id, user)
    await db.delete(traveller)
    await db.commit()


# --- Companion relationships -------------------------------------------------


class CompanionIn(BaseModel):
    companion_id: str
    # No default. Omitting this field is a 422, not a silent NOT_COMBINABLE —
    # the safe default must be a decision the caller makes, not one the API
    # makes for them (spec §9).
    points_relationship: PointsRelationship


class CompanionResponse(BaseModel):
    id: str
    traveller_id: str
    companion_id: str
    points_relationship: PointsRelationship
    created_at: UtcDatetime


@router.get("/{traveller_id}/companions", response_model=list[CompanionResponse])
async def list_companions(
    traveller_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[CompanionResponse]:
    traveller = await _get_owned_traveller(db, traveller_id, user)
    result = await db.execute(
        select(TravellerRelationship).where(TravellerRelationship.traveller_id == traveller.id)
    )
    return [
        CompanionResponse(
            id=str(r.id),
            traveller_id=str(r.traveller_id),
            companion_id=str(r.companion_id),
            points_relationship=r.points_relationship,
            created_at=r.created_at,
        )
        for r in result.scalars().all()
    ]


@router.post("/{traveller_id}/companions", response_model=CompanionResponse, status_code=201)
async def add_companion(
    traveller_id: str,
    body: CompanionIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CompanionResponse:
    traveller = await _get_owned_traveller(db, traveller_id, user)

    try:
        companion_uuid = uuid.UUID(body.companion_id)
    except ValueError as exc:
        raise UnprocessableProblem("companion_id is not a valid identifier") from exc

    if companion_uuid == traveller.id:
        raise UnprocessableProblem("a traveller cannot be their own companion")

    companion = await db.get(TravellerProfile, companion_uuid)
    if companion is None:
        raise UnprocessableProblem("companion_id does not refer to an existing traveller")

    relationship = TravellerRelationship(
        id=uuid.uuid4(),
        traveller_id=traveller.id,
        companion_id=companion.id,
        points_relationship=body.points_relationship,
        created_at=datetime.now(UTC),
    )
    db.add(relationship)
    try:
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — surfaced as a clean conflict below
        await db.rollback()
        raise ConflictProblem("this companion relationship already exists") from exc

    await db.refresh(relationship)
    return CompanionResponse(
        id=str(relationship.id),
        traveller_id=str(relationship.traveller_id),
        companion_id=str(relationship.companion_id),
        points_relationship=relationship.points_relationship,
        created_at=relationship.created_at,
    )
