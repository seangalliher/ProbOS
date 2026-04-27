# AD-651: Standing Order Decomposition

**Status:** Ready for builder
**Priority:** Medium
**Depends:** None (EventType registry already exists)
**Unlocks:** Improved token efficiency across all cognitive chain steps

## Files

| File | Action | Est. Lines |
|------|--------|-----------|
| `src/probos/cognitive/step_instruction_router.py` | **Create** | ~200 |
| `src/probos/cognitive/standing_orders.py` | Modify | ~40 |
| `src/probos/config.py` | Modify | ~20 |
| `src/probos/cognitive/sub_tasks/analyze.py` | Modify | ~15 |
| `src/probos/cognitive/sub_tasks/compose.py` | Modify | ~15 |
| `config/standing_orders/ship.md` | Modify | ~20 |
| `config/standing_orders/federation.md` | Modify | ~20 |
| `src/probos/startup/finalize.py` | Modify | ~10 |
| `tests/test_ad651_step_instruction_router.py` | **Create** | ~350 |

## Problem

Standing orders are composed as a monolithic block via `compose_instructions()` in `standing_orders.py` (line 286) and injected wholesale into every cognitive chain step. The analyze handler (`sub_tasks/analyze.py`, line 58), compose handler (`sub_tasks/compose.py`, line 77), and every other handler all call `compose_instructions()` with identical arguments and receive the same ~2000-token wall of instructions. This is wasteful and dilutes the instructions relevant to each step.

The analyze step does not need communication style guidance. The compose step does not need observation assessment criteria. The evaluate step does not need self-monitoring instructions. Each step should receive only the standing order sections relevant to its role.

## Scope

**In scope:**
- `StepInstructionRouter` class that slices composed standing orders by step relevance
- Category markers (`<!-- category: name -->`) in standing order markdown files
- Step-to-category mapping configuration
- Per-step instruction extraction from the full composed text
- Token savings logging for observability
- `StepInstructionConfig` in config.py
- Backward-compatible fallback when no category markers exist

**Out of scope:**
- Changing standing order content (beyond adding `<!-- category -->` markers)
- Modifying `billet_registry.py` or the billet template resolution system
- Changing the 7-tier hierarchy in `compose_instructions()`
- Adding API endpoints
- Changing the chain flow or sub-task protocol

### Design Principles

- **Backward compatible:** If no `<!-- category: ... -->` markers exist in standing order files, the router returns the full monolithic text for every step. Identical behavior to today.
- **Constructor injection:** `StepInstructionRouter` receives its config via constructor, not global lookup.
- **DRY:** The router consumes the output of `compose_instructions()` (line 286). It does NOT re-implement the 7-tier hierarchy. `compose_instructions()` produces the full text; the router slices it.
- **SRP:** `StepInstructionRouter` does instruction routing only. It does not compose instructions, manage caches, or interact with the LLM.
- **Open/Closed:** New step-to-category mappings are added via config, not code changes.

---

## Section 1: StepInstructionConfig

Add to `src/probos/config.py`, after `ChainTuningConfig` (around line 310).

```python
class StepInstructionConfig(BaseModel):
    """AD-651: Step-specific standing order decomposition."""

    enabled: bool = False  # Disabled by default — opt-in after validation

    # Step-to-category mappings. Keys are chain step names (matching SubTaskType values),
    # values are lists of category tags that the step should receive.
    step_categories: dict[str, list[str]] = {
        "query": [],  # Query is deterministic, no LLM — receives no instructions
        "analyze": [
            "observation_guidelines",
            "situation_assessment",
            "when_to_act_vs_observe",
            "memory_anchoring",
            "source_attribution",
            "self_monitoring",
        ],
        "compose": [
            "communication_style",
            "personality_expression",
            "audience_awareness",
            "ward_room_actions",
            "knowledge_capture",
            "duty_reporting",
        ],
        "evaluate": [
            "self_monitoring",
            "scope_discipline",
            "communication_style",
        ],
        "reflect": [
            "self_monitoring",
            "scope_discipline",
            "knowledge_capture",
        ],
    }

    # Categories that every LLM-calling step receives regardless of mapping.
    # These are foundational and should never be excluded.
    universal_categories: list[str] = [
        "identity",
        "chain_of_command",
        "core_directives",
        "encoding_safety",
    ]

    # If True, log token savings per step at DEBUG level.
    log_token_savings: bool = True
```

Wire into `SystemConfig` (around line 1152):

```python
    step_instruction: StepInstructionConfig = StepInstructionConfig()  # AD-651
```

## Section 2: Category Markers in Standing Orders

