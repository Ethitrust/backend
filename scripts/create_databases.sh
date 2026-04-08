#!/bin/sh
set -e

# PostgreSQL is running on localhost inside the container
# No need to wait - just use localhost
POSTGRES_USER="${POSTGRES_USER:-postgres}"
export PGPASSWORD="${POSTGRES_PASSWORD:-postgres}"

# Simple wait with a timeout
echo "Waiting for PostgreSQL to be ready..."
for i in $(seq 1 30); do
    if pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" > /dev/null 2>&1; then
        echo "PostgreSQL is ready!"
        break
    fi
    echo "Waiting... ($i/30)"
    sleep 1
    if [ $i -eq 30 ]; then
        echo "Timeout waiting for PostgreSQL"
        exit 1
    fi
done

DATABASES_RAW="${POSTGRES_MULTIPLE_DATABASES:-ethitrust_core,ethitrust_auth,ethitrust_user,ethitrust_wallet,ethitrust_escrow,ethitrust_payment_link,ethitrust_payout,ethitrust_kyc,ethitrust_dispute,ethitrust_notification,ethitrust_audit,ethitrust_fee,ethitrust_organization,ethitrust_admin,ethitrust_webhook}"

echo "Creating databases..."
for db in $(echo "$DATABASES_RAW" | tr ',' ' '); do
    [ -z "$db" ] && continue

    # Check if database exists
    exists=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" 2>/dev/null || echo "")

    if [ "$exists" = "1" ]; then
        echo "Database already exists: $db"
    else
        echo "Creating database: $db"
        psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE \"$db\";"
    fi
    
    psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres -c "GRANT ALL PRIVILEGES ON DATABASE \"$db\" TO \"$POSTGRES_USER\";"
done

echo "All databases created successfully!"