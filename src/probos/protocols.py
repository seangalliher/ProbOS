"""AD-514: Service boundary protocols for interface segregation.

These protocols define the narrow interfaces that consumers depend on,
enabling decomposition of ProbOSRuntime into focused modules.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence, TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from probos.events import BaseEvent


# ── EventEmitterMixin (BF-092) ─────────────────────────────────────


class EventEmitterMixin:
    """Shared _emit() for services that hold an _emit_event callback.

    Expects the subclass ``__init__`` to set ``self._emit_event`` to a
    ``Callable[[str, dict], None] | None``.
    """

    _emit_event: Callable[..., Any] | None

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self._emit_event:
            self._emit_event(event_type, data)

if TYPE_CHECKING:
    from probos.cognitive.self_mod import DesignedAgentRecord
    from probos.consensus.trust import TrustRecord
    from probos.ontology import VesselOntologyService
    from probos.types import Episode


@runtime_checkable
class EpisodicMemoryProtocol(Protocol):
    """What agents and services need from episodic memory."""

    async def store(self, episode: Episode) -> None: ...
    async def recall(self, query: str, k: int = 5) -> list[Episode]: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


@runtime_checkable
class TrustNetworkProtocol(Protocol):
    """What services need from the trust network."""

    def get_trust_score(self, agent_id: str) -> float: ...
    def get_or_create(self, agent_id: str) -> TrustRecord: ...
    def record_outcome(self, agent_id: str, success: bool, weight: float = 1.0) -> float: ...
    def remove_agent(self, agent_id: str) -> None: ...


@runtime_checkable
class EventLogProtocol(Protocol):
    """What services need from event logging."""

    async def log(self, category: str, agent_id: str, data: dict[str, Any] | None = None) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


@runtime_checkable
class WardRoomProtocol(Protocol):
    """What services need from the Ward Room."""

    async def create_thread(self, channel_id: str, title: str, author_id: str, **kwargs: Any) -> dict[str, Any]: ...
    async def create_post(self, thread_id: str, author_id: str, content: str) -> dict[str, Any]: ...
    async def get_thread(self, thread_id: str) -> dict[str, Any] | None: ...
    async def list_channels(self) -> list[dict[str, Any]]: ...
    async def post_system_message(self, channel_name: str, content: str, author: str = "ship_computer") -> None: ...
    def set_ontology(self, ontology: VesselOntologyService) -> None: ...


@runtime_checkable
class KnowledgeStoreProtocol(Protocol):
    """What services need from the knowledge store."""

    async def store_agent(self, record: DesignedAgentRecord, source_code: str) -> None: ...
    async def store_episode(self, episode: Episode) -> None: ...
    async def store_skill(self, name: str, source: str, descriptor: dict[str, Any]) -> None: ...
    async def store_trust_snapshot(self, data: dict[str, Any]) -> None: ...
    async def store_routing_snapshot(self, data: dict[str, Any]) -> None: ...


@runtime_checkable
class HebbianRouterProtocol(Protocol):
    """What services need from Hebbian routing."""

    def record_interaction(self, source: str, target: str, success: bool) -> float: ...
    def get_all_weights(self) -> dict[tuple[str, str, str], float]: ...
    def set_weight(self, key: tuple[str, str, str], value: float) -> None: ...
    def remove_weights_for_agent(self, agent_id: str) -> None: ...


@runtime_checkable
class EventEmitterProtocol(Protocol):
    """What modules need to emit HXI events."""

    def emit_event(self, event: BaseEvent | str, data: dict[str, Any] | None = None) -> None: ...
    def add_event_listener(self, fn: Callable[..., Any]) -> None: ...
    def remove_event_listener(self, fn: Callable[..., Any]) -> None: ...


# ── Database abstraction (AD-542) ──────────────────────────────────


@runtime_checkable
class DatabaseConnection(Protocol):
    """Abstract async database connection.

    Mirrors the aiosqlite.Connection API surface used throughout ProbOS.
    Commercial overlays implement this protocol for Postgres/cloud backends.
    """

    async def execute(self, sql: str, parameters: Sequence[Any] = ...) -> Any:
        """Execute a single SQL statement."""
        ...

    async def executemany(self, sql: str, parameters: Iterable[Sequence[Any]]) -> Any:
        """Execute a SQL statement for each set of parameters."""
        ...

    async def executescript(self, sql_script: str) -> None:
        """Execute a multi-statement SQL script."""
        ...

    async def fetchone(self) -> Any:
        """Fetch the next row from the last executed query."""
        ...

    async def fetchall(self) -> Any:
        """Fetch all remaining rows from the last executed query."""
        ...

    async def commit(self) -> None:
        """Commit the current transaction."""
        ...

    async def close(self) -> None:
        """Close the connection."""
        ...


@runtime_checkable
class ConnectionFactory(Protocol):
    """Factory for creating database connections.

    Default implementation wraps aiosqlite.connect().
    Commercial overlays provide Postgres/cloud implementations.
    """

    async def connect(self, db_path: str) -> DatabaseConnection:
        """Create and return a new database connection."""
        ...
