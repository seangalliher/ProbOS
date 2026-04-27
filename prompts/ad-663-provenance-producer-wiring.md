# AD-663: Provenance Producer Wiring

**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-662 (Corroboration Source Provenance — COMPLETE, consumer-side infrastructure)
**Unlocks:** AD-665 (Corroboration Source Validation — consumer-side graded scoring, currently production no-op because provenance fields are empty)
**Files:** `src/probos/ward_room/messages.py` (EDIT), `src/probos/ward_room/threads.py` (EDIT), `src/probos/proactive.py` (EDIT), `src/probos/cognitive/cognitive_agent.py` (EDIT), `src/probos/cognitive/dreaming.py` (EDIT), `tests/test_ad663_provenance_producers.py` (NEW)

## Problem

AD-662 added three provenance fields to `AnchorFrame` — `source_origin_id`, `artifact_version`, `anomaly_window_id` — and consumer-side validation logic (`_share_artifact_ancestry()`, `_in_anomaly_window()`, anomaly discount scoring). AD-665 adds graded version-aware scoring.

**Neither works yet.** All three fields default to empty string (`""`), and no producer populates them. Every episode stored today has empty provenance. The consumer-side checks (`_share_artifact_ancestry()` returns `False` when either origin is empty; `_in_anomaly_window()` returns `False` when `anomaly_window_id` is empty) are correct but inert.

This AD wires the **producer side** — the 5 highest-corroboration-risk episode construction sites — to populate `source_origin_id` and `artifact_version` at AnchorFrame creation time.

**Failure mode this prevents (BF-226/227):** During queue pressure, multiple agents observe the same Ward Room post independently (different duty cycles, different channels, >60s apart). Their observations pass all spatiotemporal independence checks but share corrupted ancestry — the corroboration is circular. With provenance populated, `_share_artifact_ancestry()` detects the shared `source_origin_id` and vetoes false independence.

### Scope

**In scope (5 producers, 2 fields):**
- Ward Room reply episodes (`messages.py:320`)
- Ward Room thread creation episodes (`threads.py:565`)
- Proactive thought episodes (`proactive.py:988`)
- Cognitive agent action episodes (`cognitive_agent.py:4954`)
- Dream consolidation reflection episodes (`dreaming.py:2340`)

**Explicitly out of scope:**
- `anomaly_window_id` — No automated anomaly window detection infrastructure exists. The alert condition system (GREEN/YELLOW/RED) is manual and operational. Building an anomaly detector is a separate AD. All producers set `anomaly_window_id=""` (existing behavior). **Track as future AD.**
- Proactive no-response episodes (`proactive.py:753`) — Low corroboration risk; "[NO_RESPONSE]" episodes are rarely corroborated. Leave provenance empty.
- Peer repetition episodes (`messages.py:358`, `threads.py:604`) — System-generated secondary episodes, not direct observations. Leave provenance empty.
- Feedback episodes (`feedback.py:218, 379`) — Captain-originated, single-source. No shared-ancestry risk.
- Smoke test episodes (`runtime.py:3267`) — SystemQA-originated, single-source.
- DM/session episodes (`session.py:149`, `agents.py:312`) — Captain-to-agent 1:1, single-source.
- DAG execution episodes (`runtime.py:2520`, `renderer.py:414`) — Minimal anchors today; provenance wiring deferred until DAG episodes carry richer context.
- Metadata field promotion — Provenance fields are serialized inside `anchors_json` (via `dataclasses.asdict()`). No need to promote `source_origin_id` or `artifact_version` as individual ChromaDB metadata keys — the consumer (`social_verification.py`) reads them from the deserialized `AnchorFrame`, not from raw metadata queries.

### Design Principles

1. **Deterministic provenance.** `source_origin_id` identifies the root data artifact; `artifact_version` fingerprints its content at observation time. Both are deterministic — same input always produces the same ID/version.
2. **No new dependencies.** Uses only `hashlib` (stdlib). No new config fields. No new modules.
3. **Fail-safe degradation.** If provenance computation fails at any producer site, the episode is still stored with empty provenance fields (existing behavior). Log at debug level. Never fail the episode store because of provenance.
4. **Frozen dataclass construction.** `AnchorFrame` is frozen — provenance fields are set at construction time, not mutated afterward. Each producer adds the fields to its existing `AnchorFrame(...)` constructor call.
5. **No behavioral change for existing episodes.** Episodes already stored have empty provenance. Consumer-side logic (`_share_artifact_ancestry`) handles empty fields correctly (returns `False`). No migration needed.

