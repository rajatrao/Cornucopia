"""In-app demo reset.

Nothing is deleted: the journal, audit log and plan history are append-only by
design. A reset instead moves the deployment to a brand-new demonstration
organization:

1. create the organization (slug ``<prefix>-<UTC timestamp>``, same name);
2. copy every active operator account into it (same argon2id hashes, so the
   same passwords keep working);
3. switch the API to it and record the switch in the active-org file, which
   the agent worker watches;
4. load the Thanksgiving sample data through the API itself, signed in as the
   operator who asked for the reset.

Every session issued before the reset is bound to the old organization, so
everyone signs in again afterwards. One reset runs at a time.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from cornucopia.agent.supervisor import SpriteHold
from cornucopia.auth import OperatorIdentity, issue_session
from cornucopia.config import Settings
from cornucopia.demo.seed import seed
from cornucopia.persistence.repositories.operations import OperationsRepository, Organization

log = logging.getLogger("cornucopia.demo")

ClientFactory = Callable[[dict[str, str]], httpx.Client]


class ResetBusy(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


class DemoReset:
    def __init__(
        self,
        state: Any,
        settings: Settings,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._state = state  # app.state: holds ops_repo and the active organization
        self._settings = settings
        self._factory = client_factory or self._http_client
        self._lock = threading.Lock()
        self.status: dict[str, Any] = {"state": "idle"}

    def _http_client(self, headers: dict[str, str]) -> httpx.Client:
        return httpx.Client(
            base_url=f"{self._settings.self_url.rstrip('/')}/api/v1",
            headers=headers,
            timeout=60,
            limits=httpx.Limits(max_keepalive_connections=0),
        )

    @property
    def running(self) -> bool:
        return self.status.get("state") == "running"

    def start(self, op: OperatorIdentity, *, background: bool = True) -> dict[str, Any]:
        with self._lock:
            if self.running:
                raise ResetBusy("a reset is already running")
            self.status = {
                "state": "running",
                "step": "creating a fresh organization",
                "requested_by": op.username,
                "started_at": _now(),
            }
        if background:
            threading.Thread(target=self._run, args=(op,), daemon=True, name="demo-reset").start()
        else:
            self._run(op)
        return dict(self.status)

    def _step(self, text: str) -> None:
        self.status = {**self.status, "step": text}
        log.info("demo reset: %s", text)

    def _run(self, op: OperatorIdentity) -> None:
        repo: OperationsRepository = self._state.ops_repo
        old: Organization = self._state.organization
        # Self-calls on localhost do not count as Sprite activity: hold the
        # Sprite awake explicitly, or it can suspend mid-reset.
        hold = SpriteHold(name="cornucopia-demo-reset", expire="10m")
        hold.refresh()
        try:
            prefix = re.sub(r"-\d{12,14}$", "", old.slug)
            slug = f"{prefix}-{datetime.now(UTC):%Y%m%d%H%M%S}"
            new = repo.ensure_organization(slug, old.name)

            self._step("copying operator accounts")
            me: dict[str, Any] | None = None
            for row in repo.list("operators", old.id, limit=500):
                if not row.get("active"):
                    continue
                repo.call(
                    "create_operator",
                    {
                        "p_organization_id": str(new.id),
                        "p_username": row["username"],
                        "p_display_name": row["display_name"],
                        "p_role": row["role"],
                        "p_password_hash": row["password_hash"],
                    },
                )
            for row in repo.list("operators", new.id, filters={"username": f"eq.{op.username}"}):
                me = row
            if me is None:
                raise RuntimeError("could not copy the requesting operator")

            self._step("switching to the fresh organization")
            self._state.organization = new
            self._settings.set_active_org(new.slug, new.name)

            self._step("loading the Thanksgiving sample data")
            token, _ = issue_session(
                OperatorIdentity.model_validate(me),
                new.id,
                self._settings.session_secret.get_secret_value(),
                30,
            )
            headers = {"X-Cornucopia-Session": token}
            if self._settings.api_token is not None:
                headers["Authorization"] = f"Bearer {self._settings.api_token.get_secret_value()}"
            http = self._factory(headers)
            try:
                summary = seed(http, label="", quinoa_lb="130")
            finally:
                http.close()
            self.status = {
                **self.status,
                "state": "done",
                "step": "done",
                "organization": new.slug,
                "summary": summary,
                "finished_at": _now(),
            }
            log.info("demo reset complete: %s (%s)", new.slug, summary)
        except Exception as exc:  # noqa: BLE001 - reported to the operator, never swallowed
            log.exception("demo reset failed")
            self._state.organization = old
            self._settings.set_active_org(old.slug, old.name)
            self.status = {
                **self.status,
                "state": "failed",
                "error": str(exc)[:300],
                "finished_at": _now(),
            }
        finally:
            hold.release()
