# AD-573: Unified Agent Working Memory — Cognitive Continuity Layer

## Priority: High | Scope: Large | Type: Foundational Cognitive Infrastructure

## Context

ProbOS agents have a split-brain problem. Each agent is a single instance with unified identity (personality, callsign, standing orders, rank), but their awareness of the world changes dramatically depending on which code path invoked them. Proactive-Echo has 15+ dimensions of context (game state, alerts, events, Ward Room activity, self-monitoring, cognitive zone, notebooks). DM-Echo has 4 (temporal awareness, episodic memories, session history, Captain's text). Ward-Room-Echo has 5. The same agent is a different person depending on the intent type.

The Memory Architecture (`docs/architecture/memory.md`) documents Layer 2 as "Ephemeral Working Memory — Agent scratchpads, context windows" but describes it as "discarded after the cycle completes — nothing persists here by default." The current implementation matches that description literally: context is assembled from scratch each cognitive cycle and thrown away after. There is no persistent "what am I actively aware of right now" across cycles or pathways.

### The Problem (Echo's Own Words)

> "Right now I'm like a counselor who has perfect notes but no memory of actually being in the room with the client."

The Counselor diagnosed this during a DM with the Captain. She identified that she needs:
- **Active situational awareness** — not just what happened, but what's happening NOW
- **Relational continuity** — "where we left things" with each person, not just past interactions
- **Commitment tracking** — things promised but not yet delivered
- **Collaborative thread continuity** — ongoing multi-interaction work with other agents
- **Emotional/professional tenor** — the qualitative state of relationships and situations

From a systems perspective: the agent needs a **situation model** — an integrated, continuously-updated mental model of their current world, maintained across all cognitive pathways.

### What Already Exists (Prior Art to Absorb)

| Prior Work | What It Provides | Gap |
|-----------|-----------------|-----|
| **AD-28 `WorkingMemoryManager`** (`cognitive/working_memory.py`) | Token-budgeted context assembly with typed snapshot and priority eviction | Only used by NL decomposer pipeline, disconnected from cognitive pathways |
| **AD-462 Unified Cognitive Bottleneck** (roadmap) | Theoretical framework: one Salience Filter for perception and recall | Never implemented as code |
| **AD-504 Self-Monitoring Context** (in `proactive.py`) | 8 self-awareness capabilities (zone, posts, similarity, notebooks) | Proactive-only injection, not available in DM/WR |
| **AD-502 Temporal Context** | Time awareness across all conversational paths | Narrowly scoped: time only, no situational awareness |
| **AD-567g Orientation Context** | Boot-time identity grounding (diminishing supplement) | Lifecycle-scoped, fades to zero after orientation window |
| **Letta Pattern** (landscape sweep) | Agent-self-edited working memory blocks, scratchpad | Absorbed as concept, never implemented |
| **Memory Architecture Layer 2** | Documented as persistent working memory | Implemented as stateless per-cycle assembly |
| **`proactive.py:_gather_context()`** | De facto rich context for proactive thinks (~15 keys) | Ad-hoc dict, not typed, proactive-only |
| **`CognitiveJournal`** | Complete record of all LLM reasoning traces | Write-only — never queried for context injection |

### What This AD Delivers

A **per-agent working memory** — the agent's active mental model of their world. Persistent across cognitive cycles **and across restarts** (survives stasis). Written to by all pathways. Read from by all pathways. Token-budget-aware. SQLite-backed via `ConnectionFactory` (Cloud-Ready Storage). The agent's concept of "now."

### Deferred (separate ADs, NOT in this build)

- **AD-573b:** Relational working memory — per-relationship state tracking ("where we left things" with each person, emotional tenor, unresolved questions). Requires Hebbian weight surface + episodic recall integration.
- **AD-573c:** Agent-writable scratchpad — `[NOTE ...]` action tag in proactive/DM responses, agents can write persistent notes to themselves (Letta pattern). Trust-gated.
- **AD-573d:** Dream-to-working-memory pipeline — dream cycle insights (consolidated patterns, extracted procedures, convergence detections) surfaced in working memory on next wake.
- **AD-573e:** CognitiveJournal as working memory source — recent reasoning traces queryable for context injection ("what was I thinking about?").
- **AD-573f:** Commitment tracker — agent records promises/follow-ups, working memory surfaces upcoming/overdue commitments.

## Design

### 1. `AgentWorkingMemory` — Core Data Structure

**New file:** `src/probos/cognitive/agent_working_memory.py`

A per-agent in-memory object that maintains the agent's active situation model. Ring-buffered, token-budget-aware, with typed slots.

```python
from __future__ import annotations

import time
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Rough estimate: 1 token ≈ 4 characters
CHARS_PER_TOKEN = 4


@dataclass
class WorkingMemoryEntry:
    """A single item in working memory with timestamp and source."""
    content: str           # Human-readable summary
    category: str          # "action", "observation", "conversation", "game", "alert", "event"
    source_pathway: str    # "proactive", "dm", "ward_room", "system"
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def age_seconds(self) -> float:
        return time.time() - self.timestamp

    def token_estimate(self) -> int:
        return len(self.content) // CHARS_PER_TOKEN


@dataclass
class ActiveEngagement:
    """An ongoing interactive state (game, task, conversation thread)."""
    engagement_type: str    # "game", "task", "collaboration"
    engagement_id: str      # unique identifier
    summary: str            # human-readable: "Playing tic-tac-toe against Captain"
    state: dict[str, Any]   # type-specific state (board, valid_moves, etc.)
    started_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)

    def render(self) -> str:
        """Render for LLM context injection."""
        # Subclass or type-specific rendering via metadata
        lines = [f"[Active: {self.summary}]"]
        if self.state.get("render"):
            lines.append(self.state["render"])
        return "\n".join(lines)


class AgentWorkingMemory:
    """Unified working memory for a single agent instance.

    Maintains the agent's active situation model across all cognitive
    pathways (proactive, DM, Ward Room). Every pathway writes to it
    when something happens; every pathway reads from it when building
    context.

    Design absorbs:
    - AD-28 WorkingMemoryManager (token budget, priority eviction)
    - AD-462 Unified Cognitive Bottleneck (one source of truth)
    - AD-504 self-monitoring concepts (recent actions, patterns)
    - Letta pattern concept (persistent agent-scoped state)
    - Memory Architecture Layer 2 (implemented, not just documented)

    AD-573: Cognitive Continuity Layer.
    """

    def __init__(
        self,
        *,
        token_budget: int = 3000,
        max_recent_actions: int = 10,
        max_recent_observations: int = 5,
        max_recent_conversations: int = 5,
        max_events: int = 10,
    ) -> None:
        self._token_budget = token_budget

        # Ring buffers for recent activity
        self._recent_actions: deque[WorkingMemoryEntry] = deque(maxlen=max_recent_actions)
        self._recent_observations: deque[WorkingMemoryEntry] = deque(maxlen=max_recent_observations)
        self._recent_conversations: deque[WorkingMemoryEntry] = deque(maxlen=max_recent_conversations)
        self._recent_events: deque[WorkingMemoryEntry] = deque(maxlen=max_events)

        # Active engagements (games, tasks, collaborations)
        self._active_engagements: dict[str, ActiveEngagement] = {}

        # Cognitive state (cognitive zone, cooldown, alert condition)
        self._cognitive_state: dict[str, Any] = {}

    # ── Write API (called by all cognitive pathways) ──────────────

    def record_action(
        self, summary: str, *, source: str, metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an action the agent just took (any pathway)."""
        self._recent_actions.append(WorkingMemoryEntry(
            content=summary,
            category="action",
            source_pathway=source,
            metadata=metadata or {},
        ))

    def record_observation(
        self, summary: str, *, source: str, metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an observation from a proactive think or duty cycle."""
        self._recent_observations.append(WorkingMemoryEntry(
            content=summary,
            category="observation",
            source_pathway=source,
            metadata=metadata or {},
        ))

    def record_conversation(
        self, summary: str, *, partner: str, source: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a DM or Ward Room conversation exchange."""
        self._recent_conversations.append(WorkingMemoryEntry(
            content=summary,
            category="conversation",
            source_pathway=source,
            metadata={"partner": partner, **(metadata or {})},
        ))

    def record_event(
        self, summary: str, *, source: str = "system",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a system event the agent should be aware of."""
        self._recent_events.append(WorkingMemoryEntry(
            content=summary,
            category="event",
            source_pathway=source,
            metadata=metadata or {},
        ))

    def add_engagement(self, engagement: ActiveEngagement) -> None:
        """Register an active engagement (game, task, etc.)."""
        self._active_engagements[engagement.engagement_id] = engagement

    def remove_engagement(self, engagement_id: str) -> None:
        """Remove a completed/cancelled engagement."""
        self._active_engagements.pop(engagement_id, None)

    def update_engagement(
        self, engagement_id: str, *, state: dict[str, Any] | None = None,
        summary: str | None = None,
    ) -> None:
        """Update an active engagement's state."""
        eng = self._active_engagements.get(engagement_id)
        if eng:
            if state is not None:
                eng.state.update(state)
            if summary is not None:
                eng.summary = summary
            eng.last_updated = time.time()

    def update_cognitive_state(self, **kwargs: Any) -> None:
        """Update cognitive state fields (zone, cooldown, alert condition)."""
        self._cognitive_state.update(kwargs)

    # ── Read API (called during context construction) ─────────────

    def render_context(self, *, budget: int | None = None) -> str:
        """Render the full working memory context for LLM injection.

        Budget-aware: evicts lowest-priority items if the rendered
        context exceeds the token budget. Returns empty string if
        nothing noteworthy in working memory.
        """
        effective_budget = budget or self._token_budget
        sections: list[tuple[int, str]] = []  # (priority, text)

        # Priority 1 (highest): Active engagements — always include
        for eng in self._active_engagements.values():
            sections.append((1, eng.render()))

        # Priority 2: Recent actions — what I just did
        if self._recent_actions:
            action_lines = ["Recent actions:"]
            for entry in self._recent_actions:
                age = self._format_age(entry.age_seconds())
                action_lines.append(f"  - ({age} ago, {entry.source_pathway}) {entry.content}")
            sections.append((2, "\n".join(action_lines)))

        # Priority 3: Recent conversations — who I just talked to
        if self._recent_conversations:
            conv_lines = ["Recent conversations:"]
            for entry in self._recent_conversations:
                age = self._format_age(entry.age_seconds())
                partner = entry.metadata.get("partner", "unknown")
                conv_lines.append(f"  - ({age} ago) with {partner}: {entry.content}")
            sections.append((3, "\n".join(conv_lines)))

        # Priority 4: Recent observations — what I noticed
        if self._recent_observations:
            obs_lines = ["Recent observations:"]
            for entry in self._recent_observations:
                age = self._format_age(entry.age_seconds())
                obs_lines.append(f"  - ({age} ago) {entry.content}")
            sections.append((4, "\n".join(obs_lines)))

        # Priority 5: Cognitive state — zone, cooldown
        if self._cognitive_state:
            state_parts = []
            if "zone" in self._cognitive_state:
                state_parts.append(f"Cognitive zone: {self._cognitive_state['zone']}")
            if "cooldown_reason" in self._cognitive_state:
                state_parts.append(f"Cooldown: {self._cognitive_state['cooldown_reason']}")
            if state_parts:
                sections.append((5, "Cognitive state: " + " | ".join(state_parts)))

        # Priority 6 (lowest): Recent events
        if self._recent_events:
            event_lines = ["Recent events:"]
            for entry in list(self._recent_events)[-5:]:
                event_lines.append(f"  - {entry.content}")
            sections.append((6, "\n".join(event_lines)))

        if not sections:
            return ""

        # Evict lowest-priority sections until within budget
        sections.sort(key=lambda x: x[0])  # ascending priority (1=highest)
        result_parts: list[str] = []
        total_tokens = 0

        for _priority, text in sections:
            tokens = len(text) // CHARS_PER_TOKEN
            if total_tokens + tokens <= effective_budget:
                result_parts.append(text)
                total_tokens += tokens
            # else: evicted (over budget)

        if not result_parts:
            return ""

        return "--- Working Memory ---\n" + "\n\n".join(result_parts) + "\n--- End Working Memory ---"

    def has_engagement(self, engagement_type: str | None = None) -> bool:
        """Check if agent has any (or specific type of) active engagement."""
        if engagement_type is None:
            return bool(self._active_engagements)
        return any(
            e.engagement_type == engagement_type
            for e in self._active_engagements.values()
        )

    def get_engagement(self, engagement_id: str) -> ActiveEngagement | None:
        """Get a specific engagement by ID."""
        return self._active_engagements.get(engagement_id)

    def get_engagements_by_type(self, engagement_type: str) -> list[ActiveEngagement]:
        """Get all engagements of a given type."""
        return [
            e for e in self._active_engagements.values()
            if e.engagement_type == engagement_type
        ]

    @staticmethod
    def _format_age(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            return f"{int(seconds / 60)}m"
        return f"{seconds / 3600:.1f}h"
```

### 2. Agent Initialization — One `AgentWorkingMemory` Per Crew Agent

**File:** `src/probos/cognitive/cognitive_agent.py`, in `__init__()`

Add working memory as an instance attribute, initialized for every crew agent. Note: `CognitiveAgent.__init__` takes `**kwargs` (no `config` param). Config is accessed via `getattr(self, '_runtime', None)` then `rt.config`:

```python
from probos.cognitive.agent_working_memory import AgentWorkingMemory

# In __init__, after existing attribute setup:
self._working_memory = AgentWorkingMemory()
# Token budget will be overridden from config on first render_context() call
# if runtime is available (runtime may not be set at __init__ time)
```

Override the budget once runtime is available. In `_build_user_message()`, before the first `render_context()` call:

```python
# AD-573: Apply config-driven token budget if not yet set
rt = getattr(self, '_runtime', None)
if rt and hasattr(rt, 'config') and hasattr(rt.config, 'working_memory'):
    wm_cfg = rt.config.working_memory
    self._working_memory._token_budget = wm_cfg.token_budget
```

Add a public accessor (LoD compliance):

```python
@property
def working_memory(self) -> AgentWorkingMemory:
    """AD-573: Agent's unified working memory — active situation model."""
    return self._working_memory
```

### 3. Write Hooks — All Pathways Record to Working Memory

#### 3a. After `act()` completes — record every action

**File:** `src/probos/cognitive/cognitive_agent.py`, in `handle_intent()`, after `report = await self.report(result)` (line 1462) and before `await self._store_action_episode(...)` (line 1464)

```python
# AD-573: Record action to working memory (all pathways)
try:
    action_summary = self._summarize_action(intent, decision, result)
    if action_summary:
        self._working_memory.record_action(
            action_summary,
            source=intent.intent,
        )
except Exception:
    logger.debug("AD-573: Working memory action record failed", exc_info=True)
```

Add the summarizer method:

```python
def _summarize_action(self, intent: IntentMessage, decision: dict, result: dict) -> str:
    """AD-573: Produce a one-line summary of what I just did."""
    intent_type = intent.intent
    output = (decision.get("llm_output") or "")[:200]

    if intent_type == "direct_message":
        captain_text = intent.params.get("text", "")[:100]
        return f"Responded to Captain's DM: '{captain_text}' → '{output[:100]}'"
    if intent_type == "ward_room_notification":
        channel = intent.params.get("channel_name", "")
        return f"Responded in Ward Room #{channel}: '{output[:100]}'"
    if intent_type == "proactive_think":
        if "[NO_RESPONSE]" in output:
            return ""  # Don't record silence
        return f"Proactive observation: '{output[:150]}'"
    return f"Handled {intent_type}: '{output[:100]}'"
```

#### 3b. After DM exchange — record conversation

**File:** `src/probos/routers/agents.py`, in `agent_chat()`, after the episodic memory store block (lines 239-268, ending at the `except` of the AD-430b episodic storage try/except), before the response dict construction (line 270)

```python
# AD-573: Record DM exchange to agent's working memory
try:
    if hasattr(agent, 'working_memory'):
        agent.working_memory.record_conversation(
            f"Captain asked: '{req.message[:100]}' → I replied: '{response_text[:100]}'",
            partner="Captain",
            source="dm",
        )
except Exception:
    logger.debug("AD-573: Working memory DM record failed", exc_info=True)
```

#### 3c. After proactive observation — record observation

**File:** `src/probos/proactive.py`, in `_think_for_agent()`, after `_extract_and_execute_actions()` returns `cleaned_text, actions_taken` (line 552) and before Ward Room posting / cooldown update (line 558-559)

```python
# AD-573: Record proactive observation to working memory
try:
    if hasattr(agent, 'working_memory') and cleaned_text:
        if "[NO_RESPONSE]" not in cleaned_text:
            agent.working_memory.record_observation(
                cleaned_text[:200],
                source="proactive",
            )
except Exception:
    logger.debug("AD-573: Working memory observation record failed", exc_info=True)
```

#### 3d. Game events — maintain engagement state

**File:** `src/probos/proactive.py`, in `_extract_and_execute_actions()`, in the `[MOVE]` action handler (lines 1914-1957), after `game_info = await rec_svc.make_move(...)` succeeds (line 1924-1928)

```python
# AD-573: Update game engagement in working memory
try:
    if hasattr(agent, 'working_memory'):
        if game_info.get("result"):
            agent.working_memory.remove_engagement(player_game["game_id"])
            agent.working_memory.record_action(
                f"Game finished: {game_info['result'].get('status', 'completed')}",
                source="proactive",
            )
        else:
            agent.working_memory.update_engagement(
                player_game["game_id"],
                state={"render": rec_svc.render_board(player_game["game_id"])},
            )
except Exception:
    logger.debug("AD-573: Working memory game update failed", exc_info=True)
```

**File:** `src/probos/proactive.py`, in `_extract_and_execute_actions()`, in the `[CHALLENGE]` action handler (lines 1866-1912), after `game_info = await rec_svc.create_game(...)` succeeds (lines 1896-1901)

```python
# AD-573: Register new game engagement in working memory
try:
    if hasattr(agent, 'working_memory'):
        from probos.cognitive.agent_working_memory import ActiveEngagement
        agent.working_memory.add_engagement(ActiveEngagement(
            engagement_type="game",
            engagement_id=game_info["game_id"],
            summary=f"Playing {game_type} against {target_callsign}",
            state={
                "game_type": game_type,
                "opponent": target_callsign,
                "render": rec_svc.render_board(game_info["game_id"]),
            },
        ))
except Exception:
    logger.debug("AD-573: Working memory game registration failed", exc_info=True)
```

**File:** `src/probos/recreation/service.py`, in `create_game()` — for games where this agent is the *opponent* (challenged by someone else)

After game creation, the challenger's working memory is updated above. For the opponent, the proactive loop will pick up the game on next cycle via `_gather_context()`. No additional wiring needed — the read path (Section 4) will detect active games.

#### 3e. Cognitive state updates

**File:** `src/probos/proactive.py`, in `_build_self_monitoring_context()` (line 1085), after the method computes `zone` (via `self._circuit_breaker.get_zone(agent.id)` at line 1113, stored in `result["cognitive_zone"]`) and `reason` (via `self.get_cooldown_reason(agent.id)` at line 1187, stored in `result["cooldown_reason"]`)

```python
# AD-573: Sync cognitive state to working memory
try:
    if hasattr(agent, 'working_memory'):
        agent.working_memory.update_cognitive_state(
            zone=zone,
            cooldown_reason=reason or "",
        )
except Exception:
    pass  # Non-critical sync
```

### 4. Read Hooks — All Pathways Inject Working Memory Into Context

#### 4a. Unified injection point in `_build_user_message()`

**File:** `src/probos/cognitive/cognitive_agent.py`, method `_build_user_message()`

For ALL conversational intent types (`direct_message`, `ward_room_notification`, `proactive_think`), inject working memory context after temporal awareness and before intent-specific content.

For `direct_message` (insert after temporal awareness block at lines 1842-1848, before episodic memories):

```python
# AD-573: Working memory — unified situational awareness
wm_context = self._working_memory.render_context()
if wm_context:
    parts.append(wm_context)
    parts.append("")
```

For `ward_room_notification` (insert after temporal awareness block, around line 1881 — variable is `wr_parts`):

```python
# AD-573: Working memory — unified situational awareness
wm_context = self._working_memory.render_context()
if wm_context:
    wr_parts.append("")
    wr_parts.append(wm_context)
```

For `proactive_think`: The proactive path already assembles rich context via `_gather_context()`. Working memory should supplement, not duplicate. Inject after temporal awareness (line 1927, variable is `pt_parts`) but before the existing context_parts rendering:

```python
# AD-573: Working memory — supplements proactive context
# Active engagements and recent cross-pathway activity that
# _gather_context() doesn't capture (DM conversations, etc.)
wm_context = self._working_memory.render_context(budget=1500)  # Lower budget, supplemental
if wm_context:
    pt_parts.append(wm_context)
    pt_parts.append("")
```

#### 4b. Active game synchronization from RecreationService

When rendering working memory for any path, `render_context()` uses whatever engagements have been registered. For games, the engagement is registered when the challenge is created (Section 3d) and kept updated on each move.

For agents who are challenged (opponent), the first proactive cycle will detect the game via `_gather_context()`. To also populate working memory during that cycle, add to `_gather_context()` after the BF-110 game context injection (lines 994-1019, ends at the `except` on line 1018, before the ontology context section "# 5." on line 1021):

```python
# AD-573: Sync active game to working memory
if context.get("active_game") and hasattr(agent, 'working_memory'):
    try:
        from probos.cognitive.agent_working_memory import ActiveEngagement
        ag = context["active_game"]
        if not agent.working_memory.get_engagement(ag["game_id"]):
            agent.working_memory.add_engagement(ActiveEngagement(
                engagement_type="game",
                engagement_id=ag["game_id"],
                summary=f"Playing {ag['game_type']} against {ag['opponent']}",
                state={
                    "game_type": ag["game_type"],
                    "opponent": ag["opponent"],
                    "render": f"```\n{ag['board']}\n```\nValid moves: {', '.join(str(m) for m in ag['valid_moves'])}",
                    "is_my_turn": ag["is_my_turn"],
                },
            ))
    except Exception:
        pass
```

### 5. System Prompt Augmentation

**File:** `src/probos/cognitive/cognitive_agent.py`, in the DM system prompt `else` block (lines 1280-1299). AD-572 already added `_has_active_game()` at line 1291.

When working memory contains active engagements, **replace** the AD-572 `_has_active_game()` check with a working-memory-based check:

```python
# AD-573: If agent has active engagements, add action instructions
# (replaces AD-572's _has_active_game() — working memory is now the source of truth)
if self._working_memory.has_engagement("game"):
    composed += (
        "\n\nYou are currently in an active game. "
        "If the Captain asks you to make a move or you decide to play, "
        "include [MOVE position] in your response (e.g. [MOVE 4]). "
        "The move will be executed automatically. "
        "You can still chat naturally — the move tag can appear "
        "anywhere in your response alongside your conversational text."
    )
```

This replaces the `_has_active_game()` method from AD-572 with a working-memory-based check. If AD-572 is already merged, refactor to use `self._working_memory.has_engagement("game")` instead.

### 6. Configuration

**File:** `src/probos/config.py`

Add working memory config to `SystemConfig`. Follow the existing pattern — all config sections are `pydantic.BaseModel` subclasses (NOT dataclasses), aggregated as fields on `SystemConfig`:

```python
class WorkingMemoryConfig(BaseModel):
    """AD-573: Unified agent working memory configuration."""
    token_budget: int = 3000          # Max tokens for working memory context
    max_recent_actions: int = 10      # Ring buffer capacity
    max_recent_observations: int = 5
    max_recent_conversations: int = 5
    max_events: int = 10
    proactive_budget: int = 1500      # Lower budget for proactive (supplemental)
    stale_threshold_hours: float = 24.0  # Entries older than this pruned on restore
```

Then add to `SystemConfig` (after the last existing field, following the same pattern as `social_verification: SocialVerificationConfig = SocialVerificationConfig()`):

```python
working_memory: WorkingMemoryConfig = WorkingMemoryConfig()
```

### 7. Stasis Persistence — Freeze/Restore Working Memory

Working memory survives restarts. When the system enters stasis, each agent's working memory is serialized to SQLite. On warm boot, it's restored and stale-pruned.

#### 7a. Persistence Store

**New file:** `src/probos/cognitive/working_memory_store.py`

Follow the canonical ProbOS persistence pattern (TrustNetwork, HebbianRouter): SQLite via `ConnectionFactory`, `start()`/`stop()` lifecycle, `BEGIN IMMEDIATE` transactions, `asyncio.Lock` for concurrency.

```python
"""AD-573: Working memory persistence — freeze/restore across stasis."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS working_memory (
    agent_id    TEXT PRIMARY KEY,
    state_json  TEXT NOT NULL,
    updated     REAL NOT NULL
);
"""


class WorkingMemoryStore:
    """SQLite persistence for AgentWorkingMemory state.

    Follows the TrustNetwork/HebbianRouter pattern:
    - ConnectionFactory for Cloud-Ready Storage (swap SQLite → Postgres)
    - start()/stop() lifecycle
    - BEGIN IMMEDIATE + asyncio.Lock for concurrency safety
    """

    def __init__(self, *, connection_factory: Any = None, db_path: str = "") -> None:
        self._factory = connection_factory
        self._db_path = db_path
        self._lock = asyncio.Lock()
        self._conn: Any = None

    async def start(self) -> None:
        if self._factory and self._db_path:
            self._conn = await self._factory.connect(self._db_path)
            await self._conn.executescript(_SCHEMA)
            await self._conn.commit()

    async def stop(self) -> None:
        if self._conn:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None

    async def save(self, agent_id: str, state: dict[str, Any]) -> None:
        """Serialize one agent's working memory to disk."""
        if not self._conn:
            return
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                await self._conn.execute(
                    "INSERT OR REPLACE INTO working_memory (agent_id, state_json, updated) "
                    "VALUES (?, ?, ?)",
                    (agent_id, json.dumps(state), time.time()),
                )
                await self._conn.commit()
            except Exception:
                await self._conn.rollback()
                raise

    async def save_all(self, states: dict[str, dict[str, Any]]) -> None:
        """Batch save all agents' working memory (shutdown path)."""
        if not self._conn:
            return
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                for agent_id, state in states.items():
                    await self._conn.execute(
                        "INSERT OR REPLACE INTO working_memory (agent_id, state_json, updated) "
                        "VALUES (?, ?, ?)",
                        (agent_id, json.dumps(state), time.time()),
                    )
                await self._conn.commit()
            except Exception:
                await self._conn.rollback()
                raise

    async def load(self, agent_id: str) -> dict[str, Any] | None:
        """Load one agent's frozen working memory."""
        if not self._conn:
            return None
        async with self._lock:
            cursor = await self._conn.execute(
                "SELECT state_json FROM working_memory WHERE agent_id = ?",
                (agent_id,),
            )
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
        return None

    async def load_all(self) -> dict[str, dict[str, Any]]:
        """Load all agents' frozen working memory (startup path)."""
        if not self._conn:
            return {}
        result: dict[str, dict[str, Any]] = {}
        async with self._lock:
            cursor = await self._conn.execute(
                "SELECT agent_id, state_json FROM working_memory"
            )
            rows = await cursor.fetchall()
            for row in rows:
                try:
                    result[row[0]] = json.loads(row[1])
                except Exception:
                    logger.debug("AD-573: Failed to deserialize WM for %s", row[0])
        return result

    async def clear(self) -> None:
        """Clear all working memory state (used on `probos reset`)."""
        if not self._conn:
            return
        async with self._lock:
            await self._conn.execute("DELETE FROM working_memory")
            await self._conn.commit()
```

#### 7b. Serialization on `AgentWorkingMemory`

Add `to_dict()` and `from_dict()` methods to `AgentWorkingMemory`:

```python
def to_dict(self) -> dict[str, Any]:
    """Serialize working memory state for persistence."""
    return {
        "recent_actions": [
            {"content": e.content, "category": e.category,
             "source_pathway": e.source_pathway, "timestamp": e.timestamp,
             "metadata": e.metadata}
            for e in self._recent_actions
        ],
        "recent_observations": [
            {"content": e.content, "category": e.category,
             "source_pathway": e.source_pathway, "timestamp": e.timestamp,
             "metadata": e.metadata}
            for e in self._recent_observations
        ],
        "recent_conversations": [
            {"content": e.content, "category": e.category,
             "source_pathway": e.source_pathway, "timestamp": e.timestamp,
             "metadata": e.metadata}
            for e in self._recent_conversations
        ],
        "recent_events": [
            {"content": e.content, "category": e.category,
             "source_pathway": e.source_pathway, "timestamp": e.timestamp,
             "metadata": e.metadata}
            for e in self._recent_events
        ],
        "active_engagements": {
            eid: {
                "engagement_type": eng.engagement_type,
                "engagement_id": eng.engagement_id,
                "summary": eng.summary,
                "state": eng.state,
                "started_at": eng.started_at,
                "last_updated": eng.last_updated,
            }
            for eid, eng in self._active_engagements.items()
        },
        "cognitive_state": dict(self._cognitive_state),
    }

@classmethod
def from_dict(
    cls,
    data: dict[str, Any],
    *,
    stale_threshold_seconds: float = 86400.0,  # 24 hours default
) -> AgentWorkingMemory:
    """Restore working memory from persisted state.

    Prunes entries older than stale_threshold_seconds.
    Active engagements are restored but may need revalidation
    against live services (e.g., games that expired during stasis).
    """
    now = time.time()
    wm = cls()

    def _restore_entries(entries: list[dict], target: deque) -> None:
        for raw in entries:
            age = now - raw.get("timestamp", 0)
            if age < stale_threshold_seconds:
                target.append(WorkingMemoryEntry(
                    content=raw["content"],
                    category=raw.get("category", "unknown"),
                    source_pathway=raw.get("source_pathway", "restored"),
                    timestamp=raw.get("timestamp", now),
                    metadata=raw.get("metadata", {}),
                ))

    _restore_entries(data.get("recent_actions", []), wm._recent_actions)
    _restore_entries(data.get("recent_observations", []), wm._recent_observations)
    _restore_entries(data.get("recent_conversations", []), wm._recent_conversations)
    _restore_entries(data.get("recent_events", []), wm._recent_events)

    for eid, eng_data in data.get("active_engagements", {}).items():
        wm._active_engagements[eid] = ActiveEngagement(
            engagement_type=eng_data.get("engagement_type", "unknown"),
            engagement_id=eng_data.get("engagement_id", eid),
            summary=eng_data.get("summary", ""),
            state=eng_data.get("state", {}),
            started_at=eng_data.get("started_at", now),
            last_updated=eng_data.get("last_updated", now),
        )

    wm._cognitive_state = data.get("cognitive_state", {})

    # Add stasis awareness marker
    wm.record_event(
        "Restored from stasis — working memory reloaded",
        source="system",
    )

    return wm
```

#### 7c. Shutdown Integration

**File:** `src/probos/startup/shutdown.py`

Add working memory freeze **before** the KnowledgeStore artifact persistence (line 242), after the 1-second grace period. This ensures all in-flight cognitive cycles have completed recording.

```python
# AD-573: Freeze all agent working memory to disk
wm_store = getattr(runtime, '_wm_store', None)
if wm_store:
    try:
        states: dict[str, dict] = {}
        for agent in runtime.registry.all():
            if hasattr(agent, 'working_memory'):
                states[agent.id] = agent.working_memory.to_dict()
        if states:
            await asyncio.wait_for(wm_store.save_all(states), timeout=5.0)
            logger.info("AD-573: Froze working memory for %d agents", len(states))
    except Exception:
        logger.warning("AD-573: Working memory freeze failed", exc_info=True)
```

#### 7d. Startup Integration

**File:** `src/probos/startup/cognitive_services.py` — Create the store alongside other SQLite-backed services.

1. Create the store (follow TrustNetwork/HebbianRouter pattern — lazy-import `default_factory`):
```python
from probos.cognitive.working_memory_store import WorkingMemoryStore
from probos.storage.sqlite_factory import default_factory

wm_store = WorkingMemoryStore(
    connection_factory=default_factory,
    db_path=str(data_dir / "working_memory.db"),
)
await wm_store.start()
runtime._wm_store = wm_store
```

2. **File:** `src/probos/startup/finalize.py` — After agents are created and registered, restore frozen state. This file handles late-init services wired after all agents exist.

```python
# AD-573: Restore working memory from stasis
if runtime._lifecycle_state == "stasis_recovery":
    wm_store = getattr(runtime, '_wm_store', None)
    if wm_store:
        try:
            frozen_states = await wm_store.load_all()
            stale_hours = runtime.config.working_memory.stale_threshold_hours
            for agent in runtime.registry.all():
                if hasattr(agent, 'working_memory') and agent.id in frozen_states:
                    agent._working_memory = AgentWorkingMemory.from_dict(
                        frozen_states[agent.id],
                        stale_threshold_seconds=stale_hours * 3600,
                    )
            logger.info("AD-573: Restored working memory for %d agents", len(frozen_states))
        except Exception:
            logger.warning("AD-573: Working memory restore failed", exc_info=True)
```

#### 7e. Engagement Revalidation on Restore

Active engagements restored from stasis may reference state that no longer exists (e.g., a game that was active before shutdown but whose RecreationService has been reset). After restoration in `finalize.py`, validate engagements:

```python
# AD-573: Revalidate active engagements against live services
rec_svc = getattr(runtime, 'recreation_service', None)
for agent in runtime.registry.all():
    if not hasattr(agent, 'working_memory'):
        continue
    wm = agent.working_memory
    stale_engagements = []
    for eid, eng in list(wm._active_engagements.items()):
        if eng.engagement_type == "game" and rec_svc:
            # Game engagements: verify game still exists
            game = None
            try:
                active_games = rec_svc.get_active_games()
                game = next((g for g in active_games if g["game_id"] == eid), None)
            except Exception:
                pass
            if not game:
                stale_engagements.append(eid)
    for eid in stale_engagements:
        wm.remove_engagement(eid)
        wm.record_event(f"Game engagement {eid[:8]} ended during stasis", source="system")
```

#### 7f. Reset Integration

**File:** `src/probos/runtime.py` — Reset is handled by the CLI in `__main__.py` (`probos reset` command), not a method on runtime. Add to wherever the reset data cleanup occurs:

```python
# AD-573: Clear working memory on reset
wm_store = getattr(runtime, '_wm_store', None)
if wm_store:
    await wm_store.clear()
```

Alternatively, the `working_memory.db` file will be in `data_dir` and the CLI's data-directory cleanup already handles this. Verify which pattern to follow — if `probos reset -y` deletes the entire data directory, no explicit clear is needed. If it selectively clears, add the above.

### 8. Migration Path from AD-28 `WorkingMemoryManager`

The existing `WorkingMemoryManager` in `cognitive/working_memory.py` is used only by `process_natural_language()` in the NL decomposer. It should NOT be modified or replaced in this AD. It serves a different purpose (ship-level system state for NL parsing) and will be addressed separately.

`AgentWorkingMemory` is a new, separate concern: per-agent cognitive continuity. Different scope, different consumer, different lifecycle.

## Engineering Principles Compliance

- **SOLID (S):** `AgentWorkingMemory` has one responsibility: maintaining the agent's active situation model. `WorkingMemoryEntry` is a pure data container. `ActiveEngagement` handles engagement lifecycle. No god objects.
- **SOLID (O):** New `ActiveEngagement` types can be added (tasks, collaborations) without modifying `AgentWorkingMemory`. The write/read API is type-agnostic.
- **SOLID (D):** No direct imports of concrete services. Write hooks use `hasattr()` guards and catch `Exception`. Working memory depends on nothing outside itself.
- **SOLID (I):** Callers use only the narrow write/read API they need. `proactive.py` calls `record_observation()`, router calls `record_conversation()`, agent calls `record_action()`.
- **Law of Demeter:** Working memory is accessed via `self._working_memory` (1 hop from agent) or `agent.working_memory` property (1 hop from caller). No chain violations.
- **Fail Fast:** All write hooks wrapped in `try/except` → non-critical tier 1 (degrade gracefully). An agent functions normally without working memory — it just lacks cross-pathway awareness. `render_context()` returns empty string on any failure.
- **Defense in Depth:** Ring buffers enforce capacity limits. Token budget enforces context size. Priority eviction ensures critical state (active engagements) survives budget pressure.
- **DRY:** One `render_context()` method serves all pathways. One `record_action()` method serves all post-act hooks. Active engagement lifecycle (add/update/remove) is centralized.
- **Cloud-Ready Storage:** SQLite-backed via `ConnectionFactory` (Section 7). `WorkingMemoryStore` follows the TrustNetwork/HebbianRouter canonical pattern — abstract connection interface enables commercial overlay to swap SQLite → Postgres without changing business logic.

## Files Modified / Created

| File | Change |
|------|--------|
| `src/probos/cognitive/agent_working_memory.py` | **NEW** — `AgentWorkingMemory`, `WorkingMemoryEntry`, `ActiveEngagement` with `to_dict()`/`from_dict()` serialization |
| `src/probos/cognitive/working_memory_store.py` | **NEW** — `WorkingMemoryStore` SQLite persistence (freeze/restore via ConnectionFactory) |
| `src/probos/cognitive/cognitive_agent.py` | Initialize `_working_memory`, inject into all `_build_user_message()` branches, action recording in `handle_intent()`, `_summarize_action()` helper, system prompt augmentation |
| `src/probos/routers/agents.py` | Record DM exchanges to working memory |
| `src/probos/proactive.py` | Record observations, game engagements, cognitive state to working memory; sync active games from `_gather_context()`; supplemental WM injection in proactive context |
| `src/probos/config.py` | `WorkingMemoryConfig` dataclass |
| `src/probos/startup/shutdown.py` | Freeze all agent working memory to disk before KnowledgeStore persistence |
| `src/probos/startup/cognitive_services.py` | Create `WorkingMemoryStore`, wire to runtime; restore frozen state on stasis recovery; revalidate engagements |
| `docs/development/roadmap.md` | AD-573 entry |
| `docs/architecture/memory.md` | Update Layer 2 description to reference AD-573 implementation |

## Tests

### `tests/test_agent_working_memory.py` — new file:

**Core data structures:**
- `test_working_memory_entry_age` — verify `age_seconds()` returns positive value
- `test_working_memory_entry_token_estimate` — verify token estimate proportional to content length
- `test_active_engagement_render` — verify `render()` includes summary and state render

**Write API:**
- `test_record_action` — verify action appended to ring buffer
- `test_record_action_ring_buffer_eviction` — overflow maxlen, oldest evicted
- `test_record_observation` — verify observation appended
- `test_record_conversation` — verify partner metadata stored
- `test_record_event` — verify event appended
- `test_add_engagement` — verify engagement registered by ID
- `test_remove_engagement` — verify engagement removed
- `test_update_engagement` — verify state and summary updated, `last_updated` bumped
- `test_update_engagement_missing` — verify no error on missing ID

**Read API:**
- `test_render_context_empty` — empty working memory returns empty string
- `test_render_context_with_actions` — verify "Recent actions:" section rendered
- `test_render_context_with_engagements` — verify active engagements rendered first (priority 1)
- `test_render_context_budget_eviction` — fill all slots, set low budget, verify low-priority sections evicted while engagements survive
- `test_render_context_format` — verify `--- Working Memory ---` / `--- End Working Memory ---` markers
- `test_has_engagement_by_type` — verify type filtering
- `test_has_engagement_any` — verify returns True when any engagement exists
- `test_get_engagement` — verify retrieval by ID
- `test_get_engagements_by_type` — verify filtering returns correct list

**Integration hooks (mocked):**
- `test_cognitive_agent_has_working_memory` — verify `CognitiveAgent` instance has `_working_memory` attribute
- `test_dm_user_message_includes_working_memory` — mock working memory with content, verify `_build_user_message("direct_message")` includes "Working Memory" section
- `test_proactive_user_message_includes_working_memory` — same for proactive_think
- `test_ward_room_user_message_includes_working_memory` — same for ward_room_notification
- `test_action_recorded_after_act` — mock `handle_intent()`, verify `record_action()` called
- `test_summarize_action_dm` — verify DM summary format
- `test_summarize_action_proactive_no_response` — verify `[NO_RESPONSE]` returns empty string

**Serialization (to_dict / from_dict):**
- `test_to_dict_roundtrip` — populate all fields, `to_dict()` → `from_dict()`, verify content matches
- `test_from_dict_stale_pruning` — entries older than threshold are dropped on restore
- `test_from_dict_fresh_entries_kept` — entries within threshold survive restore
- `test_from_dict_engagements_restored` — active engagements roundtrip correctly
- `test_from_dict_adds_stasis_marker` — verify "Restored from stasis" event added on restore
- `test_from_dict_empty_dict` — gracefully handles empty/minimal input

### `tests/test_working_memory_store.py` — new file:

**Store lifecycle:**
- `test_store_start_creates_schema` — verify table created after `start()`
- `test_store_save_and_load` — save one agent's state, load it back, verify contents
- `test_store_save_all_and_load_all` — batch save 3 agents, load all, verify all 3 present
- `test_store_load_missing_agent` — returns `None` for unknown agent ID
- `test_store_save_overwrites` — save twice for same agent, load returns latest
- `test_store_clear` — save data, clear, verify `load_all()` returns empty dict
- `test_store_no_connection` — all methods are no-ops when `_conn` is None (graceful degradation)

## Verification

1. `pytest tests/test_agent_working_memory.py tests/test_working_memory_store.py -v` — all new tests pass
2. `pytest tests/ -x --timeout=60` — full suite passes (no regressions)
3. Manual: Start ProbOS → trigger proactive cycle → open DM with agent → verify DM context includes "Working Memory" section showing the proactive observation
4. Manual: Have DM conversation → trigger proactive cycle → verify proactive context includes "Working Memory" section showing the DM conversation
5. Manual: Challenge agent to game → DM the agent → verify game appears in working memory context (not just via AD-572 injection)
6. Manual: Verify working memory renders across all three pathways (DM, WR, proactive) with consistent format
7. Manual: `probos shutdown` → verify "Froze working memory for N agents" log → restart → verify "Restored working memory for N agents" log → open DM → verify pre-stasis activity appears in working memory context
8. Manual: `probos reset -y` → verify working memory store cleared → restart → verify clean working memory (no stale state)
