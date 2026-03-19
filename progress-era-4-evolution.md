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

## Phase 32t: BuildBlueprint & ChunkSpec — Pattern Buffer (AD-330)

**Decision:** AD-330 — Transporter Pattern data structures: `ChunkSpec` (parallel work unit with DAG dependencies), `ChunkResult` (Structured Information Protocol with confidence 1-5), `BuildBlueprint` (wraps BuildSpec with interface contracts, shared context, chunk hints, DAG validation via Kahn's algorithm, ready-chunk scheduler). `create_blueprint()` factory. Pure data, no I/O.

**Status:** Phase 32t complete — 1989 Python + 30 Vitest

## Phase 32u: ChunkDecomposer — Dematerializer (AD-331)

**Decision:** AD-331 — `decompose_blueprint()` async function: fast-tier LLM decomposes BuildBlueprint into ChunkSpecs. AST outlines + CodebaseIndex imports for structural analysis. JSON parse with int/string dep normalization. DAG validation + coverage gap filling. `_fallback_decompose()` for LLM failure/bad JSON/cycles. `_build_chunk_context()` for per-chunk context (contracts, imports, outline).

**Status:** Phase 32u complete — 2003 Python + 30 Vitest

## Phase 32v: Parallel Chunk Execution — Matter Stream (AD-332)

**Decision:** AD-332 — `execute_chunks()` wave-based parallel execution via `asyncio.gather()`. Independent chunks concurrent, dependent chunks wait. `_execute_single_chunk()` with deep-tier LLM, asyncio.wait_for timeout, configurable retry. `_build_chunk_prompt()` assembles focused per-chunk prompt. `_parse_chunk_response()` extracts file blocks, DECISIONS, CONFIDENCE (1-5 clamped). Partial success valid.

**Status:** Phase 32v complete — 2018 Python + 30 Vitest

## Phase 32w: ChunkAssembler — Rematerializer (AD-333)

**Decision:** AD-333 — `assemble_chunks()` merges ChunkResults into `_parse_file_blocks()` format. Groups by path+mode, confidence-sorted. `_merge_create_blocks()` deduplicates imports, concatenates bodies. MODIFY blocks: concatenated replacement lists. `assembly_summary()` for logging/HXI. Zero-LLM, partial assembly valid.

**Status:** Phase 32w complete — 2031 Python + 30 Vitest

## Phase 32x: Interface Validator — Heisenberg Compensator (AD-334)

**Decision:** AD-334 — `validate_assembly()` with 5 zero-LLM checks: syntax validity, duplicate defs, empty MODIFY search strings, interface contract satisfaction, stricter unresolved-name checking for low-confidence chunks. `ValidationResult` with per-chunk attribution. `_find_unresolved_names()` conservative ast-based name resolution.

**Status:** Phase 32x complete — 2046 Python + 30 Vitest

## Phase 32y: HXI Transporter Visualization (AD-335)

**Decision:** AD-335 — WebSocket event emission for chunk lifecycle and UI display. (a) `decompose_blueprint()` gains optional `on_event` callback, emits `transporter_decomposed` on success and fallback paths. (b) `execute_chunks()` gains `on_event`, emits `transporter_wave_start`, `transporter_chunk_done`, `transporter_execution_done` with wave counter. (c) `_emit_transporter_events()` async helper emits `transporter_assembled` and `transporter_validated` via runtime. (d) Frontend: `TransporterChunkStatus` and `TransporterProgress` types in types.ts, `transporterProgress` state field in useStore.ts, 6 event handler cases with chat panel messages. All backward compatible — on_event defaults to None.

**Status:** Phase 32y complete — 2054 Python + 30 Vitest

## Phase 32z: End-to-End Integration & Fallback (AD-336)

**Decision:** AD-336 — Wire the Transporter Pattern into the BuilderAgent lifecycle. (a) `_should_use_transporter()` — decision function: >2 target files, >20K context, or >2 combined impl+test files triggers Transporter. (b) `transporter_build()` — orchestrates full pipeline (create_blueprint → decompose → execute → assemble → validate), returns file blocks in `_parse_file_blocks()` format. Validation failures are logged but blocks still returned (test-fix loop catches real issues). (c) `BuilderAgent.perceive()` builds a BuildSpec from intent params, checks `_should_use_transporter()`, runs `transporter_build()` if appropriate, stores result on `self._transporter_result`. Graceful fallback to single-pass on failure. (d) `BuilderAgent.decide()` overridden to short-circuit LLM call when `_transporter_result` is present. (e) `BuilderAgent.act()` handles `transporter_complete` action alongside existing single-pass path. `execute_approved_build()` unchanged — receives identical file blocks from either path.

**Status:** Phase 32z complete — 2066 Python + 30 Vitest

## Builder Quality Gates & Standing Orders (AD-337 through AD-341)

### AD-337: Implement /ping Command (DONE)

**Decision:** AD-337 — First end-to-end Builder test. Builder generated `/ping` slash command with system uptime, agent count, and health score. Revealed 4 pipeline defects: (a) `execute_approved_build()` commits regardless of test passage (`result.success` based on syntax validation only). (b) `api.py._execute_build()` does not pass `llm_client` to `execute_approved_build()`, making the 2-retry test-fix loop a no-op. (c) UI reports "Files: 0" for MODIFY-only builds (`files_written` vs `files_modified`). (d) Builder's `instructions` string has minimal test-writing guidance, leading to wrong constructor args, wrong imports, and wrong assertions in generated tests.

**Fixes applied manually:** test_shell.py rewritten (removed `renderer=Mock()`, added AgentState/confidence mocks, updated assertions for multi-line output). builder.py path resolution (`_resolve_path`, `_normalize_change_paths`), per-tier LLM timeout, pytest subprocess fix. api.py self-mod approval bypass, work_dir fix.

**Status:** AD-337 complete — 2213 Python + 30 Vitest

### AD-338: Builder Commit Gate & Fix Loop (DONE)

**Decision:** AD-338 — Gate commits on test passage. Pass llm_client from api.py to enable test-fix loop. Fix "Files: 0" reporting bug.

**Implementation:** (a) `execute_approved_build()` now checks `result.tests_passed` before committing — if tests fail, code stays on disk for debugging but is NOT committed, `result.success = False`, `result.error` contains last 1000 chars of test output. (b) `_execute_build()` in api.py creates `LLMClient` and passes it to `execute_approved_build()`, enabling the 2-retry LLM-powered fix loop. (c) File count now reports `files_written + files_modified` in both message and event payload.

**Status:** AD-338 complete — 4 new tests (TestCommitGate)

### AD-339: Standing Orders Architecture (DONE)

**Decision:** AD-339 — ProbOS constitution system. 4-tier hierarchy: Federation Constitution (universal, immutable) → Ship Standing Orders (per-instance) → Department Protocols (per-department) → Agent Standing Orders (per-agent, evolvable via self-mod). `config/standing_orders/` with `federation.md`, `ship.md`, `engineering.md`, `science.md`, `medical.md`, `security.md`, `bridge.md`. `compose_instructions()` assembles complete system prompt at call time. Integrated into `CognitiveAgent.decide()`. Like Claude Code's `CLAUDE.md` and OpenClaw's `soul.md`, but hierarchical, composable, and evolvable. No IDE dependency.

**Implementation:** (a) `src/probos/cognitive/standing_orders.py` — `compose_instructions()`, `get_department()`, `register_department()`, `clear_cache()`, `_AGENT_DEPARTMENTS` mapping, `_load_file()` with `lru_cache`. (b) `CognitiveAgent.decide()` now calls `compose_instructions()` at call time on every LLM request. (c) 7 standing orders files seeded in `config/standing_orders/`. Key invariant preserved: empty/missing directory = identical behavior to before.

**Status:** AD-339 complete — 13 new tests

### AD-340: Builder Instructions Enhancement (DONE)

**Decision:** AD-340 — Add concrete test-writing rules to Builder's hardcoded instructions: read __init__ signatures, use full import paths, trace mock coverage, match actual output format.

**Implementation:** 7 test-writing rules added to `BuilderAgent.instructions` after "Every public function/method needs a test": __init__ signatures, full `probos.*` import paths, `_Fake*` stubs, `pytest.mark.asyncio`, mock completeness tracing, assertion accuracy, encoding safety.

**Status:** AD-340 complete — 1 new test

### AD-341: Code Review Agent (DONE)

**Decision:** AD-341 — CodeReviewAgent reviews Builder output against Standing Orders before commit gate. Engineering department, standard tier. Starts as soft gate (advisory, logs issues). Earns hard gate authority through ProbOS trust model (Beta(1,3) probationary → promoted after demonstrated accuracy).

**Implementation:** (a) `src/probos/cognitive/code_reviewer.py` — `CodeReviewAgent` with `review()`, `_format_changes()`, `_parse_review()`. Reads standards from Standing Orders via `compose_instructions()`. Fails-open on LLM error (approves with warning). (b) Integrated into `execute_approved_build()` as step 4b between validation and test loop. Soft gate — logs issues but doesn't block commits. (c) `BuildResult` extended with `review_result` and `review_issues` fields. (d) Review info surfaced in build_success event payload.

**Status:** AD-341 complete — 10 new tests + 2 integration tests

**Combined status:** AD-338–341 complete — 2243 Python + 30 Vitest (30 new tests)

---

## Standing Orders Display & Builder Failure Escalation (AD-342 through AD-347)

### AD-342: Standing Orders Display Command (DONE)

**Decision:** AD-342 — `/orders` slash command showing all standing orders files with tier classification (Federation Constitution/Ship/Department/Agent), first non-heading line as summary, and file size. Rich Table output with color-coded tiers (red=Federation, blue=Ship, yellow=Department, green=Agent).

**Implementation:** `_cmd_orders()` in `shell.py`. Builder attempted this build but commit gate (AD-338) correctly blocked it — pytest timed out at 120s on 2254 tests, and builder forgot `from pathlib import Path` import. Manual fix applied: added import, wrote 4 tests, committed on main.

**Status:** AD-342 complete — 4 new tests (15 total in test_shell.py)

### AD-343–347: Builder Failure Escalation (DONE)

**Problem:** Builder failures produce raw error dumps with no classification, no context, no actionable options. The 120s test timeout causes spurious failures when only targeted tests are needed. No resolution options in the HXI.

**Implemented ADs:**
- AD-343: `BuildFailureReport` dataclass & `classify_build_failure()` — 6 categories, failed test extraction, error location extraction, resolution options per category. 12 tests.
- AD-344: Smart test selection — `_map_source_to_tests()` by naming convention, `_run_targeted_tests()` two-phase (targeted first 60s, full suite 180s only if targeted pass). 6 tests.
- AD-345: Enriched `build_failure` event & `POST /api/build/resolve` endpoint — `_pending_failures` cache with 30-min TTL, 6 resolution actions. 1 test.
- AD-346: HXI failure diagnostic card — category badge, metadata, failed tests, collapsible error, color-coded resolution buttons. `BuildFailureReport` TypeScript interface.
- AD-347: `escalation_hook` parameter on `execute_approved_build()` — fires before Captain sees failure, fails-open. 4 tests.

**Build prompt:** `prompts/builder-failure-escalation.md`

**Status:** AD-343–347 complete — 2281 Python + 30 Vitest (38 new Python tests)
