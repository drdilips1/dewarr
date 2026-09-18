from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api import (
    acquisition_selections,
    auth,
    catalog,
    destinations,
    downloaders,
    identity,
    import_runs,
    imports,
    inspection_groupings,
    inspection_matches,
    integrations,
    library,
    lists,
    metadata,
    operations,
    organization,
    requests,
    source_artifacts,
    sources,
)
from app.config import get_settings
from app.db.session import get_engine
from app.jobs.queue import get_queue


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings().encryption_key()
    async with get_queue().open_async():
        yield
    await get_engine().dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Book Search", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exception: RequestValidationError):
        # Validation failures must not echo passwords, tokens or private URLs.
        errors = [
            {key: error[key] for key in ("loc", "msg", "type")} for error in exception.errors()
        ]
        return JSONResponse({"detail": errors}, 422)

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(uuid4())
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' https: data:; "
            "style-src 'self'; script-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health/live", tags=["health"])
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health/ready", tags=["health"])
    async def readiness():
        try:
            async with get_engine().connect() as connection:
                ready = await connection.scalar(
                    text(
                        "SELECT to_regclass('public.operations') IS NOT NULL "
                        "AND to_regclass('book_queue.procrastinate_jobs') IS NOT NULL"
                    )
                )
            if ready:
                return {"status": "ready"}
        except SQLAlchemyError:
            pass
        return JSONResponse(
            {"status": "unavailable", "action": "Check database and migrations"}, 503
        )

    app.include_router(auth.router, prefix="/api")
    app.include_router(operations.router, prefix="/api")
    app.include_router(catalog.router, prefix="/api")
    app.include_router(lists.router, prefix="/api")
    app.include_router(integrations.router, prefix="/api")
    app.include_router(library.router, prefix="/api")
    app.include_router(metadata.router, prefix="/api")
    app.include_router(identity.router, prefix="/api")
    app.include_router(requests.router, prefix="/api")
    app.include_router(organization.router, prefix="/api")
    app.include_router(imports.router, prefix="/api")
    app.include_router(inspection_groupings.router, prefix="/api")
    app.include_router(inspection_matches.router, prefix="/api")
    app.include_router(import_runs.router, prefix="/api")
    app.include_router(destinations.router, prefix="/api")
    app.include_router(sources.router, prefix="/api")
    app.include_router(downloaders.router, prefix="/api")
    app.include_router(source_artifacts.router, prefix="/api")
    app.include_router(acquisition_selections.router, prefix="/api")
    dist: Path = get_settings().web_dist
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        if path.startswith("api/") or not (dist / "index.html").is_file():
            return JSONResponse({"detail": "Not found"}, 404)
        return FileResponse(dist / "index.html")

    return app


app = create_app()
