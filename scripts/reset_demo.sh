#!/usr/bin/env bash
# Manually reset the public demo to a clean starting point.
#
#   scripts/reset_demo.sh
#
# Nothing is deleted: the event journal, audit log and plan history are
# append-only by design. Instead, the Sprite is pointed at a brand-new
# demonstration organization, the same operator accounts are recreated in it
# (passwords from the gitignored .env.operators), and the Thanksgiving sample
# data is loaded through the public API. Previous demo runs stay in the
# database under their own organizations.
#
# Requires: sprite CLI (logged in), uv, and .env.operators with
#   CN_raj_PASSWORD, CN_judge_PASSWORD, CN_judge_viewer_PASSWORD
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SPRITE="${SPRITE:-cornucopia}"
OPS="$ROOT/.env.operators"
[ -f "$OPS" ] || { echo "missing $OPS" >&2; exit 1; }
pw() { grep "^CN_$1_PASSWORD=" "$OPS" | cut -d= -f2-; }

SLUG="thanksgiving-2026-demo-$(date -u +%Y%m%d%H%M)"
NAME="Thanksgiving Community Food Rescue (demonstration data)"

if [ -z "${SUPABASE_GATEWAY_URL:-}" ]; then
  SUPABASE_GATEWAY_URL=$(sprite exec -s "$SPRITE" --no-stdin -- sh -c \
    'curl -s https://api.sprites.dev/v1/gateway/list' | python3 -c \
    'import sys,json; print([c["gateway_base_url"] for c in json.load(sys.stdin)["connections"] if c["provider"]=="supabase"][0])')
fi
export SUPABASE_GATEWAY_URL

echo "==> switching the Sprite to a fresh organization: $SLUG"
CORNUCOPIA_ORG_SLUG="$SLUG" CORNUCOPIA_ORG_NAME="$NAME" "$ROOT/scripts/deploy_sprite.sh" >/dev/null

echo "==> recreating operator accounts"
for spec in "raj:Raj:admin:raj" "judge:Hackathon Judge:approver:judge" "judge-viewer:Judge (read-only):viewer:judge_viewer"; do
  IFS=: read -r user name role key <<< "$spec"
  secret="$(pw "$key")"
  [ -n "$secret" ] || { echo "no password for $user in $OPS, skipping"; continue; }
  printf '%s\n' "$secret" | sprite exec -s "$SPRITE" --stdin -- bash -c \
    "cd /home/sprite/cornucopia/current/backend && .venv/bin/python -m cornucopia.admin create-operator --username $user --name '$name' --role $role --password-stdin" | tail -1
done

echo "==> loading the Thanksgiving sample data"
PORT=18765
sprite proxy -s "$SPRITE" "$PORT:8000" >/dev/null 2>&1 &
PROXY=$!
trap 'kill $PROXY 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -s -o /dev/null "localhost:$PORT/health" && break; sleep 1; done
TOKEN=$(sprite exec -s "$SPRITE" --no-stdin -- sh -c 'grep ^CORNUCOPIA_API_TOKEN= ~/.config/cornucopia/cornucopia.env | cut -d= -f2')
CORNUCOPIA_API_URL="http://localhost:$PORT" CORNUCOPIA_API_TOKEN="$TOKEN" \
CORNUCOPIA_USERNAME=raj CORNUCOPIA_PASSWORD="$(pw raj)" \
  uv run --quiet --project "$ROOT/backend" python "$ROOT/scripts/seed_sample.py" --label "" --quinoa-lb 130

echo "==> demo reset complete: $SLUG"
