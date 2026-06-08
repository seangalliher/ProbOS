"""AD-928: agent-authored ``[STATUS]`` -> task-room "show your work" tests.

BF-287 discipline (MagicMock-at-substrate-boundary trap): the one substrate the
code under test actually touches is **real** -- a real :class:`ChatThreadStore`
on ``tmp_path``. The runtime container is a ``MagicMock(spec=ProbOSRuntime)``
shell (the AD-924/AD-927 precedent) but its ``chat_thread_store`` is the REAL
store, so the ``append_message`` post path and the ``_resolve_agent_task_room``
participation lookup exercise reality, never a mock. Rank is driven by the
injected trust score (``Rank.from_trust``); the agent / clock are real-but-fake
duck stubs, never ``MagicMock``.

v1 is MESSAGE-ONLY: the work item is NOT transitioned (forward marker AD-928a);
there is no UI status-chip render (AD-928b). These tests assert the backend
contract only: a status message lands in the task room with ``metadata.kind`` =
``"status"`` (and ``status_final`` for the final result), honest-degrade on the
no-room / empty / oversize / cap / malformed paths, and the rank gate.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from probos.config import SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.proactive import ProactiveCognitiveLoop
from probos.runtime import ProbOSRuntime
from probos.threads import ChatThreadStore
from probos.ward_room import WardRoomService


FEDERATION_ORDERS = Path("config/standing_orders/federation.md")
GROUP_CHAT_MANUAL = Path("config/manuals/group-chat.md")


# Trust thresholds: <0.5 ensign, 0.5-0.7 lieutenant, 0.7-0.85 commander, 0.85+ senior.
_TRUST_LIEUTENANT = 0.6
_TRUST_ENSIGN = 0.3


class _FakeAgent:
    """Real-but-fake crew agent: ``.id`` + ``.agent_type`` (no ``.callsign`` ->
    the log line falls back to ``agent_type``)."""

    def __init__(self, agent_id: str, agent_type: str = "builder") -> None:
        self.id = agent_id
        self.agent_type = agent_type
        self.is_alive = True


class _Clock:
    """Deterministic injectable clock (real fixture, not MagicMock)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def _build_loop(tmp_path, *, trust: float = _TRUST_LIEUTENANT, cfg=None, clock=None):
    """Wire a real ChatThreadStore behind a MagicMock(spec=ProbOSRuntime) shell.

    The artifact/attachment stores are left ``None`` so the AD-927 artifact
    extractor (which the end-to-end ``_extract_and_execute_actions`` path also
    runs) is a clean honest-degrade no-op -- these tests exercise only the
    AD-928 status path.
    """
    cfg = cfg or SystemConfig()
    clk = clock or _Clock()
    thread_store = ChatThreadStore(tmp_path / "chat_threads.db", clock=clk)
    runtime = MagicMock(spec=ProbOSRuntime)
    runtime.ward_room = MagicMock(spec=WardRoomService)   # truthy -> passes the early-return guard
    runtime.ward_room_router = None                        # neutralize the endorsement/reply path
    runtime.is_cold_start = False
    runtime.trust_network = MagicMock(spec=TrustNetwork)
    runtime.trust_network.get_score.return_value = trust
    runtime.config = cfg
    runtime.artifact_store = None                          # AD-927 extractor early-returns (no-op)
    runtime.attachment_store = None
    runtime.chat_thread_store = thread_store               # REAL
    loop = ProactiveCognitiveLoop(interval=60)
    loop.set_runtime(runtime)
    return loop, thread_store, runtime


# ---------------- 1. happy path: status lands in the task room ----------------


@pytest.mark.asyncio
async def test_status_posted_to_task_room(tmp_path):
    loop, thr_store, _ = _build_loop(tmp_path)
    agent = _FakeAgent("agent-1")
    room = thr_store.create_thread(
        title="Task Room", participants=["agent-1", "other"], task_id="task-1",
    )
    text = "On it. [STATUS]Drafting the analysis section now.[/STATUS] more prose."

    cleaned, actions = await loop._extract_and_execute_statuses(agent, text)

    status_actions = [a for a in actions if a["type"] == "status"]
    assert len(status_actions) == 1
    assert status_actions[0]["thread_id"] == room.id
    assert status_actions[0]["final"] is False
    msgs = thr_store.list_messages(room.id)
    assert len(msgs) == 1
    assert msgs[0].body == "Drafting the analysis section now."
    assert msgs[0].author_id == "agent-1"
    assert msgs[0].role == "agent"
    assert msgs[0].metadata == {"kind": "status"}
    # tag stripped, prose retained
    assert "[STATUS" not in cleaned
    assert "[/STATUS]" not in cleaned
    assert "On it." in cleaned
    assert "more prose." in cleaned


# ---------------- 2. final variant sets status_final ----------------


