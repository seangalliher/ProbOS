# ProbOS — Architectural Decisions: Era III — Product (Phases 22–29)

Archived decisions from the Product era. AD-247 through AD-329.

For current decisions, see [DECISIONS.md](DECISIONS.md).

---

### Phase 22 — Bundled Agent Suite + Distribution (AD-247 through AD-253)

ProbOS becomes installable and immediately useful. 10 bundled CognitiveAgent subclasses cover common personal assistant tasks. Distribution infrastructure enables `pip install probos`, `probos init`, `probos serve`. Self-mod continues to handle the long tail beyond bundled agents.

**Bundled agents (10 agents in `src/probos/agents/bundled/`):**

All bundled agents subclass `CognitiveAgent` and use `_BundledMixin` for self-deselect (return `None` from `handle_intent()` for unrecognized intents, preventing cascading intent broadcasts). Web-facing agents dispatch `http_fetch` through the mesh via `intent_bus.broadcast()` — never httpx directly. File-persisting agents dispatch `read_file`/`write_file` through the mesh — never `Path.write_text()` directly. This preserves governance (consensus, trust) across the entire stack.

| AD | What |
|----|------|
| AD-247 | Distribution: `[project.scripts]` for `pip install`, `probos init` config wizard (creates `~/.probos/` with config.yaml, data/, notes/), `probos serve` with FastAPI/uvicorn HTTP + WebSocket server, `_boot_runtime()` shared boot logic, `_load_config_with_fallback()` config resolution chain. `src/probos/api.py`: `create_app(runtime)` returns FastAPI with `/api/health`, `/api/status`, `/api/chat`, `/ws/events` |
| AD-248 | Web + Content agents: `WebSearchAgent` (DuckDuckGo via mesh `http_fetch`), `PageReaderAgent` (URL → summarize, HTML tag stripping), `WeatherAgent` (wttr.in JSON), `NewsAgent` (RSS XML parsing via `xml.etree.ElementTree`, `_parse_rss()`, default feeds dict). All fetch via `_mesh_fetch()` helper. `_BundledMixin` self-deselect guard |
| AD-249 | Language agents: `TranslateAgent` (pure LLM translation), `SummarizerAgent` (pure LLM summarization). No `perceive()` override — entirely LLM-driven via `instructions` |
| AD-250 | Productivity agents: `CalculatorAgent` (safe eval for simple arithmetic via `_SAFE_EXPR_RE`, LLM fallback), `TodoAgent` (file-backed `~/.probos/todos.json` via mesh `read_file`/`write_file`). Mesh I/O helpers |
| AD-251 | Organizer agents: `NoteTakerAgent` (file-backed `~/.probos/notes/`, semantic search via `_semantic_layer`), `SchedulerAgent` (file-backed `~/.probos/reminders.json`, no background timer). Mesh I/O helpers |
| AD-252 | Runtime registration: 10 new pools (2 agents each), spawner templates, `BundledAgentsConfig(enabled=True)`, descriptor refresh, MockLLMClient patterns for all 10 bundled intents. MockLLMClient `match_text` extraction: pattern matching against "User request:" portion only (prevents false positives from pool names and capability listings in system state context) |
| AD-253 | 66 tests: `test_bundled_agents.py` (50 tests — per-agent attributes, handle_intent, self-deselect, agent-specific behavior), `test_distribution.py` (16 tests — runtime integration, probos init, FastAPI endpoints) |

#### Files changed

| File | Changes |
|------|---------|
| `pyproject.toml` | Added `[project.scripts]` entry `probos = "probos.__main__:main"`, added `fastapi>=0.115` and `uvicorn>=0.34` dependencies |
| `src/probos/__main__.py` | Rewritten: added `init` and `serve` subcommands via argparse, `_boot_runtime()` shared boot logic, `_load_config_with_fallback()`, `_cmd_init()`, `_serve()` |
| `src/probos/api.py` | **New.** FastAPI app: `/api/health`, `/api/status`, `/api/chat`, `/ws/events` |
| `src/probos/agents/bundled/__init__.py` | **New.** Re-exports all 10 bundled agent classes |
| `src/probos/agents/bundled/web_agents.py` | **New.** WebSearchAgent, PageReaderAgent, WeatherAgent, NewsAgent + `_BundledMixin` + `_mesh_fetch()` |
| `src/probos/agents/bundled/language_agents.py` | **New.** TranslateAgent, SummarizerAgent + `_BundledMixin` |
| `src/probos/agents/bundled/productivity_agents.py` | **New.** CalculatorAgent, TodoAgent + `_BundledMixin` + mesh I/O helpers |
| `src/probos/agents/bundled/organizer_agents.py` | **New.** NoteTakerAgent, SchedulerAgent + `_BundledMixin` + mesh I/O helpers |
| `src/probos/config.py` | Added `BundledAgentsConfig(enabled=True)` to `SystemConfig` |
| `config/system.yaml` | Added `bundled_agents: enabled: true` |
| `src/probos/runtime.py` | Added bundled agent imports, spawner template registrations, conditional pool creation gated by `bundled_agents.enabled` |
| `src/probos/cognitive/llm_client.py` | Added 10 MockLLMClient patterns + response handlers for bundled intents, `match_text` extraction from "User request:" portion to prevent false positives |
| `tests/test_bundled_agents.py` | **New.** 50 tests covering all 10 bundled agents |
| `tests/test_distribution.py` | **New.** 16 tests for runtime integration, probos init, FastAPI endpoints |
| `tests/test_decomposer.py` | Updated 2 tests: changed "translate hello to French" → "please convert this audio to text" (avoids matching new translate pattern) |
| `tests/test_experience.py` | Updated 3 tests: changed "translate hello into japanese" → "please transcribe this audio clip" (avoids matching new translate pattern) |

#### Phase 22 design notes

- **`_BundledMixin` self-deselect** — the IntentBus broadcasts every intent to ALL subscribers. Without the mixin, CognitiveAgent.handle_intent() runs full perceive→decide→act for ANY intent, causing cascading sub-intent broadcasts from perceive() overrides. The mixin returns `None` for unrecognized intents, preventing infinite loops
- **MockLLMClient `match_text` extraction** — the decomposer wraps user text in system state context (pool names, capability listings). Bare pattern matching against the full prompt caused false positives (e.g., "news" matching pool name "news: 2"). Now patterns only match against the "User request: ..." portion
- **Mesh dispatch for all I/O** — bundled agents never use httpx or Path directly. All web fetches go through `intent_bus.broadcast(IntentMessage(intent="http_fetch"))` and all file I/O goes through `read_file`/`write_file` intents. This preserves consensus, trust scoring, and event logging for every operation
- **No background timer** — SchedulerAgent stores reminders but has no cron-like timer. Reminders are checked at boot/interaction. Background scheduling comes in a future phase

