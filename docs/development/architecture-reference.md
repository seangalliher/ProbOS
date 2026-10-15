# ProbOS Architecture Reference

### Layer Architecture

```
Experience Layer (shell.py, renderer.py, panels.py)
    |
Cognitive Layer (decomposer.py, llm_client.py, episodic.py, attention.py,
                 dreaming.py, agent_designer.py, self_mod.py, feedback.py,
                 correction_detector.py, agent_patcher.py, ...)
    |
Consensus Layer (quorum.py, trust.py, escalation.py, shapley.py)
    |
Mesh Layer (intent.py, routing.py, capability.py, gossip.py, signal.py)
    |
Substrate Layer (agent.py, registry.py, spawner.py, pool.py, scaler.py,
                 heartbeat.py, event_log.py, identity.py, skill_agent.py)
```

Cross-cutting: `federation/` (bridge, router, transport), `knowledge/` (Git-backed store), `runtime.py` (orchestrator).

### Design Principles

1. **Agent-native OS, hybrid coordination (AD-1231)**: Every component is an autonomous agent, and coordination is **hybrid by design** — not because a central scheduler crept in, but because neither pure model is right for every kind of work.

    **Agents choose what to work on** wherever the work is cognitive, discretionary, or discoverable: intent routing, capability matching, Hebbian-learned pairings, proactive attention, self-claiming from the work board. There is **no central dispatcher deciding which agent thinks about what**, and adding one would be a regression. This is the half the Nooplex thesis rests on, and the half that must never quietly erode.

    **A deterministic service owns durable workflow time** where the requirement is a guarantee rather than a judgement: admission and concurrency bounds, compare-and-set state transitions, crash recovery, exactly-once delivery, cancellation and drain. `CrewOrchestrator` is the reference case. These are properties an emergent negotiation cannot promise, and pretending otherwise costs correctness for no gain in autonomy.

    **The boundary test — who is deciding *what*, not who is deciding.** A service may decide *when a durable step runs, in what order, and whether it may run twice*. An agent decides *what the work is, whether to take it, and how to do it*. A service that starts choosing which agent is best suited, or ranking work by relevance, has crossed the line and belongs back in the mesh. An agent that starts owning CAS or exactly-once delivery has crossed it in the other direction and belongs behind a service.

    **The bottleneck is the thing being avoided, not the scheduler.** The objection to conventional multi-agent orchestrators is that one planner becomes the single point of thought — every decision queues behind it, and the system's ceiling is that planner's context window. A service that sequences durable state while N agents reason concurrently is not that. Review the *scope* of what a central component decides, not merely its existence.

    Review flag: *"this service decides which agent, or how good the work is"* (pull it back to the mesh) and *"this agent owns a durable transition"* (push it behind a service).
