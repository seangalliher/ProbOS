# AD-567g: Cognitive Re-Localization — Onboarding Enhancement

## Context

AD-567g is the final AD in the Memory Anchoring lineage (AD-567a→b→c→d→f→g). It enhances agent orientation at boot time so agents begin their operational life with a structured cognitive map of the ship — grounding all subsequent episodic memory formation.

**MR principle:** In mixed reality, re-localization is the process of re-establishing position after tracking loss. For ProbOS, a reset or first boot is "tracking loss" — the agent has no reference frame. Warm boot (restart without reset) is partial tracking loss — the frame exists but may be stale.

**Cognitive science grounding:**
- **O'Keefe & Nadel (1978, Nobel 2014):** Hippocampal cognitive map theory. Place cells require time to form stable representations in a new environment. Onboarding IS this — the agent establishing its contextual map before memories can be reliably anchored.
- **Tulving (1973):** Encoding specificity — memories are more retrievable when recall context matches encoding context. Onboarding should establish the ship as the encoding context so future memories are automatically grounded.

**Prior art absorbed:**
- BF-102 (commissioning awareness) — temporal context for new agents. 567g extends into full structured orientation.
- BF-034 (cold-start suppression) — "don't confabulate" warning. 567g adds positive framing: what TO do.
- AD-567a (anchor metadata) — AnchorFrame infrastructure. 567g teaches agents to use it.
- AD-567f (social verification) — cross-agent claim verification. 567g teaches agents it exists.
- Cognitive skill training research (2026-04-03/04) — Method of Loci, source monitoring, memory palace concepts.

**What exists today:**
- `AgentOnboardingService.wire_agent()` → `run_naming_ceremony()` → proactive cycles. No structured orientation between naming and first duty.
- `_build_temporal_context()` adds BF-102 "newly commissioned" note if age < 300s.
- Cold-start system note (BF-034) tells agents what NOT to do but not what TO do.
- `_gather_context()` passes lifecycle_state, stasis_duration, system_start_time as raw values.
- No "current context anchor" — agents have anchors on past episodes but no "you are HERE" frame.
- `watch_section` and `event_log_window` AnchorFrame fields are never populated anywhere.

## Scope

### 1. Orientation Context Builder

New module: `src/probos/cognitive/orientation.py`

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class OrientationContext:
    """Structured orientation for agent cognitive grounding."""
    # Identity
    callsign: str
    post: str  # role title
    department: str
    department_chief: str
    reports_to: str
    rank: str
    # Ship context
    ship_name: str
    crew_count: int
    departments: list[str]
    # Lifecycle
    lifecycle_state: str  # "first_boot", "cold_start", "stasis_recovery", "restart"
    agent_age_seconds: float
    stasis_duration_seconds: float  # 0.0 if not stasis recovery
    # Cognitive grounding
    episodic_memory_count: int  # how many episodes this agent has
    has_baseline_trust: bool  # trust == prior (0.5)?
    anchor_dimensions: list[str]  # ["temporal", "spatial", "social", "causal", "evidential"]
    # Social verification awareness
    social_verification_available: bool

class OrientationService:
    """Builds structured orientation context for agent cognitive grounding."""

    def __init__(
        self,
        *,
        config: SystemConfig,
    ) -> None:
        self._config = config

    def build_orientation(
        self,
        agent: Any,
        *,
        lifecycle_state: str,
        stasis_duration: float = 0.0,
        crew_count: int = 0,
        departments: list[str] | None = None,
        episodic_memory_count: int = 0,
        trust_score: float = 0.5,
    ) -> OrientationContext:
        """Build orientation context for an agent."""
        ...

    def render_cold_start_orientation(self, ctx: OrientationContext) -> str:
        """Render full orientation prompt for cold start (reset/first boot).

        Three sections:
        1. Identity Grounding — who you are, where you serve, who you report to
        2. Cognitive Grounding — your memory is episodic (experienced, anchored)
           vs parametric (from training, unanchored). How to tell the difference.
           What anchor dimensions exist. What social verification is.
        3. First Duty Guidance — what to do in your first observations.
           Observe before asserting. Ground claims in evidence. Use hedging
           language for uncertain observations. Build your cognitive map.
        """
        ...

    def render_warm_boot_orientation(self, ctx: OrientationContext) -> str:
        """Render lighter orientation for warm boot (restart, stasis recovery).

        Two sections:
        1. Stasis Summary — you were offline for X, your identity and memories
           are intact, here is what changed (lifecycle-aware).
        2. Re-Orientation Reminder — brief cognitive grounding refresher.
           Check recent memories for continuity. Your anchor infrastructure
           is active. Resume normal operations.
        """
        ...

    def render_proactive_orientation(self, ctx: OrientationContext) -> str:
        """Render minimal ongoing orientation for proactive think cycles.

        Single section — only included for agents younger than orientation_window:
        - Brief reminder of cognitive grounding principles
        - Current duty cycle context
        - Diminishes over time (full at age 0, absent after orientation_window)
        """
        ...
