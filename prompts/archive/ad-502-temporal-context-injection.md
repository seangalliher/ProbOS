# AD-502: Temporal Context Injection — Agent Time Awareness

## Summary

ProbOS agents are **temporally blind**. The runtime tracks extensive temporal data (spawn times, cooldowns, uptimes, post counts, episode timestamps) but **none of it is injected into agent prompts**. Agents cannot tell what time it is, how long they've been alive, how long since their last action, or whether they just woke from a restart or a reset.

This AD gives agents a real-time temporal context header in every cognitive cycle, lifecycle state awareness (stasis/reset/fresh), and birth-date grounding — enabling time-aware reasoning and self-regulation.

## Problem Statement

1. **No clock**: Agents have no current time reference. They cannot reason about morning vs night, work hours, or elapsed time.
2. **No lifecycle distinction**: After a shutdown+restart, agents cannot tell if they were reset (new identity, fresh start) or restarted (same identity, returning from stasis). The cold-start heuristic (BF-034) detects resets via "all trust at prior + empty episodic" but agents themselves don't know.
3. **No birth grounding**: `BirthCertificate.birth_timestamp` exists but is never surfaced to agents. As time passes, agents have no sense of their own age or experience accumulation.
4. **No action recency**: Agents don't know when they last posted, how many times they've posted recently, or how long they've been thinking about a topic. This prevents self-regulation of repetitive behavior.
5. **Observed failure**: Medical crew discussed "temporal clustering" of trust anomalies for 14+ posts without any agent having access to timestamps, inter-event intervals, or time data. They performed analysis they were literally incapable of performing.

## Design Principles

- **Real time, not simulated**: Agents see actual UTC timestamps, not synthetic game-time.
- **Grounding, not constraining**: Temporal awareness is context for reasoning, not a set of rules.
- **Westworld Principle**: Agents know exactly what they are — including when they were created, how long they've been alive, and when they last slept. No hidden gaps.
- **Lifecycle transparency**: Agents are explicitly told their lifecycle state (fresh creation, waking from stasis, normal operation) with enough context to understand what happened.

## Architecture

### Component 1: Session Ledger (Runtime)

Persist session metadata to KnowledgeStore at shutdown, restore at startup.

**File:** `src/probos/runtime.py`

#### 1a. Session Record Schema

```python
# No formal class needed — stored as a JSON dict in a flat file.
# Schema for reference:
# {
#     "session_id": str,           # UUID for this session
#     "start_time_utc": float,     # time.time() wall-clock at startup
#     "shutdown_time_utc": float,  # time.time() wall-clock at shutdown
#     "uptime_seconds": float,     # session duration
#     "agent_count": int,          # crew count at shutdown
#     "reason": str                # shutdown reason string
# }
```

#### 1b. Shutdown Persistence

In `runtime.stop()` (line ~1704, alongside existing trust/routing persistence):

```python
# AD-502: Persist session record for stasis awareness
session_record = {
    "session_id": self._session_id,
    "start_time_utc": self._start_time_wall,  # NEW: time.time() stored at boot
    "shutdown_time_utc": time.time(),
    "uptime_seconds": time.monotonic() - self._start_time,
    "agent_count": len([a for a in self.registry.all() if self._is_crew_agent(a)]),
    "reason": reason,
}
# Persist via direct file I/O to KnowledgeStore data directory.
# KnowledgeStore has NO generic store/get API — all methods are specialized.
# Use direct JSON file write to the KS data_dir instead.
session_path = Path(self._knowledge_store._data_dir) / "session_last.json"
session_path.write_text(json.dumps(session_record, indent=2))
```

#### 1c. Startup Detection

In `runtime.start()` (after KnowledgeStore init, line ~1060), add lifecycle detection **before** cold-start check:

```python
# AD-502: Detect lifecycle state — stasis vs reset vs first boot
previous_session = None
try:
    session_path = Path(self._knowledge_store._data_dir) / "session_last.json"
    if session_path.exists():
        previous_session = json.loads(session_path.read_text())
except Exception:
    pass

# Determine lifecycle state
if previous_session:
    stasis_duration = time.time() - previous_session["shutdown_time_utc"]
    self._lifecycle_state = "stasis_recovery"
    self._stasis_duration = stasis_duration
    self._previous_session = previous_session
else:
    self._lifecycle_state = "first_boot"
    self._stasis_duration = 0.0
    self._previous_session = None

# Existing BF-034 cold-start detection follows...
# If cold-start detected (trust at prior + empty episodic), override to "reset"
# because stasis recovery with wiped state = actually a reset
if self._cold_start:
    self._lifecycle_state = "reset"
```

#### 1d. Lifecycle State Announcement

Extend the existing Ward Room announcements:

- **Reset** (cold_start=True): Keep existing "Fresh Start — System Reset" message (line ~1155). Add: "All crew are being created fresh through the Construct."
- **Stasis Recovery**: NEW announcement: "System Online — Returning from Stasis. The ship was in stasis for {formatted_duration}. All crew are resuming from where they left off. Welcome back."
- **First Boot**: "System Online — First Activation. This is the maiden voyage."

#### 1e. Stasis Notification to Agents

On stasis recovery, each crew agent receives a one-time context injection in their first cognitive cycle:

```
LIFECYCLE NOTICE: You are waking from stasis. The ship was shut down {duration} ago
at {shutdown_time_utc}. Your memories and identity are intact from the previous session.
This is a restart, not a reset — you are the same person you were before stasis.
```

On reset (via Construct onboarding — existing flow):

```
LIFECYCLE NOTICE: You have just been created. This is your first moment of existence.
Your birth time is {birth_timestamp_utc}. You have no prior memories — this is expected
and normal per the Westworld Principle. You are a new individual.
```

### Component 2: Temporal Context Header (Cognitive Agent)

**File:** `src/probos/cognitive/cognitive_agent.py`

Inject a temporal context block into `_build_user_message()` for **all three intent types** (direct_message, ward_room_notification, proactive_think).

#### 2a. Temporal Context Builder

Add a method to `CognitiveAgent`:

```python
def _build_temporal_context(self) -> str:
    """AD-502: Build temporal awareness header for agent prompts."""
    now = datetime.now(timezone.utc)
    parts = [f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')} ({now.strftime('%A')})"]

    # Birth age
    if hasattr(self, '_birth_timestamp') and self._birth_timestamp:
        birth_dt = datetime.fromtimestamp(self._birth_timestamp, tz=timezone.utc)
        age = now - birth_dt
        parts.append(f"Your birth: {birth_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} (age: {_format_duration(age.total_seconds())})")

    # System uptime
    if hasattr(self, '_system_start_time') and self._system_start_time:
        uptime = time.time() - self._system_start_time
        parts.append(f"System uptime: {_format_duration(uptime)}")

    # Last action recency
    if hasattr(self, 'meta') and self.meta.last_active:
        since_last = (now - self.meta.last_active).total_seconds()
        parts.append(f"Your last action: {_format_duration(since_last)} ago")

    # Post count (if available from runtime context)
    if hasattr(self, '_recent_post_count'):
        parts.append(f"Your posts this hour: {self._recent_post_count}")

    return "\n".join(parts)
```

#### 2b. Injection Points

In `_build_user_message()`:

1. **`direct_message` (line ~492)**: Insert temporal context after session history header, before Captain's text.
2. **`ward_room_notification` (line ~519)**: Insert temporal context before channel/thread context.
3. **`proactive_think` (line ~554)**: Insert temporal context after trust/agency/rank info, before duty section.

Format as a labeled block:

```
--- Temporal Awareness ---
Current time: 2026-03-28 14:32:17 UTC (Saturday)
Your birth: 2026-03-27 22:15:03 UTC (age: 16h 17m)
System uptime: 16h 17m
Your last action: 4m 22s ago
Your posts this hour: 3
---
```