1520/1520 tests passing (+ 11 skipped). 66 new tests.

---

### Phase 23 — HXI MVP: "See Your AI Thinking" (AD-254 through AD-261)

**Track A (Python — AD-254):** Enriched event stream
- `runtime.py`: `add_event_listener()` / `remove_event_listener()` / `_emit_event()` — fire-and-forget event dispatch to registered listeners
- `build_state_snapshot()` — full system state serialized on WebSocket connect (agents, connections, pools, system_mode, tc_n, routing_entropy)
- Instrumented events: `agent_state` (on wire), `trust_update` (after record_outcome), `hebbian_update` (after record_interaction), `consensus` (after quorum evaluate), `system_mode` (pre/post dream)
- `dreaming.py`: Added `_pre_dream_fn` callback to DreamScheduler, symmetric with existing `_post_dream_fn`

**Track A (Python — AD-260):** Serve integration
- `api.py`: CORS middleware for HXI dev server (`localhost:5173`), event listener bridge (runtime → WebSocket), state_snapshot on WS connect, static file serving from `ui/dist/`
- `__main__.py`: `probos serve` auto-opens browser via `webbrowser.open()`
- Fallback HTML when `ui/dist/` not built

**Track B (TypeScript/React/Three.js — AD-255 through AD-259):**
- `ui/package.json`: Vite + React 19 + Three.js + R3F + Zustand + postprocessing
- `ui/src/store/types.ts`: Full TypeScript type definitions matching Python event schema
- `ui/src/store/useStore.ts`: Zustand reactive state — handles all event types, computes spatial layout (pool-based radial arrangement)
- `ui/src/hooks/useWebSocket.ts`: Auto-reconnecting WebSocket with exponential backoff
- `ui/src/canvas/scene.ts`: HXI visual palette — trust spectrum (amber→blue→violet), pool tints, system mode color grading, confidence→intensity mapping
- `ui/src/canvas/agents.tsx`: Instanced mesh rendering — per-instance trust color, confidence glow, breathing animation
- `ui/src/canvas/connections.tsx`: Quadratic bezier Hebbian curves with weight-based opacity
- `ui/src/canvas/effects.tsx`: Bloom post-processing with mode-based grading
- `ui/src/canvas/animations.tsx`: Heartbeat pulse, consensus golden flash, self-mod bloom flare, intent routing trace
- `ui/src/components/CognitiveCanvas.tsx`: Three.js scene — ACES tone mapping, orbit controls, dark-field background
- `ui/src/components/IntentSurface.tsx`: Chat input + DAG node status visualization (top overlay)
- `ui/src/components/DecisionSurface.tsx`: Status bar (connection, agent count, health, mode, TC_N, H(r)), feedback strip (approve/correct/reject)

**Track D (Python tests — AD-261):**

| Test | What it validates |
|------|-------------------|
| `test_add_event_listener` | Listener registration |
| `test_remove_event_listener` | Listener removal |
| `test_remove_nonexistent_listener` | No-crash on removing unregistered listener |
| `test_emit_event_calls_listeners` | Event delivery to all listeners |
| `test_emit_no_listeners` | No-crash on emission with no listeners |
| `test_failing_listener_doesnt_crash_others` | Error isolation between listeners |
| `test_event_timestamps_increasing` | Monotonic timestamps |
| `test_state_snapshot_structure` | Snapshot has required keys |
| `test_state_snapshot_json_serializable` | JSON round-trip clean |
| `test_state_snapshot_has_agents` | Agent entries have all fields |
| `test_agent_state_emitted_on_wire` | agent_state fires during boot |
| `test_system_mode_event_on_dream` | dreaming → idle mode transition events |

**Files changed/created:**

| File | Change |
|------|--------|
| `src/probos/runtime.py` | `_event_listeners`, `add_event_listener()`, `remove_event_listener()`, `_emit_event()`, `build_state_snapshot()`, `_on_pre_dream()`. Instrumented `_wire_agent()`, `submit_intent()`, `submit_intent_with_consensus()`, `_run_qa_for_designed_agent()` |
| `src/probos/api.py` | CORS, event listener bridge, state_snapshot on WS connect, static file serving, fallback HTML |
| `src/probos/cognitive/dreaming.py` | `_pre_dream_fn` callback in DreamScheduler |
| `src/probos/__main__.py` | `webbrowser.open()` in serve command |
| `tests/test_hxi_events.py` | **New.** 12 tests for HXI event system |
| `ui/` | **New.** Full TypeScript/React/Three.js frontend (14 source files) |

#### Phase 23 design notes

- **Facade pattern honored** — HXI has zero independent logic. All state comes from the runtime via WebSocket events. If the connection drops, the canvas freezes but ProbOS keeps working. Reconnect delivers a full `state_snapshot` to resync
- **Event listeners are synchronous** — `_emit_event` calls listeners in a tight loop with exception swallowing. This avoids introducing async complexity at the event emission boundary. The API bridge schedules WebSocket sends as asyncio tasks via `_broadcast_event`
- **Layout is deterministic** — agents are positioned radially by pool in a fixed order. No force simulation (saves complexity; pools don't move). The visual weight comes from trust/confidence mapping, not from layout dynamics
- **Three.js not optional** — bloom, instanced mesh, tone mapping are impossible in SVG/Canvas2D. The rendering system handles hundreds of instances when federation adds cross-node agents
- **`hasattr` guards in api.py** — `create_app()` accepts a raw runtime object. Pre-existing tests use a `FakeRuntime` without `add_event_listener`. Guards prevent breakage

1532/1532 tests passing (+ 11 skipped). 12 new tests.

---

### AD-262 + AD-263: Close `run_command` Escape Hatch + Fix Python Interpreter Path

**Problem:** Sonnet routes requests like "generate a QR code" to `run_command` with `python -c "import qrcode; ..."` instead of flagging a capability gap. The `run_command` IntentDescriptor says "anything a shell can do" — a blank check. Additionally, when the LLM does generate `python -c ...`, the bare `python` isn't on PATH (venv's interpreter not exposed).

