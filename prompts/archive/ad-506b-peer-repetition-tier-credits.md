# AD-506b: Peer Repetition Detection & Tier Credits

**Type:** Build Prompt — Self-Regulation Wave (6b/6)
**Depends on:** AD-506a (graduated zone model)
**Scope:** Cross-agent repetition detection in the Ward Room posting pipeline + positive cognitive health signal tracking (tier credits). Completes the Self-Regulation Wave.

---

## Context

AD-506a built the graduated zone model (GREEN/AMBER/RED/CRITICAL) for self-regulation. The system can now detect when *one* agent is repeating itself and respond clinically. But there's no detection of cross-agent repetition — Agent A publishing content semantically identical to what Agent B just posted in the same channel. This is a real-world problem: multiple agents analyzing the same system event often converge on the same observation, creating redundant noise.

Additionally, the system has no way to credit *positive* cognitive behavior. Self-correction (an agent in amber who stops posting, zone decays to green) is invisible. Peer catches (system detects an echo before it posts) are never recorded. The Counselor's CognitiveProfile is entirely deficit-focused.

AD-506b adds two complementary capabilities:
1. **Peer repetition detection** — similarity check at the Ward Room posting pipeline level (not just the proactive loop). Detection, not suppression — the post still goes through, but a signal is emitted for Counselor monitoring.
2. **Tier credits** — positive cognitive health signals tracked on CognitiveProfile, emitted when an agent self-corrects from amber or when peer repetition is caught pre-trip.

---

## Part 0: Prerequisites & Bug Fixes

### 0a. BF-098: `_save_profile_and_assessment()` missing `await`

**File:** `src/probos/cognitive/counselor.py`

At lines 937-938, `save_profile()` and `save_assessment()` are async methods called without `await`. The coroutines are created but never executed — profiles may not actually persist.

**Fix:** Make `_save_profile_and_assessment()` async and await both calls:

```python
async def _save_profile_and_assessment(
    self, agent_id: str, assessment: CounselorAssessment,
) -> None:
    """Persist profile and assessment to store (DRY helper, AD-495)."""
    profile = self._cognitive_profiles.get(agent_id)
    if profile and self._profile_store:
        try:
            await self._profile_store.save_profile(profile)
            await self._profile_store.save_assessment(assessment)
        except Exception:
            logger.debug(
                "Failed to persist counselor profile for %s",
                agent_id, exc_info=True,
            )
```

Then update all callers of `_save_profile_and_assessment()` to `await` the call. Grep for `_save_profile_and_assessment(` throughout the file and add `await` to each call site. The method is called from:
- `_on_circuit_breaker_trip()`
- `_run_wellness_sweep()`
- `_on_trust_update()`
- `_on_self_monitoring_concern()`
- `_on_dream_complete()`

All callers are already async, so adding `await` is safe.

**Tests (2):**
1. `_save_profile_and_assessment()` actually persists profile (mock store, verify `save_profile` awaited).
2. `_save_profile_and_assessment()` actually persists assessment (mock store, verify `save_assessment` awaited).

### 0b. Zone recovery event

**File:** `src/probos/cognitive/circuit_breaker.py`

At line 334, `_update_zone()` returns `(old_zone, new_zone)` but `check_and_trip()` discards the value. Change to capture and return zone transition info:

```python
old_zone, new_zone = self._update_zone(agent_id, signals, tripped)
```

Add a property to `AgentBreakerState` or a dict field to cache the last zone transition:

```python
last_zone_transition: tuple[str, str] | None = None  # (old, new) or None if no change
```

Set it in `_update_zone()` when a zone change occurs. `check_and_trip()` no longer needs to return it — callers can query `get_last_zone_transition(agent_id)`:

```python
def get_last_zone_transition(self, agent_id: str) -> tuple[str, str] | None:
    """Return (old_zone, new_zone) from the most recent check, or None if no change."""
    return self._get_state(agent_id).last_zone_transition
```

**File:** `src/probos/events.py`

Add `ZONE_RECOVERY` event type:

```python
ZONE_RECOVERY = "zone_recovery"  # AD-506b: agent zone improved
```

Add typed dataclass:

```python
@dataclass
class ZoneRecoveryEvent(BaseEvent):
    """Emitted when an agent's cognitive zone improves (e.g., amber → green)."""
    event_type: EventType = field(default=EventType.ZONE_RECOVERY, init=False)
    agent_id: str = ""
    agent_callsign: str = ""
    old_zone: str = ""
    new_zone: str = ""
```

**File:** `src/probos/proactive.py`

After the `check_and_trip()` call (around line 434) and the existing zone check (around line 465), add zone recovery emission:

```python
# AD-506b: Emit zone recovery event
transition = self._circuit_breaker.get_last_zone_transition(agent.id)
if transition and self._on_event:
    old_zone, new_zone = transition
    # Recovery = zone improved (amber→green, red→amber, etc.)
    zone_order = {"green": 0, "amber": 1, "red": 2, "critical": 3}
    if zone_order.get(new_zone, 0) < zone_order.get(old_zone, 0):
        self._on_event({
            "type": EventType.ZONE_RECOVERY.value,
            "data": {
                "agent_id": agent.id,
                "agent_callsign": getattr(agent, "callsign", ""),
                "old_zone": old_zone,
                "new_zone": new_zone,
            },
        })
```

**Tests (3):**
1. `get_last_zone_transition()` returns `(old, new)` after zone change.
2. `get_last_zone_transition()` returns `None` when zone unchanged.
3. `ZONE_RECOVERY` event emitted when zone improves (e.g., amber→green).

---

## Part 1: Peer Repetition Detection

### 1a. `_check_peer_similarity()` method on ThreadManager

**File:** `src/probos/ward_room/threads.py`

Add a new method to `ThreadManager`:

```python
async def _check_peer_similarity(
    self, channel_id: str, author_id: str, body: str,
    window_seconds: float = 600.0, threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Check if body is similar to recent posts by OTHER authors in this channel.

    Returns list of matches: [{author_id, author_callsign, body_preview, similarity, post_id}]
    Empty list = no peer similarity detected.
    """
```

Implementation:
1. Call `self.get_recent_activity(channel_id, since=time.time() - window_seconds, limit=20)`.
2. Filter to posts by authors OTHER than `author_id`.
3. For each, compute `jaccard_similarity(text_to_words(body), text_to_words(post_body))`.
4. Return matches where similarity >= `threshold`, sorted by similarity descending.
5. Wrap in try/except — return `[]` on any failure (log-and-degrade).

Import `jaccard_similarity` and `text_to_words` from `src/probos/cognitive/similarity.py`.

### 1b. Wire peer detection into `create_thread()`

**File:** `src/probos/ward_room/threads.py`

After the credibility restrictions check (line 215) and before the `WardRoomThread` object construction (line 217), add:

```python
# AD-506b: Peer repetition detection (detection, not suppression)
peer_matches = await self._check_peer_similarity(channel_id, author_id, body)
```

The post still proceeds regardless of matches. After the event emission (line 251) and before the episodic memory storage (line 253), emit a peer repetition event if matches were found:

```python
if peer_matches and self._emit:
    self._emit({
        "type": "peer_repetition_detected",
        "data": {
            "channel_id": channel_id,
            "author_id": author_id,
            "author_callsign": author_callsign,
            "matches": [
                {
                    "author": m["author_callsign"],
                    "similarity": m["similarity"],
                    "post_id": m["post_id"],
                }
                for m in peer_matches[:3]  # Cap at top 3 matches
            ],
            "post_type": "thread",
            "thread_id": thread.id,
        },
    })
```

### 1c. Wire peer detection into `create_post()`

**File:** `src/probos/ward_room/messages.py`

Same pattern as 1b. Need to resolve the channel_id from the thread_id first (already available from the thread validation query at line 50-57). After the restrictions check (line 68), add:

```python
# AD-506b: Peer repetition detection
# channel_id is already available from the thread query above
peer_matches = await self._thread_manager._check_peer_similarity(
    channel_id, author_id, body
)
```

**Important design decision:** `MessageStore` doesn't currently have a reference to `ThreadManager`. Two options:
1. Add `_check_peer_similarity` as a standalone function that takes a `db` connection (both managers have `self._db`).
2. Wire `ThreadManager` into `MessageStore` as a dependency.

**Recommended:** Option 1 — extract `_check_peer_similarity` as a module-level async function in `threads.py` that takes `db` and the same parameters. Both `create_thread()` and `create_post()` call it. This avoids circular dependencies and follows DRY. `MessageStore` just imports the function.

