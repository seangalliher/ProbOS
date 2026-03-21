# ProbOS — Architectural Decisions: Era II — Emergence (Phases 10–21)

Archived decisions from the Emergence era. AD-109 through AD-246.

For current decisions, see [DECISIONS.md](DECISIONS.md).

---

### AD-109: Static analysis over runtime sandboxing for security

Generated agent code is validated statically via AST analysis (CodeValidator) rather than relying on runtime sandboxing (seccomp, containers). The CodeValidator checks: (1) syntax validity, (2) import whitelist, (3) forbidden pattern regex scan, (4) schema conformance (BaseAgent subclass, intent_descriptors, handle_intent), (5) module-level side effect detection. The SandboxRunner verifies functional correctness (does the agent handle a synthetic intent and return IntentResult?), not security. This keeps the test suite fast and portable (no Docker/seccomp dependency) while the static analysis catches the most dangerous patterns (subprocess, eval, exec, socket, ctypes, __import__, file writes).

### AD-110: Probationary trust for self-created agents

Self-created agents start with a pessimistic Beta prior: α=1, β=3 → E[trust] = 0.25. This means consensus weights their votes at 25% of an established agent's weight. The prior converges toward the system's default (α=2, β=2 → E[trust] = 0.5) after ~5 successful operations. This implements "trust but verify" — new agents participate immediately but cannot dominate consensus until they've proven reliable. The `TrustNetwork.create_with_prior()` method sets the custom prior; it's a no-op if the agent already has a record (prevents overwriting earned trust).

### AD-111: MockLLMClient agent design pattern

The MockLLMClient detects agent design requests by matching "UNHANDLED INTENT:" and "Subclass BaseAgent" in the prompt. It generates minimal but valid agent source code that conforms to the BaseAgent contract: correct imports, class with intent_descriptors/agent_type/_handled_intents class attributes, perceive/decide/act/report lifecycle methods, handle_intent dispatcher. This allows the full self-mod pipeline to be tested end-to-end without a real LLM. The intent extraction pattern similarly detects "no existing agent can handle it" + "intent_name_snake_case" and returns valid JSON.

### AD-112: Unhandled intent detection via decomposer fallback

When `process_natural_language()` produces an empty TaskDAG (no nodes and no `response` field), and self_mod is enabled, the runtime calls `_extract_unhandled_intent()` to ask the LLM what kind of agent is needed. If extraction succeeds, the pipeline designs/validates/sandboxes/registers the new agent, then retries decomposition. This retry means the user's original request may succeed on the first attempt, transparently. The `response` field check prevents self-mod from triggering on conversational LLM replies (where no intent execution is needed).

### AD-113: CodeValidator schema conformance checks

The CodeValidator checks that generated code structurally matches the agent contract by walking the AST: (1) exactly one class subclassing BaseAgent, (2) class-level `intent_descriptors` assignment, (3) class-level `agent_type` assignment, (4) class-level `_handled_intents` assignment, (5) `handle_intent` method (async or sync). This catches structural errors before sandbox execution, providing faster feedback and clearer error messages than runtime ImportError/AttributeError.

### AD-114: BehavioralMonitor as post-deployment guardrail

Unlike red team agents (which verify output correctness during consensus), the BehavioralMonitor tracks operational patterns of self-created agents over time: execution duration, failure rate, trust trajectory. Alerts are informational — visible via `/designed` — not blocking. The `should_recommend_removal()` method recommends removal after 10+ executions with >50% failure rate, or after 3 consecutive trust declines. This separates "is this output correct?" (red team) from "is this agent reliable over time?" (behavioral monitor).

### AD-115: LLM client injection into designed agents

Designed agents that need LLM intelligence (e.g., translation, summarization) can't function without access to the LLM client. The `AgentDesigner` prompt now includes an LLM ACCESS section with `self._llm_client = kwargs.get("llm_client")` in `__init__`. `SandboxRunner` forwards the LLM client during sandbox testing. `ProbOSRuntime._create_designed_pool()` passes `llm_client=self.llm_client` in the pool kwargs. This means designed agents can make LLM calls just like the cognitive layer, enabling intelligence-based capabilities beyond simple data retrieval.

### AD-116: subprocess.Popen for SelectorEventLoop compatibility

On Windows, `WindowsSelectorEventLoopPolicy` is required for pyzmq (AD-108), but `SelectorEventLoop` does not support `asyncio.create_subprocess_shell/exec`. Replaced async subprocess calls in `ShellCommandAgent` with synchronous `subprocess.Popen` run via `loop.run_in_executor(None, _run_sync, ...)`. The `_run_sync()` function blocks in a thread pool, preserving async compatibility while working on all Windows event loop policies. Uses PowerShell on Windows (`["powershell", "-Command", cmd]`), `/bin/sh -c` elsewhere.

### AD-117: PowerShell wrapper stripping via _PS_WRAPPER_RE

LLM-generated commands often arrive wrapped in redundant `powershell -Command "..."` shells. Since `ShellCommandAgent` already invokes PowerShell on Windows, this creates a double-nesting problem (`powershell -Command "powershell -Command '...'"`) that changes quoting semantics and breaks commands. `_strip_ps_wrapper()` uses `_PS_WRAPPER_RE` regex to detect and unwrap these patterns before execution, extracting the inner command. The regex handles both quoted (`"..."`, `'...'`) and unquoted forms.

### AD-118: Escalation re-execution after user approval

When Tier 3 user consultation approves an intent, the escalation manager now re-executes the original intent through the mesh rather than just returning a stale result. The re-execution uses the same pool rotation and submit function as Tier 1 retries. If the user rejects, the node is marked as failed with a descriptive message. On consensus-policy rejection (Tier 2 LLM rejects), the original agent results are preserved and returned instead of being discarded.

### AD-119: Existing-agent routing before self-mod

Before triggering the self-modification pipeline, the renderer checks whether the LLM-extracted intent name matches an already-registered intent. If a match is found, the request is re-decomposed using the existing agent rather than creating a duplicate. This prevents the common case where the LLM extracts `run_command` as the "unhandled intent" even though `ShellCommandAgent` already handles it, avoiding unnecessary agent proliferation.

### AD-120: General-purpose intent preference in self-mod

`_extract_unhandled_intent()` includes explicit guidance: "Prefer general-purpose intents (translate_text, convert_data) over narrow ones (translate_hello_to_japanese)." This nudges the LLM toward creating reusable agents rather than single-use ones. The intent extraction prompt also avoids creating intents that overlap with existing capabilities by listing all registered intent names.

### AD-121: Reflect prompt rewrite with node status prefix

The `REFLECT_PROMPT` was rewritten to produce synthesized answers rather than summaries. Each node's results in the reflect payload are now prefixed with `[status]` (e.g., `[completed]`, `[failed]`) so the LLM can distinguish successful from failed operations. The `_summarize_node_result()` method deduplicates identical `output` and `result` fields (common when an agent returns the same data in both) to reduce payload bloat.

### AD-122: Force reflect=true for designed agent intents

When a designed agent handles an intent, its descriptor is created with `requires_reflect=True`. The renderer also forces `dag.reflect = True` on DAGs produced by designed agents. This ensures all designed agent responses go through LLM synthesis, compensating for the fact that designed agents may produce raw/structured output that benefits from a natural-language reflection step.

### AD-123: Self-mod UX with explicit user approval

Self-modification now shows the user what intent was detected, what the proposed agent will do, and asks for explicit approval before creating the agent. The renderer displays the intent name, purpose, and "Create this agent? (y/N)" prompt. After approval, the agent is designed, validated, sandboxed, and registered with the user's original request retried immediately. The shell wires `_user_approval_callback` for this prompt.

### AD-124: Anti-echo rules for run_command

The prompt builder generates explicit rules prohibiting `echo`, `Write-Host`, `Write-Output`, and similar commands from being used to fabricate answers. Without this, the LLM would often decompose "what time is it?" into `run_command: echo "The time is 3pm"` — faking the answer rather than running an actual time-querying command. The anti-echo rules force the LLM to use real system commands for data retrieval.

### AD-125: Log suppression during interactive shell

`__main__.py` now raises the logging level for noisy loggers (root, probos, asyncio, etc.) during interactive shell operation. Without this, INFO-level log messages from subsystems (dream scheduler, Hebbian router, gossip protocol) would print over the interactive prompt, making the shell unusable. Log level is restored to the configured level when the shell exits.

### AD-126: Capability-gap detection via regex heuristic

`is_capability_gap()` in `decomposer.py` uses a compiled regex (`_CAPABILITY_GAP_RE`) to detect LLM responses that indicate a missing capability rather than a genuine conversational reply. Phrases like "I don't have", "no capability", "not equipped", "unable to", "beyond my current capabilities" trigger self-modification. This fixes a regression where capability-gap responses blocked self-mod because the `response` field was non-empty (AD-112 originally gated self-mod on empty `response`). The regex has 16 positive and 8 negative test cases to prevent false positives on normal responses.

### AD-127: Strategy proposals with reversibility preference

`StrategyRecommender` analyzes unhandled intents and proposes strategies with confidence scores. Two strategies: `new_agent` (always available, creates dedicated agent with probationary trust) and `add_skill` (adds modular handler to existing SkillBasedAgent — more reversible, preferred when keyword overlap exists). The `add_skill` strategy gets a `_REVERSIBILITY_BONUS = 0.1` boost reflecting the Reversibility Preference axiom — skills can be removed without destroying a pool. The renderer displays a numbered strategy menu instead of a simple y/n prompt, letting users choose their preferred approach.

### AD-128: Skill type and SkillBasedAgent architecture

The `Skill` dataclass (in `types.py`) encapsulates a modular intent handler: name, `IntentDescriptor`, source code, compiled async handler callable, creation timestamp, and origin. `SkillBasedAgent` is a general-purpose agent that dispatches intents to attached `Skill` objects. Critical implementation: `add_skill()` updates BOTH instance-level AND class-level `_handled_intents` and `intent_descriptors`, ensuring that `_collect_intent_descriptors()` (which reads class-level descriptors from `spawner._templates`) discovers new skills without requiring a template re-registration. `SkillDesigner` generates async handler functions (not full agent classes) via LLM, and `SkillValidator` performs the same static analysis checks as `CodeValidator` but validates function-level schema (async def handle_{name}) instead of class-level schema.

### AD-129: Skills pool conditional spawning

The `skills` ResourcePool (2 SkillBasedAgents with `llm_client` injection) is only created when `config.self_mod.enabled=True`. This prevents unnecessary agent spawning in systems without self-modification capability. The pipeline's `handle_add_skill()` method orchestrates: design → validate → compile (importlib) → create Skill → `add_skill_fn` callback → record with `strategy="skill"`. The `add_skill_fn` iterates `pool.healthy_agents` to inject the skill into all pool members and refreshes decomposer descriptors.

### AD-130: Web research with domain whitelist security

`ResearchPhase` adds optional pre-design documentation research. Security model: (1) Search queries generated by LLM, (2) URLs constructed via `urllib.parse.urlencode()` — never raw string concatenation — for whitelisted domains only (`docs.python.org`, `pypi.org`, `developer.mozilla.org`, `learn.microsoft.com`), (3) Page fetching goes through the mesh's `http_fetch` intent with consensus, (4) Fetched content truncated to `research_max_content_per_page` chars before LLM processing, (5) Research output is context for code generation only — never executed directly — all generated code still passes through `CodeValidator` + `SandboxRunner`. Config fields: `research_enabled`, `research_domain_whitelist`, `research_max_pages`, `research_max_content_per_page`.

### AD-131: Research integration in self-modification pipeline