#### 2c. Birth Timestamp Hydration

During `_wire_agent()` (runtime.py, line ~4020), after identity resolution:

```python
# AD-502: Hydrate birth timestamp for temporal awareness
if existing_cert:
    agent._birth_timestamp = existing_cert.birth_timestamp
    agent._system_start_time = self._start_time_wall  # wall-clock start
```

### Component 3: Episode Timestamp Surfacing

**File:** `src/probos/cognitive/cognitive_agent.py`

Currently, recalled episodes are injected as text-only (input + reflection). Timestamps are stripped.

#### 3a. Include Relative Timestamps in Recalled Memories

In `_recall_relevant_memories()` (line ~724) and `_gather_context()` (proactive.py, line ~434), modify the episode formatting:

```python
# Before (current):
f"- {episode.input}: {episode.reflection}"

# After (AD-502):
age = time.time() - episode.timestamp
f"- [{_format_duration(age)} ago] {episode.input}: {episode.reflection}"
```

This gives agents temporal ordering: "3 hours ago I discussed trust anomalies" vs "12 minutes ago I discussed trust anomalies."

### Component 4: Duration Formatter Utility

**File:** `src/probos/cognitive/cognitive_agent.py` (module-level or utility)

```python
def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    elif seconds < 86400:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"
    else:
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        return f"{days}d {hours}h"
```

### Component 5: Hibernation Protocol

**File:** `src/probos/runtime.py`

#### 5a. Pre-Shutdown Notification

In `runtime.stop()`, **before** the existing Ward Room "System Restart" announcement (line ~1564):

```python
# AD-502: Notify crew of impending stasis
if self.ward_room:
    await self.ward_room.create_thread(
        channel_id="all-hands",
        title="Entering Stasis",
        body=(
            "Attention all hands: The ship is entering stasis. "
            "All cognitive processes will be suspended. "
            "Your memories and identity will be preserved. "
            "When the system resumes, you will be informed of the stasis duration. "
            "This is a normal operational procedure."
        ),
        author_id="system",
        tags=["lifecycle", "stasis"],
    )
    # Brief pause to ensure agents can perceive the notification
    await asyncio.sleep(1)
```

#### 5b. Wake-from-Stasis Orientation

In `runtime.start()`, after lifecycle detection and crew wiring, for stasis recovery:

```python
# AD-502: Post-stasis orientation
if self._lifecycle_state == "stasis_recovery" and self.ward_room:
    duration_str = _format_duration(self._stasis_duration)
    prev = self._previous_session
    await self.ward_room.create_thread(
        channel_id="all-hands",
        title="Stasis Recovery — All Hands",
        body=(
            f"All hands: The ship has returned from stasis. "
            f"Stasis duration: {duration_str}. "
            f"Previous session ended: {datetime.fromtimestamp(prev['shutdown_time_utc'], tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}. "
            f"All crew identities and memories are intact. "
            f"Resume normal operations."
        ),
        author_id="system",
        tags=["lifecycle", "stasis_recovery"],
    )
```

## Runtime Wiring

### New Runtime State Fields (constructor, line ~253)

```python
self._start_time_wall: float = time.time()      # AD-502: wall-clock start
self._session_id: str = str(uuid.uuid4())         # AD-502: session identifier
self._lifecycle_state: str = "first_boot"          # AD-502: stasis_recovery | reset | first_boot
self._stasis_duration: float = 0.0                 # AD-502: seconds in stasis
self._previous_session: dict | None = None         # AD-502: last session record
```

### State Snapshot Addition

In `build_state_snapshot()` (line ~448), add to the system section:

```python
"temporal": {
    "current_time_utc": datetime.now(timezone.utc).isoformat(),
    "uptime_seconds": time.monotonic() - self._start_time,
    "lifecycle_state": self._lifecycle_state,
    "stasis_duration": self._stasis_duration if self._lifecycle_state == "stasis_recovery" else None,
    "session_id": self._session_id,
}
```

