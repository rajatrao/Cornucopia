#!/usr/bin/env bash
# Reproducibility check: apply every supabase/migrations/*.sql, in order, to two
# fresh scratch databases on a LOCAL Postgres and require identical schemas.
#   PGHOST=localhost PGPORT=54329 PGUSER=postgres scripts/verify_migrations_local.sh
# Needs roles anon, authenticated, service_role to exist (as on Supabase).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
psqlq() { psql -v ON_ERROR_STOP=1 -q "$@"; }
for db in cn_repro_a cn_repro_b; do
  psqlq -d postgres -c "drop database if exists $db" -c "create database $db"
  for f in "$ROOT"/supabase/migrations/*.sql; do
    psqlq -d "$db" -1 -f "$f"
  done
  pg_dump -s -n cornucopia "$db" | grep -v -E '^\\(un)?restrict' > "$TMP/$db.sql"
done
diff -u "$TMP/cn_repro_a.sql" "$TMP/cn_repro_b.sql"
echo "OK: $(ls "$ROOT"/supabase/migrations/*.sql | wc -l | tr -d ' ') migration(s) reproduce an identical schema"
