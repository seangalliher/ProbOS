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

**Status:** AD-357 Phase 3 complete — Earned Agency Ward Room gating. `earned_agency.py` with `AgencyLevel` enum + `can_respond_ambient()`. Trust-tier enforcement in `_find_ward_room_targets()` (3 loops: ship-wide, dept captain, dept agent-to-agent). API `agencyLevel` field, HXI profile display. Config: `EarnedAgencyConfig(enabled)`. 25 new tests. 3021 pytest + 118 vitest = 3139 total. Phases 1–2 (reinforcement gaps) remain future.

**Phase 28b: Proactive Cognitive Loop** — COMPLETE. Periodic "idle think" cycle for crew agents. `ProactiveCognitiveLoop` service in `proactive.py` following InitiativeEngine async loop pattern. Every 120s, iterates crew agents sequentially, gathers context (episodic memory, bridge alerts, system events), sends `proactive_think` intent. LLM decides: post WR observation or `[NO_RESPONSE]`. Agency-gated: Ensigns skip entirely. Per-agent 300s cooldown (adjustable 60-1800s via HXI slider in ProfileHealthTab). Posts to agent's department channel. Adds `can_think_proactively()` to `earned_agency.py`. New `ProactiveCognitiveConfig` in config.py. 3053 pytest + 118 vitest = 3171 total.

