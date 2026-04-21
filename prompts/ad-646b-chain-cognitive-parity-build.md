# AD-646b: Chain Cognitive Parity — Build Prompt

**AD:** 646b  
**Depends on:** AD-646 (Universal Cognitive Baseline)  
**Issue:** #289  
**Scope:** ~150 lines across 4 files. Zero new modules. Zero new infrastructure.

---

## Problem

AD-646 gave the chain ward_room path a universal cognitive baseline (temporal, working memory, trust, ontology, confabulation guard). But six data sources still exist only in the one-shot ward_room path. These gaps cause chain responses to confabulate more than one-shot — agents lack self-monitoring, telemetry grounding, cold-start awareness, rich source attribution, self-recognition cues, and cross-tier oracle knowledge.

---

## Design

Four parts, each independently testable:

- **Part A:** Two new QUERY operations in query.py (async data)
- **Part B:** Three enhancements to `_build_cognitive_baseline()` in cognitive_agent.py (sync data)
- **Part C:** Chain definition update — add new QUERY keys
- **Part D:** Prompt consumption — analyze.py and compose.py render new data

---

## Part A: New QUERY Operations in `query.py`

Add two new async operations to the dispatch table. Follow the existing pattern (see `_query_credibility` at line 95, `_query_posts_by_author` at line 173).

### Operation 1: `self_monitoring`

DM thread self-repetition detection + cognitive zone check. Mirrors the one-shot pattern at `cognitive_agent.py` line 3639-3647.

```python
async def _query_self_monitoring(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """AD-646b: Self-monitoring for chain ward_room path.
    
    DM threads: check agent's recent posts for self-repetition (Jaccard).
    All threads: report cognitive zone if not green.
    """
    result_parts: list[str] = []
    
    # Cognitive zone from working memory
    # The agent object is not directly available here — read zone from context
    # (baseline already sets _working_memory_context, but zone is a separate check)
    # Context has _agent_id from observation
    agent_id = context.get("_agent_id", "") or _ctx(context, "agent_id")
    
    # DM self-monitoring: check for self-repetition in thread
    channel_name = _ctx(context, "channel_name")
    if channel_name.startswith("dm-"):
        ward_room = getattr(runtime, "ward_room", None)
        if ward_room:
            try:
                callsign = context.get("callsign", "") or _ctx(context, "callsign")
                thread_id = _ctx(context, "thread_id")
                if callsign and thread_id:
                    posts = await ward_room.get_posts_by_author(
                        callsign, limit=3, thread_id=thread_id,
                    )
                    if posts and len(posts) >= 2:
                        from probos.cognitive.similarity import jaccard_similarity, text_to_words
                        word_sets = [text_to_words(p["body"]) for p in posts]
                        total_sim = 0.0
                        pair_count = 0
                        for j in range(len(word_sets)):
                            for k in range(j + 1, len(word_sets)):
                                total_sim += jaccard_similarity(word_sets[j], word_sets[k])
                                pair_count += 1
                        if pair_count > 0:
                            avg_sim = total_sim / pair_count
                            if avg_sim >= 0.4:
                                result_parts.append(
                                    f"WARNING: Your last {len(posts)} messages in this thread "
                                    f"show {avg_sim:.0%} self-similarity. You may be repeating "
                                    "yourself. If you and the other person agree, conclude the "
                                    "conversation naturally. Do NOT restate conclusions you've "
                                    "already communicated. If there's nothing new to add, "
                                    "respond with exactly: [NO_RESPONSE]"
                                )
            except Exception:
                logger.debug("AD-646b: DM self-monitoring query failed", exc_info=True)

    return {"self_monitoring": "\n".join(result_parts) if result_parts else ""}
```

**Key details:**
- `channel_name` is in observation params (ward_room_router.py line 510 sends `channel_name`)
- `callsign` is in observation (set by perceive(), or from `_ctx(context, "callsign")`)
- `thread_id` is in observation params (ward_room_router.py line 506)
- `ward_room.get_posts_by_author(callsign, limit=3, thread_id=thread_id)` — same call as `_build_dm_self_monitoring()` at cognitive_agent.py line 2876
- Import `jaccard_similarity, text_to_words` from `probos.cognitive.similarity` (same as line 2882)

