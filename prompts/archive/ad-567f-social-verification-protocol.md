# AD-567f: Social Verification Protocol

**Absorbs:** AD-462d (Social Memory — cross-agent episodic queries)
**Depends:** AD-567a (Episode Anchor Metadata — COMPLETE), AD-554 (Real-Time Convergence Detection — COMPLETE), AD-506b (Peer Repetition Detection — COMPLETE)
**Prior art:** Johnson & Raye (1981) reality monitoring, OBS-015 cascade confabulation (2026-04-03/04), March 26 cascade event (five-stage anatomy), "circular reporting" from intelligence analysis (Iraq WMD), Multi-sensor SLAM (MR) independent anchor corroboration

---

## Context

ProbOS agents can detect when they echo each other's Ward Room posts (AD-506b peer similarity) and when they independently converge on the same notebook topic (AD-554 convergence detection). But neither mechanism distinguishes **corroboration** (good — independent anchored observations of the same real event) from **cascade confabulation** (bad — the same unverified claim propagating socially without independent evidence).

Two documented cascade events demonstrate the failure mode:
- **March 26 cascade:** 11 agents constructed a fabricated crisis from a noisy sensor. Five-stage anatomy: Seed → Validation → Expert Confirmation → Consensus Lock → Proposal Cascade. "Two ungrounded assertions do not become one grounded fact."
- **OBS-015 (April 3–4):** Horizon and Atlas propagated fabricated observations ("SerendipityAgent") between each other via Ward Room. Neither agent verified anchors, checked their own episodic memory, or expressed uncertainty. Confirmed as recurring pattern with second observation the following day.

Standing Orders (federation.md Memory Anchoring Protocol, lines 188–195) already instruct agents to verify claims before building on them — but provide zero architectural tooling. AD-567f provides that tooling: privacy-preserving corroboration queries, anchor-independence scoring, and cascade confabulation detection.

**Core insight:** Anchor independence is what separates corroboration from cascade.
- High content similarity + **independent anchors** (different duty cycles, channels, timestamps) = **genuine corroboration**
- High content similarity + **no independent anchors** (all traceable to one unanchored social post) = **cascade confabulation**

---

## Scope

### 1. Corroboration Service — Core Engine

**File: `src/probos/cognitive/social_verification.py`** (NEW)

Create the `SocialVerificationService` class — the core engine for cross-agent claim verification.

```python
@dataclass(frozen=True)
class CorroborationResult:
    """Result of a cross-agent corroboration query."""
    query: str                           # Original claim/query text
    requesting_agent_id: str             # Who asked
    corroborating_agent_count: int       # How many OTHER agents have relevant episodes
    independent_anchor_count: int        # How many have INDEPENDENT anchors (different source)
    total_matching_episodes: int         # Total matching episodes across agents
    anchor_independence_score: float     # 0.0–1.0: ratio of independent vs dependent anchors
    corroboration_score: float           # 0.0–1.0: composite score
    is_corroborated: bool                # corroboration_score >= threshold
    cascade_risk: bool                   # High similarity + low anchor independence
    matching_agents: list[str]           # Callsigns of corroborating agents (not content!)
    matching_departments: list[str]      # Departments of corroborating agents
    anchor_summary: dict[str, Any]       # Aggregate anchor metadata (no episode content)
```

```python
class SocialVerificationService:
    """AD-567f: Cross-agent claim verification and cascade detection.

    Absorbs AD-462d (Social Memory) — provides the cross-agent episodic
    query mechanism, with privacy-preserving corroboration scoring on top.

    Privacy principle: agents learn WHETHER corroborating evidence exists
    and WHO has it, but never see other agents' episode content.
    """

    def __init__(
        self,
        episodic_memory: Any,                    # EpisodicMemory instance
        config: "SocialVerificationConfig",       # Config (from SystemConfig)
        emit_event_fn: Callable[[str, dict], None] | None = None,
    ) -> None:
```

#### Method 1: `check_corroboration()`

The primary verification query — "did anyone else observe X?"

```python
async def check_corroboration(
    self,
    requesting_agent_id: str,
    claim: str,
    *,
    k: int = 10,
    min_confidence: float = 0.3,
) -> CorroborationResult:
```

Implementation:
1. Call `self._episodic.recall(claim, k=k)` — the **global** (un-agent-scoped) recall method. This returns episodes from ALL agents matching the query semantically.
2. **Exclude** episodes where `requesting_agent_id` is in `episode.agent_ids` — the agent shouldn't corroborate itself.
3. For each remaining episode:
   - Compute `anchor_confidence` via `compute_anchor_confidence(episode.anchors)` (from `anchor_quality.py`).
   - Skip episodes below `min_confidence`.
   - Extract agent IDs and anchor metadata (but NOT episode content — privacy boundary).
