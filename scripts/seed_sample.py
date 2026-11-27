"""Seed a clearly labelled SAMPLE Thanksgiving operation through the public API.

Everything goes through the same validated endpoints the UI uses (resources
CRUD + operational events), so seeded data is audited like any other change.
Idempotent: existing records (matched by name) are reused, donation events
use fixed idempotency keys.

    CORNUCOPIA_API_URL=http://localhost:8000 CORNUCOPIA_API_TOKEN=... \
    CORNUCOPIA_USERNAME=raj CORNUCOPIA_PASSWORD=... \
      uv run --project backend python scripts/seed_sample.py --label "[sample] "

This is demonstration data. It must only be loaded into a development or
demonstration organization.
"""

from __future__ import annotations

import argparse
import os

import httpx

from cornucopia.demo.seed import SeedError, seed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="[sample] ", help="prefix for every seeded name")
    ap.add_argument("--day", default=None, help="service date YYYY-MM-DD (default: tomorrow)")
    ap.add_argument("--quinoa-lb", default="40", help="pantry quinoa donated by the grocer")
    args = ap.parse_args()
    base = os.environ.get("CORNUCOPIA_API_URL", "http://localhost:8000").rstrip("/")
    token = os.environ["CORNUCOPIA_API_TOKEN"]
    http = httpx.Client(base_url=f"{base}/api/v1", timeout=60,
                        # fresh connection per request: long-lived keep-alive
                        # connections through the Sprite URL proxy can stall
                        limits=httpx.Limits(max_keepalive_connections=0),
                        headers={"Authorization": f"Bearer {token}"})
    login = http.post("/auth/login", json={"username": os.environ["CORNUCOPIA_USERNAME"],
                                           "password": os.environ["CORNUCOPIA_PASSWORD"]})
    if login.is_error:
        raise SystemExit(f"sign-in failed: {login.status_code}")
    http.headers["X-Cornucopia-Session"] = login.json()["token"]
    try:
        print("seeded.", seed(http, label=args.label, quinoa_lb=args.quinoa_lb, day_iso=args.day))
    except SeedError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
