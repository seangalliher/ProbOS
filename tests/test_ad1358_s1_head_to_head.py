"""AD-1358 S1 (#1750): a crew member in a game is told the recorded games against that opponent.

During an active game the crew ``direct_message`` prompt carries, directly after the AD-572
active-game block, a block counted from the AD-526a game records in Ship's Records
(``recreation/games/<game_type>/``), read as the agent (BF-949's reader identity), so a record
it may not read is not counted. With nothing recorded between the two players, or on any
failure, nothing is added and the prompt is as before.

Real fixtures: a real ``RecreationService`` plays and records the games through a real
``RecordsStore`` on ``tmp_path``; a real ``CognitiveAgent`` runs ``_recall_relevant_memories``
then ``_decide_via_llm`` with a ``SimpleNamespace`` runtime and a real ``SystemConfig`` (a
``MagicMock`` config would make ``dm_agentic.enabled`` truthy). Names the slice adds are reached
through ``_built``, which asserts that they exist, so on the base every new-behaviour test fails
at an assertion and the file collects.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from probos.activation.dispatcher import DispatchResult
from probos.cognitive import oracle_service
from probos.cognitive.cognitive_agent import CognitiveAgent, _build_result_metadata
from probos.config import RecordsConfig, SystemConfig
from probos.knowledge.records_store import RecordsStore
from probos.recreation.service import RecreationService
from probos.types import IntentMessage, LLMResponse

_UNTIL_M2 = pytest.mark.xfail(strict=True, raises=AssertionError, reason="AD-1358 S1: built in M2")

AGENT_ID = "ad1358-ezri"
GAMES = "recreation/games/tictactoe"
X_WINS = ["0", "3", "1", "4", "2"]  # X takes the top row (test_cognitive_agent_dm_game.py:691)
O_WINS = ["0", "3", "1", "4", "8", "5"]  # O takes the middle row (:692)
DRAW = ["0", "1", "2", "4", "3", "5", "7", "6", "8"]  # (:693)
FROZEN_TEMPORAL = "Current time: 2026-11-06 12:00:00 UTC (Friday)"
HEADER = "--- Previous Games (Ship's Records) ---"


def _built(name: str) -> Any:
    """An attribute of ``probos.recreation.history``, asserted to exist."""
    assert importlib.util.find_spec("probos.recreation.history") is not None, "AD-1358 S1 is not built"
    module = importlib.import_module("probos.recreation.history")
    assert hasattr(module, name), name
    return getattr(module, name)


async def _empty_sensorium(path: object, observation: dict) -> dict[str, str]:
    del path, observation
    return {}


class _OneReply:
    def __init__(self, content: str) -> None:
        self.content = content
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            content=self.content, model="scripted", tier="standard",
            tokens_used=10, prompt_tokens=5, completion_tokens=5,
        )


class _RaisingRegistry:
    def get(self, _agent_id: str) -> Any:
        raise RuntimeError("registry unavailable")

    def all(self) -> list[Any]:
        raise RuntimeError("registry unavailable")


def _crew_registry() -> SimpleNamespace:
    ezri = SimpleNamespace(id=AGENT_ID, agent_type="scout", callsign="Ezri", sovereign_id="")
    return SimpleNamespace(
        get=lambda agent_id: ezri if agent_id == AGENT_ID else None,
        all=lambda: [ezri],
        get_by_pool=lambda _pool: [],
    )


def _runtime(**attributes: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "config": SystemConfig(),
        "cognitive_journal": None,
        "episodic_memory": None,
        "trust_network": None,
        "recreation_service": None,
        "records_store": None,
        "registry": _crew_registry(),
        "ontology": SimpleNamespace(get_agent_department=lambda _agent_type: "science"),
    }
    base.update(attributes)
    return SimpleNamespace(**base)


def _agent(runtime: Any) -> CognitiveAgent:
    agent = CognitiveAgent(agent_id=AGENT_ID, instructions="You are Ezri.")
    agent.agent_type = "scout"
    agent.callsign = "Ezri"
    agent._runtime = runtime
    agent._llm_client = _OneReply("Good luck, Captain.")
    agent._build_temporal_context = lambda: FROZEN_TEMPORAL  # type: ignore[method-assign]
    agent._dispatch_sensorium_async = _empty_sensorium  # type: ignore[method-assign]
    return agent


async def _turn(agent: CognitiveAgent) -> tuple[str, dict[str, Any]]:
    """One DM turn on "Hello Ezri": the prompt, and the manifest as ``IntentResult.metadata`` carries it."""
    params = {"text": "Hello Ezri", "captain_message": "Hello Ezri"}
    intent = IntentMessage(intent="direct_message", params=params)
    observation = await agent._recall_relevant_memories(
        intent, {"intent": "direct_message", "intent_id": intent.id, "params": params},
    )
    decision = await agent._decide_via_llm(observation)
    manifest = _build_result_metadata({}, decision, observation)["context_manifest"]
    return agent._llm_client.requests[0].prompt, manifest


def _names(manifest: dict[str, Any]) -> list[str]:
    return [section["name"] for section in manifest["sections"]]


async def _store(tmp_path: Path) -> RecordsStore:
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    await store.initialize()
    return store


def _service(store: Any) -> RecreationService:
    dispatcher = SimpleNamespace(dispatch=AsyncMock(return_value=DispatchResult("admission", 1, 1, 0, 0, [])))
    return RecreationService(records_store=store, dispatcher=dispatcher)


async def _play(service: RecreationService, x: str, o: str, moves: list[str]) -> dict[str, Any]:
    """One whole game through the real service; ``_record_game`` writes its record on the last move."""
    game = await service.create_game("tictactoe", x, o)
    for index, position in enumerate(moves):
        await service.make_move(game["game_id"], x if index % 2 == 0 else o, position)
    assert game["result"]["status"] in ("won", "draw")  # premise: finished, so recorded
    return game


async def _record(
    store: RecordsStore, name: str, *, x: str, o: str, winner: str,
    author: str = "system", classification: str = "ship", department: str = "",
) -> None:
    """A record in the AD-526a body form, written through the store with the writer's tags."""
    result = f"won — **{winner}** wins!" if winner else "draw"
    await store.write_entry(
        author, f"{GAMES}/{name}.md",
        f"# Game Record: Tictactoe\n\n**Players:** {x} (X) vs {o} (O)\n**Result:** {result}\n**Moves:** 5\n",
        "AD-1358 fixture", classification=classification, department=department, tags=["game", "tictactoe"],
    )


