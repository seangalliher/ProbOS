"""AD-1227 (BF-739 / #1198): an agent knows what it has made, without asking
its memory.

AD-1226 shipped correctly. Verified live on the reference vessel 2026-08-09,
work item ``712ebc8d645f``: the episode carried a well-formed ``artifact_ref``,
the bytes were in the attachment store under ``origin="agent_artifact"``, the
``ArtifactStore`` row existed. Every write worked — and the agent still told the
Captain it could not see what it had sent.

The ref-bearing episode never reached the prompt. Measured against the live
store with the real ``recall_for_agent`` at ``k=10``, the question that actually
failed returned two episodes and neither was the one holding the ref; rank 1 was
the agent's own earlier denial. A wrong answer, once given, is stored and
preferentially recalled for the question that produced it.

So this AD stops asking. "What have I produced recently?" is not a similarity
question: the artifact register already knows the answer exactly, and reading it
directly cannot be outranked by a self-replenishing population of competitors.

Two tests carry the weight:

* ``test_the_register_renders_with_no_episodic_memory_at_all`` — the whole point
  of the AD. BF-739 happened because the only route to this information ran
  through semantic recall; a test that would still pass if that dependency were
  quietly reintroduced is worthless.
* ``test_the_crossing_promoted_run_to_rendered_register_to_original_text`` — a
  real promoted run, a real ``FilesystemAttachmentStore``, a real
  ``ArtifactStore``, the real renderer and the real tool, with the hash taken
  OUT OF THE RENDERED LINE. This is the mechanical equivalent of the Captain's
  live test.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.artifacts import ArtifactStore
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.cognitive_agent import (
    _PRODUCED_HASH_CHARS,
    _RECENT_OUTPUTS_LIMIT,
    _format_recent_outputs,
)
from probos.cognitive.turn_promotion import run_with_promotion
from probos.config import SystemConfig
from probos.tools.recall_artifact_tool import RecallArtifactTool
from probos.workforce import WorkItem
from tests.fixtures.ad1028_golden._capture_golden import (
    dm_observation,
    make_dm_agent,
)

AGENT = "counselor_counselor_0_67c601cb"
OTHER = "yeoman_yeoman_0_xyz"
THREAD = "thread-1"
OTHER_THREAD = "thread-2"

REPORT_BODY = (
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


class _Clock:
    """Monotonic test clock so ``created_at`` ordering is deterministic."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


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


class _EpisodeLog:
    """A plain list of episodes. Not ``EpisodicMemory``: no embeddings, no
    similarity, no ranking, no ChromaDB — ``recent_for_agent`` returns what was
    stored, newest first.

    ``_store_promoted_episode`` returns early when ``runtime.episodic_memory``
    is None, so a crossing test that drives the REAL promotion path needs
    something here. This is the smallest honest something, and it counts every
    recall so the crossing test can assert the register consulted it zero times
    before rendering.
    """

    def __init__(self) -> None:
        self.stored: list[Any] = []
        self.recall_calls = 0

    async def store(self, episode: Any, **_kwargs: Any) -> None:
        import dataclasses
        import json

        # Round-trip ``outcomes`` through JSON exactly as ChromaDB storage
        # does, so a ref that is not JSON-serialisable fails here.
        self.stored.append(dataclasses.replace(
            episode, outcomes=json.loads(json.dumps(episode.outcomes)),
        ))

    async def recent_for_agent(self, agent_id: str, k: int = 5) -> list[Any]:
        self.recall_calls += 1
        return [ep for ep in reversed(self.stored) if agent_id in ep.agent_ids][:k]


def _config(*, refs_on: bool) -> SystemConfig:
    cfg = SystemConfig()
    cfg.memory.recall_outcome_refs_enabled = refs_on
    return cfg


def _runtime(
    *,
    refs_on: bool = True,
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
        ontology=None,
        registry=None,
    )


def _store(tmp_path: Path, *, clock: Any = None) -> ArtifactStore:
    if clock is None:
        return ArtifactStore(tmp_path / "artifacts.db")
    return ArtifactStore(tmp_path / "artifacts.db", clock=clock)


def _add(
    store: ArtifactStore,
    name: str,
    *,
    thread_id: str = THREAD,
    created_by: str = AGENT,
    content_hash: str | None = None,
    size_bytes: int = 100,
) -> Any:
    return store.add_version(
        thread_id=thread_id,
        name=name,
        content_hash=content_hash or ("a" * 64),
        mime="text/markdown",
        size_bytes=size_bytes,
        created_by=created_by,
    )


