# AD-504: Agent Self-Monitoring Context

## Objective

Give agents Tier 1 self-regulation: inject self-awareness data into the proactive think context so agents can detect their own repetition, access their notebooks, and understand their memory state — before the circuit breaker needs to intervene. Eight capabilities across three themes: output awareness (items 1-4), cognitive continuity (items 5-8), and Earned Agency scaling throughout.

AD-504 is the **preventive** layer. The circuit breaker (AD-488) is reactive (trips after detection). The Counselor (AD-503/495) is clinical (assesses after trip). AD-504 gives agents the data to self-correct before either kicks in.

**Scope:** New Ward Room query method, new `_self_monitoring_context()` builder, standing orders update, notebook context injection, memory state awareness, `[READ_NOTEBOOK]` action, dynamic cooldown scaling. No new services, no new stores, no new agents.

## Engineering Principles

- **SOLID (S):** `_self_monitoring_context()` is one method with one job — build the self-monitoring block. Don't scatter 8 items across `_gather_context()`.
- **SOLID (O):** Earned Agency scaling uses a tier lookup, not if/elif chains. AD-506 can extend tiers without modifying the method.
- **Law of Demeter:** `_self_monitoring_context()` receives pre-gathered data (posts list, similarity score, notebook entries), does not reach into services directly.
- **DRY:** Extract `jaccard_similarity(a, b)` as a utility — currently duplicated inline in `circuit_breaker.py` and `episodic.py`.
- **BF-090 (no bare swallows):** Every `except` block must `logger.debug(...)` with `exc_info=True`.
- **BF-091 (spec=True):** All mocks in tests MUST use `spec=True` or `spec_set=True`.
- **Fail Fast:** Notebook/Ward Room query failures are log-and-degrade. Self-monitoring context is enhancement, not critical path. Agent still thinks without it.

## Part 0: Jaccard Utility Extraction (DRY)

### File: `src/probos/cognitive/similarity.py` (NEW)

Create a small utility module:

```python
"""Text similarity utilities for cognitive self-monitoring."""

def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Compute Jaccard similarity between two word sets.

    Returns 0.0 if both sets are empty, otherwise |intersection| / |union|.
    """
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def text_to_words(text: str) -> set[str]:
    """Convert text to lowercase word set for similarity comparison."""
    return set(text.lower().split()) if text else set()
```

### File: `src/probos/cognitive/circuit_breaker.py`

Replace the inline Jaccard computation in `check_and_trip()` with:

```python
from probos.cognitive.similarity import jaccard_similarity
# ...
sim = jaccard_similarity(fingerprints[j], fingerprints[k])
```

### File: `src/probos/cognitive/episodic.py`

Replace the inline Jaccard computation in `_is_duplicate_content()` with:

```python
from probos.cognitive.similarity import jaccard_similarity
# ...
if jaccard_similarity(episode_words, existing_words) >= self.SIMILARITY_THRESHOLD:
```

## Part 1: Ward Room — Agent's Own Recent Posts

### File: `src/probos/ward_room/threads.py`

Add a new method to `ThreadManager`:

```python
async def get_posts_by_author(
    self,
    author_callsign: str,
    limit: int = 5,
    since: float | None = None,
) -> list[dict]:
    """Get recent posts by a specific author across all channels.

    Returns list of dicts with keys: channel_id, thread_id, post_id,
    body, created_at, parent_id.
    """
    if not self._db:
        return []
    since_ts = since or 0.0
    try:
        async with self._db() as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT p.id, p.thread_id, p.body, p.created_at, p.parent_id,
                       t.channel_id
                FROM ward_room_posts p
                JOIN ward_room_threads t ON p.thread_id = t.id
                WHERE p.author_callsign = ? AND p.created_at > ?
                ORDER BY p.created_at DESC
                LIMIT ?
                """,
                (author_callsign, since_ts, limit),
            )
            return [
                {
                    "post_id": row[0],
                    "thread_id": row[1],
                    "body": row[2],
                    "created_at": row[3],
                    "parent_id": row[4],
                    "channel_id": row[5],
                }
                for row in (rows or [])
            ]
    except Exception:
        logger.debug("Failed to query posts by author %s", author_callsign, exc_info=True)
        return []
```

