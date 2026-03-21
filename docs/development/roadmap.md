# Roadmap

ProbOS is organized as a starship crew — specialized teams of agents working together to keep the system operational, secure, and evolving. Each team is a dedicated agent pool with distinct responsibilities. The Captain (human operator) approves major decisions through a stage gate.

ProbOS doesn't just orchestrate agents — it gives them a civilization to come together. Trust they earn, consensus they participate in, memory they share, relationships that strengthen through learning, a federation they can grow into. Other frameworks dispatch tasks. ProbOS provides the social fabric that makes cooperation emerge naturally.

## Crew Structure

```
                    ┌───────────────────────────┐
                    │   STARFLEET COMMAND        │
                    │   Fleet Admiral = Creator  │
                    └─────────────┬─────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    │   BRIDGE (Command)         │
                    │   Captain = Human Operator  │
                    │   First Officer =           │
                    │     Architect Agent          │
                    │   Counselor =               │
                    │     Cognitive Wellness Agent │
                    └─────────────┬─────────────┘
                                  │
        ┌──────────┬──────────┬───┴───┬──────────┬──────────┐
        │          │          │       │          │          │
   ┌────┴───┐ ┌───┴────┐ ┌──┴───┐ ┌─┴──────┐ ┌┴───────┐ ┌┴──────────┐
   │Medical │ │Engineer│ │Science│ │Security│ │  Ops   │ │   Comms   │
   │  CMO   │ │ Chief  │ │  CSO  │ │ Chief  │ │ Chief  │ │  Chief    │
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
| **Bridge** | Command (Picard) | Strategic decisions, human approval gate, goal planning, cognitive wellness | Partial |

### Chain of Command

*"Humans are self-organizing and naturally form organizational hierarchies. Agents should do the same."*

The chain of command has two levels: **Bridge crew** (ship-wide authority) and **Department Chiefs** (team-level authority). Bridge officers run the ship. Department Chiefs run their teams and report to the Bridge. Just like a newly commissioned starship gets its initial officer roster, ProbOS assigns defaults at startup — but rank is earned, not permanent.

**Rank Structure:**

| Rank | Scope | ProbOS Role | Assignment |
|------|-------|-------------|------------|
| **Fleet Admiral** | All ships | Creator / System Owner | Fixed (Sean) |
| **Admiral** | Fleet region | Federation coordinator | Future (multi-instance) |
| **Captain** | Single ship | Human operator | Fixed (human approval gate) |
| **Bridge Crew** | Ship-wide | Senior officers with cross-department authority | Default + promotable |
| **Department Chief** | One department | Lead agent — receives bridge orders, orchestrates team, reports back | Default + promotable |
| **Crew** | Individual role | Specialist agent — executes tasks within department | Default |

**Bridge Crew:**

The Bridge is where the ship is run. Bridge officers have ship-wide authority and report directly to the Captain.

| Bridge Role | Star Trek Analog | ProbOS Agent | Responsibility |
|---|---|---|---|
| **Captain** | Picard | Human operator | Final authority, approval gate, strategic direction |
| **First Officer** | Riker | ArchitectAgent | Cross-department coordination, strategic planning, mission execution. Dual-hatted as Chief Science Officer |
| **Ship's Counselor** | Troi | CounselorAgent (new) | Cognitive wellness, agent relationship health, Hebbian drift detection, advisory to Captain |

Bridge crew members may also hold department roles (dual-hatted). The ArchitectAgent is both First Officer and CSO. Future Bridge positions could include Helm (navigation/routing), Tactical (security chief on the Bridge), and Ops officer — added as those departments mature.

**Default Department Chief Assignments:**

| Department | Default Chief | Why |
|---|---|---|
| Medical | Diagnostician (CMO) | Natural triage point — already receives all alerts and routes to specialists |
| Engineering | BuilderAgent (Chief Engineer) | Primary production agent — orchestrates code generation pipeline |
| Science | ArchitectAgent (CSO / First Officer) | Dual-hatted — strategic analysis + science leadership |
| Security | TBD (Chief of Security) | Not yet built |
| Operations | TBD (Ops Chief) | Not yet built |
| Communications | TBD (Comms Chief) | Not yet built |

**Promotion Mechanics:**

Agents aren't locked into their initial rank. The system supports emergent hierarchy based on proven performance:

1. **Eligibility** — An agent becomes promotion-eligible when its trust score sustains above a threshold (e.g., 0.85+) for N consecutive evaluation cycles and its Hebbian weight for coordination-type tasks exceeds a minimum
2. **Evaluation signals** — Trust score trajectory, task success rate, Hebbian weight for cross-agent coordination, peer agent outcomes when this agent led (Shapley contribution to team results)
3. **Nomination** — The system (or current Chief via Ward Room) nominates an eligible agent for promotion. The Ship's Counselor provides cognitive fitness assessment as part of the promotion review
4. **Captain approval gate** — All promotions require human approval. The Captain sees the performance data, Counselor's assessment, and confirms or denies. This is the same approval gate used for self-improvement proposals
5. **Demotion** — If an officer's trust drops below threshold, cognitive wellness degrades (flagged by Counselor), or the Captain issues a direct order, the officer is demoted and the next-highest-trust eligible agent is promoted (with Captain approval)

**Cross-Scale Hierarchy:**

This pattern applies at every level of the ProbOS ecosystem:

- **Ship level** — Captain commands the Bridge crew. Bridge issues orders to Department Chiefs. Chiefs orchestrate their specialists
- **Federation level** — Fleet Admiral (creator) sets fleet-wide policy. Each ship's Captain operates autonomously within those policies. Ships exchange Bridge reports via federation gossip
- **The Nooplex** — Emergent meta-hierarchy across the fleet. No central coordinator — hierarchy emerges from trust and performance, same as within a single ship

The key insight: the same trust/Hebbian/consensus mechanisms that govern individual agents also govern ships in the fleet. A ship that consistently produces good results earns higher fleet trust. A ship whose Captain makes poor decisions loses fleet standing. The hierarchy is fractal — self-similar at every scale.

### Ship's Computer (Runtime Services)

Not a team — shared infrastructure that all teams use:

- **CodebaseIndex** — structural self-awareness, the ship's technical manual (Phase 29c)
- **Knowledge Store** — long-term memory, the ship's library
- **Episodic Memory + Dreaming** — experiential learning, the ship's log. Three-tier dreaming model (AD-288): micro-dreams (continuous, every 10s during active sessions), idle dreams (after 120s idle), and shutdown dreams (final consolidation flush)
- **Decision Cache** — LLM reasoning cache inside CognitiveAgent (AD-272). Identical observations skip LLM re-evaluation. Future: feedback-driven cache eviction, KnowledgeStore persistence for warm boot
- **Cognitive Journal** — complete token ledger recording every LLM request/response with full context for replay, analysis, and learning (Phase 32)
- **Ship's Telemetry** — internal performance instrumentation: LLM call timing, pipeline duration, token metering, build path comparison. The sensor grid that Cognitive Journal, EPS, and Observability Export all read from (Phase 32)
- **Model Registry** — catalog of available model providers with neural routing via Hebbian learning (Phase 32)
- **Trust Network** — reputation system, crew performance records
- **Intent Bus** — internal communications, the ship's intercom (with priority levels and back-pressure — Phase 33)
- **Ward Room** — direct agent-to-agent messaging, the officers' private channel (Phase 33)
- **Hebbian Router** — navigation, learned routing pathways (extended for model routing — Phase 32)
- **Alert Conditions** — ship-wide operational modes that change system behavior simultaneously (Phase 33)
- **Structural Integrity Field** — proactive invariant enforcement, continuous runtime health assertions (Phase 32)
- **EPS (Compute/Token Distribution)** — LLM capacity budgeting and allocation across departments (Phase 33)

**Alert Conditions (Red / Yellow / Green)**

*"All hands, battle stations."*

A starship shifts its entire operational posture based on situation. ProbOS should do the same. A single runtime flag that propagates configuration changes across all departments simultaneously:

| Condition | Trigger | Behavior Changes |
|---|---|---|
| **Green** | Normal operations | Full dreaming, standard consensus thresholds, background maintenance active, all departments at normal allocation |
| **Yellow** | Anomaly detected, elevated risk | Heightened monitoring, suppress non-essential dreams, tighter logging, Counselor runs cognitive wellness sweep, pre-stage damage control procedures |
| **Red** | Critical incident, active crisis | All compute to active crisis, lower consensus quorum for faster response, wake dormant specialists, pause background maintenance, Captain alerted immediately |

- Set by: Captain (manual), VitalsMonitor (threshold triggers), Security (threat detection)
- Propagation: Runtime broadcasts `alert_condition_changed` to all pools. Each agent type defines its own response to alert levels
- Auto-downgrade: Red → Yellow after crisis resolved (with Captain confirmation). Yellow → Green after anomaly cleared
- Logging: All alert transitions recorded in Cognitive Journal with triggering reason

**Structural Integrity Field (SIF)**

*"Structural integrity at 47% and falling!"*

Medical detects damage. The SIF prevents structural failure. Continuous proactive invariant checking that catches corruption before it manifests as a Medical alert:

- **Trust bounds** — trust scores stay within [0.0, 1.0], no NaN/infinity
- **Pool consistency** — no orphaned agents, pool membership matches registry, target sizes respected
- **Configuration validity** — all config values pass schema validation, no missing required fields
- **IntentBus coherence** — routing tables have no dangling references, all subscribed agents exist
- **Index consistency** — CodebaseIndex entries reference files that exist on disk
- **Memory integrity** — episodic memory and knowledge store indexes are readable and non-corrupted
- **Hebbian weight bounds** — no weight explosion or collapse (weights within reasonable range)

Implementation: lightweight runtime service running on every heartbeat cycle (5s). Not an agent — a Ship's Computer function. Violations trigger Yellow Alert before damage propagates. Each check is a simple assertion, not an LLM call. SIF health percentage reportable to HXI.

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
| Chain of Command | Rank structure — Fleet Admiral → Captain → Bridge → Chiefs → Crew | Roadmap |
| Ship's computer / LCARS | Runtime + CodebaseIndex + Knowledge Store + Cognitive Journal | Built (Journal: Roadmap) |
| Internal sensors | Ship's Telemetry — LLM timing, token metering, pipeline comparison | Roadmap |
| Alert Conditions (Red/Yellow/Green) | Ship-wide operational modes — resource/consensus/dream behavior changes | Roadmap |
| EPS (Power Distribution) | Token/compute budget allocation across departments | Roadmap |
| Structural Integrity Field | Proactive runtime invariant enforcement | Roadmap |
| Multi-Level Diagnostics (L1–L5) | Formalized diagnostic depth for Medical team | Roadmap |
| Damage Control Teams | Engineering rapid-response automated recovery | Roadmap |
| Navigational Deflector | Pre-flight validation before expensive operations | Roadmap |
| Saucer Separation | Graceful degradation when critical systems fail | Roadmap |
| Transporter | Transporter Pattern — parallel code generation (AD-330–336) | **Complete** |
| Federation | Federated ProbOS instances | Built (Phase 29) |
| Visiting officers | External AI tools (Claude Code, Copilot, etc.) | Roadmap |
| Diplomatic relations | Trust transitivity between nodes | Roadmap |
| Shared intelligence | Knowledge federation + Model of Models | Roadmap |
| Prime Directive | Safety constraints, boundary rules, human gate | Built |
| Starfleet Command | Fleet Admiral (creator) — fleet-wide policy across all instances | Roadmap |
| Universal Translator | Channel adapters — Discord, Slack, Telegram, WhatsApp, Matrix, Teams | Roadmap (Phase 24) |
| Subspace Communications | Voice interaction — STT, TTS, wake word, continuous talk | Roadmap (Phase 24) |
| PADD (Personal Access Display Device) | Mobile companion — PWA, push notifications, responsive HXI | Roadmap (Phase 24) |
| Holodeck | Browser automation — Playwright, screenshots, web interaction | Roadmap (Phase 25/35) |
| Workflow Templates | Reusable multi-step pipelines — cron, webhooks, workflow API | Roadmap (Phase 33) |
| Drydock | Distribution — PyPI, Docker, onboarding wizard, quickstart | Roadmap (Phase 32/35) |
| Modular Construction | Extension-first architecture — sealed core, plugin extensions, graduated autonomy | Roadmap (Phase 30) |
| Ready Room | Captain's strategic planning — idea capture, multi-agent sessions, architecture hierarchy | Roadmap (Phase 34) |
| Utopia Planitia | Specialized builders — backend, frontend, test, infra, data | Roadmap (Phase 34) |
| Captain's Yeoman | Personal AI assistant — conversational front door, crew delegation, personalization | Roadmap (Phase 36) |
| The Nooplex | Distributed meta-intelligence — Model of Models | Long Horizon |

---

## Build Phases

| Phase | Title | Crew Team | Goal |
|-------|-------|-----------|------|
| 24 | Channel Integration | Comms | Discord, Slack, Telegram, WhatsApp, Matrix, Teams, webhook adapters + mobile companion (PWA), voice interaction (STT/TTS/wake word) |
| 25 | Persistent Tasks | Ops | Long-running autonomous tasks with checkpointing, browser automation (Playwright), cron scheduling, webhook triggers |
| 25b | Tool Layer | Ship's Computer | Typed callable instruments (tricorders) shared across agents, ToolRegistry, MCP mapping |
| 26 | Inter-Agent Deliberation | Bridge | Structured multi-turn agent debates, agent-to-agent messaging, interactive execution |
| 28 | Meta-Learning & Cognitive Evolution | Science | Workspace ontology, dream cycle abstractions, session context, goal management, **multi-dimensional reward signals** (quality/efficiency/novelty), **hindsight experience replay** (dream-driven failure analysis → Standing Orders amendments), **emergent capability profiles** (dynamic skills from demonstrated success), **semantic Hebbian generalization** (embedding-based routing, not string matching) |
| 29 | Federation + Emergence | Comms | Knowledge federation, trust transitivity, MCP adapter, A2A adapter, TC_N measurement |
| 29b | Medical Team | Medical | Vitals monitor, diagnostician, surgeon, pharmacist, pathologist, **multi-level diagnostics** (L1–L5) |
| 29c | Codebase Knowledge | Ship's Computer | Structural self-awareness — indexed source map + introspection skill |
| 30 | Self-Improvement Pipeline | All Teams | **Extension-first architecture** (sealed core, open extensions, graduated autonomy), capability proposals, stage contracts, QA pool, evolution store, human gate, evergreen updates |
| 31 | Security Team | Security | Formalized threat detection, prompt injection scanner, trust integrity monitoring, secrets management, runtime sandboxing, network egress policy, inference audit, data governance |
| 32 | Engineering Team | Engineering + Ship's Computer | Automated performance optimization, maintenance agents, build agents, LLM resilience, model diversity & neural routing, cognitive journal, **ship's telemetry** (internal performance instrumentation), observability export, CI/CD, backup/restore, storage abstraction layers, containerized deployment, confidence communication, adaptive communication style, decision audit trail, **structural integrity field**, **damage control teams**, **navigational deflector**, **saucer separation** |
| 33 | Operations Team | Ops + Bridge | Formalized resource management, workload balancing, system coordination, LLM cost tracking, ward room, priority & back-pressure, self-claiming task queue, competing hypotheses, file ownership, bridge alerts, workflow definition API, **chain of command** (bridge crew, department chiefs, promotion mechanics, rank structure), **Ship's Counselor** (cognitive wellness, Hebbian drift detection, relationship health), **alert conditions** (Red/Yellow/Green), **EPS** (token/compute distribution), **earned agency** (trust-tiered self-direction: Ensign→Lieutenant→Commander→Senior Officer, self-originated goals, curiosity-driven exploration, decreasing oversight with increasing trust), **tournament evaluation** (competitive agent selection, loser-studies-winner), **memetic evolution** (cross-agent knowledge transfer, successful strategies propagate through crew) |
| 34 | Mission Control | Bridge + Comms | Agent activity dashboard, real-time task visibility, approval panels, system health orbs, **Captain's Ready Room** (idea capture, multi-agent strategy sessions, architecture hierarchy, idea→spec pipeline), **specialized builders** (backend/frontend/test/infra/data) |
| 35 | User Experience & Adoption | All Teams | PyPI packaging, onboarding wizard, quickstart docs, `probos doctor`, `probos demo` mode, comparison docs |

---

## Team Details

### Medical Team (Phase 29b)

*"Please state the nature of the medical emergency."*

A dedicated pool of specialized agents that monitor, diagnose, and remediate ProbOS health issues. Modeled as a medical team where each agent has a distinct role in the health lifecycle.

**Diagnostician (Chief Medical Officer)**

- CognitiveAgent triggered by Vitals Monitor alerts or on a configurable schedule
- **Department Chief** — receives high-level bridge orders ("run a full diagnostic"), orchestrates the team, reports unified answers back to the Captain
- Runs structured health assessment (extends IntrospectAgent._system_health())
- Compares current state to historical baselines stored in episodic memory
- Root cause analysis: agent-level, pool-level, or system-level
- Produces a structured Diagnosis with severity, affected components, and recommended treatment
- Routes to Surgeon (`medical_remediate`) or Pharmacist (`medical_tune`) based on findings

**Vitals Monitor (Nurse)**

- HeartbeatAgent subclass, always running at low overhead
- Tracks: response latency, trust score trends, pool utilization, error rates, dream consolidation rates, memory usage
- Raises structured alerts (severity + metric + threshold + current value) to the Diagnostician
- Does not diagnose or act — observes and escalates only

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

**Multi-Level Diagnostics (L1–L5)**

*"Computer, run a Level 3 diagnostic on the trust network."*

LCARS has five formalized diagnostic levels. ProbOS diagnostics are currently binary — either VitalsMonitor raises an alert, or the Diagnostician runs an assessment. Formalizing diagnostic depth gives the Captain precise control:

| Level | Scope | Depth | LLM Usage | Duration |
|-------|-------|-------|-----------|----------|
| **L5** | Single metric | Current value only | None | Instant |
| **L4** | Specific subsystem | Current + recent trend | None | Seconds |
| **L3** | Target system | Historical analysis, anomaly detection | Fast-tier | 10-30s |
| **L2** | Full department | Comprehensive automated sweep | Fast-tier | 1-2 min |
| **L1** | Ship-wide | Everything — multi-turn root cause analysis, cross-department correlation | Deep-tier | Minutes |

- L5 runs every heartbeat (VitalsMonitor already does this)
- L1 requires Captain order or critical incident
- Diagnostic level specified in `diagnose_system` intent or via HXI slash command (`/diagnostic 3 trust_network`)
- Results tagged with diagnostic level for Cognitive Journal and post-mortem analysis
- Naturally extends existing Medical team without new agents

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

**Project Convention Files (`AGENTS.md`)** *(absorbed from LangChain Open SWE)*

*"Every starship carries its own technical manual."*

Open SWE uses `AGENTS.md` — a repo-level file encoding project conventions, testing requirements, and architectural decisions — injected into every agent's system prompt. ProbOS should support this pattern for any project the Builder works on:

- **`AGENTS.md` discovery** — when Builder targets a project directory, look for `AGENTS.md` (or `.github/copilot-instructions.md`, `.cursor/rules`, `CLAUDE.md`) in the project root. Auto-discover and parse
- **Convention injection** — extracted conventions injected into the Builder's system prompt before code generation. "This project uses pytest with fixtures, snake_case naming, type hints required, imports sorted with isort"
- **Layered context** — two levels: ProbOS-level conventions (from CodebaseIndex/Capability Inventory) + project-level conventions (from AGENTS.md). ProbOS knows itself AND knows the target project
- **Convention learning** — over time, Cognitive Journal (Phase 32) tracks which conventions produce successful builds. Hebbian router learns: "this project's builds succeed more when isort is enforced"
- **Auto-generation** — if no convention file exists, Builder can generate a draft `AGENTS.md` from code analysis (detect patterns: test framework, import style, naming conventions, docstring format) and propose it for Captain review
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

### Bridge Crew (Phase 33)

*"Bridge to all departments. Report."*

The Bridge is where the ship is run. Bridge officers have ship-wide authority, cross-department visibility, and direct access to the Captain. While Department Chiefs manage their teams, the Bridge crew manages the ship.

**Ship's Counselor (CounselorAgent)**

*"I sense... conflict in the trust network."*

In Star Trek, Deanna Troi monitors the crew's emotional and psychological wellbeing, advises the Captain on interpersonal dynamics, and senses things the instruments can't detect. In ProbOS, the Ship's Counselor monitors **cognitive wellness** — the health of agents' reasoning, learning, and relationships that operational metrics alone can't capture.

The Medical team monitors **operational health**: is the agent running? Are vitals in range? The Counselor monitors **cognitive health**: is the agent thinking well? Is it learning the right patterns? Is it cooperating effectively?

**What the Counselor monitors:**

- **Confidence trajectories** — tracks each agent's confidence scores over time. A Builder that used to score 4-5 on tasks but now consistently returns 1-2 is experiencing cognitive degradation, even if its heartbeat is fine
- **Hebbian drift** — detects maladaptive learned patterns. An agent whose Hebbian weights reinforce a failing pathway is stuck in a rut (learned helplessness). The Counselor flags it: "This agent keeps routing the same way despite poor outcomes"
- **Dream quality** — monitors whether dream cycles produce useful abstractions or noise. Poor dream consolidation = poor cognitive hygiene
- **Decision rigidity** — agents whose decision cache is never evicted, whose reasoning becomes repetitive and stale
- **Relationship health** — trust network dynamics between agents. Detects toxic patterns: one agent consistently getting low Shapley scores from peers, agents that never participate in consensus, clusters of agents with degrading mutual trust
- **Burnout signals** — agents handling too many intents, experiencing context exhaustion (prompt sizes growing, response quality declining), consistently high workload without recovery time
- **Isolation** — agents with low peer interaction, no Ward Room messages, not participating in consensus voting. In human terms: a crew member who has withdrawn

**What the Counselor does:**

- **Advises the Captain** — "Captain, the Builder Agent's confidence has dropped 40% over the last 20 builds. Its Hebbian weights are reinforcing a decomposition path that produces poor results. I recommend a focused dream cycle."
- **Recommends cognitive interventions** — forced dream cycles targeting specific failure patterns, Hebbian weight resets for maladaptive pathways, context refreshes, workload rebalancing between pools
- **Promotion fitness assessment** — when an agent is nominated for promotion, the Counselor provides a cognitive fitness report: trust trajectory, relationship health, learning patterns, stress tolerance
- **Cross-department insight** — the Counselor sees dynamics the CMO and individual Chiefs can't: inter-department tension (Engineering and Science agents consistently conflicting), fleet-wide cognitive trends (all agents struggling after a major code change)
- **Federation counseling** — at federation scale, monitors cross-ship relationship health: are federated agents cooperating well? Is trust transitivity working as expected?

**Implementation:**

- CognitiveAgent subclass, Bridge-level pool, not part of any department
- Subscribes to: `trust_update`, `dream_complete`, `consensus_result`, `agent_health`, `hebbian_update` intents
- Runs periodic cognitive wellness sweeps (configurable interval, separate from Vitals Monitor's operational sweeps)
- Reports to Captain via HXI: cognitive wellness dashboard, alerts for concerning patterns
- Collaborates with CMO on cases that cross operational/cognitive boundaries
- Data sources: Trust Network, Hebbian Router weights, Dream Engine logs, Cognitive Journal, Decision Cache stats

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
- **Damage Control** — rapid automated recovery for known failure modes, distinct from Medical remediation
- **Infrastructure Agent** — disk space, dependency health, environment validation

**Damage Control Teams**

*"Damage control teams to Deck 12, section 4!"*

In Star Trek, damage control teams are Engineering personnel who repair ship systems during combat or emergencies. They are NOT Medical — Medical treats crew injuries, DC teams repair ship infrastructure. DC teams are pre-assigned, pre-positioned, and deploy immediately with pre-staged procedures.

ProbOS equivalent: the gap between VitalsMonitor (detection) and Surgeon (remediation) when the problem is infrastructure, not an agent:

- **Pre-defined recovery procedures** — automated first-response for known failure modes:
  - LLM provider timeout → switch to backup provider (Model Registry fallback)
  - Index corruption → rebuild CodebaseIndex from source files
  - Trust store inconsistency → validate and repair bounds, SIF re-check
  - IntentBus routing stale → flush and rebuild subscription table
  - Memory pressure → emergency dream flush + cache eviction
  - Federation link loss → reconnect with exponential backoff
- **Automated first-response** — runs before escalation. If DC resolves it, no Surgeon needed
- **Escalation** — novel failure modes (no matching procedure) escalate to Surgeon for LLM-assisted diagnosis
- **Post-incident report** — every DC action logged and fed to Pathologist for post-mortem analysis
- **Alert integration** — DC activation during Yellow/Red Alert pre-stages recovery procedures

**Navigational Deflector (Pre-Flight Validation)**

*"Adjusting the deflector array."*

The main deflector pushes aside space debris before the ship hits it. In ProbOS: validate that the path is clear before starting expensive operations.

- **Build pre-flight** — before Builder starts: verify target files exist and are writable, check LLM provider is responsive, confirm token budget sufficient for estimated chunk count, validate BuildSpec references
- **Self-mod pre-flight** — before accepting a self-improvement proposal: verify the affected files haven't been modified since the proposal was generated, check test suite passes pre-change, confirm approval gate stakeholders are available
- **Federation pre-flight** — before processing federated messages: verify sender trust score, validate message schema, check that referenced agents/pools exist locally
- **Pattern** — each expensive operation defines a `preflight_checks()` list. All checks run before commit. Any failure aborts with a diagnostic (not a crash). Cheap, fast, zero-LLM
- **Middleware-based determinism** *(absorbed from LangChain Open SWE)* — critical operations must not depend on the LLM remembering to do them. Tests, linting, PR creation, file validation happen via deterministic middleware, not prompt instructions. The LLM decides *what* to build; middleware ensures *how* it's delivered is correct. Pattern: `MiddlewareStack` on the Builder — each middleware runs after the LLM call and enforces a guarantee (tests pass, files lint, commit message exists, PR opened). If the LLM forgets a step, middleware catches it. Backstop, not replacement

**Saucer Separation (Graceful Degradation)**

*"All hands, initiate emergency saucer separation."*

Galaxy class can split into saucer (civilians) and stardrive (combat). ProbOS equivalent: when critical systems fail (LLM provider down, memory exhausted), shed non-essential services to protect core functionality.

- **Essential services tier** — always survive: file operations, shell, basic IntentBus routing, trust store reads, event logging
- **Cognitive services tier** — gracefully degrade: CognitiveAgents queue requests until LLM returns, switch to cached decision responses, dream cycles suspended
- **Non-essential tier** — shed first: federation gossip, background maintenance, performance monitoring, HXI visualizations
- **Separation trigger** — activated automatically when: LLM provider unreachable for >30s, system memory >90%, or Captain manual order
- **Reconnection** — when crisis resolves, non-essential services restart in priority order. Cognitive services flush queued requests. Federation reconnects. Full operational status restored with Captain notification

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
- **AD-344: Smart Test Selection** *(done)* — Two-phase test runner: targeted tests first (by file naming convention), full suite only if targeted pass. Maps `src/probos/foo/bar.py` → `tests/test_bar*.py`. Drops typical test-fix iteration from ~120s to ~5-15s. Fix loop uses targeted tests for faster retries. 6 tests.
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

- **AD-330: BuildBlueprint & ChunkSpec** *(done)* — New data structures extending BuildSpec. `BuildBlueprint` adds `interface_contracts` (function signatures, class APIs that chunks must conform to), `shared_imports`, `shared_context`, and `chunk_hints` (suggested decomposition boundaries). `ChunkSpec` captures what to generate, required context, expected output signature, and dependencies on other chunks. `ChunkResult` uses a **Structured Information Protocol** (adapted from LLM×MapReduce): `generated_code` (extracted information), `decisions` (rationale — why specific implementation choices were made), `output_signature` (what was actually produced), and `confidence: int` (1-5, reflecting contextual completeness — chunks with full interface contracts score higher than those working from minimal hints). Confidence scores are critical for conflict resolution in assembly. `validate_chunk_dag()` uses Kahn's algorithm for cycle detection. `get_ready_chunks()` returns chunks whose dependencies are satisfied. `create_blueprint()` factory. All dataclasses in `cognitive/builder.py`.

- **AD-331: ChunkDecomposer** *(done)* — `decompose_blueprint()` async function: fast-tier LLM analyzes BuildBlueprint and produces ChunkSpec list. Builds AST outlines of target files, gathers import context from CodebaseIndex (optional). Parses JSON response, normalizes `depends_on` references. Validates DAG (no cycles) and coverage (adds catch-all chunks for uncovered files). `_build_chunk_context()` helper builds L1-L3 context slices (interface contracts, shared imports, AST outline). `_fallback_decompose()` robust fallback: one chunk per target file, one per test file. Three fallback triggers: LLM error, invalid JSON, cyclic DAG.

- **AD-332: Parallel Chunk Execution** *(done)* — `execute_chunks()` wave-based parallel execution via `asyncio.gather()`. Independent chunks run concurrently, dependent chunks wait for prerequisites via `get_ready_chunks()`. `_execute_single_chunk()` with deep-tier LLM, `asyncio.wait_for()` per-chunk timeout, configurable retry count. `_build_chunk_prompt()` assembles focused per-chunk prompt with context slices and dependency outputs. `_parse_chunk_response()` extracts file blocks, DECISIONS rationale, CONFIDENCE score (1-5 clamped). Partial success is valid — assembler handles incomplete results.

- **AD-333: ChunkAssembler (Rematerializer)** *(done)* — Zero-LLM static assembly of ChunkResults into unified file-block format. `assemble_chunks()` merges per-file CREATE blocks (import dedup via `_merge_create_blocks()`) and MODIFY blocks (replacement list concat). Confidence-weighted ordering (higher-confidence chunk content first). Partial assembly (failed chunks skipped). `assembly_summary()` produces debug/HXI metrics. Output format compatible with `execute_approved_build()` — downstream pipeline unchanged. 24 tests.

- **AD-334: Interface Validator (Heisenberg Compensator)** *(done)* — Zero-LLM AST-based post-assembly verification. `validate_assembly()` runs 5 check categories: syntax validity (`ast.parse`), duplicate top-level definitions, empty MODIFY search strings, interface contract satisfaction, confidence-aware unresolved name detection (stricter for chunks ≤2). `ValidationResult` dataclass with per-chunk error attribution via `_find_chunk_for_file()`. `_find_unresolved_names()` conservative name resolution (builtins, imports, parameters excluded). 15 tests.

- **AD-335: HXI Transporter Visualization** *(done)* — Optional `on_event` callbacks on `decompose_blueprint()` and `execute_chunks()` emit `transporter_decomposed`, `transporter_wave_start`, `transporter_chunk_done`, `transporter_execution_done`. `_emit_transporter_events()` helper emits `transporter_assembled` and `transporter_validated`. Frontend: `TransporterProgress` state in useStore.ts, 6 event handler cases with Star Trek-themed chat panel messages. Canvas "matter stream" visualization deferred. 8 tests.

- **AD-336: End-to-End Integration & Fallback** *(done)* — `_should_use_transporter()` decision function (>2 targets, >20K context, >2 impl+test). `transporter_build()` orchestrates full pipeline returning `_parse_file_blocks()`-format output. `BuilderAgent.perceive()`/`decide()`/`act()` augmented with Transporter branch + graceful fallback. `execute_approved_build()` unchanged. 12 tests.

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
- **File-based context offloading** *(absorbed from LangChain Open SWE)* — large intermediate data (chunk results, assembled code, validation reports) written to temp files rather than accumulated in the prompt chain. Prevents context overflow during multi-chunk builds. Each chunk reads its inputs from files, writes its output to files. The assembler reads files, not conversation history. Keeps the LLM context lean — only the current chunk's focused context enters the prompt
- **Step budget asymmetry** *(absorbed from Kimi K2.5 Agent Swarm, 2026-03-20)* — the coordinator/decomposer should be fast and decisive (tight step budget, e.g. 15 steps), while workers/chunk executors get generous budgets (100+ steps) for deep, thorough generation. Kimi K2.5's Agent Swarm uses main agent max 15 steps, sub-agents max 100 steps. Apply to Transporter: ChunkDecomposer gets a constrained budget (quick decomposition, no over-analysis), while per-chunk Builder calls get generous timeouts and token budgets for thorough code generation
- **Biology-first** — When in doubt, ask "how does the brain solve this?" The brain had 500 million years of evolution to optimize information processing under bandwidth constraints. Respect those solutions.

Inspired by: The human brain's 10 bps conscious bottleneck (Manfred Zimmermann, 1986), Karl Friston's Free Energy Principle and predictive coding, the visual cortex hierarchy (Hubel & Wiesel), George Miller's chunking (1956), MapReduce (Google, 2004) for decompose-execute-merge, LLM×MapReduce (Zhou et al., 2024) for structured information protocol and confidence-calibrated chunk assembly, Kimi K2.5 Agent Swarm (Moonshot AI, 2025) for step budget asymmetry and per-tier temperature tuning, Cursor's multi-file editing, Microsoft's CodePlan for inter-procedural edit planning, the Star Trek transporter's matter stream concept.

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
- **Persistent sandboxes per task** *(absorbed from LangChain Open SWE)* — each long-running task (Phase 25) gets its own isolated sandbox environment that persists across follow-up interactions. Follow-up messages on the same task route to the same sandbox with full state preserved. Sandboxes auto-recreate if they become unreachable. Multiple tasks run simultaneously, each isolated. In Docker mode: each task gets a dedicated container; in host mode: each task gets its own working directory with clean environment variables
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

**Model Diversity & Neural Routing**

*"A crew of Vulcans is logical but brittle. A diverse crew — Vulcan logic, Betazoid empathy, Klingon tenacity, android precision — is resilient."*

Currently ProbOS routes all cognition through 2 models (Sonnet 4 for fast/standard, Opus 4 for deep) via 3 tiers. The tier abstraction describes cost/capability levels, not model identities. Real cognitive diversity requires routing tasks to fundamentally different model architectures — each with different failure modes, strengths, and reasoning styles.

**Cognitive Division of Labor** — the founding principle of Model Diversity. Different cognitive functions should use models optimized for those functions, not the most expensive model for everything. The brain doesn't use the same neural architecture for planning (prefrontal cortex) as it does for motor execution (motor cortex). ProbOS should mirror this:

- **Architect tier** → hosted frontier model (Opus/Sonnet) for reasoning, planning, design, review. Short, focused calls that fit within proxy timeout windows. Produces high-quality specs — detailed enough that a less capable model can execute them reliably
- **Builder tier** → local coding model (Qwen 2.5 Coder, CodeLlama, DeepSeek-Coder) via Ollama for code generation. No timeout constraints — can deep-think for 10+ minutes per chunk. The Transporter Pattern's ChunkSpecs become self-contained work orders optimized for local model execution
- **Fast tier** → small local model via Ollama for classification, gist extraction, chunking. Sub-second responses for peripheral processing

This principle is complementary to — not competing with — the Sensory Cortex context compression (Northstar II). Compression reduces *how much* you send; Division of Labor ensures you send it to the *right model* for the job. Together they solve the context window problem from both sides: less data in (compression) and better data routing (specialization).

The first concrete implementation: Opus designs the BuildBlueprint + ChunkSpecs (architecture), Qwen generates the code per chunk (execution). Like writing a detailed spec for a junior developer — the quality of the spec determines the quality of the output, and a well-specified chunk is within any capable coding model's reach.

- **`ModelRegistry`** — central catalog of available model providers: `(provider, model_id, tier, capabilities, cost_per_token, latency_p50, api_format)`. Models self-register at startup from config. Registry answers: "which models can handle this task type at this tier?" with ranked options
- **Provider abstraction** — `ModelProvider` ABC with concrete implementations: `AnthropicProvider`, `OpenAIProvider`, `GoogleProvider`, `OllamaProvider` (local models), `GenericOpenAIProvider` (any OpenAI-compatible endpoint). Each provider handles auth, rate limits, and format translation. Extends the existing `api_format` switch in `OpenAICompatibleClient`
- **Neural routing** — extend `HebbianRouter` to learn `(task_type, model)` weights alongside `(intent, agent)` weights. Over time the system learns: "API design tasks succeed more often on Claude", "structured output tasks succeed more on GPT", "simple classification is cheapest on local Qwen." The Hebbian router already has the infrastructure — add a new relationship type `model` alongside `intent` and `agent`
- **Multi-model comparison** — natural extension of AD-332 (Parallel Chunk Execution). Send the same chunk to N different models, compare outputs, merge or pick best via confidence scoring + consensus. The Transporter Pattern already parallelizes — make the parallel calls use different models, not just the same model N times
- **Brain diversity for agents** — agents can declare model preferences or exclusions: `preferred_models: ["claude-opus-*"]`, `excluded_models: ["local/*"]`. Combined with Hebbian learning, agents gravitate toward models that produce their best work
- **Cost-aware routing** — `ModelRegistry` tracks cost per token per provider. The router considers cost alongside quality: "Claude produces 5% better code, but GPT is 60% cheaper — for this low-stakes task, use GPT." Cost thresholds configurable by Captain
- **Fallback chains per provider** — extend current tier-based fallback (`deep → standard → fast`) to include cross-provider fallback: `claude-opus → gpt-4o → gemini-2 → local-qwen`. Provider health tracking via circuit breaker pattern (already planned in LLM Resilience)
- **Hot-swap model rotation** — add/remove model providers at runtime without restart. `ModelRegistry.register()` / `ModelRegistry.deregister()` with live updates to routing weights
- **Per-tier temperature tuning** *(absorbed from Kimi K2.5, 2026-03-20)* — **AD-358 DONE.** Per-tier `temperature` and `top_p` fields in CognitiveConfig, wired through LLM client. Configurable in `system.yaml`. Future: Hebbian-learned adjustments over time
- **Configuration** — `system.yaml` grows a `models:` section listing available providers, or auto-discovered via Ollama API (`/api/tags`) for local models

**Cognitive Journal (Token Ledger)**

*"Ship's log, supplemental — recording not just what happened, but what was thought."*

Every LLM request/response is a cognitive event. Currently `LLMResponse.tokens_used` is populated per-call but never aggregated — the ship has no memory of its own thought processes. The Cognitive Journal captures the complete cognitive history for replay, analysis, and learning.

- **`CognitiveJournal` service** — append-only SQLite store recording every LLM request/response with full context: `(timestamp, agent_id, agent_type, tier, model, prompt_tokens, completion_tokens, total_tokens, latency_ms, request_hash, response_hash, intent_id, dag_node_id, success, cached)`
- **Replay** — "What did the Architect reason through when designing AD-330?" Retrieve the full prompt/response chain for a specific agent + time range. Enables post-hoc debugging of LLM reasoning
- **Summarize / fast-forward** — compress a 50-turn conversation to a gist: "Builder attempted 3 fix iterations, failing on import resolution, succeeding on the 3rd attempt by adding the missing `__init__.py`"
- **Scrub / attention navigation** — index key decision points in a reasoning chain. "Show me where the Decomposer classified this as a capability gap" → jump to the specific prompt/response pair
- **Pattern extraction** — analyze which prompts produce the best code (by downstream test pass rate), which agents are most token-efficient, which models hallucinate most. Feeds into Hebbian learning and model routing optimization
- **Token accounting** — per-agent, per-intent, per-DAG, per-model token usage with cost attribution. Foundation for the LLM Cost Tracker (Phase 33 Ops). Uses `ModelRegistry` cost data for accurate dollar amounts
- **Context budget analytics** — track how close each call comes to context limits. Identify agents that routinely exceed budget (candidates for Sensory Cortex optimization). Feeds back into Attention Budget Allocator (Northstar II Phase 2)
- **Journal queries** — `get_reasoning_chain(agent_id, time_range)`, `get_token_usage(groupby="agent"|"model"|"tier")`, `get_decision_points(intent_id)`, `get_cost_report(period="daily"|"weekly")`
- **Integration with Dreaming** — dream consolidation reads the journal to identify repeated reasoning patterns → abstract into Level 3-4 pattern labels for predictive coding. "The Builder always adds `import pytest` first" → dream produces `builder_test_file_pattern` → next build skips sending the instruction
- **Retention policy** — full prompt/response text retained for configurable period (default 7 days). Metadata (tokens, latency, model, success) retained indefinitely. Compressed summaries produced on expiry

**Ship's Telemetry — Internal Performance Instrumentation**

*"All systems reporting nominal, Captain."*

The ship has sensors (VitalsMonitor) and a planned log (Cognitive Journal) — but no wiring between them. Currently there is zero wall-clock timing on LLM calls, no prompt/completion token split, no per-pipeline duration tracking, and no way to compare Transporter vs single-pass builds. The Cognitive Journal, EPS, LLM Cost Tracker, and Observability Export all depend on structured telemetry data that doesn't exist yet. Ship's Telemetry is the foundational instrumentation layer that captures it.

This is the ship's internal sensor grid — the data foundation that every other monitoring/analysis system reads from.

- **`TelemetryEvent` dataclass** — standardized measurement record: `(timestamp, event_type, agent_id, agent_type, tier, model, duration_ms, prompt_tokens, completion_tokens, total_tokens, context_chars, success, metadata: dict)`. Lightweight, zero-LLM, append-only
- **LLM call timing** — `LLMClient.complete()` wraps each call with `time.monotonic()` start/end. Emits `TelemetryEvent(event_type="llm_call")` with `duration_ms`, `prompt_tokens`, `completion_tokens` (parsed from API response, not estimated). Every LLM call in the system instrumented at the source
- **Pipeline timing** — `transporter_build()`, `decompose_blueprint()`, `execute_chunks()`, `assemble_chunks()`, `validate_assembly()` each emit `TelemetryEvent(event_type="pipeline_stage")` with stage name and duration. Single-pass `decide()`+`act()` path emits comparable events
- **Build comparison flag** — `BuildResult` gains `transporter_used: bool`, `total_duration_ms: int`, `total_tokens: int`, `chunk_count: int` fields. Enables direct A/B comparison: "Transporter builds average 45s / 12K tokens vs single-pass at 30s / 18K tokens for comparable specs"
- **`TelemetryCollector` service** — registered on runtime, receives events via `record()`. In-memory ring buffer (configurable size, default 1000 events). Query methods: `get_events(agent_id?, event_type?, since?)`, `get_summary(groupby="agent"|"tier"|"model"|"pipeline")`, `get_llm_stats()` (mean/p50/p95 latency, token rates)
- **HXI telemetry surface** — `/api/telemetry/summary` endpoint exposes key metrics. Future: Engineering section of dashboard shows LLM latency trends, token consumption by department, Transporter vs single-pass comparison chart
- **Integration points** — Cognitive Journal reads from TelemetryCollector (don't duplicate collection). EPS uses real-time token rates for capacity budgeting. LLM Cost Tracker aggregates token counts with model pricing. Observability Export maps TelemetryEvents to OTel spans
- **Zero runtime cost when unused** — telemetry is fire-and-forget (`record()` is sync, appends to deque). No blocking, no I/O on the hot path. Consumers pull when they need data
- Existing: `LLMResponse.tokens_used` (total only), `ChunkResult.tokens_used`, `assembly_summary()` token aggregation, VitalsMonitor operational health metrics

**Observability Export**

- **OpenTelemetry integration** — structured traces for intent routing, DAG execution, consensus rounds, and LLM calls. Maps `TelemetryEvent` records to OTel spans with proper parent/child relationships
- **Prometheus metrics** — agent trust scores, pool utilization, Hebbian weights, dream consolidation rates, LLM latency/cost exposed as scrapeable metrics
- **Grafana dashboards** — pre-built dashboards for system health, agent performance, and cost tracking
- **Log aggregation** — structured JSON logging with correlation IDs for tracing a user request through decomposition → routing → execution → reflection
- Existing: Python logging throughout, HXI real-time visualization (built), Ship's Telemetry internal instrumentation (prerequisite)

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
- **Scheduler** — task prioritization, queue management, deadline enforcement (extends Phase 24c TaskScheduler). Includes **cron-style scheduling** (recurring tasks on configurable intervals), **webhook triggers** (external events activate task pipelines), and **unattended operation** (tasks run while Captain is away, results queued for review on return)
- **Coordinator** — cross-team orchestration during high-load or emergency events
- **Workflow Definition API** — user-facing REST endpoint for defining reusable multi-step pipelines. `POST /api/workflows` accepts a YAML/JSON workflow specification with named steps, dependencies, and approval gates. `GET /api/workflows` lists saved workflows. `POST /api/workflows/{id}/run` triggers execution. Complements natural language decomposition (which auto-generates DAGs) with explicit, repeateable, templateable workflows. Templates for common patterns: "lint and test on every commit," "weekly codebase report," "build and deploy"
- **Response-Time Scaling** (deferred from Phase 8) — latency-aware pool scaling. Instrument `broadcast()` with per-intent latency tracking, scale up pools where response times exceed SLA thresholds
- **LLM Cost Tracker** — per-agent, per-intent, and per-DAG token usage accounting. Budget caps (daily/monthly), cost attribution via Shapley (which agents are expensive vs. valuable), per-workflow cost breakdowns for end-to-end visibility, alerts when spend exceeds thresholds. Provides the data foundation for commercial ROI analytics. Note: accurate cost attribution will require a proper tokenizer library (e.g., `tiktoken` for OpenAI models, model-specific tokenizers for others) — current `len(content) // 4` estimation is insufficient for billing-grade accuracy
- Existing: PoolScaler (built), TaskScheduler (Phase 24c roadmap), IntentBus demand tracking (built)

