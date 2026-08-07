"""BF-721: a DM reply must reach the agent that authored the thread.

`dm-captain-{agent_id[:8]}` truncates inside the agent TYPE, so every instance of
a type keys to the same channel (`counselor_counselor_0_…` and
`counselor_counselor_1_…` both → `counselo`). Agent-to-agent channels are worse:
the live vessel has 20+ `dm-{a8}-{b8}` channels holding threads from BOTH
participants, and the channel-level resolver answers with whichever prefix comes
first in the name.

The fix resolves per THREAD: `threads.author_id` already holds the exact full
agent id of the filer, so each thread carries its own `target_agent_id`. The
channel-level field stays as the fallback for threads with no registered author
(Captain-authored threads, unregistered authors).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from probos.routers.wardroom import (
    _resolve_dm_target_agent_id,
    _resolve_thread_target_agent_id,
    _thread_with_target,
    list_captain_dms,
    list_dm_channels,
    list_dm_threads,
    wardroom_thread_detail,
)


# ── Fakes ─────────────────────────────────────────────────────────


class _FakeAgent:
    def __init__(self, agent_id: str, alive: bool = True) -> None:
        self.id = agent_id
        self.is_alive = alive


class _FakeRegistry:
    """Registry double supporting both ``all()`` and ``get()``."""

    def __init__(self, agents: list[_FakeAgent]) -> None:
        self._agents = {a.id: a for a in agents}

    def all(self) -> list[_FakeAgent]:
        return list(self._agents.values())

    def get(self, agent_id: str) -> _FakeAgent | None:
        return self._agents.get(agent_id)


class _FakeChannel:
    def __init__(self, channel_id: str, name: str, description: str = "") -> None:
        self.id = channel_id
        self.name = name
        self.channel_type = "dm"
        self.description = description
        self.created_at = 1000.0


class _FakeThread:
    """Minimal stand-in for ``WardRoomThread`` (dataclass ⇒ has ``__dict__``)."""

    def __init__(self, thread_id: str, channel_id: str, author_id: str,
                 channel_name: str) -> None:
        self.id = thread_id
        self.channel_id = channel_id
        self.author_id = author_id
        self.title = f"thread {thread_id}"
        self.body = ""
        self.created_at = 1000.0
        self.last_activity = 1000.0
        self.channel_name = channel_name
        self.author_callsign = ""


class _FakeWardRoom:
    def __init__(self, channels: list[_FakeChannel],
                 threads_by_channel: dict[str, list[_FakeThread]]) -> None:
        self._channels = channels
        self._threads = threads_by_channel

    async def list_channels(self) -> list[_FakeChannel]:
        return self._channels

    async def list_threads(self, channel_id: str, limit: int = 100,
                           **_kwargs: Any) -> list[_FakeThread]:
        return self._threads.get(channel_id, [])[:limit]

    async def count_threads(self, channel_id: str) -> int:
        return len(self._threads.get(channel_id, []))

    async def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        for threads in self._threads.values():
            for t in threads:
                if t.id == thread_id:
                    return {"thread": dict(vars(t)), "posts": [], "total_post_count": 0}
        return None


# Two instances of the SAME agent type. `[:8]` of either is "counselo".
COUNSELOR_0 = "counselor_counselor_0_67c601cb"
COUNSELOR_1 = "counselor_counselor_1_aa11bb22"
SHARED_CHANNEL = "dm-captain-counselo"


@pytest.fixture
def same_type_runtime() -> SimpleNamespace:
    """One Captain-DM channel, two same-type agents, one thread each."""
    assert COUNSELOR_0[:8] == COUNSELOR_1[:8] == "counselo", "prefix collision is the premise"
    channel = _FakeChannel("ch-1", SHARED_CHANNEL)
    threads = [
        _FakeThread("t-0", "ch-1", COUNSELOR_0, SHARED_CHANNEL),
        _FakeThread("t-1", "ch-1", COUNSELOR_1, SHARED_CHANNEL),
    ]
    return SimpleNamespace(
        registry=_FakeRegistry([_FakeAgent(COUNSELOR_0), _FakeAgent(COUNSELOR_1)]),
        ward_room=_FakeWardRoom([channel], {"ch-1": threads}),
    )


# ── 1. The headline ───────────────────────────────────────────────


class TestPerThreadTargetResolution:
    """Two same-prefix agents in one channel: each thread answers its own author."""

    def test_each_thread_resolves_to_its_own_author(self, same_type_runtime):
        # Fails before the fix: the channel-level resolver returns instance 0 for both.
        assert _resolve_thread_target_agent_id(
            SHARED_CHANNEL, COUNSELOR_0, same_type_runtime) == COUNSELOR_0
        assert _resolve_thread_target_agent_id(
            SHARED_CHANNEL, COUNSELOR_1, same_type_runtime) == COUNSELOR_1

    @pytest.mark.asyncio
    async def test_captain_dms_payload_targets_each_thread_author(self, same_type_runtime):
        payload = await list_captain_dms(runtime=same_type_runtime)
        threads = payload[0]["threads"]
        by_id = {t["id"]: t["target_agent_id"] for t in threads}
        assert by_id == {"t-0": COUNSELOR_0, "t-1": COUNSELOR_1}

    @pytest.mark.asyncio
    async def test_dm_threads_payload_targets_each_thread_author(self, same_type_runtime):
        payload = await list_dm_threads("ch-1", runtime=same_type_runtime)
        by_id = {t["id"]: t["target_agent_id"] for t in payload["threads"]}
        assert by_id == {"t-0": COUNSELOR_0, "t-1": COUNSELOR_1}

    @pytest.mark.asyncio
    async def test_thread_detail_targets_the_open_threads_author(self, same_type_runtime):
        """The payload the HXI actually reads for the OPEN thread."""
        detail_0 = await wardroom_thread_detail("t-0", runtime=same_type_runtime)
        detail_1 = await wardroom_thread_detail("t-1", runtime=same_type_runtime)
        assert detail_0["thread"]["target_agent_id"] == COUNSELOR_0
        assert detail_1["thread"]["target_agent_id"] == COUNSELOR_1

    @pytest.mark.asyncio
    async def test_dms_latest_thread_targets_its_author(self, same_type_runtime):
        payload = await list_dm_channels(runtime=same_type_runtime)
        assert payload[0]["latest_thread"]["target_agent_id"] == COUNSELOR_0

    def test_agent_to_agent_channel_threads_target_their_own_authors(self):
        """Live vessel shape: `dm-{a8}-{b8}` holds threads from BOTH participants."""
        builder = "builder_builder_0_0e6917c3"
        engineer = "engineering_officer_engineering_officer_0_872b75e7"
        channel = "dm-builder_-engineer"
        rt = SimpleNamespace(registry=_FakeRegistry([_FakeAgent(builder), _FakeAgent(engineer)]))
        # Channel-level answers "builder" for every thread; per-thread does not.
        assert _resolve_dm_target_agent_id(channel, rt) == builder
        assert _resolve_thread_target_agent_id(channel, engineer, rt) == engineer
        assert _resolve_thread_target_agent_id(channel, builder, rt) == builder


# ── 2. Registration, not liveness (AD-1076 class) ─────────────────


class TestRestingAuthorStillResolves:
    def test_resting_author_resolves_per_thread(self):
        """A proactive crew member is idle most of the time; idle is not gone."""
        rt = SimpleNamespace(
            registry=_FakeRegistry([_FakeAgent(COUNSELOR_0, alive=False)]))
        assert _resolve_thread_target_agent_id(
            SHARED_CHANNEL, COUNSELOR_0, rt) == COUNSELOR_0

    def test_resting_agent_resolves_at_channel_level(self):
        """Channel-level fallback must not gate on liveness either."""
        rt = SimpleNamespace(
            registry=_FakeRegistry([_FakeAgent(COUNSELOR_0, alive=False)]))
        assert _resolve_dm_target_agent_id(SHARED_CHANNEL, rt) == COUNSELOR_0

    def test_agent_with_no_is_alive_attribute_resolves(self):
        """Registration is the test, so an object without ``is_alive`` is fine."""
        rt = SimpleNamespace(registry=_FakeRegistry([]))
        rt.registry._agents[COUNSELOR_0] = SimpleNamespace(id=COUNSELOR_0)
        assert _resolve_dm_target_agent_id(SHARED_CHANNEL, rt) == COUNSELOR_0
        assert _resolve_thread_target_agent_id(
            SHARED_CHANNEL, COUNSELOR_0, rt) == COUNSELOR_0


# ── 3/4/5. Fallbacks ──────────────────────────────────────────────


class TestFallbackToChannelTarget:
    def test_captain_authored_thread_falls_back_and_is_never_the_captain(self):
        rt = SimpleNamespace(registry=_FakeRegistry([_FakeAgent(COUNSELOR_0)]))
        result = _resolve_thread_target_agent_id(SHARED_CHANNEL, "captain", rt)
        assert result == COUNSELOR_0
        assert result != "captain"

    def test_unregistered_author_falls_back_to_channel_target(self):
        rt = SimpleNamespace(registry=_FakeRegistry([_FakeAgent(COUNSELOR_0)]))
        assert _resolve_thread_target_agent_id(
            SHARED_CHANNEL, "counselor_counselor_9_deadbeef", rt) == COUNSELOR_0

    def test_empty_author_falls_back_to_channel_target(self):
        rt = SimpleNamespace(registry=_FakeRegistry([_FakeAgent(COUNSELOR_0)]))
        assert _resolve_thread_target_agent_id(SHARED_CHANNEL, "", rt) == COUNSELOR_0

    def test_no_registered_agent_yields_none(self):
        rt = SimpleNamespace(registry=_FakeRegistry([]))
        assert _resolve_thread_target_agent_id(SHARED_CHANNEL, "captain", rt) is None
        assert _resolve_thread_target_agent_id(SHARED_CHANNEL, "who-dis", rt) is None

    @pytest.mark.asyncio
    async def test_endpoint_still_returns_payload_with_no_registered_agents(self):
        channel = _FakeChannel("ch-1", SHARED_CHANNEL)
        thread = _FakeThread("t-0", "ch-1", COUNSELOR_0, SHARED_CHANNEL)
        rt = SimpleNamespace(
            registry=_FakeRegistry([]),
            ward_room=_FakeWardRoom([channel], {"ch-1": [thread]}),
        )
        payload = await list_captain_dms(runtime=rt)
        assert len(payload) == 1
        assert payload[0]["target_agent_id"] is None
        assert payload[0]["threads"][0]["target_agent_id"] is None
        assert payload[0]["threads"][0]["id"] == "t-0"

    def test_registry_lookup_failure_degrades_to_channel_target(self):
        class _BoomOnGet(_FakeRegistry):
            def get(self, agent_id: str):
                raise RuntimeError("registry unavailable")

        rt = SimpleNamespace(registry=_BoomOnGet([_FakeAgent(COUNSELOR_0)]))
        assert _resolve_thread_target_agent_id(
            SHARED_CHANNEL, COUNSELOR_1, rt) == COUNSELOR_0

    def test_runtime_without_registry_yields_none(self):
        rt = SimpleNamespace()
        assert _resolve_thread_target_agent_id(SHARED_CHANNEL, COUNSELOR_0, rt) is None


# ── 6. Non-DM threads / channel-level compatibility ───────────────


class TestNonDmAndCompatibility:
    def test_non_dm_channel_thread_has_no_target(self):
        rt = SimpleNamespace(registry=_FakeRegistry([_FakeAgent(COUNSELOR_0)]))
        assert _resolve_thread_target_agent_id("ship-general", COUNSELOR_0, rt) is None

    @pytest.mark.asyncio
    async def test_channel_level_target_unchanged_for_single_agent_channel(self):
        """The pre-existing channel-level field keeps its pre-existing answer."""
        channel = _FakeChannel("ch-1", SHARED_CHANNEL, description="DM: Counselor → Captain")
        thread = _FakeThread("t-0", "ch-1", COUNSELOR_0, SHARED_CHANNEL)
        rt = SimpleNamespace(
            registry=_FakeRegistry([_FakeAgent(COUNSELOR_0)]),
            ward_room=_FakeWardRoom([channel], {"ch-1": [thread]}),
        )
        dms = await list_dm_channels(runtime=rt)
        captain_dms = await list_captain_dms(runtime=rt)
        assert dms[0]["target_agent_id"] == COUNSELOR_0
        assert captain_dms[0]["target_agent_id"] == COUNSELOR_0

    @pytest.mark.asyncio
    async def test_existing_thread_keys_are_preserved_verbatim(self):
        """The payload gains one key and changes nothing else."""
        channel = _FakeChannel("ch-1", SHARED_CHANNEL)
        thread = _FakeThread("t-0", "ch-1", COUNSELOR_0, SHARED_CHANNEL)
        expected = dict(vars(thread))
        rt = SimpleNamespace(
            registry=_FakeRegistry([_FakeAgent(COUNSELOR_0)]),
            ward_room=_FakeWardRoom([channel], {"ch-1": [thread]}),
        )
        payload = await list_dm_threads("ch-1", runtime=rt)
        served = payload["threads"][0]
        assert set(served) == set(expected) | {"target_agent_id"}
        for key, value in expected.items():
            assert served[key] == value

    def test_thread_with_target_does_not_mutate_its_source(self):
        rt = SimpleNamespace(registry=_FakeRegistry([_FakeAgent(COUNSELOR_0)]))
        thread = _FakeThread("t-0", "ch-1", COUNSELOR_0, SHARED_CHANNEL)
        _thread_with_target(thread, SHARED_CHANNEL, rt)
        assert not hasattr(thread, "target_agent_id")

    def test_thread_with_target_accepts_dict_rows(self):
        rt = SimpleNamespace(registry=_FakeRegistry([_FakeAgent(COUNSELOR_0)]))
        row = {"id": "t-0", "author_id": COUNSELOR_0, "channel_name": SHARED_CHANNEL}
        out = _thread_with_target(row, SHARED_CHANNEL, rt)
        assert out["target_agent_id"] == COUNSELOR_0
        assert "target_agent_id" not in row  # source untouched

    @pytest.mark.asyncio
    async def test_non_dm_thread_detail_carries_a_null_target(self):
        channel = _FakeChannel("ch-2", "ship-general")
        thread = _FakeThread("t-9", "ch-2", COUNSELOR_0, "ship-general")
        rt = SimpleNamespace(
            registry=_FakeRegistry([_FakeAgent(COUNSELOR_0)]),
            ward_room=_FakeWardRoom([channel], {"ch-2": [thread]}),
        )
        detail = await wardroom_thread_detail("t-9", runtime=rt)
        assert detail["thread"]["target_agent_id"] is None
        assert detail["thread"]["id"] == "t-9"
