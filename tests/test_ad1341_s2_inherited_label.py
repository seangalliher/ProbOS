"""AD-1341 S2 (#1569): a later crew reads the Ship's Archive as inherited knowledge, never as its own memory.

The real ``ArchiveStore`` on a temporary file (BF-919 keeps every test archive under the suite's temporary roots),
the real ``OracleService``, and the real renderers through which an Oracle result reaches an agent:
``query_formatted`` (the ORACLE recall tier and the ``oracle_lookup`` sub-task), the AD-1139 ``oracle_query`` tool,
AD-462f memory refs, the AD-1141 crew consult and the AD-725 DM lookup. The seam test runs the real ``probos reset``
twice, with S1's helpers. Amendment A2 adds the consumers after the renderers: AD-1148's bound of a tool result,
through the real tool, executor and loop; AD-547's compaction; and AD-688's graph expansion on the real edge store.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import probos
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.crew_executor import _render_commons_block
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.dm_targeted_lookup import LookupDispatcher
from probos.cognitive.oracle_service import OracleService, _extract_entity_tokens
from probos.cognitive.swe_harness.agentic_loop import (
    _ELISION_MARKER,
    AgenticLoop,
    resolve_tool_result_bounds,
    truncate_tool_output,
)
from probos.cognitive.swe_harness.session_compactor import SessionCompactor
from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolCallResult, ToolUseBlock
from probos.config import AgenticLoopConfig
from probos.knowledge.archive_store import (
    ARCHIVE_ORIGIN_NOTICE,
    LABEL_EARLIER_CREW,
    LABEL_THIS_CREW,
    ArchiveEntry,
    ArchiveStore,
    GenerationOutcome,
    GenerationRecord,
    PromotionRecord,
    SourceKind,
    holds_archive_label,
    inheritance_label,
)
from probos.knowledge.edges import (
    KnowledgeEdge,
    KnowledgeEntityType,
    KnowledgeRelationType,
    SQLiteKnowledgeEdgeStore,
)
from probos.ontology.service import VesselOntologyService
from probos.startup.communication import _register_oracle_query_tool
from probos.storage.sqlite_factory import default_factory
from probos.tools.executor import ToolExecutor
from probos.tools.oracle_query_tool import OracleQueryTool
from probos.tools.registry import ToolRegistry
from probos.types import LLMResponse
from tests.test_ad1341_s1_archive_store import _plant_v0
from tests.test_ad1341_s1_reset_and_erase import _SHIP, _config, _data_dir, _records, _reset, _write_records

_SRC = Path(probos.__file__).resolve().parent
_REPO = _SRC.parents[1]
_MARKER_END = _ELISION_MARKER.split("{omitted}", 1)[1]  # AD-1148's elision marker after its count
_BODY = "Three officers independently traced the coolant drift."
_SECOND = "ship-did-second-0002"
_THIRD = "ship-did-third-0003"
_SECOND_REPORT = "reports/convergence/convergence-20261023-000000.md"
_HEADER = re.compile(r"\[(?:convergence_report|published_report|captains_log|notebook_finding)\] ")
_LABEL_ENDS = ("not your own memory]", "a record, not a memory]")

# Closes in id order: a skip with no instance id, a skip whose instance id is only a tab and line breaks (A2: blank
# by ``str.strip``, not by SQLite's ``trim``), alpha, beta (skipped), alpha again, gamma. t-open has no close.
_TIMELINES = ("t-alpha", "t-beta", "t-gamma", "t-open")
_EXPECTED = {"t-alpha": 1, "t-beta": 2, "t-gamma": 3, "t-open": None}


def _generation_label(generation: int) -> str:
    return f"[Inherited from the crew of generation {generation}: not your own memory]"


def _store(tmp_path: Path) -> ArchiveStore:
    return ArchiveStore(str(tmp_path / "archive.db"), connection_factory=default_factory)


def _new_oracle(store: Any, **collaborators: Any) -> OracleService:
    return OracleService(archive_store=store, **collaborators)


def _oracle(store: Any, current_timeline: str = "", **collaborators: Any) -> OracleService:
    oracle = _new_oracle(store, **collaborators)
    oracle.attach_current_timeline(current_timeline)
    return oracle


def _content(timeline: str) -> str:
    """Long enough that every renderer's cap cuts it."""
    return f"{_BODY} ({timeline}) " + "Detail. " * 300


