"""BF-932 (#1670) D1: the dream cycle's synchronous loops give the event loop a turn, and Step 7g publishes no stale note.

A ticker task counts the turns the event loop gives other tasks. A recorder notes the ticker's count at each unit of
one loop (a pair comparison, a word set, a notebook read, a parsed file, an episode written). The difference between
the first and the last unit of that loop is how many turns the loop gave; at the base each of these loops gave none.
The step's output is compared on a fixed fixture. Over a real RecordsStore, a note revised at any turn Step 7g gives,
or right after the step's read of it, keeps its revision; an unchanged note is consolidated as at the base whatever
its frontmatter loads to; a write, a publish, a rename away and a deletion each read as changed; and a check that
raises skips its own cluster only. No assertion bounds a duration.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive import dreaming
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.knowledge import records_store as records_module
from probos.knowledge.records_store import RecordsStore
from tests.test_ad551_notebook_consolidation import _entry, _make_engine, _make_records_store, _read_result

# The contract's budgets, written out: a test that read them from the module could not catch a changed budget.
_PAIRS_PER_TURN = 2000
_READS_PER_TURN = 16
_LIST_FILES_PER_TURN = 16
_DECAY_EPISODES_PER_TURN = 8

_ALPHA, _BETA, _GAMMA = 100, 20, 20
# Each agent's convergent notes: 64 in all, so the convergence's coherence makes 64 * 63 / 2 = 2,016 comparisons, more
# than one pair budget.
_CONVERGENT = {"alpha": range(2, 32), "beta": range(0, 17), "gamma": range(0, 17)}
_SHARED = "reactor coolant pressure trending nominal"  # 5 words
_DUPLICATE = "duplicate finding about the warp core alignment log"


class _Ticker:
    """Counts the event loop's turns for other tasks: one per iteration, each ending in ``sleep(0)``."""

    def __init__(self) -> None:
        self.turns = 0
        self._task: asyncio.Task[None] | None = None

    async def _run(self) -> None:
        while True:
            self.turns += 1
            await asyncio.sleep(0)

    async def __aenter__(self) -> "_Ticker":
        self._task = asyncio.create_task(self._run())
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        assert self._task is not None
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)


def _fixture() -> tuple[list[dict], dict[str, dict]]:
    """Three agents in two departments. Alpha's notes 0 and 1 form one per-agent cluster. Each convergent note is the
    5 shared words and 2 of its own, so any two share 5 of 9 words (0.556): under the per-agent threshold (0.6), over
    the convergence threshold (0.5). They form one convergence of 64 notes; every other note is unique."""
    entries: list[dict] = []
    read_map: dict[str, dict] = {}
    plan = (("alpha", "science", _ALPHA), ("beta", "medical", _BETA), ("gamma", "science", _GAMMA))
    for agent, dept, count in plan:
        for k in range(count):
            path = f"notebooks/{agent}/note-{k:03d}.md"
            if agent == "alpha" and k in (0, 1):
                content = _DUPLICATE
            elif k in _CONVERGENT[agent]:
                content = f"{_SHARED} {agent}-{k}-x {agent}-{k}-y"
            else:
                content = " ".join(f"{agent}-{k}-w{m}" for m in range(12))
            entries.append(_entry(path, author=agent, dept=dept, updated=f"2026-04-01T{k % 24:02d}:00:00"))
            read_map[path] = _read_result(path, content)
    return entries, read_map


