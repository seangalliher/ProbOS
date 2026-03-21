# AD-386: Runtime Directive Overlays — Evolvable Chain-of-Command Instructions

## Goal

Agent instructions today are static files on disk (`config/standing_orders/*.md`), loaded once and cached. No agent — not even the Captain — can issue a new directive at runtime. Department chiefs can't instruct subordinates. Lessons learned during operation vanish unless someone manually edits a file.

This AD adds a **tier 6 instruction layer**: persistent runtime directives that can be issued, revoked, and queried through the chain of command. Instructions evolve as agents learn and collaborate.

## Architecture

**Pattern:** New Ship's Computer service (`DirectiveStore`), same lifecycle as `ServiceProfileStore` (AD-382) and `ProfileStore` (crew_profile.py). SQLite-backed, wired into `compose_instructions()` as an additional layer after personal standing orders.

## Reference Files (read these first)

- `src/probos/cognitive/standing_orders.py` — `compose_instructions()`, `_AGENT_DEPARTMENTS`, `clear_cache()`
- `src/probos/cognitive/cognitive_agent.py` — `decide()` calls `compose_instructions()` at line ~106
- `src/probos/crew_profile.py` — `Rank` enum with trust thresholds, `ProfileStore`
- `src/probos/runtime.py` — service wiring pattern in `start()`/`stop()`
- `src/probos/experience/shell.py` — `COMMANDS` dict + `_dispatch_slash()` handler dict

## Files to Create

### `src/probos/directive_store.py` (~200 lines)

