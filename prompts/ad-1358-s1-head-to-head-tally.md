# AD-1358 S1 (#1750): a crew member in a game is told the recorded games against that opponent

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-06
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-06: Amendment A1 (§15), the repair of review round 1 (GPT-6.1 Sol, NOT READY): the reads run off the event loop and the cap is checked by name before any read (HH8); the tally's game lookup logs its failure; L4, L10 and HH5 corrected; L11 to L13 added; T10 to T14 added and T6 above-cap strengthened; rows HH-18 to HH-22 added and HH-4, HH-5, HH-11 restated.
**Status:** ready to build after AD-1357 (#1749) and BF-952 (#1751) are on `main`.
**Base:** `cognitive_agent.py`, `oracle_service.py`, `dm_targeted_lookup.py`, `DECISIONS.md` (the AD-1357 entry) as on `b3348e2a` (AD-1357 + A1). The records files as on `cf61c683` (BF-952 + A2); this slice edits neither `records_store.py` nor `routers/records.py`.
**Dependencies:** AD-1357 (the DM bid ledger and manifest). Not BF-952: no keyword search is used.
**Tier:** M1 STANDARD (tests only); M2 STANDARD with a shared contract (`records_reader_for`, BF-949's reader rule, now public); M3 STANDARD (trackers).
**Estimated tests:** one new file, `tests/test_ad1358_s1_head_to_head.py`: 10 functions, 33 cases; after A1, 15 functions, 38 cases. Counted by reading, not by running. No existing test file is edited.
**AD number:** AD-1358, held by #1750. Nothing new is allocated.

**Which text describes the head.** Before building, run `git diff --stat b3348e2a HEAD -- src/probos/cognitive/cognitive_agent.py src/probos/cognitive/oracle_service.py src/probos/cognitive/dm_targeted_lookup.py src/probos/recreation/`. Any change other than BF-952's merge (which touches none of these files) is a hard stop: the SEARCH text goes back to the Architect. Working copies are CRLF and SEARCH text here is LF. Where prose and a block differ, the block wins.

## 1. Problem

1. On 2026-11-04 Ezri volunteered "Last time you beat me twice" during an active game. Nothing in her prompt supported or refuted it.
2. The DM active-game block (`cognitive_agent.py:8566-8614`, emitted at `:10825-10828`) gives the board and whose turn it is. It gives no history.
3. The facts exist. `RecreationService._record_game` (`recreation/service.py:346-386`) writes one ship-classified record per finished game at `recreation/games/<type>/<game_id>.md`, tagged `["game", <type>]`, author `system`. The players and result are only in its body:
   - `**Players:** A (X) vs B (O)`
   - `**Result:** won — **A** wins!` or `**Result:** draw`
   - The format is unchanged since `41345697` (2026-04-05).
4. Only a text search could reach them, and #1751 shows the passive query cannot rank them.

## 2. Solution

1. **New module `recreation/history.py`.**
   - `parse_game_record(content)` reads the AD-526a body form.
   - `read_head_to_head(store, *, game_type, me, opponent, reader_id, reader_department)` returns a frozen `HeadToHead`, or `None`.
   - `HeadToHead.render()` returns the block.
2. **`CognitiveAgent._build_head_to_head_context()`** (async) runs after the `active_game` bid. It resolves the reader with `oracle_service.records_reader_for(runtime, self.id)` and emits a bid named `head_to_head`.
3. **`oracle_service.records_reader_for`** is the body of `dm_targeted_lookup._knowledge_lookup_reader` made public. The old function delegates to it, so its behaviour is unchanged.
4. **Unchanged:** the prompt whenever nothing is counted, `records_store.py`, `RecreationService`, `context_manifest.py`, config.

## 3. Decisions

HH1 to HH7 as in the consult answer of 2026-11-06 (summary):
- **HH1:** the new module plus an agent method. Rejected: a `RecreationService` method (its 16th; the SRP check fails above 15); doing it inside the synchronous `_build_active_game_context`.
- **HH2:** a strict tag-filtered `list_entries`, then `read_entry` per path, then a body parse. A frontmatter lookup is impossible: the record's frontmatter holds no players or result.
- **HH3:** one line, for the active game's type and opponent only. Zero games means no block. Size ≤ `MAX_BLOCK_CHARS`.
- **HH4:** the agent reads as itself (`records_reader_for`, BF-949). A record `read_entry` returns `None` for is not counted.
- **HH5:** a count by name, then one listing plus at most 256 `read_entry` calls per DM turn during a game, all in a worker thread (A1, HH8). Above the cap: no listing, no entry reads, no block, a WARNING.
- **HH6:** any exception means `None` plus a WARNING with `exc_info`; the prompt is unchanged.
- **HH7:** the manifest records the section `head_to_head` by name, length and kept flag only.
- **Flag:** none. The block appears only when at least one recorded game between these two players exists during an active game, so the default preserves behaviour (T2).

## 4. Milestones and gates

| M | Pairs | Gate |
|---|---|---|
| M1 | N1-1 | G1 |
| M2 | N2-1, P2-1 to P2-8, P2-9 (the test markers) | G2 |
| M3 | P3-1, P3-2, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`.

- **M0:** on the base, record the collected count of every existing file named in G2.
- **G1:** `PY -m pytest tests/test_ad1358_s1_head_to_head.py -q -n 0`.
  - Expected: **4 passed (T2 ×4), 29 xfailed.**
  - Each xfailed case fails at an `AssertionError` (the marker has `raises=AssertionError`, so any other exception is a FAIL). Any other count is a hard stop.
- **G2:** `PY -m pytest tests/test_ad1358_s1_head_to_head.py tests/test_cognitive_agent_dm_game.py tests/test_ad1028_context_assembler.py tests/test_ad1029_attention_faculty.py tests/test_ad1357_context_manifest.py tests/test_ad723_sensorium_dispatch.py tests/test_ad723a_1_consumer_migration.py tests/test_ad666_sensorium.py tests/test_ad588_telemetry_introspection.py tests/test_recreation_service.py tests/test_recreation_get_game_by_player.py tests/test_records_store.py tests/test_bf949_notebook_reader_identity.py tests/test_ad725_dm_targeted_lookup.py tests/test_bf679_oracle_records_reader_identity.py tests/test_bf950_oracle_result_age.py tests/test_layer_boundaries.py tests/test_ad1065_conversational_agentic.py tests/test_ad914_group_chat_fanout.py -q -n 0`, then `PY -P scripts/check_architecture_principles.py --check`.
  - Expected: **33 passed** in the new file. Others: 0 failed, with counts equal to M0.
  - Hard stop: `test_dm_golden_byte_identical` failing (the golden runtime is `None`, `_capture_golden.py:50`, so this slice must not touch it).
- **G3:** `PY -P scripts/gen_ad_ledger.py`; `PY -P scripts/gen_ad_ledger.py --check`; `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **Harness rule (G1, G2).** The tests drive real `_recall_relevant_memories` and `_decide_via_llm` with a `SimpleNamespace` runtime.
  - Allowed: if a test fails only because the runtime, its `registry` or its `ontology` lacks something the DM path reads, the Builder may add it as `None` or as an inert method returning `None`, and must report which.
  - Not allowed: a source change, a skip, a `MagicMock` runtime, or a loosened assertion. Any of those goes back to the Architect.
- The broad gate runs once, in the main session with `--receipt`, after the review repairs.

## 5. Commit messages

- M1: `AD-1358 S1 M1: tests for the head-to-head tally from the game records, xfail until built`
- M2: `AD-1358 S1 M2: a crew member in a game is told the recorded games against that opponent`
- M3: `AD-1358 S1 M3: trackers and ledger`

## 6. Tests (`tests/test_ad1358_s1_head_to_head.py`)

| Id | Test | Cases | Covers | xfail until |
|---|---|---|---|---|
| T1 | `test_recorded_games_reach_the_dm_prompt_as_a_head_to_head_tally` | 1 | #1750 acceptance 2: real service → records → agent reading as itself → prompt → manifest | M2 |
| T2 | `test_with_no_recorded_game_between_the_two_the_dm_prompt_is_unchanged` | 4 | byte-identical default (a guard; passes on the base) | none |
| T2b | `test_a_records_read_that_fails_adds_nothing_and_logs_a_warning` | 2 | HH6 | M2 |
| T3 | `test_a_record_the_reader_may_not_read_is_not_counted` | 3 | HH4 | M2 |
| T4 | `test_the_writers_record_round_trips_through_the_parser` | 3 | writer ↔ parser | M2 |
| T5 | `test_a_document_that_is_not_an_ad526a_record_is_not_counted` | 5 | parser strictness | M2 |
| T6 | `test_the_read_is_bounded` | 5 | HH5, HH3 size, path safety, strict listing | M2 |
| T7 | `test_the_records_reader_is_the_agent_or_the_anonymous_reader` | 6 | `records_reader_for` | M2 |
| T8 | `test_the_tally_is_told_from_the_readers_side_whichever_side_it_played` | 2 | perspective | M2 |
| T9 | `test_the_most_recent_date_is_the_latest_record_and_is_left_out_when_none_parses` | 2 | date | M2 |

## 7. The contract

### 7.1 M1

**N1-1** `tests/test_ad1358_s1_head_to_head.py` (new)

```python
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
```

The em dash in `_record`, `_raw` and `NOT_RECORDS` is U+2014, as in `service.py:363`. The file is UTF-8.

### 7.2 M2

**N2-1** `src/probos/recreation/history.py` (new)

```python
"""AD-1358 S1 (#1750): the recorded games between two players, from the AD-526a game records.

``RecreationService._record_game`` writes one Ship's Records document per finished game, at
``recreation/games/<game_type>/<game_id>.md``, tagged ``game`` and the game type. Its
frontmatter names no players and no result; its body does, in a fixed form:
``**Players:** A (X) vs B (O)``, then ``**Result:** won — **A** wins!`` or ``**Result:** draw``.
:func:`parse_game_record` reads that form, and the AD-1358 tests round-trip the writer's own
output through it, so the two cannot drift apart.

:func:`read_head_to_head` reads one game type's records as one reader, through
``RecordsStore.list_entries`` and ``RecordsStore.read_entry``, so a record that reader may not
read is not counted. It returns ``None`` when no game between the two players is recorded,
when more than :data:`MAX_GAME_RECORDS` records of the type are listed, and on any failure.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Final

from probos.cognitive.provenance import iso_utc, record_write_time

logger = logging.getLogger(__name__)

#: The most records of one game type read for one tally. Above it no tally is shown:
#: a count of some of the records would be a wrong count.
MAX_GAME_RECORDS: Final = 256
#: The longest player name the block repeats.
MAX_NAME_CHARS: Final = 64
#: The longest block :meth:`HeadToHead.render` can return, by construction.
MAX_BLOCK_CHARS: Final = 400
HEADER: Final = "--- Previous Games (Ship's Records) ---"

_GAME_TYPE = re.compile(r"[a-z0-9_]{1,32}")
_PLAYERS = re.compile(r"^\*\*Players:\*\* (.+?) \(X\) vs (.+?) \(O\)$", re.MULTILINE)
_RESULT = re.compile(r"^\*\*Result:\*\* (won|draw)(?: — \*\*(.+?)\*\* wins!)?$", re.MULTILINE)


@dataclass(frozen=True)
class GameOutcome:
    """One finished game, as its AD-526a record states it."""

    x_player: str
    o_player: str
    winner: str  # "" for a draw


@dataclass(frozen=True)
class HeadToHead:
    """The recorded games of one type between the reader and ``opponent``, from the reader's side."""

    game_type: str
    opponent: str
    me_won: int
    opponent_won: int
    drawn: int
    last_date: str  # "YYYY-MM-DD" (UTC) of the latest counted record, or "" when none has a date

    @property
    def total(self) -> int:
        return self.me_won + self.opponent_won + self.drawn

    def render(self) -> str:
        """The prompt block: the header, one line, the closing rule."""
        name = self.opponent[:MAX_NAME_CHARS]
        line = (
            f"Recorded {self.game_type} games between you and {name} before this one: {self.total}. "
            f"{name} won {self.opponent_won}, you won {self.me_won}, {self.drawn} drawn."
        )
        if self.last_date:
            line += f" Most recent: {self.last_date}."
        return "\n".join([HEADER, line, "---"])


def parse_game_record(content: Any) -> GameOutcome | None:
    """The players and result of an AD-526a game record's body, or ``None`` when it is not one."""
    if type(content) is not str:
        return None
    players = _PLAYERS.search(content)
    result = _RESULT.search(content)
    if players is None or result is None:
        return None
    x_player, o_player = players.group(1), players.group(2)
    status, winner = result.group(1), result.group(2) or ""
    if status == "draw":
        return GameOutcome(x_player, o_player, "") if not winner else None
    if winner not in (x_player, o_player):
        return None
    return GameOutcome(x_player, o_player, winner)


async def read_head_to_head(
    records_store: Any,
    *,
    game_type: str,
    me: str,
    opponent: str,
    reader_id: str,
    reader_department: str,
) -> HeadToHead | None:
    """The recorded ``game_type`` games between ``me`` and ``opponent``, read as one reader.

    One strict listing of ``recreation/games/<game_type>/`` (a file that cannot be read fails the
    read rather than going uncounted), then at most :data:`MAX_GAME_RECORDS` ``read_entry`` calls
    as ``reader_id``/``reader_department``: a record that reader may not read is not counted.
    ``None`` when nothing is recorded, above the cap, and on any failure.
    """
    if records_store is None or type(me) is not str or type(opponent) is not str:
        return None
    if not me or not opponent or me == opponent:
        return None
    if type(game_type) is not str or _GAME_TYPE.fullmatch(game_type) is None:
        return None
    me_won = opponent_won = drawn = 0
    latest: float | None = None
    try:
        listed = await records_store.list_entries(
            f"recreation/games/{game_type}", tags=["game", game_type], strict=True,
        )
        if len(listed) > MAX_GAME_RECORDS:
            logger.warning(
                "AD-1358: %d %s game records exceed the head-to-head cap of %d; no tally is shown",
                len(listed), game_type, MAX_GAME_RECORDS,
            )
            return None
        for entry in listed:
            doc = await records_store.read_entry(
                entry["path"], reader_id=reader_id, reader_department=reader_department,
            )
            if doc is None:
                continue
            outcome = parse_game_record(doc.get("content"))
            if outcome is None or {outcome.x_player, outcome.o_player} != {me, opponent}:
                continue
            if outcome.winner == me:
                me_won += 1
            elif outcome.winner == opponent:
                opponent_won += 1
            else:
                drawn += 1
            written = record_write_time(doc.get("frontmatter"))
            if written is not None and (latest is None or written > latest):
                latest = written
    except Exception:
        logger.warning(
            "AD-1358: the %s game records could not be read for a head-to-head tally; none is shown",
            game_type, exc_info=True,
        )
        return None
    if me_won + opponent_won + drawn == 0:
        return None
    return HeadToHead(
        game_type=game_type,
        opponent=opponent,
        me_won=me_won,
        opponent_won=opponent_won,
        drawn=drawn,
        last_date=iso_utc(latest)[:10] if latest is not None else "",
    )
```

**P2-1** `src/probos/cognitive/cognitive_agent.py` (SEARCH once: line 32 is the only `from probos.recreation.turns import`)

SEARCH:
```
from probos.dm_reply import ToolInvocations  # AD-1295 (#1087)
from probos.recreation.turns import RecreationTurnClaim, RecreationTurnOperations
from probos.substrate.agent import BaseAgent
```
REPLACE:
```
from probos.dm_reply import ToolInvocations  # AD-1295 (#1087)
from probos.recreation import history as game_history  # AD-1358 S1
from probos.recreation.turns import RecreationTurnClaim, RecreationTurnOperations
from probos.substrate.agent import BaseAgent
```

**P2-2** `cognitive_agent.py` (SEARCH once: `"_build_active_game_context": SensoriumEntry(` occurs only at `:1318`)

SEARCH:
```
        "_build_active_game_context": SensoriumEntry(
            layer=SensoriumLayer.EXTEROCEPTION,
            description="Active game board state (inventory; DM-side rendered inline; AD-723a-1)",
        ),
```
REPLACE:
```
        "_build_active_game_context": SensoriumEntry(
            layer=SensoriumLayer.EXTEROCEPTION,
            description="Active game board state (inventory; DM-side rendered inline; AD-723a-1)",
        ),
        "_build_head_to_head_context": SensoriumEntry(
            layer=SensoriumLayer.EXTEROCEPTION,
            description="Recorded games against the active game's opponent (inventory; DM-side rendered inline; AD-1358 S1)",
        ),
```

**P2-3** `cognitive_agent.py` (SEARCH once: `def _summarize_action(` occurs only at `:8616`)

SEARCH:
```
            else:
                lines.append("Waiting for your opponent to move.")
            return "\n".join(lines)
        except Exception:
            return None

    def _summarize_action(self, intent, decision: dict, result: dict) -> str:
```
REPLACE:
```
            else:
                lines.append("Waiting for your opponent to move.")
            return "\n".join(lines)
        except Exception:
            return None

    async def _build_head_to_head_context(self) -> str | None:
        """AD-1358 S1 (#1750): the recorded games against the active game's opponent.

        Counted from the AD-526a game records in Ship's Records, read as this agent
        (``records_reader_for``, BF-949's reader), so a record it may not read is not
        counted. ``None`` with no active game, no records store or nothing recorded, and
        on any failure: the prompt is then as before. The Oracle module is imported here,
        not at module scope, as its import pulls in the knowledge package.
        """
        from probos.cognitive.oracle_service import records_reader_for

        rt = getattr(self, '_runtime', None)
        if not rt:
            return None
        rec_svc = getattr(rt, 'recreation_service', None)
        store = getattr(rt, 'records_store', None)
        callsign = self._resolve_callsign()
        if not rec_svc or store is None or not callsign:
            return None
        try:
            game = rec_svc.get_game_by_player(callsign)
        except Exception:
            return None
        if type(game) is not dict:
            return None
        opponent = next(
            (p for p in (game.get("challenger", ""), game.get("opponent", "")) if p != callsign),
            "",
        )
        reader_id, reader_department = records_reader_for(rt, self.id)
        tally = await game_history.read_head_to_head(
            store,
            game_type=game.get("game_type", ""),
            me=callsign,
            opponent=opponent,
            reader_id=reader_id,
            reader_department=reader_department,
        )
        return tally.render() if tally is not None else None

    def _summarize_action(self, intent, decision: dict, result: dict) -> str:
```

**P2-4** `cognitive_agent.py` (SEARCH once: `:10559`)

SEARCH:
```
        attribution, session history, active game context, then Captain message.
```
REPLACE:
```
        attribution, session history, active game context, the head-to-head record (AD-1358), then Captain message.
```

**P2-5** `cognitive_agent.py` (SEARCH once: `_emit("active_game"` occurs only at `:10828`)

SEARCH:
```
            # AD-572: Active game state awareness in DM path
            active_game_ctx = self._build_active_game_context()
            if active_game_ctx:
                _emit("active_game", [active_game_ctx, ""])

            _emit("captain_message", [self._format_direct_message_trigger(params)])
```
REPLACE:
```
            # AD-572: Active game state awareness in DM path
            active_game_ctx = self._build_active_game_context()
            if active_game_ctx:
                _emit("active_game", [active_game_ctx, ""])
                # AD-1358 S1 (#1750): the recorded games against this opponent, from the
                # AD-526a game records; nothing is added when none is recorded.
                head_to_head_ctx = await self._build_head_to_head_context()
                if head_to_head_ctx:
                    _emit("head_to_head", [head_to_head_ctx, ""])

            _emit("captain_message", [self._format_direct_message_trigger(params)])
```

**P2-6** `src/probos/cognitive/oracle_service.py` (SEARCH once: `def _decode_record_frontmatter` occurs only at `:137`)

SEARCH:
```
        return callsign, department

    return _resolve


def _decode_record_frontmatter(raw: Any) -> dict[str, Any]:
```
REPLACE:
```
        return callsign, department

    return _resolve


def records_reader_for(runtime: Any, agent_id: str) -> tuple[str, str]:
    """BF-949, AD-1358: the Ship's Records reader an agent reads as.

    The agent resolved as the Oracle resolves its callers (``make_reader_identity_resolver``):
    its callsign and its ontology department. A runtime without a registry or an ontology, an
    agent id that is empty or not a string, an agent the resolver does not find, and a resolver
    that raises all give ``("", "")``, BF-679's anonymous reader (``record_is_readable``).
    """
    registry = getattr(runtime, "registry", None)
    ontology = getattr(runtime, "ontology", None)
    if registry is None or ontology is None or type(agent_id) is not str or not agent_id:
        return "", ""
    try:
        return make_reader_identity_resolver(registry=registry, ontology=ontology)(agent_id)
    except Exception:
        logger.warning(
            "BF-949: records reader resolution failed for agent=%s; Ship's Records "
            "are read as the anonymous reader",
            agent_id, exc_info=True,
        )
        return "", ""


def _decode_record_frontmatter(raw: Any) -> dict[str, Any]:
```

**P2-7** `src/probos/cognitive/dm_targeted_lookup.py` (SEARCH once: `:20`)

SEARCH:
```
from probos.cognitive.oracle_service import make_reader_identity_resolver
```
REPLACE:
```
from probos.cognitive.oracle_service import records_reader_for
```

**P2-8** `dm_targeted_lookup.py` (SEARCH once: `:103-124`)

SEARCH:
```
def _knowledge_lookup_reader(runtime: Any, agent_id: str) -> tuple[str, str]:
    """BF-949: the Ship's Records reader the knowledge lookup reads as.

    The agent the DM is addressed to, resolved as the Oracle resolves its callers
    (``make_reader_identity_resolver``): its callsign and its ontology department.
    A runtime without a registry or an ontology, an agent id that is empty or not
    a string, an agent the resolver does not find, and a resolver that raises all
    give ``("", "")``, BF-679's anonymous reader (``record_is_readable``).
    """
    registry = getattr(runtime, "registry", None)
    ontology = getattr(runtime, "ontology", None)
    if registry is None or ontology is None or type(agent_id) is not str or not agent_id:
        return "", ""
    try:
        return make_reader_identity_resolver(registry=registry, ontology=ontology)(agent_id)
    except Exception:
        logger.warning(
            "BF-949: records reader resolution failed for agent=%s; the knowledge "
            "lookup reads as the anonymous reader",
            agent_id, exc_info=True,
        )
        return "", ""
```
REPLACE:
```
def _knowledge_lookup_reader(runtime: Any, agent_id: str) -> tuple[str, str]:
    """BF-949: the Ship's Records reader the knowledge lookup reads as.

    The agent the DM is addressed to: :func:`probos.cognitive.oracle_service.records_reader_for`,
    which AD-1358 S1 made public so the DM head-to-head tally reads by the same rule.
    """
    return records_reader_for(runtime, agent_id)
```

**P2-9** `tests/test_ad1358_s1_head_to_head.py`: remove the markers. Each SEARCH is `@_UNTIL_M2` + newline + the def line below, and occurs once, because each def name is unique. REPLACE is the def line alone. The nine def lines:
1. `async def test_recorded_games_reach_the_dm_prompt_as_a_head_to_head_tally(tmp_path: Path) -> None:`
2. `async def test_a_records_read_that_fails_adds_nothing_and_logs_a_warning(`
3. `async def test_a_record_the_reader_may_not_read_is_not_counted(`
4. `async def test_the_writers_record_round_trips_through_the_parser(tmp_path: Path, moves: list[str], side: str) -> None:`
5. `async def test_a_document_that_is_not_an_ad526a_record_is_not_counted(tmp_path: Path, name: str) -> None:`
6. `async def test_the_read_is_bounded(`
7. `def test_the_records_reader_is_the_agent_or_the_anonymous_reader(case: str, expected: tuple[str, str]) -> None:`
8. `async def test_the_tally_is_told_from_the_readers_side_whichever_side_it_played(`
9. `async def test_the_most_recent_date_is_the_latest_record_and_is_left_out_when_none_parses(`

Then delete the definition: SEARCH `_UNTIL_M2 = pytest.mark.xfail(strict=True, raises=AssertionError, reason="AD-1358 S1: built in M2")` + newline + blank line, REPLACE empty. After this, `rg -n "_UNTIL_M2" tests/test_ad1358_s1_head_to_head.py` must return nothing.

### 7.3 M3: tracking

**Head constraint:** neither head may carry a lifecycle keyword from `gen_ad_ledger.py` `_STATUS_PATTERNS` (`:126-132`) in its first 120 characters.
**Date rule:** both heads use M3's commit date; 2026-11-06 is shown below.
**Staging:** explicit paths only.
**Re-anchoring:** P3-1 goes directly under the title. P3-2 anchors on the AD-1357 entry's last line (`DECISIONS.md:1454` on `b3348e2a`). These are the only re-anchorings allowed.

**P3-1** `PROGRESS.md`

SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1358 S1 (2026-11-06), #1750 -- a crew member in a game is told the recorded games against that opponent.** During an active game, a crew `direct_message` prompt carries, directly after the AD-572 active-game block, a head-to-head block counted from the AD-526a game records in Ship's Records (`recreation/games/<game_type>/`): the number of recorded games of that type between the agent and its opponent, how many each won, the draws, and the UTC date of the latest (`recreation/history.py`). The records are read as the agent (`oracle_service.records_reader_for`, BF-949's reader, which `dm_targeted_lookup._knowledge_lookup_reader` now delegates to), so a record it may not read is not counted. With no game recorded between the two, no records store, more than 256 records of the type, or a read that fails, nothing is added and the prompt is as before. The AD-1357 manifest names the section `head_to_head` by its length only. No config field. The contract is `prompts/ad-1358-s1-head-to-head-tally.md`. S2 (a claimed lookup checked against the turn's tool trace) and S3 (claims about shared history, with the BF-741 check) follow.

```

**P3-2** `DECISIONS.md`

SEARCH:
```
- *Reversal.* Revert the AD-1357 commits.

```
REPLACE:
```
- *Reversal.* Revert the AD-1357 commits.

### AD-1358 S1 -- A crew member in a game is told the recorded games against that opponent (2026-11-06, #1750)

- *Scope.* `recreation/history.py` (new: `parse_game_record`, `GameOutcome`, `HeadToHead`, `read_head_to_head`), `cognitive/cognitive_agent.py` (`_build_head_to_head_context`, the `head_to_head` DM bid after `active_game`, its inventory entry), `cognitive/oracle_service.py` (`records_reader_for`, public), `cognitive/dm_targeted_lookup.py` (`_knowledge_lookup_reader` delegates), tests. Contract `prompts/ad-1358-s1-head-to-head-tally.md`.
- *HH1 (where).* A new module beside the record's writer, so a round-trip test pins writer and parser together. Rejected: a `RecreationService` method (its 16th, over the SRP trigger); inside the synchronous `_build_active_game_context`.
- *HH2 (read).* A strict, tag-filtered `list_entries` of one game-type directory, then `read_entry` per record and a parse of the body: the record's frontmatter holds no players or result. Rejected: a frontmatter lookup (impossible for existing records); a new store API.
- *HH3 (what).* One line for the active game's type and opponent: the total, wins each, draws, latest UTC date. Zero games gives no block.
- *HH4 (privacy).* Read as the agent through BF-949's rule, now `records_reader_for`; a record `read_entry` withholds is not counted.
- *HH5 (cost).* One listing plus at most 256 entry reads per DM turn during a game; above the cap, none, no block and a warning.
- *HH6 (failure).* Log-and-degrade: any failure gives no block and a warning; the prompt is unchanged.
- *Not changed.* `records_store.py`, `RecreationService`, the AD-526a record format, `context_manifest.py`, the Ward Room chain's game context, config.
- *Residual.* Recorded limits L1 to L10 of the contract.
- *Reversal.* Revert the AD-1358 S1 commits.

```

Then run `PY -P scripts/gen_ad_ledger.py` and stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as written. **Not updated:** `docs/development/roadmap.md`.

## 8. What this does NOT change

- `knowledge/records_store.py`, `routers/records.py` (BF-952's files), `RecreationService` and the AD-526a record format.
- `context_manifest.py`, `ContextAssembler`, `AttentionFaculty` and the AD-1028 golden (its runtime is `None`).
- The Ward Room chain's active-game situation (`_sensorium_situation_active_game`, `:9734`) and `proactive.py:2366`.
- No config field, no `EventType`, no `create_task`, no database connection.

## 9. Mutation rows (each Line occurs once in its file on M2's head; after A1, on A1-M2's head, with §15.6)

| Id | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| HH-1 | cognitive_agent.py | `                if head_to_head_ctx:` | `                if False:` | T1 |
| HH-2 | cognitive_agent.py | `                    _emit("head_to_head", [head_to_head_ctx, ""])` | `_emit("active_game", …)` | T1 (manifest order) |
| HH-3 | cognitive_agent.py | `        reader_id, reader_department = records_reader_for(rt, self.id)` | `        reader_id, reader_department = "captain", ""` | T1 (Lyra's private counted: 5) |
| HH-4 | history.py | `        if len(listed) > MAX_GAME_RECORDS:` | `>=` | T6 at-cap |
| HH-5 | history.py | `                entry["path"], reader_id=reader_id, reader_department=reader_department,` | `entry["path"], reader_id="captain", reader_department="",` | T3 other-department, T3 anonymous |
| HH-6 | history.py | `            if outcome is None or {outcome.x_player, outcome.o_player} != {me, opponent}:` | `            if outcome is None or opponent not in (outcome.x_player, outcome.o_player):` | T1 (Lyra game counted as a draw) |
| HH-7 | history.py | `            if outcome.winner == me:` | `            if outcome.winner == opponent:` | T8 |
| HH-8 | history.py | `                drawn += 1` | `                opponent_won += 1` | T1 |
| HH-9 | history.py | `            if written is not None and (latest is None or written > latest):` | `<` | T9 latest |
| HH-10 | history.py | `    if type(game_type) is not str or _GAME_TYPE.fullmatch(game_type) is None:` | `    if type(game_type) is not str:` | T6 unsafe-game-type |
| HH-11 | history.py | `            f"recreation/games/{game_type}", tags=["game", game_type], strict=True,` | `strict=False` | T6 strict-listing |
| HH-12 | history.py | `    if me_won + opponent_won + drawn == 0:` | `    if False:` | T2 other-pairs-only |
| HH-13 | history.py | `    if winner not in (x_player, o_player):` | `    if False:` | T5 winner-not-a-player |
| HH-14 | history.py | `    except Exception:` | `    except KeyError:` | T2b ×2 |
| HH-15 | history.py | `        name = self.opponent[:MAX_NAME_CHARS]` | `        name = self.opponent` | T6 long-name |
| HH-16 | history.py | `            line += f" Most recent: {self.last_date}."` | `            pass` | T9 latest, T1 |
| HH-17 | oracle_service.py | `        return make_reader_identity_resolver(registry=registry, ontology=ontology)(agent_id)` | `        return agent_id, ""` | T7 resolved |

No campaign of record yet; after A1, the campaign of record runs on A1-M2's head (§15.6).

## 10. Recorded limits

- **L1.** DM path only. The Ward Room chain and proactive game context are unchanged.
- **L2.** Forfeits are not recorded by AD-526a (`forfeit_game`, `service.py:321-344`), so they are not counted.
- **L3.** Players match by the exact callsign in the record. Games played before a callsign change are not matched.
- **L4.** No cache. Each DM turn during a game counts the directory's `*.md` files by name (no read). At most 256, it lists them (each file read and parsed) and reads each again with `read_entry`: up to 512 file reads, in a worker thread, which the DM turn waits for (A1). Above 256 `*.md` files in the directory, game records or not, no tally is shown and none is read. The remedy, structured frontmatter on new records plus an index, is considered and deferred.
- **L5.** Dates are UTC (`updated`, else `created`, by BF-950's `record_write_time`).
- **L6.** Zero games gives no block. Stating the absence is S3's job.
- **L7.** `read_entry`'s department rule (an empty department matches an empty one) is inherited, as for the agent's own reads.
- **L8.** A document that does not match the AD-526a body form is not counted, and nothing is logged.
- **L9.** `_build_head_to_head_context` repeats `_build_active_game_context`'s opponent expression (default `""` there, `"unknown"` in AD-572); AD-572 is not refactored.
- **L10.** A group-chat DM turn shows the block too, as it shows the active-game block. The tally counts every record the agent whose prompt it is may read (HH4), its own private records and its department's records included; `_record_game` writes ship-classified records, so another classification arises only when a record is rewritten through the store. The other participants see that agent's reply, so a count that includes such a record can reach them through it, as any other content of its prompt can. A group-turn restriction to ship-classified records would apply to every DM-side read; considered, deferred.
- **L11.** A file the store's strict listing skips is not counted, and AD-1358 logs nothing for it: bytes that are not UTF-8 (the store's rule, "a property of the file, not of the moment") and a frontmatter whose YAML constructor raises. A frontmatter YAML rejects reads as `{}` without the game tags, so it is not listed. A listed file that is gone, or that `read_entry` withholds, reads as `None` and is not counted. Only a listing or read that raises fails the tally.
- **L12.** `HeadToHead` built directly is not validated; `MAX_BLOCK_CHARS` bounds only a tally `read_head_to_head` returns (at most 317 characters).
- **L13.** The worker may read while the event loop writes a record (`write_entry` rewrites the file in place). A record read mid-write may parse as no record and go uncounted for that turn, as in BF-952's search walk.

## 11. Verified Against Codebase (2026-11-06)

See the Verified block in the consult answer; it is copied here unchanged when the file is saved.

## 12. Prior Art and Blind Spots

- **LoCoMo (Maharana et al., ACL 2024).** Its adversarial questions ask about events that never happened; long-context models do poorly on them. Absorbed into S3, not S1: S3's test set includes such non-events. [emergentmind](https://www.emergentmind.com/topics/locomo), [arXiv 2402.17753](https://ar5iv.labs.arxiv.org/html/2402.17753).
- **LoCoMo-Plus (arXiv 2602.10715).** Implicit-constraint recall. Considered, deferred (S3). [arXiv](https://arxiv.org/html/2602.10715)
- **Memori / PersonaTree.** Provenance-linked facts (claim → evidence). Adapted: the tally is a deterministic fact from the objective record. Record paths are kept out of the prompt for size; S3 may use support paths. [emergentmind Memori](https://www.emergentmind.com/topics/memori), [PersonaTree](https://www.alphaxiv.org/abs/2606.04780v1)
- **RAGFlow** (overdue). Considered, deferred: it is not relevant to a directory tally.
- **Blind spots handled:** forfeits (L2), renamed callsigns (L3), the swallowed record write (why zero shows nothing), Windows CRLF (`read_text` normalises it), chess (same `won`/`draw` statuses, `chess_engine.py:579-591`).

## 13. Diff Reviewer: properties to verify

1. With no active game, no records store, no recorded game between the pair, more than the cap, or any read failure, the DM prompt is byte-identical to the one built with no records store, and the manifest lists no `head_to_head` section.
2. Every counted record came back from `read_entry` called with `records_reader_for(runtime, self.id)`'s identity, never a hard-coded reader. A `None` read is never counted.
3. Every path through `records_reader_for` that does not resolve returns `("", "")`. `_knowledge_lookup_reader` gives the same output as before for every input.
4. The parser accepts the body `_record_game` writes for a win by either side and for a draw, and rejects a winner who is not a player.
5. The listing is strict, covers one directory and is tag-filtered. There are at most `MAX_GAME_RECORDS` `read_entry` calls. Above the cap (counted by name), there is no listing and no `read_entry`.
10. (A1) No `RecordsStore` file read or YAML parse of the tally runs on the event-loop thread; the store is reached only through `list_entries`, `read_entry` and the `repo_path` property.
11. (A1) `RecordsStore.list_entries` and `read_entry`, run in a worker, touch no mutable store state; a store read that suspends fails closed (WARNING, no tally).
6. The `head_to_head` bid is emitted only after an `active_game` bid and before `captain_message`. The manifest holds its name, length and kept flag only.
7. `game_type` is validated before it forms a path.
8. Failure is log-and-degrade (WARNING with `exc_info`). `CancelledError` is not swallowed.
9. `RecreationService` and `RecordsStore` gain no method. No new config field, `EventType`, `create_task` or database connection.

## 14. Acceptance criteria

- G1, G2 and G3 as expected. #1750 acceptance 2 (first half) is met by T1.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Amendment A1 (2026-11-06): review round 1 (GPT-6.1 Sol, NOT READY)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-06. **Anchors:** candidate head `baea653d` (base `48ed13bf`). Every SEARCH below occurs exactly once in its file on `baea653d` (§15.9). Working copies are CRLF; SEARCH text is LF. Where §15 and §7 differ, §15 wins.

### 15.1 Findings and decisions

| # | Finding | Decision |
|---|---|---|
| F1 | The tally's listing and reads run synchronously on the event loop; the listing reads every file before the cap is checked | **HH8:** the reads run in a worker thread (`asyncio.to_thread`), which drives the store's own `list_entries` and `read_entry` coroutines with no event loop (`_drive`; they await nothing). Before any read, the directory's `*.md` files are counted by name (`RecordsStore.repo_path`, public); above `MAX_GAME_RECORDS`, nothing is listed or read. The check after the listing stays. `RecordsStore` is unchanged (13.9 holds). |
| F2 | L10 says the group-turn records are ship-classified | L10 corrected: the agent's own private and department records are counted (HH4) |
| F3 | A file that is not UTF-8 is skipped by the strict listing, so the claim "a read that fails fails the tally" is false | Claims narrowed (docstring, PROGRESS, DECISIONS); L11; T13 guards the recorded limit |
| F4 | The tally's own `get_game_by_player` swallows silently | WARNING with `exc_info` (HH6); `_build_active_game_context` (AD-572) unchanged |
| F5 | `MAX_BLOCK_CHARS` "by construction" is false for a `HeadToHead` built directly | Comment narrowed to tallies `read_head_to_head` builds; L12 |

**Rejected for F1:** a `RecordsStore` method (a shared contract; deferred with L4's index); offloading without the count (the cost above the cap is unbounded); yielding between reads (the listing is one blocking call); `asyncio.run` in the worker (a new event loop per tally, with a loopback socket pair on Windows).

### 15.2 Milestones and gates

| M | Pairs | Gate |
|---|---|---|
| A1-M1 (tests) | A1-T1 to A1-T4 | GA1a on `baea653d` + A1-M1 |
| A1-M2 (source) | A1-S1 to A1-S7 | GA1b, then the campaign (§15.6), then B (§15.7) |
| A1-M3 (trackers, contract, ledger) | A1-P1, A1-P2, C-01 to C-08 (§15.8), ledger | G3 |

Commit A1-M1 and A1-M2 as one commit (`AD-1358 S1 A1: the tally reads off the event loop; review round 1 repairs (#1750)`), so no commit carries a failing test. Commit A1-M3 separately (`AD-1358 S1 A1: trackers, contract and ledger (#1750)`).

- **GA1a** (A1-M1 applied, source still `baea653d`): `PY -m pytest tests/test_ad1358_s1_head_to_head.py -q -n 0`.
  - Expected: **33 passed, 5 failed**: `test_the_read_is_bounded[above-cap]`, T10, T11, T12 and T14, each at an `AssertionError`.
  - T10 and T11 each wait about 5 s on the tip; that is their bound, not a hang.
  - Any other count, or a failure at setup or collection, is a hard stop.
- **GA1b** (after A1-M2): G2's command unchanged (§4).
  - Expected: **38 passed** in the new file; **810 passed** over G2's files (805 + 5), 0 failed.
  - Then `PY -P scripts/check_architecture_principles.py --check`.
  - Hard stop: `test_dm_golden_byte_identical` fails.
- **G3** after A1-M3, as in §4.

### 15.3 Tests (new file total: 15 functions, 38 cases)

| Id | Test | Cases | Covers | On `baea653d` |
|---|---|---|---|---|
| T6 (changed) | `test_the_read_is_bounded[above-cap]` also asserts no listing | 0 new | HH8's count | fails (listing called) |
| T10 | `test_the_records_are_read_in_a_worker_thread_while_the_event_loop_runs` | 1 | F1, structural: every store call is off the loop thread, and a callback queued on the loop runs before the listing proceeds | fails: the wait times out on the loop thread (5 s) |
| T11 | `test_cancelling_the_tally_while_the_records_are_read_raises_cancelled_error` | 1 | 13.8 with the worker | fails: the tally completes |
| T12 | `test_a_game_lookup_that_fails_for_the_tally_adds_nothing_and_logs_a_warning` | 1 | F4 | fails: no warning |
| T13 | `test_a_record_the_store_cannot_decode_is_not_counted` | 1 | L11 (a guard of the recorded limit) | passes by design |
| T14 | `test_a_records_store_that_suspends_gives_no_tally_and_a_warning` | 1 | the driver fails closed | fails: a tally is returned |

T10 uses no wall clock. If the read regresses to the loop thread, the loop cannot run the queued callback, `Event.wait(5.0)` returns `False`, and the first assertion fails. If a regression yields before an on-loop listing, the thread assertion fails instead.

### 15.4 Pairs: A1-M1 (tests)

**A1-T1** `tests/test_ad1358_s1_head_to_head.py`

SEARCH:
```
import importlib
import importlib.util
import json
import logging
```
REPLACE:
```
import asyncio
import importlib
import importlib.util
import json
import logging
import threading
```

**A1-T2** `tests/test_ad1358_s1_head_to_head.py`

SEARCH:
```
        assert tally is None and calls["read"] == 0
```
REPLACE:
```
        assert tally is None and calls["read"] == 0
        assert calls["list"] == []  # A1 (F1): counted by name above the cap; nothing is listed
```

**A1-T3** `tests/test_ad1358_s1_head_to_head.py` (appends T10 to T14 after T9)

SEARCH:
```
    assert tally.last_date == last
    assert tally.render() == _block(2, "Captain", 2, 0, 0, last)
```
REPLACE:
```
    assert tally.last_date == last
    assert tally.render() == _block(2, "Captain", 2, 0, 0, last)


# ── T10 to T14: Amendment A1 ─────────────────────────────────────────


async def test_the_records_are_read_in_a_worker_thread_while_the_event_loop_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1 (F1), structural, no timing: every store call runs off the event-loop thread, and a
    callback queued on the loop runs before the listing proceeds. Read on the loop thread, the
    callback cannot run, the wait ends at its bound and the first assertion fails."""
    read_head_to_head = _built("read_head_to_head")
    store = await _store(tmp_path)
    for index in range(3):
        await _record(store, f"g{index}", x="Captain", o="Ezri", winner="Captain")
    loop_thread = threading.get_ident()
    loop_ran = threading.Event()
    seen: dict[str, Any] = {"loop_ran_first": None, "threads": []}
    real_list, real_read = store.list_entries, store.read_entry

    async def list_spy(*args: Any, **kwargs: Any) -> Any:
        seen["threads"].append(threading.get_ident())
        seen["loop_ran_first"] = loop_ran.wait(5.0)
        return await real_list(*args, **kwargs)

    async def read_spy(*args: Any, **kwargs: Any) -> Any:
        seen["threads"].append(threading.get_ident())
        return await real_read(*args, **kwargs)

    monkeypatch.setattr(store, "list_entries", list_spy)
    monkeypatch.setattr(store, "read_entry", read_spy)
    asyncio.get_running_loop().call_soon(loop_ran.set)
    tally = await read_head_to_head(
        store, game_type="tictactoe", me="Ezri", opponent="Captain", reader_id="Ezri", reader_department="science",
    )
    assert seen["loop_ran_first"] is True
    assert len(seen["threads"]) == 4 and loop_thread not in seen["threads"]
    assert (tally.total, tally.opponent_won) == (3, 3)


async def test_cancelling_the_tally_while_the_records_are_read_raises_cancelled_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1 (F1), 13.8: a caller cancelled while the worker reads gets ``CancelledError``, not ``None``
    and not a tally; the worker's result is dropped."""
    read_head_to_head = _built("read_head_to_head")
    store = await _store(tmp_path)
    await _record(store, "g0", x="Captain", o="Ezri", winner="Captain")
    entered, release = threading.Event(), threading.Event()
    real_list = store.list_entries

    async def held_list(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        release.wait(5.0)
        return await real_list(*args, **kwargs)

    monkeypatch.setattr(store, "list_entries", held_list)
    task = asyncio.create_task(read_head_to_head(
        store, game_type="tictactoe", me="Ezri", opponent="Captain", reader_id="Ezri", reader_department="science",
    ))
    try:
        assert await asyncio.to_thread(entered.wait, 5.0)  # premise: the listing has begun
        task.cancel()
        (outcome,) = await asyncio.gather(task, return_exceptions=True)
    finally:
        release.set()
    assert isinstance(outcome, asyncio.CancelledError)


async def test_a_game_lookup_that_fails_for_the_tally_adds_nothing_and_logs_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A1 (F4), HH6: the tally's own ``get_game_by_player`` (the second of the turn; the active-game
    block's is the first) raising gives the prompt with no tally and a WARNING with ``exc_info``."""
    store = await _store(tmp_path)
    service = _service(store)
    try:
        await _play(service, "Captain", "Ezri", X_WINS)
        await service.create_game("tictactoe", "Captain", "Ezri")
        baseline_prompt, _ = await _turn(_agent(_runtime(recreation_service=service, records_store=None)))
        real_lookup = service.get_game_by_player
        calls: list[str] = []

        def second_fails(callsign: str) -> Any:
            calls.append(callsign)
            if len(calls) == 2:
                raise RuntimeError("the game table is busy")
            return real_lookup(callsign)

        monkeypatch.setattr(service, "get_game_by_player", second_fails)
        caplog.set_level(logging.WARNING, logger="probos.cognitive.cognitive_agent")
        prompt, manifest = await _turn(_agent(_runtime(recreation_service=service, records_store=store)))
    finally:
        await service.turns.stop()
    assert calls == ["Ezri", "Ezri"]  # premise: the active-game block's lookup, then the tally's
    assert prompt == baseline_prompt
    assert "head_to_head" not in _names(manifest)
    assert any(
        r.levelno == logging.WARNING and r.name == "probos.cognitive.cognitive_agent"
        and "AD-1358" in r.getMessage() and r.exc_info is not None
        for r in caplog.records
    )


async def test_a_record_the_store_cannot_decode_is_not_counted(tmp_path: Path) -> None:
    """A1 (F3), L11, a guard of a recorded limit: ``list_entries(strict=True)`` skips a file whose
    bytes are not UTF-8 (the store's rule), so the other records are counted. If the store's rule
    changes, change L11 with this test."""
    read_head_to_head = _built("read_head_to_head")
    store = await _store(tmp_path)
    await _record(store, "kept", x="Captain", o="Ezri", winner="Captain")
    await _record(store, "undecodable", x="Captain", o="Ezri", winner="Captain")
    path = store.repo_path / GAMES / "undecodable.md"
    path.write_bytes(b"\xff" + path.read_bytes())
    tally = await read_head_to_head(
        store, game_type="tictactoe", me="Ezri", opponent="Captain", reader_id="Ezri", reader_department="science",
    )
    assert tally.total == 1


async def test_a_records_store_that_suspends_gives_no_tally_and_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A1 (F1): the worker drives the store's coroutines with no event loop, which holds for
    ``RecordsStore`` (its reads await nothing). A read that does suspend fails closed and loudly:
    no tally and a WARNING with ``exc_info``, never a hang."""
    read_head_to_head = _built("read_head_to_head")
    store = await _store(tmp_path)
    await _record(store, "g0", x="Captain", o="Ezri", winner="Captain")
    real_list = store.list_entries

    async def suspending_list(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(0)
        return await real_list(*args, **kwargs)

    monkeypatch.setattr(store, "list_entries", suspending_list)
    caplog.set_level(logging.WARNING, logger="probos.recreation.history")
    assert await read_head_to_head(
        store, game_type="tictactoe", me="Ezri", opponent="Captain", reader_id="Ezri", reader_department="science",
    ) is None
    assert any(
        r.name == "probos.recreation.history" and "AD-1358" in r.getMessage() and r.exc_info is not None
        for r in caplog.records
    )
```

### 15.5 Pairs: A1-M2 (source)

**A1-S1** `src/probos/recreation/history.py`

SEARCH:
```
import logging
import re
from dataclasses import dataclass
from typing import Any, Final
```
REPLACE:
```
import asyncio
import logging
import re
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Any, Final
```

**A1-S2** `src/probos/recreation/history.py`

SEARCH:
```
:func:`read_head_to_head` reads one game type's records as one reader, through
``RecordsStore.list_entries`` and ``RecordsStore.read_entry``, so a record that reader may not
read is not counted. It returns ``None`` when no game between the two players is recorded,
when more than :data:`MAX_GAME_RECORDS` records of the type are listed, and on any failure.
```
REPLACE:
```
:func:`read_head_to_head` reads one game type's records as one reader, through
``RecordsStore.list_entries`` and ``RecordsStore.read_entry``, so a record that reader may not
read is not counted. The reads run in a worker thread, never on the event loop (A1). It returns
``None`` when no game between the two players is recorded, when the directory holds more than
:data:`MAX_GAME_RECORDS` ``*.md`` files (then none is read), and when a listing or read raises.
```

**A1-S3** `src/probos/recreation/history.py`

SEARCH:
```
#: The longest block :meth:`HeadToHead.render` can return, by construction.
MAX_BLOCK_CHARS: Final = 400
```
REPLACE:
```
#: The longest block :meth:`HeadToHead.render` returns for a tally :func:`read_head_to_head` built:
#: its game type is checked, each count is at most :data:`MAX_GAME_RECORDS` and the name is cut to
#: :data:`MAX_NAME_CHARS` (at most 317 characters). A ``HeadToHead`` built directly is not checked.
MAX_BLOCK_CHARS: Final = 400
```

**A1-S4** `src/probos/recreation/history.py` (two functions before `read_head_to_head`)

SEARCH:
```
    return GameOutcome(x_player, o_player, winner)


async def read_head_to_head(
```
REPLACE:
```
    return GameOutcome(x_player, o_player, winner)


def _drive(make: Callable[..., Coroutine[Any, Any, Any]], /, *args: Any) -> Any:
    """A1 (F1): run ``make(*args)`` to its end in this worker thread, with no event loop.

    ``RecordsStore.list_entries`` and ``read_entry`` are coroutines that await nothing, so one
    ``send`` runs one to its end. A coroutine that suspends would need an event loop this thread
    does not have: it is closed and ``RuntimeError`` raised, which the caller logs as a failure.
    """
    coro = make(*args)
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    coro.close()
    raise RuntimeError("AD-1358: a records store read suspended; the tally reads only stores that do not")


async def _read_records(
    records_store: Any, game_type: str, reader_id: str, reader_department: str,
) -> list[dict[str, Any]] | None:
    """The records of one game type that the reader may read, or ``None`` above the cap.

    Run by :func:`_drive` in a worker thread. It reads files only through the store's own
    ``list_entries`` and ``read_entry``, which touch no store state but the repository path, so
    they are safe off the event loop, as BF-952's ``_search_records`` walk is. The directory's
    ``*.md`` files are counted by name first, reading none, so a directory above the cap costs
    one scan and no reads.
    """
    directory = f"recreation/games/{game_type}"
    named = Path(records_store.repo_path, directory).rglob("*.md")
    if len(list(islice(named, MAX_GAME_RECORDS + 1))) > MAX_GAME_RECORDS:
        logger.warning(
            "AD-1358: more than %d %s game records; no head-to-head tally is shown",
            MAX_GAME_RECORDS, game_type,
        )
        return None
    listed = await records_store.list_entries(
        directory, tags=["game", game_type], strict=True,
    )
    if len(listed) > MAX_GAME_RECORDS:
        logger.warning(
            "AD-1358: %d %s game records exceed the head-to-head cap of %d; no tally is shown",
            len(listed), game_type, MAX_GAME_RECORDS,
        )
        return None
    docs: list[dict[str, Any]] = []
    for entry in listed:
        doc = await records_store.read_entry(
            entry["path"], reader_id=reader_id, reader_department=reader_department,
        )
        if doc is not None:
            docs.append(doc)
    return docs


async def read_head_to_head(
```

**A1-S5** `src/probos/recreation/history.py`

SEARCH:
```
    One strict listing of ``recreation/games/<game_type>/`` (a file that cannot be read fails the
    read rather than going uncounted), then at most :data:`MAX_GAME_RECORDS` ``read_entry`` calls
    as ``reader_id``/``reader_department``: a record that reader may not read is not counted.
    ``None`` when nothing is recorded, above the cap, and on any failure.
    """
```
REPLACE:
```
    A count by name of ``recreation/games/<game_type>/*.md``, then one strict listing, then at most
    :data:`MAX_GAME_RECORDS` ``read_entry`` calls as ``reader_id``/``reader_department``, all in a
    worker thread (:func:`_read_records`): a record that reader may not read is not counted. A
    listing or read that raises gives ``None`` and a warning. A file the store's listing itself
    skips (bytes that are not UTF-8, a frontmatter whose constructor raises) and a ``read_entry``
    that returns ``None`` are not counted (contract L11). ``None`` when nothing is recorded and
    above the cap. A cancelled caller gets ``CancelledError`` at once; the worker finishes its
    bounded pass and its result is dropped.
    """
```

**A1-S6** `src/probos/recreation/history.py`

SEARCH:
```
    try:
        listed = await records_store.list_entries(
            f"recreation/games/{game_type}", tags=["game", game_type], strict=True,
        )
        if len(listed) > MAX_GAME_RECORDS:
            logger.warning(
                "AD-1358: %d %s game records exceed the head-to-head cap of %d; no tally is shown",
                len(listed), game_type, MAX_GAME_RECORDS,
            )
            return None
        for entry in listed:
            doc = await records_store.read_entry(
                entry["path"], reader_id=reader_id, reader_department=reader_department,
            )
            if doc is None:
                continue
            outcome = parse_game_record(doc.get("content"))
```
REPLACE:
```
    try:
        # A1 (F1): every file read and parse runs in a worker thread, never on the event loop.
        docs = await asyncio.to_thread(_drive, _read_records, records_store, game_type, reader_id, reader_department)
        if docs is None:
            return None
        for doc in docs:
            outcome = parse_game_record(doc.get("content"))
```

**A1-S7** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
        try:
            game = rec_svc.get_game_by_player(callsign)
        except Exception:
            return None
        if type(game) is not dict:
```
REPLACE:
```
        try:
            game = rec_svc.get_game_by_player(callsign)
        except Exception:
            logger.warning(
                "AD-1358: the active game of %s could not be read for a head-to-head tally; none is shown",
                callsign, exc_info=True,
            )
            return None
        if type(game) is not dict:
```

### 15.6 Mutation rows (A1). Each Line occurs once in its file on A1-M2's head

HH-4, HH-5 and HH-11 are restated because their code moved into `_read_records`. HH-1 to HH-3, HH-6 to HH-10 and HH-12 to HH-17 are unchanged and still occur once. **Campaign of record:** run all rows, HH-1 to HH-22, on A1-M2's head. Record the sha256 of `history.py`, `cognitive_agent.py` and `oracle_service.py`; if a later repair changes a file, rerun only that file's rows.

| Id | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| HH-4 (A1) | history.py | `    if len(listed) > MAX_GAME_RECORDS:` | `>=` | T6 at-cap |
| HH-5 (A1) | history.py | `            entry["path"], reader_id=reader_id, reader_department=reader_department,` | `            entry["path"], reader_id="captain", reader_department="",` | T3 other-department, T3 anonymous |
| HH-11 (A1) | history.py | `        directory, tags=["game", game_type], strict=True,` | `        directory, tags=["game", game_type], strict=False,` | T6 strict-listing |
| HH-18 | history.py | `        docs = await asyncio.to_thread(_drive, _read_records, records_store, game_type, reader_id, reader_department)` | `        docs = _drive(_read_records, records_store, game_type, reader_id, reader_department)` | T10, T11 |
| HH-19 | history.py | `    if len(list(islice(named, MAX_GAME_RECORDS + 1))) > MAX_GAME_RECORDS:` | `    if False:` | T6 above-cap (listing called) |
| HH-20 | history.py | `    raise RuntimeError("AD-1358: a records store read suspended; the tally reads only stores that do not")` | `    return None` | T14 (no warning) |
| HH-21 | history.py | `    except Exception:` | `    except BaseException:` | T11 |
| HH-22 | cognitive_agent.py | `                callsign, exc_info=True,` | `                callsign, exc_info=False,` | T12 |

### 15.7 B: loop measurement (reported, not a test)

On A1-M2's head, rerun the orchestrator's `probe_loop_block.py` for N = 3, 256, 257 and 1,024. Report the median and the longest loop gap for each.

- **Expected:** for N ≥ 257, no `read_entry` and no listing (one scan by name). For N = 256, the longest gap is far below the base's 386 ms, of the order of the GIL switch interval.
- **Return to the Architect** if the longest gap at N = 256 or N = 1,024 exceeds 50 ms.

### 15.8 Contract text edits (apply before appending §15)

**C-01**
SEARCH:
```
**Status:** ready to build after AD-1357 (#1749) and BF-952 (#1751) are on `main`.
```
REPLACE:
```
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-06: Amendment A1 (§15), the repair of review round 1 (GPT-6.1 Sol, NOT READY): the reads run off the event loop and the cap is checked by name before any read (HH8); the tally's game lookup logs its failure; L4, L10 and HH5 corrected; L11 to L13 added; T10 to T14 added and T6 above-cap strengthened; rows HH-18 to HH-22 added and HH-4, HH-5, HH-11 restated.
**Status:** ready to build after AD-1357 (#1749) and BF-952 (#1751) are on `main`.
```

**C-02**
SEARCH:
```
**Estimated tests:** one new file, `tests/test_ad1358_s1_head_to_head.py`: 10 functions, 33 cases. Counted by reading, not by running. No existing test file is edited.
```
REPLACE:
```
**Estimated tests:** one new file, `tests/test_ad1358_s1_head_to_head.py`: 10 functions, 33 cases; after A1, 15 functions, 38 cases. Counted by reading, not by running. No existing test file is edited.
```

**C-03**
SEARCH:
```
- **HH5:** one listing plus at most 256 `read_entry` calls per DM turn during a game. Above the cap: no block, no entry reads, a WARNING.
```
REPLACE:
```
- **HH5:** a count by name, then one listing plus at most 256 `read_entry` calls per DM turn during a game, all in a worker thread (A1, HH8). Above the cap: no listing, no entry reads, no block, a WARNING.
```

**C-04**
SEARCH:
```
- **L4.** No cache: each DM turn during a game lists the directory once. Above 256 records of one type, no tally is shown. The remedy, structured frontmatter on new records plus an index, is considered and deferred.
```
REPLACE:
```
- **L4.** No cache. Each DM turn during a game counts the directory's `*.md` files by name (no read). At most 256, it lists them (each file read and parsed) and reads each again with `read_entry`: up to 512 file reads, in a worker thread, which the DM turn waits for (A1). Above 256 `*.md` files in the directory, game records or not, no tally is shown and none is read. The remedy, structured frontmatter on new records plus an index, is considered and deferred.
```

**C-05**
SEARCH:
```
- **L10.** A group-chat DM turn shows the block too, as it shows the active-game block. The records involved are ship-classified.
```
REPLACE:
```
- **L10.** A group-chat DM turn shows the block too, as it shows the active-game block. The tally counts every record the agent whose prompt it is may read (HH4), its own private records and its department's records included; `_record_game` writes ship-classified records, so another classification arises only when a record is rewritten through the store. The other participants see that agent's reply, so a count that includes such a record can reach them through it, as any other content of its prompt can. A group-turn restriction to ship-classified records would apply to every DM-side read; considered, deferred.
- **L11.** A file the store's strict listing skips is not counted, and AD-1358 logs nothing for it: bytes that are not UTF-8 (the store's rule, "a property of the file, not of the moment") and a frontmatter whose YAML constructor raises. A frontmatter YAML rejects reads as `{}` without the game tags, so it is not listed. A listed file that is gone, or that `read_entry` withholds, reads as `None` and is not counted. Only a listing or read that raises fails the tally.
- **L12.** `HeadToHead` built directly is not validated; `MAX_BLOCK_CHARS` bounds only a tally `read_head_to_head` returns (at most 317 characters).
- **L13.** The worker may read while the event loop writes a record (`write_entry` rewrites the file in place). A record read mid-write may parse as no record and go uncounted for that turn, as in BF-952's search walk.
```

**C-06**
SEARCH:
```
5. The listing is strict, covers one directory and is tag-filtered. There are at most `MAX_GAME_RECORDS` `read_entry` calls, and none above the cap.
```
REPLACE:
```
5. The listing is strict, covers one directory and is tag-filtered. There are at most `MAX_GAME_RECORDS` `read_entry` calls. Above the cap (counted by name), there is no listing and no `read_entry`.
10. (A1) No `RecordsStore` file read or YAML parse of the tally runs on the event-loop thread; the store is reached only through `list_entries`, `read_entry` and the `repo_path` property.
11. (A1) `RecordsStore.list_entries` and `read_entry`, run in a worker, touch no mutable store state; a store read that suspends fails closed (WARNING, no tally).
```

**C-07**
SEARCH:
```
## 9. Mutation rows (each Line occurs once in its file on M2's head)
```
REPLACE:
```
## 9. Mutation rows (each Line occurs once in its file on M2's head; after A1, on A1-M2's head, with §15.6)
```

**C-08**
SEARCH:
```
No campaign of record yet; the Builder runs them on M2's head.
```
REPLACE:
```
No campaign of record yet; after A1, the campaign of record runs on A1-M2's head (§15.6).
```

### 15.9 A1-M3 tracker pairs

**A1-P1** `PROGRESS.md`. Replace the whole of line 3. The head, its first 120 characters, is unchanged.

SEARCH:
```
**AD-1358 S1 (2026-11-06), #1750 -- a crew member in a game is told the recorded games against that opponent.** During an active game, a crew `direct_message` prompt carries, directly after the AD-572 active-game block, a head-to-head block counted from the AD-526a game records in Ship's Records (`recreation/games/<game_type>/`): the number of recorded games of that type between the agent and its opponent, how many each won, the draws, and the UTC date of the latest (`recreation/history.py`). The records are read as the agent (`oracle_service.records_reader_for`, BF-949's reader, which `dm_targeted_lookup._knowledge_lookup_reader` now delegates to), so a record it may not read is not counted. With no game recorded between the two, no records store, more than 256 records of the type, or a read that fails, nothing is added and the prompt is as before. The AD-1357 manifest names the section `head_to_head` by its length only. No config field. The contract is `prompts/ad-1358-s1-head-to-head-tally.md`. S2 (a claimed lookup checked against the turn's tool trace) and S3 (claims about shared history, with the BF-741 check) follow.
```
REPLACE:
```
**AD-1358 S1 (2026-11-06), #1750 -- a crew member in a game is told the recorded games against that opponent.** During an active game, a crew `direct_message` prompt carries, directly after the AD-572 active-game block, a head-to-head block counted from the AD-526a game records in Ship's Records (`recreation/games/<game_type>/`): the number of recorded games of that type between the agent and its opponent, how many each won, the draws, and the UTC date of the latest (`recreation/history.py`). The records are read as the agent (`oracle_service.records_reader_for`, BF-949's reader, which `dm_targeted_lookup._knowledge_lookup_reader` now delegates to), so a record it may not read is not counted; its own private and department records are. The directory is counted by name, then listed and read in a worker thread, so the event loop is not held. With no game recorded between the two, no records store, more than 256 records of the type (then none is read), or a game lookup, listing or read that raises (logged), nothing is added and the prompt is as before; a file the store's listing skips (bytes that are not UTF-8) is left out of the count. The AD-1357 manifest names the section `head_to_head` by its length only. No config field. The contract is `prompts/ad-1358-s1-head-to-head-tally.md`, with Amendment A1. S2 (a claimed lookup checked against the turn's tool trace) and S3 (claims about shared history, with the BF-741 check) follow.
```

**A1-P2** `DECISIONS.md`

SEARCH:
```
- *HH5 (cost).* One listing plus at most 256 entry reads per DM turn during a game; above the cap, none, no block and a warning.
- *HH6 (failure).* Log-and-degrade: any failure gives no block and a warning; the prompt is unchanged.
- *Not changed.* `records_store.py`, `RecreationService`, the AD-526a record format, `context_manifest.py`, the Ward Room chain's game context, config.
- *Residual.* Recorded limits L1 to L10 of the contract.
- *Reversal.* Revert the AD-1358 S1 commits.
```
REPLACE:
```
- *HH5 (cost).* A count of the directory's `*.md` files by name, then one listing plus at most 256 entry reads per DM turn during a game, all in a worker thread; above the cap, no listing, no read, no block and a warning.
- *HH6 (failure).* Log-and-degrade: a game lookup, listing or read that raises gives no block and a warning with the traceback; the prompt is unchanged. A file the store's listing skips (bytes that are not UTF-8) is not counted (L11).
- *HH8 (A1, off the loop).* The store's own `list_entries` and `read_entry` coroutines, which await nothing, are run to their end in a worker thread with no event loop, as BF-952's search walk runs off the loop; a store read that suspends fails closed. Rejected: a synchronous or counting `RecordsStore` method (a shared contract; deferred with the index of L4); yielding between reads (the listing is one blocking call); a private event loop per tally.
- *Not changed.* `records_store.py`, `RecreationService`, the AD-526a record format, `context_manifest.py`, the Ward Room chain's game context, config.
- *Residual.* Recorded limits L1 to L13 of the contract.
- *Reversal.* Revert the AD-1358 S1 commits.
```

Then the ledger: `PY -P scripts/gen_ad_ledger.py`, staging `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as written; then G3. `docs/development/roadmap.md` is not updated.

### 15.10 Verified Against Codebase (2026-11-06, on `baea653d`)

    rg "def read_entry|def list_entries" src/probos/knowledge/records_store.py
      1282: async def read_entry(   1313: async def list_entries(
    records_store.py:1296  raw = file_path.read_text(encoding="utf-8")      (synchronous, in the coroutine)
    records_store.py:1342  found = _markdown_files_or_raise(search_path) if strict else ...
    records_store.py:1350  raw = md_file.read_text(encoding="utf-8")       (every file, before any cap)
    records_store.py:1330  "Bytes that are not UTF-8 are still skipped"
    records_store.py:1357-1359  except Exception: logger.debug("Skipping unreadable file"...); continue
    records_store.py:1305  if doc_class == "private" and reader_id != doc_author: return None
    records_store.py:1478  return await asyncio.to_thread(   (BF-952 precedent)
    records_store.py:527-528  @property / def repo_path(self) -> Path:
    records_store.py:671  file_path.write_text(full_content, encoding="utf-8")   (write_entry, in place)
    records_store.py:1575-1585  _parse_document: yaml.YAMLError -> {} ; no other state
    history.py:32  #: The longest block :meth:`HeadToHead.render` can return, by construction.
    history.py:105-108, 118-134, 146   the docstring, the on-loop try block, except Exception
    cognitive_agent.py:66  logger = logging.getLogger(__name__)
    cognitive_agent.py:8642-8646  try / get_game_by_player / except Exception: return None / if type(game) is not dict:
    cognitive_agent.py:8590-8591, 8620-8621  _build_active_game_context's lookup and its silent except (AD-572; untouched)
    startup/cognitive_services.py:609  records_store = RecordsStore(rcfg, ontology=None)   (production store is RecordsStore)
    CPython 3.12.13 (d:/ProbOS/.venv/pyvenv.cfg): pathlib.py:169-170 select_from returns iter([]) when not is_dir();
      unittest/mock.py:2279-2314 AsyncMock's _execute_mock_call awaits only a side_effect coroutine (never suspends)
    pyproject.toml:9 requires-python = ">=3.12"   (asyncio.to_thread available)
    SEARCH uniqueness on baea653d: history.py:18,21 (imports), :10-13, :32-33, :91-94, :105-109, :118-134;
      cognitive_agent.py:8642-8646 (":8646 if type(game) is not dict:" once; ":8643" differs from ":8591" by the next line);
      tests:21-22, :378, :459-460; PROGRESS.md:3; DECISIONS.md:1484-1488 (":1487 Residual L1 to L10" also at :1394, unique with :1488);
      contract :4, :8, :40, :1061, :1068, :1074, :1094, and the §9 heading — each one hit.
    New Lines unique post-repair: "callsign, exc_info=True," at 16 spaces has no hit in cognitive_agent.py today
      (hits only in after_action.py, stand_down.py, reply_pipeline.py and others).

### Absence Verified (2026-11-06)

    CLAIM: only read_head_to_head constructs HeadToHead
    RUN:   rg "HeadToHead\(" src/   FOUND: history.py:154   HOLDS: yes
    CLAIM: no test outside the new file calls the tally
    RUN:   rg "head_to_head|recreation\.history" tests/   FOUND: the new file; test_ad1357_context_manifest.py:894,899 (an unrelated literal)   HOLDS: yes
    CLAIM: the store's two read coroutines touch no mutable store state
    RUN:   Read records_store.py:1282-1373   FOUND: self._safe_path, self._repo_path, self._parse_document only   HOLDS: yes
    CLAIM: MAX_BLOCK_CHARS has no production consumer
    RUN:   rg "MAX_BLOCK_CHARS" src/   FOUND: history.py:33 only   HOLDS: yes

**Bound for L12:** a 39-character header, plus 1, plus a 273-character line (a 32-character type, two 64-character names, four counts of at most 3 digits each, a 10-character date), plus 4, makes 317.

### 15.11 Prior art and blind spots (A1)

- Offloading blocking file I/O from an asyncio loop with `asyncio.to_thread` is the standard library's documented pattern. BF-952 is the in-repo precedent: absorbed.
- Running a coroutine that never suspends with `send(None)` (no loop) instead of `asyncio.run` per call: adapted, with a fail-closed guard (T14).
- **Blind spots handled:**
  - The GIL: the worker's pure-Python YAML still shares the GIL, but the loop regains it at each switch interval (§15.7 measures it).
  - Cancellation cannot stop the worker. Its pass is bounded, and its result is dropped (T11).
  - A concurrent writer (L13).
  - Files added between the count and the listing: the check after the listing stays.
- External search was skipped: this is ProbOS-specific plumbing with an in-repo precedent.