Research context is injected into both `AGENT_DESIGN_PROMPT` and `SKILL_DESIGN_PROMPT` via a `{research_context}` template variable. When `config.self_mod.research_enabled=True` and a `ResearchPhase` instance is available, `handle_unhandled_intent()` runs research before the design step. Research failures are caught and logged — they never block design (fallback: "No research available."). The design prompt instructs: "Use the above research to inform your implementation. If research context says 'No research available.', rely on your training knowledge." This makes research a best-effort enhancement, not a required dependency.

### AD-132: Per-tier endpoint config with shared fallback

Each LLM tier (fast/standard/deep) can override `base_url`, `api_key`, and `timeout` independently. When not specified (value is `None`), each falls back to the shared `llm_base_url`, `llm_api_key`, and `llm_timeout_seconds`. This is fully backward compatible — existing configs with only shared values produce identical behavior. The `tier_config(tier)` helper method on `CognitiveConfig` returns a resolved dict `{"base_url", "api_key", "model", "timeout"}` for any tier. The user's setup: fast=`qwen3.5:35b` at Ollama `localhost:11434` (no auth), standard=`claude-sonnet-4.6` at Copilot proxy `localhost:8080`, deep=`claude-opus-4.6` at Copilot proxy.

### AD-133: httpx client deduplication by base_url

`OpenAICompatibleClient` creates one `httpx.AsyncClient` per unique `base_url`, not per tier. If standard and deep share the same endpoint (as in the user's setup), they share the same connection pool. This avoids duplicate connection pools and redundant connectivity checks. The deduplication key is the URL string. Each client gets its own `Authorization` header at construction time — if `api_key` is empty, the header is omitted entirely (handles Ollama's no-auth model cleanly without a special flag — AD-135).

### AD-134: Per-tier connectivity at boot

`check_connectivity()` returns `dict[str, bool]` instead of a single `bool`. Each unique endpoint is checked independently — shared endpoints are checked once and the result reused for all tiers pointing to that URL. Boot sequence: if ALL tiers unreachable → fall back to `MockLLMClient`; if SOME tiers unreachable → warn but continue with `OpenAICompatibleClient` (partial connectivity). The `_check_endpoint()` method sends a minimal completion request with a 5-second timeout.

### AD-135: Empty api_key means no Authorization header

When `api_key` is empty string, the `Authorization` header is omitted from the `httpx.AsyncClient` headers entirely. This handles Ollama (no auth) and other local endpoints cleanly without a separate "no auth" flag. The `/model` command shows per-tier endpoint info with shared-endpoint notes when multiple tiers use the same URL (e.g., "shared with standard"). The `/tier` command now displays the endpoint URL on switch.

### AD-136: Response cache keyed by (tier, prompt_hash)

The response cache is shared across tiers but qualified by tier name: `f"{tier}:{hash(prompt)}"`. A cached response from the fast tier won't be served for a standard-tier request, since different models produce different outputs. Previously the cache was keyed by `(model, prompt_hash)` — the tier-based key is semantically equivalent but more explicit about the routing intent.

### AD-137: Configurable default LLM tier

All cognitive components (decomposer, escalation, agent designer, skill designer) previously hardcoded `tier="standard"` in their `LLMRequest` construction. This meant requests always went to the Copilot proxy regardless of what `default_tier` was set to on the LLM client. Fixed by: (1) adding `default_llm_tier: str = "fast"` to `CognitiveConfig`, (2) having `OpenAICompatibleClient` read `default_tier` from `config.default_llm_tier` when a config is provided, (3) changing all hardcoded `tier="standard"` to `tier=None` — the LLM client resolves `None` to `self.default_tier`. Intentional `tier="fast"` usages in `ResearchPhase` and `runtime._extract_unhandled_intent()` are left as-is since they are explicitly choosing the lightweight tier for specific tasks. The `/tier` command still overrides the default at runtime.

### AD-138: Debug panel shows tier and model

The debug panel (enabled with `/debug on`) previously showed `"DEBUG: Raw LLM Response"` with no indication of which tier or model was used. Added `last_tier` and `last_model` tracking on the decomposer (populated from `LLMResponse.tier` and `.model` after each LLM call). The debug panel title now reads `"DEBUG: Raw LLM Response  fast / qwen3.5:35b"`. Also fixed `LLMResponse.tier` in `_call_api()` to store the resolved tier (`request.tier or self.default_tier`) instead of the raw request tier (which could be `None`).

### AD-139 – AD-141: Self-mod routing fixes

Prompt rules to route capability-gap requests through self-mod instead of answering inline (AD-139). Structured `capability_gap` boolean field in decomposer output (AD-140). `<think>` tag stripping from qwen LLM responses (AD-141). Unicode apostrophe regex fix and JSON code-fence stripping in `_extract_unhandled_intent`.

### AD-142: Self-mod pipeline end-to-end fix

Three issues prevented the self-mod pipeline from completing:

1. **Token budget in `_extract_unhandled_intent`:** `max_tokens=256` was too small — qwen3.5 used all tokens in the `reasoning` response field (separate from `content`), content was empty, `finish_reason: 'length'`. Bumped to `max_tokens=2048` with `/no_think` prefix.

2. **LLM client reasoning fallback:** When qwen returns `content=''` but has a `reasoning` field in the OpenAI-compatible response, the client now falls back to the reasoning content. Prevents silent empty responses from reasoning-heavy models.

3. **Agent/skill designer tier routing:** `tier=None` resolved to "fast" (qwen3.5:35b), which timed out generating agent code at 30s. Changed agent_designer and skill_designer to `tier="standard"` (Claude) — faster, no reasoning overhead, better code quality. Added `max_tokens=4096` for complete agent output. Added `<think>` tag stripping on designer output.

Also bumped `llm_timeout_fast` from 15→30s in system.yaml.

Verified end-to-end: "translate hello into japanese" → capability_gap → extract intent → design TranslateTextAgent (Claude) → validate → sandbox → register → re-decompose → execute → こんにちは. 754/754 tests passing.

---

### AD-143: Live LLM integration tests

Added `tests/test_live_llm.py` with 11 tests across 5 classes that exercise the full stack against real LLM backends (Ollama + Copilot proxy). Tests are marked `@pytest.mark.live_llm` and skipped by default — run explicitly with `pytest -m live_llm`.

**Test classes:**
- `TestRawLLMResponse` — fast/standard tier connectivity and content
- `TestDecomposerLive` — read_file decomposition, capability_gap detection, conversational filtering, multi-intent DAGs, think-tag survival
- `TestExtractUnhandledIntentLive` — translation/summarization intent extraction
- `TestAgentDesignerLive` — agent code generation + validation
- `TestFullPipelineLive` — end-to-end self-mod: NL input → gap detection → design → execute

**Infrastructure:**
- `conftest.py`: `pytest_collection_modifyitems` hook auto-skips `live_llm` tests unless `-m live_llm` is passed
- `pyproject.toml`: registered `live_llm` marker in `[tool.pytest.ini_options]`
- Connectivity-based skip decorators (`skip_no_ollama`, `skip_no_proxy`) for graceful degradation when backends are down

754/754 tests passing, 11 live_llm tests skipped by default.

---

### AD-144: Fast→standard tier-fallback for intent extraction

Fixed `test_extract_summarize_intent` live LLM test failure. Root cause: qwen puts all tokens into the `reasoning` field (not `content`) for "summarize" prompts when thinking mode is active — the `/no_think` directive and Ollama API `think: false` option are unreliable via OpenAI-compatible endpoint.

**Fix:** `_extract_unhandled_intent()` in `runtime.py` now cascades fast→standard tier on parse failure: if fast tier returns unparseable JSON, retries on standard tier (Claude) before giving up.

754/754 tests + 11/11 live LLM tests passing.

---

### AD-145: Native Ollama API format + dynamic capability-gap examples

Two-part fix that eliminates thinking-mode interference for the fast tier (qwen via Ollama) and resolves a prompt conflict that broke the self-mod pipeline.

**Part 1 — Per-tier API format (`config.py`, `llm_client.py`, `system.yaml`):**
- Added `llm_api_format_fast/standard/deep` fields to `CognitiveConfig` — values: `"ollama"` or `"openai"` (default)
- `tier_config()` returns `api_format` per tier
- Refactored `OpenAICompatibleClient` with dual API path: `_call_openai()` (existing chat/completions) and `_call_ollama_native()` (posts to `/api/chat` with `stream: False, think: False`)
- Client dedup key changed from `url` to `url|api_format` to support same-host setups
- `system.yaml` fast tier updated: `llm_base_url_fast: "http://127.0.0.1:11434"` + `llm_api_format_fast: "ollama"`
- 25+ regression tests across 8 test classes in `test_llm_client.py`

**Part 2 — Dynamic capability-gap examples (`prompt_builder.py`):**
- Hardcoded examples showed `"translate 'hello world' to French" → capability_gap: true` unconditionally, even when `translate_text` was in the intents table (added by self-mod)
- With thinking disabled (native Ollama API), qwen follows examples literally instead of reasoning against the intents table
- Fix: capability-gap examples are now conditionally included — suppressed when a matching intent exists in the descriptors list
- `_GAP_EXAMPLES` list with keyword matching, `_build_examples()` method filters based on registered intent names
- 6 new tests in `TestCapabilityGapExamples` class in `test_prompt_builder.py`

**Result:** `test_extract_summarize_intent` passes (was the AD-144 driver — native API eliminates thinking overhead entirely). `test_self_mod_creates_and_executes_agent` passes (dynamic examples prevent prompt conflict after self-mod adds translate_text).

784/784 tests + 11/11 live LLM tests passing.

### AD-146: Agent designer mesh access for external data tasks

Designed agents were answering factual/knowledge questions from LLM training data instead of searching the web. Root cause: the `AGENT_DESIGN_PROMPT` only showed `self._llm_client` for "intelligence tasks" and never explained how to dispatch sub-intents through the mesh to reach `HttpFetchAgent`.

**Agent designer prompt (`agent_designer.py`):**
- Split `LLM ACCESS` section into two: `LLM ACCESS (for inference)` and `MESH ACCESS (for external data)`
- `MESH ACCESS` section shows `self._runtime.intent_bus.broadcast()` pattern with `http_fetch` example, then optional LLM synthesis of fetched content
- Updated RULES: separated INFERENCE tasks (→ `self._llm_client`) from EXTERNAL DATA tasks (→ mesh → http_fetch → optional LLM synthesis)
- Added rule: "NEVER use `self._llm_client` alone to answer factual/knowledge questions — it has no internet access and will hallucinate"

**Decomposer prompt (`prompt_builder.py`):**
- Added knowledge-lookup to `_GAP_EXAMPLES`: `("who is Alan Turing?", ..., "lookup")` — suppressed when a `lookup*` intent exists
- Updated `_build_rules()`: both the general fallback rule and the intelligence-task rule now explicitly mention knowledge/factual questions as capability gaps, with `capability_gap: true` in the response format and a warning against answering from training data

**Tests (`test_prompt_builder.py`):**
- `test_lookup_gap_present_without_matching_intent` — knowledge-lookup gap example appears by default
- `test_lookup_gap_suppressed_when_lookup_intent_exists` — suppressed when `lookup_info` intent registered
- `test_all_gaps_suppressed_when_all_intents_exist` — all 3 gap examples suppressed together

787/787 tests + 8/8 live LLM tests passing (3 skipped — Copilot proxy not running).

### AD-147: Runtime injection for designed agent pools

Designed agents had `self._runtime = None` at runtime because `_create_designed_pool()` passed `llm_client=self.llm_client` but not `runtime=self`. Without runtime, the agent's mesh dispatch (`self._runtime.intent_bus.broadcast()`) hit the sandbox fallback path and returned placeholder results instead of fetching from the web.

