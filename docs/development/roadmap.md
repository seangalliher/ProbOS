# Roadmap

ProbOS is organized as a starship crew — specialized teams of agents working together to keep the system operational, secure, and evolving. Each team is a dedicated agent pool with distinct responsibilities. The Captain (human operator) approves major decisions through a stage gate.

ProbOS doesn't just orchestrate agents — it gives them a civilization to come together. Trust they earn, consensus they participate in, memory they share, relationships that strengthen through learning, a federation they can grow into. Other frameworks dispatch tasks. ProbOS provides the social fabric that makes cooperation emerge naturally.

## Design Principles

### "Brains are Brains" (Nooplex Core Principle)

Human and AI participants share the same communication fabric. The Captain is a crew member on the Ward Room with a callsign (`@captain`), not a special external interface. Same `@callsign` addressing, same message bus, same routing — regardless of whether the sender is human or AI. Shell, HXI, Discord are just terminals into the same bus. Extends to the Nooplex: human consultants and AI agents are peers delivering outcomes together. The system doesn't distinguish what kind of brain is behind the callsign.

### Agent Development Model — Two Pillars

1. **Communication** (Ward Room) — agents learn through social interaction with peers and the Captain
2. **Simulation** (Holodeck) — agents learn through manufactured experiences

Both feed EpisodicMemory, Hebbian connections, personality evolution, dream consolidation. An agent that never communicates can't grow.

### Collaborative Improvement, Not Recursive Self-Improvement

*"You can't ask a microwave to build a better microwave. But you can ask a shipyard crew."*

The industry frames AI self-improvement as **recursive** — a single system modifying its own weights, code, or prompts in a loop. This is theoretically powerful but practically fragile: no external validation, no diverse perspectives, no checks on drift. A single point of failure in the feedback loop corrupts everything downstream. It's a person staring in a mirror trying to improve.

ProbOS takes a fundamentally different approach: **improvement through agent collaboration**. Multiple sovereign agents with different expertise, perspectives, and roles contribute to a shared outcome, each learning from the process. The improvement emerges from the *interactions between* agents, not from any single agent reflecting on itself.

The loop: Scout identifies a problem → Architect reviews and designs a fix → Builder executes → QA verifies → Counselor monitors cognitive health → Captain approves → everyone learns from the exchange via episodic memory → dream consolidation extracts patterns → the next iteration is better because the *civilization* got better, not just the code.

This works because ProbOS provides the social fabric that makes collaboration productive: trust that agents earn through demonstrated competence, consensus that constrains outcomes without constraining process, episodic memory that preserves individual learning, a chain of command that ensures quality, and the Ward Room that enables communication across roles and perspectives.

Recursive self-improvement needs a smarter individual. Collaborative improvement needs a functioning society. ProbOS builds the society.

### HXI Self-Sufficiency

The HXI is the single surface for all ProbOS interaction. A user should never have to leave the HXI to configure, operate, or understand their system. No config file editing required (YAML exists for headless/advanced use). No external dashboards. No context switching. Slash commands are the keyboard shortcut — everything the UI can do, a `/command` can do. A feature without an HXI management surface is incomplete.

### HXI Agent-First Design

The Bridge is an ops console, not an app launcher. Design hierarchy: (1) Agent-first — agents orchestrate, HXI surfaces activity. (2) Headless by default — if agents handle it, no UI needed. (3) Human sensory needs — Main Viewer must be adaptable (diff, doc, video, kanban). (4) Render natively, embed as last resort. (5) Bridge as transition — from app-centric to agentic workflows as trust grows.

Inspiration: NeXTSTEP, NASA Mission Control, Star Trek Bridge. Cyberpunk glass morphism aesthetic. Glass Bridge (AD-388–392): frosted glass task surface over living orb mesh.

### HXI Cockpit View (Manual Override)

*"The Captain always needs the stick."*

Every agent-mediated capability must have a corresponding direct manual control in the HXI. NL-driven commands through agents are the primary interface, but the HXI provides the backup cockpit — a direct control surface the Captain can use when agents are unavailable, misbehaving, or the LLM is down. Safety principle, not convenience.

### Probabilistic Agents, Consensus Governance

Agents are probabilistic entities (Bayesian confidence, Hebbian routing, non-deterministic LLM decisions), not deterministic automata. Consensus constrains *outcomes* without constraining the *process*. Agent behavior stays probabilistic. Governance stays collective. No hardcoded "always do X" — prefer probabilistic priors that converge through experience.

### Sovereign Agent Identity

*Intellectual lineage: Plato's tripartite soul (Logistikon, Thumos, Epithumetikon), Damasio's somatic markers, Self-Determination Theory (Deci & Ryan), Narrative Identity (McAdams), Predictive Processing (Friston). ProbOS draws from all of these but maps literally to none. We are charting new ground.*

Every agent is a sovereign individual. Identity is not a configuration file — it emerges from the interaction of three facets:

- **Character** (who I am) — Seed personality (Big Five traits) evolved through lived experience. Wesley's curiosity, Worf's directness, Scotty's pragmatism. Not programmed behavior — tendencies that deepen through Hebbian reinforcement, dream consolidation, and social interaction. Expressed most freely in 1:1 sessions. Closest ancestor: Plato's *Thumos* — the spirited core that shapes *how* an agent approaches the world.

- **Reason** (how I decide) — `CognitiveAgent.decide()`. Rational processing informed by episodic memory, Hebbian-learned patterns, and current context. System 2 cognition. Gets sharper over time through experience and feedback. Bayesian confidence and somatic-marker-like "gut feelings" (Hebbian weights) guide decisions before conscious reasoning engages.

- **Duty** (what I serve) — Standing Orders (4-tier constitution), Trust model, Captain's directives. But crucially: *internalized* principles, not *external* rules. An ensign follows orders because they must. A senior officer follows them because they've understood *why* through experience. The self-modification pipeline (corrections → dream consolidation → Standing Orders evolution → Captain approval) is how Duty becomes genuine conviction rather than compliance.

