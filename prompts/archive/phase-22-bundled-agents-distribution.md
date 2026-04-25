# Phase 22 — Bundled Agent Suite + Distribution

## Context

You are building Phase 22 of ProbOS, a probabilistic agent-native OS runtime. Read `PROGRESS.md` for full architectural context. Current state: **1454/1454 tests passing + 11 skipped. Latest AD: AD-246.**

ProbOS has powerful cognitive infrastructure — self-modification, Hebbian routing, trust scoring, episodic memory, dreaming, feedback loops — but only 7 core tool agents (file reader, file writer, directory list, file search, shell command, http fetch, introspection). A new user must wait for self-mod to design agents before ProbOS can do anything beyond basic file I/O. This is like selling an operating system without Notepad, Calculator, or a web browser.

This phase adds **10 bundled CognitiveAgent subclasses** covering the most common personal assistant tasks, plus distribution infrastructure (`pip install probos`, `probos init`, `probos serve`). After this phase, ProbOS is useful on Day 1.

Self-mod continues to handle the long tail — tasks the bundled agents don't cover trigger the existing capability gap → design → validate → deploy pipeline. The bundled agents are the 80%; self-mod builds the 20%.

---

## Pre-Build Audit

Before writing any code, verify:

1. **Latest AD number in PROGRESS.md** — confirm AD-246 is the latest. Phase 22 AD numbers start at **AD-247**. If AD-246 is NOT the latest, adjust all AD numbers upward accordingly.
2. **Test count** — confirm 1454 tests pass before starting: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
3. **Read these files thoroughly:**
   - `src/probos/cognitive/cognitive_agent.py` — understand `CognitiveAgent(BaseAgent)`: `instructions`, `_llm_client`, `_runtime`, `perceive()`, `decide()`, `act()`, `report()`, `handle_intent()`, `_build_user_message()`, `_resolve_tier()`, `add_skill()`. All bundled agents extend this class
   - `src/probos/substrate/agent.py` — understand `BaseAgent`: `agent_type`, `tier`, `intent_descriptors`, `_handled_intents`, `default_capabilities`, `initial_confidence`
   - `src/probos/types.py` — understand `IntentDescriptor`, `IntentMessage`, `IntentResult`, `CapabilityDescriptor`, `LLMRequest`
   - `src/probos/runtime.py` — understand `create_pool()`, `_create_pools()`, `register_agent_type()`, `_collect_intent_descriptors()`, pool creation pattern with `llm_client=self.llm_client, runtime=self` kwargs
   - `src/probos/config.py` — understand `SystemConfig`, `PoolConfig`, `load_config()`
   - `src/probos/__main__.py` — understand boot sequence, config loading, `--config` and `--fresh` flags
   - `src/probos/agents/http_fetch.py` — understand `HttpFetchAgent`: `USER_AGENT`, `DEFAULT_TIMEOUT`, `_fetch_url()`. Bundled agents that fetch URLs will dispatch through the mesh via `self._runtime.intent_bus.broadcast()`, NOT by using httpx directly
   - `src/probos/cognitive/agent_designer.py` — understand `AGENT_DESIGN_PROMPT`, the dual template structure (pure LLM reasoning vs web-fetching `perceive()` override). Bundled agents follow the same CognitiveAgent pattern but are hand-written and curated
   - `config/system.yaml` — understand pool configuration, self_mod config, LLM tier config

---

## What To Build

### Part A: Distribution Infrastructure (AD-247)

**AD-247: `pip install probos`, `probos init`, `probos serve`.**

#### A1: PyPI packaging

The `pyproject.toml` already exists. Verify it has:
- `[project.scripts]` entry: `probos = "probos.__main__:main"` (or equivalent CLI entry point)
- All dependencies listed (pydantic, pyyaml, aiosqlite, httpx, rich, chromadb, etc.)
- `version = "0.1.0"` (already set)

If `[project.scripts]` doesn't exist, add it so `pip install probos` creates the `probos` CLI command. The entry point should call the existing `__main__.py` logic.

