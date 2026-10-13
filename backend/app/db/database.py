"""
SQLAlchemy engine/session setup for the NidhiGuard backend.

Engine + session factory + declarative Base + table creation, all pointed at
a single configured DATABASE_URL (see backend/app/config.py). Models live in
models.py — this file only wires up the plumbing.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.app.config import DATABASE_URL


def create_db_engine(url: str) -> Engine:
    """
    Build an engine for `url`. For SQLite this also turns on foreign-key
    enforcement (SQLite ships with it OFF), so the Stage 6.2 foreign keys are
    actually checked by the database and not just declared.
    """
    # check_same_thread=False is the standard SQLite + web-framework setting:
    # SQLite objects are created on one thread but FastAPI may use another to
    # handle a given request. Session usage is still one-session-per-request
    # via get_db() below, so this does not introduce cross-request sharing.
    is_sqlite = url.startswith("sqlite")
    eng = create_engine(url, connect_args={"check_same_thread": False} if is_sqlite else {})

    if is_sqlite:

        @event.listens_for(eng, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return eng


engine = create_db_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Declarative base for all NidhiGuard backend ORM models."""


def init_db(bind: Engine | None = None) -> None:
    """Create all tables that don't already exist. Safe to call repeatedly."""
    # Import models here (not at module top) so every model is registered on
    # Base.metadata before create_all runs, without creating an import cycle
    # between database.py and models.py.
    from backend.app.db import models  # noqa: F401

    Base.metadata.create_all(bind=bind or engine)


def get_db():
    """FastAPI dependency yielding a request-scoped SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
