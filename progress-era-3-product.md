# Era III: Product — The Ship Sets Sail

*Phases 22-29: Bundled Agents, Distribution, HXI, Channels, Self-Mod Hardening, Medical Team, Codebase Knowledge*

This era transformed ProbOS from a research prototype into a usable product. Bundled agents made it useful on day one, the HXI canvas let users watch cognition in real-time, channel adapters connected ProbOS to Discord, the medical team added self-healing, and the codebase knowledge service gave agents structural self-awareness. By the end of Product, ProbOS was installable, visual, connectable, and self-maintaining.

---

## What's Been Built

### Bundled Agents (new in Phase 22)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/agents/bundled/__init__.py` | done | Package root, re-exports all 10 bundled agent classes |
| `src/probos/agents/bundled/web_agents.py` | done | `WebSearchAgent` (DuckDuckGo via mesh `http_fetch`), `PageReaderAgent` (URL → summarize, HTML tag stripping), `WeatherAgent` (wttr.in JSON via mesh), `NewsAgent` (RSS XML parsing with `xml.etree.ElementTree`, `_parse_rss()` static method, default RSS feeds dict). `_BundledMixin` self-deselect guard for unrecognized intents. `_mesh_fetch()` helper dispatches `http_fetch` through intent bus (AD-248) |
| `src/probos/agents/bundled/language_agents.py` | done | `TranslateAgent` (pure LLM translation), `SummarizerAgent` (pure LLM summarization). No `perceive()` override — entirely LLM-driven via `instructions`. `_BundledMixin` self-deselect guard (AD-249) |
| `src/probos/agents/bundled/productivity_agents.py` | done | `CalculatorAgent` (safe eval for simple arithmetic via `_SAFE_EXPR_RE`, LLM fallback for complex expressions), `TodoAgent` (file-backed via mesh `read_file`/`write_file`, `~/.probos/todos.json`). `_BundledMixin` self-deselect guard. Mesh I/O helpers: `_mesh_read_file()`, `_mesh_write_file()` (AD-250) |
| `src/probos/agents/bundled/organizer_agents.py` | done | `NoteTakerAgent` (file-backed notes in `~/.probos/notes/`, semantic search via `_semantic_layer`), `SchedulerAgent` (file-backed reminders in `~/.probos/reminders.json`, no background timer). `_BundledMixin` self-deselect guard. Mesh I/O helpers: `_mesh_read_file()`, `_mesh_write_file()`, `_mesh_list_dir()` (AD-251) |

### Distribution (new in Phase 22)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/api.py` | done | FastAPI app with REST + WebSocket endpoints. `create_app(runtime)` returns wired FastAPI instance. `GET /api/health` (status, agent count, avg health), `GET /api/status` (full runtime status), `POST /api/chat` (NL message → DAG execution → response), `WebSocket /ws/events` (event stream with 30s keepalive ping). `_broadcast_event()` fire-and-forget to connected WebSocket clients (AD-247) |

## What's Working

### Bundled agent tests (50 tests — new in Phase 22)

Per-agent tests for all 10 bundled agents (4-7 tests each):
- Class attributes: `agent_type`, `_handled_intents`, `intent_descriptors`, `default_capabilities`
- `handle_intent()` with recognized intent returns `IntentResult(success=True)` via MockLLMClient
- Self-deselect: unrecognized intent returns `None` via `_BundledMixin`
- Agent-specific: WebSearchAgent DuckDuckGo URL construction, PageReaderAgent HTML stripping, WeatherAgent wttr.in URL, NewsAgent `_parse_rss()` XML parsing (valid/malformed/empty/limit-10), CalculatorAgent safe eval (arithmetic, parentheses, rejects `__import__`, rejects alphabetic), TodoAgent/NoteTakerAgent/SchedulerAgent perceive without runtime
- Cross-cutting: `__init__.py` exports all 10, CognitiveAgent subclass check, attribute completeness

### Distribution tests (16 tests — new in Phase 22)

#### Runtime integration (8 tests)
- All 10 bundled pool types created at boot when enabled, bundled agents have `llm_client` set, bundled agents have `runtime` set, `_collect_intent_descriptors()` includes bundled intents, `bundled_agents.enabled: false` skips pools, status includes bundled pools, total agent count ≥ 40, bundled NL query via MockLLMClient