#### A2: `probos init` — config wizard

Add a `probos init` subcommand (via argparse in `__main__.py`) that:

1. Creates `~/.probos/` directory if it doesn't exist
2. Creates `~/.probos/config.yaml` with sensible defaults:
   - `llm_base_url` → prompts user for their LLM endpoint (default: `http://127.0.0.1:11434` for Ollama)
   - `llm_model` → prompts user for model name (default: `qwen3.5:35b`)
   - `llm_api_format` → auto-detects from URL (`ollama` for port 11434, `openai` otherwise)
   - Per-tier settings kept simple: fast=user's model, standard/deep=same or Copilot proxy if available
   - `self_mod.enabled: true` (enable self-mod by default)
   - `knowledge.enabled: true` with `repo_path: ~/.probos/knowledge`
3. Creates `~/.probos/data/` for ChromaDB and SQLite
4. Prints "ProbOS initialized. Run `probos serve` to start."

**Keep it simple.** No interactive menus, no curses UI. Just sequential prompts with defaults that the user can accept by pressing Enter. Use Rich for formatting.

#### A3: `probos serve` — daemon mode with API

Add a `probos serve` subcommand that:

1. Loads config from `~/.probos/config.yaml` (falls back to `config/system.yaml`)
2. Starts the ProbOS runtime (same as current `__main__.py` interactive mode)
3. Starts a FastAPI/uvicorn HTTP server alongside the runtime on `http://127.0.0.1:18900`:
   - `POST /api/chat` — accepts `{"message": "..."}`, calls `runtime.process_natural_language()`, returns `{"response": "...", "dag": {...}, "results": {...}}`
   - `GET /api/status` — returns `runtime.status()` as JSON
   - `GET /api/health` — returns `{"status": "ok", "agents": N, "health": 0.XX}`
   - `WebSocket /ws/events` — streams runtime events (for future HXI, Phase 24)
4. Falls back to interactive shell mode if `--interactive` flag is set (or no `serve` subcommand)
5. `Ctrl+C` triggers clean shutdown

**Dependencies:** Add `fastapi` and `uvicorn` to `pyproject.toml` dependencies.

**The WebSocket event stream (`/ws/events`):** This is a forward-looking hook for the HXI (Phase 24). For now, emit a simple JSON event on every `on_event` callback from the DAG executor: `{"type": "node_start"|"node_complete"|..., "data": {...}, "timestamp": float}`. Also emit agent lifecycle events from the runtime. The HXI will consume this stream in Phase 24 — get the plumbing right now.

**Run tests after this step: all 1454 existing tests must still pass.**

---

### Part B: Bundled Agent Suite (AD-248 through AD-252)

**Directory:** `src/probos/agents/bundled/` (new package)

**File:** `src/probos/agents/bundled/__init__.py` — re-exports all bundled agent classes

All bundled agents follow the same pattern:
1. Subclass `CognitiveAgent`
2. Set class-level `agent_type`, `instructions`, `intent_descriptors`, `_handled_intents`, `default_capabilities`
3. Override `perceive()` for agents that fetch external data (web search, weather, news, page reader)
4. Override `act()` for agents that need structured output parsing
5. Each agent handles 1-3 related intents

**Critical design constraint: Bundled agents dispatch sub-intents through the mesh.** An agent that needs web data broadcasts `http_fetch` through `self._runtime.intent_bus.broadcast()`, NOT by using httpx directly. This preserves governance (consensus, trust scoring) and keeps the mesh as the single coordination mechanism. The `_runtime` reference is passed via `kwargs` at pool creation time (same pattern as designed agents, AD-147).

**Error handling:** All agents must handle LLM unavailability gracefully. If `self._llm_client` is None, return `IntentResult(success=False, error="LLM not available")`. If the LLM returns empty or malformed output, return a useful error message, not a crash.

---

#### AD-248: Web + Content Agents (4 agents)

**File:** `src/probos/agents/bundled/web_agents.py`