def _record(timeline: str, content: str = "") -> PromotionRecord:
    fields: dict[str, Any] = {
        "timeline_id": timeline, "source_kind": SourceKind.CONVERGENCE_REPORT,
        "source_ref": f"reports/convergence/{timeline}.md", "title": timeline,
        "content": content or _content(timeline),
        "classification": "ship", "author_callsign": "system",
    }
    return PromotionRecord(**fields)


def _closed(timeline: str, *, skipped: bool = False) -> GenerationRecord:
    fields: dict[str, Any] = {"timeline_id": timeline, "reset_tier": 2}
    if skipped:
        fields.update(outcome=GenerationOutcome.SKIPPED, reason="Captain: a recorded skip")
    else:
        fields.update(outcome=GenerationOutcome.PROMOTED, created=1)
    return GenerationRecord(**fields)


def _entry(timeline: str, generation: Any) -> ArchiveEntry:
    fields: dict[str, Any] = {
        "id": 7, "timeline_id": timeline, "category": "convergence_report", "title": "t", "content": _BODY,
        "author_agent_type": "", "author_callsign": "system", "archived_at": 1.0, "generation": generation,
    }
    return ArchiveEntry(**fields)


async def _plant(store: ArchiveStore, timelines: tuple[str, ...] = _TIMELINES) -> None:
    for closure in (
        _closed("", skipped=True), _closed("\t\r\n", skipped=True), _closed("t-alpha"),
        _closed("t-beta", skipped=True), _closed("t-alpha"), _closed("t-gamma"),
    ):
        await store.record_generation(closure)
    for timeline in timelines:
        await store.promote_entry(_record(timeline))


def _every_entry_is_labelled_first(text: str) -> int:
    """Each archive entry's header (``[<kind>] <title>``) is preceded by an inheritance label, with only whitespace,
    or a ``repr``'s escaped newline, between them. Returns how many headers it checked."""
    checked = 0
    for header in _HEADER.finditer(text):
        before = text[: header.start()].rstrip().removesuffix("\\n").rstrip()
        assert before.endswith(_LABEL_ENDS), text[max(0, header.start() - 160): header.start() + 40]
        checked += 1
    return checked


# --- T1, T2: the store numbers the crews (D3) -----------------------------------------------------------------


async def test_each_entry_carries_its_crews_generation_from_every_read(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store)
        searched = await store.search("coolant drift")
        recent = await store.get_recent()
        by_id = [await store.entry_by_id(entry.id) for entry in recent]
    finally:
        await store.close()
    for read in (searched, recent, by_id):
        assert {entry.timeline_id: entry.generation for entry in read} == _EXPECTED
    assert sorted(entry.content for entry in recent) == sorted(_content(t) for t in _TIMELINES)  # unlabelled


@pytest.mark.parametrize("v0", [False, True], ids=["empty-generations", "v0-row"])
async def test_an_entry_whose_crew_has_no_recorded_close_has_no_generation(tmp_path: Path, v0: bool) -> None:
    if v0:
        _plant_v0(tmp_path / "archive.db")  # AD-524's two rows, timeline "timeline-zero", never closed
    store = _store(tmp_path)
    await store.initialize()
    try:
        if v0:
            await store.record_generation(_closed("t-alpha"))
            entries = await store.search("Legacy")
        else:
            await store.promote_entry(_record("t-alpha"))
            entries = await store.search("coolant drift")
    finally:
        await store.close()
    assert entries, "premise: the read returns the entry"
    assert all(entry.generation is None for entry in entries)
    assert {inheritance_label(entry, current_timeline="t-now") for entry in entries} == {LABEL_EARLIER_CREW}


# --- T3, T3b: the rule (D4, D5) -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("timeline", "generation", "current", "expected"),
    [
        ("t-alpha", 3, "t-now", _generation_label(3)),
        ("t-alpha", 1, "", _generation_label(1)),
        ("t-alpha", None, "t-now", LABEL_EARLIER_CREW),
        ("t-alpha", 0, "t-now", LABEL_EARLIER_CREW),
        ("t-alpha", True, "t-now", LABEL_EARLIER_CREW),
        ("t-alpha", "2", "t-now", LABEL_EARLIER_CREW),
        ("t-now", 2, "t-now", LABEL_THIS_CREW),
        ("t-now", None, "t-now", LABEL_THIS_CREW),
        ("", None, "", LABEL_EARLIER_CREW),
    ],
    ids=["generation", "no-current", "unrecorded", "zero", "bool", "str", "this-crew-closed", "this-crew-open",
         "both-empty"],
)
def test_the_label_says_where_an_entry_came_from(timeline: str, generation: Any, current: str, expected: str) -> None:
    label = inheritance_label(_entry(timeline, generation), current_timeline=current)
    assert label == expected
    assert label.startswith("[") and label.endswith(_LABEL_ENDS)