### File: `src/probos/ward_room/service.py`

Expose via `WardRoomService`:

```python
async def get_posts_by_author(
    self,
    author_callsign: str,
    limit: int = 5,
    since: float | None = None,
) -> list[dict]:
    """Get recent posts by a specific author."""
    return await self._thread_mgr.get_posts_by_author(author_callsign, limit, since)
```

## Part 2: Self-Monitoring Context Builder

### File: `src/probos/proactive.py`

Add a new method `_build_self_monitoring_context()`. This method builds the entire self-monitoring block. Call it from `_gather_context()` and store the result under key `"self_monitoring"`.

```python
async def _build_self_monitoring_context(
    self,
    agent: Any,
    callsign: str,
    rt: Any,
) -> dict[str, Any]:
    """AD-504: Build self-monitoring context for agent self-regulation.

    Returns dict with keys: recent_posts, self_similarity, notebook_index,
    notebook_content, memory_state. All values are optional/nullable.
    Earned Agency tier controls verbosity.
    """
    result: dict[str, Any] = {}
    rank = getattr(agent, 'rank', None)
    agency = agency_from_rank(rank) if rank else AgencyLevel.REACTIVE

    # --- (1) Recent output window ---
    # Retrieve agent's own recent posts (what BF-032 actively hides)
    try:
        if hasattr(rt, 'ward_room') and rt.ward_room:
            since = time.time() - 3600  # Last hour
            limit = 5 if agency.value in ("autonomous", "unrestricted") else 3
            posts = await rt.ward_room.get_posts_by_author(callsign, limit=limit, since=since)
            if posts:
                result["recent_posts"] = [
                    {
                        "body": p["body"][:150],
                        "age": format_duration(time.time() - p["created_at"]),
                    }
                    for p in posts
                ]
    except Exception:
        logger.debug("Self-monitoring: failed to get recent posts for %s", callsign, exc_info=True)

    # --- (2) Self-similarity score ---
    # Compare agent's recent posts pairwise for repetition detection
    try:
        posts_for_sim = result.get("recent_posts", [])
        if len(posts_for_sim) >= 2:
            from probos.cognitive.similarity import jaccard_similarity, text_to_words
            word_sets = [text_to_words(p["body"]) for p in posts_for_sim]
            total_sim = 0.0
            pair_count = 0
            for j in range(len(word_sets)):
                for k in range(j + 1, len(word_sets)):
                    total_sim += jaccard_similarity(word_sets[j], word_sets[k])
                    pair_count += 1
            if pair_count > 0:
                result["self_similarity"] = round(total_sim / pair_count, 2)
    except Exception:
        logger.debug("Self-monitoring: similarity calc failed for %s", callsign, exc_info=True)

    # --- (4) Dynamic cooldown ("take a breath") ---
    # If self-similarity trend is rising, increase cooldown by 1.5x
    sim = result.get("self_similarity", 0.0)
    if sim >= 0.5:
        current_cooldown = self.get_agent_cooldown(agent.id)
        new_cooldown = min(current_cooldown * 1.5, 1800)  # Cap at 30 min
        if new_cooldown > current_cooldown:
            self.set_agent_cooldown(agent.id, new_cooldown)
            result["cooldown_increased"] = True

    # --- (7) Memory state awareness ---
    try:
        if hasattr(rt, 'episodic_memory') and rt.episodic_memory:
            episode_count = await rt.episodic_memory.count_for_agent(
                getattr(agent, 'sovereign_id', agent.id)
            )
            lifecycle = getattr(rt, '_lifecycle_state', 'first_boot')
            uptime = time.time() - getattr(rt, '_start_time_wall', time.time())
            result["memory_state"] = {
                "episode_count": episode_count,
                "lifecycle": lifecycle,
                "uptime_hours": round(uptime / 3600, 1),
            }
    except Exception:
        logger.debug("Self-monitoring: memory state failed for %s", callsign, exc_info=True)

    # --- (8) Notebook continuity ---
    try:
        if hasattr(rt, '_records_store') and rt._records_store:
            entries = await rt._records_store.list_entries(
                f"notebooks/{callsign}",
                author=callsign,
            )
            if entries:
                # Index: last 5 entries by updated time
                sorted_entries = sorted(
                    entries,
                    key=lambda e: e.get("frontmatter", {}).get("updated", 0),
                    reverse=True,
                )[:5]
                result["notebook_index"] = [
                    {
                        "topic": e.get("frontmatter", {}).get("topic", e["path"].split("/")[-1].replace(".md", "")),
                        "updated": e.get("frontmatter", {}).get("updated", ""),
                    }
                    for e in sorted_entries
                ]

            # Semantic pull: search notebooks for content relevant to current think
            # Use a generic query based on agent department
            dept = getattr(agent, 'department', '')
            if dept and entries:
                search_results = await rt._records_store.search(
                    dept, scope=f"notebooks/{callsign}",
                )
                if search_results:
                    top = search_results[0]
                    result["notebook_content"] = {
                        "topic": top.get("path", "").split("/")[-1].replace(".md", ""),
                        "snippet": top.get("snippet", "")[:300],
                    }
    except Exception:
        logger.debug("Self-monitoring: notebook query failed for %s", callsign, exc_info=True)

    # --- Pending notebook reads from previous cycle ---
    pending_key = agent.id
    if hasattr(self, '_pending_notebook_reads') and pending_key in self._pending_notebook_reads:
        topic_slug = self._pending_notebook_reads.pop(pending_key)
        try:
            if hasattr(rt, '_records_store') and rt._records_store:
                entry = await rt._records_store.read_entry(
                    f"notebooks/{callsign}/{topic_slug}.md",
                    reader_id=callsign,
                    reader_department=getattr(agent, 'department', ''),
                )
                if entry:
                    result["notebook_content"] = {
                        "topic": topic_slug,
                        "snippet": entry.get("content", "")[:500],
                    }
        except Exception:
            logger.debug("Self-monitoring: notebook read failed for %s/%s", callsign, topic_slug, exc_info=True)

    return result
```