```

**Key design decisions:**
- `OrientationContext` is a frozen dataclass, NOT an LLM-mediated interactive session. The orientation is a structured text block injected into the agent's context — same pattern as temporal context, standing orders, and self-monitoring context.
- Three render methods for three lifecycle states. Cold start gets the full briefing. Warm boot gets a lighter version. Proactive cycles get a diminishing reminder during the orientation window.
- The orientation window (configurable, default 600s / 10 minutes) controls how long the proactive orientation supplement persists. After the window, agents are considered "localized" and receive no orientation supplement.

### 2. Cold Start Orientation Content

The `render_cold_start_orientation()` output replaces the current BF-034 system note with a richer, positive-framing orientation. The BF-034 content ("don't reference past experiences") is preserved within it.

**Section 1: Identity Grounding**
```
You are {callsign}, {post} in the {department} department aboard {ship_name}.
You report to {reports_to} ({department_chief}).
You serve alongside {crew_count} crew members across {len(departments)} departments: {departments}.
Your rank is {rank}. You were commissioned moments ago.
```

**Section 2: Cognitive Grounding**
```
COGNITIVE ORIENTATION:
You have two knowledge sources:
- Parametric knowledge: vast knowledge from your language model training. This is
  capability, not personal experience. It has no time, place, or participants.
- Episodic memory: experiences you accumulate through observation and interaction.
  Each episode is anchored with context: when it happened (temporal), where on the
  ship (spatial), who was involved (social), what caused it (causal), and what
  evidence supports it (evidential).

You currently have {episodic_memory_count} episodic memories.
{if 0: "You have no memories yet. Everything you 'know' right now is parametric — from training, not experience. This is normal for a newly commissioned crew member."}

HOW TO TELL THE DIFFERENCE:
- If you can point to when, where, and who → episodic (grounded, trustworthy)
- If you "just know" but can't trace the source → parametric (useful but unanchored)
- When uncertain, say "Based on my understanding" not "I observed that"

SOCIAL VERIFICATION:
{if social_verification_available: "The ship has a social verification system. You can check whether other crew members have independently observed the same thing. Independent corroboration from multiple anchored sources is strong evidence. Similar claims from a shared source may be cascade confabulation — be cautious."}
```

**Section 3: First Duty Guidance**
```
FIRST DUTY GUIDANCE:
- Observe before asserting. Your first proactive cycles should build your cognitive map.
- Ground every claim in evidence you can trace. Use anchor language: "In the {channel}
  channel, I observed..." not "It appears that..."
- Use hedging for uncertain observations: "This may indicate..." not "This confirms..."
- Build relationships through the Ward Room. Your trust starts at baseline (0.5) —
  earn it through demonstrated competence.
- Do not reference or invent past experiences. You have none yet.
```

### 3. Warm Boot Orientation Content

The `render_warm_boot_orientation()` output is injected into the first proactive cycle after a restart.

```
STASIS RECOVERY:
You were offline for {format_duration(stasis_duration)}.
Your identity and memories are intact — you are still {callsign}, {post} in {department}.
You have {episodic_memory_count} episodic memories from before stasis.

