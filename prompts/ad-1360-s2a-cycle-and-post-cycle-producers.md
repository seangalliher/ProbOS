# AD-1360 S2a (#1828): producers that store an episode inside or after a cognitive cycle record that cycle's AD-492 id

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-21

**Status:** oracle-proven (section 15). #1828 stays open until S3; the S1+S2a+S2b PR says `Refs #1828`. Decision: consult `bfa178a3`. No Captain condition. AD-1360 appears only in REPLACE text, the new file and the trackers.
- AD ceiling (`scripts/ad_ceiling.py`, run 2026-11-21): **AD-1361** (from `prompts/` filenames); git AD-1359; issues AD-1360.
- S2a allocates no AD and no BF.

**Base:** `24c30a7c` (main after the pull request for #1838) + S1 as committed on this branch (head `a4012763`, its trackers included). The pairs of section 7 were proven on a scratch tree that held the S1 contract applied (7.1-7.14, and 7.15-7.17 before this slice's M3); section 15, O9 repeats the check on this branch. Line numbers in sections 3 and 10 were measured on that scratch tree; those in `cognitive_agent.py` are higher on this branch (BF-989's seven lines and S1's repair), by up to about 30, so search by symbol.

**Line endings:**
- Every edited tracked file is `i/lf w/crlf` (`git ls-files --eol`), `cycle_trace.py` (S1's new file, committed) included.
- SEARCH blocks are LF; match and write each file in its own endings.
- The new test file is LF and ASCII only. No SEARCH holds a non-ASCII character.

**Milestones** (one Builder delegation each; apply pairs, run no test; no `AD-`/`BF-` token in a subject):

| M | Content | Tier | Review | Calls |
|---|---|---|---|---|
| M1 | 7.1 (new tests) first, then 7.2 and 7.4-7.9 (7.3 is not used) | MEDIUM | Full GPT Diff Reviewer. Shared contract: `DmReplyContext` | ~65 |
| M2 | 7.10, 7.11 | MEDIUM | Full | ~30 |
| M3 | 7.12, 7.13, ledger check | LOW | Delta | ~12 |

Commit subjects:
- M1: `Store the cycle's id on episodes written in or after a cognitive cycle`
- M2: `Bind a proactive think's cycle id around its posts and register promoted work items`
- M3: `Record the cycle-producer slice in the status and decisions entries`

## 0. Premises (this tree, read 2026-11-21)

| P | Premise | Evidence |
|---|---|---|
| P1 | S1 API | `cycle_trace.py:51-72` (`current_cycle_id`, `bind_cycle`, `unbind_cycle`), `:112-133` (`issue(kind=)`, `register`, `kind_of`). No `cycle_scope`/`result_cycle_id` |
| P2 | Bound lifecycle and its two call sites | `cognitive_agent.py:7607-7623`, `:8312`, `:8336` (in `_handle_admitted_intent`, `:8194`) |
| P3 | Result id | `_build_result_metadata` `:255`, id block `:323-327`. The compound replay's early return (`:7839-7845`) builds its result by hand; S1's `_carry_cycle_id`, called in `_run_cycle_bound_lifecycle` on every result the lifecycle returns, puts the cycle's id on it, so S2a reads the id of every cycle result through `result_cycle_id` and changes nothing in `cognitive_agent.py`. The other lifecycle return is `:8104-8121` |
| P4 | AD-654a self-post is inside the lifecycle | `:8095-8096` -> `_self_post_ward_room_response` `:7569` -> `ward_room_pipeline.py:387` `create_post`. `_store_action_episode` skips `ward_room_notification` (`:12755-12756`) |
| P5 | DM route stores after the cycle | `routers/agents.py:3699` `send`. ctx built `:3810-3848`. `"from": "hxi_profile"` `:3597`. Step 5 `reply_pipeline.py:2494-2573` (`Episode(` `:2553`, `source=` `:2562`), only in `_full_steps` (`:505`; escalation excludes it, `:535-545`). `_run_steps` `:560-577`. Last ctx field `:209` |
| P6 | Shell session stores after the cycle | `session.py:138` `send`, `Episode(` `:171-195`, `"from": "captain"` `:114` |
| P7 | Ward Room sites | `messages.py:344` (reply), `:388` (peer echo); `threads.py:586` (thread), `:630` (peer echo). All `source="direct"`, no id |
| P8 | Proactive | `handle_intent` `:1425`/`:1437`, settle `finally` `:1440-1443`. Actions `:1577`. Thread post `:1637` -> `_post_to_ward_room` `:3128-3192` (`create_thread` `:3173`). Reply blocks `:4126-4256` (`create_post` `:4248`). Sole production caller of `_think_for_agent`: `:1210` |
| P9 | AD-1343 pins | `tests/fixtures/ad1343_seam_registry.py:174` keys `("proactive.py", "ProactiveCognitiveLoop._think_for_agent", "handle_intent")`; `:100` pins `_run_cycle` order; `:184-185` pin `resume_promoted_turn` callees |
| P10 | Promoted runs | `_create_promoted_work_item` `turn_promotion.py:995-1046`; `_store_promoted_episode` `:1464`, `correlation_id=work_item_id` `:1591`; `resume_promoted_turn` `:2915`, item re-read `:2939-2941`. Callers: `capability_gap_driver.py:331`, `promoted_turn_recovery.py:178` |
| P11 | MCP episode in the agentic loop | `runtime.py:5155` `_store_mcp_invoke_episode`, `Episode(` `:5219-5240`; wired as `episode_writer` `finalize.py:5131`; called `agentic_dispatch.py:1937` |
| P12 | Harnesses reused | `tests/bf934_world.py:119-177` (real loop + Ward Room); `tests/test_ad1156_plan_execute_mode.py:696-741` (`_route_runtime`, `_chat_request`) |

## 1. Problem

S1 records a verdict at store time, but most direct producers still pass no `correlation_id`:
- Inside a bound cycle, such an episode records `empty`.
- After the cycle has ended (the DM route, the shell, proactive posts), the binding is gone (P2's `finally`), so the producer also records `empty`.

## 2. Solution

| Where the id comes from | Producers |
|---|---|
| `current_cycle_id()` at the site (inside a bound cycle) | Ward Room x4 (P7); MCP invoke (P11) |
| `cycle_scope(id)` around work done for an ended cycle | DM reply steps (`_run_steps`); proactive actions and observation thread (P8) |
| `result_cycle_id(result)` | DM route -> `DmReplyContext.cycle_id` -> step 5; shell session |
| the result carries it | S1's `_carry_cycle_id`, on every result `_run_cycle_bound_lifecycle` returns, the compound replay's included (P3) |
| registered work item (S1 D5) | `_create_promoted_work_item`; `resume_promoted_turn` |

Outside any cycle, every changed producer stores `""`, as before. The cutoff stays 0.0.

**Heavier designs rejected:**
- A `correlation_id` parameter on `create_thread`/`create_post`: 52 call sites (rg), every in-cycle caller threaded.
- Renaming `_think_for_agent` to wrap its body: it moves the `handle_intent` call P9 pins.
- Registering at store time: it certifies any id handed to `store()`.

## 3. Consumers checked (what I enumerated)

| Changed | Consumers | Result |
|---|---|---|
| Producers' `correlation_id` | `rg -n correlation_id tests` (38 files, 318 hits). Producer-relevant: `test_ad1165_turn_promotion.py:732` (work item id, unchanged), `test_bf740_*` (its own episodes), `test_bf925_*:167` (its own episode), `test_bf934_s3_*`/`test_bf976_*` (event-log rows keyed by intent id). `rg "== Episode\(\|\.correlation_id == \"\""` finds only Episode defaults and test_bf740's own rows. No test pins an S2a producer's empty id | No X pair |
| Source-scanning tests | `getsource`/`read_text` over the producer files: `test_ad617b:187` (`_run_cycle`), `test_bf164`, `bf163`, `bf257`, `bf156`, `ad590`, `ad591` (strings not touched), `test_ad1248_slice_b` (step 1, 4j), `test_bf296` (`_full_steps`, 4b) | Unchanged |
| AD-1343 census | P9; `cycle_scope` and `result_cycle_id` are not in its callee lists; the `handle_intent` call stays in `_think_for_agent` | Holds |
| `DmReplyContext` | `test_ad791a:291` checks only `chat_thread_id`. The new field is defaulted and last; `thread_fanout.py:848` and `reply_pipeline.py:2715` pass nothing (`""`) | Compatible |
| `_think_for_agent` callers and patches | 40+ tests call or patch it by name; the signature is unchanged | Compatible |
| `_store_mcp_invoke_episode` | `test_ad1019c_consensus.py:325-503` read anchors, agent ids and outcomes, never the id | Compatible |
| `_create_promoted_work_item`, `resume_promoted_turn` | MagicMock or no-registry runtimes: not a `CycleIdRegistry`, so nothing is registered | Compatible |
| `procedure_challenger.py:259` | Pins episodes whose id equals the source turn's; after S2a that includes a Ward Room reply the turn posted | Disclosed |

**Not checked:** the live vessel.

## 4. Decisions

- **D7.** Each source is chosen per the table in section 2. A producer reached inside a cycle by an awaited call or a task inherits that cycle's id (PEP 567; S1 N8).
- **D8.** Work items are registered at creation and on each resume. These are the two seams every promoted run passes (P10).
- **D9.** `cycle_scope("")` (or a non-`str`) keeps the outer id, so a block for a result with no id runs exactly as before.
- **G-e.** `_register_promoted_work_item` accepts only a `CycleIdRegistry` and a non-blank `str` (MagicMock runtimes, S1 G-e).

## 5. Tests: new file `tests/test_ad1360_s2a_producers.py` (11 cases)

| N | Case | S1 tree | After M1 | After M2 |
|---|---|---|---|---|
| N1 | `cycle_scope` binds, keeps the outer id for blank or non-str, restores on exit and raise, undoes an inner bind | collection error | pass | pass |
| N2 | `result_cycle_id` reads only a non-empty str | error | pass | pass |
| N3 | `_run_steps` binds `ctx.cycle_id`, restores after a raising step; the default is `""` | error | pass | pass |
| N4 | **crossing:** DM route -> real cycle -> step 5 -> real memory: `resolved` | error | pass | pass |
| N5 | **crossing:** shell session -> real cycle -> episode `resolved` | error | pass | pass |
| N6 | **crossing:** AD-654a self-post on the real Ward Room: reply and peer echo `resolved`; posts outside a cycle `empty` | error | pass | pass |
| N8 | MCP episode inside a bound cycle `resolved`, outside `empty` | error | pass | pass |
| N9 | **crossing:** real proactive loop -> observation thread and its peer echo `resolved`; the peer's thread `empty` | error | **fail** (`empty`) | pass |
| N10 | **crossing:** a proactive `[REPLY]` block's post `resolved` | error | **fail** | pass |
| N11 | promoted item registered at creation; outcome episode `resolved`; MagicMock, absent or blank registers nothing | error | **fail** (AttributeError) | pass |
| N12 | resume after a restart re-registers; outcome `resolved` | error | **fail** | pass |

After M1: 7 pass, 4 fail. After M2: 11 pass.

N7 is not used: the compound replay's early return gets the cycle's id from S1's `_carry_cycle_id` (the S1 case N36 runs it through a real `handle_intent`), so this slice has no edit to `cognitive_agent.py` and no case for it. The labels N8 to N12 keep their numbers.

**Evidence limit:** N8 tests the producer under a bound cycle. That the agentic tool loop runs inside the cycle is established by reading (P11), not by a test.

## 6. Left to S2b (not patched here)

| Site (this tree) | Why S2b | Suggested disposition |
|---|---|---|
| `quartermaster.py:202`, `:471` | `BaseAgent` sweep, no cycle | entry chain `kind="quartermaster"` |
| `ground_truth.py:220` | constant `""`; no caller of `.write` (`rg verification_episode_writer src`: only `finalize.py:4834,4838,4899`) | exempt or entry chain |
| `routers/wardroom.py:281`, `:351`; `routers/recreation.py:118`; `routers/procedures.py:201` | HXI request | `hxi_post` entry chain |
| `ward_room_router.py:273`, `:293` and notifier/startup threads (author `system`) | no cycle | entry chain or exempt |
| DM route with `result is None` (AD-1230 held turn) or a non-cognitive result | no cycle ran; step 5 stores `empty` | route chain when `ctx.cycle_id == ""` |
| `proactive.py:1525` | `should_store` rejects every episode it builds | exempt |
| `proactive.py:1802` | unreachable (`:1114`; `:1637` dereferences the ward room at `:3138` before `:1759`); `context` undefined at `:1781` | delete the branch, or fix to `context_parts` and test it |
| `__main__.py:2343`, `crew_synth.py:646` | non-direct sources (section 6 of S1) | exemption rows |
| `runtime.py:5562`, `device_service.py:138` | in-cycle reach not established | `current_cycle_id()` at the site + entry chain |
| NL pipeline (`runtime.py:6160`, `renderer.py:491`, `dream_adapter.py:407`), `feedback.py:257,418`, `routers/agents.py:499`, `routers/perception.py:96`, `perception/consumer.py:1181`, `runtime.py:7009` | entry points (consult Q2) | entry chains |
| `cognitive_agent.py:8246` (work-item dispatch), `:8279` (compound replay intent), `:8284` (skills) | outside `_run_cycle_bound_lifecycle` | the guard decides |

## 7. The contract

### 7.1 New file `tests/test_ad1360_s2a_producers.py` (M1, written first)

```python
"""AD-1360 S2a (#1828): producers that store an episode inside or after a cognitive cycle record that cycle's id.

Each crossing case runs a real producer (a CognitiveAgent cycle, the Captain's 1:1 DM route, the shell session, the
Ward Room service, the proactive loop, the promoted-turn helpers, the MCP episode writer) into a real ChromaDB-backed
EpisodicMemory with a cycle-id registry bound, and reads the stored record back. security.memory.correlation_cutoff
stays at 0.0, so nothing here changes a recall.
"""

from __future__ import annotations

import functools
import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from probos.cognitive import turn_promotion
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.episodic import EpisodicMemory
from probos.crew_profile import Rank
from probos.cycle_trace import (
    VERDICT_EMPTY,
    VERDICT_RESOLVED,
    CycleIdRegistry,
    bind_cycle,
    current_cycle_id,
    cycle_scope,
    result_cycle_id,
    unbind_cycle,
)
from probos.dm_reply import DmReply
from probos.experience.commands.session import SessionManager
from probos.types import IntentMessage, IntentResult
from probos.ward_room.service import WardRoomService
from probos.ward_room_pipeline import WardRoomPostPipeline
from probos.workforce import WorkItemStore
from tests import bf934_world
from tests.test_ad1156_plan_execute_mode import _chat_request, _route_runtime

_OBSERVATION = "The coolant loop on deck four reads within limits after the morning flush."
_REPLY = "Coolant pressure on deck four held steady through the evening watch handover."
_QUESTION = "What does the coolant loop read?"


class _Agent(CognitiveAgent):
    """A real CognitiveAgent whose model steps are stubbed (test_ad1360_s1_cycle_trace's pattern): the real perceive,
    lifecycle, cycle binding and AD-654a self-post run; ``answer`` is the whole reply."""

    agent_type = "science_officer"
    instructions = "AD-1360 S2a producer test agent."
    answer = _OBSERVATION

    async def _recall_relevant_memories(self, intent: Any, observation: dict) -> dict:
        return observation

    async def decide(self, observation: dict) -> dict:
        return {"llm_output": ""}

    async def act(self, decision: dict) -> dict:
        return {"success": True, "result": self.answer}

    async def report(self, result: dict) -> dict:
        return {"success": True, "result": self.answer}


def _records(memory: EpisodicMemory) -> dict[str, tuple[str, str]]:
    """Every stored episode, read back from ChromaDB: user_input -> (correlation_id, correlation_verdict)."""
    got = memory._collection.get(include=["metadatas", "documents"])
    episodes = [
        EpisodicMemory._metadata_to_episode(episode_id, document, metadata)
        for episode_id, document, metadata in zip(got["ids"], got["documents"], got["metadatas"])
    ]
    return {episode.user_input: (episode.correlation_id, episode.correlation_verdict) for episode in episodes}


def _only(records: dict[str, tuple[str, str]], prefix: str, author: str = "") -> tuple[str, str]:
    hits = [value for key, value in records.items() if key.startswith(prefix) and author in key]
    assert len(hits) == 1, (prefix, author, sorted(records))
    return hits[0]


def _ctx(**overrides: Any) -> DmReplyContext:
    return DmReplyContext(
        runtime=SimpleNamespace(), agent=None, agent_id="ad1360-agent", callsign=None, req_message="",
        reply=DmReply(body="noted"), has_image_attachment=False, per_attachment=[], sanity_gate=None, params={},
        message_text="", sampling_state=None, avatar_event_bus=None, **overrides,
    )


def _cycle_runtime(memory: EpisodicMemory, registry: CycleIdRegistry, **extra: Any) -> SimpleNamespace:
    return SimpleNamespace(episodic_memory=memory, ontology=None, cycle_registry=registry, **extra)


def _recording(agent: CognitiveAgent, results: list[IntentResult]) -> Any:
    """The intent bus's ``send`` as a real cycle of ``agent``; each result is kept."""

    async def _send(intent: IntentMessage, **_kwargs: Any) -> IntentResult:
        results.append(await agent._run_cycle_bound_lifecycle(intent))
        return results[-1]

    return _send


async def _science_channel(w: Any) -> Any:
    """The channel ``_post_to_ward_room`` picks for a science officer: its department's, else the ship-wide one."""
    channels = await w.ws.list_channels()
    department = next((c for c in channels if c.channel_type == "department" and c.department == "science"), None)
    return department or next(c for c in channels if c.channel_type == "ship")


async def _thinker(w: Any, answer: str = _OBSERVATION) -> tuple[_Agent, list[IntentResult]]:
    """Kira as a real CognitiveAgent on the world's runtime: the real handle_intent runs, and its results are kept."""
    agent = _Agent(agent_id=w.ids["science_officer"], runtime=w.rt)
    agent.callsign = "Kira"
    agent.answer = answer
    await w.registry.register(agent)
    results: list[IntentResult] = []
    real = agent.handle_intent

    async def _handle(intent: IntentMessage) -> IntentResult | None:
        results.append(await real(intent))
        return results[-1]

    agent.handle_intent = _handle  # type: ignore[method-assign]
    return agent, results


@pytest.fixture
async def memory(tmp_path: Path) -> Any:
    em = EpisodicMemory(db_path=str(tmp_path / "episodic.db"), relevance_threshold=0.0)
    await em.start()
    try:
        yield em
    finally:
        await em.stop()


@pytest.fixture
def registry(memory: EpisodicMemory) -> CycleIdRegistry:
    bound = CycleIdRegistry()
    memory.set_cycle_registry(bound)
    return bound


# -- N1 to N3: the scope, the result's id, the reply steps ------------------------------------------------------------


def test_cycle_scope_binds_an_id_keeps_the_outer_one_otherwise_and_always_puts_it_back() -> None:
    outer = bind_cycle("0123456789ab")
    try:
        with cycle_scope("feedfacecafe") as bound:
            assert bound == current_cycle_id() == "feedfacecafe"
            bind_cycle("aaaaaaaaaaaa")  # bound inside the scope and never reset: the scope's exit undoes it
        assert current_cycle_id() == "0123456789ab"
        for kept in ("", "   ", None, 7):
            with cycle_scope(kept) as bound:  # type: ignore[arg-type]
                assert bound == current_cycle_id() == "0123456789ab"
        with pytest.raises(RuntimeError, match="ad1360"):
            with cycle_scope("feedfacecafe"):
                raise RuntimeError("ad1360: the block failed")
        assert current_cycle_id() == "0123456789ab"
    finally:
        unbind_cycle(outer)
    assert current_cycle_id() == ""


def test_result_cycle_id_reads_only_a_non_empty_string() -> None:
    def result(metadata: dict) -> IntentResult:
        return IntentResult(intent_id="ad1360-intent", agent_id="ad1360-agent", success=True, metadata=metadata)

    assert result_cycle_id(result({"correlation_id": "abcdefabcdef"})) == "abcdefabcdef"
    for metadata in ({}, {"correlation_id": ""}, {"correlation_id": "   "}, {"correlation_id": 7}):
        assert result_cycle_id(result(metadata)) == ""
    for other in (None, MagicMock(), SimpleNamespace(metadata="abcdefabcdef")):
        assert result_cycle_id(other) == ""


async def test_the_reply_steps_run_with_the_cycle_bound_and_the_outer_id_comes_back() -> None:
    seen: list[str] = []

    async def probe() -> None:
        seen.append(current_cycle_id())

    async def fails() -> None:
        seen.append(current_cycle_id())
        raise RuntimeError("ad1360: a step failed")

    assert _ctx().cycle_id == ""  # every construction site that does not set it
    outer = bind_cycle("0123456789ab")
    try:
        await DmReplyPipeline(_ctx(cycle_id="feedfacecafe"))._run_steps((probe, fails, probe))
        assert current_cycle_id() == "0123456789ab"
        await DmReplyPipeline(_ctx())._run_steps((probe,))
    finally:
        unbind_cycle(outer)
    assert seen == ["feedfacecafe", "feedfacecafe", "feedfacecafe", "0123456789ab"]


# -- N4 to N8: crossing, from a real cycle (or inside one) to the stored record -------------------------------------


async def test_the_captains_dm_route_stores_the_turn_with_the_agents_cycle_id(
    memory: EpisodicMemory, registry: CycleIdRegistry, tmp_path: Path,
) -> None:
    from probos.routers.agents import agent_chat

    agent = _Agent()
    agent._runtime = _cycle_runtime(memory, registry)
    results: list[IntentResult] = []
    rt = _route_runtime(tmp_path, modes=False)
    rt.registry.get.return_value.sovereign_id = "ad1360-dm-agent"
    rt.episodic_memory = memory
    rt.intent_bus.send = AsyncMock(side_effect=_recording(agent, results))
    with patch("probos.routers.agents.is_crew_agent", return_value=True):
        await agent_chat("test-agent", _chat_request(_QUESTION), rt)
    chain_id = result_cycle_id(results[0])
    assert len(results) == 1 and registry.kind_of(chain_id) == "cognitive_cycle" and current_cycle_id() == ""
    assert _only(_records(memory), "[1:1 with") == (chain_id, VERDICT_RESOLVED)


async def test_a_shell_session_turn_stores_its_episode_with_the_agents_cycle_id(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    agent = _Agent()
    agent._runtime = _cycle_runtime(memory, registry)
    results: list[IntentResult] = []
    session = SessionManager()
    session.callsign, session.agent_id, session.agent_type, session.department = "Kira", agent.id, agent.agent_type, "science"
    session._sovereign_id = agent.id
    runtime = SimpleNamespace(
        intent_bus=SimpleNamespace(send=_recording(agent, results)), episodic_memory=memory, chat_thread_store=None,
    )
    await session.handle_message(_QUESTION, runtime, Console(file=io.StringIO()))
    chain_id = result_cycle_id(results[0])
    assert registry.kind_of(chain_id) == "cognitive_cycle"
    assert _only(_records(memory), "[1:1 with Kira]") == (chain_id, VERDICT_RESOLVED)


async def test_a_ward_room_reply_an_agent_posts_in_its_cycle_records_the_cycles_id(
    memory: EpisodicMemory, registry: CycleIdRegistry, tmp_path: Path,
) -> None:
    ws = WardRoomService(db_path=str(tmp_path / "wr.db"), episodic_memory=memory)
    await ws.start()
    try:
        channel = (await ws.list_channels())[0]
        thread = await ws.create_thread(
            channel.id, "captain", "Deck four", "What is on deck four today?", author_callsign="Captain",
        )
        await ws.create_post(thread.id, "ad1360-peer", _REPLY, author_callsign="Peer")  # outside any cycle
        agent = _Agent()
        agent.answer = _REPLY  # the peer's words, so AD-506b also writes the agent a peer-echo episode
        agent._runtime = _cycle_runtime(
            memory, registry, ward_room=ws,
            ward_room_post_pipeline=WardRoomPostPipeline(
                ward_room=ws, ward_room_router=None, proactive_loop=None, trust_network=None,
                callsign_registry=None, config=None,
            ),
        )
        intent = IntentMessage(
            intent="ward_room_notification", target_agent_id=agent.id,
            params={"thread_id": thread.id, "event_type": "ward_room_thread_created", "was_mentioned": True},
        )
        result = await agent._run_cycle_bound_lifecycle(intent)
    finally:
        await ws.stop()
    chain_id = result_cycle_id(result)
    records = _records(memory)
    assert registry.kind_of(chain_id) == "cognitive_cycle"
    assert _only(records, "[Ward Room reply]", "science_officer:") == (chain_id, VERDICT_RESOLVED)
    assert _only(records, "[Peer echo]") == (chain_id, VERDICT_RESOLVED)
    assert _only(records, "[Ward Room reply]", "Peer:") == ("", VERDICT_EMPTY)  # outside a cycle: S2b's
    assert _only(records, "[Ward Room]", "Captain:") == ("", VERDICT_EMPTY)


async def test_an_mcp_invoke_episode_stored_inside_a_cycle_records_that_cycles_id(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    from probos.runtime import ProbOSRuntime

    host = SimpleNamespace(episodic_memory=memory, identity_registry=None)
    token = bind_cycle(registry.issue(kind="cognitive_cycle"))
    try:
        chain_id = current_cycle_id()
        await ProbOSRuntime._store_mcp_invoke_episode(
            host, server_url="mcp.ad1360", tool="status", tier="open", success=True, agent_id="ad1360-agent",
        )
    finally:
        unbind_cycle(token)
    await ProbOSRuntime._store_mcp_invoke_episode(
        host, server_url="mcp.ad1360", tool="survey", tier="open", success=True, agent_id="ad1360-agent",
    )
    records = _records(memory)
    assert records["[mcp_invoke] status on mcp.ad1360"] == (chain_id, VERDICT_RESOLVED)
    assert records["[mcp_invoke] survey on mcp.ad1360"] == ("", VERDICT_EMPTY)  # outside a cycle: S2b's


# -- N9, N10: crossing, a real proactive think to the Ward Room's records --------------------------------------------


async def test_a_proactive_observation_thread_records_the_thinks_cycle_id(
    memory: EpisodicMemory, registry: CycleIdRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bf934_world, "WardRoomService", functools.partial(WardRoomService, episodic_memory=memory))
    async with bf934_world.world(tmp_path) as w:
        w.rt.cycle_registry = registry
        channel = await _science_channel(w)
        await w.ws.create_thread(channel.id, "ad1360-peer", "[Observation] coolant", _OBSERVATION, author_callsign="Peer")
        agent, results = await _thinker(w)
        await bf934_world.think(w, agent)
    chain_id = result_cycle_id(results[0])
    records = _records(memory)
    assert len(results) == 1 and registry.kind_of(chain_id) == "cognitive_cycle"
    assert _only(records, "[Ward Room]", "Kira:") == (chain_id, VERDICT_RESOLVED)
    assert _only(records, "[Peer echo]") == (chain_id, VERDICT_RESOLVED)
    assert _only(records, "[Ward Room]", "Peer:") == ("", VERDICT_EMPTY)


async def test_a_reply_block_a_proactive_think_carries_out_records_the_thinks_cycle_id(
    memory: EpisodicMemory, registry: CycleIdRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bf934_world, "WardRoomService", functools.partial(WardRoomService, episodic_memory=memory))
    async with bf934_world.world(tmp_path) as w:
        w.rt.cycle_registry = registry
        channel = await _science_channel(w)
        thread = await w.ws.create_thread(
            channel.id, "captain", "Deck four", "What is on deck four today?", author_callsign="Captain",
        )
        agent, results = await _thinker(w, f"[REPLY {thread.id}]\n{_REPLY}\n[/REPLY]")
        for _ in range(5):
            w.rt.trust_network.record_outcome(agent.id, success=True)
        assert Rank.from_trust(w.rt.trust_network.get_score(agent.id)) is not Rank.ENSIGN  # premise: replies allowed
        await bf934_world.think(w, agent)
    chain_id = result_cycle_id(results[0])
    records = _records(memory)
    assert registry.kind_of(chain_id) == "cognitive_cycle"
    assert _only(records, "[Ward Room reply]", "Kira:") == (chain_id, VERDICT_RESOLVED)
    assert _only(records, "[Ward Room]", "Captain:") == ("", VERDICT_EMPTY)


# -- N11, N12: a promoted run's work item, registered so its outcome episode resolves --------------------------------


async def test_a_promoted_work_item_is_registered_when_made_so_its_outcome_episode_resolves(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    items = WorkItemStore(db_path=":memory:")
    await items.start()
    try:
        runtime = SimpleNamespace(work_item_store=items, cycle_registry=registry, episodic_memory=memory, registry=None)
        item = await turn_promotion._create_promoted_work_item(
            runtime=runtime, agent_id="ad1360-agent", thread_id="ad1360-thread", request_text="Survey the coolant loop.",
        )
        assert item is not None and registry.kind_of(item.id) == "work_item"
        await turn_promotion._store_promoted_episode(
            runtime=runtime, agent_id="ad1360-agent", thread_id="ad1360-thread", work_item_id=item.id,
            request_text="Survey the coolant loop.", body=_OBSERVATION, complete=True, failed=False,
        )
    finally:
        await items.stop()
    assert _only(_records(memory), "[1:1 background task]") == (item.id, VERDICT_RESOLVED)
    stray = MagicMock()
    turn_promotion._register_promoted_work_item(SimpleNamespace(cycle_registry=stray), "ad1360-item")
    turn_promotion._register_promoted_work_item(SimpleNamespace(), "ad1360-item")
    turn_promotion._register_promoted_work_item(SimpleNamespace(cycle_registry=registry), "   ")
    stray.register.assert_not_called()
    assert not registry.resolves("ad1360-item") and not registry.resolves("   ")


async def test_a_resumed_work_item_is_registered_again_after_a_restart(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    # ``registry`` is the one a restart left: it never saw the item promoted before it.
    item = SimpleNamespace(id="ad1360workitem", assigned_to="", metadata={"thread_id": "ad1360-thread"})
    runtime = SimpleNamespace(cycle_registry=registry, episodic_memory=memory, work_item_store=None, registry=None)
    assert not registry.resolves(item.id)
    await turn_promotion.resume_promoted_turn(runtime, item, "ad1360-request")
    assert registry.kind_of(item.id) == "work_item"
    await turn_promotion._store_promoted_episode(
        runtime=runtime, agent_id="ad1360-agent", thread_id="ad1360-thread", work_item_id=item.id,
        request_text="Survey the coolant loop.", body=_OBSERVATION, complete=True, failed=False,
    )
    assert _only(_records(memory), "[1:1 background task]") == (item.id, VERDICT_RESOLVED)
```

### 7.2 `src/probos/cycle_trace.py` (M1)

**C1.** SEARCH:
```
* ``CURRENT_CYCLE_ID`` carries the bound id. An awaited coroutine runs in its caller's context and a task copies the
  context it was created in (PEP 567), so code inside a bound cycle reads the id without a parameter. ``bind_cycle``
  returns the token ``unbind_cycle`` resets in a ``finally``, as ``admission/carrier.py`` does for the work ticket.
"""
```
REPLACE:
```
* ``CURRENT_CYCLE_ID`` carries the bound id. An awaited coroutine runs in its caller's context and a task copies the
  context it was created in (PEP 567), so code inside a bound cycle reads the id without a parameter. ``bind_cycle``
  returns the token ``unbind_cycle`` resets in a ``finally``, as ``admission/carrier.py`` does for the work ticket.
  AD-1360 S2a: ``cycle_scope`` binds a cycle's id again for work done for it after it has ended (the DM reply's steps,
  a proactive think's posts), and ``result_cycle_id`` reads that id off the cycle's ``IntentResult``.
"""
```
**C2.** SEARCH:
```
from collections import OrderedDict
from collections.abc import Callable
from contextvars import ContextVar, Token
```
REPLACE:
```
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
```
**C3.** SEARCH:
```
    try:
        CURRENT_CYCLE_ID.reset(token)
    except (RuntimeError, ValueError):
        pass
```
REPLACE:
```
    try:
        CURRENT_CYCLE_ID.reset(token)
    except (RuntimeError, ValueError):
        pass


@contextmanager
def cycle_scope(chain_id: str = "") -> Iterator[str]:
    """Bind ``chain_id`` for the block, or keep the bound id when it is blank or not a str; yields the id bound inside.

    On exit, by return, raise or cancellation, the id bound before the block is back, whatever the block bound in this
    context without resetting. For work done for a cycle after the cycle has ended (AD-1360 S2a).
    """
    bound = chain_id if type(chain_id) is str and chain_id.strip() else CURRENT_CYCLE_ID.get()
    token = CURRENT_CYCLE_ID.set(bound)
    try:
        yield bound
    finally:
        unbind_cycle(token)


def result_cycle_id(result: object) -> str:
    """The AD-492 id a cognitive cycle's ``IntentResult`` carries in ``metadata["correlation_id"]``; "" when there is no
    result, its metadata is not a dict, or the value is not a non-blank str."""
    metadata = getattr(result, "metadata", None)
    chain_id = metadata.get("correlation_id") if type(metadata) is dict else None
    return chain_id if type(chain_id) is str and chain_id.strip() else ""
```

### 7.3 Not used

The compound replay's early return gets the cycle's id from S1's `_carry_cycle_id`, so this slice edits nothing in `cognitive_agent.py` (section 0, P3; section 5, N7).

### 7.4 `src/probos/cognitive/dm/reply_pipeline.py` (M1)

**D1.** SEARCH:
```
    disclosure_for,
)
from probos.dm_reply import DmReply, ToolInvocations  # AD-1248 / AD-1295
```
REPLACE:
```
    disclosure_for,
)
from probos.cycle_trace import cycle_scope  # AD-1360 (#1828)
from probos.dm_reply import DmReply, ToolInvocations  # AD-1248 / AD-1295
```
**D2.** SEARCH:
```
    # AD-1156 A-4: the reply as plan mode's passes left it, before
    # ``step_4p_plan_mode_notice`` shows what they held back and adds the notice.
    # Step 5 stores it, with the notice; ``None`` until step 4p has one to add.
    plan_mode_reply_text: str | None = None
```
REPLACE:
```
    # AD-1156 A-4: the reply as plan mode's passes left it, before
    # ``step_4p_plan_mode_notice`` shows what they held back and adds the notice.
    # Step 5 stores it, with the notice; ``None`` until step 4p has one to add.
    plan_mode_reply_text: str | None = None
    # AD-1360 (#1828): the AD-492 id of the agent cycle this reply came from (its ``IntentResult.metadata``), set by
    # the one-to-one route; "" when no cycle ran or it carried none. ``_run_steps`` binds it and step 5 stores it.
    cycle_id: str = ""
```
**D3.** SEARCH:
```
        gate = self.ctx.plan_mode_gate
        for step in steps:
            try:
                if gate is not None and self._plan_mode_holds_back(step, gate):
                    continue
                await step()
            except Exception:
                logger.warning(
                    "AD-726: pipeline step %s raised for agent=%s; continuing",
                    step.__name__, self.ctx.agent_id, exc_info=True,
                )
```
REPLACE:
```
        gate = self.ctx.plan_mode_gate
        # AD-1360 (#1828): the steps run after the agent's cycle has ended and store episodes and post to the Ward Room
        # for it, so its AD-492 id is bound while they run; the id bound before is back afterwards.
        with cycle_scope(self.ctx.cycle_id):
            for step in steps:
                try:
                    if gate is not None and self._plan_mode_holds_back(step, gate):
                        continue
                    await step()
                except Exception:
                    logger.warning(
                        "AD-726: pipeline step %s raised for agent=%s; continuing",
                        step.__name__, self.ctx.agent_id, exc_info=True,
                    )
```
**D4.** SEARCH:
```
                    reflection=f"Captain had a 1:1 conversation with {self.ctx.callsign or self.ctx.agent_id} via HXI.",
                    source="direct",
```
REPLACE:
```
                    reflection=f"Captain had a 1:1 conversation with {self.ctx.callsign or self.ctx.agent_id} via HXI.",
                    source="direct",
                    correlation_id=self.ctx.cycle_id,  # AD-1360 (#1828): the cycle that answered
```

### 7.5 `src/probos/routers/agents.py` (M1)

**R1.** SEARCH:
```
    from probos.cognitive.dm import DmReplyContext, DmReplyPipeline
    from probos.dm_reply import DmReply, ToolInvocations, require_rendered  # AD-1248
```
REPLACE:
```
    from probos.cognitive.dm import DmReplyContext, DmReplyPipeline
    from probos.cycle_trace import result_cycle_id  # AD-1360 (#1828)
    from probos.dm_reply import DmReply, ToolInvocations, require_rendered  # AD-1248
```
**R2.** SEARCH:
```
        owned_steps_feedback=_owned_steps_capture_feedback,
        plan_mode_gate=_plan_mode_gate,  # AD-1156
    ))
```
REPLACE:
```
        owned_steps_feedback=_owned_steps_capture_feedback,
        plan_mode_gate=_plan_mode_gate,  # AD-1156
        cycle_id=result_cycle_id(result),  # AD-1360 (#1828): the agent cycle this reply came from
    ))
```

### 7.6 `src/probos/experience/commands/session.py` (M1)

**H1.** SEARCH:
```
        from probos.types import IntentMessage, Episode, AnchorFrame, EPISODE_PLAN_MODE_KEY

        intent = IntentMessage(
```
REPLACE:
```
        from probos.types import IntentMessage, Episode, AnchorFrame, EPISODE_PLAN_MODE_KEY
        from probos.cycle_trace import result_cycle_id  # AD-1360 (#1828)

        intent = IntentMessage(
```
**H2.** SEARCH:
```
                    reflection=f"Captain had a 1:1 conversation with {self.callsign}.",
                    source="direct",
```
REPLACE:
```
                    reflection=f"Captain had a 1:1 conversation with {self.callsign}.",
                    source="direct",
                    correlation_id=result_cycle_id(result),  # AD-1360 (#1828): the agent cycle that answered
```

### 7.7 `src/probos/ward_room/messages.py` (M1)

**W1.** SEARCH:
```
from typing import Any, Callable

from probos.ward_room.models import (
```
REPLACE:
```
from typing import Any, Callable

from probos.cycle_trace import current_cycle_id  # AD-1360 (#1828)
from probos.ward_room.models import (
```
**W2.** SEARCH:
```
                    reflection=f"{author_callsign or author_id} replied in thread '{thread_title[:60]}': {body[:300]}",
                    source="direct",
```
REPLACE:
```
                    reflection=f"{author_callsign or author_id} replied in thread '{thread_title[:60]}': {body[:300]}",
                    source="direct",
                    correlation_id=current_cycle_id(),  # AD-1360 (#1828): the cycle the post is made in; "" outside one
```
**W3.** SEARCH:
```
                        f"System detected overlap between my reply and "
                        f"{top_match['author_callsign']}'s recent contribution. "
                        f"Similarity: {top_match['similarity']:.0%}."
                    ),
                    source="direct",
```
REPLACE:
```
                        f"System detected overlap between my reply and "
                        f"{top_match['author_callsign']}'s recent contribution. "
                        f"Similarity: {top_match['similarity']:.0%}."
                    ),
                    source="direct",
                    correlation_id=current_cycle_id(),  # AD-1360 (#1828): the cycle the post is made in; "" outside one
```

### 7.8 `src/probos/ward_room/threads.py` (M1)

**T1.** SEARCH:
```
from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.ward_room.models import WardRoomThread, extract_mentions
```
REPLACE:
```
from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.cycle_trace import current_cycle_id  # AD-1360 (#1828)
from probos.ward_room.models import WardRoomThread, extract_mentions
```
**T2.** SEARCH:
```
                    reflection=f"{author_callsign or author_id} posted to {ch_name}: {title[:100]}",
                    source="direct",
```
REPLACE:
```
                    reflection=f"{author_callsign or author_id} posted to {ch_name}: {title[:100]}",
                    source="direct",
                    correlation_id=current_cycle_id(),  # AD-1360 (#1828): the cycle the thread is made in; "" outside one
```
**T3.** SEARCH:
```
                        f"System detected overlap between my post and "
                        f"{top_match['author_callsign']}'s recent contribution. "
                        f"Similarity: {top_match['similarity']:.0%}."
                    ),
                    source="direct",
```
REPLACE:
```
                        f"System detected overlap between my post and "
                        f"{top_match['author_callsign']}'s recent contribution. "
                        f"Similarity: {top_match['similarity']:.0%}."
                    ),
                    source="direct",
                    correlation_id=current_cycle_id(),  # AD-1360 (#1828): the cycle the thread is made in; "" outside one
```

### 7.9 `src/probos/runtime.py` (M1)

**U1.** SEARCH (whole line `:150`):
```
from probos.cycle_trace import CycleIdRegistry  # AD-1360 (#1828)
```
REPLACE:
```
from probos.cycle_trace import CycleIdRegistry, current_cycle_id  # AD-1360 (#1828)
```
**U2.** SEARCH:
```
                dag_summary={},
                anchors=AnchorFrame(channel="mcp", trigger_type="mcp_invoke"),
            )
```
REPLACE:
```
                dag_summary={},
                anchors=AnchorFrame(channel="mcp", trigger_type="mcp_invoke"),
                # AD-1360 (#1828): the agent's cycle when the agentic loop invokes the tool inside one; "" outside one.
                correlation_id=current_cycle_id(),
            )
```

### 7.10 `src/probos/proactive.py` (M2)

**P1.** SEARCH:
```
from probos.crew_profile import Rank
from probos.crew_utils import is_crew_agent
from probos.cognitive.cognitive_agent import CognitiveAgent
```
REPLACE:
```
from probos.crew_profile import Rank
from probos.crew_utils import is_crew_agent
from probos.cycle_trace import cycle_scope, result_cycle_id  # AD-1360 (#1828)
from probos.cognitive.cognitive_agent import CognitiveAgent
```
**P2.** SEARCH:
```
            if not standing_settled:
                self._standing_interests.restore_notices(agent.id, standing_taken)
        if not result or not result.success or not result.result:
```
REPLACE:
```
            if not standing_settled:
                self._standing_interests.restore_notices(agent.id, standing_taken)
        # AD-1360 (#1828): the think's cycle has ended; what this method posts for it below runs with the cycle's id
        # bound again (cycle_scope), so the Ward Room records each post's episode against that cycle.
        _cycle_id = result_cycle_id(result)
        if not result or not result.success or not result.result:
```
**P3.** SEARCH:
```
        cleaned_text, actions_taken = await self._extract_and_execute_actions(
            agent, response_text
        )
        if cleaned_text != response_text:
```
REPLACE:
```
        with cycle_scope(_cycle_id):  # AD-1360: a reply, thread or DM a block posts is the cycle's
            cleaned_text, actions_taken = await self._extract_and_execute_actions(
                agent, response_text
            )
        if cleaned_text != response_text:
```
**P4.** SEARCH:
```
        if await self._post_to_ward_room(agent, response_text):  # BF-934: True once a thread was created
            actions_taken.append({"type": "ward_room_post"})
```
REPLACE:
```
        with cycle_scope(_cycle_id):  # AD-1360: the observation's thread is the cycle's
            _posted = await self._post_to_ward_room(agent, response_text)
        if _posted:  # BF-934: True once a thread was created
            actions_taken.append({"type": "ward_room_post"})
```

### 7.11 `src/probos/cognitive/turn_promotion.py` (M2)

**K1.** SEARCH:
```
)
from probos.tools.executor import recording_identity, sample_recording_identity
```
REPLACE:
```
)
from probos.cycle_trace import CycleIdRegistry  # AD-1360 (#1828)
from probos.tools.executor import recording_identity, sample_recording_identity
```
**K2.** SEARCH:
```
async def _create_promoted_work_item(
    *,
    runtime: Any,
```
REPLACE:
```
def _register_promoted_work_item(runtime: Any, work_item_id: object) -> None:
    """AD-1360 (#1828): adopt a promoted run's work-item id into the runtime's cycle-id registry.

    BF-740 pairs the run's outcome episode by ``correlation_id`` = the work item, not a cycle id; registered here, when
    the item is made and again on each resume (a restart forgets every id), it resolves when that episode is stored.
    Nothing is registered without a ``CycleIdRegistry`` on the runtime or for a blank id.
    """
    registry = getattr(runtime, "cycle_registry", None)
    if isinstance(registry, CycleIdRegistry) and type(work_item_id) is str and work_item_id.strip():
        registry.register(work_item_id, kind="work_item")


async def _create_promoted_work_item(
    *,
    runtime: Any,
```
**K3.** SEARCH:
```
    if item is None:
        return None
    # ``task`` starts ``open``; the run is already executing, so the board must
    # say so. ``open -> in_progress`` requires an assignee, which is set above.
```
REPLACE:
```
    if item is None:
        return None
    _register_promoted_work_item(runtime, getattr(item, "id", ""))  # AD-1360 (#1828)
    # ``task`` starts ``open``; the run is already executing, so the board must
    # say so. ``open -> in_progress`` requires an assignee, which is set above.
```
**K4.** SEARCH:
```
    item = await _resumed_item_now(runtime, item, work_item_id, request_id)
    if item is None:
        return RESUME_MOVED_ON
```
REPLACE:
```
    item = await _resumed_item_now(runtime, item, work_item_id, request_id)
    if item is None:
        return RESUME_MOVED_ON
    _register_promoted_work_item(runtime, work_item_id)  # AD-1360 (#1828): again on resume; a restart forgot it
```

### 7.12 `PROGRESS.md` (M3; anchors exist after S1's M3)

**G1.** SEARCH (whole line `:1`, once): `# ProbOS Progress`. REPLACE:
```markdown
# ProbOS Progress

**AD-1360 S2a (2026-11-21), #1828 -- producers that store an episode inside or after a cognitive cycle record that cycle's AD-492 id.** The Ward Room's four direct episodes (a thread, a reply, and the AD-506b peer-echo note for each) and the MCP-invoke episode take the id bound in their context. Work done for a cycle after it has ended runs with the cycle's id bound again (`cycle_trace.cycle_scope`): the 1:1 DM reply's steps, and a proactive think's observation thread and action blocks. The 1:1 DM route and the shell session store their turn's episode with the id the cycle's `IntentResult.metadata` carries (`cycle_trace.result_cycle_id`). A promoted run's work-item id is registered when the item is made and on each resume. Outside a cycle every changed producer stores the empty id it stored before, and the cutoff stays at 0.0. Measured by `tests/test_ad1360_s2a_producers.py` (11 cases), from real producers into a real ChromaDB-backed memory: each episode records `resolved`; posts made outside any cycle record `empty`. The live vessel was not measured. Producers outside any cycle and the guard test are AD-1360 S2b. Contract `prompts/ad-1360-s2a-cycle-and-post-cycle-producers.md`.
```
**G2.** SEARCH (substring of S1's entry, once): `Producers outside a cognitive cycle are AD-1360 S2a and S2b.` REPLACE: `Producers outside a cognitive cycle are AD-1360 S2b; S2a (above) covers those inside or after one.`

### 7.13 `DECISIONS.md` (M3)

**J1.** SEARCH (whole line, S1's last bullet, once):
```
- *Residual.* #1820 items ad-1360 R1 to R3. *Reversal.* Revert the S1 commits; the two keys stay on stored rows and the old reader ignores them.
```
REPLACE:
```markdown
- *Residual.* #1820 items ad-1360 R1 to R3. *Reversal.* Revert the S1 commits; the two keys stay on stored rows and the old reader ignores them.
- *S2a (2026-11-21), D7 (where a producer's id comes from).* Inside a cycle, `current_cycle_id()` at the site: the Ward Room's four direct episodes and the MCP-invoke episode. After the cycle, either the producer binds the result's id with `cycle_scope` around the work it does for the cycle (the DM reply's `_run_steps`; a proactive think's action blocks and observation thread), or reads `result_cycle_id(result)` at the site (the DM route into `DmReplyContext.cycle_id`; the shell session). Rejected: a `correlation_id` parameter on `create_thread`/`create_post` (52 call sites), and wrapping `_think_for_agent`'s body in a renamed method (it would move the `handle_intent` call that `tests/fixtures/ad1343_seam_registry.py:174` pins).
- *S2a D8 (work items).* `_create_promoted_work_item` and `resume_promoted_turn` register the item's id, the two seams every promoted run passes. Registering at store time was rejected: it would certify any id handed to `store()`.
- *S2a measured.* `tests/test_ad1360_s2a_producers.py` (11 cases) on a real ChromaDB-backed memory. That the agentic tool loop runs inside the cycle is read, not tested (`finalize.py:5131`, `agentic_dispatch.py:1937`).
- *S2a disclosed effects.* Episodes that stored `""` now carry an id: the DM and shell 1:1 turns, and Ward Room posts and MCP invokes made in or for a cycle. `procedure_challenger.py:259` pins every episode carrying the source turn's id, which now includes a Ward Room reply that turn posted. A promoted run's acknowledgement carries the DM cycle's id and its outcome the work item's, so AD-1166's pairing by `correlation_id` is still not made (as before; considered, deferred). A reply from a federated peer would carry the peer's id, which records `unresolved` here (it recorded `empty` before).
- *S2a scope moved to S2b.* The quartermaster, `ground_truth.py:220` and the HXI Ward Room routes run outside any cycle. Found dead: `proactive.py:1525` (`should_store` rejects every episode it builds) and `:1802` (unreachable, and `context` is undefined there). S2b disposes of both.
```
**Ledger:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`. Regenerate and commit in M3 only if it reports drift. No `roadmap.md` row.

## 8. What this does NOT change

- Every `enforce_*` default and `correlation_cutoff` (0.0); profiles; `KNOWN_MEMORY_SOURCES`; `compute_episode_hash`; `store()`; the registry.
- Producers outside a cycle (section 6); `thread_fanout.py` (the escalation subset writes no direct episode, `reply_pipeline.py:535-545`).
- `_think_for_agent`'s signature and its `handle_intent` call; `_run_cycle`; the AD-1343/AD-1346 censuses.
- BF-740's `correlation_id=work_item_id` (`turn_promotion.py:1591`).

## 9. Mutation rows (campaign on the M2 candidate)

| Row | Mutant | Killed by |
|---|---|---|
| M1 | `cycle_scope` binds the outer id for a non-empty `chain_id` | N1, N3, N9 |
| M2 | `cycle_scope` does not reset | N1 |
| M3 | `cycle_scope("")` clears the outer id | N1 |
| M4 | `result_cycle_id` always `""` | N2, N4, N5, N9 |
| M5 | `result_cycle_id` accepts a non-str or blank value | N2 |
| M6 | route omits `cycle_id=` | N4 |
| M7 | step 5 omits `correlation_id=` | N4 |
| M8 | `_run_steps` binds nothing | N3 |
| M9 | session omits `correlation_id=` | N5 |
| M10, M11 | `messages.py` reply / peer-echo omits it | N6 |
| M12, M13 | `threads.py` thread / peer-echo omits it | N9 |
| M14 | a Ward Room site uses `new_cycle_id()` | N6 (`unresolved`), N9 |
| M17 | MCP site omits it | N8 |
| M18 | no scope around `_post_to_ward_room` | N9 |
| M19 | no scope around the actions | N10 |
| M20 | creation does not register | N11 |
| M21 | resume does not register | N12 |
| M22 | `_register_promoted_work_item` accepts any registry | N11 (MagicMock) |
| M23 | blank-id guard removed | N11 (`register` raises) |

M15 and M16 are not used: they mutated the compound return and `_build_result_metadata`'s id line, which this slice no longer edits (S1's rows RM2 to RM6 and its cases N30 and N33 cover them). The other labels keep their numbers.

## 10. Verified Against Codebase (2026-11-21, this tree)

```
rg -n "def current_cycle_id|def bind_cycle|def unbind_cycle|def issue|def register|def kind_of" src/probos/cycle_trace.py   51,56,63,112,119,130
rg -n "_run_cycle_bound_lifecycle|_run_cognitive_lifecycle\(" src   cognitive_agent.py:7607,7621,7625,8134,8312,8336
rg -n "return IntentResult\(|metadata=" src/probos/cognitive/cognitive_agent.py   7839 (built by hand; S1's `_carry_cycle_id` covers it), 8104/8120, 8129, 8163
rg -n "_self_post_ward_room_response\(|process_and_post\(" src   cognitive_agent.py:7569,8096,7593; ward_room_pipeline.py:247
rg -n "Episode\(" <S2a files>   messages.py:344,388 threads.py:586,630 reply_pipeline.py:1202,2553 proactive.py:1525,1802 turn_promotion.py:1587 runtime.py:5219,5562,6160,7009 quartermaster.py:202,471 ground_truth.py:220 crew_synth.py:646,1302 __main__.py:2343
rg -n "DmReplyContext\(" src   routers/agents.py:3810, routers/thread_fanout.py:848, reply_pipeline.py:2715
rg -n "\"from\": \"hxi_profile\"" src/probos/routers/agents.py   3597
rg -n "_think_for_agent\(" src   proactive.py:1210,1354
rg -n "_create_promoted_work_item\(|resume_promoted_turn\(" src   turn_promotion.py:2283,2489,2915; capability_gap_driver.py:331; promoted_turn_recovery.py:178
rg -n "MAX_EPISODES_PER_HOUR =|SIMILARITY_THRESHOLD =" src/probos/cognitive/episodic.py   1375 (20), 1377 (0.8)
rg -n "TRUST_LIEUTENANT" src/probos/config.py   218 (0.5)
git ls-files --eol <9 edited tracked files>   all i/lf w/crlf
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py   CEILING AD-1361
```

## Absence Verified (2026-11-21)

| Claim | Run | Found | Holds |
|---|---|---|---|
| No S2a name exists in `src` | `rg -n "cycle_scope\|result_cycle_id\|_register_promoted_work_item" src` | none (`_register_work_item_pull_tools` in `startup/communication.py:215` is a different name, so I chose a distinct one) | yes |
| The compound return is the lifecycle's only output-bearing result without metadata | `rg -n "return IntentResult\(" cognitive_agent.py`, lifecycle range `:7625-8121` | `:7839` (covered by S1's `_carry_cycle_id`), `:8104` (has it) | yes |
| No test pins an S2a producer's empty id | section 3 commands | none | yes |
| `ground_truth` writer has no caller | `rg -n "verification_episode_writer\|\.write\(result\)" src` | only assignments at `finalize.py:4834,4838,4899` | yes |
| Proactive `:1802` is unreachable and broken | `rg -n "\bcontext\b" proactive.py` | first binding in `_gather_context` `:1875`; `:1781` reads it in `_think_for_agent` | yes |
| `:1525` never stores | `test_selective_encoding.py:16-21` | `should_store` is False for that exact shape | yes |
| Ward Room callers of `create_thread`/`create_post` | `rg -n "\.(create_post\|create_thread)\(" src` | 52 hits, classified: in-cycle (AD-654a pipeline, recreation extraction), S2a-bound (proactive, DM pipeline), S2b (routers, notifiers, startup, system) | yes |

## 11. Deterministic checks

- **Focused gate, `-n 0`:**
  - `tests/test_ad1360_s2a_producers.py`, `tests/test_ad1360_s1_cycle_trace.py`
  - `tests/test_ad726_dm_reply_pipeline.py`, `tests/test_ad791a_chat_threads_wiring.py`, `tests/test_bf795_episode_carries_the_tool_facts.py`, `tests/test_ad1156_plan_mode_learning.py`, `tests/test_ad1156_plan_mode_side_effects.py`, `tests/test_ad1156_plan_execute_mode.py`, `tests/test_ad933_group_chat_escalation.py`, `tests/test_bf296_dm_outbound_in_reply.py`, `tests/test_ad1248_slice_b.py`, `tests/test_session_manager.py`
  - `tests/test_ward_room.py`, `tests/test_ward_room_agents.py`, `tests/test_selective_encoding.py`, `tests/test_bf164_stale_unread_dm.py`, `tests/test_ad654a_async_dispatch.py`
  - `tests/test_proactive.py`, `tests/test_bf934_s1_decision_routing.py`, `tests/test_bf934_s2_secondary_gates.py`, `tests/test_bf934_s3_intended_actions_ledger.py`, `tests/test_bf976_withdrawal_ledger.py`, `tests/test_bf874_dm_e2e.py`, `tests/test_ad1228_standing_interests.py`, `tests/test_bf925_event_log_window.py`, `tests/test_ad617b_per_agent_token_budget.py`
  - `tests/test_ad1343_seam_registry.py`, `tests/test_ad1343_stop_seam_inventory.py`, `tests/test_ad1343_stop_crossing.py`
  - `tests/test_ad1165_turn_promotion.py`, `tests/test_bf740_correlation_id_persists.py`, `tests/test_bf887_continue_resumes_the_promoted_turn.py`, `tests/test_ad855_block_resume.py`, `tests/test_ad1323_continue_extension_restart.py`
  - `tests/test_ad1019c_consensus.py`, `tests/test_ad492_cognitive_correlation_ids.py`, `tests/test_bf938_episode_source_guard.py`, `tests/test_layer_boundaries.py`, `tests/test_ad1184_ad_ledger.py`
- **`rg` checks:**
  - `rg -n "cycle_scope\(" src/probos` gives `reply_pipeline.py` `_run_steps` and two `with` statements in `proactive.py` `_think_for_agent`, nothing else.
  - `rg -n "\.register\(.*kind=\"work_item\"" src` gives only `turn_promotion.py`.
- **Broad gate:** once, after S2b, with the S1 label (`ad-1360-1828`).

## 12. Prior art and blind spots

- **Internal:** S1 section 13 (OpenTelemetry's attach/detach pattern) is reused. `cycle_scope` is OTel's "attach a stored context for deferred work" (`context.attach`/`detach` in a `finally`).
- **External:** skipped. This is ProbOS plumbing, and S1 checked `reference-projects.md` on 2026-11-20 and found no relevant row; not re-run.
- **Blind spots named:**
  - A task created inside a scope inherits the id (PEP 567). Long work started there resolves until the TTL; S3 measures the TTL.
  - A non-cognitive agent awaited inside a cycle inherits the caller's id, which is the caller's own provenance.
  - A federated reply's foreign id records `unresolved` (disclosed above).
  - Dead proactive sites go to S2b.

## 13. Diff Reviewer: properties to verify

1. Every new `correlation_id=` reads `current_cycle_id()`, `self.ctx.cycle_id` or `result_cycle_id(result)`. None is a constant or a freshly minted id; BF-740's id is unchanged.
2. Every `cycle_scope` is a `with` whose block holds only work done for that cycle, and it restores the outer id on return, raise and cancellation.
3. Outside any bound cycle, each changed producer stores exactly what it stored before. With the cutoff at 0.0, no recall result or event changes.
4. This slice does not edit `cognitive_agent.py` or `_build_result_metadata`; the id it reads from a cycle's result (`result_cycle_id`) is the one S1's `_carry_cycle_id` guarantees on every result the lifecycle returns.
5. `_think_for_agent` keeps its name, signature and `handle_intent` call; `_run_cycle` is untouched.
6. `DmReplyContext.cycle_id` is defaulted and last; only the 1:1 route sets it.
7. `_register_promoted_work_item` registers only into a `CycleIdRegistry` with a non-blank `str`, and never raises for a MagicMock runtime.
8. New imports are `probos.cycle_trace` only (standard library, layer-safe). `cycle_trace.py` still imports only the standard library.
9. The test file is ASCII and pins no source line.

## 14. Acceptance

- [ ] Section 5 predictions hold after M1 and M2; the section 11 focused gate is green.
- [ ] Mutation rows M1-M14 and M17-M23 are killed by the named cases.
- [ ] Section 11's `rg` checks hold.
- [ ] G1-G2 and J1 are applied after S1's M3; the ledger check passes.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. The orchestrator's first-hand checks (2026-11-21, a scratch tree detached at `f4ccb082` (S1's last code and test commit) and the pairs of section 7)

Every pair of section 7 was applied to a scratch worktree by `audit\contract_tools.py` (ASCII only: no `--utf8` was needed), and every check below was run, before the Builder started. Each test run went through `run_pytest_homeguard.ps1` (a redirected, empty home: entries left in it 0). Results:

| O | Result |
|---|---|
| O1 | All 31 operations (the new test file and 30 pairs: C1-C3, D1-D4, R1-R2, H1-H2, W1-W3, T1-T3, U1-U2, P1-P4, K1-K4, G1-G2, J1) are found by `contract_tools.py list --prefix 7.`; every SEARCH occurs exactly once on the S1 tree (the substring G2 once), in files that are CRLF throughout; the new test file was absent. |
| O2 | The new test file alone on the S1 tree: **a collection error**, `ImportError: cannot import name 'cycle_scope' from 'probos.cycle_trace'`, as section 5 says. |
| O3 | After the new test file and the M1 pairs (7.1, 7.2 and 7.4 to 7.9): **4 failed, 7 passed**: the four reds are N9 to N12, the proactive think and the promoted run, which need M2. After the M2 pairs (7.10 and 7.11): **11 passed**. |
| O4 | **The focused gate** (section 11's list: 39 files, the new test file and S1's among them; on the scratch tree with the trackers and the regenerated ledger), under the default embeddings and under `PROBOS_EMBEDDINGS=local` as CI sets it: **1341 passed under the default embeddings (537 s) and 1341 passed under `PROBOS_EMBEDDINGS=local` (831 s)**, four workers, other tests running on the host meanwhile; no failure and no error. |
| O5 | **The wide consumer run**, made on an earlier oracle (S1 as first drafted, and this slice's pairs including the compound-return pairs A1 to A3 that were dropped afterwards, so it covered a superset of the code this contract applies): every test file under `tests/` that names a producer S2a changed (the DM reply pipeline, the shell session, the Ward Room messages and threads, the proactive loop, turn promotion, the MCP episode, `cycle_trace`, `handle_intent`), **401 files** in two chunks. Chunk 0 (201 files): **6739 passed, 1 skipped**. Chunk 1 (200 files): **6185 passed, 21 skipped**. No failure, so no pair was added to the draft's. |
| O6 | **The mutation campaign** (section 9; `mutants_gen.py` over `rows_ad1360s2a.py`: each row changes one line of the candidate in place, and its unmutated baseline had to be all green): rows M1 to M23 without M15 and M16 (dropped with the compound-return pairs), with M14 split in two (the post site of `messages.py`, killed by N6, and the thread site of `threads.py`, killed by N9: the draft's one row named both killers, and the post site is not driven by N9) = 22 rows over a baseline of 11 cases: **killed 22, differs 0, survived 0, invalid 0**; every named killer failed in every row (M1, M2, M3, M4, M10, M14 and M14b also failed more cases than the draft named). |
| O7 | The trackers G1-G2 and J1 applied on the scratch tree (each SEARCH once), then `gen_ad_ledger.py` regenerated the ledger pair and `--check` reported "AD/BF ledger is current". |
| O8 | The AD-1343 seam tests and BF-938's census are in the focused gate (O4) and green. |
| O9 | **Re-checked on this branch before the Builder started** (2026-11-21, on main after the pull request for #1838 with S1 committed on it): `contract_tools.py checkpoints` with `--prefix 7.` on this branch at `a4012763` (S1 as approved) found all 31 operations, each SEARCH exactly once, exit 0 and nothing on stderr; the blobs of the twelve files after operation 31 equal those of the scratch tree of O1 to O7 (`check_blobs_table.py`: 12 files checked, 0 differences). |

**What the orchestrator changed in the Architect's draft:** the pair labels and the two headings that the tool reads; the mutation row M14 (one row became two, O6); the placeholder of this section; and, on the Architect's decision of 2026-11-21, the compound-return edit: S1's repair (`_carry_cycle_id`, called in `_run_cycle_bound_lifecycle`) puts the cycle's id on every result a cycle returns, the compound replay's included, so the draft's pairs A1 to A3, its case N7, its mutation rows M15 and M16, the J2 tracker pair and the sentences that depended on them are dropped (section 7.3 is not used; the labels N8 to N12 and M17 to M23 keep their numbers).

**What these checks do not show.**
- The vessel: nothing here ran against `%LOCALAPPDATA%\ProbOS\data`. The cutoff ships at 0.0, so no recall result changes until S3 arms it.
- The producers outside any cycle (section 6) still store an id the registry never issued, or none: S2b.
- That a proactive think's posts, a DM reply's episode or a promoted run's outcome are reached inside a cycle on a live vessel is read from the code and exercised by real producers over a real memory, not measured.

## 16. Repair after review round 1 (2026-11-21)

Round 1 (`gpt-6.1-sol`, 17 minutes, the committed candidate `a4012763..8c8ce27a`) requested changes: one finding, P2, ordinary reach, new in this slice, size findings 0. The orchestrator reproduced it before repairing it (section 16.7).

**R1. A DM whose reply the sanity gate retried stores the first cycle's id.** `DmReplyPipeline.step_1_sanity_gate_retry` asks the agent again when the gate rejects the reply (AD-724-1, on by default) and replaces the reply with the retry's answer (`replaced_by`). The retry is a second cycle with its own id, and `DmReplyContext.cycle_id` still holds the first cycle's. `_run_steps` bound that id once around the whole tuple, so the DM episode (step 5) and every Ward Room post a later step makes from the replacement name the cycle whose reply was thrown away, and record `resolved` against it. Repair: step 1 takes the retry's id with its reply (`result_cycle_id(retry_resp)`; a retry result that carries none keeps the first cycle's), and `_run_steps` binds the context's current id for each step instead of once, so the steps after the retry see the new one. A reply that was not replaced (the retry returned nothing, or failed) keeps the first id, as before.

No design decision is open: the repair is the reviewer's smallest fix. Nothing in sections 1 to 15 changes except the number of cases of the new test file, which is 14 instead of 11 (section 16.2; the trackers of sections 16.3 and 16.4 say 14).

### 16.1 `src/probos/cognitive/dm/reply_pipeline.py` (M-R1)

**RA1.** SEARCH:
```
from probos.cycle_trace import cycle_scope  # AD-1360 (#1828)
```
REPLACE:
```
from probos.cycle_trace import cycle_scope, result_cycle_id  # AD-1360 (#1828)
```
**RA2.** SEARCH:
```
        # AD-1360 (#1828): the steps run after the agent's cycle has ended and store episodes and post to the Ward Room
        # for it, so its AD-492 id is bound while they run; the id bound before is back afterwards.
        with cycle_scope(self.ctx.cycle_id):
            for step in steps:
                try:
                    if gate is not None and self._plan_mode_holds_back(step, gate):
                        continue
                    await step()
                except Exception:
                    logger.warning(
                        "AD-726: pipeline step %s raised for agent=%s; continuing",
                        step.__name__, self.ctx.agent_id, exc_info=True,
                    )
```
REPLACE:
```
        # AD-1360 (#1828): the steps run after the agent's cycle has ended and store episodes and post to the Ward Room
        # for it, so its AD-492 id is bound while each runs; the id bound before is back afterwards. Bound per step:
        # step 1 can adopt a retry's reply, and with it the id of the cycle that answered.
        for step in steps:
            with cycle_scope(self.ctx.cycle_id):
                try:
                    if gate is not None and self._plan_mode_holds_back(step, gate):
                        continue
                    await step()
                except Exception:
                    logger.warning(
                        "AD-726: pipeline step %s raised for agent=%s; continuing",
                        step.__name__, self.ctx.agent_id, exc_info=True,
                    )
```
**RA3.** SEARCH:
```
                        self.ctx.reply = self.ctx.reply.replaced_by(
                            DmReply.from_intent_result(retry_resp).with_body(
                                retry_result.cleaned_text
                            )
                        )
```
REPLACE:
```
                        self.ctx.reply = self.ctx.reply.replaced_by(
                            DmReply.from_intent_result(retry_resp).with_body(
                                retry_result.cleaned_text
                            )
                        )
                        # AD-1360 (#1828): the reply now comes from the retry's own cycle, so the steps after this one
                        # (the DM episode, the Ward Room posts) belong to it; a retry result with no id keeps this one.
                        self.ctx.cycle_id = result_cycle_id(retry_resp) or self.ctx.cycle_id
```

### 16.2 `tests/test_ad1360_s2a_producers.py` (M-R1)

Three cases are added: N14 (a step that changes the context's id: the steps after it run under the new one), N13 (the Captain's DM route when the real sanity gate asks again: the DM episode carries the retry's id, which the registry issued, not the first cycle's) and N15 (the retry's result carries no id: the first cycle's stays in place). The file has 14 cases.

**RT1.** SEARCH:
```
    assert seen == ["feedfacecafe", "feedfacecafe", "feedfacecafe", "0123456789ab"]
```
REPLACE:
```
    assert seen == ["feedfacecafe", "feedfacecafe", "feedfacecafe", "0123456789ab"]


async def test_a_step_that_changes_the_cycle_id_binds_the_new_one_for_the_steps_after_it() -> None:
    seen: list[str] = []
    pipeline = DmReplyPipeline(_ctx(cycle_id="feedfacecafe"))

    async def adopts() -> None:
        seen.append(current_cycle_id())
        pipeline.ctx.cycle_id = "0123456789ab"

    async def probe() -> None:
        seen.append(current_cycle_id())

    await pipeline._run_steps((adopts, probe))
    assert seen == ["feedfacecafe", "0123456789ab"] and current_cycle_id() == ""
```
**RT2.** SEARCH:
```
    assert _only(_records(memory), "[1:1 with") == (chain_id, VERDICT_RESOLVED)
```
REPLACE:
```
    assert _only(_records(memory), "[1:1 with") == (chain_id, VERDICT_RESOLVED)


async def test_a_dm_whose_reply_the_gate_retried_stores_the_id_of_the_cycle_that_answered(
    memory: EpisodicMemory, registry: CycleIdRegistry, tmp_path: Path,
) -> None:
    from probos.routers.agents import agent_chat

    agent = _Agent()
    agent._runtime = _cycle_runtime(memory, registry)
    results: list[IntentResult] = []
    cycle = _recording(agent, results)
    answers = iter((_REPLY + " []", _OBSERVATION))  # the real gate rejects an empty tag pair and asks again

    async def _send(intent: IntentMessage, **kwargs: Any) -> IntentResult:
        agent.answer = next(answers)
        return await cycle(intent, **kwargs)

    rt = _route_runtime(tmp_path, modes=False)
    rt.registry.get.return_value.sovereign_id = "ad1360-dm-agent"
    rt.episodic_memory = memory
    rt.intent_bus.send = AsyncMock(side_effect=_send)
    with patch("probos.routers.agents.is_crew_agent", return_value=True):
        await agent_chat("test-agent", _chat_request(_QUESTION), rt)
    assert len(results) == 2
    first, retry = (result_cycle_id(result) for result in results)
    assert first != retry and registry.kind_of(first) == registry.kind_of(retry) == "cognitive_cycle"
    assert _only(_records(memory), "[1:1 with") == (retry, VERDICT_RESOLVED) and current_cycle_id() == ""


async def test_a_retry_result_that_carries_no_cycle_id_leaves_the_first_cycles_id_in_place(
    memory: EpisodicMemory, registry: CycleIdRegistry, tmp_path: Path,
) -> None:
    from probos.routers.agents import agent_chat

    agent = _Agent()
    agent._runtime = _cycle_runtime(memory, registry)
    results: list[IntentResult] = []
    cycle = _recording(agent, results)

    async def _send(intent: IntentMessage, **kwargs: Any) -> IntentResult:
        if results:  # the retry: a result no cycle built, so it carries no id
            return IntentResult(intent_id=intent.id, agent_id=agent.id, success=True, result=_OBSERVATION)
        agent.answer = _REPLY + " []"  # the real gate rejects an empty tag pair and asks again
        return await cycle(intent, **kwargs)

    rt = _route_runtime(tmp_path, modes=False)
    rt.registry.get.return_value.sovereign_id = "ad1360-dm-agent"
    rt.episodic_memory = memory
    rt.intent_bus.send = AsyncMock(side_effect=_send)
    with patch("probos.routers.agents.is_crew_agent", return_value=True):
        await agent_chat("test-agent", _chat_request(_QUESTION), rt)
    assert len(results) == 1 and rt.intent_bus.send.await_count == 2
    assert _only(_records(memory), "[1:1 with") == (result_cycle_id(results[0]), VERDICT_RESOLVED)
```

### 16.3 `PROGRESS.md` (M-R1)

**TR1.** SEARCH (substring of S2a's entry, once): `(11 cases), from real producers`. REPLACE: `(14 cases), from real producers`.

### 16.4 `DECISIONS.md` (M-R1)

**TR2.** SEARCH (whole line, once):
```
- *S2a measured.* `tests/test_ad1360_s2a_producers.py` (11 cases) on a real ChromaDB-backed memory. That the agentic tool loop runs inside the cycle is read, not tested (`finalize.py:5131`, `agentic_dispatch.py:1937`).
```
REPLACE:
```
- *S2a measured.* `tests/test_ad1360_s2a_producers.py` (14 cases) on a real ChromaDB-backed memory. That the agentic tool loop runs inside the cycle is read, not tested (`finalize.py:5131`, `agentic_dispatch.py:1937`).
- *S2a repair after review round 1.* A DM whose sanity gate asks again takes the id of the retry's cycle together with the retry's reply (`step_1_sanity_gate_retry`), and `_run_steps` binds the context's current id for each step, so the DM episode and the Ward Room work made from the replacement name the cycle that answered. A retry result that carries no id keeps the first cycle's id. Pinned by three cases of `tests/test_ad1360_s2a_producers.py`.
```

### 16.5 Mutation rows (campaign on the repaired tree; restore between rows)

`mutants_gen.py` over `audit\rows_ad1360s2ar1.py`: each row changes one line of the repaired tree in place and runs the new test file (14 cases, all green before the row).

| Row | Mutant | Killed by |
|---|---|---|
| RM1 | step 1 keeps the first cycle's id: `self.ctx.cycle_id = self.ctx.cycle_id` | N13 |
| RM2 | step 1 takes the retry's id with no fallback: `self.ctx.cycle_id = result_cycle_id(retry_resp)` | N15 |
| RM3 | no scope around a step: `with cycle_scope(""):` (the same line as M8 of section 9, which is now the per-step one) | N3, N14 |
| RM4 | the scope is bound to the id the pipeline started with, for every step (kept in an instance attribute at the first step): the repaired defect as a one-line mutant | N14 |

### 16.6 Properties for the round-2 Diff Reviewer (the delta only)

Verify at least one end-to-end path by execution: the Captain's DM route (`agent_chat`) with the real `DmSanityGate`, a real cognitive agent as the answering cycle and a real ChromaDB-backed `EpisodicMemory` with a registry bound, where the first reply holds an empty tag pair and so is retried.
1. When step 1 adopts the retry's reply, the DM episode (step 5) and every Ward Room post a later step makes carry the retry's cycle id, and the first cycle's id is nowhere on them.
2. A retry whose result carries no id, a retry that returns nothing and a retry that fails each leave the id the context had: the first cycle's, or the route's `hxi_dm` entry id when the first result carried none (S2b's fallback in `routers/agents.py`).
3. `_run_steps` binds the context's current id around each step and puts the outer id back on return, on a step's raise (the guard swallows it and the next step runs) and on cancellation; a step plan mode holds back (`continue`) leaves the scope too.
4. No step other than step 1 changes `cycle_id`; no signature changed; `run_escalation_only`, `run_plan_mode_text` and the steps of `_full_steps` behave as before for a reply that was not retried.
5. The three new cases discriminate: on the S2a head N13 and N14 fail and N15 passes (it pins the fallback), and each row of section 16.5 fails its named killers.

### 16.7 The orchestrator's first-hand checks of the repair (2026-11-21, an oracle tree detached at `9facefd9`)

| O | Result |
|---|---|
| R1 | The finding was reproduced before the repair with a probe that asserts its own premises (two cycles ran, both ids are registered and differ, the Captain's reply is the retry's answer): on the unrepaired source the stored DM episode names the first cycle (`first 5dcf1185fd1c`, `retry faf791765ab4`, stored `('5dcf1185fd1c', 'resolved')`); after pairs RA1 to RA3 the same probe fails, the episode naming the retry's (`first 5be6f641ddc1`, `retry b05d9fa0ed04`, stored `('b05d9fa0ed04', 'resolved')`). The three new cases on the unrepaired source (pairs RT1 and RT2 only): **2 failed, 12 passed**: N13 and N14 fail (N14: the step after the one that changes the id sees `feedfacecafe`, not `0123456789ab`), and N15 passes, as it pins the fallback. |
| R2 | After the pairs of 16.1 to 16.4: **14 passed** (the new test file). Every SEARCH occurs exactly once, in files that are CRLF throughout. |
| R3 | The campaign of 16.5: baseline of 14 cases green; **killed 4, differs 0, survived 0, invalid 0**; every named killer failed. |
| R4 | The focused check on the repaired oracle (80 files: the slice's 39 and the 41 more that name the DM reply pipeline, `G:\tmp\b10\r1s2a-focused-tests.txt`), four workers each, the two runs side by side with a review's own test runs beside them. Under `PROBOS_EMBEDDINGS=local`: **2488 passed, 1 skipped** (the skip is `test_bf758_file_read_confinement.py:151`: symlink creation needs a privilege this host lacks). Under the default embeddings: **2487 passed, 1 skipped, 1 failed**: `tests/test_ad1019c_consensus.py::test_approved_commits_single_invoke` (`ConsensusOutcome.INSUFFICIENT` where `APPROVED` was expected), a case that waits on consensus timeouts, run while the host held two four-worker runs and a review. The file alone then passed three times in a row on the repaired oracle (14 passed each, 142 to 147 s); it is in the focused sets of S2a and S2b, where it passed in both modes (1341 and 1848 passed) on the code before the repair, and it exercises MCP consensus, not the DM reply pipeline. It is recorded as a failure under load, not as a result of the repair. |
| R5 | `gen_ad_ledger.py --check` on the repaired oracle: "AD/BF ledger is current" (the tracker edits change a count, not an entry). |
