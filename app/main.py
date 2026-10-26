from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_admin,
    routes_approvals,
    routes_auth,
    routes_cases,
    routes_growth,
    routes_insights,
    routes_locations,
    routes_meta,
    routes_orders,
    routes_privacy,
)
from app.config import get_settings
from mocks.registry import enable_persistence


def create_app() -> FastAPI:
    app = FastAPI(title="ResolveDesk")
    # Bearer tokens, not cookies: no credentials mode, only the listed origins (WEB_ORIGINS).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().web_origin_list,
        allow_methods=["GET", "POST"],
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
    app.include_router(routes_cases.router)
    app.include_router(routes_approvals.router)
    app.include_router(routes_growth.router)
    app.include_router(routes_insights.router)
    app.include_router(routes_privacy.router)
    if get_settings().app_env in routes_admin.DEV_ENVS:  # allow-list
        app.include_router(routes_admin.router)
        if get_settings().mock_state_file:  # mock providers only exist in dev/test
            enable_persistence(get_settings().mock_state_file)
    return app


app = create_app()