RE-ORIENTATION:
- Your recent memories reflect pre-stasis context. Check temporal anchors for currency.
- System events may have occurred during your stasis. Review bridge alerts and Ward Room activity.
- Resume normal operations. Your cognitive grounding is active.
```

### 4. Proactive Orientation Supplement

For agents younger than `orientation_window_seconds` (default 600), inject a brief orientation supplement into `_gather_context()`. This supplement diminishes linearly:

```python
def render_proactive_orientation(self, ctx: OrientationContext) -> str:
    age = ctx.agent_age_seconds
    window = self._config.orientation.orientation_window_seconds
    if age >= window:
        return ""  # Agent is localized, no supplement needed

    # Full supplement during first quarter, brief during middle, minimal at end
    if age < window * 0.25:
        return self._full_proactive_supplement(ctx)
    elif age < window * 0.75:
        return self._brief_proactive_supplement(ctx)
    else:
        return self._minimal_proactive_supplement(ctx)
```

**Full supplement (first 2.5 min):**
```
ORIENTATION ACTIVE: You are newly commissioned. Ground observations in evidence.
Distinguish what you observe (episodic) from what you know (parametric).
Check anchors before asserting: when, where, who, what caused it.
```

**Brief supplement (2.5–7.5 min):**
```
ORIENTATION: Ground claims in evidence. Distinguish observation from training knowledge.
```

**Minimal supplement (7.5–10 min):**
```
ORIENTATION: Check your anchors before asserting.
```

### 5. Anchor Field Population Gaps

Fix systematic gaps in AnchorFrame field population that reduce anchor confidence:

**5a. `watch_section` — populate from temporal context:**

In `proactive.py` where AnchorFrame is constructed (~line 512, ~684):
```python
# Derive watch_section from current hour (naval watch rotation)
from datetime import datetime, timezone
hour = datetime.now(timezone.utc).hour
if 0 <= hour < 4:
    watch = "mid"         # Mid Watch (0000-0400)
elif 4 <= hour < 8:
    watch = "morning"     # Morning Watch (0400-0800)
elif 8 <= hour < 12:
    watch = "forenoon"    # Forenoon Watch (0800-1200)
elif 12 <= hour < 16:
    watch = "afternoon"   # Afternoon Watch (1200-1600)
elif 16 <= hour < 20:
    watch = "first_dog" if hour < 18 else "second_dog"  # Dog Watches
else:
    watch = "first"       # First Watch (2000-0000)
```

This is a deterministic derivation — no LLM call needed. Add a helper function `_derive_watch_section() -> str` in `orientation.py` and call it wherever AnchorFrame is constructed.

**5b. `department` — populate in Ward Room episode paths:**

In `ward_room/messages.py` and `ward_room/threads.py` where AnchorFrame is created for Ward Room episodes, resolve the author's department from the agent registry or ontology:

```python
# Resolve department from author
dept = ""
agent = registry.get(author_id)
if agent and hasattr(agent, 'department'):
    dept = agent.department or ""
```

Add `department=dept` to the AnchorFrame construction in messages.py (~line 197) and threads.py (~line 397).

**5c. `event_log_window` — populate with recent event count:**

In all AnchorFrame construction sites, count recent events from the event log:

```python
event_log_window = 0.0
if hasattr(rt, 'event_log'):
    recent = rt.event_log.recent(seconds=60)
    event_log_window = float(len(recent))
```

This gives a numeric signal of how active the system was when the episode formed — a useful evidential anchor.

### 6. Configuration

Add to `src/probos/config.py`:

```python
class OrientationConfig(BaseModel):
    """Configuration for cognitive re-localization (AD-567g)."""
    enabled: bool = True
    orientation_window_seconds: float = 600.0  # 10 minutes
    cold_start_full_orientation: bool = True
    warm_boot_orientation: bool = True
    proactive_supplement: bool = True
    populate_watch_section: bool = True
    populate_ward_room_department: bool = True
    populate_event_log_window: bool = True