async def _run_dream(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """One dream cycle over the fixture, with the ticker's count noted at each comparison, word set and read."""
    entries, read_map = _fixture()
    store = _make_records_store(entries, read_map)
    engine = _make_engine(records_store=store)
    events: list[tuple[str, dict]] = []
    engine._emit_event_fn = lambda event_type, data: events.append((event_type, data))
    pair_turns: list[int] = []
    word_turns: list[int] = []
    read_turns: list[int] = []
    reader = store.read_entry.side_effect
    async with _Ticker() as ticker:

        def _pair(a: set[str], b: set[str]) -> float:
            pair_turns.append(ticker.turns)
            return jaccard_similarity(a, b)

        def _words(text: str) -> set[str]:
            word_turns.append(ticker.turns)
            return text_to_words(text)

        async def _read(path: str, reader_id: str = "system", **kwargs: Any) -> Any:
            read_turns.append(ticker.turns)
            return await reader(path, reader_id=reader_id, **kwargs)

        monkeypatch.setattr(dreaming, "jaccard_similarity", _pair)
        monkeypatch.setattr(dreaming, "text_to_words", _words)
        store.read_entry.side_effect = _read
        report = await engine.dream_cycle()
    return {
        "report": report, "store": store, "events": events,
        "pairs": pair_turns, "words": word_turns, "reads": read_turns,
    }


@pytest.mark.asyncio
async def test_d1_step_7g_gives_the_loop_turns_inside_each_of_its_loops(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = await _run_dream(monkeypatch)
    pairs, words, reads = seen["pairs"], seen["words"], seen["reads"]
    notes = _ALPHA + _BETA + _GAMMA
    alpha_pairs = _ALPHA * (_ALPHA - 1) // 2  # alpha is listed first, so its pass makes the first comparisons
    cross_pairs = _ALPHA * _BETA + _ALPHA * _GAMMA + _BETA * _GAMMA  # different-agent pairs; the coherence pairs follow
    convergent = sum(len(ks) for ks in _CONVERGENT.values())
    coherence_pairs = convergent * (convergent - 1) // 2  # 2,016: more than one pair budget
    per_agent_pairs = alpha_pairs + _BETA * (_BETA - 1) // 2 + _GAMMA * (_GAMMA - 1) // 2
    assert len(pairs) == per_agent_pairs + cross_pairs + coherence_pairs
    assert pairs[alpha_pairs - 1] - pairs[0] >= alpha_pairs // _PAIRS_PER_TURN
    assert pairs[-(coherence_pairs + 1)] - pairs[-(cross_pairs + coherence_pairs)] >= cross_pairs // _PAIRS_PER_TURN
    assert pairs[-1] - pairs[-coherence_pairs] >= coherence_pairs // _PAIRS_PER_TURN  # the coherence pass's own turn
    assert reads[_ALPHA - 1] - reads[0] >= _ALPHA // _READS_PER_TURN  # alpha's reads, before its comparisons
    # The cross-agent pass reads every note again, last. Counted from the end, so the count holds whatever else
    # reads a note before that pass (the publication checks fingerprint the files and do not call read_entry).
    assert reads[-1] - reads[-notes] >= notes // _READS_PER_TURN
    assert words[2 * notes - 1] - words[notes] >= notes // _READS_PER_TURN  # the cross-agent pass's word sets
    assert words[_ALPHA - 1] - words[0] >= _ALPHA // _READS_PER_TURN  # alpha's per-agent word sets


@pytest.mark.asyncio
async def test_d1_step_7g_output_is_the_bases_on_a_fixed_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Control: passes on the base too. One per-agent cluster, one convergence of 64 notes, the base's coherence to the bit."""
    seen = await _run_dream(monkeypatch)
    report, store, events = seen["report"], seen["store"], seen["events"]
    consolidated = [
        (call.kwargs["path"], call.kwargs["message"])
        for call in store.write_entry.call_args_list
        if str(call.kwargs.get("message", "")).startswith("AD-551: Consolidated")
    ]
    assert consolidated == [("notebooks/alpha/note-001.md", "AD-551: Consolidated 2 entries")]
    assert report.notebook_consolidations == 1
    convergences = [data for event_type, data in events if event_type == "convergence_detected"]
    assert report.convergence_reports_generated == 1 and len(convergences) == 1
    assert convergences[0]["agents"] == ["alpha", "beta", "gamma"]
    assert convergences[0]["departments"] == ["medical", "science"]
    coherence_pairs = 64 * 63 // 2
    total = 0.0
    for _ in range(coherence_pairs):
        total += 5 / 9  # each pair shares 5 of 9 distinct words; the sum runs in the base's order
    assert convergences[0]["coherence"] == total / coherence_pairs


def _notes(root: Path, count: int) -> list[str]:
    folder = root / "notebooks" / "ezri"
    folder.mkdir(parents=True)
    paths: list[str] = []
    for k in range(count):
        (folder / f"note-{k:03d}.md").write_text(f"---\nauthor: ezri\ntopic: t{k}\n---\nbody {k}\n", encoding="utf-8")
        paths.append(f"notebooks/ezri/note-{k:03d}.md")
    return paths


async def _listing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, strict: bool) -> tuple[list[str], list[dict], list[int]]:
    """A real RecordsStore over 40 notes; the ticker's count noted at each file the listing parses."""
    store = RecordsStore(SimpleNamespace(repo_path=str(tmp_path / "records")))
    expected = _notes(tmp_path / "records", 40)
    turns: list[int] = []
    parse = records_module._load_document
    async with _Ticker() as ticker:

        def _parse(raw: str) -> Any:
            turns.append(ticker.turns)
            return parse(raw)

        monkeypatch.setattr(records_module, "_load_document", _parse)
        listed = await store.list_entries("notebooks", strict=strict)
    return expected, listed, turns


@pytest.mark.asyncio
async def test_d1_a_default_listing_gives_the_loop_turns_and_lists_every_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected, listed, turns = await _listing(tmp_path, monkeypatch, strict=False)
    assert [entry["path"] for entry in listed] == expected
    assert len(turns) == 40
    assert turns[-1] - turns[0] >= 40 // _LIST_FILES_PER_TURN


@pytest.mark.asyncio
async def test_d1_a_strict_listing_keeps_its_one_uninterrupted_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: passes on the base too. The stand-down's and the archive promotion's listing is one pass."""
    expected, listed, turns = await _listing(tmp_path, monkeypatch, strict=True)
    assert [entry["path"] for entry in listed] == expected
    assert len(turns) == 40
    assert turns[-1] - turns[0] == 0


class _Collection:
    """Stands in for chromadb's Collection: the page read, the read by id and the update the AD-873 sweep makes."""

    def __init__(self, count: int, turns: Any) -> None:
        self.ids = [f"ep-{k:03d}" for k in range(count)]
        self._metadata = {episode_id: {"timestamp": 1000.0} for episode_id in self.ids}
        self._turns = turns
        self.updates: list[tuple[str, int]] = []

    def get(self, ids: list[str] | None = None, include: Any = None, limit: Any = None, offset: Any = None) -> dict:
        wanted = list(self.ids) if ids is None else list(ids)
        return {"ids": wanted, "metadatas": [dict(self._metadata[episode_id]) for episode_id in wanted]}

    def update(self, ids: list[str], metadatas: list[dict]) -> None:
        self.updates.append((ids[0], self._turns()))
        self._metadata[ids[0]] = metadatas[0]


@pytest.mark.asyncio
async def test_d1_the_decay_sweep_gives_the_loop_turns_and_writes_every_episode(tmp_path: Path) -> None:
    memory = EpisodicMemory(db_path=tmp_path / "episodic")
    async with _Ticker() as ticker:
        collection = _Collection(40, lambda: ticker.turns)
        memory._collection = collection
        counts = await memory.sweep_episode_decay(None)
    assert counts == {"swept": 40, "reinforced": 0}
    assert [episode_id for episode_id, _turn in collection.updates] == collection.ids
    turns = [turn for _episode_id, turn in collection.updates]
    assert turns[-1] - turns[0] >= 40 // _DECAY_EPISODES_PER_TURN


def test_d1_loop_yield_is_due_on_every_nth_unit_only() -> None:
    from probos.utils.loop_yield import LoopYield  # here, so the base's missing module fails this test alone

    pacer = LoopYield(3)
    assert [pacer.due() for _ in range(7)] == [False, False, True, False, False, True, False]
    with pytest.raises(ValueError):
        LoopYield(0)


_SEED = "trust score is stable at nominal levels for all agents in the medical department"  # 14 words
_REVISION = "captain-correction-after-the-read"
_PRIMARY = "notebooks/alpha/n-2.md"  # the newest of the three, so the cluster's primary
_MEMBER = "notebooks/alpha/n-0.md"  # read first and archived last
_OTHER = "warp field geometry holds steady across every deck during a long patrol tonight"  # 13 words, none of _SEED's
# Frontmatter that the safe loader accepts and that a comparison of loaded documents mishandles. Step 7g compares file
# bytes, so a note holding any of them consolidates as at the base. "loop": a mapping that contains itself (an anchor
# and its alias; == between two loads raises RecursionError). "bigint": an integer of 16,384 bits (its decimal repr
# passes CPython's 4,300-digit limit and raises ValueError). "nanset": a set of explicitly tagged NaNs (each load makes
# new NaNs, so the set's order, and its repr, can differ between loads of the same bytes). "mixed": an ordered map
# (a list of tuples), a date, bytes, and a key 1 beside a key true (equal keys of different types).
_LOOP_FRONTMATTER = "loop: &loop\n  self: *loop\n"
_BIG_INT_FRONTMATTER = "big: 0x" + "f" * 4096 + "\n"
_NAN_SET_FRONTMATTER = "nans: !!set\n" + "  ? !!float nan\n" * 8
_MIXED_FRONTMATTER = (
    "mixed:\n  pairs: !!omap\n    - a: 1\n    - b: 2\n  day: 2026-04-01\n  blob: !!binary aGVsbG8=\n"
    "  keys: {1: one, true: two}\n"
)
_ODD_FRONTMATTER = {
    "loop": _LOOP_FRONTMATTER,
    "bigint": _BIG_INT_FRONTMATTER,
    "nanset": _NAN_SET_FRONTMATTER,
    "mixed": _MIXED_FRONTMATTER,
}
_CONSOLIDATED_ALPHA = (
    f"{_SEED} reading 2\n\n## Consolidated Observations\n\n"
    f"{_SEED} reading 1\n\n---\n\n{_SEED} reading 0"
)


class _StepTurns:
    """Stands in for the dreaming module's ``asyncio``: each ``sleep`` there is one of Step 7g's turns."""

    def __init__(self, on_turn: Any) -> None:
        self._on_turn = on_turn

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)

    async def sleep(self, delay: float, result: Any = None) -> Any:
        await self._on_turn()
        return await asyncio.sleep(delay, result)