**Fix (`runtime.py`):**
- `_create_designed_pool()` now passes `runtime=self` alongside `llm_client=self.llm_client`
- Matches the pattern used by the introspection pool: `create_pool(..., runtime=self)`

787/787 tests passing.

### AD-148: HttpFetchAgent User-Agent header + DuckDuckGo search strategy

Designed agents dispatching `http_fetch` sub-intents got 403 responses from Wikipedia and other sites because httpx's default User-Agent is blocked. Also, the agent designer prompt only showed a Wikipedia API example, which doesn't work for general person/topic lookups.

**HttpFetchAgent (`http_fetch.py`):**
- Added `USER_AGENT = "ProbOS/0.1.0 (https://github.com/seangalliher/ProbOS)"` constant
- `_fetch_url()` now creates httpx client with User-Agent header and `follow_redirects=True`

**Agent designer prompt (`agent_designer.py`):**
- Added DuckDuckGo HTML search pattern as the primary web search example: `https://html.duckduckgo.com/html/?q={query}` with `urllib.parse.quote_plus()`
- Wikipedia REST API kept as secondary example for known topics
- Clearer separation: "GENERAL WEB SEARCH" vs "KNOWN TOPICS"

787/787 tests passing.

---

### AD-149: DAG execution timeout excludes user-wait during escalation

When consensus is INSUFFICIENT and escalation reaches Tier 3 (user consultation), the interactive prompt blocks the DAG coroutine. The 60-second `dag_execution_timeout_seconds` counted this user-wait time against the deadline, causing timeouts even when the user promptly approved.

**Root cause:** `asyncio.wait_for(coro, timeout=60)` sets a fixed deadline at call time. User-wait time accumulates *during* execution and cannot retroactively extend the deadline.

**EscalationManager (`escalation.py`):**
- Added `user_wait_seconds: float` accumulator, reset per `execute()` call
- `_tier3_user()` wraps the `user_callback` call with `time.monotonic()` timing — seconds spent waiting for the user are recorded but excluded from the effective elapsed time

**DAGExecutor (`decomposer.py`):**
- Replaced `asyncio.wait_for` with direct `await _execute_dag()` — individual nodes already have their own 10s timeouts via `submit_intent(timeout=10.0)`
- Added `_effective_elapsed()` helper: `(wall_clock - user_wait_seconds)` — the time the *system* has been working, excluding user interaction
- Deadline check runs between batches in `_execute_dag()`: if effective elapsed exceeds `self.timeout`, raises `asyncio.TimeoutError`
- `_dag_start` timestamp set at top of `execute()` for accurate measurement

**Tests (3 new):**
- `test_user_wait_excluded_from_deadline` — simulates 2s user-wait with 3s timeout; effective elapsed (~0.5s) is within budget
- `test_genuine_timeout_still_fires` — multi-batch DAG where first batch exceeds timeout; deadline check fires before second batch
- `test_user_wait_seconds_reset_each_execute` — verifies accumulator is reset between executions

790/790 tests passing.

---

### AD-150: http_fetch non-consensus + pool scaling consensus floor

Read-only HTTP GET requests were gated by consensus (`requires_consensus=True`), but the `http_fetch` pool at `target_size=3` could be scaled down below `min_votes=3` by the PoolScaler, causing structural INSUFFICIENT consensus. More fundamentally, 2-agent consensus is meaningless (unanimous or tie — neither useful), and GET requests are non-destructive reads already protected by red team URL verification.

**Two-part fix:**

**http_fetch non-consensus (`http_fetch.py`, `runtime.py`):**
- `IntentDescriptor.requires_consensus` changed from `True` to `False`
- Removed `"http_fetch"` from `consensus_intents` set in `_validate_remote_result()`
- Updated docstrings: "Read-only: GET requests are non-destructive" (was "Medium-risk: all requests go through consensus")

**Pool scaling consensus floor (`scaler.py`, `runtime.py`):**
- `PoolScaler.__init__` accepts `consensus_pools: set[str]` and `consensus_min_agents: int` (defaults to 3)
- `_scale_down()` refuses to remove agents from consensus pools when `current_size <= consensus_min_agents`
- `scale_down_idle()` same floor check — idle dreaming can't starve consensus pools
- Runtime computes `consensus_pools` via new `_find_consensus_pools()` method (iterates spawner templates, returns pool names whose agents declare `requires_consensus=True`)
- Passes `consensus_pools` and `consensus_min_agents=config.consensus.min_votes` to PoolScaler

**Tests:**
- Updated `test_prompt_builder.py`: moved `http_fetch` from consensus-true to consensus-false assertions
- Updated `test_expansion_agents.py`: http_fetch test docstring reflects non-consensus
- 3 new tests in `test_scaling.py` (`TestPoolScalerConsensusFloor`):
  - Scale-down blocked by consensus floor
  - Idle scale-down blocked by consensus floor
  - Non-consensus pool still scales below floor (only `min_size` applies)

793/793 tests passing.

---

### AD-151: http_fetch few-shot examples still showed use_consensus: true + red team timeout mismatch

AD-150 changed `http_fetch.requires_consensus` to `False` and updated the dynamic `_build_rules()` output, but the **few-shot examples** in both `PROMPT_EXAMPLES` (prompt_builder.py) and `_LEGACY_SYSTEM_PROMPT` (decomposer.py) still showed `"use_consensus": true` for all 3 http_fetch examples. The LLM followed the examples over the rules, emitting `use_consensus: true` and routing through the full consensus + red team verification path.

Additionally, the red team's `_verify_http_fetch` used `httpx.AsyncClient(timeout=15.0)` but the runtime wrapped verification in `asyncio.wait_for(..., timeout=5.0)`. The httpx timeout exceeded the verification timeout, so `asyncio.wait_for` killed the coroutine mid-request instead of httpx returning a clean `TimeoutException`.

**Prompt fixes (`prompt_builder.py`, `decomposer.py`):**
- Changed 3 http_fetch few-shot examples from `"use_consensus": true` to `false` in `PROMPT_EXAMPLES`
- Same 3 examples updated in `_LEGACY_SYSTEM_PROMPT`
- Updated "what can you do?" response: "Writes and commands go through consensus verification" (was "Writes, commands, and HTTP requests")
- Fixed legacy prompt rule numbering (removed dedicated http_fetch consensus rule, merged into non-consensus group)

**Red team timeout fix (`red_team.py`):**
- `_verify_http_fetch` httpx timeout: 15.0s → 4.0s (fits within 5.0s `verification_timeout_seconds`)
- httpx now times out cleanly before `asyncio.wait_for`, producing a proper `TimeoutException` caught by the existing handler instead of a raw coroutine cancellation

793/793 tests passing.

### AD-152: Non-consensus node status + http_fetch timeout alignment + regression tests

**Root cause:** Two bugs caused http_fetch to show "✓ done" while the reflector reported "unable to retrieve":

1. `HttpFetchAgent.DEFAULT_TIMEOUT = 15.0s` exceeded the DAG executor broadcast timeout of `10.0s`. When the target site was slow, `asyncio.wait(tasks, timeout=10.0)` cancelled the httpx request before it completed, producing empty results.
2. The non-consensus path in `_execute_node()` unconditionally set `node.status = "completed"` regardless of whether any result succeeded. Failed tasks appeared as completed, confusing the reflector.

**Fixes:**

- `http_fetch.py`: `DEFAULT_TIMEOUT` 15.0 → 8.0 (fits within 10s broadcast window)
- `decomposer.py`: Non-consensus path now sets `node.status = "completed" if success else "failed"` based on `any(r.success for r in intent_results)`
- `decomposer.py`: Added `node_failed` event emission for failed non-consensus nodes (mirrors existing `node_complete` event)

**Regression tests (`tests/test_ad152_regressions.py` — 27 tests):**

| Class | Tests | What it guards |
|-------|-------|----------------|
| `TestTimeoutAlignment` | 3 | http_fetch timeout < broadcast timeout, red team httpx < verification timeout |
| `TestPromptConsistency` | 5 | Few-shot examples match `requires_consensus`, dynamic rules correct |
| `TestNonConsensusResultFormat` | 4 | Result dict structure, empty/failed/mixed results |
| `TestNodeStatusReflectsSuccess` | 5 | Node.status based on success, event emission for completed/failed |
| `TestSummarizeHttpFetchResult` | 5 | `_summarize_node_result` with http_fetch data variants |
| `TestHttpFetchNonConsensus` | 3 | Descriptor check, runtime pool mapping, consensus_intents exclusion |
| `TestDependencyFailurePropagation` | 1 | Failed node causes dependent nodes to fail |
| `TestHttpFetchTimeoutMessage` | 1 | Timeout error message reflects actual DEFAULT_TIMEOUT |

820/820 tests passing (+ 11 skipped).

---

### AD-153 through AD-158: Phase 13 — SystemQAAgent

**SystemQAAgent** is a meta-agent that smoke-tests newly designed agents after self-modification. When the self-mod pipeline successfully creates a new agent, SystemQAAgent generates synthetic test intents from the agent's intent metadata, dispatches them, validates the results, and updates the trust network. The system tests itself as it evolves.

**Architecture decisions:**

| AD | Decision |
|----|----------|
| AD-153 | Single-agent QA pool — intentional exception to Design Principle #1 (no single points of failure). QA is a singleton testing tool, not a mission-critical service. Pool excluded from demand-driven scaling |
| AD-154 | Non-blocking QA via `asyncio.create_task()`. Full error containment: try/except in task body, `qa_error` event logged on failure, never crashes the runtime |
| AD-155 | Trust weight asymmetry: `trust_penalty_weight=2.0` > `trust_reward_weight=1.0`. Failing agents lose trust faster than passing agents gain it, creating conservative self-correction |
| AD-156 | Param type inference from key name heuristics, not description string parsing. Key names like "url", "path", "count", "flag" map to typed synthetic values (URLs, file paths, integers, booleans) |
| AD-157 | Dual storage: `runtime._qa_reports` (typed dict, fast) for `/qa` command, episodic memory (durable) for decomposer context. Avoids fragile string-matching on `[SystemQA]` prefixes |
| AD-158 | QA pool excluded from user-facing routing: `smoke_test_agent` descriptor excluded from decomposer, pool excluded from scaler. `_EXCLUDED_AGENT_TYPES = {"red_team", "system_qa"}` |

**Files changed/created:**

| File | Change |
|------|--------|
| `src/probos/config.py` | Added `QAConfig` class, `qa: QAConfig = QAConfig()` to SystemConfig, None-section filtering in `load_config()` |
| `config/system.yaml` | Added `qa:` section with commented defaults |
| `src/probos/agents/system_qa.py` | **New.** `QAReport` dataclass, `SystemQAAgent` with `generate_synthetic_intents()`, `validate_result()`, `run_smoke_tests()`, `_infer_param_type()` heuristics |
| `src/probos/runtime.py` | QA pool creation, `_run_qa_for_designed_agent()` with trust+episodic+eventlog+flagging+auto-remove, `_EXCLUDED_AGENT_TYPES` set, QA in `status()` |
| `src/probos/experience/qa_panel.py` | **New.** `render_qa_panel()` summary table, `render_qa_detail()` per-agent breakdown |
| `src/probos/experience/panels.py` | `render_designed_panel()` — optional `qa_reports` parameter, QA column with verdict styling |
| `src/probos/experience/shell.py` | `/qa` command registration and handler, `/designed` passes qa_reports |
| `tests/test_system_qa.py` | **New.** 72 tests across 16 test classes covering all AD-153–AD-158 requirements |

892/892 tests passing (+ 11 skipped).

---

### Phase 14 — Persistent Knowledge Store (AD-159 through AD-169)

