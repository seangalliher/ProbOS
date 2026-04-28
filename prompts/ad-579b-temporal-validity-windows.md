# AD-579b: Temporal Validity Windows

**Status:** Ready for builder
**Depends on:** None (standalone dataclass + recall extension)
**Issue:** #37

## Problem Statement

Knowledge entries lack validity windows. "Worf's trust is 0.72" from 3 days ago has no expiration signal — it persists in recall indefinitely with no indication it may be stale. Temporal facts need `valid_from` / `valid_until` metadata so recall can filter episodes that are no longer valid at the time of query.

Currently `Episode` and `AnchorFrame` in `src/probos/types.py` have no validity fields. `EpisodicMemory.recall_weighted()` in `src/probos/cognitive/episodic.py` has no validity-aware filtering. ChromaDB metadata does not store validity timestamps.

## Implementation

### Add Validity Fields to Episode

File: `src/probos/types.py`

`Episode` is `@dataclass(frozen=True)` at line 407. Add two new fields **after** `correlation_id`:

```python
# AD-579b: Temporal validity windows — when is this episode's content valid?
valid_from: float = 0.0    # epoch timestamp; 0.0 = episode.timestamp (creation time)
valid_until: float = 0.0   # epoch timestamp; 0.0 = no expiry (valid forever)
```

Both fields have defaults, so existing code constructing `Episode` without them continues to work.

### Add Validity Fields to AnchorFrame

File: `src/probos/types.py`

`AnchorFrame` is `@dataclass(frozen=True)` at line 352. Add two new fields **after** `anomaly_window_id` (line 385):

```python
# AD-579b: Temporal validity for anchor-scoped facts
temporal_validity_start: float = 0.0  # epoch; 0.0 = anchor creation time
temporal_validity_end: float = 0.0    # epoch; 0.0 = no expiry
```

### Update Episode Reconstruction in store()

File: `src/probos/cognitive/episodic.py`

The `store()` method at line 913 reconstructs frozen Episodes when computing importance (line 933-948). Update the reconstruction to include the new fields:

```python
episode = Episode(
    ...existing fields...,
    correlation_id=episode.correlation_id,
    valid_from=episode.valid_from,
    valid_until=episode.valid_until,
)
```

### Add Validity Fields to ChromaDB Metadata

File: `src/probos/cognitive/episodic.py`

In `_episode_to_metadata()` (line 1709), add to the `metadata` dict after `"importance"`:

```python
"valid_from": float(ep.valid_from),
"valid_until": float(ep.valid_until),
```

### Add Validity-Aware Filtering to recall_weighted()

File: `src/probos/cognitive/episodic.py`

Modify `recall_weighted()` signature (line 2052) — add optional parameter:

```python
valid_at: float = 0.0,  # AD-579b: when non-zero, exclude expired episodes
```

After the existing scoring loop, before the context budget enforcement section, add a post-filter:

```python
# AD-579b: Temporal validity filtering
if valid_at > 0:
    scored = [
        s for s in scored
        if _episode_validity_check(s.episode, valid_at)
    ]
```

### Add _episode_validity_check Helper

File: `src/probos/cognitive/episodic.py`

Add as a module-level function near the top (after imports):

```python
def _episode_validity_check(episode: Episode, at_time: float) -> bool:
    """AD-579b: Check if an episode is temporally valid at a given time.

    Rules:
    - valid_until == 0.0 means no expiry — always valid
    - valid_until > 0 and valid_until < at_time means expired — exclude
    - valid_from > at_time means not yet valid — exclude
    - valid_from == 0.0 means valid from creation — always passes start check
    """
    if episode.valid_until > 0 and episode.valid_until < at_time:
        return False
    if episode.valid_from > 0 and episode.valid_from > at_time:
        return False
    return True
```

### Add recall_valid_at() Convenience Method

File: `src/probos/cognitive/episodic.py`

Add a new method to `EpisodicMemory` (after `recall_weighted`):