def test_the_fixed_labels_read_as_decided() -> None:
    assert LABEL_THIS_CREW == "[Archived by this crew: a record, not a memory]"
    assert LABEL_EARLIER_CREW == "[Inherited from an earlier crew: not your own memory]"


# --- T4, T5, T5b: the one attachment point (D2, D5) -----------------------------------------------------------


async def test_the_oracle_puts_the_label_first_in_each_archive_result(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store)
        results = await _oracle(store, "t-now").query("coolant drift", tiers=["archive"])
    finally:
        await store.close()
    assert sorted(result.metadata["timeline_id"] for result in results) == sorted(_TIMELINES)
    for result in results:
        timeline = result.metadata["timeline_id"]
        generation = _EXPECTED[timeline]
        label = _generation_label(generation) if generation else LABEL_EARLIER_CREW
        assert result.content.split("\n", 1)[0] == label
        assert result.content == f"{label}\n[convergence_report] {timeline}\n{_content(timeline)}"
        assert (result.source_tier, result.metadata["generation"], result.metadata["inherited"]) == (
            "archive", generation, True,
        )
        assert result.provenance == f"Archive/convergence_report (timeline {timeline[:8]}...)"


async def test_an_entry_this_crew_archived_is_its_own_record_never_inherited(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store)
        attached = await _oracle(store, "t-alpha\n").query("coolant drift", tiers=["archive"])
        unattached = await _new_oracle(store).query("coolant drift", tiers=["archive"])
    finally:
        await store.close()
    labels = {r.metadata["timeline_id"]: (r.content.split("\n", 1)[0], r.metadata["inherited"]) for r in attached}
    assert labels == {
        "t-alpha": (LABEL_THIS_CREW, False),
        "t-beta": (_generation_label(2), True),
        "t-gamma": (_generation_label(3), True),
        "t-open": (LABEL_EARLIER_CREW, True),
    }
    # Until the runtime attaches the timeline nothing reads as this crew's own: the safe direction (D5).
    assert all(result.metadata["inherited"] is True for result in unattached)
    assert LABEL_THIS_CREW not in "".join(result.content for result in unattached)


@pytest.mark.parametrize("value", [None, 7, b"t-alpha"], ids=["none", "int", "bytes"])
def test_the_oracle_takes_its_timeline_only_as_text(value: Any) -> None:
    oracle = _new_oracle(None)
    with pytest.raises(TypeError):
        oracle.attach_current_timeline(value)


# --- T6, T7: every renderer an agent reads (§5) ---------------------------------------------------------------


async def _agent_text(oracle: OracleService, path: str, query: str) -> str:
    """The text an agent receives from the Oracle through ``path``, by the renderer that path uses."""
    if path == "query-formatted":  # the ORACLE recall tier and the oracle_lookup sub-task
        return await oracle.query_formatted(query, k_per_tier=3, max_chars=2000)
    if path == "oracle-tool":  # AD-1139
        return (await OracleQueryTool(oracle=oracle).invoke({"query": query, "kind": "archive"})).output
    if path == "memory-refs":  # AD-462f, the oracle_refs sub-task
        return OracleService.format_refs(await oracle.query_refs(query, k_per_tier=3))
    if path == "crew-consult":  # AD-1141
        consult = await oracle.query(query, k_per_tier=3, tiers=["archive"])
        return _render_commons_block(consult, max_chars=4000, max_entries=5, min_score=0.0)
    return LookupDispatcher._stringify(await oracle.query(query))  # AD-725: every tier, stringified


@pytest.mark.parametrize("path", ["query-formatted", "oracle-tool", "memory-refs", "crew-consult", "dm-lookup"])
async def test_every_path_from_the_archive_to_an_agent_carries_the_label_before_the_content(
    tmp_path: Path, path: str,
) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store, ("t-alpha", "t-beta", "t-open"))
        text = await _agent_text(_oracle(store, "t-now"), path, "coolant drift")
    finally:
        await store.close()
    assert _every_entry_is_labelled_first(text) == 3
    for label in (_generation_label(1), _generation_label(2), LABEL_EARLIER_CREW):
        assert label in text


