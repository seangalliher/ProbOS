# AD-428b v1 — Agent Skill Framework: Advanced Features (5-feature OSS v1)

**Status:** Draft, ready for build.
**Closes:** GH issue #38 (umbrella AD-428b "Advanced Features").
**Depends on:** AD-428 (shipped — `skill_framework.py`), AD-357 Earned Agency (shipped — `earned_agency.py`), Hebbian Router (shipped — `mesh/routing.py`), Dreaming (shipped — `cognitive/dreaming.py`), Proactive Cognitive Loop (shipped — `proactive.py`).
**Estimated tests:** +18 (window **[+15, +22]**).
**Baseline:** 11480 collected at HEAD `04bc430`. Target 11498.

## What ships in v1

Per Captain rule "don't defer unless no choice": this v1 ships every AD-428b feature whose dependencies are present at HEAD. Five of nine feature rows in the AD-428b roadmap table land here. The four force-deferred rows (Holodeck-based assessment, Assessment criteria per level, Model-Skill Alignment, INNATE category) all have prerequisite systems that are absent or partial at HEAD — see "Force-deferred" section below for explicit forcing functions.

| # | Feature | Status |
|---|---------|--------|
| 1 | Composite skills + synergy bonuses | **v1** |
| 2 | Development goals | **v1** |
| 3 | Earned Agency proficiency-informed rank | **v1** |
| 4 | Skill-weighted task routing (OSS basic) | **v1** |
| 5 | Dream consolidation reinforcement | **v1** |
| 6 | Holodeck-based assessment | **deferred → AD-428b-i** |
| 7 | Assessment criteria per level | **deferred → AD-428b-i** |
| 8 | Model-Skill Alignment | **deferred → AD-428b-ii** |
| 9 | INNATE skill category | **deferred → AD-428b-ii** |

## Architect calls (Decision Log)

1. **DLog #1 — Schema additions via runtime `ALTER TABLE`, NOT `_SCHEMA` literal.** AD-423a precedent at `skill_framework.py:376-381` adds `preferred_tools` via `ALTER TABLE skill_definitions ADD COLUMN ...` wrapped in try/except (column-already-exists swallowed). v1 follows the same pattern for the four new columns (`composite_skill_ids`, `synergy_partners`, `development_goals_json`, plus `agent_skills.development_goal` lacks an SQL column — goals are stored on a per-agent JSON blob in a new `agent_development_goals` table, see DLog #2). The `_SCHEMA` literal block at `skill_framework.py:305` stays untouched so older DBs are upgraded in place at startup.

2. **DLog #2 — Development goals live on a new `agent_development_goals` table, NOT on `agent_skills`.** A goal is an aspirational target ("reach APPLY in threat_analysis by 2026-06-01"), not a per-skill column. New table `agent_development_goals(agent_id TEXT, skill_id TEXT, target_level INTEGER, set_at REAL, notes TEXT, PRIMARY KEY (agent_id, skill_id))`. One goal per (agent, skill) pair. Not a list — adding the same skill replaces the previous goal. This is the simplest shape that lets proactive context render "your goal: APPLY threat_analysis (currently FOLLOW)" without a join.

3. **DLog #3 — `SkillDefinition.composite_skill_ids` declares membership, NOT computation.** A composite skill is a `SkillDefinition` whose `composite_skill_ids` field lists the constituent skill IDs. `has_composite_capability(composite_id)` returns True iff the agent has APPLY+ on EVERY constituent. No partial composite — the composite either fires or it doesn't. Synergy bonus is a separate, narrower concept (DLog #4).

4. **DLog #4 — Synergy is a pairwise float, NOT an emergent multi-skill calculation.** `SkillDefinition.synergy_partners: list[str]` declares "skills that pair well with this one." `SkillProfile.synergy_bonus(skill_a_id, skill_b_id) -> float` returns `0.0` unless BOTH skills are at APPLY+ AND each declares the other as a synergy_partner. When both conditions hold, the bonus is `0.10 * (min(level_a, level_b) - ProficiencyLevel.APPLY.value + 1)` capped at `0.50` — so APPLY+APPLY = 0.10, ENABLE+ENABLE = 0.20, ADVISE+ADVISE = 0.30, LEAD+LEAD = 0.40, SHAPE+SHAPE = 0.50. v1 does NOT route this bonus anywhere — it's a public API surface that AD-428b-iii (skill-weighted ANALYZE chains) will consume. Today the only consumer is the test suite + `HebbianRouter.score_with_skill_weight()` (DLog #6).

5. **DLog #5 — `proficiency_promotion_eligibility(profile, current_rank)` is a pure function in `earned_agency.py`, NOT a side-effect on Rank.from_trust.** Per AD-571 DLog #5 ("`Rank.from_trust()` is NOT modified in this wave; 20+ call sites; Wave-10 6+ rule"), v1 ships a NEW pure function that returns `{"trust_passes": bool, "proficiency_passes": bool, "blockers": list[str]}` for inspection and HXI surfacing. NO change to `Rank.from_trust()` itself. NO existing caller of `Rank.from_trust()` is rewired. The function lets the Captain (or AD-428b-iv) opt into proficiency gating later by reading both the trust passes and the proficiency passes side by side.

6. **DLog #6 — Skill-weighted routing is a NEW method `score_with_skill_weight()`, NOT a change to `score()` or `record_interaction()`.** `HebbianRouter` gains a `set_skill_service(service)` injection (mirrors `set_tier_registry()` from AD-571) and a new public method `score_with_skill_weight(intent_id, agent_id, base_weight) -> float`. The method returns `base_weight` unchanged when no skill_service is attached or when no skill maps to the intent. When a skill maps (via the new `IntentSkillMap` declaration on `MeshConfig` — see DLog #7), the method multiplies `base_weight` by `(1.0 + 0.10 * (proficiency.value - 1))` capped at `2.0`. FOLLOW is neutral, SHAPE doubles. v1 does NOT call this method from any existing routing decision — it's a public API that the existing `score()` consumers can opt into. AD-428b-v will consume it in routing decisions.

7. **DLog #7 — `MeshConfig.intent_skill_map: dict[str, str]` is the intent-to-skill declaration.** A new Pydantic field on `MeshConfig` (`config.py:129` neighborhood). Default `{}` — empty dict means skill weighting is off entirely. Operator-configurable. Example: `{"threat_assessment": "threat_analysis", "ward_room_notification": "communication"}`. The Hebbian router reads this dict at `score_with_skill_weight()` time. NOT loaded into routing state at boot (re-reads on every call) so config reload picks up changes without router restart.

