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
ORG_SLUG="${CORNUCOPIA_ORG_SLUG:-cornucopia-dev}"
ORG_NAME="${CORNUCOPIA_ORG_NAME:-CORNUCOPIA development}"
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
  if ! grep -q '^CORNUCOPIA_API_TOKEN=' \$ENVF; then
    echo \"CORNUCOPIA_API_TOKEN=\$(openssl rand -hex 32)\" >> \$ENVF
    echo 'generated new API token'
  fi
  sed -i '/^SUPABASE_GATEWAY_URL=/d;/^CORNUCOPIA_TRANSPORT=/d;/^CORNUCOPIA_ENV=/d;/^CORNUCOPIA_ORG_/d' \$ENVF
  {
    echo 'CORNUCOPIA_ENV=production'
    echo 'CORNUCOPIA_TRANSPORT=gateway'
    echo 'SUPABASE_GATEWAY_URL=$SUPABASE_GATEWAY_URL'
    echo 'CORNUCOPIA_ORG_SLUG=$ORG_SLUG'
    echo 'CORNUCOPIA_ORG_NAME=$ORG_NAME'
  } >> \$ENVF

  sprite-env services delete cornucopia-api >/dev/null 2>&1 || true
  sprite-env services create cornucopia-api \
    --cmd \$BASE/current/backend/.venv/bin/uvicorn \
    --args cornucopia.main:app,--host,0.0.0.0,--port,8000,--proxy-headers \
    --dir \$BASE/current/backend \
    --http-port 8000 --duration 8s

  # keep the 3 newest releases
  ls -1dt \$BASE/releases/* | tail -n +4 | xargs -r rm -rf
"

echo "==> smoke test inside the Sprite"
sprite exec -s "$SPRITE" --no-stdin -- bash -c 'curl -fsS localhost:8000/health; echo'
echo "==> deployed $REL"