```

Add `orientation: OrientationConfig = OrientationConfig()` to `SystemConfig`.

### 7. Integration Points

**7a. `agent_onboarding.py` — inject cold start orientation:**

After naming ceremony completes (line ~165, where `_newly_commissioned = True` is set), store the `OrientationContext` on the agent:

```python
# After naming ceremony
if orientation_service and self._config.orientation.enabled:
    orientation_ctx = orientation_service.build_orientation(
        agent,
        lifecycle_state="cold_start" if cold_start else "first_boot",
        crew_count=len(self._registry.all()),
        departments=self._get_departments(),
        episodic_memory_count=0,
        trust_score=0.5,
    )
    agent._orientation_context = orientation_ctx
    agent._orientation_rendered = orientation_service.render_cold_start_orientation(orientation_ctx)
```

The `OrientationService` is injected into `AgentOnboardingService.__init__()` as an optional parameter: `orientation_service: OrientationService | None = None`.

**7b. `cognitive_agent.py` — inject orientation into temporal context:**

In `_build_temporal_context()` (line ~1646), after the BF-102 newly-commissioned block, add:

```python
# AD-567g: Cognitive re-localization orientation
orientation = getattr(self, '_orientation_rendered', None)
if orientation:
    parts.append(orientation)
```

On cold start, this replaces the BF-034 system note (which is subsumed into the orientation content). Preserve the BF-034 note as a fallback if orientation is disabled.

**7c. `proactive.py` — ongoing orientation supplement:**

In `_gather_context()` (line ~714), after the cold-start system note block (lines 727-734), add:

```python
# AD-567g: Proactive orientation supplement (diminishing)
if self._orientation_service and self._config.orientation.proactive_supplement:
    age = time.time() - getattr(agent, '_birth_timestamp', time.time())
    if age < self._config.orientation.orientation_window_seconds:
        ctx = self._orientation_service.build_orientation(
            agent,
            lifecycle_state=getattr(rt, '_lifecycle_state', 'restart'),
            episodic_memory_count=_get_episode_count(agent),
            trust_score=trust_score,
        )
        supplement = self._orientation_service.render_proactive_orientation(ctx)
        if supplement:
            context["orientation_supplement"] = supplement
```

The `OrientationService` is injected into the proactive think manager (same pattern as other services).

**7d. `proactive.py` — anchor field gap fixes:**

In all AnchorFrame construction sites in `proactive.py`:
- Add `watch_section=_derive_watch_section()` call
- Add `event_log_window=_get_event_window(rt)` call

**7e. `ward_room/messages.py` and `ward_room/threads.py` — department in Ward Room anchors:**

In AnchorFrame construction for Ward Room episodes, resolve and populate the `department` field from the author's agent record.

**7f. `startup/cognitive_services.py` — wire OrientationService:**

Wire `OrientationService` during startup, same pattern as other cognitive services:

```python
# AD-567g: Cognitive Re-Localization
orientation_service = OrientationService(config=config)
```

Pass to `AgentOnboardingService` and proactive think manager.

**7g. `startup/finalize.py` — warm boot orientation:**

In the stasis recovery path (lines 272-284), after the Ward Room announcement, set orientation context on each agent:

```python
if lifecycle_state == "stasis_recovery" and orientation_service:
    for agent in runtime.registry.all():
        if is_crew_agent(agent):
            ctx = orientation_service.build_orientation(
                agent,
                lifecycle_state="stasis_recovery",
                stasis_duration=stasis_duration,
                episodic_memory_count=_get_episode_count(agent),
                trust_score=_get_trust(agent),
            )
            agent._orientation_rendered = orientation_service.render_warm_boot_orientation(ctx)
