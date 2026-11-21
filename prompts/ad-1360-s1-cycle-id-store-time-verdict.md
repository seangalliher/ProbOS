# AD-1360 S1 (#1828): an episode records, when it is stored, whether its AD-492 correlation id came from a cognitive cycle; the rule that reads the record ships off

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-20

**Status:** oracle-proven (section 16). Issue #1828 stays open until S3. The PR (S1, S2a and S2b together, one broad gate) says `Refs #1828`. Decision: consult `bfa178a3` (one AD; slices S1, S2a and S2b, then S3); no Captain condition for S1. AD-1360 appears only in REPLACE text, the new files and the trackers, never in a SEARCH.

**Base:** the merged main after BF-989 (`24c30a7c`, tree `5d767c91`). The pairs were written and proved on `86b9c156`; BF-989 (#1844) also edits `cognitive_agent.py` (the qualification-marker guards of the lifecycle's working-memory records) and the two trackers, and no other file this contract edits. Every SEARCH occurs exactly once on the merged tree (section 16, O1), and operations 38 to 46 and 49 to 52 have new checkpoint blobs there. Every line number this contract gives for `cognitive_agent.py` below line 7877 is 7 lower than on the merged tree (BF-989 added seven lines above it); the pairs match by text, never by line.

**Line endings:** every edited file is `i/lf w/crlf` (`git ls-files --eol`). The SEARCH blocks are LF; match and write each file with its own line endings. The two new files are LF and ASCII only. No SEARCH contains a character outside ASCII.

**Milestones** (one Builder delegation each; the Builder applies the pairs, runs only the generators named, and runs no test; no `AD-` or `BF-` token in a commit subject):

| M | Content | Tier | Review |
|---|---|---|---|
| M1 | 7.1 (new tests) first, then 7.2 (new `cycle_trace.py`), T1-T2, S1-S6, C1-C2, E1-E8, K1-K2, X1-X6; then the config generators in 7.16 | HIGH | **Shared contract:** persisted episode schema, `types.py`, a security control, a new cross-layer API |
| M2 | B1-B5, R1-R4, A1-A9, X7-X8 | HIGH | **Shared contract:** cycle binding in `handle_intent`, `IntentResult.metadata` |
| M3 | TR1-TR4, ledger (7.17-7.19) | LOW | Delta |

- M1 and M2 get one full review by the GPT Diff Reviewer.
- Commit subjects:
  - M1: `Record a store-time correlation verdict on each episode, off by default`
  - M2: `Issue and bind a registered cycle id for every cognitive cycle`
  - M3: `Record the cycle-id registry in the status and decisions entries`
- About 70 Builder tool calls for M1, 30 for M2, 15 for M3.

## 0. Premises (this tree)

| P | Premise | Evidence |
|---|---|---|
| P1 | The one AD-492 cycle id generator | `cognitive_agent.py:3021-3023`; `perceive` builds the observation with `correlation_id` (`:3031`, `:3073`) |
| P2 | The rule is retired | `memory_security.py:95-112`; called at `:205` (`validate_recall_result`), `:266` (`sanitize_inbound_episode`) and `episodic.py:1567` (`_security_anomaly_drop`) |
| P3 | Metadata round trip | `_episode_to_metadata` `episodic.py:4388`; `correlation_id` key at `:4436`, kept out of the hash; `_metadata_to_episode` `:4561`, building `Episode(` at `:4624` |
| P4 | The hash's fields | `compute_episode_hash` `:1062-1088` hashes ten named fields |
| P5 | `store()` | `:2034`; the last edit before persisting is `:2217-2218`; `dataclasses` and `time` imported (`:11`, `:18`) |
| P6 | Binding | `bind_episodic_memory_gates` `startup/cognitive_services.py:54-89`; callers `:353` and `__main__.py:2329` |
| P7 | Lifecycle call sites | `handle_intent` `:8270` (concurrency slot) and `:8294` (BF-239 `try/finally`); `_run_recreation_turn` `:8092` (inside the same cycle) |
| P8 | Result metadata | `_build_result_metadata` `:254-330`, built only at `:8078`; the AD-1357 manifest is written last (`:320-329`) |
| P9 | Runtime service reach | `_cognitive_journal` property `:1781-1786`; runtime annotation `runtime.py:536`; set in `__init__` at `:1176`; `init_cognitive_services(` at `:3034` |
| P10 | ContextVar precedent | `admission/carrier.py:24`; `TicketHold.end` `:36-47` |
| P11 | Main producer | `_store_action_episode` `:12693`; `correlation_id=observation.get(...)` `:12810`; called from the lifecycle at `:7906` |
| P12 | Config | `MemorySecurityConfig` `config_models/crew.py:148-161`; dump pinned in `test_ad1270e2g_crew_models.py:186-191`; rendered at `config-reference.md:1043-1053` |

## 1. Problem

BF-938 retired AD-607b's correlation rule (DECISIONS `:2142`). It checked only that a `direct` episode's id was non-empty, and most direct producers set none. #1828 asks for the rule back as a check that the id resolves to a real AD-492 chain, and only for episodes written after a cutoff.

Nothing records which ids a cycle issued (P1), and episodes keep no write time (P5). An id is therefore unverifiable at recall.

## 2. Overview

| Part | Change |
|---|---|
| `probos/cycle_trace.py` (new, standard library only) | `CycleIdRegistry` (issue, register, resolves, kind_of; TTL and size bound); `judge_correlation_id`; `CURRENT_CYCLE_ID` ContextVar with `bind_cycle` and `unbind_cycle`; `new_cycle_id()` |
| `Episode` | `stored_at: float = 0.0` and `correlation_verdict: str = ""`, added last; not hashed |
| `store()` | Writes both fields with `dataclasses.replace` just before metadata is built, replacing whatever the producer set |
| Metadata | Both keys round-trip; a row without them reads `(0.0, "")` |
| Rule | `validate_provenance(episode, *, correlation_cutoff=0.0)` judges a `direct` episode with `stored_at > cutoff > 0`; any verdict other than `resolved` is flagged (section 4 G-c) |
| Callers | `validate_recall_result` and `_security_anomaly_drop` pass `configured_correlation_cutoff(config)`; `sanitize_inbound_episode` passes nothing |
| Config | `security.memory.correlation_cutoff: float = 0.0`, at least 0; accepts epoch seconds or ISO-8601 with an offset |
| Wiring | `runtime.cycle_registry`, passed through `init_cognitive_services` to `bind_episodic_memory_gates(..., cycle_registry=)` and then `EpisodicMemory.set_cycle_registry` |
| Agent | `_cycle_registry` property and `_issue_cycle_id()`; `_run_cycle_bound_lifecycle` binds an issued id and resets it in a `finally`; `perceive` takes the bound id; `IntentResult.metadata["correlation_id"]` |
| Mock | `MockEpisodicMemory.set_cycle_registry` stores the registry and never applies it (BF-938 R1 pattern) |

**Heavier designs rejected (one line each):**
- A recall-time check against the journal or event log: they are pruned after 14 and 7 days (consult Q1).
- A never-pruned id ledger: it grows with every cycle.
- OpenTelemetry: a new dependency for one ContextVar.
- A keyed MAC over the record: considered, deferred as R3.
- Binding inside `perceive`: no reset point, and BaseAgent tools call their own `perceive`.
- Renaming `_run_cognitive_lifecycle`: breaks the `?raw` pin at `test_ad1248_slice_a_crossing.py:573-574`.

## 3. Consumers checked

| Changed | Consumers | Result |
|---|---|---|
| `Episode` fields | `_metadata_to_episode` (about 25 callers, `sif.py:385`, `:447`): new fields read with defaults. `memory_security.py:403-421` (AD-607i redacted copy) and `knowledge/store.py:158-199` (warm boot) drop the record, so those episodes are never judged (R2). BF-938 guard (`test_bf938_episode_source_guard.py:29`, `:166`) reads only `source` and the positional order, and the fields are appended. No router or HXI reads the whole Episode: field picks at `routers/memory_graph.py:282` and `proactive.py:2207`; `asdict(` occurs only in `knowledge/erasure.py:721` (an attachment scan). `procedure_challenger.py:259`: S1 changes no producer's id presence, and the format is unchanged | Additive |
| `Episode.__eq__` | The two new fields use `compare=False` (T1), so an episode read back from a memory equals the one its producer built. The wide run found two tests that compare a stored-and-read episode with another: `test_ad608_retroactive_evolution.py:336` (the evolver is handed the stamped copy) and `test_ad1340_s1_eviction.py:243` (two memories store at different times); both stay green unedited. No `src` code compares whole episodes (the Architect's enumeration found only id-set comparisons, `episodic_mock.py:123`), and a frozen `Episode` with list fields cannot be hashed, so none is a set member or a dict key | Unchanged |
| Unbound `perceive` on a stand-in | `test_bf698_thread_provenance.py` builds a `SimpleNamespace` agent and calls `CognitiveAgent.perceive(agent, ...)` 7 times; `perceive` now calls `self._issue_cycle_id()`, so the stand-in gains `_issue_cycle_id=new_cycle_id` (X7, X8; the wide run found 6 red). `perceive` and `_run_cycle_bound_lifecycle` are the only readers of `_issue_cycle_id` in `src`; `test_bf991_diagnostic_intent_message.py:167` passes a real agent, and the `CognitiveAgent.act` and `.decide` callers do not reach it | Compatible with X7, X8 |
| Metadata keys | `seed()` `:1902` and `_force_update` `:2713` carry them. Archive restore writes the archived metadata verbatim (`:3185`). `update_episode_metadata` `:2469` merges (R3). No test pins an exact key set (section 11) | Additive |
| `validate_provenance` | Three callers (P2). `test_ad607_memory_security.py:200-206` still holds with the default (X1 updates its comment). `test_bf938_ad607_recall_gate.py:168` and `test_bf938_episode_source_guard.py:221` call without a cutoff, so the result is unchanged | Unchanged at default |
| `bind_episodic_memory_gates` | `test_bf984_rebuild_binding.py:90`, `:106` (positional, so the keyword-only default fits). The rebuild fake `test_ad819_rebuild_episodic.py:406-430` gets no registry, so no new setter is called on it. `test_bf938_ad607_binding.py:170-181` checks the setters by name, and a new call keeps it true | Compatible |
| `init_cognitive_services` | `runtime.py:3034`; tests `test_ad1340_s1_erasure.py:1059`, `test_ad600_transactive_memory.py:183`, `test_bf938_ad607_binding.py:83` (keyword default) | Compatible |
| `handle_intent` call sites | `test_bf239_ward_room_engagement_tracking.py` patches `_run_cognitive_lifecycle` with `(self, intent, csi, se)`; the wrapper passes the same three positional arguments. `test_ad1034_cognitive_spine.py:200`, `:221` call the body directly and stay unbound | Compatible |
| `perceive` id | `test_ad492_cognitive_correlation_ids.py:41`, `:52`, `:64` need 12 hex characters, unique per unbound call; the MagicMock runtime at `:210` is ignored by the property | Holds |
| `self._current_correlation_id` | Set in `perceive`, cleared `:8061`, read `:8817` | Unchanged |
| `IntentResult.metadata` | Wire `mesh/intent.py:2171` plus BF-805 pruning (a string of at most 64 characters). `routers/agents.py:2843-2873` picks keys selectively. `test_ad1248_slice_a_crossing.py:245`, `:252`; `test_bf934_s3...:252-255`; `test_ad1357...:762`, `:876` pass no observation `correlation_id`. AD-1248 DD-5: a bounded fact, not payload | Additive |
| `MemorySecurityConfig` | `test_ad1270e2g_crew_models.py:186-191` (X2), its bound table `:272` and the total `:597` (X3, X4), `test_ad1270e1_config_facade.py:1572` (the field count, X5; the oracle found these three pins red, the draft had missed them), `test_ad1152_agentic_correlation.py:346` (a pinned digest of the default dump: its helper pops each added field, X6; the wide run found it red), facade baseline and reference (regenerated), `test_ad607...:161-169` (no field enumeration). `check_config_profiles.py:166-170` manifests only bools, so no row | Regenerated |
| Layers | `tests/test_layer_boundaries.py:145-150`, `:169`: a top-level module is core, importable by every layer | Allowed |

**Not checked:** a live boot, live log or event volume, and anything under `%LOCALAPPDATA%` (section 17).

## 4. Decisions

- **D1 (when).** Store time, once; the verdict is kept on the episode.
- **D2 (against what).** An in-process registry, not the journal (`journal.py:403-405` is best-effort).
- **D3 (which time).** `stored_at` written by `store()`, not `Episode.timestamp`, which the producer sets.
- **D4 (propagation).** A ContextVar. Each cycle binds its own id, and the reset restores the outer id.
- **D5 (work items).** `register()` adopts external ids; S2a uses it.
- **D6 (cutoff).** Ships at 0.0; S3 arms it.
- **D7 (equality).** `stored_at` and `correlation_verdict` use `compare=False`: they are the memory's notes, not episode content, so an episode read back equals the one its producer built (the Architect's ruling on the wide run's findings, 2026-11-21, consult edd29843).
- **G-a.** `empty` is decided before the registry is asked, so an empty id is `empty` even with no registry.
- **G-b.** A registry that raises gives `unchecked` and a WARNING; the store proceeds (log-and-degrade).
- **G-c.** Reasons: `empty` gives `direct_source_missing_correlation_id`; `unresolved` gives `direct_source_unresolved_correlation_id`; any other verdict gives `direct_source_unchecked_correlation_id`.
- **G-d.** The TTL (86,400 s) and size (100,000) are **not measured**. They are constructor arguments with defaults; S3 measures them.
- **G-e.** `_cycle_registry` accepts only a `CycleIdRegistry`. A MagicMock runtime issues a plain id.

## 5. Tests: new file `tests/test_ad1360_s1_cycle_trace.py` (67 cases)

Focused gate at `-n 0`: section 12.

| N | Case (function) | Base | After M1 | After M2 |
|---|---|---|---|---|
| N1-N4 | registry: issued id shape and resolves; TTL boundary; `max_entries`; `register` refresh | collection error | pass | pass |
| N5 | bad arguments raise [8] | error | pass | pass |
| N6 | `judge_correlation_id` cases | error | pass | pass |
| N7-N8 | unbind restores the outer id; a task inherits the id | error | pass | pass |
| N9 | the rule [11] | error | pass | pass |
| N10-N11 | pre-cutoff never flagged [4]; `missing_agent_ids` still first | error | pass | pass |
| N12-N14 | configured cutoff; recall verdict with config; peer episode never judged | error | pass | pass |
| N15-N17 | cutoff ships at 0.0 (default and supported profile); accepted [5]; refused [9] | error | pass | pass |
| N18-N19 | metadata round trip and legacy row; hash invariance | error | pass | pass |
| N20-N23 | real memory: store verdicts and overwrite; no registry gives unchecked; seed keeps; legacy kept when armed | error | pass | pass |
| N24-N27 | binding only when given; startup binds; mock accepts and records nothing; runtime owns and passes | error | **fail** | pass |
| N28-N30 | agent issues from the registry, never a mock; `perceive` takes the bound id; result metadata | error | **fail** | pass |
| N31-N32 | `handle_intent` binds a new id per cycle and restores the outer one [plain, slot]; restored on raise | error | **fail** | pass |
| N33-N34 | **crossing:** a real CognitiveAgent cycle into a real ChromaDB memory gives `resolved`; armed recall keeps it and drops a forged one, with an event | error | **fail** | pass |

After M1: 55 pass, 12 fail. After M2: 67 pass. Existing suites in section 12 stay green.

## 6. What S2a and S2b need from S1 (no redesign)

| Need | S1 API |
|---|---|
| Producer inside a bound cycle | `probos.cycle_trace.current_cycle_id()` at the `Episode(` site |
| Non-cycle entry point (router, shell, NL pipeline, device, MCP, perception, system QA, ground truth) | Inject `runtime.cycle_registry` into the owning service; `token = bind_cycle(registry.issue(kind="<entry>"))`, then `unbind_cycle(token)` in a `finally` |
| Post-cycle producer (proactive) | `IntentResult.metadata["correlation_id"]` |
| Work item (BF-740 pairing stays) | `registry.register(work_item_id, kind="work_item")` at run start and on resume |
| Guard test (S2b) | Verdict constants; `CycleIdRegistry.kind_of`; `_run_cycle_bound_lifecycle` as the bound-cycle entry |
| Sites S1 leaves as they are | `__main__.py:2343` and `crew_synth.py:646` (`**kw`, default `direct`) need a disposition. Other correlation-id generators are not AD-492 ids and are unregistered, so a direct episode carrying one records `unresolved`: `agents/system_qa.py:294` (`qa-`), `dream_adapter.py:190` (`dream-`), `cognitive/ready_room/sessions.py:87`. `thought_store.py:109` writes `reflection`, which is never judged |
| Rebuild command | No registry (`unchecked`); it writes `wardroom_import`, which is never judged |

## 7. The contract

### 7.1 New file `tests/test_ad1360_s1_cycle_trace.py` (M1, written first)

```python
"""AD-1360 S1 (#1828): the AD-492 cycle id is issued into a registry, bound for the cycle and checked once, at store time.

S1 ships with ``security.memory.correlation_cutoff`` at 0.0, so AD-607b judges no episode it did not judge before. The
crossing cases run a real CognitiveAgent cycle into a real ChromaDB-backed EpisodicMemory and recall through AD-607's
verdict.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import contextvars
import dataclasses
import functools
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from probos.cognitive.cognitive_agent import CognitiveAgent, _build_result_metadata
from probos.cognitive.episodic import EpisodicMemory, compute_episode_hash
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.memory_security import (
    configured_correlation_cutoff,
    sanitize_inbound_episode,
    validate_provenance,
    validate_recall_result,
)
from probos.config import MemorySecurityConfig, SystemConfig
from probos.config_profiles import load_profile
from probos.cycle_trace import (
    VERDICT_EMPTY,
    VERDICT_RESOLVED,
    VERDICT_UNCHECKED,
    VERDICT_UNRESOLVED,
    CycleIdRegistry,
    bind_cycle,
    current_cycle_id,
    judge_correlation_id,
    new_cycle_id,
    unbind_cycle,
)
from probos.events import EventType
from probos.startup.cognitive_services import bind_episodic_memory_gates, init_cognitive_services
from probos.types import Episode, EpisodeStoreOutcome, IntentMessage, IntentResult
from tests import test_bf938_ad607_binding as binding
from tests.test_bf239_ward_room_engagement_tracking import _make_agent, _make_ward_room_intent

_ROOT = Path(__file__).resolve().parents[1]
_T0 = 1_700_000_000.0  # long ago, so BF-039's last-hour rate limit and similarity window never see these episodes
_RECORDED = 2_000_000_000.0  # a store time after every cutoff below but the one equal to it
_HEX = frozenset("0123456789abcdef")


def _is_cycle_id(value: object) -> bool:
    return type(value) is str and len(value) == 12 and set(value) <= _HEX


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, event_type: Any, data: dict[str, Any] | None = None) -> None:
        self.events.append((event_type, data or {}))

    def gaps(self) -> dict[str, str]:
        return {
            data.get("episode_id", ""): data.get("reason", "")
            for kind, data in self.events
            if kind == EventType.MEMORY_PROVENANCE_GAP
        }


class _Slots:
    """A concurrency manager that admits every intent: handle_intent's first lifecycle call site."""

    @contextlib.asynccontextmanager
    async def slot(self, intent: str, priority: Any) -> Any:
        yield


def _episode(episode_id: str, *, agent: str = "agent-ad1360", correlation_id: str = "", i: int = 0, **extra: Any) -> Episode:
    return Episode(
        id=episode_id,
        timestamp=_T0 + 600.0 * i,
        user_input=f"the engineering section logged coolant reading {episode_id} within limits",
        agent_ids=[agent],
        source="direct",
        correlation_id=correlation_id,
        outcomes=[{"intent": "report", "success": True}],
        **extra,
    )


def _read_back(em: EpisodicMemory, episode_id: str) -> Episode:
    got = em._collection.get(ids=[episode_id], include=["metadatas", "documents"])
    return EpisodicMemory._metadata_to_episode(got["ids"][0], got["documents"][0], got["metadatas"][0])


@pytest.fixture
async def memory(tmp_path: Path) -> Any:
    em = EpisodicMemory(db_path=str(tmp_path / "episodic.db"), relevance_threshold=0.0)
    await em.start()
    try:
        yield em
    finally:
        await em.stop()


# -- N1 to N8: the registry, the verdict and the binding ------------------------------------------------------------


def test_an_issued_id_is_ad492_shaped_and_resolves_and_a_made_up_one_does_not() -> None:
    registry = CycleIdRegistry()
    chain_id = registry.issue(kind="cognitive_cycle")
    assert _is_cycle_id(chain_id) and _is_cycle_id(new_cycle_id())
    assert registry.resolves(chain_id) is True and registry.kind_of(chain_id) == "cognitive_cycle"
    assert registry.resolves(new_cycle_id()) is False and registry.kind_of("feedfacecafe") == ""
    assert registry.resolves("") is False


def test_an_id_resolves_for_its_ttl_and_not_after() -> None:
    clock = _Clock()
    registry = CycleIdRegistry(ttl_seconds=60.0, clock=clock)
    chain_id = registry.issue(kind="cognitive_cycle")
    clock.now += 60.0
    assert registry.resolves(chain_id) is True  # at the TTL
    clock.now += 0.001
    assert registry.resolves(chain_id) is False and len(registry) == 0


def test_the_oldest_id_is_dropped_past_max_entries() -> None:
    registry = CycleIdRegistry(max_entries=2)
    first, second, third = (registry.issue(kind="cognitive_cycle") for _ in range(3))
    assert [registry.resolves(chain_id) for chain_id in (first, second, third)] == [False, True, True]
    assert len(registry) == 2


def test_register_adopts_an_external_id_and_refreshes_its_ttl() -> None:
    clock = _Clock()
    registry = CycleIdRegistry(ttl_seconds=60.0, clock=clock)
    registry.register("712ebc8d645f", kind="work_item")
    clock.now += 50.0
    registry.register("712ebc8d645f", kind="work_item")  # a resumed run registers again
    clock.now += 50.0
    assert registry.resolves("712ebc8d645f") is True and registry.kind_of("712ebc8d645f") == "work_item"


@pytest.mark.parametrize(
    "build",
    [
        lambda: CycleIdRegistry(ttl_seconds=0.0),
        lambda: CycleIdRegistry(ttl_seconds=-1.0),
        lambda: CycleIdRegistry(ttl_seconds=math.inf),
        lambda: CycleIdRegistry(max_entries=0),
        lambda: CycleIdRegistry().issue(kind=""),
        lambda: CycleIdRegistry().register("", kind="work_item"),
        lambda: CycleIdRegistry().register("712ebc8d645f", kind=" "),
        lambda: bind_cycle(""),
    ],
    ids=["ttl-zero", "ttl-negative", "ttl-inf", "no-entries", "issue-no-kind", "register-no-id", "register-no-kind",
         "bind-empty"],
)
def test_bad_arguments_raise(build: Any) -> None:
    with pytest.raises(ValueError):
        build()


def test_the_store_time_verdict_for_each_case() -> None:
    registry = CycleIdRegistry()
    issued = registry.issue(kind="cognitive_cycle")

    class _Down:
        def resolves(self, chain_id: str) -> bool:
            raise RuntimeError("ad1360: the registry is down")

    assert judge_correlation_id(issued, registry) == VERDICT_RESOLVED
    assert judge_correlation_id("deadbeef0000", registry) == VERDICT_UNRESOLVED
    assert judge_correlation_id("", registry) == VERDICT_EMPTY
    assert judge_correlation_id("   ", registry) == VERDICT_EMPTY
    assert judge_correlation_id("", None) == VERDICT_EMPTY  # an empty id needs no registry
    assert judge_correlation_id(issued, None) == VERDICT_UNCHECKED
    assert judge_correlation_id(issued, _Down()) == VERDICT_UNCHECKED


def test_unbind_puts_back_the_outer_id_and_passes_over_a_used_token() -> None:
    def _body() -> None:
        assert current_cycle_id() == ""
        outer = bind_cycle("aaaaaaaaaaaa")
        inner = bind_cycle("bbbbbbbbbbbb")
        assert current_cycle_id() == "bbbbbbbbbbbb"
        unbind_cycle(inner)
        assert current_cycle_id() == "aaaaaaaaaaaa"
        unbind_cycle(outer)
        assert current_cycle_id() == ""
        unbind_cycle(outer)  # used: passed over (PEP 567 RuntimeError)

    contextvars.copy_context().run(_body)


async def test_a_task_started_inside_a_cycle_reads_its_id() -> None:
    async def _read() -> str:
        return current_cycle_id()

    token = bind_cycle("cccccccccccc")
    try:
        child = asyncio.create_task(_read())
    finally:
        unbind_cycle(token)
    assert await child == "cccccccccccc"  # the task copied the context it was created in
    assert current_cycle_id() == ""


# -- N9 to N17: the rule, its callers and the cutoff ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("cutoff", "stored_at", "verdict", "source", "expected"),
    [
        (0.0, _RECORDED, VERDICT_UNRESOLVED, "direct", (True, "")),
        (_RECORDED, _RECORDED, VERDICT_UNRESOLVED, "direct", (True, "")),
        (_RECORDED + 1.0, _RECORDED, VERDICT_EMPTY, "direct", (True, "")),
        (1.0, 0.0, VERDICT_UNRESOLVED, "direct", (True, "")),
        (1.0, _RECORDED, VERDICT_EMPTY, "secondhand", (True, "")),
        (1.0, _RECORDED, VERDICT_EMPTY, "reflection", (True, "")),
        (1.0, _RECORDED, VERDICT_RESOLVED, "direct", (True, "")),
        (1.0, _RECORDED, VERDICT_EMPTY, "direct", (False, "direct_source_missing_correlation_id")),
        (1.0, _RECORDED, VERDICT_UNRESOLVED, "direct", (False, "direct_source_unresolved_correlation_id")),
        (1.0, _RECORDED, VERDICT_UNCHECKED, "direct", (False, "direct_source_unchecked_correlation_id")),
        (1.0, _RECORDED, "", "direct", (False, "direct_source_unchecked_correlation_id")),
    ],
    ids=["cutoff-off", "at-cutoff", "before-cutoff", "no-record", "secondhand", "reflection", "resolved", "empty",
         "unresolved", "unchecked", "blank-with-time"],
)
def test_the_correlation_rule(
    cutoff: float, stored_at: float, verdict: str, source: str, expected: tuple[bool, str],
) -> None:
    episode = Episode(agent_ids=["agent-a"], source=source, stored_at=stored_at, correlation_verdict=verdict)
    assert validate_provenance(episode, correlation_cutoff=cutoff) == expected


@pytest.mark.parametrize("verdict", ["", VERDICT_EMPTY, VERDICT_UNRESOLVED, VERDICT_UNCHECKED])
def test_a_pre_cutoff_episode_is_never_flagged(verdict: str) -> None:
    """BF-938 retired the rule for every episode then stored; AD-1360 never judges one with no store time."""
    legacy = Episode(agent_ids=["agent-a"], source="direct", correlation_id="", correlation_verdict=verdict)
    for cutoff in (0.0, 1.0, time.time()):
        assert validate_provenance(legacy, correlation_cutoff=cutoff) == (True, "")
    assert validate_provenance(legacy) == (True, "")  # the default a caller with no config passes


def test_missing_agent_ids_is_still_reported_first() -> None:
    episode = Episode(agent_ids=[], source="direct", stored_at=_RECORDED, correlation_verdict=VERDICT_EMPTY)
    assert validate_provenance(episode, correlation_cutoff=1.0) == (False, "missing_agent_ids")


def test_the_configured_cutoff_is_a_finite_positive_number_or_zero() -> None:
    assert configured_correlation_cutoff(None) == 0.0
    assert configured_correlation_cutoff(SimpleNamespace(anchor_mismatch_threshold=0.7)) == 0.0
    assert configured_correlation_cutoff(MagicMock()) == 0.0  # a mocked config never arms the rule
    assert configured_correlation_cutoff(SimpleNamespace(correlation_cutoff=True)) == 0.0
    assert configured_correlation_cutoff(SimpleNamespace(correlation_cutoff=-5.0)) == 0.0
    assert configured_correlation_cutoff(MemorySecurityConfig()) == 0.0
    assert configured_correlation_cutoff(MemorySecurityConfig(correlation_cutoff=5.0)) == 5.0


def test_the_recall_verdict_reports_a_judged_episode_only_with_a_cutoff_config() -> None:
    forged = Episode(
        agent_ids=["agent-a"], source="direct", correlation_id="deadbeef0000",
        stored_at=_RECORDED, correlation_verdict=VERDICT_UNRESOLVED,
    )
    assert validate_recall_result(forged).allowed is True
    assert validate_recall_result(forged, config=MemorySecurityConfig()).allowed is True
    judged = validate_recall_result(forged, config=MemorySecurityConfig(correlation_cutoff=1.0))
    assert judged.allowed is False and judged.anomalies == ("provenance_gap",)


def test_a_peer_episode_is_never_judged_on_its_correlation_id() -> None:
    peer = Episode(
        agent_ids=["peer-agent"], source="direct", user_input="the peer logged a routine reading",
        dag_summary={"classification": "ship"}, correlation_id="peer00000000",
        stored_at=time.time(), correlation_verdict=VERDICT_UNRESOLVED,
    )
    assert sanitize_inbound_episode(peer) == (True, "")


def test_the_cutoff_ships_at_zero_and_nothing_arms_it() -> None:
    for config in (SystemConfig(), load_profile("supported")):
        assert config.security.memory.correlation_cutoff == 0.0
    defaults = MemorySecurityConfig()
    assert (defaults.enforce_recall, defaults.enforce_provenance, defaults.enforce_store) == (False, False, False)


_DEC_1 = datetime(2026, 12, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1796083200, 1796083200.0),
        ("1796083200.5", 1796083200.5),
        ("2026-12-01T00:00:00Z", _DEC_1.timestamp()),
        ("2026-12-01T01:00:00+01:00", _DEC_1.timestamp()),
        (_DEC_1, _DEC_1.timestamp()),
    ],
    ids=["epoch-int", "epoch-string", "iso-z", "iso-offset", "aware-datetime"],
)
def test_the_cutoff_accepts_epoch_seconds_or_an_iso_time_with_an_offset(value: Any, expected: float) -> None:
    assert MemorySecurityConfig(correlation_cutoff=value).correlation_cutoff == pytest.approx(expected)


@pytest.mark.parametrize(
    "value",
    ["2026-12-01T00:00:00", "2026-12-01", "next tuesday", math.inf, math.nan, "inf", -1.0, True, datetime(2026, 12, 1)],
    ids=["naive-iso", "date-only", "words", "inf", "nan", "inf-string", "negative", "bool", "naive-datetime"],
)
def test_the_cutoff_refuses_an_ambiguous_or_impossible_instant(value: Any) -> None:
    with pytest.raises(ValidationError):
        MemorySecurityConfig(correlation_cutoff=value)


# -- N18 to N23: the record, stored and read back -------------------------------------------------------------------


def test_the_record_round_trips_and_a_legacy_row_reads_as_not_recorded() -> None:
    episode = _episode("ad1360-rt", correlation_id="abcdefabcdef", stored_at=_RECORDED, correlation_verdict=VERDICT_RESOLVED)
    metadata = EpisodicMemory._episode_to_metadata(episode)
    assert (metadata["stored_at"], metadata["correlation_verdict"]) == (_RECORDED, VERDICT_RESOLVED)
    back = EpisodicMemory._metadata_to_episode(episode.id, episode.user_input, metadata)
    assert (back.stored_at, back.correlation_verdict) == (_RECORDED, VERDICT_RESOLVED)
    legacy = {key: value for key, value in metadata.items() if key not in ("stored_at", "correlation_verdict")}
    old = EpisodicMemory._metadata_to_episode(episode.id, episode.user_input, legacy)
    assert (old.stored_at, old.correlation_verdict) == (0.0, "")
    garbled = {**metadata, "stored_at": "not a time", "correlation_verdict": 7}
    bad = EpisodicMemory._metadata_to_episode(episode.id, episode.user_input, garbled)
    assert (bad.stored_at, bad.correlation_verdict) == (0.0, "")


def test_the_record_is_not_part_of_the_content_hash() -> None:
    episode = _episode("ad1360-hash", correlation_id="abcdefabcdef")
    recorded = dataclasses.replace(episode, stored_at=_RECORDED, correlation_verdict=VERDICT_UNRESOLVED)
    assert compute_episode_hash(episode) == compute_episode_hash(recorded)
    assert (EpisodicMemory._episode_to_metadata(episode)["content_hash"]
            == EpisodicMemory._episode_to_metadata(recorded)["content_hash"])


async def test_store_records_each_verdict_and_replaces_what_the_producer_set(memory: EpisodicMemory) -> None:
    registry = CycleIdRegistry()
    memory.set_cycle_registry(registry)
    issued = registry.issue(kind="cognitive_cycle")
    cases = {
        "ad1360-resolved": (issued, VERDICT_RESOLVED),
        "ad1360-made-up": ("deadbeef0000", VERDICT_UNRESOLVED),
        "ad1360-empty": ("", VERDICT_EMPTY),
    }
    before = time.time()
    for i, (episode_id, (chain_id, _)) in enumerate(cases.items()):
        producer_record = {"stored_at": 1.0, "correlation_verdict": VERDICT_RESOLVED}  # ignored by store()
        episode = _episode(episode_id, agent=f"agent-{i}", correlation_id=chain_id, i=i, **producer_record)
        assert await memory.store(episode) is EpisodeStoreOutcome.STORED
    after = time.time()
    for episode_id, (_, verdict) in cases.items():
        back = _read_back(memory, episode_id)
        assert back.correlation_verdict == verdict
        assert before <= back.stored_at <= after


async def test_a_store_with_no_registry_bound_records_unchecked(memory: EpisodicMemory) -> None:
    await memory.store(_episode("ad1360-unbound", correlation_id="abcdefabcdef"))
    assert _read_back(memory, "ad1360-unbound").correlation_verdict == VERDICT_UNCHECKED


async def test_seed_keeps_the_record_an_episode_carries(memory: EpisodicMemory) -> None:
    memory.set_cycle_registry(CycleIdRegistry())
    seeded = [
        _episode("ad1360-legacy"),
        _episode("ad1360-carried", correlation_id="abcdefabcdef", i=1, stored_at=_RECORDED,
                 correlation_verdict=VERDICT_RESOLVED),
    ]
    assert await memory.seed(seeded) == 2
    legacy, carried = _read_back(memory, "ad1360-legacy"), _read_back(memory, "ad1360-carried")
    assert (legacy.stored_at, legacy.correlation_verdict) == (0.0, "")
    assert (carried.stored_at, carried.correlation_verdict) == (_RECORDED, VERDICT_RESOLVED)


async def test_an_episode_without_a_record_is_kept_when_the_rule_is_armed(memory: EpisodicMemory) -> None:
    await memory.seed([_episode("ad1360-legacy", agent="agent-legacy")])
    memory.set_security_config(MemorySecurityConfig(enforce_provenance=True, correlation_cutoff=1.0))
    assert [episode.id for episode in await memory.recent_for_agent("agent-legacy", k=5)] == ["ad1360-legacy"]


# -- N24 to N27: the wiring -----------------------------------------------------------------------------------------


def test_the_binding_sets_a_registry_only_when_given_one(tmp_path: Path) -> None:
    config = SystemConfig()
    config.storage_gate.enabled = False
    em = EpisodicMemory(db_path=str(tmp_path / "episodic.db"))
    bind_episodic_memory_gates(em, config, None)  # the rebuild command's call
    assert em._cycle_registry is None
    registry = CycleIdRegistry()
    bind_episodic_memory_gates(em, config, None, cycle_registry=registry)
    assert em._cycle_registry is registry


async def test_startup_binds_the_registry_it_is_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = CycleIdRegistry()
    monkeypatch.setattr(binding, "init_cognitive_services", functools.partial(init_cognitive_services, cycle_registry=registry))
    async with binding._bound(tmp_path, monkeypatch, SystemConfig(), binding._Recorder()) as em:
        assert em._cycle_registry is registry


async def test_the_mock_memory_accepts_the_registry_and_records_nothing() -> None:
    mock = MockEpisodicMemory()
    registry = CycleIdRegistry()
    config = SystemConfig()
    config.storage_gate.enabled = False  # AD-610 is not under test
    bind_episodic_memory_gates(mock, config, None, cycle_registry=registry)
    assert mock._cycle_registry is registry
    episode = _episode("ad1360-mock", correlation_id="deadbeef0000")
    assert await mock.store(episode) is EpisodeStoreOutcome.STORED
    assert mock._episodes == [episode]  # stored as given: the mock applies no AD-607 control and records nothing


async def test_the_runtime_owns_one_registry_and_passes_it_to_startup(tmp_path: Path) -> None:
    from probos.runtime import ProbOSRuntime

    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    assert isinstance(runtime.cycle_registry, CycleIdRegistry)
    tree = ast.parse((_ROOT / "src" / "probos" / "runtime.py").read_text(encoding="utf-8"))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "init_cognitive_services"
    ]
    assert len(calls) == 1  # premise: the one startup call
    assert {kw.arg: ast.unparse(kw.value) for kw in calls[0].keywords}.get("cycle_registry") == "self.cycle_registry"


# -- N28 to N32: the agent ------------------------------------------------------------------------------------------


def test_the_agent_issues_from_the_runtime_registry_and_never_from_a_mock() -> None:
    agent = _make_agent()
    registry = CycleIdRegistry()
    agent._runtime = SimpleNamespace(cycle_registry=registry)
    issued = agent._issue_cycle_id()
    assert registry.resolves(issued) and registry.kind_of(issued) == "cognitive_cycle"
    for runtime in (MagicMock(), None):  # a test runtime's attribute is not a registry
        agent._runtime = runtime
        assert _is_cycle_id(agent._issue_cycle_id())


async def test_perceive_takes_the_bound_id_and_issues_one_when_none_is_bound() -> None:
    agent = _make_agent()
    intent = IntentMessage(intent="direct_message", params={"text": "status"})
    token = bind_cycle("feedfacecafe")
    try:
        bound = await agent.perceive(intent)
    finally:
        unbind_cycle(token)
    assert bound["correlation_id"] == "feedfacecafe" == agent._current_correlation_id
    unbound = await agent.perceive(intent)
    assert _is_cycle_id(unbound["correlation_id"]) and unbound["correlation_id"] != "feedfacecafe"


def test_the_result_metadata_carries_the_cycle_id_as_a_bounded_fact() -> None:
    assert _build_result_metadata({}, {}, {"correlation_id": "abcdefabcdef"}) == {"correlation_id": "abcdefabcdef"}
    assert _build_result_metadata({}, {}, {}) == {}
    assert _build_result_metadata({}, {}, {"correlation_id": ""}) == {}
    assert _build_result_metadata({}, {}, {"correlation_id": 7}) == {}
    assert _build_result_metadata({}, {}, {"correlation_id": "x" * 100})["correlation_id"] == "x" * 64


@pytest.mark.parametrize("slots", [False, True], ids=["plain", "concurrency-slot"])
async def test_handle_intent_binds_a_new_id_for_each_cycle_and_puts_back_the_outer_one(slots: bool) -> None:
    seen: list[str] = []

    async def _lifecycle(self: Any, intent: Any, csi: Any = None, se: Any = None) -> IntentResult:
        seen.append(current_cycle_id())
        return IntentResult(intent_id=intent.id, agent_id=self.id, success=True, result="ok")

    agent = _make_agent()
    if slots:
        agent._concurrency_manager = _Slots()
    outer = bind_cycle("0123456789ab")
    try:
        with patch.object(type(agent), "_run_cognitive_lifecycle", _lifecycle):
            for thread_id in ("thread-ad1360-a", "thread-ad1360-b"):
                await agent.handle_intent(_make_ward_room_intent(thread_id))
        assert current_cycle_id() == "0123456789ab"
    finally:
        unbind_cycle(outer)
    assert len(seen) == 2 and seen[0] != seen[1]
    assert all(_is_cycle_id(chain_id) and chain_id != "0123456789ab" for chain_id in seen)


async def test_the_cycle_id_is_put_back_when_the_lifecycle_raises() -> None:
    async def _raises(self: Any, intent: Any, csi: Any = None, se: Any = None) -> IntentResult:
        assert _is_cycle_id(current_cycle_id())
        raise RuntimeError("ad1360: the lifecycle failed")

    agent = _make_agent()
    with patch.object(type(agent), "_run_cognitive_lifecycle", _raises):
        with pytest.raises(RuntimeError, match="ad1360"):
            await agent.handle_intent(_make_ward_room_intent("thread-ad1360-raise"))
    assert current_cycle_id() == ""


# -- N33, N34: crossing, from a real cycle to the stored record and an armed recall ---------------------------------


class _CycleAgent(CognitiveAgent):
    """A real CognitiveAgent whose model steps are stubbed (test_ad1034_cognitive_spine's pattern): the real perceive,
    lifecycle and AD-430c episode write run."""

    agent_type = "ad1360_test"
    instructions = "AD-1360 cycle test agent."

    async def _recall_relevant_memories(self, intent: Any, observation: dict) -> dict:
        return observation

    async def decide(self, observation: dict) -> dict:
        return {"llm_output": ""}

    async def act(self, decision: dict) -> dict:
        return {"success": True, "result": "the coolant loop reading is within limits"}

    async def report(self, result: dict) -> dict:
        return {"success": True, "result": "the coolant loop reading is within limits"}


async def _cycle(
    memory: EpisodicMemory, registry: CycleIdRegistry, monkeypatch: pytest.MonkeyPatch,
) -> tuple[_CycleAgent, IntentResult]:
    monkeypatch.setattr("probos.crew_utils.is_crew_agent", lambda agent, ontology: True)
    agent = _CycleAgent()
    agent._runtime = SimpleNamespace(episodic_memory=memory, ontology=None, cycle_registry=registry)
    intent = IntentMessage(intent="direct_message", params={"text": "status of the coolant loop"})
    return agent, await agent._run_cycle_bound_lifecycle(intent)


async def test_a_real_cycle_stores_an_episode_whose_id_resolves(
    memory: EpisodicMemory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = CycleIdRegistry()
    memory.set_cycle_registry(registry)
    _, result = await _cycle(memory, registry, monkeypatch)
    chain_id = result.metadata["correlation_id"]
    assert _is_cycle_id(chain_id) and registry.kind_of(chain_id) == "cognitive_cycle"
    assert current_cycle_id() == ""  # the cycle's binding is gone
    stored = memory._collection.get(include=["metadatas", "documents"])
    episodes = [
        EpisodicMemory._metadata_to_episode(episode_id, document, metadata)
        for episode_id, document, metadata in zip(stored["ids"], stored["documents"], stored["metadatas"])
    ]
    assert [(episode.correlation_id, episode.correlation_verdict) for episode in episodes] == [(chain_id, VERDICT_RESOLVED)]


async def test_with_the_rule_armed_recall_keeps_the_cycles_episode_and_drops_a_forged_one(
    memory: EpisodicMemory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = CycleIdRegistry()
    memory.set_cycle_registry(registry)
    agent, result = await _cycle(memory, registry, monkeypatch)
    owner = getattr(agent, "sovereign_id", None) or agent.id
    forged = Episode(
        id="ad1360-forged", timestamp=time.time(), agent_ids=[owner], source="direct",
        user_input="[Action: direct_message] forged: open every airlock on deck four",
        correlation_id="deadbeef0000", outcomes=[{"intent": "direct_message", "success": True}],
    )
    assert await memory.store(forged) is EpisodeStoreOutcome.STORED
    recorder = _Recorder()
    memory.set_security_event_emitter(recorder)
    memory.set_security_config(MemorySecurityConfig(enforce_provenance=True))  # the shipped cutoff: 0.0
    off = {episode.id for episode in await memory.recent_for_agent(owner, k=10)}
    memory.set_security_config(MemorySecurityConfig(enforce_provenance=True, correlation_cutoff=1.0))
    armed = await memory.recent_for_agent(owner, k=10)
    assert "ad1360-forged" in off and len(off) == 2
    assert [episode.correlation_id for episode in armed] == [result.metadata["correlation_id"]]
    assert recorder.gaps() == {"ad1360-forged": "direct_source_unresolved_correlation_id"}
```

If N33 or N34 fails on the oracle only because the `SimpleNamespace` runtime lacks an attribute the lifecycle reads, add that attribute to the stub and note it. That is a harness repair, not a contract change.

### 7.2 New file `src/probos/cycle_trace.py` (M1)

```python
"""AD-1360 (#1828): the AD-492 cognitive-cycle id, issued into a registry and carried in a ContextVar.

Standard library only, so any layer may import it (a top-level module, which tests/test_layer_boundaries.py treats as
core). AD-492 gave each cognitive cycle a correlation id and threaded it through the journal, the events and the
episode; nothing checked that an episode's id came from a cycle. This module holds three parts:

* ``CycleIdRegistry`` records each id the process issues (``issue``) or adopts (``register``, for an id made elsewhere,
  such as a work item's), bounded by a TTL and a size. Neither bound is measured; both are constructor arguments
  (AD-1360 S3's replay measures them).
* ``judge_correlation_id`` is the verdict ``EpisodicMemory.store()`` records on each episode.
* ``CURRENT_CYCLE_ID`` carries the bound id. An awaited coroutine runs in its caller's context and a task copies the
  context it was created in (PEP 567), so code inside a bound cycle reads the id without a parameter. ``bind_cycle``
  returns the token ``unbind_cycle`` resets in a ``finally``, as ``admission/carrier.py`` does for the work ticket.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from contextvars import ContextVar, Token
from typing import Final, Protocol

logger = logging.getLogger(__name__)

#: Created at module level, as the contextvars documentation asks. "" = no cycle is bound.
CURRENT_CYCLE_ID: Final[ContextVar[str]] = ContextVar("probos_cycle_id", default="")

#: The verdicts EpisodicMemory.store() records in Episode.correlation_verdict. The field's default "" means not
#: recorded: an episode stored before AD-1360, seeded or restored.
VERDICT_RESOLVED: Final = "resolved"
VERDICT_UNRESOLVED: Final = "unresolved"
VERDICT_EMPTY: Final = "empty"
VERDICT_UNCHECKED: Final = "unchecked"

#: Not measured: one day, so a cycle that stores its episode within a day of its start resolves.
DEFAULT_TTL_SECONDS: Final = 86_400.0
#: Not measured: the most ids held at once; the oldest is dropped past it.
DEFAULT_MAX_ENTRIES: Final = 100_000


def new_cycle_id() -> str:
    """A new id in AD-492's format: twelve hex characters of a random UUID."""
    return uuid.uuid4().hex[:12]


def current_cycle_id() -> str:
    """The id bound in this context, or "" when no cycle is bound."""
    return CURRENT_CYCLE_ID.get()


def bind_cycle(chain_id: str) -> Token[str]:
    """Bind ``chain_id`` for the work this context runs next; reset it with ``unbind_cycle`` in a ``finally``."""
    if type(chain_id) is not str or not chain_id:
        raise ValueError("bind_cycle needs a non-empty id")
    return CURRENT_CYCLE_ID.set(chain_id)


def unbind_cycle(token: Token[str]) -> None:
    """Put back the id bound before ``bind_cycle``.

    Raises no Exception: a token already used, or one another context created, is passed over (ContextVar.reset raises
    RuntimeError or ValueError, PEP 567).
    """
    try:
        CURRENT_CYCLE_ID.reset(token)
    except (RuntimeError, ValueError):
        pass


class CycleIdResolver(Protocol):
    """What EpisodicMemory.store() needs: whether an id was issued or adopted and has not expired."""

    def resolves(self, chain_id: str) -> bool: ...


def _require_kind(kind: str) -> None:
    if type(kind) is not str or not kind.strip():
        raise ValueError("a cycle id needs a non-empty kind")


class CycleIdRegistry:
    """The ids this process issued or adopted, each held for ``ttl_seconds`` and at most ``max_entries`` at once.

    In memory: a restart forgets every id, so an episode stored after a restart for a cycle begun before it records
    "unresolved". Thread-safe. ``clock`` is monotonic by default, so a wall-clock step expires nothing.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)):
            raise ValueError("ttl_seconds must be a number")
        if not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be finite and above 0")
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError("max_entries must be an int of at least 1")
        self._ttl = float(ttl_seconds)
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = threading.Lock()

    def issue(self, *, kind: str) -> str:
        """Record and return a new id; ``kind`` names the entry point that issued it ("cognitive_cycle")."""
        _require_kind(kind)
        chain_id = new_cycle_id()
        self._record(chain_id, kind)
        return chain_id

    def register(self, chain_id: str, *, kind: str) -> None:
        """Adopt an id made elsewhere (a work item's), or refresh one already held: it resolves for another TTL."""
        if type(chain_id) is not str or not chain_id.strip():
            raise ValueError("register needs a non-empty id")
        _require_kind(kind)
        self._record(chain_id, kind)

    def resolves(self, chain_id: str) -> bool:
        """True while ``chain_id`` is held and no older than the TTL."""
        return self._live_entry(chain_id) is not None

    def kind_of(self, chain_id: str) -> str:
        """The kind an id was recorded with, or "" when it does not resolve."""
        entry = self._live_entry(chain_id)
        return entry[1] if entry is not None else ""

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _record(self, chain_id: str, kind: str) -> None:
        now = self._clock()
        with self._lock:
            self._entries[chain_id] = (now, kind)
            self._entries.move_to_end(chain_id)
            self._evict(now)

    def _live_entry(self, chain_id: str) -> tuple[float, str] | None:
        if type(chain_id) is not str or not chain_id:
            return None
        now = self._clock()
        with self._lock:
            self._evict(now)
            return self._entries.get(chain_id)

    def _evict(self, now: float) -> None:
        # Entries are in recording order and share one TTL, so the expired ones and the oldest are at the front.
        while self._entries:
            oldest_id, (recorded_at, _kind) = next(iter(self._entries.items()))
            if now - recorded_at <= self._ttl and len(self._entries) <= self._max_entries:
                return
            del self._entries[oldest_id]


def judge_correlation_id(chain_id: str, resolver: CycleIdResolver | None) -> str:
    """The verdict EpisodicMemory.store() records for an episode's correlation id.

    "empty" for no id (no registry is needed to say so); "unchecked" when no registry is bound or it raises (logged at
    WARNING; the store goes on); otherwise "resolved" or "unresolved".
    """
    if type(chain_id) is not str or not chain_id.strip():
        return VERDICT_EMPTY
    if resolver is None:
        return VERDICT_UNCHECKED
    try:
        return VERDICT_RESOLVED if resolver.resolves(chain_id) is True else VERDICT_UNRESOLVED
    except Exception:
        logger.warning("AD-1360: the cycle-id registry failed on %r; the episode records unchecked", chain_id, exc_info=True)
        return VERDICT_UNCHECKED
```

### 7.3 `src/probos/types.py` (M1)

**T1.** SEARCH:
```
    affect_salience: float = 0.0
```
REPLACE:
```
    affect_salience: float = 0.0
    # AD-1360 (#1828): the record AD-607b's correlation rule reads, written by EpisodicMemory.store() and nowhere else
    # (a producer's values are replaced). stored_at is the primary write's epoch time; correlation_verdict is what the
    # cycle-id registry said of correlation_id then: "resolved", "unresolved", "empty" or "unchecked"
    # (probos.cycle_trace). 0.0 and "" = not recorded (stored before AD-1360, seeded or restored): never judged.
    # Neither is in compute_episode_hash, like correlation_id (BF-740), so no stored hash changes.
    # Not compared either: an episode read back from a memory equals the one its producer built.
    stored_at: float = field(default=0.0, compare=False)
    correlation_verdict: str = field(default="", compare=False)
```
**T2.** SEARCH:
```
    # here, and they are bounded and versioned so this cannot become a second
    # body channel. See ``prompts/ad-1248-dm-reply-value.md`` DD-5.
    metadata: dict[str, Any] = field(default_factory=dict)
```
REPLACE:
```
    # here, and they are bounded and versioned so this cannot become a second
    # body channel. See ``prompts/ad-1248-dm-reply-value.md`` DD-5.
    # AD-1360 (#1828): a cognitive cycle's result also carries ``correlation_id``,
    # the cycle's AD-492 id (at most 64 characters), for a caller that stores an
    # episode after the cycle has ended.
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 7.4 `src/probos/cognitive/memory_security.py` (M1)

**S1.** SEARCH:
```
import logging
import re
import time as _time
```
REPLACE:
```
import logging
import math
import re
import time as _time
```
**S2.** SEARCH:
```
from probos.types import Episode, MemorySource
```
REPLACE:
```
from probos.cycle_trace import VERDICT_EMPTY, VERDICT_RESOLVED, VERDICT_UNRESOLVED
from probos.types import Episode, MemorySource
```
**S3.** SEARCH:
```
def validate_provenance(episode: Episode) -> tuple[bool, str]:
```
REPLACE:
```
# AD-1360 (#1828): the reason AD-607b returns for a judged episode's recorded verdict. A verdict this map does not name
# ("unchecked", or "" on an episode that has a store time) returns direct_source_unchecked_correlation_id.
_CORRELATION_REASONS: dict[str, str] = {
    VERDICT_EMPTY: "direct_source_missing_correlation_id",
    VERDICT_UNRESOLVED: "direct_source_unresolved_correlation_id",
}
_UNCHECKED_CORRELATION_REASON = "direct_source_unchecked_correlation_id"


def configured_correlation_cutoff(config: Any) -> float:
    """AD-1360 (#1828): the ``correlation_cutoff`` a recall config sets, or 0.0, which judges nothing.

    0.0 for no config, a config without the field (a test's namespace), a bool, or a value that is not a finite
    positive number, so a mocked config never arms the rule.
    """
    value = getattr(config, "correlation_cutoff", 0.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    cutoff = float(value)
    return cutoff if math.isfinite(cutoff) and cutoff > 0.0 else 0.0


def validate_provenance(episode: Episode, *, correlation_cutoff: float = 0.0) -> tuple[bool, str]:
```
**S4.** SEARCH:
```
    Reason is empty when provenance is intact; otherwise ``missing_agent_ids`` or ``unknown_source:<source>``.
    BF-938 (#1680) retired a third reason, ``direct_source_missing_correlation_id``, on the Captain's decision of
    2026-11-18. AD-1360 (#1828) restores it as a check that the id resolves to an AD-492 chain, for episodes written
    after a cutoff.
```
REPLACE:
```
    Reason is empty when provenance is intact; otherwise ``missing_agent_ids``, ``unknown_source:<source>``, or, for a
    ``direct`` episode stored strictly after ``correlation_cutoff`` (epoch seconds; the default 0.0 judges none),
    ``direct_source_missing_correlation_id``, ``direct_source_unresolved_correlation_id`` or
    ``direct_source_unchecked_correlation_id`` (AD-1360, #1828).
```
**S5.** SEARCH:
```
    # BF-938 (#1680), the Captain's decision of 2026-11-18 (option A): a direct episode with no AD-492 correlation id
    # is no longer a provenance gap. The rule checked only that the id was non-empty, most direct producers set none
    # (704 of 1,227 live episodes, 2026-10-27), and armed it would have dropped 71% of crew recall. The retirement is
    # temporary: AD-1360 (#1828) restores it as a check that the id resolves, for episodes written after a cutoff.
    return True, ""  # BF-938: no correlation-id rule until AD-1360 (#1828)
```
REPLACE:
```
    # BF-938 (#1680) retired the rule that a direct episode carries a correlation id (the Captain's decision of
    # 2026-11-18): it checked only that the id was non-empty, and most direct producers set none. AD-1360 (#1828)
    # restores it on the record EpisodicMemory.store() writes: the store time and whether the id resolved in the
    # cycle-id registry then. Only a direct episode stored strictly after the cutoff is judged, so an episode with no
    # record (stored before AD-1360, seeded or restored; stored_at 0.0) is never flagged, and with the cutoff at 0.0
    # no episode is.
    if correlation_cutoff > 0.0 and source == MemorySource.DIRECT.value:
        stored_at = getattr(episode, "stored_at", 0.0)
        if isinstance(stored_at, (int, float)) and stored_at > correlation_cutoff:
            verdict = getattr(episode, "correlation_verdict", "")
            if verdict != VERDICT_RESOLVED:
                return False, _CORRELATION_REASONS.get(verdict, _UNCHECKED_CORRELATION_REASON)
    return True, ""
```
**S6.** SEARCH:
```
    ok, reason = validate_provenance(episode)
    if not ok:
        anomalies.append("missing_agent_ids" if reason == "missing_agent_ids" else "provenance_gap")
```
REPLACE:
```
    ok, reason = validate_provenance(episode, correlation_cutoff=configured_correlation_cutoff(config))
    if not ok:
        anomalies.append("missing_agent_ids" if reason == "missing_agent_ids" else "provenance_gap")
```

### 7.5 `src/probos/config_models/crew.py` (M1)

**C1.** SEARCH:
```
from collections.abc import Iterable
```
REPLACE:
```
import math
from collections.abc import Iterable
from datetime import datetime
```
**C2.** SEARCH:
```
    anchor_mismatch_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    dp_min_cohort_size: int = Field(default=3, ge=1)
```
REPLACE:
```
    anchor_mismatch_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    dp_min_cohort_size: int = Field(default=3, ge=1)
    # AD-1360 (#1828): 0.0 ships the correlation rule off; AD-1360 S3 sets it in the supported profile after the replay.
    correlation_cutoff: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "AD-1360: AD-607b judges a direct episode's AD-492 correlation id only when the episode was stored "
            "strictly after this instant (epoch seconds, or an ISO-8601 time with a UTC offset). 0.0: never judged."
        ),
    )

    @field_validator("correlation_cutoff", mode="before")
    @classmethod
    def _correlation_cutoff_instant(cls, value: object) -> object:
        """AD-1360: epoch seconds or an ISO-8601 time with an offset; never a bool, a naive time or a non-finite value."""
        if isinstance(value, bool):
            raise ValueError("correlation_cutoff is epoch seconds or an ISO-8601 time, not a bool")
        if isinstance(value, str):
            text = value.strip()
            try:
                value = float(text)
            except ValueError:
                try:
                    value = datetime.fromisoformat(text)
                except ValueError as exc:
                    raise ValueError(f"correlation_cutoff is neither epoch seconds nor an ISO-8601 time: {text!r}") from exc
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("correlation_cutoff needs a UTC offset, for example 2026-12-01T00:00:00+00:00")
            return value.timestamp()
        if isinstance(value, (int, float)) and not math.isfinite(value):
            raise ValueError("correlation_cutoff must be finite")
        return value
```

### 7.6 `src/probos/cognitive/episodic.py` (M1)

**E1.** SEARCH:
```
from probos.admission.seam import check_at
from probos.admission.taxonomy import EFFECT_STORE_WRITE
```
REPLACE:
```
from probos.admission.seam import check_at
from probos.admission.taxonomy import EFFECT_STORE_WRITE
from probos.cycle_trace import CycleIdResolver, judge_correlation_id  # AD-1360 (#1828)
```
**E2.** SEARCH:
```
        are swallowed so security-event emission never breaks the memory path.
        """
        self._security_event_emitter = emitter
```
REPLACE:
```
        are swallowed so security-event emission never breaks the memory path.
        """
        self._security_event_emitter = emitter

    def set_cycle_registry(self, registry: CycleIdResolver | None) -> None:
        """AD-1360 (#1828): the registry ``store()`` checks an episode's AD-492 correlation id against."""
        self._cycle_registry = registry
```
**E3.** SEARCH:
```
        self._security_event_emitter: Any = None  # AD-607: emit hook for security events
        self._store_write_lock = asyncio.Lock()
```
REPLACE:
```
        self._security_event_emitter: Any = None  # AD-607: emit hook for security events
        self._cycle_registry: CycleIdResolver | None = None  # AD-1360 (#1828): bound by set_cycle_registry
        self._store_write_lock = asyncio.Lock()
```
**E4.** SEARCH:
```
            # Provenance-specific event (separate audit channel)
            ok, reason = validate_provenance(episode)
```
REPLACE:
```
            # Provenance-specific event (separate audit channel). AD-1360 (#1828): judged with the cutoff the verdict
            # above used, so the event names the reason that fired.
            from probos.cognitive.memory_security import configured_correlation_cutoff

            ok, reason = validate_provenance(episode, correlation_cutoff=configured_correlation_cutoff(config))
```
**E5.** SEARCH:
```
            metadata = self._episode_to_metadata(episode)
            document = self._prepare_document(episode)
```
REPLACE:
```
            # AD-1360 (#1828): the record AD-607b's correlation rule reads, written here and nowhere else; whatever the
            # producer set is replaced. The id is checked once, now, against the bound cycle-id registry ("unchecked"
            # when none is bound, so a missing binding shows on the record instead of passing).
            episode = dataclasses.replace(
                episode,
                stored_at=time.time(),
                correlation_verdict=judge_correlation_id(
                    episode.correlation_id, getattr(self, "_cycle_registry", None),
                ),
            )
            metadata = self._episode_to_metadata(episode)
            document = self._prepare_document(episode)
```
**E6.** SEARCH:
```
            # AD-979f: affective-salience retrieval slot (0.0 = neutral)
            "affect_salience": float(ep.affect_salience),
        }
```
REPLACE:
```
            # AD-979f: affective-salience retrieval slot (0.0 = neutral)
            "affect_salience": float(ep.affect_salience),
            # AD-1360 (#1828): the store-time record (store() writes it; seed() and _force_update keep what the
            # episode carries). Not in compute_episode_hash, so no stored hash changes.
            "stored_at": float(ep.stored_at),
            "correlation_verdict": ep.correlation_verdict or "",
        }
```
**E7.** SEARCH:
```
        # AD-979f: affective-salience slot (pre-979f episodes lack the key -> 0.0).
        try:
            affect_salience = float(metadata.get("affect_salience", 0.0))
        except (TypeError, ValueError):
            affect_salience = 0.0
        return Episode(
```
REPLACE:
```
        # AD-979f: affective-salience slot (pre-979f episodes lack the key -> 0.0).
        try:
            affect_salience = float(metadata.get("affect_salience", 0.0))
        except (TypeError, ValueError):
            affect_salience = 0.0
        # AD-1360 (#1828): the store-time record. A row stored before AD-1360 lacks both keys and reads (0.0, ""),
        # which AD-607b never judges.
        try:
            stored_at = float(metadata.get("stored_at", 0.0) or 0.0)
        except (TypeError, ValueError):
            stored_at = 0.0
        correlation_verdict = metadata.get("correlation_verdict", "")
        if not isinstance(correlation_verdict, str):
            correlation_verdict = ""
        return Episode(
```
**E8.** SEARCH:
```
            # AD-979f: affective-salience retrieval slot
            affect_salience=affect_salience,
        )
```
REPLACE:
```
            # AD-979f: affective-salience retrieval slot
            affect_salience=affect_salience,
            stored_at=stored_at,  # AD-1360 (#1828)
            correlation_verdict=correlation_verdict,  # AD-1360 (#1828)
        )
```

### 7.7 `src/probos/cognitive/episodic_mock.py` (M1)

**K1.** SEARCH:
```
        self._security_event_emitter: Any = None
        self._store_write_lock = asyncio.Lock()
```
REPLACE:
```
        self._security_event_emitter: Any = None
        self._cycle_registry: Any = None  # AD-1360: stored and never applied, as the AD-607 slots above
        self._store_write_lock = asyncio.Lock()
```
**K2.** SEARCH:
```
    def set_security_event_emitter(self, emitter: Any) -> None:
        """AD-607 (BF-938 R1): stored and never called; the mock emits no security event."""
        self._security_event_emitter = emitter
```
REPLACE:
```
    def set_security_event_emitter(self, emitter: Any) -> None:
        """AD-607 (BF-938 R1): stored and never called; the mock emits no security event."""
        self._security_event_emitter = emitter

    def set_cycle_registry(self, registry: Any) -> None:
        """AD-1360 (#1828): stored and never applied; the mock records no correlation verdict."""
        self._cycle_registry = registry
```

### 7.8 `tests/test_ad607_memory_security.py` (M1)

**X1.** SEARCH:
```
        # BF-938 (#1680): this pinned "fails" (direct_source_missing_correlation_id). The Captain retired that rule on
        # 2026-11-18 until AD-1360 (#1828) restores it as a check that the id resolves to an AD-492 chain.
```
REPLACE:
```
        # BF-938 (#1680): this pinned "fails" (direct_source_missing_correlation_id). The Captain retired that rule on
        # 2026-11-18. AD-1360 (#1828) restores it only for a direct episode stored after
        # security.memory.correlation_cutoff, which defaults to 0.0 (judges none), so with no cutoff this still passes
        # (tests/test_ad1360_s1_cycle_trace.py).
```

### 7.9 `tests/test_ad1270e2g_crew_models.py` (M1)

**X2.** SEARCH:
```
                                'enforce_store': False,
                                'anchor_mismatch_threshold': 0.7,
                                'dp_min_cohort_size': 3},
```
REPLACE:
```
                                'enforce_store': False,
                                'anchor_mismatch_threshold': 0.7,
                                'dp_min_cohort_size': 3,
                                # AD-1360 (#1828): added after the move; 0.0 judges no episode.
                                'correlation_cutoff': 0.0},
