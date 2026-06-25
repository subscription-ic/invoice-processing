#!/usr/bin/env bash
# Container entrypoint. When RUN_MIGRATIONS=true (set on the API container app),
# applies Alembic migrations before launching the given command. Worker/beat
# containers leave it unset and skip straight to their command.
set -e

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "[entrypoint] Running database migrations (alembic upgrade head)..."
  alembic upgrade head || echo "[entrypoint] WARNING: alembic upgrade failed — continuing startup"
fi

if [ "${SEED_DEMO:-false}" = "true" ]; then
  echo "[entrypoint] Seeding demo data (python seed/seed.py)..."
  python /app/seed/seed.py || echo "[entrypoint] WARNING: seed failed — continuing startup"
fi

exec "$@"
