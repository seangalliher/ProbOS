# Build Prompt: AD-552 — Notebook Self-Repetition Detection

**Ticket:** AD-552
**Priority:** Medium (noise reduction pipeline, step 3 of 7)
**Scope:** Cumulative notebook write tracking, Counselor intervention, write suppression circuit breaker
**Principles Compliance:** DRY, Fail Fast (log-and-degrade), Law of Demeter, Single Responsibility
**Dependencies:** AD-506b (Peer Repetition Detection — COMPLETE), AD-550 (Notebook Dedup — COMPLETE), AD-551 (Notebook Consolidation — COMPLETE)

---

## Context

AD-550 catches redundant notebook writes at the point of write (per-write dedup gate, 0.8 Jaccard threshold). AD-551 retrospectively consolidates similar notebooks during dreams. But neither detects the *cumulative pattern* of an agent writing about the same topic repeatedly with small incremental additions that individually pass the dedup gate. If an agent writes 5 entries on "hull-stress-analysis" in 24 hours, each 25% different from the last, all 5 pass the 0.8 threshold — but the *pattern* signals a cognitive loop.

AD-552 addresses this by tracking notebook write frequency per agent per topic, detecting repetitive patterns, and intervening via the Counselor. It extends AD-506b's peer repetition detection to cover self-authored notebook content.

**Motivating case:** Chapel's self-diagnosed analysis loop (`diagnostic-loop-pattern.md`). Cortez writing 86 files with ~12% signal. Both caught only by manual review — AD-552 would detect these patterns automatically.

---

## Architecture

### Where the Detection Lives

The detection piggybacks on the **AD-550 dedup gate** in `proactive.py` (lines 1294-1331). This is where all notebook writes flow through. After the per-write dedup check, AD-552 adds a cumulative frequency check using the entry's existing frontmatter metadata (`revision` count, `created` timestamp, `updated` timestamp) — data already maintained by AD-550's update-in-place mechanics.

### Tracking State

**No new tracking store needed.** AD-550 already maintains per-entry frontmatter with:
- `revision: int` — incremented on each update
- `created: str` — ISO timestamp of first write
- `updated: str` — ISO timestamp of last write

AD-552 uses these to compute write frequency: `revision / (now - created_time)`. If an entry has `revision >= 3` and `(now - created) < repetition_window_hours`, the agent is writing about this topic at a suspiciously high rate. The novelty of each write is already computed by the dedup gate's Jaccard similarity check.

### Tier Credit Model

AD-506b has two positive credit types: `self_correction` (agent self-corrects from amber zone) and `peer_catch` (peer repetition detected). AD-552 adds a **negative signal**: `notebook_repetition`. This is tracked as a counter on `CognitiveProfile` (`notebook_repetitions`), parallel to `peer_catches`. It does NOT use a credit-budget/consumption model — it follows the existing pattern where the counter is a diagnostic signal that the Counselor uses for assessment, not a finite resource.

---

## Deliverables

### Deliverable 1: Frequency Check in Dedup Gate

**File:** `src/probos/proactive.py`

Extend the AD-550 dedup gate (lines 1294-1331) to add a cumulative frequency check after `check_notebook_similarity()` returns. The similarity check already reads the existing entry's frontmatter — extend `check_notebook_similarity()` to return frequency metadata in its result dict.

**Changes to `src/probos/knowledge/records_store.py`:**

Extend the return dict from `check_notebook_similarity()` to include:
```python
{
    "action": "write" | "update" | "suppress",
    "reason": str,
    "existing_path": str | None,
    "existing_content": str | None,
    "similarity": float,
    # AD-552: Frequency metadata (new fields)
    "revision": int,           # Current revision count (0 if new)
    "created_iso": str | None, # ISO timestamp of first write (None if new)
    "updated_iso": str | None, # ISO timestamp of last write (None if new)
}
```

These fields are already parsed from frontmatter in the existing code — just pass them through in the return dict.

**Changes to `src/probos/proactive.py`:**

After the existing dedup gate logic, add a frequency check:

```
1. Extract frequency fields from dedup_result: revision, created_iso, updated_iso
2. Guard: if revision < repetition_threshold_count (config, default 3) → skip
3. Parse created_iso to timestamp, compute hours_active = (now - created_time) / 3600
4. If hours_active < repetition_window_hours (config, default 48):
   a. Compute novelty = 1.0 - dedup_result["similarity"]
   b. If novelty < novelty_threshold (config, default 0.2):
      → Self-repetition detected with LOW novelty
   c. Even if novelty >= novelty_threshold, the high revision rate is notable:
      if revision >= hard_suppression_count (config, default 5) AND novelty < 0.3:
      → High-frequency repetition approaching suppression
5. On detection:
   a. Emit NOTEBOOK_SELF_REPETITION event
   b. Log: "AD-552: Self-repetition detected for {callsign} on {topic_slug}
      (revision={revision}, hours_active={hours_active:.1f}, novelty={novelty:.2f})"
6. On suppression threshold (revision >= hard_suppression_count AND novelty < novelty_threshold):
   a. Override action to "suppress"
   b. Log: "AD-552: Suppressing write — {callsign} has written {topic_slug}
      {revision} times in {hours_active:.1f}h with <{novelty_threshold*100}% novel content"
```

**Important:** The suppression override only fires when BOTH conditions are met: high revision count AND low novelty. An agent writing frequently about a topic with genuinely new content each time should NOT be suppressed.

### Deliverable 2: NOTEBOOK_SELF_REPETITION Event

**File:** `src/probos/events.py`

Add new EventType:
```python
NOTEBOOK_SELF_REPETITION = "notebook_self_repetition"
```

Add typed event dataclass (follow `PeerRepetitionDetectedEvent` pattern):
```python
@dataclass
class NotebookSelfRepetitionEvent(BaseEvent):
    event_type: EventType = field(default=EventType.NOTEBOOK_SELF_REPETITION, init=False)
    agent_id: str = ""
    agent_callsign: str = ""
    topic_slug: str = ""
    revision: int = 0
    hours_active: float = 0.0
    novelty: float = 0.0
    suppressed: bool = False  # True if write was suppressed
```

### Deliverable 3: Counselor Subscription & Intervention

**File:** `src/probos/cognitive/counselor.py`

**3a. Event subscription** — Add `EventType.NOTEBOOK_SELF_REPETITION` to the subscription list at line 537 (after `PEER_REPETITION_DETECTED`).

**3b. Event router** — Add `elif` branch in `_on_event_async()` at line 726 (after peer repetition):
```python
elif event_type == EventType.NOTEBOOK_SELF_REPETITION.value:
    await self._on_notebook_self_repetition(data)
```

**3c. Handler** — New method `_on_notebook_self_repetition()`. Follow `_on_peer_repetition_detected()` pattern (lines 831-866):
```python
async def _on_notebook_self_repetition(self, data: dict[str, Any]) -> None:
    """AD-552: Track notebook self-repetition for Counselor monitoring."""
    agent_id = data.get("agent_id", "")
    callsign = data.get("agent_callsign", agent_id[:8])
    topic = data.get("topic_slug", "unknown")
    revision = data.get("revision", 0)
    suppressed = data.get("suppressed", False)

    if not agent_id or agent_id == self.id:
        return

    # Update profile
    profile = self.get_or_create_profile(agent_id)
    profile.notebook_repetitions += 1
    profile.last_notebook_repetition = time.time()

    # Lightweight assessment
    metrics = self._gather_agent_metrics(agent_id)
    assessment = self.assess_agent(
        agent_id=agent_id,
        current_trust=metrics["trust_score"],
        current_confidence=metrics["confidence"],
        hebbian_avg=metrics["hebbian_avg"],
        success_rate=metrics["success_rate"],
        personality_drift=metrics["personality_drift"],
        trigger="notebook_self_repetition",
    )
    assessment.tier_credit = "notebook_repetition"
    await self._save_profile_and_assessment(agent_id, assessment)

    # Therapeutic DM — only if not suppressed (suppression is its own feedback)
    if not suppressed:
        message = (
            f"@{callsign}, I've noticed you've documented **{topic}** "
            f"{revision} times recently. Your earlier entry already covers "
            f"the core observations. Consider updating it with genuinely "
            f"new findings rather than writing a fresh entry — your notebook "
            f"will be clearer and more useful for the crew."
        )
        await self._send_therapeutic_dm(agent_id, callsign, message)
```

**3d. CognitiveProfile extension** — Add to CognitiveProfile dataclass (after `last_peer_catch`, line 140):
```python
# AD-552: Notebook self-repetition tracking
notebook_repetitions: int = 0
last_notebook_repetition: float = 0.0
```

