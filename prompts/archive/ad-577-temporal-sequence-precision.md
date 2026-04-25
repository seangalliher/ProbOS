# AD-577: Temporal Sequence Precision — Intra-Cycle Event Ordering

## Classification
- **Type:** Enhancement (memory capture quality)
- **Priority:** Medium
- **Risk:** Low — additive fields, no behavioral changes to existing pathways
- **Estimated Scope:** 3 files modified, ~60 lines changed, 12+ new tests

## Problem

During high-activity Ward Room periods, episode timestamps reflect **processing time**
(`time.time()` at episode creation) rather than **source event time** (when the Ward Room
post was originally created). Additionally, when multiple Ward Room posts are consumed
as context within a single proactive cycle, their relative ordering is lost — all context
items share the same processing timestamp with no sequence differentiation.

Echo (Counselor) identified the clinical impact: "The temporal anchoring during
high-activity periods sometimes gets a bit fuzzy... it makes my clinical assessments
slightly less precise."

## Root Cause Analysis

**Two distinct gaps:**

1. **Source timestamps dropped.** Ward Room's `get_recent_activity()` returns `created_at`
   on each item (epoch float from SQLite). But `_gather_context()` in `proactive.py`
   (lines 1034-1045) builds the `ward_room_activity` list WITHOUT including `created_at`.
   The original post timestamp is discarded at context-building time.

2. **No intra-batch ordering.** AnchorFrame (AD-567a) has temporal fields (`duty_cycle_id`,
   `watch_section`) but no sub-cycle ordering mechanism. When `_gather_context()` fetches
   5 department posts + 3 All Hands posts + 2 Recreation posts in one cycle, they are
   presented to the LLM as an unordered list. The episode created from the agent's response
   has no record of which stimulus came first.

**What IS working correctly:** Each Ward Room `create_thread()` and `create_post()` call
creates its own episode with `timestamp=time.time()` at creation — these are accurate
because they happen synchronously. The problem is the **consuming side** (proactive loop)
where an agent reads multiple posts and creates an episode about its response to them.

## Prior Work Absorbed

- **AD-567a** — AnchorFrame infrastructure (10 fields, 5 dimensions). This AD adds fields
  to the TEMPORAL dimension.
- **AD-570/570b** — Anchor-indexed recall + participant index. Benefits from richer temporal
  metadata for query filtering.
- **AD-573** — Working memory. WM entries also benefit from source timestamps.
- **AD-568b** — Adaptive Budget Scaling. Temporal precision improves confidence scoring.
- **Content hash impact:** AnchorFrame fields are NOT included in content hash
  (`episodic.py` line 1199: `normalized = replace(ep, ..., anchors=None)`). Adding new
  AnchorFrame fields will NOT affect episode integrity verification.
- **ChromaDB metadata:** AnchorFrame is stored as JSON blob in `anchors_json` metadata
  field. New fields serialize automatically via `dataclasses.asdict()` and deserialize
  via `AnchorFrame(**dict)`. No schema migration needed — new fields have defaults.

## Engineering Principles Applied

- **Open/Closed (O):** Extends AnchorFrame with new defaulted fields — existing episodes
  deserialize without changes (`sequence_index=0`, `source_timestamp=0.0` defaults).
- **DRY:** Reuses existing `created_at` data from Ward Room — no new timestamp source.
- **Fail Fast / Log-and-Degrade:** If `created_at` is missing from activity items, fall
  back to 0.0 (unknown). Never fail on missing temporal data.
- **Defense in Depth:** Both `sequence_index` AND `source_timestamp` are provided.
  Sequence gives relative ordering even when timestamps collide. Source timestamp gives
  absolute time even without sequence context.
- **Single Responsibility (S):** AnchorFrame holds metadata, proactive loop holds
  context-building logic. Each changes for one reason.

## Implementation

### 1. Add fields to AnchorFrame — `src/probos/types.py`

**Location:** AnchorFrame dataclass (lines 310-338)

Add two fields to the TEMPORAL section:

```python
@dataclass(frozen=True)
class AnchorFrame:
    # TEMPORAL
    duty_cycle_id: str = ""
    watch_section: str = ""
    sequence_index: int = 0       # AD-577: intra-cycle ordering (monotonic within a batch)
    source_timestamp: float = 0.0  # AD-577: original event time (e.g. WR post created_at)
    # SPATIAL
    channel: str = ""
    channel_id: str = ""
    department: str = ""
    # SOCIAL
    participants: list[str] = field(default_factory=list)
    trigger_agent: str = ""
    # CAUSAL
    trigger_type: str = ""
    # EVIDENTIAL
    thread_id: str = ""
    event_log_window: float = 0.0
```

**Design notes:**
- `sequence_index: int = 0` — 0 means "no sequence info" (backwards compatible). 1-based
  within a batch.
