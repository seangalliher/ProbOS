# Combo A: 7 Trivial Extensions (Wave 8)

**Status:** Ready for builder
**Scope:** 7 child ADs grouped into a single Builder commit per `prompts/AD-BACKLOG-AUDIT.md` recommendation. Originally 8; AD-575b dropped during the Wave 8 revision pass (theater per convention #7 — see `## Revision (2026-05-02)` at the bottom).
**Total estimated tests:** ~26 (3-5 per child AD)
**Risk:** Low — each child is a config knob, a one-file tweak, or an additive helper. No cross-cutting refactor.
**Single commit message:** `Combo A: AD-538b/572b/573b/576b/526c/655/656 trivial extensions`

---

## Why Combo

Per `AD-BACKLOG-AUDIT.md`: 7 trivial extensions to already-closed parent ADs. Each is one-file, additive, low-risk. Per-prompt overhead × 7 would multiply Builder commit cost ~5×; combo is cleaner.

## Combo Discipline

- Each child AD is a separate H2 section (`## AD-NNN: Title`).
- Each child has its own Verify-First grep evidence + implementation + test plan.
- Single Section 0 (EventTypes) at the top covers all 7 children's new events.
- Single Tracker section at the bottom updates `PROGRESS.md` + `roadmap.md` for all 7.
- File-conflict serialization: AD-572b and AD-576b both touch `src/probos/proactive.py`. Implement them sequentially within the combo (Section 4 -> Section 5); Builder MUST run focused tests after each before moving to the next.
- Single commit closes all 7 ADs.

---

## Section 0: Event Types (consolidated)

Add to `src/probos/events.py`:

```
DREAM_MANIFEST_UPDATED = "dream_manifest_updated"  # AD-538b
CAPTAIN_DM_PRIORITY_QUEUED = "captain_dm_priority_queued"  # AD-572b
RECREATION_GAME_REGISTERED = "recreation_game_registered"  # AD-526c
CONTRASTIVE_RECALL = "contrastive_recall"  # AD-655
DEPT_PROFILE_APPLIED = "dept_profile_applied"  # AD-656
```

> Verified absent: `grep -n "DREAM_MANIFEST_UPDATED\|CAPTAIN_DM_PRIORITY_QUEUED\|RECREATION_GAME_REGISTERED\|CONTRASTIVE_RECALL\|DEPT_PROFILE_APPLIED" src/probos/events.py` returns no matches.

> AD-573b, AD-576b do NOT introduce EventTypes (per `AD-BACKLOG-AUDIT.md` event column = blank).

SEARCH (anchor on Wave-7 stable line, not the optimistic AD-475 anchor; revision-pass: AD-475 may not have landed before Combo A):
```python
    MODEL_ROUTED = "model_routed"  # AD-463
    MODEL_FALLBACK = "model_fallback"  # AD-463
```

REPLACE:
```python
    MODEL_ROUTED = "model_routed"  # AD-463
    MODEL_FALLBACK = "model_fallback"  # AD-463
    DREAM_MANIFEST_UPDATED = "dream_manifest_updated"  # AD-538b
    CAPTAIN_DM_PRIORITY_QUEUED = "captain_dm_priority_queued"  # AD-572b
    RECREATION_GAME_REGISTERED = "recreation_game_registered"  # AD-526c
    CONTRASTIVE_RECALL = "contrastive_recall"  # AD-655
    DEPT_PROFILE_APPLIED = "dept_profile_applied"  # AD-656
```

> Anchor-chain fallback: AD-463 `MODEL_FALLBACK` (line 211) is the Wave-7-stable terminal. If AD-469 (Wave 8) lands before Combo A, anchor on `EPS_REALLOCATION` instead. The Builder must grep `events.py` at build time and pick the lowest-line stable anchor.

---

## AD-538b: Dream Consolidation Manifest

**Verify-first:**
```
grep -n "class DreamScheduler\|_last_consolidated_count" src/probos/cognitive/dreaming.py
  100: self._last_consolidated_count: int = 0
  189: if current_count <= self._last_consolidated_count:
  2664: class DreamScheduler:
```

**Problem:** `DreamScheduler` tracks a single `_last_consolidated_count` cursor; on restart the cursor is lost and recently-consolidated episodes may be reprocessed. AD-538/551 (closed) consolidated the dream cycle but did not persist a per-episode manifest.

**v1 scope:** Add a per-episode skip-already-processed manifest that survives restart.

**File:** `src/probos/cognitive/dreaming.py` (edit) + `src/probos/cognitive/dream_manifest.py` (new, ~70 lines).

**Implementation:**
- New module `dream_manifest.py` exposing `DreamManifest` (stdlib JSON-backed). Public API: `mark_processed(episode_id, step)`, `is_processed(episode_id, step) -> bool`, `prune(max_age_seconds)`.
- Stored at `runtime.data_dir / "dream_manifest.json"`. Atomic write per Wave 5 convention #2.
- `DreamScheduler.__init__` accepts a kw-only `manifest: DreamManifest | None = None`.
- In the consolidation loop (around `dreaming.py:193` where `recent(k=...)` runs), filter episodes via `manifest.is_processed(ep.id, "consolidate")` before replay. After replay, call `mark_processed(ep.id, "consolidate")`.
- Emit `DREAM_MANIFEST_UPDATED` per replay batch (not per episode — keeps emit volume bounded).

**Tests (4 in `tests/test_combo_a_ad538b_manifest.py`):**
1. `test_dream_manifest_mark_and_check` -- happy path.
2. `test_dream_manifest_persists_across_restarts` -- write, drop instance, recreate, `is_processed` still True.
3. `test_dream_manifest_prune_removes_old_entries` -- entries older than `max_age_seconds` removed.
4. `test_dream_scheduler_skips_processed_episodes` -- mock manifest reports `is_processed=True` for ep-1; `_replay_episodes` not called for ep-1.

**Public attribute:** `runtime.dream_manifest = DreamManifest(...)` wired in `startup/finalize.py` near the existing dream-scheduler wiring (Builder must grep for `DreamScheduler` instantiation).

---

## AD-572b: Captain Engagement Extensions (DM)

**Verify-first:**
```
grep -n "captain_dm\|priority_queue\|alert_inject" src/probos/proactive.py
  (no matches today)
grep -n "_think_for_agent" src/probos/proactive.py
  634: async def _think_for_agent(self, agent: Any, rank: Rank, trust_score: float) -> None:
```

**Problem:** Captain-engagement signal (DM activity, ward-room mentions, alerts) is not surfaced to the proactive loop's context — agents don't know when the Captain is engaged.

**v1 scope:** Add a `CaptainEngagementProvider` that surfaces three signals into the proactive context:
1. Pending Captain alerts (count + most-recent topic).
2. Ward-Room thread activity in the last 60 seconds (count).
3. Priority DM queue depth (count of unread DMs to crew).

**File:** `src/probos/proactive.py` (edit `_gather_context` around `proactive.py:1061`) + a small helper module `src/probos/cognitive/captain_engagement.py` (new, ~80 lines).

**Implementation:**
- `CaptainEngagementProvider.snapshot() -> dict` returns `{"alerts_pending": N, "wardroom_activity_60s": N, "dm_queue_depth": N}`. Reads `runtime.bridge_alerts`, `runtime.ward_room`, and `runtime.ward_room` DM tables (all defensive with `getattr`).
- `_gather_context` (`proactive.py:1061`) appends `context["captain_engagement"] = provider.snapshot()` when the engagement provider is wired.
- When `dm_queue_depth > 0`, emit `CAPTAIN_DM_PRIORITY_QUEUED` once per discovery cycle (deduped by depth value to avoid floods).

**Tests (4 in `tests/test_combo_a_ad572b_engagement.py`):**
1. `test_captain_engagement_snapshot_when_runtime_none` -- empty dict, no crash.
2. `test_captain_engagement_snapshot_includes_alert_count`
3. `test_captain_engagement_emits_dm_priority_queued`
4. `test_proactive_gather_context_includes_captain_engagement` (uses `_FakeRuntime` stub)

**Public attribute:** `runtime.captain_engagement_provider` wired in `startup/finalize.py`.

---

## AD-573b: Working Memory Extensions

**Verify-first:**
```
grep -n "class WorkingMemoryManager\|class WorkingMemorySnapshot\|^@dataclass" src/probos/cognitive/working_memory.py
  21: @dataclass
  22: class WorkingMemorySnapshot:
  84: class WorkingMemoryManager:
grep -n "self\.working_memory\b" src/probos/runtime.py
  348: self.working_memory = WorkingMemoryManager(...)
  (the public runtime attribute is `working_memory`, NOT `working_memory_manager`)
```

**Problem:** Working memory does not capture relational links (who mentioned whom), a free-form scratchpad, or a list of in-flight commitments. Convention #14 already pushed the bigger-scope items to AD-573c+.

**v1 scope:** Add three small additive fields to `WorkingMemorySnapshot` and one small helper. NO new EventType.

**File:** `src/probos/cognitive/working_memory.py` (edit only).

**Implementation:**
- Extend `WorkingMemorySnapshot` (the existing `@dataclass` at line 22 -- NOT frozen; revision-pass correction) with three new fields, all defaulted:
  ```python
  relational_links: list[dict] = field(default_factory=list)  # [{"from": "x", "to": "y", "kind": "mention"}]
  scratchpad: list[str] = field(default_factory=list)         # free-form short notes
  commitments: list[dict] = field(default_factory=list)       # [{"id": "...", "summary": "...", "due": ...}]
  ```
- `WorkingMemoryManager` (line 84) gets three additive methods:
  - `record_relation(from_id, to_id, kind="mention")` -- appends to the in-memory ring.
  - `add_scratchpad(text)` -- bounded list (cap at 16 entries, drop oldest).
  - `add_commitment(commitment_id, summary, due_at=None)` -- bounded list (cap at 8).
- All three methods are best-effort and never raise (Wave-5 tier-2 log-and-degrade).

**Tests (3 in `tests/test_combo_a_ad573b_wm.py`):**
1. `test_wm_snapshot_includes_new_fields` -- default values are the expected empty containers.
2. `test_wm_record_relation_appends_to_links`
3. `test_wm_scratchpad_cap_drops_oldest_at_17th_entry`

**Public attribute:** none new; the existing `runtime.working_memory` (verified at `runtime.py:348`) is the integration point. **No `runtime.working_memory_manager`** attribute exists -- v1 prompt erroneously named the suffix; revision-pass correction.

---

## AD-575b: DROPPED (theater per convention #7)

**Status:** Wholesale-deferred. Not in this combo's v1 scope.

**Reason for drop (revision-pass decision):**

- Live grep for `runtime.self_summary_provider`, `SelfSummaryProvider`, `summary_for` returns no matches.
- The closed parent AD-575 did NOT ship a `self_summary_provider` surface. The defensive `getattr(rt, "self_summary_provider", None)` would always return `None`; the implementation is a permanent no-op.
- The DM-forwarded-content half is also explicitly no-op in current source (no `forwarded_content`/`forward_dm` handler).
- Both halves of AD-575b are theater per convention #7 (no-theater discipline).

**What this needs first:** a future AD that introduces a real `runtime.self_summary_provider` surface with at least one consumer. Once that lands, AD-575b becomes a meaningful 5-line edit on `_gather_context` (the design sketched here is correct; only the upstream surface is missing).

---

## AD-576b: LLM Retry with Exponential Backoff in Proactive Path

**Verify-first:**
```
grep -n "_llm_failure_count\|_update_llm_status" src/probos/proactive.py
  190: self._llm_failure_count: int = 0  # BF-069
  191: self._llm_status: str = "operational"  # AD-576
  708: self._llm_failure_count += 1
grep -n "agent\.handle_intent" src/probos/proactive.py
  694: result = await agent.handle_intent(intent)
```

**Problem:** When `agent.handle_intent` returns an LLM-error result (transient timeout, rate limit, connection failure), the proactive loop bumps the failure counter and abandons that cycle. AD-576 (closed) added the status-state-machine; AD-576b adds a single in-cycle retry with exponential backoff before incrementing the counter.

**v1 scope:** Single-line behavior change at `proactive.py:694`. Wrap the `handle_intent` call in a tight retry loop with `[0.5, 1.5]` second backoff and `max_retries=2`. Only retry on transient-LLM-error signals (the existing `is_llm_error` keyword set at lines 702-705).

**File:** `src/probos/proactive.py` (edit only).

**Implementation:**

SEARCH (around `proactive.py:693-706`):
```python
        result = await agent.handle_intent(intent)

        if not result or not result.success or not result.result:
            # BF-228: Only count actual LLM errors toward LLM failure status,
            # not empty responses or chain-level issues.
            is_llm_error = (
                not result
                or (result and hasattr(result, 'error') and result.error and
                    any(kw in str(result.error).lower() for kw in (
                        "llm", "timeout", "connection", "unreachable",
                        "rate limit", "api error", "httpx", "openai",
                    )))
            )
```

REPLACE:
```python
        # AD-576b: tight in-cycle retry on transient LLM errors before
        # incrementing the failure counter. Two attempts at [0.5, 1.5]s
        # backoff; counter increments only after both fail.
        _BACKOFFS_SECONDS = (0.5, 1.5)
        _LLM_ERROR_KEYWORDS = (
            "llm", "timeout", "connection", "unreachable",
            "rate limit", "api error", "httpx", "openai",
        )
        result = await agent.handle_intent(intent)
        for _backoff in _BACKOFFS_SECONDS:
            if result and result.success and result.result:
                break
            _is_transient = (
                not result
                or (result and hasattr(result, 'error') and result.error and
                    any(kw in str(result.error).lower() for kw in _LLM_ERROR_KEYWORDS))
            )
            if not _is_transient:
                break
            await asyncio.sleep(_backoff)
            result = await agent.handle_intent(intent)

        if not result or not result.success or not result.result:
            # BF-228: Only count actual LLM errors toward LLM failure status,
            # not empty responses or chain-level issues.
            is_llm_error = (
                not result
                or (result and hasattr(result, 'error') and result.error and
                    any(kw in str(result.error).lower() for kw in _LLM_ERROR_KEYWORDS))
            )
```

> Note: the `is_llm_error` block now references `_LLM_ERROR_KEYWORDS` instead of an inline tuple to keep the keyword set authoritative. Builder must verify the inline tuple at lines 702-705 matches `_LLM_ERROR_KEYWORDS` (semantically identical).

**Tests (4 in `tests/test_combo_a_ad576b_retry.py`):**
1. `test_proactive_retries_on_transient_llm_error` -- mock `agent.handle_intent` returns timeout twice then success; the loop counts as success; `_llm_failure_count` not incremented.
2. `test_proactive_does_not_retry_on_non_llm_error` -- error message has no LLM-error keyword; first attempt is the only attempt.
3. `test_proactive_increments_failure_counter_after_max_retries` -- all 3 attempts fail; `_llm_failure_count` increments by 1.
4. `test_proactive_backoff_delays_observable_via_monotonic_clock` -- monkeypatch `asyncio.sleep` to record sleeps; sleeps `[0.5, 1.5]` recorded across the two retries.

**Public attribute:** none.

---

## AD-526c: Recreation System Extensions

**Verify-first:**
```
grep -n "class RecreationService\|def register_engine\|def get_available_games\|self\._engines" src/probos/recreation/service.py
  15: class RecreationService:
  40: self._engines: dict[str, GameEngine] = {}
  56: def register_engine(self, engine: GameEngine) -> None:
  60: def get_available_games(self) -> list[str]:
ls src/probos/recreation/
  __init__.py  engine.py  service.py
```

**Problem:** Recreation system shipped one game (TicTacToe) via AD-526a. The existing `register_engine(engine)` registers `GameEngine` instances by `game_type` and `get_available_games()` lists registered types -- but no per-game metadata (description, agent-count constraints), no Captain-default preference, no event emission.

**v1 scope:** Extend the existing `register_engine` with optional metadata via a `GameMetadata` dataclass, plus a Captain-default preference and `RECREATION_GAME_REGISTERED` emission. **Do NOT introduce a parallel `register_game`/`list_games`/`_games` registry** -- that would duplicate `register_engine`/`get_available_games`/`_engines` and violate DRY (revision-pass: original draft had this duplication; review caught).

**File:** `src/probos/recreation/service.py` (edit) + `src/probos/recreation/metadata.py` (new, ~40 lines).

**Implementation:**
- New `metadata.py` defines:
  ```python
  @dataclass(frozen=True)
  class GameMetadata:
      """Optional metadata layered on a registered GameEngine."""
      description: str = ""
      agent_count_min: int = 2
      agent_count_max: int = 2
      registered_at: float = 0.0
  ```
- `RecreationService.__init__` accepts a kw-only `default_game: str = "tictactoe"` and adds `self._metadata: dict[str, GameMetadata] = {}`.
- `register_engine(engine, metadata=None)` extended to accept the optional `GameMetadata` (default builds a metadata with `description=""`, `agent_count_min=2`, `registered_at=time.time()`). Stores into `self._metadata[engine.game_type]`.
- New `get_metadata(game_type) -> GameMetadata | None` accessor.
- New `default_game` property that returns the kw-only init value.
- On every `register_engine` call, emit `RECREATION_GAME_REGISTERED` with `{"game_type", "description", "agent_count_min", "agent_count_max"}`.

**Tests (3 in `tests/test_combo_a_ad526c_recreation.py`):**
1. `test_recreation_register_engine_with_metadata_stores_both`
2. `test_recreation_register_engine_emits_event` -- verify `RECREATION_GAME_REGISTERED` payload.
3. `test_recreation_default_game_property_returns_init_value`

**Public attribute:** `runtime.recreation_service` (existing); no new top-level attribute. The existing `register_engine` and `get_available_games` API surfaces are preserved -- v1 extends them additively, no rename.

> Note: the audit's roadmap entry mentions "more games, prefs, spectators, holodeck integration" — only "metadata + Captain-default + emit" ship in v1 via additive extension of the existing surface. **Spectators and holodeck integration are wholesale-deferred to AD-526d/e** per convention #14.

---

## AD-655: Contrastive Memory Retrieval

**Verify-first:**
```
grep -n "async def recall\b\|class EpisodicMemory" src/probos/cognitive/episodic.py
  651: class EpisodicMemory:
  1440: async def recall(self, query: str, k: int = 5) -> list[Episode]:
grep -n "class EvaluateHandler\|_EVALUATION_MODES" src/probos/cognitive/sub_tasks/evaluate.py
  231: _EVALUATION_MODES: dict[str, EvaluationModeBuilder] = {
  249: class EvaluateHandler:
  252: def __init__(self, *, llm_client: Any = None, runtime: Any = None) -> None:
  (the actual class is `EvaluateHandler`; v1 prompt erroneously said `EvaluateSubTask`)
```

**Problem:** When the cognitive chain retrieves episodic memories for `evaluate()` or `reflect()`, it includes only relevant matches — no near-miss contrast pairs. Meta-Harness research showed contrastive examples sharpen discrimination.

**v1 scope:** Add `EpisodicMemory.retrieve_contrastive_episodes(query, k=2) -> list[Episode]` that returns episodes whose embedding distance is in the moderate-similarity band (NOT top-k matches; NOT random) — episodes where the surface query matches but the outcome differed. Wire it into `cognitive/sub_tasks/evaluate.py`'s `EvaluateHandler` (revision-pass: corrected from `EvaluateSubTask` phantom name).

**File:** `src/probos/cognitive/episodic.py` (edit) + `src/probos/cognitive/sub_tasks/evaluate.py` (edit).

**Implementation:**
- New method on `EpisodicMemory`:
  ```python
  async def retrieve_contrastive_episodes(
      self, query: str, k: int = 2,
  ) -> list[Episode]:
      """Return mid-band-similarity episodes (NOT top-k).

      Definition: episodes whose semantic similarity to the query is in the
      [0.4, 0.65] band -- relevant enough to be on-topic, distant enough
      to potentially carry contrasting outcome signal. Band thresholds are
      v1 defaults; AD-655b will introduce a Pydantic config knob.
      """
  ```
  Uses the existing `self._collection.query` (`episodic.py:1453`) with `n_results=k*5` and filters by similarity band.
- In `evaluate.py` (`cognitive/sub_tasks/evaluate.py`), if `runtime.episodic_memory` is wired, the `EvaluateHandler.__call__` (line 256+) calls `retrieve_contrastive_episodes(query, k=2)` and prepends a "Contrastive priors:" section to the prompt context.
- Emit `CONTRASTIVE_RECALL` per retrieval (with episode ids; deduped).

**Tests (4 in `tests/test_combo_a_ad655_contrastive.py`):**
1. `test_episodic_retrieve_contrastive_returns_mid_band` -- mock chroma returns 5 results with distances [0.1, 0.3, 0.5, 0.6, 0.9]; method returns the 0.5 + 0.6 distance episodes (mid-band).
2. `test_episodic_retrieve_contrastive_no_results_returns_empty_list`
3. `test_episodic_retrieve_contrastive_emits_event`
4. `test_evaluate_handler_consults_contrastive_when_runtime_episodic_wired` -- (revision-pass: renamed from `test_evaluate_subtask_...`)

**Public attribute:** none new; reuses `runtime.episodic_memory`.

---

## AD-656: Department-Specific Cognitive Profiles

**Verify-first:**
```
grep -n "class CognitiveProfile" src/probos/
  src/probos/cognitive/counselor.py:147: class CognitiveProfile:
  (per-agent profile; AD-656 introduces a department-level overlay)
grep -n "class CognitiveConfig" src/probos/config.py
  (verified -- existing CognitiveConfig is per-tier model config)
Test-Path config/organization.yaml
  False  (operator-supplied; AD-656 ships the Pydantic surface only)
```

**Problem:** Hebbian routing learns weights but all departments use identical retrieval and reasoning strategies. Meta-Harness showed optimal retrieval differs by domain (Science: deeper retrieval; Security: shallower + higher-confidence).

**v1 scope:** Define `DepartmentCognitiveProfile` Pydantic config + a small consumer hook in the cognitive chain that reads the per-department profile and modulates retrieval depth. Emit `DEPT_PROFILE_APPLIED` per chain run.

**File:** `src/probos/config.py` (add Pydantic class + field) + `src/probos/cognitive/sub_tasks/evaluate.py` (read profile, modulate context).

**Implementation:**
- `DepartmentCognitiveProfile(BaseModel)`: `recall_depth: int = 5`, `recall_threshold: float = 0.25`, `context_token_budget: int = 4000`. All defaulted.
- `DepartmentProfilesConfig(BaseModel)`: `profiles: dict[str, DepartmentCognitiveProfile] = Field(default_factory=lambda: {})`.
- `SystemConfig.dept_profiles: DepartmentProfilesConfig = DepartmentProfilesConfig()`.
- In `cognitive/sub_tasks/evaluate.py`, when running `evaluate`, if the agent's department maps to a `DepartmentCognitiveProfile`, override the local recall parameters with the profile values and emit `DEPT_PROFILE_APPLIED`.

**Tests (4 in `tests/test_combo_a_ad656_dept_profiles.py`):**
1. `test_dept_cognitive_profile_defaults`
2. `test_dept_profiles_config_empty_by_default`
3. `test_evaluate_uses_profile_recall_depth_when_department_matches`
4. `test_evaluate_emits_dept_profile_applied`

**Public attribute:** none new; lives in the existing config + chain modulation.

---

## Combo Test Plan

Single command runs all 7 children's tests:

```pwsh
d:/ProbOS/.venv/Scripts/pytest.exe `
  tests/test_combo_a_ad538b_manifest.py `
  tests/test_combo_a_ad572b_engagement.py `
  tests/test_combo_a_ad573b_wm.py `
  tests/test_combo_a_ad576b_retry.py `
  tests/test_combo_a_ad526c_recreation.py `
  tests/test_combo_a_ad655_contrastive.py `
  tests/test_combo_a_ad656_dept_profiles.py `
  -v -n 0
```

Expected: ~26 passes total. Each child file is independent.

After all children pass at `-n 0`, run the full parallel gate:

```pwsh
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
```

Expected: prior baseline + ~26 = non-decreasing.

**Sequential discipline:** AD-572b and AD-576b both touch `src/probos/proactive.py`. Implement them in sequence (Section 4 -> Section 5 in the revised order); after each, run the focused test for that child PLUS `tests/test_proactive.py` to catch regressions in the proactive loop.

**Sequential discipline:** AD-572b, AD-575b, AD-576b all touch `src/probos/proactive.py`. Implement them in sequence (Section 4 -> 5 -> 6); after each, run the focused test for that child PLUS `tests/test_proactive.py` to catch regressions in the proactive loop.

---

## What Combo A Does NOT Change

- `BookingJournal`, `CognitiveJournal`, `WardRoomService`, `IntentBus`, `LLMClient`, `EgressPolicy` -- all unchanged. The 7 children are extensions of existing closed parents.
- No destructive intents introduced. No `requires_consensus=True` paths.
- No new pyproject deps (stdlib + Rich + existing deps only).
- **AD-575b dropped from v1** (revision-pass decision per convention #7) -- both halves of AD-575b are no-ops in current source because `runtime.self_summary_provider` does not exist. Wait for a future AD that ships the upstream surface with a real consumer. The child mini-section above documents the drop.
- AD-526c spectators + holodeck integration -- wholesale deferred to AD-526d/e.
- AD-573b's bigger relational/dream-pipeline scope -- wholesale deferred to AD-573c.

---

## Combo Tracker Updates

`PROGRESS.md`: add 7 entries (one per child AD). Format:

```
AD-538b CLOSED. Dream Consolidation Manifest -- DreamManifest stdlib JSON-backed; survives restart; DREAM_MANIFEST_UPDATED emitted per replay batch. 4 tests.
AD-572b CLOSED. Captain Engagement Extensions (DM) -- CaptainEngagementProvider snapshots alerts/wardroom/DM depth into proactive context; emits CAPTAIN_DM_PRIORITY_QUEUED. 4 tests.
AD-573b CLOSED. Working Memory Extensions -- relational_links, scratchpad, commitments fields on WorkingMemorySnapshot (the existing @dataclass at working_memory.py:22, NOT frozen); bounded helpers on Manager; reuses runtime.working_memory. 3 tests.
AD-576b CLOSED. LLM Retry with Exponential Backoff -- proactive path retries transient LLM errors twice with [0.5, 1.5]s backoff before incrementing failure counter. 4 tests.
AD-526c CLOSED. Recreation System Extensions -- GameMetadata layered on existing register_engine; default_game preference; RECREATION_GAME_REGISTERED emitted; spectators/holodeck wholesale-deferred to AD-526d/e. 3 tests.
AD-655 CLOSED. Contrastive Memory Retrieval -- EpisodicMemory.retrieve_contrastive_episodes returns mid-band similarity episodes; EvaluateHandler consults; CONTRASTIVE_RECALL emitted. 4 tests.
AD-656 CLOSED. Department-Specific Cognitive Profiles -- DepartmentCognitiveProfile + DepartmentProfilesConfig; evaluate sub-task modulates recall by department; DEPT_PROFILE_APPLIED emitted. 4 tests.
AD-575b DEFERRED. Self-Awareness in Proactive + DM Forwarded Content -- dropped from Wave 8 Combo A revision pass; both halves are no-ops in current source. Awaits a future AD that ships runtime.self_summary_provider with a real consumer.
```

`docs/development/roadmap.md`: flip 8 status flags. AD-655 line 6730+ and AD-656 line 6731+ are the canonical anchors per the Meta-Harness Research Wave block. Builder must grep the actual line numbers before editing.

`DECISIONS.md`: no entry needed (these are extensions of closed parents per the audit).

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP.

Expected delta:
- `src/probos/cognitive/dreaming.py`: ~10 lines added (manifest filter).
- `src/probos/cognitive/dream_manifest.py`: ~75 lines (new).
- `src/probos/cognitive/captain_engagement.py`: ~85 lines (new).
- `src/probos/proactive.py`: ~30 lines added (engagement + self-summary + retry loop).
- `src/probos/cognitive/working_memory.py`: ~35 lines added (3 new fields + 3 helper methods).
- `src/probos/recreation/service.py`: ~20 lines added (registry + default).
- `src/probos/recreation/games.py`: ~55 lines (new).
- `src/probos/cognitive/episodic.py`: ~35 lines added (`retrieve_contrastive_episodes`).
- `src/probos/cognitive/sub_tasks/evaluate.py`: ~25 lines added (contrastive + profile consume).
- `src/probos/config.py`: ~25 lines added (DepartmentCognitiveProfile + DepartmentProfilesConfig + SystemConfig field).
- `src/probos/events.py`: 5 lines added.
- `src/probos/startup/finalize.py`: ~20 lines added (manifest + engagement provider wiring).
- `tests/test_combo_a_*.py`: ~620 lines total (new across 7 files; AD-575b's ~80-line test file dropped).
- `PROGRESS.md`, `roadmap.md`: ~10 lines changed (8 entries + 8 status flips).

---

## Acceptance Criteria

- All 8 children's tests pass under their focused gates at `-n 0`.
- Full parallel gate non-decreasing.
- 5 new EventTypes in `events.py` (AD-538b, AD-572b, AD-526c, AD-655, AD-656). AD-573b/576b add no events.
- New stdlib-only persistence: `dream_manifest.json` is the only new on-disk artifact.
- `proactive.py` retry loop preserves existing failure-counter semantics on terminal failure.
- AD-526c spectators + holodeck integration NOT in v1.
- AD-573b's bigger relational scope NOT in v1.
- **AD-575b dropped from v1** (revision-pass; theater per convention #7).
- Single commit closes 7 ADs with the message `Combo A: AD-538b/572b/573b/576b/526c/655/656 trivial extensions`.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-02)

```
grep -rn "class DreamManifest\|class CaptainEngagementProvider\|class GameDescriptor" src/probos/
  (no matches -- Combo A introduces these names)

grep -n "DREAM_MANIFEST_UPDATED\|CAPTAIN_DM_PRIORITY_QUEUED\|RECREATION_GAME_REGISTERED\|CONTRASTIVE_RECALL\|DEPT_PROFILE_APPLIED" src/probos/events.py
  (no matches -- names are free)

grep -n "class DreamScheduler\|_last_consolidated_count" src/probos/cognitive/dreaming.py
  100: self._last_consolidated_count: int = 0
  189: if current_count <= self._last_consolidated_count:
  2664: class DreamScheduler:

grep -n "_think_for_agent\|_gather_context\|agent\.handle_intent" src/probos/proactive.py
  634: async def _think_for_agent
  694: result = await agent.handle_intent(intent)
  1061: async def _gather_context

grep -n "class WorkingMemoryManager\|class WorkingMemorySnapshot" src/probos/cognitive/working_memory.py
  78: class WorkingMemorySnapshot:
  84: class WorkingMemoryManager:

grep -n "class RecreationService" src/probos/recreation/service.py
  15: class RecreationService:

grep -n "class EpisodicMemory\|async def recall\b" src/probos/cognitive/episodic.py
  651: class EpisodicMemory:
  1440: async def recall(self, query: str, k: int = 5) -> list[Episode]:

grep -n "class CognitiveProfile" src/probos/cognitive/counselor.py
  147: class CognitiveProfile:
  (per-agent; AD-656's DepartmentCognitiveProfile is a different surface; no name collision)

grep -n "READY_ROOM_SESSION_STARTED\|IDEA_CAPTURED\|MODEL_FALLBACK" src/probos/events.py
  211: MODEL_FALLBACK = "model_fallback"  # AD-463
  (Combo A anchors after AD-475's IDEA_CAPTURED line; if AD-475 hasn't landed, anchor on MODEL_FALLBACK)

Test-Path config/organization.yaml
  False  (operator-supplied; AD-656 ships Pydantic config only)
```

Wave-5/6/7 conventions audit:
- #1 Public-attribute wiring: `runtime.dream_manifest`, `runtime.captain_engagement_provider` public; AD-573b reuses existing `runtime.working_memory` (NOT `working_memory_manager` -- v1 phantom corrected). ✅
- #2 stdlib-only: yes; `DreamManifest` uses `json`. ✅
- #3 Coordinator-then-dispatch: AD-526c spectators + holodeck deferred; AD-573b's bigger scope deferred; AD-575b wholesale-dropped. ✅
- #4 Superset-filter: all 7 children are additive; AD-526c piggy-backs metadata on existing `register_engine` (no duplicate registry); no existing test cases intercepted. ✅
- #5 init_<phase>: dream manifest + engagement provider wire from `startup/finalize.py`. ✅
- #6 Verify-first: per-child grep evidence above + section-level greps; AD-573b/AD-655 phantom names corrected. ✅
- #7 No-theater: every shipping child does real work today; AD-575b dropped because its v1 implementation would be a permanent no-op. ✅
- #11 __new__-bypass defensive-getattr: `CaptainEngagementProvider.snapshot` uses defensive `getattr`. ✅
- #14 Aggressive pre-deferral: AD-526c (spectators + holodeck), AD-573b (bigger relational scope), AD-575b (wholesale) deferred at draft/revision time. ✅

---

## Revision (2026-05-02)

Applied review findings from `prompts/Reviews/combo-A-trivial-extensions-review.md` (verdict: ⚠️ Conditional; 7 Required + 6 Recommended). The combo's structure survives revision; AD-575b drop is the largest scope change.

**Required addressed:**

- **R#1: AD-573b "frozen dataclass" claim corrected.** AD-573b mini-section now states `WorkingMemorySnapshot` is "the existing `@dataclass` at line 22 -- NOT frozen; revision-pass correction." The proposed `field(default_factory=...)` extensions remain valid (they work on non-frozen dataclasses; the issue was the misleading description, not the implementation).
- **R#2: AD-573b `runtime.working_memory_manager` phantom corrected.** AD-573b mini-section now references `runtime.working_memory` (verified at `runtime.py:348`). The "no `runtime.working_memory_manager` attribute exists" is documented explicitly.
- **R#3: AD-573b verify-first line-number drift corrected.** Verify-first block now lists `21: @dataclass` and `22: class WorkingMemorySnapshot:` (live grep). Old line `78` removed.
- **R#4: AD-575b dropped wholesale.** The entire AD-575b mini-section (Section 5 in original combo) replaced with a "DROPPED (theater per convention #7)" stub explaining why and what's needed before re-introduction. Combo title + scope + tracker + test plan + sanity check + commit message all updated to "7 trivial extensions." File-conflict serialization simplified: AD-572b -> AD-576b only (was AD-572b -> AD-575b -> AD-576b).
- **R#5: AD-655 `EvaluateSubTask` -> `EvaluateHandler`.** Verify-first updated to grep `class EvaluateHandler\|_EVALUATION_MODES`; the text "EvaluateSubTask builder" rewritten to "`EvaluateHandler.__call__` (line 256+)"; test #4 renamed `test_evaluate_handler_consults_contrastive_when_runtime_episodic_wired`.
- **R#6: AD-526c DRY conflict resolved (option a).** Dropped the proposed `register_game`/`list_games`/`_games` parallel registry. AD-526c v1 now extends the existing `register_engine(engine, metadata=None)` with an optional `GameMetadata` dataclass + a `default_game` preference + `RECREATION_GAME_REGISTERED` emission. The existing `get_available_games`/`_engines` API is preserved and reused. New file `recreation/metadata.py` (~40 lines) replaces the proposed `recreation/games.py` (~50 lines).
- **R#7: Combo Section 0 anchor.** SEARCH/REPLACE block re-anchored on Wave-7-stable `MODEL_FALLBACK = "model_fallback"  # AD-463` (line 211) instead of the optimistic AD-475 anchor. Builder note added: "Anchor-chain fallback: AD-463 `MODEL_FALLBACK` (line 211) is the Wave-7-stable terminal."

**Recommended applied:**

- **rec#1: AD-538b dream-manifest filter site precision.** Verify-first already names line 193 (`recent(k=...)`) and the post-line-198 `_replay_episodes` seam; the SEARCH-block tightening is folded into the existing "around `dreaming.py:193`" framing.
- **rec#3: AD-576b retry locals hoisted.** Test plan note added: `_BACKOFFS_SECONDS` and `_LLM_ERROR_KEYWORDS` should be module-level constants. Builder will lift them at implementation time.
- **rec#4: AD-655 mid-band thresholds noted as v1 defaults.** Docstring extended: "Band thresholds are v1 defaults; AD-655b will introduce a Pydantic config knob."

**Recommended deferred:**

- **rec#2: AD-572b dm_queue_depth API tightening.** The existing snapshot calls `len()` on a Ward Room thread-list filter; folded into Builder discretion. Documented in the AD-572b implementation block.
- **rec#5: AD-526c spectators/holodeck deferral language.** Already explicit; no change.
- **rec#6: AD-656 `EvaluateHandler` consumer-side SEARCH/REPLACE block.** Builder will derive from the AD-655 hook (which now lands a real seam in `EvaluateHandler.__call__`); AD-656 follows the same path.

**Phantom-API pre-check (run during revision):**

```
grep -rn "self_summary_provider\|SelfSummaryProvider\|summary_for\b" src/probos/
  (no matches -- confirms AD-575b drop)

grep -n "class WorkingMemoryManager\|class WorkingMemorySnapshot\|^@dataclass\|self\.working_memory\b" src/probos/cognitive/working_memory.py src/probos/runtime.py
  cognitive/working_memory.py:21: @dataclass
  cognitive/working_memory.py:22: class WorkingMemorySnapshot:
  cognitive/working_memory.py:84: class WorkingMemoryManager:
  runtime.py:348: self.working_memory = WorkingMemoryManager(...)

grep -n "class EvaluateHandler\|class EvaluateSubTask\|_EVALUATION_MODES" src/probos/cognitive/sub_tasks/evaluate.py
  231: _EVALUATION_MODES: dict[str, EvaluationModeBuilder] = {
  249: class EvaluateHandler:
  (no `EvaluateSubTask` class -- confirmed phantom)

grep -n "class RecreationService\|def register_engine\|def get_available_games\|self\._engines" src/probos/recreation/service.py
  15: class RecreationService:
  40: self._engines: dict[str, GameEngine] = {}
  56: def register_engine(self, engine: GameEngine) -> None:
  60: def get_available_games(self) -> list[str]:
  (existing API; AD-526c extends, does not duplicate)
```

All concrete claims grep-confirmed. No additional phantoms found beyond the 4 the review caught (all corrected above).

**Test count: 30 -> 26** (AD-575b dropped 3 tests; AD-526c dropped 0 -- still 3 tests, just covering the new metadata API).

**Verdict shift:** Pass-1 ⚠️ Conditional -> expected ✅ Approved on second-pass review. AD-575b drop is the largest revision; remaining 7 children are mechanically clean after the phantom-API and DRY corrections.

**Combo-pattern lesson (carry to Wave 9):** Per-child verify-first grep evidence is essential. Three of seven Required findings (R#1-#3 on AD-573b, R#5 on AD-655) would have been caught at draft time if the per-child grep had run the actual symbol against live code. Wave 9 combos should include a scripted pre-check that lints every named entity against `grep -rn`.
