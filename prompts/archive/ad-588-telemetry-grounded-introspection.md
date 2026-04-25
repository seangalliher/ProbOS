# AD-588: Telemetry-Grounded Introspection

**Priority:** High
**Issue:** #152
**Depends on:** AD-587 (COMPLETE — Cognitive Architecture Manifest)
**Extends:** AD-504 (self-monitoring), AD-568d (source attribution)

## Problem

When agents are asked introspective questions ("How do you feel about your trust score?" "What's your memory like?" "Do you process during stasis?"), they confabulate narratives instead of consulting actual system metrics. AD-587 provided a static self-model (the manifest); AD-588 adds dynamic, real-time telemetry so agents can ground self-referential claims in actual data.

**Current gap:** Self-monitoring context (`_build_self_monitoring_context()` in `proactive.py:1313`) is ONLY injected into the `proactive_think` prompt path. DM (`_build_user_message()` at `cognitive_agent.py:2052`) and Ward Room (`cognitive_agent.py:2125`) responses receive zero self-monitoring data. Agents literally cannot access their own telemetry when answering direct questions about themselves.

**Theoretical basis:** Nisbett & Wilson (1977) — humans confabulate about cognitive processes they can't introspect. Fix: provide the actual data, not suppress confabulation. AD-587 = static architecture knowledge. AD-588 = dynamic runtime state. AD-589 (future) = faithfulness verification.

## Design

Three components:

### Component 1: IntrospectiveTelemetryService

New module `src/probos/cognitive/introspective_telemetry.py`. Stateless service that queries existing runtime services to assemble telemetry snapshots.

```python
class IntrospectiveTelemetryService:
    """AD-588: Queryable interface for agent self-knowledge grounded in actual telemetry."""

    def __init__(self, *, runtime: Any) -> None:
        self._runtime = runtime

    async def get_memory_state(self, agent_id: str) -> dict[str, Any]:
        """Episode count, lifecycle, retrieval mechanism, capacity."""

    async def get_trust_state(self, agent_id: str) -> dict[str, Any]:
        """Score, observations, uncertainty, recent trend, trust model."""

    async def get_cognitive_state(self, agent_id: str) -> dict[str, Any]:
        """Zone, cooldown, recent posts count, self-similarity."""

    async def get_temporal_state(self, agent_id: str) -> dict[str, Any]:
        """Uptime, birth age, last action, lifecycle state."""

    async def get_social_state(self, agent_id: str) -> dict[str, Any]:
        """Routing affinities (Hebbian), interaction breadth."""

    async def get_full_snapshot(self, agent_id: str) -> dict[str, Any]:
        """All five telemetry domains combined."""
```

Each method returns a flat dict. All methods are best-effort (return partial data on failure, never raise). The service does NOT store state — it reads from existing runtime services.

**Data sources (all verified in live codebase):**
- `runtime.episodic_memory.count_for_agent(agent_id)` — episode count (`episodic.py:1256`)
- `runtime.trust_network.get_score(agent_id)` — trust score (`trust.py:385`)
- `runtime.trust_network.get_record(agent_id)` — alpha, beta, observations, uncertainty (`trust.py:392`)
- `runtime.trust_network.get_events_for_agent(agent_id, n=5)` — recent trust events (`trust.py:401`)
- Circuit breaker zone — `circuit_breaker.get_zone(agent_id)` (accessed via `proactive._circuit_breaker`)
- Ward Room recent posts — `runtime.ward_room.get_posts_by_author(callsign, ...)` (`proactive.py:1375`)
- `runtime._lifecycle_state` — lifecycle state
- `runtime._start_time_wall` — system start time
- Agent attributes: `_birth_timestamp`, `rank`, `sovereign_id`, `_orientation_context.manifest`

### Component 2: Self-Query Detection + Telemetry Injection

Modify `_build_user_message()` in `cognitive_agent.py` to detect introspective questions in DM and Ward Room paths, and inject telemetry when detected.

**Detection approach:** Keyword/pattern matching on the captain's text or Ward Room post content. Not LLM-based — must be fast, deterministic, zero-token.

