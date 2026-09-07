"""FastAPI application factory.

Serves the JSON API under ``/api`` and, in production, the built React bundle
for everything else. In dev the Vite server proxies ``/api`` here instead, so
the same code path works in both modes.
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError

from . import __version__
from .api import (
    access,
    armory,
    auth,
    items,
    manufacturers,
    preferences,
    scans,
    sites,
    system,
)
from .config import ROOT_DIR, get_config
from .scheduler import get_scheduler
from .services import bootstrap

log = logging.getLogger("milsurp")

#: The built UI this process serves.
#:
#: Overridable because the Playwright harness builds an *instrumented* bundle
#: (COVERAGE=1), and it used to write it straight over frontend/dist — the same
#: directory `make start` serves. Running the test suite therefore replaced the
#: running app's bundle with an instrumented one, silently, and left it there.
#: Worse, the fresh timestamp made `make start` consider dist up to date, so it
#: would not rebuild and the swap survived a restart. The harness now builds to
#: its own directory and points this at it.
FRONTEND_DIST = Path(os.environ.get("MILSURP_FRONTEND_DIST") or (ROOT_DIR / "frontend" / "dist"))


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


class SecretHealth(str, Enum):
    """What is wrong with a configured secret, if anything.

    The point of this type is what it does *not* carry. The old code passed the
    secret itself into the function that logs about it, and while that function
    only ever logged the setting's name, "a function that was handed a secret
    logs something" is indistinguishable — to a reader and to a static
    analyser — from one that logs the secret. So the secret is examined here
    and only the verdict travels on.
    """

    OK = "ok"
    MISSING = "missing"
    SAMPLE = "sample"
    SHORT = "short"


def inspect_secret(value: str | None) -> SecretHealth:
    """Judge a secret. Returns a verdict and never the secret."""
    if not value:
        return SecretHealth.MISSING
    if "CHANGE-ME" in value:
        return SecretHealth.SAMPLE
    if len(value.encode("utf-8")) < MIN_SECRET_BYTES:
        return SecretHealth.SHORT
    return SecretHealth.OK


def _warn_about_one_secret(name: str, health: SecretHealth, source: object) -> None:
    """Say what is wrong with a setting, given only the verdict.

    Nothing derived from the secret reaches this function — not its length,
    which is not the secret but is a hint about it, and worth no risk at all
    when the operator can already see what they configured.
    """
    where = source or "your config.yaml"
    if health is SecretHealth.MISSING:
        # The marker rides on the call rather than sitting above it: on its own
        # line ruff reads it as commented-out code. The rule fires on the words
        # "make secrets" in the message, and this function is never given a
        # secret to leak — see SecretHealth, which is a stronger guarantee than
        # the rule is looking for.
        log.warning(  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
            "%s is not set. Run 'make secrets' and put the values in %s.", name, where
        )
    elif health is SecretHealth.SAMPLE:
        log.warning("%s still holds the sample value from config.yaml.sample.", name)
    elif health is SecretHealth.SHORT:
        log.warning(
            "%s is shorter than %s bytes; run 'make secrets' for a strong one.",
            name,
            MIN_SECRET_BYTES,
        )


def _warn_about_weak_secrets(config) -> None:
    """Complain about secrets that are missing, short, or still the sample."""
    source = config.source_path
    # Judged here, so only the verdict crosses into the logging function.
    _warn_about_one_secret(
        "security.jwt_secret", inspect_secret(config.security.jwt_secret), source
    )
    _warn_about_one_secret(
        "security.password_pepper", inspect_secret(config.security.password_pepper), source
    )


#: What to tell a client to wait when the database is locked.
#:
#: Comfortably longer than a scan's longest write burst — it commits at least
#: every COMMIT_SECONDS — and short enough that a person retrying by hand does
#: not give up first.
RETRY_AFTER_SECONDS = 5

#: SQLite's way of saying "someone else is writing". Matched on the message
#: because the DBAPI does not give these their own exception type.
_LOCKED = re.compile(r"\b(?:database|table|schema) is locked\b", re.I)


def _is_locked(exc: OperationalError) -> bool:
    return bool(_LOCKED.search(str(getattr(exc, "orig", exc))))


#: One path segment of a built asset: letters, digits, and the punctuation a
#: bundler puts in a filename. Anything else — a separator, a "..", a NUL, a
#: percent-escape — is not a segment of ours.
_ASSET_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]*$")


def _asset_path(requested: str) -> Path | None:
    """The built file this request names, or None.

    The request is validated *before* it is joined to anything, rather than
    joined and then checked afterwards. Both orders reject a traversal, but
    only this one never constructs the path in the first place — which is what
    a reader, and CodeQL, can see at a glance.

    Three rules, all of them about the request rather than the filesystem: the
    path is a run of ordinary segments, none of them "." or "..", and the file
    it names is inside the build directory and is a file.
    """
    if not requested:
        return None
    segments = requested.split("/")
    if any(not _ASSET_SEGMENT.match(segment) or segment in (".", "..") for segment in segments):
        return None

    dist = FRONTEND_DIST.resolve()
    candidate = dist.joinpath(*segments)
    # Belt and braces: a symlink inside the build could still point outside it.
    resolved = candidate.resolve()
    if not resolved.is_relative_to(dist) or not resolved.is_file():
        return None
    return resolved


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

    @app.exception_handler(OperationalError)
    async def database_busy(_request: Request, exc: OperationalError) -> Response:
        """Answer 503 when the database is locked, rather than 500.

        SQLite has one writer, and a scan of a large vendor holds the write
        lock in short bursts for as long as the scan runs. A request that
        arrives during one waits out its busy timeout and then fails — and
        "500 Internal Server Error" is the wrong thing to say about it. Nothing
        is broken, the request was not refused, and it will very likely work if
        it is made again in a moment. That is what 503 and Retry-After mean.

        Only a lock says this. Every other OperationalError — a missing table,
        a disk that has gone away — is a genuine fault and keeps its 500, or a
        real problem would spend its life being politely retried.
        """
        if not _is_locked(exc):
            log.exception("Database error", exc_info=exc)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "The database could not answer that request."},
            )
        log.warning("Database busy; answered 503: %s", exc.orig)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": (
                    "The database is busy, most likely because a scan is "
                    "running. Try again in a moment."
                )
            },
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
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
    api.include_router(manufacturers.router)
    api.include_router(armory.router)
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

        asset = _asset_path(full_path)
        if asset is not None:
            return FileResponse(asset)

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