---

## Section 1: Ward Room Reply Episodes

**File:** `src/probos/ward_room/messages.py` (EDIT)

At the reply episode construction site (find the `AnchorFrame(` inside the `if self._episodic_memory and author_id:` block that stores reply episodes, where `trigger_type="ward_room_reply"`):

**Current AnchorFrame construction:**
```python
                    anchors=AnchorFrame(
                        channel="ward_room",
                        channel_id=channel_name,
                        thread_id=thread_id,
                        trigger_type="ward_room_reply",
                        participants=[author_callsign or author_id],
                        trigger_agent=author_callsign or author_id,
                        department=self._resolve_author_department(author_id),
                        source_timestamp=post.created_at,  # AD-577
                    ),
```

**Add two provenance fields:**
```python
                    anchors=AnchorFrame(
                        channel="ward_room",
                        channel_id=channel_name,
                        thread_id=thread_id,
                        trigger_type="ward_room_reply",
                        participants=[author_callsign or author_id],
                        trigger_agent=author_callsign or author_id,
                        department=self._resolve_author_department(author_id),
                        source_timestamp=post.created_at,  # AD-577
                        # AD-663: Provenance — the WR post is the root artifact
                        source_origin_id=f"wr-post:{post.id}",
                        artifact_version=hashlib.sha256(
                            (post.body or "").encode("utf-8")
                        ).hexdigest()[:16],
                    ),
```

**Add import** at the module top of `messages.py` (if not already present):
```python
import hashlib
```

**Builder:** Verify `hashlib` is not already imported. If it is, skip the import addition.

**Rationale:**
- `source_origin_id = f"wr-post:{post.id}"` — The WR post UUID is the root artifact. The `wr-post:` prefix prevents ID collisions across artifact types (a thread ID could theoretically equal a post ID).
- `artifact_version` — SHA-256 of the post body, truncated to 16 hex chars. Two agents observing the same post get the same version. If the post is edited (`edit_post()`), later observers get a different version. 16 hex chars = 64 bits of collision resistance, sufficient for per-instance uniqueness.

---

## Section 2: Ward Room Thread Creation Episodes

**File:** `src/probos/ward_room/threads.py` (EDIT)

At the thread creation episode construction site (find the `AnchorFrame(` inside the `if self._episodic_memory and author_id:` block that stores thread episodes, where `trigger_type="ward_room_post"`):

**Current AnchorFrame construction:**
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

**Add two provenance fields:**
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
                        # AD-663: Provenance — the thread is the root artifact
                        source_origin_id=f"wr-thread:{thread.id}",
                        artifact_version=hashlib.sha256(
                            (title or "").encode("utf-8")
                        ).hexdigest()[:16],
                    ),