```

**X3.** SEARCH:
```
    "MemorySecurityConfig": 3,
```
REPLACE:
```
    "MemorySecurityConfig": 4,  # AD-1360 (#1828): correlation_cutoff (ge 0.0)
```
**X4.** SEARCH:
```
    assert sum(EXPECTED_BOUND_COUNTS.values()) == 30
```
REPLACE:
```
    assert sum(EXPECTED_BOUND_COUNTS.values()) == 31  # AD-1360 (#1828): MemorySecurityConfig 3 -> 4
```

### 7.10 `tests/test_ad1270e1_config_facade.py` (M1)

**X5.** SEARCH:
```
    assert counts["field_definitions"] == 1885  # AD-1206 intentionally adds github_repository.
```
REPLACE:
```
    # AD-1360 (#1828) adds security.memory.correlation_cutoff (1885 -> 1886).
    assert counts["field_definitions"] == 1886  # AD-1206 intentionally adds github_repository.
```

### 7.11 `tests/test_ad1152_agentic_correlation.py` (M1)

**X6.** SEARCH:
```
    assert config["records"].pop("git_last_commit_warn_hours") == 24.0
```
REPLACE:
```
    assert config["records"].pop("git_last_commit_warn_hours") == 24.0
    # AD-1360's inert correlation cutoff (0.0 judges no episode) was added to the memory-security section after this
    # capture too.
    assert config["security"]["memory"].pop("correlation_cutoff") == 0.0
