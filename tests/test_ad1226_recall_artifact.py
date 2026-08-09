"""AD-1226 (#1197): an agent can recall what it produced, without carrying it.

Measured on the reference vessel 2026-08-08. The Captain asked Ezri for the top
fifteen PyPI packages; AD-1221 worked and the table was delivered correctly.
Four minutes later he asked her about it and she reported that she could not see
what she had sent, then offered to file a proposal to build the mechanism that
would let her. It was already built: AD-1166 had stored the episode at the exact
second of delivery with the real table in ``outcomes[0]["response"]``.

Two measured facts define the work, and this file pins both fixes:

1. Nothing read ``outcomes`` back. The recall dict was built from ``user_input``
   and ``reflection`` only, so the outcome never reached a prompt.
2. The write capped it at ``body[:500]`` anyway — 1362 chars and fifteen rows
   delivered, 500 chars and seven rows stored, cut mid-word at
   ``| charset-normalizer | 3.4.9 | The Real Fi``.

``test_the_crossing_promoted_run_to_rendered_ref_to_original_text`` is the test
that matters. Its absence is why this shipped: every half worked, and nothing
traversed the chain. It drives a real promoted run into a real
``EpisodicMemory``, a real ``FilesystemAttachmentStore`` and a real
``ArtifactStore``, renders the memory section through the real recall path,
takes the ref out of THE RENDERED LINE, and reads the original body back through
the real tool.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from probos.artifacts import ArtifactStore
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.turn_promotion import (
    _OUTCOME_DIGEST_CHARS,
    _outcome_digest,
    run_with_promotion,
)
from probos.config import SystemConfig
from probos.tools.recall_artifact_tool import (
    _MAX_CHARS_PER_READ,
    RecallArtifactTool,
)
from probos.types import Episode, IntentDescriptor, IntentMessage
from probos.workforce import WorkItem

AGENT = "counselor_counselor_0_abc"
OTHER = "yeoman_yeoman_0_xyz"
THREAD = "thread-1"

# The measured payload, in shape: a markdown table whose rows are longer than the
# digest cap, so a naive cut lands mid-cell.
TABLE_BODY = (
    "Here are the top 15 PyPI packages by download volume:\n\n"
    "| Package | Version | Summary |\n"
    "|---|---|---|\n"
    + "".join(
        f"| package-number-{i:02d} | 1.2.{i} | A reasonably wordy summary line "
        f"for entry {i:02d} so the row is not short |\n"
        for i in range(1, 16)
    )
    + "\nThat is the full list."
)


# ── harness ───────────────────────────────────────────────────────


class _RecallTestAgent(CognitiveAgent):
    """Minimal CognitiveAgent, mirroring tests/test_memory_integrity.py."""

    agent_type = "recall_test"
    _handled_intents = {"direct_message"}
    instructions = "You are a test agent."
    intent_descriptors = [
        IntentDescriptor(
            name="direct_message",
            params={"text": "input"},
            description="DM",
            tier="domain",
        )
    ]


class _FakeWorkItemStore:
    """Records create/transition, backed by the REAL ``WorkItem`` dataclass so a
    field name that does not exist raises here instead of passing silently."""

    def __init__(self) -> None:
        self.created: list[WorkItem] = []
        self.transitions: list[tuple[str, str, str]] = []

    async def create_work_item(self, **kwargs: Any) -> WorkItem:
        item = WorkItem(status="open", **kwargs)
        self.created.append(item)
        return item

    async def transition_work_item(
        self, work_item_id: str, new_status: str, source: str = "system",
    ) -> None:
        self.transitions.append((work_item_id, new_status, source))


class _FakeThreadStore:
    def __init__(self) -> None:
        self.appended: list[dict] = []

    def append_message(
        self, thread_id: str, *, author_id: str, role: str, body: str,
        metadata: dict | None = None,
    ) -> None:
        self.appended.append({"thread_id": thread_id, "body": body})


class _CollectingEpisodicMemory:
    """Round-trips ``outcomes`` through JSON exactly as ChromaDB storage does.

    ``EpisodicMemory`` persists outcomes as ``json.dumps(ep.outcomes)`` and
    rebuilds them with ``json.loads``. A double that kept the live dict would
    hide a ref that is not JSON-serialisable, so this one does not.
    """

    def __init__(self) -> None:
        self.stored: list[Episode] = []
        self.error: Exception | None = None

    async def store(self, episode: Episode, **_kwargs: Any) -> None:
        import dataclasses
        import json

        if self.error is not None:
            raise self.error
        self.stored.append(dataclasses.replace(
            episode, outcomes=json.loads(json.dumps(episode.outcomes)),
        ))

    async def recent_for_agent(self, agent_id: str, k: int = 5) -> list[Episode]:
        return [ep for ep in reversed(self.stored) if agent_id in ep.agent_ids][:k]


def _config(*, refs_on: bool) -> SystemConfig:
    cfg = SystemConfig()
    cfg.memory.recall_outcome_refs_enabled = refs_on
    return cfg


def _stores(tmp_path: Path) -> tuple[FilesystemAttachmentStore, ArtifactStore]:
    return (
        FilesystemAttachmentStore(tmp_path / "attachments"),
        ArtifactStore(tmp_path / "artifacts.db"),
    )


def _runtime(
    *,
    refs_on: bool,
    attachments: Any = None,
    artifacts: Any = None,
    memory: Any = None,
    work_items: Any = None,
    threads: Any = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        config=_config(refs_on=refs_on),
        attachment_store=attachments,
        artifact_store=artifacts,
        episodic_memory=memory,
        work_item_store=work_items,
        chat_thread_store=threads,
        registry=None,
    )


async def _drain(hold: set) -> None:
    while hold:
        await asyncio.gather(*tuple(hold), return_exceptions=True)
        await asyncio.sleep(0)


async def _promoted_run(
    *, runtime: Any, body: str, request_text: str = "top 15 PyPI packages",
) -> None:
    """Drive a REAL promotion end to end and settle its reporter task."""
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        return body

    await run_with_promotion(
        _work,
        promote_after_seconds=0.01,
        runtime=runtime,
        agent_id=AGENT,
        thread_id=THREAD,
        request_text=request_text,
        hold=hold,
        completed_probe=lambda: True,
    )
    release.set()
    await _drain(hold)


def _agent(runtime: Any) -> _RecallTestAgent:
    agent = _RecallTestAgent.__new__(_RecallTestAgent)
    agent.id = AGENT
    agent.sovereign_id = AGENT
    agent.agent_type = "recall_test"
    agent._runtime = runtime
    agent._question_classifier = None
    agent._retrieval_strategy_selector = None
    agent._spreading_activation = None
    return agent


def _memory_section(runtime: Any, memories: list[dict]) -> list[str]:
    return _agent(runtime)._format_memory_section(memories)


def _today_section(runtime: Any, memories: list[dict]) -> list[str]:
    """The exact lines this section produced before AD-1226 existed.

    Written out literally rather than derived from the implementation, so a
    change to the flag-off path fails here rather than silently redefining the
    baseline. The confabulation guard is fetched from the real method because
    its wording is AD-592's contract, not this test's subject.
    """
    guard = CognitiveAgent._confabulation_guard(None)
    lines = [
        "=== SHIP MEMORY (your experiences aboard this vessel) ===",
        "These are YOUR experiences. Do NOT confuse with training knowledge.",
        guard,
        "Markers: [direct] = you experienced it, [secondhand] = you heard about it.",
        "[verified] = corroborated by ship's log, [unverified] = not yet corroborated.",
        "",
    ]
    for mem in memories:
        lines.append("  [direct | unverified]")
        lines.append(f"    {mem.get('input', '') or mem.get('reflection', '')}")
    lines.append("")
    lines.append("=== END SHIP MEMORY ===")
    return lines


def _ref_memory() -> dict:
    return {
        "input": "[1:1 background task] Captain: top 15 PyPI packages",
        "reflection": "",
        "source": "direct",
        "outcome_digest": "Here are the top 15 PyPI packages",
        "outcome_ref": {
            "content_hash": "7f3a9c2e2b1d4455667788990011223344556677889900aabbccddeeff001122",
            "mime": "text/markdown",
            "size_bytes": 1362,
            "chars": 1362,
            "artifact_id": "art-1",
            "name": "task-70cd290af319",
        },
    }


async def _capture_offered_tools(runtime: Any) -> set[str]:
    """Drive the REAL executor tool assembly and report what reached the loop."""
    import probos.cognitive.swe_harness.agentic_loop as loop_mod
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

    seen: dict = {}

    class _CaptureLoop:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def run(self, **kwargs: Any) -> Any:
            seen["tools"] = kwargs.get("tools") or []
            return loop_mod.AgenticResult(final_text="ok")

    class _LLM:
        async def complete(self, request: Any, **_k: Any) -> Any:
            from probos.cognitive.llm_client import LLMResponse

            return LLMResponse(content="ok", model="m", tier="standard")

    original = loop_mod.AgenticLoop
    loop_mod.AgenticLoop = _CaptureLoop  # type: ignore[misc]
    try:
        await WorkItemAgenticExecutor(llm_client=_LLM()).run(
            agent_id=AGENT, instructions="i", task_text="t", runtime=runtime,
        )
    finally:
        loop_mod.AgenticLoop = original  # type: ignore[misc]

    return {
        (t.get("function") or {}).get("name") or t.get("name")
        for t in seen.get("tools", [])
    }


# ── 1. flag OFF is byte-identical ─────────────────────────────────


def test_format_memory_section_flag_off_is_byte_identical() -> None:
    """An episode carrying a ref renders EXACTLY as it did before AD-1226.

    Default-OFF has to mean the assembled prompt is unchanged, not merely
    similar — so this compares against literal expected lines, not a
    re-derivation of the implementation.
    """
    runtime = _runtime(refs_on=False)
    memories = [_ref_memory()]

    lines = _memory_section(runtime, memories)

    assert lines == _today_section(runtime, memories)
    assert "recall_artifact" not in "\n".join(lines)
    assert "you produced" not in "\n".join(lines)


def test_format_memory_section_flag_off_ignores_the_ref_keys_entirely() -> None:
    """A memory WITH ref keys and the same memory WITHOUT them render the same."""
    runtime = _runtime(refs_on=False)
    with_ref = _ref_memory()
    without_ref = {
        k: v for k, v in with_ref.items()
        if k not in ("outcome_ref", "outcome_digest")
    }

    assert _memory_section(runtime, [with_ref]) == _memory_section(
        runtime, [without_ref]
    )


async def test_the_tool_is_not_offered_when_the_flag_is_off(tmp_path: Path) -> None:
    """OFF must also mean the loop is never told the tool exists."""
    from probos.tools.registry import ToolRegistry

    attachments, _artifacts = _stores(tmp_path)
    runtime = SimpleNamespace(
        config=_config(refs_on=False),
        attachment_store=attachments,
        tool_registry=ToolRegistry(),
    )

    offered = await _capture_offered_tools(runtime)

    assert "recall_artifact" not in offered, (
        f"the tool leaked into the offer with the flag off; offered={sorted(offered)}"
    )


async def test_the_tool_is_actually_offered_when_the_flag_is_on(
    tmp_path: Path,
) -> None:
    """Registered is not offered. A tool the loop never sees answers nothing —
    the shape in which AD-1157 / BF-688 / BF-690 / BF-692 / BF-695 all shipped
    inert."""
    from probos.tools.registry import ToolRegistry

    attachments, _artifacts = _stores(tmp_path)
    runtime = SimpleNamespace(
        config=_config(refs_on=True),
        attachment_store=attachments,
        tool_registry=ToolRegistry(),
    )

    offered = await _capture_offered_tools(runtime)

    assert "recall_artifact" in offered, (
        f"the recall tool was not offered to the loop; offered={sorted(offered)}"
    )


# ── 2-4. the write side ───────────────────────────────────────────


async def test_a_promoted_run_stores_its_report_and_refs_it(
    tmp_path: Path,
) -> None:
    """The blob lands under ``agent_artifact``, a version is registered, and the
    outcome carries a well-formed ref to both."""
    attachments, artifacts = _stores(tmp_path)
    memory = _CollectingEpisodicMemory()
    runtime = _runtime(
        refs_on=True, attachments=attachments, artifacts=artifacts,
        memory=memory, work_items=_FakeWorkItemStore(), threads=_FakeThreadStore(),
    )

    await _promoted_run(runtime=runtime, body=TABLE_BODY)

    assert len(memory.stored) == 1
    ref = memory.stored[0].outcomes[0]["artifact_ref"]
    assert len(ref["content_hash"]) == 64
    assert ref["mime"] == "text/markdown"
    assert ref["size_bytes"] == len(TABLE_BODY.encode("utf-8"))
    assert ref["chars"] == len(TABLE_BODY)
    assert ref["name"].startswith("task-")
    assert ref["artifact_id"]

    # The bytes are really there, tagged as an agent artifact (AD-797 origin).
    assert await attachments.read(ref["content_hash"]) == TABLE_BODY.encode("utf-8")
    origins = {h for h, _ts in await attachments.list_by_origin("agent_artifact")}
    assert ref["content_hash"] in origins

    # And the version chain names it.
    latest = artifacts.latest(thread_id=THREAD, name=ref["name"])
    assert latest is not None
    assert latest.content_hash == ref["content_hash"]
    assert latest.created_by == AGENT


async def test_a_promoted_run_writes_nothing_extra_when_the_flag_is_off(
    tmp_path: Path,
) -> None:
    """OFF keeps the AD-1166 outcome verbatim: no ref key, the 500-char cap."""
    attachments, artifacts = _stores(tmp_path)
    memory = _CollectingEpisodicMemory()
    runtime = _runtime(
        refs_on=False, attachments=attachments, artifacts=artifacts,
        memory=memory, work_items=_FakeWorkItemStore(), threads=_FakeThreadStore(),
    )

    await _promoted_run(runtime=runtime, body=TABLE_BODY)

    outcome = memory.stored[0].outcomes[0]
    assert "artifact_ref" not in outcome
    assert outcome["response"] == TABLE_BODY[:500]
    assert await attachments.list_by_origin("agent_artifact") == []


async def test_a_failing_artifact_write_still_delivers_and_still_remembers(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Losing the artifact must never cost the Captain the report, nor the
    system the episode."""

    class _Boom(FilesystemAttachmentStore):
        async def write(self, *a: Any, **k: Any) -> Any:
            raise OSError("the disk is on fire")

    memory = _CollectingEpisodicMemory()
    threads = _FakeThreadStore()
    _attachments, artifacts = _stores(tmp_path)
    runtime = _runtime(
        refs_on=True,
        attachments=_Boom(tmp_path / "boom"),
        artifacts=artifacts,
        memory=memory,
        work_items=_FakeWorkItemStore(),
        threads=threads,
    )

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.turn_promotion"):
        await _promoted_run(runtime=runtime, body=TABLE_BODY)

    assert [m["body"] for m in threads.appended] == [TABLE_BODY]
    assert len(memory.stored) == 1
    assert "artifact_ref" not in memory.stored[0].outcomes[0]
    assert any("AD-1226" in r.message for r in caplog.records)