```

**Add import** at the module top of `threads.py` (if not already present):
```python
import hashlib
```

**Rationale:**
- `source_origin_id = f"wr-thread:{thread.id}"` — Thread ID as root artifact, `wr-thread:` prefix for type disambiguation.
- `artifact_version` — SHA-256 of the thread title. Thread titles are the initial observation content; the body is the opening post (stored as a separate reply with its own post ID).

---

## Section 3: Proactive Thought Episodes

**File:** `src/probos/proactive.py` (EDIT)

At the proactive thought episode construction site (find the `AnchorFrame(` inside the `else:` branch where the agent reports a substantive observation, where `trigger_type="duty_cycle"` or `"proactive_think"`). This is the block that already has `source_timestamp=_earliest_source_ts`.

**Design decision:** Proactive agents observe Ward Room activity. Their `context` dict includes `ward_room_activity` — a list of recent WR posts. The `source_origin_id` should identify the primary WR content that triggered the observation. Since multiple posts may contribute, use a composite fingerprint.

**Add provenance computation BEFORE the Episode construction** (after the `_earliest_source_ts` computation, before the `episode = Episode(` line):

```python
                # AD-663: Provenance — identify observed WR content
                _wr_origin = ""
                _wr_version = ""
                if _wr_activity:
                    # Primary origin: first WR post ID in the activity window
                    _first_post_id = _wr_activity[0].get("post_id", "") if _wr_activity else ""
                    if _first_post_id:
                        _wr_origin = f"wr-post:{_first_post_id}"
                    # Version: hash of all observed post IDs (composite fingerprint)
                    _post_ids = sorted(
                        a.get("post_id", "") for a in _wr_activity if a.get("post_id")
                    )
                    if _post_ids:
                        _wr_version = hashlib.sha256(
                            "|".join(_post_ids).encode("utf-8")
                        ).hexdigest()[:16]
```

**Then add the fields to the AnchorFrame constructor:**
```python
                    anchors=AnchorFrame(
                        channel="duty_report",
                        duty_cycle_id=duty.duty_id if duty else "",
                        department=_dept,
                        trigger_type="duty_cycle" if duty else "proactive_think",
                        watch_section=derive_watch_section(),
                        event_log_window=float(len(rt.event_log.recent(seconds=60))) if hasattr(rt, 'event_log') and hasattr(rt.event_log, 'recent') else 0.0,
                        source_timestamp=_earliest_source_ts,  # AD-577
                        # AD-663: Provenance
                        source_origin_id=_wr_origin,
                        artifact_version=_wr_version,
                    ),
```

**Add import** at the module top of `proactive.py` (if not already present):
```python
import hashlib
```

**Builder:** Verify `hashlib` is not already imported.

**Rationale:**
- `source_origin_id` — Points to the first WR post in the activity window. When multiple agents observe the same WR post during different duty cycles, their `source_origin_id` values match, triggering the shared-ancestry check. This is the BF-226/227 failure mode.
- `artifact_version` — Composite hash of all observed post IDs (sorted for determinism). Two agents observing the exact same set of posts get the same version. An agent observing a subset gets a different version — AD-665 grades this as "same origin, different version" (partial independence).
- **If `_wr_activity` is empty** (agent observed EventLog or other non-WR context), both fields remain empty string — graceful degradation to pre-AD-663 behavior.

**Note on `_wr_activity` variable:** The existing code computes `_wr_activity = context.get("ward_room_activity", [])` at line 982. Builder: verify this variable is still named `_wr_activity` and is accessible at the point where the provenance computation is inserted. If the variable name has drifted, adjust accordingly.

---

## Section 4: Cognitive Agent Action Episodes

**File:** `src/probos/cognitive/cognitive_agent.py` (EDIT)

At the action episode construction site (find the `AnchorFrame(` inside the `_store_action_episode` or equivalent method, where `channel="action"`):

**Current AnchorFrame construction:**
```python
                anchors=AnchorFrame(
                    channel="action",
                    department=_dept,
                    trigger_type=intent.intent,
                    trigger_agent=params.get("from", ""),
                ),
```

**Add provenance fields:**
```python
                anchors=AnchorFrame(
                    channel="action",
                    department=_dept,
                    trigger_type=intent.intent,
                    trigger_agent=params.get("from", ""),
                    # AD-663: Provenance — the triggering observation is the root artifact
                    source_origin_id=observation.get("correlation_id", "") or "",
                    artifact_version=hashlib.sha256(
                        str(query_text)[:500].encode("utf-8")
                    ).hexdigest()[:16] if query_text else "",
                ),
```

**Add import** at the module top of `cognitive_agent.py` (if not already present):
```python
import hashlib
```

**Builder:** Verify `hashlib` is not already imported. This is a large file — search carefully.

**Rationale:**
- `source_origin_id` — Uses the `correlation_id` from the observation, which traces back to the original event that triggered this action chain. When two agents process the same correlated event, their `source_origin_id` values match.
- `artifact_version` — SHA-256 of the query text (first 500 chars, matching the existing truncation pattern for `result_text`). Two agents processing the same query text get the same version. Different interpretations of the same event get different versions.
- **If `correlation_id` is absent** (legacy or non-correlated actions), `source_origin_id` is empty — graceful degradation.

---

## Section 5: Dream Consolidation Reflection Episodes

**File:** `src/probos/cognitive/dreaming.py` (EDIT)

At the reflection episode construction site (find the `AnchorFrame(trigger_type="dream_consolidation")` inside the method that creates AD-599 reflection episodes):

**Current AnchorFrame construction:**
```python
            anchors = AnchorFrame(
                trigger_type="dream_consolidation",
            )
```

**Add provenance fields:**
```python
            anchors = AnchorFrame(
                trigger_type="dream_consolidation",
                # AD-663: Provenance — the reflection is derived from consolidated episodes
                source_origin_id=f"dream-cluster:{episode_id}",
                artifact_version=content_hash,
            )
```

**Rationale:**
- `source_origin_id = f"dream-cluster:{episode_id}"` — The reflection's episode ID is deterministic (`reflection-{content_hash[:16]}`), making this a stable origin. Two reflection episodes from the same content share ancestry (correctly — they're the same insight).
- `artifact_version = content_hash` — Reuses the `content_hash` variable already computed at the line above (`content_hash = hashlib.sha256(content_text.encode()).hexdigest()[:16]`). No new hash computation needed.

**Builder:** Verify `content_hash` is in scope at the `AnchorFrame` construction point. It's computed a few lines above at the `episode_id = f"reflection-{content_hash}"` line.

---

## Section 6: Tests

**File:** `tests/test_ad663_provenance_producers.py` (NEW)

### Test categories (14 tests):

**Ward Room provenance (4 tests):**

1. **`test_wr_reply_episode_has_provenance`** — Create a WardRoomPost with known `id` and `body`. Construct the reply episode AnchorFrame the same way the production code does. Assert `anchors.source_origin_id == f"wr-post:{post.id}"` and `anchors.artifact_version` is a 16-char hex string equal to `hashlib.sha256(post.body.encode()).hexdigest()[:16]`.

2. **`test_wr_thread_episode_has_provenance`** — Create a thread with known `id` and `title`. Construct the thread episode AnchorFrame. Assert `anchors.source_origin_id == f"wr-thread:{thread.id}"` and `anchors.artifact_version == hashlib.sha256(title.encode()).hexdigest()[:16]`.

3. **`test_wr_same_post_same_provenance`** — Two agents construct reply episode AnchorFrames from the same WardRoomPost. Assert both have identical `source_origin_id` and `artifact_version`. This is the core BF-226/227 invariant: same post → shared ancestry detected.

4. **`test_wr_edited_post_different_version`** — Same post ID but different body text (simulating post edit). Assert `source_origin_id` is identical (same post) but `artifact_version` differs. This enables AD-665's graded "same origin, different version" scoring.

**Proactive provenance (3 tests):**

5. **`test_proactive_episode_has_wr_provenance`** — Construct `_wr_activity` list with one post. Compute provenance the same way the production code does. Assert `source_origin_id == f"wr-post:{post_id}"` and `artifact_version` is a 16-char hex string.

6. **`test_proactive_same_activity_same_provenance`** — Two agents with identical `_wr_activity` lists (same post IDs in same order) produce identical `source_origin_id` and `artifact_version`. Shared ancestry is detected.

7. **`test_proactive_empty_activity_no_provenance`** — Empty `_wr_activity` → `source_origin_id == ""` and `artifact_version == ""`. Graceful degradation.

**Cognitive agent provenance (2 tests):**

8. **`test_action_episode_correlation_id_provenance`** — Observation with `correlation_id="evt-123"`. Assert `anchors.source_origin_id == "evt-123"` and `artifact_version` is a 16-char hex of the query text.

9. **`test_action_episode_no_correlation_id`** — Observation without `correlation_id`. Assert `anchors.source_origin_id == ""`. Graceful degradation.

**Dream consolidation provenance (2 tests):**

10. **`test_dream_reflection_has_provenance`** — Reflection episode with known `episode_id` and `content_hash`. Assert `anchors.source_origin_id == f"dream-cluster:{episode_id}"` and `anchors.artifact_version == content_hash`.

11. **`test_dream_same_content_same_provenance`** — Two reflection episodes from identical content. Assert identical provenance (same deterministic episode ID → same origin).

**Consumer integration (3 tests):**

12. **`test_shared_ancestry_detected_for_same_wr_post`** — Construct two episodes with the same `source_origin_id` (from same WR post). Call `_share_artifact_ancestry(ep_a.anchors, ep_b.anchors)`. Assert `True`. This is the end-to-end integration: producer populates → consumer detects.

13. **`test_no_shared_ancestry_for_different_posts`** — Two episodes with different `source_origin_id` values. Assert `_share_artifact_ancestry()` returns `False`.

14. **`test_provenance_prefix_prevents_cross_type_collision`** — Construct one episode with `source_origin_id="wr-post:abc-123"` and another with `source_origin_id="wr-thread:abc-123"` (same UUID, different artifact types). Assert `_share_artifact_ancestry()` returns `False`. Proves the type prefix works.

**Test implementation notes:**
- Tests construct `AnchorFrame` directly with provenance fields — no need to mock WR infrastructure. The tests verify the provenance computation logic, not the WR plumbing.
- Import `_share_artifact_ancestry` from `probos.cognitive.social_verification` for integration tests (12-14).
- Import `AnchorFrame` from `probos.types`.
- Use `hashlib.sha256` to compute expected values. Do NOT hardcode hex strings — compute them in the test for clarity.

---

## Engineering Principles Compliance

- **SOLID/S** — No new classes. Each producer is responsible for its own provenance computation at the AnchorFrame construction site. No shared provenance service needed (DRY violation would be premature — each producer has different source data).
- **SOLID/O** — Purely additive: new keyword arguments to existing `AnchorFrame()` constructor calls. No existing behavior changes.
- **SOLID/D** — AnchorFrame is the contract. Producers populate it; consumers read it. No coupling between producers and consumers beyond the field names.
- **Law of Demeter** — Each producer accesses only its own local variables (`post.id`, `post.body`, `thread.id`, `_wr_activity`, `observation`, `content_hash`). No reaching through objects to extract provenance data.
- **Fail Fast** — Provenance computation uses simple hash operations that cannot fail in practice. The only failure mode is missing data (empty `post.body`, empty `_wr_activity`), which degrades to empty strings. No `try/except` needed around hash computations. The outer `try/except` on the episode store already catches catastrophic failures.
- **DRY** — Each producer's provenance computation is 2-4 lines at the construction site. No utility function extracted — the logic is site-specific (WR post ID vs thread ID vs correlation ID vs dream cluster ID). Extracting a common function would add abstraction with no reuse benefit.
- **Defense in Depth** — Consumer-side validation (`_share_artifact_ancestry`) handles empty strings correctly. Producer-side provides the data; consumer-side validates it. If a producer fails to populate provenance, the consumer degrades gracefully (treats as independent — same as pre-AD-663 behavior).

---

## Tracker Updates

After all tests pass:

1. **PROGRESS.md** — Add entry:
   ```
   AD-663 COMPLETE. Provenance Producer Wiring — populate source_origin_id and artifact_version on AnchorFrame at 5 episode producer sites (WR reply, WR thread, proactive thought, cognitive agent action, dream consolidation reflection). Enables AD-662 consumer-side ancestry detection and AD-665 graded scoring. WR posts use post/thread ID as origin, SHA-256 body hash as version. Proactive uses observed WR post IDs. Cognitive agent uses correlation_id. Dream uses deterministic reflection ID. anomaly_window_id deferred (no automated detector). 14 tests. Issue #XXX.
   ```
   Replace `#XXX` with the actual issue number created for this AD.

2. **docs/development/roadmap.md** — Add AD-663 entry after the AD-662 entry (around line 7089):
   ```
   **AD-663: Provenance Producer Wiring** *(Complete, OSS, Issue #XXX)* — Populate `source_origin_id` and `artifact_version` on AnchorFrame at 5 episode producer sites: Ward Room replies/threads, proactive thoughts, cognitive agent actions, dream consolidation reflections. Enables AD-662 consumer-side ancestry detection and AD-665 graded version scoring. WR posts use `wr-post:{id}` / `wr-thread:{id}` origin prefixes with SHA-256 body hash versioning. Proactive agents use observed WR post IDs. Cognitive agents use correlation_id from event tracing. Dream reflections use deterministic cluster IDs. `anomaly_window_id` deferred to future AD (no automated anomaly detection infrastructure). 14 tests. *Depends on: AD-662 (consumer infrastructure — COMPLETE). Unlocks: AD-665 (graded source validation).*
   ```

3. **DECISIONS.md** — Add entry:
   ```
   ### AD-663 — Provenance Producer Wiring (2026-04-26)
   **Context:** AD-662 added consumer-side provenance validation (`_share_artifact_ancestry`, anomaly window discount) but no producer populates the three AnchorFrame provenance fields. AD-665 adds graded scoring but is production no-op without populated fields. BF-226/227 demonstrated the failure mode: multiple agents observe the same WR post during queue pressure, observations pass spatiotemporal independence checks but share corrupted ancestry.
   **Decision:** Wire 5 highest-risk episode producers to populate `source_origin_id` and `artifact_version` at AnchorFrame construction. Provenance strategy is site-specific: WR uses post/thread IDs with type prefixes (`wr-post:`, `wr-thread:`), proactive uses observed WR post IDs from context, cognitive agent uses correlation_id, dream reflections use deterministic cluster IDs. Version fingerprints use SHA-256 truncated to 16 hex chars. `anomaly_window_id` explicitly deferred — no automated anomaly detection infrastructure exists. Remaining producers (no-response, peer repetition, feedback, smoke test, DM) are low corroboration risk and retain empty provenance.
   **Consequences:** AD-662's consumer-side checks become active for new WR-derived episodes. AD-665's graded scoring will work for post-edit scenarios (same origin, different body hash → different artifact_version). Agents observing the same WR post during different duty cycles now trigger shared-ancestry detection. Legacy episodes retain empty provenance and are treated as independent (no behavioral change for existing data).
   ```
