import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_admin,
    routes_approvals,
    routes_auth,
    routes_cases,
    routes_data_rights,
    routes_growth,
    routes_insights,
    routes_locations,
    routes_meta,
    routes_offers,
    routes_orders,
    routes_platform,
    routes_policies,
)
from app.config import get_settings
from mocks.registry import enable_persistence

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the job scheduler only when SCHEDULER_ENABLED is set (off by default), and stop it
    cleanly with the app. A scheduler that cannot start never stops the API."""
    scheduler = None
    s = get_settings()
    if s.scheduler_enabled:
        try:
            from app.core.db import get_engine
            from app.core.scheduler import Scheduler
            from app.engine.scheduled_jobs import build_jobs

            engine = get_engine()
            scheduler = Scheduler(
                engine,
                build_jobs(s, engine),
                tick_seconds=s.scheduler_tick_seconds,
                startup_delay=s.scheduler_startup_delay_seconds,
                grace=s.scheduler_shutdown_grace_seconds,
            )
            scheduler.start()
            log.info("job scheduler started: %s", [j.name for j in scheduler.jobs])
        except Exception as exc:
            log.warning("job scheduler not started: %s", type(exc).__name__)
            scheduler = None
    try:
        yield
    finally:
        if scheduler is not None:
            await asyncio.shield(scheduler.stop())


def create_app() -> FastAPI:
    app = FastAPI(title="ResolveDesk", lifespan=lifespan)
    # Bearer tokens, not cookies: no credentials mode, only the listed origins (WEB_ORIGINS).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().web_origin_list,
        allow_methods=["GET", "POST", "PUT"],  # every method a route uses (tested)
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(routes_auth.router)
    app.include_router(routes_locations.router)
    app.include_router(routes_meta.router)
    app.include_router(routes_orders.router)
    app.include_router(routes_policies.router)
    app.include_router(routes_cases.router)
    app.include_router(routes_approvals.router)
    app.include_router(routes_offers.router)
    app.include_router(routes_growth.router)
    app.include_router(routes_insights.router)
    app.include_router(routes_data_rights.router)
    app.include_router(routes_platform.router)  # 404 unless the platform admin is configured
    if get_settings().app_env in routes_admin.DEV_ENVS:  # allow-list
        app.include_router(routes_admin.router)
        if get_settings().mock_state_file:  # mock providers only exist in dev/test
            enable_persistence(get_settings().mock_state_file)
    return app


app = create_app()