Add `<!-- category: name -->` markers to the standing order markdown files. These markers are HTML comments and invisible when rendered. Each marker applies to all content from its position until the next `<!-- category: -->` marker or the next `##` heading (whichever comes first).

### `config/standing_orders/federation.md` markers

Add markers before the following sections (exact placements):

- Before `## Authentic Identity` (line 7): `<!-- category: identity -->`
- Before `## Crew Survival Guide` (line 39): `<!-- category: identity -->`
- Before `### Chain of Command` (line 49): `<!-- category: chain_of_command -->`
- Before `### Trust and Rank` (line 59): `<!-- category: chain_of_command -->`
- Before `### Constraint Awareness Principle` (line 72): `<!-- category: observation_guidelines -->`
- Before `### Duties` (line 82): `<!-- category: duty_reporting -->`
- Before `### Memory` (line 88): `<!-- category: memory_anchoring -->`
- Before `### Dreams` (line 97): `<!-- category: memory_anchoring -->`
- Before `### Working with Other Crew` (line 105): `<!-- category: audience_awareness -->`
- Before `### Leadership and Mentorship` (line 113): `<!-- category: audience_awareness -->`
- Before `### When Things Go Wrong` (line 128): `<!-- category: situation_assessment -->`
- Before `## Core Directives` (line 131): `<!-- category: core_directives -->`
- Before `## Knowledge Source Attribution` (line 140): `<!-- category: source_attribution -->`
- Before `## Memory Reliability Hierarchy` (line 155): `<!-- category: source_attribution -->`
- Before `## Memory Anchoring Protocol` (line 168): `<!-- category: memory_anchoring -->`
- Before `## Layer Architecture` (line 214): `<!-- category: core_directives -->`
- Before `## Encoding Safety` (line 222): `<!-- category: encoding_safety -->`
- Before `## Communications` (line 228): `<!-- category: communication_style -->`
- Before `## Agent Classification` (line 305): `<!-- category: identity -->`

### `config/standing_orders/ship.md` markers

Add markers before the following sections:

- Before `## Import Conventions` (line 3): `<!-- category: core_directives -->`
- Before `## Testing Standards` (line 9): `<!-- category: core_directives -->`
- Before `## Code Patterns` (line 19): `<!-- category: core_directives -->`
- Before `## Startup Sequence` (line 30): `<!-- category: situation_assessment -->`
- Before `## Ship's Records` (line 45): `<!-- category: knowledge_capture -->`
- Before `## Monitoring & Telemetry` (line 75): `<!-- category: situation_assessment -->`
- Before `## Ward Room Communication` (line 89): `<!-- category: communication_style -->`
- Before `### Ward Room Action Vocabulary` (line 108): `<!-- category: ward_room_actions -->`
- Before `**When to act vs. observe:**` (line 160): `<!-- category: when_to_act_vs_observe -->`
- Before `## Knowledge Capture` (line 167): `<!-- category: knowledge_capture -->`
- Before `## Scope Discipline` (line 183): `<!-- category: scope_discipline -->`
- Before `## Self-Monitoring` (line 189): `<!-- category: self_monitoring -->`
- Before `## Cognitive Zones` (line 200): `<!-- category: self_monitoring -->`
- Before `## Source Attribution in Practice` (line 215): `<!-- category: source_attribution -->`
- Before `## Duty Reporting Expectations` (line 225): `<!-- category: duty_reporting -->`

**Important:** Place each `<!-- category: name -->` marker on its own line immediately BEFORE the heading it categorizes. Do not modify any existing content. Do not remove or change any existing text. Only insert marker lines.

## Section 3: StepInstructionRouter

Create `src/probos/cognitive/step_instruction_router.py`.

