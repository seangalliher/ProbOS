# WAVE 75 DISPATCH — AD-428b v1 Agent Skill Framework: Advanced Features (5-feature OSS v1)

**Wave id:** 75
**Single per-AD prompt:** `prompts/ad-428b-skill-framework-advanced-v1.md`
**Closes:** GH issue #38 (umbrella AD-428b "Advanced Features")
**Baseline test count:** 11480 (HEAD `04bc430`, post-Wave-74) → expected **11498** (+18 net), window **[+15, +22]** = [11495, 11502]
**HEAD at draft:** `04bc430`, working tree clean (per Captain task brief)
**Builder:** required

## What ships — five of nine roadmap rows

Per Captain rule "don't defer unless no choice." AD-428b's roadmap table at `docs/development/roadmap.md:1980-1991` lists nine features. Five ship in v1; four force-defer with explicit forcing functions tied to absent prerequisite systems.

**In scope (v1):**

1. **Composite skills + synergy bonuses** — `SkillDefinition.composite_skill_ids` + `synergy_partners` fields, `SkillProfile.has_composite_capability()` + `synergy_bonus()` methods. Pure data model, no missing dep.
2. **Development goals** — new `agent_development_goals` SQLite table + `AgentSkillService.{add,clear,get}_development_goal[s]()` + proactive context surfacing at `proactive.py:1796`. Proactive ✓ + Earned Agency ✓ both shipped.
3. **Earned Agency proficiency-informed rank** — new pure inspector `proficiency_promotion_eligibility(profile, next_rank)` in `earned_agency.py`. Returns structured dict with `passes` + `blockers`. Does NOT modify `Rank.from_trust()` or any of its 20+ call sites.
4. **Skill-weighted task routing (OSS basic)** — `HebbianRouter.set_skill_service()` + `set_intent_skill_map()` + new async `score_with_skill_weight()` method. New `MeshConfig.intent_skill_map: dict[str, str]` Pydantic field. v1 ships the API; no existing routing decision is rewired.
5. **Dream consolidation reinforcement** — `DreamCycle.__init__` accepts `skill_service` + `intent_skill_map`; new `_reinforce_skills_for_episodes(episodes)` helper called at the existing `_consolidate_trust(episodes)` integration point.

**Force-deferred (with explicit forcing functions, GH-tracked at close-comment):**

- **AD-428b-i — Holodeck-based assessment + per-level assessment criteria** *(2 roadmap rows).* Forcing function: **Holodeck does not exist at HEAD.** Verified by `grep "class Holodeck|holodeck_" src/probos/` returning 0 hits. Cannot ship `assessment_criteria` per level when there is no assessment engine to consume them. New GH tracking issue at close-comment time.
- **AD-428b-ii — Model-Skill Alignment + INNATE skill category** *(2 roadmap rows).* Forcing function: **Per-agent ModelDescriptor assignment is incomplete.** Per `roadmap.md:4179`, AD-463 v1 ships `ModelRegistry`/`ModelDescriptor`/`ModelRouter` foundation but `ProviderABC` + `MAD` + `HebbianRouter integration` + `hot-swap` + `edit-format` are all deferred to AD-463b/c/d/e/f. Without per-agent model assignment, `suspend_incompatible_skills(agent_id)` and `SkillProfile.innate_capabilities` have no model to read against. New GH tracking issue at close-comment time.

These are the ONLY deferrals. The remaining five rows ship complete in v1.

**No commercial leak.** AD-428b features 1-5 ship the OSS basic skill-weighted routing surface (`MeshConfig.intent_skill_map` dict + `HebbianRouter.score_with_skill_weight()` method). The advanced skill analytics + automated development plan generation + competency-based workforce planning surfaces remain in the private commercial roadmap. No pricing, no paid SKU, no go-to-market language in this prompt or any source comment. Verified — see commercial audit footer.

## Architect calls (Decision Log)

The full 12-item decision log lives in `prompts/ad-428b-skill-framework-advanced-v1.md` Section "Architect calls". Highest-risk items repeated for Builder pre-flight:

- **DLog #1 — Schema migrations via runtime `ALTER TABLE`, NOT `_SCHEMA` literal mutation.** AD-423a precedent at `skill_framework.py:376-381` adds `preferred_tools` via post-start ALTER. v1 mirrors for `composite_skill_ids` + `synergy_partners`. The new `agent_development_goals` table is greenfield and lands in the `_SCHEMA` literal because there's no compatibility risk.
- **DLog #2 — Development goals on a NEW table, NOT on `agent_skills`.** A goal is an aspirational target, not a per-skill column. `agent_development_goals(agent_id, skill_id, target_level, set_at, notes)` PK `(agent_id, skill_id)`. One goal per (agent, skill) — INSERT OR REPLACE.
- **DLog #5 — `Rank.from_trust()` is NOT modified this wave.** Wave-74 / AD-571 DLog #5 precedent. 20+ call sites. v1 adds a NEW pure inspector `proficiency_promotion_eligibility()` that returns a structured dict; no existing caller is rewired.
- **DLog #6 — Skill-weighted routing is a NEW method, NOT a change to `score()` or `record_interaction()`.** New `score_with_skill_weight()` is async. Returns `base_weight` unchanged when service or map is absent. Caps multiplier at `2.0`. v1 ships the API; AD-428b-v consumes.
- **DLog #7 — `MeshConfig.intent_skill_map: dict[str, str]` defaults to `{}` (off).** Re-read per call so config reload picks up changes without router restart.
- **DLog #8 — Dream reinforcement uses per-cluster `set[(agent_id, skill_id)]` dedup.** Repeated `communication` episodes in one cluster don't multi-count. Tier-2 log-and-degrade.
- **DLog #10 — Default-off on every new pathway.** Wave-10 convention #14. `intent_skill_map = {}`. No new `enabled` flag — every behavioral pathway is gated on the relevant service being attached AND the relevant config being non-empty.
- **DLog #11 — Composite skills do NOT count toward `SkillProfile.depth`/`breadth`.** Existing properties walk `all_skills` (= pccs + role_skills + acquired_skills); composites enter `acquired_skills` only when `acquire_composite_skill()` lands (sibling AD). `has_composite_capability()` is the read-side answer.
- **DLog #12 — Commercial-leak audit: clean.** OSS basic skill-weighted routing only; commercial analytics + workforce planning remain in private repo.

## Builder workflow (standard)

1. **Pre-flight gate:** `pytest tests/ -q -n 4 --dist=loadfile` → confirm 11480 collected at HEAD `04bc430`. Working tree clean.
2. **Apply Section 0** (`config.py` — `MeshConfig.intent_skill_map: dict[str, str] = Field(default_factory=dict)`). Run `pytest tests/test_config*.py -n 0 -q` → no regressions; new field default-valid.
3. **Apply Section 1a-1e** (`skill_framework.py` — `SkillDefinition` 2 new fields, `SkillProfile` 3 new methods, ALTER TABLE migrations, row R/W). Run `pytest tests/test_skill*.py -n 0 -q` → existing 25 AD-428 tests must pass unchanged.
4. **Apply Section 2a-2b** (`skill_framework.py` — `agent_development_goals` table in `_SCHEMA`, 3 new `AgentSkillService` methods). Run `pytest tests/test_skill*.py -n 0 -q` again.
5. **Apply Section 3** (`earned_agency.py` — new `proficiency_promotion_eligibility()` pure function inserted before `agency_from_rank`). Run `pytest tests/test_*earned_agency* tests/test_*rank* -n 0 -q` → existing earned-agency tests must pass unchanged.
6. **Apply Section 4a-4c** (`mesh/routing.py` — new `set_skill_service()` + `set_intent_skill_map()` + `_skill_service`/`_intent_skill_map` defaults + async `score_with_skill_weight()`). Run `pytest tests/test_*hebbian* tests/test_*routing* tests/test_ad571* -n 0 -q` → all must still pass; new method is purely additive.
7. **Apply Section 5a-5c** (`cognitive/dreaming.py` — ctor 2 new kwargs, store on self, integration call `await self._reinforce_skills_for_episodes(episodes)` next to `_consolidate_trust`, helper definition). Run `pytest tests/test_*dreaming* -n 0 -q` → existing dream-cycle tests must pass; new ctor kwargs default to None.
8. **Apply Section 6** (`proactive.py` — extend skill_profile injection block at `:1796` with sibling try/except for development_goals). Run `pytest tests/test_*proactive* -n 0 -q`.
9. **Apply Section 7** (NEW `tests/test_ad428b_skill_advanced.py` — 18 tests). Add tests one at a time; confirm each passes before adding the next.
10. **Final gate:** `pytest tests/ -q -n 4 --dist=loadfile` → expect 11498 (+18 net target; window [11495, 11502]).
11. **Update tracking:**
    - `PROGRESS.md` — append CLOSED paragraph for AD-428b v1 listing the 5 features shipped + 4 features deferred with their forcing functions.
    - `docs/development/roadmap.md` — flip the AD-428b heading from `*Deferred (blocked on dependencies)*` to `*partial — v1 ships features 1-5 (composite/synergy/goals/proficiency-rank/skill-routing/dream-reinforce); features 6-9 deferred to AD-428b-i (Holodeck dep) + AD-428b-ii (per-agent ModelDescriptor dep)*`. Update the table to mark each row with v1 vs deferred status.
    - `prompts/wave-plan.yaml` (id 75) — `status: done`.
    - GH issue #38 — close with summary listing v1 features 1-5 (with test counts), deferred features 6-9 with forcing functions, and this commit hash. File AD-428b-i and AD-428b-ii GH tracking issues at this time.

## Hard-stop conditions