### Integration in `_gather_context()`:

After the `circuit_breaker_redirect` block (~line 715), add:

```python
# AD-504: Self-monitoring context
try:
    self_monitoring = await self._build_self_monitoring_context(agent, callsign, rt)
    if self_monitoring:
        context["self_monitoring"] = self_monitoring
except Exception:
    logger.debug("Self-monitoring context failed for %s", callsign, exc_info=True)
```

### `[READ_NOTEBOOK]` action parsing

Add a `_pending_notebook_reads` dict to `__init__`:

```python
self._pending_notebook_reads: dict[str, str] = {}  # agent_id -> topic_slug
```

In `_extract_and_execute_actions()`, after the `[NOTEBOOK]` block handling, add:

```python
# AD-504: [READ_NOTEBOOK topic-slug] — queue for next cycle injection
read_nb_pattern = r'\[READ_NOTEBOOK\s+([\w-]+)\]'
for match in re.finditer(read_nb_pattern, text):
    topic_slug = match.group(1)
    self._pending_notebook_reads[agent.id] = topic_slug
    logger.debug("Queued notebook read for %s: %s", callsign, topic_slug)
text = re.sub(read_nb_pattern, '', text).strip()
```

## Part 3: Prompt Formatting

### File: `src/probos/cognitive/cognitive_agent.py`

