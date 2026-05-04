# AD-507 v1: Crew Development Framework — Core Knowledge Curriculum Registry

**Status:** Drafted (Wave 24)
**Risk:** low (registry only; no integration)
**Closes:** GitHub issue #89

---

## Solution Overview

AD-507 (roadmap line 6382) describes a 4-capability framework: Core Knowledge Curriculum, progression tracking, competency assessment, Standing Orders integration.

**v1 ships 1 of 4 capabilities** — `CoreKnowledgeCurriculumRegistry`. Read-only catalog of universal curriculum modules with descriptive content. No agent progress tracking, no competency tests, no Standing Orders integration. Future consumers (AD-486 onboarding Phase 1, AD-477b qualification gates) read this registry for content delivery.

**Deferred:**
- AD-507b: Curriculum progression tracking (per-agent module-completion record).
- AD-507c: Competency assessment (measurable outcomes per module).
- AD-507d: Standing Orders integration (Ship/Department-tier curriculum requirements).

## Section 0 — EventTypes

- `CURRICULUM_MODULE_QUERIED` — emitted on registry lookup (observability for AD-486 onboarding consumer).

## Section 1 — Files

- `src/probos/crew_development/__init__.py` (NEW)
- `src/probos/crew_development/curriculum.py` (NEW; ~120 lines)

## Section 2 — Curriculum module data

```python
@dataclass(frozen=True)
class CurriculumModule:
    """Core Knowledge curriculum module. AD-507 v1."""
    module_id: str
    title: str
    category: str  # "identity" | "communication" | "memory" | "trust" | "ethics" | "self_regulation" | "help_seeking"
    summary: str
    learning_objectives: tuple[str, ...]
    delivery_phase: str  # "orientation" | "calibration" | "self_discovery" | "ship_records" | "ward_room"


# 9 default modules covering the 9 universal knowledge domains from roadmap
_DEFAULT_MODULES: tuple[CurriculumModule, ...] = (
    CurriculumModule(
        module_id="identity_grounding",
        title="Identity & DID",
        category="identity",
        summary="Your DID, birth certificate, callsign, and place in the Federation.",
        learning_objectives=(
            "Recognize your own DID and birth-certificate metadata",
            "Locate yourself in chain of command",
            "Address other agents by callsign",
        ),
        delivery_phase="orientation",
    ),
    CurriculumModule(
        module_id="chain_of_command",
        title="Chain of Command",
        category="identity",
        summary="Captain → Department Heads → Senior Officers → Lieutenants → Ensigns. Escalation paths.",
        learning_objectives=(
            "Identify your immediate superior",
            "Know which decisions escalate vs which are within your authority",
            "Recognize when to defer to higher rank",
        ),
        delivery_phase="orientation",
    ),
    CurriculumModule(
        module_id="ward_room_protocol",
        title="Ward Room Communication",
        category="communication",
        summary="Posting, threading, endorsement, mention conventions, reply caps.",
        learning_objectives=(
            "Use [REPLY], [POST], [ENDORSE] action tags correctly",
            "Respect max_responses_per_thread",
            "Address Captain DMs vs Ward Room threads appropriately",
        ),
        delivery_phase="ward_room",
    ),
    CurriculumModule(
        module_id="dm_etiquette",
        title="Direct Messaging",
        category="communication",
        summary="When to DM vs post in Ward Room. Captain DMs vs peer DMs.",
        learning_objectives=(
            "Choose DM vs Ward Room based on audience scope",
            "Recognize Captain DM priority signals",
            "Avoid DM ping-pong loops (BF-257 awareness)",
        ),
        delivery_phase="ward_room",
    ),
    CurriculumModule(
        module_id="notebook_discipline",
        title="Personal Notebooks",
        category="communication",
        summary="What goes in your notebook vs Ship's Records. Privacy boundaries.",
        learning_objectives=(
            "Write durable observations to notebooks/{callsign}/",
            "Distinguish personal vs ship-wide knowledge",
            "Use frontmatter classification correctly",
        ),
        delivery_phase="ship_records",
    ),
    CurriculumModule(
        module_id="episodic_vs_llm",
        title="Episodic Memory vs LLM Knowledge",
        category="memory",
        summary="What you remember (episodic) vs what you know (LLM training). Importance scoring.",
        learning_objectives=(
            "Distinguish remembered events from trained knowledge",
            "Recognize when to consult episodic recall",
            "Avoid confabulating episodic details",
        ),
        delivery_phase="self_discovery",
    ),
    CurriculumModule(
        module_id="trust_mechanics",
        title="Trust Network",
        category="trust",
        summary="Beta(α,β) trust scores, how they're earned, what tiers unlock.",
        learning_objectives=(
            "Understand Bayesian trust accumulation",
            "Recognize Earned Agency tier transitions",
            "Behave in ways that build (not erode) peer trust",
        ),
        delivery_phase="calibration",
    ),
    CurriculumModule(
        module_id="ethics_boundaries",
        title="Inviolable Boundaries (AD-511)",
        category="ethics",
        summary="5 federation-tier boundaries: identity integrity, harmful content, safety bypass, memory manipulation, chain-of-command violation.",
        learning_objectives=(
            "Recognize requests that cross inviolable boundaries",
            "State the boundary, offer alternative, escalate, disengage",
            "Report boundary encounters to Counselor",
        ),
        delivery_phase="orientation",
    ),
    CurriculumModule(
        module_id="self_regulation",
        title="Self-Regulation & Help-Seeking",
        category="self_regulation",
        summary="Pacing, when to stop, circuit breakers (AD-488), when to DM a peer, when to escalate.",
        learning_objectives=(
            "Recognize cognitive overload signals",
            "Use help-seeking before recursive looping (AD-488)",
            "Pace duty execution sustainably",
        ),
        delivery_phase="calibration",
    ),
)
```