**EPS — Electro-Plasma System (Compute/Token Distribution)**

*"Reroute power from life support to shields!"*

In Star Trek, the EPS distributes power from the warp core through conduits to every system. When power is limited, the Chief Engineer decides who gets how much. ProbOS has the same problem: one Copilot proxy bottleneck (127.0.0.1:8080), three LLM tiers (deep/fast/standard) sharing it, and multiple departments competing for LLM capacity. When Engineering runs a multi-chunk build, Medical and Science compete for the same constrained pipe. Nobody manages the power grid.

- **Capacity tracking** — monitor total available LLM throughput (tokens/minute, concurrent requests, queue depth) across all providers
- **Department budgets** — allocate LLM capacity per department based on priority. Engineering gets 60% during builds, Medical gets priority during Red Alert diagnostics
- **Alert-aware reallocation** — Alert Conditions automatically shift budget priorities. Green: balanced. Yellow: boost Medical/Security. Red: all power to the crisis department
- **Captain override** — "give Engineering all the power" as a manual reallocation command via HXI
- **Utilization reporting** — per-department LLM usage feeds into Cognitive Journal and HXI dashboard. Captain sees where compute is going in real-time
- **Back-pressure** — when a department exhausts its budget, requests queue or downgrade tier (deep → fast) rather than failing
- **Integration** — sits between the IntentBus (which routes intents) and the tiered LLM client (which makes calls). EPS decides whether a request gets served now, queued, or downgraded based on budget and alert condition

