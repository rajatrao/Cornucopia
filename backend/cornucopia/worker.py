"""Agent worker entrypoint: ``python -m cornucopia.worker``.

Runs as its own Sprite service, independent of the API and the frontend.
Graceful shutdown on SIGTERM/SIGINT: the current node boundary is respected
by the lease; an interrupted execution is resumed from its last checkpoint by
whichever worker claims it next.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading

from cornucopia.agent.supervisor import Worker
from cornucopia.config import get_settings
from cornucopia.logging_setup import configure
from cornucopia.persistence.factory import build_client
from cornucopia.persistence.repositories.operations import SupabaseOperationsRepository


def main() -> int:
    configure("cornucopia-worker")
    settings = get_settings()
    db = build_client(settings)
    repo = SupabaseOperationsRepository(db)
    log = logging.getLogger("cornucopia.worker")
    stopping = threading.Event()
    current: list[Worker] = []

    def _stop(signum: int, _frame: object) -> None:
        log.info("signal %s: stopping", signum)
        stopping.set()
        for w in current:
            w.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    # The in-app demo reset switches the active organization at runtime; when
    # it does, finish the current step, then start over for the new one.
    while not stopping.is_set():
        slug, name = settings.active_org()
        org = repo.ensure_organization(slug, name)
        worker = Worker(db, org.id, approval_ttl_minutes=settings.approval_ttl_minutes)
        current[:] = [worker]

        def _watch(w: Worker = worker, active: str = slug) -> None:
            while not stopping.wait(5):
                if settings.active_org()[0] != active:
                    log.info("active organization changed: restarting the worker loop")
                    w.stop()
                    return

        threading.Thread(target=_watch, daemon=True, name="org-watch").start()
        worker.run_forever()
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
