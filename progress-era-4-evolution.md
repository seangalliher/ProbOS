# Era IV: Evolution — The Ship Evolves (ARCHIVED)

> **ARCHIVED:** This file is no longer updated. As of AD-396, the canonical decision log is [DECISIONS.md](DECISIONS.md). Historical entries below are preserved for reference.

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

### AD-377: Watch Rotation + Duty Shifts (DONE)

**Decision:** AD-377 — Naval-style watch rotation system for scheduled agent duty. Three watches: Alpha (full ops), Beta (reduced), Gamma (maintenance). `WatchManager` maintains a duty roster, dispatches `StandingTask` items (recurring department tasks with interval-based scheduling) and `CaptainOrder` directives (persistent orders, optionally one-shot) to on-duty agents via a configurable `dispatch_fn` callback.

**Changes:**
- New `src/probos/watch_rotation.py` (254 lines): `WatchType` enum, `StandingTask`, `CaptainOrder`, `DutyShift`, `WatchManager` with async dispatch loop
- New `tests/test_watch_rotation.py`: 18 tests covering roster management, standing tasks, captain's orders, dispatch loop

**Build prompt:** `prompts/watch-rotation.md`
**Status:** AD-377 complete — 18 new tests, 2454 pytest + 34 vitest = 2488 total

### AD-378: CounselorAgent + Cognitive Profiles (DONE)

**Decision:** AD-378 — Ship's Counselor (Bridge-level CognitiveAgent). Monitors cognitive wellness of every crew member. Maintains `CognitiveProfile` per agent with `CognitiveBaseline` snapshot and `CounselorAssessment` history. Deterministic `assess_agent()` computes drift from baseline (trust, confidence, Hebbian, personality) → wellness score + concerns + recommendations + fit-for-duty/promotion flags. Alert levels (green/yellow/red).

**Changes:**
- New `src/probos/cognitive/counselor.py` (388 lines): `CognitiveBaseline`, `CounselorAssessment`, `CognitiveProfile`, `CounselorAgent` (pool="bridge", 3 intent descriptors, perceive/act/report lifecycle)
- New `tests/test_counselor.py`: 18 tests covering baselines, assessments, alert transitions, drift trending, healthy/degraded/promotion paths, lifecycle overrides
- Modified `config/standing_orders/bridge.md`: Added Counselor Protocol section

**Build prompt:** `prompts/counselor-cognitive-profiles.md`
**Status:** AD-378 complete — 18 new tests, 2472 pytest + 34 vitest = 2506 total

### AD-322: Mission Control Kanban Dashboard (DONE)

**Decision:** AD-322 — 4-column Kanban board (Queued → Working → Review → Done) as HXI overlay. Derives `MissionControlTask` from existing `BuildQueueItem` WebSocket events — no new backend code. Department color coding, status pulse animation, Approve/Reject buttons on review items.

**Changes:**
- New `ui/src/components/MissionControl.tsx` (209 lines): Full Kanban board with TaskCard component
- Modified `ui/src/store/types.ts`: `MissionControlTask` interface
- Modified `ui/src/store/useStore.ts`: `buildQueueToTasks()` derivation, `missionControlTasks` + `missionControlView` state, wired to both WebSocket handlers
- Modified `ui/src/components/IntentSurface.tsx`: Toggle button and overlay rendering

**Build prompt:** `prompts/mission-control-kanban.md`
**Status:** AD-322 complete — 0 new tests (UI only), 2472 pytest + 34 vitest = 2506 total

### AD-316: TaskTracker Service + AgentTask Data Model (DONE)

**Decision:** AD-316 — Unified task lifecycle tracking for all agent activity. Foundational service for Mission Control, Activity Drawer, and Notification Queue. Follows SIF/BuildQueue/BuildDispatcher startup pattern.

**Changes:**
- New `src/probos/task_tracker.py` (274 lines): `TaskType` enum (build/design/diagnostic/assessment/query), `StepStatus` enum (pending/in_progress/done/failed), `TaskStatus` enum (queued/working/review/done/failed), `TaskStep` dataclass (start/complete/fail/to_dict), `AgentTask` dataclass (lifecycle methods, step management, step_progress, to_dict with step_current/step_total), `TaskTracker` class (create/start/advance/complete/fail lifecycle, queries, snapshot, event emission, done-task pruning)
- Modified `src/probos/runtime.py`: Import, field init (`None`), construction in `start()` with `on_event=self._emit_event`, cleanup in `stop()`, snapshot in `build_state_snapshot()`
- Modified `ui/src/store/types.ts`: `TaskStepView` and `AgentTaskView` interfaces
- Modified `ui/src/store/useStore.ts`: `agentTasks` state field, `task_created`/`task_updated` event handlers with `MissionControlTask` derivation, `state_snapshot` hydration
- New `tests/test_task_tracker.py`: 30 tests across 3 classes (TestTaskStep, TestAgentTask, TestTaskTracker)

**Build prompt:** `prompts/task-tracker.md`
**Status:** AD-316 complete — 30 new tests, 2502 pytest + 34 vitest = 2536 total

