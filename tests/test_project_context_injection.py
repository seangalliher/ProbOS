"""AD-793 (Wave 196): pytest for project preamble injection into the
DM message_text + ordering guard (visual → project → recall → user)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.config import CognitiveConfig, DmTargetedLookupConfig
from probos.routers.agents import agent_chat
from probos.threads import ChatThreadStore, ProjectStore


_CREW_PATCH = patch("probos.routers.agents.is_crew_agent", return_value=True)


def _make_runtime(
    *,
    db_path: Path,
    dm_targeted_lookup_enabled: bool = False,
    perception_enabled: bool = False,
):
    runtime = MagicMock()

    # Real stores so thread.project_id round-trips correctly.
    runtime.chat_thread_store = ChatThreadStore(db_path=db_path)
    runtime.project_store = ProjectStore(db_path=db_path)

    # Registry / agent.
    agent = MagicMock()
    agent.id = "test-id"
    agent.agent_type = "science_officer"
    agent.confidence = 0.7
    runtime.registry.get.return_value = agent
    runtime.callsign_registry.get_callsign.return_value = "Lynx"

    # Capture sent IntentMessage.
    intent_result = MagicMock()
    intent_result.result = "Acknowledged, Captain. Reviewing context now."
    intent_result.error = None
    runtime.intent_bus.send = AsyncMock(return_value=intent_result)

    runtime.recreation_service = None
    runtime.ward_room = None

    runtime.config = SimpleNamespace(
        attachments=SimpleNamespace(
            enabled=True,
            text_extraction_max_bytes=1024,
            pdf_extraction_enabled=False,
            vision_tier="standard",
        ),
        cognitive=CognitiveConfig(),
        dm_targeted_lookup=DmTargetedLookupConfig(
            enabled=dm_targeted_lookup_enabled
        ),
        perception=SimpleNamespace(
            enabled=perception_enabled,
            dm_force_describe_enabled=False,
        ),
    )

    runtime.llm_client = MagicMock()
    runtime.llm_client.get_health_status = MagicMock(
        return_value={"tiers": {"standard": {"status": "operational"}},
                      "overall": "operational"},
    )
    runtime.episodic_memory = None
    from probos.cognitive.dm_sanity_gate import DmSanityGate
    runtime.dm_sanity_gate = DmSanityGate()

    return runtime


def _req(message: str = "hello"):
    r = MagicMock()
    r.message = message
    r.history = []
    r.attachment_ids = []
    r.thread_id = None
    return r


@pytest.mark.asyncio
async def test_project_description_prepended_to_chat(tmp_path: Path) -> None:
    runtime = _make_runtime(db_path=tmp_path / "t.db")
    # Create project + thread inside it.
    project = runtime.project_store.create_project(
        name="ProbOS Dev",
        description="Working on the OSS runtime",
    )
    thread = runtime.chat_thread_store.create_thread(
        title="Lynx",
        participants=["test-id"],
        project_id=project.id,
    )
    req = _req("hi")
    req.thread_id = thread.id

    with _CREW_PATCH:
        await agent_chat("test-id", req, runtime)

    sent_intent = runtime.intent_bus.send.call_args.args[0]
    text = sent_intent.params["text"]
    assert "--- Project: ProbOS Dev ---" in text
    assert "Working on the OSS runtime" in text
    assert "--- End Project Context ---" in text


@pytest.mark.asyncio
async def test_no_preamble_when_project_id_null(tmp_path: Path) -> None:
    runtime = _make_runtime(db_path=tmp_path / "t.db")
    # Thread with no project.
    thread = runtime.chat_thread_store.create_thread(
        title="Lynx",
        participants=["test-id"],
        project_id=None,
    )
    req = _req("hi")
    req.thread_id = thread.id

    with _CREW_PATCH:
        await agent_chat("test-id", req, runtime)

    sent_intent = runtime.intent_bus.send.call_args.args[0]
    text = sent_intent.params["text"]
    assert "--- Project:" not in text
    assert "--- End Project Context ---" not in text


@pytest.mark.asyncio
async def test_empty_description_omitted(tmp_path: Path) -> None:
    runtime = _make_runtime(db_path=tmp_path / "t.db")
    project = runtime.project_store.create_project(
        name="Empty Project",
        description="",  # empty → preamble omitted
    )
    thread = runtime.chat_thread_store.create_thread(
        title="Lynx",
        participants=["test-id"],
        project_id=project.id,
    )
    req = _req("hi")
    req.thread_id = thread.id

    with _CREW_PATCH:
        await agent_chat("test-id", req, runtime)

    sent_intent = runtime.intent_bus.send.call_args.args[0]
    text = sent_intent.params["text"]
    # No preamble even though project_id is set — empty description
    # silently omits the block (Tier-2 honest-degrade).
    assert "--- Project:" not in text


@pytest.mark.asyncio
async def test_ordering_visual_project_recall_user(tmp_path: Path) -> None:
    """Substring-index guard: visual → project → recall → user.

    Without this test, future changes to agents.py could silently
    reorder the chain (the spec's R3 defect is exactly this regression
    class).
    """
    runtime = _make_runtime(
        db_path=tmp_path / "t.db",
        dm_targeted_lookup_enabled=True,
        perception_enabled=True,
    )
    project = runtime.project_store.create_project(
        name="OrderProj",
        description="ProjectDescriptionMarker",
    )
    thread = runtime.chat_thread_store.create_thread(
        title="Lynx",
        participants=["test-id"],
        project_id=project.id,
    )
    req = _req("UserMessageMarker")
    req.thread_id = thread.id

    # Stub the targeted-lookup dispatcher to inject a recall block.
    from probos.cognitive.dm_targeted_lookup import (
        LookupDispatcher,
        TargetedLookupResult,
    )

    async def _fake_lookup(self, message, *, agent_id):
        return TargetedLookupResult(
            lookup_type="episodic",
            query=message,
            content="RecallContentMarker",
            elapsed_ms=1.0,
        )

    # Stub working memory to inject a visual scene block.
    fake_wm = MagicMock()
    fake_wm.render_for_prompt = MagicMock(return_value="VisualSceneMarker")

    with _CREW_PATCH, \
         patch.object(LookupDispatcher, "maybe_lookup", _fake_lookup), \
         patch(
             "probos.perception.consumer.get_or_create_working_memory",
             return_value=fake_wm,
         ):
        await agent_chat("test-id", req, runtime)

    sent_intent = runtime.intent_bus.send.call_args.args[0]
    text = sent_intent.params["text"]

    # All four markers present.
    assert "VisualSceneMarker" in text
    assert "ProjectDescriptionMarker" in text
    assert "RecallContentMarker" in text
    assert "UserMessageMarker" in text

    # Substring-index ordering: visual → project → recall → user.
    i_visual = text.index("VisualSceneMarker")
    i_project = text.index("ProjectDescriptionMarker")
    i_recall = text.index("RecallContentMarker")
    i_user = text.index("UserMessageMarker")
    assert i_visual < i_project < i_recall < i_user, (
        f"Bad ordering: visual={i_visual} project={i_project} "
        f"recall={i_recall} user={i_user}\nFull text:\n{text}"
    )


@pytest.mark.asyncio
async def test_missing_project_store_degrades(tmp_path: Path) -> None:
    """Honest-degrade: when project_store is missing from the runtime
    (older code path / migration window), the DM still goes through
    with no preamble injection and no crash."""
    runtime = _make_runtime(db_path=tmp_path / "t.db")
    project = runtime.project_store.create_project(
        name="P", description="should not appear",
    )
    thread = runtime.chat_thread_store.create_thread(
        title="Lynx", participants=["test-id"], project_id=project.id,
    )
    # Strip project_store off the runtime to simulate the migration
    # window where the substrate hasn't been wired yet.
    runtime.project_store = None
    req = _req("hello")
    req.thread_id = thread.id

    with _CREW_PATCH:
        await agent_chat("test-id", req, runtime)

    sent_intent = runtime.intent_bus.send.call_args.args[0]
    text = sent_intent.params["text"]
    assert "should not appear" not in text
    assert "--- Project:" not in text
