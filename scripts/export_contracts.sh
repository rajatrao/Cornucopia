#!/usr/bin/env bash
# Shared API contracts: FastAPI's OpenAPI document -> contracts/openapi.json
# -> generated TypeScript types for the frontend.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$ROOT/backend" && CORNUCOPIA_TRANSPORT=memory uv run --quiet python -c "
import json
from cornucopia.api.app import create_app
from cornucopia.config import Settings
app = create_app(Settings(CORNUCOPIA_TRANSPORT='memory', _env_file=None))
print(json.dumps(app.openapi(), indent=2, sort_keys=True))
") > "$ROOT/contracts/openapi.json"
(cd "$ROOT/frontend" && npx openapi-typescript ../contracts/openapi.json -o src/lib/api/contract.gen.ts >/dev/null)
echo "contracts updated"
