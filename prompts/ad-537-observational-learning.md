# AD-537: Observational Learning (Ward Room Cross-Agent Learning)

**Type:** Build Prompt
**AD:** 537
**Title:** Observational Learning — Ward Room Cross-Agent Learning
**Depends:** AD-532 ✅ (Procedure Extraction), AD-430 ✅ (Action Memory / Ward Room episodes), AD-535 ✅ (Graduated Compilation), AD-536 ✅ (Trust-Gated Promotion), Ward Room ✅ (existing), DreamingEngine ✅ (existing)
**Branch:** `ad-537-observational-learning`

---

## Context

Agents currently learn only from their own direct experience. If Security solves a problem that Engineering later encounters, Engineering starts from scratch — even though the solution was discussed in the Ward Room where Engineering could have been listening. The entire Cognitive JIT pipeline (AD-531–536) is self-referential: an agent extracts procedures from *its own* episode clusters.

AD-537 adds **observational learning** — Bandura's social learning theory, implemented. During dream consolidation, agents scan Ward Room discussions for success/failure narratives authored by *other* agents. When a discussion contains enough actionable detail, the dreaming agent extracts a **vicarious procedure** — a procedure derived from observation, not personal experience. These procedures enter the compilation hierarchy at Level 1 (Novice) regardless of the originating agent's level, because the observing agent hasn't validated the approach yet.

AD-537 also implements **Level 5 (Expert)** — the teaching compilation level deferred since AD-535. When a promoted procedure (AD-536 approved) reaches Level 5, the owning agent can explicitly teach it to specific agents via Ward Room DMs. Taught procedures start at Level 2 (Guided), giving them a head start over passively observed ones.

**Intellectual lineage:**
- **Bandura (1977)** — Social Learning Theory. Learning through observation of models. Attention → Retention → Reproduction → Motivation.
- **Lave & Wenger (1991)** — Situated Learning / Communities of Practice. Learning is social participation, not isolated cognition. The Ward Room IS the curriculum.
- **Collins, Brown, Newman (1989)** — Cognitive Apprenticeship. Modeling phase = Ward Room observation.

**Security note (AD-529):** Observational learning creates a contagion vector — one compromised agent could spread harmful patterns through Ward Room discussion. The trust-gated filtering (only learn from agents above a trust threshold) and the Level 1 entry point (observed procedures must be personally validated before advancing) provide defense in depth. Full contagion firewall is a separate AD (AD-529).

---

## Engineering Principles Compliance

- **SOLID (S):** Observational extraction is a new function in `procedures.py`, not bolted onto existing extraction. Teaching protocol is a new method on CognitiveAgent, not merged into existing promotion logic.
- **SOLID (O):** Extends DreamingEngine via new Step 7e (after 7d, before 8). Extends Procedure dataclass with `learned_via` field. No modification to existing extraction functions.
- **SOLID (D):** Depends on WardRoomService abstraction (public API), ProcedureStore abstraction, EpisodicMemory abstraction. Constructor injection for all.
- **Law of Demeter:** Query Ward Room via `browse_threads()`, `get_thread()` public API. Don't reach into Ward Room's SQLite tables directly.
- **Fail Fast:** If Ward Room is unavailable or has no new threads, Step 7e completes immediately with zero extractions. Don't block the dream cycle.
- **DRY:** Reuse `_format_episode_blocks()` pattern for formatting Ward Room content. Reuse ProcedureStore's `save()` for storing observed procedures. Reuse `_announce_promotion_request()` pattern for teaching Ward Room announcements.
- **Cloud-Ready Storage:** New `learned_via` column follows existing ProcedureStore migration pattern.

---

## What NOT to Build

- **AD-529 (Communication Contagion Firewall)** — Full adversarial protection is a separate AD. AD-537 includes basic trust-threshold filtering as defense in depth, but not the full firewall.
- **AD-538 (Procedure Lifecycle)** — Decay, re-validation, deduplication. Separate AD.
- **AD-554 (Cross-Agent Convergence Detection)** — Convergence scoring is a Notebook Quality Pipeline feature. Separate.
- **Automatic teaching triggers** — AD-537 makes teaching an explicit action (agent decides to teach). Automatic "you should learn this" recommendations are a future enrichment.
- **Bulk observation** — Dream Step 7e scans recent Ward Room activity (since last dream). It does not do full historical backfill.