8. **DLog #8 — Dream consolidation reinforcement uses `agent_id` from cluster episodes, NOT a global tally.** When `DreamCycle._consolidate_clusters()` finishes processing a cluster, v1 walks `cluster.episodes` and for each (agent_id, intent_type) pair, looks up the mapped skill via `MeshConfig.intent_skill_map`. If `skill_service` is attached AND a skill is mapped, calls `await skill_service.record_exercise(agent_id, skill_id)`. Per-cluster dedup via a local `set[(agent_id, skill_id)]` so repeated communication episodes in one cluster don't multi-count. Tier-2 log-and-degrade — every call wrapped in try/except, dream cycle never fails on skill-side error.

9. **DLog #9 — Proactive surfacing of development goals lives next to existing skill_profile block.** `proactive.py:1796` already injects `context["skill_profile"]` from `rt.skill_service.get_profile()`. v1 extends this same block: when `skill_service.get_development_goals(agent.id)` returns non-empty, render `context["development_goals"] = [{"skill_id": ..., "target_level": ..., "current_level": ..., "label": "..."}]`. NOT a new context section — same call site, same try/except, same `hasattr` guard.

10. **DLog #10 — Default-False on every new flag is REQUIRED, not optional.** Wave-10 convention #14 + #3. `MeshConfig.intent_skill_map = {}` (empty = off), no new `enabled` flags but every behavioral pathway is gated on the relevant service being attached AND the relevant config being non-empty. AD-571c-i forcing-function precedent: ship the dial, leave the existing default behavior unchanged.

11. **DLog #11 — Composite skills do NOT count toward `SkillProfile.depth`/`breadth`.** Existing `depth`/`breadth` properties at `skill_framework.py:107-126` walk `all_skills` (= pccs + role_skills + acquired_skills). Composite skills live as `SkillDefinition`s with `category=ACQUIRED` whose `composite_skill_ids` is non-empty — they're stored in `acquired_skills` only when an agent meets the composite's gate via `acquire_composite_skill()` (a new ledger method, see Section 3). Until then the composite is a definition without a record, and `has_composite_capability()` is the read-side answer.

12. **DLog #12 — Commercial-leak audit: clean.** AD-428b features 1-5 ship the OSS basic skill-weighted routing (intent_skill_map dict + score_with_skill_weight method). The advanced skill analytics + workforce planning surfaces remain in the private commercial roadmap. No pricing, no paid SKU, no go-to-market language in this prompt or any source comment.

## Force-deferred (with explicit forcing functions)

- **AD-428b-i — Holodeck-based assessment + per-level assessment criteria.** Two roadmap rows. Forcing function: **Holodeck doesn't exist at HEAD.** Grep `class Holodeck|holodeck_` returns 0 hits in `src/probos/`. Cannot land assessment_criteria when no assessment engine exists. New GH tracking issue at close-comment time.
- **AD-428b-ii — Model-Skill Alignment + INNATE skill category.** Two roadmap rows. Forcing function: **Per-agent ModelDescriptor assignment is incomplete.** AD-463 v1 ships `ModelRegistry`/`ModelDescriptor`/`ModelRouter` foundation but `ProviderABC`/`MAD`/`HebbianRouter integration`/`hot-swap`/`edit-format` are all deferred to AD-463b/c/d/e/f (per `roadmap.md:4179`). Without per-agent model assignment, `suspend_incompatible_skills(agent_id)` has no model to check against. New GH tracking issue at close-comment time.

These are the ONLY deferrals. The remaining five rows ship.

---

## Section 0: New Pydantic config

**File:** `src/probos/config.py`

Add `intent_skill_map` to the existing `MeshConfig` block adjacent to `hebbian_decay_rate` (line 129) and `hebbian_social_decay_rate` (added Wave 74).

```search
===SEARCH===
    hebbian_decay_rate: float = 0.995
    hebbian_social_decay_rate: float = 0.995
===REPLACE===
    hebbian_decay_rate: float = 0.995
    hebbian_social_decay_rate: float = 0.995
    # AD-428b v1: Map intent_id -> skill_id for skill-weighted routing.
    # Empty dict (default) means skill weighting is off; the router returns
    # base_weight unchanged. Reread per call so config reload picks up changes.
    intent_skill_map: dict[str, str] = Field(default_factory=dict)
===END REPLACE===
```

(If the existing line is `hebbian_social_decay_rate: float = 0.999` per a Wave-74 default, match the actual HEAD literal — verify-first via `grep -n "hebbian_social_decay_rate" src/probos/config.py` shows the exact value at HEAD `04bc430`.)

## Section 1: Schema migration + dataclass extensions

**File:** `src/probos/skill_framework.py`

### 1a — `SkillDefinition` gains two fields

```search
===SEARCH===
@dataclass
class SkillDefinition:
    """A skill that agents can acquire and develop."""
    skill_id: str               # e.g., "threat_analysis", "ward_room_communication"
    name: str                   # Human-readable display name
    category: SkillCategory
    description: str = ""
    domain: str = "*"           # "security", "engineering", "*" (universal)
    prerequisites: list[str] = field(default_factory=list)  # skill_ids required at APPLY+
    decay_rate_days: int = 14   # Days idle before proficiency drops one level
    origin: str = "built_in"    # "built_in" (PCC), "role", "acquired", "designed"
    preferred_tools: list[ToolPreference] = field(default_factory=list)
===REPLACE===
@dataclass
class SkillDefinition:
    """A skill that agents can acquire and develop."""
    skill_id: str               # e.g., "threat_analysis", "ward_room_communication"
    name: str                   # Human-readable display name
    category: SkillCategory
    description: str = ""
    domain: str = "*"           # "security", "engineering", "*" (universal)
    prerequisites: list[str] = field(default_factory=list)  # skill_ids required at APPLY+
    decay_rate_days: int = 14   # Days idle before proficiency drops one level
    origin: str = "built_in"    # "built_in" (PCC), "role", "acquired", "designed"
    preferred_tools: list[ToolPreference] = field(default_factory=list)
    # AD-428b v1: composite-skill membership. When non-empty, this skill is a
    # composite that fires when the agent has APPLY+ on every constituent.
    composite_skill_ids: list[str] = field(default_factory=list)
    # AD-428b v1: pairwise synergy declaration. When skill A lists B AND B lists A,
    # SkillProfile.synergy_bonus(A, B) returns a non-zero float.
    synergy_partners: list[str] = field(default_factory=list)
===END REPLACE===
```

