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

## Bug Fixes (AD-348 through AD-350)

### AD-348: Fix Self-Mod False Positive on Knowledge Questions / BF-001 (DONE)

**Decision:** AD-348 — Knowledge questions ("who is Alan Turing?") no longer trigger capability_gap classification. Removed knowledge domain examples from KNOWN_CAPABILITIES in prompt_builder.py and softened decomposer rule 12b. Tests verify factual queries stay conversational.

### AD-349: Fix Agent Orbs Escaping Pool Group Spheres / BF-002 (DONE)

**Decision:** AD-349 — `poolToGroup` and `poolGroups` persisted in Zustand state from `state_snapshot` events. `agent_state` handler passes pool group data to `computeLayout()` so agent orbs stay inside their group spheres. 2 vitest tests.

### AD-350: Fix Diagnostician Bypassing VitalsMonitor / BF-003 (DONE)

**Decision:** AD-350 — VitalsMonitorAgent gains `scan_now()` for on-demand metric collection. Diagnostician overrides `perceive()` to find VitalsMonitor via runtime registry and enrich context with live metrics. No more asking the user for alert data.

**Build prompt:** `prompts/fix-open-bugs-bf001-bf003.md`

**Status:** AD-348–350 complete — BF-001/002/003 all closed — 2283 Python + 32 Vitest

## Copilot SDK Visiting Officer Integration (AD-351 through AD-353)

### AD-351: CopilotBuilderAdapter (DONE)

**Decision:** AD-351 — `CopilotBuilderAdapter` wraps the GitHub Copilot SDK Python package to execute build tasks as a visiting officer. NOT a CognitiveAgent — it's an external system wrapper. Creates CopilotClient, injects Standing Orders via `compose_instructions()`, translates BuildSpec to session prompt, captures output using native `_parse_file_blocks()`. SDK import guarded (optional dependency). Fails-open on any error. 11 tests.

### AD-352: ProbOS MCP Tool Server (DONE)

**Decision:** AD-352 — Seven MCP tools registered per Copilot session: `codebase_query`, `codebase_find_callers`, `codebase_get_imports`, `codebase_find_tests`, `codebase_read_source` (from CodebaseIndex), `system_self_model` (from runtime), `standing_orders_lookup` (from config files). Visiting Builder has same codebase knowledge as native crew. 8 tests.

### AD-353: Routing & Apprenticeship Wiring (DONE)

**Decision:** AD-353 — `_should_use_visiting_builder()` routing decision: force flags → SDK availability → Hebbian weight comparison → default visiting (bootstrap). `builder_source` field on BuildResult ("native"/"visiting"). `REL_BUILDER_VARIANT` relationship type in HebbianRouter tracks `(build_code, native|visiting)` success/failure after session and after tests. Over time, Hebbian weights steer toward whichever builder produces more passing code. 10 tests.

**Build prompt:** `prompts/copilot-sdk-visiting-officer.md`

**Status:** AD-351–353 complete — 2313 Python + 32 Vitest (30 new Python tests)

## Visiting Officer HXI Integration (AD-354)

### AD-354: Visiting Officer HXI Integration (DONE)

**Decision:** AD-354 — Three bug fixes and three enhancements for end-to-end visiting officer integration with the HXI build pipeline:

**Bug fixes:**
- Path normalization in `CopilotBuilderAdapter.execute()` — SDK workspace file change events return paths that don't resolve correctly (absolute vs relative, backslash vs forward slash), causing empty `content` on modify blocks
- Temp directory isolation — Builder now copies target files into a temp dir for the SDK session, preventing the visiting officer from writing directly into the ProbOS source tree (bypassing Captain approval)
- Force flags passthrough — `force_native`/`force_visiting` params wired from `BuildRequest` through intent params to `_should_use_visiting_builder()`

**Enhancements:**
- `builder_source` in WebSocket `build_generated` event — HXI knows which builder produced the code
- `model` field on `BuildRequest` — API can specify which model the visiting officer uses
- HXI type updates — `BuildFailureReport` and build event types updated for builder source display

