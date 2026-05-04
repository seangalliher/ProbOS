"""Tests for AD-683: Ship State Snapshot for Cold-Start Onboarding."""

from __future__ import annotations

import dataclasses
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.boot_camp import BootCampCoordinator
from probos.config import BootCampConfig, ShipStateSnapshotConfig
from probos.events import EventType
from probos.onboarding import (
    DepartmentSummary,
    ShipStateSnapshot,
    ShipStateSnapshotBuilder,
    WardRoomTopicSummary,
)
from probos.startup.finalize import _wire_ship_state_snapshot


# ---------------------------------------------------------------------------
# Section 0 — EventType
# ---------------------------------------------------------------------------


def test_event_type_registered() -> None:
    assert EventType.SHIP_STATE_SNAPSHOT_CAPTURED.value == "ship_state_snapshot_captured"


# ---------------------------------------------------------------------------
# Section 2 — Dataclasses
# ---------------------------------------------------------------------------


def test_dataclass_frozen_and_field_order() -> None:
    snap = ShipStateSnapshot(
        captured_at=100.0,
        vessel_name="Enterprise",
        alert_condition="YELLOW",
        uptime_seconds=42.5,
        active_crew_count=7,
        departments=(DepartmentSummary("bridge", "Bridge", 2),),
        open_work_item_count=1,
        open_work_item_titles=("fix warp core",),
        recent_ward_room_topics=(
            WardRoomTopicSummary(channel_name="ship", thread_titles=("hello",)),
        ),
    )
    fields = dataclasses.fields(snap)
    assert fields[0].name == "captured_at"
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.vessel_name = "Voyager"  # type: ignore[misc]
    d = snap.to_dict()
    assert d["captured_at"] == 100.0
    assert d["vessel_name"] == "Enterprise"
    assert d["departments"] == [
        {"department_id": "bridge", "name": "Bridge", "crew_count": 2}
    ]
    assert d["open_work_item_titles"] == ["fix warp core"]
    assert d["recent_ward_room_topics"] == [
        {"channel_name": "ship", "thread_titles": ["hello"]}
    ]


def test_render_text_contains_key_fields() -> None:
    snap = ShipStateSnapshot(
        captured_at=0.0,
        vessel_name="Enterprise",
        alert_condition="YELLOW",
        uptime_seconds=42.9,
        active_crew_count=7,
        departments=(DepartmentSummary("bridge", "Bridge", 2),),
        open_work_item_count=1,
        open_work_item_titles=("fix warp core",),
        recent_ward_room_topics=(
            WardRoomTopicSummary(
                channel_name="ship", thread_titles=("hello world",)
            ),
        ),
    )
    text = snap.render_text()
    assert "Enterprise" in text
    assert "YELLOW" in text
    assert "42s" in text  # int-cast of uptime
    assert "Active crew: 7" in text
    assert "fix warp core" in text
    assert "[ship]" in text
    assert "hello world" in text


# ---------------------------------------------------------------------------
# Section 2 — Builder
# ---------------------------------------------------------------------------


def _make_runtime_full() -> SimpleNamespace:
    """Construct a runtime mock with all collectors populated."""
    identity = SimpleNamespace(name="Enterprise")
    state = SimpleNamespace(
        alert_condition="YELLOW", uptime_seconds=42.0, active_crew_count=7
    )
    bridge_dept = SimpleNamespace(id="bridge", name="Bridge", description="")
    med_dept = SimpleNamespace(id="med", name="Medical", description="")
    captain_assign = SimpleNamespace(agent_id="a-captain", post_id="p-captain")
    bones_assign = SimpleNamespace(agent_id="a-bones", post_id="p-bones")
    captain_post = SimpleNamespace(department_id="bridge")
    bones_post = SimpleNamespace(department_id="med")

    def get_assignment_for_agent(agent_type: str):
        return {"captain": captain_assign, "bones": bones_assign}.get(agent_type)

    def get_post_for_agent(agent_type: str):
        return {"captain": captain_post, "bones": bones_post}.get(agent_type)

    ontology = SimpleNamespace(
        get_vessel_identity=lambda: identity,
        get_vessel_state=lambda: state,
        get_departments=lambda: [bridge_dept, med_dept],
        get_crew_agent_types=lambda: {"captain", "bones"},
        get_assignment_for_agent=get_assignment_for_agent,
        get_post_for_agent=get_post_for_agent,
    )

    work_items = [
        SimpleNamespace(title="fix warp core"),
        SimpleNamespace(title="run diagnostics"),
        SimpleNamespace(title="update logs"),
    ]
    work_item_store = SimpleNamespace(
        list_work_items=AsyncMock(return_value=work_items)
    )

    ch_ship = SimpleNamespace(id="ship", name="ship")
    ch_eng = SimpleNamespace(id="eng", name="engineering")

    async def list_threads(channel_id, limit=3, sort="recent"):
        return [
            SimpleNamespace(title=f"{channel_id} thread 1"),
            SimpleNamespace(title=f"{channel_id} thread 2"),
        ]

    ward_room = SimpleNamespace(
        list_channels=AsyncMock(return_value=[ch_ship, ch_eng]),
        list_threads=list_threads,
    )

    return SimpleNamespace(
        ontology=ontology, work_item_store=work_item_store, ward_room=ward_room
    )