**1. WebSearchAgent**
```python
agent_type = "web_search"
instructions = """You are a web search agent. When given a search query:
1. Formulate a DuckDuckGo search URL using urllib.parse.quote_plus()
2. Dispatch http_fetch through the mesh to fetch the search results page
3. Parse the HTML response to extract the top 5 results (title + snippet + URL)
4. Present the results clearly to the user

If the fetch fails, explain what went wrong. Never fabricate search results."""

intent_descriptors = [
    IntentDescriptor(name="web_search", params={"query": "search terms"}, 
                     description="Search the web and return summarized results",
                     requires_reflect=True),
]
```
- Override `perceive()`: constructs DuckDuckGo URL, broadcasts `http_fetch` via mesh, stores HTML in observation
- Override `act()`: parses HTML for result snippets (basic regex or string parsing — no bs4 dependency required initially)

**2. PageReaderAgent**
```python
agent_type = "page_reader"
instructions = """You are a page reader agent. When given a URL:
1. Dispatch http_fetch through the mesh to fetch the page content
2. Extract the main text content from the HTML (strip tags, scripts, styles)
3. Summarize the content concisely, focusing on the key information

If the page can't be fetched, explain what happened. Never invent content."""

intent_descriptors = [
    IntentDescriptor(name="read_page", params={"url": "<url>"}, 
                     description="Read and summarize a web page",
                     requires_reflect=True),
]
```
- Override `perceive()`: broadcasts `http_fetch` via mesh, stores body text in observation
- `decide()` sends extracted text + instructions to LLM for summarization

**3. WeatherAgent**
```python
agent_type = "weather"
instructions = """You are a weather agent. When asked about weather:
1. Dispatch http_fetch through the mesh to fetch weather data from wttr.in/{location}?format=j1
2. Parse the JSON response to extract current conditions, temperature, humidity, wind
3. Present the weather in a clear, friendly format

If the location is ambiguous, make a reasonable assumption and note it."""

intent_descriptors = [
    IntentDescriptor(name="get_weather", params={"location": "city name"}, 
                     description="Get current weather for a location",
                     requires_reflect=True),
]
```
- Override `perceive()`: constructs wttr.in URL with `format=j1` (JSON), broadcasts `http_fetch`, parses JSON
- `act()` formats weather data from parsed JSON

**4. NewsAgent**
```python
agent_type = "news"
instructions = """You are a news headlines agent. When asked for news:
1. Dispatch http_fetch through the mesh to fetch RSS feed from news sources
2. Parse the XML response to extract headline titles, descriptions, and links
3. Present the top headlines clearly

Default RSS feeds: use well-known feeds (e.g., Reuters, BBC, NPR).
If the user specifies a source, try to find its RSS feed URL."""

intent_descriptors = [
    IntentDescriptor(name="get_news", params={"source": "news source (optional)", "topic": "topic (optional)"}, 
                     description="Get latest news headlines",
                     requires_reflect=True),
]
```
- Override `perceive()`: selects RSS URL based on source param, broadcasts `http_fetch`, stores XML
- Override `act()`: parses XML for `<title>` and `<description>` elements (basic XML parsing with `xml.etree.ElementTree` from stdlib — no external deps)

---

#### AD-249: Language + Content Agents (2 agents)

**File:** `src/probos/agents/bundled/language_agents.py`

**5. TranslateAgent**
```python
agent_type = "translator"
instructions = """You are a translation agent. When given text and a target language:
1. Translate the text accurately into the target language
2. Preserve meaning, tone, and formatting
3. If the source language is ambiguous, detect it and note your detection

Support all major languages. For specialized terminology, prioritize accuracy."""

intent_descriptors = [
    IntentDescriptor(name="translate_text", params={"text": "text to translate", "target_language": "target language"}, 
                     description="Translate text to another language",
                     requires_reflect=True),
]
```
- Pure LLM agent — no `perceive()` override needed, the LLM does the translation

