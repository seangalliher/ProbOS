# Bug Fix Batch: BF-001, BF-002, BF-003 — AD-348 through AD-350

**Current highest AD: AD-347 (Builder Failure Escalation)**

This prompt fixes the three open bugs in the ProbOS bug tracker. Each bug is an independent AD. Execute them in order: **AD-348 → AD-349 → AD-350**.

---

## AD-348: Fix Self-Mod False Positive on Knowledge Questions (BF-001)

**Problem:** When a user asks a general knowledge question ("who is Alan Turing?", "what is a CPU?"), ProbOS shows "Build Agent" / "Design Agent" buttons instead of answering. The decomposer prompt rules classify ALL knowledge questions as capability gaps, triggering the self-mod proposal flow.

**Root cause:** Three prompt rules explicitly list "knowledge questions" and "factual questions" as tasks that should produce `capability_gap: true` when no matching intent exists. The LLM can answer well-established factual questions from training data — these are conversational, not task gaps.

The distinction is:
- **True capability gap** (needs external tool): "translate this to French", "search the web for X", "generate a QR code" — the LLM genuinely cannot do this without an agent.
- **Knowledge question** (LLM can answer): "who is Alan Turing?", "what is the speed of light?", "explain quantum computing" — well-established facts from training data.

**Files to modify:**

### 1. `src/probos/cognitive/prompt_builder.py`

#### 1a. Update `_GAP_EXAMPLES` (around line 138)

Remove the "who is Alan Turing?" gap example entirely. It teaches the LLM to treat knowledge questions as gaps. The remaining examples (translation, creative writing, QR code) are genuine capability gaps.

**Before:**
```python
_GAP_EXAMPLES: list[tuple[str, str, str]] = [
    ...
    (
        "who is Alan Turing?",
        "I don't have an intent for knowledge lookup yet.",
        "lookup",
    ),
    ...
]
```

**After:** Remove the Alan Turing tuple entirely. Do NOT add a replacement — having 3 gap examples is sufficient.

#### 1b. Update the conversational-vs-task rule (around line 299)

Change the rule that classifies "knowledge/factual lookup, person lookup" as tasks into one that explicitly classifies them as conversational.

**Current text (line 299-306):**
```python
f'{rule_num}. If the request is conversational (greeting, help, small talk), respond with '
'{"intents": [], "response": "a helpful reply"}. '
'If the request is a task (translation, analysis, creative writing, knowledge/factual '
'lookup, person lookup, etc.) that cannot be mapped to any available intent, respond with '
'{"intents": [], "response": "I don\'t have an intent for <task type> yet.", "capability_gap": true}. '
'NEVER answer factual questions or perform tasks yourself in the response field — '
'you have no internet access and will hallucinate.'
```

**Replace with:**
```python
f'{rule_num}. If the request is conversational (greeting, help, small talk) OR a general '
'knowledge question (who is X, what is Y, explain Z, factual questions about well-known '
'topics), respond directly with '
'{"intents": [], "response": "a helpful answer"}. '
'If the request is a task requiring external tools or computation (translation, web search, '
'code generation, image creation, API calls, etc.) that cannot be mapped to any available '
'intent, respond with '
'{"intents": [], "response": "I don\'t have an intent for <task type> yet.", "capability_gap": true}. '
'You may answer factual questions about well-known topics from your training data.'
```

#### 1c. Update the run_command guard rule (around line 322)

Remove "knowledge questions", "person/topic lookup", "factual questions" from the list of tasks that trigger capability gaps.

**Current text (line 322-330):**
```python
f'{rule_num}. For tasks requiring intelligence or external data — translation, '
'creative writing, summarization, knowledge questions, person/topic lookup, '
'factual questions — if a matching intent exists in the '
'table above, use it. If NO matching intent exists, return '
'{"intents": [], "response": "I don\'t have an intent for <task type> yet.", "capability_gap": true}. '
'NEVER answer factual questions or perform tasks yourself in the response field — '
'you have no internet access and will hallucinate. '
'Conversational replies (greetings, help, small talk) are fine as direct responses.'
```

