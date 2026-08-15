"""extend searches to the full multi-origin/destination query model

Revision ID: 9c1a4f2e7d3b
Revises: 7fa84f663103
Create Date: 2026-08-15 14:02:11.000000

Replaces `searches`' single origin/destination/depart_month columns with the
full docs/api.md §5 "Create" shape: origins/destinations as JSON weighted-
location arrays, a date range and nights range instead of one month, cabins,
max_stops, hard_filters, a budget, and the computed space/sources columns
"Retrieve" reports. Every existing row is a walking-skeleton search with no
successor once this lands (pre-production, per CLAUDE.md's stated current
state), so the old columns are dropped rather than migrated forward.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9c1a4f2e7d3b"
down_revision: str | None = "7fa84f663103"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("searches", "origin")
    op.drop_column("searches", "destination")
    op.drop_column("searches", "depart_month")

    op.add_column(
        "searches",
        sa.Column(
            "traveller_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("traveller_profiles.id"),
            nullable=True,
        ),
    )
    op.add_column("searches", sa.Column("origins", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column(
        "searches", sa.Column("destinations", sa.JSON(), nullable=False, server_default="[]")
    )
    op.add_column("searches", sa.Column("date_start", sa.Date(), nullable=False))
    op.add_column("searches", sa.Column("date_end", sa.Date(), nullable=False))
    op.add_column(
        "searches", sa.Column("min_nights", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "searches", sa.Column("max_nights", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("searches", sa.Column("cabins", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("searches", sa.Column("max_stops", sa.Integer(), nullable=True))
    op.add_column(
        "searches", sa.Column("hard_filters", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column(
        "searches", sa.Column("budget_calls", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "searches", sa.Column("budget_spent", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "searches", sa.Column("space_total", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "searches", sa.Column("space_explored", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("searches", sa.Column("sources", sa.JSON(), nullable=False, server_default="[]"))

    # PENDING/RUNNING/READY/FAILED already existed; PARTIAL is new (spec §29,
    # reachable once a second source exists). The Postgres enum stores each
    # Python Enum member's NAME (e.g. "PENDING"), not its lowercase .value —
    # that is how the original searches migration defined it, so the added
    # label has to match that casing, not SearchState.PARTIAL.value.
    # ALTER TYPE ... ADD VALUE cannot run inside the transaction Alembic
    # wraps migrations in by default, so autocommit is required here.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE searchstate ADD VALUE IF NOT EXISTS 'PARTIAL'")


def downgrade() -> None:
    op.drop_column("searches", "sources")
    op.drop_column("searches", "space_explored")
    op.drop_column("searches", "space_total")
    op.drop_column("searches", "budget_spent")
    op.drop_column("searches", "budget_calls")
    op.drop_column("searches", "hard_filters")
    op.drop_column("searches", "max_stops")
    op.drop_column("searches", "cabins")
    op.drop_column("searches", "max_nights")
    op.drop_column("searches", "min_nights")
    op.drop_column("searches", "date_end")
    op.drop_column("searches", "date_start")
    op.drop_column("searches", "destinations")
    op.drop_column("searches", "origins")
    op.drop_column("searches", "traveller_profile_id")

    op.add_column(
        "searches", sa.Column("origin", sa.String(4), nullable=False, server_default="XXX")
    )
    op.add_column(
        "searches", sa.Column("destination", sa.String(4), nullable=False, server_default="XXX")
    )
    op.add_column(
        "searches",
        sa.Column("depart_month", sa.String(7), nullable=False, server_default="2026-01"),
    )
    # SearchState.PARTIAL cannot be removed from the Postgres enum type
    # (dropping an enum value requires rebuilding the type and everything
    # that references it) — a downgrade leaves it defined but unreachable,
    # the same tradeoff Postgres itself forces on every ADD VALUE.
