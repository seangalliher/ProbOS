# AD-567b: Anchor-Aware Recall Formatting + Salience-Weighted Retrieval

**Absorbs:** AD-462a (Salience-Weighted Episodic Recall)
**Depends:** AD-567a (Episode Anchor Metadata — COMPLETE)
**Prior art:** Tulving (1973) encoding specificity, CAST (Ma 2026), RPMS (Yuan 2026)
**Principle:** "The brain doesn't remember everything — it remembers what matters. And when it can't, it asks someone who does."

---

## Context

AD-567a added `AnchorFrame` metadata to every episode (10 fields across 5 dimensions: temporal, spatial, social, causal, evidential). All 15 episode creation paths now populate anchors. But the recall pipeline ignores them entirely — recalled memories still appear as flat text with only `[source | verified]` tags. The recall query is hardcoded `"recent activity"` in the proactive path. There is no post-retrieval ranking beyond raw ChromaDB cosine similarity. And `MemorySource.SECONDHAND` has never been assigned to any episode despite being defined since AD-541.

AD-567b closes all four gaps in one AD:
1. **Anchor-aware recall formatting** — agents see WHERE, WHEN, WHO, WHY for each memory
2. **Salience-weighted re-ranking** — Trust × Hebbian × Recency scoring after retrieval
3. **FTS5 keyword search** — secondary retrieval channel alongside vector search
4. **SECONDHAND source wiring** — Ward Room episodes correctly tagged by source type

---

## Scope

### 1. Recall Result Scoring (`RecallScore` dataclass + `score_recall()`)

**File: `src/probos/cognitive/episodic.py`**

Create a `RecallScore` frozen dataclass:
```python
@dataclass(frozen=True)
class RecallScore:
    episode: Episode
    semantic_similarity: float   # 0.0–1.0, from ChromaDB cosine distance
    keyword_hits: int            # FTS5 match count (0 if no keyword match)
    trust_weight: float          # agent trust score (0.0–1.0)
    hebbian_weight: float        # intent-agent Hebbian weight (0.0–1.0)
    recency_weight: float        # exponential decay by age
    anchor_completeness: float   # 0.0–1.0, proportion of filled anchor fields
    composite_score: float       # weighted combination of all signals
```

Create `score_recall()` function that computes composite score:
```
composite = (
    0.35 * semantic_similarity
  + 0.10 * min(keyword_hits / 3.0, 1.0)
  + 0.15 * trust_weight
  + 0.10 * hebbian_weight
  + 0.20 * recency_weight
  + 0.10 * anchor_completeness
)
```

**Recency weight formula:** `recency = exp(-age_hours / 168.0)` — half-life of ~1 week, matching existing Ebbinghaus-style decay in AD-538.

**Anchor completeness:** Count non-empty AnchorFrame fields / 10. Episodes with `anchors=None` get 0.0.

**Configuration** — add to `MemoryConfig` in `config.py`:
```python
# AD-567b: Salience-weighted recall
recall_weights: dict[str, float] = field(default_factory=lambda: {
    "semantic": 0.35,
    "keyword": 0.10,
    "trust": 0.15,
    "hebbian": 0.10,
    "recency": 0.20,
    "anchor": 0.10,
})
recall_context_budget_chars: int = 4000  # ~4K char memory budget
```

### 2. Salience-Weighted Recall API (`recall_weighted()`)

**File: `src/probos/cognitive/episodic.py`**

Add new method to `EpisodicMemory`:

```python
async def recall_weighted(
    self,
    agent_id: str,
    query: str,
    *,
    trust_network: Any = None,
    hebbian_router: Any = None,
    intent_type: str = "",
    k: int = 5,
    context_budget: int = 4000,
) -> list[RecallScore]:
```

**Algorithm:**
1. **Semantic retrieval** — call existing `recall_for_agent(agent_id, query, k=k*3)` to get candidate episodes (over-fetch for re-ranking headroom)
2. **Keyword retrieval** — query FTS5 sidecar (see §3) with extracted keywords from `query`. Merge any new episodes not already in semantic results.
3. **Score each candidate:**
   - `semantic_similarity` — already computed inside `recall_for_agent` but NOT returned. **Modify `recall_for_agent` to return `list[tuple[Episode, float]]`** (episode + similarity). Add a `_scored` variant or modify the existing method with an optional `return_scores=True` parameter. Keep backwards compatibility — default behavior returns `list[Episode]` as today.
   - `trust_weight` — `trust_network.get_score(agent_id)` if available, else 0.5
   - `hebbian_weight` — `hebbian_router.get_weight(intent_type, agent_id, rel_type="intent")` if both `intent_type` and router available, else 0.5
   - `recency_weight` — `exp(-(time.time() - ep.timestamp) / (168 * 3600))`
   - `anchor_completeness` — count filled AnchorFrame fields
   - `keyword_hits` — from FTS5 results
