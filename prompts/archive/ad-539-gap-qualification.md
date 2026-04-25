# AD-539: Knowledge Gap → Qualification Pipeline

**Type:** Build Prompt
**AD:** 539
**Title:** Knowledge Gap → Qualification Pipeline
**Depends:** AD-531 ✅ (Episode Clustering), AD-538 ✅ (Procedure Lifecycle — decay/failures), AD-428 ✅ (Skill Framework), AD-385 ✅ (Gap Predictor), AD-503 ✅ (Counselor Activation), RecordsStore ✅ (existing)
**Branch:** `ad-539-gap-qualification`

---

## Context

Capability gaps are invisible. If an agent repeatedly fails at a task type, no one notices until the Captain observes it manually. The system has infrastructure for detecting failure patterns (AD-531 failure-dominant clusters, AD-385 gap predictor, AD-538 procedure decay) and infrastructure for tracking competency (AD-428 Skill Framework with qualification paths). But these two systems are disconnected — failure detection doesn't feed competency tracking, and competency tracking doesn't know about operational failures.

AD-539 closes the loop. Episode clustering failures + procedure decay + procedure health diagnosis → **gap detection** → **gap classification** (knowledge gap, capability gap, data gap) → **qualification integration** (map gaps to skills, check proficiency, trigger qualification paths) → **Counselor awareness** (gaps feed wellness assessments) → **progress tracking** (gap closure measured by procedure improvement and skill proficiency growth). Gap reports are persisted to Ship's Records for institutional memory.

This is the final AD in the Cognitive JIT pipeline (9/9). After AD-539, the full lifecycle is operational: episodes cluster → procedures extract → procedures store → replay at graduated levels → promote through governance → learn from peers → decay/archive/dedup → **identify gaps → map to qualifications → track closure**.

**Intellectual lineage:**
- **Schön (1983)** — Reflective Practice. Professionals improve by reflecting on what went wrong, not just by accumulating experience. Gap detection is systematic reflection.
- **Dreyfus & Dreyfus (1986)** — Skill acquisition model underpins both AD-535's compilation levels AND the Skill Framework's proficiency levels. Gap detection identifies where an agent is stuck on the Dreyfus curve.
- **Argyris & Schön (1978)** — Double-loop learning. Single-loop: did the procedure work? Double-loop: should we change how we approach this problem type? Gap classification is double-loop learning.

---

## Engineering Principles Compliance

- **SOLID (S):** Gap detection is a new function in `gap_predictor.py` (`detect_gaps_from_clusters_and_procedures()`), separate from existing `predict_gaps()`. Gap classification is a new function. Qualification bridging is a new service method. Each concern is a distinct function.
- **SOLID (O):** Extends DreamingEngine via enhanced Step 8 (adds cluster + procedure evidence to existing gap prediction). Extends Counselor via new event subscription. No modification to existing SkillFramework methods.
- **SOLID (D):** Depends on ProcedureStore, SkillFramework (AgentSkillService), Counselor abstractions. Constructor injection.
- **Law of Demeter:** Query Skill Framework via public `get_profile()`, `update_proficiency()`, `record_exercise()` APIs. Don't reach into SQLite.
- **Fail Fast:** If Skill Framework is unavailable, gap detection still works (just skips qualification integration). If Counselor is unavailable, gap reports are still generated.
- **DRY:** Reuse existing `predict_gaps()` for episode-level gaps. New `detect_gaps_from_clusters_and_procedures()` adds cluster + procedure evidence types. Reuse `RecordsStore.write_entry()` for gap report persistence.
- **Cloud-Ready Storage:** Gap reports stored via RecordsStore (Git-backed). No new SQLite tables needed — gaps are transient analysis results persisted as documents, not relational data.

---

## What NOT to Build

