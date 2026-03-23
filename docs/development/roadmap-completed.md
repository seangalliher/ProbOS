# Roadmap — Completed Work

*Archived from [roadmap.md](roadmap.md). Reference for completed ADs, closed bugs, and historical decisions.*

---

## Engineering Team Completed ADs

**Builder Quality Gates & Standing Orders (AD-337–341)**

*"All hands, new standing orders from the bridge."*

AD-337 proved the Builder pipeline works end-to-end but revealed systemic quality gaps: the builder committed code with failing tests, the test-fix loop was disabled in practice, and test-writing guidance was minimal. These ADs fix the pipeline and introduce ProbOS's own constitution system.

- **AD-337: Implement /ping Command** *(done)* — First successful end-to-end Builder test. Added `/ping` slash command showing system uptime, agent count, health score. Revealed pipeline gaps: commit not gated on test passage, test-fix loop disabled (no llm_client passed), "Files: 0" reporting bug for MODIFY-only builds.
- **AD-338: Builder Commit Gate & Fix Loop** *(done)* — Gate commits on test passage (don't commit broken code). Pass llm_client from api.py to enable 2-retry test-fix loop. Fix "Files: 0" reporting bug (count files_modified + files_written).
- **AD-339: Standing Orders Architecture** *(done)* — ProbOS's own hierarchical instruction system. Four tiers: Federation Constitution (universal, immutable) → Ship Standing Orders (per-instance) → Department Protocols (per-department) → Agent Standing Orders (per-agent, evolvable). `config/standing_orders/` directory with `federation.md`, `ship.md`, `engineering.md`, `science.md`, `medical.md`, `security.md`, `bridge.md`. `compose_instructions()` assembles complete system prompt at call time. Like Claude Code's `CLAUDE.md` and OpenClaw's `soul.md`, but hierarchical and evolvable. No IDE dependency.
- **AD-340: Builder Instructions Enhancement** *(done)* — Add concrete test-writing rules to Builder's hardcoded instructions: read __init__ signatures, use full import paths, trace mock coverage, match actual output format.
- **AD-341: Code Review Agent** *(done)* — CodeReviewAgent reviews Builder output against Standing Orders before commit gate. Engineering department, standard tier. Starts as soft gate (advisory, logs issues). Earns hard gate authority through ProbOS trust model. Reads standards from Standing Orders, not IDE config.
  - **Future: Hard Gate Upgrade** (absorbed from Claude Code code-review plugin, 2026-03-20) — When the reviewer earns hard-gate authority, enhance with patterns from Anthropic's code-review plugin:
    - **Parallel specialist reviewers** — Launch 3-4 independent review agents in parallel (Standing Orders compliance, bug detection, pattern adherence, historical context via git blame). Redundancy catches more issues than a single reviewer
    - **Confidence scoring** — Each finding scored 0-100. Only issues ≥80 surface to Captain. Reduces false positives that erode trust in the reviewer. Scoring considers: explicit Standing Orders match, evidence strength, whether issue is pre-existing vs introduced
    - **Validation pass** — After initial findings, a separate agent validates each issue before surfacing. "Review the review" — expensive but high-signal. Optional, activated only in hard-gate mode
    - **False positive exclusion list** — Standing Orders for the reviewer itself: don't flag pre-existing issues, linter-catchable items, pedantic nitpicks, code with lint-ignore comments
    - **Model tiering for review tasks** — Fast tier for triage (is this build worth deep review?), standard for compliance, deep for subtle bugs. Cognitive Division of Labor applied to review
- **AD-342: Standing Orders Display Command** *(done)* — `/orders` slash command showing all standing orders files with tier classification (Federation/Ship/Department/Agent), summaries, and sizes.

**Builder Failure Escalation & Diagnostic Reporting (AD-343–347)**

*"Damage report, Number One."*

AD-342's `/orders` build revealed the next pipeline gap: when the builder fails, the Captain gets a raw error dump with no classification, no context, and no actionable options. The test runner also runs the full 2254-test suite with a 120s timeout, causing spurious timeouts when only a handful of targeted tests are relevant. These ADs introduce structured failure diagnostics, smart test selection, resolution options in the HXI, and the foundation for chain-of-command escalation.

- **AD-343: BuildFailureReport & Classification** *(done)* — Structured failure report dataclass with failure categorization (timeout, test_failure, syntax_error, import_error, llm_error). Parses pytest output to extract failed test names and file:line error locations. Generates context-appropriate resolution options per category. 12 tests.
- **AD-344: Smart Test Selection** *(done)* — Two-phase test runner: targeted tests first (by file naming convention), full suite only if targeted pass. Maps `src/probos/foo/bar.py` → `tests/test_bar*.py`. Drops typical test-fix iteration from ~120s to ~5-15s. Fix loop uses targeted tests for faster retries. 6 tests. **Future enhancement:** Build classification (additive vs integration) to skip full suite entirely for new standalone files. Wave-level batching — run full suite once per build wave rather than per AD, saving ~6 min per additive build.
- **AD-345: Enriched Failure Event & Resolution API** *(done)* — Wire `BuildFailureReport` into `build_failure` WebSocket event. New `/api/build/resolve` endpoint handles: retry_extended, retry_targeted, retry_fix, commit_override, abort, investigate. Pending failure cache with 30-min expiry. 1 test.
- **AD-346: HXI Build Failure Diagnostic Card** *(done)* — Frontend rendering of structured failure report with category badge, failed tests list, collapsible error output, and resolution action buttons. Red/amber accent styling. Mirrors build proposal card pattern.
- **AD-347: Builder Escalation Hook** *(done)* — Pluggable callback on `execute_approved_build()` that fires before failure reaches the Captain. No-op initially; Phase 33 wires it to Engineering Chief → Architect → Captain cascade. Returns `BuildResult` if resolved, `None` to escalate. 4 tests.

**Builder Pipeline Guardrails (AD-360)**

*"The ship's safety systems catch what the crew might miss."*

Visiting officer builds failed 2 of 3 times by creating files in wrong directories and generating files not in the spec. AD-360 adds six structural guardrails to catch these problems automatically. Inspired by Aider (pre-edit dirty commit), Cline (shadow git checkpoints, workspace access tiers), SWE-Agent (container isolation), OpenHands (overlay mounts).

- **AD-360: Builder Pipeline Guardrails** *(done)* — Six guardrails: (1) branch lifecycle management — cleanup on failure + stale branch deletion, (2) `_validate_file_path()` — blocks traversal, absolute, forbidden, and out-of-scope paths (hard gate), (3) visiting officer disk scan filtering in `CopilotBuilderAdapter` (first line of defense), (4) build spec file allowlist warning (soft gate), (5) dirty working tree protection via `_is_dirty_working_tree()` (hard gate), (6) untracked file cleanup in `finally` block — deletes created files + empty parent dirs on failure. 10 tests.
- **AD-361: CI/CD Pipeline** *(done)* — GitHub Actions workflow with two parallel jobs: `python-tests` (Python 3.12, uv, pytest) and `ui-tests` (Node 22, npm, vitest + tsc build). Runs on push to main and PRs. CI stabilization: flaky monotonic TTL fix, ToolResult SDK fallback, SDK test skip marker.

**GPT-5.4 Code Review Findings (AD-362–364)**

*Identified by GPT-5.4 via GitHub Copilot. All findings verified against source with line numbers confirmed.*

- **AD-362: Fix Bundled Persistence** *(done)* — Silent data loss in TodoAgent, NoteTakerAgent, SchedulerAgent. `_mesh_write_file()` saw a proposal response as success without calling `commit_write()`. Fixed: call `FileWriterAgent.commit_write()` directly (personal data, no consensus needed), check return value, propagate failure. 4 tests.
- **AD-363: Fix Mock Reminder Routing** *(done)* — "remind me to..." routed to `manage_todo` instead of `manage_schedule` in MockLLMClient due to first-match-wins regex ordering. Fixed: moved `remind` phrase to scheduler regex. 1 test.
- **AD-364: Fix get_event_loop in Async Code** *(done)* — 7 call sites in shell.py and renderer.py using deprecated `get_event_loop()` inside `async def` methods, violating Standing Orders. Fixed: mechanical replacement with `get_running_loop()`.

**GPT-5.4 Code Review Findings — Round 2 (AD-365–369)**

*Second batch of GPT-5.4 findings across Runtime/Consensus, HXI/UI, Builder/Self-Mod. 9 findings triaged → 2 already addressed (AD-362, BF-004), 7 new.*

- **AD-365: Red-Team Write Verification** *(done)* — RedTeamAgent had no real handler for `write_file` intents — fell through to `verified=True` with `confidence=0.1`. Added `_verify_write()` with path traversal, forbidden path, empty path, and content size checks. 4 tests.
- **AD-366: Fix API Import Approval Callback Leak** *(done)* — API self-mod path set `_import_approval_fn` to auto-approve but never restored it in `finally` block. All future import approvals silently auto-approved. Fixed: save/restore pattern matching `_user_approval_fn`. 1 test.
- **AD-367: Move Validation Check Before Commit** *(done)* — `validation_errors` checked after commit step; with `run_tests=False`, syntax-invalid files got committed. Fixed: moved check before commit using if/elif chain. 1 test.
- **AD-368: Self-Mod Registration Rollback** *(done)* — Agent type registered in spawner/decomposer before pool creation; if pool fails, phantom type remained. Added `unregister_fn` plumbing and rollback on failure. 1 test.
- **AD-369: Fix WebSocket Protocol Detection** *(done)* — Hardcoded `ws://` in `useWebSocket.ts` breaks behind HTTPS. Dynamic protocol detection via `window.location.protocol`.

**SIF Implementation (AD-370)**

- **AD-370: Structural Integrity Field** *(done)* — Runtime service with 7 invariant checks (trust bounds, Hebbian bounds, pool consistency, IntentBus coherence, config validity, index consistency, memory integrity). Background asyncio task at 5s interval. `SIFReport` with `health_pct` property. No LLM calls.

**Automated Builder Dispatch (AD-371–374)**

*"The ship builds itself — and dispatches its own builders."*

Full automation of the Architect→Builder pipeline. Captain approves ADs, builders automatically pick up work, execute in isolated worktrees, and submit for review. No copy-paste, no manual dispatch.

- **AD-371: BuildQueue + WorktreeManager** *(done)* — Priority-ordered queue of `QueuedBuild` items with status lifecycle validation, file footprint conflict detection, cancel support. `WorktreeManager` handles async git worktree lifecycle: create, remove, collect diff, merge to main, cleanup. 20 tests.
- **AD-372: BuildDispatcher + SDK Integration** *(done)* — Core dispatch loop: watches BuildQueue, allocates worktrees, invokes CopilotBuilderAdapter, applies changes via `execute_approved_build()` with full guardrails. Configurable concurrency, Captain approve/reject actions, `on_build_complete` callback. Absorbs AD-374. 11 tests.
- **AD-373: HXI Build Dashboard** *(done)* — Real-time build queue card with engineering amber theme. `BuildQueueItem` type, `build_queue_update`/`build_queue_item` event handlers, status dots, approve/reject buttons, file footprint display.
- **AD-374: File Footprint Conflict Detection** *(absorbed into AD-372)* — `_find_dispatchable()` checks `has_footprint_conflict()` before dispatch. Overlapping specs serialized, non-overlapping run concurrently.
- **AD-375: Dispatch System Runtime Wiring** *(done)* — Wire BuildQueue, WorktreeManager, BuildDispatcher into runtime lifecycle. API endpoints: `/api/build/queue/approve`, `/api/build/queue/reject`, `/api/build/enqueue`, `GET /api/build/queue`. `_emit_queue_snapshot` broadcasts full state, `_on_build_complete` emits per-item events. HXI button URLs fixed. 9 tests.

**Crew Identity + Operations (AD-376–379)**

*"A crew isn't a list of agents — it's people with personalities, ranks, histories, and duty shifts."*

The foundational identity layer for ProbOS agents. Every crew member gets a formal profile, seeded personality, cognitive assessment record, individual standing orders, and scheduled duty shifts.

- **AD-376: CrewProfile + Personality System** *(done)* — `CrewProfile` dataclass with identity (display_name, callsign, department, role), rank (Ensign→Senior, earned via trust), `PersonalityTraits` (Big Five dimensions seeded from YAML, evolvable), `PerformanceReview` history, `ProfileStore` (SQLite persistence). Crew profile YAML seeds for 12 agent types in `config/standing_orders/crew_profiles/`. 25 tests.
- **AD-377: Watch Rotation + Duty Shifts** *(done)* — Naval-style watch system (Alpha/Beta/Gamma). `WatchManager` with duty roster, `StandingTask` (recurring department tasks with interval scheduling), `CaptainOrder` (persistent directives, one-shot or recurring). Dispatch loop executes due tasks for on-duty agents.
- **AD-378: CounselorAgent + Cognitive Profiles** *(done)* — Ship's Counselor (Bridge-level CognitiveAgent). `CognitiveProfile` per agent with `CognitiveBaseline` snapshot and `CounselorAssessment` history. Deterministic assessment: trust drift, confidence drift, Hebbian drift, personality drift → wellness score + concerns + recommendations. Alert levels (green/yellow/red). Promotion fitness assessments.
- **AD-379: Per-Agent Standing Orders** *(done)* — Tier 5 standing orders for all 12 agent types. Individual responsibilities, boundaries, personality expression. Callsigns matching crew profiles. Under 20 lines each. Evolvable via self-improvement pipeline.

**Callsign Addressing — AD-397** *(done)*

*"Wesley, report." — not "af37b1ec37ac4af49aeb45c3d80e604e, report."*

Agent IDs are implementation details. The Captain addresses crew by name or by role — and agents address each other the same way. Two addressing modes:

- **`@callsign`** → address a specific crew member by name. `@wesley scan for new projects` routes to the specific Scout agent with callsign "Wesley." Like calling a person
- **`/role`** → address the station/pool. `/scout scan for new projects` routes to any available agent in the scout pool. Like calling "Helm" — whoever is on duty answers

**Universal addressing — Captain and agents alike:**

`@callsign` is not a Captain-only privilege. Agents use the same syntax to address each other. Wesley can `@bones` to ask about an anomaly. Scotty can `@numberone` to clarify a build spec. The Counselor can `@wesley` to check in on drift patterns. Same resolution mechanism, same routing, same Ward Room delivery — regardless of whether the sender is the Captain or another agent. The callsign registry is the ship's universal directory.

Implementation:
- **Callsign registry** — at startup, build `callsign → agent_type → agent_id` lookup from YAML seed profiles + ProfileStore. Ship's Computer service on the runtime. Queryable by any agent via `resolve_callsign()`
- **NL resolution** — decomposer recognizes `@callsign` mentions in natural language input. Resolves to specific agent routing (bypasses pool broadcast, targets individual)
- **Agent-side resolution** — agents include `@callsign` in Ward Room messages. Ward Room resolves callsign to agent_id via the registry before delivery. Agents never need to know IDs
- **Shell `@` prefix** — `@wesley report` in the command surface. Tab-completion of callsigns
- **`/role` already works** — existing `/scout`, `/build`, etc. slash commands already address pools. No change needed
- **HXI display** — Bridge panel, notifications, pool views show callsigns alongside (or instead of) agent IDs. Scout report should say "Wesley" not `af37b1ec...`
- **Ambiguity handling** — if multiple agents share a callsign (e.g., scaled pool with 3 builders all "Scotty"), `@scotty` routes to the healthiest/most trusted. Or each gets a unique callsign variant (Scotty-1, Scotty-2)

**1:1 Crew Sessions:**

The Captain doesn't just issue one-shot commands — they have conversations. "Wesley, give me a check-in report" → "What about that repo you flagged yesterday?" → "Keep an eye on it." This is the Captain's office hours with individual crew members.

- **`@wesley` opens a 1:1 session** — subsequent messages route directly to that agent (bypassing the Decomposer) until the Captain exits. Like DMs vs. a channel
- **Persistent conversation context** — the 1:1 maintains message history so the agent can reference earlier exchanges. Context scoped to the session. Stored in EpisodicMemory with session tag
- **Agent responds as themselves** — Wesley's personality, standing orders, and callsign inform the response. Not the Ship's Computer paraphrasing. "Aye Captain, here's what I've been tracking..." not "The scout agent reports..."
- **Check-in reports** — any agent can be asked for a status check-in during a 1:1. Agent reports what they've done recently (from CognitiveJournal), current observations, anything flagged for Captain's attention
- **Session indicator** — HXI shows who the Captain is talking to. Command surface shows crew member's callsign and department color. Bridge panel shows "1:1 with Wesley (Science)"
- **Return to bridge** — `/bridge` or `@computer` exits the 1:1 and returns to normal Ship's Computer routing. Like hanging up a call

---

## Northstar I — Automated Build Pipeline

**Automated Build Pipeline — Northstar I (AD-311+) ✓ COMPLETE**

*"The ship builds itself — with the Captain's approval."*

The Architect and Builder agents form an automated design-and-build pipeline. The Architect reads full source via CodebaseIndex (import graphs, caller analysis, API surface verification), produces structured proposals with embedded BuildSpecs, and the Builder executes them with test-fix retry (AD-314). Ship's Computer identity grounds the Decomposer's self-knowledge (AD-317), with a four-level progression: SystemSelfModel (AD-318), Pre-Response Verification (AD-319), and Introspection Delegation (AD-320). A GPT-5.4 code review (AD-325–329) hardened runtime safety, validator correctness, and HXI resilience. All 18 steps complete.

Inspired by: SWE-agent (Princeton NLP) for tool design, Aider for repo maps, Agentless (UIUC) for localize-then-repair pipelines, AutoCodeRover for call graph analysis, LangChain Open SWE/Deep Agents for middleware-based determinism and mid-run input injection patterns.

- **AD-311: Architect Deep Localize** *(done)* — 3-step localize pipeline: fast-tier LLM selects 8 most relevant files from 20 candidates, reads full source (up to 4000 lines), auto-discovers test files, callers, and verified API surface.
- **AD-312: CodebaseIndex Structured Tools** *(done)* — `find_callers()`, `find_tests_for()`, `get_full_api_surface()` methods. Expanded `_KEY_CLASSES` with CodebaseIndex, PoolGroupRegistry, Shell.
- **AD-315: CodebaseIndex Import Graph** *(done)* — AST-based `_import_graph` and `_reverse_import_graph` built at startup. `get_imports()` and `find_importers()` query methods. Architect Layer 2a+ traces imports of selected files, expanding context up to 12 files.
- **AD-313: Builder File Edit Support** *(done)* — Search-and-replace `===SEARCH===`/`===REPLACE===` MODIFY mode in `execute_approved_build()`. Builder `perceive()` reads target files for accurate SEARCH blocks. `ast.parse()` validation after writes. Old `===AFTER LINE:===` format deprecated.
- **AD-317: Ship's Computer Identity** *(done)* — The Decomposer is the Ship's Computer (LCARS, TNG/Voyager). PROMPT_PREAMBLE with 6 grounding rules, dynamic System Configuration section with tier counts, runtime_summary injection as SYSTEM CONTEXT, confabulating examples fixed. Level 1 of self-knowledge grounding (prompt rules).
- **AD-314: Builder Test-Fix Loop** *(done)* — After writing code, run tests. On failure, feed errors back to the LLM for fix attempts (up to 2 retries). `_run_tests()` helper extracted, `_build_fix_prompt()` for fix context, `max_fix_attempts` parameter on `execute_approved_build()`, `fix_attempts` tracked in BuildResult. Two flaky network tests fixed with proper mocks.
- **AD-316a: Architect Proposal Validation + Pattern Recipes** *(done)* — New `_validate_proposal()` method with 6 programmatic checks (non-empty required fields, non-empty test_files, target/reference file paths verified against file tree with directory pattern matching, valid priority, description minimum length). Advisory warnings in `act()` result — non-blocking. 3 Pattern Recipes (New Agent, New Slash Command, New API Endpoint) appended to `instructions` with file paths, reference files, and structural checklists. Zero LLM calls. 14 tests.
- **AD-318: SystemSelfModel** *(done)* — `SystemSelfModel` dataclass in `cognitive/self_model.py`: identity (version), topology (pool_count, agent_count, per-pool `PoolSnapshot` with name/type/count/department, departments, intent_count), health (system_mode active/idle/dreaming, uptime_seconds, recent_errors capped at 5, last_capability_gap). `to_context()` serializes to compact text (<500 chars). `_build_system_self_model()` on runtime replaces `_build_runtime_summary()`. `_record_error()` helper and capability gap tracking wired into `process_natural_language()`. Level 2 of self-knowledge grounding (rules → **data** → verification → delegation). 9 new + 1 updated tests.
- **AD-319: Pre-Response Verification** *(done)* — `_verify_response()` method on runtime with 5 programmatic checks: pool count claims, agent count claims, fabricated department names (context-aware regex), fabricated pool names (with generic word exclusion), system mode contradictions. Appends `[Note: ...]` correction footnote with verified facts when violations detected — non-blocking, zero-LLM. Wired at both response paths: no-nodes `dag.response` and nodes `reflection` (self_model passed through `_execute_dag()`). Warning logging on violations. Level 3 of self-knowledge grounding (rules → data → **verification** → delegation). 14 tests.
- **AD-320: Introspection Delegation** *(done)* — `_grounded_context()` on IntrospectionAgent builds detailed verified text from `SystemSelfModel` (per-pool breakdowns by department, intent listing, health). 4 intent handlers (`_agent_info`, `_system_health`, `_team_info`, `_introspect_system`) enriched with `grounded_context` key. REFLECT_PROMPT rule 7 treats it as VERIFIED SYSTEM FACTS. `_summarize_node_result()` preserves outside truncation. Level 4 of self-knowledge grounding (rules → data → verification → **delegation**). 12 tests.

#### Runtime Safety & Correctness (GPT-5.4 Code Review — AD-325 through AD-329)

*Identified by GPT-5.4 deep code review. All findings verified against source with line numbers confirmed.*

- **AD-325: Escalation Tier 3 Timeout** *(done)* — `_tier3_user()` now wraps user callback in `asyncio.wait_for(timeout=user_timeout)` (default 120s). On timeout, returns `EscalationResult(resolved=False, user_approved=None)` with descriptive reason. User-wait seconds accumulated on timeout for accurate DAG deadline accounting. New `user_timeout` constructor parameter on `EscalationManager`. 5 tests.
- **AD-326: API Task Lifecycle & WebSocket Hardening** *(done)* — `_background_tasks` set tracks all pipeline tasks with `_track_task()` helper (7 call sites converted). `_safe_send()` inner coroutine catches per-client `send_json()` failures and prunes dead WebSocket clients. `GET /api/tasks` endpoint for Captain visibility. FastAPI `_lifespan` handler drains/cancels tasks on shutdown. 5 tests.
- **AD-327: CodeValidator Hardening** *(done)* — (a) `_check_schema()` now rejects code with multiple `BaseAgent` subclasses (was silently picking first). (b) New `_check_class_body_side_effects()` scans class bodies for bare function calls, loops, and conditionals that execute at import time. Both early-return patterns consistent with existing validator flow. 4 tests.
- **AD-328: Self-Mod Durability & Bloom Fix** *(done)* — (a) Knowledge store and semantic layer post-deployment failures now logged with `logger.warning(exc_info=True)` instead of bare `except: pass`. Partial failure warnings propagated in `self_mod_success` event and displayed to Captain. (b) `self_mod_success` event includes `agent_id`. Bloom stores `agent_id` (falling back to `agent_type`), lookup uses `a.id || a.agentType`. 3 Python + 1 Vitest tests.
- **AD-329: HXI Canvas Resilience & Component Tests** *(done)* — `connections.tsx` pool centers cached in `useMemo` keyed on `agentCount`, reactive `agents` subscription replaced with ref + count-based re-render pattern. `CognitiveCanvas.tsx` and `AgentTooltip.tsx` action subscriptions (`setHoveredAgent`, `setPinnedAgent`) replaced with `useStore.getState()` calls. 8 new Vitest tests covering pool center computation, connection filtering, tooltip state, and animation event clearing. 30 Vitest total.

---

## Northstar II Phase 1 — Transporter Pattern

#### Phase 1: Transporter Pattern (Builder — AD-330 through AD-336)

*The first concrete implementation. Prove the architecture in the Builder, then generalize.*

The Builder faces the most acute version of the bottleneck: generating code for 1000+ line files in a single LLM call. The Transporter Pattern applies decompose-execute-merge to code generation — MapReduce for building software.

```
BuildBlueprint ─→ ChunkDecomposer ─→ ┌─ Chunk 1 ──→ LLM ──→ Output 1 ─┐
                                      │  Chunk 2 ──→ LLM ──→ Output 2  │──→ Assembler ──→ Validator ──→ Final
                                      │  Chunk 3 ──→ LLM ──→ Output 3  │
                                      └─ Chunk N ──→ LLM ──→ Output N ─┘
```

**Components (starship transporter metaphor):**

1. **Pattern Buffer (BuildBlueprint)** — Enhanced specification format that captures function signatures, interface contracts, and inter-chunk dependencies. The shared "truth" that all chunks reference. Extends the existing BuildSpec with structural metadata the decomposer needs.

2. **Dematerializer (ChunkDecomposer)** — Analyzes the BluePrint and breaks it into independent ChunkSpecs. Each chunk specifies: what to generate (a function, a class, a test block), what context it needs (interface signatures, imports, type definitions), and what it produces (function signature, exports). The decomposer uses CodebaseIndex and import graph data to identify natural seams.

3. **Matter Stream (Parallel Chunk Execution)** — Multiple Builder LLM calls run simultaneously. Each chunk gets only its required context (interface contracts + minimal surrounding code), keeping every call well within context budget. Uses `asyncio.gather()` for parallel execution with per-chunk timeout.

4. **Rematerializer (ChunkAssembler)** — Merges chunk outputs into unified file changes. Handles import deduplication, ordering (classes before functions that reference them), and conflict detection when two chunks modify the same region.

5. **Heisenberg Compensator (Interface Validator)** — AST-based verification that assembled code is correct: function signatures match their declarations, imports resolve, cross-chunk references are consistent, type annotations align. Catches errors that arise from independent generation. Zero-LLM validation pass.

6. **HXI Integration** — Visualize chunks on the Cognitive Canvas as parallel transporter streams. Show decomposition plan, per-chunk generation progress, assembly result with per-chunk attribution. Captain can inspect individual chunks before approving the assembled result.

**AD Breakdown:**

- **AD-330: BuildBlueprint & ChunkSpec** *(done)* — New data structures extending BuildSpec. `BuildBlueprint` adds `interface_contracts` (function signatures, class APIs that chunks must conform to), `shared_imports`, `shared_context`, and `chunk_hints` (suggested decomposition boundaries). `ChunkSpec` captures what to generate, required context, expected output signature, and dependencies on other chunks. `ChunkResult` uses a **Structured Information Protocol** (adapted from LLM×MapReduce): `generated_code` (extracted information), `decisions` (rationale — why specific implementation choices were made), `output_signature` (what was actually produced), and `confidence: int` (1-5, reflecting contextual completeness — chunks with full interface contracts score higher than those working from minimal hints). Confidence scores are critical for conflict resolution in assembly. `validate_chunk_dag()` uses Kahn's algorithm for cycle detection. `get_ready_chunks()` returns chunks whose dependencies are satisfied. `create_blueprint()` factory. All dataclasses in `cognitive/builder.py`.

- **AD-331: ChunkDecomposer** *(done)* — `decompose_blueprint()` async function: fast-tier LLM analyzes BuildBlueprint and produces ChunkSpec list. Builds AST outlines of target files, gathers import context from CodebaseIndex (optional). Parses JSON response, normalizes `depends_on` references. Validates DAG (no cycles) and coverage (adds catch-all chunks for uncovered files). `_build_chunk_context()` helper builds L1-L3 context slices (interface contracts, shared imports, AST outline). `_fallback_decompose()` robust fallback: one chunk per target file, one per test file. Three fallback triggers: LLM error, invalid JSON, cyclic DAG.

- **AD-332: Parallel Chunk Execution** *(done)* — `execute_chunks()` wave-based parallel execution via `asyncio.gather()`. Independent chunks run concurrently, dependent chunks wait for prerequisites via `get_ready_chunks()`. `_execute_single_chunk()` with deep-tier LLM, `asyncio.wait_for()` per-chunk timeout, configurable retry count. `_build_chunk_prompt()` assembles focused per-chunk prompt with context slices and dependency outputs. `_parse_chunk_response()` extracts file blocks, DECISIONS rationale, CONFIDENCE score (1-5 clamped). Partial success is valid — assembler handles incomplete results.

- **AD-333: ChunkAssembler (Rematerializer)** *(done)* — Zero-LLM static assembly of ChunkResults into unified file-block format. `assemble_chunks()` merges per-file CREATE blocks (import dedup via `_merge_create_blocks()`) and MODIFY blocks (replacement list concat). Confidence-weighted ordering (higher-confidence chunk content first). Partial assembly (failed chunks skipped). `assembly_summary()` produces debug/HXI metrics. Output format compatible with `execute_approved_build()` — downstream pipeline unchanged. 24 tests.

- **AD-334: Interface Validator (Heisenberg Compensator)** *(done)* — Zero-LLM AST-based post-assembly verification. `validate_assembly()` runs 5 check categories: syntax validity (`ast.parse`), duplicate top-level definitions, empty MODIFY search strings, interface contract satisfaction, confidence-aware unresolved name detection (stricter for chunks ≤2). `ValidationResult` dataclass with per-chunk error attribution via `_find_chunk_for_file()`. `_find_unresolved_names()` conservative name resolution (builtins, imports, parameters excluded). 15 tests.

- **AD-335: HXI Transporter Visualization** *(done)* — Optional `on_event` callbacks on `decompose_blueprint()` and `execute_chunks()` emit `transporter_decomposed`, `transporter_wave_start`, `transporter_chunk_done`, `transporter_execution_done`. `_emit_transporter_events()` helper emits `transporter_assembled` and `transporter_validated`. Frontend: `TransporterProgress` state in useStore.ts, 6 event handler cases with Star Trek-themed chat panel messages. Canvas "matter stream" visualization deferred. 8 tests.

- **AD-336: End-to-End Integration & Fallback** *(done)* — `_should_use_transporter()` decision function (>2 targets, >20K context, >2 impl+test). `transporter_build()` orchestrates full pipeline returning `_parse_file_blocks()`-format output. `BuilderAgent.perceive()`/`decide()`/`act()` augmented with Transporter branch + graceful fallback. `execute_approved_build()` unchanged. 12 tests.

---

## Mission Control Completed ADs

**AD-316: AgentTask Data Model + TaskTracker Service** *(done)*

Unified task lifecycle tracking. `TaskTracker` service (SIF/BuildQueue pattern), `AgentTask` dataclass with full lifecycle (queued→working→review→done/failed), `TaskStep` with timing, step_progress (current/total), WebSocket events (`task_created`/`task_updated`), frontend `AgentTaskView` types and store wiring. 30 tests.

**AD-321: Activity Drawer (React)** *(done)*

Slide-out panel from right edge of HXI. Three collapsible sections: Needs Attention (amber, action buttons, always expanded), Active (working tasks with step progress bars and `neural-pulse` animation, always expanded), Recent (done/failed, most recent first, capped at 10, collapsed by default). Task cards with department color left border stripe, status dot, type badge, truncated title, agent type, department, elapsed time, AD number. Click to expand: full title, step checklist with status icons, progress bar, Approve/Reject buttons, error text, metadata display. Glass panel styling, ACTIVITY toggle button with attention count badge. `ActivityDrawer.tsx` (new, 351 lines), `IntentSurface.tsx` modified for toggle + rendering. Consumes `agentTasks` from TaskTracker (AD-316) — no backend changes.

**AD-322: Kanban Board View** *(done)*

Mission Control Kanban dashboard — 4-column board (Queued → Working → Review → Done). `MissionControl.tsx` with `TaskCard` component showing department color coding, AD numbers, agent type, elapsed time, status pulse animation. Approve/Reject buttons on review-status items. `MissionControlTask` type derived from existing `BuildQueueItem` via `buildQueueToTasks()` — no new backend endpoints needed. Toggle button in HXI header switches between standard view and Mission Control overlay. Extensible to non-build task types (design, diagnostic, assessment) via `MissionControlTask.type`.

Previously planned features for future iteration:
- Columns: `Queued` → `Working` → `Needs Review` → `Done`
- Cards show: agent type icon, task title, team color, elapsed time, step progress bar
- Click card to expand into full detail panel: original prompt, step-by-step progress, file diffs (build tasks), proposal text (design tasks), action buttons (Approve / Reject / Respond)
- Cards auto-move between columns as task state changes
- Filter by team (Science, Engineering, Medical, etc.) or agent type
- "Done" column auto-archives after configurable time

**AD-323: Agent Notification Queue** *(done)*

Implemented: `AgentNotification` dataclass + `NotificationQueue` service in `task_tracker.py`. `Runtime.notify()` convenience method with auto-lookup of agent_type/department. `build_state_snapshot()` includes `notifications` + `unread_count`. Two API endpoints: `POST /api/notifications/{id}/ack` and `POST /api/notifications/ack-all`. `NotificationDropdown` React component with glass panel styling, type-colored left borders (info=blue, action_required=amber, error=red), relative time, click-to-ack, mark-all-read. Bell button (`NOTIF`) at `right: 210` with unread count badge. Zustand: `notifications: NotificationView[]` state with `notification`/`notification_ack`/`notification_snapshot` event handlers + snapshot hydration. 12 pytest + 4 vitest tests.

**AD-324: Orb Hover Enhancement** *(done)*

Upgrade the existing system health orb with per-agent hover preview:

- When hovering over an agent representation in the orb, show a tooltip with: current task prompt (truncated), current step label, elapsed time, progress fraction (step 3 of 5)
- Visual indicator on the orb when any agent requires Captain attention (pulsing amber)
- Click-through from orb tooltip to the Activity Drawer card for that agent

**AD-387: Unified Bridge — Single Panel HXI Redesign** *(done)*

Replace three separate panels (NOTIF, ACTIVITY, MISSION CTRL) with a single BRIDGE button and unified command panel. Bridge panel (380px right sidebar) has five priority-ordered sections: Attention (merged `requires_action` tasks + `action_required` notifications, always expanded), Active (working tasks), Notifications (info/error), Kanban (compact inline, expandable to main viewer), Recent (done/failed). Empty sections auto-hide. Shared card components extracted into `bridge/` subdirectory. Main viewer switches between 3D canvas and full kanban via `mainViewer` state. ViewSwitcher appears top-left when non-canvas view active. Old components deleted: ActivityDrawer, NotificationDropdown, MissionControl. `bridgeOpen` + `mainViewer` replace `missionControlView` + `activityDrawerOpen` in Zustand store.

#### HXI Glass Bridge — Progressive Enhancement

*"A sheet of frosted glass over a living neural mesh — the Captain's bridge for a starship that runs on agents, not engines."*

The Glass Bridge layers a frosted working surface over the existing orb mesh. Three depth layers: Backdrop (3D mesh, z=0), Glass (task/collaboration surface, z=1), Controls (Bridge panel + Command Surface, z=2). The mesh is never replaced — the glass is translucent, the orbs breathe beneath. Each phase builds on the current HXI. Full design spec: `docs/design/hxi-glass-bridge.md`.

**AD-388: Glass Overlay & Center Task Cards** *(done)*

Frosted glass layer over the canvas with center task card(s). `GlassLayer.tsx` renders at z-index 5 between canvas and controls. Dynamic frost level (backdrop-filter blur scales 0→2→4→6px with task count). Multi-task constellation layout (1-5+ tasks arranged spatially). `GlassTaskCard.tsx` with glass morphism, department-colored left border, progress bar, JetBrains Mono system data. Attention tasks elevated (-8px) with amber pulse animation. Click-through opens Bridge panel. Noise texture overlay. 9 new vitest tests.

**AD-389: DAG Visualization** *(done)*

`GlassDAGNodes.tsx` renders step nodes radially around expanded task cards. 28px circles with status-colored borders and icons (done=green filled, in_progress=pulsing dept color, pending=ghosted, failed=red). SVG dependency lines connecting sequential nodes. Hover tooltips show step label and duration. Single-click card → expand steps, double-click → open Bridge panel. `expandedGlassTask: string | null` in store (one expanded at a time). Staggered fade-in animation (80ms per node). 7 new vitest tests.

**AD-390: Ambient Intelligence & Bridge States** *(done)*

Three bridge states (idle/autonomous/attention) derived from agentTasks + notifications. `ContextRibbon.tsx` HUD strip at top with bridge state dot, agent count, active tasks, attention count, system mode. Ambient edge glow (inset box-shadow: cyan→gold→amber, 1.2s transition). `BriefingCard.tsx` return-to-bridge summary after 3+ min inactivity (auto-dismiss 8s). Completion celebrations: department-colored bloom (600ms) on task status → done. 11 new vitest tests.

**AD-391: Cyberpunk Atmosphere Layer** *(done)*

Opt-in visual effects: `ScanLineOverlay.tsx` (CSS repeating gradient, intensity-adjustable), `DataRainOverlay.tsx` (canvas hex characters colored by bridge state, Ctrl+Shift+D toggle), chromatic aberration (inline SVG filter with feColorMatrix/feOffset). Luminance ripple (80ms left-to-right sweep on bridge state change, always on). Sound engine: `playStepComplete` ascending chords, `playBridgeHum` continuous ambient per state, `playCaptainReturn` welcoming chime. All visual effects off by default, preferences persisted to localStorage. 10 new vitest tests.

**AD-392: Adaptive Bridge** *(done)*

Trust-driven progressive reveal: `trustBand()` categorizes agents into low/medium/high with corresponding visual treatment (prominent→standard→condensed). Command Surface breathing via IntentSurface: pill recedes to 80x4px glow line during autonomous mode when mouse is far, swells on 200px proximity. Captain's Gaze: throttled mouse tracking (100ms) promotes nearest task card with scale(1.03) + glow. `useBreakpoint()` hook adapts layout across 5 viewport ranges. 16 new vitest tests.

---

## Cognitive Evolution Concrete ADs

### Cognitive Evolution — Concrete ADs (Phase 28b)

*"The biggest structural gap is that a sentiment agent learning doesn't help the file agent."*

Six ADs that close the gaps between the theoretical Cognitive Evolution framework above and buildable code. Identified via Nooplex emergence criteria gap analysis. These make the existing data (ring buffers, episodic memory, dream cycles) actually useful for cross-agent learning.

**Wave 1 (parallel, no shared files):**

**AD-380: EmergentDetector Trend Regression** *(done)* — Compute slopes over the snapshot ring buffer: `tc_n_slope`, `entropy_slope`, `cluster_stability_index`, `trust_convergence_rate`. Simple linear regression (pure Python, no numpy). `TrendReport` dataclass with direction (rising/stable/falling), r_squared confidence, significance test. Replace list with `collections.deque`. Wire into `detect_anomalies()` output. 12 tests.

**AD-382: ServiceProfile — Learned External Service Modeling** *(done)* — Replace hardcoded `_KNOWN_RATE_LIMITS` in HttpFetchAgent with SQLite-backed `ServiceProfile` per domain. Learned `min_interval`, latency percentiles (EMA), error rate, reliability history. Profiles persist across restarts. `ServiceProfileStore` (CrewProfile pattern). Seed intervals become defaults, overridden by learned data. 17 tests.

**Wave 2:**

**AD-381: InitiativeEngine — SIF → Remediation Proposals** *(done)* — Bridge SIF (read-only monitoring) and the self-mod pipeline. New Ship's Computer service monitors SIF violations, EmergentDetector falling trends (from AD-380), Counselor red/yellow alerts. When triggers persist for N consecutive checks, generates `RemediationProposal` with trust-gated execution: AUTO (diagnose, alert_captain), COMMANDER (scale, recycle), CAPTAIN (patch). Fails-open, no LLM calls. (~300 lines + 18 tests).

**Wave 3 (sequential chain):**

**AD-383: Strategy Extraction — Dream-Derived Transferable Patterns** *(done)* — New dream pass after trust consolidation. Scans episodic memory for cross-agent recurring patterns: error→recovery across agent types, high-confidence intent patterns across agents, intent co-occurrence sequences. Outputs `StrategyPattern` objects stored in KnowledgeStore. The dream cycle literally extracts crew wisdom from experience. (~250 lines + 15 tests).

**AD-385: Capability Gap Prediction — Proactive Self-Mod** *(done)* — New dream pass after strategy extraction. Analyzes episodic memory for: repeated low confidence on an intent type, repeated fallback (no intent matched), partial DAG coverage (one node consistently fails). Outputs `CapabilityGapPrediction` objects surfaced to Captain. The system says "I've noticed we struggle with X — shall I design a specialist?" instead of waiting for the user to hit the wall. (~200 lines + 14 tests).

**AD-384: Strategy Application — Cross-Agent Knowledge Transfer** *(done)* — `StrategyAdvisor` queries KnowledgeStore for strategies matching the current intent, formats them as "[CREW EXPERIENCE]" context for the LLM. New `REL_STRATEGY` relationship type on HebbianRouter tracks which strategies work for which agents. Strategies that help get reinforced; strategies that don't get decayed. MemoryForge (Long Horizon) becomes a consumer of the strategies collection. (~200 lines + 12 tests).

| AD | Title | Wave | Depends On | Est. Lines | Est. Tests |
|----|-------|------|------------|-----------|-----------|
| AD-380 | EmergentDetector Trends | 1 | None | ~150 | 12 |
| AD-382 | ServiceProfile | 1 | None | ~200 | 14 |
| AD-381 | InitiativeEngine | 2 | AD-380 | ~300 | 18 |
| AD-383 | Strategy Extraction | 3 | None | ~250 | 15 |
| AD-385 | Capability Gap Prediction | 3 | AD-383 | ~200 | 14 |
| AD-384 | Strategy Application | 3 | AD-383 | ~200 | 12 |
| AD-386 | Runtime Directive Overlays | 4 | AD-376 (Rank) | ~200 | 30 |

**Nooplex emergence impact:** AD-380 + AD-385 directly advance emergence criteria (trend measurement, proactive capability expansion). AD-383 + AD-384 close the biggest structural gap (cross-agent transfer learning). AD-381 + AD-382 create practical value while building infrastructure those criteria require.

**AD-386: Runtime Directive Overlays — Evolvable Chain-of-Command Instructions** *(done)* — Instructions today are static files; no crew member can issue new directives at runtime. This AD adds a persistent tier 6 instruction layer: `RuntimeDirective` objects issued through the chain of command (Captain→any, Bridge→advisory, Chief→subordinates, Self→self, Peer→suggestion). SQLite-backed `DirectiveStore`, authorized by `Rank` from CrewProfile. Self-updates tiered by trust: Ensign needs Captain approval, Lieutenant+ auto-approved (Counselor monitors drift). Wired into `compose_instructions()` as an additional layer after personal standing orders. Shell commands `/order` and `/directives`. (~200 lines + 30 tests). Build prompt: `prompts/runtime-directives.md`.

---

## Bug Tracker — Closed Issues

### BF-001: Self-Mod False Positive on Knowledge Questions

**Severity:** Medium — UX confusion, not data loss
**Found:** 2026-03-18 (Captain testing)
**Component:** Decomposer → Runtime self-mod pipeline → IntentSurface UI

**Symptom:** "Build Agent" / "Design Agent" / "Skip" buttons appear after conversational responses that have nothing to do with agent building (e.g., financial advice, general knowledge questions).

**Root Cause Chain:**

1. **Decomposer rule 12b** (decomposer.py line 113) classifies all "knowledge questions" as tasks requiring intelligence → returns `capability_gap: true` when no matching intent exists. This is too broad — financial advice and trivia are not missing system capabilities.
2. **Runtime self-mod filter** (runtime.py line 1524-1537) triggers `_extract_unhandled_intent()` on every capability gap in API mode. No check for whether building an agent is actually appropriate.
3. **`_extract_unhandled_intent()`** (runtime.py line 3057-3120) always succeeds — the LLM prompt assumes every unhandled request should become a new agent. Will happily propose `financial_advisor`, `recipe_generator`, etc.

**Fix Strategy:** Three-layer fix, any one of which would prevent the false positive:

1. **(Recommended) Refine rule 12b** — Distinguish between "system capability gap" (trust scoring, monitoring, scheduling — agent-worthy) and "general knowledge question" (finance, weather, recipes — answer conversationally). The decomposer should answer general knowledge questions directly in the response field with `capability_gap: false`.
2. **Add relevance filter in runtime** — Before calling `_extract_unhandled_intent()`, check if the gap is system-relevant (mentions ProbOS concepts, agents, pools, intents) vs. general knowledge. Only propose self-mod for system-relevant gaps.
3. **Let `_extract_unhandled_intent()` return null** — Add an instruction to the LLM prompt: "If this request is a general knowledge question that doesn't warrant a permanent agent, return an empty object." This is the weakest fix (LLM-dependent) but adds a safety net.

**Files to modify:** `src/probos/cognitive/decomposer.py` (rule 12b), `src/probos/runtime.py` (`_extract_unhandled_intent` call site and/or prompt)

### BF-002: Agent Orbs Escape Pool Group Spheres on Cognitive Canvas

**Severity:** High — visual corruption of the primary HXI visualization
**Found:** 2026-03-18 (Captain testing)
**Component:** Cognitive Canvas → useStore.ts `computeLayout()` → `agent_state` event handler

**Symptom:** Agent orbs (glowing spheres representing individual agents) explode outward and scatter far beyond their department wireframe geodesic spheres (Medical, Engineering, Science, etc.) on the Cognitive Canvas.

**Root Cause Chain:**

1. **`agent_state` handler loses pool group data** (useStore.ts line 423) — When any agent changes state (spawning, active, degraded, recycling), the handler calls `computeLayout(agents)` with NO `poolToGroup` or `poolGroups` parameters. This makes `computeLayout()` take the flat Fibonacci fallback branch (line 75) instead of the grouped cluster layout (line 110). All agents are repositioned on large tier-based spheres (radii 3.5/5.5/7.5) while the geodesic shells remain at their cluster positions (radius ~6.0).
2. **No containment force or boundary clamping** — There is no physics simulation, spring system, or boundary enforcement anywhere in the canvas code. Agents are placed once by `computeLayout()` and never constrained. If placed wrong, they stay wrong.
3. **Small group margin overflow** (minor) — For groups with 1-3 agents, the visual orb radius (up to 0.50 units) can exceed the shell's 15% margin over placement radius. E.g., 1-agent group: clusterRadius=1.2, shell=1.38, but orb edge can reach 1.70.

**Fix Strategy:**

1. **(Primary) Persist `poolToGroup` and `poolGroups` in Zustand state** on `state_snapshot` receipt. In the `agent_state` handler, pass the stored values to `computeLayout()` so agents always use the grouped layout path.
2. **(Alternative) Skip re-layout on agent state changes** — For state transitions that don't add/remove agents, just update the agent's non-position fields (status, confidence, etc.) in place. Only re-run `computeLayout()` when pool membership actually changes.
3. **(Enhancement) Add soft containment** — After layout, clamp agent positions to stay within `clusterRadius * 0.95` of their group center. Provides a safety net even if future layout changes introduce drift.

**Files to modify:** `ui/src/store/useStore.ts` (`agent_state` handler line 423, `computeLayout()` call)

### BF-003: "Run Diagnostic" Bypasses Vitals Monitor

**Severity:** Medium — broken user experience, medical team partially unreachable
**Found:** 2026-03-18 (Captain testing)
**Component:** Medical pool → IntentBus routing → Diagnostician

**Symptom:** When the user asks "perform a diagnostic and suggest system performance optimization opportunities," the Diagnostician responds by asking the user to provide health alert data (severity, metric, value, threshold, affected components) instead of proactively scanning the system.

**Root Cause Chain:**

1. **No proactive scan intent** — The medical team has two entry points: `medical_alert` (from VitalsMonitor threshold breaches) and `diagnose_system` (on-demand). But `diagnose_system` still expects structured alert data as input, not a high-level command.
2. **Missing orchestration** — There is no workflow that chains VitalsMonitor scan → Diagnostician analysis → unified report. The Diagnostician can't trigger a VitalsMonitor scan because the VitalsMonitor is a HeartbeatAgent (runs on a timer, doesn't handle intents).
3. **No department lead / CMO pattern** — Every pool treats agents as flat peers. There is no "Chief Medical Officer" that can receive a high-level bridge order ("run a full diagnostic"), orchestrate the right specialists in sequence, and return a unified answer. This is a broader architectural gap affecting all departments.