4. **Compute composite**, sort descending
5. **Budget enforcement** — accumulate episodes until `sum(len(ep.user_input))` exceeds `context_budget`, then stop. This replaces hardcoded `k=3` / `k=5`.
6. Return `list[RecallScore]` sorted by composite score

**Do NOT remove existing `recall_for_agent()` or `recent_for_agent()`** — they are used by dream consolidation, clustering, spaced retrieval, etc. `recall_weighted()` is a new higher-level API consumed by the recall injection paths.

### 3. FTS5 Keyword Search Sidecar

**File: `src/probos/cognitive/episodic.py`**

Add an `aiosqlite`-backed FTS5 index alongside ChromaDB. This is a secondary index, not a replacement.

**Schema:**
```sql
CREATE VIRTUAL TABLE IF NOT EXISTS episode_fts USING fts5(
    episode_id UNINDEXED,
    content,
    tokenize='porter unicode61'
);
```

**Integration points:**
- **On `store()`:** After successful ChromaDB insert, also insert into FTS5: `INSERT INTO episode_fts(episode_id, content) VALUES (?, ?)` where content = `episode.user_input + " " + (episode.reflection or "")`.
- **On `_evict()`:** Delete from FTS5: `DELETE FROM episode_fts WHERE episode_id = ?`
- **On `seed()`:** Also populate FTS5 for warm boot.
- **New method `keyword_search()`:**
```python
async def keyword_search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
    """FTS5 keyword search. Returns [(episode_id, rank_score), ...]."""
```
  Uses `SELECT episode_id, rank FROM episode_fts WHERE episode_fts MATCH ? ORDER BY rank LIMIT ?`

**Database path:** `{data_dir}/episode_fts.db` (separate from ChromaDB persistence directory). Initialize in `start()`, close in `stop()`.

**Import:** `import aiosqlite` — already used elsewhere in ProbOS (trust, Hebbian, counselor, eviction audit).

### 4. Anchor-Aware Recall Formatting

**File: `src/probos/cognitive/cognitive_agent.py`**

Replace `_format_memory_section()` (currently lines 1697-1718) with anchor-aware formatting:

```python
def _format_memory_section(self, memories: list[dict]) -> list[str]:
    """Format recalled episodes with anchor context headers (AD-567b)."""
    lines = [
        "=== SHIP MEMORY (your experiences aboard this vessel) ===",
        "These are YOUR experiences. Do NOT confuse with training knowledge.",
        "Markers: [direct] = you experienced it, [secondhand] = you heard about it.",
        "[verified] = corroborated by ship's log, [unverified] = not yet corroborated.",
        "",
    ]
    for mem in memories:
        # Anchor header line
        anchor_parts = []
        if mem.get("age"):
            anchor_parts.append(f"{mem['age']} ago")
        if mem.get("anchor_channel"):
            anchor_parts.append(mem["anchor_channel"])
        if mem.get("anchor_department"):
            anchor_parts.append(f"{mem['anchor_department']} dept")
        if mem.get("anchor_participants"):
            anchor_parts.append(f"with {mem['anchor_participants']}")
        if mem.get("anchor_trigger"):
            anchor_parts.append(f"re: {mem['anchor_trigger']}")

        source = mem.get("source", "direct")
        verified = "verified" if mem.get("verified") else "unverified"
        header = f"  [{source} | {verified}]"
        if anchor_parts:
            header += f" [{' | '.join(anchor_parts)}]"

        lines.append(header)
        lines.append(f"    {mem.get('input', '') or mem.get('reflection', '')}")
    lines.append("")
    lines.append("=== END SHIP MEMORY ===")
    return lines
```

**Example rendered output:**
```
=== SHIP MEMORY (your experiences aboard this vessel) ===
These are YOUR experiences. Do NOT confuse with training knowledge.
Markers: [direct] = you experienced it, [secondhand] = you heard about it.
[verified] = corroborated by ship's log, [unverified] = not yet corroborated.

  [direct | verified] [2h 15m ago | ward_room #security | Security dept | with Worf, Atlas | re: trust_variance]
    Alert condition YELLOW — trust variance spike detected in security pool...
  [secondhand | unverified] [5h 30m ago | ward_room #bridge | with Meridian]
    Meridian proposed adjusting baseline threshold for new crew members...

=== END SHIP MEMORY ===
```

### 5. Memory Dict Enrichment (Anchor Fields)

**File: `src/probos/cognitive/cognitive_agent.py`**

