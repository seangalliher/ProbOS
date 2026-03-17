# Era II: Emergence — The Ship Comes Alive

*Phases 10-21: Self-Modification, QA, Knowledge Store, Tiers, CognitiveAgent, Feedback, Shapley, Correction, Emergent Detection, Semantic Knowledge*

This era gave ProbOS intelligence beyond execution. The system learned to design new agents at runtime, validate them through QA, persist knowledge across sessions, classify agents by tier, attach skills to cognitive agents, learn from human feedback and corrections, detect emergent patterns in its own population dynamics, and build a semantic knowledge layer. By the end of Emergence, ProbOS was not just executing tasks — it was learning, adapting, and self-modifying.

---

## What's Been Built

### Knowledge Layer (new in Phase 14)

| File | Status | Description |
|------|--------|-------------|
| `src/probos/knowledge/__init__.py` | done | Package root with KnowledgeStore re-export |
| `src/probos/knowledge/store.py` | done | `KnowledgeStore` — Git-backed persistent repository for all ProbOS artifacts. `initialize()` creates repo directory + all subdirectories (episodes, agents, skills, trust, routing, workflows, qa). Store/load methods for 7 artifact types: episodes (JSON per file, oldest-first eviction), agents (.py source + .json metadata sidecar), skills (.py + .json descriptor), trust (single snapshot.json with raw alpha/beta — AD-168), routing (single weights.json), workflows (single cache.json with max_workflows eviction), QA reports (per-agent JSON). Git integration: `_ensure_repo()` for late Git init on first write with meta.json (AD-159, AD-169), `_schedule_commit()` debounced via `asyncio.TimerHandle` (AD-161), `_git_commit()` via thread executor (AD-166), `flush()` with `_flushing` race guard. `rollback_artifact()` restores previous version via `git log --follow` + `git show` (AD-164). `artifact_history()` per-file commit log. `recent_commits()`, `commit_count()`, `meta_info()`, `artifact_counts()`. All file I/O via `_write_json()` / `_read_json()` using asyncio executor |
| `src/probos/knowledge/semantic.py` | done | `SemanticKnowledgeLayer` — unified semantic search across all ProbOS knowledge types (AD-242). Manages 5 ChromaDB collections (`sk_agents`, `sk_skills`, `sk_workflows`, `sk_qa_reports`, `sk_events`) for non-episode knowledge. Episodes queried via existing `EpisodicMemory` — no duplicate collection. Indexing methods: `index_agent()`, `index_skill()`, `index_workflow()`, `index_qa_report()`, `index_event()` — all `upsert()` with deterministic IDs and typed metadata. `search()` fans out across collections + episodic memory, merges by cosine similarity score, sorts descending. `stats()` per-collection document counts. `reindex_from_store()` bulk re-index from `KnowledgeStore` for warm boot. `source_node` metadata on all entries for future federation |

## What's Working

### Phase 4 Milestone — Achieved


### Self-modification tests (44 tests — new in Phase 10)

#### CodeValidator (9 tests)
- Valid agent code passes (1 test)
- Syntax error rejected (1 test)
- Forbidden import rejected (1 test)
- Forbidden pattern (eval/exec) rejected (1 test)
- Missing BaseAgent subclass rejected (1 test)
- Missing intent_descriptors rejected (1 test)
- Missing handle_intent rejected (1 test)
- Module-level side effects rejected (1 test)
- Allowed imports pass (1 test)

#### AgentDesigner (5 tests)
- Design returns valid source code (1 test)
- Generated code passes CodeValidator (1 test)
- Design prompt contains intent name and description (1 test)
- Design prompt includes IntentResult/IntentMessage signatures (1 test)
- Design prompt includes BaseAgent lifecycle methods (1 test)

#### SandboxRunner (4 tests)
- Valid agent loads and returns IntentResult (1 test)
- Syntax error agent fails sandbox (1 test)
- Non-BaseAgent subclass fails (1 test)
- Timeout kills runaway agent (1 test)

