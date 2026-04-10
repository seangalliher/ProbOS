# BF-138: Sovereign ID Completion — Remaining Slot ID Leaks

| Field | Value |
|-------|-------|
| **Ticket** | BF-138 |
| **Priority** | Critical |
| **Scope** | OSS (`src/probos/cognitive/memory_probes.py`, `src/probos/cognitive/drift_detector.py`, `src/probos/routers/agents.py`, `src/probos/experience/commands/session.py`, `src/probos/cognitive/feedback.py`, `src/probos/cognitive/cognitive_agent.py`) |
| **Principles Compliance** | DRY (`resolve_sovereign_id` / `resolve_sovereign_id_from_slot` reuse), Fail Fast (recall exceptions at warning level, not debug), Defense in Depth (ID resolution at every storage boundary), Single Responsibility (ID resolution is the episodic module's concern, callers don't pick ID types) |
| **Dependencies** | BF-103 (Sovereign ID normalization, COMPLETE), AD-441 (Persistent Agent Identity, COMPLETE) |
| **Absorbs** | BF-103 scope exclusion for HXI chat history API — now needs fixing |

---

## Bug Description

**Symptom:** All cognitive-pipeline memory recall probes (SeededRecallProbe, KnowledgeUpdateProbe, TemporalReasoningProbe, CrossAgentSynthesisProbe, MemoryAbstentionProbe) fail systemically at or near 0.000 scores. RetrievalAccuracyBenchmark passes (1.000). AD-584a/b/c scoring improvements had zero measurable impact.

**Root Cause:** BF-103 fixed sovereign ID normalization for production write paths (Ward Room, dreams, proactive, runtime) but missed the **qualification probe chain** and several **HXI/CLI interaction paths**. These paths still use raw slot IDs (`agent.id`) to tag episodes. Recall always queries by sovereign ID (`sovereign_id`). Episodes tagged with slot IDs are invisible to sovereign-ID recall.

**Why RetrievalAccuracyBenchmark passes:** It calls `recall_for_agent()` *directly* with the same slot ID used to seed — internally consistent, bypasses the cognitive pipeline. All other probes route through `_send_probe()` → cognitive agent → `recall_weighted()` which uses `sovereign_id`.

**Secondary issue:** The entire 270-line recall pipeline in `cognitive_agent.py` (lines 2469–2740) is wrapped in a single `try/except Exception: logger.debug(...)`. ANY exception silently drops all memory context from the LLM prompt. This masks failures and should log at `warning` level.

### Remaining Slot ID Sites (from BF-103 miss list):

| Code Path | File:Line | ID Used | Should Be |
|-----------|-----------|---------|-----------|
| Drift detector crew enumeration | `drift_detector.py:442` | `agent.id` (slot) | `resolve_sovereign_id(agent)` |
| SeededRecallProbe seed | `memory_probes.py:239` | raw `agent_id` param (slot) | resolved sovereign_id |
| KnowledgeUpdateProbe seed | `memory_probes.py:355,361` | raw `agent_id` (slot) | resolved sovereign_id |
| TemporalReasoningProbe seed | `memory_probes.py:480` | raw `agent_id` (slot) | resolved sovereign_id |
| CrossAgentSynthesisProbe seed | `memory_probes.py:594,604` | `a.id` (slot) | `resolve_sovereign_id(a)` |
| MemoryAbstentionProbe seed | `memory_probes.py:710` | raw `agent_id` (slot) | resolved sovereign_id |
| RetrievalAccuracyBenchmark seed+query | `memory_probes.py:863,879` | raw `agent_id` (slot) | resolved sovereign_id |
| HXI 1:1 episode creation | `routers/agents.py:312` | `agent_id` (route param = slot) | resolved sovereign_id |
| HXI chat history recall | `routers/agents.py:365` | `agent_id` (route param = slot) | resolved sovereign_id |
| CLI session episode creation | `session.py:146` | `self.agent_id` (slot) | resolved sovereign_id |
| CLI session recall | `session.py:69-70` | `resolved["agent_id"]` (slot) | resolved sovereign_id |
| Feedback episode creation | `feedback.py:79` | `_extract_agent_ids()` returns slots | resolve each to sovereign_id |

