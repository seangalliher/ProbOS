# AD-622: Special Access Grants (ClearanceGrant)

## Context

AD-620 (complete) established billet-based clearance — each post in `organization.yaml` carries a `clearance` field, and `effective_recall_tier(rank, billet_clearance)` computes the max of rank-derived and billet-derived tiers. AD-621 (complete) made channel visibility subscription-driven via the ontology.

AD-622 adds the third input to the clearance equation: **temporary, Captain-issued special access grants**. This is the SAP (Special Access Program) analog — time-limited, scoped, revocable elevated access for specific operational needs (security investigations, cross-department projects, incident response).

**Design reference:** `docs/research/clearance-system-design.md` (lines 163-186), Issue #208.

**Existing patterns to follow:**
- `BridgeAlertService` for SQLite-backed service creation in `communication.py`
- `commands_alert.py` for shell command module structure
- `ConnManager` for authority delegation semantics
- `ConnectionFactory` protocol for Cloud-Ready Storage

## Scope

**In scope:**
1. `ClearanceGrant` dataclass in `earned_agency.py`
2. `ClearanceGrantStore` — SQLite-backed persistent grant storage (new file)
3. Extend `effective_recall_tier()` to accept grants as a third input
4. Shell `/grant` command (issue, revoke, list)
5. Service wiring (communication.py, results.py, runtime.py, shutdown.py, shell.py)
6. Grant resolution helpers at both call sites (cognitive_agent.py, proactive.py)

**Out of scope:**
- API endpoints (future HXI integration)
- First Officer delegation (First Officer can issue grants via `/conn` authority — existing ConnManager handles this)
- Ward Room notifications when grants are issued/revoked (future enhancement)
- Channel visibility changes based on grants (AD-621 handles visibility, grants handle recall tier only)

## Engineering Principles Compliance

