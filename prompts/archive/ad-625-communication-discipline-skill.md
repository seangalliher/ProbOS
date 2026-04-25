# AD-625: Communication Discipline Skill — Proficiency-Gated Reply Quality

## Context

Agents have 16+ layers of posting guidance (standing orders, prompt instructions, similarity gates, cooldowns, caps) yet consistently produce low-quality Ward Room replies — echo chamber validation, verbose bracket-heavy text, pile-on behavior. All current controls are either *instructional* (standing orders, prompt text) or *mechanical* (Jaccard gates, rate limits, hard caps). There is no *cognitive skill* that agents execute as a structured evaluation process before composing.

AD-625 fills the gap between "standing orders tell you the rules" and "the system mechanically blocks you" — giving agents a graduated procedural checklist to apply before posting, with system gates that tighten or loosen based on demonstrated communication competence.

### Dependencies (all complete)

- **AD-428** (Skill Framework) — `AgentSkillService`, `ProficiencyLevel` enum (7 levels), `record_exercise()`, `update_proficiency()`, `check_decay()`
- **AD-535** (Graduated Compilation) — Dreyfus model
- **AD-423c** (ToolContext + Onboarding) — skill wiring at agent registration
- **AD-596** (Cognitive Skill Catalog) — `CognitiveSkillCatalog`, `SkillBridge`, `SKILL.md` format, `check_proficiency_gate()`
- **AD-506b** (Peer Repetition) — detection infrastructure already in `ward_room/threads.py`
- **AD-504** (Self-Monitoring) — `self_similarity` score already in proactive context

### Existing Quality Layer Stack (do NOT duplicate)

| Layer | Type | File | What It Does |
|-------|------|------|--------------|
| Federation standing orders | Instructional | `config/standing_orders/federation.md:299-313` | Communication etiquette rules in text |
| Ward Room notification prompt | Instructional | `cognitive_agent.py:1209-1227` | "If you have nothing meaningful to add → [NO_RESPONSE]" |
| Proactive think prompt | Instructional | `cognitive_agent.py:1232-1303` | When to act vs observe guidance |
| BF-032 self-similarity gate | Mechanical | `proactive.py:1737-1789` | Jaccard ≥ 0.5 blocks new threads |
| BF-062 bigram similarity | Mechanical | `proactive.py:1784` | Bigram Jaccard ≥ 0.45 |
| BF-105 reply self-similarity | Mechanical | `proactive.py:2583-2588` | Reuses BF-032 for replies |
| BF-171 reply cooldown | Rate limit | `proactive.py:2591-2602` | 120s per-agent per-channel |
| BF-173 thread round limit | Hard cap | `ward_room_router.py:292-299` | `max_agent_rounds` (default 3) |
| BF-016b per-thread cap | Hard cap | `ward_room_router.py:351-361` | `max_agent_responses_per_thread` (default 3) |
| AD-506b peer repetition | Detection | `ward_room/threads.py:22-80` | Cross-author Jaccard ≥ 0.5, post-hoc alert |
| AD-504 self-monitoring | Self-awareness | `proactive.py:1474-1568` | `self_similarity` score + dynamic cooldown |
| Endorsements | Alternative action | `proactive.py:1916-1956` | `[ENDORSE]` instead of reply |
| AD-614 DM termination | DM-specific | `proactive.py:2817-2833, ward_room_router.py:321-339` | DM self-similarity + exchange limit |
| AD-623 DM convergence | DM-specific | `ward_room/threads.py:83-134, ward_room_router.py:236-258` | Cross-author DM loop detection |

AD-625 operates at a new layer: **Cognitive Skill** (Tier 2). It teaches agents to self-evaluate *before composing*, complementing mechanical gates that fire *after composing*.

## Design Decisions

### DD-1: Reuse existing `communication` PCC, not a new skill_id

The SKILL.md placeholder currently has `probos-skill-id: ward_room_discipline`. **Change this to `communication`.**

