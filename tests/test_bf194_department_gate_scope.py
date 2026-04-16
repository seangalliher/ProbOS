"""BF-194: Department gate applies only to department channels.

AD-629 introduced a per-department "first responder wins" gate inside
``check_and_increment_reply_cap()``. That gate fired unconditionally, which
blocked Captain all-hands messages on ship-wide channels — only 5-6 of 14
crew could reply because one agent per department consumed the department
slot for the entire thread.

BF-194 scopes the gate to department channels only. Ship-wide channels
(All Hands, Recreation) allow multiple agents per department. The default
for ``is_department_channel`` is ``False`` — safe for the common case
(Captain all-hands traffic).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════


def _make_config(max_per_thread: int = 3):
    cfg = MagicMock()
    cfg.ward_room.max_agent_responses_per_thread = max_per_thread
    cfg.ward_room.event_coalesce_ms = 0
    return cfg


def _make_router(
    config=None,
    ontology=None,
    registry=None,
):
    from probos.ward_room_router import WardRoomRouter

    config = config or _make_config()
    registry = registry or MagicMock()
    if ontology is None:
        ontology = MagicMock()
        ontology.get_agent_department.return_value = None

    return WardRoomRouter(
        ward_room=MagicMock(),
        registry=registry,
        intent_bus=MagicMock(),
        trust_network=MagicMock(),
        ontology=ontology,
        callsign_registry=MagicMock(),
        episodic_memory=None,
        event_emitter=MagicMock(),
        event_log=MagicMock(),
        config=config,
        proactive_loop=None,
    )


def _dept_registry(agent_dept_map: dict[str, str]):
    """Build (ontology, registry) pair where agents are keyed by id.

    ``agent_dept_map`` maps agent_id -> department_id. Each agent's
    ``agent_type`` is set equal to its id for simplicity.
    """
    ontology = MagicMock()
    registry = MagicMock()

    agent_type_to_dept = {aid: dept for aid, dept in agent_dept_map.items()}

    def dept_lookup(agent_type):
        return agent_type_to_dept.get(agent_type)

    ontology.get_agent_department.side_effect = dept_lookup

    def get_agent(aid):
        if aid not in agent_dept_map:
            return None
        a = MagicMock()
        a.agent_type = aid
        return a

    registry.get.side_effect = get_agent
    return ontology, registry


# ══════════════════════════════════════════════════════════════════════
# Department gate scoping (the core fix)
# ══════════════════════════════════════════════════════════════════════


class TestDepartmentGateScope:
    def test_department_gate_blocks_on_department_channel(self):
        """Existing behavior preserved: same-dept second agent blocked on
        department channel."""
        ontology, registry = _dept_registry({
            "agent-scotty": "engineering",
            "agent-laforge": "engineering",
        })
        router = _make_router(ontology=ontology, registry=registry)

        assert router.check_and_increment_reply_cap(
            "thread-1", "agent-scotty", is_department_channel=True,
        ) is True
        assert router.check_and_increment_reply_cap(
            "thread-1", "agent-laforge", is_department_channel=True,
        ) is False

    def test_department_gate_allows_on_ship_channel(self):
        """BF-194 fix: same-dept agents both pass on ship-wide channel."""
        ontology, registry = _dept_registry({
            "agent-scotty": "engineering",
            "agent-laforge": "engineering",
        })
        router = _make_router(ontology=ontology, registry=registry)

        assert router.check_and_increment_reply_cap(
            "thread-1", "agent-scotty", is_department_channel=False,
        ) is True
        assert router.check_and_increment_reply_cap(
            "thread-1", "agent-laforge", is_department_channel=False,
        ) is True

    def test_department_gate_default_false(self):
        """Omitting the kwarg must NOT apply the department gate (safe
        default for Captain all-hands traffic)."""
        ontology, registry = _dept_registry({
            "agent-scotty": "engineering",
            "agent-laforge": "engineering",
        })
        router = _make_router(ontology=ontology, registry=registry)

        assert router.check_and_increment_reply_cap(
            "thread-1", "agent-scotty",
        ) is True
        assert router.check_and_increment_reply_cap(
            "thread-1", "agent-laforge",
        ) is True

    def test_per_agent_cap_still_enforced_on_ship_channel(self):
        """Per-agent cap is independent of channel type."""
        ontology, registry = _dept_registry({"agent-scotty": "engineering"})
        router = _make_router(
            config=_make_config(max_per_thread=2),
            ontology=ontology, registry=registry,
        )

        assert router.check_and_increment_reply_cap(
            "thread-1", "agent-scotty", is_department_channel=False,
        ) is True
        assert router.check_and_increment_reply_cap(
            "thread-1", "agent-scotty", is_department_channel=False,
        ) is True
        # Third attempt blocked by per-agent cap, not department gate
        assert router.check_and_increment_reply_cap(
            "thread-1", "agent-scotty", is_department_channel=False,
        ) is False

    def test_all_14_crew_eligible_ship_channel(self):
        """Regression witness: 14 crew across 6 departments all pass on a
        ship-wide channel (the bug was: only 5-6 passed)."""
        crew = {
            # Science (5)
            "architect": "science",
            "scout": "science",
            "data_analyst": "science",
            "systems_analyst": "science",
            "research_specialist": "science",
            # Medical (4)
            "diagnostician": "medical",
            "surgeon": "medical",
            "pharmacist": "medical",
            "pathologist": "medical",
            # Engineering (2)
            "engineering_officer": "engineering",
            "builder": "engineering",
            # Security (1)
            "security_officer": "security",
            # Operations (1)
            "operations_officer": "operations",
            # Bridge (1)
            "counselor": "bridge",
        }
        ontology, registry = _dept_registry(crew)
        router = _make_router(ontology=ontology, registry=registry)

        allowed = [
            router.check_and_increment_reply_cap(
                "thread-1", agent_id, is_department_channel=False,
            )
            for agent_id in crew
        ]
        assert all(allowed), f"Expected 14 allowed, got {sum(allowed)}"
        assert len(allowed) == 14

    def test_department_gate_mixed_channels(self):
        """An agent may record department participation in a department
        thread, yet still reply in a ship-wide thread (different thread_id)
        without being blocked."""
        ontology, registry = _dept_registry({
            "agent-scotty": "engineering",
            "agent-laforge": "engineering",
        })
        router = _make_router(ontology=ontology, registry=registry)

        # Department channel: thread-dept. Scotty records engineering.
        assert router.check_and_increment_reply_cap(
            "thread-dept", "agent-scotty", is_department_channel=True,
        ) is True
        # Ship-wide channel: thread-ship. LaForge (same dept) is NOT
        # blocked — different thread, and gate is skipped anyway.
        assert router.check_and_increment_reply_cap(
            "thread-ship", "agent-laforge", is_department_channel=False,
        ) is True
        # And Scotty can also reply in the ship thread.
        assert router.check_and_increment_reply_cap(
            "thread-ship", "agent-scotty", is_department_channel=False,
        ) is True


# ══════════════════════════════════════════════════════════════════════
# Proactive call site passes the flag
# ══════════════════════════════════════════════════════════════════════


class TestProactiveReplyPassesChannelType:
    @pytest.mark.asyncio
    async def test_proactive_reply_passes_channel_type_ship(self):
        """Ship-wide channel: proactive path invokes cap with
        is_department_channel=False."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = MagicMock(spec=ProactiveCognitiveLoop)
        loop._runtime = MagicMock()
        loop._reply_cooldowns = {}

        wr_router = MagicMock()
        wr_router.check_and_increment_reply_cap.return_value = True
        loop._runtime.ward_room_router = wr_router

        # Mock async ward_room with get_thread and get_channel
        loop._runtime.ward_room = AsyncMock()
        loop._runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"locked": False, "channel_id": "ship-ch"},
            "posts": [],
        })
        ship_channel = MagicMock()
        ship_channel.channel_type = "public"  # not "department"
        loop._runtime.ward_room.get_channel = AsyncMock(return_value=ship_channel)
        loop._runtime.ward_room.create_post = AsyncMock()

        loop._runtime.callsign_registry = MagicMock()
        loop._runtime.callsign_registry.get_callsign.return_value = "Scotty"

        agent = MagicMock()
        agent.id = "agent-scotty"
        agent.agent_type = "scotty"

        text = "[REPLY thread-abc] Engines are nominal. [/REPLY]"

        loop._resolve_thread_id = AsyncMock(return_value="thread-abc")
        loop._is_similar_to_recent_posts = AsyncMock(return_value=False)
        loop._extract_commands_from_reply = AsyncMock(
            return_value=("Engines are nominal.", []),
        )
        loop._get_comm_gate_overrides = MagicMock(return_value=None)

        real_method = ProactiveCognitiveLoop._extract_and_execute_replies
        await real_method(loop, agent, text)

        wr_router.check_and_increment_reply_cap.assert_called_once()
        _args, _kwargs = wr_router.check_and_increment_reply_cap.call_args
        assert _args == ("thread-abc", "agent-scotty")
        assert _kwargs.get("is_department_channel") is False

    @pytest.mark.asyncio
    async def test_proactive_reply_passes_channel_type_department(self):
        """Department channel: proactive path invokes cap with
        is_department_channel=True."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = MagicMock(spec=ProactiveCognitiveLoop)
        loop._runtime = MagicMock()
        loop._reply_cooldowns = {}

        wr_router = MagicMock()
        wr_router.check_and_increment_reply_cap.return_value = True
        loop._runtime.ward_room_router = wr_router

        loop._runtime.ward_room = AsyncMock()
        loop._runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"locked": False, "channel_id": "eng-ch"},
            "posts": [],
        })
        dept_channel = MagicMock()
        dept_channel.channel_type = "department"
        loop._runtime.ward_room.get_channel = AsyncMock(return_value=dept_channel)
        loop._runtime.ward_room.create_post = AsyncMock()

        loop._runtime.callsign_registry = MagicMock()
        loop._runtime.callsign_registry.get_callsign.return_value = "Scotty"

        agent = MagicMock()
        agent.id = "agent-scotty"
        agent.agent_type = "scotty"

        text = "[REPLY thread-abc] Engines are nominal. [/REPLY]"

        loop._resolve_thread_id = AsyncMock(return_value="thread-abc")
        loop._is_similar_to_recent_posts = AsyncMock(return_value=False)
        loop._extract_commands_from_reply = AsyncMock(
            return_value=("Engines are nominal.", []),
        )
        loop._get_comm_gate_overrides = MagicMock(return_value=None)

        real_method = ProactiveCognitiveLoop._extract_and_execute_replies
        await real_method(loop, agent, text)

        wr_router.check_and_increment_reply_cap.assert_called_once()
        _args, _kwargs = wr_router.check_and_increment_reply_cap.call_args
        assert _args == ("thread-abc", "agent-scotty")
        assert _kwargs.get("is_department_channel") is True

    @pytest.mark.asyncio
    async def test_proactive_reply_defaults_false_on_lookup_failure(self):
        """If get_channel raises, fall back to is_department_channel=False
        (over-permit rather than under-permit)."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = MagicMock(spec=ProactiveCognitiveLoop)
        loop._runtime = MagicMock()
        loop._reply_cooldowns = {}

        wr_router = MagicMock()
        wr_router.check_and_increment_reply_cap.return_value = True
        loop._runtime.ward_room_router = wr_router

        loop._runtime.ward_room = AsyncMock()
        loop._runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"locked": False, "channel_id": "broken-ch"},
            "posts": [],
        })
        loop._runtime.ward_room.get_channel = AsyncMock(
            side_effect=RuntimeError("db error"),
        )
        loop._runtime.ward_room.create_post = AsyncMock()

        loop._runtime.callsign_registry = MagicMock()
        loop._runtime.callsign_registry.get_callsign.return_value = "Scotty"

        agent = MagicMock()
        agent.id = "agent-scotty"
        agent.agent_type = "scotty"

        text = "[REPLY thread-abc] Engines are nominal. [/REPLY]"

        loop._resolve_thread_id = AsyncMock(return_value="thread-abc")
        loop._is_similar_to_recent_posts = AsyncMock(return_value=False)
        loop._extract_commands_from_reply = AsyncMock(
            return_value=("Engines are nominal.", []),
        )
        loop._get_comm_gate_overrides = MagicMock(return_value=None)

        real_method = ProactiveCognitiveLoop._extract_and_execute_replies
        await real_method(loop, agent, text)

        wr_router.check_and_increment_reply_cap.assert_called_once()
        _args, _kwargs = wr_router.check_and_increment_reply_cap.call_args
        assert _kwargs.get("is_department_channel") is False
