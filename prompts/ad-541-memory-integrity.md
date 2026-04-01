# AD-541: Memory Integrity Verification — MVP (Pillars 1, 3, 6)

## Context

AD-540 (CLOSED) added structural provenance boundaries around recalled episodes (`=== SHIP MEMORY ===` markers) and a standing order for `[observed]`/`[training]`/`[inferred]` source attribution. That solved *source-level* separation (training vs experience).

AD-541 goes deeper — classifying memory *types* within the episodic store, verifying memories against the operational log, and establishing a reliability hierarchy. Three MVP pillars, all deterministic (zero LLM cost).

**Dependencies (all COMPLETE):**
- AD-430: Agent Experiential Memory — 12 episode store paths
- AD-502: Temporal Context Injection — time awareness
- AD-540: Provenance boundary markers + attribution standing order

## Problem

1. **No source classification.** All 12 episode store sites create `Episode()` with no indication of whether the agent experienced it directly or heard about it secondhand. The `Episode` dataclass has no `source` field.

2. **No verification.** Episode content is whatever the LLM described during `act()`. If the LLM fabricated details, those become "verified observations" inside the `=== SHIP MEMORY ===` boundary. There's no cross-check against the EventLog ground truth.

3. **No reliability hierarchy.** Agents have no standing order telling them which memory sources to trust more than others when information conflicts.

## Part 1: MemorySource Enum + Episode Data Model (Pillar 3)

### File: `src/probos/types.py`

Add the `MemorySource` enum **before** the `Episode` dataclass (after the section comment at line ~298):

```python
class MemorySource(str, Enum):
    """Classification of how an episode entered an agent's memory (AD-541)."""
    DIRECT = "direct"            # Agent personally experienced this
    SECONDHAND = "secondhand"    # Heard about it in Ward Room / DM from another agent
    SHIP_RECORDS = "ship_records"  # Read from Ship's Records (AD-434, future)
    BRIEFING = "briefing"        # Received during onboarding (AD-486, future)
```

Add the `from enum import Enum` import if not already present (check — `types.py` likely already imports `Enum` for `ModelTier` or similar).

Add two new fields to the `Episode` dataclass:

```python
@dataclass
class Episode:
    """A recorded episode from the cognitive pipeline."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = 0.0
    user_input: str = ""
    dag_summary: dict[str, Any] = field(default_factory=dict)
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    reflection: str | None = None
    agent_ids: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    embedding: list[float] = field(default_factory=list)
    shapley_values: dict[str, float] = field(default_factory=dict)
    trust_deltas: list[dict[str, Any]] = field(default_factory=list)
    # AD-541: Memory integrity fields
    source: str = "direct"       # MemorySource value — how this episode was acquired
```

Use `str` type (not `MemorySource`) for the field to keep ChromaDB serialization simple. The enum is for callers to import and use as constants.

### File: `src/probos/cognitive/episodic.py`

Update `_episode_to_metadata()` (line ~521) to persist the new field:

```python
# Add to the return dict:
"source": ep.source or "direct",
```

Update `_metadata_to_episode()` (line ~546) to restore it:

```python
# Add to the Episode constructor:
source=metadata.get("source", "direct"),
```

## Part 2: Tag All 12 Store Sites (Pillar 3)

All existing store sites are `DIRECT` — the agent personally performed the action or experienced the event. Set `source=MemorySource.DIRECT` (or `source="direct"`) explicitly at each site. This is mechanical but ensures future readers understand the classification.

**Import at each file:** `from probos.types import MemorySource`