async def _drain(hold: set) -> None:
    while hold:
        await asyncio.gather(*tuple(hold), return_exceptions=True)
        await asyncio.sleep(0)


async def _promoted_run(*, runtime: Any, body: str, agent_id: str = AGENT) -> None:
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
        agent_id=agent_id,
        thread_id=THREAD,
        request_text="top 15 PyPI packages",
        hold=hold,
        completed_probe=lambda: True,
    )
    release.set()
    await _drain(hold)


# ── 1-6. the store query ──────────────────────────────────────────


def test_the_register_returns_only_the_callers_own_artifacts(tmp_path: Path) -> None:
    """One agent's work must not appear in another's register."""
    store = _store(tmp_path)
    _add(store, "mine.md")
    _add(store, "theirs.md", created_by=OTHER)

    rows = store.list_recent_by_creator(AGENT)

    assert [r.name for r in rows] == ["mine.md"]
    assert all(r.created_by == AGENT for r in rows)


def test_a_blank_creator_is_not_a_wildcard(tmp_path: Path) -> None:
    """An anonymous caller must not enumerate the ship's output — the same
    ownership rule ``recall_artifact_tool`` enforces."""
    store = _store(tmp_path)
    _add(store, "mine.md")
    _add(store, "theirs.md", created_by=OTHER)

    for blank in ("", "   ", None):
        assert store.list_recent_by_creator(blank) == [], repr(blank)