Git-backed persistence layer that survives restarts. All system artifacts (episodes, designed agents, skills, trust scores, routing weights, workflow cache entries, QA reports) are stored as human-readable JSON/Python files in a local Git repository. Enables warm boot (restore state from previous session), per-artifact rollback via Git history, and versioned audit trail of all system evolution.

**Key design decisions (AD numbers):**

| AD | Decision |
|----|----------|
| AD-159 | Late Git init: Git repo created on first write, not at boot. Avoids empty repos. meta.json with schema_version and probos_version (AD-169) |
| AD-160 | Human-readable artifacts: JSON for data, .py for agent/skill source. No binary formats |
| AD-161 | Debounced commits: `asyncio.TimerHandle` batches writes within configurable window. `_flushing` race guard prevents double-commit during shutdown |
| AD-162 | Warm boot restore order: trust → routing → agents → skills → episodes → workflows → QA. Each step independent with try/except |
| AD-163 | Validated restoration: `CodeValidator.validate()` on restored .py files before importlib loading. Corrupted/malicious agents rejected at boot |
| AD-164 | Per-artifact rollback: `git log --follow` + `git show` to retrieve previous version, creates new commit (non-destructive) |
| AD-165 | `--fresh` flag: Sets `restore_on_boot=False`. Does NOT delete the repo — new writes still persist. Previous data preserved for future warm boots |
| AD-166 | Thread executor for Git: All git subprocess calls via `asyncio.get_running_loop().run_in_executor()` — never blocks event loop |
| AD-167 | Optional infrastructure: System falls back to current behavior if knowledge disabled or git unavailable |
| AD-168 | Raw Beta parameters: Trust snapshots capture `(alpha, beta)` not derived `mean()` scores. Preserves full distribution information |
| AD-169 | Repo metadata: `meta.json` with `schema_version`, `probos_version`, `created` timestamp |

**Resolved (AD-162 → AD-177/AD-181):** Warm boot previously orphaned trust records and Hebbian weights because `BaseAgent.__init__` generated a new `uuid4()` on every instantiation. Fixed in Phase 14c: agents now have deterministic IDs derived from `hash(agent_type, pool_name, instance_index)` (AD-177), and warm boot only sets probationary trust for agents NOT found in the trust snapshot (AD-181). Agents that earned high trust retain it across restarts.

**Files changed/created:**

| File | Change |
|------|--------|
| `src/probos/config.py` | Added `KnowledgeConfig` class (enabled, repo_path, auto_commit, commit_debounce_seconds, max_episodes, max_workflows, restore_on_boot), `knowledge: KnowledgeConfig` to SystemConfig |
| `config/system.yaml` | Added `knowledge:` section with commented defaults |
| `src/probos/knowledge/__init__.py` | **New.** Package root with KnowledgeStore re-export |
| `src/probos/knowledge/store.py` | **New.** Full KnowledgeStore implementation (~430 lines): initialize(), store/load for all 7 artifact types, git init on first write, debounced commits, flush with race guard, rollback, artifact_history, thread executor for git ops |
| `src/probos/cognitive/episodic.py` | Added `seed()` — bulk restore episodes preserving original IDs via INSERT OR IGNORE |
| `src/probos/cognitive/episodic_mock.py` | Added `seed()` — in-memory bulk restore for tests |
| `src/probos/cognitive/workflow_cache.py` | Added `export_all()` — returns list of serializable dicts for shutdown persistence |
| `src/probos/consensus/trust.py` | Added `raw_scores()` — returns {agent_id: {alpha, beta, observations}} for persistence |
| `src/probos/runtime.py` | KnowledgeStore init in start(), `_restore_from_knowledge()` warm boot, episode/agent/skill/QA persistence hooks with try/except guards, shutdown flush (trust+routing+workflows+flush()), knowledge status in `status()`, default repo_path from data_dir |
| `src/probos/__main__.py` | Added `--fresh` CLI flag that sets `restore_on_boot=False` |
| `src/probos/experience/knowledge_panel.py` | **New.** `render_knowledge_panel()` — artifact count table, `render_knowledge_history()` — commit log, `render_rollback_result()` — success/failure panel |
| `src/probos/experience/shell.py` | `/knowledge` and `/rollback` commands with handlers |
| `tests/test_knowledge_store.py` | **New.** 91 tests across 12 test classes covering all AD-159–AD-169 requirements |
| `tests/test_experience.py` | Fixed `test_no_episode_for_empty_dag` — filter out SystemQA background episodes |

983/983 tests passing (+ 11 skipped).

### Phase 14b — ChromaDB Semantic Recall (AD-170 through AD-176)

Replaced keyword-overlap bag-of-words similarity with real embedding-based semantic search across four subsystems: EpisodicMemory, WorkflowCache, CapabilityRegistry, and StrategyRecommender. ChromaDB runs embedded (no external server) using ONNX MiniLM embeddings. "Find past tasks about deployment" now matches "push to production" — the system understands meaning, not just words.

**Key design decisions (AD numbers):**

| AD | Decision |
|----|----------|
| AD-170 | Shared embedding utility: lazy singleton `get_embedding_function()` wrapping ChromaDB's DefaultEmbeddingFunction (ONNX MiniLM). Graceful fallback to keyword-overlap bag-of-words when ONNX unavailable |
| AD-171 | EpisodicMemory backend swap: SQLite → ChromaDB PersistentClient. Same interface (`store`, `recall`, `recall_by_intent`, `recent`, `get_stats`, `seed`). Callers unchanged. Complex metadata (dicts, lists) serialized to JSON strings for ChromaDB metadata constraints |
| AD-172 | Two-tier persistence: ChromaDB is hot-path retrieval engine, Git KnowledgeStore is long-term persistence. On warm boot, `seed()` loads episodes from Git into ChromaDB |
| AD-173 | WorkflowCache semantic fuzzy matching: `compute_similarity()` replaces keyword overlap ratio. Intent subset check stays. Configurable `similarity_threshold` parameter (default 0.6) |
| AD-174 | CapabilityRegistry semantic tier: exact match → substring → **semantic** → keyword. Semantic tier uses `compute_similarity()` with 0.5 threshold. `semantic_matching: bool` config flag for feature toggle |
| AD-175 | StrategyRecommender semantic scoring: `compute_similarity()` replaces Jaccard keyword overlap for intent-descriptor comparison. Higher similarity → higher add_skill confidence. Fallback to keyword overlap |
| AD-176 | MockEpisodicMemory unchanged: tests stay deterministic and fast with keyword matching, no ChromaDB dependency |

**Files changed/created:**

| File | Change |
|------|--------|
| `pyproject.toml` | Added `chromadb>=1.0` dependency |
| `src/probos/cognitive/embeddings.py` | **New.** Shared embedding utility: `get_embedding_function()`, `embed_text()`, `compute_similarity()`, keyword-overlap fallback (`_keyword_embedding`, `_keyword_similarity`, `_tokenize`) |
| `src/probos/cognitive/episodic.py` | Rewritten: SQLite → ChromaDB PersistentClient. `_episode_to_metadata()` / `_metadata_to_episode()` for JSON-serialized complex fields. Cosine distance → similarity conversion |
| `src/probos/cognitive/workflow_cache.py` | `lookup_fuzzy()` uses `compute_similarity()` instead of keyword overlap ratio. Added `similarity_threshold` parameter |
| `src/probos/mesh/capability.py` | `_score_match()` adds semantic tier between substring and keyword. `semantic_matching` constructor parameter |
| `src/probos/cognitive/strategy.py` | `_compute_overlap()` replaces `_keyword_overlap()` with `compute_similarity()` + keyword fallback |
| `src/probos/config.py` | Added `similarity_threshold: float = 0.6` to `MemoryConfig`, `semantic_matching: bool = True` to `MeshConfig` |
| `config/system.yaml` | Added commented `similarity_threshold` to memory section, `semantic_matching` to mesh section |
| `src/probos/__main__.py` | Passes `relevance_threshold` from config to EpisodicMemory |
| `src/probos/runtime.py` | Passes `semantic_matching` config to CapabilityRegistry |
| `tests/test_embeddings.py` | **New.** 7 tests: embedding function callable, embed_text returns floats, cosine similarity, semantic ordering, empty text, fallback |
| `tests/test_episodic_chromadb.py` | **New.** 11 tests: store/recall, ranked results, semantic deployment match, intent filter, recent ordering, stats, eviction, seed, dedup, round-trip, empty collection |
| `tests/test_episodic.py` | Updated imports: `_keyword_embedding`/`_keyword_similarity` from `embeddings.py`. Renamed `TestEpisodicMemorySQLite` → `TestEpisodicMemoryChromaDBLegacy` |
| `tests/test_workflow_cache.py` | Updated fuzzy test for semantic similarity. Added `test_fuzzy_lookup_semantic_deploy_matches_production` |
| `tests/test_capability.py` | Added `test_semantic_match_open_file_finds_read_document`, `test_semantic_matching_disabled` |
| `tests/test_strategy.py` | Added `test_semantic_similarity_higher_confidence_for_similar_intents` |
| `tests/test_knowledge_store.py` | Added `TestChromaDBKnowledgeIntegration`: episode persist → Git → seed → ChromaDB recall, warm boot integration |

1007/1007 tests passing (+ 11 skipped). 24 new tests.

### Phase 14c — Persistent Agent Identity (AD-177 through AD-184)

Agents are now persistent individuals that survive restarts. Previously, every agent got a random UUID on each instantiation — all earned trust, Hebbian routing weights, and confidence history was orphaned on restart. Now agents have deterministic IDs derived from deployment topology (`hash(agent_type, pool_name, instance_index)`), and the full agent roster is persisted as a Git-backed manifest in the KnowledgeStore. Warm boot reconnects trust and routing data to the correct agents automatically. Pruning permanently removes an individual — its ID is never recycled.

**Key design decisions (AD numbers):**

| AD | Decision |
|----|----------|
| AD-177 | Deterministic agent IDs: `generate_agent_id(agent_type, pool_name, instance_index)` → `{type}_{pool}_{index}_{sha256[:8]}`. Same inputs always produce the same ID. Human-readable with collision-resistant hash suffix |
| AD-178 | `agent_id` kwarg is optional everywhere — `BaseAgent.__init__` falls back to `uuid.uuid4().hex` if not provided. All 1008 pre-existing tests pass without modification |
| AD-179 | Recycle preserves identity: `AgentSpawner.recycle()` passes the original `agent_id` to the replacement. The individual persists through recycling — same trust, same routing, same ID |
| AD-180 | Agent manifest persisted in KnowledgeStore as `manifest.json` — Git-backed artifact recording `{agent_id, agent_type, pool_name, instance_index, skills_attached}` for every agent. Persisted at end of `start()` and in `stop()` |
| AD-181 | Warm boot trust reconnection: `_restore_from_knowledge()` only sets probationary trust for agents NOT found in the trust snapshot. Agents with restored trust records keep their earned trust instead of being demoted |
| AD-182 | Pool `_next_instance_index` tracking: replacement agents spawned during health check recovery get deterministic IDs at the next available index, not recycled pruned IDs |
| AD-183 | `prune_agent()` removes from pool, registry, trust network, and Hebbian router. Updated manifest persisted. The pruned ID is permanently retired |
| AD-184 | `--fresh` flag (`restore_on_boot=False`) gives agents deterministic IDs but does not restore trust or routing — clean slate with stable identity |

**Files changed/created:**

