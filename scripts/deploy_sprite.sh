#!/usr/bin/env bash
# Deploy the CORNUCOPIA backend to a Fly.io Sprite using only documented
# Sprite mechanisms: `sprite file push`, `sprite exec`, `sprite-env services`.
#
#   SPRITE=cornucopia SUPABASE_GATEWAY_URL=https://api.sprites.dev/v1/gateway/supabase/<id> \
#     scripts/deploy_sprite.sh
#
# The Supabase secret key is never sent to the Sprite: the connector gateway
# injects it. The only secret created on the Sprite is the API bearer token,
# generated there on first deploy and kept in a mode-600 file.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SPRITE="${SPRITE:-cornucopia}"
# Which organization this deployment operates (MVP: one per deployment).
# Set CORNUCOPIA_ORG_SLUG to switch organizations; leave it unset on a plain
# code redeploy to keep the current one (including one chosen by an in-app
# demo reset).
ORG_SLUG="${CORNUCOPIA_ORG_SLUG:-}"
ORG_NAME="${CORNUCOPIA_ORG_NAME:-CORNUCOPIA development}"
# Minimum role allowed to reset the demo from the UI (unset: keep current).
RESET_ROLE="${CORNUCOPIA_DEMO_RESET_ROLE:-}"
: "${SUPABASE_GATEWAY_URL:?set SUPABASE_GATEWAY_URL (see CONNECTOR_SETUP.md)}"
REL="$(date -u +%Y%m%dT%H%M%SZ)"
TARBALL="$(mktemp -d)/cornucopia-$REL.tgz"

echo "==> packaging release $REL"
COPYFILE_DISABLE=1 tar --no-xattrs -C "$ROOT" -czf "$TARBALL" \
  --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude '.mypy_cache' --exclude '.ruff_cache' --exclude '.env' --exclude '.env.*' \
  backend

echo "==> uploading"
sprite file push -s "$SPRITE" -p "$TARBALL" "/home/sprite/cornucopia/incoming/$REL.tgz"

echo "==> installing on the Sprite"
sprite exec -s "$SPRITE" --no-stdin -- bash -seuo pipefail -c "
  BASE=/home/sprite/cornucopia
  mkdir -p \$BASE/releases/$REL
  tar -C \$BASE/releases/$REL -xzf \$BASE/incoming/$REL.tgz
  rm -f \$BASE/incoming/$REL.tgz
  cd \$BASE/releases/$REL/backend
  uv sync --frozen --no-dev --quiet
  ln -sfn \$BASE/releases/$REL \$BASE/current

  CONF=/home/sprite/.config/cornucopia
  mkdir -p \$CONF && chmod 700 \$CONF
  ENVF=\$CONF/cornucopia.env
  touch \$ENVF && chmod 600 \$ENVF
  if ! grep -q '^CORNUCOPIA_SESSION_SECRET=' \$ENVF; then
    echo \"CORNUCOPIA_SESSION_SECRET=\$(openssl rand -hex 32)\" >> \$ENVF
    echo 'generated new session signing secret'
  fi
  if ! grep -q '^CORNUCOPIA_API_TOKEN=' \$ENVF; then
    echo \"CORNUCOPIA_API_TOKEN=\$(openssl rand -hex 32)\" >> \$ENVF
    echo 'generated new API token'
  fi
  sed -i '/^SUPABASE_GATEWAY_URL=/d;/^CORNUCOPIA_TRANSPORT=/d;/^CORNUCOPIA_ENV=/d;/^CORNUCOPIA_LOG_FORMAT=/d;/^CORNUCOPIA_ACTIVE_ORG_FILE=/d' \$ENVF
  {
    echo 'CORNUCOPIA_ENV=production'
    echo 'CORNUCOPIA_TRANSPORT=gateway'
    echo 'SUPABASE_GATEWAY_URL=$SUPABASE_GATEWAY_URL'
    echo 'CORNUCOPIA_LOG_FORMAT=json'
    echo \"CORNUCOPIA_ACTIVE_ORG_FILE=\$CONF/active_org.json\"
  } >> \$ENVF
  if [ -n '$ORG_SLUG' ]; then
    sed -i '/^CORNUCOPIA_ORG_/d' \$ENVF
    printf 'CORNUCOPIA_ORG_SLUG=%s\nCORNUCOPIA_ORG_NAME=%s\n' '$ORG_SLUG' '$ORG_NAME' >> \$ENVF
    rm -f \$CONF/active_org.json
  elif ! grep -q '^CORNUCOPIA_ORG_SLUG=' \$ENVF; then
    printf 'CORNUCOPIA_ORG_SLUG=cornucopia-dev\nCORNUCOPIA_ORG_NAME=CORNUCOPIA development\n' >> \$ENVF
  fi
  if [ -n '$RESET_ROLE' ]; then
    sed -i '/^CORNUCOPIA_DEMO_RESET_ROLE=/d' \$ENVF
    echo 'CORNUCOPIA_DEMO_RESET_ROLE=$RESET_ROLE' >> \$ENVF
  fi

  sprite-env services delete cornucopia-api >/dev/null 2>&1 || true
  sprite-env services create cornucopia-api \
    --cmd \$BASE/current/backend/.venv/bin/uvicorn \
    --args cornucopia.main:app,--host,0.0.0.0,--port,8000,--proxy-headers \
    --dir \$BASE/current/backend \
    --http-port 8000 --duration 8s

  # The autonomous agent: its own service, independent of the API and the
  # frontend. Restarted by the Sprite runtime on crash and after cold boots;
  # in-flight work is resumed from Supabase checkpoints via expired leases.
  sprite-env services delete cornucopia-worker >/dev/null 2>&1 || true
  sprite-env services create cornucopia-worker \
    --cmd \$BASE/current/backend/.venv/bin/python \
    --args -m,cornucopia.worker \
    --dir \$BASE/current/backend \
    --duration 6s

  # keep the 3 newest releases
  ls -1dt \$BASE/releases/* | tail -n +4 | xargs -r rm -rf
"

echo "==> smoke test inside the Sprite"
sprite exec -s "$SPRITE" --no-stdin -- bash -c 'curl -fsS localhost:8000/health; echo'
echo "==> deployed $REL"