## Phase 28b: Cognitive Evolution (AD-380–385)

### AD-380: EmergentDetector Trend Regression (DONE)

**Decision:** AD-380 — Multi-snapshot trend analysis over the ring buffer. Pure Python `_linear_regression()` computes slopes for tc_n, routing_entropy, cluster_count, trust_spread, capability_count. `TrendDirection` enum (rising/stable/falling), `MetricTrend` dataclass with r_squared significance test. `TrendReport` aggregates all 5 metrics with `significant_trends` filter. Ring buffer converted from list to `collections.deque(maxlen=...)`. Wired into `detect_anomalies()` as `emergence_trends` pattern. Configurable `trend_threshold` (default 0.005). introspect.py fixed for deque slicing.

**Build prompt:** `prompts/emergent-trends.md`
**Status:** AD-380 complete — 12 new tests, 2514 pytest + 34 vitest = 2548 total

### AD-382: ServiceProfile — Learned External Service Modeling (DONE)

**Decision:** AD-382 — SQLite-backed `ServiceProfile` replaces hardcoded `_KNOWN_RATE_LIMITS`. `LatencyStats` with asymmetric EMA for p50/p95/p99 percentiles. `ServiceProfile` with learned_min_interval, error/rate-limit tracking, 429→increase, 2xx→decay logic. `ServiceProfileStore` (SQLite, CrewProfile pattern) with `get_or_create()`, `save()`, `all_profiles()`, `get_interval()`. Seed intervals preserve existing defaults. HttpFetchAgent reads from store via `set_profile_store()` classmethod. Runtime wires store at startup/shutdown.

**Build prompt:** `prompts/service-profile.md`
**Status:** AD-382 complete — 17 new tests, 2531 pytest + 34 vitest = 2565 total

### AD-381: InitiativeEngine — SIF → Remediation Proposals (DONE)

**Decision:** AD-381 — Ship's Computer service bridging read-only monitoring (SIF, EmergentDetector, Counselor) and the self-mod pipeline. `TriggerSource` enum (SIF/emergent/counselor), `ActionType` enum (diagnose/scale/recycle/patch/alert_captain), `ActionGate` enum (auto/commander/captain). `TriggerState` tracks persistent triggers across consecutive check cycles. `RemediationProposal` with trust-gated execution classification. `InitiativeEngine` runs async check loop: monitors SIF violations, EmergentDetector falling trends (tc_n, capability_count), Counselor red/yellow alerts. Triggers cleared when resolved. Proposals generated at persistence_threshold (default 3). Approve/reject API. Capped at 50 proposals. Fails-open on all signal checks. Runtime wired with SIF and EmergentDetector references.

**Build prompt:** `prompts/initiative-engine.md`
**Status:** AD-381 complete — 19 new tests, 2550 pytest + 34 vitest = 2584 total

### AD-383: Strategy Extraction — Dream-Derived Transferable Patterns (DONE)

**Decision:** AD-383 — New dream pass (step 6) extracting cross-agent transferable patterns from episodic memory. Three pattern detectors: (1) error recovery — same error resolved by 2+ different agent types, (2) high-confidence prompting — intent type with avg confidence >0.8 across 2+ agents, (3) coordination — intent co-occurrence within 60s window across 3+ episodes. `StrategyType` enum (ERROR_RECOVERY/PROMPT_TECHNIQUE/COORDINATION/OPTIMIZATION). `StrategyPattern` dataclass with deterministic SHA-256 ID, `reinforce()` for evidence accumulation, confidence formula `1 - 1/(count+1)`. `extract_strategies()` main function with dedup. File named `strategy_extraction.py` (not `strategy.py`) to avoid conflict with existing `StrategyRecommender`. Wired into `DreamingEngine.dream_cycle()` via `strategy_store_fn` callback. `DreamReport.strategies_extracted` field added (backward compatible default 0). Runtime persists strategies as JSON files under `knowledge_store.repo_path / "strategies/"`.

**Build prompt:** `prompts/strategy-extraction.md`
**Status:** AD-383 complete — 15 new tests, 2565 pytest + 34 vitest = 2599 total

### AD-385: Capability Gap Prediction — Proactive Self-Mod (DONE)

**Decision:** AD-385 — New dream pass (step 7) analyzing episodic memory for recurring near-misses. Three detection methods: (1) repeated low confidence — intent type with avg confidence below threshold across 5+ episodes, (2) repeated fallback — no intent matched or very low confidence on similar topics 3+ times, (3) partial DAG coverage — DAG node fails >50% across 3+ attempts. `CapabilityGapPrediction` dataclass with descriptive ID, evidence type/summary/count, suggested intent, priority. `_extract_topic()` with stopword filtering, `_get_field()` for dict/object access. Wired into `DreamingEngine.dream_cycle()` via `gap_prediction_fn`. `DreamReport.gaps_predicted` field added. Runtime broadcasts to HXI as `capability_gap_predicted` events.