| File | Change |
|------|--------|
| `src/probos/substrate/identity.py` | **New.** `generate_agent_id()`, `generate_pool_ids()` — deterministic ID generation from deployment topology |
| `src/probos/substrate/agent.py` | `BaseAgent.__init__` accepts optional `agent_id` kwarg, falls back to `uuid.uuid4().hex` |
| `src/probos/substrate/spawner.py` | `recycle()` preserves agent_id through recycling by forwarding to `spawn()` |
| `src/probos/substrate/pool.py` | Accepts `agent_ids` list for predetermined IDs, tracks `_next_instance_index`, `check_health()` and `add_agent()` generate deterministic IDs |
| `src/probos/substrate/heartbeat.py` | Added `**kwargs` forwarding to `super().__init__()` for `agent_id` support |
| `src/probos/knowledge/store.py` | Added `store_manifest()` and `load_manifest()` for Git-backed agent roster persistence |
| `src/probos/runtime.py` | All built-in pools use `generate_pool_ids()`, designed/skill/red-team pools get deterministic IDs, `_build_manifest()`, `_persist_manifest()`, `prune_agent()`, warm boot only sets probationary trust for new agents |
| `src/probos/experience/shell.py` | Added `/prune <agent_id>` command with confirmation prompt |
| `tests/test_identity.py` | **New.** 15 tests: deterministic generation, format validation, collision resistance, agent_id kwarg, spawner forwarding, pool with predetermined IDs |
| `tests/test_persistent_identity.py` | **New.** 18 tests: manifest persistence (5), warm boot reconnection (6), pruning (6), end-to-end milestone (1) |
| `tests/test_spawner.py` | Updated `test_recycle_with_respawn` — recycle now preserves ID (Phase 14c design) |

1041/1041 tests passing (+ 11 skipped). 33 new tests.

### Phase 14d — Agent Tier Classification & Self-Introspection (AD-185 through AD-190)

Two changes that formalize ProbOS's agent architecture: (1) a `tier` field classifying every agent as `"core"`, `"utility"`, or `"domain"`, replacing the hardcoded `_EXCLUDED_AGENT_TYPES` set with descriptor-based filtering; (2) two new self-introspection intents (`introspect_memory`, `introspect_system`) so ProbOS can accurately report its own state instead of falling through to the LLM.

**Key design decisions (AD numbers):**

| AD | Decision |
|----|----------|
| AD-185 | Three-tier classification: `core` (infrastructure I/O, deterministic tool agents), `utility` (meta-cognitive, system monitoring), `domain` (user-facing cognitive work). Default is `domain` — designed agents automatically get the right tier |
| AD-186 | `_EXCLUDED_AGENT_TYPES` removed entirely. Descriptor collection includes all agents with non-empty `intent_descriptors` regardless of tier. Agents with empty descriptors (heartbeat, red_team, corrupted) are naturally excluded |
| AD-187 | SystemQAAgent `intent_descriptors` set to `[]` — its `smoke_test_agent` intent is internal-only, triggered by the self-mod pipeline, not routed via the intent bus |
| AD-188 | `tier` field added to both `BaseAgent` (class attribute) and `IntentDescriptor` (dataclass field), both defaulting to `"domain"` for backward compatibility |
| AD-189 | `introspect_memory` returns episodic memory stats (episode count, intent distribution, success rate, backend). `introspect_system` returns tier-grouped agent counts, trust summary (mean/min/max), Hebbian weight count, pool health, knowledge store status, dream cycle state |
| AD-190 | Both introspection intents use `requires_reflect=True` — the agent returns structured data, the reflect step synthesizes natural language. The system describes itself through observed state, not LLM confabulation |

**Agent classification:**

| Tier | Agents |
|------|--------|
| core | FileReaderAgent, FileWriterAgent, DirectoryListAgent, FileSearchAgent, ShellCommandAgent, HttpFetchAgent, RedTeamAgent, HeartbeatAgent, SystemHeartbeatAgent, CorruptedFileReaderAgent |
| utility | IntrospectionAgent, SystemQAAgent |
| domain | SkillBasedAgent, all designed agents (default) |

**Files changed/created:**

| File | Change |
|------|--------|
| `src/probos/types.py` | Added `tier: str = "domain"` to `IntentDescriptor` |
| `src/probos/substrate/agent.py` | Added `tier: str = "domain"` class attribute to `BaseAgent` |
| `src/probos/agents/file_reader.py` | `tier = "core"` |
| `src/probos/agents/file_writer.py` | `tier = "core"` |
| `src/probos/agents/directory_list.py` | `tier = "core"` |
| `src/probos/agents/file_search.py` | `tier = "core"` |
| `src/probos/agents/shell_command.py` | `tier = "core"` |
| `src/probos/agents/http_fetch.py` | `tier = "core"` |
| `src/probos/agents/red_team.py` | `tier = "core"` |
| `src/probos/agents/corrupted.py` | `tier = "core"` |
| `src/probos/agents/heartbeat_monitor.py` | `tier = "core"` |
| `src/probos/substrate/heartbeat.py` | `tier = "core"` |
| `src/probos/agents/introspect.py` | `tier = "utility"`, added `introspect_memory` and `introspect_system` intent handlers |
| `src/probos/agents/system_qa.py` | `tier = "utility"`, `intent_descriptors = []` (internal-only) |
| `src/probos/substrate/skill_agent.py` | `tier = "domain"` (explicit) |
| `src/probos/runtime.py` | Removed `_EXCLUDED_AGENT_TYPES`, descriptor collection based on non-empty descriptors, `tier` added to manifest entries |
| `src/probos/experience/panels.py` | Added Tier column to agent table |
| `src/probos/cognitive/llm_client.py` | MockLLMClient patterns for `introspect_memory` and `introspect_system` |
| `tests/test_agent_tiers.py` | **New.** 21 tests: default tier, all agent classifications, descriptor field, manifest tier, panel column, descriptor collection |
| `tests/test_introspection_phase14d.py` | **New.** 11 tests: memory stats, memory disabled, tier counts, trust summary, Hebbian count, knowledge status, descriptor validation, MockLLMClient patterns |
| `tests/test_system_qa.py` | Updated routing exclusion test comments for Phase 14d |
| `tests/test_self_mod.py` | Updated sandbox timeout default assertion (60s) |

1073/1073 tests passing (+ 11 skipped). 32 new tests.

### Phase 15a — CognitiveAgent Base Class (AD-191 through AD-198)

The single biggest architectural change since Phase 3a. Introduces `CognitiveAgent(BaseAgent)` — an agent base class where `decide()` consults an LLM guided by per-agent `instructions`. This brings reasoning *inside* the mesh as a trust-scored, confidence-tracked, recyclable participant rather than concentrating all reasoning in the decomposer. The `AgentDesigner` now generates `CognitiveAgent` subclasses with `instructions` strings (LLM system prompts) instead of procedural `act()` code — the agent reasons at runtime, not at design time.

**Key design decisions (AD numbers):**

| AD | Decision |
|----|----------|
| AD-191 | `CognitiveAgent(BaseAgent)` base class: `decide()` invokes LLM with `instructions` as system prompt + observation as user message. Full perceive/decide/act/report lifecycle preserved. `act()` is the subclass extension point for structured output parsing. `_resolve_tier()` returns `"standard"` by default |
| AD-192 | `instructions: str | None = None` on `BaseAgent` (class attribute). Tool agents ignore it. `CognitiveAgent` requires non-empty instructions — raises `ValueError` otherwise. kwargs override for runtime-provided instructions |
| AD-193 | `AgentDesigner` generates `CognitiveAgent` subclasses. Instructions string is the core design output. Minimal `act()` override for output parsing. No more fully-generated procedural `act()` logic |
| AD-194 | Design prompt rewrite: LLM generates instructions (reasoning prompt) instead of procedural code. The cognitive agent reasons at runtime, not at design time |
| AD-195 | `CodeValidator` accepts `CognitiveAgent` subclasses. Does not require `handle_intent` method when parent provides it. `probos.cognitive.cognitive_agent` in import whitelist |
| AD-196 | `SandboxRunner` discovers and tests `CognitiveAgent` subclasses via existing `BaseAgent` inheritance. `CognitiveAgent` excluded from base-class filter (same as `BaseAgent`) |
| AD-197 | `MockLLMClient` updated: `agent_design` pattern generates `CognitiveAgent` code with `instructions` + `act()` override, new `cognitive_agent_decide` pattern for testing cognitive agent LLM calls |
| AD-198 | Runtime `_create_designed_pool()` works for `CognitiveAgent` via existing kwargs injection (`llm_client`, `runtime`). No API changes needed |

**Files changed / created:**

| File | Change |
|------|--------|
| `src/probos/cognitive/cognitive_agent.py` | **New.** `CognitiveAgent(BaseAgent)` base class with LLM-guided `decide()`, `instructions` field, full lifecycle |
| `src/probos/substrate/agent.py` | Added `instructions: str | None = None` class attribute |
| `src/probos/cognitive/agent_designer.py` | Rewrote `AGENT_DESIGN_PROMPT` for instructions-first CognitiveAgent generation |
| `src/probos/cognitive/code_validator.py` | Accepts `CognitiveAgent` subclasses, `probos.cognitive.cognitive_agent` import, relaxed `handle_intent` requirement for cognitive subclasses |
| `src/probos/cognitive/sandbox.py` | Imports `CognitiveAgent`, excludes it from base-class filter |
| `src/probos/cognitive/llm_client.py` | Updated `agent_design` mock to generate `CognitiveAgent` code, added `cognitive_agent_decide` pattern |
| `tests/test_cognitive_agent.py` | **New.** 24 tests: init validation, lifecycle, formatting, overrides |
| `tests/test_agent_designer_cognitive.py` | **New.** 12 tests: design output, validator, sandbox, end-to-end pipeline |
| `tests/test_self_mod.py` | Updated `CognitiveAgent` assertion in design test |

1109/1109 tests passing (+ 11 skipped). 36 new tests.

### Phase 15b — Domain-Aware Skill Attachment (AD-199 through AD-203)