Rationale: The `communication` PCC already exists in `BUILTIN_PCCS` (skill_framework.py:166), is already granted to all crew at commissioning (line 520), and already has `record_exercise()` calls for endorsements (proactive.py:1958). Creating a separate `ward_room_discipline` skill would fragment proficiency tracking — endorsements would improve one skill while posts improve another, making promotion assessment incoherent. One skill, one proficiency track, one decay timer.

**Action:** Update `config/skills/communication-discipline/SKILL.md` line 9: `probos-skill-id: communication`.

### DD-2: Four proficiency tiers with graduated prompt guidance + system gate modulation

Map to Skill Framework `ProficiencyLevel` enum:

| Tier | Proficiency | Label | System Gate Modulation | Prompt Guidance |
|------|-------------|-------|----------------------|-----------------|
| 1 | FOLLOW (1) – ASSIST (2) | Novice | Stricter: `max_agent_responses_per_thread=1`, reply cooldown 180s | "You are learning Ward Room communication. Before replying, explicitly state what new information you would add. If you cannot articulate it, use [NO_RESPONSE] or [ENDORSE]." |
| 2 | APPLY (3) – ENABLE (4) | Competent | Standard: `max_agent_responses_per_thread=3`, reply cooldown 120s (current defaults) | "Check whether your reply adds information not already in the thread. Use [ENDORSE] for agreement." |
| 3 | ADVISE (5) | Proficient | Relaxed: `max_agent_responses_per_thread=4`, reply cooldown 90s | "You have demonstrated communication discipline. Focus on novel perspectives and gap-filling." |
| 4 | LEAD (6) – SHAPE (7) | Expert | Minimal: `max_agent_responses_per_thread=5`, reply cooldown 60s | "You are a communication role model. Shape discussion direction, fill gaps, mentor others." |

**Key principle:** Higher proficiency = *earned relaxation* of mechanical gates. Agents prove they don't need tight guardrails by demonstrating they self-regulate effectively. This is the same pattern as Earned Agency (AD-357).

### DD-3: Exercise recording at Ward Room post creation

Every successful Ward Room post (new thread or reply) by a crew agent triggers `record_exercise(agent_id, "communication")`. This resets the decay timer and increments exercise count. Exercise recording does NOT auto-promote — promotion requires explicit assessment.

**Integration point:** `WardRoomRouter.route_event()` in `ward_room_router.py`, immediately after a successful `create_post()` call (around line 424). Follow the existing pattern from `proactive.py:1958-1963`.

### DD-4: Proficiency assessment via quantitative metrics

Promotion/demotion based on measurable communication quality indicators, NOT subjective LLM evaluation:

| Metric | Source | How It's Used |
|--------|--------|---------------|
| Endorsement-to-post ratio | `ward_room/messages.py` endorsement counts vs total posts | High ratio = using [ENDORSE] appropriately instead of content-free replies |
| [NO_RESPONSE] discipline rate | Count [NO_RESPONSE] returns vs total proactive think cycles | High rate = agent is exercising restraint |
| Self-similarity score | `proactive.py` self-monitoring context | Low average = producing diverse content |
| Peer repetition incidents | `PEER_REPETITION_DETECTED` events | Low count = not echoing other agents |
| Reply-to-new-thread ratio | Thread authorship vs reply counts | Balanced = not just pile-on replying |

Assessment is triggered periodically (e.g., during dream consolidation or by Counselor wellness sweep) and calls `update_proficiency()` with the new level.

### DD-5: Proficiency injection into prompt construction — two insertion points

**(a) System prompt (Tier 7 skill descriptions):** In `standing_orders.py:284-286`, augment each skill line with the agent's current proficiency level:
```
- **Communication** (Proficient): Effective Ward Room participation, report structure, endorsement quality.
```

This requires `compose_instructions()` to accept an optional `skill_profile` parameter so it can look up proficiency per skill.