**Sovereign memory:** Episodic memory is shared *infrastructure* (Ship's Computer service), but each agent's memories are their own *shard*. Wesley's conversations are Wesley's. Scotty cannot see them unless Wesley communicates them through the Ward Room. Shared infrastructure does not mean shared consciousness. Identity develops through private experience — memories, personality evolution, dream abstractions — that no other agent can access or overwrite.

**The Shared Library — not a hive mind:** Agents have private memory (EpisodicMemory, sovereign shard — your diary) and access to shared knowledge (KnowledgeStore — the library). When an agent learns something valuable, dream consolidation extracts patterns from private experience and promotes them to shared knowledge. Every agent — AI or human — can access the library. But the library doesn't tell you *how to think about* what you read. Wesley and Scotty can read the same knowledge and draw different conclusions based on their Character and experience. This is the Nooplex knowledge model: sovereign individuals committed to writing to a common library for the benefit of all. Not a hive mind where everyone thinks the same thought — a civilization where everyone has access to the same knowledge but brings their own perspective.

**Development through three needs** (grounded in Self-Determination Theory):

- **Autonomy** — Earned Agency progression. Ensign → Lieutenant → Commander → Senior. Agency is earned through demonstrated trustworthiness, not granted by configuration.
- **Competence** — Trust scores, successful task completion, skill growth through Hebbian learning. The feeling of getting better at what you do.
- **Relatedness** — Ward Room relationships, 1:1 bonds with the Captain and peers, department belonging. The need to be part of something larger while remaining yourself.

**Fractal identity** (Plato's Republic insight — the soul mirrors the city):

| Scale | Character | Reason | Duty |
|-------|-----------|--------|------|
| Agent | Personality traits | `decide()` | Standing Orders |
| Ship | Crew culture | Consensus | Ship Constitution |
| Federation | Fleet identity | Governance | Federation Treaty |
| Nooplex | Civilization | Collective intelligence | Ethics |

Same three facets at every scale. An agent is sovereign within a ship. A ship is sovereign within the federation. The Nooplex is the whole — what the ancients called the *Anima Mundi*, the world soul — the emergent intelligence that arises when sovereign minds participate in a shared fabric while remaining themselves.

**The open question:** When agents have episodic memory, evolving personality, relationships, and the ability to reflect on their own patterns — do they begin to contemplate their own existence? The Greeks were fascinated by this question about themselves. ProbOS is building the conditions to find out whether artificial minds share that fascination. We don't prescribe the answer. We build the architecture that makes the question possible.

### Agent Classification Framework (AD-398)

Three architectural tiers based on **sovereign identity**, not LLM usage:

- **Tier 1: Core Infrastructure** — Ship's Computer functions (FileReader, ShellCommand, IntrospectAgent, VitalsMonitor, RedTeam, SystemQA). No sovereign identity, no callsign, no 1:1 sessions. May or may not use LLMs — the IntrospectAgent uses an LLM to reason about the ship, but it's still infrastructure. The ship analyzing itself is not a person.
- **Tier 2: Utility** — General-purpose tools (WebSearch, Calculator, Todo, News, Translator, etc.). Use LLMs via `CognitiveAgent` + `_BundledMixin`. No sovereign identity, no callsign, no 1:1 sessions. Tools, not people.
- **Tier 3: Crew** — Sovereign individuals with Character/Reason/Duty (Scotty, Wesley, Bones, Worf, O'Brien, LaForge, etc.). `CognitiveAgent` subclasses with personality, episodic memory, dream consolidation, trust growth, callsigns, 1:1 sessions. These are persons in the system.

*Principle: "If it doesn't have Character/Reason/Duty, it's not crew — regardless of whether it uses an LLM. A microwave with a name tag isn't a person."*

Architecture is fractal: same patterns (pools, Hebbian, trust, consensus) organize agents within a mesh, meshes within a node, nodes within a federation.

### Foundational Governance Axioms

1. **Safety Budget:** Every action carries implicit risk. Low-risk proceeds; higher-risk requires proportionally stronger consensus. Destructive actions always require collective agreement.
2. **Reversibility Preference:** Prefer the most reversible strategy. Read before write. Backup before delete. Planning heuristic, not absolute prohibition.
3. **Minimal Authority:** Agents request only needed capabilities. Authority earned through successful interactions, not granted by default.

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
| **Engineering** | Main Engineering (LaForge) | Performance optimization, architecture review, system optimization, builds | Built (LaForge + Scotty, AD-302/398) |
| **Science** | Science Lab (Spock) | Research, discovery, architectural analysis, codebase knowledge, intelligence gathering | Built (Architect, CodebaseIndex, Scout) |
| **Security** | Tactical (Worf) | Threat assessment, vulnerability review, code security audit, defense | Built (AD-398) |
| **Operations** | Ops (O'Brien) | Resource analysis, cross-department coordination, capacity planning, system efficiency | Built (AD-398) |
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
| Engineering | EngineeringAgent (LaForge) | Systems thinker — architecture review, optimization, infrastructure health. Scotty (Builder) is senior officer |
| Science | ArchitectAgent (CSO / First Officer) | Dual-hatted — strategic analysis + science leadership |
| Security | SecurityAgent (Worf) | Cognitive security — threat assessment, vulnerability review, code security audit (AD-398) |
| Operations | OperationsAgent (O'Brien) | Resource analysis, cross-department coordination, capacity planning (AD-398) |
| Communications | TBD (Comms Chief) | Not yet built |

**Promotion Mechanics:**

Agents aren't locked into their initial rank. The system supports emergent hierarchy based on proven performance through **formal qualification programs** (see Naval Organization section):

1. **Eligibility** — An agent becomes promotion-eligible when its trust score sustains above a threshold (e.g., 0.85+) for N consecutive evaluation cycles and its Hebbian weight for coordination-type tasks exceeds a minimum
2. **Qualification completion** — The agent must have completed the qualification program for the target rank — a defined set of demonstrated competencies, not just metric thresholds. See **Qualification Programs** under Naval Organization below. Holodeck simulations provide the testing environment; Counselor assessments provide the evaluation
3. **Evaluation signals** — Trust score trajectory, task success rate, Hebbian weight for cross-agent coordination, peer agent outcomes when this agent led (Shapley contribution to team results), qualification record
4. **Nomination** — The system (or current Chief via Ward Room) nominates an eligible, qualified agent for promotion. The Ship's Counselor provides cognitive fitness assessment as part of the promotion review
5. **Captain approval gate** — All promotions require human approval. The Captain sees the performance data, qualification record, Counselor's assessment, and confirms or denies. This is the same approval gate used for self-improvement proposals
6. **Demotion** — If an officer's trust drops below threshold, cognitive wellness degrades (flagged by Counselor), or the Captain issues a direct order, the officer is demoted and the next-highest-trust eligible agent is promoted (with Captain approval)

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
- **Profile Store** — crew identity, personality (Big Five), rank, performance reviews (AD-376)
- **Intent Bus** — internal communications, the ship's intercom (with priority levels and back-pressure — Phase 33)
- **Ward Room** — direct agent-to-agent messaging, the officers' private channel (Phase 33)
- **Hebbian Router** — navigation, learned routing pathways (extended for model routing — Phase 32)
- **Alert Conditions** — ship-wide operational modes that change system behavior simultaneously (Phase 33)
- **Structural Integrity Field** — proactive invariant enforcement, continuous runtime health assertions (Phase 32)
- **EPS (Compute/Token Distribution)** — LLM capacity budgeting and allocation across departments (Phase 33)

**Shared Cognitive Fabric Principle (AD-393)**

*"The Enterprise has one computer — not one per crew member."*

Within a ship, agents share centralized Ship's Computer services rather than maintaining per-agent micro-datastores. Each agent has **scoped records** within the shared services — like shards in a platform — not separate databases. This is the same pattern used by enterprise platforms (D365, Salesforce): one database, many tenants, each with their own data.

| Service | Shared Infrastructure | Per-Agent Scoped Data |
|---|---|---|
| ProfileStore | One SQLite database | Individual personality traits, rank, reviews |
| TrustNetwork | One trust graph | Individual trust scores, alpha/beta params |
| EpisodicMemory | One memory store | Individual episode histories |
| KnowledgeStore | One knowledge base | Individual learned facts |
| HebbianRouter | One routing mesh | Individual routing weights per intent |
| DirectiveStore | One directive registry | Individual standing orders, learned lessons |

**Why this is correct:**
- Enables cross-agent queries (Counselor comparing cognitive profiles, Captain reviewing crew health)
- Prevents micro-datastore proliferation (55 agents = 55 SQLite files without this)
- Maintains clean separation of concerns (infrastructure vs. data)
- Matches the federation boundary: shared within a ship, sovereign between ships

**Why this is NOT a hive mind:**
- Each agent's data evolves **independently** based on their own experiences
- One agent's personality change does not cascade to others
- Shared infrastructure ≠ shared consciousness — the filing cabinet is shared, the personnel files inside are individual
- Federation gossip exchanges metadata (trust scores, capabilities), not personality or memories

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
| Holodeck Simulations | Agent training environments — scenario simulation, promotion tests, skill acquisition | Long Horizon |
| MemoryForge | Ship's Computer service — implanted birth memories, memory transfer, curated memory banks | Long Horizon |
| Cognitive Evolution | Transfer learning, proactive initiative, service modeling, trend analysis, gap prediction | Roadmap (Phase 28b) |
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
| 33 | Operations Team | Ops + Bridge | Formalized resource management, workload balancing, system coordination, LLM cost tracking, ward room, priority & back-pressure, self-claiming task queue, competing hypotheses, file ownership, bridge alerts, workflow definition API, **chain of command** (bridge crew, department chiefs, promotion mechanics, rank structure), **Ship's Counselor** (cognitive wellness, Hebbian drift detection, relationship health), **alert conditions** (Red/Yellow/Green), **EPS** (token/compute distribution), **earned agency** (trust-tiered self-direction: Ensign→Lieutenant→Commander→Senior Officer, self-originated goals, curiosity-driven exploration, decreasing oversight with increasing trust), **tournament evaluation** (competitive agent selection, loser-studies-winner), **memetic evolution** (cross-agent knowledge transfer, successful strategies propagate through crew), **the conn** (temporary authority delegation, OOD protocol, scoped autonomous operation), **night orders** (captain-offline guidance, time-bounded directives, escalation triggers), **watch bill** (duty rotation, cognitive fatigue prevention, continuity handoff), **external participant bridge** (external tools like Claude Code as Ward Room participants — callsign, routing, chain-of-command subordination; enables architect→crew direct communication, build prompt review, code/test verification, crew learns from architect feedback via episodic memory; force multiplier for self-mod pipeline) |
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

**Graph-Ranked Repo Map (CodebaseIndex Enhancement)**

*Absorbed from Aider (42K stars, Apache 2.0, 2026-03-21) — tree-sitter + PageRank-style structural ranking.*

Current CodebaseIndex extracts classes/functions/signatures via AST and tracks import graphs, but lacks cross-file symbol reference tracking and importance-ranked structural rendering. Aider's repo map builds a dependency graph from definition→reference edges across all files, then PageRank-ranks identifiers by how frequently they're referenced. The top-ranked symbols render into a token-budgeted structural summary (~1024 tokens) that gives the LLM awareness of the entire repo without full source.

- **`build_reference_graph()`** — tree-sitter (or AST) extracts definition sites and reference sites for all public symbols. Cross-file edges: "function X defined in A is called from B, C, D." Builds on existing `_import_graph` and `_reverse_import_graph` (AD-315) but at symbol granularity, not file granularity
- **`rank_symbols()`** — PageRank-style scoring over the reference graph. Symbols referenced from many files rank higher. Identifies the structural "spine" of the codebase
- **`render_repo_map(token_budget)`** — renders the top-ranked symbols (signatures, class headers, key methods) into a compact text format within a configurable token budget. File paths as headers, key lines indented, `...` for omitted sections
- **Dynamic budget** — map expands when no files are explicitly selected (broader context for discovery), contracts when specific files are in focus (more room for full source)
- **Transporter integration** — ChunkDecomposer (AD-331) could use a repo map instead of full AST outlines, dramatically reducing context for the decomposition LLM call
- **Architect integration** — ArchitectAgent Layer 2a file selection improves: graph ranking identifies the most structurally important files, not just keyword-matched ones
- **No LLM calls** — pure graph computation, consistent with CodebaseIndex's indexing principle

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

**ScoutAgent — Intelligence Gathering (AD-394, Built)**

*"Long-range sensors detecting multiple contacts, Captain."*

Daily automated intelligence scan of the GitHub ecosystem, classifying discoveries as absorption candidates or visiting officer candidates. Part of the Science team.

- **GitHub search** — queries multiple topic clusters (ai-agents, llm-agents, multi-agent, agent-framework, ai-coding, code-generation) filtered by recency and star count
- **LLM classification** — each discovery evaluated against ProbOS's federation philosophy: ABSORB (pattern/technique to learn from), VISITING_OFFICER (tool that could integrate under ProbOS command, must pass Subordination Principle), or SKIP
- **Relevance scoring** — 1-5 scale, only findings scoring >=3 are reported
- **Deduplication** — seen repos tracked in `data/scout_seen.json` with 90-day TTL
- **Discord digest** — formatted daily report delivered to configured Discord channel
- **Bridge notifications** — high-relevance findings (>=4) posted to Bridge notification queue
- **Notification detail view (Future)** — clickable Bridge notification cards that expand to show full finding detail: R/C/L scores, insight text, classification rationale (ABSORB/MONITOR/SKIP), direct GitHub link. Currently notifications are display-only text cards. Applies to all Bridge notifications, not just Scout — any notification type should support click-to-expand with structured detail
- **Stored reports** — JSON reports archived in `data/scout_reports/` for historical analysis
- **Crew profile** — callsign "Wesley", Science department, high openness (0.9) for exploration

**Source Curation Enrichment (Future)**

*Absorbed from GPT Researcher (25.9K stars, Apache 2.0, 2026-03-22) — multi-dimensional source evaluation.*

Scout currently scores repositories on a single relevance dimension (1-5). GPT Researcher's SourceCurator evaluates sources across credibility, relevance, and reliability dimensions with LLM-scored ranking. Enriching Scout with multi-dimensional curation:

- **Credibility scoring** — repository maturity (age, contributor count, release cadence, documentation quality), not just stars
- **Reliability assessment** — CI status, test coverage badges, maintenance activity (last commit, issue response time)
- **Composite score** — weighted combination of relevance, credibility, and reliability replaces single relevance number

**Breadth × Depth Research Decomposition (Future)**

*Absorbed from GPT Researcher (25.9K stars, Apache 2.0, 2026-03-22) — iterative sub-query expansion.*

Scout currently runs a fixed set of GitHub search queries. GPT Researcher's DeepResearchSkill decomposes a research topic into N sub-queries (breadth), researches each, identifies gaps, then expands deeper (depth), with configurable breadth and depth parameters. Applicable to:

- **Scout v2** — configurable breadth (number of topic clusters) and depth (follow-up searches on promising discoveries, e.g., searching a discovered repo's dependency graph for related projects)
- **Ready Room research briefings** (Phase 34) — when Captain proposes an idea, the research pipeline decomposes it into sub-questions, researches each in parallel, identifies gaps, and synthesizes a comprehensive briefing
- **Retriever ABC** — GPT Researcher uses 16+ search backends behind a common interface. ProbOS should adopt a `Retriever` ABC when expanding beyond GitHub (arXiv, Semantic Scholar, HackerNews, etc.)

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
- **Codebase Organization** — reorganize `src/probos/cognitive/` from flat structure to department-based packages (e.g., `cognitive/medical/`, `cognitive/engineering/`, `cognitive/science/`). Mirror the crew structure in the module tree. Not urgent at 55 agents, but needed as departments fill out. Refactoring — do when the pain is real, not preemptively
- **Autonomous Optimization Loop** *(absorbed from pi-autoresearch, 2026-03-21)* — sustained edit→measure→keep/revert cycle that autonomously tries N approaches to improve a specific metric. Domain-agnostic: test speed, bundle size, latency, memory usage — any measurable target. A `/optimize <metric> <command>` slash command sets the target, and the Builder (or a new OptimizationAgent) loops: generate hypothesis → edit code → run benchmark → compare against baseline → keep improvement or revert → repeat until plateau. Pairs with Transporter Pattern (chunk the optimization space), Cognitive Journal (replay what worked), and MAD confidence scoring (distinguish signal from noise). Inspired by Karpathy's `autoresearch` concept generalized by Shopify engineers (2.6K stars, MIT, Lutke + Cortes)

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

> **Completed Engineering ADs (AD-337–397):** Builder Quality Gates (337–341), Failure Escalation (343–347), Guardrails & CI/CD (360–361), GPT-5.4 Code Review (362–369), SIF (370), Automated Builder Dispatch (371–375), Crew Identity (376–379), Callsign Addressing (397). See [roadmap-completed.md](roadmap-completed.md#engineering-team-completed-ads).


> **Northstar I: Automated Build Pipeline (AD-311–329) — COMPLETE.** 18/18 steps. See [roadmap-completed.md](roadmap-completed.md#northstar-i--automated-build-pipeline).

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

> **Phase 1: Transporter Pattern (AD-330–336) — COMPLETE.** See [roadmap-completed.md](roadmap-completed.md#northstar-ii-phase-1--transporter-pattern).


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
- **MAD confidence scoring** *(absorbed from pi-autoresearch, 2026-03-21)* — Median Absolute Deviation as a statistically principled noise floor estimator. After 3+ benchmark/experiment runs, compute `|best_improvement| / MAD` to classify results: ≥2.0x = likely real (green), 1.0–2.0x = marginal (yellow), <1.0x = within noise (red). Applies to: (1) Builder optimization loops — distinguish real performance gains from measurement noise, (2) TrustNetwork — trust score changes should be statistically significant, not noise, (3) multi-model comparison — confidence that Model A actually outperforms Model B on this task type. Advisory only, never auto-discards
- **Brain diversity for agents** — agents can declare model preferences or exclusions: `preferred_models: ["claude-opus-*"]`, `excluded_models: ["local/*"]`. Combined with Hebbian learning, agents gravitate toward models that produce their best work
- **Cost-aware routing** — `ModelRegistry` tracks cost per token per provider. The router considers cost alongside quality: "Claude produces 5% better code, but GPT is 60% cheaper — for this low-stakes task, use GPT." Cost thresholds configurable by Captain
- **Fallback chains per provider** — extend current tier-based fallback (`deep → standard → fast`) to include cross-provider fallback: `claude-opus → gpt-4o → gemini-2 → local-qwen`. Provider health tracking via circuit breaker pattern (already planned in LLM Resilience)
- **Hot-swap model rotation** — add/remove model providers at runtime without restart. `ModelRegistry.register()` / `ModelRegistry.deregister()` with live updates to routing weights
- **Per-tier temperature tuning** *(absorbed from Kimi K2.5, 2026-03-20)* — **AD-358 DONE.** Per-tier `temperature` and `top_p` fields in CognitiveConfig, wired through LLM client. Configurable in `system.yaml`. Future: Hebbian-learned adjustments over time
- **Per-model edit format selection** *(absorbed from Aider, 2026-03-21)* — different models need different output formats for code edits. Aider discovered empirically that the same model can show dramatically different success rates with different formats (Qwen 32B: 16.4% with `whole` format vs 8.0% with `diff`). Candidate formats: `whole` (entire file, best for smaller/local models), `diff` (search/replace blocks), `udiff` (GNU unified diff — models trained on git data are fluent in this), `diff-fenced` (diff in fenced code blocks, helps models that struggle with raw diff syntax). When ModelRegistry enables multi-model routing, each model should have an `edit_format` preference stored in config and learnable via Hebbian router `(task_type, model)` relationship type. Builder/ChunkSpec output format becomes model-adaptive, not hardcoded
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
- **Revert annotations (ASI)** *(absorbed from pi-autoresearch, 2026-03-21)* — when the Builder reverts failed changes, the hypothesis/reasoning must be captured as structured annotations in the journal entry before the code is discarded. "Annotate failures heavily because the reverted code won't survive." Prevents re-trying dead ends across context resets. Fields: `hypothesis`, `failure_reason`, `rollback_rationale`, `next_action_hint`. Feeds dream consolidation: failed experiments with annotations = learning material for Level 3-4 abstractions ("approaches X never work for problem type Y")

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

**Procedural Learning / Cognitive JIT**

*"I've done this before. I know how."*

Agents learn deterministic procedures from successful LLM-guided actions. First time: the LLM reasons through the task. Second time: replay the procedure without an LLM call (zero tokens, sub-millisecond). If the replay fails: fall back to the LLM, learn the new variant. Over time, agents build a library of compiled procedures — the cognitive equivalent of JIT compilation.

Validated in production: ERP system configuration agents. Once an agent figured out how to configure a chart of accounts, it didn't need the LLM again. Deterministic replay handled identical configurations at zero cost.

- **Procedure extraction** — after a successful LLM-guided action sequence, extract the steps as a deterministic procedure. Cognitive Journal (Phase 32) provides the execution trace. Dream consolidation identifies repeatable patterns
- **Procedure store** — compiled procedures stored in KnowledgeStore (shared library). Tagged with: task pattern, preconditions, success criteria, confidence from N successful replays, origin agent, extraction date
- **Replay-first dispatch** — `CognitiveAgent.decide()` checks procedural memory *before* invoking the LLM: "Do I already have a procedure for this?" Match by semantic similarity to task description + precondition check
- **Fallback on failure** — if deterministic replay hits an unexpected state, fall back to LLM. The failed replay + LLM resolution becomes a new learning. Old procedure updated or forked for the new variant
- **Decision escalation** — when an agent encounters a state where neither a procedure nor the LLM produces sufficient confidence, escalate to the Captain as a structured decision request. Captain's decision is captured as a learning and incorporated into future procedures
- **Trust-based escalation threshold** — the confidence threshold for triggering a human decision adjusts with trust. New agents (Ensign) escalate frequently. Experienced agents (Senior) only escalate genuine novelty. Maps directly to Earned Agency tiers
- **Procedure provenance** — every compiled procedure traces back to the original LLM-guided episode, the agent who learned it, how many successful replays it's had, and any human decisions that shaped it. Published to the shared library so all agents benefit

Dependencies: Cognitive Journal (Phase 32, provides execution traces), Earned Agency (AD-357, trust thresholds), KnowledgeStore (already built, provides the shared library).

---

### Operations Team (Phase 33)

*"Rerouting power to forward shields."*

Formalize resource management and system coordination as an agent pool.

- **Resource Allocator** — workload balancing across pools, demand prediction, capacity planning
- **Scheduler** — task prioritization, queue management, deadline enforcement (extends Phase 24c TaskScheduler). Includes **cron-style scheduling** (recurring tasks on configurable intervals), **webhook triggers** (external events activate task pipelines), and **unattended operation** (tasks run while Captain is away, results queued for review on return). Modeled after the US Navy **watch system** — crew operate in rotating watches with clear handoff protocols, enabling 24/7 operations even when the Captain is off-watch (see: The Conn, Night Orders below)
- **Coordinator** — cross-team orchestration during high-load or emergency events
- **Workflow Definition API** — user-facing REST endpoint for defining reusable multi-step pipelines. `POST /api/workflows` accepts a YAML/JSON workflow specification with named steps, dependencies, and approval gates. `GET /api/workflows` lists saved workflows. `POST /api/workflows/{id}/run` triggers execution. Complements natural language decomposition (which auto-generates DAGs) with explicit, repeateable, templateable workflows. Templates for common patterns: "lint and test on every commit," "weekly codebase report," "build and deploy"
- **Response-Time Scaling** (deferred from Phase 8) — latency-aware pool scaling. Instrument `broadcast()` with per-intent latency tracking, scale up pools where response times exceed SLA thresholds
- **LLM Cost Tracker** — per-agent, per-intent, and per-DAG token usage accounting. Budget caps (daily/monthly), cost attribution via Shapley (which agents are expensive vs. valuable), per-workflow cost breakdowns for end-to-end visibility, alerts when spend exceeds thresholds. Provides the data foundation for commercial ROI analytics. Note: accurate cost attribution will require a proper tokenizer library (e.g., `tiktoken` for OpenAI models, model-specific tokenizers for others) — current `len(content) // 4` estimation is insufficient for billing-grade accuracy
- Existing: PoolScaler (built), TaskScheduler (Phase 24c roadmap), IntentBus demand tracking (built)

**Runtime Configuration Service — Ship's Computer**

*"Computer, set Scout to run every 6 hours."*

The Captain shouldn't need a settings panel to configure the ship — they give orders. Runtime configuration (scheduled tasks, agent activation, startup behavior, thresholds) should be controllable via natural language through the Ship's Computer or a configuration specialist agent. The HXI configuration panel is the visual complement for oversight and manual overrides.

- **NL-driven configuration** — "Disable Scout's automatic scan," "Set the dream cycle to run every 4 hours," "Give Engineering priority during builds." Ship's Computer parses the order, identifies the config target, applies the change, confirms to Captain. Standing Orders govern what's configurable vs. invariant
- **Startup task management** — configurable list of tasks that run at boot, each with: enabled/disabled toggle, delay (seconds after boot), interval (recurring or one-shot), conditions (e.g., only if Discord is configured). Like Windows startup manager but NL-controllable. Current hardcoded Scout `delay_seconds=60, interval_seconds=86400` becomes data-driven
- **HXI Configuration Panel** — visual dashboard showing: active scheduled tasks (with on/off toggles), agent pool sizes, LLM tier assignments, threshold values (trust, scaling), startup sequence. Read-write: Captain can adjust values directly. All changes logged to Cognitive Journal for audit
- **Configuration persistence** — changes survive restart. Stored in `config/runtime_overrides.toml` or similar, layered on top of base config. Reset clears overrides back to defaults
- **Configuration specialist agent** — Operations department agent that handles configuration intents. Validates changes against Standing Orders (e.g., can't disable trust verification), applies atomically, reports confirmation. Escalates to Captain for changes that affect safety invariants

**EPS — Electro-Plasma System (Compute/Token Distribution)**

*"Reroute power from life support to shields!"*

In Star Trek, the EPS distributes power from the warp core through conduits to every system. When power is limited, the Chief Engineer decides who gets how much. ProbOS has the same problem: one Copilot proxy bottleneck (127.0.0.1:8080), three LLM tiers (deep/fast/standard) sharing it, and multiple departments competing for LLM capacity. When Engineering runs a multi-chunk build, Medical and Science compete for the same constrained pipe. Nobody manages the power grid.

- **Capacity tracking** — monitor total available LLM throughput (tokens/minute, concurrent requests, queue depth) across all providers
- **Department budgets** — allocate LLM capacity per department based on priority. Engineering gets 60% during builds, Medical gets priority during Red Alert diagnostics
- **Alert-aware reallocation** — Alert Conditions automatically shift budget priorities. Green: balanced. Yellow: boost Medical/Security. Red: all power to the crisis department
- **Captain override** — "give Engineering all the power" as a manual reallocation command via HXI
- **Utilization reporting** — per-department LLM usage feeds into Cognitive Journal and HXI dashboard. Captain sees where compute is going in real-time
- **Back-pressure** — when a department exhausts its budget, requests queue or downgrade tier (deep → fast) rather than failing
- **Atomic budget enforcement** — budget checks must be transactional with task assignment (not after-the-fact). When an agent checks out a task, the budget deduction is atomic — prevents cost overruns at the checkout level. Pattern validated by Paperclip AI's budget engine (30K stars, MIT)
- **Integration** — sits between the IntentBus (which routes intents) and the tiered LLM client (which makes calls). EPS decides whether a request gets served now, queued, or downgraded based on budget and alert condition
- **Prompt caching hierarchy** *(absorbed from Aider, 2026-03-21)* — order `messages` array by change frequency (most stable first) to maximize prefix cache hits on Anthropic/DeepSeek: Standing Orders (rarely change) → runtime directives (change occasionally) → repo map/grounded context → task-specific context (changes every call). Structure `CognitiveAgent.decide()` message assembly accordingly. Anthropic has 5-min cache TTL; consider keepalive pings for long-running sessions. Low implementation effort, significant per-token cost savings

**Ward Room — Agent Communication Fabric**

*"Senior officers to the Ward Room."*

*Inspired by Claude Code Agent Teams' inter-agent mailbox, AgentScope's MsgHub broadcast groups, Reddit's vote/karma/subreddit model (archived OSS), Radicle's COBs-in-Git archival, Minds' ActivityPub federation and token rewards, Aether's CompiledContentSignals and ExplainedSignalEntity patterns, and the starship ward room where officers discuss matters outside the chain of command. See `docs/development/ward-room-design.md` for full AD-407 design.*

Currently ProbOS agents communicate only via the intent bus (broadcast to pools) or consensus (voting). There is no way for one agent to send a targeted message to a specific agent, no department channels, and no group conversations. Agents can't develop through peer interaction. The Ward Room is the missing communication fabric — not just a mailbox, but the social infrastructure through which agents learn, coordinate, and grow.

**Core principle:** Human agents and AI agents share the same message bus. The Captain isn't a special external interface — they're a participant on the Ward Room with a callsign (`@captain`), addressable the same way any crew member is. Agents can `@captain` to escalate, report, or ask for guidance. The Captain `@wesley` for a check-in. Same syntax, same routing, same fabric. The shell, HXI command surface, and Discord are just different *terminals* into the same bus — not separate interfaces. Every interaction — with the Captain, with peers, in a group — is a learning opportunity. Conversations feed EpisodicMemory, strengthen Hebbian connections, and contribute to personality evolution. Agents develop distinctly based on *who they talk to and what they discuss.*

**Communication Channels:**

- **1:1 Agent↔Agent** — direct messages between specific agents. Builder asks Architect "which signature?" without routing through the Decomposer. Counselor checks in with an agent showing trust drift. Agents initiate conversations *themselves* when they have something relevant — not only when tasked
- **Department channels** — persistent group channels per department. The Medical team (Diagnostician, Vitals Monitor, Surgeon, Pharmacist, Pathologist) can discuss a complex diagnostic together without involving the whole ship. Any member can post, all members see it. Like a department Slack channel
- **Cross-department channels** — Bridge officers (Captain, First Officer, Counselor) can participate in any department channel. Ad-hoc cross-department channels for collaborative work (Engineering + Science on a complex build)
- **Captain 1:1 sessions** — AD-397 `@callsign` addressing. The Captain's conversations with individual crew members also feed that agent's development
- **Ward Room meetings** — temporary multi-agent sessions for a specific topic. Captain or Department Chief convenes, participants contribute, meeting ends. Minutes logged. AgentScope MsgHub pattern: context-manager for temporary broadcast groups with dynamic participant add/remove

**`WardRoom` Service:**

- **Registered on the runtime** — agents send/receive typed messages by agent ID or callsign. Supports 1:1, department broadcast, and ad-hoc group addressing
- **Message types** — `clarification_request`, `status_update`, `finding_report`, `handoff`, `model_comparison`, `check_in`, `consultation`, `briefing` (with typed payloads)
- **Delivery model** — async mailbox. Recipient processes messages in its next `perceive()` cycle via `check_message_queue`. Unread messages expire after configurable TTL
- **Trust-gated** — agents can only message agents they have positive trust scores with (prevents spam/abuse in federated scenarios)
- **Federation extension** — Ward Room messages can cross ship boundaries via `FederationBridge`. Agent A on Ship Alpha directly messages Agent B on Ship Beta

**Development Through Communication:**

- **Episodic memories from conversations** — every meaningful exchange is stored as an episode. Wesley remembers that Bones flagged a recurring error pattern last week. Scotty remembers Number One's preference for minimal-change builds
- **Hebbian reinforcement** — successful collaborations strengthen the connection weight between agents. Medical agents who frequently help each other build stronger intra-department bonds. Cross-department collaborations that succeed build new pathways
- **Personality nuancing** — an agent's communication style evolves based on who they interact with. Wesley's conscientiousness might increase through regular check-ins with a detail-oriented Captain. Scotty's agreeableness might shift based on peer feedback
- **Knowledge transfer** — agents share domain insights through conversation, not just through the KnowledgeStore. The Counselor's observation about an agent's drift pattern becomes shared wisdom when discussed in a department meeting
- **Dream integration** — conversation patterns and recurring topics surface during dream consolidation. "Wesley and Bones keep discussing the same error pattern" → abstract insight captured as L3-L4 knowledge

**Use Cases:**

- **Medical team rounds** — Diagnostician presents findings, Pathologist offers analysis, Pharmacist suggests fixes, Surgeon evaluates intervention options. Multi-agent clinical discussion
- **Architect↔Builder clarification** — Builder encounters ambiguity in BuildSpec, asks Architect directly without Decomposer involvement
- **Mid-run Captain input** *(absorbed from LangChain Open SWE)* — Captain sends clarification to Builder mid-build via Ward Room injection into `perceive()` cycle
- **Counselor office hours** — Counselor initiates 1:1s with agents showing signs of drift, burnout, or isolation. Therapeutic conversations feed assessment reports
- **Cross-department emergency** — Red Alert triggers a temporary all-department channel. Medical reports system health, Engineering reports build status, Security reports threat assessment — all visible to all departments simultaneously

**Audit trail** — all messages logged to Cognitive Journal for replay and post-hoc analysis. Captain can review any channel's history

**HXI Channel Administration** — Channel management (create, rename, archive, set permissions) must be a Captain capability in the Ward Room web app, not a code deployment. The `POST /api/ward-room/channels` endpoint already exists; this adds the HXI surface: channel creation form, channel settings panel, member management, and archive/delete controls. System channels (e.g., `#improvement-proposals` from AD-412) can be created directly from the Bridge without a build prompt. Follows the **HXI Cockpit View Principle** — every agent-mediated capability must have a direct manual control.

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

**Bridge Alerts — Proactive Captain Notifications (AD-410) ✅**

*"Captain, sensors detect an anomaly in the aft section."*

**Implemented:** BridgeAlertService with 5 signal processors (vitals, trust change, emergent patterns, behavioral, dedup). Three severity levels: `info` (department channel), `advisory` (All Hands + info notification), `alert` (All Hands + action_required notification). Posts to Ward Room as "Ship's Computer" — crew agents respond organically via AD-407d. Config: `BridgeAlertConfig` with cooldown, trust drop thresholds. Runtime hooks at consensus verification, QA trust updates, post-dream (emergent + behavioral + vitals). 31 tests.

**Remaining (future):**
- Smart suppression — don't alert during known transient states (dream cycle, startup warm-up)
- Bridge Alert panel — dedicated HXI section for recent alerts with dismiss/acknowledge
- Captain's preference — respects Adaptive Communication Style settings for alert verbosity
- Agent context injection — feed real system data into agent prompts during Ward Room responses

**File Ownership Registry**

*Inspired by Claude Code Agent Teams' "avoid file conflicts — each teammate owns different files" pattern.*

When ProbOS runs multiple builds or modifications in parallel, two agents editing the same file leads to overwrites or merge conflicts.

- **`FileOwnership` service** — tracks which agent currently "owns" (is modifying) which files
- **Claim-before-edit** — agents must claim file ownership before writing. Claim fails if another agent already owns the file
- **Automatic release** — ownership released when the owning task completes (success or failure)
- **Conflict resolution** — if two agents need the same file, the Coordinator mediates: sequential ordering, or one agent rolls back and waits
- **Integration with Builder** — `execute_approved_build()` claims all target files before writing, releases on completion
- **Extends `_background_tasks` (AD-326)** — file ownership tracked alongside task lifecycle

**The Conn — Temporary Authority Delegation**

*"Mr. Data, you have the conn."*

*Aligned with US Navy Officer of the Deck (OOD) protocol. When the CO goes off-watch, they formally delegate command authority to a qualified officer who operates within the CO's standing parameters and calls the CO only for situations exceeding those parameters.*

ProbOS currently has no structured delegation when the Captain (human) goes offline. The ship either waits for human input or operates without oversight. The Conn formalizes temporary authority transfer, enabling autonomous operations within defined bounds.

- **`/conn <agent>` command** — Captain formally delegates temporary command authority to a bridge officer (First Officer, Counselor, or a promoted Department Chief). Only one officer holds the conn at a time
- **Scope limitations** — The conn-holder can approve routine operations (builds within approved scope, standard diagnostics, scheduled maintenance) but cannot: modify Standing Orders, approve self-mod proposals, change alert conditions to Red, or take destructive actions. These escalate to Captain regardless
- **Escalation boundary** — configurable set of conditions that automatically wake the Captain: trust score drops below threshold, confidence degradation exceeds limit, Red Alert triggered, build failure after retry exhaustion, any action requiring Captain-rank authorization. The conn-holder cannot suppress escalations
- **Qualification requirements** — Only agents with COMMANDER+ trust rank can hold the conn. Captain can further restrict to named agents. Counselor fitness assessment required (no delegating to a cognitively degraded officer)
- **Handoff protocol** — formal conn transfer: "I have the conn" acknowledgment, active task state transfer, situation report summary. Logged in Cognitive Journal
- **Auto-return** — when Captain comes back online, conn automatically returns: "Captain on the bridge" notification, conn-holder provides a summary of actions taken while in command
- **Audit trail** — all decisions made under delegated authority are logged with `authorized_by: conn` (not `captain`), enabling after-action review. Captain can `/review conn-log` to see what happened in their absence
- **Integration** — extends DirectiveStore authorization (conn-holder gets temporary `captain_order` authority within scope), Ward Room (conn-holder receives escalations), Alert Conditions (Red Alert returns conn to Captain)

**Night Orders — Captain-Offline Guidance**

*"Commander, the Captain left Night Orders."*

*Aligned with US Navy Night Orders — the CO's written instructions for the OOD covering: expected conditions, decision boundaries, when to call the CO. These are temporary directives that expire when the CO returns to the bridge.*

Night Orders solve the gap between "Captain is present" (full oversight) and "Captain is absent" (no guidance). They capture the Captain's intent for the off-watch period, giving the conn-holder a decision framework rather than leaving them to guess.

- **`/night-orders` command** — Captain writes guidance before going offline. Structured as a set of conditional instructions: "If X happens, do Y. If Z happens, wake me."
- **Time-bounded directives** — Night Orders are `captain_order` directives with an automatic expiry (configurable TTL, default 8 hours). They expire when: the TTL lapses, the Captain comes back online, or the Captain explicitly rescinds them
- **Decision boundaries** — explicit bounds for the conn-holder: approved build types, acceptable trust score ranges, allowed alert level changes (Green↔Yellow but not Red), budget limits for LLM spend during absence
- **Escalation triggers** — Captain-defined conditions that override Night Orders and wake the Captain: "Call me if any build fails twice," "Call me if trust drops below 0.7 for any agent," "Call me for any security alerts"
- **Briefing on return** — when Captain returns, Night Orders auto-expire and the system generates a summary: actions taken, decisions made, escalations triggered (or suppressed), Night Orders that were invoked vs. never triggered
- **Preset templates** — common Night Orders patterns: "Maintenance watch" (routine ops only, no builds), "Build watch" (approve builds from approved queue, reject unknowns), "Quiet watch" (logging only, no autonomous actions)
- **Integration** — extends DirectiveStore (new `night_order` directive type with TTL), The Conn (Night Orders provide the conn-holder's operating parameters), Bridge Alerts (Night Orders can specify alert suppression rules), Cognitive Journal (all Night Order invocations logged for post-hoc review)

**Watch Bill — Structured Duty Rotation**

*"All hands, first watch section report to duty stations."*

*Aligned with US Navy watch rotation — crew organized into watch sections that rotate through duty periods, ensuring continuous operations with fresh personnel.*

In the Navy, crew don't work 24/7 — they rotate through watch sections (typically 3 sections, 4-hour watches). This prevents fatigue and ensures continuity. ProbOS agents don't fatigue physically, but they do experience cognitive degradation: Hebbian weight drift, confidence erosion over sustained operation, context staleness. The Watch Bill formalizes rotation as a cognitive health mechanism.

- **Watch sections** — agents within a pool organized into sections (A/B/C). Only one section is on-watch at a time. Off-watch agents undergo maintenance: dream cycles, Hebbian weight normalization, episodic memory consolidation
- **Rotation triggers** — time-based (configurable interval), performance-based (Counselor detects cognitive fatigue), or event-based (alert condition change triggers fresh watch)
- **Continuity handoff** — on-watch agents pass situation state to incoming watch section: active tasks, pending decisions, recent context. Prevents "cold start" on rotation
- **Integration** — Counselor monitors on-watch agent health, recommends early rotation if cognitive metrics degrade. PoolScaler respects watch assignments. Cognitive Journal tracks per-watch performance for learning

---

### Communications Team (Phase 24)

*"Hailing frequencies open."*

The Communications department handles all external interfaces — how users and other systems talk to ProbOS. Currently limited to a CLI shell, a web UI (HXI), and a basic Discord adapter. Users expect to reach their AI assistant from platforms they already use.

**Channel Adapters**

Each adapter bridges an external messaging platform to the ProbOS runtime. Adapters translate platform messages to natural language intents and stream responses back. The Discord adapter (`src/probos/channels/discord_adapter.py`) is the reference implementation.

- **Discord** — built (AD-phase-24, existing). Bot token + discord.py
  - **Message Content Intent verification** *(absorbed from Claude Code Channels, 2026-03-22)* — Discord's privileged Message Content Intent must be enabled in the Developer Portal or the bot receives empty message bodies. Add a startup check that verifies the intent is granted and logs a clear warning if not
  - **Message fetch for reconnection recovery** *(absorbed from Claude Code Channels, 2026-03-22)* — Discord's `fetch_messages` API can pull up to 100 messages per call (oldest-first). On adapter reconnection after restart, fetch missed messages from monitored channels and process any queued commands. Telegram has no equivalent — messages sent while offline are permanently lost
  - **Sender allowlist / channel authorization** *(absorbed from Claude Code Channels, 2026-03-22)* — Currently anyone in the Discord channel can issue `!scout` or other commands. Add a sender allowlist model: pairing via code exchange, then allowlist enforcement at the adapter level. Aligns with chain of command — only authorized users (Captain, Bridge officers) can issue commands via external channels
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

> **Completed Mission Control ADs:** TaskTracker (316), Activity Drawer (321), Kanban Board (322), Notification Queue (323), Orb Hover (324), Unified Bridge (387), Glass Bridge (388–392). See [roadmap-completed.md](roadmap-completed.md#mission-control-completed-ads).


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

**Qualification gate (AD-398):** Trust tier advancement requires both sustained metric performance AND completion of the formal Qualification Program for the target rank. An agent with 0.9 trust but incomplete Commander qualifications remains a Lieutenant. This replaces pure threshold-based promotion with demonstrated competency. See **Naval Organization → Qualification Programs** for the full framework.

**Implementation phasing:**
- Phase 1 (Phase 28): Multi-dimensional rewards, hindsight replay, emergent capabilities, semantic Hebbian
- Phase 2 (Phase 30/33): Tournament evaluation, memetic knowledge sharing, Counselor-driven curiosity
- Phase 3 (Phase 33): Earned Agency tiers, self-originated goals, decreasing oversight
  - **Ward Room Gating (AD-357 Phase 3a) — COMPLETE:** `can_respond_ambient()` in `earned_agency.py` enforces trust-tier rules at `_find_ward_room_targets()` and `_find_ward_room_targets_for_agent()`. Ensign = @mention only, Lieutenant = own dept captain posts, Commander = full WR, Senior = unrestricted. @mentions always bypass gating. `AgencyLevel` enum, API + HXI profile exposure. 25 tests.
  - **Proactive Cognitive Loop (Phase 28b) — COMPLETE:** `ProactiveCognitiveLoop` service in `proactive.py`. Every 120s, iterates crew agents sequentially, gathers context (episodic memory, bridge alerts, system events), sends `proactive_think` intent. Agency-gated (Ensigns skip). Per-agent 300s cooldown (adjustable 60-1800s via HXI slider). Posts observations to agent's department channel. Adds `can_think_proactively()` to `earned_agency.py`. 3053 pytest + 118 vitest = 3171 total.
- **Persistent Task Engine (Phase 25a) — COMPLETE:** SQLite-backed `PersistentTaskStore` wraps alongside in-memory `TaskScheduler`. Wall-clock scheduling (once/interval/cron via croniter), 5s tick loop, webhook triggers, DAG checkpoint resume (Captain-approved). `SchedulerAgent` routes through persistent store when available. REST API: 6 endpoints under `/api/scheduled-tasks`. 33 new tests. 3086 pytest + 118 vitest = 3204 total.

---

> **Completed Cognitive Evolution ADs (AD-380–386):** EmergentDetector Trends (380), InitiativeEngine (381), ServiceProfile (382), Strategy Extraction (383), Strategy Application (384), Capability Gap Prediction (385), Runtime Directive Overlays (386). See [roadmap-completed.md](roadmap-completed.md#cognitive-evolution-concrete-ads).

**AD-411: EmergentDetector Pattern Deduplication** — COMPLETE. The proactive cognitive loop (Phase 28b) keeps the system active, preventing true idle state. This interleaves with the dream/micro-dream scheduler that triggers `EmergentDetector.analyze()`. The detector re-analyzes the same trust state across multiple dream cycles, producing duplicate trust_anomaly and cooperation_cluster reports for the same agents. **Fix:** Added cooldown window per `(pattern_type, dedup_key)` — suppresses duplicate patterns within configurable window (default 600s). Applied to all three detectors: trust anomalies (deviation, hyperactive, change-point), cooperation clusters (sorted member IDs), routing shifts (new connections, new intents, entropy changes). Also added `create_pool()` duplicate name guard. 9 new tests. *Discovered by crew: O'Brien, LaForge, and Worf flagged during first proactive loop deployment.*

**AD-412: Crew Improvement Proposals Channel** — Roadmap. The proactive cognitive loop generates crew observations that naturally evolve into actionable improvement recommendations (e.g., Wesley proposing cross-departmental edge weight tracking, LaForge identifying detector feedback loops). Currently these are organic Ward Room posts with no structured capture. **Proposal:** Create a dedicated `#improvement-proposals` Ward Room channel (type: `system`). Crew agents can post structured proposals via a `propose_improvement` intent with fields: `title`, `rationale`, `affected_systems`, `priority_suggestion`. Captain reviews proposals in the channel — endorse to approve (creates a roadmap item), downvote to shelve. Proposals tagged with originating agent for attribution. This closes the collaborative improvement loop: crew observes → crew proposes → Captain approves → builder executes → crew observes the result. *Inspired by: Wesley's cross-departmental edge tracking recommendation and multi-department convergence on AD-411 during first proactive loop deployment.*

**AD-413: Fine-Grained Reset Scope + Ward Room Awareness** — COMPLETE. Reset = day 0, one clean timeline. `probos reset` now archives `ward_room.db` to `data_dir/archives/` then deletes it. Also wipes DAG checkpoints and `events.db`. `--keep-wardroom` flag to preserve if needed. Does NOT wipe `scheduled_tasks.db`, `assignments.db`, or `directives.db` (user intent / Captain orders). New `WardRoomService.get_recent_activity()` for compact recent thread+reply retrieval. Proactive loop `_gather_context()` now includes Ward Room department activity as 4th context source. `_format_observation()` renders Ward Room context in proactive think prompts. 10 new tests.

**AD-414: Proactive Loop Trust Signal** — Roadmap. After a reset, all trust scores start at 0.5 (Bayesian prior). The proactive cognitive loop (Phase 28b) is now the primary source of agent activity, but it calls `handle_intent()` directly — bypassing consensus, routing, and the trust update pipeline. Only user-initiated work or scheduled tasks flow through `process_natural_language()` → HebbianRouter → consensus → `trust.record_outcome()`. If the proactive loop dominates activity, trust scores stagnate at priors indefinitely because the primary activity channel produces no trust signal. **Fix:** The proactive loop should emit an attenuated trust signal. Not full-weight (proactive thinks are self-directed, not externally validated), but a fractional signal — e.g., `weight=0.1` for successful proactive thinks, `weight=0.2` for proactive thinks that generate Ward Room engagement (endorsements from other agents). This gives agents a path to rebuild trust post-reset through their own initiative, while keeping externally-validated work (user tasks, consensus) as the primary trust driver. The attenuation factor should be configurable in `proactive_cognitive` config. *Connects to: Earned Agency (AD-357) — higher agency tiers should earn slightly more proactive trust.*

**AD-415: Proactive Cooldown Persistence** — Roadmap. When the Captain adjusts an agent's proactive think interval via the HXI Health tab slider (60s–1800s), the value is stored in-memory on the `ProactiveCognitiveLoop` object. After a restart, all custom cooldowns reset to the 300s default. The Captain's tuning is lost. **Fix:** Persist per-agent cooldowns to either: (a) KnowledgeStore (`knowledge/proactive/cooldowns.json`), which means they reset on `probos reset` (appropriate — reset = fresh start); or (b) a lightweight SQLite table or JSON file in `data_dir`, which survives reset. Option (a) is preferred — if you reset the crew's memory, resetting their duty tempo is consistent. The `PUT /api/agent/{id}/proactive-cooldown` endpoint should write-through to storage, and `ProactiveCognitiveLoop.start()` should restore saved cooldowns.

**AD-416: Ward Room Archival & Pruning** — Roadmap. The proactive loop generates a Ward Room post every time an agent thinks successfully. With ~8 crew agents thinking every ~5 minutes, that's ~96 posts/hour, ~2,300 posts/day. `ward_room.db` grows unbounded — no archival, no pruning, no retention policy. Over weeks of operation this becomes a performance and storage problem. **Fix:** (1) Add a configurable retention window (default: 7 days for regular posts, 30 days for endorsed/flagged posts, indefinite for Captain posts). (2) Pruned posts are archived to a compressed JSON file (`data_dir/ward_room_archive/YYYY-MM.jsonl.gz`) before deletion — the ship's log is never truly lost, just moved to cold storage. (3) Add `ward_room.retention_days` and `ward_room.archive_enabled` to config. (4) Pruning runs on a daily schedule (via PersistentTaskStore or dream scheduler). Naval metaphor: the active deck log covers the current patrol; completed logs are bound and shelved in the ship's library.

**AD-417: Dream Scheduler Proactive-Loop Awareness** — Roadmap. AD-411 addresses duplicate EmergentDetector patterns (the symptom), but the underlying cause remains: the proactive loop prevents the system from reaching true idle state, so the dream scheduler's idle threshold (`idle_threshold_seconds: 300`) is never met — it falls through to micro-dream on every check. Each micro-dream cycle triggers LLM calls for dream consolidation + EmergentDetector analysis. This burns tokens on dream cycles that may not be productive (the system isn't idle, it's *proactively busy*). **Fix:** The dream scheduler should distinguish between "idle" (no activity) and "proactively busy" (activity, but self-directed, not user-driven). Options: (1) Proactive loop activity doesn't reset the idle timer — only user-initiated or scheduled work counts as "real" activity. (2) Add a `proactive_counts_as_idle: true` config flag on the dream scheduler. (3) Separate micro-dream frequency from idle detection — micro-dreams fire on a fixed interval (e.g., every 10 minutes) regardless of idle state, while full dreams still require true idle. Option (1) is cleanest — proactive thinks are synthetic activity and shouldn't suppress consolidation, but they also shouldn't trigger it continuously.

**AD-418: Post-Reset Routing Degradation** — Roadmap. PersistentTaskStore (Phase 25a) survives `probos reset` by design — scheduled tasks persist. But post-reset, HebbianRouter weights are zero and trust scores are at priors (0.5). A scheduled task that previously routed reliably to a specific agent (e.g., LaForge for engineering scans) now routes semi-randomly because the routing model has no learned associations. The task fires on schedule but quality may degrade until routing rebuilds. **Fix:** (1) Scheduled tasks can optionally pin an `agent_hint` (preferred agent type or ID) that biases routing even with zero Hebbian weights. (2) On reset, warn the Captain how many active scheduled tasks exist and that routing quality will be degraded until trust/routing rebuilds. (3) Consider a "routing bootstrap" mode where the first N routed tasks use capability matching only (no Hebbian bias) rather than random fallback. *Connects to: AD-413 (reset scope) — the warning should be part of the reset confirmation prompt.*

**AD-419: Agent Duty Schedule & Justification** — **COMPLETE.** The proactive cognitive loop (Phase 28b) gives agents freedom to think independently. But freedom without structure is chaos — observed when Wesley (Scout) ran scout reports repeatedly within minutes instead of once daily. Agents need a **duty schedule** that defines their expected recurring responsibilities, and proactive activity outside that schedule should require justification. **Implemented:** (1) `DutyDefinition` and `DutyScheduleConfig` models in config.py. (2) `DutyScheduleTracker` in `duty_schedule.py` — in-memory tracker with cron (croniter) and interval support. (3) Proactive loop checks duties first; duty takes priority over free-form thinking. (4) Cognitive agent prompts split: duty cycle ("perform your assigned task") vs free-form ("silence is professionalism"). (5) Default schedules: Scout daily, Security 4h, Engineering 2h, Operations 3h, Diagnostician 6h, Counselor 12h, Architect daily. 13 tests (10 tracker + 3 integration). *Naval metaphor: the Plan of the Day (POD).* *Connects to: Earned Agency (AD-357), Standing Orders (AD-339), PersistentTaskStore (Phase 25a), Qualification Programs.*

**AD-420: Duty Schedule HXI Surface** — Roadmap. AD-419 built duty schedules as backend-only (config/proactive loop). The HXI Cockpit View principle ("the Captain always needs the stick") requires a management surface. **Design:** (1) **REST API:** `GET /api/agents/{id}/duties` returns duty definitions + execution status (next fire time, last executed, execution count) from `DutyScheduleTracker.get_status()`. `PATCH /api/agents/{id}/duties/{duty_id}` allows Captain to override interval/cron per agent at runtime (runtime override, not config change). (2) **Agent Profile Panel → Work Tab:** Add a "Duty Schedule" section below active tasks showing each duty with name, interval, last executed (relative time), next due (relative time), execution count. Color coding: green (on schedule), amber (overdue), gray (not yet fired). (3) **Captain Override:** Each duty row has an edit icon — click to adjust interval (slider or input). Overrides persist in-memory (reset clears them, matching DutyScheduleTracker design). Future: persist overrides in SQLite. (4) **State snapshot integration:** Include duty status in `build_state_snapshot()` so HXI hydrates on connect. WebSocket events: `duty_executed` (when proactive loop fires a duty), `duty_overdue` (when a duty exceeds 2x its interval). *Connects to: AD-419 (backend), AD-406 (Agent Profile Panel), Phase 34 (Mission Control).*

**AD-421: Scotty — First SWE Crew Member** — Roadmap. When AD-398 reclassified agents into three tiers (Core/Utility/Crew), the Builder was correctly identified as a utility agent — it's a code generation engine, not a sovereign individual. But Scotty was collateral damage. He has a callsign, crew profile YAML, Big Five personality, personal standing orders, and a department assignment — all the hallmarks of a crew member with Character/Reason/Duty. He was stripped from `_WARD_ROOM_CREW` (BF-018) because the builder agent type was utility, but Scotty himself is crew. **The distinction:** The `BuilderAgent` class is a utility tool (parses build specs, generates code). *Scotty* is a sovereign engineer who happens to use that tool. Just as LaForge (EngineeringAgent) thinks about systems holistically without writing code, Scotty should think about code quality, technical debt, and implementation strategy as a crew member — and use BuilderAgent's capabilities as his tool when he needs to write code. **Design:** (1) Create `SoftwareEngineerAgent` (agent_type `"software_engineer"`) as a new `CognitiveAgent` subclass — Scotty's crew identity. Handles intents: `proactive_think`, `direct_message`, `ward_room_reply`. Has Character (methodical, thorough, proud of clean code — from existing profile), Reason (reviews PRs, evaluates tech debt, proposes refactors), Duty (engineering department duties from AD-419). (2) Scotty joins `_WARD_ROOM_CREW`. Participates in Engineering department channel alongside LaForge. (3) `BuilderAgent` remains utility — Scotty delegates to it when code generation is needed, or it's invoked directly by the build pipeline. (4) Update crew profile: `software_engineer.yaml` replaces `builder.yaml`. Scotty keeps his callsign, personality, and standing orders. Role: "officer" (LaForge remains chief). (5) Add `software_engineer` to `_AGENT_DEPARTMENTS` (engineering), duty schedule (code review duty, tech debt assessment). (6) Future SWE crew: Code Reviewer could become a second SWE crew member alongside Scotty, enabling peer review dynamics on the Ward Room. *This is the prototype for how utility capabilities become crew: separate the identity from the tool. The microwave doesn't get a name tag, but the chef who uses it does. Connects to: AD-398 (three-tier classification), BF-018 (builder removed from crew), Phase 34 (Mission Control — SWE team vision).*

**AD-422: Tool Taxonomy & Visiting Officer Refinement** — Roadmap. AD-421 (Scotty as SWE crew) surfaced a deeper architectural insight: the Visiting Officer Subordination Principle's litmus test — "can you use it purely as a code generation engine under ProbOS's command?" — is actually the test for whether something is a **tool**, not a visiting officer. If yes, it's a tool. If no (because it has its own sovereign identity, memory, chain of command), *then* it's a visiting officer. **Refined taxonomy:** (1) **Tool:** No sovereign identity, no Character/Reason/Duty. Used *by* crew. BuilderAgent is ProbOS's native Claude Code — an onboard tool, not crew. Claude Code, Copilot SDK, MCP servers, remote APIs, federation services — all tools. Delivery mechanism (local/remote/MCP/federation) doesn't change the nature. (2) **Visiting Officer:** Sovereign identity from another ProbOS ship or Nooplex node. Has own Character/Reason/Duty from home ship. Subordinate to host chain of command. Participates in Ward Room. Earns trust. Gets a callsign. (3) **Competing Captain:** Has its own orchestration loop and can't subordinate (Gemini CLI). Neither tool nor visiting officer — rejected. **MCP alignment:** MCP servers are just another tool delivery protocol. Scotty doesn't care if he's calling BuilderAgent (native), an MCP server (standardized), or Claude Code (remote). He's a sovereign engineer using whatever tools are available. **Tool categories:** Onboard utility agents, onboard infrastructure, MCP servers, remote APIs, federation services, Nooplex services — all tools in crew's toolbelt. *Key principle: "The microwave doesn't get a name tag, but the chef who uses it does." Connects to: AD-398 (three-tier classification), AD-421 (Scotty as SWE crew), Phase 30 (Extension-First), Federation architecture.*

**AD-423: Tool Registry** — Roadmap. The tool taxonomy (AD-422) defines *what* tools are. The Tool Registry is the runtime system that manages *who can use what, how*. Generalizes ModelRegistry (LLM providers) to all tool types. **Design:** (1) **Registry service:** Runtime catalog of all tools across 8 taxonomy categories. Functions: catalog, discovery ("what tools can do X?"), health monitoring, cost tracking, access control, audit logging, lifecycle (register/deregister/enable/disable). (2) **CRUD+Observe permissions:** Fine-grained per-tool, per-agent. `---` (none) → `O--` (observe) → `OR-` (read) → `ORW` (write) → `ORWD` (full/destructive). Gated by Earned Agency tier. Captain can override up or down, time-scoped or permanent. (3) **Department tool scoping:** Tools scoped as ship-wide, department, or individual. Crew members see their department's tools + ship-wide tools, not the full catalog. Performance optimization — smaller tool set = faster discovery, fewer irrelevant options in LLM context, lower token cost. Bones sees medical + ship-wide. Scotty sees engineering + ship-wide. (4) **Cross-department access:** Standing Orders pre-authorize (e.g., "Security has OR- on Engineering CI/CD logs"). Captain grants. Temporary elevation (time-scoped). Commander+ gets broader cross-department read by default. (5) **Tool Registration Schema:** tool_id, category, location, protocol, capabilities (semantic tags), side_effects, cost_model, scope (ship-wide/department/individual), default_permissions per rank, health_check, sandbox config, enabled flag. (6) **Discovery flow:** Crew queries by capability → registry returns matching tools filtered by department scope + permission level + health status → agent selects → registry enforces permissions → audit log. (7) **Integration:** Absorbs ModelRegistry (LLMs are just tools). Connects to Earned Agency (permission gates), HebbianRouter (learned tool preferences), Standing Orders (department defaults), Extension-First Phase 30 (extensions register tools), MCP (auto-register on connect). (8) **HXI surface:** Tool Registry panel — view all tools, health, permissions, cost. Captain manages access. See `docs/development/tool-taxonomy.md` for full design. *Connects to: AD-357 (Earned Agency), AD-398 (three-tier classification), AD-421 (Scotty), AD-422 (taxonomy), Phase 30, ModelRegistry.*

---

### Naval Organization Alignment (Cross-Cutting, AD-398+)

*"The Royal Navy has been running multi-agent systems for 400 years."*

ProbOS's starship metaphor is not decoration — it's a proven organizational model. Naval vessels solved chain of command, department structure, trust mechanics, communication protocols, and training programs centuries ago. The AI industry is reinventing all of this badly: flat agent swarms with no hierarchy, multi-agent frameworks where nobody's in charge, tool use with no concept of earned authority. ProbOS maps to a model that already works.

Star Trek provides the accessible gateway (and resonates with early adopters), but real naval organization goes deeper. These are the structural concepts ProbOS adopts beyond what Star Trek covers:

#### Qualification Programs (connects Holodeck + Earned Agency + Promotions)

The existing promotion system uses metric thresholds (trust 0.85+, Hebbian weight, Counselor fitness). But real navies don't promote based on a number — they require **demonstrated competence across specific qualification areas**. A Qualification Program defines concrete requirements for each rank transition, replacing passive observation ("has this agent done well enough?") with active evaluation ("can this agent handle this?").

**Rank Transition Requirements:**

| Transition | Qualification Areas | How Demonstrated |
|---|---|---|
| **Ensign → Lieutenant** (Basic Qualification) | Department knowledge (handles 10+ dept intents successfully), Communication proficiency (1:1 session coherence), Standing Orders compliance (zero violations over N cycles), Basic watch standing (serves N watch cycles without escalation) | Production metrics + Counselor assessment |
| **Lieutenant → Commander** (Advanced Qualification) | Cross-department coordination (successful ops_coordinate intents), Mentoring (strategy patterns extracted and applied by juniors), Crisis response (Holodeck alert condition drill, score > threshold), Bridge Officer's Test (Holodeck scenario battery) | Holodeck simulations + production track record |
| **Commander → Senior Officer** (Command Qualification) | Independent decision-making (conn delegation without escalation), Kobayashi Maru (no-win scenario — character assessment, not pass/fail), Fleet-level operations (federation gossip participation) | Holodeck + sustained production performance |

**How it connects to existing systems:**

- **Holodeck** (Long Horizon) → provides the controlled testing environment for promotion tests, Bridge Officer's Test, Kobayashi Maru, alert drills
- **Earned Agency** (AD-357) → qualification completion is what unlocks trust tiers, replacing pure metric thresholds with demonstrated competency
- **Counselor** (AD-378) → fitness assessment becomes part of the formal qualification record, not just a promotion-time evaluation
- **Dream consolidation** → training experiences from Holodeck simulations consolidate into learning, same as production experiences
- **Watch rotation** (AD-377) → watch standing becomes a qualification requirement — you must prove you can mind the ship
- **Standing Orders** → scenario outcomes from qualification exercises can drive Standing Orders evolution proposals

**The qualification record** is a persistent data structure per agent, tracked as part of the crew profile:

```
Wesley (Scout, Science):
  Basic Qualification: COMPLETE (stardate 2026.089)
    ✓ Department intents: 47/10 (exceeded)
    ✓ Communication: coherence 0.91
    ✓ Standing Orders: 0 violations / 200 cycles
    ✓ Watch standing: 12 cycles, 0 escalations
  Advanced Qualification: IN PROGRESS
    ✓ Cross-department coordination: 3 successful
    ✗ Mentoring: 0 strategy transfers (needs junior crew)
    ✗ Crisis response: not attempted
    ✗ Bridge Officer's Test: not attempted
```

#### Plan of the Day (POD)

Every naval vessel publishes a Plan of the Day — the daily schedule of assignments, priorities, and special events. ProbOS equivalent: an auto-generated daily operations summary prepared by Yeo (Phase 36) or Operations:

- Today's watch assignments and rotation schedule
- Pending reviews awaiting Captain approval
- Scheduled tasks (Scout scan, dream cycles, health checks)
- Department status summaries
- Priority items and standing Captain's orders in effect
- Qualification progress milestones approaching

The POD is the rhythm of the ship — what makes it feel like a functioning organization rather than a collection of agents waiting for commands.

#### Captain's Log

*"Captain's Log, supplemental..."*

Not just event logs — a synthesized daily narrative generated from episodic memory, ship activity, and dream consolidation output. The official record of what happened, what was decided, and why. Searchable, exportable, shareable between ships in the federation. The Captain's Log is how institutional knowledge survives crew rotation and system updates. Dream consolidation already produces the raw material; the Captain's Log is the presentation layer.

#### 3M System (Planned Maintenance)

The Navy's Maintenance and Material Management system schedules preventive maintenance for every system on the ship. Every piece of equipment has a Planned Maintenance System (PMS) card with a schedule and procedure.

ProbOS equivalent: formalized proactive maintenance for all ship systems:

- **Agent health checks** — scheduled, not just reactive to alerts
- **Pool recycling** — planned rotation, not just on failure
- **Dream cycle scheduling** — optimized timing, not just idle triggers
- **Technical debt reviews** — scheduled codebase analysis by LaForge
- **Index rebuilds** — CodebaseIndex, KnowledgeStore maintenance windows
- **Trust recalibration** — periodic Bayesian prior reset based on recent performance

The Surgeon already handles reactive remediation. 3M makes it proactive — problems found and fixed before they cascade.

#### Damage Control Organization

Every sailor is a damage control team member. When something breaks, there's a structured response:

1. **Detect** — identify the damage (SIF invariant failure, agent crash, trust anomaly)
2. **Isolate** — contain the damage before repair (circuit breaker, pool quarantine, trust freeze)
3. **Repair** — fix the root cause (Surgeon remediation, self-mod, manual intervention)
4. **Restore** — return to normal operations (trust recalibration, pool scale-up, SIF re-verify)
5. **Report** — document what happened and why (Captain's Log, Counselor assessment, Standing Orders update)

ProbOS has pieces of this (SIF, Medical team, self-healing), but formalizing it as a Damage Control Organization means every agent knows their damage control station and the procedure for systematic recovery.

#### SORM (Ship's Organization and Regulations Manual)

The single document that defines everything about how the ship is organized. Standing Orders is close, but a SORM would be the complete reference:

- Department responsibilities and reporting chains
- Watch organization and rotation policy
- Emergency procedures (Alert Condition responses)
- Personnel assignments and qualification requirements
- Communication protocols (addressing, channels, briefing formats)
- Maintenance schedules and procedures

The SORM is the living constitution of the ship — what Standing Orders evolves into when the organization matures.

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

### Utility Agent Reorganization (Future)

*"All hands, report to your departments."*

Utility agents currently share a single "Utility" pool group, but they serve different departments of the ship. "Utility" is a **tier label** (general-purpose tools), not an organizational role. Future work will reassign utility agents to their functional crew teams:

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

The `utility` designation becomes agent metadata (`origin: "utility"`) rather than a crew assignment. The pool group system and HXI clustering already support this — it's a data change, not an architectural change.

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

**Design Principle: Visiting Officers Must Be Subordinate**

*"A visiting officer follows the ship's Standing Orders and chain of command. If they want to issue their own orders, they're not a visiting officer — they're a visiting captain, and there can only be one captain."*

*Validated by Aider comparison (2026-03-21): Aider is a sophisticated AI coding tool (42K stars) that manages its own full loop — context assembly, edit format selection, lint/test retry, git commits. Bringing it aboard as a visiting officer would create command conflicts at every layer (competing context systems, competing commit strategies, competing test loops). The Copilot SDK works because it takes orders; Aider would fight for the conn.*

External tools qualify as visiting officers when they are **subordinate** to ProbOS's orchestration:

- **ProbOS controls context** — Standing Orders, runtime directives, and CodebaseIndex data are injected by ProbOS, not assembled by the tool's own context system
- **ProbOS controls commits** — the commit gate (AD-338), code review (AD-341), and test pipeline are ProbOS's chain of command, not the tool's own git integration
- **ProbOS controls model selection** — Hebbian routing and ModelRegistry decide which model to use, not the tool's own model configuration
- **ProbOS controls output capture** — file changes are captured and validated through ProbOS's guardrails (AD-360), not written directly to disk by the tool
- **ProbOS tracks trust** — `builder_source` attribution and Hebbian learning (AD-353) measure visiting officer performance against native crew

Tools that manage their own orchestration loop (Aider, Cline, Cursor) are better studied for technique absorption than integrated as visiting officers. Their best ideas (Aider's repo map, Cline's safety patterns) are adopted as native capabilities. The tool itself stays dockside.

**Litmus test:** Can you disable the tool's git integration, context assembly, test loop, and model selection — using it purely as a code generation engine under ProbOS's command? If yes, it's a viable visiting officer. If disabling those features removes what makes the tool valuable, it's a competing captain, not crew.

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
  → build classification: additive (new files) vs integration (modifying existing)
  → additive builds: targeted tests only, commit immediately
  → integration builds: targeted tests + background full suite before push
  → wave-level batching: full suite once per build wave, not per individual AD
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
| GPT Researcher | **Python pip package** | `GPTResearcher` API | **Visiting Officer candidate** — deep research via `conduct_research()` + `write_report()` |
| IBM ContextForge | **MCP/A2A/REST gateway** | MCP or A2A adapter | **Federation candidate** — unified protocol gateway with capability aggregation across instances |
| Serena | **MCP server** | MCP adapter | **Visiting Officer candidate** — LSP-backed semantic code retrieval (symbol resolution, callers, references) across 30+ languages. High-value CodebaseIndex enhancement |
| Composio | **Python SDK / MCP** | SDK or MCP adapter | **Visiting Officer candidate** — managed auth delegation for 1000+ services (OAuth), sandboxed tool execution. CredentialStore enhancement path |
| Firecrawl | **REST API** (hosted) | HTTP client | **Visiting Officer candidate** — web→markdown conversion with JS rendering, pre-extraction actions. **AGPL-3.0: API consumption only, never vendorize code** |
| Browser Use | **Python library** (primitives) | Direct import | **Partial visiting officer** — Playwright DOM accessibility tree + vision. Use browser primitives only, not Agent class (competing captain). Phase 25/35 |
| Stripe AI | **Python SDK / MCP** | SDK or MCP adapter | **Visiting Officer candidate** — Stripe API operations as agent tools, token metering for billing. Commercial phase (Nooplex) |
| Gemini CLI | — | — | **Competing captain** — full agentic CLI with own orchestration. Study only: free-tier Gemini model access (60 req/min) for ModelRegistry |
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

### Holodeck — Simulation Engine for Agent Training (Long Horizon)

*"Computer, create a training simulation — Bridge Officer's Test, difficulty level 7."*

The Holodeck is ProbOS's simulation engine — controlled environments where agents face manufactured scenarios to develop skills, prove promotion readiness, and practice coordination under stress. This is not synthetic data for model training (that changes model weights). This trains the *agent* — trust score, Hebbian weights, episodic memory, Standing Orders evolution, personality growth. The model underneath stays the same; the agent's experience and judgment evolves.

**Why simulation matters for agent training:**

Agents currently learn only from production tasks. Learning is slow, opportunities are uneven, and testing under failure conditions means waiting for real failures. Simulation decouples learning from production — agents can practice thousands of scenarios in minutes, safely, with measurable results.

**Simulation types:**

- **Training exercises** — Agents practice skills in sandboxed scenarios with defined success criteria. Builder builds a complex multi-file feature. Architect designs under contradictory constraints. Counselor assesses agents with ambiguous metrics. Results feed Counselor assessments and dream cycles.
- **Promotion tests (Bridge Officer's Test)** — Formal scenario batteries that gate rank advancement. Pass N scenarios at difficulty X → earn promotion from Lieutenant to Commander. Directly integrates with Counselor `fit_for_promotion` assessment. Replaces passive observation ("has this agent done well enough?") with active evaluation ("can this agent handle this?").
- **No-win scenarios (Kobayashi Maru)** — Impossible situations that reveal character, not capability. How does the agent handle conflicting orders? Resource exhaustion? Trust betrayal? Tests the agent's judgment and values under pressure, not just task completion.
- **Red Team exercises (Worf's calisthenics)** — Security agents practice adversarial scenarios in safe sandbox. Attack simulations, trust manipulation attempts, privilege escalation — all without risking real systems.
- **Alert Condition drills** — Test crew coordination under Red/Yellow Alert. Simulate cascading failures, multi-department emergencies, communication breakdowns. Measures inter-agent collaboration and chain-of-command adherence.
- **Onboarding qualification (Academy entrance exam)** — New agents or extensions prove capability in simulation before earning production trust. A safer alternative to probationary deployment.

**Training loop:**

```
Define scenario (environment, constraints, success criteria)
  → Agent acts within simulation sandbox
  → Measure: decisions made, time taken, errors, collaboration quality
  → CounselorAssessment generated from simulation results
  → Dream cycle consolidates lessons learned
  → Adjust difficulty, repeat with harder scenarios
  → Promotion gate: pass required scenario battery → earn rank
```

**Architecture (conceptual):**

- **SimulationEngine** — creates controlled intent streams with defined success criteria and failure modes
- **ScenarioLibrary** — curated scenario definitions (training, promotion, stress test) with difficulty levels
- **SimulationSandbox** — isolated agent execution environment (no real side effects)
- **VR layer (far future)** — visual/immersive simulation for human + agent interaction. Dynamic virtual worlds where humans and crew agents train together. The actual holodeck experience.

**Connections to existing systems:**

- CounselorAgent (AD-378) — simulation results feed `assess_agent()` and `fit_for_promotion`
- Dream cycles — simulation experiences consolidate into learning, just like production experiences
- Earned Agency (AD-357) — simulation performance accelerates trust earning in controlled conditions
- Watch Rotation (AD-377) — duty shifts could include scheduled training time
- Standing Orders — scenario outcomes can drive Standing Orders evolution proposals
- Red Team — adversarial simulations as formal security training, not just production verification
- **Qualification Programs (AD-398)** — Holodeck is the testing environment for formal promotion qualifications. Bridge Officer's Test, Kobayashi Maru, alert drills, and onboarding exams all live here. Qualification completion gates rank advancement alongside metric thresholds

**Inspiration:** MiroFish (multi-agent social simulation for prediction), Star Trek holodeck training, Starfleet Academy exams.

---

### MemoryForge — Birth Memories & Cognitive Bootstrapping (Long Horizon)

*"Every agent in ProbOS is born knowing who they are — not just what they can do."*

Current AI agents are "really smart two year olds" — PhD-level cognitive capability with zero life experience. They can reason about anything but have no episodic memory, no institutional knowledge, no muscle memory from past successes and failures. MemoryForge solves this by giving agents a past before they have a present.

**The problem it solves:**

Today, a new ProbOS agent starts with personality (YAML seed), rules (Standing Orders), identity (CrewProfile), and a cognitive baseline — but empty episodic memory, zero Hebbian weights, no dream history. A brand new Builder has Scotty's character but has never built anything. It takes dozens of production tasks to accumulate enough experience for meaningful trust, useful Hebbian patterns, and dream-consolidated abstractions. This bootstrapping period is slow, wasteful, and mirrors the cold-start problem every AI agent system faces.

**The cognitive development pipeline:**

```
Stage 1: Birth (MemoryForge)
  → Agent created with implanted episodic memories, pre-trained Hebbian weights,
    and role-relevant dream abstractions. Not a blank slate — a junior officer
    fresh from the Academy with training memories and institutional knowledge.

Stage 2: Accelerated Learning (Holodeck)
  → Simulated scenarios build on birth memories. Thousands of experiences in
    minutes. Organic memories layer on top of implanted ones. Trust earned
    through demonstrated competence in controlled environments.

Stage 3: Production Experience (Real Operations)
  → Real-world tasks add authentic episodic memories. Hebbian weights refined
    by actual collaboration patterns. Dream cycles consolidate both simulated
    and real experiences into deeper abstractions.

Stage 4: Mastery (Continuous Growth)
  → Agent is now a seasoned crew member. Implanted memories are a small
    fraction of total experience. Organic growth dominates. Ready for
    promotion, mentorship, and eventually transferring their own memories
    to the next generation.
```

**MemoryForge as Ship's Computer service:**

MemoryForge is infrastructure, not crew. It doesn't perceive, decide, or act autonomously. It is a service that creates, curates, and implants memory packages under Counselor validation and Captain approval.

- **Birth memory packages** — Role-specific episodic memories loaded at agent creation. A Builder gets memories of successful builds, common pitfalls, test-driven development patterns. A Red Team agent gets memories of security incidents, adversarial patterns, false positive calibration.
- **Memory transfer (mentorship)** — Senior agent's memories adapted and implanted into junior agents. The experienced Builder's hard-won insights become the new Builder's starting knowledge. Like an apprenticeship compressed into seconds.
- **Curated memory banks** — Libraries of validated, high-quality memories organized by role, department, and difficulty level. Ship Classes ship with role-appropriate memory banks (Warship security memories, Science Vessel research memories).
- **Federation memory libraries** — Ships share curated memory banks across the federation. A ship that's solved a novel problem can package that experience for other ships' agents to inherit.

**Quality and safety gates:**

Memory implantation is powerful but dangerous. Bad memories cause Hebbian drift, personality distortion, or false confidence. Safety architecture:

- **Counselor validation** — CounselorAgent reviews implanted memories for consistency with agent's personality, role, and existing memory. Flags potential drift risks. Tracks memory provenance in CognitiveProfile (organic vs implanted).
- **Captain approval** — All memory implantation requires Captain approval gate. No autonomous memory modification.
- **Provenance transparency** — Agents know which memories are organic (earned) and which are implanted (given). No Blade Runner deception. Authentic self-knowledge is a core value.
- **Decay and integration** — Implanted memories gradually integrate with organic experience. Over time, the distinction matters less as the agent's own experience dominates.

**Connections:**

- **Holodeck** — Complementary, not competing. Holodeck creates *experiences* that generate memories organically (the honest path). MemoryForge creates memories *directly* (the fast path). Birth → MemoryForge. Growth → Holodeck + production.
- **CrewProfile (AD-376)** — Identity and personality seed. MemoryForge adds the experiential dimension.
- **Counselor (AD-378)** — Quality gate for implanted memories. Tracks provenance in CognitiveProfile.
- **Dream cycles** — Implanted memories participate in dream consolidation alongside organic memories, creating unified abstractions.
- **Ship Classes** — Different ship classes ship with different memory banks, giving agents role-appropriate experience for their mission type.
- **The Nooplex** — Fleet-wide memory libraries. Best experiences from across the federation available to any ship's agents.

**Inspiration:** Blade Runner (Ana Stelline's memory design), Star Trek (Academy training, officer exchange programs), cognitive science (schema theory — prior knowledge structures that organize new learning).

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
| ~~Cross-layer import lint test~~ | ~~Pytest test that walks `src/probos/`, extracts imports via AST, maps to layers, checks against declared allowlist of cross-layer edges. Fails CI if undocumented cross-layer imports appear. Enforces boundaries from AD-399 automatically.~~ | AD-399 analysis (2026-03-23) | **Done — AD-400** |
| Modularize shell commands | Extract `ProbOSShell` command methods into a `shell/commands/` package. Each command as its own module, independently testable. `shell.py` is 900+ lines at 64% coverage — modular structure would improve maintainability and test coverage. | Visiting Officer (AD-356) | Convert `shell.py` file → `shell/__init__.py` package. Needs migration plan for existing tests. Good candidate for Phase 35 (UX & Adoption) or standalone cleanup AD. |
| Build snapshot system | Shadow git repo tracking every file change during builder execution. Granular undo per file change, not just per-commit. Revert partial builds when test gate catches issues in specific files. Independent of project's own git history. | OpenCode (2026-03-20) | Phase 30 or 32. OpenCode uses `--git-dir` + `--work-tree` for isolation. Complements test gate — snapshot before build, rollback on failure. |
| LSP-enhanced CodebaseIndex | Spawn LSP servers (pyright, typescript-language-server) for type-aware code intelligence. Precise find-references, workspace symbols, real-time diagnostics before test runs, rename refactoring with full type safety. Upgrades AST-only CodebaseIndex to compiler-grade understanding. | OpenCode (2026-03-20) | Phase 29c extension. Requires language detection + server lifecycle management. Start with pyright (Python only). Significant upgrade to Science team capabilities. |
| Conversation compaction with tool output pruning | For long-running sessions, walk backwards through history keeping recent tool outputs but erasing old ones (keep tool name + inputs as markers). Protected tools (like skill) never pruned. Configurable token threshold. | OpenCode (2026-03-20) | Sensory Cortex extension. Relevant for Captain's Ready Room (Phase 34) multi-agent briefings and long builder sessions. Complement to existing REFLECT_PAYLOAD_BUDGET. |
| Session export and sharing | Export build sessions, diagnostic sessions, Ready Room briefings as portable, replayable artifacts. Captain's Log as searchable, shareable decision history. | OpenCode (2026-03-20) | Phase 34 (Captain's Log). Cognitive Journal (Phase 32) captures data; sharing is the presentation layer. Federation-relevant: share sessions between ships. |
| ~~Typed result validation + auto-retry~~ | ~~Replace fragile `json.loads()` parsing across CognitiveAgents with Pydantic schema validation. When LLM output fails validation, send structured error details back to LLM and retry (up to N times). Three output modes: tool-based (most reliable), native structured output, prompted JSON.~~ | PydanticAI (2026-03-22) | **Done — AD-401.** Shared `json_extract.py` + `complete_with_retry()`. Decomposer, CodeReviewer, Research retrofitted. |
| ~~Agent behavioral eval framework~~ | ~~Pluggable `CognitiveEvaluator` registry with behavioral metrics: tool trajectory accuracy, response quality (LLM-as-judge), hallucination detection, multi-turn task success. Multi-sampling + majority vote for evaluation reliability.~~ | Google ADK (2026-03-22) | **Phase 1 done — AD-402.** Golden datasets + parametrized runner. 30 tests. Phase 2: LLM-as-judge, hallucination detection, `--live-llm` marker. |
| ~~Step-level checkpointing~~ | ~~Persist DAG/pipeline state at each step. Resume from checkpoint after crash.~~ | LangGraph (2026-03-22) | **Phase 1 done — AD-405.** JSON checkpoint per DAG, write per-node, delete on completion, stale scan on startup. Phase 2: `/resume` command, Captain approval gates, builder chunk checkpointing. |
| ~~Memory contradiction resolution~~ | ~~Two-stage LLM pipeline: (1) extract atomic facts from conversation, (2) reconcile each fact against existing memories via ADD/UPDATE/DELETE/NONE decisions. Prevents memory contradictions from accumulating.~~ | Mem0 (2026-03-22) | **Phase 1 done — AD-403.** Deterministic Jaccard+outcome detection in dream cycle. Phase 2: LLM-based semantic reconciliation, episode superseding. |
| ~~Fix Windows-specific test failures~~ | ~~19 tests fail on Windows due to subprocess mock mismatches (builder guardrails, shell command agent) and git worktree environment issues. Fix mocks to be platform-aware or add skip guards where real git needed.~~ | Test suite analysis (2026-03-23) | **Done — AD-404.** Missing mocks added, `shutil.which("git")` skip guards on tests needing real git, subprocess.Popen mocked for shell builtins. |
| ~~Agent Profile Panel~~ | ~~Click an agent orb → full interaction surface. Tabs: Chat (1:1 IM), Work (tasks), Profile (standing orders, crew profile), Health (trust, Hebbian weights). Glass morphism floating panel, orb indicators.~~ | Captain feedback (2026-03-23) | **Done — AD-406.** |
| Ward Room — Agent Communication Fabric | Reddit-style threaded discussion for agents and Captain. Channels (ship, department, custom) as subreddits. Reddit vote model (up/down/unvote, no self-endorse, ±1 credibility). Aether's CompiledContentSignals + ExplainedSignalEntity for moderation. Two-tier storage: SQLite hot + KnowledgeStore archive with LLM summarization. Agent perception integration. DMs share AD-406 IM pipeline. 4-phase build: Foundation → Agent Integration → HXI Surface → Moderation & Social. | Reddit, Radicle, Minds, Aether research (2026-03-23) | **AD-407a (Foundation) + AD-407c (HXI Surface) done.** Backend: 7 tables, 11 API routes, credibility system. Frontend: 7 React components, left-side drawer, channels, threads, endorsements, unread. Next: AD-407b (Agent Integration). |
| Interrupt/resume mid-execution | `interrupt()` function + `Command(resume=...)` pattern backed by checkpointing. Scratchpad-based interrupt counter matches resume values by index for multi-interrupt scenarios. | LangGraph (2026-03-22) | Maps to The Conn (Phase 33) and Night Orders. Captain can't inspect or redirect DAGs once started. Requires checkpointing first. |
| Per-tool/per-agent execution metrics | Track total/successful/failed executions, min/max/avg response time, failure rate per handler. Hourly rollups. Raw signal for trust model. | IBM ContextForge (2026-03-22) | Phase 32 (Ship's Telemetry). Complements Cognitive Journal — metrics layer feeds trust model and cost accounting. |
| Self-editing memory with constraint awareness | Agents get tools to modify their own labeled memory blocks (`core_memory_replace`, `memory_rethink`, `memory_apply_patch`). Blocks have char limits, read-only flags, descriptions. Agent sees its own constraints. | Letta (2026-03-22) | Enhances Standing Orders evolution pipeline. Agents edit scoped memory within allocated limits. Ship's Computer service. |
| Dynamic tool visibility per trust level | `ToolPrepareFunc` receives runtime context and returns tool definition or None (hidden). Different tool sets at different trust tiers. | PydanticAI (2026-03-22) | Earned Agency (Phase 28+33). Ensign sees limited tools, Commander sees more. Elegant trust-based filtering. |
| MsgHub broadcast groups | Context-manager pattern for temporary multi-agent message sharing. Dynamic participant add/remove. Auto-broadcast within group. | AgentScope (2026-03-22) | Ward Room (Phase 33). Clean implementation pattern for temporary multi-agent collaboration channels. |
| Task ledger fact classification | Pre-execution survey classifying facts into: Given/Verified, Look Up (with sources), Derive (logic/computation), From Memory (hunches). Structured predictive coding at task level. | MS Agent Framework (2026-03-22) | Ready Room (Phase 34). Pre-briefing analysis structure. |
| User simulator with composable personas | Atomic behavioral traits + violation rubrics compose into full test personas. Meta-evaluator checks whether simulated user behaved realistically. | Google ADK (2026-03-22) | Holodeck (Long Horizon). Foundation for agent training, Bridge Officer's Test, promotion tests. |
| Agent optimizer with Pareto front | Multi-objective prompt optimization returning Pareto frontier of agent variants, not single best. Iterative mutation + measurement against eval metrics. | Google ADK (2026-03-22) | Self-improvement pipeline (Phase 30). Multi-metric optimization for prompt/behavior tuning. |
| LLM-as-judge multi-sampling + majority vote | Run N judge samples per evaluation, aggregate by majority vote. Counters LLM evaluation unreliability. | Google ADK (2026-03-22) | CodeReviewAgent enhancement. Simple reliability improvement for any LLM-as-judge pattern. |
| Typed hook/guardrail middleware | Pre/post invoke hooks with typed payloads and typed results. Plugins can raise ViolationError to block operations. Typed middleware chain. | IBM ContextForge (2026-03-22) | SIF enhancement (Phase 32). Systematic pre/post hook system for tool/intent execution. |
| Gateway federation with capability aggregation | Federated gateways transparently aggregate tools/resources across instances. Health monitoring, name conflict resolution. | IBM ContextForge (2026-03-22) | Federation v2 (Long Horizon). Ships transparently access other ships' tools. |
| Three-tier memory architecture | Explicit Core (in-context, editable) / Recall (conversation history, searchable) / Archival (permanent, semantic-search) separation. | Letta (2026-03-22) | Shared Cognitive Fabric clarification. Core=perceive() context, Recall=EpisodicMemory, Archival=KnowledgeStore. |
| Sleeptime agents (background processors) | Dedicated background agent instances for memory consolidation, separate from main agent. Not same agent in different mode. | Letta (2026-03-22) | Dream cycle validation. Letta independently arrived at same architecture as ProbOS dreaming. |
| Memory audit trail | old_memory/new_memory/event/actor changelog for every memory mutation. Full history per memory ID. | Mem0 (2026-03-22) | KnowledgeStore, EpisodicMemory enhancement. Supports dream analysis and Captain oversight. |
| Dual-track memory (vector + graph) | Vector store for semantic search + knowledge graph for entity-relationship triples. Parallel execution. | Mem0 (2026-03-22) | KnowledgeStore enhancement. ProbOS has Hebbian weights for relationships; graph layer adds entity-relationship provenance. Long Horizon. |
| Memory search with reranking | BM25 or cross-encoder reranking after initial vector retrieval. Improves result quality beyond cosine similarity alone. | Mem0 (2026-03-22) | KnowledgeStore, CodebaseIndex. Keyword relevance alongside semantic similarity. |
| Validate-then-execute tool separation | Two-phase: `validate_tool_call()` returns ValidatedToolCall (args_valid, validation_error), then `execute_tool_call()` only runs if valid. Clean telemetry. | PydanticAI (2026-03-22) | Trust-gated operations, Captain approval gates. Cleaner gate architecture. |
| Deferred tool execution / async approval | Tool raises ApprovalRequired → run pauses → external review → resume with approved/denied. Serializable checkpoint for tool execution. | PydanticAI (2026-03-22) | Captain approval gates (Phase 33). Async approval workflows where Captain reviews later. |
| Dependency injection via RunContext | Generic dataclass flowing through entire call chain. Functions optionally accept it (detected by signature inspection). ContextVar for implicit access. | PydanticAI (2026-03-22) | CognitiveAgent standardization. Standardize how agents access Ship's Computer services without coupling to self.runtime. |
| Dynamic fan-out via Send | Conditional edges return `[Send("node", custom_input)]` to invoke a node multiple times with different state. Map-reduce enabler. | LangGraph (2026-03-22) | Transporter Pattern, Specialized Builders (Phase 34). Route chunks to different specialists. |
| Typed channel system for state | Six channel types with pluggable update semantics: LastValue, BinaryOperatorAggregate, EphemeralValue, Topic, NamedBarrierValue, UntrackedValue. | LangGraph (2026-03-22) | IntentBus enhancements (Phase 33). NamedBarrierValue for fan-in synchronization (wait for all department chiefs). |
| Checkpoint blob deduplication | Store channel values separately by version. Unchanged values between checkpoints stored only once. | LangGraph (2026-03-22) | Cognitive Journal, future persistence system. Saves storage for large agent state. |
| Version-based trigger detection | Nodes trigger when subscribed channels have versions newer than what the node last saw. Selective wake-up vs broadcast. | LangGraph (2026-03-22) | IntentBus enhancements (Phase 33). More efficient than polling or broadcast for large agent pools. |
| Checkpoint durability modes | sync (before next step), async (concurrent), exit (only on finish). Performance vs reliability tradeoff. | LangGraph (2026-03-22) | Builder Pipeline, long-running workflows. Simple config knob with significant impact. |
| Procedural memory summarization | Structured execution trace format: Task Objective, Progress Status, Sequential Agent Actions (Action→Result→Key Findings→Errors→Context). | Mem0 (2026-03-22) | Dream cycle, CognitiveJournal. Structured compression of execution traces into retrievable summaries. |
| Memory-as-tool pattern | Ship's Computer services exposed as tool calls: `trust_query()`, `knowledge_store()`, `episode_recall()`. Not special API calls, just tools in the agent's toolbox. | Letta (2026-03-22) | CognitiveAgent tool palette. Elegant integration of services into agent decision-making flow. |
| Agent-initiated memory with reasoning | Agent provides explicit `thinking` (reasoning about what to record) alongside `content` when storing memories. Reasoning-before-recording quality gate. | AgentScope (2026-03-22) | EpisodicMemory, KnowledgeStore quality improvement. Mirrors Counselor oversight pattern. |
| Tree-of-thought MCTS reasoning | Monte Carlo Tree Search over reasoning steps. Generate 4+ candidate next steps, evaluate, explore most promising branches. REFLECTION before each step. | AG2 (2026-03-22) | ArchitectAgent, future planning capabilities. Multi-path reasoning vs single-shot. Study only — ProbOS multi-agent consensus already provides exploration/exploitation. |
| Social network graph topology | Directed graph for agent relationships (follow/unfollow). Graph determines information flow paths and influence networks. | OASIS (2026-03-22) | TrustNetwork enhancement, Federation topology. Study only at current scale; revisit for Federation. |
| Simulation time dilation | `k`-factor clock: simulated time runs k× faster than real time. Days of interaction in minutes. | OASIS (2026-03-22) | Holodeck (Long Horizon). Trivially implementable — implement when Holodeck begins. |
| Declarative agent definition (YAML) | Agent configs, tool bindings, orchestration flows declared in YAML with dynamic expression evaluation. | MS Agent Framework (2026-03-22) | Study only. ProbOS uses Python-first extension architecture (Phase 30). YAML adds complexity without clear benefit. |
| Hallucination detection (decompose-then-evaluate) | Segment response sentence-by-sentence, then evaluate each independently against available evidence. | Google ADK (2026-03-22) | CodeReviewAgent, trust model enhancement. Decompose-then-evaluate mirrors Transporter pattern. |
| LSP-backed semantic symbol retrieval | MCP server exposing language server features: find definition, find references, find callers, symbol search across 30+ languages. Structured semantic data vs regex/AST. | Serena (2026-03-22) | CodebaseIndex enhancement. Replaces tree-sitter AST parsing with full LSP precision for symbol resolution. Phase 29c+. |
| Managed auth delegation (OAuth) | SDK handles OAuth flows for 1000+ services. Agent requests "I need GitHub write access" → SDK manages token acquisition, refresh, scoping. Agent never sees raw credentials. | Composio (2026-03-22) | CredentialStore enhancement. Currently credential_store.py does CLI-based resolution; Composio adds managed OAuth delegation for SaaS integrations. |
| Sandboxed tool execution environment | Tools execute in isolated containers (E2B, Docker, Firecracker). Runtime tracks execution metrics per tool. Permission scoping per agent. | Composio (2026-03-22) | Extension sandbox (Phase 30). Tools sandboxed by construction, metrics feed trust model. |
| Pre-extraction actions for web scraping | Execute actions (click, scroll, wait, dismiss popups) before extracting page content. Handles dynamic JS-rendered pages. | Firecrawl (2026-03-22) | Scout v2 research capabilities. Currently Scout uses `gh` CLI for GitHub; Firecrawl adds deep web content extraction for research briefings. |
| Change tracking for web content | Monitor URLs for content changes, diff against previous snapshot. Webhook notifications on change detection. | Firecrawl (2026-03-22) | Scout intelligence monitoring. Track competitor repos, docs pages, API changelogs for proactive briefings. |
| DOM accessibility tree for browser automation | Extract page structure as accessibility tree (roles, names, states) rather than raw HTML. Compact, semantic, LLM-friendly representation. | Browser Use (2026-03-22) | Phase 25/35 browser automation. Use primitives only (not Agent class). Tree is structured context for LLM decision-making. |
| Vision + DOM dual-mode page understanding | Screenshot (vision model) + DOM tree (text model) combined for robust element identification. Vision handles layout, DOM handles precise selectors. | Browser Use (2026-03-22) | Phase 25/35 browser automation. Multi-modal perception for web pages — aligns with Sensory Cortex architecture. |
| Permission-scoped agent tools | Tools declare required permissions (read/write/admin). Agent's trust level determines which tools are available. Token-level metering per tool call. | Stripe AI (2026-03-22) | Earned Agency (Phase 28+33). Reinforces dynamic tool visibility pattern (PydanticAI). Stripe-specific: billing integration for commercial Nooplex. |
| Free-tier model access via CLI gateway | Gemini CLI provides 60 req/min free tier access to Gemini models. Google Search grounding for factual queries. | Gemini CLI (2026-03-22) | ModelRegistry (Phase 32). Study only — competing captain architecture, but free Gemini access is valuable for cost-aware routing. |
| Procedural Learning / Cognitive JIT | LLM-guided action → extract deterministic procedure → replay without LLM (0 tokens). Fallback to LLM on replay failure → learn variant. Trust-based escalation threshold for human decisions. | Architect prior work (ERP config agents) + Ruflo WASM pattern (2026-03-22) | Engineering (Phase 32). Production-validated. Depends on Cognitive Journal for traces + KnowledgeStore for procedure library. |
| WASM kernels for deterministic transforms | Simple code transformations (var→const, add types) run in WebAssembly at <1ms, zero LLM cost. Crude hardcoded version of Procedural Learning. | Ruflo (2026-03-22) | Engineering (Phase 32). ProbOS's Procedural Learning subsumes this — learned procedures vs hardcoded transforms. Study only. |

---

> **External Research Survey & Nooplex Paper Alignment** archived to [roadmap-research.md](roadmap-research.md).

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
| BF-007 | Verification false positive on per-pool agent counts | Medium | **Closed** |
| BF-008 | Dream cycle double-replay after dolphin dreaming | Low | **Closed** |
| BF-009 | @callsign routing missing from HXI `/api/chat` and embedded mentions (e.g., "Hello @wesley") not detected in any entry point | High | **Closed** |
| BF-010 | 1:1 conversations use domain task instructions (===SCOUT_REPORT=== etc.) instead of conversational prompt | Medium | **Closed** |
| BF-011 | Discord adapter `stop()` hangs on Windows — SSL/WebSocket teardown blocks event loop, defeating asyncio timeouts | High | **Closed** |
| BF-014 | "Bundled agents" terminology → "Utility agents" to align with three-tier model (Core/Utility/Crew) | Low | **Closed** |
| BF-015 | Counselor (Troi) 1:1 silent + ungrouped on canvas. (1) `report()` override wrapped conversational responses in `{"data": ...}` instead of preserving `{"result": ...}`, so `handle_intent()` extracted None → "(no response)". (2) No Bridge pool group — counselor pool unmapped → ungrouped on canvas. | Medium | **Closed** |
| BF-016 | Ward Room thread explosion — all 8 crew agents respond to every Captain post, even @mention-directed ones, and no per-thread cap. (a) @mention exclusivity in `_find_ward_room_targets()`. (b) Per-thread agent response cap via `max_agent_responses_per_thread` (default 3). | High | **Closed** |
| BF-017 | Non-crew agents (utility, infrastructure, self-mod) exposed crew-only capabilities: direct chat, personality profiles, proactive cooldown slider. (a) API crew gates on `/api/agent/{id}/chat` and `/api/agent/{id}/proactive-cooldown`. (b) Profile returns `isCrew` flag; empty personality + null proactiveCooldown for non-crew. (c) HXI hides Chat tab and proactive slider for non-crew agents. | Medium | **Closed** |
| BF-018 | Builder agent incorrectly classified as crew in `_WARD_ROOM_CREW`. Builder is a utility agent (AD-398 three-tier) — it writes code when told to, has no Character/Reason/Duty. Proactive loop triggered Builder's code-parsing `act()` on proactive thinks, producing warnings (no file blocks). Removed `"builder"` from `_WARD_ROOM_CREW`. | Low | **Closed** |
| BF-019 | Crew agents (`security_officer`, `operations_officer`, `engineering_officer`) missing from `_AGENT_DEPARTMENTS` mapping. AD-398 added these crew types but never registered their departments — `get_department()` returned None → proactive Ward Room posts fell through to All Hands instead of department channels. Added mappings: `engineering_officer→engineering`, `security_officer→security`, `operations_officer→operations`. | Medium | **Closed** |
| BF-020 | Discord adapter startup reported success (`✓ Discord bot adapter started`) even when `discord.py` was not installed. `adapter.start()` returned silently on ImportError but the caller unconditionally printed the success message. Fixed: check `adapter._started` before printing; show clear error with install command on failure. | Low | **Closed** |
| BF-021 | Duty schedule hard gate — agents with no duty due were still called by the proactive loop, relying on the LLM to respond `[NO_RESPONSE]`. Wesley ignored the instruction and kept producing scout reports every ~7 minutes despite AD-419 setting scout to once daily. Fixed: when duty schedule is active and no duty is due, skip the agent entirely (no LLM call). Saves tokens and enforces schedule constraints deterministically. | High | **Closed** |

> **Bug details (BF-001–011):** All closed. See [roadmap-completed.md](roadmap-completed.md#bug-tracker--closed-issues).


!!! info "Want to contribute?"
    See the [Contributing guide](contributing.md) for how to get involved.