#### probos init (4 tests)
- Creates directory structure (`~/.probos/`, `data/`, `notes/`), creates valid YAML config with system/cognitive/bundled_agents sections, `--force` overwrites existing config, skips without `--force` when config exists

#### FastAPI endpoints (4 tests)
- `GET /api/health` returns `{status, agents, health}`, `GET /api/status` returns runtime status with pools, `POST /api/chat` processes message and returns `{response, dag, results}`, `create_app()` returns FastAPI instance

The interactive terminal interface works end-to-end:

1. `uv run python -m probos` boots the system with a Rich banner and boot sequence display.
2. Shows pool creation (2 heartbeats, 3 file readers, 2 red team) with green checkmarks.
3. Drops into an interactive shell with ambient health prompt: `[7 agents | health: 0.80] probos>`
4. Slash commands render system state as Rich tables and panels:
   - `/status` — full system overview (pools, mesh, consensus, cognitive config)
   - `/agents` — colour-coded agent table with ID, type, pool, state, confidence, trust
   - `/weights` — Hebbian weight table sorted by weight descending
   - `/gossip` — gossip view with agent states and capabilities
   - `/log [category]` — recent event log entries with timestamp, category, event, detail
   - `/memory` — working memory snapshot (active intents, recent results)
5. Natural language input routes through the full cognitive pipeline:
   - Shows spinner during "Decomposing intent..."
   - Displays the TaskDAG plan (number of tasks, intents, parameters)
   - Live-updates a progress table during execution (pending → running → done/FAILED)
   - Shows final results panel with checkmarks and optional result excerpts
6. `/debug on` enables verbose output: raw TaskDAG JSON, individual agent responses with confidence scores, consensus outcomes, verification results.
7. Error handling is graceful — malformed input, failed intents, empty DAGs produce user-friendly messages, never stack traces.
8. `/quit` triggers clean shutdown with spinner.

---

The following interactive session demonstrates the system:

```
$ uv run python -m probos

╭─ ProbOS v0.1.0 — Probabilistic Agent-Native OS ─╮
╰──────────────────────────────────────────────────╯

Starting ProbOS...
  ✓ Pool system: 2 system_heartbeat agents
  ✓ Pool filesystem: 3 file_reader agents
  ✓ Red team: 2 verification agents
  ✓ Total: 7 agents across 2 pools

ProbOS ready.
Type /help for commands, or enter a natural language request.

[7 agents | health: 0.80] probos> read the file at /tmp/test.txt

> read the file at /tmp/test.txt
  Plan: 1 task(s)
    t1: read_file (path=/tmp/test.txt)
╭─ Results ─╮
│ 1/1 tasks completed │
│   ✓ t1: read_file   │
╰──────────────────────╯

[7 agents | health: 0.80] probos> /agents
                    Agents
┌──────────┬─────────────────┬────────────┬────────┬────────────┬───────┐
│ ID       │ Type            │ Pool       │ State  │ Confidence │ Trust │
├──────────┼─────────────────┼────────────┼────────┼────────────┼───────┤
│ a1b2c3d4 │ file_reader     │ filesystem │ active │       0.80 │  0.50 │
│ ...      │ ...             │ ...        │ ...    │        ... │   ... │
└──────────┴─────────────────┴────────────┴────────┴────────────┴───────┘

[7 agents | health: 0.80] probos> /quit
Shutting down...
ProbOS stopped.
```

---

## Milestones

### Phase 22: Bundled Agent Suite + Distribution — "Useful on Day 1" ✅ COMPLETE
**Goal:** Make ProbOS installable and immediately useful without waiting for self-mod to generate agents.
- ✅ `pip install probos` PyPI packaging, `probos init` config wizard, `probos serve` daemon mode
- ✅ Tier 1 bundled CognitiveAgent suite (10 agents): WebSearchAgent, PageReaderAgent, SchedulerAgent, NoteTakerAgent, WeatherAgent, NewsAgent, TranslateAgent, SummarizerAgent, CalculatorAgent, TodoAgent
- ✅ All bundled agents are pre-built CognitiveAgent subclasses in `src/probos/agents/bundled/`, registered at boot
- ✅ Self-mod continues to handle the long tail beyond bundled agents
- **Demo moment:** `pip install probos && probos init && probos serve` — ask it anything, it works
- **Result:** 1520/1520 tests passing (+ 11 skipped). 66 new tests (50 bundled agent + 16 distribution)