```python
_INTROSPECTIVE_PATTERNS = [
    # Memory queries
    r"\b(?:your|you)\b.*\b(?:memor(?:y|ies)|remember|recall|forget|episode)\b",
    # Trust queries
    r"\b(?:your|you)\b.*\b(?:trust|reputation|reliab|scor)\b",
    # State queries
    r"\b(?:how (?:are|do) you|how.*feel|what.*like|your state|your status)\b",
    # Architecture queries
    r"\b(?:how (?:do|does) your|your (?:brain|mind|cognit|process|think))\b",
    # Stasis queries
    r"\b(?:stasis|offline|sleep|shutdown|dream|while.*(?:away|gone|down))\b",
]
```

When detected, call `IntrospectiveTelemetryService.get_full_snapshot()` and inject a telemetry section into the user message with grounding instructions:

```
--- Your Telemetry (AD-588: ground self-referential claims in these metrics) ---
Memory: 47 episodes (cosine similarity retrieval, no offline processing)
Trust: 0.72 (23 observations, uncertainty ±0.08, trend: stable)
Cognitive zone: GREEN
Uptime: 2.3h | Birth: 2.3h ago | Last action: 4m ago

When answering questions about yourself, cite these numbers rather than
generating narratives. You may express warmth and personality, but ground
factual claims about your architecture and state in your telemetry.
---
```

**Injection points:**

1. **DM path** (`cognitive_agent.py:2052`, `intent_name == "direct_message"`): After temporal context (line 2060), before working memory (line 2063). Detect on `params.get("text", "")`.

2. **Ward Room path** (`cognitive_agent.py:2125`, `intent_name == "ward_room_notification"`): After temporal context (line 2141), before working memory (line 2144). Detect on `params.get("text", "")` + `params.get("title", "")`.

3. **Proactive think path**: Already has self-monitoring (line 2379). Add telemetry snapshot to `context_parts` dict. In `proactive.py:_gather_context()`, after the self-monitoring context assembly (line 1267 `context["self_monitoring"] = self_monitoring`), add telemetry snapshot as `context["introspective_telemetry"]`. Render in `_build_user_message()` proactive path after self-monitoring rendering (line 2459).

### Component 3: Extend Self-Monitoring to DM/Ward Room Paths

The gap isn't just introspective questions — agents should have basic self-awareness of their cognitive zone in ALL response paths, not just proactive. When an agent is in AMBER or RED zone, they should know this during DMs and Ward Room responses too.

**Minimal injection:** Add cognitive zone and memory state context to DM and Ward Room paths. NOT the full self-monitoring block (recent posts, similarity, notebooks — those are proactive-specific). Just:
- Cognitive zone (if not GREEN)
- Memory state (episode count + lifecycle note if sparse)

This uses data already available on the agent via `_working_memory` (AD-573 syncs cognitive zone to working memory in `proactive.py:1419-1431`). No additional service calls needed for the zone — read from `agent._working_memory`.

## Implementation

### File 1: `src/probos/cognitive/introspective_telemetry.py` (NEW)

Create `IntrospectiveTelemetryService` class with the six methods described above.

**Constructor:**
```python
def __init__(self, *, runtime: Any) -> None:
    self._runtime = runtime
```

**`get_memory_state(agent_id: str) -> dict[str, Any]`:**
```python
result: dict[str, Any] = {}
rt = self._runtime
if hasattr(rt, 'episodic_memory') and rt.episodic_memory:
    try:
        result["episode_count"] = await rt.episodic_memory.count_for_agent(agent_id)
    except Exception:
        result["episode_count"] = "unknown"
result["retrieval"] = "cosine_similarity"
result["capacity"] = "unbounded"
result["offline_processing"] = False
# Lifecycle
result["lifecycle"] = getattr(rt, '_lifecycle_state', 'unknown')
return result
```

