#!/bin/sh
# Runs once, on first init of an empty data volume, after 00-schema.sql.
# schema.sql creates role lca_app with a placeholder password; replace it
# with LCA_APP_PASSWORD from the environment.
set -eu

if [ -z "${LCA_APP_PASSWORD:-}" ]; then
    echo "10-app-password.sh: LCA_APP_PASSWORD is empty" >&2
    exit 1
fi

# psql variable + :'var' quoting escapes the password safely
psql -v ON_ERROR_STOP=1 -v app_pw="$LCA_APP_PASSWORD" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
ALTER ROLE lca_app WITH PASSWORD :'app_pw';
SQL

echo "10-app-password.sh: lca_app password set"