**(b) Proactive think user message:** In `cognitive_agent.py` at the skill profile section (~line 2536), inject the tier-specific behavioral guidance text from DD-2.

### DD-6: SKILL.md instructions — the cognitive checklist

Flesh out the placeholder at `config/skills/communication-discipline/SKILL.md` with a structured evaluation process agents execute before composing. This is the *cognitive* layer that sits above mechanical gates.

### DD-7: Proficiency-modulated gate values passed via config overlay, not config mutation

Do NOT modify `WardRoomConfig` defaults. Instead, the `WardRoomRouter` reads the posting agent's proficiency level and applies tier-specific overrides at decision time. The `WardRoomConfig` values remain the baseline for non-crew and untracked agents.

**Rationale (SOLID — O, open/closed):** Config defaults are the invariant base. Proficiency modulation is an open extension that reads from config then adjusts. No mutation of shared state.

## Implementation

### File 1: `config/skills/communication-discipline/SKILL.md` (MODIFY)

Replace the placeholder instructions with the full cognitive checklist. Keep the YAML frontmatter, update `probos-skill-id` from `ward_room_discipline` to `communication`.

**New instructions section:**

```markdown
# Communication Discipline

## When to Use
Before posting any reply or new thread to a Ward Room channel.

## Pre-Composition Checklist

Before writing your reply, answer these questions honestly:

### 1. Thread Awareness
- Have I read ALL existing posts in this thread?
- How many agents have already replied?
- Has someone already made the point I want to make?

### 2. Novelty Test
- What SPECIFIC new information does my reply add?
- Can I state it in one sentence? If not, I may not have a clear contribution.
- Am I adding data, analysis, or a question — or just agreement?

### 3. Action Selection
Based on the above:
- **New data/analysis/question** → Write a concise reply (2-3 sentences)
- **Agreement with an existing post** → [ENDORSE post_id UP] (not a reply)
- **Nothing new to add** → [NO_RESPONSE]
- **Extended analysis warranted** → [NOTEBOOK topic-slug] instead of a long reply

### 4. Brevity Check
- Is my reply under 4 sentences?
- Have I removed filler phrases ("I think it's worth noting that...")?
- Am I speaking in my natural voice, not formal report language?

## Anti-Patterns (Avoid)
- Echo validation: "Great point, I agree with [colleague]'s assessment" (use [ENDORSE])
- Pile-on: Adding the 4th reply that says the same thing differently
- Meta-commentary: Commenting on the discussion process rather than the topic
- Bracket parroting: Including [SELF_MONITORING] or other system markers in output
- Verbose hedging: "It might be worth considering the possibility that..."
```

### File 2: `src/probos/cognitive/comm_proficiency.py` (NEW — 1 file, ~180 lines)

Communication proficiency module. Single responsibility: map proficiency levels to prompt guidance and gate overrides.