**Fix Strategy:**

1. **(Short-term) Add a `full_diagnostic` intent handler to Diagnostician** — When no alert data is provided, the Diagnostician proactively calls VitalsMonitor's metric collection functions directly (they're pure code, no LLM needed) to gather current system state, then runs its normal LLM analysis on the collected data.
2. **(Medium-term) Department Lead pattern** — Add a `lead: bool` field to pool agent configuration. The lead agent receives high-level commands from the bridge and orchestrates its department's specialists. For Medical: Diagnostician becomes the CMO (lead). For Engineering: BuilderAgent or a new ChiefEngineer. For Science: ArchitectAgent. This is a broader architectural enhancement that would benefit all departments.
3. **(Long-term) Ward Room integration (Phase 33)** — Department leads participate in the Ward Room for cross-department coordination. Bridge orders route to department leads, not individual specialists.

**Files to modify:** `src/probos/agents/medical/diagnostician.py` (add proactive scan path), potentially `src/probos/substrate/pool.py` (lead agent concept)

### BF-004: Transporter HXI Visualization Not Rendered

**Severity:** Medium — data flow works, visual rendering missing
**Found:** 2026-03-19 (Captain testing)
**Component:** HXI → IntentSurface.tsx → TransporterProgress state

**Symptom:** When the Transporter Pattern activates during a build, chunk decomposition and execution are tracked in the Zustand store (`transporterProgress`) and announced in chat messages ("Transporter: decomposed into N chunks"), but no visual progress card renders in the IntentSurface component. The user only sees chat text, not a structured visualization with chunk statuses.