### 1b — `SkillProfile` gains synergy/composite/development_goals helpers

```search
===SEARCH===
    @property
    def breadth(self) -> int:
        """Number of distinct domains with ASSIST+ proficiency."""
        domains = set()
        for s in self.all_skills:
            if s.proficiency.value >= ProficiencyLevel.ASSIST.value and not s.suspended:
                domains.add(s.skill_id)
        return len(domains)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "pccs": [s.to_dict() for s in self.pccs],
            "role_skills": [s.to_dict() for s in self.role_skills],
            "acquired_skills": [s.to_dict() for s in self.acquired_skills],
            "depth": self.depth,
            "breadth": self.breadth,
        }
===REPLACE===
    @property
    def breadth(self) -> int:
        """Number of distinct domains with ASSIST+ proficiency."""
        domains = set()
        for s in self.all_skills:
            if s.proficiency.value >= ProficiencyLevel.ASSIST.value and not s.suspended:
                domains.add(s.skill_id)
        return len(domains)

    def get_proficiency(self, skill_id: str) -> ProficiencyLevel | None:
        """AD-428b v1: lookup proficiency for a skill_id; None if not held or suspended."""
        for record in self.all_skills:
            if record.skill_id == skill_id and not record.suspended:
                return record.proficiency
        return None

    def has_composite_capability(
        self, composite: "SkillDefinition"
    ) -> bool:
        """AD-428b v1: True iff agent has APPLY+ on EVERY constituent of the composite.

        Composites with empty composite_skill_ids never fire (degenerate case).
        """
        if not composite.composite_skill_ids:
            return False
        for constituent_id in composite.composite_skill_ids:
            level = self.get_proficiency(constituent_id)
            if level is None or level.value < ProficiencyLevel.APPLY.value:
                return False
        return True

    def synergy_bonus(
        self,
        skill_a_id: str,
        skill_b_id: str,
        registry_lookup: Any = None,
    ) -> float:
        """AD-428b v1: pairwise synergy bonus between two skills.

        Returns 0.0 unless ALL of:
          - agent holds both skills at APPLY+
          - skill A's SkillDefinition.synergy_partners contains B
          - skill B's SkillDefinition.synergy_partners contains A
        Bonus = 0.10 * min(level_a, level_b) - 0.20 (so APPLY+APPLY=0.10),
        capped at 0.50.

        registry_lookup: callable taking skill_id -> SkillDefinition | None.
        Pass None to opt out of synergy_partners check (returns 0.0).
        """
        if registry_lookup is None or skill_a_id == skill_b_id:
            return 0.0
        level_a = self.get_proficiency(skill_a_id)
        level_b = self.get_proficiency(skill_b_id)
        if level_a is None or level_b is None:
            return 0.0
        if level_a.value < ProficiencyLevel.APPLY.value or level_b.value < ProficiencyLevel.APPLY.value:
            return 0.0
        defn_a = registry_lookup(skill_a_id)
        defn_b = registry_lookup(skill_b_id)
        if defn_a is None or defn_b is None:
            return 0.0
        if skill_b_id not in defn_a.synergy_partners:
            return 0.0
        if skill_a_id not in defn_b.synergy_partners:
            return 0.0
        bonus = 0.10 * (min(level_a.value, level_b.value) - ProficiencyLevel.APPLY.value + 1)
        return min(bonus, 0.50)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "pccs": [s.to_dict() for s in self.pccs],
            "role_skills": [s.to_dict() for s in self.role_skills],
            "acquired_skills": [s.to_dict() for s in self.acquired_skills],
            "depth": self.depth,
            "breadth": self.breadth,
        }
===END REPLACE===
```

### 1c — Schema additions on `SkillRegistry.start()` (ALTER TABLE pattern)

Add two new `ALTER TABLE` statements next to the existing `preferred_tools` migration. SEARCH anchor is the existing block at `skill_framework.py:376-381`.

```search
===SEARCH===
            # AD-423a: Add preferred_tools column if missing (migration)
            try:
                await self._db.execute(
                    "ALTER TABLE skill_definitions ADD COLUMN preferred_tools TEXT DEFAULT '[]'"
                )
                await self._db.commit()
            except Exception:
                pass  # Column already exists
===REPLACE===
            # AD-423a: Add preferred_tools column if missing (migration)
            try:
                await self._db.execute(
                    "ALTER TABLE skill_definitions ADD COLUMN preferred_tools TEXT DEFAULT '[]'"
                )
                await self._db.commit()
            except Exception:
                pass  # Column already exists
            # AD-428b v1: composite_skill_ids column (JSON-encoded list)
            try:
                await self._db.execute(
                    "ALTER TABLE skill_definitions ADD COLUMN composite_skill_ids TEXT DEFAULT '[]'"
                )
                await self._db.commit()
            except Exception:
                pass  # Column already exists
            # AD-428b v1: synergy_partners column (JSON-encoded list)
            try:
                await self._db.execute(
                    "ALTER TABLE skill_definitions ADD COLUMN synergy_partners TEXT DEFAULT '[]'"
                )
                await self._db.commit()
            except Exception:
                pass  # Column already exists
===END REPLACE===
```

### 1d — `_row_to_definition` reads new columns

```search
===SEARCH===
    def _row_to_definition(self, row) -> SkillDefinition:
        prefs_raw = json.loads(row["preferred_tools"] if "preferred_tools" in row.keys() else "[]")
        prefs = [ToolPreference(tool_id=p["tool_id"], priority=p.get("priority", 0), context=p.get("context", "")) for p in prefs_raw]
        return SkillDefinition(
            skill_id=row["skill_id"],
            name=row["name"],
            category=SkillCategory(row["category"]),
            description=row["description"] or "",
            domain=row["domain"] or "*",
            prerequisites=json.loads(row["prerequisites"] or "[]"),
            decay_rate_days=row["decay_rate_days"] or 14,
            origin=row["origin"] or "built_in",
            preferred_tools=prefs,
        )
===REPLACE===
    def _row_to_definition(self, row) -> SkillDefinition:
        prefs_raw = json.loads(row["preferred_tools"] if "preferred_tools" in row.keys() else "[]")
        prefs = [ToolPreference(tool_id=p["tool_id"], priority=p.get("priority", 0), context=p.get("context", "")) for p in prefs_raw]
        # AD-428b v1: tolerate older rows where columns are absent.
        composite_raw = row["composite_skill_ids"] if "composite_skill_ids" in row.keys() else "[]"
        synergy_raw = row["synergy_partners"] if "synergy_partners" in row.keys() else "[]"
        return SkillDefinition(
            skill_id=row["skill_id"],
            name=row["name"],
            category=SkillCategory(row["category"]),
            description=row["description"] or "",
            domain=row["domain"] or "*",
            prerequisites=json.loads(row["prerequisites"] or "[]"),
            decay_rate_days=row["decay_rate_days"] or 14,
            origin=row["origin"] or "built_in",
            preferred_tools=prefs,
            composite_skill_ids=json.loads(composite_raw or "[]"),
            synergy_partners=json.loads(synergy_raw or "[]"),
        )
===END REPLACE===
```