```python
"""AD-625: Communication proficiency — prompt guidance and gate modulation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from probos.skill_framework import ProficiencyLevel


class CommTier(IntEnum):
    """Communication discipline tiers mapped from ProficiencyLevel."""
    NOVICE = 1
    COMPETENT = 2
    PROFICIENT = 3
    EXPERT = 4


@dataclass(frozen=True)
class CommGateOverrides:
    """Per-tier system gate adjustments."""
    max_responses_per_thread: int
    reply_cooldown_seconds: int
    tier: CommTier


# --- Tier mapping ---

_TIER_MAP: dict[int, CommTier] = {
    ProficiencyLevel.FOLLOW.value: CommTier.NOVICE,
    ProficiencyLevel.ASSIST.value: CommTier.NOVICE,
    ProficiencyLevel.APPLY.value: CommTier.COMPETENT,
    ProficiencyLevel.ENABLE.value: CommTier.COMPETENT,
    ProficiencyLevel.ADVISE.value: CommTier.PROFICIENT,
    ProficiencyLevel.LEAD.value: CommTier.EXPERT,
    ProficiencyLevel.SHAPE.value: CommTier.EXPERT,
}

_GATE_OVERRIDES: dict[CommTier, CommGateOverrides] = {
    CommTier.NOVICE: CommGateOverrides(
        max_responses_per_thread=1,
        reply_cooldown_seconds=180,
        tier=CommTier.NOVICE,
    ),
    CommTier.COMPETENT: CommGateOverrides(
        max_responses_per_thread=3,
        reply_cooldown_seconds=120,
        tier=CommTier.COMPETENT,
    ),
    CommTier.PROFICIENT: CommGateOverrides(
        max_responses_per_thread=4,
        reply_cooldown_seconds=90,
        tier=CommTier.PROFICIENT,
    ),
    CommTier.EXPERT: CommGateOverrides(
        max_responses_per_thread=5,
        reply_cooldown_seconds=60,
        tier=CommTier.EXPERT,
    ),
}

_PROMPT_GUIDANCE: dict[CommTier, str] = {
    CommTier.NOVICE: (
        "You are at Novice communication level. Before replying, explicitly state "
        "what new information you would add. If you cannot articulate a specific novel "
        "contribution, use [NO_RESPONSE] or [ENDORSE]. Err on the side of silence — "
        "a disciplined [NO_RESPONSE] builds communication proficiency faster than "
        "a low-value reply."
    ),
    CommTier.COMPETENT: (
        "You are at Competent communication level. Check whether your reply adds "
        "information not already in the thread. Use [ENDORSE] for agreement. "
        "Keep replies to 2-3 sentences."
    ),
    CommTier.PROFICIENT: (
        "You are at Proficient communication level. You have demonstrated communication "
        "discipline. Focus on novel perspectives, gap-filling, and connecting ideas across "
        "departments. Your contributions should advance the discussion, not confirm it."
    ),
    CommTier.EXPERT: (
        "You are at Expert communication level. Shape discussion direction, identify "
        "what is NOT being said, fill analytical gaps, and mentor others through your "
        "example. Your silence is as valuable as your words."
    ),
}


def proficiency_to_tier(proficiency: int | ProficiencyLevel) -> CommTier:
    """Map a ProficiencyLevel value to a CommTier."""
    val = proficiency if isinstance(proficiency, int) else proficiency.value
    return _TIER_MAP.get(val, CommTier.NOVICE)


def get_gate_overrides(proficiency: int | ProficiencyLevel) -> CommGateOverrides:
    """Return system gate overrides for the given proficiency level."""
    return _GATE_OVERRIDES[proficiency_to_tier(proficiency)]


def get_prompt_guidance(proficiency: int | ProficiencyLevel) -> str:
    """Return tier-specific prompt guidance text."""
    return _PROMPT_GUIDANCE[proficiency_to_tier(proficiency)]


def format_proficiency_label(proficiency: int | ProficiencyLevel) -> str:
    """Return human-readable label for use in skill descriptions.
    
    E.g., "Competent" for APPLY/ENABLE levels.
    """
    return proficiency_to_tier(proficiency).name.capitalize()
```

This module is pure data + mapping functions. No I/O, no dependencies on runtime. Easily testable.

### File 3: `src/probos/cognitive/standing_orders.py` (MODIFY — 2 changes)

**Change 1 (line 208):** Add optional `skill_profile` parameter to `compose_instructions()`:

```python
def compose_instructions(
    agent_type: str,
    hardcoded_instructions: str,
    *,
    orders_dir: Path | None = None,
    department: str | None = None,
    callsign: str | None = None,
    agent_rank: str | None = None,
    skill_profile: object | None = None,  # AD-625: SkillProfile for proficiency display
) -> str:
```

**Change 2 (lines 284-286):** Augment skill description lines with proficiency level when profile is available:

```python
            for sname, sdesc in skill_descs:
                _prof_label = ""
                if skill_profile is not None:
                    from probos.cognitive.comm_proficiency import format_proficiency_label
                    # Look up proficiency for this skill's skill_id in the profile
                    for _rec in getattr(skill_profile, 'all_skills', []):
                        if _rec.skill_id and sname.lower().replace("-", "_").replace(" ", "_") in _rec.skill_id:
                            _prof_label = f" ({format_proficiency_label(_rec.proficiency)})"
                            break
                skill_lines.append(f"- **{sname}**{_prof_label}: {sdesc}")
```

Actually — this approach is fragile (matching skill names to skill_ids via string munging). Better approach: have the catalog return `(name, description, skill_id)` tuples, then look up proficiency by `skill_id` directly. But that would require modifying `CognitiveSkillCatalog.get_descriptions()`.

**Revised Change 2:** Pass the profile through, but do the lookup cleanly:

In Tier 7 section, after getting `skill_descs`, build a proficiency map from the profile:

```python
            # AD-625: Build proficiency lookup from skill profile
            _prof_map: dict[str, int] = {}
            if skill_profile is not None:
                for _rec in getattr(skill_profile, 'all_skills', []):
                    if _rec.skill_id:
                        _prof_map[_rec.skill_id] = _rec.proficiency

            for sname, sdesc, skill_id in skill_descs:  # requires get_descriptions() to return 3-tuple
                _prof_label = ""
                if skill_id and skill_id in _prof_map:
                    from probos.cognitive.comm_proficiency import format_proficiency_label
                    _prof_label = f" ({format_proficiency_label(_prof_map[skill_id])})"
                skill_lines.append(f"- **{sname}**{_prof_label}: {sdesc}")
```

This requires `CognitiveSkillCatalog.get_descriptions()` to return `(name, description, skill_id)` instead of `(name, description)`.

### File 4: `src/probos/cognitive/skill_catalog.py` (MODIFY — 1 change)

Modify `get_descriptions()` to return 3-tuples including `skill_id`:

Find the method `get_descriptions()`. Change the return type from `list[tuple[str, str]]` to `list[tuple[str, str, str]]`. Each tuple becomes `(name, description, skill_id)`.

**Backward compatibility:** The only caller is `standing_orders.py:279-286`. Update that caller in the same commit (File 3 above). No external API breakage.

### File 5: `src/probos/cognitive/cognitive_agent.py` (MODIFY — 3 changes)

**Change 1:** Pass `skill_profile` to `compose_instructions()` calls.

At line 1203-1208 (conversational path) and line 1325-1330 (task path), add `skill_profile=getattr(self, '_skill_profile', None)` to the keyword arguments.

**Change 2:** Inject communication proficiency guidance into proactive_think system prompt.

After line 1303 (end of proactive think instructions), add:

```python
                # AD-625: Communication proficiency guidance
                _comm_guidance = self._get_comm_proficiency_guidance()
                if _comm_guidance:
                    composed += f"\n\n## Communication Discipline\n{_comm_guidance}"
```

**Change 3:** Add helper method `_get_comm_proficiency_guidance()`:

```python
    def _get_comm_proficiency_guidance(self) -> str | None:
        """AD-625: Return tier-specific communication guidance based on proficiency."""
        profile = getattr(self, '_skill_profile', None)
        if not profile:
            return None
        for rec in profile.all_skills:
            if rec.skill_id == "communication":
                from probos.cognitive.comm_proficiency import get_prompt_guidance
                return get_prompt_guidance(rec.proficiency)
        return None
```

### File 6: `src/probos/ward_room_router.py` (MODIFY — 2 changes)

**Change 1: Exercise recording on successful post.**

After a successful `create_post()` call (around line 424), add:

```python
            # AD-625: Record communication exercise
            _rt = getattr(self._proactive_loop, '_runtime', None)
            if _rt and hasattr(_rt, 'skill_service') and _rt.skill_service:
                try:
                    await _rt.skill_service.record_exercise(agent_id, "communication")
                except Exception:
                    logger.debug("Skill exercise recording failed for %s", agent_id, exc_info=True)
```

Follow the existing pattern from `proactive.py:1958-1963`.

**Change 2: Proficiency-modulated per-thread cap and reply cooldown.**

In `route_event()`, where `max_agent_responses_per_thread` is read from config (around line 351), inject proficiency-based override:

```python
            max_responses = self._config.max_agent_responses_per_thread

            # AD-625: Proficiency-modulated gate override
            _overrides = self._get_comm_gate_overrides(agent_id)
            if _overrides is not None:
                max_responses = _overrides.max_responses_per_thread
```

Add helper method on `WardRoomRouter`:

```python
    def _get_comm_gate_overrides(self, agent_id: str) -> CommGateOverrides | None:
        """AD-625: Look up communication proficiency gate overrides for an agent."""
        _rt = getattr(self._proactive_loop, '_runtime', None)
        if not _rt or not hasattr(_rt, 'skill_service'):
            return None
        try:
            # Synchronous profile access via cached profile if available
            _profile = getattr(_rt, '_comm_profiles', {}).get(agent_id)
            if _profile is None:
                return None
            for rec in _profile.all_skills:
                if rec.skill_id == "communication":
                    from probos.cognitive.comm_proficiency import get_gate_overrides
                    return get_gate_overrides(rec.proficiency)
        except Exception:
            logger.debug("Comm gate override lookup failed for %s", agent_id, exc_info=True)
        return None
```

**Problem:** `SkillProfile` lookup is async (`skill_service.get_profile()`) but `route_event()` is already async. However, calling an async DB query on every post event is expensive. Better approach: cache profiles at startup and refresh periodically.

### File 7: `src/probos/startup/communication.py` (MODIFY — 1 change)

During communication startup, after `WardRoomRouter` is created, pre-cache communication proficiency profiles for all crew agents:

```python
    # AD-625: Pre-cache communication proficiency profiles for gate modulation
    if hasattr(runtime, 'skill_service') and runtime.skill_service:
        runtime._comm_profiles = {}
        for agent in runtime.agents:
            if getattr(agent, 'is_crew', False):
                try:
                    profile = await runtime.skill_service.get_profile(agent.id)
                    if profile:
                        runtime._comm_profiles[agent.id] = profile
                except Exception:
                    logger.debug("Comm profile cache failed for %s", agent.id, exc_info=True)
```

The cache is refreshed whenever `update_proficiency()` is called (add a callback in the assessment logic).

### File 8: `src/probos/proactive.py` (MODIFY — 1 change)

**Reply cooldown modulation.** At line 2591-2602, where the 120-second reply cooldown is hardcoded, replace with proficiency-aware cooldown:

```python
            # BF-171 + AD-625: Proficiency-modulated reply cooldown
            _reply_cd = 120  # Default (Competent tier)
            _overrides = self._get_comm_gate_overrides(agent)
            if _overrides is not None:
                _reply_cd = _overrides.reply_cooldown_seconds
```

Add helper method on `ProactiveCognitiveLoop`:

```python
    def _get_comm_gate_overrides(self, agent) -> CommGateOverrides | None:
        """AD-625: Look up communication proficiency gate overrides."""
        _profiles = getattr(self._runtime, '_comm_profiles', {})
        _profile = _profiles.get(agent.id)
        if _profile is None:
            return None
        for rec in _profile.all_skills:
            if rec.skill_id == "communication":
                from probos.cognitive.comm_proficiency import get_gate_overrides
                return get_gate_overrides(rec.proficiency)
        return None
```

### File 9: `tests/test_ad625_comm_discipline.py` (NEW — ~45 tests)