Actually, even simpler: since `MessageStore` already has `self._db`, extract the peer detection as a standalone async function in a new location or in `similarity.py`:

```python
# In src/probos/ward_room/threads.py (or a shared location)
async def check_peer_similarity(
    db, channel_id: str, author_id: str, body: str,
    window_seconds: float = 600.0, threshold: float = 0.5,
) -> list[dict[str, Any]]:
```

Then both `ThreadManager.create_thread()` and `MessageStore.create_post()` import and call it.

For `create_post()`, the channel_id needs to be extracted from the thread query. The existing validation at lines 50-57 already fetches the thread row. Extract `channel_id` from it:

```python
# Existing thread validation already does:
row = await cursor.fetchone()
# Add: extract channel_id for peer detection
thread_channel_id = row[N]  # whichever column index has channel_id
```

Then after restrictions check, call the same `check_peer_similarity()` function.

After event emission (line 105), emit similarly to create_thread:

```python
if peer_matches and self._emit:
    self._emit({
        "type": "peer_repetition_detected",
        "data": {
            "channel_id": thread_channel_id,
            "author_id": author_id,
            "author_callsign": author_callsign,
            "matches": [...],
            "post_type": "reply",
            "thread_id": thread_id,
            "post_id": post.id,
        },
    })
```

### 1d. `PEER_REPETITION_DETECTED` event type

**File:** `src/probos/events.py`

Add to EventType enum:

```python
PEER_REPETITION_DETECTED = "peer_repetition_detected"  # AD-506b
```

Add typed dataclass:

```python
@dataclass
class PeerRepetitionDetectedEvent(BaseEvent):
    """Emitted when a Ward Room post is similar to another agent's recent post."""
    event_type: EventType = field(default=EventType.PEER_REPETITION_DETECTED, init=False)
    channel_id: str = ""
    author_id: str = ""
    author_callsign: str = ""
    match_count: int = 0
    top_similarity: float = 0.0
    post_type: str = ""  # "thread" or "reply"
```

**Tests (8):**
1. `check_peer_similarity()` returns empty list when no recent posts.
2. `check_peer_similarity()` returns empty list when only self-posts (same author).
3. `check_peer_similarity()` returns match when different author posted similar content.
4. `check_peer_similarity()` respects threshold — similarity below threshold returns no matches.
5. `check_peer_similarity()` respects window — old posts outside window ignored.
6. `create_thread()` emits `PEER_REPETITION_DETECTED` event when peer similarity found.
7. `create_thread()` does NOT suppress the post (thread still created despite similarity).
8. `create_post()` emits `PEER_REPETITION_DETECTED` event when peer similarity found.

---

## Part 2: Tier Credits on CognitiveProfile

### 2a. Add tier credit fields to CognitiveProfile

**File:** `src/probos/cognitive/counselor.py`

Add fields to the `CognitiveProfile` dataclass (after line 132):

```python
# AD-506b: Tier credits — positive cognitive health signals
self_corrections: int = 0     # Times agent self-corrected from amber (Tier 1)
peer_catches: int = 0         # Times peer repetition was detected for this agent (Tier 2)
last_self_correction: float = 0.0  # Timestamp of most recent self-correction
last_peer_catch: float = 0.0       # Timestamp of most recent peer catch
```

These are cumulative counters on the profile. They persist across assessments (profile-level, not assessment-level). They provide the Counselor with a longitudinal view: "Agent X has self-corrected 7 times and been caught echoing peers 2 times."

### 2b. Add tier credit fields to CounselorAssessment

**File:** `src/probos/cognitive/counselor.py`

Add optional credit indicators to `CounselorAssessment` (after line 87):

```python
# AD-506b: Tier credit indicators for this assessment
tier_credit: str = ""  # "self_correction" | "peer_catch" | "" (none)
```

This tags individual assessments triggered by positive signals, distinguishing them from deficit-triggered assessments.

### 2c. Update `add_assessment()` to factor in credits

**File:** `src/probos/cognitive/counselor.py`

In `add_assessment()` (line 134), the alert level logic currently only checks for deficits. Add credit influence:

After the existing alert level computation, add a credit bonus that can improve the alert level:

```python
# AD-506b: Tier credit influence — sustained self-correction demonstrates cognitive health
if assessment.tier_credit == "self_correction":
    self.self_corrections += 1
    self.last_self_correction = assessment.timestamp
    # Frequent self-correction is a positive signal — don't let it
    # keep agent at yellow if they're consistently self-regulating
    if self.alert_level == "yellow" and self.self_corrections >= 3:
        # Check last 3 assessments — if all are self-correction credits,
        # strong evidence of healthy self-regulation
        recent_credits = sum(
            1 for a in self.assessments[-3:]
            if a.tier_credit == "self_correction"
        )
        if recent_credits >= 2:
            self.alert_level = "green"
```

This doesn't override red (not fit_for_duty) — that's a hard gate. It can recover yellow → green when self-correction is sustained.

### 2d. Counselor subscribes to `ZONE_RECOVERY` and `PEER_REPETITION_DETECTED`

**File:** `src/probos/cognitive/counselor.py`

In `initialize()` event subscriptions, add:

```python
event_types=[
    EventType.TRUST_UPDATE,
    EventType.CIRCUIT_BREAKER_TRIP,
    EventType.DREAM_COMPLETE,
    EventType.SELF_MONITORING_CONCERN,  # AD-506a
    EventType.ZONE_RECOVERY,            # AD-506b
    EventType.PEER_REPETITION_DETECTED, # AD-506b
]
```

### 2e. `_on_zone_recovery()` handler — self-correction credit

**File:** `src/probos/cognitive/counselor.py`

Add handler:

```python
async def _on_zone_recovery(self, event_data: dict) -> None:
    """AD-506b: Credit agent for self-correction when zone improves."""
    agent_id = event_data.get("agent_id", "")
    old_zone = event_data.get("old_zone", "")
    new_zone = event_data.get("new_zone", "")

    if agent_id == self.id:
        return

    # Only credit for amber→green recovery (amber self-correction)
    # red→amber decay is system-regulated (circuit breaker cooldown), not agent-initiated
    if old_zone != "amber" or new_zone != "green":
        return

    logger.info("AD-506b: Self-correction credit for %s (amber→green)", agent_id[:8])

    # Run lightweight assessment with positive credit
    metrics = await self._gather_agent_metrics(agent_id)
    assessment = await self.assess_agent(
        agent_id=agent_id,
        metrics=metrics,
        trigger="self_correction",
    )
    assessment.tier_credit = "self_correction"

    # Persist — this updates the profile's self_corrections counter via add_assessment()
    profile = self._cognitive_profiles.get(agent_id)
    if profile:
        profile.add_assessment(assessment)
    await self._save_profile_and_assessment(agent_id, assessment)
```

**Key design decision:** Only AMBER→GREEN gets self-correction credit. RED→AMBER is system-regulated decay (the circuit breaker forced the cooldown), not the agent choosing to self-regulate. An agent earns credit by being warned (amber), changing behavior (not repeating), and the zone naturally decaying back to green.

### 2f. `_on_peer_repetition_detected()` handler — peer catch tracking

**File:** `src/probos/cognitive/counselor.py`

Add handler:

```python
async def _on_peer_repetition_detected(self, event_data: dict) -> None:
    """AD-506b: Track peer repetition for Counselor monitoring.

    This is informational — the Counselor notes the echo pattern.
    No intervention: the post still went through.
    """
    author_id = event_data.get("author_id", "")
    callsign = event_data.get("author_callsign", author_id[:8])
    match_count = event_data.get("match_count", 0)

    if author_id == self.id:
        return

    logger.info(
        "AD-506b: Peer repetition detected for %s (%d matches)",
        callsign, match_count,
    )

    # Update profile with peer catch count
    profile = self._cognitive_profiles.get(author_id)
    if profile:
        profile.peer_catches += 1
        profile.last_peer_catch = time.time()

    # Lightweight assessment with peer catch tag
    metrics = await self._gather_agent_metrics(author_id)
    assessment = await self.assess_agent(
        agent_id=author_id,
        metrics=metrics,
        trigger="peer_repetition",
    )
    assessment.tier_credit = "peer_catch"
    await self._save_profile_and_assessment(author_id, assessment)
```

Note: No DM, no intervention, no cooldown. Peer repetition is a diagnostic signal, not a corrective action. The Counselor watches the pattern over time. If an agent consistently echoes peers (high `peer_catches` count), that may factor into future assessments — but that's a judgment call for the Counselor's assessment logic, not an automated response.