1. Test count delta lands outside [+15, +22]. → Triage which Section over/under-shot.
2. Existing AD-428 tests at `tests/test_skill_framework.py` regress. → Section 1d/1e (`_row_to_definition` / `register_skill`) likely catches a row shape it shouldn't. Re-verify the `"in row.keys()"` guards work for older DBs without the new columns.
3. Real working-tree changes appear in source files NOT named in this dispatch (`src/probos/config.py`, `src/probos/skill_framework.py`, `src/probos/earned_agency.py`, `src/probos/mesh/routing.py`, `src/probos/cognitive/dreaming.py`, `src/probos/proactive.py`, `tests/test_ad428b_skill_advanced.py` (NEW), plus tracking files). → Hard stop, surface to Captain.
4. Any source change to `src/probos/crew_profile.py` (`Rank.from_trust`). → DLog #5 violation. Hard-stop.
5. Any source change to existing routing decision paths (the `score()`/`record_interaction()`/`decay_all()` bodies beyond the additive setter calls). → DLog #6 violation. Hard-stop.
6. Any change to `BUILTIN_PCCS` or `ROLE_SKILL_TEMPLATES` content (populating `composite_skill_ids` or `synergy_partners` on built-ins). → Out of scope; sibling AD. Hard-stop.
7. Any change wiring `skill_service` into the runtime `DreamCycle()` constructor at `runtime.py`. → AD-428b-v territory. v1 ctor signature is defensive (defaults None) but no caller passes the new kwargs this wave. Hard-stop.
8. Any HXI / `ui/` / `routers/` change. → HXI surfacing is AD-428b-vi. Hard-stop.
9. Test boots a real `ProbOSRuntime` to validate Section 4 or Section 5 wiring. → Use `_FakeSkillService` per Wave 13/66/67/68/69/70/72/73/74 fixture precedent. Hard-stop on any `ProbOSRuntime(...)` boot in the new test file.
10. The Builder elects to ship Model-Skill Alignment, INNATE category, Holodeck assessment, or assessment_criteria "while we're here". → Force-deferred per dependency analysis. Hard-stop.

## Acceptance criteria

1. Full gate passes at 11498 ± 3 (target +18; window [+15, +22] = [11495, 11502]).
2. All Section 0–6 SEARCH/REPLACE blocks applied byte-for-byte as specified.
3. 18 new tests in `tests/test_ad428b_skill_advanced.py` all pass.
4. No file outside the dispatch's named set is modified (other than tracking files).
5. The Builder build report cites the test count delta + the eleven "what this AD does NOT change" verifications from the per-AD prompt.
6. The Builder build report explicitly cites which deferred children remain (AD-428b-i Holodeck-dependent, AD-428b-ii ModelRegistry-dependent) and what their forcing functions are.
7. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-06, HEAD `04bc430`)

The full 14-anchor verify-first table lives in the per-AD prompt at `prompts/ad-428b-skill-framework-advanced-v1.md` "Verified Against Codebase" footer. Highest-risk anchors repeated:

```
grep -n "@dataclass" src/probos/skill_framework.py | head
  54:@dataclass    # SkillDefinition
  68:@dataclass    # AgentSkillRecord
  97:@dataclass    # SkillProfile
  136:@dataclass   # QualificationRecord
  (Section 1 anchors confirmed)

grep -n "preferred_tools TEXT DEFAULT" src/probos/skill_framework.py
  378:                    "ALTER TABLE skill_definitions ADD COLUMN preferred_tools TEXT DEFAULT '[]'"
  (DLog #1 — ALTER TABLE migration precedent)

grep -n "set_tier_registry" src/probos/mesh/routing.py
  78:    def set_tier_registry(self, registry: Any) -> None:
  (Section 4a — late-bind setter precedent from AD-571a)

grep -n "self._procedure_store = procedure_store" src/probos/cognitive/dreaming.py
  103:        self._procedure_store = procedure_store  # AD-533: persistent procedure storage
  (Section 5b — DreamCycle ctor precedent for service injection)

grep -n "context\[\"skill_profile\"\]" src/probos/proactive.py
  1796:                        context["skill_profile"] = skill_summary
  (Section 6 — extension anchor next to existing AD-429b skill_profile injection)

grep -c "Rank.from_trust" src/probos -r
  20+ call sites — DLog #5 forbids modification this wave (Wave-74 precedent).

grep -rn "class Holodeck\|holodeck_" src/probos
  0 hits — AD-428b-i forced-defer rationale confirmed.

grep -n "AD-463" docs/development/roadmap.md | head -1
  4179: AD-463 (partial — ProviderABC/HebbianRouter integration deferred)
  (AD-428b-ii forced-defer rationale confirmed: per-agent ModelDescriptor not yet shipped.)
```

## Wave-75 build report addendum (to be filled by Builder at close)

- Test count delta: actual vs target +18.
- Anchor drift report (any SEARCH block that needed adaptation due to HEAD movement between draft and build).
- Phantom-API pre-check result on prompt body (expected: 0 NEW phantoms; new methods/fields are intra-prompt-introductions = same FP class as Waves 27-74).
- Pre-commit deletion sanity (max ~10 deletions any single file expected — additive-only changes).
- GH tracking issues filed for AD-428b-i and AD-428b-ii (with their forcing functions repeated in the issue body).