- **AD-539b (Holodeck Scenario Generation)** — When the Holodeck exists, gap reports should feed scenario generation ("Agent Worf fails at static analysis interpretation 40% of the time → generate 10 exercises"). Holodeck does not exist. Defer. AD-539b is the bridge.
- **AD-539c (Automatic Remediation)** — Automatically reassigning work away from agents with persistent gaps. Requires Workforce Scheduling Engine (AD-496–498). Defer.
- **AD-539d (Fleet-Level Gap Aggregation)** — Cross-instance gap analysis across federated ProbOS instances. Requires federation gossip protocol. Defer. Nooplex-era feature.
- **Skill-weighted task routing** — AD-428b deferred feature. Using gap data to adjust routing weights is an enrichment, not core.
- **Gap-driven agent creation** — Detecting that NO agent can handle a task type and recommending a new agent type. This is career planning, not gap analysis. Future AD.

---

## What to Build

### Part 0: Config Constants

File: `src/probos/config.py`

Add constants:

```python
# AD-539: Gap → Qualification Pipeline
GAP_MIN_FAILURE_RATE: float = 0.30         # Cluster failure rate threshold for gap detection
GAP_MIN_EPISODES: int = 5                  # Minimum episodes in cluster to qualify as gap evidence
GAP_MIN_PROCEDURE_FAILURES: int = 3        # Minimum procedure failures to constitute a gap
GAP_PROFICIENCY_TARGET: int = 3            # Target ProficiencyLevel (APPLY) for gap closure
GAP_REPORT_MAX_PER_DREAM: int = 10         # Cap gap reports per dream cycle
```

---

### Part 1: GapReport Data Model

File: `src/probos/cognitive/gap_predictor.py`

Add a new dataclass `GapReport` below the existing `CapabilityGapPrediction`:

```python
@dataclass
class GapReport:
    """A classified knowledge gap linked to skill framework and qualification paths."""
    id: str                          # e.g., "gap:agent_type:intent_type:timestamp_hex"
    agent_id: str                    # which agent has the gap
    agent_type: str                  # agent type for skill mapping
    gap_type: str                    # "knowledge" | "capability" | "data"
    description: str                 # human-readable gap description
    evidence_sources: list[str]      # list of evidence tags: "failure_cluster:X", "procedure_decay:Y", "low_confidence:Z"
    affected_intent_types: list[str] # intent types where the gap manifests
    failure_rate: float              # aggregate failure rate across evidence
    episode_count: int               # total supporting episodes
    mapped_skill_id: str             # Skill Framework skill_id (if mappable, else "")
    current_proficiency: int         # agent's current proficiency level (0 if no record)
    target_proficiency: int          # target proficiency for gap closure (from config)
    qualification_path_id: str       # qualification path triggered (if any, else "")
    priority: str                    # "low" | "medium" | "high" | "critical"
    created_at: float = field(default_factory=time.time)
    resolved: bool = False           # set True when gap closure criteria met
    resolved_at: float | None = None
```

Add `to_dict()` method.

**Gap classification logic** — new function `classify_gap()`:

```python
def classify_gap(
    evidence_type: str,
    failure_rate: float,
    episode_count: int,
) -> str:
    """Classify a gap as knowledge, capability, or data.

    - knowledge: agent doesn't know how (training helps)
      Evidence: low confidence, procedure failures, decay
    - capability: agent fundamentally can't do this (escalation needed)
      Evidence: very high failure rate (>80%) with many attempts (>10)
    - data: agent lacks information (information routing problem)
      Evidence: repeated fallback with no matching intent
    """
```