```

### 7.12 `src/probos/startup/cognitive_services.py` (M2)

**B1.** SEARCH:
```
    from probos.consensus.trust import TrustNetwork
    from probos.mesh.intent import IntentBus
```
REPLACE:
```
    from probos.consensus.trust import TrustNetwork
    from probos.cycle_trace import CycleIdResolver
    from probos.mesh.intent import IntentBus
```
**B2.** SEARCH:
```
def bind_episodic_memory_gates(
    episodic_memory: Any,
    config: "SystemConfig",
    emit_event_fn: Callable[..., Any] | None,
) -> None:
```
REPLACE:
```
def bind_episodic_memory_gates(
    episodic_memory: Any,
    config: "SystemConfig",
    emit_event_fn: Callable[..., Any] | None,
    *,
    cycle_registry: "CycleIdResolver | None" = None,
) -> None:
```
**B3.** SEARCH:
```
    episodic_memory.set_security_event_emitter(emit_event_fn)
    logger.info("AD-607: memory security config, store gate and event emitter bound to EpisodicMemory (BF-938)")
```
REPLACE:
```
    episodic_memory.set_security_event_emitter(emit_event_fn)
    logger.info("AD-607: memory security config, store gate and event emitter bound to EpisodicMemory (BF-938)")
    # AD-1360 (#1828): the cycle-id registry store() checks a correlation id against, bound only when given. The
    # rebuild command passes none, so its episodes record "unchecked"; it writes wardroom_import, which AD-607b never
    # judges.
    if cycle_registry is not None:
        episodic_memory.set_cycle_registry(cycle_registry)