```python
"""AD-386: Runtime Directive Overlays — evolvable chain-of-command instructions."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from probos.crew_profile import Rank


class DirectiveType(str, Enum):
    CAPTAIN_ORDER = "captain_order"          # Human Captain → any agent
    CHIEF_DIRECTIVE = "chief_directive"      # Department chief → subordinates
    COUNSELOR_GUIDANCE = "counselor_guidance" # Bridge officer → any agent (advisory)
    LEARNED_LESSON = "learned_lesson"        # Self → self (via dream/self-mod)
    PEER_SUGGESTION = "peer_suggestion"      # Peer → peer (must be accepted)


class DirectiveStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    SUPERSEDED = "superseded"
    PENDING_APPROVAL = "pending_approval"   # For learned_lesson from low-trust agents


@dataclass
class RuntimeDirective:
    """A runtime instruction overlay issued through the chain of command."""
    id: str                              # uuid
    target_agent_type: str               # e.g., "builder", "diagnostician", "*" for broadcast
    target_department: str | None        # scope limiter — "engineering", "medical", None=any
    directive_type: DirectiveType
    content: str                         # the actual instruction text (natural language)
    issued_by: str                       # agent_type or "captain" (human)
    issued_by_department: str | None
    authority: float                     # trust score of issuer at time of issuance
    priority: int = 3                    # 1-5, higher priority applied later (overrides)
    status: DirectiveStatus = DirectiveStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None      # None = permanent until revoked
    revoked_by: str | None = None
    revoked_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target_agent_type": self.target_agent_type,
            "target_department": self.target_department,
            "directive_type": self.directive_type.value,
            "content": self.content,
            "issued_by": self.issued_by,
            "issued_by_department": self.issued_by_department,
            "authority": self.authority,
            "priority": self.priority,
            "status": self.status.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "revoked_by": self.revoked_by,
            "revoked_at": self.revoked_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RuntimeDirective:
        return cls(
            id=d["id"],
            target_agent_type=d["target_agent_type"],
            target_department=d.get("target_department"),
            directive_type=DirectiveType(d["directive_type"]),
            content=d["content"],
            issued_by=d["issued_by"],
            issued_by_department=d.get("issued_by_department"),
            authority=d.get("authority", 1.0),
            priority=d.get("priority", 3),
            status=DirectiveStatus(d.get("status", "active")),
            created_at=d.get("created_at", 0.0),
            expires_at=d.get("expires_at"),
            revoked_by=d.get("revoked_by"),
            revoked_at=d.get("revoked_at"),
        )


def authorize_directive(
    issuer_type: str,
    issuer_department: str | None,
    issuer_rank: Rank,
    target_agent_type: str,
    target_department: str | None,
    directive_type: DirectiveType,
) -> tuple[bool, str]:
    """Check if the issuer is authorized to create this directive.

    Returns (authorized: bool, reason: str).

    Authorization rules:
    - captain_order: issuer_type must be "captain" (human). Always authorized.
    - counselor_guidance: issuer_type must be "counselor" or "architect" (bridge officers). Any target.
    - chief_directive: issuer must be COMMANDER+ rank AND same department as target. Cannot target "*".
    - learned_lesson: issuer_type must equal target_agent_type (self only).
      Rank >= LIEUTENANT: auto-approved (status=ACTIVE).
      Rank < LIEUTENANT (ENSIGN): created with status=PENDING_APPROVAL.
    - peer_suggestion: issuer_rank must be >= LIEUTENANT. Any target.
      Created with status=PENDING_APPROVAL (target must accept).
    """
    if directive_type == DirectiveType.CAPTAIN_ORDER:
        if issuer_type != "captain":
            return False, "Only the Captain can issue captain_order directives"
        return True, "Captain authority"

    if directive_type == DirectiveType.COUNSELOR_GUIDANCE:
        if issuer_type not in ("counselor", "architect"):
            return False, "Only bridge officers (counselor, architect) can issue counselor_guidance"
        return True, "Bridge officer authority"

    if directive_type == DirectiveType.CHIEF_DIRECTIVE:
        if issuer_rank.value not in (Rank.COMMANDER.value, Rank.SENIOR.value):
            return False, f"Chief directives require COMMANDER+ rank, issuer is {issuer_rank.value}"
        if target_agent_type == "*":
            return False, "Chief directives cannot target all agents (*)"
        if issuer_department != target_department and target_department is not None:
            return False, f"Chief can only direct subordinates in own department ({issuer_department}), not {target_department}"
        return True, f"Chief authority in {issuer_department}"

    if directive_type == DirectiveType.LEARNED_LESSON:
        if issuer_type != target_agent_type:
            return False, "Learned lessons can only target self"
        return True, "Self-directed learning"

    if directive_type == DirectiveType.PEER_SUGGESTION:
        if issuer_rank.value not in (Rank.LIEUTENANT.value, Rank.COMMANDER.value, Rank.SENIOR.value):
            return False, f"Peer suggestions require LIEUTENANT+ rank, issuer is {issuer_rank.value}"
        return True, "Peer collaboration"

    return False, f"Unknown directive type: {directive_type}"


class DirectiveStore:
    """SQLite-backed persistent store for runtime directives."""

    def __init__(self, db_path: str = "data/directives.db") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS directives ("
            "  id TEXT PRIMARY KEY,"
            "  data TEXT NOT NULL,"
            "  target_agent_type TEXT,"
            "  target_department TEXT,"
            "  status TEXT,"
            "  created_at REAL"
            ")"
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the SQLite connection."""
        self._conn.close()

    def add(self, directive: RuntimeDirective) -> None:
        """Persist a new directive."""
        self._conn.execute(
            "INSERT OR REPLACE INTO directives (id, data, target_agent_type, target_department, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (directive.id, json.dumps(directive.to_dict()), directive.target_agent_type,
             directive.target_department, directive.status.value, directive.created_at),
        )
        self._conn.commit()

    def revoke(self, directive_id: str, revoked_by: str) -> bool:
        """Revoke a directive. Returns True if found and revoked."""
        row = self._conn.execute("SELECT data FROM directives WHERE id = ?", (directive_id,)).fetchone()
        if not row:
            return False
        directive = RuntimeDirective.from_dict(json.loads(row[0]))
        directive.status = DirectiveStatus.REVOKED
        directive.revoked_by = revoked_by
        directive.revoked_at = time.time()
        self.add(directive)  # re-persist with updated status
        return True

    def approve(self, directive_id: str) -> bool:
        """Approve a pending directive. Returns True if found and approved."""
        row = self._conn.execute("SELECT data FROM directives WHERE id = ?", (directive_id,)).fetchone()
        if not row:
            return False
        directive = RuntimeDirective.from_dict(json.loads(row[0]))
        if directive.status != DirectiveStatus.PENDING_APPROVAL:
            return False
        directive.status = DirectiveStatus.ACTIVE
        self.add(directive)
        return True

    def get_active_for_agent(self, agent_type: str, department: str | None = None) -> list[RuntimeDirective]:
        """Get all active directives applicable to an agent.

        Matches directives where:
        - status = "active"
        - not expired (expires_at is None or > now)
        - target_agent_type matches agent_type OR is "*"
        - target_department matches department OR is None

        Returns sorted by priority (ascending, so highest priority is last/overrides).
        """
        now = time.time()
        rows = self._conn.execute(
            "SELECT data FROM directives WHERE status = 'active'"
        ).fetchall()
        results: list[RuntimeDirective] = []
        for (data_json,) in rows:
            d = RuntimeDirective.from_dict(json.loads(data_json))
            # Check expiry
            if d.expires_at is not None and d.expires_at <= now:
                # Auto-expire
                d.status = DirectiveStatus.EXPIRED
                self.add(d)
                continue
            # Check target match
            if d.target_agent_type != "*" and d.target_agent_type != agent_type:
                continue
            if d.target_department is not None and d.target_department != department:
                continue
            results.append(d)
        results.sort(key=lambda x: x.priority)
        return results

    def all_directives(self, include_inactive: bool = False) -> list[RuntimeDirective]:
        """Return all directives, optionally including inactive ones."""
        if include_inactive:
            rows = self._conn.execute("SELECT data FROM directives ORDER BY created_at DESC").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT data FROM directives WHERE status IN ('active', 'pending_approval') ORDER BY created_at DESC"
            ).fetchall()
        return [RuntimeDirective.from_dict(json.loads(row[0])) for row in rows]

    def create_directive(
        self,
        *,
        issuer_type: str,
        issuer_department: str | None,
        issuer_rank: Rank,
        target_agent_type: str,
        target_department: str | None,
        directive_type: DirectiveType,
        content: str,
        authority: float = 1.0,
        priority: int = 3,
        expires_at: float | None = None,
    ) -> tuple[RuntimeDirective | None, str]:
        """Authorize and create a directive in one step.

        Returns (directive, reason). directive is None if authorization failed.
        For learned_lesson from ENSIGN rank: creates with PENDING_APPROVAL status.
        For peer_suggestion: creates with PENDING_APPROVAL status.
        """
        authorized, reason = authorize_directive(
            issuer_type, issuer_department, issuer_rank,
            target_agent_type, target_department, directive_type,
        )
        if not authorized:
            return None, reason

        # Determine initial status
        status = DirectiveStatus.ACTIVE
        if directive_type == DirectiveType.PEER_SUGGESTION:
            status = DirectiveStatus.PENDING_APPROVAL
        elif directive_type == DirectiveType.LEARNED_LESSON:
            if issuer_rank == Rank.ENSIGN:
                status = DirectiveStatus.PENDING_APPROVAL

        directive = RuntimeDirective(
            id=str(uuid.uuid4()),
            target_agent_type=target_agent_type,
            target_department=target_department,
            directive_type=directive_type,
            content=content,
            issued_by=issuer_type,
            issued_by_department=issuer_department,
            authority=authority,
            priority=priority,
            status=status,
            expires_at=expires_at,
        )
        self.add(directive)
        return directive, reason
```

