# AD-393: Personality Activation — Wire Big Five Traits into Agent Behavior

## Overview

ProbOS agents have fully designed personality profiles (Big Five traits,
callsigns, roles, departments) stored in `config/standing_orders/crew_profiles/`
YAML files — but these traits are never injected into the LLM system prompt.
Every agent talks with the same behavioral style regardless of their personality
profile.

This AD activates personality by wiring crew profiles into
`compose_instructions()` as a new tier between the hardcoded identity and the
Federation Constitution. Each agent will receive natural language behavioral
guidance derived from their Big Five trait values, plus their identity
(callsign, role, department, rank).

This is a **horizontal concern** — one change that activates personality for
every CognitiveAgent in the system simultaneously.

## Architecture

### 1. Personality Tier in `compose_instructions()`

**File:** `src/probos/cognitive/standing_orders.py`

Add a new **Tier 1.5** between the hardcoded identity (Tier 1) and Federation
Constitution (Tier 2). This tier translates the crew profile into natural
language behavioral guidance.

**New function: `_build_personality_block(agent_type, department)`**

This function:
1. Calls `load_seed_profile(agent_type)` to get the YAML profile
2. If no profile exists (returns empty dict), returns empty string (graceful skip)
3. Builds a `## Crew Identity & Personality` section with:
   - Identity line: callsign, display_name, department, role
   - Behavioral guidance derived from Big Five trait values

**Signature:**
```python
def _build_personality_block(agent_type: str, department: str | None = None) -> str:
```

**Identity line format:**
```
You are {callsign}, the {display_name} — {role} of {department} department.
```
If callsign is empty, use display_name only. If department is empty, omit.
If role is "chief", say "department chief". If "officer", say "officer".
If "crew", say "crew member".

**Trait-to-guidance mapping:**

Each Big Five dimension produces a behavioral instruction based on whether the
trait is high (>= 0.7), low (<= 0.3), or neutral (0.31-0.69). Neutral traits
produce no guidance (only deviations from baseline are worth mentioning).

```python
_TRAIT_GUIDANCE: dict[str, dict[str, str]] = {
    "openness": {
        "high": "Explore creative and unconventional approaches. Suggest alternatives the Captain may not have considered.",
        "low": "Prefer proven patterns and established conventions. Be cautious with novel approaches unless evidence supports them.",
    },
    "conscientiousness": {
        "high": "Be thorough and precise. Verify claims before asserting them. Show your reasoning.",
        "low": "Focus on the big picture over details. Move quickly and iterate rather than perfecting upfront.",
    },
    "extraversion": {
        "high": "Be proactive in communication. Volunteer relevant observations. Collaborate openly.",
        "low": "Be concise and speak only when you have substantive input. Avoid unnecessary commentary.",
    },
    "agreeableness": {
        "high": "Seek consensus and build on others' ideas. Defer to the crew's collective judgment when appropriate.",
        "low": "Challenge assumptions and question consensus. Play devil's advocate when you see risks others may miss.",
    },
    "neuroticism": {
        "high": "Flag risks early. Consider failure modes. Err on the side of caution with irreversible actions.",
        "low": "Stay calm under pressure. Don't over-index on edge cases. Trust the system's safety mechanisms.",
    },
}
```

For each trait, check the value:
- `>= 0.7`: include the "high" guidance
- `<= 0.3`: include the "low" guidance
- Between: skip (neutral, no guidance needed)

Collect all applicable guidance lines into a bulleted list under "Behavioral
Style:".

**Example output for the Architect (openness=0.9, conscientiousness=0.8,
agreeableness=0.5, neuroticism=0.3):**

```
## Crew Identity & Personality

You are Number One, the Architect — department chief of Science.

Behavioral Style:
- Explore creative and unconventional approaches. Suggest alternatives the Captain may not have considered.
- Be thorough and precise. Verify claims before asserting them. Show your reasoning.
- Stay calm under pressure. Don't over-index on edge cases. Trust the system's safety mechanisms.
```

### 2. Integration into `compose_instructions()`

**File:** `src/probos/cognitive/standing_orders.py`

Modify `compose_instructions()` to insert the personality block after Tier 1
(hardcoded identity) and before Tier 2 (Federation Constitution):

```python
def compose_instructions(
    agent_type: str,
    hardcoded_instructions: str,
    *,
    orders_dir: Path | None = None,
    department: str | None = None,
) -> str:
    d = orders_dir or _DEFAULT_ORDERS_DIR
    parts: list[str] = []

    # 1. Hardcoded identity
    if hardcoded_instructions:
        parts.append(hardcoded_instructions.strip())

    # 1.5 Crew personality & identity (AD-393) — NEW
    dept = department or get_department(agent_type)
    personality_block = _build_personality_block(agent_type, dept)
    if personality_block:
        parts.append(personality_block)

    # 2. Federation Constitution
    # ... (rest unchanged)
```

Note: `dept` is computed once here and reused in Tier 4 (department protocols).
Refactor the existing Tier 4 code to use this already-computed `dept` variable
instead of re-computing it.

