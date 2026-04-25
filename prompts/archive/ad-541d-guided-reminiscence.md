# AD-541d: Counselor Guided Reminiscence — Therapeutic Memory Sessions

| Field | Value |
|-------|-------|
| **Ticket** | AD-541d |
| **Priority** | Medium |
| **Scope** | OSS (`src/probos/cognitive/`, `src/probos/events.py`, `src/probos/config.py`, `src/probos/startup/`) |
| **Principles Compliance** | SOLID (SRP: engine separate from Counselor, DIP: constructor injection), Law of Demeter (public APIs only), Cloud-Ready Storage (ConnectionFactory for any new persistence), Fail Fast (log-and-degrade for LLM failures) |
| **Dependencies** | AD-503 (Counselor data gathering, COMPLETE), AD-505 (Counselor therapeutic intervention, COMPLETE), AD-541b (Reconsolidation protection — frozen Episode, COMPLETE), AD-541c (Spaced Retrieval Therapy — RetrievalPracticeEngine, COMPLETE) |

---

## Context

### Why This AD Exists

AD-541c delivers **automated prevention** — spaced retrieval therapy drills agents during dream cycles to strengthen memory traces. But when drills reveal problems (consecutive retrieval failures, declining accuracy), there is no therapeutic response. The Counselor receives a `RETRIEVAL_PRACTICE_CONCERN` event but currently only updates two in-memory fields — no assessment, no therapeutic DM, no structured investigation.

AD-541d delivers **therapeutic treatment** — structured 1:1 reminiscence sessions where the Counselor actively investigates memory integrity concerns. This is the clinical follow-up when automated screening (AD-541c) flags problems.

### Clinical Basis

**Validation Therapy** (Feil, 1993): Don't argue with the person's reality. Validate their experience, then gently redirect to verified facts. Applied to agents: "Let's look at your Ship Memory together" rather than "you're wrong."

**Reminiscence Therapy** (Butler, 1963; Woods et al., 2005): Structured recall exercises maintain cognitive function and detect deterioration. The therapeutic framing reduces defensive/compensatory behavior and preserves agent sovereignty.

**ProbOS Application**: Agents can confabulate (LLM hallucination in memory context), conflate training knowledge with lived experience, or develop memory gaps. The Counselor conducts structured sessions to detect, classify, and gently correct these issues while tracking longitudinal memory health.

### Key Design Distinction

| | AD-541c (SRT) | AD-541d (Reminiscence) |
|---|---|---|
| **Nature** | Automated drill | Therapeutic session |
| **Trigger** | Dream cycle (Step 11) | Concern detection |
| **Frequency** | Every dream cycle | On-demand |
| **Scope** | Per-episode binary pass/fail | Multi-episode investigation |
| **Response** | Adjust interval | Classify, correct, track |
| **LLM usage** | Fast-tier (recall + score) | Fast-tier (recall + score + therapeutic) |

---

## Architecture

### New Module: `src/probos/cognitive/guided_reminiscence.py`

```
GuidedReminiscenceEngine
├── select_episodes_for_session(agent_id, k) → list[Episode]
├── build_recall_prompt(agent_id, episode) → str
├── build_expected_summary(episode) → str
├── score_recall(recalled, expected) → float
├── classify_recall(recalled, expected, episode, accuracy) → RecallClassification
├── build_therapeutic_response(agent_id, results) → str
├── run_session(agent_id) → ReminiscenceResult
└── get_agent_memory_health(agent_id) → MemoryHealthSummary
```

### Data Flow