async def test_a_failing_version_registration_keeps_the_readable_ref(
    tmp_path: Path,
) -> None:
    """The attachment ref alone is enough to fetch by, so a broken artifact
    store must not cost the agent the ability to read its own work back."""

    class _BrokenArtifacts:
        def add_version(self, **_k: Any) -> Any:
            raise RuntimeError("artifact db locked")

    attachments, _artifacts = _stores(tmp_path)
    memory = _CollectingEpisodicMemory()
    runtime = _runtime(
        refs_on=True, attachments=attachments, artifacts=_BrokenArtifacts(),
        memory=memory, work_items=_FakeWorkItemStore(), threads=_FakeThreadStore(),
    )

    await _promoted_run(runtime=runtime, body=TABLE_BODY)

    ref = memory.stored[0].outcomes[0]["artifact_ref"]
    assert ref["artifact_id"] == ""
    assert await attachments.read(ref["content_hash"]) == TABLE_BODY.encode("utf-8")


def _ends_on_a_line_boundary(part: str, whole: str) -> bool:
    """Every line in ``part`` is a COMPLETE line of ``whole``."""
    return whole.startswith(part) and (
        len(part) == len(whole) or whole[len(part)] == "\n"
    )


def test_the_digest_cuts_on_a_line_boundary_not_mid_cell() -> None:
    """The measured defect was ``| charset-normalizer | 3.4.9 | The Real Fi``."""
    digest = _outcome_digest(TABLE_BODY)

    assert len(digest) <= _OUTCOME_DIGEST_CHARS
    assert _ends_on_a_line_boundary(digest, TABLE_BODY), repr(digest[-60:])
    # The old cap is what the measured defect looked like: a mid-cell cut.
    assert not _ends_on_a_line_boundary(TABLE_BODY[:500], TABLE_BODY), (
        "the fixture no longer reproduces the mid-cell cut it exists to pin"
    )