**`get_trust_state(agent_id: str) -> dict[str, Any]`:**
```python
result: dict[str, Any] = {}
if hasattr(rt, 'trust_network') and rt.trust_network:
    trust_net = rt.trust_network
    result["score"] = round(trust_net.get_score(agent_id), 3)
    record = trust_net.get_record(agent_id)
    if record:
        result["observations"] = int(record.observations)
        result["uncertainty"] = round(record.uncertainty, 3)
    # Recent trend
    events = trust_net.get_events_for_agent(agent_id, n=5)
    if len(events) >= 2:
        old = events[0].new_score
        new = events[-1].new_score
        if new > old + 0.02:
            result["trend"] = "rising"
        elif new < old - 0.02:
            result["trend"] = "falling"
        else:
            result["trend"] = "stable"
    result["model"] = "bayesian_beta"
    result["range"] = "0.05–0.95"
return result
```

Note: `_resolve_agent(agent_id)` is a private helper:

```python
def _resolve_agent(self, agent_id: str) -> Any:
    """Resolve agent object from registry by ID."""
    rt = self._runtime
    if hasattr(rt, 'registry') and rt.registry:
        return rt.registry.get(agent_id)  # returns BaseAgent | None
    return None
```

**`get_cognitive_state(agent_id: str) -> dict[str, Any]`:**

Zone is available via working memory (AD-573 syncs zone from circuit breaker to working memory at `proactive.py:1425`). The proactive loop is NOT stored on the runtime, so circuit breaker is not directly accessible.

```python
result: dict[str, Any] = {}
agent = self._resolve_agent(agent_id)
if agent:
    wm = getattr(agent, '_working_memory', None)
    if wm and hasattr(wm, 'get_cognitive_zone'):
        zone = wm.get_cognitive_zone()
        if zone:
            result["zone"] = zone
result["regulation_model"] = "graduated_zones"
return result
```

**`get_temporal_state(agent_id: str) -> dict[str, Any]`:**
```python
result: dict[str, Any] = {}
now = time.time()
result["system_uptime_hours"] = round((now - getattr(rt, '_start_time_wall', now)) / 3600, 1)
agent = self._resolve_agent(agent_id)
if agent:
    birth = getattr(agent, '_birth_timestamp', None)
    if birth:
        result["agent_age_hours"] = round((now - birth) / 3600, 1)
    if hasattr(agent, 'meta') and agent.meta.last_active:
        last_active = agent.meta.last_active
        delta = (datetime.now(timezone.utc) - last_active).total_seconds()
        result["last_action_minutes"] = round(delta / 60, 1)
result["lifecycle"] = getattr(rt, '_lifecycle_state', 'unknown')
return result
```

**`get_social_state(agent_id: str) -> dict[str, Any]`:**

Hebbian weights in ProbOS are intent→agent (routing weights), not agent→agent. Report the agent's strongest routing weights.

```python
result: dict[str, Any] = {}
if hasattr(rt, 'hebbian_router') and rt.hebbian_router:
    try:
        # Find routing weights where this agent is the target
        all_weights = rt.hebbian_router.all_weights_typed()  # dict[(src, tgt, rel), weight]
        agent_weights = {
            src: w for (src, tgt, rel), w in all_weights.items()
            if tgt == agent_id and w > 0
        }
        if agent_weights:
            # Top 3 strongest routing affinities
            top = sorted(agent_weights.items(), key=lambda x: x[1], reverse=True)[:3]
            result["routing_affinities"] = [
                {"intent": src, "weight": round(w, 2)} for src, w in top
            ]
    except Exception:
        pass
# Trust network social signals — how many agents this agent has interacted with
if hasattr(rt, 'trust_network') and rt.trust_network:
    try:
        events = rt.trust_network.get_events_for_agent(agent_id, n=20)
        unique_intents = set(e.intent_type for e in events)
        result["interaction_breadth"] = len(unique_intents)
    except Exception:
        pass
return result
```

**`get_full_snapshot(agent_id: str) -> dict[str, Any]`:**
Calls all five methods, merges into `{"memory": {...}, "trust": {...}, "cognitive": {...}, "temporal": {...}, "social": {...}}`. Best-effort — each domain returns independently on failure.

**`render_telemetry_context(snapshot: dict[str, Any]) -> str`:**
Class method that renders the snapshot into a human-readable context block. Format:

```
--- Your Telemetry (ground self-referential claims in these metrics) ---
Memory: {episode_count} episodes (cosine similarity retrieval, no offline processing)
Trust: {score} ({observations} observations, uncertainty ±{uncertainty}, trend: {trend})
Cognitive zone: {zone}
Uptime: {system_uptime_hours}h | Age: {agent_age_hours}h | Last action: {last_action_minutes}m ago

When discussing yourself, cite these numbers. You may express warmth and
personality — do not generate claims about architecture not reflected here.
---
```

### File 2: `src/probos/cognitive/cognitive_agent.py` (MODIFY)

**Change 2a — Update telemetry access pattern in `_build_user_message` to use runtime reference (no per-agent wiring needed):**

Agents already have `self._runtime` (line 57 via `kwargs.get("runtime")`). Access telemetry service via `self._runtime._introspective_telemetry` instead of a per-agent attribute. This eliminates the need for per-agent wiring.

**Change 2b — Add `_is_introspective_query` static helper method (near line 1860, before `_build_temporal_context`):**

```python
_INTROSPECTIVE_PATTERNS: ClassVar[list[re.Pattern]] = [
    re.compile(r"\b(?:your|you)\b.*\b(?:memor(?:y|ies)|remember|recall|forget|episode)\b", re.IGNORECASE),
    re.compile(r"\b(?:your|you)\b.*\b(?:trust|reputation|reliab|scor)\b", re.IGNORECASE),
    re.compile(r"\b(?:how (?:are|do) you|how.*feel|what.*(?:like for you)|your (?:state|status))\b", re.IGNORECASE),
    re.compile(r"\b(?:how (?:do|does) your|your (?:brain|mind|cognit|process|think))\b", re.IGNORECASE),
    re.compile(r"\b(?:stasis|offline|sleep|shutdown|dream|while.*(?:away|gone|down))\b", re.IGNORECASE),
    re.compile(r"\b(?:tell me about yourself|who are you|what are you|describe yourself)\b", re.IGNORECASE),
]

@staticmethod
def _is_introspective_query(text: str) -> bool:
    """AD-588: Detect introspective questions in captain/crew messages."""
    if not text:
        return False
    for pattern in CognitiveAgent._INTROSPECTIVE_PATTERNS:
        if pattern.search(text):
            return True
    return False
```

Note: `import re` is already at the top of `cognitive_agent.py`. Verify this during build. If not, add it.

**Change 2c — DM path telemetry injection (`_build_user_message`, after temporal context at line 2060, before working memory at line 2063):**

```python
            # AD-588: Introspective telemetry for self-referential queries
            captain_text = params.get("text", "")
            _telemetry_svc = getattr(self._runtime, '_introspective_telemetry', None) if self._runtime else None
            if _telemetry_svc and self._is_introspective_query(captain_text):
                try:
                    _agent_id = getattr(self, 'sovereign_id', None) or self.id
                    _snapshot = await _telemetry_svc.get_full_snapshot(_agent_id)
                    _telemetry_text = _telemetry_svc.render_telemetry_context(_snapshot)
                    if _telemetry_text:
                        parts.append(_telemetry_text)
                        parts.append("")
                except Exception:
                    logger.debug("AD-588: telemetry injection failed for DM", exc_info=True)
```

**IMPORTANT:** `_build_user_message` is currently synchronous (`def`, not `async def`). To call the async `get_full_snapshot()`, we must make `_build_user_message` async.

**Call site (1 location):** `_decide_via_llm()` at `cognitive_agent.py:1173`:
```python
# BEFORE:
user_message = self._build_user_message(observation)

# AFTER:
user_message = await self._build_user_message(observation)
```

**Method signature:**
```python
# BEFORE (cognitive_agent.py:2045):
def _build_user_message(self, observation: dict) -> str:

# AFTER:
async def _build_user_message(self, observation: dict) -> str:
```

**Subclass overrides (MUST also be updated to `async def`):**
- `architect.py:550` — `def _build_user_message(...)` → `async def _build_user_message(...)`. Also update `super()._build_user_message(observation)` at line 555 to `await super()._build_user_message(observation)`.
- `builder.py:2132` — `def _build_user_message(...)` → `async def _build_user_message(...)`. Also update `super()._build_user_message(observation)` at line 2137 to `await super()._build_user_message(observation)`.