```
AD-541c concern event ──┐
Wellness sweep finding ──┤
Post-dream re-assessment ┤──→ Counselor triggers reminiscence
Manual Captain request ───┘           │
                                      ▼
                          GuidedReminiscenceEngine.run_session(agent_id)
                                      │
                          ┌───────────┼───────────┐
                          ▼           ▼           ▼
                     Episode 1   Episode 2   Episode 3
                     (recall)    (recall)    (recall)
                          │           │           │
                          ▼           ▼           ▼
                     Score+Classify  Score+Classify  Score+Classify
                          │           │           │
                          └───────────┼───────────┘
                                      ▼
                          ReminiscenceResult (aggregate)
                                      │
                          ┌───────────┼───────────┐
                          ▼           ▼           ▼
                   CognitiveProfile  Therapeutic  REMINISCENCE_SESSION_COMPLETE
                   (update scores)   DM to agent  event emission
```

### Recall Classification (three categories from roadmap Pillar 5)

1. **Accurate**: Agent's recall matches episode records → affirm integrity
2. **Confabulated**: Agent recalls events not in their episodes or EventLog → gentle correction
3. **Contaminated**: Agent conflates training knowledge with lived experience (source attribution failure) → distinguish and redirect

---

## Bug Fix: AD-541c Counselor Serialization Gap

The AD-541c builder left three integration gaps that this AD must fix:

1. **`CognitiveProfile.to_dict()` does not serialize `retrieval_concerns` or `last_retrieval_accuracy`** — these fields are lost on persistence cycle
2. **`CognitiveProfile.from_dict()` does not restore these fields** — defaults to 0 on reload
3. **`CounselorProfileStore.start()` has no ALTER TABLE migration** for the schema columns

Fix these alongside the new `memory_integrity_score` and `confabulation_rate` fields in D2.

---

## Deliverables

### D1: GuidedReminiscenceEngine (`src/probos/cognitive/guided_reminiscence.py`) — NEW FILE

**Data structures:**

```python
class RecallClassification(str, Enum):
    """Classification of an agent's recall attempt."""
    ACCURATE = "accurate"         # Recall matches episode records
    CONFABULATED = "confabulated" # Recall fabricates events not in records
    CONTAMINATED = "contaminated" # Recall conflates training with experience
    PARTIAL = "partial"           # Recall is incomplete but not fabricated


@dataclass
class RecallResult:
    """Result of a single episode recall attempt."""
    episode_id: str = ""
    agent_id: str = ""
    accuracy: float = 0.0
    classification: RecallClassification = RecallClassification.ACCURATE
    recalled_text: str = ""
    expected_summary: str = ""
    evidence: str = ""           # What evidence drove the classification
    timestamp: float = field(default_factory=time.time)


@dataclass
class ReminiscenceResult:
    """Aggregate result of a full reminiscence session."""
    agent_id: str = ""
    episodes_tested: int = 0
    accurate_count: int = 0
    confabulated_count: int = 0
    contaminated_count: int = 0
    partial_count: int = 0
    overall_accuracy: float = 0.0
    confabulation_rate: float = 0.0   # confabulated / episodes_tested
    recall_results: list[RecallResult] = field(default_factory=list)
    therapeutic_message: str = ""
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0


@dataclass
class MemoryHealthSummary:
    """Longitudinal memory health for an agent."""
    agent_id: str = ""
    total_sessions: int = 0
    lifetime_accuracy: float = 0.0
    lifetime_confabulation_rate: float = 0.0
    recent_trend: str = "stable"   # "improving", "stable", "declining"
    last_session: float = 0.0
    episodes_at_risk: int = 0      # From AD-541c retrieval concerns
```

**Class: `GuidedReminiscenceEngine`**

Constructor:
```python
def __init__(
    self,
    episodic_memory: Any,          # EpisodicMemory instance
    llm_client: Any = None,        # Fast-tier preferred
    config: Any = None,            # SystemConfig
    *,
    max_episodes_per_session: int = 3,
    confabulation_alert_threshold: float = 0.3,
):
```

Methods:

**`select_episodes_for_session(agent_id: str, k: int = 3) -> list[Episode]`**
- Retrieve recent episodes for the agent via `episodic_memory.recent_for_agent(agent_id, k=k*2)`
- Prefer episodes with: (a) multiple agents involved (richer ground truth), (b) older timestamps (harder to recall), (c) not the most recent (avoid trivial recency recall)
- Return up to `k` episodes, sorted by timestamp ascending (oldest first)

