from fastapi import FastAPI

from app.api import routes_admin, routes_auth, routes_locations, routes_orders
from app.config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="ResolveDesk")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(routes_auth.router)
    app.include_router(routes_locations.router)
    app.include_router(routes_orders.router)
    if get_settings().app_env != "prod":  # dev controls simply don't exist in prod
        app.include_router(routes_admin.router)
    return app


app = create_app()
