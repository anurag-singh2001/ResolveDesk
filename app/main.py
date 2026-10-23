from fastapi import FastAPI

from app.api import routes_auth, routes_locations


def create_app() -> FastAPI:
    app = FastAPI(title="ResolveDesk")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(routes_auth.router)
    app.include_router(routes_locations.router)
    return app


app = create_app()