class _FarArchive:
    """An archive whose one entry has SQLite's largest rowid and a generation the test chooses: the widest prefix."""

    def __init__(self, generation: int) -> None:
        self.generation = generation

    async def search(self, query: str, *, limit: int = 10) -> list[ArchiveEntry]:
        fields: dict[str, Any] = {
            "id": 2**63 - 1, "timeline_id": "t-far", "category": "convergence_report", "title": "x" * 200,
            "content": "y" * 2000, "author_agent_type": "", "author_callsign": "system",
            "archived_at": time.time(), "generation": self.generation,
        }
        return [ArchiveEntry(**fields)][:limit]


@pytest.mark.parametrize(
    ("generation", "survives"),
    [(10**6 - 1, _generation_label(10**6 - 1)), (10**6, "generation 1000000: not your own memory")],
    ids=["whole-label", "warning-words"],
)
async def test_the_label_survives_the_tightest_cap_any_consumer_applies(generation: int, survives: str) -> None:
    """``format_refs`` keeps 119 characters of a line; prefix and label take 94 plus the digits of the id and of the
    generation. Up to 25 digits the whole label survives; past that the warning words do (RS2-7)."""
    refs_text = OracleService.format_refs(await _oracle(_FarArchive(generation), "t-now").query_refs("anything"))
    assert f"[archive] archive:{2**63 - 1} (score: 0.99) " in refs_text  # premise: the widest prefix
    assert survives in refs_text


# --- T8: the real seam: two resets, then a later crew's Oracle and the text it hands an agent ------------------


async def _publish_second_finding(data_dir: Path) -> None:
    await _records(data_dir).write_entry(
        author="system", path=_SECOND_REPORT,
        content="## Convergence Report\n\nThe second watch traced the coolant drift to a cracked manifold.",
        message="AD-551: Convergence report (manifold)", classification="ship", tags=["convergence", "ad-551"],
    )


async def _third_crew_reads(tmp_path: Path, query: str) -> tuple[list[Any], str, str]:
    later = _store(tmp_path)  # the third crew's boot opens the archive the resets wrote
    await later.initialize()
    try:
        oracle = _oracle(later, _THIRD)
        results = await oracle.query(query, tiers=["archive"])
        tool = await _agent_text(oracle, "oracle-tool", query)
        formatted = await _agent_text(oracle, "query-formatted", query)
    finally:
        await later.close()
    return results, tool, formatted


@pytest.mark.parametrize("full", [False, True], ids=["default", "full"])
def test_after_two_resets_a_later_crew_reads_each_generations_knowledge_labelled_as_inherited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, full: bool,
) -> None:
    data_dir = _data_dir(tmp_path)  # the first crew, under _SHIP
    asyncio.run(_write_records(data_dir))
    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=full) == 0

    # The second crew boots under a new instance id, as the ontology loader writes it, and publishes a finding.
    (data_dir / "ontology").mkdir(parents=True, exist_ok=True)
    (data_dir / "ontology" / "instance_id").write_text(_SECOND, encoding="utf-8")
    asyncio.run(_publish_second_finding(data_dir))
    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=full) == 0

    results, tool, formatted = asyncio.run(_third_crew_reads(tmp_path, "coolant drift"))
    generations = {(result.metadata["timeline_id"], result.metadata["generation"]) for result in results}
    assert generations == {(_SHIP, 1), (_SECOND, 2)}
    for result in results:
        assert result.source_tier == "archive"
        assert result.content.split("\n", 1)[0] == _generation_label(result.metadata["generation"])
        assert result.metadata["inherited"] is True
    for text in (tool, formatted):
        assert _every_entry_is_labelled_first(text) == len(results)
        assert _generation_label(1) in text and _generation_label(2) in text
        assert LABEL_THIS_CREW not in text
    assert "cracked manifold" in tool  # premise: the second crew's finding reached the third crew


# --- T9: the runtime is the one caller ------------------------------------------------------------------------


