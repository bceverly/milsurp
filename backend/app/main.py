"""FastAPI application factory.

Serves the JSON API under ``/api`` and, in production, the built React bundle
for everything else. In dev the Vite server proxies ``/api`` here instead, so
the same code path works in both modes.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import access, auth, items, preferences, scans, sites, system
from .config import ROOT_DIR, get_config
from .scheduler import get_scheduler
from .services import bootstrap

log = logging.getLogger("milsurp")

FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=os.environ.get("MILSURP_LOG_LEVEL", level).upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config = get_config()
    log.info(
        "Starting Milsurp Monitor %s in %s mode (config: %s)",
        __version__,
        config.mode,
        config.source_path or "built-in defaults",
    )
    log.info("Database: %s", config.database_path)
    log.info("Image store: %s", config.images_path)

    _warn_about_weak_secrets(config)
    bootstrap.initialize(config)

    scheduler = get_scheduler()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.stop()


#: HMAC-SHA256 keys shorter than the 256-bit digest add no further security
#: (RFC 7518 section 3.2 requires at least this many bytes).
MIN_SECRET_BYTES = 32


def _warn_about_weak_secrets(config) -> None:
    """Complain about secrets that are missing, short, or still the sample."""
    checks = (
        ("security.jwt_secret", config.security.jwt_secret),
        ("security.password_pepper", config.security.password_pepper),
    )
    for name, value in checks:
        if not value:
            log.warning(
                "%s is not set. Run 'make secrets' and put the values in %s.",
                name,
                config.source_path or "your config.yaml",
            )
        elif "CHANGE-ME" in value:
            log.warning("%s still holds the sample value from config.yaml.sample.", name)
        elif len(value.encode("utf-8")) < MIN_SECRET_BYTES:
            log.warning(
                "%s is only %s bytes; use at least %s. Run 'make secrets'.",
                name,
                len(value.encode("utf-8")),
                MIN_SECRET_BYTES,
            )


def create_app() -> FastAPI:
    configure_logging()
    config = get_config()

    app = FastAPI(
        title="Milsurp Monitor",
        description=(
            "Tracks military surplus firearm listings across vendor sites, "
            "records price history, and emails per-user digests."
        ),
        version=__version__,
        lifespan=lifespan,
        # The docs are an admin convenience in dev; production hides them since
        # the API is not a public product surface.
        docs_url="/api/docs" if config.is_dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if config.is_dev else None,
    )

    if config.is_dev:
        # Only needed for `npm run dev`, where the UI is served from :5173.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        """Headers that apply to every response, API and asset alike."""
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        return response

    api = APIRouter(prefix="/api")
    api.include_router(system.router)
    api.include_router(auth.router)
    api.include_router(access.router)
    api.include_router(users_router())
    api.include_router(sites.router)
    api.include_router(scans.router)
    api.include_router(items.router)
    api.include_router(preferences.router)
    app.include_router(api)

    _mount_frontend(app)
    return app


def users_router() -> APIRouter:
    # Imported here rather than at module scope to keep the import list in
    # create_app() symmetrical with the routers it mounts.
    from .api import users

    return users.router


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built React bundle, falling back to index.html for routes."""
    assets = FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    # response_model=None: the return annotation is a union of Response
    # subclasses, which FastAPI would otherwise try to build a schema from.
    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    async def spa(full_path: str) -> FileResponse | JSONResponse:
        # An unmatched /api path is a genuine 404, not a client-side route.
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found."}, status_code=404)

        candidate = (FRONTEND_DIST / full_path).resolve()
        dist = FRONTEND_DIST.resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(candidate)

        index = FRONTEND_DIST / "index.html"
        if index.is_file():
            # The SPA owns routing, so any unknown path renders the app shell
            # and React decides what it means.
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

        return JSONResponse(
            {
                "detail": (
                    "The frontend has not been built. Run 'make build-frontend' "
                    "(or 'make start')."
                )
            },
            status_code=503,
        )


app = create_app()