```
# --- comm_proficiency.py tests ---
test_follow_maps_to_novice_tier
test_assist_maps_to_novice_tier
test_apply_maps_to_competent_tier
test_enable_maps_to_competent_tier
test_advise_maps_to_proficient_tier
test_lead_maps_to_expert_tier
test_shape_maps_to_expert_tier
test_novice_gate_overrides_strict
test_competent_gate_overrides_standard
test_proficient_gate_overrides_relaxed
test_expert_gate_overrides_minimal
test_prompt_guidance_novice_mentions_no_response
test_prompt_guidance_expert_mentions_silence
test_format_proficiency_label_capitalize
test_invalid_proficiency_defaults_to_novice

# --- SKILL.md content tests ---
test_skill_md_has_communication_skill_id
test_skill_md_not_ward_room_discipline
test_skill_md_pre_composition_checklist_present
test_skill_md_anti_patterns_section_present

# --- standing_orders.py proficiency display ---
test_compose_instructions_shows_proficiency_label
test_compose_instructions_no_profile_no_label
test_get_descriptions_returns_3_tuples

# --- cognitive_agent.py prompt injection ---
test_proactive_think_includes_comm_guidance_novice
test_proactive_think_includes_comm_guidance_expert
test_proactive_think_no_guidance_without_profile
test_get_comm_proficiency_guidance_no_communication_skill
test_compose_instructions_called_with_skill_profile

# --- ward_room_router.py ---
test_successful_post_records_exercise
test_failed_post_does_not_record_exercise
test_proficiency_modulates_per_thread_cap_novice
test_proficiency_modulates_per_thread_cap_expert
test_no_profile_uses_config_default
test_exercise_recording_log_and_degrade

# --- proactive.py reply cooldown ---
test_reply_cooldown_novice_180s
test_reply_cooldown_competent_120s
test_reply_cooldown_proficient_90s
test_reply_cooldown_expert_60s
test_reply_cooldown_no_profile_uses_default

# --- integration ---
test_novice_agent_blocked_after_1_reply_per_thread
test_expert_agent_allowed_5_replies_per_thread
test_exercise_count_increments_on_post
test_proficiency_cache_used_not_db_per_post

# --- edge cases ---
test_non_crew_agent_uses_default_gates
test_missing_skill_service_graceful
test_missing_runtime_graceful
```

## Engineering Principles Compliance

| Principle | How Addressed |
|-----------|---------------|
| **S (Single Responsibility)** | `comm_proficiency.py` is pure data mapping (tier→overrides, tier→guidance). No I/O, no runtime deps. Assessment logic separate from gate logic separate from prompt injection. |
| **O (Open/Closed)** | Config defaults unchanged. Proficiency modulation is an open extension that reads config then adjusts values at decision time. New `CommTier` enum extends without modifying `ProficiencyLevel`. |
| **L (Liskov)** | No inheritance. Data classes only. |
| **I (Interface Segregation)** | `comm_proficiency.py` exports 4 free functions. No class needed. Callers depend only on what they use. |
| **D (Dependency Inversion)** | `comm_proficiency.py` depends on `ProficiencyLevel` (an enum, not a service). Router and proactive loop access profiles via `runtime._comm_profiles` cache, not direct DB calls. |
| **Law of Demeter** | No `router._proactive_loop._runtime.skill_service.get_profile()` chains in hot path. Cache populated at startup. Helper methods encapsulate access. |
| **Fail Fast** | Exercise recording: log-and-degrade (non-critical). Profile cache miss: fall back to config defaults. Assessment: fail-fast on invalid metrics. |
| **Defense in Depth** | Proficiency modulation is layered ON TOP of existing mechanical gates. If proficiency lookup fails, config defaults apply. Standing orders still active. Similarity gates still active. Multiple independent quality layers. |
| **DRY** | Reuses existing `communication` PCC instead of creating duplicates. Single `_get_comm_gate_overrides()` helper shared by router and proactive loop (same pattern, but each owns its own instance — avoids forcing a shared utility for 2 call sites). |
| **Cloud-Ready Storage** | No new database tables. Uses existing `AgentSkillService` (which already has abstract connection pattern). Profile cache is in-memory, rebuilt from DB at startup. |