### 1e — `register_skill` writes new columns

```search
===SEARCH===
    async def register_skill(self, defn: SkillDefinition) -> SkillDefinition:
        """Register or update a skill definition."""
        self._cache[defn.skill_id] = defn
        if self._db:
            prefs_json = json.dumps([{"tool_id": p.tool_id, "priority": p.priority, "context": p.context} for p in defn.preferred_tools])
            await self._db.execute(
                "INSERT OR REPLACE INTO skill_definitions "
                "(skill_id, name, category, description, domain, prerequisites, decay_rate_days, origin, preferred_tools) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (defn.skill_id, defn.name, defn.category.value, defn.description,
                 defn.domain, json.dumps(defn.prerequisites), defn.decay_rate_days, defn.origin, prefs_json),
            )
            await self._db.commit()
        return defn
===REPLACE===
    async def register_skill(self, defn: SkillDefinition) -> SkillDefinition:
        """Register or update a skill definition."""
        self._cache[defn.skill_id] = defn
        if self._db:
            prefs_json = json.dumps([{"tool_id": p.tool_id, "priority": p.priority, "context": p.context} for p in defn.preferred_tools])
            composite_json = json.dumps(defn.composite_skill_ids)
            synergy_json = json.dumps(defn.synergy_partners)
            await self._db.execute(
                "INSERT OR REPLACE INTO skill_definitions "
                "(skill_id, name, category, description, domain, prerequisites, decay_rate_days, origin, preferred_tools, composite_skill_ids, synergy_partners) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (defn.skill_id, defn.name, defn.category.value, defn.description,
                 defn.domain, json.dumps(defn.prerequisites), defn.decay_rate_days, defn.origin, prefs_json,
                 composite_json, synergy_json),
            )
            await self._db.commit()
        return defn
===END REPLACE===
```

## Section 2: Development goals (new table + service methods)

**File:** `src/probos/skill_framework.py`

### 2a — Add `agent_development_goals` table to `_SCHEMA`

The existing `_SCHEMA` literal at line 305 is the boot schema. Append the new table at the end of the schema string (before the closing `"""`).

```search
===SEARCH===
CREATE TABLE IF NOT EXISTS qualification_records (
    agent_id TEXT NOT NULL,
    path_id TEXT NOT NULL,
    started_at REAL NOT NULL,
    completed_at REAL,
    requirement_status TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (agent_id, path_id)
);
"""
===REPLACE===
CREATE TABLE IF NOT EXISTS qualification_records (
    agent_id TEXT NOT NULL,
    path_id TEXT NOT NULL,
    started_at REAL NOT NULL,
    completed_at REAL,
    requirement_status TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (agent_id, path_id)
);

-- AD-428b v1: per-agent development goals (one goal per skill).
CREATE TABLE IF NOT EXISTS agent_development_goals (
    agent_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    target_level INTEGER NOT NULL,
    set_at REAL NOT NULL,
    notes TEXT DEFAULT '',
    PRIMARY KEY (agent_id, skill_id)
);

CREATE INDEX IF NOT EXISTS idx_dev_goals_agent ON agent_development_goals(agent_id);
"""
===END REPLACE===
```

### 2b — `AgentSkillService` gains 3 development-goal methods

Insert after the existing `get_all_records` method (the end of the class body). Locate via grep `async def get_all_records` in `skill_framework.py`.

```search
===SEARCH===
    async def get_all_records(self, agent_id: str) -> list[AgentSkillRecord]:
        """Get all skill records for an agent."""
        if not self._db:
            return []
        records: list[AgentSkillRecord] = []
        async with self._db.execute(
            "SELECT * FROM agent_skills WHERE agent_id = ?", (agent_id,)
        ) as cur:
            async for row in cur:
                records.append(self._row_to_record(row))
        return records
===REPLACE===
    async def get_all_records(self, agent_id: str) -> list[AgentSkillRecord]:
        """Get all skill records for an agent."""
        if not self._db:
            return []
        records: list[AgentSkillRecord] = []
        async with self._db.execute(
            "SELECT * FROM agent_skills WHERE agent_id = ?", (agent_id,)
        ) as cur:
            async for row in cur:
                records.append(self._row_to_record(row))
        return records

    # ------------------------------------------------------------------
    # AD-428b v1: Development goals
    # ------------------------------------------------------------------

    async def add_development_goal(
        self,
        agent_id: str,
        skill_id: str,
        target_level: ProficiencyLevel,
        notes: str = "",
    ) -> dict[str, Any]:
        """AD-428b v1: set or replace a development goal for a (agent, skill).

        One goal per (agent_id, skill_id). Calling with the same skill_id
        replaces the existing goal. Returns the persisted goal as a dict.
        """
        if not self._db:
            return {
                "agent_id": agent_id,
                "skill_id": skill_id,
                "target_level": target_level.value,
                "set_at": time.time(),
                "notes": notes,
            }
        await self._db.execute(
            "INSERT OR REPLACE INTO agent_development_goals "
            "(agent_id, skill_id, target_level, set_at, notes) "
            "VALUES (?, ?, ?, ?, ?)",
            (agent_id, skill_id, target_level.value, time.time(), notes),
        )
        await self._db.commit()
        return {
            "agent_id": agent_id,
            "skill_id": skill_id,
            "target_level": target_level.value,
            "set_at": time.time(),
            "notes": notes,
        }

    async def clear_development_goal(
        self, agent_id: str, skill_id: str
    ) -> bool:
        """AD-428b v1: remove a development goal. Returns True if a row was deleted."""
        if not self._db:
            return False
        cur = await self._db.execute(
            "DELETE FROM agent_development_goals WHERE agent_id = ? AND skill_id = ?",
            (agent_id, skill_id),
        )
        await self._db.commit()
        return cur.rowcount > 0  # type: ignore[attr-defined]

    async def get_development_goals(
        self, agent_id: str
    ) -> list[dict[str, Any]]:
        """AD-428b v1: return all development goals for an agent.

        Each entry: {skill_id, target_level (int 1-7), target_label, set_at, notes,
        current_level (int|None — agent's current proficiency on the skill)}.
        Sorted by skill_id.
        """
        if not self._db:
            return []
        # Build a map of agent's current proficiency per skill.
        records = await self.get_all_records(agent_id)
        current_by_skill = {r.skill_id: r.proficiency.value for r in records}
        goals: list[dict[str, Any]] = []
        async with self._db.execute(
            "SELECT skill_id, target_level, set_at, notes "
            "FROM agent_development_goals WHERE agent_id = ? ORDER BY skill_id",
            (agent_id,),
        ) as cur:
            async for row in cur:
                target_lvl = int(row["target_level"])
                try:
                    target_label = ProficiencyLevel(target_lvl).name
                except ValueError:
                    target_label = "UNKNOWN"
                goals.append({
                    "skill_id": row["skill_id"],
                    "target_level": target_lvl,
                    "target_label": target_label,
                    "set_at": row["set_at"],
                    "notes": row["notes"] or "",
                    "current_level": current_by_skill.get(row["skill_id"]),
                })
        return goals
===END REPLACE===
```