| AD | Decision |
|----|----------|
| AD-262 | Prompt hardening: reworded `run_command` descriptor (removed "anything a shell can do"), added anti-scripting rule (explicit ban on `python -c`/`node -e` workarounds), added QR-code capability gap example to `_GAP_EXAMPLES` |
| AD-263 | `_rewrite_python_interpreter()` — detects bare `python`/`python3` at command start, replaces with `sys.executable`. Same preprocessing pattern as `_strip_ps_wrapper()`. Applied on all platforms |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/agents/shell_command.py` | Reworded IntentDescriptor description, added `_BARE_PYTHON_RE` + `_rewrite_python_interpreter()`, wired in `_run_command()` |
| `src/probos/cognitive/prompt_builder.py` | Added anti-scripting rule to `_build_rules()`, added QR code entry to `_GAP_EXAMPLES` |
| `tests/test_prompt_builder.py` | 4 new tests: descriptor wording, anti-scripting rule, QR gap present, QR gap suppressed |
| `tests/test_expansion_agents.py` | 4 new tests: python rewrite, python3 rewrite, passthrough, full-path passthrough |

1552/1552 tests passing (+ 11 skipped). 8 new tests.

---

### AD-264: `probos reset` CLI Subcommand

**Problem:** No way to permanently clear learned state during development. `--fresh` skips restore for one session but data persists. Manual deletion of `data/knowledge/` works but has no audit trail and can miss ChromaDB.

| AD | Decision |
|----|----------|
| AD-264 | Offline CLI command `probos reset` that clears all KnowledgeStore artifacts (episodes, agents, skills, trust, routing, workflows, QA) + ChromaDB data. Git-commits the empty state. `--yes` skips confirmation, `--keep-trust` preserves trust scores. Does NOT boot the runtime |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/__main__.py` | Added `reset` subcommand to argparse, `_cmd_reset()` implementation |
| `tests/test_distribution.py` | 4 new tests: clear artifacts, keep-trust flag, clear ChromaDB, empty repo safety |

1556/1556 tests passing (+ 11 skipped). 4 new tests.

---

### AD-265: Designed Agent Pool Size = 1

**Problem:** Self-designed agents spawned in pools of 2. The IntentBus fans out to all pool subscribers, so web-fetching agents with `perceive()` httpx overrides made 2 identical HTTP requests per intent — doubling API quota usage and triggering rate limits (observed: CoinGecko 429 on first request from Bitcoin price agent).

| AD | Decision |
|----|----------|
| AD-265 | Designed agent pool default size changed from 2 to 1. The PoolScaler can still scale up later based on demand. One agent per pool eliminates duplicate API calls while preserving all existing scaling infrastructure |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/cognitive/self_mod.py` | `_create_pool_fn(agent_type, pool_name, 2)` → `1` |
| `src/probos/runtime.py` | `_create_designed_pool` default `size` parameter `2` → `1` |
| `tests/test_self_mod.py` | Mock `create_pool_fn` default `size` parameter `2` → `1` |

1556/1556 tests passing (+ 11 skipped). 0 new tests.

---

### AD-266: Post-Design Capability Report

**Problem:** When self-mod designs a new agent, the HXI only shows "[ClassName] deployed!" — not enough for users (or demo audiences) to understand what was built.

| AD | Decision |
|----|----------|
| AD-266 | After successful agent design, LLM generates a brief capability summary from the agent's `instructions` string (extracted via AST). Included in the `self_mod_success` event message. HXI already renders it — no frontend changes. Graceful fallback to original message on failure |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/api.py` | Added capability report generation in `_run_selfmod()` after successful design, before `self_mod_success` event |

1556/1556 tests passing (+ 11 skipped).

---

### AD-267: Self-Mod Progress Stepper

**Problem:** Self-mod pipeline takes 10-30 seconds with no visual progress feedback in the HXI. User sees "Starting agent design..." then waits with no indication of what's happening.

| AD | Decision |
|----|----------|
| AD-267 | Added `on_progress` async callback to `handle_unhandled_intent()`. Backend emits `self_mod_progress` events at each pipeline stage (designing → validating → testing → deploying → executing). HXI renders each step as a chat message with emoji prefix. No new UI component — leverages existing chat message rendering. Progress state cleared on success/failure |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/cognitive/self_mod.py` | Added optional `on_progress` callback parameter to `handle_unhandled_intent()`, called at each pipeline stage |
| `src/probos/api.py` | Wire `_on_progress` callback to emit `self_mod_progress` events with step labels |
| `ui/src/store/useStore.ts` | Added `selfModProgress` state, handle `self_mod_progress` event, clear on completion |
| `tests/test_self_mod.py` | 2 new tests: progress callback called at all stages, backward compat without callback |

1558/1558 tests passing (+ 11 skipped). 2 new tests.

---

### AD-268: AgentDesigner Mesh-Fetch Template

**Problem:** Designed web-fetching agents used raw `httpx.AsyncClient` in `perceive()`, bypassing the mesh's governance (consensus, trust, event logging) and causing duplicate API calls (sandbox + auto-retry = 2 calls). This triggered rate limits on free-tier APIs.

| AD | Decision |
|----|----------|
| AD-268 | Replaced httpx template with mesh-fetch template in `AGENT_DESIGN_PROMPT`. Designed agents now route HTTP through `self._runtime.intent_bus.broadcast(IntentMessage(intent="http_fetch"))` — same pattern as bundled agents (AD-248). Sandbox test passes without making real HTTP calls (`self._runtime` is None → graceful FETCH_ERROR). All HTTP goes through HttpFetchAgent — governed, logged, deduplicated |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/cognitive/agent_designer.py` | Replaced httpx perceive() example and web-fetching template with mesh-fetch pattern. Updated RULES to direct agents to use mesh, not httpx directly |
| `tests/test_agent_designer_cognitive.py` | 1 new test: design prompt uses mesh broadcast, not raw httpx |

1559/1559 tests passing (+ 11 skipped). 1 new test.

---

### HXI Fixes: New Agent Position, Bloom Visual, Tooltip Raycasting, Command Validation

**Problem (position):** Designed agents spawned at `[0,0,0]` (center, alongside heartbeat agents) instead of on the outer domain sphere. Bloom animation was amber — same color as heartbeat — making it visually indistinct.

**Problem (tooltips):** `SelfModBloom` subscribed to `useStore((s) => s.agents)`, causing re-renders on every agent state/trust update inside the R3F Canvas. This disrupted the internal raycaster event system, breaking hover tooltips for ALL agents.

**Problem (command validation):** `run_command` executed nonexistent commands (e.g., `qr`) producing raw shell errors. No hint to use self-mod.

| Fix | Change |
|-----|--------|
| New agent position | `useStore.ts`: Derive `agentType` from pool name for new agents; `computeLayout()` already places domain agents on outer sphere |
| Bloom visual | `animations.tsx`: Cyan-white (`#80f0ff`) ring geometry instead of amber sphere. 800ms duration, faster 150ms attack, `DoubleSide` |
| Tooltip fix | `animations.tsx`: Changed `useStore((s) => s.agents)` → `useStore.getState().agents` inside effect. Non-reactive read eliminates Canvas re-renders |
| Command validation | `shell_command.py`: Added `_command_exists()` — checks builtins, PowerShell cmdlets (hyphen), `shutil.which()`. Returns descriptive error suggesting self-mod |

**Files changed:**