def _raw(store: RecordsStore, name: str, *, updated: str) -> None:
    """A Captain-won record file with a chosen ``created``/``updated``, laid out as the store writes one."""
    path = store.repo_path / GAMES / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nauthor: system\nclassification: ship\nstatus: draft\n"
        f"created: '{updated}'\nupdated: '{updated}'\ntags:\n- game\n- tictactoe\n---\n\n"
        "**Players:** Captain (X) vs Ezri (O)\n**Result:** won — **Captain** wins!\n",
        encoding="utf-8",
    )


def _block(total: int, opponent: str, opponent_won: int, me_won: int, drawn: int, last: str) -> str:
    line = (
        f"Recorded tictactoe games between you and {opponent} before this one: {total}. "
        f"{opponent} won {opponent_won}, you won {me_won}, {drawn} drawn."
    )
    if last:
        line += f" Most recent: {last}."
    return "\n".join([HEADER, line, "---"])


# ── T1: the crossing ─────────────────────────────────────────────────


@_UNTIL_M2
async def test_recorded_games_reach_the_dm_prompt_as_a_head_to_head_tally(tmp_path: Path) -> None:
    """#1750 acceptance 2 (C), across every seam: the real service records the games, the agent reads
    them as itself, the tally follows the active-game block, and the manifest names the section only."""
    store = await _store(tmp_path)
    service = _service(store)
    try:
        counted = [
            await _play(service, "Captain", "Ezri", X_WINS),  # Captain wins
            await _play(service, "Ezri", "Captain", O_WINS),  # Ezri is X; Captain (O) wins
            await _play(service, "Captain", "Ezri", DRAW),
        ]
        await _play(service, "Captain", "Lyra", O_WINS)  # another pair: not counted
        await _record(store, "private-lyra", x="Captain", o="Ezri", winner="Ezri", author="Lyra", classification="private")
        await _record(store, "private-ezri", x="Captain", o="Ezri", winner="Ezri", author="Ezri", classification="private")
        await service.create_game("tictactoe", "Captain", "Ezri")  # the game in progress
        prompt, manifest = await _turn(_agent(_runtime(recreation_service=service, records_store=store)))
    finally:
        await service.turns.stop()

    paths = [f"{GAMES}/{game['game_id']}.md" for game in counted] + [f"{GAMES}/private-ezri.md"]
    dates = [str((await store.read_entry(path, "captain"))["frontmatter"]["updated"])[:10] for path in paths]
    expected = _block(4, "Captain", 2, 1, 1, max(dates))
    assert prompt.count(expected) == 1
    assert prompt.index("--- Active Game ---") < prompt.index(expected) < prompt.index("Hello Ezri")
    names = _names(manifest)
    assert names[names.index("active_game") + 1] == "head_to_head"
    assert {"name": "head_to_head", "chars": len(expected) + 1, "kept": True} in manifest["sections"]
    encoded = json.dumps(manifest)
    assert HEADER not in encoded and "Captain won" not in encoded