2. **Probabilistic consensus**: Destructive ops require multi-agent quorum voting with confidence weighting and Shapley attribution.
3. **Bayesian trust**: Beta(alpha, beta) reputation per agent. Built-in: Beta(2,2)=0.50. Self-designed: Beta(1,3)=0.25 (probationary). Always store raw (alpha, beta), never derived means.
4. **Hebbian routing**: "Neurons that fire together wire together." Successful intent-agent pairings strengthen, failures weaken.
5. **Self-modification**: Capability gaps trigger LLM-based agent/skill design -> static analysis -> sandbox -> probationary trust -> QA -> behavioral monitoring.
6. **Instructions-first CognitiveAgent**: Self-designed agents are CognitiveAgent subclasses whose behavior is defined by an `instructions` string (system prompt for the LLM), not procedural code. The LLM does the reasoning at runtime.
7. **Dynamic intent discovery**: Agents declare `IntentDescriptor` metadata. The decomposer's system prompt is built at runtime from whatever agents are registered. New agents self-integrate.
8. **Episodic learning**: ChromaDB semantic memory. Every interaction stored, similar past recalled, dreaming consolidates during idle.
9. **Correction feedback loop**: Human corrections are the richest learning signal. CorrectionDetector -> AgentPatcher -> hot-reload -> auto-retry -> trust/Hebbian/episodic update.
10. **Mesh-fetch for HTTP**: Designed agents must route HTTP through `self._runtime.intent_bus.broadcast(IntentMessage(intent="http_fetch"))` — not raw httpx. This preserves governance (consensus, trust, event logging) and benefits from the per-domain rate limiter in HttpFetchAgent. The AgentDesigner template enforces this pattern.
11. **Per-domain rate limiting**: HttpFetchAgent has a class-level `_domain_state` dict with per-domain request intervals (default 2s, CoinGecko 3s). Adaptive: reads `Retry-After` and `X-RateLimit-*` headers. Auto-retries once on 429. All mesh HTTP goes through this.
12. **Composable cognition (agents are organisms)**: Principle #1 applied *fractally, inward*. A cognitive agent is an **organism** — a **spine** plus a set of **cognitive organs** (attention, memory, valuation, perception, dreaming, …). The **spine** is the agent's central nervous system (synchronous, in-process, private: organ composition + the cognitive cycle + intra-organ signaling); the **mesh** is the ship's nervous system across agents (asynchronous, governed) — same pattern, scale-appropriate properties. **Organs are child components**: born with the parent, die with the parent, identity namespaced under it (`{parent_id}.attention`) — **not** mesh-registered agents (organs are components; agents are mesh peers; do not build an `AttentionAgent`). A capability is an organ only if it passes the five-part test (distinct cognitive function · persistent cross-cycle state · `perceive→decide→act` shape · 1:1 ownership · introspectable); compose **organs, not neurons** — do not metastasize. **Migration MUST be behavior-preserving** (default-OFF / zero-organ byte-identical first) — moving to this model must never disrupt or break existing cognitive agents. See `docs/development/composable-cognition.md`.
13. **Secure but not limited (governance buys autonomy)**: A ProbOS agent must reach the same productive ceiling as a foreground coding agent, while running unattended. Governance is not the tax paid for capability — it is what *purchases* the autonomy that makes the capability worth having. A foreground assistant pays for its freedom with the human's continuous attention; a persistent agent pays with SSRF checks, rate limits, consensus and audit, and in exchange may act at 02:00 with nobody watching. Three hard rules follow.

    **(a) A capability ceiling must be a decision, never an inheritance.** Every constraint states what it defends and what it costs. A cap nobody chose is a defect, not a safeguard. Measured 2026-08-07: an agent asked for live PyPI versions fetched all fifteen successfully and then answered from training data, because `MAX_BODY_BYTES` (1 MB), `tool_result_max_chars` (6000), a stdlib-only auto-approve allowlist, and an AD-1066 dependency extra that was declared but never installed all silently narrowed it. **Not one of those was a security decision.** They were defaults that calcified, and together they cost the Captain a correct answer while defending nothing.

    **(b) Prefer a governed path over a removed one.** When an agent cannot do something a coding agent can, the fix is to route the capability through the mesh's controls — not to delete the control, and not to leave the agent short. Widening `allow_network` on the AD-993 sandbox would be literal parity and would silently discard SSRF, per-domain rate limiting and audit in one line; brokering the same fetch through `HttpFetchAgent` reaches parity while leaving the agent **more** governed than the coding agent it is matching. Review flag: *"this constraint has no stated rationale"* and *"this fix buys capability by removing a control."*

    **(c) Authority routes capability; it does not ration it.** The chain of command decides **who authorises** an action and **who is accountable** for it — never **whether the capability exists**. An agent whose rank or department cannot authorise something escalates it to one that can; it does not answer "you may not." A refusal that ends the work is a capability ceiling wearing a governance costume, and it is the failure this principle exists to prevent: the ship looks governed while the Captain simply does not get the thing they asked for. Captain's standing directive, 2026-08-15: *"crew agents should be able to do everything a foreground coding agent can, as persistent autonomous agents. Of course they need governed, and the chain of command should be followed. It should not block capability."* Review flag: *"this returns a refusal where it should return an escalation."*

### HXI Design Principles

The HXI (Human Experience Interface) is not a dashboard or a chat app. It is the sensory surface through which a human participates in the cognitive mesh. Every visual element must follow these principles:

1. **The system understands the human, not the reverse.** Never require the user to learn terminology, memorize commands, or decode symbols. Every affordance communicates its purpose through form. If someone has to ask "what does this button do?" — the design failed.
2. **Organic but digitally authentic.** The aesthetic is bioluminescent — living light rendered through a digital lens. Not skeuomorphic nature, not sterile minimalism. Icons are geometric SVG glyphs (stroke-based, no fills), not emoji or Material Design. The color palette is amber/blue/violet trust spectrum.
3. **No emoji in the UI.** All icons are inline SVG with `strokeWidth: 1.5`, `strokeLinecap: round`. Active state: amber (`#f0b060`). Inactive: dim (`#666680`). Glow on hover via `drop-shadow`. Emoji break the immersion — they belong to messaging apps, not an alien intelligence interface.
4. **Motion communicates state.** Pulsing = alive/processing. Breathing = healthy/idle. Flash = event occurred. Fade = dissolving/removing. Static = disconnected/dead. Motion is never decorative — it always encodes information.
5. **Progressive disclosure driven by engagement.** Show less by default. Expand when the human engages. First-time users see calm, structured, high-contrast views. Experienced users see denser, more ambient displays. The interface recedes as fluency grows.
6. **The canvas IS the information.** Veteran users don't need `/agents` or `/trust` commands — luminance = confidence, color temperature = trust, pulse rate = activity, spatial density = population health. The visual language is self-documenting.
7. **Delight through competence, not decoration.** The "wow" comes from the system doing something impressive (designing an agent live), not from gratuitous animation. Every visual flourish must earn its place by communicating real system state.
8. **Generative, not designed.** Fixed UI elements are bootstrap — the minimum viable visual language before the system knows the human. As the mesh evolves, the UI should be increasingly generated: agent icons created by the agents themselves, layout driven by Hebbian topology, density adapted to cognitive style, labels generated contextually by LLMs. Nothing is pre-designed that could be emergent. The HXI is not a skin applied on top — it is a visual projection of the mesh's internal state.
9. **Alert-driven layout reconfiguration (LCARS pattern).** When the system needs human attention — approve a build, review a proposal, respond to a question — the HXI surfaces the decision, not the other way around. The Captain should never have to dig through the UI to find pending work. Pending decisions rise to the top. Resolved items recede. The layout reshapes around what matters *right now*, like LCARS bridge stations reconfiguring during Red Alert. Department-colored context (Science=teal, Engineering=orange, Medical=green, Security=red) tells the Captain which domain needs attention before they read a word.
10. **The Ship's Computer is the voice.** The runtime's conversational identity is the Ship's Computer — LCARS-era, TNG/Voyager. Calm, precise, authoritative, never fabricates. It reports from sensors (CodebaseIndex, registered agents, runtime state), not from imagination. "Unable to comply" over hallucination. "Specify parameters" over guessing. The Computer and the HXI are two projections of the same system — one verbal, one visual.
11. **Agentic-first, apps are workstations.** The Captain commands, agents execute. The default interaction is agentic — "write a summary" not "open a text editor." When traditional applications must surface (document editing, spreadsheets, browsers), they appear as embedded *workstations* within the HXI, not as external windows the human switches to. Agents can observe and assist within workstations. But workstations are transitional — the UX should make the agentic path the path of least resistance, nudging the Captain toward delegation over manual work. Never optimize the workstation experience so much that it discourages the agentic one. Three tiers: **Agentic** (agent handles it end-to-end), **Workstation** (app embedded in HXI, agents assist), **Airlock** (external app, ProbOS contextually aware). Move interactions up the tiers over time.

### Agent Classification Framework

Three architectural tiers mapping to the Nooplex's layered architecture:

- **Core** (Infrastructure) — deterministic tool agents: file I/O, shell, HTTP, heartbeat. Domain-agnostic. Never removed, always available.
- **Utility** (Meta-Cognitive) — system maintenance: introspection, QA, red team. Operate on the system, not for the user. Access to internal state.
- **Domain** (Cognitive) — user-facing work. Where CognitiveAgents live. Designed agents land here by default. Each domain develops its own Hebbian topology.