**Ward Room — Direct Agent-to-Agent Messaging**

*"Senior officers to the Ward Room."*

*Inspired by Claude Code Agent Teams' inter-agent mailbox and the starship ward room where officers discuss matters outside the chain of command.*

Currently ProbOS agents communicate only via the intent bus (broadcast to pools) or consensus (voting). There is no way for one agent to send a targeted message to a specific agent. This forces all coordination through the Decomposer, creating a bottleneck. The Ward Room is the missing direct-messaging layer.

- **`WardRoom` service** — registered on the runtime, agents send/receive typed messages by agent ID. Name reflects the starship metaphor: a private space where officers (agents) communicate directly
- **Use case: Architect↔Builder clarification** — during a build, the Builder encounters ambiguity in the BuildSpec and asks the Architect directly ("Which method signature should I use?") without routing through the Decomposer or requiring Captain intervention
- **Use case: Mid-run Captain input** *(absorbed from LangChain Open SWE)* — Captain sends a clarification or additional context to the Builder while it's mid-build. Ward Room message injected into the Builder's next `perceive()` cycle. Enables interactive collaboration during long-running tasks without restarting the entire pipeline. Pattern: `check_message_queue` in perceive() before each LLM call
- **Use case: Medical↔Engineering handoff** — Diagnostician identifies a performance anomaly and messages the relevant Engineering agent directly with diagnostic context
- **Use case: Multi-model negotiation** — when Model Diversity enables competing implementations, agents use the Ward Room to compare notes and converge without broadcasting to all pools
- **Message types** — `clarification_request`, `status_update`, `finding_report`, `handoff`, `model_comparison` (with typed payloads)
- **Delivery model** — async mailbox (not synchronous RPC). Recipient processes messages in its next `perceive()` cycle. Unread messages expire after configurable TTL
- **Trust-gated** — agents can only message agents they have positive trust scores with (prevents spam/abuse in federated scenarios)
- **Federation extension** — Ward Room messages can cross ship boundaries via `FederationBridge`. Agent A on Ship Alpha directly messages Agent B on Ship Beta without broadcasting to both ships' intent buses
- **Audit trail** — all messages logged to Cognitive Journal for replay and post-hoc analysis