| File | Change |
|------|--------|
| `ui/src/store/useStore.ts` | Derive agentType from pool name in agent_state handler |
| `ui/src/canvas/animations.tsx` | Cyan-white ring bloom, non-reactive agent lookup, 200ms delay for layout |
| `src/probos/agents/shell_command.py` | Pre-execution command validation with `_command_exists()` |

1559/1559 tests passing (+ 11 skipped).

### AD-269: Fix Conversational Responses Showing Build Agent Button

**Problem:** Saying "Hello" in the HXI showed a "Build Agent" button alongside the greeting. The API-mode self-mod proposal path in `process_natural_language()` was missing the `is_gap` check, causing `_extract_unhandled_intent()` to run for conversational replies.

| AD | Decision |
|----|----------|
| AD-269 | Added `if is_gap or not dag.response` guard around the API-mode self-mod proposal path. Conversational responses (where `dag.response` is set and `is_gap` is False) no longer trigger `_extract_unhandled_intent()` or produce `self_mod_proposal` in the API response |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/runtime.py` | Added `is_gap` guard in API-mode self-mod proposal branch |

1559/1559 tests passing (+ 11 skipped).

### AD-270: Per-Domain Rate Limiter in HttpFetchAgent

**Problem:** Free-tier APIs (CoinGecko, wttr.in) throttle when ProbOS makes multiple requests to the same domain in quick succession. No rate awareness in the HTTP layer caused repeated 429 errors.

| AD | Decision |
|----|----------|
| AD-270 | Per-domain rate limiter in `HttpFetchAgent` — the single gateway for all mesh HTTP. Tracks per-domain state (last request time, min interval, consecutive 429 count). Known domain overrides for common free APIs (CoinGecko: 3s, wttr.in: 2s, DuckDuckGo: 2s). Adaptive: reads `Retry-After` and `X-RateLimit-*` response headers. Exponential backoff on consecutive 429s. Default 2s interval for unknown domains. Auto-retries once on 429 after computed delay. Class-level shared state across all pool members |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/agents/http_fetch.py` | Added `DomainRateState` dataclass, `_domain_state` class-level dict, `_KNOWN_RATE_LIMITS`, `_get_domain_state()`, `_wait_for_rate_limit()`, `_update_rate_state()`. Modified `_fetch_url()` with pre-request delay + post-response state update + 429 retry. Added rate limit headers to `_SAFE_HEADERS` |

1566/1566 tests passing (+ 11 skipped). 7 new tests.

### AD-271: Vibe Agent Creation — Human-Guided Agent Design

**Problem:** Self-mod agent creation was fully automated — the human only got approve/reject. No input into what gets built or how. This led to poorly designed agents when the LLM guessed the wrong implementation approach.

| AD | Decision |
|----|----------|
| AD-271 | Added "🎨 Design Agent" option alongside "✨ Build Agent" in the HXI self-mod proposal. User describes desired behavior in a text field → LLM enriches into detailed spec → user reviews → approves → same design pipeline with the enriched description. New `/api/selfmod/enrich` endpoint. No changes to the self-mod pipeline itself — the enriched text flows through as `intent_description` |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/api.py` | Added `EnrichRequest` model and `POST /api/selfmod/enrich` endpoint |
| `ui/src/components/IntentSurface.tsx` | Added "🎨 Design Agent" button, vibe input textarea, enrichment display, approve/edit/cancel flow |

1568/1568 tests passing (+ 11 skipped). 2 new tests.

### AD-272: Decision Distillation — Deterministic Learning Loop

**Problem:** Every CognitiveAgent call made an LLM request even for identical repetitive queries. "Bitcoin price" 100 times = 100 LLM calls (2-5s, ~$1-5 total).

| AD | Decision |
|----|----------|
| AD-272 | In-memory decision cache in `CognitiveAgent.decide()`. Cache key: SHA256 of instructions + observation. Cache hit returns instantly (<1ms, $0) with `"cached": True` flag. TTL per entry — time-sensitive agents (price, weather) get 2min TTL, static knowledge (translate, calculate) gets 1hr. Module-level cache dict keyed by agent_type (each agent type has its own cache). 1000-entry cap per type with oldest eviction. Cache metrics (hits/misses) exposed via `cache_stats()` |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/cognitive/cognitive_agent.py` | Added `_DECISION_CACHES`, `_CACHE_HITS`, `_CACHE_MISSES` module-level dicts. `_compute_cache_key()`, `_get_cache_ttl()` methods. `decide()` checks cache before LLM, stores result after. `evict_cache_for_type()`, `cache_stats()` class methods. 1000-entry cap with oldest eviction |

1575/1575 tests passing (+ 11 skipped). 7 new tests.

### AD-273: Conversation Context for Decomposer

**Problem:** Each message was stateless — the decomposer couldn't resolve references like "What about Portland?" after a Seattle weather query. The system felt "born 5 minutes ago" every time.

| AD | Decision |
|----|----------|
| AD-273 | HXI sends last 10 chat messages as `history` in ChatRequest. Runtime passes to decomposer as `conversation_history`. Decomposer injects last 5 messages (truncated to 200 chars) as CONVERSATION CONTEXT section in LLM prompt. LLM resolves references naturally. Optional parameter — backward compatible with shell/tests |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/api.py` | ChatMessage model, history field on ChatRequest, passed to process_natural_language() |
| `src/probos/runtime.py` | conversation_history parameter on process_natural_language(), passed to decomposer |
| `src/probos/cognitive/decomposer.py` | conversation_history parameter on decompose(), CONVERSATION CONTEXT prompt section |
| `ui/src/components/IntentSurface.tsx` | Sends last 10 messages as history in /api/chat request |

1578/1578 tests passing (+ 11 skipped). 3 new tests.

### E2E Self-Mod Pipeline Tests

Added `tests/test_selfmod_e2e.py` — 12 integration tests exercising the full self-mod chain through the FastAPI API layer using httpx AsyncClient with ASGITransport. Covers: capability gap detection, self-mod approve + agent creation, pool size 1, auto-retry message routing, QA ordering, hello response, conversation history passthrough, enrich endpoint, empty message, self-mod disabled, slash commands. No production code modified.

1590/1590 tests passing (+ 11 skipped). 12 new tests.

### Phase 24a: Discord Bot Adapter (AD-274 through AD-278)

**Problem:** ProbOS had no external channel integrations — users could only interact via CLI shell or HXI web UI. Phase 24 calls for channel adapters to bridge external messaging platforms.

| AD | Decision |
|----|----------|
| AD-274 | `ChannelAdapter` ABC + `ChannelMessage` dataclass + shared `extract_response_text()` in `src/probos/channels/`. Reusable base for Discord, Slack, email, Teams |
| AD-275 | `probos serve --discord` flag wires `DiscordAdapter` lifecycle into `_serve()`. Startup after app creation, shutdown before runtime.stop(). Token resolved from `PROBOS_DISCORD_TOKEN` env var or config |
| AD-276 | `discord.py>=2.0` added as optional dependency in pyproject.toml. Commented channel config section added to system.yaml |
| AD-277 | 14 tests in `test_channel_base.py`: response formatter (8), ChannelMessage (2), handle_message routing + history (4) |
| AD-278 | 8 tests in `test_discord_adapter.py`: message chunking (4), adapter init (2), config parsing (2) |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/channels/__init__.py` | Package init, re-exports |
| `src/probos/channels/base.py` | ChannelAdapter ABC, ChannelMessage, per-channel conversation history |
| `src/probos/channels/response_formatter.py` | Shared `extract_response_text()` extracted from api.py |
| `src/probos/channels/discord_adapter.py` | Full Discord bot: message routing, mention filtering, channel filtering, chunked replies |
| `src/probos/config.py` | DiscordConfig + ChannelsConfig models |
| `src/probos/api.py` | Refactored to use shared response formatter |
| `src/probos/__main__.py` | `--discord` flag, adapter lifecycle in _serve() |
| `pyproject.toml` | Optional `[discord]` dependency group |
| `config/system.yaml` | Commented channels config section |