**Change 2d — Ward Room path telemetry injection (after temporal context at line 2141, before working memory at line 2144):**

```python
            # AD-588: Introspective telemetry for self-referential ward room posts
            _wr_text = f"{params.get('title', '')} {params.get('text', '')}".strip()
            _telemetry_svc = getattr(self._runtime, '_introspective_telemetry', None) if self._runtime else None
            if _telemetry_svc and self._is_introspective_query(_wr_text):
                try:
                    _agent_id = getattr(self, 'sovereign_id', None) or self.id
                    _snapshot = await _telemetry_svc.get_full_snapshot(_agent_id)
                    _telemetry_text = _telemetry_svc.render_telemetry_context(_snapshot)
                    if _telemetry_text:
                        wr_parts.append("")
                        wr_parts.append(_telemetry_text)
                except Exception:
                    logger.debug("AD-588: telemetry injection failed for WR", exc_info=True)
```

**Change 2e — Proactive think path telemetry rendering (after self-monitoring rendering, line 2459, after notebook content):**

```python
            # AD-588: Introspective telemetry snapshot (always available in proactive path)
            introspective_telemetry = context_parts.get("introspective_telemetry")
            if introspective_telemetry:
                pt_parts.append("")
                pt_parts.append(introspective_telemetry)
```

**Change 2f — Cognitive zone awareness for DM and Ward Room (non-introspective):**

After the temporal context in DM path (after line 2060), add basic zone awareness:

```python
            # AD-588: Cognitive zone awareness in DM path
            _zone = None
            _wm_zone = getattr(self, '_working_memory', None)
            if _wm_zone and hasattr(_wm_zone, 'get_cognitive_zone'):
                _zone = _wm_zone.get_cognitive_zone()
            if _zone and _zone != "green":
                parts.append(f"[COGNITIVE ZONE: {_zone.upper()}]")
                parts.append("")
```

Same pattern in Ward Room path (after line 2141).

**Note:** Need to verify `get_cognitive_zone()` exists on `AgentWorkingMemory`. Check `agent_working_memory.py`.

### File 3: `src/probos/proactive.py` (MODIFY)

**Change 3a — Inject telemetry snapshot into `_gather_context()` (after self-monitoring assembly at line 1269):**

In `_gather_context()`, after line 1269 (`context["self_monitoring"] = self_monitoring`), add:

```python
        # AD-588: Introspective telemetry for proactive path
        try:
            _telemetry_svc = getattr(rt, '_introspective_telemetry', None)
            if _telemetry_svc:
                _agent_id = getattr(agent, 'sovereign_id', None) or agent.id
                _snapshot = await _telemetry_svc.get_full_snapshot(_agent_id)
                _rendered = _telemetry_svc.render_telemetry_context(_snapshot)
                if _rendered:
                    context["introspective_telemetry"] = _rendered
        except Exception:
            logger.debug("AD-588: telemetry context assembly failed", exc_info=True)
```

### File 4: `src/probos/runtime.py` (MODIFY)

Wire the `IntrospectiveTelemetryService` to the runtime after the orientation service wiring (line 1138).

**Location: After line 1139 (`self._oracle_service = cog.oracle_service`):**

```python
        # AD-588: Introspective Telemetry Service
        try:
            from probos.cognitive.introspective_telemetry import IntrospectiveTelemetryService
            self._introspective_telemetry = IntrospectiveTelemetryService(runtime=self)
            logger.info("AD-588: IntrospectiveTelemetryService initialized")
        except Exception as e:
            logger.warning("IntrospectiveTelemetryService failed to start: %s — continuing without", e)
            self._introspective_telemetry = None
```

No per-agent wiring needed — agents access via `self._runtime._introspective_telemetry`.

No changes to `CognitiveServicesResult` or `init_cognitive_services()` — the telemetry service depends on having the full runtime reference (trust_network, episodic_memory, etc.), so it must be created after all services are wired, not inside cognitive_services init.

### File 5: `src/probos/cognitive/agent_working_memory.py` (MODIFY)

`get_cognitive_zone()` does not exist. Zone is currently accessed only via internal `_cognitive_state["zone"]` in `render_context()` (line 228). Add a public accessor:

```python
def get_cognitive_zone(self) -> str | None:
    """AD-588: Return cognitive zone if set via AD-573 sync."""
    return self._cognitive_state.get("zone")
```

Place after `update_cognitive_state()` (line 180). This is the correct access point — `update_cognitive_state(zone=...)` is called by `proactive.py:1425`.

## Prior Work Absorbed

- **AD-504** (`proactive.py:1313`): Self-monitoring context assembly — reused architecture, not duplicated
- **AD-506a** (graduated zones): Zone rendering pattern reused for DM/WR paths
- **AD-568d** (source attribution): Ambient attribution pattern — telemetry section follows same "grounding" approach
- **AD-573** (working memory): Zone sync path — already stores zone in working memory for cross-path access
- **AD-587** (manifest): Static self-model — AD-588 is the dynamic complement. Manifest data referenced in telemetry rendering
- **AD-502** (temporal context): Already present in all three paths — telemetry hooks into the same sequence

## Files Modified

| File | Change | Type |
|---|---|---|
| `src/probos/cognitive/introspective_telemetry.py` | NEW — IntrospectiveTelemetryService | New module |
| `src/probos/cognitive/cognitive_agent.py` | Self-query detection + telemetry injection in DM/WR/proactive paths + async `_build_user_message` | Modify |
| `src/probos/cognitive/architect.py` | `_build_user_message` → async + await super() | Modify |
| `src/probos/cognitive/builder.py` | `_build_user_message` → async + await super() | Modify |
| `src/probos/proactive.py` | Telemetry snapshot in `_gather_context()` | Modify |
| `src/probos/runtime.py` | Wire IntrospectiveTelemetryService (after line 1139) | Modify |
| `src/probos/cognitive/agent_working_memory.py` | Add `get_cognitive_zone()` method | Modify |

## Files NOT Modified

- `src/probos/cognitive/orientation.py` — AD-587 manifest already done, no changes needed
- `src/probos/consensus/trust.py` — telemetry service reads, doesn't modify
- `src/probos/cognitive/episodic.py` — telemetry service reads, doesn't modify
- `tests/test_ad593_pruning_acceleration.py` — unrelated
- `tests/test_orientation.py` — AD-587 tests unchanged

## Testing

### Test File: `tests/test_ad588_telemetry_introspection.py` (NEW)

**Test Class 1: `TestIntrospectiveTelemetryService`** (~12 tests)

1. `test_get_memory_state_with_episodes` — mock episodic_memory.count_for_agent returning 47, verify episode_count=47, retrieval="cosine_similarity"
2. `test_get_memory_state_no_episodic` — runtime without episodic_memory, verify graceful return
3. `test_get_trust_state_with_record` — mock trust_network with score 0.72, 23 observations, verify all fields
4. `test_get_trust_state_baseline` — no trust record, verify score=0.5 (prior)
5. `test_get_trust_state_trend_rising` — mock 5 events with increasing scores, verify trend="rising"
6. `test_get_trust_state_trend_falling` — mock 5 events with decreasing scores, verify trend="falling"
7. `test_get_trust_state_trend_stable` — mock events with flat scores, verify trend="stable"
8. `test_get_cognitive_state_zone` — mock circuit breaker returning "amber", verify zone="amber"
9. `test_get_temporal_state` — mock runtime start time + agent birth, verify uptime/age
10. `test_get_social_state_hebbian` — mock hebbian_router.get_weight, verify hebbian_captain
11. `test_get_full_snapshot_all_domains` — verify all 5 domains present in snapshot
12. `test_get_full_snapshot_partial_failure` — one domain throws, others still return

**Test Class 2: `TestSelfQueryDetection`** (~8 tests)

1. `test_detects_memory_query` — "What are your memories like?" → True
2. `test_detects_trust_query` — "How's your trust score?" → True
3. `test_detects_state_query` — "How are you doing?" → True
4. `test_detects_architecture_query` — "How does your brain work?" → True
5. `test_detects_stasis_query` — "What happened during stasis?" → True
6. `test_detects_identity_query` — "Tell me about yourself" → True
7. `test_ignores_non_introspective` — "What's the weather like?" → False
8. `test_ignores_third_person` — "Is the captain's memory good?" → False