Modify `_recall_relevant_memories()` to:
1. Use `recall_weighted()` instead of `recall_for_agent()` + `recent_for_agent()` fallback
2. Pass `trust_network` and `hebbian_router` from `self._runtime`
3. Pack anchor fields into the memory dict:

```python
for scored in scored_results:
    ep = scored.episode
    anchors = ep.anchors  # AnchorFrame | None
    mem = {
        "input": ep.user_input[:200] if ep.user_input else "",
        "reflection": ep.reflection[:200] if ep.reflection else "",
        "source": getattr(ep, 'source', 'direct'),
        "verified": False,  # AD-541 cross-check below
    }
    if include_ts and ep.timestamp > 0:
        mem["age"] = format_duration(time.time() - ep.timestamp)
    # Anchor context for formatting
    if anchors:
        mem["anchor_channel"] = anchors.channel or ""
        mem["anchor_department"] = anchors.department or ""
        mem["anchor_participants"] = ", ".join(anchors.participants) if anchors.participants else ""
        mem["anchor_trigger"] = anchors.trigger_type or ""
    # ... EventLog cross-verification as before ...
```

**File: `src/probos/proactive.py`**

Modify `_gather_context()` memory section to:
1. Use `recall_weighted()` instead of `recall_for_agent("recent activity", k=5)`
2. Derive the query from the agent's current duty/context instead of hardcoded `"recent activity"`:
   ```python
   duty = ...  # already available in the proactive loop
   query = f"{agent.agent_type} {duty.duty_type if duty else ''} recent duty observations"
   ```
3. Pack anchor fields into memory dicts (same pattern as conversational path)
4. Add `source` and `verified` fields (currently missing from proactive path — asymmetry fix)

### 6. SECONDHAND Source Wiring

**File: `src/probos/ward_room/threads.py`** and **`src/probos/ward_room/messages.py`**

The current Ward Room episode creation paths store episodes for the **author** of a post with `source="direct"`. This is correct — the author directly experienced writing the post.

The gap: there is NO episode created for **readers/observers** of Ward Room posts. When Agent B reads Agent A's thread post during perception, no secondhand episode is created for Agent B.

**Implementation approach:** Do NOT create reader-side episodes at read time (this would flood episodic memory). Instead, wire SECONDHAND at the point where an agent **acts on** information from another agent's Ward Room post.