# ── T2, T2b: the prompt is unchanged when nothing is counted ─────────


@pytest.mark.parametrize("case", ["no-directory", "other-pairs-only", "no-store", "no-active-game"])
async def test_with_no_recorded_game_between_the_two_the_dm_prompt_is_unchanged(tmp_path: Path, case: str) -> None:
    """Nothing to count adds nothing: the prompt equals one built with no records store, and the manifest
    names no head-to-head section. Passes on the base by design (a guard, as AD-1357's T7b)."""
    store = await _store(tmp_path)
    service = _service(store)
    try:
        if case != "no-directory":
            await _play(service, "Captain", "Lyra", X_WINS)
        if case == "no-active-game":
            await _play(service, "Captain", "Ezri", X_WINS)
        else:
            await service.create_game("tictactoe", "Captain", "Ezri")
        agent = _agent(_runtime(recreation_service=service, records_store=None if case == "no-store" else store))
        prompt, manifest = await _turn(agent)
        baseline_prompt, _ = await _turn(_agent(_runtime(recreation_service=service, records_store=None)))
    finally:
        await service.turns.stop()
    assert prompt == baseline_prompt
    assert "head_to_head" not in _names(manifest)


@pytest.mark.parametrize("failing", ["list_entries", "read_entry"])
@_UNTIL_M2
async def test_a_records_read_that_fails_adds_nothing_and_logs_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, failing: str,
) -> None:
    store = await _store(tmp_path)
    service = _service(store)
    try:
        await _play(service, "Captain", "Ezri", X_WINS)
        await service.create_game("tictactoe", "Captain", "Ezri")
        broken = AsyncMock(side_effect=OSError("the file is in use"))
        setattr(store, failing, broken)
        caplog.set_level(logging.WARNING, logger="probos.recreation.history")
        prompt, manifest = await _turn(_agent(_runtime(recreation_service=service, records_store=store)))
        baseline_prompt, _ = await _turn(_agent(_runtime(recreation_service=service, records_store=None)))
    finally:
        await service.turns.stop()
    assert broken.await_count == 1  # premise: the read was attempted
    assert prompt == baseline_prompt
    assert "head_to_head" not in _names(manifest)
    assert any(
        r.levelno == logging.WARNING and r.name == "probos.recreation.history" and "AD-1358" in r.getMessage()
        for r in caplog.records
    )