def test_a_short_report_is_kept_whole_by_the_digest() -> None:
    assert _outcome_digest("All done.") == "All done."


def test_a_single_long_line_still_respects_the_cap() -> None:
    """No line boundary inside the cap ⇒ a hard cut, never an unbounded copy."""
    body = "x" * 5000
    assert _outcome_digest(body) == "x" * _OUTCOME_DIGEST_CHARS


async def test_a_promoted_run_stores_a_digest_not_a_partial_copy(
    tmp_path: Path,
) -> None:
    attachments, artifacts = _stores(tmp_path)
    memory = _CollectingEpisodicMemory()
    runtime = _runtime(
        refs_on=True, attachments=attachments, artifacts=artifacts,
        memory=memory, work_items=_FakeWorkItemStore(), threads=_FakeThreadStore(),
    )

    await _promoted_run(runtime=runtime, body=TABLE_BODY)

    response = memory.stored[0].outcomes[0]["response"]
    assert len(response) <= _OUTCOME_DIGEST_CHARS
    assert response == _outcome_digest(TABLE_BODY)


# ── 5-6. the render ───────────────────────────────────────────────


def test_the_produced_line_appears_once_and_names_the_tool() -> None:
    runtime = _runtime(refs_on=True)

    lines = _memory_section(runtime, [_ref_memory()])

    produced = [ln for ln in lines if "you produced" in ln]
    assert len(produced) == 1, f"expected exactly one cue, got {produced}"
    line = produced[0]
    assert "task-70cd290af319" in line
    assert "1,362 chars" in line
    assert "recall_artifact" in line
    # The hash prefix is quoted so it can be copied straight into the call.
    assert '"7f3a9c2e2b1d"' in line
    # One extra line and no more.
    assert len(lines) == len(_today_section(runtime, [_ref_memory()])) + 1