## Files to Modify

### `src/probos/cognitive/standing_orders.py`

1. Add module-level variable to hold directive store reference:
```python
_directive_store: Any = None  # Set by runtime at startup

def set_directive_store(store: Any) -> None:
    """Wire the DirectiveStore for tier 6 composition."""
    global _directive_store
    _directive_store = store
```

2. Modify `compose_instructions()` to add tier 6 after personal standing orders. After the existing 5 tiers are assembled into `sections`, add:

```python
# Tier 6: Active runtime directives (AD-386)
if _directive_store is not None:
    dept = department or _AGENT_DEPARTMENTS.get(agent_type)
    directives = _directive_store.get_active_for_agent(agent_type, dept)
    if directives:
        directive_lines = []
        for d in directives:
            prefix = d.directive_type.value.replace("_", " ").title()
            directive_lines.append(f"- [{prefix}] {d.content}")
        sections.append("## Active Directives\n\n" + "\n".join(directive_lines))
```

3. In `clear_cache()`: no changes needed — the directive store is queried live (not cached). The `_load_file` cache only affects file-based tiers 1-5.

**Important:** Import `DirectiveType` only inside the conditional block to avoid circular imports:
```python
if _directive_store is not None:
    # directives are already RuntimeDirective objects, no import needed
```