---

## Fix Strategy

Reuse the existing BF-103 helpers (`resolve_sovereign_id`, `resolve_sovereign_id_from_slot`) to normalize all remaining slot ID leaks. No new abstractions. No dual lookup. Same pattern BF-103 established, applied to missed sites.

For the exception swallowing: narrow the catch radius and elevate logging.

---

## Deliverables

### D1: Fix Drift Detector ID Resolution (`src/probos/cognitive/drift_detector.py`)

**File:** `src/probos/cognitive/drift_detector.py`
**Change:** `_get_crew_agent_ids()` at line 442

Replace:
```python
ids.append(agent.id)
```
With:
```python
from probos.cognitive.episodic import resolve_sovereign_id
ids.append(resolve_sovereign_id(agent))
```

Place the import at the top of the method (inside the existing try block) or at module level. This is the single point that poisons the entire qualification probe chain — fixing it here fixes all probes downstream.

### D2: Fix Memory Probes — Episode Seeding (`src/probos/cognitive/memory_probes.py`)

Even though D1 fixes the ID coming *into* probes, the probes should also resolve IDs defensively (Defense in Depth). Fix all probe classes to resolve the `agent_id` parameter to sovereign_id before seeding episodes.

**D2a: Add sovereign ID resolution at probe entry** (near line 224–228)

In `SeededRecallProbe._run_inner()`, after the agent lookup at line 228:
```python
agent = runtime.registry.get(agent_id)
```

Add resolution:
```python
from probos.cognitive.episodic import resolve_sovereign_id
sovereign_id = resolve_sovereign_id(agent) if agent else agent_id
```

Then use `sovereign_id` instead of `agent_id` in:
- `agent_ids=[sovereign_id]` at line 239

**D2b: Same pattern for KnowledgeUpdateProbe** (~lines 338–361)

After agent lookup, resolve to sovereign_id. Use in `agent_ids=[sovereign_id]` at lines 355 and 361.

**D2c: Same pattern for TemporalReasoningProbe** (~lines 460–480)

After agent lookup, resolve to sovereign_id. Use in `agent_ids=[sovereign_id]` at line 480.

**D2d: Fix CrossAgentSynthesisProbe** (~lines 590–604)

Line 594 currently does:
```python
cognitive_ids = [a.id for a in all_agents if hasattr(a, "handle_intent")][:3]
```

Replace with:
```python
from probos.cognitive.episodic import resolve_sovereign_id
cognitive_ids = [resolve_sovereign_id(a) for a in all_agents if hasattr(a, "handle_intent")][:3]
```

And use `sovereign_id` for the current agent when backfilling:
```python
while len(cognitive_ids) < 3:
    cognitive_ids.append(sovereign_id)  # instead of agent_id
```

**D2e: Same pattern for MemoryAbstentionProbe** (~line 710)

After agent lookup, resolve to sovereign_id. Use in `agent_ids=[sovereign_id]`.

**D2f: Same pattern for RetrievalAccuracyBenchmark** (~lines 863, 879)

Resolve to sovereign_id. Use in:
- `agent_ids=[sovereign_id]` at line 863
- `recall_for_agent(sovereign_id, query, k=5)` at line 879

This makes the benchmark test the production-equivalent ID path even though it bypasses the cognitive pipeline.

**Implementation note:** To keep DRY, extract the resolve call into a shared helper at the top of the probe module:

```python
def _resolve_probe_agent_id(agent_id: str, runtime: Any) -> str:
    """Resolve a probe agent_id (slot ID) to sovereign_id for episode seeding.

    BF-138: Probes must seed episodes with the same ID type the cognitive
    pipeline uses for recall (sovereign_id), not the slot ID passed from
    the drift detector.
    """
    from probos.cognitive.episodic import resolve_sovereign_id
    agent = runtime.registry.get(agent_id) if hasattr(runtime, 'registry') else None
    if agent:
        return resolve_sovereign_id(agent)
    return agent_id
```