#### SelfModificationPipeline (7 tests)
- Full pipeline: design → validate → sandbox → register (1 test)
- Validation failure aborts pipeline (1 test)
- Sandbox failure aborts pipeline (1 test)
- Max designed agents limit enforced (1 test)
- Config disabled returns early (1 test)
- Pipeline events emitted (design, success/failure) (2 tests)

#### BehavioralMonitor (5 tests)
- Record execution updates metrics (1 test)
- High failure rate triggers alert (1 test)
- Low failure rate no alert (1 test)
- Trust decline detection (1 test)
- should_recommend_removal with insufficient data (1 test)

#### Runtime self-mod integration (8 tests)
- Runtime creates pipeline when enabled (1 test)
- Runtime skips pipeline when disabled (1 test)
- Empty DAG triggers self-mod design (1 test)
- Successful design registers new agent type (1 test)
- Designed agent pool created with correct size (1 test)
- Probationary trust set on designed agents (1 test)
- /designed command shows designed agents (1 test)
- re-decomposition after design uses new agent (1 test)

#### Escalation post-Phase-10 hardening (6 tests)
- Re-execute intent after user approval (1 test)
- User rejection marks node failed (1 test)
- Original agent results preserved on consensus-policy rejection (1 test)
- Escalation re-execution with pool rotation (1 test)
- Re-execution logging includes intent details (1 test)
- Empty error message replaced with "(empty)" (1 test)


### Phase 11 tests (59 tests — new in Phase 11)

#### Strategy Recommender (12 tests)
- Always returns at least one option (new_agent fallback) (1 test)
- Zero overlap → new_agent highest confidence (1 test)
- Keyword overlap with LLM-equipped → add_skill recommended (1 test)
- add_skill confidence > new_agent when both viable (reversibility) (1 test)
- Options sorted by confidence descending (1 test)
- recommended property returns is_recommended option (1 test)
- recommended property returns None when no options (1 test)
- Keyword overlap tokenization (AD-55 pattern) (1 test)
- StrategyOption fields roundtrip (1 test)
- StrategyProposal with empty options (1 test)
- LLM-equipped types filters add_skill (1 test)
- Safety budget risk confidence — reversible scores higher (1 test)

#### SkillBasedAgent (10 tests)
- Agent creates with empty skills (1 test)
- add_skill registers intent on instance (1 test)
- add_skill updates class-level descriptors (1 test)
- remove_skill clears intent from both levels (1 test)
- handle_intent dispatches to correct skill (1 test)
- handle_intent returns None for unknown (1 test)
- handle_intent passes llm_client (1 test)
- Multiple skills dispatch independently (1 test)
- agent_type is "skill_agent" (1 test)
- Skill with LLM handler (1 test)

#### SkillDesigner (3 tests)
- design_skill returns valid function source (1 test)
- Generated code passes SkillValidator (1 test)
- _build_function_name conversion (1 test)

#### SkillValidator (6 tests)
- Valid skill code passes (1 test)
- Missing async function rejected (1 test)
- Wrong function name rejected (1 test)
- Forbidden import rejected (1 test)
- Forbidden pattern rejected (1 test)
- Module-level side effects rejected (1 test)

#### Skill Pipeline Integration (7 tests)
- handle_add_skill full flow — design → validate → compile → attach (1 test)
- handle_add_skill validation failure aborts (1 test)
- DesignedAgentRecord.strategy field (1 test)
- Runtime _add_skill_to_agents updates pool members (1 test)
- Descriptor refresh after skill addition includes new intent (1 test)
- Skills pool spawned when self_mod.enabled=True (1 test)
- Skills pool NOT spawned when self_mod.enabled=False (1 test)

