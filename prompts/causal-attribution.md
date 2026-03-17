# AD-295: Causal Attribution for Emergent Behavior + Self-Introspection

## Problem

ProbOS detects emergent patterns (trust anomalies, routing shifts, cooperation clusters) but cannot explain *why* they're happening. When a user asks "what is causing the adaptation?", the system returns no useful information because:

1. **No causal trail for trust changes.** `TrustNetwork.record_outcome()` updates alpha/beta but does not record which intent, Shapley values, or verifier caused the change. The SQLite table stores only `agent_id, alpha, beta, updated`.

2. **No Shapley values in Episodes.** Episodes record outcomes (intent + success/status) and agent_ids, but not the Shapley attribution scores that directly drove trust updates.

3. **IntrospectionAgent has no CodebaseIndex access.** It can answer questions about runtime state (trust, pools, Hebbian weights) but cannot examine ProbOS's own source code to answer design questions. When asked "is there a design limitation?", ProbOS gives a generic LLM answer instead of introspecting on its own architecture. The `codebase_knowledge` skill is only available to medical team agents (Pathologist).

4. **EmergentDetector patterns have no back-references.** `EmergentPattern.evidence` contains statistical data (which agents, what thresholds) but not the episodes/intents that caused the detected pattern.

## Objective

Make ProbOS capable of answering "why is this happening?" about its own emergent behavior, and "what would be needed?" about its own architecture.

## Pre-read

Before starting, read these files:
- `src/probos/cognitive/emergent_detector.py` — `EmergentPattern` dataclass (line 30), `detect_trust_anomalies()` (line 255), `detect_routing_shifts()` (line 353)
- `src/probos/consensus/trust.py` — `TrustRecord` (line 28), `record_outcome()` (line 128)
- `src/probos/consensus/quorum.py` — Shapley computation at line 97
- `src/probos/types.py` — `Episode` dataclass (line 299)
- `src/probos/runtime.py` — trust update flow (lines 1069-1086), episode building (lines 2139-2187)
- `src/probos/agents/introspect.py` — IntrospectionAgent, `_system_anomalies()`, `_emergent_patterns()`
- `src/probos/cognitive/codebase_skill.py` — `codebase_knowledge` skill
- `src/probos/cognitive/episodic.py` — Episode serialization to ChromaDB (line 293)
- `PROGRESS.md` — current test count on line 3

## Step 1: Trust Event Log (AD-295a)

Add a lightweight causal trail to trust changes.

### `src/probos/consensus/trust.py`

Add a `TrustEvent` dataclass and a ring buffer to `TrustNetwork`:

```python
@dataclass
class TrustEvent:
    """A single trust change with causal context."""
    timestamp: float
    agent_id: str
    success: bool
    old_score: float
    new_score: float
    weight: float  # Shapley weight used
    intent_type: str  # which intent was being processed
    episode_id: str  # which episode this belongs to
    verifier_id: str  # which red-team agent verified
```

Modify `record_outcome()` signature:

```python
def record_outcome(
    self, agent_id: str, success: bool, weight: float = 1.0,
    intent_type: str = "", episode_id: str = "", verifier_id: str = "",
) -> float:
```

Inside `record_outcome()`:
- Capture `old_score` before the update
- After the update, append a `TrustEvent` to `self._event_log: deque[TrustEvent]` (maxlen=500)
- Return the new score (unchanged behavior)

Add methods:
- `get_recent_events(n: int = 50) -> list[TrustEvent]`: Return last N events
- `get_events_for_agent(agent_id: str, n: int = 20) -> list[TrustEvent]`: Filter by agent
- `get_events_since(timestamp: float) -> list[TrustEvent]`: Filter by time

### `src/probos/runtime.py`

Update *all* `record_outcome()` call sites to pass the new optional kwargs. There are several call sites to find:

1. The red-team verification loop (around line 1069-1086) — this is the main one. Pass:
   - `intent_type`: from the current DAG node's intent
   - `episode_id`: from the episode being built (or generate one)
   - `verifier_id`: the red-team agent's ID
   - `weight`: the Shapley-weighted value already being computed

2. Any other `record_outcome()` calls — search for all occurrences and add context where available. If context isn't available at a call site, leave the defaults (empty strings).

### Tests (add to `tests/test_trust.py` or create `tests/test_trust_events.py`):

1. `test_trust_event_recorded` — call `record_outcome()` with intent_type and episode_id, verify event shows up in `get_recent_events()`
2. `test_trust_event_scores` — verify `old_score` and `new_score` are correct
3. `test_trust_event_log_capped` — fill beyond 500 events, verify oldest are dropped
4. `test_get_events_for_agent` — multiple agents, filter returns correct subset
5. `test_get_events_since` — time-based filtering works
6. `test_backward_compatible` — calling `record_outcome(agent_id, success)` without new kwargs still works (no KeyError, events have empty strings for causal fields)

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Step 2: Enrich Episodes with Attribution (AD-295b)

### `src/probos/types.py`

Add optional fields to `Episode`:

```python
@dataclass
class Episode:
    # ... existing fields ...
    shapley_values: dict[str, float] = field(default_factory=dict)
    trust_deltas: list[dict[str, Any]] = field(default_factory=list)
    # trust_deltas format: [{"agent_id": str, "old": float, "new": float, "weight": float}]
```

### `src/probos/runtime.py`

In `_build_episode()` (around line 2139):
- After the DAG executes, capture `self._last_shapley_values` and store in `episode.shapley_values`
- Capture trust deltas: after red-team verification, collect the trust events generated during this episode (using `trust_network.get_events_since(episode_start_time)`) and store as `episode.trust_deltas`

### `src/probos/cognitive/episodic.py`

Update `_serialize_metadata()` to include `shapley_values_json` and `trust_deltas_json` in ChromaDB metadata. Update deserialization to restore these fields.

### Tests:

1. `test_episode_stores_shapley` — process an intent, verify episode has shapley_values
2. `test_episode_stores_trust_deltas` — verify trust deltas are captured in episode
3. `test_episode_serialization_roundtrip` — serialize and deserialize episode with all new fields, verify nothing is lost

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Step 3: Causal Back-References in EmergentPatterns (AD-295c)

### `src/probos/cognitive/emergent_detector.py`

**Enrich `detect_trust_anomalies()`:**

After detecting a trust anomaly (statistical outlier, change-point, or hyperactive agent), query `trust_network.get_events_for_agent(agent_id)` to find the recent trust events that explain the anomaly. Add to `EmergentPattern.evidence`:

```python
evidence = {
    # ... existing fields ...
    "causal_events": [
        {
            "intent_type": event.intent_type,
            "success": event.success,
            "weight": event.weight,
            "score_change": round(event.new_score - event.old_score, 4),
            "episode_id": event.episode_id,
        }
        for event in recent_events[:5]  # last 5 trust events for this agent
    ],
}
```

**Enrich `detect_routing_shifts()`:**

When a new agent-intent connection is detected, include the Hebbian weight and the trust score of the newly-routed agent. This explains *why* routing shifted (e.g., "agent X gained trust and Hebbian weight on intent Y").

### `src/probos/agents/introspect.py`

**Update `_emergent_patterns()` and `_system_anomalies()`:**

When reporting patterns that have `causal_events` in their evidence, format them into the response. The LLM reflection step will then be able to say "trust shifted because agent X successfully handled 3 health alerts" instead of just "84 trust anomalies detected."

### Tests:

1. `test_trust_anomaly_has_causal_events` — mock a trust anomaly scenario, verify EmergentPattern.evidence includes causal_events list
2. `test_routing_shift_includes_context` — verify routing shift patterns include agent trust and Hebbian weight context
3. `test_introspection_surfaces_causal_data` — verify IntrospectionAgent response includes causal attribution when available

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Step 4: Self-Introspection via CodebaseIndex (AD-295d)