### Phase 23: HXI MVP — "See Your AI Thinking" ✅ COMPLETE
**Goal:** Browser-based visualization of the cognitive mesh — the product differentiator. The GIF that gets shared.
- ✅ Track A (Python): Enriched WebSocket event stream — typed events for all system dynamics (agent lifecycle, trust, Hebbian, consensus, dream cycles, self-mod). State snapshot on connect
- ✅ Track B (TypeScript/React/Three.js): Cognitive Canvas — dark-field WebGL, luminous agent nodes (trust-spectrum colors, confidence glow), Hebbian connection curves, bloom post-processing. React overlays: Intent Surface (chat + DAG display), Decision Surface (results + feedback)
- ✅ Animations: heartbeat pulse, consensus golden flash, self-mod bloom, dream mode color shift, intent routing traces, agent breathing
- ✅ `probos serve` serves HXI as static files, auto-opens browser
- **Demo moment:** Open browser, watch agents coordinate on your request in real time. The animated GIF that makes people install ProbOS.
- **Result:** 1532/1532 tests passing (+ 11 skipped). 12 new tests. 14 new TypeScript source files.

### Self-Mod Pipeline Hardening (future — pre-Phase 24)
**Goal:** Fix real issues discovered during self-mod demo testing. These are reliability improvements to the existing pipeline, not new features.
- ✅ **Designed agent pool size = 1** (AD-265)
- ✅ **AgentDesigner `_mesh_fetch()` template** (AD-268)
- ✅ **Per-domain rate limiter** (AD-270)
- **Agent-generated SVG icons** — when the AgentDesigner creates a new agent, also generate a simple 16x16 SVG icon (stroke-based, single path) that visually represents the agent's function. Store alongside agent source in KnowledgeStore. Render on the canvas as the agent's unique glyph instead of a generic sphere. Each designed agent gets its own visual identity — a crypto agent gets a diamond, a weather agent gets a cloud arc, a translation agent gets overlapping speech bubbles. The self-mod pipeline already generates code — generating an icon is a natural extension

### Phase 24a: Discord Bot Adapter (AD-274 through AD-278)

**Problem:** ProbOS had no external channel integrations — users could only interact via CLI shell or HXI web UI. Phase 24 calls for channel adapters to bridge external messaging platforms.

| AD | Decision |
|----|----------|
| AD-274 | `ChannelAdapter` ABC + `ChannelMessage` dataclass + shared `extract_response_text()` in `src/probos/channels/`. Reusable base for Discord, Slack, email, Teams |
| AD-276 | `discord.py>=2.0` added as optional dependency in pyproject.toml. Commented channel config section added to system.yaml |
| AD-277 | 14 tests in `test_channel_base.py`: response formatter (8), ChannelMessage (2), handle_message routing + history (4) |

| File | Description |
|------|-------------|
| `src/probos/channels/__init__.py` | Package init, re-exports |
| `src/probos/channels/base.py` | ChannelAdapter ABC, ChannelMessage, per-channel conversation history |
| `src/probos/channels/response_formatter.py` | Shared `extract_response_text()` extracted from api.py |
| `src/probos/channels/discord_adapter.py` | Full Discord bot: message routing, mention filtering, channel filtering, chunked replies |
| `src/probos/config.py` | DiscordConfig + ChannelsConfig models |
| `config/system.yaml` | Commented channels config section |

### Phase 24b: Self-Assessment Bug Fixes (AD-279, AD-280)

### Phase 24c: Lightweight Task Scheduler (AD-281 through AD-284)

**Problem:** ProbOS identified its own inability to deliver timed messages during a Discord self-assessment conversation. The SchedulerAgent stored reminders to file but had no background timer to execute them.

| AD | Decision |
|----|----------|
| AD-281 | `TaskScheduler` engine: `ScheduledTask` dataclass, background 1-second tick loop (follows `DreamScheduler` pattern), `schedule()`/`cancel()`/`list_tasks()`/`get_stats()`. One-shot and recurring tasks. Per-task error isolation |
| AD-282 | Wire `TaskScheduler` into `ProbOSRuntime` lifecycle (start/stop), expose as property, add to `status()` output |
| AD-283 | Upgrade `SchedulerAgent`: removed "no background timer" disclaimer, `act()` calls `task_scheduler.schedule/cancel/list`, `perceive()` includes live scheduled tasks alongside saved reminders |
| AD-284 | Channel delivery for scheduled tasks: results sent to Discord/Slack channel when `channel_id` is set on the task. `__main__.py` passes channel adapters to TaskScheduler after adapter creation |