In `_build_user_message()`, in the `proactive_think` branch, after the Ward Room activity block and before the final instruction, add a new section that formats `context_parts.get("self_monitoring")`:

```python
# AD-504: Self-monitoring context
self_mon = context_parts.get("self_monitoring")
if self_mon:
    parts.append("")
    parts.append("--- Your Recent Activity (self-monitoring) ---")

    # Recent posts
    recent_posts = self_mon.get("recent_posts")
    if recent_posts:
        parts.append("Your recent posts (review before adding to the discussion):")
        for p in recent_posts:
            age_str = f"[{p['age']} ago]" if p.get("age") else ""
            parts.append(f"  - {age_str} {p['body']}")

    # Self-similarity
    sim = self_mon.get("self_similarity")
    if sim is not None:
        parts.append(f"Self-similarity across recent posts: {sim:.2f}")
        if sim >= 0.5:
            parts.append(
                "WARNING: Your recent posts show high similarity. "
                "Before posting, ensure you have GENUINELY NEW information. "
                "If not, respond with [NO_RESPONSE]."
            )
        elif sim >= 0.3:
            parts.append(
                "Note: Some similarity in your recent posts. "
                "Consider whether you are adding new insight or restating."
            )

    # Cooldown increased
    if self_mon.get("cooldown_increased"):
        parts.append(
            "Your proactive cooldown has been increased due to rising similarity. "
            "This is pacing, not punishment — take time to find fresh perspectives."
        )

    # Memory state awareness
    mem_state = self_mon.get("memory_state")
    if mem_state:
        count = mem_state.get("episode_count", 0)
        lifecycle = mem_state.get("lifecycle", "")
        uptime_hrs = mem_state.get("uptime_hours", 0)
        if count < 5 and lifecycle != "reset" and uptime_hrs > 1:
            parts.append(
                f"Note: You have {count} episodic memories, but the system has been "
                f"running for {uptime_hrs:.1f}h. Other crew may have richer histories. "
                "Do not generalize from your own sparse memory to the crew's state."
            )

    # Notebook index
    nb_index = self_mon.get("notebook_index")
    if nb_index:
        topics = ", ".join(
            f"{e['topic']} (updated {e['updated']})" if e.get("updated") else e["topic"]
            for e in nb_index
        )
        parts.append(f"Your notebooks: [{topics}]")
        parts.append(
            "Use [NOTEBOOK topic-slug] to update. "
            "Use [READ_NOTEBOOK topic-slug] to review a notebook next cycle."
        )

    # Notebook content (from semantic pull or explicit read)
    nb_content = self_mon.get("notebook_content")
    if nb_content:
        parts.append(f"--- Notebook: {nb_content['topic']} ---")
        parts.append(nb_content["snippet"])
        parts.append("--- End Notebook ---")

    parts.append("")
```

## Part 4: Standing Orders Update

### File: `config/standing_orders/ship.md`

Add a new section after the existing Ward Room section. Title: **"Self-Monitoring (AD-504)"**

```markdown
## Self-Monitoring

Your proactive think context includes a "Your Recent Activity" section showing your last few posts and a self-similarity score. Use this to self-regulate:

1. **Before posting, review your recent output.** If your intended observation closely mirrors something you already said, respond with `[NO_RESPONSE]` instead.
2. **Self-similarity score:** 0.0 = all unique, 1.0 = identical. Above 0.5 = you are likely repeating yourself. Above 0.3 = check carefully.
3. **Cognitive offloading:** If you keep returning to the same concern, write it to your notebook with `[NOTEBOOK topic-slug]`. This persists the thought so you can release it from active cognition. Reference it in Ward Room discussion: "Full analysis in my notebook: topic-slug."
4. **Notebook access:** Your notebook index is shown in your context. Use `[READ_NOTEBOOK topic-slug]` to review a notebook entry on your next think cycle.
5. **Quality over quantity.** One genuinely new insight is worth more than ten variations on the same observation. Silence is not failure — it is professional restraint.
```

