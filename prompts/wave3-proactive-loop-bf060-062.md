# Wave 3: Proactive Loop Quality — BF-060 / BF-061 / BF-062

**Priority:** Medium (all three)
**Scope:** `proactive.py` primarily
**Files to modify:** 1 source file, 1 test file (new)
**Estimated tests:** 8–10

## Context

Instance 5 overnight run revealed three proactive loop issues that degrade Ward Room signal quality:

1. **BF-060:** `[NOTEBOOK]` content leaks into Ward Room posts
2. **BF-061:** `[REPLY thread:...]` tag fails to match — wrong format, rank gate too restrictive
3. **BF-062:** Near-identical posts aren't caught by similarity gate

All three are in `src/probos/proactive.py`. The extraction/stripping pipeline works correctly for DMs and endorsements — these three are the gaps.

---

## BF-060: Notebook content leaks into Ward Room posts

**Root cause:** The notebook stripping at line 821 uses `text.replace()` with the captured `notebook_content` — but `re.findall()` strips leading/trailing whitespace from the captured group (line 795: `notebook_content = notebook_content.strip()`). The stripped version no longer matches the original text in the `[NOTEBOOK]...[/NOTEBOOK]` block, so `text.replace()` finds nothing and the tag survives.

**Evidence:** Atlas's notebook was correctly extracted (no leak). Cora, Minerva, and Pascal all had leaks. The difference is likely whitespace — some notebook blocks have leading newlines that cause the stripped content to diverge from the original.

**Fix:** Replace the `text.replace()` approach with `re.sub()` using the same pattern. After extracting all notebook entries, strip ALL matching `[NOTEBOOK ...]...[/NOTEBOOK]` blocks from the text using the regex:

At line 791–821, change the stripping approach:

```python
# --- Notebook writes (AD-434) ---
notebook_pattern = r'\[NOTEBOOK\s+([\w-]+)\](.*?)\[/NOTEBOOK\]'
notebook_matches = re.findall(notebook_pattern, text, re.DOTALL)
for topic_slug, notebook_content in notebook_matches:
    notebook_content = notebook_content.strip()
    if not notebook_content or not self._runtime._records_store:
        continue
    try:
        callsign = agent.callsign if hasattr(agent, 'callsign') else agent.agent_type
        department = ""
        if self._runtime.ontology:
            dept = self._runtime.ontology.get_agent_department(agent.agent_type)
            if dept:
                department = dept.department_id if hasattr(dept, 'department_id') else str(dept)
        await self._runtime._records_store.write_notebook(
            callsign=callsign,
            topic_slug=topic_slug,
            content=notebook_content,
            department=department,
            tags=[topic_slug],
        )
        actions_executed.append({
            "type": "notebook_write",
            "topic": topic_slug,
            "callsign": callsign,
        })
        logger.info("Notebook entry written: %s/%s", callsign, topic_slug)
    except Exception as e:
        logger.warning("Notebook write failed for %s: %s", topic_slug, e)

# Strip ALL notebook blocks from text using regex (not string replace)
text = re.sub(notebook_pattern, '', text, flags=re.DOTALL).strip()
```

The key change: replace the per-match `text.replace(...)` inside the loop (line 821) with a single `re.sub()` AFTER the loop. This guarantees all `[NOTEBOOK]` blocks are removed regardless of whitespace differences.

---

## BF-061: Reply tag format mismatch + rank gate too restrictive

**Two sub-issues:**

### A. Pattern mismatch

The reply extraction pattern at line 838 is:
```python
r'\[REPLY\s+(\S+)\]\s*\n(.*?)\n\[/REPLY\]'
```

This expects `[REPLY thread_id]\n...\n[/REPLY]` — the body MUST start on a new line after the tag.

But Minerva wrote: `[REPLY thread:65a0cf3e]\n...\n[/REPLY]`