@pytest.mark.asyncio
async def test_final_status_sets_status_final(tmp_path):
    loop, thr_store, _ = _build_loop(tmp_path)
    agent = _FakeAgent("agent-1")
    room = thr_store.create_thread(
        title="Task Room", participants=["agent-1"], task_id="task-1",
    )
    text = "[STATUS final]Complete. Final report attached to the room.[/STATUS]"

    _, actions = await loop._extract_and_execute_statuses(agent, text)

    status_actions = [a for a in actions if a["type"] == "status"]
    assert len(status_actions) == 1
    assert status_actions[0]["final"] is True
    msgs = thr_store.list_messages(room.id)
    assert len(msgs) == 1
    assert msgs[0].metadata["kind"] == "status"
    assert msgs[0].metadata["status_final"] is True


# ---------------- 3. end-to-end via _extract_and_execute_actions (rank gate) ----------------


@pytest.mark.asyncio
async def test_status_end_to_end_through_gate(tmp_path):
    loop, thr_store, _ = _build_loop(tmp_path)
    agent = _FakeAgent("agent-1")
    room = thr_store.create_thread(
        title="Task Room", participants=["agent-1"], task_id="task-1",
    )
    text = "Here we go. [STATUS]Kicked off the task.[/STATUS] done"

    cleaned, actions = await loop._extract_and_execute_actions(agent, text)

    status_actions = [a for a in actions if a["type"] == "status"]
    assert len(status_actions) == 1
    assert status_actions[0]["thread_id"] == room.id
    msgs = thr_store.list_messages(room.id)
    assert len(msgs) == 1
    assert msgs[0].metadata == {"kind": "status"}
    assert "[STATUS" not in cleaned


# ---------------- 4. no task room -> honest-degrade ----------------


@pytest.mark.asyncio
async def test_no_task_room_honest_degrades(tmp_path):
    loop, thr_store, _ = _build_loop(tmp_path)
    agent = _FakeAgent("agent-1")
    # The agent participates only in a plain (no-task_id) thread; the one task
    # room that exists does NOT list the agent as a participant.
    thr_store.create_thread(title="Plain", participants=["agent-1"])  # no task_id
    other = thr_store.create_thread(
        title="Other Task", participants=["other"], task_id="task-9",
    )
    text = "[STATUS]Working on it.[/STATUS]"

    cleaned, actions = await loop._extract_and_execute_statuses(agent, text)

    assert any(
        a["type"] == "status_suppressed" and a["reason"] == "no_task_room"
        for a in actions
    )
    assert not any(a["type"] == "status" for a in actions)
    assert thr_store.list_messages(other.id) == []  # nothing posted anywhere
    assert "[STATUS" not in cleaned  # tag stripped regardless of outcome


# ---------------- 5. rank-gated out below threshold (Ensign) ----------------


@pytest.mark.asyncio
async def test_rank_gated_out_below_threshold(tmp_path):
    loop, thr_store, _ = _build_loop(tmp_path, trust=_TRUST_ENSIGN)
    agent = _FakeAgent("agent-1")
    room = thr_store.create_thread(
        title="Task Room", participants=["agent-1"], task_id="task-1",
    )
    text = "[STATUS]Working on it.[/STATUS]"

    _, actions = await loop._extract_and_execute_actions(agent, text)

    # Gate skipped at Ensign -> the status path never runs: no status (or
    # status_suppressed) action is emitted and no message is posted. (Had the
    # gate passed, the valid room + body would have produced a post.) The bare
    # opening tag is later removed by the pre-existing BF-203 hallucinated-tag
    # cleanup (proactive.py), a different path -- so we assert on the post path,
    # NOT on tag survival.
    assert not any(a["type"] in ("status", "status_suppressed") for a in actions)
    assert thr_store.list_messages(room.id) == []


# ---------------- 6. per-turn cap enforced ----------------


@pytest.mark.asyncio
async def test_per_turn_cap_enforced(tmp_path):
    cfg = SystemConfig()
    cfg.communications.status_max_per_turn = 3
    loop, thr_store, _ = _build_loop(tmp_path, cfg=cfg)
    agent = _FakeAgent("agent-1")
    room = thr_store.create_thread(
        title="Task Room", participants=["agent-1"], task_id="task-1",
    )
    text = "[STATUS]a[/STATUS] [STATUS]b[/STATUS] [STATUS]c[/STATUS] [STATUS]d[/STATUS]"

    _, actions = await loop._extract_and_execute_statuses(agent, text)

    posted = [a for a in actions if a["type"] == "status"]
    rate = [
        a for a in actions
        if a["type"] == "status_suppressed" and a["reason"] == "rate_limited"
    ]
    assert len(posted) == 3
    assert len(rate) == 1
    assert len(thr_store.list_messages(room.id)) == 3