| File | Change |
|------|--------|
| `src/probos/cognitive/task_scheduler.py` | New — `ScheduledTask` dataclass, `TaskScheduler` engine with background loop, channel delivery |
| `src/probos/runtime.py` | Import TaskScheduler, create in `start()`, stop in `stop()`, add to `status()` |
| `src/probos/agents/bundled/organizer_agents.py` | SchedulerAgent upgraded: new instructions, `act()` interacts with TaskScheduler, `perceive()` includes live tasks |
| `src/probos/__main__.py` | Wire channel adapters into task scheduler for delivery |
| `tests/test_task_scheduler.py` | 17 tests (7 core scheduler + 2 runtime integration + 4 SchedulerAgent + 1 persistence + 3 channel delivery) |

**Scope boundary:** In-session scheduling only. Persistent tasks with checkpointing and resume-after-restart remain in Phase 25.

1705/1705 tests passing (+ 11 skipped).

### AD-293: Crew Team Introspection

**Problem:** Pool groups (AD-291) were invisible to the intent system — asking about a crew team returned no results.

| AD | Decision |
|----|----------|
| AD-293 | `team_info` intent on IntrospectionAgent — list all teams or get detailed health/roster/pools for a specific team. Fuzzy substring matching. `agent_info` pool name fallback for defense-in-depth |

| File | Change |
|------|--------|
| `src/probos/agents/introspect.py` | `team_info` IntentDescriptor + `_team_info()` method, pool name fallback in `_agent_info()` |
| `tests/test_team_introspection.py` | 6 tests |

1711/1711 tests passing (+ 11 skipped).

### Pre-Launch: Personalization + Security + Documentation (completed items)
- ✅ **SSRF protection** (AD-285) — `_validate_url()` in HttpFetchAgent blocks private IPs (10/172.16/192.168/127), cloud metadata (169.254.169.254), link-local, file:// scheme, and DNS rebinding attacks. 8 tests
- ✅ **.env file support** (AD-286) — `python-dotenv` loads `.env` from cwd at startup. `.env.example` documents available vars (`PROBOS_DISCORD_TOKEN`, `PROBOS_LLM_API_KEY`). Import-guarded so it degrades gracefully. 3 tests
- ✅ **HXI agent activity visualization** (AD-287) — Fixed 3 bugs preventing agent node flashes: (1) `node_start` event now includes `agent_id` + `intent` at top level, (2) `RoutingPulse` positions at target agent instead of `[0,0,0]`, (3) `activatedAt` timestamp on Agent type triggers 500ms brightness flash in `AgentNodes` useFrame loop
- ✅ **Dream consolidation — dolphin sleep model** (AD-288) — Three-tier dreaming: Tier 1 micro-dream (every 10s, replays new episodes only), Tier 2 idle dream (after 120s idle, full cycle with pruning/trust), Tier 3 shutdown flush (final `dream_cycle()` on stop). Fixed `_build_episode()` agent_id extraction for dicts. Added early-session guard to cooperation detector (requires 10+ episodes). `dream_consolidation_rate` now reflects micro-dream activity
- ✅ **Performance bottleneck optimization — P0 fixes** (AD-289) — Three critical-at-scale fixes: (1) Intent bus pre-filtering via reverse index (`_intent_index: dict[str, set[str]]`) — only agents registered for a specific intent receive broadcasts instead of fan-out to all 43+ agents, (2) Shapley value factorial explosion guard — coalitions >10 agents switch to Monte Carlo approximation (1000 random permutation samples) instead of exact enumeration (12 agents = 479M iterations), (3) `Registry.all()` caching — cached list invalidated only on register/unregister, avoiding list creation on every call from 11+ call sites
- ✅ **Medical team pool + Codebase Knowledge Service** (AD-290) — Created `medical` pool with 5 specialized agents: VitalsMonitorAgent (HeartbeatAgent subclass, continuous metric collection with sliding window + threshold alerting), DiagnosticianAgent (LLM-guided root-cause analysis), SurgeonAgent (acute remediation: force_dream, surge_pool, recycle_agent), PharmacistAgent (config tuning recommendations without mutation), PathologistAgent (post-mortem failure analysis with codebase_knowledge skill). Built CodebaseIndex runtime service — pure AST-based source tree analysis (<1s build, read-only, no LLM calls) with query(), read_source(), get_agent_map(), get_api_surface() methods. Created codebase_knowledge skill wrapping CodebaseIndex for CognitiveAgent use. Added MedicalConfig to SystemConfig. Medical pools excluded from PoolScaler. 31 tests (9 CodebaseIndex + 22 medical team)
- ✅ **Pool groups — crew team abstraction** (AD-291) — Added `PoolGroup` dataclass + `PoolGroupRegistry` to organize pools into named teams (core, bundled, medical, self_mod). Groups are first-class in runtime: `pool_groups.excluded_pools()` replaces hardcoded scaler exclusions, `status()` and `build_state_snapshot()` include group health aggregation. Status panel now displays "Crew Teams" headings with per-group agent counts. HXI layout sorts by group then pool for cluster adjacency on Fibonacci spheres. Added `PoolGroupInfo` to TypeScript types. Medical pool tints added to scene.ts (warm red/pink family). Adding future crew teams requires only pool creation + one `PoolGroup` registration. 13 tests (9 unit + 4 integration)