In `cognitive_agent.py` `_store_action_episode()`:
- If the triggering intent is `ward_room_notification` (agent is responding to someone else's post), the resulting episode should be tagged `source=MemorySource.SECONDHAND` if the author is NOT the current agent.
- Check: does the intent come from a Ward Room post by a different agent? If `observation["params"].get("from")` != current agent's ID/callsign, set `source=MemorySource.SECONDHAND`.

In `proactive.py` episode creation paths (#5, #6):
- If the proactive thought was triggered by Ward Room content (the agent is thinking about another agent's post), tag as `SECONDHAND`. Check if `duty` or context indicates Ward Room origin.

**Keep it conservative:** Only tag SECONDHAND when there is clear evidence the episode derives from another agent's communication, not from the agent's own observations. When ambiguous, default to DIRECT (fail-safe for integrity).

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/probos/types.py` | Add `RecallScore` dataclass |
| `src/probos/config.py` | Add `recall_weights` and `recall_context_budget_chars` to `MemoryConfig` |
| `src/probos/cognitive/episodic.py` | `recall_weighted()`, `keyword_search()`, FTS5 sidecar init/teardown, modify `store()`/`_evict()`/`seed()` for FTS5 dual-write, `recall_for_agent()` optional score return |
| `src/probos/cognitive/cognitive_agent.py` | `_recall_relevant_memories()` → use `recall_weighted()` + anchor dict packing, `_format_memory_section()` → anchor headers, `_store_action_episode()` → SECONDHAND source |
| `src/probos/proactive.py` | `_gather_context()` → use `recall_weighted()` + dynamic query + anchor packing + source/verified |
| `src/probos/ward_room/threads.py` | No changes (author episodes stay DIRECT) |
| `src/probos/ward_room/messages.py` | No changes (author episodes stay DIRECT) |

## Files NOT to Modify

- `episodic.py` existing `recall_for_agent()`, `recent_for_agent()` — keep as-is, used by dream engine, clustering, spaced retrieval
- `dream_adapter.py` — episode creation anchors already set by AD-567a
- `ward_room/` episode creation — author episodes correctly use DIRECT
- Qualification tests — AD-567b doesn't change test infrastructure

---

## Test Requirements

**File: `tests/test_ad567b_anchor_recall.py`** (new)

1. **RecallScore computation** — verify composite score formula with known inputs
2. **Recency weight** — verify exponential decay (fresh episode ≈ 1.0, 1-week-old ≈ 0.37, 2-week-old ≈ 0.14)
3. **Anchor completeness** — 0/10 fields filled = 0.0, 5/10 = 0.5, 10/10 = 1.0, anchors=None = 0.0
4. **Budget enforcement** — verify `recall_weighted()` stops accumulating when context budget exceeded
5. **FTS5 dual-write** — store episode → keyword_search finds it
6. **FTS5 eviction** — evict episode → keyword_search no longer finds it
7. **FTS5 seed** — seed episodes → keyword_search finds them
8. **FTS5 + semantic merge** — episode found by keyword but not by vector still appears in `recall_weighted()` results
9. **Anchor-aware formatting** — `_format_memory_section()` renders anchor header with channel, department, participants, trigger
10. **Anchor-aware formatting — empty anchors** — graceful degradation when anchors=None (old episodes)
11. **SECONDHAND source** — episode from ward_room_notification by a different agent tagged SECONDHAND
12. **DIRECT source preserved** — episode from own action stays DIRECT
13. **Recall ordering** — higher composite score ranks first
14. **Config weights** — custom weights in MemoryConfig affect composite score
15. **Backwards compatibility** — `recall_for_agent()` still returns `list[Episode]` by default

---

## Tracking

Update PROGRESS.md, DECISIONS.md, roadmap.md on completion.

**DECISIONS.md entry:**
```
### AD-567b: Anchor-Aware Recall Formatting + Salience-Weighted Retrieval
- **Date:** [completion date]
- **Status:** COMPLETE
- **Absorbs:** AD-462a (Salience-Weighted Episodic Recall)
- **Decision:** Four-part recall upgrade: (1) salience-weighted re-ranking (Trust × Hebbian × Recency × Anchor composite), (2) FTS5 keyword search sidecar alongside ChromaDB vector search, (3) anchor context headers in recalled memory formatting, (4) SECONDHAND source wiring for Ward Room-derived episodes. Prior art: Tulving encoding specificity, CAST axis organization, RPMS confidence gating.
- **Rationale:** Raw ChromaDB cosine similarity is insufficient — all signals (trust, Hebbian, recency, anchor grounding) available but unused in recall ranking. Hardcoded "recent activity" query and fixed k=5 waste context budget. Agents couldn't distinguish own observations from secondhand reports. Anchor headers implement Tulving's encoding specificity — resurfacing storage-time context cues improves recall accuracy.
- **Deferred:** Anchor quality & integrity (AD-567c absorbs 567e), memory lifecycle/dream (AD-567d absorbs AD-462b), social memory (AD-567f absorbs AD-462d), recall depth & Oracle (AD-462c absorbs AD-462e), cognitive re-localization (AD-567g).
```

---

## Deferred Items (Consolidated)

| Prompt | Absorbs | Scope | Depends |
|--------|---------|-------|---------|
| **AD-567c** | AD-567c + AD-567e | **Anchor Quality & Integrity** — anchor confidence scoring (0.0–1.0 groundedness from filled dimensions) + SIF `check_anchor_integrity()` drift detection (verify anchors correspond to real ship events) + CAST per-agent anchor profiles + RPMS confidence gating threshold + Counselor diagnostics for low-confidence patterns + **drift classification** (distinguish healthy cognitive specialization from concerning drift using anchor confidence as discriminant: high-confidence divergence = adaptive specialization, low-confidence divergence = ungrounded drift; crew observation by Echo/Meridian 2026-04-03 thread 92719789) | AD-567b |
| **AD-567d** | AD-567d + AD-462b | **Memory Lifecycle (Dream)** — anchor-preserving dream consolidation (Steps 7a-7g carry forward contextual anchors when merging episodes) + ACT-R activation-based decay (`activation = ln(Sum t_j^(-d))`), low-activation episodes pruned during dreaming, high-activation promoted | AD-567b |
| **AD-567f** | AD-567f + AD-462d | **Social Memory** — social verification protocol ("does anyone remember?" Ward Room queries) + cross-agent episodic search + claim verification intents + corroboration scoring | AD-567b |
| **AD-462c** | AD-462c + AD-462e | **Recall Depth & Oracle** — trust-gated variable recall tiers (Basic=vector only for Ensigns, Enhanced=vector+FTS5 for trust 0.7+, Full=LLM-augmented for Chiefs+Bridge) + Oracle Service (Ship's Computer cross-tier retrieval across Episodes, Ship's Records, KnowledgeStore) | AD-567b, AD-567c |
| **AD-567g** | standalone | **Cognitive Re-Localization** — onboarding anchor-frame establishment exercises, O'Keefe cognitive map rebuilding during agent instantiation, ship topology as spatial memory scaffold | AD-567c, AD-567d |
