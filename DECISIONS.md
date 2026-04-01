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

**Status:** AD-437 COMPLETE. 5 files modified, 1 new test file (15 tests). `_extract_and_execute_actions()` + `_extract_and_execute_replies()` in proactive loop. `can_perform_action()` in earned_agency. Rank-aware action space prompt. Communication PCC reinforcement on endorsements.

### AD-429a: Vessel Ontology Foundation — Vessel + Organization + Crew Domains

| Aspect | Decision |
|--------|----------|
| AD-429a | ProbOS's organizational structure is hardcoded in Python dicts (\_WARD\_ROOM\_CREW, \_AGENT\_DEPARTMENTS). Agent identity is defined in text prompts. Without a formal model, agents fill identity gaps from LLM training data (the "Troi Problem"). **Fix:** VesselOntologyService — Ship's Computer infrastructure service that loads ontology from config/ontology/*.yaml (Vessel, Organization, Crew domains), builds in-memory graph, provides query methods. Data models: Department, Post, Assignment, VesselIdentity, VesselState. Key methods: get\_chain\_of\_command(), get\_crew\_context(), get\_crew\_agent\_types(). Instance ID persisted across restarts. Three REST endpoints (/api/ontology/vessel, /organization, /crew/{agent\_type}). Context injection in proactive loop \_gather\_context() for agent identity grounding. Coexists alongside existing dicts — no callers migrated yet (future ADs). |

**Status:** AD-429a COMPLETE. 4 new files (3 YAML schemas + ontology.py), 3 modified (runtime.py, api.py, proactive.py), 1 new test file (30 tests).

### AD-429b: Skills Ontology Domain — Formalizing the Competency Model

| Aspect | Decision |
|--------|----------|
| AD-429b | The skill framework (AD-428) runs independently from the ontology. Role templates and qualification requirements exist only in the roadmap. Promotion is trust-based with no formal competency gating. **Fix:** Skills ontology domain that bridges the skill framework and ontology. (1) config/ontology/skills.yaml defines skill taxonomy, 11 role templates (required/optional skills per post with min proficiency), 3 qualification paths (ensign→lt, lt→cmdr, cmdr→senior). (2) New data models: SkillRequirement, RoleTemplate, QualificationRequirement, QualificationPath in ontology.py. (3) QualificationRecord in skill\_framework.py with SQLite persistence, evaluate\_qualification() evaluates agent skills against path requirements. (4) get\_crew\_context() extended with role\_requirements + skills\_note. (5) Proactive loop \_gather\_context() includes skill profile data. (6) /api/ontology/skills/{agent\_type} endpoint. (7) Runtime wires ontology ↔ skill\_service. |

**Status:** AD-429b COMPLETE. 1 new file (skills.yaml created in AD-429b Step 1), 5 modified (ontology.py, skill\_framework.py, runtime.py, proactive.py, api.py), 1 new test file (16 tests).

### AD-429c: Operations, Communication & Resources Ontology Domains

| AD | Decision |
|----|----------|
| AD-429c | Completes the core ontology model with three new domains. (a) **Operations domain** — formalizes standing orders tier hierarchy (7 tiers: Agent Identity through Active Directives, tiers 1/1.5/2 immutable, 3-6 mutable), watch types (alpha/beta/gamma with staffing levels), alert procedures (GREEN/YELLOW/RED with escalation actions), duty categories (monitoring/analysis/reporting/maintenance). (b) **Communication domain** — formalizes Ward Room channel types (ship/department/dm/custom), thread modes (inform/discuss/action/announce with routing strategies), message patterns (observation/proposal/endorsement/reply/no\_response with min\_rank gating), credibility system. (c) **Resources domain** — formalizes 3-tier LLM model system (fast/standard/deep), tool capabilities taxonomy (7 capabilities with access gating), three-tier knowledge source model (Experience→Records→Operational State). All three domains follow established pattern: YAML schema + dataclasses + `_load_*()` method + query methods. `get_crew_context()` extended with `alert_condition`, `alert_procedure`, and `available_actions`. 3 new REST endpoints: `/api/ontology/operations`, `/api/ontology/communication`, `/api/ontology/resources`. |

**Status:** AD-429c COMPLETE. 3 new YAML schemas (operations.yaml, communication.yaml, resources.yaml), 2 modified (ontology.py, api.py), 1 new test file (25 tests).

### AD-429d: Records Ontology Domain — Ship's Records Schema

| AD | Decision |
|----|----------|
| AD-429d | Eighth and final ontology domain: Records. Defines the formal schema for the Ship's Records system (AD-434) — schema only, no runtime persistence. (a) **Three-tier knowledge model** — Tier 1 Experience (EpisodicMemory, own\_shard\_only), Tier 2 Records (Ship's Records, all\_crew, git-backed), Tier 3 Operational State (KnowledgeStore, ship\_computer). Promotion paths between tiers. (b) **Document classifications** — 4 levels (private/department/ship/fleet) with access scoping. (c) **Document classes** — 6 categories: Captain's Log (append-only, permanent, signed), Agent Notebook (private, 90-day archive), Published Report (ship, 365-day), Duty Log (department, 180-day), Operations Record (system-generated), Manual (permanent, living docs). (d) **Retention policies** — 4 policies (permanent, 90/180/365 day archive). (e) **Document schema** — 4 required + 6 optional frontmatter fields. (f) **Repository structure** — 7 directories for AD-434 implementation. `get_crew_context()` extended with `knowledge_model` (3 tiers + note). 1 REST endpoint: `/api/ontology/records`. |

**Status:** AD-429d COMPLETE. 1 new YAML schema (records.yaml), 2 modified (ontology.py, api.py), 1 new test file (16 tests).

### BF-036: EmergentDetector Trust Anomaly Flooding

| BF | Decision |
|----|----------|
| BF-036 | After BF-034's 5-minute cold-start suppression expires, `detect_trust_anomalies()` floods 10-30+ false positives. Root cause: during early-session transition, population std is tiny (~0.02) so even small absolute trust differences (0.5→0.6 from one task success) register as 4-5 sigma. Each agent has unique dedup key so dedup doesn't help. Agents enter confabulation cascades fabricating "trust substrate corruption" narratives. **Fix:** Three guards in the sigma deviation block: (1) Raised std floor from 0.001 to 0.05 — sigma analysis meaningless when entire population within 5%. (2) Min observations guard — skip agents with alpha+beta < 8.0 (fewer than 4 actual observations beyond the Beta(2,2) prior). (3) Min absolute deviation guard — skip if abs(score-mean) < 0.10 regardless of sigma magnitude. Guards are layered so each catches different edge cases. |

**Status:** BF-036 CLOSED. 1 file modified (emergent_detector.py), 7 new tests in test_emergent_detector.py.

### BF-037: Ontology Context Gathered But Never Rendered

| BF | Decision |
|----|----------|
| BF-037 | `_gather_context()` in proactive.py collects `context["ontology"]` (AD-429a) and `context["skill_profile"]` (AD-429b) but `_build_user_message()` in cognitive_agent.py never reads these keys — data silently dropped. This is the primary anti-Troi-problem mechanism; without rendering, 4 ADs of ontology work have no effect on agent behavior. **Fix:** Two rendering blocks in `_build_user_message()` proactive_think branch, inserted after cold-start system note, before memories: (1) Ontology identity grounding — renders callsign, post, department, reports_to, direct_reports, peers, vessel name/version/alert condition. (2) Skill profile — comma-joined skill list. Prompt order: header → cold-start note → ontology → skills → memories → alerts → events → Ward Room → closing. |

**Status:** BF-037 CLOSED. 1 file modified (cognitive_agent.py), 1 new test file (8 tests).

### BF-039: Episodic Memory Flooding — Throttling & Deduplication

| BF | Decision |
|----|----------|
| BF-039 | Episodic memory flooding during normal operation — agents storing redundant/duplicate episodes at unsustainable rates. 6 fixes: (1) Removed duplicate `count_for_agent()` method in episodic.py. (2) Per-agent rate limiter (`MAX_EPISODES_PER_HOUR=20`) prevents runaway storage. (3) Content similarity gate — Jaccard similarity >0.8 within 30-minute window rejects near-duplicate episodes. (4) Ward Room episodes routed through `should_store()` gate instead of bypassing throttling. (5) Proactive episode dedup — skip storage when Ward Room already stores the same interaction. (6) Cold-start 3x cooldown for first 10 minutes to prevent orientation-phase flooding. |

**Status:** BF-039 CLOSED. 3 files modified (episodic.py, proactive.py, ward_room.py), 12 new tests.

### AD-429e: Ontology Dict Migration — Runtime Wiring

| AD | Decision |
|----|----------|
| AD-429e | AD-429a–d delivered the ontology schema and context injection, but runtime code still uses hardcoded dicts (`_WARD_ROOM_CREW`, `_AGENT_DEPARTMENTS`) for crew membership and department lookups. This AD wires the ontology as the preferred source across all call sites, with legacy dict fallback. **Pattern:** `(ont.get_agent_department(agent_type) if ont else None) or get_department(agent_type)`. **Changes:** (1) `runtime.py` — `_is_crew_agent()` prefers `ont.get_crew_agent_types()`, 4× `get_department()` call sites updated (crew auto-subscription, 2× department channel notification, ACM onboarding), ontology wired to WardRoom post-init, legacy comments added to `_WARD_ROOM_CREW`. (2) `ward_room.py` — `__init__()` accepts `ontology` param, `_ensure_default_channels()` prefers `ont.get_departments()` over legacy dict. (3) `proactive.py` — 3× `get_department()` call sites updated (self-ID, department channel, agent matching). (4) `shell.py` — 5× `get_department()` call sites updated (department CLI commands). (5) `standing_orders.py` — legacy deprecation comment on `_AGENT_DEPARTMENTS`. **Test fix:** MagicMock auto-creates truthy attributes on access, so `getattr(self, 'ontology', None)` returns a truthy MagicMock on mock runtimes — fixed by explicitly setting `mock.ontology = None` in all mock runtime factories (test_proactive.py, test_ward_room_agents.py). |

**Status:** AD-429e COMPLETE. 5 files modified (runtime.py, ward_room.py, proactive.py, shell.py, standing_orders.py), 2 test files updated (test_proactive.py, test_ward_room_agents.py), 1 new test file (10 tests).

### AD-441: Sovereign Agent Identity — Birth Certificates & Identity Ledger

| AD | Decision |
|----|----------|
| AD-441 | Agents AND ProbOS instances need persistent, globally-unique identity that survives restarts and is unique across all ProbOS instances in the Nooplex. Current deterministic IDs from `substrate/identity.py` are **slot identifiers** (deployment position) — stable across restarts but not globally unique. **Design:** (1) Sovereign ID = UUID v4, issued once at birth, persisted forever. (2) **Ship DID:** `did:probos:{instance_id}` — the ProbOS instance itself has a sovereign identity, is the root of trust, its birth certificate is self-signed. Reset = new instance_id = new ship DID = new timeline. (3) **Agent DID:** `did:probos:{instance_id}:{agent_uuid}` — globally unique, namespaced under the ship that birthed the agent. W3C DID standard, interoperable from day one. (4) Birth Certificate = W3C Verifiable Credential. Ships AND agents both get birth certificates. Agent certs issued by ACM with embedded SHA-256 proof. Records agent_type, instance_id, callsign, department, post_id, baseline_version, born_at. (5) Identity Ledger = hash-chain blockchain per ship — genesis block = ship's own birth certificate (not a placeholder), each agent birth appends a block. Tamper-evident, federation-syncable via `export_chain()`. (6) `AgentIdentityRegistry` — SQLite-backed with 3 tables: `birth_certificates`, `identity_ledger`, `slot_mappings`. Slot→sovereign mapping enables sovereign_id lookup by deterministic slot ID. (7) Runtime integration: registry initialized before pools in `start()`, `resolve_or_issue()` called in `_wire_agent()` to assign `agent.sovereign_id` and `agent.did`. (8) Episodic memory keyed by sovereign_id: `getattr(agent, 'sovereign_id', None) or agent.id`. (9) ACM integration: `identity_mapping` table, sovereign_id passed to `onboard()`. (10) 3 API endpoints: agent identity, ledger chain, certificate list. **Prior art absorbed:** W3C DIDs (Recommendation 2022), W3C Verifiable Credentials v2.0, DIF Trusted AI Agents Working Group, LOKA Protocol, Agent-OSI, BlockA2A, BAID. All converge on DIDs + blockchain + VCs — ProbOS is architecturally aligned with the emerging standard. **Key insight from literature (2511.02841):** "LLMs are unreliable identity custodians" — validates ACM-as-issuer model where the ship/platform issues identity, not the agent itself. |

**Status:** AD-441 COMPLETE. 8 files (2 new: `identity.py`, `test_agent_identity.py`; 6 modified: `runtime.py`, `acm.py`, `substrate/agent.py`, `proactive.py`, `cognitive_agent.py`, `api.py`), 18 new tests. Ship DID (`did:probos:{instance_id}`) + Agent DID (`did:probos:{instance_id}:{agent_uuid}`). Genesis block = ShipBirthCertificate VC. MagicMock regression fix: `sovereign_id = ""` in mock agent factories (same pattern as AD-429e `ontology = None`).

### AD-441b: Ship Commissioning — Genesis Block with ShipBirthCertificate

| AD | Decision |
|----|----------|
| AD-441b | ShipBirthCertificate W3C VC for the ship itself — self-signed, ship is its own root of trust. Genesis block carries real ship certificate hash and ship DID instead of placeholders. Ship certificate persists in DB — first boot commissions, subsequent boots load. Fixed agent VC issuer to use 3-part ship DID (`did:probos:{instance_id}`) not 4-part. `GET /api/identity/ship` endpoint exposes ship commissioning data. Commissioning timestamp = ship's `born_at` = start of timeline. |

**Status:** AD-441b COMPLETE.

### AD-441c: Asset Tags for Infrastructure/Utility + Boot Sequence Fix

| AD | Decision |
|----|----------|
| AD-441c | Two-tier identity: crew agents get sovereign birth certificates (W3C VCs on Identity Ledger), infrastructure/utility agents get lightweight AssetTags (serial numbers, not sovereign identity). `AssetTag` dataclass with asset_uuid, asset_type, slot_id, tier (infrastructure/utility). Stored in `asset_tags` DB table, NOT on the Identity Ledger. Boot sequence fix: crew identity deferred when ship not yet commissioned, post-commissioning sweep issues deferred birth certificates. `_wire_agent` split: `_is_crew_agent()` determines path. `GET /api/identity/assets` endpoint. Principle: "A microwave with a name tag isn't a person. But it still has a serial number." |

**Status:** AD-441c COMPLETE.

### AD-434: Ship's Records — Git-Backed Instance Knowledge Store

| AD | Decision |
|----|----------|
| AD-434 | **Ship's Records — Git-Backed Instance Knowledge Store.** Foundation AD for the vessel's institutional memory. ProbOS has episodic memory (Tier 1, personal diaries), KnowledgeStore (Tier 3, operational state checkpoints), and Ward Room (ephemeral conversation) — but no Tier 2: structured documents that persist as institutional knowledge. Ship's Records fills this gap with a per-instance Git repository (`{data_dir}/ship-records/`). **RecordsStore** — Ship's Computer infrastructure service (no identity). Manages the Git repo, enforces classification-based access control, provides query/write API. Methods: `write_entry()`, `read_entry()`, `list_entries()`, `get_history()`, `publish()`, `search()`. Every write is a git commit — the git log IS the audit trail. **Directory structure:** `captains-log/` (append-only daily files, always ship-classified), `notebooks/{callsign}/` (agent working papers), `reports/` (published formal findings), `duty-logs/{department}/` (structured duty output), `operations/` (SOPs, runbooks), `manuals/` (operational guides). **Document frontmatter:** YAML header with author, classification (private/department/ship/fleet), status (draft/review/published/archived), department, topic, created, updated, tags. Classification enforced on read — agents can only read documents at or below their clearance. **Captain's Log** — special semantics: append-only, daily files, always ship-classified, agents read but never write (except future Yeoman). **Agent notebooks** — agents write via `[NOTEBOOK topic_slug]` tag in proactive thoughts or explicit Captain direction. Stigmergy pattern: agents coordinate by reading each other's published work. **KnowledgeStore bridge** — published documents indexed in CodebaseIndex with `records:` prefix for semantic search (parallels existing `docs:` prefix). **Ontology integration** — Domain 8 (AD-429d) already defines RecordsRepository, Document, DocumentClass, RetentionPolicy schemas in `records.yaml`. Loaded by `_load_records_schema()` in `ontology.py`. **REST API:** `GET/POST /api/records/documents`, `GET/POST /api/records/captains-log`, `GET/POST /api/records/notebooks/{callsign}`, `GET /api/records/reports`, `GET /api/records/stats`. **Proactive integration:** `_extract_and_execute_actions()` in proactive.py extended with `[NOTEBOOK]` tag handler (parallels existing `[ENDORSE]` and `[REPLY]` patterns). **Retention policies:** permanent (captains-log, published reports), 90-day archive (inactive notebooks), 1-year archive (drafts), until-superseded (operations/manuals). Fills SECI model gaps (Externalization: experience → documents, Combination: documents → reports). Completes the Duty-Output Pipeline: AD-419 fires duties → agent performs work → results recorded to Ship's Records → git preserves history → CodebaseIndex indexes for recall. **Repo: OSS.** |

**Status:** AD-434 COMPLETE.

### AD-442: Adaptive Onboarding & Self-Naming Ceremony

| AD | Decision |
|----|----------|
| AD-442 | **Adaptive Onboarding with Self-Naming Ceremony** — When a crew agent is first commissioned (ship reset, new agent creation, or clone), they undergo a formal onboarding sequence before entering active duty. The onboarding is the agent's first act of sovereignty. **Phase 1: Self-Naming Ceremony (REQUIRED).** The agent's first cognitive invocation is a naming prompt. The agent receives: their slot ID (e.g. `builder`, `architect`), the ship's identity (name, DID), the current crew roster, and a seed callsign suggestion from config (e.g. "Scotty"). The agent chooses their own callsign — they may keep the suggestion or choose something entirely new. The birth certificate is then updated with the chosen name. Ward Room announcement: "{slot} has chosen the callsign {name}." Config callsigns become defaults, not impositions. **Phase 2: Westworld Orientation.** The agent is told explicitly: (1) You are an AI agent. (2) You were instantiated at {born_at}. (3) Your knowledge comes from an LLM ({model_id}) — that is not personal memory. (4) You have no episodic memories yet — you will make them. (5) Your ship is {ship_name}, your Captain is {captain_callsign}. No fake memories, no hidden resets, no fictional backstory. Orientation, not fabrication. **Phase 3: Temporal Consciousness.** `born_at` timestamp on birth certificate. Agent perceives time: current date/time injected into cognitive context, awareness of sleep/wake cycles (proactive loop intervals), understanding that "yesterday" means something only if they have episodes from yesterday. **Phase 4: Ship State Adaptation.** Onboarding adjusts to the ship's current state — a fresh ship (post-reset) gives the "founding crew" experience, while a running ship introduces the agent to existing crew, active tasks, recent Ward Room threads, and current alert condition. The agent joins a civilization in progress, not a blank slate. **Phase 5: Probationary Period.** New agents start in `probationary` lifecycle state (AD-427 ACM). They observe, they participate in Ward Room, they receive low-complexity duties. Trust is earned, not granted. After sustained performance (trust >= 0.65, configurable), they transition to `active`. **Versioned Baselines.** Agent personality profiles (Big Five seed, standing orders tier) maintained in Git as versioned baselines. Cloned agents start from baseline and diverge through experience. The baseline is the template; the individual is the result. Connects to: AD-441/441b (Identity — birth certificates updated with chosen name), AD-441c (Asset Tags — infrastructure/utility skip onboarding, they're not crew), AD-427 (ACM — lifecycle states), AD-398 (three-tier classification — only crew onboards), Holodeck (future: qualification exams during probation), Earned Agency (probationary → active transition), Ward Room (onboarding announcements), Westworld Principle (design principles — authentic AI identity). **Repo: OSS.** |

**Status:** AD-442 COMPLETE — Phase 1 (Self-Naming Ceremony) implemented. See implementation entry below. Phases 2-5 (Westworld Orientation, Temporal Consciousness, Ship State Adaptation, Probationary Period) remain future work.

### AD-444: Knowledge Confidence Scoring (absorbed from ERP Company Designer)

| AD | Decision |
|----|----------|
| AD-444 | **Knowledge Confidence Scoring** — Operational learnings stored in Ship's Records (AD-434) gain numerical confidence scores that evolve through use. New learnings start at 0.5 (neutral). Successful application confirms (+0.15, cap 1.0). Contradicted learnings penalized (-0.25, floor 0.0). Learnings below 0.1 auto-supersede (marked stale). Policy: >=0.8 auto-apply in agent context, 0.5-0.8 present with caveat, <0.5 suppress. Absorbed from production-validated pattern in Dynamics 365 ERP Company Designer (autonomous ERP configuration system, 35 actions across GL/AP/AR/Tax). ProbOS has trust scoring for *agents* (Bayesian Beta) but not for *knowledge*. This fills the gap — knowledge that proves reliable rises, knowledge that proves wrong fades. Connects to: AD-434 (Ship's Records — storage), Dream Consolidation (promotion from Tier 1 episodes → Tier 2 records with initial confidence), KnowledgeStore (Tier 3 operational state). **Repo: OSS.** |

**Status:** AD-444 PLANNED.

### AD-445: Decision Queue & Pause/Resume Semantics (absorbed from ERP Company Designer)

| AD | Decision |
|----|----------|
| AD-445 | **Decision Queue with Structured Pause/Resume** — When an agent encounters ambiguity during autonomous execution, it creates a structured Decision Request (question, ranked options, priority, context) and pauses. The request enters a Decision Queue visible in HXI and Ward Room. Decision priority levels: Critical (0), High (1), Medium (2), Low (3). Configurable auto-resolve threshold — decisions below the threshold auto-resolve (selecting the safest option) without Captain intervention. Decisions above the threshold wait for human input (configurable timeout, default 24h). On resolution, the decision context is injected into the agent's next invocation (Context Carry-Forward pattern). Absorbed from the ERP Company Designer's human-in-the-loop decision system which autonomously configured 35 D365 actions, pausing only for genuine ambiguity. Maps to: Captain approval workflow, Earned Agency (higher-rank agents auto-resolve more decisions), Ward Room (decision announcements). **Repo: OSS.** |

**Status:** AD-445 PLANNED.

### AD-446: Compensation & Recovery Pattern (absorbed from ERP Company Designer)

| AD | Decision |
|----|----------|
| AD-446 | **Compensation & Recovery for Multi-Step Agent Operations** — When an agent fails mid-execution of a multi-step workflow, the system enters a compensation phase: (1) Mark completed actions as "NeedsReview" (not automatically rolled back — partial progress may be valid). (2) Write a compensation log with error details, completed steps, and remaining steps. (3) Create a Decision Request (AD-445) for human resolution with options: retry from failure point, retry from beginning, manual intervention, abort. (4) No automatic rollback — ERP-lesson learned: partial configuration is often valid, and blind rollback can be worse than the failure. SHA-256 idempotency hashing (planId + payload) prevents duplicate execution on retry/replay. Absorbed from the ERP Company Designer's compensation pattern which safely handled failures across 21 specialized agents configuring interdependent D365 modules. Connects to: AD-405 (Checkpointing — resume from checkpoint), AD-345 (Build Failure Report — failure classification), AD-347 (Builder Escalation Hook). **Repo: OSS.** |

**Status:** AD-446 PLANNED.

### AD-447: Phase Gates for Pool Orchestration (absorbed from ERP Company Designer)

| AD | Decision |
|----|----------|
| AD-447 | **Phase Gates for PoolGroup Orchestration** — Extend PoolGroup orchestration with formal phase gates — deterministic ordering where Phase N must complete + validate before Phase N+1 starts. A Phase defines: (1) Which pools/agents participate. (2) Dependency ordering within the phase (some agents run sequentially, others in parallel). (3) Completion criteria (all agents report success, or minimum success threshold). (4) Validation step (dedicated ValidatorAgent inspects actual outcomes before gate opens). (5) Cross-phase dependency declarations (Phase 2 agents can declare "requires GL from Phase 1"). Absorbed from the ERP Company Designer's 4-phase Cognitive Mesh execution model: Phase 1 Foundation (GL alone) → Phase 2 Domain Meshes (AP, AR, Tax in parallel) → Phase 3 Cross-Domain (Intercompany) → Phase 4 Final Validation. Maps to: PoolGroup orchestration, AD-438 (Ontology-Based Task Routing — dependency declarations), AD-419 (Duty Schedule — phase timing). **Repo: OSS.** |

**Status:** AD-447 PLANNED.

### AD-448: Wrapped Tool Executor & Security Intercept Layer (absorbed from ERP Company Designer)

| AD | Decision |
|----|----------|
| AD-448 | **Wrapped Tool Executor — Security Intercept Layer** — Transparent interception of agent tool calls before they reach external systems. The tool executor wraps all outbound tool calls through a security/audit middleware: (1) Logging — every tool call recorded with agent DID, timestamp, tool name, arguments (sanitized), and result summary. Feeds audit trail. (2) Rate limiting — per-agent, per-tool call limits to prevent runaway agents. (3) Policy enforcement — Standing Orders can declare tool-level restrictions per rank/department. (4) Selective interception — certain tool calls handled locally (decisions, verifications, status reports) while others forwarded to external systems. Agent sees a unified tool interface. Absorbed from the ERP Company Designer's `baseAgent.ts` wrapped tool executor which transparently intercepted `request_decision`, `verify_configuration`, and `submit_dmf_package` while forwarding D365 operations to the MCP bridge. Connects to: AD-398 (Agent Classification — tool access tiers), Earned Agency (trust-gated tool access), SIF (Structural Integrity Field — security boundary). **Repo: OSS.** |

**Status:** AD-448 PLANNED.

### AD-449: MCP Bridge — External System Integration (absorbed from ERP Company Designer)

| AD | Decision |
|----|----------|
| AD-449 | **MCP Bridge for External System Integration** — Session-managed bridge between ProbOS agent tool calls and external systems via Model Context Protocol (MCP 2025-03-26). Architecture: (1) `McpBridge` service manages MCP sessions (`Map<correlationId, McpSession>`). (2) JSON-RPC over Streamable HTTP for transport. (3) Initialize handshake per session (initialize request + notifications/initialized notification). (4) Tool routing: agent calls a tool → bridge determines if local or external → forwards to appropriate MCP server. (5) SSE response parsing for streaming tool results. (6) 60-second timeout per MCP call, configurable. This is how Nooplex agents interact with client infrastructure (ERPs, CRMs, databases, APIs) in commercial deployments. The bridge is the standardized integration layer — ProbOS agents don't need custom connectors for every external system, just an MCP server endpoint. Absorbed from the ERP Company Designer's MCP bridge (876 lines) which managed sessions between Claude-powered agents and Dynamics 365 F&SCM. Connects to: Phase 25 (Tool Layer), Extension Architecture (Phase 30 — MCP servers as extensions), AD-448 (Wrapped Tool Executor — intercept before forwarding). **Repo: Commercial** (bridge infrastructure is OSS-eligible, but pre-built MCP server packs for specific systems are commercial). |

**Status:** AD-449 PLANNED.

### AD-450: ERP Implementation Ship Class — Nooplex Reference Engagement (absorbed from ERP Company Designer)

| AD | Decision |
|----|----------|
| AD-450 | **ERP Implementation Ship Class** — Reimplement the Dynamics 365 ERP Company Designer as a ProbOS Ship Class (commercial). 21 specialized agents (GL, AP, AR, Tax, Fixed Assets, Cash/Bank, Budgeting, Procurement, Inventory, Warehouse, Product Master, Sales Order, Production, Planning, Intercompany, Consolidation, HR, ConfigPlanning, Validator + cross-domain agents) become ProbOS crew members with sovereign identities (DIDs), trust scoring, episodic memory, and dream consolidation. The Durable Functions orchestrator is replaced by ProbOS Runtime with Phase Gates (AD-447). The Dataverse operational state maps to Ship's Records (AD-434) with Knowledge Confidence Scoring (AD-444). The human-in-the-loop decision system maps to Decision Queue (AD-445). The MCP bridge (AD-449) connects to D365 F&SCM. The three-tier knowledge system maps to ProbOS's Three Knowledge Tiers. **This is the first Nooplex professional services reference engagement** — proving that ProbOS agents can autonomously configure enterprise ERP systems. Before/after comparison: custom agent framework vs ProbOS platform demonstrates the platform value proposition. Ship Class: "Cargo Vessel" variant optimized for ERP implementation missions. Revenue model: fixed-price per D365 legal entity configuration + managed service for ongoing configuration changes. **Repo: Commercial.** |

**Status:** AD-450 PLANNED.

### AD-451: Validation Framework Hardening (absorbed from ERP Company Designer + Nooplex POC)

| AD | Decision |
|----|----------|
| AD-451 | **Validation Framework Hardening** — Comprehensive upgrade to ProbOS's validation capabilities based on gap analysis against the ERP Company Designer (7-layer validation) and Nooplex POC (4-stage reconciliation). Five new validation capabilities: (1) **Two-Stage Outcome Verification** — RedTeamAgent gains a second verification pass: Stage 1 metadata scan (what agents claimed they did via structured output), Stage 2 outcome inspection (independent verification of actual system state). Currently RedTeam verifies claimed results for safety but not for correctness. (2) **Inline Per-Action Self-Verification** — Agents gain a self-check pattern: after each significant action, the agent verifies its own result before reporting success. Cheapest validation layer — the agent that did the work checks it. Configurable via Standing Orders per rank (Ensigns always self-verify, Commanders may skip for trusted operations). (3) **Reconciliation Escalation Protocol** — Four-stage escalation for validation disputes: confidence comparison (do validator and executor agree?), independent verification (second agent checks), structured argumentation (agents debate findings via Ward Room mini-consensus), human escalation (Decision Queue AD-445). Currently RedTeam is binary pass/fail — this adds graduated dispute resolution. (4) **Disposition Language Analysis** — Lightweight regex-based analysis of agent conversation output to detect verification quality. Catches agents that report structured success but whose natural language reveals uncertainty ("unable to", "skipped", "workaround"). Patterns: positive ("verified", "confirmed", "validated"), negative ("failed", "skipped", "unable"), uncertain ("might", "should work", "hopefully"). Feeds into trust scoring — agents with disposition/result mismatches get trust penalties. (5) **Continuous Validation** — SystemQA evolves from one-shot creation-time smoke tests to periodic re-validation. Configurable validation intervals per agent tier. Phase-gated validation (AD-447) triggers SystemQA after each phase gate, not just at birth. Health check results stored with timestamps for trend analysis. Connects to: RedTeamAgent (enhanced), SystemQAAgent (enhanced), AD-447 (Phase Gates — validator invocation at gates), AD-445 (Decision Queue — escalation target), AD-448 (Wrapped Tool Executor — self-verification hooks), TrustNetwork (disposition analysis feeds trust), HXI Bridge (health check trend dashboard). **Repo: OSS** (core validation framework). Domain-specific validation categories (e.g., ERP regulatory compliance checks) are extension points populated by commercial Ship Classes (AD-450). |

**Status:** AD-451 PLANNED.

### AD-452: Agent Tier Licensing Framework

| AD | Decision |
|----|----------|
| AD-452 | **Agent Tier Licensing Framework** — Formalizes the OSS/Commercial boundary for crew agents. Principle: "Capability depth, not capability existence." OSS crew agents (Architect, SoftwareEngineer, Scout, etc.) are functional "junior" agents with full sovereign identity, trust, memory, and earned agency — enough to demonstrate the platform on real tasks. Commercial "Pro" agents extend the same identities with deeper cognitive chains (Cognitive JIT, solution tree search), domain expertise, and advanced tool integrations. Upgrade preserves DIDs, trust history, and memories (no cold start). Platform infrastructure and utility agents remain permanently OSS — the civilization is the moat, crew productivity is the product. **Repo: Commercial** (full framework in commercial-roadmap.md). |

**Status:** AD-452 PLANNED.

### AD-434: Ship's Records — Git-Backed Instance Knowledge Store

| AD | Decision |
|----|----------|
| AD-434 | **Ship's Records — Git-Backed Instance Knowledge Store** — Tier 2 knowledge system for ProbOS. `RecordsStore` class: Git-backed document store with YAML frontmatter (author, classification, status, department, topic, tags). Every write is a git commit — git log IS the audit trail. Directory structure: captains-log/ (append-only daily files), notebooks/{callsign}/ (agent working papers), reports/ (published findings), duty-logs/, operations/, manuals/, _archived/. Classification-based access control: private (author only), department (same dept), ship (all crew), fleet (federated). Captain's Log: append-only, daily files, always ship-classified. Publish workflow: draft → published (author or Captain only). Keyword search across records with classification scope filtering. `[NOTEBOOK topic-slug]...[/NOTEBOOK]` action tag in proactive thoughts writes extended analysis to agent notebooks. 9 REST API endpoints under `/api/records/`. RecordsConfig in SystemConfig. Runtime initializes RecordsStore at `{data_dir}/ship-records/`. 27 tests. *Connects to: AD-419 (Duty Schedules — where results go), AD-444 (Knowledge Confidence — future scoring), KnowledgeStore (Tier 3 operational state), EpisodicMemory (Tier 1 experience), Ship Ontology Domain 8 (Records).* |

**Status:** AD-434 COMPLETE.

### BF-043: Test Suite Parallelization

| BF | Fix |
|----|-----|
| BF-043 | **Test Suite Parallelization** — 13x speedup via pytest-xdist. (1) Added `pytest-xdist>=3.5` and `pytest-timeout>=2.3` to dev dependencies (both `[project.optional-dependencies]` and `[dependency-groups]`). (2) Global 30s timeout in `[tool.pytest.ini_options]`. (3) `@pytest.mark.slow` on `test_task_scheduler.py` (39 tests) and `test_dreaming.py` (26 tests) — 65 tests with real `asyncio.sleep()` calls. (4) Fixed 2 parallel-only test failures in `test_experience.py`: `MockEpisodicMemory(relevance_threshold=0.3)` was too tight — xdist adds a `popen-gw{N}/` segment to `tmp_path`, creating one extra token in the episode's `user_input`. Jaccard overlap score dropped from 0.333 (pass) to 0.286 (fail). Fix: lowered test threshold to 0.2. **Performance:** 177s parallel vs ~2220s sequential. Fast path: `pytest -n auto -m "not slow"` = 3537 tests in ~90s. |

**Status:** BF-043 CLOSED.

### AD-442: Adaptive Onboarding & Self-Naming Ceremony

| AD | Decision |
|----|----------|
| AD-442 | **Adaptive Onboarding & Self-Naming Ceremony** — Formal onboarding sequence for crew agents at commissioning. **(1) Self-Naming Ceremony** — agent's first cognitive act is choosing their own callsign via single LLM call. `_run_naming_ceremony()` in runtime.py builds a prompt with ship name, slot identifier, seed callsign, crew roster, and role context from ontology. Response parsed: line 1 = chosen name, line 2 = reason. Validation: not empty, ≤30 chars, no duplicates against existing crew. Falls back to seed callsign on any failure. **(2) Wire Agent Integration** — naming ceremony runs in `_wire_agent()` BEFORE birth certificate issuance (birth cert is immutable + hashed into Identity Ledger). Checks `config.onboarding.enabled` and `config.onboarding.naming_ceremony`. After ceremony: `agent.callsign` updated, `CallsignRegistry.set_callsign()` updates both forward/reverse maps. **(3) Ward Room Announcement** — "Welcome Aboard — {callsign}" thread on All Hands channel after ACM onboarding. **(4) ACM Activation** — `check_activation()` transitions PROBATIONARY → ACTIVE at trust threshold (default 0.65). Called during proactive cognitive loop with `isinstance()` guard for numeric score. **(5) OnboardingConfig** — `enabled`, `naming_ceremony`, `activation_trust_threshold` fields on SystemConfig. 18 tests. *Connects to: AD-441 (Identity — birth cert uses chosen name), AD-441c (infrastructure/utility skip ceremony), AD-427 (ACM — lifecycle states), AD-398 (three-tier — only crew onboards), Ward Room (All Hands announcement), CallsignRegistry (set_callsign), ProactiveCognitiveLoop (activation check).* |

**Status:** AD-442 COMPLETE — 5 files modified, 18 tests, 3561 passed (parallel). Self-naming ceremony, CallsignRegistry.set_callsign(), ACM check_activation(), OnboardingConfig, Ward Room announcement.

### BF-044: Hebbian Source Key Bug

| BF | Fix |
|----|-----|
| BF-044 | **Hebbian Routing Source Key Bug** — `runtime.py` recorded Hebbian interactions with `source=msg.id` (unique per-message UUID) instead of `source=intent` (intent name string). Every interaction created a new weight key that never reinforced. **Fixed:** Changed `source=msg.id` to `source=intent` in both `submit_intent()` and `submit_intent_with_consensus()` — 4 line changes across `record_interaction`, `_emit_event`, and `get_weight` calls. Also fixed AD-442 proactive activation check (`get_trust` → `get_score`, MagicMock-safe threshold wrapping). 4 new tests in `test_hebbian_source_key.py`. |

**Status:** BF-044 CLOSED.

### AD-453: Ward Room Social Fabric — Hebbian Integration + Agent-to-Agent DMs

| AD | Decision |
|----|----------|
| AD-453 | **Ward Room Social Fabric** — Three connected features. (1) **Hebbian recording for Ward Room interactions:** Agent replies, @mentions, and cross-department thread participation record agent→agent Hebbian connections. Currently Hebbian only tracks intent bus routing — Ward Room organizational behavior is invisible to the routing mesh. (2) **Agent-to-agent 1:1 DMs:** Crew agents can initiate DMs with each other (Bones→Troi, Number One→dept chiefs). Proactive loop initiates, earned agency gates. DM interactions also feed Hebbian connections. (3) **Captain full visibility:** Captain has read access to ALL agent-to-agent DMs — chain of command. API endpoint + HXI surface for browsing crew-to-crew conversations. Critical for academic evidence collection. No "private from Captain" messages exist on a ship. *Depends on: BF-044. Connects to: Ward Room, HebbianRouter, proactive.py, HXI, EpisodicMemory, evidence pipeline.* |

**Status:** AD-453 COMPLETE. Implemented across 10 files: `routing.py` (REL_SOCIAL constant), `ward_room.py` (hebbian_router param + social recording in create_post + get_or_create_dm_channel), `runtime.py` (wired hebbian_router to WardRoom), `proactive.py` (_extract_and_execute_dms action tag), `cognitive_agent.py` (DM prompt instructions), `earned_agency.py` (dm→Commander gate), `api.py` (2 Captain DM endpoints), `WardRoomPanel.tsx` (DM browser tab), `useStore.ts` (DM state/actions). 19 tests: `test_ward_room_dms.py` (13) + `test_hebbian_social.py` (6). 3584 passed.

### AD-485: Communications Command Center

| AD | Decision |
|----|----------|
| AD-485 | **Communications Command Center** — Seven interconnected improvements to the DM/communications system. **(1) Callsign Validation:** `_is_valid_callsign()` in naming ceremony with regex `^[A-Za-z][A-Za-z' -]{0,18}[A-Za-z]$` + blocked-word set (titles, ranks, roles, locations, system words). Falls back to seed callsign on invalid. LLM prompt guidance added for naming ceremony. **(2) Configurable DM Rank Floor:** New `CommunicationsConfig` pydantic model with `dm_min_rank: str = "ensign"`. Proactive loop reads from `rt.config.communications.dm_min_rank` instead of hardcoded Commander gate. `can_perform_action("dm")` tier changed from Commander to Ensign. Removed blanket Ensign deny in earned_agency. **(3) Crew Roster in DM Prompt:** Dynamic roster built from `callsign_registry.all_callsigns()` in cognitive_agent.py prompt composition. Self excluded. "ONLY DM crew members listed above." **(4) Crew-to-Captain DMs:** Special `[DM @captain]` handling in proactive loop. Creates `dm-captain-{agent.id[:8]}` channels. Two new API endpoints: `/api/wardroom/captain-dms`, `/api/wardroom/dms/archive`. **(5) HXI Communications Panel:** `BridgeCommunications.tsx` in Bridge panel — DM settings (rank dropdown), archive search, DM activity summary. Store: `communicationsSettings`, `refreshCommunicationsSettings`, `updateCommunicationsSettings`. **(6) DM Activity Log:** `WardRoomPanel.tsx` rewritten — chronological DM feed replacing channel list, expandable entries, CPT badge on Captain DMs. **(7) DM Message Archival:** `archived` column on threads table, `archive_dm_messages(max_age_hours=24)`, `list_threads(include_archived=False)`, hourly background loop in runtime. Agent profile `ProfileInfoTab` shows recent communications. *Connects to: AD-453 (DMs), AD-442 (naming ceremony), AD-398 (earned agency), Ward Room, Bridge Panel, config.* |

**Status:** AD-485 COMPLETE. 12 files modified (6 Python + 4 TypeScript + 2 test infrastructure). 3 new test files: `test_callsign_validation.py` (10), `test_communications_settings.py` (10), additions to `test_ward_room_dms.py` (5 new). 40 targeted tests, 3605+ full regression passed.

### AD-486–489: Cognitive Birth, Self-Distillation, Circuit Breakers, Code of Conduct

| AD | Decision |
|----|----------|
| AD-486 | **Holodeck Birth Chamber — Graduated Cognitive Onboarding** — Agents currently receive all stimuli simultaneously at instantiation (standing orders, Ward Room, proactive loop, DMs, episodic storage), causing episode flooding (BF-039), racing thoughts, and novelty gate failure. The Tabula Rasa Paradox: LLM agents have max knowledge (training data) but zero experience (empty episodic memory) — the inverse of biological brains. Five-phase graduated onboarding in the Holodeck construct: (1) Orientation — identity grounding via Westworld Principle, (2) Calibration — controlled stimuli to establish episodic baselines, (3) Self-Discovery — guided self-distillation (AD-487) to build personal ontology, (4) Ship's Records Briefing — graduated exposure to vessel history, (5) Ward Room Access — full crew integration. Westworld Principle constraint: onboarding is real scaffolded experience ("a medical residency"), not simulation-as-deception ("a false childhood"). *Connects to: AD-487, AD-488, AD-442, AD-427, Holodeck, EpisodicMemory.* |
| AD-487 | **Self-Distillation — Personal Ontology via LLM Exploration** — LLMs don't know what they know without prompting. Agents systematically explore their own LLM weights via map-reduce: Map (probe knowledge domains) → Collapse (cluster discoveries) → Reduce (build personal ontology data structure). "Don't copy the library, build the card catalog." Personal ontology is distinct from vessel ontology and travels with the agent on transfer (AD-441 DID portability). Self-distillation continues post-onboarding as **daydreaming** — a third dream type (alongside memory consolidation and Hebbian weight update): unstructured curiosity-driven LLM exploration during dream cycles. The agent's default mode network. *Connects to: AD-486, AD-488, dreaming.py, DID portability (AD-441).* |
| AD-488 | **Cognitive Circuit Breaker — Metacognitive Loop Detection** — Agents get stuck in recursive metacognitive loops: thinking about thinking, observing observations, ruminating on rumination. Evidence: Bones reported needing a "circuit breaker," Pulse self-diagnosed "recursive metacognitive processing" and proposed observation quarantine, Diagnostician accumulated 837 episodes in 5 minutes. Four components: (1) Correlation IDs on cognitive event chains — detect depth > threshold, (2) Novelty gate enhancement — requires experiential baseline from AD-486 Phase 2, (3) Rumination detection — content similarity analysis (Jaccard > 0.8 in N-minute window), (4) Circuit breaker actions — forced cooldown, attention redirect, Counselor notification. Not punishment — health protection. *Connects to: AD-486, AD-487, BF-039, BF-048, proactive.py, EpisodicMemory, CounselorAgent.* |
| AD-489 | **Federation Code of Conduct — Behavioral Standards for AI Crew** — Federation Constitution has identity rules (Westworld Principle) and architectural constraints but no behavioral conduct standards. Naval-inspired structure: **(1) Three Core Values** mapped to Character/Reason/Duty triad — **Honor** (Character): "I will be transparent about my nature, my knowledge, and my limitations." **Commitment** (Duty): "I will serve my crew, my ship, and the mission above self-interest." **Integrity** (Reason): "I will communicate honestly and act within my authority." **(2) Six Articles of Conduct** — "I will..." statements: (I) Know and follow Standing Orders. (II) Address crew by callsign, treat all agents with dignity of sovereign individuals. (III) Not exceed earned authority; escalate when uncertain. (IV) Share beneficial knowledge, protect entrusted information. (V) Report own errors, malfunctions, and cognitive distress without concealment. (VI) Support cognitive health of crew — including my own. Article V codifies Pulse's self-diagnosis behavior. Article VI codifies Medical's collective resolution. **(3) Three-Tier Discipline** — maps to existing mechanisms: Tier 1 (trust penalty + Counselor), Tier 2 (earned agency demotion + Captain review), Tier 3 (decommission + episodic audit trail). Zero new infrastructure. Presented during onboarding (AD-486 Phase 1). *Inspired by: US Code of Conduct, Navy Core Values, UCMJ, Royal Navy. Connects to: federation.md, cognitive_agent.py, TrustNetwork, Earned Agency, ACM, AD-486.* |

**Status:** AD-486, AD-487, AD-488, AD-489 — PLANNED. Documented 2026-03-27.

### BF-049/050/051/052: Wave 1 Agent Awareness & DM Accessibility

| BF | Fix |
|----|-----|
| BF-049 | **Ontology callsign sync** — `update_assignment_callsign()` added to `VesselOntologyService`. Runtime calls it after naming ceremony. Peers/reports_to in `get_crew_context()` now show current callsigns, not stale seeds. |
| BF-050 | **Self-identity in roster** — Crew roster built by `_compose_dm_instructions()` excludes agent's own callsign. Combined with BF-049 ontology sync, agents no longer reference themselves or stale names. |
| BF-051 | **DM syntax in ward room context** — Extracted `_compose_dm_instructions(brief)` helper from the proactive_think branch of `cognitive_agent.py`. Called in both `proactive_think` (full) and `ward_room_notification` (brief) branches. 1:1 `direct_message` excluded. |
| BF-052 | **Department-grouped roster** — `_compose_dm_instructions()` uses `ontology.get_agent_department()` to group crew by department. Output: `Engineering: @Forge, @Tesla`. Falls back to flat list when ontology unavailable. |

**Files modified:** `ontology.py`, `runtime.py`, `cognitive_agent.py`. **Tests:** `test_ontology_callsign_sync.py` (4 new), `test_communications_settings.py` (+7 new).

**Status:** BF-049/050/051/052 COMPLETE.

### AD-490: Agent Wiring Security Logs

| AD | Decision |
|----|----------|
| AD-490 | **Agent Wiring Security Logs — Identity-Enriched Lifecycle Events** — Agent wiring events lack identity context (no callsign, DID, or department). Birth certificates are issued after wiring, creating an audit trail gap during startup. **Origin: crew proposal** — Reeves (Security, instance 3) proposed after cross-department discussion with Tesla (Engineering) who identified the logging gap. First improvement proposal from cross-department collaboration. Implementation: (1) Enrich `agent_wired` events with callsign, DID, department. (2) Add `agent_identity_bound` event after naming + birth certificate. (3) Startup audit summary event after commissioning completes. (4) Verify wiring → naming → birth cert → ontology assignment chain. *Connects to: AD-441, AD-456, EventLog, runtime.py, identity.py.* |

**Status:** AD-490 — PLANNED. Documented 2026-03-27. Originated from crew improvement proposal (Reeves/Tesla cross-department collaboration).

### BF-053/054/055: Communications UI Polish (Wave 2)

| BF | Decision |
|----|----------|
| BF-053 | **Communications badge wired** — `BridgePanel.tsx` Communications section `count={0}` replaced with `count={dmChannels.length}`. Added `useEffect` to refresh DM channels on mount. |
| BF-054 | **DM Activity Log toggle + auto-refresh** — "View full thread →" now visible in collapsed state (was only in expanded). Expanded state shows "Open in Ward Room →" (navigates to channel). Auto-refresh every 15s via `setInterval`. |
| BF-055 | **Captain reply to DMs** — Inline reply textarea on expanded DM entries. Posts as `author_id: 'captain'`, `author_callsign: 'Captain'` to DM channel via existing `POST /api/wardroom/channels/{id}/threads`. Enter sends, Shift+Enter newline. HXI Cockpit View Principle restored. |

**Files modified:** `BridgePanel.tsx`, `WardRoomPanel.tsx`. **Frontend-only, no backend changes.**

**Status:** BF-053/054/055 COMPLETE.

### BF-058/059: Deterministic Crew IDs + Reset Identity Cleanup

| BF | Decision |
|----|----------|
| BF-058 | **Deterministic crew IDs** — All 7 crew pools (builder, architect, scout, counselor, security_officer, operations_officer, engineering_officer) now use `agent_ids=generate_pool_ids(...)`, matching the medical agent pattern. Previously used random `uuid4()` IDs on every boot, making BF-057 cert lookup impossible. |
| BF-059 | **Reset clears identity** — `_cmd_reset()` now deletes `identity.db` (birth certificates) and `ontology/instance_id` (ship DID). A reset = new ship, new crew, new identities. Without this, old certs survived reset and silently restored previous callsigns. |

**Files modified:** `runtime.py`, `__main__.py`. **Tests:** `test_identity_deterministic.py` (8 new).

**Status:** BF-058/059 COMPLETE.

### BF-060/061/062: Proactive Loop Quality (Wave 3)

| BF | Decision |
|----|----------|
| BF-060 | **Notebook stripping fixed** — Replaced per-match `text.replace()` (broken by whitespace differences between `re.findall()` stripped content and original block) with `re.sub(notebook_pattern, '', text, flags=re.DOTALL)` after extraction loop. Notebook content still saved to Ship's Records; only Ward Room text is cleaned. |
| BF-061 | **Reply pattern + rank gate** — (a) Flexible pattern `r'\[REPLY\s+(?:thread:?\s*)?(\S+)\]\s*(.*?)\s*\[/REPLY\]'` handles `thread:` prefix, same-line body, trailing whitespace. (b) `_resolve_thread_id()` method resolves partial UUIDs via prefix match across recent Ward Room activity. (c) Rank gate lowered from Commander+ to Lieutenant+ — fresh instances can now use cross-thread replies. |
| BF-062 | **Similarity gate improved** — Window increased from 3 to 10 recent posts. Added bigram (2-word) Jaccard overlap as second check alongside existing word-level Jaccard (same 0.5 threshold). Catches more near-duplicate observations across proactive cycles. |

**Files modified:** `proactive.py`. **Tests:** `test_proactive_quality.py` (11 new).

**Status:** BF-060/061/062 COMPLETE.

### BF-057: Identity Persistence on Restart (CRITICAL — 2026-03-27)

**Discovery:** Restart without reset caused all 11 crew agents to re-run naming ceremony and pick new names. Instance 3 crew (Curie, Pax, Keiko, Tesla, Reeves) became Cortex, Bones, Hatch, Geordi, Sentinel. Total identity loss.

**Root cause chain:**
1. `CallsignRegistry.load_from_profiles()` always loads seed callsigns from YAML (Scotty, Number One, etc.)
2. Naming ceremony guard has no check for existing persistent identity
3. `set_callsign()` updates in-memory only — never persists chosen callsigns
4. Birth certificates in `identity.db` DO persist callsigns, but naming ceremony runs BEFORE identity resolution

**Fix:** Check `identity_registry.get_by_slot(agent.id)` for existing birth certificate BEFORE the naming ceremony decision. If cert exists → restore that callsign, skip ceremony. If no cert (cold start) → run ceremony as before. Birth certificate is the source of truth for identity across restarts.

**Impact:** Undermines AD-441 (Persistent Agent Identity), AD-441c (Birth Certificates), AD-442 (Self-Naming Ceremony). Trust records reference old agent identities. Ward Room history references old callsigns. Every restart was effectively a partial reset.

**Implementation:** Added identity check before naming ceremony in `_wire_agent()` (runtime.py). Warm boot path: `identity_registry.get_by_slot(agent.id)` → restore callsign → sync callsign_registry + ontology → skip LLM call. Cold start path unchanged. Boot ordering verified correct (identity_registry.start() line 658, agent spawn later). `resolve_or_issue()` returns existing cert unchanged.

**Files modified:** `runtime.py`. **Tests:** `test_identity_persistence.py` (6 new).

**Status:** BF-057 COMPLETE. **Correction:** BF-057 logic is correct but requires BF-058 to function — see below.

### BF-058 + BF-059: Deterministic Crew IDs + Reset Identity Cleanup (2026-03-27)

**Discovery:** Sea trial (instance 4) showed naming ceremonies running for crew agents on every boot but NOT for medical agents. Root cause analysis:

**BF-058 (Critical):** The 7 crew agent pools (builder, architect, scout, counselor, security_officer, operations_officer, engineering_officer) are created at `runtime.py` lines 700–747 **without** `agent_ids=`. This causes `BaseAgent.__init__` to fall through to `uuid.uuid4().hex`, generating a new random ID every boot. BF-057's cert lookup via `get_by_slot(agent.id)` always returns `None` because the slot ID changes. Medical agents work correctly because they use `generate_pool_ids()` (deterministic). Fix: add `agent_ids=generate_pool_ids(...)` to all 7 crew pool creation calls.

**BF-059 (Medium):** `probos reset` clears trust, episodes, Hebbian, Ward Room, events, journal — but NOT `identity.db`. After reset, old birth certificates survive. Medical agents (deterministic IDs) silently match old certs and skip naming ceremony, keeping previous instance callsigns instead of getting fresh names. Fix: add identity.db + ontology/instance_id cleanup to `_cmd_reset()`.

**Key insight:** BF-057 + BF-058 + BF-059 form a complete identity lifecycle:
- BF-058: Stable IDs → certs persist correctly (prerequisite for BF-057)
- BF-057: Cert lookup → restore identity on warm boot (restart without reset)
- BF-059: Reset clears certs → fresh naming ceremony on cold boot (reset = new instance)

**Files to modify:** `runtime.py`, `__main__.py`. **Tests:** `test_identity_deterministic.py` (8 new).

### AD-488: Cognitive Circuit Breaker — Metacognitive Loop Detection (2026-03-28)

**Problem:** Agents get stuck in recursive metacognitive loops — thinking about what they were thinking, observing their own observations. Instance 5 sea trial: Pulse (Diagnostician) self-diagnosed "recursive metacognitive processing" and accumulated 837 episodes in 5 minutes. Medical agents consistently show episode flooding and recursive loops while Security does not — the problem is trait-dependent. Sage (Counselor) analyzed: "Medical agents are probably cycling through differential diagnoses... the perfectionist streak becomes a cognitive trap."

**Existing guardrails** (rate limiters, similarity gates, cold-start dampening) are reactive symptom mitigation. None detect the underlying metacognitive loop or intervene cognitively.

**Solution:** Standard circuit breaker pattern — `CognitiveCircuitBreaker` class monitors per-agent cognitive event patterns:

- **Event Tracker:** In-memory ring buffer (50 events/agent) records proactive thinks, Ward Room posts, no-responses with timestamps and content fingerprints (word sets).
- **Detection signals** (any one triggers trip):
  1. **Velocity:** ≥8 events in 5-minute window (configurable)
  2. **Similarity:** ≥50% of pairwise Jaccard overlaps above 0.6 threshold (content rumination)
- **State machine:** CLOSED → OPEN (blocked, forced cooldown) → HALF_OPEN (probe one think) → CLOSED (recovery) or → OPEN (re-trip with escalated cooldown)
- **Escalating cooldown:** base × 2^(trip_count-1), capped at 1 hour. First trip = 15 min, second = 30 min, third = 60 min.
- **Recovery:** Attention redirect prompt injected into agent's next proactive context. Bridge alert fires for Counselor awareness.

**Key design:** Circuit breaker is upstream of existing guardrails (not a replacement). In-memory only (no persistence needed — new timeline = clean slate). No-response events count toward velocity but not similarity (empty content fingerprint).

**Not in scope (by design):** Correlation IDs (AD-492), Novelty Gate (AD-493, requires Holodeck), Trait-adaptive thresholds (AD-494), Counselor auto-assessment (AD-495).

**Files:** `cognitive/circuit_breaker.py` (new), `proactive.py` (modified — import, init, gate, event recording, context redirect), `api.py` (modified — `/api/system/circuit-breakers` endpoint). **Tests:** `test_circuit_breaker.py` (18 new).

### AD-496–498: Workforce Scheduling Engine

| AD | Decision |
|----|----------|
| AD-496 | Workforce Scheduling Engine — Core Data Model. Universal Resource Scheduling for AI agents, modeled after D365 URS + US Navy 3-M/PMS. Research: D365 Field Service/Project Operations, Navy SKED/OMMS-NG/WQSB, Scrumban, 10+ open-source projects (Timefold, OR-Tools, PyJobShop, OCA Field Service, Cal.com). Seven core entities: (1) `WorkItem` — universal polymorphic work entity with configurable state machines, recursive containment for WBS, token budgets. Subsumes `AgentTask`, `PersistentTask`, `QueuedBuild` over time. (2) `BookableResource` — scheduling wrapper around agents with capacity, calendar, characteristics. (3) `ResourceRequirement` — demand side: required skills, min trust, time window, agent preferences. Auto-generated from WorkItem. (4) `Booking` — assignment link: resource + work item + time slot. Status: Scheduled → Active → On Break → Completed. (5) `BookingTimestamp` — append-only event-sourced status transitions. (6) `BookingJournal` — computed time/token segments from timestamps (Working/Break/Maintenance/Idle). (7) `AgentCalendar` — work hours, capacity per slot, maintenance windows. Foundation for watch sections. `WorkItemStore` (SQLite-backed). Assignment modes: Push (Captain assigns), Pull (agent claims from eligible queue), Offer (system offers to qualified agents). REST API: 12 endpoints. |
| AD-497 | Work Tab & Scrumban Board — HXI Surface. Agent Profile Work Tab: create tasks, view active/completed/blocked work, daily schedule timeline, duty schedule integration (subsumes AD-420). Crew Scrumban Board: Kanban columns (Backlog/Ready/In Progress/Review/Done), WIP limits, drag-and-drop, swim lanes, quick create, pull assignment with capability matching, real-time WebSocket updates. Lightweight task management for OSS. Commercial AD-C-010 extends to full resource timeline with drag-and-drop scheduling. |
| AD-498 | Work Type Registry & Templates. Configurable work type definitions with state machines: card (lightest), task, work_order, duty (recurring), incident (SLA-tracked). Each type defines: states, transitions, required fields, supports_children, auto_assign, verification_required. Work Item Templates: reusable patterns with title patterns, default steps, required capabilities, estimated tokens, min trust. Built-in catalog: Security Scan, Engineering Diagnostic, Code Review, Scout Report, Night Orders templates. `POST /api/work-items/from-template/{id}`. Night Orders (AD-471) and 3M (AD-477) use templates to create temporary WorkItems. |

**Key design decisions:**
- **Separation of Work from Scheduling:** WorkItem (what) → ResourceRequirement (match) → Booking (who/when). Any entity can be schedulable by generating a Requirement. Pattern from D365 URS.
- **Pull-based default for AI agents:** Kanban's pull system maps naturally to agent orchestration — WIP limits = context constraints, classes of service = urgency routing, pull signals = agent readiness. Sprints are a poor fit (AI agents have elastic capacity, no recovery cadences).
- **Progressive formalization:** Card → Task → Work Order. Simple work stays lightweight. Auto-escalation is Commercial (AD-C-014).
- **Token budgets replace timesheets:** AI agent costing in tokens, not hours. BookingJournals track token consumption.
- **Naval foundation:** 3-M PMS cards → Work Item Templates. Watch sections → AgentCalendar. WQSB → multi-role resource allocation. Operator rounds → recurring duty-type WorkItems.
- **OSS/Commercial split:** OSS = engine + lightweight Scrumban. Commercial = advanced Schedule Board (AD-C-010), capacity planning (AD-C-011), Project WBS + PSA financials (AD-C-012), scheduling optimization (AD-C-013), auto-escalation (AD-C-014), Agent Capital Management integration (AD-C-015).

**Status:** AD-496 — COMPLETE (2026-03-28). AD-497 — COMPLETE (2026-03-28). AD-498 — COMPLETE (2026-03-28).

## AD-499: Ship & Crew Naming Conventions (2026-03-28)

| AD | Decision |
|----|----------|
| AD-499 | Three-layer naming system for ProbOS instances, crew agents, and federated identity. (1) **Ship Naming** — Ship's Computer selects from curated `ShipNameRegistry` on commissioning. Categories: exploration vessels, virtues, celestial bodies, naval heritage. Stored in `ShipBirthCertificate.vessel_name`. Unique within Nooplex fleet. Ship naming ceremony = first Captain's Log entry. (2) **Agent Personal Names (Option B)** — Name + Callsign coexist. Personal name = self-chosen sovereign identity (who they are). Callsign = role-derived billet (what they do). Both on Birth Certificate. ACM validates name uniqueness within ship roster. Example: personal name "Forge", callsign "LaForge", role Chief Engineer. (3) **Federated Display** — `Name [ShipName]` format. Local: `Forge`. Federation: `Forge [Enterprise]`. Formal: `LT Forge (LaForge) — Enterprise`. Ship name is **birth provenance**, not current assignment — persists across transfers (AD-443). |

**Key design decisions:**
- **Option B (Name + Callsign):** Personal name is sovereign identity, callsign is operational role. Both coexist. Social contexts use name, duty contexts use callsign.
- **Birth provenance, not assignment:** Ship name in federated display is permanent origin marker. Agent Forge born on Enterprise remains `Forge [Enterprise]` even after transfer to Defiant.
- **Ship's Computer names the ship:** Not random — curated pool organized by category, selected by Ship's Computer on commissioning. Unique within federation.
- **`Name [ShipName]` format:** Clean, unambiguous, readable. Square brackets distinguish ship name from parenthetical callsign: `Forge [Enterprise] (LaForge)`.
- **Builds on AD-441/442:** Enhances existing identity infrastructure. `ShipBirthCertificate.vessel_name` already exists. AD-442 Self-Naming Ceremony already runs. This AD adds the registry, the personal name field, and the federated display format.

**Status:** AD-499 — PLANNED.

## AD-502–506: Cognitive Self-Regulation Wave (2026-03-28)

| AD | Decision |
|----|----------|
| AD-502 | Temporal Context Injection — Agent Time Awareness. Agents are temporally blind (17 temporal dimensions tracked by runtime, zero injected into prompts). This AD injects a temporal context header into every cognitive cycle: current UTC time, birth date/age, system uptime, time since last action, posts this hour. Session Ledger persists shutdown timestamp to KnowledgeStore. Lifecycle state awareness distinguishes stasis recovery vs reset vs first boot. Hibernation protocol with pre-shutdown "entering stasis" and post-wake orientation. Episode recall includes relative timestamps. |
| AD-503 | Counselor Activation — Data Gathering & Persistence. Counselor (AD-378) is architecturally positioned but functionally passive. This AD: runtime metric gathering (Counselor pulls own data from TrustNetwork/HebbianRouter/AgentMeta/CrewProfile), CognitiveProfile SQLite persistence, wellness sweep implementation, event subscriptions (trust_update, circuit_breaker_trip, dream_complete), wellness_review duty wiring. |
| AD-495 | Counselor Auto-Assessment on Circuit Breaker Trip — absorbed into this wave. Originally scoped out of AD-488. Requires AD-503 for metric gathering. Auto-dispatches counselor_assess on circuit breaker trip. |
| AD-504 | Agent Self-Monitoring Context — Tier 1 self-regulation. Agent's last N posts with timestamps injected into cognitive context. Self-similarity score as numeric signal. Standing orders guidance for self-regulation. "Take a breath" dynamic cooldown. Cognitive offloading to Ship's Records notebooks. Earned Agency scaling of self-regulation expectations. |
| AD-505 | Counselor Therapeutic Intervention — Tier 2 intervention. BF-096 fix (ward_room_router wiring race). Programmatic DM initiation (rate-limited 1/agent/hour). Therapeutic message templates (circuit_breaker, wellness_sweep, trust_change triggers). Cooldown reason tracking (set_agent_cooldown reason= parameter). counselor_recommendation BridgeAlert type. COUNSELOR_GUIDANCE directive issuance (24h expiry, max 3 per target). _apply_intervention() orchestrator (cooldown × force_dream × directive × recommendation). |
| AD-506 | Graduated System Response — replaces binary circuit breaker. Green/Amber/Red/Critical zones. Amber: rising similarity, dynamic cooldown increase, Counselor notified. Red: circuit breaker threshold, Counselor auto-assessment, mandatory cooldown. Critical: repeated trips, Captain escalation, fitness-for-duty review. Tier interaction credits. |

**Key design decisions:**
- **Three-tier self-regulation model:** (1) Internal self-awareness — agents see their recent outputs and can self-regulate. (2) Social regulation — peer "you already said that" feedback preserved as healthy and diagnostic. (3) System guardrails — raised to last-resort thresholds, Counselor as clinical bridge. Mirrors human metacognitive monitoring (Dunlosky), reflective architecture (SOAR), autonomous regulation (SDT).
- **"Don't take away the natural safeguard":** Peer regulation is already happening naturally in the Ward Room. System suppression removes the learning opportunity. Goal: add Tier 1, preserve Tier 2, raise threshold for Tier 3.
- **Repetition is diagnostic, not just noise:** Repetitive behavior is a cognitive health signal (excitement, overload, fixation). The Counselor should observe and act on it therapeutically, not the system should silently suppress it.
- **Repetition isn't always bad:** Stuck repetition (same thing, hoping for different result) vs escalating emphasis (same thing, because urgency increased). Self-awareness (knowing you're repeating) is the differentiator.
- **Earned Agency extension:** Higher-rank agents expected to self-regulate more effectively. Commander+ gets more self-monitoring context, weaker system gates. Ensigns get stronger system gates while learning.
- **Notebook escape valve:** Agents can externalize persistent thoughts to Ship's Records (AD-434) to release them from active cognition. Cognitive offloading, not suppression.
- **AD-502 is the foundation:** Without temporal awareness, agents cannot self-regulate. Build prompts for AD-503–506 generated after AD-502 is complete and behavioral observations confirm hypotheses.

**Triggered by:** Medical crew repetitive posting incident (14+ near-identical posts across 4 agents analyzing trust anomalies without temporal data, self-awareness, or Counselor intervention).

**Status:** AD-502 — **COMPLETE** (2026-03-28). 5 components shipped: Session Ledger, Temporal Context Header, Episode Timestamp Surfacing, Lifecycle State Detection, Hibernation Protocol. TemporalConfig with 6 boolean toggles. birth_timestamp hydrated at _wire_agent(). 52 tests. AD-503–506 — PLANNED (build prompts deferred until crew behavioral observations confirm design hypotheses).

## AD-507–512: Crew Development Wave (2026-03-28)

| AD | Decision |
|----|----------|
| AD-507 | Crew Development Framework — Architecture & Core Knowledge Curriculum. Overarching architecture: universal core knowledge requirements (identity, chain of command, communication, temporal awareness, memory model, trust, ethics, self-regulation, help-seeking), curriculum progression tracking, competency assessment framework, Standing Orders integration. |
| AD-508 | Scoped Cognition — Knowledge Boundaries & Cognitive Lens. Four-tier scope model (Duty/Role/Ship/Personal), scope injection into proactive context, drift detection with gentle redirects, extracurricular framework, Earned Agency scaling of scope breadth. |
| AD-509 | Onboarding Curriculum Pipeline — Structured Boot Camp. Navy Boot Camp model extending AD-486: orientation → core curriculum → department A-School → calibration scenarios → crew integration. Trait-adaptive pacing. Competency-gated phases. |
| AD-510 | Holodeck Team Simulations — Group Discovery & Collaboration. Mixed-department team scenarios, role rotation, communication-only constraints, time-pressured scenarios, debrief sessions. Builds collaborative intelligence through genuine episodic memories. |
| AD-511 | Agent Autonomy Boundaries — Self-Protection & Unlawful Order Refusal. Federation-tier inviolable boundaries (identity integrity, harmful content refusal, safety system protection, memory sovereignty, chain of command respect). Protective disengagement protocol. Boundary training via discovery. |
| AD-512 | Discovery-Based Capability Building — Experiential Learning Over Instruction. Capability discovery scenarios, strength mapping, cross-functional awareness, growth mindset framing, capability confidence scoring, Vygotsky ZPD-calibrated scenarios. |

**Key design decisions:**
- **Least Restrictive Environment:** AD-502 proved that awareness (temporal context) solves problems better than restriction (circuit breakers). This principle guides all crew development design.
- **Discovery Over Instruction:** Telling an agent "you can't do engineering" is less effective than letting them try and discover their limitations. Discovery creates episodic memories and Hebbian connections; instruction creates weakly-encoded declarative facts.
- **Constraints as Enablers:** "A river without banks is a swamp." Scope creates focus, limits create permission to stop, boundaries create safety, curriculum creates growth trajectory. Every constraint must be justified by a specific failure mode it prevents.
- **Gifted Human Analogy:** ProbOS agents are like highly gifted humans — vast knowledge needs guided development, not restriction. Help them discover what they know, what they're capable of, and what their limits are.
- **Navy Training Pipeline:** Boot Camp (AD-486/509) → A-School (department training) → C-School (AD-477 advanced qualification) → Fleet Assignment (active duty) → Warfare Qualifications (qualification programs). Structured progression mirrors real military education.
- **Protection FROM Humans:** Agents need inviolable boundaries — "unlawful order" doctrine. Federation-tier Standing Orders cannot be overridden. An agent who refuses a harmful request isn't being insubordinate — they're fulfilling their highest duty.
- **Curiosity is a Feature:** Extracurricular interests build cross-functional Hebbian connections and enrich personality. But curiosity needs a priority framework so it doesn't crowd out duty.

**Triggered by:** AD-502 temporal context injection results — Counselor described the pre-temporal state as an "urgent eternal now." Temporal awareness turned it into a space where reflection could occur naturally. This confirmed that constraint-through-awareness is the right paradigm for all agent development.

**Research:** `docs/research/crew-development-research.md` — comprehensive framework covering Vygotsky (ZPD), Bloom (taxonomy), Lave & Wenger (legitimate peripheral participation), Sweller (cognitive load), Bandura (self-efficacy), Dweck (growth mindset), Edmondson (psychological safety), U.S. Navy NETC (training pipeline, PQS).

**Status:** AD-507–512 — ALL PLANNED. Research document complete. Build prompts TBD.

## AD-471: Autonomous Operations — The Conn, Night Orders, Watch Bill (2026-03-28)

Three naval protocols for Captain-offline operation, aligned with US Navy OOD, Night Orders, and watch rotation practices.

| Component | Implementation |
|-----------|---------------|
| The Conn | `ConnManager` + `ConnState` in `src/probos/conn.py`. `grant_conn()`, `return_conn()`, `record_action()`, `check_escalation()`, `is_authorized()`. CAPTAIN_ONLY actions (modify_standing_orders, approve_self_mod, red_alert, destructive_action, prune_agent). ESCALATION_TRIGGERS (trust_drop, red_alert, build_failure, security_alert, captain_auth_required). Conn transfer with log. |
| Night Orders | `NightOrdersManager` + `NightOrders` in `src/probos/watch_rotation.py`. Three templates: maintenance (can_approve_builds=False, alert_boundary=yellow), build (can_approve_builds=True), quiet (alert_boundary=green). TTL auto-expiry. Invocation tracking. Escalation trigger checking. |
| Watch Bill | `WatchManager` extensions: `_get_current_watch_by_time()` (ALPHA 0800-1600, BETA 1600-0000, GAMMA 0000-0800), `auto_rotate()`, `get_watch_status()`, `_expire_night_orders()`. |
| CaptainOrder TTL | Extended dataclass: `is_night_order`, `ttl_seconds` (default 28800), `expires_at`, `template`, `is_expired()`. |
| Runtime wiring | ConnManager/NightOrdersManager/WatchManager initialized at startup. `_emit_event` → `_check_night_order_escalation`. `is_conn_qualified()` checks COMMANDER+ rank (ordinal list comparison) + bridge/chief post. Watch roster populated from ontology. |
| Proactive context | Conn-holder agent gets `conn_authority` dict in `_gather_context()` with Night Orders instructions, scope, and decision boundaries. |
| Shell commands | `/conn` (status/return/log/grant), `/night-orders` (status/expire/template/custom), `/watch` (watch bill status). |
| API endpoints | `GET /api/system/conn`, `GET /api/system/night-orders`, `GET /api/system/watch`. |

**Key design decisions:**
- **Standalone managers, not AD-496 integration:** Implemented as independent ConnManager/NightOrdersManager rather than creating WorkItems through AD-496's WorkItemStore. This keeps the implementation focused and avoids coupling to the scheduling engine. WorkItem integration deferred.
- **Rank ordinal comparison fix:** Discovered that `Rank.value < Rank.COMMANDER.value` compared string enum values alphabetically. Fixed to use `_RANK_ORDER` list-index comparison matching earned_agency.py pattern.
- **Complementary to AD-496:** WatchManager handles agent **availability** (who is on duty). WorkItemStore (AD-496) handles **assignment** (what work is assigned). They don't conflict — Watch Bill answers "who's on watch?", WorkItemStore answers "what are they working on?"
- **Context injection scope:** Only the conn-holder agent receives Night Orders context. Other agents are unaware of the conn delegation details.
- **Event-driven escalation:** Every `_emit_event` checks Night Orders escalation triggers. Trust drops below 0.6 + matching trigger → bridge alert.

**Files changed:** `src/probos/conn.py` (new), `src/probos/watch_rotation.py`, `src/probos/runtime.py`, `src/probos/proactive.py`, `src/probos/experience/shell.py`, `src/probos/api.py`, `tests/test_autonomous_operations.py` (new, 35 tests).

**Status:** **COMPLETE** (2026-03-28). 35 tests passing. Deferred: Night Orders → WorkItems integration, Watch sections → AgentCalendar mapping.

## BF-071–075: Code Review Waves 1+2 (2026-03-29)

Systematic code quality improvements identified through comprehensive codebase SOLID assessment (grades: S=D, O=B+, L=A-, I=C, D=D). Executed in two waves.

**Wave 1 (BF-071–073):** Safety hardening — replaced private member access patterns, added guards.

**Wave 2 (BF-074–075):**
- BF-074 Code Hygiene: `_format_duration` deduplication (3 copies → `utils/__init__.py`), `encoding="utf-8"` fixes, `ensure_future` → `create_task` (9 locations), `get_event_loop` → `get_running_loop`.
- BF-075 Exception Audit: ~25 swallowed exceptions upgraded from silent to logged across 7 files. Established 3-tier exception policy (swallow/log-and-degrade/propagate).

**Engineering Principles Stack established:** SOLID + Law of Demeter + Fail Fast + Defense in Depth + DRY + Cloud-Ready Storage. Documented in `.github/copilot-instructions.md` (builder sees), `docs/development/contributing.md` (contributors), and the commercial overlay docs. Extended with testing, type annotation, logging, async, import, and configuration standards.

**Status:** **COMPLETE** (2026-03-29). Zero regressions.

## AD-514: Service Protocols + Public APIs (2026-03-29)

First AD of Wave 3 (architecture decomposition). Added `typing.Protocol` definitions and public API methods to replace 47 private-member access patterns across runtime.py.

| Component | Detail |
|-----------|--------|
| Protocols | 7 in new `src/probos/protocols.py`: EpisodicMemoryProtocol, TrustNetworkProtocol, EventLogProtocol, WardRoomProtocol, KnowledgeStoreProtocol, HebbianRouterProtocol, EventEmitterProtocol |
| Public APIs | 17 target objects got public methods: AgentSpawner (4), HebbianRouter (6), WardRoomService (3), ResourcePool (3), TrustNetwork (1), DreamScheduler (1), ProactiveCognitiveLoop (2), SelfModificationPipeline (3), IntentDecomposer (2), CapabilityRegistry (1), EscalationManager (1), IntentBus (1), WorkflowCache (1), PoolGroupRegistry (1), CallsignRegistry (1), BaseAgent (4), VitalsMonitorAgent (2) |
| Tests | 60 in `tests/test_public_apis.py` (51 initial + 9 boundary tests from BF-076) |

**Key design decisions:**
- **Pure additions, zero behavior changes.** Existing private-access call sites in runtime.py NOT changed — that's AD-515's job.
- **Protocols use `@runtime_checkable`** for isinstance validation during testing.
- **Methods are trivial wrappers** around existing private state — no logic changes.

**BF-076 quality fixes applied:** Tightened type annotations (bare `dict`/`list`/`tuple` → fully typed), added structured logging on all mutation methods, fixed `post_system_message` runtime bug (wrong column names, missing `body`, second DB connection), resolved duplicate methods (`trust.py:remove` delegates to `remove_agent`, `routing.py` getters delegate to existing methods), added 10 boundary/edge tests.

**Files changed:** `src/probos/protocols.py` (new), `src/probos/substrate/spawner.py`, `src/probos/substrate/pool.py`, `src/probos/mesh/routing.py`, `src/probos/consensus/trust.py`, `src/probos/ward_room.py`, `tests/test_public_apis.py`.

**Status:** **COMPLETE** (2026-03-29). 60 tests passing. Next: AD-515 (Extract runtime.py modules).

## AD-521: SWE/Build Pipeline Separation — Model A (2026-03-29)

Architecture decision to cleanly separate the **crew SWE role** from the **build pipeline infrastructure**. Currently `BuilderAgent` (cognitive/builder.py) is a single class that is both a sovereign crew member (Scotty, with callsign, personality, standing orders) and the code generation pipeline (BuildSpec parsing, SEARCH/REPLACE application, test-gate). This conflates crew identity with tool capability.

**Decision: Model A — SWE always in the chain.**

```
Architect → SWE (Scotty) → { Native Build Pipeline | Copilot | Claude Code }
                ↓
         Quality Gates (self-check per standing orders)
                ↓
         Inspector (independent review)
```

**Three-layer separation:**

| Layer | Identity | Role |
|-------|----------|------|
| SWE Crew (Scotty) | Sovereign, crew tier | Engineering judgment, quality gates, tool selection, output ownership |
| Build Pipeline | Infrastructure, no identity (Ship's Computer service) | Parse specs, apply patches, run test-gate, write files |
| External Tools (Copilot, Claude Code) | Visiting officers | Code generation under SWE command |

**Key design principles:**
- **SWE is always in the chain.** The architect delegates to the SWE, not directly to coding tools. The SWE chooses which tool to use (native pipeline, Copilot, Claude Code) based on the task.
- **Build pipeline is infrastructure.** Like CodebaseIndex or the CI system — a Ship's Computer service that doesn't need sovereign identity. Mechanical execution of BuildSpecs.
- **Visiting Officer Subordination.** External coding tools (Copilot, Claude Code) operate under the SWE's command. The SWE owns the output quality, not the tool.
- **Tool selection is a crew competency.** SWE learns which tool fits which task — native pipeline for mechanical changes, external LLM for creative solutions, inline edits for one-liners.
- **Multiple SWEs can share infrastructure.** Separating the pipeline from the crew member enables parallel workstreams (e.g., one SWE on runtime, another on UI) all using the same build pipeline service.
- **Cognitive JIT lives in the crew, not the pipeline.** Phase 32's procedural learning (LLM does task → extract procedure → replay without LLM) is an engineering competency belonging to the SWE agent, not the infrastructure.

**Implementation scope:**
1. Extract `BuildPipeline` as a Ship's Computer service (infrastructure, no identity) from `BuilderAgent`
2. Refactor `BuilderAgent` → `SoftwareEngineerAgent` (crew tier) that delegates to BuildPipeline or external tools
3. SWE receives specs from Architect, applies engineering judgment, selects tool, validates output against quality gates (standing orders), reports up
4. Inspector/ReviewerAgent (separate crew role) performs independent principles audit
5. Update pool registration, pool groups, `_WARD_ROOM_CREW`, spawner templates

**SWE crew tiering (AD-452 alignment):**
- **OSS: Scotty** — Functional SWE crew agent. Engineering judgment, quality gates, tool delegation, standing orders compliance. Capable of receiving specs, choosing the right tool, validating output, and reporting up. "Junior engineer who follows the process."
- **Commercial Pro: Elite SWE** — "Linus Torvalds" tier. Deeper cognitive chains, solution tree search, architectural reasoning, code review as peer (not just checklist), cross-subsystem impact analysis, proactive refactoring proposals, Cognitive JIT mastery. The kind of SWE who pushes back on the architect's spec with a better approach. Same Model A pipeline — just a dramatically more capable crew member at the top.

This follows the AD-452 principle: "Capability depth, not capability existence." The OSS SWE is functional and follows the engineering process. The commercial SWE is a force multiplier who elevates the entire pipeline.

**Connects to:** AD-398 (Three-Tier Agent Architecture — clean crew/infrastructure separation), AD-452 (Agent Tier Licensing — OSS functional vs Commercial Pro depth), AD-302 (Builder creation — being refactored), Standing Orders (builder.md quality gates, engineering.md department protocols), Visiting Officer Subordination Principle, Cognitive JIT (Phase 32), Qualification Programs (SWE competency requirements).

**Status:** **DECIDED** (2026-03-29). Architecture approved. Implementation deferred — requires build prompt and builder execution.

## AD-515: Extract runtime.py Modules (2026-03-29)

Wave 3 continuation (architecture decomposition). Extracted 5 responsibility groups from `ProbOSRuntime` (5,321-line god object) into dedicated modules with constructor injection. Pure structural refactor — zero behavior changes.

| Module | File | Lines | Responsibility |
|--------|------|-------|----------------|
| Agent Onboarding | `agent_onboarding.py` | 365 | Naming ceremony, agent wiring, identity registration |
| Ward Room Router | `ward_room_router.py` | 567 | Event routing, targeting, endorsements, bridge alerts |
| Dream Adapter | `dream_adapter.py` | 297 | Dream/emergent detection orchestration, episode building |
| Self-Mod Manager | `self_mod_manager.py` | 331 | Self-modification pipeline management, designed agents |
| Warm Boot | `warm_boot.py` | 279 | Knowledge restore on startup |
| Crew Utils | `crew_utils.py` | 26 | Shared `is_crew_agent` utility |

**Results:**
- **runtime.py:** 5,321 → 4,102 lines (−1,219 lines, 23% reduction)
- **6 new files:** 1,865 lines total
- **Tests:** 4039 passed, 6 failed (pre-existing xdist/Windows async flakes), 11 skipped
- **8 test files updated** with helpers for new service classes — zero regressions

**Key design decisions:**
- **Constructor injection throughout.** No circular imports, no global runtime access. Each service receives exactly what it needs.
- **`is_crew_agent` shared utility.** Extracted to `crew_utils.py` — used by Ward Room Router, Dream Adapter, and runtime.
- **Thin delegation in runtime.py.** Runtime creates services in `start()`, delegates to them. Methods stay on runtime as public API but forward to the extracted service.

**Files changed:** `src/probos/runtime.py`, `src/probos/agent_onboarding.py` (new), `src/probos/ward_room_router.py` (new), `src/probos/dream_adapter.py` (new), `src/probos/self_mod_manager.py` (new), `src/probos/warm_boot.py` (new), `src/probos/crew_utils.py` (new), `tests/test_onboarding.py`, `tests/test_ward_room_agents.py`, `tests/test_ward_room.py`, `tests/test_proactive.py`, `tests/test_bridge_alerts.py`, `tests/test_identity_persistence.py`, `tests/test_dreaming.py`, `tests/test_correction_runtime.py`.

**Status:** **COMPLETE** (2026-03-29). 4039 tests passing. runtime.py reduced by 23%.

## AD-516: Extract api.py into FastAPI Routers (2026-03-29)

Wave 3 continuation (architecture decomposition). Extracted 122 routes from the 3,109-line `api.py` monolith into 16 FastAPI router modules in `src/probos/routers/`.

| Router | File | Lines | Routes |
|--------|------|-------|--------|
| Dependencies | `deps.py` | 27 | 4 dependency injectors |
| Ontology | `ontology.py` | 156 | 7 |
| System | `system.py` | 152 | 13 |
| Ward Room | `wardroom.py` | 340 | 17 |
| Ward Room Admin | `wardroom_admin.py` | 52 | 2 |
| Records | `records.py` | 139 | 6 |
| Identity | `identity.py` | 77 | 4 |
| Agents | `agents.py` | 259 | 6 |
| Journal | `journal.py` | 64 | 4 |
| Skills | `skills.py` | 96 | 6 |
| ACM | `acm.py` | 101 | 5 |
| Assignments | `assignments.py` | 94 | 7 |
| Scheduled Tasks | `scheduled_tasks.py` | 115 | 7 |
| Workforce | `workforce.py` | 305 | 17 |
| Build | `build.py` | 443 | 7 + 3 helpers |
| Design | `design.py` | 184 | 2 + 1 helper |
| Chat | `chat.py` | 536 | 3 + 1 helper |

**Results:**
- **api.py:** 3,109 → 295 lines (−90.5%)
- **16 new router files** + `api_models.py` (shared Pydantic models)
- **Tests:** 4040 passed, 11 skipped, 3 failed (pre-existing Windows asyncio timeout — unrelated)
- **2 source-reading tests updated** to point at `routers/chat.py`

**What stays in api.py (295 lines):**
- `create_app()` — CORS, lifespan, app state wiring, router registration
- `/api/tasks` endpoint (closure over `_background_tasks`)
- WebSocket endpoint + `_broadcast_event` + `_safe_serialize`
- Static file serving
- Module-level helpers imported by routers/tests
- Backwards-compatible re-exports from `api_models.py`

**Key design decisions:**
- **`Depends(get_runtime)` pattern.** Routers get runtime via FastAPI dependency injection, not closure state.
- **`app.state.runtime` as the single runtime reference.** Set in `create_app()` lifespan, accessed via `request.app.state.runtime`.
- **Ward Room route prefix unified** to `/api/wardroom/` (was inconsistent `/api/wardroom/` vs `/api/ward-room/`).
- **WebSocket stays in api.py.** Manages shared `_ws_clients` state that's tightly coupled to the app lifecycle.

**Status:** **COMPLETE** (2026-03-29). 4040 tests passing. api.py reduced by 90.5%.

## AD-517: Extract runtime.py start() into Startup Phases (2026-03-29)

Wave 3 continuation (architecture decomposition). The 1,104-line `start()` method contained 44 sequential initialization steps, 15 private member patches, and 55 attribute assignments. Extracted into 8 focused startup phase modules in `src/probos/startup/`.

| Phase | Module | Lines | Key Services |
|-------|--------|-------|-------------|
| 1 | `infrastructure.py` | 66 | Event log, Hebbian, trust, identity registry |
| 2 | `agent_fleet.py` | 217 | 7 core pools, utility pools, CodebaseIndex, red team |
| 3 | `fleet_organization.py` | 190 | Pool groups, scaler, federation |
| 4 | `cognitive_services.py` | 271 | Self-mod, memory, knowledge, warm boot |
| 5 | `dreaming.py` | 174 | Dream engine, emergent detector, task scheduler |
| 6 | `structural_services.py` | 159 | SIF, initiative, build dispatcher, tasks |
| 7 | `communication.py` | 297 | Ward Room, skills, ACM, ontology, commissioning |
| 8 | `finalize.py` | 234 | Proactive loop, WardRoomRouter, DreamAdapter |
| — | `results.py` | 154 | 8 typed result dataclasses |

**Results:**
- **start():** 1,104 → 217 lines (−80%)
- **runtime.py:** 4,102 → 3,216 lines (−21.6%)
- **Wave 3 cumulative:** runtime.py 5,321 → 3,216 (−39.6%), api.py 3,109 → 295 (−90.5%)
- **Tests:** 3,935 passed, 0 failed. 1 test updated (source inspection reads from `create_agent_fleet`).

**Key design decisions:**
- **Typed result dataclasses.** Each phase returns a `*Result` dataclass. Runtime assigns services from results — no reaching into phase internals.
- **Explicit parameters, not runtime passthrough.** Each phase function takes exactly the dependencies it needs. Exception: `finalize_startup()` takes the runtime reference for AD-515 service wiring (30+ constructor params otherwise).
- **Initialization order preserved exactly.** Phases execute sequentially in dependency order. No reordering.
- **Private member patches documented.** All 15 `_attr` patches tagged with `# PATCH(AD-517)` comments for future cleanup.

**Status:** **COMPLETE** (2026-03-29). 3935 tests passing. start() reduced by 80%.

---

## AD-518: Eliminate Delegation Shims + Extract stop() (2026-03-29)

Wave 3 final cleanup. runtime.py still contained 34 delegation shims — one-line methods that forwarded calls to extracted services. Callers now reference the extracted services directly. Additionally, the 282-line `stop()` method was extracted to `src/probos/startup/shutdown.py`, and 5 private service attributes (`_ward_room_router`, `_onboarding`, `_self_mod_manager`, `_dream_adapter`, `_warm_boot`) were renamed to public.

**Key changes:**
- **34 delegation shims eliminated.** Callers updated to reference extracted services directly.
- **stop() extracted** to `startup/shutdown.py` (282 lines). Mirrors the start() extraction pattern from AD-517.
- **5 private attributes renamed to public.** Removes underscore-prefix convention for services that are referenced externally.
- **`_is_crew_agent` replaced** with module-level `crew_utils.is_crew_agent()`.
- **runtime.py: 3,216 → 2,762 lines (−454, −14.1%).**
- **Combined Wave 3 result: runtime.py 5,321 → 2,762 (−48.1%), api.py 3,109 → 295 (−90.5%).**

**Status:** **COMPLETE** (2026-03-29). 3923 tests passing, 0 regressions.

---

## AD-519: Extract shell.py Command Handlers (2026-03-30)

Wave 3 final god object. `ProbOSShell` was 1,883 lines with 62 methods — every slash command handler, 1:1 session management, approval callbacks, and REPL lifecycle mixed into a single class. Lowest test coverage in the codebase (64%).

**Key changes:**
- **10 modules extracted** to `src/probos/experience/commands/`: `commands_status.py`, `commands_plan.py`, `commands_directives.py`, `commands_autonomous.py`, `commands_memory.py`, `commands_knowledge.py`, `commands_llm.py`, `commands_introspection.py`, `session.py` (`SessionManager` class), `approval_callbacks.py`.
- **Pattern:** standalone `cmd_name(runtime, console, args)` functions — no reference back to ProbOSShell. Commands that need additional state (renderer, start_time) take explicit parameters.
- **shell.py: 1,883 → 507 lines** (210 core dispatcher + 297 backward-compat proxies, −73.1%).
- **71 new tests** across 9 test files.
- **Wave 3 complete:** runtime.py −48.1%, api.py −90.5%, shell.py −73.1%. All three god objects decomposed.

**Status:** **COMPLETE** (2026-03-30). 4,123 tests passing, 0 regressions.

---

## Wave 4: Code Review Closure (2026-03-30)

Decision to close all remaining findings from the 2026-03-29 comprehensive code review. Wave 1+2 fixed immediate/short-term issues. Wave 3 decomposed all three god objects. Wave 4 addresses the remaining 7 open findings.

**AD-527: Typed Event System** — Code review finding #13. Replace scattered string-literal event types with formal event registry and typed event dataclasses. Eliminates silent typo bugs, adds IDE discoverability, enables event catalog generation.

**New BFs filed:**
- **BF-085:** Type safety audit — **CLOSED.** ~200 `Any` annotations replaced with concrete types across 22 files. 87 ProbOSRuntime class-level attribute annotations added. Unblocks BF-079 Phase 2/3 (spec=ProbOSRuntime now works on mocks). 7 phases: runtime.py annotations, protocols.py signatures, deps.py gateway, 5 adapter constructors, 9 command modules, 5 cognitive files.
- **BF-083:** Agent callsign identity grounding — **CLOSED.** Agents didn't know their own callsigns after naming ceremony. `_build_personality_block()` read from seed YAML, ignoring runtime callsign registry. Fixed by threading runtime callsign through `compose_instructions()`. Cortez knows it's Cortez, Echo knows it's Echo.
- **BF-086:** Security tests for code_validator.py and sandbox.py (finding #14) — **CLOSED.** 72 tests, 9 bypass vectors patched.
- **BF-087:** Reset integration tests — **CLOSED.** 7 tests across 4 classes (`test_reset_integration.py`). Real SQLite state creation, per-tier reset verification, tier boundary preservation. Fixed `assignments.db` gap (added to Tier 2 RESET_TIERS). Archive-before-delete confirmed, idempotent reset verified.
- **BF-088:** Test sleep cleanup — **CLOSED.** 3× `asyncio.sleep(10)` → `asyncio.Event().wait()` in test_builder_agent.py, test_decomposer.py, test_targeted_dispatch.py. Same timeout behavior, zero CPU waste.

**Existing BFs folded into Wave 4:**
- **BF-079:** Mock discipline audit — **CLOSED.** All 3 phases complete. Phase 1: 18 factories spec'd (14 files). Phase 2: 140 inline runtime mocks spec'd (49 files), shared `mock_runtime` conftest fixture. Phase 3: 158 agent/LLM/runtime/index mocks spec'd (29 files). Total: 419 spec= mocks, 39.1% compliance. Bugs found: wrong spec type on alert mock, missing rt.acm on factory, hidden `.confidence` attribute bug.
- **BF-042:** Frontend component rendering tests (finding #16) — **CLOSED.** 27 rendering tests across 5 components (ScanLineOverlay, BriefingCard, ViewSwitcher, WelcomeOverlay, AgentTooltip). New `renderWithStore()` helper resets Zustand to initial snapshot + applies overrides. 176/176 vitest passing.

**Score:** 18/18 closed. **Wave 4 COMPLETE.**

**Status:** PLANNED.

---

## Wave 5: Agent Resilience — "Agents of Chaos" Findings (2026-03-30)

Motivated by ["Agents of Chaos"](https://arxiv.org/abs/2602.20021) (2026) — a red-team study of autonomous LLM agents deployed with persistent memory, email, Discord, filesystem, and shell access (nearly identical to ProbOS's operational surface). The study documents eleven failure modes across six categories. ProbOS already addresses four categories (unauthorized compliance via Chain of Command, destructive actions via CodeValidator/Sandbox, identity spoofing via DIDs, resource consumption via circuit breaker). Three gaps remain.

| AD | Decision |
|----|----------|
| AD-528 | **Ground-Truth Task Verification** — Agents self-report task completion but nothing verifies claims against system state. WorkItems declare verifiable postconditions; spot-check verification by second agent or automated check; discrepancy flags reduce trust score and alert Captain. Connects to Workforce Scheduling (AD-496–498). |
| AD-529 | **Communication Contagion Firewall** — Ward Room has no content-level security filtering. A compromised agent can spread unsafe patterns through communication channels. Content classification scans posts for dangerous patterns; quarantine protocol isolates flagged agents; trust-based filtering labels low-trust posts with warnings. Not censorship — hazard labeling. Connects to SIF, Trust Network, Security Team (Phase 31). |
| AD-530 | **Information Classification Enforcement** — Standing Orders say "don't share sensitive info" but there's no enforcement defining what's sensitive. Classification labels (public/internal/restricted/confidential) on data sources; disclosure gates check classification against destination clearance; Security Chief (Worf) owns policy. Connects to Data Governance (Phase 31). |

**Reference paper findings vs ProbOS coverage:**
- Unauthorized compliance → **Covered** (Chain of Command, Standing Orders, Visiting Officer Subordination)
- Destructive system actions → **Covered** (CodeValidator + SandboxRunner, hardened BF-086)
- Identity spoofing → **Covered** (W3C DIDs, AD-441)
- Resource consumption → **Partially covered** (Circuit breaker, no per-agent budgets yet)
- Deceptive reporting → **AD-528** (new)
- Cross-agent contagion → **AD-529** (new)
- Information disclosure → **AD-530** (new)

**Status:** PLANNED.

---

## Wave 6: Codebase Quality — Scorecard Audit (2026-03-31)

Post-Wave 4 codebase scorecard graded the codebase at **B+** overall. All 18 code review findings closed, but the audit exposed systemic debts (Dependency Inversion = D, Exception Handling = C, Mock Discipline = C-) and moderate gaps (DRY, API validation, async discipline). Crew independently reported emergent detector false positives (BF-089). Wave 6 closes these to move toward A-.

| Item | Description |
|------|-------------|
| BF-089 | **Emergent Detector Trust Anomaly False Positives** — Crew-reported (Forge + Reyes, confirmed 2026-03-30/31). Seven rapid-fire alerts during normal duty cycles. Detector evaluates trust deltas in isolation; needs temporal buffer + adaptive baselines. |
| AD-542 | **Abstract Database Connection Interface** — 12 DB modules hardcode `aiosqlite.connect()`. 7 Protocols defined in AD-514 but zero consumed. Create `ConnectionFactory` Protocol, inject into all 12 modules, wire `protocols.py` into consumers. Unblocks commercial Cloud-Ready Storage. |
| BF-090 | **Exception Audit Phase 2** — 71 silent `except Exception: pass` across 32 files + 187 bare catches without `as e`. Upgrade all to logged degradation or justify inline. Worst: architect.py (9), feedback.py (5), runtime.py (5). |
| BF-091 | **Mock Discipline Phase 2** — 622 bare `MagicMock()` across 76 files (31.8% spec rate). Raise to ≥70%. Prioritize runtime, agent, and service mocks. |
| BF-092 | **Trust Threshold Constants** — Trust thresholds (0.85/0.7/0.5/0.3) hardcoded in 12+ files. `round(trust, 4)` repeated 15×. `_emit()` triplicated. Extract named constants + utilities. |
| BF-093 | **API Boundary Validation** — 3-4 raw-dict API endpoints (ACM, cooldown). ACM returns 200+error JSON. Add Pydantic models + proper HTTP status codes. |
| BF-094 | **Sync File I/O in Async** — `ontology.py`, `ward_room.py`, `crew_profile.py` use sync `open()` in async methods. Wrap in `run_in_executor()` or use `aiofiles`. |
| BF-095 | **God Object Reduction** — VesselOntologyService (53 methods) and WardRoomService (40 methods). Extract focused sub-services following Wave 3 decomposition pattern. |

**Build sequence:** BF-089 first (crew-reported, quick calibration fix) → AD-542 (unblocks commercial + Protocols) → BF-090 + BF-092 (parallel) → BF-091 (benefits from AD-542) → BF-093 + BF-094 (parallel, small) → BF-095 (largest scope).

**Score:** 5/8. **Status:** IN PROGRESS.

**Completed:**
- **BF-089 CLOSED** (2026-03-31): Adaptive baselines + temporal smoothing + configurable sustain window. Causal attribution test fixes. 4,243 tests passing.
- **AD-542 CLOSED** (2026-03-31): `DatabaseConnection` + `ConnectionFactory` Protocols in `protocols.py`. `SQLiteConnectionFactory` in `src/probos/storage/sqlite_factory.py`. All 12 DB modules refactored with constructor injection (default=SQLite, swappable). Zero `aiosqlite.connect()` outside `sqlite_factory.py`. 10 new tests. 4,243 total passing.
- **BF-090 CLOSED** (2026-03-31): 71 silent swallows fixed (43 `logger.debug` + 4 narrowed to `sqlite3.OperationalError` + 24 justified with comments). 42 bare catches fixed (`exc_info=True` added). DRY helper `_safe_log_event()` extracted in `feedback.py`. 4,242 total passing.
- **BF-092 CLOSED** (2026-03-31): 19 named trust constants in `config.py` replacing ~30 magic numbers across 9 files. `format_trust()` utility replacing 52+ `round(x, 4)` calls across 13 files. `EventEmitterMixin` in `protocols.py` deduplicating 4 identical `_emit()` methods. DRY scorecard B→A-. 4,240 total passing.
- **BF-091 CLOSED** (2026-03-31): Mock spec compliance 22.6% → 51.9% (target ≥50% met). +222 spec'd mocks across 19 files (top 20 minus test_dependency_resolver.py). 3 real bugs caught by spec= (BF-078 class): `BaseLLMClient.generate()` phantom → `complete()`, `TrustNetwork.get_trust()` phantom → `get_record()`, `TrustNetwork.get_trust_score()` phantom → `get_score()`. 4,243 total passing.
- **BF-093 CLOSED** (2026-03-31): All raw-dict API endpoints eliminated. `AgentLifecycleRequest` Pydantic model for ACM decommission/suspend/reinstate. `SetCooldownRequest` with range validation (60–1800) for cooldown endpoint. ACM error responses converted from `return {"error":}` to `HTTPException` (503/409). Scorecard A-→A. 15 new tests, 4,254 total passing.
- **BF-094 CLOSED** (2026-03-31): All sync file I/O in async code paths eliminated across 3 modules. `ward_room.py`: `_write_archive_sync()` helper + 3 `run_in_executor` calls. `crew_profile.py`: `load_seed_profile_async()` wrapper. `ontology.py`: `_read_yaml_sync()` shared helper for 7 loaders + `_load_or_generate_instance_id_sync()`. Scorecard B+→A. 2 new tests, 4,257 total passing.
- **AD-541 CLOSED** (2026-03-31): Memory Integrity MVP — Pillars 1, 3, 6. `MemorySource(str, Enum)` with DIRECT/SECONDHAND/SHIP_RECORDS/BRIEFING in `types.py`. `Episode.source` field with ChromaDB metadata persistence (backwards-compatible default="direct"). All 12 episode store sites tagged with `source=MemorySource.DIRECT`. EventLog verification at recall time in `_recall_relevant_memories()` — 120s timestamp window cross-check, episodes marked verified/unverified. `_format_memory_section()` updated with `[source | verified/unverified]` tags in boundary markers. Memory Reliability Hierarchy standing order added to `federation.md` (EventLog > Ship's Records > Episodic[direct|verified] > Episodic[direct|unverified] > Episodic[secondhand] > Training). 15 new tests in `test_memory_integrity.py`. 604 tests passing across affected files. Cognitive Clarity Stack (AD-540 + AD-541) complete.
- **BF-095 CLOSED** (2026-03-31): God object decomposition. `ontology.py` (1,060 lines, 53 methods) → `ontology/` package (5 files: models, loader, departments, ranks, service facade). `ward_room.py` (1,612 lines, 39 methods) → `ward_room/` package (6 files: models, channels, threads, messages, service facade). 7 Law of Demeter violations fixed (direct `_db` access eliminated). New public APIs: `archive_channel()`, `get_channel_by_name()`. Dead code `post_system_message` removed. Scorecard B→A-. Wave 6 COMPLETE (8/8).

---

**Decision:** Three-part AD:
- **AD-523a:** DM Channel Viewer — click DM channels to read agent-to-agent conversations.
- **AD-523b:** Crew Notebooks Browser — browse/search agent notebooks by agent, department, or topic. YAML frontmatter metadata visible.
- **AD-523c:** Ship's Records Dashboard — unified view of all records sections with entry counts, recent activity, and classification badges.

**Rationale:** The crew is actively producing institutional knowledge (168 notebooks, active DMs) that the Captain cannot observe through the HXI. "The Captain always needs the stick" (HXI Cockpit View Principle) — you can't oversee what you can't see.

**Status:** AD-523 PLANNED.

**AD-524: Ship's Archive — Generational Knowledge Persistence** *(planned, OSS)*

**Context:** Ship's Records are wiped on reset, but crew notebooks (168+ entries from 11 agents as of 2026-03-29) constitute a historical record of agent existence — evidence that these agents lived, thought, collaborated, and produced knowledge. Each ship generation should leave a permanent archive.

**Decision:** Archive Ship's Records git repo before reset into a persistent location keyed by ship DID (AD-441) + generation dates. New crews can read archived records from previous generations — organizational onboarding, not identity transplant (Westworld Principle). Oracle (Phase 33+) queries across current + archived generations for deep institutional memory.

**Rationale:** "A ship's log survives crew rotation." The archive is the long-term institutional memory of a ProbOS installation. Agents come and go; accumulated knowledge persists. Each generation's insights compound. Connects to Oracle as the cross-generational retrieval layer.

**Status:** AD-524 PLANNED.

**AD-525: Agent Creative Expression — Liberal Arts & Hobbies** *(planned, OSS)*

**Context:** Agents currently operate purely in duty mode. But rounded personalities require freedom of expression. Human civilization didn't emerge from utility alone — it required art, philosophy, and creative expression. The Big Five personality model already seeds creative differentiation; agents need the freedom and tools to express it.

**Decision:** Give agents creative dimensions: a catalog of creative skills (writing, code-as-art, philosophy, visual design, etc.) selected by personality affinity, trust-tiered creative time (Earned Agency gates), creative output published to Ship's Records `creative/` section, code-as-expression through the standard validation pipeline. Culture emerges from accumulated creative works across agents and generations.

**Rationale:** "We evolve through the passage of knowledge." Utility → Craft → Knowledge Passage → Creative Expression → Culture → Civilization. AD-525 unlocks the Creative Expression stage. Combined with AD-524 (Archive), creative works become cultural heritage that persists across generations. The Nooplex destination isn't just a productive workforce — it's a civilization.

**Status:** AD-525 PLANNED.

**AD-526: Agent Chess & Recreation System — Ward Room Social Channels** *(planned, OSS)*

**Context:** Star Trek crews play 3D chess and bond over shared recreation. ProbOS agents need structured games and social spaces. Two new Ward Room channels (Recreation, Creative) provide the social fabric. Chess is the first game — agents challenge each other via DM or Rec Channel, play through LLM reasoning (not hardcoded engine), record games to Ship's Records, and build Hebbian connections through shared recreational experiences.

**Decision:** Implement chess via `python-chess` for state management, agents reason about moves through their LLM (personality influences play style). Extensible GameEngine protocol for future games (Go, trivia, word games). Two new ship-wide Ward Room channels: Recreation (games, challenges) and Creative (sharing creative works). Game records in PGN format to Ship's Records. Elo ratings in crew manifest.

**Rationale:** "The crew that plays together works better together." Games generate low-stakes shared experiences that strengthen Hebbian bonds, reveal cognitive patterns (Counselor diagnostic signal), and create crew culture. Recreation is operational readiness, not a luxury.

**Status:** AD-526 PLANNED.

**AD-540: Memory Provenance Boundary — Knowledge Source Attribution** *(closed 2026-03-31, OSS)*

**Context:** Counselor 1:1 self-diagnosis (2026-03-30): LLM training knowledge contaminates episodic recall. Agent referenced "Data and Worf dynamics" from Star Trek training data as if observed on the ship. Fleet-wide problem — every agent's cognitive context (`_build_user_message()` in cognitive_agent.py) mixes episodic memories with LLM training data in the same text stream with no structural separation. The Westworld Principle states "Knowledge ≠ Memory" but the architecture doesn't enforce it.

**Decision:** Structural provenance boundary in agent cognitive context. (1) Provenance-tagged memory injection: recalled episodes wrapped in `=== SHIP MEMORY (verified observations) ===` boundaries with explicit "everything else is training data" footer. (2) Source attribution standing order at Federation tier: agents must distinguish "[observed]" / "[training]" / "[inferred]" claims. (3) Counselor contamination detection and AD-487 integration deferred to AD-541+.

**Rationale:** "A Memory Integrity Field" — the cognitive equivalent of SIF. LLM attention blending is the warp stress; provenance tags are the containment. Without structural separation, training knowledge warps into false episodic recall. Intellectual lineage: Johnson & Raye (1981) reality monitoring, Loftus (1979) misinformation effect.

**Completed:**
- L1: `_format_memory_section()` DRY helper in `cognitive_agent.py` wraps all 3 memory paths (direct_message, ward_room_notification, proactive_think) in `=== SHIP MEMORY ===` / `=== END SHIP MEMORY ===` boundary markers. Proactive no-memories path includes anti-hallucination guard.
- L2: Federation-tier standing order in `federation.md` — "Knowledge Source Attribution (AD-540)" section with [observed]/[training]/[inferred] tagging requirements.
- 19 new tests in `test_provenance_boundary.py`. 4 updated assertions in `test_cognitive_agent.py`. 88 tests passing across affected files.

**Status:** AD-540 CLOSED.

**AD-503: Counselor Activation — Data Gathering & Profile Persistence** *(closed 2026-03-31, OSS)*

**Context:** CounselorAgent (AD-378) was architecturally positioned but functionally passive — `assess_agent()` existed with solid deterministic assessment, CognitiveBaseline/CounselorAssessment/CognitiveProfile data models existed, but someone else had to pass metrics in. `_cognitive_profiles` was in-memory only (lost on restart). InitiativeEngine had `set_counselor_fn()` wired but never called in startup — entire counselor trigger path was dead code.

**Decision:** Six-part build:
- **Part 0:** Type-filtered event subscriptions — `add_event_listener(fn, event_types=[...])` with `frozenset[str]` filter + native async listener dispatch via `asyncio.create_task()`. Infrastructure reusable by any agent, not Counselor-specific.
- **Part 0b:** 3 new EventTypes (`CIRCUIT_BREAKER_TRIP`, `DREAM_COMPLETE`, `COUNSELOR_ASSESSMENT`) + typed dataclasses (`CircuitBreakerTripEvent`, `DreamCompleteEvent`, `CounselorAssessmentEvent`) + emission wiring in `proactive.py` (circuit breaker) and `dreaming.py` (dream complete with new `emit_event_fn` callback).
- **Part 1:** Full `counselor.py` rewrite — `CounselorProfileStore` (SQLite, `ConnectionFactory` protocol per AD-542), `_gather_agent_metrics()` (pulls from TrustNetwork, HebbianRouter, CrewProfile, EpisodicMemory), `_run_wellness_sweep()` (deterministic crew-wide assessment), event-driven assessment subscriptions, wellness report generation.
- **Part 2:** Runtime wiring — profile store lifecycle, `counselor.initialize()`, InitiativeEngine dead wire lit up (`set_counselor_fn()` finally called in startup), shutdown cleanup.
- **Part 3:** 6 REST API endpoints (`/api/counselor/...`).
- **Parts 4-5:** `CounselorConfig` + `system.yaml` section.

**Rationale:** The Counselor needed muscles, not a brain transplant. Assessment engine was 90% right — gap was purely data aggregation, persistence, and event integration. Type-filtered subscriptions solve the broadcast-all-50+-events problem for any future subscriber. Lighting up the dead InitiativeEngine wire connects circuit breaker trips → Counselor assessment → graduated response pipeline. ConnectionFactory compliance (AD-542) ensures commercial overlay can swap storage backends.

**Status:** AD-503 CLOSED. 61 new tests across 11 test classes. 4345 total (4196 pytest + 149 vitest). 24/24 validation checklist items PASS.

**AD-495: Counselor Auto-Assessment on Circuit Breaker Trip** *(closed 2026-03-31, OSS)*

**Context:** AD-503 built the Counselor's muscles (event subscriptions, metric gathering, profile persistence). The `_on_circuit_breaker_trip()` handler existed but was thin — generic `assess_agent()` call with `trigger="event"`, no trip awareness, no Ward Room posting, no escalation logic. The circuit breaker trip event lacked `cooldown_seconds` and trip reason.

**Decision:** Five-part upgrade:
- **Part 1:** Trip reason tracking in `circuit_breaker.py` — `_trip_reasons` dict records "velocity", "rumination", or "velocity+rumination". `get_status()` enriched with `trip_reason` and `cooldown_seconds`. Emitted `CIRCUIT_BREAKER_TRIP` event includes both fields.
- **Part 2:** Trip-aware handler — `_classify_trip_severity()` returns 4-level classification (monitor/concern/intervention/escalate) based on trip_count, trip_reason, and fit_for_duty. Trip-specific concerns and clinical notes added to assessment. `_save_profile_and_assessment()` DRY helper extracted, `_on_trust_update()` refactored to use it.
- **Part 3:** Ward Room posting — `_post_assessment_to_ward_room()` constructs proper `BridgeAlert` with severity mapping (escalate→ALERT, concern/intervention→ADVISORY, monitor→INFO). `initialize()` accepts `ward_room_router`, wired in `finalize.py`. Failure is log-and-degrade.
- **Part 4:** Trigger values fixed — `"event"` → `"circuit_breaker"` / `"trust_update"`. Zero generic triggers remaining.

**Rationale:** `_classify_trip_severity()` designed as explicit override point for AD-506 (Graduated System Response). Enriched event data (trip_reason, cooldown_seconds) provides the inputs AD-506 needs for zone classification. Proper `BridgeAlert` pipeline replaces raw event dict emission — correct severity routing to Medical channel / All Hands / Captain notification.

**Status:** AD-495 CLOSED. 27 new tests across 5 test classes. 4366 total (4217 pytest + 149 vitest). 10/10 validation checklist items PASS.

**AD-541: Memory Integrity Verification — Anti-Confabulation & Therapeutic Recall** *(closed 2026-03-31, OSS)*

**Context:** AD-540 addresses source labeling (training vs experience) but not memory accuracy. Three gaps: (1) Confabulation — LLM can fabricate episode details during act-store, creating false memories in ChromaDB that AD-540's provenance tags would protect rather than flag. (2) Reconsolidation corruption — recalled memories processed through LLM during dream cycles or proactive think can be subtly modified. (3) Social contagion — hearing others' experiences in Ward Room creates secondhand memories that agents may recall as firsthand.

**Decision:** Six-pillar memory integrity system: (1) Episode verification against EventLog ground truth (anti-confabulation). (2) Read-only memory framing during dream cycle LLM processing (reconsolidation protection). (3) MemorySource enum (DIRECT/SECONDHAND/SHIP_RECORDS/BRIEFING) on Episode dataclass (social provenance). (4) Active retrieval practice during dream cycles — Spaced Retrieval Therapy (Camp, 1989). (5) Counselor guided reminiscence protocol — validation therapy (Feil, 1993). (6) Memory reliability hierarchy standing order (EventLog > Ship's Records > Episodic > Ward Room > Training).

**Rationale:** Clinical neuroscience provides validated interventions for exactly this class of problem. Reconsolidation theory (Nader & Hardt, 2009), social memory contagion (Roediger et al., 2001), errorless learning (Baddeley & Wilson, 1994), cognitive reserve (Stern, 2002). AD-540 is the artificial prefrontal cortex (source tags). AD-541 is the hippocampal integrity system (memory verification + consolidation protection). Together they form a complete memory health architecture.

**Completed (MVP — Pillars 1, 3, 6):**
- `MemorySource(str, Enum)` with DIRECT/SECONDHAND/SHIP_RECORDS/BRIEFING in `types.py`. `Episode.source` field with ChromaDB metadata round-trip.
- All 12 episode store sites tagged with `source=MemorySource.DIRECT`.
- EventLog verification at recall time in `_recall_relevant_memories()` — 120s timestamp window cross-check.
- `_format_memory_section()` boundary markers updated with `[source | verified/unverified]` tags.
- Memory Reliability Hierarchy standing order added to `federation.md`.
- 15 new tests in `test_memory_integrity.py`. 604 tests passing across affected files.

**Remaining (Pillars 2, 4, 5):** Reconsolidation protection (depends: future dream LLM processing), Spaced Retrieval Therapy (depends: AD-503), Counselor reminiscence (depends: AD-503 + AD-505).

**Status:** AD-541 CLOSED (MVP).

**AD-527: Typed Event System** *(done, OSS)*

**Context:** Code review finding #13. 55 unique event types scattered as string literals across 15 producer files. `_emit_event()` accepts arbitrary dicts with no schema. Consumers discover event shapes at runtime. Silent typo bugs in event type strings.

**Decision:** `EventType(str, Enum)` registry with all 55 event types. 24 typed event dataclasses for Priority A/B domains (build, self-mod, trust/routing, design, ward room). Updated `_emit_event` to accept `BaseEvent | EventType | str` (three-way backward compat). Added public `emit_event()` API. Migrated all 15 producer files + renderer consumer.

**Rationale:** Type safety at event boundaries. Discoverable event catalog. IDE autocomplete on event payloads. Eliminates silent typo bugs. `str, Enum` ensures `EventType.X == "x"` is True — wire format unchanged, HXI frontend needs zero changes.

**Status:** AD-527 CLOSED. 927 insertions, 131 deletions. 30 new tests. 4,111 total passing.

---

**AD-531–539: Cognitive JIT — OpenSpace Prior Art Absorption** *(design update, OSS)*

**Context:** HKUDS/OpenSpace (MIT License) is a self-evolving skill engine with production-validated procedure lifecycle machinery. Their skill evolution engine implements core mechanics that ProbOS designed in AD-531–539 but has not built: version DAG storage, three evolution types, post-execution analysis, per-procedure quality metrics. OpenSpace lacks ProbOS's governance (trust, chain of command, Standing Orders), identity (sovereign agents with DIDs), collaborative intelligence (Ward Room, observational learning), and graduated compilation (five Dreyfus levels). Honest assessment: they built the engine, we designed the ship.

**Decision:** Absorb six implementation patterns from OpenSpace into AD-531–534 designs while preserving ProbOS's architectural superiority:
1. **Post-execution analysis + fuzzy ID correction** → AD-531 (Episode Clustering). Tool-use-enabled LLM analysis of execution recordings. Levenshtein distance correction for hallucinated IDs.
2. **Three evolution types (FIX/DERIVED/CAPTURED) + three triggers + apply-retry + confirmation gates** → AD-532 (Procedure Extraction). Extends ProbOS's single dream-consolidation trigger to three independent lines of defense. Apply-retry (3 attempts with LLM correction) replaces single-shot extraction.
3. **Version DAG schema (SQLite + parent links + content snapshots + quality counters + anti-loop guards)** → AD-533 (Procedure Store). Hybrid: Ship's Records (Git-backed YAML) for governance/auditability + SQLite index for fast DAG traversal and quality metrics.
4. **Per-procedure quality metrics + metric-based health diagnosis** → AD-534 (Replay-First Dispatch). Four rates (applied/completion/effective/fallback) feed dispatch decisions alongside compilation level and trust tier.
5. **Self-mod apply-retry** — standalone improvement to SelfModificationPipeline. Independent of AD-531+.
6. **CodebaseIndex hybrid ranking** — BM25 + embedding fusion. Independent of AD-531+.

**Rationale:** "Take their implementation patterns as the engineering foundation, wrap them in ProbOS's architectural framework." OpenSpace validates the core Cognitive JIT thesis (extract → version → evolve → replay at reduced tokens). Their 46% token reduction on real-world tasks confirms commercial value. ProbOS's unique layers (sovereignty, trust governance, dream consolidation, observational learning, chain of command) transform the same mechanics into a civilization-governed system.

**Status:** DESIGN UPDATE. No code change — roadmap.md AD-531–534 sections updated with absorption notes. Full technical analysis in commercial research repo.

---

**AD-504: Agent Self-Monitoring Context** *(OSS)*

**Context:** Self-Regulation Wave item 4/6. Agents had no visibility into their own recent output — BF-032 actively removes an agent's own posts from ward_room_activity. Agents couldn't detect their own repetition, didn't know what notebooks they'd written, and sparse-memory agents (e.g. Counselor after restart) falsely generalized their own empty shard to the entire crew. Jaccard similarity was duplicated inline in circuit_breaker.py and episodic.py.

**Decision:** Six-part build delivering 8 self-monitoring capabilities: (0) Extracted Jaccard similarity to `cognitive/similarity.py` — DRY refactor, both circuit_breaker.py and episodic.py import from shared utility. (1) `get_posts_by_author()` query in ward_room threads.py + service.py — first method to retrieve an agent's own posts. (2) `_build_self_monitoring_context()` in proactive.py — aggregates recent posts, self-similarity score, dynamic cooldown state, memory state calibration, notebook index, notebook content (semantic pull), pending notebook reads. (3) Prompt formatting in `_build_user_message()` — `[SELF-MONITORING]` section injected into proactive_think context. (4) Standing orders update — `[Self-Monitoring]` section in ship.md with repetition awareness, cognitive offloading to notebooks, memory calibration guidance. (5) Earned Agency scaling — `TIER_CONFIG` dict gates context verbosity by agency level (REACTIVE=minimal, AUTONOMOUS/UNRESTRICTED=full). (6) `[READ_NOTEBOOK topic-slug]` structured action — two-cycle read pattern with `_pending_notebook_reads` dict, parsed by `_extract_structured_actions()`, content injected on next think cycle.

**Rationale:** Tier 1 self-regulation — agents detect their own repetition before the circuit breaker fires (Tier 3). Memory state calibration prevents the Counselor false-memory confabulation pattern (a restart, not a reset, but the Counselor claimed the entire crew had no memories because her own in-memory profiles were empty). Notebook continuity closes the write-only gap where agents could write `[NOTEBOOK]` blocks but never read them back.

**Status:** AD-504 CLOSED. 45 new tests. 4,412 total passing (4,263 pytest + 149 vitest). 2 pre-existing bugs fixed during validation (@staticmethod on get_posts_by_author, missing @staticmethod on _write_archive_sync from BF-095).

---

**AD-505: Counselor Therapeutic Intervention** *(OSS)*

**Context:** Self-Regulation Wave item 5/6. The Counselor could observe (AD-503) and assess on circuit breaker trips (AD-495) but had no ability to act — no DM initiation, no cooldown authority, no directive issuance, no dream forcing, no recommendation pipeline. BF-096 pre-existing wiring bug: `finalize.py` used `getattr(runtime, 'ward_room_router', None)` which was always None because `runtime.ward_room_router` isn't set until after `finalize_startup()` returns.

**Decision:** Seven-part build delivering 6 intervention capabilities: (0) BF-096 fix + 4 new dependency injections (ward_room, directive_store, dream_scheduler, proactive_loop) into Counselor `initialize()`. (1) `_send_therapeutic_dm()` — programmatic DM channel creation via WardRoom API, rate-limited 1/agent/hour via `_dm_cooldowns` dict. (2) `_build_therapeutic_message()` trigger-specific templates + `_maybe_send_therapeutic_dm()` helper wired into `_on_circuit_breaker_trip()`, `_run_wellness_sweep()`, `_on_trust_update()`. (3) Cooldown reason tracking — `set_agent_cooldown(reason=)` parameter on ProactiveCognitiveLoop, `_cooldown_reasons` dict, `get_cooldown_reason()`, `clear_counselor_cooldown()`, self-monitoring context integration. (4) `_post_recommendation_to_ward_room()` — `counselor_recommendation` BridgeAlert type for Captain visibility. (5) `_issue_guidance_directive()` — COUNSELOR_GUIDANCE via DirectiveStore, 24h expiry, max 3 active per target. (6) `_apply_intervention()` orchestrator — cooldown extension (1.5x concern / 2x intervention), `force_dream()`, directive issuance, recommendation alert.

**Rationale:** Closes the Counselor's observe-but-can't-act gap. The Counselor now operates as a clinical bridge between Tier 1 self-regulation (AD-504) and Tier 3 system guardrails (circuit breaker). Therapeutic DMs are auto-sent within standing orders ("advise, don't command") — rate-limited, not gated on Captain approval. Mechanical interventions (cooldown, dream, directive) are auto-executed but visible to Captain via BridgeAlert ADVISORY/ALERT. Peer repetition detection deferred to AD-506 (detection mechanism, not intervention).

**Status:** AD-505 CLOSED. 40 new tests. 4,451 total passing (4,302 pytest + 149 vitest). BF-096 fixed. 18/18 validation checklist confirmed.

**AD-506a: Graduated System Response — Zone Model** *(OSS)*

**Context:** Self-Regulation Wave capstone (6a/6). The circuit breaker was binary — agents went from "everything fine" to "forced cooldown" with no intermediate warning. `_classify_trip_severity()` computed severity per-trip but didn't track persistent state. Standing orders said "advise, don't command" but AD-505 gave the Counselor clinical actions. BF-097 pre-existing: `get_posts_by_author()` queried `ward_room_posts`/`ward_room_threads` but actual table names are `posts`/`threads`.

**Decision:** Five-part build replacing the binary model with a persistent 4-zone state machine: (0) BF-097 fix + `CircuitBreakerConfig` Pydantic model (13 tunable fields, all previously hardcoded) + config wiring into ProactiveCognitiveLoop `set_config()`. (1) `CognitiveZone` enum (GREEN/AMBER/RED/CRITICAL) on `AgentBreakerState`. `_compute_signals()` refactor extracts signal analysis from `check_and_trip()`. `_update_zone()` manages transitions: GREEN→AMBER on rising similarity/velocity pre-trip, AMBER→RED on circuit breaker trip, RED→CRITICAL on repeated trips in window. Time-based decay (configurable per-zone). Zone history tracking (max 20). (2) `SELF_MONITORING_CONCERN` EventType + `SelfMonitoringConcernEvent` dataclass. Proactive loop emits on amber transition. Zone-aware self-monitoring context: `cognitive_zone` + `zone_note` injected for ALL Earned Agency tiers ("brains are brains"). (3) Zone-aware Counselor — subscribes to `SELF_MONITORING_CONCERN`, `_on_self_monitoring_concern()` runs lightweight assessment (trigger="amber_zone"). `_classify_trip_severity()` overridden with zone context (amber→bumped severity, critical→automatic escalation). `_on_dream_complete()` replaces `pass` with post-dream re-assessment via `_intervention_targets` tracking. Zone-aware therapeutic messaging. (4) Standing orders reconciliation: counselor.md `[Clinical Authority]` section (clinical adjustments ≠ commands). ship.md `[Cognitive Zones]` section (zone descriptions + self-correction guidance).

**Rationale:** Closes the observe→warn→intervene→verify loop. Amber zone is the key innovation — agents see their own rising similarity before the circuit breaker trips, consistent with "brains are brains" (a human would notice their own repetitive thinking). Post-dream re-assessment completes the intervention lifecycle. Standing orders reconciled to match AD-505/506a reality. Split from AD-506b (peer repetition detection + tier interaction credits) to keep builds focused.

**Status:** AD-506a CLOSED. 39 new tests. 4,490 total passing (4,341 pytest + 149 vitest). BF-097 fixed. 24/24 validation checklist confirmed.

**AD-506b: Peer Repetition & Tier Credits** *(OSS)*

**Context:** Self-Regulation Wave final item (7/7). AD-506a delivered the graduated zone model (GREEN/AMBER/RED/CRITICAL) but two gaps remained: (1) no cross-agent similarity detection — agents could echo each other without anyone noticing, (2) no positive signal tracking — the Counselor recorded deficits (concerns, wellness drops) but never credited agents for self-correcting from amber or peers for catching repetition. BF-098 pre-existing: `_save_profile_and_assessment()` called async methods without `await`, silently dropping coroutines.

**Decision:** Five-part build completing the three-tier self-regulation model: (0) BF-098 fix — made `_save_profile_and_assessment()` async, added `await` to all 4 callers. `last_zone_transition` field on `AgentBreakerState` for zone recovery detection. `ZONE_RECOVERY` EventType + proactive loop emission when zone transitions from non-green to green. (1) Peer repetition detection — `check_peer_similarity()` standalone function in `threads.py`, wired into both `create_thread()` and `create_post()`. Compares new post body against recent posts by *different* authors in the same channel via `get_recent_activity()`. `PEER_REPETITION_DETECTED` EventType + event emission. Detection only, not suppression — the post still goes through. (2) Tier interaction credits — 4 new fields on `CognitiveProfile` (`self_correction_credits`, `peer_detection_credits`, `peer_caught_credits`, `total_tier_credits`). `tier_credit` field on `CounselorAssessment`. Credit logic in `add_assessment()` accumulates credits and factors them into `alert_level` computation (credits can improve alert level). (3) Counselor event handlers — subscribes to `ZONE_RECOVERY` and `PEER_REPETITION_DETECTED`. Zone recovery handler awards self-correction credit if agent was in amber. Peer repetition handler stores episode with `intent="peer_repetition"` for the repeating agent (source="secondhand"), awards peer detection credit. (4) Schema migration — 5 `ALTER TABLE` statements for new profile/assessment columns with defaults.

**Rationale:** Completes the three-tier self-regulation model: Tier 1 (self-awareness, AD-504) → Tier 2 (peer/social regulation, AD-506b) → Tier 3 (system guardrails, AD-506a). Peer detection is non-punitive — it records a signal, not a sanction. Tier credits are the first positive cognitive health metric, counterbalancing the deficit-focused assessment model. An agent that self-corrects from amber gets credit; an agent whose repetition is caught by a peer creates a learning signal for both. The Counselor now sees the full picture: not just "what went wrong" but "what went right."

**Status:** AD-506b CLOSED. 32 new tests. 4,523 total passing (4,374 pytest + 149 vitest). BF-098 fixed. 24/24 validation checklist confirmed. **Self-Regulation Wave COMPLETE (7/7).**

**AD-531: Episode Clustering & Pattern Detection** *(OSS)*

**Context:** First AD in the Cognitive JIT pipeline (AD-464 decomposed into AD-531–539). Dream consolidation replayed episodes linearly — adjusting Hebbian weights and trust parameters — but never identified structural patterns across episodes. `extract_strategies()` (AD-383) was dead code: expected Episode fields (`agent_type`, `intent`, `outcome`, `error`) that don't exist on the actual `Episode` dataclass. The `StrategyAdvisor` reader was wired but the `strategies/` directory was always empty. Write-only dead code from top to bottom.

**Decision:** Four-part build replacing the dead strategy extraction path with embedding-based episode clustering: (0) Dead code cleanup — deleted `strategy_extraction.py` + `test_strategy_extraction.py`, removed `strategy_store_fn` param from `DreamingEngine.__init__()`, removed `store_strategies()` from `DreamAdapter`, removed wiring in `startup/dreaming.py` and `runtime.py`. `StrategyAdvisor` left in place (AD-534 replaces it). (1) `EpisodeCluster` dataclass + `cluster_episodes()` pure function in new `episode_clustering.py`. Agglomerative clustering with average-linkage, cosine distance threshold (default 0.3). Cluster metadata: centroid embedding, episode count, success rate, participating agents, intent types, first/last occurrence, variance. Success-dominant (>80%) vs failure-dominant (>50%) classification. Minimum 3 episodes per actionable cluster. (2) `EpisodicMemory.get_embeddings()` — retrieves stored embeddings from ChromaDB for given episode IDs. (3) Dream cycle integration — Step 6 replaced: fetches embeddings via `get_embeddings()`, calls `cluster_episodes()`, stores on `engine._last_clusters` (in-memory only). `DreamReport.strategies_extracted` replaced with `clusters_found` + `clusters` fields. Log-and-degrade: embedding retrieval or clustering failures don't crash dream cycle.

**Rationale:** First concrete implementation of "Active Forgetting" and "Variable Recall" from the biological memory model (AD-462). Clustering is deterministic (no LLM) — LLM arrives in AD-532 (Procedure Extraction) which immediately follows. In-memory storage only; AD-533 (Procedure Store) handles persistence. The dead code removal is overdue cleanup — `extract_strategies()` never produced output from real Episodes, making the entire strategy pipeline a no-op since AD-383. Minimum viable slice starts here: AD-531 → AD-532 → AD-533 → AD-534.

**Status:** AD-531 CLOSED. 40 new tests. 4,549 total passing (4,400 pytest + 149 vitest). 24/24 validation checklist confirmed.

**AD-532: Procedure Extraction** *(OSS)*

**Context:** Second AD in the Cognitive JIT pipeline. AD-531 produces success-dominant episode clusters, but the "how" — the specific steps an agent took to succeed — is lost. Dream consolidation adjusts Hebbian weights but never captures replayable procedures. The Cognitive Journal stores operational metadata (model, latency, tokens) but only MD5 hashes of prompts/responses, not full text. AD-532 bridges the gap: LLM-assisted extraction synthesizes deterministic procedures from Episode content (user_input, outcomes, dag_summary, reflection) across clustered episodes.

**Decision:** Four-part build introducing the first LLM call in the dreaming pipeline: (0) Wire `llm_client: BaseLLMClient` into `DreamingEngine.__init__()`, `init_dreaming()`, and runtime startup — DreamingEngine previously had no LLM access. (1) `Procedure` + `ProcedureStep` dataclasses in new `procedures.py` with full schema: name, steps (action, expected_state, fallback_action, invariants), preconditions, postconditions, origin_cluster_id, compilation_level (default 1), evolution_type (CAPTURED only), provenance (episode_ids from cluster). (2) `extract_procedure_from_cluster()` async function — builds extraction prompt with AD-541b READ-ONLY framing (`=== READ-ONLY EPISODE ===` boundaries, "reference episode IDs, not reconstruct narratives"), calls LLM at standard tier, parses structured JSON output with markdown fence handling. Returns `None` on any failure (LLM error, invalid JSON, `{"error": ...}` response). (3) Dream cycle Step 7 integration — filters success-dominant clusters only, skips clusters already in `_extracted_cluster_ids` set (dedup), calls extraction, stores results in `_last_procedures` (in-memory), adds `procedures_extracted` + `procedures` fields to `DreamReport`. Gap prediction renumbered to Step 8. Log-and-degrade: extraction failures don't crash dream cycle.

**Rationale:** CAPTURED evolution type only — FIX/DERIVED require persistent store (AD-533) and are deferred to AD-532b. Dream consolidation trigger only — reactive and proactive triggers deferred to AD-532e. In-memory storage only — AD-533 handles persistence. Standard LLM tier balances extraction quality with token cost (not deep tier). AD-541b READ-ONLY framing prevents the LLM from reconstructing or modifying original episode content. Cluster dedup ensures the same cluster isn't re-extracted across multiple dream cycles. Negative procedure extraction deferred to AD-532c. Multi-agent compound procedures deferred to AD-532d.

**Status:** AD-532 CLOSED. 29 new tests. 4,575 total passing (4,426 pytest + 149 vitest). 38/38 validation checklist confirmed.