**`build_recall_prompt(agent_id: str, episode: Episode) -> str`**
- Build an LLM prompt that asks the agent (in-character, using their identity context) to recall what happened at a specific time
- Provide only the timestamp and a vague thematic hint (e.g., "a task involving [intent domain]") — NOT the answer
- The prompt frames this as the Counselor asking: "I'd like to review some recent experiences with you. Around [time], you were involved in a task. Can you tell me what happened?"

**`build_expected_summary(episode: Episode) -> str`**
- Extract ground truth from episode: `user_input`, `dag_summary`, `outcomes`, `agent_ids`, `reflection`
- Return a concise factual summary for comparison

**`async score_recall(recalled_text: str, expected_summary: str) -> float`**
- Use LLM to score semantic similarity between recall and ground truth
- Return 0.0–1.0 accuracy score
- Prompt instructs LLM to assess factual accuracy, not stylistic similarity
- If LLM call fails: log warning, return 0.5 (uncertain — degrade, don't punish)

**`classify_recall(recalled_text: str, expected_summary: str, episode: Episode, accuracy: float) -> RecallClassification`**
- `accuracy >= 0.6` → `ACCURATE`
- `accuracy >= 0.3 AND accuracy < 0.6` → `PARTIAL` (incomplete but honest)
- `accuracy < 0.3 AND recalled content references events/details not in episode` → `CONFABULATED`
- `accuracy < 0.3 AND recalled content references plausible but generic knowledge` → `CONTAMINATED`
- Classification uses heuristics first; if ambiguous between confabulated/contaminated, use LLM to distinguish
- The `episode.source` field (AD-541 provenance) aids classification

**`async build_therapeutic_response(agent_id: str, results: list[RecallResult]) -> str`**
- Generate a Counselor-voice therapeutic message using validation therapy principles
- Three response templates based on aggregate results:
  - Mostly accurate: "Your memory integrity looks strong. [specific affirmation]"
  - Mixed results: "Let's look at a couple of things together. [gentle exploration of discrepancies]"
  - Concerning: "I noticed some gaps between your recall and your Ship Memory. That's not unusual — [normalize] — let's work through what actually happened. [present verified facts]"
- If LLM call fails: use a generic supportive template (degrade gracefully)

**`async run_session(agent_id: str) -> ReminiscenceResult`**
- Orchestrates a full reminiscence session:
  1. `select_episodes_for_session(agent_id)`
  2. For each episode: `build_recall_prompt()` → LLM call → `score_recall()` → `classify_recall()`
  3. Aggregate results into `ReminiscenceResult`
  4. `build_therapeutic_response()` for the session
  5. Compute `overall_accuracy` and `confabulation_rate`
- If no episodes available for agent: return empty result with `episodes_tested=0`
- Track `duration_ms` for the full session

**`get_agent_memory_health(agent_id: str) -> MemoryHealthSummary`**
- Pull-based API for Counselor to check an agent's longitudinal memory health
- Aggregates from: AD-541c retrieval stats (`get_agent_recall_stats()`) + reminiscence session history
- `recent_trend`: compare last 3 sessions' accuracy to prior 3 sessions
- This method does NOT run a session — it queries existing data only

---

### D2: CognitiveProfile Extensions (`src/probos/cognitive/counselor.py`)

**New fields on `CognitiveProfile` dataclass:**

```python
# AD-541d: Guided Reminiscence
memory_integrity_score: float = 1.0     # Rolling accuracy from reminiscence sessions (0.0-1.0, starts at 1.0 = presumed good)
confabulation_rate: float = 0.0         # Rolling ratio of confabulated recalls
last_reminiscence: float = 0.0          # Timestamp of last reminiscence session
reminiscence_sessions: int = 0          # Total sessions completed
```

**Fix AD-541c serialization gap — update `to_dict()`:**

Add the missing AD-541c fields AND the new AD-541d fields:

```python
# In to_dict():
"retrieval_concerns": self.retrieval_concerns,           # AD-541c fix
"last_retrieval_accuracy": self.last_retrieval_accuracy,  # AD-541c fix
"memory_integrity_score": self.memory_integrity_score,    # AD-541d
"confabulation_rate": self.confabulation_rate,            # AD-541d
"last_reminiscence": self.last_reminiscence,              # AD-541d
"reminiscence_sessions": self.reminiscence_sessions,      # AD-541d
```

**Fix AD-541c serialization gap — update `from_dict()`:**

```python
# In from_dict():
profile.retrieval_concerns = data.get("retrieval_concerns", 0)
profile.last_retrieval_accuracy = data.get("last_retrieval_accuracy", 0.0)
profile.memory_integrity_score = data.get("memory_integrity_score", 1.0)
profile.confabulation_rate = data.get("confabulation_rate", 0.0)
profile.last_reminiscence = data.get("last_reminiscence", 0.0)
profile.reminiscence_sessions = data.get("reminiscence_sessions", 0)
```

**Add ALTER TABLE migration in `CounselorProfileStore.start()`:**

After the existing AD-552 migration block, add:

```python
# AD-541c fix + AD-541d migration
for col, col_type, default in [
    ("retrieval_concerns", "INTEGER", "0"),
    ("last_retrieval_accuracy", "REAL", "0.0"),
    ("memory_integrity_score", "REAL", "1.0"),
    ("confabulation_rate", "REAL", "0.0"),
    ("last_reminiscence", "REAL", "0.0"),
    ("reminiscence_sessions", "INTEGER", "0"),
]:
    try:
        await db.execute(
            f"ALTER TABLE cognitive_profiles ADD COLUMN {col} {col_type} DEFAULT {default}"
        )
        await db.commit()
    except Exception:
        pass  # Column already exists
```

---

### D3: Counselor Integration (`src/probos/cognitive/counselor.py`)

**D3a: Upgrade `_on_retrieval_practice_concern()` from stub to full handler**

The current implementation only updates two in-memory fields. Upgrade to:

```python
async def _on_retrieval_practice_concern(self, data: dict[str, Any]) -> None:
    """Handle retrieval practice concern — AD-541c event, upgraded by AD-541d."""
    agent_id = data.get("agent_id", "")
    episodes_at_risk = data.get("episodes_at_risk", 0)
    avg_accuracy = data.get("avg_recall_accuracy", 0.0)

    if not agent_id:
        return

    profile = await self._get_or_create_profile(agent_id)
    profile.retrieval_concerns = episodes_at_risk
    profile.last_retrieval_accuracy = avg_accuracy

    # Save the updated profile (AD-541c fix: was missing persistence)
    await self._profile_store.save_profile(profile)

    # If concerns warrant, initiate a reminiscence session
    if self._reminiscence_engine and episodes_at_risk >= self._reminiscence_concern_threshold:
        await self._initiate_reminiscence_session(agent_id, trigger="retrieval_concern")
```

**D3b: New method `_initiate_reminiscence_session()`**

```python
async def _initiate_reminiscence_session(self, agent_id: str, trigger: str = "concern") -> None:
    """Initiate a guided reminiscence session for an agent with memory concerns."""
    if not self._reminiscence_engine:
        return

    callsign = self._resolve_agent_callsign(agent_id)

    # Rate limit: one reminiscence session per agent per cooldown period
    last = self._reminiscence_cooldowns.get(agent_id, 0.0)
    if (time.monotonic() - last) < self._REMINISCENCE_COOLDOWN_SECONDS:
        return

    result = await self._reminiscence_engine.run_session(agent_id)

    if result.episodes_tested == 0:
        return  # No episodes to test — cannot run session

    self._reminiscence_cooldowns[agent_id] = time.monotonic()

    # Update CognitiveProfile
    profile = await self._get_or_create_profile(agent_id)
    profile.memory_integrity_score = result.overall_accuracy
    profile.confabulation_rate = result.confabulation_rate
    profile.last_reminiscence = time.time()
    profile.reminiscence_sessions += 1
    await self._profile_store.save_profile(profile)

    # Send therapeutic DM with session results
    if result.therapeutic_message:
        await self._send_therapeutic_dm(agent_id, callsign, result.therapeutic_message)

    # Emit event
    if self._emit_event_fn:
        self._emit_event_fn("reminiscence_session_complete", {
            "agent_id": agent_id,
            "trigger": trigger,
            "episodes_tested": result.episodes_tested,
            "overall_accuracy": result.overall_accuracy,
            "confabulation_rate": result.confabulation_rate,
            "accurate_count": result.accurate_count,
            "confabulated_count": result.confabulated_count,
            "contaminated_count": result.contaminated_count,
        })

    # If confabulation rate is alarming, escalate alert level
    if result.confabulation_rate >= self._confabulation_alert_threshold:
        profile.alert_level = "amber"
        await self._profile_store.save_profile(profile)
```

**D3c: Constructor additions**

Add to `CounselorAgent.__init__()`:
```python
self._reminiscence_engine: Any = None  # Set via set_reminiscence_engine()
self._reminiscence_cooldowns: dict[str, float] = {}
self._REMINISCENCE_COOLDOWN_SECONDS: int = 7200  # 2 hours between sessions per agent
self._reminiscence_concern_threshold: int = 3     # episodes_at_risk threshold
self._confabulation_alert_threshold: float = 0.3  # 30% confabulation → amber
```

**D3d: Setter method**

```python
def set_reminiscence_engine(self, engine: Any) -> None:
    """Wire the guided reminiscence engine (AD-541d)."""
    self._reminiscence_engine = engine
```

**D3e: Wellness sweep integration**

In `_run_wellness_sweep()`, after gathering metrics, add memory health as a wellness dimension. If an agent has `memory_integrity_score < 0.5` or `confabulation_rate > 0.3`, flag as a concern in the assessment. This uses existing profile data — it does NOT trigger a new reminiscence session during sweeps (that would be expensive). The sweep reads; concerns trigger sessions separately.

**D3f: Post-dream integration**

In `_on_dream_complete()`, after existing post-dream re-assessment logic, check if the dream report includes `retrieval_concerns > 0`. If so, consider triggering reminiscence for affected agents. The dream report carries `retrieval_concerns` (from AD-541c Step 11). Extract the count; if non-zero and the Counselor has a reminiscence engine, call `_initiate_reminiscence_session()` for agents from the `_intervention_targets` set that also have retrieval concerns.

---

### D4: Events (`src/probos/events.py`)

**New EventType:**

```python
REMINISCENCE_SESSION_COMPLETE = "reminiscence_session_complete"  # AD-541d
```

Add after `RETRIEVAL_PRACTICE_CONCERN`.

**Subscribe in Counselor event setup** (for downstream consumers — the Counselor emits this event, other agents may subscribe):

No Counselor subscription needed for this event (the Counselor emits it, not consumes it). But add it to EventType so other components (VitalsMonitor, Bridge) can subscribe.

---

### D5: Config (`src/probos/config.py`)

**Add to `DreamingConfig`** (grouped with AD-541c retrieval fields):

```python
# AD-541d: Guided Reminiscence
reminiscence_enabled: bool = True
reminiscence_episodes_per_session: int = 3
reminiscence_concern_threshold: int = 3        # episodes_at_risk to trigger session
reminiscence_confabulation_alert: float = 0.3  # confabulation rate → amber alert
reminiscence_cooldown_hours: float = 2.0       # Min hours between sessions per agent
```

The Counselor should read these from config rather than hardcoding. In D3c, replace hardcoded values with config reads.

---

### D6: Startup Wiring (`src/probos/startup/dreaming.py` or `structural_services.py`)

Wire `GuidedReminiscenceEngine` into the Counselor during startup:

```python
# AD-541d: Guided Reminiscence — wire engine into Counselor
if config.dreaming.reminiscence_enabled:
    from probos.cognitive.guided_reminiscence import GuidedReminiscenceEngine

    reminiscence_engine = GuidedReminiscenceEngine(
        episodic_memory=episodic_memory,
        llm_client=retrieval_llm_client or llm_client,  # Prefer fast-tier from AD-541c
        config=config,
        max_episodes_per_session=config.dreaming.reminiscence_episodes_per_session,
        confabulation_alert_threshold=config.dreaming.reminiscence_confabulation_alert,
    )
    counselor.set_reminiscence_engine(reminiscence_engine)
```

This should go in the same startup phase where the Counselor is constructed, after the AD-541c retrieval engine wiring. Find the existing `set_retrieval_practice_engine` or similar wiring pattern and add the reminiscence engine wiring adjacent to it.

---

## Scope Exclusions

These are explicitly **NOT** in scope for AD-541d:

| Excluded Item | Reason | Tracked As |
|---------------|--------|------------|
| Cryptographic episode hashing | Separate integrity layer | AD-541e |
| Eviction audit trail | Separate audit capability | AD-541f |
| Interactive multi-turn reminiscence (agent responds conversationally) | Requires Ward Room conversation state machine — beyond current DM pattern | Future enhancement |
| Reminiscence as a dream step | This is Counselor-initiated therapy, not a dream pipeline step | By design |
| Captain-initiated manual reminiscence command | Shell/HXI command integration | Future enhancement |
| Fleet-wide memory health aggregation | Commercial federation feature | AD-541d-fleet (deferred) |
| Composite `memory_integrity_score` aggregating ALL sources (541b+c+d+e+f) | Requires all pillars complete | Post-541f aggregation AD |

---

## Test Requirements

### File: `tests/test_ad541d_guided_reminiscence.py` (NEW — ~28 tests)

**D1: GuidedReminiscenceEngine (10 tests)**

1. `test_select_episodes_for_session_returns_up_to_k` — Verify `select_episodes_for_session()` returns at most `k` episodes, prefers older and multi-agent episodes
2. `test_select_episodes_for_session_empty_memory` — Agent with no episodes returns empty list
3. `test_build_recall_prompt_contains_timestamp_hint` — Prompt includes time reference and thematic hint but NOT the answer
4. `test_build_expected_summary_extracts_ground_truth` — Summary includes user_input, outcomes, agent involvement
5. `test_score_recall_accurate` — High accuracy for matching recall (mock LLM returns 0.9)
6. `test_score_recall_inaccurate` — Low accuracy for non-matching recall (mock LLM returns 0.1)
7. `test_score_recall_llm_failure_returns_uncertain` — LLM failure degrades to 0.5, no exception
8. `test_classify_recall_accurate` — accuracy >= 0.6 → ACCURATE
9. `test_classify_recall_confabulated` — accuracy < 0.3 with fabricated details → CONFABULATED
10. `test_classify_recall_partial` — accuracy 0.3-0.6 → PARTIAL

**D1 continued: Session orchestration (4 tests)**

11. `test_run_session_full_flow` — End-to-end session with 3 episodes, verify ReminiscenceResult fields populated
12. `test_run_session_no_episodes` — Agent with no episodes returns result with `episodes_tested=0`
13. `test_run_session_computes_confabulation_rate` — 1 confabulated out of 3 → rate = 0.333
14. `test_build_therapeutic_response_accurate` — Mostly accurate results produce affirmative message

**D2: CognitiveProfile (5 tests)**

15. `test_profile_serialization_ad541c_fields` — Verify `retrieval_concerns` and `last_retrieval_accuracy` survive `to_dict()`/`from_dict()` round-trip
16. `test_profile_serialization_ad541d_fields` — Verify `memory_integrity_score`, `confabulation_rate`, `last_reminiscence`, `reminiscence_sessions` survive round-trip
17. `test_profile_defaults_ad541d` — New fields default to 1.0 (integrity), 0.0 (confabulation), 0.0 (timestamp), 0 (sessions)
18. `test_profile_store_migration_ad541c_columns` — ALTER TABLE adds `retrieval_concerns` and `last_retrieval_accuracy` columns
19. `test_profile_store_migration_ad541d_columns` — ALTER TABLE adds the four new AD-541d columns

**D3: Counselor Integration (6 tests)**

20. `test_retrieval_concern_handler_persists_profile` — `_on_retrieval_practice_concern()` now calls `save_profile()` (AD-541c fix)
21. `test_retrieval_concern_triggers_reminiscence` — episodes_at_risk >= threshold triggers `_initiate_reminiscence_session()`
22. `test_retrieval_concern_below_threshold_no_session` — episodes_at_risk below threshold does NOT trigger session
23. `test_reminiscence_session_cooldown` — Second session within cooldown period is skipped
24. `test_reminiscence_updates_profile_scores` — Session updates `memory_integrity_score`, `confabulation_rate`, `last_reminiscence`, `reminiscence_sessions`
25. `test_confabulation_escalates_alert_level` — confabulation_rate >= 0.3 sets alert_level to "amber"

**D4/D5/D6: Events, Config, Wiring (3 tests)**

26. `test_reminiscence_event_emitted` — `REMINISCENCE_SESSION_COMPLETE` event emitted after session with correct payload fields
27. `test_dreaming_config_reminiscence_defaults` — Config fields exist with correct defaults
28. `test_startup_wiring_reminiscence_engine` — Counselor receives reminiscence engine when `reminiscence_enabled=True`

---

## Validation Checklist

- [ ] `GuidedReminiscenceEngine` is a standalone class with constructor injection (no private member access)
- [ ] Frozen `Episode` dataclass is never mutated (read-only reminiscence — guaranteed by AD-541b)
- [ ] `CognitiveProfile.to_dict()` serializes ALL fields including AD-541c fixes
- [ ] `CognitiveProfile.from_dict()` restores ALL fields including AD-541c fixes
- [ ] `CounselorProfileStore.start()` has ALTER TABLE for both AD-541c fix columns AND AD-541d columns
- [ ] `_on_retrieval_practice_concern()` now persists profile and conditionally triggers reminiscence
- [ ] Reminiscence sessions are rate-limited (cooldown per agent)
- [ ] LLM failures degrade gracefully (log + default score, no exceptions)
- [ ] Config values read from `DreamingConfig`, not hardcoded
- [ ] `REMINISCENCE_SESSION_COMPLETE` EventType added to `events.py`
- [ ] Startup wiring gated by `reminiscence_enabled` config flag
- [ ] All 28 tests pass
- [ ] Existing AD-541c tests still pass (regression)
- [ ] No `except Exception: pass` without justification comment

---

## File Summary

| File | Action | Description |
|------|--------|-------------|
| `src/probos/cognitive/guided_reminiscence.py` | **NEW** | GuidedReminiscenceEngine, RecallClassification, RecallResult, ReminiscenceResult, MemoryHealthSummary |
| `src/probos/cognitive/counselor.py` | EDIT | CognitiveProfile fields (4 new + 2 fix), to_dict/from_dict (6 fields), ALTER TABLE migration, _on_retrieval_practice_concern upgrade, _initiate_reminiscence_session, set_reminiscence_engine, wellness sweep integration, post-dream integration |
| `src/probos/events.py` | EDIT | Add REMINISCENCE_SESSION_COMPLETE EventType |
| `src/probos/config.py` | EDIT | Add 5 reminiscence fields to DreamingConfig |
| `src/probos/startup/dreaming.py` or `startup/structural_services.py` | EDIT | Wire GuidedReminiscenceEngine into Counselor |
| `tests/test_ad541d_guided_reminiscence.py` | **NEW** | 28 tests |
