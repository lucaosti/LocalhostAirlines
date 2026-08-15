"""ORM models for the M0 foundation: users, sessions, traveller profiles and
companion relationships.

Two rules from the specification are enforced structurally here, not just by
convention:

- Every instant is `timestamptz` (spec §12). No naive `DateTime` column exists in
  this module; `DateTime(timezone=True)` is used throughout.
- Sessions live in PostgreSQL, not Redis, so that a Redis restart never logs a user
  out (spec §78, correcting the draft that had put them in Redis).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.postgres.base import Base


class Role(enum.StrEnum):
    USER = "USER"
    ADMIN = "ADMIN"


class PointsRelationship(enum.StrEnum):
    """How a companion's points may participate in a redemption (spec §9).

    The default on creation is NOT_COMBINABLE — most programmes forbid pooling,
    and assuming otherwise produces advice the user cannot act on. The API layer
    must require this value explicitly rather than defaulting it silently, so
    the safe default is a decision, not an accident.
    """

    INDIVIDUALLY_USABLE = "INDIVIDUALLY_USABLE"
    TRANSFERABLE = "TRANSFERABLE"
    SHAREABLE = "SHAREABLE"
    NOT_COMBINABLE = "NOT_COMBINABLE"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[Role] = mapped_column(default=Role.USER)
    telegram_user_id: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    traveller_profiles: Mapped[list["TravellerProfile"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    """Server-side session record. The cookie carries only this row's id."""

    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")


class TravellerProfile(Base):
    """A traveller profile (spec §8). Nationality and residence are separate
    fields on purpose: the travel-requirement engine needs the passport, some fare
    and residency rules need residence, and conflating them produces wrong visa
    answers for anyone living abroad.

    A traveller may hold more than one passport, hence `passport_countries` is an
    array rather than a single column.
    """

    __tablename__ = "traveller_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    display_name: Mapped[str] = mapped_column(String(128))
    passport_countries: Mapped[list[str]] = mapped_column(ARRAY(String(2)))
    residence_country: Mapped[str | None] = mapped_column(String(2), nullable=True)

    # Weighted preferences (spec §8, §27): [{"code": "MXP", "weight": 100}, ...].
    # Stored as JSONB rather than a join table — small, read-mostly, and always
    # read as a whole with its owning profile.
    home_airports: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    preferred_airports: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    preferred_airlines: Mapped[list[str]] = mapped_column(ARRAY(String(3)), default=list)
    preferred_alliances: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    excluded_airlines: Mapped[list[str]] = mapped_column(ARRAY(String(3)), default=list)
    preferred_cabins: Mapped[list[str]] = mapped_column(ARRAY(String(16)), default=list)

    maximum_stops: Mapped[int | None] = mapped_column(Integer, nullable=True)
    maximum_trip_duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="traveller_profiles")

    __table_args__ = (
        CheckConstraint("cardinality(passport_countries) >= 1", name="has_at_least_one_passport"),
    )


class TravellerRelationship(Base):
    """A companion relationship between two traveller profiles (spec §9).

    Self-referential to traveller_profiles rather than to users, because the
    relationship is between two specific profiles — a user could in principle
    register more than one profile, and the points relationship is a property of
    the profile pairing, not of the account.
    """

    __tablename__ = "traveller_relationships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    traveller_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("traveller_profiles.id", ondelete="CASCADE"), index=True
    )
    companion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("traveller_profiles.id", ondelete="CASCADE"), index=True
    )
    points_relationship: Mapped[PointsRelationship] = mapped_column()

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    traveller: Mapped[TravellerProfile] = relationship(foreign_keys=[traveller_id])
    companion: Mapped[TravellerProfile] = relationship(foreign_keys=[companion_id])

    __table_args__ = (
        CheckConstraint("traveller_id != companion_id", name="companion_is_not_self"),
        UniqueConstraint("traveller_id", "companion_id", name="uq_traveller_companion_pair"),
    )