def _seed_notes(
    root: Path, agent: str = "alpha", text: str = _SEED, extra_in: int | None = None, odd: str = _LOOP_FRONTMATTER,
) -> None:
    """Three similar notes of one agent; note ``n-<extra_in>``'s frontmatter also holds ``odd``."""
    folder = root / "notebooks" / agent
    folder.mkdir(parents=True)
    for k in range(3):
        stamp = f"2026-04-01T0{k}:00:00"
        extra = odd if k == extra_in else ""
        front = f"---\nauthor: {agent}\nclassification: ship\ncreated: '{stamp}'\nupdated: '{stamp}'\n{extra}---\n\n"
        (folder / f"n-{k}.md").write_text(f"{front}{text} reading {k}", encoding="utf-8")


async def _consolidate_on_disk(
    root: Path, monkeypatch: pytest.MonkeyPatch, *, target: str | None = None, at_turn: int = 0, seed: bool = True,
    extra_in: int | None = None,
) -> dict[str, Any]:
    """One dream over three similar notes of one agent in a real RecordsStore (auto_commit off, git stubbed).

    A turn is each ``sleep`` of Step 7g (both budgets set to 1, so each read, word set and pair gives one), the
    consolidation write's return (with auto_commit on, write_entry awaits git and the indexer after its file write)
    and each archive rename's ``git add -A``. At turn ``at_turn`` the target note is revised through the real
    ``write_entry``, as a writer task would be in that turn.
    """
    if seed:
        _seed_notes(root, extra_in=extra_in)
    store = RecordsStore(SimpleNamespace(repo_path=str(root), auto_commit=False))
    write = store.write_entry
    state: dict[str, Any] = {"turns": 0, "landed": False}

    async def on_turn() -> None:
        state["turns"] += 1
        if target is not None and state["turns"] == at_turn:
            await write(author="alpha", path=target, content=f"{_SEED} {_REVISION}", message="revision")
            state["landed"] = True

    async def written(*args: Any, **kwargs: Any) -> str:
        path = await write(*args, **kwargs)
        if str(kwargs.get("message", "")).startswith("AD-551: Consolidated"):
            await on_turn()
        return path

    async def git(*args: str) -> str:
        if args[:2] == ("add", "-A"):
            await on_turn()
        return ""

    store.write_entry = written  # type: ignore[method-assign]
    store._git = git  # type: ignore[method-assign]
    monkeypatch.setattr(dreaming, "_STEP_7G_READS_PER_YIELD", 1, raising=False)  # absent at the base: no turn there
    monkeypatch.setattr(dreaming, "_STEP_7G_PAIRS_PER_YIELD", 1, raising=False)
    monkeypatch.setattr(dreaming, "asyncio", _StepTurns(on_turn))
    report = await _make_engine(records_store=store).dream_cycle()
    folder = root / "notebooks" / "alpha"
    live: dict[str, Any] = {}
    for note in sorted(folder.glob("*.md")):
        doc = await store.read_entry(f"notebooks/alpha/{note.name}", reader_id="captain")
        live[note.name] = doc["content"] if doc else None
    archived = sorted(note.name for note in (folder / "_archived").glob("*.md"))
    return {"report": report, "turns": state["turns"], "landed": state["landed"], "live": live, "archived": archived}


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [_PRIMARY, _MEMBER], ids=["primary", "member"])
async def test_d1_a_note_revised_at_any_turn_of_step_7g_keeps_its_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str,
) -> None:
    """At each turn the step gives, one run revises the target; afterwards a live note holds the revision."""
    total = (await _consolidate_on_disk(tmp_path / "count", monkeypatch))["turns"]
    lost: list[int] = []
    for turn in range(1, total + 1):
        seen = await _consolidate_on_disk(tmp_path / f"turn-{turn}", monkeypatch, target=target, at_turn=turn)
        assert seen["landed"]
        if not any(text and _REVISION in text for text in seen["live"].values()):
            lost.append(turn)
    assert lost == []