4. Compute **anchor independence** — group matching episodes by their anchor signature:
   - Two episodes are "independently anchored" if they have **different** `duty_cycle_id` OR **different** `channel_id` OR timestamps > 60 seconds apart.
   - Two episodes with the **same** `thread_id` are NOT independent — they came from the same conversation.
   - `anchor_independence_score = independent_anchors / total_matching_episodes` (0.0–1.0).
5. Compute **corroboration score**: `0.5 * (corroborating_agent_count / max_agents) + 0.3 * anchor_independence_score + 0.2 * mean_anchor_confidence`. Cap at 1.0.
   - `max_agents` = config.`corroboration_max_agents` (default 5). More than 5 independent sources is maximum corroboration.
6. Set `is_corroborated = corroboration_score >= config.corroboration_threshold` (default 0.4).
7. Set `cascade_risk = total_matching_episodes >= 2 and anchor_independence_score < config.cascade_independence_threshold` (default 0.3).
8. Build `anchor_summary` with aggregate anchor metadata: shared channels, shared departments, unique participants list, time span — but NO episode content.
9. Return `CorroborationResult`.

#### Method 2: `check_cascade_risk()`

Proactive cascade detection — called on Ward Room posts to detect propagation of unverified claims.

```python
async def check_cascade_risk(
    self,
    author_id: str,
    author_callsign: str,
    post_body: str,
    channel_id: str,
    *,
    peer_matches: list[dict[str, Any]] | None = None,
) -> CascadeRiskResult | None:
```

```python
@dataclass(frozen=True)
class CascadeRiskResult:
    """Result of cascade confabulation detection."""
    risk_level: str                    # "none", "low", "medium", "high"
    propagation_count: int             # How many agents have posted similar content
    anchor_independence_score: float   # Do the similar posts have independent evidence?
    source_agent: str                  # Earliest poster (likely cascade origin)
    affected_agents: list[str]         # Agents propagating the claim
    affected_departments: list[str]    # Departments affected
    detail: str                        # Human-readable explanation
```

Implementation:
1. If `peer_matches` is provided (from existing `check_peer_similarity()` in AD-506b), use those. Otherwise, return `None` (no peer echoing detected, no cascade risk).
2. For each peer match, look up the matching author's recent episodes via `recall(post_body, k=3)` filtered to that author's episodes.
3. Score the anchor independence of matched posts' underlying episodes.
4. Classify risk level:
   - **none:** `peer_matches` empty or all matches have independent anchors.
   - **low:** 1 match with weak anchor independence (< 0.5). Log only.
   - **medium:** 2+ matches with weak anchor independence (< 0.3). Emit event.
   - **high:** 3+ matches with zero independent anchors (all traceable to same thread or no anchors). Emit event + Bridge Alert.
5. Identify `source_agent` — the match with the earliest timestamp.
6. Return `CascadeRiskResult`.

#### Method 3: `get_verification_context()`

Utility for agents to get a verification summary they can include in their reasoning.

```python
async def get_verification_context(
    self,
    agent_id: str,
    claim: str,
) -> str:
```

Returns a short text block (under 200 chars) like:
- `"[VERIFIED: 3 crew independently observed this across 2 departments]"`
- `"[UNVERIFIED: no independent corroboration found — treat as unconfirmed]"`
- `"[CASCADE RISK: 2 crew echo this claim but none have independent evidence]"`

This can be injected into agent perceive/think context alongside the claim.

---

### 2. Events — New Event Types

**File: `src/probos/events.py`** (MODIFY)

Add to `EventType` enum (after `PEER_REPETITION_DETECTED`):

```python
CASCADE_CONFABULATION_DETECTED = "cascade_confabulation_detected"  # AD-567f
CORROBORATION_VERIFIED = "corroboration_verified"                  # AD-567f
```

Add event classes (after `PeerRepetitionDetectedEvent`):