def test_only_the_runtime_tells_the_oracle_its_timeline_and_it_reads_the_ontologys_instance_id() -> None:
    calls: list[tuple[str, str]] = []
    for path in sorted(_SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "attach_current_timeline"
            ):
                calls.append((path.relative_to(_SRC).as_posix(), ast.unparse(node)))
    assert calls == [(
        "runtime.py",
        "self._oracle_service.attach_current_timeline(self.ontology.get_vessel_identity().instance_id)",
    )]


# --- T10: the timeline a boot attaches is the one the reset closes (D5's premise, A2) --------------------------


async def _booted_instance_id(data_dir: Path) -> str:
    """The instance id a boot's real ontology loads: what the runtime attaches (T9 pins the expression)."""
    ontology = VesselOntologyService(_REPO / "config" / "ontology", data_dir=data_dir)
    await ontology.initialize()
    return ontology.get_vessel_identity().instance_id


async def _archived(tmp_path: Path) -> list[ArchiveEntry]:
    store = _store(tmp_path)
    await store.initialize()
    try:
        return await store.get_recent()
    finally:
        await store.close()


def test_the_timeline_a_boot_attaches_is_the_one_the_reset_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path)
    booted = asyncio.run(_booted_instance_id(data_dir))
    asyncio.run(_write_records(data_dir))
    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 0
    entries = asyncio.run(_archived(tmp_path))
    assert entries, "premise: the reset archived the crew's records"
    assert {(entry.timeline_id, entry.generation) for entry in entries} == {(booted, 1)}
    assert asyncio.run(_booted_instance_id(data_dir)) not in ("", booted)  # the next crew is a new timeline


# --- T11, T12: AD-1148's bound of a tool result keeps the archive origin before what it kept (A2) --------------


def _origin_of_what_was_kept(bounded: str) -> None:
    """AD-1148 kept a head and a tail of a labelled tool result: every entry header in the head follows its label,
    and the tail, which may begin inside an entry, opens with the archive origin notice."""
    head, cut, tail = bounded.partition(_MARKER_END)
    assert cut, "premise: the cap elided the middle"
    assert "Detail." in tail, "premise: archived text crosses the cut"
    _every_entry_is_labelled_first(head)
    assert tail.startswith(f"{ARCHIVE_ORIGIN_NOTICE}\n"), tail[:200]


@pytest.mark.parametrize("cap", [1000, 2000, 3000])
async def test_an_elided_tool_result_introduces_what_it_kept_after_the_cut_with_the_archive_origin(
    tmp_path: Path, cap: int,
) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store, ("t-alpha", "t-beta", "t-open"))
        text = await _agent_text(_oracle(store, "t-now"), "oracle-tool", "coolant drift")
    finally:
        await store.close()
    bounded = truncate_tool_output(text, max_chars=cap, head_chars=4000, tail_chars=2000)
    assert len(text) > cap >= len(bounded)  # premise: the cap elides; the notice stays inside it
    _origin_of_what_was_kept(bounded)
    # Text that holds no label is bounded as AD-1148 bounds it, with no notice.
    plain = text.replace("[Inherited from ", "[Received from ")
    assert ARCHIVE_ORIGIN_NOTICE not in truncate_tool_output(plain, max_chars=cap, head_chars=4000, tail_chars=2000)


class _ScriptedModel:
    """Asks for one ``oracle_query`` call, then finishes; records every request the loop sends."""

    def __init__(self, call: ToolCallRequest) -> None:
        self.call = call
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_: Any) -> LLMResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return LLMResponse(content="", content_blocks=[ToolUseBlock(tool_call=self.call)], tokens_used=1)
        return LLMResponse(content="finished", content_blocks=[TextBlock(text="finished")], tokens_used=1)