def test_an_ordinary_memory_with_no_ref_renders_exactly_as_today() -> None:
    runtime = _runtime(refs_on=True)
    plain = {"input": "Captain asked about the dogs.", "reflection": "", "source": "direct"}

    assert _memory_section(runtime, [plain]) == _today_section(runtime, [plain])


def test_a_ref_that_stored_nothing_falls_back_to_the_digest_line() -> None:
    runtime = _runtime(refs_on=True)
    mem = _ref_memory()
    mem["outcome_ref"] = {"content_hash": "", "name": "task-x", "chars": 0}

    produced = [ln for ln in _memory_section(runtime, [mem]) if "you produced" in ln]

    assert len(produced) == 1
    assert "recall_artifact" not in produced[0]
    assert "Here are the top 15 PyPI packages" in produced[0]


def test_a_ref_that_stored_nothing_and_has_no_digest_renders_nothing() -> None:
    runtime = _runtime(refs_on=True)
    mem = _ref_memory()
    mem["outcome_ref"] = {"content_hash": ""}
    mem.pop("outcome_digest")

    assert _memory_section(runtime, [mem]) == _today_section(runtime, [mem])


def test_the_produced_line_does_not_trip_the_capability_gap_regex() -> None:
    """Agent-facing text matching _CAPABILITY_GAP_RE triggers self-modification."""
    from probos.cognitive.decomposer import is_capability_gap

    runtime = _runtime(refs_on=True)
    for mem in (_ref_memory(), {**_ref_memory(), "outcome_ref": {"content_hash": ""}}):
        for line in _memory_section(runtime, [mem]):
            assert not is_capability_gap(line), line