**Root Cause:** AD-335 (HXI Transporter Visualization) created the complete data flow — 6 WebSocket event types (`transporter_decomposed`, `transporter_wave_start`, `transporter_chunk_done`, `transporter_execution_done`, `transporter_assembled`, `transporter_validated`), `TransporterProgress` Zustand state with per-chunk status tracking, and chat messages. However, `IntentSurface.tsx` has no rendering block that reads `transporterProgress` from the store. The state updates correctly but nothing draws it.

**Fix:** Add a `TransporterProgress` card to `IntentSurface.tsx` following the build proposal card pattern. Show: chunk list with per-chunk status (pending/executing/done/failed), wave progress, assembly phase indicator. Use the existing `transporterProgress` state from the store.

**Files to modify:** `ui/src/components/IntentSurface.tsx` (add rendering block for `transporterProgress`)

### BF-007: Verification False Positive on Per-Pool Agent Counts

**Severity:** Medium — unnecessary correction footnotes on valid responses
**Found:** 2026-03-21 (Captain log review)
**Component:** `runtime.py` → `_verify_response()` → Check 1 & 2

**Symptom:** When the LLM describes per-pool or per-department agent counts (e.g. "Engineering has 18 agents, Medical has 3 agents"), each number is flagged as a violation because the regex `(\d+)\s+agents?\b` compares every match against the system-wide total (53). Five false positives in a single response: `agents: claimed 18, actual 53; claimed 20, actual 53; claimed 5, actual 53; claimed 2, actual 53; claimed 3, actual 53`. Same issue affects pool count check.