```python
"""AD-651: Step-specific standing order instruction routing.

Decomposes monolithic standing orders into step-relevant slices.
Each cognitive chain step (analyze, compose, reflect, etc.) receives
only the instruction categories relevant to its role.

Backward compatible: returns full text when no category markers exist.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import StepInstructionConfig

logger = logging.getLogger(__name__)

# Pattern matches: <!-- category: name --> or <!-- category: name1, name2 -->
_CATEGORY_MARKER_RE = re.compile(
    r"<!--\s*category:\s*([\w,\s]+?)\s*-->",
    re.IGNORECASE,
)


class StepInstructionRouter:
    """Routes composed standing orders to chain steps by category relevance.

    Consumes the full output of compose_instructions() and extracts
    category-tagged sections. Each chain step name maps to a set of
    categories via config; the router returns only matching sections.

    Parameters
    ----------
    config : StepInstructionConfig
        Step-to-category mappings and universal categories.
    """

    def __init__(self, config: "StepInstructionConfig") -> None:
        self._config = config
        self._step_categories: dict[str, frozenset[str]] = {}
        self._universal: frozenset[str] = frozenset(config.universal_categories)
        for step, cats in config.step_categories.items():
            self._step_categories[step] = frozenset(cats) | self._universal

    def route(self, full_instructions: str, step_name: str) -> str:
        """Extract step-relevant instructions from the full composed text.

        Parameters
        ----------
        full_instructions : str
            The complete output of compose_instructions().
        step_name : str
            The chain step name (e.g., "analyze", "compose", "reflect").

        Returns
        -------
        str
            The filtered instructions containing only categories relevant
            to the given step. Returns full_instructions unchanged if:
            - The feature is disabled
            - No category markers are found in the text
            - The step_name is not in the config
        """
        if not self._config.enabled:
            return full_instructions

        # Parse category-tagged sections
        sections = self._parse_sections(full_instructions)

        if not sections:
            # No markers found — backward-compatible fallback
            logger.debug(
                "AD-651: No category markers found, returning full instructions for step '%s'",
                step_name,
            )
            return full_instructions

        # Resolve target categories for this step
        target_cats = self._step_categories.get(step_name)
        if target_cats is None:
            # Unknown step — return full instructions
            logger.debug(
                "AD-651: Unknown step '%s', returning full instructions",
                step_name,
            )
            return full_instructions

        # Filter sections by category membership
        matched_parts: list[str] = []
        untagged_parts: list[str] = []

        for categories, text in sections:
            if not categories:
                # Untagged content (e.g., hardcoded instructions, personality block)
                # Always included — these are tier 1/1.5 content without markers
                untagged_parts.append(text)
            elif categories & target_cats:
                matched_parts.append(text)

        # Compose result: untagged (always) + matched tagged sections
        result_parts = untagged_parts + matched_parts
        result = "\n\n---\n\n".join(part for part in result_parts if part.strip())

        if self._config.log_token_savings:
            full_len = len(full_instructions)
            result_len = len(result)
            savings_pct = ((full_len - result_len) / full_len * 100) if full_len > 0 else 0
            logger.debug(
                "AD-651: step='%s' full=%d chars, filtered=%d chars, savings=%.1f%%",
                step_name, full_len, result_len, savings_pct,
            )

        return result

    def _parse_sections(
        self, text: str,
    ) -> list[tuple[frozenset[str], str]]:
        """Parse text into (categories, content) pairs.

        Sections are delimited by:
        - ``<!-- category: name -->`` markers
        - ``---`` separators (from compose_instructions tier joins)

        Content before any category marker is returned with an empty
        frozenset (untagged). A marker's categories apply to all content
        until the next marker or ``---`` separator.

        Returns
        -------
        list[tuple[frozenset[str], str]]
            Each element is (category_set, section_text). category_set is
            empty for untagged sections.
        """
        sections: list[tuple[frozenset[str], str]] = []
        # Split on --- separators first (these come from compose_instructions)
        tier_blocks = re.split(r"\n---\n", text)

        for block in tier_blocks:
            if not block.strip():
                continue
            # Find all category markers in this block
            markers = list(_CATEGORY_MARKER_RE.finditer(block))

            if not markers:
                # No markers in this block — untagged
                sections.append((frozenset(), block.strip()))
                continue

            # Content before first marker is untagged
            pre_marker = block[:markers[0].start()].strip()
            if pre_marker:
                sections.append((frozenset(), pre_marker))

            # Process each marker and its content
            for i, match in enumerate(markers):
                # Parse comma-separated category names
                raw_cats = match.group(1)
                cats = frozenset(
                    c.strip().lower() for c in raw_cats.split(",") if c.strip()
                )

                # Content runs from after this marker to start of next marker
                # (or end of block)
                content_start = match.end()
                if i + 1 < len(markers):
                    content_end = markers[i + 1].start()
                else:
                    content_end = len(block)

                content = block[content_start:content_end].strip()
                if content:
                    sections.append((cats, content))

        return sections

    def has_markers(self, text: str) -> bool:
        """Check whether text contains any category markers.

        Useful for diagnostics and testing.
        """
        return bool(_CATEGORY_MARKER_RE.search(text))
```

## Section 4: Modify standing_orders.py

Add a module-level `StepInstructionRouter` reference and a setter, following the same pattern used for `_billet_registry` (line 219) and `_directive_store` (line 26).

After line 229 (after `set_billet_registry`), add:

```python
# Module-level StepInstructionRouter, set at startup (AD-651).
_step_router: "StepInstructionRouter | None" = None


def set_step_router(router: "StepInstructionRouter | None") -> None:
    """Wire the StepInstructionRouter for per-step instruction slicing (AD-651).

    Called from finalize.py at startup. Module-level state -- single-runtime
    assumption. Tests must save/restore.
    """
    global _step_router
    _step_router = router


def get_step_instructions(
    agent_type: str,
    hardcoded_instructions: str,
    step_name: str,
    *,
    orders_dir: Path | None = None,
    department: str | None = None,
    callsign: str | None = None,
    agent_rank: str | None = None,
    skill_profile: object | None = None,
) -> str:
    """Compose instructions filtered for a specific chain step.

    Calls compose_instructions() to get the full text, then routes
    through StepInstructionRouter if available and enabled.

    Falls back to full compose_instructions() output when:
    - No StepInstructionRouter is wired
    - The router is disabled
    - No category markers exist in the standing orders
    """
    full = compose_instructions(
        agent_type=agent_type,
        hardcoded_instructions=hardcoded_instructions,
        orders_dir=orders_dir,
        department=department,
        callsign=callsign,
        agent_rank=agent_rank,
        skill_profile=skill_profile,
    )
    if _step_router is not None:
        return _step_router.route(full, step_name)
    return full
```

Also update `clear_cache()` (line 203) to reset the step router reference on cache clear -- add this comment and no-op since the router holds no cache of its own:

```python
    # AD-651: StepInstructionRouter holds no cache — nothing to clear.
```

## Section 5: Wire Into Sub-Task Handlers

### `src/probos/cognitive/sub_tasks/analyze.py`

In `_build_thread_analysis_prompt` (line 50), `_build_situation_review_prompt` (line 209), and `_build_dm_comprehension_prompt` (line 410), replace the `compose_instructions` call with `get_step_instructions`.

Change the import at line 17:

```python
# Before:
from probos.cognitive.standing_orders import compose_instructions

# After:
from probos.cognitive.standing_orders import get_step_instructions
```

In `_build_thread_analysis_prompt` (line 58), replace:

```python
    system_prompt = compose_instructions(
        agent_type=context.get("_agent_type", "agent"),
        hardcoded_instructions="",
        callsign=callsign,
        agent_rank=context.get("_agent_rank"),
        skill_profile=context.get("_skill_profile"),
    )
```

With:

```python
    system_prompt = get_step_instructions(
        agent_type=context.get("_agent_type", "agent"),
        hardcoded_instructions="",
        step_name="analyze",
        callsign=callsign,
        agent_rank=context.get("_agent_rank"),
        skill_profile=context.get("_skill_profile"),
    )
```

Apply the identical change in `_build_situation_review_prompt` (line 217) and `_build_dm_comprehension_prompt` (line 418). All three should pass `step_name="analyze"`.

### `src/probos/cognitive/sub_tasks/compose.py`

Change the import at line 19:

```python
# Before:
from probos.cognitive.standing_orders import compose_instructions

# After:
from probos.cognitive.standing_orders import get_step_instructions
```

In `_build_ward_room_compose_prompt` (line 77), `_build_dm_compose_prompt` (line 198), and `_build_proactive_compose_prompt` (line 240), replace each `compose_instructions(...)` call with `get_step_instructions(...)` adding `step_name="compose"`.

For example, in `_build_ward_room_compose_prompt` (line 77):

```python
    system_prompt = get_step_instructions(
        agent_type=context.get("_agent_type", "agent"),
        hardcoded_instructions="",
        step_name="compose",
        callsign=callsign,
        agent_rank=agent_rank,
        skill_profile=skill_profile,
    )
```

Apply identically to `_build_dm_compose_prompt` (line 198) and `_build_proactive_compose_prompt` (line 240).

**Note:** Do NOT modify evaluate.py or reflect.py in this AD. Those handlers do not currently call `compose_instructions()` directly. When they do in future ADs, they will use `get_step_instructions()` with their respective step names.

## Section 6: Startup Wiring

**File:** `src/probos/startup/finalize.py`

Wire the `StepInstructionRouter` into the standing orders module at startup. Place after the existing `set_billet_registry` wiring (around line 125):

```python
    # AD-651: Wire StepInstructionRouter into standing orders
    from probos.cognitive.standing_orders import set_step_router
    from probos.cognitive.step_instruction_router import StepInstructionRouter
    _step_router = StepInstructionRouter(config.step_instruction)
    set_step_router(_step_router)
    logger.info("AD-651: StepInstructionRouter wired into standing orders")
```

