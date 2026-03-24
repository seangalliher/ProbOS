"""Tests for AssignmentService (AD-408a)."""

import pytest
import pytest_asyncio

from probos.assignment import AssignmentService, Assignment


@pytest_asyncio.fixture
async def assignment_service(tmp_path):
    events = []
    def capture_event(event_type, data):
        events.append({"type": event_type, "data": data})

    svc = AssignmentService(
        db_path=str(tmp_path / "assignments.db"),
        emit_event=capture_event,
    )
    await svc.start()
    svc._captured_events = events
    yield svc
    await svc.stop()


@pytest_asyncio.fixture
async def assignment_with_wardroom(tmp_path):
    """Assignment service with a real WardRoomService for integration tests."""
    from probos.ward_room import WardRoomService

    events = []
    def capture_event(event_type, data):
        events.append({"type": event_type, "data": data})

    wr = WardRoomService(
        db_path=str(tmp_path / "ward_room.db"),
        emit_event=capture_event,
    )
    await wr.start()

    svc = AssignmentService(
        db_path=str(tmp_path / "assignments.db"),
        emit_event=capture_event,
        ward_room=wr,
    )
    await svc.start()
    svc._captured_events = events
    yield svc
    await svc.stop()
    await wr.stop()


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------

class TestCRUD:
    async def test_create_away_team(self, assignment_service):
        a = await assignment_service.create_assignment(
            name="Alpha Team", assignment_type="away_team",
            created_by="captain", members=["a1", "a2"],
            mission="Investigate anomaly",
        )
        assert a.name == "Alpha Team"
        assert a.assignment_type == "away_team"
        assert a.status == "active"
        assert a.members == ["a1", "a2"]
        assert a.mission == "Investigate anomaly"
        assert a.id

    async def test_create_bridge_assignment(self, assignment_service):
        a = await assignment_service.create_assignment(
            name="Bridge Watch", assignment_type="bridge",
            created_by="captain", members=["a1"],
        )
        assert a.assignment_type == "bridge"

    async def test_create_working_group(self, assignment_service):
        a = await assignment_service.create_assignment(
            name="Code Review", assignment_type="working_group",
            created_by="a1", members=["a1", "a2", "a3"],
        )
        assert a.assignment_type == "working_group"
        assert len(a.members) == 3

    async def test_invalid_assignment_type_rejected(self, assignment_service):
        with pytest.raises(ValueError, match="Invalid assignment type"):
            await assignment_service.create_assignment(
                name="Bad", assignment_type="invalid",
                created_by="captain", members=["a1"],
            )

    async def test_empty_members_rejected(self, assignment_service):
        with pytest.raises(ValueError, match="Members list cannot be empty"):
            await assignment_service.create_assignment(
                name="Empty", assignment_type="away_team",
                created_by="captain", members=[],
            )

    async def test_duplicate_name_rejected(self, assignment_service):
        await assignment_service.create_assignment(
            name="Alpha", assignment_type="away_team",
            created_by="captain", members=["a1"],
        )
        with pytest.raises(ValueError, match="already exists"):
            await assignment_service.create_assignment(
                name="Alpha", assignment_type="bridge",
                created_by="captain", members=["a2"],
            )

    async def test_get_assignment(self, assignment_service):
        a = await assignment_service.create_assignment(
            name="Team", assignment_type="away_team",
            created_by="captain", members=["a1"],
        )
        loaded = await assignment_service.get_assignment(a.id)
        assert loaded is not None
        assert loaded.name == "Team"
        assert loaded.members == ["a1"]

    async def test_get_nonexistent_returns_none(self, assignment_service):
        result = await assignment_service.get_assignment("nonexistent-id")
        assert result is None

    async def test_list_active_assignments(self, assignment_service):
        await assignment_service.create_assignment(
            name="A", assignment_type="away_team",
            created_by="captain", members=["a1"],
        )
        a2 = await assignment_service.create_assignment(
            name="B", assignment_type="bridge",
            created_by="captain", members=["a2"],
        )
        await assignment_service.complete_assignment(a2.id)

        active = await assignment_service.list_assignments(status="active")
        assert len(active) == 1
        assert active[0].name == "A"

    async def test_list_completed_assignments(self, assignment_service):
        a = await assignment_service.create_assignment(
            name="Done", assignment_type="away_team",
            created_by="captain", members=["a1"],
        )
        await assignment_service.complete_assignment(a.id)

        completed = await assignment_service.list_assignments(status="completed")
        assert len(completed) == 1
        assert completed[0].name == "Done"