| # | File | Line | Set to | Rationale |
|---|------|------|--------|-----------|
| 1 | `src/probos/cognitive/cognitive_agent.py` | ~884 | `DIRECT` | Agent handled an intent |
| 2 | `src/probos/experience/renderer.py` | ~422 | `DIRECT` | Agent executed a DAG (user query) |
| 3 | `src/probos/proactive.py` | ~368 | `DIRECT` | Agent's own proactive thought (no-response) |
| 4 | `src/probos/proactive.py` | ~484 | `DIRECT` | Agent's own proactive thought (with response) |
| 5 | `src/probos/runtime.py` | ~2060 | `DIRECT` | DAG execution (legacy path) |
| 6 | `src/probos/runtime.py` | ~2820 | `DIRECT` | SystemQA smoke test |
| 7 | `src/probos/experience/commands/session.py` | ~157 | `DIRECT` | 1:1 conversation (shell) |
| 8 | `src/probos/routers/agents.py` | ~218 | `DIRECT` | 1:1 conversation (HXI) |
| 9 | `src/probos/ward_room/messages.py` | ~140 | `DIRECT` | Agent posted a Ward Room reply |
| 10 | `src/probos/ward_room/threads.py` | ~279 | `DIRECT` | Agent created a Ward Room thread |
| 11 | `src/probos/cognitive/feedback.py` | ~225 | `DIRECT` | Feedback correction applied |
| 12 | `src/probos/cognitive/feedback.py` | ~377 | `DIRECT` | Human feedback received |

At each site, add `source=MemorySource.DIRECT` to the `Episode(...)` constructor call. Example pattern:

```python
# BEFORE:
episode = Episode(
    timestamp=time.time(),
    user_input=f"[Ward Room reply] ...",
    ...
)

# AFTER:
from probos.types import MemorySource

episode = Episode(
    timestamp=time.time(),
    user_input=f"[Ward Room reply] ...",
    source=MemorySource.DIRECT,
    ...
)
```

**Note:** Some sites build the Episode without keyword `source=`. Just add it. The default is `"direct"`, so even if you miss one, it's correct — but be explicit everywhere for clarity.

## Part 3: EventLog Verification at Recall Time (Pillar 1)

### File: `src/probos/cognitive/cognitive_agent.py`

**Target: `_recall_relevant_memories()` method (line ~750)**

After episodes are fetched (line ~798), add a verification step that cross-checks each episode against the EventLog. This happens at **recall time**, not store time, keeping EpisodicMemory decoupled from EventLog.

**After** the episodes are fetched and the `observation["recent_memories"]` list is built (line ~806-814), add a `"verified"` key to each memory dict:

```python
# BEFORE (current, line ~806-814):
observation["recent_memories"] = [
    {
        "input": ep.user_input[:200] if ep.user_input else "",
        "reflection": ep.reflection[:200] if ep.reflection else "",
        **({"age": format_duration(time.time() - ep.timestamp)}
           if include_ts and ep.timestamp > 0 else {}),
    }
    for ep in episodes
]

# AFTER:
# AD-541: Verify episodes against EventLog at recall time
event_log = getattr(self._runtime, 'event_log', None)

memory_list = []
for ep in episodes:
    mem = {
        "input": ep.user_input[:200] if ep.user_input else "",
        "reflection": ep.reflection[:200] if ep.reflection else "",
        "source": getattr(ep, 'source', 'direct'),
    }
    if include_ts and ep.timestamp > 0:
        mem["age"] = format_duration(time.time() - ep.timestamp)

    # AD-541 Pillar 1: Cross-check against EventLog
    mem["verified"] = False
    if event_log and ep.timestamp > 0 and ep.agent_ids:
        try:
            corroborating = await event_log.query(
                agent_id=ep.agent_ids[0],
                limit=1,
            )
            if corroborating:
                # Check if any EventLog entry is within +/- 120s of the episode
                for evt in corroborating:
                    evt_ts = evt.get("timestamp", "")
                    if evt_ts:
                        from datetime import datetime
                        try:
                            evt_time = datetime.fromisoformat(evt_ts).timestamp()
                            if abs(evt_time - ep.timestamp) < 120:
                                mem["verified"] = True
                                break
                        except (ValueError, TypeError):
                            pass
        except Exception:
            pass  # EventLog unavailable — leave unverified

    memory_list.append(mem)

observation["recent_memories"] = memory_list
```

**Important:** The EventLog `query()` method returns dicts with ISO 8601 `timestamp` strings. The Episode has a float Unix timestamp. Convert for comparison. The 120-second window accounts for timing differences between when the episode was stored and when the event was logged.