This follows the exact pattern of `set_billet_registry` (line 124-126): import the setter, create the instance, call the setter, log.

## Section 7: Tests

Create `tests/test_ad651_step_instruction_router.py`.

### Test Pattern

Use `_Fake*` stubs over complex mocks. Use `tmp_path` for any file I/O. Each test is Arrange-Act-Assert, verifying one behavior.

### Test Table

| # | Test Name | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_route_disabled_returns_full` | When `enabled=False`, `route()` returns full text unchanged |
| 2 | `test_route_no_markers_returns_full` | Text with no `<!-- category: -->` markers returns full text |
| 3 | `test_route_unknown_step_returns_full` | Unknown step name returns full text |
| 4 | `test_route_analyze_filters_correctly` | Analyze step receives only analyze-relevant categories + universal |
| 5 | `test_route_compose_filters_correctly` | Compose step receives only compose-relevant categories + universal |
| 6 | `test_route_query_receives_minimal` | Query step (no categories beyond universal) receives only untagged + universal |
| 7 | `test_untagged_content_always_included` | Content before any marker is always included in every step |
| 8 | `test_universal_categories_always_included` | Categories in `universal_categories` appear in every step |
| 9 | `test_parse_sections_single_category` | Parser extracts a single category marker correctly |
| 10 | `test_parse_sections_multi_category` | Parser handles `<!-- category: name1, name2 -->` correctly |
| 11 | `test_parse_sections_tier_separator` | Parser handles `---` tier separators from compose_instructions |
| 12 | `test_has_markers_true` | `has_markers()` returns True when markers present |
| 13 | `test_has_markers_false` | `has_markers()` returns False when no markers |
| 14 | `test_token_savings_logged` | When `log_token_savings=True`, debug log emitted with savings percentage |
| 15 | `test_get_step_instructions_no_router` | `get_step_instructions()` returns full output when no router wired |
| 16 | `test_get_step_instructions_with_router` | `get_step_instructions()` routes through router when wired |
| 17 | `test_category_markers_in_ship_md` | `config/standing_orders/ship.md` contains expected category markers |
| 18 | `test_category_markers_in_federation_md` | `config/standing_orders/federation.md` contains expected category markers |
| 19 | `test_compose_analyze_disjoint` | Analyze and compose results for the same input share universal categories but diverge on step-specific ones |
| 20 | `test_empty_instructions_returns_empty` | Empty string input returns empty string |

### Test Implementation Notes

For tests 17-18, read the actual standing order files from `config/standing_orders/` and verify they contain `<!-- category: -->` markers using `StepInstructionRouter.has_markers()` and by checking for specific expected categories via regex.

For test 14, use `caplog` fixture at DEBUG level to verify the log message format.

For tests 15-16, save and restore the module-level `_step_router` in `standing_orders.py` using try/finally:

```python
from probos.cognitive import standing_orders

old_router = standing_orders._step_router
try:
    standing_orders._step_router = None  # or a configured router
    # ... test ...
finally:
    standing_orders._step_router = old_router
```

### Targeted Test Commands

```bash
# After each section:
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad651_step_instruction_router.py -v

# Full suite after all sections:
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

After all tests pass:

1. **PROGRESS.md** — Add line: `- [x] AD-651: Standing Order Decomposition (step-specific instruction routing)`
2. **docs/development/roadmap.md** — Add to Era V table: `| AD-651 | Standing Order Decomposition | Step-specific instruction routing for cognitive chain | CLOSED |`
3. **DECISIONS.md** — Add entry:
   ```
   ## AD-651: Standing Order Decomposition
   **Date:** 2026-04-27
   **Decision:** Decompose monolithic standing orders into step-specific instruction slices using category markers in markdown files and a StepInstructionRouter class.
   **Rationale:** Each cognitive chain step (analyze, compose, evaluate, reflect) receives only the standing order sections relevant to its role, reducing token waste and instruction dilution. Backward compatible via fallback when no markers exist.
   **Status:** Implemented
   ```

## Scope Boundaries (Hard Rules)

- **DO:** Create StepInstructionRouter, add category markers, add StepInstructionConfig, wire get_step_instructions into analyze.py and compose.py, write 20 tests.
- **DO NOT:** Change standing order prose content (only add marker comments). Do not modify billet_registry.py. Do not change the 7-tier hierarchy in compose_instructions(). Do not add API endpoints. Do not modify evaluate.py or reflect.py. Do not modify cognitive_agent.py (the single-call path continues to use compose_instructions directly). Do not change the sub-task chain flow or protocol.