**Build prompt:** `prompts/visiting-officer-hxi-integration.md`

**Status:** AD-354 complete — 2325 Python + 34 Vitest

## Visiting Officer Live Testing Fixes (AD-355)

### AD-355: Visiting Officer Live Testing Fixes (DONE)

**Decision:** AD-355 — Three fixes from live HXI testing of the visiting officer:

**Fixes:**
- System prompt improvement — Added `WORKING ENVIRONMENT` and `PROJECT STRUCTURE` sections to `_VISITING_BUILDER_INSTRUCTIONS`. SDK agent now knows it's in an isolated temp dir, should not explore the filesystem, and has the full project layout (src/probos/, tests/, config/)
- Diagnostic logging cleanup — Removed verbose event-type dumps, changed per-file capture logs to `logger.debug`, added single consolidated `logger.info` with message count + file count
- PYTHONPATH for test gate — Both `_run_tests()` and `_run_targeted_tests()` now set `PYTHONPATH` to `{work_dir}:{work_dir}/src` in subprocess env, so visiting officer files at any location can be imported by tests

**Build prompt:** `prompts/visiting-officer-live-fixes.md`

**Status:** AD-355 complete — 2327 Python + 34 Vitest

## Per-Tier Temperature & Top-P Tuning (AD-358)

### AD-358: Per-Tier Temperature & Top-P Tuning (DONE)

**Decision:** AD-358 — Per-tier sampling parameter configuration, inspired by Kimi K2.5 research showing different cognitive modes benefit from different generation temperatures.

**Changes:**
- `CognitiveConfig` — 6 new optional fields: `llm_temperature_{fast,standard,deep}`, `llm_top_p_{fast,standard,deep}`. `tier_config()` returns `temperature` and `top_p` (None when not set)
- `LLMRequest` — Added `top_p: float | None = None` field
- `OpenAICompatibleClient` — `complete()` resolves effective temperature/top_p from tier config when caller uses defaults. Passed through `_call_api()` → `_call_openai()`/`_call_ollama_native()`. `tier_info()` reports sampling params
- `system.yaml` — Commented-out per-tier sampling config lines

**Build prompt:** `prompts/per-tier-temperature-tuning.md`
**Builder:** Visiting officer (Copilot SDK) — code correct, but also created stray files in wrong paths. Cleanup by architect.

**Status:** AD-358 complete — 5 new tests, 0 regressions (22+36 pass)

## Builder Pipeline Guardrails (AD-360)

### AD-360: Builder Pipeline Guardrails (DONE)

**Decision:** AD-360 — Six structural guardrails for `execute_approved_build()` and visiting officer adapter, addressing the pattern of visiting officer builds creating files in wrong directories and outside the build spec.

**Changes:**
- `builder.py` — `_validate_file_path()` with `_ALLOWED_PATH_PREFIXES` and `_FORBIDDEN_PATHS` constants. `_is_dirty_working_tree()` using `asyncio.create_subprocess_exec` directly. `_git_create_branch()` stale branch deletion. `execute_approved_build()` gains dirty tree check, path validation in file loop, spec allowlist warning, branch cleanup + untracked file cleanup in `finally` block
- `copilot_adapter.py` — `_EXPECTED_PREFIXES` disk scan filtering rejects files outside expected project structure with `rejected_count` summary log
- `tests/test_builder_guardrails.py` — 10 new tests across 4 test classes

**Guardrails:**
1. Branch lifecycle management (cleanup on failure + stale branch deletion)
2. File path validation (hard gate — blocks traversal, absolute, forbidden, out-of-scope)
3. Visiting officer disk scan filtering (first line of defense)
4. Build spec file allowlist (soft gate — advisory warning only)
5. Dirty working tree protection (hard gate — aborts build)
6. Untracked file cleanup (deletes created files + empty parent dirs on failure)

**Build prompt:** `prompts/builder-pipeline-guardrails.md`
**Inspired by:** Aider, Cline, SWE-Agent, OpenHands safety patterns

**Status:** AD-360 complete — 10 new tests, 0 regressions. 2358 Python + 34 Vitest total