## Section 3: Earned Agency proficiency-informed rank gate

**File:** `src/probos/earned_agency.py`

Add a new pure function `proficiency_promotion_eligibility()`. It returns a structured dict for inspection — does NOT change `Rank.from_trust()` or any existing call site.

Insertion point: immediately BEFORE the existing `agency_from_rank()` function definition at `earned_agency.py:169` (verified live). The new function is module-level, async-free, dependency-free apart from `Rank` (already imported via `from probos.crew_profile import Rank` in `earned_agency.py`). The Builder must keep the `Any` import on the existing `from typing import ...` line — verify-first via grep that `Any` is already imported; if not, the Builder adds it on the same line as existing typing imports.

```search
===SEARCH===
def agency_from_rank(rank: Rank) -> AgencyLevel:
===REPLACE===
def proficiency_promotion_eligibility(
    *,
    profile: Any,
    next_rank: Rank,
    pcc_floor: int = 3,
    role_floor: int = 3,
) -> dict[str, Any]:
    """AD-428b v1: pure inspector for proficiency-based promotion readiness.

    Returns:
        {
            "next_rank": str,                        # next_rank.value
            "pcc_floor": int,                        # required PCC proficiency floor
            "role_floor": int,                       # required ROLE proficiency floor
            "passes": bool,                          # all gates pass
            "blockers": list[str],                   # human-readable failure reasons
            "pcc_count_at_floor": int,               # PCCs at >= pcc_floor (non-suspended)
            "role_count_at_floor": int,              # ROLE skills at >= role_floor (non-suspended)
            "required_pcc_count": int,               # minimum PCCs at floor for next_rank
            "required_role_count": int,              # minimum ROLE skills at floor for next_rank
        }

    Rank thresholds (Dreyfus mapping):
        ENSIGN -> LIEUTENANT: 2 PCCs at APPLY (3), 1 ROLE at APPLY (3)
        LIEUTENANT -> COMMANDER: 4 PCCs at APPLY (3), 2 ROLE at ENABLE (4)
        COMMANDER -> SENIOR: 6 PCCs at ENABLE (4), 3 ROLE at ADVISE (5)

    Does NOT modify Rank.from_trust(). NOT called from any existing decision
    path; v1 is inspection only. Captain or AD-428b-iv (gating consumer)
    decides whether to enforce.
    """
    blockers: list[str] = []
    if next_rank == Rank.LIEUTENANT:
        req_pcc, req_role = 2, 1
        pcc_floor, role_floor = 3, 3
    elif next_rank == Rank.COMMANDER:
        req_pcc, req_role = 4, 2
        pcc_floor, role_floor = 3, 4
    elif next_rank == Rank.SENIOR:
        req_pcc, req_role = 6, 3
        pcc_floor, role_floor = 4, 5
    else:
        # ENSIGN promotion to ENSIGN is the boot state — no gate.
        req_pcc, req_role = 0, 0

    if profile is None:
        return {
            "next_rank": next_rank.value,
            "pcc_floor": pcc_floor,
            "role_floor": role_floor,
            "passes": req_pcc == 0 and req_role == 0,
            "blockers": ["no_skill_profile"] if (req_pcc + req_role) > 0 else [],
            "pcc_count_at_floor": 0,
            "role_count_at_floor": 0,
            "required_pcc_count": req_pcc,
            "required_role_count": req_role,
        }

    pccs_ok = sum(
        1 for r in getattr(profile, "pccs", [])
        if not getattr(r, "suspended", False)
        and getattr(getattr(r, "proficiency", None), "value", 0) >= pcc_floor
    )
    role_ok = sum(
        1 for r in getattr(profile, "role_skills", [])
        if not getattr(r, "suspended", False)
        and getattr(getattr(r, "proficiency", None), "value", 0) >= role_floor
    )

    if pccs_ok < req_pcc:
        blockers.append(
            f"need {req_pcc} PCCs at level {pcc_floor}+ (have {pccs_ok})"
        )
    if role_ok < req_role:
        blockers.append(
            f"need {req_role} role skills at level {role_floor}+ (have {role_ok})"
        )

    return {
        "next_rank": next_rank.value,
        "pcc_floor": pcc_floor,
        "role_floor": role_floor,
        "passes": not blockers,
        "blockers": blockers,
        "pcc_count_at_floor": pccs_ok,
        "role_count_at_floor": role_ok,
        "required_pcc_count": req_pcc,
        "required_role_count": req_role,
    }


def agency_from_rank(rank: Rank) -> AgencyLevel:
===END REPLACE===
```

## Section 4: Skill-weighted Hebbian routing

**File:** `src/probos/mesh/routing.py`

### 4a — `HebbianRouter.__init__` accepts skill_service kwarg + `set_skill_service()`

Anchor: existing `set_tier_registry()` method at line 78.