@pytest.mark.asyncio
async def test_builder_happy_path_full_data() -> None:
    runtime = _make_runtime_full()
    emit_event = MagicMock()
    builder = ShipStateSnapshotBuilder(runtime, emit_event=emit_event)

    snap = await builder.build()

    assert snap.vessel_name == "Enterprise"
    assert snap.alert_condition == "YELLOW"
    assert snap.uptime_seconds == 42.0
    assert snap.active_crew_count == 7
    dept_map = {d.department_id: d for d in snap.departments}
    assert dept_map["bridge"].crew_count == 1
    assert dept_map["med"].crew_count == 1
    assert snap.open_work_item_count == 3
    assert "fix warp core" in snap.open_work_item_titles
    assert len(snap.recent_ward_room_topics) == 2

    # Privacy: emit payload contains COUNTS only.
    assert emit_event.call_count == 1
    call = emit_event.call_args
    assert call.args[0] == EventType.SHIP_STATE_SNAPSHOT_CAPTURED
    payload = call.args[1]
    assert payload["work_item_count"] == 3
    assert payload["dept_count"] == 2
    assert payload["topic_count"] == 2
    assert payload["alert_condition"] == "YELLOW"
    # No titles or department names in payload.
    assert "open_work_item_titles" not in payload
    assert "departments" not in payload
    assert "thread_titles" not in payload


@pytest.mark.asyncio
async def test_builder_degrades_when_collectors_missing() -> None:
    runtime = SimpleNamespace()
    builder = ShipStateSnapshotBuilder(runtime)
    snap = await builder.build()
    assert snap.vessel_name == "ProbOS"
    assert snap.alert_condition == "GREEN"
    assert snap.uptime_seconds == 0.0
    assert snap.active_crew_count == 0
    assert snap.departments == ()
    assert snap.open_work_item_count == 0
    assert snap.open_work_item_titles == ()
    assert snap.recent_ward_room_topics == ()


@pytest.mark.asyncio
async def test_builder_degrades_when_collectors_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    boom = RuntimeError("boom")
    ontology = MagicMock()
    ontology.get_vessel_identity.side_effect = boom
    ontology.get_departments.side_effect = boom

    work_item_store = SimpleNamespace(list_work_items=AsyncMock(side_effect=boom))
    ward_room = SimpleNamespace(list_channels=AsyncMock(side_effect=boom))

    runtime = SimpleNamespace(
        ontology=ontology, work_item_store=work_item_store, ward_room=ward_room
    )
    builder = ShipStateSnapshotBuilder(runtime)
    with caplog.at_level(logging.WARNING):
        snap = await builder.build()
    # All defaults; no exception escaped.
    assert snap.vessel_name == "ProbOS"
    assert snap.open_work_item_count == 0
    assert any("AD-683" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Section 5 — Capture in BootCampCoordinator.activate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_in_boot_camp_activate() -> None:
    runtime = _make_runtime_full()
    builder = ShipStateSnapshotBuilder(runtime)

    ward_room = AsyncMock()
    trust_service = MagicMock()
    trust_service.get_trust_score = MagicMock(return_value=0.0)
    episodic = AsyncMock()

    coord = BootCampCoordinator(
        config=BootCampConfig(),
        ward_room=ward_room,
        trust_service=trust_service,
        episodic_memory=episodic,
        ship_state_builder=builder,
    )
    assert coord.ship_state_snapshot is None

    await coord.activate(
        [{"agent_id": "a1", "callsign": "Bones", "department": "medical"}]
    )

    assert coord._active is True  # ordering: active set before snapshot read
    assert coord.ship_state_snapshot is not None
    assert isinstance(coord.ship_state_snapshot, ShipStateSnapshot)
    assert coord.ship_state_snapshot.vessel_name == "Enterprise"


def test_boot_camp_coordinator_backward_compat_and_wirer() -> None:
    """Section 5 backward-compat + Section 4 wirer (combined to hit 8-test exact count)."""
    # Backward-compat: BootCampCoordinator constructs without ship_state_builder kwarg.
    coord = BootCampCoordinator(
        config=BootCampConfig(),
        ward_room=AsyncMock(),
        trust_service=MagicMock(),
        episodic_memory=AsyncMock(),
    )
    assert coord.ship_state_snapshot is None

    # Wirer enabled path.
    runtime_on = MagicMock(spec=["emit_event", "ship_state_snapshot"])
    config_on = SimpleNamespace(
        ship_state_snapshot=ShipStateSnapshotConfig(enabled=True)
    )
    assert _wire_ship_state_snapshot(runtime=runtime_on, config=config_on) is True
    assert isinstance(runtime_on.ship_state_snapshot, ShipStateSnapshotBuilder)

    # Wirer disabled path.
    runtime_off = SimpleNamespace(emit_event=lambda *a, **k: None)
    config_off = SimpleNamespace(
        ship_state_snapshot=ShipStateSnapshotConfig(enabled=False)
    )
    assert _wire_ship_state_snapshot(runtime=runtime_off, config=config_off) is False
    assert not hasattr(runtime_off, "ship_state_snapshot")