```python
@dataclass
class CascadeConfabulationEvent(BaseEvent):
    """AD-567f: Emitted when cascade confabulation risk is detected."""
    event_type: EventType = field(default=EventType.CASCADE_CONFABULATION_DETECTED, init=False)
    risk_level: str = ""                    # "low", "medium", "high"
    source_agent: str = ""                  # Earliest poster (callsign)
    affected_agents: list[str] = field(default_factory=list)
    affected_departments: list[str] = field(default_factory=list)
    propagation_count: int = 0
    anchor_independence_score: float = 0.0
    channel_id: str = ""
    detail: str = ""


@dataclass
class CorroborationVerifiedEvent(BaseEvent):
    """AD-567f: Emitted when a claim is independently corroborated."""
    event_type: EventType = field(default=EventType.CORROBORATION_VERIFIED, init=False)
    requesting_agent: str = ""              # Callsign of verifying agent
    claim_preview: str = ""                 # First 100 chars of the claim
    corroborating_agents: list[str] = field(default_factory=list)
    corroboration_score: float = 0.0
    anchor_independence_score: float = 0.0
```

---

### 3. Bridge Alert — Cascade Detection

**File: `src/probos/bridge_alerts.py`** (MODIFY)

Add method to `BridgeAlertService` (after `check_divergence()`):

```python
def check_cascade_risk(self, cascade_result: dict) -> list[BridgeAlert]:
    """AD-567f: Alert Bridge when cascade confabulation is detected."""
    if cascade_result.get("risk_level") not in ("medium", "high"):
        return []

    risk = cascade_result["risk_level"]
    source = cascade_result.get("source_agent", "unknown")
    affected = cascade_result.get("affected_agents", [])
    count = cascade_result.get("propagation_count", 0)
    independence = cascade_result.get("anchor_independence_score", 0.0)

    key = f"cascade:{source}:{','.join(sorted(affected))}"
    if not self._should_emit(key):
        return []

    severity = AlertSeverity.WARNING if risk == "high" else AlertSeverity.ADVISORY

    a = BridgeAlert(
        id=str(uuid.uuid4()),
        severity=severity,
        source="social_verification",
        alert_type="cascade_confabulation",
        title=f"Cascade confabulation risk ({risk}): {count} agents, anchor independence {independence:.0%}",
        detail=f"Source: {source}. Affected: {', '.join(affected)}. "
               f"{cascade_result.get('detail', '')}",
        department=None,
        dedup_key=key,
    )
    self._record(a)
    return [a]
```

---

### 4. Configuration

**File: `src/probos/config.py`** (MODIFY)

Add `SocialVerificationConfig` class (after `RecordsConfig`):

```python
class SocialVerificationConfig(BaseModel):
    """AD-567f: Social Verification Protocol configuration."""
    enabled: bool = True
    # Corroboration
    corroboration_threshold: float = 0.4       # Score above this = corroborated
    corroboration_max_agents: int = 5          # Denominator for agent count scoring
    corroboration_min_confidence: float = 0.3  # Anchor confidence gate for matches
    # Cascade detection
    cascade_enabled: bool = True
    cascade_independence_threshold: float = 0.3  # Below this = cascade risk
    cascade_cooldown_seconds: float = 300.0      # Dedup window for cascade alerts
    # Privacy
    expose_episode_content: bool = False  # MUST stay False — privacy boundary
```

Add field to `SystemConfig` (alongside `records: RecordsConfig`):

```python
social_verification: SocialVerificationConfig = SocialVerificationConfig()
```

---

### 5. Ward Room Integration — Cascade Check on Posts

**File: `src/probos/ward_room/threads.py`** (MODIFY)

In `ThreadManager.create_thread()`, AFTER the existing `check_peer_similarity()` call (around line 286), add cascade risk checking:

```python
# AD-567f: Check cascade risk when peer similarity is detected
if peer_matches and self._social_verification:
    try:
        cascade = await self._social_verification.check_cascade_risk(
            author_id=author_id,
            author_callsign=author_callsign,
            post_body=body,
            channel_id=channel_id,
            peer_matches=peer_matches,
        )
        if cascade and cascade.risk_level in ("medium", "high"):
            from probos.events import CascadeConfabulationEvent
            if self._emit_event:
                self._emit_event(
                    EventType.CASCADE_CONFABULATION_DETECTED,
                    dataclasses.asdict(cascade),
                )
    except Exception:
        logger.debug("AD-567f: cascade check failed", exc_info=True)
```