Each probe's `_run_inner()` calls `_resolve_probe_agent_id(agent_id, runtime)` early and uses the result throughout. This avoids duplicating the resolve-and-import pattern in 6 classes.

### D3: Fix HXI 1:1 Episode Creation (`src/probos/routers/agents.py`)

**Line 312** — episode creation in `agent_chat()`:

Replace:
```python
agent_ids=[agent_id],
```
With:
```python
from probos.cognitive.episodic import resolve_sovereign_id
agent_ids=[resolve_sovereign_id(agent)],
```

The `agent` object is already available in scope (looked up at ~line 267). Place the import at module level or with the existing episodic imports.

**Line 365** — chat history recall in `agent_chat_history()`:

Replace:
```python
episodes = await runtime.episodic_memory.recall_for_agent(
    agent_id, "1:1 conversation with Captain", k=3
)
```
With:
```python
agent = runtime.registry.get(agent_id)
sovereign_id = resolve_sovereign_id(agent) if agent else agent_id
episodes = await runtime.episodic_memory.recall_for_agent(
    sovereign_id, "1:1 conversation with Captain", k=3
)
```

Same for the `recent_for_agent` fallback at line 369 — use `sovereign_id`.

### D4: Fix CLI Session Episode Creation and Recall (`src/probos/experience/commands/session.py`)

**Line 61** — resolve sovereign_id when entering session. After `self.agent_id = resolved["agent_id"]`:

```python
# BF-138: Resolve to sovereign_id for episodic memory operations
agent = runtime.registry.get(self.agent_id) if hasattr(runtime, 'registry') else None
from probos.cognitive.episodic import resolve_sovereign_id
self._sovereign_id = resolve_sovereign_id(agent) if agent else self.agent_id
```

**Line 69–70** — session recall: use `self._sovereign_id` instead of `resolved["agent_id"]`:
```python
past = await runtime.episodic_memory.recall_for_agent(
    agent_id=self._sovereign_id,
```

**Line 76** — fallback recall: same, use `self._sovereign_id`.

**Line 146** — episode creation: use `self._sovereign_id`:
```python
agent_ids=[self._sovereign_id],
```

### D5: Fix Feedback Episode Creation (`src/probos/cognitive/feedback.py`)

**Line 79** — `_extract_agent_ids()` (defined at line 306) returns slot IDs from DAG node results.

FeedbackEngine currently has NO registry access. Constructor at line 42 accepts: `trust_network`, `hebbian_router`, `episodic_memory`, `event_log`, `feedback_hebbian_reward`, `feedback_trust_weight`.

**D5a: Add `identity_registry` parameter to FeedbackEngine constructor** (line 42):

```python
def __init__(
    self,
    trust_network: TrustNetwork,
    hebbian_router: HebbianRouter,
    episodic_memory: EpisodicMemory | None = None,
    event_log: EventLog | None = None,
    feedback_hebbian_reward: float = 0.10,
    feedback_trust_weight: float = 1.5,
    identity_registry: Any = None,  # BF-138: for sovereign ID resolution
) -> None:
    ...
    self._identity_registry = identity_registry
```

**D5b: Wire identity_registry at construction site** (`src/probos/startup/cognitive_services.py:225`):

The `identity_registry` is already a parameter to the cognitive services startup function (line 50). Pass it through:

```python
feedback_engine = FeedbackEngine(
    trust_network=trust_network,
    hebbian_router=hebbian_router,
    episodic_memory=episodic_memory,
    event_log=event_log,
    identity_registry=identity_registry,  # BF-138
)
```

**D5c: Resolve IDs in `_extract_agent_ids()`** (line 306):

After the existing extraction logic, add resolution:

```python
def _extract_agent_ids(self, dag: TaskDAG) -> list[str]:
    """Extract unique agent IDs from an executed DAG's node results."""
    agent_ids: list[str] = []
    for node in dag.nodes:
        agent_id = self._get_agent_id_from_node(node)
        if agent_id and agent_id not in agent_ids:
            agent_ids.append(agent_id)
    # BF-138: Resolve slot IDs to sovereign IDs
    if self._identity_registry:
        from probos.cognitive.episodic import resolve_sovereign_id_from_slot
        return [resolve_sovereign_id_from_slot(aid, self._identity_registry) for aid in agent_ids]
    return agent_ids
```

### D6: Elevate Recall Exception Logging (`src/probos/cognitive/cognitive_agent.py`)

**Line 2739** — the outer catch-all:

Replace:
```python
except Exception:
    logger.debug("Failed to fetch episodic memory context", exc_info=True)
```

With:
```python
except Exception:
    logger.warning("BF-138: Failed to fetch episodic memory context — agent will respond without memory", exc_info=True)
```

This is a single-line change. Do NOT restructure the try/except block — that's a separate refactoring concern. Just elevate visibility so failures are no longer silent.

---

## Test Requirements

### File: `tests/test_bf138_sovereign_id_completion.py` (NEW — 15 tests)

**D1: Drift Detector (2 tests)**

1. `test_drift_detector_returns_sovereign_ids` — `_get_crew_agent_ids()` returns sovereign IDs when agents have `sovereign_id` set, NOT slot IDs. Mock agents with both `.id` and `.sovereign_id` attributes.
2. `test_drift_detector_falls_back_to_slot_id` — When `sovereign_id` is empty/None, returns `agent.id` (fallback behavior preserved).

**D2: Memory Probe Seeding (5 tests)**

3. `test_seeded_recall_probe_uses_sovereign_id` — SeededRecallProbe seeds episodes with sovereign_id in `agent_ids_json`, not slot ID. Verify by inspecting seeded episodes in ChromaDB.
4. `test_knowledge_update_probe_uses_sovereign_id` — KnowledgeUpdateProbe seeds both old and new episodes with sovereign_id.
5. `test_temporal_reasoning_probe_uses_sovereign_id` — TemporalReasoningProbe seeds episodes with sovereign_id.
6. `test_cross_agent_synthesis_uses_sovereign_ids` — CrossAgentSynthesisProbe resolves all agent IDs to sovereign_ids for episode seeding.
7. `test_retrieval_benchmark_uses_sovereign_id` — RetrievalAccuracyBenchmark seeds AND queries with sovereign_id (both paths consistent).

**D3: HXI Episodes (2 tests)**

8. `test_hxi_chat_episode_uses_sovereign_id` — Episode created via `/agents/{id}/chat` stores sovereign_id in `agent_ids_json`. Mock the registry to return an agent with `sovereign_id` different from slot ID.
9. `test_hxi_chat_history_uses_sovereign_id` — Chat history recall queries by sovereign_id, not slot ID.

**D4: CLI Session (2 tests)**

10. `test_cli_session_episode_uses_sovereign_id` — CLI session episode creation uses sovereign_id.
11. `test_cli_session_recall_uses_sovereign_id` — CLI session recall queries by sovereign_id.

**D5: Feedback (2 tests)**

12. `test_feedback_extract_agent_ids_resolves_sovereign` — `_extract_agent_ids()` returns sovereign IDs, not raw slot IDs from DAG results.
13. `test_feedback_episode_uses_sovereign_ids` — Episodic episode created by feedback engine stores sovereign IDs.

**D6: Exception Logging (2 tests)**

14. `test_recall_exception_logs_warning` — When episodic recall raises an exception, it's logged at `WARNING` level (not `DEBUG`). Use a log capture fixture.
15. `test_recall_exception_still_returns_observation` — Despite the exception, `_enrich_with_memory()` still returns the observation dict (graceful degradation preserved).

