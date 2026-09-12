"""SQLAlchemy engine and session management.

Two engines are supported, and which one is in use is decided entirely by
``database:`` in config.yaml. SQLite needs a set of pragmas and one connection
argument; PostgreSQL needs neither and wants a pool instead. Everything above
this module is written against the ORM and does not know the difference --
which is the property the "Two engines, one schema" rule in README.md exists to
keep.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_config


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _configure_sqlite(dbapi_connection, _record) -> None:
    """Apply the pragmas that make SQLite behave well for this workload."""
    cursor = dbapi_connection.cursor()
    # WAL lets the scheduler's scan threads write while the API reads.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    # Wait rather than fail immediately when a scan holds the write lock.
    cursor.execute("PRAGMA busy_timeout=15000")
    cursor.close()


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        config = get_config()
        config.ensure_directories()
        if config.database.is_postgres:
            _engine = create_engine(
                config.database_url,
                future=True,
                # Every datetime in this schema is UTC, and every column is
                # "timestamp without time zone". utcnow() hands the driver an
                # *aware* UTC value, and PostgreSQL casts timestamptz to
                # timestamp using the session's TimeZone -- so on a server set
                # to America/New_York, 19:36 UTC was stored as 15:36 and read
                # back as though it were UTC. Four hours, silently, on every
                # row the application wrote.
                #
                # SQLite never had the problem: it formats the datetime's own
                # fields, which for an aware UTC value are already UTC. This is
                # the session setting that makes PostgreSQL agree.
                connect_args={"options": "-c timezone=UTC"},
                # A pooled connection can be handed out after the far end has
                # quietly dropped it -- a restarted server, an idle timeout on
                # a firewall or pgbouncer. pre_ping costs one round trip and
                # turns that into a reconnect rather than an error.
                pool_pre_ping=True,
                pool_size=config.database.pool_size,
                max_overflow=config.database.max_overflow,
                pool_recycle=config.database.pool_recycle_seconds,
            )
        else:
            _engine = create_engine(
                config.database_url,
                future=True,
                # The scheduler runs scans on worker threads that share the engine.
                connect_args={"check_same_thread": False},
            )
            event.listen(_engine, "connect", _configure_sqlite)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _SessionFactory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background work (scans, digests, the CLI)."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def reset_engine() -> None:
    """Drop the cached engine (used by tests and after a config reload)."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