- **SOLID/S**: `ClearanceGrantStore` owns persistence only. `effective_recall_tier()` owns tier computation. Shell commands own user interaction. Each has one reason to change.
- **SOLID/O**: `effective_recall_tier()` gains a new parameter with default `()` — all existing callers continue working without changes until wired.
- **SOLID/D**: Grant store accepts optional `ConnectionFactory` — commercial overlay can swap SQLite for Postgres.
- **Cloud-Ready Storage**: `ClearanceGrantStore` follows `ConnectionFactory` protocol pattern from `ward_room/service.py`.
- **Law of Demeter**: New `resolve_active_grants(agent_id, grant_store)` function in `earned_agency.py` — callers don't reach through runtime to query grants directly.
- **Fail Fast**: Grant store unavailable → log-and-degrade (return empty list, don't crash recall).
- **DRY**: `_TIER_ORDER` dict reused for grant tier comparison (already exists from AD-620).

## Changes

### 1. `src/probos/earned_agency.py` — `ClearanceGrant` dataclass + `effective_recall_tier()` extension

**Add `ClearanceGrant` dataclass after `RecallTier` (after line 23):**

```python
@dataclass(frozen=True)
class ClearanceGrant:
    """AD-622: Temporary elevated access record.

    Captain-issued, time-limited, scoped, revocable.
    SAP analog for project/duty-based elevated recall access.
    """
    id: str                         # UUID
    target_agent_id: str            # Who receives the grant (sovereign ID)
    recall_tier: RecallTier         # Granted tier level
    scope: str = "general"          # "general" | "project:{name}" | "investigation:{id}"
    reason: str = ""                # Justification (audit trail)
    issued_by: str = "captain"      # Issuer identity
    issued_at: float = 0.0          # Timestamp
    expires_at: float | None = None # None = until revoked
    revoked: bool = False           # Soft-delete
    revoked_at: float | None = None # When revoked (audit trail)
```

**Note:** Import `dataclass` from `dataclasses` (already imported for other uses in this file — check). Import `time` for timestamp defaults.

**Extend `effective_recall_tier()` signature (line 45):**

```python
def effective_recall_tier(
    rank: Rank | None,
    billet_clearance: str = "",
    grants: Sequence[ClearanceGrant] = (),
) -> RecallTier:
    """AD-620/622: Resolve effective recall tier — max(rank-based, billet-based, grant-based).

    Billet clearance comes from the Post.clearance field in organization.yaml.
    Grants come from active ClearanceGrants issued by the Captain.
    Takes the highest of all three sources.
    """
    rank_tier = recall_tier_from_rank(rank) if rank else RecallTier.ENHANCED

    if not billet_clearance:
        best = rank_tier
    else:
        try:
            billet_tier = RecallTier(billet_clearance.lower())
        except ValueError:
            billet_tier = rank_tier
        best = billet_tier if _TIER_ORDER.get(billet_tier, 0) > _TIER_ORDER.get(rank_tier, 0) else rank_tier

    # AD-622: Apply active grants
    for grant in grants:
        grant_order = _TIER_ORDER.get(grant.recall_tier, 0)
        if grant_order > _TIER_ORDER.get(best, 0):
            best = grant.recall_tier

    return best
```

**Add `resolve_active_grants()` helper (after `resolve_billet_clearance()`, around line 86):**

```python
def resolve_active_grants(
    agent_id: str,
    grant_store: Any | None,
) -> list[ClearanceGrant]:
    """AD-622: Look up active grants for an agent.

    Returns empty list if grant store unavailable. Law of Demeter —
    callers don't reach through runtime to query grants directly.

    NOTE: This is a synchronous wrapper — grant_store.get_active_grants_sync()
    returns cached grants. See ClearanceGrantStore for cache details.
    """
    if not grant_store:
        return []
    try:
        return grant_store.get_active_grants_sync(agent_id)
    except Exception:
        return []
```

**Builder decision needed — sync vs async:** `effective_recall_tier()` is called in both sync and async contexts. The `resolve_active_grants()` helper must be sync (like `resolve_billet_clearance()`). The grant store should maintain an in-memory cache of active grants that's populated at startup and updated on issue/revoke. `get_active_grants_sync()` reads from cache; `issue_grant()`/`revoke_grant()` update cache + DB. This mirrors how `ChannelManager` caches channels in memory.

**Import needed:** `from collections.abc import Sequence` at top of file.

### 2. NEW FILE: `src/probos/clearance_grants.py` — `ClearanceGrantStore`

```python
"""AD-622: Persistent storage for ClearanceGrant records.

SQLite-backed with in-memory cache for sync access from
effective_recall_tier(). Follows ConnectionFactory pattern
for cloud-ready storage.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from probos.earned_agency import ClearanceGrant, RecallTier

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clearance_grants (
    id TEXT PRIMARY KEY,
    target_agent_id TEXT NOT NULL,
    recall_tier TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'general',
    reason TEXT NOT NULL DEFAULT '',
    issued_by TEXT NOT NULL DEFAULT 'captain',
    issued_at REAL NOT NULL,
    expires_at REAL,
    revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at REAL
);
CREATE INDEX IF NOT EXISTS idx_grants_target ON clearance_grants(target_agent_id);
CREATE INDEX IF NOT EXISTS idx_grants_active ON clearance_grants(revoked, expires_at);
"""


class ClearanceGrantStore:
    """Persistent grant storage with sync cache for effective_recall_tier().

    - issue_grant() / revoke_grant() write to DB + update cache
    - get_active_grants_sync() reads from cache (zero I/O)
    - start() loads all active grants into cache
    - stop() closes DB connection
    """

    def __init__(
        self,
        db_path: str = "",
        connection_factory: "ConnectionFactory | None" = None,
    ) -> None:
        self.db_path = db_path
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory
        self._db: Any = None
        # In-memory cache: agent_id -> list of active grants
        self._cache: dict[str, list[ClearanceGrant]] = {}

    async def start(self) -> None:
        if self.db_path:
            self._db = await self._connection_factory.connect(self.db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            await self._refresh_cache()
            logger.info("ClearanceGrantStore started (db=%s)", self.db_path)

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _refresh_cache(self) -> None:
        """Load all active grants into memory cache."""
        self._cache.clear()
        if not self._db:
            return
        now = time.time()
        async with self._db.execute(
            "SELECT id, target_agent_id, recall_tier, scope, reason, "
            "issued_by, issued_at, expires_at, revoked, revoked_at "
            "FROM clearance_grants WHERE revoked = 0 "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (now,),
        ) as cursor:
            async for row in cursor:
                grant = self._row_to_grant(row)
                self._cache.setdefault(grant.target_agent_id, []).append(grant)

    def get_active_grants_sync(self, agent_id: str) -> list[ClearanceGrant]:
        """Sync cache read — zero I/O. Used by effective_recall_tier()."""
        now = time.time()
        grants = self._cache.get(agent_id, [])
        # Filter expired grants from cache (lazy cleanup)
        active = [g for g in grants if g.expires_at is None or g.expires_at > now]
        if len(active) != len(grants):
            self._cache[agent_id] = active
        return active

    async def issue_grant(
        self,
        target_agent_id: str,
        recall_tier: RecallTier,
        scope: str = "general",
        reason: str = "",
        issued_by: str = "captain",
        expires_at: float | None = None,
    ) -> ClearanceGrant:
        """Issue a new grant. Writes to DB + updates cache."""
        grant = ClearanceGrant(
            id=str(uuid.uuid4()),
            target_agent_id=target_agent_id,
            recall_tier=recall_tier,
            scope=scope,
            reason=reason,
            issued_by=issued_by,
            issued_at=time.time(),
            expires_at=expires_at,
        )
        if self._db:
            await self._db.execute(
                "INSERT INTO clearance_grants "
                "(id, target_agent_id, recall_tier, scope, reason, "
                "issued_by, issued_at, expires_at, revoked, revoked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)",
                (grant.id, grant.target_agent_id, grant.recall_tier.value,
                 grant.scope, grant.reason, grant.issued_by,
                 grant.issued_at, grant.expires_at),
            )
            await self._db.commit()
        # Update cache
        self._cache.setdefault(grant.target_agent_id, []).append(grant)
        logger.info(
            "AD-622: Grant issued — %s gets %s (scope=%s, by=%s, expires=%s)",
            target_agent_id[:12], recall_tier.value, scope, issued_by,
            expires_at,
        )
        return grant

    async def revoke_grant(self, grant_id: str) -> bool:
        """Soft-delete revocation. Returns True if found and revoked."""
        now = time.time()
        if self._db:
            cursor = await self._db.execute(
                "UPDATE clearance_grants SET revoked = 1, revoked_at = ? "
                "WHERE id = ? AND revoked = 0",
                (now, grant_id),
            )
            await self._db.commit()
            if cursor.rowcount == 0:
                return False
        # Update cache — remove from all agent lists
        for agent_id, grants in self._cache.items():
            self._cache[agent_id] = [g for g in grants if g.id != grant_id]
        logger.info("AD-622: Grant revoked — %s", grant_id[:12])
        return True

    async def list_grants(
        self, active_only: bool = True,
    ) -> list[ClearanceGrant]:
        """List grants. active_only=True filters expired/revoked."""
        if not self._db:
            return []
        now = time.time()
        if active_only:
            query = (
                "SELECT id, target_agent_id, recall_tier, scope, reason, "
                "issued_by, issued_at, expires_at, revoked, revoked_at "
                "FROM clearance_grants WHERE revoked = 0 "
                "AND (expires_at IS NULL OR expires_at > ?) "
                "ORDER BY issued_at DESC"
            )
            params = (now,)
        else:
            query = (
                "SELECT id, target_agent_id, recall_tier, scope, reason, "
                "issued_by, issued_at, expires_at, revoked, revoked_at "
                "FROM clearance_grants ORDER BY issued_at DESC"
            )
            params = ()
        grants = []
        async with self._db.execute(query, params) as cursor:
            async for row in cursor:
                grants.append(self._row_to_grant(row))
        return grants

    async def get_grant(self, grant_id: str) -> ClearanceGrant | None:
        """Get a specific grant by ID."""
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT id, target_agent_id, recall_tier, scope, reason, "
            "issued_by, issued_at, expires_at, revoked, revoked_at "
            "FROM clearance_grants WHERE id = ?",
            (grant_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_grant(row) if row else None

    @staticmethod
    def _row_to_grant(row: tuple) -> ClearanceGrant:
        return ClearanceGrant(
            id=row[0],
            target_agent_id=row[1],
            recall_tier=RecallTier(row[2]),
            scope=row[3],
            reason=row[4],
            issued_by=row[5],
            issued_at=row[6],
            expires_at=row[7],
            revoked=bool(row[8]),
            revoked_at=row[9],
        )
```

### 3. NEW FILE: `src/probos/experience/commands/commands_clearance.py` — Shell `/grant` command

Follow the `commands_alert.py` pattern exactly. Subcommands:

```python
"""AD-622: Clearance grant shell commands."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


async def cmd_grant(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Grant management commands: issue, revoke, list."""
    parts = args.split(maxsplit=1) if args else []
    sub = parts[0].lower() if parts else ""

    if sub == "issue":
        await _grant_issue(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "revoke":
        await _grant_revoke(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "list":
        await _grant_list(runtime, console, parts[1] if len(parts) > 1 else "")
    else:
        console.print("[yellow]Usage: /grant <issue|revoke|list> [...][/yellow]")
        console.print("  issue <callsign> <tier> [scope] [duration_hours] [reason...]")
        console.print("    tier: basic, enhanced, full, oracle")
        console.print("    scope: general (default), project:<name>, investigation:<id>")
        console.print("    duration_hours: 0 = until revoked (default)")
        console.print("  revoke <grant_id>")
        console.print("  list [--all]   — Show active grants (--all includes revoked/expired)")
```

**`_grant_issue()` implementation:**
- Parse: `<callsign> <tier> [scope] [duration_hours] [reason...]`
- Resolve callsign to agent_id via `runtime.callsign_registry.resolve(callsign)`. If callsign not found, try `agent_type` directly. Show error if not found.
- Validate tier string against RecallTier values.
- Convert duration_hours to `expires_at` (0 or omitted = None = until revoked).
- Call `runtime.clearance_grant_store.issue_grant(...)`.
- Print confirmation with grant ID.

**`_grant_revoke()` implementation:**
- Parse: `<grant_id>` (accepts prefix match — first 8 chars of UUID)
- Call `runtime.clearance_grant_store.revoke_grant(grant_id)`.
- Print confirmation or "not found".

**Builder: for prefix matching, load all grants and find the one whose ID starts with the input prefix. This follows the pattern used in `/alert dismiss <pattern>` (lines 56-69 of commands_alert.py).**

**`_grant_list()` implementation:**
- `--all` flag shows revoked/expired too.
- Rich Table with columns: ID (first 8), Agent, Tier, Scope, Issued By, Issued, Expires, Status.
- Status: "Active", "Expired", "Revoked".

**Callsign resolution helper:** Use `runtime.callsign_registry` to resolve callsigns to agent IDs. Check the pattern at `ward_room_router.py:275-277` where `self._callsign_registry.resolve(callsign)` returns `{"agent_id": ...}`.

### 4. `src/probos/experience/shell.py` — Register `/grant` command

**Add import (after line 22, near `commands_alert`):**
```python
    commands_clearance,
```

**Add to COMMANDS help dict (after `/alert` line 94):**
```python
        "/grant":     "Manage clearance grants (issue/revoke/list)",
```

**Add to command dispatch dict (after `/alert` line 275):**
```python
            "/grant":      lambda: commands_clearance.cmd_grant(rt, con, arg),
```

**Add duplicate method stub (after the alert method stub, following the pattern):**
```python
    async def _cmd_grant(self, arg: str = "") -> None:
        from probos.experience.commands import commands_clearance
        await commands_clearance.cmd_grant(self.runtime, self.console, arg)
```

### 5. `src/probos/startup/results.py` — Add to CommunicationResult

**Add TYPE_CHECKING import (after line 51):**
```python
    from probos.clearance_grants import ClearanceGrantStore
```

**Add field to CommunicationResult (after `ontology` line 150):**
```python
    clearance_grant_store: "ClearanceGrantStore | None"
```

### 6. `src/probos/startup/communication.py` — Create ClearanceGrantStore

**Add after the BridgeAlertService creation block (after line 238), before Cognitive Journal:**

```python
    # --- Clearance Grant Store (AD-622) ---
    clearance_grant_store = None
    from probos.clearance_grants import ClearanceGrantStore

    clearance_grant_store = ClearanceGrantStore(
        db_path=str(data_dir / "clearance_grants.db"),
    )
    await clearance_grant_store.start()
    logger.info("clearance-grant-store started")
```

**Add to CommunicationResult return (after `ontology=ontology` line 342):**
```python
        clearance_grant_store=clearance_grant_store,
```

### 7. `src/probos/runtime.py` — Wire ClearanceGrantStore

**Add TYPE_CHECKING import (near line 120 where BridgeAlertService is imported):**
```python
    from probos.clearance_grants import ClearanceGrantStore
```

**Add type annotation (near line 198 where bridge_alerts is declared):**
```python
    clearance_grant_store: ClearanceGrantStore | None
```

**Add initialization (near line 385 where bridge_alerts is initialized):**
```python
        self.clearance_grant_store: ClearanceGrantStore | None = None
```

**Add wiring from CommunicationResult (after line 1374 where bridge_alerts is wired):**
```python
        self.clearance_grant_store = comm.clearance_grant_store
```

### 8. `src/probos/startup/shutdown.py` — Cleanup

**Add after the `bridge_alerts` section or near other store `.stop()` calls (e.g., after cognitive_journal at line 175):**

```python
    # AD-622: Clearance grant store
    if hasattr(runtime, 'clearance_grant_store') and runtime.clearance_grant_store:
        await runtime.clearance_grant_store.stop()
        logger.debug("clearance-grant-store stopped")
```

### 9. `src/probos/cognitive/cognitive_agent.py` — Wire grants into tier resolution

**At the existing tier resolution block (around line 2738-2747), add grant resolution:**

After `_billet_clearance = resolve_billet_clearance(...)` and before `_recall_tier = effective_recall_tier(...)`, add:

```python
from probos.earned_agency import resolve_active_grants
_active_grants = resolve_active_grants(
    getattr(self, 'sovereign_id', None) or self.id,
    getattr(self._runtime, 'clearance_grant_store', None),
)
_recall_tier = effective_recall_tier(_rank, _billet_clearance, _active_grants)
```

**Important:** Use `sovereign_id` (not slot ID) for grant lookup — grants target the persistent agent identity. The `sovereign_id` pattern is used throughout for episodic memory and identity-related lookups.

### 10. `src/probos/proactive.py` — Wire grants into tier resolution

**At the existing tier resolution block (around line 898-910), add the same pattern:**

After `_billet_clearance = resolve_billet_clearance(...)` and before `_recall_tier = effective_recall_tier(...)`, add:

```python
from probos.earned_agency import resolve_active_grants
_active_grants = resolve_active_grants(
    getattr(agent, 'sovereign_id', None) or agent.id,
    getattr(rt, 'clearance_grant_store', None),
)
_recall_tier = effective_recall_tier(_rank, _billet_clearance, _active_grants)
```

## Tests

### File: `tests/test_ad622_clearance_grants.py` (NEW)

**ClearanceGrant dataclass tests:**
1. **Grant creation with defaults** — ClearanceGrant with required fields only, verify defaults.
2. **Grant is frozen** — Attempting to modify a field raises FrozenInstanceError.

**effective_recall_tier with grants tests:**
3. **No grants = existing behavior** — Same as before when grants=().
4. **Grant elevates beyond rank** — Ensign (BASIC rank) + ORACLE grant → ORACLE.
5. **Grant elevates beyond billet** — Officer (ENHANCED billet) + FULL grant → FULL.
6. **Max of all three sources** — rank=BASIC, billet=ENHANCED, grant=FULL → FULL.
7. **Expired grant ignored** — Grant with `expires_at` in the past is filtered by `get_active_grants_sync()`, not passed to `effective_recall_tier()`.
8. **Revoked grant ignored** — Same for revoked grants.
9. **Multiple grants = highest wins** — Two grants (ENHANCED, FULL) → FULL used.

**ClearanceGrantStore tests:**
10. **issue_grant creates record** — Issue + list → grant present.
11. **revoke_grant soft-deletes** — Revoke → grant.revoked=True, still in list(active_only=False).
12. **get_active_grants_sync returns cached** — Issue → sync read returns grant.
13. **expired grants excluded from sync cache** — Issue with expires_at in past → not in sync results.
14. **revoke updates cache** — Revoke → sync read no longer returns grant.
15. **list_grants with --all** — Includes revoked and expired.
16. **start loads existing grants into cache** — Pre-populate DB, start() → cache populated.
17. **get_grant by ID** — Returns specific grant or None.

**resolve_active_grants tests:**
18. **None store → empty list** — Law of Demeter helper returns [] when store unavailable.
19. **Store with grants → returns list** — Helper returns active grants for agent.

**Shell command tests (optional, can be lighter):**
20. **cmd_grant issue parses correctly** — Valid args → grant created.
21. **cmd_grant revoke by prefix** — 8-char prefix matches grant ID.
22. **cmd_grant list renders table** — No crash, Rich table output.

## Verification

```bash
# AD-622 tests
uv run python -m pytest tests/test_ad622_clearance_grants.py -v

# Verify grant store created at startup
grep -n "clearance_grant_store" src/probos/startup/communication.py

# Verify shell command registration
grep -n "grant" src/probos/experience/shell.py

# Verify effective_recall_tier signature
grep -n "def effective_recall_tier" src/probos/earned_agency.py

# Verify wiring at both call sites
grep -n "resolve_active_grants" src/probos/cognitive/cognitive_agent.py src/probos/proactive.py

# Existing clearance tests still pass
uv run python -m pytest tests/test_ad620_clearance_model.py tests/test_ad621_channel_visibility.py tests/test_ad619_counselor_awareness.py -v

# Full suite
uv run python -m pytest tests/ -x -q
```

## Tracking Updates

- PROGRESS.md: AD-622 → IN PROGRESS
- DECISIONS.md: Add AD-622 entry after build
- roadmap.md: Update status
- GitHub Project: Issue #208 → In Progress