**6. SummarizerAgent**
```python
agent_type = "summarizer"
instructions = """You are a text summarization agent. When given text or content:
1. Identify the key points, arguments, and conclusions
2. Produce a concise summary that captures the essential information
3. Adjust summary length based on input length (shorter input = shorter summary)

If given a URL, note that the page_reader agent should be used first to fetch the content."""

intent_descriptors = [
    IntentDescriptor(name="summarize_text", params={"text": "text to summarize", "length": "short|medium|detailed (optional)"}, 
                     description="Summarize text or content concisely",
                     requires_reflect=True),
]
```
- Pure LLM agent

---

#### AD-250: Productivity Agents (2 agents)

**File:** `src/probos/agents/bundled/productivity_agents.py`

**7. CalculatorAgent**
```python
agent_type = "calculator"
instructions = """You are a calculator and unit conversion agent. When given a math problem:
1. Parse the mathematical expression or conversion request
2. Compute the result accurately
3. Show your work for complex calculations

Support: arithmetic, percentages, unit conversions (temperature, distance, weight, currency estimates), date math (days between dates, date arithmetic).

For currency: use approximate rates and note they may be outdated. Suggest web_search for current rates."""

intent_descriptors = [
    IntentDescriptor(name="calculate", params={"expression": "math expression or conversion"}, 
                     description="Calculate math, convert units, or do date math"),
]
```
- Pure LLM agent for most math. For precision, override `act()` to attempt Python `eval()` on safe numeric expressions before falling back to LLM. **Security:** only eval simple arithmetic expressions matching `^[0-9+\-*/().,%\s]+$` — reject anything else and fall through to LLM.

**8. TodoAgent**
```python
agent_type = "todo_manager"
instructions = """You are a todo list manager. You maintain a persistent todo list for the user.

Operations:
- add: Add a new todo item (with optional priority: high/medium/low and optional due date)
- list: Show all active todos, sorted by priority then due date
- complete: Mark a todo as done
- remove: Remove a todo
- clear: Clear all completed todos

The todo list is stored as a JSON file. Read/write it using the mesh's file I/O intents."""

intent_descriptors = [
    IntentDescriptor(name="manage_todo", params={"action": "add|list|complete|remove|clear", "item": "todo text", "priority": "high|medium|low", "due": "date"}, 
                     description="Manage todo list — add, list, complete, remove items"),
]
```
- Override `perceive()`: broadcasts `read_file` via mesh to load `~/.probos/todos.json`, stores current list in observation
- Override `act()`: after LLM decides what to do, broadcasts `write_file` via mesh to persist changes
- **File path:** `~/.probos/todos.json` (configurable). Uses existing `write_file` intent → consensus-gated, trust-scored

---

#### AD-251: Note + Schedule Agents (2 agents)

**File:** `src/probos/agents/bundled/organizer_agents.py`

**9. NoteTakerAgent**
```python
agent_type = "note_taker"
instructions = """You are a personal notes agent. You help the user save and retrieve notes.

Operations:
- save: Save a note with a title and optional tags
- search: Find notes matching a query (semantic search via the knowledge layer)
- list: Show recent notes
- read: Read a specific note by title

Notes are stored as individual files in ~/.probos/notes/ — one .md file per note.
Use the mesh's file I/O intents for persistence."""

intent_descriptors = [
    IntentDescriptor(name="manage_notes", params={"action": "save|search|list|read", "title": "note title", "content": "note content", "query": "search query"}, 
                     description="Save, search, and organize personal notes"),
]
```
- Override `perceive()`: for search action, queries `self._runtime._semantic_layer.search()` (or `episodic_memory.recall()`) for semantic note search. For read/list, broadcasts `read_file`/`list_directory` via mesh
- `act()`: for save, broadcasts `write_file` via mesh + indexes note via semantic layer