**Build prompt:** `prompts/gap-prediction.md`
**Status:** AD-385 complete — 14 new tests, 2579 pytest + 34 vitest = 2613 total

### AD-384: Strategy Application — Cross-Agent Knowledge Transfer (DONE)

**Decision:** AD-384 — Makes dream-extracted strategies (AD-383) consumable by all CognitiveAgents. `StrategyAdvisor` loads strategies from knowledge store's `strategies/` directory (JSON), matches by intent type against `source_intent_types` and `applicability`, filters low-confidence (<0.3), boosts with `REL_STRATEGY` Hebbian weight, returns top 3 sorted by relevance. `format_for_context()` produces `[CREW EXPERIENCE]` block injected into user message before LLM call. `record_outcome()` writes to HebbianRouter so strategy usefulness is learned per agent type. `REL_STRATEGY` constant added to `routing.py`. `CognitiveAgent` gains `_strategy_advisor` field + `set_strategy_advisor()`. Runtime wires advisor onto all CognitiveAgent instances after pool creation.

**Build prompt:** `prompts/strategy-application.md`
**Status:** AD-384 complete — 12 new tests, 2591 pytest + 34 vitest = 2625 total

### AD-386: Runtime Directive Overlays — Evolvable Chain-of-Command Instructions (DONE)

**Decision:** AD-386 — Persistent tier 6 instruction layer for chain-of-command directives. `DirectiveStore` (SQLite-backed, CrewProfile/ServiceProfile pattern). 5 `DirectiveType` values: captain_order, chief_directive, counselor_guidance, learned_lesson, peer_suggestion. `authorize_directive()` enforces chain-of-command: Captain→any, Bridge officers (counselor/architect)→advisory, Department chiefs (COMMANDER+)→subordinates in same department, Self→self (Ensign→pending approval, Lieutenant+→auto-approved), Peers (LIEUTENANT+)→suggestion (target accepts). `RuntimeDirective` dataclass with full serialization, priority ordering, expiry, revocation. `DirectiveStore` with `create_directive()` (authorize + persist), `get_active_for_agent()` (target/department filtering, auto-expire), `revoke()`, `approve()`, `all_directives()`. Wired into `compose_instructions()` as tier 6 via module-level `_directive_store` + `set_directive_store()`. `CognitiveAgent.decide()` picks up directives automatically — zero changes to cognitive_agent.py. Shell: `/order <agent> <text>` (Captain issues with priority 5, calls `clear_cache()`), `/directives [agent]` (view active/pending). Runtime: SQLite init in `start()`, cleanup in `stop()`, `_directive_summary()` in state snapshot.

**Build prompt:** `prompts/runtime-directives.md`
**Status:** AD-386 complete — 30 new tests, 2621 pytest + 34 vitest = 2655 total

### AD-321: Activity Drawer — Real-Time Agent Task Panel (DONE)

**Decision:** AD-321 — Slide-out panel from the right edge of the HXI for real-time agent task visibility. Consumes existing `agentTasks` state from TaskTracker (AD-316) — no backend changes. Three collapsible sections: Needs Attention (amber, `requires_action` filter, Approve/Reject buttons, always expanded), Active (`status === 'working'`, step progress bars with `neural-pulse` animation, always expanded), Recent (done/failed, sorted by `completed_at` descending, capped at 10, collapsed by default). Task cards show department color left border stripe (DEPT_COLORS), status dot (STATUS_COLORS), type badge (BUILD/DESIGN/DIAGNOSTIC/ASSESSMENT/QUERY), truncated title (50 chars), agent type, department, elapsed time, AD number. Click to expand: full title, step-by-step checklist (○ pending, ◐ in_progress, ● done, ✕ failed), overall progress bar, error text (200 chars, muted red), metadata key-value display. Glass panel styling: `rgba(10, 10, 18, 0.92)`, backdrop blur, 320px width, z-index 20, transform slide animation. ACTIVITY toggle button in header with attention count badge.

**Changes:**
- New `ui/src/components/ActivityDrawer.tsx` (351 lines): SectionHeader, StepList, ProgressBar, TaskCard, ActivityDrawer components with DEPT_COLORS, STATUS_COLORS, STEP_ICONS constants
- Modified `ui/src/components/IntentSurface.tsx`: Import, `drawerOpen` state, `agentTasks` selector, `needsAttentionCount`, ACTIVITY toggle button, ActivityDrawer rendering

**Build prompt:** `prompts/activity-drawer.md`
**Status:** AD-321 complete — 0 new tests (UI only), 2621 pytest + 34 vitest = 2655 total

### BF-007: Verification False Positive on Per-Pool Agent Counts (DONE)

**Decision:** BF-007 — `_verify_response()` regex `(\d+)\s+agents?\b` falsely flagged per-pool/per-department agent counts against system-wide total (53). Fix: `_is_subset_claim()` helper examines 80 chars before each match for known pool names, department names, or subset indicator words ("pool", "department", "team", "each", "per"). Known pool size whitelist skips numbers matching any individual `pool.agent_count`. Only system-wide total claims are flagged.

