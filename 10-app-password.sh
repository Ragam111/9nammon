#!/bin/sh
# Runs once, after 00-schema.sql, on first database creation.
# Replaces the placeholder password of the app role with the one from .env
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    ALTER ROLE lca_app PASSWORD '${LCA_APP_PASSWORD}';
EOSQL
