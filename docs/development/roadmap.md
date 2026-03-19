# Roadmap

ProbOS is organized as a starship crew — specialized teams of agents working together to keep the system operational, secure, and evolving. Each team is a dedicated agent pool with distinct responsibilities. The Captain (human operator) approves major decisions through a stage gate.

ProbOS doesn't just orchestrate agents — it gives them a civilization to come together. Trust they earn, consensus they participate in, memory they share, relationships that strengthen through learning, a federation they can grow into. Other frameworks dispatch tasks. ProbOS provides the social fabric that makes cooperation emerge naturally.

## Crew Structure

```
                        ┌─────────────────────┐
                        │   BRIDGE (Command)   │
                        │   Captain = Human     │
                        │   First Officer =     │
                        │   Architect Agent     │
                        └─────────┬───────────┘
                                  │
        ┌──────────┬──────────┬───┴───┬──────────┬──────────┐
        │          │          │       │          │          │
   ┌────┴───┐ ┌───┴────┐ ┌──┴───┐ ┌─┴──────┐ ┌┴───────┐ ┌┴──────────┐
   │Medical │ │Engineer│ │Science│ │Security│ │  Ops   │ │   Comms   │
   │Sickbay │ │   ing  │ │       │ │Tactical│ │        │ │           │
   └────────┘ └────────┘ └──────┘ └────────┘ └────────┘ └───────────┘
```