@pytest.mark.asyncio
async def test_d1_a_cluster_skipped_as_stale_is_consolidated_by_the_next_dream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Turn 9 is the step's last before its write: 3 reads, 3 word sets, then the third pair's turn.
    first = await _consolidate_on_disk(tmp_path, monkeypatch, target=_PRIMARY, at_turn=9)
    assert first["landed"]
    assert first["report"].notebook_consolidations == 0
    assert first["archived"] == [] and sorted(first["live"]) == ["n-0.md", "n-1.md", "n-2.md"]
    second = await _consolidate_on_disk(tmp_path, monkeypatch, seed=False)
    assert second["report"].notebook_consolidations == 1
    assert second["archived"] == ["n-0.md", "n-1.md"] and list(second["live"]) == ["n-2.md"]
    assert second["live"]["n-2.md"].startswith(f"{_SEED} {_REVISION}\n\n## Consolidated Observations\n\n")


@pytest.mark.asyncio
async def test_d1_step_7g_on_disk_with_no_concurrent_writer_writes_what_the_base_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: passes on the base too. The primary keeps its body, then the others' bodies, newest first."""
    seen = await _consolidate_on_disk(tmp_path, monkeypatch)
    assert seen["report"].notebook_consolidations == 1
    assert seen["archived"] == ["n-0.md", "n-1.md"]
    assert seen["live"] == {"n-2.md": _CONSOLIDATED_ALPHA}