#### ResearchPhase (17 tests)
- Research returns synthesis on success (1 test)
- Research returns fallback on network failure (1 test)
- Research returns fallback on empty content (1 test)
- _generate_queries returns list (1 test)
- _generate_queries handles malformed response (1 test)
- _queries_to_urls uses urllib.parse (1 test)
- _queries_to_urls filters non-whitelisted domains (1 test)
- _queries_to_urls returns empty for empty queries (1 test)
- _queries_to_urls caps at max_pages (1 test)
- _fetch_pages truncates content (1 test)
- _fetch_pages handles failed fetches (1 test)
- _synthesize passes content to LLM (1 test)
- _synthesize handles no useful docs (1 test)
- Full research flow (1 test)
- Research context injected into design prompt (1 test)
- Pipeline research_enabled=False skips research (1 test)
- Pipeline research_enabled=True includes context (1 test)

#### Research Security (4 tests)
- URLs use urllib.parse.urlencode (1 test)
- Non-whitelisted domain URLs filtered (1 test)
- Content truncation enforced (1 test)
- Fetch goes through consensus submit_intent (1 test)

### Phase 12 tests (17 tests — new in Phase 12)

#### CognitiveConfig Tiers (5 tests)
- Default config falls back to shared values (1 test)
- Per-tier URL overrides shared (1 test)
- Per-tier API key overrides shared (1 test)
- Mixed overrides: fast overridden, standard/deep fall back (1 test)
- tier_config() returns correct model per tier (1 test)

#### OpenAICompatibleClient Multi-Endpoint (7 tests)
- Separate httpx clients for different base_urls (1 test)
- Deduplicates httpx clients for shared base_urls (1 test)
- complete() routes fast-tier to fast endpoint (1 test)
- complete() routes standard-tier to standard endpoint (1 test)
- tier_info() returns per-tier config (1 test)
- Backward-compat legacy keyword args (1 test)
- models property reflects tier_configs (1 test)

#### Connectivity Check (3 tests)
- check_connectivity() returns per-tier status dict (1 test)
- Shared endpoint checked once, result reused (1 test)
- Individual tier failure doesn't block others (1 test)

#### Boot Sequence (2 tests)
- All tiers unreachable falls back to MockLLMClient (1 test)
- Partial connectivity tracked in tier_status (1 test)

### SystemQA tests (72 tests — new in Phase 13)

#### QAConfig (4 tests)
- Default config values match spec (1 test)
- QAConfig in SystemConfig as qa field (1 test)
- QAConfig from YAML with custom values (1 test)
- Missing qa: section falls back to defaults (1 test)

#### Synthetic Intent Generation (11 tests)
- Happy path intents have valid params (1 test)
- Edge case intents have minimal/empty params (1 test)
- Error case intents have invalid params (1 test)
- Count parametrize [3, 5, 7] — total matches (3 tests)
- Param type inference: url key → URL values (1 test)
- Param type inference: path key → path values (1 test)
- Param type inference: numeric key → int values (1 test)
- Param type inference: bool key → bool values (1 test)
- Param type inference: unknown key → string defaults (1 test)

#### Validate Result (7 tests)
- Happy path success passes (1 test)
- Error case graceful failure passes (1 test)
- Unhandled crash fails (1 test)
- None on error case counts as pass (declined) (1 test)
- None on happy path counts as fail (1 test)
- Edge case success passes (1 test)
- Edge case failure passes (no crash = pass) (1 test)

#### QAReport Structure (4 tests)
- All required fields and correct types (1 test)
- Pass rate calculation 3/5 → 0.6, verdict "passed" (1 test)
- Fail rate calculation 2/5 → 0.4, verdict "failed" (1 test)
- Boundary: exactly 0.6 → "passed", below → "failed" (1 test)

#### Smoke Test Integration (6 tests)
- Passing agent → verdict "passed", all tests pass (1 test)
- Failing agent → verdict "failed", agent crashes (1 test)
- Flaky agent → mixed results (1 test)
- Declining agent → only error case passes (1 test)
- Per-test timeout triggers on slow agent (1 test)
- Total timeout skips remaining tests (1 test)