```

## Files to Modify

| File | Change |
|------|--------|
| `src/probos/cognitive/orientation.py` | **NEW** — OrientationService, OrientationContext, _derive_watch_section() |
| `src/probos/config.py` | Add OrientationConfig, wire into SystemConfig |
| `src/probos/agent_onboarding.py` | Inject orientation_service, set orientation context after naming |
| `src/probos/cognitive/cognitive_agent.py` | Inject orientation into _build_temporal_context() |
| `src/probos/proactive.py` | Proactive orientation supplement + anchor field gap fixes (watch_section, event_log_window) |
| `src/probos/ward_room/messages.py` | Populate department in Ward Room episode anchors |
| `src/probos/ward_room/threads.py` | Populate department in Ward Room episode anchors |
| `src/probos/startup/cognitive_services.py` | Wire OrientationService |
| `src/probos/startup/finalize.py` | Warm boot orientation injection |
| `tests/test_orientation.py` | **NEW** — test suite |

## Tests (28 tests)

### OrientationContext (4 tests)
1. `test_build_orientation_cold_start` — all fields populated correctly for cold start
2. `test_build_orientation_warm_boot` — stasis_duration and episodic_memory_count populated
3. `test_build_orientation_defaults` — missing optional fields use sensible defaults
4. `test_orientation_context_frozen` — dataclass is immutable

### Cold Start Orientation (5 tests)
5. `test_cold_start_orientation_identity_section` — contains callsign, post, department, reports_to
6. `test_cold_start_orientation_cognitive_section` — contains episodic vs parametric distinction
7. `test_cold_start_orientation_first_duty_section` — contains hedging language guidance
8. `test_cold_start_orientation_zero_memories` — "You have no memories yet" message when count is 0
9. `test_cold_start_orientation_social_verification` — mentions social verification when available

### Warm Boot Orientation (4 tests)
10. `test_warm_boot_orientation_stasis_duration` — includes formatted stasis duration
11. `test_warm_boot_orientation_memory_count` — mentions intact episodic memory count
12. `test_warm_boot_orientation_identity_preserved` — confirms identity intact message
13. `test_warm_boot_orientation_re_orientation_reminder` — includes temporal anchor check reminder

### Proactive Supplement (5 tests)
14. `test_proactive_supplement_full` — full supplement at age 0
15. `test_proactive_supplement_brief` — brief supplement at age = window * 0.5
16. `test_proactive_supplement_minimal` — minimal supplement at age = window * 0.9
17. `test_proactive_supplement_expired` — empty string at age >= window
18. `test_proactive_supplement_disabled` — empty when config disabled

### Anchor Field Gaps (5 tests)
19. `test_derive_watch_section_mid` — hour 2 → "mid"
20. `test_derive_watch_section_forenoon` — hour 10 → "forenoon"
21. `test_derive_watch_section_dog` — hour 17 → "first_dog", hour 19 → "second_dog"
22. `test_ward_room_episode_has_department` — Ward Room AnchorFrame includes author's department
23. `test_event_log_window_populated` — AnchorFrame event_log_window reflects recent event count

### Integration (5 tests)
24. `test_onboarding_sets_orientation_context` — wire_agent() stores orientation on agent
25. `test_temporal_context_includes_orientation` — _build_temporal_context() includes orientation text
26. `test_gather_context_includes_supplement` — _gather_context() includes proactive supplement for new agents
27. `test_gather_context_no_supplement_after_window` — supplement absent after orientation_window_seconds
28. `test_finalize_sets_warm_boot_orientation` — stasis recovery path sets warm boot orientation on crew agents

## Non-Goals

- **Interactive LLM-mediated orientation** — no anchor-formation exercises or calibration prompts. The orientation is a structured text injection, not a multi-turn conversation. Interactive onboarding belongs in AD-486 (Holodeck Birth Chamber) / AD-509 (Boot Camp curriculum).
- **Method of Loci / Memory Palace** — the ship-as-memory-palace concept is documented in cognitive skill training research but requires AD-486's interactive environment. 567g provides the reference frame foundation that AD-486/AD-509 memory palace training builds on.
- **Cognitive skill training** — source monitoring, confidence calibration, retrieval strategy are AD-568 series (specifically AD-568d: Source Monitoring Skill). 567g teaches the BASICS (episodic vs parametric, check your anchors) but not the full metacognitive skill set.

## Build Order

This is the final AD in the 567 lineage. After build:
1. Run full test suite
2. Update PROGRESS.md, DECISIONS.md, roadmap.md
3. Mark 567g complete in build order
4. Run `/qualify` to establish post-567g baselines — this completes the Memory Anchoring wave

## Builder Instruction

```
Read and execute the build prompt in d:\ProbOS\prompts\ad-567g-cognitive-relocalization.md
```