@pytest.mark.parametrize("structured", [False, True], ids=["flattened", "structured"])
async def test_a_bounded_archive_tool_result_reaches_the_next_model_request_with_its_origin(
    tmp_path: Path, structured: bool,
) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store, ("t-alpha", "t-beta", "t-open"))
        oracle = _oracle(store, "t-now")
        registry = ToolRegistry()
        _register_oracle_query_tool(tool_registry=registry, enabled=True, oracle=oracle)
        tool = OracleQueryTool(oracle=oracle)
        model = _ScriptedModel(ToolCallRequest(
            name=tool.tool_id, arguments={"query": "coolant drift", "kind": "archive"}, id="archive-call",
        ))
        bounds = resolve_tool_result_bounds(
            AgenticLoopConfig(tool_result_max_chars=2000, structured_tool_messages=structured),
        )
        loop = AgenticLoop(
            llm_client=model, tool_executor=ToolExecutor(registry=registry), max_iterations=2,
            structured_tool_messages=structured, **bounds,
        )
        result = await loop.run(
            system_prompt="Complete the task.", user_message="Read the archived finding.",
            tools=[{"type": "function", "function": {
                "name": tool.tool_id, "description": tool.description, "parameters": tool.input_schema,
            }}],
            context={"agent_id": "archive-reader", "department": "science", "rank": "ensign"},
        )
    finally:
        await store.close()
    assert [r.is_error for r in result.tool_results] == [False]  # premise: the registered tool ran
    assert len(model.requests) == 2
    request = model.requests[1]
    seen = (
        next(m["content"] for m in request.messages if m.get("role") == "tool") if structured else request.prompt
    )
    _origin_of_what_was_kept(seen)


# --- T13: AD-547's summary opens with the archive origin when it summarised archive text (A2) ------------------


class _Summarizer:
    """A fast-tier model whose summary keeps the finding and names no source, as a concise summary may."""

    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def complete(self, request: Any) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content="The key finding is the cracked manifold.", tokens_used=12)


@pytest.mark.parametrize("source", ["label", "earlier-notice", "none"])
async def test_a_compaction_summary_opens_with_the_archive_origin_when_it_summarised_archive_text(
    source: str,
) -> None:
    earlier = {
        "label": f"{_generation_label(1)}\n[convergence_report] t-alpha\n{_BODY}",
        "earlier-notice": f"[CONTEXT SUMMARY — earlier exchanges]\n{ARCHIVE_ORIGIN_NOTICE}\nThe drift was traced.",
        "none": "Three officers discussed the duty roster.",
    }[source]
    messages = [
        {"role": "system", "content": "Complete the task."},
        {"role": "user", "content": "Review the earlier finding."},
        {"role": "user", "content": earlier},
        *({"role": "assistant" if n % 2 else "user", "content": f"Step {n}."} for n in range(8)),
    ]
    summarizer = _Summarizer()
    compacted = await SessionCompactor().compact(messages, fast_llm=summarizer)
    assert len(summarizer.requests) == 1 and earlier in summarizer.requests[0].prompt  # premise: it was summarised
    summaries = [m["content"] for m in compacted if m["content"].startswith("[CONTEXT SUMMARY")]
    notice = f"{ARCHIVE_ORIGIN_NOTICE}\n" if source != "none" else ""
    assert summaries == [f"[CONTEXT SUMMARY — earlier exchanges]\n{notice}The key finding is the cracked manifold."]


# --- T14: what counts as archive text (A2) --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "holds"),
    [
        (f"quoted {_generation_label(4)} here", True),
        (f"quoted {LABEL_EARLIER_CREW} here", True),
        (f"quoted {LABEL_THIS_CREW} here", True),
        (f"quoted {ARCHIVE_ORIGIN_NOTICE} here", True),
        ("Three officers traced the coolant drift.", False),
        ("Inherited from the crew of generation 4, with no bracket.", False),
    ],
    ids=["generation", "earlier-crew", "this-crew", "notice", "plain", "unbracketed"],
)
def test_archive_text_is_recognised_by_any_label_or_the_notice(text: str, holds: bool) -> None:
    assert holds_archive_label(text) is holds
    # AD-1148 DD-3 and AD-1142 DD-11: a model-facing marker must never read as a capability gap.
    assert _CAPABILITY_GAP_RE.search(ARCHIVE_ORIGIN_NOTICE) is None


# --- T15: AD-688's graph expansion reads an archive entry without its label (A2) -------------------------------


class _RecordingGraph:
    """The real edge store; records each token AD-688's expansion looks up."""

    def __init__(self, graph: SQLiteKnowledgeEdgeStore) -> None:
        self.graph = graph
        self.tokens: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.graph, name)

    async def find_edges(self, **kwargs: Any) -> list[Any]:
        self.tokens.append(kwargs["source_id"])
        return await self.graph.find_edges(**kwargs)