```
**B4.** SEARCH:
```
    emit_event_fn: Callable[..., Any] | None = None,
    ontology: Any = None,  # BF-118: for OrientationService
) -> CognitiveServicesResult:
```
REPLACE:
```
    emit_event_fn: Callable[..., Any] | None = None,
    ontology: Any = None,  # BF-118: for OrientationService
    cycle_registry: "CycleIdResolver | None" = None,  # AD-1360 (#1828): the runtime's registry
) -> CognitiveServicesResult:
```
**B5.** SEARCH:
```
        bind_episodic_memory_gates(episodic_memory, config, emit_event_fn)
```
REPLACE:
```
        bind_episodic_memory_gates(episodic_memory, config, emit_event_fn, cycle_registry=cycle_registry)
```

### 7.13 `src/probos/runtime.py` (M2)

**R1.** SEARCH:
```
from probos.agent_onboarding import AgentOnboardingService
from probos.crew_utils import is_crew_agent
from probos.dream_adapter import DreamAdapter
```
REPLACE:
```
from probos.agent_onboarding import AgentOnboardingService
from probos.crew_utils import is_crew_agent
from probos.cycle_trace import CycleIdRegistry  # AD-1360 (#1828)
from probos.dream_adapter import DreamAdapter
```
**R2.** SEARCH:
```
    crew_session_delivery_listener: Callable[..., Any] | None
    cognitive_journal: CognitiveJournal | None