# ── T3: privacy ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("reader_id", "reader_department", "expected"),
    [
        pytest.param("Ezri", "science", (1, 1, 0), id="other-department"),
        pytest.param("Ezri", "medical", (2, 1, 1), id="same-department"),
        pytest.param("", "", (1, 1, 0), id="anonymous"),
    ],
)
@_UNTIL_M2
async def test_a_record_the_reader_may_not_read_is_not_counted(
    tmp_path: Path, reader_id: str, reader_department: str, expected: tuple[int, int, int],
) -> None:
    read_head_to_head = _built("read_head_to_head")
    store = await _store(tmp_path)
    await _record(store, "ship", x="Captain", o="Ezri", winner="Captain")
    await _record(
        store, "medical", x="Captain", o="Ezri", winner="Ezri",
        author="Chapel", classification="department", department="medical",
    )
    tally = await read_head_to_head(
        store, game_type="tictactoe", me="Ezri", opponent="Captain",
        reader_id=reader_id, reader_department=reader_department,
    )
    assert (tally.total, tally.opponent_won, tally.me_won) == expected


# ── T4, T5: the parser ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("moves", "side"),
    [pytest.param(X_WINS, "x", id="x-wins"), pytest.param(O_WINS, "o", id="o-wins"), pytest.param(DRAW, "", id="draw")],
)
@_UNTIL_M2
async def test_the_writers_record_round_trips_through_the_parser(tmp_path: Path, moves: list[str], side: str) -> None:
    parse_game_record = _built("parse_game_record")
    game_outcome = _built("GameOutcome")
    store = await _store(tmp_path)
    service = _service(store)
    try:
        game = await _play(service, "Captain", "Ezri", moves)
    finally:
        await service.turns.stop()
    winner = {"x": "Captain", "o": "Ezri", "": ""}[side]
    assert game["result"]["winner"] == winner  # premise: the engine's result
    doc = await store.read_entry(f"{GAMES}/{game['game_id']}.md", "captain")
    assert parse_game_record(doc["content"]) == game_outcome("Captain", "Ezri", winner)


NOT_RECORDS = {
    "empty": "",
    "prose": "# Notes\n\nThe Captain beat Ezri twice.\n",
    "no-result": "**Players:** Captain (X) vs Ezri (O)\n",
    "winner-not-a-player": "**Players:** Captain (X) vs Ezri (O)\n**Result:** won — **Lyra** wins!\n",
    "forfeited": "**Players:** Captain (X) vs Ezri (O)\n**Result:** forfeited\n",
}


@pytest.mark.parametrize("name", list(NOT_RECORDS))
@_UNTIL_M2
async def test_a_document_that_is_not_an_ad526a_record_is_not_counted(tmp_path: Path, name: str) -> None:
    parse_game_record = _built("parse_game_record")
    read_head_to_head = _built("read_head_to_head")
    assert parse_game_record(NOT_RECORDS[name]) is None
    store = await _store(tmp_path)
    await store.write_entry(
        "system", f"{GAMES}/{name}.md", NOT_RECORDS[name] or "\n", "AD-1358 fixture", tags=["game", "tictactoe"],
    )
    assert await read_head_to_head(
        store, game_type="tictactoe", me="Ezri", opponent="Captain", reader_id="Ezri", reader_department="science",
    ) is None


# ── T6: bounds ───────────────────────────────────────────────────────


@pytest.mark.parametrize("case", ["above-cap", "at-cap", "unsafe-game-type", "strict-listing", "long-name"])
@_UNTIL_M2
async def test_the_read_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, case: str,
) -> None:
    read_head_to_head = _built("read_head_to_head")
    history = importlib.import_module("probos.recreation.history")
    store = await _store(tmp_path)
    opponent = "C" * 500 if case == "long-name" else "Captain"
    for index in range(3):
        await _record(store, f"g{index}", x=opponent, o="Ezri", winner=opponent)
    calls: dict[str, Any] = {"list": [], "read": 0}
    real_list, real_read = store.list_entries, store.read_entry

    async def list_spy(*args: Any, **kwargs: Any) -> Any:
        calls["list"].append((args, kwargs))
        return await real_list(*args, **kwargs)

    async def read_spy(*args: Any, **kwargs: Any) -> Any:
        calls["read"] += 1
        return await real_read(*args, **kwargs)

    monkeypatch.setattr(store, "list_entries", list_spy)
    monkeypatch.setattr(store, "read_entry", read_spy)
    if case in ("above-cap", "at-cap"):
        monkeypatch.setattr(history, "MAX_GAME_RECORDS", 2 if case == "above-cap" else 3)
    caplog.set_level(logging.WARNING, logger="probos.recreation.history")
    tally = await read_head_to_head(
        store, game_type="../notebooks" if case == "unsafe-game-type" else "tictactoe",
        me="Ezri", opponent=opponent, reader_id="Ezri", reader_department="science",
    )
    if case == "above-cap":
        assert tally is None and calls["read"] == 0
        assert any("AD-1358" in r.getMessage() for r in caplog.records)
    elif case == "at-cap":
        assert tally.total == 3 and calls["read"] == 3
    elif case == "unsafe-game-type":
        assert tally is None and calls["list"] == []
    elif case == "strict-listing":
        assert calls["list"] == [(("recreation/games/tictactoe",), {"tags": ["game", "tictactoe"], "strict": True})]
    else:
        text = tally.render()
        assert len(text) <= history.MAX_BLOCK_CHARS
        assert "C" * history.MAX_NAME_CHARS + " won 3" in text
        assert "C" * (history.MAX_NAME_CHARS + 1) not in text


