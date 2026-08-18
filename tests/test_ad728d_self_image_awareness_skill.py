"""AD-728d: tests for self-image-awareness skill + [SELF_CHECK] marker.

Seven boundary tests covering: SKILL.md loads with correct frontmatter,
skill surfaces for the three configured intents on find_augmentation_skills,
marker stripped from reply text, valid reason dispatches check_own_render,
invalid reason silently strips (no dispatch), multiple markers (first
dispatches, rest stripped, WARNING logged), disabled gate still dispatches.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.dm import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm.reply_value import DmReply  # AD-1248
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.cognitive.skill_catalog import (
    CognitiveSkillCatalog,
    parse_skill_file,
)


# --------------------------------------------------------------------------- #
# Minimal fakes                                                                #
# --------------------------------------------------------------------------- #


@dataclass
class _FakeConfig:
    avatar_telemetry: Any | None = None


@dataclass
class _FakeRuntime:
    config: _FakeConfig = field(default_factory=_FakeConfig)
    recreation_service: Any | None = None
    callsign_registry: Any | None = None
    ward_room: Any | None = None
    episodic_memory: Any | None = None
    intent_bus: Any | None = None
    divergence_results: dict[str, Any] | None = None
    profile_store: Any | None = None


@dataclass
class _RecordingAgent:
    """Records check_own_render invocations without unittest.mock."""

    agent_id: str = "ezri"
    agent_type: str = "counselor"
    working_memory: Any | None = None
    calls: list[str | None] = field(default_factory=list)

    def mark_reply_emitted(self) -> None:
        pass

    async def check_own_render(self, reason: str | None = None) -> None:
        self.calls.append(reason)


def _ctx(*, response_text: str, agent: _RecordingAgent | None = None) -> DmReplyContext:
    return DmReplyContext(
        runtime=_FakeRuntime(),
        agent=agent or _RecordingAgent(),
        agent_id="ezri",
        callsign="ezri",
        req_message="hello",
        reply=DmReply(body=response_text),
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=DmSanityGate(),
        params={},
        message_text="hello",
        sampling_state=None,
        avatar_event_bus=None,
    )


# --------------------------------------------------------------------------- #
# 1. SKILL.md loads with correct frontmatter                                   #
# --------------------------------------------------------------------------- #


def test_skill_md_loads_with_correct_frontmatter() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    skill_md = repo_root / "config" / "skills" / "self-image-awareness" / "SKILL.md"
    assert skill_md.exists(), "SKILL.md must exist at canonical path"

    entry = parse_skill_file(skill_md)
    assert entry is not None
    assert entry.name == "self-image-awareness"
    assert entry.activation == "augmentation"
    assert "direct_message" in entry.intents
    assert "ward_room_notification" in entry.intents
    assert "proactive_think" in entry.intents
    # Hard-stop: skill must NOT load for unrelated intents.
    assert "system_heartbeat" not in entry.intents
    assert "run_command" not in entry.intents


# --------------------------------------------------------------------------- #
# 2. Skill surfaces for the three configured intents on a crew agent          #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_skill_appears_for_direct_message_intent_on_crew_agent(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_skill = repo_root / "config" / "skills" / "self-image-awareness" / "SKILL.md"
    skill_dir = tmp_path / "self-image-awareness"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        src_skill.read_text(encoding="utf-8"), encoding="utf-8"
    )

    catalog = CognitiveSkillCatalog(skills_dir=tmp_path)
    await catalog.start()
    try:
        for intent in ("direct_message", "ward_room_notification", "proactive_think"):
            results = catalog.find_augmentation_skills(
                intent, department="medical", agent_rank="lieutenant"
            )
            names = [e.name for e in results]
            assert "self-image-awareness" in names, (
                f"skill must surface for intent={intent}"
            )
        # Hard-stop: skill MUST NOT surface for unrelated intents.
        for intent in ("system_heartbeat", "run_command", "http_fetch"):
            results = catalog.find_augmentation_skills(intent)
            assert not any(e.name == "self-image-awareness" for e in results), (
                f"skill must not surface for intent={intent}"
            )
    finally:
        await catalog.stop()


# --------------------------------------------------------------------------- #
# 3. Marker stripped from reply text                                           #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_marker_stripped_from_reply_text() -> None:
    ctx = _ctx(response_text="All clear, Captain. [SELF_CHECK pre_reply]")
    pipeline = DmReplyPipeline(ctx)
    await pipeline.step_4_self_check_parse()
    # Drain the fire-and-forget so it doesn't leak into other tests.
    if ctx._self_check_task is not None:
        await ctx._self_check_task
    assert ctx.response_text == "All clear, Captain."


# --------------------------------------------------------------------------- #
# 4. Valid reason dispatches check_own_render                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_marker_dispatches_check_own_render_with_reason() -> None:
    agent = _RecordingAgent()
    ctx = _ctx(
        response_text="Hello [SELF_CHECK pre_reply] world",
        agent=agent,
    )
    pipeline = DmReplyPipeline(ctx)
    await pipeline.step_4_self_check_parse()
    # Hard-stop: task reference held on ctx, not on agent.
    assert ctx._self_check_task is not None
    assert isinstance(ctx._self_check_task, asyncio.Task)
    await ctx._self_check_task
    assert agent.calls == ["pre_reply"]


# --------------------------------------------------------------------------- #
# 5. Invalid reason silently strips, no dispatch                               #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_invalid_reason_silently_strips_no_dispatch() -> None:
    agent = _RecordingAgent()
    ctx = _ctx(
        response_text="Hello [SELF_CHECK HowDoILook?] world",
        agent=agent,
    )
    pipeline = DmReplyPipeline(ctx)
    await pipeline.step_4_self_check_parse()
    assert ctx._self_check_task is None
    assert agent.calls == []
    # The lax strip regex removes the malformed marker too.
    assert "[SELF_CHECK" not in ctx.response_text
    assert "Hello" in ctx.response_text
    assert "world" in ctx.response_text


# --------------------------------------------------------------------------- #
# 6. Multiple markers — first dispatches, others stripped, WARNING logged     #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_multiple_markers_first_dispatches_warning_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    agent = _RecordingAgent()
    ctx = _ctx(
        response_text="[SELF_CHECK pre_reply] body [SELF_CHECK mid_conversation]",
        agent=agent,
    )
    pipeline = DmReplyPipeline(ctx)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.dm.reply_pipeline"):
        await pipeline.step_4_self_check_parse()
    assert ctx._self_check_task is not None
    await ctx._self_check_task
    assert agent.calls == ["pre_reply"]
    assert "[SELF_CHECK" not in ctx.response_text
    # Exactly one WARNING containing AD-728d and the count "2".
    matching = [
        r for r in caplog.records
        if r.levelno == logging.WARNING
        and "AD-728d" in r.getMessage()
        and " 2 " in r.getMessage()
    ]
    assert len(matching) == 1, (
        f"expected exactly one AD-728d collapse warning, got {len(matching)}: "
        f"{[r.getMessage() for r in caplog.records]}"
    )


# --------------------------------------------------------------------------- #
# 7. Disabled gate still dispatches (honest-degrade is downstream)            #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_disabled_gate_still_dispatches_honest_degrade() -> None:
    # The runtime fake has no avatars.render_self_check_enabled — the
    # pipeline does NOT short-circuit on the gate. The dispatched coroutine
    # itself honest-degrades inside verify_render_coherence (covered by
    # AD-728c tests).
    agent = _RecordingAgent()
    ctx = _ctx(
        response_text="check me [SELF_CHECK appearance_changed]",
        agent=agent,
    )
    pipeline = DmReplyPipeline(ctx)
    await pipeline.step_4_self_check_parse()
    assert ctx._self_check_task is not None
    await ctx._self_check_task
    assert agent.calls == ["appearance_changed"]