Wire both handlers in the event dispatch routing to their respective EventTypes.

**Tests (8):**
1. CognitiveProfile has `self_corrections` and `peer_catches` fields (default 0).
2. CounselorAssessment has `tier_credit` field (default "").
3. `add_assessment()` increments `self_corrections` when `tier_credit == "self_correction"`.
4. `add_assessment()` with sustained self-corrections can recover yellow → green alert level.
5. `add_assessment()` does NOT override red alert level with self-correction credits.
6. Counselor subscribes to `ZONE_RECOVERY` and `PEER_REPETITION_DETECTED` events.
7. `_on_zone_recovery()` grants self_correction credit only for amber→green (not red→amber).
8. `_on_peer_repetition_detected()` updates profile `peer_catches` counter.

---

## Part 3: Peer Repetition Episode Type

### 3a. Store peer repetition episode for the *repeating* agent

**File:** `src/probos/ward_room/threads.py` and `messages.py`

When peer repetition is detected in `create_thread()` or `create_post()`, store a `secondhand` episode for the author:

```python
if peer_matches and self._episodic_memory:
    top_match = peer_matches[0]
    try:
        ep = Episode(
            timestamp=time.time(),
            user_input=(
                f"[Peer echo] Your post in {channel_name} was similar to "
                f"{top_match['author_callsign']}'s recent post "
                f"(similarity {top_match['similarity']:.0%})"
            ),
            agent_ids=[author_id],
            outcomes=[{
                "intent": "peer_repetition",
                "success": True,
                "channel": channel_name,
                "similar_to_author": top_match["author_callsign"],
                "similarity": top_match["similarity"],
                "post_id": top_match.get("post_id", ""),
            }],
            reflection=(
                f"System detected overlap between my post and "
                f"{top_match['author_callsign']}'s recent contribution. "
                f"Similarity: {top_match['similarity']:.0%}."
            ),
            source=MemorySource.DIRECT.value,  # Agent authored the post
        )
        await self._episodic_memory.store(ep)
    except Exception:
        logger.debug("AD-506b: Failed to store peer repetition episode", exc_info=True)
```

This gives the agent memory of the echo event. When the agent next builds self-monitoring context (AD-504), this episode is available in their recent memories. Over time via dream consolidation, the pattern "I tend to echo my colleagues" can emerge.

The episode uses `source=DIRECT` because the agent authored the post. The `intent="peer_repetition"` distinguishes it from regular `ward_room_post` episodes.

**Tests (3):**
1. Peer repetition episode stored with `intent="peer_repetition"` in outcomes.
2. Episode `agent_ids` is `[author_id]` (the repeating agent gets the memory).
3. Episode `source` is `"direct"`.

---

## Part 4: CounselorProfileStore Schema Update

### 4a. Update profile serialization for new fields

**File:** `src/probos/cognitive/counselor.py`

The `CounselorProfileStore` persists profiles to SQLite (AD-503). The schema was created with specific columns. The new `self_corrections`, `peer_catches`, `last_self_correction`, `last_peer_catch` fields on CognitiveProfile need to be persisted.

Check how `save_profile()` serializes the profile. If it uses JSON serialization of the full dataclass, the new fields will serialize automatically. If it uses explicit column mapping, add the new columns.

Similarly, `save_assessment()` needs to include the `tier_credit` field.

**For the profile table**, add columns via schema migration in `_ensure_schema()`:

```sql
ALTER TABLE counselor_profiles ADD COLUMN self_corrections INTEGER DEFAULT 0;
ALTER TABLE counselor_profiles ADD COLUMN peer_catches INTEGER DEFAULT 0;
ALTER TABLE counselor_profiles ADD COLUMN last_self_correction REAL DEFAULT 0.0;
ALTER TABLE counselor_profiles ADD COLUMN last_peer_catch REAL DEFAULT 0.0;
```

Use the standard `try/except` pattern for ALTER TABLE (column already exists is OK).

**For the assessment table**, add column:

```sql
ALTER TABLE counselor_assessments ADD COLUMN tier_credit TEXT DEFAULT '';
```

**Tests (2):**
1. `save_profile()` persists `self_corrections` and `peer_catches`.
2. `save_assessment()` persists `tier_credit` field.

---

