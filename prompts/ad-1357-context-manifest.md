# AD-1357 (#1749): a crew chat reply records what it was given — a context manifest beside the reply, and a journal row for the agentic DM turn

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05
**Revised by:** the orchestrator (Copilot), 2026-11-06, after applying every pair by tool and running the gates on a scratch tree: Absence A7's FOUND names the docstring hit at `federation/bridge.py:2237`; the mutation rows CXM-21 to CXM-23 mutate to `pass` (their statement is the only body of its block, so deleting the line is an `IndentationError` that fails every test, not the claimed case; with `pass` each is killed by its claimed T16 case alone); and each milestone that removes a marker's last decorator also deletes that marker's definition line (§7.2 to §7.4), so no `_UNTIL_` constant is left unused. No pair, count or test changes.
**Status:** ready to build.
**Base:** drafted on `8ecf968d567632ea09316406dc9d7fdb3d98c7c1` (tree `d0733f9e`), the head of the AD-1346 M3e4d6 to M3e4d8 batch. That batch changes only admission, census, `capability_request.py`, `artifacts`, `workforce.py` and tests, so every file this contract anchors in is as on `origin/main` `1c01a5ee`.
**Dependencies:** none. BF-952 (#1751) edits `knowledge/records_store.py` and the trackers. This contract does not touch `records_store.py`, and section 8 re-anchors the tracker pairs.
**Tier:** M1 STANDARD; M2, M3 and M4 STANDARD with a shared contract each (§4); M5 STANDARD.
**Estimated tests:** one new file, `tests/test_ad1357_context_manifest.py`, with 20 functions and 37 cases. Both counts were made by reading the file as written in §7.1, not by running it. No existing test is edited.
**AD number:** AD-1357, held by the title of #1749. `scripts/ad_ceiling.py` reports CEILING AD-1358 (from GitHub issue titles, all states). Nothing new is allocated.

**Which text describes the head.** Line numbers are those of `8ecf968d`. Before building, run `git diff --stat 8ecf968d HEAD -- src/probos/cognitive/cognitive_agent.py src/probos/cognitive/oracle_service.py src/probos/cognitive/transcript_grounding.py src/probos/routers/agents.py src/probos/routers/thread_fanout.py`. It must be empty. A SEARCH that no longer matches goes back to the Architect; do not rebase it by hand. Where prose and a block differ, the block wins. The two tracker pairs (§8) are the only re-anchoring allowed.

## 1. Problem

1. The stored metadata of a 1:1 crew reply is `_build_reply_metadata` (`routers/agents.py:2840-2872`): `intent_id`, `tool_trace_ref` when non-empty, and `emotion`. A group reply's metadata is `{"intent_id", "fanout"}` plus `generated_attachment_ids` (`routers/thread_fanout.py:965-967`). Neither records what the prompt held.
2. The DM prompt is assembled from `_emit` bids (`cognitive_agent.py:10496-10519` and `:10529-10808`; the source names run from `boot_snapshot` to `camera_scene_ambient`). `ContextAssembler.assemble` keeps bids by salience under a token budget and calls `render()` only on the ones it keeps (`attention.py:89-124`). Nothing records which bids existed or which survived.
3. Recall facts exist only as transient observation keys or log lines:
   - the query (`:11436`);
   - the fed episodes (`:11830-11915`), where the BF-631 INFO line is the only trace and the memory dicts carry no episode id (`:11853-11857`);
   - the AD-981a/AD-1038 probe (`:11943-11952`), which stores only the band and the recall type;
   - cross-agent recall (`:11926-11932`);
   - transcript grounding (`:11962-12006`);
   - the passive Oracle (`:11722-11768`), whose `query_formatted` returns text only (`oracle_service.py:721-780`).
4. The AgenticLoop branch returns at `cognitive_agent.py:4407-4417`, before the journal write at `:4572-4610`. Nothing in `agentic_dispatch.py` writes a journal row (Absence A8). So an agentic DM turn has no journal row, while a single-pass DM turn has one.

## 2. Solution

1. **A new stdlib-only module, `cognitive/context_manifest.py`.** It builds a bounded, JSON-safe manifest:
   - the sections, in emission order, with each one's character count and whether it was kept;
   - text appended after assembly;
   - recall: whether it ran, the query (when it is the Captain's words), the agent's own episode ids and source tags, and the band, best similarity and recall type;
   - the lookups: cross-agent recall (count), transcript grounding (room id) and the Oracle (counts per tier, Ship's Records paths);
   - the journal's two hashes and the id of the turn's journal row.
2. **Where the facts are collected.** `_build_user_message` gives each DM bid the ledger's renderer. `_recall_relevant_memories` notes recall and the lookups. `_decide_via_llm` finishes the manifest on both exits.
3. **How it reaches the stored reply.** `_build_result_metadata` carries it, as its last key. The 1:1 route and the group fan-out store it.
4. **The journal row.** The agentic branch writes one row for the DM turn.
5. **Unchanged:** the prompt text, ranking, retrieval and config.

## 3. Decisions

**CM1, the shape and where it lives (ranked):**
1. **Chosen:** inline, under `metadata["context_manifest"]`. Retention is the row's own.
   - **Readers:** `ChatThreadMessage.to_dict` (`threads/__init__.py:198-207`) through `GET /api/threads/{id}/messages` (`routers/threads.py:454`).
   - **Consumers that ignore unknown keys** read only their named keys: `room_inputs.py:151` (attachments), `thread_fanout.py:548` (convergence), `transcript_grounding.py:70-74` (callsign). The HXI's `ConsultedEvidence` reads only `tool_trace_ref` (Absence A5, A11).
2. A content-addressed ref (`tool_trace_ref`'s pattern). Rejected: the blob is kept and reaped on its own schedule, it needs a resolver and an HXI change, and the typical manifest is about 1.8 KB.
3. A new table keyed by message id. Rejected: a second store and a join for every reader.

**CM2, the producer (ranked):**
1. **Chosen:** `ContextLedger.renderer(source, text)` replaces the lambda renderer of each DM `_emit` bid.
   - It returns the same `text` object and marks the section kept. Survival is therefore the fact the assembler already guarantees, and the prompt is byte-identical (the AD-1028 golden).
   - Names come from `_emit`'s `source`, so a new section is recorded with no change to the manifest code (T10).
2. A survivors API on `ContextAssembler` or `AttentionFaculty`. Rejected: both are pure and golden-pinned (AD-1028, AD-1029).
3. Re-deriving sections from observation keys. Rejected: it duplicates every `_emit` condition.

**CM3, the journal row (ranked):**
1. **Chosen:** one row on the agentic branch only: `tier="agentic"`, `model="unknown"`, empty `token_source`, `cached` 0, `dag_node_id="dm-turn"`, the hashes and `intent_id`.
   - BF-901's doctor requires `model` to name the answering model or "unknown" (`doctor/checks/token_accounting_check.py:171`).
   - An empty source is filed as uncharged (`journal_token_report.py:15-16`), as BF-183's timeout rows are (`sub_task.py:589-602`).
   - The single-pass row already exists (`cognitive_agent.py:4585-4608`, `entry_id=request.id`).
2. `cached=True`, after the cache-hit precedent at `:3748-3758`. Rejected: the report would file it as replayed.
3. A separate table. Rejected: `get_reasoning_chain` would not show it.
4. Journaling each loop call. Deferred: that is the gap BF-901 S2 left (`journal_token_report.py:23-24`).

**CM4, privacy (ranked):**
1. **Chosen:**
   - Identify the agent's own episode ids and source tags, Ship's Records result paths, and the agent's own transcript room.
   - Count cross-agent results and every other Oracle tier.
   - Keep the query only when `params["captain_message"]` is a non-empty `str` on a turn that is not a group chat. Otherwise only its length is kept: a group query is the room's trigger, and the `text` fallback can lead with the camera scene (AD-733a, `routers/agents.py:3565`).
   - Pinned by T3 (4 cases) and T15.
2. Hash the peer ids. Rejected: a stable pointer into another agent's memory.
3. Include peer ids. Rejected: that widens exposure, so it would be a Captain item.
4. Never keep the query. Rejected: it is the Captain's own text in the Captain's own thread, and it is what made BF-631's line useful.
- **Federation:** the manifest never leaves the vessel. `_serialize_directed_result` forwards only `dm_reply` (`federation/bridge.py:943-947`).

**CM5, the wire.** The manifest is the last key of `_build_result_metadata`. BF-805's `_prune_metadata` keeps keys greedily in iteration order (`mesh/intent.py:2387-2390`), so when the envelope is too large the manifest is dropped first (T9). `storable` returns a stub when the store's own encoding would refuse the manifest (`threads/__init__.py:1474-1482`), because the 1:1 append catches that refusal and the Captain would lose the reply in the transcript (`routers/agents.py:3849-3853`).

**CM6, flags and cost.**
- No `SystemConfig` field. The feature is always on, and the recall-off case is recorded as `{"ran": false}`.
- Size is at most `MAX_MANIFEST_BYTES` (16 KiB), enforced by `storable`. The worst case at every cap is about 13.7 KB of ASCII by hand, and the incident-shaped case about 1.8 KB by hand. Both are pinned by T4a. If T4a fails, that is a hard stop that comes back here; do not raise the constant.
- CPU cost is not measured.

**CM7, the sinks (ranked):**
1. **Chosen:** the 1:1 route (`routers/agents.py:3837-3848`) and the group fan-out (`routers/thread_fanout.py:965-972`), the two paths #1749 names.
2. Also the inline-callsign route (`routers/chat.py:586-592`), the main-chat multi-agent append (`:328-337`, built from `PerAgentReply`) and the deferred-turn replay (`startup/finalize.py:3103-3109`). Deferred (L1): each persists through a different reply shape, and each needs its own crossing test.

## 4. Milestones and gates

| M | Tier | Shared contract? | Pairs | Gate |
|---|---|---|---|---|
| M1 | STANDARD | test only | N1-1 | G1 |
| M2 | STANDARD | **yes**: `metadata["context_manifest"]` and its key order, read by the HXI API and the stored rows | N2-1, P2-1 to P2-14 | G2 |
| M3 | STANDARD | **yes**: `OracleService.query_formatted` and `consult_transcript` gain `sources_out` | P3-1 to P3-13 | G3 |
| M4 | STANDARD | **yes**: the journal row's shape, read by `journal_token_report`, `get_token_usage*`, EPS capacity and the doctor | P4-1 | G4 |
| M5 | STANDARD | trackers | P5-1, P5-2, ledger | G5 |

For M2 to M4 the Diff Reviewer covers each whole contract (§16), not only the delta.

- **M0:** on the base, record the collected count of every existing file named in G1 to G4.
- `PY` below means `d:/ProbOS/.venv/Scripts/python.exe`.
- **G1:** `PY -m pytest tests/test_ad1357_context_manifest.py -q -n 0`.
  - Expected: **4 passed (T7b ×4), 33 xfailed.**
  - Any other count is a hard stop.
- **G2:** `PY -m pytest tests/test_ad1357_context_manifest.py tests/test_ad1028_context_assembler.py tests/test_ad1029_attention_faculty.py tests/test_ad1030_salience.py tests/test_ad1031_camera_bid.py tests/test_ad1032_arousal.py tests/test_ad1036_exogenous_mention.py tests/test_ad1227_recent_outputs.py tests/test_ad1270_boot_camp_orientation.py tests/test_ad1203_turn_provenance.py tests/test_ad1248_slice_a_crossing.py tests/test_ad1295_tool_success_ledger.py tests/test_ad914_group_chat_fanout.py tests/test_ad1275_sink_side_composition.py tests/test_cognitive_journal.py tests/test_bf901_s2_journal_token_provenance.py tests/test_ad981b_recall_confidence_gating.py tests/test_ad631_skill_effectiveness.py tests/test_ad723a_1_consumer_migration.py tests/test_events.py tests/test_ad700c_diagnostician_tier_routing.py tests/test_ad492_cognitive_correlation_ids.py -q -n 0`, then `PY -P scripts/check_architecture_principles.py --check`.
  - Expected in the new file: **26 passed, 11 xfailed.** Others: 0 failed, with counts equal to M0.
  - Hard stop: `test_dm_golden_byte_identical` failing means the ledger changed the prompt.
- **G3:** `PY -m pytest tests/test_ad1357_context_manifest.py tests/test_ad986b_transcript_grounding.py tests/test_bf625_transcript_ranking.py tests/test_ad979d_cross_agent_recall.py tests/test_ad979d_slice2_live_wiring.py tests/test_ad1038_remember_know_render.py tests/test_ad981b_recall_confidence_gating.py tests/test_ad1294_read_provenance_rendering.py tests/test_ad988_retrieval_reason.py tests/test_memory_architecture.py tests/test_ad1341_s2_inherited_label.py tests/test_ad620_clearance_model.py tests/test_ad619_counselor_awareness.py tests/test_bf138_sovereign_id_completion.py tests/test_cognitive_agent.py tests/test_memory_integrity.py tests/test_ad604_spreading_activation.py tests/test_ad570c_nl_anchor_query.py tests/test_ad1226_recall_artifact.py tests/test_ad1034_cognitive_spine.py tests/test_ad696_agentic_oracle_retrieval.py -q -n 0`, then the architecture check.
  - Expected in the new file: **36 passed, 1 xfailed (T6).** Others: 0 failed.
- **G4:** `PY -m pytest tests/test_ad1357_context_manifest.py tests/test_ad1065_conversational_agentic.py tests/test_ad1208_cost_bounded_turns.py tests/test_ad1165_turn_promotion.py tests/test_ad1246_long_run_promotion.py tests/test_ad1248_slice_a_gaps.py tests/test_ad1257_defect_follows_failure.py tests/test_ad1205_fault_paths.py tests/test_ad1180_agentic_disposition.py tests/test_ad1167_conversational_compaction.py tests/test_ad1224_durable_tool_start.py tests/test_ad1322_economic_judgment_integration.py tests/test_ad1323_continue_extension_seam.py tests/test_ad1324_tier_choice_e2e.py tests/test_ad1341_s4_stand_down.py tests/test_bf697_agentic_final_text_on_max_iterations.py tests/test_bf698_thread_provenance.py tests/test_bf887_continue_resumes_the_promoted_turn.py tests/test_cognitive_journal.py tests/test_bf901_s2_journal_token_provenance.py tests/test_bf901_s3_token_accounting_view.py -q -n 0`, then the architecture check.
  - Expected: **37 passed** in the new file. Others: 0 failed.
- **G5:** `PY -P scripts/gen_ad_ledger.py`; `PY -P scripts/gen_ad_ledger.py --check`; `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **The harness rule (applies to G1 to G4).** The new tests drive real `_decide_via_llm` and `_recall_relevant_memories` with a `SimpleNamespace` runtime. If a test fails only because the runtime lacks an attribute the DM path reads, the Builder may add that attribute to `_runtime()` as `None` or as an inert value, and must report which. Not allowed: a source change, a skip, a `MagicMock` runtime (it makes `dm_agentic.enabled` truthy), or loosening an assertion. Any of those goes back to the Architect.
- The broad gate runs once, in the main session with `--receipt`, after the review repairs.

## 5. Commit messages

- M1: `AD-1357 M1: tests for the DM reply's context manifest and the DM-turn journal row, xfail until built`
- M2: `AD-1357 M2: a crew DM reply carries a context manifest of its prompt sections, stored beside it`
- M3: `AD-1357 M3: the manifest records recall and the cross-agent, transcript and Oracle lookups`
- M4: `AD-1357 M4: an agentic DM turn writes one cognitive-journal row, named by the manifest`
- M5: `AD-1357 M5: trackers and ledger`

## 6. Tests (`tests/test_ad1357_context_manifest.py`)

| Id | Test | Cases | Covers | xfail until |
|---|---|---|---|---|
| T1 | `test_a_dm_reply_with_recall_an_active_game_and_a_records_hit_lists_all_three` | 1 | Acceptance 1 and 2: recall → prompt → result metadata → reply metadata → stored row | M3 |
| T2 | `test_a_dm_reply_with_recall_off_says_recall_did_not_run` | 3 | Acceptance 2 (recall off) | M2 |
| T3 | `test_the_manifest_holds_no_other_agents_text_and_no_camera_scene` | 4 | Acceptance 3, CM4 | M3 |
| T4a | `test_the_manifest_fits_its_bound_at_every_cap` | 1 | CM6 | M2 |
| T4b | `test_a_similarity_that_is_not_a_finite_number_is_recorded_as_none_and_the_row_stores` | 5 | CM5 | M2 |
| T4c | `test_a_manifest_the_store_would_refuse_is_replaced_by_a_stub_that_says_so` | 3 | CM5 | M2 |
| T5 | `test_the_manifest_names_its_journal_row_on_the_single_pass_path` | 1 | CM3, the match | M2 |
| T6 | `test_an_agentic_dm_turn_writes_one_journal_row_that_the_manifest_names` | 1 | Acceptance 4, CM3 | M4 |
| T7 | `test_the_reply_metadata_carries_the_manifest_the_agent_made` | 1 | 1:1 sink | M2 |
| T7b | `test_a_reply_without_a_manifest_keeps_its_metadata_unchanged` | 4 | compatibility | none |
| T8 | `test_a_group_reply_is_stored_with_its_manifest_and_one_without_stays_unchanged` | 1 | group sink, real fan-out | M2 |
| T9 | `test_the_manifest_is_the_last_reply_metadata_key_so_bf805_drops_it_first` | 1 | CM5 | M2 |
| T10 | `test_a_section_is_recorded_by_its_name_alone_and_kept_only_when_assembly_renders_it` | 1 | CM2 registry | M2 |
| T11 | `test_a_section_the_attention_budget_drops_is_recorded_as_not_kept` | 1 | CM2, "dropped" | M2 |
| T13 | `test_the_oracle_reports_what_it_rendered_and_renders_the_same_text` | 1 | `sources_out` | M3 |
| T14 | `test_transcript_grounding_reports_the_room_its_excerpt_came_from` | 2 | `sources_out` | M3 |
| T15 | `test_only_ship_records_results_are_identified_and_every_tier_is_counted` | 1 | CM4 | M2 |
| T16 | `test_text_appended_after_assembly_is_recorded_by_name_and_length` | 3 | appended sections | M2 |
| T17 | `test_recall_records_the_room_transcript_grounding_drew_on` | 1 | AD-986b record | M3 |
| T18 | `test_a_graph_only_lookup_is_recorded_with_its_scope` | 1 | BF-265 branch | M3 |

## 7. The contract

### 7.1 M1

**N1-1** `tests/test_ad1357_context_manifest.py` (new)

```python
"""AD-1357 (#1749): what a crew chat reply was given, recorded beside the reply.

A crew ``direct_message`` reply carries a context manifest under its stored
``metadata["context_manifest"]``: the prompt's sections by name, size and whether
the budget kept them; what recall fed (the agent's own episode ids and source
tags, the band); which lookups ran and what they returned (Ship's Records paths,
the transcript room id, counts); and the journal row the turn wrote.

Real fixtures where the chain matters: a real ``CognitiveAgent`` through
``_recall_relevant_memories`` and ``_decide_via_llm``, a real ``OracleService`` over
a real ``RecordsStore`` on ``tmp_path``, a real ``CognitiveJournal``, a real
``ChatThreadStore`` and the real AD-914 group fan-out over a real ``IntentBus``.
The runtime is a ``SimpleNamespace`` with a real ``SystemConfig``: a ``MagicMock``
config would make ``dm_agentic.enabled`` truthy and run the AgenticLoop. Names
the change adds are imported inside the tests, so the file collects on the base.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.attention import estimate_tokens
from probos.cognitive.cognitive_agent import CognitiveAgent, _build_result_metadata
from probos.cognitive.episodic import RecallConfidence
from probos.cognitive.journal import CognitiveJournal
from probos.cognitive.oracle_service import OracleService, make_reader_identity_resolver
from probos.config import RecordsConfig, SystemConfig
from probos.knowledge.records_store import RecordsStore
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.agents import _build_reply_metadata
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import Episode, IntentMessage, IntentResult, LLMResponse
from tests.fixtures.ad1028_golden._capture_golden import dm_observation, make_dm_agent

_UNTIL_M2 = pytest.mark.xfail(strict=True, reason="AD-1357 M2: a DM reply carries no context manifest")
_UNTIL_M3 = pytest.mark.xfail(strict=True, reason="AD-1357 M3: recall and the lookups are not recorded")
_UNTIL_M4 = pytest.mark.xfail(strict=True, reason="AD-1357 M4: an agentic DM turn writes no journal row")

AGENT_ID = "ad1357-ezri"
GAME_RECORD = "recreation/games/tictactoe/game-58042e2b4637.md"
GAME_QUERY = "tictactoe Captain Ezri"
FROZEN_TEMPORAL = "Current time: 2026-11-05 12:00:00 UTC (Thursday)"
NO_LOOKUPS = {
    "cross_agent_recall": {"ran": False},
    "transcript_grounding": {"ran": False},
    "oracle": {"ran": False},
}


async def _empty_sensorium(path: object, observation: dict) -> dict[str, str]:
    del path, observation
    return {}


class _OneReply:
    """An ``llm_client`` that answers every request with one reply and keeps the requests."""

    def __init__(self, content: str) -> None:
        self.content = content
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            content=self.content, model="scripted", tier="standard",
            tokens_used=10, prompt_tokens=5, completion_tokens=5,
        )


class _Episodic:
    """What ``_recall_relevant_memories`` reads of episodic memory (the BASIC path: no ``recall_weighted``)."""

    def __init__(self, episodes: list[Episode], confidence: RecallConfidence | None = None) -> None:
        self._episodes = episodes
        self._confidence = confidence or RecallConfidence(
            band="strong", best_similarity=0.9, candidate_count=len(episodes), query="",
        )

    async def count_for_agent(self, _mem_id: str) -> int:
        return len(self._episodes)

    async def recall_for_agent(self, _mem_id: str, _query: str, k: int = 3) -> list[Episode]:
        return list(self._episodes)

    async def recent_for_agent(self, _mem_id: str, k: int = 3) -> list[Episode]:
        return []

    async def recall_for_agent_with_confidence(self, _mem_id: str, _query: str, k: int = 5) -> Any:
        return [], self._confidence


class _Recreation:
    """``RecreationService``'s three reads for the AD-572 active-game block."""

    def get_game_by_player(self, callsign: str) -> dict[str, Any] | None:
        if callsign != "Ezri":
            return None
        return {
            "game_id": "game-1", "game_type": "tictactoe", "challenger": "Captain",
            "opponent": "Ezri", "state": {"current_player": "Captain"}, "moves_count": 0,
        }

    def render_board(self, _game_id: str) -> str:
        return " | | \n-+-+-\n | | \n-+-+-\n | | "

    def get_valid_moves(self, _game_id: str) -> list[int]:
        return []


def _config(**memory: Any) -> SystemConfig:
    config = SystemConfig()
    for name, value in memory.items():
        setattr(config.memory, name, value)
    return config


def _runtime(**attributes: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "config": SystemConfig(),
        "cognitive_journal": None,
        "episodic_memory": None,
        "ontology": None,
        "trust_network": None,
        "recreation_service": None,
    }
    base.update(attributes)
    return SimpleNamespace(**base)


def _agent(runtime: Any, llm: Any, *, agent_type: str = "scout") -> CognitiveAgent:
    """A real agent (test_ad1038's construction); clock and sensorium pinned as AD-1028's golden pins them."""
    agent = CognitiveAgent(agent_id=AGENT_ID, instructions="You are Ezri.")
    agent.agent_type = agent_type
    agent.callsign = "Ezri"
    agent._runtime = runtime
    agent._llm_client = llm
    agent._build_temporal_context = lambda: FROZEN_TEMPORAL  # type: ignore[method-assign]
    agent._dispatch_sensorium_async = _empty_sensorium  # type: ignore[method-assign]
    return agent


def _observation(params: dict[str, Any], *, intent_id: str) -> dict[str, Any]:
    return {"intent": "direct_message", "intent_id": intent_id, "params": params}


async def _turn(agent: CognitiveAgent, params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recall, then the decision, in ``_run_cognitive_lifecycle``'s order; returns (observation, decision)."""
    intent = IntentMessage(intent="direct_message", params=params)
    observation = await agent._recall_relevant_memories(intent, _observation(params, intent_id=intent.id))
    decision = await agent._decide_via_llm(observation)
    return observation, decision


def _manifest_of(observation: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """The manifest as ``IntentResult.metadata`` carries it, through the production construction."""
    return _build_result_metadata({}, decision, observation)["context_manifest"]


def _names(manifest: dict[str, Any]) -> list[str]:
    return [section["name"] for section in manifest["sections"]]


def _in_order(wanted: list[str], names: list[str]) -> bool:
    remaining = iter(names)
    return all(name in remaining for name in wanted)


def _seq_clock():
    count = {"t": 0}

    def _clock() -> float:
        count["t"] += 1
        return float(count["t"])

    return _clock


async def _records_oracle(tmp_path: Path) -> OracleService:
    """A real ``OracleService`` over a real ``RecordsStore`` holding one AD-526a-shaped game record.

    Each query word appears as a whole word, so the record matches under both the
    substring scorer on the base and BF-952's word-boundary scorer.
    """
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    await store.initialize()
    await store.write_entry(
        "captain", GAME_RECORD,
        "# tictactoe\n\ntictactoe game between Captain and Ezri. Result: Captain wins.\n",
        "AD-1357 fixture", classification="ship",
    )
    oracle = OracleService(records_store=store)
    oracle.attach_reader_identity_resolver(
        make_reader_identity_resolver(
            registry=SimpleNamespace(
                get=lambda aid: SimpleNamespace(agent_type="scout", callsign="Ezri", sovereign_id="")
                if aid == AGENT_ID else None,
                all=lambda: [],
            ),
            ontology=SimpleNamespace(get_agent_department=lambda _t: "science"),
        )
    )
    return oracle


def _thread_store(tmp_path: Path) -> ChatThreadStore:
    return ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())


# ── T1: the crossing ─────────────────────────────────────────────────


@_UNTIL_M3
async def test_a_dm_reply_with_recall_an_active_game_and_a_records_hit_lists_all_three(tmp_path: Path) -> None:
    """#1749 acceptance 1 and 2, across every seam: recall, the prompt, the result's metadata, the reply's
    metadata, the stored row."""
    episodes = [
        Episode(id="ep-own-direct-0001", timestamp=1.0, user_input="The Captain and I ran the warp drill.", source="direct"),
        Episode(id="ep-own-reflection-02", timestamp=2.0, user_input="I keep thinking about our games.", source="reflection"),
    ]
    weak = RecallConfidence(band="weak", best_similarity=0.513, candidate_count=2, query=GAME_QUERY)
    runtime = _runtime(
        config=_config(recall_confidence_gating_enabled=True),
        episodic_memory=_Episodic(episodes, weak),
        trust_network=SimpleNamespace(get_score=lambda _agent_id: 0.95),  # SENIOR: the ORACLE recall tier
        _oracle_service=await _records_oracle(tmp_path),
        recreation_service=_Recreation(),
    )
    agent = _agent(runtime, _OneReply("Good game, Captain."))

    observation, decision = await _turn(agent, {"text": GAME_QUERY, "captain_message": GAME_QUERY})
    result = IntentResult(
        intent_id="intent-ad1357", agent_id=AGENT_ID, success=True, result=decision["llm_output"],
        metadata=_build_result_metadata({}, decision, observation),
    )
    store = _thread_store(tmp_path)
    thread = store.get_or_create_default_for_agent(AGENT_ID, "Ezri")
    store.append_message(
        thread.id, author_id=AGENT_ID, role="agent", body="Good game, Captain.",
        metadata=_build_reply_metadata("intent-ad1357", result, {}),
    )
    (row,) = [m for m in store.list_messages(thread.id, limit=10) if m.role == "agent"]
    manifest = row.metadata["context_manifest"]

    prompt = agent._llm_client.requests[0].prompt
    assert "--- Active Game ---" in prompt and "CROSS-TIER KNOWLEDGE" in prompt  # premise: all three reached it
    names = _names(manifest)
    assert _in_order(["episodic", "recall_confidence", "oracle", "active_game", "captain_message"], names), names
    assert all(section["kept"] for section in manifest["sections"])
    assert manifest["path"] == "single_pass"
    assert (manifest["recall"]["ran"], manifest["recall"]["query"]) == (True, GAME_QUERY)
    assert manifest["recall"]["episodes"] == [
        {"id": "ep-own-direct-0001", "source": "direct"},
        {"id": "ep-own-reflection-02", "source": "reflection"},
    ]
    assert manifest["recall"]["confidence"] == {"band": "weak", "best_similarity": 0.513, "recall_type": None}
    oracle = manifest["lookups"]["oracle"]
    assert (oracle["ran"], oracle["scope"], oracle["failed"]) == (True, "all", False)
    assert GAME_RECORD in oracle["record_paths"]
    assert oracle["by_tier"]["records"] == len(oracle["record_paths"])
    assert "Captain wins" not in json.dumps(manifest)


# ── T2: recall off says so ───────────────────────────────────────────


@_UNTIL_M2
@pytest.mark.parametrize(
    ("runtime_attributes", "agent_type", "params"),
    [
        pytest.param({}, "scout", {"text": "hello", "captain_message": "hello"}, id="no-episodic-memory"),
        pytest.param({"episodic_memory": _Episodic([])}, "tester", {"text": "hello", "captain_message": "hello"}, id="not-crew"),
        pytest.param({"episodic_memory": _Episodic([])}, "scout", {"text": "   ", "captain_message": "   "}, id="empty-query"),
    ],
)
async def test_a_dm_reply_with_recall_off_says_recall_did_not_run(
    runtime_attributes: dict[str, Any], agent_type: str, params: dict[str, Any],
) -> None:
    """#1749 acceptance 2: with recall off the manifest says so rather than omitting the key."""
    agent = _agent(_runtime(**runtime_attributes), _OneReply("Hello, Captain."), agent_type=agent_type)
    observation, decision = await _turn(agent, params)
    manifest = _manifest_of(observation, decision)
    assert manifest["recall"] == {"ran": False}
    assert manifest["lookups"] == NO_LOOKUPS
    assert "captain_message" in _names(manifest)


# ── T3: privacy ──────────────────────────────────────────────────────


@_UNTIL_M3
@pytest.mark.parametrize(
    "case", ["one-to-one-scene-and-peer", "group-turn", "group-turn-with-captain-message", "empty-captain-message"],
)
async def test_the_manifest_holds_no_other_agents_text_and_no_camera_scene(case: str) -> None:
    """#1749 acceptance 3: ids and counts only. A peer's recalled text, its episode id and callsign, another
    agent's room message and the camera scene the router prepends (AD-733a) all reach the prompt; none is in
    the manifest."""
    own = [Episode(id="ep-own-0001", timestamp=1.0, user_input="A chat with the Captain.", source="direct")]
    weak = RecallConfidence(band="weak", best_similarity=0.5, candidate_count=1, query="")
    peer = SimpleNamespace(id="peer-agent-1", agent_type="scout", sovereign_id="peer-agent-1")
    peer_recall = SimpleNamespace(
        episode=Episode(id="peer-episode-SECRET-0001", user_input="PEER-PRIVATE-TEXT about the Captain"),
        peer_callsign="Lyra",
    )
    runtime = _runtime(
        config=_config(cross_agent_recall_enabled=True, recall_confidence_gating_enabled=True),
        episodic_memory=_Episodic(own, weak),
        registry=SimpleNamespace(all=lambda: [peer], get_by_pool=lambda _pool: []),
        hebbian_router=SimpleNamespace(get_weight=lambda *_args: 0.5),
        _cross_agent_recall_service=SimpleNamespace(escalate_recall=AsyncMock(return_value=[peer_recall])),
    )
    agent = _agent(runtime, _OneReply("Hello, Captain."))
    scene = "Current Visual Context: SCENE-MARKER a red chair\n\nhello Ezri"
    params = {
        "one-to-one-scene-and-peer": {"text": scene, "captain_message": "hello Ezri"},
        "group-turn": {"text": "PEER-PRIVATE-TEXT from the room", "is_group_chat": True, "trigger_speaker": "Lyra"},
        "group-turn-with-captain-message": {
            "text": "PEER-PRIVATE-TEXT from the room", "is_group_chat": True, "trigger_speaker": "Lyra",
            "captain_message": "PEER-PRIVATE-TEXT from the room",
        },
        "empty-captain-message": {"text": scene, "captain_message": ""},
    }[case]

    observation, decision = await _turn(agent, params)
    manifest = _manifest_of(observation, decision)
    prompt = agent._llm_client.requests[0].prompt
    encoded = json.dumps(manifest)

    assert "PEER-PRIVATE-TEXT" in prompt  # premise: the prompt carried another agent's text
    for secret in ("PEER-PRIVATE-TEXT", "peer-episode-SECRET-0001", "Lyra", "SCENE-MARKER"):
        assert secret not in encoded, secret
    assert manifest["recall"]["episodes"] == [{"id": "ep-own-0001", "source": "direct"}]
    if case == "one-to-one-scene-and-peer":
        assert "SCENE-MARKER" in prompt  # premise
        assert manifest["recall"]["query"] == "hello Ezri"
        assert manifest["lookups"]["cross_agent_recall"] == {"ran": True, "failed": False, "count": 1}
    else:
        assert manifest["recall"]["query"] is None
        assert manifest["recall"]["query_chars"] > 0


# ── T4: bounds and storability ───────────────────────────────────────


def _encoded_size(manifest: dict[str, Any]) -> int:
    """Bytes as ``ChatThreadStore.append_message_once`` encodes metadata."""
    return len(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    )


@_UNTIL_M2
def test_the_manifest_fits_its_bound_at_every_cap() -> None:
    """The largest manifest the caps allow, in ASCII as production names and ids are (the query at its worst
    JSON escape), fits ``MAX_MANIFEST_BYTES``; one shaped like the 2026-11-04 turn is under 4 KiB."""
    from probos.cognitive import context_manifest as cm

    ledger = cm.ContextLedger()
    big = "y" * 1_000_000
    for index in range(cm.MAX_SECTIONS + 5):
        ledger.renderer(f"s{index:02d}".ljust(100, "x"), big)
    observation: dict[str, Any] = {}
    cm.start_recall(observation, query="\x01" * 500, captain_words=True)
    cm.note_episodes(observation, [SimpleNamespace(id="e" * 100, source="s" * 100) for _ in range(cm.MAX_EPISODES + 8)])
    cm.note_confidence(observation, SimpleNamespace(band="b" * 100, best_similarity=0.123456, recall_type="r" * 100))
    cm.note_cross_agent(observation, 3)
    cm.note_transcript(observation, hit=True, thread_ids=["t" * 100] * 10)
    cm.note_oracle(
        observation, "all",
        [(f"tier{i}".ljust(100, "z"), "p" * 500) for i in range(20)] + [("records", "p" * 500)] * 20,
    )
    worst = cm.build_manifest(
        ledger, observation[cm.RECALL_KEY], path="single_pass", system_prompt="x" * 50_000,
        user_message="u", response_text="r", journal_entry_id="j" * 100,
    )
    assert "unrecorded" not in worst
    assert (len(worst["sections"]), worst["sections_omitted"]) == (cm.MAX_SECTIONS, 5)
    assert worst["recall"]["episode_count"] == cm.MAX_EPISODES + 8
    assert len(worst["recall"]["episodes"]) == cm.MAX_EPISODES
    assert len(worst["lookups"]["oracle"]["record_paths"]) == cm.MAX_RECORD_PATHS
    assert len(worst["lookups"]["oracle"]["by_tier"]) == cm.MAX_TIERS
    assert len(worst["lookups"]["transcript_grounding"]["thread_ids"]) == cm.MAX_THREADS
    assert _encoded_size(worst) <= cm.MAX_MANIFEST_BYTES

    live = cm.ContextLedger()
    for name in ("temporal", "working_memory", "dm_sensorium", "episodic", "recall_confidence", "oracle",
                 "source_attribution", "session_history", "active_game", "captain_message"):
        live.renderer(name, "x" * 1500)
    turn: dict[str, Any] = {}
    cm.start_recall(turn, query="Hello Ezri", captain_words=True)
    cm.note_episodes(turn, [SimpleNamespace(id=f"{i:032x}", source="direct") for i in range(10)])
    cm.note_confidence(turn, SimpleNamespace(band="weak", best_similarity=0.513, recall_type=""))
    cm.note_oracle(turn, "all", [("records", GAME_RECORD)])
    shaped = cm.build_manifest(
        live, turn[cm.RECALL_KEY], path="agentic", system_prompt="s" * 8000,
        user_message="u" * 900, response_text="r", journal_entry_id="f" * 32,
    )
    assert _encoded_size(shaped) <= 4096


@_UNTIL_M2
@pytest.mark.parametrize(
    "similarity", [float("nan"), float("inf"), True, "0.5", 10**400],
    ids=["nan", "infinity", "a-bool", "text", "too-large-for-a-float"],
)
def test_a_similarity_that_is_not_a_finite_number_is_recorded_as_none_and_the_row_stores(
    tmp_path: Path, similarity: Any,
) -> None:
    from probos.cognitive import context_manifest as cm

    ledger = cm.ContextLedger()
    ledger.renderer("captain_message", "Captain says: hi")
    observation: dict[str, Any] = {}
    cm.start_recall(observation, query="hi", captain_words=True)
    cm.note_confidence(observation, SimpleNamespace(band="weak", best_similarity=similarity, recall_type=""))
    manifest = cm.build_manifest(
        ledger, observation[cm.RECALL_KEY], path="single_pass", system_prompt="",
        user_message="", response_text="", journal_entry_id="row-1",
    )
    assert manifest["recall"]["confidence"]["best_similarity"] is None
    store = _thread_store(tmp_path)
    thread = store.get_or_create_default_for_agent(AGENT_ID, "Ezri")
    saved = store.append_message(
        thread.id, author_id=AGENT_ID, role="agent", body="hi", metadata={"context_manifest": manifest},
    )
    assert saved is not None and saved.metadata["context_manifest"] == manifest


@_UNTIL_M2
@pytest.mark.parametrize(
    ("value", "reason"),
    [
        pytest.param(float("nan"), "unencodable", id="nan"),
        pytest.param("\ud800", "unencodable", id="lone-surrogate"),
        pytest.param("y" * 16_385, "oversize", id="oversize"),
    ],
)
def test_a_manifest_the_store_would_refuse_is_replaced_by_a_stub_that_says_so(
    tmp_path: Path, value: Any, reason: str,
) -> None:
    from probos.cognitive import context_manifest as cm

    stub = cm.storable({"x": value}, path="single_pass")
    assert stub == {"v": cm.MANIFEST_VERSION, "path": "single_pass", "unrecorded": reason}
    store = _thread_store(tmp_path)
    thread = store.get_or_create_default_for_agent(AGENT_ID, "Ezri")
    assert store.append_message(
        thread.id, author_id=AGENT_ID, role="agent", body="hi", metadata={"context_manifest": stub},
    ) is not None


# ── T5, T6: the journal row ──────────────────────────────────────────


@_UNTIL_M2
async def test_the_manifest_names_its_journal_row_on_the_single_pass_path(tmp_path: Path) -> None:
    """The single-pass row (``entry_id=request.id``) and the manifest carry the same id and hashes."""
    journal = CognitiveJournal(db_path=str(tmp_path / "cognitive_journal.db"))
    await journal.start()
    try:
        agent = _agent(_runtime(cognitive_journal=journal), _OneReply("R" * 700))
        words = "Tell me about the drill. " * 30  # over 600 characters, so the journal's 500-character cut matters
        observation, decision = await _turn(agent, {"text": words, "captain_message": words})
        manifest = _manifest_of(observation, decision)
        (row,) = await journal.get_reasoning_chain(agent.id, limit=10)
    finally:
        await journal.stop()
    assert len(agent._llm_client.requests[0].prompt) > 600  # premise
    assert manifest["path"] == "single_pass"
    assert row["intent"] == "direct_message"
    assert (row["id"], row["prompt_hash"], row["response_hash"]) == (
        manifest["journal_entry_id"], manifest["prompt_hash"], manifest["response_hash"],
    )


@_UNTIL_M4
async def test_an_agentic_dm_turn_writes_one_journal_row_that_the_manifest_names(tmp_path: Path) -> None:
    """#1749 acceptance 4: the journal has a row for the DM turn, beside the chain intents."""
    journal = CognitiveJournal(db_path=str(tmp_path / "cognitive_journal.db"))
    await journal.start()
    try:
        agent = _agent(_runtime(cognitive_journal=journal), _OneReply("unused"))
        agent._maybe_run_conversational_agentic = AsyncMock(return_value="Done, Captain.")  # type: ignore[method-assign]
        observation, decision = await _turn(agent, {"text": "Make me a doc.", "captain_message": "Make me a doc."})
        manifest = _manifest_of(observation, decision)
        rows = await journal.get_reasoning_chain(agent.id, limit=10)
    finally:
        await journal.stop()
    assert decision["tier_used"] == "agentic" and agent._llm_client.requests == []  # premise: the loop answered
    (row,) = rows
    assert manifest["path"] == "agentic"
    keys = ("id", "intent", "tier", "model", "dag_node_id", "cached", "token_source", "success",
            "response_length", "intent_id", "prompt_hash", "response_hash")
    assert {key: row[key] for key in keys} == {
        "id": manifest["journal_entry_id"], "intent": "direct_message", "tier": "agentic", "model": "unknown",
        "dag_node_id": "dm-turn", "cached": 0, "token_source": "", "success": 1,
        "response_length": len("Done, Captain."), "intent_id": observation["intent_id"],
        "prompt_hash": manifest["prompt_hash"], "response_hash": manifest["response_hash"],
    }


# ── T7 to T9: the sinks and the wire ─────────────────────────────────


@_UNTIL_M2
def test_the_reply_metadata_carries_the_manifest_the_agent_made() -> None:
    manifest = {"v": 1, "path": "single_pass", "sections": []}
    result = IntentResult(
        intent_id="i1", agent_id="a1", success=True,
        metadata={"tool_trace_ref": "a" * 64, "context_manifest": manifest},
    )
    assert _build_reply_metadata("intent-1", result, {"emotion": "warm"}) == {
        "intent_id": "intent-1", "tool_trace_ref": "a" * 64, "emotion": "warm", "context_manifest": manifest,
    }


@pytest.mark.parametrize(
    "result",
    [
        IntentResult(intent_id="i1", agent_id="a1", success=True),
        IntentResult(intent_id="i1", agent_id="a1", success=True, metadata={"context_manifest": "not a dict"}),
        IntentResult(intent_id="i1", agent_id="a1", success=True, metadata={"context_manifest": {}}),
        None,
    ],
    ids=["no-metadata", "manifest-not-a-dict", "empty-manifest", "no-result"],
)
def test_a_reply_without_a_manifest_keeps_its_metadata_unchanged(result: Any) -> None:
    assert _build_reply_metadata("intent-1", result, None) == {"intent_id": "intent-1"}


@_UNTIL_M2
async def test_a_group_reply_is_stored_with_its_manifest_and_one_without_stays_unchanged(tmp_path: Path) -> None:
    """The real AD-914 fan-out over a real ``IntentBus`` and store (test_ad914's harness, restated)."""
    store = _thread_store(tmp_path)
    bus = IntentBus(SignalManager(reap_interval=1.0))
    types = {"scout1": "scout", "counselor1": "counselor"}
    runtime = SimpleNamespace(
        chat_thread_store=store, intent_bus=bus, ontology=None, project_store=None,
        registry=SimpleNamespace(get=lambda aid: SimpleNamespace(agent_type=types[aid]) if aid in types else None),
        callsign_registry=SimpleNamespace(get_callsign=lambda t: {"scout": "Wesley", "counselor": "Ezri"}.get(t, "")),
    )
    manifest = {"v": 1, "path": "single_pass", "sections": [{"name": "captain_message", "chars": 10, "kept": True}]}

    def _handler(agent_id: str, metadata: dict[str, Any]):
        async def _handle(intent: IntentMessage) -> IntentResult:
            return IntentResult(
                intent_id=intent.id, agent_id=agent_id, success=True,
                result=f"reply::{agent_id}", metadata=metadata,
            )
        return _handle

    bus.subscribe("scout1", _handler("scout1", {"context_manifest": manifest}), intent_names=["direct_message"])
    bus.subscribe("counselor1", _handler("counselor1", {}), intent_names=["direct_message"])
    thread = store.create_thread(title="room", participants=["scout1", "counselor1"])
    captain = store.append_message(thread.id, author_id="captain", role="captain", body="status?")
    await group_chat_fanout(runtime, thread.id, captain_body="status?", captain_msg=captain)
    rows = {m.author_id: m.metadata for m in store.list_messages(thread.id, limit=100) if m.role == "agent"}
    assert rows["scout1"]["context_manifest"] == manifest
    assert "context_manifest" not in rows["counselor1"]
    assert rows["counselor1"]["fanout"] == "ad914"


@_UNTIL_M2
def test_the_manifest_is_the_last_reply_metadata_key_so_bf805_drops_it_first() -> None:
    from probos.cognitive import context_manifest as cm

    metadata = _build_result_metadata({}, {}, {"_tool_trace_ref": "a" * 64, cm.MANIFEST_KEY: {"v": 1}})
    assert list(metadata) == ["tool_trace_ref", "context_manifest"]
    # 100 bytes of room fit the trace ref's 84 and not the manifest's 30 more (by hand: IntentBus._prune_metadata)
    kept, dropped = IntentBus._prune_metadata(metadata, 0, 100)
    assert (list(kept), dropped) == (["tool_trace_ref"], ["context_manifest"])


# ── T10, T11: the ledger ─────────────────────────────────────────────


@_UNTIL_M2
def test_a_section_is_recorded_by_its_name_alone_and_kept_only_when_assembly_renders_it() -> None:
    from probos.cognitive import context_manifest as cm

    observation: dict[str, Any] = {cm.MANIFEST_KEY: {"v": 1, "path": "stale"}}
    ledger = cm.start_ledger(observation)
    assert observation[cm.LEDGER_KEY] is ledger and cm.MANIFEST_KEY not in observation
    assert cm.ledger_of(observation) is ledger
    text = "the head-to-head tally: Captain 2, Ezri 0"
    render = ledger.renderer("head_to_head_tally", text)  # a name no manifest code knows
    ledger.renderer("dropped_section", "never rendered")
    ledger.note_appended("nothing_appended", 0)
    ledger.note_appended("strategy_advice", 7)
    assert ledger.to_wire() == ([
        {"name": "head_to_head_tally", "chars": len(text), "kept": False},
        {"name": "dropped_section", "chars": 14, "kept": False},
        {"name": "strategy_advice", "chars": 7, "kept": True},
    ], 0)
    assert render() is text
    sections, _ = ledger.to_wire()
    assert (sections[0]["kept"], sections[1]["kept"]) == (True, False)


@_UNTIL_M2
async def test_a_section_the_attention_budget_drops_is_recorded_as_not_kept() -> None:
    from probos.cognitive import context_manifest as cm

    agent = make_dm_agent()
    observation = dm_observation()
    captain = "Captain says: " + observation["params"]["text"]
    agent._runtime = SimpleNamespace(config=SimpleNamespace(memory=SimpleNamespace(
        attention=SimpleNamespace(enabled=True, token_budget=estimate_tokens(captain)),
    )))
    prompt = await agent._build_user_message(observation)
    sections, _ = observation[cm.LEDGER_KEY].to_wire()
    kept = {section["name"]: section["kept"] for section in sections}
    assert prompt == captain
    assert [name for name, was_kept in kept.items() if was_kept] == ["captain_message"]
    assert {"temporal", "episodic", "oracle", "session_history"} <= set(kept)


# ── T13 to T18: the lookups ──────────────────────────────────────────


@_UNTIL_M3
async def test_the_oracle_reports_what_it_rendered_and_renders_the_same_text(tmp_path: Path) -> None:
    oracle = await _records_oracle(tmp_path)
    sources: list[tuple[str, str]] = []
    with_sink = await oracle.query_formatted(GAME_QUERY, agent_id=AGENT_ID, k_per_tier=3, max_chars=2000, sources_out=sources)
    without = await oracle.query_formatted(GAME_QUERY, agent_id=AGENT_ID, k_per_tier=3, max_chars=2000)
    assert with_sink == without
    assert ("records", GAME_RECORD) in sources
    for _tier, path in sources:
        assert path in with_sink


@_UNTIL_M3
@pytest.mark.parametrize("case", ["a-room-matches", "only-a-title-matches"])
def test_transcript_grounding_reports_the_room_its_excerpt_came_from(tmp_path: Path, case: str) -> None:
    from probos.cognitive.transcript_grounding import consult_transcript

    store = _thread_store(tmp_path)
    if case == "a-room-matches":
        thread = store.create_thread(title="sidebar", participants=[AGENT_ID, "captain"])
        store.append_message(thread.id, author_id="captain", role="captain", body="the condensed sidebar voice stream")
        query = "condensed sidebar voice"
    else:
        thread = store.create_thread(title="kingfisher anomaly", participants=[AGENT_ID, "captain"])
        store.append_message(thread.id, author_id="captain", role="captain", body="hello there")
        query = "kingfisher"
    rooms: list[str] = []
    excerpt = consult_transcript(store, {AGENT_ID}, query, sources_out=rooms)
    assert excerpt == consult_transcript(store, {AGENT_ID}, query)
    if case == "a-room-matches":
        assert excerpt is not None and rooms == [thread.id]
    else:
        assert excerpt is None and rooms == []


@_UNTIL_M2
def test_only_ship_records_results_are_identified_and_every_tier_is_counted() -> None:
    from probos.cognitive import context_manifest as cm

    observation: dict[str, Any] = {}
    cm.start_recall(observation, query="q", captain_words=True)
    cm.note_oracle(observation, "all", [
        ("records", "notebooks/Lyra/drill.md"), ("episodic", "peer-episode-9"),
        ("archive", "archive/peer.md"), ("records", ""),
    ])
    _, lookups = observation[cm.RECALL_KEY].to_wire()
    assert lookups["oracle"] == {
        "ran": True, "scope": "all", "failed": False, "results": 4,
        "by_tier": {"records": 2, "episodic": 1, "archive": 1}, "record_paths": ["notebooks/Lyra/drill.md"],
    }
    cm.note_oracle(observation, "graph", None)
    _, lookups = observation[cm.RECALL_KEY].to_wire()
    assert lookups["oracle"] == {
        "ran": True, "scope": "graph", "failed": True, "results": 0, "by_tier": {}, "record_paths": [],
    }


@_UNTIL_M2
@pytest.mark.parametrize("case", ["strategy-advice", "owned-steps-view", "room-inputs"])
async def test_text_appended_after_assembly_is_recorded_by_name_and_length(case: str) -> None:
    agent = _agent(_runtime(), _OneReply("Aye."))
    params: dict[str, Any] = {"text": "status?", "captain_message": "status?"}
    if case == "strategy-advice":
        agent._strategy_advisor = SimpleNamespace(
            query_strategies=lambda _intent, _type: [{"id": "s-1"}],
            format_for_context=lambda _strategies: "STRATEGY: answer briefly.",
        )
        name, chars = "strategy_advice", len("\n\n" + "STRATEGY: answer briefly.")
    elif case == "owned-steps-view":
        owner = SimpleNamespace(admit_owned_steps_presentation=AsyncMock())
        agent._resolve_owned_steps_model_context = AsyncMock(  # type: ignore[method-assign]
            return_value=("RAW-VIEW", owner, object(), object()),
        )
        name, chars = "owned_steps_view", len("\n\n<owned_steps_view>\nRAW-VIEW\n</owned_steps_view>")
    else:
        params = {"text": "status?", "is_group_chat": True, "room_input_hashes": ["deadbeef"]}
        name, chars = "room_inputs", len("\nRoom inputs unavailable; do not claim complete analysis.")
    observation, decision = await _turn(agent, params)
    manifest = _manifest_of(observation, decision)
    assert manifest["sections"][-1] == {"name": name, "chars": chars, "kept": True}


@_UNTIL_M3
async def test_recall_records_the_room_transcript_grounding_drew_on(tmp_path: Path) -> None:
    from probos.cognitive import context_manifest as cm

    store = _thread_store(tmp_path)
    thread = store.create_thread(title="sidebar", participants=[AGENT_ID, "captain"])
    store.append_message(thread.id, author_id="captain", role="captain", body="the condensed sidebar voice stream")
    runtime = _runtime(
        config=_config(transcript_grounded_recall_enabled=True),
        episodic_memory=_Episodic([]), chat_thread_store=store,
    )
    agent = _agent(runtime, _OneReply("unused"))
    params = {"text": "condensed sidebar voice", "captain_message": "condensed sidebar voice"}
    intent = IntentMessage(intent="direct_message", params=params)
    observation = await agent._recall_relevant_memories(intent, _observation(params, intent_id=intent.id))
    _, lookups = observation[cm.RECALL_KEY].to_wire()
    assert observation.get("_transcript_grounding")  # premise: grounding fed the prompt
    assert lookups["transcript_grounding"] == {"ran": True, "hit": True, "thread_ids": [thread.id]}


@_UNTIL_M3
async def test_a_graph_only_lookup_is_recorded_with_its_scope(tmp_path: Path) -> None:
    """No trust network: the agent's rank is None, so its tier is ENHANCED and BF-265's graph-only query runs."""
    from probos.cognitive import context_manifest as cm

    runtime = _runtime(
        episodic_memory=_Episodic([Episode(id="ep-1", timestamp=1.0, user_input="a chat", source="direct")]),
        _oracle_service=await _records_oracle(tmp_path),
    )
    agent = _agent(runtime, _OneReply("unused"))
    params = {"text": GAME_QUERY, "captain_message": GAME_QUERY}
    intent = IntentMessage(intent="direct_message", params=params)
    observation = await agent._recall_relevant_memories(intent, _observation(params, intent_id=intent.id))
    _, lookups = observation[cm.RECALL_KEY].to_wire()
    assert lookups["oracle"] == {
        "ran": True, "scope": "graph", "failed": False, "results": 0, "by_tier": {}, "record_paths": [],
    }
```

### 7.2 M2

**N2-1** `src/probos/cognitive/context_manifest.py` (new)

```python
"""AD-1357 (#1749): what a crew chat reply was given, kept beside the reply.

``CognitiveAgent`` builds a ``direct_message`` prompt from named context sections
(the ``_emit`` bids of ``_build_user_message``) and from what recall and the
passive lookups put on the observation. This module records those facts as a
small, bounded, JSON-safe context manifest, stored under the reply's
``metadata["context_manifest"]``:

* every section bid, in emission order, with its character count and whether
  the attention budget kept it, then the text appended after assembly;
* whether episodic recall ran; its query, only when that query is the Captain's
  own words on a 1:1 turn; the agent's own recalled episode ids with their
  source tags; and the AD-981a band, best similarity and AD-1038 recall type;
* whether cross-agent recall (AD-979d), transcript grounding (AD-986b) and the
  passive Oracle lookup ran, and what they returned: a count for cross-agent
  recall, the room id for transcript grounding, and for the Oracle a count per
  tier plus the paths of its Ship's Records results;
* the cognitive journal's prompt and response hashes, and the id of the
  journal row for the same turn.

It holds no section text, no other agent's message text, no peer agent's
episode id and no camera scene. A section is recorded by its name alone, so a
new ``_emit`` source is recorded with no change here.

Stdlib only, because the chat routers import it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Final

logger = logging.getLogger(__name__)

#: The reply metadata key, on ``IntentResult.metadata`` and on the stored message.
CONTEXT_MANIFEST_METADATA_KEY: Final = "context_manifest"
#: Observation keys: this prompt's ledger, this turn's recall record, the finished manifest.
LEDGER_KEY: Final = "_context_ledger"
RECALL_KEY: Final = "_context_recall"
MANIFEST_KEY: Final = "_context_manifest"
#: The ``dag_node_id`` of the journal row an agentic DM turn writes.
DM_TURN_DAG_NODE: Final = "dm-turn"
MANIFEST_VERSION: Final = 1

MAX_SECTIONS: Final = 48
MAX_NAME_CHARS: Final = 64
MAX_EPISODES: Final = 32
MAX_ID_CHARS: Final = 64
MAX_SOURCE_CHARS: Final = 32
MAX_THREADS: Final = 4
MAX_TIERS: Final = 8
MAX_RECORD_PATHS: Final = 12
MAX_PATH_CHARS: Final = 200
MAX_QUERY_CHARS: Final = 200
MAX_MANIFEST_BYTES: Final = 16384

#: The one Oracle tier whose results are identified, by path. Ship's Records are
#: the shared record; another tier's ids can name another agent's episodes, so
#: those results are counted and never identified.
_IDENTIFIED_TIER: Final = "records"
_LOOKUPS: Final = ("cross_agent_recall", "transcript_grounding", "oracle")


def turn_hash(text: Any) -> str:
    """The cognitive journal's hash of a prompt or a reply: the first 12 hex digits of
    the MD5 of its first 500 characters, as ``_decide_via_llm`` computes it (AD-431).

    A value that is not a ``str`` hashes as ``""``, and a lone surrogate is encoded
    rather than raising, so the hash never stops a turn.
    """
    value = text if isinstance(text, str) else ""
    return hashlib.md5(value[:500].encode("utf-8", "surrogatepass")).hexdigest()[:12]


def _text(value: Any, limit: int) -> str:
    """``value`` cut to ``limit`` characters when it is a ``str``; otherwise ``""``."""
    return value[:limit] if isinstance(value, str) else ""


def _finite(value: Any) -> float | None:
    """A finite number rounded to four places; a bool, NaN, an infinity, text or an
    int too large for a float is ``None``."""
    if type(value) is bool or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return round(number, 4) if math.isfinite(number) else None


@dataclass(slots=True)
class _Section:
    name: str
    chars: int
    kept: bool


class ContextLedger:
    """The sections of one ``direct_message`` prompt, in the order they were bid.

    ``renderer`` is called once per ``_emit`` bid, before assembly. It returns the
    bid's lazy renderer, which returns ``text`` itself and marks the section kept.
    ``ContextAssembler.assemble`` calls only the renderers of the bids it keeps, so
    a section whose renderer never ran was dropped by the token budget.
    ``note_appended`` records text appended to the user message after assembly.
    """

    __slots__ = ("_sections",)

    def __init__(self) -> None:
        self._sections: list[_Section] = []

    def renderer(self, name: str, text: str) -> Callable[[], str]:
        section = _Section(name=name, chars=len(text), kept=False)
        self._sections.append(section)

        def _render() -> str:
            section.kept = True
            return text

        return _render

    def note_appended(self, name: str, chars: int) -> None:
        if chars > 0:
            self._sections.append(_Section(name=name, chars=chars, kept=True))

    def to_wire(self) -> tuple[list[dict[str, Any]], int]:
        """The first ``MAX_SECTIONS`` sections and how many were left out."""
        shown = [
            {"name": _text(section.name, MAX_NAME_CHARS), "chars": section.chars, "kept": section.kept}
            for section in self._sections[:MAX_SECTIONS]
        ]
        return shown, max(0, len(self._sections) - MAX_SECTIONS)


@dataclass(slots=True)
class RecallRecord:
    """What ``_recall_relevant_memories`` did for one ``direct_message`` turn."""

    query: str | None
    query_chars: int
    failed: bool = False
    episodes: list[dict[str, str]] = field(default_factory=list)
    episode_count: int = 0
    confidence: dict[str, Any] | None = None
    cross_agent: dict[str, Any] | None = None
    transcript: dict[str, Any] | None = None
    oracle: dict[str, Any] | None = None

    def to_wire(self) -> tuple[dict[str, Any], dict[str, Any]]:
        recall = {
            "ran": True,
            "query": self.query,
            "query_chars": self.query_chars,
            "failed": self.failed,
            "episodes": list(self.episodes),
            "episode_count": self.episode_count,
            "confidence": self.confidence,
        }
        lookups = {
            "cross_agent_recall": self.cross_agent or {"ran": False},
            "transcript_grounding": self.transcript or {"ran": False},
            "oracle": self.oracle or {"ran": False},
        }
        return recall, lookups


def start_ledger(observation: Any) -> ContextLedger:
    """A new ledger for this prompt, kept on the observation; an earlier manifest on it is dropped."""
    ledger = ContextLedger()
    if isinstance(observation, dict):
        observation[LEDGER_KEY] = ledger
        observation.pop(MANIFEST_KEY, None)
    return ledger


def ledger_of(observation: Any) -> ContextLedger | None:
    ledger = observation.get(LEDGER_KEY) if isinstance(observation, dict) else None
    return ledger if isinstance(ledger, ContextLedger) else None


def _record(observation: Any) -> RecallRecord | None:
    record = observation.get(RECALL_KEY) if isinstance(observation, dict) else None
    return record if isinstance(record, RecallRecord) else None


def start_recall(observation: Any, *, query: str, captain_words: bool) -> None:
    """Recall ran for this turn. The query text is kept only when ``captain_words``."""
    if isinstance(observation, dict):
        observation[RECALL_KEY] = RecallRecord(
            query=_text(query, MAX_QUERY_CHARS) if captain_words else None,
            query_chars=len(query) if isinstance(query, str) else 0,
        )


def note_episodes(observation: Any, episodes: Iterable[Any]) -> None:
    """The agent's own recalled episodes that reached the memory section: ids and source tags."""
    record = _record(observation)
    if record is None:
        return
    listed = list(episodes)
    record.episode_count = len(listed)
    record.episodes = [
        {
            "id": _text(getattr(ep, "id", ""), MAX_ID_CHARS),
            "source": _text(getattr(ep, "source", "direct"), MAX_SOURCE_CHARS),
        }
        for ep in listed[:MAX_EPISODES]
    ]


def note_recall_failed(observation: Any) -> None:
    record = _record(observation)
    if record is not None:
        record.failed = True


def note_confidence(observation: Any, confidence: Any) -> None:
    """The AD-981a band and best similarity and the AD-1038 recall type the probe returned."""
    record = _record(observation)
    if record is None or confidence is None:
        return
    record.confidence = {
        "band": _text(getattr(confidence, "band", ""), MAX_SOURCE_CHARS) or None,
        "best_similarity": _finite(getattr(confidence, "best_similarity", None)),
        "recall_type": _text(getattr(confidence, "recall_type", ""), MAX_SOURCE_CHARS) or None,
    }


def note_cross_agent(observation: Any, count: int | None) -> None:
    """AD-979d was consulted; ``count`` peer memories came back, or ``None`` when it raised.

    Never a peer's episode id, callsign or text.
    """
    record = _record(observation)
    if record is not None:
        record.cross_agent = {"ran": True, "failed": count is None, "count": count or 0}


def note_transcript(observation: Any, *, hit: bool, thread_ids: Iterable[str]) -> None:
    """AD-986b ran; whether an excerpt came back, and the id of the room it came from."""
    record = _record(observation)
    if record is not None:
        record.transcript = {
            "ran": True,
            "hit": bool(hit),
            "thread_ids": [_text(thread_id, MAX_ID_CHARS) for thread_id in list(thread_ids)[:MAX_THREADS]],
        }


def note_oracle(observation: Any, scope: str, sources: Iterable[tuple[str, str]] | None) -> None:
    """The passive Oracle lookup ran with ``scope`` ("all", or "graph" for BF-265's query).

    ``sources`` holds the ``(tier, path)`` of each rendered result, from
    ``OracleService.query_formatted(sources_out=...)``, or is ``None`` when the
    query raised. Results are counted per tier; only Ship's Records results are
    identified, by path.
    """
    record = _record(observation)
    if record is None:
        return
    if sources is None:
        record.oracle = {
            "ran": True, "scope": scope, "failed": True, "results": 0, "by_tier": {}, "record_paths": [],
        }
        return
    listed = list(sources)
    by_tier: dict[str, int] = {}
    paths: list[str] = []
    for tier, path in listed:
        name = _text(tier, MAX_SOURCE_CHARS)
        if name in by_tier or len(by_tier) < MAX_TIERS:
            by_tier[name] = by_tier.get(name, 0) + 1
        if name == _IDENTIFIED_TIER and path and len(paths) < MAX_RECORD_PATHS:
            paths.append(_text(path, MAX_PATH_CHARS))
    record.oracle = {
        "ran": True, "scope": scope, "failed": False, "results": len(listed),
        "by_tier": by_tier, "record_paths": paths,
    }


def storable(manifest: dict[str, Any], *, path: str) -> dict[str, Any]:
    """``manifest`` when it encodes as the chat store encodes metadata and fits
    ``MAX_MANIFEST_BYTES``; otherwise a stub that says why it was not recorded.

    ``ChatThreadStore.append_message_once`` refuses metadata that ``json.dumps``
    rejects with ``allow_nan=False``, and the 1:1 route's append catches that
    refusal, so an unstorable manifest would cost the Captain the reply in the
    transcript.
    """
    try:
        encoded = json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        return {"v": MANIFEST_VERSION, "path": path, "unrecorded": "unencodable"}
    if len(encoded) > MAX_MANIFEST_BYTES:
        return {"v": MANIFEST_VERSION, "path": path, "unrecorded": "oversize"}
    return manifest


def build_manifest(
    ledger: ContextLedger,
    recall: RecallRecord | None,
    *,
    path: str,
    system_prompt: Any,
    user_message: Any,
    response_text: Any,
    journal_entry_id: str,
) -> dict[str, Any]:
    """The manifest for one reply; ``recall`` is ``None`` when recall did not run."""
    sections, omitted = ledger.to_wire()
    if recall is None:
        recall_wire: dict[str, Any] = {"ran": False}
        lookups: dict[str, Any] = {name: {"ran": False} for name in _LOOKUPS}
    else:
        recall_wire, lookups = recall.to_wire()
    manifest = {
        "v": MANIFEST_VERSION,
        "path": path,
        "sections": sections,
        "sections_omitted": omitted,
        "system_prompt_chars": len(system_prompt) if isinstance(system_prompt, str) else 0,
        "recall": recall_wire,
        "lookups": lookups,
        "prompt_hash": turn_hash(user_message),
        "response_hash": turn_hash(response_text),
        "journal_entry_id": _text(journal_entry_id, MAX_ID_CHARS),
    }
    return storable(manifest, path=path)


def record_manifest(
    observation: Any,
    *,
    path: str,
    system_prompt: Any,
    user_message: Any,
    response_text: Any,
    journal_entry_id: str,
) -> None:
    """Put this turn's manifest on the observation when ``_build_user_message``
    assembled a ``direct_message`` prompt on it.

    An ``Exception`` while building is logged and no manifest is recorded; a
    ``BaseException``, or a failure of the logging itself, propagates.
    """
    ledger = ledger_of(observation)
    if ledger is None:
        return
    try:
        observation[MANIFEST_KEY] = build_manifest(
            ledger,
            _record(observation),
            path=path,
            system_prompt=system_prompt,
            user_message=user_message,
            response_text=response_text,
            journal_entry_id=journal_entry_id,
        )
    except Exception:
        logger.warning(
            "AD-1357: the context manifest for this reply could not be built; "
            "the reply goes out without one",
            exc_info=True,
        )


def context_manifest_metadata(result: Any) -> dict[str, Any]:
    """``{"context_manifest": ...}`` for a stored reply, from ``IntentResult.metadata``.

    ``{}`` when the result carries no non-empty dict under the key, so such a
    reply's metadata is unchanged. An ``Exception`` reading the result gives ``{}``.
    """
    try:
        metadata = getattr(result, "metadata", None)
        manifest = metadata.get(CONTEXT_MANIFEST_METADATA_KEY) if isinstance(metadata, dict) else None
    except Exception:
        return {}
    if type(manifest) is dict and manifest:
        return {CONTEXT_MANIFEST_METADATA_KEY: manifest}
    return {}
```

**P2-1** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
from probos.cognitive.attention import AttentionBid, ContextAssembler, estimate_tokens
from probos.cognitive.tiered_knowledge import TieredKnowledgeLoader
```
REPLACE:
```
from probos.cognitive.attention import AttentionBid, ContextAssembler, estimate_tokens
from probos.cognitive import context_manifest  # AD-1357
from probos.cognitive.tiered_knowledge import TieredKnowledgeLoader
```

**P2-2** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
    Empty on every non-agentic path, so an unchanged turn carries an unchanged
    (empty) metadata dict.
    """
    sources = [s for s in (report, decision, observation) if isinstance(s, dict)]
```
REPLACE:
```
    Empty on every non-agentic path except a ``direct_message`` turn whose
    prompt ``_build_user_message`` assembled, which carries its AD-1357 context
    manifest; any other such turn carries an unchanged (empty) metadata dict.
    """
    sources = [s for s in (report, decision, observation) if isinstance(s, dict)]
```

**P2-3** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
    for source in sources:
        references = source.get("_owned_steps_view_references")
        if type(references) is list and references:
            metadata["owned_steps_view_references"] = references[:8]
            break
    return metadata
```
REPLACE:
```
    for source in sources:
        references = source.get("_owned_steps_view_references")
        if type(references) is list and references:
            metadata["owned_steps_view_references"] = references[:8]
            break
    # AD-1357 (#1749): the reply's context manifest, LAST, so that BF-805's greedy
    # prune (``IntentBus._prune_metadata``, in iteration order) drops it before any
    # key above when the reply would not fit the wire.
    for source in sources:
        manifest = source.get(context_manifest.MANIFEST_KEY)
        if type(manifest) is dict and manifest:
            metadata[context_manifest.CONTEXT_MANIFEST_METADATA_KEY] = manifest
            break
    return metadata
```

**P2-4** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
        user_message = await self._build_user_message(observation)

        # Strategy advice (AD-384)
        applied_strategy_ids: list[str] = []
        if self._strategy_advisor:
            intent_type = observation.get("intent", "")
            if intent_type:
                strategies = self._strategy_advisor.query_strategies(
                    intent_type, self.agent_type
                )
                context = self._strategy_advisor.format_for_context(strategies)
                if context:
                    user_message = user_message + "\n\n" + context
                applied_strategy_ids = [
                    s["id"] for s in strategies if s.get("id")
                ]

        owned_presentation = await self._resolve_owned_steps_model_context(
            observation
        )
        if owned_presentation is not None:
            owned_raw, _, _, _ = owned_presentation
            user_message = (
                f"{user_message}\n\n<owned_steps_view>\n"
                f"{owned_raw}\n</owned_steps_view>"
            )
```
REPLACE:
```
        user_message = await self._build_user_message(observation)
        # AD-1357 (#1749): the ledger ``_build_user_message`` left for a
        # direct_message prompt, or None. Text appended below is recorded by its
        # name and length, never its content.
        _ledger = context_manifest.ledger_of(observation)

        # Strategy advice (AD-384)
        applied_strategy_ids: list[str] = []
        if self._strategy_advisor:
            intent_type = observation.get("intent", "")
            if intent_type:
                strategies = self._strategy_advisor.query_strategies(
                    intent_type, self.agent_type
                )
                context = self._strategy_advisor.format_for_context(strategies)
                if context:
                    user_message = user_message + "\n\n" + context
                    if _ledger is not None:
                        _ledger.note_appended("strategy_advice", len(context) + 2)
                applied_strategy_ids = [
                    s["id"] for s in strategies if s.get("id")
                ]

        owned_presentation = await self._resolve_owned_steps_model_context(
            observation
        )
        if owned_presentation is not None:
            owned_raw, _, _, _ = owned_presentation
            _before_owned = len(user_message)
            user_message = (
                f"{user_message}\n\n<owned_steps_view>\n"
                f"{owned_raw}\n</owned_steps_view>"
            )
            if _ledger is not None:
                _ledger.note_appended("owned_steps_view", len(user_message) - _before_owned)
```

**P2-5** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
        _agentic_output = await self._maybe_run_conversational_agentic(
            observation,
            system_prompt=composed,
            user_message=user_message,
            owned_steps_presentation=owned_presentation,
        )
        if _agentic_output is not None:
            decision = {
                "action": "execute",
                "llm_output": _agentic_output,
                "tier_used": "agentic",
            }
            # AD-1203 + AD-1248: provenance for the turn, set by the run above.
            _attach_run_provenance(decision, observation)
            if applied_strategy_ids:
                decision["_applied_strategy_ids"] = applied_strategy_ids
            return decision
```
REPLACE:
```
        _agentic_output = await self._maybe_run_conversational_agentic(
            observation,
            system_prompt=composed,
            user_message=user_message,
            owned_steps_presentation=owned_presentation,
        )
        if _agentic_output is not None:
            decision = {
                "action": "execute",
                "llm_output": _agentic_output,
                "tier_used": "agentic",
            }
            # AD-1203 + AD-1248: provenance for the turn, set by the run above.
            _attach_run_provenance(decision, observation)
            # AD-1357 (#1749): the id the reply's context manifest gives this turn.
            _turn_entry_id = uuid.uuid4().hex
            context_manifest.record_manifest(
                observation,
                path="agentic",
                system_prompt=composed,
                user_message=user_message,
                response_text=_agentic_output,
                journal_entry_id=_turn_entry_id,
            )
            if applied_strategy_ids:
                decision["_applied_strategy_ids"] = applied_strategy_ids
            return decision
```

**P2-6** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
        room_input_context = None
        room_params = observation.get("params", {})
        if (
            observation.get("intent") == "direct_message"
```
REPLACE:
```
        room_input_context = None
        room_params = observation.get("params", {})
        _before_room_inputs = len(user_message)  # AD-1357
        if (
            observation.get("intent") == "direct_message"
```

**P2-7** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
            if room_params.get("room_inputs_omitted"):
                user_message += "\nSome room inputs were omitted; do not claim complete analysis."

        # AD-730 (Wave 151): vision pipe-through for DM perception.
```
REPLACE:
```
            if room_params.get("room_inputs_omitted"):
                user_message += "\nSome room inputs were omitted; do not claim complete analysis."
        if _ledger is not None:  # AD-1357: room inputs are named and counted, never stored
            _ledger.note_appended("room_inputs", len(user_message) - _before_room_inputs)

        # AD-730 (Wave 151): vision pipe-through for DM perception.
```

**P2-8** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
            except Exception:
                logger.debug("Journal recording failed", exc_info=True)  # Non-critical — never block agent cognition

        # BF-922 (#1639): a single call that answers for a chain that returned no
```
REPLACE:
```
            except Exception:
                logger.debug("Journal recording failed", exc_info=True)  # Non-critical — never block agent cognition

        # AD-1357 (#1749): what this reply was given, naming the journal row above
        # by ``request.id`` and its two hashes.
        context_manifest.record_manifest(
            observation,
            path="single_pass",
            system_prompt=composed,
            user_message=user_message,
            response_text=response.content,
            journal_entry_id=request.id,
        )

        # BF-922 (#1639): a single call that answers for a chain that returned no
```

**P2-9** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
            # AD-1203: so the caller recording this turn can bind the claim to
            # the calls behind it. Empty on every non-agentic path.
```
REPLACE:
```
            # AD-1203: so the caller recording this turn can bind the claim to
            # the calls behind it. Empty on every non-agentic path but a
            # direct_message, which carries its AD-1357 context manifest.
```

**P2-10** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
            _bids: list[AttentionBid] = []

            def _emit(
                source: str,
                segments: list[str],
                *,
                salience: float | None = None,
                zone_floor: int | None = None,
            ) -> None:
                idx = len(_bids)
                text = "\n".join(segments)
                _bids.append(AttentionBid(
                    source=source,
                    render=(lambda _t=text: _t),
```
REPLACE:
```
            _bids: list[AttentionBid] = []
            # AD-1357 (#1749): each bid's renderer is the ledger's. It returns the
            # same text and records that assembly kept the section, by name and
            # length only, so the prompt is unchanged (the AD-1028 golden holds it).
            _ledger = context_manifest.start_ledger(observation)

            def _emit(
                source: str,
                segments: list[str],
                *,
                salience: float | None = None,
                zone_floor: int | None = None,
            ) -> None:
                idx = len(_bids)
                text = "\n".join(segments)
                _bids.append(AttentionBid(
                    source=source,
                    render=_ledger.renderer(source, text),
```

**P2-11** `src/probos/routers/agents.py`

SEARCH:
```
from probos.agent_stop import SEAM_DM_ROUTE, active_stop
from probos.crew_utils import is_crew_agent
from probos.mesh.intent import IntentAuthorizationDenied
```
REPLACE:
```
from probos.agent_stop import SEAM_DM_ROUTE, active_stop
from probos.cognitive.context_manifest import context_manifest_metadata  # AD-1357
from probos.crew_utils import is_crew_agent
from probos.mesh.intent import IntentAuthorizationDenied
```

**P2-12** `src/probos/routers/agents.py`

SEARCH:
```
    if emotion:
        meta["emotion"] = emotion
    return meta
```
REPLACE:
```
    if emotion:
        meta["emotion"] = emotion
    # AD-1357 (#1749): what the reply was given, beside it. Absent when the agent
    # recorded none, so such a turn's metadata is unchanged.
    meta.update(context_manifest_metadata(result))
    return meta
```

**P2-13** `src/probos/routers/thread_fanout.py`

SEARCH:
```
from probos.cognitive.dm import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm.write_ledger import WriteLedger
from probos.dm_reply import DmReply  # AD-1248
```
REPLACE:
```
from probos.cognitive.dm import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm.write_ledger import WriteLedger
from probos.cognitive.context_manifest import context_manifest_metadata  # AD-1357
from probos.dm_reply import DmReply  # AD-1248
```

**P2-14** `src/probos/routers/thread_fanout.py`

SEARCH:
```
            metadata: dict[str, Any] = {"intent_id": intent.id, "fanout": "ad914"}
            if generated_ids:
                metadata["generated_attachment_ids"] = generated_ids
```
REPLACE:
```
            metadata: dict[str, Any] = {"intent_id": intent.id, "fanout": "ad914"}
            if generated_ids:
                metadata["generated_attachment_ids"] = generated_ids
            metadata.update(context_manifest_metadata(result))  # AD-1357 (#1749)
```

M2 also removes `_UNTIL_M2` from T2, T4a, T4b, T4c, T5, T7, T8, T9, T10, T11, T15 and T16 (12 decorator lines), and then deletes its definition line, `_UNTIL_M2 = pytest.mark.xfail(strict=True, reason="AD-1357 M2: a DM reply carries no context manifest")`, which no test uses afterwards.

### 7.3 M3

**P3-1** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
            if not query:
                return observation

            # AD-602: Classify query and select strategy
```
REPLACE:
```
            if not query:
                return observation
            # AD-1357 (#1749): recall ran for this direct_message turn. Its query is
            # kept only when it is the Captain's own words, BF-632's
            # ``captain_message`` on a 1:1 turn. A group turn's query is the room's
            # trigger, which can be another agent's message, and the ``text``
            # fallback can lead with the camera scene (AD-733a); for those only
            # the length is kept.
            if intent.intent == "direct_message":
                _captain_words = params.get("captain_message")
                context_manifest.start_recall(
                    observation,
                    query=query,
                    captain_words=(
                        not params.get("is_group_chat")
                        and isinstance(_captain_words, str)
                        and bool(_captain_words)
                    ),
                )

            # AD-602: Classify query and select strategy
```

**P3-2** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
                observation["recent_memories"] = memory_list
                # BF-631 DIAG: surface what the per-message recall actually fed
```
REPLACE:
```
                observation["recent_memories"] = memory_list
                context_manifest.note_episodes(observation, episodes)  # AD-1357
                # BF-631 DIAG: surface what the per-message recall actually fed
```

**P3-3** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
        except Exception:
            logger.warning("BF-138: Failed to fetch episodic memory context — agent will respond without memory", exc_info=True)
```
REPLACE:
```
        except Exception:
            logger.warning("BF-138: Failed to fetch episodic memory context — agent will respond without memory", exc_info=True)
            context_manifest.note_recall_failed(observation)  # AD-1357
```

**P3-4** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
                    try:
                        oracle = self._runtime._oracle_service
                        oracle_text = await oracle.query_formatted(
                            query_text=query,
                            agent_id=_mem_id,
                            k_per_tier=3,
                            max_chars=2000,
                        )
                        if oracle_text:
                            observation["_oracle_context"] = oracle_text
```
REPLACE:
```
                    try:
                        oracle = self._runtime._oracle_service
                        _oracle_sources: list[tuple[str, str]] = []  # AD-1357
                        oracle_text = await oracle.query_formatted(
                            query_text=query,
                            agent_id=_mem_id,
                            k_per_tier=3,
                            max_chars=2000,
                            sources_out=_oracle_sources,
                        )
                        context_manifest.note_oracle(observation, "all", _oracle_sources)
                        if oracle_text:
                            observation["_oracle_context"] = oracle_text
```

**P3-5** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
                    except Exception:
                        logger.warning("AD-568a: Oracle query failed, continuing without", exc_info=True)
```
REPLACE:
```
                    except Exception:
                        logger.warning("AD-568a: Oracle query failed, continuing without", exc_info=True)
                        context_manifest.note_oracle(observation, "all", None)  # AD-1357
```

**P3-6** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
                    try:
                        oracle = self._runtime._oracle_service
                        graph_text = await oracle.query_formatted(
                            query_text=query,
                            agent_id=_mem_id,
                            k_per_tier=3,
                            max_chars=1000,
                            tiers=["graph"],
                        )
                        if graph_text:
                            observation["_oracle_context"] = graph_text
                    except Exception:
                        logger.debug("BF-265: graph-only Oracle query failed, continuing without")
```
REPLACE:
```
                    try:
                        oracle = self._runtime._oracle_service
                        _graph_sources: list[tuple[str, str]] = []  # AD-1357
                        graph_text = await oracle.query_formatted(
                            query_text=query,
                            agent_id=_mem_id,
                            k_per_tier=3,
                            max_chars=1000,
                            tiers=["graph"],
                            sources_out=_graph_sources,
                        )
                        context_manifest.note_oracle(observation, "graph", _graph_sources)
                        if graph_text:
                            observation["_oracle_context"] = graph_text
                    except Exception:
                        logger.debug("BF-265: graph-only Oracle query failed, continuing without")
                        context_manifest.note_oracle(observation, "graph", None)  # AD-1357
```

**P3-7** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
            try:
                _peer_mems = await self._maybe_cross_agent_recall(query=query, mem_id=_mem_id, k=3)
                if _peer_mems:
                    observation.setdefault("recent_memories", []).extend(_peer_mems)
            except Exception:
                logger.warning("AD-979d: cross-agent recall wiring failed; continuing", exc_info=True)
```
REPLACE:
```
            try:
                _peer_mems = await self._maybe_cross_agent_recall(query=query, mem_id=_mem_id, k=3)
                # AD-1357: how many peer memories came back; never their ids or text.
                context_manifest.note_cross_agent(observation, len(_peer_mems))
                if _peer_mems:
                    observation.setdefault("recent_memories", []).extend(_peer_mems)
            except Exception:
                logger.warning("AD-979d: cross-agent recall wiring failed; continuing", exc_info=True)
                context_manifest.note_cross_agent(observation, None)  # AD-1357
```

**P3-8** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
                _conf = await self._recall_confidence_probe(query=query, mem_id=_mem_id, k=5)
                if _conf is not None:
```
REPLACE:
```
                _conf = await self._recall_confidence_probe(query=query, mem_id=_mem_id, k=5)
                context_manifest.note_confidence(observation, _conf)  # AD-1357
                if _conf is not None:
```

**P3-9** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```
                    _excerpt = consult_transcript(
                        _store, _agent_ids, _tg_query,
                        max_threads=getattr(_mem_cfg, "transcript_grounding_max_threads", 8),
                        max_chars=getattr(_mem_cfg, "transcript_grounding_max_chars", 1200),
                    )
                    if _excerpt:
                        observation["_transcript_grounding"] = _excerpt
```
REPLACE:
```
                    _tg_threads: list[str] = []  # AD-1357: the room the excerpt came from
                    _excerpt = consult_transcript(
                        _store, _agent_ids, _tg_query,
                        max_threads=getattr(_mem_cfg, "transcript_grounding_max_threads", 8),
                        max_chars=getattr(_mem_cfg, "transcript_grounding_max_chars", 1200),
                        sources_out=_tg_threads,
                    )
                    context_manifest.note_transcript(
                        observation, hit=bool(_excerpt), thread_ids=_tg_threads,
                    )
                    if _excerpt:
                        observation["_transcript_grounding"] = _excerpt
```

**P3-10** `src/probos/cognitive/oracle_service.py`

SEARCH:
```
        tiers: list[str] | None = None,
        max_chars: int = 4000,
    ) -> str:
        """Query and return formatted string with provenance tags.

        Budget enforcement: accumulates content lengths, stops at max_chars.
        """
```
REPLACE:
```
        tiers: list[str] | None = None,
        max_chars: int = 4000,
        sources_out: list[tuple[str, str]] | None = None,
    ) -> str:
        """Query and return formatted string with provenance tags.

        Budget enforcement: accumulates content lengths, stops at max_chars.

        AD-1357: when ``sources_out`` is a list, the ``(source_tier, path)`` of each
        rendered result is appended to it in rendered order (``path`` is ``""`` for
        a result whose metadata has none). The returned text is the same either way.
        """
```

**P3-11** `src/probos/cognitive/oracle_service.py`

SEARCH:
```
            if char_count + len(line) + 1 > max_chars:
                break
            lines.append(line)
            char_count += len(line) + 1

        lines.append("=== END ORACLE RESULTS ===")
```
REPLACE:
```
            if char_count + len(line) + 1 > max_chars:
                break
            lines.append(line)
            char_count += len(line) + 1
            if sources_out is not None:
                sources_out.append((r.source_tier, str(r.metadata.get("path") or "")))

        lines.append("=== END ORACLE RESULTS ===")
```

**P3-12** `src/probos/cognitive/transcript_grounding.py`

SEARCH:
```
    max_threads: int = 8,
    max_chars: int = 1200,
) -> str | None:
    """Return a bounded excerpt of the canonical transcript (the recording) for
    the room — among those the agent participated in — that best matches
    ``query``; or ``None`` when nothing meaningfully matches.
```
REPLACE:
```
    max_threads: int = 8,
    max_chars: int = 1200,
    sources_out: list[str] | None = None,
) -> str | None:
    """Return a bounded excerpt of the canonical transcript (the recording) for
    the room — among those the agent participated in — that best matches
    ``query``; or ``None`` when nothing meaningfully matches. AD-1357: when
    ``sources_out`` is a list and an excerpt is returned, the id of the room it
    came from is appended to it; the excerpt is the same either way.
```

**P3-13** `src/probos/cognitive/transcript_grounding.py`

SEARCH:
```
    if excerpt is None and best_focus:
        excerpt = _format_excerpt(
            best_thread, best_msgs, qtokens, max_chars=max_chars
        )
    return excerpt
```
REPLACE:
```
    if excerpt is None and best_focus:
        excerpt = _format_excerpt(
            best_thread, best_msgs, qtokens, max_chars=max_chars
        )
    if excerpt is not None and sources_out is not None:
        sources_out.append(str(getattr(best_thread, "id", "") or ""))
    return excerpt
```

M3 also removes `_UNTIL_M3` from T1, T3, T13, T14, T17 and T18 (6 decorator lines), and then deletes its definition line, `_UNTIL_M3 = pytest.mark.xfail(strict=True, reason="AD-1357 M3: recall and the lookups are not recorded")`, which no test uses afterwards.

### 7.4 M4

**P4-1** `src/probos/cognitive/cognitive_agent.py` (the SEARCH is P2-5's REPLACE)

SEARCH:
```
        _agentic_output = await self._maybe_run_conversational_agentic(
            observation,
            system_prompt=composed,
            user_message=user_message,
            owned_steps_presentation=owned_presentation,
        )
        if _agentic_output is not None:
            decision = {
                "action": "execute",
                "llm_output": _agentic_output,
                "tier_used": "agentic",
            }
            # AD-1203 + AD-1248: provenance for the turn, set by the run above.
            _attach_run_provenance(decision, observation)
            # AD-1357 (#1749): the id the reply's context manifest gives this turn.
            _turn_entry_id = uuid.uuid4().hex
            context_manifest.record_manifest(
```
REPLACE:
```
        _t_turn = time.monotonic()  # AD-1357: the DM-turn journal row's latency
        _agentic_output = await self._maybe_run_conversational_agentic(
            observation,
            system_prompt=composed,
            user_message=user_message,
            owned_steps_presentation=owned_presentation,
        )
        if _agentic_output is not None:
            decision = {
                "action": "execute",
                "llm_output": _agentic_output,
                "tier_used": "agentic",
            }
            # AD-1203 + AD-1248: provenance for the turn, set by the run above.
            _attach_run_provenance(decision, observation)
            # AD-1357 (#1749): the loop's own model calls write no journal row
            # (``journal_token_report``'s docstring), so the DM turn writes one
            # under this id, which the reply's context manifest names. ``model``
            # is "unknown", as BF-901 requires of a row that names no answering
            # model, and the empty token source files it as uncharged.
            _turn_entry_id = uuid.uuid4().hex
            if self._cognitive_journal:
                try:
                    await self._cognitive_journal.record(
                        entry_id=_turn_entry_id,
                        timestamp=time.time(),
                        agent_id=self.id,
                        agent_type=self.agent_type,
                        tier="agentic",
                        model="unknown",
                        latency_ms=(time.monotonic() - _t_turn) * 1000,
                        intent=observation.get("intent", ""),
                        success=True,
                        prompt_hash=context_manifest.turn_hash(user_message),
                        response_length=len(_agentic_output),
                        intent_id=observation.get("intent_id", ""),
                        dag_node_id=context_manifest.DM_TURN_DAG_NODE,
                        response_hash=context_manifest.turn_hash(_agentic_output),
                        correlation_id=observation.get("correlation_id", ""),
                    )
                except Exception:
                    logger.debug("AD-1357: DM-turn journal recording failed", exc_info=True)
            context_manifest.record_manifest(
```

M4 also removes `_UNTIL_M4` from T6 (1 decorator line), and then deletes its definition line, `_UNTIL_M4 = pytest.mark.xfail(strict=True, reason="AD-1357 M4: an agentic DM turn writes no journal row")`, which no test uses afterwards.

## 8. Tracking (M5's commit)

**Head constraint:** neither head may carry a lifecycle keyword from `gen_ad_ledger.py` `_STATUS_PATTERNS` (`:126-132`) in its first 120 characters.
**Date rule:** both heads carry 2026-11-05. If M5 is committed on another local date (`git log -1 --format=%cs`), use that date.
**Staging:** explicit paths only.
**Re-anchoring:** BF-952 may already have added a `PROGRESS.md` paragraph directly under `# ProbOS Progress` and a `DECISIONS.md` entry above `### BF-950 --`. P5-1 still matches the title and goes above it. P5-2 anchors on the M3e4d8 entry's last line, which BF-952 does not touch. Those are the only re-anchorings allowed, and the orchestrator re-checks both on the real base.

**P5-1** `PROGRESS.md`

SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1357 (2026-11-05), #1749 -- a crew chat reply records what it was given.** A crew `direct_message` reply carries a context manifest under its stored `metadata["context_manifest"]` (`cognitive/context_manifest.py`). The manifest names each prompt section the `_emit` bids of `_build_user_message` put up, in emission order, with its character count and whether the attention budget kept it, then the text appended after assembly (strategy advice, the owned-steps view, room inputs). It records whether episodic recall ran; its query, only when that is the Captain's own words on a 1:1 turn; the agent's own recalled episode ids and source tags; and the AD-981a band, best similarity and AD-1038 recall type. It records whether cross-agent recall (a count), transcript grounding (the room id) and the passive Oracle lookup (a count per tier, and the paths of Ship's Records results) ran. It also carries the journal's prompt and response hashes and the id of the turn's journal row. It holds no section text, no other agent's text, no peer episode id and no camera scene, and it is at most 16 KiB. An agentic DM turn writes one cognitive-journal row (`tier` agentic, `model` unknown, `dag_node_id` dm-turn, no token source); a single-pass turn already wrote one. The 1:1 route and the group fan-out store the manifest. `OracleService.query_formatted` and `consult_transcript` gain a keyword-only `sources_out` list and return the same text. No config field. The contract is `prompts/ad-1357-dm-context-manifest.md`.

```

**P5-2** `DECISIONS.md`

SEARCH:
```
- *Reversal.* Revert the M3e4d8 commits.

```
REPLACE:
```
- *Reversal.* Revert the M3e4d8 commits.

### AD-1357 -- A crew chat reply records what it was given: a context manifest beside it, and a journal row for the agentic DM turn (2026-11-05, #1749)

- *Scope.* `cognitive/context_manifest.py` (new: `ContextLedger`, `RecallRecord`, `build_manifest`, `record_manifest`, `storable`, `turn_hash`, `context_manifest_metadata`), `cognitive/cognitive_agent.py` (the DM `_emit` renderer, both exits of `_decide_via_llm` and the agentic journal row, the recall and lookup notes in `_recall_relevant_memories`, `_build_result_metadata`), `cognitive/oracle_service.py` (`query_formatted(sources_out=)`), `cognitive/transcript_grounding.py` (`consult_transcript(sources_out=)`), `routers/agents.py` (`_build_reply_metadata`), `routers/thread_fanout.py` (the group reply's metadata), tests. Contract `prompts/ad-1357-dm-context-manifest.md`.
- *CM1 (shape).* Inline under the reply's `metadata["context_manifest"]`, at most 16 KiB and always storable, so it is kept as long as the message. Rejected: a content-addressed blob ref; a new table.
- *CM2 (producer).* Each DM `_emit` bid's renderer is the ledger's: it returns the same text and marks the section kept, because `ContextAssembler` renders only the bids it keeps. A section is recorded by its name, so a new one needs no change here. Rejected: a survivors API on the assembler; rebuilding the sections from observation keys.
- *CM3 (journal).* The agentic branch writes one row: `model` unknown (BF-901), an empty token source (uncharged), `cached` 0, `dag_node_id` dm-turn. On both paths the manifest names its row by id and hashes. Rejected: `cached` true (filed as replayed); a separate table; journaling each loop call (BF-901 S2's gap).
- *CM4 (privacy).* The agent's own episode ids, Ship's Records paths and its own transcript room are identified. Cross-agent recall and every other Oracle tier are counted. The query is kept only when it is the Captain's words on a 1:1 turn. Rejected: hashed peer ids; peer ids.
- *CM5 (wire).* The manifest is the last key of `_build_result_metadata`, so BF-805's prune drops it first, and `storable` turns one the store would refuse into a stub.
- *Not changed.* `ContextAssembler`, `AttentionFaculty`, the prompt text, `CognitiveJournal`'s schema, the federation bridge (it forwards only `dm_reply`), config.
- *Residual.* Recorded limits L1 to L15 of the contract.
- *Reversal.* Revert the AD-1357 commits.

```

Then regenerate the ledger (`PY -P scripts/gen_ad_ledger.py`) and stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as written. **Not updated:** `docs/development/roadmap.md`.

## 9. What this does NOT change

- **The prompt text** (the AD-1028 golden).
- **The attention code:** `ContextAssembler`, `AttentionFaculty`, salience and the camera bid.
- **Recall ranking:** retrieval, ranking, BF-631, AD-981b's cues and AD-979d's gates.
- **The Oracle and the transcript code:** the Oracle's tiers and scores; `consult_transcript`'s ranking and excerpt.
- **The journal's schema and its readers.**
- **Wire and federation:** the federation bridge's allow-list (`federation/bridge.py:943-947`); `IntentBus._prune_metadata`.
- **Reply pipeline, UI and records:** `DmReplyPipeline`; the HXI; `records_store.py` (BF-952's file).
- **No new config field and no new `EventType`.**

## 10. Mutation rows (campaign of record on M4's head)

- Prefixes `CXM` and `DTJ`. Neither occurs in `prompts/`, `DECISIONS.md` or `PROGRESS.md` (Absence A9); the same search finds `OAM-`.
- Run an unmutated baseline of the new file first, then each row against it.
- Record the base tree and the sha256 of `context_manifest.py`, `cognitive_agent.py`, `oracle_service.py`, `transcript_grounding.py`, `routers/agents.py` and `routers/thread_fanout.py`.
- A row whose line appears more than once names the function it sits in.

| Id | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| CXM-1 | context_manifest.py | `section.kept = True` | `section.kept = False` | `test_a_section_is_recorded_by_its_name_alone_and_kept_only_when_assembly_renders_it`, `test_a_section_the_attention_budget_drops_is_recorded_as_not_kept` |
| CXM-2 | context_manifest.py | `return text` (in `_render`) | `return text + " "` | `test_dm_golden_byte_identical` (tests/test_ad1028_context_assembler.py), `test_a_section_the_attention_budget_drops_is_recorded_as_not_kept` |
| CXM-3 | context_manifest.py | `if chars > 0:` | `if True:` | `test_a_section_is_recorded_by_its_name_alone_and_kept_only_when_assembly_renders_it` |
| CXM-4 | context_manifest.py | `query=_text(query, MAX_QUERY_CHARS) if captain_words else None,` | `query=_text(query, MAX_QUERY_CHARS),` | `test_the_manifest_holds_no_other_agents_text_and_no_camera_scene` [group-turn] |
| CXM-5 | context_manifest.py | `for ep in listed[:MAX_EPISODES]` | `for ep in listed` | `test_the_manifest_fits_its_bound_at_every_cap` |
| CXM-6 | context_manifest.py | `if type(value) is bool or not isinstance(value, (int, float)):` | `if not isinstance(value, (int, float)):` | `test_a_similarity_that_is_not_a_finite_number_is_recorded_as_none_and_the_row_stores` [a-bool] |
| CXM-7 | context_manifest.py | `return round(number, 4) if math.isfinite(number) else None` | `return round(number, 4)` | `test_a_similarity_that_is_not_a_finite_number_is_recorded_as_none_and_the_row_stores` [nan], [infinity] |
| CXM-8 | context_manifest.py | `"best_similarity": _finite(getattr(confidence, "best_similarity", None)),` | `"best_similarity": None,` | `test_a_dm_reply_with_recall_an_active_game_and_a_records_hit_lists_all_three` |
| CXM-9 | context_manifest.py | `record.cross_agent = {"ran": True, "failed": count is None, "count": count or 0}` | `record.cross_agent = {"ran": True, "failed": False, "count": 0}` | `test_the_manifest_holds_no_other_agents_text_and_no_camera_scene` [one-to-one-scene-and-peer] |
| CXM-10 | context_manifest.py | `if name == _IDENTIFIED_TIER and path and len(paths) < MAX_RECORD_PATHS:` | `if path and len(paths) < MAX_RECORD_PATHS:` | `test_only_ship_records_results_are_identified_and_every_tier_is_counted` |
| CXM-11 | context_manifest.py | `if name in by_tier or len(by_tier) < MAX_TIERS:` | `if True:` | `test_the_manifest_fits_its_bound_at_every_cap` |
| CXM-12 | context_manifest.py | `"prompt_hash": turn_hash(user_message),` | `"prompt_hash": turn_hash(system_prompt),` | `test_the_manifest_names_its_journal_row_on_the_single_pass_path` |
| CXM-13 | context_manifest.py | `"response_hash": turn_hash(response_text),` | `"response_hash": turn_hash(user_message),` | `test_the_manifest_names_its_journal_row_on_the_single_pass_path` |
| CXM-14 | context_manifest.py | `return hashlib.md5(value[:500].encode("utf-8", "surrogatepass")).hexdigest()[:12]` | `return hashlib.md5(value[:600].encode("utf-8", "surrogatepass")).hexdigest()[:12]` | `test_the_manifest_names_its_journal_row_on_the_single_pass_path` |
| CXM-15 | context_manifest.py | `allow_nan=False,` (in `storable`) | delete the line | `test_a_manifest_the_store_would_refuse_is_replaced_by_a_stub_that_says_so` [nan] |
| CXM-16 | context_manifest.py | `if len(encoded) > MAX_MANIFEST_BYTES:` | `if False:` | `test_a_manifest_the_store_would_refuse_is_replaced_by_a_stub_that_says_so` [oversize] |
| CXM-17 | context_manifest.py | `observation.pop(MANIFEST_KEY, None)` | delete the line | `test_a_section_is_recorded_by_its_name_alone_and_kept_only_when_assembly_renders_it` |
| CXM-18 | context_manifest.py | `if type(manifest) is dict and manifest:` (in `context_manifest_metadata`) | `if manifest is not None:` | `test_a_reply_without_a_manifest_keeps_its_metadata_unchanged` [manifest-not-a-dict], [empty-manifest] |
| CXM-20 | cognitive_agent.py | `render=_ledger.renderer(source, text),` | `render=(lambda _t=text: _t),` | `test_a_dm_reply_with_recall_an_active_game_and_a_records_hit_lists_all_three`, `test_a_section_the_attention_budget_drops_is_recorded_as_not_kept` |
| CXM-21 | cognitive_agent.py | `_ledger.note_appended("strategy_advice", len(context) + 2)` | `pass` | `test_text_appended_after_assembly_is_recorded_by_name_and_length` [strategy-advice] |
| CXM-22 | cognitive_agent.py | `_ledger.note_appended("owned_steps_view", len(user_message) - _before_owned)` | `pass` | `test_text_appended_after_assembly_is_recorded_by_name_and_length` [owned-steps-view] |
| CXM-23 | cognitive_agent.py | `_ledger.note_appended("room_inputs", len(user_message) - _before_room_inputs)` | `pass` | `test_text_appended_after_assembly_is_recorded_by_name_and_length` [room-inputs] |
| CXM-24 | cognitive_agent.py | `journal_entry_id=request.id,` | `journal_entry_id="",` | `test_the_manifest_names_its_journal_row_on_the_single_pass_path` |
| CXM-25 | cognitive_agent.py | `path="single_pass",` | `path="agentic",` | `test_the_manifest_names_its_journal_row_on_the_single_pass_path` |
| CXM-26 | cognitive_agent.py | `metadata[context_manifest.CONTEXT_MANIFEST_METADATA_KEY] = manifest` | `pass` | `test_a_dm_reply_with_recall_an_active_game_and_a_records_hit_lists_all_three`, `test_the_manifest_is_the_last_reply_metadata_key_so_bf805_drops_it_first` |
| CXM-27 | cognitive_agent.py | `not params.get("is_group_chat")` | `True` | `test_the_manifest_holds_no_other_agents_text_and_no_camera_scene` [group-turn-with-captain-message] |
| CXM-28 | cognitive_agent.py | `and bool(_captain_words)` | delete the line | `test_the_manifest_holds_no_other_agents_text_and_no_camera_scene` [empty-captain-message] |
| CXM-29 | cognitive_agent.py | `context_manifest.note_episodes(observation, episodes)  # AD-1357` | delete the line | `test_a_dm_reply_with_recall_an_active_game_and_a_records_hit_lists_all_three`, `test_the_manifest_holds_no_other_agents_text_and_no_camera_scene` |
| CXM-30 | cognitive_agent.py | `context_manifest.note_confidence(observation, _conf)  # AD-1357` | delete the line | `test_a_dm_reply_with_recall_an_active_game_and_a_records_hit_lists_all_three` |
| CXM-31 | cognitive_agent.py | `sources_out=_oracle_sources,` | delete the line | `test_a_dm_reply_with_recall_an_active_game_and_a_records_hit_lists_all_three` |
| CXM-32 | cognitive_agent.py | `context_manifest.note_oracle(observation, "graph", _graph_sources)` | `context_manifest.note_oracle(observation, "all", _graph_sources)` | `test_a_graph_only_lookup_is_recorded_with_its_scope` |
| CXM-33 | cognitive_agent.py | `context_manifest.note_cross_agent(observation, len(_peer_mems))` | delete the line | `test_the_manifest_holds_no_other_agents_text_and_no_camera_scene` [one-to-one-scene-and-peer] |
| CXM-34 | cognitive_agent.py | `observation, hit=bool(_excerpt), thread_ids=_tg_threads,` | `observation, hit=False, thread_ids=_tg_threads,` | `test_recall_records_the_room_transcript_grounding_drew_on` |
| CXM-35 | cognitive_agent.py | `if intent.intent == "direct_message":` (P3-1's) | `if False:` | `test_a_dm_reply_with_recall_an_active_game_and_a_records_hit_lists_all_three`, `test_recall_records_the_room_transcript_grounding_drew_on` |
| CXM-40 | oracle_service.py | `sources_out.append((r.source_tier, str(r.metadata.get("path") or "")))` | `sources_out.append((r.source_tier, ""))` | `test_the_oracle_reports_what_it_rendered_and_renders_the_same_text`, `test_a_dm_reply_with_recall_an_active_game_and_a_records_hit_lists_all_three` |
| CXM-41 | transcript_grounding.py | `sources_out.append(str(getattr(best_thread, "id", "") or ""))` | `sources_out.append("")` | `test_transcript_grounding_reports_the_room_its_excerpt_came_from` [a-room-matches], `test_recall_records_the_room_transcript_grounding_drew_on` |
| CXM-42 | transcript_grounding.py | `if excerpt is not None and sources_out is not None:` | `if sources_out is not None:` | `test_transcript_grounding_reports_the_room_its_excerpt_came_from` [only-a-title-matches] |
| CXM-45 | routers/agents.py | `meta.update(context_manifest_metadata(result))` | delete the line | `test_the_reply_metadata_carries_the_manifest_the_agent_made`, `test_a_dm_reply_with_recall_an_active_game_and_a_records_hit_lists_all_three` |
| CXM-46 | routers/thread_fanout.py | `metadata.update(context_manifest_metadata(result))  # AD-1357 (#1749)` | delete the line | `test_a_group_reply_is_stored_with_its_manifest_and_one_without_stays_unchanged` |
| DTJ-1 | cognitive_agent.py | `tier="agentic",` | `tier="standard",` | `test_an_agentic_dm_turn_writes_one_journal_row_that_the_manifest_names` |
| DTJ-2 | cognitive_agent.py | `model="unknown",` (in the DM-turn `record` call; the other `model="unknown",` lines carry a comment) | `model="",` | `test_an_agentic_dm_turn_writes_one_journal_row_that_the_manifest_names` |
| DTJ-3 | cognitive_agent.py | `dag_node_id=context_manifest.DM_TURN_DAG_NODE,` | delete the line | `test_an_agentic_dm_turn_writes_one_journal_row_that_the_manifest_names` |
| DTJ-4 | cognitive_agent.py | `prompt_hash=context_manifest.turn_hash(user_message),` | `prompt_hash=context_manifest.turn_hash(composed),` | `test_an_agentic_dm_turn_writes_one_journal_row_that_the_manifest_names` |
| DTJ-5 | cognitive_agent.py | `entry_id=_turn_entry_id,` | `entry_id=uuid.uuid4().hex,` | `test_an_agentic_dm_turn_writes_one_journal_row_that_the_manifest_names` |
| DTJ-6 | cognitive_agent.py | `response_hash=context_manifest.turn_hash(_agentic_output),` | `response_hash="",` | `test_an_agentic_dm_turn_writes_one_journal_row_that_the_manifest_names` |

## 11. Recorded limits

- **L1.** Three other sinks store no manifest, though the `IntentResult` carries one: the inline-callsign route (`routers/chat.py:586-592`), the main-chat multi-agent append (`:328-337`, built from `PerAgentReply`) and the deferred-turn replay (`startup/finalize.py:3103-3109`). Considered, deferred (CM7).
- **L2.** On an AD-724-1 sanity-gate retry, the stored body may be the retry's (`cognitive/dm/reply_pipeline.py:679-699`), while the route's metadata comes from the first `result` (`routers/agents.py:3837`). The manifest then describes the first attempt, as `tool_trace_ref` already does.
- **L3.** A turn that does not reach `_decide_via_llm` carries no manifest: a decision-cache hit (off by default, BF-864), a procedural replay, an external sub-task chain.
- **L4.** An AD-1165 promoted run: the acknowledgement carries a manifest, but the report posted later (`cognitive/turn_promotion.py`) does not.
- **L5.** Exogenous bids that `AttentionFaculty` merges are not `_emit` bids and are not listed.
- **L6.** Working memory (which carries Ward Room activity) and `dm_sensorium` are recorded as one section each, not itemised.
- **L7.** Emission order is recorded. The prompt order can differ, by `zone_floor` (the camera, AD-1031) and AD-1030 salience.
- **L8.** For cross-agent recall, `ran: true, count: 0` covers both "asked, nothing came back" and AD-979d's own gates declining (a band other than weak, or no associated peer).
- **L9.** A Ship's Records path can name another agent's notebook (`notebooks/<callsign>/…`). That is a ship-classified record the agent was cleared to read (BF-679).
- **L10.** An oversize or unencodable manifest is replaced by the stub `{"v","path","unrecorded"}`, not truncated.
- **L11.** In `get_token_usage` and EPS capacity, the agentic DM-turn row counts as one call with 0 tokens, as BF-183's timeout rows do. The loop's own calls stay unjournaled (BF-901 S2).
- **L12.** There is no HXI view, Counselor reader or API filter for the manifest. `GET /api/threads/{id}/messages` already returns it inside `metadata`.
- **L13.** A recall that raises before `start_recall` (only `_dm_recall_query` runs before it) reads as `ran: false`.
- **L14.** The response hash is of the model's raw reply, as the journal's is, not of the body `DmReplyPipeline` stores.
- **L15.** Explicit tool lookups (`oracle_query`, the records tools) are in the tool trace (`tool_trace_ref`) and are not repeated in the manifest. The source refs a later section reads (AD-1358 option C's game records) would need a `refs` field on the ledger; considered, deferred.

## 12. The Captain's items

- **None to decide.** The manifest is additive metadata, and it keeps #1749's privacy guarantee as strong as asked (CM4). The federation allow-list already keeps it on the vessel.
- **Optional live check after merge (reads only):** after a crew DM, `GET /api/threads/<id>/messages` shows `metadata.context_manifest` on the agent's row. On an agentic turn, the journal has a `dm-turn` row whose id matches it.

## 13. Verified Against Codebase (2026-11-05, on `8ecf968d`)

```
git rev-parse HEAD -> 8ecf968d567632ea09316406dc9d7fdb3d98c7c1 ; git status --short -> (clean)
cognitive_agent.py:28 `from probos.cognitive.attention import AttentionBid, ContextAssembler, estimate_tokens`; :29 tiered_knowledge import; :15 `import uuid`; :14 `import time`
cognitive_agent.py:249-307 _build_result_metadata; :267-268 "Empty on every non-agentic path..."; :302-307 owned_steps loop, `return metadata`
cognitive_agent.py:3889 _decide_via_llm; :4004 build_user_message; :4006-4029 strategy advice, owned_steps_view
cognitive_agent.py:4401-4417 agentic branch returns before :4571-4610 journal record (entry_id=request.id :4586; prompt_hash md5(user_message[:500])[:12] :4574; response_hash :4604)
cognitive_agent.py:4419-4455 room inputs; :4612-4617 BF-922 gate; :4711-4740 _conversational_agentic_will_run (1:1, not group, not vision)
cognitive_agent.py:3745-3758 cache-hit row cached=True model "unknown"; :3786-3798 procedural row
cognitive_agent.py:7924-7939 IntentResult(metadata=_build_result_metadata(report, decision, observation)); :7931-7932 comment
cognitive_agent.py:8488-8536 _build_active_game_context; :10187-10199 recall_confidence segment; :10421-10430 trigger format
cognitive_agent.py:10496-10519 DM _bids/_emit; :10529-10808 _emit sources; :10814-10821 faculty/assembler
cognitive_agent.py:11429-11443 query; :11527 recall tier; :11564 strategy NONE; :11619-11626 BASIC; :11722-11768 ORACLE / graph query_formatted
cognitive_agent.py:11853-11857 memory dict (no id); :11900 recent_memories; :11916-11917 BF-138; :11926-11932 AD-979d; :11943-11952 probe; :11962-12006 AD-986b
cognitive_agent.py:12045-12162 _maybe_cross_agent_recall (peer text "X recalls:", source SECONDHAND, no id); :658-674 _dm_recall_query
architect.py:554-555 and builder.py:2615-2616: direct_message delegates to super()._build_user_message
attention.py:51-77 AttentionBid; :89-124 assemble renders survivors only; attention_faculty.py:374-386 arbitrate delegates (:324)
oracle_service.py:36-48 OracleResult.metadata dict; :721-780 query_formatted; :759-760 path; :1076/:1124 source_tier "records"
transcript_grounding.py:121-237 consult_transcript (one best room); :65-75 _speaker reads metadata["callsign"]
episodic.py:83-116 RecallConfidence(band, best_similarity, candidate_count, query, recall_type)
journal.py:21-47 schema; :375-428 record (never raises Exception); :782-815 get_reasoning_chain; :835-944 token readers filter cached = 0
journal_token_report.py:9-24 buckets (uncharged = empty source; agentic loop unjournaled); :59 dag_node_id LIKE 'st:%'
doctor/checks/token_accounting_check.py:166-174 model must be named or 'unknown'; sub_task.py:589-602 timeout row precedent
routers/agents.py:44-47 imports; :2840-2872 _build_reply_metadata; :3571-3583 captain_message raw; :3565 scene prepend; :3837-3853 append in try
routers/thread_fanout.py:42-44 imports; :676-686 group params (no captain_message); :794 result; :965-972 append
threads/__init__.py:198-207 to_dict incl metadata; :1466-1482 json.dumps allow_nan=False -> ValueError; :120 id regex
routers/threads.py:437-454 GET messages returns to_dict; mesh/intent.py:2217-2412 BF-805 _reply_bytes/_prune_metadata greedy order
federation/bridge.py:925-948 _serialize_directed_result forwards dm_reply only
config.py:1025,1033,1047 the three memory flags default False; config_models/agentic.py:504-513 dm_agentic.enabled False
crew_utils.py:58-66 _WARD_ROOM_CREW contains "scout"; earned_agency.py:61-68,100-120 tiers (None rank -> ENHANCED); config.py:216 TRUST_SENIOR 0.85
records_store.py:249-263 write_entry; :1140-1176 search (no status filter, "/" paths)
tests: test_ad1028_context_assembler.py:64 dm golden; test_ad1203_turn_provenance.py:114-283; test_ad1248_slice_a_crossing.py:245,260,574; test_ad914_group_chat_fanout.py:97-128; test_ad1140_publish_finding.py:1413-1430; test_ad1038_remember_know_render.py:398-412; test_bf901_s2_journal_token_provenance.py:98-118
scripts/ad_ceiling.py -> CEILING AD-1358 (issue titles, all states)
```

## Absence Verified (2026-11-05, on `8ecf968d`)

```
A1 CLAIM: the names this AD adds are new
   RUN:   rg -n "context_manifest|_context_ledger|_context_recall|ContextLedger|RecallRecord|DM_TURN_DAG_NODE|sources_out" -g "*.py"
   FOUND: none
   HOLDS: yes
A2 CLAIM: query_formatted has one definition, so no other Oracle-like class lacks sources_out
   RUN:   rg -n "def query_formatted" -g "*.py"
   FOUND: src/probos/cognitive/oracle_service.py:721
   HOLDS: yes
A3 CLAIM: no test pins the passive path's query_formatted kwargs
   RUN:   rg -n "query_formatted" tests
   FOUND: test_ad1294 (direct calls), test_ad1341_s2:282, test_ad696 (the chain lookup, unchanged), test_ad988, test_memory_architecture
   HOLDS: yes
A4 CLAIM: consult_transcript has one production caller
   RUN:   rg -n "consult_transcript\(" -g "*.py"
   FOUND: cognitive_agent.py:11981; tests test_ad986b, test_bf625 (positional and max_chars only)
   HOLDS: yes
A5 CLAIM: chat-message metadata readers read named keys only
   RUN:   rg -n "(msg|m|message|row|saved_message|current)\.metadata" src ; rg -n "metadata" src/probos/cognitive/transcript_grounding.py
   FOUND: room_inputs.py:151 (attachments); thread_fanout.py:548 (convergence); threads/__init__.py:830,1514 (equality on re-append); transcript_grounding.py:70 (callsign); crew_session.py and workforce.py are other stores
   HOLDS: yes
A6 CLAIM: no agent tool reads the chat thread store
   RUN:   rg -l chat_thread_store src/probos/tools
   FOUND: none
   HOLDS: yes
A7 CLAIM: federation forwards only dm_reply from metadata
   RUN:   rg -n metadata src/probos/federation/bridge.py
   FOUND: :943-947, :1464 (dm_reply only); :2237 is a docstring
   HOLDS: yes
A8 CLAIM: the agentic loop writes no journal row
   RUN:   rg -n journal src/probos/cognitive/agentic_dispatch.py ; rg -n "journal\.record\(|_journal\.record\(" src
   FOUND: none ; cognitive_agent.py:3748,3786,4585, sub_task.py:589,661
   HOLDS: yes (the agentic return at :4417 precedes :4585)
A9 CLAIM: the mutation prefixes CXM and DTJ are free
   RUN:   rg -l "\b(CXM|DTJ)-\d" prompts DECISIONS.md PROGRESS.md ; control rg -l "\bOAM-\d" (same scope)
   FOUND: none ; control finds prompts/bf-950-oracle-result-age.md
   HOLDS: yes
A10 CLAIM: no source-scan test reads a line this AD changes
   RUN:   rg -n "lambda _t=text|getsource\(CognitiveAgent\._build_user_message|_build_result_metadata\(|_build_reply_metadata" tests
   FOUND: test_ad1028:50, test_ad1029:71, test_ad1032:99 (their own bids); getsource asserts in test_ad631:246-271, test_ad723a_1:265-273, test_ad981b:239-242 (substrings that stay); test_ad1203:221-222,283 and test_ad1248:574 (substrings that stay)
   HOLDS: yes
A11 CLAIM: the HXI reads tool_trace_ref and no manifest key
   RUN:   rg -l tool_trace_ref ui/src
   FOUND: ConsultedEvidence.tsx and its test and helper
   HOLDS: yes (a new key only)
A12 CLAIM: no test pins the agentic DM turn as journal-free
   RUN:   rg -n "record\.(assert_not_awaited|assert_not_called|await_count|call_count)" tests
   FOUND: test_ad632a/h, test_ad632b, test_bf183, test_cognitive_journal:271,296 (intent "test" or chain steps)
   HOLDS: yes
A13 CLAIM: dag_node_id is parsed only for the "st:" prefix
   RUN:   rg -n dag_node_id src
   FOUND: journal_token_report.py:59 LIKE 'st:%'; gap_predictor.py:127 (episode field); journal.py; sub_task.py
   HOLDS: yes
```

## 14. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`:** `context_manifest.py` sits in the ranked `cognitive` package and imports only the stdlib. `routers` is unranked. No new class approaches the `SRP_MAX_*` limits: `ContextLedger` has 4 methods and `RecallRecord` has 1. `CognitiveAgent` keeps its frozen triggers.
- **`check_dormant_classes.py`:** `ContextLedger` and `RecallRecord` have production users (`cognitive_agent.py`).
- **`tests/test_events.py` registry scan:** no `._emit("` call is added.
- **Goldens:** the AD-1028 DM and WR goldens are unchanged by construction (CXM-2 proves the guard).
- **Config:** none. **EventType:** none.
- **Collection:** names the change adds are imported inside the tests, so M1 collects on the base, and the strict xfails keep G1 green.

## 15. Prior Art and Blind Spots

- **Internal:**
  - AD-568d's `_source_attribution` is copied into the episode's `dag_summary` (`cognitive_agent.py:12164-12178`), as counts only and in an episode that pruning can lose (the April games, #1749). **Adapted:** the facts go beside the reply instead.
  - BF-631's INFO line (`:11913`) is **made durable** as `recall.episodes`.
  - AD-1203 and `tool_trace_ref`, and BF-805's prune (**respected**, CM5).
  - Source monitoring (`docs/research/metacognitive-architecture.md` §2.3, Johnson et al. 1993): the manifest is the external source record that diagnosing a confabulation needs.
- **External** (from search summaries, not full reads):
  - OpenTelemetry GenAI conventions make capturing prompt content opt-in ([TrueFoundry summary](https://www.truefoundry.com/blog/opentelemetry-genai-semantic-conventions)). **Adopted:** content is never captured.
  - OpenInference's `retrieval.documents[].document.id`/`score` ([spec](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md)). **Adopted:** ids and counts. **Rejected:** `document.content`.
  - RAGFlow attaches a `reference` (`chunks`, `doc_aggs`) to each answer ([HTTP API](https://ragflow.io/docs/v0.25.0/http_api_reference)). **Adopted:** sources beside the answer. Whether RAGFlow stores them is not verified.
  - ContextCite attributes statements to context by ablation ([arXiv 2409.00729](https://arxiv.org/abs/2409.00729)). Considered, deferred: it is a later use of this manifest, not part of it.
  - `reference-projects.md`, judged on 2026-11-05: RAGFlow (memory systems, 180 days, last 2026-05-08) was overdue and is examined above. Considered, deferred: LoCoMo (2026-05-08), MCP Apps (2026-04-08), AG-UI (never).
- **Blind spots found:**
  1. BF-805 prunes in iteration order, so a large manifest placed early could starve `tool_trace_ref`.
  2. The store's `allow_nan=False` combined with the route's catch-all means a NaN would cost the Captain the reply in the transcript.
  3. The `text` fallback of `_dm_recall_query` can lead with the camera scene.
  4. A group query is another agent's message.
  5. The AD-724-1 retry swaps the body but not the result (L2).
  6. The federation allow-list already keeps the manifest aboard.
  7. A `MagicMock` runtime turns the AgenticLoop on in tests.
  8. A title-only transcript match returns `None` after choosing a room.

## 16. Diff Reviewer: properties to verify

M2 to M4 are shared contracts: review each whole contract, not only the delta.

1. **The prompt is byte-identical.** The ledger's renderer returns the same `text` object; the WR path is untouched; `ContextAssembler` and `AttentionFaculty` are unchanged.
2. **A manifest exists only after a DM prompt was assembled.** It is present on an observation only if `_build_user_message`'s DM branch ran on it (`start_ledger`). No other intent gains a key in `IntentResult.metadata`.
3. **Order and kept flags.** Sections follow emission order, appended ones come last, and `kept` is true if and only if the assembler rendered that section.
4. **The manifest holds no content.** No section text, no peer episode id, callsign or text, and no camera scene. The query is present only for a non-group turn with a non-empty `str` `captain_message`.
5. **Oracle results.** Only `records` results are identified, by path; every tier is counted; `by_tier` has at most 8 keys.
6. **Storability.** Every manifest stored is accepted by `ChatThreadStore.append_message_once`'s encoding and is at most 16,384 bytes, or it is the stub.
7. **Key order.** The manifest is the last key of `_build_result_metadata`.
8. **The single-pass journal call is byte-identical.** The manifest's hashes equal its row's (T5), and the agentic row's hashes equal the manifest's (T6).
9. **The agentic branch writes exactly one row.** Its fields are as T6 lists, and it is written before `record_manifest` with the same id.
10. **`sources_out` is a pure sink.** In `query_formatted` and `consult_transcript` it is keyword-only, defaults to `None`, never changes the returned text, and is appended to only for rendered results (the Oracle) or a returned excerpt (the transcript).
11. **The routers.** They add the key only through `context_manifest_metadata`, which returns `{}` for no manifest, a non-dict or an empty dict.
12. **Docstrings.** Every new or changed docstring and comment is true of the head, including P2-2, P2-9 and the M4 comment.
13. **xfail marks.** Each is removed only at its milestone (its decorator lines, then its definition line), and each test failed on the base for the reason its marker names. T7b passes on the base.
14. **No config field or `EventType` is added,** and nothing is federated.

## 17. Acceptance criteria

1. After a crew DM reply, its stored metadata names every emitted context section, the recalled episode ids and the band, and whether the Oracle or Records lookup ran and what it returned (T1).
2. A DM reply with recall, an active game and a Records hit lists all three (T1). With recall off, the manifest says so rather than omitting the key (T2).
3. Nothing in the manifest contains another agent's message text or the camera scene (T3, T15).
4. The journal has a row for the DM turn, on both paths, named by the manifest (T5, T6).
5. Every §10 mutant is killed. G1 to G5 and the §14 checks pass, and the broad gate's receipt is green.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## For the Captain

None. The change is additive metadata that keeps #1749's privacy guarantee as strong as asked. One risk for the orchestrator to watch at M1: the tests drive real recall and decision code through a `SimpleNamespace` runtime. Section 4's harness rule allows inert runtime attributes only; anything more comes back to the Architect.

Sources:
- [OpenTelemetry GenAI semantic conventions (TrueFoundry summary)](https://www.truefoundry.com/blog/opentelemetry-genai-semantic-conventions)
- [OpenInference semantic conventions](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md)
- [RAGFlow HTTP API reference v0.25.0](https://ragflow.io/docs/v0.25.0/http_api_reference)
- [ContextCite: Attributing Model Generation to Context (arXiv 2409.00729)](https://arxiv.org/abs/2409.00729)
