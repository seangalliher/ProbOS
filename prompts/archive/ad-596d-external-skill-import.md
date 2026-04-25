# AD-596d: External Skill Import — Draft

## Context

AD-596a/b/c delivered the cognitive skill catalog, intent routing, and skill-registry bridge. All skills currently come from `config/skills/*/SKILL.md` — hand-authored internal skills with ProbOS metadata extensions.

The AgentSkills.io ecosystem has 30+ tool integrations (Claude Code, Cursor, VS Code, Gemini CLI, etc.) producing standard SKILL.md files. Real external skills (e.g., FastAPI's `.agents/skills/fastapi/SKILL.md` shipping inside pip packages) contain only `name` and `description` in frontmatter — no `metadata`, no `license`, no ProbOS governance fields.

AD-596d enables ProbOS to consume these external skills.

## Objective

1. **Import function**: `import_external_skill(source_path)` — validate, copy into `config/skills/`, register with `origin: external`
2. **Discovery**: Auto-discover skills from pip-installed packages (`.agents/skills/*/SKILL.md` convention)
3. **Ungoverned mode**: External skills with no ProbOS metadata are available to all crew, all departments, all ranks — no proficiency gating
4. **API + Shell**: REST endpoint and shell command for import/discovery operations
5. **Origin tracking**: Catalog properly distinguishes `internal` vs `external` skills

---

## Design Decisions

### D1: Import Function on CognitiveSkillCatalog

Add `import_skill(source_path, origin="external")` to `CognitiveSkillCatalog`.

**Behavior:**
1. Validate: `parse_skill_file(source_path / "SKILL.md")` must succeed — fail fast if invalid
2. Check duplicate: if skill `name` already in catalog, reject with error (no silent overwrite)
3. Copy: `shutil.copytree(source_path, self._skills_dir / entry.name)` — skill name becomes directory name
4. Set origin: `entry.origin = origin` (default `"external"`)
5. Register: `await self.register(entry)` — puts in cache + SQLite
6. Return the registered entry

**Rationale:** Copy into `config/skills/` rather than referencing in-place. Skills become part of the ship's configuration — portable, version-controlled, survive dependency updates. If a pip package updates its skill, ProbOS keeps the imported snapshot until explicitly re-imported.

**Engineering Principles:**
- SRP: import function does validation + copy + register. No enrichment (that's separate).
- DRY: Reuses `parse_skill_file()` for validation, `register()` for persistence.
- Fail Fast: Invalid SKILL.md rejected immediately, no partial state.

### D2: Fix `origin` Field — Never Set to "external"

**Bug found:** `parse_skill_file()` at skill_catalog.py:126 unconditionally sets `origin="internal"`. There is no code path that sets `origin="external"`. The `origin` column exists in SQLite but is always `"internal"`.

**Fix:** `import_skill()` overrides `entry.origin = origin` after parsing. The `parse_skill_file()` default of `"internal"` remains correct for `scan_and_register()` which only processes the local `config/skills/` directory.

### D3: Package Discovery — `.agents/skills/` Convention

Add `discover_package_skills()` to `CognitiveSkillCatalog`.

**Behavior:**
1. Walk `sys.path` site-packages directories
2. For each installed package, check for `.agents/skills/*/SKILL.md`
3. For each found skill, call `parse_skill_file()` to validate
4. Return list of `(package_name, skill_entry, source_path)` tuples — discovery only, no auto-import
5. User decides which to import via shell command or API

**Rationale:** Discovery is separate from import. Auto-importing every pip-installed skill would violate the Captain's authority principle — the Captain (or architect) must approve what capabilities the crew has access to. Discovery surfaces what's available; import is the deliberate act.

**Implementation:**
```python
import importlib.metadata
import site

def discover_package_skills(self) -> list[dict]:
    """Discover SKILL.md files shipped with installed pip packages."""
    results = []
    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        sp_path = Path(sp)
        if not sp_path.exists():
            continue
        for skill_md in sp_path.rglob(".agents/skills/*/SKILL.md"):
            entry = parse_skill_file(skill_md)
            if entry:
                # Infer package name from path
                pkg_root = skill_md.parent
                while pkg_root.parent != sp_path and pkg_root.parent != pkg_root:
                    pkg_root = pkg_root.parent
                results.append({
                    "package": pkg_root.name,
                    "skill_name": entry.name,
                    "description": entry.description,
                    "source_path": str(skill_md.parent),
                    "has_probos_metadata": bool(entry.skill_id or entry.department != "*"),
                })
    return results
```

**Note:** This is a synchronous function — filesystem walk, no async I/O. Keep it simple. Called on-demand, not at startup.

### D4: Enrichment — `enrich_skill()` Method

Add `enrich_skill(name, metadata)` to update ProbOS metadata on an imported external skill.

**Behavior:**
1. Lookup entry in catalog by name
2. Update fields: `department`, `skill_id`, `min_proficiency`, `min_rank`, `intents`
3. Rewrite the SKILL.md frontmatter to include `metadata:` block
4. Re-register in catalog (cache + SQLite)
5. If SkillBridge is available, re-validate the mapping

**Why on CognitiveSkillCatalog and not a separate service:** Enrichment is metadata update on an existing catalog entry. No new responsibilities — the catalog already manages entries. A separate `probos-enrich` CLI command is deferred to AD-596e (validation + linting), which needs the `skills-ref` library.

**Scope constraint:** The enrichment method does field updates only. It does NOT validate the quality of the metadata values (e.g., whether `skill_id` exists in SkillRegistry, whether `department` is valid in the ontology). That validation is AD-596e's job. This is the mechanical write operation.

### D5: REST API Endpoints

Add to `routers/skills.py`:

| Method | Path | Action |
|--------|------|--------|
| `POST` | `/api/skills/catalog/import` | Import a skill from a source path |
| `GET` | `/api/skills/catalog/discover` | Discover pip-installed skills |
| `PUT` | `/api/skills/catalog/{name}/enrich` | Add/update ProbOS metadata on a skill |

**Import request body:** `{"source_path": "/path/to/skill-dir"}`
**Enrich request body:** `{"department": "science", "skill_id": "...", "min_proficiency": 3, "min_rank": "lieutenant", "intents": ["intent_a", "intent_b"]}`

### D6: Shell Command — `/skill`

Add `/skill` command to the ProbOS shell with subcommands:

| Subcommand | Action |
|------------|--------|
| `/skill list` | List all cognitive skills (name, origin, department) |
| `/skill discover` | Show pip-installed skills available for import |
| `/skill import <path>` | Import a skill from a directory path |
| `/skill import <package:skill>` | Import a discovered pip skill by `package:skill` shorthand |
| `/skill info <name>` | Show full skill details |
| `/skill enrich <name> --dept <dept> --intents <i1 i2>` | Add ProbOS metadata |
| `/skill remove <name>` | Remove a skill from catalog + delete directory |

**Pattern:** Follows `/qualify` and `/alert` command patterns — `ShellCommandHandler` with subcommand dispatch.

### D7: Skill Removal

Add `remove_skill(name)` to `CognitiveSkillCatalog`.

**Behavior:**
1. Check entry exists, check `origin == "external"` (cannot remove internal skills via this method)
2. Delete from SQLite
3. Remove from cache
4. Delete the skill directory from `config/skills/`
5. If agents have this skill's intents subscribed, they'll lose them on next restart (acceptable — cold-start re-onboarding handles this)

**Safety:** Only external skills can be removed this way. Internal skills are part of the ship's configuration — removing them requires manual file deletion by the architect.

### D8: Frontmatter Rewrite for Enrichment

When `enrich_skill()` rewrites SKILL.md frontmatter:

1. Read file, parse existing frontmatter
2. Merge new metadata fields into existing (or create) `metadata:` block
3. Preserve all non-ProbOS fields (name, description, license, compatibility, any custom fields)
4. Preserve the markdown body below frontmatter exactly as-is
5. Write back with `---` delimiters

This is low-risk because external skills are copies, not originals. If the rewrite corrupts something, the user can re-import from the source.

---

## Prior Work Absorbed

| Source | What's Absorbed |
|--------|----------------|
| FastAPI `.agents/skills/` convention | Package discovery path pattern (D3) |
| `origin` field never set to "external" (latent bug) | Fixed as part of import flow (D2) |
| Existing `scan_and_register()` rglob pattern | Import copies into `config/skills/` so existing scan picks it up (D1) |
| Existing `POST /catalog/rescan` endpoint | Import calls `register()` directly — rescan is for manual recovery (D1) |
| `/qualify` shell command pattern (AD-566f) | Shell command structure for `/skill` (D6) |
| AD-596c SkillBridge | Enriched skills with `skill_id` get bridge validation on next startup (D4) |
| `_RESET_SUBDIRS` includes "skills" data | External skills in `config/skills/` are config, not data — survive reset (distinction) |

## Things NOT in Scope (AD-596d)

| Item | Belongs To |
|------|-----------|
| SKILL.md structural validation (`skills-ref` library) | AD-596e |
| Ontology cross-reference validation (department exists?) | AD-596e |
| Callsign detection in instructions (BF-146 class) | AD-596e |
| Instruction staleness detection | AD-596e |
| `probos-enrich` CLI tool | AD-596e (extends D4 with validation) |
| Remote skill import (URL / Git) | Future — 596d is local filesystem only |
| Skill marketplace | Commercial (Nooplex) |

---

## Engineering Principles Compliance

| Principle | Applied |
|-----------|---------|
| Single Responsibility | Import function: validate + copy + register. Discovery: find + report. Enrichment: update metadata. Three distinct operations |
| Open/Closed | Extends CognitiveSkillCatalog with new methods, doesn't modify existing scan/register flow |
| Dependency Inversion | Import uses `parse_skill_file()` and `register()` — public APIs, not internals |
| Law of Demeter | Shell command talks to catalog via runtime, not reaching into internals |
| Fail Fast | Invalid SKILL.md rejected before copy. Duplicate names rejected. No partial state |
| Interface Segregation | Discovery returns data dicts, not full entries — caller decides what to do |
| DRY | Reuses parse_skill_file, register, list_entries. No duplicate parsing logic |
| Cloud-Ready Storage | No new database — uses existing cognitive_skills.db via ConnectionFactory |

---

## Files Summary

| # | File | Action |
|---|------|--------|
| 1 | `src/probos/cognitive/skill_catalog.py` | MODIFY — `import_skill()`, `discover_package_skills()`, `enrich_skill()`, `remove_skill()` |
| 2 | `src/probos/routers/skills.py` | MODIFY — 3 new endpoints (import, discover, enrich) |
| 3 | `src/probos/experience/commands/commands_skill.py` | **CREATE** — `/skill` shell command |
| 4 | `src/probos/experience/shell.py` | MODIFY — register `/skill` command |
| 5 | `tests/test_ad596d_external_skill_import.py` | **CREATE** — import, discovery, enrichment, removal tests |

---

## Test Plan (~20-25 tests)

### Import tests:
1. Import valid external skill → copies to config/skills, origin="external"
2. Import skill with no metadata block → ungoverned defaults (dept=*, rank=ensign, etc.)
3. Import skill with existing name → rejected with error
4. Import from invalid path → fails fast, no side effects
5. Import skill with invalid SKILL.md (no name) → rejected
6. Import skill with full ProbOS metadata → governs normally
7. Imported skill appears in list_entries() and find_by_intent()

### Discovery tests:
8. Discover finds skill in mock site-packages `.agents/skills/` path
9. Discover reports has_probos_metadata correctly
10. Discover with no installed skills → empty list
11. Discover skips invalid SKILL.md files gracefully

### Enrichment tests:
12. Enrich adds metadata to external skill → frontmatter rewritten
13. Enrich preserves existing non-ProbOS fields (license, compatibility)
14. Enrich preserves markdown body exactly
15. Enrich updates catalog cache and SQLite
16. Enrich on nonexistent skill → error
17. Enrich partial fields (only department) → other fields unchanged

### Removal tests:
18. Remove external skill → deleted from catalog + filesystem
19. Remove internal skill → rejected
20. Remove nonexistent skill → error

### Shell command tests:
21. `/skill list` returns skills with origin column
22. `/skill import <path>` triggers import_skill
23. `/skill info <name>` shows full details
24. `/skill remove <name>` triggers removal

### API tests:
25. POST /catalog/import with valid body
26. GET /catalog/discover returns discovered skills
27. PUT /catalog/{name}/enrich updates metadata