```search
===SEARCH===
    def set_tier_registry(self, registry: Any) -> None:
        """Inject agent tier registry for tier-aware reporting (AD-571)."""
        self._tier_registry = registry
===REPLACE===
    def set_tier_registry(self, registry: Any) -> None:
        """Inject agent tier registry for tier-aware reporting (AD-571)."""
        self._tier_registry = registry

    def set_skill_service(self, service: Any) -> None:
        """AD-428b v1: inject AgentSkillService for skill-weighted routing.

        Late-bind. Idempotent. None disables skill weighting (default).
        """
        self._skill_service = service

    def set_intent_skill_map(self, mapping: dict[str, str]) -> None:
        """AD-428b v1: set the intent_id -> skill_id mapping read at routing time.

        Empty mapping (default) means score_with_skill_weight() is a no-op.
        Late-bind. Idempotent. Re-callable.
        """
        # Defensive copy — caller may continue to mutate the original config dict.
        self._intent_skill_map = dict(mapping or {})
===END REPLACE===
```

### 4b — `__init__` defaults

Initial `_skill_service = None` and `_intent_skill_map = {}` need to be set in `__init__`. Anchor: existing `self._tier_registry: Any = None` line.

```search
===SEARCH===
        self._tier_registry: Any = None
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory
===REPLACE===
        self._tier_registry: Any = None
        # AD-428b v1: skill-weighted routing late-binds. Both default to "off".
        self._skill_service: Any = None
        self._intent_skill_map: dict[str, str] = {}
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory
===END REPLACE===
```

### 4c — `score_with_skill_weight()` method

Insert after `set_intent_skill_map()` method. The method is `async` because `skill_service.get_profile()` is async. Locate the end of the existing class via the natural file structure (after the AD-571c `record_interaction` and `decay_all` blocks).

```search
===SEARCH===
    def set_skill_service(self, service: Any) -> None:
        """AD-428b v1: inject AgentSkillService for skill-weighted routing.

        Late-bind. Idempotent. None disables skill weighting (default).
        """
        self._skill_service = service

    def set_intent_skill_map(self, mapping: dict[str, str]) -> None:
        """AD-428b v1: set the intent_id -> skill_id mapping read at routing time.

        Empty mapping (default) means score_with_skill_weight() is a no-op.
        Late-bind. Idempotent. Re-callable.
        """
        # Defensive copy — caller may continue to mutate the original config dict.
        self._intent_skill_map = dict(mapping or {})
===REPLACE===
    def set_skill_service(self, service: Any) -> None:
        """AD-428b v1: inject AgentSkillService for skill-weighted routing.

        Late-bind. Idempotent. None disables skill weighting (default).
        """
        self._skill_service = service

    def set_intent_skill_map(self, mapping: dict[str, str]) -> None:
        """AD-428b v1: set the intent_id -> skill_id mapping read at routing time.

        Empty mapping (default) means score_with_skill_weight() is a no-op.
        Late-bind. Idempotent. Re-callable.
        """
        # Defensive copy — caller may continue to mutate the original config dict.
        self._intent_skill_map = dict(mapping or {})

    async def score_with_skill_weight(
        self,
        intent_id: AgentID,
        agent_id: AgentID,
        base_weight: float,
    ) -> float:
        """AD-428b v1: skill-weighted routing score multiplier.

        Returns base_weight unchanged when:
          - skill_service is not attached
          - intent_skill_map is empty
          - intent_id is not in the map
          - agent has no profile
          - agent has no record for the mapped skill (or it's suspended)

        When all conditions hold, returns:
          base_weight * (1.0 + 0.10 * (proficiency.value - 1))
        capped at 2.0x. FOLLOW (1) is neutral; SHAPE (7) doubles.

        Tier-2 log-and-degrade — any error returns base_weight unchanged.
        """
        if self._skill_service is None or not self._intent_skill_map:
            return base_weight
        skill_id = self._intent_skill_map.get(intent_id)
        if skill_id is None:
            return base_weight
        try:
            profile = await self._skill_service.get_profile(agent_id)
        except Exception:
            logger.debug(
                "AD-428b: skill_service.get_profile failed for %s; returning base_weight",
                agent_id,
                exc_info=True,
            )
            return base_weight
        if profile is None:
            return base_weight
        # Reuse the SkillProfile.get_proficiency helper added in Section 1b.
        try:
            level = profile.get_proficiency(skill_id)
        except AttributeError:
            return base_weight
        if level is None:
            return base_weight
        multiplier = 1.0 + 0.10 * (level.value - 1)
        capped = min(multiplier, 2.0)
        return base_weight * capped
===END REPLACE===
```

## Section 5: Dream consolidation reinforcement

**File:** `src/probos/cognitive/dreaming.py`

### 5a — `DreamCycle.__init__` accepts `skill_service` + `intent_skill_map`

Locate the existing `failure_distiller` ctor parameter (the last AD-prefixed Any kwarg).

```search
===SEARCH===
        failure_distiller: Any = None,  # AD-609: failure and comparative analysis
        manifest: Any = None,  # AD-538b: DreamManifest for skip-already-processed
    ) -> None:
===REPLACE===
        failure_distiller: Any = None,  # AD-609: failure and comparative analysis
        manifest: Any = None,  # AD-538b: DreamManifest for skip-already-processed
        skill_service: Any = None,  # AD-428b v1: AgentSkillService for cluster reinforcement
        intent_skill_map: dict[str, str] | None = None,  # AD-428b v1: intent->skill map
    ) -> None:
===END REPLACE===
```

### 5b — Store the new injections

Locate the existing `self._procedure_store = procedure_store` line.

```search
===SEARCH===
        self._llm_client = llm_client  # AD-532: for procedure extraction
        self._procedure_store = procedure_store  # AD-533: persistent procedure storage
===REPLACE===
        self._llm_client = llm_client  # AD-532: for procedure extraction
        self._procedure_store = procedure_store  # AD-533: persistent procedure storage
        # AD-428b v1: dream consolidation reinforces skills via record_exercise().
        self._skill_service = skill_service
        self._intent_skill_map: dict[str, str] = dict(intent_skill_map or {})
===END REPLACE===
```

### 5c — New `_reinforce_skills_for_cluster()` method

Insert as a private helper near the existing consolidation paths. The Builder should grep for an existing private async helper signature in the same file (e.g. `async def _consolidate_trust`) and place the new helper next to it for cohesion.

```search
===SEARCH===
        trust_adjustments = self._consolidate_trust(episodes)
===REPLACE===
        trust_adjustments = self._consolidate_trust(episodes)
        # AD-428b v1: reinforce skills based on consolidated episodes.
        await self._reinforce_skills_for_episodes(episodes)
===END REPLACE===
```