### Crew Team Introspection (AD-293) — ✅ COMPLETE

See detailed AD-293 section above. 6 tests. 1711/1711 tests passing (+ 11 skipped).

### HXI Crew Team Sub-Clusters (AD-294) — ✅ COMPLETE

Built gravitational sub-clusters with translucent boundary shells. Each pool group gets its own spatial cluster center, agents orbit within it on a mini Fibonacci sphere, and a faint wireframe shell + team name label marks the boundary.

### HXI Cluster Fixes + Security Pool Group (AD-296) — ✅ COMPLETE

**Problem:** Team name labels rotated with the scene and became unreadable. Red team agents were ungrouped (no pool group), floating in an orphaned "_ungrouped" cluster.

**Solution:** Billboard text labels (always face camera) via `@react-three/drei` `Billboard` component. New `security` PoolGroup for the `red_team` pool. Crew teams now 5: Core, Bundled, Medical, Self-Mod, Security.

| File | Change |
|------|--------|
| `ui/src/canvas/clusters.tsx` | Wrapped `<Text>` in `<Billboard follow>` for camera-facing labels |
| `src/probos/runtime.py` | Added `security` PoolGroup with `red_team` pool |
| `ui/src/store/useStore.ts` | Added `security: '#c85068'` to `GROUP_TINT_HEXES` |
| `ui/src/__tests__/useStore.test.ts` | 1 test: red_team agents in security group |

### CodebaseIndex as Ship's Library (AD-297) — ✅ COMPLETE

**Problem:** CodebaseIndex was gated behind `config.medical.enabled` — if medical team disabled, the introspect agent couldn't examine source code. Additionally, `_introspect_design()` only returned metadata (file paths, class names), never actual source code.

**Solution:** Decoupled CodebaseIndex from medical config — builds unconditionally at startup. Enhanced `_introspect_design()` to call `read_source()` on the top 3 matching files (first 80 lines each), returning actual source code snippets alongside architecture metadata.

| File | Change |
|------|--------|
| `src/probos/runtime.py` | Moved CodebaseIndex build out of `if config.medical.enabled:` block |
| `src/probos/agents/introspect.py` | `_introspect_design()` reads source snippets via `read_source()` (top 3 files, 80 lines) |
| `tests/test_introspect_design.py` | Updated mock + 4 new tests (source snippets, 3-file limit, skip empty, always available) |

**Status:** Complete — 4 new tests (1731 Python total)

### Word-Level Query Matching in CodebaseIndex (AD-298) — ✅ COMPLETE

**Problem:** `CodebaseIndex.query()` used exact substring matching against the full concept string. Multi-word queries like "trust network scoring" matched nothing because no file path or docstring contains that exact phrase.

**Solution:** Split query concepts into individual keywords, filter stop words, and score each keyword independently. Files matching more keywords rank higher. Additive scoring means "trust consensus" finds `consensus/trust.py` at the top.