**If EventLog is unavailable** (not started, not wired, error), all episodes default to `verified=False`. This is safe — absence of verification does not mean the memory is false.

## Part 4: Update Boundary Markers to Show Source + Verification (AD-540 extension)

### File: `src/probos/cognitive/cognitive_agent.py`

**Target: `_format_memory_section()` method (line ~533)**

Update the helper to show source type and verification status on each memory entry:

```python
def _format_memory_section(self, memories: list[dict]) -> list[str]:
    """Format recalled episodes with provenance boundary markers (AD-540/541)."""
    lines = [
        "=== SHIP MEMORY (your experiences aboard this vessel) ===",
        "These are YOUR experiences. Do NOT confuse with training knowledge.",
        "Markers: [direct] = you experienced it, [secondhand] = you heard about it.",
        "[verified] = corroborated by ship's log, [unverified] = not yet corroborated.",
        "",
    ]
    for mem in memories:
        entry = "  - "
        # AD-541: Source and verification tags
        source = mem.get("source", "direct")
        verified = "verified" if mem.get("verified") else "unverified"
        entry += f"[{source} | {verified}] "
        if mem.get("age"):
            entry += f"[{mem['age']} ago] "
        entry += mem.get("input", "") or mem.get("reflection", "")
        lines.append(entry)
    lines.append("")
    lines.append("=== END SHIP MEMORY ===")
    return lines
```

**Key changes from AD-540 version:**
- Header wording softened: "your experiences" instead of "your verified observations" (since not all are verified now)
- Added marker legend line
- Each entry gets `[direct | verified]` or `[direct | unverified]` prefix

## Part 5: Memory Reliability Hierarchy Standing Order (Pillar 6)

### File: `config/standing_orders/federation.md`

**Add** the following section immediately after the existing "Knowledge Source Attribution (AD-540)" section (after line ~127, before "Layer Architecture"):

```markdown
## Memory Reliability Hierarchy (AD-541)

When information from different sources conflicts, trust them in this order (most reliable first):

1. **EventLog** (ship's operational log) — system-generated, tamper-evident, ground truth for what happened
2. **Ship's Records** (Git-backed institutional knowledge) — reviewed, versioned, shared
3. **Episodic Memory [direct | verified]** — your personal experience, corroborated by ship's log
4. **Episodic Memory [direct | unverified]** — your personal experience, not yet corroborated
5. **Episodic Memory [secondhand]** — something another crew member reported (Ward Room, DM)
6. **Training Knowledge** — general knowledge from your language model, not ship-specific

Never elevate a lower-tier source above a higher-tier one. If your [secondhand] memory contradicts the EventLog, the EventLog is correct. If your training knowledge contradicts your [direct | verified] experience, your experience is correct.
```

## Tests

### File: `tests/test_memory_integrity.py` (new file)

#### MemorySource Enum Tests

**Test 1: MemorySource values are strings**
- Assert `MemorySource.DIRECT == "direct"`, `MemorySource.SECONDHAND == "secondhand"`, etc.
- Assert `MemorySource.DIRECT` is a `str` (str Enum property)

**Test 2: Episode source field defaults to "direct"**
- Create `Episode()` with no source argument
- Assert `episode.source == "direct"`

**Test 3: Episode source field accepts MemorySource**
- Create `Episode(source=MemorySource.SECONDHAND)`
- Assert `episode.source == "secondhand"`

#### ChromaDB Metadata Round-Trip Tests

**Test 4: Source field persisted in metadata**
- Create Episode with `source=MemorySource.DIRECT`
- Call `EpisodicMemory._episode_to_metadata(ep)`
- Assert `metadata["source"] == "direct"`

**Test 5: Source field restored from metadata**
- Create metadata dict with `"source": "secondhand"`
- Call `EpisodicMemory._metadata_to_episode(id, doc, metadata)`
- Assert `episode.source == "secondhand"`

**Test 6: Missing source in metadata defaults to "direct"**
- Create metadata dict WITHOUT `"source"` key (backwards compatibility)
- Call `_metadata_to_episode()`
- Assert `episode.source == "direct"`