### `src/probos/runtime.py`

1. Add import: `from probos.directive_store import DirectiveStore`
2. Add import: `from probos.cognitive.standing_orders import set_directive_store`
3. In `__init__()`: `self.directive_store: DirectiveStore | None = None`
4. In `start()`, after ServiceProfileStore initialization:
```python
# Directive store (AD-386)
try:
    self.directive_store = DirectiveStore(
        db_path=str(Path(self._data_dir) / "directives.db")
    )
    set_directive_store(self.directive_store)
    logger.info("DirectiveStore initialized")
except Exception:
    logger.exception("DirectiveStore init failed (non-fatal)")
```
5. In `stop()`:
```python
if self.directive_store:
    set_directive_store(None)
    self.directive_store.close()
    self.directive_store = None
```
6. In `build_state_snapshot()`, add directive summary:
```python
if self.directive_store:
    active = self.directive_store.all_directives(include_inactive=False)
    state["directives"] = {
        "active": len([d for d in active if d.status.value == "active"]),
        "pending": len([d for d in active if d.status.value == "pending_approval"]),
    }
```

### `src/probos/experience/shell.py`

Add two new commands: `/order` and `/directives`.

1. Add to `COMMANDS` dict:
```python
"/order":      "Issue a directive (/order <agent_type> <text>)",
"/directives": "Show active directives (/directives [agent_type])",
```

2. Add to `handlers` dict inside `_dispatch_slash()`:
```python
"/order":      self._cmd_order,
"/directives": self._cmd_directives,
```

3. Implement `_cmd_order`:
```python
async def _cmd_order(self, arg: str) -> None:
    """Issue a Captain's order to an agent type."""
    if not arg:
        self.console.print("[yellow]Usage: /order <agent_type> <instruction text>[/yellow]")
        return
    parts = arg.split(maxsplit=1)
    if len(parts) < 2:
        self.console.print("[yellow]Usage: /order <agent_type> <instruction text>[/yellow]")
        return
    target = parts[0]
    content = parts[1]
    store = self.runtime.directive_store
    if not store:
        self.console.print("[red]DirectiveStore not available[/red]")
        return
    from probos.directive_store import DirectiveType
    from probos.crew_profile import Rank
    from probos.cognitive.standing_orders import get_department, clear_cache
    directive, reason = store.create_directive(
        issuer_type="captain",
        issuer_department=None,
        issuer_rank=Rank.SENIOR,  # Captain has highest authority
        target_agent_type=target,
        target_department=get_department(target),
        directive_type=DirectiveType.CAPTAIN_ORDER,
        content=content,
        authority=1.0,
        priority=5,  # Captain orders are highest priority
    )
    if directive:
        clear_cache()  # Invalidate composed instructions
        self.console.print(f"[green]Order issued to {target}:[/green] {content}")
        self.console.print(f"[dim]ID: {directive.id}[/dim]")
    else:
        self.console.print(f"[red]Authorization failed: {reason}[/red]")
```

4. Implement `_cmd_directives`:
```python
async def _cmd_directives(self, arg: str) -> None:
    """Show active directives, optionally filtered by agent type."""
    store = self.runtime.directive_store
    if not store:
        self.console.print("[red]DirectiveStore not available[/red]")
        return
    directives = store.all_directives(include_inactive=False)
    if arg:
        from probos.cognitive.standing_orders import get_department
        dept = get_department(arg)
        directives = [
            d for d in directives
            if d.target_agent_type in (arg, "*") and
               (d.target_department is None or d.target_department == dept)
        ]
    if not directives:
        self.console.print("[dim]No active directives[/dim]")
        return
    for d in directives:
        status_color = "green" if d.status.value == "active" else "yellow"
        dtype = d.directive_type.value.replace("_", " ").title()
        target = d.target_agent_type
        if d.target_department:
            target += f" ({d.target_department})"
        self.console.print(
            f"[{status_color}][{dtype}][/{status_color}] → {target}: {d.content}"
        )
        self.console.print(f"  [dim]by {d.issued_by} | priority {d.priority} | {d.id[:8]}[/dim]")
```