# ---------------------------------------------------------------------------
# Member management
# ---------------------------------------------------------------------------

class TestMembers:
    async def test_add_member(self, assignment_service):
        a = await assignment_service.create_assignment(
            name="Team", assignment_type="away_team",
            created_by="captain", members=["a1"],
        )
        updated = await assignment_service.add_member(a.id, "a2")
        assert "a2" in updated.members
        assert len(updated.members) == 2

    async def test_add_duplicate_member_rejected(self, assignment_service):
        a = await assignment_service.create_assignment(
            name="Team", assignment_type="away_team",
            created_by="captain", members=["a1"],
        )
        with pytest.raises(ValueError, match="already a member"):
            await assignment_service.add_member(a.id, "a1")

    async def test_remove_member(self, assignment_service):
        a = await assignment_service.create_assignment(
            name="Team", assignment_type="away_team",
            created_by="captain", members=["a1", "a2"],
        )
        updated = await assignment_service.remove_member(a.id, "a1")
        assert "a1" not in updated.members
        assert len(updated.members) == 1

    async def test_remove_last_member_auto_dissolves(self, assignment_service):
        a = await assignment_service.create_assignment(
            name="Team", assignment_type="away_team",
            created_by="captain", members=["a1"],
        )
        result = await assignment_service.remove_member(a.id, "a1")
        assert result.status == "dissolved"

    async def test_get_agent_assignments(self, assignment_service):
        await assignment_service.create_assignment(
            name="Team1", assignment_type="away_team",
            created_by="captain", members=["a1", "a2"],
        )
        await assignment_service.create_assignment(
            name="Team2", assignment_type="bridge",
            created_by="captain", members=["a1"],
        )
        await assignment_service.create_assignment(
            name="Team3", assignment_type="working_group",
            created_by="captain", members=["a3"],
        )

        a1_assignments = await assignment_service.get_agent_assignments("a1")
        assert len(a1_assignments) == 2
        names = {a.name for a in a1_assignments}
        assert "Team1" in names
        assert "Team2" in names


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    async def test_complete_assignment(self, assignment_service):
        a = await assignment_service.create_assignment(
            name="Mission", assignment_type="away_team",
            created_by="captain", members=["a1"],
        )
        completed = await assignment_service.complete_assignment(a.id)
        assert completed.status == "completed"
        assert completed.completed_at is not None

    async def test_dissolve_assignment(self, assignment_service):
        a = await assignment_service.create_assignment(
            name="Temp", assignment_type="working_group",
            created_by="captain", members=["a1"],
        )
        dissolved = await assignment_service.dissolve_assignment(a.id)
        assert dissolved.status == "dissolved"
        assert dissolved.completed_at is not None

    async def test_complete_already_completed_rejected(self, assignment_service):
        a = await assignment_service.create_assignment(
            name="Done", assignment_type="away_team",
            created_by="captain", members=["a1"],
        )
        await assignment_service.complete_assignment(a.id)
        with pytest.raises(ValueError, match="not active"):
            await assignment_service.complete_assignment(a.id)


# ---------------------------------------------------------------------------
# Ward Room integration
# ---------------------------------------------------------------------------