Rules (first match wins):
- `evidence_type == "repeated_fallback"` → `"data"` (no intent exists for this request type)
- `failure_rate > 0.80 and episode_count >= 10` → `"capability"` (tried many times, can't do it)
- Default → `"knowledge"` (most gaps are knowledge gaps — training helps)

---

### Part 2: Multi-Source Gap Detection

File: `src/probos/cognitive/gap_predictor.py`

New function: `detect_gaps()`

```python
def detect_gaps(
    episodes: list,
    clusters: list,                       # EpisodeCluster list from Step 6
    procedure_decay_results: list[dict],  # from decay_stale_procedures()
    procedure_health_results: list[dict], # from diagnose_procedure_health() scans
    agent_id: str = "",
    agent_type: str = "",
) -> list[GapReport]:
```

**This function aggregates evidence from 4 sources:**

1. **Existing `predict_gaps()` results** — call the existing function on the episodes. Convert each `CapabilityGapPrediction` to a `GapReport` with `evidence_sources=["episode:{prediction.evidence_type}"]`.

2. **Failure-dominant clusters** (AD-531) — for each cluster where `is_failure_dominant == True` and `episode_count >= GAP_MIN_EPISODES`:
   - Calculate failure rate: `1.0 - cluster.success_rate`
   - If `failure_rate >= GAP_MIN_FAILURE_RATE`:
     - Create a `GapReport` with `evidence_sources=["failure_cluster:{cluster.cluster_id}"]`
     - `affected_intent_types = cluster.intent_types`
     - `episode_count = cluster.episode_count`

3. **Procedure decay** (AD-538) — for each decayed procedure in `procedure_decay_results`:
   - A decayed procedure indicates capability atrophy — the agent isn't using this skill
   - Create a `GapReport` with `evidence_sources=["procedure_decay:{proc_id}"]`
   - `gap_type = "knowledge"` (decay is always a knowledge gap — refresher training helps)
   - `priority = "low"` (decay is gentle — might just mean the task type isn't occurring)

4. **Procedure health diagnosis** (AD-538/532b) — for each procedure with a health diagnosis:
   - `"FIX:high_fallback_rate"` → indicates the procedure doesn't work reliably
   - `"FIX:low_completion"` → indicates the procedure starts but can't finish
   - `"DERIVED:low_effective_rate"` → indicates the procedure is ineffective
   - Create a `GapReport` with `evidence_sources=["procedure_health:{diagnosis}:{proc_id}"]`
   - Priority higher than decay: `"medium"` for FIX, `"low"` for DERIVED

**Deduplication:** If the same `affected_intent_types` appear across multiple evidence sources (e.g., both a failure cluster AND a decayed procedure cover `code_review`), merge into a single `GapReport` with combined `evidence_sources` and the higher priority.

**Cap output** at `GAP_REPORT_MAX_PER_DREAM`.

---

### Part 3: Skill Framework Bridge

File: `src/probos/cognitive/gap_predictor.py`

New function: `map_gap_to_skill()`

```python
async def map_gap_to_skill(
    gap: GapReport,
    skill_service: Any,   # AgentSkillService
) -> GapReport:
    """Map a gap's intent types to a Skill Framework skill and check proficiency."""
```

**How it works:**

1. **Intent → Skill mapping.** Use a simple heuristic: check if any of the gap's `affected_intent_types` match a `SkillDefinition.skill_id` or `SkillDefinition.domain` in the registry. For example:
   - Intent type `code_review` → skill `code_review` (exact match) or domain `engineering` (domain match)
   - Intent type `security_scan` → skill `threat_analysis` (role skill for security_officer)
   - If no direct match, map to the most relevant PCC (e.g., `duty_execution` as fallback)

   Build a mapping function `_intent_to_skill_id()` that:
   - First tries exact match against registered skill IDs
   - Then tries domain match against agent's role skill templates
   - Falls back to `duty_execution` PCC if no match

2. **Check current proficiency.** Call `skill_service.get_profile(gap.agent_id)` and look up the matched skill's `proficiency` level.

3. **Set target proficiency** from `GAP_PROFICIENCY_TARGET` (default: APPLY = 3).

4. **Update the gap report** with `mapped_skill_id`, `current_proficiency`, `target_proficiency`.

5. Return the updated gap.

---

### Part 4: Qualification Path Triggering

File: `src/probos/cognitive/gap_predictor.py`

New function: `trigger_qualification_if_needed()`

```python
async def trigger_qualification_if_needed(
    gap: GapReport,
    skill_service: Any,   # AgentSkillService
) -> GapReport:
    """If the gap reveals proficiency below target, start a qualification path."""
```

**How it works:**

1. If `gap.mapped_skill_id == ""` → no skill mapping → skip.
2. If `gap.current_proficiency >= gap.target_proficiency` → already proficient → skip.
3. If `gap.gap_type == "capability"` → can't be trained → skip (needs escalation, not qualification).
4. If `gap.gap_type == "data"` → information gap → skip (needs routing fix, not training).

5. **Check if a qualification path already exists** for this agent via `skill_service.get_qualification_record(gap.agent_id, relevant_path_id)`. If it exists and is incomplete, just link it — don't create a duplicate.

6. **Determine the qualification path ID.** Use the agent's current rank to build the path: e.g., if the agent is an Ensign, the path is `"ensign_to_lieutenant"`. The gap adds a requirement to the path: the mapped skill must reach `target_proficiency`.

7. **If no existing path**, call `skill_service.start_qualification(gap.agent_id, path_id)`.

8. Update the gap report with `qualification_path_id`.

9. Return the updated gap.

**Note:** The Skill Framework's `evaluate_qualification()` already handles checking PCC and role skill requirements against qualification paths. AD-539 doesn't need to duplicate that logic — it just needs to ensure the gap's skill requirement is captured in the qualification path.

---

### Part 5: Enhanced Dream Step 8

File: `src/probos/cognitive/dreaming.py`

**Enhance existing Step 8** (gap prediction) to incorporate the new multi-source gap detection.

Currently Step 8 (lines 405-412) only calls `predict_gaps(episodes)`. Enhance it to:

1. Call `detect_gaps()` with:
   - `episodes` — existing episode list
   - `clusters` — from Step 6 (`self._last_clusters`)
   - `procedure_decay_results` — from Step 7f (capture the return value)
   - `procedure_health_results` — scan active procedures via `diagnose_procedure_health()`
   - `agent_id` and `agent_type` — from runtime context

2. For each `GapReport`:
   a. Call `map_gap_to_skill()` (if Skill Framework available)
   b. Call `trigger_qualification_if_needed()` (if Skill Framework available)
   c. Write to Ship's Records via `RecordsStore.write_entry()` (if available): path `reports/gap-reports/{gap.id}.md`, classification `"ship"`, topic `"gap_analysis"`, tags `["ad-539", gap.gap_type, gap.priority]`

3. Emit `GAP_IDENTIFIED` event for each gap (for Counselor subscription). Pass the `GapReport.to_dict()` as event data.

4. Update DreamReport with new fields.

5. Call existing `_gap_prediction_fn` callback with the combined results (backward compatibility).

**Important:** Capture Step 7f's `decay_results` and `procedure_health_scan` results and pass them to Step 8. Currently Step 7f's return values aren't stored. Either:
- Store them on `self._last_decay_results` and `self._last_health_results` (same pattern as `self._last_clusters`)
- Or restructure so Step 8 receives them as parameters

---

### Part 6: Counselor Integration

File: `src/probos/cognitive/counselor.py`

**6a: Subscribe to GAP_IDENTIFIED event.**

Add `GAP_IDENTIFIED` to the event subscriptions (follow the existing pattern for `TRUST_UPDATE`, `CIRCUIT_BREAKER_TRIP`, etc.).

**6b: Handler method `_on_gap_identified()`:**

```python
async def _on_gap_identified(self, event_data: dict) -> None:
```

When a gap is identified:
1. Get or create `CognitiveProfile` for the agent.
2. Add the gap to the profile's `concerns` list: `"Knowledge gap in {intent}: {description} (priority: {priority})"`.
3. If the gap is `"capability"` type, flag `fit_for_promotion = False` until resolved.
4. If the gap priority is `"high"` or `"critical"`, send a therapeutic DM to the agent (rate-limited, follow existing DM pattern) acknowledging the gap and recommending focus on the qualification path.
5. Log the integration: "Counselor noted gap for {agent}: {gap.description}".

**6c: Gap-aware fitness assessment.**

In the existing `assess_agent()` method, add a check: if the agent has unresolved `"high"` or `"critical"` gaps in their profile concerns, note it in the assessment's `concerns` and reduce `fit_for_promotion` likelihood. Don't modify existing assessment logic heavily — this is additive.

---

### Part 7: Progress Tracking

File: `src/probos/cognitive/gap_predictor.py`

New function: `check_gap_closure()`

```python
async def check_gap_closure(
    gap: GapReport,
    skill_service: Any,
    procedure_store: Any,
) -> bool:
    """Check if a gap has been closed based on:
    1. Skill proficiency reached target level
    2. Procedure effective_rate improved above threshold
    3. Recent failure rate decreased below GAP_MIN_FAILURE_RATE
    """
```

Logic:
1. If `mapped_skill_id` is set, check current proficiency via `skill_service.get_profile()`. If `proficiency >= target_proficiency` → gap closure signal.
2. If the gap has procedure evidence, check quality metrics via `procedure_store.get_quality_metrics()`. If `effective_rate > PROMOTION_MIN_EFFECTIVE_RATE` → gap closure signal.
3. Both signals must be positive for closure. If only one, the gap is "improving" but not closed.

**Where this is called:** During Dream Step 8, after generating new gaps, also evaluate existing unresolved gaps for potential closure. This requires persisting gap state — use Ship's Records. On each dream cycle, load existing gap reports from Ship's Records, run `check_gap_closure()`, and update the YAML document if resolved.

**Pragmatic simplification:** For the initial implementation, gap closure detection can be done during the Captain's manual review via a shell command (`/gap check`), rather than automatically on every dream cycle. Dream cycle generates the gap; manual review closes it. This keeps Step 8 fast and avoids complex state management for the MVP.

---

### Part 8: DreamReport Updates

File: `src/probos/types.py`

Add to the `DreamReport` dataclass:

```python
# AD-539: Gap → Qualification Pipeline
gaps_classified: int = 0
qualification_paths_triggered: int = 0
gap_reports_generated: int = 0
```

---

### Part 9: Shell Commands

File: `src/probos/experience/commands/commands_procedure.py` (or new `commands_gap.py`)

Add a new `/gap` command group:

**`/gap list [--agent <callsign>] [--type <knowledge|capability|data>] [--priority <low|medium|high|critical>]`**
- Lists open (unresolved) gap reports.
- Reads from Ship's Records `reports/gap-reports/`.
- Shows: agent, gap_type, description, priority, mapped_skill, current/target proficiency.

**`/gap detail <gap_id>`**
- Shows full gap report including evidence sources, qualification path status, creation date.

**`/gap check [<gap_id>]`**
- Runs `check_gap_closure()` on the specified gap (or all open gaps).
- Updates Ship's Records if resolved.
- Output: "Gap '{description}' resolved — {agent} reached proficiency {level} in {skill}" or "Gap still open — proficiency {current}/{target}."

**`/gap summary`**
- Aggregate view: total open gaps by type, by priority, by department.
- Shows which agents have the most gaps and which skills are most commonly deficient.

Register the `/gap` command in `shell.py`.

---

### Part 10: API Endpoints

File: `src/probos/routers/` — new `gaps.py` or extend `procedures.py`

**`GET /api/gaps`**
- Query params: `agent` (optional), `type` (optional), `priority` (optional), `resolved` (optional, default: `false`)
- Returns list of gap reports.

**`GET /api/gaps/{gap_id}`**
- Returns a single gap report with full detail.

**`POST /api/gaps/{gap_id}/check`**
- Runs gap closure check.
- Returns updated gap report with resolved status.

**`GET /api/gaps/summary`**
- Returns aggregate statistics: counts by type, priority, department, top affected skills.

Register the router in `api.py`.

---

### Part 11: EventType Addition

File: `src/probos/types.py` (or wherever `EventType` enum lives)

Add `GAP_IDENTIFIED` to the `EventType` enum (or use a string event type if the system uses string-based events).

Search for how existing event types like `TRUST_UPDATE`, `CIRCUIT_BREAKER_TRIP` are defined and follow the same pattern.

---

## Guard Rails

### What to check before each Part

1. **Read the file you're modifying** before making changes.
2. **Search for existing implementations** — `predict_gaps()`, `CapabilityGapPrediction`, `classify_gap` patterns.
3. **Run targeted tests** after each Part completes.
4. **Follow existing patterns** — Dream Step 7/8 pattern, Counselor event subscription pattern, shell command pattern, API router pattern.

### Interactions with existing code

- **`predict_gaps()` stays unchanged.** The existing function continues to work on raw episodes. `detect_gaps()` calls it internally and wraps results into `GapReport` objects.
- **Dream Step 8 enhancement** — the existing `predict_gaps(episodes)` call is subsumed by `detect_gaps()`. The `_gap_prediction_fn` callback still fires with backward-compatible data.
- **Step 7f results must be captured.** Currently `decay_stale_procedures()` and `archive_stale_procedures()` results are used to update DreamReport counters but not stored for Step 8 consumption. Store them on `self._last_decay_results` and `self._last_health_results`.
- **Counselor event subscriptions** — follow the exact pattern of `_on_trust_update()` handler. The Counselor subscribes to events via `_add_event_listener_fn`.
- **Ship's Records gap reports** — use YAML frontmatter: `classification: ship`, `status: open` or `resolved`, `department: <agent's department>`, `topic: gap_analysis`. Gap closure updates the status to `resolved`.

### Scope boundaries

- **No automatic task reassignment.** Gaps are informational. The Captain decides what to do (qualification path, reassignment, or acceptance). AD-539c covers automatic remediation.
- **No Holodeck scenarios.** Gap reports include enough detail for future scenario generation (intent types, failure patterns, affected skills), but AD-539b bridges to the Holodeck.
- **No cross-instance gaps.** Gap detection is per-ship. AD-539d covers federation-level aggregation.
- **Gap reports are documents, not relational data.** Stored as YAML in Ship's Records, not SQLite. This is intentional — gaps are analysis artifacts with a narrative structure (evidence, classification, recommendation), not transactional records.

---

## Deferred ADs

| AD | Title | Dependency | Description |
|----|-------|------------|-------------|
| AD-539b | Holodeck Scenario Generation | AD-539 ✅, Holodeck | Gap reports feed Holodeck scenario specification. "Agent Worf fails at static analysis 40% of the time" → generate 10 exercises with known answers. |
| AD-539c | Automatic Gap Remediation | AD-539 ✅, AD-496 (Workforce Scheduling) | Automatically adjust work routing away from agents with persistent unresolved gaps. Workforce Scheduling Engine reassigns work items based on gap severity. |
| AD-539d | Fleet-Level Gap Aggregation | AD-539 ✅, Federation Gossip | Cross-instance gap analysis. Aggregate gap patterns across federated ProbOS instances. Fleet-wide capability assessment for Nooplex workforce planning. |

---

## Tests

Target: **50-60 tests across 6 test files.**

### `tests/test_gap_detection.py` (~12 tests)

1. `test_detect_gaps_from_failure_clusters` — failure-dominant cluster → GapReport
2. `test_detect_gaps_skips_success_clusters` — success-dominant cluster → no gap
3. `test_detect_gaps_from_procedure_decay` — decayed procedure → GapReport
4. `test_detect_gaps_from_procedure_health` — FIX diagnosis → GapReport
5. `test_detect_gaps_from_episodes` — wraps existing predict_gaps() output
6. `test_detect_gaps_deduplicates` — same intent from multiple sources → single merged GapReport
7. `test_detect_gaps_respects_min_failure_rate` — cluster below threshold → no gap
8. `test_detect_gaps_respects_min_episodes` — cluster with too few episodes → no gap
9. `test_detect_gaps_caps_output` — more than GAP_REPORT_MAX_PER_DREAM → capped
10. `test_detect_gaps_priority_assignment` — high failure rate → high priority
11. `test_detect_gaps_empty_inputs` — no clusters, no decay, no episodes → empty list
12. `test_gap_report_to_dict` — serialization includes all fields

### `tests/test_gap_classification.py` (~8 tests)

1. `test_classify_knowledge_gap` — default classification
2. `test_classify_capability_gap` — high failure + many episodes
3. `test_classify_data_gap` — repeated_fallback evidence
4. `test_classify_boundary_failure_rate` — exactly at 80% threshold
5. `test_classify_boundary_episode_count` — exactly at 10 episodes
6. `test_gap_report_includes_classification` — GapReport.gap_type populated correctly
7. `test_map_gap_to_skill_exact_match` — intent matches skill_id directly
8. `test_map_gap_to_skill_fallback` — no match → duty_execution PCC

### `tests/test_gap_qualification.py` (~8 tests)

1. `test_trigger_qualification_for_knowledge_gap` — knowledge gap triggers qualification path
2. `test_skip_qualification_for_capability_gap` — capability gap → no qualification
3. `test_skip_qualification_for_data_gap` — data gap → no qualification
4. `test_skip_qualification_if_proficient` — already at target → no trigger
5. `test_skip_if_qualification_exists` — existing path → link, don't duplicate
6. `test_gap_closure_proficiency_reached` — proficiency at target → gap resolved
7. `test_gap_closure_partial` — one signal positive, one not → still open
8. `test_gap_closure_effective_rate_improved` — procedure effective_rate up → signal

### `tests/test_gap_dream_integration.py` (~8 tests)

1. `test_step_8_enhanced_with_clusters` — Step 8 uses failure clusters from Step 6
2. `test_step_8_uses_decay_results` — Step 8 consumes Step 7f decay results
3. `test_step_8_generates_gap_reports` — GapReport objects generated in dream
4. `test_step_8_writes_to_records` — Ship's Records receives gap YAML (if available)
5. `test_step_8_emits_gap_events` — GAP_IDENTIFIED events emitted
6. `test_step_8_updates_dream_report` — gaps_classified, qualification_paths_triggered, gap_reports_generated
7. `test_step_8_backward_compatible` — _gap_prediction_fn callback still fires
8. `test_step_8_no_skill_framework_graceful` — no SkillFramework→ detection works, qualification skipped

### `tests/test_gap_commands.py` (~7 tests)

1. `test_gap_list_command` — `/gap list` shows open gaps
2. `test_gap_list_filter_by_agent` — `--agent` filter works
3. `test_gap_list_filter_by_type` — `--type knowledge` filter works
4. `test_gap_detail_command` — `/gap detail <id>` shows full report
5. `test_gap_check_command` — `/gap check` runs closure check
6. `test_gap_summary_command` — `/gap summary` shows aggregates
7. `test_gap_check_resolves` — `/gap check` marks resolved gap

### `tests/test_gap_routing.py` (~7 tests)

1. `test_api_gaps_list_endpoint` — GET `/api/gaps` returns gaps
2. `test_api_gaps_filter` — query params filter correctly
3. `test_api_gap_detail_endpoint` — GET `/api/gaps/{id}` returns single gap
4. `test_api_gap_check_endpoint` — POST `/api/gaps/{id}/check` runs closure
5. `test_api_gaps_summary_endpoint` — GET `/api/gaps/summary` returns aggregates
6. `test_api_gaps_empty` — no gaps → empty list
7. `test_api_gap_not_found` — bad ID → 404

---

## Existing Test Updates

- Tests for Dream Step 8 (`test_gap_prediction` if any exist) may need updating to reflect the enhanced step.
- Search for `gaps_predicted` in test files — any test that asserts the dream report field should still pass since the existing field is preserved (new fields are additive).

---

## Verification

After all parts are complete:

1. Run all AD-539 tests: `uv run pytest tests/test_gap_detection.py tests/test_gap_classification.py tests/test_gap_qualification.py tests/test_gap_dream_integration.py tests/test_gap_commands.py tests/test_gap_routing.py -v`
2. Run all Cognitive JIT tests (full suite across AD-531 through AD-539)
3. Run full suite: `uv run pytest tests/ -x -q`