## Tests

### Create `tests/test_directive_store.py` (~200 lines)

1. **`test_directive_to_dict_roundtrip`** — Create `RuntimeDirective`, verify `to_dict()` then `from_dict()` roundtrip preserves all fields
2. **`test_directive_type_enum`** — All 5 types serializable as string values
3. **`test_directive_status_enum`** — All 5 statuses serializable
4. **`test_authorize_captain_order`** — `issuer_type="captain"` → authorized for any target
5. **`test_authorize_captain_order_non_captain`** — `issuer_type="builder"` with `captain_order` → rejected
6. **`test_authorize_counselor_guidance`** — `issuer_type="counselor"` → authorized
7. **`test_authorize_counselor_guidance_non_bridge`** — `issuer_type="builder"` → rejected
8. **`test_authorize_chief_directive_commander`** — COMMANDER rank, same department → authorized
9. **`test_authorize_chief_directive_lt_rank`** — LIEUTENANT rank → rejected (need COMMANDER+)
10. **`test_authorize_chief_directive_cross_dept`** — COMMANDER but different department → rejected
11. **`test_authorize_chief_directive_broadcast`** — target `"*"` → rejected (chiefs can't broadcast)
12. **`test_authorize_learned_lesson_self`** — `issuer_type == target_agent_type` → authorized
13. **`test_authorize_learned_lesson_other`** — `issuer_type != target_agent_type` → rejected
14. **`test_authorize_peer_suggestion_lt`** — LIEUTENANT rank → authorized
15. **`test_authorize_peer_suggestion_ensign`** — ENSIGN rank → rejected
16. **`test_store_add_and_retrieve`** — Add directive, `get_active_for_agent()` returns it
17. **`test_store_target_filtering`** — Directive for `"builder"` not returned for `"diagnostician"`
18. **`test_store_broadcast_directive`** — `target_agent_type="*"` returned for any agent
19. **`test_store_department_filtering`** — Directive for `"engineering"` not returned for `"medical"` agents
20. **`test_store_revoke`** — `revoke()` sets status to REVOKED, no longer returned by `get_active_for_agent()`
21. **`test_store_approve_pending`** — `approve()` changes PENDING_APPROVAL to ACTIVE
22. **`test_store_approve_non_pending`** — `approve()` on ACTIVE directive returns False
23. **`test_store_expiry`** — Directive with `expires_at` in the past → auto-expired on query
24. **`test_store_priority_ordering`** — Multiple directives returned sorted by priority (ascending)
25. **`test_create_directive_captain`** — `create_directive()` with captain → ACTIVE status
26. **`test_create_directive_learned_lesson_ensign`** — `create_directive()` with ENSIGN self-update → PENDING_APPROVAL
27. **`test_create_directive_learned_lesson_lt`** — `create_directive()` with LIEUTENANT self-update → ACTIVE
28. **`test_create_directive_peer_suggestion`** — `create_directive()` with peer → PENDING_APPROVAL
29. **`test_all_directives_active_only`** — `all_directives(include_inactive=False)` excludes revoked/expired
30. **`test_all_directives_include_inactive`** — `all_directives(include_inactive=True)` includes everything

Use `tmp_path` fixture for SQLite database path. No mocking of SQLite needed — use real in-memory or temp file databases.

## Constraints

- No LLM calls — purely programmatic authorization and storage
- Backward compatible: if no `DirectiveStore` is wired, `compose_instructions()` behaves exactly as before
- The module-level `_directive_store` variable in `standing_orders.py` is set/unset by runtime at startup/shutdown
- Do not modify `cognitive_agent.py` — the `decide()` method already calls `compose_instructions()` which will pick up directives automatically
- `clear_cache()` should be called after creating/revoking directives to invalidate composed instructions
- Import `DirectiveStore` types only where needed to avoid circular imports
- Rank comparison uses `.value` string comparison — the `authorize_directive()` function receives a `Rank` enum value, not a trust float