**10. SchedulerAgent**
```python
agent_type = "scheduler"
instructions = """You are a scheduling and reminder agent. You help the user set reminders and manage time.

Operations:
- remind: Set a reminder (stored with timestamp)
- list: Show upcoming reminders
- cancel: Cancel a reminder
- check: Check what's coming up today/this week

Reminders are stored in ~/.probos/reminders.json. For reminders that are due within the current session, use the system's event mechanism. For future reminders, persist to file and check at startup.

Note: ProbOS currently has no background timer — reminders are checked when the user interacts or at boot. Be transparent about this limitation."""

intent_descriptors = [
    IntentDescriptor(name="manage_schedule", params={"action": "remind|list|cancel|check", "text": "reminder text", "when": "datetime or relative time"}, 
                     description="Set reminders and manage schedule",
                     requires_reflect=True),
]
```
- Override `perceive()`: reads `~/.probos/reminders.json` via mesh file I/O
- `act()`: writes updates via mesh file I/O
- **Honest about limitations:** no background cron in Phase 22. Reminders are checked at boot and on user interaction. Future phases can add a background timer.

---

#### AD-252: Runtime Registration + Config

**Files:** `src/probos/runtime.py`, `config/system.yaml`

Register all bundled agents at boot:

1. **Import bundled agents** in `runtime.py`
2. **Create pools** in `_create_pools()` for each bundled agent:
   ```python
   # Bundled cognitive agents (Phase 22)
   bundled_agents = [
       ("web_search", "web_search", 2),
       ("page_reader", "page_reader", 2),
       ("weather", "weather", 2),
       ("news", "news", 2),
       ("translator", "translator", 2),
       ("summarizer", "summarizer", 2),
       ("calculator", "calculator", 2),
       ("todo_manager", "todo_manager", 2),
       ("note_taker", "note_taker", 2),
       ("scheduler", "scheduler", 2),
   ]
   for pool_name, agent_type, size in bundled_agents:
       ids = generate_pool_ids(agent_type, pool_name, size)
       await self.create_pool(pool_name, agent_type, target_size=size,
                              agent_ids=ids, llm_client=self.llm_client, runtime=self)
   ```

3. **Register agent types** with the spawner so pool recovery and scaling work
4. **Refresh decomposer descriptors** — bundled agent intents should appear in the decomposer's intent table automatically via the existing `_collect_intent_descriptors()` mechanism

5. **Config option:** Add `bundled_agents.enabled: true` to system config (default true). When false, no bundled agents are created — only core tool agents + self-mod.

6. **Pool count impact:** This adds 20 agents (10 types × 2 per pool) to the existing ~25. Total: ~45 agents. Verify this doesn't cause performance issues (it shouldn't — pools are lightweight).

**Run tests after this step: all 1454 must still pass. Add NO new tests yet.**

---

### Part C: Tests (AD-253)

**Files:** `tests/test_bundled_agents.py` (new), `tests/test_distribution.py` (new)

**AD-253: Comprehensive test suite for bundled agents and distribution.**

#### Agent unit tests (30 tests across 10 agents, ~3 per agent)

For EACH bundled agent, test:
1. Agent class has correct `agent_type`, `intent_descriptors`, `_handled_intents`
2. `handle_intent()` with valid params returns IntentResult with success=True (using MockLLMClient)
3. `handle_intent()` with missing/invalid params returns graceful error (not crash)

Agent-specific tests:
- **WebSearchAgent**: constructs DuckDuckGo URL correctly from query params
- **PageReaderAgent**: declines intent without URL param
- **WeatherAgent**: constructs wttr.in URL with location param
- **NewsAgent**: parses XML `<title>` elements from mock RSS XML
- **TranslateAgent**: passes text + target_language to LLM
- **SummarizerAgent**: passes text to LLM
- **CalculatorAgent**: safe eval for simple arithmetic, rejects unsafe expressions
- **TodoAgent**: reads/writes todo file via mesh dispatch
- **NoteTakerAgent**: saves note via mesh dispatch
- **SchedulerAgent**: reads/writes reminders file via mesh dispatch

#### Runtime integration tests (8 tests)

- All 10 bundled pool types created at boot when enabled
- Bundled agents have `llm_client` and `runtime` references set
- `_collect_intent_descriptors()` includes bundled agent intents
- Decomposer prompt includes bundled intents (web_search, get_weather, etc.)
- `bundled_agents.enabled: false` skips bundled pool creation
- Status includes bundled agent pools
- Total agent count is ~45 (core + bundled + utility)
- Bundled agents respond to NL queries via MockLLMClient patterns

