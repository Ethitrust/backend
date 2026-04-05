#!/bin/bash
set -e
# Creates multiple PostgreSQL databases for each microservice
DATABASES="ethitrust_core ethitrust_auth ethitrust_user ethitrust_wallet ethitrust_escrow ethitrust_invoice ethitrust_payment_link ethitrust_payout ethitrust_kyc ethitrust_dispute ethitrust_notification ethitrust_audit ethitrust_fee ethitrust_organization"
for db in $DATABASES; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE $db;
    GRANT ALL PRIVILEGES ON DATABASE $db TO $POSTGRES_USER;
EOSQL
  echo "Created database: $db"
done
