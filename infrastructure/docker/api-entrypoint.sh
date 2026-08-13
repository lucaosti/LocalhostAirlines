#!/bin/sh
# Migrates the database, then execs the container's CMD.
#
# Running migrations from the api container's own startup, rather than as a
# separate deploy step, is a deliberate simplification for a single-host
# personal deployment (spec §6) — not a pattern that would suit a
# multi-replica production system, where migrations must run exactly once,
# not once per replica.
set -eu

echo "Running database migrations..."
alembic upgrade head

exec "$@"
