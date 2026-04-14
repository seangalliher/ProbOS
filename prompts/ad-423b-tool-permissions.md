# AD-423b: Tool Permissions & Scoping

**Ticket:** AD-423b (Issue #145)
**Depends on:** AD-423a (Tool Foundation, complete), AD-357 (Earned Agency, complete), AD-339 (Standing Orders, complete)
**Unlocks:** AD-423c (ToolContext + onboarding), AD-548 (trust-gated tool permissions in SWE Harness)

## Problem

AD-423a established `Tool`, `ToolRegistry`, and adapters — but any caller can invoke any tool with no access control. No permission checking, no department scoping, no Captain overrides, no exclusive-access locks. The 7 ontology-seeded tools have no enforcement of the `available_to` and `gated_by` fields defined in `resources.yaml`.

AD-423b adds the permission layer: a CRUD+O permission model, Earned Agency rank gates, department scoping, Captain overrides (grant/revoke with SQLite persistence), and LOTO exclusive-access locks for dangerous tools. Deny-by-default.

## Design References

- `docs/development/tool-taxonomy.md` — CRUD+O model (lines 410-446), LOTO (lines 205-249), department scoping (lines 251-366), permission resolution chain (lines 308-317)
- `docs/research/crew-capability-architecture.md` — ToolContext concept (lines 416-436), connections C1/C3
- `src/probos/earned_agency.py` — Rank enum, AgencyLevel, `can_perform_action()` pattern
- `src/probos/clearance_grants.py` — ClearanceGrantStore pattern (SQLite + cache, ConnectionFactory)
- `src/probos/directive_store.py` — `authorize_directive()` pattern (rank + role + department)

## Design Decisions

1. **Five additive permission levels.** `ToolPermission` enum: NONE → OBSERVE → READ → WRITE → FULL. Each level includes the powers of all lower levels. Matches the taxonomy spec.

2. **Permission resolution chain.** Five-layer check as designed in taxonomy spec: (1) scope filter, (2) restriction filter, (3) rank gate, (4) permission level, (5) Captain override. Implemented as a pure function `check_permission()`.

3. **SQLite-backed Captain override store.** Follows `ClearanceGrantStore` pattern exactly — ConnectionFactory, WAL mode, in-memory cache, start/stop lifecycle. Stores per-agent tool permission grants and restrictions. Survives restart.

4. **LOTO is in-memory.** Exclusive locks do NOT survive restart (tool is released and available after reboot). Lock state is volatile. Audit trail of lock/release events goes through the event system.

5. **ToolRegistration extension.** New fields added to the existing `ToolRegistration` dataclass: `default_permissions`, `restricted_to`, `concurrency`, `lock_timeout_seconds`. These are additive — existing registrations continue working with defaults.

6. **`/tool-access` shell command.** Captain interface for grant/revoke/lock-break/list. Follows `commands_clearance.py` pattern.

7. **ToolPermissionDenied exception.** Raised by a new `check_and_invoke()` method on ToolRegistry that wraps permission check + invocation. Agents that bypass this and call `tool.invoke()` directly skip permission enforcement — AD-423c's ToolContext will close this gap.

## Scope — 9 Changes

| # | File | Action |
|---|------|--------|
| 1 | `src/probos/tools/protocol.py` | MODIFY — ToolPermission enum, ToolAccessGrant dataclass, extend ToolRegistration |
| 2 | `src/probos/tools/registry.py` | MODIFY — check_permission(), check_and_invoke(), LOTO lock/release/break |
| 3 | `src/probos/tools/permissions.py` | NEW — ToolPermissionStore (SQLite + cache for Captain overrides) |
| 4 | `src/probos/experience/commands/commands_tool_access.py` | NEW — /tool-access shell command |
| 5 | `src/probos/experience/shell.py` | MODIFY — register /tool-access |
| 6 | `src/probos/events.py` | MODIFY — TOOL_PERMISSION_DENIED, TOOL_LOCKED, TOOL_UNLOCKED events |
| 7 | `src/probos/startup/results.py` | MODIFY — add tool_permission_store to CommunicationResult |
| 8 | `src/probos/startup/communication.py` | MODIFY — create ToolPermissionStore, wire to ToolRegistry |
| 9 | `src/probos/runtime.py` | MODIFY — wire tool_permission_store |

Shutdown entry needed (ToolPermissionStore has SQLite).

---

## Change 1 — `src/probos/tools/protocol.py` (MODIFY)

### 1a. Add ToolPermission enum

After the `ToolType` enum (line 26), add:

```python
class ToolPermission(str, Enum):
    """Additive CRUD+O permission levels (AD-423b).

    Each level includes the powers of all lower levels.
    NONE < OBSERVE < READ < WRITE < FULL.
    """

    NONE = "none"          # No access
    OBSERVE = "observe"    # Passive monitoring, no data retrieval
    OBSERVE = "observe"    # Passive monitoring only
    READ = "read"          # Query/retrieve, no mutations
    WRITE = "write"        # Create, modify (includes read)
    FULL = "full"          # Delete, destructive ops (includes write)


# Numeric ordering for comparison
_PERMISSION_ORDER: dict[ToolPermission, int] = {
    ToolPermission.NONE: 0,
    ToolPermission.OBSERVE: 1,
    ToolPermission.READ: 2,
    ToolPermission.WRITE: 3,
    ToolPermission.FULL: 4,
}


def permission_includes(held: ToolPermission, required: ToolPermission) -> bool:
    """Does `held` permission include `required`?

    Additive: WRITE includes READ includes OBSERVE.
    """
    return _PERMISSION_ORDER[held] >= _PERMISSION_ORDER[required]
```

### 1b. Add Concurrency enum

After the `ToolPermission` section:

```python
class ToolConcurrency(str, Enum):
    """Tool concurrency mode (AD-423b LOTO)."""

    CONCURRENT = "concurrent"  # Multiple agents can use simultaneously
    EXCLUSIVE = "exclusive"    # Only one agent at a time (LOTO)
```

### 1c. Add ToolAccessGrant dataclass

After `ToolPreference` (line 151), add:

```python
@dataclass(frozen=True)
class ToolAccessGrant:
    """Captain-issued per-agent tool permission override.

    Grants elevate access above the default_permissions matrix.
    Restrictions lower access below the default. Both survive restart
    (SQLite-backed via ToolPermissionStore).
    """

    id: str
    agent_id: str           # Target — sovereign_id or agent slot ID
    tool_id: str
    permission: ToolPermission
    is_restriction: bool = False   # True = restrict down, False = grant up
    reason: str = ""
    issued_by: str = "captain"
    issued_at: float = 0.0
    expires_at: float | None = None  # None = until revoked
    revoked: bool = False
    revoked_at: float | None = None
```

### 1d. Add default_permissions and LOTO fields to ToolRegistration

Extend the `ToolRegistration` dataclass (line 99). Add these fields after `registered_at` (line 113):

```python
    # AD-423b: Permission & scoping fields
    default_permissions: dict[str, str] = field(default_factory=dict)
    # Maps Rank value → ToolPermission value, e.g.:
    # {"ensign": "read", "lieutenant": "write", "commander": "write", "senior_officer": "full"}
    # Empty dict = ship-wide default (READ for all ranks)

    restricted_to: list[str] | None = None
    # If set, only these agent IDs/types can access (within scope)

    concurrency: str = "concurrent"  # "concurrent" | "exclusive"
    lock_timeout_seconds: float | None = None  # Auto-release for exclusive tools
```

### 1e. Update to_dict() on ToolRegistration

Add the new fields to the `to_dict()` return (line 123):

```python
    def to_dict(self) -> dict[str, Any]:
        """Serialize for API responses."""
        return {
            "tool_id": self.tool.tool_id,
            "name": self.tool.name,
            "tool_type": self.tool.tool_type.value,
            "description": self.tool.description,
            "domain": self.domain,
            "department": self.department,
            "tags": self.tags,
            "provider": self.provider,
            "enabled": self.enabled,
            "input_schema": self.tool.input_schema,
            "output_schema": self.tool.output_schema,
            "default_permissions": self.default_permissions,
            "restricted_to": self.restricted_to,
            "concurrency": self.concurrency,
            "lock_timeout_seconds": self.lock_timeout_seconds,
        }
```

---

## Change 2 — `src/probos/tools/registry.py` (MODIFY)

### 2a. Add imports

At the top, extend the imports:

```python
import time
from typing import Any, Callable, Awaitable

from probos.tools.protocol import (
    Tool, ToolRegistration, ToolType, ToolPermission, ToolResult,
    ToolAccessGrant, permission_includes,
)
```

### 2b. Add ToolPermissionDenied exception

After the imports:

```python
class ToolPermissionDenied(Exception):
    """Raised when an agent lacks permission to use a tool."""

    def __init__(self, agent_id: str, tool_id: str, required: ToolPermission, held: ToolPermission, reason: str = ""):
        self.agent_id = agent_id
        self.tool_id = tool_id
        self.required = required
        self.held = held
        self.reason = reason or f"Agent {agent_id} has {held.value} on {tool_id}, needs {required.value}"
        super().__init__(self.reason)
```

### 2c. Add LOTO state to ToolRegistry.__init__

In `__init__` (line 35), add:

```python
        # AD-423b: LOTO lock state (in-memory, volatile)
        self._locks: dict[str, dict[str, Any]] = {}
        # {tool_id: {"holder": agent_id, "locked_at": float, "reason": str, "timeout": float | None}}

        # AD-423b: Permission store (late-bound)
        self._permission_store: Any = None  # ToolPermissionStore, set via set_permission_store()

        # AD-423b: Event callback (late-bound)
        self._emit_event: Callable[..., Any] | None = None
```

### 2d. Add late-binding setters

After `__init__`:

```python
    def set_permission_store(self, store: Any) -> None:
        """Late-bind the ToolPermissionStore (available after startup)."""
        self._permission_store = store

    def set_event_callback(self, fn: Callable[..., Any]) -> None:
        """Late-bind event emission."""
        self._emit_event = fn
```

### 2e. Add resolve_permission() method

The five-layer permission resolution chain:

```python
    def resolve_permission(
        self,
        agent_id: str,
        tool_id: str,
        *,
        agent_department: str | None = None,
        agent_rank: str = "ensign",
        agent_types: list[str] | None = None,
    ) -> ToolPermission:
        """Resolve the effective permission for an agent on a tool.

        Five-layer resolution chain (AD-423b):
        1. Scope filter — can the agent see the tool?
        2. Restriction filter — is the agent in restricted_to?
        3. Rank gate — default_permissions matrix
        4. Captain override — grants/restrictions from ToolPermissionStore

        Returns the effective ToolPermission level.
        """
        reg = self._tools.get(tool_id)
        if not reg or not reg.enabled:
            return ToolPermission.NONE

        # Layer 1: Scope — department match
        if reg.department is not None and agent_department != reg.department:
            return ToolPermission.NONE

        # Layer 2: Restriction — agent allowlist
        if reg.restricted_to is not None:
            agent_ids = [agent_id] + (agent_types or [])
            if not any(aid in reg.restricted_to for aid in agent_ids):
                return ToolPermission.NONE

        # Layer 3: Rank gate — default permissions matrix
        if reg.default_permissions:
            rank_perm_str = reg.default_permissions.get(agent_rank, "none")
            try:
                base_perm = ToolPermission(rank_perm_str)
            except ValueError:
                base_perm = ToolPermission.NONE
        else:
            # No explicit matrix → READ for all ranks (ship-wide default)
            base_perm = ToolPermission.READ

        # Layer 4: Captain override (grant up / restrict down)
        if self._permission_store:
            grants = self._permission_store.get_active_grants_sync(agent_id, tool_id)
            for grant in grants:
                if grant.is_restriction:
                    # Restrict down: use the lower of base and restriction
                    from probos.tools.protocol import _PERMISSION_ORDER
                    if _PERMISSION_ORDER.get(grant.permission, 0) < _PERMISSION_ORDER.get(base_perm, 0):
                        base_perm = grant.permission
                else:
                    # Grant up: use the higher of base and grant
                    from probos.tools.protocol import _PERMISSION_ORDER
                    if _PERMISSION_ORDER.get(grant.permission, 0) > _PERMISSION_ORDER.get(base_perm, 0):
                        base_perm = grant.permission

        return base_perm
```

### 2f. Add check_permission() method

```python
    def check_permission(
        self,
        agent_id: str,
        tool_id: str,
        required: ToolPermission,
        *,
        agent_department: str | None = None,
        agent_rank: str = "ensign",
        agent_types: list[str] | None = None,
    ) -> bool:
        """Check if an agent has at least `required` permission on a tool."""
        held = self.resolve_permission(
            agent_id, tool_id,
            agent_department=agent_department,
            agent_rank=agent_rank,
            agent_types=agent_types,
        )
        return permission_includes(held, required)
```

### 2g. Add check_and_invoke() method

```python
    async def check_and_invoke(
        self,
        agent_id: str,
        tool_id: str,
        params: dict[str, Any],
        *,
        required: ToolPermission = ToolPermission.READ,
        agent_department: str | None = None,
        agent_rank: str = "ensign",
        agent_types: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Permission-checked tool invocation.

        Resolves permission, checks LOTO, then invokes.
        Raises ToolPermissionDenied if permission insufficient.
        Returns ToolResult with error if tool is locked by another agent.
        """
        # Permission check
        held = self.resolve_permission(
            agent_id, tool_id,
            agent_department=agent_department,
            agent_rank=agent_rank,
            agent_types=agent_types,
        )
        if not permission_includes(held, required):
            if self._emit_event:
                self._emit_event("TOOL_PERMISSION_DENIED", {
                    "agent_id": agent_id, "tool_id": tool_id,
                    "required": required.value, "held": held.value,
                })
            raise ToolPermissionDenied(agent_id, tool_id, required, held)

        # LOTO check
        lock = self._locks.get(tool_id)
        if lock and lock["holder"] != agent_id:
            # Check for expired lock
            if lock.get("timeout") and (time.monotonic() - lock["locked_at"]) > lock["timeout"]:
                self._release_lock(tool_id)
            else:
                return ToolResult(
                    error=f"Tool '{tool_id}' is locked by {lock['holder']}: {lock.get('reason', '')}",
                )

        # Invoke
        tool = self.get_tool(tool_id)
        if not tool:
            return ToolResult(error=f"Tool '{tool_id}' not found")

        ctx = dict(context or {})
        ctx.setdefault("agent_id", agent_id)
        ctx["permission"] = held.value
        return await tool.invoke(params, ctx)
```

### 2h. Add LOTO lock/release/break methods

```python
    # ------------------------------------------------------------------
    # LOTO: Lock-Out / Tag-Out (AD-423b)
    # ------------------------------------------------------------------

    def acquire_lock(
        self, tool_id: str, agent_id: str, reason: str = "",
    ) -> bool:
        """Acquire exclusive access to a tool.

        Returns True if lock acquired, False if already held by another.
        Auto-sets timeout from ToolRegistration.lock_timeout_seconds.
        """
        reg = self._tools.get(tool_id)
        if not reg or reg.concurrency != "exclusive":
            return False  # Not an exclusive tool

        existing = self._locks.get(tool_id)
        if existing:
            # Check for expired lock
            if existing.get("timeout") and (time.monotonic() - existing["locked_at"]) > existing["timeout"]:
                self._release_lock(tool_id)
            elif existing["holder"] != agent_id:
                return False  # Held by another

        self._locks[tool_id] = {
            "holder": agent_id,
            "locked_at": time.monotonic(),
            "reason": reason,
            "timeout": reg.lock_timeout_seconds,
        }
        logger.info("LOTO: %s locked by %s (%s)", tool_id, agent_id, reason or "no reason")
        if self._emit_event:
            self._emit_event("TOOL_LOCKED", {
                "tool_id": tool_id, "holder": agent_id, "reason": reason,
            })
        return True

    def release_lock(self, tool_id: str, agent_id: str) -> bool:
        """Release a held lock. Only the holder can release (or Captain via break_lock)."""
        lock = self._locks.get(tool_id)
        if not lock or lock["holder"] != agent_id:
            return False
        self._release_lock(tool_id)
        return True

    def break_lock(self, tool_id: str, reason: str = "") -> bool:
        """Captain override: force-release any lock."""
        if tool_id not in self._locks:
            return False
        holder = self._locks[tool_id]["holder"]
        logger.warning("LOTO: Captain break-lock on %s (was held by %s): %s", tool_id, holder, reason)
        self._release_lock(tool_id)
        return True

    def get_lock(self, tool_id: str) -> dict[str, Any] | None:
        """Get current lock info, or None if unlocked."""
        lock = self._locks.get(tool_id)
        if lock and lock.get("timeout") and (time.monotonic() - lock["locked_at"]) > lock["timeout"]:
            self._release_lock(tool_id)
            return None
        return lock

    def list_locks(self) -> list[dict[str, Any]]:
        """List all active LOTO locks."""
        # Clean expired locks first
        expired = [
            tid for tid, l in self._locks.items()
            if l.get("timeout") and (time.monotonic() - l["locked_at"]) > l["timeout"]
        ]
        for tid in expired:
            self._release_lock(tid)
        return [{"tool_id": tid, **info} for tid, info in self._locks.items()]

    def _release_lock(self, tool_id: str) -> None:
        """Internal: release a lock and emit event."""
        lock = self._locks.pop(tool_id, None)
        if lock:
            logger.info("LOTO: %s unlocked (was %s)", tool_id, lock["holder"])
            if self._emit_event:
                self._emit_event("TOOL_UNLOCKED", {
                    "tool_id": tool_id, "holder": lock["holder"],
                })
```

### 2i. Extend register() to accept new fields

Update the `register()` method signature (line 38) to accept the new fields:

```python
    def register(
        self,
        tool: Tool,
        *,
        domain: str = "*",
        department: str | None = None,
        tags: list[str] | None = None,
        provider: str = "",
        enabled: bool = True,
        default_permissions: dict[str, str] | None = None,
        restricted_to: list[str] | None = None,
        concurrency: str = "concurrent",
        lock_timeout_seconds: float | None = None,
    ) -> ToolRegistration:
```

And pass them through to the `ToolRegistration` constructor:

```python
        reg = ToolRegistration(
            tool=tool,
            domain=domain,
            department=department,
            tags=tags or [],
            provider=provider,
            enabled=enabled,
            default_permissions=default_permissions or {},
            restricted_to=restricted_to,
            concurrency=concurrency,
            lock_timeout_seconds=lock_timeout_seconds,
        )
```

---

## Change 3 — `src/probos/tools/permissions.py` (NEW)

```python
"""AD-423b: ToolPermissionStore — persistent Captain overrides for tool access.

SQLite-backed store for per-agent tool access grants and restrictions.
Follows ClearanceGrantStore pattern (ConnectionFactory, WAL, cache).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Sequence

from probos.protocols import ConnectionFactory
from probos.tools.protocol import ToolAccessGrant, ToolPermission

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_access_grants (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    tool_id TEXT NOT NULL,
    permission TEXT NOT NULL,
    is_restriction INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    issued_by TEXT NOT NULL DEFAULT 'captain',
    issued_at REAL NOT NULL,
    expires_at REAL,
    revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at REAL
);
CREATE INDEX IF NOT EXISTS idx_tag_agent ON tool_access_grants(agent_id);
CREATE INDEX IF NOT EXISTS idx_tag_tool ON tool_access_grants(tool_id);
CREATE INDEX IF NOT EXISTS idx_tag_active ON tool_access_grants(revoked, expires_at);
"""


class ToolPermissionStore:
    """Persistent store for Captain tool access overrides.

    SQLite-backed with in-memory cache for sync access.
    Follows ClearanceGrantStore pattern exactly.

    Public API:
        start() / stop() — lifecycle
        issue_grant(...) → ToolAccessGrant
        revoke_grant(grant_id) → bool
        get_active_grants_sync(agent_id, tool_id?) → list[ToolAccessGrant]
        list_grants(active_only=True) → list[ToolAccessGrant]
    """

    def __init__(
        self,
        db_path: str = "",
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._db_path = db_path
        self._db: Any = None
        self._cache: list[ToolAccessGrant] = []
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    async def start(self) -> None:
        if self._db_path:
            self._db = await self._connection_factory.connect(self._db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            await self._load_cache()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _load_cache(self) -> None:
        """Load all active grants into cache."""
        self._cache.clear()
        if not self._db:
            return
        now = time.time()
        async with self._db.execute(
            "SELECT * FROM tool_access_grants WHERE revoked = 0 AND (expires_at IS NULL OR expires_at > ?)",
            (now,),
        ) as cur:
            async for row in cur:
                self._cache.append(self._row_to_grant(row))

    def _row_to_grant(self, row: Any) -> ToolAccessGrant:
        return ToolAccessGrant(
            id=row[0],
            agent_id=row[1],
            tool_id=row[2],
            permission=ToolPermission(row[3]),
            is_restriction=bool(row[4]),
            reason=row[5],
            issued_by=row[6],
            issued_at=row[7],
            expires_at=row[8],
            revoked=bool(row[9]),
            revoked_at=row[10],
        )

    async def issue_grant(
        self,
        agent_id: str,
        tool_id: str,
        permission: ToolPermission,
        *,
        is_restriction: bool = False,
        reason: str = "",
        issued_by: str = "captain",
        expires_at: float | None = None,
    ) -> ToolAccessGrant:
        """Issue a tool access grant or restriction."""
        grant = ToolAccessGrant(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            tool_id=tool_id,
            permission=permission,
            is_restriction=is_restriction,
            reason=reason,
            issued_by=issued_by,
            issued_at=time.time(),
            expires_at=expires_at,
        )
        if self._db:
            await self._db.execute(
                "INSERT INTO tool_access_grants "
                "(id, agent_id, tool_id, permission, is_restriction, reason, issued_by, issued_at, expires_at, revoked, revoked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)",
                (grant.id, grant.agent_id, grant.tool_id, grant.permission.value,
                 int(grant.is_restriction), grant.reason, grant.issued_by,
                 grant.issued_at, grant.expires_at),
            )
            await self._db.commit()
        self._cache.append(grant)
        logger.info(
            "Tool access %s issued: %s → %s = %s%s",
            "restriction" if is_restriction else "grant",
            agent_id, tool_id, permission.value,
            f" (expires {expires_at})" if expires_at else "",
        )
        return grant

    async def revoke_grant(self, grant_id: str) -> bool:
        """Soft-revoke a grant (retained for audit)."""
        now = time.time()
        if self._db:
            result = await self._db.execute(
                "UPDATE tool_access_grants SET revoked = 1, revoked_at = ? WHERE id = ? AND revoked = 0",
                (now, grant_id),
            )
            await self._db.commit()
            if result.rowcount == 0:
                return False
        # Update cache
        self._cache = [g for g in self._cache if g.id != grant_id]
        logger.info("Tool access grant revoked: %s", grant_id)
        return True

    def get_active_grants_sync(
        self, agent_id: str, tool_id: str | None = None,
    ) -> list[ToolAccessGrant]:
        """Sync read from cache — zero I/O.

        Filters expired grants lazily (removes from cache on access).
        """
        now = time.time()
        active: list[ToolAccessGrant] = []
        expired_ids: list[str] = []
        for g in self._cache:
            if g.agent_id != agent_id:
                continue
            if tool_id is not None and g.tool_id != tool_id:
                continue
            if g.expires_at is not None and g.expires_at <= now:
                expired_ids.append(g.id)
                continue
            active.append(g)
        if expired_ids:
            self._cache = [g for g in self._cache if g.id not in expired_ids]
        return active

    async def list_grants(self, *, active_only: bool = True) -> list[ToolAccessGrant]:
        """List all grants from the database."""
        if not self._db:
            return list(self._cache)
        if active_only:
            now = time.time()
            async with self._db.execute(
                "SELECT * FROM tool_access_grants WHERE revoked = 0 AND (expires_at IS NULL OR expires_at > ?) ORDER BY issued_at DESC",
                (now,),
            ) as cur:
                return [self._row_to_grant(row) async for row in cur]
        else:
            async with self._db.execute(
                "SELECT * FROM tool_access_grants ORDER BY issued_at DESC",
            ) as cur:
                return [self._row_to_grant(row) async for row in cur]
```

---

## Change 4 — `src/probos/experience/commands/commands_tool_access.py` (NEW)

```python
"""AD-423b: /tool-access shell command — Captain tool permission management.

Subcommands:
  /tool-access grant <callsign> <tool_id> <permission> [duration_hours] [reason]
  /tool-access restrict <callsign> <tool_id> <permission> [reason]
  /tool-access revoke <grant_id>
  /tool-access break-lock <tool_id> [reason]
  /tool-access list [--grants | --locks | --all]
  /tool-access check <callsign> <tool_id>
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

COMMANDS = {
    "grant": "Grant elevated tool access to an agent",
    "restrict": "Restrict tool access for an agent",
    "revoke": "Revoke a tool access grant/restriction",
    "break-lock": "Force-release a LOTO lock (Captain override)",
    "list": "List active grants and/or locks",
    "check": "Check an agent's effective permission on a tool",
}


async def cmd_tool_access(runtime: Any, console: Any, args: str) -> None:
    """Dispatch /tool-access subcommands."""
    parts = args.strip().split(None, 1)
    sub = parts[0] if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

    dispatch = {
        "grant": _cmd_grant,
        "restrict": _cmd_restrict,
        "revoke": _cmd_revoke,
        "break-lock": _cmd_break_lock,
        "list": _cmd_list,
        "check": _cmd_check,
    }

    handler = dispatch.get(sub)
    if not handler:
        console.print("[bold]Usage:[/bold] /tool-access <grant|restrict|revoke|break-lock|list|check>")
        for sub_name, desc in COMMANDS.items():
            console.print(f"  {sub_name:12s} — {desc}")
        return

    await handler(runtime, console, rest)


async def _cmd_grant(runtime: Any, console: Any, args: str) -> None:
    """Grant elevated tool access: /tool-access grant <callsign> <tool_id> <permission> [hours] [reason]."""
    parts = args.strip().split()
    if len(parts) < 3:
        console.print("[red]Usage: /tool-access grant <callsign> <tool_id> <permission> [duration_hours] [reason][/red]")
        return

    callsign, tool_id, perm_str = parts[0], parts[1], parts[2]
    duration_hours = None
    reason = ""

    if len(parts) > 3:
        try:
            duration_hours = float(parts[3])
            reason = " ".join(parts[4:])
        except ValueError:
            reason = " ".join(parts[3:])

    # Resolve callsign to agent ID
    agent_id = _resolve_callsign(runtime, callsign)
    if not agent_id:
        console.print(f"[red]Unknown callsign: {callsign}[/red]")
        return

    # Validate permission
    from probos.tools.protocol import ToolPermission
    try:
        permission = ToolPermission(perm_str.lower())
    except ValueError:
        valid = ", ".join(p.value for p in ToolPermission)
        console.print(f"[red]Invalid permission: {perm_str}. Valid: {valid}[/red]")
        return

    # Validate tool exists
    store = getattr(runtime, "tool_permission_store", None)
    registry = getattr(runtime, "tool_registry", None)
    if not store or not registry:
        console.print("[red]Tool permission system not available[/red]")
        return

    if not registry.get(tool_id):
        console.print(f"[red]Unknown tool: {tool_id}[/red]")
        return

    import time
    expires_at = (time.time() + duration_hours * 3600) if duration_hours else None

    grant = await store.issue_grant(
        agent_id=agent_id,
        tool_id=tool_id,
        permission=permission,
        reason=reason or f"Captain grant via /tool-access",
        expires_at=expires_at,
    )
    dur_str = f" ({duration_hours}h)" if duration_hours else " (permanent)"
    console.print(f"[green]Granted {perm_str} on {tool_id} to {callsign}{dur_str}[/green]")
    console.print(f"  Grant ID: {grant.id[:12]}...")


async def _cmd_restrict(runtime: Any, console: Any, args: str) -> None:
    """Restrict tool access: /tool-access restrict <callsign> <tool_id> <permission> [reason]."""
    parts = args.strip().split()
    if len(parts) < 3:
        console.print("[red]Usage: /tool-access restrict <callsign> <tool_id> <max_permission> [reason][/red]")
        return

    callsign, tool_id, perm_str = parts[0], parts[1], parts[2]
    reason = " ".join(parts[3:])

    agent_id = _resolve_callsign(runtime, callsign)
    if not agent_id:
        console.print(f"[red]Unknown callsign: {callsign}[/red]")
        return

    from probos.tools.protocol import ToolPermission
    try:
        permission = ToolPermission(perm_str.lower())
    except ValueError:
        valid = ", ".join(p.value for p in ToolPermission)
        console.print(f"[red]Invalid permission: {perm_str}. Valid: {valid}[/red]")
        return

    store = getattr(runtime, "tool_permission_store", None)
    if not store:
        console.print("[red]Tool permission system not available[/red]")
        return

    grant = await store.issue_grant(
        agent_id=agent_id,
        tool_id=tool_id,
        permission=permission,
        is_restriction=True,
        reason=reason or f"Captain restriction via /tool-access",
    )
    console.print(f"[yellow]Restricted {callsign} to max {perm_str} on {tool_id}[/yellow]")
    console.print(f"  Grant ID: {grant.id[:12]}...")


async def _cmd_revoke(runtime: Any, console: Any, args: str) -> None:
    """Revoke a grant: /tool-access revoke <grant_id>."""
    grant_id = args.strip()
    if not grant_id:
        console.print("[red]Usage: /tool-access revoke <grant_id>[/red]")
        return

    store = getattr(runtime, "tool_permission_store", None)
    if not store:
        console.print("[red]Tool permission system not available[/red]")
        return

    # Support partial ID match
    grants = await store.list_grants(active_only=True)
    matches = [g for g in grants if g.id.startswith(grant_id)]
    if not matches:
        console.print(f"[red]No active grant matching: {grant_id}[/red]")
        return
    if len(matches) > 1:
        console.print(f"[red]Ambiguous ID, {len(matches)} matches. Provide more characters.[/red]")
        return

    ok = await store.revoke_grant(matches[0].id)
    if ok:
        console.print(f"[green]Grant {matches[0].id[:12]}... revoked[/green]")
    else:
        console.print(f"[red]Failed to revoke grant[/red]")


async def _cmd_break_lock(runtime: Any, console: Any, args: str) -> None:
    """Break a LOTO lock: /tool-access break-lock <tool_id> [reason]."""
    parts = args.strip().split(None, 1)
    if not parts:
        console.print("[red]Usage: /tool-access break-lock <tool_id> [reason][/red]")
        return

    tool_id = parts[0]
    reason = parts[1] if len(parts) > 1 else "Captain break-lock"

    registry = getattr(runtime, "tool_registry", None)
    if not registry:
        console.print("[red]Tool registry not available[/red]")
        return

    ok = registry.break_lock(tool_id, reason)
    if ok:
        console.print(f"[green]Lock on {tool_id} broken[/green]")
    else:
        console.print(f"[yellow]No active lock on {tool_id}[/yellow]")


async def _cmd_list(runtime: Any, console: Any, args: str) -> None:
    """List grants and/or locks: /tool-access list [--grants|--locks|--all]."""
    flag = args.strip()
    show_grants = flag in ("", "--grants", "--all")
    show_locks = flag in ("", "--locks", "--all")

    registry = getattr(runtime, "tool_registry", None)
    store = getattr(runtime, "tool_permission_store", None)

    if show_grants and store:
        grants = await store.list_grants(active_only=True)
        if grants:
            console.print(f"[bold]Active grants/restrictions ({len(grants)}):[/bold]")
            for g in grants:
                kind = "RESTRICT" if g.is_restriction else "GRANT"
                exp = f" expires {g.expires_at:.0f}" if g.expires_at else " permanent"
                console.print(f"  {g.id[:12]}  {kind:8s} {g.agent_id[:16]:16s} → {g.tool_id:20s} = {g.permission.value}{exp}")
        else:
            console.print("[dim]No active grants[/dim]")

    if show_locks and registry:
        locks = registry.list_locks()
        if locks:
            console.print(f"[bold]Active LOTO locks ({len(locks)}):[/bold]")
            for l in locks:
                console.print(f"  {l['tool_id']:20s} held by {l['holder']} ({l.get('reason', '')})")
        else:
            console.print("[dim]No active locks[/dim]")


async def _cmd_check(runtime: Any, console: Any, args: str) -> None:
    """Check effective permission: /tool-access check <callsign> <tool_id>."""
    parts = args.strip().split()
    if len(parts) < 2:
        console.print("[red]Usage: /tool-access check <callsign> <tool_id>[/red]")
        return

    callsign, tool_id = parts[0], parts[1]
    agent_id = _resolve_callsign(runtime, callsign)
    if not agent_id:
        console.print(f"[red]Unknown callsign: {callsign}[/red]")
        return

    registry = getattr(runtime, "tool_registry", None)
    if not registry:
        console.print("[red]Tool registry not available[/red]")
        return

    # Get agent context
    from probos.cognitive.standing_orders import get_department
    from probos.crew_profile import Rank
    dept = get_department(callsign) or ""
    agent = runtime.registry.get(agent_id) if hasattr(runtime, 'registry') else None
    trust = 0.5
    if agent and hasattr(runtime, 'trust_network'):
        trust = runtime.trust_network.get_trust(agent_id)
    rank = Rank.from_trust(trust)

    perm = registry.resolve_permission(
        agent_id, tool_id,
        agent_department=dept,
        agent_rank=rank.value,
        agent_types=[callsign] if callsign != agent_id else None,
    )
    console.print(f"[bold]{callsign}[/bold] on [bold]{tool_id}[/bold]: {perm.value}")


def _resolve_callsign(runtime: Any, callsign: str) -> str | None:
    """Resolve a callsign to agent ID."""
    cr = getattr(runtime, "callsign_registry", None)
    if cr:
        agent_id = cr.resolve(callsign)
        if agent_id:
            return agent_id
    # Fallback: try as direct agent_type
    if hasattr(runtime, "registry"):
        agent = runtime.registry.get(callsign)
        if agent:
            return agent.id
    return None
```

---

## Change 5 — `src/probos/experience/shell.py` (MODIFY)

### 5a. Add to COMMANDS help dict

After the `/grant` entry (line 96), add:

```python
        "/tool-access": "Manage tool permissions (grant/restrict/revoke/break-lock/list/check)",
```

### 5b. Add to dispatch dict

In the dispatch dict (around line 220), add alongside the `/grant` entry:

```python
        "/tool-access": lambda: commands_tool_access.cmd_tool_access(rt, con, arg),
```

And add the import at the top of the dispatch method:

```python
        from probos.experience.commands import commands_tool_access
```

---

## Change 6 — `src/probos/events.py` (MODIFY)

Add three new event types. Find a suitable location near the existing tool/permission-related events (or at the end of the event type constants):

```python
    # AD-423b: Tool permissions
    TOOL_PERMISSION_DENIED = "tool_permission_denied"
    TOOL_LOCKED = "tool_locked"
    TOOL_UNLOCKED = "tool_unlocked"
```

---

## Change 7 — `src/probos/startup/results.py` (MODIFY)

### 7a. Add TYPE_CHECKING import

In the `if TYPE_CHECKING:` block, add:

```python
    from probos.tools.permissions import ToolPermissionStore
```

### 7b. Add field to CommunicationResult

After `tool_registry` in `CommunicationResult`, add:

```python
    tool_permission_store: "ToolPermissionStore | None"
```

---

## Change 8 — `src/probos/startup/communication.py` (MODIFY)

### 8a. Create ToolPermissionStore

After the ToolRegistry creation block and before the return statement, insert:

```python
    # --- Tool Permission Store (AD-423b) ---
    from probos.tools.permissions import ToolPermissionStore

    tool_permission_store = ToolPermissionStore(
        db_path=str(data_dir / "tool_permissions.db"),
    )
    await tool_permission_store.start()
    tool_registry.set_permission_store(tool_permission_store)
    tool_registry.set_event_callback(emit_event_fn)
    logger.info("tool-permission-store started")
```

### 8b. Add to CommunicationResult return

Add `tool_permission_store=tool_permission_store` to the return statement.

---

## Change 9 — `src/probos/runtime.py` (MODIFY)

### 9a. Class-level type annotation

In the deferred-init annotations section (around line 200), after `tool_registry`, add:

```python
    tool_permission_store: ToolPermissionStore | None
```

And add the TYPE_CHECKING import:

```python
    from probos.tools.permissions import ToolPermissionStore
```

### 9b. `__init__` initialization

After the tool_registry initialization, add:

```python
        # --- Tool Permission Store (AD-423b) ---
        self.tool_permission_store: ToolPermissionStore | None = None
```

### 9c. `start()` assignment

After `self.tool_registry = comm.tool_registry`, add:

```python
        self.tool_permission_store = comm.tool_permission_store
```

### 9d. Shutdown — `src/probos/startup/shutdown.py` (MODIFY)

After the clearance grant store shutdown block (line 181), add:

```python
    # AD-423b: Tool permission store
    if hasattr(runtime, 'tool_permission_store') and runtime.tool_permission_store:
        await runtime.tool_permission_store.stop()
        runtime.tool_permission_store = None
```

---

## Engineering Principles Compliance

| Principle | Application |
|-----------|-------------|
| **Single Responsibility** | `permissions.py` = persistence only, `registry.py` = resolution + LOTO only, `protocol.py` = types only |
| **Open/Closed** | New permission levels added to enum without modifying resolution chain |
| **Interface Segregation** | `ToolPermissionStore` is a focused persistence service — not coupled to registry logic |
| **Dependency Inversion** | Registry depends on abstract `ToolPermissionStore` via late-binding setter, not constructor injection |
| **Law of Demeter** | `_resolve_callsign()` is a helper — shell commands don't reach through runtime deeply |
| **Cloud-Ready Storage** | ToolPermissionStore follows ConnectionFactory protocol |
| **Fail Fast** | `ToolPermissionDenied` exception with rich context (agent, tool, held vs required) |
| **Defense in Depth** | Permission checked at registry level; AD-423c ToolContext will add agent-side enforcement |
| **DRY** | `permission_includes()` is a single comparison function reused throughout |

---

## Tests — `tests/test_ad423b_tool_permissions.py` (NEW)

28 tests across 7 classes.

### Class 1: `TestToolPermission` (3 tests)

```
test_permission_ordering — NONE < OBSERVE < READ < WRITE < FULL via _PERMISSION_ORDER
test_permission_includes — WRITE includes READ, READ does not include WRITE
test_permission_enum_values — All 5 values present as str enum
```

### Class 2: `TestToolRegistrationExtensions` (3 tests)

```
test_default_permissions_field — ToolRegistration default_permissions dict works
test_restricted_to_field — restricted_to list filters correctly
test_concurrency_and_timeout — concurrency="exclusive", lock_timeout_seconds=30.0
```

### Class 3: `TestResolvePermission` (6 tests)

```
test_disabled_tool_returns_none — disabled tool → NONE
test_department_mismatch_returns_none — agent in engineering, tool scoped to security → NONE
test_restricted_to_excludes — agent not in restricted_to → NONE
test_rank_gate_default_matrix — ensign gets "read", commander gets "write" from default_permissions
test_no_matrix_defaults_to_read — empty default_permissions → READ for all
test_captain_override_grant_up — Captain grant elevates above rank gate
```

### Class 4: `TestCheckAndInvoke` (4 tests)

```
test_permission_denied_raises — insufficient permission → ToolPermissionDenied exception
test_permission_denied_emits_event — TOOL_PERMISSION_DENIED event emitted
test_locked_tool_returns_error — tool locked by another → ToolResult with error
test_successful_invoke — permission OK + not locked → tool invoked, ToolResult returned
```

### Class 5: `TestLOTO` (6 tests)

```
test_acquire_release — acquire returns True, release returns True, lock cleared
test_acquire_blocked — lock held by another → acquire returns False
test_acquire_reentrant — same agent can re-acquire (idempotent)
test_timeout_auto_expire — expired lock auto-releases on next acquire
test_break_lock — Captain break_lock force-releases, emits TOOL_UNLOCKED
test_concurrent_tool_rejects_lock — concurrent tool → acquire returns False
```

### Class 6: `TestToolPermissionStore` (4 tests)

```
test_issue_and_cache — issue_grant adds to DB and cache
test_revoke_soft_delete — revoke_grant removes from cache, retained in DB
test_get_active_grants_sync — sync reads from cache, filters expired
test_list_grants_active_vs_all — active_only=True excludes revoked, all returns everything
```

### Class 7: `TestToolAccessCommand` (2 tests)

```
test_cmd_grant_and_list — /tool-access grant followed by /tool-access list shows the grant
test_cmd_break_lock — /tool-access break-lock releases a held lock
```

---

## Tracking Updates

### PROGRESS.md

Add to the status line:

```
AD-423b COMPLETE — Tool Permissions & Scoping (CRUD+O model, 5-layer resolution, LOTO, Captain overrides, /tool-access command)
```

### DECISIONS.md

Add decision record:

```markdown
### AD-423b: Tool Permissions & Scoping

| Aspect | Decision |
|--------|----------|
| **Scope** | CRUD+O permission model, 5-layer resolution chain, LOTO locks, Captain override store, /tool-access command |
| **Permission levels** | NONE < OBSERVE < READ < WRITE < FULL (additive, str enum) |
| **Resolution chain** | Scope → Restriction → Rank gate → Captain override |
| **LOTO** | In-memory volatile locks, timeout auto-expire, Captain break-lock |
| **Captain overrides** | SQLite-backed ToolPermissionStore (ConnectionFactory, WAL), grant up + restrict down |
| **Deny-by-default** | Empty default_permissions → READ; unrecognized rank → NONE |
| **No queue** | LOTO queue-by-tier deferred — simple lock/release/break for now |
| **No agent-side enforcement** | check_and_invoke() on registry; ToolContext enforcement deferred to AD-423c |
| **Unlocks** | AD-423c (ToolContext), AD-548 (trust-gated SWE tools) |
```

### roadmap.md

Update AD-423b status from `(planned, OSS)` to `(complete, OSS)`.

### GitHub

Close issue #145 with completion comment.

---

## Verification

```bash
# Run AD-423b tests
uv run python -m pytest tests/test_ad423b_tool_permissions.py -v

# Verify no regression on AD-423a tests
uv run python -m pytest tests/test_ad423a_tool_foundation.py -v

# Import check
uv run python -c "from probos.tools.protocol import ToolPermission, ToolConcurrency, ToolAccessGrant, permission_includes; from probos.tools.permissions import ToolPermissionStore; from probos.tools.registry import ToolPermissionDenied; print('All imports OK')"
```