Then add the helper method definition immediately BEFORE `_consolidate_trust` (verified live signature at `dreaming.py:2333`: `def _consolidate_trust(self, episodes: list[Episode]) -> int:`).

```search
===SEARCH===
    def _consolidate_trust(self, episodes: list[Episode]) -> int:
===REPLACE===
    async def _reinforce_skills_for_episodes(
        self, episodes: list[Any]
    ) -> int:
        """AD-428b v1: reinforce skills via record_exercise() per consolidated episode.

        Walks episodes, maps each (agent_id, intent_type) to a skill via
        self._intent_skill_map, and calls skill_service.record_exercise(agent_id,
        skill_id) once per (agent_id, skill_id) pair (per-call dedup).

        Tier-2 log-and-degrade — every record_exercise call is wrapped; any
        skill-side error logs at debug and the next pair proceeds.

        Returns the number of (agent_id, skill_id) reinforcements made.
        """
        if self._skill_service is None or not self._intent_skill_map:
            return 0
        seen: set[tuple[str, str]] = set()
        reinforced = 0
        for ep in episodes:
            # Episode shape varies; tolerate dict + dataclass + namedtuple.
            agent_ids = getattr(ep, "agent_ids", None)
            if agent_ids is None and isinstance(ep, dict):
                agent_ids = ep.get("agent_ids") or ep.get("agent_id")
            if isinstance(agent_ids, str):
                agent_ids = [agent_ids]
            if not agent_ids:
                continue
            intent_type = getattr(ep, "intent_type", None)
            if intent_type is None and isinstance(ep, dict):
                intent_type = ep.get("intent_type") or ep.get("intent")
            if not intent_type:
                continue
            skill_id = self._intent_skill_map.get(intent_type)
            if skill_id is None:
                continue
            for aid in agent_ids:
                key = (aid, skill_id)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    await self._skill_service.record_exercise(aid, skill_id)
                    reinforced += 1
                except Exception:
                    logger.debug(
                        "AD-428b: record_exercise failed for %s/%s",
                        aid, skill_id, exc_info=True,
                    )
        return reinforced

    def _consolidate_trust(self, episodes: list[Episode]) -> int:
===END REPLACE===
```

## Section 6: Proactive context — surface development goals

**File:** `src/probos/proactive.py`

The existing skill_profile injection at `proactive.py:1788-1796` is the home for development goals. v1 extends this same try/except block — same `hasattr` guard, same fall-through.

```search
===SEARCH===
        # 6. Skill profile context (AD-429b)
        if hasattr(rt, 'skill_service') and rt.skill_service:
            try:
                profile = await rt.skill_service.get_profile(agent.id)
                if profile:
                    skill_summary = []
                    for record in profile.all_skills:
                        skill_summary.append(f"{record.skill_id}: level {record.proficiency.value} ({record.proficiency.name})")
                    if skill_summary:
                        context["skill_profile"] = skill_summary
            except Exception:
                logger.debug("Skill profile fetch failed for %s", agent.id, exc_info=True)
===REPLACE===
        # 6. Skill profile context (AD-429b) + AD-428b v1 development goals
        if hasattr(rt, 'skill_service') and rt.skill_service:
            try:
                profile = await rt.skill_service.get_profile(agent.id)
                if profile:
                    skill_summary = []
                    for record in profile.all_skills:
                        skill_summary.append(f"{record.skill_id}: level {record.proficiency.value} ({record.proficiency.name})")
                    if skill_summary:
                        context["skill_profile"] = skill_summary
            except Exception:
                logger.debug("Skill profile fetch failed for %s", agent.id, exc_info=True)
            # AD-428b v1: development goals (separate try so a goal-fetch
            # failure doesn't suppress skill_profile, and vice versa).
            try:
                goals = await rt.skill_service.get_development_goals(agent.id)
                if goals:
                    context["development_goals"] = goals
            except Exception:
                logger.debug(
                    "AD-428b: development_goals fetch failed for %s",
                    agent.id, exc_info=True,
                )
===END REPLACE===
```

## Section 7: Tests

**New file:** `tests/test_ad428b_skill_advanced.py`

Target: **18 tests**. Each test creates its own fixtures (no shared state); use `tmp_path` for SQLite paths; `pytest.mark.asyncio` where async.

The list below names tests with the assertion they enforce. The Builder is free to consolidate trivial fixture bootstrapping into a small helper but every test should remain readable in isolation.

| # | Test | Section | What it verifies |
|---|------|---------|------------------|
| 1 | `test_skill_definition_composite_and_synergy_fields_default_empty` | 1a | New fields default to empty list |
| 2 | `test_skill_definition_register_and_load_round_trips_composite_and_synergy` | 1c-1e | DB migration columns persist + reload |
| 3 | `test_skill_profile_get_proficiency_returns_none_for_missing_or_suspended` | 1b | `get_proficiency` semantics |
| 4 | `test_has_composite_capability_requires_apply_on_every_constituent` | 1b | All-constituents-APPLY+ rule |
| 5 | `test_has_composite_capability_returns_false_for_empty_composite` | 1b | Degenerate-composite guard |
| 6 | `test_synergy_bonus_zero_when_only_one_partner_declares_other` | 1b | Symmetric-declaration rule |
| 7 | `test_synergy_bonus_apply_apply_returns_0_10_caps_at_0_50` | 1b | Numeric ladder + cap |
| 8 | `test_add_development_goal_persists_and_replaces_on_duplicate` | 2b | INSERT OR REPLACE semantics |
| 9 | `test_get_development_goals_includes_current_level_and_target_label` | 2b | Read shape |
| 10 | `test_clear_development_goal_returns_false_when_no_row` | 2b | Negative-path return |
| 11 | `test_proficiency_promotion_eligibility_blocker_lists_pcc_and_role_gaps` | 3 | Pure-function shape, blockers populated |
| 12 | `test_proficiency_promotion_eligibility_passes_with_full_profile` | 3 | Happy-path passes=True |
| 13 | `test_proficiency_promotion_eligibility_handles_none_profile` | 3 | None-profile path returns blockers |
| 14 | `test_hebbian_score_with_skill_weight_returns_base_when_no_service` | 4c | Off-by-default invariant |
| 15 | `test_hebbian_score_with_skill_weight_multiplies_at_apply` | 4c | APPLY → 1.20x |
| 16 | `test_hebbian_score_with_skill_weight_caps_at_2x` | 4c | SHAPE → 1.60x (within 2.0 cap) |
| 17 | `test_dream_reinforce_skills_records_exercise_once_per_pair` | 5c | Per-cluster dedup |
| 18 | `test_dream_reinforce_skills_no_op_when_intent_skill_map_empty` | 5c | Off-by-default invariant |