**Replace with:**
```python
f'{rule_num}. For tasks requiring external tools or computation — translation, '
'creative writing, summarization, code generation, web search — if a matching intent '
'exists in the table above, use it. If NO matching intent exists, return '
'{"intents": [], "response": "I don\'t have an intent for <task type> yet.", "capability_gap": true}. '
'General knowledge questions (who is X, what is Y, explain Z) are conversational — '
'answer them directly in the response field. '
'Conversational replies (greetings, help, small talk, factual questions) are fine as direct responses.'
```

### 2. `src/probos/cognitive/decomposer.py`

#### 2a. Update legacy rule 12b (around lines 113-118)

Remove "knowledge questions" from the legacy system prompt rule.

**Current (lines 113-118):**
```
12b. For tasks requiring intelligence — translation, creative writing, \
summarization, knowledge questions — if a matching intent exists in the \
table above, use it. If NO matching intent exists, return \
{"intents": [], "response": "I don't have an intent for <task type> yet."}. \
NEVER perform these tasks yourself in the response field. \
Conversational replies (greetings, help, small talk) are fine as direct responses.
```

**Replace with:**
```
12b. For tasks requiring external tools or computation — translation, creative \
writing, summarization, code generation, web search — if a matching intent exists \
in the table above, use it. If NO matching intent exists, return \
{"intents": [], "response": "I don't have an intent for <task type> yet."}. \
General knowledge questions (who/what/explain) are conversational — answer directly. \
Conversational replies (greetings, help, small talk, factual questions) are fine as direct responses.
```

### 3. Test file: `tests/test_prompt_builder.py`

#### 3a. Update existing gap example test

The existing test at around line 238 asserts that "who is Alan Turing?" appears in the gap examples. Since we removed that example, update the test to assert it does NOT appear:

```python
def test_gap_example_knowledge_not_classified_as_gap(self, builder, descriptors):
    """BF-001: Knowledge questions should not be in gap examples."""
    prompt = builder.build_system_prompt(descriptors)
    assert "who is Alan Turing" not in prompt
```

#### 3b. Add test for knowledge question classification

Add a test that verifies the prompt text instructs the LLM to answer knowledge questions directly:

```python
def test_knowledge_questions_are_conversational(self, builder, descriptors):
    """BF-001: Knowledge questions should be classified as conversational."""
    prompt = builder.build_system_prompt(descriptors)
    assert "general knowledge question" in prompt.lower() or "knowledge question" in prompt.lower()
    # Should NOT tell the LLM to never answer factual questions
    assert "NEVER answer factual questions" not in prompt
```

### 4. Test file: `tests/test_decomposer.py`

#### 4a. Add false-positive test to `TestCapabilityGap`

In the `TestCapabilityGap` class (around line 387), add a parametrized false-negative case to confirm that a direct knowledge answer is NOT a capability gap:

```python
@pytest.mark.parametrize("text", [
    "Alan Turing was a British mathematician and computer scientist.",
    "The speed of light is approximately 299,792,458 meters per second.",
    "Python is a high-level programming language.",
])
def test_knowledge_answers_are_not_capability_gaps(self, text):
    """BF-001: Direct knowledge answers should not be flagged as gaps."""
    assert not is_capability_gap(text)
```