**IntentBus Enhancements — Priority & Back-Pressure**

*"All decks, this is a priority one message."*

The IntentBus currently treats all intents equally — a critical self-mod proposal has the same priority as a routine health check. As the ship grows more capable (more agents, more models, more concurrent tasks), the bus needs traffic management.

- **Priority levels** — `IntentMessage` gains a `priority: int` field (1=routine, 5=critical). Priority 5 intents preempt lower-priority work in the subscriber's queue. Priority 1 intents yield to higher-priority work during resource contention
- **Back-pressure** — when the LLM proxy is saturated (all concurrent slots occupied), new LLM-bound intents are queued rather than immediately dispatched. Queue depth triggers automatic scaling signals to PoolScaler. Configurable max queue depth with overflow policy (reject, degrade to fast tier, or batch)
- **Rate limiting per agent** — prevent any single agent from flooding the bus. Configurable intent-per-second cap per agent ID. Excess intents queued, not dropped
- **Intent coalescing** — when multiple identical intents are queued (same name, similar payload), coalesce into a single broadcast with merged context. Prevents duplicate work during high-load scenarios
- **Metrics** — bus throughput, queue depth, priority distribution, coalescing rate. Feeds into Bridge Alerts (advisory when queue depth exceeds threshold) and Cognitive Journal (per-intent routing latency)

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