1612/1612 tests passing (+ 11 skipped). 22 new tests.

### Phase 24b: Self-Assessment Bug Fixes (AD-279, AD-280)

**Problem:** ProbOS demonstrated functional self-awareness by diagnosing its own gaps via Discord conversation. Investigation of its self-assessment revealed two bugs causing partially inaccurate self-reporting.

| AD | Decision |
|----|----------|
| AD-279 | Fix key name mismatch in `_introspect_memory()`: reads `total_episodes` but `get_stats()` returns `total`. Same mismatch for `unique_intents` and `success_rate`. ProbOS always reports 0 episodes even when episodes are stored correctly |
| AD-280 | Add `TrustNetwork.reconcile(active_agent_ids)` called after warm boot. Removes stale trust entries from previous sessions. Fixes 72-vs-43 agent count discrepancy in self-assessment. `TrustNetwork.remove()` was dead code — never called anywhere |

**Status:** Complete — both bugs identified by ProbOS's own self-assessment via Discord. 9 new tests (4 introspect memory + 5 trust reconcile). Also fixed pre-existing bug where `_restore_from_knowledge()` used `create_with_prior()` (no-op if record exists) instead of force-setting alpha/beta on warm boot restore.

### Phase 24c: Lightweight Task Scheduler (AD-281 through AD-284)

**Problem:** ProbOS identified its own lack of background scheduling as an architectural gap during a Discord self-assessment conversation ("I don't have a background timer"). The existing `SchedulerAgent` stores reminders to file but cannot execute them on a timer.

| AD | Decision |
|----|----------|
| AD-281 | `TaskScheduler` engine in `cognitive/task_scheduler.py`: background asyncio loop (1s tick), `ScheduledTask` dataclass, one-shot and recurring tasks, session-scoped (does not survive restart) |
| AD-282 | Wire `TaskScheduler` into `ProbOSRuntime` lifecycle (start/stop), expose as property |
| AD-283 | Upgrade `SchedulerAgent`: remove "no background timer" disclaimer, `act()` calls `task_scheduler.schedule/cancel/list`, reminders.json reload on boot |
| AD-284 | Channel delivery for scheduled tasks: results sent to Discord/Slack channel when `channel_id` is set on the task |

**Scope boundary:** In-session scheduling only. Persistent tasks with checkpointing and resume-after-restart remain in Phase 25.

**Status:** Complete — 17 tests, 1705/1705 passing

---

### AD-293: Crew Team Introspection

**Problem:** Asking "tell me about the medical team" failed — `agent_info` searches by `agent_type` and no agent has type `"medical"`. Pool groups (AD-291) were invisible to the intent system.

| AD | Decision |
|----|----------|
| AD-293 | Add `team_info` intent to IntrospectionAgent. Lists all crew teams (no param) or returns detailed health/roster/pools for a specific team. Fuzzy substring matching on team names. Defense-in-depth: `agent_info` now falls back to pool name search when agent_type match fails |

| File | Change |
|------|--------|
| `src/probos/agents/introspect.py` | Added `team_info` IntentDescriptor, routing, `_team_info()` method (list all / specific with fuzzy match), pool name fallback in `_agent_info()` |
| `tests/test_team_introspection.py` | 6 tests: specific team, all teams, unknown team, fuzzy match, pool name fallback, core team |

**Status:** Complete — 6 tests, 1711/1711 passing

### AD-294: HXI Crew Team Sub-Clusters

**Problem:** Agents on the HXI canvas were on a flat Fibonacci sphere, sorted by group for adjacency but with no visual boundary. Users couldn't distinguish teams without hovering.

| AD | Decision |
|----|----------|
| AD-294 | Replace flat Fibonacci sphere layout with gravitational sub-clusters. Each pool group gets its own center on a spacing sphere (radius 6.0), agents orbit within on mini Fibonacci spheres. Cluster radius scales: `0.8 + √n × 0.4`. Faint wireframe boundary shell + BackSide solid glow + floating text label per team. `GROUP_TINT_HEXES` color map. Falls back to flat layout when no pool group data available |

| File | Change |
|------|--------|
| `ui/src/store/useStore.ts` | `GroupCenter` interface, `GROUP_TINT_HEXES`, group-aware `computeLayout()`, `groupCenters` in state |
| `ui/src/canvas/clusters.tsx` | New — `TeamClusters` component with wireframe shells and text labels |
| `ui/src/components/CognitiveCanvas.tsx` | Added `<TeamClusters />` to scene |
| `ui/src/__tests__/useStore.test.ts` | 5 tests: cluster grouping, groupCenters metadata, ungrouped agents, heartbeat center, state_snapshot |

**Status:** Complete — 5 Vitest tests, 20/20 Vitest passing

### AD-295: Causal Attribution for Emergent Behavior + Self-Introspection

**Problem:** ProbOS detects emergent patterns but cannot explain *why* they're happening. No causal trail for trust changes — `record_outcome()` updated alpha/beta without recording which intent, Shapley values, or verifier caused the change. Episodes lacked Shapley attribution. IntrospectionAgent couldn't examine ProbOS's own source code.

| AD | Decision |
|----|----------|
| AD-295a | `TrustEvent` dataclass + ring buffer (`deque(maxlen=500)`) in TrustNetwork. `record_outcome()` gains optional `intent_type`, `episode_id`, `verifier_id` kwargs. Old/new scores captured per event. Query methods: `get_recent_events()`, `get_events_for_agent()`, `get_events_since()` |
| AD-295b | `Episode` gains `shapley_values: dict[str, float]` and `trust_deltas: list[dict]`. `_build_episode()` captures from `_last_shapley_values` and `trust_network.get_events_since(t_start)`. ChromaDB serialization updated with `shapley_values_json` and `trust_deltas_json` |
| AD-295c | `detect_trust_anomalies()` adds `causal_events` list (last 5 trust events per anomalous agent) to `EmergentPattern.evidence`. `detect_routing_shifts()` adds `agent_trust` and `hebbian_weight` context to routing shift evidence |
| AD-295d | `introspect_design` intent on IntrospectionAgent. Uses `rt.codebase_index.query()` + `get_agent_map()` + `get_layer_map()` to answer architecture questions. Graceful fallback when CodebaseIndex unavailable |