### Operation 2: `introspective_telemetry`

Conditional telemetry for self-referential threads. Mirrors the one-shot pattern at cognitive_agent.py line 3649-3665.

```python
async def _query_introspective_telemetry(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """AD-646b: Introspective telemetry for self-referential ward room threads.
    
    Only fires when the thread content matches introspective patterns (AD-588).
    Returns rendered telemetry text or empty string.
    """
    # Check if thread content is self-referential
    title = _ctx(context, "title")
    text = _ctx(context, "text")
    thread_text = f"{title} {text}".strip()
    
    if not thread_text:
        return {"introspective_telemetry": ""}
    
    from probos.cognitive.cognitive_agent import CognitiveAgent
    if not CognitiveAgent._is_introspective_query(thread_text):
        return {"introspective_telemetry": ""}
    
    telemetry_svc = getattr(runtime, '_introspective_telemetry', None)
    if not telemetry_svc:
        return {"introspective_telemetry": ""}
    
    try:
        agent_id = context.get("_agent_id", "") or _ctx(context, "agent_id")
        # sovereign_id preferred over agent_id for telemetry
        sovereign_id = context.get("sovereign_id", "") or agent_id
        snapshot = await telemetry_svc.get_full_snapshot(sovereign_id)
        rendered = telemetry_svc.render_telemetry_context(snapshot)
        return {"introspective_telemetry": rendered or ""}
    except Exception:
        logger.debug("AD-646b: introspective telemetry query failed", exc_info=True)
        return {"introspective_telemetry": ""}
```

**Key details:**
- `_is_introspective_query` is a `@staticmethod` on `CognitiveAgent` at line 3365 — import the class
- `_introspective_telemetry` service is on runtime (set during startup)
- `title` and `text` are in observation params (ward_room_router.py sends them)
- `sovereign_id` may be in observation (set by perceive), fallback to `agent_id`
- `get_full_snapshot(agent_id)` is async — returns dict with memory, trust, cognitive, temporal, social domains
- `render_telemetry_context(snapshot)` is a `@staticmethod` — returns formatted text

### Register both operations

Add to `_QUERY_OPERATIONS` dict at line 194:

```python
_QUERY_OPERATIONS: dict[str, QueryOperation] = {
    "thread_metadata": _query_thread_metadata,
    "thread_activity": _query_thread_activity,
    "comm_stats": _query_comm_stats,
    "credibility": _query_credibility,
    "unread_counts": _query_unread_counts,
    "unread_dms": _query_unread_dms,
    "trust_score": _query_trust_score,
    "trust_summary": _query_trust_summary,
    "posts_by_author": _query_posts_by_author,
    "self_monitoring": _query_self_monitoring,                 # AD-646b
    "introspective_telemetry": _query_introspective_telemetry,  # AD-646b
}
```

---

## Part B: Baseline Enhancements in `cognitive_agent.py`

Add three items to `_build_cognitive_baseline()` (at line 2969). Insert after item 8 (`_comm_proficiency`, line 3068), before `return state`.

### Enhancement 1: Cold-start note (BF-102)

Mirrors one-shot pattern at line 3675-3681:

```python
# 9. Cold-start note (BF-102) — sync check
_rt_cs = getattr(self, '_runtime', None)
if _rt_cs and getattr(_rt_cs, 'is_cold_start', False):
    state["_cold_start_note"] = (
        "SYSTEM NOTE: This is a fresh start. You have no prior "
        "episodic memories. Do not reference or invent past experiences."
    )
```

**Key detail:** `is_cold_start` is a boolean attribute on runtime (line 3676 pattern). Sync. No async.

### Enhancement 2: Rich source attribution (AD-568d override)

