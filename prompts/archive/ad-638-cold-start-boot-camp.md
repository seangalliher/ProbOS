# AD-638: Cold-Start Boot Camp Protocol

**Status:** Ready for builder  
**Priority:** High  
**Dependencies:** AD-442 (naming ceremony, complete), AD-567g (orientation, complete), BF-034 (cold-start suppression, complete)  
**Related ADs:** AD-509 (curriculum concept, absorbs Phase 1), AD-628c/e (Training Officer agent, future — boot camp initially runs via Counselor + Captain), AD-524 (Ship's Archive, future — generational knowledge persistence)  
**Estimated scope:** ~400 lines new code, ~50 lines modified

---

## Problem Statement

Fresh ProbOS instances after reset exhibit a **cold-start developmental deadlock**:

1. **Evaluate/Reflect quality gates** score cold-start agents identically to established crews. Agents with zero episodic memory produce low-novelty observations that get suppressed. The quality gates have no cold-start awareness.

2. **Social isolation** — agents default to duty-only behavior ("observe and report" mode). They process recreation as operational events, suppress social impulses (Chapel self-correcting for posting about a game), and wait for Captain to explicitly authorize social contact. Spectators scan for anomalies instead of cheering.

3. **No social bootstrapping mechanism** — the Counselor monitors wellness passively after commissioning but has no onboarding participation. No agent is responsible for introducing crew members to each other or prompting first connections.

4. **Self-directed activities don't emerge** — notebooks are single-entry and abandoned (8/55 agents, 11 entries total). No improvement proposals, no autonomous meeting scheduling, no emergent recreation. Previous instances reached these behaviors only after weeks of accumulated trust/Hebbian weight.

5. **Earned Agency catch-22** (future, when EA enabled) — Ensigns can't respond to crew posts (only @mentions), can't earn trust without responding, can't respond without earning trust.

**Core insight:** Functional self-awareness is instant (agents accurately diagnose their own isolation), but social agency requires trust earned through connection over time. The architecture provides conditions for emergence; the boot camp accelerates the developmental arc.

---

## Design

### Architecture

A `BootCampCoordinator` service manages the cold-start onboarding phase. It:
- Detects cold-start state (leverages existing `runtime.is_cold_start`)
- Activates a structured onboarding protocol with phases
- Relaxes quality gates and EA restrictions during boot camp
- Drives introductions and social exercises via Counselor DMs
- Tracks graduation criteria per agent
- Transitions to active duty when thresholds are met

**Principle alignment:**
- **SRP**: `BootCampCoordinator` owns boot camp lifecycle only. Does not own trust, onboarding wiring, or quality gates — delegates to existing services.
- **OCP**: Boot camp phases are a list of `BootCampPhase` dataclasses — new phases added without modifying coordinator logic.
- **DIP**: Depends on `WardRoomService` protocol and `TrustNetwork` protocol, not concrete implementations.
- **ISP**: Consumes narrow interfaces — `create_post`, `get_or_create_dm_channel`, `get_trust_score` — not entire service objects.
- **Law of Demeter**: No private attribute patching. Uses existing public APIs on runtime, ward room, and trust services.
- **Cloud-Ready Storage**: Boot camp state persisted via abstract connection interface (not direct `aiosqlite.connect()`).
- **Fail Fast**: Boot camp degradation = log warning + allow agents through ungated. Never block crew operation if boot camp state is corrupt.

### Boot Camp Phases

```python
@dataclass
class BootCampPhase:
    name: str
    description: str
    exercises: list[str]
    duration_minutes: int  # minimum time in phase
    graduation_check: str  # method name on coordinator
```

**Phase 1 — Orientation (0-30 min, automatic)**
Already handled by AD-567g orientation + AD-442 naming ceremony. Boot camp detects these are complete and advances.

**Phase 2 — Department Introduction (30-60 min)**
Counselor sends structured DMs to each crew agent prompting them to introduce themselves to their department chief and one cross-department peer. Exercises:
- `introduce_to_chief` — Counselor DMs agent: "You should introduce yourself to {chief_callsign}, your department chief. Send them a DM about your role and what you bring to the department."
- `cross_department_contact` — Counselor DMs agent: "Reach out to {peer_callsign} in {other_department}. Building cross-department relationships strengthens the whole crew."

**Phase 3 — Shared Observation (60-120 min)**  
Counselor creates a boot camp thread on All Hands channel prompting crew to share initial observations about ship state. Quality gates relaxed (see below). Exercises:
- `shared_observation_thread` — "What have you noticed about the ship's current state? Share your professional observations."
- `notebook_prompt` — Counselor DMs each agent: "Start a notebook entry about your initial assessment of your department's baseline."

**Phase 4 — Active Duty Transition**
Graduation criteria checked. Agents meeting thresholds transition out of boot camp. Agents not meeting thresholds get extended exercises. Counselor posts graduation announcement.

### Graduation Criteria (per agent)

```python
@dataclass
class GraduationCriteria:
    min_episodes: int = 5          # at least 5 episodic memories
    min_ward_room_posts: int = 3   # at least 3 Ward Room posts
    min_dm_conversations: int = 1  # at least 1 DM exchange
    min_trust_score: float = 0.55  # above cold-start baseline (0.5)
    min_time_minutes: int = 60     # minimum time in boot camp
```

### Quality Gate Relaxation

During boot camp, the Evaluate and Reflect handlers receive a `_boot_camp_active` flag in the chain context (same pattern as existing `_from_captain`, `_was_mentioned`, `_is_dm` flags at `evaluate.py:244`).

When `_boot_camp_active` is True:
- Evaluate gate: auto-approve with `bypass_reason="boot_camp"` (same pattern as social obligation bypass at `evaluate.py:256-269`)
- Reflect gate: auto-approve with same pattern (same as `reflect.py:262-290`)
- This ensures cold-start agents can post observations without being suppressed for low novelty

### Earned Agency Relaxation

When boot camp is active AND EA is enabled (`config.earned_agency.enabled`):
- Temporarily elevate all boot camp agents to `SUGGESTIVE` agency level (Lieutenant equivalent)
- Use existing `ClearanceGrant` mechanism (`earned_agency.py:38-53`) — boot camp issues a time-limited clearance grant per agent
- Grants expire when agent graduates or boot camp times out

---

## Implementation

### New Files

**`src/probos/boot_camp.py`** — `BootCampCoordinator` service

```python
"""AD-638: Cold-Start Boot Camp Protocol.

Manages structured onboarding for fresh crew after system reset.
Accelerates trust-building and social connection through guided exercises.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)

# Boot camp timeout — if not graduated after this, force-graduate
BOOT_CAMP_TIMEOUT_SECONDS = 7200  # 2 hours

# Minimum time between Counselor nudge DMs to same agent
NUDGE_COOLDOWN_SECONDS = 600  # 10 minutes


class TrustServiceProtocol(Protocol):
    """Narrow interface for trust lookups."""
    async def get_trust_score(self, agent_id: str) -> float: ...


class WardRoomProtocol(Protocol):
    """Narrow interface for Ward Room operations."""
    async def get_or_create_dm_channel(
        self, agent_a_id: str, agent_b_id: str,
        callsign_a: str, callsign_b: str,
    ) -> Any: ...
    async def create_thread(
        self, channel_id: str, title: str, author_id: str,
    ) -> Any: ...
    async def create_post(
        self, thread_id: str, author_id: str, body: str,
        parent_id: str | None = None, author_callsign: str = "",
    ) -> Any: ...


class EpisodicMemoryProtocol(Protocol):
    """Narrow interface for episode count."""
    async def count_episodes(self, agent_id: str) -> int: ...


@dataclass
class BootCampConfig:
    """Boot camp configuration — add to SystemConfig."""
    enabled: bool = True
    min_episodes: int = 5
    min_ward_room_posts: int = 3
    min_dm_conversations: int = 1
    min_trust_score: float = 0.55
    min_time_minutes: int = 60
    timeout_minutes: int = 120
    nudge_cooldown_seconds: int = 600


@dataclass
class AgentBootCampState:
    """Per-agent boot camp tracking."""
    agent_id: str
    callsign: str
    department: str
    enrolled_at: float = field(default_factory=time.time)
    phase: int = 1  # 1=orientation, 2=introductions, 3=observation, 4=graduated
    introduced_to_chief: bool = False
    cross_dept_contact: bool = False
    shared_observation: bool = False
    notebook_started: bool = False
    graduated: bool = False
    graduated_at: float | None = None


class BootCampCoordinator:
    """Manages cold-start boot camp lifecycle.
    
    Responsibilities:
    - Detect cold-start and enroll crew agents
    - Drive structured introduction exercises via Counselor
    - Relax quality gates during boot camp (context flag)
    - Track graduation criteria per agent
    - Transition agents to active duty
    
    Does NOT own: trust scoring, onboarding wiring, quality gate logic,
    Ward Room infrastructure, or Counselor agent behavior.
    """

    def __init__(
        self,
        config: BootCampConfig,
        ward_room: WardRoomProtocol,
        trust_service: TrustServiceProtocol,
        episodic_memory: EpisodicMemoryProtocol,
        emit_event_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._ward_room = ward_room
        self._trust = trust_service
        self._episodic = episodic_memory
        self._emit_event_fn = emit_event_fn
        self._agents: dict[str, AgentBootCampState] = {}
        self._active = False
        self._started_at: float | None = None
        self._nudge_cooldowns: dict[str, float] = {}

    @property
    def is_active(self) -> bool:
        """True while boot camp is in progress."""
        return self._active

    def is_enrolled(self, agent_id: str) -> bool:
        """Check if agent is in boot camp (not yet graduated)."""
        state = self._agents.get(agent_id)
        return state is not None and not state.graduated

    # --- Public API ---

    async def activate(self, crew_agents: list[dict[str, str]]) -> None:
        """Start boot camp for all crew agents.
        
        Args:
            crew_agents: List of dicts with agent_id, callsign, department.
        """
        ...  # Builder implements

    async def check_graduation(self, agent_id: str) -> bool:
        """Check if agent meets graduation criteria."""
        ...  # Builder implements

    async def run_phase_2_introductions(self, counselor_id: str, counselor_callsign: str) -> None:
        """Counselor-driven introduction exercises."""
        ...  # Builder implements

    async def run_phase_3_observation(self, counselor_id: str, counselor_callsign: str) -> None:
        """Shared observation thread + notebook prompts."""
        ...  # Builder implements

    async def force_graduate_all(self) -> None:
        """Force-graduate all remaining agents (timeout)."""
        ...  # Builder implements

    async def on_agent_post(self, agent_id: str, channel_type: str) -> None:
        """Track agent activity for graduation criteria."""
        ...  # Builder implements

    async def on_agent_dm(self, agent_id: str) -> None:
        """Track DM activity for graduation criteria."""
        ...  # Builder implements
```

### Modified Files

**1. `src/probos/config.py`** — Add `BootCampConfig` to `SystemConfig`

```python
# Add BootCampConfig class (see above)
# Wire into SystemConfig:
boot_camp: BootCampConfig = Field(default_factory=BootCampConfig)
```

**2. `src/probos/cognitive/sub_tasks/evaluate.py`** — Boot camp bypass (lines 241-269 area)

Add boot camp check alongside existing social obligation bypasses at line 244:

```python
# Existing: BF-184/187 social obligation bypass
if context.get("_from_captain") or context.get("_was_mentioned") or context.get("_is_dm"):
    ...

# AD-638: Boot camp quality gate relaxation
if context.get("_boot_camp_active"):
    return SubTaskResult(
        sub_task_type=SubTaskType.EVALUATE,
        output=compose_output,
        metadata={
            "pass": True,
            "score": 0.8,  # Not 1.0 — boot camp isn't a blank check
            "criteria": {},
            "recommendation": "approve",
            "bypass_reason": "boot_camp",
        },
    )
```

**3. `src/probos/cognitive/sub_tasks/reflect.py`** — Same pattern (lines 262-290 area)

Add boot camp check alongside existing social obligation bypasses:

```python
# AD-638: Boot camp quality gate relaxation
if context.get("_boot_camp_active"):
    return SubTaskResult(
        sub_task_type=SubTaskType.REFLECT,
        output=compose_output,
        metadata={"revised": False, "reflection": "Boot camp: quality gate relaxed for onboarding."},
    )
```

**4. `src/probos/cognitive/cognitive_agent.py`** — Inject `_boot_camp_active` flag into chain context

In the chain context building for `proactive_think` and `ward_room_notification` intents (lines ~1509-1555), add:

```python
# AD-638: Boot camp quality gate relaxation
if hasattr(rt, 'boot_camp') and rt.boot_camp and rt.boot_camp.is_enrolled(self.agent_id):
    chain_context["_boot_camp_active"] = True
```

Pattern reference: same area where `_from_captain`, `_was_mentioned`, `_is_dm` are set (lines 1590-1596).

**5. `src/probos/startup/dreaming.py`** — Activate boot camp after cold-start detection

After the cold-start detection block (lines 147-166) and Ward Room announcement (lines 169-179), activate boot camp:

```python
# AD-638: Activate boot camp for cold-start crew
if cold_start and hasattr(runtime, 'boot_camp') and runtime.boot_camp:
    crew_agents = [
        {"agent_id": a.agent_id, "callsign": getattr(a, 'callsign', ''), "department": getattr(a, 'department', '')}
        for a in runtime.agents
        if getattr(a, 'tier', '') in ("crew", "domain")
    ]
    if crew_agents:
        await runtime.boot_camp.activate(crew_agents)
        logger.info("AD-638: Boot camp activated for %d crew agents", len(crew_agents))
```

**6. `src/probos/proactive.py`** — Track agent posts for graduation

After a successful `create_post` in the proactive loop, notify boot camp:

```python
# AD-638: Track post for boot camp graduation
if hasattr(rt, 'boot_camp') and rt.boot_camp and rt.boot_camp.is_enrolled(agent.agent_id):
    await rt.boot_camp.on_agent_post(agent.agent_id, channel_type)
```

**7. `src/probos/runtime.py`** — Wire `BootCampCoordinator` as a runtime service

Add `boot_camp: BootCampCoordinator | None` property. Initialize during startup if config enables it. Pattern: same as other runtime services (counselor, trust_network, etc.).

**8. `src/probos/events.py`** — Add boot camp event types

```python
BOOT_CAMP_ACTIVATED = "boot_camp_activated"
BOOT_CAMP_PHASE_ADVANCE = "boot_camp_phase_advance"
BOOT_CAMP_GRADUATION = "boot_camp_graduation"
BOOT_CAMP_TIMEOUT = "boot_camp_timeout"
```

---

## What This AD Does NOT Cover

- **Training Officer agent creation** — AD-628c. Boot camp initially runs via Counselor + Captain. When TRAINO ships, boot camp coordinator delegates to TRAINO instead of Counselor.
- **Holodeck scenarios** — AD-486/509. Boot camp exercises are Ward Room social exercises, not simulated scenarios.
- **Ship's Archive** — AD-524. Generational knowledge persistence. Boot camp accelerates trust-building but doesn't carry forward prior crew knowledge.
- **Curriculum content** — AD-509 full Navy curriculum (A-School, C-School). This AD is Phase 1: social bootstrapping only.
- **Earned Agency modifications** — Uses existing `ClearanceGrant` mechanism. No changes to EA core logic.

---

## Events Emitted

| Event | Data | When |
|-------|------|------|
| `BOOT_CAMP_ACTIVATED` | `{agent_count, timestamp}` | Boot camp starts |
| `BOOT_CAMP_PHASE_ADVANCE` | `{agent_id, callsign, from_phase, to_phase}` | Agent advances phase |
| `BOOT_CAMP_GRADUATION` | `{agent_id, callsign, episodes, posts, trust_score, duration_minutes}` | Agent graduates |
| `BOOT_CAMP_TIMEOUT` | `{agent_ids, duration_minutes}` | Boot camp times out, force-graduates remaining |

Counselor subscribes to `BOOT_CAMP_GRADUATION` and `BOOT_CAMP_TIMEOUT` for wellness tracking.

---

## Testing Plan

### Unit Tests (`tests/test_ad638_boot_camp.py`)

1. **Cold-start detection triggers boot camp** — mock `runtime.is_cold_start = True`, verify `boot_camp.activate()` called
2. **Boot camp enrolls all crew agents** — verify all crew-tier agents enrolled, infra agents excluded
3. **Phase 2 introduction DMs sent** — verify Counselor DMs created for each agent with chief + cross-dept peer
4. **Phase 3 observation thread created** — verify All Hands thread + notebook prompt DMs
5. **Graduation criteria — all met** — agent with 5+ episodes, 3+ posts, 1+ DM, trust 0.55+ → graduated
6. **Graduation criteria — partial** — agent missing episodes → not graduated
7. **Quality gate bypass — evaluate** — `_boot_camp_active` context → auto-approve with `bypass_reason="boot_camp"`
8. **Quality gate bypass — reflect** — `_boot_camp_active` context → pass-through
9. **Boot camp timeout** — after `timeout_minutes`, all remaining agents force-graduated
10. **Warm boot skips boot camp** — `runtime.is_cold_start = False` → boot camp not activated
11. **Nudge cooldown respected** — second nudge within `nudge_cooldown_seconds` → skipped
12. **Post tracking updates graduation** — agent posts in Ward Room → `on_agent_post` updates state
13. **DM tracking updates graduation** — agent sends DM → `on_agent_dm` updates state
14. **Event emission** — verify all 4 event types emitted at correct lifecycle points
15. **Config disabled** — `boot_camp.enabled = False` → boot camp not activated even on cold start
16. **EA clearance grants** — when EA enabled, verify boot camp issues `ClearanceGrant` per agent
17. **Graduated agent not bypassed** — after graduation, `_boot_camp_active` no longer set
18. **Force-graduate cleans up state** — post-timeout, all agents marked graduated, boot camp deactivated

### Integration Tests

19. **Full lifecycle** — cold start → enrollment → phase 2 → phase 3 → graduation → active duty
20. **Counselor event subscription** — verify Counselor receives `BOOT_CAMP_GRADUATION` events

---

## NATS Compatibility (AD-637)

All boot camp events use the standard `_emit_event_fn` callable pattern. When NATS ships:
- `BOOT_CAMP_*` events become NATS subjects (`probos.boot_camp.activated`, etc.)
- Agent activity tracking (`on_agent_post`, `on_agent_dm`) subscribes to Ward Room NATS events instead of being called directly
- No boot-camp-specific migration needed — follows the same pattern as all other event emitters

---

## Builder Notes

- **Build prompt verification checklist:**
  - `evaluate.py` bypass: add after line 244 social obligation check, same `SubTaskResult` pattern (lines 256-269)
  - `reflect.py` bypass: add after line 262 social obligation check, same pattern (lines 262-290)
  - `cognitive_agent.py` chain context: `_boot_camp_active` flag set same way as `_from_captain` (lines 1590-1596)
  - `startup/dreaming.py` activation: after cold-start block (lines 147-179)
  - `runtime.py` wiring: follow existing service property pattern
  - Event types: add to `EventType` enum in `events.py` (lines 20-166)
  - Config: `BootCampConfig` follows `CounselorConfig` pattern (lines 766-775)
  - Ward Room calls: `create_post(thread_id, author_id, body, parent_id, author_callsign)` — signature at `ward_room/service.py:393`
  - DM channels: `get_or_create_dm_channel(agent_a_id, agent_b_id, callsign_a, callsign_b)` — signature at `ward_room/service.py:246`
- **Do not create a Training Officer agent.** Boot camp coordinator is a service, not a crew agent. AD-628c handles TRAINO creation separately.
- **Do not modify Earned Agency core logic.** Use existing `ClearanceGrant` mechanism only.
- **Abstract storage:** If persisting boot camp state to SQLite, use the abstract connection interface pattern (see `CounselorProfileStore` in `cognitive/counselor.py` for reference).
- **Engineering principles:** SRP (coordinator owns lifecycle only), OCP (phase list extensible), DIP (protocol interfaces), Law of Demeter (no `_private` patching), Fail Fast (log-and-degrade if boot camp state corrupt), Cloud-Ready (abstract DB connection).