| File | Change |
|------|--------|
| `src/probos/consensus/trust.py` | `TrustEvent` dataclass, `_event_log` deque, enriched `record_outcome()`, 3 query methods |
| `src/probos/types.py` | `Episode.shapley_values`, `Episode.trust_deltas` fields |
| `src/probos/runtime.py` | Causal context in verification `record_outcome()`, `_build_episode()` captures Shapley + trust deltas |
| `src/probos/cognitive/episodic.py` | Serialize/deserialize new Episode fields in ChromaDB metadata |
| `src/probos/cognitive/emergent_detector.py` | `causal_events` in trust anomaly evidence, trust/Hebbian context in routing shifts |
| `src/probos/agents/introspect.py` | `introspect_design` intent + `_introspect_design()` method |
| `tests/test_trust_events.py` | 6 tests |
| `tests/test_episode_attribution.py` | 4 tests |
| `tests/test_causal_attribution.py` | 3 tests |
| `tests/test_introspect_design.py` | 3 tests |

**Status:** Complete — 16 new tests

### AD-296: HXI Cluster Label Billboarding + Security Pool Group

**Problem:** Team name labels rotated with the 3D scene, becoming unreadable. Red team agents had no pool group, floating in "_ungrouped" cluster.

| AD | Decision |
|----|----------|
| AD-296 | Wrap team name `<Text>` in `<Billboard follow>` from `@react-three/drei` so labels always face the camera. Add `security` PoolGroup for `red_team` pool (not excluded from scaler). Add `security: '#c85068'` to `GROUP_TINT_HEXES`. 5 crew teams: Core, Bundled, Medical, Self-Mod, Security |

**Status:** Complete — 1 new Vitest test, 21 Vitest total

### AD-297: CodebaseIndex as Ship's Library

| AD | Decision |
|----|----------|
| AD-297 | Decouple CodebaseIndex from `config.medical.enabled` — build unconditionally at startup so all agents (including IntrospectionAgent) can access source knowledge. Enhance `_introspect_design()` to call `read_source()` on top 3 matching files (first 80 lines each) so ProbOS can analyze its own source code, not just metadata |

**Status:** Complete — 4 new Python tests, 1731 Python total

### AD-298: Word-Level Query Matching in CodebaseIndex

| AD | Decision |
|----|----------|
| AD-298 | Replace exact-substring matching in `CodebaseIndex.query()` with word-level keyword scoring. Split concept into keywords, filter stop words (`_STOP_WORDS` frozenset), score each keyword independently against file paths (+3), docstrings (+2), and class names (+2). Additive scoring ranks multi-keyword matches higher. Fallback to full string if all words are stop words |

**Status:** Complete — 4 new Python tests, 1735 Python total

### AD-299: Project Docs in CodebaseIndex

| AD | Decision |
|----|----------|
| AD-299 | Index whitelisted project Markdown files (`DECISIONS.md`, `PROGRESS.md`, roadmap, progress-era-* files) alongside Python source code. Store with `docs:` prefix in `_file_tree`. Parse `# title` as docstring and `## section` headings as searchable "classes". `read_source()` handles `docs:` paths against `_project_root` with path traversal protection. No changes to `_introspect_design()` — docs flow through existing `query()` → `read_source()` pipeline |

**Status:** Complete — 5 new Python tests, 1740 Python total

### AD-300: Section-Targeted Doc Reading in CodebaseIndex

| AD | Decision |
|----|----------|
| AD-300 | Store section line numbers in `_analyze_doc()` alongside section names. New `read_doc_sections(file_path, keywords, max_lines=200)` scores sections by keyword overlap and reads only matching sections. `_introspect_design()` uses section-targeted reading for `docs:` files instead of fixed 80-line read. Imports `_STOP_WORDS` to extract keywords from the question for section matching |

**Status:** Complete — 6 new Python tests, 1746 Python total

### AD-302: BuilderAgent — Code Generation via LLM

| AD | Decision |
|----|----------|
| AD-302 | BuilderAgent — CognitiveAgent (domain/Engineering) that generates code from BuildSpec via deep LLM tier. Parses file blocks from LLM output, returns for Captain approval. Registered as `builder` in `engineering` pool group with consensus required |
| AD-303 | Git integration — async git helpers (branch, commit, checkout) via asyncio.create_subprocess_exec. `execute_approved_build()` pipeline: branch → write → test → commit. ProbOS Builder as git co-author |

**Status:** Complete — 29 new Python tests, 1775 Python total

---

## Phase 32b: Builder API + HXI (AD-304–305)

*"Engineering to Bridge — the blueprints are ready for your review, Captain."*

| AD | Decision |
|----|----------|
| AD-304 | Builder API — `POST /api/build/submit` triggers BuilderAgent via intent bus, `/api/build/approve` executes `execute_approved_build()`. `/build` slash command parses `title: description` format. WebSocket events: build_started, build_progress, build_generated, build_success, build_failure. Fire-and-forget async pattern matching selfmod |
| AD-305 | Builder HXI — BuildProposal type, Zustand build_* event handlers, IntentSurface inline approval UI with file summary, code review toggle, Approve/Reject buttons. Transient buildProposal on ChatMessage (not persisted to localStorage) |

**Status:** Complete — 15 new Python tests, 1790 Python + 21 Vitest total

---

## Phase 32c: Architect Agent (AD-306–307)

*"The First Officer surveys the star charts, identifies the next heading, and drafts the orders."*

| AD | Decision |
|----|----------|
| AD-306 | ArchitectAgent — Science-team CognitiveAgent (deep tier) that analyzes roadmap and codebase to produce structured ArchitectProposal containing a BuildSpec. Parses ===PROPOSAL=== blocks from LLM output. `perceive()` gathers codebase context via CodebaseIndex (files, agents, layers, roadmap sections, DECISIONS tail). `requires_consensus=False`, `requires_reflect=True` |
| AD-307 | Runtime integration — architect template registered, `architect` pool (target_size=1), `science` PoolGroup, codebase_skill attached independently of medical config, HXI teal color `#50a0b0` |

**Status:** Complete — 25 new Python tests, 1815 Python + 21 Vitest total

---

## Phase 32d: Architect API + HXI (AD-308–309)