## CI/CD Pipeline (AD-361)

### AD-361: CI/CD Pipeline — GitHub Actions (DONE)

**Decision:** AD-361 — Automated test gate on GitHub Actions. Every push to main and every PR now runs the full test suite.

**Changes:**
- `.github/workflows/ci.yml` — Two parallel jobs: `python-tests` (Python 3.12, uv lockfile, pytest -x -q) and `ui-tests` (Node 22, npm ci, vitest + tsc build)
- `tests/test_cognitive_agent.py` — Fixed flaky TTL test: `created_at=0.0` → `time.monotonic() - ttl - 1` (CI runners have low uptime, `monotonic()` near zero)
- `tests/test_copilot_adapter.py` — Added `@pytest.mark.skipif(not _SDK_AVAILABLE)` on `TestCopilotBuilderAdapterExecution`
- `src/probos/cognitive/copilot_adapter.py` — Added fallback `ToolResult` class when `github-copilot-sdk` not importable

**Build prompt:** `prompts/ci-cd-pipeline.md`
**Builder:** Claude Code (VS Code Copilot Chat) created the workflow file. CI stabilization fixes done by architect.

**Status:** AD-361 complete — CI green. Both jobs passing on GitHub Actions

## GPT-5.4 Code Review Findings (AD-362–364, BF-005)

*Identified by GPT-5.4 via GitHub Copilot, verified by architect, implemented by Claude Code builder.*

### AD-362: Fix Bundled Persistence Silent Data Loss (DONE)

**Decision:** AD-362 — `_mesh_write_file()` reported success from a FileWriterAgent proposal without actually calling `commit_write()`. Silent data loss for todos, notes, and reminders.

**Changes:**
- `productivity_agents.py` — `_mesh_write_file()` now calls `FileWriterAgent.commit_write()` directly. `TodoAgent.act()` checks return value.
- `organizer_agents.py` — Same `_mesh_write_file()` fix. `NoteTakerAgent.act()` and `SchedulerAgent.act()` check return value.
- `test_bundled_agents.py` — 4 new integration tests (3 disk persistence + 1 failure propagation)

**Build prompt:** `prompts/bundled-persistence-fix.md`
**Status:** AD-362 complete — 4 new tests, 0 regressions

### AD-363: Fix Mock Reminder Routing (DONE)

**Decision:** AD-363 — MockLLMClient first-match-wins dispatch routed "remind me to..." to `manage_todo` instead of `manage_schedule`.

**Changes:**
- `llm_client.py` — Removed `remind me to` from todo regex, added `remind(?:er| me)` to scheduler regex
- `test_llm_client.py` — 1 new routing test

**Build prompt:** `prompts/mock-reminder-routing-fix.md`
**Status:** AD-363 complete — 1 new test, 0 regressions

### AD-364: Fix get_event_loop in Async Code (DONE)

**Decision:** AD-364 — 7 call sites using deprecated `asyncio.get_event_loop()` inside `async def` methods, violating Standing Orders.

**Changes:**
- `shell.py` — 6 replacements: `get_event_loop()` → `get_running_loop()`
- `renderer.py` — 1 replacement

**Build prompt:** `prompts/fix-get-event-loop.md`
**Status:** AD-364 complete — mechanical fix, 0 regressions

### BF-005: HTTP Consensus Docs Drift (DONE)

**Bug:** AD-150 removed consensus gating from `http_fetch` but docs still described it as consensus-gated.

**Changes:**
- `docs/development/structure.md` — Removed "(consensus-gated)" from http_fetch line
- `docs/agents/inventory.md` — Changed http row consensus to "No", updated note text

**Build prompt:** `prompts/fix-http-consensus-docs.md`
**Status:** BF-005 closed

## GPT-5.4 Code Review — Round 2 (AD-365–369, BF-006)

Second batch of GPT-5.4 code review findings across Runtime/Consensus, HXI/UI, Builder/Self-Mod. 9 findings triaged → 2 already addressed (AD-362, BF-004), 7 new issues fixed.