- `source_timestamp: float = 0.0` — 0.0 means "no source timestamp available" (backwards
  compatible). Epoch float matching Ward Room `created_at` format.
- `frozen=True` preserved — immutable after creation.
- Default values ensure existing AnchorFrame deserialization (`AnchorFrame(**dict)`) works
  for old episodes that lack these fields.

### 2. Pass `created_at` through context — `src/probos/proactive.py`

**Location:** `_gather_context()` method, three Ward Room activity list comprehensions.

#### 2a. Department channel activity (lines 1034-1045)

Add `created_at` to the activity dict:

```python
context["ward_room_activity"] = [
    {
        "type": a["type"],
        "author": a["author"],
        "body": a.get("title", a.get("body", ""))[:500],
        "net_score": a.get("net_score", 0),       # AD-426
        "post_id": a.get("post_id", a.get("id", "")),  # AD-426
        "thread_id": a.get("thread_id", ""),  # AD-437
        "created_at": a.get("created_at", 0.0),  # AD-577
    }
    for a in activity
    if (a.get("author_id", "") or a.get("author", "")) not in self_ids  # BF-032
]
```

#### 2b. All Hands activity (lines 1065-1077)

Add `created_at` to the All Hands activity dict:

```python
context["ward_room_activity"].extend([
    {
        "type": item["type"],
        "author": item.get("author", "unknown"),
        "body": item.get("body", "")[:500],
        "channel": "All Hands",
        "net_score": item.get("net_score", 0),       # AD-426
        "post_id": item.get("post_id", item.get("id", "")),  # AD-426
        "thread_id": item.get("thread_id", ""),  # AD-437
        "created_at": item.get("created_at", 0.0),  # AD-577
    }
    for item in all_hands_filtered[:3]
    if (item.get("author_id", "") or item.get("author", "")) not in self_ids  # BF-032
])
```

#### 2c. Recreation channel activity (lines ~1094+)

Find the Recreation channel activity list comprehension (after line 1094) and add
`created_at` in the same pattern:

```python
"created_at": item.get("created_at", 0.0),  # AD-577
```

### 3. Source timestamp on proactive Ward Room episodes — `src/probos/ward_room/threads.py`

**Location:** Thread creation episode (lines 383-410)

The thread creation episode already has an AnchorFrame. Add `source_timestamp` using the
thread's own `created_at`:

```python
anchors=AnchorFrame(
    channel="ward_room",
    channel_id=channel_id,
    thread_id=thread.id,
    trigger_type="ward_room_post",
    participants=[author_callsign or author_id],
    trigger_agent=author_callsign or author_id,
    department=self._resolve_author_department(author_id),
    source_timestamp=thread.created_at,  # AD-577
),
```

### 4. Source timestamp on Ward Room reply episodes — `src/probos/ward_room/messages.py`

Find the reply episode creation (around line 184-210) and add `source_timestamp` using
the post's `created_at`:

```python
source_timestamp=post.created_at,  # AD-577: original event time
```

**Note:** For thread/reply episodes, `source_timestamp` will be very close to `timestamp`
(both set at creation time). The value is for consistency — all Ward Room episodes now
carry source timing in the same field, and future recall queries can use `source_timestamp`
uniformly.

### 5. Sequence indexing on proactive context — `src/probos/proactive.py`

**Location:** After all three Ward Room activity batches are assembled in `_gather_context()`,
sort by `created_at` and assign sequence indices.

After the Recreation channel activity block (after the `rec_filtered` processing), add:

```python
# AD-577: Sort ward_room_activity by source timestamp and assign sequence indices
if context.get("ward_room_activity"):
    context["ward_room_activity"].sort(key=lambda a: a.get("created_at", 0.0))
    for idx, item in enumerate(context["ward_room_activity"], start=1):
        item["sequence_index"] = idx
```

This ensures that when the LLM sees Ward Room activity, it's in chronological order,
and each item carries its sequence position for downstream use.

### 6. Anchor enrichment on proactive response episode — `src/probos/proactive.py`

**Location:** Find where the proactive thought episode is created when Ward Room is
NOT available (the fallback path around line 696-720). This is the `if not wr_available`
block that creates episodes directly.

If this fallback episode has an AnchorFrame, add the earliest source timestamp from the
Ward Room context that triggered the response:

```python
# AD-577: Use earliest WR source timestamp if available
wr_activity = context.get("ward_room_activity", [])
earliest_source_ts = min(
    (a.get("created_at", 0.0) for a in wr_activity if a.get("created_at", 0.0) > 0),
    default=0.0,
)
```

Then pass `source_timestamp=earliest_source_ts` to the AnchorFrame constructor if one
exists in that block. If no AnchorFrame is constructed in that block, this step is
optional — the primary path (WR available) creates episodes via `create_thread()` which
is already handled in step 3.

