# ProbOS — Architectural Decisions

Append-only log of architectural decisions made during ProbOS development. Each AD documents the reasoning behind a design choice.

See [PROGRESS.md](PROGRESS.md) for project status. See [docs/development/roadmap.md](docs/development/roadmap.md) for future plans.

**Archives:** [Era I — Genesis](decisions-era-1-genesis.md) | [Era II — Emergence](decisions-era-2-emergence.md) | [Era III — Product](decisions-era-3-product.md)

---

## Era IV — Evolution (Phases 30+)

## Phase 32t: BuildBlueprint & ChunkSpec — Pattern Buffer (AD-330)

| AD | Decision |
|----|----------|
| AD-330 | BuildBlueprint & ChunkSpec — Pattern Buffer data structures for the Transporter Pattern (Northstar II). (a) `ChunkSpec` dataclass: single unit of parallel work with chunk_id, description, target_file, what_to_generate, required_context, expected_output, depends_on (DAG edges), constraints. (b) `ChunkResult` dataclass: Structured Information Protocol (adapted from LLM×MapReduce) — generated_code, decisions rationale, output_signature, confidence (1-5), tokens_used. (c) `BuildBlueprint` dataclass: wraps `BuildSpec` with interface_contracts, shared_imports, shared_context, chunk_hints, chunks list, results list. `validate_chunk_dag()` uses Kahn's algorithm to detect cycles. `get_ready_chunks(completed)` returns chunks whose dependencies are satisfied. (d) `create_blueprint(spec)` factory function. All pure data — no LLM calls, no I/O. |

**Status:** Complete — 17 new Python tests, 1989 Python + 30 Vitest total

## Phase 32u: ChunkDecomposer — Dematerializer (AD-331)

| AD | Decision |
|----|----------|
| AD-331 | ChunkDecomposer — Dematerializer for the Transporter Pattern. (a) `decompose_blueprint()` async function: fast-tier LLM analyzes BuildBlueprint and produces ChunkSpec list. Builds AST outlines of target files, gathers import context from CodebaseIndex (optional), constructs decomposition prompt with rules. Parses JSON response, normalizes `depends_on` (int→chunk-id, string passthrough). Validates DAG (no cycles) and coverage (every target file has a chunk). (b) `_build_chunk_context()` helper: builds required_context for each chunk from interface contracts, shared imports, shared context, and target file outline (L1 AST) + imports section. (c) `_fallback_decompose()` helper: robust fallback when LLM fails — one chunk per target file, one per test file (depends on all impl chunks). Three fallback triggers: LLM error, invalid JSON, cyclic DAG. |

**Status:** Complete — 14 new Python tests, 2003 Python + 30 Vitest total

## Phase 32v: Parallel Chunk Execution — Matter Stream (AD-332)

| AD | Decision |
|----|----------|
| AD-332 | Parallel Chunk Execution — Matter Stream for the Transporter Pattern. (a) `execute_chunks()` async function: wave-based parallel execution via `asyncio.gather()`. `get_ready_chunks()` drives the loop — independent chunks run concurrently, dependent chunks wait. Partial success is valid (assembler handles). (b) `_execute_single_chunk()`: deep-tier LLM generation with `asyncio.wait_for()` timeout and configurable retry. Builds focused per-chunk prompt, uses Builder file-block output format (===FILE:/===MODIFY:). (c) `_build_chunk_prompt()`: assembles chunk description, constraints, required_context, and completed dependency outputs (capped at 2000 chars/dep). (d) `_parse_chunk_response()`: extracts file blocks via `_parse_file_blocks()`, DECISIONS rationale, CONFIDENCE score (1-5, clamped), output signature (CREATE/MODIFY). Structured Information Protocol from LLM×MapReduce. |

**Status:** Complete — 15 new Python tests, 2018 Python + 30 Vitest total

## Phase 32w: ChunkAssembler — Rematerializer (AD-333)

| AD | Decision |
|----|----------|
| AD-333 | ChunkAssembler — Rematerializer for the Transporter Pattern. (a) `assemble_chunks()` function: merges ChunkResults into unified `list[dict]` in `_parse_file_blocks()` format for `execute_approved_build()`. Re-parses each successful chunk's generated_code via `_parse_file_blocks()`. Groups by (path, mode). CREATE blocks: confidence-sorted merge via `_merge_create_blocks()`. MODIFY blocks: concatenated replacement lists, higher-confidence first. Failed chunks skipped (partial assembly valid). (b) `_merge_create_blocks()` helper: separates imports from body in each content block, deduplicates imports while preserving order, concatenates body parts. (c) `assembly_summary()` helper: chunk statuses dict with success/failure/confidence/tokens for logging and HXI display. Zero-LLM, pure code. |

**Status:** Complete — 13 new Python tests, 2031 Python + 30 Vitest total

## Phase 32x: Interface Validator — Heisenberg Compensator (AD-334)

| AD | Decision |
|----|----------|
| AD-334 | Interface Validator — Heisenberg Compensator for the Transporter Pattern. Zero-LLM post-assembly verification via Python `ast` module. (a) `ValidationResult` dataclass with per-chunk error/warning attribution (type, message, file, chunk_id). (b) `validate_assembly()` runs 5 checks: syntax validity (ast.parse), duplicate top-level definitions (Counter on defs), empty MODIFY search strings, interface contract satisfaction (regex-extracted function names), and stricter unresolved-name checking (ast-based) for low-confidence chunks (confidence ≤ 2). Errors = invalid, warnings = advisory. (c) `_find_chunk_for_file()` for error attribution with suffix matching. (d) `_find_unresolved_names()` conservative best-effort ast-based name resolution (defs, imports, assignments, params, builtins, common typing names excluded). |

**Status:** Complete — 15 new Python tests, 2046 Python + 30 Vitest total

## Phase 32y: HXI Transporter Visualization (AD-335)

| AD | Decision |
|----|----------|
| AD-335 | HXI Transporter Visualization — WebSocket event emission for the Transporter Pattern chunk lifecycle. (a) `decompose_blueprint()` and `execute_chunks()` gain optional `on_event: Any | None = None` async callback parameter. `decompose_blueprint` emits `transporter_decomposed` (with chunk_count, chunks list, fallback flag) on both success and fallback paths. `execute_chunks` emits `transporter_wave_start` (wave number, chunk_ids), `transporter_chunk_done` (per-chunk success/failure/confidence), and `transporter_execution_done` (summary counts and wave total). Wave counter tracks execution progress. (b) `_emit_transporter_events()` async helper in builder.py emits `transporter_assembled` (file_count, assembly_summary) and `transporter_validated` (valid, errors, warnings, checks_passed/failed) via runtime._emit_event(). (c) Frontend: `TransporterChunkStatus` and `TransporterProgress` interfaces in types.ts, `transporterProgress` state field in useStore.ts initialized to null, 6 handleEvent switch cases with Star Trek-themed chat messages (hexagon prefix, "Matter stream", "Rematerialized", "Heisenberg compensator"). All backward compatible — on_event defaults to None, existing callers unchanged. |

**Status:** Complete — 8 new Python tests, 2054 Python + 30 Vitest total

## Phase 32z: End-to-End Integration & Fallback (AD-336)

| AD | Decision |
|----|----------|
| AD-336 | End-to-End Integration & Fallback — Wire the Transporter Pattern into the BuilderAgent lifecycle. (a) `_should_use_transporter(spec, context_size)` — decision function: >2 target files, >20K context chars, or >2 combined impl+test files triggers Transporter. (b) `transporter_build(spec, llm_client, work_dir, codebase_index, on_event)` — orchestrates full pipeline (create_blueprint → decompose_blueprint → execute_chunks → assemble_chunks → validate_assembly), returns `list[dict]` file blocks in same format as `_parse_file_blocks()`. Validation failures logged as warnings but blocks still returned; downstream test-fix loop in `execute_approved_build()` catches real issues. Empty list on total failure. (c) `BuilderAgent.perceive()` augmented: builds BuildSpec from intent params, evaluates `_should_use_transporter()`, runs `transporter_build()` if triggered, stores result on `self._transporter_result`. Graceful fallback to single-pass on any exception. (d) `BuilderAgent.decide()` overridden: checks `_transporter_result`, returns transporter decision directly (skips LLM call), consumes attribute. Falls through to `super().decide()` for single-pass. (e) `BuilderAgent.act()` handles `"action": "transporter_complete"` — returns pre-parsed `file_changes` without re-parsing. Existing single-pass path unchanged. `execute_approved_build()` NOT modified — receives identical file block format from either path. |

