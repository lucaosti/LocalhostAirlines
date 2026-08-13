"""Structural checks on the ORM models that don't need a database — that every
instant column is timezone-aware, and that no naive DateTime slips in (spec §12).
"""

from sqlalchemy import DateTime, inspect

from infrastructure.postgres.models import (
    TravellerProfile,
    TravellerRelationship,
    User,
    UserSession,
)

MODELS = [User, UserSession, TravellerProfile, TravellerRelationship]


def test_every_datetime_column_is_timezone_aware() -> None:
    for model in MODELS:
        for column in inspect(model).columns:
            if isinstance(column.type, DateTime):
                assert column.type.timezone is True, (
                    f"{model.__name__}.{column.name} is a naive DateTime; "
                    "spec §12 requires timestamptz throughout"
                )


def test_traveller_relationship_requires_explicit_points_relationship() -> None:
    # No default is set on the column: creating a row without the value fails
    # at the database level, not silently. Verified structurally here; the API
    # layer (issue #13) enforces the same requirement one layer up.
    column = inspect(TravellerRelationship).columns["points_relationship"]
    assert column.default is None
    assert column.nullable is False
