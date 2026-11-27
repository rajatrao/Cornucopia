import hmac
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cornucopia import __version__
from cornucopia.api.agent import build_router as build_agent_router
from cornucopia.api.approvals import build_router as build_approvals_router
from cornucopia.api.command import build_router as build_command_router
from cornucopia.api.compiler import build_router as build_compiler_router
from cornucopia.api.demo import build_router as build_demo_router
from cornucopia.api.operations import build_router, current_operator
from cornucopia.api.optimizer import build_router as build_optimizer_router
from cornucopia.api.schemas import DbHealthOut, Liveness, ProbeCreate, ProbeOut
from cornucopia.config import Settings, TransportMode, get_settings
from cornucopia.demo.reset import DemoReset
from cornucopia.persistence.client import SupabaseClient, SupabaseError
from cornucopia.persistence.factory import build_client
from cornucopia.persistence.repositories import SupabaseSystemRepository, SystemRepository
from cornucopia.persistence.repositories.operations import SupabaseOperationsRepository

log = logging.getLogger("cornucopia.api")

_bearer = HTTPBearer(auto_error=False)


def _runtime() -> str:
    # /.sprite exists inside every Sprite (sprite-env, api.sock, logs).
    return "sprite" if os.path.isdir("/.sprite") else "local"


def create_app(settings: Settings | None = None, client: SupabaseClient | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = client or build_client(settings)
        app.state.db = db
        app.state.system_repo = SupabaseSystemRepository(db)
        app.state.ops_repo = SupabaseOperationsRepository(db)
        app.state.organization = app.state.ops_repo.ensure_organization(*settings.active_org())
        app.state.demo_reset = DemoReset(app.state, settings)
        log.info("startup transport=%s runtime=%s", settings.transport, _runtime())
        try:
            yield
        finally:
            db.close()

    app = FastAPI(title="CORNUCOPIA API", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.demo_reset_background = True
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Cornucopia-Actor"],
        )

    def system_repo(request: Request) -> SystemRepository:
        repo: SystemRepository = request.app.state.system_repo
        return repo

    def require_token(
        creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> None:
        expected = settings.api_token
        if expected is None:
            return  # development without a token configured
        if creds is None or not hmac.compare_digest(
            creds.credentials.encode(), expected.get_secret_value().encode()
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing bearer token")

    Repo = Annotated[SystemRepository, Depends(system_repo)]
    Auth = Depends(require_token)

    @app.get("/health", response_model=Liveness, tags=["health"])
    def health() -> Liveness:
        return Liveness(
            status="ok",
            service="cornucopia-api",
            version=__version__,
            environment=settings.environment,
            transport=settings.transport.value,
            runtime=_runtime(),
        )

    @app.get("/health/db", response_model=DbHealthOut, tags=["health"], dependencies=[Auth])
    def health_db(repo: Repo) -> DbHealthOut:
        started = time.perf_counter()
        try:
            h = repo.health()
        except (SupabaseError, OSError) as exc:
            log.warning("db health failed: %s", exc)
            return DbHealthOut(
                status="error",
                transport=settings.transport.value,
                db_schema=settings.db_schema,
                latency_ms=_ms(started),
                detail=type(exc).__name__ + ": " + str(exc)[:300],
            )
        return DbHealthOut(
            status="ok",
            transport=settings.transport.value,
            db_schema=h.schema_name,
            server_time=h.server_time,
            latency_ms=_ms(started),
        )

    @app.get("/health/agent", tags=["health"], dependencies=[Auth])
    def health_agent(request: Request) -> dict[str, object]:
        """Is an agent worker alive? Workers heartbeat every 15 s while the
        Sprite is awake; a paused Sprite resumes them on the next request."""
        repo = request.app.state.ops_repo
        org = request.app.state.organization
        workers = repo.list("agent_workers", org.id, order="last_seen_at.desc", limit=5)
        now = time.time()
        live = []
        for w in workers:
            from datetime import datetime

            age = now - datetime.fromisoformat(str(w["last_seen_at"])).timestamp()
            if w["status"] == "running" and age < 90:
                live.append({"worker_id": w["worker_id"], "seconds_since_heartbeat": round(age, 1)})
        return {
            "status": "ok" if live else "degraded",
            "live_workers": live,
            "known_workers": len(workers),
        }

    @app.post(
        "/api/v1/system/probes",
        response_model=ProbeOut,
        status_code=201,
        tags=["system"],
        dependencies=[Auth],
    )
    def create_probe(body: ProbeCreate, repo: Repo) -> ProbeOut:
        source = {TransportMode.GATEWAY: "gateway", TransportMode.DIRECT: "direct"}.get(
            settings.transport, "test"
        )
        return ProbeOut.model_validate(repo.record_probe(body.note, source).model_dump())

    @app.get(
        "/api/v1/system/probes/{probe_id}",
        response_model=ProbeOut,
        tags=["system"],
        dependencies=[Auth],
    )
    def get_probe(probe_id: UUID, repo: Repo) -> ProbeOut:
        p = repo.get_probe(probe_id)
        if p is None:
            raise HTTPException(404, "probe not found")
        return ProbeOut.model_validate(p.model_dump())

    @app.get(
        "/api/v1/system/probes",
        response_model=list[ProbeOut],
        tags=["system"],
        dependencies=[Auth],
    )
    def list_probes(repo: Repo) -> list[ProbeOut]:
        return [ProbeOut.model_validate(p.model_dump()) for p in repo.recent_probes()]

    # Every operational route needs the service token AND a signed-in operator.
    Session = Depends(current_operator)
    app.include_router(build_router(), dependencies=[Auth, Session])
    app.include_router(build_compiler_router(), dependencies=[Auth, Session])
    app.include_router(build_optimizer_router(), dependencies=[Auth, Session])
    app.include_router(build_agent_router(), dependencies=[Auth, Session])
    app.include_router(build_command_router(), dependencies=[Auth, Session])
    app.include_router(build_approvals_router(), dependencies=[Auth])
    app.include_router(build_demo_router(), dependencies=[Auth])
    return app


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