These texts should already pass (they don't contain "don't have" or "can't" etc.), but the test documents the intent.

**Total expected new/modified tests for AD-348:** ~3-4 tests

---

## AD-349: Fix Agent Orbs Escaping Pool Group Spheres (BF-002)

**Problem:** On the Cognitive Canvas (HXI), agent orbs escape their pool group spheres after any `agent_state` WebSocket event. Initial layout from `state_snapshot` is correct, but subsequent `agent_state` updates destroy clustering.

**Root cause:** The `agent_state` handler in `useStore.ts` at line 433 calls:
```typescript
return { agents: computeLayout(agents).agents };
```

`computeLayout` is called with only `agents` — the `poolToGroup` and `poolGroups` parameters are omitted. Without pool group data, `computeLayout` falls back to flat Fibonacci sphere placement (line 74-108), scattering agents across the canvas without regard to their pool groups.

The `state_snapshot` handler (line 391) calls `computeLayout` correctly with all three arguments but does NOT persist `poolToGroup` or `poolGroups` to Zustand state. So the `agent_state` handler has no way to access them.

**File to modify:** `ui/src/store/useStore.ts`

### Step 1: Add pool group data fields to `HXIState` interface

Around line 178, after the existing `groupCenters` field, add two new state fields:

```typescript
poolToGroup: Record<string, string>;
poolGroups: Record<string, PoolGroupInfo>;
```

Import `PoolGroupInfo` from `types.ts` if not already imported (check the existing imports at the top of the file).

### Step 2: Initialize the new fields in the store defaults

Around line 249 (inside `create<HXIState>(...)`), after `groupCenters: new Map(),`, add:

```typescript
poolToGroup: {},
poolGroups: {},
```

### Step 3: Persist pool group data in the `state_snapshot` handler

In the `state_snapshot` handler, the `set()` call at line 392 currently sets: `agents`, `groupCenters`, `connections`, `pools`, `systemMode`, `tcN`, `routingEntropy`. Add the pool group data:

```typescript
set({
  agents: layoutResult.agents,
  groupCenters: layoutResult.groupCenters,
  connections,
  pools,
  poolToGroup,                              // <-- ADD
  poolGroups: snap.pool_groups || {},        // <-- ADD
  systemMode: snap.system_mode as SystemMode,
  tcN: snap.tc_n,
  routingEntropy: snap.routing_entropy,
  ...(snap.fresh_boot ? { chatHistory: [] } : {}),
});
```

### Step 4: Fix the `agent_state` handler to use persisted pool group data

Replace line 433:
```typescript
return { agents: computeLayout(agents).agents };
```

With:
```typescript
const result = computeLayout(agents, s.poolToGroup, s.poolGroups);
return { agents: result.agents, groupCenters: result.groupCenters };
```

`s.poolToGroup` and `s.poolGroups` are available because the `set` callback receives the current state as `s` (line 407: `set((s) => {`).

### Step 5: Tests — `ui/src/__tests__/useStore.test.ts`

Add tests to the existing `agent_state` test section (around line 78):

```typescript
it('preserves pool group clustering on agent_state update', () => {
  // Set up initial state with pool group data (simulating state_snapshot)
  const { handleEvent } = useStore.getState();

  // First, send a state_snapshot that establishes pool groups
  handleEvent({
    type: 'state_snapshot',
    data: {
      agents: [
        { id: 'a1', agent_type: 'file_reader', pool: 'filesystem', state: 'active', confidence: 0.9, trust: 0.5, tier: 'core' },
        { id: 'a2', agent_type: 'diagnostician', pool: 'medical_diagnostician', state: 'active', confidence: 0.9, trust: 0.5, tier: 'domain' },
      ],
      connections: [],
      pools: [],
      pool_groups: {
        core: { pools: { filesystem: { healthy: 1, target: 1 } } },
        medical: { pools: { medical_diagnostician: { healthy: 1, target: 1 } } },
      },
      pool_to_group: { filesystem: 'core', medical_diagnostician: 'medical' },
      system_mode: 'active',
      tc_n: 1,
      routing_entropy: 0.5,
    },
  });

  // Record positions after snapshot
  const afterSnapshot = useStore.getState();
  const a1PosSnapshot = afterSnapshot.agents.get('a1')?.position;
  const a2PosSnapshot = afterSnapshot.agents.get('a2')?.position;
  expect(afterSnapshot.poolToGroup).toEqual({ filesystem: 'core', medical_diagnostician: 'medical' });

  // Now send an agent_state update
  handleEvent({
    type: 'agent_state',
    data: { agent_id: 'a1', pool: 'filesystem', state: 'active', confidence: 0.95, trust: 0.6 },
  });

  // Positions should remain clustered (not reset to flat layout)
  const afterUpdate = useStore.getState();
  const a1PosUpdate = afterUpdate.agents.get('a1')?.position;
  const a2PosUpdate = afterUpdate.agents.get('a2')?.position;

  // groupCenters should still be populated (not empty)
  expect(afterUpdate.groupCenters.size).toBeGreaterThan(0);

  // Agent positions should be close to their snapshot positions (within same cluster)
  // The exact positions may shift slightly due to layout recalculation, but they should
  // stay in the same general region, not scatter to a flat layout
  if (a1PosSnapshot && a1PosUpdate) {
    const dist = Math.sqrt(
      (a1PosSnapshot[0] - a1PosUpdate[0]) ** 2 +
      (a1PosSnapshot[1] - a1PosUpdate[1]) ** 2 +
      (a1PosSnapshot[2] - a1PosUpdate[2]) ** 2,
    );
    expect(dist).toBeLessThan(2.0); // Should be in same cluster, not across canvas
  }
});

it('stores poolToGroup and poolGroups from state_snapshot', () => {
  const { handleEvent } = useStore.getState();
  handleEvent({
    type: 'state_snapshot',
    data: {
      agents: [],
      connections: [],
      pools: [],
      pool_groups: { core: { pools: { filesystem: { healthy: 1, target: 1 } } } },
      pool_to_group: { filesystem: 'core' },
      system_mode: 'active',
      tc_n: 0,
      routing_entropy: 0,
    },
  });
  const state = useStore.getState();
  expect(state.poolToGroup).toEqual({ filesystem: 'core' });
  expect(state.poolGroups).toEqual({ core: { pools: { filesystem: { healthy: 1, target: 1 } } } });
});
```

**Total expected new tests for AD-349:** 2 vitest tests

---

## AD-350: Fix "Run Diagnostic" Bypassing VitalsMonitor (BF-003)

**Problem:** When a user says "run diagnostic", the Diagnostician receives a `diagnose_system` intent with only an optional `focus` parameter. Its LLM instructions tell it to "analyze the alert data (severity, metric, current_value, threshold, affected)" — data that doesn't exist for on-demand requests. The LLM, having no data, asks the user to provide it. VitalsMonitor (a HeartbeatAgent) has the metrics but cannot be called on-demand.

**Root cause:** Two issues:
1. VitalsMonitor has no on-demand scan method exposed to other agents.
2. Diagnostician's instructions and `perceive()` don't differentiate between `medical_alert` (has alert data) and `diagnose_system` (needs to gather data first).

**Fix approach:** Proactive scan path. The Diagnostician overrides `perceive()` to detect `diagnose_system` intents and fetch current metrics from VitalsMonitor before sending them to the LLM. No new agent needed — this is the simplest fix that solves the user-facing problem.

### File 1: `src/probos/agents/medical/vitals_monitor.py`

#### 1a. Add `scan_now()` public method

Add an async method that runs `collect_metrics()` on-demand and returns the metrics dict. This is safe because `collect_metrics()` is already idempotent. Add it after `collect_metrics()`, before `_check_thresholds()`:

```python
async def scan_now(self) -> dict[str, Any]:
    """On-demand metric snapshot for the Diagnostician (AD-350).

    Unlike the periodic heartbeat, this does NOT check thresholds or
    emit alerts — it simply collects and returns the current metrics.
    """
    metrics: dict[str, Any] = {
        "pulse": self._pulse_count,
        "agent_id": self.id,
        "timestamp": time.time(),
    }

    rt = self._runtime
    if rt is None:
        return metrics

    # Reuse the same metric collection logic as collect_metrics,
    # but without threshold checks or window storage.
    # Pool health ratios
    pool_health: dict[str, float] = {}
    for pool_name, pool in rt.pools.items():
        target = pool.target_size
        active = len([
            a for a in pool.healthy_agents
            if (getattr(a, "state", None) == AgentState.ACTIVE
                if hasattr(a, "state") else True)
        ])
        pool_health[pool_name] = active / target if target > 0 else 1.0
    metrics["pool_health"] = pool_health

    # Trust statistics
    scores = rt.trust_network.all_scores()
    if scores:
        score_vals = list(scores.values())
        metrics["trust_mean"] = sum(score_vals) / len(score_vals)
        metrics["trust_min"] = min(score_vals)
        metrics["trust_outliers"] = [
            aid for aid, s in scores.items() if s < self._trust_floor
        ]
    else:
        metrics["trust_mean"] = 1.0
        metrics["trust_min"] = 1.0
        metrics["trust_outliers"] = []

    # Dream state
    if rt.dream_scheduler:
        metrics["is_dreaming"] = rt.dream_scheduler._is_dreaming if hasattr(rt.dream_scheduler, "_is_dreaming") else False
    else:
        metrics["is_dreaming"] = False

    # Attention queue depth
    if hasattr(rt, "attention") and rt.attention:
        metrics["attention_queue"] = rt.attention.queue_size
    else:
        metrics["attention_queue"] = 0

    # Overall system health
    all_agents = rt.registry.all()
    active_confs = [
        a.confidence for a in all_agents
        if getattr(a, "state", None) == AgentState.ACTIVE
    ]
    metrics["system_health"] = (
        sum(active_confs) / len(active_confs) if active_confs else 1.0
    )

    # Include recent window history if available
    if self._window:
        metrics["recent_history"] = list(self._window)

    return metrics
```

**Note:** This duplicates the metric collection from `collect_metrics()`. An alternative is to extract a shared helper, but for a bug fix, keeping it self-contained is fine. If the builder prefers, they can extract a `_collect_raw_metrics()` helper called by both `collect_metrics()` and `scan_now()` — that's acceptable too.

### File 2: `src/probos/agents/medical/diagnostician.py`

#### 2a. Update `_INSTRUCTIONS` to differentiate the two intents

Replace the current `_INSTRUCTIONS` string:

```python
_INSTRUCTIONS = (
    "You are the ProbOS Diagnostician.  You receive health alerts from the Vitals Monitor "
    "and produce structured root-cause diagnoses.\n\n"
    "You handle two types of requests:\n\n"
    "1. **medical_alert** — A threshold breach detected by the Vitals Monitor. "
    "Alert data (severity, metric, current_value, threshold, affected) is provided. "
    "Analyze the specific alert and diagnose the root cause.\n\n"
    "2. **diagnose_system** — An on-demand diagnostic scan requested by the crew. "
    "Current system metrics are provided from the Vitals Monitor. Analyze the overall "
    "system health and report any anomalies, even if no thresholds have been breached.\n\n"
    "For both types:\n"
    "1. Identify root cause: agent problem, pool problem, trust issue, memory issue, or load.\n"
    "2. Recommend a treatment: 'medical_remediate' for acute fixes or 'medical_tune' for config.\n\n"
    "Respond with JSON:\n"
    '{"severity": "low|medium|high|critical", "category": "agent|pool|trust|memory|performance", '
    '"affected_components": ["..."], "root_cause": "...", "evidence": ["..."], '
    '"recommended_treatment": "...", "treatment_intent": "medical_remediate|medical_tune", '
    '"treatment_params": {...}}'
)
```

#### 2b. Override `perceive()` to fetch metrics for `diagnose_system`

Add a `perceive()` override that detects `diagnose_system` intents and enriches the context with live metrics from VitalsMonitor. Add these imports and the method to the class:

```python
import logging

logger = logging.getLogger(__name__)
```

Add the `perceive()` method to `DiagnosticianAgent`:

```python
async def perceive(self, intent: dict[str, Any]) -> dict[str, Any]:
    """Enrich diagnose_system intents with live metrics from VitalsMonitor (AD-350)."""
    result = await super().perceive(intent)

    if intent.get("intent") == "diagnose_system" and hasattr(self, "_runtime") and self._runtime:
        # Find the VitalsMonitor agent
        vitals_agent = None
        for agent in self._runtime.registry.all():
            if getattr(agent, "agent_type", None) == "vitals_monitor":
                vitals_agent = agent
                break

        if vitals_agent is not None:
            try:
                metrics = await vitals_agent.scan_now()
                result["context"] = (
                    f"LIVE SYSTEM METRICS (from Vitals Monitor scan):\n"
                    f"{json.dumps(metrics, indent=2, default=str)}"
                )
            except Exception as e:
                logger.warning("Diagnostician: VitalsMonitor scan failed: %s", e)
                result["context"] = "VitalsMonitor scan failed — diagnose based on available information."
        else:
            result["context"] = "VitalsMonitor not found — diagnose based on available information."

    return result
```

Add `import json` to the imports at the top of the file.

**Important:** The `_runtime` attribute is set by the runtime when registering agents (same pattern used by `IntrospectionAgent`). The Diagnostician already has access to it through the CognitiveAgent base class when the runtime registers the agent.

Verify this: check if `CognitiveAgent.__init__` or the runtime's `_register_agent` / pool code sets `_runtime` on agents. If it does, the above code works as-is. If not, add this to `__init__`:

```python
def __init__(self, **kwargs: Any) -> None:
    kwargs.setdefault("pool", "medical")
    super().__init__(**kwargs)
    self._runtime = kwargs.get("runtime")
```

### File 3: Tests — `tests/test_diagnostician.py` (NEW FILE)

Create a focused test file:

```python
"""Tests for DiagnosticianAgent — BF-003 fix (AD-350)."""

from __future__ import annotations

import pytest

from probos.agents.medical.diagnostician import DiagnosticianAgent


class TestDiagnosticianIntents:
    """Verify intent descriptors and handled intents."""

    def test_handles_medical_alert(self):
        agent = DiagnosticianAgent(agent_id="diag-1")
        assert "medical_alert" in agent._handled_intents

    def test_handles_diagnose_system(self):
        agent = DiagnosticianAgent(agent_id="diag-1")
        assert "diagnose_system" in agent._handled_intents

    def test_instructions_differentiate_intents(self):
        """BF-003: Instructions must distinguish medical_alert from diagnose_system."""
        agent = DiagnosticianAgent(agent_id="diag-1")
        assert "medical_alert" in agent.instructions
        assert "diagnose_system" in agent.instructions
        # Should not tell LLM to analyze "alert data" for both intents
        # (the old bug — instructions said "analyze the alert data" for both)
        assert agent.instructions.count("alert data") <= 1


class TestDiagnosticianPerceive:
    """BF-003: perceive() should enrich diagnose_system with live metrics."""

    @pytest.mark.asyncio
    async def test_perceive_diagnose_system_with_vitals(self):
        """diagnose_system intent should include VitalsMonitor metrics in context."""

        class _FakeVitals:
            agent_type = "vitals_monitor"

            async def scan_now(self):
                return {"system_health": 0.95, "pool_health": {"core": 1.0}, "trust_mean": 0.7}

        class _FakeRegistry:
            def all(self):
                return [_FakeVitals()]

        class _FakeRuntime:
            registry = _FakeRegistry()

        agent = DiagnosticianAgent(agent_id="diag-1", runtime=_FakeRuntime())
        result = await agent.perceive({"intent": "diagnose_system", "params": {"focus": "trust"}})
        assert "LIVE SYSTEM METRICS" in result.get("context", "")
        assert "system_health" in result.get("context", "")

    @pytest.mark.asyncio
    async def test_perceive_diagnose_system_without_vitals(self):
        """diagnose_system without VitalsMonitor should degrade gracefully."""

        class _FakeRegistry:
            def all(self):
                return []

        class _FakeRuntime:
            registry = _FakeRegistry()

        agent = DiagnosticianAgent(agent_id="diag-1", runtime=_FakeRuntime())
        result = await agent.perceive({"intent": "diagnose_system", "params": {}})
        assert "not found" in result.get("context", "").lower()

    @pytest.mark.asyncio
    async def test_perceive_medical_alert_unchanged(self):
        """medical_alert intents should not trigger VitalsMonitor scan."""
        agent = DiagnosticianAgent(agent_id="diag-1")
        result = await agent.perceive({
            "intent": "medical_alert",
            "params": {"severity": "warning", "metric": "pool_health"},
        })
        # Should NOT contain "LIVE SYSTEM METRICS" — alert already has data
        assert "LIVE SYSTEM METRICS" not in result.get("context", "")

    @pytest.mark.asyncio
    async def test_perceive_diagnose_system_no_runtime(self):
        """No runtime = graceful fallback, no crash."""
        agent = DiagnosticianAgent(agent_id="diag-1")
        result = await agent.perceive({"intent": "diagnose_system", "params": {}})
        # Should not crash, context may be empty or contain fallback text
        assert isinstance(result, dict)


class TestVitalsMonitorScanNow:
    """Test the on-demand scan_now() method added for AD-350."""

    @pytest.mark.asyncio
    async def test_scan_now_no_runtime(self):
        from probos.agents.medical.vitals_monitor import VitalsMonitorAgent
        agent = VitalsMonitorAgent(agent_id="vm-1", pool="medical_vitals")
        metrics = await agent.scan_now()
        assert "pulse" in metrics
        assert "timestamp" in metrics
        # No runtime = minimal metrics only
        assert "pool_health" not in metrics

    @pytest.mark.asyncio
    async def test_scan_now_with_runtime(self):
        from probos.agents.medical.vitals_monitor import VitalsMonitorAgent
        from probos.types import AgentState

        class _FakeAgent:
            state = AgentState.ACTIVE
            confidence = 0.9
            id = "fake-1"

        class _FakePool:
            target_size = 1
            healthy_agents = [_FakeAgent()]

        class _FakeTrust:
            def all_scores(self):
                return {"fake-1": 0.8}

        class _FakeRegistry:
            def all(self):
                return [_FakeAgent()]

        class _FakeRuntime:
            pools = {"test_pool": _FakePool()}
            trust_network = _FakeTrust()
            dream_scheduler = None
            attention = None
            registry = _FakeRegistry()

        agent = VitalsMonitorAgent(agent_id="vm-1", pool="medical_vitals", runtime=_FakeRuntime())
        metrics = await agent.scan_now()
        assert "pool_health" in metrics
        assert "trust_mean" in metrics
        assert "system_health" in metrics
        assert metrics["pool_health"]["test_pool"] == 1.0

    @pytest.mark.asyncio
    async def test_scan_now_does_not_emit_alerts(self):
        """scan_now() must NOT check thresholds or emit alerts."""
        from probos.agents.medical.vitals_monitor import VitalsMonitorAgent

        class _FakeRuntime:
            pools = {}
            trust_network = type("T", (), {"all_scores": lambda self: {}})()
            dream_scheduler = None
            attention = None
            registry = type("R", (), {"all": lambda self: []})()

        agent = VitalsMonitorAgent(agent_id="vm-1", pool="medical_vitals", runtime=_FakeRuntime())
        # scan_now should return metrics without calling _check_thresholds
        metrics = await agent.scan_now()
        assert "timestamp" in metrics
```

**Total expected new tests for AD-350:** ~8 pytest tests

---

## Execution Checklist

After implementing all three ADs:

1. Run targeted tests first:
   - `uv run pytest tests/test_prompt_builder.py tests/test_decomposer.py -v`
   - `uv run pytest tests/test_diagnostician.py -v`
   - `cd ui && npx vitest run src/__tests__/useStore.test.ts`
2. Then run the full test suite: `uv run pytest tests/ -v`
3. All pre-existing tests must still pass.
4. Append AD-348, AD-349, AD-350 entries to `DECISIONS.md`.

## AD Entries for DECISIONS.md

Append these after the last AD entry:

```markdown
### AD-348: Fix Self-Mod False Positive on Knowledge Questions (BF-001)

Knowledge questions ("who is Alan Turing?") no longer trigger capability_gap. Prompt rules in prompt_builder.py and decomposer.py updated to classify general knowledge/factual questions as conversational (answer directly) rather than task gaps. The "who is Alan Turing?" gap example removed from _GAP_EXAMPLES. Distinction: tasks requiring external tools (translation, web search) → capability_gap; well-known factual questions → direct LLM answer.

### AD-349: Fix Agent Orbs Escaping Pool Group Spheres (BF-002)

`poolToGroup` and `poolGroups` persisted in Zustand state from `state_snapshot` handler. `agent_state` handler passes persisted pool group data to `computeLayout()`, preserving cluster positions. Previously, `agent_state` called `computeLayout(agents)` without pool data, falling back to flat Fibonacci sphere layout.

### AD-350: Fix Diagnostician Bypassing VitalsMonitor (BF-003)

VitalsMonitorAgent gains `scan_now()` for on-demand metric collection (no threshold checks, no alerts). DiagnosticianAgent overrides `perceive()` to detect `diagnose_system` intents and fetch live metrics via `scan_now()`. Instructions updated to differentiate `medical_alert` (alert data provided) from `diagnose_system` (metrics gathered proactively). Graceful fallback if VitalsMonitor unavailable.
```