#### Trust Integration (3 tests)
- Trust scores increase after passing QA (1 test)
- Trust scores decrease after failing QA (1 test)
- Penalty weight (2.0) > reward weight (1.0) asymmetry (1 test)

#### Episodic Memory Integration (2 tests)
- Episode stored with [SystemQA] prefix after QA (1 test)
- Episode has correct dag_summary, outcomes, reflection, agent_ids (1 test)

#### Event Log Integration (5 tests)
- smoke_test_started event emitted (1 test)
- smoke_test_passed event emitted on success (1 test)
- smoke_test_failed event emitted on failure (1 test)
- agent_flagged event when flag_on_fail=True (1 test)
- No agent_flagged when flag_on_fail=False (1 test)

#### Auto-Remove (3 tests)
- Pool emptied when 0/N pass and auto_remove=True (1 test)
- Pool NOT emptied on partial failure (1 test)
- Pool NOT emptied when auto_remove=False (1 test)

#### QA Report Store (2 tests)
- Report stored in runtime._qa_reports[agent_type] (1 test)
- Report overwritten on rerun of same agent type (1 test)

#### QA Disabled (2 tests)
- QA disabled skips execution, returns None (1 test)
- No system_qa agent when self-mod disabled (1 test)

#### Error Containment (4 tests)
- Exception in run_smoke_tests → qa_error event logged (1 test)
- Exception does not propagate to caller (1 test)
- Empty pool → graceful None/error, no crash (1 test)
- Missing pool → graceful None, no crash (1 test)

#### Routing Exclusion (5 tests)
- smoke_test_agent not in _collect_intent_descriptors (1 test)
- smoke_test_agent not in decomposer prompt after boot (1 test)
- system_qa pool in scaler excluded_pools (1 test)
- system_qa pool created at boot when self_mod+qa enabled (1 test)
- system_qa pool NOT created when qa disabled (1 test)

#### Regression Invariants (4 tests)
- runtime.status() includes qa key with enabled and report_count (1 test)
- runtime.status() works when QA disabled (1 test)
- Self-mod pipeline unchanged (1 test)
- Existing shell commands unchanged (1 test)

#### QA Panel Rendering (3 tests)
- render_qa_panel with reports shows Rich table (1 test)
- render_qa_panel empty shows "No QA results" (1 test)
- render_qa_panel mixed verdicts shows PASSED and FAILED (1 test)

#### QA Shell Command (4 tests)
- /qa registered in COMMANDS (1 test)
- /qa command renders panel (1 test)
- /qa agent_type shows detail view (1 test)
- /help includes /qa (1 test)

#### Designed Panel QA Column (3 tests)
- render_designed_panel with qa_reports shows QA column (1 test)
- render_designed_panel with qa_reports=None — backward compat (1 test)
- Agent not in QA reports shows em-dash (1 test)

### Phase 14 Knowledge Store tests (91 tests — new in Phase 14)

#### KnowledgeConfig (4 tests)
- Default values match spec (1 test)
- KnowledgeConfig in SystemConfig (1 test)
- Custom values from YAML (1 test)
- Missing section falls back to defaults (1 test)

#### EpisodicMemory.seed() (6 tests)
- seed() restores episodes (1 test)
- Preserves original IDs (1 test)
- Preserves timestamps (1 test)
- Skips duplicate IDs (1 test)
- Empty list returns 0 (1 test)
- MockEpisodicMemory seed works (1 test)

#### WorkflowCache.export_all() (3 tests)
- Returns all entries (1 test)
- Empty cache returns empty list (1 test)
- Entries are JSON-serializable (1 test)

#### TrustNetwork.raw_scores() (2 tests)
- Returns alpha/beta parameters (1 test)
- Raw params not derived mean (1 test)

#### KnowledgeStore Init (4 tests)
- Creates directory (1 test)
- Creates all subdirectories (1 test)
- Idempotent initialization (1 test)
- repo_exists false before write (1 test)