---

## What to Build

### Part 0: Config Constants

File: `src/probos/config.py`

Add constants:

```python
# AD-537: Observational Learning
OBSERVATION_MIN_TRUST: float = 0.5               # Only observe agents with trust >= this
OBSERVATION_MAX_THREADS_PER_DREAM: int = 20       # Cap threads scanned per dream cycle
OBSERVATION_MIN_DETAIL_SCORE: float = 0.6         # LLM-assessed actionability threshold
OBSERVATION_WARD_ROOM_LOOKBACK_HOURS: float = 24  # Scan threads from last N hours
TEACHING_MIN_COMPILATION_LEVEL: int = 5           # Must be Level 5 to teach
TEACHING_MIN_TRUST: float = 0.85                  # Must be Commander+ trust to teach
COMPILATION_MAX_LEVEL: int = 5                    # Raise from 4 → 5 (unlocks Expert)
```

**Important:** Change `COMPILATION_MAX_LEVEL` from `4` to `5`. This is the gating constant that currently prevents Level 5 from being reached (line 731 of `cognitive_agent.py`: `return min(4, COMPILATION_MAX_LEVEL)`). AD-536 already implemented `_max_compilation_level_for_promoted()` which returns 5 for approved procedures with Commander+ trust, but the `min(max_allowed, COMPILATION_MAX_LEVEL)` at line 1374 clamps it. Raising the cap lets the existing AD-536 logic work.

---

### Part 1: Procedure Dataclass — `learned_via` Field

File: `src/probos/cognitive/procedures.py`

Add a `learned_via` field to the `Procedure` dataclass:

```python
learned_via: str = "direct"  # "direct" | "observational" | "taught"
```

Place it after `tags` (line 85). Values:
- `"direct"` — default. Procedure extracted from agent's own episode clusters (AD-532).
- `"observational"` — extracted from Ward Room observation during dream consolidation (AD-537).
- `"taught"` — explicitly taught by a Level 5 Expert agent via Ward Room DM (AD-537).

Also add a field to track the originating agent for observed/taught procedures:

```python
learned_from: str = ""  # callsign of the agent observed/taught from (AD-537)
```

Update `to_dict()` and `from_dict()` to include both fields.

---

### Part 2: ProcedureStore Migration — `learned_via` Column

File: `src/probos/cognitive/procedure_store.py`

Add migration in `_migrate()` (follow the AD-535/536 pattern):

```python
# AD-537: Observational learning provenance
("learned_via", "TEXT DEFAULT 'direct'"),
("learned_from", "TEXT DEFAULT ''"),
```

Update `_row_to_procedure()` to read these columns.
Update `save()` to write these columns.

---

### Part 3: Observational Extraction Function

File: `src/probos/cognitive/procedures.py`

New function: `extract_procedure_from_observation()`

```python
async def extract_procedure_from_observation(
    thread_content: str,          # Formatted Ward Room thread (title + posts)
    observer_agent_type: str,     # The watching agent's type
    author_callsign: str,         # Who wrote the original discussion
    author_trust: float,          # Author's current trust score
    llm_client: Any,
) -> Procedure | None:
```

**How it works:**

1. Format the Ward Room thread content into a structured block (title, author, posts in chronological order).

2. Send to LLM with a new system prompt (`_OBSERVATION_SYSTEM_PROMPT`) that instructs:
   - Analyze this Ward Room discussion for actionable procedural knowledge.
   - Is there a clear problem → solution narrative with enough detail to extract steps?
   - Score the **detail level** (0.0–1.0): can someone who wasn't there reproduce this?
   - If detail_score >= `OBSERVATION_MIN_DETAIL_SCORE`, extract a procedure.
   - The procedure should be framed from the observer's perspective (what *I* learned from watching).
   - Include a `learned_context` note in the description: "Observed from {author_callsign}'s discussion about {topic}."

3. Parse the LLM response (same JSON schema as `extract_procedure_from_cluster()`).