async def test_graph_expansion_reads_an_archive_entry_without_its_label(tmp_path: Path) -> None:
    short = "The coolant actuator drifted under load."
    graph = SQLiteKnowledgeEdgeStore(str(tmp_path / "edges.db"), connection_factory=default_factory)
    await graph.start()
    store = _store(tmp_path)
    await store.initialize()
    try:
        for source, edge_id in (("actuator", "content-edge"), ("crew", "label-edge")):
            await graph.add_edge(KnowledgeEdge(
                source_type=KnowledgeEntityType.CAPABILITY, source_id=source,
                relation=KnowledgeRelationType.DEPENDS_ON, target_type=KnowledgeEntityType.FINDING,
                target_id=f"{source}-detail", id=edge_id, created_at=1, updated_at=1,
            ))
        await store.record_generation(_closed("t-alpha"))
        await store.promote_entry(_record("t-alpha", short))
        recording = _RecordingGraph(graph)
        results = await _oracle(store, "t-now", knowledge_graph=recording).query("actuator", tiers=["archive"])
    finally:
        await store.close()
        await graph.stop()
    labels = [r.content.split("\n", 1)[0] for r in results if r.source_tier == "archive"]
    assert labels == [_generation_label(1)]  # premise: the parent carries its label
    assert recording.tokens == _extract_entity_tokens(f"[convergence_report] t-alpha\n{short}")
    expanded = [(r.metadata["edge_id"], r.metadata["matched_token"]) for r in results if r.source_tier == "graph"]
    assert expanded == [("content-edge", "actuator")]


# --- T16: the AD-1151 durable trace keeps all the model saw of an archive tool result (A3) -----------------------


def _kept(bounded: str) -> tuple[str, str]:
    """The head AD-1148 kept before its elision marker, and what follows the marker: the notice, then the tail."""
    head = bounded.split(_ELISION_MARKER.split("{omitted}", 1)[0], 1)[0]
    return head, bounded.partition(_MARKER_END)[2]


@pytest.mark.parametrize(
    ("context_cap", "trace_cap"),
    [
        (401, 401), (402, 402), (1000, 1000), (1001, 1001), (1999, 1999),
        (2000, 2000), (2000, 1000), (2001, 2001), (2999, 2999), (3000, 3000),
    ],
    ids=["401", "402", "1000", "1001", "1999", "2000", "2000-raised-from-1000", "2001", "2999", "3000"],
)
async def test_the_durable_trace_keeps_every_character_the_model_saw_of_an_archive_tool_result(
    tmp_path: Path, context_cap: int, trace_cap: int,
) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store, ("t-alpha", "t-beta", "t-open"))
        text = await _agent_text(_oracle(store, "t-now"), "oracle-tool", "coolant drift")
    finally:
        await store.close()
    cfg = AgenticLoopConfig(tool_result_max_chars=context_cap, tool_trace_output_max_chars=trace_cap)
    bounds = resolve_tool_result_bounds(cfg)
    # What the loop's message boundary hands the model (`_bound_tool_output`; T12 runs it through the real loop).
    seen = truncate_tool_output(
        text,
        max_chars=bounds["tool_result_max_chars"],
        head_chars=bounds["tool_result_head_chars"],
        tail_chars=bounds["tool_result_tail_chars"],
    )
    attachments = FilesystemAttachmentStore(tmp_path / "attachments")
    try:
        ref = await WorkItemAgenticExecutor(llm_client=None)._persist_tool_trace(
            SimpleNamespace(
                tool_calls=[ToolCallRequest(name="oracle_query", id="archive-call", timestamp=1.0)],
                tool_results=[ToolCallResult(id="archive-call", output=text)],
            ),
            SimpleNamespace(config=SimpleNamespace(agentic_loop=cfg), attachment_store=attachments),
            "archive-reader",
        )
        assert ref is not None, "premise: the real trace writer persisted the trace"
        (entry,) = json.loads(await attachments.read(ref))
    finally:
        attachments.close()
    # premise: a labelled result that both bounds elide (the resolver raises a durable cap below the context cap)
    assert holds_archive_label(text) and len(text) > context_cap and entry["output_truncated"] is True
    notice = f"{ARCHIVE_ORIGIN_NOTICE}\n"
    seen_head, seen_rest = _kept(seen)
    kept_head, kept_rest = _kept(entry["output"])
    # AD-1151: the durable trace is never bounded tighter than what the model saw.
    assert kept_head.startswith(seen_head), (len(seen_head), len(kept_head))
    assert seen_rest.startswith(notice) and kept_rest.startswith(notice)
    assert kept_rest.endswith(seen_rest.removeprefix(notice))