@pytest.mark.asyncio
@pytest.mark.parametrize("odd", list(_ODD_FRONTMATTER))
async def test_d1_an_unchanged_note_is_consolidated_as_at_the_base_whatever_its_frontmatter_loads_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, odd: str,
) -> None:
    """Control: passes on the base too. Two clusters and no writer: alpha's, whose oldest member's frontmatter also
    holds ``_ODD_FRONTMATTER[odd]``, and beta's, ordinary. Both consolidate; no check skips alpha's."""
    _seed_notes(tmp_path, extra_in=0, odd=_ODD_FRONTMATTER[odd])
    _seed_notes(tmp_path, agent="beta", text=_OTHER)
    seen = await _consolidate_on_disk(tmp_path, monkeypatch, seed=False)
    assert seen["report"].notebook_consolidations == 2
    assert seen["report"].notebook_entries_archived == 4
    assert seen["archived"] == ["n-0.md", "n-1.md"]
    assert seen["live"] == {"n-2.md": _CONSOLIDATED_ALPHA}
    beta = tmp_path / "notebooks" / "beta"
    assert sorted(note.name for note in (beta / "_archived").glob("*.md")) == ["n-0.md", "n-1.md"]
    assert sorted(note.name for note in beta.glob("*.md")) == ["n-2.md"]


