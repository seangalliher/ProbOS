# AD-1360 S2b (#1828): producers outside any cognitive cycle record an id their entry point issued, and a guard covers every direct `Episode(`

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-21

**Status:** oracle-proven (section 15). #1828 stays open until S3; the S1+S2a+S2b PR says `Refs #1828`. No Captain condition (section 4, G0). AD-1360 appears only in REPLACE text, the new files and the trackers.
- AD ceiling (`scripts/ad_ceiling.py`, run 2026-11-21): **AD-1361** (from `prompts/` filenames); git AD-1359; issues AD-1360. S2b allocates no AD and no BF.

**Base:** `24c30a7c` (main after the pull request for #1838) + S1 and S2a as committed on this branch (head `8c8ce27a`, their trackers included). The pairs of section 7 were proven on a scratch tree that held S1 and the S2a contract applied; section 15, O9 repeats the check on this branch. Line numbers in sections 3 and 10 were measured on that scratch tree and may differ on this branch, so search by symbol.

**Line endings:**
- Every edited tracked file is `i/lf w/crlf`, except `src/probos/cycle_trace.py`, which is `i/lf w/lf` (`git ls-files --eol`).
- SEARCH blocks are LF; match and write each file in its own endings.
- The new test files are LF and ASCII only. No SEARCH holds a non-ASCII character.

**Milestones** (one Builder delegation each; apply the pairs, run no test; no `AD-`/`BF-` token in a commit subject):

| M | Content | Tier | Review | Calls |
|---|---|---|---|---|
| M1 | 7.1 and 7.2 (new tests) first, then 7.3-7.11 | MEDIUM | Full GPT Diff Reviewer (new shared API in `cycle_trace`) | ~75 |
| M2 | 7.12-7.19 | MEDIUM | Full (`FeedbackEngine` constructor, `CognitiveAgent`) | ~70 |
| M3 | 7.20, 7.21, ledger check | LOW | Delta | ~12 |

Commit subjects:
- M1: `Issue an id at entry points outside any cognitive cycle and guard every direct producer`
- M2: `Record entry-point ids for the language pipeline, feedback, perception, devices, QA and dispatched work`
- M3: `Record the entry-chain slice in the status and decisions entries`

## 0. Premises (this tree, read 2026-11-21)

| P | Premise | Evidence |
|---|---|---|
| P1 | S1/S2a API | `cycle_trace.py:54` `current_cycle_id`, `:59` `bind_cycle`, `:79` `cycle_scope`, `:93` `result_cycle_id`, `:107` `_require_kind`, `:138` `issue(kind=)`, `:145` `register`, `:156` `kind_of` |
| P2 | An agent's lifecycle always binds a fresh id, so an outer entry id never reaches a cognitive cycle | `cognitive_agent.py:7623` `token = bind_cycle(self._issue_cycle_id())`; `:1801-1807` `_cycle_registry` accepts only a `CycleIdRegistry` |
| P3 | The runtime owns the registry | `runtime.py:1183`; it is passed to `init_cognitive_services` at `:3066` (param `cognitive_services.py:237`); `FeedbackEngine(` is built at `:550-557` inside it (`:210`) |
| P4 | 26 test files build `ProbOSRuntime.__new__` hosts (no `cycle_registry`) | `rg -l "__new__\(ProbOSRuntime\)\|ProbOSRuntime\.__new__" tests` -> 26 files. So runtime sites use `getattr(self, "cycle_registry", None)` |
| P5 | HXI post routes | `routers/wardroom.py:281` (`wardroom_create_thread`, `:277`), `:351` (`wardroom_create_post`, `:329`); `routers/recreation.py:118` (`make_move`, `:87`); `routers/procedures.py:201` (`teach_procedure`, `:150`). The Ward Room producers read `current_cycle_id()` (`threads.py:602`, `messages.py:359`) |
| P6 | DM route fallback | `routers/agents.py:3699` send (None when held); `:3776` import; `:3849` `cycle_id=result_cycle_id(result)` in `_agent_chat_impl` (`:2947`) |
| P7 | Quartermaster | `quartermaster.py:202` (`reconcile`), `:471` (`reconcile_for_agent`); `BaseAgent._runtime` from kwargs (`substrate/agent.py:55`); spawned with `runtime=` (`agent_fleet.py:84`) |
| P8 | Ground truth | `ground_truth.py:220-235` writes `correlation_id=""`; `rg "verification_episode_writer\|VerificationEpisodeWriter" src` shows only assignments (`finalize.py:4834,4838,4899`), no `.write(` caller |
| P9 | NL pipeline | `runtime.py:6155-6172` in `_execute_dag` (`:6092`); `renderer.py:481-501` in `process_with_feedback` (`:70`); `dream_adapter.py:347` `build_episode`, `Episode(` `:407`, `source=` `:417`; `agent_ids` = the DAG node agents (`:376-385`) |
| P10 | Feedback | `feedback.py:257` (in `apply_correction_feedback`, `:171`), `:418` (in `_store_feedback_episode`, `:384`); `__init__` `:43-61` has no registry |
| P11 | Perception | `routers/perception.py:96` (`_write_anchor_episode`, `:66`, `agent_ids` empty); `perception/consumer.py:1181` (`_anchor_episode`, `:1149`, `agent_ids` = observers); `self._runtime` `:137` |
| P12 | Devices | `runtime.py:5564` (`_store_device_consensus_episode`, `:5542`); `device_service.py:138` (`_store_episode`); both `agent_ids=[f"device:{id}"]` |
| P13 | System QA | `runtime.py:7011` in `_run_qa_for_designed_agent` (`:6929`) |
| P14 | Voice approval | `routers/agents.py:499` in `set_agent_voice_profile` (`:443`) |
| P15 | Proactive dead sites | `proactive.py:1529` (no-response; `should_store` rejects it, `test_selective_encoding.py:16-21`), `:1809` (unreachable: `:1642` reaches `_post_to_ward_room` `:3145` `rt.ward_room.list_channels()` first; `context` undefined at `:1788`). `_cycle_id` is set at `:1447` |
| P16 | Work-item dispatch | `cognitive_agent.py:2253` -> `_handle_work_item_dispatch` `:2241`; the agentic run `:2334-2339` is outside any bound cycle; the fallback `handle_intent(dm)` `:2342` binds its own |
| P17 | Compound replay `:2218-2239` and skill dispatch `:8289-8291` store no episode | No `Episode(` in either (rg list, section 10) |
| P18 | BF-938 enumerator | `tests/test_bf938_episode_source_guard.py:68-189` (`_Site`, `_episode_calls`, `_sites`, `_SRC`); key = `(file relative to src/probos, innermost function)` |

## 1. Problem

After S2a, the direct producers that run outside any cognitive cycle store `correlation_id=""` (or the constant `""` in `ground_truth.py`), so each records `empty`. Nothing stops a new direct producer from shipping with no id.

## 2. Solution

| Mechanism | Sites |
|---|---|
| `issue_entry_id(registry, kind=)`: the bound cycle's id if there is one, else a new id the registry issues under `kind`, else `""` without a `CycleIdRegistry` | quartermaster x2, ground truth, voice approval, camera anchor, vision consumer, System QA, feedback x2, DM fallback |
| `entry_scope(registry, kind=)`: binds that id for a block whose producers read the context | HXI Ward Room posts x4; NL pipeline (runtime, renderer; `dream_adapter` and the inline `Episode` read `current_cycle_id()`) |
| `current_cycle_id()` at the site | device x2 |
| the think's `_cycle_id` | proactive x2 (dead) |
| register + `cycle_scope(work_item_id)` (S2a D8's rule) | dispatched work item's agentic run |
| guard test | every `Episode(` whose source can be `direct` |

With no registry (tests, MagicMock runtimes), every changed producer stores `""`, as before.

**Heavier designs rejected:**
- A new `correlation_id` parameter on `build_episode`: test fakes with the old signature exist (`test_ad791g_main_chat_thread.py:84`, `test_ad933a_group_episode.py:93`).
- One `entry_scope` around the whole of `_execute_dag` or `reconcile`: it re-indents about 100 lines and adds nothing a test can see.
- Changing the Ward Room to store no episode for non-crew authors: a behaviour change; considered, deferred.

## 3. Consumers checked (what I enumerated)

| Changed | Enumerated | Result |
|---|---|---|
| Producers' `correlation_id` | `rg -l correlation_id tests` (39 files): none is a quartermaster, feedback, ground-truth, perception, device, QA, NL, renderer or voice test. `rg "== Episode\(\|asdict\(" tests`: only `test_bf869_fused_frame_refs.py:104`, which is a membership scan (an extra id string cannot match a sha) | No pin |
| Mock `store` arguments | `rg "(store\|_store)\.(call_args\|assert_called_once_with\|assert_awaited_once_with\|await_args)" tests` -> 16 files; the S2b-relevant ones (`test_feedback_engine`, `test_correction_runtime`, `test_ad528_ground_truth`, `test_api_profile`, `test_ad733*`, `test_ad720d3`, `test_ad746`, `test_bf869`, `test_bf138`) assert no `correlation_id` and no full field set (rg `correlation_id\|fields\(` over them) | Compatible |
| Source scans of edited files | `test_ad1228_standing_interests.py:1694` (a quartermaster string, untouched); `test_ad733_frame_endpoint.py:168`, `test_ad733_2_screen_source.py:175` (base64 patterns absent from REPLACE); `test_ad1341_s1_promotion.py:404` (`resolve_records_repo_path` count); `test_bf938_ad607_binding.py:172` (`episodic_memory.<setter>` calls) | Unchanged |
| AD-1343 censuses | `tests/fixtures/ad1343_seam_registry.py:99-111` (SOURCE_ORDER), `:165-186` (AGENT_WORK_CALLS): `_agent_chat_impl`'s pinned callees keep their order; the new callees are not agent-work names | Holds |
| `build_episode` callers and fakes | `rg build_episode src tests`: two src callers, three test fakes; signature unchanged | Compatible |
| `FeedbackEngine(` | 9 test constructions without `cycle_registry` -> `""` | Compatible |
| Layer rules | `test_layer_boundaries.py:42,169`: a top-level module is always importable | Holds |

**Not checked:** the live vessel.

## 4. Decisions

- **G0.** No Captain condition. No persisted field is added (values only), no new event, no control weakened, and the cutoff stays at 0.0.
- **D10 (entry chains).** An id is issued only where a real request or unit of work starts (a Captain action, a sweep, a verification, a described frame, a QA run). Inside a cycle, the cycle's id wins (P2 keeps agent cycles separate). Kinds: `hxi_post`, `hxi_dm`, `hxi_request`, `quartermaster_sweep`, `quartermaster_reclaim`, `nl_request`, `captain_feedback`, `vision_observation`, `system_qa`, `ground_truth_verification`.
- **D11 (device sites).** Device episodes belong to the device (`agent_ids=[device:...]`), so a chain belongs at the sender: read the cycle's id; outside one, `""`.
- **D12 (work items).** `_handle_work_item_dispatch` registers the item's id (kind `work_item`) and binds it around `_run_agentic_dispatch`, only with a `CycleIdRegistry` and a non-blank `str` id.
- **D13 (left as is, `outside any cycle by design`).** These keep reading `current_cycle_id()` through the Ward Room producers. Outside a context with a bound id they store `""`:
  - posts by non-crew authors: `ward_room_router.py:273,293`; `capability_request_notifier.py:127`; `task_completion_notifier.py:137`; `startup/crew_start.py:62`; `finalize.py:6403,6513`; `shutdown.py:1041`;
  - shell-command posts: `commands_procedure.py`, `commands_autonomous.py`, `commands_alert.py`.

  Their episodes are stored under the author's slot. A crew agent's recall filters on its own `agent_ids` (`episodic.py:3946-3950`), so a crew recall does not return them. That is read, not measured.
- **D14 (the dead proactive sites).** Both pass `_cycle_id`, so they comply if ever reached. Deleting the dead branches is a separate cleanup: it is no behaviour change, and `:1809`'s undefined `context` is a latent `NameError`. The orchestrator should file it as a BF.
- **D15 (guard).** It keys on `(file, function)`, never on line numbers. A site whose source can be `direct` (a `direct` label, the default, or a computed copy) must pass `correlation_id=` with a non-`Constant` value, or be in `_EXEMPT` with a reason from {`never stored`, `copy`, `dead`, `outside any cycle by design`}. A non-direct source needs no row (BF-938 already resolves the labels). `_ENTRY_CHAINS` must equal the census of `entry_scope`/`issue_entry_id` calls by `(file, function) -> kinds`. It cannot see:
  - a positional or `**kw` `correlation_id` (reported missing, so it fails closed);
  - `dataclasses.replace`;
  - an overlay's `Episode(`;
  - whether a forwarded expression is empty at runtime;
  - an entry point that calls neither helper (the Ward Room callers in D13).

**S3 exposure (from the code).** These sites were `empty` before S2b and carry crew `agent_ids`, so a crew recall can return their episodes and S3 would flag them:
- the NL pipeline;
- feedback;
- the vision consumer;
- voice approval;
- the DM fallback;
- the BF-263 UI dual-write post (`wardroom.py:337`, agent-authored);
- MCP episodes in a dispatched work item's run;
- System QA (designed agents).

Low exposure (no crew `agent_ids`): quartermaster, devices, the camera anchor, Captain- and system-authored posts.

**Unclassified residual:** other non-cycle callers of `create_post`/`create_thread` (`counselor.py:2349`, `deliberation/protocol.py:105,175,231`, `social_memory.py:71,153`, `ready_room/sessions.py:94`, `agent_work_runner.py:791,806,820`, `recreation/service.py:200`, `agent_onboarding.py:540`) and MCP invokes outside any cycle. S3's replay groups by `user_input` prefix and anchor channel, so it reports them.

## 5. Tests

**`tests/test_ad1360_s2b_entry_chains.py` (13 cases)**, all on a real ChromaDB-backed `EpisodicMemory` unless noted:

| N | Case | S2a tree | M1 | M2 |
|---|---|---|---|---|
| E1 | `issue_entry_id`/`entry_scope`: issue, keep the bound id, `""` without a registry, blank kind raises, restore on exit and raise | collection error | pass | pass |
| E2 | **crossing:** HXI thread, post and recreation move on a real `WardRoomService`, `resolved` `hxi_post` | error | pass | pass |
| E3 | **crossing:** DM route, reply without an id, step 5 `resolved` `hxi_dm` | error | pass | pass |
| E4 | **crossing:** real quartermaster sweep `resolved`; an agent with no runtime stores `empty` | error | pass | pass |
| E5 | **crossing:** reactive reclaim `resolved` `quartermaster_reclaim` | error | pass | pass |
| E6 | ground-truth writer `resolved` | error | pass | pass |
| E7 | **crossing:** voice-approval route `resolved` `hxi_request` | error | pass | pass |
| E8 | **crossing:** `_execute_dag`, dream-adapter and inline paths, `resolved` `nl_request` | error | **fail** (`empty`) | pass |
| E9 | real `FeedbackEngine` execution feedback `resolved`; without a registry `empty` | error | **fail** (TypeError: `cycle_registry`) | pass |
| E10 | camera anchor `hxi_request` and vision consumer `vision_observation` `resolved` | error | **fail** (consumer `empty`) | pass |
| E11 | device episodes in a bound cycle `resolved`, outside `empty` | error | **fail** | pass |
| E12 | **crossing:** real `CognitiveAgent` work-item dispatch: the run sees the item's id; its MCP episode `resolved`; no registry binds nothing | error | **fail** | pass |
| E13 | startup passes `cycle_registry=cycle_registry` to `FeedbackEngine(` (AST) | error | **fail** | pass |

**`tests/test_ad1360_s2b_direct_producer_guard.py` (5 cases):**

| N | Case | S2a tree | M1 | M2 |
|---|---|---|---|---|
| G1 | premises: >=35 sites, >=25 direct-capable, each exemption a live direct-capable key, reasons from the vocabulary | pass | pass | pass |
| G2 | every direct-capable site forwards an id or is exempt | **fail** (16 sites) | **fail** (9 sites) | pass |
| G3 | no exempt site forwards an id (stale row) | pass | pass | pass |
| G4 | synthetic: a missing id, `""` and a literal id fail; an expression passes; a non-direct source needs none | pass | pass | pass |
| G5 | the entry-call census equals `_ENTRY_CHAINS` | **fail** (no calls) | **fail** (M2 rows missing) | pass |

After M1: 7+3 pass, 6+2 fail. After M2: all 18 pass.

**Evidence limits:** System QA, the renderer and `teach_procedure` are pinned by G2/G5 only. That a device episode is reached inside a cycle is not tested, only that it forwards the bound id.

## 6. What this does NOT change

- `correlation_cutoff` (0.0), every `enforce_*` default, profiles, `store()`, `judge_correlation_id`, the registry's bounds, and `KNOWN_MEMORY_SOURCES`.
- BF-938's file (imported, not edited) and `_MIN_SITES`.
- S2a's sites, `cycle_scope` and `result_cycle_id`.
- The D13 producers, `thread_fanout`, `routers/chat.py` (non-direct sources).
- Any signature except `FeedbackEngine.__init__` (one defaulted keyword, last).

## 7. The contract

### 7.1 New file `tests/test_ad1360_s2b_entry_chains.py` (M1, written first)

```python
"""AD-1360 S2b (#1828): producers outside any cognitive cycle record an id their entry point issued.

Each case runs a real producer (the HXI Ward Room and recreation routes on a real WardRoomService, the Captain's 1:1 DM
route, the quartermaster, the ground-truth writer, the voice-approval route, the natural-language pipeline's episode
step, the FeedbackEngine, the camera route and the vision consumer, the device episode writers, a dispatched work item's
agentic run) into a real ChromaDB-backed EpisodicMemory with a cycle-id registry bound, and reads the stored record back.
security.memory.correlation_cutoff stays at 0.0, so nothing here changes a recall.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.agents.quartermaster import QuartermasterAgent
from probos.api_models import CreatePostRequest, CreateThreadRequest, SetVoiceProfileRequest
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.feedback import FeedbackEngine
from probos.cognitive.ground_truth import GroundTruthResult, VerificationEpisodeWriter
from probos.cycle_trace import (
    VERDICT_EMPTY,
    VERDICT_RESOLVED,
    CycleIdRegistry,
    bind_cycle,
    current_cycle_id,
    entry_scope,
    issue_entry_id,
    unbind_cycle,
)
from probos.dream_adapter import DreamAdapter
from probos.perception.consumer import VisionConsumer
from probos.routers.perception import _reset_state_for_tests, _write_anchor_episode
from probos.substrate.device_service import DeviceNodeService
from probos.types import Episode, IntentMessage, IntentResult, TaskDAG, TaskNode
from probos.ward_room.service import WardRoomService
from tests.test_ad1156_plan_execute_mode import _chat_request, _route_runtime

_REPLY = "Coolant pressure on deck four held steady through the evening watch handover."
_QUESTION = "What does the coolant loop read?"


class _Agent(CognitiveAgent):
    agent_type = "science_officer"
    instructions = "AD-1360 S2b entry-chain test agent."


def _episodes(memory: EpisodicMemory) -> list[Episode]:
    got = memory._collection.get(include=["metadatas", "documents"])
    return [
        EpisodicMemory._metadata_to_episode(episode_id, document, metadata)
        for episode_id, document, metadata in zip(got["ids"], got["documents"], got["metadatas"])
    ]


def _one(memory: EpisodicMemory, needle: str, agent: str = "") -> tuple[str, str]:
    """(correlation_id, correlation_verdict) of the one stored episode whose user_input or reflection holds needle."""
    episodes = _episodes(memory)
    hits = [
        ep for ep in episodes
        if (needle in ep.user_input or needle in (ep.reflection or "")) and (not agent or agent in ep.agent_ids)
    ]
    assert len(hits) == 1, (needle, agent, [(ep.user_input, ep.reflection) for ep in episodes])
    return hits[0].correlation_id, hits[0].correlation_verdict


def _chain(registry: CycleIdRegistry, record: tuple[str, str], kind: str) -> None:
    """The record resolved against an id the registry issued under ``kind``."""
    chain_id, verdict = record
    assert verdict == VERDICT_RESOLVED and registry.kind_of(chain_id) == kind, (record, registry.kind_of(chain_id))


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


def _quartermaster(memory: EpisodicMemory, registry: CycleIdRegistry | None, agent_id: str) -> QuartermasterAgent:
    return QuartermasterAgent(
        reconciler=MagicMock(), work_item_store=SimpleNamespace(list_work_items=AsyncMock(return_value=[])),
        work_item_router=MagicMock(), episodic=memory, agent_id=agent_id,
        runtime=SimpleNamespace(cycle_registry=registry) if registry is not None else None,
    )


def _nl_host(memory: EpisodicMemory, registry: CycleIdRegistry, adapter: Any) -> SimpleNamespace:
    results = {"t1": {"results": [{"agent_id": "ad1360-nl-agent"}]}}
    return SimpleNamespace(
        dag_executor=SimpleNamespace(execute=AsyncMock(return_value={"results": results})),
        working_memory=MagicMock(), episodic_memory=memory, dream_adapter=adapter, _last_shapley_values={},
        _knowledge_store=None, workflow_cache=None, cycle_registry=registry, _record_error=MagicMock(),
    )


# -- E1: the helpers ----------------------------------------------------------------------------------------------------


def test_an_entry_point_issues_its_own_id_unless_a_cycle_is_bound() -> None:
    registry = CycleIdRegistry()
    issued = issue_entry_id(registry, kind="hxi_post")
    assert registry.kind_of(issued) == "hxi_post" and current_cycle_id() == ""
    for stray in (None, MagicMock(), SimpleNamespace()):
        assert issue_entry_id(stray, kind="hxi_post") == ""
    for blank in ("", "   ", None):
        with pytest.raises(ValueError):
            issue_entry_id(None, kind=blank)  # type: ignore[arg-type]
    outer = bind_cycle("0123456789ab")
    try:
        held = len(registry)
        assert issue_entry_id(registry, kind="hxi_post") == "0123456789ab" and len(registry) == held
        with entry_scope(registry, kind="nl_request") as bound:
            assert bound == current_cycle_id() == "0123456789ab"
        assert current_cycle_id() == "0123456789ab"
    finally:
        unbind_cycle(outer)
    with entry_scope(registry, kind="nl_request") as bound:
        assert bound == current_cycle_id() and registry.kind_of(bound) == "nl_request"
    with pytest.raises(RuntimeError, match="ad1360"):
        with entry_scope(registry, kind="nl_request"):
            raise RuntimeError("ad1360: the block failed")
    with entry_scope(MagicMock(), kind="nl_request") as bound:
        assert bound == current_cycle_id() == ""
    assert current_cycle_id() == ""


# -- E2 to E7: entry points that M1 wires ---------------------------------------------------------------------------------


async def test_the_captains_ward_room_posts_from_the_hxi_record_the_requests_id(
    memory: EpisodicMemory, registry: CycleIdRegistry, tmp_path: Path,
) -> None:
    from probos.routers.recreation import make_move
    from probos.routers.wardroom import wardroom_create_post, wardroom_create_thread

    ws = WardRoomService(db_path=str(tmp_path / "wr.db"), episodic_memory=memory)
    await ws.start()
    try:
        channel = (await ws.list_channels())[0]
        runtime = SimpleNamespace(ward_room=ws, cycle_registry=registry, registry=MagicMock(), callsign_registry=None)
        thread = await wardroom_create_thread(channel.id, CreateThreadRequest(
            author_id="captain", title="Deck four survey", body="What is on deck four today?", author_callsign="Captain",
        ), runtime)
        await wardroom_create_post(
            thread["id"], CreatePostRequest(author_id="captain", body=_REPLY, author_callsign="Captain"), runtime,
        )
        game = MagicMock()
        game.make_move = AsyncMock(return_value={
            "thread_id": thread["id"], "state": {"status": "in_progress", "current_player": "Kira"}, "board_text": "X|O|X",
        })
        runtime.recreation_service = game
        await make_move({"game_id": "ad1360-game", "position": "5"}, runtime)
    finally:
        await ws.stop()
    _chain(registry, _one(memory, "Captain posted to"), "hxi_post")
    _chain(registry, _one(memory, _REPLY), "hxi_post")
    _chain(registry, _one(memory, "Captain played position 5."), "hxi_post")
    assert current_cycle_id() == ""


async def test_a_dm_whose_reply_carries_no_cycle_id_stores_the_routes_own_id(
    memory: EpisodicMemory, registry: CycleIdRegistry, tmp_path: Path,
) -> None:
    from probos.routers.agents import agent_chat

    rt = _route_runtime(tmp_path, modes=False)
    rt.registry.get.return_value.sovereign_id = "ad1360-dm-agent"
    rt.episodic_memory = memory
    rt.cycle_registry = registry
    rt.intent_bus.send = AsyncMock(return_value=IntentResult(
        intent_id="ad1360-intent", agent_id="ad1360-dm-agent", success=True, result=_REPLY,
    ))
    with patch("probos.routers.agents.is_crew_agent", return_value=True):
        await agent_chat("test-agent", _chat_request(_QUESTION), rt)
    _chain(registry, _one(memory, "[1:1 with"), "hxi_dm")


async def test_a_quartermaster_sweep_records_its_own_id(memory: EpisodicMemory, registry: CycleIdRegistry) -> None:
    await _quartermaster(memory, registry, "ad1360-quartermaster").reconcile()
    await _quartermaster(memory, None, "ad1360-bare-quartermaster").reconcile()
    _chain(registry, _one(memory, "quartermaster sweep", "ad1360-quartermaster"), "quartermaster_sweep")
    assert _one(memory, "quartermaster sweep", "ad1360-bare-quartermaster") == ("", VERDICT_EMPTY)


async def test_a_reactive_reclaim_records_its_own_id(memory: EpisodicMemory, registry: CycleIdRegistry) -> None:
    await _quartermaster(memory, registry, "ad1360-quartermaster").reconcile_for_agent("ad1360-departed")
    _chain(registry, _one(memory, "reactive reclaim for ad1360-departed"), "quartermaster_reclaim")


async def test_a_ground_truth_verification_records_its_own_id(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    writer = VerificationEpisodeWriter(runtime=SimpleNamespace(episodic_memory=memory, cycle_registry=registry))
    assert await writer.write(GroundTruthResult(
        verified=False, score=0.0, agent_id="ad1360-agent", claimed_summary="Surveyed the coolant loop on deck four.",
    ))
    _chain(registry, _one(memory, "Surveyed the coolant loop"), "ground_truth_verification")


async def test_the_captains_voice_approval_records_the_requests_id(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    from probos.routers.agents import set_agent_voice_profile

    agent = SimpleNamespace(
        id="ad1360-voice-agent", agent_type="science_officer", pool="science", sovereign_id="ad1360-voice-agent",
    )
    runtime = SimpleNamespace(
        registry=SimpleNamespace(get=lambda _agent_id: agent), episodic_memory=memory, cycle_registry=registry,
    )
    await set_agent_voice_profile(
        "ad1360-voice-agent", SetVoiceProfileRequest(proposal_rationale="A calmer voice for the night watch."), runtime,
    )
    _chain(registry, _one(memory, "[voice approval]"), "hxi_request")


# -- E8 to E13: entry points that M2 wires --------------------------------------------------------------------------------


async def test_the_natural_language_pipeline_stores_its_episode_with_the_requests_id(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    from probos.runtime import ProbOSRuntime

    adapter = DreamAdapter.__new__(DreamAdapter)
    adapter._trust_network, adapter._last_shapley_values, adapter._identity_registry = None, {}, None
    for host, text in (
        (_nl_host(memory, registry, adapter), "Survey the coolant loop on deck four"),
        (_nl_host(memory, registry, None), "Read the reactor log for the night watch"),
    ):
        dag = TaskDAG(nodes=[TaskNode(id="t1", intent="survey", status="completed")])
        await ProbOSRuntime._execute_dag(host, dag, text, time.monotonic())
        _chain(registry, _one(memory, text), "nl_request")
    assert current_cycle_id() == ""


async def test_captain_feedback_on_a_plan_records_its_own_id(memory: EpisodicMemory, registry: CycleIdRegistry) -> None:
    engine = FeedbackEngine(
        trust_network=MagicMock(), hebbian_router=MagicMock(), episodic_memory=memory, cycle_registry=registry,
    )
    assert (await engine.apply_execution_feedback(TaskDAG(nodes=[]), True, "Survey the coolant loop")).episode_stored
    bare = FeedbackEngine(trust_network=MagicMock(), hebbian_router=MagicMock(), episodic_memory=memory)
    assert (await bare.apply_execution_feedback(TaskDAG(nodes=[]), False, "Read the reactor log")).episode_stored
    _chain(registry, _one(memory, "Survey the coolant loop"), "captain_feedback")
    assert _one(memory, "Read the reactor log") == ("", VERDICT_EMPTY)


async def test_a_camera_frame_and_its_vision_description_record_their_own_ids(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    _reset_state_for_tests()
    try:
        await _write_anchor_episode(
            SimpleNamespace(episodic_memory=memory, cycle_registry=registry), "ad1360-session", "a" * 64, time.time(),
        )
    finally:
        _reset_state_for_tests()
    consumer = VisionConsumer.__new__(VisionConsumer)
    consumer._runtime = SimpleNamespace(episodic_memory=memory, cycle_registry=registry)
    await consumer._anchor_episode(
        "b" * 64, "the coolant gauge reads nominal", 0.9, "ad1360-session", agent_ids=["ad1360-observer"],
    )
    _chain(registry, _one(memory, "Camera stream began"), "hxi_request")
    _chain(registry, _one(memory, "Vision observation: the coolant gauge"), "vision_observation")


async def test_a_device_episode_records_the_cycle_that_actuated_it_and_none_outside_one(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    from probos.runtime import ProbOSRuntime

    service = DeviceNodeService(registry=MagicMock(), adapter=MagicMock(), episodic_provider=lambda: memory)
    token = bind_cycle(registry.issue(kind="cognitive_cycle"))
    try:
        chain_id = current_cycle_id()
        await service._store_episode(
            IntentMessage(intent="device.notify"), "dev-alpha", authorized=True, success=True, reason="",
        )
        await ProbOSRuntime._store_device_consensus_episode(
            SimpleNamespace(episodic_memory=memory), device_id="dev-bravo", intent_name="device.location",
            authorized=True, committed=True, reason="",
        )
    finally:
        unbind_cycle(token)
    await service._store_episode(
        IntentMessage(intent="device.notify"), "dev-charlie", authorized=False, success=False, reason="unpaired",
    )
    assert _one(memory, "-> dev-alpha") == (chain_id, VERDICT_RESOLVED)
    assert _one(memory, "-> dev-bravo") == (chain_id, VERDICT_RESOLVED)
    assert _one(memory, "-> dev-charlie") == ("", VERDICT_EMPTY)


async def test_a_dispatched_work_items_agentic_run_records_the_work_items_id(
    memory: EpisodicMemory, registry: CycleIdRegistry,
) -> None:
    from probos.runtime import ProbOSRuntime

    host = SimpleNamespace(episodic_memory=memory, identity_registry=None)
    seen: list[str] = []

    def _run_for(tool: str) -> Any:
        async def _run(**_kwargs: Any) -> str:
            seen.append(current_cycle_id())
            await ProbOSRuntime._store_mcp_invoke_episode(
                host, server_url="mcp.ad1360", tool=tool, tier="open", success=True, agent_id=f"ad1360-{tool}",
            )
            return "Acknowledged; surveying the coolant loop."
        return _run

    for runtime, tool in (
        (SimpleNamespace(cycle_registry=registry, chat_thread_store=None, work_item_store=None), "status"),
        (SimpleNamespace(chat_thread_store=None, work_item_store=None), "survey"),
    ):
        agent = _Agent()
        agent._runtime = runtime
        agent._run_agentic_dispatch = _run_for(tool)  # type: ignore[method-assign]
        result = await agent._handle_work_item_dispatch(IntentMessage(
            intent="work_item_dispatched", params={"work_item_id": f"ad1360{tool}item", "title": "Survey"},
            target_agent_id=agent.id,
        ))
        assert result.success and current_cycle_id() == ""
    assert seen == ["ad1360statusitem", ""]
    assert registry.kind_of("ad1360statusitem") == "work_item" and not registry.resolves("ad1360surveyitem")
    assert _one(memory, "[mcp_invoke] status on mcp.ad1360") == ("ad1360statusitem", VERDICT_RESOLVED)
    assert _one(memory, "[mcp_invoke] survey on mcp.ad1360") == ("", VERDICT_EMPTY)


def test_startup_hands_the_feedback_engine_the_runtimes_registry() -> None:
    """A structural pin: the startup branch runs inside the boot sequence, which no focused test reaches."""
    path = Path(__file__).resolve().parents[1] / "src" / "probos" / "startup" / "cognitive_services.py"
    calls = [
        node for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "FeedbackEngine"
    ]
    assert len(calls) == 1
    assert {kw.arg: ast.unparse(kw.value) for kw in calls[0].keywords}.get("cycle_registry") == "cycle_registry"
```

### 7.2 New file `tests/test_ad1360_s2b_direct_producer_guard.py` (M1, written first)

```python
"""AD-1360 S2b (#1828): every Episode( a recall can judge as direct forwards a cycle id, or is exempt with a reason.

S3 arms security.memory.correlation_cutoff; from then on, a recalled direct episode stored after it whose correlation_id
is empty, unresolved or unchecked is flagged. This guard enumerates every Episode( construction under src/probos with
BF-938's enumerator and requires, for each site whose source can be "direct" (a resolved "direct" label, the dataclass
default, or a computed copy), a correlation_id= keyword whose value is not a constant, unless the site is in _EXEMPT
with its reason. A site whose source is never "direct" needs no row: BF-938 resolves its labels.

The Ward Room's producers read the id from the context, so the routes that post outside a cycle are invisible to the
Episode( census. _ENTRY_CHAINS therefore pins every call to cycle_trace.entry_scope / issue_entry_id by (file, function)
and the kind it issues under; a new call or a moved one fails here until the table says so.

What it cannot see: a correlation_id passed positionally or inside **kwargs (reported as missing, so it fails closed);
a dataclasses.replace(...) copy; an Episode built outside src/probos (an overlay); whether a forwarded expression is
non-empty at run time (current_cycle_id() outside a cycle is ""); an entry point that calls neither helper.
"""

from __future__ import annotations

import ast
import functools

from tests.test_bf938_episode_source_guard import _SRC, _episode_calls, _sites

_REASONS = ("never stored", "copy", "dead", "outside any cycle by design")
# (file, enclosing function) -> why the direct-capable site needs no cycle id. Each reason starts with one of _REASONS.
_EXEMPT: dict[tuple[str, str], str] = {
    ("cognitive/episodic.py", "migrate_enriched_embedding"):
        "never stored: a minimal Episode whose only use is _prepare_document's text",
    ("knowledge/store.py", "load_episodes"):
        "copy: the knowledge store's JSON copy of a stored episode; it carries no stored_at, so no cutoff judges it",
}
# (file, enclosing function) -> the kinds its entry_scope / issue_entry_id calls issue under.
_ENTRY_CHAINS: dict[tuple[str, str], frozenset[str]] = {
    ("agents/quartermaster.py", "reconcile"): frozenset({"quartermaster_sweep"}),
    ("agents/quartermaster.py", "reconcile_for_agent"): frozenset({"quartermaster_reclaim"}),
    ("cognitive/feedback.py", "apply_correction_feedback"): frozenset({"captain_feedback"}),
    ("cognitive/feedback.py", "_store_feedback_episode"): frozenset({"captain_feedback"}),
    ("cognitive/ground_truth.py", "write"): frozenset({"ground_truth_verification"}),
    ("experience/renderer.py", "process_with_feedback"): frozenset({"nl_request"}),
    ("perception/consumer.py", "_anchor_episode"): frozenset({"vision_observation"}),
    ("routers/agents.py", "_agent_chat_impl"): frozenset({"hxi_dm"}),
    ("routers/agents.py", "set_agent_voice_profile"): frozenset({"hxi_request"}),
    ("routers/perception.py", "_write_anchor_episode"): frozenset({"hxi_request"}),
    ("routers/procedures.py", "teach_procedure"): frozenset({"hxi_post"}),
    ("routers/recreation.py", "make_move"): frozenset({"hxi_post"}),
    ("routers/wardroom.py", "wardroom_create_post"): frozenset({"hxi_post"}),
    ("routers/wardroom.py", "wardroom_create_thread"): frozenset({"hxi_post"}),
    ("runtime.py", "_execute_dag"): frozenset({"nl_request"}),
    ("runtime.py", "_run_qa_for_designed_agent"): frozenset({"system_qa"}),
}
_ENTRY_CALLS = frozenset({"entry_scope", "issue_entry_id"})
_MIN_DIRECT = 25  # 29 after S2b (2026-11-21); fewer means the enumeration broke


def _called(call: ast.Call) -> str:
    return call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", "")


def _forwards_an_id(call: ast.Call) -> bool:
    value = next((keyword.value for keyword in call.keywords if keyword.arg == "correlation_id"), None)
    return value is not None and not isinstance(value, ast.Constant)


def _may_be_direct(labels: frozenset[str], form: str) -> bool:
    return "direct" in labels or form in ("computed", "unresolved")


@functools.cache
def _calls() -> dict[str, ast.Call]:
    """file:line -> its Episode( call, keyed as BF-938's _Site.where."""
    found: dict[str, ast.Call] = {}
    for path in sorted(_SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "Episode(" not in text:
            continue
        relative = path.relative_to(_SRC).as_posix()
        for _owner, call in _episode_calls(ast.parse(text)):
            where = f"{relative}:{call.lineno}"
            assert where not in found, where  # premise: one Episode( per line
            found[where] = call
    return found


def _direct_sites() -> list[tuple[str, tuple[str, str], bool]]:
    """(where, (file, function), forwards an id) for every site whose source can be direct."""
    return [
        (site.where, (site.key[0], site.key[1]), _forwards_an_id(_calls()[site.where]))
        for site in _sites() if _may_be_direct(site.labels, site.form)
    ]


def _entry_chains() -> dict[tuple[str, str], frozenset[str]]:
    found: dict[tuple[str, str], set[str]] = {}

    def visit(node: ast.AST, relative: str, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Call) and _called(child) in _ENTRY_CALLS:
                kind = next((keyword.value for keyword in child.keywords if keyword.arg == "kind"), None)
                literal = isinstance(kind, ast.Constant) and isinstance(kind.value, str)
                found.setdefault((relative, owner), set()).add(kind.value if literal else "<not a literal>")
            visit(child, relative, child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else owner)

    for path in sorted(_SRC.rglob("*.py")):
        relative = path.relative_to(_SRC).as_posix()
        text = path.read_text(encoding="utf-8")
        if relative != "cycle_trace.py" and any(name in text for name in _ENTRY_CALLS):
            visit(ast.parse(text), relative, "<module>")
    return {key: frozenset(kinds) for key, kinds in found.items()}


def test_the_census_finds_its_sites_and_every_exemption_is_live() -> None:
    assert len(_sites()) >= 35
    direct = _direct_sites()
    assert len(direct) >= _MIN_DIRECT, len(direct)
    keys = {key for _where, key, _forwards in direct}
    assert set(_EXEMPT) <= keys, sorted(set(_EXEMPT) - keys)
    assert all(reason.startswith(_REASONS) for reason in _EXEMPT.values()), _EXEMPT


def test_every_direct_episode_forwards_a_cycle_id_or_is_exempt() -> None:
    missing = [(where, key) for where, key, forwards in _direct_sites() if not forwards and key not in _EXEMPT]
    assert missing == [], (
        "a direct Episode( stores no cycle id: pass correlation_id= (current_cycle_id(), the result's id, or "
        f"issue_entry_id(registry, kind=...) at an entry point), or add the site to _EXEMPT with its reason: {missing}"
    )


def test_an_exempt_site_that_forwards_an_id_is_a_stale_row() -> None:
    stale = sorted({key for _where, key, forwards in _direct_sites() if forwards and key in _EXEMPT})
    assert stale == [], f"remove these rows from _EXEMPT: {stale}"


def test_the_rule_rejects_a_missing_or_constant_id_and_accepts_an_expression() -> None:
    def call(source: str) -> ast.Call:
        node = ast.parse(source).body[0]
        assert isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        return node.value

    for source in (
        'Episode(source="direct")', 'Episode(user_input="x")', 'Episode(source="direct", correlation_id="")',
        'Episode(source="direct", correlation_id="abcdefabcdef")', 'Episode(source="direct", correlation_id=None)',
        'Episode(**payload)',
    ):
        assert not _forwards_an_id(call(source)), source
    for source in (
        'Episode(source="direct", correlation_id=current_cycle_id())', 'Episode(correlation_id=self.ctx.cycle_id)',
    ):
        assert _forwards_an_id(call(source)), source
    assert _may_be_direct(frozenset({"direct"}), "literal") and _may_be_direct(frozenset(), "computed")
    assert not _may_be_direct(frozenset({"reflection"}), "member")


def test_each_entry_point_issues_under_its_kind() -> None:
    assert _entry_chains() == _ENTRY_CHAINS
```

### 7.3 `src/probos/cycle_trace.py` (M1)

**C1.** SEARCH:
```
  AD-1360 S2a: ``cycle_scope`` binds a cycle's id again for work done for it after it has ended (the DM reply's steps,
  a proactive think's posts), and ``result_cycle_id`` reads that id off the cycle's ``IntentResult``.
"""
```
REPLACE:
```
  AD-1360 S2a: ``cycle_scope`` binds a cycle's id again for work done for it after it has ended (the DM reply's steps,
  a proactive think's posts), and ``result_cycle_id`` reads that id off the cycle's ``IntentResult``.
  AD-1360 S2b: ``issue_entry_id`` and ``entry_scope`` give an entry point outside any cycle (an HXI request, a sweep,
  a verification) an id the registry issued, so the episodes it stores record their own chain.
"""
```
**C2.** SEARCH:
```
    metadata = getattr(result, "metadata", None)
    chain_id = metadata.get("correlation_id") if type(metadata) is dict else None
    return chain_id if type(chain_id) is str and chain_id.strip() else ""
```
REPLACE:
```
    metadata = getattr(result, "metadata", None)
    chain_id = metadata.get("correlation_id") if type(metadata) is dict else None
    return chain_id if type(chain_id) is str and chain_id.strip() else ""


def issue_entry_id(registry: object, *, kind: str) -> str:
    """AD-1360 S2b: the AD-492 id an entry point's work records, for an entry point no cognitive cycle runs.

    The bound id when one is bound (inside a cycle, or a ``cycle_scope``): the work joins the chain that reached it.
    Otherwise a new id ``registry`` issues and records under ``kind``, the entry point's name ("hxi_post"). Without a
    ``CycleIdRegistry`` (none, or a test runtime's MagicMock attribute), "": an id nothing issued would only turn the
    episode's verdict from empty into unresolved or unchecked. Raises ValueError for a blank or non-str ``kind``.
    """
    _require_kind(kind)
    bound = CURRENT_CYCLE_ID.get()
    if bound:
        return bound
    return registry.issue(kind=kind) if isinstance(registry, CycleIdRegistry) else ""


@contextmanager
def entry_scope(registry: object, *, kind: str) -> Iterator[str]:
    """Bind ``issue_entry_id(registry, kind=kind)`` for the block, for an entry point whose producers read
    ``current_cycle_id()`` (the Ward Room's); yields the id ("" when none is bound). The outer id is back on exit."""
    with cycle_scope(issue_entry_id(registry, kind=kind)) as bound:
        yield bound
```

### 7.4 `src/probos/routers/wardroom.py` (M1)

**H1.** SEARCH:
```
)
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)
```
REPLACE:
```
)
from probos.cycle_trace import entry_scope  # AD-1360 S2b (#1828)
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)
```
**H2.** SEARCH:
```
    try:
        thread = await runtime.ward_room.create_thread(
            channel_id=channel_id, author_id=req.author_id,
            title=req.title, body=req.body,
            author_callsign=req.author_callsign,
            thread_mode=req.thread_mode,
            max_responders=req.max_responders,
        )
        return vars(thread)
```
REPLACE:
```
    try:
        # AD-1360 S2b (#1828): an HXI post runs in no cognitive cycle; the request's own id is bound for the thread's episode.
        with entry_scope(getattr(runtime, "cycle_registry", None), kind="hxi_post"):
            thread = await runtime.ward_room.create_thread(
                channel_id=channel_id, author_id=req.author_id,
                title=req.title, body=req.body,
                author_callsign=req.author_callsign,
                thread_mode=req.thread_mode,
                max_responders=req.max_responders,
            )
        return vars(thread)
```
**H3.** SEARCH:
```
    try:
        post = await runtime.ward_room.create_post(
            thread_id=thread_id, author_id=req.author_id,
            body=req.body, parent_id=req.parent_id,
            author_callsign=author_callsign,
        )
        return vars(post)
```
REPLACE:
```
    try:
        # AD-1360 S2b (#1828): an HXI post runs in no cognitive cycle; the request's own id is bound for the post's episode.
        with entry_scope(getattr(runtime, "cycle_registry", None), kind="hxi_post"):
            post = await runtime.ward_room.create_post(
                thread_id=thread_id, author_id=req.author_id,
                body=req.body, parent_id=req.parent_id,
                author_callsign=author_callsign,
            )
        return vars(post)
```

### 7.5 `src/probos/routers/recreation.py` (M1)

**V1.** SEARCH:
```
from probos.recreation.turns import RecreationConflict, RecreationTurns, canonical_text, validate_revision
```
REPLACE:
```
from probos.cycle_trace import entry_scope  # AD-1360 S2b (#1828)
from probos.recreation.turns import RecreationConflict, RecreationTurns, canonical_text, validate_revision
```
**V2.** SEARCH:
```
            await runtime.ward_room.create_post(
                thread_id=thread_id,
                author_id="captain",
                body=msg,
                author_callsign="Captain",
            )
        except Exception:
            logger.debug("Ward Room post failed for Captain move", exc_info=True)
```
REPLACE:
```
            # AD-1360 S2b (#1828): the Captain's move is an HXI request; its own id is bound for the post's episode.
            with entry_scope(getattr(runtime, "cycle_registry", None), kind="hxi_post"):
                await runtime.ward_room.create_post(
                    thread_id=thread_id,
                    author_id="captain",
                    body=msg,
                    author_callsign="Captain",
                )
        except Exception:
            logger.debug("Ward Room post failed for Captain move", exc_info=True)
```

### 7.6 `src/probos/routers/procedures.py` (M1)

**Q1.** SEARCH:
```
from probos.routers.deps import get_runtime
from probos.visiting_officers import VisitorScopeRefused
```
REPLACE:
```
from probos.cycle_trace import entry_scope  # AD-1360 S2b (#1828)
from probos.routers.deps import get_runtime
from probos.visiting_officers import VisitorScopeRefused
```
**Q2.** SEARCH:
```
        await runtime.ward_room.create_thread(
            channel_id=dm_channel.id,
            author_id="captain",
            title=f"[TEACHING] {procedure.name}",
            body=dm_body,
            author_callsign="captain",
        )
```
REPLACE:
```
        # AD-1360 S2b (#1828): the Captain's teaching request; its own id is bound for the thread's episode.
        with entry_scope(getattr(runtime, "cycle_registry", None), kind="hxi_post"):
            await runtime.ward_room.create_thread(
                channel_id=dm_channel.id,
                author_id="captain",
                title=f"[TEACHING] {procedure.name}",
                body=dm_body,
                author_callsign="captain",
            )
```

### 7.7 `src/probos/routers/agents.py` (M1)

**R1.** SEARCH:
```
    from probos.cycle_trace import result_cycle_id  # AD-1360 (#1828)
```
REPLACE:
```
    from probos.cycle_trace import issue_entry_id, result_cycle_id  # AD-1360 (#1828)
```
**R2.** SEARCH:
```
        cycle_id=result_cycle_id(result),  # AD-1360 (#1828): the agent cycle this reply came from
```
REPLACE:
```
        # AD-1360 (#1828): the agent cycle this reply came from; S2b: the route's own id when no cycle's id came back
        # (a held turn, no reply, or a non-cognitive result).
        cycle_id=result_cycle_id(result) or issue_entry_id(getattr(runtime, "cycle_registry", None), kind="hxi_dm"),
```
**R3.** SEARCH:
```
            from probos.cognitive.episodic import resolve_sovereign_id
            from probos.types import AnchorFrame, Episode
            sovereign_id = resolve_sovereign_id(agent)
            new_voice_dict = new_profile.to_dict()
```
REPLACE:
```
            from probos.cognitive.episodic import resolve_sovereign_id
            from probos.cycle_trace import issue_entry_id  # AD-1360 S2b (#1828)
            from probos.types import AnchorFrame, Episode
            sovereign_id = resolve_sovereign_id(agent)
            new_voice_dict = new_profile.to_dict()
```
**R4.** SEARCH:
```
                    f"{agent_id}; rationale recorded for learning."
                ),
                source="direct",
```
REPLACE:
```
                    f"{agent_id}; rationale recorded for learning."
                ),
                source="direct",
                # AD-1360 S2b (#1828): the Captain's approval is an HXI request outside any cycle; its own id.
                correlation_id=issue_entry_id(getattr(runtime, "cycle_registry", None), kind="hxi_request"),
```

### 7.8 `src/probos/routers/perception.py` (M1)

**F1.** SEARCH:
```
from probos.routers.deps import get_runtime
from probos.types import AnchorFrame, Episode, IntentMessage
```
REPLACE:
```
from probos.cycle_trace import issue_entry_id  # AD-1360 S2b (#1828)
from probos.routers.deps import get_runtime
from probos.types import AnchorFrame, Episode, IntentMessage
```
**F2.** SEARCH:
```
            source="direct",
            importance=8,
```
REPLACE:
```
            source="direct",
            # AD-1360 S2b (#1828): the frame upload is an HXI request outside any cycle; its own id.
            correlation_id=issue_entry_id(getattr(runtime, "cycle_registry", None), kind="hxi_request"),
            importance=8,
```

### 7.9 `src/probos/agents/quartermaster.py` (M1)

**A1.** SEARCH:
```
from probos.events import EventType
from probos.substrate.agent import BaseAgent
```
REPLACE:
```
from probos.cycle_trace import issue_entry_id  # AD-1360 S2b (#1828)
from probos.events import EventType
from probos.substrate.agent import BaseAgent
```
**A2.** SEARCH:
```
                            f"Reconciled board: scanned={counts['scanned']} "
                            f"redispatched={counts['redispatched']} "
                            f"cleared={counts['cleared']} skipped={counts['skipped']}"
                        ),
                    )
```
REPLACE:
```
                            f"Reconciled board: scanned={counts['scanned']} "
                            f"redispatched={counts['redispatched']} "
                            f"cleared={counts['cleared']} skipped={counts['skipped']}"
                        ),
                        # AD-1360 S2b (#1828): the sweep's own id; no cognitive cycle runs it.
                        correlation_id=issue_entry_id(
                            getattr(self._runtime, "cycle_registry", None), kind="quartermaster_sweep",
                        ),
                    )
```
**A3.** SEARCH:
```
                            f"Reactive reclaim for {agent_id}: scanned={counts['scanned']} "
                            f"redispatched={counts['redispatched']} "
                            f"cleared={counts['cleared']} skipped={counts['skipped']}"
                        ),
                    )
```
REPLACE:
```
                            f"Reactive reclaim for {agent_id}: scanned={counts['scanned']} "
                            f"redispatched={counts['redispatched']} "
                            f"cleared={counts['cleared']} skipped={counts['skipped']}"
                        ),
                        # AD-1360 S2b (#1828): the reclaim's own id; no cognitive cycle runs it.
                        correlation_id=issue_entry_id(
                            getattr(self._runtime, "cycle_registry", None), kind="quartermaster_reclaim",
                        ),
                    )
```

### 7.10 `src/probos/cognitive/ground_truth.py` (M1)

**B1.** SEARCH:
```
from probos.events import EventType

if TYPE_CHECKING:
```
REPLACE:
```
from probos.cycle_trace import issue_entry_id  # AD-1360 S2b (#1828)
from probos.events import EventType

if TYPE_CHECKING:
```
**B2.** SEARCH:
```
            importance=7 if not result.verified else 4,
            correlation_id="",
        )
```
REPLACE:
```
            importance=7 if not result.verified else 4,
            # AD-1360 S2b (#1828): the verification's own id, or the cycle's when one reaches it (was a constant "").
            correlation_id=issue_entry_id(getattr(rt, "cycle_registry", None), kind="ground_truth_verification"),
        )
```

### 7.11 `src/probos/proactive.py` (M1)

**P1.** SEARCH:
```
                        reflection=f"{callsign or agent.agent_type} reviewed context but had nothing to report.",
                        source=MemorySource.DIRECT,
```
REPLACE:
```
                        reflection=f"{callsign or agent.agent_type} reviewed context but had nothing to report.",
                        source=MemorySource.DIRECT,
                        correlation_id=_cycle_id,  # AD-1360 S2b (#1828): the think's cycle (should_store rejects this shape)
```
**P2.** SEARCH:
```
                    reflection=f"{callsign or agent.agent_type} observed: {thought_summary}",
                    source=MemorySource.DIRECT,
```
REPLACE:
```
                    reflection=f"{callsign or agent.agent_type} observed: {thought_summary}",
                    source=MemorySource.DIRECT,
                    correlation_id=_cycle_id,  # AD-1360 S2b (#1828): the think's cycle (branch unreachable, DECISIONS S2b)
```

### 7.12 `src/probos/runtime.py` (M2)

**U1.** SEARCH (whole line):
```
from probos.cycle_trace import CycleIdRegistry, current_cycle_id  # AD-1360 (#1828)
```
REPLACE:
```
from probos.cycle_trace import CycleIdRegistry, current_cycle_id, entry_scope, issue_entry_id  # AD-1360 (#1828)
```
**U2.** SEARCH:
```
                dag_summary={},
                anchors=AnchorFrame(channel="device", trigger_type=intent_name),
            )
```
REPLACE:
```
                dag_summary={},
                anchors=AnchorFrame(channel="device", trigger_type=intent_name),
                correlation_id=current_cycle_id(),  # AD-1360 S2b (#1828): the actuating cycle's; "" outside one
            )
```
**U3.** SEARCH:
```
            try:
                t_end = time.monotonic()
                if self.dream_adapter:
                    self.dream_adapter._last_shapley_values = self._last_shapley_values
                    episode = self.dream_adapter.build_episode(text, execution_result, t_start, t_end)
                else:
                    episode = Episode(
                        timestamp=time.time(),
                        user_input=text,
                        dag_summary={},
                        outcomes=[],
                        agent_ids=[],
                        duration_ms=(t_end - t_start) * 1000,
                        source="direct",
                        anchors=AnchorFrame(channel="dag", trigger_type="dag_execution"),
                    )
                await self.episodic_memory.store(episode)
```
REPLACE:
```
            try:
                t_end = time.monotonic()
                # AD-1360 S2b (#1828): the request's own id (the cycle's when one reached this pipeline), bound while
                # the episode is built; the dream adapter's builder and the inline episode read it.
                with entry_scope(getattr(self, "cycle_registry", None), kind="nl_request"):
                    if self.dream_adapter:
                        self.dream_adapter._last_shapley_values = self._last_shapley_values
                        episode = self.dream_adapter.build_episode(text, execution_result, t_start, t_end)
                    else:
                        episode = Episode(
                            timestamp=time.time(),
                            user_input=text,
                            dag_summary={},
                            outcomes=[],
                            agent_ids=[],
                            duration_ms=(t_end - t_start) * 1000,
                            source="direct",
                            correlation_id=current_cycle_id(),
                            anchors=AnchorFrame(channel="dag", trigger_type="dag_execution"),
                        )
                await self.episodic_memory.store(episode)
```
**U4.** SEARCH:
```
                    embedding=[],
                    source="direct",
                    anchors=AnchorFrame(channel="smoke_test", trigger_type="smoke_test"),
```
REPLACE:
```
                    embedding=[],
                    source="direct",
                    # AD-1360 S2b (#1828): the QA run's own id; no cognitive cycle runs it.
                    correlation_id=issue_entry_id(getattr(self, "cycle_registry", None), kind="system_qa"),
                    anchors=AnchorFrame(channel="smoke_test", trigger_type="smoke_test"),
```

### 7.13 `src/probos/experience/renderer.py` (M2)

**N1.** SEARCH:
```
            try:
                t_end = time.monotonic()
                if self.runtime.dream_adapter:
                    self.runtime.dream_adapter._last_shapley_values = getattr(self.runtime, '_last_shapley_values', {})
                    episode = self.runtime.dream_adapter.build_episode(
                        text, execution_result, t_start, t_end,
                    )
                else:
                    from probos.types import AnchorFrame, Episode
                    episode = Episode(
                        timestamp=time.time(),
                        user_input=text,
                        dag_summary={},
                        outcomes=[],
                        agent_ids=[],
                        duration_ms=(t_end - t_start) * 1000,
                        source="direct",
                        anchors=AnchorFrame(channel="dag", trigger_type="dag_execution"),
                    )
                await self.runtime.episodic_memory.store(episode)
```
REPLACE:
```
            try:
                t_end = time.monotonic()
                # AD-1360 S2b (#1828): the shell request's own id (the cycle's when one reached it), bound while the
                # episode is built; the dream adapter's builder and the inline episode read it.
                from probos.cycle_trace import current_cycle_id, entry_scope
                with entry_scope(getattr(self.runtime, "cycle_registry", None), kind="nl_request"):
                    if self.runtime.dream_adapter:
                        self.runtime.dream_adapter._last_shapley_values = getattr(self.runtime, '_last_shapley_values', {})
                        episode = self.runtime.dream_adapter.build_episode(
                            text, execution_result, t_start, t_end,
                        )
                    else:
                        from probos.types import AnchorFrame, Episode
                        episode = Episode(
                            timestamp=time.time(),
                            user_input=text,
                            dag_summary={},
                            outcomes=[],
                            agent_ids=[],
                            duration_ms=(t_end - t_start) * 1000,
                            source="direct",
                            correlation_id=current_cycle_id(),
                            anchors=AnchorFrame(channel="dag", trigger_type="dag_execution"),
                        )
                await self.runtime.episodic_memory.store(episode)
```

### 7.14 `src/probos/dream_adapter.py` (M2)

**D1.** SEARCH:
```
from probos.config import format_trust
from probos.events import EventType
```
REPLACE:
```
from probos.config import format_trust
from probos.cycle_trace import current_cycle_id  # AD-1360 S2b (#1828)
from probos.events import EventType
```
**D2.** SEARCH:
```
            trust_deltas=trust_deltas,
            source=MemorySource.DIRECT,
```
REPLACE:
```
            trust_deltas=trust_deltas,
            source=MemorySource.DIRECT,
            correlation_id=current_cycle_id(),  # AD-1360 S2b (#1828): the request's id its caller bound (entry_scope)
```

### 7.15 `src/probos/cognitive/feedback.py` (M2)

**K1.** SEARCH:
```
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
```
REPLACE:
```
import time
from typing import Any, TYPE_CHECKING

from probos.cycle_trace import issue_entry_id  # AD-1360 S2b (#1828)

if TYPE_CHECKING:
```
**K2.** SEARCH:
```
        identity_registry: Any = None,
        agent_registry: AgentRegistry | None = None,
    ) -> None:
```
REPLACE:
```
        identity_registry: Any = None,
        agent_registry: AgentRegistry | None = None,
        cycle_registry: Any = None,
    ) -> None:
```
**K3.** SEARCH:
```
        self._agent_registry = agent_registry  # BF-907: agent_type -> slot for correction trust
```
REPLACE:
```
        self._agent_registry = agent_registry  # BF-907: agent_type -> slot for correction trust
        # AD-1360 S2b (#1828): the runtime's cycle-id registry; the Captain's feedback is an entry point of its own.
        self._cycle_registry = cycle_registry
```
**K4.** SEARCH:
```
                reflection=f"Correction {feedback_label}: {changes_description}",
                source="direct",
```
REPLACE:
```
                reflection=f"Correction {feedback_label}: {changes_description}",
                source="direct",
                correlation_id=issue_entry_id(self._cycle_registry, kind="captain_feedback"),  # AD-1360 S2b (#1828)
```
**K5.** SEARCH:
```
            reflection=f"Human feedback: {feedback_type}",
            source="direct",
```
REPLACE:
```
            reflection=f"Human feedback: {feedback_type}",
            source="direct",
            correlation_id=issue_entry_id(self._cycle_registry, kind="captain_feedback"),  # AD-1360 S2b (#1828)
```

### 7.16 `src/probos/startup/cognitive_services.py` (M2)

**S1.** SEARCH:
```
        identity_registry=identity_registry,
        agent_registry=registry,
    )

    # Create CorrectionDetector + AgentPatcher (AD-229, AD-230)
```
REPLACE:
```
        identity_registry=identity_registry,
        agent_registry=registry,
        cycle_registry=cycle_registry,  # AD-1360 S2b (#1828)
    )

    # Create CorrectionDetector + AgentPatcher (AD-229, AD-230)
```

### 7.17 `src/probos/perception/consumer.py` (M2)

**O1.** SEARCH:
```
from probos.perception.working_memory import VisionObservation
from probos.types import (
```
REPLACE:
```
from probos.cycle_trace import issue_entry_id  # AD-1360 S2b (#1828)
from probos.perception.working_memory import VisionObservation
from probos.types import (
```
**O2.** SEARCH:
```
                reflection=f"Vision observation: {description}",
                source="direct",
```
REPLACE:
```
                reflection=f"Vision observation: {description}",
                source="direct",
                # AD-1360 S2b (#1828): the described frame's own id; no cognitive cycle runs the consumer.
                correlation_id=issue_entry_id(getattr(self._runtime, "cycle_registry", None), kind="vision_observation"),
```

### 7.18 `src/probos/substrate/device_service.py` (M2)

**Y1.** SEARCH:
```
Layer discipline: substrate. Imports ONLY ``probos.substrate.device_node`` +
``probos.types`` + stdlib. NO consensus/cognitive/mesh/federation/runtime
```
REPLACE:
```
Layer discipline: substrate. Imports ONLY ``probos.substrate.device_node`` +
``probos.types`` + ``probos.cycle_trace`` (AD-1360, standard library only) +
stdlib. NO consensus/cognitive/mesh/federation/runtime
```
**Y2.** SEARCH:
```
from probos.substrate.device_node import DeviceNodeAdapter, DeviceNodeRegistry
from probos.types import AnchorFrame, Episode, IntentMessage, IntentResult
```
REPLACE:
```
from probos.cycle_trace import current_cycle_id  # AD-1360 S2b (#1828)
from probos.substrate.device_node import DeviceNodeAdapter, DeviceNodeRegistry
from probos.types import AnchorFrame, Episode, IntentMessage, IntentResult
```
**Y3.** SEARCH:
```
                dag_summary={},
                anchors=AnchorFrame(channel="device", trigger_type=intent.intent),
            )
```
REPLACE:
```
                dag_summary={},
                anchors=AnchorFrame(channel="device", trigger_type=intent.intent),
                correlation_id=current_cycle_id(),  # AD-1360 S2b (#1828): the actuating cycle's; "" outside one
            )
```

### 7.19 `src/probos/cognitive/cognitive_agent.py` (M2)

**W1.** SEARCH (whole line `:25`):
```
from probos.cycle_trace import CycleIdRegistry, bind_cycle, current_cycle_id, new_cycle_id, unbind_cycle  # AD-1360
```
REPLACE:
```
from probos.cycle_trace import (  # AD-1360
    CycleIdRegistry, bind_cycle, current_cycle_id, cycle_scope, new_cycle_id, unbind_cycle,
)
```
**W2.** SEARCH:
```
        _dispatch_started = time.time()
        reply_text = await self._run_agentic_dispatch(
            work_item_id=work_item_id,
            task_text=task_text,
            runtime=runtime,
            failures_sink=_dispatch_failures,
        )
```
REPLACE:
```
        _dispatch_started = time.time()
        # AD-1360 S2b (#1828): the agentic run is no cognitive cycle; the work item's id is its chain, adopted into the
        # registry (as a promoted run's is, S2a D8) and bound while the run stores episodes (an MCP invoke's).
        _work_registry = self._cycle_registry
        _work_chain = work_item_id if type(work_item_id) is str and work_item_id.strip() else ""
        if _work_registry is not None and _work_chain:
            _work_registry.register(_work_chain, kind="work_item")
        with cycle_scope(_work_chain if _work_registry is not None else ""):
            reply_text = await self._run_agentic_dispatch(
                work_item_id=work_item_id,
                task_text=task_text,
                runtime=runtime,
                failures_sink=_dispatch_failures,
            )
```

### 7.20 `PROGRESS.md` (M3)

**G1.** SEARCH (whole line `:1`, once): `# ProbOS Progress`. REPLACE:
```markdown
# ProbOS Progress

**AD-1360 S2b (2026-11-21), #1828 -- producers outside any cognitive cycle record an id their entry point issued, and a guard covers every direct episode.** `cycle_trace.issue_entry_id` returns the bound cycle's id, or else a new id the registry issues under the entry point's kind; `entry_scope` binds it for producers that read the context. Wired: the HXI Ward Room thread, post, recreation-move and teaching routes (`hxi_post`), the 1:1 DM route when the reply carries no cycle id (`hxi_dm`), voice approval and the camera anchor (`hxi_request`), the quartermaster's sweep and reclaim, the natural-language pipeline in the runtime and the shell (`nl_request`), Captain feedback, the vision consumer, System QA and the ground-truth writer. A dispatched work item's agentic run registers and binds the work item's id. Device episodes and two dead proactive sites read the cycle's id. `tests/test_ad1360_s2b_direct_producer_guard.py` requires every `Episode(` whose source can be `direct` to pass a non-constant `correlation_id=` or carry an exemption (two: a never-stored migration Episode and the knowledge store's copy), and pins every entry point's kind. Measured by `tests/test_ad1360_s2b_entry_chains.py` (13 cases) from real producers into a real ChromaDB-backed memory: each records `resolved`; without a registry, `empty` as before. The cutoff stays at 0.0. The live vessel was not measured. Contract `prompts/ad-1360-s2b-entry-chains-and-direct-producer-guard.md`.
```
**G2.** SEARCH (substring, once): `Producers outside any cycle and the guard test are AD-1360 S2b.` REPLACE: `Producers outside any cycle and the guard test are AD-1360 S2b (above).`

### 7.21 `DECISIONS.md` (M3)

**J1.** SEARCH (whole line, once):
```
- *S2a scope moved to S2b.* The quartermaster, `ground_truth.py:220` and the HXI Ward Room routes run outside any cycle. Found dead: `proactive.py:1525` (`should_store` rejects every episode it builds) and `:1802` (unreachable, and `context` is undefined there). S2b disposes of both.
```
REPLACE:
```markdown
- *S2a scope moved to S2b.* The quartermaster, `ground_truth.py:220` and the HXI Ward Room routes run outside any cycle. Found dead: `proactive.py:1525` (`should_store` rejects every episode it builds) and `:1802` (unreachable, and `context` is undefined there). S2b disposes of both.
- *S2b (2026-11-21), D10 (entry chains).* An entry point no cognitive cycle runs records its work under `cycle_trace.issue_entry_id(registry, kind=)`: the bound cycle's id when one is bound (an agent's lifecycle always binds its own, `cognitive_agent.py:7623`), else a new id the registry records under the kind, else "" without a `CycleIdRegistry`. `entry_scope` binds it for producers that read the context (the Ward Room). Kinds: `hxi_post`, `hxi_dm`, `hxi_request`, `quartermaster_sweep`, `quartermaster_reclaim`, `nl_request`, `captain_feedback`, `vision_observation`, `system_qa`, `ground_truth_verification`. D11: device episodes read the actuating cycle's id. D12: a dispatched work item's agentic run registers the item's id (`work_item`) and binds it. Rejected: a `correlation_id` parameter on `build_episode` (test fakes keep the old signature) and binding around whole method bodies (about 100 re-indented lines, nothing a test sees).
- *S2b D13 (left outside any chain by design).* Ward Room posts by non-crew authors (`ward_room_router.py:273,293`, the capability and task notifiers, startup and shutdown threads) and shell-command posts read `current_cycle_id()` and store "" outside a bound context. A crew agent's recall filters on its own `agent_ids` (read, not measured). Not classified, left to S3's replay (grouped by `user_input` prefix and anchor channel): other non-cycle callers of `create_post`/`create_thread` (counselor, deliberation, social memory, ready room, agent work runner, recreation service, onboarding) and MCP invokes outside any cycle or work item.
- *S2b D15 (guard).* `tests/test_ad1360_s2b_direct_producer_guard.py` reuses BF-938's enumerator, keys sites by (file, function), and requires a non-constant `correlation_id=` on every `Episode(` whose source can be `direct`, or an `_EXEMPT` row whose reason is one of `never stored`, `copy`, `dead`, `outside any cycle by design`; stale rows fail. `_ENTRY_CHAINS` must equal the census of `entry_scope`/`issue_entry_id` calls. It cannot see a positional or `**kw` id (it fails closed), `dataclasses.replace`, an overlay's `Episode(`, whether a forwarded value is empty at run time, or an entry point that calls neither helper.
- *S2b disclosed.* Each wired entry point now issues one id per request, sweep, described frame or QA run, which counts toward the registry's `max_entries` (not measured; S3's replay measures it). A task created inside an `entry_scope` inherits the id (PEP 567), so a system notice posted while routing a Captain's HXI post records that post's chain. `ground_truth.py`'s writer has no caller (`finalize.py:4834,4838,4899` assign it). *Deferred:* deleting `proactive.py`'s dead no-response branch and its unreachable no-Ward-Room branch (`context` undefined at `:1788`); both pass the think's id meanwhile.
```

**Ledger:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`; regenerate and commit in M3 only if it reports drift. No `roadmap.md` row.

## 9. Mutation rows (campaign on the M2 candidate)

| Row | Mutant | Killed by |
|---|---|---|
| X1 | `issue_entry_id` ignores the bound id | E1 |
| X2 | `issue_entry_id` accepts any object with `issue` | E1 (MagicMock) |
| X3 | `_require_kind` dropped | E1 (`None` registry, blank kind) |
| X4 | `entry_scope` does not restore | E1 |
| X5-X7 | the thread, post or move route without its scope | E2 |
| X8 | `teach_procedure` without its scope | G5 |
| X9 | DM fallback dropped | E3 |
| X10 | voice approval omits the id | E7, G2 |
| X11 | camera anchor omits it | E10, G2 |
| X12, X13 | quartermaster sweep / reclaim omits it | E4 / E5, G2 |
| X14 | ground truth back to `""` | E6, G2 (Constant) |
| X15 | a proactive site omits `_cycle_id` | G2 |
| X16 | `_execute_dag` without its scope | E8 |
| X17 | `dream_adapter` omits the id | E8, G2 |
| X18 | renderer without its scope | G5 |
| X19 | a feedback site omits the id | E9 (`_store_feedback_episode`), G2 (both) |
| X20 | startup does not pass the registry | E13 |
| X21 | vision consumer omits the id | E10, G2 |
| X22 | a device site omits the id | E11, G2 |
| X23 | QA omits the id | G2, G5 |
| X24 | work item not registered | E12 (`unresolved`) |
| X25 | work item not bound | E12 (`seen`) |
| X26 | work item bound without a registry | E12 (`seen[1]`) |
| X27 | an entry kind renamed | G5 and the crossing test's `kind_of` |
| X28 | an exempt row left after its site forwards | G3 |

Known gap: a site that forges `new_cycle_id()` passes G2. The crossing tests catch it as `unresolved`; the guard does not.

## 10. Verified Against Codebase (2026-11-21, this tree)

```
rg -n "def current_cycle_id|def bind_cycle|def cycle_scope|def result_cycle_id|def _require_kind|def issue|def register|def kind_of" src/probos/cycle_trace.py   54,59,79,93,107,138,145,156
rg -n "bind_cycle\(|_issue_cycle_id\(\)" src/probos   cognitive_agent.py:3049,7623; cycle_trace.py:59
rg -n "cycle_registry" src   runtime.py:538,1183,3066; cognitive_services.py:60,96-97,237,362; cognitive_agent.py:1801-1811; turn_promotion.py:1003
rg -n "Episode\(" src/probos   quartermaster.py:202,471 dream_adapter.py:407 renderer.py:491 feedback.py:257,418 ground_truth.py:220 runtime.py:5219,5564,6162,7011 consumer.py:1181 proactive.py:1529,1809 routers/agents.py:499 routers/perception.py:96 device_service.py:138 episodic.py:928,4656 knowledge/store.py:188 (+ S2a and non-direct sites)
rg -n "\.(create_post|create_thread)\(" src/probos   wardroom.py:281,351 recreation.py:118 procedures.py:201 ward_room_router.py:273,293 (+ D13 list)
rg -n "^async def _agent_chat_impl|^async def set_agent_voice_profile" src/probos/routers/agents.py   2947, 443
rg -n "^    (async )?def " src/probos/runtime.py   5542 _store_device_consensus_episode, 6092 _execute_dag, 6929 _run_qa_for_designed_agent, 7074
rg -n "^    (async )?def " src/probos/experience/renderer.py   70 process_with_feedback, 526
rg -n "^(async )?def " src/probos/startup/cognitive_services.py   210 init_cognitive_services (FeedbackEngine( at 550)
rg -n "verification_episode_writer|VerificationEpisodeWriter" src   ground_truth.py:188; finalize.py:4825,4834,4838,4899
rg -n "build_episode" src tests   2 src callers (runtime.py:6160, renderer.py:486); fakes test_ad791g:84, test_ad933a:93
rg -n "__new__\(ProbOSRuntime\)|ProbOSRuntime\.__new__" tests   26 files
rg -n "SIMILARITY_THRESHOLD|MAX_EPISODES_PER_HOUR" src/probos/cognitive/episodic.py   1375,1377 (per agent, 3344-3398)
git ls-files --eol <19 files>   all i/lf w/crlf except cycle_trace.py i/lf w/lf
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py   CEILING AD-1361
```

## Absence Verified (2026-11-21)

| Claim | Run | Found | Holds |
|---|---|---|---|
| No S2b name exists yet | `rg "issue_entry_id\|entry_scope\|hxi_post\|nl_request" src tests` | `test_cognitive_integration.py:110` (`test_multiple_nl_requests`, unrelated) | yes |
| No test pins an S2b producer's id | section 3 commands | none | yes |
| Compound replay and skill dispatch store no episode | the `Episode(` list above; `cognitive_agent.py:2218-2239`, `:8289-8291` | none | yes |
| The ground-truth writer has no caller | rg above | assignments only | yes |
| The PROGRESS and DECISIONS anchors occur once | `rg -c "# ProbOS Progress"` 1; `rg -c "Producers outside any cycle and the guard test are AD-1360 S2b\."` 1; `rg -c "^- \*S2a scope moved to S2b\.\*" DECISIONS.md` 1 | 1 each | yes |

## 11. Deterministic checks

- **Focused gate, `-n 0`:**
  - this slice and the earlier ones: both new files, `tests/test_ad1360_s2a_producers.py`, `tests/test_ad1360_s1_cycle_trace.py`, `tests/test_bf938_episode_source_guard.py`;
  - quartermaster, work items, Ward Room and recreation: `tests/test_ad875_quartermaster.py`, `tests/test_ad880_reactive_reclaim.py`, `tests/test_ad839_work_item_dispatch.py`, `tests/test_ad856_agentic_dispatch.py`, `tests/test_ward_room.py`, `tests/test_recreation_router.py`;
  - feedback, ground truth and profile: `tests/test_feedback_engine.py`, `tests/test_correction_runtime.py`, `tests/test_bf138_sovereign_id_completion.py`, `tests/test_ad528_ground_truth.py`, `tests/test_api_profile.py`;
  - perception and devices: `tests/test_ad733_frame_endpoint.py`, `tests/test_ad733_2_screen_source.py`, `tests/test_ad733a_vision_consumer.py`, `tests/test_ad720d3_vision_episode_write.py`, `tests/test_ad746_source_binding.py`, `tests/test_bf869_fused_frame_refs.py`, `tests/test_ad843c1_device_actuation.py`, `tests/test_ad843c2_device_consensus.py`;
  - QA, the NL pipeline and the DM route: `tests/test_system_qa.py`, `tests/test_ad567a_anchor_metadata.py`, `tests/test_bf103_episode_id_mismatch.py`, `tests/test_ad791g_main_chat_thread.py`, `tests/test_experience_nl_memory.py`, `tests/test_ad726_dm_reply_pipeline.py`, `tests/test_ad1156_plan_execute_mode.py`;
  - proactive: `tests/test_selective_encoding.py`, `tests/test_proactive.py`;
  - censuses and boundaries: `tests/test_ad1343_seam_registry.py`, `tests/test_ad1343_stop_seam_inventory.py`, `tests/test_layer_boundaries.py`, `tests/test_ad1341_s1_promotion.py`, `tests/test_bf938_ad607_binding.py`, `tests/test_ad1184_ad_ledger.py`.
- **`rg` checks:**
  - `rg -n "entry_scope\(|issue_entry_id\(" src/probos` gives exactly the 16 `_ENTRY_CHAINS` functions, plus `cycle_trace.py` itself.
  - `rg -n 'kind="work_item"' src` gives `turn_promotion.py` and `cognitive_agent.py` only.
- **Broad gate:** once, after M3, with the S1 label (`ad-1360-1828`).

## 12. Prior art and blind spots

- **Internal:** S1 section 13 (OpenTelemetry attach/detach) applies here. `entry_scope` is the tracing rule "start a root span when no parent context exists, else a child": a request without a bound id starts a new chain.
- **External:** skipped. This is ProbOS plumbing, and S1 reviewed `reference-projects.md` on 2026-11-20 and found no relevant row; not re-run (date used 2026-11-21).
- **Blind spots named:**
  - registry volume from vision frames (D13 disclosure);
  - tasks inheriting an entry id;
  - a forged `new_cycle_id()` passes the guard (X-table gap);
  - the D13 residual list.

## 13. Diff Reviewer: properties to verify

1. Every new `correlation_id=` reads `current_cycle_id()`, `_cycle_id` or `issue_entry_id(...)`. None is a constant or `new_cycle_id()`.
2. Every `issue_entry_id`/`entry_scope` is at an entry point no cognitive cycle runs, with a literal kind that matches `_ENTRY_CHAINS`. Inside a bound cycle it returns that cycle's id and issues nothing.
3. Without a `CycleIdRegistry` (None, MagicMock, SimpleNamespace), each changed producer stores `""`, as before. With the cutoff at 0.0, no recall result or event changes.
4. Each `entry_scope` restores the outer id on return, raise and cancellation, and wraps only the producer's construction or post.
5. `FeedbackEngine.__init__` gains one defaulted keyword, last. No other signature changes.
6. The work-item registration happens only with a `CycleIdRegistry` and a non-blank `str`, and the fallback `handle_intent(dm)` runs outside the scope.
7. New imports are `probos.cycle_trace` only. `cycle_trace.py` still imports only the standard library.
8. Both test files are ASCII and pin no source line number. The guard imports BF-938's helpers without editing that file.

## 14. Acceptance

- [ ] The section 5 predictions hold after M1 and M2, and the section 11 focused gate is green.
- [ ] Mutation rows X1-X28 are killed by the named cases.
- [ ] The section 11 `rg` checks hold. G1-G2 and J1 are applied, and the ledger check passes.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. The orchestrator's first-hand checks (2026-11-21, a scratch tree detached at `f4ccb082` (S1's last code and test commit) with the S2a contract applied, and the pairs of section 7 of this contract)

Every pair of section 7 was applied to a scratch worktree by `audit\contract_tools.py` (ASCII only: no `--utf8` was needed), and every check below was run, before the Builder started. Each test run went through `run_pytest_homeguard.ps1` (a redirected, empty home: entries left in it 0). Results:

| O | Result |
|---|---|
| O1 | All 47 operations (the two new test files and 45 pairs: C1-C2, H1-H3, V1-V2, Q1-Q2, R1-R4, F1-F2, A1-A3, B1-B2, P1-P2 in M1; U1-U4, N1, D1-D2, K1-K5, S1, O1-O2, Y1-Y3, W1-W2 in M2; G1-G2, J1 in M3) are found by `contract_tools.py list --prefix 7.`; every SEARCH occurs exactly once on the S2a-applied tree, in files that are CRLF throughout; the new test files were absent. |
| O2 | The two new test files alone on the S2a tree: the entry-chains file is **a collection error**, `ImportError: cannot import name 'entry_scope' from 'probos.cycle_trace'`; in the guard file the census test lists the 16 sites that forward no id and the entry-call census finds none: **2 failed, 3 passed, 1 error** (run with `--continue-on-collection-errors`), as section 5 says. |
| O3 | After the M1 pairs (7.3 to 7.11): **8 failed, 10 passed**: the reds are the guard's two (9 sites left; the M2 entry calls are missing) and E8 to E13, the natural-language pipeline, feedback, the camera and vision consumer, the device episodes, the work-item run and the startup pin, which need M2. After the M2 pairs (7.12 to 7.19): **18 passed**. |
| O4 | **The focused gate** (the 66 files that are the union of section 11's list, 39 files with the two new ones, and S2a's 39 files, on the scratch tree with the trackers and the regenerated ledger), under the default embeddings and under `PROBOS_EMBEDDINGS=local` as CI sets it: **1848 passed under the default embeddings (1265.86 s) and 1848 passed under `PROBOS_EMBEDDINGS=local` (686.69 s)**, four workers, other tests running on the host meanwhile; no failure and no error. |
| O5 | **The wide consumer run**, made on an earlier oracle (S1 as first drafted, S2a with its since-dropped compound-return pairs, and this contract's pairs; the code of this contract is unchanged since, and what changed under it is S1's two repairs and the dropped pairs): every test file under `tests/` that names a producer, router, runtime or helper this slice changed (the HXI routes, the quartermaster, the ground-truth writer, the proactive loop, the language pipeline, feedback, perception, devices, System QA, work-item dispatch, the Ward Room service, the cycle id module, or `ProbOSRuntime`), **528 files** in three chunks, four workers: chunk 0 **8325 passed, 13 skipped**; chunk 1 **2733 passed, 1 skipped**; chunk 2 **6010 passed, 31 skipped**; in all **17,068 passed, 45 skipped, 0 failed**. Chunk 2 left 8 PowerShell profile-cache entries in its redirected home (a test starts `pwsh`; none is ProbOS data). No failure, so no pair was added to the draft's. |
| O6 | **The mutation campaign** (section 9; `mutants_gen.py` over `rows_ad1360s2b.py`: each row changes one line of the candidate in place, and its unmutated baseline of 18 cases had to be all green): **killed 33, differs 0, survived 0, invalid 0** on the full candidate: the draft's 28 rows, of which X15, X19 and X22 run at each of their two sites (a and b) and X12 and X13 also run as a second mutant of the same call line (X12g and X13g, named to E4 or E5 and G2); every named killer failed in every row, and X4 also failed 11 other cases. |
| O7 | The trackers G1-G2 and J1 applied on the scratch tree (each SEARCH once), then `gen_ad_ledger.py` regenerated the ledger pair and `--check` reported "AD/BF ledger is current". |
| O8 | The AD-1343 seam tests and BF-938's census are in the focused gate (O4) and green. |
| O9 | **Re-checked on this branch before the Builder started** (2026-11-21, on main after the pull request for #1838 with S1 and S2a committed on it): `contract_tools.py checkpoints` with `--prefix 7.` on this branch at `8c8ce27a` (S1 and S2a as committed) found all 47 operations, each SEARCH exactly once, exit 0 and nothing on stderr; the blobs of the 21 files after operation 47 equal those of the scratch tree of O1 to O7 and O9 (`check_blobs_table.py`: 21 files checked, 0 differences). |

**What the orchestrator changed in the Architect's draft:** the pair labels and the two headings that the tool reads ("New file" in 7.1 and 7.2); the mutation rows (the draft's 28 became 33 one-line rows, O6); the placeholder of this section.

**What these checks do not show.**
- The vessel: nothing here ran against `%LOCALAPPDATA%\ProbOS\data`. The cutoff ships at 0.0, so no recall result changes until S3 arms it.
- That System QA, the renderer and `teach_procedure` store the id is pinned by the guard and the entry-call census only (no crossing case drives them); that a device episode is reached inside a cycle is not tested, only that the writers forward the bound id.
- The producers section 4 lists as outside any cycle by design (D13) and the unclassified residual still store `""` or an id nothing issued; S3's replay reports them.

## 16. Repair after review round 1 (2026-11-21)

Round 1 (`gpt-6.1-sol`, 28 minutes, the committed candidate `8c8ce27a..9facefd9`) requested changes: one finding, P2, reach injected-only, new in this slice, size findings 0. The orchestrator reproduced it before repairing it (section 16.9), and the Architect decided to fix it in this batch, at all three sites, with one predicate (consult `36e52865`, recorded on #1828).

**R1. A mock made with a spec passes `isinstance`, and its `issue()` returns another mock.** Three checks decide whether a runtime's `cycle_registry` attribute is a registry: `issue_entry_id` (this slice), the agent's `_cycle_registry` getter (S1, which this slice's work-item scope relies on) and `_register_promoted_work_item` (S2a). Each used `isinstance(x, CycleIdRegistry)`. A `MagicMock(spec=CycleIdRegistry)`, a `Mock(spec=CycleIdRegistry)` or a `create_autospec(CycleIdRegistry, instance=True)` passes it, because its `__class__` reads as the spec. `issue()` then returns a mock, `issue_entry_id` hands it to the producer as the id, ChromaDB refuses the metadata value and the episode is lost (the feedback engine, the ground-truth writer and the DM route stored 0 rows where the base stored 1), and the work-item scope registered an id in a mock, so the episode recorded `unresolved` where the base recorded `empty`. Nothing in `src` or `tests` builds such a mock and production builds the one real registry; the code's own docstrings already said that a test runtime's mock must not count. Repair: one predicate, `cycle_trace.is_cycle_registry(obj)`, which is `issubclass(type(obj), CycleIdRegistry)`: true for a registry and for an instance of a subclass, false for None, a namespace and every mock. The three sites call it.

No design decision is open: the Architect's ruling fixes the scope and the form. S1's getter keeps its interface (it only refuses more), so S1's approval stands. Nothing in sections 1 to 15 changes except the number of cases of the entry-chains test file, which is 16 instead of 13 (section 16.4; the tracker of section 16.5 says 16).

### 16.1 `src/probos/cycle_trace.py` (M-R1)

**RC0.** SEARCH:
```
  a verification) an id the registry issued, so the episodes it stores record their own chain.
```
REPLACE:
```
  a verification) an id the registry issued, so the episodes it stores record their own chain. ``is_cycle_registry``
  says whether an object is a real registry (a mock is not, spec'd or not).
```
**RC1.** SEARCH:
```
def issue_entry_id(registry: object, *, kind: str) -> str:
```
REPLACE:
```
def is_cycle_registry(obj: object) -> bool:
    """AD-1360 S2b: True for a ``CycleIdRegistry`` or an instance of a subclass, False for anything else.

    Not ``isinstance``: a mock made with ``spec=CycleIdRegistry`` or ``create_autospec`` passes it, because its
    ``__class__`` reads as the spec, and its ``issue()`` returns another mock. The type is what a real registry has.
    """
    return issubclass(type(obj), CycleIdRegistry)


def issue_entry_id(registry: object, *, kind: str) -> str:
```
**RC2.** SEARCH:
```
    ``CycleIdRegistry`` (none, or a test runtime's MagicMock attribute), "": an id nothing issued would only turn the
    episode's verdict from empty into unresolved or unchecked. Raises ValueError for a blank or non-str ``kind``.
```
REPLACE:
```
    real ``CycleIdRegistry`` (``is_cycle_registry``: not None, and not a test runtime's MagicMock attribute, spec'd or
    not), "": an id nothing issued would only turn the episode's verdict from empty into unresolved or unchecked.
    Raises ValueError for a blank or non-str ``kind``.
```
**RC3.** SEARCH:
```
    return registry.issue(kind=kind) if isinstance(registry, CycleIdRegistry) else ""
```
REPLACE:
```
    return registry.issue(kind=kind) if is_cycle_registry(registry) else ""
```

### 16.2 `src/probos/cognitive/cognitive_agent.py` (M-R1)

**RD1.** SEARCH:
```
    CycleIdRegistry, bind_cycle, current_cycle_id, cycle_scope, new_cycle_id, unbind_cycle,
```
REPLACE:
```
    CycleIdRegistry, bind_cycle, current_cycle_id, cycle_scope, is_cycle_registry, new_cycle_id, unbind_cycle,
```
**RD2.** SEARCH:
```
        Only a ``CycleIdRegistry`` counts: a test runtime's MagicMock attribute would otherwise issue a MagicMock id.
        """
        registry = getattr(getattr(self, "_runtime", None), "cycle_registry", None)
        return registry if isinstance(registry, CycleIdRegistry) else None
```
REPLACE:
```
        Only a real ``CycleIdRegistry`` counts (``is_cycle_registry``): a test runtime's MagicMock attribute, spec'd or
        not, would otherwise issue a MagicMock id.
        """
        registry = getattr(getattr(self, "_runtime", None), "cycle_registry", None)
        return registry if is_cycle_registry(registry) else None
```

### 16.3 `src/probos/cognitive/turn_promotion.py` (M-R1)

**RE1.** SEARCH:
```
from probos.cycle_trace import CycleIdRegistry  # AD-1360 (#1828)
```
REPLACE:
```
from probos.cycle_trace import is_cycle_registry  # AD-1360 (#1828)
```
**RE2.** SEARCH:
```
    Nothing is registered without a ``CycleIdRegistry`` on the runtime or for a blank id.
    """
    registry = getattr(runtime, "cycle_registry", None)
    if isinstance(registry, CycleIdRegistry) and type(work_item_id) is str and work_item_id.strip():
```
REPLACE:
```
    Nothing is registered without a real ``CycleIdRegistry`` on the runtime (not a spec'd mock) or for a blank id.
    """
    registry = getattr(runtime, "cycle_registry", None)
    if is_cycle_registry(registry) and type(work_item_id) is str and work_item_id.strip():
```

### 16.4 `tests/test_ad1360_s2b_entry_chains.py` (M-R1)

Three cases are added at the end (E14: the predicate and `issue_entry_id` on every kind of stand-in; E15: the agent's getter and a promoted work item's registration; E16: the chain, with an autospec registry on the runtime, to the stored rows), and E1 runs its stray-registry checks over every stand-in. The file has 16 cases.

**RT1.** SEARCH:
```
from unittest.mock import AsyncMock, MagicMock, patch
```
REPLACE:
```
from unittest.mock import AsyncMock, MagicMock, Mock, create_autospec, patch
```
**RT2.** SEARCH:
```
from probos.cognitive.cognitive_agent import CognitiveAgent
```
REPLACE:
```
from probos.cognitive import turn_promotion
from probos.cognitive.cognitive_agent import CognitiveAgent
```
**RT3.** SEARCH:
```
    entry_scope,
    issue_entry_id,
```
REPLACE:
```
    entry_scope,
    is_cycle_registry,
    issue_entry_id,
```
**RT4.** SEARCH:
```
        _knowledge_store=None, workflow_cache=None, cycle_registry=registry, _record_error=MagicMock(),
    )
```
REPLACE:
```
        _knowledge_store=None, workflow_cache=None, cycle_registry=registry, _record_error=MagicMock(),
    )


class _Subclass(CycleIdRegistry):
    """A registry of a subclass is a registry."""


def _fakes() -> list[Any]:
    """What is not a registry: nothing, a namespace, a plain mock, and the mocks that name the registry class as their
    spec (they pass ``isinstance``, and their ``issue()`` returns another mock)."""
    return [
        None, SimpleNamespace(), MagicMock(), MagicMock(spec=CycleIdRegistry), Mock(spec=CycleIdRegistry),
        create_autospec(CycleIdRegistry, instance=True),
    ]
```
**RT5.** SEARCH:
```
    for stray in (None, MagicMock(), SimpleNamespace()):
```
REPLACE:
```
    for stray in _fakes():
```
**RT6.** SEARCH:
```
        assert issue_entry_id(registry, kind="hxi_post") == "0123456789ab" and len(registry) == held
```
REPLACE:
```
        assert issue_entry_id(registry, kind="hxi_post") == "0123456789ab" and len(registry) == held
        assert {issue_entry_id(fake, kind="hxi_post") for fake in _fakes()} == {"0123456789ab"}  # a bound id needs none
```
**RT7.** SEARCH:
```
    with entry_scope(MagicMock(), kind="nl_request") as bound:
        assert bound == current_cycle_id() == ""
```
REPLACE:
```
    for fake in _fakes():
        with entry_scope(fake, kind="nl_request") as bound:
            assert bound == current_cycle_id() == ""
```
**RT8.** SEARCH:
```
    assert {kw.arg: ast.unparse(kw.value) for kw in calls[0].keywords}.get("cycle_registry") == "cycle_registry"
```
REPLACE:
```
    assert {kw.arg: ast.unparse(kw.value) for kw in calls[0].keywords}.get("cycle_registry") == "cycle_registry"


# -- E14 to E16: a mock that names the registry class as its spec is not a registry --------------------------------------


def test_only_a_real_registry_is_a_cycle_registry() -> None:
    assert is_cycle_registry(CycleIdRegistry()) and is_cycle_registry(_Subclass())
    assert not is_cycle_registry(CycleIdRegistry)  # the class is not an instance of itself
    for fake in _fakes():
        assert not is_cycle_registry(fake)
    assert {issue_entry_id(fake, kind="hxi_post") for fake in _fakes()} == {""}
    registry = _Subclass()
    assert registry.kind_of(issue_entry_id(registry, kind="hxi_post")) == "hxi_post"


def test_a_mock_runtime_registry_is_no_registry_for_the_agent_or_a_promoted_work_item() -> None:
    for fake in _fakes():
        agent = _Agent()
        agent._runtime = SimpleNamespace(cycle_registry=fake)
        assert agent._cycle_registry is None and len(agent._issue_cycle_id()) == 12
        turn_promotion._register_promoted_work_item(SimpleNamespace(cycle_registry=fake), "ad1360workitem")
    spec = create_autospec(CycleIdRegistry, instance=True)
    turn_promotion._register_promoted_work_item(SimpleNamespace(cycle_registry=spec), "ad1360workitem")
    spec.register.assert_not_called()
    for real in (CycleIdRegistry(), _Subclass()):
        agent = _Agent()
        agent._runtime = SimpleNamespace(cycle_registry=real)
        assert agent._cycle_registry is real
        turn_promotion._register_promoted_work_item(SimpleNamespace(cycle_registry=real), "ad1360workitem")
        assert real.kind_of("ad1360workitem") == "work_item"


async def test_a_mock_registry_on_the_runtime_costs_no_episode_and_certifies_no_id(
    memory: EpisodicMemory, registry: CycleIdRegistry, tmp_path: Path,
) -> None:
    from probos.routers.agents import agent_chat
    from probos.runtime import ProbOSRuntime

    fake = create_autospec(CycleIdRegistry, instance=True)  # ``registry`` stays the one the memory judges ids by
    engine = FeedbackEngine(
        trust_network=MagicMock(), hebbian_router=MagicMock(), episodic_memory=memory, cycle_registry=fake,
    )
    assert (await engine.apply_execution_feedback(TaskDAG(nodes=[]), True, "Survey the coolant loop")).episode_stored
    writer = VerificationEpisodeWriter(runtime=SimpleNamespace(episodic_memory=memory, cycle_registry=fake))
    assert await writer.write(GroundTruthResult(
        verified=False, score=0.0, agent_id="ad1360-agent", claimed_summary="Surveyed the coolant loop on deck four.",
    ))
    rt = _route_runtime(tmp_path, modes=False)
    rt.registry.get.return_value.sovereign_id = "ad1360-dm-agent"
    rt.episodic_memory = memory
    rt.cycle_registry = fake
    rt.intent_bus.send = AsyncMock(return_value=IntentResult(
        intent_id="ad1360-intent", agent_id="ad1360-dm-agent", success=True, result=_REPLY,
    ))
    with patch("probos.routers.agents.is_crew_agent", return_value=True):
        await agent_chat("test-agent", _chat_request(_QUESTION), rt)
    host = SimpleNamespace(episodic_memory=memory, identity_registry=None)

    async def _run(**_kwargs: Any) -> str:
        await ProbOSRuntime._store_mcp_invoke_episode(
            host, server_url="mcp.ad1360", tool="survey", tier="open", success=True, agent_id="ad1360-survey",
        )
        return "Acknowledged; surveying the coolant loop."

    agent = _Agent()
    agent._runtime = SimpleNamespace(cycle_registry=fake, chat_thread_store=None, work_item_store=None)
    agent._run_agentic_dispatch = _run  # type: ignore[method-assign]
    result = await agent._handle_work_item_dispatch(IntentMessage(
        intent="work_item_dispatched", params={"work_item_id": "ad1360fakeitem", "title": "Survey"},
        target_agent_id=agent.id,
    ))
    assert result.success and current_cycle_id() == ""
    needles = ("Survey the coolant loop", "Surveyed the coolant loop", "[1:1 with", "[mcp_invoke] survey on mcp.ad1360")
    assert [_one(memory, needle) for needle in needles] == [("", VERDICT_EMPTY)] * 4
    assert fake.method_calls == [] and not registry.resolves("ad1360fakeitem")
```

### 16.5 `PROGRESS.md` (M-R1)

**TR1.** SEARCH (substring of S2b's entry in `PROGRESS.md`, once): `(13 cases) from real producers`. REPLACE: `(16 cases) from real producers`.

### 16.6 `DECISIONS.md` (M-R1)

**TR2.** SEARCH (substring of the last S2b bullet, once): `both pass the think's id meanwhile.` REPLACE:
```
both pass the think's id meanwhile.
- *S2b repair after review round 1.* Three checks decide whether a runtime's `cycle_registry` attribute is a registry (`issue_entry_id`, `CognitiveAgent._cycle_registry`, `_register_promoted_work_item`); each used `isinstance`, which a mock made with `spec=CycleIdRegistry` or `create_autospec` passes, and whose `issue()` returns another mock, so the producers lost the episode. They call `cycle_trace.is_cycle_registry` (`issubclass(type(obj), CycleIdRegistry)`: a registry or an instance of a subclass, not a mock). Decided by the Architect (consult `36e52865`): fixed in this batch at all three sites, not recorded. Pinned by three cases of `tests/test_ad1360_s2b_entry_chains.py`.
```

### 16.7 Mutation rows (campaign on the repaired tree; restore between rows)

`mutants_gen.py` over `audit\rows_ad1360s2br1.py`: each row changes one line of the repaired tree in place and runs the entry-chains test file (16 cases, all green before the row).

| Row | Mutant | Killed by |
|---|---|---|
| RS1 | `issue_entry_id` back to `isinstance(registry, CycleIdRegistry)` | E1, E14, E16 |
| RS2 | `is_cycle_registry` returns `isinstance(obj, CycleIdRegistry)` | E1, E14, E15, E16 |
| RS3 | `is_cycle_registry` narrowed to `type(obj) is CycleIdRegistry` | E14, E15 |
| RS4 | the agent's getter back to `isinstance(registry, CycleIdRegistry)` | E15, E16 |
| RS5 | the promoted work item registers into any non-None registry | E15 |

### 16.8 Properties for the round-2 Diff Reviewer (the delta only)

Verify at least one end-to-end path by execution: a runtime whose `cycle_registry` is `create_autospec(CycleIdRegistry, instance=True)`, a real ChromaDB-backed `EpisodicMemory` and the real feedback engine, ground-truth writer, DM route and work-item dispatch: each stores exactly one episode with the empty id, and the mock is never called.
1. `is_cycle_registry` is true for `CycleIdRegistry()` and an instance of a subclass, and false for None, `SimpleNamespace()`, `MagicMock()`, `MagicMock(spec=CycleIdRegistry)`, `Mock(spec=CycleIdRegistry)`, `create_autospec(CycleIdRegistry, instance=True)` and the class itself.
2. No `isinstance(..., CycleIdRegistry)` remains in `src/probos` that decides whether an object is a registry; `rg "isinstance\(.*CycleIdRegistry" src` finds none, and the other readers of a registry (`runtime.py`'s own, the memory's resolver binding in S1) are not affected.
3. The three sites behave as before for a real registry: `issue_entry_id` returns the bound id when one is bound (whatever the registry), else an id the registry issued under the kind; `_cycle_registry` returns the registry; a work item registers when its id is a non-blank `str`.
4. `turn_promotion.py` no longer imports `CycleIdRegistry` and nothing else in it used the name; `cycle_trace.py` still imports only the standard library; the import order of the touched files is kept.
5. The three new cases and the changed E1 delete, loosen or skip nothing; E14 to E16 fail on the S2b head (E14 and E15 by the spec'd mocks, E16 by the lost episodes) and pass after the repair; each row of section 16.7 fails its named killers.

### 16.9 The orchestrator's first-hand checks of the repair (2026-11-21, an oracle tree detached at `9facefd9` with the S2a repair applied)

| O | Result |
|---|---|
| R1 | The finding was reproduced before the repair: the new cases on the unrepaired source (pairs RT1 to RT8 only, with the predicate standing in as `isinstance`, the previous check): **4 failed, 12 passed**. E1 fails because `issue_entry_id` of a `MagicMock(spec=CycleIdRegistry)` returns `<MagicMock name='mock.issue()'>` where `""` is expected; E14 because the predicate accepts the spec'd mock; E15 because the agent's getter returns it; E16 because the feedback engine's episode is not stored (`Failed to store feedback episode: Expected metadata value to be a str, int, float, bool, SparseVector, list, or None, got <MagicMock name='mock.issue()'`), the symptom the reviewer's probes found. |
| R2 | After the pairs of 16.1 to 16.6: **16 passed** (the entry-chains file). Every SEARCH occurs exactly once, in files that are CRLF throughout. |
| R3 | The campaign of 16.7: baseline of 16 cases green; **killed 5, differs 0, survived 0, invalid 0**; every named killer failed. |