#### Episode storage (7 tests)
- store_episode creates file (1 test)
- Stored episode is valid JSON (1 test)
- load_episodes returns stored (1 test)
- Episodes sorted by timestamp desc (1 test)
- load_episodes with limit (1 test)
- Empty directory returns empty list (1 test)
- Max episodes eviction (1 test)

#### Agent storage (7 tests)
- store_agent creates .py and .json (1 test)
- Source code matches (1 test)
- Metadata matches (1 test)
- load_agents returns stored (1 test)
- Empty directory returns empty list (1 test)
- remove_agent deletes files (1 test)
- remove_agent nonexistent is no-op (1 test)

#### Skill storage (2 tests)
- store_skill creates files (1 test)
- load_skills returns stored (1 test)

#### Trust storage (4 tests)
- store_trust_snapshot (1 test)
- load_trust_snapshot (1 test)
- load_trust_snapshot missing returns empty (1 test)
- Contains raw alpha/beta params (1 test)

#### Routing storage (2 tests)
- store_routing_weights (1 test)
- load_routing_weights (1 test)

#### Workflow storage (3 tests)
- store_workflows (1 test)
- load_workflows (1 test)
- Max workflows eviction (1 test)

#### QA storage (2 tests)
- store_qa_report (1 test)
- load_qa_reports (1 test)

#### Git integration (11 tests)
- Git init on first write (1 test)
- meta.json with schema_version/probos_version (1 test)
- repo_exists true after write (1 test)
- flush commits immediately (1 test)
- Commit messages include artifact info (1 test)
- Flush prevents debounce race (1 test)
- Thread executor doesn't block event loop (1 test)
- Uses get_running_loop (1 test)
- Git not available graceful fallback (1 test)
- Auto-commit after debounce (1 test)
- Debounce batches writes (1 test)

#### Rollback (5 tests)
- Rollback restores previous version (1 test)
- Rollback creates new commit (1 test)
- No history returns False (1 test)
- artifact_history returns commits (1 test)
- artifact_history empty returns empty list (1 test)

#### Warm boot (11 tests)
- Restores trust with correct alpha/beta (1 test)
- Restores routing weights (1 test)
- Restores episodes via seed() (1 test)
- Restores workflows (1 test)
- Restores QA reports (1 test)
- Trust before agents order (1 test)
- Partial failure skips corrupted, restores rest (1 test)
- Empty repo cold-starts normally (1 test)
- --fresh skips restore (1 test)
- --fresh preserves repo (1 test)
- Skips invalid agent with validation failure (1 test)

#### Runtime integration (8 tests)
- Episode persisted after processing (1 test)
- Persistence failure doesn't crash (1 test)
- Shutdown flushes knowledge (1 test)
- Shutdown persists workflows (1 test)
- Shutdown persists trust (1 test)
- Shutdown persists routing (1 test)
- Knowledge disabled skips persistence (1 test)
- Knowledge status in runtime (1 test)

#### Knowledge panels (5 tests)
- render_knowledge_panel returns Panel (1 test)
- render_knowledge_history returns Panel (1 test)
- render_knowledge_history empty (1 test)
- render_rollback_result success (1 test)
- render_rollback_result failure (1 test)

#### Knowledge shell commands (5 tests)
- /knowledge shows status (1 test)
- /knowledge history shows commits (1 test)
- /rollback usage hint (1 test)
- /rollback no knowledge store (1 test)
- /help includes knowledge commands (1 test)

### Phase 14b ChromaDB Semantic Recall tests (24 tests — new in Phase 14b)

#### Embedding utility (7 tests — `test_embeddings.py`)
- `get_embedding_function()` returns callable (1 test)
- `embed_text()` returns non-empty list of floats (1 test)
- `compute_similarity()` identical text near 1.0 (1 test)
- `compute_similarity()` different text < 0.8 (1 test)
- Semantic similarity ordering: related > unrelated (1 test)
- Empty text returns 0.0 (1 test)
- Fallback to keyword overlap when unavailable (1 test)