def test_the_outcome_cue_survives_malformed_outcomes() -> None:
    """``outcomes`` round-trips through JSON and may hold anything."""
    cue = CognitiveAgent._episode_outcome_cue
    assert cue(SimpleNamespace(outcomes=None)) == {}
    assert cue(SimpleNamespace(outcomes=[])) == {}
    assert cue(SimpleNamespace(outcomes=["not a dict", 7])) == {}
    assert cue(SimpleNamespace(outcomes=[{"response": "x"}])) == {}
    assert cue(SimpleNamespace(outcomes=[{"artifact_ref": "not a dict"}])) == {}
    assert cue(SimpleNamespace()) == {}


def test_the_outcome_cue_takes_the_first_outcome_carrying_a_ref() -> None:
    cue = CognitiveAgent._episode_outcome_cue(SimpleNamespace(outcomes=[
        {"response": "no ref here"},
        {"response": "second", "artifact_ref": {"content_hash": "aa"}},
        {"response": "third", "artifact_ref": {"content_hash": "bb"}},
    ]))

    assert cue == {
        "outcome_ref": {"content_hash": "aa"},
        "outcome_digest": "second",
    }


# ── 7-10. the tool ────────────────────────────────────────────────


async def _seed(tmp_path: Path, body: str, *, owner: str = AGENT) -> tuple[Any, str]:
    """Store ``body`` through a real promoted run; return (runtime, content_hash)."""
    attachments, artifacts = _stores(tmp_path)
    memory = _CollectingEpisodicMemory()
    runtime = _runtime(
        refs_on=True, attachments=attachments, artifacts=artifacts,
        memory=memory, work_items=_FakeWorkItemStore(), threads=_FakeThreadStore(),
    )
    release = asyncio.Event()
    hold: set = set()

    async def _work() -> str:
        await release.wait()
        return body

    await run_with_promotion(
        _work,
        promote_after_seconds=0.01,
        runtime=runtime,
        agent_id=owner,
        thread_id=THREAD,
        request_text="produce it",
        hold=hold,
        completed_probe=lambda: True,
    )
    release.set()
    await _drain(hold)
    return runtime, memory.stored[0].outcomes[0]["artifact_ref"]["content_hash"]


