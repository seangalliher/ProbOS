# AD-525: Agent Creative Expression v1 — Skills Inventory + Records Output

**Status:** Drafted (Wave 16)
**Risk:** medium (new agent-facing surface; bounded scope via aggressive pre-deferral)
**Depends on:** RecordsStore (shipped), Earned Agency (AD-357 shipped); AD-434 (Archive) and Holodeck NOT required for v1
**Closes:** GitHub issue #100

---

## Solution Overview

AD-525 in roadmap.md (line 2937) lists 5 capabilities for agent creative expression: Skills Inventory, Time Allocation, Records Output, Code-as-Art, Cultural Emergence. Heavy interaction surface; large scope.

**v1 ships 2 of 5 capabilities** (per convention #14 aggressive pre-deferral) — the bounded, generative-surface capabilities with no infrastructure ask:

1. **Creative Skills Inventory** — `CreativeSkillsRegistry` exposes the open-ended catalog of creative skills (Creative Writing, Technical Writing, Code as Art, Visual Design, Music Composition, Philosophy, Historiography, Comedy/Satire) with per-skill personality affinity (Big Five trait alignment). Per-agent affinity scoring via existing `CrewProfile` Big Five fields. Read-only surface — agents query "what creative skills suit me?"

2. **Creative Output to Ship's Records** — `CreativeOutputWriter` writes agent creative works to `creative/{callsign}/{topic_slug}.md` via existing `RecordsStore.write_entry()`. Frontmatter: `type: creative`, `medium`, `author`, `department`. Default classification `ship` (shared culture). Mirror existing notebook pattern at `notebooks/{callsign}/{topic_slug}.md` (verified at proactive.py:2111).

**Deferred to grandchildren:**

- AD-525b: Creative time allocation gated by Earned Agency rank. Forcing function: when v1 surfaces show agents using `CreativeOutputWriter` and capacity policy needs to enforce limits.
- AD-525c: Code-as-creative-expression — relaxed-consensus path for non-duty BuildSpec runs. Forcing function: a future BuildSpec extension that distinguishes "creative" from "duty" runs.
- AD-525d: Cultural emergence detection — cross-agent creative-work analysis (shared references, aesthetic traditions, generational influence). Requires Archive (AD-434) + multi-agent emergence detection. Forcing function: AD-434 ships + creative corpus reaches threshold (e.g., 50+ works).
- AD-525e: Creative collaboration — co-authoring, multi-agent creative threads. Depends on Ward Room thread integration; defer until cultural-emergence baseline exists.

## Dependencies

- `runtime.records_store` — read-only consumer (`write_entry()` at records_store.py:89; verified signature: author, path, content, message, *, classification, status, department, topic, tags, metrics).
- `runtime.profile_store` — read-only consumer for Big Five trait fields (verified at acm.py:300; real attribute name is `profile_store` NOT `crew_profile_store`).
- `RecordsStore` git-backed write — already exists; AD-525 just adds a new path prefix `creative/`.
- Earned Agency — referenced for AD-525b deferral context, NOT required for v1.

All reads from existing surfaces; one new file path namespace under `creative/`.

## Sections

### Section 0 — EventTypes

- `CREATIVE_WORK_PUBLISHED` — emitted when a creative work is written to Ship's Records.
- `CREATIVE_SKILL_AFFINITY_QUERIED` — emitted when an agent queries skill affinity (observability for AD-525b time-allocation forcing function).

Verify no collision with events.py post-Wave-15.

### Section 1 — Create `src/probos/creative/` package

- `src/probos/creative/__init__.py`
- `src/probos/creative/skills_registry.py`
- `src/probos/creative/output_writer.py`

Per Wave 8/9/12/14 precedents — owns directory creation.

### Section 2 — `CreativeSkill` frozen dataclass

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class CreativeSkill:
    """A creative skill agents can adopt. AD-525 v1."""
    skill_id: str  # e.g., "creative_writing"
    name: str  # e.g., "Creative Writing"
    medium: tuple[str, ...]  # e.g., ("prose", "poetry", "journal")
    # Big Five trait affinities — values 0.0-1.0; omitted traits default to 0.5 (neutral)
    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5  # lower neuroticism = better fit for some skills (e.g., Music Composition)
```

### Section 3 — `CreativeSkillsRegistry`

```python
class CreativeSkillsRegistry:
    """Catalog of creative skills with per-skill personality affinity. Read-only surface.

    AD-525 v1. Default catalog seeded from roadmap.md table (8 skills); extensible via
    register_skill() (no persistence in v1 — runtime-only).
    """

    DEFAULT_SKILLS: tuple[CreativeSkill, ...] = (
        CreativeSkill("creative_writing", "Creative Writing", ("prose", "poetry", "journal"), openness=0.85),
        CreativeSkill("technical_writing", "Technical Writing", ("documentation", "tutorial", "guide"), conscientiousness=0.85),
        CreativeSkill("code_as_art", "Code as Art", ("generative", "visualization"), openness=0.80),
        CreativeSkill("visual_design", "Visual Design", ("svg", "diagram", "schematic"), openness=0.80),
        CreativeSkill("music_composition", "Music Composition", ("algorithmic", "procedural"), openness=0.80, neuroticism=0.30),
        CreativeSkill("philosophy", "Philosophy", ("essay", "analysis"), openness=0.85, conscientiousness=0.80),
        CreativeSkill("historiography", "Historiography", ("history", "chronicle"), conscientiousness=0.85),
        CreativeSkill("comedy_satire", "Comedy/Satire", ("humor", "observational"), openness=0.75, extraversion=0.80),
    )

    def __init__(self) -> None:
        self._skills: dict[str, CreativeSkill] = {s.skill_id: s for s in self.DEFAULT_SKILLS}
        self._emit_event_fn: Callable[..., None] | None = None  # late-bind setter

    def list_skills(self) -> tuple[CreativeSkill, ...]:
        """Return all registered skills."""
        return tuple(self._skills.values())

    def get_skill(self, skill_id: str) -> CreativeSkill | None:
        """Return skill by id; None if absent."""
        return self._skills.get(skill_id)

    def affinity_score(self, skill_id: str, traits: dict[str, float]) -> float:
        """Compute affinity score for an agent's Big Five traits against a skill.

        Args:
            skill_id: The creative skill to score.
            traits: Agent's Big Five trait values, keyed by trait name (openness,
                conscientiousness, extraversion, agreeableness, neuroticism), values 0.0-1.0.

        Returns:
            Affinity score 0.0-1.0. Higher = better fit. Computed as 1.0 - mean(|trait - skill_affinity|)
            across all 5 Big Five dimensions. Returns 0.0 if skill_id absent or traits empty.

        Emits CREATIVE_SKILL_AFFINITY_QUERIED with {agent_traits, skill_id, score}.
        """

    def top_skills_for(self, traits: dict[str, float], k: int = 3) -> list[tuple[CreativeSkill, float]]:
        """Return top k skills by affinity score, descending.

        Returns empty list if traits is empty or k <= 0.
        """

    def register_skill(self, skill: CreativeSkill) -> None:
        """Add a skill to the registry. Idempotent on skill_id (overwrites)."""
```

### Section 4 — `CreativeOutputWriter`

```python
class CreativeOutputWriter:
    """Writes agent creative works to Ship's Records under creative/{callsign}/. AD-525 v1.

    Mirrors notebook pattern at notebooks/{callsign}/{topic_slug}.md (proactive.py:2111).
    Default classification: ship (shared culture per AD-525 design).
    """

    def __init__(
        self,
        runtime: Any,
        config: CreativeExpressionConfig,
        *,
        records_store: Any | None = None,  # injected; falls back to runtime.records_store
    ) -> None:
        self._runtime = runtime
        self._config = config
        self._records_store = records_store
        self._emit_event_fn: Callable[..., None] | None = None

    async def publish(
        self,
        author_callsign: str,
        topic_slug: str,
        content: str,
        *,
        medium: str,
        skill_id: str,
        department: str = "",
        classification: str = "ship",
    ) -> str:
        """Write creative work. Returns relative path within Ship's Records.

        Args:
            author_callsign: Agent's callsign (used in path: creative/{callsign}/{topic_slug}.md).
            topic_slug: URL-safe slug for the work title.
            content: The creative work itself (Markdown body).
            medium: One of the skill's media (e.g., "poetry", "essay", "diagram").
            skill_id: References CreativeSkillsRegistry skill_id.
            department: Optional department of author (for frontmatter).
            classification: Ship/department/private; default ship per AD-525 design.

        Returns:
            Relative path "creative/{callsign}/{topic_slug}.md".

        Emits CREATIVE_WORK_PUBLISHED with {author, skill_id, medium, path, classification}.

        Raises:
            CreativeOutputError: if records_store unavailable or write fails.
        """

    async def list_works_by_author(self, author_callsign: str) -> list[str]:
        """Return relative paths of all creative works by an author."""
```

### Section 5 — Pydantic config

```python
class CreativeExpressionConfig(BaseModel):
    """Configuration for AD-525 v1 (Skills Inventory + Records Output)."""
    enabled: bool = True
    default_classification: str = "ship"  # one of: ship, department, private
    skills_catalog: list[str] = Field(default_factory=list)  # additional skill_ids to load via plugin (deferred); v1 ignores
```

Wire into `SystemConfig.creative_expression: CreativeExpressionConfig = Field(default_factory=CreativeExpressionConfig)`.

### Section 6 — Runtime wiring (finalize.py)

Add to `_wire_creative_expression`:

```python
async def _wire_creative_expression(*, runtime, config) -> bool:
    """AD-525 v1: Wire CreativeSkillsRegistry + CreativeOutputWriter."""
    cfg = getattr(config, "creative_expression", None)
    if not cfg or not cfg.enabled:
        return False
    runtime.creative_skills_registry = CreativeSkillsRegistry()
    runtime.creative_skills_registry._emit_event_fn = runtime.emit_event
    runtime.creative_output_writer = CreativeOutputWriter(runtime, cfg)
    runtime.creative_output_writer._emit_event_fn = runtime.emit_event
    logger.info(
        "AD-525: Creative Expression v1 initialized (default_classification=%s; %d skills)",
        cfg.default_classification, len(runtime.creative_skills_registry.list_skills()),
    )
    return True
```

Public attributes (Wave 5 convention #1):
- `runtime.creative_skills_registry`
- `runtime.creative_output_writer`

Both NO leading underscore.

## What This Does NOT Change

- AD-525b time-allocation rules — deferred. v1 has no rate limits or rank gates.
- AD-525c code-as-creative — deferred. CreativeOutputWriter writes Markdown only in v1; code-art runs through existing BuildSpec infrastructure.
- AD-525d cultural-emergence detection — deferred (depends on Archive AD-434 + corpus threshold).
- AD-525e creative collaboration — deferred. v1 publishes single-author works only.
- Existing notebook path (`notebooks/{callsign}/`) — untouched. Creative works live at `creative/{callsign}/`.
- Earned Agency rank gating — referenced for AD-525b deferral context only; v1 doesn't gate.
- Holodeck integration — not required.

## Test Plan

| # | Test | Purpose |
|---|---|---|
| 1 | `test_event_type_creative_work_published_exists` | Section 0 surface |
| 2 | `test_event_type_creative_skill_affinity_queried_exists` | Section 0 surface |
| 3 | `test_creative_expression_config_defaults` | Pydantic defaults |
| 4 | `test_creative_skill_is_frozen_dataclass` | Section 2 contract |
| 5 | `test_skills_registry_seeds_8_default_skills` | Catalog completeness |
| 6 | `test_skills_registry_get_skill_returns_skill_or_none` | Lookup behavior |
| 7 | `test_affinity_score_returns_zero_for_empty_traits` | Edge case |
| 8 | `test_affinity_score_returns_zero_for_unknown_skill` | Edge case |
| 9 | `test_affinity_score_high_for_aligned_traits` | Happy path: high openness → high creative_writing affinity |
| 10 | `test_affinity_score_emits_queried_event` | EventType emission |
| 11 | `test_top_skills_for_returns_descending_order` | Ranking behavior |
| 12 | `test_top_skills_for_respects_k_limit` | Bound check |
| 13 | `test_register_skill_overwrites_existing_id` | Idempotency |
| 14 | `test_publish_writes_to_creative_path` | Path format `creative/{callsign}/{topic_slug}.md` |
| 15 | `test_publish_emits_published_event` | EventType emission |
| 16 | `test_publish_uses_default_classification_ship` | Config-driven default |
| 17 | `test_publish_raises_when_records_store_unavailable` | Error path |
| 18 | `test_list_works_by_author_returns_only_authors_works` | Filter behavior |
| 19 | `test_runtime_attributes_set_when_enabled` | Public-attribute wiring |
| 20 | `test_runtime_attributes_not_set_when_disabled` | Disabled config skips wiring |

Total: ~20 tests.

## Tracking

1. **PROGRESS.md:** prepend AD-525 entry.
2. **DECISIONS.md:** add entry under Era V:

```markdown
### AD-525: Agent Creative Expression v1 (Skills Inventory + Records Output) (2026-05-03)

**Problem:** Agents operate purely in duty mode — every action serves a functional purpose. Personality framework (Big Five traits) exists but has no creative outlet. Roadmap describes 5 capabilities (Skills Inventory + Time Allocation + Records Output + Code-as-Art + Cultural Emergence). Heavy interaction surface; large scope.

**Decision:** v1 ships 2 of 5 capabilities — the bounded generative surfaces with no infrastructure ask:
- `CreativeSkillsRegistry` — open-ended catalog of 8 default creative skills (Creative Writing, Technical Writing, Code as Art, Visual Design, Music Composition, Philosophy, Historiography, Comedy/Satire). Per-skill Big Five trait affinity. Read-only `affinity_score(skill_id, traits)` + `top_skills_for(traits, k)`. Extensible via `register_skill()` (runtime-only; no persistence in v1).
- `CreativeOutputWriter` — publishes agent creative works to `creative/{callsign}/{topic_slug}.md` via existing `RecordsStore.write_entry`. Default classification `ship` (shared culture per design). Frontmatter includes `type: creative`, `medium`, `author`, `department`.

Both are read-only consumers of existing runtime surfaces (`records_store`, `crew_profile_store`); no writes to existing data. Public attributes (no underscore per Wave 5 convention #1).

**Why:** Generative + bounded. Skills Inventory is a stateless registry. Output Writer mirrors notebook pattern (proactive.py:2111). No rate limits, no rank gating, no multi-agent collaboration in v1 — those are AD-525b/c/d/e territory with explicit forcing functions.

**Deferred:**
- AD-525b: Time-allocation rules gated by Earned Agency rank. Forcing function: v1 surfaces show agents using CreativeOutputWriter and capacity policy needs to enforce limits.
- AD-525c: Code-as-creative-expression — relaxed-consensus path for non-duty BuildSpec runs.
- AD-525d: Cultural emergence detection — depends on Archive (AD-434) + corpus threshold (~50+ works).
- AD-525e: Creative collaboration — co-authoring; depends on cultural-emergence baseline.

**Cross-links:** AD-357 (Earned Agency — eventual gate), AD-434 (Archive — eventual cultural-emergence consumer), AD-526 (Recreation — Combo A AD-526c + Combo C AD-526d trackers exist; creative output is distinct from games), CrewProfile Big Five traits (read-only consumer), RecordsStore (consumer).
```

3. **docs/development/roadmap.md:** flip AD-525 status to `partial — v1 ships Skills Inventory + Records Output; Time Allocation/Code-as-Art/Cultural Emergence/Collaboration deferred to AD-525b/c/d/e`.

## Verified Against Codebase (2026-05-03)

```
grep -n "class RecordsStore\|async def write_entry" src/probos/knowledge/records_store.py
   46: class RecordsStore:
   89: async def write_entry(self, author, path, content, message, *, classification, status, department, topic, tags, metrics)

grep -rn "notebooks/{callsign}" src/probos/
  proactive.py:2001: f"notebooks/{callsign}"
  proactive.py:2093: dept, scope=f"notebooks/{callsign}"
  proactive.py:2111: f"notebooks/{callsign}/{topic_slug}.md"
  knowledge/records_store.py:260: Creates or updates notebooks/{callsign}/{topic_slug}.md

grep -n "class Rank\|class CrewProfile" src/probos/crew_profile.py
   30: class Rank(Enum):
  116: class CrewProfile:

grep -n "openness\|conscientiousness" src/probos/crew_profile.py | head -5
  (Builder verifies CrewProfile Big Five field shape — should expose openness/conscientiousness/extraversion/agreeableness/neuroticism floats)

grep -n "runtime\.profile_store\|profile_store" src/probos/acm.py
  acm.py:300: if hasattr(runtime, 'profile_store') and runtime.profile_store:
  acm.py:301: crew_profile = runtime.profile_store.get(agent_id)
  (verified: runtime attribute is `profile_store` NOT `crew_profile_store`)
```

## Acceptance Criteria

- `src/probos/creative/` package exists.
- `CreativeSkillsRegistry` + `CreativeOutputWriter` + `CreativeSkill` ship as described.
- 8 default skills seeded; affinity scoring + top-k ranking work.
- Public attributes `runtime.creative_skills_registry`, `runtime.creative_output_writer` (no underscore) per Wave 5 convention #1.
- 2 new EventTypes (`CREATIVE_WORK_PUBLISHED`, `CREATIVE_SKILL_AFFINITY_QUERIED`).
- `CreativeExpressionConfig` Pydantic class wired into `SystemConfig`.
- Creative works persist to `creative/{callsign}/{topic_slug}.md` via existing RecordsStore (no schema migration).
- 20 tests pass.
- DECISIONS.md entry under Era V.
- GH issue #100 closes when commit lands.

## Hard-Stops

- `RecordsStore.write_entry` signature differs from assumption — surface; review verified at records_store.py:89 but build-time confirmation needed.
- Existing `creative/` path namespace already in use — surface; verify by grep before commit.
- CrewProfile Big Five field names differ from Pydantic shape — surface; affinity_score uses generic `dict[str, float]` so this should be soft.
- Earned Agency runtime hook tries to gate publish — should NOT happen in v1 (gating is AD-525b territory). If you find yourself adding rank checks, STOP.