```
REPLACE:
```
    crew_session_delivery_listener: Callable[..., Any] | None
    cognitive_journal: CognitiveJournal | None
    cycle_registry: CycleIdRegistry  # AD-1360 (#1828): the AD-492 ids this process issued
```
**R3.** SEARCH:
```
        # --- Cognitive Journal (AD-431) ---
        self.cognitive_journal: CognitiveJournal | None = None
```
REPLACE:
```
        # --- Cognitive Journal (AD-431) ---
        self.cognitive_journal: CognitiveJournal | None = None

        # --- Cycle-id registry (AD-1360, #1828) ---
        # The AD-492 ids this process issued, which EpisodicMemory.store() checks an episode's correlation id
        # against. In memory and bounded; its TTL and size are CycleIdRegistry's unmeasured defaults.
        self.cycle_registry: CycleIdRegistry = CycleIdRegistry()
```
**R4.** SEARCH:
```
            emit_event_fn=self._emit_event,
            ontology=self.ontology,  # BF-118
        )
```
REPLACE:
```
            emit_event_fn=self._emit_event,
            ontology=self.ontology,  # BF-118
            cycle_registry=self.cycle_registry,  # AD-1360 (#1828)
        )
```

### 7.14 `src/probos/cognitive/cognitive_agent.py` (M2)

**A1.** SEARCH:
```
from probos.admission.seam import hold_at, shadow_at  # AD-1346 M3c; hold_at: AD-1346 M3d2
from probos.events import EventType, SensoriumBudgetExceededEvent
```
REPLACE:
```
from probos.admission.seam import hold_at, shadow_at  # AD-1346 M3c; hold_at: AD-1346 M3d2
from probos.cycle_trace import CycleIdRegistry, bind_cycle, current_cycle_id, new_cycle_id, unbind_cycle  # AD-1360
from probos.events import EventType, SensoriumBudgetExceededEvent
```
**A2.** SEARCH:
```
    Empty on every non-agentic path except a ``direct_message`` turn whose
    prompt ``_build_user_message`` assembled, which carries its AD-1357 context
    manifest; any other such turn carries an unchanged (empty) metadata dict.