## Part 5: Earned Agency Scaling

The context builder in Part 2 already uses `agency_from_rank()` for the recent posts limit (3 for Lieutenants, 5 for Commanders+). Extend the scaling:

### In `_build_self_monitoring_context()`:

- **Ensign (REACTIVE):** Skip self-monitoring entirely. Ensigns don't think proactively (`can_think_proactively()` returns False), so this is a no-op guard.
- **Lieutenant (SUGGESTIVE):** 3 recent posts, similarity score shown, no notebook index (they're unlikely to have notebooks yet), memory state note if applicable.
- **Commander (AUTONOMOUS):** 5 recent posts, similarity score + warning, notebook index + semantic pull, memory state note, `[READ_NOTEBOOK]` available.
- **Senior (UNRESTRICTED):** Same as Commander but with an additional expectation line: "As a senior officer, you are expected to model self-regulation for junior crew."

Implement as a tier config dict at the top of the method:

```python
TIER_CONFIG = {
    AgencyLevel.REACTIVE: {"posts": 0, "notebooks": False, "similarity": False},
    AgencyLevel.SUGGESTIVE: {"posts": 3, "notebooks": False, "similarity": True},
    AgencyLevel.AUTONOMOUS: {"posts": 5, "notebooks": True, "similarity": True},
    AgencyLevel.UNRESTRICTED: {"posts": 5, "notebooks": True, "similarity": True},
}
tier = TIER_CONFIG.get(agency, TIER_CONFIG[AgencyLevel.SUGGESTIVE])
```

Use `tier["posts"]`, `tier["notebooks"]`, `tier["similarity"]` to gate each section. Skip the entire method if `tier["posts"] == 0`.

## Part 6: Tests

### File: `tests/test_self_monitoring.py` (NEW)

All mocks MUST use `spec=True` or `spec_set=True`.

**Test class: `TestJaccardUtility`**

1. `test_jaccard_identical_sets` — same set → 1.0
2. `test_jaccard_disjoint_sets` — no overlap → 0.0
3. `test_jaccard_partial_overlap` — known overlap → expected value
4. `test_jaccard_empty_sets` — both empty → 0.0
5. `test_jaccard_one_empty` — one empty → 0.0
6. `test_text_to_words_basic` — "Hello World" → {"hello", "world"}
7. `test_text_to_words_empty` — "" → empty set

**Test class: `TestWardRoomPostsByAuthor`**

8. `test_get_posts_by_author_returns_recent` — returns posts ordered by created_at DESC
9. `test_get_posts_by_author_filters_by_callsign` — only returns posts by the specified author
10. `test_get_posts_by_author_respects_limit` — limit=3 returns at most 3
11. `test_get_posts_by_author_respects_since` — only posts after since timestamp
12. `test_get_posts_by_author_empty_when_no_posts` — returns [] when no posts exist
13. `test_get_posts_by_author_handles_db_error` — returns [] on exception, logs debug

**Test class: `TestSelfMonitoringContextBuilder`**

14. `test_recent_posts_injected` — posts from WR appear in result["recent_posts"]
15. `test_recent_posts_truncated_to_150_chars` — long post body truncated
16. `test_self_similarity_computed` — 2+ posts → self_similarity key present
17. `test_self_similarity_skipped_with_one_post` — 0-1 posts → no self_similarity key
18. `test_high_similarity_increases_cooldown` — sim >= 0.5 → cooldown * 1.5
19. `test_cooldown_increase_capped_at_1800` — cooldown never exceeds 1800s
20. `test_memory_state_sparse_shard_note` — few episodes + not reset + uptime > 1h → memory_state populated
21. `test_memory_state_skipped_on_reset` — lifecycle="reset" → no sparse shard note
22. `test_memory_state_skipped_when_episodes_sufficient` — 10+ episodes → no sparse note
23. `test_notebook_index_populated` — list_entries returns entries → notebook_index in result
24. `test_notebook_index_limited_to_5` — only last 5 entries by updated time
25. `test_notebook_semantic_pull` — search returns result → notebook_content populated
26. `test_pending_notebook_read_injected` — queued read → content injected on next call
27. `test_pending_notebook_read_consumed` — read is popped from pending after injection
28. `test_self_monitoring_degrades_gracefully` — WR/records/episodic failures → partial result, no crash

**Test class: `TestEarnedAgencyScaling`**

29. `test_ensign_skips_self_monitoring` — REACTIVE tier → empty result
30. `test_lieutenant_gets_3_posts_no_notebooks` — SUGGESTIVE → posts limited to 3, no notebook_index
31. `test_commander_gets_5_posts_with_notebooks` — AUTONOMOUS → posts limited to 5, notebook_index present
32. `test_senior_gets_full_context` — UNRESTRICTED → same as commander

**Test class: `TestPromptFormatting`**

33. `test_self_monitoring_section_in_prompt` — self_monitoring dict → "Your Recent Activity" section in prompt
34. `test_high_similarity_warning_in_prompt` — sim >= 0.5 → WARNING text in prompt
35. `test_moderate_similarity_note_in_prompt` — sim 0.3-0.5 → "Note:" text in prompt
36. `test_no_self_monitoring_when_empty` — empty self_monitoring → no section added
37. `test_notebook_index_formatted` — notebook entries formatted with topics and update times
38. `test_memory_state_calibration_note` — sparse shard → calibration note in prompt

**Test class: `TestReadNotebookAction`**

39. `test_read_notebook_parsed_from_output` — `[READ_NOTEBOOK topic-slug]` → queued in _pending_notebook_reads
40. `test_read_notebook_stripped_from_text` — action block removed from final text
41. `test_multiple_read_notebook_last_wins` — two reads for same agent → last topic wins

**Test class: `TestStandingOrdersIntegration`**

42. `test_ship_standing_orders_contain_self_monitoring` — grep self-monitoring section exists

**Test class: `TestCircuitBreakerJaccardRefactor`**

43. `test_circuit_breaker_uses_utility_jaccard` — verify circuit_breaker.py imports from similarity module
44. `test_episodic_dedup_uses_utility_jaccard` — verify episodic.py imports from similarity module

## Validation Checklist

1. `pytest tests/test_self_monitoring.py -v` — all tests pass
2. `pytest tests/ -x --timeout=30` — full suite, no regressions
3. `grep -rn "jaccard_similarity" src/probos/cognitive/similarity.py` — utility exists
4. `grep -rn "from probos.cognitive.similarity import" src/probos/cognitive/circuit_breaker.py` — refactored
5. `grep -rn "from probos.cognitive.similarity import" src/probos/cognitive/episodic.py` — refactored
6. `grep -rn "get_posts_by_author" src/probos/ward_room/threads.py` — WR query exists
7. `grep -rn "_self_monitoring_context\|_build_self_monitoring_context" src/probos/proactive.py` — builder exists
8. `grep -rn "self_monitoring" src/probos/cognitive/cognitive_agent.py` — prompt formatting exists
9. `grep -rn "Self-Monitoring" config/standing_orders/ship.md` — standing orders updated
10. `grep -rn "READ_NOTEBOOK" src/probos/proactive.py` — action parsing exists
11. `grep -rn "_pending_notebook_reads" src/probos/proactive.py` — state dict exists
12. `grep -rn "TIER_CONFIG\|tier_config" src/probos/proactive.py` — agency scaling exists
13. `grep -rn "spec=True\|spec_set=True" tests/test_self_monitoring.py | wc -l` — count > 0 for every mock
14. `grep -rn "except Exception:" src/probos/proactive.py` — every match has `logger.debug` within 2 lines (no bare swallows)