def test_only_the_latest_version_of_a_name_appears(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for _ in range(3):
        _add(store, "report.md")

    rows = store.list_recent_by_creator(AGENT)

    assert len(rows) == 1
    assert rows[0].version == 3


def test_two_threads_sharing_a_name_both_appear(tmp_path: Path) -> None:
    """Artifact names are unique per THREAD, so grouping by name alone would
    silently collapse two different threads' outputs into one."""
    store = _store(tmp_path)
    _add(store, "notes.md", thread_id=THREAD)
    _add(store, "notes.md", thread_id=OTHER_THREAD)

    rows = store.list_recent_by_creator(AGENT)

    assert len(rows) == 2
    assert {r.thread_id for r in rows} == {THREAD, OTHER_THREAD}
    assert {r.version for r in rows} == {1}


def test_the_newest_artifact_comes_first(tmp_path: Path) -> None:
    store = _store(tmp_path, clock=_Clock())
    _add(store, "first.md")
    _add(store, "second.md")
    _add(store, "third.md")

    rows = store.list_recent_by_creator(AGENT)

    assert [r.name for r in rows] == ["third.md", "second.md", "first.md"]


def test_a_limit_bounds_the_register(tmp_path: Path) -> None:
    store = _store(tmp_path, clock=_Clock())
    for i in range(5):
        _add(store, f"doc-{i}.md")

    assert len(store.list_recent_by_creator(AGENT, limit=2)) == 2


@pytest.mark.parametrize("bad", [0, -1, True, "3", 2.0])
def test_an_invalid_limit_is_refused(tmp_path: Path, bad: Any) -> None:
    """Same validation and same message as ``list_thread_latest``."""
    store = _store(tmp_path)
    _add(store, "doc.md")

    with pytest.raises(ValueError, match="artifact_list_limit_invalid"):
        store.list_recent_by_creator(AGENT, limit=bad)


# ── 7-12. the render ──────────────────────────────────────────────


def test_the_register_is_empty_when_the_flag_is_off(tmp_path: Path) -> None:
    """Default-OFF must mean the assembled prompt is unchanged, not merely
    similar: no segments at all, so no bid is ever emitted."""
    store = _store(tmp_path)
    _add(store, "report.md")
    runtime = _runtime(refs_on=False, artifacts=store)

    assert _format_recent_outputs(runtime, AGENT) == []


def test_the_register_is_empty_with_no_artifact_store() -> None:
    assert _format_recent_outputs(_runtime(artifacts=None), AGENT) == []


def test_the_register_is_empty_for_an_anonymous_caller(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _add(store, "report.md")
    runtime = _runtime(artifacts=store)

    for blank in ("", "   "):
        assert _format_recent_outputs(runtime, blank) == [], repr(blank)


def test_an_agent_that_has_produced_nothing_renders_no_header(
    tmp_path: Path,
) -> None:
    """An empty header block would tell the agent it has a register and then
    show it nothing, which reads as 'you made nothing' even when the store is
    simply young."""
    runtime = _runtime(artifacts=_store(tmp_path))

    lines = _format_recent_outputs(runtime, AGENT)

    assert lines == []
    assert "WHAT YOU HAVE PRODUCED" not in "\n".join(lines)


def test_a_raising_store_degrades_to_nothing_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Boom:
        def list_recent_by_creator(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("artifact db locked")

    runtime = _runtime(artifacts=_Boom())

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.cognitive_agent"):
        lines = _format_recent_outputs(runtime, AGENT)

    assert lines == []
    assert any("AD-1227" in r.message for r in caplog.records)


def test_a_rendered_line_names_the_artifact_and_a_callable_ref(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    content_hash = "c1a8be361c54" + "0" * 52
    _add(store, "task-712ebc8d645f", content_hash=content_hash, size_bytes=1333)

    lines = _format_recent_outputs(_runtime(artifacts=store), AGENT)

    body = "\n".join(lines)
    assert lines[0] == "=== WHAT YOU HAVE PRODUCED ==="
    assert "=== END ===" in lines
    assert '"task-712ebc8d645f"' in body
    assert "1,333 bytes" in body
    assert "ago)" in body
    quoted = re.search(r'recall_artifact\("([0-9a-f]+)"\)', body)
    assert quoted is not None, body
    # The SAME prefix length AD-1226's memory cue uses, so both surfaces name an
    # identifier ``recall_artifact`` actually resolves.
    assert len(quoted.group(1)) == _PRODUCED_HASH_CHARS
    assert quoted.group(1) == content_hash[:_PRODUCED_HASH_CHARS]


def test_a_second_version_is_marked_and_a_first_is_not(tmp_path: Path) -> None:
    """A v1 marker on everything is noise; a v3 marker is information."""
    store = _store(tmp_path, clock=_Clock())
    _add(store, "once.md")
    for _ in range(2):
        _add(store, "twice.md")

    lines = _format_recent_outputs(_runtime(artifacts=store), AGENT)

    once = [ln for ln in lines if "once.md" in ln][0]
    twice = [ln for ln in lines if "twice.md" in ln][0]
    assert " v2" in twice
    assert " v" not in once.split("(", 1)[0].replace(".md", "")


def test_the_register_is_bounded_by_the_named_limit(tmp_path: Path) -> None:
    """Always-present sections are charged to every turn's budget, so the cap is
    a decision and must be enforced, not merely documented."""
    store = _store(tmp_path, clock=_Clock())
    for i in range(_RECENT_OUTPUTS_LIMIT + 4):
        _add(store, f"doc-{i}.md")

    lines = _format_recent_outputs(_runtime(artifacts=store), AGENT)

    assert len([ln for ln in lines if "recall_artifact(" in ln]) == _RECENT_OUTPUTS_LIMIT


def test_the_register_does_not_trip_the_capability_gap_regex(
    tmp_path: Path,
) -> None:
    """Agent-facing text matching ``_CAPABILITY_GAP_RE`` triggers
    self-modification."""
    from probos.cognitive.decomposer import is_capability_gap

    store = _store(tmp_path)
    _add(store, "report.md")

    for line in _format_recent_outputs(_runtime(artifacts=store), AGENT):
        assert not is_capability_gap(line), line


# ── 13. independent of episodic memory ────────────────────────────


def test_the_register_renders_with_no_episodic_memory_at_all(
    tmp_path: Path,
) -> None:
    """THE POINT OF THE AD. BF-739 happened because the only path to "what have
    I produced?" ran through semantic recall, where the ref-bearing episode is
    outranked by its own conversational twin, by dream-consolidated narrations
    of the failure, and by the agent's own earlier denial.

    A test that would still pass if that dependency were quietly reintroduced
    would be worthless, so this one removes episodic memory entirely.
    """
    store = _store(tmp_path)
    _add(store, "task-712ebc8d645f", content_hash="d" * 64, size_bytes=1333)
    runtime = _runtime(artifacts=store, memory=None)
    assert runtime.episodic_memory is None

    lines = _format_recent_outputs(runtime, AGENT)

    assert lines, "the register needs semantic recall, which is the defect"
    assert any("task-712ebc8d645f" in ln for ln in lines)
    assert any("recall_artifact(" in ln for ln in lines)


# ── 14. THE CROSSING TEST ─────────────────────────────────────────


async def test_the_crossing_promoted_run_to_rendered_register_to_original_text(
    tmp_path: Path,
) -> None:
    """Promoted run → artifact registered → register rendered → the hash taken
    FROM THAT RENDERED LINE → the original body, byte for byte.

    Nothing between the register and the body is stubbed: a real
    ``FilesystemAttachmentStore``, a real ``ArtifactStore``, the real
    ``run_with_promotion`` write path, the real renderer and the real tool. No
    ``EpisodicMemory`` — no embeddings, no similarity, no ranking — anywhere.

    The load-bearing assertion is ``recall_calls == 0`` at step 2: the register
    answers from ``ArtifactStore`` alone. Step 4 then exercises
    ``recall_artifact`` as it actually ships (see
    ``test_the_rendered_prefix_resolves_only_through_the_episode_index`` for
    what that costs).
    """
    attachments = FilesystemAttachmentStore(tmp_path / "attachments")
    artifacts = ArtifactStore(tmp_path / "artifacts.db")
    episodes = _EpisodeLog()
    runtime = _runtime(
        attachments=attachments,
        artifacts=artifacts,
        memory=episodes,
        work_items=_FakeWorkItemStore(),
        threads=_FakeThreadStore(),
    )

    # 1. A promoted run produces the report and registers it.
    await _promoted_run(runtime=runtime, body=REPORT_BODY)

    # 2. The register renders it — no recall, no embeddings, no ranking.
    lines = _format_recent_outputs(runtime, AGENT)
    assert lines, "the promoted run's artifact never reached the register"
    assert episodes.recall_calls == 0, (
        "the register consulted episodic memory, which is the BF-739 defect"
    )

    # 3. Take the ref out of the RENDERED LINE, exactly as the agent would.
    produced = [ln for ln in lines if "recall_artifact(" in ln]
    assert len(produced) == 1, produced
    quoted = re.search(r'recall_artifact\("([0-9a-f]+)"\)', produced[0])
    assert quoted is not None, produced[0]
    ref_from_prompt = quoted.group(1)

    # 4. The tool returns the original body.
    res = await RecallArtifactTool(runtime=runtime).invoke(
        {"ref": ref_from_prompt}, {"agent_id": AGENT, "thread_id": THREAD},
    )

    assert res.error is None
    assert res.output["found"] is True
    assert res.output["text"] == REPORT_BODY, (
        "the round trip did not return the original report"
    )
    assert res.output["total_chars"] == len(REPORT_BODY)


async def test_the_rendered_prefix_resolves_without_any_episode_index(
    tmp_path: Path,
) -> None:
    """The identifier the register prints must stay readable for as long as the
    artifact exists, not merely while its episode is fresh.

    This began as a characterisation of a real gap found while building
    AD-1227: ``recall_artifact`` resolved a hash PREFIX only through
    ``_resolve_from_episodes`` -- the 50-episode ``recent_for_agent`` window --
    while full hashes and names went to ``ArtifactStore``. So the register was
    independent of episodic memory but the ref it printed was not, and an
    artifact whose episode had aged out was named in the prompt and then
    unreadable. ``ArtifactStore.find_by_hash_prefix`` closed that. The test is
    kept and inverted rather than deleted, so the gap cannot reopen silently.

    No ``EpisodicMemory`` anywhere here -- that is the point.
    """
    import hashlib

    attachments = FilesystemAttachmentStore(tmp_path / "attachments")
    artifacts = ArtifactStore(tmp_path / "artifacts.db")
    blob = REPORT_BODY.encode("utf-8")
    content_hash = hashlib.sha256(blob).hexdigest()
    await attachments.write(
        content_hash, blob, "text/markdown", origin="agent_artifact",
    )
    artifacts.add_version(
        thread_id=THREAD, name="task-aged-out", content_hash=content_hash,
        mime="text/markdown", size_bytes=len(blob), created_by=AGENT,
    )
    # No episode index at all: the artifact outlived its episode.
    runtime = _runtime(attachments=attachments, artifacts=artifacts, memory=None)
    tool = RecallArtifactTool(runtime=runtime)
    ctx = {"agent_id": AGENT, "thread_id": THREAD}

    rendered = _format_recent_outputs(runtime, AGENT)
    quoted = re.search(r'recall_artifact\("([0-9a-f]+)"\)', "\n".join(rendered))
    assert quoted is not None

    prefix = (await tool.invoke({"ref": quoted.group(1)}, ctx)).output
    full = (await tool.invoke({"ref": content_hash}, ctx)).output
    by_name = (await tool.invoke({"ref": "task-aged-out"}, ctx)).output

    assert prefix["found"] is True, (
        "the prefix the register prints must resolve with no episode index"
    )
    assert prefix["text"] == REPORT_BODY
    assert full["found"] is True
    assert by_name["found"] is True


async def test_a_prefix_belonging_to_another_agent_does_not_resolve(
    tmp_path: Path,
) -> None:
    """``find_by_hash_prefix`` is creator-scoped in SQL. A prefix is short
    enough that an unscoped lookup could reach across agents, and the register
    is only ever the caller's own work.
    """
    import hashlib

    attachments = FilesystemAttachmentStore(tmp_path / "attachments")
    artifacts = ArtifactStore(tmp_path / "artifacts.db")
    blob = REPORT_BODY.encode("utf-8")
    content_hash = hashlib.sha256(blob).hexdigest()
    await attachments.write(
        content_hash, blob, "text/markdown", origin="agent_artifact",
    )
    artifacts.add_version(
        thread_id=THREAD, name="someone-elses", content_hash=content_hash,
        mime="text/markdown", size_bytes=len(blob), created_by="another_agent_0_ffff",
    )
    runtime = _runtime(attachments=attachments, artifacts=artifacts, memory=None)

    assert artifacts.find_by_hash_prefix(content_hash[:12], created_by=AGENT) is None
    out = (await RecallArtifactTool(runtime=runtime).invoke(
        {"ref": content_hash[:12]}, {"agent_id": AGENT, "thread_id": THREAD},
    )).output
    assert out["found"] is False


def test_a_non_hex_or_short_prefix_is_refused_not_stripped(tmp_path: Path) -> None:
    """A wildcard in the pattern must be rejected, never removed: stripping it
    would silently search for a different hash than the caller named.
    """
    store = _store(tmp_path)
    _add(store, "task-1", content_hash="ab" * 32)

    assert store.find_by_hash_prefix("ababab", created_by=AGENT) is None  # too short
    assert store.find_by_hash_prefix("abababa%", created_by=AGENT) is None
    assert store.find_by_hash_prefix("ababab_a", created_by=AGENT) is None
    assert store.find_by_hash_prefix("zzzzzzzz", created_by=AGENT) is None
    assert store.find_by_hash_prefix("abababab", created_by="") is None
    assert store.find_by_hash_prefix("abababab", created_by=AGENT) is not None


# ── 15. the emit site is live ─────────────────────────────────────


def _dm_agent(runtime: Any) -> Any:
    agent = make_dm_agent()
    agent._runtime = runtime
    agent.id = AGENT
    return agent


async def test_the_dm_prompt_actually_carries_the_register(tmp_path: Path) -> None:
    """The renderer being correct proves nothing if nothing calls it.

    A tested producer plus a tested consumer with no test across the seam is
    this repo's most common defect — every link correct, the chain dead. This
    one drives the REAL ``_build_user_message`` DM branch and asserts the block
    reached the assembled prompt.
    """
    store = _store(tmp_path)
    _add(store, "task-712ebc8d645f", content_hash="e" * 64, size_bytes=1333)

    msg = await _dm_agent(_runtime(artifacts=store))._build_user_message(
        dm_observation()
    )

    assert "=== WHAT YOU HAVE PRODUCED ===" in msg
    assert "task-712ebc8d645f" in msg
    assert 'recall_artifact("eeeeeeeeeeee")' in msg


async def test_the_dm_prompt_is_byte_identical_with_the_flag_off(
    tmp_path: Path,
) -> None:
    """Default-OFF has to mean unchanged, not merely similar."""
    store = _store(tmp_path)
    _add(store, "task-712ebc8d645f")

    on_store_off_flag = await _dm_agent(
        _runtime(refs_on=False, artifacts=store)
    )._build_user_message(dm_observation())
    no_runtime_at_all = await _dm_agent(None)._build_user_message(dm_observation())

    assert on_store_off_flag == no_runtime_at_all
    assert "WHAT YOU HAVE PRODUCED" not in on_store_off_flag