| File | Change |
|------|--------|
| `src/probos/cognitive/codebase_index.py` | Added `_STOP_WORDS` frozenset, replaced substring matching in `query()` with per-keyword scoring |
| `tests/test_codebase_index.py` | 4 new tests (word-level matching, stop words filtered, multi-keyword scoring, all-stop-words fallback) |

**Status:** Complete — 4 new tests (1735 Python total)

### Project Docs in CodebaseIndex (AD-299) — ✅ COMPLETE

**Problem:** CodebaseIndex only indexed Python source files under `src/probos/`. Project documents (roadmap, decisions, progress) were invisible to the introspection agent, so questions like "what's on the roadmap?" returned nothing.

**Solution:** Added `_PROJECT_DOCS` whitelist and `_project_root` to CodebaseIndex. `build()` now scans whitelisted Markdown docs with lightweight parsing (title from `# heading`, sections from `## headings`). Files stored with `docs:` prefix in `_file_tree`. `read_source()` resolves `docs:` paths against project root with path traversal protection.

| File | Change |
|------|--------|
| `src/probos/cognitive/codebase_index.py` | `_PROJECT_DOCS` whitelist, `_project_root`, `_analyze_doc()`, `build()` scans docs, `read_source()` handles `docs:` prefix |
| `tests/test_codebase_index.py` | 5 new tests (doc indexing, section query matching, doc reading, path traversal, missing docs) |

**Status:** Complete — 5 new tests (1740 Python total)

### Section-Targeted Doc Reading (AD-300) — ✅ COMPLETE

**Problem:** `_introspect_design()` read the first 80 lines of every matched file, including Markdown docs. The roadmap is 530+ lines — 80 lines captures only the table of contents, not the content. ProbOS couldn't read relevant doc sections.

**Solution:** `_analyze_doc()` now stores section line numbers alongside names. New `read_doc_sections()` method scores sections by keyword overlap and reads only the matching sections (up to `max_lines=200`). `_introspect_design()` detects `docs:` prefixed files and uses section-targeted reading instead of the fixed 80-line source read.

| File | Change |
|------|--------|
| `src/probos/cognitive/codebase_index.py` | `_analyze_doc()` stores `sections` with `name` + `line`. New `read_doc_sections()` method |
| `src/probos/agents/introspect.py` | `_introspect_design()` uses `read_doc_sections()` for `docs:` files, imports `_STOP_WORDS` for keyword extraction |
| `tests/test_codebase_index.py` | 5 new tests (section line storage, keyword matching, multi-keyword scoring, fallback, max_lines) |
| `tests/test_introspect_design.py` | 1 new test (doc files use `read_doc_sections` instead of `read_source`) |

**Status:** Complete — 6 new tests (1746 Python total)

### BuilderAgent — Code Generation via LLM (AD-302/303) — ✅ COMPLETE

**Problem:** ProbOS had no way to generate code changes programmatically. The path from "architect designs a spec" to "code gets written" required a human. This is the first step toward the automated federation northstar.

**Solution:** `BuilderAgent` — a CognitiveAgent in the Engineering team that accepts `BuildSpec` dataclasses, generates code via the deep LLM tier, parses file changes from `===FILE:===` / `===MODIFY:===` markers, and returns them for Captain approval. After approval, `execute_approved_build()` orchestrates: git branch → write files → pytest → commit → return to main. All git operations are async (`asyncio.create_subprocess_exec`). MODIFY mode is parsed but not yet applied (logged and skipped).

| File | Change |
|------|--------|
| `src/probos/cognitive/builder.py` | **NEW** — `BuildSpec`, `BuildResult` dataclasses, `BuilderAgent` (CognitiveAgent, domain tier), `_parse_file_blocks()`, git helpers (`_git_create_branch`, `_git_add_and_commit`, `_git_checkout_main`), `execute_approved_build()` pipeline |
| `src/probos/runtime.py` | Import `BuilderAgent`, register template, create `builder` pool (gated on `bundled_agents.enabled`), register `engineering` PoolGroup |
| `ui/src/store/useStore.ts` | Added `engineering: '#b0a050'` to `GROUP_TINT_HEXES` |
| `tests/test_builder_agent.py` | **NEW** — 29 tests across 10 test classes |

**Status:** Complete — 29 new tests (1775 Python total)

### Builder API + HXI Approval Surface (AD-304/305) — ✅ COMPLETE