**Changes:**
- Modified `src/probos/runtime.py`: `_verify_response()` refactored with `_is_subset_claim()`, `known_pool_sizes` whitelist, `re.finditer()` for positional matching
- Modified `tests/test_decomposer.py`: 4 new tests (per-pool not flagged, per-department breakdown not flagged, wrong system total still caught, ambiguous count matching known pool size not flagged)

**Build prompt:** `prompts/bf-004-verification-false-positive.md`
**Status:** BF-007 closed — 4 new tests, 2644 pytest + 34 vitest = 2678 total

### BF-008: Dream Cycle Double-Replay After Dolphin Dreaming (DONE)

**Decision:** BF-008 — Micro-dream (Tier 1, every 10s) already replayed episodes incrementally; full dream (Tier 2, every 10min) re-replayed same 50 episodes, double-strengthening Hebbian weights. Fix: `dream_cycle()` now starts with `micro_dream()` flush as Step 0 (composable), then does maintenance only (pruning, trust consolidation, pre-warming, strategy extraction, gap prediction). No separate `_replay_episodes()` call. `DreamReport` reflects micro-dream flush counts. Log shows `flushed=N` instead of `replayed=50`. Micro-dream cursor reset removed from full dream. No caller changes needed — `dream_cycle()` is self-contained.

**Changes:**
- Modified `src/probos/cognitive/dreaming.py`: `dream_cycle()` starts with `micro_dream()`, removed `_replay_episodes()` call, removed cursor reset, updated log format
- Modified `tests/test_dreaming.py`: 6 new tests (calls micro_dream first, no direct replay, maintenance still runs, report reflects flush, cursor not reset, existing scheduler test updated)

**Build prompt:** `prompts/bf-008-dream-double-replay.md`
**Status:** BF-008 closed — 6 new tests, 2650 pytest + 34 vitest = 2684 total

### AD-323: Agent Notification Queue (DONE)

**Decision:** AD-323 — Persistent notification system for agent→Captain communication. `AgentNotification` dataclass + `NotificationQueue` service (notify, acknowledge, acknowledge_all, snapshot, prune). `Runtime.notify()` convenience method with auto-lookup of agent_type/department. Two API endpoints: `POST /api/notifications/{id}/ack` and `POST /api/notifications/ack-all`. `NotificationDropdown` React component with glass panel, type-colored left borders (info=blue, action_required=amber, error=red), relative time, click-to-ack, mark-all-read. Bell button (NOTIF) at `right: 210` with unread count badge. Zustand notifications state with 3 event handlers + snapshot hydration.

**Changes:**
- Modified `src/probos/task_tracker.py`: `AgentNotification` dataclass, `NotificationQueue` service
- Modified `src/probos/runtime.py`: `notification_queue` init, `notify()`, `_find_agent()`, `_get_agent_department()`, `build_state_snapshot()` updated
- Modified `src/probos/api.py`: 2 ack endpoints
- New `ui/src/components/NotificationDropdown.tsx`: dropdown panel, NotificationCard
- Modified `ui/src/components/IntentSurface.tsx`: bell button, dropdown integration
- Modified `ui/src/store/types.ts`: `NotificationView` interface
- Modified `ui/src/store/useStore.ts`: notifications state, 3 event handlers, snapshot hydration
- New `tests/test_notifications.py`: 12 tests
- Modified `ui/src/__tests__/useStore.test.ts`: 4 new vitest tests

**Build prompt:** `prompts/ad-323-notification-queue.md`
**Status:** AD-323 complete — 12 pytest + 4 vitest new, 2663 pytest + 38 vitest = 2701 total

### AD-324: Orb Hover Enhancement (DONE)

**Decision:** AD-324 — Enhanced agent orb interactivity with three features: (1) Amber pulsing animation on 3D orbs when any agent has a `requires_action` task — builds attention Set once per frame from `agentTasks` for O(1) per-instance lookup, pulses between normal color and amber `(0.94, 0.69, 0.38)` at ~2Hz with increased breathing amplitude (0.08 vs 0.03). (2) Enhanced AgentTooltip with current task info — title (50-char truncate), step label, elapsed time (formatted as "Xm Ys"), progress bar (4px, department-colored), department label from `poolToGroup`, amber attention badge for `requires_action`, click-through "View in Activity" button. (3) Moved `activityDrawerOpen` from IntentSurface local `useState` to Zustand store for cross-component access (tooltip can open drawer).

**Changes:**
- Modified `ui/src/canvas/agents.tsx`: attention set built once per frame, amber pulse sine wave, increased breath amplitude
- Modified `ui/src/components/AgentTooltip.tsx`: task info section, department label, progress bar, attention badge, click-through
- Modified `ui/src/components/IntentSurface.tsx`: `drawerOpen` reads from Zustand `activityDrawerOpen` instead of local state
- Modified `ui/src/store/useStore.ts`: `activityDrawerOpen: boolean` added to store
- Modified `ui/src/__tests__/useStore.test.ts`: 4 new vitest tests (drawer toggle, task lookup, no-task case, attention badge)