```python
async def recall_valid_at(
    self,
    timestamp: float,
    agent_id: str,
    query: str,
    **kwargs: Any,
) -> list[RecallScore]:
    """AD-579b: Convenience wrapper — recall_weighted with validity filtering at the given timestamp.

    Passes all kwargs through to recall_weighted with valid_at set.
    """
    return await self.recall_weighted(
        agent_id, query, valid_at=timestamp, **kwargs
    )
```

### Add TemporalValidityConfig

File: `src/probos/config.py`

Add after `PinnedKnowledgeConfig` (or after `MetabolismConfig` if AD-579a has not been built yet):

```python
class TemporalValidityConfig(BaseModel):
    """AD-579b: Temporal validity windows for episodic memory."""
    enabled: bool = True
    default_validity_hours: float = 0.0  # 0 = no default expiry
```

### Update _metadata_to_episode()

File: `src/probos/cognitive/episodic.py`

Find `_metadata_to_episode()` — update it to reconstruct validity fields from ChromaDB metadata:

```python
valid_from=float(meta.get("valid_from", 0.0)),
valid_until=float(meta.get("valid_until", 0.0)),
```

## Acceptance Criteria

1. `Episode` has `valid_from` and `valid_until` fields with 0.0 defaults.
2. `AnchorFrame` has `temporal_validity_start` and `temporal_validity_end` fields with 0.0 defaults.
3. ChromaDB metadata includes `valid_from` and `valid_until` for new episodes.
4. `recall_weighted()` accepts `valid_at` parameter and excludes expired episodes.
5. `recall_valid_at()` convenience method works correctly.
6. `_episode_validity_check()` correctly handles all four cases (no expiry, expired, not yet valid, valid).
7. Existing code that constructs `Episode` without validity fields continues to work (defaults).
8. `TemporalValidityConfig` added to config with Pydantic validation.
9. Metadata round-trip: store episode with validity -> recall -> fields preserved.

## Test Plan

File: `tests/test_ad579b_temporal_validity.py`

10 tests:

| # | Test Name | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_episode_validity_fields_default` | New `Episode()` has `valid_from=0.0, valid_until=0.0` |
| 2 | `test_anchor_validity_fields_default` | New `AnchorFrame()` has `temporal_validity_start=0.0, temporal_validity_end=0.0` |
| 3 | `test_validity_check_excludes_expired` | `_episode_validity_check(ep, now)` returns False when `valid_until < now` |
| 4 | `test_validity_check_includes_valid` | Returns True when `valid_until > now` or `valid_until == 0` |
| 5 | `test_validity_zero_means_no_expiry` | `valid_until=0.0` never expires regardless of query time |
| 6 | `test_valid_from_future_excluded` | `valid_from > query_time` excludes episode (not yet valid) |
| 7 | `test_chromadb_metadata_roundtrip` | Store episode with validity fields, retrieve metadata, confirm fields present |
| 8 | `test_recall_weighted_valid_at_filters` | `recall_weighted(..., valid_at=now)` excludes expired episodes from results |
| 9 | `test_validity_config_defaults` | `TemporalValidityConfig()` has expected defaults |
| 10 | `test_mixed_valid_invalid_episodes` | Batch of episodes with mixed validity; recall returns only valid ones |

Use `_FakeEpisodicMemory` or construct real `EpisodicMemory` with `tmp_path` ChromaDB for metadata round-trip tests. For pure filtering tests, test `_episode_validity_check()` directly.

Run targeted: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad579b_temporal_validity.py -v`

## Do Not Build

- No automatic validity inference from episode content (no LLM parsing of "Worf's trust is 0.72 as of today").
- No UI for setting validity windows.
- No retroactive validity propagation across existing episodes (that is AD-608).
- No validity-aware anchor recall (`recall_by_anchor` unchanged).
- No changes to dream consolidation (that is AD-579c).

## Tracker Updates

- `PROGRESS.md`: Add `AD-579b Temporal Validity Windows — CLOSED` under Memory Architecture
- `DECISIONS.md`: Add entry: "AD-579b: Added valid_from/valid_until to Episode and AnchorFrame. recall_weighted() accepts valid_at parameter for temporal filtering. ChromaDB metadata stores validity timestamps. 0.0 = no constraint (backward compatible)."
- `docs/development/roadmap.md`: Update AD-579b row to COMPLETE
- Issue: #37
