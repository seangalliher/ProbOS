# Era IV: Evolution — The Ship Evolves

*Phases 30+: Self-Improvement Pipeline, Security Team, Engineering Team, Operations Team*

This era is where ProbOS begins to evolve itself. Research agents discover capabilities, architect agents spec them, builder agents implement them, QA agents validate them — all with a human approval gate. The crew teams mature from pool groups into fully autonomous departments. The ship doesn't just sail — it upgrades itself.

See [docs/development/roadmap.md](docs/development/roadmap.md) for the crew structure and phase details.

---

## Phase 32f: Architect Deep Localize + CodebaseIndex Structured Tools (AD-311/312)

| AD | Decision |
|----|----------|
| AD-311 | ArchitectAgent Layer 2 replaced with 3-step localize pipeline: (2a) fast-tier LLM selects up to 8 most relevant files from 20 candidates, (2b) full source read of selected files with 4000-line budget and 500-line per-file cap, (2c) test file discovery via `find_tests_for()`, caller analysis via `find_callers()`, and verified API surface via `get_full_api_surface()`. Instructions hardened with rule #6 requiring API method verification against the API Surface section. |
| AD-312 | CodebaseIndex gains three structured query methods: `find_callers(method_name)` with caching for cross-file reference search, `find_tests_for(file_path)` using naming conventions, `get_full_api_surface()` exposing the complete `_api_surface` dict. `_KEY_CLASSES` expanded with CodebaseIndex, PoolGroupRegistry, Shell. |

**Status:** Complete — 22 new Python tests (15 architect + 7 codebase_index), 1860 Python + 21 Vitest total

## Phase 32g: CodebaseIndex Import Graph + Architect Pattern Discovery (AD-315)

| AD | Decision |
|----|----------|
| AD-315 | CodebaseIndex builds forward and reverse import graphs at startup using AST-extracted `import`/`from X import Y` statements (probos-internal only). New methods: `get_imports(file_path)` returns internal files imported by a file, `find_importers(file_path)` returns files that import a given file. ArchitectAgent Layer 2a+ traces imports of LLM-selected files and expands `selected_paths` up to 12 total. Layer 2c appends "Import Graph" section showing import/imported-by relationships. Instructions updated with import-awareness in context listing and DESIGN PROCESS step 3. |

**Status:** Complete — 11 new Python tests (3 architect + 8 codebase_index), 1871 Python + 21 Vitest total

## Phase 32h: Builder File Edit Support (AD-313)

| AD | Decision |
|----|----------|
| AD-313 | Builder MODIFY mode — search-and-replace (`===SEARCH===`/`===REPLACE===`/`===END REPLACE===`) execution for existing files. `_parse_file_blocks()` parses SEARCH/REPLACE pairs within MODIFY blocks. `execute_approved_build()` applies replacements sequentially (first occurrence only). `perceive()` reads `target_files` so the LLM sees current content for accurate SEARCH blocks. `_validate_python()` runs `ast.parse()` on .py files after write/modify. `_build_user_message()` includes target file content. Old `===AFTER LINE:===` format deprecated with warning. `BuildResult.files_modified` now populated |

**Status:** Complete — 20 new Python tests (6 parse + 6 execute + 3 validate + 3 perceive + 2 existing updated), 1891 Python + 21 Vitest total

## Phase 32i: Ship's Computer Identity (AD-317)

**Decision:** AD-317 — The Decomposer is the Ship's Computer. LCARS-era identity (TNG/Voyager): calm, precise, authoritative, never fabricates. Grounding rules prevent confabulation about unbuilt features. Dynamic capability summary from registered intents. Runtime state injection for accurate status reports. Hardcoded examples cleaned of fabricated capabilities.

**Status:** Phase 32i complete — 1899 Python + 21 Vitest

## Self-Knowledge Grounding Progression (AD-318, AD-319, AD-320)

Progression: AD-317 (rules) → AD-318 (data) → AD-319 (verification) → AD-320 (delegation).

