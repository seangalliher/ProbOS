# AD-671: Dream-Working Memory Integration — Bidirectional Bridge

**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-573 (AgentWorkingMemory — complete), AD-599 (Reflection Episode Promotion — complete)
**Files:** `src/probos/cognitive/dream_wm_bridge.py` (NEW), `src/probos/cognitive/dreaming.py` (EDIT), `src/probos/startup/dreaming.py` (EDIT), `src/probos/config.py` (EDIT), `src/probos/types.py` (EDIT — DreamReport), `tests/test_ad671_dream_wm_integration.py` (NEW)

## Problem

Working memory (AgentWorkingMemory, AD-573) and dream consolidation (DreamingEngine) operate in isolation. When a dream cycle begins, the agent's active WM context — what it was tracking, which topics it engaged with, what conversations it was following — is silently discarded. The dream cycle has no signal about what the agent was cognitively focused on. After the dream cycle completes, the agent wakes up with a blank WM, having no priming about what it learned overnight.

AD-671 creates a bidirectional bridge:
- **Pre-dream flush:** Snapshot WM state into a session summary episode before dream consolidation, so the dream cycle has prioritization signal.
- **Post-dream seed:** Extract dream insights and seed them into WM as priming entries, so the agent starts its next session with continuity.

**What this does NOT include:**
- Modifying any existing dream step behavior (Steps 0–15 are unchanged)
- Changing WM eviction or decay logic (that is AD-670)
- LLM-based summarization (summaries are mechanical aggregation, no LLM calls)
- Named buffer support (that is AD-667; this AD uses the existing category-based buffers)

---

## Section 1: DreamWMConfig

**File:** `src/probos/config.py` (EDIT)

Add a new config model for the dream-WM bridge. Place it after the `DreamingConfig` class.

```python
class DreamWMConfig(BaseModel):
    """AD-671: Dream-Working Memory bridge configuration."""

    enabled: bool = True
    max_priming_entries: int = 3        # Max WM entries seeded after a dream
    flush_min_entries: int = 5          # Don't flush if WM has fewer than this many entries
    priming_category: str = "observation"  # WM category for priming entries
```

Then add a `dream_wm` field to `SystemConfig`:

```python
dream_wm: DreamWMConfig = DreamWMConfig()
```

Place the field near the other cognitive config fields (near `dreaming`, `emergence_metrics`, etc.).

---

## Section 2: DreamReport Extension

**File:** `src/probos/types.py` (EDIT)

Add WM bridge tracking fields to `DreamReport`. Find the `DreamReport` dataclass and add after the `reflections_created` field (currently the last field, line ~535):

```python
    # AD-671: Dream-Working Memory bridge
    wm_entries_flushed: int = 0       # Entries captured in pre-dream flush
    wm_priming_entries: int = 0       # Entries seeded into WM post-dream
```

---

## Section 3: DreamWorkingMemoryBridge

**File:** `src/probos/cognitive/dream_wm_bridge.py` (NEW, ~130 lines)

Create the bridge class. This is a pure-logic module with no IO, no async, no LLM calls.

```python
"""AD-671: Dream-Working Memory Bridge.

Bidirectional pipeline between AgentWorkingMemory and the dream cycle.
Pre-dream: flush WM state to episodic memory as a session summary.
Post-dream: seed WM with priming entries from dream insights.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Any

from probos.cognitive.agent_working_memory import (
    AgentWorkingMemory,
    WorkingMemoryEntry,
)
from probos.config import DreamWMConfig
from probos.types import AnchorFrame, DreamReport, Episode, MemorySource

logger = logging.getLogger(__name__)
```

### Class: DreamWorkingMemoryBridge

Constructor takes `DreamWMConfig`. No other dependencies.

```python
class DreamWorkingMemoryBridge:
    """Bidirectional bridge between working memory and dream consolidation."""

    def __init__(self, config: DreamWMConfig) -> None:
        self._config = config
```

### Method: pre_dream_flush

```python
    def pre_dream_flush(
        self,
        wm: AgentWorkingMemory,
        agent_id: str,
    ) -> dict[str, Any]:
```

This method:

1. Collect all WM entries by reading the internal deques. Use the public `to_dict()` method on `AgentWorkingMemory` to snapshot the state without reaching into private attributes.
2. Count total entries across all buffers (actions + observations + conversations + events + reasoning).
3. If total entries < `flush_min_entries`, return `{"flushed": False, "entry_count": total, "reason": "below_threshold"}` and do nothing.
4. Build a session summary dict containing:
   - `entry_count`: total entries across all buffers
   - `buffer_counts`: dict mapping buffer name to count (e.g. `{"recent_actions": 3, "recent_observations": 2, ...}`)
   - `active_engagements`: list of engagement summaries (from `to_dict()["active_engagements"]`)
   - `top_sources`: Counter of `source_pathway` values across all entries, `.most_common(5)`
   - `top_categories`: Counter of `category` values across all entries, `.most_common(5)`
   - `cognitive_state`: from `to_dict()["cognitive_state"]`