#### EpisodicMemory ChromaDB (11 tests — `test_episodic_chromadb.py`)
- Store and recall single episode via semantic similarity (1 test)
- Ranked results by semantic similarity (1 test)
- Semantic recall: "deployment" matches "push to production" (1 test)
- recall_by_intent filters by metadata (1 test)
- recent() returns most recent first (1 test)
- get_stats returns counts (1 test)
- max_episodes eviction (1 test)
- seed() bulk loads episodes (1 test)
- seed() skips duplicate IDs (1 test)
- Episode round-trip: all fields survive store → recall (1 test)
- Empty collection returns empty (1 test)

#### WorkflowCache semantic (1 test)
- Fuzzy lookup: "deploy the app to production" matches cached "push app to production" (1 test)

#### CapabilityRegistry semantic (2 tests)
- Semantic match: "access file data" finds capability "read_file" with detail "Read a document from disk" (1 test)
- Semantic matching disabled produces lower scores than enabled (1 test)

#### StrategyRecommender semantic (1 test)
- Semantically similar intent produces higher add_skill confidence than dissimilar (1 test)

#### ChromaDB + KnowledgeStore integration (2 tests)
- Episode persist → Git → seed → ChromaDB recall (1 test)
- Warm boot: fresh ChromaDB + seed from KnowledgeStore produces searchable episodes (1 test)

## Milestones