async def test_a_small_artifact_comes_back_whole(tmp_path: Path) -> None:
    runtime, content_hash = await _seed(tmp_path, TABLE_BODY)

    res = await RecallArtifactTool(runtime=runtime).invoke(
        {"ref": content_hash[:12]}, {"agent_id": AGENT, "thread_id": THREAD},
    )

    out = res.output
    assert res.error is None
    assert out["found"] is True
    assert out["text"] == TABLE_BODY
    assert out["total_chars"] == len(TABLE_BODY)
    assert out["offset"] == 0
    assert out["next_offset"] is None
    assert out["truncated"] is False
    assert out["mime"] == "text/markdown"


async def test_a_large_artifact_pages_with_no_gap_and_no_overlap(
    tmp_path: Path,
) -> None:
    """The Captain's book example: walk it all, never hold it all."""
    # No leading/trailing whitespace: BF-702 strips the delivered report, so a
    # padded fixture would compare against text the run never produced.
    body = "\n".join(f"line {i:05d} of a long document" for i in range(500))
    assert len(body) > _MAX_CHARS_PER_READ * 2
    runtime, content_hash = await _seed(tmp_path, body)
    tool = RecallArtifactTool(runtime=runtime)

    pages: list[str] = []
    offset: int | None = 0
    seen_offsets: list[int] = []
    while offset is not None:
        seen_offsets.append(offset)
        out = (await tool.invoke(
            {"ref": content_hash[:12], "offset": offset},
            {"agent_id": AGENT, "thread_id": THREAD},
        )).output
        assert out["found"] is True
        assert out["offset"] == offset
        assert len(out["text"]) <= _MAX_CHARS_PER_READ
        pages.append(out["text"])
        offset = out["next_offset"]

    assert len(pages) > 2, "the fixture must actually require paging"
    assert len(pages[0]) == _MAX_CHARS_PER_READ
    # Every page but the last was truncated, and continuation is contiguous.
    assert seen_offsets == [i * _MAX_CHARS_PER_READ for i in range(len(pages))]
    # THE assertion: concatenation reconstructs the original exactly.
    assert "".join(pages) == body


async def test_an_offset_past_the_end_returns_an_empty_final_page(
    tmp_path: Path,
) -> None:
    runtime, content_hash = await _seed(tmp_path, "short")

    out = (await RecallArtifactTool(runtime=runtime).invoke(
        {"ref": content_hash[:12], "offset": 9999},
        {"agent_id": AGENT, "thread_id": THREAD},
    )).output

    assert out["found"] is True
    assert out["text"] == ""
    assert out["truncated"] is False
    assert out["next_offset"] is None


async def test_a_malformed_offset_reads_from_the_beginning(tmp_path: Path) -> None:
    runtime, content_hash = await _seed(tmp_path, "hello there")

    for bad in ("banana", None, -5, [1]):
        out = (await RecallArtifactTool(runtime=runtime).invoke(
            {"ref": content_hash[:12], "offset": bad},
            {"agent_id": AGENT, "thread_id": THREAD},
        )).output
        assert out["offset"] == 0
        assert out["text"] == "hello there"


async def test_another_agents_artifact_is_not_readable(tmp_path: Path) -> None:
    """Reporting another crew member's output would leak one agent's work into
    another's context."""
    runtime, content_hash = await _seed(tmp_path, "the other agent's secret", owner=OTHER)

    res = await RecallArtifactTool(runtime=runtime).invoke(
        {"ref": content_hash}, {"agent_id": AGENT, "thread_id": THREAD},
    )

    assert res.output["found"] is False
    assert "secret" not in str(res.output)
    assert res.error is None


