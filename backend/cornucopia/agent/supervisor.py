"""Agent supervisor: claims work by lease, runs the graph, survives restarts.

Lifecycle of one execution:
  1. ``claim_next_execution`` (RPC) hands this worker either a new pending
     event or a running execution whose lease expired (its worker died).
  2. While the graph runs, a heartbeat thread renews the lease and a Sprites
     Tasks API hold keeps the Sprite from pausing mid-run.
  3. The graph checkpoints after every node through the Supabase saver. A
     resumed execution continues from its last checkpoint
     (``graph.invoke(None, config)``), so finished nodes do not re-run.
  4. ``finish_execution`` (RPC, fenced by attempt) records the outcome.

Nothing is kept in memory between executions; everything needed to resume
lives in Supabase.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import uuid
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from cornucopia.agent.checkpointer import SupabaseCheckpointSaver
from cornucopia.agent.graph import RECURSION_LIMIT, build_agent_graph
from cornucopia.agent.tools import ExecutionContext, LeaseLost, SupabaseAgentTools
from cornucopia.persistence.client import SupabaseClient, SupabaseError
from cornucopia.persistence.repositories.operations import SupabaseOperationsRepository

log = logging.getLogger("cornucopia.worker")

SPRITE_SOCK = "/.sprite/api.sock"


class SpriteHold:
    """Hold the Sprite active via the documented Tasks API while work runs.

    PUT /v1/tasks/<name> {"expire": "5m"} on /.sprite/api.sock creates or
    refreshes a hold; DELETE releases it. Outside a Sprite this is a no-op.
    """

    def __init__(self, name: str = "cornucopia-agent", expire: str = "5m") -> None:
        self.name, self.expire = name, expire
        self.enabled = os.path.exists(SPRITE_SOCK)
        self._client = (
            httpx.Client(
                transport=httpx.HTTPTransport(uds=SPRITE_SOCK), base_url="http://sprite", timeout=5
            )
            if self.enabled
            else None
        )

    def refresh(self) -> None:
        if self._client is None:
            return
        try:
            self._client.put(f"/v1/tasks/{self.name}", json={"expire": self.expire})
        except httpx.HTTPError as exc:  # never let keep-awake break the agent
            log.warning("sprite task refresh failed: %s", exc)

    def release(self) -> None:
        if self._client is None:
            return
        try:
            self._client.delete(f"/v1/tasks/{self.name}")
        except httpx.HTTPError as exc:
            log.warning("sprite task release failed: %s", exc)


@dataclass
class Claim:
    resumed: bool
    execution: dict[str, Any]
    event: dict[str, Any]


class Worker:
    def __init__(
        self,
        db: SupabaseClient,
        organization_id: UUID,
        *,
        worker_id: str | None = None,
        lease_seconds: int = 60,
        poll_seconds: float = 2.0,
        hold: SpriteHold | None = None,
    ) -> None:
        self.db = db
        self.org = organization_id
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.lease_seconds = lease_seconds
        self.poll_seconds = poll_seconds
        self.repo = SupabaseOperationsRepository(db)
        self.saver = SupabaseCheckpointSaver(db, organization_id)
        self.graph = build_agent_graph(self.saver)
        self.hold = hold or SpriteHold()
        self._stop = threading.Event()

    # ---------------------------------------------------------------- loop
    def stop(self) -> None:
        self._stop.set()

    def run_forever(self) -> None:
        log.info("worker %s started for org %s", self.worker_id, self.org)
        while not self._stop.is_set():
            try:
                worked = self.run_once()
            except (SupabaseError, httpx.HTTPError) as exc:
                log.warning("claim failed, backing off: %s", exc)
                worked = False
            if not worked:
                self._stop.wait(self.poll_seconds)
        log.info("worker %s stopped", self.worker_id)

    def claim(self) -> Claim | None:
        raw = self.db.rpc(
            "claim_next_execution",
            {
                "p_organization_id": str(self.org),
                "p_worker": self.worker_id,
                "p_lease_seconds": self.lease_seconds,
            },
        )
        if not raw:
            return None
        return Claim(bool(raw["resumed"]), dict(raw["execution"]), dict(raw["event"]))

    def run_once(self) -> bool:
        claim = self.claim()
        if claim is None:
            return False
        self.process(claim)
        return True

    # ------------------------------------------------------------ execution
    def process(self, claim: Claim) -> str:
        ex = claim.execution
        ctx = ExecutionContext(
            organization_id=self.org,
            execution_id=UUID(ex["id"]),
            event_id=UUID(ex["event_id"]),
            correlation_id=UUID(str(ex["correlation_id"])),
            thread_id=ex["thread_id"],
            worker=self.worker_id,
            attempt=int(ex["attempt"]),
        )
        tools = SupabaseAgentTools(self.db, self.repo, ctx)
        config: dict[str, Any] = {
            "configurable": {"thread_id": ctx.thread_id, "tools": tools},
            "recursion_limit": RECURSION_LIMIT,
        }
        lost = threading.Event()
        beat = threading.Thread(target=self._heartbeat, args=(ctx, lost), daemon=True)
        self.hold.refresh()
        beat.start()
        log.info(
            "execution %s attempt %s (%s) for event %s",
            ctx.execution_id,
            ctx.attempt,
            "resume" if claim.resumed else "new",
            ctx.event_id,
        )
        try:
            existing = self.saver.get_tuple({"configurable": {"thread_id": ctx.thread_id}})
            if existing is not None:
                self.graph.invoke(None, config, durability="sync")
            else:
                self.graph.invoke(
                    {
                        "execution_id": str(ctx.execution_id),
                        "event_id": str(ctx.event_id),
                        "correlation_id": str(ctx.correlation_id),
                        "trail": [],
                    },
                    config,
                    durability="sync",
                )
            snapshot = self.graph.get_state(config)
            status, result, error = self._outcome(snapshot)
        except LeaseLost as exc:
            log.warning("lease lost, abandoning: %s", exc)
            return "lease_lost"
        except Exception as exc:
            log.exception("execution %s failed", ctx.execution_id)
            status, result, error = "failed", {"trail": []}, f"{type(exc).__name__}: {exc}"[:1000]
        finally:
            lost.set()
            beat.join(timeout=5)
            self.hold.release()
        ok = self.db.rpc(
            "finish_execution",
            {
                "p_execution_id": str(ctx.execution_id),
                "p_worker": self.worker_id,
                "p_attempt": ctx.attempt,
                "p_status": status,
                "p_result": result,
                "p_error": error,
            },
        )
        if ok is not True:
            log.warning("finish fenced off for %s (a newer attempt owns it)", ctx.execution_id)
            return "lease_lost"
        log.info("execution %s -> %s", ctx.execution_id, status)
        return status

    def _outcome(self, snapshot: Any) -> tuple[str, dict[str, Any], str | None]:
        values = snapshot.values
        trail = list(values.get("trail", []))
        if snapshot.next and snapshot.interrupts:
            payload = snapshot.interrupts[0].value
            return (
                "awaiting_approval",
                {"trail": trail, "proposal": _jsonable(payload), "report": values.get("report")},
                None,
            )
        outcome = values.get("outcome") or {}
        status = {
            "escalated": "escalated",
            "completed": "completed",
            "committed": "completed",
            "rejected": "completed",
        }.get(outcome.get("status", ""), "completed")
        return (
            status,
            {
                "trail": trail,
                "outcome": outcome,
                "report": values.get("report"),
                "investigation": values.get("investigation"),
            },
            None,
        )

    def _heartbeat(self, ctx: ExecutionContext, lost: threading.Event) -> None:
        interval = max(self.lease_seconds / 3, 1.0)
        while not lost.wait(interval):
            try:
                ok = self.db.rpc(
                    "heartbeat_execution",
                    {
                        "p_execution_id": str(ctx.execution_id),
                        "p_worker": self.worker_id,
                        "p_attempt": ctx.attempt,
                        "p_lease_seconds": self.lease_seconds,
                    },
                )
                self.hold.refresh()
                if ok is not True:
                    log.warning("heartbeat refused for %s; lease lost", ctx.execution_id)
                    return
            except (SupabaseError, httpx.HTTPError) as exc:
                log.warning("heartbeat failed: %s", exc)


def _jsonable(v: Any) -> Any:
    return json.loads(json.dumps(v, default=str))