**ThreadManager needs `_social_verification` reference.** Add late-binding setter (same pattern as SIF's `set_ward_room()`):

```python
def set_social_verification(self, svc: Any) -> None:
    """AD-567f: Late-bind social verification service."""
    self._social_verification = svc
```

Initialize `self._social_verification = None` in `__init__`.

Also apply the same cascade check in `MessageStore.add_post()` (messages.py) after its existing `check_peer_similarity()` call — same pattern. Add `set_social_verification()` setter and `self._social_verification = None` in `__init__`.

---

### 6. Proactive Think Integration — Verification Context

**File: `src/probos/proactive.py`** (MODIFY)

In the `_build_self_monitoring_context()` method (around line 1179), add a section for recent cascade warnings. Similar to how `notebook_repetition_warnings` are injected:

```python
# AD-567f: Recent cascade confabulation warnings for this agent
cascade_ctx = ""
if hasattr(self._runtime, '_social_verification') and self._runtime._social_verification:
    # Check if this agent was flagged in a recent cascade
    # (The agent should be aware if claims they've been spreading are unverified)
    pass  # Cascade context is delivered via Bridge Alerts + Counselor, not self-monitoring
```

**NOTE:** Do NOT inject `get_verification_context()` into every perceive cycle — that would be a token cost explosion. The verification context is available as a **tool** the agent can invoke when they want to verify a specific claim, not a default injection. The standing orders already tell agents to verify; this gives them the mechanism.

---

### 7. Startup Wiring

**File: `src/probos/startup/cognitive_services.py`** (MODIFY)

Add `SocialVerificationService` initialization after RecordsStore initialization (around line 281):

```python
# AD-567f: Social Verification Protocol
social_verification = None
if config.social_verification.enabled:
    try:
        from probos.cognitive.social_verification import SocialVerificationService
        social_verification = SocialVerificationService(
            episodic_memory=episodic_memory,
            config=config.social_verification,
            emit_event_fn=emit_event_fn,
        )
        logger.info("AD-567f: SocialVerificationService initialized")
    except Exception as e:
        logger.warning("SocialVerificationService failed to start: %s — continuing without", e)
```

Return it in `CognitiveServicesResult`. Add `social_verification: Any = None` field to that dataclass.

**File: `src/probos/startup/finalize.py`** (MODIFY)

Wire `social_verification` into ThreadManager and MessageStore via late-binding setters:

```python
# AD-567f: Wire social verification into Ward Room
if hasattr(runtime, '_social_verification') and runtime._social_verification:
    ward_room = runtime.ward_room
    if hasattr(ward_room, '_threads') and hasattr(ward_room._threads, 'set_social_verification'):
        ward_room._threads.set_social_verification(runtime._social_verification)
    if hasattr(ward_room, '_messages') and hasattr(ward_room._messages, 'set_social_verification'):
        ward_room._messages.set_social_verification(runtime._social_verification)
```

**File: `src/probos/runtime.py`** (MODIFY)

Store reference: `self._social_verification = cognitive_result.social_verification` in the startup sequence where other cognitive service results are stored.

---

### 8. Counselor Subscription

**File: `src/probos/agents/counselor.py`** (MODIFY)

Add `CASCADE_CONFABULATION_DETECTED` to the Counselor's event subscriptions (alongside existing `TRUST_UPDATE`, `CIRCUIT_BREAKER_TRIP`, etc.):

```python
EventType.CASCADE_CONFABULATION_DETECTED,
```

In the event handler, when a cascade event arrives:
- Log the cascade to the agent's Counselor wellness context.
- If risk_level is "high", DM the affected agents with a non-judgmental prompt: *"I noticed several crew members are discussing a claim that may not have independent verification. Could you each check your own observations and anchors before building further analysis on this?"*
- Rate-limit: use existing Counselor DM cooldown.

---

## Tests

**File: `tests/test_social_verification.py`** (NEW — target 28 tests)

### CorroborationResult tests (8):
1. `test_corroboration_no_matching_episodes` — empty recall returns score 0, not corroborated
2. `test_corroboration_self_excluded` — requesting agent's own episodes excluded from results
3. `test_corroboration_single_independent_agent` — one corroborating agent with good anchors
4. `test_corroboration_multiple_independent_agents` — 3+ agents, high independence score
5. `test_corroboration_same_thread_not_independent` — two episodes from same thread_id count as dependent
6. `test_corroboration_below_confidence_gate_filtered` — low-anchor episodes excluded by min_confidence
7. `test_corroboration_privacy_no_content_exposed` — result contains NO episode content, only metadata
8. `test_corroboration_threshold_boundary` — score exactly at threshold passes, below fails

### CascadeRiskResult tests (7):
9. `test_cascade_no_peer_matches_returns_none` — no peer similarity = no cascade risk
10. `test_cascade_independent_anchors_no_risk` — peer matches but all independently anchored = "none"
11. `test_cascade_low_risk` — 1 match with weak anchors = "low"
12. `test_cascade_medium_risk` — 2 matches with weak anchors = "medium", event emitted
13. `test_cascade_high_risk` — 3+ matches with zero anchors = "high", event + alert
14. `test_cascade_source_agent_earliest_post` — source_agent is the match with earliest timestamp
15. `test_cascade_same_thread_dependent` — matches sharing thread_id are not independent

### AnchorIndependence tests (5):
16. `test_anchor_independence_different_duty_cycles` — different duty_cycle_id = independent
17. `test_anchor_independence_different_channels` — different channel_id = independent
18. `test_anchor_independence_time_separation` — timestamps > 60s apart = independent
19. `test_anchor_independence_same_thread_dependent` — same thread_id = NOT independent
20. `test_anchor_independence_no_anchors` — episodes without anchors = not independent (score 0)

### Integration tests (5):
21. `test_verification_context_corroborated` — returns "[VERIFIED: ...]" string
22. `test_verification_context_unverified` — returns "[UNVERIFIED: ...]" string
23. `test_verification_context_cascade` — returns "[CASCADE RISK: ...]" string
24. `test_bridge_alert_cascade_medium` — medium risk creates ADVISORY bridge alert
25. `test_bridge_alert_cascade_high` — high risk creates WARNING bridge alert

### Event tests (3):
26. `test_cascade_event_emitted` — CascadeConfabulationEvent emitted on medium/high risk
27. `test_corroboration_event_emitted` — CorroborationVerifiedEvent emitted when corroborated
28. `test_cascade_event_not_emitted_on_low` — low risk does NOT emit event

---

## DECISIONS.md Entry

```
| AD-567f | Social Verification Protocol (absorbs AD-462d). Cross-agent claim verification, corroboration scoring, and cascade confabulation detection. Privacy-preserving: agents learn WHETHER evidence exists and WHO has it, never see other agents' content. Anchor independence as the discriminator: independent anchors = corroboration (good), dependent/missing anchors = cascade (bad). Ward Room integration: cascade check fires after AD-506b peer similarity detection. Bridge Alerts on medium/high cascade risk. Counselor subscription for therapeutic intervention. Prior art: Johnson & Raye (1981) reality monitoring, multi-sensor SLAM, circular reporting (intelligence analysis). Empirical evidence: OBS-015 (Horizon+Atlas cascade confabulation, April 3-4), March 26 cascade (11 agents, 5-stage anatomy). 28 tests. |
```

---

## Roadmap Updates

In `docs/development/roadmap.md`:
- Mark AD-567f as complete in the sequencing diagram
- Mark AD-462d as absorbed into AD-567f
- Update the AD-567f description from "planned" to "complete" with summary
- Update build order line: `567d ✅ → 567f ✅ → 567g`

---

## Implementation Notes

- **Privacy is non-negotiable.** The `expose_episode_content` config MUST default to False and MUST NOT be set to True in any default config. Agents see metadata (who, when, where) but never content. This is the sovereign memory boundary.
- **Performance:** `recall()` global search hits ChromaDB across all episodes. For a 100K episode store, semantic search is O(n) on the embedding space. This is acceptable for verification queries (infrequent, user-initiated) but NOT for every Ward Room post. Cascade detection reuses peer_matches already computed by AD-506b — minimal additional cost.
- **Late-binding pattern:** Follow the established pattern from SIF (`set_ward_room()`), DreamingEngine (`set_activation_tracker()`). Social verification initializes after EpisodicMemory but needs to reach into Ward Room components. Use `set_social_verification()` setters, wired in `finalize.py`.
- **Do NOT inject verification into every perceive cycle.** Standing orders already instruct verification. The service is a tool the agent can invoke, not a default injection. Token cost would be prohibitive otherwise.
- **`dataclasses.asdict()` on frozen dataclasses:** Both `CorroborationResult` and `CascadeRiskResult` are frozen. Use `dataclasses.asdict()` for event emission dict conversion.

---

## What This Does NOT Do (Deferred)

- **Agent-invocable verification tool** (future) — Let agents programmatically call `check_corroboration()` during their think cycle via a cognitive tool interface. Currently the service runs reactively (cascade check on Ward Room posts) and is available programmatically to the proactive loop. Agent-initiated verification requires the Native SWE Harness tool loop (AD-543+).
- **Propagation graph tracking** (future) — Full graph of who-said-what-first across the cascade. Would require message lineage tracking in Ward Room. Current implementation identifies the source_agent (earliest poster) but not the full propagation chain.
- **Semantic similarity for cascade detection** (future) — Currently reuses Jaccard-based `check_peer_similarity()` from AD-506b. Semantic similarity (embedding-based) would catch paraphrased cascade propagation but adds significant compute cost. Defer until cascade detection proves valuable.
