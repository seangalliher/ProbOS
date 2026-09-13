"""Typed contracts for the browser owner's in-process lifecycle."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class BrowserAuthorityBasis(str, Enum):
    SHARED_CREW_SCOPE = "shared_crew_scope"
    SINGLE_OPERATOR_COMPATIBILITY = "single_operator_compatibility"


class BrowserLifecycleState(str, Enum):
    CREATING = "creating"
    ACTIVE = "active"
    ENDING = "ending"
    CLEANUP_FAILED = "cleanup_failed"
    ENDED = "ended"


@dataclass(frozen=True)
class BrowserActor:
    authority_basis: BrowserAuthorityBasis

    @property
    def actor_id(self) -> str:
        return self.authority_basis.value


class BrowserAuthorization(Protocol):
    def allows(self, actor: BrowserActor) -> bool: ...


class BrowserOwnership(Protocol):
    def is_known_crew_owner(self, agent_id: str) -> bool: ...


class BrowserOwnerRecord(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def agent_type(self) -> str: ...


class BrowserOwnerRegistry(Protocol):
    def get(self, agent_id: str) -> BrowserOwnerRecord | None: ...


class BrowserPendingWork(Protocol):
    def pending_browser_work(self, session_id: str) -> int | None: ...


class BrowserPendingWorkReader(Protocol):
    async def read_pending_browser_work(self, session_id: str) -> int | None: ...


@dataclass(frozen=True)
class BrowserSessionSnapshot:
    session_id: str
    state: BrowserLifecycleState
    owner_id: str | None
    sharing_scope: str
    recording_state: str
    recording_scope: str
    pending_work: int | None
    expires_at: float | None
    external_browser: bool


@dataclass(frozen=True)
class BrowserSessionMetadata(BrowserSessionSnapshot):
    agent_id: str
    streaming_url: str | None
    last_url: str


@dataclass(frozen=True)
class BrowserSessionListing:
    enabled: bool
    sessions: list[BrowserSessionMetadata]
    input_forwarding_enabled: bool
    authority_basis: BrowserAuthorityBasis


@dataclass(frozen=True)
class BrowserStream:
    viewer_id: str
    session_id: str


@dataclass(frozen=True)
class BrowserLifecycleResult:
    outcome: str
    reason: str
    status_code: int
    session: BrowserSessionSnapshot | None = None


@dataclass(frozen=True)
class BrowserUse:
    scope_id: str
    session: BrowserSessionSnapshot | None
    page_url: str = ""


class BrowserUseReservations(Protocol):
    def reserve_use(
        self, session_id: str | None = None, *, agent_id: str | None = None,
    ) -> AbstractAsyncContextManager[BrowserUse]: ...

    def is_use_active(self, use: BrowserUse) -> bool: ...


class BrowserLifecycleConflict(RuntimeError):
    """A session identity cannot admit the requested operation."""