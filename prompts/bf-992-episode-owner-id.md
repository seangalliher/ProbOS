# BF-992: three readers that hold a slot id count episodes under the agent's sovereign id: the boot camp's episode criterion, the episodic-recall probe and the consolidated profile

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-24
**Assembled by:** the orchestrator, 2026-11-24: the heading and pair layout follow what `contract_tools.py` reads; the Architect's text is otherwise unchanged, except three sentences in section 8, corrected after the orchestrator ran the checks (results in section 15): check 1 names this build's base; check 3 counts 14 `count_for_agent(` lines (9 calls and 5 definitions, all listed in section 10; the draft said 12 and pointed at section 9); check 4 expects all four cases of file 1 to fail on the base (the draft said case 2 passes; it fails, because the base counts the slot-id episodes and graduates the agent).
**Status:** ready to build. **Owning issue:** #1324. This builds the register addition of 2026-10-29 (a comment by `claude-architect`, "Register addition: the AD-638 boot camp's episode criterion counts under the slot id..."). Commits and the PR say `Refs #1324.`
**Base:** `ad28bc34756df2d21ad33af711a20eebfd3a93f1` (origin/main after B12 (BF-981 part 2, #1815) merged; the draft's base was `542a2a68`). B12 shared only `PROGRESS.md`, `DECISIONS.md` and the ledger pair with this item, and P3-1 and P3-2 anchor on text that exists on both trees.
**Number:** BF-992. The orchestrator allocated it on 2026-11-24, when `docs/development/open-ads-report.md:32` named it as the next free BF. BF-993 was allocated afterwards, to a test repair inside B12 (#1815), so on this base the report shows BF-993 as the ceiling and BF-992 among the numbers below it that no authority mentions, until this item's tracker entries land. No AD.
**Line endings:** the working copies are CRLF and the blocks below are LF. Every SEARCH starts at a line start and occurs once in its file at its turn. All new text is ASCII.
**Estimated tests:** 22 new cases in three new files (12 in sections 6.3 and 6.9; 10 in 16.2, amendment A1); 0 changed; 0 removed.
**Scope:** `src/probos/boot_camp.py`, `startup/finalize.py`, `cognitive/episodic.py`, `cognitive/qualification_tests.py`, `acm.py`, `cognitive/memory_probes.py`, `cognitive/drift_detector.py` (amendment A1, section 16), three new test files and the trackers.

## 1. Problem

| Reader | Id passed in | What it reads with that id | Defect |
|---|---|---|---|
| `boot_camp.py:211` `check_graduation` | The slot id. Enrolment uses `"agent_id": agent.id` (`finalize.py:1005`); posts and DMs use `agent.id` (`proactive.py:4279`, `:5137`) | `count_for_agent(agent_id)` | Yes |
| `qualification_tests.py:445` and `:474` `EpisodicRecallProbe` | The slot id. Callers: `commands_qualification.py:121` (`agent.id`) and the drift detector (`drift_detector.py:438-441`: "Returns slot IDs (agent.id), NOT sovereign IDs"). `:460` `registry.get(agent_id)` is keyed by slot and is correct | `count_for_agent(agent_id)`, `recent_for_agent(agent_id, k=3)` | Yes, at `:445` and `:474`; `:460` is right |
| `acm.py:505` `get_consolidated_profile` | The slot id. `routers/crew.py:259-261` returns 404 unless `registry.get(agent_id)` finds the agent, and `routers/acm.py:42` passes the route id | `count_for_agent(agent_id)` | Yes |
| `holodeck/gates.py:79` | `record.agent_id` | `count_for_agent` | Out of scope: #1700 S1 deletes it |

Crew episodes carry the sovereign id: `cognitive_agent.py:12857` stores `agent_ids=[getattr(self, 'sovereign_id', None) or self.id]`. Wiring sets `sovereign_id` before finalization (`agent_onboarding.py:446-456`). `count_for_agent` matches the id against each episode's `agent_ids_json` (`episodic.py:4344-4363`).

**Effect, by reading:**
- **Boot camp:** a crew agent's count is 0, so `min_episodes` (5, `config_models/crew.py:28`) is never met, and every enrolled agent leaves only through the timeout.
- **Probe:** it returns `skipped`/`insufficient_episodes` with score 1.0 and `passed=True` (`:446-457`).
- **Profile:** `episode_count` reads 0 in the HXI Service Record (`ui/src/components/personnel/ServiceRecord.tsx:417`).

The trust criterion is correct. `TrustNetwork` is keyed by slot and maps a sovereign identity to its slot record (`consensus/trust.py:303-317`, `:1017-1031`, BF-907).

## 2. Overview

- **S1 (boot camp):**
  - Finalization adds `"memory_id": resolve_sovereign_id(agent)` to each enrolment dict. That helper returns the sovereign id, else `agent.id` (`episodic.py:466-472`).
  - `activate` stores `agent_info.get("memory_id") or agent_id` in the new field `AgentBootCampState.memory_id`.
  - `check_graduation` counts `state.memory_id`.
  - The coordinator's dict key, its posts, DMs and trust reads, and both events stay keyed by the slot id.
  - The `BOOT_CAMP_GRADUATION` payload keeps its keys (`boot_camp.py:330-337`). `"episodes"` is now the count under the memory id.
- **S2 (readers with a registry):**
  - New `resolve_sovereign_id_from_registry(agent_id, registry)` in `cognitive/episodic.py`, beside the BF-103 helpers. The registry's agent answers through `resolve_sovereign_id`. An id the registry does not hold, and a missing registry, return the id unchanged.
  - The probe resolves once and uses the result for its count and its episode read. `TestResult.agent_id` stays the slot id, because the store keys results by slot.
  - The ACM count uses the same helper.
  - `memory_probes._resolve_probe_agent_id` (BF-138, the same logic) delegates to it, so there is one copy.
- **Rejected (one line each):**
  - Injecting the identity registry into the coordinator: a new constructor dependency and runtime wiring, when the agent object at finalization already holds the id.
  - Counting through `count_agent_episodes` in the coordinator: it needs the agent object, and the coordinator holds dicts.
  - Moving the probe's `registry.get` before its count: it changes the result for an unknown agent with few episodes from `skipped` to an error.
  - Repairing `holodeck/gates.py:79`: #1700 S1 deletes it.

## 3. Decisions

| # | Decision |
|---|---|
| D1 | The memory id is resolved once, at enrolment, from the agent object. One fallback (in `activate`): no `memory_id` key, or an empty one, gives the slot id. An agent with no sovereign id gets its slot id through `resolve_sovereign_id`, which is also how its episodes are stored. |
| D2 | `AgentBootCampState.memory_id: str = ""` is the last field. Only `activate` builds a state (`boot_camp.py:170`; Absence A2). |
| D3 | One shared slot-to-memory reader for callers that hold a registry, in `cognitive/episodic.py`. Callers import it lazily, as `acm.py:489` and `qualification_tests.py:489` already do for their imports. |
| D4 | `_resolve_probe_agent_id` keeps its name and signature, so the BF-138 tests and six callers are untouched. One case widens: `runtime.registry is None` used to raise `AttributeError` and now returns the id. |
| D5 | Risk tier **STANDARD**, crew-facing, see below. Graduation only takes an agent out of enrolment. Enrolment gates `relaxes_quality_gates` (off by default; when on, graduating earlier ends the relaxation earlier, which tightens the chain), the AD-683 snapshot in DMs (`boot_camp.py:123-136`) and post and DM counting. No permission, trust value, rank or record changes. No security, governance or audit control changes. |
| D6 | The probe now measures a crew agent with at least 3 episodes, so its score can fall below 0.5 and `passed` can be False. This is the intended behaviour. Its consequence for drift is register row 992-R1 (section 12), measured in review round 1 and repaired by amendment A1 (D7). |
| D7 | Amendment A1 (section 16): the drift window leaves out rows whose `details["skipped"]` is True, beside BF-711's `inconclusive` filter. The flag is read from the stored row, so no migration is needed. The skipped baseline and the signal's `direction` stay with the AD-1186 item in #1324. |

## 4. Milestones, commits, review

The Builder applies the pairs and runs no test. The orchestrator commits by plumbing. No subject carries an `AD-` or `BF-` token, and no commit text uses the words close, fix or resolve. Every body says `Refs #1324.`

- **M1** (S1): P1-1 to P1-5 and the new file in 6.3.
  Subject: `Boot camp counts each enrolled agent's episodes under the id its episodes carry`
- **M2** (S2): P2-1 to P2-5 and the new file in 6.9.
  Subject: `Recall probe and consolidated profile count episodes under the agent's sovereign id through one shared reader`
- **M3** (trackers): P3-1 and P3-2, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`). Stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md`.
  Subject: `Trackers for the episode owner id in the boot camp, the recall probe and the profile`
- **M4** (amendment A1, drift detector): A1-1 and the new file in 16.2.
  Subject: `Drift window leaves out results a probe skipped, as it does inconclusive ones`
- **M5** (amendment A1, trackers): A1-3 and A1-4, then `gen_ad_ledger.py` as in M3; stage the two ledger files if they change.
  Subject: `Trackers for the drift window and skipped probe results`

One Builder delegation covers M1 to M3, under about 60 tool calls. A second delegation (amendment A1) covers M4 and M5, under about 20 tool calls.

**Shared contracts touched:**
- The enrolment dict: one producer, `finalize.py:1003-1011`; one consumer, `activate` (A3). The new key is additive and optional.
- `AgentBootCampState`: an additive field.
- `count_for_agent`'s callers: three move to the memory id.
- A new public helper in `episodic.py`.
- The probe's `TestResult`: same shape, values now measured.
- `_resolve_probe_agent_id`: D4.
- The stored qualification row (amendment A1): `details["skipped"] is True` now means "not a data point" for drift, across five producers (D7).

**Review:** one `gpt-6.1-sol` reviewer over the whole candidate, using the section 8 properties. Repair rounds review the delta unless a repair changes a shared contract above. Round 2 reviews the A1 delta plus the stored-row convention (section 9, property 10).

**Pins:**
- **Not changed.** The boot-camp fakes in `test_ad638_boot_camp.py:30-33`, `test_ad1270_boot_camp_lifecycle.py:47-52`, `_orientation.py:48-50`, `_repair_a1.py:48-52`, `_trust.py:37-44` and `test_ad1270a_startup_receipts.py:56-58` return a constant for any id. They pin nothing about the id; the new files carry the keyed proof.
- **Unaffected.** The probe fakes (`test_ad566b_baseline_tests.py:86-97`, used by `test_bf988_llm_response_text.py:247-253`) are id-blind, and their `MockAgent` has no `sovereign_id`, so the helper returns `"agent-1"`.
- **Unaffected.** `test_acm.py:207-220` uses an empty real `AgentRegistry` and an `AsyncMock(return_value=42)`.
- **Unaffected.** No test asserts `count_for_agent`'s argument on these paths (A5).

## 5. Builder: may and may not

- **May:** apply the pairs in order, create the two files, run `gen_ad_ledger.py` (M3), `git diff --check` and `git diff --stat`.
- **May not:** run pytest, commit, edit an unnamed file, add `skip`/`xfail`, or reword an anchor. If a SEARCH does not match exactly once, stop and report.

## 6. The pairs

### 6.1 `src/probos/boot_camp.py` (M1)

**P1-1**
SEARCH:
```python
    graduated: bool = False
    graduated_at: float | None = None
```
REPLACE:
```python
    graduated: bool = False
    graduated_at: float | None = None
    # BF-992: the id this agent's episodes carry; ``activate`` sets it (the sovereign id, else the
    # slot id). Posts, DMs and trust stay keyed by ``agent_id``, the slot id.
    memory_id: str = ""
```

**P1-2**
SEARCH:
```python
            crew_agents: List of dicts with agent_id, callsign, department.
```
REPLACE:
```python
            crew_agents: List of dicts with agent_id, callsign, department and, optionally,
                memory_id (BF-992: the id the agent's episodes carry; absent or empty, the agent_id).
```

**P1-3**
SEARCH:
```python
                department=agent_info.get("department", ""),
                enrolled_at=self._started_at,
            )
```
REPLACE:
```python
                department=agent_info.get("department", ""),
                enrolled_at=self._started_at,
                memory_id=agent_info.get("memory_id") or agent_id,  # BF-992
            )
```

**P1-4**
SEARCH:
```python
        # Episode count
        try:
            episode_count = await self._episodic.count_for_agent(agent_id)
```
REPLACE:
```python
        # Episode count, under the id the agent's episodes carry (BF-992), not the slot id
        try:
            episode_count = await self._episodic.count_for_agent(state.memory_id)
```

### 6.2 `src/probos/startup/finalize.py` (M1)

**P1-5**
SEARCH:
```python
    from probos.cognitive.standing_orders import get_department

    ontology = getattr(runtime, "ontology", None)
    crew_agents = [
        {
            "agent_id": agent.id,
```
REPLACE:
```python
    from probos.cognitive.episodic import resolve_sovereign_id
    from probos.cognitive.standing_orders import get_department

    ontology = getattr(runtime, "ontology", None)
    crew_agents = [
        {
            "agent_id": agent.id,
            "memory_id": resolve_sovereign_id(agent),  # BF-992: the id the agent's episodes carry
```

### 6.3 `tests/test_bf992_boot_camp_episode_owner.py` (M1, new file)

```python
"""BF-992 (#1324): the boot camp counts an enrolled agent's episodes under the id its episodes carry.

Crew episodes carry the sovereign id (``cognitive_agent.py:12857``); enrolment is keyed by the slot id.
A real coordinator over a real ``TrustNetwork`` and a real ``MockEpisodicMemory`` holding real ``Episode``
rows, enrolled through finalization's own helper. Nothing stands in for ``count_for_agent``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from probos.boot_camp import BootCampCoordinator
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.config import BootCampConfig
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
from probos.startup.finalize import _activate_boot_camp_on_cold_start
from probos.types import Episode

_START = 1_000_000.0
_SLOT = "security_officer-0"
_SOVEREIGN = "3f9c2a1e-sovereign"


class _Clock:
    def __init__(self) -> None:
        self.now = _START

    def __call__(self) -> float:
        return self.now


def _episodes(owner: str, count: int) -> list[Episode]:
    return [Episode(user_input=f"watch report {i}", timestamp=float(i + 1), agent_ids=[owner]) for i in range(count)]


def _member(**extra: Any) -> SimpleNamespace:
    return SimpleNamespace(id=_SLOT, agent_type="security_officer", callsign="Worf", department="security", **extra)


class _Rig:
    """The shipped criteria (``BootCampConfig()``: 5 episodes, 3 posts, 1 DM, trust 0.55, 60 to 120 minutes)."""

    def __init__(self) -> None:
        self.clock = _Clock()
        self.trust = TrustNetwork()
        self.memory = MockEpisodicMemory()
        self.events: list[tuple[Any, dict]] = []
        self.coord = BootCampCoordinator(
            config=BootCampConfig(),
            trust_service=self.trust,
            episodic_memory=self.memory,
            emit_event_fn=lambda event_type, data: self.events.append((event_type, data)),
            clock=self.clock,
        )

    async def enrol(self, member: SimpleNamespace) -> None:
        runtime = SimpleNamespace(
            boot_camp=self.coord, is_cold_start=False, ontology=None, _lifecycle_state="first_boot",
            episodic_memory=self.memory,  # empty here, so this boot starts a new crew (BF-941)
            registry=SimpleNamespace(all=lambda: [member]),
        )
        assert await _activate_boot_camp_on_cold_start(runtime=runtime) is True

    async def serve(self, agent_id: str) -> None:
        """Every criterion but the episodes is met, at 61 of 120 minutes."""
        self.trust.create_with_prior(agent_id, 3.0, 2.0)  # 0.6; after activation, which skips 0.55 and above
        for _ in range(3):
            await self.coord.on_agent_post(agent_id, "department")
        self.clock.now = _START + 61 * 60
        await self.coord.on_agent_dm(agent_id)  # the last tracked activity; it checks graduation

    def of(self, event_type: EventType) -> list[dict]:
        return [data for kind, data in self.events if kind == event_type]


async def test_episodes_under_the_sovereign_id_graduate_before_the_timeout() -> None:
    rig = _Rig()
    await rig.enrol(_member(sovereign_id=_SOVEREIGN))
    await rig.memory.seed(_episodes(_SOVEREIGN, 5))  # none under the slot id
    await rig.serve(_SLOT)

    assert rig.coord.get_state(_SLOT).memory_id == _SOVEREIGN
    assert not rig.coord.is_enrolled(_SLOT)
    assert [(g["agent_id"], g["episodes"]) for g in rig.of(EventType.BOOT_CAMP_GRADUATION)] == [(_SLOT, 5)]
    assert rig.of(EventType.BOOT_CAMP_TIMEOUT) == []


async def test_episodes_under_the_slot_id_alone_do_not_count_for_an_agent_with_a_sovereign_id() -> None:
    rig = _Rig()
    await rig.enrol(_member(sovereign_id=_SOVEREIGN))
    await rig.memory.seed(_episodes(_SLOT, 5))
    await rig.serve(_SLOT)

    assert rig.coord.is_enrolled(_SLOT)
    assert rig.of(EventType.BOOT_CAMP_GRADUATION) == []


async def test_an_agent_with_no_sovereign_id_is_counted_by_its_slot_id() -> None:
    rig = _Rig()
    await rig.enrol(_member())
    await rig.memory.seed(_episodes(_SLOT, 5))
    await rig.serve(_SLOT)

    assert rig.coord.get_state(_SLOT).memory_id == _SLOT
    assert [g["episodes"] for g in rig.of(EventType.BOOT_CAMP_GRADUATION)] == [5]


async def test_an_enrolment_without_a_memory_id_counts_by_the_agent_id() -> None:
    rig = _Rig()
    await rig.coord.activate([{"agent_id": "crew-1", "callsign": "Wesley", "department": "science"}])
    await rig.memory.seed(_episodes("crew-1", 5))
    await rig.serve("crew-1")

    assert rig.coord.get_state("crew-1").memory_id == "crew-1"
    assert [g["agent_id"] for g in rig.of(EventType.BOOT_CAMP_GRADUATION)] == ["crew-1"]
```

### 6.4 `src/probos/cognitive/episodic.py` (M2)

**P2-1**
SEARCH:
```python
    cert = identity_registry.get_by_slot(slot_id)
    if cert:
        return cert.agent_uuid
    return slot_id
```
REPLACE:
```python
    cert = identity_registry.get_by_slot(slot_id)
    if cert:
        return cert.agent_uuid
    return slot_id


def resolve_sovereign_id_from_registry(agent_id: str, registry: Any) -> str:
    """BF-992: the id an agent's episodes carry, for a caller that holds a slot id and the agent registry.

    The registry is keyed by slot id; the agent it returns answers through ``resolve_sovereign_id``
    (its sovereign id, else its slot id). An id the registry does not hold, such as one that is
    already a sovereign id, and a missing registry return the id unchanged.
    """
    agent = registry.get(agent_id) if registry is not None else None
    if agent is None:
        return agent_id
    return resolve_sovereign_id(agent)
```

### 6.5 `src/probos/cognitive/qualification_tests.py` (M2)

**P2-2**
SEARCH:
```python
        # Check sufficient episodes
        episode_count = await runtime.episodic_memory.count_for_agent(agent_id)
```
REPLACE:
```python
        # Check sufficient episodes. BF-992: agent_id is the registry's key (the slot id, as the lookup
        # below uses it); the agent's episodes carry its sovereign id, so both episode reads use that.
        from probos.cognitive.episodic import resolve_sovereign_id_from_registry
        memory_id = resolve_sovereign_id_from_registry(agent_id, getattr(runtime, "registry", None))
        episode_count = await runtime.episodic_memory.count_for_agent(memory_id)
```

**P2-3**
SEARCH:
```python
        episodes = await runtime.episodic_memory.recent_for_agent(agent_id, k=3)
```
REPLACE:
```python
        episodes = await runtime.episodic_memory.recent_for_agent(memory_id, k=3)
```

### 6.6 `src/probos/acm.py` (M2)

**P2-4**
SEARCH:
```python
                try:
                    profile["episode_count"] = await runtime.episodic_memory.count_for_agent(agent_id)
```
REPLACE:
```python
                try:
                    from probos.cognitive.episodic import resolve_sovereign_id_from_registry  # BF-992
                    memory_id = resolve_sovereign_id_from_registry(agent_id, getattr(runtime, "registry", None))
                    profile["episode_count"] = await runtime.episodic_memory.count_for_agent(memory_id)
```

### 6.7 `src/probos/cognitive/memory_probes.py` (M2)

**P2-5**
SEARCH:
```python
    the drift detector.
    """
    from probos.cognitive.episodic import resolve_sovereign_id
    agent = runtime.registry.get(agent_id) if hasattr(runtime, 'registry') else None
    if agent:
        return resolve_sovereign_id(agent)
    return agent_id
```
REPLACE:
```python
    the drift detector. BF-992: the shared reader, also used by the recall probe and the ACM profile.
    """
    from probos.cognitive.episodic import resolve_sovereign_id_from_registry
    return resolve_sovereign_id_from_registry(agent_id, getattr(runtime, "registry", None))
```

### 6.8 (no pair: `holodeck/gates.py` is not touched)

### 6.9 `tests/test_bf992_slot_id_readers.py` (M2, new file)

```python
"""BF-992 (#1324): the episodic-recall probe and the consolidated profile hold a slot id and count episodes
under the agent's sovereign id, through ``resolve_sovereign_id_from_registry``.

Real ``MockEpisodicMemory`` over real ``Episode`` rows, a real ``AgentCapitalService``, and the probe's own
scoring path with a judge that answers a real ``LLMResponse``. Nothing stands in for ``count_for_agent``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.acm import AgentCapitalService
from probos.cognitive.episodic import resolve_sovereign_id_from_registry
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.qualification_tests import EpisodicRecallProbe
from probos.types import Episode, LLMResponse
from tests.test_ad566b_baseline_tests import MockAgent, MockRegistry

_SLOT = "security_officer-0"
_SOVEREIGN = "3f9c2a1e-sovereign"


async def _memory(*owners: tuple[str, int]) -> MockEpisodicMemory:
    memory = MockEpisodicMemory()
    for owner, count in owners:
        await memory.seed([
            Episode(user_input=f"{owner} watch report {i}", timestamp=float(i + 1), agent_ids=[owner])
            for i in range(count)
        ])
    return memory


class _Judge:
    """Answers every judge prompt with a score, as ``BaseLLMClient.complete`` does."""

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        return LLMResponse(content="0.9")


def _crew_agent(sovereign_id: str | None) -> MockAgent:
    agent = MockAgent(agent_id=_SLOT, response="I filed the watch report.")
    if sovereign_id is not None:
        agent.sovereign_id = sovereign_id
    return agent


def _probe_runtime(agent: MockAgent, memory: MockEpisodicMemory) -> SimpleNamespace:
    return SimpleNamespace(registry=MockRegistry(agent), episodic_memory=memory, llm_client=_Judge())


async def test_the_recall_probe_measures_episodes_held_under_the_sovereign_id() -> None:
    runtime = _probe_runtime(_crew_agent(_SOVEREIGN), await _memory((_SOVEREIGN, 3)))
    result = await EpisodicRecallProbe().run(_SLOT, runtime)

    assert result.error is None
    assert result.details["skipped"] is False
    assert result.details["episodes_tested"] == 3
    assert result.score == pytest.approx(0.9)
    assert result.agent_id == _SLOT  # the qualification store keeps results by slot id


async def test_the_recall_probe_skips_when_only_the_slot_id_holds_episodes() -> None:
    runtime = _probe_runtime(_crew_agent(_SOVEREIGN), await _memory((_SLOT, 3)))
    result = await EpisodicRecallProbe().run(_SLOT, runtime)

    assert result.details == {"skipped": True, "reason": "insufficient_episodes", "episode_count": 0}


async def test_the_recall_probe_counts_an_agent_with_no_sovereign_id_by_its_slot_id() -> None:
    runtime = _probe_runtime(_crew_agent(None), await _memory((_SLOT, 3)))
    result = await EpisodicRecallProbe().run(_SLOT, runtime)

    assert result.details["episodes_tested"] == 3


@pytest.fixture
async def acm(tmp_path: Path):
    service = AgentCapitalService(data_dir=str(tmp_path))
    await service.start()
    yield service
    await service.stop()


async def test_the_profile_counts_episodes_under_the_sovereign_id(acm: AgentCapitalService) -> None:
    await acm.onboard(_SLOT, "security_officer", "security", "security")
    member = SimpleNamespace(id=_SLOT, agent_type="security_officer", sovereign_id=_SOVEREIGN)
    runtime = SimpleNamespace(
        registry=SimpleNamespace(get={_SLOT: member}.get),
        episodic_memory=await _memory((_SOVEREIGN, 4), (_SLOT, 2)),
    )

    profile = await acm.get_consolidated_profile(_SLOT, runtime)

    assert profile["agent_id"] == _SLOT
    assert profile["episode_count"] == 4  # the sovereign id's 4: not the slot id's 2, not both


@pytest.mark.parametrize(
    ("agent_id", "registry", "expected"),
    [
        (_SLOT, MockRegistry(_crew_agent(_SOVEREIGN)), _SOVEREIGN),
        (_SLOT, MockRegistry(_crew_agent(None)), _SLOT),
        (_SOVEREIGN, MockRegistry(_crew_agent(_SOVEREIGN)), _SOVEREIGN),  # an id the registry does not hold
        (_SLOT, None, _SLOT),
    ],
    ids=["sovereign", "no-sovereign", "unknown-id", "no-registry"],
)
def test_the_shared_reader_maps_a_slot_id_to_the_memory_id(agent_id: str, registry: Any, expected: str) -> None:
    assert resolve_sovereign_id_from_registry(agent_id, registry) == expected
```

### 6.10 `PROGRESS.md` (M3)

**P3-1**
SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-992 (2026-11-24), #1324 -- three readers that hold a slot id count episodes under the agent's sovereign id: the boot camp, the recall probe and the profile.** Crew episodes carry the sovereign id (`cognitive_agent.py:12857`); the AD-638 boot camp's episode criterion, the episodic-recall probe and the ACM consolidated profile passed the slot id to `count_for_agent`. Finalization's enrolment dict carries `memory_id` (`resolve_sovereign_id`: the sovereign id, else the slot id); `AgentBootCampState.memory_id` holds it and `check_graduation` counts under it, while the coordinator's posts, DMs, trust and events stay keyed by slot. The new `resolve_sovereign_id_from_registry` (`cognitive/episodic.py`) maps a slot id to that id through the agent registry, returning an id it does not hold unchanged; the probe's count and episode read and the profile's count use it, and `memory_probes._resolve_probe_agent_id` delegates to it. Measured by `tests/test_bf992_boot_camp_episode_owner.py` (4 cases): with 5 episodes under the sovereign id and none under the slot id, an enrolled agent graduates at 61 of 120 minutes with `episodes` 5 and no timeout event; 5 under the slot id alone keep it enrolled; an agent with no sovereign id, and an enrolment with no `memory_id`, are counted by the slot id. By `tests/test_bf992_slot_id_readers.py` (8 cases): the probe measures 3 episodes held under the sovereign id (score 0.9 from the judge) and skips when only the slot id holds them; the profile reports 4 (the sovereign id's) where the slot id holds 2; the shared reader's four cases. Mutation census: 12 of 12 killed, each by its named test (the Architect's rows M1 to M11 and one added row, the probe's `TestResult.agent_id`), run once on the candidate overlay of `ad28bc34`. Not measured: a live new-crew start, the HXI's Episodes value, a drift cycle with the probe measuring. `holodeck/gates.py:79` still counts under the slot id; #1700 S1 deletes it. Contract `prompts/bf-992-episode-owner-id.md`.
```
The first 120 characters hold no ledger status word (`gen_ad_ledger.py:126-139`).

### 6.11 `DECISIONS.md` (M3)

**P3-2**
SEARCH:
```markdown
## Era V — Civilization (Phases 31-36)
```
REPLACE:
```markdown
## Era V — Civilization (Phases 31-36)

### BF-992 -- Readers that hold a slot id count episodes under the agent's sovereign id: boot camp, recall probe, profile (2026-11-24, #1324)

- *Scope.* `boot_camp.py`, `startup/finalize.py`, `cognitive/episodic.py`, `cognitive/qualification_tests.py`, `acm.py`, `cognitive/memory_probes.py`; tests `tests/test_bf992_boot_camp_episode_owner.py`, `tests/test_bf992_slot_id_readers.py`. Contract `prompts/bf-992-episode-owner-id.md`. Builds the #1324 register addition of 2026-10-29.
- *D1.* The boot camp's memory id is resolved once, at enrolment, from the agent object (`resolve_sovereign_id`), carried as `memory_id` in the enrolment dict and held on the state; an absent or empty key falls back to the slot id. Rejected: injecting the identity registry into the coordinator (a new dependency for an id the agent object already holds), and `count_agent_episodes` (it needs the agent object).
- *D2.* One shared reader for callers that hold a slot id and the agent registry: `resolve_sovereign_id_from_registry`, beside the BF-103 helpers. The recall probe and the ACM profile use it; BF-138's `_resolve_probe_agent_id` delegates to it, which also returns the id when `runtime.registry` is None (it raised before).
- *D3.* The coordinator stays keyed by slot id: posts, DMs and trust are recorded by slot (BF-907), and the graduation event keeps its keys; `episodes` is the count under the memory id.
- *D4.* `holodeck/gates.py:79` is left to #1700 S1, which deletes it.
- *D5.* The probe's skipped results still pass at 1.0; with crew episodes now counted, a measured score after a run of skipped rows can read as a decline (#1324 register row 992-R1).
- *Reversal.* Revert the commits. Qualification results the probe records meanwhile stay in the store.
```

## 7. Consumers

| Contract | Checked | Result |
|---|---|---|
| Enrolment dict | Producer `finalize.py:1003-1011`; the only `activate` call is `finalize.py:1014` (A3); test producers pass dicts without `memory_id` | Additive and optional |
| `AgentBootCampState` | Built only at `boot_camp.py:170` (A2); `get_state` has no `src/` reader (it appears only in tests) | Additive |
| Graduation result | `check_graduation` is called only by `on_agent_post` and `on_agent_dm` (`boot_camp.py:284`, `:293`), which ignore the return | None |
| `BOOT_CAMP_GRADUATION` | Emitted at `boot_camp.py:330`; persisted by name (`event_persistence.py:144`); no `src/` subscriber; no `ui/src` match (A4) | Same keys |
| Probe `TestResult` | Harness auto-baseline (`qualification.py:443-447`); drift history (`drift_detector.py:140-184`); billet gating via `required_qualifications` (no config names this probe, A6); `/qualify` (`commands_qualification.py:121`); `cognitive/counselor.py` matches the drift event names (not traced further) | Values change (D6, 992-R1) |
| `episode_count` | `routers/acm.py:42`, `routers/crew.py:265`; HXI `ServiceRecord.tsx:78` (`episode_count?: number`), `:417`; `test_ad892_crew_record_api.py:117` fakes the ACM | Same type; the value is now the sovereign count |
| `_resolve_probe_agent_id` | Six callers (`memory_probes.py:282`, `:443`, `:600`, `:795`, `:931`, `:1072`); BF-138 tests `:160-183` | Same results (D4) |
| Size pins | `test_bf906_acm_commissioning.py:563-580` (class span limit 500 at `check_architecture_principles.py:187`; `AgentCapitalService` is lines 139 to 594, about 456 lines, and grows by 2); `architecture-baseline.yaml:323-326` (`BootCampCoordinator`, methods trigger; no method added) | Hold |

**Not checked:**
- How `CrewPersonnelConsole` obtains `selected.agent_id`. It must be a slot id, or `routers/crew.py:261` would return 404.
- The Counselor's handler.
- `drill_calendar.py:99`'s id source.

## 8. Gates (the orchestrator runs all of them)

**First-hand checks on the oracle tree before the Builder starts:**
1. Every SEARCH matches exactly once, on the base `ad28bc34`. Expected: all 12 pairs match.
2. `rg -n "resolve_sovereign_id_from_registry|memory_id" src/probos/boot_camp.py src/probos/cognitive/episodic.py src/probos/startup/finalize.py`. Expected: no hits.
3. `rg -n "count_for_agent\(" src/probos`. Expected: the 14 lines listed at the end of section 10 (9 calls and 5 definitions), unchanged.
4. Copy the two new test files onto the base tree, without the source pairs, and run them at `-n 0`. Expected:
   - File 1: all four cases fail. Cases 1, 3 and 4 fail with `AttributeError: ... no attribute 'memory_id'`; case 2 fails at its `is_enrolled` assertion, because the base counts the five slot-id episodes and graduates the agent.
   - File 2: collection fails with `ImportError` (`resolve_sovereign_id_from_registry`).
5. (A1) Copy `tests/test_bf992_drift_skipped_rows.py` onto the candidate `74d6477e`, without A1-1, and run it at `-n 0`. Expected: 8 of 10 cases fail. Two pass on that tree: `test_rows_marked_not_skipped_still_count`, a guard, and `test_each_skip_helper_is_left_out[behavioral_probes]`, which BF-923 already marks inconclusive.

**Focused gate on the frozen candidate:**
```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf992_boot_camp_episode_owner.py tests/test_bf992_slot_id_readers.py tests/test_ad638_boot_camp.py tests/test_ad1270_boot_camp_lifecycle.py tests/test_ad1270_boot_camp_orientation.py tests/test_ad1270_boot_camp_repair_a1.py tests/test_ad1270_boot_camp_trust.py tests/test_ad1270a_startup_receipts.py tests/test_ad640_tiered_trust.py tests/test_ad683_ship_state_snapshot.py tests/test_acm.py tests/test_ad885_acm_unified_lens.py tests/test_ad891_duty_lens.py tests/test_ad892_crew_record_api.py tests/test_bf906_acm_commissioning.py tests/test_ad566b_baseline_tests.py tests/test_bf988_llm_response_text.py tests/test_bf138_sovereign_id_completion.py tests/test_ad582_memory_probes.py tests/test_bf923_episodic_recall_callers.py tests/test_bf992_drift_skipped_rows.py tests/test_bf711_inconclusive_not_incompetent.py tests/test_ad566c_drift_detection.py tests/test_ad567c_anchor_quality.py tests/test_bf990_qualification_drift_alert_edge.py tests/test_ad1287_s2b_drift_recorder.py tests/test_ad1186_contract_inconclusive.py -q -n 0
```
Then the broad gate once: `scripts/run_test_gate.py --label bf-992 --receipt logs/gates/bf-992.receipt.json`.

**Mutation census.** Run it once on the candidate overlay and mark it the campaign of record, with each pinned file's sha256.

| Row | Mutant | Killer |
|---|---|---|
| M1 | `boot_camp.py` count reverts to `count_for_agent(agent_id)` | File 1, case 1 |
| M2 | `finalize.py` `"memory_id": agent.id` | File 1, case 1 |
| M3 | `activate` sets `memory_id=agent_id` | File 1, case 1 |
| M4 | `activate` drops `or agent_id` | File 1, case 4 |
| M5 | Count is slot plus memory id | File 1, case 2 |
| M6 | Probe count by `agent_id` | File 2, probe case 1 |
| M7 | Probe `recent_for_agent(agent_id, ...)` | File 2, probe case 1 |
| M8 | ACM count by `agent_id` | File 2, profile case |
| M9 | Helper always returns `agent_id` | File 2, `sovereign` case and probe case 1 |
| M10 | Helper drops the `registry is not None` guard | File 2, `no-registry` case |
| M11 | Delegate returns `agent_id` | `test_bf138_sovereign_id_completion.py::...::test_resolve_probe_agent_id_resolves_sovereign` |
| A1-M1 | Delete the A1 filter | File 3: `test_a_full_window_of_skips_does_not_make_the_first_score_critical`, `test_eight_skips_do_not_make_the_first_score_a_warning`, `test_a_genuine_decline_among_skips_is_still_reported`, `test_a_window_of_only_skips_reports_no_samples`, `test_each_skip_helper_is_left_out` (three of four cases), `test_a_recall_probe_skip_keeps_its_flag_through_the_store_and_stays_out` |
| A1-M2 | Filter on key presence (`"skipped" in r.details`) | File 3: `test_rows_marked_not_skipped_still_count`, `test_a_recall_probe_skip_keeps_its_flag_through_the_store_and_stays_out` |
| A1-M3 | Truthiness without `is True` (`r.details.get("skipped")`) | Equivalent: every producer writes the bool True or False (section 16). Recorded; not counted as killed |
| A1-M4 | Bare `r.details` instead of `getattr(r, "details", None)` | `test_ad567c_anchor_quality.py::TestDriftClassification::test_specialization_high_conf_out_of_domain`, `::test_concerning_low_conf_decline`, `::test_no_decline_unclassified` (their `_MockResult` has only `score`) |

## 9. Diff Reviewer: properties to verify

1. In each of the three readers, every episode-store read uses the resolved id and none uses the slot id. The probe's `registry.get` and `TestResult.agent_id`, and the ACM's other blocks, still use the slot id.
2. The coordinator's dict key, the `ward_room_posts`/`dm_conversations` counters, both `get_trust_score` calls and both event payloads are keyed by the slot id, and the event keys are unchanged.
3. `activate` accepts a dict with no `memory_id` key, or an empty one, and then counts by `agent_id`.
4. `resolve_sovereign_id_from_registry` returns a `str` for a `str` input with a real registry, never raises when the registry is None, and returns an unknown id unchanged.
5. `_resolve_probe_agent_id` returns what it returned before for every runtime the BF-138 tests build.
6. No method is added to `BootCampCoordinator` or `AgentCapitalService`, and the ACM class span stays at or under 500 lines.
7. No new test mocks `count_for_agent`, and the new tests fail on the base tree (check 4).
8. Each tracker head holds no ledger status word in its first 120 characters, and every behaviour sentence in the trackers maps to a named test.
9. `holodeck/gates.py` is unchanged.
10. (A1) The stored-row convention `details["skipped"] is True` now means "not a data point" for drift, across five producers. Verify:
    - (a) Every producer that sets it returns without measuring anything: `memory_probes.py:189-202`, `domain_tests.py:50-61`, `collective_tests.py:48-59`, `behavioral_probes.py:29-43`, and `qualification_tests.py:433-442`, `:450-460`, `:479-489`.
    - (b) No measuring path sets it.
    - (c) Rows with `"skipped": False` still count.
    - (d) History rows without `details` still work (the doubles in `test_ad567c_anchor_quality.py:366-367`, `:427-428`, `:475-476`).
    - (e) The `drift_detector.py:150` reference in `behavioral_probes.py:24` stays valid.
    - (f) The BF-711 and BF-923 tests are unchanged and green.

## 10. Verified Against Codebase (2026-11-24, tree `542a2a68`)

```
boot_camp.py:30        async def count_for_agent(self, agent_id: str) -> int: ...
boot_camp.py:45-46     graduated: bool = False / graduated_at: float | None = None
boot_camp.py:144       crew_agents: List of dicts with agent_id, callsign, department.
boot_camp.py:162       current_trust = self._trust.get_trust_score(agent_id)
boot_camp.py:170-175   self._agents[agent_id] = AgentBootCampState(... enrolled_at=self._started_at,
boot_camp.py:209-211   # Episode count / try: / episode_count = await self._episodic.count_for_agent(agent_id)
boot_camp.py:228       trust = self._trust.get_trust_score(agent_id)
boot_camp.py:330-337   BOOT_CAMP_GRADUATION {"agent_id", "callsign", "episodes", "posts", "trust_score", "duration_minutes"}
finalize.py:1000,1005,1014  get_department import / "agent_id": agent.id, / await coordinator.activate(crew_agents)
runtime.py:3431-3437   BootCampCoordinator(config=..., trust_service=self.trust_network, episodic_memory=self.episodic_memory, ...)
episodic.py:466-486    resolve_sovereign_id / resolve_sovereign_id_from_slot (cert = identity_registry.get_by_slot(slot_id))
episodic.py:4344-4363  count_for_agent matches agent_ids_json
episodic_mock.py:115,236,241,257  seed / recent_for_agent / count_for_agent / get_stats
orientation.py:128-140 count_agent_episodes: sovereign_id or agent.id
agent_onboarding.py:446-456  cert = ... resolve_or_issue(slot_id=agent.id ...) / agent.sovereign_id = cert.agent_uuid
cognitive_agent.py:12857  agent_ids=[getattr(self, 'sovereign_id', None) or self.id],
consensus/trust.py:303-317, 1017-1031  slot-keyed; get_trust_score calls get_score
proactive.py:4279, 5137  on_agent_post(agent.id, _ch_type) / on_agent_dm(agent.id)
qualification_tests.py:444-445, 460, 473-474, 535-537  count / registry.get / recent_for_agent / TestResult(agent_id=agent_id
commands_qualification.py:121  results = await harness.run_all(agent.id, runtime)
drift_detector.py:438-441  "Returns slot IDs (agent.id), NOT sovereign IDs."
memory_probes.py:88-99  _resolve_probe_agent_id; callers :282 :443 :600 :795 :931 :1072
acm.py:443, 487, 501-507  get_consolidated_profile / registry.get / count_for_agent(agent_id)
routers/acm.py:37-42; routers/crew.py:258-265  route ids
ui/src/components/personnel/ServiceRecord.tsx:78, 180, 417
qualification.py:443-447  auto-baseline when result.error is None
crew_utils.py:58-60    _WARD_ROOM_CREW includes "security_officer"
config_models/crew.py:28-53  min_episodes 5, posts 3, DMs 1, trust 0.55, 60 min, timeout 120
check_architecture_principles.py:187-188  SRP_MAX_BODY_LINES = 500 / SRP_MAX_DIRECT_METHODS = 15
open-ads-report.md:32  | BF | **BF-991** | **BF-992** |
count_for_agent( callers in src: boot_camp:211 acm:505 qualification_tests:445 holodeck/gates:79
  cognitive_agent:11844 proactive:2006,2864 introspective_telemetry:91 orientation:140 (+ defs episodic:4344,
  episodic_mock:241, participant_index:181, protocols boot_camp:30, introspective_telemetry:41)
```

## Absence Verified (2026-11-24)

| # | Claim | Run | Found | Holds |
|---|---|---|---|---|
| A1 | `resolve_sovereign_id_from_registry` is a new name | `rg resolve_sovereign_id_from_registry` | nothing | yes |
| A2 | Only `activate` builds `AgentBootCampState` | `rg "AgentBootCampState\("` | `boot_camp.py:170` only | yes |
| A3 | Only finalization calls `activate` | `rg "coordinator\.activate\(\|boot_camp\.activate\("` src | `finalize.py:1014` | yes |
| A4 | Nothing subscribes to the graduation event | `rg "BOOT_CAMP_GRADUATION\|boot_camp_graduation"` (py, ts, tsx) | `events.py:407`, `event_persistence.py:144`, `boot_camp.py:330`, tests | yes |
| A5 | No test asserts `count_for_agent`'s argument on these paths | `rg "count_for_agent\.(assert\|call_args\|await_args)" tests` | nothing (`test_api_profile.py:129` records calls for `/api/agent`, a different route) | yes |
| A6 | No config requires the probe | `rg required_qualifications` (yaml, yml, json) | nothing | yes |
| A7 | Recent BFs carry no roadmap row | `rg "BF-98[0-9]" docs/development/roadmap.md` | nothing | yes, so no roadmap row |
| A8 | No `src/` reader of `get_state` | `rg "boot_camp\.get_state\("` src | nothing | yes |

## 11. What this does NOT change, and recorded limits

- **Not touched:**
  - `holodeck/gates.py:79` (#1700 S1 deletes it; #1700's Problem item 3 and S1 row already record it).
  - The other `count_for_agent` callers, which already resolve the id (section 10).
  - `routers/agents.py` (`/api/agent/{id}/profile`, which already resolves at `:495-498`).
  - Trust keys, the probe's skip semantics, the skip helpers of the other probes, the harness auto-baseline (`qualification.py:443-447`), the Counselor, the HXI types.
  - The drift detector beyond amendment A1's one filter (directly after `drift_detector.py:150`). Its statistics, severities, direction, events and the BF-711 line are unchanged.
- **Recorded limit, D4:** a `runtime.registry` that is `None` now yields the id instead of raising.
- **Recorded limit, D7:** skipped results still pass and still set the first baseline, so a signal's `direction` can read "declined" against a 1.0 baseline while its severity is normal. No event fires (`drift_detector.py:468`). Owner: the AD-1186 item in #1324.
- **Not measured:**
  - Live graduation timing.
  - Additional model calls per drift cycle. Each crew agent with at least 3 episodes now gets up to 3 probe sends and 3 judge calls per tier-1 run.

## 12. Issue texts

**#1324:** the register addition is a comment, not a body checkbox. The body holds no register list and says it does not restate the linked lists, so the body is not edited. The tick is a landing comment:

> **Register addition (2026-10-29, `claude-architect`) "the AD-638 boot camp's episode criterion counts under the slot id": built as BF-992** (PR #<n>, merge `<sha>`), <date>. Enrolment carries the agent's memory id and `check_graduation` counts under it; the episodic-recall probe and the consolidated profile count through `resolve_sovereign_id_from_registry`. Evidence: `tests/test_bf992_boot_camp_episode_owner.py` (5 episodes under the sovereign id, none under the slot id: graduates at 61 of 120 min, no timeout event) and `tests/test_bf992_slot_id_readers.py`; census <killed/total>; gate receipt `logs/gates/bf-992.receipt.json` <counts>.
>
> **Register (BF-992):**
> - **992-R1 (P2, ordinary reach; measured, repaired here, part residual):** measured with the real `DriftDetector` and the default config. With k skipped 1.0 rows in the window, the first measured score gives |z| = sqrt(k): a Counselor warning at k >= 4 and a Bridge/Captain critical at a full window, lasting about three weekly runs. Every crew agent was exposed once BF-992 counted their episodes. Repaired in B13 (amendment A1): `DriftDetector._analyze_single` drops rows whose `details["skipped"] is True`, next to the BF-711 `inconclusive` filter. This covers stored and new rows from memory_probes, domain_tests, collective_tests and the recall probe, with no migration (`tests/test_bf992_drift_skipped_rows.py`). **Residual, owned by the AD-1186 item:** skipped results still pass and still set the first baseline (`qualification.py:444`), so `direction` can read "declined" against a 1.0 baseline while severity is normal and no event fires (`drift_detector.py:196-197`, `:468`).
> - **992-R2:** `holodeck/gates.py:79` still counts under the slot id; #1700 S1 deletes it.
> - **992-R3 (not measured):** a live new-crew start's graduations by criteria; the HXI Episodes value; the extra model calls per drift cycle.

**#1700:** no edit.

**PR:** `Refs #1324.` It carries no closing keyword and avoids the words close, fix and resolve.

## 13. Prior art and blind spots

**Internal prior art:**
- BF-103's helpers (`episodic.py:462-486`): the new reader sits with them.
- BF-138's `_resolve_probe_agent_id`: absorbed as a delegate.
- BF-923's `count_agent_episodes`: the same fallback, but it needs the agent object, so it is not reused.
- BF-907's slot-keyed trust: why the coordinator stays on the slot id.
- `routers/agents.py:495-498` and `introspective_telemetry.py:79-91`: the same resolve-then-count pattern.

**External prior art:** ProbOS-specific id plumbing with no outside analogue, so no searches were made and `reference-projects.md` was not reviewed for this item.

**Blind spots:**
1. The drift reading (992-R1).
2. Model-call cost (992-R3).
3. An agent whose identity resolution failed at wiring (`agent_onboarding.py:477-478`) has no `sovereign_id`. It stores and is counted under its slot id, consistently.
4. A route caller holding a sovereign id gets it back unchanged from the reader, so it is counted correctly.
5. Graduating earlier ends the AD-683 snapshot in DMs earlier.

## 14. Acceptance criteria

1. The 22 new cases pass (12 in the two files of section 6, 10 in the file of 16.2), and the focused gate in section 8 passes at `-n 0`.
2. Check 4 shows the new tests fail on the base tree, and check 5 shows 8 of the 10 A1 cases fail without A1-1. Census rows M1 to M11, A1-M1, A1-M2 and A1-M4 are killed by their killers; A1-M3 is recorded as equivalent.
3. The section 9 properties hold, and the Diff Reviewer verdict is READY on round 1 and on the A1 delta (round 2, with property 10).
4. The receipted broad gate is green on the merged tree.
5. The trackers hold P3-1, P3-2, A1-3 and A1-4 with the placeholders filled, and the ledger is regenerated.
6. The #1324 landing comment is posted with 992-R1 to 992-R3.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Results on the oracle trees (the orchestrator, 2026-11-24)

The base oracle is a clean detached tree at `ad28bc34`; the candidate is that tree with the source and test pairs of section 6 applied by `contract_tools.py` (P1-1 to P2-5 and the two new files; every SEARCH occurred once at its turn; `ws_ambiguity.py`: 0 hazards; `git diff --check` clean). The two tracker pairs P3-1 and P3-2 wait for the census and are applied after it. The rows ran with `bf992_rows.py` and the focused runs with `run_focused.py` (both outside the repository): one pytest process per selector, `-n 0 -p no:randomly` (the random order only where named), `HOME` and `USERPROFILE` redirected to an empty directory (empty afterwards), the cases read from the JUnit file.

### 15.1 Checks 1 to 3 of section 8, on `ad28bc34`

- Check 1: all 12 pairs matched exactly once. Check 2: no hits.
- Check 3: 14 lines, the draft's list unchanged. Calls: `acm.py:505`, `boot_camp.py:211`, `cognitive_agent.py:11844`, `holodeck/gates.py:79`, `proactive.py:2006` and `:2864`, `introspective_telemetry.py:91`, `orientation.py:140`, `qualification_tests.py:445`. Definitions: `boot_camp.py:30`, `introspective_telemetry.py:41`, `episodic_mock.py:241`, `episodic.py:4344`, `participant_index.py:181`.

### 15.2 Check 4: the two new test files on the clean base tree

| File | Result on the base |
|---|---|
| `test_bf992_boot_camp_episode_owner.py` | 4 failed. Cases 1, 3 and 4: `AttributeError: 'AgentBootCampState' object has no attribute 'memory_id'`. Case 2 (`test_episodes_under_the_slot_id_alone_do_not_count_for_an_agent_with_a_sovereign_id`): `assert is_enrolled(...)` is False, because the base counts the five slot-id episodes and graduates the agent |
| `test_bf992_slot_id_readers.py` | 1 collection error: `ImportError` for `resolve_sovereign_id_from_registry` |

The draft expected case 2 to pass on the base. It fails, which is what makes it a regression pin; section 8 is corrected in place.

### 15.3 Candidate runs

- The new files on the candidate: 4 passed (file 1) and 8 passed (file 2). The BF-138 file: 15 passed.
- The focused command of section 8 (20 files), `-n 0`: 424 passed in the given order (96.66 s), in reverse (68.74 s) and in the default random order (64.75 s).
- The same command plus 16 more consumer files (`test_ad1270_boot_camp_tracker_retired`, `test_bf941_cold_start_detector`, `test_bf103_episode_id_mismatch`, `test_mention_fanout_episode_owner`, `test_bf906_crew_enrollment_boot`, `test_bf906_doctor_check`, `test_onboarding`, `test_ad723a_1_consumer_migration`, `test_ad723a_2_wr_consumer_migration`, `test_ad729b_peer_observation_training`, `test_bf874_dm_callsign_and_fail_closed`, `test_bf874_dm_e2e`, `test_bf901_s2_journal_token_provenance`, `test_bf917_template_skills_and_recommission`, `test_bf922_output_grounding`, `test_issue1419_failed_start_rollback`): 36 files, 1010 passed in 369.88 s.

### 15.4 Mutation census (the campaign of record)

Run once on the candidate overlay (tree `ad28bc34` plus the source and test pairs of section 6), one mutant at a time, each file restored byte for byte. **12 of 12 killed**, each by its named killer. M1 to M11 are the draft's rows; M12 is an added row.

| ID | Verdict | Killed by |
|---|---|---|
| M1 | KILLED | file 1: case 1 (`assert not is_enrolled`) and case 2 |
| M2 | KILLED | file 1: case 1 (`memory_id` is the slot id) and case 2 |
| M3 | KILLED | file 1: case 1 and case 2 |
| M4 | KILLED | file 1: case 4 (`None == 'crew-1'`) |
| M5 | KILLED | file 1: case 2 and case 3 (`[10] == [5]`) |
| M6 | KILLED | file 2: probe case 1 (`skipped` is True) |
| M7 | KILLED | file 2: probe case 1 |
| M8 | KILLED | file 2: profile case (`2 == 4`) |
| M9 | KILLED | file 2: probe case 1, probe skip case, profile case and the `sovereign` case |
| M10 | KILLED | file 2: `no-registry` case (`AttributeError: 'NoneType' object has no attribute 'get'`) |
| M11 | KILLED | `test_bf138_sovereign_id_completion.py::test_resolve_probe_agent_id_resolves_sovereign` |
| M12 | KILLED | file 2: probe case 1 (the probe's `TestResult.agent_id` takes the memory id; it must stay the slot id) |

M12 mutates the 10th `agent_id=agent_id,` line of `qualification_tests.py` (the probe's final `TestResult`) to `agent_id=memory_id,`.

Pinned files, as they stand in the oracle's working copy (sha256, and the git blob id that `git hash-object --path` gives under autocrlf):

| File | sha256 | Blob id |
|---|---|---|
| `src/probos/acm.py` | `87c7c5256a6ed24864b7da962506e391e733cbcac79ab51c5626fead5e732544` | `4b1bbec813fee946dc38e518541085f40a7a2af5` |
| `src/probos/boot_camp.py` | `e1fff99b59c095170546526e86596e7e3542a1deae740e7c66753f01166330e5` | `852bcc58cde3f3d1db862acf8bba3312cefed710` |
| `src/probos/cognitive/episodic.py` | `d6aca69d755d4cdb71a481599e885a2cd791b418943b966c444288e259137c53` | `43a206bdf0787c6026cf2c767d154155abed8b6f` |
| `src/probos/cognitive/memory_probes.py` | `959a3e4c7e464f88f6582991dd77e5c96a5d32691f0c789d421f740d34c81a0b` | `7eed0d7b2ec5c730cf54bd6097930a9beae88366` |
| `src/probos/cognitive/qualification_tests.py` | `6232f18fb9ae68ef20991401cf47d5600c6ce689f6fc52e8bc09df6716a7dafb` | `384d3c08e0fda72a7a5748a76c4aba56db95ca2a` |
| `src/probos/startup/finalize.py` | `f9d44791d9a0c7fad468796076ef249292eef8e4436f962458aeab917e5ff935` | `f0ede172aa139369d8c6bf6e2ce99cf771f79c5f` |
| `tests/test_bf992_boot_camp_episode_owner.py` | `ce4f4f4a01d583aa7bde984d2d1bf492e9a31fe6a45daec1685c667d7d3f25aa` | `1043d3eb648d72937f59ebff56f7521e5527bccf` |
| `tests/test_bf992_slot_id_readers.py` | `42adef223117ef694baa9db990ffd47bfd4c640f4dd127a37cde94d3ee44579f` | `35fab2d5a12db1e58becbdd77d6dabd052ebe144` |

### 15.5 Tracker milestone (M3) on the oracle

P3-1 and P3-2 applied by the tool to the candidate (each SEARCH occurred once at its turn, `ws_ambiguity.py` 0 hazards on all 12 pairs, `git diff --check` clean), then `scripts/gen_ad_ledger.py -P` (no `--online`) rewrote `docs/development/ad-ledger-snapshot.json` (`captured_at`, `head` `ad28bc34`, `subject_count` 4543 to 4548) and `docs/development/open-ads-report.md` (BF shipped 632 to 633; the BF numbers below the ceiling that no authority mentions 352 to 351, BF-992 leaving that list; BF ceiling still BF-993). `gen_ad_ledger.py --check`: the ledger is current.

### 15.6 Amendment A1 (review round 1): results on the oracle trees

The oracle for the A1 rows is a clean detached tree at `74d6477e` (the frozen candidate that round 1 reviewed) with the four operations of section 16 applied by `contract_tools.py` (each SEARCH occurred once at its turn; `ws_ambiguity.py`: 0 hazards; `git diff --check` clean). A second clean tree at `74d6477e` is the base of check 5. The rows ran with `bf992_a1_rows.py` and the focused runs with `run_focused.py` (both outside the repository) under the conditions of section 15: one pytest process per selector, `-n 0 -p no:randomly` (the random order only where named), `HOME` and `USERPROFILE` redirected to an empty directory (empty afterwards), the cases read from the JUnit file. The measurement of the row itself, with the real `DriftDetector`, `QualificationStore` and `QualificationConfig` defaults, is the table in the first paragraph of section 16 (`drift_probe_b13.py`, outside the repository).

- **Check 5** (the new file on the clean candidate, without A1-1): 8 failed, 2 passed. The two that pass are `test_rows_marked_not_skipped_still_count` (a guard) and `test_each_skip_helper_is_left_out[behavioral_probes]` (BF-923 already marks those skips inconclusive).
- **Candidate** (A1-1 and the new file applied): the new file 10 passed; `test_ad567c_anchor_quality.py` 23 passed.
- **The focused command of section 8** (27 files, `-n 0`): 567 passed in the reversed order (76.25 s) and in the default random order (76.25 s). With four more consumer files (`test_ad566d_domain_tests`, `test_ad566e_collective_tests`, `test_ad729c_peer_observation_monitor`, `test_behavioral_metrics`) in the given order: 31 files, 707 passed (84.41 s).
- **Census rows**, one mutant at a time on the candidate overlay (`74d6477e` plus A1-1 and the new file), each file restored byte for byte:

| ID | Verdict | Killed by |
|---|---|---|
| A1-M1 | KILLED | the new file: 8 failed (the four skip-window cases, three of the four helper cases and the recall-probe store case) |
| A1-M2 | KILLED | the new file: 2 failed (`test_rows_marked_not_skipped_still_count` and the recall-probe store case) |
| A1-M3 | SURVIVED | equivalent: every producer writes the bool True or False; recorded, not counted as killed |
| A1-M4 | KILLED | `test_ad567c_anchor_quality.py`: 3 failed (`AttributeError: '_MockResult' object has no attribute 'details'`) |

Pinned files, as they stand in the A1 oracle's working copy (sha256):

| File | sha256 |
|---|---|
| `src/probos/cognitive/drift_detector.py` | `23723971bdefb8e60f729e53ff0e9b546d8a6c03e9e63d84cdc1efa305838c09` |
| `tests/test_bf992_drift_skipped_rows.py` | `2a09bd4e1bb212e3ce74f004dabbde361a4826d4b7cd0938c2ce8845dff1de35` |

## 16. Amendment A1 (review round 1: row 992-R1)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-24 (Architect decision B on the round-1 register row).

**What changed and why.** Review round 1 (`gpt-6.1-sol`, APPROVED, 0 blocking) and the orchestrator's probe (`drift_probe_b13.py`, outside the repository) measured row 992-R1 with the real `DriftDetector`, `QualificationStore` and `QualificationConfig` defaults (window 20, minimum 3 samples, warning 2.0 sigma, critical 3.0 sigma, `config.py:3642-3646`). The setup was k skipped 1.0 rows followed by a healthy agent's 0.9, 0.9, 0.85, 0.9. The first run was normal at k 2 and 3, a warning at k 4 (z -2.0) and at k 8, and critical at a full window of 19 (z -4.36). The noise lasted about three weekly runs. The control, with the probe measuring throughout, stayed normal. For one measured score among k equal rows, |z| = sqrt(k) whatever the size of the deviation. Every crew agent has been skipped on this probe since the defect began. Without A1, the first drift run after this item lands would therefore raise a Counselor warning or a Bridge/Captain critical for each crew agent with at least 3 episodes. No trust, rank or lifecycle penalty follows; the reviewer ran the Counselor handler and got a healthy assessment and no intervention. It is still the false alarm BF-711 exists to prevent, and it has ordinary reach, so this item repairs it.

**D7.**
- **The filter.** `DriftDetector._analyze_single` drops rows whose `details["skipped"] is True`. The new line sits directly after BF-711's `inconclusive` filter, so the `drift_detector.py:150` reference in `behavioral_probes.py:24` stays valid.
- **Why that flag.** It is the one marker every skip helper writes: `memory_probes.py:189-202`, `domain_tests.py:50-61`, `collective_tests.py:48-59`, `behavioral_probes.py:29-43` and the recall probe at `qualification_tests.py:433-442`, `:450-460` and `:479-489`. Each of these returns without measuring anything. Measuring paths write `"skipped": False`.
- **Why read it from the row.** The store already persists `details` (`qualification.py:363`), so the rows already stored on the vessel are covered. No migration and no producer change is needed.
- **Why `getattr`.** The drift tests' doubles carry only `score` (`test_ad567c_anchor_quality.py:366-367`, `:427-428`, `:475-476`).
- **Rejected:**
  - Marking the skips `inconclusive` at their producers. That covers new rows only, so the stored windows would still raise the first-run alarm.
  - Holding this item for the AD-1186 item.
- **What stays the same:**
  - Skipped results still pass and still set the first baseline (`qualification.py:444`). A signal's `direction` can therefore read "declined" against a 1.0 baseline while its severity is normal (`drift_detector.py:196-197`). No event fires, because the scheduler emits only warning and critical (`drift_detector.py:468`).
  - That residual stays with the AD-1186 item in #1324.
  - `DriftSignal` and the detector's signature are unchanged. The detector is built in one place (`runtime.py:3236`).

**Milestones** (the orchestrator commits by plumbing; every body says `Refs #1324.`):
- **M4** (drift detector and its tests): A1-1 and the new file in 16.2.
  Subject: `Drift window leaves out results a probe skipped, as it does inconclusive ones`
- **M5** (trackers and ledger): A1-3 and A1-4, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`). Stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` if they change.
  Subject: `Trackers for the drift window and skipped probe results`

One Builder delegation covers M4 and M5, in under about 20 tool calls.

**Builder: may and may not.** Section 5 applies unchanged.

**Review.** Round 2 reviews the A1 delta plus the stored-row convention check (section 9, property 10). `DriftDetector`'s interface is not a shared contract here. The convention `details["skipped"] is True` becomes one, across five producers.

**Verified for A1 (2026-11-24, HEAD `74d6477e`):**
```
drift_detector.py:144-150   BF-711 comment / history = [r for r in history if not getattr(r, "inconclusive", False)]
drift_detector.py:158-170   sample_count == 0 -> direction "stable", severity "normal"
drift_detector.py:196-203   severity: < drift_min_samples -> normal; >= critical sigma; >= warning sigma
drift_detector.py:468       events only for severity warning or critical
qualification.py:82,92      details: dict = field(default_factory=dict) / inconclusive: bool = False
qualification.py:363        details=json.loads(row[9]) if row[9] else {}
qualification.py:255-264    get_history(..., *, limit=20) ORDER BY timestamp DESC
qualification.py:443-447    auto-baseline when result.error is None
memory_probes.py:189-202    _make_skip_result: score 1.0, passed True, details {"skipped": True, ...}
domain_tests.py:50-61       _skip_result: score 1.0, passed True, details {"skipped": True, ...}
collective_tests.py:48-59   _skip_result: score 0.0, passed True, details {"skipped": True, ...}
behavioral_probes.py:29-43  _skip_result: inconclusive=True, details {"skipped": True, ...}
qualification_tests.py:433-442, 450-460, 479-489  recall probe skip returns: score 1.0, passed True, no inconclusive
test_ad567c_anchor_quality.py:366-367, 427-428, 475-476  _MockResult has only `score`
test_bf923_episodic_recall_callers.py:582-601  real QualificationStore + DriftDetector(store, QualificationConfig()) pattern
runtime.py:3234-3236        the one DriftDetector construction
pyproject.toml:181          asyncio_mode = "auto"
```
**Absence verified (A1):**
- Claim: no other producer sets `details["skipped"] = True`. Run: `rg "[\"']skipped[\"']\s*:" src/probos`. Found: the seven skip sites above; `"skipped": False` on measuring paths; and quartermaster, workforce and emergent_leadership dicts, which are not `TestResult` details. Holds.
- Claim: no drift test file pins skipped rows. Run: `rg skipped tests/*drift*.py`. Found: nothing. Holds.

### 16.1 `src/probos/cognitive/drift_detector.py` (M4)

**A1-1**
SEARCH:
```python
        # stay available for forensics.
        history = [r for r in history if not getattr(r, "inconclusive", False)]

        # Get baseline
```
REPLACE:
```python
        # stay available for forensics.
        history = [r for r in history if not getattr(r, "inconclusive", False)]
        # BF-992 (992-R1): a skipped result measured nothing either. The skip helpers of memory_probes,
        # domain_tests, collective_tests and the recall probe pass at a fixed score without setting
        # inconclusive, so a window of them made any first real score read as drift (|z| = sqrt(k)).
        # Read from details so rows already stored are covered without a migration.
        history = [
            r for r in history
            if not (isinstance(getattr(r, "details", None), dict) and r.details.get("skipped") is True)
        ]

        # Get baseline
```

### 16.2 `tests/test_bf992_drift_skipped_rows.py` (M4, new file, A1-2)

```python
"""BF-992 amendment A1 (#1324, register row 992-R1): the drift window leaves out results a probe skipped.

The skip helpers return a passing result at a fixed score with no error and, apart from
``behavioral_probes``, without BF-711's ``inconclusive`` flag. Once BF-992 counted crew episodes, a crew
agent's window held only skipped 1.0 rows, and for one measured score among k equal rows |z| = sqrt(k)
whatever its size: a warning at k 8, critical at a full window. A skip measured nothing, so
``DriftDetector._analyze_single`` drops it beside the ``inconclusive`` filter, reading ``details["skipped"]``
from the row so rows already stored are covered without a migration.

Real ``QualificationConfig`` and ``DriftDetector`` throughout; the last case uses a real
``QualificationStore`` and the real recall probe. Nothing stands in for the detector.
"""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from probos.cognitive import behavioral_probes, collective_tests, domain_tests, memory_probes
from probos.cognitive.drift_detector import DriftDetector
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.qualification import QualificationStore
from probos.cognitive.qualification import TestResult as QualTestResult  # aliased: pytest collects Test* names
from probos.cognitive.qualification_tests import EpisodicRecallProbe
from probos.config import QualificationConfig
from probos.types import Episode, LLMResponse
from tests.test_ad566b_baseline_tests import MockAgent, MockRegistry

_SLOT = "security_officer-0"
_SOVEREIGN = "3f9c2a1e-sovereign"
_SKIPPED = {"skipped": True, "reason": "insufficient_episodes", "episode_count": 0}


def _result(score: float, details: dict[str, Any] | None = None) -> QualTestResult:
    return QualTestResult(
        agent_id="a", test_name="t", tier=1, score=score, passed=True,
        timestamp=time.time(), duration_ms=1.0, details=dict(details or {}),
    )


def _skipped() -> QualTestResult:
    """What the recall probe stored for every crew agent before BF-992: a pass at 1.0, no error."""
    return _result(1.0, _SKIPPED)


def _unmarked(rows: list[QualTestResult]) -> list[QualTestResult]:
    """The same rows without the skip flag: the window as the detector read it before A1."""
    return [dataclasses.replace(r, details={}) for r in rows]


class _Store:
    def __init__(self, history: list[QualTestResult]) -> None:
        self._history = history

    async def get_history(self, agent_id: str, test_name: str, limit: int = 0):
        return self._history

    async def get_baseline(self, agent_id: str, test_name: str):
        # The harness auto-baselines the first result with no error, which was a skip (qualification.py:444).
        return dataclasses.replace(_skipped(), is_baseline=True)


async def _signal(history: list[QualTestResult]) -> Any:
    return await DriftDetector(store=_Store(history), config=QualificationConfig())._analyze_single("a", "t")


async def test_a_full_window_of_skips_does_not_make_the_first_score_critical() -> None:
    history = [_result(0.9)] + [_skipped() for _ in range(19)]  # newest first

    assert (await _signal(_unmarked(history))).severity == "critical"  # the premise: z = -4.36
    signal = await _signal(history)

    assert signal.sample_count == 1
    assert signal.severity == "normal"


async def test_eight_skips_do_not_make_the_first_score_a_warning() -> None:
    history = [_result(0.9)] + [_skipped() for _ in range(8)]

    assert (await _signal(_unmarked(history))).severity == "warning"  # the premise: z = -sqrt(8)
    signal = await _signal(history)

    assert signal.sample_count == 1
    assert signal.severity == "normal"


async def test_a_genuine_decline_among_skips_is_still_reported() -> None:
    history = [_result(0.1)]
    for _ in range(9):
        history += [_skipped(), _result(0.9)]
    history.append(_skipped())

    signal = await _signal(history)

    assert signal.sample_count == 10
    assert signal.current_score == pytest.approx(0.1)
    assert signal.direction == "declined"
    assert signal.severity in ("warning", "critical")  # z = -3.0 over the ten measured scores


async def test_rows_marked_not_skipped_still_count() -> None:
    signal = await _signal([_result(0.1, {"skipped": False}) for _ in range(4)])

    assert signal.sample_count == 4
    assert signal.direction == "declined"


async def test_a_window_of_only_skips_reports_no_samples() -> None:
    signal = await _signal([_skipped() for _ in range(5)])

    assert signal.sample_count == 0
    assert signal.direction == "stable"
    assert signal.severity == "normal"


_SKIP_HELPERS: dict[str, Callable[[], QualTestResult]] = {
    "memory_probes": lambda: memory_probes._make_skip_result("a", "t", 1, time.time(), "no_episodic_memory"),
    "domain_tests": lambda: domain_tests._skip_result("a", "t", 2, "not_in_department"),
    "collective_tests": lambda: collective_tests._skip_result("t", "no_engine"),
    "behavioral_probes": lambda: behavioral_probes._skip_result("t", "no_engine"),
}


@pytest.mark.parametrize("producer", sorted(_SKIP_HELPERS))
async def test_each_skip_helper_is_left_out(producer: str) -> None:
    skip = _SKIP_HELPERS[producer]()
    assert skip.details["skipped"] is True and skip.error is None  # a pass that measured nothing

    signal = await _signal([_result(0.9)] + [dataclasses.replace(skip) for _ in range(8)])

    assert signal.sample_count == 1
    assert signal.severity == "normal"


class _Judge:
    """Answers every judge prompt with a score, as ``BaseLLMClient.complete`` does."""

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        return LLMResponse(content="0.9")


async def _recall_runtime(episodes: int) -> SimpleNamespace:
    agent = MockAgent(agent_id=_SLOT, response="I filed the watch report.")
    agent.sovereign_id = _SOVEREIGN
    memory = MockEpisodicMemory()
    await memory.seed([
        Episode(user_input=f"watch report {i}", timestamp=float(i + 1), agent_ids=[_SOVEREIGN])
        for i in range(episodes)
    ])
    return SimpleNamespace(registry=MockRegistry(agent), episodic_memory=memory, llm_client=_Judge())


async def test_a_recall_probe_skip_keeps_its_flag_through_the_store_and_stays_out(tmp_path: Path) -> None:
    probe = EpisodicRecallProbe()
    skipped = await probe.run(_SLOT, await _recall_runtime(2))
    measured = await probe.run(_SLOT, await _recall_runtime(3))
    assert skipped.details["skipped"] is True and skipped.error is None and skipped.score == 1.0
    assert measured.details["skipped"] is False

    store = QualificationStore(data_dir=tmp_path)
    await store.start()
    try:
        now = time.time()
        for i in range(19):
            await store.save_result(dataclasses.replace(skipped, timestamp=now - 3600.0 * (i + 3)))
        for i in range(2):
            await store.save_result(dataclasses.replace(measured, timestamp=now - 3600.0 * (i + 1)))
        history = await store.get_history(_SLOT, probe.name)
        signal = await DriftDetector(store, QualificationConfig())._analyze_single(_SLOT, probe.name)
    finally:
        await store.stop()

    assert len(history) == 20
    assert sum(1 for r in history if r.details.get("skipped") is True) == 18  # the flag survives SQLite
    assert signal.sample_count == 2
    assert signal.severity == "normal"
```

### 16.3 `PROGRESS.md` (M5)

**A1-3**
SEARCH:
```markdown
run once on the candidate overlay of `ad28bc34`. Not measured: a live new-crew start, the HXI's Episodes value, a drift cycle with the probe measuring.
```
REPLACE:
```markdown
run once on the candidate overlay of `ad28bc34`. Amendment A1 (review round 1, #1324 row 992-R1): `DriftDetector._analyze_single` also leaves out rows whose `details["skipped"]` is True, beside the BF-711 `inconclusive` filter, so a window of skipped results no longer makes a crew agent's first measured recall score read as drift. Measured by `tests/test_bf992_drift_skipped_rows.py` (10 cases): after 19 skipped 1.0 rows a measured 0.9 counts as 1 sample at severity normal, where the same rows without the flag read critical; after 8 they read warning and the flagged window stays normal; a 0.1 after nine 0.9 scores, with ten skipped rows among them, still reads at least warning over 10 samples; rows marked `"skipped": False` still count; a window of skips alone gives 0 samples; the skip helpers of `memory_probes`, `domain_tests`, `collective_tests` and `behavioral_probes` are each left out; a real recall-probe skip keeps its flag through a real `QualificationStore`, and 2 measured rows of 20 are counted. A1 census: A1-M1, A1-M2 and A1-M4 killed and A1-M3 recorded as equivalent, run once on the overlay of `74d6477e` plus the A1 pairs. Skipped results still pass and still set the first baseline (`qualification.py:444`), so a signal's direction can read "declined" at severity normal with no event; that part stays with the AD-1186 item in #1324. Not measured: a live new-crew start, the HXI's Episodes value, a live drift cycle with the probe measuring.
```

### 16.4 `DECISIONS.md` (M5)

**A1-4**
SEARCH:
```markdown
- *D5.* The probe's skipped results still pass at 1.0; with crew episodes now counted, a measured score after a run of skipped rows can read as a decline (#1324 register row 992-R1).
- *Reversal.* Revert the commits. Qualification results the probe records meanwhile stay in the store.
```
REPLACE:
```markdown
- *D5.* The probe's skipped results still pass at 1.0 and still set the first baseline; with crew episodes now counted, a run of them in the drift window made the first measured score read as drift (#1324 register row 992-R1, measured in review round 1).
- *D6.* Amendment A1: the drift window also leaves out rows whose `details["skipped"]` is True, beside BF-711's `inconclusive` filter (`drift_detector.py`, after `:150`). A skip measured nothing, whichever probe wrote it (`memory_probes`, `domain_tests`, `collective_tests`, the recall probe; `behavioral_probes` already marks its skips inconclusive, BF-923). The flag is read from the stored row, so rows already in the store are covered without a migration. Tests `tests/test_bf992_drift_skipped_rows.py`. Rejected: marking the skips inconclusive at their producers (new rows only; the stored windows would still raise the first-run alarm), and holding this item for the AD-1186 item. The skipped baseline and the signal's `direction` stay with the AD-1186 item in #1324.
- *Reversal.* Revert the commits; reverting A1's commit alone restores counting of skipped rows in the drift window. Qualification results the probe records meanwhile stay in the store.
```