class TestWardRoomIntegration:
    async def test_create_with_wardroom_creates_channel(self, assignment_with_wardroom):
        svc = assignment_with_wardroom
        a = await svc.create_assignment(
            name="Recon Team", assignment_type="away_team",
            created_by="captain", members=["a1", "a2"],
            mission="Recon mission",
        )
        assert a.ward_room_channel_id != ""

        # Verify channel exists
        channels = await svc._ward_room.list_channels()
        channel_ids = {c.id for c in channels}
        assert a.ward_room_channel_id in channel_ids

    async def test_create_with_wardroom_subscribes_members(self, assignment_with_wardroom):
        svc = assignment_with_wardroom
        a = await svc.create_assignment(
            name="Recon Team", assignment_type="away_team",
            created_by="captain", members=["a1", "a2"],
        )
        # Check members are subscribed via direct DB query
        async with svc._ward_room._db.execute(
            "SELECT agent_id FROM memberships WHERE channel_id = ?",
            (a.ward_room_channel_id,),
        ) as cursor:
            subs = {row[0] async for row in cursor}
        assert "a1" in subs
        assert "a2" in subs

    async def test_add_member_with_wardroom_subscribes(self, assignment_with_wardroom):
        svc = assignment_with_wardroom
        a = await svc.create_assignment(
            name="Team", assignment_type="away_team",
            created_by="captain", members=["a1"],
        )
        await svc.add_member(a.id, "a2")

        # Check a2 is subscribed via direct DB query
        async with svc._ward_room._db.execute(
            "SELECT agent_id FROM memberships WHERE channel_id = ? AND agent_id = ?",
            (a.ward_room_channel_id, "a2"),
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None

    async def test_complete_archives_wardroom_channel(self, assignment_with_wardroom):
        svc = assignment_with_wardroom
        a = await svc.create_assignment(
            name="Done Team", assignment_type="away_team",
            created_by="captain", members=["a1"],
        )
        await svc.complete_assignment(a.id)

        # Verify channel is archived
        async with svc._ward_room._db.execute(
            "SELECT archived FROM channels WHERE id = ?",
            (a.ward_room_channel_id,),
        ) as cursor:
            row = await cursor.fetchone()
            assert row[0] == 1

    async def test_create_without_wardroom_works(self, assignment_service):
        """Without ward_room, assignments work but have no channel."""
        a = await assignment_service.create_assignment(
            name="Solo Team", assignment_type="away_team",
            created_by="captain", members=["a1"],
        )
        assert a.ward_room_channel_id == ""


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------

class TestEvents:
    async def test_create_emits_event(self, assignment_service):
        assignment_service._captured_events.clear()
        await assignment_service.create_assignment(
            name="Team", assignment_type="away_team",
            created_by="captain", members=["a1"],
        )
        created_events = [e for e in assignment_service._captured_events if e["type"] == "assignment_created"]
        assert len(created_events) == 1
        assert created_events[0]["data"]["name"] == "Team"

    async def test_add_member_emits_event(self, assignment_service):
        a = await assignment_service.create_assignment(
            name="Team", assignment_type="away_team",
            created_by="captain", members=["a1"],
        )
        assignment_service._captured_events.clear()
        await assignment_service.add_member(a.id, "a2")

        updated_events = [e for e in assignment_service._captured_events if e["type"] == "assignment_updated"]
        assert len(updated_events) == 1
        assert updated_events[0]["data"]["action"] == "add_member"

    async def test_complete_emits_event(self, assignment_service):
        a = await assignment_service.create_assignment(
            name="Team", assignment_type="away_team",
            created_by="captain", members=["a1"],
        )
        assignment_service._captured_events.clear()
        await assignment_service.complete_assignment(a.id)

        completed_events = [e for e in assignment_service._captured_events if e["type"] == "assignment_completed"]
        assert len(completed_events) == 1
        assert completed_events[0]["data"]["status"] == "completed"


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

class TestSnapshot:
    async def test_get_assignment_snapshot(self, assignment_service):
        await assignment_service.create_assignment(
            name="A", assignment_type="away_team",
            created_by="captain", members=["a1"],
        )
        await assignment_service.create_assignment(
            name="B", assignment_type="bridge",
            created_by="captain", members=["a2"],
        )

        snapshot = assignment_service.get_assignment_snapshot()
        assert len(snapshot) == 2
        names = {s["name"] for s in snapshot}
        assert "A" in names
        assert "B" in names
        # Snapshot should be dicts, not Assignment objects
        assert isinstance(snapshot[0], dict)
