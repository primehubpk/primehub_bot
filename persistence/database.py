"""SQLAlchemy 2.0 engine and session management."""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base class for all ORM models."""


def _prepare_sqlite_url(database_url: str) -> str:
    """Create the parent directory for a local SQLite database."""
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        database_path = Path(database_url[len(prefix):])
        database_path.parent.mkdir(parents=True, exist_ok=True)
    return database_url


def create_engine_for_url(database_url: str) -> Engine:
    """Create a SQLAlchemy engine with safe connection pre-ping."""
    url = _prepare_sqlite_url(database_url)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(
        url,
        connect_args=connect_args,
        pool_pre_ping=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a typed SQLAlchemy session factory."""
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )


def get_session(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Yield one database session and close it deterministically."""
    session = factory()
    try:
        yield session
    finally:
        session.close()