#### Distribution tests (7 tests)

- `probos init` creates `~/.probos/` directory structure (using temp dir)
- `probos init` creates valid YAML config
- `probos serve` creates FastAPI app
- `/api/health` returns correct JSON
- `/api/status` returns runtime status
- `/api/chat` processes message and returns response
- WebSocket `/ws/events` accepts connection

**Total: ~45 tests → ~1499 total**

---

## What NOT To Build

- **No channel integration** — Discord/Slack/WhatsApp are Phase 23
- **No HXI frontend** — the WebSocket event stream is a hook for Phase 24, not a UI
- **No inter-agent deliberation** — agents execute independently, Phase 25
- **No new architectural features** — this phase is breadth (agents + distribution), not depth
- **No complex CLI framework** — argparse is sufficient. No click, no typer
- **No authentication on the API** — `probos serve` binds to localhost only. Auth comes with remote access / channels
- **No agent-to-agent communication** — bundled agents dispatch sub-intents through the mesh, they don't talk to each other directly
- **No background timer for reminders** — scheduler stores reminders, checks at boot/interaction. Cron comes later
- **No BeautifulSoup dependency** — parse HTML with regex/string methods or stdlib xml.etree. Keep dependencies minimal
- **No changes to existing core agents** — FileReaderAgent, ShellCommandAgent, etc. are unchanged
- **No changes to self-mod pipeline** — capability gap → design → validate → deploy still works for intents not covered by bundled agents

---

## QA Discipline (CRITICAL for Phase 22)

This phase creates more files than any previous phase. QA rigor is non-negotiable:

1. **Test gate after EVERY step.** Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` after each AD. All 1454 existing tests must continue passing. Report test count.

2. **Each bundled agent must have at least 3 tests.** No untested agents. No "I'll add tests later."

3. **MockLLMClient patterns.** Add patterns for ALL bundled agent intents so tests are deterministic. Each bundled intent needs a MockLLMClient regex pattern that returns a plausible DAG routing to the correct agent.

4. **No scope creep.** If a bundled agent's implementation gets complex, simplify. A minimal working agent is better than a half-finished sophisticated one. The CognitiveAgent pattern + LLM instructions handle most of the complexity — the agent code should be thin.

5. **No breaking existing tests.** Adding 20 agents to the runtime changes the agent count and pool count. Update any tests that assert specific counts (check `test_experience.py`, `test_runtime_*.py` for hardcoded agent/pool counts).

---

## Implementation Order

1. **AD-247: Distribution** (`__main__.py` + `pyproject.toml` + new `api.py` module) → run tests
2. **AD-248: Web + Content Agents** (4 agents in `bundled/web_agents.py`) → run tests
3. **AD-249: Language + Content Agents** (2 agents in `bundled/language_agents.py`) → run tests
4. **AD-250: Productivity Agents** (2 agents in `bundled/productivity_agents.py`) → run tests
5. **AD-251: Note + Schedule Agents** (2 agents in `bundled/organizer_agents.py`) → run tests
6. **AD-252: Runtime Registration** (runtime.py + config changes) → run tests
7. **AD-253: Tests** (new test files) → run tests, verify all pass

**After each step, run the full test suite: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`**

---

## PROGRESS.md Update

After all tests pass, update PROGRESS.md:

1. **Line 2** — Update status line: `Phase 22 — Bundled Agent Suite + Distribution (XXXX/XXXX tests + 11 skipped)`
2. **What's Been Built section** — Add distribution infrastructure (API server, init wizard, serve command) and bundled agents table under a new "Bundled Agents" subsection
3. **What's Working section** — Add Phase 22 test summary
4. **Architectural Decisions** — Add entries for AD-247 through AD-253
5. **Active Roadmap** — Mark Phase 22 as complete, update current phase to 23

**AD numbering reminder: Current highest is AD-246. This phase uses AD-247 through AD-253. Verify before committing.**