5. Build an `Episode` for the session summary:
   - `timestamp`: `time.time()`
   - `user_input`: `"[WM Session Summary]"`
   - `dag_summary`: the session summary dict from step 4
   - `agent_ids`: `[agent_id]`
   - `source`: `MemorySource.REFLECTION`
   - `anchors`: `AnchorFrame(trigger_type="dream_wm_flush", channel="working_memory")`
   - `importance`: `3` (low importance — this is operational metadata, not a significant event)
6. Return `{"flushed": True, "entry_count": total, "episode": episode}`.

Important: this method does NOT call `episodic_memory.store()` — it returns the episode. The caller (dreaming.py) stores it, keeping IO in the async layer.

### Method: post_dream_seed

```python
    def post_dream_seed(
        self,
        wm: AgentWorkingMemory,
        dream_report: DreamReport,
        dream_cycle_id: str,
    ) -> int:
```

This method:

1. Collect insights from the `DreamReport`. An "insight" is any non-trivial result. Build a list of insight strings by checking these fields in order:
   - If `dream_report.procedures_extracted > 0`: `"Learned {n} new procedures from experience patterns"`
   - If `dream_report.procedures_evolved > 0`: `"Evolved {n} procedures based on performance feedback"`
   - If `dream_report.gaps_classified > 0`: `"Identified {n} capability gaps for development"`
   - If `dream_report.emergence_capacity is not None`: `"Crew emergence capacity: {value:.2f}"`
   - If `dream_report.notebook_consolidations > 0`: `"Consolidated {n} notebook entries from recent analysis"`
   - If `dream_report.reflections_created > 0`: `"Created {n} reflection episodes from dream insights"`
   - If `dream_report.activation_pruned > 0`: `"Pruned {n} low-activation memories"`
   - If `dream_report.contradictions_found > 0`: `"Detected {n} memory contradictions for review"`
2. If no insights were generated, return 0.
3. Truncate to `max_priming_entries`.
4. For each insight string, call `wm.record_observation()` with:
   - `summary`: `f"Dream insight: {insight}"`
   - `source`: `"dream_consolidation"`
   - `metadata`: `{"source": "dream_consolidation", "dream_cycle_id": dream_cycle_id}`
   - `knowledge_source`: `"procedural"`
5. Log at INFO: `"AD-671: Seeded %d priming entries into WM for agent %s"` (count, agent_id — but agent_id is not passed to this method, so log without it).
6. Return the number of entries seeded.

Note: uses `record_observation()` because the `priming_category` config defaults to `"observation"`. If in the future we need configurable categories, we can switch to the appropriate `record_*` method. For now, observations are the right semantic bucket — these are things the agent should be aware of, not actions it took.

---

## Section 4: DreamingEngine Integration

**File:** `src/probos/cognitive/dreaming.py` (EDIT)

### 4a: Constructor parameter

Add an optional `dream_wm_bridge` parameter to `DreamingEngine.__init__()`. Place it after the `counselor` parameter (currently the last one, line ~79):

```python
        dream_wm_bridge: Any = None,  # AD-671: working memory bridge
```

Store it:

```python
        self._dream_wm_bridge = dream_wm_bridge  # AD-671
```

### 4b: Pre-dream flush (before Step 0)

In `dream_cycle()`, insert BEFORE the existing `# Step 0: Flush un-consolidated episodes` comment (line ~222). Add:

```python
        # AD-671: Pre-dream WM flush — capture session state before consolidation
        wm_entries_flushed = 0
        if self._dream_wm_bridge:
            try:
                flush_result = self._dream_wm_bridge.pre_dream_flush(
                    wm=getattr(self, '_agent_wm', None),
                    agent_id=self._agent_id,
                )
                if flush_result.get("flushed") and flush_result.get("episode"):
                    await self.episodic_memory.store(flush_result["episode"])
                    wm_entries_flushed = flush_result.get("entry_count", 0)
                    logger.debug(
                        "AD-671: Pre-dream WM flush stored %d entries as session summary",
                        wm_entries_flushed,
                    )
            except Exception:
                logger.debug("AD-671: Pre-dream WM flush failed (non-fatal)", exc_info=True)
```