4. If extraction succeeds, create a `Procedure` with:
   - `learned_via="observational"`
   - `learned_from=author_callsign`
   - `compilation_level=1` — always starts at Novice, regardless of original agent's level
   - `evolution_type="CAPTURED"`
   - `origin_cluster_id=""` — no cluster (Ward Room source, not episode cluster)
   - `provenance=[]` with thread_id stored in tags as `ward_room_thread:{thread_id}`
   - `origin_agent_ids=[observer_agent_type]`

5. If detail_score < threshold, return `None` (not enough detail to learn from).

**The system prompt** should emphasize the AD-541b READ-ONLY framing and the Memory Provenance Boundary (AD-540) — the observer is learning from another agent's account `[observed]`, not from direct experience.

Use `tier="standard"` (same as AD-532 extraction). Temperature 0.0.

---

### Part 4: Dream Step 7e — Observational Learning

File: `src/probos/cognitive/dreaming.py`

Add **Step 7e** after Step 7d (fallback learning) and before Step 8 (gap prediction).

```python
# Step 7e: Observational learning from Ward Room (AD-537)
```

**How it works:**

1. **Gate check:** If no WardRoomService available on the runtime, skip.

2. **Scan recent Ward Room threads.** Query `browse_threads()` with:
   - `since=` last dream cycle timestamp (or `OBSERVATION_WARD_ROOM_LOOKBACK_HOURS` ago)
   - `limit=OBSERVATION_MAX_THREADS_PER_DREAM`
   - Exclude DM channels (observe public discussions only; teaching uses DMs separately)