| AD | Title | Status |
|----|-------|--------|
| AD-318 | SystemSelfModel — structured runtime facts dataclass, replaces ad-hoc runtime_summary | Planned |
| AD-319 | Pre-Response Verification — Decomposer validates its own output against SystemSelfModel before responding | Planned |
| AD-320 | Introspection Delegation — self-knowledge questions route to IntrospectionAgent first | Planned |

## Phase 32j: Builder Test-Fix Loop (AD-314)

**Decision:** AD-314 — Builder retries test failures via LLM-driven fix loop (2 attempts max). Extracted `_run_tests()` helper, `_build_fix_prompt()` for fix context. Two flaky network tests fixed with proper mocks.

**Status:** Phase 32j complete — 1906 Python + 21 Vitest

## Phase 32k: Escalation Tier 3 Timeout (AD-325)

**Decision:** AD-325 — Tier 3 `user_callback` wrapped in `asyncio.wait_for(timeout=user_timeout)`. Default 120s. Returns unresolved on timeout. User-wait seconds accumulated for DAG deadline accounting.

**Status:** Phase 32k complete — 1911 Python + 21 Vitest

## Phase 32l: API Task Lifecycle & WebSocket Hardening (AD-326)

**Decision:** AD-326 — Managed `_background_tasks` set with `_track_task()` helper (7 call sites), `_safe_send()` for WebSocket error handling, `GET /api/tasks` status endpoint, FastAPI lifespan shutdown drain.

**Status:** Phase 32l complete — 1916 Python + 21 Vitest

## Phase 32m: CodeValidator Hardening (AD-327)

**Decision:** AD-327 — Multi-agent rejection in `_check_schema()`, class-body side effect scanning via `_check_class_body_side_effects()`.

**Status:** Phase 32m complete — 1920 Python + 21 Vitest

## Phase 32n: Self-Mod Durability & Bloom Fix (AD-328)

**Decision:** AD-328 — Post-deployment failures logged and propagated as warnings. Self-mod bloom uses agent_id for accurate targeting.

**Status:** Phase 32n complete — 1923 Python + 22 Vitest

## Phase 32o: HXI Canvas Resilience & Component Tests (AD-329)

**Decision:** AD-329 — Cached pool centers, reduced reactive subscriptions, component tests for canvas logic.

**Status:** Phase 32o complete — 1923 Python + 30 Vitest

## Phase 32p: Architect Proposal Validation + Pattern Recipes (AD-316a)

**Decision:** AD-316a — Advisory `_validate_proposal()` with 6 programmatic checks (required fields, test_files, file tree paths, priority, description length). Pattern Recipes for NEW AGENT, NEW SLASH COMMAND, NEW API ENDPOINT appended to instructions.

**Status:** Phase 32p complete — 1937 Python + 30 Vitest

## Phase 32q: SystemSelfModel (AD-318)

**Decision:** AD-318 — `SystemSelfModel` dataclass replaces ad-hoc `_build_runtime_summary()`. Structured snapshot of topology, health, and identity serialized to compact LLM context. Error and capability gap tracking wired into runtime.

**Status:** Phase 32q complete — 1946 Python + 30 Vitest

## Phase 32r: Pre-Response Verification (AD-319)

**Decision:** AD-319 — `_verify_response()` fact-checks LLM responses against SystemSelfModel with 5 regex checks (pool/agent counts, departments, pools, mode). Non-blocking footnote appended on violations. Wired into no-nodes and reflection paths.

**Status:** Phase 32r complete — 1960 Python + 30 Vitest

## Phase 32s: Introspection Delegation (AD-320)

**Decision:** AD-320 — `_grounded_context()` on IntrospectionAgent builds detailed verified text from SystemSelfModel. 4 intent handlers enriched with `grounded_context` key. REFLECT_PROMPT treats it as VERIFIED SYSTEM FACTS. `_summarize_node_result()` preserves grounded context outside truncation boundary. Level 4: delegation.

**Status:** Phase 32s complete — 1972 Python + 30 Vitest
