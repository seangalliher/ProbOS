# AD-579a: Pinned Knowledge Buffer

**Status:** Ready for builder
**Depends on:** None
**Issue:** #37

## Problem Statement

Agents lack a small, persistent "critical facts" buffer always loaded into context. Standing orders cover behavioral constraints but not operational knowledge like "the current alert condition is YELLOW" or "Worf is on shore leave." These facts need to survive across cognitive cycles within a session but are not episodic memories — they are pinned assertions about current reality.

Without this, agents must re-derive operational facts from episodic recall or LLM parametric knowledge every cycle, wasting context budget and risking stale information.

## Implementation

### Add PinnedFact Dataclass

File: `src/probos/cognitive/agent_working_memory.py`

Add a new frozen dataclass near the top of the file, after the existing `WorkingMemoryEntry` dataclass:

```python
import uuid
from dataclasses import dataclass, field

@dataclass(frozen=True)
class PinnedFact:
    """A pinned knowledge fact always loaded into agent context."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    fact: str  # human-readable assertion
    source: str  # "agent", "counselor", "dream"
    pinned_at: float  # time.time() epoch
    ttl_seconds: float | None  # None = no expiry
    priority: int = 5  # 1 (highest) to 10 (lowest), for eviction ordering
```

### Add PinnedKnowledgeBuffer Class

File: `src/probos/cognitive/agent_working_memory.py`

Add a new class after `PinnedFact`:

```python
class PinnedKnowledgeBuffer:
    """Small persistent buffer of critical operational facts (AD-579a)."""

    def __init__(self, *, max_tokens: int = 150, max_pins: int = 10, default_ttl_seconds: float = 86400.0) -> None:
        ...

    def pin(self, fact: str, source: str, *, ttl_seconds: float | None = None, priority: int = 5) -> PinnedFact:
        """Add a pinned fact. Returns the created PinnedFact.
        If a fact with identical text already exists, update its timestamp and TTL.
        If at max_pins capacity, evict lowest-priority (highest number) fact via LRU.
        """

    def unpin(self, fact_id: str) -> bool:
        """Remove a pinned fact by ID. Returns True if found and removed."""

    def render_pins(self, budget: int | None = None) -> str:
        """Render all active (non-expired) pins within token budget.
        Format: '[Pinned Knowledge]:\\n  - {fact} [{source}]'
        Ordered by priority (ascending), then pinned_at (ascending).
        Calls _evict_expired() first.
        Uses self._max_tokens as the default budget when no budget parameter is provided.
        """

    def _evict_expired(self) -> int:
        """Remove pins past their TTL. Returns count evicted."""

    @property
    def pins(self) -> list[PinnedFact]:
        """Read-only snapshot of current pins (after eviction)."""

    def __len__(self) -> int:
        """Number of active pins (after eviction)."""
```

Storage: internal `list[PinnedFact]`. Token estimation: `len(fact) // CHARS_PER_TOKEN` (reuse existing `CHARS_PER_TOKEN = 4` constant).

Three pin sources are accepted via the `source` parameter string:
- `"agent"` — agent self-pins during cognitive processing
- `"counselor"` — Counselor pins via event handler (future wiring)
- `"dream"` — dream consolidation auto-pins high-importance recurring facts (future wiring)

LRU eviction when over `max_pins`: evict the fact with the highest priority number (lowest priority), breaking ties by oldest `pinned_at`.

### Add PinnedKnowledgeConfig

File: `src/probos/config.py`

Add after `MetabolismConfig`:

```python
class PinnedKnowledgeConfig(BaseModel):
    """AD-579a: Pinned knowledge buffer configuration."""
    enabled: bool = True
    max_tokens: int = 150
    max_pins: int = 10
    default_ttl_seconds: float = 86400.0  # 24 hours
```

### Wire into AgentWorkingMemory Constructor

File: `src/probos/cognitive/agent_working_memory.py`

Modify `AgentWorkingMemory.__init__()` (currently at line 150):
- Add optional parameter: `pinned_config: PinnedKnowledgeConfig | None = None`
- When `pinned_config` is not None and `pinned_config.enabled` is True, create a `PinnedKnowledgeBuffer` instance stored as `self._pinned_knowledge`.
- When None or disabled, `self._pinned_knowledge = None`.
- Use `TYPE_CHECKING` guard for the config import.

### Wire into render_context()

File: `src/probos/cognitive/agent_working_memory.py`

Modify `render_context()` (currently at line 501). Insert a new Priority 0 section (before existing Priority 1 engagements):