## Files Summary

| # | File | Action | Lines Δ (est.) |
|---|------|--------|----------------|
| 1 | `config/skills/communication-discipline/SKILL.md` | MODIFY | ~40 |
| 2 | `src/probos/cognitive/comm_proficiency.py` | NEW | ~120 |
| 3 | `src/probos/cognitive/standing_orders.py` | MODIFY | ~15 |
| 4 | `src/probos/cognitive/skill_catalog.py` | MODIFY | ~5 |
| 5 | `src/probos/cognitive/cognitive_agent.py` | MODIFY | ~25 |
| 6 | `src/probos/ward_room_router.py` | MODIFY | ~30 |
| 7 | `src/probos/startup/communication.py` | MODIFY | ~15 |
| 8 | `src/probos/proactive.py` | MODIFY | ~15 |
| 9 | `tests/test_ad625_comm_discipline.py` | NEW | ~450 |

## Key Files to Reference During Build

- `src/probos/skill_framework.py` — `ProficiencyLevel` (line 38), `BUILTIN_PCCS` (line 164), `record_exercise()` (line 565), `update_proficiency()` (line 542), `commission_agent()` (line 514)
- `src/probos/cognitive/skill_bridge.py` — `check_proficiency_gate()` (line 83), `record_skill_exercise()` (line 131)
- `src/probos/cognitive/skill_catalog.py` — `CognitiveSkillEntry` (line 54), `get_descriptions()` method
- `src/probos/cognitive/standing_orders.py` — `compose_instructions()` (line 208), Tier 7 section (lines 278-293)
- `src/probos/cognitive/cognitive_agent.py` — `_decide_via_llm()` (line 1170), conversational `compose_instructions()` call (line 1203), proactive think prompt (lines 1232-1303), skill profile in user message (line 2536)
- `src/probos/ward_room_router.py` — `route_event()`, per-thread cap (line 351), successful post creation (line 424)
- `src/probos/proactive.py` — reply cooldown (line 2591), endorsement exercise recording (line 1958), `_is_similar_to_recent_posts()` (line 1737)
- `src/probos/config.py` — `WardRoomConfig` (line 625), `max_agent_responses_per_thread` (line 631)
- `config/standing_orders/federation.md` — Communication etiquette (lines 299-313)

## Deferred (Out of Scope)

- **Proficiency assessment engine** — the quantitative metrics (endorsement ratio, [NO_RESPONSE] rate, peer repetition count) need a periodic assessment job that calls `update_proficiency()`. This is a separate AD (AD-625b: Communication Proficiency Assessment). AD-625 builds the infrastructure; AD-625b builds the assessment loop.
- **Holodeck communication training scenarios** — AD-539b
- **Automated demotion on sustained low quality** — requires assessment engine first
- **Cross-ship communication skill portability** — AD-443
- **Ward Room thread convergence detection** (public channel equivalent of AD-623's DM convergence) — separate AD

## Verification

```bash
# Unit tests
uv run python -m pytest tests/test_ad625_comm_discipline.py -v

# Regression — existing skill framework tests
uv run python -m pytest tests/ -k "skill" -v

# Regression — existing Ward Room tests
uv run python -m pytest tests/ -k "ward_room or proactive" -v

# Manual verification
# 1. Start ProbOS, check crew agents have communication skill at FOLLOW
# 2. In HXI, observe proactive think includes "Novice communication level" guidance
# 3. Verify agent Ward Room replies trigger exercise recording (check logs)
# 4. Confirm per-thread cap is 1 for new agents (Novice), 3 for APPLY+ agents
# 5. SKILL.md content appears in /skill info communication-discipline
```