# ── T7: the reader ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("resolved", ("Ezri", "science")),
        ("no-registry", ("", "")),
        ("no-ontology", ("", "")),
        ("unknown-agent", ("", "")),
        ("raising-registry", ("", "")),
        ("empty-id", ("", "")),
    ],
)
@_UNTIL_M2
def test_the_records_reader_is_the_agent_or_the_anonymous_reader(case: str, expected: tuple[str, str]) -> None:
    records_reader_for = getattr(oracle_service, "records_reader_for", None)
    assert callable(records_reader_for), "AD-1358 S1: records_reader_for is not built"
    runtime = _runtime()
    if case == "no-registry":
        runtime.registry = None
    if case == "no-ontology":
        runtime.ontology = None
    if case == "raising-registry":
        runtime.registry = _RaisingRegistry()
    agent_id = {"unknown-agent": "nobody", "empty-id": ""}.get(case, AGENT_ID)
    assert records_reader_for(runtime, agent_id) == expected


# ── T8, T9: perspective and date ─────────────────────────────────────


@pytest.mark.parametrize(
    ("me", "opponent", "me_won", "opponent_won"), [("Ezri", "Captain", 2, 1), ("Captain", "Ezri", 1, 2)],
)
@_UNTIL_M2
async def test_the_tally_is_told_from_the_readers_side_whichever_side_it_played(
    tmp_path: Path, me: str, opponent: str, me_won: int, opponent_won: int,
) -> None:
    read_head_to_head = _built("read_head_to_head")
    store = await _store(tmp_path)
    await _record(store, "a", x="Ezri", o="Captain", winner="Ezri")
    await _record(store, "b", x="Captain", o="Ezri", winner="Ezri")
    await _record(store, "c", x="Captain", o="Ezri", winner="Captain")
    tally = await read_head_to_head(
        store, game_type="tictactoe", me=me, opponent=opponent, reader_id="captain", reader_department="",
    )
    assert (tally.me_won, tally.opponent_won, tally.drawn) == (me_won, opponent_won, 0)
    assert tally.render().startswith(_block(3, opponent, opponent_won, me_won, 0, "").removesuffix("\n---"))


@pytest.mark.parametrize(
    ("updates", "last"),
    [
        pytest.param(["2026-04-16T10:00:00+00:00", "2026-04-24T10:00:00+00:00"], "2026-04-24", id="latest"),
        pytest.param(["not a date", "also not a date"], "", id="no-date"),
    ],
)
@_UNTIL_M2
async def test_the_most_recent_date_is_the_latest_record_and_is_left_out_when_none_parses(
    tmp_path: Path, updates: list[str], last: str,
) -> None:
    read_head_to_head = _built("read_head_to_head")
    store = await _store(tmp_path)
    for index, updated in enumerate(updates):
        _raw(store, f"dated-{index}", updated=updated)
    tally = await read_head_to_head(
        store, game_type="tictactoe", me="Ezri", opponent="Captain", reader_id="Ezri", reader_department="science",
    )
    assert tally.last_date == last
    assert tally.render() == _block(2, "Captain", 2, 0, 0, last)