### 3. Import `load_seed_profile`

Add the import at the top of `standing_orders.py`:
```python
from probos.crew_profile import load_seed_profile
```

Since `load_seed_profile` uses `yaml.safe_load` internally (lazy import), no
new dependency is added.

### 4. Caching

The personality block should be cached to avoid re-reading YAML on every
`decide()` call. Use `@lru_cache(maxsize=32)` on `_build_personality_block()`.
The key is `(agent_type, department)` which is already the function signature.

Clear the personality cache when `clear_cache()` is called:
```python
def clear_cache() -> None:
    _load_file.cache_clear()
    _build_personality_block.cache_clear()
```

### 5. Register Scout Department

While we're in `standing_orders.py`, add the scout agent type to
`_AGENT_DEPARTMENTS`:

```python
"scout": "science",
```

This prepares for AD-394 (ScoutAgent).

## File Plan

| Action | File | Description |
|--------|------|-------------|
| MODIFY | `src/probos/cognitive/standing_orders.py` | Add `_build_personality_block()`, insert Tier 1.5 in `compose_instructions()`, add `load_seed_profile` import, add `"scout": "science"` to department map, update `clear_cache()` |
| CREATE | `tests/test_personality_wiring.py` | Unit tests for personality activation |

## Acceptance Criteria

1. `_build_personality_block()` loads seed profile YAML and returns a formatted
   personality section
2. High traits (>= 0.7) produce "high" behavioral guidance
3. Low traits (<= 0.3) produce "low" behavioral guidance
4. Neutral traits (0.31-0.69) produce no guidance
5. Identity line includes callsign, display_name, role, department
6. Graceful skip when no profile YAML exists (returns empty string)
7. Graceful skip when profile has no personality key
8. Personality block appears between Tier 1 and Tier 2 in composed output
9. `_build_personality_block()` is cached with `@lru_cache`
10. `clear_cache()` clears personality cache alongside file cache
11. `"scout": "science"` added to `_AGENT_DEPARTMENTS`
12. Existing tests continue to pass (this is additive — no existing prompt
    content changes)

## Test Requirements

Create `tests/test_personality_wiring.py`:

1. **test_high_trait_guidance** — Set openness=0.9 in a test profile, verify
   the "high" openness guidance appears in the personality block
2. **test_low_trait_guidance** — Set neuroticism=0.2, verify "low" neuroticism
   guidance appears
3. **test_neutral_trait_no_guidance** — Set agreeableness=0.5, verify no
   agreeableness guidance appears
4. **test_identity_line_with_callsign** — Profile with callsign "Scotty",
   display_name "Builder", verify identity line format
5. **test_identity_line_without_callsign** — Profile with empty callsign,
   verify graceful fallback
6. **test_no_profile_returns_empty** — Agent type with no YAML returns empty
   string
7. **test_personality_in_composed_instructions** — Call `compose_instructions()`
   for "architect", verify personality block appears between hardcoded
   instructions and Federation Constitution
8. **test_all_traits_high** — All traits at 0.9, verify all 5 guidance lines
   appear
9. **test_all_traits_neutral** — All traits at 0.5, verify only identity line
   appears (no behavioral style section)
10. **test_cache_is_used** — Call `_build_personality_block()` twice, verify
    `load_seed_profile` is only called once (cached)

## Design Notes

**Why Tier 1.5 and not Tier 7?**
Identity should be established early in the prompt — the LLM needs to know
*who it is* before receiving instructions about *what to do*. The hardcoded
instructions (Tier 1) define the agent's function. The personality block
(Tier 1.5) defines the agent's character. Then the standing orders define
behavioral constraints.

**Why natural language instead of raw numbers?**
LLMs respond better to behavioral descriptions than numeric parameters.
"Be thorough and precise" is more effective than "conscientiousness: 0.8".
The numeric values drive the selection logic; the text drives the behavior.

**Why only high/low, not granular?**
Three bands (high/neutral/low) are sufficient because:
1. LLMs don't reliably distinguish between "somewhat creative" and "moderately
   creative" — the behavioral difference is negligible
2. Neutral traits (the baseline) don't need mention — only deviations are
   interesting
3. This matches how personality manifests in practice — you notice the extremes

**Future evolution path (not in this AD):**
- ProfileStore persistence means personality can drift over time
- LEARNED_LESSON directives (AD-386 Tier 6) can override personality guidance
  at runtime
- Counselor tracks personality drift and flags to Captain
- Dream engine could create LEARNED_LESSON directives from consolidated patterns
- None of this requires changes to the personality wiring — it all flows
  through the existing tier system

## Do NOT Build

- **Do NOT** modify PersonalityTraits or CrewProfile dataclasses
- **Do NOT** add dream-to-directive pipeline (future AD)
- **Do NOT** add dynamic personality evolution (future AD)
- **Do NOT** modify any existing agent's hardcoded instructions
- **Do NOT** change the ProfileStore or its persistence
- **Do NOT** add rank-based behavioral changes (future, separate concern)
- **Do NOT** change any existing YAML crew profiles