Note: `self._agent_wm` will be set via a setter (see Section 4d). If it is `None`, `pre_dream_flush` receives `None` and should handle that gracefully — add a guard at the top of `pre_dream_flush`: if `wm is None`, return `{"flushed": False, "entry_count": 0, "reason": "no_wm"}`.

### 4c: Post-dream seed (after Step 15, before report construction)

Insert AFTER the Step 15 try/except block (after line ~1214) and BEFORE `duration_ms = (time.monotonic() - t_start) * 1000` (line ~1216). Add:

```python
        # AD-671: Post-dream WM seed — prime next session with dream insights
        wm_priming_entries = 0
        if self._dream_wm_bridge and getattr(self, '_agent_wm', None):
            try:
                # Build a cycle ID from agent_id + timestamp for traceability
                _cycle_id = f"{self._agent_id}_{int(time.time())}"
                # We need to construct a partial DreamReport for seeding.
                # Use a temporary report with fields populated so far.
                _partial_report = DreamReport(
                    procedures_extracted=procedures_extracted,
                    procedures_evolved=procedures_evolved,
                    gaps_classified=gaps_classified,
                    emergence_capacity=emergence_capacity,
                    notebook_consolidations=notebook_consolidations,
                    reflections_created=reflections_created,
                    activation_pruned=activation_pruned,
                    contradictions_found=contradictions_found,
                )
                wm_priming_entries = self._dream_wm_bridge.post_dream_seed(
                    wm=self._agent_wm,
                    dream_report=_partial_report,
                    dream_cycle_id=_cycle_id,
                )
            except Exception:
                logger.debug("AD-671: Post-dream WM seed failed (non-fatal)", exc_info=True)
```

### 4d: WM setter

Add a setter method on `DreamingEngine` for late-binding the agent's WM reference. Place after `set_ward_room()` (line ~111):

```python
    def set_agent_wm(self, wm: Any) -> None:
        """AD-671: Late-bind agent working memory for dream-WM bridge."""
        self._agent_wm = wm
```

### 4e: DreamReport construction update

In the `DreamReport(...)` constructor call (line ~1218), add the new fields. Place after `reflections_created=reflections_created,`:

```python
            # AD-671: Dream-WM bridge
            wm_entries_flushed=wm_entries_flushed,
            wm_priming_entries=wm_priming_entries,
```

### 4f: Log message update

In the `logger.info("dream-cycle: ...")` call (line ~1281), add `wm_flushed=%d wm_primed=%d` to the format string and `wm_entries_flushed, wm_priming_entries` to the args. Place them at the end.

---

## Section 5: Startup Wiring

**File:** `src/probos/startup/dreaming.py` (EDIT)

### 5a: Import

Add import at the top of the file (after the existing imports, before the `if TYPE_CHECKING:` block):

```python
from probos.cognitive.dream_wm_bridge import DreamWorkingMemoryBridge
```

### 5b: Create bridge and pass to DreamingEngine

In `init_dreaming()`, after `behavioral_metrics_engine` is created (line ~75) and before the `if episodic_memory:` block (line ~95), add:

```python
    # AD-671: Dream-Working Memory bridge
    dream_wm_bridge = None
    if config.dream_wm.enabled:
        dream_wm_bridge = DreamWorkingMemoryBridge(config=config.dream_wm)
```

Then add `dream_wm_bridge` to the `DreamingEngine(...)` constructor call. Add after `records_store=records_store,` (line ~117):

```python
            dream_wm_bridge=dream_wm_bridge,
```

---

## Section 6: Tests

**File:** `tests/test_ad671_dream_wm_integration.py` (NEW)

Use `pytest` + `pytest-asyncio`. Use `_Fake*` stubs, not complex mocks.

### Fixtures

```python
import time
import pytest
from probos.cognitive.agent_working_memory import AgentWorkingMemory
from probos.cognitive.dream_wm_bridge import DreamWorkingMemoryBridge
from probos.config import DreamWMConfig
from probos.types import DreamReport
```

Create a helper that populates a WM with N entries:

```python
def _populated_wm(n: int = 10) -> AgentWorkingMemory:
    wm = AgentWorkingMemory()
    for i in range(n):
        wm.record_action(f"action-{i}", source="test")
    return wm
```

### Test: pre_dream_flush happy path

- Create WM with 10 entries.
- Call `pre_dream_flush(wm, agent_id="test-agent")`.
- Assert `result["flushed"] is True`.
- Assert `result["entry_count"] == 10`.
- Assert `result["episode"]` is an `Episode` instance.
- Assert `result["episode"].source == "reflection"`.
- Assert `result["episode"].anchors.trigger_type == "dream_wm_flush"`.
- Assert `result["episode"].user_input == "[WM Session Summary]"`.