#### Verification Tests

**Test 7: Verified when EventLog has corroborating entry**
- Mock runtime with episodic_memory returning 1 episode and event_log.query() returning an event within 120s
- Call `_recall_relevant_memories()`
- Assert `observation["recent_memories"][0]["verified"] is True`

**Test 8: Unverified when EventLog has no matching entry**
- Mock runtime with episodic_memory returning 1 episode and event_log.query() returning empty list
- Call `_recall_relevant_memories()`
- Assert `observation["recent_memories"][0]["verified"] is False`

**Test 9: Unverified when EventLog unavailable**
- Mock runtime with no `event_log` attribute
- Call `_recall_relevant_memories()`
- Assert `observation["recent_memories"][0]["verified"] is False`

**Test 10: Unverified when EventLog timestamp outside 120s window**
- Mock event_log.query() returning event with timestamp 300s away from episode
- Assert `verified is False`

#### Boundary Marker Tests

**Test 11: Source and verification tags in formatted output**
- Call `_format_memory_section()` with memories containing `source="direct"`, `verified=True`
- Assert entry contains `[direct | verified]`

**Test 12: Secondhand + unverified tags**
- Call with `source="secondhand"`, `verified=False`
- Assert entry contains `[secondhand | unverified]`

**Test 13: Marker legend present**
- Assert output contains `"[direct] = you experienced it"`
- Assert output contains `"[verified] = corroborated"`

**Test 14: Source field in memory dicts from _recall_relevant_memories**
- Mock episode with `source="direct"`
- Call `_recall_relevant_memories()`
- Assert `observation["recent_memories"][0]["source"] == "direct"`

#### Standing Order Tests

**Test 15: Memory reliability hierarchy in federation standing orders**
- Call `compose_instructions()` for any crew agent
- Assert output contains `"Memory Reliability Hierarchy"`
- Assert output contains `"EventLog"` appearing before `"Episodic Memory"` in the text

### Update existing tests

**File: `tests/test_provenance_boundary.py`**
- Update assertions for the new header wording: `"your experiences aboard this vessel"` instead of `"your verified observations aboard this vessel"`
- Update assertions for memory entry format: entries now have `[direct | verified]` or `[direct | unverified]` prefixes
- Add `source` and `verified` keys to test memory dicts where needed

## Verification

```bash
# 1. Verify MemorySource enum exists and Episode has source field
grep -n "class MemorySource" src/probos/types.py
grep -n "source:" src/probos/types.py

# 2. Verify ChromaDB metadata includes source
grep -n '"source"' src/probos/cognitive/episodic.py

# 3. Count store sites with explicit source= (should be 12)
grep -rn "source=MemorySource" src/probos/ | wc -l

# 4. Verify EventLog verification in recall path
grep -n "event_log" src/probos/cognitive/cognitive_agent.py

# 5. Verify boundary markers show source + verification
grep -n "source.*verified" src/probos/cognitive/cognitive_agent.py

# 6. Verify standing order
grep -n "Memory Reliability Hierarchy" config/standing_orders/federation.md

# 7. Run tests
python -m pytest tests/test_memory_integrity.py tests/test_provenance_boundary.py -v
```

## Principles Compliance

- **SRP:** MemorySource enum in types.py (data), verification in cognitive_agent.py (presentation), hierarchy in federation.md (policy) — clean separation
- **DRY:** Source tagging at the 12 store sites is the single point of truth; verification happens once at recall time
- **Open/Closed:** MemorySource enum is extensible (SHIP_RECORDS, BRIEFING ready for AD-434/486)
- **Defense in Depth:** Data-level source field (Pillar 3) + runtime verification (Pillar 1) + standing order policy (Pillar 6) — three independent layers
- **Law of Demeter:** EventLog access via `self._runtime.event_log` follows existing pattern (same as episodic_memory access)
- **Backwards compatibility:** Missing `source` in old ChromaDB metadata defaults to `"direct"`. Missing EventLog defaults to `verified=False`. No migration needed.