**3e. Schema migration** — Add to `CounselorProfileStore.start()` migration block (lines 273-278):
```python
"ALTER TABLE cognitive_profiles ADD COLUMN notebook_repetitions INTEGER DEFAULT 0",
"ALTER TABLE cognitive_profiles ADD COLUMN last_notebook_repetition REAL DEFAULT 0.0",
```

**3f. Profile persistence** — Update the `save_profile()` and `load_profiles()` methods to include the two new columns. Follow the existing pattern for `self_corrections` / `peer_catches`.

### Deliverable 4: Config Knobs

**File:** `src/probos/config.py`

Add to `RecordsConfig` (after the AD-550 settings, line 391):
```python
# AD-552: Notebook self-repetition detection
notebook_repetition_enabled: bool = True
notebook_repetition_window_hours: float = 48.0      # Time window for frequency check
notebook_repetition_threshold_count: int = 3         # Revisions within window to trigger alert
notebook_repetition_novelty_threshold: float = 0.2   # Below = low novelty (1.0 - similarity)
notebook_repetition_suppression_count: int = 5       # Revisions within window to suppress write
```

Update the dedup gate in `proactive.py` to read these from `self._runtime.config.records` (same pattern as the AD-550 config reads at lines 1295-1304).

### Deliverable 5: Self-Monitoring Prompt Enhancement

**File:** `src/probos/cognitive/cognitive_agent.py`

The self-monitoring context (lines 1972-1983) already shows agents their recent notebook topics. Enhance this to include a repetition warning when applicable.

In the notebook index injection block, after rendering the topic list, add:
```
If any topic in the notebook_index has revision >= repetition_threshold_count
AND was created within repetition_window_hours:
  Append: "⚠ You've written about {topic} {revision} times recently.
  Review your existing entry before writing again."
```

This requires the notebook index entries (built in `proactive.py` `_build_self_monitoring_context()` lines 959-1001) to include the `revision` count. The frontmatter is already parsed there — add `revision` to the enriched index entries.

---

## Files Modified (Expected)

| File | Change |
|------|--------|
| `src/probos/knowledge/records_store.py` | Extend `check_notebook_similarity()` return dict with frequency metadata |
| `src/probos/proactive.py` | Cumulative frequency check in dedup gate, emit event |
| `src/probos/events.py` | `NOTEBOOK_SELF_REPETITION` EventType + typed dataclass |
| `src/probos/cognitive/counselor.py` | Subscription, handler, CognitiveProfile fields, schema migration, save/load |
| `src/probos/cognitive/cognitive_agent.py` | Self-monitoring prompt repetition warning |
| `src/probos/config.py` | RecordsConfig self-repetition settings |
| `tests/test_ad552_notebook_self_repetition.py` | New test file |

---

## Prior Work to Absorb

| Source | What to Reuse | How |
|--------|---------------|-----|
| AD-506b `_on_peer_repetition_detected()` | Handler pattern: profile update → assessment with tier_credit → optional DM | Direct template for `_on_notebook_self_repetition()` |
| AD-506b `PeerRepetitionDetectedEvent` | Typed event dataclass structure | Direct template for `NotebookSelfRepetitionEvent` |
| AD-506b CognitiveProfile fields | `peer_catches` / `last_peer_catch` pattern | Add `notebook_repetitions` / `last_notebook_repetition` alongside |
| AD-506b schema migration | ALTER TABLE pattern with try/except pass | Add new columns in same block |
| AD-550 dedup gate (`proactive.py` 1294-1331) | Existing gate structure, config reads, similarity result handling | Extend — don't replace. Frequency check is additive |
| AD-550 `check_notebook_similarity()` | Already parses frontmatter (revision, created, updated) | Pass through in return dict — no new parsing needed |
| AD-550 frontmatter update-in-place | `revision` counter incremented on each update | This IS the frequency tracking — no separate store needed |
| AD-504 self-monitoring context | Notebook index built with frontmatter data | Add `revision` to enriched index, consume in prompt injection |
| `cognitive/similarity.py` | `jaccard_similarity()`, `text_to_words()` | Already used by dedup gate — novelty = `1.0 - similarity` |
| Counselor `_send_therapeutic_dm()` | Rate-limited DM with cooldown + Ward Room channel | Call directly from handler |
| Counselor `_build_therapeutic_message()` | Assessment-based message builder | Not needed — AD-552 uses a custom message (topic-specific) |

---

