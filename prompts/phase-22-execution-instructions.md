# Phase 22 — Execution Instructions

## How To Use This Document

1. Read `prompts/phase-22-bundled-agents-distribution.md` first (the full spec)
2. This document repeats the highest-risk constraints and provides execution-order guidance
3. Follow the steps in order. Run tests after EVERY step

## Critical Constraints (stated redundantly)

### AD Numbering — HARD RULE
- **Current highest: AD-246** (Phase 21)
- Phase 22 uses: AD-247, AD-248, AD-249, AD-250, AD-251, AD-252, AD-253
- VERIFY by reading PROGRESS.md before assigning any AD number
- If AD-246 is NOT the latest, shift ALL AD numbers up accordingly

### Test Gate — HARD RULE
- Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` after EVERY step
- All 1454 existing tests must continue passing at every step
- Do NOT proceed to the next step if any test fails
- Report test count after each step
- **This phase adds ~45 new tests. Target: ~1499 total**

### Scope — DO NOT BUILD
- No channel integration (Discord/Slack/WhatsApp — Phase 23)
- No HXI frontend — only the WebSocket event stream plumbing
- No inter-agent deliberation
- No new deep architecture features
- No authentication on API (localhost-only)
- No complex CLI framework (argparse only)
- No BeautifulSoup dependency — use stdlib xml.etree + regex
- No background timer/cron for reminders
- No changes to existing core agents or self-mod pipeline
- No agent-to-agent direct communication — sub-intents go through the mesh

### Bundled Agent Pattern — MUST FOLLOW
- All bundled agents subclass `CognitiveAgent`
- All bundled agents live in `src/probos/agents/bundled/`
- All web-facing agents override `perceive()` and dispatch `http_fetch` through `self._runtime.intent_bus.broadcast()` — NEVER use httpx directly
- All file-persisting agents (todo, notes, scheduler) dispatch `read_file`/`write_file` through the mesh — NEVER use Path.write_text directly
- This preserves governance (consensus, trust) across the entire stack

### Existing Test Counts — WATCH FOR REGRESSIONS
- Adding 20 agents to the runtime changes pool/agent counts
- Tests in `test_experience.py`, `test_runtime_*.py` may assert specific agent or pool counts
- If tests fail after AD-252 (runtime registration), the cause is likely a count assertion that needs updating
- Update the count, don't remove the test

### QA Discipline — NON-NEGOTIABLE
- Each bundled agent MUST have at least 3 tests
- MockLLMClient MUST have patterns for all bundled intent names
- No untested agents. No untested API endpoints
- If an agent implementation gets complex, simplify — a working thin agent beats a broken sophisticated one

## Execution Sequence

### Step 1: Distribution infrastructure (AD-247)
- **Edit** `pyproject.toml` — add `[project.scripts]` entry, add fastapi + uvicorn deps
- **Edit** `src/probos/__main__.py` — add `init` and `serve` subcommands via argparse
- **Create** `src/probos/api.py` — FastAPI app with `/api/chat`, `/api/status`, `/api/health`, WebSocket `/ws/events`
- Run tests → expect 1454 pass

### Step 2: Web + Content Agents (AD-248)
- **Create** `src/probos/agents/bundled/__init__.py`
- **Create** `src/probos/agents/bundled/web_agents.py` — WebSearchAgent, PageReaderAgent, WeatherAgent, NewsAgent
- Run tests → expect 1454 pass (agents created but not registered in runtime yet)

### Step 3: Language + Content Agents (AD-249)
- **Create** `src/probos/agents/bundled/language_agents.py` — TranslateAgent, SummarizerAgent
- Run tests → expect 1454 pass

### Step 4: Productivity Agents (AD-250)
- **Create** `src/probos/agents/bundled/productivity_agents.py` — CalculatorAgent, TodoAgent
- Run tests → expect 1454 pass

### Step 5: Organizer Agents (AD-251)
- **Create** `src/probos/agents/bundled/organizer_agents.py` — NoteTakerAgent, SchedulerAgent
- Run tests → expect 1454 pass

### Step 6: Runtime registration (AD-252)
- **Edit** `src/probos/runtime.py` — register all 10 bundled agent types, create pools, refresh descriptors
- **Edit** `src/probos/cognitive/llm_client.py` — add MockLLMClient patterns for all 10 bundled intents
- **Edit** `config/system.yaml` — add `bundled_agents.enabled: true`
- **Edit** `src/probos/config.py` — add `BundledAgentsConfig` if needed
- Run tests → expect 1454 pass (watch for count assertion regressions — fix them)

### Step 7: Tests (AD-253)
- **Create** `tests/test_bundled_agents.py` — ~30 agent unit tests
- **Create** `tests/test_distribution.py` — ~8 runtime integration + ~7 distribution tests
- Run tests → expect ~1499 pass

### Step 8: PROGRESS.md update
- Update status line
- Add bundled agents + distribution to "What's Been Built"
- Add Phase 22 test summary to "What's Working"
- Add AD-247 through AD-253 to "Architectural Decisions"
- Update Active Roadmap — mark Phase 22 complete, set current phase to 23

## Key Design Decisions Summary

| AD | What |
|----|------|
| AD-247 | Distribution: `[project.scripts]` for `pip install`, `probos init` config wizard, `probos serve` with FastAPI/uvicorn HTTP + WebSocket server |
| AD-248 | Web + Content agents: WebSearchAgent (DuckDuckGo via mesh), PageReaderAgent (URL → summarize), WeatherAgent (wttr.in JSON), NewsAgent (RSS XML parsing). All fetch via `intent_bus.broadcast()` |
| AD-249 | Language agents: TranslateAgent (pure LLM), SummarizerAgent (pure LLM) |
| AD-250 | Productivity agents: CalculatorAgent (safe eval + LLM fallback), TodoAgent (file-backed via mesh I/O) |
| AD-251 | Organizer agents: NoteTakerAgent (file-backed + semantic search), SchedulerAgent (file-backed reminders, no background timer) |
| AD-252 | Runtime registration: 10 new pools (2 agents each), spawner templates, descriptor refresh, `bundled_agents.enabled` config |
| AD-253 | ~45 tests: agent unit tests (30), runtime integration (8), distribution (7) |

## Highest-Risk Items

1. **Agent count regressions.** Existing tests may assert specific agent/pool counts. Adding 10 new pools (20 agents) will break these. Find and update them in Step 6. Common locations: `test_experience.py`, `test_expansion_agents.py`, `test_runtime_*.py`.

2. **Mesh dispatch in perceive().** Agents that override `perceive()` to fetch data via the mesh need access to `self._runtime.intent_bus`. This requires `runtime=self` in pool kwargs. Verify the reference is set before `perceive()` is called — the `handle_intent()` lifecycle calls `perceive()` first.

3. **MockLLMClient pattern conflicts.** Adding 10 new intent patterns must not shadow existing patterns. New patterns go at the END of the pattern list (lower priority). Verify each new pattern regex doesn't accidentally match existing prompts.

4. **FastAPI + asyncio event loop.** ProbOS uses `asyncio.run()` with `WindowsSelectorEventLoopPolicy` on Windows. uvicorn creates its own event loop. The `serve` command needs to run both the ProbOS runtime and uvicorn in the same loop. Use `uvicorn.Config` + `uvicorn.Server` with `server.serve()` as a coroutine alongside the runtime's `start()`.

5. **XML parsing security.** NewsAgent parses RSS XML. Use `xml.etree.ElementTree.fromstring()` with `defusedxml` if available, or at minimum don't pass untrusted XML to `eval()`. The RSS content comes through the mesh's `http_fetch` (which already has body size caps), so the attack surface is bounded.

## Verification Checklist

After completion, verify:
- [ ] `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` — all tests pass
- [ ] `pip install -e .` works and creates `probos` CLI command
- [ ] `probos init` creates `~/.probos/config.yaml` (test with temp dir)
- [ ] `probos serve` starts HTTP server on port 18900
- [ ] `GET /api/health` returns `{"status": "ok"}`
- [ ] `POST /api/chat` with `{"message": "hello"}` returns a response
- [ ] All 10 bundled agent intents appear in decomposer's intent table
- [ ] MockLLMClient has patterns for all 10 bundled intents
- [ ] Each bundled agent has ≥ 3 tests
- [ ] `bundled_agents.enabled: false` prevents bundled pool creation
- [ ] All existing shell commands still work
- [ ] PROGRESS.md updated with correct AD numbers and test count