**Build prompt:** `prompts/ad-324-orb-hover.md`
**Status:** AD-324 complete — 0 pytest + 4 vitest new, 2663 pytest + 42 vitest = 2705 total

### AD-387: Unified Bridge — Single Panel HXI Redesign (DONE)

**Decision:** AD-387 — Replace three separate panels (NOTIF, ACTIVITY, MISSION CTRL) with a single BRIDGE button and unified command panel. Bridge panel (380px right sidebar, glass morphism) has five priority-ordered sections: Attention (merged `requires_action` tasks + `action_required` notifications, amber accent, always expanded when items exist), Active (working tasks, teal accent), Notifications (info/error notifs, blue accent), Kanban (compact 4-column inline grid with expand-to-main-viewer button, gold accent), Recent (done/failed, collapsed by default). Empty sections auto-hide. Shared card components extracted into `bridge/` subdirectory (BridgeCards, BridgeNotifications, BridgeKanban, FullKanban). Main viewer becomes adaptive focus surface via `mainViewer: 'canvas' | 'kanban'` state — FullKanban replaces 3D canvas in center area when activated from Bridge's kanban expand button or ViewSwitcher. ViewSwitcher (top-left tabs) appears only when non-canvas view active. Old components deleted. `bridgeOpen` + `mainViewer` replace `missionControlView` + `activityDrawerOpen` in Zustand store.

**Changes:**
- New `ui/src/components/BridgePanel.tsx`: unified panel with BridgeSection collapsible sub-component, 5 sections, mark-all-read
- New `ui/src/components/bridge/BridgeCards.tsx`: TaskCard, DEPT_COLORS, STATUS_COLORS, formatElapsed, ProgressBar, StepList (extracted from ActivityDrawer)
- New `ui/src/components/bridge/BridgeNotifications.tsx`: NotificationCard, TYPE_COLORS, formatRelativeTime (extracted from NotificationDropdown)
- New `ui/src/components/bridge/BridgeKanban.tsx`: compact 4-column kanban for sidebar
- New `ui/src/components/bridge/FullKanban.tsx`: full-width kanban board for main viewer (extracted from MissionControl)
- New `ui/src/components/ViewSwitcher.tsx`: top-left canvas/kanban tab switcher
- Modified `ui/src/App.tsx`: conditional render canvas vs FullKanban based on mainViewer
- Modified `ui/src/components/IntentSurface.tsx`: 3 buttons → 1 BRIDGE button with combined attention badge, BridgePanel + ViewSwitcher
- Modified `ui/src/store/useStore.ts`: bridgeOpen + mainViewer replace missionControlView + activityDrawerOpen
- Modified `ui/src/components/AgentTooltip.tsx`: "Open Bridge" replaces "View in Activity"
- Deleted `ui/src/components/ActivityDrawer.tsx`, `NotificationDropdown.tsx`, `MissionControl.tsx`
- Modified `ui/src/__tests__/useStore.test.ts`: 4 new tests (mainViewer default, kanban switch, independence, attention merge), existing test updated

**Build prompt:** `prompts/ad-325-unified-bridge.md`
**Status:** AD-387 complete — 0 pytest + 4 vitest new, 2652 pytest + 46 vitest = 2698 total

### HXI Glass Bridge — Progressive Enhancement (AD-388 through AD-392, PLANNED)

**Decision:** Layer a frosted glass working surface over the existing orb mesh as a progressive enhancement. Three depth layers: Backdrop (3D mesh, z=0), Glass (task/collaboration surface, z=1), Controls (Bridge panel + Command Surface, z=2). The mesh is never replaced — every phase builds on the current HXI. Inspired by NeXTSTEP precision, cyberpunk soul, LCARS reconfiguration, Bloomberg density. Agent-first design: the glass surfaces what needs the Captain's attention, not apps.

**Phases:**
- **AD-388:** Glass overlay with center task cards, dynamic frost, multi-task constellation *(done)*
- **AD-389:** DAG visualization — spatial sub-task nodes, decisions rise / results sink, inline agent commentary *(done)*
- **AD-390:** Ambient intelligence — three bridge states (Idle/Autonomous/Attention), ambient color temperature, return-to-bridge briefing, completion celebrations, Context Ribbon *(done)*
- **AD-391:** Cyberpunk atmosphere — opt-in scan lines, chromatic aberration, data rain, luminance ripple transitions, sound design *(done)*
- **AD-392:** Adaptive bridge — trust-driven progressive reveal, Command Surface breathing, Captain's Gaze attention weighting, responsive layout *(done)*

**AD-388 Changes:**
- New `ui/src/components/GlassLayer.tsx`: full-viewport overlay at z-index 5, dynamic frost (backdrop-filter blur scales 0→2→4→6px), noise texture, constellation layout for 1-6+ tasks, sorts by requires_action → status → priority
- New `ui/src/components/glass/GlassTaskCard.tsx`: glass morphism card (280px), department-colored left border, progress bar, JetBrains Mono system data, amber pulse animation on attention tasks, elevated -8px for requires_action, click opens Bridge panel
- Modified `ui/src/App.tsx`: `<GlassLayer />` inserted between canvas and IntentSurface
- New `ui/src/__tests__/GlassLayer.test.tsx`: 9 tests (null tasks, empty tasks, kanban mode, single/multiple tasks, done/failed exclusion, attention sorting, frost levels, bridge click)