async def test_an_anonymous_caller_is_not_a_wildcard(tmp_path: Path) -> None:
    runtime, content_hash = await _seed(tmp_path, TABLE_BODY)

    res = await RecallArtifactTool(runtime=runtime).invoke(
        {"ref": content_hash}, {"agent_id": "", "thread_id": THREAD},
    )

    assert res.output["found"] is False
    assert res.error is None


async def test_an_unknown_hash_degrades_rather_than_erroring(tmp_path: Path) -> None:
    runtime, _hash = await _seed(tmp_path, TABLE_BODY)

    res = await RecallArtifactTool(runtime=runtime).invoke(
        {"ref": "0" * 64}, {"agent_id": AGENT, "thread_id": THREAD},
    )

    assert res.output["found"] is False
    assert res.error is None


async def test_a_ref_shorter_than_eight_characters_is_refused_not_guessed(
    tmp_path: Path,
) -> None:
    runtime, _hash = await _seed(tmp_path, TABLE_BODY)

    res = await RecallArtifactTool(runtime=runtime).invoke(
        {"ref": "abc"}, {"agent_id": AGENT, "thread_id": THREAD},
    )

    assert res.output["found"] is False
    assert "8 characters" in res.output["reason"]
    assert res.error is None


async def test_no_attachment_store_degrades_honestly() -> None:
    res = await RecallArtifactTool(runtime=_runtime(refs_on=True)).invoke(
        {"ref": "a" * 16}, {"agent_id": AGENT},
    )

    assert res.output["found"] is False
    assert res.error is None


async def test_a_missing_blob_is_reported_not_returned_as_empty_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """The record exists but the bytes are gone. An empty document would read as
    'you wrote nothing', which is a lie."""
    runtime, content_hash = await _seed(tmp_path, TABLE_BODY)

    class _Gone:
        async def read(self, _h: str) -> bytes:
            raise FileNotFoundError("blob swept")

    runtime.attachment_store = _Gone()

    with caplog.at_level(logging.WARNING, logger="probos.tools.recall_artifact_tool"):
        res = await RecallArtifactTool(runtime=runtime).invoke(
            {"ref": content_hash[:12]}, {"agent_id": AGENT, "thread_id": THREAD},
        )

    assert res.output["found"] is False
    assert res.output.get("text", "") == ""
    assert res.error is None
    assert any("AD-1226" in r.message for r in caplog.records)