*"The First Officer presents the schematics; the Captain decides whether to build."*

| AD | Decision |
|----|----------|
| AD-308 | Architect API — `POST /api/design/submit`, `POST /api/design/approve`, `/design` slash command (supports `/design <feature>` and `/design phase N: <feature>`), `_run_design` background pipeline, `design_*` WebSocket events (design_started, design_progress, design_generated, design_failure). `_pending_designs` in-memory store. Approval forwards embedded BuildSpec to existing `_run_build` pipeline |
| AD-309 | Architect HXI — `ArchitectProposalView` TypeScript type, Zustand `design_*` event handlers with `designProgress` state, IntentSurface inline proposal review UI (teal theme `#50a0b0`) with summary/rationale/roadmap/priority/target-files/risks/dependencies card, collapsible full spec, Approve & Build / Reject buttons |

**Status:** Complete — 14 new Python tests, 1826 Python + 21 Vitest total

---

## Phase 32e: Architect Agent Quality (AD-310)

*"An officer who makes decisions without reading the ship's logs is no officer at all."*

| AD | Decision |
|----|----------|
| AD-310 | ArchitectAgent perceive() upgraded with 7 context layers (file tree with actual paths, source snippets of top-5 matches, slash commands from shell.py + inline API commands, API route extraction from @app decorators, pool group crew structure, documentation with 80-line DECISIONS tail, sample build prompt for format calibration). Instructions hardened with 5 verification rules preventing path hallucination, duplicate slash commands, duplicate API routes, duplicate agents, and ungrounded proposals |

**Status:** Complete — 12 new Python tests, 1838 Python + 21 Vitest total

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
| AD-313 | Builder MODIFY mode — search-and-replace (`===SEARCH===`/`===REPLACE===`/`===END REPLACE===`) execution for existing files. `_parse_file_blocks()` parses SEARCH/REPLACE pairs within MODIFY blocks. `execute_approved_build()` applies replacements sequentially (first occurrence only). `perceive()` reads `target_files` so the LLM sees current content for accurate SEARCH blocks. `_validate_python()` runs `ast.parse()` on .py files after write/modify. Old `===AFTER LINE:===` format deprecated with warning |

**Status:** Complete — 20 new Python tests, 1891 Python + 21 Vitest total

## Phase 32i: Ship's Computer Identity (AD-317)

| AD | Decision |
|----|----------|
| AD-317 | Ship's Computer Identity — The Decomposer's system prompt now carries a LCARS-era Ship's Computer identity: calm, precise, never fabricates. PROMPT_PREAMBLE in prompt_builder.py includes 6 grounding rules. Dynamic System Configuration section counts intents by tier. Hardcoded example responses no longer claim unregistered capabilities. runtime.py builds a lightweight runtime_summary (pool count, agent count, departments, intent count) injected into the decompose() user prompt as SYSTEM CONTEXT. Legacy prompt path unchanged. |

**Status:** Complete — 8 new Python tests, 1899 Python + 21 Vitest total

## Self-Knowledge Grounding Progression (AD-318, AD-319, AD-320)

The Ship's Computer Identity (AD-317) established Level 1: prompt-level grounding rules that prevent the worst confabulation. The following three ADs complete the progression from rules → data → verification → delegation, closing the gap between ProbOS's self-knowledge and the scaffolding quality of tools like Claude Code (which verify claims by reading files before responding).

| AD | Decision |
|----|----------|
| AD-318 | **SystemSelfModel** — A lightweight, always-current in-memory object maintained by runtime.py that holds verified facts: pool count, agent roster (name + type + tier), registered intents, recent errors (last 10), uptime, last capability gap event, department summary. Updated reactively on every pool/agent add/remove/change. Injected automatically into the Decomposer's working memory (WorkingMemorySnapshot) so the LLM never starts cold. Analogous to Claude Code's MEMORY.md but for live runtime state. Replaces the ad-hoc `runtime_summary` dict from AD-317 with a structured, typed dataclass. **Design note:** AD-317's `_build_runtime_summary()` in runtime.py (line ~1252) currently reaches into `self.decomposer._intent_descriptors` to count intents — a runtime → decomposer internal coupling. AD-318 should own intent counts directly (updated when agents register/deregister), so the Decomposer reads from SystemSelfModel instead of the reverse. The existing `_build_runtime_summary()` method and the `runtime_summary` parameter on `decompose()` should be replaced by SystemSelfModel injection. |
| AD-319 | **Pre-Response Verification** — Before the Decomposer returns a natural language response to the human, a fast validation pass checks the response text against the SystemSelfModel: (1) regex scan for capability claims not in the registered intent table, (2) agent name references not in the agent roster, (3) feature descriptions that reference unbuilt systems. For simple responses, this is a pure-Python string check against the SystemSelfModel (zero LLM cost). For complex reflective responses, optionally invoke a fast-tier LLM call with the response + SystemSelfModel to flag contradictions. Failed checks trigger rewording or an honest uncertainty qualifier. This is the "read before you speak" pattern — the Decomposer verifies its own output before the Captain sees it. |
| AD-320 | **Introspection Delegation** — For "how do I work?" and self-knowledge questions, the Decomposer routes to IntrospectionAgent first instead of answering directly. IntrospectionAgent queries SystemSelfModel + CodebaseIndex + episodic memory, assembles grounded facts, and returns a structured response. The Decomposer then synthesizes the final natural language answer from verified data rather than generating it from LLM training knowledge. Detection heuristic: intent classification tags self-referential queries ("what agents do you have", "how does trust work", "what can you do") as `introspect_self` intent type. The Decomposer becomes a dispatcher for self-knowledge, not the answerer. |

**Progression:** AD-317 (rules) → AD-318 (data) → AD-319 (verification) → AD-320 (delegation). Each level makes ProbOS's self-knowledge more reliable — not because the LLM gets smarter, but because the scaffolding gets richer.

**Status:** Planned

## Phase 32j: Builder Test-Fix Loop (AD-314)

| AD | Decision |
|----|----------|
| AD-314 | Builder Test-Fix Loop — `execute_approved_build()` now runs pytest in a retry loop: initial pass + up to `max_fix_attempts` (default 2) LLM-driven fix iterations. `_run_tests()` async helper extracted. `_build_fix_prompt()` feeds truncated (3000-char) test failure output back to the LLM with a minimal fix-only prompt. Fix responses parsed with existing `_parse_file_blocks()` and applied with existing MODIFY/CREATE logic. `fix_attempts` count added to `BuildResult`. Two flaky network tests fixed: `test_unreachable_returns_false` and `test_all_tiers_unreachable_falls_back_to_mock` now use mocked connections instead of real network calls. |

**Status:** Complete — 7 new Python tests (builder) + 2 fixed (network), 1906 Python + 21 Vitest total

## Phase 32k: Escalation Tier 3 Timeout (AD-325)