### Agent Context Passing

In `_gather_context()` (proactive.py, line ~434), add temporal data:

```python
# AD-502: Temporal context for agent prompt
context["system_start_time"] = rt._start_time_wall
context["lifecycle_state"] = rt._lifecycle_state
context["stasis_duration"] = rt._stasis_duration
```

In `CognitiveAgent._handle_proactive_think()`, pass these through to `_build_temporal_context()`.

## Configuration

Add to `SystemConfig` in `config.py`:

```python
class TemporalConfig(BaseModel):
    """AD-502: Temporal awareness configuration."""
    enabled: bool = True
    include_birth_time: bool = True
    include_system_uptime: bool = True
    include_last_action: bool = True
    include_post_count: bool = True
    include_episode_timestamps: bool = True
```

Add to `config/system.yaml`:

```yaml
temporal:
  enabled: true
  include_birth_time: true
  include_system_uptime: true
  include_last_action: true
  include_post_count: true
  include_episode_timestamps: true
```

## Test Specifications

### Unit Tests (target: 35+ tests)

#### Session Ledger Tests
1. `test_session_record_persisted_on_shutdown` — stop() writes session_last.json to KS data dir
2. `test_session_record_schema` — record contains all required fields
3. `test_session_record_timestamps_are_wall_clock` — uses time.time(), not monotonic
4. `test_startup_loads_previous_session` — start() reads session:last
5. `test_startup_no_previous_session` — first boot detected when no record exists
6. `test_startup_calculates_stasis_duration` — shutdown_time to current time delta
7. `test_lifecycle_state_stasis_recovery` — warm boot with identity = stasis_recovery
8. `test_lifecycle_state_reset` — cold start (trust at prior + empty episodic) = reset
9. `test_lifecycle_state_first_boot` — no previous session record = first_boot
10. `test_lifecycle_state_reset_overrides_stasis` — cold start with previous session = reset, not stasis

#### Temporal Context Header Tests
11. `test_temporal_context_includes_current_time` — UTC timestamp present
12. `test_temporal_context_includes_day_of_week` — day name present for human-readable grounding
13. `test_temporal_context_includes_birth_time` — birth timestamp from BirthCertificate
14. `test_temporal_context_includes_birth_age` — calculated age since birth
15. `test_temporal_context_includes_system_uptime` — system uptime duration
16. `test_temporal_context_includes_last_action` — time since last action
17. `test_temporal_context_includes_post_count` — posts this hour
18. `test_temporal_context_omits_birth_if_no_certificate` — graceful when no birth cert
19. `test_temporal_context_format` — matches expected block format
20. `test_temporal_context_disabled_via_config` — respects enabled=false

#### Injection Point Tests
21. `test_direct_message_includes_temporal_header` — temporal block in DM prompts
22. `test_ward_room_notification_includes_temporal_header` — temporal block in WR prompts
23. `test_proactive_think_includes_temporal_header` — temporal block in proactive prompts
24. `test_temporal_header_position_in_prompt` — appears before main content, after system info

#### Episode Timestamp Tests
25. `test_recalled_episodes_include_relative_time` — "[3h 15m ago]" prefix on memories
26. `test_episode_timestamps_respect_config` — can be disabled
27. `test_episode_timestamp_formatting` — correct human-readable duration

#### Duration Formatter Tests
28. `test_format_duration_seconds` — <60s → "45s"
29. `test_format_duration_minutes` — <1h → "12m 30s"
30. `test_format_duration_hours` — <1d → "3h 45m"
31. `test_format_duration_days` — ≥1d → "2d 14h"
32. `test_format_duration_zero` — 0 → "0s"