### `src/probos/agents/introspect.py`

**Add `codebase_knowledge` skill to IntrospectionAgent.**

In the class body, add an `__init__` override (or use the existing init pattern) that adds the codebase_knowledge skill:

```python
def __init__(self, **kwargs: Any) -> None:
    super().__init__(**kwargs)
    # codebase_knowledge skill will be attached by runtime after CodebaseIndex is built
```

### `src/probos/runtime.py`

After building CodebaseIndex and creating the codebase_knowledge skill (around line 480-511), also attach it to IntrospectionAgent instances. Find where introspect agents are created and add the skill:

```python
# After codebase skill creation:
for agent in self.registry.all():
    if agent.agent_type == "introspect":
        agent.add_skill(codebase_skill)
```

### `src/probos/agents/introspect.py`

**Add `introspect_design` intent** — a new IntentDescriptor:

```python
IntentDescriptor(
    name="introspect_design",
    params={"question": "question about ProbOS architecture or design"},
    description="Answer questions about ProbOS architecture, design limitations, and internal structure using source code knowledge",
    requires_reflect=True,
),
```

Add to `_handled_intents` set.

Add routing in `act()`:

```python
elif action == "introspect_design":
    return await self._introspect_design(rt, params)
```

**Implement `_introspect_design()`:**

```python
async def _introspect_design(self, rt: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Answer architectural questions using codebase knowledge."""
    question = params.get("question", "")
    if not question:
        return {"success": False, "error": "No question provided"}

    # Use codebase_knowledge skill if available
    skill = self.get_skill("codebase_knowledge")
    if skill is None:
        return {
            "success": True,
            "data": {
                "message": "Codebase knowledge not available. Cannot introspect source architecture.",
            },
        }

    # Query architecture for the concept
    arch_data = skill.query_architecture(question)
    agent_map = skill.get_agent_map()
    layer_map = skill.get_layer_map()

    return {
        "success": True,
        "data": {
            "question": question,
            "architecture_context": arch_data,
            "agent_count": len(agent_map) if agent_map else 0,
            "layers": list(layer_map.keys()) if layer_map else [],
        },
    }
```

### Tests:

1. `test_introspect_design_returns_architecture` — ask an architecture question, verify response includes architecture_context
2. `test_introspect_design_no_skill` — test graceful fallback when codebase skill isn't attached
3. `test_introspect_agent_has_codebase_skill` — verify the skill is attached after runtime startup

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Step 5: Update Progress

- Update test count on PROGRESS.md line 3
- Add AD-295 section to `progress-era-3-product.md` under the Pre-Launch section with AD-295a through AD-295d
- Update DECISIONS.md with AD-295 entries

## Constraints

- TrustEvent log is in-memory only (deque maxlen=500) — not persisted to SQLite. This keeps it lightweight. Persistence is a future enhancement.
- Episode enrichment is backward-compatible — new fields have default empty values, existing episodes still deserialize correctly
- EmergentPattern.evidence is already a dict — causal_events is just a new key, no schema change
- `record_outcome()` new params are all optional with defaults — zero risk to existing callers
- The `introspect_design` intent uses the same codebase_knowledge skill as the medical team — no code duplication, just skill sharing

## Success Criteria

- "What is causing the adaptation?" → ProbOS explains that trust shifted because specific agents handled specific intents with specific Shapley contributions
- "Is there a design limitation preventing X?" → ProbOS uses CodebaseIndex to examine its own source and answer with architectural context
- Episodes now carry Shapley values and trust deltas for post-hoc analysis
- EmergentPattern evidence includes causal back-references to recent trust events
- All existing tests pass — no regressions
- New tests pass (estimated 15 new tests across 4 steps)