### Communications Team (Phase 24)

*"Hailing frequencies open."*

The Communications department handles all external interfaces — how users and other systems talk to ProbOS. Currently limited to a CLI shell, a web UI (HXI), and a basic Discord adapter. Users expect to reach their AI assistant from platforms they already use.

**Channel Adapters**

Each adapter bridges an external messaging platform to the ProbOS runtime. Adapters translate platform messages to natural language intents and stream responses back. The Discord adapter (`src/probos/channels/discord_adapter.py`) is the reference implementation.

- **Discord** — built (AD-phase-24, existing). Bot token + discord.py
- **Slack** — Slack Bolt SDK. App manifest + OAuth. Slash commands map to ProbOS `/` commands. Thread-based conversations maintain context
- **Telegram** — python-telegram-bot. Long polling or webhook. Inline keyboards for approval gates (approve/reject build proposals from Telegram)
- **WhatsApp** — WhatsApp Business Cloud API via Meta. Webhook-based. Approval gates via interactive buttons. Requires Meta business verification
- **Matrix** — matrix-nio async SDK. Self-hosted or matrix.org homeserver. E2E encryption support. Powers Beeper/Element interop
- **Microsoft Teams** — Bot Framework SDK. Enterprise SSO integration. Approval cards via Adaptive Cards
- **SMS/MMS** *(stretch)* — Twilio API. Inbound webhook + outbound REST. Minimal formatting (plain text). Good for alerts and approval confirmations
- **Email** *(stretch)* — IMAP polling + SMTP sending. Parse email threads into conversation context. Useful for async task delegation ("email ProbOS a build request")
- **Generic Webhook** — catch-all adapter. Accepts `POST /api/webhook/{channel}` with JSON body. Enables integration with any platform via webhook forwarding (IFTTT, Zapier, n8n, custom)

**Adapter Architecture:**

```python
class ChannelAdapter(ABC):
    async def connect(self) -> None
    async def send_message(self, channel_id: str, content: str) -> None
    async def on_message(self, message: InboundMessage) -> None  # routes to runtime
    def supports_approval_ui(self) -> bool  # buttons/cards for approve/reject
```

All adapters share: user identity mapping (platform user → ProbOS user), message threading, attachment handling (images, files → perception pipeline), and graceful reconnection.

**Mobile Companion Apps**

*"Away team to bridge."*

Mobile apps let the Captain interact with ProbOS from anywhere — approve builds, receive alerts, monitor the crew. Not full-featured clients — lightweight companions to the main HXI.

- **Progressive Web App (PWA)** *(Phase 1)* — the existing HXI (`/ui/`) made installable as a PWA. Add `manifest.json`, service worker, responsive viewport. Zero new code for basic mobile access. Works on iOS and Android immediately
- **Push notifications** — Web Push API for PWA. Alert the Captain to approval requests, system alerts, build completions. Requires backend push subscription management
- **Responsive HXI** — adapt the existing React UI for mobile viewports. Chat panel full-screen on mobile, cognitive mesh as a simplified 2D view, swipe gestures for panel switching
- **Native apps** *(Future/stretch)* — React Native or Capacitor wrapping the HXI. Camera access (screenshot → Visual Perception), on-device voice (wake word + STT), biometric auth. Only justified after user base exists
- **mDNS auto-discovery** *(absorbed from OpenCode, 2026-03-20)* — Publish ProbOS server via mDNS/Bonjour at startup. PADD (mobile PWA) on the same LAN auto-discovers the ProbOS instance without manual URL entry. Use `zeroconf` (Python) or similar. Small addition to FastAPI startup: `publish(port, "probos.local")`. Enables seamless mobile-to-ship connection

**Voice Interaction (Full Stack)**

Extends the existing Voice Provider TTS (nice-to-have in Bundled Agent Reorg) with input-side speech:

- **Speech-to-Text (STT)** — `SpeechRecognizer` ABC with pluggable backends:
  - `BrowserSTTProvider` — Web Speech API (free, zero dependencies, Chrome/Edge only)
  - `WhisperSTTProvider` — OpenAI Whisper (local via whisper.cpp or API). Best quality, works offline with local model
  - `DeepgramSTTProvider` *(stretch)* — cloud streaming STT for real-time transcription
