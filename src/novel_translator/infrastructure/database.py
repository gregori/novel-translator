"""SQLite engine and schema migration control for persistence."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import Session
from sqlalchemy.pool import ConnectionPoolEntry, StaticPool

_MIGRATIONS_DIRECTORY = Path(__file__).parent / "migrations"
_MEMORY_URLS = frozenset({"sqlite://", "sqlite:///:memory:"})


def _database_url(url_or_path: str) -> str:
    """Normalize a SQLAlchemy URL or a filesystem path to a URL."""
    if "://" in url_or_path:
        return url_or_path
    if url_or_path == ":memory:":
        return "sqlite://"
    return "sqlite:///" + Path(url_or_path).expanduser().absolute().as_posix()


def _apply_sqlite_pragmas(
    dbapi_connection: DBAPIConnection,
    _connection_record: ConnectionPoolEntry,
) -> None:
    """Keep every pooled connection in WAL mode with safe durability."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


class Database:
    """Prepare the SQLite schema and create short-lived sessions."""

    def __init__(self, database_url: str) -> None:
        self._url = _database_url(database_url)
        if self._url in _MEMORY_URLS:
            self._engine: Engine = create_engine(
                self._url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            self._engine = create_engine(
                self._url,
                connect_args={"check_same_thread": False},
            )
        event.listens_for(self._engine, "connect")(_apply_sqlite_pragmas)

    @property
    def url(self) -> str:
        """Return the normalized SQLAlchemy URL."""
        return self._url

    def prepare(self) -> None:
        """Create or upgrade the schema to the latest migration.

        Migrations run on one live connection of the shared engine so
        an in-memory database is migrated on the very connection every
        session will reuse, instead of a throwaway second database.
        """
        config = Config()
        config.set_main_option(
            "script_location", _MIGRATIONS_DIRECTORY.as_posix()
        )
        config.set_main_option("sqlalchemy.url", self._url)
        with self._engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    def session(self) -> Session:
        """Create one short-lived session bound to the shared engine."""
        return Session(self._engine)