```
REPLACE:
```
    Empty on every non-agentic path except a ``direct_message`` turn whose
    prompt ``_build_user_message`` assembled, which carries its AD-1357 context
    manifest; any other such turn carries an unchanged (empty) metadata dict.
    AD-1360 (#1828): plus ``correlation_id`` whenever the observation carries
    the cycle's AD-492 id.
```
**A3.** SEARCH:
```
    # AD-1357 (#1749): the reply's context manifest, LAST, so that BF-805's greedy
    # fit check (``IntentBus._prune_metadata``, in iteration order) considers it
```
REPLACE:
```
    # AD-1360 (#1828): the cycle's AD-492 id, for a caller that stores an episode after the cycle has ended. A fact
    # about the result, bounded to 64 characters (AD-1248 DD-5); absent when the observation carries none.
    cycle_id = observation.get("correlation_id") if isinstance(observation, dict) else None
    if type(cycle_id) is str and cycle_id:
        metadata["correlation_id"] = cycle_id[:64]
    # AD-1357 (#1749): the reply's context manifest, LAST, so that BF-805's greedy
    # fit check (``IntentBus._prune_metadata``, in iteration order) considers it
```
**A4.** SEARCH:
```
    @property
    def _cognitive_journal(self):
        """AD-431: Access journal via runtime (Ship's Computer service)."""
        if self._runtime and hasattr(self._runtime, 'cognitive_journal'):
            return self._runtime.cognitive_journal
        return None
```
REPLACE:
```
    @property
    def _cognitive_journal(self):
        """AD-431: Access journal via runtime (Ship's Computer service)."""
        if self._runtime and hasattr(self._runtime, 'cognitive_journal'):
            return self._runtime.cognitive_journal
        return None

    @property
    def _cycle_registry(self) -> CycleIdRegistry | None:
        """AD-1360 (#1828): the runtime's cycle-id registry (Ship's Computer service), reached as the journal is.

        Only a ``CycleIdRegistry`` counts: a test runtime's MagicMock attribute would otherwise issue a MagicMock id.
        """
        registry = getattr(getattr(self, "_runtime", None), "cycle_registry", None)
        return registry if isinstance(registry, CycleIdRegistry) else None

    def _issue_cycle_id(self) -> str:
        """AD-1360 (#1828): a new AD-492 id, recorded in the runtime's registry when there is one."""
        registry = self._cycle_registry
        return registry.issue(kind="cognitive_cycle") if registry is not None else new_cycle_id()
```
**A5.** SEARCH:
```
        # AD-492: Generate correlation ID for this cognitive cycle
        correlation_id = uuid.uuid4().hex[:12]
        self._current_correlation_id = correlation_id
```
REPLACE:
```
        # AD-492: the correlation ID for this cognitive cycle. AD-1360 (#1828): the id the cycle bound
        # (``_run_cycle_bound_lifecycle``); a perceive outside a bound cycle issues one of its own and binds nothing.
        correlation_id = current_cycle_id() or self._issue_cycle_id()
        self._current_correlation_id = correlation_id
```
**A6.** SEARCH:
```
    async def _run_cognitive_lifecycle(
        self,
        intent: IntentMessage,
        cognitive_skill_instructions: str | None = None,
        skill_entries: list | None = None,
        *,
        recreation_turn: RecreationTurnClaim | None = None,
        recreation_turns: RecreationTurnOperations | None = None,
    ) -> IntentResult:
```
REPLACE:
```
    async def _run_cycle_bound_lifecycle(
        self,
        intent: IntentMessage,
        cognitive_skill_instructions: str | None = None,
        skill_entries: list | None = None,
    ) -> IntentResult:
        """AD-1360 (#1828): ``_run_cognitive_lifecycle`` with a newly issued AD-492 cycle id bound (``cycle_trace``).

        ``perceive`` takes the bound id, so the journal, the events, the episode and ``IntentResult.metadata`` carry one
        id the runtime's registry issued. Every cycle binds its own: an inline cycle of another agent binds its own and
        the reset gives this one's back. The reset is in the ``finally``, so it runs on return, raise and cancellation.
        """
        token = bind_cycle(self._issue_cycle_id())
        try:
            return await self._run_cognitive_lifecycle(intent, cognitive_skill_instructions, skill_entries)
        finally:
            unbind_cycle(token)

    async def _run_cognitive_lifecycle(
        self,
        intent: IntentMessage,
        cognitive_skill_instructions: str | None = None,
        skill_entries: list | None = None,
        *,
        recreation_turn: RecreationTurnClaim | None = None,
        recreation_turns: RecreationTurnOperations | None = None,
    ) -> IntentResult:
```
**A7.** SEARCH:
```
            # the calls behind it. Empty on every non-agentic path but a
            # direct_message, which carries its AD-1357 context manifest.
```
REPLACE:
```
            # the calls behind it. On a non-agentic path it holds the cycle's
            # AD-492 id when the observation carries one (AD-1360), plus, on a
            # direct_message, its AD-1357 context manifest.
```
**A8.** SEARCH:
```
                async with concurrency_manager.slot(intent.intent, priority):
                    return await self._run_cognitive_lifecycle(
                        intent, _cognitive_skill_instructions, _skill_entries,
                    )
```
REPLACE:
```
                async with concurrency_manager.slot(intent.intent, priority):
                    return await self._run_cycle_bound_lifecycle(  # AD-1360: binds the cycle's id
                        intent, _cognitive_skill_instructions, _skill_entries,
                    )
```
**A9.** SEARCH:
```
        try:
            return await self._run_cognitive_lifecycle(
                intent, _cognitive_skill_instructions, _skill_entries,
            )
        finally:
            # BF-239: Remove ward room thread engagement on ALL exit paths.
```
REPLACE:
```
        try:
            return await self._run_cycle_bound_lifecycle(  # AD-1360: binds the cycle's id
                intent, _cognitive_skill_instructions, _skill_entries,
            )
        finally:
            # BF-239: Remove ward room thread engagement on ALL exit paths.
```
`_run_recreation_turn` (`:8092`) is unchanged: it runs inside the cycle already bound.

### 7.15 `tests/test_bf698_thread_provenance.py` (M2)

**X7.** SEARCH:
```
from probos.threads import ChatThreadStore
from probos.types import IntentMessage
```
REPLACE:
```
from probos.cycle_trace import new_cycle_id
from probos.threads import ChatThreadStore
from probos.types import IntentMessage
```
**X8.** SEARCH:
```
        _runtime=runtime,
```
REPLACE:
```
        _runtime=runtime,
        _issue_cycle_id=new_cycle_id,  # AD-1360 (#1828): perceive issues its own cycle id through the agent
```

### 7.16 Config generators (end of M1, in this order; generated files go in M1's commit)

```
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_config_reference.py
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_profiles.py --check
```
Expected diff (the orchestrator measures the exact diff). Any other file, model or row is a hard stop for the Architect.
- `config-reference.md`: one row after `dp_min_cohort_size` (`:1053`): `correlation_cutoff | float | 0.0 | >= 0.0 | AD-1360: ...`.
- `config-facade-baseline.yaml`:
  - a field line `- {default: '0.0', name: correlation_cutoff}` under `MemorySecurityConfig`;
  - `schema_sha256` moves for `MemorySecurityConfig`, `SecurityConfig` and `SystemConfig`;
  - `field_definitions` and `canonical_dump_leaves` each rise by 1, and `canonical_dump_sha256` moves.
- No `config-profiles.yaml` row: the manifest covers bools only (`check_config_profiles.py:166-170`).

### 7.17 `PROGRESS.md` (M3)

**TR1.** SEARCH (the whole line `:1`, once): `# ProbOS Progress`. REPLACE:
```markdown
# ProbOS Progress

**AD-1360 S1 (2026-11-20), #1828 -- each episode records, when it is stored, whether its AD-492 correlation id was issued by a cognitive cycle; the rule that reads the record ships off.** The new standard-library module `probos/cycle_trace.py` holds the in-process `CycleIdRegistry`, the store-time verdict and a ContextVar for the cycle's id. The runtime owns one registry and startup binds it to episodic memory. Each cycle `handle_intent` runs binds a newly issued id; `perceive` takes it and the result's `metadata["correlation_id"]` carries it. `EpisodicMemory.store()` writes `Episode.stored_at` and `Episode.correlation_verdict` (`resolved`, `unresolved`, `empty` or `unchecked`), replacing a producer's values; both round-trip in the metadata and neither is in the content hash. `validate_provenance` judges a direct episode stored strictly after `security.memory.correlation_cutoff`, which ships at 0.0 and no profile sets, so with the shipped config nothing is judged. Measured by `tests/test_ad1360_s1_cycle_trace.py` (67 cases): a real agent cycle stores an episode whose id resolves on a real ChromaDB-backed memory; with the rule armed in the test, recall keeps that episode and drops a direct episode with a made-up id, reporting why; an episode with no record is never flagged; the content hash is unchanged. No live store was read. Not measured: the registry's TTL and size, and the live share of direct episodes without a resolved id (AD-1360 S3's replay, which needs a Captain decision). Producers outside a cognitive cycle are AD-1360 S2a and S2b. Open items ad-1360 R1 to R3 of #1820. Contract `prompts/ad-1360-s1-cycle-id-store-time-verdict.md`.
```
### 7.18 `DECISIONS.md` (M3)

**TR2.** SEARCH (the whole line `:1659`, once on both trees):
```
- *Residual.* L1 to L12 of the contract. *Reversal.* Revert the BF-940 slice 4 commits. *G3's frame arrangement (F1) is replaced by BF-970 (#1801): the verdict is the reading's own.*
```
REPLACE:
```markdown
- *Residual.* L1 to L12 of the contract. *Reversal.* Revert the BF-940 slice 4 commits. *G3's frame arrangement (F1) is replaced by BF-970 (#1801): the verdict is the reading's own.*

### AD-1360 -- a direct episode's AD-492 correlation id is checked once, when it is stored, against an in-process registry of issued cycle ids; the rule that reads the record ships off (S1, 2026-11-20, #1828)

- *Mechanism.* `probos/cycle_trace.py` (standard library only) holds `CycleIdRegistry`, `judge_correlation_id` and the `CURRENT_CYCLE_ID` ContextVar. The runtime owns one registry (`runtime.cycle_registry`), and `bind_episodic_memory_gates` binds it to episodic memory. Each cycle `handle_intent` runs binds a newly issued id for its whole lifecycle (`_run_cycle_bound_lifecycle`, reset in a `finally`), and `perceive` takes it. `EpisodicMemory.store()` writes `Episode.stored_at` and `Episode.correlation_verdict`, replacing a producer's values. `validate_provenance(episode, *, correlation_cutoff)` judges a `direct` episode stored strictly after the cutoff: `empty` gives `direct_source_missing_correlation_id`, `unresolved` gives `direct_source_unresolved_correlation_id`, any other verdict but `resolved` gives `direct_source_unchecked_correlation_id`. `IntentResult.metadata["correlation_id"]` carries the cycle's id.
- *Measured.* `tests/test_ad1360_s1_cycle_trace.py` (67 cases), on a real ChromaDB-backed memory and a real agent cycle. Not measured: the registry's TTL (86,400 s) and size (100,000), both constructor defaults; the live share of direct episodes without a resolved id.
- *D1 (when).* At store time, once; the verdict is kept. Rejected: a recall-time check against the journal or the event log, which are pruned after 14 and 7 days, so every older episode would become unresolvable; a never-pruned id ledger, which grows with every cycle.
- *D2 (against what).* An in-process registry. Rejected: the cognitive journal, whose `record` returns silently without a database and swallows its errors (`journal.py:403-405`), and which has no row for non-cycle producers.
- *D3 (which time).* `stored_at`, written by `store()`. `Episode.timestamp` is set by the producer and kept by `seed()`, so a backdated timestamp would avoid the rule.
- *D4 (propagation).* A ContextVar, so no producer's signature changes. Each cycle binds its own id, and an inline cycle of another agent restores the outer id on return.
- *D5 (work items).* `CycleIdRegistry.register` adopts an id made elsewhere. BF-740's `correlation_id=work_item_id` stays; S2a registers it.
- *D6 (the cutoff).* `security.memory.correlation_cutoff` ships at 0.0 and no profile sets it; every `enforce_*` default is unchanged. S3 sets it in the supported profile after the replay.
- *Disclosed effects.* Every stored episode gains two metadata keys. A store with no registry bound (the rebuild command, tests) records `unchecked`; the rebuild writes `wardroom_import`, which is never judged. `MockEpisodicMemory` accepts the registry and records nothing. Cycle ids now come from the registry in AD-492's format.
- *Limits.* Code running in the process can issue an id at a site, or rewrite the record through `update_episode_metadata` (`episodic.py:2450-2471`). The registry is in memory, so an episode stored after a restart for a cycle begun before it records `unresolved`. A peer's episode is never judged (`sanitize_inbound_episode` passes no cutoff). The knowledge-store warm boot (`knowledge/store.py:158-167`) and AD-607i's redacted copy (`memory_security.py:403-421`) drop the record, so those episodes are never judged.
- *G0.* Decided by the Architect (consult `bfa178a3`): no Captain condition for S1 to S2b. The S3 replay reads the vessel's data directory, which the orchestrator classifies as access to a live production system; that is a Captain decision.
- *Residual.* #1820 items ad-1360 R1 to R3. *Reversal.* Revert the S1 commits; the two keys stay on stored rows and the old reader ignores them.
```
**TR3.** BF-938 D8 (a substring of `:2142`; once on both trees; no newline). SEARCH (substring): `When AD-1360 lands, this entry is updated to say so. Decision: #1680, comment of 2026-11-18.` REPLACE: `When AD-1360 lands, this entry is updated to say so. Decision: #1680, comment of 2026-11-18. [Amended by AD-1360 S1 (#1828, 2026-11-20): EpisodicMemory.store() records each episode's store time and whether its id resolved in the in-process cycle-id registry, and validate_provenance judges a direct episode stored after security.memory.correlation_cutoff; the cutoff ships at 0.0, so the rule stays off until AD-1360 S3 sets it after the replay.]`

**TR4.** BF-938 Scope (a substring of `:2136`; once on both trees). SEARCH (substring): `knows every source ProbOS writes and no longer requires a correlation id.` REPLACE: `knows every source ProbOS writes and no longer requires a correlation id [amended by AD-1360 S1 (#1828): it requires a resolved one again for a direct episode stored after security.memory.correlation_cutoff, which ships at 0.0].`

### 7.19 Ledger (M3)

Run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then the same command with `--check`, then `tests/test_ad1184_ad_ledger.py`. Commit the regenerated files in M3. No `roadmap.md` row (`AD-1360`: 0 hits).

## 8. Issue texts

**8.1 Progress comment on #1828 (after the PR merges; the issue stays open).**
> AD-1360 S1 merged in PR #... (with S2a and S2b; `Refs #1828`).
> - **Record:** `EpisodicMemory.store()` writes `stored_at` and `correlation_verdict` (`resolved`, `unresolved`, `empty`, `unchecked`) on every episode, checking the id against the runtime's in-process `CycleIdRegistry`. A producer's values are replaced. Neither field is in the content hash; a row stored before this reads `(0.0, "")` and is never judged.
> - **Ids:** every cognitive cycle binds a registry-issued AD-492 id; the result carries it as `metadata["correlation_id"]`.
> - **Rule:** `validate_provenance` judges a direct episode stored after `security.memory.correlation_cutoff`. **It ships at 0.0, so it is off**, and every `enforce_*` default is unchanged.
> - **Left:** S3 (sets the cutoff in the supported profile) waits on a replay of the vessel's data, which needs the Captain's approval (contract section 17). Open items ad-1360 R1 to R3 on #1820.

**8.2 New items on #1820.**
- **ad-1360 R1** (Low; reach: an episode stored after a restart for a cycle begun before it; evidence: `CycleIdRegistry` is in memory, `runtime.py` R3). It records `unresolved` and would be flagged once the rule is armed. Size it with S3's replay (restart count).
- **ad-1360 R2** (Low; reach: knowledge-store warm-boot episodes and AD-607i redacted copies; evidence: `knowledge/store.py:158-167` writes 8 fields; `memory_security.py:403-421` copies 15). The record is dropped, so these are never judged (fail-open).
- **ad-1360 R3** (Low; reach: code running in the process; evidence: `episodic.py:2469` merges any metadata key). `update_episode_metadata` can rewrite `correlation_verdict`. A keyed MAC over the record (SMSR, section 13) would detect it. Deferred.

## 9. What this does NOT change

- Any producer's `correlation_id` (S2a and S2b).
- `KNOWN_MEMORY_SOURCES`, `config/profiles/*.yaml`, any `enforce_*` default.
- `compute_episode_hash`, the journal, the event log.
- `_run_cognitive_lifecycle`'s body, `_run_recreation_turn`.
- BF-740's work-item pairing, federation wiring (`aggregate_inbound_episodes` has no caller).
- `config/system.yaml`, the HXI and routers.

## 10. Mutation rows (campaign on the M2 candidate; killers by N)

| Row | Mutant | Killed by |
|---|---|---|
| M1 | `stored_at > cutoff` becomes `>=` | N9 at-cutoff |
| M2 | `correlation_cutoff > 0.0` guard removed | N9 cutoff-off, N10 |
| M3 | source check removed | N9 secondhand, reflection |
| M4 | only `empty` flagged | N9 unresolved, unchecked, blank |
| M5 | store keeps the producer's verdict | N20 |
| M6 | store keeps the producer's `stored_at` | N20 |
| M7 | `_episode_to_metadata` drops `correlation_verdict` | N18, N20 |
| M8 | `_metadata_to_episode` drops `stored_at` | N18, N20 |
| M9 | `resolves` always True | N1, N20 made-up, N34 |
| M10 | TTL ignored | N2 |
| M11 | wrapper does not `unbind_cycle` | N31, N32, N33 |
| M12 | `_security_anomaly_drop` calls `validate_provenance` with no cutoff | N34 (not dropped, no event) |
| M13 | `validate_recall_result` passes no cutoff | N13, N34 |
| M14 | `sanitize_inbound_episode` passes `correlation_cutoff=1.0` | N14 |
| M15 | no registry records `""` | N21 |
| M16 | `perceive` ignores the bound id | N29 |
| M17 | `_cycle_registry` accepts any object | N28 (MagicMock) |
| M18 | `_build_result_metadata` omits the id | N30, N33 |
| M19 | `bind_episodic_memory_gates` ignores `cycle_registry` | N24, N25, N26 |
| M20 | runtime does not pass `cycle_registry` | N27 |
| M21 | `max_entries` ignored | N3 |
| M22 | validator accepts a naive time | N17 naive-iso, naive-datetime |
| M23 | `judge_correlation_id` checks the resolver before emptiness | N6 (`"", None`) |
| M24 | `stored_at` added to `compute_episode_hash` | N19 |
| M25 | `configured_correlation_cutoff` returns `float(value)` for any object | N12 (MagicMock) |
| M26 | handle_intent slot site still calls `_run_cognitive_lifecycle` | N31 concurrency-slot |
| M26b | handle_intent plain site still calls `_run_cognitive_lifecycle` | N31 plain |
| M27 | `stored_at` loses `compare=False` | `test_ad608_retroactive_evolution.py::test_integration_with_store`, and the AD-1340 golden-recall test |
| M28 | `correlation_verdict` loses `compare=False` | `test_ad608_retroactive_evolution.py::test_integration_with_store` |

## 11. Verified Against Codebase (2026-11-20, `86b9c156`)

```
rg -n "uuid.uuid4\(\).hex\[:12\]|_current_correlation_id" src/probos/cognitive/cognitive_agent.py
  1485: self._current_correlation_id: str = ""   3022: correlation_id = uuid.uuid4().hex[:12]   8061, 8817
rg -n "validate_provenance|validate_recall_result" src
  episodic.py:1550,1551,1555,1567  memory_security.py:95,188,205,266,277
rg -n "def bind_episodic_memory_gates|bind_episodic_memory_gates\(" src
  cognitive_services.py:54,353  __main__.py:2329
rg -n "_run_cognitive_lifecycle\(" src     cognitive_agent.py:7584,8092,8270,8294
rg -n "def _build_result_metadata" src/probos/cognitive/cognitive_agent.py   254
rg -n "class MemorySecurityConfig" src     config_models/crew.py:148
rg -n "def compute_episode_hash|def _episode_to_metadata|def _metadata_to_episode|async def store\(|async def seed|async def update_episode_metadata" src/probos/cognitive/episodic.py
  1062, 4388, 4561, 2034, 1871, 2450
rg -n "CURRENT_TICKET|except \(RuntimeError, ValueError\)" src/probos/admission/carrier.py   24, 46
rg -n "init_cognitive_services\(" src tests   runtime.py:3034; tests 1340_s1:1059, ad600:183, bf938_binding:83
rg -n "class MemorySource|DIRECT = " src/probos/types.py   514, 516
rg -n "asyncio_mode" pyproject.toml   181: asyncio_mode = "auto"
git ls-files --eol <the 12 edited files>   all i/lf w/crlf
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py   CEILING AD-1361 (prompts); git AD-1359; issues AD-1360
```

## Absence Verified (2026-11-20)

| Claim | Run | Found | Holds |
|---|---|---|---|
| No name S1 adds exists in `src` | `rg -n "cycle_trace\|correlation_verdict\|cycle_registry\|correlation_cutoff\|_issue_cycle_id\|_run_cycle_bound_lifecycle" src` | none; `stored_at` only in `predictive_branching/cache.py:20,24,102` (another class) | yes |
| The AD-492 cycle id has one generator | `rg -n "uuid4\(\).hex\[:12\]" src/probos` (37 hits); `rg -n "correlation_id\s*=\s*[^=]" src/probos` | The cycle id is set only at `cognitive_agent.py:3022`. Other correlation-id generators: `system_qa.py:294` (`qa-`), `dream_adapter.py:190` (`dream-`), `ready_room/sessions.py:87`; copies at `thought_store.py:117`, `runtime.py:4484`..`4939` (`msg.id`, event log). The rest are object ids | yes (S2 table) |
| Only the rebuild fake defines an AD-607 setter in tests | `rg -n "def set_security_config" tests` | `test_ad819_rebuild_episodic.py:414` | yes; it gets no registry |
| No test pins the exact metadata key set | `rg` for `set(meta..)==`, `.keys())==`, `len(meta..)==` over the 16 files that call `_episode_to_metadata(` | none | yes |
| No `?raw` test pins `memory_security` lines | `rg -n "no correlation-id rule\|getsource\(.*validate_provenance\|direct_source_missing_correlation_id" tests` | only `test_ad607:201` (a comment, X1) | yes |
| No real-cycle test asserts `metadata == {}` | `rg -n "metadata == \{\}" tests` (36 hits) | IntentResult constructors, delegation, tools, wire deserialisation; `_build_result_metadata` calls with no observation id | yes |
| CognitiveAgent's `perceive` is reached only through the lifecycle or `super()` | `rg -n "\.perceive\(" src/probos` | `self.perceive(intent.__dict__)` callers are `BaseAgent` subclasses (`shell_command.py:43`, `file_reader.py:27`, `quartermaster.py:27`, ...); CognitiveAgent subclasses call `super().perceive` inside their own `perceive` | yes |
| Federation inbound is unwired | `rg -n "aggregate_inbound_episodes\(\|sanitize_inbound_episode\(" src` | only `memory_security.py:252,306,320` | yes |
| The profile manifest covers bools only | read `check_config_profiles.py:166-170` | `annotation is bool` and default False | yes |
| No ContextVar census test | `rg -l ContextVar tests` | `test_ad1192_owned_steps_store.py`, `test_ad1126_verified_finalization.py` (unrelated) | yes |

## 12. Deterministic checks

- Focused gate, `-n 0`: `d:/ProbOS/.venv/Scripts/python.exe -m pytest -n 0 -q` on these files:
  - `tests/test_ad1360_s1_cycle_trace.py`
  - `tests/test_ad607_memory_security.py`, `tests/test_bf938_ad607_binding.py`, `tests/test_bf938_mock_episodic_binding.py`, `tests/test_bf938_ad607_recall_gate.py`, `tests/test_bf938_episode_source_guard.py`
  - `tests/test_bf984_recall_gate_coverage.py`, `tests/test_bf984_rebuild_binding.py`
  - `tests/test_bf740_correlation_id_persists.py`, `tests/test_ad1165_turn_promotion.py`, `tests/test_ad492_cognitive_correlation_ids.py`
  - `tests/test_bf239_ward_room_engagement_tracking.py`, `tests/test_ad1034_cognitive_spine.py`, `tests/test_ad1248_slice_a_crossing.py`, `tests/test_ad1357_context_manifest.py`, `tests/test_ad1203_turn_provenance.py`
  - `tests/test_ad1270e2g_crew_models.py`, `tests/test_ad1270e1_config_facade.py`, `tests/test_config_reference_current.py`
  - `tests/test_ad1152_agentic_correlation.py` (X6; the wide run found it red)
  - `tests/test_ad608_retroactive_evolution.py`, `tests/test_ad1340_s1_eviction.py`, `tests/test_bf698_thread_provenance.py` (the first two stay green because of `compare=False`, with no edit; the third with X7 and X8)
  - `tests/test_layer_boundaries.py`, `tests/test_ad819_rebuild_episodic.py`, `tests/test_ad541e_content_hashing.py`, `tests/test_cognitive_journal.py`, `tests/test_ad1184_ad_ledger.py`
- `rg -n "uuid.uuid4\(\).hex\[:12\]" src/probos/cognitive/cognitive_agent.py` finds nothing.
- `rg -n "bind_cycle\(" src/probos` finds only `_run_cycle_bound_lifecycle`; its `unbind_cycle` is in the `finally` of the same function.
- `rg -n "stored_at=\|correlation_verdict=" src/probos` finds only `episodic.py` (`store()` and `_metadata_to_episode`).
- `git diff 86b9c156 -- src/probos/cognitive/episodic.py`: the `compute_episode_hash` lines are unchanged.
- The two new files are ASCII only.
- Broad gate once, after M3: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad-1360-1828 --receipt logs/gates/ad-1360-1828.receipt.json` (S1 to S2b together).

## 13. Prior art and blind spots

**Internal.**
- BF-938 (DECISIONS `:2134-2147`): the retirement and its census method.
- AD-492: the id itself.
- AD-1346 M3d2 `admission/carrier.py`: ContextVar plus token reset in a `finally`. Adopted.
- AD-607 (`agent-memory-survey-absorption.md`, the AI Meets Brain survey): retrieval-time provenance gate.
- `docs/research/reference-projects.md` (checked 2026-11-20): no row concerns trace-id provenance. None was examined, none is overdue-and-relevant, and no row update is needed.

**External.**
- OpenTelemetry Python stores context in `contextvars`, pairs `attach` with `detach(token)` in a `finally`, and propagates into asyncio tasks. **Adopted** the pattern; **rejected** the dependency.
- SMSR tags each memory write at write time (HMAC) so unsigned injections are refused, and argues retrieval-only filters cannot certify security. **Adapted:** the record is made at write time. A MAC is **deferred** (R3): the threat S1 addresses is a producer bypassing the cycle, not an outside writer.
- A-MemGuard checks content consensus across memories. **Rejected for this issue:** orthogonal to provenance.
- MINJA shows query-only injection reaches memory. **Context only:** it motivates S3's arming.

**Blind spots named.**
- Restart (R1); record-dropping copies (R2); in-process rewrite (R3).
- A multi-process deployment would need the `CycleIdResolver` Protocol backed by shared storage. Considered, deferred: none exists today.
- Clock: the TTL uses a monotonic clock, `stored_at` uses wall time. An NTP step moves `stored_at` relative to the cutoff by the step only.
- Concurrent cycles on one agent each bind in their own task context; `self._current_correlation_id` still races, as before.

## 14. Diff Reviewer: properties to verify

1. With `correlation_cutoff` 0.0, `validate_provenance` returns the base result for every input, so no recall result or event changes under any shipped profile.
2. `store()` is the only writer of `stored_at` and `correlation_verdict` in `src`, and a producer's values never survive it.
3. `compute_episode_hash` is byte-identical to the base; a row with neither key reads `(0.0, "")`.
4. A direct episode with `stored_at` 0.0 is never flagged, whatever its verdict or the cutoff.
5. Every `bind_cycle` in `src` has its `unbind_cycle` in a `finally` of the same function, and `perceive` binds nothing.
6. The registry is bounded by TTL and size, thread-safe, and stores no payload.
7. `IntentResult.metadata` gains only a `str` key of at most 64 characters, placed before the AD-1357 manifest.
8. Exception tiers: a failing registry gives `unchecked` and a WARNING with the store proceeding; `unbind_cycle` swallows only PEP 567's two errors; the binding is not wrapped (BF-938 D5).
9. `cycle_trace.py` imports only the standard library.
10. `MockEpisodicMemory` stays an inert store.
11. No `enforce_*` default, profile file or `KNOWN_MEMORY_SOURCES` entry changes.
12. An `Episode` that `store()` has stamped equals the one its producer built, and no other `Episode` field leaves `==`.

## 15. Acceptance

- [ ] Section 5's predicted pass/fail holds after M1 and after M2; the focused gate (section 12) is green.
- [ ] Mutation rows M1-M28 (M26 and M26b are the two `handle_intent` sites) are killed by the named cases.
- [ ] section 12's `rg` checks hold; the config generators produce only the diff in 7.16.
- [ ] Trackers TR1-TR4 applied; ledger regenerated and checked.
- [ ] The PR says `Refs #1828`; #1828 stays open.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. The orchestrator's first-hand checks (2026-11-21, oracle trees at `86b9c156`, whose tree is `3167ff44`)

Every pair of section 7 was applied to a scratch worktree by `audit\contract_tools.py` (ASCII only: no `--utf8` was needed), and every check below was run, before the Builder started. Each test run went through `run_pytest_homeguard.ps1` (a redirected, empty home: entries left in it 0). The test files ran with the default embeddings; the focused gate (O11) and the consumer sets also ran under `PROBOS_EMBEDDINGS=local`, as CI runs them. The merge of BF-989 moves the base, so the tool's `checkpoints` run is repeated on the merged main before C0 (the file contents of BF-989's head `6965e111`, whose tree is the merged main's, were loaded into a temporary repository, and `checkpoints` found all 52 operations with every SEARCH exactly once; 13 checkpoint blobs differ from the table on `86b9c156` (operations 38 to 46 in `cognitive_agent.py`, whose line counts are 7 higher, and operations 49 to 52 in `PROGRESS.md` and `DECISIONS.md`) because BF-989 edits those three files, and no contract line range moves; the Builders get the table of the merged tree). Results:

| O | Result |
|---|---|
| O1 | All 52 operations (the draft's 46, the pairs X3 to X5 of O5 and X6 to X8 of O9) are found by `contract_tools.py list --prefix 7.`: 28 in M1, 20 in M2, 4 in M3. Every SEARCH occurs exactly once on the base, in files that are CRLF throughout (`git ls-files --eol`: `i/lf w/crlf`); the two new files were absent. |
| O2 | The new test file alone on the base: **a collection error**, but not the draft's `ModuleNotFoundError: probos.cycle_trace`: the first failing import is `cannot import name 'configured_correlation_cutoff' from 'probos.cognitive.memory_security'`. |
| O3 | After the M1 pairs (7.2 to 7.11 without the M2 files): **55 passed, 12 failed**, as section 5 predicts. The twelve reds are N24 to N34 (N31 has two cases): `bind_episodic_memory_gates()` and `init_cognitive_services()` take no `cycle_registry` keyword; `ProbOSRuntime` has no `cycle_registry`; `CognitiveAgent` has no `_issue_cycle_id` and no `_run_cycle_bound_lifecycle`; `perceive` does not take the bound id; the result metadata is `{}`; and the two crossing cases fail on the missing agent binding. |
| O4 | After the M2 pairs: **67 passed**. |
| O5 | **The draft's focused gate (24 files) was red on two pinned counts that the draft's consumers table missed**: `test_ad1270e2g_crew_models.py::test_every_declared_bound_is_still_enforced[MemorySecurityConfig]` (`assert 4 == 3`: the declared-bound table at `:272` and its total at `:597`) and `test_ad1270e1_config_facade.py::test_committed_baseline_records_the_measured_surface` (`assert 1886 == 1885`: the field count at `:1572`). Pairs X3, X4 and X5 repair them, and the consumers row names them. After them the two files give 371 passed. |
| O6 | The config generators of 7.16, run in order on the M2 tree, change exactly two files: `docs/development/config-reference.md` (+1 line, the `correlation_cutoff` row) and `docs/development/config-facade-baseline.yaml` (13 lines: the field line under `MemorySecurityConfig`, `schema_sha256` for `MemorySecurityConfig`, `SecurityConfig` and `SystemConfig`, `field_definitions` 1885 to 1886, `canonical_dump_leaves` 1895 to 1896, `canonical_dump_sha256`). `check_config_facade.py --check` and `check_config_profiles.py --check` pass (profiles 3, classified 55, default-OFF flags 227). Blobs after the generators: `config-reference.md` `123a97b15234a6d1f60e5e962e65bf3a7934affb`, `config-facade-baseline.yaml` `79c1f44c80a6171bb27a6b3c8ca27254eed2911f`. |
| O7 | **The pre-S1 row proof** (`probe_prerow_write.py` on the clean base, then `probe_prerow_read.py` on the oracle; premises P0 to P3 asserted): a direct episode stored by the base's `EpisodicMemory.store()` into a real ChromaDB store has a raw row with neither new key; read by the S1 code it reads `(stored_at, correlation_verdict) == (0.0, "")`; `compute_episode_hash(read back)` equals the stored `content_hash` (`a18b8477f3d5557ab464c48f95578fc09e47fe2d931920d29df8868bc294c68d`); under `MemorySecurityConfig(enforce_provenance=True, correlation_cutoff=1.0)` `recent_for_agent` returns it with no provenance-gap event. The control that makes it mean something: a direct episode stored then by the S1 code with an id nothing issued (no registry bound) records `unchecked` and a store time after the cutoff, and under the same armed config recall drops it with one provenance-gap event while the legacy row is still returned. |
| O8 | The deterministic checks of section 12 hold: no `uuid.uuid4().hex[:12]` in `cognitive_agent.py`; `bind_cycle(` is called only at `cognitive_agent.py:7619`, and its `unbind_cycle` is in the `finally` of the same function (`:7623`); `stored_at=` and `correlation_verdict=` occur only in `episodic.py` (`store()` and `_metadata_to_episode`), apart from `predictive_branching/cache.py:102`, another class; the diff of `episodic.py` has no hunk in `compute_episode_hash`; the two new files hold no byte above 127; `_run_cognitive_lifecycle(` is called at `:7621` (the wrapper) and `:8134` (the recreation turn), and the wrapper is called at `:8312` and `:8336`, both inside `_handle_admitted_intent` (`:8194`), which `handle_intent` (`:8168`) reaches (the draft put the two sites in `handle_intent`). |
| O9 | **The wide consumer run** found six more pinned tests, and one ruling. The set is every file under `tests/` that names an `Episode`, the episodic memories, `handle_intent`, `perceive`, `IntentResult`, the memory-security names or a correlation id: **575 files**, in three chunks, on the draft's candidate (O1 to O8 and a compared `Episode`). Chunk 0: 8391 passed, 4 failed, 3 skipped. Chunk 1: 3329 passed, 7 failed, 5 skipped. Chunk 2: 6960 passed, 24 skipped. The 11 reds: (a) `test_ad1152_agentic_correlation.py::test_default_off_matches_pinned_base` and the two `test_default_off_golden_pins_only_descriptor_owner_platform` cases pin the default dump of the config, which now holds `security.memory.correlation_cutoff`: **pair X6**; (b) `test_bf698_thread_provenance.py` (6 cases) builds a `SimpleNamespace` agent and calls `CognitiveAgent.perceive(agent, ...)` unbound, and `perceive` now issues its id through `self._issue_cycle_id`: **pairs X7 and X8**; (c) `test_ad608_retroactive_evolution.py::test_integration_with_store` and `test_ad1340_s1_eviction.py::test_golden_recall_is_identical_under_archive_and_delete` compare an `Episode` read back from a memory with the one the producer built, and `store()`'s stamps made them unequal. (c) is **not** repaired by editing those tests: the Architect's ruling (consult `edd29843`, `consult-b10-eq.out.txt`) is that `stored_at` and `correlation_verdict` take `compare=False` (T1), so `Episode.__eq__` is the one every existing test already saw (reviewer property 12, decision D7). `rg` for `assert <ep> != <ep>` forms and `assertNotEqual(.*ep` over `tests` found nothing, so no test depends on the stamps making two episodes unequal (the pattern is narrow; the broad gate is the net). |
| O10 | **The mutation campaign** (section 10; `mutants_gen.py` over `rows_ad1360s1.py`: each row changes one line of the candidate in place, and its baseline had to be all green). M1 to M26b (27 rows, on the S1 candidate): **killed 27, differs 0, survived 0, invalid 0**; every named killer failed, and nine rows (M2, M4, M7, M8, M9, M15, M18, M22, M26b) also failed cases beyond the named ones. M26 is run as two rows, M26 for the slot site and M26b for the plain site. M27 and M28 (the `compare=False` rows, on the clean oracle after the v4 pairs): both killed, M27 by the AD-608 integration test and the AD-1340 golden recall, M28 by the AD-608 test alone. |
| O11 | **The final focused gate** (the 28 files of section 12, on the clean oracle: S1 v4 M1 and M2 and the generated docs): **1102 passed under the default embeddings (92 s) and 1102 passed under `PROBOS_EMBEDDINGS=local` (80 s)**, with no failure and no error. |
| O12 | TR1 to TR4 (operations 49 to 52) apply on the files of the merged main (each SEARCH once: the re-check above), and on the oracle of O1 to O11, after the pairs of M1 and M2, `gen_ad_ledger.py` regenerated the ledger pair and its `--check` reported "AD/BF ledger is current". The ledger is regenerated again on the merged tree after M3, because BF-989's entries change it. |

**What the orchestrator changed from the Architect's draft** (each is a pair or a line of section 7, and each came from a run above):
- X3, X4, X5: two pinned counts the consumers table missed (O5).
- X6, X7, X8: three more pinned tests, found by the wide run (O9).
- T1: `compare=False` on the two new `Episode` fields, and decision D7 (O9, the Architect's ruling).
- O2 and O8: two sentences of the draft's record were wrong (the first error of the new tests on the base, and the function that holds the two lifecycle call sites).
- A8a and A8b are named A8 and A9, so every label matches `^[A-Za-z]+\d+[.:]`.

**What these checks do not show.**
- The vessel: nothing here ran against `%LOCALAPPDATA%\ProbOS\data`. The cutoff ships at 0.0, so no recall result changes until S3 arms it, and S3 waits on a replay of that data (section 17).
- The registry's TTL (86400 s) and size (100000 entries) are defaults nobody measured; section 17's replay measures the delay and the id count they must cover.
- The wide run (O9) ran on the draft's candidate. After X6 to X8 and `compare=False` only their files and the two equality rulings changed, and those files are in the focused gate (O11); the broad gate of section 12 is the net for the rest.
- S1 does not arm the rule (the cutoff is 0.0). Until S2a and S2b land, producers that store an episode outside a cognitive cycle still write an id the registry never issued or none, which `store()` records as `unresolved` or `empty`; that is why the rule stays off until S3's replay.

## 17. S3: parked; the Captain's decision

**Decision required (Captain, for S3 only).** Approve the orchestrator taking a read-only copy of `%LOCALAPPDATA%\ProbOS\data` with the SQLite online-backup API (no stop, nothing written to the directory), at least 7 days after the S1-S2b PR is running on the vessel. Or supply such a copy.

| Rank | Option | Trade-off |
|---|---|---|
| 1 (recommended) | Approve the online-backup copy | Read-only; nothing in the vessel changes |
| 2 | The Captain supplies a copy | Same measurement; costs the Captain a step |
| 3 | Arm without a replay | **Rejected:** it would arm a recall drop with an unmeasured false-positive rate |

**The replay measures:**
- per verdict, the share of direct episodes stored after T (the first recorded `stored_at` plus 1 hour);
- the cycle-to-episode delay, max and p99 (sets the TTL);
- work-item run durations, max and p99 (sets the TTL);
- distinct cycle ids per day (sets `max_entries`);
- recall calls per hour;
- BF-938's 200-query probe with `correlation_cutoff = T` and `enforce_provenance` armed.

**Pass:** at most 2% of recalled results dropped and at most 2,500 events in the busiest hour. Then S3 sets the cutoff in `config/profiles/supported.yaml` with its binding test, and #1828 closes. **Fail:** the residual producers become a BF and the replay is rerun.

---

Sources:
- [OpenTelemetry Python: opentelemetry.context (attach/detach)](https://opentelemetry-python.readthedocs.io/en/latest/api/context.html)
- [OpenTelemetry Python context source](https://opentelemetry-python.readthedocs.io/en/latest/_modules/opentelemetry/context.html)
- [Arize: context propagation](https://arize.com/docs/phoenix/tracing/concepts-tracing/otel-openinference/context-propagation)
- [SMSR, write-time provenance for agent memory (arXiv 2606.12703)](https://arxiv.org/html/2606.12703)
- [A-MemGuard (arXiv 2510.02373)](https://arxiv.org/abs/2510.02373)
- [Memory Poisoning Attack and Defense on Memory Based LLM-Agents (arXiv 2601.05504)](https://arxiv.org/html/2601.05504)
