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

from cornucopia.agent.supervisor import Worker
from cornucopia.config import get_settings
from cornucopia.persistence.factory import build_client
from cornucopia.persistence.repositories.operations import SupabaseOperationsRepository


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    db = build_client(settings)
    org = SupabaseOperationsRepository(db).ensure_organization(settings.org_slug, settings.org_name)
    worker = Worker(db, org.id)

    def _stop(signum: int, _frame: object) -> None:
        logging.getLogger("cornucopia.worker").info("signal %s: stopping", signum)
        worker.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker.run_forever()
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