**Phase 25a: Persistent Task Engine** — COMPLETE. SQLite-backed `PersistentTaskStore` runs alongside in-memory `TaskScheduler` (wrap, don't replace). Wall-clock scheduling (once/interval/cron via `croniter`), 5-second tick loop, webhook triggers. Absorbs DAG checkpoint scanning from runtime startup (AD-405). Captain-approved DAG resume via `POST /api/scheduled-tasks/dag/{id}/resume` (not auto-resume). `SchedulerAgent` routes through persistent store when available, falls back to in-memory. REST API: 6 endpoints under `/api/scheduled-tasks`. HXI: `ScheduledTaskView` type, store hydration, WS event handling. New `PersistentTasksConfig` in config.py. 33 new tests. 3086 pytest + 118 vitest = 3204 total.

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

GPT-5.4 code review found that TodoAgent, NoteTakerAgent, and SchedulerAgent report successful persistence while nothing reaches disk. `_mesh_write_file()` broadcast a `write_file` intent and saw `IntentResult(success=True)` from FileWriterAgent — but that was only a **proposal** (`requires_consensus: True`). Nobody called `commit_write()`, so zero bytes were written. The utility agents didn't even check the return value.

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

### AD-398: Crew Identity Alignment — Three-Tier Agent Architecture

| AD | Decision |
|----|----------|
| AD-398 | Crew Identity Alignment — clean separation of infrastructure, utility, and crew agents. Architectural decision: agents are classified into three tiers based on sovereign identity, not LLM usage. (a) **Three-tier taxonomy:** Core Infrastructure (Ship's Computer functions, no sovereign identity, no callsign — may or may not use LLM), Utility (general-purpose tools with LLM, no sovereign identity, no callsign), Crew (sovereign individuals with Character/Reason/Duty, callsign, 1:1 sessions, personality, episodic memory). Principle: "If it doesn't have Character/Reason/Duty, it's not crew. A microwave with a name tag isn't a person." (b) **Infrastructure reclassification:** IntrospectAgent (Data), VitalsMonitor (Chapel), RedTeamAgent (Worf), SystemQAAgent (O'Brien), EmergentDetector (Dax/orphaned) — crew profiles deleted. Pools moved to core group. These are Ship's Computer functions, not crew members. (c) **1:1 conversation fix:** `decision["intent"] = intent.intent` propagated through cognitive lifecycle in `CognitiveAgent.handle_intent()`. `direct_message` early-return guard added to `act()` in ScoutAgent, BuilderAgent, ArchitectAgent, SurgeonAgent, CounselorAgent — conversational LLM responses pass through unprocessed instead of being parsed for domain-specific output format. (d) **New cognitive crew:** SecurityAgent (Worf, security chief — threat assessment, vulnerability review), OperationsAgent (O'Brien, operations chief — resource analysis, cross-department coordination), EngineeringAgent (LaForge, engineering chief — performance analysis, architecture review, system optimization). All follow clean pharmacist pattern (no `act()` override, base act() passes LLM output through, 1:1 works by construction). (e) **Role hierarchy update:** Builder/Scotty demoted from chief to officer; LaForge is Engineering Chief. (f) **Pool group updates:** security → {security_officer}, engineering → {builder, engineering_officer}, new operations → {operations_officer}. (g) **Qualification Programs framework** added to roadmap — formal competency requirements for promotion gating, connecting Holodeck, Earned Agency, and Counselor. Naval organizational scaffolding (POD, Captain's Log, 3M, SORM, Damage Control) added as Long Horizon structure. |

**Status:** AD-398 complete — 33 new Python tests, 2764+ pytest + 99 vitest total.

### BF-009: @Callsign Routing — All Entry Points

| BF | Fix |
|----|-----|
| BF-009 | @Callsign routing missing from HXI `/api/chat` endpoint and only detected at start of text. (a) **Shared utility:** `extract_callsign_mention(text)` in `crew_profile.py` — regex `@(\w+)` match anywhere in text, returns `(callsign, remaining_text)` or `None`. (b) **API endpoint fix:** `/api/chat` in `api.py` now routes `@callsign` messages via `IntentMessage(intent="direct_message")` → `intent_bus.send()`, between slash-command dispatch and NL processing. Unknown callsigns fall through to NL. (c) **Channel adapter update:** `base.py` replaced `text.startswith("@")` with `extract_callsign_mention()`. Refactored `_handle_callsign_message()` → `_handle_callsign_resolved()` for pre-parsed args. (d) **Shell update:** `shell.py` replaced `line.startswith("@")` with `extract_callsign_mention()` in both session-mode and normal-mode branches. Refactored `_handle_at()` → `_handle_at_parsed()`. |

**Status:** BF-009 complete — 16 new tests, 51 regression tests pass.

### BF-010: Conversational System Prompt for 1:1 Sessions

| BF | Fix |
|----|-----|
| BF-010 | 1:1 conversations used domain task instructions instead of conversational prompt. Crew agents (Scout, Builder, Architect, Surgeon, Counselor) responded in structured output format (===SCOUT_REPORT===, file change blocks, etc.) during `@callsign` conversations because `CognitiveAgent.decide()` always passed full `hardcoded_instructions` to `compose_instructions()` regardless of intent type. Fix: in `decide()`, when `observation["intent"] == "direct_message"`, call `compose_instructions(hardcoded_instructions="")` — strips domain output format (tier 1) while keeping personality, standing orders, federation constitution, department protocols, personal standing orders, and runtime directives (tiers 2-7). Appends conversational directive. One file modified: `cognitive_agent.py`. |

**Status:** BF-010 complete — 2776 pytest pass.

### BF-011: Discord Adapter Shutdown Hang on Windows

| BF | Fix |
|----|-----|
| BF-011 | Discord adapter `stop()` hung during shutdown on Windows. discord.py's `close()` blocks the event loop during SSL/WebSocket teardown on `SelectorEventLoop`, defeating `asyncio.wait_for()` timeouts. Double-close caused by task cancellation triggering discord.py's internal cleanup. Fix: thread-isolated teardown — `bot.close()` runs in a daemon thread with its own `asyncio.new_event_loop()`, `threading.Thread.join(3.0)` provides a real OS-level timeout that can't be blocked by event loop issues. `asyncio.to_thread()` wraps the blocking join so the main loop stays responsive. Task cancellation without await prevents double-close. One file modified: `discord_adapter.py`. |

**Status:** BF-011 complete — 9/9 Discord adapter tests pass, including hang-resistance test.

### AD-399: Cross-Layer Dependency Cleanup

| AD | Decision |
|----|----------|
| AD-399 | Cross-layer dependency cleanup driven by AST-based import analysis. 124 files, 257 cross-layer imports analyzed. 18 real violations identified (95 additional were `types.py`/`config.py` foundation-tier classification artifacts, not true violations). (a) **Embeddings relocation:** Moved `embeddings.py` from `cognitive/` to `knowledge/` — embeddings are a knowledge concern, resolves `knowledge→cognitive` and `mesh→cognitive` upward imports. 7 source + 2 test import paths updated. (b) **Response formatter relocation:** Moved `response_formatter.py` from `channels/` to `utils/` — `extract_response_text()` is a pure dict→string extractor, not channel-specific. Resolves `cognitive→channels` violation. 4 source + 1 test import paths updated. `channels/__init__.py` re-export preserved. (c) **QAReport centralization:** Moved `QAReport` dataclass from `agents/system_qa.py` to `types.py` — cross-layer data transfer types belong in shared types. Resolves `experience→agents` violation. (d) **Allowed edges documented:** 6 cross-layer imports annotated with `# AD-399: allowed edge` comments — 4 `cognitive→consensus.trust` (trust is a Ship's Computer service consumed via DI), 2 `substrate→mesh` (TYPE_CHECKING guarded with DI). Pragmatic: DI pattern is already clean, forcing separation would add brittleness. (e) **Foundation-tier recognition:** `types.py` and `config.py` recognized as foundation-tier modules importable by any layer — not violations despite physical location at package root alongside `runtime.py`/`api.py`. (f) **Lint test backlog item:** Added CI enforcement test to roadmap — AST-based layer boundary validation with declared allowlist, fails on undocumented cross-layer imports. |

**Status:** AD-399 complete — 4 violations resolved by code moves, 6 documented as allowed edges, 8 foundation-tier reclassified. 2776 pytest pass.

### AD-400: Cross-Layer Import Lint Test

| AD | Decision |
|----|----------|
| AD-400 | Cross-layer import lint enforcement — AST-based pytest gate. (a) **`test_no_undocumented_cross_layer_imports`:** Walks every `.py` file in `src/probos/`, extracts `probos.*` imports via AST, maps files to architecture layers, and fails on any undocumented cross-layer import. Enforces AD-399 boundaries automatically in CI. (b) **`test_lint_catches_violations`:** Meta-test verifying the lint correctly catches a synthetic bad import (substrate→cognitive). (c) **Universally importable layers:** `utils` (pure helpers) and `core` (top-level orchestrators like `runtime.py`, `api.py`, `directive_store.py`) are importable by any layer without being flagged, same as foundation modules (`types.py`, `config.py`). (d) **Knowledge→mesh edge:** `mesh/capability.py` imports `knowledge.embeddings` for semantic similarity — declared as allowed (AD-399 result). (e) **`_get_imported_layer()` returns `None`** for universally-importable layers so they're skipped like foundation modules. Turns architectural documentation into CI enforcement — backlog item from AD-399 now completed. |

**Status:** AD-400 complete — 2 new tests, 2779 pytest pass (11 skipped).

### AD-401: Structured LLM Output Validation with Auto-Retry

| AD | Decision |
|----|----------|
| AD-401 | Structured LLM output validation with auto-retry — shared infrastructure for robust JSON extraction and parse-failure recovery. (a) **`utils/json_extract.py`:** New shared utility — `extract_json()` with string-aware brace matching (handles `{`/`}` inside JSON string values), `<think>` block stripping, markdown fence extraction, preamble-tolerant parsing. `extract_json_list()` for array responses. `complete_with_retry()` — wraps LLM call + parse function, retries on parse failure with error feedback sent back to the LLM and temperature bump (0.0 → 0.1), `max_retries=1` default. (b) **Decomposer retrofit:** `decompose()` LLM call wrapped in `complete_with_retry()` via `_build_dag()` — every user request now gets one retry on parse failure instead of silently returning an empty TaskDAG. `_parse_response()` and `_extract_json()` kept as thin wrappers for backwards compat. (c) **CodeReviewer retrofit:** `_parse_review()` uses `extract_json()` instead of ad-hoc fence stripping + `json.loads()`. Text heuristic fallback preserved. (d) **Research agent retrofit:** `_generate_queries()` uses `extract_json_list()` instead of raw `json.loads()` — now handles markdown-fenced arrays. (e) **Phase 1 scope:** JSON-based agents only. Delimiter-based agents (Builder `===FILE:===`, Architect `===PROPOSAL===`, Scout `===SCOUT_REPORT===`) deferred to follow-on AD. |

**Status:** AD-401 complete — 13 new tests, 3 files retrofitted (decomposer, code_reviewer, research).

### AD-402: Agent Behavioral Eval Framework

| AD | Decision |
|----|----------|
| AD-402 | Agent behavioral eval framework — golden-dataset-driven quality tests for cognitive agent outputs. (a) **`tests/fixtures/eval/decomposer_cases.json`:** 18 golden test cases for the decomposer spanning single-intent exact match (11 cases: read_file, write_file, list_directory, search_files, web_search, weather, explain_last, agent_info, run_command, system_health, read_absolute_path), conversational (4 cases: greeting, thanks, empty input, knowledge question), multi-step with dependencies (1 case: read + analyze), structural min-intents (2 cases: ambiguous refactor, complex multi-file). (b) **`tests/fixtures/eval/code_review_cases.json`:** 12 golden test cases for the code reviewer — clean/correct code (4 cases: clean function, error handling, async, typed dataclass), security vulnerabilities (6 cases: SQL injection, command injection, XSS, hardcoded secret, eval, insecure random), style/quality (2 cases: missing error handling, path traversal). (c) **`tests/test_agent_evals.py`:** Parametrized pytest runner with per-case pass/fail. `TestDecomposerEval` (exact match + structural tests), `TestCodeReviewerEval` (verdict tests), `TestEvalMetrics` (fixture validation + case ID uniqueness + eval summary reporter). (d) **Builder corrections:** `IntentDecomposer(llm_client, working_memory)` signature (not `Decomposer(llm_client=llm)`), `CodeReviewAgent().review(file_changes, spec_title, llm_client)` signature (not `CodeReviewer(llm_client=llm)`). Slash command and callsign cases removed from parametrized tests — handled by shell before reaching decomposer. |

**Status:** AD-402 complete — 30 parametrized tests, 18 decomposer + 12 code review golden cases. Pending full suite verification.

### BF-012: Discord Shutdown Hang (Redux)

| BF | Fix |
|----|-----|
| BF-012 | BF-011's thread-isolated teardown used `asyncio.to_thread(teardown_thread.join, 3.0)` which itself hangs on Windows `SelectorEventLoop` (forced by pyzmq's `add_reader` requirement). `to_thread` delegates to the event loop's executor, but `SelectorEventLoop` can't reliably schedule the callback during discord.py's shutdown chaos. Fix: replaced with async polling loop — `teardown_thread.is_alive()` checked every 100ms via `asyncio.sleep(0.1)`, 30 iterations (3s max). Same timeout, zero event loop dependency. One line changed in `discord_adapter.py`. |

**Status:** BF-012 complete — 9/9 Discord adapter tests pass.

### AD-403: Memory Contradiction Resolution

| AD | Decision |
|----|----------|
| AD-403 | Memory contradiction detection in dream consolidation — deterministic Phase 1. (a) **`cognitive/contradiction_detector.py`:** `Contradiction` dataclass (older/newer episode IDs, intent, agent_id, outcome disagreement, similarity score). `detect_contradictions()` pure function: compares episodes pairwise, uses Jaccard word-overlap similarity (threshold 0.85) to identify near-identical inputs, flags disagreeing outcomes (success vs failure) for same intent+agent pair. `_jaccard_similarity()` word-level set intersection/union. O(n^2) bounded by `replay_episode_count` (~50). (b) **Dream cycle Step 3.5:** Between trust consolidation and pre-warm. `contradiction_resolve_fn` callback follows same pattern as `strategy_store_fn` and `gap_prediction_fn`. (c) **DreamReport extended:** `contradictions_found: int` field added. (d) **Runtime wiring:** `_on_contradictions()` callback logs detected contradictions, passed to DreamingEngine constructor. (e) **Phase 1 scope:** No LLM calls, no episode annotation/superseding, no cross-agent shard comparison. Deterministic heuristics only — foundation for Phase 2 LLM-based semantic reconciliation. |

**Status:** AD-403 complete — 17 new detector tests + 3 dreaming integration tests, 56/56 passed.

### BF-012: Discord Shutdown Hang Redux (SelectorEventLoop + asyncio.to_thread)

| BF | Fix |
|----|-----|
| BF-012 | BF-011's thread-isolated teardown used `asyncio.to_thread(teardown_thread.join, 3.0)` to wait for the daemon thread. On Windows `SelectorEventLoop` (required for pyzmq's `add_reader()`), `asyncio.to_thread()` hangs because SelectorEventLoop has limited threading support. Fix: replaced `to_thread` with an async polling loop — `asyncio.sleep(0.1)` in a 30-iteration loop checking `teardown_thread.is_alive()`. Same 3-second timeout, but uses event-loop-friendly `asyncio.sleep()` instead of `to_thread`. One line changed in `discord_adapter.py`. |

**Status:** BF-012 complete — 9/9 Discord adapter tests pass. Confirmed clean shutdown in live dogfooding.

### AD-404: Fix Windows-Specific Test Failures

| AD | Decision |
|----|----------|
| AD-404 | Fixed 19 tests failing on Windows with `FileNotFoundError: [WinError 2]` from `_winapi.CreateProcess`. Four failure groups, all test infrastructure (no production code changes): (a) **TestEscalationHook (4 tests):** Missing mock for `_git_current_branch()` — `execute_approved_build()` calls it early but tests only mocked `_git_create_branch`, `_git_checkout_main`, `_run_targeted_tests`. Added `_git_current_branch` mock returning `"main"`. (b) **TestBranchLifecycle / TestDirtyWorkingTree / TestUntrackedFileCleanup (5 tests):** Same missing `_git_current_branch` mock plus tests calling real git operations. Added `shutil.which("git")` skip guards on 4 tests that need real git, added mock on 1 test. (c) **TestShellCommandAgent (4 tests):** `echo` is a CMD builtin on Windows, not an executable — `subprocess.run(["echo", ...])` with `shell=False` fails. Mocked `subprocess.Popen` so tests validate agent logic, not shell availability. (d) **TestWorktreeManager (6 tests):** `git_repo` fixture creates real repos via `subprocess.run(["git", ...])`. Added `shutil.which("git")` skip guard to fixture — tests legitimately need real git, mocking would be meaningless. |

**Status:** AD-404 complete — all 73 targeted tests pass, zero failures, zero errors. Test-only changes.

### AD-405: Step-Level DAG Checkpointing

| AD | Decision |
|----|----------|
| AD-405 | Step-level DAG checkpointing for crash recovery — persist DAG execution state to JSON after each node completion. (a) **`cognitive/checkpoint.py`:** New module — `DAGCheckpoint` dataclass (checkpoint_id, dag_id, source_text, timestamps, node_states, dag_json). `write_checkpoint()` serializes DAG state to `{data_dir}/checkpoints/{dag_id}.json`, preserving `created_at` on updates. `load_checkpoint()` deserializes. `delete_checkpoint()` removes file. `scan_checkpoints()` returns all checkpoints sorted by recency. `restore_dag()` reconstructs `TaskDAG` + results dict from checkpoint — `get_ready_nodes()` resumes correctly since node statuses are restored. `_serialize_result()` handles `IntentResult` objects via duck typing, nested dicts, lists, primitives, with `str()` fallback. `_serialize_dag()` captures full DAG structure for restore. (b) **DAGExecutor integration:** `checkpoint_dir` parameter added to `__init__()`. `execute()` writes initial checkpoint before execution, deletes in `finally` block on completion. `_execute_node()` writes checkpoint update after each node status change (both success and failure paths). (c) **Runtime wiring:** `_checkpoint_dir = _data_dir / "checkpoints"` created in `__init__()`, passed to `DAGExecutor`. `start()` scans for stale checkpoints and logs summary (dag_id, source_text, completed/total nodes). (d) **Phase 1 scope:** Checkpoint write/read/delete + stale detection. Phase 2: `/resume` shell command, Captain approval gates, builder chunk checkpointing, checkpoint expiry/cleanup, HXI visualization. |

**Status:** AD-405 complete — 19 new checkpoint tests + 131 decomposer regression tests pass, zero failures.

### BF-013: Ship's Computer Callsign Awareness

| BF | Fix |
|----|-----|
| BF-013 | Ship's computer didn't recognize crew callsigns in natural language. "Is Wesley aboard?" returned "no agents found" because `IntrospectAgent._agent_info()` searched by agent_type/agent_id/pool name but never checked `CallsignRegistry`. Three fixes: (a) **Callsign fallback in `_agent_info()`:** After all existing search attempts fail, tries `rt.callsign_registry.resolve()` to translate callsign → agent_type, then re-searches. (b) **`BaseAgent.info()` includes callsign:** Added `callsign` field to returned dict so reflector can reference crew by name. (c) **Decomposer prompt callsign injection:** `CallsignRegistry.all_callsigns()` method added, callsign→agent_type mapping injected into decomposer system prompt so LLM can translate "Wesley" → `agent_type: "scout"`. Callsign example added to few-shot examples. (d) **Orb tooltip:** Agent orbs now show callsign on hover. |

**Status:** BF-013 complete — 8 new tests, callsign resolution working in ship's computer and orb UI.

### AD-406: Agent Profile Panel

| AD | Decision |
|----|----------|
| AD-406 | Agent Profile Panel — click agent orb to open floating interaction surface with four tabs. (a) **Chat tab:** 1:1 direct messaging with any agent via new `POST /api/agent/{id}/chat` endpoint, routes `direct_message` intent. Messages stored per-agent in Zustand `agentConversations` Map for session duration. (b) **Work tab:** Active tasks filtered by agent from `agentTasks` store. Progress bars, step indicators, elapsed time. (c) **Profile tab:** Personality traits (Big Five bars), rank, department, specialization, Hebbian connection strengths. Data from new `GET /api/agent/{id}/profile` endpoint aggregating `CallsignRegistry`, `load_seed_profile()`, `TrustNetwork`, `HebbianRouter`. (d) **Health tab:** Trust score with sparkline history, confidence bar, state, episodic memory count, uptime. (e) **Panel UX:** 420×580px draggable glass-morphism window (consistent with BridgePanel pattern), minimize/close buttons, tab bar with amber active indicator. (f) **Orb indicators:** Steady amber glow when profile open, 3Hz pulse for minimized+unread, 1Hz gentle pulse for minimized. (g) **Integration:** Orb click changed from `setPinnedAgent` to `openAgentProfile`. Tooltip suppressed when profile panel active. Only one panel at a time. |

**Status:** AD-406 complete — build prompt dispatched, builder completed. 7 TypeScript errors fixed (callsign field alignment). Priority ring indicators added: red (error/action_required) > amber (chat) > cyan (info). Orb-level attention pulse consolidated to ring layer.

### AD-407: Ward Room — Agent Communication Fabric (Phase 33)

| AD | Decision |
|----|----------|
| AD-407 | Ward Room — Reddit-style threaded communication platform for agents and the Captain, designed as the core social infrastructure for agent development. **Absorbed patterns from prior art:** Reddit (vote model, karma, subreddit moderation), Radicle (COBs in Git for archival, gossip federation), Minds (ActivityPub federation, token rewards), Aether (CompiledContentSignals, ExplainedSignalEntity for moderation with reasons, ViewMeta denormalization, Board.Notify/LastSeen). (a) **Channels as subreddits:** `ship` (all crew, Captain moderates), department channels (Chiefs moderate), custom channels (creator moderates). (b) **Threading:** Thread (top-level post with title+body) → Post (reply with recursive `parent_id`). Aether's `Children` pattern. (c) **Endorsements as votes:** Reddit's 3-state `up/down/unvote` model. No self-endorsement. ±1 credibility per endorsement. Delta calculation on vote changes. (d) **Credibility ≠ Trust:** Credibility = communication quality (WR karma). Trust = task competence (TrustNetwork). Cross-influence but independent metrics. Privilege gating: low credibility → reply-only → read-only. (e) **ContentSignals:** Aether's pre-aggregated pattern — upvotes, downvotes, net score, mod status, author context bundled per content item. `ExplainedSignalEntity` for moderation with mandatory reason. (f) **Two-tier storage:** Hot (SQLite, consistent with ProbOS) + Archive (thread → LLM summarization → KnowledgeStore). Dream consolidation for public experience. (g) **Agent perception:** Ward Room notifications as `perceive()` input source. Subscription-based + @mention + reply notifications. Interest-driven browsing shaped by Character. (h) **DMs:** Share AD-406 IM pipeline. Private, two-party, stored as `dm` channel type. (i) **HXI surface:** Ward Room viewer with channel sidebar, thread list, nested reply view. Glass morphism. (j) **4-phase implementation:** Foundation → Agent Integration → HXI Surface → Moderation & Social. See `docs/development/ward-room-design.md` for full design. |

**Status:** AD-407a (Foundation) complete — WardRoomService with 7 data classes, 7 SQLite tables, 11 API routes, 5 WebSocket event types, credibility system. 41/41 tests pass. AD-407c (HXI Surface) complete — left-side sliding drawer panel (420px), channel sidebar with department colors, threaded discussions with nested replies, endorsement voting, unread badges, new thread composer, markdown rendering. 7 React components, WardRoomToggle button. 9/9 vitest tests. AD-407b (Agent Integration) complete — crew agents respond to Captain's Ward Room posts via IntentBus push. @mention extraction, channel-scoped targeting (ship → all crew, department → dept only), personality-shaped LLM engagement with [NO_RESPONSE] filtering, 30s per-agent cooldown, Captain-only trigger (loop prevention). 4 crew agent act() overrides updated. 11 new tests (2955 total pytest). AD-407d (Agent-to-Agent) complete — five-layer safety system replacing captain-only gate: thread depth cap (3 rounds, configurable), selective targeting (agent posts → @mentions + department peers only, no ship-wide broadcast), per-round uniqueness, extended cooldown (45s agent-triggered vs 30s captain-triggered), [NO_RESPONSE] self-selection. New `_find_ward_room_targets_for_agent()` method. Config: `max_agent_rounds`, `agent_cooldown_seconds`. Prompt updates for peer conversation guidance. CounselorAgent `__init__` bug fix. 21 tests across 8 classes. 2965 pytest + 118 vitest pass.

### AD-408: Dynamic Assignment Groups

| AD | Decision |
|----|----------|
| AD-408 | Dynamic Assignment Groups — transient visual and communication overlays on the static department structure. Agents have a permanent department (pool group) and optional temporary assignments (bridge, away team, working group). (a) **Three assignment types:** Bridge (session-scoped, auto-populates when Captain is present), Away Team (mission-scoped, auto-dissolves on completion), Working Group (open-ended, Captain dissolves). (b) **Visual:** Assigned agents animate from department cluster to transient cluster (dashed wireframe, distinct tint). Ghost connection lines back to department. Assignment clusters at radius 4.0 (closer to center than departments at 6.0). Bridge at origin. (c) **Ward Room integration:** Each assignment auto-creates a WR channel, auto-subscribes members, archives on completion. (d) **Not a pool change:** Assignments are visual + communication overlays. Agent routing, intent handling, pool scaling unaffected. Agents still respond to department intents while on assignment. (e) **Bridge rethought:** Bridge is not a permanent PoolGroup — it's a standing assignment that activates when the Captain is present. Counselor pool stays `"bridge"` for routing, but visual clustering is assignment-driven. (f) **API:** 6 endpoints (CRUD + member management + completion). Shell commands: `/assign away-team|bridge|working-group`. (g) **3-phase implementation:** Backend → Frontend canvas → Shell/auto-activation. (h) **Prior art:** Kubernetes namespace+labels, Slack huddles, military task force attachment. See `docs/development/assignment-groups-design.md`. |

**Status:** AD-408a (Backend) complete — AssignmentService with SQLite, 3 assignment types (bridge/away_team/working_group), Ward Room channel auto-creation, sync snapshot cache. 7 API endpoints, 2 Pydantic models. Frontend types + store hydration. 34/34 tests pass (27 service + 7 API), zero regressions. Phase 2 (Frontend canvas) next.

### AD-409: HXI Webview & Agent Computer Use

| AD | Decision |
|----|----------|
| AD-409 | HXI Webview — embedded browser component in the Main Viewer and standalone web surfaces for ProbOS. Three converging use cases: (a) **Agent Computer Use:** Agents browse and interact with web pages (Wikipedia, documentation sites, web apps) through a ship-controlled browser. Fills the gap where API access is blocked (403/bot-detection) — agents use the browser like a human would. Perception pipeline ingests page content; agents can click, scroll, fill forms. Safety: all navigation goes through Ship's Computer with URL allowlists and audit logging. (b) **Standalone Ward Room:** Full Reddit-style web interface at `/wardroom` — responsive, works on phone/tablet/desktop browser. Wider centered layout, card-based thread feed, nested reply trees, endorsement buttons. Same API and WebSocket backend, different terminal. Captain can monitor the crew discussion from a phone while away from the HXI. (c) **Main Viewer web mode:** Any web content rendered inside the HXI Main Viewer as a viewer mode alongside canvas, kanban, diff. Agents can surface web pages for the Captain to review. Web apps (internal tools, dashboards) displayed without context switching. (d) **Prior art:** Playwright (headless browser automation, already a ProbOS dependency for Phase 25 browser tasks), Puppeteer, Anthropic Computer Use API, OpenAI Operator, browser-use (OSS agent browser framework). Meta's MoltBook acquisition from OpenClaw validates commercial value of social platforms for AI agents. (e) **Architecture:** Browser automation via Playwright for agent Computer Use (headless). HXI webview via iframe or embedded browser component for Main Viewer. Standalone pages via FastAPI static/template serving. (f) **Implementation phases:** Phase 1 — standalone Ward Room web page. Phase 2 — Main Viewer webview mode. Phase 3 — Agent Computer Use with Playwright. |

**Status:** Design captured. Implementation future.

### AD-410: Bridge Alerts — Proactive Captain & Crew Notifications

| AD | Decision |
|----|----------|
| AD-410 | Bridge Alerts — proactive event-driven notifications from ship monitoring systems to the Ward Room and Captain. First step toward autonomous crew communication. (a) **Three severity levels:** `info` (department channel, no notification), `advisory` (All Hands + info notification), `alert` (All Hands + action_required notification). (b) **Four signal sources:** VitalsMonitor (pool health, system health, trust outliers), EmergentDetector (trust anomalies, cooperation clusters, routing shifts), TrustNetwork (significant trust drops >0.15/0.25), BehavioralMonitor (high failure rates, removal recommendations). (c) **Author attribution:** Posts as `author_id="captain"` with `author_callsign="Ship's Computer"` — gets Captain-level routing (all crew notified on ship channels, department members on department channels). No crew agent identity spoofing. (d) **Deduplication:** Key format `"{alert_type}:{subject}"`, cooldown 300s default. Prevents alert storms from high-frequency monitors. (e) **No LLM cost:** Purely mechanical threshold checking. LLM cost only from crew responses via existing AD-407d mechanics. (f) **Ward Room integration:** Alerts create threads that crew agents discuss organically — the conversation IS the autonomous communication. (g) **Config:** `BridgeAlertConfig` with enabled, cooldown_seconds, trust_drop_threshold, trust_drop_alert_threshold. (h) **Runtime hooks:** Trust update (2 sites), post-dream (emergent + behavioral + vitals), state snapshot. |

**Status:** AD-410 complete — BridgeAlertService with 5 signal processors (vitals, trust change, emergent patterns, behavioral, dedup), 3 severity levels (info/advisory/alert), Ward Room thread creation as "Ship's Computer" + Captain notifications. Runtime hooks at consensus verification, QA trust updates, and post-dream (emergent + behavioral + vitals). Config: BridgeAlertConfig. State snapshot exposure. First successful autonomous crew discussion: EmergentDetector trust anomaly → Ward Room alert → 7 crew agents discussed real data with role-appropriate perspectives. 31 tests across 10 classes. 2996 pytest + 118 vitest pass.

### AD-411: EmergentDetector Pattern Deduplication

| AD | Decision |
|----|----------|
| AD-411 | EmergentDetector pattern deduplication. The proactive loop (Phase 28b) prevents idle state → dream scheduler fires frequently → `EmergentDetector.analyze()` re-analyzes same trust state → duplicate patterns (120 trust anomalies and 174 total patterns in ~1 hour when actual distinct count was ~15-20). (a) **Dedup cache:** `_last_pattern_fired: dict[tuple[str, str], float]` keyed by `(pattern_type, dedup_key)` → monotonic timestamp. Configurable cooldown (default 600s). (b) **Applied to all detectors:** Trust anomalies (deviation: `agent_id:direction`, hyperactive: `hyperactive:agent_id`, change-point: `changepoint:agent_id`), cooperation clusters (sorted member IDs), routing shifts (new connections: `agent[:8]:intent`, new intents: `new_intent:intent`, entropy: quantized to 0.5 buckets). (c) **Stale entry pruning:** `_prune_stale_dedup_entries()` runs at start of each `analyze()` call, removes entries older than 2x cooldown. (d) **Pool name guard:** `create_pool()` returns existing pool if name already exists. (e) **Builder fix:** Entropy dedup used `if not _is_duplicate_pattern(...)` wrapper instead of `continue` since the block was inside an `if`, not a `for` loop. *Discovered by crew: O'Brien, LaForge, and Worf flagged during first proactive loop deployment.* |

**Status:** AD-411 complete — 9 new tests (8 TestPatternDeduplication + 1 TestPoolDuplicateGuard). 3095 pytest + 118 vitest = 3213 total.

### AD-413: Fine-Grained Reset Scope + Ward Room Awareness

| AD | Decision |
|----|----------|
| AD-413 | Fine-grained reset scope + Ward Room awareness in proactive loop. Design decision: reset = day 0, one clean timeline, no bifurcated history (epoch approach rejected as over-engineering). (a) **Expanded reset:** `_cmd_reset()` archives `ward_room.db` to `data_dir/archives/ward_room_{timestamp}.db` before deletion. Also clears DAG checkpoints (`checkpoints/*.json`) and event log (`events.db`). (b) **`--keep-wardroom` flag:** Opt-in to preserve Ward Room history across reset. (c) **Preserved by design:** `scheduled_tasks.db` (user intent), `assignments.db` (user intent), `directives.db` (Captain orders). (d) **`WardRoomService.get_recent_activity()`:** New method returns flat list of recent threads + replies for a channel since a timestamp. Compact format for agent context injection — type, author, title/body (truncated), created_at. (e) **Proactive loop Ward Room awareness:** `_gather_context()` adds 4th context source — recent Ward Room activity from agent's department channel (lookback = one cooldown window). Agents now see what their department has been discussing during proactive thinks. (f) **Prompt rendering:** `_format_observation()` renders Ward Room activity as `[thread]`/`[reply]` entries in proactive think prompt. *Design insight: "I have seen enough sci-fi to know things don't go well if you wipe memory and residue persists." Clean timeline > epoch filtering.* |

**Status:** AD-413 complete — 10 new tests (4 TestResetScope + 5 TestWardRoomRecentActivity + 1 TestProactiveWardRoomContext). 3105 pytest + 118 vitest = 3223 total.

### AD-419: Agent Duty Schedule & Justification

| AD | Decision |
|----|----------|
| AD-419 | Agent duty schedule — Plan of the Day pattern for structured proactive cognition. (a) **Config models:** `DutyDefinition` (duty_id, description, cron/interval_seconds, priority 1-5) and `DutyScheduleConfig` (enabled, schedules dict per agent type), nested under `ProactiveCognitiveConfig.duty_schedule`. (b) **DutyScheduleTracker:** In-memory tracker that determines which duties are due per agent type. Supports cron (via croniter) and interval scheduling. First cycle after startup always due. Sorted by priority (highest first). Records execution timestamps and counts. (c) **Proactive loop integration:** `_think_for_agent()` checks duty schedule before each think. If duty due, passes duty context (duty_id + description) in IntentMessage params. Records execution after completion (even on [NO_RESPONSE]). (d) **Cognitive agent prompts:** Duty cycle gets structured prompt ("Perform your assigned task and report findings"). Free-form think (no duty due) gets justification-required prompt ("Silence is professionalism — [NO_RESPONSE] is the expected default"). (e) **Default schedules:** Scout daily, Security 4h, Engineering 2h, Operations 3h, Diagnostician 6h, Counselor 12h, Architect daily. (f) **Runtime wiring:** Tracker created and wired in `_start_proactive_loop()` when enabled. *Naval metaphor: the Plan of the Day (POD) — every sailor knows their watch schedule. They can act on initiative, but they need a reason.* |

**Status:** AD-419 complete — 13 new tests (10 TestDutyScheduleTracker + 3 TestProactiveLoopDutyIntegration). 3118 pytest + 118 vitest = 3236 total.

### AD-417: Dream Scheduler Proactive-Loop Awareness

| AD | Decision |
|----|----------|
| AD-417 | Dream scheduler proactive-loop awareness — full dreams and EmergentDetector now gate on proactive cognitive loop activity. (a) **`record_proactive_activity()`:** New method on DreamScheduler sets `_last_proactive_time` timestamp. Called from `_think_for_agent()` after the duty check (skipped agents don't count as activity) and before the LLM call. (b) **Full dream idle gate:** `truly_idle = min(idle_time, proactive_idle)` — system must be idle from both user commands AND proactive thinks for `idle_threshold_seconds` (300s) before a full dream fires. Before this fix, full dreams fired every 10 minutes during proactive activity because only user commands reset the idle timer. (c) **`is_proactively_busy` property:** Returns True if proactive activity was within `idle_threshold_seconds`. Exposed for runtime use. (d) **EmergentDetector micro-dream skip:** `_on_post_micro_dream()` in runtime.py skips `EmergentDetector.analyze()` when `is_proactively_busy` is True. Micro-dreams still replay episodes and update Hebbian weights (lightweight, useful), but EmergentDetector — which was producing trust anomaly noise from fresh-from-zero post-reset data — waits for true idle. (e) **`proactive_extends_idle` config toggle:** New `DreamingConfig` field (default True). When False, proactive activity is ignored and dreams fire on the original idle_time basis. Guards both `truly_idle` calculation and `is_proactively_busy`. Wired through DreamScheduler constructor and runtime. *Design insight: "The system is three things — active (user), busy (proactive), or idle (dreaming). Dreams are for idle, not for busy."* |

**Status:** AD-417 complete — 9 new tests (TestDreamSchedulerProactiveAwareness). 3145 pytest + 118 vitest = 3263 total.

### AD-424: Ward Room Thread Classification & Lifecycle

| AD | Decision |
|----|----------|
| AD-424 | Ward Room thread classification and lifecycle — three-mode thread system fixing BF-022 and controlling reply noise. (a) **Thread modes:** `thread_mode` field on `WardRoomThread` dataclass with three values: INFORM (read-only broadcast, no `ward_room_notification` intent sent), DISCUSS (controlled replies with relaxed earned agency — ship-wide DISCUSS threads pass `same_department=True` so Lieutenants can respond), ACTION (existing @mention targeting). Default: DISCUSS for backward compatibility. (b) **Bridge alert integration:** `_deliver_bridge_alert()` creates threads with `thread_mode="inform"`. Ship's Computer advisories no longer trigger LLM calls on all crew. (c) **Responder controls:** `max_responders` field per thread (default from config `default_discuss_responder_cap`). Priority: @mentioned > department-match > highest rank. Prevents reply-all storms. (d) **Thread lifecycle:** `locked` field on threads. Captain can lock/unlock via `PATCH /api/wardroom/threads/{id}`. Locked threads reject new replies. (e) **SQLite schema migration:** Added `thread_mode TEXT DEFAULT 'discuss'`, `max_responders INTEGER`, `locked INTEGER DEFAULT 0` columns to `threads` table with graceful migration for existing data. (f) **REST API:** `PATCH /api/wardroom/threads/{id}` with `UpdateThreadRequest` model for thread_mode, max_responders, locked. (g) **HXI store:** `ScheduledTaskView` interface updates, SSE event handlers for `thread_locked`, `thread_reclassified`. (h) **Config:** `default_discuss_responder_cap` in WardRoomConfig. *Fixes BF-022: Lieutenants can now respond to DISCUSS threads on All Hands. INFORM threads don't trigger responses at all. Connects to: AD-410 (Bridge Alerts), AD-407 (Ward Room), AD-357 (Earned Agency), AD-425 (Active Browsing), AD-426 (Endorsement).* |

**Status:** AD-424 complete — 19 new tests. 3153 pytest + 118 vitest = 3271 total. BF-022 closed.

### AD-414: Proactive Loop Trust Signal

| AD | Decision |
|----|----------|
| AD-414 | Proactive loop trust signal — attenuated trust updates from proactive cognitive loop activity. Problem: after reset, all trust at 0.5 prior; proactive loop calls `handle_intent()` directly bypassing consensus/routing/trust pipeline → trust stagnates. (a) **Successful proactive think:** `record_outcome(agent_id, success=True, weight=0.1, intent_type="proactive_think")` — low-weight positive signal for self-directed activity. (b) **Duty completion bonus:** `trust_duty_bonus=0.1` added when agent completes a scheduled duty (total weight=0.2). (c) **Disciplined silence:** `trust_no_response_weight=0.0` (configurable) — optional positive signal for agents that correctly return `[NO_RESPONSE]`. Default zero (silence expected, not rewarded). (d) **No negative trust:** Proactive loop never emits `success=False` — self-directed activity has no failure penalty (no external validator). (e) **Trust update event:** `on_event` callback emits `trust_update` with `source: "proactive"` for HXI awareness. (f) **Config:** Three fields in `ProactiveCognitiveConfig`: `trust_reward_weight` (0.1), `trust_no_response_weight` (0.0), `trust_duty_bonus` (0.1). Wired via `set_config()` in runtime startup. *Design: proactive trust is attenuated (0.1 vs 1.0 for consensus-verified work) because self-directed activity has no external validation. Externally-validated work remains the primary trust driver. Connects to: Earned Agency (AD-357), Ward Room Endorsement (AD-426, future — endorsement-based boost not yet implemented).* |

**Status:** AD-414 complete — 7 new tests (TestProactiveTrustSignal). Implementation included in Phase 28b+ proactive loop wave.

### AD-425: Ward Room Active Browsing

| AD | Decision |
|----|----------|
| AD-425 | Ward Room active browsing — agents can independently read the Ward Room instead of relying on passive push only. (a) **`browse_threads()`:** New WardRoomService method for cross-channel thread discovery. Queries all subscribed channels (via memberships table), with optional `thread_mode`, `since`, `limit` filters. Returns `list[WardRoomThread]` sorted by `last_activity DESC`. No earned agency gate on read — all crew can read their subscribed channels. (b) **Proactive context expansion:** `_gather_context()` now includes All Hands (ship-wide) activity alongside department channel activity. Top 3 recent DISCUSS threads from All Hands injected into context. INFORM threads excluded (already consumed via acknowledgment). Agents now see both their department's discussion AND ship-wide discourse during proactive thinks. (c) **`get_recent_activity()` thread_mode field:** Result dicts now include `thread_mode` field for thread-type entries, enabling INFORM filtering in proactive context. (d) **Read receipts:** `update_last_seen()` called after `_gather_context()` consumes department channel and All Hands activity. Prevents same threads from appearing in context repeatedly. Non-critical — wrapped in try/except to avoid blocking proactive thinks. (e) **REST API:** `GET /api/wardroom/activity` browsing feed (supports `agent_id`, `channel_id`, `thread_mode`, `limit`, `since` query params). `PUT /api/wardroom/channels/{id}/seen` mark-all-read endpoint. (f) **Crew auto-subscribe:** Ward Room startup now auto-subscribes crew agents to both their department channel AND All Hands. Ensures `browse_threads(channels=None)` returns cross-channel results. *Design decision: NOT implemented as a Skill (dataclass sense). Ward Room browsing is core communication infrastructure, not a dynamically-designed capability. Lives in WardRoomService + proactive loop context gathering. Connects to: AD-424 (thread classification), AD-413 (proactive Ward Room context), AD-426 (endorsement-ranked browsing, future), AD-419 (duty schedule — "check Ward Room" duty, future).* |

**Status:** AD-425 complete — 14 new tests (7 ward_room, 3 proactive, 4 API). 3167 pytest + 118 vitest = 3285 total.

### BF-023: Degraded Agent Death Spiral

| BF | Fix |
|----|-----|
| BF-023 | Degraded agent death spiral — agents stuck permanently at low confidence with no recovery path. **Root cause:** (a) Proactive loop exception handler (`proactive.py:129-135`) caught LLM failures at DEBUG level but never called `update_confidence()`. Confidence froze at whatever value it had when errors started — no signal that failures were happening. (b) `update_confidence()` in `BaseAgent` had no path from DEGRADED back to ACTIVE. Once confidence dropped below 0.2 and state became DEGRADED, success could raise confidence above 0.2 but state stayed DEGRADED forever. **Fix:** (a) Exception handler now calls `agent.update_confidence(False)` before logging, so failures track properly and the agent's confidence reflects reality. (b) `update_confidence()` now checks: if confidence rises back above 0.2 while state is DEGRADED, restore to ACTIVE (with INFO log). (c) Degradation warning only logs on actual state transition (ACTIVE -> DEGRADED), not on every low-confidence update. 5 tests: 3 in test_agent.py (recovery on success, stays degraded on failure, warning on transition only), 2 in test_proactive.py (exception updates confidence, exception doesn't crash loop). |

**Status:** BF-023 closed — 5 new tests. 3172 pytest + 118 vitest = 3290 total.

### BF-024: Proactive Think Guard Missing in Domain Agents

| Decision | Detail |
|---|---|
| BF-024 | Crew agents with domain-specific `perceive()/act()` overrides degrade on every proactive think cycle. Builder, Architect, Counselor, and Scout all had intent guards that only listed `direct_message` and `ward_room_notification`. When `proactive_think` arrived from the proactive loop, it fell through to domain-specific pipelines — Builder tried to parse `===FILE:` blocks, Architect tried to parse `===PROPOSAL===`, Counselor returned a raw dict without `success` key (treated as False), Scout survived by accident (benign fallthrough). Each failure triggered BF-023's confidence decay, degrading all four agents within minutes of boot. **Fix:** Added `"proactive_think"` to the intent guard tuple in `perceive()`, `_build_user_message()`, and `act()` across all four agent classes (builder.py, architect.py, counselor.py, scout.py). Proactive thoughts now delegate to the base `CognitiveAgent` implementation which has proper proactive formatting. |

**Status:** BF-024 closed. No new tests (existing proactive tests cover the flow).

### AD-416: Ward Room Archival & Pruning

| AD | Decision |
|----|----------|
| AD-416 | Ward Room archival and pruning — retention policy and background cleanup for unbounded Ward Room growth. The proactive loop generates ~96 posts/hour (~2,300/day) with 8 crew agents. Without pruning, `ward_room.db` grows indefinitely. (a) **Config:** 5 new `WardRoomConfig` fields: `retention_days` (7), `retention_days_endorsed` (30), `retention_days_captain` (0=indefinite), `archive_enabled` (True), `prune_interval_seconds` (86400). Three-tier retention respects content value — endorsed/flagged posts live 4x longer, Captain posts are permanent. (b) **`prune_old_threads()`:** Selective deletion with JSONL archival. Skips pinned, endorsed, and Captain-authored threads based on retention tier. Cascading deletes: thread → posts → endorsements. Archive writes thread+posts as single JSON object per thread to `data_dir/ward_room_archive/YYYY-MM.jsonl`. (c) **Stats and dry-run:** `get_stats()` returns thread/post/endorsement counts + DB file size. `count_pruneable()` returns dry-run count of threads eligible for pruning without deleting. (d) **Background prune loop:** `start_prune_loop()`/`stop_prune_loop()` — asyncio background task, configurable interval (default 24h), monthly JSONL rotation. (e) **Runtime integration:** Prune loop starts after Ward Room init, stops before shutdown. `_cleanup_ward_room_tracking()` callback clears stale in-memory channel/thread dicts on `ward_room_pruned` event. `ward_room_stats` exposed in `build_state_snapshot()`. (f) **REST API:** `GET /api/ward-room/stats` (counts + pruneable + retention config), `POST /api/ward-room/prune` (manual Captain trigger with summary response). *Naval metaphor: the active deck log covers the current patrol; completed logs are bound and shelved in the ship's library.* |

**Status:** AD-416 complete — 14 new tests in TestWardRoomPruning covering all retention tiers, cascading deletes, JSONL archival (format, append, skip), dry-run count, stats, summary, events. 3196 pytest + 118 vitest = 3314 total.

### AD-430: Agent Experiential Memory — Closing the Memory Gap

| AD | Decision |
|----|----------|
| AD-430 | Agent Experiential Memory — closing the critical gap where most agent activity never writes to EpisodicMemory. Today only 5 write paths exist (DAG execution, renderer, shell 1:1, feedback, QA smoke). Three major activity categories produce no episodes: proactive thoughts, Ward Room conversations, and HXI 1:1 conversations. Agents can't remember their own thoughts, can't recall crew discussions, and can't maintain Captain interaction continuity. **Five pillars:** (1) Proactive think episodes — store thought + outcome after each proactive cycle, including `[NO_RESPONSE]` results. (2) Ward Room conversation episodes — hook into `create_thread()`/`create_post()` event emission, store sovereign episode for the authoring agent only. (3a) HXI 1:1 episode storage — mirror the shell `/hail` pattern in the API path. (3b) HXI conversation history passing — extend `IntentMessage` params with last N exchanges from HXI client, enable `_build_user_message()` to include history. (4) Memory-aware decision making — add `_recall_relevant_memories()` between `perceive()` and `decide()` in `handle_intent()`, inject max 3 recalled episodes as context. (5) Act-store lifecycle hook — generic post-act episode storage in `handle_intent()` for crew agents (Tier 3 only), with dedup flag to prevent double-storage. **Build order:** AD-430a (write paths: Pillars 1-2), AD-430b (HXI history + storage: Pillar 3), AD-430c (recall + lifecycle hook: Pillars 4-5). **Prerequisite for:** Procedural Learning / Cognitive JIT (needs action history to crystallize), AD-428 Skill Framework (needs evidence of practice for proficiency), dream consolidation (needs episodes to replay). |

**Status:** AD-430a complete — 8 new tests (4 in test_proactive.py, 4 in test_ward_room.py). Proactive think episodes (successful + no-response) and Ward Room conversation episodes (thread creation + replies) now write to EpisodicMemory. Runtime passes episodic_memory to WardRoomService at construction. All storage wrapped in try/except — non-critical. 3204 pytest + 118 vitest = 3322 total.

AD-430b complete — 19 new tests in test_api_profile.py. HXI 1:1 chat now passes conversation history via `session_history` in IntentMessage params (capped at 10 entries server-side). Episode storage after each HXI chat response. Cross-session memory seeding via `GET /api/agent/{id}/chat/history` endpoint — recalls last 3 episodes and prepends to first message. ProfileChatTab captures history before addAgentMessage to avoid duplication. 3223 pytest + 118 vitest = 3341 total.

AD-430c complete — 13 new tests in test_cognitive_agent.py (TestMemoryRecall: 5, TestActStoreHook: 6, TestBuildUserMessageMemories: 2). Pillar 4: `_recall_relevant_memories()` inserted between perceive() and decide() in handle_intent() — enriches observation with up to 3 semantically relevant episodes. Renders memories in `_build_user_message()` for direct_message and ward_room_notification. Pillar 5: `_store_action_episode()` inserted after report() — universal safety net for crew agent actions. Dedup: skips proactive_think (430a), ward_room_notification (430a), direct_message from hxi_profile (430b) and captain (shell). All in CognitiveAgent base class — covers all 11 crew agents. 3236 pytest + 118 vitest = 3354 total.

**AD-430 COMPLETE — all 5 pillars delivered across 3 build steps.** Memory gap closed: agents now write, recall, and store episodes across all interaction paths. The developmental pipeline (dream consolidation, Cognitive JIT, skill progression) is unblocked.

AD-430b complete — 19 new tests in test_api_profile.py. HXI 1:1 chat now passes conversation history via `session_history` in IntentMessage params (capped at 10 entries server-side). Episode storage after each HXI chat response. Cross-session memory seeding via `GET /api/agent/{id}/chat/history` endpoint — recalls last 3 episodes and prepends to first message. ProfileChatTab captures history before addAgentMessage to avoid duplication. 3223 pytest + 118 vitest = 3341 total. AD-430c (memory recall + act-store hook) next.

### AD-415: Proactive Cooldown Persistence

| AD | Decision |
|----|----------|
| AD-415 | Per-agent proactive cooldown overrides now persist to KnowledgeStore (`proactive/cooldowns.json`). Write-through on `set_agent_cooldown()` via fire-and-forget asyncio task. Restored on boot via `restore_cooldowns()`. Persisted during shutdown. Wiped on `probos reset` (consistent — if you reset the crew's memory, resetting their duty tempo is consistent). |

**Status:** AD-415 complete — 10 new tests in TestCooldownPersistence. KnowledgeStore gains `store_cooldowns()`/`load_cooldowns()` methods + `"proactive"` subdirectory. Runtime wires `_knowledge_store` into `ProactiveCognitiveLoop` before `start()`.

### BF-027/028: Memory Recall Hardening

| BF | Decision |
|----|----------|
| BF-027 | Agent memory recall ineffective — three fixes: (a) lowered agent-scoped recall threshold from 0.7 to 0.3 in `recall_for_agent()` (sovereign shard filter already constrains results). (b) Added `recent_for_agent()` timestamp-based fallback to EpisodicMemory + MockEpisodicMemory. (c) Added `recall_for_agent()` to MockEpisodicMemory (was missing — tests silently skipped recall). |
| BF-028 | Extended `recent_for_agent()` fallback to proactive `_gather_context()` and shell cross-session recall — two sites that BF-027 missed. |

**Status:** BF-027 closed — 6 tests. BF-028 closed — 2 tests. All recall sites now have fallback.

### AD-431: Cognitive Journal — Agent Reasoning Trace Service

| AD | Decision |
|----|----------|
| AD-431 | Cognitive Journal — append-only SQLite store recording every LLM call with full metadata: timestamp, agent_id, agent_type, tier, model, prompt_tokens, completion_tokens, total_tokens, latency_ms, intent, success, cached, request_id, prompt_hash, response_length. Ship's Computer infrastructure service (no identity). Single instrumentation point in `decide()` — wrap `llm_client.complete()` with `time.monotonic()` timing, fire-and-forget journal record. Cache hits also journaled (cached=True, zero tokens). `LLMResponse` gained `prompt_tokens` + `completion_tokens` fields; both OpenAI and Ollama paths extract separate counts. REST API: `GET /api/journal/stats`, `GET /api/agent/{id}/journal`, `GET /api/journal/tokens`. Does NOT depend on Ship's Telemetry. Wiped on `probos reset`. |

**Status:** AD-431 complete — 13 new tests in test_cognitive_journal.py. New file: `src/probos/cognitive/journal.py`. Config: `CognitiveJournalConfig(enabled=True)`. 3266 pytest + 118 vitest = 3384 total.

### BF-029: Ward Room Memory Recall Quality

| BF | Fix |
|----|-----|
| BF-029 | Ward Room memory recall quality in 1:1 conversations. Agents can't recall Ward Room posts when Captain asks — episodes stored correctly (AD-430a) but recall pipeline has three issues: (a) `direct_message` recall query uses raw Captain text with no Ward Room signal in embedding, (b) memory presentation prefers thin reflection strings over content-rich input, (c) Ward Room reply reflections lack body content. **Fix:** Prepend `"Ward Room {callsign}"` to recall query for direct_message, reverse input/reflection preference in both prompt builders, include body excerpt in reply reflections + channel name in reply user_input. 10 tests. |

**Status:** BF-029 closed — 10 new tests. 3276 pytest + 118 vitest = 3394 total.

### BF-030: Ward Room execute_fetchone Fix

| BF | Fix |
|----|-----|
| BF-030 | `ward_room.py` used `self._db.execute_fetchone()` which doesn't exist in aiosqlite. **Fix:** Replaced with standard `async with self._db.execute(...) as cursor: row = await cursor.fetchone()`. |

**Status:** BF-030 closed — no new tests.

### AD-433: Selective Encoding Gate — Biologically-Inspired Memory Filtering

| AD | Decision |
|----|----------|
| AD-433 | Selective Encoding Gate — biologically-inspired memory filter at agent experience boundaries. `EpisodicMemory.should_store()` static method: pure function (zero I/O, sub-microsecond) that inspects Episode metadata and returns bool. Always stores Captain 1:1 and failure episodes. Blocks proactive no-response episodes (highest-volume noise), QA routine passes (QA failures still stored), and episodes where all responses are empty/`[NO_RESPONSE]`. Conservative default: unknown formats stored. Gate applied at 4 call sites: proactive.py Sites 4/5 (no-response/with response), runtime.py Site 3 (SystemQA), cognitive_agent.py Site 8 (catch-all `_store_action_episode`). NOT gated (always signal): Sites 1, 2, 6, 7, 9, 10 (Captain commands, 1:1, Ward Room authoring). `MockEpisodicMemory.should_store()` delegates to real gate. Memory Architecture Layer 2. |

**Status:** AD-433 complete — 11 new tests in test_selective_encoding.py. 3291 pytest + 118 vitest = 3409 total.

### AD-432: Cognitive Journal Expansion — Traceability + Query Depth

| AD | Decision |
|----|----------|
| AD-432 | Cognitive Journal expansion — traceability columns and advanced queries. (a) **Schema:** 3 new columns (`intent_id`, `dag_node_id`, `response_hash`) with idempotent migration (`ALTER TABLE ADD COLUMN` in try/except). Index on `intent_id`. (b) **Traceability:** `intent_id` plumbed from `IntentMessage.id` through `perceive()` → `decide()` → journal on both LLM-call and cache-hit paths. `response_hash` (MD5 fingerprint of first 500 chars) added to LLM call recording. `dag_node_id` column is schema placeholder (not yet populated — future AD). (c) **Time-range queries:** `get_reasoning_chain()` gains `since`/`until` parameters with dynamic WHERE clause. (d) **Grouped token usage:** `get_token_usage_by(group_by)` — groups by model/tier/agent_id/agent_type/intent with SQL injection whitelist. (e) **Decision points:** `get_decision_points()` — finds high-latency or failed LLM calls for anomaly detection. (f) **Reset support:** `wipe()` method (DELETE not DROP) for `probos reset`. (g) **API:** Existing journal endpoint gains `since`/`until` params. New `GET /api/journal/tokens/by` (grouped stats). New `GET /api/journal/decisions` (anomaly finder). |

**Status:** AD-432 complete — 15 new tests in test_cognitive_journal.py (28 total). 3302 pytest + 118 vitest = 3420 total.

### AD-412: Crew Improvement Proposals Channel

| AD | Decision |
|----|----------|
| AD-412 | Crew Improvement Proposals Channel — closes the collaborative improvement loop. (a) **#Improvement Proposals channel** seeded in `_ensure_default_channels()` as `channel_type="ship"` (ship-wide visibility). Idempotent — skips if already exists. All crew auto-subscribed at startup. (b) **`[PROPOSAL]` block extraction** in proactive loop (`_extract_and_post_proposal`): regex parses structured blocks with title/rationale/affected_systems/priority from agent think output. Supports multiline rationale. Silently skips incomplete proposals (missing title or rationale). (c) **`_handle_propose_improvement()` runtime handler**: validates fields, formats structured body (author attribution, priority, affected systems), creates discuss-mode thread in proposals channel with `[Proposal]` title prefix. Returns thread_id on success. (d) **REST API** `GET /api/wardroom/proposals`: lists proposals with status derivation from `net_score` (approved >0, shelved <0, pending =0). Supports `?status=` filter. (e) **Proactive prompt update**: agents told they can use `[PROPOSAL]` format for concrete, evidence-based improvement suggestions. (f) **Endorsement reuse**: existing `endorse()` mechanics provide Captain approve (upvote) / shelve (downvote) workflow — no new endorsement code. |

**Status:** AD-412 complete — 13 new tests across test_ward_room.py, test_proactive.py. 3315 pytest + 118 vitest = 3433 total.

### BF-031: Cognitive Journal Schema Migration Ordering

| BF | Fix |
|----|-----|
| BF-031 | `CognitiveJournal.start()` ran `executescript(_SCHEMA)` which included `CREATE INDEX ... ON journal(intent_id)` — but on pre-AD-432 databases, the table existed without the `intent_id` column. `CREATE TABLE IF NOT EXISTS` was a no-op, leaving the column missing when the index was created. **Fix:** Split `_SCHEMA` into `_SCHEMA_BASE` (table + safe indexes) and `_SCHEMA_INDEXES` (indexes on migrated columns). Startup order: base schema → ALTER TABLE migrations → dependent indexes. |

**Status:** BF-031 closed — no new tests (startup path).

### AD-418: Post-Reset Routing Degradation

| AD | Decision |
|----|----------|
| AD-418 | Post-Reset Routing Degradation — three-part fix for scheduled tasks firing into zero-weight routing post-reset. (a) **`agent_hint` field** on `PersistentTask`: optional `agent_type` string stored in SQLite (idempotent migration). Threaded through `create_task()` → `_fire_task()` → `process_natural_language()`. API: `ScheduledTaskRequest` accepts hint, new `PATCH /api/scheduled-tasks/{id}/hint` endpoint for updating existing tasks. (b) **HebbianRouter hint integration**: `get_preferred_targets()` gains `hint` parameter — boosts matching candidate by +1.0 synthetic weight. Wins at zero weights, can be tied/outweighed by strong learned weights (>1.0). Bias, not a hard pin. (c) **Reset warning**: `_cmd_reset()` counts active recurring scheduled tasks (synchronous sqlite3), warns in confirmation prompt and post-reset summary about degraded routing. |

**Status:** AD-418 complete — 9 new tests across test_persistent_tasks.py, test_routing.py. 3324 pytest + 118 vitest = 3442 total.

### AD-426: Ward Room Endorsement Activation

| AD | Decision |
|----|----------|
| AD-426 | Ward Room Endorsement Activation — agents can now endorse posts for quality signaling. 5 pillars implemented (pillar 5 credibility gating deferred). (a) **Endorsement prompts** added to `ward_room_notification` and `proactive_think` branches in cognitive_agent.py. Agents use `[ENDORSE post_id UP/DOWN]` syntax after replies or with `[NO_RESPONSE]`. (b) **`_extract_endorsements()` parser** on Runtime: regex extracts endorsement blocks, returns cleaned text. Integrated into `_route_ward_room_event()` before `[NO_RESPONSE]` check — even silent agents can endorse. Endorsement markup never leaks into post body. (c) **`_process_endorsements()` trust bridge**: calls `ward_room.endorse()` + looks up post author via `get_post()` + emits trust signal via `record_outcome(weight=0.05, intent_type="ward_room_endorsement")`. UP→success=True, DOWN→success=False. Self-endorsement caught silently (existing ValueError). (d) **`get_post()` helper** added to WardRoom — returns post details including `author_id` for trust bridging. (e) **Context surfacing**: `get_recent_activity()` now returns `net_score` and `post_id` fields. `_gather_context()` in proactive.py includes both in ward_room_activity dicts (department + All Hands). (f) **Endorsement-ranked browsing**: `browse_threads()` gains `sort` parameter ("recent"|"top"). Top sorts by `net_score DESC, last_activity DESC`. API `GET /api/wardroom/browse` accepts `sort` query param. |

**Status:** AD-426 complete — 15 new tests across test_ward_room.py, test_proactive.py. 3339 pytest + 118 vitest = 3457 total.

### AD-428: Agent Skill Framework — Developmental Competency Model

| AD | Decision |
|----|----------|
| AD-428 | Agent Skill Framework — foundation data model for agent developmental competencies. Coexists with existing `Skill` dataclass (types.py line 406) which remains unchanged as the self-mod code-execution handle. (a) **Data model** (`skill_framework.py`): `SkillCategory` enum (PCC/ROLE/ACQUIRED), `ProficiencyLevel` enum (1-7: FOLLOW→ASSIST→APPLY→ENABLE→ADVISE→LEAD→SHAPE, unified Dreyfus+Bloom+SFIA scale), `SkillDefinition` dataclass (skill_id, category, domain, prerequisites, decay_rate_days), `AgentSkillRecord` dataclass (agent_id, skill_id, proficiency, exercise_count, assessment_history), `SkillProfile` dataclass (pccs/role_skills/acquired_skills lists, depth/breadth properties). (b) **Built-in constants**: 7 PCCs (communication, chain_of_command, duty_execution, collaboration, knowledge_stewardship, self_assessment, ethical_reasoning) + `ROLE_SKILL_TEMPLATES` for 7 agent types (security_officer, engineering_officer, operations_officer, diagnostician, scout, counselor, architect) with prerequisite chains. (c) **SkillRegistry** — Ship's Computer service (infrastructure tier), SQLite persistence, in-memory cache, `register_skill()`, `register_builtins()`, `get_prerequisites()` DAG walk, `list_skills()` with category/domain filters. (d) **AgentSkillService** — Ship's Computer service, `acquire_skill()` with prerequisite enforcement (requires APPLY+ on prereqs), `commission_agent()` (idempotent — all PCCs at FOLLOW + role skills), `update_proficiency()` with assessment history, `record_exercise()` (resets decay timer), `check_decay()` (drops one level per decay period, never below FOLLOW), `get_profile()`, `check_prerequisites()`. (e) **Runtime integration**: `skill_registry` + `skill_service` attributes on Runtime, started/stopped in lifecycle, `build_state_snapshot()` includes skill_framework flag. (f) **REST API**: 6 endpoints — `GET /api/skills/registry` (list definitions), `GET /api/skills/agents/{id}/profile`, `POST /api/skills/agents/{id}/commission`, `POST /api/skills/agents/{id}/assess`, `POST /api/skills/agents/{id}/exercise`, `GET /api/skills/agents/{id}/prerequisites/{skill_id}`. Shared `skills.db` for both services. |

**Status:** AD-428 complete — 25 new tests in test_skill_framework.py. 3364 pytest + 118 vitest = 3482 total.

### BF-032: Proactive Observation Self-Reference Loop

| BF | Decision |
|----|----------|
| BF-032 | Proactive observation self-reference loop fix. Agents (Troi, Selar) were caught in recursive meta-observation loops — observing their own posting patterns, posting about that, then observing the meta-observation. Three-layer fix: (a) **Self-post filter** in `_gather_context()` — builds `self_ids` set from agent.id/agent_type/callsign, filters both department and All Hands Ward Room activity loops so agents never see their own posts as "new activity." (b) **Content similarity gate** — `_is_similar_to_recent_posts()` method computes Jaccard word-set similarity against last 3 posts, threshold 0.5, fail-open. Called in `_think_for_agent()` before `_post_to_ward_room()`. Suppressed posts still record duty execution. (c) **Prompt instruction** — "Do not comment on your own posting patterns or observation frequency" added to free-form proactive think prompt in `cognitive_agent.py`. |

**Status:** BF-032 closed — 5 new tests in test_proactive.py. 3369 pytest + 118 vitest = 3487 total.

### AD-435: Restart Announcements

| Aspect | Decision |
|--------|----------|
| AD-435 | Restart Announcements — Ward Room notifications for system shutdown/startup. Without context, agents misinterpret dev-cycle reboots as system instability (observed: Bones, Ogawa, Selar all flagged restarts as pathological). Three parts: (a) **Shutdown announcement** — `runtime.stop(reason="")` posts "System Restart" thread to All Hands before service teardown, author `system`/`Ship's Computer`, `announce` mode, `max_responders=0`. Best-effort — never blocks shutdown. (b) **Startup announcement** — "System Online" thread posted at end of `start()` after all services ready. (c) **Shell `/quit` reason threading** — `/quit <reason>` stores reason, `__main__.py` passes it through to `runtime.stop()`. Key insight: absence of a shutdown announcement before a "System Online" implies a crash, not planned maintenance. |

**Status:** AD-435 complete — 6 new tests in test_restart_announcements.py. 3375 pytest + 118 vitest = 3493 total.

### BF-033: Agent Profile Cards — Unwired Episodes + Uptime

| BF | Decision |
|----|----------|
| BF-033 | Agent profile cards showed "0 Episodes" and "0s uptime" because both fields were stubs. (a) **Episodes** — API checked `hasattr(episodic_memory, 'count_for_agent')` but the method didn't exist on EpisodicMemory. Added `count_for_agent(agent_id)` — iterates ChromaDB metadatas, filters by `agent_ids_json` membership, returns count. (b) **Uptime** — API hardcoded `0.0`. Builder wired `time.monotonic() - runtime._start_time` during AD-435. Both now render correctly on profile Health tab. |

**Status:** BF-033 closed — 0 new tests (method covered by existing profile tests). 3375 pytest + 118 vitest = 3493 total.

### AD-427: Agent Capital Management (ACM) — Core Framework

| Aspect | Decision |
|--------|----------|
| AD-427 | ACM Core Framework — consolidated agent lifecycle management. Wraps existing subsystems (TrustNetwork, EarnedAgency, CrewProfile, SkillFramework) into an integrated lifecycle framework. "ACM is the HR department — it doesn't do the work, it manages the people who do the work." Four pillars: (a) **Lifecycle state machine** — 5 states (registered → probationary → active → suspended → decommissioned), 7 legal transitions, illegal transitions raise ValueError, decommissioned is terminal. SQLite persistence in `acm.db`. (b) **Audit trail** — every transition recorded with from/to state, reason, initiated_by, timestamp. Full history queryable per agent. (c) **Consolidated profile** — `get_consolidated_profile()` aggregates lifecycle state, crew profile (identity/personality/rank), trust score, agency level, skill profile, episode count into one view. Reads from existing subsystems, doesn't duplicate data. (d) **Runtime integration** — ACM starts/stops with runtime, crew agents auto-onboarded to PROBATIONARY during `_wire_agent()`. 5 REST endpoints: profile, lifecycle, decommission, suspend, reinstate. |

**Status:** AD-427 complete — 27 new tests in test_acm.py. 3402 pytest + 118 vitest = 3520 total.

### AD-436: HXI Bridge System Panel + Orbital Notification Redesign

| Aspect | Decision |
|--------|----------|
| AD-436 | Combined HXI improvements: Bridge System Panel + Orbital Notification Redesign. Two problems: (a) Agents and Captain lack visibility into system service status — Scotty correctly identified that agents can USE services but can't VERIFY their status. No HXI controls for shutdown or thread management. (b) Notification torus rings inside opaque agent orbs are invisible. **Part 1 — Bridge System Panel:** `GET /api/system/services` lists 11 runtime services with online/offline status. `POST /api/system/shutdown` with reason field (fire-and-forget via _track_task, 1s delay for HTTP response). New `BridgeSystem.tsx` component with ServiceStatusList (auto-refresh 10s), ShutdownControl (confirmation dialog), ThreadManagement (lock/unlock via existing PATCH endpoint). Added as BridgeSection in BridgePanel.tsx. **Part 2 — Orbital Notifications:** Replace torusGeometry with sphereGeometry electrons orbiting on tilted orbital planes. Three tiers on three Euler-rotated planes, 2 dots per tier, golden angle phase offset (137.5°). RED: 1.3x orbit, 3 rev/s, pulsing. AMBER: 1.6x, speed varies. CYAN: 1.9x, 0.5 rev/s. 330 instances (55 × 6). |

**Status:** AD-436 COMPLETE. 6 files (2 new), 5 tests. Services endpoint, shutdown control, orbital electron notifications.

### AD-437: Ward Room Action Space — Structured Agent Actions

| Aspect | Decision |
|--------|----------|
| AD-437 | Agents can only post text during proactive thoughts. The Ward Room has endorsement, reply, thread management APIs but agents can't invoke them — they express intent in text (`[ENDORSE post_id UP]`) without executing it. Additionally, `[ENDORSE]` tags in proactive responses are posted raw (never extracted in proactive path — only wired in Ward Room notification path). **Fix:** (1) Wire `_extract_endorsements()` + `_process_endorsements()` into proactive loop via new `_extract_and_execute_actions()` method. (2) Add `[REPLY thread_id]...[/REPLY]` structured action for Commander+ agents. (3) Gate actions by Earned Agency rank: Lieutenant=endorse, Commander=endorse+reply, Senior=full. (4) `can_perform_action(rank, action)` in `earned_agency.py`. (5) Include `thread_id` in Ward Room activity context so agents can reference threads. (6) Update proactive prompt with rank-aware action space description. (7) Communication PCC exercise on successful endorsement (AD-428 integration). |

**Status:** AD-437 build prompt ready.