**Design spec:** `docs/design/hxi-glass-bridge.md`
**Build prompt:** `prompts/ad-388-glass-overlay.md`
**Status:** AD-388 complete — 9 vitest new, 2652 pytest + 55 vitest = 2707 total

### AD-389: DAG Visualization (DONE)

**Decision:** AD-389 — Add spatial sub-task node visualization around expanded glass task cards. Click a card to expand its steps as radial nodes. Double-click opens Bridge panel.

**Changes:**
- New `ui/src/components/glass/GlassDAGNodes.tsx`: radial step nodes (28px circles), SVG dependency lines, hover tooltips (label + duration), status-colored borders/icons, staggered fade-in (80ms/node), `neural-pulse` animation on active nodes
- Modified `ui/src/components/glass/GlassTaskCard.tsx`: single-click → toggle expand (set `expandedGlassTask`), double-click → open Bridge panel
- Modified `ui/src/components/GlassLayer.tsx`: renders `GlassDAGNodes` for expanded task, reads `expandedGlassTask` from store, decisions-rise translateY(-20px) on requires_action tasks
- Modified `ui/src/store/useStore.ts`: added `expandedGlassTask: string | null` (default null)
- New `ui/src/__tests__/GlassDAGNodes.test.tsx`: 7 tests (default null, set/clear, one-at-a-time, status icons, empty steps, node count, toggle logic)

**Build prompt:** `prompts/ad-389-dag-visualization.md`
**Status:** AD-389 complete — 7 vitest new, 2652 pytest + 62 vitest = 2714 total

### AD-390: Ambient Intelligence & Bridge States (DONE)

**Decision:** AD-390 — Add ambient visual intelligence to the glass layer. Three bridge states (idle/autonomous/attention) derived from agentTasks + notifications drive ambient edge glow colors and the new Context Ribbon HUD strip. Return-to-bridge briefing card after Captain absence. Completion celebrations bloom department colors.