**Problem:** BuilderAgent existed but had no way to trigger it from the UI or API. No endpoint to submit build requests, no approval surface for the Captain to review generated code, and no WebSocket events for real-time progress tracking.

**Solution:** API endpoints + HXI frontend wired end-to-end:
- **AD-304** Builder API — `POST /api/build/submit` triggers BuilderAgent via intent bus (fire-and-forget async). `POST /api/build/approve` calls `execute_approved_build()` to write files, test, and commit. `/build <title>: <description>` chat command handled inside `create_app()` closure. WebSocket events: `build_started`, `build_progress`, `build_generated`, `build_success`, `build_failure`
- **AD-305** Builder HXI — `BuildProposal` TypeScript interface with file changes, LLM output, and review status. Zustand store handles all `build_*` events with `buildProgress` state. IntentSurface renders inline approval UI: file change summary, collapsible code view, Approve/Reject buttons. `buildProposal` on ChatMessage is transient (not serialized to localStorage)

| File | Change |
|------|--------|
| `src/probos/api.py` | `BuildRequest`, `BuildApproveRequest` models. `POST /api/build/submit`, `POST /api/build/approve` endpoints. `_run_build()`, `_execute_build()` async background functions. `/build` slash command in chat endpoint |
| `ui/src/store/types.ts` | `BuildProposal` interface, `buildProposal` field on `ChatMessage` |
| `ui/src/store/useStore.ts` | `buildProgress` state, `build_started/progress/generated/success/failure` event handlers, `addChatMessage` updated for `buildProposal` meta |
| `ui/src/components/IntentSurface.tsx` | `approveBuild`/`rejectBuild` callbacks, inline approval UI with file summary, collapsible code view, Approve/Reject buttons |
| `tests/test_builder_api.py` | **NEW** — 15 tests across 7 test classes |

**Status:** Complete — 15 new tests (1790 Python + 21 Vitest total)

### Architect Agent — Roadmap-Driven BuildSpec Generation (AD-306/307) — ✅ COMPLETE

**Problem:** ProbOS had a Builder Agent that could generate code from specs, but no automated way to *produce* those specs. The Captain still hand-wrote build prompts. The Architect Agent is the "First Officer" that surveys the codebase and roadmap to draft structured BuildSpec proposals.

**Solution:** `ArchitectAgent` — a CognitiveAgent in the Science team (deep LLM tier) that:
- Reads codebase context via `CodebaseIndex` (files, agents, layers, roadmap sections, DECISIONS tail)
- Produces structured `ArchitectProposal` containing an embedded `BuildSpec` for the Builder Agent
- Parses `===PROPOSAL===...===END PROPOSAL===` blocks from LLM output with field extraction (TITLE, SUMMARY, RATIONALE, TARGET_FILES, REFERENCE_FILES, TEST_FILES, CONSTRAINTS, DEPENDENCIES, RISKS, DESCRIPTION)
- `requires_consensus=False` (proposals go to Captain, not agent consensus), `requires_reflect=True`

| File | Change |
|------|--------|
| `src/probos/cognitive/architect.py` | **NEW** — `ArchitectProposal` dataclass, `ArchitectAgent` (CognitiveAgent, Science team), `_parse_proposal()`, `perceive()` gathers codebase context, `_build_user_message()` formats design request |
| `src/probos/runtime.py` | Import `ArchitectAgent`, register template, create `architect` pool, register `science` PoolGroup, attach `codebase_skill` independently of medical config |
| `ui/src/store/useStore.ts` | Added `science: '#50a0b0'` to `GROUP_TINT_HEXES` |
| `tests/test_architect_agent.py` | **NEW** — 25 tests across 15 test classes |

**Status:** Complete — 25 new tests (1815 Python + 21 Vitest total)

### Architect API + HXI — Design Proposals from the Bridge (AD-308/309) — ✅ COMPLETE

**Problem:** The ArchitectAgent existed but had no API surface or HXI approval flow. No way to trigger it from the chat, no visual representation of proposals, and no approval path to forward specs to the Builder Agent.