### AD-365: Red-Team Write Verification (DONE)

**Decision:** AD-365 — RedTeamAgent had no real handler for `write_file` intents — fell through to `verified=True` with `confidence=0.1`.

**Changes:**
- `red_team.py` — Added `_verify_write()` method: empty path, missing content, path traversal, forbidden paths, content size checks. Added `verify_write_file` capability descriptor.
- `test_red_team.py` — 4 new tests (valid path, traversal, forbidden, empty)

**Build prompt:** `prompts/red-team-write-verification.md`
**Status:** AD-365 complete — 4 new tests, 0 regressions

### AD-366: Fix API Import Approval Callback Leak (DONE)

**Decision:** AD-366 — API self-mod path set `_import_approval_fn` to auto-approve but never restored it in `finally` block.

**Changes:**
- `api.py` — Save `original_import_approval_fn` before overwriting, restore in `finally` block
- `test_selfmod_e2e.py` — 1 new source inspection test

**Build prompt:** `prompts/fix-import-approval-leak.md`
**Status:** AD-366 complete — 1 new test, 0 regressions

### AD-367: Move Validation Check Before Commit (DONE)

**Decision:** AD-367 — `validation_errors` checked after commit step; with `run_tests=False`, syntax-invalid files got committed then marked failed.

**Changes:**
- `builder.py` — Moved validation_errors check before commit using if/elif chain
- `test_builder_guardrails.py` — 1 new integration test with real git repo

**Build prompt:** `prompts/validation-before-commit.md`
**Status:** AD-367 complete — 1 new test, 0 regressions

### AD-368: Self-Mod Registration Rollback (DONE)

**Decision:** AD-368 — Agent type registered in spawner/decomposer before pool creation; if pool fails, phantom type remained.

**Changes:**
- `self_mod.py` — Added `unregister_fn` parameter, rollback on pool failure
- `spawner.py` — Added `unregister_template()` method
- `runtime.py` — Added `unregister_agent_type()`, `_unregister_designed_agent()`, wired into pipeline
- `test_self_mod.py` — 1 new test verifying rollback call

**Build prompt:** `prompts/self-mod-registration-rollback.md`
**Status:** AD-368 complete — 1 new test, 0 regressions

### AD-369: Fix WebSocket Protocol Detection (DONE)

**Decision:** AD-369 — Hardcoded `ws://` in `useWebSocket.ts` breaks behind HTTPS.

**Changes:**
- `useWebSocket.ts` — Dynamic protocol detection via `window.location.protocol`

**Build prompt:** `prompts/fix-websocket-protocol.md`
**Status:** AD-369 complete — single-line fix

### BF-006: Fix Quorum Trust Docs Drift (DONE)

**Bug:** `docs/architecture/consensus.md` had two inaccuracies: (1) "HTTP fetches" listed as consensus-gated, (2) claimed votes carry trust reputation when `Vote` has no trust field.

**Changes:**
- `consensus.md` — Removed "HTTP fetches" from destructive ops, replaced trust bullet with "optional reason string"

**Build prompt:** `prompts/fix-quorum-trust-docs.md`
**Status:** BF-006 closed

## BF-004 + AD-370 — First Parallel Builder Trial

First trial of parallel builder dispatch: two builders ran simultaneously with zero file overlap. Builder 1 (UI, main worktree) handled BF-004, Builder 2 (Python, `ProbOS-builder-2` worktree) handled AD-370.

### BF-004: Transporter HXI Visualization (DONE)

**Bug:** Transporter Pattern (AD-330–336) emits 6 event types, Zustand store updates `transporterProgress` state, but `IntentSurface.tsx` had no rendering block — data went to nowhere.

**Changes:**
- `IntentSurface.tsx` — Added transporter progress card: phase badge, progress fraction, animated progress bar (teal fill + red for failures), chunk list with color-coded status dots, target file paths, footer stats. Auto-clears on completion.

**Build prompt:** `prompts/bf-004-transporter-visualization.md`
**Status:** BF-004 closed — 0 regressions