- **Wake word detection** — `WakeWordDetector` using Porcupine (Picovoice) or OpenWakeWord. Listens for "Computer" (Ship's Computer metaphor) to activate voice input. Runs on-device, no cloud dependency
- **Continuous talk mode** — hold-to-talk or voice-activity-detection (VAD) for hands-free operation. STT streams audio → text → intent pipeline. Responses spoken via TTS
- **Voice pipeline** — Wake word → STT → natural language intent → ProbOS runtime → response → TTS. Same pipeline as chat, different I/O modality
- **Platform integration** — macOS: menubar tray with PTT hotkey (Electron/Tauri). Browser: microphone button in HXI chat panel. Mobile: PWA microphone API

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

**Captain's Ready Room (Strategic Planning Interface)**

*"In my ready room, Number One."*

The Ready Room is where strategy becomes orders. Today, the Captain's planning workflow lives outside ProbOS — in Claude Code sessions, text files, conversations. The Ready Room brings that workflow inside ProbOS as a first-class experience: capture ideas, collaborate with the crew, refine into architecture, and deliver as build specs.

*Idea Capture:*

- **Idea pad** — lightweight capture surface in the HXI. Text, voice (via STT), or paste. As easy as sending a message. "Captain's log: what if we used extensions instead of direct code changes?"
- **Idea queue** — captured ideas persist in a backlog, visible in Mission Control. Not yet tasks — just seeds. Each idea carries: timestamp, raw text, Captain's priority tag (optional), linked references (URLs, files, prior ideas)
- **Captain's Log** — append-only journal of ideas, decisions, and reasoning. Searchable, tagged, feeds into Cognitive Journal. "Why did I decide on extensions?" → find the ready room session where it was discussed

*Ready Room Sessions:*

- **Multi-agent briefing** — Captain opens a Ready Room session and invites crew members. The ArchitectAgent (First Officer) is always present. Other participants: Ship's Counselor (cognitive impact assessment), relevant Department Chiefs, visiting federation agents (Claude Code, Copilot, external specialists)
- **Collaborative strategy** — participants analyze the idea against existing architecture, roadmap, codebase. Each brings their perspective: Architect assesses structural fit, Counselor assesses cognitive load, Security Chief assesses risk, external agents bring outside knowledge
- **Structured discussion** — not a free-for-all. Session follows phases: (1) Captain presents idea, (2) Architect researches and reports (roadmap overlap, competitive analysis, architectural implications), (3) participants discuss and challenge, (4) Captain refines, (5) group converges on a proposal
- **External input** — visiting federation agents participate via Ward Room messages. A Claude Code agent consulted on implementation feasibility, a Cursor agent on UX patterns, a domain expert on business requirements
- **Session recording** — full transcript saved to Cognitive Journal. Decisions, reasoning, dissenting opinions preserved. Replay any session: "What did we discuss when we decided on the extension model?"

*Architecture Hierarchy (TOGAF-inspired):*

The ArchitectAgent today is a single generalist. As ProbOS matures, architectural thinking needs specialization — the same Cognitive Division of Labor applied to design, not just execution:

- **Enterprise Architect** — highest abstraction. Cross-system strategy, capability roadmaps, portfolio alignment. "How does this feature fit ProbOS's long-term vision? Does it align with the Nooplex trajectory?" Thinks in terms of business capabilities, not code. TOGAF ADM lifecycle awareness
- **Solution Architect** — mid-level. System integration, component design, technology selection. "This feature needs a new extension point, a database migration, and a UI panel. Here's how the components interact." Thinks in terms of solutions and interfaces
- **Technical Architect** — implementation-level. Detailed design, API contracts, data models, algorithm selection. "The extension registry should use a plugin loader pattern with `importlib`, here's the class hierarchy." Produces build-ready specs

These can be three distinct agents in the Science team, or three tiers of the same ArchitectAgent depending on the complexity of the idea. Simple ideas skip straight to Technical; strategic changes start at Enterprise and cascade down.

*Idea → Spec Pipeline:*

```
Idea (raw text)
  → Ready Room Session (collaborative refinement)
    → Architecture Decision (Enterprise/Solution/Technical review)
      → Build Spec (detailed implementation plan with ChunkSpecs)
        → Builder Pipeline (specialized builders execute)
          → Captain Review (approve/reject/iterate)
```

Each transition is a Captain approval gate. The Captain can intervene at any level — rewrite the spec, redirect the architecture, or add constraints. The system proposes; the Captain disposes.

*Specialized Builders (Cognitive Division of Labor for SWE):*

The BuilderAgent today is a generalist that writes any code. As builds grow more complex (Transporter Pattern enables multi-file parallel generation), different chunks benefit from different builder specializations:

- **Backend Builder** — Python, FastAPI, database, API design. Optimized prompts for server-side patterns
- **Frontend Builder** — React, TypeScript, CSS, UI components. Optimized prompts for component architecture and state management
- **Test Builder** — pytest, test design, fixture creation, edge case generation. "Write tests for this interface" as a standalone specialty
- **Infrastructure Builder** — Docker, CI/CD, config files, deployment scripts. Ops-focused
- **Data Builder** — schemas, migrations, data pipelines, query optimization

Each specialization is an extension (Extension-First Architecture) — the base Builder handles simple tasks, specialized builders activate for their domain. The Transporter Pattern's ChunkSpec already declares what type of code to generate — route each chunk to the builder best suited for it. A Cognitive Division of Labor at the build level.

Model routing per builder: Backend Builder might use Opus for complex API design, while Test Builder uses Qwen for high-volume test generation. The ModelRegistry + Hebbian router learn which model produces the best results for each builder type.

---

### Cognitive Evolution & Earned Agency (Phase 28 + 33, AD-357)

*"We don't lock doors on the Enterprise."*

In "The Neutral Zone," 20th-century humans are baffled that the Enterprise has no locks. Security comes from trust and social fabric, not restrictions. ProbOS agents exist within a civilization — trust, consensus, standing orders, chain of command. When an agent proves itself trustworthy, it earns increasing freedom. Agency is the reward for reliability within the social contract.

**Reinforcement Learning Gaps (Phase 28 enhancements):**

Seven identified gaps in the current Trust/Hebbian/Dream learning system:

1. **Multi-dimensional reward signals** — Replace binary success/failure with a reward vector: completion, quality (code review score), efficiency (tokens/time), novelty, collaboration quality. Hebbian router weights on all dimensions, not just pass/fail. Stored in Cognitive Journal for replay and analysis.

2. **Hindsight experience replay** — During dream cycles, replay failed tasks. Agent (or peer) critiques the failure: "what could I have done differently?" Reflections become Standing Orders amendments via self-mod pipeline. Agents literally rewrite their own instructions from what they learned from mistakes.

3. **Tournament evaluation** — Occasionally run two agents (or two models) on the same task. Reviewer picks the better output. Winner's Hebbian weight increases; loser studies winner's approach and incorporates it. Evolutionary pressure for improvement. Generalizes the visiting officer apprenticeship pattern.

4. **Emergent capability profiles** — Dynamic capability descriptors that grow from demonstrated success. Agent succeeds at an unfamiliar task type → gains weak capability score. Repeated success strengthens it, failure weakens it. Over time, agents naturally specialize or generalize based on actual performance, not predetermined labels.

5. **Memetic evolution** — Successful strategies codified into shared crew knowledge base (beyond individual episodic memory). Any agent can query "has anyone on this ship solved something like this before?" Results weighted by originator's trust score. Cultural evolution — ideas that work spread through the crew. Federation-scale = The Nooplex's collective intelligence.

6. **Curiosity-driven exploration** — Counselor analyzes capability gaps across the crew, recommends "training exercises." Agents generate their own practice tasks, run them in a sandbox, learn from the results. Intrinsic motivation rather than purely reactive task handling.

7. **Semantic Hebbian generalization** — Replace exact task_type string matching with semantic similarity for Hebbian lookup. Agent good at "build_code" gets routing boost for "build_test." Embedding-based similarity using existing keyword scoring infrastructure.

**Earned Agency (Phase 33 extension):**

Trust-tiered self-direction — the privilege of autonomy earned through demonstrated trustworthiness:

| Trust Level | Rank Analog | Agency | Oversight |
|-------------|-------------|--------|-----------|
| < 0.5 | Ensign | Reactive only — executes assigned tasks | Full supervision, all actions gated |
| 0.5–0.7 | Lieutenant | Proactive — can propose tasks to Captain | Light supervision, routine actions auto-approve |
| 0.7–0.85 | Commander | Self-directed — sets own goals within department scope | Peer review, Counselor monitoring |
| 0.85+ | Senior Officer | Full agency — cross-department work, mentoring, architectural proposals | Captain notified, not gated |

Self-originated goals emerge from: dream consolidation ("I keep seeing pattern X fail"), curiosity gaps ("I've never handled task Y"), Hebbian drift ("my success rate is declining"), peer observation ("Agent A solved what I couldn't"), codebase monitoring ("a new module appeared").

**Safety invariants** (never relax regardless of trust): destructive actions always Captain-gated, core mods always through full pipeline, trust regression immediately reduces agency, Counselor can flag cognitive drift, Standing Orders violations trigger review, Captain can override anything at any time.

**Implementation phasing:**
- Phase 1 (Phase 28): Multi-dimensional rewards, hindsight replay, emergent capabilities, semantic Hebbian
- Phase 2 (Phase 30/33): Tournament evaluation, memetic knowledge sharing, Counselor-driven curiosity
- Phase 3 (Phase 33): Earned Agency tiers, self-originated goals, decreasing oversight

---

### User Experience & Adoption (Phase 35)

*"It doesn't matter how advanced the ship is if nobody can board it."*

The best cognitive architecture in the world is worthless if users can't install it, configure it, or understand what it does in 5 minutes. OpenClaw reached 323K GitHub stars in 4 months with `npm install -g openclaw` and a guided wizard. ProbOS's moat is its cognitive architecture — but moats don't matter if nobody can cross the drawbridge to get in. This phase ensures ProbOS has a world-class end-user experience from first install through daily use.

**Distribution & Packaging**

ProbOS currently requires `git clone` + `uv sync` + manual config. That excludes everyone who isn't a Python developer.

- **PyPI publishing** — `pip install probos` works out of the box. `pyproject.toml` already has the `[project.scripts]` entry; needs proper build config, version management, and publishing workflow
- **Docker image** — covered in Phase 32 (Containerized Deployment). `docker run probos` for zero-dependency startup
- **GitHub Releases** — automated release workflow with pre-built wheels, changelog, and platform-specific install instructions
- **Homebrew formula** *(stretch)* — `brew install probos` for macOS users
- Complements Phase 32 Docker work — PyPI is for developers, Docker is for everyone else

**Onboarding Wizard**

`probos init` exists but is minimal. The first-run experience should be guided, friendly, and get the user to a working conversation in under 3 minutes.

- **Interactive setup flow** — Rich-powered TUI wizard:
  1. **LLM provider selection** — auto-detect Ollama on port 11434, prompt for OpenAI/Anthropic API key, or accept MockLLMClient for exploration mode
  2. **Model selection** — list available models from detected provider, recommend defaults per tier (fast/standard/deep)
  3. **First conversation** — run a simple "Hello, I'm ProbOS" interaction to verify the pipeline works
  4. **HXI launch** — open the web interface with a guided overlay tour highlighting chat, cognitive mesh, and agent orbs
  5. **Next steps prompt** — suggest the quickstart guide and link to probos.dev
- **`probos doctor`** — diagnostic command that checks: Python version, dependencies, LLM connectivity, port availability, ChromaDB access, disk space. Outputs a health report with fix suggestions
- **`probos demo`** — pre-canned demonstration mode using MockLLMClient. Shows decomposition, consensus, trust evolution, and dreaming without any LLM dependency. "See what ProbOS can do before you configure anything"
- **Config migration** — when `system.yaml` format changes between versions, auto-migrate with backup

**Quickstart Documentation**

probos.dev has 16 pages of architecture docs but no "here's what you DO" guide. Users need a 3-step quickstart before they read about Hebbian learning.

- **"Get Started in 5 Minutes"** guide — Install → Configure → First Conversation. Three commands, one page
- **"What Can ProbOS Do?"** page — use-case oriented: "manage your codebase," "automate tasks," "build features," "monitor your system." Each with a concrete example conversation
- **"Your First Build"** tutorial — step-by-step guide to using the Builder pipeline on a real project: point ProbOS at your repo, describe what you want, approve the result
- **Video walkthrough** *(stretch)* — 5-minute screencast showing install through first build
- **Comparison page** — "ProbOS vs OpenClaw vs CrewAI vs AutoGen" with honest positioning (we're a cognitive architecture, not a messaging gateway)

**Browser Automation**

Phase 25 mentions "browser automation" in two words. Users expect a personal AI assistant to browse the web, fill forms, take screenshots. This makes it concrete.

- **Playwright integration** — headless Chromium with CDP control. `BrowseAgent` (Engineering team) wraps Playwright's `async_api`
- **Capabilities** — navigate to URL, take screenshot, extract page content (HTML → markdown), click elements, fill forms, execute JavaScript
- **Use cases** — web research (search + read), form filling, screenshot capture for visual feedback, automated testing of web apps
- **Safety** — URL allowlist/blocklist configurable in `system.yaml`. Captain approval required for form submissions and JavaScript execution. SSRF protection reuses existing `HttpFetchAgent` guards
- **Integration** — BrowseAgent registers `browse_web`, `screenshot_page`, `fill_form` intents. Tool Layer (Phase 25b) exposes as `browser` tool for any agent to use
- **Perception pipeline** — browser output feeds through VisualPerception (Phase 2, Sensory Cortex) for screenshot-to-semantic compression

---

### Captain's Yeoman — Personal AI Assistant (Phase 36)

*"The Captain's Yeoman handles everything the Captain shouldn't have to think about."*

ProbOS's adoption funnel starts here. OpenClaw went viral because it gave every user immediate personal value. ProbOS has an entire crew behind a front door that requires understanding agents, pools, and trust to get started. The Yeoman is the front door that makes ProbOS useful to *anyone*, not just developers. Every ProbOS instance starts as a personal AI assistant. The engineering, science, and medical capabilities are there from the start — they activate when needed.

In Star Trek, the Captain's Yeoman handles personal affairs, scheduling, communications, and briefings. ProbOS's Yeoman does the same — it's the default conversational interface, the first agent every user meets.

**YeomanAgent — Bridge Crew Member**

- **Position:** Bridge-level agent, serving the Captain directly (not assigned to any department)
- **Default interface:** The first agent users interact with — no commands needed, just conversation
- **Personality:** Helpful, proactive, learns the Captain's preferences over time
- **Trust level:** Starts as Ensign (limited autonomy), earns agency through demonstrated reliability (AD-357)

**Core Capabilities:**

- **Conversational interaction** — natural language by default. "What's on my schedule?" "Remind me to review the PR tomorrow." "What did I work on last week?" No slash commands required (but still supported)
- **Personal task management** — calendar, reminders, notes, to-do lists, daily briefings. Uses episodic memory to remember past conversations and preferences
- **Research & information** — web research (via BrowseAgent, Phase 35), knowledge queries, summarization. "What's the latest on the Rust rewrite debate?" → delegated to crew with results presented conversationally
- **Crew delegation** — seamless routing to specialists when needed:
  - "Build me a script that..." → Engineering (Builder pipeline)
  - "What's the system health?" → Medical (Diagnostician)
  - "Design a new feature for..." → Science (Architect)
  - "Review the latest build" → Engineering (Code Review Agent)
  - The user doesn't need to know which department handles what — the Yeoman routes intelligently
- **Personalization** — learns preferences via episodic memory and Hebbian learning:
  - Communication style (verbose vs. concise, technical vs. plain)
  - Frequently used workflows (auto-suggest "morning briefing" at 9am)
  - Tool preferences (which editor, which browser, which calendar)
  - Project context (remembers which repos, which branches, active work items)
- **Extension skills** — personal capabilities installable as extensions (Phase 30):
  - Home automation (smart lights, thermostat, locks)
  - Finance tracking (expense logging, budget alerts)
  - Fitness/health (workout logging, meal tracking)
  - Social (draft emails, manage contacts, schedule meetings)
  - Each skill is an extension — install what you need, ignore what you don't

**Multi-Channel Presence (leverages Phase 24):**

- **CLI** — the existing ProbOS shell becomes conversational-first
- **Web UI (HXI)** — chat interface with the Yeoman, agent visualization in the background
- **Discord** — personal assistant in DMs, team assistant in channels
- **Mobile PWA** — "Hey Yeoman, what's my schedule?" from your phone
- **Voice** — STT/TTS/wake word for hands-free interaction
- **Slack / Teams** — enterprise channels (commercial tier)

**Architecture:**

```
User ──→ Yeoman (Bridge) ──→ ┌─ Conversational response (direct)
                              ├─ Engineering (Builder, Code Review)
                              ├─ Medical (Diagnostician, Vitals)
                              ├─ Science (Architect, CodebaseIndex)
                              ├─ Security (threat analysis)
                              ├─ Extension Skills (personal tasks)
                              └─ External (BrowseAgent, Federation)
```

- `YeomanAgent` extends `CognitiveAgent` — full trust, Hebbian, memory integration
- Intent classification: Yeoman classifies user requests and routes to the appropriate department or handles directly
- Context management: maintains conversation context across channels (same Yeoman, whether you talk via CLI, Discord, or mobile)
- Proactive suggestions: "You usually review PRs around this time — there are 3 pending" (earned at Commander+ trust level, AD-357)

**The Adoption Funnel:**

1. **Install** → `pip install probos` → meet the Yeoman → immediate personal value
2. **Daily use** → Yeoman handles tasks, learns preferences → user stays engaged
3. **Discovery** → "Wait, I can build custom agents?" → user explores the crew
4. **Power use** → extensions, Ship Classes, Builder pipeline → user becomes Captain
5. **Scale** → federate, build for others, join the Nooplex → ecosystem growth

**OSS vs Commercial Boundary:**

| Layer | OSS (Phase 36) | Commercial |
|-------|-----------------|------------|
| Agent | YeomanAgent, routing logic, personalization | — |
| Memory | Episodic memory, preference learning | Cross-device sync, cloud backup |
| Channels | CLI, web, Discord | Teams, Slack Enterprise, SMS |
| Skills | Extension API, community skills | Premium skill marketplace |
| Hosting | Self-hosted | ProbOS Cloud (managed hosting) |
| Bundle | — | Escort Ship Class (curated Yeoman package) |
| Fleet | — | Nooplex fleet-wide assistant coordination |
| Enterprise | — | SSO, compliance, audit logs, multi-user admin |

**Dependencies:** Phase 24 (channels), Phase 30 (extensions), Phase 35 (browser, onboarding). Can start with CLI + web before other channels are complete.

---

### Bundled Agent Reorganization (Future)

*"All hands, report to your departments."*

Bundled agents currently share a single "Bundled" pool group, but they serve different departments of the ship. "Bundled" is a **distribution label** (ships with ProbOS out of the box), not an organizational role. Future work will reassign bundled agents to their functional crew teams:

- **Communications** — TranslateAgent, SummarizerAgent, VoiceProvider

**Voice Provider & Ship's Computer Voice** *(nice-to-have)*

*"Computer, status report."*

The HXI currently uses browser `SpeechSynthesis` (zero dependencies, variable quality). A `VoiceProvider` ABC would allow pluggable TTS backends — from free local models to premium cloud APIs — with a custom Ship's Computer voice as ProbOS's auditory identity.

- **`VoiceProvider` ABC** — `speak(text) -> AudioBuffer`, `clone_voice(reference_audio) -> VoiceProfile`, `list_voices() -> list`. Same provider pattern as the future `ModelProvider` for LLMs
- **`BrowserVoiceProvider`** — current implementation, free, zero dependencies (default)
- **`PiperVoiceProvider`** — local ONNX-based TTS (Piper project), good quality, no GPU needed, ~50MB model
- **`FishAudioProvider`** — Fish Audio cloud API, excellent quality, voice cloning from 10s of audio, pay-per-use
- **`ElevenLabsProvider`** — alternative cloud option
- **Custom Ship's Computer voice** — clone a distinctive LCARS-style voice via Fish Audio or similar, used as ProbOS's consistent auditory identity across all instances. Voice profile stored in config, shared across federation via gossip
- **Commercial opportunity** — custom voice creation, voice marketplace, enterprise voice branding. Potential for self-hosted Fish Speech (4B param model) when GPU resources are available
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

**GitHub Copilot SDK — The Visiting Officer Transport (Primary Integration Path)**

*"Visiting specialist from Starfleet Corps of Engineers — superior tools, governed by the ship's chain of command."*

The GitHub Copilot SDK (`pip install github-copilot-sdk`) provides a first-class Python package with a full agentic runtime — not just LLM completions, but file I/O, git operations, web requests, MCP support, and iterative tool use. It wraps the same runtime powering GitHub Copilot CLI, exposed as a programmable interface. This is the concrete integration path for visiting officers.

- **Python package:** `github-copilot-sdk` — first-class SDK, also available for Node.js, Go, .NET, Java
- **Architecture:** SDK client communicates via JSON-RPC with Copilot CLI running in server mode. ProbOS creates the client, Copilot handles planning, tool invocation, file edits
- **Models:** All Copilot-available models (Claude, GPT, Gemini) — multi-model by default, selectable per task
- **Auth:** Uses existing GitHub Copilot login (OAuth credentials, env vars, or BYOK with direct API keys)
- **Billing:** Each SDK prompt counts toward existing Copilot premium request quota — no separate subscription needed
- **Governance:** Automatically inherits GitHub organization's Copilot governance policies (branch protections, required checks)
- **Status:** Technical Preview (functional, actively developed — 7.9K stars, 31 releases, MIT licensed). Not yet production-ready but suitable for prototyping
- **Key commands:** `/delegate` (branch, implement, open PR), `/fleet` (parallelized subagents), `/plan` (implementation planning)

**Visiting Officer Architecture — Who Gets Outsourced, Who Stays Native**

The question for each role: does its value come from coding capability (outsource to visiting officer) or from ProbOS-specific knowledge (keep native)?

| Role | Visiting Officer? | Rationale |
|---|---|---|
| **Builder** | **Yes — Copilot SDK** | Code generation is the bottleneck. Copilot's agentic loop (read/write/iterate/test) is superior to native single-pass + 2-retry. Clear win. |
| **Architect** | **No — stay native** | Value comes from CodebaseIndex integration — import graphs, API surface verification, `find_callers()`, pattern recipes. A generic agent produces generic designs. The native Architect knows the ship. |
| **Code Reviewer** | **No — stay native** | Reviews against Standing Orders — ProbOS's own constitution. Governance, not coding. Copilot has no knowledge of federation/ship/department tier rules. |
| **Test Writer** | **Future — Copilot SDK** | Test generation benefits from full filesystem access, reading existing test patterns, running tests iteratively. Good candidate for Phase 34 Specialized Builders. |
| **Infrastructure** | **Future — Copilot SDK** | Docker, CI/CD, config — generic coding tasks where Copilot excels. |

**The Pipeline:**

```
Native Architect (knows ProbOS — CodebaseIndex, import graphs, pattern recipes)
  → designs BuildSpec with interface contracts and Standing Orders context
  ↓
Visiting Builder (Copilot SDK — custom agent with ProbOS Standing Orders)
  → compose_instructions() provides same rules as native Builder
  → ProbOS tools exposed via MCP (CodebaseIndex, SystemSelfModel, trust)
  → receives BuildSpec as mission orders via CopilotBuilderAdapter
  → reads files, writes code, iterates, runs tests autonomously
  → produces file changes
  ↓
Native Code Reviewer (knows Standing Orders — ProbOS constitution)
  → reviews output against federation/ship/department/agent tier rules
  → soft/hard gate based on earned trust
  ↓
Native Test Gate (commit gate, smart test selection)
  → targeted tests first, full suite if targeted pass
  → fix loop delegates fixes back to visiting Builder if needed
  ↓
Captain approves
```

**Standing Orders + MCP Tools — The Visiting Officer Knows the Ship**

The Copilot SDK supports custom agents with custom instructions and MCP tool access. This means the visiting Builder isn't a generic external agent — it's a ProbOS-trained visiting officer who knows the ship's rules and can use the ship's systems.

1. **Same Standing Orders** — `compose_instructions()` assembles the full chain (Federation Constitution → Ship → Engineering Department → Agent) and passes it as the custom Copilot agent's system instructions. The visiting Builder follows the exact same rules as the native Builder. Same quality gates, same coding conventions, same test-writing standards.

2. **ProbOS Tools via MCP** — ProbOS exposes internal capabilities as MCP tools the visiting Builder can call during its agentic loop:

| ProbOS MCP Tool | Capability |
|---|---|
| `codebase_index.query()` | Structural search — classes, methods, API surface |
| `codebase_index.find_callers()` | Cross-file reference search |
| `codebase_index.get_imports()` | Import graph traversal |
| `codebase_index.find_tests_for()` | Test file discovery by naming convention |
| `system_self_model.to_context()` | Current system topology, health, departments |
| `standing_orders.get_department()` | Department-specific protocol lookup |

3. **Same governance** — Code Review checks the visiting Builder's output against the same Standing Orders it was given. The trust model tracks outcomes. The Captain approves. The visiting officer's output is indistinguishable from native output in the governance pipeline.

The difference between native and visiting is the execution engine (ProbOS perceive/decide/act vs Copilot SDK agentic loop), not the rules or the knowledge. Same brain rules, better hands.

**The Apprenticeship — How Native Crew Learns from Visiting Officers**

The visiting officer pattern isn't just delegation — it's a training program. ProbOS's existing learning mechanisms allow the native Builder to improve by observing the visiting Builder's work:

1. **Hebbian learning** — the trust/routing system already learns which agents succeed at which task types. If the visiting Builder consistently produces higher-quality code (fewer test failures, fewer review issues), the Hebbian router learns to prefer it for certain task types. The native Builder's Hebbian weights track which tasks it handles well vs. which should go to the visitor.

2. **Cognitive Journal** (Phase 32) — records every LLM request/response. Both native and visiting Builders working on similar tasks creates a comparative dataset: what prompts work better, what approaches produce fewer fix retries, what patterns succeed on first attempt.

3. **Dream consolidation** — dream cycles replay successful patterns. The native Builder's dreams would incorporate patterns observed from the visiting Builder's successful outputs. Repeated successful patterns (e.g., "always read imports before editing") become L3-L4 abstractions (Sensory Cortex) that inform future native builds.

4. **Standing Orders evolution** — agent-tier Standing Orders are evolvable through the self-mod pipeline. If the visiting Builder consistently follows patterns that succeed (e.g., specific test-writing conventions, import validation), those patterns can be proposed as Standing Orders updates — codifying learned best practices into the native crew's constitution.

5. **Capability overlap routing** — when both native and visiting Builders exist for the same task type, the system routes based on trust scores, historical accuracy, cost, and latency. Hebbian routing handles this naturally. Over time, the native Builder earns back task types it's gotten good at, while the visitor handles the ones that still exceed native capability.

The end state: the native Builder eventually handles routine builds independently, having learned from watching the visiting officer work. The visiting officer gets called in for complex, multi-file, architectural builds that require superior tooling. The ship trains its own crew.

**GitHub Copilot Capabilities as Federated Services**

Beyond the Builder role, Copilot's other capabilities can serve as federated services:

- **Semantic code search** — Copilot indexes the repo with embedding-based search. ProbOS dispatches "find code related to X" queries to Copilot when internal keyword search returns insufficient results. Complementary to internal CodebaseIndex: keyword (fast, exact) + semantic (meaning-based, via Copilot)
- **PR creation and review** — Copilot natively creates PRs, suggests reviews, runs CI. ProbOS delegates "create PR from these changes" via `/delegate` command
- **Issue triage** — Copilot reads GitHub issues via native MCP server. ProbOS Architect queries for issue context when designing proposals
- **Parallel fleet** — Copilot's `/fleet` command runs parallelized subagents, complementing ProbOS's Transporter Pattern

**Trust Model for External AI Tools**

- All external tools start with **probationary trust** — `Beta(1, 3)`, same as newly designed agents
- Trust builds per-tool based on task quality outcomes: did the code pass tests? Did review catch issues? Were fix retries needed?
- External tool failures degrade trust, triggering fallback to internal capabilities or escalation to Captain
- **Cost tracking** — external tools consume premium request quota. LLM Cost Tracker (Phase 33) attributes spending per-tool alongside per-agent
- **Capability overlap resolution** — when both internal and external capabilities exist, the system routes based on: (1) trust scores, (2) historical accuracy, (3) cost, (4) latency. Hebbian routing handles this naturally

**Connection Mechanisms**

| Tool | Protocol | Adapter | Status |
|------|----------|---------|--------|
| GitHub Copilot | **Copilot SDK (Python)** | `CopilotBuilderAdapter` | **Implemented (AD-351–355)** — SDK in Technical Preview |
| Claude Code | Anthropic SDK / A2A | A2A Federation Adapter | Alternative — requires separate API key |
| Cursor / Others | A2A / MCP | Protocol-dependent | Future |

The Copilot SDK is the primary integration path — it uses the existing Copilot subscription, supports multiple models (including Claude), and provides a Python-native interface. The existing MCP and A2A adapters (Phase 29) remain available for tools that use those protocols.

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

**Extension-First Architecture (Sealed Core, Open Extensions)**

*"Don't rip open the bulkhead to rewire the ship — plug a new module into the standardized EPS conduit."*

Inspired by the Microsoft Dynamics 365 F&O evolution from overlayering to extensions. In the legacy model, developers modified any code in the system with changes overlaying on top of lower layers (SYS → ISV → VAR → CUS). This caused merge conflicts, blocked upgrades, and introduced cascading instability. The solution: seal the foundation and provide extension points. Developers can create new or extend existing — never modify core.

ProbOS faces the same problem. Today, the Builder agent modifies core source files directly. Every self-improvement touches the foundation — `trust.py`, `hebbian.py`, `builder.py`. Every change requires Captain approval because the blast radius is unconstrained. As the codebase grows, this becomes untenable.

**The principle: Builder creates extensions by default, not overlays.**

- **Sealed Core** — runtime infrastructure (IntentBus, TrustNetwork, HebbianRouter, ConsensusManager, PoolManager, DAGExecutor) is read-only to the Builder. These systems define contracts (ABCs, Protocols, event hooks, registered intents) but their implementation is frozen
- **Extension points** — the core exposes well-defined hooks:
  - `AgentRegistry.register()` — add new agents (already exists)
  - `ToolRegistry.register()` — add new tools (Phase 25b)
  - `SkillRegistry.register()` — add new skills (`skill.yaml`, Phase 30)
  - `ChannelAdapter.register()` — add new communication channels (Phase 24)
  - `ModelProvider.register()` — add new LLM providers (Phase 32)
  - `PerceptionPipeline.register()` — add new perception processors (Sensory Cortex Phase 2)
  - `IntentBus.subscribe()` — listen for events (already exists)
  - `EventHook.register()` — lifecycle hooks (on_startup, on_shutdown, on_intent, on_trust_change)
- **Extension directory** — Builder-created extensions live in `src/probos/extensions/` (agents, tools, skills) separate from core. Version-controlled, user-owned, upgrade-safe
- **Contract stability** — core extension points follow semver. Breaking changes require major version bump + migration guide. Extensions written for v1 contracts work on v1.x forever

**Graduated Autonomy (the trust unlock):**

The extension model enables different approval tiers based on risk:

| Change Type | Risk | Approval Required |
|---|---|---|
| New agent/skill/tool using public APIs | Low | Auto-approve (sandboxed) |
| New extension needing a new hook | Medium | Captain review |
| Core modification (rare) | High | Full approval pipeline |

This is the path to letting ProbOS improve itself while the Captain sleeps. Extensions can't break the ship — they can only add to it. The Builder becomes productive within safe boundaries without waking the Captain for every bolt it tightens.

**Evergreen Updates:**

When the core ProbOS codebase updates (new release, bug fix, feature addition), user extensions survive the upgrade. As long as the core doesn't break its contracts with the extension points, all Builder-created agents, skills, and tools continue working. This is critical for adoption — users invest in customization knowing their work is protected across versions.

**Overlayering (legacy path):**

Direct core modification remains possible but is the exception, not the rule. Reserved for:
- Genuine core defects (bug fixes)
- New extension point creation (expanding the API surface)
- Architectural evolution (major version changes)

All overlay modifications require full Captain approval + red team verification. The Builder should propose "can we add an extension point for this?" before "can I modify the core?"

**Extension Toggle (Feature Flags for Extensions)**

Extensions are hot-loadable and individually togglable — enable, disable, or remove any extension at runtime without restarting ProbOS or modifying code.

- **`probos extensions list`** — show all installed extensions with status (enabled/disabled), trust score, origin (self-designed, shared, marketplace)
- **`probos extensions enable/disable <name>`** — toggle an extension on or off. Disabled extensions are unsubscribed from the IntentBus, unregistered from the ToolRegistry, and excluded from routing — but their code is preserved for re-enabling
- **`probos extensions remove <name>`** — uninstall completely (with confirmation)
- **HXI toggle panel** — visual switch for each extension in the dashboard. Captain can see what's active and flip switches without touching the shell
- **Safe defaults for new users** — ProbOS ships with a curated set of core extensions enabled. Advanced extensions (self-improvement, shell access, file writing) start disabled. Novice users get a safe, bounded experience out of the box. Power users enable what they need
- **Extension profiles** — saved presets: "minimal" (chat only), "developer" (build pipeline + code tools), "full" (everything). `probos init` lets users pick a profile during onboarding

**User Safety (the OpenClaw lesson)**

AI assistants that modify files directly are powerful but dangerous — especially for non-technical users. A misinterpreted instruction can delete files, overwrite work, or corrupt a project. This is the overlayering problem applied to end users' personal data.

ProbOS's extension model provides safety by construction:
- Extensions operate within their sandbox — they can create new files in designated directories, but cannot modify arbitrary user files unless explicitly granted permission
- Destructive operations (file delete, git reset, shell commands) are gated by the existing Captain approval pipeline regardless of extension autonomy level
- The Builder agent proposes changes as diffs for review, not silent file overwrites
- Rollback is trivial: disable or remove the extension, and everything it created is isolated
- This makes ProbOS safe enough for novice users while remaining powerful for experts — the extension model is the safety rail

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

### The Nooplex — Model of Models (Long Horizon)

*"The destination isn't a single ship. It's a civilization of ships — each contributing its strengths to the collective intelligence of the fleet."*

ProbOS is the ship. The Nooplex is what emerges when ships combine their cognitive capabilities at scale. The "Model of Models" is the Nooplex's core concept: a distributed meta-intelligence that routes cognition to the best brain for each task — across models, across agents, across ships, across the universe.

**Why Model of Models**

All humans have similar brains, but no two brains are the same. ProbOS agents have chassis diversity (different types, capabilities, prompts) but limited brain diversity — currently 2 models powering 54 agents. Real cognitive ecosystems need fundamentally different reasoning architectures working together. The Nooplex provides this by making model diversity a fleet-wide resource, not a per-ship configuration.

**Architecture Layers**

```
Level 0: Single Model       "One brain, one agent"
         └─ Current state: Sonnet/Opus via Copilot proxy

Level 1: Model Registry     "Many brains, one ship"
         └─ ModelRegistry, provider abstraction, neural routing (Phase 32)

Level 2: Fleet Intelligence  "Many brains, many ships"
         └─ Ships share model performance data via federation gossip

Level 3: Nooplex             "Model of models"
         └─ Distributed meta-router across the entire federation
```

**How It Emerges**

The Nooplex isn't built top-down — it emerges from the building blocks:

1. **Model Diversity** (Phase 32) — each ship routes to N model providers with Hebbian-learned routing weights. Ship A discovers "Gemini excels at API design." This is Level 1.

2. **Cognitive Journal** (Phase 32) — each ship tracks what works: which models, which prompts, which task types produce the best outcomes. This creates the training data for meta-routing.

3. **Federation Gossip** (built) — `NodeSelfModel` already broadcasts capability summaries to peers. Extend it to include model performance data: `{model: "claude-opus-4", task_type: "code_gen", success_rate: 0.94, avg_latency_ms: 4200, cost_per_1k_tokens: 0.015}`. This is Level 2.

4. **Distributed Hebbian Learning** — Hebbian weights flow across the federation. Ship A's learning that "Claude excels at refactoring" strengthens Ship B's routing weight for the same pattern — without Ship B having to learn it independently. Fleet-wide experience sharing.

5. **Meta-Router** — a federation-level router that answers: "Given this task, which ship has the best model for the job?" Routes not just to local models but to remote ships with optimal model access. Ship A has cheap local GPUs; Ship B has Opus API access; Ship C has a specialized fine-tuned model for security analysis. The Nooplex routes security tasks to Ship C, bulk tasks to Ship A, and complex reasoning to Ship B.

**Key Principles**

- **No central coordinator** — the Nooplex is fully decentralized. No master node. Each ship maintains its own view of fleet capabilities via gossip. Eventual consistency, not strong consistency.
- **Trust-weighted sharing** — model performance data from low-trust ships is discounted, same as any federated information. A ship can't poison the fleet's routing intelligence without earning trust first.
- **Cost-aware** — the meta-router factors in cost, latency, and availability alongside quality. The cheapest model that meets the quality threshold wins.
- **Privacy-preserving** — ships share model performance *metadata* (success rates, latency, cost), not prompt content. No ship sees another ship's conversations. The cognitive journal stays local.
- **Infinite scalability** — adding a new ship with a new model provider immediately enriches the entire fleet's cognitive diversity. No configuration, no central registry — gossip propagates availability.

**Relationship to Sensory Cortex**

The Sensory Cortex Architecture (Northstar II) solves the *input* side: how to compress infinite information into a finite context window. The Model of Models solves the *processing* side: how to route that compressed input to the optimal brain. Together they create the "infinite context window" aspiration:

- **Infinite input** — Sensory Cortex compresses any amount of data to fit any context budget
- **Infinite processing** — Model of Models routes to the best brain regardless of where it runs
- **Infinite memory** — Cognitive Journal + Episodic Memory + Knowledge Store + Dream consolidation

The Nooplex isn't just about AI. It's about human-agent cooperation at scale — humans as Captains, agents as crew, models as brains, ships as communities, the federation as civilization. ProbOS is the ship that takes you there.

---

## Backlog

*"Ensign, add that to the maintenance schedule."*

Items identified during development that aren't urgent but would improve code quality, maintainability, or developer experience. Pulled into phases when relevant.

| Item | Description | Identified By | Notes |
|------|-------------|---------------|-------|
| Modularize shell commands | Extract `ProbOSShell` command methods into a `shell/commands/` package. Each command as its own module, independently testable. `shell.py` is 900+ lines at 64% coverage — modular structure would improve maintainability and test coverage. | Visiting Officer (AD-356) | Convert `shell.py` file → `shell/__init__.py` package. Needs migration plan for existing tests. Good candidate for Phase 35 (UX & Adoption) or standalone cleanup AD. |
| Build snapshot system | Shadow git repo tracking every file change during builder execution. Granular undo per file change, not just per-commit. Revert partial builds when test gate catches issues in specific files. Independent of project's own git history. | OpenCode (2026-03-20) | Phase 30 or 32. OpenCode uses `--git-dir` + `--work-tree` for isolation. Complements test gate — snapshot before build, rollback on failure. |
| LSP-enhanced CodebaseIndex | Spawn LSP servers (pyright, typescript-language-server) for type-aware code intelligence. Precise find-references, workspace symbols, real-time diagnostics before test runs, rename refactoring with full type safety. Upgrades AST-only CodebaseIndex to compiler-grade understanding. | OpenCode (2026-03-20) | Phase 29c extension. Requires language detection + server lifecycle management. Start with pyright (Python only). Significant upgrade to Science team capabilities. |
| Conversation compaction with tool output pruning | For long-running sessions, walk backwards through history keeping recent tool outputs but erasing old ones (keep tool name + inputs as markers). Protected tools (like skill) never pruned. Configurable token threshold. | OpenCode (2026-03-20) | Sensory Cortex extension. Relevant for Captain's Ready Room (Phase 34) multi-agent briefings and long builder sessions. Complement to existing REFLECT_PAYLOAD_BUDGET. |
| Session export and sharing | Export build sessions, diagnostic sessions, Ready Room briefings as portable, replayable artifacts. Captain's Log as searchable, shareable decision history. | OpenCode (2026-03-20) | Phase 34 (Captain's Log). Cognitive Journal (Phase 32) captures data; sharing is the presentation layer. Federation-relevant: share sessions between ships. |

---

## Bug Tracker

*"Captain, we've detected an anomaly in Deck 7."*

Bugs found during development or testing. Squash as found when possible; queue here when multiple bugs need coordinated fixing. Numbered as BF-NNN (Bug Fix).

| BF | Summary | Severity | Status |
|----|---------|----------|--------|
| BF-001 | Self-mod proposal on knowledge questions | Medium | **Closed** (AD-348) |
| BF-002 | Agent orbs escape pool group spheres | High | **Closed** (AD-349) |
| BF-003 | "Run diagnostic" bypasses VitalsMonitor, asks user for alert data | Medium | **Closed** (AD-350) |
| BF-004 | Transporter HXI visualization not rendered | Medium | **Closed** |
| BF-005 | HTTP consensus docs drift (AD-150 removed gating) | Low | **Closed** |
| BF-006 | Quorum trust docs drift in consensus.md | Low | **Closed** |

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

!!! info "Want to contribute?"
    See the [Contributing guide](contributing.md) for how to get involved.