3. **Filter threads:**
   - Skip threads authored by the dreaming agent itself (can't observe yourself).
   - Skip threads where the author's trust is below `OBSERVATION_MIN_TRUST` (defense in depth).
   - Skip threads already processed (store processed thread IDs in a set, persisted per-agent — use a simple tag like `observed_thread:{thread_id}` in the procedure's tags to avoid re-processing; or add a lightweight `_observed_threads` set on the DreamingEngine keyed by agent).

4. **For each qualifying thread:**
   a. Fetch thread content via Ward Room API (`get_thread()` or equivalent to get all posts).
   b. Format as a readable discussion block.
   c. Call `extract_procedure_from_observation()`.
   d. If a procedure is returned:
      - Check ProcedureStore for semantic duplicates (`find_matching()` with the new procedure's intent types). If a similar procedure already exists (from own experience), skip — direct experience takes priority over observation.
      - Save to ProcedureStore via `save()`.
      - Log: "Observed procedure '{name}' from {author_callsign}'s discussion in {channel}."

5. **Update DreamReport:**
   - Add `procedures_observed: int = 0` field to `DreamReport` dataclass.
   - Add `observation_threads_scanned: int = 0` field.
   - Increment after each extraction.

**Dedup guard:** Use `_extracted_cluster_ids` pattern from AD-532 but for thread IDs. Track which threads have already been observed to prevent duplicate procedure extraction across dream cycles. The simplest approach: the ProcedureStore already prevents exact duplicates via semantic matching. For thread-level dedup, tag observed procedures with `ward_room_thread:{thread_id}` and check before extraction.

---

### Part 5: Level 5 Expert — Teaching Protocol

File: `src/probos/cognitive/cognitive_agent.py`

**5a: Teaching method**

New method: `_teach_procedure()`

```python
async def _teach_procedure(
    self,
    procedure_id: str,
    target_callsign: str,
) -> bool:
```

**Preconditions (all must pass):**
- The procedure exists in the agent's ProcedureStore.
- The procedure is at compilation level 5 (Expert).
- The procedure has `promotion_status == "approved"` (AD-536 — must be institutionally approved to teach).
- The agent's trust is >= `TEACHING_MIN_TRUST`.
- The target agent exists in the pool.

**How it works:**
1. Validate all preconditions. Fail fast with clear reason on any failure.
2. Format the procedure as a teaching message — a structured Ward Room DM that includes:
   - Procedure name, description, and steps (full detail).
   - The teacher's experience context: success count, compilation history.
   - Explicit framing: "I'm teaching you this procedure because I've validated it through N successful executions."
3. Send as a Ward Room DM to the target agent via `WardRoomService.post()` on the DM channel (use `get_or_create_dm_channel()`).
4. The DM is stored as a Ward Room episode (AD-430 already does this).
5. Return `True` on success.

**5b: Teaching intent handler**

The teaching DM, when received by the target agent in its next dream cycle, is processed by Step 7e. However, **taught procedures get special handling:**

Add a detection heuristic in `extract_procedure_from_observation()`: if the thread is a DM channel AND the content matches a structured teaching format (contains the teaching framing markers), set `learned_via="taught"` instead of `"observational"`, and set `compilation_level=2` (Guided) instead of 1 (Novice).

Alternatively (simpler and more reliable): add a new extraction function `extract_procedure_from_teaching()` that is called specifically when the dream step detects a teaching-formatted DM. This avoids overloading the observation extraction with teaching detection logic.

**Recommended approach:** Use a single `extract_procedure_from_observation()` but pass a `is_teaching: bool = False` parameter. When `True`:
- `learned_via = "taught"`
- `compilation_level = 2`
- Skip detail_score threshold (teaching is always detailed enough)

**5c: Teaching trigger in handle_intent()**

When a procedure is promoted to Level 5 via the consecutive_successes mechanism (existing code at line 1374), check if the agent wants to teach it. For now, **don't auto-teach.** Log that the procedure reached Expert level and is eligible for teaching. The agent (or Captain) can trigger teaching via a shell command (Part 7).

---

### Part 6: Level 5 Dispatch in `_check_procedural_memory()`

File: `src/probos/cognitive/cognitive_agent.py`

Currently the dispatch branching in `_check_procedural_memory()` handles Levels 2, 3, and 4. Add Level 5 handling:

**Level 5 (Expert)** behaves identically to Level 4 (Autonomous) for execution — zero LLM tokens, pure deterministic replay. The difference is that Level 5 procedures are *eligible to teach*. No new dispatch logic needed; the existing Level 4 path handles it. Just ensure the `elif` chain doesn't exclude Level 5:

```python
# Existing Level 4 check — extend to cover Level 5
if proc.compilation_level >= 4:  # Level 4 Autonomous + Level 5 Expert
    # Zero-token replay (existing logic)
```

Verify: the current dispatch code at the Level 4 branch. If it's `== 4`, change to `>= 4`. If it's already `>= 4`, no change needed.

---

### Part 7: Shell Commands

File: `src/probos/experience/commands/commands_procedure.py`

Add to the existing `/procedure` command group (created by AD-536):

**`/procedure teach <procedure_id> <target_callsign>`**
- Calls `_teach_procedure()` on the agent that owns the procedure.
- Validates Level 5 + approved + trust preconditions.
- Output: "Teaching procedure '{name}' to {target_callsign}..." or error reason.

**`/procedure observed [--agent <callsign>]`**
- Lists procedures with `learned_via IN ('observational', 'taught')`.
- Shows: name, learned_via, learned_from, compilation_level, success_count.
- Optional filter by agent.

---

### Part 8: API Endpoints

File: `src/probos/routers/procedures.py`

Add to the existing procedures router (created by AD-536):

**`POST /procedures/teach`**
- Body: `{ "procedure_id": str, "target_callsign": str }`
- Calls `_teach_procedure()`.
- Returns 200 with teaching confirmation or 400/403 with precondition failure reason.

**`GET /procedures/observed`**
- Query params: `agent` (optional filter by agent callsign)
- Returns procedures with `learned_via != "direct"`.
- Each entry includes: id, name, learned_via, learned_from, compilation_level, success_count.

---

### Part 9: DreamReport Updates

File: `src/probos/types.py`

Add to the `DreamReport` dataclass:

```python
# AD-537: Observational learning
procedures_observed: int = 0
observation_threads_scanned: int = 0
teaching_dms_processed: int = 0
```

---

## Guard Rails

### What to check before each Part

1. **Read the file you're modifying** before making changes.
2. **Search for existing implementations** — don't duplicate. In particular, check `extract_procedure_from_cluster()` for patterns to reuse.
3. **Run targeted tests** after each Part completes.
4. **Follow existing patterns** — the AD-536 migration pattern, the AD-532 extraction function pattern, the Dream Step 7a-7d pattern.

### Interactions with existing code

- **`COMPILATION_MAX_LEVEL` change (4→5):** This affects line 731 (`return min(4, COMPILATION_MAX_LEVEL)`) and line 1374 (`min(max_allowed, COMPILATION_MAX_LEVEL)`). After changing the constant, `_max_compilation_level_for_trust()` should still return `min(4, COMPILATION_MAX_LEVEL)` — the 4 there is the trust-based cap (Lieutenant+ maxes at Level 4). Only `_max_compilation_level_for_promoted()` can return 5. Verify this logic still holds: non-promoted procedures cap at 4, promoted procedures with Commander+ trust can reach 5.
- **AD-536 `_max_compilation_level_for_promoted()`:** Already returns 5 for approved + Commander+ trust. With `COMPILATION_MAX_LEVEL` raised to 5, this code path becomes reachable. No changes needed to AD-536 code.
- **Existing tests:** Some tests may assert `COMPILATION_MAX_LEVEL == 4`. Update these to `5`. Search for `COMPILATION_MAX_LEVEL` in test files.
- **Level 4 dispatch branch:** If it uses `== 4`, change to `>= 4` to include Level 5. If `>= 4`, no change.

### Scope boundaries

- **Observation is read-only.** Observing agents never modify the Ward Room thread they're learning from. No reactions, no endorsements, no "I learned from this" posts (that's a future enrichment).
- **No cross-instance observation.** AD-537 operates within a single ProbOS instance. Federation-level observational learning is a Nooplex-era feature.
- **No retroactive observation.** Step 7e only scans threads since the last dream cycle. No historical backfill.
- **Teaching is explicit, not automatic.** An agent reaching Level 5 logs the milestone but doesn't auto-teach. The Captain or agent must trigger teaching via `/procedure teach`.

---

## Tests

Target: **50-65 tests across 7 test files.**

### `tests/test_observational_extraction.py` (~10 tests)

1. `test_extract_from_detailed_thread` — full thread with clear problem→solution → procedure extracted
2. `test_extract_from_vague_thread` — thread lacking detail → returns None (below threshold)
3. `test_learned_via_observational` — extracted procedure has `learned_via="observational"`
4. `test_learned_from_populated` — extracted procedure has `learned_from=author_callsign`
5. `test_compilation_level_always_1` — observed procedures always start at Level 1
6. `test_trust_threshold_filter` — author trust below `OBSERVATION_MIN_TRUST` → skip
7. `test_self_observation_skip` — agent doesn't extract from its own threads
8. `test_teaching_format_detection` — teaching DM → `learned_via="taught"`, `compilation_level=2`
9. `test_observation_provenance_tags` — procedure tags include `ward_room_thread:{id}`
10. `test_observation_system_prompt_includes_read_only_framing` — AD-541b compliance

### `tests/test_dream_step_7e.py` (~10 tests)

1. `test_step_7e_scans_recent_threads` — threads since last dream are scanned
2. `test_step_7e_skips_own_threads` — agent's own threads excluded
3. `test_step_7e_skips_low_trust_authors` — trust filtering works
4. `test_step_7e_skips_dm_channels` — only public discussions for observation (DMs are teaching path)
5. `test_step_7e_respects_max_threads` — `OBSERVATION_MAX_THREADS_PER_DREAM` cap
6. `test_step_7e_dedup_across_dreams` — same thread not re-processed in next dream
7. `test_step_7e_saves_to_procedure_store` — extracted procedure is saved
8. `test_step_7e_skips_if_similar_exists` — duplicate semantic match → skip
9. `test_step_7e_updates_dream_report` — `procedures_observed` and `observation_threads_scanned` incremented
10. `test_step_7e_no_ward_room_graceful` — no ward room service → step completes silently

### `tests/test_teaching_protocol.py` (~8 tests)

1. `test_teach_procedure_success` — Level 5, approved, Commander+ trust → DM sent
2. `test_teach_requires_level_5` — Level 4 procedure → fails
3. `test_teach_requires_approved` — unapproved procedure → fails
4. `test_teach_requires_commander_trust` — trust below threshold → fails
5. `test_teach_target_must_exist` — nonexistent target → fails
6. `test_teach_sends_ward_room_dm` — DM posted to correct channel
7. `test_teach_message_contains_steps` — DM includes procedure steps and context
8. `test_taught_procedure_starts_at_level_2` — taught procedure enters at Level 2

### `tests/test_level_5_dispatch.py` (~8 tests)

1. `test_compilation_max_level_is_5` — config constant is 5
2. `test_level_5_reachable_for_promoted_commander` — approved + Commander → Level 5
3. `test_level_5_unreachable_without_promotion` — non-promoted procedure capped at 4
4. `test_level_5_unreachable_without_commander_trust` — promoted but Lieutenant → capped at 4
5. `test_level_5_dispatch_same_as_level_4` — zero-token replay, same path
6. `test_level_5_promotion_from_4` — consecutive successes at Level 4 → promote to 5
7. `test_existing_level_4_tests_still_pass` — regression: existing Level 4 behavior unchanged
8. `test_non_promoted_max_level_4` — `_max_compilation_level_for_trust()` still caps at 4

### `tests/test_procedure_learned_via.py` (~6 tests)

1. `test_learned_via_default_direct` — new procedures default to "direct"
2. `test_learned_via_persists_save_load` — save + get preserves field
3. `test_learned_from_persists` — save + get preserves `learned_from`
4. `test_migration_adds_columns` — migration adds `learned_via` and `learned_from`
5. `test_to_dict_includes_learned_via` — serialization includes new fields
6. `test_from_dict_includes_learned_via` — deserialization includes new fields

### `tests/test_observational_commands.py` (~5 tests)

1. `test_procedure_teach_command` — `/procedure teach` calls `_teach_procedure()`
2. `test_procedure_teach_precondition_failure` — precondition failure → error message
3. `test_procedure_observed_list` — `/procedure observed` lists non-direct procedures
4. `test_procedure_observed_filter_by_agent` — `--agent` filter works
5. `test_procedure_observed_empty` — no observed procedures → "No observed procedures"

### `tests/test_observational_routing.py` (~5 tests)

1. `test_api_teach_endpoint` — POST `/procedures/teach` calls teaching protocol
2. `test_api_teach_precondition_error` — precondition failure returns 400/403
3. `test_api_observed_endpoint` — GET `/procedures/observed` returns observed procedures
4. `test_api_observed_filter` — `?agent=` query param filters results
5. `test_api_observed_empty` — no results → empty list

---

## Existing Test Updates

Search for tests that assert `COMPILATION_MAX_LEVEL == 4` or use `COMPILATION_MAX_LEVEL` and update them to reflect the new value of 5. Likely locations:

- `tests/test_graduated_compilation.py`
- `tests/test_replay_dispatch.py`
- `tests/test_promotion_eligibility.py`

Also check the Level 4 dispatch branch — if tests assert `compilation_level == 4` as the maximum, they should still pass since Level 4 is still achievable. Only tests that explicitly check the *cap* need updating.

---

## Verification

After all parts are complete:

1. Run all AD-537 tests: `uv run pytest tests/test_observational_extraction.py tests/test_dream_step_7e.py tests/test_teaching_protocol.py tests/test_level_5_dispatch.py tests/test_procedure_learned_via.py tests/test_observational_commands.py tests/test_observational_routing.py -v`
2. Run all Cognitive JIT tests: `uv run pytest tests/test_episode_clustering.py tests/test_procedure_extraction.py tests/test_procedure_store.py tests/test_replay_dispatch.py tests/test_procedure_evolution.py tests/test_negative_extraction.py tests/test_compound_procedures.py tests/test_reactive_proactive.py tests/test_fallback_learning.py tests/test_multi_agent_replay_dispatch.py tests/test_graduated_compilation.py tests/test_procedure_criticality.py tests/test_promotion_eligibility.py tests/test_promotion_routing.py tests/test_promotion_approval.py tests/test_promotion_commands.py tests/test_promotion_integration.py tests/test_procedure_store_promotion.py -v`
3. Run full suite: `uv run pytest tests/ -x -q`