**Important:** Read the actual code at lines 672-722 before implementing. If there is no
AnchorFrame in that block, add one following the pattern from `create_thread()` at
`threads.py` line 398-406. Include `source_timestamp` and set `sequence_index=0`
(single episode, no batch ordering needed).

### 7. Working memory source timestamp — `src/probos/proactive.py`

**Location:** Find where proactive observations are recorded to working memory (around
line 555, the `add_observation()` call).

If the observation is derived from Ward Room context, pass the earliest source timestamp
as metadata. Check the `add_observation()` signature — if it accepts metadata or extra
fields, include `source_timestamp`. If not, this step is deferred (WM entries already
have their own timestamps via `time.time()`).

**Important:** Do NOT modify `AgentWorkingMemory.add_observation()` signature unless it
already accepts a timestamp parameter. If it doesn't, skip this step — it's a future
enhancement, not a requirement for AD-577.

## Tests

**File:** `tests/test_ad577_temporal_sequence.py`

### Test Class: `TestAnchorFrameTemporalFields`

1. **`test_anchor_frame_new_fields_default`**
   - `AnchorFrame()` → `sequence_index == 0`, `source_timestamp == 0.0`

2. **`test_anchor_frame_serialization_roundtrip`**
   - Create AnchorFrame with `sequence_index=3`, `source_timestamp=1712500000.0`
   - `dataclasses.asdict()` → dict → `AnchorFrame(**dict)` → fields match

3. **`test_anchor_frame_backwards_compatible_deserialization`**
   - Old dict WITHOUT `sequence_index`/`source_timestamp` keys
   - `AnchorFrame(**old_dict)` → uses defaults, no error

### Test Class: `TestProactiveContextTimestamps`

4. **`test_gather_context_includes_created_at`**
   - Mock `get_recent_activity()` returning items with `created_at` values
   - Call `_gather_context()` (or test the dict comprehension directly)
   - Assert `ward_room_activity` items include `created_at` field

5. **`test_gather_context_sorts_by_created_at`**
   - 3 activity items with out-of-order `created_at` values
   - After processing, items sorted chronologically

6. **`test_gather_context_assigns_sequence_indices`**
   - 3 activity items in a batch
   - After processing, items have `sequence_index` 1, 2, 3

7. **`test_gather_context_created_at_missing_defaults_to_zero`**
   - Activity item without `created_at` key
   - Defaults to `0.0`, no error

### Test Class: `TestWardRoomEpisodeSourceTimestamp`

8. **`test_thread_episode_has_source_timestamp`**
   - Create a thread via `create_thread()`
   - Stored episode's AnchorFrame has `source_timestamp` matching thread's `created_at`

9. **`test_reply_episode_has_source_timestamp`**
   - Create a reply via `create_post()`
   - Stored episode's AnchorFrame has `source_timestamp` matching post's `created_at`

10. **`test_source_timestamp_zero_when_unavailable`**
    - Episode created without Ward Room context
    - AnchorFrame `source_timestamp == 0.0`

### Test Class: `TestContentHashUnaffected`

11. **`test_new_anchor_fields_do_not_affect_content_hash`**
    - Create two identical episodes, one with `sequence_index=0`/`source_timestamp=0.0`,
      one with `sequence_index=5`/`source_timestamp=1712500000.0`
    - Content hashes are identical (AnchorFrame excluded from hash)

12. **`test_episode_with_new_anchor_fields_stores_and_recalls`**
    - Store episode with populated `sequence_index`/`source_timestamp`
    - Recall episode
    - AnchorFrame fields preserved through ChromaDB round-trip

## Verification

1. `pytest tests/test_ad577_temporal_sequence.py -v` — all new tests pass
2. `pytest tests/ -x --timeout=60` — full suite, no regressions
3. Manual: Start ProbOS → wait for proactive cycle → check logs for Ward Room activity
   consumption → DM an agent → verify episode AnchorFrame includes `source_timestamp`
   and `sequence_index` in episodic memory
4. Verify: Old episodes (pre-AD-577) still deserialize correctly — `sequence_index=0`,
   `source_timestamp=0.0` defaults apply

## What This AD Does NOT Do

- Does NOT change the proactive cycle timing or frequency
- Does NOT affect dream consolidation (operates on episode-level, not entry-level)
- Does NOT require clock synchronization across agents
- Does NOT modify the content hash algorithm
- Does NOT add new ChromaDB promoted metadata fields (sequence/source_timestamp stay in
  `anchors_json` blob — promote to top-level only if recall queries need native filtering
  on these fields, which is a future AD)
- Does NOT modify `AgentWorkingMemory` entry structure (deferred, see step 7)