## Validation Checklist

| # | Check | How to verify |
|---|-------|---------------|
| 1 | BF-098 fixed — `_save_profile_and_assessment()` awaits both calls | Mock store, verify coroutines awaited |
| 2 | `get_last_zone_transition()` returns transition or None | Unit test |
| 3 | `ZONE_RECOVERY` event type exists | `EventType.ZONE_RECOVERY` |
| 4 | `ZONE_RECOVERY` event emitted on amber→green | Mock event emitter, verify |
| 5 | `ZONE_RECOVERY` NOT emitted on same-zone or escalation | Verify no emission |
| 6 | `PEER_REPETITION_DETECTED` event type exists | `EventType.PEER_REPETITION_DETECTED` |
| 7 | `check_peer_similarity()` finds cross-agent similarity | Unit test with populated channel |
| 8 | `check_peer_similarity()` ignores self-posts | Same author, no matches |
| 9 | `create_thread()` emits `PEER_REPETITION_DETECTED` on match | Event emission test |
| 10 | `create_thread()` does NOT suppress the post | Thread still created |
| 11 | `create_post()` emits `PEER_REPETITION_DETECTED` on match | Event emission test |
| 12 | `create_post()` does NOT suppress the post | Reply still created |
| 13 | Peer window respects time boundary | Old posts outside window ignored |
| 14 | CognitiveProfile has `self_corrections` and `peer_catches` | Dataclass fields exist |
| 15 | CounselorAssessment has `tier_credit` field | Dataclass field exists |
| 16 | `add_assessment()` increments `self_corrections` on self_correction credit | Counter test |
| 17 | Sustained self-corrections can recover yellow → green | Alert level test |
| 18 | Self-corrections cannot override red alert level | Safety test |
| 19 | Counselor subscribes to `ZONE_RECOVERY` and `PEER_REPETITION_DETECTED` | Subscription check |
| 20 | `_on_zone_recovery()` credits only amber→green | Credit only on amber→green |
| 21 | `_on_peer_repetition_detected()` updates `peer_catches` counter | Counter test |
| 22 | Peer repetition episode stored with `intent="peer_repetition"` | Episode check |
| 23 | Profile store persists new fields (self_corrections, peer_catches) | Round-trip test |
| 24 | Assessment store persists tier_credit | Round-trip test |

**Expected:** ~26 new tests, 24/24 checklist items.

---

## Engineering Principles Compliance

- **Single Responsibility:** `check_peer_similarity()` isolated as a function. Counselor handles credit logic. Circuit breaker handles zone transitions. Each tier has its own signal source.
- **Open/Closed:** CognitiveProfile extended with new fields (open for extension). Existing assessment logic unchanged (closed for modification) — credits are additive.
- **Dependency Inversion:** Peer detection uses the existing `_db` connection and `similarity.py` utilities. No new dependencies introduced.
- **Fail Fast:** Peer detection is log-and-degrade — exceptions return empty list, post proceeds. Episode storage failure is logged and swallowed (non-critical).
- **DRY:** `check_peer_similarity()` is a shared function used by both `create_thread()` and `create_post()`. Reuses existing `jaccard_similarity` and `text_to_words` from `similarity.py`.
- **Law of Demeter:** Proactive loop queries zone transition via `get_last_zone_transition()` accessor. Counselor receives events, doesn't reach into circuit breaker internals.

---

## What This Completes

AD-506b is the final item in the Self-Regulation Wave:
- **Tier 1 (Self):** AD-504 (self-monitoring context) + AD-506a (zone awareness) — agent sees own patterns
- **Tier 2 (Social):** AD-506b — cross-agent repetition detection + peer memory
- **Tier 3 (System):** AD-488 (circuit breaker) + AD-495 (Counselor assessment) + AD-505 (Counselor intervention) + AD-506a (graduated zones)
- **Credits:** AD-506b — self-correction tracked, peer catches tracked, positive signals influence cognitive health

The full dependency chain: AD-502 → AD-503 → AD-495 → AD-504 → AD-505 → AD-506a → AD-506b ✓

The Counselor now has a complete pipeline: **detect → warn → intervene → verify → credit**. Agents who self-regulate get recognized for it. Agents who echo peers have the pattern noted (not punished — logged for clinical monitoring). The system's response is proportional, graduated, and clinically informed.