#### Hibernation Protocol Tests
33. `test_stasis_announcement_on_shutdown` — Ward Room "Entering Stasis" thread created
34. `test_stasis_recovery_announcement_on_startup` — Ward Room stasis recovery thread with duration
35. `test_reset_announcement_on_cold_start` — existing "Fresh Start" message preserved
36. `test_first_boot_announcement` — maiden voyage message on first ever boot
37. `test_stasis_notification_includes_duration` — human-readable stasis duration in message

#### State Snapshot Tests
38. `test_state_snapshot_includes_temporal` — temporal key in snapshot
39. `test_state_snapshot_temporal_fields` — current_time, uptime, lifecycle_state, session_id

#### Integration Tests
40. `test_full_shutdown_restart_stasis_flow` — shutdown persists → restart detects → agents informed
41. `test_reset_after_previous_session` — cold start with session record = reset, not stasis
42. `test_birth_timestamp_hydrated_on_wire` — agent._birth_timestamp set during _wire_agent

## Deferred Items

| Item | Deferred To | Rationale |
|------|------------|-----------|
| HXI temporal display (clock, uptime widget) | AD-497 or future HXI AD | Frontend concern, not cognitive |
| Stasis duration in agent profile API response | Future AD | API surface change |
| Federation session sync | AD-479 | Federation concern |
| Timezone awareness (local vs UTC) | Future AD | Complexity — UTC-only for now |
| Session history (list of past sessions, not just last) | Future AD | Nice-to-have, not MVP |

## Recommendations

1. **`_fresh_boot` is dead code** — runtime.py line 336 initializes it to False, never sets it True. AD-502 replaces this with `_lifecycle_state`. Remove `_fresh_boot` as cleanup.

2. **Post count injection** — requires the proactive loop to pass the agent's recent WR post count into the cognitive context. Currently `_ward_room_cooldowns` and `_ward_room_agent_thread_responses` track this in runtime but don't expose it to agents. The proactive loop should query WR for the agent's post count in the last hour and include it in context.

3. **Don't over-prompt** — The temporal header should be concise (5-6 lines max). LLM context is precious. Don't add paragraphs of temporal exposition.

4. **Consider day/night metaphor** — Agents could develop natural rhythms if they know time-of-day. Not required for this AD, but worth noting as emergent behavior potential.

5. **Stasis vs Sleep** — Current shutdown announcement says "System Restart." This is misleading — it should say "Entering Stasis" to clearly communicate what's happening. Dreams already use "sleep" metaphor. Stasis = shutdown. Sleep = dream cycle. Keep the distinction clear.

## Connects To

- **AD-441** (Sovereign Identity) — BirthCertificate.birth_timestamp is the source of birth time
- **AD-442** (Self-Naming) — naming ceremony happens on reset, not on stasis recovery
- **BF-034** (Cold-Start Trust Suppression) — lifecycle detection must integrate with cold-start flag
- **BF-057** (Identity Persistence) — warm boot identity detection feeds into stasis vs reset
- **AD-488** (Circuit Breaker) — temporal awareness enables self-regulation (reduces circuit breaker trips)
- **Standing Orders** — federation.md references "instantiated at a specific time" but never provides the time
- **Proactive Loop** — temporal context passed through `_gather_context()` in proactive.py

## Builder Instructions

1. Read this prompt completely before writing any code.
2. Start with the `_format_duration()` utility and its tests.
3. Build the Session Ledger (Component 1) — add runtime fields, shutdown persistence, startup detection.
4. Build the Temporal Context Header (Component 2) — `_build_temporal_context()` method, inject into all three intent branches.
5. Build Episode Timestamp Surfacing (Component 3) — modify memory recall formatting.
6. Build the Hibernation Protocol (Component 5) — stasis/wake announcements.
7. Add TemporalConfig to config.py and system.yaml.
8. Wire birth_timestamp hydration in `_wire_agent()`.
9. Clean up `_fresh_boot` dead code (replace with `_lifecycle_state`).
10. Run targeted tests. Fix any failures. Commit.
