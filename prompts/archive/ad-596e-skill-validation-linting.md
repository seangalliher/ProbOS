# AD-596e: Skill Validation + Instruction Linting

## Context

AD-596a through 596d delivered the cognitive skill catalog, intent routing, skill-registry bridge, and external skill import. Skills are now parseable, discoverable, importable, and enrichable — but there is **zero semantic validation**.

`parse_skill_file()` checks that YAML is well-formed and `name`/`description` fields exist. That's it. There is no check that:
- The SKILL.md conforms to the AgentSkills.io spec (field names, name format, length limits)
- ProbOS metadata values are valid (department exists in ontology, rank is a legal value)
- Instructions contain stale references (hardcoded callsigns that will break after naming ceremony)
- `skill_id` maps to a real SkillRegistry entry (SkillBridge does this at startup, but no on-demand check)

BF-146 proved that natural-language instructions have the same defect surface as code — a stale callsign reference causes real behavioral failures. This AD delivers the validation layer.

## Dependencies

- **AD-596d** — `import_skill()`, `enrich_skill()`, `remove_skill()`, `/skill` shell command all exist
- **AD-596c** — `SkillBridge.validate_and_sync()` already validates `skill_id` at startup

## Objective

1. **AgentSkills.io spec validation** — native implementation of structural checks from the AgentSkills.io standard (no external library)
2. **ProbOS-specific validation** — department, rank, skill_id cross-references against live ontology
3. **Callsign linting** — detect hardcoded agent callsigns in SKILL.md instruction body (BF-146 class)
4. **Validation API** — on-demand `validate_skill()` method, REST endpoint, shell subcommand
5. **Validated enrichment** — wire validation into `enrich_skill()` flow (warn, don't block)

---

## Design Decisions

### D1: `validate_skill()` on CognitiveSkillCatalog

Add `validate_skill(name) -> SkillValidationResult` to `CognitiveSkillCatalog`.

**SkillValidationResult dataclass:**
```python
@dataclass
class SkillValidationResult:
    """Result of validating a cognitive skill."""
    skill_name: str
    valid: bool  # True if zero errors (warnings are OK)
    errors: list[str]    # Must fix
    warnings: list[str]  # Should fix (callsigns, unmatched skill_id, etc.)

    def to_dict(self) -> dict:
        return {
            "skill_name": self.skill_name,
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }
```

**Validation pipeline — three layers, run in sequence:**

**Layer 1: AgentSkills.io structural validation (native)**

Implement the AgentSkills.io spec rules directly — no external library. These rules are derived from the `skills-ref` reference implementation (Apache 2.0) and are stable, simple checks.

Add a module-level function `_validate_spec(entry, skill_dir) -> list[str]` that returns a list of error strings:

| Rule | Check | Error message |
|------|-------|---------------|
| Name format | `re.fullmatch(r'[a-z0-9]([a-z0-9-]*[a-z0-9])?', name)` and no `--` | `"Name must be lowercase alphanumeric with hyphens, no leading/trailing/consecutive hyphens"` |
| Name length | `len(name) <= 64` | `"Name exceeds 64 characters"` |
| Name matches directory | `entry.name == entry.skill_dir.name` | `"Name '{name}' does not match directory name '{dir}'"` |
| Description length | `len(description) <= 1024` | `"Description exceeds 1024 characters"` |
| Compatibility length | `len(compatibility) <= 500` (if non-empty) | `"Compatibility exceeds 500 characters"` |

**Why native, not `skills-ref`:** The spec rules are 5 checks totaling ~15 lines. The `skills-ref` library would add two transitive dependencies (`strictyaml`, `click`), introduce a second YAML parser conflicting with ProbOS's `yaml.safe_load`, and create uncontrolled breaking-change risk on dependency updates. The spec is the contract; the library is an implementation detail. If the spec evolves, ProbOS updates these checks alongside `parse_skill_file()` and the catalog schema — validation rules are the smallest part of that adaptation.

**Coexistence with `parse_skill_file()`:** The parser is permissive (Postel's Law — liberal in what you accept). The validator is strict (conservative in what you produce). A skill can be loadable (passes `parse_skill_file()`) but not spec-compliant (fails `_validate_spec()`). This is correct — the parser ensures the system works; the validator ensures interoperability with the AgentSkills.io ecosystem.

**Layer 2: ProbOS metadata validation**

Cross-reference ProbOS-specific metadata against live sources:

| Field | Validation | Source | Severity |
|-------|-----------|--------|----------|
| `department` | Must be `*` or a valid department ID | `_AGENT_DEPARTMENTS` values in `standing_orders.py` — extract unique set: `{bridge, engineering, science, medical, security, operations}` | error |
| `min_rank` | Must be a valid rank key | `_RANK_ORDER` keys in `skill_catalog.py`: `{ensign, lieutenant, commander, senior_officer}` | error |
| `skill_id` (if non-empty) | Should exist in SkillRegistry | `runtime.skill_registry.list_skills()` (if available) | warning |
| `min_proficiency` | Must be 1–5 (Dreyfus levels) | Constant range | error |

**Implementation:** The catalog itself doesn't have direct access to `skill_registry` or runtime. Pass an optional `validation_context` dict to `validate_skill()`:
```python
async def validate_skill(
    self,
    name: str,
    validation_context: dict | None = None,
) -> SkillValidationResult:
```

Where `validation_context` can include:
- `"valid_departments"`: `set[str]` — extracted from ontology/standing_orders
- `"valid_skill_ids"`: `set[str]` — from SkillRegistry
- `"known_callsigns"`: `set[str]` — from CallsignRegistry

If `validation_context` is None, skip cross-reference checks (Layer 2 metadata + Layer 3 callsigns degrade to structural-only). The caller (API endpoint, shell command) builds the context from runtime.

**Layer 3: Callsign linting (BF-146 class)**

Scan the SKILL.md markdown body (below frontmatter) for hardcoded agent callsigns.

**How it works:**
1. Get the instruction body via existing `get_skill_body(skill_md_path)` (already exists in `skill_catalog.py`)
2. Get `known_callsigns` from `validation_context` — these come from `CallsignRegistry.all_callsigns()`, which returns `{agent_type: display_callsign}`. Extract the callsign values (e.g., `"Meridian"`, `"Echo"`, `"LaForge"`).
3. For each callsign, case-insensitive word-boundary search in the instruction text
4. Each match produces a **warning** (not error) — the skill is still loadable, but the instruction may break if the agent self-names differently

**Pattern:** Use `re.compile(r'\b' + re.escape(callsign) + r'\b', re.IGNORECASE)` for each callsign. This prevents false positives on substrings (e.g., "forge" matching "LaForge").

**Why warning not error:** Callsign references may be intentional in some scenarios (e.g., a skill mentioning "coordinate with the Counselor" is fine as a role reference; "tell Echo to..." is the problematic pattern). Start as warnings; upgrade to errors in a future AD if warranted.

### D2: `validate_all()` on CognitiveSkillCatalog

Add `validate_all(validation_context) -> list[SkillValidationResult]` — runs `validate_skill()` for every skill in the catalog. Returns the full list. Used by `/skill validate` with no arguments.

### D3: Validated Enrichment — Wire into `enrich_skill()`

After `enrich_skill()` writes the metadata and re-registers, run `validate_skill()` on the result and **log warnings** (not block). The enrichment always succeeds — validation is advisory.

**Implementation:** Add an optional `validation_context` parameter to `enrich_skill()`:
```python
async def enrich_skill(
    self,
    name: str,
    metadata: dict,
    validation_context: dict | None = None,
) -> CognitiveSkillEntry:
```

After the existing register step, if `validation_context` is provided:
```python
result = await self.validate_skill(name, validation_context)
if result.warnings:
    logger.warning("AD-596e: Enriched skill '%s' has warnings: %s", name, result.warnings)
if result.errors:
    logger.warning("AD-596e: Enriched skill '%s' has errors: %s", name, result.errors)
```

Return the entry as before. The validation result is not returned (to keep the existing return type stable). The warnings appear in logs and the user can run `/skill validate <name>` to see them.

### D4: REST API — Validation Endpoints

Add to `routers/skills.py`:

| Method | Path | Action |
|--------|------|--------|
| `GET` | `/api/skills/catalog/{name}/validate` | Validate a single skill |
| `GET` | `/api/skills/catalog/validate` | Validate all skills |

**Response format:**
```json
{
  "results": [
    {
      "skill_name": "communication-discipline",
      "valid": true,
      "errors": [],
      "warnings": ["Callsign 'Echo' found in instruction body"]
    }
  ],
  "summary": {"total": 1, "valid": 1, "invalid": 0}
}
```

**Building validation_context in the endpoint:**
```python
context = _build_validation_context(runtime)
```

Helper function in `routers/skills.py`:
```python
def _build_validation_context(runtime: Any) -> dict:
    """Build validation cross-reference context from runtime."""
    ctx: dict = {}
    # Valid departments from standing_orders
    from probos.cognitive.standing_orders import _AGENT_DEPARTMENTS
    ctx["valid_departments"] = set(_AGENT_DEPARTMENTS.values()) | {"*"}
    # Valid ranks from skill_catalog
    from probos.cognitive.skill_catalog import _RANK_ORDER
    ctx["valid_ranks"] = set(_RANK_ORDER.keys())
    # Valid skill_ids from registry
    if runtime.skill_registry:
        ctx["valid_skill_ids"] = {s.skill_id for s in runtime.skill_registry.list_skills()}
    # Known callsigns
    if runtime.callsign_registry:
        ctx["known_callsigns"] = set(runtime.callsign_registry.all_callsigns().values())
    return ctx
```

### D5: Shell Command — `/skill validate`

Add `validate` subcommand to the existing `/skill` command in `commands_skill.py`:

| Subcommand | Action |
|------------|--------|
| `/skill validate` | Validate all skills, show summary |
| `/skill validate <name>` | Validate a specific skill |

**Output format:** Rich table with columns: Skill, Status (valid/invalid), Errors, Warnings. Color-coded: green for valid, red for errors, yellow for warnings.

**Update the help text** in `cmd_skill()` to include `validate` in the subcommand list and update the usage line.

---

## Prior Work Absorbed

| Source | What's Absorbed |
|--------|----------------|
| AgentSkills.io spec (`skills-ref` source, Apache 2.0) | Spec rules implemented natively: name format regex, length limits, directory name match. Referenced as spec source, not imported as dependency. |
| BF-146 (standing orders callsign bug) | Callsign linting pattern — word-boundary regex against `CallsignRegistry.all_callsigns()` values |
| `_RANK_ORDER` in skill_catalog.py (line 27) | Valid ranks: `{ensign, lieutenant, commander, senior_officer}` — used for rank validation |
| `_AGENT_DEPARTMENTS` in standing_orders.py (line 36) | Valid departments: `{bridge, engineering, science, medical, security, operations}` — used for department validation |
| `SkillBridge.validate_and_sync()` (skill_bridge.py:41) | Already validates `skill_id` against SkillRegistry at startup — 596e adds on-demand check |
| `CallsignRegistry.all_callsigns()` (crew_profile.py:379) | Returns `{agent_type: display_callsign}` — source for callsign linting |
| `get_skill_body()` in skill_catalog.py (line 130) | Already exists — extracts markdown body below frontmatter for callsign scanning |
| AD-596d `enrich_skill()` (skill_catalog.py:386) | Enrichment is mechanical writes only — 596e adds post-enrichment validation (advisory) |
| AD-596d `/skill` command (commands_skill.py) | Existing 6 subcommands — add `validate` as 7th |

## Things NOT in Scope (AD-596e)

| Item | Why Deferred |
|------|-------------|
| File path verification in instructions | Requires codebase indexing; premature with 1 skill. Future AD when corpus grows. |
| Method name verification in instructions | Same — requires AST analysis. Future AD. |
| Standing order / skill boundary enforcement | Requires NLP classifier to distinguish "who you are" vs "what you can do". Future AD. |
| Pre-commit hook for CI | Useful only when skills are version-controlled in CI pipelines. Defer to when repo has >5 skills. |
| `probos-enrich` standalone CLI tool | `/skill enrich` already exists. Standalone CLI adds no value over shell command. |
| Instruction staleness detection (beyond callsigns) | Callsign detection is the highest-value subset. Broader staleness requires codebase cross-referencing. Future AD. |

---

## Engineering Principles Compliance

| Principle | Applied |
|-----------|---------|
| Single Responsibility | `validate_skill()` validates. `enrich_skill()` writes. Validation is advisory on enrichment, not blocking. |
| Open/Closed | Adds `validate_skill()`, `validate_all()`, `_validate_spec()` without modifying existing `parse_skill_file()`, `register()`, or `scan_and_register()` |
| Dependency Inversion | `validation_context` dict injected by caller — catalog doesn't import runtime, CallsignRegistry, or SkillRegistry directly |
| Law of Demeter | Caller builds `validation_context` from runtime; `validate_skill()` never reaches through runtime internals |
| Fail Fast | Validation returns all errors/warnings in one pass. Invalid skill files surface immediately on `/skill validate`. |
| Interface Segregation | `SkillValidationResult` is a narrow dataclass. Callers get typed results, not raw strings. |
| DRY | Reuses `get_skill_body()` for callsign scanning, reuses `_RANK_ORDER` for rank validation, reuses `_AGENT_DEPARTMENTS` for department validation. No duplicate parsing logic — validator reads from catalog cache, not re-parsing files. |
| Cloud-Ready Storage | No new database. Validation is stateless — reads catalog cache + skill files. |

---

## Files Summary

| # | File | Action |
|---|------|--------|
| 1 | `src/probos/cognitive/skill_catalog.py` | MODIFY — add `SkillValidationResult`, `_validate_spec()`, `validate_skill()`, `validate_all()`, optional `validation_context` param on `enrich_skill()` |
| 2 | `src/probos/routers/skills.py` | MODIFY — add `_build_validation_context()`, GET `/catalog/{name}/validate`, GET `/catalog/validate` |
| 3 | `src/probos/experience/commands/commands_skill.py` | MODIFY — add `validate` subcommand, update help text |
| 4 | `tests/test_ad596e_skill_validation.py` | **CREATE** — validation tests |

---

## Test Plan (~30 tests)

### Layer 1 — AgentSkills.io spec validation (native):
1. Valid skill (lowercase name, within limits) → no errors
2. Name with uppercase letters → error
3. Name exceeding 64 chars → error
4. Name with consecutive hyphens (`my--skill`) → error
5. Name with leading hyphen → error
6. Name not matching directory name → error
7. Description exceeding 1024 chars → error
8. Compatibility exceeding 500 chars → error
9. Valid name with hyphens and digits (`my-skill-2`) → no error

### Layer 2 — ProbOS metadata validation:
10. Valid department (`"science"`) → no error
11. Wildcard department (`"*"`) → no error
12. Invalid department (`"starfleet"`) → error
13. Valid rank (`"lieutenant"`) → no error
14. Invalid rank (`"admiral"`) → error
15. Valid min_proficiency (1-5) → no error
16. Invalid min_proficiency (0, 6, -1) → error
17. Non-empty skill_id exists in SkillRegistry → no warning
18. Non-empty skill_id NOT in SkillRegistry → warning
19. Empty skill_id → no warning (ungoverned is fine)
20. No validation_context → Layers 2-3 skipped gracefully

### Layer 3 — Callsign linting:
21. Instruction body contains hardcoded callsign ("LaForge") → warning
22. Instruction body contains callsign as substring (not word boundary) → no warning
23. Instruction body with no callsigns → no warnings
24. Multiple callsigns in body → multiple warnings
25. Case-insensitive match ("echo" vs "Echo") → warning
26. No known_callsigns in context → Layer 3 skipped

### validate_all():
27. Multiple skills, mixed validity → returns all results
28. Empty catalog → returns empty list

### Enrichment validation:
29. Enrich with valid metadata + validation_context → no warnings logged
30. Enrich with invalid department + validation_context → warning logged, enrichment still succeeds
31. Enrich without validation_context → no validation run (backward compatible)

### Shell command:
32. `/skill validate` with no args → validates all, shows summary table
33. `/skill validate <name>` → validates single skill, shows detail

### API endpoints:
34. GET `/catalog/{name}/validate` → returns validation result
35. GET `/catalog/validate` → returns all results with summary