@pytest.mark.asyncio
async def test_d1_a_note_whose_frontmatter_contains_itself_keeps_a_revision_made_at_any_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The member whose frontmatter contains itself: with no writer the cluster consolidates; at each turn the step
    gives, one run revises that member, and afterwards a live note holds the revision."""
    counted = await _consolidate_on_disk(tmp_path / "count", monkeypatch, extra_in=0)
    assert counted["report"].notebook_consolidations == 1 and counted["archived"] == ["n-0.md", "n-1.md"]
    lost: list[int] = []
    for turn in range(1, counted["turns"] + 1):
        seen = await _consolidate_on_disk(
            tmp_path / f"turn-{turn}", monkeypatch, target=_MEMBER, at_turn=turn, extra_in=0,
        )
        assert seen["landed"]
        if not any(text and _REVISION in text for text in seen["live"].values()):
            lost.append(turn)
    assert lost == []


@pytest.mark.asyncio
async def test_d1_an_unchanged_set_of_nans_reads_as_loaded_on_every_check(tmp_path: Path) -> None:
    """R3-F2: two loads of a set of tagged NaNs can order it differently; its file's bytes do not change."""
    _seed_notes(tmp_path, extra_in=0, odd=_NAN_SET_FRONTMATTER)
    store = RecordsStore(SimpleNamespace(repo_path=str(tmp_path), auto_commit=False))
    item = {"path": _MEMBER, "_fp": await store.entry_fingerprint(_MEMBER)}
    assert item["_fp"] is not None
    checks = [await dreaming._reads_as_loaded(store, item) for _ in range(100)]
    assert checks == [True] * 100


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["write_entry", "publish", "rename", "delete"])
async def test_d1_a_note_reads_as_changed_after_a_write_a_publish_a_rename_or_a_deletion(
    tmp_path: Path, change: str,
) -> None:
    """Every way a note can change under Step 7g reads as changed; ``publish`` bumps ``updated`` but not ``revision``."""
    _seed_notes(tmp_path)
    store = RecordsStore(SimpleNamespace(repo_path=str(tmp_path), auto_commit=False))
    item = {"path": _MEMBER, "_fp": await store.entry_fingerprint(_MEMBER)}
    assert await dreaming._reads_as_loaded(store, item)
    note = tmp_path / _MEMBER
    if change == "write_entry":
        await store.write_entry(author="alpha", path=_MEMBER, content=f"{_SEED} {_REVISION}", message="revision")
    elif change == "publish":
        await store.publish(_MEMBER, author="alpha")
    elif change == "rename":
        (note.parent / "_archived").mkdir()
        note.rename(note.parent / "_archived" / note.name)
    else:
        note.unlink()
    assert not await dreaming._reads_as_loaded(store, item)


@pytest.mark.asyncio
async def test_d1_the_fingerprint_is_taken_before_the_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A revision that lands right after the step's read of the primary reads as changed, because the fingerprint
    was taken before that read. With the fingerprint taken after the read, the publish overwrites the revision."""
    read = RecordsStore.read_entry
    state = {"landed": False}

    async def read_then_revise(self: RecordsStore, path: str, reader_id: str, reader_department: str = "") -> Any:
        doc = await read(self, path, reader_id, reader_department)
        if path == _PRIMARY and not state["landed"]:
            state["landed"] = True
            await RecordsStore.write_entry(
                self, author="alpha", path=_PRIMARY, content=f"{_SEED} {_REVISION}", message="revision",
            )
        return doc

    monkeypatch.setattr(RecordsStore, "read_entry", read_then_revise)
    seen = await _consolidate_on_disk(tmp_path, monkeypatch)
    assert state["landed"]
    assert seen["report"].notebook_consolidations == 0
    assert seen["archived"] == []
    assert seen["live"]["n-2.md"] == f"{_SEED} {_REVISION}"


@pytest.mark.asyncio
async def test_d1_a_check_that_raises_skips_its_own_cluster_and_the_step_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """R3-F3: the primary loads, then its publication check raises. The raise counts as changed inside the helper:
    alpha's cluster is skipped with every note live, beta's (listed after alpha's) still consolidates, and nothing
    reaches Step 7g's whole-step handler."""
    _seed_notes(tmp_path)
    _seed_notes(tmp_path, agent="beta", text=_OTHER)
    fingerprint = RecordsStore.entry_fingerprint
    calls: dict[str, int] = {}

    async def fails_at_the_check(self: RecordsStore, path: str) -> str | None:
        calls[path] = calls.get(path, 0) + 1
        if path == _PRIMARY and calls[path] > 1:
            raise OSError("the fingerprint read failed")
        return await fingerprint(self, path)

    monkeypatch.setattr(RecordsStore, "entry_fingerprint", fails_at_the_check)
    caplog.set_level(logging.DEBUG, logger="probos.cognitive.dreaming")
    seen = await _consolidate_on_disk(tmp_path, monkeypatch, seed=False)
    assert calls[_PRIMARY] == 2  # the load's fingerprint, then the check that raised
    assert seen["report"].notebook_consolidations == 1
    assert seen["report"].notebook_entries_archived == 2
    assert seen["archived"] == [] and sorted(seen["live"]) == ["n-0.md", "n-1.md", "n-2.md"]
    beta = tmp_path / "notebooks" / "beta"
    assert sorted(note.name for note in (beta / "_archived").glob("*.md")) == ["n-0.md", "n-1.md"]
    assert not [r for r in caplog.records if "Step 7g notebook consolidation failed" in r.getMessage()]