**Solution:** API endpoints + HXI frontend mirroring the Builder API pattern:
- **AD-308** Architect API — `POST /api/design/submit` triggers ArchitectAgent via intent bus, `POST /api/design/approve` pops from `_pending_designs` and forwards the embedded BuildSpec to `_run_build()`. `/design` slash command supports `/design <feature>` and `/design phase N: <feature>`. WebSocket events: `design_started`, `design_progress`, `design_generated`, `design_failure`
- **AD-309** Architect HXI — `ArchitectProposalView` TypeScript interface. Zustand handles `design_*` events with `designProgress` state. IntentSurface renders teal-themed proposal review card showing summary, rationale, roadmap ref, priority, target files, risks, and dependencies. Collapsible full spec view. "Approve & Build" forwards to builder, "Reject" discards

| File | Change |
|------|--------|
| `src/probos/api.py` | `DesignRequest`, `DesignApproveRequest` models. `POST /api/design/submit`, `POST /api/design/approve` endpoints. `_run_design()` async pipeline. `_pending_designs` dict. `/design` slash command in chat endpoint |
| `ui/src/store/types.ts` | `ArchitectProposalView` interface, `architectProposal` field on `ChatMessage` |
| `ui/src/store/useStore.ts` | `designProgress` state, `design_started/progress/generated/success/failure` event handlers, `addChatMessage` updated for `architectProposal` meta |
| `ui/src/components/IntentSurface.tsx` | `approveDesign`/`rejectDesign` callbacks, teal proposal review card with summary/rationale/risks/dependencies, collapsible full spec, Approve & Build / Reject buttons |
| `tests/test_architect_api.py` | **NEW** — 14 tests across 8 test classes |

**Status:** Complete — 14 new tests (1826 Python + 21 Vitest total)

### Causal Attribution for Emergent Behavior + Self-Introspection (AD-295) — ✅ COMPLETE

**Problem:** ProbOS detects emergent patterns (trust anomalies, routing shifts, cooperation clusters) but cannot explain *why* they're happening. No causal trail linking trust changes to intents and Shapley scores. IntrospectionAgent cannot examine ProbOS's own source code for architecture questions.

**Solution:** Four-part fix:
- **AD-295a** Trust Event Log — `TrustEvent` dataclass + ring buffer (deque maxlen=500) in `TrustNetwork`. Records intent_type, Shapley weight, verifier_id, episode_id, old/new scores for every `record_outcome()` call. Query methods: `get_recent_events()`, `get_events_for_agent()`, `get_events_since()`
- **AD-295b** Episode Enrichment — `Episode` dataclass gains `shapley_values: dict[str, float]` and `trust_deltas: list[dict]`. `_build_episode()` captures both from last consensus + trust event log. ChromaDB serialization updated for roundtrip
- **AD-295c** Causal Back-References — `detect_trust_anomalies()` adds `causal_events` list to `EmergentPattern.evidence` (last 5 trust events per anomalous agent). `detect_routing_shifts()` adds `agent_trust` and `hebbian_weight` to routing shift evidence
- **AD-295d** Self-Introspection — `introspect_design` intent on IntrospectionAgent. Uses `rt.codebase_index.query()` + `get_agent_map()` + `get_layer_map()` to answer architecture questions. Graceful fallback when CodebaseIndex unavailable

| File | Change |
|------|--------|
| `src/probos/consensus/trust.py` | `TrustEvent` dataclass, `_event_log` deque, enriched `record_outcome()`, 3 query methods |
| `src/probos/types.py` | `Episode.shapley_values`, `Episode.trust_deltas` fields |
| `src/probos/runtime.py` | Causal kwargs in verification `record_outcome()`, `_build_episode()` captures Shapley + trust deltas |
| `src/probos/cognitive/episodic.py` | Serialize/deserialize `shapley_values_json`, `trust_deltas_json` |
| `src/probos/cognitive/emergent_detector.py` | `causal_events` in trust anomaly evidence, trust/Hebbian context in routing shifts |
| `src/probos/agents/introspect.py` | `introspect_design` intent + `_introspect_design()` method |
| `tests/test_trust_events.py` | 6 tests: event recording, scores, cap, agent filter, time filter, backward compat |
| `tests/test_episode_attribution.py` | 4 tests: Shapley storage, trust deltas, serialization roundtrip, backward compat |
| `tests/test_causal_attribution.py` | 3 tests: causal events in anomalies, routing shift context, introspection surfacing |
| `tests/test_introspect_design.py` | 3 tests: architecture query, no-codebase fallback, intent registration |