### AD-370: Structural Integrity Field — SIF (DONE)

**Decision:** AD-370 — Lightweight runtime service with 7 pure-assertion invariant checks running on 5s heartbeat. Ship's Computer function, not an agent. No LLM calls.

**Changes:**
- `sif.py` (NEW) — `StructuralIntegrityField` class with `SIFCheckResult`/`SIFReport` dataclasses. 4 active checks (trust bounds, Hebbian bounds, pool consistency, IntentBus coherence) + 3 graceful no-ops (config, index, memory — pending future wiring). Exception isolation per check. Background `asyncio.Task` with configurable interval. `health_pct`, `all_passed`, `violations` properties.
- `runtime.py` — SIF instantiation in `start()`, cleanup in `stop()`
- `test_sif.py` (NEW) — 12 tests: NaN/out-of-range/pass for trust and Hebbian, orphan/pass for pools, health_pct calculation, all-None graceful degradation, violations property, config validity

**Build prompt:** `prompts/sif-structural-integrity.md`
**Status:** AD-370 complete — 12 new tests, 2371 pytest + 34 vitest = 2405 total

## Automated Builder Dispatch (AD-371–374)

### AD-371: BuildQueue + WorktreeManager (DONE)

**Decision:** AD-371 — Foundation for automated builder dispatch. Two standalone utilities (no runtime wiring).

**Changes:**
- `build_queue.py` (NEW) — `BuildQueue` class with `QueuedBuild` dataclass. Priority-ordered queue, status lifecycle validation (`queued→dispatched→building→reviewing→merged/failed`), file footprint conflict detection, cancel support. 14 tests.
- `worktree_manager.py` (NEW) — `WorktreeManager` class with `WorktreeInfo` dataclass. Async git worktree lifecycle: create, remove, collect diff, merge to main, cleanup. All git ops via `asyncio.create_subprocess_exec`. 6 tests with real git repos.

**Build prompt:** `prompts/build-queue-worktree-manager.md`
**Status:** AD-371 complete — 20 new tests, 2391 pytest + 34 vitest = 2425 total

### AD-372: BuildDispatcher + SDK Integration (DONE)

**Decision:** AD-372 — Core dispatch loop for the automated builder system. Absorbs AD-374 (footprint conflict detection).

**Changes:**
- `build_dispatcher.py` (NEW) — `BuildDispatcher` class. Watches BuildQueue, allocates worktrees, invokes CopilotBuilderAdapter, applies changes via `execute_approved_build()`. Pipeline: dequeue → conflict check → worktree → adapter → guardrails → status. Captain actions: `approve_and_merge()`, `reject_build()`. Configurable concurrency, polling, model, timeout. `on_build_complete` callback.
- `test_build_dispatcher.py` (NEW) — 11 tests: priority dispatch, conflict skipping, success/failure flows, merge/reject, callback, max concurrency, file reading.

**Build prompt:** `prompts/build-dispatcher.md`
**Status:** AD-372 complete — 11 new tests, 2402 pytest + 34 vitest = 2436 total

### AD-373: HXI Build Dashboard (DONE)

**Decision:** AD-373 — Real-time build queue visualization in the HXI. Engineering amber theme (`#b0a050`).

**Changes:**
- `types.ts` — Added `BuildQueueItem` interface with status union type, file footprint, commit hash fields
- `useStore.ts` — Added `buildQueue: BuildQueueItem[] | null` state. `build_queue_update` (full snapshot) and `build_queue_item` (single upsert) event handlers. Chat logging for status transitions (building, reviewing, merged, failed). Auto-filtering of terminal items.
- `IntentSurface.tsx` — Build Queue card with status dots (gray=queued, blue=dispatched, amber-pulsing=building, amber=reviewing, green=merged, red=failed). Approve/reject buttons for reviewing items with `/api/build/approve` and `/api/build/reject` POST calls. File footprint display for reviewing items. Active count in header.

**Build prompt:** `prompts/hxi-build-dashboard.md`
**Status:** AD-373 complete — 0 new tests (UI only), 2402 pytest + 34 vitest = 2436 total