- [x] ~~Phase 10: Self-Modification (SelfModConfig, CodeValidator AST analysis, AgentDesigner LLM-based code generation, SandboxRunner dynamic module loading, BehavioralMonitor anomaly detection, SelfModificationPipeline orchestration, TrustNetwork.create_with_prior() probationary trust, MockLLMClient agent_design + intent_extraction patterns, runtime unhandled intent detection + auto-design pipeline, /designed command + render_designed_panel, renderer self_mod events)~~
- [x] ~~627/627 tests pass~~
- [x] ~~Post-Phase 10 hardening: escalation re-execution after approval (AD-118), capability-gap detection for self-mod (AD-126), SelectorEventLoop subprocess compat (AD-116), PowerShell wrapper stripping (AD-117), LLM client injection into designed agents (AD-115), self-mod UX with user approval (AD-123), existing-agent routing (AD-119), general-purpose intent preference (AD-120), force reflect for designed agents (AD-122), anti-echo rules (AD-124), reflect prompt rewrite with node status (AD-121), log suppression (AD-125)~~
- [x] ~~660/660 tests pass~~
- [x] ~~Phase 11: Skills, Transparency & Web Research (StrategyRecommender with reversibility preference, SkillBasedAgent with instance+class descriptor sync, SkillDesigner/SkillValidator, ResearchPhase with domain-whitelisted URL construction + mesh-based fetching + content truncation, MockLLMClient skill_design + research patterns, renderer strategy menu, runtime skills pool + _add_skill_to_agents + _get_llm_equipped_types)~~
- [x] ~~719/719 tests pass~~
- [x] ~~Phase 12: Per-Tier LLM Endpoints (CognitiveConfig per-tier fields + tier_config() helper, OpenAICompatibleClient per-tier httpx clients with deduplication, per-tier connectivity checks at boot, partial connectivity support, /model per-tier display, /tier endpoint display, system.yaml fast=qwen3.5:35b@Ollama + standard/deep=Claude@Copilot proxy)~~
- [x] ~~736/736 tests pass~~
- [x] ~~**Configurable default LLM tier:** `default_llm_tier: "fast"` in config, cognitive components use `tier=None` to respect default, debug panel shows tier/model (AD-137, AD-138)~~
- [x] ~~736/736 tests pass~~
- [x] ~~**Self-mod routing fixes:** Prompt rules for capability-gap routing (AD-139), structured `capability_gap` flag (AD-140), `<think>` tag stripping (AD-141), Unicode apostrophe regex + JSON fence stripping~~
- [x] ~~**Self-mod pipeline end-to-end fix:** Token budget bump to 2048 + `/no_think`, LLM client reasoning-field fallback, agent/skill designer routed to `tier="standard"` (Claude) with `max_tokens=4096` (AD-142)~~
- [x] ~~**Live LLM integration tests:** 11 tests across 5 classes (`pytest -m live_llm`), conftest auto-skip hook, connectivity-based skip decorators (AD-143)~~
- [x] ~~754/754 tests pass + 11 live LLM tests~~
- [x] ~~**Fast→standard tier-fallback:** `_extract_unhandled_intent()` cascades fast→standard on parse failure for thinking-model interference (AD-144)~~
- [x] ~~**Native Ollama API format:** Per-tier `api_format` config (`"ollama"` / `"openai"`), dual API path in LLM client, `think: false` on native `/api/chat`, 25+ regression tests (AD-145)~~
- [x] ~~**Dynamic capability-gap examples:** Prompt examples conditionally suppressed when matching intents exist — prevents non-thinking models from following stale gap examples after self-mod (AD-145)~~
- [x] ~~**Agent designer mesh access:** Designed agents taught to dispatch sub-intents through `intent_bus.broadcast()` for external data tasks (web lookups, factual questions) instead of answering from LLM training data. Knowledge-lookup gap example added to decomposer prompt. Rules updated to distinguish inference vs external data tasks (AD-146)~~
- [x] ~~**Runtime injection for designed agents:** `_create_designed_pool()` now passes `runtime=self` so designed agents can dispatch mesh sub-intents (AD-147)~~
- [x] ~~**HttpFetch User-Agent + search strategy:** User-Agent header on all HTTP requests (fixes 403 blocks), DuckDuckGo HTML search as primary web search pattern in agent designer prompt (AD-148)~~
- [x] ~~787/787 tests pass + 11 live LLM tests~~
- [x] ~~**DAG timeout excludes user-wait:** Escalation user prompts no longer count against the 60s DAG execution deadline. Deadline checked between batches using effective elapsed time (wall-clock minus accumulated user-wait). `EscalationManager` tracks `user_wait_seconds` via `time.monotonic()` around user callbacks. 3 new tests (AD-149)~~
- [x] ~~790/790 tests pass + 11 live LLM tests~~
- [x] ~~**SystemQAAgent (Internal Self-Testing):** A runtime self-monitoring agent that validates designed agents after self-modification. On every successful self-mod pipeline, SystemQAAgent smoke-tests the newly designed agent with synthetic intents, verifies the output shape and content, records pass/fail outcomes in episodic memory, and uses the trust network to flag flaky agents for demotion or redesign. Complements the external `pytest -m live_llm` integration tests with always-on internal quality assurance — the system tests itself as it evolves. (AD-153 through AD-158)~~
- [x] ~~892/892 tests pass~~
- [x] ~~**Phase 14: Persistent Knowledge Store** — Git-backed persistence, warm boot, per-artifact rollback, `--fresh` CLI flag, `/knowledge` and `/rollback` shell commands (AD-159 through AD-169)~~
- [x] ~~983/983 tests pass~~
- [x] ~~**Self-Introspection + Agent Tier Formalization (Phase 14d):** tier field on BaseAgent/IntentDescriptor, all 13 agents classified (core/utility/domain), `_EXCLUDED_AGENT_TYPES` removed in favor of descriptor-based filtering, introspect_memory and introspect_system intents, MockLLMClient patterns, Tier column in agent table, tier in manifest (AD-185 through AD-190)~~
- [x] ~~1073/1073 tests pass~~
- [x] ~~**Phase 15a: CognitiveAgent Base Class** — `CognitiveAgent(BaseAgent)` with LLM-guided `decide()`, `instructions` field on BaseAgent, AgentDesigner generates CognitiveAgent subclasses with instructions-first design, CodeValidator/SandboxRunner accept CognitiveAgent, MockLLMClient patterns for cognitive decide, runtime wiring unchanged (AD-191 through AD-198)~~
- [x] ~~1109/1109 tests pass~~
- [x] ~~**Phase 15b: Domain-Aware Skill Attachment** — CognitiveAgent skill attachment, StrategyRecommender domain-aware scoring with `compute_similarity()`, runtime `_add_skill_to_agents()` generalization, strategy menu shows cognitive agent target (AD-199 through AD-203)~~
- [x] ~~1145/1145 tests pass~~
- [x] ~~**Phase 16: DAG Proposal Mode** — `/plan` command decomposes NL into a TaskDAG without executing. `/approve` executes, `/reject` discards, `/plan remove N` edits. `render_dag_proposal()` panel. Event log integration. `_execute_dag()` extracted as shared execution path (AD-204 through AD-209)~~
- [x] ~~1187/1187 tests pass~~
- [x] ~~**Phase 17: Dependency Resolution** — `DependencyResolver` detects missing-but-allowed imports in designed agent/skill code, prompts user for approval, installs via `uv add`, verifies. Expanded `allowed_imports` whitelist (40+ stdlib, 14 third-party). Wired into `SelfModificationPipeline` between validation and sandbox. Event log audit trail for all dependency decisions (AD-210 through AD-215)~~
- [x] ~~1227/1227 tests pass~~
- [x] ~~**Phase 18: Feedback-to-Learning Loop** — `/feedback good|bad` command rates last execution. `FeedbackEngine` applies human feedback to Hebbian routing (2x reward), trust, and episodic memory. Feedback-tagged episodes (`human_feedback: positive/negative/rejected_plan`) recalled by decomposer in future planning context. `/reject` auto-records rejection feedback. Event log integration for all feedback events. Agent ID extraction from executed DAGs (AD-216 through AD-222)~~
- [x] ~~1272/1272 tests pass~~
- [x] ~~**Phase 19: Shapley Value Trust Attribution + Trust-Weighted Capability Matching** — `compute_shapley_values()` for consensus attribution (brute-force permutations, 3-7 agents), Shapley-weighted trust updates via `record_outcome(weight=shapley)`, `ConsensusResult.shapley_values` field, trust-weighted capability matching `score * (0.5 + 0.5 * trust)` on `CapabilityRegistry.query()`, `/agents` panel Shapley column (AD-223 through AD-227)~~
- [x] ~~1310/1310 tests pass~~
- [x] ~~**Phase 18b: Correction Feedback Loop** — `CorrectionDetector` distinguishes corrections from new requests, `AgentPatcher` generates patched source via LLM with same validator/sandbox pipeline, `apply_correction()` hot-reloads patched agents into live runtime with auto-retry, `/correct <text>` explicit shell command, `apply_correction_feedback()` stores correction-tagged episodes as richest learning signal, `execution_context` parameter on `AgentDesigner` passes known-working values from prior executions (AD-229 through AD-235)~~
- [x] ~~1358/1358 tests pass~~
- [x] ~~**Phase 20: Emergent Behavior Detection** — `EmergentDetector` with 5 detection algorithms, `SystemDynamicsSnapshot` ring buffer, post-dream callback, `system_anomalies` and `emergent_patterns` intents, `/anomalies` command (AD-236 through AD-240)~~
- [x] ~~1409/1409 tests pass~~
- [x] ~~**Phase 21: Semantic Knowledge Layer + Phase 20 Cleanup** — `parse_agent_id()` with `_ID_REGISTRY`, `_all_patterns` cap, `REFLECT_PROMPT` rule 6, `SemanticKnowledgeLayer` with 5 ChromaDB collections, auto-indexing hooks, warm boot re-index, `search_knowledge` intent, `/search` command (AD-241 through AD-246)~~
- [x] ~~1454/1454 tests pass~~