When the `_source_attribution` dataclass is present in observation (set by perceive's `_recall_relevant_memories()` at line 4327), render the full version with `primary_source`, `oracle_used`, `procedural_count`. This **overrides** the simplified count-only version set at item 5 (line 3044-3054).

```python
# 10. Rich source attribution override (AD-568d)
_attr = observation.get("_source_attribution")
if _attr:
    try:
        _sources_present: list[str] = []
        if _attr.episodic_count > 0:
            _sources_present.append(f"episodic memory ({_attr.episodic_count} episodes)")
        if _attr.procedural_count > 0:
            _sources_present.append(f"learned procedures ({_attr.procedural_count})")
        if _attr.oracle_used:
            _sources_present.append("ship's records")
        if not _sources_present:
            _sources_present.append("training knowledge only")
        state["_source_attribution_text"] = (
            f"<source_awareness>Your response draws on: {', '.join(_sources_present)}. "
            f"Primary basis: {_attr.primary_source.value}.</source_awareness>"
        )
    except Exception:
        logger.debug("AD-646b: Rich source attribution failed", exc_info=True)
```

**Key details:**
- `_source_attribution` is a `SourceAttribution` dataclass from `probos.cognitive.source_governance` — has `.episodic_count`, `.procedural_count`, `.oracle_used`, `.primary_source` (a `KnowledgeSource` enum with `.value`)
- Set at line 4327 by `compute_source_attribution()` during perceive/recall
- Overrides the simplified count-only version (item 5) because this runs AFTER item 5

### Enhancement 3: Self-recognition (AD-575)

Mirrors one-shot pattern at line 3732-3735:

```python
# 11. Self-recognition (AD-575) — sync regex
_content = observation.get("context", "")
if _content:
    self_cue = self._detect_self_in_content(_content)
    if self_cue:
        state["_self_recognition_cue"] = self_cue
```

**Key details:**
- `_detect_self_in_content()` at line 2740 — sync, regex-based, returns grounding cue string or empty string
- `observation["context"]` contains the thread content (set by perceive())
- New key `_self_recognition_cue` — not overriding any existing key

---

## Part C: Chain Definition Update in `cognitive_agent.py`

Update the ward_room chain QUERY step at line 1554 to include the two new operations:

```python
# Before (line 1554):
context_keys=("thread_metadata", "credibility"),

# After:
context_keys=("thread_metadata", "credibility", "self_monitoring", "introspective_telemetry"),
```

That's it. The QUERY executor (query.py line 294) iterates `context_keys`, looks up each in `_QUERY_OPERATIONS`, and awaits them sequentially. Results merge into `prior_results` which flows to ANALYZE and COMPOSE.

---

## Part D: Prompt Consumption

### D1: Thread analysis prompt in `analyze.py` — `_build_thread_analysis_prompt()`

The AD-646 "Your Current State" section (line 89-118) already renders baseline keys. Add three new sections AFTER `agent_state_section` and BEFORE `## Analysis Required`:

```python
# AD-646b: Oracle context — cross-tier knowledge grounding
oracle_section = ""
_oracle = context.get("_oracle_context", "")
if _oracle:
    oracle_section = (
        "## Cross-Tier Knowledge (Ship's Records)\n\n"
        "These are NOT your personal experiences. They are from the ship's shared "
        "knowledge stores. Treat as reference material, not memory.\n\n"
        f"{_oracle}\n\n"
    )

# AD-646b: Self-recognition cue
_self_cue = context.get("_self_recognition_cue", "")

# AD-646b: Self-monitoring from QUERY results
self_monitoring_section = ""
for pr in prior_results:
    if pr.success and pr.result:
        _sm = pr.result.get("self_monitoring", "")
        if _sm:
            self_monitoring_section = f"## Self-Monitoring\n\n{_sm}\n\n"
        _telemetry = pr.result.get("introspective_telemetry", "")
        if _telemetry:
            # Telemetry already has its own framing
            self_monitoring_section += f"{_telemetry}\n\n"
        break
```

Then update the user_prompt f-string. Current structure (line 120):

```python
user_prompt = (
    f"## Thread Content\n\n{thread_content}\n\n"
    f"{context_section}"
    f"{memory_section}"
    f"{agent_state_section}"
    f"## Analysis Required\n\n"
    ...
```

Change to:

```python
user_prompt = (
    f"## Thread Content\n\n{thread_content}\n\n"
    f"{context_section}"
    f"{memory_section}"
    f"{agent_state_section}"
    f"{oracle_section}"
    f"{self_monitoring_section}"
    + (f"{_self_cue}\n\n" if _self_cue else "")
    + f"## Analysis Required\n\n"
    ...
```

**Important:** The `_self_cue` is a simple text line (e.g., "You are being discussed in this thread."). Inject it raw, no section header needed.

### D2: Compose `_build_user_prompt()` in `compose.py`

Add oracle context rendering. Insert after the `_source_attr` block (line 296-298) and before the `_comm_prof` block (line 300):

```python
# AD-646b: Oracle context — cross-tier knowledge for compose
_oracle = context.get("_oracle_context", "")
if _oracle:
    parts.append(
        "## Cross-Tier Knowledge (Ship's Records)\n\n"
        "These are NOT your personal experiences. They are from the ship's shared "
        "knowledge stores. Treat as reference material, not memory.\n\n"
        + _oracle
    )

# AD-646b: Self-recognition cue
_self_cue = context.get("_self_recognition_cue", "")
if _self_cue:
    parts.append(_self_cue)
```

Also add self-monitoring and telemetry from QUERY results. These flow via `prior_results`. Insert after the existing "Prior QUERY data" block (line 269-275):

```python
# AD-646b: Self-monitoring and telemetry from QUERY results
for pr in prior_results:
    if pr.sub_task_type == SubTaskType.QUERY and pr.success and pr.result:
        _sm = pr.result.get("self_monitoring", "")
        if _sm:
            parts.append(f"## Self-Monitoring\n\n{_sm}")
        _telemetry = pr.result.get("introspective_telemetry", "")
        if _telemetry:
            parts.append(_telemetry)
        break
```

**Wait** — this will double-count with the existing "Prior QUERY data" block at line 269-275 which dumps ALL prior_results keys. The existing block does:

```python
for pr in prior_results:
    if pr.sub_task_type == SubTaskType.QUERY and pr.success and pr.result:
        lines = [f"- {k}: {v}" for k, v in pr.result.items()]
        if lines:
            parts.append("## Prior Data\n\n" + "\n".join(lines))
        break
```

This will render `self_monitoring` and `introspective_telemetry` as raw `- key: value` lines. To prevent double-rendering, **exclude** the new keys from the generic "Prior Data" dump:

```python
# Prior QUERY data (exclude keys with dedicated rendering)
_AD646B_DEDICATED_KEYS = {"self_monitoring", "introspective_telemetry"}
for pr in prior_results:
    if pr.sub_task_type == SubTaskType.QUERY and pr.success and pr.result:
        lines = [f"- {k}: {v}" for k, v in pr.result.items() if k not in _AD646B_DEDICATED_KEYS]
        if lines:
            parts.append("## Prior Data\n\n" + "\n".join(lines))
        break
```

Apply the same exclusion in analyze.py's `context_section` block (line 73-81):

```python
_AD646B_DEDICATED_KEYS = {"self_monitoring", "introspective_telemetry"}
context_section = ""
for pr in prior_results:
    if pr.success and pr.result:
        lines = []
        for k, v in pr.result.items():
            if k not in _AD646B_DEDICATED_KEYS:
                lines.append(f"- {k}: {v}")
        if lines:
            context_section = "## Prior Data\n\n" + "\n".join(lines) + "\n\n"
        break
```

---

## What NOT To Change

- **`_build_cognitive_extensions()`** — extensions are for proactive path overrides from `context_parts`. AD-646b adds no new extension keys.
- **`_build_situation_awareness()`** — proactive-only SA sweep. No changes.
- **`_execute_chain_with_intent_routing()`** — the observation flow is correct as-is from AD-646. Baseline runs, then extensions, then QUERY results flow via prior_results to ANALYZE/COMPOSE.
- **`proactive.py`** — no changes. Proactive path already has full data.
- **`ward_room_router.py`** — no changes. The params it sends already include all needed keys.
- **One-shot ward_room path** — no changes. It already has all data sources inline.
- **`introspective_telemetry.py`** — no changes. We call its existing methods.
- **`source_governance.py`** — no changes. We read the existing dataclass.

---

## Engineering Principles Compliance

| Principle | How This Change Complies |
|-----------|------------------------|
| **Single Responsibility** | Each QUERY operation has one job. Baseline enhancements each address one gap. |
| **Open/Closed** | QUERY operations added by registration — zero changes to `QueryHandler.__call__()`. |
| **DRY** | Self-monitoring reuses existing `jaccard_similarity` + `text_to_words`. Telemetry reuses `IntrospectiveTelemetryService`. Source attribution reuses the existing dataclass renderer pattern. |
| **Fail Fast (log-and-degrade)** | Both QUERY operations catch `Exception` with `logger.debug()`. Baseline enhancements wrap runtime reads in try/except. Chain works with partial data. |
| **Law of Demeter** | QUERY operations use public runtime service APIs (`ward_room.get_posts_by_author()`, `_introspective_telemetry.get_full_snapshot()`). Baseline reads public attributes (`is_cold_start`, `_source_attribution`). |
| **Backward Compatibility** | New QUERY keys are additive. New baseline keys are additive or override with richer data. Prompts degrade gracefully when keys are absent. |

---

## Tests

Create `tests/test_ad646b_chain_parity.py`.

### Test 1: `_query_self_monitoring` detects repetition in DM thread

```
Given: A runtime with ward_room service, observation with channel_name="dm-agent", thread_id="t1", callsign="LaForge"
And: ward_room.get_posts_by_author returns 3 posts with high similarity
When: _query_self_monitoring(runtime, spec, context) is called
Then: result["self_monitoring"] contains "self-similarity" warning
```

### Test 2: `_query_self_monitoring` returns empty for non-DM channels

```
Given: observation with channel_name="engineering"
When: _query_self_monitoring(runtime, spec, context) is called
Then: result["self_monitoring"] == ""
```

### Test 3: `_query_self_monitoring` returns empty when posts have low similarity

```
Given: DM channel, ward_room returns 3 distinct posts
When: _query_self_monitoring(runtime, spec, context) is called
Then: result["self_monitoring"] == ""
```

### Test 4: `_query_introspective_telemetry` fires for self-referential text

```
Given: A runtime with _introspective_telemetry service, observation with title containing "how is your memory"
When: _query_introspective_telemetry(runtime, spec, context) is called
Then: result["introspective_telemetry"] contains "Telemetry" text
```

### Test 5: `_query_introspective_telemetry` returns empty for non-introspective text

```
Given: observation with title="Weather report for today"
When: _query_introspective_telemetry(runtime, spec, context) is called
Then: result["introspective_telemetry"] == ""
```

### Test 6: `_query_introspective_telemetry` degrades when service unavailable

```
Given: runtime with no _introspective_telemetry attribute
When: _query_introspective_telemetry(runtime, spec, context) is called
Then: result["introspective_telemetry"] == ""
And: No exception raised
```

### Test 7: Baseline produces cold-start note when runtime.is_cold_start is True

```
Given: CognitiveAgent with runtime.is_cold_start = True
When: _build_cognitive_baseline(observation={}) is called
Then: state["_cold_start_note"] contains "fresh start"
```

### Test 8: Baseline produces NO cold-start note when is_cold_start is False

```
Given: CognitiveAgent with runtime.is_cold_start = False
When: _build_cognitive_baseline(observation={}) is called
Then: "_cold_start_note" NOT in state
```

### Test 9: Baseline produces rich source attribution from dataclass

```
Given: CognitiveAgent, observation with _source_attribution dataclass (episodic_count=3, oracle_used=True, primary_source=KnowledgeSource.EPISODIC)
When: _build_cognitive_baseline(observation) is called
Then: state["_source_attribution_text"] contains "<source_awareness>"
And: Contains "episodic memory (3 episodes)"
And: Contains "ship's records"
And: Contains "Primary basis: episodic"
```

### Test 10: Baseline rich attribution overrides simplified version

```
Given: CognitiveAgent, observation with recent_memories=[ep1] AND _source_attribution dataclass
When: _build_cognitive_baseline(observation) is called
Then: state["_source_attribution_text"] contains "<source_awareness>" (rich version, not simplified)
```

### Test 11: Baseline produces self-recognition cue

```
Given: CognitiveAgent with callsign="LaForge", observation with context containing "@LaForge"
When: _build_cognitive_baseline(observation) is called
Then: state["_self_recognition_cue"] is a non-empty string
```

### Test 12: Thread analysis prompt renders oracle context

```
Given: observation with _oracle_context="Ship's Records: power grid stable"
When: _build_thread_analysis_prompt(context, prior_results, callsign, department) is called
Then: user_prompt contains "Cross-Tier Knowledge"
And: Contains "power grid stable"
```

### Test 13: Thread analysis prompt renders self-monitoring from QUERY

```
Given: prior_results with QUERY result containing self_monitoring="WARNING: 80% self-similarity"
When: _build_thread_analysis_prompt(context, prior_results, callsign, department) is called
Then: user_prompt contains "Self-Monitoring"
And: Contains "80% self-similarity"
```

### Test 14: Thread analysis prompt renders telemetry from QUERY

```
Given: prior_results with QUERY result containing introspective_telemetry="--- Your Telemetry ---\nMemory: 42 episodes"
When: _build_thread_analysis_prompt(context, prior_results, callsign, department) is called
Then: user_prompt contains "Your Telemetry"
```

### Test 15: Compose user prompt renders oracle context

```
Given: context with _oracle_context="Duty logs from yesterday"
When: _build_user_prompt(context, prior_results) is called
Then: result contains "Cross-Tier Knowledge"
And: Contains "Duty logs from yesterday"
```

### Test 16: Prior Data excludes dedicated AD-646b keys

```
Given: prior_results with QUERY result {"thread_metadata": {...}, "self_monitoring": "warning", "introspective_telemetry": "telemetry text"}
When: _build_user_prompt(context, prior_results) is called
Then: "## Prior Data" section does NOT contain "self_monitoring" or "introspective_telemetry" as raw keys
And: self_monitoring rendered in dedicated "## Self-Monitoring" section
```

### Test 17: Ward room chain context_keys include new operations

```
Given: A CognitiveAgent
When: _build_chain_for_intent() constructs the ward_room chain
Then: QUERY step's context_keys contains "self_monitoring" and "introspective_telemetry"
```

### Test 18: Full chain regression — proactive path still works

```
Given: CognitiveAgent with full context_parts (proactive path)
When: _build_cognitive_state(full_context_parts, observation=obs) is called
Then: baseline keys present (including new cold_start_note, rich attribution, self_recognition_cue when applicable)
And: Extension keys override where appropriate
And: No regression in existing behavior
```

---

## Verification Checklist

After implementation:

- [ ] Ward Room chain ANALYZE receives: self-monitoring, telemetry, oracle context, self-recognition, cold-start
- [ ] Ward Room chain COMPOSE receives: same data via observation + prior_results
- [ ] DM threads get self-repetition detection in chain path (not just one-shot)
- [ ] Introspective queries get telemetry snapshot in chain path (not just one-shot)
- [ ] Cold-start note appears in chain baseline when `is_cold_start` is True
- [ ] Rich source attribution with oracle_used/primary_source replaces simplified count
- [ ] Self-recognition cue injected into chain prompts
- [ ] Oracle context rendered with proper framing (not personal memory)
- [ ] Prior Data dump excludes dedicated AD-646b keys (no double-rendering)
- [ ] Proactive chain still works identically — no regressions
- [ ] All 18 tests pass
- [ ] `pytest tests/test_ad646b_chain_parity.py -v` green
- [ ] `pytest tests/ -x -q` — no regressions
