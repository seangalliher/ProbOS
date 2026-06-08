"""AD-927: agent-authored ``[ARTIFACT]`` -> task-room Output pane tests.

BF-287 discipline (MagicMock-at-substrate-boundary trap): every substrate the
code under test actually touches is **real** -- a real :class:`ArtifactStore`, a
real :class:`FilesystemAttachmentStore`, and a real :class:`ChatThreadStore` on
``tmp_path``. The runtime container is a ``MagicMock(spec=ProbOSRuntime)`` shell
(the AD-924 precedent) but its substrate attributes are the REAL stores, so the
two-call write path (`sha256` -> ``attachment_store.write`` -> ``add_version``)
exercises reality, never a mock. Rank is driven by the injected trust score
(``Rank.from_trust``); the agent / clock are real-but-fake duck stubs, never
``MagicMock``.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.artifacts import ArtifactStore
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.proactive import ProactiveCognitiveLoop
from probos.runtime import ProbOSRuntime
from probos.threads import ChatThreadStore
from probos.ward_room import WardRoomService


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
    """Wire real stores behind a MagicMock(spec=ProbOSRuntime) shell (AD-924)."""
    cfg = cfg or SystemConfig()
    clk = clock or _Clock()
    artifact_store = ArtifactStore(tmp_path / "artifacts.db")
    attachment_store = FilesystemAttachmentStore(tmp_path / "attachments")
    thread_store = ChatThreadStore(tmp_path / "chat_threads.db", clock=clk)
    runtime = MagicMock(spec=ProbOSRuntime)
    runtime.ward_room = MagicMock(spec=WardRoomService)   # truthy -> passes the early-return guard
    runtime.ward_room_router = None                        # neutralize the endorsement/reply path
    runtime.is_cold_start = False
    runtime.trust_network = MagicMock(spec=TrustNetwork)
    runtime.trust_network.get_score.return_value = trust
    runtime.config = cfg
    runtime.artifact_store = artifact_store                # REAL
    runtime.attachment_store = attachment_store            # REAL
    runtime.chat_thread_store = thread_store               # REAL
    loop = ProactiveCognitiveLoop(interval=60)
    loop.set_runtime(runtime)
    return loop, artifact_store, attachment_store, thread_store, runtime


# ---------------- 1. happy path: artifact lands in the task room ----------------


@pytest.mark.asyncio
async def test_artifact_written_to_task_room(tmp_path):
    loop, art_store, att_store, thr_store, _ = _build_loop(tmp_path)
    agent = _FakeAgent("agent-1")
    room = thr_store.create_thread(
        title="Task Room", participants=["agent-1", "other"], task_id="task-1",
    )
    text = 'Working on it. [ARTIFACT name="report"]# Final\nbody[/ARTIFACT] done.'

    cleaned, actions = await loop._extract_and_execute_actions(agent, text)

    art_actions = [a for a in actions if a["type"] == "artifact"]
    assert len(art_actions) == 1
    assert art_actions[0]["thread_id"] == room.id
    assert art_actions[0]["name"] == "report"
    assert art_actions[0]["version"] == 1
    latest = art_store.list_thread_latest(room.id)
    assert len(latest) == 1
    assert latest[0].name == "report"
    # bytes landed in AttachmentStore under the sha256
    body_bytes = await att_store.read(latest[0].content_hash)
    assert body_bytes == b"# Final\nbody"
    # tag stripped from posted text
    assert "[ARTIFACT" not in cleaned
    assert "[/ARTIFACT]" not in cleaned


# ---------------- 2. second [ARTIFACT name=report] -> version 2 ----------------


@pytest.mark.asyncio
async def test_second_artifact_increments_version(tmp_path):
    loop, art_store, _, thr_store, _ = _build_loop(tmp_path)
    agent = _FakeAgent("agent-1")
    room = thr_store.create_thread(
        title="Task Room", participants=["agent-1"], task_id="task-1",
    )

    _, actions1 = await loop._extract_and_execute_artifacts(
        agent, '[ARTIFACT name="report"]v1 body[/ARTIFACT]',
    )
    _, actions2 = await loop._extract_and_execute_artifacts(
        agent, '[ARTIFACT name="report"]v2 body[/ARTIFACT]',
    )

    assert actions1[0]["version"] == 1
    assert actions2[0]["version"] == 2
    latest = art_store.list_thread_latest(room.id)
    assert len(latest) == 1
    assert latest[0].version == 2
    versions = art_store.list_versions(thread_id=room.id, name="report")
    assert len(versions) == 2
    assert versions[1].supersedes == versions[0].id  # supersedes chained


# ---------------- 3. tag stripped, prose retained ----------------


@pytest.mark.asyncio
async def test_tag_stripped_from_posted_text(tmp_path):
    loop, _, _, thr_store, _ = _build_loop(tmp_path)
    agent = _FakeAgent("agent-1")
    thr_store.create_thread(title="Task Room", participants=["agent-1"], task_id="task-1")
    text = 'Here it is [ARTIFACT name="x"]body[/ARTIFACT] done'

    cleaned, _ = await loop._extract_and_execute_actions(agent, text)

    assert "[ARTIFACT" not in cleaned
    assert "[/ARTIFACT]" not in cleaned
    assert "Here it is" in cleaned
    assert "done" in cleaned


# ---------------- 4. no task room -> honest-degrade ----------------


@pytest.mark.asyncio
async def test_no_task_room_honest_degrades(tmp_path):
    loop, art_store, _, thr_store, _ = _build_loop(tmp_path)
    agent = _FakeAgent("agent-1")
    # The agent participates only in a plain (no-task_id) thread; the one task
    # room that exists does NOT list the agent as a participant.
    thr_store.create_thread(title="Plain", participants=["agent-1"])  # no task_id
    thr_store.create_thread(title="Other Task", participants=["other"], task_id="task-9")
    text = '[ARTIFACT name="report"]body[/ARTIFACT]'

    cleaned, actions = await loop._extract_and_execute_artifacts(agent, text)

    assert any(
        a["type"] == "artifact_suppressed" and a["reason"] == "no_task_room"
        for a in actions
    )
    assert not any(a["type"] == "artifact" for a in actions)
    assert "[ARTIFACT" not in cleaned  # tag stripped regardless of outcome


# ---------------- 5. rank-gated out below threshold (Ensign) ----------------


@pytest.mark.asyncio
async def test_rank_gated_out_below_threshold(tmp_path):
    loop, art_store, _, thr_store, _ = _build_loop(tmp_path, trust=_TRUST_ENSIGN)
    agent = _FakeAgent("agent-1")
    room = thr_store.create_thread(
        title="Task Room", participants=["agent-1"], task_id="task-1",
    )
    text = '[ARTIFACT name="report"]body[/ARTIFACT]'

    _, actions = await loop._extract_and_execute_actions(agent, text)

    # Gate skipped at Ensign -> the artifact path never runs: no artifact (or
    # artifact_suppressed) action is emitted and no artifact row is written.
    # (Had the gate passed, the valid room + body would have produced a write.)
    # The bare opening tag is later removed by the pre-existing BF-203
    # hallucinated-tag cleanup (proactive.py), which is a different path from
    # the AD-927 gate -- so we assert on the write path, not on tag survival.
    assert not any(a["type"] in ("artifact", "artifact_suppressed") for a in actions)
    assert art_store.list_thread_latest(room.id) == []


# ---------------- 6. empty body suppressed ----------------


@pytest.mark.asyncio
async def test_empty_body_suppressed(tmp_path):
    loop, art_store, _, thr_store, _ = _build_loop(tmp_path)
    agent = _FakeAgent("agent-1")
    room = thr_store.create_thread(
        title="Task Room", participants=["agent-1"], task_id="task-1",
    )
    text = '[ARTIFACT name="x"]   [/ARTIFACT]'  # whitespace-only body

    cleaned, actions = await loop._extract_and_execute_artifacts(agent, text)

    assert any(
        a["type"] == "artifact_suppressed" and a["reason"] == "empty" for a in actions
    )
    assert art_store.list_thread_latest(room.id) == []
    assert "[ARTIFACT" not in cleaned


# ---------------- 7. oversized body suppressed ----------------


@pytest.mark.asyncio
async def test_oversized_body_suppressed(tmp_path):
    cfg = SystemConfig()
    cfg.communications.artifact_max_bytes = 10
    loop, art_store, _, thr_store, _ = _build_loop(tmp_path, cfg=cfg)
    agent = _FakeAgent("agent-1")
    room = thr_store.create_thread(
        title="Task Room", participants=["agent-1"], task_id="task-1",
    )
    text = '[ARTIFACT name="report"]this body is definitely longer than ten bytes[/ARTIFACT]'

    cleaned, actions = await loop._extract_and_execute_artifacts(agent, text)

    assert any(
        a["type"] == "artifact_suppressed" and a["reason"] == "too_large"
        for a in actions
    )
    assert art_store.list_thread_latest(room.id) == []
    assert "[ARTIFACT" not in cleaned


# ---------------- 8. per-turn cap enforced ----------------


@pytest.mark.asyncio
async def test_per_turn_cap_enforced(tmp_path):
    cfg = SystemConfig()
    cfg.communications.artifact_max_per_turn = 1
    loop, art_store, _, thr_store, _ = _build_loop(tmp_path, cfg=cfg)
    agent = _FakeAgent("agent-1")
    room = thr_store.create_thread(
        title="Task Room", participants=["agent-1"], task_id="task-1",
    )
    text = '[ARTIFACT name="a"]body a[/ARTIFACT] [ARTIFACT name="b"]body b[/ARTIFACT]'

    cleaned, actions = await loop._extract_and_execute_artifacts(agent, text)

    arts = [a for a in actions if a["type"] == "artifact"]
    rate = [
        a for a in actions
        if a["type"] == "artifact_suppressed" and a["reason"] == "rate_limited"
    ]
    assert len(arts) == 1
    assert len(rate) == 1
    assert len(art_store.list_thread_latest(room.id)) == 1
    assert "[ARTIFACT" not in cleaned
    assert "[/ARTIFACT]" not in cleaned


# ---------------- 9. malformed tag (no name=) left intact ----------------


@pytest.mark.asyncio
async def test_malformed_tag_left_intact(tmp_path):
    loop, art_store, _, thr_store, _ = _build_loop(tmp_path)
    agent = _FakeAgent("agent-1")
    room = thr_store.create_thread(
        title="Task Room", participants=["agent-1"], task_id="task-1",
    )
    text = '[ARTIFACT]body[/ARTIFACT]'  # missing name="..." -> does not match

    cleaned, actions = await loop._extract_and_execute_artifacts(agent, text)

    assert actions == []
    assert cleaned == text  # no match -> .sub is a no-op
    assert art_store.list_thread_latest(room.id) == []


# ---------------- 10. resolver picks the most-recent PARTICIPATING task room ----------------


@pytest.mark.asyncio
async def test_resolver_picks_most_recent_participating_task_room(tmp_path):
    clk = _Clock(start=1000.0)
    loop, art_store, _, thr_store, _ = _build_loop(tmp_path, clock=clk)
    agent = _FakeAgent("agent-1")
    clk.now = 1000.0
    room_a = thr_store.create_thread(title="A", participants=["agent-1"], task_id="task-1")
    clk.now = 2000.0
    room_b = thr_store.create_thread(title="B", participants=["agent-1"], task_id="task-2")
    clk.now = 3000.0  # most recent, but the agent is NOT a participant
    room_c = thr_store.create_thread(title="C", participants=["other"], task_id="task-3")
    text = '[ARTIFACT name="report"]body[/ARTIFACT]'

    _, actions = await loop._extract_and_execute_artifacts(agent, text)

    arts = [a for a in actions if a["type"] == "artifact"]
    assert len(arts) == 1
    assert arts[0]["thread_id"] == room_b.id  # most-recent PARTICIPATING task room
    assert art_store.list_thread_latest(room_b.id)
    assert art_store.list_thread_latest(room_a.id) == []  # older participating room not chosen
    assert art_store.list_thread_latest(room_c.id) == []  # non-participating room ignored


# ---------------- 11. store unavailable -> degrade, text untouched ----------------


@pytest.mark.asyncio
async def test_store_unavailable_degrades(tmp_path):
    loop, _, _, thr_store, runtime = _build_loop(tmp_path)
    agent = _FakeAgent("agent-1")
    thr_store.create_thread(title="Task Room", participants=["agent-1"], task_id="task-1")
    runtime.artifact_store = None  # misconfigured runtime
    text = '[ARTIFACT name="report"]body[/ARTIFACT]'

    cleaned, actions = await loop._extract_and_execute_artifacts(agent, text)

    assert actions == []
    assert cleaned == text  # early return before .sub -> untouched
