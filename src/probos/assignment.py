"""AssignmentService — Dynamic assignment groups (AD-408).

Agents have a permanent department (pool group) and optional temporary
assignments (where they're working now). Three types: Bridge (session-scoped),
Away Team (mission-scoped, auto-dissolves), Working Group (open-ended).
All assignments auto-create a Ward Room channel for team communication.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from probos.events import EventType
from probos.protocols import ConnectionFactory, DatabaseConnection, EventEmitterMixin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Assignment:
    id: str
    name: str
    assignment_type: str          # "bridge" | "away_team" | "working_group"
    members: list[str]            # agent_ids
    created_by: str               # "captain" or agent_id
    created_at: float
    completed_at: float | None = None
    mission: str = ""             # Brief description of purpose
    ward_room_channel_id: str = ""  # Auto-created Ward Room channel
    status: str = "active"        # "active" | "completed" | "dissolved"


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

_VALID_TYPES = {"bridge", "away_team", "working_group"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assignments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    assignment_type TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    completed_at REAL,
    mission TEXT NOT NULL DEFAULT '',
    ward_room_channel_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS assignment_members (
    assignment_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    joined_at REAL NOT NULL,
    PRIMARY KEY (assignment_id, agent_id),
    FOREIGN KEY (assignment_id) REFERENCES assignments(id)
);

CREATE INDEX IF NOT EXISTS idx_assignments_status ON assignments(status);
"""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class AssignmentService(EventEmitterMixin):
    """Dynamic assignment groups — transient team overlays on the static department structure."""

    def __init__(
        self,
        db_path: str | None = None,
        emit_event: Any = None,
        ward_room: Any = None,
        connection_factory: ConnectionFactory | None = None,
    ):
        self.db_path = db_path
        self._db: DatabaseConnection | None = None
        self._emit_event = emit_event
        self._ward_room = ward_room  # WardRoomService reference for auto-channel creation
        self._snapshot_cache: list[dict[str, Any]] = []  # Sync cache for build_state_snapshot
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    async def start(self) -> None:
        if self.db_path:
            self._db = await self._connection_factory.connect(self.db_path)
            await self._db.execute("PRAGMA foreign_keys = ON")
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
        # Warm the snapshot cache
        await self._refresh_snapshot_cache()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Snapshot cache (sync access for build_state_snapshot)
    # ------------------------------------------------------------------

    async def _refresh_snapshot_cache(self) -> None:
        """Rebuild in-memory snapshot cache from DB."""
        assignments = await self.list_assignments(status="active")
        self._snapshot_cache = [
            {
                "id": a.id,
                "name": a.name,
                "assignment_type": a.assignment_type,
                "members": list(a.members),
                "created_by": a.created_by,
                "created_at": a.created_at,
                "mission": a.mission,
                "ward_room_channel_id": a.ward_room_channel_id,
                "status": a.status,
            }
            for a in assignments
        ]

    def get_assignment_snapshot(self) -> list[dict[str, Any]]:
        """Return cached active assignments as dicts (sync for state_snapshot)."""
        return list(self._snapshot_cache)

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    async def create_assignment(
        self,
        name: str,
        assignment_type: str,
        created_by: str,
        members: list[str],
        mission: str = "",
    ) -> Assignment:
        """Create a new assignment group."""
        if not self._db:
            raise ValueError("Assignment service not initialized")

        if assignment_type not in _VALID_TYPES:
            raise ValueError(
                f"Invalid assignment type '{assignment_type}'. "
                f"Must be one of: {', '.join(sorted(_VALID_TYPES))}"
            )

        if not members:
            raise ValueError("Members list cannot be empty")

        # Check no duplicate active name
        async with self._db.execute(
            "SELECT COUNT(*) FROM assignments WHERE name = ? AND status = 'active'",
            (name,),
        ) as cursor:
            row = await cursor.fetchone()
            if row and row[0] > 0:
                raise ValueError(f"Active assignment '{name}' already exists")

        now = time.time()
        assignment_id = str(uuid.uuid4())
        ward_room_channel_id = ""

        # Auto-create Ward Room channel if available
        if self._ward_room:
            try:
                ch = await self._ward_room.create_channel(
                    name=name, channel_type="custom",
                    created_by=created_by, description=f"Assignment: {mission or name}",
                )
                ward_room_channel_id = ch.id
                # Subscribe all members
                for agent_id in members:
                    await self._ward_room.subscribe(agent_id, ch.id)
            except Exception as e:
                logger.debug("Ward Room channel creation failed for assignment: %s", e)

        assignment = Assignment(
            id=assignment_id,
            name=name,
            assignment_type=assignment_type,
            members=list(members),
            created_by=created_by,
            created_at=now,
            mission=mission,
            ward_room_channel_id=ward_room_channel_id,
        )

        await self._db.execute(
            "INSERT INTO assignments (id, name, assignment_type, created_by, created_at, "
            "mission, ward_room_channel_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (assignment.id, assignment.name, assignment.assignment_type,
             assignment.created_by, assignment.created_at, assignment.mission,
             assignment.ward_room_channel_id, assignment.status),
        )

        for agent_id in members:
            await self._db.execute(
                "INSERT INTO assignment_members (assignment_id, agent_id, joined_at) "
                "VALUES (?, ?, ?)",
                (assignment.id, agent_id, now),
            )

        await self._db.commit()
        await self._refresh_snapshot_cache()

        self._emit(EventType.ASSIGNMENT_CREATED, {
            "id": assignment.id,
            "name": assignment.name,
            "assignment_type": assignment.assignment_type,
            "members": assignment.members,
            "mission": assignment.mission,
        })
        return assignment

    async def get_assignment(self, assignment_id: str) -> Assignment | None:
        """Load assignment + members from DB."""
        if not self._db:
            return None

        async with self._db.execute(
            "SELECT id, name, assignment_type, created_by, created_at, completed_at, "
            "mission, ward_room_channel_id, status FROM assignments WHERE id = ?",
            (assignment_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None

        members: list[str] = []
        async with self._db.execute(
            "SELECT agent_id FROM assignment_members WHERE assignment_id = ?",
            (assignment_id,),
        ) as cursor:
            async for mrow in cursor:
                members.append(mrow[0])

        return Assignment(
            id=row[0], name=row[1], assignment_type=row[2],
            members=members, created_by=row[3], created_at=row[4],
            completed_at=row[5], mission=row[6],
            ward_room_channel_id=row[7], status=row[8],
        )

    async def list_assignments(self, status: str = "active") -> list[Assignment]:
        """Return all assignments matching status filter, with member lists."""
        if not self._db:
            return []

        assignments: list[Assignment] = []
        async with self._db.execute(
            "SELECT id, name, assignment_type, created_by, created_at, completed_at, "
            "mission, ward_room_channel_id, status "
            "FROM assignments WHERE status = ? ORDER BY created_at DESC",
            (status,),
        ) as cursor:
            async for row in cursor:
                assignments.append(Assignment(
                    id=row[0], name=row[1], assignment_type=row[2],
                    members=[], created_by=row[3], created_at=row[4],
                    completed_at=row[5], mission=row[6],
                    ward_room_channel_id=row[7], status=row[8],
                ))

        # Load members for each assignment
        for assignment in assignments:
            async with self._db.execute(
                "SELECT agent_id FROM assignment_members WHERE assignment_id = ?",
                (assignment.id,),
            ) as cursor:
                async for mrow in cursor:
                    assignment.members.append(mrow[0])

        return assignments

    async def add_member(self, assignment_id: str, agent_id: str) -> Assignment:
        """Add member to existing assignment."""
        if not self._db:
            raise ValueError("Assignment service not initialized")

        assignment = await self.get_assignment(assignment_id)
        if not assignment:
            raise ValueError(f"Assignment {assignment_id} not found")
        if assignment.status != "active":
            raise ValueError("Cannot modify inactive assignment")
        if agent_id in assignment.members:
            raise ValueError(f"Agent {agent_id} is already a member")

        now = time.time()
        await self._db.execute(
            "INSERT INTO assignment_members (assignment_id, agent_id, joined_at) "
            "VALUES (?, ?, ?)",
            (assignment_id, agent_id, now),
        )
        await self._db.commit()

        # Subscribe to Ward Room channel if available
        if self._ward_room and assignment.ward_room_channel_id:
            try:
                await self._ward_room.subscribe(agent_id, assignment.ward_room_channel_id)
            except Exception as e:
                logger.debug("Ward Room subscribe failed: %s", e)

        assignment.members.append(agent_id)
        await self._refresh_snapshot_cache()

        self._emit(EventType.ASSIGNMENT_UPDATED, {
            "id": assignment_id,
            "action": "add_member",
            "agent_id": agent_id,
            "members": assignment.members,
        })
        return assignment

    async def remove_member(self, assignment_id: str, agent_id: str) -> Assignment:
        """Remove member from assignment. Auto-dissolves if no members remain."""
        if not self._db:
            raise ValueError("Assignment service not initialized")

        assignment = await self.get_assignment(assignment_id)
        if not assignment:
            raise ValueError(f"Assignment {assignment_id} not found")
        if assignment.status != "active":
            raise ValueError("Cannot modify inactive assignment")

        await self._db.execute(
            "DELETE FROM assignment_members WHERE assignment_id = ? AND agent_id = ?",
            (assignment_id, agent_id),
        )
        await self._db.commit()

        assignment.members = [m for m in assignment.members if m != agent_id]

        # Auto-dissolve if no members remain
        if not assignment.members:
            return await self.dissolve_assignment(assignment_id)

        await self._refresh_snapshot_cache()

        self._emit(EventType.ASSIGNMENT_UPDATED, {
            "id": assignment_id,
            "action": "remove_member",
            "agent_id": agent_id,
            "members": assignment.members,
        })
        return assignment

    async def complete_assignment(self, assignment_id: str) -> Assignment:
        """Complete an assignment."""
        if not self._db:
            raise ValueError("Assignment service not initialized")

        assignment = await self.get_assignment(assignment_id)
        if not assignment:
            raise ValueError(f"Assignment {assignment_id} not found")
        if assignment.status != "active":
            raise ValueError("Assignment is not active")

        now = time.time()
        await self._db.execute(
            "UPDATE assignments SET status = 'completed', completed_at = ? WHERE id = ?",
            (now, assignment_id),
        )
        await self._db.commit()

        # Archive Ward Room channel
        if self._ward_room and assignment.ward_room_channel_id:
            try:
                await self._ward_room._db.execute(
                    "UPDATE channels SET archived = 1 WHERE id = ?",
                    (assignment.ward_room_channel_id,),
                )
                await self._ward_room._db.commit()
            except Exception as e:
                logger.debug("Ward Room channel archive failed: %s", e)

        assignment.status = "completed"
        assignment.completed_at = now
        await self._refresh_snapshot_cache()

        self._emit(EventType.ASSIGNMENT_COMPLETED, {
            "id": assignment_id,
            "status": "completed",
            "name": assignment.name,
        })
        return assignment

    async def dissolve_assignment(self, assignment_id: str) -> Assignment:
        """Dissolve an assignment."""
        if not self._db:
            raise ValueError("Assignment service not initialized")

        assignment = await self.get_assignment(assignment_id)
        if not assignment:
            raise ValueError(f"Assignment {assignment_id} not found")

        now = time.time()
        await self._db.execute(
            "UPDATE assignments SET status = 'dissolved', completed_at = ? WHERE id = ?",
            (now, assignment_id),
        )
        await self._db.commit()

        # Archive Ward Room channel
        if self._ward_room and assignment.ward_room_channel_id:
            try:
                await self._ward_room._db.execute(
                    "UPDATE channels SET archived = 1 WHERE id = ?",
                    (assignment.ward_room_channel_id,),
                )
                await self._ward_room._db.commit()
            except Exception as e:
                logger.debug("Ward Room channel archive failed: %s", e)

        assignment.status = "dissolved"
        assignment.completed_at = now
        await self._refresh_snapshot_cache()

        self._emit(EventType.ASSIGNMENT_COMPLETED, {
            "id": assignment_id,
            "status": "dissolved",
            "name": assignment.name,
        })
        return assignment

    async def get_agent_assignments(self, agent_id: str) -> list[Assignment]:
        """Return all active assignments where agent is a member."""
        if not self._db:
            return []

        assignment_ids: list[str] = []
        async with self._db.execute(
            "SELECT am.assignment_id FROM assignment_members am "
            "JOIN assignments a ON a.id = am.assignment_id "
            "WHERE am.agent_id = ? AND a.status = 'active'",
            (agent_id,),
        ) as cursor:
            async for row in cursor:
                assignment_ids.append(row[0])

        assignments: list[Assignment] = []
        for aid in assignment_ids:
            a = await self.get_assignment(aid)
            if a:
                assignments.append(a)
        return assignments