**Root Cause:** Checks 1 and 2 treat all numeric agent/pool references as system-wide total claims. No contextual awareness — "3 agents in the medical pool" is treated the same as "the system has 3 agents."

**Fix:** Add context-window analysis around each regex match. Examine 80 chars before the match for pool/department names or subset-indicating words ("pool", "department", "team", "each", "per"). Skip matches that reference a specific pool or department. Also whitelist numbers matching any individual `pool.agent_count` from the self-model. Only flag matches claiming system-wide totals. See `prompts/bf-004-verification-false-positive.md`.

**Files to modify:** `src/probos/runtime.py` (`_verify_response()`)

### BF-008: Dream Cycle Double-Replay After Dolphin Dreaming

**Severity:** Low — wasted computation, no data loss or incorrect behavior
**Found:** 2026-03-21 (Captain log review)
**Component:** `dreaming.py` → `DreamingEngine` → `dream_cycle()` + `micro_dream()`

**Symptom:** Log shows static `replayed=50 strengthened=80` every 10 minutes even with no new user activity. The same 50 episodes are re-replayed every full dream cycle, double-strengthening Hebbian weights that micro-dream already consolidated.

**Root Cause:** Micro-dream (Tier 1, every 10s) incrementally replays new episodes and advances `_last_consolidated_count`. Full dream (Tier 2, every 10min) then replays the last 50 episodes regardless, re-strengthening already-consolidated pathways. No coordination between tiers.

**Fix:** Remove replay (`_replay_episodes()`) from `dream_cycle()` — micro-dream owns incremental Hebbian consolidation, full dream owns maintenance (pruning, trust consolidation, pre-warming, strategy extraction, gap prediction). Add `micro_dream()` flush before direct `dream_cycle()` callers (shutdown, Surgeon force_dream) to catch stragglers. See `prompts/bf-008-dream-double-replay.md`.

**Files to modify:** `src/probos/cognitive/dreaming.py`, `src/probos/runtime.py`, `src/probos/agents/medical/surgeon.py`

---