| AD | Decision |
|----|----------|
| AD-325 | Escalation Tier 3 Timeout — `_tier3_user()` now wraps the `user_callback` in `asyncio.wait_for()` with a configurable `user_timeout` (default 120s). On timeout, returns `EscalationResult(resolved=False, user_approved=None)` with descriptive reason. User-wait seconds still accumulated on timeout for accurate DAG deadline accounting. Prevents hung escalation cascades when user callback never returns. |

**Status:** Complete — 5 new Python tests, 1911 Python + 21 Vitest total

## Phase 32l: API Task Lifecycle & WebSocket Hardening (AD-326)

| AD | Decision |
|----|----------|
| AD-326 | API Task Lifecycle & WebSocket Hardening — `_background_tasks` set tracks all `asyncio.create_task()` pipelines with automatic done-callback cleanup. `_track_task()` helper replaces 7 bare `create_task()` calls (build, design, self-mod, execute pipelines). `_broadcast_event()` inner `_safe_send()` coroutine catches per-client `send_json()` failures and prunes dead WebSocket clients. `GET /api/tasks` endpoint for Captain visibility into active pipelines. FastAPI lifespan handler drains/cancels all tasks on shutdown. |

**Status:** Complete — 5 new Python tests, 1916 Python + 21 Vitest total

## Phase 32m: CodeValidator Hardening (AD-327)

| AD | Decision |
|----|----------|
| AD-327 | CodeValidator Hardening — (a) `_check_schema()` now rejects code with multiple `BaseAgent` subclasses (was silently picking first). (b) New `_check_class_body_side_effects()` scans class bodies for bare function calls, loops, and conditionals that execute at import time. Both are early-return patterns consistent with existing validator flow. |

**Status:** Complete — 4 new Python tests, 1920 Python + 21 Vitest total

## Phase 32n: Self-Mod Durability & Bloom Fix (AD-328)

| AD | Decision |
|----|----------|
| AD-328 | Self-Mod Durability & Bloom Fix — (a) Knowledge store and semantic layer post-deployment failures now logged with `logger.warning(exc_info=True)` instead of bare `except: pass`. Partial failure warnings propagated in `self_mod_success` WebSocket event and displayed to Captain. (b) `self_mod_success` event now includes `agent_id`. `pendingSelfModBloom` stores `agent_id` (falling back to `agent_type`). Bloom animation lookup uses `a.id || a.agentType` for accurate targeting when multiple agents share a type. |

**Status:** Complete — 3 new Python tests, 1 new Vitest, 1923 Python + 22 Vitest total

## Phase 32o: HXI Canvas Resilience & Component Tests (AD-329)

| AD | Decision |
|----|----------|
| AD-329 | HXI Canvas Resilience & Component Tests — (a) `connections.tsx` agents subscription replaced with ref + count-based re-render. Pool centers cached in `useMemo` keyed on agent count, eliminating O(agents×connections) per-state-change recomputation. (b) Unnecessary Zustand action subscriptions removed from `CognitiveCanvas.tsx` and `AgentTooltip.tsx` — stable action refs read via `getState()` instead. (c) Component-level Vitest tests for pool center computation, connection filtering, tooltip state, and animation event clearing. |

**Status:** Complete — 8 new Vitest tests, 1923 Python + 30 Vitest total

## Phase 32p: Architect Proposal Validation + Pattern Recipes (AD-316a)

| AD | Decision |
|----|----------|
| AD-316a | Architect Proposal Validation + Pattern Recipes — (a) New `_validate_proposal()` method with 6 programmatic checks: required field presence, non-empty test_files, target/reference file path verification against codebase_index file tree (with directory-prefix fallback for new files), priority value validation, and description minimum length (100 chars). Warnings are advisory (non-blocking) — `act()` returns `success: True` with optional `warnings` list. (b) Pattern Recipes section appended to instructions string with 3 reusable templates: NEW AGENT, NEW SLASH COMMAND, NEW API ENDPOINT — each with TARGET_FILES, REFERENCE_FILES, TEST_FILES, and CHECKLIST. |

**Status:** Complete — 14 new Python tests, 1937 Python + 30 Vitest total

## Phase 32q: SystemSelfModel (AD-318)

| AD | Decision |
|----|----------|
| AD-318 | SystemSelfModel — Structured runtime self-knowledge. (a) New `SystemSelfModel` dataclass in `src/probos/cognitive/self_model.py` with `PoolSnapshot` — compact snapshot of topology (pools, departments, intents), identity (version, mode), and health (uptime, recent errors, last capability gap). `to_context()` serializes to ~500 char text for LLM injection. (b) `_build_system_self_model()` on runtime replaces `_build_runtime_summary()` — builds model from live pool state, pool groups (departments), dream scheduler (mode), decomposer (intent count). (c) `_record_error()` caps at 5 recent errors, wired into reflect and episode storage failure handlers. Capability gap tracking stores first 100 chars of unhandled requests. |

**Status:** Complete — 9 new Python tests (1 updated), 1946 Python + 30 Vitest total

## Phase 32r: Pre-Response Verification (AD-319)

| AD | Decision |
|----|----------|
| AD-319 | Pre-Response Verification — Fact-check responses against SystemSelfModel. (a) New `_verify_response()` method on runtime — zero-LLM, regex-based string matching with 5 checks: pool count claims, agent count claims, fabricated department names (context-aware pattern matching), fabricated pool names (with generic word exclusion set), system mode contradictions. Non-blocking: appends correction footnote on violations, never suppresses responses. (b) Wired into two response paths: no-nodes path (dag.response) and reflection path (_execute_dag). `_execute_dag` signature extended with optional `self_model` parameter. Timeout/error fallback strings not verified (canned text, not LLM output). |

**Status:** Complete — 14 new Python tests, 1960 Python + 30 Vitest total

## Phase 32s: Introspection Delegation (AD-320)

| AD | Decision |
|----|----------|
| AD-320 | Introspection Delegation — Grounded self-knowledge answers. Level 4 of self-knowledge progression: rules (AD-317) → data (AD-318) → verification (AD-319) → **delegation** (AD-320). (a) New `_grounded_context()` method on IntrospectionAgent builds detailed text from `SystemSelfModel` — per-pool breakdowns grouped by department, full intent listing, health signals. (b) Enriched 4 intent handlers (`_agent_info()`, `_system_health()`, `_team_info()`, `_introspect_system()`) to include `grounded_context` key in output dicts for reflector consumption. (c) REFLECT_PROMPT rule 7: treat `grounded_context` as VERIFIED SYSTEM FACTS. (d) `_summarize_node_result()` preserves grounded_context outside truncation boundary, labeled as GROUNDED SYSTEM FACTS. |

**Status:** Complete — 12 new Python tests, 1972 Python + 30 Vitest total