---

## Validation Checklist

- [ ] `_get_crew_agent_ids()` returns sovereign IDs — verified by test 1
- [ ] ALL 6 probe classes seed episodes with sovereign_id — verified by tests 3–7
- [ ] HXI episode creation uses sovereign_id — verified by test 8
- [ ] HXI chat history recall uses sovereign_id — verified by test 9
- [ ] CLI session creation AND recall use sovereign_id — verified by tests 10–11
- [ ] Feedback episode creation uses sovereign_ids — verified by tests 12–13
- [ ] Recall exceptions log at WARNING level — verified by test 14
- [ ] No `agent.id` or raw slot ID appears in any `agent_ids=` for episodic episode creation (search validation)
- [ ] `resolve_sovereign_id` / `resolve_sovereign_id_from_slot` used consistently (DRY)
- [ ] All 15 new tests pass
- [ ] Existing BF-103 tests still pass (regression)
- [ ] Full pytest suite passes

---

## Scope Exclusions

| Excluded Item | Reason |
|---------------|--------|
| Trust/Hebbian/Journal sovereign_id migration | Explicitly deferred by AD-441 — separate ADs |
| Restructuring the try/except block in `cognitive_agent.py` | Separate refactoring — BF-138 only elevates log level |
| `behavioral_metrics.py:583` thread author IDs | Thread authors come from Ward Room posts, which may use display names or callsigns — different ID resolution needed |
| `anchor_quality.py:119` profile build caller IDs | Depends on callers being correct — callers already fixed by this BF |
| `oracle_service.py:179` agent_id parameter | Depends on callers — most callers already use sovereign_id |
| `feedback.py:278` rejected plan `agent_ids=[]` | Empty list, not an ID-type issue |
| `runtime.py:2271` / `renderer.py:419` fallback `agent_ids=[]` | Empty list, not an ID-type issue |

---

## File Summary

| File | Action | Description |
|------|--------|-------------|
| `src/probos/cognitive/drift_detector.py` | EDIT | `_get_crew_agent_ids()` → use `resolve_sovereign_id(agent)` |
| `src/probos/cognitive/memory_probes.py` | EDIT | Add `_resolve_probe_agent_id()` helper; fix all 6 probe classes |
| `src/probos/routers/agents.py` | EDIT | HXI episode creation + chat history recall → sovereign_id |
| `src/probos/experience/commands/session.py` | EDIT | CLI session episode creation + recall → sovereign_id |
| `src/probos/cognitive/feedback.py` | EDIT | Add `identity_registry` param, `_extract_agent_ids()` → resolve to sovereign IDs |
| `src/probos/startup/cognitive_services.py` | EDIT | Pass `identity_registry` to FeedbackEngine constructor |
| `src/probos/cognitive/cognitive_agent.py` | EDIT | Recall exception `logger.debug` → `logger.warning` |
| `tests/test_bf138_sovereign_id_completion.py` | **NEW** | 15 tests |

---

## Engineering Principles Compliance

| Principle | How Applied |
|-----------|-------------|
| **DRY** | Reuse existing `resolve_sovereign_id()` and `resolve_sovereign_id_from_slot()` from BF-103. New `_resolve_probe_agent_id()` helper avoids duplication across 6 probe classes. |
| **Fail Fast** | Recall exception elevated from `debug` to `warning`. Failures are visible, not silent. |
| **Defense in Depth** | ID resolution at both the drift detector (upstream) AND each probe (downstream). If one is bypassed, the other catches it. |
| **Single Responsibility** | `resolve_sovereign_id()` in `episodic.py` is the single authority for ID resolution. Callers don't decide which ID type to use. |
| **Open/Closed** | No changes to the `resolve_sovereign_id()` API. Existing callers unaffected. |
| **Law of Demeter** | Probes access agent identity through `resolve_sovereign_id(agent)`, not `agent.sovereign_id` directly. The helper handles the fallback chain. |
