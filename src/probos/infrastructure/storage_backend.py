"""AD-466: StorageBackend ABC -- typed seam over ConnectionFactory.

v1 ships SQLiteStorageBackend (delegates to SQLiteConnectionFactory).
PostgreSQL implementation deferred to AD-466b.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    """Abstract storage backend.

    Concrete subclasses provide a `ConnectionFactory` that produces
    `DatabaseConnection` instances for ProbOS modules (event_log,
    cognitive_journal, etc.). v1 ships SQLiteStorageBackend; future
    PostgreSQL backend will subclass without changing consumers.
    """

    name: str = "abstract"

    @abstractmethod
    def connection_factory(self) -> "ConnectionFactory":
        """Return a ConnectionFactory consumers can use."""

    @abstractmethod
    async def connect(self, db_path: str) -> "DatabaseConnection":
        """Open a connection. Convenience pass-through to factory.connect()."""


class SQLiteStorageBackend(StorageBackend):
    """SQLite-backed storage. The default v1 backend."""

    name = "sqlite"

    def __init__(self) -> None:
        from probos.storage.sqlite_factory import default_factory
        self._factory = default_factory

    def connection_factory(self) -> "ConnectionFactory":
        return self._factory

    async def connect(self, db_path: str) -> "DatabaseConnection":
        return await self._factory.connect(db_path)