async def test_a_raising_lookup_never_breaks_the_turn(tmp_path: Path) -> None:
    attachments, _artifacts = _stores(tmp_path)

    class _Boom:
        async def recent_for_agent(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("chroma is down")

    runtime = _runtime(refs_on=True, attachments=attachments, memory=_Boom())

    res = await RecallArtifactTool(runtime=runtime).invoke(
        {"ref": "a" * 16}, {"agent_id": AGENT},
    )

    assert res.output["found"] is False
    assert res.error is None


async def test_a_binary_artifact_is_described_rather_than_inlined(
    tmp_path: Path,
) -> None:
    """Returning mojibake would be worse than an honest refusal."""
    attachments, artifacts = _stores(tmp_path)
    blob = bytes(range(256))
    import hashlib

    content_hash = hashlib.sha256(blob).hexdigest()
    await attachments.write(content_hash, blob, "image/png", origin="agent_artifact")
    artifacts.add_version(
        thread_id=THREAD, name="render.png", content_hash=content_hash,
        mime="image/png", size_bytes=len(blob), created_by=AGENT,
    )
    runtime = _runtime(refs_on=True, attachments=attachments, artifacts=artifacts)

    out = (await RecallArtifactTool(runtime=runtime).invoke(
        {"ref": content_hash}, {"agent_id": AGENT, "thread_id": THREAD},
    )).output

    assert out["found"] is True
    assert out["readable_as_text"] is False
    assert out["text"] == ""
    assert out["mime"] == "image/png"
    assert out["size_bytes"] == len(blob)


async def test_an_artifact_resolves_by_name_within_the_thread(
    tmp_path: Path,
) -> None:
    runtime, content_hash = await _seed(tmp_path, TABLE_BODY)
    name = runtime.artifact_store.find_first_by_hash(content_hash).name

    out = (await RecallArtifactTool(runtime=runtime).invoke(
        {"ref": name}, {"agent_id": AGENT, "thread_id": THREAD},
    )).output

    assert out["found"] is True
    assert out["text"] == TABLE_BODY


def test_the_tool_declares_a_read_and_teaches_the_behaviour() -> None:
    tool = RecallArtifactTool(runtime=None)
    assert tool.tool_id == "recall_artifact"
    assert sorted(tool.input_schema["properties"]) == ["offset", "ref"]
    assert tool.input_schema["required"] == ["ref"]
    text = tool.description.lower()
    assert "read-only" in text
    assert "next_offset" in text
    assert "a second time" in text


def test_the_tool_description_does_not_trip_the_capability_gap_regex() -> None:
    from probos.cognitive.decomposer import is_capability_gap

    tool = RecallArtifactTool(runtime=None)
    assert not is_capability_gap(tool.description)
    assert not is_capability_gap(str(tool.input_schema))


async def test_the_tool_never_writes_anything(tmp_path: Path) -> None:
    """Read-only means read-only: the version chain must be untouched."""
    runtime, content_hash = await _seed(tmp_path, TABLE_BODY)
    name = runtime.artifact_store.find_first_by_hash(content_hash).name
    before = len(runtime.artifact_store.list_versions(thread_id=THREAD, name=name))

    await RecallArtifactTool(runtime=runtime).invoke(
        {"ref": content_hash[:12]}, {"agent_id": AGENT, "thread_id": THREAD},
    )

    assert len(
        runtime.artifact_store.list_versions(thread_id=THREAD, name=name)
    ) == before


# ── 11. THE CROSSING TEST ─────────────────────────────────────────


async def test_the_crossing_promoted_run_to_rendered_ref_to_original_text(
    tmp_path: Path,
) -> None:
    """Promoted run → episode stored → recall renders the cue → the tool is
    invoked with the ref taken FROM THAT RENDERED LINE → the original body.

    Nothing in the middle is stubbed: a real ``FilesystemAttachmentStore``, a
    real ``ArtifactStore``, a real ``EpisodicMemory``, the real
    ``_recall_relevant_memories`` recall path, the real
    ``_format_memory_section`` renderer and the real tool. The absence of
    exactly this test is why the defect shipped — every half worked and nothing
    traversed the chain.
    """
    attachments, artifacts = _stores(tmp_path)
    memory = EpisodicMemory(db_path=str(tmp_path / "episodes.db"))
    await memory.start()
    try:
        runtime = SimpleNamespace(
            config=_config(refs_on=True),
            attachment_store=attachments,
            artifact_store=artifacts,
            episodic_memory=memory,
            work_item_store=_FakeWorkItemStore(),
            chat_thread_store=_FakeThreadStore(),
            ontology=None,
            registry=None,
        )

        # 1. A promoted run produces the report and delivers it.
        await _promoted_run(runtime=runtime, body=TABLE_BODY)

        # 2. Recall assembles the memory section through the REAL recall path.
        agent = _agent(runtime)
        intent = IntentMessage(
            intent="direct_message",
            params={"text": "what were the top 15 PyPI packages you sent me?"},
            target_agent_id=AGENT,
        )
        observation = {"intent": "direct_message", "params": intent.params}
        with patch("probos.crew_utils.is_crew_agent", return_value=True):
            observation = await agent._recall_relevant_memories(intent, observation)

        memories = observation.get("recent_memories") or []
        assert memories, "the promoted episode never came back from recall"
        lines = agent._format_memory_section(memories)

        # 3. The cue is in the rendered prompt.
        produced = [ln for ln in lines if "you produced" in ln]
        assert produced, (
            "the produced cue never reached the prompt:\n" + "\n".join(lines)
        )
        assert f"{len(TABLE_BODY):,} chars" in produced[0]

        # 4. Take the ref out of the RENDERED LINE, exactly as the agent would.
        quoted = re.search(r'recall_artifact\("([0-9a-f]+)"\)', produced[0])
        assert quoted is not None, f"no callable ref in the cue: {produced[0]}"
        ref_from_prompt = quoted.group(1)

        # 5. The tool returns the original body.
        res = await RecallArtifactTool(runtime=runtime).invoke(
            {"ref": ref_from_prompt}, {"agent_id": AGENT, "thread_id": THREAD},
        )

        assert res.error is None
        assert res.output["found"] is True
        assert res.output["text"] == TABLE_BODY, (
            "the round trip did not return the original report"
        )
        assert res.output["total_chars"] == len(TABLE_BODY)
    finally:
        try:
            await memory.stop()
        except Exception:
            pass