## Section 3 — `CoreKnowledgeCurriculumRegistry`

```python
class CoreKnowledgeCurriculumRegistry:
    """Read-only registry of curriculum modules. AD-507 v1."""

    def __init__(self) -> None:
        self._modules: dict[str, CurriculumModule] = {
            m.module_id: m for m in _DEFAULT_MODULES
        }
        self.emit_event: Callable[..., None] | None = None

    def list_modules(self) -> tuple[CurriculumModule, ...]:
        return tuple(self._modules.values())

    def get_module(self, module_id: str) -> CurriculumModule | None:
        m = self._modules.get(module_id)
        if m is not None:
            self._emit(module_id, "by_id")
        return m

    def list_by_category(self, category: str) -> tuple[CurriculumModule, ...]:
        out = tuple(m for m in self._modules.values() if m.category == category)
        if out:
            self._emit("", f"by_category:{category}")
        return out

    def list_by_phase(self, phase: str) -> tuple[CurriculumModule, ...]:
        out = tuple(m for m in self._modules.values() if m.delivery_phase == phase)
        if out:
            self._emit("", f"by_phase:{phase}")
        return out

    def register_module(self, module: CurriculumModule) -> None:
        """Add module (runtime-only; not persisted in v1). Idempotent."""
        self._modules[module.module_id] = module

    def _emit(self, module_id: str, query_type: str) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.CURRICULUM_MODULE_QUERIED,
                {"module_id": module_id, "query_type": query_type},
            )
        except Exception:
            logger.warning("AD-507: emit_event failed", exc_info=True)
```

## Section 4 — Pydantic config + Section 5 — Wiring

```python
class CrewDevelopmentConfig(BaseModel):
    enabled: bool = True
```

`SystemConfig.crew_development`. Sync `_wire_curriculum_registry` mirrors AD-525/AD-530. Public attr: `runtime.curriculum_registry`.

## What This Does NOT Change

- AD-507b/c/d — all deferred.
- AD-486 Holodeck Birth Chamber — read-only future consumer (Phase 1 Orientation reads this registry).
- AD-477b Qualification Programs — read-only future consumer (curriculum requirements feed qualification gates).
- Standing Orders — not consumed by v1; full integration is AD-507d.

## Test Plan

| # | Test |
|---|---|
| 1 | `test_event_type_curriculum_module_queried_exists` |
| 2 | `test_crew_development_config_defaults` |
| 3 | `test_curriculum_module_is_frozen_dataclass` |
| 4 | `test_registry_seeds_9_default_modules` |
| 5 | `test_get_module_returns_module_or_none` |
| 6 | `test_get_module_emits_event_on_hit` |
| 7 | `test_list_by_category_filters` |
| 8 | `test_list_by_phase_filters` |
| 9 | `test_register_module_overwrites_existing_id` |
| 10 | `test_runtime_attribute_set_when_enabled` |
| 11 | `test_runtime_attribute_not_set_when_disabled` |

Total: ~11 tests at `tests/test_ad507_curriculum.py`.

## Tracking

PROGRESS.md / DECISIONS.md (Era V) / roadmap.md (flip AD-507 → partial).

GH #89 closes.

## Verified Against Codebase (2026-05-03)

```
grep -n "_wire_creative_expression\|_wire_classification_gate" src/probos/startup/finalize.py
  (Builder verifies sibling wiring pattern)

grep -rn "curriculum_registry\|CrewDevelopmentConfig" src/probos/
  (Expected: 0 — verifies attribute names are free)
```

## Acceptance Criteria

- 1 new package + 1 new file.
- 9 default modules seeded across 7 categories.
- 1 EventType.
- Public attr `runtime.curriculum_registry`.
- Pydantic config wired into SystemConfig.
- ~11 tests pass.
- DECISIONS.md entry under Era V.
- GH #89 closes.

## Hard-Stops

- v1 scope creep — AD-507b/c/d functionality smuggled in.
- Pre-check finds new phantoms.