The `thread:` prefix is fine — `(\S+)` captures it. But two issues:
1. The `thread:` prefix means the captured thread_id is `thread:65a0cf3e` not `65a0cf3e`. The lookup at line 850 (`get_thread(thread_id)`) will fail because the actual thread ID in the DB is the full UUID, not a prefix with `thread:`.
2. Agents may also write `[REPLY thread_id]Content without newline[/REPLY]` — the `\s*\n` requires a newline between tag and body.

**Fix:** Make the pattern more flexible:

```python
pattern = re.compile(
    r'\[REPLY\s+(?:thread:?\s*)?(\S+)\]\s*(.*?)\s*\[/REPLY\]',
    re.DOTALL | re.IGNORECASE,
)
```

Changes:
- `(?:thread:?\s*)?` — optionally strip `thread:` or `thread ` prefix
- `\s*` instead of `\s*\n` — allow body to start on same line or next line
- Added `\s*` before `[/REPLY]` for trailing whitespace

Also: the thread ID captured may be a partial UUID (agents see truncated IDs in activity feeds). Add a prefix-match lookup: if `get_thread(thread_id)` returns None and `thread_id` looks like a partial ID (< 36 chars), search recent threads for a matching prefix. Add a helper:

```python
async def _resolve_thread_id(self, thread_id: str) -> str | None:
    """Resolve a full or partial thread ID to an actual thread ID."""
    rt = self._runtime
    # Try exact match first
    thread = await rt.ward_room.get_thread(thread_id)
    if thread:
        return thread_id
    # Try prefix match on recent threads across channels
    if len(thread_id) < 36:
        channels = await rt.ward_room.list_channels()
        for ch in channels:
            try:
                activity = await rt.ward_room.get_recent_activity(ch.id, limit=20, since=None)
                for item in activity:
                    tid = item.get("thread_id", "") or item.get("id", "")
                    if tid and tid.startswith(thread_id):
                        return tid
            except Exception:
                continue
    return None
```

Use this in `_extract_and_execute_replies` at line 848–853:

```python
# Resolve thread ID (may be partial or prefixed)
resolved_id = await self._resolve_thread_id(thread_id)
if not resolved_id:
    logger.debug("AD-437: Reply target thread %s not found", thread_id)
    continue
thread_id = resolved_id
thread = await rt.ward_room.get_thread(thread_id)
```

### B. Rank gate too restrictive

Line 774: `if rank in (Rank.COMMANDER, Rank.SENIOR):` — replies are Commander+ only.

On a fresh instance, all crew start as Lieutenants (trust 0.5). **No one can reply.** This means cross-thread conversation is impossible until agents earn Commander rank, which takes many duty cycles.

**Fix:** Lower reply gate to Lieutenant (same as endorsements):

```python
# --- Replies (Lieutenant+) ---
if rank.value != Rank.ENSIGN.value:
    text, reply_actions = await self._extract_and_execute_replies(
        agent, text
    )
    actions_executed.extend(reply_actions)
```

---

## BF-062: Repetitive proactive thoughts not caught by similarity gate

**Root cause:** The existing similarity check `_is_similar_to_recent_posts()` (line 563) uses Jaccard similarity with a 0.5 threshold, checking only the last 3 posts. Two problems:

1. **Threshold too low for semantic near-duplicates.** Minerva's 5 posts about "establish cognitive baselines" use different wording each time — Jaccard on individual words may score below 0.5 even though the semantic content is identical.
2. **Only checks 3 posts.** With 8-hour overnight runs at 2-hour proactive intervals, there are ~4 cycles. Checking only 3 posts means the 5th post doesn't see the 1st.

**Fix:** Two improvements:

### A. Increase recent post window
Change line 600 from `agent_posts[:3]` to `agent_posts[:10]`:

```python
for post in agent_posts[:10]:  # Check last 10 posts (was 3)
```

### B. Add bigram similarity as a second check
Jaccard on individual words misses paraphrases. Adding bigram (2-word) overlap catches "establish cognitive baselines" ≈ "establishing baseline cognitive profiles" because they share bigrams like "cognitive baseline", "establish baseline", etc.

After the existing word-level Jaccard check (lines 598–608), add a bigram check:

```python
# Jaccard similarity on word sets
new_words = set(text.lower().split())
for post in agent_posts[:10]:  # Check last 10 posts
    old_words = set(post.lower().split())
    if not new_words or not old_words:
        continue
    intersection = new_words & old_words
    union = new_words | old_words
    similarity = len(intersection) / len(union) if union else 0.0
    if similarity >= threshold:
        return True

    # BF-062: Bigram similarity catches paraphrased near-duplicates
    new_bigrams = set(zip(text.lower().split(), text.lower().split()[1:]))
    old_bigrams = set(zip(post.lower().split(), post.lower().split()[1:]))
    if new_bigrams and old_bigrams:
        bi_intersection = new_bigrams & old_bigrams
        bi_union = new_bigrams | old_bigrams
        bi_similarity = len(bi_intersection) / len(bi_union) if bi_union else 0.0
        if bi_similarity >= threshold:
            return True
```

This gives two chances to catch duplicates: word-level AND bigram-level. The same 0.5 threshold works for both since bigram overlap is naturally more selective.

---

## Tests

Create `tests/test_proactive_quality.py`:

### BF-060 tests:

1. **test_notebook_stripped_from_ward_room_text** — Input text with `[NOTEBOOK slug]\ncontent\n[/NOTEBOOK]` embedded. After `_extract_and_execute_actions`, verify the returned text does NOT contain `[NOTEBOOK` or `[/NOTEBOOK]`.

2. **test_notebook_stripped_with_leading_whitespace** — Input text with `[NOTEBOOK slug]\n\n  content with leading whitespace\n\n[/NOTEBOOK]`. Verify stripping works even with whitespace differences.

3. **test_notebook_content_still_saved** — Verify the notebook content IS written to records_store even after stripping from Ward Room text.

### BF-061 tests:

4. **test_reply_pattern_matches_thread_prefix** — Input `[REPLY thread:abc123]\nReply body\n[/REPLY]`. Verify pattern captures `abc123` (not `thread:abc123`).

5. **test_reply_pattern_matches_no_newline** — Input `[REPLY abc123]Reply body[/REPLY]`. Verify pattern matches when body is on same line.

6. **test_reply_lieutenant_can_reply** — Mock agent with Lieutenant rank. Verify replies are extracted and executed (not gated to Commander+).

7. **test_reply_partial_thread_id_resolved** — Mock ward_room with thread ID `65a0cf3e-1234-5678-abcd-ef0123456789`. Input `[REPLY thread:65a0cf3e]`. Verify prefix match resolves to full UUID.

### BF-062 tests:

8. **test_similar_post_bigram_catches_paraphrase** — Create two texts with same semantic content but different word order. Verify bigram similarity correctly flags them as similar.

9. **test_similar_post_checks_ten_posts** — Mock 10 previous posts. Post #1 is similar to new post. Verify `_is_similar_to_recent_posts` returns True (old limit of 3 would have missed it).

10. **test_dissimilar_post_passes** — Two genuinely different posts. Verify they pass both word and bigram checks.

---

## Verification

After building, manually verify on a running ProbOS instance:

1. **BF-060:** Wait for a proactive cycle with `[NOTEBOOK]` output. Check Ward Room — should show observation text only, no `[NOTEBOOK]` markup. Check Ship's Records — notebook entry should still be saved.
2. **BF-061:** Watch for any `[REPLY]` attempts in logs. If an agent tries to reply, verify it posts as an actual reply (reply_count > 0 on target thread) rather than a new thread.
3. **BF-062:** Monitor overnight — agents should not post near-identical observations across multiple cycles.

## Important

- Do NOT modify `ward_room.py`, `runtime.py`, or any frontend files
- Do NOT change the `_extract_and_execute_dms` logic — DMs are working correctly
- Do NOT change the endorsement extraction — it works correctly
- Do NOT change the proposal extraction — it works correctly
- Keep the existing Jaccard word-level check — add bigram as a SECOND check, don't replace
- Run targeted tests: `python -m pytest tests/test_proactive_quality.py -x -v`
