#!/bin/sh
set -e

# Wait for PostgreSQL to be ready (only needed for startup script)
until pg_isready -h "${POSTGRES_HOST:-localhost}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-postgres}"; do
    echo "Waiting for PostgreSQL to start..."
    sleep 2
done

# Creates multiple PostgreSQL databases for each microservice.
# Safe to run multiple times (idempotent).
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
export PGPASSWORD="${POSTGRES_PASSWORD:-postgres}"

DATABASES_RAW="${POSTGRES_MULTIPLE_DATABASES:-ethitrust_core,ethitrust_auth,ethitrust_user,ethitrust_wallet,ethitrust_escrow,ethitrust_invoice,ethitrust_payment_link,ethitrust_payout,ethitrust_kyc,ethitrust_dispute,ethitrust_notification,ethitrust_audit,ethitrust_fee,ethitrust_organization,ethitrust_admin}"

for db in $(echo "$DATABASES_RAW" | tr ',' ' '); do
  [ -z "$db" ] && continue

  exists="$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${db}'")"

  if [ "$exists" = "1" ]; then
    echo "Database already exists: $db"
  else
    psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$db\";"
    echo "Created database: $db"
  fi

  psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "GRANT ALL PRIVILEGES ON DATABASE \"$db\" TO \"$POSTGRES_USER\";"
done