```python
# Priority 0 (highest): Pinned knowledge — always include first
if self._pinned_knowledge is not None:
    pin_text = self._pinned_knowledge.render_pins()
    if pin_text:
        sections.append((0, pin_text))
```

### Add Events

File: `src/probos/events.py`

Add to the `EventType` enum, in a new comment section after the existing knowledge-related events (after `KNOWLEDGE_TIER_LOADED`):

```python
# Pinned knowledge (AD-579a)
KNOWLEDGE_PINNED = "knowledge_pinned"
KNOWLEDGE_UNPINNED = "knowledge_unpinned"
```

### Expose Public API on AgentWorkingMemory

File: `src/probos/cognitive/agent_working_memory.py`

Add three delegate methods to `AgentWorkingMemory`:

```python
def pin_knowledge(self, fact: str, source: str, *, ttl_seconds: float | None = None, priority: int = 5) -> PinnedFact | None:
    """AD-579a: Pin a knowledge fact. Returns PinnedFact or None if disabled."""

def unpin_knowledge(self, fact_id: str) -> bool:
    """AD-579a: Unpin a knowledge fact by ID. Returns True if removed."""

@property
def pinned_knowledge(self) -> list[PinnedFact]:
    """AD-579a: Read-only snapshot of pinned facts."""
```

## Acceptance Criteria

1. `PinnedKnowledgeBuffer` stores, retrieves, and renders pinned facts within token budget.
2. TTL expiry automatically removes stale pins on access.
3. LRU eviction removes lowest-priority pins when at capacity.
4. Duplicate fact text updates existing pin instead of creating a new one.
5. `render_context()` includes pinned knowledge as highest-priority section.
6. `PinnedKnowledgeConfig` with Pydantic validation and sensible defaults.
7. `KNOWLEDGE_PINNED` and `KNOWLEDGE_UNPINNED` events added to `EventType`.
8. When config is disabled or not provided, all pinned knowledge code is inert (no-op).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Test Plan

File: `tests/test_ad579a_pinned_knowledge.py`

12 tests:

| # | Test Name | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_pin_fact_stores_and_retrieves` | `pin()` creates a `PinnedFact`, accessible via `.pins` |
| 2 | `test_unpin_fact_removes` | `unpin()` removes by ID, returns True; unknown ID returns False |
| 3 | `test_ttl_expiry_evicts_stale_pins` | After TTL elapses, `_evict_expired()` removes the pin |
| 4 | `test_lru_eviction_at_max_pins` | When at `max_pins`, new pin evicts lowest-priority oldest |
| 5 | `test_render_within_budget` | `render_pins()` respects token budget, omits overflow |
| 6 | `test_duplicate_pin_updates_existing` | Pinning identical fact text updates timestamp/TTL, not duplicates |
| 7 | `test_max_pins_limit_enforced` | Cannot exceed `max_pins` count |
| 8 | `test_priority_ordering_in_render` | Higher priority (lower number) pins render first |
| 9 | `test_counselor_pin_source` | `source="counselor"` is accepted and stored correctly |
| 10 | `test_dream_auto_pin_source` | `source="dream"` is accepted and stored correctly |
| 11 | `test_disabled_config_is_noop` | When `enabled=False`, `pin_knowledge()` returns None, `render_context()` has no pin section |
| 12 | `test_render_context_includes_pins` | Full `AgentWorkingMemory.render_context()` includes pinned section at priority 0 |

Use `time.time()` monkeypatching (or small TTL values with `time.sleep()`) for TTL tests. Use `_Fake*` stubs, not mocks.

Run targeted: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad579a_pinned_knowledge.py -v`

## Do Not Build

- No LLM-based pin suggestion or auto-detection of what to pin.
- No cross-agent pin sharing or broadcasting.
- No persistence to SQLite — pins are ephemeral per session (die on restart).
- No HXI API endpoints for pin management.
- No event emission wiring (events are defined but not emitted — future AD wires them).
- No Counselor or dream auto-pinning logic (just accept the `source` string).

## Tracker Updates

- `PROGRESS.md`: Add `AD-579a Pinned Knowledge Buffer — CLOSED` under Memory Architecture
- `DECISIONS.md`: Add entry: "AD-579a: Added PinnedKnowledgeBuffer to AgentWorkingMemory — small (150 token default) persistent facts buffer rendered at priority 0 in context. Ephemeral per session, no SQLite persistence. Three sources: agent, counselor, dream."
- `docs/development/roadmap.md`: Update AD-579a row to COMPLETE
- Issue: #37
