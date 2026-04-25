# AD-626: Dual-Mode Skill Activation — Discovery + Augmentation

## Context

### The Cognitive Toolbox Metaphor

Human skills work like tools in a cognitive toolbox. You have them available, but they only activate when the context demands them. Some tools provide **new capabilities** (a wrench lets you turn bolts you couldn't turn bare-handed). Others **augment natural abilities** (a pole extends your reach — you already have arms, but the pole makes them better).

ProbOS cognitive skills (SKILL.md files) currently only support the first mode: **discovery**. When an agent encounters an intent it doesn't already handle, the skill catalog discovers a matching skill and loads its instructions. This is the "wrench" — a new capability.

But AD-625 (Communication Discipline) exposed a gap: the communication-discipline skill declares `proactive_think` as its intent, but all crew agents already handle `proactive_think`. Since the skill catalog is only consulted for *unhandled* intents (line 1435 of `cognitive_agent.py`), the SKILL.md instructions are never loaded. The agent can already reach — it just can't reach the pole.

### Current Activation Path (Discovery Only)

```
handle_intent(intent)
  │
  ├── is intent targeted at me? → yes → skip catalog check, proceed
  │
  ├── is intent in _handled_intents? → yes → skip catalog check, proceed
  │                                           ← SKILL.md never loaded
  │
  └── intent NOT handled → find_by_intent() → load SKILL.md → decide
                           ← Discovery mode: new capability
```

### What's Missing: Augmentation Mode

```
handle_intent(intent)
  │
  ├── intent handled (proactive_think, ward_room_notification, etc.)
  │   ├── any skills in toolbox augment this intent?
  │   │   ├── yes + agent has proficiency → load as supplementary instructions
  │   │   └── no → proceed with built-in behavior only
  │   └── proceed with cognitive lifecycle
  │
  └── intent NOT handled
      └── [existing discovery path unchanged]
```

### How Other Solutions Handle This

Claude Code injects skills based on **trigger conditions** matched against conversation context — not intent routing. A skill fires when it matches, regardless of whether the agent "already handles" the topic. Skills are behavioral overlays, not capability replacements.

ProbOS needs both modes because its intent routing is structural (agents declare which intents they handle), whereas Claude Code's routing is contextual (skills match dynamically). Neither model is wrong — but ProbOS needs augmentation to complement its structural routing.

### Dependencies

- **AD-596a–e** (Cognitive Skill Catalog) — COMPLETE. `CognitiveSkillCatalog`, `find_by_intent()`, `get_instructions()`, `SkillBridge`
- **AD-625** (Communication Discipline) — COMPLETE. First augmentation skill, currently blocked by this gap
- **AD-428** (Skill Framework) — COMPLETE. `ProficiencyLevel`, `AgentSkillService`, proficiency gates

## Design Decisions

### DD-1: Two activation modes, one catalog

The `CognitiveSkillCatalog` already stores all skills. Skills don't need a separate registry for augmentation vs discovery. The difference is *when* the catalog is consulted:

- **Discovery mode** (existing): Catalog consulted when `intent not in _handled_intents`. Skill provides the *entire* capability. Agent self-deselects without it.
- **Augmentation mode** (new): Catalog consulted for *all* intents. Matching skills provide supplementary instructions layered onto existing behavior. Agent functions without it — the skill makes it better.

One catalog, two consultation points, same `find_by_intent()` API.

### DD-2: SKILL.md metadata declares activation mode

Add a new optional frontmatter field: `probos-activation: discovery | augmentation | both`

- `discovery` (default, backward-compatible): Only loads for unhandled intents. Existing behavior.
- `augmentation`: Only loads as supplementary instructions for handled intents. Never used for discovery.
- `both`: Loads in either context. A skill that can both provide new capability AND augment existing behavior.

The communication-discipline skill would declare `probos-activation: augmentation`.

### DD-3: Augmentation skills load as supplementary instructions, not primary

Discovery skills are injected as `## Active Skill: {name}` — the agent's *primary* instruction set for that intent.

Augmentation skills are injected differently: `## Skill Guidance: {name}` — supplementary behavioral guidance layered *after* the agent's existing system prompt. The distinction matters:

- Discovery: "Here's how to do this task you've never done."
- Augmentation: "While doing what you already do, also apply these principles."

Multiple augmentation skills can stack (e.g., an agent handling `proactive_think` might get both communication-discipline AND a future domain-expertise skill). Discovery is exclusive (only one skill provides the capability).

### DD-4: Proficiency gates apply to augmentation too

An agent must have the skill in their profile AND meet `min_proficiency` to receive augmentation instructions. An agent at FOLLOW (1) with `min_proficiency: 1` gets the instructions. An agent without the skill record does not.

This is the "tool in my toolbox" check — you must own the tool to use it. But owning the tool (having the skill at any level) means you get the instructions. The proficiency *level* affects what the instructions say (via AD-625's tier-specific guidance), not whether the instructions load at all.

### DD-5: Augmentation loading happens in `_decide_via_llm()`, not `handle_intent()`

The discovery path is in `handle_intent()` (lines 1432-1458) because it determines *whether the agent handles the intent at all*. Self-deselection happens there.

Augmentation loading should happen in `_decide_via_llm()` (around line 1340, after `compose_instructions()` returns), because:
1. The agent has already committed to handling the intent
2. Augmentation instructions are part of prompt construction, not routing
3. Multiple augmentation skills can stack (append one by one)
4. No self-deselection possible — the agent already handles this intent

### DD-6: Augmentation skills are NOT loaded every cycle

Loading instructions for every proactive_think cycle regardless of context would be wasteful and would dilute the signal. Instead, augmentation skills load based on **contextual relevance**:

For `proactive_think`: Load communication-discipline only when the agent's think cycle produces output that would result in a Ward Room post (not when the agent returns [NO_RESPONSE]). However, since we can't predict the output before the LLM call, the pragmatic approach is:

- **Always load for matching intents.** The skill's instructions themselves teach the agent when NOT to apply them (e.g., communication-discipline says "Before posting any reply..." — if the agent decides not to post, the instructions are harmless unused context).
- **Token cost is minimal.** A SKILL.md's instruction section is typically 200-400 tokens — negligible relative to the full system prompt.
- **The skill's own checklist acts as the activation gate.** "When to Use: Before posting any reply to a Ward Room channel." The agent self-selects whether to apply.

This matches how humans use cognitive tools: the tool is *accessible* (in working memory) for the duration of the relevant activity, even if you don't end up using it every time.

## Implementation

### File 1: `src/probos/cognitive/skill_catalog.py` (MODIFY — 2 changes)

**Change 1:** Add `activation` field to `CognitiveSkillEntry` dataclass (after line 63):

```python
@dataclass
class CognitiveSkillEntry:
    name: str
    description: str
    skill_dir: Path
    license: str = ""
    compatibility: str = ""
    department: str = "*"
    skill_id: str = ""
    min_proficiency: int = 1
    min_rank: str = "ensign"
    intents: list[str] = field(default_factory=list)
    origin: str = "internal"
    loaded_at: float = 0.0
    activation: str = "discovery"  # AD-626: "discovery", "augmentation", or "both"
```

**Change 2:** Add `find_augmentation_skills()` method (after `find_by_intent` at line 357):

```python
    def find_augmentation_skills(
        self, intent_name: str, department: str | None = None, agent_rank: str | None = None,
    ) -> list[CognitiveSkillEntry]:
        """AD-626: Find skills that augment an already-handled intent.

        Returns skills where:
        - activation is 'augmentation' or 'both'
        - intent_name is in the skill's declared intents
        - department and rank filters pass
        """
        results = []
        for entry in self._cache.values():
            if entry.activation not in ("augmentation", "both"):
                continue
            if intent_name not in entry.intents:
                continue
            if department and entry.department != "*" and entry.department != department:
                continue
            if agent_rank and not self._rank_meets_minimum(agent_rank, entry.min_rank):
                continue
            results.append(entry)
        return results
```

**Change 3:** Parse `probos-activation` from SKILL.md metadata in the loader.

Find where `CognitiveSkillEntry` is constructed from YAML frontmatter (in `_load_skill_dir()` or equivalent). Add:

```python
activation=metadata.get("probos-activation", "discovery"),
```

Validate that the value is one of `("discovery", "augmentation", "both")`. Default to `"discovery"` for backward compatibility.

### File 2: `src/probos/cognitive/cognitive_agent.py` (MODIFY — 1 change)

In `_decide_via_llm()`, after the existing skill instruction injection (line 1340-1343), add augmentation skill loading:

```python
        # AD-596b: Append cognitive skill instructions when activated (discovery mode)
        _skill_instr = observation.get("cognitive_skill_instructions")
        if _skill_instr:
            composed += f"\n\n---\n\n## Active Skill: {observation.get('cognitive_skill_name', 'Unknown')}\n\n{_skill_instr}"

        # AD-626: Load augmentation skills for handled intents
        _aug_instructions = self._load_augmentation_skills(observation.get("intent", ""))
        if _aug_instructions:
            composed += _aug_instructions
```

Add helper method:

```python
    def _load_augmentation_skills(self, intent: str) -> str:
        """AD-626: Load augmentation skill instructions for a handled intent.

        Returns concatenated skill guidance sections, or empty string.
        Augmentation skills enhance existing behavior — they don't provide
        new capabilities. Think: cognitive tools that extend natural ability.
        """
        catalog = getattr(self, '_cognitive_skill_catalog', None)
        if not catalog:
            return ""

        department = getattr(self, 'department', None)
        rank = getattr(self, 'rank', None)
        rank_val = rank.value if hasattr(rank, 'value') else rank

        entries = catalog.find_augmentation_skills(
            intent, department=department, agent_rank=rank_val,
        )
        if not entries:
            return ""

        # Proficiency gate each skill
        bridge = getattr(self, '_skill_bridge', None)
        profile = getattr(self, '_skill_profile', None)
        parts = []
        for entry in entries:
            if bridge and not bridge.check_proficiency_gate(self.id, entry, profile):
                continue  # Agent lacks proficiency for this augmentation
            instructions = catalog.get_instructions(entry.name)
            if instructions:
                parts.append(
                    f"\n\n---\n\n## Skill Guidance: {entry.name}\n\n{instructions}"
                )
                logger.debug(
                    "AD-626: Loaded augmentation skill '%s' for intent '%s' on %s",
                    entry.name, intent, self.agent_type,
                )

        return "".join(parts)
```

### File 3: `config/skills/communication-discipline/SKILL.md` (MODIFY — 1 line)

Add `probos-activation` to the YAML frontmatter:

```yaml
---
name: communication-discipline
description: >
  Evaluate whether a Ward Room reply adds new information before posting.
  Use before composing any reply to a shared channel or thread.
license: Apache-2.0
metadata:
  probos-department: "*"
  probos-skill-id: communication
  probos-min-proficiency: 1
  probos-min-rank: ensign
  probos-intents: "proactive_think,ward_room_notification"
  probos-activation: augmentation
---
```

Two changes:
1. Add `probos-activation: augmentation`
2. Add `ward_room_notification` to `probos-intents` — communication discipline applies when replying to threads too, not just during proactive thinks

### File 4: `src/probos/cognitive/cognitive_agent.py` (MODIFY — exercise recording)

In `handle_intent()`, after the cognitive lifecycle completes and augmentation skills were loaded, record exercises for augmentation skills used. Add after line 1566 (existing discovery exercise recording):

```python
        # AD-626: Record exercises for augmentation skills
        if hasattr(self, '_augmentation_skills_used') and self._augmentation_skills_used:
            _bridge = getattr(self, '_skill_bridge', None)
            if _bridge:
                for _aug_entry in self._augmentation_skills_used:
                    try:
                        import asyncio
                        asyncio.create_task(
                            _bridge.record_skill_exercise(self.id, _aug_entry)
                        )
                    except Exception:
                        logger.debug("AD-626: Aug skill exercise recording failed", exc_info=True)
            self._augmentation_skills_used = []
```

Update `_load_augmentation_skills()` to track which skills were loaded:

```python
        # Track for exercise recording
        self._augmentation_skills_used = loaded_entries  # list of CognitiveSkillEntry
```

### File 5: `tests/test_ad626_skill_activation.py` (NEW — ~35 tests)

```
# --- CognitiveSkillEntry activation field ---
test_default_activation_is_discovery
test_activation_augmentation_parsed_from_yaml
test_activation_both_parsed_from_yaml
test_invalid_activation_defaults_to_discovery

# --- find_augmentation_skills() ---
test_find_augmentation_returns_augmentation_skills
test_find_augmentation_excludes_discovery_skills
test_find_augmentation_includes_both_skills
test_find_augmentation_filters_by_intent
test_find_augmentation_filters_by_department
test_find_augmentation_filters_by_rank
test_find_augmentation_returns_empty_for_no_matches
test_find_augmentation_multiple_skills_stack

# --- _load_augmentation_skills() ---
test_augmentation_loads_for_handled_intent
test_augmentation_not_loaded_without_catalog
test_augmentation_respects_proficiency_gate
test_augmentation_fails_proficiency_returns_empty
test_augmentation_multiple_skills_concatenated
test_augmentation_format_uses_skill_guidance_header
test_augmentation_no_skills_returns_empty_string

# --- Integration with discovery ---
test_discovery_still_works_for_unhandled_intents
test_augmentation_does_not_interfere_with_discovery
test_discovery_skill_uses_active_skill_header
test_augmentation_skill_uses_guidance_header

# --- SKILL.md loading ---
test_communication_discipline_has_augmentation_activation
test_communication_discipline_has_ward_room_notification_intent
test_skill_body_loads_for_augmentation_skill

# --- Exercise recording ---
test_augmentation_records_exercise_on_completion
test_no_exercise_without_augmentation_skills
test_exercise_recording_log_and_degrade

# --- Edge cases ---
test_agent_without_skill_profile_no_augmentation
test_agent_without_bridge_still_loads_instructions
test_augmentation_for_direct_message_intent
test_multiple_augmentation_skills_different_proficiency_gates

# --- Backward compatibility ---
test_existing_discovery_skills_unaffected
test_skills_without_activation_field_default_to_discovery
test_old_skill_md_without_probos_activation_works
```

## Engineering Principles Compliance

| Principle | How Addressed |
|-----------|---------------|
| **S (Single Responsibility)** | `find_augmentation_skills()` is a query on the catalog. `_load_augmentation_skills()` is prompt construction. Exercise recording is separate. Three distinct responsibilities. |
| **O (Open/Closed)** | Existing discovery path is UNCHANGED. Augmentation is a new code path that reads from the same catalog. No modification to discovery behavior. New `activation` field has a default of `"discovery"` — all existing skills work without changes. |
| **L (Liskov)** | No inheritance changes. |
| **I (Interface Segregation)** | `find_augmentation_skills()` is a narrow query method. Callers don't need to understand discovery internals. |
| **D (Dependency Inversion)** | `_load_augmentation_skills()` depends on `CognitiveSkillCatalog` (already injected) and `SkillBridge` (already injected). No new concrete dependencies. |
| **Law of Demeter** | Helper method encapsulates catalog + bridge + profile access. No deep chains. |
| **Fail Fast** | If catalog or bridge is missing, return empty string — log-and-degrade. Agent functions without augmentation. |
| **DRY** | Reuses `find_by_intent()` pattern. Reuses `check_proficiency_gate()`. Reuses `get_instructions()`. New query method is minimal — just a filter on existing data. |
| **Defense in Depth** | Augmentation is additive — it enhances prompts, doesn't replace them. If augmentation loading fails, all existing quality controls remain active (standing orders, mechanical gates, etc.). |

## Files Summary

| # | File | Action | Lines Δ (est.) |
|---|------|--------|----------------|
| 1 | `src/probos/cognitive/skill_catalog.py` | MODIFY | ~25 |
| 2 | `src/probos/cognitive/cognitive_agent.py` | MODIFY | ~50 |
| 3 | `config/skills/communication-discipline/SKILL.md` | MODIFY | ~2 |
| 4 | `tests/test_ad626_skill_activation.py` | NEW | ~350 |

## Key Files to Reference During Build

- `src/probos/cognitive/skill_catalog.py` — `CognitiveSkillEntry` (line 54), `find_by_intent()` (line 355), `get_instructions()` (line 338), `get_descriptions()` (line 326), `_load_skill_dir()` (find YAML parsing)
- `src/probos/cognitive/cognitive_agent.py` — `handle_intent()` (line 1419, discovery path at 1432-1458), `_decide_via_llm()` (line 1170, skill injection at 1340-1343)
- `src/probos/cognitive/skill_bridge.py` — `check_proficiency_gate()` (line 83), `record_skill_exercise()` (line 131)
- `config/skills/communication-discipline/SKILL.md` — the first augmentation skill

## Deferred (Out of Scope)

- **Context-triggered activation** (Claude Code style): Skills that activate based on content analysis (e.g., "activate when agent is about to write code") rather than intent matching. Requires LLM pre-screening or content classifiers. Future AD.
- **Skill priority / conflict resolution**: When multiple augmentation skills match, they stack in catalog order. Future AD could add priority fields or conflict detection.
- **Augmentation skill usage analytics**: Tracking which augmentation skills actually influence agent behavior (did the agent follow the guidance?). Requires output evaluation.
- **Dynamic skill loading**: Loading/unloading skills mid-session based on changing context. Current model loads at prompt construction time.

## Verification

```bash
# Unit tests
uv run python -m pytest tests/test_ad626_skill_activation.py -v

# Regression — existing skill catalog tests
uv run python -m pytest tests/ -k "skill_catalog or skill_596" -v

# Regression — cognitive agent tests
uv run python -m pytest tests/ -k "cognitive" -v

# Manual verification
# 1. Start ProbOS, trigger proactive_think cycle
# 2. Check logs for "AD-626: Loaded augmentation skill 'communication-discipline'"
# 3. Verify system prompt contains "## Skill Guidance: communication-discipline"
# 4. Verify SKILL.md checklist instructions appear in the prompt
# 5. Verify discovery mode still works for unhandled intents (test with a new skill)
```
