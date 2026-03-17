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

### Pre-Launch: Personalization + Security + Documentation (completed items)
- ✅ **SSRF protection** (AD-285) — `_validate_url()` in HttpFetchAgent blocks private IPs (10/172.16/192.168/127), cloud metadata (169.254.169.254), link-local, file:// scheme, and DNS rebinding attacks. 8 tests
- ✅ **.env file support** (AD-286) — `python-dotenv` loads `.env` from cwd at startup. `.env.example` documents available vars (`PROBOS_DISCORD_TOKEN`, `PROBOS_LLM_API_KEY`). Import-guarded so it degrades gracefully. 3 tests
- ✅ **HXI agent activity visualization** (AD-287) — Fixed 3 bugs preventing agent node flashes: (1) `node_start` event now includes `agent_id` + `intent` at top level, (2) `RoutingPulse` positions at target agent instead of `[0,0,0]`, (3) `activatedAt` timestamp on Agent type triggers 500ms brightness flash in `AgentNodes` useFrame loop
- ✅ **Dream consolidation — dolphin sleep model** (AD-288) — Three-tier dreaming: Tier 1 micro-dream (every 10s, replays new episodes only), Tier 2 idle dream (after 120s idle, full cycle with pruning/trust), Tier 3 shutdown flush (final `dream_cycle()` on stop). Fixed `_build_episode()` agent_id extraction for dicts. Added early-session guard to cooperation detector (requires 10+ episodes). `dream_consolidation_rate` now reflects micro-dream activity
- ✅ **Performance bottleneck optimization — P0 fixes** (AD-289) — Three critical-at-scale fixes: (1) Intent bus pre-filtering via reverse index (`_intent_index: dict[str, set[str]]`) — only agents registered for a specific intent receive broadcasts instead of fan-out to all 43+ agents, (2) Shapley value factorial explosion guard — coalitions >10 agents switch to Monte Carlo approximation (1000 random permutation samples) instead of exact enumeration (12 agents = 479M iterations), (3) `Registry.all()` caching — cached list invalidated only on register/unregister, avoiding list creation on every call from 11+ call sites
- ✅ **Medical team pool + Codebase Knowledge Service** (AD-290) — Created `medical` pool with 5 specialized agents: VitalsMonitorAgent (HeartbeatAgent subclass, continuous metric collection with sliding window + threshold alerting), DiagnosticianAgent (LLM-guided root-cause analysis), SurgeonAgent (acute remediation: force_dream, surge_pool, recycle_agent), PharmacistAgent (config tuning recommendations without mutation), PathologistAgent (post-mortem failure analysis with codebase_knowledge skill). Built CodebaseIndex runtime service — pure AST-based source tree analysis (<1s build, read-only, no LLM calls) with query(), read_source(), get_agent_map(), get_api_surface() methods. Created codebase_knowledge skill wrapping CodebaseIndex for CognitiveAgent use. Added MedicalConfig to SystemConfig. Medical pools excluded from PoolScaler. 31 tests (9 CodebaseIndex + 22 medical team)
- ✅ **Pool groups — crew team abstraction** (AD-291) — Added `PoolGroup` dataclass + `PoolGroupRegistry` to organize pools into named teams (core, bundled, medical, self_mod). Groups are first-class in runtime: `pool_groups.excluded_pools()` replaces hardcoded scaler exclusions, `status()` and `build_state_snapshot()` include group health aggregation. Status panel now displays "Crew Teams" headings with per-group agent counts. HXI layout sorts by group then pool for cluster adjacency on Fibonacci spheres. Added `PoolGroupInfo` to TypeScript types. Medical pool tints added to scene.ts (warm red/pink family). Adding future crew teams requires only pool creation + one `PoolGroup` registration. 13 tests (9 unit + 4 integration)