## Tests (25 minimum)

### TestFrequencyDetection (8 tests)
1. Entry with revision=3 within 48h AND novelty < 0.2 → NOTEBOOK_SELF_REPETITION event emitted
2. Entry with revision=2 within 48h → below threshold, no event
3. Entry with revision=3 but created > 48h ago → outside window, no event
4. Entry with revision=3 within 48h but novelty > 0.2 → event emitted (high frequency is notable even with moderate novelty)
5. Entry with revision=5 within 48h AND novelty < 0.2 → write suppressed
6. Entry with revision=5 within 48h but novelty > 0.3 → NOT suppressed (genuine new content)
7. New entry (revision=0) → no frequency check, passes through
8. Detection disabled via config `notebook_repetition_enabled=False` → no check

### TestEventEmission (3 tests)
9. NOTEBOOK_SELF_REPETITION event contains correct agent_id, callsign, topic_slug, revision, novelty
10. Event has `suppressed=True` when write is suppressed
11. Event has `suppressed=False` when write is allowed but pattern detected

### TestCounselorIntegration (7 tests)
12. Counselor subscribes to NOTEBOOK_SELF_REPETITION event
13. Handler increments `profile.notebook_repetitions` counter
14. Handler sets `profile.last_notebook_repetition` timestamp
15. Assessment created with `tier_credit="notebook_repetition"`
16. Therapeutic DM sent when `suppressed=False`
17. Therapeutic DM NOT sent when `suppressed=True` (suppression is its own feedback)
18. Counselor ignores events for its own agent_id

### TestCognitiveProfilePersistence (3 tests)
19. `notebook_repetitions` field persists through save/load cycle
20. `last_notebook_repetition` field persists through save/load cycle
21. Schema migration adds columns without error on fresh DB

### TestSelfMonitoringPrompt (2 tests)
22. Notebook index entries include `revision` count from frontmatter
23. Repetition warning injected in prompt when revision >= threshold within window

### TestConfigKnobs (2 tests)
24. RecordsConfig includes all AD-552 settings with correct defaults
25. Custom config values propagate to frequency check logic

---

## Validation Checklist

- [ ] Frequency check runs only when dedup gate is enabled AND repetition is enabled
- [ ] Entry with high revision + low novelty → detected, event emitted
- [ ] Entry with high revision + high novelty → NOT suppressed (new content respected)
- [ ] Entry with high revision + low novelty above suppression threshold → write suppressed
- [ ] New entries (no prior revision) pass through unaffected
- [ ] NOTEBOOK_SELF_REPETITION event emitted with all required fields
- [ ] Counselor subscribes and handles NOTEBOOK_SELF_REPETITION
- [ ] CognitiveProfile.notebook_repetitions counter incremented
- [ ] Schema migration adds columns without breaking existing data
- [ ] Therapeutic DM sent on detection, NOT sent on suppression
- [ ] Self-monitoring prompt shows revision warning when applicable
- [ ] Config knobs all have sensible defaults
- [ ] Log-and-degrade: frequency check failure doesn't block notebook write
- [ ] All existing AD-550/551 tests still pass (0 regressions)
- [ ] No new copies of jaccard_similarity — uses existing computation from dedup gate

---

## Notes

- **No new tracking store.** AD-552's key insight is that all frequency data already exists in the entry frontmatter thanks to AD-550's update-in-place mechanics. `revision` count + `created` timestamp = write frequency.
- **Novelty = 1.0 - similarity.** The dedup gate already computes Jaccard similarity between new content and existing content. AD-552 reinterprets this as a novelty score.
- **Suppression requires BOTH conditions:** high revision count AND low novelty. This is deliberate — an agent writing frequently about a genuinely evolving situation should not be suppressed. Only suppress when the content is repetitive AND frequent.
- **Therapeutic DM vs. suppression:** The DM fires on detection (warning), NOT on suppression (action already taken). An agent whose write was suppressed knows it — redundant DM would be noise.
- **Tier credit is informational, not consumable.** `notebook_repetition` is tracked as a diagnostic signal on CognitiveProfile, not as a finite budget that depletes. This matches the existing `peer_catches` pattern and avoids unnecessary complexity.
- **The `_build_therapeutic_message()` method is NOT used.** AD-552's DM has a custom message about the specific topic — it doesn't need the generic assessment-based builder. Use `_send_therapeutic_dm()` directly with a pre-built message string.
