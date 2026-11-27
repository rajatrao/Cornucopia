"""Drive the two demonstration scenarios through the public API and print what
the system decided. Nothing is hard-coded: the script reports events exactly
as an operator would and reads back what the agent and optimizer concluded.

  Scenario 1: the rice donation is cancelled (all 500 meals stay committed).
  Scenario 2: the potato stock turns out spoiled (resources are insufficient).

    CORNUCOPIA_API_URL=... CORNUCOPIA_API_TOKEN=... CORNUCOPIA_USERNAME=... \
    CORNUCOPIA_PASSWORD=... uv run --project backend python scripts/run_scenarios.py [--approve]
"""

from __future__ import annotations

import argparse
import os
import time
import uuid
from typing import Any

import httpx

LB = 453.59237


def client() -> httpx.Client:
    base = os.environ.get("CORNUCOPIA_API_URL", "http://localhost:8000").rstrip("/")
    http = httpx.Client(base_url=f"{base}/api/v1", timeout=120,
                        limits=httpx.Limits(max_keepalive_connections=0),
                        headers={"Authorization": f"Bearer {os.environ['CORNUCOPIA_API_TOKEN']}"})
    r = http.post("/auth/login", json={"username": os.environ["CORNUCOPIA_USERNAME"],
                                       "password": os.environ["CORNUCOPIA_PASSWORD"]})
    r.raise_for_status()
    http.headers["X-Cornucopia-Session"] = r.json()["token"]
    return http


def wait_execution(http: httpx.Client, event_id: str, timeout: float = 240) -> dict[str, Any]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        for x in http.get("/agent/executions", params={"limit": 50}).json():
            if x["event_id"] == event_id and x["status"] != "running":
                return dict(x)
        time.sleep(3)
    raise SystemExit("agent did not finish in time")


def report(http: httpx.Client, title: str, event: dict[str, Any]) -> dict[str, Any]:
    print(f"\n=== {title}")
    r = http.post("/events", json={"idempotency_key": f"demo-{uuid.uuid4()}", "event": event})
    r.raise_for_status()
    ev = r.json()["event"]
    print(f"journaled {ev['event_type']} at state v{ev['state_version']}: {ev['effect']}")
    ex = wait_execution(http, ev["id"])
    res = ex.get("result") or {}
    print(f"agent: {ex['status']} (attempt {ex['attempt']}), nodes: {' > '.join(res.get('trail', []))}")
    for line in (res.get("report") or {}).get("lines", []):
        print("  ", line)
    outcome = res.get("outcome") or {}
    for reason in outcome.get("reasons", []):
        print("   escalation:", reason)
    return ex


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--approve", action="store_true", help="approve scenario 1's proposal")
    args = ap.parse_args()
    http = client()

    cc = http.get("/command-center").json()
    print(f"{cc['organization']['name']}: {cc['meals_feasible_now']}/{cc['meals_committed']} meals feasible")

    donation = next(d for d in http.get("/inventory/donations").json()
                    if d["description"].lower().startswith("rice donation") and d["status"] != "cancelled")
    ex = report(http, "Scenario 1: rice donation cancelled", {
        "type": "DONATION_CANCELLED", "donation_id": donation["id"],
        "reason": "The rice donation has been cancelled. All 500 meals remain committed."})
    if ex["status"] == "awaiting_approval" and args.approve:
        req = next(r for r in http.get("/approvals").json() if r["execution_id"] == ex["id"])
        d = http.post(f"/approvals/{req['id']}/decision", json={
            "decision": "approve", "fingerprint": req["fingerprint"],
            "state_version": req["state_version"], "confirm": True,
            "reason": "demo: reviewed the quinoa substitution"})
        print("approval:", d.status_code, d.json())
        t0 = time.time()
        while time.time() - t0 < 180:
            st = http.get(f"/approvals/{req['id']}").json()["request"]["status"]
            if st not in ("approved", "pending"):
                break
            time.sleep(3)
        print("approval request now:", st)
        cc = http.get("/command-center").json()
        print(f"committed plan: {cc['committed_plan']}")

    potatoes = next(i for i in http.get("/resources/ingredients").json()
                    if i["name"].lower() == "potatoes")
    lots = [x for x in http.get("/inventory/lots").json()
            if x["ingredient_id"] == potatoes["id"] and x["status"] == "available"]
    for lot in lots:
        report(http, "Scenario 2: potato stock spoiled (insufficient resources)", {
            "type": "INGREDIENT_EXPIRED", "lot_id": lot["id"],
            "reason": "Cold-storage failure: the potato stock spoiled."})


if __name__ == "__main__":
    main()