### Test: pre_dream_flush below threshold

- Create WM with 3 entries (below default `flush_min_entries=5`).
- Call `pre_dream_flush`.
- Assert `result["flushed"] is False`.
- Assert `"reason"` is `"below_threshold"`.
- Assert no `"episode"` key in result (or it is absent).

### Test: pre_dream_flush with None WM

- Call `pre_dream_flush(wm=None, agent_id="test")`.
- Assert `result["flushed"] is False`.
- Assert `result["reason"] == "no_wm"`.

### Test: pre_dream_flush empty WM

- Create fresh `AgentWorkingMemory()` (0 entries).
- Call `pre_dream_flush`.
- Assert `result["flushed"] is False`.

### Test: pre_dream_flush session summary content

- Create WM, record 3 actions (source="proactive") and 2 observations (source="ward_room").
- `flush_min_entries=1` in config so it flushes.
- Assert `result["episode"].dag_summary["buffer_counts"]["recent_actions"] == 3`.
- Assert `result["episode"].dag_summary["buffer_counts"]["recent_observations"] == 2`.
- Assert `("proactive", 3)` is in `result["episode"].dag_summary["top_sources"]`.

### Test: post_dream_seed happy path

- Create empty WM.
- Create `DreamReport` with `procedures_extracted=2, gaps_classified=1`.
- Call `post_dream_seed(wm, dream_report, dream_cycle_id="cycle-1")`.
- Assert returns 2 (two insights: procedures + gaps).
- Verify WM now has 2 observation entries via `wm.to_dict()["recent_observations"]`.
- Verify first entry content starts with `"Dream insight:"`.
- Verify metadata contains `"dream_cycle_id": "cycle-1"`.

### Test: post_dream_seed respects max_priming_entries

- Create `DreamWMConfig(max_priming_entries=2)`.
- Create `DreamReport` with all insight fields populated (procedures_extracted=1, procedures_evolved=1, gaps_classified=1, emergence_capacity=0.8, notebook_consolidations=1).
- Call `post_dream_seed`.
- Assert returns exactly 2 (truncated).

### Test: post_dream_seed no insights

- Create `DreamReport()` with all defaults (zeros/None).
- Call `post_dream_seed`.
- Assert returns 0.
- Assert WM observations are empty.

### Test: post_dream_seed knowledge source is procedural

- Create `DreamReport(procedures_extracted=1)`.
- Call `post_dream_seed`.
- Check `wm.to_dict()["recent_observations"][0]["knowledge_source"] == "procedural"`.

### Test: config defaults

- Create `DreamWMConfig()`.
- Assert `enabled is True`.
- Assert `max_priming_entries == 3`.
- Assert `flush_min_entries == 5`.

### Test: config in SystemConfig

- Import `SystemConfig` and instantiate with defaults.
- Assert `config.dream_wm.enabled is True`.
- Assert `isinstance(config.dream_wm, DreamWMConfig)`.

### Test: DreamReport has new fields

- Create `DreamReport(wm_entries_flushed=5, wm_priming_entries=2)`.
- Assert `report.wm_entries_flushed == 5`.
- Assert `report.wm_priming_entries == 2`.

### Test: DreamingEngine accepts bridge parameter

```python
@pytest.mark.asyncio
async def test_dreaming_engine_accepts_bridge():
    """DreamingEngine constructor accepts dream_wm_bridge without error."""
    from probos.cognitive.dreaming import DreamingEngine
    from probos.config import DreamingConfig
    # Minimal construction — most params are optional/None-safe
    engine = DreamingEngine(
        router=None,
        trust_network=None,
        episodic_memory=None,
        config=DreamingConfig(),
        dream_wm_bridge="sentinel",
    )
    assert engine._dream_wm_bridge == "sentinel"
```

---

## Targeted Test Commands

After each section, run:

```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad671_dream_wm_integration.py -v
```

After all sections complete, run full suite:

```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

After all tests pass:

1. **PROGRESS.md** — Add entry: `AD-671 | Dream-Working Memory Integration | CLOSED`
2. **docs/development/roadmap.md** — Update the AD-671 row status to COMPLETE
3. **DECISIONS.md** — Add entry:
   - **AD-671**: Dream-Working Memory Integration. DreamWorkingMemoryBridge provides bidirectional pipeline: pre-dream WM flush stores session summary episode; post-dream seed primes WM with dream insights. Bridge is optional (getattr guard). No LLM calls. ~130 lines new code.