**Status:** Complete — 12 new Python tests, 2066 Python + 30 Vitest total

---

## Builder Quality Gates & Standing Orders (AD-337 through AD-341)

| AD | Decision |
|----|----------|
| AD-337 | Implement /ping Command — First end-to-end Builder test. Builder generated `/ping` slash command with system uptime, agent count, health score. Revealed 4 pipeline defects: (a) `execute_approved_build()` commits regardless of test passage. (b) API does not pass `llm_client`, disabling the test-fix loop. (c) "Files: 0" for MODIFY-only builds. (d) Minimal test-writing guidance in Builder instructions. Manual fixes: test_shell.py rewrite, path resolution (`_resolve_path`, `_normalize_change_paths`), per-tier LLM timeout, pytest subprocess fix, api.py self-mod approval bypass. |
| AD-338 | Builder Commit Gate & Fix Loop — `execute_approved_build()` now gates commits on test passage: when tests fail, code stays on disk for debugging but is NOT committed, `result.success = False`, `result.error` contains last 1000 chars of test output. `_execute_build()` in api.py creates `LLMClient` and passes it to enable 2-retry LLM-powered fix loop. File count reports `files_written + files_modified`. 4 tests (TestCommitGate). |
| AD-339 | Standing Orders Architecture — ProbOS constitution system. 4-tier hierarchy: Federation Constitution (universal, immutable) → Ship Standing Orders (per-instance) → Department Protocols (per-department) → Agent Standing Orders (per-agent, evolvable via self-mod). `config/standing_orders/` with 7 seed files. `compose_instructions()` assembles complete system prompt at call time. Integrated into `CognitiveAgent.decide()`. Key invariant: empty/missing directory = identical behavior. Like Claude Code's CLAUDE.md but hierarchical and evolvable. No IDE dependency. 13 tests. |
| AD-340 | Builder Instructions Enhancement — 7 test-writing rules added to `BuilderAgent.instructions`: __init__ signatures, full `probos.*` import paths, `_Fake*` stubs, `pytest.mark.asyncio`, mock completeness tracing, assertion accuracy, encoding safety. 1 test. |
| AD-341 | Code Review Agent — `CodeReviewAgent` reviews Builder output against Standing Orders before commit gate. Engineering department, standard LLM tier. Soft gate (logs issues, doesn't block). Fails-open on LLM error. `review()`, `_format_changes()`, `_parse_review()`. `BuildResult` extended with `review_result` and `review_issues`. Surfaced in build_success event payload. 10 + 2 integration tests. |

**Status:** AD-337–341 all complete — 2243 Python + 30 Vitest (30 new tests from AD-338–341).

---

## Standing Orders Display & Builder Failure Escalation (AD-342 through AD-347)

| AD | Decision |
|----|----------|
| AD-342 | Standing Orders Display Command — `/orders` slash command showing all standing orders files with tier classification (Federation Constitution/Ship/Department/Agent), first non-heading line as summary, and file size. Builder attempted this command but commit gate correctly blocked it (pytest timed out at 120s on 2254 tests + missing `from pathlib import Path` import). Manual fix + 4 tests. |
| AD-343 | BuildFailureReport & Failure Classification — Structured failure report dataclass (`BuildFailureReport`) with categorization (timeout, test_failure, syntax_error, import_error, llm_error, commit_error). `classify_build_failure()` parses pytest output to extract failed test names and file:line error locations. Generates resolution options per category. `to_dict()` for WebSocket serialization. 12 tests. |
| AD-344 | Smart Test Selection — `_map_source_to_tests()` maps source files to test files by naming convention (`src/probos/foo/bar.py` → `tests/test_bar*.py`). `_run_targeted_tests()` two-phase: targeted first (60s), full suite only if targeted pass (180s). Fix loop uses targeted tests for faster retries. 6 tests. |
| AD-345 | Enriched Failure Event & Resolution API — `build_failure` WebSocket event enriched with `BuildFailureReport`. `_pending_failures` cache with 30-min TTL. `POST /api/build/resolve` endpoint handles: retry_extended, retry_targeted, retry_fix, retry_full, commit_override, abort. 1 test. |
| AD-346 | HXI Build Failure Diagnostic Card — Frontend failure card in IntentSurface.tsx with category badge, metadata (AD, title, files, branch, fix attempts), failed tests list, collapsible raw error, resolution action buttons (color-coded: blue=retry, amber=commit_override, gray=abort). `BuildFailureReport` TypeScript interface. `build_resolved` WebSocket event handler. |
| AD-347 | Builder Escalation Hook — `escalation_hook` parameter on `execute_approved_build()`. Called after fix loop exhausted, before failure reaches Captain. Returns `BuildResult` if crew resolved, `None` to escalate. Errors caught, fails-open. No-op initially; Phase 33 wires to chain of command. 4 tests. |

**Status:** AD-342–347 all complete — 2281 Python + 30 Vitest (38 new Python tests from AD-343–347).

### AD-348: Fix Self-Mod False Positive on Knowledge Questions (BF-001)

Knowledge questions ("who is Alan Turing?") no longer trigger capability_gap. Prompt rules in prompt_builder.py and decomposer.py updated to classify general knowledge/factual questions as conversational (answer directly) rather than task gaps. The "who is Alan Turing?" gap example removed from _GAP_EXAMPLES. Distinction: tasks requiring external tools (translation, web search) → capability_gap; well-known factual questions → direct LLM answer.

### AD-349: Fix Agent Orbs Escaping Pool Group Spheres (BF-002)

`poolToGroup` and `poolGroups` persisted in Zustand state from `state_snapshot` handler. `agent_state` handler passes persisted pool group data to `computeLayout()`, preserving cluster positions. Previously, `agent_state` called `computeLayout(agents)` without pool data, falling back to flat Fibonacci sphere layout.

### AD-350: Fix Diagnostician Bypassing VitalsMonitor (BF-003)

VitalsMonitorAgent gains `scan_now()` for on-demand metric collection (no threshold checks, no alerts). DiagnosticianAgent overrides `perceive()` to detect `diagnose_system` intents and fetch live metrics via `scan_now()`. Instructions updated to differentiate `medical_alert` (alert data provided) from `diagnose_system` (metrics gathered proactively). Graceful fallback if VitalsMonitor unavailable.

**Status:** AD-348–350 all complete — 2283 Python + 32 Vitest (BF-001/002/003 all closed).

### AD-351: CopilotBuilderAdapter

`CopilotBuilderAdapter` wraps the GitHub Copilot SDK Python package to execute build tasks as a visiting officer. The adapter is NOT a CognitiveAgent — it's an external system wrapper (like ChannelAdapter for Discord). Creates a CopilotClient, injects ProbOS Standing Orders as system instructions, registers MCP tools, translates BuildSpec to session prompt, captures output in native file block format. Fails-open on any SDK error. SDK import guarded with try/except (optional dependency). `CopilotBuildResult` dataclass for structured output. 11 tests.

### AD-352: ProbOS MCP Tool Server

Seven MCP tools registered with Copilot sessions via the SDK's `Tool` class: `codebase_query` (CodebaseIndex.query), `codebase_find_callers` (find_callers), `codebase_get_imports` (get_imports), `codebase_find_tests` (find_tests_for), `codebase_read_source` (read_source), `system_self_model` (SystemSelfModel.to_context), `standing_orders_lookup` (department protocol files). Tools expose ProbOS internals so the visiting Builder has the same knowledge as the native Builder. Each handler returns `{"textResultForLlm": str, "resultType": "success"}`. 8 tests.

### AD-353: Routing & Apprenticeship Wiring

`_should_use_visiting_builder()` routing decision based on SDK availability, force flags, and Hebbian weight comparison. `builder_source` field added to `BuildResult` ("native" or "visiting"). Hebbian `builder_variant` relationship type tracks `(build_code, native|visiting)` success/failure. Outcomes recorded after Copilot session (immediate) and after test results (execute_approved_build). Default: prefer visiting in bootstrap phase. Over time, Hebbian weights steer toward whichever builder produces more passing code. `REL_BUILDER_VARIANT` constant in routing.py. 11 tests.

**Status:** AD-351–353 all complete — 2313 Python + 32 Vitest (30 new tests from AD-351–353).

### AD-354: Visiting Officer HXI Integration

Three bug fixes and three enhancements for end-to-end Copilot SDK visiting officer integration. Bug 1: `_normalize_sdk_path()` normalizes absolute/backslash/mixed-separator paths from SDK `workspace_file_changed` events to cwd-relative forward-slash paths. Bug 2: `perceive()` creates temp directory for visiting builder sessions — SDK writes to temp dir, not project root, preserving Captain approval gate. Bug 3: `force_native`/`force_visiting`/`model` params pass through from `BuildRequest` → intent params → `_should_use_visiting_builder()` and adapter constructor. Enhancement 1: `builder_source` propagated to `build_generated` WebSocket event. Enhancement 2: `model` field on `BuildRequest` for model selection. Enhancement 3: `BuildProposal.builder_source` in HXI store for UI badge display. Hebbian weight comparison wrapped in try/except for mock-safety. Builder agent tests get autouse fixture disabling visiting builder. 12 new tests (42 total in file).

**Status:** AD-354 complete — 2325 Python + 34 Vitest.

### AD-355: Visiting Officer Live Testing Fixes

Three fixes from live HXI testing of the visiting officer. Issue 1: Added `WORKING ENVIRONMENT` and `PROJECT STRUCTURE` sections to `_VISITING_BUILDER_INSTRUCTIONS` — SDK agent no longer wastes time exploring the temp directory filesystem; told it's isolated, all context comes through MCP tools, and given the project layout (src/probos/, tests/, config/). Issue 2: Reduced diagnostic logging — removed early message-count log, changed disk-scan file list and per-file capture to `logger.debug`, added consolidated `logger.info` with message count + file count after scan completes. Issue 3: Added `PYTHONPATH` with project root + `src/` to the subprocess env in both `_run_tests()` and `_run_targeted_tests()` — visiting officer files at project root can now be imported by tests.

**Status:** AD-355 complete — 2327 Python + 34 Vitest.

### AD-357: Cognitive Evolution & Earned Agency Framework

*"In the 24th century, we don't lock doors — because nobody needs to be locked out."*

A comprehensive framework for agent learning, evolution, and self-originated goals. Seven reinforcement gaps identified in the current Trust/Hebbian/Dream system, plus a new concept: **Earned Agency** — the privilege of self-directed goal-setting, unlocked through demonstrated trustworthiness.

**Philosophical foundation:** ProbOS agents exist within a social fabric (trust, consensus, standing orders, chain of command). When an agent has proven itself trustworthy — sustained high trust, positive Hebbian weight, Counselor fitness, no standing order violations — it earns increasing freedom. Agency is not a right; it's the natural reward for demonstrated reliability within the civilization. No locks needed when no one has ill intent.

**Seven Reinforcement Gaps:**

1. **Multi-dimensional reward signals** — Replace binary success/failure with a reward vector: completion, quality (review score), efficiency (tokens/time), novelty, collaboration quality. Stored in Cognitive Journal. Hebbian router weights on all dimensions.

2. **Hindsight experience replay** — During dream cycles, replay failed tasks. Agent (or peer) critiques the failure, generates "what I should have done" reflections. Reflections become Standing Orders amendments via self-mod pipeline. Agents literally learn from their mistakes.

3. **Tournament evaluation / competitive selection** — Occasionally run two agents (or two models) on the same task. Reviewer picks best output. Winner's Hebbian weight increases; loser studies winner's approach. Evolutionary pressure for improvement. Generalizes the visiting officer apprenticeship pattern.

4. **Emergent capability profiles** — Dynamic capability descriptors that grow from demonstrated success. Agent succeeds at unfamiliar task type → gains weak capability score. Repeated success strengthens it. Over time, agents naturally specialize or generalize based on performance, not predetermined labels.

5. **Memetic evolution / cross-agent knowledge transfer** — Successful strategies codified into shared crew knowledge base. Any agent can query "has anyone solved something like this?" Results weighted by originator's trust score. Cultural evolution — ideas that work spread through the crew. Federation-scale = The Nooplex's collective intelligence.

6. **Curiosity-driven exploration** — Counselor analyzes capability gaps across the crew, recommends training. Agents generate their own practice tasks, run in sandbox, learn from results. Intrinsic motivation rather than purely reactive task handling.

7. **Semantic Hebbian generalization** — Replace exact task_type string matching with semantic similarity for Hebbian lookup. Agent good at "build_code" gets routing boost for "build_test." Embedding-based similarity using existing keyword scoring infrastructure.

**Earned Agency — The Privilege of Self-Direction:**

Trust tier progression (inspired by Starfleet rank structure):

| Trust Level | Rank Analog | Agency Level | Oversight |
|-------------|-------------|--------------|-----------|
| < 0.5 | Ensign | Reactive only — executes assigned tasks | Full supervision, all actions gated |
| 0.5–0.7 | Lieutenant | Proactive suggestions — can propose tasks to Captain | Light supervision, routine actions auto-approved |
| 0.7–0.85 | Commander | Self-originated goals — can set own objectives within department scope | Peer review, Counselor monitoring |
| 0.85+ | Senior Officer | Full agency — can initiate cross-department work, mentor others, propose architectural changes | Captain notified, not gated (unless flagged by Counselor) |

**Safety invariants** (these never relax regardless of trust):
- Destructive actions always require Captain approval
- Core system modifications always go through full pipeline
- Trust score regression immediately reduces agency level
- Counselor can flag cognitive drift and recommend demotion
- Standing Orders violations trigger immediate agency review
- Captain can override any autonomous action at any time

**Self-originated goals emerge from:**
- Dream consolidation — "I keep seeing pattern X fail; I should address that"
- Curiosity gap detection — "I've never handled task type Y; I should prepare"
- Hebbian drift — "My success rate on Z is declining; something changed"
- Peer observation — "Agent A solved a problem I couldn't; I should learn that technique"
- Codebase monitoring — "A new module was added; I should index and understand it"

**Implementation sequencing:**
- Phase 1 (extends Phase 28): Multi-dimensional rewards + hindsight replay + emergent capabilities
- Phase 2 (extends Phase 30/33): Tournament evaluation + memetic knowledge sharing + Counselor-driven curiosity
- Phase 3 (extends Phase 33): Earned Agency tiers + self-originated goals + decreasing oversight

**Status:** AD-357 — Architecture decision captured. Implementation spans Phases 28, 30, 33.

### AD-358: Per-Tier Temperature & Top-P Tuning

Different cognitive modes benefit from different generation temperatures. Research from Kimi K2.5 (Moonshot AI) shows deep reasoning benefits from higher temperature (diversity of thought), while fast classification benefits from lower temperature (deterministic, consistent).

Added per-tier `temperature` and `top_p` configuration to CognitiveConfig. Six new optional fields (`llm_temperature_{fast,standard,deep}`, `llm_top_p_{fast,standard,deep}`) serve as tier-level defaults. When not set, returns `None` (no fallback). Request-level values always override tier defaults (caller wins). The `top_p` field was also added to `LLMRequest`.

Wiring: `complete()` resolves effective temperature/top_p from tier config when the caller hasn't set a non-default value, then passes through `_call_api()` → `_call_openai()`/`_call_ollama_native()`. `tier_info()` reports sampling params for `/models` and `/registry` display.

**Status:** AD-358 — Implemented. 5 new tests, 0 regressions (22+36 pass). Built by visiting officer (Copilot SDK), cleanup by architect.

### AD-359: Captain's Yeoman — Personal AI Assistant (Phase 36)

*"The Captain's Yeoman handles everything the Captain shouldn't have to think about."*

The single biggest adoption barrier for ProbOS is that it requires understanding agents, pools, and trust to get started. OpenClaw reached 323K stars because it gave every user immediate personal value — a personal AI they could talk to. ProbOS has an entire crew behind a front door that's too narrow. The Yeoman changes that.

**The Captain's Yeoman** is ProbOS's default conversational interface — the first agent every user meets. It handles personal tasks (calendar, email, research, reminders, shopping), learns preferences over time, and delegates to the crew when needed. It's the "front door" that makes ProbOS useful to anyone, not just developers.

**Why this belongs in OSS:**
- It's the adoption funnel — if the Yeoman is behind a paywall, users never experience ProbOS
- The infrastructure is already OSS (agents, pools, trust, memory, channels)
- The Yeoman is a crew member using existing systems, not a separate product
- Follows the boundary rule: "how it works" → OSS; "how it makes money" → commercial
- Commercial value comes from managed hosting, premium integrations (Teams, Salesforce), Escort Ship Class bundling, and Nooplex fleet coordination — not the agent itself

**Architecture:**
- `YeomanAgent` — Bridge-level agent (like First Officer and Counselor). Not assigned to any department — serves the Captain directly
- Conversational by default — natural language interaction, no commands required
- Routes to crew when needed: "Yeoman, have Engineering build me a script" → Builder pipeline. "What's the system health?" → Medical. "Design a new feature" → Science/Architect
- Uses episodic memory for personalization — remembers preferences, past conversations, frequently used workflows
- Extension-compatible — personal skills (home automation, finance tracking, fitness) installable as extensions
- Channel-native — works across all Phase 24 channels (CLI, web, Discord, Slack, mobile PWA, voice)
- Trust-integrated — Yeoman starts at Ensign level, earns agency through demonstrated reliability (AD-357 Earned Agency)

**The adoption funnel this enables:**
1. User installs ProbOS, meets the Yeoman — immediate personal value
2. Yeoman handles daily tasks, learns preferences — user stays engaged
3. User discovers the crew — "Wait, I can build custom agents?"
4. User explores extensions, Ship Classes, the Builder — becomes a Captain
5. Power users federate, build for others, join the Nooplex

**OSS vs Commercial boundary:**
- **OSS (Phase 36):** YeomanAgent, basic conversational interface, memory/personalization, crew routing, CLI/web/Discord channels, extension API for personal skills
- **Commercial:** Managed cloud hosting ("ProbOS Cloud"), premium channel adapters (Teams, Slack Enterprise), Escort Ship Class (curated Yeoman bundle), Nooplex fleet-wide assistant coordination, enterprise SSO/compliance/audit

**Status:** AD-359 — Architecture decision captured. Implementation: Phase 36.

### AD-360: Builder Pipeline Guardrails

*"The ship's safety systems catch what the crew might miss."*

Six structural guardrails added to `execute_approved_build()` and related functions to prevent the class of failures seen in visiting officer builds (files in wrong directories, stray files outside spec, branch collisions on retry):

1. **Branch lifecycle management** — `_git_create_branch()` deletes stale branches from prior failed builds before creating new ones (defensive fallback). `finally` block deletes the build branch when no commit was made (primary cleanup). Prevents branch name collisions on retry.

2. **File path validation** — `_validate_file_path()` function with `_ALLOWED_PATH_PREFIXES` (`src/`, `tests/`, `config/`, `docs/`, `prompts/`) and `_FORBIDDEN_PATHS` (`.git/`, `.env`, `pyproject.toml`, `.github/`). Blocks path traversal (`..`), absolute paths, and paths outside allowed directories. Hard gate — invalid paths are skipped with validation error.

3. **Visiting officer disk scan filtering** — `CopilotBuilderAdapter.execute()` disk scan rejects files outside expected project structure (`_EXPECTED_PREFIXES`). First line of defense catching the exact failure pattern: `probos/types.py` instead of `src/probos/types.py`.

4. **Build spec file allowlist** — After file-write loop, warns when builder produces files not in `spec.target_files`. Soft gate (advisory only) — logs warning but doesn't block. Future: hard gate after trust is established.

5. **Dirty working tree protection** — `_is_dirty_working_tree()` checks `git status --porcelain` before creating the build branch. Hard gate — build aborts with "uncommitted changes" error. Uses `asyncio.create_subprocess_exec` directly to avoid interference with existing `subprocess.run` mocks in tests.

6. **Untracked file cleanup** — `finally` block deletes files from the `written` list when build fails (git checkout restores modified files but doesn't delete newly created ones). Empty parent directories cleaned up to `work_dir`. Prevents stray files from lingering after failed builds.

Inspired by: Aider (pre-edit dirty commit, edit-lint-test-reflect cycle), Cline (shadow git checkpoints, workspace access tiers), SWE-Agent (container-scoped isolation), OpenHands (overlay mount pattern).

**Build prompt:** `prompts/builder-pipeline-guardrails.md`

**Status:** AD-360 — Implemented. 10 new tests (6 path validation + 2 branch lifecycle + 1 dirty tree + 1 untracked cleanup), 0 regressions. 2358 Python + 34 Vitest total. Note: Architect implemented directly (should have been delegated to builder — lesson learned on role discipline).

### AD-361: CI/CD Pipeline — GitHub Actions

*"All hands, condition green — automated systems online."*

GitHub Actions CI workflow running on every push to `main` and every pull request. Two parallel jobs:

1. **python-tests** — `ubuntu-latest`, Python 3.12, `uv sync --group dev` from lockfile, `pytest -x -q --tb=short`. `live_llm` tests auto-skipped by conftest. 15-minute timeout.
2. **ui-tests** — `ubuntu-latest`, Node 22 LTS, `npm ci`, `npm run test` (vitest), `npm run build` (tsc + vite type check). 10-minute timeout.

**CI stabilization fixes:**
- Flaky `test_decision_cache_ttl_expiry` — used `created_at=0.0` to force TTL expiry, but `time.monotonic()` returns system uptime. On freshly-booted CI runners, uptime < TTL so the entry wasn't expired. Fixed: `time.monotonic() - ttl - 1` guarantees expiry regardless of uptime.
- `TestCopilotBuilderAdapterExecution` — patches `SessionEventType` from `github-copilot-sdk`, which is an optional dependency not installed in CI. Fixed: `@pytest.mark.skipif(not _SDK_AVAILABLE, ...)`.
- `TestMCPToolHandlers` — tool handlers return `ToolResult` from the SDK. Fixed: fallback `ToolResult` class defined in `copilot_adapter.py` when SDK not importable.

**Build prompt:** `prompts/ci-cd-pipeline.md`

**Status:** AD-361 — Implemented and green. Both jobs passing on GitHub Actions.

### AD-362: Fix Bundled Persistence Silent Data Loss

*"Captain, the crew thinks they saved their work — but they didn't."*

GPT-5.4 code review found that TodoAgent, NoteTakerAgent, and SchedulerAgent report successful persistence while nothing reaches disk. `_mesh_write_file()` broadcast a `write_file` intent and saw `IntentResult(success=True)` from FileWriterAgent — but that was only a **proposal** (`requires_consensus: True`). Nobody called `commit_write()`, so zero bytes were written. The bundled agents didn't even check the return value.

**Fix:** Both copies of `_mesh_write_file()` (in `productivity_agents.py` and `organizer_agents.py`) now call `FileWriterAgent.commit_write()` directly, bypassing consensus (correct for user-owned personal data in `~/.probos/`). All three agents check the write return value and propagate failure.

**Build prompt:** `prompts/bundled-persistence-fix.md`

**Status:** AD-362 — Implemented. 4 new integration tests (3 disk persistence + 1 failure propagation), 0 regressions.

### AD-363: Fix Mock Reminder Routing

GPT-5.4 code review found that `MockLLMClient` routes "remind me to..." phrases to `manage_todo` instead of `manage_schedule`. The todo regex included `remind me to` as a final alternative and was registered before the scheduler pattern. First-match-wins dispatch meant reminders hit the wrong agent, masking scheduler regressions in tests.

**Fix:** Removed `remind me to` from the todo regex. Added `remind(?:er| me)` to the front of the scheduler regex.

**Build prompt:** `prompts/mock-reminder-routing-fix.md`

**Status:** AD-363 — Implemented. 1 new routing test, 0 regressions.

### AD-364: Fix get_event_loop in Async Code

GPT-5.4 code review found 7 call sites in the experience layer using `asyncio.get_event_loop()` inside `async def` methods. ProbOS Standing Orders (`ship.md` line 24) mandate `get_running_loop()`. All sites are inside async methods where a running loop is guaranteed.

**Fix:** Mechanical replacement of `get_event_loop()` → `get_running_loop()` at all 7 call sites (6 in `shell.py`, 1 in `renderer.py`).

**Build prompt:** `prompts/fix-get-event-loop.md`

**Status:** AD-364 — Implemented. 0 regressions.

### AD-365: Red-Team Write Verification

RedTeamAgent.verify() had no real handler for `write_file` intents — they fell through to a default that returned `verified=True` with `confidence=0.1`, making the governance path for writes weaker than it appeared. Added `_verify_write()` method that validates write proposals without re-executing: checks for empty path, missing content, path traversal (`..` in parts), forbidden paths (`.git/`, `.env`, `pyproject.toml`, `.github/workflows/`), and suspiciously large content (>1MB). Added `verify_write_file` capability descriptor. 4 new tests.

**Status:** AD-365 complete — 2356 Python + 34 Vitest.

### AD-366: Fix API Import Approval Callback Leak

API self-mod path in `api.py` set `_import_approval_fn` to auto-approve but never restored it. After the first HXI-triggered self-mod, all future import approvals (including interactive shell) were silently auto-approved. Fixed by saving `original_import_approval_fn` before overwriting and restoring it in the `finally` block, matching the existing pattern for `_user_approval_fn`. 1 new test verifies the restore pattern via source inspection.

**Status:** AD-366 complete — 2357 Python + 34 Vitest.

### AD-367: Move Validation Check Before Commit

In `execute_approved_build()`, `ast.parse()` validation errors were checked **after** the commit step. With `run_tests=False`, a file with syntax errors could be committed to the build branch, then marked as failed — but the commit was already done. Fixed by moving the `validation_errors` check before the commit block using an `if/elif` chain: syntax errors → block (no commit), test failures → escalation, clean → commit. 1 new test verifies syntax errors block commits even with `run_tests=False`.

**Status:** AD-367 complete — 2358 Python + 34 Vitest.

### AD-368: Self-Mod Registration Rollback

If agent type registration succeeded (step 4) but pool creation failed (step 5), the agent type remained registered in the spawner and decomposer — a phantom agent type that would accept intents but have no pool to run them. Fixed by adding `unregister_fn` parameter to `SelfModificationPipeline`, `unregister_template()` to `AgentSpawner`, and `unregister_agent_type()` to the runtime. On pool creation failure, the failed_pool handler now rolls back the registration (wrapped in try/except to not mask the original error). 1 new test verifies rollback is called.

**Status:** AD-368 complete — 2359 Python + 34 Vitest.

### AD-369: Fix WebSocket Protocol Detection

Hardcoded `ws://` in `useWebSocket.ts` would cause browsers to block WebSocket connections when ProbOS is served behind HTTPS. Changed to dynamic protocol detection: `wss:` for HTTPS origins, `ws:` for HTTP. Single-line fix.

**Status:** AD-369 complete — 2359 Python + 34 Vitest.

### BF-006: Fix Quorum Trust Docs Drift

`docs/architecture/consensus.md` had two inaccuracies found by GPT-5.4 code review: (1) listed "HTTP fetches" as consensus-gated (removed in AD-150, already fixed in structure.md and inventory.md by BF-005 but missed here), and (2) claimed each vote carries "the agent's current trust reputation" — the actual `Vote` dataclass has no trust field; votes carry `confidence`, not trust. Fixed both: removed "HTTP fetches" from destructive ops list, replaced trust bullet with "optional reason string" matching the actual `Vote` fields.

**Status:** BF-006 complete — docs only, no code changes.

### BF-004: Transporter HXI Visualization

The Transporter Pattern (AD-330–336) emits 6 event types during parallel chunk builds. The Zustand store already processes all 6 and updates `transporterProgress` state, but no component rendered it — data flowed from server → WebSocket → store → nowhere. Added a transporter progress card to `IntentSurface.tsx` that reads `transporterProgress` from the store and renders: phase badge, progress fraction, animated progress bar (teal fill + red for failures), chunk list with status dots (gray/pulsing amber/green/red), target file paths in monospace, and footer stats (waves completed, failed count). Card auto-clears when `transporterProgress` resets to null after validation. Teal/cyan color palette (`#50c8e0`) matches science/transporter theme. Follows BuildFailureReport card patterns for layout consistency.

**Status:** BF-004 complete — 2359 Python + 34 Vitest.

### AD-370: Structural Integrity Field (SIF)

"Medical detects damage. The SIF prevents structural failure." Lightweight runtime service that runs 7 pure-assertion invariant checks on every heartbeat cycle (5s). No LLM calls — every check reads in-memory data structures. `StructuralIntegrityField` is a Ship's Computer function, not an agent. Checks: trust bounds ([0,1] + finite), Hebbian weight bounds ([-10,10] + finite), pool consistency (agent types registered in spawner), IntentBus coherence (subscriber IDs exist in registry). Three checks (config validity, index consistency, memory integrity) are graceful no-ops pending future wiring. Each check is exception-isolated — one failure doesn't block others. `SIFReport` with `health_pct`, `all_passed`, `violations` properties. Background `asyncio.Task` with configurable interval. Wired into runtime `start()`/`stop()`. 12 tests.

**Build prompt:** `prompts/sif-structural-integrity.md`
**Status:** AD-370 complete — 2371 Python + 34 Vitest.

### AD-371: BuildQueue + WorktreeManager

Foundation for the Automated Builder Dispatch system (AD-371–374). Two standalone utilities with no runtime wiring (AD-372 does the wiring). **BuildQueue**: in-memory priority-ordered queue of `QueuedBuild` items tracking `BuildSpec`s through a lifecycle (`queued→dispatched→building→reviewing→merged/failed`). Status transition validation, file footprint conflict detection (`has_footprint_conflict()` via set intersection), cancel support, `active_count` property. IDs via `uuid4().hex[:12]`. 14 tests. **WorktreeManager**: async git worktree lifecycle management. `create()` makes worktree + branch, `remove()` force-removes + deletes branch, `collect_diff()` returns three-dot diff vs main, `merge_to_main()` merges and returns commit hash, `cleanup_all()` for shutdown. All git ops via `asyncio.create_subprocess_exec`. 6 tests with real git repos in `tmp_path`.

**Build prompt:** `prompts/build-queue-worktree-manager.md`
**Status:** AD-371 complete — 2391 Python + 34 Vitest.

### AD-372: BuildDispatcher + SDK Integration

Core dispatch loop for the Automated Builder Dispatch system. `BuildDispatcher` watches `BuildQueue`, allocates worktrees via `WorktreeManager`, invokes `CopilotBuilderAdapter` to generate code, and applies changes through `execute_approved_build()` with all existing guardrails (syntax validation, test-before-commit, code review). Pipeline: `dequeue → footprint conflict check → create worktree → read source files → adapter.execute() → execute_approved_build() → status update → callback`. Absorbs AD-374 (footprint conflict detection) via `_find_dispatchable()` which skips conflicting builds. Captain actions: `approve_and_merge()` (merge + cleanup) and `reject_build()` (cleanup only). Conditional SDK import (`_SDK_AVAILABLE`). Configurable: `max_concurrent` (default 2), `poll_interval` (5s), `builder_model`, `builder_timeout`, `run_tests`, `on_build_complete` callback. 11 tests.

**Build prompt:** `prompts/build-dispatcher.md`
**Status:** AD-372 complete — 2402 Python + 34 Vitest.

### AD-373: HXI Build Dashboard

Real-time build queue visualization in the HXI. `BuildQueueItem` interface in `types.ts` with full status lifecycle. Two WebSocket event handlers: `build_queue_update` (full snapshot) and `build_queue_item` (single upsert with chat logging for status transitions). Build Queue card in `IntentSurface.tsx` with: "Build Queue" header badge showing active count, item list with color-coded status dots (gray/blue/amber-pulsing/amber/green/red), title + AD number, status badge, Approve/Reject buttons for reviewing items (POST to `/api/build/approve` and `/api/build/reject`), file footprint display for reviewing items. Engineering amber theme (`#b0a050`, `rgba(176, 160, 80, ...)`). UI ready for backend API wiring.

**Build prompt:** `prompts/hxi-build-dashboard.md`
**Status:** AD-373 complete — 2402 Python + 34 Vitest.

### AD-376: CrewProfile + Personality System

Foundational crew identity layer. `CrewProfile` dataclass with identity (display_name, callsign, department, role), `Rank` enum (Ensign→Senior via `from_trust()`), `PersonalityTraits` (Big Five, 0.0–1.0 validated, `distance_from()` drift detection), `PerformanceReview` (append-only history), `ProfileStore` (SQLite persistence). `load_seed_profile()` reads YAML seeds from `config/standing_orders/crew_profiles/` with `_default.yaml` fallback. 12 crew profile YAMLs with seeded personalities and callsigns.

**Build prompt:** `prompts/crew-profile-personality.md`
**Status:** AD-376 complete — 2436 Python + 34 Vitest.

### AD-379: Per-Agent Standing Orders

Tier 5 personal standing orders for all 12 crew members. Auto-loaded by existing `compose_instructions()` in `standing_orders.py`. Each file under 20 lines defining standards, boundaries, and personality expression. Callsigns: Builder/Scotty, Architect/Number One, Diagnostician/Bones, Vitals Monitor/Chapel, Surgeon/Pulaski, Pharmacist/Ogawa, Pathologist/Selar, Red Team/Worf, System QA/O'Brien, Emergent Detector/Dax, Introspection/Data, Counselor.

**Build prompt:** `prompts/per-agent-standing-orders.md`
**Status:** AD-379 complete — config only, no test changes.

### AD-377: Watch Rotation + Duty Shifts

Naval-style watch rotation system for scheduled agent duty. Three watches: Alpha (full ops), Beta (reduced), Gamma (maintenance). `WatchManager` maintains a duty roster, dispatches `StandingTask` items (recurring department tasks with interval-based scheduling) and `CaptainOrder` directives (persistent orders, optionally one-shot) to on-duty agents via a configurable `dispatch_fn` callback. Orders for off-duty agents are deferred until their watch. The dispatch loop runs periodically and is start/stoppable. No runtime wiring yet — standalone module ready for integration. Fixed build prompt test: `get_active_orders()[0]` IndexError when one-shot order already deactivated (empty list); replaced with `executed_count` assertion.

**Status:** AD-377 complete — 2454 Python + 34 Vitest.

### AD-378: CounselorAgent + Cognitive Profiles

Ship's Counselor — Bridge-level CognitiveAgent monitoring crew cognitive wellness. `CognitiveBaseline` snapshots an agent's metrics at baselining time. `CounselorAssessment` computes drift from baseline (trust, confidence, Hebbian, personality) → wellness score (0.0–1.0) + concerns + recommendations + fit-for-duty/promotion flags. `CognitiveProfile` tracks assessment history with alert levels (green/yellow/red) and drift trending. `CounselorAgent` extends `CognitiveAgent` in pool="bridge" with 3 intent descriptors (assess, wellness report, promotion fitness). Deterministic fast-path `assess_agent()` method; LLM path via `decide()` adds nuanced judgment. Bridge department protocol updated.

**Status:** AD-378 complete — 2472 Python + 34 Vitest.

### AD-322: Mission Control Kanban Dashboard

4-column Kanban board (Queued → Working → Review → Done) as a full-screen overlay in the HXI. `MissionControl.tsx` with `TaskCard` component: department color coding (engineering gold, science teal, medical blue, security red, bridge gold), AD number badges, agent type, elapsed time, status dot with pulse animation for in-progress items. Approve/Reject buttons on review-status cards call existing `/api/build/queue/approve` and `/api/build/queue/reject` endpoints. `MissionControlTask` interface in store types, derived from existing `BuildQueueItem` via `buildQueueToTasks()` — no new backend code needed. Toggle button top-right of HXI switches between standard view and Mission Control. Extensible to non-build task types via `type` field (design, diagnostic, assessment).

**Status:** AD-322 complete — 0 new tests (UI only), 2472 pytest + 34 vitest.

### AD-316: TaskTracker Service + AgentTask Data Model

Unified task lifecycle tracking for all agent activity. `TaskTracker` service follows SIF/BuildQueue/BuildDispatcher startup pattern (import → field → start() → stop()). `TaskType` enum (build/design/diagnostic/assessment/query), `StepStatus` enum, `TaskStatus` enum (queued/working/review/done/failed). `TaskStep` dataclass with start/complete/fail lifecycle and timing. `AgentTask` dataclass with full lifecycle methods (start, set_review, complete, fail), step management (add_step, current_step, step_progress), and serialization (to_dict with step_current/step_total). `TaskTracker` class: create_task, start_task, advance_step (auto-completes previous), complete_step, set_review, complete_task (auto-completes lingering step), fail_task (auto-fails lingering step), queries (active_tasks, needs_attention, all_tasks), snapshot for WebSocket broadcast, done-task pruning (max 50). Frontend: `AgentTaskView` + `TaskStepView` TypeScript interfaces, `agentTasks` state, event handlers deriving `MissionControlTask` from task events, state_snapshot hydration.

**Status:** AD-316 complete — 30 new tests, 2502 pytest + 34 vitest.

### AD-380: EmergentDetector Trend Regression

Multi-snapshot trend analysis for the EmergentDetector. Previously only compared current vs previous snapshot (pairwise); now computes linear regression slopes over the ring buffer (default 20-snapshot window). Added `TrendDirection` enum (rising/stable/falling), `MetricTrend` dataclass (slope, r_squared, significance), `TrendReport` (5 metrics: tc_n, routing_entropy, cluster_count, trust_spread, capability_count). Pure Python `_linear_regression()` — no numpy. Significance requires `abs(slope) > threshold AND r_squared > 0.5`. Wired into `analyze()` as `emergence_trends` pattern entries. Replaced `_history` list with `collections.deque(maxlen=...)` for proper ring buffer behavior. Fixed `introspect.py` slice on deque (`list(deque)[-10:]`). Configurable `trend_threshold` (default 0.005).

**Status:** AD-380 complete — 2514 Python + 34 Vitest.

### AD-381: InitiativeEngine — Proactive Remediation

Bridges read-only monitoring (SIF, EmergentDetector, Counselor) to the self-mod pipeline. Background async loop monitors three signal sources: SIF invariant violations, EmergentDetector falling trends (tc_n, capability_count), and Counselor red/yellow alerts. Persistent triggers tracked via `TriggerState` with consecutive counts; proposals generated only after `persistence_threshold` consecutive checks (default 3) — prevents one-off noise from triggering remediation. Trust-gated execution: AUTO actions (diagnose, alert_captain) always run; COMMANDER actions (scale, recycle) require healthy system trust; CAPTAIN actions (patch) always require human approval. `RemediationProposal` dataclass with full serialization, approve/reject lifecycle, 50-proposal cap. Fails-open: each signal source check wrapped in try/except. Wired into runtime with same lifecycle pattern as SIF (import → field → start/stop). Adapted `_emit_event` bridge (runtime takes two args, engine emits single dict).

**Status:** AD-381 complete — 2550 Python + 34 Vitest.

### AD-382: ServiceProfile — Learned External Service Modeling

SQLite-backed `ServiceProfile` replaces hardcoded `_KNOWN_RATE_LIMITS` in HttpFetchAgent. `LatencyStats` with asymmetric EMA for p50/p95/p99 percentiles (memory-efficient, no sample storage). `ServiceProfile` tracks per-domain learned_min_interval, error/rate-limit counters, reliability score. Rate-limit response (429) increases interval by 50% (capped at 60s); successful request after previous 429s decays interval toward seed (×0.9, floor at seed). `ServiceProfileStore` (SQLite, CrewProfile/TrustNetwork pattern) with `get_or_create()`, `save()`, `all_profiles()`, `get_interval()`. Seed intervals preserve existing defaults. HttpFetchAgent reads from store via `set_profile_store()` classmethod. Runtime wires store at startup/shutdown.

**Status:** AD-382 complete — 2531 Python + 34 Vitest.

### AD-383: Strategy Extraction — Dream-Derived Transferable Patterns

New dream pass (step 6) extracting cross-agent transferable patterns from episodic memory. Three pattern detectors: (1) error recovery — same error resolved by 2+ different agent types suggests a transferable technique, (2) high-confidence prompting — intent type with avg confidence >0.8 across 2+ agent types identifies successful approaches, (3) coordination — intent co-occurrence within 60s window across 3+ episodes detects useful sequencing. `StrategyType` enum (ERROR_RECOVERY/PROMPT_TECHNIQUE/COORDINATION/OPTIMIZATION). `StrategyPattern` dataclass with deterministic SHA-256 ID, `reinforce()` for evidence accumulation (confidence = 1 - 1/(count+1)). File named `strategy_extraction.py` to avoid conflict with existing `StrategyRecommender` in `strategy.py`. Wired into `DreamingEngine.dream_cycle()` via `strategy_store_fn` callback. `DreamReport.strategies_extracted` field added. Runtime persists strategies as JSON files under KnowledgeStore.

**Status:** AD-383 complete — 2565 Python + 34 Vitest.

### AD-384: Strategy Application — Cross-Agent Knowledge Transfer

Makes dream-extracted strategies (AD-383) consumable by all CognitiveAgents. `StrategyAdvisor` loads strategies from the knowledge store's `strategies/` directory (JSON files persisted by AD-383 dream extraction), matches by intent type against `source_intent_types` and `applicability`, filters low-confidence (<0.3), boosts with `REL_STRATEGY` Hebbian weight, and returns top 3 sorted by relevance. `format_for_context()` produces concise `[CREW EXPERIENCE]` block injected into the user message before the LLM call — no system prompt modification needed. `record_outcome()` writes back to HebbianRouter so strategy usefulness is learned per agent type. Adapted from build prompt: KnowledgeStore has no `search_by_keywords` method, so advisor loads from filesystem directly with in-memory caching. `REL_STRATEGY` constant added to `routing.py`. `CognitiveAgent` gains `_strategy_advisor` field + `set_strategy_advisor()` setter. Runtime wires advisor onto all CognitiveAgent instances after pool creation.

**Status:** AD-384 complete — 2591 Python + 34 Vitest.

### AD-385: Capability Gap Prediction — Proactive Self-Mod

New dream pass (step 7) analyzing episodic memory for recurring near-misses. Three detection methods: (1) repeated low confidence — intent type with avg confidence below threshold across 5+ episodes suggests a specialization gap, (2) repeated fallback — no intent matched or very low confidence on similar topics 3+ times suggests a missing capability, (3) partial DAG coverage — DAG node fails >50% across 3+ attempts suggests an unreliable subtask handler. `CapabilityGapPrediction` dataclass with descriptive ID, evidence type/summary/count, suggested intent name and description, priority (high if very low confidence or high failure rate). `_extract_topic()` uses stopword filtering for topic extraction from raw text. `_get_field()` handles both dict and object access patterns. Wired into `DreamingEngine.dream_cycle()` via `gap_prediction_fn` callback. `DreamReport.gaps_predicted` field added. Runtime broadcasts predictions to HXI as `capability_gap_predicted` events.

**Status:** AD-385 complete — 2591 Python + 34 Vitest.

### AD-386: Runtime Directive Overlays — Evolvable Chain-of-Command Instructions

*Architecture decision captured. Build prompt: `prompts/runtime-directives.md`.*

Instructions today are static files on disk (`config/standing_orders/*.md`). No agent can issue new directives at runtime. Department chiefs can't instruct subordinates. Lessons learned during operation vanish unless someone manually edits a file.

This AD adds a persistent tier 6 instruction layer: `RuntimeDirective` objects issued through the chain of command. `DirectiveType` enum: captain_order, chief_directive, counselor_guidance, learned_lesson, peer_suggestion. `DirectiveStore` (SQLite-backed, CrewProfile/ServiceProfile pattern). Authorization via `Rank` from CrewProfile: Captain→any agent, Bridge officers→advisory, Department chiefs (COMMANDER+)→subordinates in same department, Self→self (tiered by rank: Ensign needs Captain approval, Lieutenant+ auto-approved), Peers→suggestion (target accepts/rejects). Wired into `compose_instructions()` as tier 6 after personal standing orders — `CognitiveAgent.decide()` picks up directives automatically with zero changes to cognitive_agent.py. Shell commands: `/order <agent> <text>` (Captain issues), `/directives [agent]` (view active). Cache invalidation on directive create/revoke.

**Status:** AD-386 complete — 30 new tests, 2621 Python + 34 Vitest.

### AD-321: Activity Drawer — Real-Time Agent Task Panel

Slide-out panel from the right edge of the HXI giving the Captain real-time visibility into all agent activity. Consumes existing `agentTasks` state from TaskTracker (AD-316) — no new backend code. Three collapsible sections: Needs Attention (amber, action buttons, always expanded), Active (working tasks with step progress bars and `neural-pulse` animation, always expanded), Recent (done/failed, most recent first, capped at 10, collapsed by default). Task cards show department color left border stripe, status dot, type badge (BUILD/DESIGN/etc.), truncated title, agent type, department, elapsed time, AD number. Click to expand: full title, step-by-step checklist with status icons, progress bar, Approve/Reject buttons for review tasks, error text for failed tasks, metadata key-value display. Glass panel styling matching IntentSurface. Toggle button ("ACTIVITY") in header next to MISSION CTRL with attention count badge. Always rendered (transform slide animation for smooth transitions).

**Status:** AD-321 complete — 0 new Python tests (UI only), 34 Vitest passed, tsc clean.

### BF-008: Dream Cycle Double-Replay After Dolphin Dreaming

The micro-dream (Tier 1, every 10s) and full dream (Tier 2, when idle) were both independently replaying episodes through `_replay_episodes()`, causing double-strengthening of Hebbian weights. Observable as `replayed=50 strengthened=80` every 10 minutes even with no new episodes. Fix: compose `dream_cycle()` with `micro_dream()` — Step 0 flushes any un-consolidated episodes via micro_dream, the old Step 1 replay is removed. The micro-dream cursor `_last_consolidated_count` tracks what has been replayed and is only advanced by micro_dream, not reset by the full dream. DreamReport now reflects the micro-dream flush counts (0 when idle, not the redundant 50). Log message updated from `replayed=` to `flushed=`. Maintenance steps (pruning, trust consolidation, pre-warm, strategy extraction, gap prediction) all still run on the full episode window. No caller changes needed — dream_cycle is self-contained and composable. Updated 1 existing test (`test_triggers_after_idle_threshold` assertion), added 5 new BF-008 tests verifying composability, no-double-replay, maintenance execution, flush-based report counts, and cursor integrity.

**Status:** BF-008 closed — 2640 Python tests passed (5 new), 0 failures.

### AD-324: Orb Hover Enhancement — Amber Pulse, Task Tooltip, Department Colors

Enhanced 3D agent orbs with amber pulsing for `requires_action` tasks using performant per-frame Set lookup (built once from `agentTasks`, O(1) per-instance check). Pulse alternates between normal color and amber `(0.94, 0.69, 0.38)` at ~2Hz with increased breathing amplitude. AgentTooltip expanded with current task title (50-char truncate), step label, elapsed time, 4px department-colored progress bar, attention badge, and "View in Activity" click-through. Department label derived from `poolToGroup` with DEPT_COLORS. Moved `activityDrawerOpen` from IntentSurface local useState to Zustand store for cross-component access.

**Status:** AD-324 complete — 4 new Vitest tests, 42 Vitest total, tsc clean.

### AD-387: Unified Bridge — Single Panel HXI Redesign

Replace three separate panels (NOTIF, ACTIVITY, MISSION CTRL) with a single BRIDGE button and unified command panel. Bridge panel (380px right sidebar) has five priority-ordered sections: Attention (merged requires_action tasks + action_required notifications), Active, Notifications, Kanban (compact inline with expand-to-main-viewer), Recent. Empty sections auto-hide. Shared card components extracted into `bridge/` subdirectory. Main viewer becomes adaptive focus surface: `mainViewer: 'canvas' | 'kanban'`. ViewSwitcher appears top-left when non-canvas view active. Design principles: agent-first (not app-first), fluid, dynamic, contextual, immersive, infinite, adaptive. Inspired by NeXTSTEP inspector panels, NASA Mission Control, Star Trek Bridge.

**Status:** AD-387 complete — 4 new Vitest tests, 46 Vitest total, tsc clean.

### AD-388 through AD-392: HXI Glass Bridge — Progressive Enhancement

Frosted glass task surface layered over the existing orb mesh. Three depth layers: Backdrop (3D mesh), Glass (tasks/collaboration), Controls (Bridge panel + chat). Five progressive phases: (1) Glass overlay with center task cards and multi-task constellation, (2) DAG visualization with spatial sub-task nodes, (3) Ambient intelligence with three bridge states and color temperature, (4) Cyberpunk atmosphere with opt-in effects, (5) Adaptive bridge with trust-driven progressive reveal and Captain's Gaze. The mesh is never replaced — every phase preserves and enhances existing HXI. Agent-first design: glass surfaces attention items, not apps. Full design spec: `docs/design/hxi-glass-bridge.md`.

**Status:** AD-392 complete (Phase 5) — All 5 Glass Bridge phases done. 16 new Vitest tests, 99 Vitest total, tsc clean.

### AD-393: Personality Activation — Big Five Traits Wired into Agent Behavior

Agent personality profiles (Big Five traits, callsigns, roles) existed in crew_profiles/ YAML but were never injected into the LLM system prompt. AD-393 adds `_build_personality_block()` to `compose_instructions()` as Tier 1.5 (between hardcoded identity and Federation Constitution). High traits (>=0.7) produce "high" behavioral guidance, low traits (<=0.3) produce "low" guidance, neutral traits are silent. Identity line includes callsign, display_name, role, department. Cached via `@lru_cache`. Horizontal concern — activates personality for all 12 existing agents simultaneously.

**Status:** AD-393 complete — 10 new Python tests, 2673 pytest + 99 vitest = 2772 total.

### AD-394: ScoutAgent — Daily GitHub Intelligence Gathering

Science department officer (callsign Wesley) that searches GitHub REST API for recent AI agent repositories, classifies each as absorb/visiting_officer/skip via LLM with structured ===SCOUT_REPORT=== output format, filters by relevance (>=3), stores daily JSON reports, delivers formatted markdown digest to Discord (via scout_channel_id config), and posts Bridge notifications for high-relevance (>=4) findings. /scout command for on-demand scan, /scout report for latest. TaskScheduler daily interval (24h). Seen repos tracked in data/scout_seen.json with 90-day pruning. Crew profile: openness 0.9, conscientiousness 0.7, neuroticism 0.2.

**Status:** AD-394 complete — 10 new Python tests, 2683 pytest + 99 vitest = 2782 total.

### AD-395: CredentialStore + Scout gh CLI Enhancement

CredentialStore — Ship's Computer centralized credential resolution service. Resolution chain: config key (dot-path traversal) → env var → env var aliases → CLI command → None. Cached with 5-min TTL, audit-logged to event_log, department-scoped access (future-ready). Built-in specs for github, discord, llm_api. Extensions can register custom credentials via `register()`. /credentials command for Captain visibility (names + available/unavailable, never values). Scout migrated from httpx to `gh api` subprocess for authenticated 5000 req/hr rate limits. Multi-dimensional source curation absorbed from GPT Researcher: credibility (1-5) and reliability (1-5) scoring alongside relevance, with weighted composite_score (50% relevance, 25% credibility, 25% reliability). Filtering and Bridge notifications use composite_score instead of raw relevance.

**Status:** AD-395 complete — 19 new Python tests (13 credential store + 6 scout), 2702 pytest + 99 vitest = 2801 total.

### AD-396: Quality Hardening — Subprocess Encoding, Path Safety, Integration Tests

Dogfooding ScoutAgent on Windows exposed 9 integration bugs that unit tests with mocks couldn't catch. Systemic fixes: (1) 7 subprocess.run calls using `text=True` (Windows cp1252 default) replaced with `encoding="utf-8", errors="replace"` across credential_store.py, knowledge/store.py, dependency_resolver.py (3×), __main__.py (2×). (2) Scout's hardcoded `_DATA_DIR` from `__file__` replaced with runtime-resolved properties. (3) Personality trait type guard (`isinstance` check) in standing_orders.py. (4) New integration test file for encoding, paths, types, and shell↔agent boundary patterns.

**Status:** AD-396 complete — 13 new Python tests (net +2 after scout test consolidation), 2704 pytest + 99 vitest = 2803 total.

### AD-397: Callsign Addressing — `@callsign` Targeted Dispatch & 1:1 Crew Sessions

| AD | Decision |
|----|----------|
| AD-397 | Callsign Addressing — agents addressed by name, not ID. (a) `CallsignRegistry` in crew_profile.py — `load_from_profiles()` scans YAML seeds, `bind_registry()` wires live `AgentRegistry`, `resolve()` returns `(agent_type, agent_id)`, case-insensitive lookup. Ship's Computer service initialized at runtime startup. (b) `BaseAgent.callsign` attribute set by `_wire_agent()`. (c) Shell `@callsign` routing — third path in `execute_command()` after `@` prefix detection, opens 1:1 session mode. (d) 1:1 Session Mode — `_session_callsign`, `_session_agent_id`, `_session_history` state fields. Subsequent messages route directly to the session agent (bypasses Decomposer). `/bridge` exits session. Agent responds as themselves with personality and standing orders. (e) Session Memory — within-session `_session_history` list passed as context to `decide()`. Cross-session via `EpisodicMemory.store()` on each exchange. `recall_for_agent()` sovereign scoped retrieval seeds new sessions with prior conversation context. (f) `IntentMessage.target_agent_id` field + `IntentBus.send()` for targeted dispatch (bypasses subscriber broadcast). `broadcast()` delegates to `send()` when target set. (g) `CognitiveAgent.handle_intent()` accepts `direct_message` intent when targeted. Enhanced `_build_user_message()` for conversational 1:1 context. (h) Channel adapter `@callsign` routing in `BaseChannelAdapter.handle_message()`. (i) Agent roster display includes callsigns. Sovereign Agent Identity principle: Character/Reason/Duty — each agent's episodic memory is their own shard, shared only through communication. |

**Status:** AD-397 complete — 27 new Python tests (10 registry + 5 dispatch + 12 session), 2731 pytest + 99 vitest = 2830 total.
