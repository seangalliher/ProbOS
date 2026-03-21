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
            # Try prefix match (short ID)
            row = self._conn.execute(
                "SELECT data FROM directives WHERE id LIKE ?", (directive_id + "%",)
            ).fetchone()
        if not row:
            return False
        directive = RuntimeDirective.from_dict(json.loads(row[0]))
        directive.status = DirectiveStatus.REVOKED
        directive.revoked_by = revoked_by
        directive.revoked_at = time.time()
        self.add(directive)  # re-persist with updated status
        return True

    def amend(self, directive_id: str, new_content: str, amended_by: str) -> RuntimeDirective | None:
        """Amend (FRAGO) — replace the content of an existing directive in place.

        Returns the amended directive, or None if not found or not active.
        """
        row = self._conn.execute("SELECT data FROM directives WHERE id = ?", (directive_id,)).fetchone()
        if not row:
            # Try prefix match (short ID)
            row = self._conn.execute(
                "SELECT data FROM directives WHERE id LIKE ?", (directive_id + "%",)
            ).fetchone()
        if not row:
            return None
        directive = RuntimeDirective.from_dict(json.loads(row[0]))
        if directive.status not in (DirectiveStatus.ACTIVE, DirectiveStatus.PENDING_APPROVAL):
            return None
        directive.content = new_content
        self.add(directive)
        return directive

    def get(self, directive_id: str) -> RuntimeDirective | None:
        """Look up a directive by full or prefix ID."""
        row = self._conn.execute("SELECT data FROM directives WHERE id = ?", (directive_id,)).fetchone()
        if not row:
            row = self._conn.execute(
                "SELECT data FROM directives WHERE id LIKE ?", (directive_id + "%",)
            ).fetchone()
        if not row:
            return None
        return RuntimeDirective.from_dict(json.loads(row[0]))

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

        # Check for duplicate — same content, target, and type already active
        existing = self._conn.execute(
            "SELECT data FROM directives WHERE status IN ('active', 'pending_approval')"
        ).fetchall()
        for (data_json,) in existing:
            d = RuntimeDirective.from_dict(json.loads(data_json))
            if (d.content == content
                    and d.target_agent_type == target_agent_type
                    and d.directive_type == directive_type):
                return None, f"Duplicate — this order is already in effect (ID: {d.id[:8]})"

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