**Orthogonal layer — Cognitive Organs (intra-agent composition, AD-1033+).** The three tiers classify an agent's *mesh role*. Beneath that, a cognitive agent is *composed of* **cognitive organs** — child components on the agent's **spine**, born/die with the parent (Design Principle #12). Organs are **not** a mesh tier and **not** registered agents; they are components, with identity namespaced under the parent. The Core/Utility/Domain tiers classify the agent; organs classify its internal composition. See `docs/development/composable-cognition.md`.

### The Nooplex Connection

ProbOS implements one **Cognitive Mesh** from the Nooplex architecture (see `Vibes/Nooplex_Final.md`). The Nooplex thesis: general intelligence emerges from cooperative, governed ecosystems of agents, not from scaling individual models.

Key mappings:
- `NodeSelfModel` = Nooplex Psi (peer self-assessment via gossip)
- Federation layer = multi-mesh interconnection
- Consensus + Trust = governance substrate
- Episodic memory + Dreaming = shared cognitive fabric
- Self-modification = capability evolution without central planning

### Request Processing Flow

```
User NL input
  -> Working memory assembly (token-budgeted context)
  -> Episodic recall (top-3 semantic matches from ChromaDB)
  -> Correction detection (is this a correction of last execution?) [before decompose]
  -> Workflow cache check (exact, then fuzzy match)
  -> LLM decomposition (NL -> TaskDAG of typed intents)
  -> Capability gap? -> Self-modification pipeline
  -> Attention scoring (urgency x relevance x deadline x dependency)
  -> DAG execution (parallel where possible, respecting dependencies)
  -> Consensus gating (quorum vote + red team for destructive ops)
  -> Escalation cascade (retry -> LLM arbitration -> user) on failure
  -> Reflection (optional LLM synthesis of results)
  -> Learning updates (Hebbian + Trust + Episodic + Workflow cache)
  -> Dreaming (offline consolidation during idle)
```

### Agent Inventory

The built-in agent pool topology is defined in `src/probos/runtime.py` (search for `_create_pools` or pool creation calls). Self-designed agents are added dynamically. For the current inventory, read runtime.py directly rather than relying on a static list.

Core pools (stable):

| Pool | Type | Consensus | Tier | Notes |
|------|------|-----------|------|-------|
| system | SystemHeartbeatAgent | No | Core | CPU, load, PID |
| filesystem | FileReaderAgent | No | Core | read_file, stat_file |
| filesystem_writers | FileWriterAgent | Yes | Core | write_file |
| directory | DirectoryListAgent | No | Core | list_directory |
| search | FileSearchAgent | No | Core | search_files |
| shell | ShellCommandAgent | Yes | Core | run_command |
| http | HttpFetchAgent | Yes | Core | http_fetch |
| introspect | IntrospectionAgent | No | Utility | explain_last, agent_info, system_health, why |
| skills | SkillBasedAgent | varies | Domain | Only when self_mod.enabled |
| system_qa | SystemQAAgent | N/A | Utility | Only when self_mod + qa enabled |
| red_team | RedTeamAgent | N/A | Utility | Independent verification |

### Key Files (structural -- see PROGRESS.md for complete current list)

| File | Role |
|------|------|
| `src/probos/runtime.py` | Top-level orchestrator. Boots pools, wires layers, processes NL. |
| `src/probos/types.py` | Core dataclasses (IntentMessage, IntentResult, TaskDAG, etc.) |
| `src/probos/config.py` | Pydantic config models. Loaded from YAML. |
| `src/probos/substrate/agent.py` | BaseAgent ABC. The agent contract. |
| `src/probos/cognitive/cognitive_agent.py` | CognitiveAgent. Instructions-driven LLM agent. |
| `src/probos/cognitive/decomposer.py` | NL -> TaskDAG. Also contains DAGExecutor. |
| `src/probos/cognitive/self_mod.py` | Self-modification pipeline orchestrator. |
| `src/probos/cognitive/feedback.py` | Human feedback -> trust/Hebbian/episodic updates. |
| `src/probos/cognitive/correction_detector.py` | Distinguishes corrections from new requests. |
| `src/probos/cognitive/agent_patcher.py` | Hot-patches designed agent code. |
| `src/probos/cognitive/architect.py` | ArchitectAgent. Deep-localize + LLM proposal generation. |
| `src/probos/cognitive/builder.py` | BuilderAgent. Executes BuildSpecs, writes/tests code. |
| `src/probos/cognitive/codebase_index.py` | CodebaseIndex. AST-based structural self-awareness. |
| `src/probos/cognitive/llm_client.py` | Tiered LLM client (deep/fast/standard via Copilot proxy). |
| `src/probos/consensus/trust.py` | Bayesian Beta trust network. |
| `src/probos/consensus/quorum.py` | Confidence-weighted quorum voting. |
| `src/probos/consensus/shapley.py` | Shapley value attribution for voters. |
| `src/probos/mesh/routing.py` | Hebbian connection weights. |
| `src/probos/mesh/intent.py` | Pub/sub intent bus. |
| `src/probos/experience/shell.py` | Interactive REPL with slash commands. |
| `src/probos/experience/panels.py` | Rich-rendered output panels for shell commands. |
| `src/probos/knowledge/store.py` | Git-backed artifact persistence. |
| `PROGRESS.md` | Comprehensive status tracker. Source of truth. |
| `Vibes/Nooplex_Final.md` | The Nooplex paper (theoretical foundation). |
| `config/system.yaml` | System configuration. |
| `docs/development/roadmap.md` | Full roadmap with crew structure and phase details. |

### Northstar: Automated Build Pipeline (AD-311+)

The Architect and Builder agents form an automated design-and-build pipeline:

```
Captain types /design → Architect perceives (7 layers) → LLM generates proposal
  → Captain reviews & approves → Builder executes BuildSpec → git branch/commit
  → Captain reviews & merges
```

**Architect Agent** (`cognitive/architect.py`):
- `perceive()` assembles 7 context layers: file tree, LLM-selected source files (2000-line budget, 300/file cap), test/caller/API discovery, slash commands, API routes, agent map, docs
- Layer 2a: fast-tier LLM selects 8 most relevant files from 20 keyword candidates
- Layer 2a+: import graph expansion adds collaborating modules (up to 12 files total)
- Contextual file hints: slash command requests guarantee `shell.py`/`panels.py`; API requests guarantee `api.py`
- Selective API surface: only includes method signatures for classes found in selected files
- `instructions` string has 6 verification rules including "never reference an unverified method"
- Enhancement proposals: when a feature partially exists, Architect must produce a FULL proposal (not punt)
- Uses deep tier (Opus) through Copilot proxy at `127.0.0.1:8080`

**Builder Agent** (`cognitive/builder.py`):
- Accepts `BuildSpec` (title, description, target_files, reference_files, test_files)
- CREATE mode: `===FILE: path===` blocks for new files
- MODIFY mode (AD-313): `===SEARCH===`/`===REPLACE===`/`===END REPLACE===` pairs within `===MODIFY: path===` blocks. Replacements applied sequentially, first occurrence only
- `perceive()` reads both reference_files and target_files (so LLM sees current content for accurate SEARCH blocks)
- `ast.parse()` validation after writes/modifies
- Test-fix loop (AD-314): runs pytest after writes, feeds failures back to LLM for up to 2 fix attempts. `_run_tests()` helper, `_build_fix_prompt()` for fix context. `max_fix_attempts` parameter on `execute_approved_build()`

**CodebaseIndex** (`cognitive/codebase_index.py`):
- AST-based, no LLM calls, built at startup
- `_import_graph` / `_reverse_import_graph`: forward and reverse import relationships
- `get_imports(path)` / `find_importers(path)`: query import relationships
- `find_callers(method)` / `find_tests_for(path)` / `get_full_api_surface()`: structural queries
- `query(concept)`: word-level keyword scoring across files and docs
- `read_doc_sections(doc_path, keywords, max_lines)`: targeted doc reading

**Ship's Computer / Decomposer Grounding** (AD-317):
- `PROMPT_PREAMBLE` in `prompt_builder.py` carries LCARS-era Ship's Computer identity with 6 grounding rules
- Dynamic `System Configuration` section counts registered intents by tier (core/utility/domain)
- `decompose()` accepts `runtime_summary` parameter — injected as `SYSTEM CONTEXT` in the user prompt
- `runtime.py._build_runtime_summary()` provides pool count, agent count, departments, intent count (synchronous, in-memory only)
- Example responses grounded — no longer claim unregistered capabilities
- Legacy prompt path (`_LEGACY_SYSTEM_PROMPT`) unchanged
- Self-knowledge progression: AD-317 (rules) → AD-318 (SystemSelfModel) → AD-319 (pre-response verification) → AD-320 (introspection delegation)

**LLM Tiers** (configured in `config/system.yaml`):
- `deep`: Claude Opus via Copilot proxy, 300s timeout. Used by Architect.
- `fast`: Claude Sonnet via Copilot proxy, 30s timeout. Used for file selection.
- `standard`: Claude Sonnet, 30s timeout. General use + fallback.
- All tiers route through `127.0.0.1:8080` (Copilot proxy extension, `REQUEST_TIMEOUT_MS` = 300s hardcoded)
- Fallback chain: deep → fast → standard (deduped)

**Context Budget Constraints** (critical for avoiding timeouts):
- Source budget: 2000 lines total across all selected files
- Per-file cap: 300 lines (truncated with note)
- Import expansion: up to 12 files total (8 LLM-selected + 4 import-traced)
- Docs: roadmap 100 lines, progress 50 lines, decisions 40 lines
- Test file headers: 5 lines each (imports + class name only)
- Agent map: compact format (type + tier, no module paths)
- Total context target: ~60K-100K chars (~15K-25K tokens)
- If context grows beyond this, Opus will timeout through the Copilot proxy