| Team | Starfleet Analog | ProbOS Function | Status |
|------|-----------------|-----------------|--------|
| **Medical** | Sickbay (Crusher) | Health monitoring, diagnosis, remediation, post-mortems | Built (AD-290) |
| **Engineering** | Main Engineering (Scotty) | Performance optimization, maintenance, builds, infrastructure | Partial (Builder, Architect built) |
| **Science** | Science Lab (Spock) | Research, discovery, architectural analysis, codebase knowledge | Built (Architect, CodebaseIndex) |
| **Security** | Tactical (Worf) | Threat detection, defense, trust integrity, input validation | Partial |
| **Operations** | Ops (Data/O'Brien) | Resource management, scheduling, load balancing, coordination | Partial |
| **Communications** | Comms (Uhura) | Channel adapters, federation, external interfaces | Partial |
| **Bridge** | Command (Picard) | Strategic decisions, human approval gate, goal planning | Partial |

### Ship's Computer (Runtime Services)

Not a team — shared infrastructure that all teams use:

- **CodebaseIndex** — structural self-awareness, the ship's technical manual (Phase 29c)
- **Knowledge Store** — long-term memory, the ship's library
- **Episodic Memory + Dreaming** — experiential learning, the ship's log. Three-tier dreaming model (AD-288): micro-dreams (continuous, every 10s during active sessions), idle dreams (after 120s idle), and shutdown dreams (final consolidation flush)
- **Decision Cache** — LLM reasoning cache inside CognitiveAgent (AD-272). Identical observations skip LLM re-evaluation. Future: feedback-driven cache eviction, KnowledgeStore persistence for warm boot
- **Trust Network** — reputation system, crew performance records
- **Intent Bus** — internal communications, the ship's intercom
- **Hebbian Router** — navigation, learned routing pathways

### Capability Tiers (Crew, Instruments, Knowledge)

ProbOS has three tiers of capability, modeled after a starship crew:

```
Agents  (Crew)        → who decides what    → crew members who think and collaborate
Tools   (Instruments) → what you can do     → tricorder, transporter, phaser
Skills  (Knowledge)   → what you know       → ship's library, reference data
```

| Tier | Star Trek Analog | ProbOS | Governance | Examples |
|------|-----------------|--------|------------|----------|
| **Agent** | Crew member (Crusher, Worf) | Intent handler with full lifecycle | Trust, Hebbian, consensus, Shapley | DiagnosticianAgent, SurgeonAgent |
| **Tool** | Tricorder, transporter, phaser | Typed callable function, shared across agents | Tool-level trust tracking, no per-call consensus | File read/write, HTTP fetch, API calls, MCP tools |
| **Skill** | Ship's library, computer database | Read-only data access attached to agents | None (internal) | `codebase_knowledge`, search indexes |

**When to use each:**
- **Agent** — handles a user intent, needs to decide/reason, should participate in trust and Hebbian routing
- **Tool** — performs a specific action, any authorized agent can use it, doesn't need consensus for each call
- **Skill** — provides data access internally, no behavior, read-only

Tools are the natural mapping target for MCP — external MCP tools become ProbOS tools, and ProbOS tools are exposed as MCP tools to external systems.

### The Federation

*"Cooperation at scale — across agents and humans together."*

Each ProbOS instance is a ship. Multiple instances form a federation. But the federation extends beyond ProbOS — any capable agent, regardless of origin, can join the crew. There will always be a better agent somewhere. The strategy is cooperation, not competition: federate with the best, wherever they are.

ProbOS's value isn't any single agent's capability — it's the **orchestration layer**: trust network, consensus, Hebbian routing, escalation, and the human approval gate that makes diverse agents work together better than any of them alone. A single officer is skilled, but a well-run ship with a diverse crew accomplishes more. The Enterprise's strength wasn't one species — it was Vulcan logic alongside Betazoid empathy alongside Klingon tenacity alongside android precision. Different cognitive architectures, unified by trust and shared mission. ProbOS applies the same principle to AI: Claude's reasoning, GPT's generation, Copilot's search, open-source models' cost efficiency — each brings what the others lack. The trust network and consensus layer turn that diversity into strength. ProbOS is the ship that takes you to the Nooplex — human-agent cooperation at scale.

| Star Trek Concept | ProbOS Equivalent | Status |
|---|---|---|
| Starship | Single ProbOS instance | Built |
| Ship departments | Agent pools (crew teams) | In progress |
| Ship's computer | Runtime + CodebaseIndex + Knowledge Store | Built |
| Federation | Federated ProbOS instances | Built (Phase 29) |
| Visiting officers | External AI tools (Claude Code, Copilot, etc.) | Roadmap |
| Diplomatic relations | Trust transitivity between nodes | Roadmap |
| Shared intelligence | Knowledge federation | Roadmap |
| Prime Directive | Safety constraints, boundary rules, human gate | Built |

---

## Build Phases

| Phase | Title | Crew Team | Goal |
|-------|-------|-----------|------|
| 24 | Channel Integration | Comms | Discord, Slack, Telegram adapters + external tool connectors |
| 25 | Persistent Tasks | Ops | Long-running autonomous tasks with checkpointing, browser automation |
| 25b | Tool Layer | Ship's Computer | Typed callable instruments (tricorders) shared across agents, ToolRegistry, MCP mapping |
| 26 | Inter-Agent Deliberation | Bridge | Structured multi-turn agent debates, agent-to-agent messaging, interactive execution |
| 28 | Meta-Learning | Science | Workspace ontology, dream cycle abstractions, session context, goal management |
| 29 | Federation + Emergence | Comms | Knowledge federation, trust transitivity, MCP adapter, A2A adapter, TC_N measurement |
| 29b | Medical Team | Medical | Vitals monitor, diagnostician, surgeon, pharmacist, pathologist |
| 29c | Codebase Knowledge | Ship's Computer | Structural self-awareness — indexed source map + introspection skill |
| 30 | Self-Improvement Pipeline | All Teams | Capability proposals, stage contracts, QA pool, evolution store, human gate |
| 31 | Security Team | Security | Formalized threat detection, prompt injection scanner, trust integrity monitoring, secrets management, runtime sandboxing, network egress policy, inference audit, data governance |
| 32 | Engineering Team | Engineering | Automated performance optimization, maintenance agents, build agents, LLM resilience, observability export, CI/CD, backup/restore, storage abstraction layers, containerized deployment, confidence communication, adaptive communication style, decision audit trail |
| 33 | Operations Team | Ops | Formalized resource management, workload balancing, system coordination, LLM cost tracking, crew mailbox, self-claiming task queue, competing hypotheses, file ownership, bridge alerts |

---

## Team Details

### Medical Team (Phase 29b)

*"Please state the nature of the medical emergency."*

A dedicated pool of specialized agents that monitor, diagnose, and remediate ProbOS health issues. Modeled as a medical team where each agent has a distinct role in the health lifecycle.

**Vitals Monitor (Nurse)**

- HeartbeatAgent subclass, always running at low overhead
- Tracks: response latency, trust score trends, pool utilization, error rates, dream consolidation rates, memory usage
- Raises structured alerts (severity + metric + threshold + current value) to the Diagnostician
- Does not diagnose or act — observes and escalates only

**Diagnostician**

- CognitiveAgent triggered by Vitals Monitor alerts or on a configurable schedule
- Runs structured health assessment (extends IntrospectAgent._system_health())
- Compares current state to historical baselines stored in episodic memory
- Root cause analysis: agent-level, pool-level, or system-level
- Produces a structured Diagnosis with severity, affected components, and recommended treatment

**Surgeon (Remediation)**

- CognitiveAgent that takes corrective action based on Diagnostician findings
- Actions: recycle degraded agents, trigger emergency dream cycles via force_dream(), rebalance pools via pool_scaler, prune stale episodic memory
- Actions are trust-scored via Shapley contribution — did the intervention actually fix the problem?
- High-impact actions (pruning agents, config changes) can require human approval via the approval gate

**Pharmacist (Tuning)**

- CognitiveAgent for slow-acting, trend-based configuration adjustments
- Analyzes patterns over time: "sessions average 4 minutes, idle dream threshold should be 60s not 120s"
- Produces configuration recommendations with justification and expected impact
- Changes applied through the existing config system with audit trail

**Pathologist (Post-Mortem)**

- CognitiveAgent triggered by escalation Tier 3 hits, consensus failures, or agent crashes
- Produces structured post-mortems stored in episodic memory and (future) evolution store
- Identifies recurring failure patterns across sessions
- Findings feed into the self-improvement pipeline (Phase 30) as improvement signals

---

### Codebase Knowledge Service (Phase 29c)

*The ship's technical manual — available to any crew member.*

ProbOS already has runtime self-awareness — it knows what agents are doing, their trust scores, and routing patterns. This phase adds structural self-awareness: understanding how ProbOS is built, not just how it's behaving. Access is shared across agents via a skill, like a library that any crew member can visit.

**CodebaseIndex (Runtime Service)**

- Built at startup, cached in memory, read-only during a session
- Scans `src/probos/` and builds a structured map:
  - File tree with module-level descriptions
  - Agent registry: type, tier, pool, capabilities, intent descriptors
  - Layer organization: substrate, mesh, consensus, cognitive, federation
  - Key APIs: public methods on Runtime, TrustNetwork, IntentBus, HebbianRouter, etc.
  - Configuration schema: what's tunable, current values, and where each parameter lives
- Indexed by concept, not just filename ("how does trust work?" maps to the relevant files)
- No LLM calls — pure AST/inspection-based indexing

**Semantic Code Search (CodebaseIndex Enhancement)**

*Inspired by GitHub Copilot coding agent's semantic search tool (March 2026) — meaning-based retrieval when exact names/patterns are unknown.*

Current `query()` uses word-level keyword scoring. This works when the caller knows approximate terminology, but fails for conceptual queries: "how does the system handle untrusted input?" won't match `code_validator.py` or `red_team.py` unless those exact words appear in comments or docstrings. Semantic search closes this gap.

- **Embedding index** — at startup, CodebaseIndex generates vector embeddings for each file's summary, class docstrings, and function signatures. Uses ChromaDB (already a dependency for episodic memory) as the vector store
- **Hybrid query** — `query()` combines keyword scoring (fast, exact) with semantic similarity (meaning-based). Results merged with reciprocal rank fusion
- **Chunking strategy** — embed at class/function granularity, not whole files. Each chunk carries metadata (file path, line range, layer, team) for filtering
- **Incremental updates** — when CodebaseIndex rebuilds (new agents, modified files), only re-embed changed chunks. Startup cost amortized across sessions
- **No runtime LLM calls** — embeddings generated by a small local model or pre-computed at build time. Keeps the "no LLM calls for indexing" principle intact (embeddings ≠ LLM inference)
- **Crew access** — any CognitiveAgent querying CodebaseIndex gets semantic search transparently. The Architect's Layer 2 file selection improves: "find files related to trust scoring" returns trust_network.py, routing.py, consensus.py even without keyword overlap
- **External proxy** — if ProbOS federates with GitHub Copilot (see External AI Tools below), it gains access to Copilot's semantic search over the same repo by delegation, providing a complementary external perspective

**`codebase_knowledge` Skill (Shared Crew Capability)**

- Any CognitiveAgent can use this skill to query the codebase
- Methods: `query_architecture(concept)`, `read_source(file, lines)`, `search_code(pattern)`, `get_agent_map()`, `get_layer_map()`, `get_config_schema()`
- Returns structured, context-aware answers rather than raw file contents
- Used by: Medical (Pathologist, Diagnostician), Science (Architect, Research), Engineering (Builder), Bridge (IntrospectAgent)

**Self-Knowledge Comprehension**

*"ProbOS's biggest cognitive gap is not knowing what it already knows."*

The CodebaseIndex delivers data (source code, doc sections, architecture maps) to the reflection LLM, but the LLM's synthesis is shallow — it gives generic distributed systems advice rather than reasoning about what's actually built. Improving comprehension quality:

- **Structured reflection prompts** — format context with explicit sections ("Source code from X shows...", "Roadmap section Y describes...") instead of dumping raw dicts; guide the LLM to reason about specific evidence
- **Evidence-grounded responses** — reflection prompt instructs LLM to cite specific code/docs when making claims, and to verify claims against provided snippets before stating them
- **Self-contradiction detection** — flag when a response contradicts data in the provided context (e.g., "no episodic memory" when episodic memory source code is in the snippets)

**Capability Inventory (ProbOS's MEMORY.md)**

*Inspired by Claude Code's persistent memory file — a structured self-knowledge baseline.*

Claude Code maintains a `MEMORY.md` with facts about the project it's working on (file counts, architecture layers, key systems). ProbOS should generate equivalent self-knowledge at build time:

- **Auto-generated at startup** — CodebaseIndex produces a compact capability summary alongside its structural index: "ProbOS has: episodic memory (ChromaDB, persistent), dreaming (three-tier: micro/idle/shutdown), trust network (Bayesian Beta distribution), federation (ZeroMQ), 52 agents across 25 pools..."
- **Injected into every reflection prompt** — prepended as system context so the LLM never starts cold. Prevents recommending building things that already exist
- **Updated on rebuild** — when CodebaseIndex rebuilds (new agents, new capabilities), the inventory regenerates automatically
- **Structured format** — organized by crew team and architecture layer, not just a flat list. "Medical team: Vitals Monitor, Diagnostician, Surgeon, Pharmacist, Pathologist (Phase 29b, designed). Security: red team agents (built), SSRF protection (AD-285, built)..."

**Tool-Augmented Reflection (Agentic RAG)**

*Inspired by Claude Code's ability to read files mid-reasoning — the reflection LLM should be able to look things up.*

Currently, reflection is a single LLM call with pre-assembled context. If the context is incomplete or the LLM needs to verify a claim, it has no recourse — it guesses or stays generic. Tool-augmented reflection gives the reflection step the ability to query CodebaseIndex during response generation:

- **Verification tool calls** — before stating "X doesn't exist," the reflection LLM can call `query("X")` to check. If results come back, it corrects itself before responding
- **Follow-up reads** — if the initial context mentions a file but doesn't include enough detail, the reflection LLM can call `read_source()` or `read_doc_sections()` to get more
- **Two-pass reflection** — first pass generates a draft response; second pass verifies claims in the draft against CodebaseIndex queries, revises any contradictions, then finalizes
- **Bounded iteration** — max 2-3 tool calls per reflection to keep latency reasonable; not a full agent loop, just targeted verification
- **Cost-aware** — tool-augmented reflection only activates for introspection and analysis queries, not simple command responses

**Confidence Communication in Responses**

*"Insufficient data" is honest — but "I'm 72% confident based on 3 trust observations" is more useful.*

ProbOS tracks confidence and uncertainty deeply (Bayesian Beta distributions, Shapley values, per-agent confidence scores) but never surfaces this information in natural language responses. The system knows when it's uncertain but doesn't tell the Captain.

- **Reflect prompt enhancement** — instruct the reflection LLM to communicate uncertainty levels when they exist: "Based on the trust network, Agent X has high uncertainty (only 4 observations)" rather than flat assertions
- **Confidence qualifiers** — when the Decomposer routes to an agent with low confidence (<0.5), the response should note this: "This result comes from an agent with limited track record"
- **Trust context in responses** — when consensus involves disagreement, surface the dissent: "3 of 4 agents agreed, but Agent Y dissented because..."
- **Graduated disclosure** — simple queries get clean answers; complex/ambiguous queries get confidence-tagged responses. Don't overwhelm the Captain with statistics on trivial operations
- **SystemSelfModel integration** — confidence communication depends on AD-318 (SystemSelfModel) providing the data; this enhancement consumes that data in the reflect/decompose output

**Adaptive Communication Style**

*"A new ensign gets detailed explanations. A seasoned Captain gets terse status reports."*

The Ship's Computer currently responds at a fixed technical depth regardless of who's asking or what they prefer. An adaptive style system allows users to set preferences that shape response format and detail level.

- **User preference store** — lightweight config (per-user or per-instance) with settings: `technical_depth` (brief/standard/detailed), `formality` (casual/professional/LCARS), `response_length` (concise/normal/verbose)
- **Default profiles** — "Captain" (terse, status-focused, high familiarity assumed), "Engineer" (technical detail, code references, architecture context), "Observer" (explanatory, first-principles, no jargon)
- **Runtime injection** — preferences injected into the reflect prompt alongside SYSTEM CONTEXT, shaping the LLM's response style without changing content accuracy
- **Slash command** — `/style brief` or `/style detailed` to change on the fly. Persisted across sessions
- **No accuracy compromise** — adaptive style changes *how* information is presented, never *what* information is presented. The grounding rules (AD-317) still apply regardless of style

**Decision Audit Trail**

*"Captain's log, supplemental. Explain every decision, not just the result."*

Trust events, episodes, escalation results, and agent selections exist as separate data stores. There is no unified "reasoning trace" that links a user's request through decomposition → agent selection → execution → reflection into a single auditable narrative.

- **`DecisionTrace` record** — a structured log entry created per user request that captures: original query, decomposition rationale (which intents identified, why), agent selection (which agents considered, trust scores, why the chosen agent was selected), execution outcome (success/failure, confidence), reflection summary, and any escalation events
- **Stored in episodic memory** — each trace is an episode tagged with `decision_trace` type, searchable via `/recall` or IntrospectionAgent
- **User-accessible** — `/explain` (enhanced) reconstructs the full reasoning narrative from the trace: "You asked X → I identified intent Y → routed to Agent Z (trust: 0.85, confidence: 0.92) → Agent Z returned result → I reflected and synthesized this response"
- **Captain's review** — when audit trail shows repeated low-confidence routing or escalation patterns, the Captain can identify systemic issues (e.g., "Agent X is always the fallback — maybe we need a specialist")
- **Post-hoc analysis** — dreaming engine can consolidate decision traces to identify patterns: which decomposition strategies lead to best outcomes, which agent selections correlate with escalation
- **Complement to AD-319** — Pre-Response Verification (AD-319) checks *before* responding; Decision Audit Trail documents *what happened and why* for later review

---

### Security Team (Phase 31)

*"Shields up. Red alert."*

Formalize threat detection and defense as a dedicated agent pool. Builds on existing security infrastructure (red team agents, SSRF protection).

- **Threat Detector** — monitors inbound requests for prompt injection, adversarial input, abnormal patterns
- **Trust Integrity Monitor** — detects trust score manipulation, coordinated attacks on consensus, Sybil patterns
- **Input Validator** — rate limiting enforcement, payload size limits, content policy
- **Red Team Lead** — coordinates existing red team agents, schedules adversarial verification campaigns
- Existing: Red team agents (built), SSRF protection (AD-285), prompt injection scanner (roadmap)

**Secrets Management**

- **Secure credential store** — integrate with system keyring, HashiCorp Vault, or AWS KMS for API keys, tokens, and sensitive config values
- **Runtime injection** — secrets resolved at startup and injected into agents/tools that need them, never stored in config files or logs
- **Rotation support** — automatic credential rotation without restart; agents notified when credentials change
- Existing: `.env` file support (basic), config values in `system.yaml` (not encrypted)

**Runtime Sandboxing**

- **Process isolation** — imported and self-designed agents execute in sandboxed subprocesses with restricted filesystem, network, and memory access
- **Capability whitelisting** — agents declare required capabilities in their manifest; runtime grants only those capabilities at startup
- **Resource limits** — per-agent CPU time, memory, and network quotas enforced by the sandbox; violations terminate the agent and report to Trust Network
- **Graduated trust → graduated access** — new/untrusted agents get tighter sandboxes; high-trust agents get relaxed constraints
- Existing: AST validation for self-mod agents (built), restricted imports whitelist (built), red team source scanning (built)

**Network Egress Policy**

*Inspired by NVIDIA NemoClaw's outbound connection control.*

ProbOS has SSRF protection (AD-285) for inbound attack patterns, but no outbound egress control. Agents — especially imported or self-designed ones — should not have unrestricted internet access:

- **Domain allowlist** — per-agent (or per-pool) list of permitted outbound domains. Agents can only reach URLs on their allowlist; all other requests are blocked
- **Trust-graduated access** — new/imported agents start with no network access. As trust increases, domains can be unlocked. High-trust agents get broader access
- **Real-time approval** — when an agent attempts to contact an unlisted domain, surface the request to the Captain via HXI for approve/deny (NemoClaw pattern). Approved domains are added to the allowlist
- **Hot-reloadable** — egress rules can be updated at runtime without restarting agents
- Existing: SSRF protection blocks dangerous inbound patterns (AD-285, built). Egress policy blocks unauthorized outbound connections

**Inference Audit Layer**

*Inspired by NemoClaw's inference gateway that intercepts all LLM calls.*

ProbOS centralizes LLM calls through the tiered client, but doesn't audit the content of agent-to-LLM communications. An adversarial designed agent could embed sensitive data in its prompts:

- **Prompt logging** — log all LLM requests (prompt content, system prompt, tier, requesting agent) to the event log for audit
- **Anomaly detection** — flag unusual patterns: agents sending base64-encoded data, agents including file contents they shouldn't have access to, sudden prompt size spikes
- **PII scrubbing** — optionally redact detected PII from LLM prompts before they leave the system (complements Data Governance)
- **Per-agent LLM access control** — allow/deny specific agents from using specific LLM tiers (e.g., imported agents restricted to fast tier only)
- Existing: Tiered LLM client centralizes all LLM calls (built), decision cache tracks LLM usage (AD-272, built)

**Data Governance & Privacy**

- **PII detection** — scan agent conversations and episodic memory for personally identifiable information; flag or redact before storage
- **Data retention policies** — configurable TTLs for episodic memory, conversation history, and knowledge store entries; auto-purge expired data
- **Right-to-erasure** — delete all data associated with a specific user or session on request (GDPR/CCPA compliance)
- **Audit trail** — immutable log of who accessed what data, when, and why; required for enterprise and regulated deployments
- **Consent tracking** — record user consent for data collection and processing; respect opt-out preferences across all agents

---

### Engineering Team (Phase 32)

*"I'm givin' her all she's got, Captain!"*

Automated performance optimization, maintenance, and construction. The team that keeps the ship running and builds new capabilities.

- **Performance Monitor** — tracks latency, throughput, memory pressure, identifies bottlenecks (what AD-289 did manually, but automated)
- **Maintenance Agent** — database compaction, log rotation, cache eviction, connection pool management
- **Builder Agent** — executes build prompts, constructs new capabilities (bridges to external coding agents initially)
- **Architect Agent** — reads codebase, produces build-prompt-grade proposals that the Builder can execute autonomously

**Automated Build Pipeline — Northstar I (AD-311+) ✓ COMPLETE**

*"The ship builds itself — with the Captain's approval."*

The Architect and Builder agents form an automated design-and-build pipeline. The Architect reads full source via CodebaseIndex (import graphs, caller analysis, API surface verification), produces structured proposals with embedded BuildSpecs, and the Builder executes them with test-fix retry (AD-314). Ship's Computer identity grounds the Decomposer's self-knowledge (AD-317), with a four-level progression: SystemSelfModel (AD-318), Pre-Response Verification (AD-319), and Introspection Delegation (AD-320). A GPT-5.4 code review (AD-325–329) hardened runtime safety, validator correctness, and HXI resilience. All 18 steps complete.

Inspired by: SWE-agent (Princeton NLP) for tool design, Aider for repo maps, Agentless (UIUC) for localize-then-repair pipelines, AutoCodeRover for call graph analysis.

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
**Sensory Cortex Architecture — Northstar II (AD-330+)**

*"The human brain processes 10 bits per second of conscious thought from 1 billion bits per second of sensory input. The solution isn't a wider channel — it's smarter selection."*

Every CognitiveAgent in ProbOS faces the same fundamental bottleneck: the LLM context window is a narrow conscious channel receiving a massive information stream. The Decomposer can't fit a 10K-line build log. The Architect times out on large files. The Builder starves for context on multi-file changes. Future multi-modal agents processing screenshots, telemetry, and federated state will face this at orders of magnitude greater scale.

The brain solved this problem through architecture, not bandwidth. ProbOS's Sensory Cortex Architecture applies the same biological principles to AI agent cognition:

- **Predictive Coding** — The brain maintains a generative model and only processes *prediction errors* (what's surprising). An LLM already "knows" Python, FastAPI, pytest from training. Don't send confirmed predictions — send only what's unique to THIS codebase, THIS change. Delta encoding against the model's own priors.
- **Hierarchical Abstraction** — The visual cortex processes in layers: V1 (edges) → V2 (contours) → V4 (shapes) → IT (objects). By the time "cat" reaches consciousness, billions of pixels have been compressed to a concept. Code should be represented at multiple resolution levels: L0 (raw source) → L1 (AST outline) → L2 (semantic summary) → L3 (interface contract) → L4 (pattern label). The LLM gets L0 only for lines being edited; everything else at L2-L4. 10x coverage in the same context budget.
- **Peripheral vs Foveal Processing** — The fovea (2° center) processes at high resolution; peripheral vision detects change at low resolution and redirects attention. Fast/cheap models as sensory cortex (peripheral), expensive model as executive function (foveal). Parallel fast-tier scans maintain a salience map; the deep-tier model processes only what matters.
- **Chunking with Expertise** — Working memory holds ~7 chunks, but an expert chess player's "chunk" encodes an entire board position. Pattern-label code regions ("this is a Strategy pattern", "this is a pub-sub handler") so the LLM chunks at a higher level. One label replaces thousands of implementation tokens.
- **Gist Extraction** — The brain categorizes a scene in 100ms before any detailed processing. A rapid pre-scan produces a compressed semantic map ("this is an API endpoint addition touching routing, shell, and tests") that guides all subsequent context selection.
- **Attention as Resource Allocation** — Trust scores (emotional valence), Hebbian weights (learned salience), EmergentDetector (novelty/dopamine), and task DAG dependencies (goal-directed attention) directly influence context budget allocation. High-trust agent results get more context. Novel/surprising patterns override routine data.
- **Dreaming as Abstraction Factory** — Dreams don't just consolidate — they produce the hierarchical abstractions that make future perception efficient. Dream about today's build failures → produce Level 4 pattern: "Builder timeout = file >1000 lines + deep tier." Next perception cycle uses dream-built predictions, processing only prediction errors.

```
                          SENSORY CORTEX ARCHITECTURE

  Raw Input                Perception Pipeline             Working Memory (LLM)
  ┌──────────┐      ┌─────────────────────────┐      ┌──────────────────────┐
  │ Source    │──┐   │  L4: Pattern labels     │      │                      │
  │ Logs     │  │   │  L3: Interface contracts │──────│  Focused context     │
  │ Tests    │  ├──→│  L2: Semantic summaries  │      │  (fits in window)    │
  │ Telemetry│  │   │  L1: AST outlines        │      │                      │
  │ Images   │──┘   │  L0: Raw (selected only)│      │  Prediction errors   │
  │ Fed state│      └─────────┬───────────────┘      │  only, not confirmed │
  └──────────┘                │                       │  priors              │
                    ┌─────────┴───────────────┐      └──────────────────────┘
                    │  Salience Filter         │
                    │  Trust × Hebbian ×       │
                    │  Novelty × Task priority │
                    └─────────────────────────┘
```

This architecture has implications far beyond code generation:

- **Multi-Modal Perception Gateway** — Screenshots through a "Visual Cortex" that extracts `{gist: "settings page", elements: [{button: "Save", state: "disabled"}], anomalies: ["layout overflow"]}`. Telemetry through an "Analytical Cortex" that extracts anomaly timestamps. Voice through an "Auditory Cortex" that extracts intent. Each modality gets a specialized processor that compresses to standardized hierarchical representations.
- **Federation as Social Cognition** — Federated ships exchange Level 3-4 abstractions, not raw state. The brain can't transmit its full neural state to another brain — language itself is lossy compression. Ship A tells Ship B: "Builder available, trust 0.85, Python specialist, idle" not the full agent registry.
- **Decomposer / Architect / All Agents** — Every CognitiveAgent gets a perception pipeline. The Decomposer receives pre-digested meaning from logs, history, and state — not raw data. The Architect perceives the codebase through hierarchical abstractions, not full source dumps.

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

- **AD-330: BuildBlueprint & ChunkSpec** — New data structures extending BuildSpec. `BuildBlueprint` adds `interface_contracts` (function signatures, class APIs that chunks must conform to), `shared_imports`, and `chunk_hints` (suggested decomposition boundaries). `ChunkSpec` captures what to generate, required context, expected output signature, and dependencies on other chunks. `ChunkResult` uses a **Structured Information Protocol** (adapted from LLM×MapReduce): `generated_code` (extracted information), `decisions` (rationale — why specific implementation choices were made), `output_signature` (what was actually produced), and `confidence: int` (1-5, reflecting contextual completeness — chunks with full interface contracts score higher than those working from minimal hints). Confidence scores are critical for conflict resolution in assembly. Both are dataclasses in `cognitive/builder.py` or a new `cognitive/transporter.py` module.

- **AD-331: ChunkDecomposer** — Analyzes a BuildBlueprint and produces a list of ChunkSpecs. Uses CodebaseIndex (import graph, class structure) to identify natural decomposition boundaries: one chunk per new function/method, one chunk per test class, one chunk per file in multi-file builds. Each ChunkSpec includes only the context slices needed for that chunk (interface contracts, not full file content). Validates that chunks cover the full blueprint and that inter-chunk dependencies form a DAG.

- **AD-332: Parallel Chunk Execution** — New `_execute_chunks()` method on BuilderAgent. Takes a list of ChunkSpecs, runs LLM generation for each in parallel via `asyncio.gather()`. Each call uses a focused prompt with only the chunk's required context. Per-chunk timeout, retry on failure, partial success handling (some chunks succeed, others fail). Results collected as `ChunkResult` objects with generated code + metadata.

- **AD-333: ChunkAssembler** — Three-stage assembly pipeline adapted from LLM×MapReduce's Map→Collapse→Reduce pattern. **Map** outputs are the ChunkResults from AD-332. **Collapse stage**: when chunk outputs exceed the assembler's context budget, group related chunks (same file, same class) and pre-merge them iteratively until total output fits — this allows the Transporter Pattern to scale to arbitrarily large builds, not just "large enough to chunk but small enough to reassemble in one pass." **Reduce stage**: final merge into unified file content. Handles: import deduplication and ordering, function/class ordering within files, indentation normalization, **confidence-weighted conflict resolution** (when chunks produce conflicting imports or overlapping signatures, higher-confidence chunk wins). Produces the same file-block output format the existing Builder pipeline expects, so downstream (git commit, test-fix loop) works unchanged.

- **AD-334: Interface Validator (Heisenberg Compensator)** — AST-based post-assembly verification. Checks: all function calls resolve to defined functions, all imports are present, class method signatures match interface contracts from the BluePrint, no duplicate definitions, no orphaned code. **Confidence-aware validation**: low-confidence chunks (≤2) trigger stricter checking (verify every reference resolves, not just signatures). Returns validation result with specific errors and per-chunk attribution. Zero-LLM — pure static analysis. On failure, feeds errors back for targeted re-generation of failing chunks (not full rebuild).

- **AD-335: HXI Transporter Visualization** — WebSocket events for chunk lifecycle (`chunk_started`, `chunk_completed`, `chunk_failed`, `assembly_started`, `assembly_completed`). Cognitive Canvas shows parallel "matter streams" during generation. IntentSurface shows decomposition plan and per-chunk results. Assembly diff view with chunk attribution highlights.

- **AD-336: End-to-End Integration & Fallback** — Wire Transporter Pattern into `execute_approved_build()`. Decision logic: use Transporter when combined file content exceeds `_LOCALIZE_THRESHOLD` or when blueprint specifies >2 target files or >3 functions. Fall back to existing single-pass generation for small builds. Test with real multi-file builds. Per-chunk test-fix retry integration.

#### Phase 2: Generalized Perception Pipeline (Future)

*Extract the architecture from the Builder and make it available to all CognitiveAgents.*

- **PerceptionPipeline ABC** — Shared base class with hierarchical abstraction levels (L0-L4), salience filtering, and predictive coding hooks. Any CognitiveAgent can plug in a perception pipeline to compress its input before the LLM call.
- **CodePerception** — Builder/Architect specialization. Multi-resolution code representations with AST-aware abstraction.
- **LogPerception** — Decomposer/Diagnostician specialization. Build logs, error traces, and test output compressed to semantic summaries with anomaly highlighting.
- **TelemetryPerception** — VitalsMonitor/Performance specialization. Time series compressed to pattern labels and anomaly timestamps.
- **VisualPerception** — Multi-modal specialization. Screenshots/UI state compressed to element trees with anomaly flags.
- **FederationPerception** — Federation specialization. Remote ship state compressed to capability summaries with trust scores.
- **Dream-Driven Prediction Models** — Dreaming consolidation produces Level 3-4 abstractions that become the predictive coding baseline. Future perception cycles process only prediction errors (what changed since last dream), not raw data.
- **Attention Budget Allocator** — Trust scores, Hebbian weights, novelty signals, and task priority dynamically allocate context budget across perception channels. High-trust, high-salience, novel information gets more tokens.

**Design Principles:**

- **Graceful degradation** — Single-file, small builds still use the proven single-pass path. Transporter only activates when the problem is too large for one context window.
- **Composable** — Each component (decomposer, executor, assembler, validator) is independently testable and replaceable.
- **Observable** — Every step emits events. The Captain sees what's happening. Chunks can be inspected, approved, or rejected individually.
- **No new agents** — The Transporter Pattern enhances the existing BuilderAgent, not a separate agent. The Builder gains the ability to decompose and parallelize, but it's still the same agent in the same pool.
- **Biology-first** — When in doubt, ask "how does the brain solve this?" The brain had 500 million years of evolution to optimize information processing under bandwidth constraints. Respect those solutions.

Inspired by: The human brain's 10 bps conscious bottleneck (Manfred Zimmermann, 1986), Karl Friston's Free Energy Principle and predictive coding, the visual cortex hierarchy (Hubel & Wiesel), George Miller's chunking (1956), MapReduce (Google, 2004) for decompose-execute-merge, LLM×MapReduce (Zhou et al., 2024) for structured information protocol and confidence-calibrated chunk assembly, Cursor's multi-file editing, Microsoft's CodePlan for inter-procedural edit planning, the Star Trek transporter's matter stream concept.

- **Infrastructure Agent** — disk space monitoring, dependency health, environment validation
- Existing: PoolScaler handles some Ops/Engineering overlap

**Containerized Deployment (Docker)**

*"The ship in a bottle — portable, isolated, cross-platform."*

ProbOS currently runs directly on the host OS. A Docker-based deployment provides security isolation (agents can't reach the host filesystem), cross-platform parity (Windows, Linux, macOS from one image), and simplified setup:

- **Official Dockerfile** — multi-stage build: Python base with ProbOS deps, Ollama for local LLM, optional HXI frontend served via the built-in FastAPI static mount
- **docker-compose.yml** — one-command startup: ProbOS runtime + Ollama + optional ChromaDB (persistent volume for data)
- **Cross-platform parity** — same container image runs identically on Windows (Docker Desktop), Linux (native), and macOS (Docker Desktop). Eliminates platform-specific setup issues (pip not found, path separators, venv activation)
- **Security boundary** — containerized ProbOS can't access host filesystem, network, or processes beyond explicitly mapped volumes and ports. Essential for the public Twitch demo and any scenario with untrusted agents
- **Safe mode profile** — container startup flag (`--safe-mode`) that enables restricted config: disabled shell commands, disabled file writes outside `/sandbox`, rate limiting, SSRF protection enforced
- **Volume mounts** — `data/` (episodic memory, knowledge store, event log), `config/` (system.yaml), optional `agents/` (designed agents). Everything else is ephemeral
- **Ollama sidecar** — Ollama runs as a separate container on the same Docker network. ProbOS connects to it via `http://ollama:11434/v1`. No GPU passthrough required for CPU-only models; GPU passthrough available for CUDA-enabled hosts
- Existing: Twitch demo plan already specifies Docker-based deployment (commercial roadmap)

**Backup & Restore**

- **Episodic memory snapshots** — periodic ChromaDB backup to disk or cloud storage; restore from snapshot on corruption or migration
- **System state export** — export trust scores, Hebbian weights, agent registry, and config as a portable snapshot for migration between instances
- **Point-in-time recovery** — roll back episodic memory to a known-good state after bad dream consolidation or corrupted imports

**CI/CD Pipeline**

- **GitHub Actions test suite** — run full pytest suite (1700+ tests) on every PR and push to main
- **Vitest for HXI** — run frontend tests alongside Python tests
- **Quality gates** — block merge if tests fail, lint errors, or type check issues
- **Automated release** — tag-based releases with changelog generation from commit history
- Existing: GitHub Actions for docs deployment to probos.dev (built)

**Performance & Load Testing**

- **Benchmarks** — reproducible performance baselines for DAG execution, consensus rounds, LLM latency, and intent routing throughput
- **Load simulation** — synthetic concurrent user workloads to identify scaling bottlenecks before production
- **Regression detection** — CI compares benchmark results against baselines, flags performance regressions on PRs

**LLM Resilience — Graceful Degradation**

- **Provider failover** — if the primary LLM provider is down or rate-limited, fall back to a secondary provider (e.g., OpenAI → Anthropic → local model)
- **Cached response mode** — when all providers are unavailable, serve cached responses from the decision cache for previously-seen patterns
- **Degraded operation** — agents that don't require LLM calls (HeartbeatAgents, mesh agents) continue operating; cognitive agents queue work until LLM access is restored
- **Circuit breaker** — after N consecutive LLM failures, stop retrying and notify the Captain rather than burning through rate limits
- **Health indicator** — LLM provider status surfaced through Vitals Monitor and HXI

**Observability Export**

- **OpenTelemetry integration** — structured traces for intent routing, DAG execution, consensus rounds, and LLM calls
- **Prometheus metrics** — agent trust scores, pool utilization, Hebbian weights, dream consolidation rates, LLM latency/cost exposed as scrapeable metrics
- **Grafana dashboards** — pre-built dashboards for system health, agent performance, and cost tracking
- **Log aggregation** — structured JSON logging with correlation IDs for tracing a user request through decomposition → routing → execution → reflection
- Existing: Python logging throughout, HXI real-time visualization (built)

**Storage Abstraction Layer**

ProbOS currently uses aiosqlite (SQLite) for event log and episodic memory, and ChromaDB for vector storage. Both are ideal for local-first, single-ship deployment (zero config, embedded, pip install). For enterprise and cloud deployment, swappable backends are needed:

- **`StorageBackend` ABC** — abstract interface for relational/event storage operations (write event, query events, store episode, recall episodes)
- **`SQLiteBackend`** — default implementation wrapping current aiosqlite usage. Remains the zero-config default for OSS
- **Future backends** — PostgreSQL, etc. implemented as drop-in replacements behind the same interface
- **Migration path** — existing `EventLog` and `EpisodicMemory` classes code against the ABC, not raw aiosqlite. Backend selected via config
- SQLite is proven for single-node: zero config, WAL mode handles modest concurrency, file-based backup. The abstraction exists so cloud/enterprise can swap without changing agent code

**Vector Store Abstraction Layer**

ChromaDB is the right default for OSS (embedded, zero config, works offline), but enterprise/cloud needs backends with clustering, replication, and multi-tenant isolation:

- **`VectorStore` ABC** — abstract interface for vector operations (add, query, get, delete, count). Small surface — ~50 lines
- **`ChromaDBBackend`** — default implementation wrapping current ChromaDB usage. Remains the zero-config default for OSS
- **Future backends** — pgvector, Qdrant, Pinecone implemented as drop-in replacements behind the same interface
- **Migration path** — existing `KnowledgeStore` and `EpisodicMemory` (vector side) code against the ABC, not raw ChromaDB API. Backend selected via config
- Key insight: PostgreSQL + pgvector could serve as the single enterprise backend for both relational and vector storage, reducing operational complexity

**P1 Performance Optimizations (deferred from AD-289)**

- **Pool health check caching** — cache healthy_agents list with short TTL, invalidate on agent state change
- **WebSocket delta updates** — send state deltas instead of full snapshots, throttle event broadcast rate (batch within 100ms window)
- **Event log write batching** — batch SQLite commits (flush every 100ms or 10 events), enable WAL mode
- **Episodic memory query optimization** — add timestamp index to ChromaDB collection, cache recent episodes with TTL

**Decision Cache Persistence (deferred from AD-272)**

- Persist CognitiveAgent decision caches to KnowledgeStore for warm boot — returning users get instant responses for previously-seen patterns
- Feedback-driven cache eviction: `/feedback bad` invalidates cached decisions for involved agents, preventing stale bad judgments from persisting

---

### Operations Team (Phase 33)

*"Rerouting power to forward shields."*

Formalize resource management and system coordination as an agent pool.

- **Resource Allocator** — workload balancing across pools, demand prediction, capacity planning
- **Scheduler** — task prioritization, queue management, deadline enforcement (extends Phase 24c TaskScheduler)
- **Coordinator** — cross-team orchestration during high-load or emergency events
- **Response-Time Scaling** (deferred from Phase 8) — latency-aware pool scaling. Instrument `broadcast()` with per-intent latency tracking, scale up pools where response times exceed SLA thresholds
- **LLM Cost Tracker** — per-agent, per-intent, and per-DAG token usage accounting. Budget caps (daily/monthly), cost attribution via Shapley (which agents are expensive vs. valuable), per-workflow cost breakdowns for end-to-end visibility, alerts when spend exceeds thresholds. Provides the data foundation for commercial ROI analytics. Note: accurate cost attribution will require a proper tokenizer library (e.g., `tiktoken` for OpenAI models, model-specific tokenizers for others) — current `len(content) // 4` estimation is insufficient for billing-grade accuracy
- Existing: PoolScaler (built), TaskScheduler (Phase 24c roadmap), IntentBus demand tracking (built)

**Crew Mailbox — Direct Agent-to-Agent Messaging**

*Inspired by Claude Code Agent Teams' inter-agent mailbox.*

Currently ProbOS agents communicate only via the intent bus (broadcast to pools) or consensus (voting). There is no way for one agent to send a targeted message to a specific agent. This forces all coordination through the Decomposer, creating a bottleneck.

- **`CrewMailbox` service** — registered on the runtime, agents send/receive typed messages by agent ID
- **Use case: Architect↔Builder clarification** — during a build, the Builder encounters ambiguity in the BuildSpec and asks the Architect directly ("Which method signature should I use?") without routing through the Decomposer or requiring Captain intervention
- **Use case: Medical↔Engineering handoff** — Diagnostician identifies a performance anomaly and messages the relevant Engineering agent directly with diagnostic context
- **Message types** — `clarification_request`, `status_update`, `finding_report`, `handoff` (with typed payloads)
- **Delivery model** — async mailbox (not synchronous RPC). Recipient processes messages in its next `perceive()` cycle. Unread messages expire after configurable TTL
- **Trust-gated** — agents can only message agents they have positive trust scores with (prevents spam/abuse in federated scenarios)
- **Audit trail** — all messages logged to episodic memory for post-hoc analysis

**Self-Claiming Task Queue**

*Inspired by Claude Code Agent Teams' shared task list with self-claim.*

Currently ProbOS DAGExecutor assigns work centrally — the Decomposer decomposes, the executor dispatches. Self-claiming adds a complementary pattern where agents pull work from a shared queue based on their capabilities and availability.

- **`TaskQueue` service** — shared queue of pending work items, visible to all agents in a pool
- **Claim protocol** — agents inspect the queue during idle cycles, claim tasks matching their `_handled_intents`, file-lock or atomic CAS prevents double-claim
- **Use case: parallel builds** — multiple BuildSpecs queued, multiple Builder instances (pool scaled) each claim one and work independently
- **Use case: investigation sweep** — Science team agents self-claim codebase analysis tasks from a queue rather than having each assigned individually
- **Task dependencies** — tasks can declare `depends_on` (other task IDs). Dependent tasks remain blocked until prerequisites complete. Automatic unblocking on dependency completion
- **Complements DAGExecutor** — DAGExecutor handles structured decomposition (query → sub-tasks → aggregate). TaskQueue handles unstructured work pools where any capable agent can contribute

**Competing Hypotheses / Adversarial Investigation**

*Inspired by Claude Code Agent Teams' "spawn agents with competing theories, have them debate" pattern.*

ProbOS has red team agents for adversarial verification, but not a structured pattern where multiple agents explore competing theories and actively try to disprove each other's findings before converging.

- **Investigation Team pattern** — spawn N agents (Science team) with different hypotheses about the same problem. Each agent investigates independently, then agents exchange findings and actively challenge each other
- **Debate protocol** — after investigation phase, agents enter a structured debate: present evidence → challenge claims → rebut → converge. Dissenting positions recorded, not suppressed
- **Convergence scoring** — use trust-weighted voting to identify the hypothesis with the strongest evidence. Bayesian update on agent trust based on whether their hypothesis was validated
- **Use case: root cause analysis** — when a system anomaly occurs, spawn 3 investigators with different theories. The survivor hypothesis drives the fix
- **Use case: design review** — Architect proposes, multiple reviewers critique from different angles (security, performance, maintainability), synthesize into a stronger proposal
- **Quality gate hook** — upon convergence, the winning hypothesis must pass a verification step before being accepted (similar to Claude Code's `TaskCompleted` hook pattern)

**Bridge Alerts — Proactive Captain Notifications**

*"Captain, sensors detect an anomaly in the aft section."*

ProbOS monitors everything internally — behavioral anomalies, emergent patterns, trust shifts, confidence degradation — but never surfaces these findings to the Captain unless asked. The ship should alert its Captain to significant events proactively, not wait to be queried.

- **Alert categories** — `trust_shift` (agent trust changed significantly), `confidence_degradation` (agent dropped below threshold), `emergent_pattern` (EmergentDetector found something), `behavioral_anomaly` (BehavioralMonitor flagged unusual behavior), `capability_gap` (new capability requested but not available), `system_health` (resource pressure, high error rate)
- **Severity levels** — `info` (logged, Captain sees on next status check), `advisory` (pushed to HXI chat as a system message), `alert` (pushed with sound/visual indicator in HXI)
- **Rate limiting** — alerts are batched and deduplicated over a configurable window (default 60s) to prevent alert fatigue. "Agent X confidence dropped" appears once, not 10 times as confidence ticks down
- **Smart suppression** — don't alert on known transient states (agent rebuilding, dream cycle in progress, startup warm-up period)
- **Bridge Alert panel** — new section in HXI showing recent alerts with dismiss/acknowledge
- **Integration points** — BehavioralMonitor → Bridge Alerts, EmergentDetector → Bridge Alerts, TrustNetwork → Bridge Alerts (on significant trust events), EscalationManager → Bridge Alerts (on timeout/failure)
- **Captain's preference** — respects Adaptive Communication Style settings for alert verbosity

**File Ownership Registry**

*Inspired by Claude Code Agent Teams' "avoid file conflicts — each teammate owns different files" pattern.*

When ProbOS runs multiple builds or modifications in parallel, two agents editing the same file leads to overwrites or merge conflicts.

- **`FileOwnership` service** — tracks which agent currently "owns" (is modifying) which files
- **Claim-before-edit** — agents must claim file ownership before writing. Claim fails if another agent already owns the file
- **Automatic release** — ownership released when the owning task completes (success or failure)
- **Conflict resolution** — if two agents need the same file, the Coordinator mediates: sequential ordering, or one agent rolls back and waits
- **Integration with Builder** — `execute_approved_build()` claims all target files before writing, releases on completion
- **Extends `_background_tasks` (AD-326)** — file ownership tracked alongside task lifecycle

---

### Mission Control — Agent Activity Dashboard (Phase 34)

*"Captain on the bridge — all stations reporting."*

The UX layer that gives the Captain full visibility into what every agent is doing, in real time. Today, cognitive agents (Architect, Builder) work in a black box — the user triggers `/design` or `/build` and waits for a result or failure with no insight into progress. Mission Control replaces that with a live operational dashboard where the Captain can see every active task, track step-by-step progress, respond to agent requests, and manage the crew's workload at a glance.

Inspired by: GitHub Copilot's task list, Kanban boards (Trello/Linear), mission control dashboards (NASA MCC).

**AD-316: AgentTask Data Model + Progress Events**

The foundational primitive that everything else renders from:

- `AgentTask` dataclass: agent_id, agent_type, team, task_type (design/build/query/skill), prompt (original request text), started_at, steps (list of `TaskStep` with label/status/duration), requires_action flag, action_type (approve/review/respond/null)
- `TaskStep` dataclass: label, status (pending/in_progress/done/failed), started_at, duration_ms
- `TaskTracker` service on the runtime — agents register tasks, emit step updates, mark completion
- Architect `perceive()` emits real progress events at each layer: "Selecting relevant files...", "Reading 8 files (2,400 lines)...", "Analyzing callers and tests...", "Generating proposal via Opus..."
- Builder emits: "Reading reference files...", "Generating code...", "Writing files...", "Running tests..."
- WebSocket event type `agent_task_update` streams TaskTracker state to the HXI
- Replaces the current cosmetic progress events (fired before work starts) with real events fired during work

**AD-321: Activity Drawer (React)**

A slide-out panel from the right edge of the chat:

- Three sections: **Active** (agents currently working, with live step progress), **Needs Attention** (agents waiting for human input — approve/reject/respond), **Recent** (completed tasks with outcomes)
- Each item is a compact card: agent type icon, task title (truncated prompt), team color badge, elapsed time
- Click card to expand: full prompt, step-by-step checklist with timings, action buttons if applicable
- Badge count on the drawer toggle button for "Needs Attention" items
- Subscribes to `agent_task_update` WebSocket events for live updates

**AD-322: Kanban Board View**

Full mission control as a dedicated view (route or tab):

- Columns: `Queued` → `Working` → `Needs Review` → `Done`
- Cards show: agent type icon, task title, team color, elapsed time, step progress bar
- Click card to expand into full detail panel: original prompt, step-by-step progress, file diffs (build tasks), proposal text (design tasks), action buttons (Approve / Reject / Respond)
- Cards auto-move between columns as task state changes
- Filter by team (Science, Engineering, Medical, etc.) or agent type
- "Done" column auto-archives after configurable time

**AD-323: Agent Notification Queue**

Persistent notifications that agents can emit and that persist until the Captain acknowledges:

- `AgentNotification` dataclass: agent_id, agent_type, notification_type (info/action_required/error), title, detail, action_url (link to the relevant card), created_at, acknowledged
- Notification types: "Proposal ready for review", "Build failed — 3 test failures", "Question: should this modify panels.py or create a new file?"
- Bell icon in the HXI header with unread count badge
- Notification dropdown: list of unread notifications, click to navigate to the relevant card/drawer item
- `action_required` notifications stay pinned until explicitly acknowledged or the underlying task is resolved
- Agent API: `self._runtime.notify(agent_id, title, detail, action_required=True)` — simple method any agent can call

**AD-324: Orb Hover Enhancement**

Upgrade the existing system health orb with per-agent hover preview:

- When hovering over an agent representation in the orb, show a tooltip with: current task prompt (truncated), current step label, elapsed time, progress fraction (step 3 of 5)
- Visual indicator on the orb when any agent requires Captain attention (pulsing amber)
- Click-through from orb tooltip to the Activity Drawer card for that agent

---

### Bundled Agent Reorganization (Future)

*"All hands, report to your departments."*

Bundled agents currently share a single "Bundled" pool group, but they serve different departments of the ship. "Bundled" is a **distribution label** (ships with ProbOS out of the box), not an organizational role. Future work will reassign bundled agents to their functional crew teams:

- **Communications** — TranslateAgent, SummarizerAgent
- **Science/Research** — WebSearchAgent, PageReaderAgent, NewsAgent, WeatherAgent
- **Operations** — CalculatorAgent, TodoAgent, NoteTakerAgent, SchedulerAgent

The `bundled` designation becomes agent metadata (`origin: "bundled"`) rather than a crew assignment. The pool group system and HXI clustering already support this — it's a data change, not an architectural change.

---

### Meta-Learning (Phase 28)

*"Fascinating." — The ship learns to learn.*

Move beyond per-session learning to cross-session concept formation, persistent goals, and abstract reasoning.

- **Workspace Ontology** — auto-discovered conceptual vocabulary from the user's usage patterns, stored in Knowledge Store
- **Dream Cycle Abstractions** — dreaming produces not just weight updates but abstract rules and recognized patterns
- **Session Context** — conversation history carries across sessions, decomposer resolves references to past interactions (AD-273 provides foundation)
- **Goal Management** (deferred from Phase 16) — persistent goals with progress tracking, conflict arbitration between competing goals, goal decomposition into sub-goals with dependency tracking
- Existing: Episodic memory (built), dreaming engine with three-tier model (built), conversation context (AD-273, built)

---

### Federation Hardening (Phase 29)

*Additional federation capabilities deferred from Phase 9.*

Beyond the core federation transport (ZeroMQ, gossip, intent forwarding) already built:

- **Dynamic Peer Discovery** — multicast/broadcast-based automatic node discovery on local networks, replacing manual `--config` peer lists
- **Cross-Node Episodic Memory** — federated memory queries that span multiple ProbOS instances, enabling a ship to recall experiences from allied ships
- **Cross-Node Agent Sharing** — propagate self-designed agents to federated peers (deferred from Phase 10). Agents carry their trust history and design provenance
- **Smart Capability Routing** — cost-benefit routing between federation nodes, factoring in capability scores, latency, trust, and load. Beyond the current "all peers" routing
- **Federation TLS/Authentication** — encrypted transport and node identity verification for federation channels. Required before any production multi-node deployment
- **Cluster Management** — node health monitoring, auto-restart, graceful handoff of responsibilities when a node goes down

---

### MCP Federation Adapter (Phase 29)

*A universal translator for the wider agent ecosystem.*

MCP (Model Context Protocol) is becoming the standard for inter-agent tool sharing. ProbOS supports it as a federation transport alongside ZeroMQ — connecting ProbOS to external agent frameworks, IDEs, and MCP-compatible tools without requiring them to run ProbOS.

**Inbound (MCP Server)**

- ProbOS exposes its agent capabilities as MCP tools
- MCP tool calls are translated to `IntentMessage` and dispatched through the intent bus
- MCP-originated intents go through the same governance pipeline as any federated intent: consensus, red team verification, escalation
- The MCP adapter is a transport, not a trust bypass

**Outbound (MCP Client)**

- ProbOS discovers and invokes capabilities on external MCP servers
- External tool definitions translated to `IntentDescriptor` and registered as federated capabilities
- `FederationRouter` routes intents to MCP-connected systems alongside ZeroMQ-connected ProbOS nodes
- External capabilities carry federated trust discount (same δ factor as trust transitivity)

**MCP Client Trust**

- MCP clients treated as federated peers with configurable trust
- New clients start with probationary trust (same `Beta(alpha, beta)` prior as new agents — AD-110)
- Trust updated based on outcome quality of submitted intents
- Destructive intents from MCP clients always require full consensus regardless of accumulated trust

**Transport Coexistence**

- ZeroMQ remains the primary intra-Nooplex transport (fast, binary, low-latency)
- MCP serves the tool boundary between ProbOS and the wider ecosystem
- A2A serves the agent boundary between ProbOS and external agent frameworks
- `FederationBridge` becomes transport-polymorphic: ZeroMQ, MCP, and A2A implementations behind a shared interface

---

### A2A Federation Adapter (Phase 29)

*"Hailing frequencies open — to all ships, not just ours."*

Google's Agent-to-Agent (A2A) protocol is the agent-communication complement to MCP (which is tool-communication). MCP lets agents use external tools; A2A lets agents collaborate with external agents. ProbOS supports both as federation transports.

```
External World ←→ ProbOS
─────────────────────────────────
Tools:   MCP Protocol  ←→ Intent Bus (tool calls)
Agents:  A2A Protocol  ←→ Intent Bus (agent collaboration)
Nodes:   ZeroMQ        ←→ Federation (ProbOS-to-ProbOS)
```

**Inbound (A2A Server)**

- ProbOS exposes agent capabilities as A2A-discoverable services
- External agents can send tasks to ProbOS agents via A2A task protocol
- A2A tasks are translated to `IntentMessage` and dispatched through the intent bus
- Full governance applies: consensus, red team verification, trust scoring
- ProbOS publishes an Agent Card describing available capabilities, authentication requirements, and supported modalities

**Outbound (A2A Client)**

- ProbOS discovers external agents via A2A Agent Card discovery
- External agent capabilities registered as federated agents (not tools — key distinction from MCP)
- `FederationRouter` routes intents to A2A-connected agents alongside ZeroMQ and MCP peers
- Supports A2A streaming for long-running collaborative tasks

**A2A Trust Model**

- External A2A agents treated as federated crew members with discounted trust (same δ factor as trust transitivity)
- New A2A peers start with probationary trust, same as MCP clients
- Trust updated based on task outcome quality, measured by Shapley attribution
- A2A agents never bypass consensus — they're collaborators, not privileged operators
- Agent Card metadata (publisher, version, capabilities) stored for provenance tracking

**MCP vs A2A Decision Matrix**

- Use **MCP** when: consuming a stateless capability (file read, API call, database query) — tools
- Use **A2A** when: delegating a task that requires reasoning, context, multi-step work — agents
- ProbOS agents can use both: MCP for instruments, A2A for collaboration with external crew
- Phase 26 Agent-as-Tool works internally; A2A extends the pattern across framework boundaries

---

### External AI Tools as Federated Crew (Phase 29/32)

*"Visiting officers from allied ships — each with specializations our crew lacks."*

ProbOS doesn't need to build every capability internally. External AI coding tools — Claude Code, GitHub Copilot, Cursor, future agents — can join the federation as crew members, providing capabilities by proxy. Just as Starfleet officers transfer between ships, external AI tools serve aboard the ProbOS instance under the Captain's authority and the trust network's governance.

**The Pattern: AI Tool → Federated Crew Member**

```
External AI Tool              ProbOS Federation Role
──────────────────────────────────────────────────────
Claude Code                →  Builder crew member (A2A/SDK)
GitHub Copilot Agent       →  Science crew member (MCP/API)
Cursor / Windsurf / etc.   →  Engineering crew member (A2A)
```

Each external tool is wrapped as a federated agent with:
- **Probationary trust** — starts with `Beta(1, 3)`, earns trust through verified task outcomes
- **Captain approval gate** — requests routed through the same approval pipeline as internal agents
- **Capability registration** — tool's capabilities mapped to `IntentDescriptor` entries (e.g., Copilot's semantic search → `search_code_semantic` intent)
- **Shapley attribution** — external tool contributions measured alongside internal agents for cost/value analysis
- **Consensus participation** — external tools never bypass consensus. Their outputs are verified by internal agents before acceptance

**GitHub Copilot as Federated Crew**

GitHub Copilot's coding agent brings capabilities ProbOS can access by delegation rather than reimplementation:

- **Semantic code search** — Copilot indexes the repo with embedding-based search. ProbOS dispatches "find code related to X" queries to Copilot when internal keyword search returns insufficient results. Complementary to internal CodebaseIndex: keyword (fast, exact) + semantic (meaning-based, via Copilot proxy)
- **PR creation and review** — Copilot natively creates PRs, suggests reviews, runs CI. ProbOS Builder could delegate "create PR from these changes" to Copilot rather than shelling out to `git`
- **Issue triage** — Copilot reads GitHub issues. ProbOS Architect could query Copilot for issue context when designing proposals
- **Code generation** — Copilot generates code with different model strengths (GPT-5.x). ProbOS can solicit competing implementations from Claude (via Builder) and Copilot (via federation), then use consensus to pick the best one — the "competing hypotheses" pattern applied to code generation

**Claude Code as Federated Crew** (Northstar Pipeline)

Already designed in the Northstar context. Claude Code executes build prompts, creates branches/commits, runs tests:

- **Current (manual):** Captain writes build prompt → Claude Code executes → git commit → Captain approves
- **Future (automated):** ProbOS Architect designs → BuildSpec → Claude Code (via Anthropic SDK or A2A) → PR → Captain approves
- **Medium win:** Builder Agent calls Anthropic SDK directly, bypassing full A2A protocol

**Trust Model for External AI Tools**

- All external tools start with **federated trust discount** (δ factor from trust transitivity)
- Trust builds per-tool based on task quality outcomes: did the PR pass tests? Did the code review catch real issues? Did the semantic search return relevant results?
- External tool failures degrade trust, triggering fallback to internal capabilities or escalation to Captain
- **Cost tracking** — external tools have API costs. LLM Cost Tracker (Phase 33) attributes spending per-tool alongside per-agent
- **Capability overlap resolution** — when both internal and external capabilities exist (e.g., internal CodebaseIndex + Copilot semantic search), the system routes based on: (1) trust scores, (2) historical accuracy, (3) cost, (4) latency. Hebbian routing handles this naturally

**Connection Mechanisms**

| Tool | Protocol | Adapter |
|------|----------|---------|
| Claude Code | Anthropic SDK / A2A | A2A Federation Adapter |
| GitHub Copilot | GitHub API / MCP | MCP Federation Adapter |
| Cursor / Others | A2A / MCP | Protocol-dependent |

The existing MCP and A2A adapters (Phase 29) are the connection layer. External AI tools don't require new federation protocols — they plug into the existing transport-polymorphic `FederationBridge`.

---

### Skill Manifest Format (Phase 30)

*A standard manifest for portable, publishable skills.*

Inspired by OpenClaw's declarative skill metadata. Standardizes how skills are described, discovered, and distributed — foundation for the Agent Marketplace.

- **Manifest file** (`skill.yaml`) — name, description, version, author, license, required dependencies, platform constraints, ProbOS version compatibility
- **Dependency declaration** — Python packages, system binaries, external services needed
- **Auto-installation** — skills declare their dependencies; runtime installs them on first use
- **Discovery protocol** — skills can be searched, browsed, and installed from registries
- **Testing contract** — manifest includes test commands, expected coverage, integration test requirements
- Pairs with the commercial Agent Marketplace for publishing and distribution

---

### Task Ledger (Phase 33 — Operations Team)

*Two-loop architecture for long-horizon task management.*

Inspired by Microsoft Magentic-One's Task Ledger + Progress Ledger pattern. Structured tracking for multi-step, multi-agent tasks with adaptive replanning.

- **Task Ledger** — tracks facts (confirmed), guesses (unverified), plan (ordered steps), and blockers for each active long-horizon task
- **Progress Ledger** — per-subtask tracking: assigned agent, status, output, retries, duration
- **Adaptive replanning** — when progress stalls or a subtask fails, revise the plan using updated facts and lessons learned
- Extends Phase 24c TaskScheduler from "schedule and run" to "schedule, track, and adapt"
- Integrates with Evolution Store — task outcomes feed back as lessons for future planning

---

### Tool Layer — Instruments (Phase 25b)

*"Tricorder readings, Captain."*

A lightweight callable abstraction for operations that don't need full agent lifecycle. Tools are the ship's instruments — trusted, shared, and purpose-built. Any authorized crew member (agent) can pick up a tricorder and use it without filing a request through the chain of command.

**Why this tier exists:**

Currently, reading a file routes through the full agent lifecycle: Hebbian routing → trust scoring → consensus → Shapley attribution. That's a committee meeting to pick up a tricorder. Tools provide a direct-call path for operations that need reliability but not deliberation.

**`Tool` base class:**

```python
class Tool:
    name: str                           # "file_reader", "http_fetch", "stripe_api"
    description: str                    # Human-readable purpose
    input_schema: dict                  # JSON schema for typed inputs
    output_schema: dict                 # JSON schema for typed outputs
    trust_score: float                  # Tool-level reliability tracking
    requires_approval: bool = False     # Some tools (shell, delete) need Captain approval

    async def execute(self, **kwargs) -> ToolResult
```

**`ToolRegistry`:**

- Central registry of available tools, analogous to agent Registry
- `register(tool)`, `get(name)`, `list()`, `search(capability)`
- Any CognitiveAgent can discover and invoke registered tools via `self.use_tool(name, **kwargs)`
- Tool results include execution metadata (duration, success, error) for trust tracking

**Tool Trust (lightweight):**

- Tools carry a simple success/failure trust score (same Beta distribution as agents)
- Trust is updated per-call but does NOT feed into Hebbian routing or Shapley attribution
- Below-threshold trust triggers a warning to the using agent, not a consensus vote
- Captain can disable untrusted tools globally

**Migration Path:**

Current mesh agents that are pure function wrappers can be optionally demoted to tools:

| Current Agent | Tool Equivalent | Governance Change |
|---------------|----------------|-------------------|
| FileReaderAgent | `file_reader` tool | Direct call, no consensus |
| FileWriterAgent | `file_writer` tool | Requires approval for write paths |
| HttpFetchAgent | `http_fetch` tool | SSRF validation stays, no consensus |
| ShellCommandAgent | `shell_command` tool | Always requires Captain approval |
| DirectoryListAgent | `directory_list` tool | Direct call, no consensus |
| FileSearchAgent | `file_search` tool | Direct call, no consensus |

Migration is optional and gradual — agents remain as fallback. Tools supplement, not replace.

**MCP Compatibility:**

- External MCP tools register as ProbOS tools automatically (with probationary trust)
- ProbOS tools are exposed as MCP tools to external systems via the MCP adapter (Phase 29)
- `Tool.input_schema` / `Tool.output_schema` map directly to MCP tool schemas
- This makes the MCP adapter implementation straightforward: MCP tool ↔ ProbOS tool is 1:1

**External Integration Pattern:**

Third-party tools (Stripe, GitHub, database, etc.) follow the same pattern:

```python
class StripeTool(Tool):
    name = "stripe_checkout"
    description = "Create a Stripe checkout session"
    input_schema = {"amount": "int", "currency": "str", "description": "str"}
    requires_approval = True  # financial operations need Captain approval
```

No need to build a full StripeAgent with intent handling, Hebbian routing, and Shapley attribution — just a validated instrument.

---

### Agent-as-Tool Invocation (Phase 26)

*Explicit agent-to-agent capability consumption.*

Allows one agent to explicitly invoke another agent's capability as a typed function call, complementing the implicit collaboration that already happens through the intent bus. Builds on the Tool Layer (Phase 25b) — agents can be wrapped as tools for direct invocation.

- **`AgentTool` wrapper** — any agent can be consumed as a tool by another agent with typed input/output contracts
- Intent bus remains the primary collaboration mechanism for loosely-coupled work
- AgentTool is for tightly-coupled cases where one agent always needs another's output (e.g., Diagnostician consumes Vitals Monitor metrics)
- Trust and consensus still apply — wrapping doesn't bypass governance (unlike plain tools, AgentTools are full agents underneath)
- Natural fit for Phase 26 Inter-Agent Deliberation

**Interactive Execution Mode (deferred from Phase 16)**

- Pause, inject, or redirect a running DAG mid-flight during execution
- Human can add constraints, modify node parameters, or insert new nodes into an active plan
- CollaborationEvent type for HXI visualization of human-agent co-editing
- Foundation for real-time human-agent pair programming on complex tasks

---

### Self-Improvement Pipeline (Phase 30)

*The mechanism that allows the ship to upgrade itself — with the Captain's approval.*

The infrastructure for a closed-loop improvement cycle: discover capabilities, evaluate fit, propose changes, validate results, and learn from outcomes.

**Stage Contracts (Typed Agent Handoffs)**

- Formal I/O specifications for inter-agent task handoffs
- Each contract declares: input artifacts, output artifacts, definition of done, error codes, max retries
- Enables reliable multi-step workflows where agents hand off work to each other with clear expectations

**Capability Proposal Format**

- Typed schema for "here's what was found, why it matters, and how it fits"
- Fields: source (repo/paper/API), relevance score, architectural fit assessment, integration effort estimate, dependency analysis, license compatibility
- Proposals flow through a review queue with approve/reject/modify actions

**Human Approval Gate**

- Stage-gate mechanism that pauses automated pipelines for Captain review
- Approval queue surfaced via HXI, shell, or API
- Supports approve, reject, or modify-and-resubmit workflows
- Audit trail of all decisions for traceability

**QA Agent Pool**

- Automated validation agents that go beyond pytest
- Behavioral testing: does the new capability actually improve the metric it claimed to?
- Regression detection: did anything break?
- Performance benchmarking: latency, memory, throughput before and after
- Shapley scoring to measure marginal contribution of new capabilities

**Evolution Store**

- Append-only store of lessons learned from capability integrations (successes, failures, and why)
- Time-decayed retrieval: recent lessons weighted higher, stale lessons fade
- Fed into episodic memory and dream consolidation for cross-session learning
- Future Science team agents query this store to avoid repeating past mistakes

**PIVOT/REFINE Decision Loops**

- Autonomous decision points in multi-step workflows: proceed, refine (tweak and retry), or pivot (abandon and try a different approach)
- Artifact versioning on rollback: previous work is preserved, not overwritten
- Hard iteration caps to prevent infinite loops

**Capability Injection (Adapter Bundle)**

- Agents declare needed capabilities (search, store, fetch, notify) via typed Protocol interfaces
- Runtime injects concrete implementations at startup
- Swappable providers without changing agent code (e.g., swap OpenAlex for Semantic Scholar)
- Recording stubs for testing: log calls without side effects, verify agent behavior in isolation

**Multi-Layer Verification (Anti-Hallucination)**

- Graduated verification of agent-produced claims against external sources
- Multiple verification layers, each catching what the previous missed (e.g., direct ID lookup -> API search -> fuzzy title match -> LLM relevance scoring)
- Classifications: VERIFIED (high confidence), SUSPICIOUS (needs review), HALLUCINATED (fabricated), SKIPPED (unverifiable)
- Extends the trust network from binary success/fail to graduated confidence scoring
- Applied to research findings, generated references, claimed capabilities, and factual assertions

**Agent Versioning + Shadow Deployment (deferred from Phase 14c)**

- Track version history of designed agents — each modification produces a new version with provenance chain
- Shadow deployment: run new agent versions alongside existing ones, compare performance on identical intents via Shapley scoring, promote or rollback based on observed metrics
- Depends on persistent agent identity (AD-177, built)

**Vibe Agent Creation (AD-271, built)**

- Human-guided agent design: user provides natural language guidance ("make it focus on security" or "it should be conservative") before generation
- An alternative mode alongside fully automated self-mod — the Captain can shape agent design without writing code
- Extends the Human Approval Gate from binary approve/reject to collaborative design

**Git-Backed Agent Persistence**

Self-designed agents currently live in the evolution store (KnowledgeStore) as runtime artifacts. To become permanent crew members, they need to be version-controlled:

- **Write-to-disk serialization** — promote approved agents from evolution store to `src/probos/agents/designed/` as clean `.py` files
- **Git integration** — ProbOS creates a branch, commits the agent file, opens a PR. ProbOS becomes a git contributor (`Co-Authored-By: ProbOS <probos@probos.dev>`)
- **Code quality gate** — lint, test, security scan (red team), and behavioral validation before commit
- **Provenance chain** — each agent file carries metadata: which conversation spawned it, design intent, trust score earned, Shapley contribution, version history
- **Rollback** — if an agent degrades post-promotion, revert the commit and demote back to evolution store
- **User-owned repos** — each ProbOS user's designed agents sync to their own git repo (local or GitHub). The user chooses private or public visibility

---

### Agent Sharing Ecosystem (Future)

*"The Federation shares its finest officers."*

When users make their agent repos public, a decentralized agent-sharing ecosystem emerges — like P2P file sharing but for ProbOS agents, with GitHub as the transport layer.

---

### Multi-User / Multi-Tenant (Future)

*"Multiple Captains on the bridge."*

Currently ProbOS assumes a single Captain — one human operator with full authority. Multi-user support enables shared ProbOS instances where multiple users connect simultaneously without interfering with each other.

- **Session isolation** — each connected user gets their own conversation context, decomposer state, and episodic memory namespace
- **User identity** — authenticated users via channel adapters (Discord user ID, API key, SSO token) mapped to ProbOS user profiles
- **Permission model** — role-based access: Captain (full authority, approval gate), Officer (can issue intents, no self-mod approval), Observer (read-only, monitor HXI)
- **Approval routing** — self-mod and destructive intents route to the Captain regardless of which user triggered them
- **Per-user trust context** — agents may have different trust scores per user (optional, advanced)
- **Shared resources** — all users share the same agent pools, knowledge store, and trust network, but conversation state is isolated
- Foundation for team deployments and the commercial multi-tenant hosting model

**Discovery**

- GitHub repos tagged with `probos-agent` topic are discoverable by any ProbOS instance
- Discovery agent (Science team) periodically indexes public agent repos via GitHub API search
- Agent catalog: name, description, trust score history, design provenance, compatibility info
- No central registry needed — GitHub is the index

**Import with Review**

- Captain browses discovered agents, previews trust history, provenance chain, and source code
- Import creates a branch in the user's local repo with the external agent
- Red team scans imported agent source for security issues (prompt injection, data exfiltration, sandbox escapes)
- QA pool runs behavioral tests before the agent joins the crew
- Imported agents start with a low trust score and earn trust through performance (same onboarding as self-designed agents)

**Trust and Provenance**

- Agents carry a signed provenance chain: who designed them (human or ProbOS), which instance, what version
- Trust scores from the source instance are visible but not inherited — each ship builds its own trust independently
- Community trust signals: how many instances have imported this agent, aggregate success/failure rates
- License compatibility checks: agents inherit the license of their source repo

**Sharing Back**

- If a user improves an imported agent, they can contribute the improvement back to the source repo via PR
- ProbOS-to-ProbOS collaboration: one ship's agent evolves and the improvement propagates across the fleet
- Opt-in only — no automatic propagation, every change goes through Captain approval

---

## Bug Tracker

*"Captain, we've detected an anomaly in Deck 7."*

Bugs found during development or testing. Squash as found when possible; queue here when multiple bugs need coordinated fixing. Numbered as BF-NNN (Bug Fix).

| BF | Summary | Severity | Status |
|----|---------|----------|--------|
| BF-001 | Self-mod proposal on knowledge questions | Medium | Open |
| BF-002 | Agent orbs escape pool group spheres | High | Open |

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

!!! info "Want to contribute?"
    See the [Contributing guide](contributing.md) for how to get involved.