**Test Class 3: `TestTelemetryInjection`** (~8 tests)

1. `test_dm_introspective_gets_telemetry` — DM with "How's your memory?", verify telemetry section in user message
2. `test_dm_non_introspective_no_telemetry` — DM with "Run diagnostics", verify no telemetry section
3. `test_wr_introspective_gets_telemetry` — Ward Room post about trust, verify telemetry injected
4. `test_proactive_gets_telemetry_snapshot` — proactive path with telemetry in context_parts, verify rendered
5. `test_telemetry_injection_failure_graceful` — telemetry service raises, verify no crash
6. `test_no_telemetry_service_no_crash` — `_introspective_telemetry = None`, verify normal response
7. `test_cognitive_zone_in_dm_amber` — agent in AMBER zone, verify zone appears in DM prompt
8. `test_cognitive_zone_green_not_shown` — agent in GREEN zone, verify no zone note in DM

**Test Class 4: `TestRenderTelemetryContext`** (~4 tests)

1. `test_renders_full_snapshot` — all domains present, verify readable output
2. `test_renders_partial_snapshot` — only memory and trust, verify handles missing domains
3. `test_renders_empty_snapshot` — empty dict, verify returns empty string or minimal
4. `test_grounding_instructions_present` — verify output contains grounding language

**Total: ~32 tests**

### Verification

```bash
# 1. AD-588 tests
pytest tests/test_ad588_telemetry_introspection.py -v

# 2. Regression: orientation tests (AD-587 unchanged)
pytest tests/test_orientation.py -v

# 3. Regression: proactive tests
pytest tests/test_proactive.py -v

# 4. Regression: cognitive agent tests
pytest tests/test_cognitive_agent.py -v

# 5. Broader dreaming/memory regression
pytest tests/test_dreaming.py tests/test_ad567b_anchor_recall.py -v
```

All must pass before committing.

## Build Verification Checklist

Before executing, the builder MUST verify:

- [x] `import re` exists at top of `cognitive_agent.py` — **CONFIRMED** (line 8)
- [x] `_build_user_message` call site — **CONFIRMED** 1 call site in `_decide_via_llm` (line 1173)
- [x] `_build_user_message` subclass overrides — **CONFIRMED** in `architect.py:550` and `builder.py:2132` (both delegate to super() for conversational intents)
- [x] `AgentWorkingMemory.get_cognitive_zone()` — **CONFIRMED** does NOT exist; `_cognitive_state["zone"]` is set by `update_cognitive_state()` (line 180), need to add `get_cognitive_zone()` method
- [x] Startup wiring — **CONFIRMED** at `runtime.py:1138-1139` (after orientation_service and oracle_service)
- [x] Proactive loop / circuit breaker access — **CONFIRMED** proactive loop is NOT stored on runtime. Use working memory `get_cognitive_zone()` (AD-573 syncs zone). No direct circuit breaker access needed.
- [x] `registry.get()` signature — **CONFIRMED** `registry.get(agent_id: AgentID) -> BaseAgent | None` at `substrate/registry.py:51`

## Tracking

Update these files:
- `PROGRESS.md` — add AD-588 entry
- `DECISIONS.md` — add AD-588 entry
- `docs/development/roadmap.md` — update AD-588 status to COMPLETE

## Engineering Principles Compliance

- **SRP**: `IntrospectiveTelemetryService` has one job — query and render telemetry. Detection is in `CognitiveAgent`. No god objects.
- **DI**: Service injected via runtime wiring, not constructed inside CognitiveAgent
- **Open/Closed**: New telemetry service extends prompt construction without modifying existing self-monitoring logic
- **Law of Demeter**: Service accesses runtime services via the runtime reference it was constructed with
- **Fail Fast (tiered)**: All telemetry queries are best-effort (log-and-degrade). Telemetry failure never blocks agent response.
- **DRY**: Does NOT duplicate `_build_self_monitoring_context()` — that stays in proactive.py for proactive-specific context. Telemetry service provides different data (architectural grounding, not behavioral monitoring).
- **Cloud-Ready**: Service uses runtime interface, no direct storage access