**Changes:**
- New `ui/src/components/glass/ContextRibbon.tsx`: dense HUD strip (32px) at top of glass layer, JetBrains Mono 10px, shows bridge state dot+label, agent count, active task count, attention count (conditional), system mode. Exports `deriveBridgeState()` and `BridgeState` type. State-colored bottom border glow with 1.2s transition.
- New `ui/src/components/glass/BriefingCard.tsx`: return-to-bridge summary card (320px), glass morphism, shows completed tasks + new notifications + bridge state. Auto-dismiss 8s, click-to-dismiss. Briefing-fade-in animation.
- Modified `ui/src/components/GlassLayer.tsx`: ambient edge glow (`EDGE_GLOW` per bridge state — cyan/gold/amber inset box-shadow), ContextRibbon integration, activity tracking (lastActivityRef, wasAwayRef, snapshotRef for 3-min inactivity threshold), celebration detection (prevStatusesRef comparing status transitions, 600ms department-colored bloom), briefing state (showBriefing useState keeps layer mounted during briefing). Renders when active tasks exist OR briefing is pending.
- New `ui/src/__tests__/GlassBridgeState.test.tsx`: 11 tests — deriveBridgeState (6 cases: null/empty→idle, done/failed→idle, active→autonomous, requires_action→attention, action_required notif→attention, acknowledged notif→autonomous), edge glow color mapping (3), celebration detection (2: working→done triggers, done→done doesn't)

**Build prompt:** `prompts/ad-390-ambient-intelligence.md`
**Status:** AD-390 complete — 11 vitest new, 2652 pytest + 73 vitest = 2725 total

### AD-391: Cyberpunk Atmosphere Layer (DONE)

**Decision:** AD-391 — Add opt-in cyberpunk atmosphere effects to the glass layer. Configurable scan lines, chromatic aberration, and data rain (Ctrl+Shift+D toggle) — all off by default. Luminance ripple transitions sweep on bridge state changes. Sound engine gains DAG step chords, bridge state ambient hum, and Captain return tone. Atmosphere preferences persisted to localStorage.

**Changes:**
- New `ui/src/components/glass/ScanLineOverlay.tsx`: CSS-only repeating-linear-gradient scan lines (2px spacing), opacity scales with `atmosphereIntensity` (0→0, 1→0.8), slow vertical scroll animation (8s loop), data-testid
- New `ui/src/components/glass/DataRainOverlay.tsx`: canvas-based falling hex characters (0-9, A-F, unicode blocks), bridge-state-colored, column density scales with intensity, requestAnimationFrame loop with proper cleanup, JetBrains Mono 10px, fade top→bottom
- Modified `ui/src/components/glass/ContextRibbon.tsx`: exported `STATE_COLORS` record for DataRainOverlay consumption
- Modified `ui/src/components/GlassLayer.tsx`: integrated ScanLineOverlay + DataRainOverlay + chromatic aberration SVG filter + luminance ripple (80ms left-to-right sweep on bridgeState change) + Ctrl+Shift+D keyboard handler + Captain return sound cue on briefing appearance
- Modified `ui/src/audio/soundEngine.ts`: `playStepComplete(stepIndex, totalSteps)` ascending major-third chord, `playBridgeHum(state)` continuous ambient oscillators with cross-fade, `playCaptainReturn()` two-note welcoming chime (E5→G5)
- Modified `ui/src/store/useStore.ts`: `scanLinesEnabled`, `chromaticAberrationEnabled`, `dataRainEnabled` (all default false), `atmosphereIntensity` (default 0.3, clamped 0-1), setters persist to `hxi_atmosphere_prefs` localStorage key
- New `ui/src/__tests__/GlassAtmosphere.test.tsx`: 10 tests — atmosphere defaults (3 false + 0.3 intensity), 3 setter+persistence tests, intensity clamping, localStorage round-trip, ripple detection logic, 3 sound engine method existence tests

**Build prompt:** `prompts/ad-391-cyberpunk-atmosphere.md`
**Status:** AD-391 complete — 10 vitest new, 2652 pytest + 83 vitest = 2735 total

### AD-392: Adaptive Bridge (DONE)

**Decision:** AD-392 — Final Glass Bridge phase. Trust-driven progressive reveal: low-trust agents get prominent cards (brighter, thicker border), high-trust agents get condensed cards (smaller, dimmer). Command Surface breathing: resting pill recedes to thin glow line during autonomous bridge state when Captain is away, swells on proximity (200px threshold). Captain's Gaze: mouse position promotes nearest task card with scale(1.03) + glow boost, throttled to 100ms intervals. Responsive breakpoints via `useBreakpoint()` hook adapt layout across ultrawide/standard/laptop/tablet/mobile.

**Changes:**
- New `ui/src/hooks/useBreakpoint.ts`: `getBreakpoint()` pure function + `useBreakpoint()` hook detecting 5 viewport ranges (ultrawide >2560, standard >1440, laptop >1024, tablet >768, mobile <=768)
- Modified `ui/src/components/glass/GlassTaskCard.tsx`: `trust` prop drives visual variants (low/medium/high bands with matching colors and sizes), `compact` prop for tablet/mobile, `isGazed` prop for Captain's Gaze boost. Exports `trustBand()` and `TRUST_COLORS` for testing.
- Modified `ui/src/components/glass/ContextRibbon.tsx`: `compact` prop hides labels on mobile, shows only state dot + counts
- Modified `ui/src/components/GlassLayer.tsx`: trust lookup from `agents` Map via `task.agent_id`, Captain's Gaze via throttled `onMouseMove` + `gazedTaskId` state, responsive layout via `useBreakpoint()`, compact props passed on tablet/mobile
- Modified `ui/src/components/IntentSurface.tsx`: Command Surface breathing — pill recedes to 80x4px glow line during autonomous state when mouse >200px away, swells on proximity (300ms ease-out) or non-autonomous state (800ms ease-in recede)
- New `ui/src/__tests__/GlassAdaptive.test.tsx`: 16 tests — trust band thresholds (3), trust color mapping (3), breakpoint detection (5), pill breathing logic (4), gaze throttle (1)

**Build prompt:** `prompts/ad-392-adaptive-bridge.md`
**Status:** AD-392 complete — 16 vitest new, 2652 pytest + 99 vitest = 2751 total. All 5 Glass Bridge phases done.

### AD-393: Personality Activation — Big Five Traits Wired into Agent Behavior (DONE)

**Decision:** AD-393 — Wire existing crew profile Big Five personality traits into the LLM system prompt. Added `_build_personality_block()` to `compose_instructions()` as Tier 1.5 between hardcoded identity and Federation Constitution. High traits (>=0.7) produce behavioral guidance (e.g., "Explore creative approaches"), low traits (<=0.3) produce inverse guidance (e.g., "Prefer proven patterns"), neutral traits are silent. Identity line includes callsign, display_name, role, department. Cached via `@lru_cache`. Horizontal concern — activates personality for all 12 agents. Also added `"scout": "science"` to `_AGENT_DEPARTMENTS` preparing for AD-394.

**Changes:**
- Modified `src/probos/cognitive/standing_orders.py`: `_build_personality_block()`, `_TRAIT_GUIDANCE` mapping, Tier 1.5 insertion, `load_seed_profile` import, `clear_cache()` updated, `"scout"` department entry
- Modified `tests/test_standing_orders.py`: 3 existing tests adjusted for personality block appearing in composed output
- New `tests/test_personality_wiring.py`: 10 tests — high/low/neutral trait guidance, identity with/without callsign, no-profile graceful skip, composed ordering, all-high/all-neutral, cache verification

**Build prompt:** `prompts/ad-393-personality-activation.md`
**Status:** AD-393 complete — 10 pytest new, 2673 pytest + 99 vitest = 2772 total.

### AD-394: ScoutAgent — Daily GitHub Intelligence Gathering (DONE)

**Decision:** AD-394 — Science department officer (callsign Wesley) that searches GitHub REST API for recent AI agent repos, classifies as absorb/visiting_officer/skip via LLM with structured ===SCOUT_REPORT=== blocks, filters by relevance (>=3), stores daily JSON reports in data/scout_reports/, delivers Discord digest to configured scout_channel_id, posts Bridge notifications for relevance >=4. /scout and /scout report slash commands. TaskScheduler daily interval. Seen repos tracked with 90-day pruning. First agent to use AD-393 personality activation — high openness (0.9), low neuroticism (0.2).

**Changes:**
- New `src/probos/cognitive/scout.py`: ScoutAgent, ScoutFinding, parse_scout_reports(), filter_findings(), format_digest(), GitHub REST API search, Discord delivery, report persistence
- New `config/standing_orders/crew_profiles/scout.yaml`: Big Five personality + Wesley callsign
- Modified `src/probos/runtime.py`: register scout template, create pool, add to Science group, schedule daily scan
- Modified `src/probos/experience/shell.py`: /scout command (COMMANDS dict + _dispatch_slash + _cmd_scout handler)
- Modified `src/probos/config.py`: scout_channel_id field on DiscordConfig
- Modified `config/system.yaml`: scout_channel_id default
- New `tests/test_scout.py`: 10 tests — parsing, classification, filtering, seen tracking, Discord format, notification threshold, graceful no-Discord

**Build prompt:** `prompts/ad-394-scout-agent.md`
**Status:** AD-394 complete — 10 pytest new, 2683 pytest + 99 vitest = 2782 total.

### AD-395: CredentialStore + Scout gh CLI Enhancement (DONE)

**Decision:** AD-395 — CredentialStore: Ship's Computer centralized credential resolution service. Resolution chain: config key (dot-path traversal) → env var → env var aliases → CLI command (subprocess) → None. Cached with 5-min TTL (configurable), audit-logged to event_log, department-scoped access control (future-ready). Built-in specs for github, discord, llm_api. Extensions register custom credentials via `register()`. Scout migrated from httpx to `gh api` subprocess for authenticated 5000 req/hr rate limits. Multi-dimensional source curation absorbed from GPT Researcher (25.9K stars): credibility and reliability scoring alongside relevance, with weighted composite_score. /credentials command for Captain visibility.

**Changes:**
- New `src/probos/credential_store.py`: CredentialSpec dataclass, CredentialStore class (resolution chain, caching, audit logging, department-scoped access, register(), available(), list_credentials())
- Modified `src/probos/cognitive/scout.py`: removed _get_gh_token() and httpx, added _search_github() via gh api subprocess, added credibility/reliability fields to ScoutFinding, composite_score property, updated parse_scout_reports/filter_findings/format_digest/act for multi-dimensional scoring
- Modified `src/probos/runtime.py`: register CredentialStore on Runtime.__init__
- Modified `src/probos/experience/shell.py`: /credentials command (COMMANDS dict + _dispatch_slash + _cmd_credentials handler)
- New `tests/test_credential_store.py`: 13 tests — config key, env var, aliases, CLI, priority chain, cache TTL, available, list_credentials, department scope, extension registration, audit logging, unknown credential
- Modified `tests/test_scout.py`: 16 tests total (6 new) — credibility/reliability parsing, backward compat defaults, composite_score calculation, gh CLI search, gh not found graceful degradation

**Build prompt:** `prompts/ad-395-credential-store-scout-enhancement.md`
**Status:** AD-395 complete — 19 pytest new (13 credential store + 6 scout), 2702 pytest + 99 vitest = 2801 total.

### AD-396: Quality Hardening — Subprocess Encoding, Path Safety, Integration Tests (IN PROGRESS)

Dogfooding ScoutAgent on Windows exposed 9 integration bugs that unit tests with mocks couldn't catch. This AD fixes all known instances of systemic issues and adds integration tests to prevent regression. Four categories: (1) Windows subprocess encoding — 7 calls using `text=True` (cp1252 default) instead of `encoding="utf-8"`, (2) Scout hardcoded `_DATA_DIR` from `__file__` instead of runtime `_data_dir`, (3) personality trait type safety in standing_orders.py, (4) integration tests for shell↔agent boundary, encoding, and path resolution.

**Changes:**
- Fix 7 subprocess.run calls across 4 files: `text=True` → `encoding="utf-8", errors="replace"`
- Replace Scout module-level `_DATA_DIR` with runtime-resolved properties
- Add `isinstance` type guard for personality trait values
- New `tests/test_quality_hardening.py` — integration tests for encoding, paths, types, boundaries
- Update `tests/test_scout.py` for new `_load_seen`/`_save_seen` signatures

**Build prompt:** `prompts/ad-396-quality-hardening.md`
**Status:** AD-396 complete — 13 pytest new (net +2 after scout test consolidation), 2704 pytest + 99 vitest = 2803 total.