# ---------------- 7. oversized body suppressed ----------------


@pytest.mark.asyncio
async def test_oversized_body_suppressed(tmp_path):
    cfg = SystemConfig()
    cfg.communications.status_max_bytes = 10
    loop, thr_store, _ = _build_loop(tmp_path, cfg=cfg)
    agent = _FakeAgent("agent-1")
    room = thr_store.create_thread(
        title="Task Room", participants=["agent-1"], task_id="task-1",
    )
    text = "[STATUS]this status line is definitely longer than ten bytes[/STATUS]"

    _, actions = await loop._extract_and_execute_statuses(agent, text)

    assert any(
        a["type"] == "status_suppressed" and a["reason"] == "too_large"
        for a in actions
    )
    assert thr_store.list_messages(room.id) == []


# ---------------- 8. empty body suppressed ----------------


@pytest.mark.asyncio
async def test_empty_body_suppressed(tmp_path):
    loop, thr_store, _ = _build_loop(tmp_path)
    agent = _FakeAgent("agent-1")
    room = thr_store.create_thread(
        title="Task Room", participants=["agent-1"], task_id="task-1",
    )
    text = "[STATUS]   [/STATUS]"  # whitespace-only body

    cleaned, actions = await loop._extract_and_execute_statuses(agent, text)

    assert any(
        a["type"] == "status_suppressed" and a["reason"] == "empty" for a in actions
    )
    assert thr_store.list_messages(room.id) == []
    assert "[STATUS" not in cleaned


# ---------------- 9. malformed tag (no closing) left intact ----------------


@pytest.mark.asyncio
async def test_malformed_tag_left_intact(tmp_path):
    loop, thr_store, _ = _build_loop(tmp_path)
    agent = _FakeAgent("agent-1")
    room = thr_store.create_thread(
        title="Task Room", participants=["agent-1"], task_id="task-1",
    )
    text = "[STATUS] with no closing tag"  # no [/STATUS] -> does not match

    cleaned, actions = await loop._extract_and_execute_statuses(agent, text)

    assert actions == []
    assert cleaned == text  # no match -> .sub is a no-op
    assert thr_store.list_messages(room.id) == []


# ---------------- 10. mixed milestones in one turn (document order) ----------------


@pytest.mark.asyncio
async def test_mixed_milestones_in_one_turn(tmp_path):
    loop, thr_store, _ = _build_loop(tmp_path)
    agent = _FakeAgent("agent-1")
    room = thr_store.create_thread(
        title="Task Room", participants=["agent-1"], task_id="task-1",
    )
    text = (
        "[STATUS]first milestone[/STATUS] "
        "[STATUS]second milestone[/STATUS] "
        "[STATUS final]all done[/STATUS]"
    )

    _, actions = await loop._extract_and_execute_statuses(agent, text)

    # Actions are emitted in document order (finditer order), deterministic
    # regardless of DB tie-ordering: progress, progress, then final.
    posted = [a for a in actions if a["type"] == "status"]
    assert len(posted) == 3
    assert posted[0]["final"] is False
    assert posted[1]["final"] is False
    assert posted[2]["final"] is True
    # All three landed; the final one carries status_final, the others do not.
    msgs = thr_store.list_messages(room.id)
    assert len(msgs) == 3
    by_body = {m.body: m.metadata for m in msgs}
    assert by_body["first milestone"] == {"kind": "status"}
    assert by_body["second milestone"] == {"kind": "status"}
    assert by_body["all done"] == {"kind": "status", "status_final": True}


# ---------------- 11. federation.md standing order ----------------


def test_federation_md_contains_show_your_work_instruction():
    text = FEDERATION_ORDERS.read_text(encoding="utf-8")
    assert "### Show Your Work" in text
    assert "[STATUS" in text
    assert "[/STATUS]" in text
    # Encoding Safety rule: the NEW section must stay ASCII-only -- it sits inside
    # the AD-924 "### Group Chat".."### Notebook" slice, so a non-ASCII char here
    # would break the AD-924 content test too.
    start = text.index("### Show Your Work")
    section = text[start:text.index("### Notebook", start)]
    assert all(ord(c) < 128 for c in section)


# ---------------- 12. manual seeded ----------------


def test_show_your_work_manual_seeded():
    assert GROUP_CHAT_MANUAL.exists()
    text = GROUP_CHAT_MANUAL.read_text(encoding="utf-8")
    assert "[STATUS" in text
    assert "Showing Your Work" in text
    # Encoding Safety rule: ASCII-only (no chars > 0x7F).
    assert all(ord(c) < 128 for c in text)


# ---------------- 13. config defaults ----------------


def test_status_config_defaults():
    comms = SystemConfig().communications
    assert comms.status_min_rank == "lieutenant"
    assert comms.status_max_per_turn == 3
    assert comms.status_max_bytes == 4096