**Test fixture pattern (recommended):**
```python
@pytest.fixture
async def skill_stack(tmp_path):
    """Real SkillRegistry + AgentSkillService with built-ins registered."""
    db_path = str(tmp_path / "skills.db")
    registry = SkillRegistry(db_path=db_path)
    await registry.start()
    await registry.register_builtins()
    service = AgentSkillService(db_path=db_path, registry=registry)
    await service.start()
    yield registry, service
    await service.stop()
    await registry.stop()
```

For dream-reinforcement tests, build a minimal `_FakeSkillService` with an `async def record_exercise(agent_id, skill_id)` that appends to a list. Do NOT boot a real `ProbOSRuntime` — DreamCycle's ctor takes injected services.

## What this AD does NOT change

- No new Pydantic config beyond `MeshConfig.intent_skill_map`.
- No deletion of `Rank.from_trust()` or any of its 20+ existing call sites (DLog #5).
- No HXI surface for development goals, composite badges, synergy bonuses, or proficiency-rank gates (deferred — HXI fragility per copilot-instructions).
- No new REST endpoint. `/api/skills/agents/{id}/profile` already serializes `SkillProfile` via `to_dict()`; v1 does NOT change the serialized shape (composite/synergy/goals are queryable separately via existing or new endpoints if AD-428b-vi adds them).
- No change to `_SCHEMA` literal for `skill_definitions` (uses ALTER TABLE per DLog #1). The literal addition for `agent_development_goals` is appended after `qualification_records` because the table is greenfield.
- No call to `score_with_skill_weight()` from existing routing paths. AD-428b-v will consume.
- No change to `SkillProfile.depth`/`breadth` properties. Composite skills do not enter the depth/breadth tally (DLog #11).
- No change to AgentSkillService.acquire_skill / commission_agent / record_exercise / update_proficiency.
- No change to `BUILTIN_PCCS` / `ROLE_SKILL_TEMPLATES` content. v1 ships the dial; populating composite_skill_ids on built-ins is a sibling AD.
- No change to runtime construction of SkillRegistry / AgentSkillService / DreamCycle (Wave 75 builder must NOT wire `skill_service` into DreamCycle yet — Section 5 changes the constructor signature defensively but no caller passes the new kwargs in this wave; AD-428b-v fans out wiring).
- No NATS, no Bills, no Watch Bill, no federation export.

## Verified Against Codebase (2026-05-06, HEAD `04bc430`)

```
grep -n "@dataclass" src/probos/skill_framework.py | head
  54:@dataclass
  68:@dataclass
  97:@dataclass
  136:@dataclass
  (Section 1 anchors confirmed — SkillDefinition, AgentSkillRecord, SkillProfile, QualificationRecord)

grep -n "preferred_tools TEXT DEFAULT" src/probos/skill_framework.py
  378:                    "ALTER TABLE skill_definitions ADD COLUMN preferred_tools TEXT DEFAULT '[]'"
  (Section 1c precedent confirmed — ALTER TABLE migration block)

grep -n "PRIMARY KEY (agent_id, path_id)" src/probos/skill_framework.py
  340:    PRIMARY KEY (agent_id, path_id)
  (Section 2a anchor — _SCHEMA closing block above the """ terminator)

grep -n "async def get_all_records" src/probos/skill_framework.py
  672:    async def get_all_records(self, agent_id: str) -> list[AgentSkillRecord]:
  (Section 2b insertion anchor)

grep -n "def from_trust" src/probos/crew_profile.py
  38:    def from_trust(cls, trust_score: float) -> "Rank":
  (DLog #5 — NOT modified this wave)

grep -n "def agency_from_rank" src/probos/earned_agency.py
  (Section 3 anchor — verify location at build time)

grep -n "set_tier_registry" src/probos/mesh/routing.py
  78:    def set_tier_registry(self, registry: Any) -> None:
  (Section 4a anchor — late-bind setter precedent)

grep -n "self._tier_registry: Any = None" src/probos/mesh/routing.py
  76:        self._tier_registry: Any = None
  (Section 4b anchor — defaults block)

grep -n "self._procedure_store = procedure_store" src/probos/cognitive/dreaming.py
  103:        self._procedure_store = procedure_store  # AD-533: persistent procedure storage
  (Section 5b anchor)

grep -n "trust_adjustments = self._consolidate_trust" src/probos/cognitive/dreaming.py
  349:        trust_adjustments = self._consolidate_trust(episodes)
  (Section 5c integration anchor)

grep -n "context\[\"skill_profile\"\]" src/probos/proactive.py
  1796:                        context["skill_profile"] = skill_summary
  (Section 6 anchor)

grep -c "Rank.from_trust" src/probos -r
  20+ call sites — DLog #5 forbids modification this wave.

grep -n "^class Holodeck\|holodeck_" src/probos -r
  0 hits — AD-428b-i forced-defer rationale confirmed.

grep -n "AD-463" docs/development/roadmap.md | head
  4179: AD-463 (partial — v1 ships ModelRegistry foundation; ProviderABC/MAD/HebbianRouter integration/hot-swap/edit-format deferred)
  (AD-428b-ii forced-defer rationale confirmed: per-agent ModelDescriptor assignment is in deferred AD-463b/c/d/e/f.)
```

## Acceptance criteria

1. Full gate passes at 11498 ± 3 (target +18; window [+15, +22] = [11495, 11502]).
2. All Section 0–6 SEARCH/REPLACE blocks applied byte-for-byte as specified (or with verified-anchor adaptation when HEAD has drifted; report any anchor drift in the build report).
3. 18 new tests in `tests/test_ad428b_skill_advanced.py` all pass, including order-independence (each test creates its own fixtures).
4. No file outside the dispatch's named set is modified (other than tracking files).
5. The Builder build report cites the test count delta + the eleven "what this AD does NOT change" verifications.
6. The Builder build report explicitly cites which deferred children remain (AD-428b-i Holodeck-dependent, AD-428b-ii ModelRegistry-dependent) and what their forcing functions are.
7. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