### AD-375: Dispatch System Runtime Wiring (DONE)

**Decision:** AD-375 — Wire BuildQueue, WorktreeManager, and BuildDispatcher into the runtime lifecycle + API layer. Closes the end-to-end loop: components are now live at startup with proper shutdown.

**Changes:**
- `runtime.py` — Import and instantiate `BuildQueue`, `WorktreeManager`, `BuildDispatcher` in start/stop (SIF pattern). `_on_build_complete` callback emits `build_queue_item` WebSocket events for real-time HXI updates.
- `api.py` — 3 Pydantic models (`BuildQueueApproveRequest`, `BuildQueueRejectRequest`, `BuildEnqueueRequest`). 4 endpoints: `POST /api/build/queue/approve` (merge), `POST /api/build/queue/reject` (discard), `POST /api/build/enqueue` (add to queue), `GET /api/build/queue` (list state). `_emit_queue_snapshot` broadcasts full queue after mutations.
- `IntentSurface.tsx` — Button URLs fixed from `/api/build/approve` → `/api/build/queue/approve`, `/api/build/reject` → `/api/build/queue/reject`.
- `test_dispatch_wiring.py` (NEW) — 9 tests: runtime fields, callback, all 4 endpoints, dispatcher-not-running guard, snapshot emission.

**Build prompt:** `prompts/dispatch-runtime-wiring.md`
**Status:** AD-375 complete — 9 new tests, 2411 pytest + 34 vitest = 2445 total

### AD-376: CrewProfile + Personality System (DONE)

**Decision:** AD-376 — Foundational crew identity layer. Every agent gets a formal personnel file with identity, rank, Big Five personality traits, and performance history.

**Changes:**
- `crew_profile.py` (NEW) — `Rank` enum (Ensign→Lieutenant→Commander→Senior, with `from_trust()` convenience). `PersonalityTraits` (Big Five: openness, conscientiousness, extraversion, agreeableness, neuroticism; 0.0–1.0 validated; `distance_from()` for drift detection). `PerformanceReview` (timestamped, append-only). `CrewProfile` (identity + rank + personality + baseline + reviews, `personality_drift()`, `promotion_velocity()`). `ProfileStore` (SQLite-backed, `get_or_create()`, `by_department()`, `by_rank()`). `load_seed_profile()` loads YAML seeds with `_default.yaml` fallback.
- `config/standing_orders/crew_profiles/` (NEW) — 12 YAML seed files (builder/Scotty, architect/Number One, diagnostician/Bones, vitals_monitor/Chapel, surgeon/Pulaski, pharmacist/Ogawa, pathologist/Selar, red_team/Worf, system_qa/O'Brien, emergent_detector/Dax, introspect/Data) + `_default.yaml`.
- `test_crew_profile.py` (NEW) — 25 tests: rank boundaries, personality validation/drift/roundtrip, profile operations, store CRUD, seed loading.

**Build prompt:** `prompts/crew-profile-personality.md`
**Status:** AD-376 complete — 25 new tests, 2436 pytest + 34 vitest = 2470 total

### AD-379: Per-Agent Standing Orders (DONE)

**Decision:** AD-379 — Tier 5 personal standing orders for all 12 crew members. Each file defines standards, boundaries, and personality expression specific to that agent. Auto-loaded by existing `compose_instructions()` in `standing_orders.py`.

**Changes:**
- 12 new files in `config/standing_orders/`: `builder.md` (Scotty), `architect.md` (Number One), `diagnostician.md` (Bones), `vitals_monitor.md` (Chapel), `surgeon.md` (Pulaski), `pharmacist.md` (Ogawa), `pathologist.md` (Selar), `red_team.md` (Worf), `system_qa.md` (O'Brien), `emergent_detector.md` (Dax), `introspect.md` (Data), `counselor.md`. All under 20 lines, no code changes needed.

**Build prompt:** `prompts/per-agent-standing-orders.md`
**Status:** AD-379 complete — 0 new tests (config only), 2436 pytest + 34 vitest = 2470 total