Wires the skill system so skills are attached to the cognitive agent whose domain best matches the new capability, rather than always to the generic `SkillBasedAgent` dispatcher. This makes skills more effective (the cognitive agent's domain context is semantically adjacent) and more discoverable.

**Key design decisions (AD numbers):**

| AD | Decision |
|----|----------|
| AD-199 | `CognitiveAgent` skill attachment: `add_skill()`/`remove_skill()` following SkillBasedAgent pattern (AD-128). `_skills` dict, instance+class descriptor sync. `handle_intent()` checks skills first, falls through to cognitive lifecycle |
| AD-200 | StrategyRecommender domain-aware scoring: scores cognitive agents' `instructions` against new intent via `compute_similarity()`. Best match above 0.3 threshold becomes `target_agent_type`. Falls back to `skill_agent` |
| AD-201 | StrategyRecommender accepts optional `agent_classes: dict[str, type]` for instructions lookup. Runtime passes registered agent templates via `_get_agent_classes()` |
| AD-202 | Runtime `_add_skill_to_agents()` generalized: accepts `target_agent_type`, searches all pools, falls back to SkillBasedAgent if target type not found. `_get_llm_equipped_types()` includes CognitiveAgent subclasses |
| AD-203 | Strategy menu shows target agent name in label/reason when target is a cognitive agent (display-only: "Add skill to text_analyzer agent" vs "Add skill to existing agent") |

**Files changed / created:**

| File | Change |
|------|--------|
| `src/probos/cognitive/cognitive_agent.py` | Added `add_skill()`, `remove_skill()`, `_skills` dict, skill-first dispatch in `handle_intent()` |
| `src/probos/cognitive/strategy.py` | Added `_find_best_skill_target()`, `_compute_text_similarity()`, `agent_classes` parameter, domain-aware label/reason |
| `src/probos/cognitive/self_mod.py` | Passes `target_agent_type` through `_add_skill_fn` callback |
| `src/probos/runtime.py` | `_add_skill_to_agents()` generalized with `target_agent_type` parameter, `_get_llm_equipped_types()` includes cognitive agents, new `_get_agent_classes()` method |
| `src/probos/experience/renderer.py` | Passes `agent_classes` to StrategyRecommender, shows "domain match" for cognitive target |
| `tests/test_cognitive_agent_skills.py` | **New.** 17 tests: init, add/remove skill, dispatch, lifecycle fallthrough |
| `tests/test_strategy_domain_aware.py` | **New.** 14 tests: domain scoring, threshold, multi-agent, labels, backward compat |
| `tests/test_runtime_skill_routing.py` | **New.** 5 tests: target routing, fallback, equipped types, agent classes |
| `tests/test_skill_agent.py` | Updated mock `add_skill_fn` signatures for `target_agent_type` kwarg |

1145/1145 tests passing (+ 11 skipped). 36 new tests.

### Phase 16 — DAG Proposal Mode (AD-204 through AD-209)

Adds a `/plan <text>` command that decomposes natural language into a TaskDAG without executing it, letting the user inspect, edit, approve, or reject before execution. This completes the human-in-the-loop control surface for ProbOS.

**Key design decisions (AD numbers):**

| AD | Decision |
|----|----------|
| AD-204 | `propose()` reuses `process_natural_language()` decomposition path but stops before execution. Stores result as `_pending_proposal` |
| AD-205 | `execute_proposal()` / `reject_proposal()` / `remove_proposal_node()` — execute, discard, or modify the pending proposal. `_execute_dag()` extracted as shared execution path for both `process_natural_language()` and `execute_proposal()` |
| AD-206 | `render_dag_proposal()` panel: numbered Rich Table with intent, params, dependency indices, consensus flags. Title shows `/approve`, `/reject`, `/plan remove N` hints |
| AD-207 | Shell commands `/plan`, `/approve`, `/reject` wired into `ProbOSShell`. `/plan` handles three forms: `/plan <text>` (propose), `/plan` (re-display), `/plan remove N` (edit) |
| AD-208 | `/plan <text>` delegates self-mod gap detection to existing flow. `/approve` uses renderer event tracking for progress display |
| AD-209 | Event log entries: `proposal_created`, `proposal_approved`, `proposal_rejected`, `proposal_node_removed` in `cognitive` category |

**Files changed / created:**

| File | Change |
|------|--------|
| `src/probos/runtime.py` | Extracted `_execute_dag()` from `process_natural_language()`. Added `propose()`, `execute_proposal()`, `reject_proposal()`, `remove_proposal_node()`. Added `_pending_proposal` and `_pending_proposal_text` state. Imported `TaskDAG`/`TaskNode` |
| `src/probos/experience/panels.py` | Added `render_dag_proposal()` with numbered table, dependency index mapping, consensus flags, reflect annotation |
| `src/probos/experience/shell.py` | Added `/plan`, `/approve`, `/reject` commands with full handler implementations. Updated COMMANDS and handler dicts |
| `tests/test_dag_proposal.py` | **New.** 42 tests: propose lifecycle, execute/reject/remove, panel rendering, event log, shell commands, workflow cache integration |

1187/1187 tests passing (+ 11 skipped). 42 new tests.

### Phase 17 — Dependency Resolution (AD-210 through AD-215)

Self-designed agents and skills can now import any module on the expanded `allowed_imports` whitelist. When a designed agent or skill uses a third-party package that isn't installed, the `DependencyResolver` detects the gap, prompts the user for approval, and installs via `uv add`.

| AD | What |
|----|------|
| AD-210 | Expand `allowed_imports` whitelist in all config YAML files — stdlib additions (40+ modules) + third-party additions (httpx, feedparser, bs4, lxml, chardet, yaml, toml, pandas, numpy, openpyxl, markdown, jinja2, dateutil, tabulate) with inline comments grouping by category |
| AD-211 | `DependencyResolver` module — `detect_missing(source_code)` parses imports via AST, checks `importlib.util.find_spec()`, returns missing-but-allowed packages |
| AD-212 | `DependencyResolver.resolve()` — orchestrates detection → approval → installation → verification. `IMPORT_TO_PACKAGE` mapping for non-obvious names (bs4→beautifulsoup4, yaml→pyyaml, dateutil→python-dateutil). `_install_package()` calls `uv add` with timeout |
| AD-213 | Wire `DependencyResolver` into `SelfModificationPipeline` — new optional constructor param. Resolution runs between CodeValidator and SandboxRunner in both agent and skill flows. Pipeline aborts with `dependencies_declined` or `dependencies_failed` record status on failure |
| AD-214 | Shell approval UX — `_user_dep_install_approval()` callback in shell.py, wired to resolver's `approval_fn`. Displays missing packages as bulleted list, prompts `Install with uv add? [y/n]` |
| AD-215 | Event log integration — `dependency_check`, `dependency_install_approved`, `dependency_install_success`, `dependency_install_declined`, `dependency_install_failed` events in `self_mod` category. Both agent and skill flows emit events. Uses `detail=json.dumps(...)` for structured data |

#### Files changed

| File | Changes |
|------|---------|
| `config/system.yaml` | Expanded `allowed_imports` from 18 to 60+ entries with category comments |
| `config/node-1.yaml` | Same `allowed_imports` expansion |
| `config/node-2.yaml` | Same `allowed_imports` expansion |
| `src/probos/cognitive/dependency_resolver.py` | **New.** `DependencyResolver` class, `DependencyResult` dataclass, `IMPORT_TO_PACKAGE` mapping. AST-based import detection, `importlib.util.find_spec` availability check, `uv add` installation, user approval callback |
| `src/probos/cognitive/self_mod.py` | Added `DependencyResolver` and `EventLog` imports. Added `dependency_resolver` and `event_log` optional constructor params. Inserted dependency resolution step (2b) between validation and sandbox in both `handle_unhandled_intent()` and `handle_add_skill()`. Event logging for dependency lifecycle |
| `src/probos/runtime.py` | Creates `DependencyResolver` in self-mod init block, passes to pipeline with `event_log` |
| `src/probos/experience/shell.py` | Added `_user_dep_install_approval()` callback. Wires approval to resolver's `_approval_fn` during init |
| `tests/test_dependency_resolver.py` | **New.** 28 tests: stdlib detection, third-party detection, import forms, package mapping, resolve orchestration, approval/decline/install, dataclass defaults |
| `tests/test_self_mod_deps.py` | **New.** 12 tests: pipeline backward compat, resolver integration, declined/failed abort, skill resolution, event log events, end-to-end flow |

#### Phase 17 HXI specifics

- **User approval before install** — ProbOS never installs packages without asking. The shell prompts with a clear list of packages and their names, with `[y/n]` confirmation
- **Transparent package mapping** — when import name differs from package name (e.g., `bs4` → `beautifulsoup4`), the approval prompt shows both names so the user knows exactly what will be installed
- **Full event log audit trail** — every dependency decision is logged: what was checked, what was approved/declined, what succeeded/failed. Supports `/events` inspection

1227/1227 tests passing (+ 11 skipped). 40 new tests.

### Phase 18 — Feedback-to-Learning Loop (AD-216 through AD-222)

User signals after execution — `/feedback good|bad` and `/reject` — now feed into Hebbian weight updates, trust adjustments, and tagged episodic memory. Human feedback is the highest-quality training signal available: the system learns faster from human feedback than from agent-to-agent interactions (2x Hebbian reward: 0.10 vs 0.05).

| AD | What |
|----|------|
| AD-216 | `/feedback good\|bad` shell command. Operates on `_last_execution`. One rating per execution (`_last_feedback_applied` flag). Reset on each new execution |
| AD-217 | `FeedbackEngine`: applies human signals to trust, Hebbian routing, and episodic memory. `feedback_hebbian_reward=0.10` (2x normal) because human feedback is higher quality. One `record_outcome()` per agent for trust |
| AD-218 | Feedback-tagged episodes: `human_feedback` field in episode metadata (`"positive"`, `"negative"`, `"rejected_plan"`). Recalled by decomposer via `recall_similar()` to influence future planning |
| AD-219 | `FeedbackEngine` created in runtime `start()`, wired to `record_feedback()`. `reject_proposal()` auto-applies rejection feedback. `_last_feedback_applied` and `_last_execution_text` state tracking. Executed DAG stored in `execution_result["dag"]` for feedback access |
| AD-220 | `/feedback` command wired to `runtime.record_feedback()`. `/reject` display updated to indicate feedback was recorded |
| AD-221 | Agent ID extraction from executed DAGs: handles dict results, IntentResult objects, missing results, deduplication. Intent→agent pairs for Hebbian updates |
| AD-222 | Event log: `feedback_positive`, `feedback_negative`, `feedback_plan_rejected`, `feedback_hebbian_update`, `feedback_trust_update`. Category: `cognitive` |

### AD-228: Web-fetching perceive() override for designed agents

**Problem:** `AGENT_DESIGN_PROMPT` explicitly forbade overriding `perceive()`, locking all designed CognitiveAgents into pure LLM reasoning. LLMs cannot browse the internet, so any intent requiring real-time web data (news, weather, live APIs) would fail — the agent asked the LLM to produce data it cannot access.

**Decision:** Allow `perceive()` override in designed agents specifically for real-time data fetching. The design prompt now provides two templates: (1) pure LLM reasoning (no override — for intents solvable via reasoning alone) and (2) web-fetching (override `perceive()` to fetch data via httpx, store in `observation["fetched_content"]`). An explicit guard states: "An LLM cannot browse the internet. If the intent requires fetching live data, you MUST override perceive()."

**Changes:**
- `agent_designer.py`: Updated `AGENT_DESIGN_PROMPT` — removed `perceive()` from "do NOT redefine" list, added web-fetching template with httpx pattern, added LLM-cannot-browse warning, dual template structure
- `cognitive_agent.py`: `_build_user_message()` now includes `fetched_content` from observation dict in the LLM user prompt, so web-fetched data flows through to the LLM automatically

**Constraints:** `perceive()` override is scoped to data fetching only — `decide()`, `report()`, `handle_intent()`, and `__init__()` remain forbidden overrides. httpx is already in `allowed_imports` (system.yaml). The mesh governance model is preserved — the agent fetches data in `perceive()` but still uses the LLM in `decide()` for reasoning over that data.

#### Files changed

| File | Changes |
|------|---------|
| `src/probos/cognitive/feedback.py` | **New.** `FeedbackEngine` class, `FeedbackResult` dataclass. Hebbian updates (2x reward), trust updates, feedback-tagged episode storage, event log integration. Agent ID extraction from DAG node results (dict/IntentResult/None). Intent→agent pair extraction for Hebbian routing |
| `src/probos/runtime.py` | Added `_last_feedback_applied`, `_last_execution_text`, `feedback_engine` state. `FeedbackEngine` creation in `start()`. `record_feedback()` method. `reject_proposal()` wired to rejection feedback. `execution_result["dag"] = dag` in `_execute_dag()` for feedback access. Feedback state resets in `process_natural_language()` and `_execute_dag()` |
| `src/probos/experience/shell.py` | `/feedback good\|bad` command: usage validation, guard checks (no execution, already rated), calls `runtime.record_feedback()`, displays agent count. `/reject` updated to show "Feedback recorded for future planning" |
| `tests/test_feedback_engine.py` | **New.** 28 tests: positive/negative Hebbian updates, trust updates, episode storage with tags, FeedbackResult correctness, 2x reward verification, empty DAG, failed nodes, deduplication, rejection feedback (episode only, no trust/Hebbian), agent ID extraction (dict, IntentResult, missing, dedup), intent-agent pairs, event log integration (events, categories), FeedbackResult dataclass |
| `tests/test_feedback_runtime.py` | **New.** 17 tests: record_feedback guard checks (no execution, already rated, no engine, no DAG), positive/negative engine calls, flag setting, _execute_dag reset, reject_proposal feedback wiring (with/without engine), shell command integration (usage, good, bad, already rated, no execution) |

#### Phase 18 HXI specifics

- **Feedback is opt-in** — `/feedback good|bad` is user-initiated, never prompted. Each execution can only be rated once (prevents signal-spamming)
- **Rejection becomes a learning signal** — `/reject` automatically stores a rejection-tagged episode so the decomposer sees "user rejected a plan like this" in future PAST EXPERIENCE context
- **Transparent weight updates** — the shell reports exactly how many agents were affected by the feedback, making the learning process visible to the user
- **No forced learning** — feedback episodes influence future planning through the existing `recall_similar()` mechanism. The decomposer sees tagged episodes in context but is not forced to follow them — it uses its own judgment about how to incorporate the signal

1272/1272 tests passing (+ 11 skipped). 45 new tests.

### Phase 19 — Shapley Value Trust Attribution + Trust-Weighted Capability Matching (AD-223 through AD-227)

Two game-theoretic improvements that make ProbOS's trust and agent selection systems meaningfully smarter:

1. **Shapley Value Trust Attribution** — when a consensus outcome succeeds or fails, agents who were *decisive* (removing them would have changed the outcome) get proportionally more trust credit than agents who were *redundant* (the outcome would have been the same without them).

2. **Trust-Weighted Capability Matching** — when agents match for an intent, the system prefers agents whose capability claims are backed by trust history. `final_score = capability_score * (0.5 + 0.5 * trust)` — floor at 50%, never eliminates matches.

| AD | What |
|----|------|
| AD-223 | `compute_shapley_values()` — brute-force permutation algorithm for coalitions of 3-7 agents. Marginal contribution: does adding agent *i* change the quorum outcome? Supports confidence-weighted and unweighted voting. Normalized to [0, 1]. Edge cases: unanimous → equal split, dissenter → 0.0, single agent → 1.0 |
| AD-224 | Shapley-weighted trust updates. `ConsensusResult.shapley_values: dict[str, float] | None` populated by `QuorumEngine.evaluate()`. Trust `record_outcome()` uses Shapley value as weight (floor 0.1 for redundant agents). `_last_shapley_values` stored on runtime for panel display |
| AD-225 | Trust-weighted capability matching. `CapabilityRegistry.query()` accepts optional `trust_scores: dict[str, float]`. Score formula: `score * (0.5 + 0.5 * trust)`. Trust 1.0 → no change, trust 0.0 → halved. Backward compatible (None = no weighting) |
| AD-226 | Agent selection wiring. ProbOS agents self-select via `handle_intent()` — the CapabilityRegistry is not in the dispatch path. Trust-based quality differentiation is already covered by confidence-weighted consensus voting (AD-19) and Shapley attribution (AD-224). Trust-weighted matching is available for future mesh routing and the StrategyRecommender |
| AD-227 | `/agents` panel shows Shapley column when values available: value + label (decisive/marginal/redundant). Thresholds: ≥0.4 decisive, ≥0.15 marginal, <0.15 redundant |

#### Files changed

| File | Changes |
|------|---------|
| `src/probos/consensus/shapley.py` | **New.** `compute_shapley_values()` — permutation-based Shapley computation, `_evaluate_coalition()` helper for subset quorum evaluation |
| `src/probos/consensus/quorum.py` | Imports `compute_shapley_values`. `evaluate()` populates `ConsensusResult.shapley_values` for non-INSUFFICIENT outcomes |
| `src/probos/types.py` | Added `shapley_values: dict[str, float] | None = None` to `ConsensusResult` |
| `src/probos/mesh/capability.py` | `query()` accepts optional `trust_scores` parameter. When provided, scores multiplied by `(0.5 + 0.5 * trust)` |
| `src/probos/runtime.py` | Shapley-weighted trust updates in `submit_intent_with_consensus()`: `record_outcome(weight=shapley_weight)` with floor 0.1. `_last_shapley_values` stored for panel display |
| `src/probos/experience/panels.py` | `render_agent_table()` accepts optional `shapley_values` parameter, shows Shapley column with value + decisive/marginal/redundant label |
| `src/probos/experience/shell.py` | `/agents` command passes `_last_shapley_values` to panel renderer |
| `tests/test_shapley.py` | **New.** 26 tests: core computation (unanimous, dissenter, decisive voter, 5-agent, single, all-reject, confidence-weighted, empty, sum ≤1, non-negative, identical votes, marginal vote, unweighted, 4-agent split, 2-agent, 7-agent tractable, rejected outcome, high threshold), ConsensusResult integration (default None, explicit set, QuorumEngine populates, INSUFFICIENT no Shapley), panel integration (with/without Shapley column) |
| `tests/test_trust_weighted_capability.py` | **New.** 12 tests: trust weighting (no scores unchanged, trust 1.0/0.0/0.5, higher trust ranks above, never eliminates, multiple agents ordering, missing agent default), Shapley-weighted trust updates (decisive stronger, redundant weaker, equal votes equal, weight backward compat) |

#### Phase 19 design notes

- **Brute-force is fine** — ProbOS quorums are 3-7 agents, so `itertools.permutations` produces at most 5040 iterations. No approximation algorithms needed
- **Shapley applies to consensus only** — it's specifically about coalition games (quorum voting). Hebbian routing and feedback trust use different update mechanics
- **Trust-weighted matching complements, doesn't replace** — agents still self-select for intents. Trust weighting is a parallel signal available for ranking when multiple agents match the same capability
- **Floor at 0.1 for trust updates** — even redundant agents get minimal trust signal so they don't become invisible to the trust network

1310/1310 tests passing (+ 11 skipped). 38 new tests.

### Phase 18b — Correction Feedback Loop (AD-229 through AD-235)

Bridges the gap between self-modification (Phase 10) and feedback-to-learning (Phase 18): when a self-mod'd agent fails and the user provides a correction, the system fixes the agent instead of starting a new self-mod cycle.

**The problem:** user says "get news from CNN" → agent created → uses wrong URL protocol (HTTPS instead of HTTP) → fails. User says "use http not https" → system interprets this as a *new* unhandled intent → creates yet another agent. The correction loop intercepts this: detects the correction, patches the failing agent's source code, hot-reloads it, and auto-retries.

| AD | What |
|----|------|
| AD-229 | `CorrectionDetector` — LLM-based classifier distinguishes corrections from new requests. `CorrectionSignal` dataclass. Conservative threshold (confidence ≥ 0.5). Detection prompt with examples. Handles DAG objects and dicts. Returns None gracefully on failure |
| AD-230 | `AgentPatcher` — generates patched source via LLM, validates with same `CodeValidator` + `SandboxRunner` as self-mod. `PatchResult` and `CorrectionResult` dataclasses. Supports agent (sandbox test) and skill (importlib compilation) strategies. `_clean_source()` strips markdown fences and think blocks. No new security surface |
| AD-231 | `apply_correction()` — hot-reloads patched agent into live runtime. Agent strategy: swap class in pool agents + spawner templates. Skill strategy: remove + re-add skill. Refreshes decomposer descriptors, persists to knowledge store. Auto-retries original request after reload |
| AD-232 | Correction detection in `process_natural_language()` before `decomposer.decompose()`. Runs after preamble (activity tracking, focus, pre-warm sync) but before decomposition — if correction succeeds, decompose is skipped entirely. Only targets designed agents (built-in agents cannot be patched). Falls through gracefully on detection failure or patch failure |
| AD-233 | `/correct <text>` explicit shell command. Same pipeline as auto-detection but user-initiated. Checks `_last_execution` exists, detects correction signal, patches, hot-reloads, retries. Displays patch diff and retry result. Added to `/help` |
| AD-234 | `apply_correction_feedback()` in `FeedbackEngine`. Correction episodes stored with rich metadata: `human_feedback: "correction_applied"/"correction_failed"`, correction_type, corrected_values, changes_description, retry_success. Hebbian strengthen/weaken on retry outcome. Trust bump on retry success. Event log: `feedback_correction_applied`/`feedback_correction_failed`. Corrections are the richest feedback signal — they encode "what went wrong" and "how to fix it" |
| AD-235 | `execution_context` parameter on `AgentDesigner.design_agent()` and `SelfModificationPipeline.handle_unhandled_intent()`. Prior successful execution results passed to the LLM so generated agents use known-working values (URLs, parameters, protocols) instead of guessing. Addresses the root cause: AgentDesigner was guessing values that provably worked in the prior execution |

#### Files changed

| File | Changes |
|------|---------|
| `src/probos/cognitive/correction_detector.py` | **New.** `CorrectionDetector`, `CorrectionSignal` dataclass, LLM detection prompt, `_format_dag()`, `_parse_response()` |
| `src/probos/cognitive/agent_patcher.py` | **New.** `AgentPatcher`, `PatchResult` dataclass, `CorrectionResult` dataclass, `_patch_agent()`, `_patch_skill()`, `_clean_source()` |
| `src/probos/cognitive/feedback.py` | Added `apply_correction_feedback()` method — Hebbian, trust, episodic memory, event log for correction events |
| `src/probos/cognitive/agent_designer.py` | Added `execution_context` parameter to `design_agent()` and EXECUTION CONTEXT section to prompt template |
| `src/probos/cognitive/self_mod.py` | Added `execution_context` parameter to `handle_unhandled_intent()`, passed through to `design_agent()` |
| `src/probos/runtime.py` | Added `_correction_detector`, `_agent_patcher` fields and creation in `start()`. Added `apply_correction()`, `_apply_agent_correction()`, `_apply_skill_correction()`, `_find_designed_record()`, `_was_last_execution_successful()`, `_format_execution_context()`. Correction detection wired before `decomposer.decompose()` in `process_natural_language()` — successful correction returns early, skipping decomposition entirely. Execution context passed to `handle_unhandled_intent()`. Correction feedback recorded via `feedback_engine.apply_correction_feedback()` |
| `src/probos/experience/shell.py` | Added `/correct` command to COMMANDS dict, handler dispatch, and `_cmd_correct()` implementation |
| `tests/test_correction_detector.py` | **New.** 12 tests: detection (no prior execution, no DAG, empty nodes, LLM correction, new request, low confidence, parameter_fix, malformed response, execution context in prompt, LLM failure, markdown fences, DAG as dict) |
| `tests/test_agent_patcher.py` | **New.** 14 tests: patching (success agent, preserves original, changes description, validation failure, sandbox failure, LLM failure, empty response, skill handler, clean markdown, clean think blocks, correction info in prompt, PatchResult defaults, CorrectionResult defaults, sends prompt) |
| `tests/test_correction_runtime.py` | **New.** 22 tests: _find_designed_record (recent active, built-in, no pipeline, patched), _was_last_execution_successful (no execution, all completed, node failed), _format_execution_context (no execution, includes text, includes intent/params), correction feedback (applied/failed, Hebbian, trust success/failure, episodic, event log), /correct shell command (help includes, description), correction before decompose (successful correction skips decompose), AgentDesigner context (included in prompt, empty default, pipeline passthrough) |

#### Phase 18b design notes

- **Correction detection is conservative** — false positives (treating a new request as a correction) are worse than false negatives. Confidence threshold ≥ 0.5
- **Only designed agents can be patched** — built-in agents are part of the core codebase. If correction detection targets a built-in, it falls through to normal flow
- **No new security surface** — patched code goes through the same `CodeValidator` + `SandboxRunner` pipeline as freshly designed agents
- **Correction episodes are the richest learning signal** — they include both "what went wrong" (the original failure) and "how to fix it" (the corrected values). Future decomposer recall will surface these episodes as PAST EXPERIENCE context, teaching the LLM to avoid the same mistakes

1358/1358 tests passing (+ 11 skipped). 48 new tests.

### Phase 20 — Emergent Behavior Detection (AD-236 through AD-240)

Population-level dynamics analyzer that monitors ALL agents for emergent behavior patterns. Unlike BehavioralMonitor (which tracks individual self-created agents for behavioral anomalies), EmergentDetector analyzes system-wide patterns:

1. **Hebbian weight topology** → cooperation clusters via union-find connected components
2. **Trust score trajectories** → z-score outlier detection, hyperactive observation detection, change-point detection
3. **Routing patterns** → new intent/connection detection, Shannon entropy over pool weight distribution
4. **Dream consolidation** → baseline comparison for anomalous strengthening/pruning/trust adjustments
5. **TC_N (total correlation proxy)** → fraction of intent types routing to 2+ pools (multi-pool cooperation)

| AD | What |
|----|------|
| AD-236 | `EmergentDetector` — population-level dynamics analyzer. `EmergentPattern` dataclass (pattern_type, description, confidence, evidence, severity). `SystemDynamicsSnapshot` for point-in-time metrics. `compute_tc_n()` — total correlation proxy. `compute_routing_entropy()` — Shannon entropy. `detect_cooperation_clusters()` — union-find on Hebbian weight graph. `detect_trust_anomalies()` — z-score + hyperactive + change-point. `detect_routing_shifts()` — new intents/connections + entropy delta. `detect_consolidation_anomalies()` — dream report baseline comparison. Ring buffer history for trend analysis |
| AD-237 | Runtime wiring. `_emergent_detector` created unconditionally in `start()`. `_on_post_dream()` callback wired to `DreamScheduler._post_dream_fn`. `status()` includes `"emergent"` key with summary. Event logging for detected patterns (category: `emergent`) |
| AD-238 | Introspection integration. Two new intents: `system_anomalies` (runs detectors, returns pattern list) and `emergent_patterns` (returns snapshot + summary + trends). MockLLMClient patterns for "anomalies" and "emergent patterns" NL queries |
| AD-239 | Shell + panel. `/anomalies` command shows emergent behavior panel. `render_anomalies_panel()` — system dynamics metrics (TC_N, routing entropy, cooperation clusters, snapshots, patterns detected) + pattern table with severity coloring (info=dim, notable=yellow, significant=red) |
| AD-240 | 51 tests: dataclass roundtrips (3), TC_N computation (7: no episodic, no weights, single pool, multi pool, mixed, pool extraction, malformed ID), cooperation clusters (5: empty, single, disconnected, threshold, members), trust anomalies (6: similar, low, high, change point, hyperactive, single agent), routing shifts (5: no previous, new connection, stable, entropy uniform, entropy concentrated), consolidation anomalies (5: no report, normal, high strengthened, high pruned, prewarm), analyze integration (4: returns list, stores snapshot, max history, trends), summary/snapshot (3: JSON serializable, returns dynamics, capped patterns), runtime integration (4: creates detector, status includes emergent, tc_n zero, post dream wired), introspection integration (4: system_anomalies intent, emergent_patterns intent, MockLLM anomalies, MockLLM emergent), shell/panel (5: command works, help includes, patterns panel, empty panel, severity coloring) |

#### Files changed

| File | Changes |
|------|---------|
| `src/probos/cognitive/emergent_detector.py` | **New.** `EmergentDetector`, `EmergentPattern`, `SystemDynamicsSnapshot` dataclasses, 5 detection algorithms, `summary()`, `get_snapshot()`, ring buffer history |
| `src/probos/cognitive/dreaming.py` | Added `_post_dream_fn` callback to `DreamScheduler`. Invoked in `force_dream()` and `_monitor_loop()` after each dream cycle completes |
| `src/probos/runtime.py` | Added `_emergent_detector` field, creation in `start()`, `_on_post_dream()` method, `status()` includes `"emergent"` key, post-dream callback wiring |
| `src/probos/agents/introspect.py` | Added `system_anomalies` and `emergent_patterns` intents (descriptors + handlers + dispatch) |
| `src/probos/cognitive/llm_client.py` | Added `system_anomalies` and `emergent_patterns` MockLLMClient patterns and response handlers |
| `src/probos/experience/panels.py` | Added `render_anomalies_panel()` — system dynamics metrics + pattern table with severity coloring |
| `src/probos/experience/shell.py` | Added `/anomalies` command to COMMANDS dict, handler dispatch, and `_cmd_anomalies()` implementation |
| `tests/test_emergent_detector.py` | **New.** 51 tests covering all detectors, runtime integration, introspection integration, shell/panel rendering |

#### Phase 20 design notes

- **Population-level, not individual** — BehavioralMonitor tracks designed agents for safety. EmergentDetector monitors the whole system for interesting dynamics: cooperation clusters, trust anomalies, routing shifts, consolidation spikes
- **Purely observational** — EmergentDetector is a reader, not a writer. It doesn't modify trust, routing, or behavior. It only reports what it sees
- **Post-dream timing** — emergent analysis piggybacks on dream cycles. Dream cycles already consolidate Hebbian weights and trust, making the post-dream snapshot a natural observation point
- **TC_N is a proxy, not the theory** — the original Tononi TC_N requires Gaussian mutual information across independent modules. ProbOS has a single mesh, so we approximate with multi-pool cooperation fraction: what percentage of intent types route to 2+ distinct pools?
- **Ring buffer history** — snapshots are stored in a bounded ring buffer (default 100). Trend analysis looks at the last 10 snapshots to avoid stale baselines

1409/1409 tests passing (+ 11 skipped). 51 new tests.

### Phase 21 — Semantic Knowledge Layer + Phase 20 Cleanup (AD-241 through AD-246)

Two parts: (1) Phase 20 cleanup fixes (`parse_agent_id`, pattern cap, reflect prompt), (2) Semantic Knowledge Layer — unified semantic search across all ProbOS knowledge types via ChromaDB collections.

**Phase 20 cleanup (AD-241):**
- `parse_agent_id()` — reverses `generate_agent_id()` using `_ID_REGISTRY` module-level registry (populated on each ID generation) + right-to-left regex parsing with hash verification fallback
- `_all_patterns` capped at 500 entries in `EmergentDetector.analyze()` to prevent unbounded growth
- `REFLECT_PROMPT` rule 6 — structured data extraction guidance for XML, JSON, HTML, CSV results

**Semantic Knowledge Layer (AD-242 through AD-246):**

`SemanticKnowledgeLayer` manages 5 ChromaDB collections (`sk_agents`, `sk_skills`, `sk_workflows`, `sk_qa_reports`, `sk_events`) for non-episode knowledge. Episodes queried via existing `EpisodicMemory` — no duplicate collection. The layer fans out semantic queries across all collections and merges results by cosine similarity score.

| AD | What |
|----|------|
| AD-241 | Phase 20 cleanup: `parse_agent_id()` with `_ID_REGISTRY` + hash verification fallback, `_all_patterns` cap at 500, `REFLECT_PROMPT` rule 6 for structured data extraction |
| AD-242 | `SemanticKnowledgeLayer` — 5 ChromaDB collections, indexing methods (`index_agent`, `index_skill`, `index_workflow`, `index_qa_report`, `index_event`), `search()` with cross-type fan-out + episode recall, `stats()`, `reindex_from_store()` for warm boot |
| AD-243 | Runtime wiring. `_semantic_layer` created when episodic memory available. Auto-indexing hooks on `store_agent()`, `store_skill()`, `store_qa_report()`. Warm boot re-index in `_restore_from_knowledge()`. `status()` includes `"semantic_knowledge"` key. Shutdown cleanup |
| AD-244 | Introspection integration. `search_knowledge` intent with `query` and `types` params. MockLLMClient pattern for "search for", "find in knowledge", "what do you know about" |
| AD-245 | Shell + panel. `/search` command with `--type` filter. `render_search_panel()` — stats section + ranked results table with type-based coloring (agent=cyan, skill=green, workflow=yellow, qa_report=magenta, event=blue, episode=dim) |
| AD-246 | 45 tests: `parse_agent_id` (4: registry, compound pool, hash fallback, UUID returns None), `_all_patterns` cap (1), lifecycle (3: start creates collections, stop cleans up, stats returns counts), agent indexing (4: stores document, metadata, idempotent, multiple searchable), skill indexing (3: stores, metadata, searchable), workflow indexing (3: stores, metadata, searchable), QA report indexing (2: stores, searchable), event indexing (2: stores, searchable), cross-type search (6: multiple types, type filter, includes episodes, sorted by score, respects limit, no matches empty), bulk reindex (3: indexes agents, indexes skills, returns count dict), runtime integration (5: creates layer with episodic, no layer without episodic, status includes semantic_knowledge, status disabled without layer, shutdown cleans up), introspection integration (4: search_knowledge intent, with types, no layer, MockLLM routes), shell/panel (5: help includes search, render with results, render empty, score format, no query error) |

#### Files changed

| File | Changes |
|------|---------|
| `src/probos/substrate/identity.py` | Added `_ID_REGISTRY` module-level dict, `generate_agent_id()` populates registry, added `_ID_SUFFIX_RE` regex, added `parse_agent_id()` |
| `src/probos/cognitive/emergent_detector.py` | `_extract_pool()` rewritten to use `parse_agent_id()` with fallback, `analyze()` caps `_all_patterns` at 500 |
| `src/probos/cognitive/decomposer.py` | Added rule 6 to `REFLECT_PROMPT` for structured data extraction |
| `src/probos/knowledge/semantic.py` | **New.** `SemanticKnowledgeLayer` with 5 ChromaDB collections, indexing/search/stats/reindex methods |
| `src/probos/runtime.py` | Added `_semantic_layer` field, creation in `start()`, auto-indexing hooks, warm boot reindex, `status()` key, shutdown cleanup |
| `src/probos/agents/introspect.py` | Added `search_knowledge` intent (descriptor + handler + dispatch) |
| `src/probos/cognitive/llm_client.py` | Added `search_knowledge` MockLLMClient pattern and response handler |
| `src/probos/experience/panels.py` | Added `_TYPE_COLORS` dict, `render_search_panel()` — stats + ranked results table |
| `src/probos/experience/shell.py` | Added `/search` command to COMMANDS dict, handler dispatch, `_cmd_search()` with `--type` filter |
| `tests/test_semantic_knowledge.py` | **New.** 45 tests covering parse_agent_id, lifecycle, all indexing types, cross-type search, bulk reindex, runtime integration, introspection, shell/panel |

#### Phase 21 design notes

- **No duplicate episode collection** — episodes already live in `EpisodicMemory`'s ChromaDB. The semantic layer queries it via `recall()` rather than creating a second copy. This avoids data divergence and leverages the existing embedding setup
- **Fire-and-forget auto-indexing** — runtime hooks after `store_agent()`, `store_skill()`, `store_qa_report()` are wrapped in try/except. If the semantic layer is unavailable, the primary store operation still succeeds
- **Conditional creation** — the semantic layer requires episodic memory (for ChromaDB and episode search). If no episodic memory is configured, the layer is not created and `/search` gracefully reports "disabled"
- **Cosine similarity → score** — ChromaDB returns cosine distance (0 = identical, 2 = opposite). The layer converts to similarity (`1.0 - distance`) for consistent scoring. Episode results from episodic memory get a default 0.5 score (already filtered by relevance)
- **`parse_agent_id()` design** — the registry lookup is O(1) for IDs generated in the current session. The hash verification fallback handles IDs from warm boot (pre-registry). Right-to-left split tries all possible type/pool boundaries and verifies against the stored hash suffix

1454/1454 tests passing (+ 11 skipped). 45 new tests.

