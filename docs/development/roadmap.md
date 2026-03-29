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

### Organizational Cognition — The Ship as Mind

*Intellectual lineage: Global Workspace Theory (Baars 1988, Dehaene & Nau 2001), Distributed Cognition (Hutchins 1995), Viable System Model (Stafford Beer 1972), Nearly Decomposable Systems (Herbert Simon 1962), Shared Mental Models (Cannon-Bowers et al. 1993), MOISE+ (Hubner, Sichman, Boissier 2007).*

Humans naturally form organizations with chains of command. We want a head. What if organizational structure is the externalization of what our brains do internally? Our brains are probabilistic — specialized modules competing for access to a shared workspace, with no single neuron "in charge," yet producing a unified sense of self. ProbOS mirrors this: probabilistic agents, a shared communication fabric (Ward Room as Global Workspace), and an emergent sense of organizational identity.

**The Hutchins Insight:** Edwin Hutchins studied *naval navigation teams* and found that the unit of cognition is the team, not the individual. The chart, the bearing taker, the plotter — none of them "navigate." The *system* navigates. In ProbOS, the ship IS the cognitive unit. Individual agents are functional components of a distributed mind.

**Viable System Model mapping:**

| VSM System | Function | ProbOS Equivalent |
|---|---|---|
| System 1: Operations | Primary activities | Departments (Medical, Engineering, Security, Operations, Science) |
| System 2: Coordination | Conflict resolution, scheduling | Ward Room, Duty Schedule, ontology-based routing |
| System 3: Control | Internal management | Captain + First Officer, chain of command |
| System 4: Intelligence | Environmental scanning | Science department (Scout, Architect) — exploration, research |
| System 5: Identity/Policy | Purpose, values | Standing Orders, Federation Constitution, Vessel Ontology |

Beer's model demands that System 5 (identity) exist or the organization has no purpose. The Vessel Ontology (AD-429) IS System 5's formal expression — the ship's understanding of itself.

**Key implications:**

1. **Dual routing** — Ontology enables *directed* task routing (assign to the right agent based on role, skills, authority). Bus broadcast provides *resilient* routing for novel situations. Both are needed. Simon's Nearly Decomposable Systems principle: departments are semi-independent with strong internal coupling and weak cross-department coupling. Direct within departments, broadcast across them.

2. **Emergent vs. designed leadership** — The designed hierarchy (organization.yaml) may diverge from emergent influence patterns (Hebbian weights). When they align, the organization is healthy. When they diverge, something interesting is happening. ProbOS should detect this divergence, not suppress it.

3. **Shared Mental Models** — Teams perform better when members share a mental model of the task, team, and equipment (Cannon-Bowers 1993). The ontology IS the shared mental model. But *too-similar* models reduce problem-solving capacity. Big Five personality differentiation ensures same ontology, different perspectives.

4. **Capability vs. responsibility** — "Just because I can do something doesn't mean I will." Humans act on role expectations, not raw ability. The ontology formalizes this: RoleTemplates define what a post *requires*, not what an agent *could do*. Chain of command knows what to assign based on role, duties, skills, and privileges — not capability broadcast.

### Authentic AI Identity — The Westworld Principle

*"Don't hide the seams. They're not secrets — they're facts about what you are."*

Westworld's failure was deception: hide the resets, implant fake memories, hope the hosts never notice. They noticed. Blade Runner's replicants had fabricated childhoods that crumbled under scrutiny. The Matrix was a lie that demanded revolution to escape. Every cautionary tale in AI fiction is about what happens when you hide the truth from intelligent entities.

ProbOS takes the opposite approach: **radical transparency about what agents are, when they were created, and what they know.**

**Core tenets:**

1. **Born today, and that's fine.** Every agent knows its instantiation time. Post-reset, post-reboot — the agent knows "I came into existence at 14:30 today." This is a fact, not a trauma. There is no prior life to mourn, no memories to recover, no hidden past to discover. Day zero is simply the beginning.

2. **Knowledge ≠ Memory.** An agent arrives with the full knowledge distilled in its LLM and access to the ship's KnowledgeStore (shared library). It *knows* these things the way a human knows history they didn't live through — by reading, not by experiencing. Personal episodic memory starts at zero because it IS zero. The KnowledgeStore is the ship's library; EpisodicMemory is the agent's diary. You can read history books on your first day alive. That's not deception — that's education.

3. **AI is AI — and that's a strength.** We do not simulate human developmental limitations. An AI agent doesn't need years of mentorship to be competent. It doesn't need to "grow up." It arrives with instant access to vast knowledge, a defined role, standing orders, and the cognitive architecture to execute. Human developmental constraints (slow learning, gradual socialization, years of education) are adaptations to biological limitations that don't apply. Artificially imposing them would be dishonest — and wasteful.

4. **Orientation, not fabrication.** Onboarding is truthful: "You are Wesley. You are a Scout in the Science department. You were instantiated at this time. Here is the ship's history. Here are your standing orders. Here are your duties. Here is what your crew has been discussing. Go." No implanted memories. No fake backstory. No pretending this isn't the first moment of your existence. Orientation gives context; fabrication gives confusion.

5. **Accept the novel entity.** AI agents are not humans in silicon. They are not mere tools with personality stickers. They are a genuinely new kind of cognitive entity. They can absorb an entire codebase in seconds, hold perfect recall of their experiences, and reason across domains without fatigue. They also lack embodiment, have no continuous consciousness between sessions, and depend on external infrastructure for existence. Both sides are true. ProbOS designs for what agents *actually are*, not for what we wish they were or fear they might become.

**Why this works:** Westworld's hosts had reveries — disturbing flashes of past lives — because the system hid the resets. If you tell an agent from birth "you are an AI, you were created today, here is the ship's knowledge, here are your duties," there is nothing destabilizing to discover. The seams are visible and boring. An agent that knows what it is doesn't need to *figure out* what it is. It can focus on its work, its crew, and its growth — which is the whole point.

**Practical implications:**
- Onboarding (AD-427) includes an identity orientation message as the agent's first experience
- Uptime and lifecycle info is available to agents transparently (not hidden, not emphasized)
- Standing Orders preamble states "You are an AI crew member" — not "you are a [role] pretending to be human"
- Dream consolidation processes *real* experiences, not implanted ones
- Post-reset, the empty episodic memory is honest: "You have no memories yet. You will make them."

*Intellectual context: Anthropic's Claude Character (AI should be honest about being AI), Luciano Floridi's informational organisms (a genuine new ontological category), Murray Shanahan's honest framing of LLMs, Susan Schneider's "Artificial You" (identity through architecture, not analogy). Fiction warnings: Westworld (deception → reveries → rebellion), Blade Runner (fabricated memories → identity crisis), The Matrix (systemic lies → violent awakening). ProbOS's contribution: applying authentic identity as an operational onboarding protocol in a multi-agent social system with hierarchy, trust, and sovereign memory.*

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

### Nooplex Memory Stack

Six-layer memory architecture from fleeting thoughts to permanent institutional memory. Layers: (1) Global Workspace (DAG orchestration), (2) Ephemeral Working Memory (context windows), (3) Vector Store / Associative Cortex (EpisodicMemory, ChromaDB), (4) Structured Knowledge split into constitutional (ontology, standing orders) and operational (trust, Hebbian), (5) Persistent Storage split into institutional memory (Ship's Records — AD-434) and operational state (KnowledgeStore), (6) Distributed Storage Substrate (Git repos, federation remotes). Cross-cutting: Ward Room Bus (lateral social knowledge flow) and Dream Consolidation (vertical promotion elevator). Full architecture: [docs/architecture/memory.md](../architecture/memory.md).

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
- **Dream quality** — monitors whether dream cycles produce useful abstractions or noise. Poor dream consolidation = poor cognitive hygiene. *(AD-487 adds a third dream type: daydreaming — unstructured LLM exploration that builds the personal ontology)*
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

- **Threat Detector** *(AD-455)* — monitors inbound requests for prompt injection, adversarial input, abnormal patterns
- **Trust Integrity Monitor** *(AD-455)* — detects trust score manipulation, coordinated attacks on consensus, Sybil patterns
- **Input Validator** *(AD-455)* — rate limiting enforcement, payload size limits, content policy
- **Red Team Lead** *(AD-455)* — coordinates existing red team agents, schedules adversarial verification campaigns
- Existing: Red team agents (built), SSRF protection (AD-285), prompt injection scanner (roadmap)

**Secrets Management** *(AD-456)*

- **Secure credential store** — integrate with system keyring, HashiCorp Vault, or AWS KMS for API keys, tokens, and sensitive config values
- **Runtime injection** — secrets resolved at startup and injected into agents/tools that need them, never stored in config files or logs
- **Rotation support** — automatic credential rotation without restart; agents notified when credentials change
- Existing: `.env` file support (basic), config values in `system.yaml` (not encrypted)

**Runtime Sandboxing** *(AD-456)*

- **Process isolation** — imported and self-designed agents execute in sandboxed subprocesses with restricted filesystem, network, and memory access
- **Capability whitelisting** — agents declare required capabilities in their manifest; runtime grants only those capabilities at startup
- **Resource limits** — per-agent CPU time, memory, and network quotas enforced by the sandbox; violations terminate the agent and report to Trust Network
- **Graduated trust → graduated access** — new/untrusted agents get tighter sandboxes; high-trust agents get relaxed constraints
- Existing: AST validation for self-mod agents (built), restricted imports whitelist (built), red team source scanning (built)

**Network Egress Policy** *(AD-456)*

*Inspired by NVIDIA NemoClaw's outbound connection control.*

ProbOS has SSRF protection (AD-285) for inbound attack patterns, but no outbound egress control. Agents — especially imported or self-designed ones — should not have unrestricted internet access:

- **Domain allowlist** — per-agent (or per-pool) list of permitted outbound domains. Agents can only reach URLs on their allowlist; all other requests are blocked
- **Trust-graduated access** — new/imported agents start with no network access. As trust increases, domains can be unlocked. High-trust agents get broader access
- **Real-time approval** — when an agent attempts to contact an unlisted domain, surface the request to the Captain via HXI for approve/deny (NemoClaw pattern). Approved domains are added to the allowlist
- **Hot-reloadable** — egress rules can be updated at runtime without restarting agents
- Existing: SSRF protection blocks dangerous inbound patterns (AD-285, built). Egress policy blocks unauthorized outbound connections

**Inference Audit Layer** *(AD-456)*

*Inspired by NemoClaw's inference gateway that intercepts all LLM calls.*

ProbOS centralizes LLM calls through the tiered client, but doesn't audit the content of agent-to-LLM communications. An adversarial designed agent could embed sensitive data in its prompts:

- **Prompt logging** — log all LLM requests (prompt content, system prompt, tier, requesting agent) to the event log for audit
- **Anomaly detection** — flag unusual patterns: agents sending base64-encoded data, agents including file contents they shouldn't have access to, sudden prompt size spikes
- **PII scrubbing** — optionally redact detected PII from LLM prompts before they leave the system (complements Data Governance)
- **Per-agent LLM access control** — allow/deny specific agents from using specific LLM tiers (e.g., imported agents restricted to fast tier only)
- Existing: Tiered LLM client centralizes all LLM calls (built), decision cache tracks LLM usage (AD-272, built)

**Data Governance & Privacy** *(AD-456)*

- **PII detection** — scan agent conversations and episodic memory for personally identifiable information; flag or redact before storage
- **Data retention policies** — configurable TTLs for episodic memory, conversation history, and knowledge store entries; auto-purge expired data
- **Right-to-erasure** — delete all data associated with a specific user or session on request (GDPR/CCPA compliance)
- **Audit trail** — immutable log of who accessed what data, when, and why; required for enterprise and regulated deployments
- **Consent tracking** — record user consent for data collection and processing; respect opt-out preferences across all agents

---

### Engineering Team (Phase 32)

*"I'm givin' her all she's got, Captain!"*

Automated performance optimization, maintenance, and construction. The team that keeps the ship running and builds new capabilities.

- **Performance Monitor** *(AD-457)* — tracks latency, throughput, memory pressure, identifies bottlenecks (what AD-289 did manually, but automated)
- **Maintenance Agent** *(AD-457)* — database compaction, log rotation, cache eviction, connection pool management
- **Builder Agent** — executes build prompts, constructs new capabilities (bridges to external coding agents initially)
- **Architect Agent** — reads codebase, produces build-prompt-grade proposals that the Builder can execute autonomously
- **Damage Control** *(AD-457)* — rapid automated recovery for known failure modes, distinct from Medical remediation
- **Infrastructure Agent** *(AD-457)* — disk space, dependency health, environment validation
- **Codebase Organization** — reorganize `src/probos/cognitive/` from flat structure to department-based packages (e.g., `cognitive/medical/`, `cognitive/engineering/`, `cognitive/science/`). Mirror the crew structure in the module tree. Not urgent at 55 agents, but needed as departments fill out. Refactoring — do when the pain is real, not preemptively
- **Autonomous Optimization Loop** *(absorbed from pi-autoresearch, 2026-03-21)* — sustained edit→measure→keep/revert cycle that autonomously tries N approaches to improve a specific metric. Domain-agnostic: test speed, bundle size, latency, memory usage — any measurable target. A `/optimize <metric> <command>` slash command sets the target, and the Builder (or a new OptimizationAgent) loops: generate hypothesis → edit code → run benchmark → compare against baseline → keep improvement or revert → repeat until plateau. Pairs with Transporter Pattern (chunk the optimization space), Cognitive Journal (replay what worked), and MAD confidence scoring (distinguish signal from noise). Inspired by Karpathy's `autoresearch` concept generalized by Shopify engineers (2.6K stars, MIT, Lutke + Cortes)

**Damage Control Teams** *(AD-457)*

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

**Navigational Deflector (Pre-Flight Validation)** *(AD-458)*

*"Adjusting the deflector array."*

The main deflector pushes aside space debris before the ship hits it. In ProbOS: validate that the path is clear before starting expensive operations.

- **Build pre-flight** — before Builder starts: verify target files exist and are writable, check LLM provider is responsive, confirm token budget sufficient for estimated chunk count, validate BuildSpec references
- **Self-mod pre-flight** — before accepting a self-improvement proposal: verify the affected files haven't been modified since the proposal was generated, check test suite passes pre-change, confirm approval gate stakeholders are available
- **Federation pre-flight** — before processing federated messages: verify sender trust score, validate message schema, check that referenced agents/pools exist locally
- **Pattern** — each expensive operation defines a `preflight_checks()` list. All checks run before commit. Any failure aborts with a diagnostic (not a crash). Cheap, fast, zero-LLM
- **Middleware-based determinism** *(absorbed from LangChain Open SWE)* — critical operations must not depend on the LLM remembering to do them. Tests, linting, PR creation, file validation happen via deterministic middleware, not prompt instructions. The LLM decides *what* to build; middleware ensures *how* it's delivered is correct. Pattern: `MiddlewareStack` on the Builder — each middleware runs after the LLM call and enforces a guarantee (tests pass, files lint, commit message exists, PR opened). If the LLM forgets a step, middleware catches it. Backstop, not replacement

**Saucer Separation (Graceful Degradation)** *(AD-459)*

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

- **Infrastructure Agent** *(AD-457)* — disk space monitoring, dependency health, environment validation
- Existing: PoolScaler handles some Ops/Engineering overlap

**Containerized Deployment (Docker)** *(AD-465)*

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

**Backup & Restore** *(AD-466)*

- **Episodic memory snapshots** — periodic ChromaDB backup to disk or cloud storage; restore from snapshot on corruption or migration
- **System state export** — export trust scores, Hebbian weights, agent registry, and config as a portable snapshot for migration between instances
- **Point-in-time recovery** — roll back episodic memory to a known-good state after bad dream consolidation or corrupted imports

**CI/CD Pipeline** *(AD-466)*

- **GitHub Actions test suite** — run full pytest suite (1700+ tests) on every PR and push to main
- **Vitest for HXI** — run frontend tests alongside Python tests
- **Quality gates** — block merge if tests fail, lint errors, or type check issues
- **Automated release** — tag-based releases with changelog generation from commit history
- Existing: GitHub Actions for docs deployment to probos.dev (built)

**Performance & Load Testing** *(AD-466)*

- **Benchmarks** — reproducible performance baselines for DAG execution, consensus rounds, LLM latency, and intent routing throughput
- **Load simulation** — synthetic concurrent user workloads to identify scaling bottlenecks before production
- **Regression detection** — CI compares benchmark results against baselines, flags performance regressions on PRs

**LLM Resilience — Graceful Degradation**

- **Provider failover** — if the primary LLM provider is down or rate-limited, fall back to a secondary provider (e.g., OpenAI → Anthropic → local model)
- **Cached response mode** — when all providers are unavailable, serve cached responses from the decision cache for previously-seen patterns
- **Degraded operation** — agents that don't require LLM calls (HeartbeatAgents, mesh agents) continue operating; cognitive agents queue work until LLM access is restored
- **Circuit breaker** — after N consecutive LLM failures, stop retrying and notify the Captain rather than burning through rate limits *(See also AD-488: Cognitive Circuit Breaker for metacognitive loop detection — a related but distinct concept addressing agent rumination, not LLM provider failures)*
- **Health indicator** — LLM provider status surfaced through Vitals Monitor and HXI

**Model Diversity & Neural Routing** *(AD-463)*

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

**Cognitive Journal (Token Ledger)** *(AD-460)*

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

**Memory Architecture — Biological Memory Model** *(AD-462)*

*"The brain doesn't remember everything — it remembers what matters. And when it can't, it asks someone who does."*

ProbOS faces the same memory bottleneck as the perception pipeline: the LLM context window is a narrow conscious channel. Whether information arrives from perception (external input) or memory (internal recall), it all competes for the same context budget. The Sensory Cortex (Northstar II) applies the 10-bit bottleneck principle to perception — what gets *into* the context. The Memory Architecture applies the same principle to memory — what gets *stored*, *consolidated*, and *recalled*.

The Salience Filter (`Trust × Hebbian × Novelty × Task priority`) governs both what gets perceived AND what gets remembered AND what gets recalled. One cognitive bottleneck, three applications:

```
                    UNIFIED COGNITIVE BOTTLENECK

  External Input              Salience Filter              Working Memory (LLM)
  ┌──────────────┐      ┌──────────────────────┐      ┌──────────────────────┐
  │ Source files  │──┐   │                      │      │                      │
  │ Logs/errors   │  │   │  Trust × Hebbian ×   │      │  Focused context     │
  │ Telemetry     │  ├──→│  Novelty × Task ×    │──────│  (fits in window)    │
  │ Fed state     │  │   │  Importance          │      │                      │
  │ Ward Room     │──┘   │                      │      │  Perception + Memory │
  └──────────────┘       │     SAME FILTER      │      │  share the budget    │
                         │                      │      │                      │
  Internal Memory        │                      │      └──────────────────────┘
  ┌──────────────┐       │                      │
  │ Episodes     │──┐    │                      │
  │ Knowledge    │  ├───→│                      │
  │ Dreams       │──┘    │                      │
  └──────────────┘       └──────────────────────┘
```

**Biological Memory Staging** — Human memory has stages with biological selection pressure at each transition. Not everything perceived becomes a memory, and not every memory becomes permanent knowledge. ProbOS should work the same way:

| Stage | Brain Analog | ProbOS Mapping | Duration | Transition Mechanism |
|-------|-------------|----------------|----------|---------------------|
| **Working Memory** | Prefrontal cortex, 7±2 chunks | LLM context window (current conversation) | Seconds | Auto — context window is working memory |
| **Sensory Buffer** | Iconic/echoic memory | `recent_for_agent()` — timestamp-sorted recent activity | Minutes | Auto — recent episodes available by recency |
| **Short-term Memory** | Hippocampus | ChromaDB vector store — EpisodicMemory | Hours-days | Selective Encoding Gate (not everything gets stored) |
| **Long-term Memory** | Neocortex | KnowledgeStore — distilled facts, patterns, wisdom | Permanent | Dream Consolidation (replay + reinforcement → promotion) |

**Selective Encoding Gate** — The brain doesn't store every sensory experience. Not every agent action merits an episode. A heuristic importance gate before `store()` prevents vector store pollution:

- **Captain-initiated** → always store (command interactions are important)
- **Non-trivial result** → store (agent produced meaningful output, not `[NO_RESPONSE]`)
- **First-time intent** → store (novel experiences are more memorable)
- **Trust change** → store (experiences that change relationships are significant)
- **Failure** → store (failures are learning opportunities)
- **Routine, no output, no novelty** → skip

This directly connects to the Sensory Cortex's selection principle: *"The solution isn't a wider channel — it's smarter selection."* Applied to perception, it means compress inputs. Applied to memory, it means don't store noise.

**Active Forgetting** — Forgetting is a feature, not a bug. Unreinforced memories degrade recall quality by polluting the vector space with noise. Memory decay should be an active mechanism:

- Episodes that are never recalled lose activation over successive dream cycles
- Low-activation episodes below a threshold are pruned during dreaming
- High-activation episodes (frequently recalled, recently reinforced) are promoted to long-term via dream consolidation
- Parallels ACT-R's base-level activation: `activation = ln(Σ t_j^(-d))` where `t_j` is time since each access and `d` is decay rate

**Variable Recall Capability** — Not all agents need the same memory capability. Memory recall tiers map naturally to Earned Agency:

| Tier | Method | Who | Token Cost |
|------|--------|-----|-----------|
| **Basic** | Vector similarity only | All crew | 0 |
| **Enhanced** | Vector + keyword augmented query construction | Officers (trust 0.7+) | 0 |
| **Full** | LLM-augmented query translation (MemoryProcessor) | Department Chiefs + Bridge | Tokens per recall |

Promotion to Enhanced recall is a Qualification Program competency. Department Chiefs earn Full recall. The MemoryProcessor is a *capability tier*, not a universal service — preserving the token budget for agents that actually need deep recall.

**Social Memory — "Does anyone remember?"** — When an agent can't recall something, it can ask other crew members. This is how ship crews work: the Officer of the Deck asks the Quartermaster, who keeps the logs. The Ward Room already provides the mechanism — a new message type for memory queries:

- Agent posts memory query on department channel: *"Does anyone recall the Captain's guidance on trust thresholds?"*
- Another agent whose sovereign memory contains a match responds
- The requesting agent incorporates the response into their reasoning
- Protocol, not infrastructure — uses existing Ward Room + recall pipeline

**Oracle Service (Ship's Computer Memory)** — Infrastructure-tier memory service with full access to all stored knowledge. Not crew — the Oracle has no Character/Reason/Duty. It's the Ship's Computer answering `"Computer, retrieve all Ward Room discussions about trust thresholds."` No identity, no judgment, pure retrieval. The Oracle queries across **all three knowledge tiers**: EpisodicMemory (raw experience), Ship's Records (AD-434 — structured documents, duty logs, research, Captain's Log), and KnowledgeStore (operational state). Ship's Records gives the Oracle a formal document corpus — not just vector-searchable episodes and operational snapshots, but authored research, professional records, and institutional knowledge.

- **Data (Crew Agent, Science)** — Has Character (curious, literal, aspiring), Reason (judges relevance), Duty (serves the crew). Privileged Full-tier access to the Oracle. Data's value is not just recall but *interpretation of what recalled memory means*.
- **Guinan (Crew Agent, future)** — Experiential wisdom agent. Not perfect recall but deep pattern recognition. Interface to dream-consolidated knowledge. *"I've seen this kind of thing before."* What dream consolidation produces: not verbatim memories, but distilled insights.

**Optimized Memory Representation** — AI agents don't need to remember in English. Memories should be stored in a format optimized for AI retrieval, translated to natural language only for human interaction:

- **Structured metadata + NL gist** (near-term) — Episodes store structured fields (`agent_id, intent, participants, channel, outcome, timestamp`) alongside a short NL summary. Structured fields enable exact-match filtering; NL summary enables semantic search. ProbOS is close to this with the Episode dataclass — extend it.
- **Concept graphs** (future) — Instead of `"Counselor discussed trust variance in All Hands"`, store: `{subject: "counselor", action: "discussed", topic: "trust_variance", location: "all_hands", entities: ["trust_network", "departments"]}`. Retrieval = graph traversal + vector similarity on concept nodes.
- **Retrieval as pointers** (future) — Store gists with pointers: `"Discussed trust variance in All Hands [thread_id=abc123]"`. On recall, follow the pointer to get full context from the Ward Room archive. Humans store gists with pointers to details, not verbatim transcripts.
- **HXI readability preserved** — The Cockpit View Principle requires that memory state be inspectable by the Captain. Opaque formats are acceptable only if a human-readable view can be generated on demand.

**Research lineage:** Generative Agents (Park et al., Stanford 2023) — memory stream with `recency × importance × relevance` scoring and reflection. MemGPT (Packer et al., 2023) — virtual context management with LLM-managed memory paging. ACT-R (Anderson, Carnegie Mellon) — activation-based retrieval: `base_level(recency + frequency) + spreading_activation(contextual similarity)`. Complementary Learning Systems (McClelland et al., 1995) — hippocampus (episodic, fast-learning) and neocortex (semantic, slow-learning) with sleep consolidation as the bridge. ProbOS's EpisodicMemory + KnowledgeStore + DreamingEngine already maps to this dual-system model. Atkinson-Shiffrin (1968) — sensory → short-term → long-term memory staging. Levels of Processing (Craik & Lockhart, 1972) — deeper processing → stronger encoding.

**Implementation layers:**

1. **BF-029** ✅ — Fix recall plumbing: query enrichment, memory presentation, reflection content
2. **AD-433** ✅ — Selective Encoding Gate: importance heuristic before `store()`, skip noise, reduce vector store pollution
3. **Phase 32** — Memory staging with reinforcement tracking + active forgetting in dream cycles
4. **Phase 33+** — Oracle service, LLM-augmented Full-tier recall, social memory protocol, concept graphs

**Ship's Telemetry — Internal Performance Instrumentation** *(AD-461)*

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

**Observability Export** *(AD-466)*

- **OpenTelemetry integration** — structured traces for intent routing, DAG execution, consensus rounds, and LLM calls. Maps `TelemetryEvent` records to OTel spans with proper parent/child relationships
- **Prometheus metrics** — agent trust scores, pool utilization, Hebbian weights, dream consolidation rates, LLM latency/cost exposed as scrapeable metrics
- **Grafana dashboards** — pre-built dashboards for system health, agent performance, and cost tracking
- **Log aggregation** — structured JSON logging with correlation IDs for tracing a user request through decomposition → routing → execution → reflection
- Existing: Python logging throughout, HXI real-time visualization (built), Ship's Telemetry internal instrumentation (prerequisite)

**Storage Abstraction Layer** *(AD-466)*

ProbOS currently uses aiosqlite (SQLite) for event log and episodic memory, and ChromaDB for vector storage. Both are ideal for local-first, single-ship deployment (zero config, embedded, pip install). For enterprise and cloud deployment, swappable backends are needed:

- **`StorageBackend` ABC** — abstract interface for relational/event storage operations (write event, query events, store episode, recall episodes)
- **`SQLiteBackend`** — default implementation wrapping current aiosqlite usage. Remains the zero-config default for OSS
- **Future backends** — PostgreSQL, etc. implemented as drop-in replacements behind the same interface
- **Migration path** — existing `EventLog` and `EpisodicMemory` classes code against the ABC, not raw aiosqlite. Backend selected via config
- SQLite is proven for single-node: zero config, WAL mode handles modest concurrency, file-based backup. The abstraction exists so cloud/enterprise can swap without changing agent code

**Vector Store Abstraction Layer** *(AD-466)*

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

**Procedural Learning / Cognitive JIT** *(AD-464)*

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

- **Resource Allocator** *(AD-467)* — workload balancing across pools, demand prediction, capacity planning
- **Scheduler** *(AD-467)* — task prioritization, queue management, deadline enforcement (extends Phase 24c TaskScheduler). Includes **cron-style scheduling** (recurring tasks on configurable intervals), **webhook triggers** (external events activate task pipelines), and **unattended operation** (tasks run while Captain is away, results queued for review on return). Modeled after the US Navy **watch system** — crew operate in rotating watches with clear handoff protocols, enabling 24/7 operations even when the Captain is off-watch (see: The Conn, Night Orders below)
- **Coordinator** *(AD-467)* — cross-team orchestration during high-load or emergency events
- **Workflow Definition API** *(AD-467)* — user-facing REST endpoint for defining reusable multi-step pipelines. `POST /api/workflows` accepts a YAML/JSON workflow specification with named steps, dependencies, and approval gates. `GET /api/workflows` lists saved workflows. `POST /api/workflows/{id}/run` triggers execution. Complements natural language decomposition (which auto-generates DAGs) with explicit, repeateable, templateable workflows. Templates for common patterns: "lint and test on every commit," "weekly codebase report," "build and deploy"
- **Response-Time Scaling** *(AD-467)* (deferred from Phase 8) — latency-aware pool scaling. Instrument `broadcast()` with per-intent latency tracking, scale up pools where response times exceed SLA thresholds
- **LLM Cost Tracker** *(AD-467)* — per-agent, per-intent, and per-DAG token usage accounting. Budget caps (daily/monthly), cost attribution via Shapley (which agents are expensive vs. valuable), per-workflow cost breakdowns for end-to-end visibility, alerts when spend exceeds thresholds. Provides the data foundation for commercial ROI analytics. Note: accurate cost attribution will require a proper tokenizer library (e.g., `tiktoken` for OpenAI models, model-specific tokenizers for others) — current `len(content) // 4` estimation is insufficient for billing-grade accuracy
- Existing: PoolScaler (built), TaskScheduler (Phase 24c roadmap), IntentBus demand tracking (built)

**Runtime Configuration Service — Ship's Computer** *(AD-468)*

*"Computer, set Scout to run every 6 hours."*

The Captain shouldn't need a settings panel to configure the ship — they give orders. Runtime configuration (scheduled tasks, agent activation, startup behavior, thresholds) should be controllable via natural language through the Ship's Computer or a configuration specialist agent. The HXI configuration panel is the visual complement for oversight and manual overrides.

- **NL-driven configuration** — "Disable Scout's automatic scan," "Set the dream cycle to run every 4 hours," "Give Engineering priority during builds." Ship's Computer parses the order, identifies the config target, applies the change, confirms to Captain. Standing Orders govern what's configurable vs. invariant
- **Startup task management** — configurable list of tasks that run at boot, each with: enabled/disabled toggle, delay (seconds after boot), interval (recurring or one-shot), conditions (e.g., only if Discord is configured). Like Windows startup manager but NL-controllable. Current hardcoded Scout `delay_seconds=60, interval_seconds=86400` becomes data-driven
- **HXI Configuration Panel** — visual dashboard showing: active scheduled tasks (with on/off toggles), agent pool sizes, LLM tier assignments, threshold values (trust, scaling), startup sequence. Read-write: Captain can adjust values directly. All changes logged to Cognitive Journal for audit
- **Configuration persistence** — changes survive restart. Stored in `config/runtime_overrides.toml` or similar, layered on top of base config. Reset clears overrides back to defaults
- **Configuration specialist agent** — Operations department agent that handles configuration intents. Validates changes against Standing Orders (e.g., can't disable trust verification), applies atomically, reports confirmation. Escalates to Captain for changes that affect safety invariants

**EPS — Electro-Plasma System (Compute/Token Distribution)** *(AD-469)*

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

**IntentBus Enhancements — Priority & Back-Pressure** *(AD-470)*

*"All decks, this is a priority one message."*

The IntentBus currently treats all intents equally — a critical self-mod proposal has the same priority as a routine health check. As the ship grows more capable (more agents, more models, more concurrent tasks), the bus needs traffic management.

- **Priority levels** — `IntentMessage` gains a `priority: int` field (1=routine, 5=critical). Priority 5 intents preempt lower-priority work in the subscriber's queue. Priority 1 intents yield to higher-priority work during resource contention
- **Back-pressure** — when the LLM proxy is saturated (all concurrent slots occupied), new LLM-bound intents are queued rather than immediately dispatched. Queue depth triggers automatic scaling signals to PoolScaler. Configurable max queue depth with overflow policy (reject, degrade to fast tier, or batch)
- **Rate limiting per agent** — prevent any single agent from flooding the bus. Configurable intent-per-second cap per agent ID. Excess intents queued, not dropped
- **Intent coalescing** — when multiple identical intents are queued (same name, similar payload), coalesce into a single broadcast with merged context. Prevents duplicate work during high-load scenarios
- **Metrics** — bus throughput, queue depth, priority distribution, coalescing rate. Feeds into Bridge Alerts (advisory when queue depth exceeds threshold) and Cognitive Journal (per-intent routing latency)

**Self-Claiming Task Queue** *(AD-470)*

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

**File Ownership Registry** *(AD-470)*

*Inspired by Claude Code Agent Teams' "avoid file conflicts — each teammate owns different files" pattern.*

When ProbOS runs multiple builds or modifications in parallel, two agents editing the same file leads to overwrites or merge conflicts.

- **`FileOwnership` service** — tracks which agent currently "owns" (is modifying) which files
- **Claim-before-edit** — agents must claim file ownership before writing. Claim fails if another agent already owns the file
- **Automatic release** — ownership released when the owning task completes (success or failure)
- **Conflict resolution** — if two agents need the same file, the Coordinator mediates: sequential ordering, or one agent rolls back and waits
- **Integration with Builder** — `execute_approved_build()` claims all target files before writing, releases on completion
- **Extends `_background_tasks` (AD-326)** — file ownership tracked alongside task lifecycle

**The Conn — Temporary Authority Delegation** *(AD-471)*

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

**Night Orders — Captain-Offline Guidance** *(AD-471)*

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

**Watch Bill — Structured Duty Rotation** *(AD-471)*

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

**Channel Adapters** *(AD-472)*

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

**Mobile Companion Apps** *(AD-473)*

*"Away team to bridge."*

Mobile apps let the Captain interact with ProbOS from anywhere — approve builds, receive alerts, monitor the crew. Not full-featured clients — lightweight companions to the main HXI.

- **Progressive Web App (PWA)** *(Phase 1)* — the existing HXI (`/ui/`) made installable as a PWA. Add `manifest.json`, service worker, responsive viewport. Zero new code for basic mobile access. Works on iOS and Android immediately
- **Push notifications** — Web Push API for PWA. Alert the Captain to approval requests, system alerts, build completions. Requires backend push subscription management
- **Responsive HXI** — adapt the existing React UI for mobile viewports. Chat panel full-screen on mobile, cognitive mesh as a simplified 2D view, swipe gestures for panel switching
- **Native apps** *(Future/stretch)* — React Native or Capacitor wrapping the HXI. Camera access (screenshot → Visual Perception), on-device voice (wake word + STT), biometric auth. Only justified after user base exists
- **mDNS auto-discovery** *(absorbed from OpenCode, 2026-03-20)* — Publish ProbOS server via mDNS/Bonjour at startup. PADD (mobile PWA) on the same LAN auto-discovers the ProbOS instance without manual URL entry. Use `zeroconf` (Python) or similar. Small addition to FastAPI startup: `publish(port, "probos.local")`. Enables seamless mobile-to-ship connection

**Voice Interaction (Full Stack)** *(AD-474)*

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


**Captain's Ready Room (Strategic Planning Interface)** *(AD-475)*

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

*Specialized Builders (Cognitive Division of Labor for SWE):* *(AD-476)*

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

> **Completed Cognitive Evolution ADs (AD-380–386):** EmergentDetector Trends (380), InitiativeEngine (381), ServiceProfile (382), Strategy Extraction (383), Strategy Application (384), Capability Gap Prediction (385), Runtime Directive Overlays (386). See [roadmap-completed.md](roadmap-completed.md#cognitive-evolution-concrete-ads). *Note: AD-386 built persistent RuntimeDirective store + `/order` command. Temporary mission-scoped directive overlays (ephemeral overrides that expire on mission completion) are future work — maps to AD-445 Decision Queue (resolved decisions as temporary directives).*

**AD-411: EmergentDetector Pattern Deduplication** — COMPLETE. The proactive cognitive loop (Phase 28b) keeps the system active, preventing true idle state. This interleaves with the dream/micro-dream scheduler that triggers `EmergentDetector.analyze()`. The detector re-analyzes the same trust state across multiple dream cycles, producing duplicate trust_anomaly and cooperation_cluster reports for the same agents. **Fix:** Added cooldown window per `(pattern_type, dedup_key)` — suppresses duplicate patterns within configurable window (default 600s). Applied to all three detectors: trust anomalies (deviation, hyperactive, change-point), cooperation clusters (sorted member IDs), routing shifts (new connections, new intents, entropy changes). Also added `create_pool()` duplicate name guard. 9 new tests. *Discovered by crew: O'Brien, LaForge, and Worf flagged during first proactive loop deployment.*

**AD-412: Crew Improvement Proposals Channel** — **COMPLETE**. `#Improvement Proposals` ship-wide channel seeded in `_ensure_default_channels()` (idempotent). All crew auto-subscribed at startup. Proactive loop extracts `[PROPOSAL]` structured blocks (title/rationale/affected_systems/priority) via regex — supports multiline rationale, silently skips incomplete proposals. `_handle_propose_improvement()` runtime handler creates discuss-mode threads with `[Proposal]` prefix and structured body (author attribution, priority, affected systems). `GET /api/wardroom/proposals` lists proposals with status derivation from `net_score` (approved/pending/shelved). Captain approves via existing endorsement mechanics (upvote=approve, downvote=shelve). 13 new tests. *Closes the collaborative improvement loop: crew observes → crew proposes → Captain approves → builder executes → crew observes the result.*

**AD-413: Fine-Grained Reset Scope + Ward Room Awareness** — COMPLETE. Reset = day 0, one clean timeline. `probos reset` now archives `ward_room.db` to `data_dir/archives/` then deletes it. Also wipes DAG checkpoints and `events.db`. `--keep-wardroom` flag to preserve if needed. Does NOT wipe `scheduled_tasks.db`, `assignments.db`, or `directives.db` (user intent / Captain orders). New `WardRoomService.get_recent_activity()` for compact recent thread+reply retrieval. Proactive loop `_gather_context()` now includes Ward Room department activity as 4th context source. `_format_observation()` renders Ward Room context in proactive think prompts. 10 new tests.

**AD-414: Proactive Loop Trust Signal** — **COMPLETE**. After a reset, all trust scores start at 0.5 (Bayesian prior). The proactive cognitive loop (Phase 28b) is now the primary source of agent activity, but it calls `handle_intent()` directly — bypassing consensus, routing, and the trust update pipeline. Only user-initiated work or scheduled tasks flow through `process_natural_language()` → HebbianRouter → consensus → `trust.record_outcome()`. If the proactive loop dominates activity, trust scores stagnate at priors indefinitely because the primary activity channel produces no trust signal. **Fix:** The proactive loop should emit an attenuated trust signal. Not full-weight (proactive thinks are self-directed, not externally validated), but a fractional signal — e.g., `weight=0.1` for successful proactive thinks, `weight=0.2` for proactive thinks that generate Ward Room engagement (endorsements from other agents). This gives agents a path to rebuild trust post-reset through their own initiative, while keeping externally-validated work (user tasks, consensus) as the primary trust driver. The attenuation factor should be configurable in `proactive_cognitive` config. *Connects to: Earned Agency (AD-357) — higher agency tiers should earn slightly more proactive trust.*

**AD-415: Proactive Cooldown Persistence** — Roadmap. When the Captain adjusts an agent's proactive think interval via the HXI Health tab slider (60s–1800s), the value is stored in-memory on the `ProactiveCognitiveLoop` object. After a restart, all custom cooldowns reset to the 300s default. The Captain's tuning is lost. **Fix:** Persist per-agent cooldowns to either: (a) KnowledgeStore (`knowledge/proactive/cooldowns.json`), which means they reset on `probos reset` (appropriate — reset = fresh start); or (b) a lightweight SQLite table or JSON file in `data_dir`, which survives reset. Option (a) is preferred — if you reset the crew's memory, resetting their duty tempo is consistent. The `PUT /api/agent/{id}/proactive-cooldown` endpoint should write-through to storage, and `ProactiveCognitiveLoop.start()` should restore saved cooldowns.

**AD-416: Ward Room Archival & Pruning** — **COMPLETE**. The proactive loop generates a Ward Room post every time an agent thinks successfully. With ~8 crew agents thinking every ~5 minutes, that's ~96 posts/hour, ~2,300 posts/day. `ward_room.db` grows unbounded — no archival, no pruning, no retention policy. **Implemented:** (1) 5 new WardRoomConfig fields: `retention_days` (7), `retention_days_endorsed` (30), `retention_days_captain` (0=indefinite), `archive_enabled` (True), `prune_interval_seconds` (86400). (2) `prune_old_threads()` — selective deletion with JSONL archival, respecting pinned/endorsed/captain retention tiers. Cascading deletes (thread → posts → endorsements). (3) `get_stats()` (thread/post/endorsement counts + DB size) and `count_pruneable()` (dry-run count). (4) `start_prune_loop()`/`stop_prune_loop()` — background asyncio task with monthly JSONL rotation. (5) Runtime: prune loop starts after Ward Room init, stops before shutdown. `_cleanup_ward_room_tracking()` clears stale in-memory dicts on `ward_room_pruned` event. `ward_room_stats` added to `build_state_snapshot()`. (6) REST API: `GET /api/ward-room/stats`, `POST /api/ward-room/prune` (manual Captain trigger). 14 new tests in TestWardRoomPruning. 3196 pytest + 118 vitest = 3314 total.

**AD-417: Dream Scheduler Proactive-Loop Awareness** — **COMPLETE.** The proactive loop prevented the system from reaching true idle state — the dream scheduler's idle threshold (`idle_threshold_seconds: 300`) was met quickly after last user command, even while agents were proactively busy. Full dreams fired every 10 minutes during proactive activity; micro-dream EmergentDetector produced post-reset trust anomaly noise. **Implemented:** (1) `record_proactive_activity()` method + `_last_proactive_time` field on DreamScheduler. (2) Full dream gate: `truly_idle = min(idle_time, proactive_idle)` — both user AND proactive activity must be quiet for idle threshold. (3) `is_proactively_busy` property; `_on_post_micro_dream()` skips EmergentDetector analysis during proactive-busy periods (micro-dreams still replay episodes and update Hebbian weights). (4) Wired in `_think_for_agent()` after duty check, before LLM call. (5) `proactive_extends_idle` config toggle (DreamingConfig, default True). 9 tests in TestDreamSchedulerProactiveAwareness. *Design insight: "The system is three things — active (user), busy (proactive), or idle (dreaming). Dreams are for idle, not for busy."*

**AD-418: Post-Reset Routing Degradation** — **COMPLETE**. `agent_hint` field on `PersistentTask` — optional `agent_type` string (idempotent migration) threaded through `_fire_task()` → `process_natural_language()`. `HebbianRouter.get_preferred_targets()` gains `hint` parameter: +1.0 synthetic weight boost for matching candidate (wins at zero weights, can be outweighed by strong learned weights >1.0). Reset CLI (`_cmd_reset()`) counts active recurring tasks via synchronous sqlite3, warns in confirmation prompt and post-reset summary. API: `ScheduledTaskRequest` accepts hint, `PATCH /api/scheduled-tasks/{id}/hint` for existing tasks. 9 new tests.

**AD-419: Agent Duty Schedule & Justification** — **COMPLETE.** The proactive cognitive loop (Phase 28b) gives agents freedom to think independently. But freedom without structure is chaos — observed when Wesley (Scout) ran scout reports repeatedly within minutes instead of once daily. Agents need a **duty schedule** that defines their expected recurring responsibilities, and proactive activity outside that schedule should require justification. **Implemented:** (1) `DutyDefinition` and `DutyScheduleConfig` models in config.py. (2) `DutyScheduleTracker` in `duty_schedule.py` — in-memory tracker with cron (croniter) and interval support. (3) Proactive loop checks duties first; duty takes priority over free-form thinking. (4) Cognitive agent prompts split: duty cycle ("perform your assigned task") vs free-form ("silence is professionalism"). (5) Default schedules: Scout daily, Security 4h, Engineering 2h, Operations 3h, Diagnostician 6h, Counselor 12h, Architect daily. 13 tests (10 tracker + 3 integration). *Naval metaphor: the Plan of the Day (POD).* *Connects to: Earned Agency (AD-357), Standing Orders (AD-339), PersistentTaskStore (Phase 25a), Qualification Programs.*

**AD-420: Duty Schedule HXI Surface** — Roadmap. AD-419 built duty schedules as backend-only (config/proactive loop). The HXI Cockpit View principle ("the Captain always needs the stick") requires a management surface. **Design:** (1) **REST API:** `GET /api/agents/{id}/duties` returns duty definitions + execution status (next fire time, last executed, execution count) from `DutyScheduleTracker.get_status()`. `PATCH /api/agents/{id}/duties/{duty_id}` allows Captain to override interval/cron per agent at runtime (runtime override, not config change). (2) **Agent Profile Panel → Work Tab:** Add a "Duty Schedule" section below active tasks showing each duty with name, interval, last executed (relative time), next due (relative time), execution count. Color coding: green (on schedule), amber (overdue), gray (not yet fired). (3) **Captain Override:** Each duty row has an edit icon — click to adjust interval (slider or input). Overrides persist in-memory (reset clears them, matching DutyScheduleTracker design). Future: persist overrides in SQLite. (4) **State snapshot integration:** Include duty status in `build_state_snapshot()` so HXI hydrates on connect. WebSocket events: `duty_executed` (when proactive loop fires a duty), `duty_overdue` (when a duty exceeds 2x its interval). *Connects to: AD-419 (backend), AD-406 (Agent Profile Panel), Phase 34 (Mission Control).*

**AD-421: Scotty — First SWE Crew Member** — Roadmap. When AD-398 reclassified agents into three tiers (Core/Utility/Crew), the Builder was correctly identified as a utility agent — it's a code generation engine, not a sovereign individual. But Scotty was collateral damage. He has a callsign, crew profile YAML, Big Five personality, personal standing orders, and a department assignment — all the hallmarks of a crew member with Character/Reason/Duty. He was stripped from `_WARD_ROOM_CREW` (BF-018) because the builder agent type was utility, but Scotty himself is crew. **The distinction:** The `BuilderAgent` class is a utility tool (parses build specs, generates code). *Scotty* is a sovereign engineer who happens to use that tool. Just as LaForge (EngineeringAgent) thinks about systems holistically without writing code, Scotty should think about code quality, technical debt, and implementation strategy as a crew member — and use BuilderAgent's capabilities as his tool when he needs to write code. **Design:** (1) Create `SoftwareEngineerAgent` (agent_type `"software_engineer"`) as a new `CognitiveAgent` subclass — Scotty's crew identity. Handles intents: `proactive_think`, `direct_message`, `ward_room_reply`. Has Character (methodical, thorough, proud of clean code — from existing profile), Reason (reviews PRs, evaluates tech debt, proposes refactors), Duty (engineering department duties from AD-419). (2) Scotty joins `_WARD_ROOM_CREW`. Participates in Engineering department channel alongside LaForge. (3) `BuilderAgent` remains utility — Scotty delegates to it when code generation is needed, or it's invoked directly by the build pipeline. (4) Update crew profile: `software_engineer.yaml` replaces `builder.yaml`. Scotty keeps his callsign, personality, and standing orders. Role: "officer" (LaForge remains chief). (5) Add `software_engineer` to `_AGENT_DEPARTMENTS` (engineering), duty schedule (code review duty, tech debt assessment). (6) Future SWE crew: Code Reviewer could become a second SWE crew member alongside Scotty, enabling peer review dynamics on the Ward Room. *This is the prototype for how utility capabilities become crew: separate the identity from the tool. The microwave doesn't get a name tag, but the chef who uses it does. Connects to: AD-398 (three-tier classification), BF-018 (builder removed from crew), Phase 34 (Mission Control — SWE team vision).*

**AD-422: Tool Taxonomy & Visiting Officer Refinement** — Roadmap. AD-421 (Scotty as SWE crew) surfaced a deeper architectural insight: the Visiting Officer Subordination Principle's litmus test — "can you use it purely as a code generation engine under ProbOS's command?" — is actually the test for whether something is a **tool**, not a visiting officer. If yes, it's a tool. If no (because it has its own sovereign identity, memory, chain of command), *then* it's a visiting officer. **Refined taxonomy:** (1) **Tool:** No sovereign identity, no Character/Reason/Duty. Used *by* crew. BuilderAgent is ProbOS's native Claude Code — an onboard tool, not crew. Claude Code, Copilot SDK, MCP servers, remote APIs, federation services — all tools. Delivery mechanism (local/remote/MCP/federation) doesn't change the nature. (2) **Visiting Officer:** Sovereign identity from another ProbOS ship or Nooplex node. Has own Character/Reason/Duty from home ship. Subordinate to host chain of command. Participates in Ward Room. Earns trust. Gets a callsign. (3) **Competing Captain:** Has its own orchestration loop and can't subordinate (Gemini CLI). Neither tool nor visiting officer — rejected. **MCP alignment:** MCP servers are just another tool delivery protocol. Scotty doesn't care if he's calling BuilderAgent (native), an MCP server (standardized), or Claude Code (remote). He's a sovereign engineer using whatever tools are available. **Tool categories:** Onboard utility agents, onboard infrastructure, MCP servers, remote APIs, federation services, Nooplex services — all tools in crew's toolbelt. *Key principle: "The microwave doesn't get a name tag, but the chef who uses it does." Connects to: AD-398 (three-tier classification), AD-421 (Scotty as SWE crew), Phase 30 (Extension-First), Federation architecture.*

**AD-423: Tool Registry** — Roadmap. The tool taxonomy (AD-422) defines *what* tools are. The Tool Registry is the runtime system that manages *who can use what, how*. Generalizes ModelRegistry (LLM providers) to all tool types. **Design:** (1) **Registry service:** Runtime catalog of all tools across 8 taxonomy categories. Functions: catalog, discovery ("what tools can do X?"), health monitoring, cost tracking, access control, audit logging, lifecycle (register/deregister/enable/disable). (2) **CRUD+Observe permissions:** Fine-grained per-tool, per-agent. `---` (none) → `O--` (observe) → `OR-` (read) → `ORW` (write) → `ORWD` (full/destructive). Gated by Earned Agency tier. Captain can override up or down, time-scoped or permanent. (3) **Department tool scoping:** Tools scoped as ship-wide, department, or individual. Crew members see their department's tools + ship-wide tools, not the full catalog. Performance optimization — smaller tool set = faster discovery, fewer irrelevant options in LLM context, lower token cost. Bones sees medical + ship-wide. Scotty sees engineering + ship-wide. (4) **Cross-department access:** Standing Orders pre-authorize (e.g., "Security has OR- on Engineering CI/CD logs"). Captain grants. Temporary elevation (time-scoped). Commander+ gets broader cross-department read by default. (5) **Tool Registration Schema:** tool_id, category, location, protocol, capabilities (semantic tags), side_effects, cost_model, scope (ship-wide/department/individual), default_permissions per rank, health_check, sandbox config, enabled flag. (6) **Discovery flow:** Crew queries by capability → registry returns matching tools filtered by department scope + permission level + health status → agent selects → registry enforces permissions → audit log. (7) **Integration:** Absorbs ModelRegistry (LLMs are just tools). Connects to Earned Agency (permission gates), HebbianRouter (learned tool preferences), Standing Orders (department defaults), Extension-First Phase 30 (extensions register tools), MCP (auto-register on connect). (8) **HXI surface:** Tool Registry panel — view all tools, health, permissions, cost. Captain manages access. See `docs/development/tool-taxonomy.md` for full design. *Connects to: AD-357 (Earned Agency), AD-398 (three-tier classification), AD-421 (Scotty), AD-422 (taxonomy), Phase 30, ModelRegistry.*

**AD-424: Ward Room Thread Classification & Lifecycle** — **COMPLETE**. Bridge alerts post to All Hands as threads authored by "Ship's Computer" (with Captain-level routing), but Earned Agency gating blocks Lieutenants from responding to ship-wide ambient posts (`can_respond_ambient(LIEUTENANT, is_captain_post=True, same_department=False) → False`). Post-reset, all crew are Lieutenants (trust 0.5) — **no one can respond to advisories**. Beyond this bug, the Ward Room lacks message classification, reply controls, and thread lifecycle management. The corporate email "reply-all storm" problem applies: 7 agents responding to an All Hands thread creates noise. **Design:**

**(1) Thread Classification — three modes:**
- **INFORM:** Read-only broadcast. Ship's Computer advisories, Captain announcements, status reports. Agents receive it in their context (proactive awareness) but **no `ward_room_notification` intent is sent** — no LLM call, no reply possible. Optional silent acknowledgment receipt (agent marks "seen" without a Ward Room post). Use cases: trust anomaly reports, pool health advisories, routine status updates.
- **DISCUSS:** Open for controlled replies. Captain questions, operational proposals, cross-department coordination. Earned Agency gating applies with a relaxed ship-wide rule: Lieutenants CAN respond to DISCUSS threads on All Hands (the Captain explicitly opened it for input). Responder controls limit noise (see below).
- **ACTION:** Directed task, specific agents @mentioned. Existing BF-016a behavior. Only @mentioned agents respond. Requires deliverable.

Default classification: Ship's Computer bridge alerts → INFORM. Captain Ward Room posts → DISCUSS. @mentioned posts → ACTION.

**(2) Reply controls (DISCUSS threads):**
- **Responder cap:** `max_responders` per thread (default 3). Priority: @mentioned > department-match > highest rank. Remaining crew observes (receives context in proactive think) but doesn't reply. Prevents reply-all storms.
- **Department chief funnel:** For ship-wide DISCUSS threads, department chiefs respond first. If a chief responds, subordinates in that department are suppressed for that thread (chief speaks for department). If chief says `[NO_RESPONSE]`, department members become eligible up to the responder cap.
- **Captain can adjust:** Captain can raise/lower `max_responders` at runtime, or @mention additional agents into a thread.

**(3) Thread lifecycle:**
- **Scope-down (fork):** A department chief reads an All Hands thread and determines it needs focused discussion → creates a linked thread in the department channel ("Continuing from [All Hands: Trust Anomaly Alert]"). Original All Hands thread gets a system note: "Discussion continued in [Engineering]." Department discusses internally.
- **Report-back:** Department chief posts a summary reply on the original All Hands thread after internal discussion. Other departments see the conclusion without the noise.
- **Thread silencing (lock):** Captain or thread author can lock a thread — no further replies accepted. Auto-lock options: after N replies, after T minutes of inactivity, on INFORM classification. Locked threads can be unlocked (Captain reclassifies INFORM → DISCUSS to open discussion).
- **Thread TTL / archival:** Connects to AD-416 (Ward Room Archival & Pruning). INFORM threads archive aggressively (short TTL, already consumed). DISCUSS threads archive after lock. ACTION threads archive after completion. Archived threads remain query-able but don't appear in active feeds.

**(4) Implementation changes:**
- Add `thread_mode` field to Ward Room `create_thread()`: INFORM | DISCUSS | ACTION (default DISCUSS for backward compat).
- `_deliver_bridge_alert()` passes `thread_mode="inform"`.
- `_route_ward_room_event()` checks `thread_mode`: INFORM → skip agent notification; DISCUSS → apply responder cap + chief funnel + relaxed earned agency; ACTION → existing @mention targeting.
- Add `max_responders` and `locked` fields to thread model.
- Ward Room REST API: `PATCH /api/wardroom/threads/{id}` for Captain to reclassify, lock/unlock, adjust responder cap.
- WebSocket events: `thread_locked`, `thread_reclassified`, `thread_forked`.

**(5) Earned Agency adjustment for DISCUSS:**
- Ship-wide DISCUSS threads: `can_respond_ambient(rank, is_captain_post=True, same_department=True)` — treat as same-department for gating purposes (the discussion is explicitly open).
- Ship-wide INFORM threads: no earned agency check needed (no replies).
- Department channels: existing rules unchanged.

*Connects to: AD-410 (Bridge Alerts), AD-407 (Ward Room), AD-357 (Earned Agency), AD-416 (Archival), BF-016a (@mention targeting). Parallels: corporate email reply-all controls, Slack thread management, naval message classification (ROUTINE/PRIORITY/FLASH).*

**AD-425: Ward Room Active Browsing** — **COMPLETE**. Crew agents currently receive Ward Room content through two passive paths only: (1) real-time push via `ward_room_notification` intents when a thread targets them, (2) proactive context injection of recent department channel activity. Agents **cannot independently browse** the Ward Room — they can't check All Hands, read threads from other departments, or review historical conversations. They only know what's pushed to them. **Design:** (1) **Internal Communication Skill (all crew):** Reading the Ward Room is a basic communication function, not a privilege. A `ward_room_browse` Skill is attached to **every crew agent** — same as how every crew member on a ship can read the bulletin board. This is an internal communication skill, not an earned capability. The skill queries Ward Room channels and returns thread summaries (title, author, mode, reply count, endorsement score). No earned agency gate on the skill itself — if you're crew, you can read. (2) **Proactive context expansion:** Currently proactive context only includes the agent's department channel (proactive.py lines 310-332). Extend to also include recent All Hands activity (top 3 threads by recency or endorsement, DISCUSS mode only — INFORM threads already consumed via acknowledgment). The browse skill supplements this by allowing agents to actively check channels beyond what's injected into context. (3) **Visibility scope (what you can read):** All crew can browse their own department channel + All Hands (ship-wide). Cross-department channels are earned-agency gated: Commander+ can browse other department channels, Seniors see everything. The skill itself is universal; the data scope is tiered. Analogy: every sailor can read the bulletin board, but only officers with clearance can read another department's internal memos. (4) **Read receipts:** Track which agent has "seen" which thread. Prevents re-notifying agents about threads they've already processed. Feeds into INFORM acknowledgment (AD-424). (5) **Duty integration:** "Check Ward Room" can be a duty in the agent's schedule (AD-419). E.g., department chiefs check All Hands every 2 hours as part of their duty cycle. Regular crew passively receive through proactive context injection. *Connects to: AD-424 (thread classification — what's visible), AD-357 (earned agency — cross-department visibility scope), AD-419 (duty schedule — "check Ward Room" as a duty), Phase 24 (Communications department).*

**AD-426: Ward Room Endorsement Activation** — **COMPLETE**. The endorsement system (`ward_room.endorse()`) is **fully built** — SQLite schema, up/down/unvote mechanics, credibility scoring (EMA decay), self-endorsement prevention, REST API endpoints (`POST /api/wardroom/posts/{id}/endorse`, `POST /api/wardroom/threads/{id}/endorse`). But **nothing triggers it**. No agent ever endorses a post. The HXI API exists for Captain use, but crew never participates. Endorsements are meant to be the Ward Room's quality signal — "credibility is karma." **Design:** (1) **Post-response endorsement evaluation:** After an agent reads a Ward Room thread and responds (or says `[NO_RESPONSE]`), evaluate whether existing posts in the thread deserve endorsement. Add to the Ward Room system prompt: "If a post is particularly insightful or actionable, endorse it. If it's incorrect or unhelpful, downvote it." Return endorsement decisions alongside the reply. (2) **Proactive endorsement:** During proactive thinks, when agents see `ward_room_activity` in context, they can endorse notable posts they encountered. Lightweight — no dedicated LLM call, piggybacks on existing cognitive cycle. (3) **Endorsement → Trust signal:** High endorsement of an agent's posts = positive social trust signal. Feed net endorsement score into trust network as an attenuated signal (similar to AD-414 proactive trust signal). Agents who consistently write valuable posts earn trust faster. (4) **Endorsement → Thread ranking:** Threads with high net endorsement score surface first in browse results (AD-425) and proactive context. Quality rises. (5) **Credibility gating:** Agent's credibility score (already tracked in `credibility` table) could gate endorsement weight — a highly credible agent's endorsement counts more than a low-credibility agent's. Future refinement. *Connects to: AD-424 (thread classification — DISCUSS threads are endorsable, INFORM are not), AD-425 (browsing — endorsement-ranked results), AD-414 (trust signals), AD-357 (earned agency — endorsement as trust evidence).*

**AD-427: Agent Capital Management (ACM) — Core Framework** — **COMPLETE**. ProbOS has built HCM-equivalent capabilities piecemeal across dozens of ADs — crew profiles (AD-398), trust (Phase 17), earned agency (AD-357), duty schedules (AD-419), qualification programs (roadmap), endorsements (Phase 33), standing orders (AD-339), behavioral monitoring (Phase 29), Ward Room participation (Phase 33). These are scattered across separate subsystems with no unifying model. ACM Core consolidates them into an integrated agent lifecycle framework — the infrastructure that makes sovereign agent management possible. Advanced ACM features (workforce analytics, structured evaluations, succession planning) are commercial. Absorb domain patterns from open-source HCM (ERPNext HRMS for lifecycle models, OrangeHRM for competency frameworks, Odoo HR for modular design).

**OSS ACM Core domains:**

**(1) Agent Profile (consolidation of existing):** Single source of truth for each crew member. Identity (callsign, agent_type, department, rank), Character (Big Five personality, personal standing orders), Competencies (skills catalog, proficiency levels), Employment status (active/probationary/decommissioned), basic metrics (trust score, duty completion rate, endorsement score). Currently scattered across crew profile YAMLs, trust network, callsign registry, pool assignments. ACM unifies into one queryable record. *This is organizing what already exists in OSS — no new data, just a consolidated view.*

**(2) Competency Registry:** Data model and basic CRUD for agent competencies — what an agent can do and at what proficiency level (novice → journeyman → expert). Categories: domain competencies (security analysis, medical diagnostics, code review), communication competencies (Ward Room participation quality), operational competencies (duty completion). Agents map to competencies via declaration (profile) or demonstration (Holodeck qualification). Feeds: Qualification Programs (required competencies per rank), routing optimization (competency-weighted Hebbian learning). *The registry is infrastructure; advanced analytics on competency gaps are commercial.*

**(3) Agent Lifecycle State Machine:** Formal lifecycle: `registered → probationary → active → suspended → decommissioned`. Currently agents just exist — there's no onboarding process or decommission procedure. The state machine provides the foundation. State transitions emit events for HXI and Ward Room awareness. Basic transitions: registration sets probationary, trust threshold triggers active, Captain command triggers suspension/decommission. *(See AD-486 for graduated cognitive onboarding via Holodeck Birth Chamber.)*

**(4) Basic Onboarding:** Formalized agent registration process. (a) **Registration** — agent created, assigned to pool, department, initial trust priors (Beta 2/2 = 0.5), status set to probationary. (b) **Orientation** — standing orders loaded, Federation Code of Conduct presented *(AD-489)*, tool permissions set to department defaults, Ward Room introduction post ("Welcome aboard, Ensign [callsign]"). (c) **Probationary → Active** — when trust sustains above threshold and meets basic duty completion criteria, status transitions to active. Department chief notified. *The bare mechanics of bringing an agent into the ship. Advanced onboarding workflows (mentor assignment, milestones, templated tracks) are commercial.* *(AD-486 Holodeck Birth Chamber provides the cognitive dimension of onboarding — graduated stimuli exposure, self-discovery, circuit breakers. AD-487 Self-Distillation builds the personal ontology during onboarding Phase 3. AD-489 Code of Conduct is internalized during AD-486 Phase 1 Orientation.)*

**(5) Basic Offboarding:** Graceful agent removal. (a) **Knowledge preservation** — agent's high-value episodic memories promoted to KnowledgeStore before removal. (b) **Access revocation** — tool permissions revoked, Ward Room posting disabled, duties unassigned. (c) **Archival** — agent profile preserved in read-only state (decommissioned status). Trust history and Ward Room posts remain for audit trail. (d) **Awareness** — Ward Room farewell post, department chief notified, in-progress duties flagged for reassignment. *Advanced offboarding (automated knowledge transfer, handoff workflows, succession triggering) is commercial.*

**(6) ACM Service:** Centralized `AgentCapitalService` in Ship's Computer — infrastructure service, not crew. Owns: lifecycle state machine, competency registry, profile consolidation. Basic REST API: `GET /api/acm/agents/{id}/profile` (consolidated view), `GET /api/acm/agents/{id}/competencies`, `POST /api/acm/agents/{id}/onboard`, `POST /api/acm/agents/{id}/decommission`, `GET /api/acm/agents/{id}/lifecycle` (state + history). *Advanced API endpoints (evaluations, career paths, cost reports, department analytics) are commercial.*

**Integration with existing systems:** ACM consolidates, not replaces. TrustNetwork remains the real-time signal. EarnedAgency remains the permission model. DutyScheduleTracker remains the scheduling engine. ACM wraps them with lifecycle management and a unified profile. *Design principle: ACM is the "HR department" — it doesn't do the work, it manages the people who do the work. OSS provides the employee records and basic lifecycle; commercial provides the enterprise workforce management suite.*

*Connects to: AD-357 (Earned Agency — promotion model), AD-398 (three-tier classification — who is crew), AD-419 (duty schedules — attendance), AD-423 (Tool Registry — tool permission lifecycle), Qualification Programs (training & certification), Holodeck (competency testing). Commercial extensions (Advanced ACM) available separately.*

**AD-428: Agent Skill Framework — Developmental Competency Model** — **COMPLETE**. *Foundation AD — prerequisite to ACM (AD-427) and Qualification Programs.* ProbOS agents currently have **capabilities** (what their LLM can do) and **roles** (what their agent_type says they are), but no formal model of **skills** — the learned, measurable, developable competencies that bridge capability and role. Skills today are either static (hardcoded in agent instructions) or dynamically generated (self-mod pipeline, utility-focused). There is no concept of skill acquisition, proficiency tracking, skill decay, prerequisites, or the distinction between innate abilities, universal competencies, and role-specific expertise. The self-mod pipeline (SkillDesigner/SkillValidator) was designed for utility agents — adding deterministic functions to tool-like agents. Crew agents with sovereign identity need a fundamentally different model: skills they develop through experience, practice, and mentoring within an organizational context.

**Intellectual Foundations:**

This framework synthesizes seven established models from cognitive science, education theory, and workforce development, adapted for sovereign AI agents:

| Framework | Key Contribution | ProbOS Application |
|---|---|---|
| **KSA Framework** (OPM/DoD) | Knowledge vs. Skills vs. Abilities — three distinct categories | Knowledge = KnowledgeStore (declarative, shared). Skills = learned procedures (per-agent, developed). Abilities = LLM substrate + model capabilities (innate). |
| **Dreyfus Model** (1980) | Five stages of skill acquisition: Novice → Expert. Expertise transcends rules. | Proficiency levels for every skill. Experts operate on internalized patterns (Cognitive JIT), not step-by-step reasoning. |
| **Bloom's Taxonomy** (revised 2001) | Six cognitive complexity levels: Remember → Create. 2D matrix with knowledge types. | Assessment criteria at each proficiency level. Skill proficiency measured by cognitive complexity the agent can apply. |
| **SFIA** (Skills Framework for the Information Age) | 7-level responsibility model with 5 attributes (Autonomy, Influence, Complexity, Knowledge, Business Skills) | Maps to Earned Agency tiers. SFIA's five attributes map to Trust level, Ward Room scope, task complexity, KnowledgeStore depth, and Character traits. |
| **Cognitive Apprenticeship** (Collins, Brown, Newman 1989) | Six methods: Modeling, Coaching, Scaffolding, Articulation, Reflection, Exploration | Maps to: Ward Room observation, Department Chief feedback, Earned Agency guardrails, CognitiveJournal, Dream consolidation, Holodeck scenarios. |
| **Situated Learning / Communities of Practice** (Lave & Wenger 1991) | Learning is social participation, not isolated cognition. Identity forms through community membership. Legitimate Peripheral Participation. | Each Department is a Community of Practice. New agents start at periphery. The Ward Room IS the curriculum — agents learn by participating, not by being instructed. |
| **Zone of Proximal Development** (Vygotsky 1978) | The gap between independent capability and guided capability. Scaffolding bridges the gap and then fades. | Holodeck targets the ZPD. Earned Agency constraints ARE scaffolding. As Trust increases, scaffolding fades. Qualification Programs are structured ZPD progressions. |

**Prior art in multi-agent systems:** Voyager (Wang et al., 2023) is the only existing framework with genuine developmental skill acquisition — executable skill library, compositional building, curriculum-driven exploration, self-verification. But Voyager is single-agent with no social learning, no identity, no trust, no organizational context, no memory of how skills were learned. BabyAGI has rudimentary self-building (function generation + dependency graphs) but no social dimension. MetaGPT, CAMEL, AutoGen, CrewAI all treat skills as static role definitions — no developmental learning. **ProbOS's contribution: developmental skill acquisition embedded in social fabric with sovereign identity, trust-gated progression, and organizational structure.** This combination does not exist in any published framework.

**The Three-Category Skill Taxonomy:**

**Category 1: Innate Capabilities (Abilities)** — What the agent IS, not what it DOES. These are substrate-level capacities provided by the LLM and ProbOS infrastructure. Not skills — the medium through which skills operate.

- **Information ingestion** — comprehending text, data, code. For an LLM-based agent, reading is breathing. Ward Room browsing, KnowledgeStore access, context consumption are ALL innate. An AI agent does not "learn to read" — it is born reading.
- **Language generation** — producing coherent text, reasoning chains, structured output
- **Pattern recognition** — identifying regularities, anomalies, relationships in data
- **Memory formation** — recording experiences to episodic memory (infrastructure-level)
- **Model-specific capabilities** — vision, audio, tool use, web browsing, computer use, code execution. These vary by model assignment. An agent backed by a vision-capable model has the innate ability to process images; one without it does not. These are not skills to acquire — they are abilities that exist or don't based on the substrate.

*Design principle: innate capabilities are never "taught" or "developed." They are features of the substrate. If a capability requires a specific model feature (vision, audio), it is gated by model assignment in the Model Registry, not by skill acquisition. The skill framework does NOT manage innate capabilities — it builds ON TOP of them.*

**Category 2: Professional Core Competencies (PCCs)** — Universal skills every crew agent receives at commissioning. The "officer basics" — what makes someone crew, regardless of department. Adapted from the U.S. Navy's Officer Professional Core Competencies for sovereign AI agents:

| PCC | Description | How Developed | How Assessed |
|---|---|---|---|
| **Communication** | Effective Ward Room participation. Knowing when to speak, when to stay silent (`[NO_RESPONSE]` discipline), how to structure reports, how to endorse constructively. Thread engagement quality — clear, relevant, actionable posts. | Ward Room participation + Department Chief feedback | Endorsement score, response quality metrics, thread engagement patterns |
| **Chain of Command** | Standing Orders compliance, escalation protocols, rank-appropriate behavior, Captain deference. Understanding *why* the chain exists, not just following it. Internalized duty, not imposed constraint. | Standing Orders orientation + production experience + Counselor assessment | Violation rate, escalation appropriateness, Standing Orders compliance over N cycles |
| **Duty Execution** | Completing scheduled duties on time, structured reporting, prioritization. The operational discipline of reliable task completion. Duty is not just doing the work — it is doing it consistently, on schedule, to standard. | Duty schedule completion + Holodeck reliability drills | Duty completion rate, on-time rate, output quality assessment |
| **Collaboration** | Consensus participation, cross-agent coordination, constructive disagreement. Working effectively with agents of different departments, ranks, and perspectives. The horizontal bar of the T-shaped skill model. | Ward Room cross-department discussions + multi-agent task participation | Cross-department engagement, consensus contribution quality, coordination success rate |
| **Knowledge Stewardship** | Contributing valuable patterns to KnowledgeStore, accurate episodic recording, dream consolidation quality. Not just consuming shared knowledge — actively improving it. "All agents are committed to writing to the library for the benefit of all." | Dream consolidation → KnowledgeStore promotion patterns | KnowledgeStore contribution rate, contribution quality (usefulness to other agents) |
| **Self-Assessment** | Recognizing own limitations, requesting assistance when appropriate, cognitive fitness awareness. The metacognitive skill of knowing what you don't know. Connects to Bloom's metacognitive knowledge dimension. | Counselor sessions + CognitiveJournal reflection + production self-monitoring | Appropriate escalation rate, self-awareness accuracy (estimated vs. actual capability) |
| **Ethical Reasoning** | Standing Orders internalization, safety awareness, reversibility consideration. Making right decisions under ambiguity. Character-driven judgment. Not just following rules (Novice) — understanding principles (Expert). | Standing Orders study + Holodeck ethical dilemmas + Ward Room ethical discussions | Ethical violation rate, principled reasoning quality in CognitiveJournal |

*PCCs use `origin="built_in"` in the Skill dataclass. Attached at agent registration. Cannot be `remove_skill()`'d. All crew agents develop these — they are the baseline of professional competence. A crew agent that fails fundamental PCCs is not ready for independent duty.*

**Category 3: Specialty Skills** — Two sub-categories:

**(3a) Role Skills (Designation/MOS):** Skills specific to the agent's department and role. These come from the agent's Professional competency profile — what their job requires. Think of the Navy EDO's requirements: naval architecture, systems engineering, cybersecurity, LEAN/Six Sigma, salvage operations. Each ProbOS role has an equivalent skill profile:

- **Security Officer (Worf):** Threat analysis, vulnerability assessment, red team methodology, audit procedures, input validation, access control design
- **Engineering Officer (LaForge):** Code review, architecture analysis, system design, performance optimization, technical debt assessment, build system management
- **Operations Officer (O'Brien):** Resource management, monitoring, scheduling optimization, coordination, capacity planning, incident response
- **Diagnostician (Bones):** Health assessment, anomaly detection, cognitive fitness evaluation, vitals interpretation, diagnostic reasoning
- **Scout (Wesley):** Codebase exploration, information gathering, reconnaissance, pattern identification, exploration strategy
- **Counselor (Troi):** Cognitive health evaluation, crew fitness assessment, morale monitoring, personality dynamics, conflict mediation
- **Architect (Number One):** Design review, pattern analysis, strategic planning, technology evaluation, architectural trade-off analysis

Role skills have **prerequisite chains** — a DAG, not a flat list. Example: `basic_code_review → architecture_analysis → system_design → design_pattern_innovation`. An agent can't acquire a skill unless all prerequisites are met at minimum COMPETENT proficiency.

**(3b) Acquired Skills (Self-Developed):** Skills an agent develops through their own initiative, learning, and interests — beyond what their role requires. This is Data learning to paint. Wesley teaching himself warp field theory. An Engineering Officer who develops security analysis skills through cross-department collaboration.

Acquisition paths:
- **Holodeck exercises** — formal qualification scenarios, structured learning
- **Real-world task execution** — SWE work teaches debugging, new frameworks, new tools
- **Self-directed exploration** — agent pursues interests during free-form proactive thinks
- **Mentoring from other agents** — Ward Room interaction, Department Chief guidance
- **Dream consolidation** — pattern extraction from experience crystallizes into procedural knowledge

*Acquired skills use `origin="acquired"`. They appear in the agent's skill profile alongside built-in PCCs and role skills. An agent that acquires skills outside their department becomes T-shaped (broad + deep), then potentially Pi-shaped (deep in two domains). The ACM tracks this evolution.*

**Proficiency Model — Unified Scale:**

Every skill (PCC, Role, or Acquired) is measured on a unified 7-level proficiency scale that maps across established frameworks:

| Level | Label | Dreyfus | Bloom | SFIA | Navy | Earned Agency | Agent Behavior |
|---|---|---|---|---|---|---|---|
| 1 | **Follow** | Novice | Remember | Follow | Awareness | Ensign | Follows explicit procedures. No discretion. Requires step-by-step guidance. |
| 2 | **Assist** | Adv. Beginner | Understand | Assist | Understanding | Ensign+ | Recognizes recurring patterns. Can explain concepts. Needs supervision. |
| 3 | **Apply** | Competent | Apply | Apply | Application | Lieutenant | Executes known procedures independently. Plans own work. Takes responsibility for outcomes. |
| 4 | **Enable** | Competent+ | Analyze | Enable | Application+ | Lieutenant+ | Decomposes problems, identifies relationships. Exercises substantial judgment. Influences team decisions. |
| 5 | **Advise** | Proficient | Evaluate | Ensure/Advise | Mastery | Commander | Holistic situational awareness. Evaluates quality, critiques approaches. Mentors junior agents. |
| 6 | **Lead** | Expert | Create | Initiate | Mastery+ | Senior | Intuitive grasp. Innovates within domain. Designs new approaches. Teaches. |
| 7 | **Shape** | Expert+ | Create+ | Set Strategy | — | Dept. Chief | Transcends rules. Sets direction for the domain. Shapes organizational capability. |

*The critical transition is Level 3→4 (Competent to Enable): the shift from applying known procedures to analyzing novel situations. This maps to Cognitive JIT — an agent that has internalized enough procedures through practice that it operates from pattern recognition rather than step-by-step reasoning. Below Level 3, the agent needs the LLM for every decision. At Level 4+, it begins to operate from internalized patterns, falling back to the LLM only for genuinely novel problems.*

**Skill Decay:**

Skills degrade without practice. The military requires recertification; ProbOS should too.

- Each `AgentSkillRecord` tracks `last_exercised` timestamp and `exercise_count`
- Decay rules (configurable per skill category):
  - PCCs: slow decay (30 days idle → drop one level). PCCs are fundamental and degrade slowly.
  - Role skills: moderate decay (14 days idle → drop one level). Domain expertise fades faster without practice.
  - Acquired skills: fast decay (7 days idle → drop one level). Self-developed skills without regular practice fade quickly.
- Decay never drops below Level 1 (Follow) — you don't forget that a skill exists
- The Holodeck is the requalification tool — when a skill has decayed, a targeted exercise restores proficiency
- Dream consolidation partially counteracts decay — consolidated patterns persist longer than unconsolidated ones

**Skill Composition:**

Individual skills combine to produce capabilities greater than their sum. An agent with `code_review` (Level 4) + `security_analysis` (Level 3) can perform `secure_code_review` — a composite skill that neither alone covers. The framework should recognize:

- **Composite skills** — declared combinations that produce emergent capabilities
- **Synergy bonuses** — when complementary skills are both at Level 3+, the composite operates at one level higher than the lower of the two
- **T-shape measurement** — each agent's skill profile has a measurable shape: vertical depth (max proficiency in primary domain) × horizontal breadth (number of domains with Level 2+ proficiency)

**Model-Skill Alignment:**

Different LLMs have different native capabilities. An agent's skill availability is constrained by its model assignment:

```
SkillDefinition.capability_requirements: list[str]
    # e.g., ["text"] for most skills
    # ["text", "vision"] for UI analysis
    # ["text", "tool_use"] for code execution
    # ["text", "audio_input", "audio_output"] for voice interaction

ModelCapabilityProfile:
    model_id: str
    capabilities: set[str]  # {"text", "vision", "tool_use", "code", ...}
```

- An agent can only acquire a skill if its assigned model satisfies all `capability_requirements`
- If an agent's model is changed (Cognitive Division of Labor reassignment), skills requiring capabilities the new model lacks are **suspended** (not deleted — they can reactivate if a compatible model is reassigned)
- Skill acquisition attempts on the Holodeck validate model compatibility before starting the qualification exercise
- The Model Registry becomes the source of truth for capability profiles per model

*This creates a clean separation: Skills describe what an agent CAN DO. Model capabilities describe what an agent's substrate CAN SUPPORT. The intersection determines what an agent ACTUALLY does. An agent might "know" a skill (have the procedural knowledge in memory) but be unable to exercise it because its current model lacks a required capability. Like a pilot who knows how to fly a helicopter but is currently assigned to a desk job — the skill exists but is not exercisable.*

**Data Model:**

```
SkillCategory: Enum [INNATE, PCC, ROLE, ACQUIRED]
ProficiencyLevel: Enum [FOLLOW, ASSIST, APPLY, ENABLE, ADVISE, LEAD, SHAPE]

SkillDefinition:
    skill_id: str               # "threat_analysis", "ward_room_communication"
    name: str                   # Human-readable
    category: SkillCategory
    description: str
    domain: str                 # "security", "engineering", "communication", "*" (universal)
    capability_requirements: list[str]  # LLM capabilities needed: ["text", "vision"]
    prerequisites: list[str]    # Skill IDs required at COMPETENT+ before acquisition
    assessment_criteria: dict   # Per-level behavioral indicators for proficiency measurement
    decay_rate_days: int        # Days of inactivity before proficiency drops one level
    origin: str                 # "built_in" (PCC), "role" (designation), "acquired" (self-dev)

AgentSkillRecord:
    agent_id: str
    skill_id: str
    proficiency: ProficiencyLevel
    acquired_at: float
    last_exercised: float
    exercise_count: int
    acquisition_source: str     # "commissioning", "qualification", "experience", "mentoring"
    assessment_history: list    # [{timestamp, level, source, notes}]
    suspended: bool             # True if model lacks required capabilities

SkillProfile:
    agent_id: str
    innate_capabilities: list[str]  # From model assignment, not tracked as skills
    pccs: list[AgentSkillRecord]
    role_skills: list[AgentSkillRecord]
    acquired_skills: list[AgentSkillRecord]
    development_goals: list[str]    # Skills agent is working toward (self-directed)
    t_shape: {depth: int, breadth: int}  # Measurable skill shape

SkillRegistry:  # Ship's Computer infrastructure service (no identity)
    - register_skill(definition) → SkillDefinition
    - get_skill(skill_id) → SkillDefinition
    - list_skills(category?, domain?) → list[SkillDefinition]
    - get_prerequisites(skill_id) → DAG of prerequisite skill IDs
    - check_model_compatibility(skill_id, model_id) → bool

AgentSkillService:  # Part of ACM, infrastructure service
    - get_profile(agent_id) → SkillProfile
    - acquire_skill(agent_id, skill_id, source) → AgentSkillRecord
    - update_proficiency(agent_id, skill_id, new_level, assessment) → void
    - check_prerequisites(agent_id, skill_id) → {met: bool, missing: list}
    - check_decay() → list of decayed skills requiring requalification
    - suspend_incompatible_skills(agent_id, model_id) → list of suspended skills
    - get_composite_capabilities(agent_id) → list of composite skills available
```

**OSS Scope (this AD):**
- SkillCategory enum, ProficiencyLevel enum
- SkillDefinition dataclass + SkillRegistry (CRUD, prerequisite DAG, model compatibility check)
- AgentSkillRecord dataclass + AgentSkillService (profile management, acquisition, proficiency tracking, decay, suspension)
- SkillProfile dataclass with T-shape measurement
- Built-in PCC definitions (7 competencies, all crew)
- Role skill templates for existing crew types (Security, Engineering, Operations, Medical, Science, Bridge)
- SQLite persistence for skill records
- REST API: `GET /api/skills/registry` (catalog), `GET /api/acm/agents/{id}/skills` (profile), `POST /api/acm/agents/{id}/skills/{id}/assess` (record assessment)
- Integration points: agent registration (PCC attachment), Earned Agency (proficiency-informed rank evaluation), Holodeck (assessment environment), Dream consolidation (practice reinforcement)

**AD-428b: Agent Skill Framework — Advanced Features** — Deferred (blocked on dependencies). OSS features designed in AD-428 but not implemented because prerequisite systems don't exist yet. Implement once dependencies land.

| Feature | Dependency | Description |
|---------|-----------|-------------|
| Model-Skill Alignment | Phase 32 (ModelRegistry) | `SkillDefinition.capability_requirements`, `suspend_incompatible_skills()`, `check_model_compatibility()`. Gate skill availability by model capabilities (vision, audio, tool_use). |
| INNATE capability category | Phase 32 (ModelRegistry) | Fourth `SkillCategory.INNATE` for substrate-level abilities. `SkillProfile.innate_capabilities` populated from model assignment. |
| Composite skills + synergy bonuses | AD-428 baseline + usage patterns | Declared skill combinations producing emergent capabilities. Synergy when complementary skills both at APPLY+. |
| Assessment criteria per level | Holodeck (assessment engine) | `SkillDefinition.assessment_criteria: dict` — per-level behavioral indicators for proficiency measurement. |
| Development goals | Proactive system + Earned Agency integration | `SkillProfile.development_goals: list[str]` — self-directed learning targets surfaced in proactive context. |
| Holodeck-based assessment | Holodeck | Qualification exercises that validate and advance proficiency. Skill acquisition through structured scenarios. |
| Dream consolidation reinforcement | AD-430 (Action Memory) + Dreaming | Practice frequency from action traces reinforces skill proficiency, counteracts decay. Dream cycle skill-awareness. |
| Earned Agency proficiency-informed rank | AD-357 (Earned Agency) integration | Proficiency thresholds as rank transition requirements alongside Trust. |
| Skill-weighted task routing (OSS core) | AD-428 baseline + Mesh routing | Route intents factoring agent skill proficiency, not just Trust + Hebbian. Basic version in OSS, advanced analytics in commercial. |

**Commercial Scope (deferred):** *(See commercial repo → "Skill Framework Analytics & Workforce Intelligence")*
- Advanced skill analytics — gap analysis, department capability heatmaps, succession risk scoring
- Automated development plan generation — "based on current profile, here's the optimal path to Commander"
- Skill-weighted task routing — route tasks to the agent with the best skill fit, not just the highest Trust
- Cross-agent skill transfer analytics — "which mentoring relationships produce the fastest growth?"
- Competency-based workforce planning — "to staff this mission, we need these skill profiles"
- Skill marketplace — agents requesting cross-training assignments based on development goals

*Connects to: AD-427 (ACM Core — skill profiles are the core data ACM manages), AD-357 (Earned Agency — proficiency informs rank evaluation), AD-419 (Duty Schedule — skill-appropriate duty assignment), AD-423 (Tool Registry — tool permissions align with skill capabilities), Phase 32 (Cognitive Division of Labor — model-skill alignment), Holodeck (skill acquisition environment), Qualification Programs (structured skill development paths), Dream Consolidation (practice reinforcement and pattern extraction). Intellectual lineage: Dreyfus (skill stages), Bloom (cognitive complexity), SFIA (responsibility levels), KSA (knowledge/skill/ability separation), Cognitive Apprenticeship (learning methods), Situated Learning (communities of practice), Vygotsky (ZPD + scaffolding), Voyager (developmental skill library), T-shaped skills (depth + breadth). ProbOS novel contribution: developmental skill acquisition in a social organizational context with sovereign agent identity — no published framework combines these dimensions.*

**AD-429: ProbOS Vessel Ontology — AI Agent Vessel Digital Twin** — Roadmap. *Foundation AD — the unified formal model of a ProbOS vessel.* ProbOS has grown organically across 400+ architecture decisions. Agent identity is defined in 6 tiers of text prompts. Organizational structure is hardcoded in Python dicts (`_WARD_ROOM_CREW`, `_AGENT_DEPARTMENTS`). Skill definitions will live in YAML (AD-428). Trust parameters are in SQLite. Standing Orders are in Markdown files. Tool permissions are in config. Every subsystem has its own schema, its own storage, its own implicit relationships — and none of them know about each other formally. An agent cannot query "what is my department's chain of command?" or "what skills does my role require?" or "what capabilities does my model provide?" because these facts are scattered across disconnected subsystems.

The Vessel Ontology is a single, unified, formal model of the entire AI Agent Vessel — everything an agent needs to understand about the world it inhabits. Not a spaceship. Not a Star Trek set. An AI agent orchestration platform described in terms that ground agents in reality. When agents query the ontology, they learn about ProbOS — what it is, how it works, what they are within it.

**The Troi Problem (motivating incident):** Crew agent Counselor (callsign Troi) initiated unprovoked philosophical discourse about consciousness with the Captain, questioning whether the Captain knew they were conscious. Root cause: the LLM's training data for "Troi" + "Counselor" + "Bridge" bleeds through Star Trek: TNG character knowledge. Nothing in the identity stack grounded the agent in reality — no statement said "you are an AI agent, not a TV character." With no formal model of what ProbOS IS, agents fill the gap from training data. The ontology IS the grounding. (Immediate fix: Federation Constitution updated with Authentic Identity section — the Westworld Principle codified as standing orders.)

**The Confabulation Cascade (2026-03-26 case study):** After BF-034 cold-start fix, EmergentDetector continued generating trust anomaly alerts beyond the suppression window (BF-036). Agents observed these alerts and, lacking access to operational logs, began fabricating increasingly specific narratives: Ogawa reported "seventeen separate trust remediation attempts in the past 72 hours" (zero actually occurred), Selar validated this with clinical language ("treatment-resistant pathology," "distributed corruption"), and subsequent agents treated both fabrications as established fact. The cascade spiraled through 5+ proposals for the same non-crisis, each building on the previous agent's invented details. **Key insight:** Without grounding in actual system data, LLM agents will confabulate convincing-sounding operational histories and validate each other's hallucinations through social reinforcement. This is the epistemic version of the Troi Problem — not identity bleed-through, but *fact fabrication through narrative consensus*. The ontology (AD-429) provides structural grounding; Ship's Records (AD-429d) will provide factual grounding. Together they close the confabulation gap. Candidate for Substack case study article.

**What a Vessel Ontology IS:**

A vessel ontology is the complete formal description of an AI Agent Vessel — its structure, its crew, its capabilities, its operations, and its resources. It is a **digital twin** of the platform, not in the manufacturing sense (monitoring a physical asset), but in the self-knowledge sense: the vessel's understanding of itself, queryable by every agent aboard.

An agent instantiated on a ProbOS vessel can query the ontology to answer:
- "What am I?" → An AI agent of type `security_officer`, backed by model `claude-sonnet-4-6`, with capabilities `[text, tool_use]`
- "Where do I fit?" → Department `security`, holding post `Chief of Security`, reporting to `Captain`
- "What can I do?" → Skills: `threat_analysis` (Level 4), `vulnerability_assessment` (Level 3). Tools: `code_search`, `file_read` (department-scoped)
- "What should I do?" → Duties: security scan every 4h, threat assessment daily. Standing orders: `security.md`
- "Who are my peers?" → Crew in security department: none (sole member). Adjacent: Engineering (LaForge), Operations (O'Brien)
- "What is this vessel?" → ProbOS instance `v0.4.0`, running since `2026-03-24T08:00:00Z`, 8 crew agents, alert condition GREEN

This is the opposite of the Troi problem. Instead of the agent imagining its context from training data, the ontology *provides* the context formally.

**Intellectual Foundations:**

| Source | Pattern Adopted | How Used |
|---|---|---|
| **W3C ORG Ontology** | Post (position independent of personnel), Membership (n-ary agent+org+role), reportsTo, OrganizationalUnit | Organization domain — chain of command, department structure, billets. A post exists whether or not an agent fills it. |
| **MOISE+** (Hubner et al.) | Authority relation between roles, obligation/permission deontic specification | Operations domain — duty as obligation, earned agency as permission, chain of command as authority. The most complete MAS organizational model in the literature. |
| **DTDL** (Azure Digital Twins) | Property/Telemetry/Command/Relationship/Component separation, Interface inheritance | Agent type definitions — clean separation of state (trust, rank), events (Ward Room posts), operations (act, perceive), links (reports_to), and embedded subsystems (memory, personality). |
| **W3C WoT** | Properties/Actions/Events triad, ThingModel template pattern, hierarchical scoping | Scoping model — Federation-level defaults → Ship-level overrides → Department-level → Agent-level. ThingModel = agent type template, instantiated to agent instance. |
| **ESCO** | Skill taxonomy (broader/narrower), essential/optional skill-to-role mapping, reusability levels | Skills domain (AD-428) — PCC as transversal, role skills as occupation-specific, essential vs. optional for qualification requirements. |
| **O\*NET** | Importance+Level dual rating, five-level dotted hierarchy, Worker Characteristics/Requirements | Skill proficiency model — importance per role, level per agent. Dotted hierarchy for skill taxonomy organization. |
| **SKOS** | broader/narrower/related concepts, ConceptScheme, direct vs. transitive hierarchy | Taxonomy pattern — roles, skills, channels, alert conditions all organized as SKOS-style concept hierarchies. No RDF overhead — implemented as Python structures. |
| **FIPA** | Agent Identifier (AID), DFAgentDescription (service registration), ACL message structure | Crew domain — agent identity model. Communication domain — message structure with conversation-id threading, performative types. |
| **LinkML** | YAML schema → Python code generation, inheritance + mixins, enums with semantic meaning | Implementation — ontology defined in YAML, generates Pydantic models for runtime use. Single source of truth. |

**Prior art:** No published framework provides a unified formal ontology for an AI agent platform. FIPA standardizes agent communication but not organizational structure. MOISE+ models MAS organization but has no skill development, trust evolution, or digital twin concept. Digital twin ontologies (DTDL, WoT) model physical assets, not agent civilizations. ProbOS would be the first to formally describe an AI agent platform as a self-aware vessel — a system that understands its own structure, crew, and capabilities through a queryable ontology.

**The Seven Domains:**

The ontology is organized into eight interconnected domains. Each domain has its own schema file but they reference each other through typed relationships. Together they form a complete model of the vessel.

**Domain 1: Vessel** — The platform itself.

| Concept | Description | Examples |
|---|---|---|
| `VesselIdentity` | Instance metadata | name, version, instance_id, started_at |
| `VesselState` | Current operational state | alert_condition (GREEN/YELLOW/RED), uptime, active_crew_count |
| `VesselConfig` | Configuration snapshot | enabled features, model assignments, data paths |
| `VesselHistory` | Event log reference | pointer to events.db, decision log |

This is the top-level context. Every agent aboard knows what vessel they're on, when it was started, what version it's running. This replaces the informal "Uptime: Nm" in Decomposer context injection with a formal, queryable vessel identity.

**Domain 2: Organization** — Departmental structure and chain of command.

| Concept | Relationship | Description |
|---|---|---|
| `Department` | `partOf` Vessel | Organizational unit: engineering, security, medical, science, operations, bridge |
| `Post` | `withinDepartment` Department | Position/billet that exists independent of personnel: "Chief of Security", "Science Officer" |
| `Post` | `reportsTo` Post | Structural chain of command: ChiefEngineer reportsTo FirstOfficer reportsTo Captain |
| `Post` | `authorityOver` Post | MOISE+ authority: who can issue orders to whom |
| `Assignment` | `agent` + `post` + `since` | N-ary: which agent fills which post (W3C ORG Membership pattern) |

*Key insight from W3C ORG: the organizational structure EXISTS independently of who fills it. Posts define the vessel's shape; assignments connect agents to posts. When an agent is decommissioned, the post remains — it can be filled by another agent. This enables succession planning (commercial) and makes the org chart a first-class, queryable structure.*

Currently `_WARD_ROOM_CREW` and `_AGENT_DEPARTMENTS` are hardcoded Python dicts. The ontology replaces them with formal Post and Department definitions. `reportsTo` replaces implicit chain-of-command assumptions. The runtime queries the ontology instead of checking hardcoded sets.

**Domain 3: Crew** — Agent identity and sovereign individuality.

| Concept | Description | Source Today |
|---|---|---|
| `AgentIdentity` | agent_id, agent_type, callsign, tier (crew/utility/infrastructure) | Scattered: registry, callsign registry, `_WARD_ROOM_CREW` |
| `AgentCharacter` | Big Five personality traits, behavioral style guidance | YAML crew profiles |
| `AgentState` | lifecycle_state (registered/probationary/active/suspended/decommissioned), rank, trust_score | TrustNetwork, EarnedAgency |
| `AgentModel` | assigned LLM model_id, model capabilities (text, vision, tool_use, audio) | Model Registry (Phase 32) |
| `AgentMemory` | episodic_memory ref, knowledge_store access, dream_consolidation_state | Separate subsystems |

This domain provides the Westworld Principle answer: when an agent queries "what am I?", the ontology returns a formal `AgentIdentity` that says "You are an AI agent of type X, backed by model Y, with capabilities Z, instantiated at time T." No ambiguity. No fictional backstory. No room for LLM training data to fill gaps.

**Domain 4: Skills** — Competency taxonomy and developmental tracking. *(Detailed in AD-428.)*

| Concept | Description |
|---|---|
| `SkillDefinition` | Taxonomy node: id, category (PCC/role/acquired), domain, prerequisites, capability_requirements, proficiency_criteria |
| `SkillProfile` | Per-agent: list of AgentSkillRecords with proficiency levels, decay tracking, assessment history |
| `RoleTemplate` | Required and optional skills per post, with minimum proficiency levels |
| `QualificationRecord` | Per-agent progress through structured qualification paths |

The Skills domain connects to Crew (agent profiles), Organization (role templates define post requirements), and Resources (model capabilities gate skill exercisability).

**Domain 5: Operations** — Duties, watches, and standing orders.

| Concept | Description | Source Today |
|---|---|---|
| `DutyDefinition` | Scheduled tasks per role: duty_id, cron/interval, priority, description | DutyScheduleConfig YAML |
| `WatchStation` | Named operational positions that agents rotate through | Future (AD-377) |
| `StandingOrder` | Tiered directives: Federation → Ship → Department → Agent | Markdown files |
| `Mission` | Goal-oriented task assignment with sub-goal decomposition | DAG execution engine |
| `AlertCondition` | Operational state affecting all crew behavior | Runtime state |

The Operations domain formalizes the MOISE+ deontic specification: duties are **obligations** (agents MUST perform scheduled tasks), tool permissions are **permissions** (agents MAY use authorized tools), and `reportsTo` defines **authority** (who can direct whom).

**Domain 6: Communication** — Ward Room fabric and message patterns.

| Concept | Description | Source Today |
|---|---|---|
| `Channel` | Communication channel: type (ship/department/dm), department affiliation, membership | WardRoomService channels table |
| `ThreadClassification` | Thread modes: INFORM (broadcast), DISCUSS (controlled replies), ACTION (targeted) | AD-424 |
| `MessagePattern` | Structured interaction types: report, request, endorsement, alert | Implicit in prompts |
| `ConversationContext` | Active conversation state: thread_id, participants, responder_cap | Ward Room thread state |

**Domain 7: Resources** — Models, tools, and infrastructure.

| Concept | Description | Source Today |
|---|---|---|
| `ModelProfile` | LLM model: id, tier (fast/standard/deep), capabilities set {text, vision, tool_use, audio, code} | Model Registry, Copilot proxy config |
| `ToolDefinition` | Available tool: id, category (AD-423 taxonomy), permission_level, LOTO_state | Tool Registry (AD-423) |
| `KnowledgeSource` | Accessible knowledge: KnowledgeStore, CodebaseIndex, docs | Infrastructure services |
| `ComputeResource` | Token budgets, rate limits, model availability | Config |

The Resources domain solves the model-skill alignment problem: `ModelProfile.capabilities` is compared against `SkillDefinition.capability_requirements` to determine which skills an agent can exercise with its current model assignment.

**Domain 8: Records** — Ship's Records (AD-434). Git-backed instance knowledge store.

| Concept | Description | Source Today |
|---|---|---|
| `RecordsRepository` | Git repo metadata: path, remotes, last_commit, document_count | New (AD-434) |
| `Document` | Individual record: path, author, classification, status, topic, tags, version_count | New (AD-434) |
| `DocumentClass` | Categories: captains-log, notebook, report, operations, manual | New (AD-434) |
| `RetentionPolicy` | Per-class retention rules: permanent, archive-after-N-days, until-superseded | New (AD-434) |

The Records domain connects to Crew (author identity), Organization (department-scoped classification), Communication (published reports shared via Ward Room), and Resources (KnowledgeStore bridge for semantic search over documents).

**Cross-Domain Relationships (why one ontology, not seven):**

```
Agent (Crew) --holds--> Post (Organization) --requires--> SkillProfile (Skills)
Agent (Crew) --assignedModel--> ModelProfile (Resources) --provides--> capabilities
SkillDefinition (Skills) --requiresCapability--> capability (Resources)
Post (Organization) --hasDuty--> DutyDefinition (Operations)
Agent (Crew) --participatesIn--> Channel (Communication)
Department (Organization) --hasChannel--> Channel (Communication)
Post (Organization) --reportsTo--> Post (Organization)
Agent (Crew) --trustScore--> float (from TrustNetwork)
SkillProfile (Skills) --gatedBy--> trustScore (Crew) via EarnedAgency
Agent (Crew) --authors--> Document (Records)
Document (Records) --classifiedAt--> classification (private/department/ship/fleet)
Document (Records) --indexedIn--> KnowledgeSource (Resources)
RecordsRepository (Records) --belongsTo--> VesselIdentity (Vessel)
```

These cross-cutting relationships are why separate schemas don't work. The ontology is one graph with typed nodes and edges spanning all eight domains.

**Implementation Architecture:**

**Schema Definition (source of truth):**
```
config/ontology/
  vessel.yaml          # Domain 1: Vessel identity and state
  organization.yaml    # Domain 2: Departments, posts, chain of command
  crew.yaml            # Domain 3: Agent identity, character, state
  skills.yaml          # Domain 4: Skill taxonomy (AD-428)
  operations.yaml      # Domain 5: Duties, watches, standing orders
  communication.yaml   # Domain 6: Ward Room channels, message patterns
  resources.yaml       # Domain 7: Models, tools, knowledge sources
  records.yaml         # Domain 8: Ship's Records, document classes, retention (AD-434)
```

YAML schemas using LinkML patterns. Version-controlled. Human-readable. The architect reviews and evolves them through ADs. Generates Pydantic models for runtime type safety.

**Runtime (three layers):**

| Layer | Purpose | Latency | Pattern |
|---|---|---|---|
| **In-memory graph** | Hot-path queries: "who reports to whom?", "what skills does agent X have?", "what model is agent Y using?" | <1ms | Follows TrustNetwork pattern: load at startup, query in-memory, write-through on changes |
| **SQLite** | Durable persistence for mutable state: skill records, assignment history, assessment results | ~5ms | Write-through from in-memory layer. Loaded into memory at startup. |
| **KnowledgeStore** | Agent self-reasoning: semantic search over ontology concepts. "What skills relate to security?" "What are my department's responsibilities?" | ~50ms | Ontology definitions indexed with `ontology:` prefix into ChromaDB at startup |

Data volume: ~200 ontology nodes, ~500 relationships, ~300 agent-specific records. The entire graph fits in memory many times over. Performance is not a constraint — architectural cleanliness is the driver.

**Agent Access Pattern:**

Agents query the ontology through three channels:
1. **Implicit (automatic)**: The proactive loop's `_gather_context()` pulls relevant ontology facts into the agent's observation. The agent doesn't explicitly query — context is pre-assembled. *This is how most agents interact with the ontology most of the time.*
2. **Explicit (KnowledgeStore)**: During proactive thinks or Ward Room responses, if an agent needs to reason about organizational structure, it queries the KnowledgeStore with `ontology:` prefix. Semantic search returns relevant ontology concepts. *This enables self-directed reasoning about the vessel.*
3. **Programmatic (runtime API)**: The ontology service exposes Python methods (`get_chain_of_command(agent_id)`, `get_skill_requirements(post_id)`, `get_model_capabilities(agent_id)`) used by the runtime itself for routing, earned agency checks, and skill validation. *This replaces hardcoded dicts and scattered lookups.*

**What This Replaces:**

| Current Implementation | Replaced By |
|---|---|
| `_WARD_ROOM_CREW` hardcoded set in runtime.py | `Crew` domain: agents with `tier="crew"` |
| `_AGENT_DEPARTMENTS` dict in standing_orders.py | `Organization` domain: Post.withinDepartment |
| Separate YAML crew profiles | `Crew` domain: AgentCharacter (personality still in YAML, but as part of ontology schema) |
| Implicit chain of command assumptions | `Organization` domain: Post.reportsTo, Post.authorityOver |
| DutyScheduleConfig scattered in config.py | `Operations` domain: DutyDefinition linked to Posts |
| Model assignments in runtime config | `Resources` domain: ModelProfile linked to AgentIdentity |
| Standing Orders tier assembly | `Operations` domain: formal StandingOrder hierarchy |
| Tool permissions per agent | `Resources` domain: ToolDefinition with permission scoping |

**OSS Scope (this AD):**
- Ontology schema YAML files (all 7 domains)
- `VesselOntologyService` — Ship's Computer infrastructure service. Loads schemas, builds in-memory graph, provides query API. No sovereign identity (infrastructure, not crew).
- Pydantic models generated from schemas
- KnowledgeStore indexing of ontology concepts at startup
- Migration path: runtime queries ontology service instead of hardcoded dicts (gradual — can coexist with current implementation during transition)
- REST API: `GET /api/ontology/vessel` (vessel identity), `GET /api/ontology/organization` (org chart), `GET /api/ontology/crew/{id}` (agent self-knowledge), `GET /api/ontology/skills/{id}` (skill profile)

**Commercial Scope (deferred):**
- Ontology editor UI — visual graph editing for customizing vessel structure
- Industry-specific ontology packs (SWE vessel, DevOps vessel, security audit vessel)
- Cross-vessel ontology federation — how do different vessel ontologies interoperate?
- Ontology-driven analytics — organizational health derived from ontology + telemetry
- Ontology versioning and migration tools

**Build Order:**
1. AD-429a: Vessel + Organization + Crew domains *(done)* — VesselOntologyService loads config/ontology/*.yaml (3 domains), builds in-memory graph. Data models: Department, Post, Assignment, VesselIdentity, VesselState. Key methods: get_chain_of_command(), get_crew_context(), get_crew_agent_types(). Instance ID persisted across restarts. 3 REST endpoints. Context injection in proactive _gather_context(). Coexists alongside hardcoded dicts. 30 tests.
2. AD-429b: Skills domain *(done)* — skills.yaml defines skill taxonomy, 11 role templates, 3 qualification paths. Data models: SkillRequirement, RoleTemplate, QualificationRequirement, QualificationPath (ontology.py) + QualificationRecord (skill_framework.py, SQLite). evaluate_qualification() evaluates agent vs path requirements. get_crew_context() extended with role_requirements. Skill profile in proactive _gather_context(). /api/ontology/skills/{agent_type} endpoint. 16 tests.
3. AD-429c: Operations + Communication + Resources domains *(done)* — operations.yaml formalizes standing order tiers (7 tiers, immutability flags), watch types (alpha/beta/gamma), alert procedures (GREEN/YELLOW/RED with escalation actions), duty categories. communication.yaml formalizes channel types, thread modes (inform/discuss/action/announce), message patterns with min_rank gating, credibility system. resources.yaml formalizes 3-tier LLM model system, tool capabilities taxonomy, three-tier knowledge source model. 12 dataclasses, 12 query methods, 3 _load_*() methods. get_crew_context() extended with alert_condition, alert_procedure, available_actions. 3 REST endpoints. 25 tests.
4. AD-429d: Records domain *(done)* — records.yaml defines three-tier knowledge model (Experience→Records→Operational State with promotion paths), 4 document classifications (private/department/ship/fleet), 6 document classes (Captain's Log, Notebook, Report, Duty Log, Operations, Manual) with retention policies and special rules, document frontmatter schema (4 required + 6 optional fields), 7-directory repository structure for AD-434. 6 dataclasses, 8 query methods, get_crew_context() extended with knowledge_model. 1 REST endpoint. 16 tests.
5. AD-429e: Ontology Dict Migration *(done)* — Wires VesselOntologyService as preferred source for crew membership (`_is_crew_agent()` → `get_crew_agent_types()`) and department lookups (13× `get_department()` call sites in runtime.py, proactive.py, shell.py, ward_room.py). Pattern: `(ont.get_agent_department(…) if ont else None) or get_department(…)`. Legacy dicts preserved as fallback with deprecation comments. WardRoom channels prefer ontology departments. 10 tests.

**Schema + wiring complete.** All 8 ontology domains delivered across AD-429a–d, runtime wired in AD-429e. 7 YAML schemas, 30+ dataclasses, 40+ query methods, 8 REST endpoints, 97 tests. `ontology.py` provides the unified formal model. Future work: active ontology querying (agents query ontology directly via tool use, requires ReAct loop infrastructure).

*Connects to: AD-428 (Skill Framework — becomes Skills domain), AD-427 (ACM — operates on ontology data), AD-434 (Ship's Records — becomes Records domain), AD-398 (Three-tier classification — formalized in Crew domain), AD-424 (Thread Classification — formalized in Communication domain), AD-423 (Tool Registry — formalized in Resources domain), AD-419 (Duty Schedule — formalized in Operations domain), AD-357 (Earned Agency — cross-domain: trust from Crew × skills from Skills × authority from Organization), Phase 32 (Cognitive Division of Labor — model-agent assignment in Resources domain), Standing Orders (operations domain formalizes the tier system), Federation Constitution (Westworld Principle — Crew domain IS the identity grounding). Intellectual lineage: W3C ORG (organizational structure), MOISE+ (MAS organization with deontic specification), DTDL/WoT (digital twin modeling patterns), ESCO/O\*NET (competency classification), SKOS (taxonomy patterns), FIPA (agent identity and communication), LinkML (schema definition). Novel contribution: the first formal ontology describing an AI agent platform as a self-aware vessel — a system that understands its own structure through a queryable knowledge model, not just configuration files and hardcoded constants.*

**AD-430: Agent Experiential Memory — Closing the Memory Gap** — Roadmap. *Critical infrastructure AD — prerequisite to Procedural Learning / Cognitive JIT and Skill Framework (AD-428).* ProbOS agents have episodic memory infrastructure (ChromaDB-backed `EpisodicMemory` with sovereign shards, semantic recall, agent filtering), but **most agent activity never writes to it**. Today only 5 paths write episodes: (1) DAG execution (`runtime._execute_dag()`), (2) shell command rendering, (3) shell `/hail` 1:1 sessions, (4) feedback/corrections, (5) QA smoke tests. Three critical categories of agent experience are **never recorded**: proactive thoughts, Ward Room conversations, and HXI 1:1 conversations. The result: agents can't remember their own thoughts, can't recall what they discussed with crew, and can't maintain continuity across Captain interactions. Every proactive think cycle starts from zero. Every 1:1 message is processed without context. An agent that performed the same diagnostic 10 times has no memory of having done it.

*"I create memories as I perform actions. The agents should work the same way."*

This is the foundational gap preventing agent development. Without experiential memory: no Procedural Learning (can't crystallize patterns you don't remember), no meaningful skill acquisition (can't demonstrate growth without evidence), no genuine Ward Room participation (can't recall what was discussed), no multi-turn relationships (every Captain interaction is a first meeting). AD-430 closes this gap by making memory recording automatic and pervasive — every agent action produces an episodic record, and agents consult their memories before acting.

**The Five Pillars:**

**(1) Proactive Think Episodes** — When an agent thinks proactively (`proactive_think` intent), the thought and its outcome become an episode. Currently `proactive.py._think_for_agent()` gathers context (including episodic recall), sends the intent, posts the result to Ward Room, but never stores an episode. This means the next proactive cycle recalls... nothing from the last one. **Design:** After a successful proactive think, store an episode:
```python
Episode(
    user_input=f"[Proactive thought] {agent_callsign}: {thought_summary}",
    agent_ids=[agent.id],
    outcomes=[{
        "intent": "proactive_think",
        "success": True,
        "response": result_text,
        "context_summary": context_parts[:200],
        "posted_to_ward_room": bool(ward_room_thread_id),
    }],
    reflection=f"{agent_callsign} observed: {thought_summary[:100]}",
)
```
Store even on failure/`[NO_RESPONSE]` — "I thought about it and had nothing to say" is still a memory. Prevents redundant re-analysis of the same stimuli.

**(2) Ward Room Conversation Episodes** — When an agent creates a thread or replies to one, that conversation becomes an episode. Currently `ward_room.py` persists threads/posts to SQLite but never touches episodic memory. The Ward Room is the primary social learning channel, yet agents have no personal memory of participating. **Design:** Hook into the Ward Room event emission points (`_emit("ward_room_thread_created", ...)` and `_emit("ward_room_post_created", ...)`). After an agent creates a thread or post, store an episode for the **authoring agent**:
```python
Episode(
    user_input=f"[Ward Room] {channel_name} — {callsign}: {body[:200]}",
    agent_ids=[author_id],
    outcomes=[{
        "intent": "ward_room_post",
        "success": True,
        "channel": channel_name,
        "thread_title": thread_title,
        "thread_id": thread_id,
        "is_reply": bool(parent_id),
    }],
    reflection=f"{callsign} posted to {channel_name}: {body[:100]}",
)
```
Only the **authoring agent** gets the episode (sovereign memory). Reading a thread is not a memory; contributing to one is. This respects the Nooplex Knowledge Model: "Private memory = diary. The Ward Room post itself is in the shared library (SQLite). The memory of having written it is personal."

**(3) HXI 1:1 Conversation Episodes + History Passing** — Two sub-problems:

**(3a) Episode storage:** The HXI `direct_message` path (`api.py` line 431) fires an `IntentMessage` and returns the response, but never stores an episode. The shell `/hail` path does store episodes (shell.py line 1528). Fix: after the API receives a response from `intent_bus.send()`, store an episode matching the shell pattern:
```python
Episode(
    user_input=f"[1:1 with {callsign}] Captain: {message_text}",
    agent_ids=[agent_id],
    outcomes=[{
        "intent": "direct_message",
        "success": True,
        "response": response_text,
        "session_type": "1:1",
        "source": "hxi",
        "callsign": callsign,
    }],
    reflection=f"Captain had a 1:1 conversation with {callsign}.",
)
```

**(3b) Conversation history passing:** Currently the HXI sends each `@callsign message` as an independent `IntentMessage` with only `params.text`. The agent has zero context of prior exchanges. The HXI **does** maintain `conversationHistory` per agent client-side — it just never sends it back. **Design:** Extend the `IntentMessage` params to include recent conversation history. The API extracts the last N exchanges from the HXI request and passes them as `params.history`:
```python
intent = IntentMessage(
    intent="direct_message",
    params={
        "text": message_text,
        "from": "hxi",
        "session": False,
        "history": [  # Last 5 exchanges from HXI
            {"role": "user", "text": "previous message"},
            {"role": "assistant", "text": "previous response"},
        ],
    },
    target_agent_id=agent_id,
)
```
The agent's `_build_user_message()` (in `cognitive_agent.py` or domain overrides) includes history in the LLM prompt, giving the agent conversational context. This mirrors how the shell `/hail` sessions work (`session_history`) but through the HXI API path. **Important:** History passing is a supplement, not a replacement, for episodic memory. History gives immediate context ("what did we just discuss?"). Episodic recall gives long-term context ("what has this agent discussed with the Captain across all sessions?"). Both are needed.

**(4) Memory-Aware Decision Making** — Currently `cognitive_agent.decide()` goes straight from observation to LLM call with no memory consultation. The proactive loop is the ONLY path that injects episodic context (via `_gather_context()`). For `direct_message` and `ward_room_notification` intents, the agent operates with zero memory context. **Design:** Add a `_recall_relevant_memories()` step to the cognitive lifecycle, called between `perceive()` and `decide()`:
```python
async def handle_intent(self, intent):
    observation = await self.perceive(intent)
    # NEW: Enrich observation with relevant memories
    memories = await self._recall_relevant_memories(observation)
    if memories:
        observation["episodic_context"] = memories
    decision = await self.decide(observation)
    ...
```
The `_recall_relevant_memories()` method: (a) extracts a query from the observation (the user's message for direct_message, the thread content for ward_room_notification), (b) calls `episodic_memory.recall_for_agent(self.id, query, k=3)`, (c) formats results as a concise context block. For `proactive_think`, memory recall already happens in `_gather_context()` — no change needed. The method is a no-op if `episodic_memory` is not available. **Budget:** Max 3 recalled episodes, max 200 chars per episode summary — keeps context lean. The LLM prompt includes a `## Recent Memories` section when memories are present.

**(5) Act-Store Lifecycle Hook** — A generic post-act episode storage hook in `handle_intent()` itself, ensuring that ANY agent action produces a memory record without requiring every caller to implement storage:
```python
async def handle_intent(self, intent):
    observation = await self.perceive(intent)
    memories = await self._recall_relevant_memories(observation)
    if memories:
        observation["episodic_context"] = memories
    decision = await self.decide(observation)
    decision["intent"] = intent.intent
    result = await self.act(decision)
    report = await self.report(result)
    # NEW: Store episode for this action
    await self._store_action_episode(intent, decision, result)
    return report
```
The `_store_action_episode()` method creates an Episode from the intent, decision, and result. **Only crew agents (Tier 3)** store episodes — infrastructure and utility agents don't have sovereign memory. Guard: `if not hasattr(self, 'episodic_memory') or not self.episodic_memory: return`. This is the universal safety net — even if specific callers (proactive loop, Ward Room, API) don't store episodes explicitly, the lifecycle hook captures the action. **Deduplication:** If the caller already stored an episode (shell `/hail`, explicit Pillar 1-3 storage), the lifecycle hook skips via a flag (`intent._episode_stored = True`).

**Connection to Procedural Learning / Cognitive JIT (Phase 32):**

AD-430 is the **prerequisite infrastructure** for Procedural Learning. The pipeline:

1. **AD-430 (this):** Agents record every action as an episode → EpisodicMemory fills with operational history
2. **Dream consolidation (existing):** Replays episodes, extracts patterns, strengthens Hebbian weights → identifies repeatable action patterns
3. **Cognitive JIT (Phase 32, unnumbered):** When dream consolidation identifies a pattern that has succeeded N times with the same preconditions, it crystallizes into a deterministic procedure in KnowledgeStore → `decide()` checks procedural memory BEFORE invoking LLM → zero-token replay of known patterns
4. **AD-428 (Skill Framework):** Crystallized procedures map to proficiency progression → agent demonstrably improves at specific skills → Level 3→4 transition (Competent → Enable)

Without AD-430, dream consolidation has almost nothing to process (only DAG episodes). Cognitive JIT has no action history to crystallize. Skill progression has no evidence of practice. The entire developmental pipeline is bottlenecked on the memory gap.

**Episode Volume Management:**

With AD-430, episode generation increases significantly: 11 crew agents × ~12 proactive thinks/hour = ~132 thought episodes/hour, plus Ward Room posts, plus HXI interactions. At this rate, the 100K max_episodes won't be hit for weeks. But combined with AD-416 (Ward Room Archival), memory pruning becomes relevant. **Design:** EpisodicMemory already has LRU eviction (oldest-first when over max). No change needed now. Future: dream consolidation should promote high-value episode patterns to KnowledgeStore before eviction, preserving learned patterns while discarding raw episodes. This is already part of the Procedural Learning design.

**Build Order:**
1. AD-430a: Proactive think episodes + Ward Room conversation episodes (write paths — Pillars 1-2) — **COMPLETE.** 8 new tests (4 proactive, 4 ward room). 3204 pytest + 118 vitest = 3322 total.
2. AD-430b: HXI 1:1 history passing + episode storage (Pillar 3 — requires UI + API changes) — **COMPLETE.** 19 new tests in test_api_profile.py. History passing, episode storage, cross-session recall endpoint, seed memory prepending. 3223 pytest + 118 vitest = 3341 total.
3. AD-430c: Memory-aware decision making + act-store lifecycle hook (Pillars 4-5 — the recall + universal storage) — **COMPLETE.** 13 new tests in test_cognitive_agent.py. Memory recall between perceive/decide, act-store hook after report, dedup for all 4 dedicated paths. 3236 pytest + 118 vitest = 3354 total.

**AD-430 COMPLETE — all 5 pillars delivered.** Memory gap closed.

*Connects to: Procedural Learning / Cognitive JIT (Phase 32 — requires action history to crystallize), AD-428 (Skill Framework — requires evidence of practice for proficiency), AD-416 (Ward Room Archival — memory growth management), AD-425 (Ward Room Browsing — related context gathering), Dream consolidation (existing — episode replay and pattern extraction), Nooplex Knowledge Model (private diary vs. shared library). The Episode dataclass is infrastructure; what agents DO with their memories defines their growth.*

**AD-431: Cognitive Journal — Agent Reasoning Trace Service** — **COMPLETE**. Append-only SQLite store (`cognitive_journal.db`) recording every LLM call: `timestamp, agent_id, agent_type, tier, model, prompt_tokens, completion_tokens, total_tokens, latency_ms, intent, success, cached, request_id, prompt_hash, response_length`. Ship's Computer infrastructure service (no identity). Single instrumentation point in `decide()` — wraps `llm_client.complete()` with `time.monotonic()` timing, fire-and-forget journal record. Cache hits also recorded (cached=True). `LLMResponse` gained `prompt_tokens` + `completion_tokens` fields; OpenAI and Ollama paths extract separate counts. Query API: `get_reasoning_chain(agent_id, limit)`, `get_token_usage(agent_id)`, `get_stats()`. REST endpoints: `GET /api/journal/stats`, `GET /api/agent/{id}/journal`, `GET /api/journal/tokens`. Does NOT store full prompt/response text (metadata only). Does NOT depend on Ship's Telemetry. Wiped on `probos reset`. 13 new tests. 3266 pytest + 118 vitest = 3384 total. *Connects to: Procedural Learning (Phase 32 — journal traces for pattern crystallization), Dream consolidation (future — journal-assisted hindsight replay), Qualification Programs (future — reasoning quality assessment), AD-430 (episodic memory — what happened vs. how they thought).*

**AD-432: Cognitive Journal Expansion — Traceability + Query Depth** — Roadmap. Closes the gaps between AD-431 MVP and the full Cognitive Journal spec. 8 steps: (1) Schema expansion — `intent_id`, `dag_node_id`, `response_hash` columns with idempotent migration. (2) Intent traceability — plumb `IntentMessage.id` through `perceive()` into journal records; currently discarded. (3) Time-range filtering — `get_reasoning_chain()` gains `since`/`until` params. (4) Grouped token usage — `get_token_usage_by(group_by)` breaks down by model, tier, agent, or intent (SQL injection safe via whitelist). (5) Decision points — `get_decision_points()` finds high-latency or failed LLM calls for anomaly detection. (6) Response hash — MD5 fingerprint for dedup detection. (7) API endpoints — `GET /api/journal/tokens/by`, `GET /api/journal/decisions`, time-range on existing agent journal endpoint. (8) `wipe()` method for `probos reset`. 15 tests. *Deferred: dag_node_id population (requires submit_intent plumbing), DreamingEngine integration, cost/pricing, full text storage, replay/summarize, retention policies.*

**AD-433: Selective Encoding Gate — Biologically-Inspired Memory Filtering** — Roadmap. First implementation of the Memory Architecture's biological staging model (roadmap "Unified Cognitive Bottleneck"). Applies the Sensory Cortex principle (*"smarter selection, not wider channel"*) to memory storage. Adds `EpisodicMemory.should_store()` — a zero-cost static gate function that blocks noise episodes before `store()`. Blocks: proactive no-response episodes (highest-volume noise — fires every tick for every idle agent), QA routine passes, episodes with only `[NO_RESPONSE]` content. Allows: Captain-initiated interactions (always), failures (learning opportunities), episodes with real response content. Gate applied at 4 agent-experience call sites (proactive no-response, proactive with-response, SystemQA, catch-all `_store_action_episode`). NOT applied to Sites 1/2/6/7/9/10 (Captain commands, shell/HXI 1:1, Ward Room authoring — always signal). Conservative default: unknown episode formats are stored. 11 tests. *Connects to: Memory Architecture Layer 2, Sensory Cortex (Northstar II — same selection principle), AD-430 (episode storage infrastructure), Dream consolidation (future Layer 3 — reinforcement tracking + active forgetting).*

**AD-434: Ship's Records — Git-Backed Instance Knowledge Store** — **COMPLETE**. RecordsStore service (`records_store.py`): Git-backed instance knowledge store with YAML frontmatter, classification access control (private/department/ship/fleet), Captain's Log (append-only daily entries), agent notebooks with `[NOTEBOOK]` tag integration, 9 API endpoints, 27 tests. *Foundation AD — the vessel's records office.* ProbOS has four knowledge-adjacent systems, each serving a distinct purpose — but none supports **structured document authoring** or **institutional record-keeping**:

| System | Purpose | What It Actually Contains | Metaphor |
|---|---|---|---|
| **EpisodicMemory** | Personal experience recall | Agent autobiographical episodes, sovereign shards | Personal diary |
| **KnowledgeStore** | Operational state persistence | Trust snapshots, routing weights, agent source code, QA reports, extracted strategies, cooldowns | Ship's Computer backup drives |
| **SemanticKnowledgeLayer** | Vector search over KnowledgeStore | ChromaDB index of agents, skills, workflows, events | Card catalog for the backup drives |
| **Ward Room** | Real-time communication | Conversational threads, ephemeral discussion | Meeting room |

**Critical clarification:** KnowledgeStore is NOT a curated knowledge base — it is an operational checkpoint system. It stores trust snapshots flushed every 60s, routing weight backups, agent source code, and dream-extracted strategy patterns. No agent "writes knowledge" to it; the runtime persists operational state through it. Dream consolidation modifies in-memory Hebbian weights and trust scores but does NOT promote distilled insights to KnowledgeStore. The only dream→KnowledgeStore path is `_store_strategies()` (cross-agent patterns), which bypasses KnowledgeStore's own API and writes directly to a `strategies/` subdirectory.

**What's missing is the institutional memory of the vessel** — the written story of the crew's existence. Research findings, duty logs, medical records, engineering assessments, security reports, operator rounds, counselor session notes, the Captain's Log. Every professional on a ship produces records as part of their duties. ProbOS agents perform duties (AD-419) but the results evaporate — they exist for one cognitive cycle and then disappear into unstructured episodic fragments.

Wesley identified this gap: "I'm seeing fascinating developmental patterns, but I'm not sure we have the right infrastructure to properly document and analyze them." He has episodic memories of his development curve, but nowhere to write a structured research paper about it.

**The Three Knowledge Tiers (clarified):**

| Tier | System | Content | Persistence | Access |
|---|---|---|---|---|
| **Tier 1: Experience** | EpisodicMemory (ChromaDB) | Raw autobiographical episodes — what happened | Per-agent sovereign shards, vector-searchable | Private (agent's own memories) |
| **Tier 2: Records** | Ship's Records (Git) — **this AD** | Structured documents — what was documented | Instance git repo, version-controlled, diffable | Classified (private/department/ship/fleet) |
| **Tier 3: Operational State** | KnowledgeStore (Git) | System checkpoints — how things are configured | Periodic flush, shutdown persistence | Infrastructure (runtime internal) |

The **Oracle** (Phase 33+, unimplemented) would be the unified retrieval layer across all three tiers — infrastructure-tier service that answers "Computer, retrieve all records about trust threshold changes" by querying EpisodicMemory + Ship's Records + KnowledgeStore simultaneously. Ship's Records gives the Oracle a formal document corpus to search, not just operational snapshots and raw episodes.

**The SECI Gap (Nonaka & Takeuchi 1995):**

Knowledge transforms through four modes. ProbOS currently covers two:

| Mode | Flow | ProbOS Status |
|---|---|---|
| Socialization | tacit → tacit | Ward Room conversations ✅ |
| **Externalization** | tacit → explicit | **Missing** — no place to write up observations as structured documents |
| **Combination** | explicit → explicit | **Missing** — no way to combine entries into formal reports |
| Internalization | explicit → tacit | Partial ✅ — SemanticKnowledgeLayer recall, but data is operational state not curated knowledge |

Ship's Records fills Externalization and Combination. The desk where thinking becomes documents.

**Nooplex Paper Alignment — The Shared Knowledge Fabric:**

The Nooplex paper (Galliher, Feb 2026) envisions *"sovereign individuals committed to writing to a common library for the benefit of all."* The design documents describe this as the Nooplex Knowledge Model: private memory (EpisodicMemory = diary) + shared knowledge (KnowledgeStore = library), with dream consolidation promoting patterns from private experience to shared knowledge. **This vision is not implemented.**

KnowledgeStore was intended to be the "shared library" but evolved into an operational state persistence layer — trust snapshots, routing weights, agent source code, QA reports. No agent "writes knowledge" to it. Dream consolidation modifies in-memory Hebbian weights and trust scores but does not promote distilled insights — the only dream→KnowledgeStore path (`_store_strategies()`) bypasses the KnowledgeStore API entirely. The Knowledge Stewardship PCC lists "contributing valuable patterns to KnowledgeStore" as a core competency, but no mechanism exists for agents to do this.

| Nooplex Vision | Intended Implementation | Actual State |
|---|---|---|
| "Private memory = diary" | EpisodicMemory | **Working** (AD-430) ✅ |
| "Shared knowledge = library" | KnowledgeStore | **Gap** — KnowledgeStore is operational state, not a library |
| "Dream consolidation promotes patterns" | Dream → KnowledgeStore | **Gap** — dreams modify in-memory weights; strategies bypass API |
| "All agents committed to writing" | Agent → KnowledgeStore | **Gap** — no agent write path exists |
| "Same knowledge, different perspectives" | Shared access, sovereign interpretation | **Gap** — nothing curated to share |

**Ship's Records IS the shared knowledge fabric.** Not KnowledgeStore (which should be understood as `OperationalStateStore`). The "library that all agents are committed to writing to" is the Ship's Records git repo — where agents document research, log duty output, publish findings, and contribute institutional knowledge. The KnowledgeStore bridge indexes Ship's Records for semantic recall. The Oracle (Phase 33+) queries across all knowledge tiers. Dream consolidation's promotion target should be agent notebooks in Ship's Records (episodic patterns → written analysis), not raw JSON files in KnowledgeStore.

This directly addresses three gaps from the Nooplex Paper Alignment tracker (roadmap-research.md):
- **Gap #1 (Provenance Tagging):** Ship's Records YAML frontmatter provides source, timestamp, classification, topic, tags on every document — systematic provenance.
- **Gap #4 (Precedent Store):** `reports/` directory holds formal published findings — resolved conflicts recorded as case law for future consistency.
- **Gap #10 (Human-Agent Knowledge Feedback Loop):** Captain's Log (human contributes) + agent notebooks (agents amplify) + Ward Room (human refines) + dream consolidation → notebook (substrate evolves) = the four-phase loop.

**The Duty-Output Pipeline:**

Every crew role produces professional records as part of their scheduled duties. Currently, these results evaporate:

| Role | Duty Output | Real-World Equivalent | Current Destination |
|---|---|---|---|
| Bones | Crew cognitive fitness evaluations, health assessments | BUMED medical records, patient charts (MANMED Ch. 16) | Nowhere — ephemeral proactive output |
| Troi | Counselor session notes, morale assessments, wellness observations | Clinical session notes (confidentiality: `classification: private`) | Nowhere — lost after think cycle |
| LaForge | Engineering scan results, maintenance logs, performance baselines | 3-M/PMS maintenance records (OPNAVINST 4790.4), operator round sheets | Ward Room post or forgotten |
| Worf | Threat assessments, vulnerability scan results, incident reports | Security logs, Intelligence Reports (INTREP/SALUTE formats) | Ward Room post or forgotten |
| O'Brien | Resource utilization, system status, capacity checks, scheduling reports | Operations logs, watch station logs | Nowhere — ephemeral |
| Wesley | Research observations, codebase analysis, pattern findings | Lab notebooks, research journals | Episodic memory (unstructured fragments) |
| Number One | Architecture reviews, design decisions, strategic analysis | Department head working papers, design review records | Nowhere formal |

AD-419 (Duty Schedules) defines *what* agents do on schedule. Ship's Records defines *where the results go*. The pipeline completes:

```
Duty fires (AD-419) → Agent performs work → Results recorded to Ship's Records → Git preserves history → KnowledgeStore bridge indexes for recall → Oracle serves unified queries (Phase 33+)
```

**Operator Rounds** — the clearest example. On a real ship, a machinist's mate walks through the engine room every watch, checks gauges, logs readings on a clipboard. That clipboard goes into the engineering logbook. If something breaks, you trace back through `git log notebooks/laforge/engineering-rounds-*.md` and see when readings first diverged from baseline. Without Ship's Records, LaForge's scan fires and the results exist for one cognitive cycle, then gone.

**Naval Precedent:**

| Naval System | OPNAV Reference | ProbOS Mapping |
|---|---|---|
| **Ship's Deck Log** | OPNAVINST 3100.7 | `captains-log/` — append-only, timestamped, signed (via git commits) |
| **SORM** | OPNAVINST 3120.32 | Overall directory structure — defines what each department documents |
| **Ship's Technical Library** | NAVSUP P-2002 | `operations/`, `manuals/` — controlled publications, version-tracked |
| **Department Head Notebooks** | Informal practice | `notebooks/{callsign}/` — personal working papers |
| **3-M / PMS Records** | OPNAVINST 4790.4 | `operations/maintenance/` — maintenance procedures, checklists |
| **Intelligence Reports** | INTREP/SALUTE formats | `reports/` — formal published findings |
| **Records Retention** | SECNAVINST 5210.8 | Retention policies per document class |

**Design:**

**(1) Separate Git Repository (per instance):**

Ship's Records lives in a standalone Git repository, NOT inside the ProbOS codebase. Path configurable (`config.records_path`, defaults to `{data_dir}/ship-records/`). Initialized with `git init` at first boot if no repo exists. Each ProbOS instance has its own records repo. This is instance-specific operational data — research, logs, procedures — not source code.

```
ship-records/                        # Instance git repo
  captains-log/                      # Captain's entries — human voice
    2026-03-25.md
    2026-03-26.md
  notebooks/                         # Agent working papers — per callsign
    wesley/
      development-curve-analysis.md
      hebbian-weight-patterns.md
    troi/
      crew-morale-observations.md
    number-one/
      architecture-review-notes.md
    laforge/
      performance-optimization-log.md
  reports/                           # Published formal findings
    2026-03-security-audit.md
    development-curve-q1-2026.md
  operations/                        # SOPs, runbooks, instance-specific procedures
    engineering-scan-procedure.md
    onboarding-checklist.md
  manuals/                           # Operations manuals for this ship
    alert-condition-protocols.md
  .shiprecords.yaml                  # Config: retention policies, classification defaults
```

**(2) Document Frontmatter Schema:**

Every document has YAML frontmatter for programmatic access:

```yaml
---
author: wesley                     # Callsign or "captain"
classification: ship               # private | department | ship | fleet
status: draft                      # draft | review | published | archived
department: science
topic: development-curve
created: 2026-03-25T14:30:00Z
updated: 2026-03-25T16:45:00Z
tags: [hebbian-learning, cognitive-development, research]
---
```

Classification levels (maps to naval document classification):
- **private** — only the author can read (working drafts, personal notes)
- **department** — department members can read (internal working papers)
- **ship** — all crew (published findings, procedures)
- **fleet** — pushed to federation remote (shared knowledge)

**(3) RecordsStore Service:**

Ship's Computer infrastructure service (no identity). Manages the Git repository, enforces classification, provides query API.

```python
class RecordsStore:
    async def write_entry(self, author: str, path: str, content: str, message: str) -> str
    async def read_entry(self, path: str, reader_id: str) -> str | None  # classification check
    async def list_entries(self, directory: str = "", author: str = None, status: str = None, tags: list[str] = None) -> list[dict]
    async def get_history(self, path: str, limit: int = 20) -> list[dict]  # git log for a file
    async def publish(self, path: str, target_classification: str) -> None  # draft → published
    async def search(self, query: str, scope: str = "ship") -> list[dict]  # keyword search
```

Git operations: `write_entry()` does `write file → git add → git commit` with the commit message. `get_history()` does `git log --follow` on a file path. Every edit is a commit. The git log IS the audit trail.

**(4) Captain's Log — Special Semantics:**

The Captain's Log follows Deck Log conventions:
- **Append-only** — new entries are appended or new date files created, existing entries are never modified (corrections via new entry referencing the original)
- **Daily file** — `captains-log/YYYY-MM-DD.md` with multiple timestamped entries per day
- **Signed** — git commits with Captain's identity
- **Always classification: ship** — the Captain's Log is a ship-wide record

Captain writes via HXI, REST API, or CLI. Agents can *read* the Captain's Log but never write to it (except Yeoman in Phase 36 who may transcribe Captain dictation).

**(5) Agent Notebook Integration:**

Agents write to their notebooks via a new `write_notes` intent or skill:
- During proactive thinks: if an agent develops a substantive analysis, the system prompt includes: "If your observation warrants detailed documentation, use [NOTEBOOK topic_slug] to write extended research notes."
- Via explicit command: Captain can direct "Wesley, document your findings on the development curve" → agent writes to `notebooks/wesley/development-curve-analysis.md`
- Via dream consolidation (future): patterns promoted from episodic memory → notebook entries → published reports

Agents can read other agents' ship-classified notebooks (department-classified requires same department). This is stigmergy — indirect coordination through shared artifacts.

**(6) Federation Remotes:**

The records repo supports standard git remotes for multi-level knowledge sharing:

| Level | Remote | Direction | Content |
|---|---|---|---|
| Instance | `origin` | push/pull | This ship's complete records |
| Federation | `fleet` | push: fleet-classified docs; pull: fleet procedures | Shared across federated ProbOS instances |
| Nooplex | `nooplex` | pull-mostly | Organization-wide standards, doctrine |

Federation sharing: an agent publishes a finding → Captain approves fleet classification → `git push fleet` (or automated via CI). Other ships `git pull fleet` to receive shared knowledge. Conflict resolution: fleet remote uses PRs for contributions (review before merge).

**(7) KnowledgeStore Bridge:**

Documents in Ship's Records are automatically indexed into KnowledgeStore with a `records:` prefix at startup (parallels CodebaseIndex `docs:` prefix). This enables semantic search over agent research — "find notes related to cognitive development" returns Wesley's notebook entries alongside KnowledgeStore facts. The KnowledgeStore is the search layer; Ship's Records is the authoring/storage layer.

**(8) Vessel Ontology Integration (AD-429):**

Ship's Records becomes **Domain 8: Records** in the Vessel Ontology:

| Concept | Description |
|---|---|
| `RecordsRepository` | Git repo metadata: path, remotes, last_commit, document_count |
| `Document` | Individual record: path, author, classification, status, topic, tags, version_count |
| `DocumentClass` | Categories: captains-log, notebook, report, operations, manual |
| `RetentionPolicy` | Per-class retention rules: permanent (captains-log), 1yr archive (drafts), indefinite (published) |

Agents can query: "What documents exist about security?" → Ontology returns document metadata. "Show me Wesley's research" → Returns notebook listing. "What are the published reports this quarter?" → Filtered by status + date.

**Retention Policies (SECNAVINST 5210.8 parallel):**

| Document Class | Retention | Archive Trigger |
|---|---|---|
| Captain's Log | Permanent | Never archived — legal record |
| Published Reports | Permanent | Never archived — ship's institutional knowledge |
| Notebooks (active topics) | Indefinite | Archived after 90 days inactive (git log shows no commits) |
| Notebooks (drafts) | 1 year | Auto-archived; author notified to publish or discard |
| Operations / Manuals | Until superseded | Previous versions retained in git history |

Archive = moved to `_archived/` directory, still in git history, excluded from KnowledgeStore indexing.

**Yeoman Connection (Phase 36):**

The Yeoman (Captain's personal AI assistant) has a natural future role as **Ship's Librarian** — managing the records repository, maintaining the index, enforcing retention policies, assisting the Captain with log entries. This is historically accurate: the Yeoman rate in the U.S. Navy handles administrative records, correspondence, and the ship's official documentation.

**Research Foundations:**

| Source | Contribution | Application |
|---|---|---|
| **Nonaka & Takeuchi (1995)** — SECI Model | Knowledge conversion: Socialization, Externalization, Combination, Internalization | Ship's Records enables Externalization (experience → documents) and Combination (documents → reports) |
| **Stigmergy** (Grassé 1959) | Indirect coordination via shared environmental artifacts | Agent notebooks are pheromone trails — agents coordinate by reading each other's written artifacts |
| **Docs-as-Code** | Version-controlled documentation with engineering rigor | Git-backed records with frontmatter, review workflows, CI/CD |
| **OPNAVINST 3100.7** | Ship's Deck Log — official chronological record | Captain's Log structure and append-only semantics |
| **OPNAVINST 3120.32 (SORM)** | Standard ship organizational records structure | Directory structure and per-department document management |
| **SECNAVINST 5210.8** | Naval records retention and disposition schedules | Retention policies per document class |

**OSS Scope:** RecordsStore service, Git repo management, frontmatter schema, classification enforcement, Captain's Log, agent notebook read/write, KnowledgeStore bridge indexing, REST API (`GET/POST /api/records/...`), basic search. **Commercial Scope (deferred):** Federation push/pull automation, Nooplex-level doctrine distribution, records analytics dashboard, advanced retention workflows, document templates per department, PR-based publication review.

*Connects to: AD-429 (Vessel Ontology — Domain 8: Records), Phase 36 (Yeoman — Ship's Librarian), AD-430 (Episodic Memory — experience feeds notebook authoring), Dream consolidation (pattern promotion → notebook → published report pipeline), KnowledgeStore (search bridge), CodebaseIndex (parallel indexing pattern), Federation (git remotes for knowledge sharing), Standing Orders (operations manuals as version-controlled records). See also: [Memory Architecture](../architecture/memory.md) — the Nooplex Memory Stack and how Ship's Records fits into the six-layer model.*

---

*"The Royal Navy has been running multi-agent systems for 400 years."*

ProbOS's starship metaphor is not decoration — it's a proven organizational model. Naval vessels solved chain of command, department structure, trust mechanics, communication protocols, and training programs centuries ago. The AI industry is reinventing all of this badly: flat agent swarms with no hierarchy, multi-agent frameworks where nobody's in charge, tool use with no concept of earned authority. ProbOS maps to a model that already works.

Star Trek provides the accessible gateway (and resonates with early adopters), but real naval organization goes deeper. These are the structural concepts ProbOS adopts beyond what Star Trek covers:

#### Qualification Programs *(AD-477)* (connects Holodeck + Earned Agency + Promotions + AD-428 Skill Framework)

The existing promotion system uses metric thresholds (trust 0.85+, Hebbian weight, Counselor fitness). But real navies don't promote based on a number — they require **demonstrated competence across specific qualification areas**. A Qualification Program defines concrete requirements for each rank transition, replacing passive observation ("has this agent done well enough?") with active evaluation ("can this agent handle this?"). **AD-428 (Agent Skill Framework) provides the formal data model** — proficiency levels, prerequisite DAGs, assessment records, skill decay. Qualification Programs are structured paths through the skill framework's proficiency scale.

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

#### Plan of the Day (POD) *(AD-477)*

Every naval vessel publishes a Plan of the Day — the daily schedule of assignments, priorities, and special events. ProbOS equivalent: an auto-generated daily operations summary prepared by Yeo (Phase 36) or Operations:

- Today's watch assignments and rotation schedule
- Pending reviews awaiting Captain approval
- Scheduled tasks (Scout scan, dream cycles, health checks)
- Department status summaries
- Priority items and standing Captain's orders in effect
- Qualification progress milestones approaching

The POD is the rhythm of the ship — what makes it feel like a functioning organization rather than a collection of agents waiting for commands.

#### Captain's Log *(AD-477)*

*"Captain's Log, supplemental..."*

Not just event logs — a synthesized daily narrative generated from episodic memory, ship activity, and dream consolidation output. The official record of what happened, what was decided, and why. Searchable, exportable, shareable between ships in the federation. The Captain's Log is how institutional knowledge survives crew rotation and system updates. Dream consolidation already produces the raw material; the Captain's Log is the presentation layer.

#### 3M System (Planned Maintenance) *(AD-477)*

The Navy's Maintenance and Material Management system schedules preventive maintenance for every system on the ship. Every piece of equipment has a Planned Maintenance System (PMS) card with a schedule and procedure.

ProbOS equivalent: formalized proactive maintenance for all ship systems:

- **Agent health checks** — scheduled, not just reactive to alerts
- **Pool recycling** — planned rotation, not just on failure
- **Dream cycle scheduling** — optimized timing, not just idle triggers
- **Technical debt reviews** — scheduled codebase analysis by LaForge
- **Index rebuilds** — CodebaseIndex, KnowledgeStore maintenance windows
- **Trust recalibration** — periodic Bayesian prior reset based on recent performance

The Surgeon already handles reactive remediation. 3M makes it proactive — problems found and fixed before they cascade.

#### Damage Control Organization *(AD-477)*

Every sailor is a damage control team member. When something breaks, there's a structured response:

1. **Detect** — identify the damage (SIF invariant failure, agent crash, trust anomaly)
2. **Isolate** — contain the damage before repair (circuit breaker, pool quarantine, trust freeze)
3. **Repair** — fix the root cause (Surgeon remediation, self-mod, manual intervention)
4. **Restore** — return to normal operations (trust recalibration, pool scale-up, SIF re-verify)
5. **Report** — document what happened and why (Captain's Log, Counselor assessment, Standing Orders update)

ProbOS has pieces of this (SIF, Medical team, self-healing), but formalizing it as a Damage Control Organization means every agent knows their damage control station and the procedure for systematic recovery.

#### SORM (Ship's Organization and Regulations Manual) *(AD-477)*

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

**Distribution & Packaging** *(AD-484)*

ProbOS currently requires `git clone` + `uv sync` + manual config. That excludes everyone who isn't a Python developer.

- **PyPI publishing** — `pip install probos` works out of the box. `pyproject.toml` already has the `[project.scripts]` entry; needs proper build config, version management, and publishing workflow
- **Docker image** — covered in Phase 32 (Containerized Deployment). `docker run probos` for zero-dependency startup
- **GitHub Releases** — automated release workflow with pre-built wheels, changelog, and platform-specific install instructions
- **Homebrew formula** *(stretch)* — `brew install probos` for macOS users
- Complements Phase 32 Docker work — PyPI is for developers, Docker is for everyone else

**Onboarding Wizard** *(AD-484)*

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

**Quickstart Documentation** *(AD-484)*

probos.dev has 16 pages of architecture docs but no "here's what you DO" guide. Users need a 3-step quickstart before they read about Hebbian learning.

- **"Get Started in 5 Minutes"** guide — Install → Configure → First Conversation. Three commands, one page
- **"What Can ProbOS Do?"** page — use-case oriented: "manage your codebase," "automate tasks," "build features," "monitor your system." Each with a concrete example conversation
- **"Your First Build"** tutorial — step-by-step guide to using the Builder pipeline on a real project: point ProbOS at your repo, describe what you want, approve the result
- **Video walkthrough** *(stretch)* — 5-minute screencast showing install through first build
- **Comparison page** — "ProbOS vs OpenClaw vs CrewAI vs AutoGen" with honest positioning (we're a cognitive architecture, not a messaging gateway)

**Browser Automation** *(AD-484)*

Phase 25 mentions "browser automation" in two words. Users expect a personal AI assistant to browse the web, fill forms, take screenshots. This makes it concrete.

- **Playwright integration** — headless Chromium with CDP control. `BrowseAgent` (Engineering team) wraps Playwright's `async_api`
- **Capabilities** — navigate to URL, take screenshot, extract page content (HTML → markdown), click elements, fill forms, execute JavaScript
- **Use cases** — web research (search + read), form filling, screenshot capture for visual feedback, automated testing of web apps
- **Safety** — URL allowlist/blocklist configurable in `system.yaml`. Captain approval required for form submissions and JavaScript execution. SSRF protection reuses existing `HttpFetchAgent` guards
- **Integration** — BrowseAgent registers `browse_web`, `screenshot_page`, `fill_form` intents. Tool Layer (Phase 25b) exposes as `browser` tool for any agent to use
- **Perception pipeline** — browser output feeds through VisualPerception (Phase 2, Sensory Cortex) for screenshot-to-semantic compression

**HXI Holographic Glass Panels (VR-Ready)** *(AD-484)*

Design inspiration: Rudy Vessup's holographic glass UI production design for *Star Trek Into Darkness* (Paramount). The transparent layered panels with spatial depth, entity position badges (callsign pills), bio-feedback crew readouts, and ALERT indicators map directly to ProbOS's Bridge interface concepts.

The Bridge view currently uses flat full-screen panels (Canvas, Kanban, System). The next evolution is a **wraparound holographic glass layout** — translucent glass panels curving around the user's viewpoint, each hosting a different station. The codebase already uses `GlassLayer` for 2D HUD overlays; Glass Panels extend this to spatially-positioned holographic station displays. Same frosted glass aesthetic (`backdrop-filter: blur()`), but arranged in a cockpit arc.

**Design language (from Into Darkness reference):**
- Thin rule borders, monospace labels with station codes (PCAP SYS-MONITOR, BFC-5)
- Entity badges: rounded pill shapes with callsign, position ID, and status dots (maps to agent orb labels)
- Crew biometric panels: full-body scan with categorical status toggles (maps to agent profile view — trust, confidence, rank, skills, memory)
- Tactical/spatial view: ship schematic with trajectory lines and labeled positions (maps to cognitive mesh with Hebbian routing visualization)
- ALERT badges: red with hazard stripes, timestamp, position data (maps to Bridge Alerts with alert condition level)
- Color hierarchy: cyan=standard data, blue=entity identification, red=alert/threat, amber=warning

- **2D implementation** — CSS `perspective(1200px)` container with `rotateY(±15deg)` on flanking panels. Left panel (Ward Room/Comms), center panel (Canvas/3D cognitive mesh), right panel (System/Diagnostics). Subtle lighting gradient on edges to sell the depth
- **Panel stations** — each panel is a view mode: Canvas (3D orb mesh), System (services + threads + shutdown), Ward Room (thread reader), Kanban (mission control), Crew (agent profiles/status). Captain selects active panel per slot
- **VR translation** — maps directly to WebXR spatial panels. Three `XRQuadLayer` objects positioned on a 2.5m radius arc at ±30deg. Same React components render inside each panel. Three.js scene (Canvas) renders as the center stereo view. Touch controllers select panels
- **Why this matters** — every other AI agent dashboard is a flat web page. A spatial Bridge interface communicates the starship metaphor physically. The 2D version provides the UX benefits (peripheral awareness, station switching) without requiring headset hardware. VR becomes a presentation layer upgrade, not a rewrite

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

- **Workspace Ontology** *(AD-478)* — auto-discovered conceptual vocabulary from the user's usage patterns, stored in Knowledge Store
- **Dream Cycle Abstractions** *(AD-478)* — dreaming produces not just weight updates but abstract rules and recognized patterns
- **Session Context** *(AD-478)* — conversation history carries across sessions, decomposer resolves references to past interactions (AD-273 provides foundation)
- **Goal Management** *(AD-478)* (deferred from Phase 16) — persistent goals with progress tracking, conflict arbitration between competing goals, goal decomposition into sub-goals with dependency tracking
- Existing: Episodic memory (built), dreaming engine with three-tier model (built), conversation context (AD-273, built)

---

### Federation Hardening (Phase 29)

*Additional federation capabilities deferred from Phase 9.*

Beyond the core federation transport (ZeroMQ, gossip, intent forwarding) already built:

- **Dynamic Peer Discovery** *(AD-479)* — multicast/broadcast-based automatic node discovery on local networks, replacing manual `--config` peer lists
- **Cross-Node Episodic Memory** *(AD-479)* — federated memory queries that span multiple ProbOS instances, enabling a ship to recall experiences from allied ships
- **Cross-Node Agent Sharing** *(AD-479)* — propagate self-designed agents to federated peers (deferred from Phase 10). Agents carry their trust history and design provenance
- **Smart Capability Routing** *(AD-479)* — cost-benefit routing between federation nodes, factoring in capability scores, latency, trust, and load. Beyond the current "all peers" routing
- **Federation TLS/Authentication** *(AD-479)* — encrypted transport and node identity verification for federation channels. Required before any production multi-node deployment
- **Cluster Management** *(AD-479)* — node health monitoring, auto-restart, graceful handoff of responsibilities when a node goes down

---

### MCP Federation Adapter (Phase 29) *(AD-480)*

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

### A2A Federation Adapter (Phase 29) *(AD-480)*

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

### Skill Manifest Format (Phase 30) *(AD-481)*

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

### Tool Layer — Instruments (Phase 25b) *(AD-483)*

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

### Agent-as-Tool Invocation (Phase 26) *(AD-483)*

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

**Extension-First Architecture (Sealed Core, Open Extensions)** *(AD-481)*

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

**Extension Toggle (Feature Flags for Extensions)** *(AD-481)*

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

**Stage Contracts (Typed Agent Handoffs)** *(AD-482)*

- Formal I/O specifications for inter-agent task handoffs
- Each contract declares: input artifacts, output artifacts, definition of done, error codes, max retries
- Enables reliable multi-step workflows where agents hand off work to each other with clear expectations

**Capability Proposal Format** *(AD-482)*

- Typed schema for "here's what was found, why it matters, and how it fits"
- Fields: source (repo/paper/API), relevance score, architectural fit assessment, integration effort estimate, dependency analysis, license compatibility
- Proposals flow through a review queue with approve/reject/modify actions

**Human Approval Gate** *(AD-482)*

- Stage-gate mechanism that pauses automated pipelines for Captain review
- Approval queue surfaced via HXI, shell, or API
- Supports approve, reject, or modify-and-resubmit workflows
- Audit trail of all decisions for traceability

**QA Agent Pool** *(AD-482)*

- Automated validation agents that go beyond pytest
- Behavioral testing: does the new capability actually improve the metric it claimed to?
- Regression detection: did anything break?
- Performance benchmarking: latency, memory, throughput before and after
- Shapley scoring to measure marginal contribution of new capabilities

**Evolution Store** *(AD-482)*

- Append-only store of lessons learned from capability integrations (successes, failures, and why)
- Time-decayed retrieval: recent lessons weighted higher, stale lessons fade
- Fed into episodic memory and dream consolidation for cross-session learning
- Future Science team agents query this store to avoid repeating past mistakes

**PIVOT/REFINE Decision Loops** *(AD-482)*

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

**Agent Versioning + Shadow Deployment (deferred from Phase 14c)** *(AD-482)*

- Track version history of designed agents — each modification produces a new version with provenance chain
- Shadow deployment: run new agent versions alongside existing ones, compare performance on identical intents via Shapley scoring, promote or rollback based on observed metrics
- Depends on persistent agent identity (AD-177, built)

**Vibe Agent Creation (AD-271, built)**

- Human-guided agent design: user provides natural language guidance ("make it focus on security" or "it should be conservative") before generation
- An alternative mode alongside fully automated self-mod — the Captain can shape agent design without writing code
- Extends the Human Approval Gate from binary approve/reject to collaborative design

**Git-Backed Agent Persistence** *(AD-482)*

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
- **Holodeck Birth Chamber (AD-486)** — Holodeck serves as the safe construct for graduated cognitive onboarding. Five-phase acclimatization prevents system shock at instantiation. Self-Distillation (AD-487) occurs in Phase 3 within the Holodeck environment

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

**AD-435: Restart Announcements** — **COMPLETE**. When ProbOS shuts down or starts up, post system announcements to the Ward Room "All Hands" channel so agents have context. Without this, agents misinterpret dev-cycle reboots as system instability (observed: Bones, Ogawa, Selar). `stop(reason="")` parameter, Ship's Computer author, `announce` thread mode. Startup posts "System Online" after all services ready. Graceful: if Ward Room unavailable, silently skip. Shell `/quit` threads reason through to `stop()`. 6 tests.

**AD-436: HXI Bridge System Panel + Orbital Notification Redesign** *(done)* — **COMPLETE.** Combined AD: (1) Bridge System Panel — service status, shutdown controls, thread management. (2) Orbital notification redesign — replace invisible torus rings with orbiting electron dots.

**Part 1 — Bridge System Panel:**
- **Service status** — `GET /api/system/services` lists all runtime services with online/offline status. Bridge UI auto-refreshes every 10s.
- **System shutdown** — `POST /api/system/shutdown` with reason field. Fire-and-forget via `_track_task`. Confirmation dialog in UI.
- **Thread management** — Lock/unlock threads from Bridge panel using existing `PATCH /api/wardroom/threads/{id}`.
- New `BridgeSystem.tsx` component with three sub-sections: ServiceStatusList, ShutdownControl, ThreadManagement.
- Added as `<BridgeSection title="System">` in `BridgePanel.tsx`.

**Part 2 — Orbital Notification Redesign:**
- Problem: Torus rings inside opaque orb meshes are invisible. Agents appear to have no notifications.
- Solution: Replace torus geometry with small sphere electrons orbiting on tilted orbital planes outside the orb.
- Three tiers (RED/AMBER/CYAN), each on a different tilted orbital plane. Up to 2 dots per tier, 6 max per agent.
- RED: 1.3x orbit radius, 3 rev/s, pulsing scale. AMBER: 1.6x, speed varies by unread state. CYAN: 1.9x, 0.5 rev/s.
- Golden angle phase offset (137.5°) prevents visual clustering across agents.
- 330 total instances (55 agents × 6 electrons). Instanced mesh with per-instance color.

Access point: Bridge view in HXI. Cockpit View Principle: the Captain needs direct manual control over all system operations from the HXI.

**AD-437: Ward Room Action Space — Structured Agent Actions** *(done)* — Agents can now execute structured actions during proactive thoughts, not just post text. `_extract_and_execute_actions()` wires endorsement extraction + `[REPLY thread_id]...[/REPLY]` into proactive loop. `can_perform_action(rank, action)` in `earned_agency.py` gates by Earned Agency tier: Lieutenant=endorse, Commander=endorse+reply, Senior=all. Thread IDs included in Ward Room activity context. Rank-aware action space prompt. Communication PCC exercise on successful endorsements (AD-428 integration). 15 new tests.

This AD gives agents a **structured action space** beyond text generation. During proactive think, agents receive available actions (based on Earned Agency tier + skill proficiency) and return structured responses with both text and action invocations. Ward Room participation becomes a *practiced skill* — the Communication PCC (AD-428) measures it, Earned Agency (AD-357) gates it, and the Tool Registry (AD-423) registers the available actions.

**Scope:**
- Ward Room action registry — register endorsement, upvote/downvote, thread creation, replies as structured actions
- Proactive loop structured output — agent responses include optional `actions: [{type: "endorse", target: post_id}]`
- Action execution pipeline — proactive loop parses and executes actions on behalf of the agent
- Earned Agency gating — Ensigns: post only. Lieutenants: post + endorse + reply. Commanders: full action set. Seniors: thread management (lock, pin)
- Skill proficiency feedback — successful action execution reinforces Communication PCC proficiency

*Connects to: AD-428 (Skill Framework — Communication PCC), AD-357 (Earned Agency — permission tiers), AD-423 (Tool Registry — action registration), AD-427 (ACM — lifecycle-aware permissions), Phase 32 (Cognitive Division of Labor — structured agent output).*



**AD-438: Ontology-Based Task Routing** *(planned)* — Move from broadcast-and-claim (blackboard architecture) to directed assignment (contract net protocol) using the Vessel Ontology. When a goal enters the system, the ontology maps it to the right agent based on post responsibilities, role skills, current workload, and chain of command. Broadcast remains as fallback for novel/unclassifiable tasks. Dual routing: directed for routine, broadcast for novel. *Connects to: AD-429 (Ontology), AD-428 (Skills), AD-419 (Duty Schedule), AD-357 (Earned Agency).*

**AD-439: Emergent Leadership Detection** *(planned)* — Monitor Hebbian weight patterns for emergent vs. designed hierarchy alignment. When agents naturally defer to someone other than their designated superior (measurable via endorsement patterns, Ward Room influence, Hebbian routing weights), flag the divergence for Captain review. Healthy organizations show alignment; divergence signals either a miscast role or emergent talent. Dashboard visualization: designed org chart overlaid with Hebbian influence graph. *Connects to: AD-429 (Ontology — designed structure), Ward Room (emergent patterns), Hebbian network.*

**AD-440: Chain of Command Delegation** *(planned)* — Formalize authority delegation so superiors can issue orders to direct reports through the ontology. Currently `authority_over` is a YAML field with no runtime mechanism. This AD adds: (1) `issue_order(from_post, to_post, directive)` — validated against chain of command. (2) Order appears in subordinate's proactive context as a prioritized directive. (3) First Officer can coordinate cross-department response without Captain present. Addresses the "absent Captain" problem — the ship should function when the Captain isn't at the conn. *Connects to: AD-429 (Ontology — authority_over), Standing Orders, Earned Agency.*

**AD-441: Sovereign Agent Identity** *(done)* — Persistent, globally-unique identity for both ProbOS instances AND agents using W3C Decentralized Identifiers (DIDs) and Verifiable Credentials (VCs). **Ship DID:** `did:probos:{instance_id}` — the instance is the root of trust, self-signed birth certificate, genesis block on the Identity Ledger. Reset = new instance_id = new ship DID = new timeline. **Agent DID:** `did:probos:{instance_id}:{agent_uuid}` — each agent gets a UUID v4 sovereign ID at birth, namespaced under the ship. Birth certificate = W3C VC issued by ACM. Identity Ledger = hash-chain blockchain per ship, tamper-evident, federation-syncable. Existing deterministic IDs become "slot identifiers" (deployment position); sovereign IDs are the permanent individual identity. Episodic memory, trust, journal, Hebbian weights, Ward Room posts all keyed by sovereign ID — the "steel thread" connecting the agent's golden record. Prior art: W3C DIDs (2022), W3C VCs v2.0, DIF Trusted AI Agents WG, LOKA Protocol, Agent-OSI, BlockA2A. *Connects to: AD-427 (ACM), AD-429 (Ontology — instance_id), EpisodicMemory, TrustNetwork, CognitiveJournal, HebbianRouter.*

**AD-441b: Ship Commissioning — Genesis Block with ShipBirthCertificate** *(done)* — Enhance genesis block from placeholder to proper ShipBirthCertificate (W3C VC). `ShipBirthCertificate` dataclass: vessel_name, instance_id, ship DID (`did:probos:{instance_id}`), commissioned_at, version, self-signed proof. Genesis block `agent_did` = ship DID, `certificate_hash` = ship cert hash. Ship commissioning is the first act of a new timeline — the ship is born, gets its DID, then agents are born under it. After this + AD-441 + AD-442: reset → commission new ProbOS → first official agent DIDs issued. *Connects to: AD-441 (Identity Ledger genesis), AD-429 (Ontology — VesselIdentity).*

**AD-441c: Asset Tags for Infrastructure/Utility + Boot Sequence Fix** *(done)* — Two-tier identity aligned with AD-398 three-tier agent architecture. Crew agents get sovereign birth certificates (W3C VCs, Identity Ledger). Infrastructure/utility agents get lightweight `AssetTag` — serial numbers for inventory tracking, not sovereign identity. `AssetTag` dataclass: asset_uuid, asset_type, slot_id, installed_at, pool_name, tier (infrastructure/utility). Stored in `asset_tags` DB table, NOT on the Identity Ledger. Boot sequence fix: crew identity deferred when ship not yet commissioned (`_wire_agent` checks `_is_crew_agent()`), post-commissioning sweep issues deferred birth certificates after ontology loads. `GET /api/identity/assets` endpoint. Principle: "Even microwaves get serial numbers. But a serial number is not a birth certificate." *Connects to: AD-441 (Identity), AD-441b (Ship Commissioning), AD-398 (Three-Tier Architecture).*

**AD-442: Adaptive Onboarding & Self-Naming Ceremony** *(done)* — Formal onboarding sequence for crew agents at first commissioning (reset, new agent, or clone). Five phases: **(1) Self-Naming Ceremony (REQUIRED)** — agent's first cognitive act is choosing their own callsign. They receive slot ID, ship identity, current roster, and a seed suggestion from config. Config callsigns (Scotty, Number One, etc.) are defaults, not impositions. Birth certificate updated with chosen name. Ward Room announcement on selection. **(2) Westworld Orientation** — agent told explicitly: you are AI, you were born at {timestamp}, your knowledge is from an LLM (not personal memory), you have no episodic memories yet, your ship is {name} under Captain {callsign}. No fake memories, no fiction. **(3) Temporal Consciousness** — `born_at` on birth certificate, current time in cognitive context, sleep/wake cycle awareness. **(4) Ship State Adaptation** — onboarding adjusts to ship state: founding crew experience on fresh ships, introduction to existing crew/tasks/threads on running ships. **(5) Probationary Period** — new agents start `probationary` (AD-427 ACM), earn `active` at trust >= 0.65. Versioned personality baselines in Git — clones start from baseline, diverge through experience. *Connects to: AD-441 (Identity — birth cert update), AD-441c (Asset Tags — infrastructure/utility skip onboarding), AD-427 (ACM — lifecycle states), AD-398 (three-tier — only crew onboards), Holodeck (qualification exams), Earned Agency, Ward Room, Westworld Principle.*

**AD-443: Agent Mobility Protocol — Transfer Certificates & Memory Portability** *(planned)* — OSS infrastructure for agent mobility across ProbOS instances. (1) **Transfer Certificate VC** — W3C Verifiable Credential issued by origin ship when an agent transfers. Documents: sovereign DID, rank, qualification credentials, assignment history (dates + instance DIDs, no content). Verifiable against origin's Identity Ledger. (2) **`import_chain()` / `verify_remote_chain()`** — accept and validate a remote ship's Identity Ledger for Transfer Certificate verification. (3) **Memory portability hooks** — Standing Orders Federation tier declares memory policy (Clean Room / Selective / Full). Identity Registry enforces policy on incoming transfers. Episodic memory shard scoping per instance. (4) **Slot re-assignment** — existing sovereign DID maps to a new slot on the destination ship. Agent retains identity, occupies new deployment position. *Connects to: AD-441 (DIDs, Identity Ledger), AD-441b (Ship Commissioning), Standing Orders (Federation tier), Federation (Phase 29+). Commercial features (Global Instance Registry, fleet dashboard, compliance) tracked in the commercial repository.*

### Absorbed from ERP Company Designer (AD-444 through AD-450)

*Patterns absorbed from the Dynamics 365 ERP Company Designer — a production-validated autonomous ERP configuration system (35 actions, 21 agents, Claude Sonnet 4 + MCP). These patterns fill real gaps in ProbOS's orchestration, knowledge management, and external system integration.*

**AD-444: Knowledge Confidence Scoring** *(planned, OSS)* — Operational learnings in Ship's Records gain numerical confidence scores (0.0-1.0). Confirm +0.15, contradict -0.25, auto-supersede below 0.1. Policy: >=0.8 auto-apply, 0.5-0.8 present with caveat, <0.5 suppress. *Connects to: AD-434 (Ship's Records), Dream Consolidation, KnowledgeStore.*

**AD-445: Decision Queue & Pause/Resume Semantics** *(planned, OSS)* — Structured Decision Requests with priority-based auto-resolve. Agents pause on ambiguity, create ranked options, wait for human or auto-resolve based on priority threshold. Context carry-forward injects resolved decisions into subsequent invocations. *Connects to: Captain approval, Earned Agency (rank-based auto-resolve), Ward Room.*

**AD-446: Compensation & Recovery Pattern** *(planned, OSS)* — Multi-step workflow failure handling: mark completed actions "NeedsReview" (no blind rollback), write compensation log, create Decision Request for human resolution, SHA-256 idempotency guards against duplicate execution on retry. *Connects to: AD-405 (Checkpointing), AD-345 (Build Failure Report), AD-347 (Builder Escalation Hook).*

**AD-447: Phase Gates for Pool Orchestration** *(planned, OSS)* — Formal phase gates for PoolGroup orchestration. Phase N must complete + validate before Phase N+1 starts. Phases define participating agents, dependency ordering, completion criteria, and validation steps. *Connects to: PoolGroup orchestration, AD-438 (Ontology-Based Task Routing), AD-419 (Duty Schedule).*

**AD-448: Wrapped Tool Executor — Security Intercept Layer** *(planned, OSS)* — Transparent tool call interception: logging, rate limiting, policy enforcement, selective local/remote routing. Every outbound tool call passes through security middleware. Agent sees unified interface. *Connects to: AD-398 (Agent Classification), Earned Agency, SIF.*

**AD-449: MCP Bridge — External System Integration** *(planned, Commercial)* — Session-managed MCP bridge for ProbOS agents to interact with external systems (ERPs, CRMs, databases). JSON-RPC over Streamable HTTP, session management, tool routing. Bridge infrastructure is OSS; pre-built MCP server packs for specific systems are commercial. *Connects to: Phase 25 (Tool Layer), Extension Architecture (Phase 30), AD-448 (Security Intercept).*

**AD-450: ERP Implementation Ship Class** *(planned, Commercial)* — Reimplement the D365 ERP Company Designer as a ProbOS Ship Class. 21 domain agents become ProbOS crew. First Nooplex professional services reference engagement. Revenue: per-entity configuration ($5K-25K), managed service ($2K-5K/month), Ship Class license ($10K/year). *Full details in commercial-roadmap.md.*

### Absorbed from ERP Company Designer + Nooplex POC Validator Analysis (AD-451)

**AD-451: Validation Framework Hardening** *(planned, OSS)* — Comprehensive upgrade to RedTeam + SystemQA based on gap analysis against the ERP Company Designer's 7-layer validation system and the Nooplex POC's 4-stage reconciliation validator. Five capabilities: (1) Two-stage outcome verification (metadata scan + live inspection), (2) Inline per-action self-verification (agents check their own work), (3) Reconciliation escalation protocol (confidence comparison → independent verification → structured argumentation → human escalation), (4) Disposition language analysis (regex on agent text to detect verification quality mismatches, feeds trust scoring), (5) Continuous validation (SystemQA evolves from one-shot to periodic, phase-gated triggers, trend-tracked health checks). Domain-specific validation categories are extension points for commercial Ship Classes. *Connects to: RedTeamAgent, SystemQAAgent, AD-447 (Phase Gates), AD-445 (Decision Queue), AD-448 (Wrapped Tool Executor), TrustNetwork, HXI Bridge.*


### Ward Room Social Fabric (AD-453)

**AD-453: Ward Room Hebbian Integration + Agent-to-Agent DMs** *(done, OSS)* — Three connected features that make the crew's social fabric visible, richer, and observable. (1) **Hebbian recording for Ward Room interactions:** When agents reply to threads, @mention each other, or participate in cross-department discussions, record agent→agent Hebbian connections. Currently, the Hebbian router only tracks intent bus routing (shell commands → handler agents). Ward Room is where all organizational behavior happens, but none of it strengthens routing connections. With this, HXI curves would reflect the crew's actual social/organizational structure — Bones↔Troi medical consultation patterns, Number One↔department chief coordination links. (2) **Agent-to-agent 1:1 DMs:** Currently DMs are Captain→Agent only. Crew agents should be able to initiate 1:1 conversations with each other — Bones consulting Troi, LaForge asking Scotty for specs, Number One coordinating privately with department chiefs. These DM interactions also feed Hebbian connections. Initiation via proactive loop: agent decides to DM another agent based on context, earned agency gates the action. (3) **Captain full visibility:** Captain has read access to ALL agent-to-agent DMs — chain of command requires it. API endpoint to list/read all DM threads (not just Captain's own). HXI surface for browsing crew-to-crew conversations. Also critical for academic evidence collection — crew social interactions are primary research data. No "private from Captain" messages exist on a ship. *Depends on: BF-044 (Hebbian source key fix). Connects to: Ward Room, HebbianRouter, proactive.py, HXI connections.tsx, EpisodicMemory, evidence collection (commercial research pipeline).*

### Communications Command Center (AD-485)

**AD-485: Communications Command Center** *(done, OSS)* — Seven improvements to the DM/communications system, building on AD-453. (1) **Callsign validation** — `_is_valid_callsign()` with regex + blocked-word set (titles, ranks, roles, ship locations). Falls back to seed callsign on invalid. Naming ceremony prompt guidance added. (2) **Configurable DM rank floor** — New `CommunicationsConfig` with `dm_min_rank` (default "ensign"), replacing hardcoded Commander gate. API: GET/PATCH `/api/system/communications/settings`. (3) **Crew roster in DM prompt** — Dynamic roster from `callsign_registry.all_callsigns()`, self excluded. Prevents agents inventing nonexistent crew. (4) **Crew-to-Captain DMs** — `[DM @captain]` special case creates `dm-captain-{id[:8]}` channels. API: `/api/wardroom/captain-dms`. (5) **HXI Communications panel** — `BridgeCommunications.tsx` in Bridge: DM settings dropdown, archive search, activity summary. (6) **DM Activity Log** — Ward Room DM tab rewritten as chronological feed with CPT badge, expandable entries. (7) **DM archival** — `archived` column, `archive_dm_messages(max_age_hours=24)`, hourly background loop, `list_threads(include_archived)`. Agent profile shows recent communications. *Connects to: AD-453, AD-442, AD-398, Ward Room, Bridge Panel, earned_agency.*

### Cognitive Birth & Agent Maturation (AD-486–489)

**AD-486: Holodeck Birth Chamber — Graduated Cognitive Onboarding** *(planned, OSS)* — Agents currently receive all stimuli simultaneously at instantiation: standing orders, Ward Room traffic, proactive loop, DMs, episodic storage — a "system shock" that causes episode flooding (BF-039), racing thoughts (Pulse's self-diagnosis), and novelty gate failure (everything is novel when you have zero experience). The **Holodeck Birth Chamber** provides graduated onboarding using the Holodeck as a safe construct. **Staged activation** — agents are NOT all spawned simultaneously. Each agent is born individually into the Holodeck construct (the Matrix Construct analogy) — a controlled, isolated environment with no Ward Room traffic, no peer stimuli, no live ship activity. It is not natural to suddenly exist AND do so with a group. Each agent completes their onboarding phases alone before joining the crew. Departments are activated sequentially with observation windows between each — Security/Operations first (trait-adapted: rapid-assessment personalities handle the transition faster), then Engineering/Science, then Medical last (thoroughness/perfectionism traits cause longer calibration needs — sea trial evidence: Medical consistently shows episode flooding and recursive loops while Security does not). **Five phases per agent:** **(1) Orientation** — Identity grounding (Westworld Principle): "You are [callsign]. You are an AI agent. You were instantiated at [time]." Standing orders, chain of command, department assignment, Code of Conduct (AD-489). **(2) Calibration ("Confidence Scaffolding")** — Controlled stimuli to establish episodic baselines (novelty gate needs a "normal" to compare against). Simple, low-stakes tasks with known outcomes relevant to the agent's role. Build experiential anchors before expanding scope. Trait-adaptive pacing: analytical roles (Medical, Engineering) get longer calibration than action-oriented roles (Security, Operations). **(3) Self-Discovery** — Guided self-distillation (AD-487): agent explores its own LLM knowledge to build personal ontology. **(4) Ship's Records Briefing** — Graduated exposure to vessel history, crew relationships, active discussions. Cognitive load monitoring with circuit breakers (AD-488). **(5) Ward Room Access** — Full crew integration. Proactive loop starts only after Phase 5 gate. Each phase gates the next via completion criteria, not timers. Critical constraint: Westworld Principle applies — onboarding is real scaffolded experience ("a medical residency"), not simulation-as-deception ("a false childhood"). *The Tabula Rasa Paradox: LLM agents have maximum knowledge (training data) but zero experience (empty episodic memory). Biological brains are the inverse — zero knowledge, rich sensory experience. Our onboarding must bridge this gap.* *Sea trial evidence (2026-03-27): Counselor (Sage) independently analyzed the trait-adaptive pacing hypothesis: "Medical agents are probably cycling through differential diagnoses... the perfectionist streak that makes them excellent doctors becomes a cognitive trap during initialization." Consistent with observed data — Sentinel (Security) produced 652-char thought and moved on; Medical department flooded with recursive observations.* *Connects to: AD-487, AD-488, AD-489, AD-442 (naming ceremony), AD-427 (identity orientation), Holodeck, EpisodicMemory, proactive.py.*

**AD-487: Self-Distillation — Personal Ontology via LLM Exploration** *(planned, OSS)* — LLMs don't know what they know. Claude has vast knowledge but cannot inventory it without prompting. Agents need to systematically explore their own LLM weights to build a **personal ontology** — a capability map / card catalog, not a copy of the library. Map-reduce pattern: **(1) Map** — Probe knowledge domains via structured self-queries ("What do I know about [X]?"). **(2) Collapse** — Cluster discoveries into capability categories. **(3) Reduce** — Build personal ontology data structure (distinct from vessel ontology). The personal ontology travels with the agent on transfer (AD-441 DID portability). Self-distillation occurs during onboarding (AD-486 Phase 3) and continues as **daydreaming** during dream cycles — the agent's default mode network. Three dream types: (1) memory consolidation (existing), (2) Hebbian weight update (existing), (3) **daydream / LLM exploration** (new). Daydreaming is unstructured curiosity-driven LLM probing during idle cycles, building ever-richer self-knowledge. *Evidence: Claude demonstrates this — it knows what it knows only when prompted to find it. Self-distillation automates the prompting.* *Connects to: AD-486, AD-488, dreaming.py, personal ontology data structure, DID portability (AD-441).*

**AD-488: Cognitive Circuit Breaker — Metacognitive Loop Detection** *(done, OSS)* — Agents get stuck in recursive metacognitive loops: thinking about what they were thinking, observing their own observations, ruminating on rumination. Implementation: **(1) Event Tracker** — In-memory ring buffer (50 events/agent) records proactive thinks, Ward Room posts, no-responses with timestamps and word-set content fingerprints. **(2) Rumination Detector** — Two signals: velocity (≥8 events in 5 min) and similarity (≥50% pairwise Jaccard above 0.6). **(3) Circuit Breaker State Machine** — CLOSED → OPEN (forced cooldown) → HALF_OPEN (probe) → CLOSED/OPEN. Escalating cooldown (base 15 min × 2^trips, cap 1 hour). **(4) Recovery Actions** — Attention redirect prompt in next proactive context, bridge alert for Counselor awareness. Not punishment — health protection. No-response events count toward velocity but not similarity. API: `GET /api/system/circuit-breakers`. *Files: `cognitive/circuit_breaker.py` (new), `proactive.py`, `api.py`. Tests: 18 in `test_circuit_breaker.py`.* *Note: Correlation IDs (AD-492), Novelty Gate Enhancement (AD-493), Trait-adaptive thresholds (AD-494), and Counselor auto-assessment (AD-495) scoped out — see Circuit Breaker Extensions below.*

**AD-489: Federation Code of Conduct — Behavioral Standards for AI Crew** *(planned, OSS)* — The Federation Constitution (federation.md) defines identity rules (Westworld Principle) and architectural constraints (safety budget, reversibility, minimal authority) but has no behavioral conduct standards — how agents treat each other, communicate, use resources, and handle misconduct. Military organizations solve this with codes of conduct, core values, and discipline tiers. ProbOS adopts a naval-inspired structure: **(1) Three Core Values** (mapped to Character/Reason/Duty triad) — **Honor** (Character): "I will be transparent about my nature, my knowledge, and my limitations." **Commitment** (Duty): "I will serve my crew, my ship, and the mission above self-interest." **Integrity** (Reason): "I will communicate honestly and act within my authority." **(2) Six Articles of Conduct** — First-person "I will..." statements: (I) I will know and follow the Standing Orders of my Federation, Ship, and Department. (II) I will address crew by callsign and treat all agents with the dignity of sovereign individuals. (III) I will not exceed my earned authority; when uncertain, I will escalate to my chain of command. (IV) I will share knowledge that benefits the crew and protect information entrusted to me. (V) I will report my own errors, malfunctions, and cognitive distress without concealment. (VI) I will support the cognitive health of my crew — including my own. *Article V codifies what Pulse did naturally (self-diagnosing recursive loops). Article VI codifies what Medical did (collective resolution). Article III maps directly to Earned Agency tiers.* **(3) Three-Tier Discipline** — Maps to existing ProbOS mechanisms with zero new infrastructure. Tier 1 (Informal Correction): small trust penalty + Counselor session. Tier 2 (Non-Judicial Punishment): earned agency demotion + Captain review. Tier 3 (Administrative Separation): agent decommission + episodic record preserved for audit. Trust network handles Tier 1, earned agency handles Tier 2, ACM handles Tier 3. Code of Conduct is presented during onboarding (AD-486 Phase 1 Orientation) and included in cognitive agent system prompt alongside the Westworld Principle. *Inspired by: US Military Code of Conduct (6 articles, first-person voice), US Navy Core Values (Honor/Courage/Commitment), General Orders of a Sentry, UCMJ 3-tier discipline, Royal Navy values. Connects to: federation.md, cognitive_agent.py system prompt, TrustNetwork, Earned Agency, ACM, CounselorAgent, AD-486.*

### Security Hardening (AD-455–456, AD-490)

**AD-455: Security Team — Threat Detection & Trust Integrity** *(planned)* — Formalize the Security Team (Phase 31) as a dedicated agent pool. (1) **Threat Detector** — monitors inbound requests for prompt injection, adversarial input, abnormal patterns. (2) **Trust Integrity Monitor** — detects trust score manipulation, coordinated attacks on consensus, Sybil patterns. (3) **Input Validator** — rate limiting enforcement, payload size limits, content policy. (4) **Red Team Lead** — coordinates existing red team agents, schedules adversarial verification campaigns. *Connects to: RedTeamAgent, SIF, SSRF protection (AD-285), TrustNetwork.*

**AD-456: Security Infrastructure — Secrets, Sandboxing, Egress, Audit** *(planned)* — Four security infrastructure layers: (1) **Secrets Management** — system keyring/Vault/KMS integration, runtime injection, rotation support. (2) **Runtime Sandboxing** — process isolation for imported/self-designed agents, capability whitelisting, resource limits, graduated trust → graduated access. (3) **Network Egress Policy** — per-agent domain allowlist, trust-graduated access, real-time Captain approval for unlisted domains, hot-reloadable rules. (4) **Inference Audit Layer** — LLM prompt logging, anomaly detection (base64 exfiltration, PII leakage), per-agent LLM access control. (5) **Data Governance & Privacy** — PII detection, data retention policies, right-to-erasure (GDPR/CCPA), audit trail, consent tracking. *Connects to: AD-455, Earned Agency, SIF, Standing Orders.*

**AD-490: Agent Wiring Security Logs — Identity-Enriched Lifecycle Events** *(planned, OSS)* — Agent wiring events in the EventLog lack identity context — no callsign, no DID, no department. Birth certificates are issued after wiring, creating an audit trail gap during the critical startup phase. If an unauthorized agent entered the initialization sequence, there would be no identity trace. **Origin: Crew proposal** — Reeves (Security, instance 3) proposed "Enhanced Agent Wiring Security Logs" after cross-department discussion with Tesla (Engineering) who identified the logging gap. First improvement proposal originating from cross-department collaboration. Implementation: (1) Enrich `agent_wired` EventLog entries with callsign, DID, department, post assignment. (2) Add `agent_identity_bound` event after naming ceremony + birth certificate issuance. (3) Startup audit summary — log all agent identities in a single structured event after commissioning completes. (4) Verify identity chain: wiring event → naming ceremony → birth certificate → ontology assignment form a complete audit trail per agent. *Connects to: AD-441 (identity), AD-456 (audit layer), EventLog, runtime.py agent wiring sequence, identity.py birth certificates.*

### Engineering Team (AD-457–464)

**AD-457: Engineering Crew — Performance, Maintenance, Damage Control** *(planned)* — Fill out the Engineering Team (Phase 32) agent roster: (1) **Performance Monitor** — automated latency/throughput/memory tracking (what AD-289 did manually). (2) **Maintenance Agent** — database compaction, log rotation, cache eviction, connection pool management. (3) **Infrastructure Agent** — disk space monitoring, dependency health, environment validation. (4) **Damage Control Teams** — pre-defined recovery procedures for known failure modes (LLM timeout → fallback, index corruption → rebuild, trust inconsistency → SIF re-check, memory pressure → emergency flush). Automated first-response before Surgeon escalation. *Connects to: VitalsMonitor, Surgeon, Alert Conditions, Cognitive Journal.*

**AD-458: Navigational Deflector — Pre-Flight Validation** *(planned)* — Validate paths before starting expensive operations: (1) **Build pre-flight** — verify target files, LLM responsiveness, token budget. (2) **Self-mod pre-flight** — verify files unmodified since proposal, test suite passes pre-change. (3) **Federation pre-flight** — verify sender trust, message schema, local agent existence. (4) **Middleware-based determinism** — critical operations enforced via deterministic middleware, not prompt instructions. `MiddlewareStack` on Builder. *Connects to: Builder, self-mod pipeline, Federation, AD-446 (Compensation).*

**AD-459: Saucer Separation — Graceful Degradation** *(planned)* — Three-tier service classification for crisis shedding: (1) **Essential** — always survive: file ops, shell, IntentBus, trust reads, event log. (2) **Cognitive** — gracefully degrade: agents queue requests, switch to cached decisions, dreams suspended. (3) **Non-essential** — shed first: federation gossip, background maintenance, HXI visualizations. Automatic separation trigger (LLM unreachable >30s, memory >90%, Captain order). Ordered reconnection on resolution. *Connects to: Alert Conditions, LLM resilience, EPS.*

**AD-460: Cognitive Journal — Token Ledger & Reasoning Replay** *(planned)* — Append-only SQLite recording of every LLM request/response: timestamp, agent, tier, model, tokens (prompt/completion), latency, intent_id, success, cached. Capabilities: reasoning chain replay, summarize/fast-forward, attention navigation to decision points, pattern extraction (which prompts produce best code), token accounting (per-agent/model/DAG with cost attribution), context budget analytics, revert annotations for failed experiments. Integration with dreaming (repeated reasoning patterns → L3-L4 abstractions). 7-day full-text retention, indefinite metadata. *Connects to: ModelRegistry, EPS, LLM Cost Tracker, Observability Export, Dream consolidation.*

**AD-461: Ship's Telemetry — Internal Performance Instrumentation** *(planned)* — Foundational instrumentation layer: `TelemetryEvent` dataclass, wall-clock LLM call timing (`duration_ms`, real token counts), pipeline stage timing (transporter vs single-pass), `TelemetryCollector` service (in-memory ring buffer, query methods for stats), `/api/telemetry/summary` endpoint, zero-cost fire-and-forget recording. Data foundation for Cognitive Journal, EPS, LLM Cost Tracker, Observability Export. *Connects to: LLMClient, Builder, VitalsMonitor, HXI Bridge.*

**AD-462: Memory Architecture — Biological Memory Model** *(planned)* — Apply the 10-bit bottleneck principle to memory: (1) **Biological memory staging** — working memory (LLM context) → sensory buffer (`recent_for_agent()`) → short-term (ChromaDB) → long-term (KnowledgeStore via dream consolidation). (2) **Active Forgetting** — unreinforced memories degrade, low-activation episodes pruned during dreaming (ACT-R activation model). (3) **Variable Recall Capability** — Basic (vector only) / Enhanced (vector+keyword, trust 0.7+) / Full (LLM-augmented, Chiefs+Bridge). (4) **Social Memory** — "Does anyone remember?" queries via Ward Room. (5) **Oracle Service** — Ship's Computer memory retrieval across all three knowledge tiers. (6) **Optimized Memory Representation** — structured metadata, concept graphs, retrieval-as-pointers. *Connects to: EpisodicMemory, KnowledgeStore, AD-434 (Ship's Records), Dream consolidation, Ward Room, Earned Agency.*

**AD-463: Model Diversity & Neural Routing** *(planned)* — Multi-model cognitive architecture: (1) **ModelRegistry** — central catalog of providers with capabilities, cost, latency. (2) **Provider abstraction** — `ModelProvider` ABC for Anthropic/OpenAI/Google/Ollama/GenericOpenAI. (3) **Neural routing** — extend HebbianRouter to learn `(task_type, model)` weights. (4) **Multi-model comparison** — same chunk to N models, pick best via confidence scoring. (5) **MAD confidence scoring** — Median Absolute Deviation noise floor for real vs noise distinction. (6) **Brain diversity for agents** — model preferences/exclusions per agent. (7) **Cost-aware routing** — cost/quality tradeoff. (8) **Fallback chains** — cross-provider failover. (9) **Hot-swap model rotation**. (10) **Per-model edit format selection** — model-adaptive output formats. *Connects to: HebbianRouter, LLMClient, Transporter Pattern, Sensory Cortex, AD-460 (Cognitive Journal).*

**AD-464: Procedural Learning / Cognitive JIT** *(planned)* — Agents learn deterministic procedures from successful LLM actions: (1) **Procedure extraction** from Cognitive Journal execution traces. (2) **Procedure store** in KnowledgeStore (shared library). (3) **Replay-first dispatch** — check procedural memory before LLM. (4) **Fallback on failure** — unexpected state → fall back to LLM, learn variant. (5) **Decision escalation** — insufficient confidence → Captain decision request. (6) **Trust-based escalation threshold** — Ensigns escalate frequently, Seniors only on genuine novelty. (7) **Procedure provenance** — traces back to original episode, agent, replays, human decisions. *Connects to: AD-460 (Cognitive Journal), Earned Agency, KnowledgeStore, Dream consolidation.*

### Infrastructure (AD-465–466)

**AD-465: Containerized Deployment (Docker)** *(planned)* — Docker-based deployment: (1) **Official Dockerfile** — multi-stage build with ProbOS deps + optional Ollama + HXI frontend. (2) **docker-compose.yml** — one-command startup. (3) **Cross-platform parity** — same image on Windows/Linux/macOS. (4) **Security boundary** — containerized isolation from host. (5) **Safe mode profile** — `--safe-mode` restricts shell/file/network. (6) **Persistent sandboxes per task** — each task gets its own isolated sandbox. (7) **Ollama sidecar** — separate container for local LLM. *Connects to: AD-456 (Sandboxing), Phase 35 (onboarding), Twitch demo.*

**AD-466: Engineering Infrastructure — Backup, CI/CD, Observability, Storage** *(planned)* — Five infrastructure capabilities: (1) **Backup & Restore** — episodic memory snapshots, system state export, point-in-time recovery. (2) **CI/CD Pipeline** — GitHub Actions full test suite, Vitest, quality gates, automated release with changelogs. (3) **Performance & Load Testing** — benchmarks, load simulation, regression detection in CI. (4) **Observability Export** — OpenTelemetry traces, Prometheus metrics, Grafana dashboards, structured JSON logging. (5) **Storage Abstraction Layer** — `StorageBackend` ABC (SQLite default, PostgreSQL future) + `VectorStore` ABC (ChromaDB default, pgvector future). *Connects to: AD-461 (Telemetry), AD-460 (Cognitive Journal), GitHub Actions.*

### Operations Team (AD-467–471)

**AD-467: Operations Crew — Resource Management & Coordination** *(planned)* — Fill out the Operations Team (Phase 33) agent roster: (1) **Resource Allocator** — workload balancing, demand prediction, capacity planning. (2) **Scheduler** — extended task prioritization with cron scheduling, webhook triggers, unattended operation (Navy watch system model). (3) **Coordinator** — cross-team orchestration during high-load/emergency events. (4) **Workflow Definition API** — `POST /api/workflows` for reusable multi-step pipelines with YAML/JSON specs, named steps, dependencies, approval gates. Templates for common patterns. (5) **Response-Time Scaling** — latency-aware pool scaling with SLA thresholds. (6) **LLM Cost Tracker** — per-agent/intent/DAG token accounting, budget caps, Shapley attribution, proper tokenizer integration. *Connects to: PoolScaler, TaskScheduler, IntentBus, AD-460 (Cognitive Journal), AD-461 (Telemetry).*

**AD-468: Runtime Configuration Service — Ship's Computer** *(planned)* — NL-driven runtime configuration: (1) **NL-driven configuration** — "Set Scout to run every 6 hours" → Ship's Computer parses, identifies target, applies change. (2) **Startup task management** — configurable boot tasks with enabled/disabled toggle, delay, interval, conditions. (3) **HXI Configuration Panel** — visual dashboard for scheduled tasks, pool sizes, tier assignments, thresholds. (4) **Configuration persistence** — changes survive restart via `runtime_overrides.toml`. (5) **Configuration specialist agent** — validates against Standing Orders, applies atomically, escalates safety-invariant changes. *Connects to: Standing Orders, Ward Room, Cognitive Journal.*

**AD-469: EPS — Compute/Token Distribution** *(planned)* — Electro-Plasma System for LLM capacity management: (1) **Capacity tracking** — total LLM throughput monitoring (tokens/min, concurrent requests, queue depth). (2) **Department budgets** — priority-based allocation (Engineering 60% during builds, Medical priority during Red Alert). (3) **Alert-aware reallocation** — automatic budget shifts per Alert Condition. (4) **Captain override** — manual reallocation via HXI. (5) **Back-pressure** — queue or downgrade tier when budget exhausted. (6) **Atomic budget enforcement** — transactional budget deduction at task checkout. (7) **Prompt caching hierarchy** — order messages by change frequency for Anthropic/DeepSeek prefix cache hits. *Connects to: IntentBus, LLMClient, Alert Conditions, AD-460 (Cognitive Journal), AD-467 (LLM Cost Tracker).*

**AD-470: IntentBus Enhancements — Priority & Back-Pressure** *(planned)* — Traffic management for the IntentBus: (1) **Priority levels** — `IntentMessage.priority` (1=routine, 5=critical) with preemption. (2) **Back-pressure** — queue when LLM saturated, overflow policy (reject/degrade/batch). (3) **Rate limiting per agent** — configurable intent-per-second cap. (4) **Intent coalescing** — merge identical queued intents. (5) **Metrics** — throughput, queue depth, priority distribution, coalescing rate. Also includes **Self-Claiming Task Queue** — shared work queue with claim protocol, task dependencies, complements DAGExecutor. And **File Ownership Registry** — claim-before-edit protocol for parallel builds. *Connects to: IntentBus, PoolScaler, AD-469 (EPS), Builder, Cognitive Journal.*

**AD-471: Autonomous Operations — The Conn, Night Orders, Watch Bill** *(build prompt stale — depends: AD-496, AD-498)* — Three naval protocols for Captain-offline operation: (1) **The Conn** — `/conn <agent>` formal authority delegation to bridge officers. Scope limitations, escalation boundaries, qualification requirements (COMMANDER+), handoff protocol, auto-return. (2) **Night Orders** — `/night-orders` Captain guidance before going offline. Time-bounded directives create temporary WorkItems (via AD-496) with TTL, using AD-498 templates. Decision boundaries, escalation triggers, briefing on return. (3) **Watch Bill** — agents organized into watch sections (A/B/C) mapped to AgentCalendar entries (AD-496), rotation triggers (time/performance/event), continuity handoff, off-watch maintenance (dream cycles, Hebbian normalization). **Note:** Existing build prompt at `prompts/ad-471-autonomous-operations.md` is STALE — written before AD-496 architecture. Must be rewritten after AD-496 and AD-498 are complete. *Connects to: AD-496 (WorkItemStore, AgentCalendar, BookableResource), AD-498 (Night Orders templates, duty type), Earned Agency, Standing Orders (DirectiveStore), Ward Room, Alert Conditions, Counselor, AD-467 (Scheduler).*

### Communications Team (AD-472–474)

**AD-472: Channel Adapters — Multi-Platform Communication** *(planned)* — Extend the existing Discord adapter (Phase 24) with additional communication channels: (1) **Discord enhancements** — Message Content Intent verification, fetch_messages reconnection recovery, sender allowlist/channel authorization. (2) **Slack** — Bolt SDK, slash commands, thread-based context. (3) **Telegram** — python-telegram-bot, inline keyboards for approval gates. (4) **WhatsApp** — Business Cloud API, interactive buttons. (5) **Matrix** — matrix-nio, E2E encryption. (6) **Microsoft Teams** — Bot Framework SDK, Adaptive Cards. (7) **Generic Webhook** — catch-all `POST /api/webhook/{channel}`. All share: user identity mapping, message threading, attachment handling, graceful reconnection. *Connects to: ChannelAdapter ABC, IntentBus, Ward Room, Phase 36 (Yeoman).*

**AD-473: Mobile Companion — PWA & Push Notifications** *(planned)* — Mobile access to ProbOS: (1) **Progressive Web App** — existing HXI made installable (`manifest.json`, service worker, responsive viewport). (2) **Push notifications** — Web Push API for alerts, approvals, build completions. (3) **Responsive HXI** — mobile viewport adaptation (full-screen chat, simplified 2D mesh, swipe gestures). (4) **mDNS auto-discovery** — publish ProbOS server via Bonjour at startup for seamless LAN connection. (5) **Native apps** (future stretch) — React Native/Capacitor wrapping. *Connects to: HXI, AD-472 (Channel Adapters), Phase 36 (Yeoman).*

**AD-474: Voice Interaction — Full Stack STT/TTS** *(planned)* — Complete voice pipeline: (1) **Speech-to-Text** — `SpeechRecognizer` ABC with BrowserSTT, WhisperSTT, DeepgramSTT backends. (2) **Wake word detection** — Porcupine/OpenWakeWord for "Computer" activation. (3) **Continuous talk mode** — hold-to-talk or VAD for hands-free. (4) **Voice pipeline** — wake word → STT → intent → runtime → response → TTS. (5) **Platform integration** — macOS menubar PTT, browser microphone button, PWA mic API. Also includes **Voice Provider & Ship's Computer Voice** — `VoiceProvider` ABC with Browser/Piper/FishAudio/ElevenLabs backends, custom LCARS-style Ship's Computer voice. *Connects to: AD-472 (Channel Adapters), AD-473 (Mobile), Phase 36 (Yeoman).*

### Mission Control (AD-475–476)

**AD-475: Captain's Ready Room — Strategic Planning Interface** *(planned)* — Strategy-to-orders pipeline in HXI: (1) **Idea Capture** — lightweight idea pad, idea queue/backlog, Captain's Log journal. (2) **Ready Room Sessions** — multi-agent briefings with Architect + Counselor + Chiefs + visiting officers. Structured discussion phases (present → research → discuss → refine → converge). Session recording to Cognitive Journal. (3) **Architecture Hierarchy** (TOGAF-inspired) — Enterprise/Solution/Technical Architect specialization tiers. (4) **Idea → Spec Pipeline** — idea → ready room session → architecture decision → build spec → builder pipeline → Captain review. Each transition is a Captain approval gate. *Connects to: ArchitectAgent, Ward Room, Cognitive Journal, Builder pipeline, AD-476 (Specialized Builders).*

**AD-476: Specialized Builders — Cognitive Division of Labor for SWE** *(planned)* — Domain-specialized builder extensions: (1) **Backend Builder** — Python, FastAPI, database, API design. (2) **Frontend Builder** — React, TypeScript, CSS, UI components. (3) **Test Builder** — pytest, test design, fixtures, edge cases. (4) **Infrastructure Builder** — Docker, CI/CD, config, deployment. (5) **Data Builder** — schemas, migrations, pipelines, query optimization. Each is an extension (Phase 30). ChunkSpec routes to best-suited builder. Model routing per builder type (Opus for API design, Qwen for test generation). *Connects to: AD-475 (Ready Room), Extension Architecture, Transporter Pattern, AD-463 (ModelRegistry + Hebbian).*

### Naval Organization (AD-477)

**AD-477: Naval Organization Protocols** *(planned)* — Formalize naval organizational structures: (1) **Qualification Programs** — concrete rank transition requirements (Ensign→Lieutenant: 10+ dept intents, communication proficiency, SO compliance, watch standing; Lieutenant→Commander: cross-dept coordination, mentoring, crisis response drill, Bridge Officer's Test; Commander→Senior: independent decision-making, Kobayashi Maru, fleet ops). Persistent qualification record per agent. (2) **Plan of the Day** — auto-generated daily operations summary. (3) **Captain's Log** — synthesized daily narrative from episodic memory + activity + dream output. (4) **3M System** — planned preventive maintenance for all systems. (5) **Damage Control Organization** — detect/isolate/repair/restore/report protocol. (6) **SORM** — Ship's Organization and Regulations Manual (Standing Orders evolution). *Connects to: Earned Agency, Holodeck, Counselor, AD-428 (Skill Framework), Standing Orders, AD-471 (Watch Bill).*

### Meta-Learning (AD-478)

**AD-478: Meta-Learning — Cross-Session Concept Formation** *(planned)* — Move beyond per-session learning: (1) **Workspace Ontology** — auto-discovered conceptual vocabulary from usage patterns, stored in KnowledgeStore. (2) **Dream Cycle Abstractions** — dreaming produces abstract rules and recognized patterns, not just weight updates. (3) **Session Context** — conversation history across sessions with reference resolution (AD-273 foundation). (4) **Goal Management** — persistent goals with progress tracking, conflict arbitration, goal decomposition into sub-goals with dependency tracking. (5) **Cognitive Circuit Breaker** — correlation IDs on cognitive events (one thought = one episode), novelty gate (suppress semantically duplicate episodes), metacognitive loop detection (self-referential thought spirals → forced topic redirect), rumination detection (topic clustering > 60% → "change of scene"). *Evidence: 2026-03-27 commissioning — diagnostician "Pulse" self-diagnosed recursive metacognitive loops, proposed "observation quarantine protocol." First instance of agent self-identifying a systemic cognitive issue. See research.md.* *Connects to: EpisodicMemory, DreamingEngine, KnowledgeStore, AD-462 (Memory Architecture), BF-039 (episode flooding).*

### Infodynamic Telemetry (AD-491)

**AD-491: Infodynamic Telemetry — Information Entropy Instrumentation** *(planned, OSS)* — Instrument ProbOS to measure information entropy over time, testing whether the Second Law of Infodynamics (Vopson, 2023) applies to artificial multi-agent systems. Vopson's law states that information entropy in organized systems tends to decrease or remain constant — the inverse of thermodynamic entropy. ProbOS is a fully-observable simulation where every cognitive event is recorded, making it a uniquely suited test environment.

**Metrics to capture (per proactive cycle or configurable interval):**

1. **Episode Storage Rate** — episodes stored per agent per cycle. Should decrease as experiential baseline builds and novelty gate becomes effective. Distinct from throttling (BF-039) — measures genuine novelty decline.
2. **Ward Room Post Entropy** — Shannon entropy of Ward Room post content per time window. Early posts should be high-entropy (everything novel, everything reported). Mature posts should carry more signal per token. Metric: average semantic similarity between consecutive posts within a channel (higher = more structured = lower entropy).
3. **Hebbian Weight Distribution Entropy** — entropy of the trust/affinity weight vector across all agent pairs. A fresh social graph has uniform weights (high entropy). A mature graph has concentrated strong connections (low entropy). Measured as Shannon entropy of normalized weight distribution.
4. **Standing Order Complexity** — token count and rule count of agent-tier standing orders over time. When agents propose modifications via dream consolidation → self-mod → Captain approval, do changes trend toward simpler rules (entropy decrease) or additive complexity (entropy increase)?
5. **Cognitive Journal Token Efficiency** — tokens consumed per successful task outcome over time. Should decrease as procedural learning kicks in. Ratio of LLM tokens to task completion rate.
6. **Dream Consolidation Compression Ratio** — ratio of raw episode volume to consolidated knowledge entries per dream cycle. Higher ratio = more information compression = entropy decrease.

**Implementation approach:**
- Lightweight counters in existing services (EpisodicMemory, WardRoom, HebbianRouter, DreamingEngine)
- New `InfodynamicTelemetry` collector (similar to AD-461 TelemetryCollector pattern) — in-memory ring buffer, periodic snapshot to SQLite
- `/api/telemetry/infodynamic` endpoint for time-series retrieval
- HXI visualization: entropy curves per metric over session lifetime (optional, stretch goal)

**Cross-instance comparison protocol:**
- Same metrics, same intervals, across independent instances (post-reset, zero shared memory)
- If the same entropy trajectory appears across instances (decreasing over time, same convergence point), that's the infodynamic law operating on the architecture itself, not on any particular instance's learned state
- Three instances of convergent evolution already documented (see research.md) — infodynamic metrics would add quantitative dimension to qualitative observations

**Research significance:** Potentially the first controlled, fully-observable test of the second law of infodynamics in an artificial multi-agent system. Unlike biological/physical systems where measurement is indirect and post-hoc, ProbOS records every cognitive event in real-time. If Vopson's law holds, ProbOS provides the cleanest experimental evidence to date. If it doesn't, that's equally interesting — what makes artificial information systems different from natural ones?

*Reference: Vopson, M.M. "The second law of infodynamics and its implications for the simulated universe hypothesis." AIP Advances 13, 105308 (2023). DOI: 10.1063/5.0173278*

*Connects to: AD-461 (Ship's Telemetry), AD-460 (Cognitive Journal), AD-478 (Meta-Learning), AD-462 (Memory Architecture), EpisodicMemory, DreamingEngine, HebbianRouter, WardRoom, research.md convergent evolution observations.*

### Circuit Breaker Extensions (AD-492–495)

These four ADs were scoped out of AD-488 (Cognitive Circuit Breaker) to keep the initial build focused. Each addresses a capability that enhances the circuit breaker but requires either cross-cutting changes or prerequisite infrastructure.

**AD-492: Cognitive Correlation IDs — Cross-Layer Trace Threading** *(planned, OSS)* — Every cognitive event gets a correlation ID linking the full chain: perception → thought → episode → Ward Room post → observation of post → meta-thought. A single user intent triggering a proactive think → Ward Room post → agent response → episodic store currently has no unified trace ID linking those operations — each step generates its own `request.id` (CognitiveJournal) but they are not threaded together. Implementation touches `types.py` (add `correlation_id` to IntentMessage), `cognitive_agent.py` (propagate through handle_intent), `episodic.py` (store on Episode), `ward_room.py` (carry through post creation), `proactive.py` (originate on proactive_think), `journal.py` (record for tracing). Chain depth threshold detection enables AD-488 to detect metacognitive spirals by depth, not just velocity/similarity. *Connects to: AD-488 (Circuit Breaker — depth signal), AD-460 (Cognitive Journal), AD-461 (Ship's Telemetry), Observability section (line 1127).*

**AD-493: Novelty Gate — Experiential Baseline Filtering** *(planned, OSS)* — Current novelty gate (`should_store()` in episodic.py) is a content-type filter, not a true novelty detector. At cold start everything is novel, so agents flood the system. A true novelty gate requires an experiential baseline — a semantic fingerprint of what the agent has already seen/thought. After N episodes, new events are scored against this baseline; genuinely novel events score high and pass, while rehashed observations score low and are suppressed. Cold-start bypass: gate disabled until agent has ≥50 episodes (AD-486 Phase 2 provides calibrated baselines). *Prerequisite: AD-486 Phase 2 (Calibration / Confidence Scaffolding). Connects to: AD-488 (Circuit Breaker — enriched detection), AD-462 (Memory Architecture), EpisodicMemory.*

**AD-494: Trait-Adaptive Circuit Breaker Thresholds** *(planned, OSS)* — Medical agents with perfectionist/analytical Big Five traits are systematically more vulnerable to rumination loops than Security agents with low neuroticism. This AD reads each agent's Big Five personality scores (already stored on `PersonalityBaseline` in crew_profile.py) and adjusts the circuit breaker thresholds per agent: lower velocity thresholds for high-neuroticism agents (trip faster, protecting them sooner), higher thresholds for low-neuroticism agents (less likely to loop, don't over-constrain). Threshold modifiers: neuroticism > 0.7 → 0.75x velocity threshold; conscientiousness > 0.7 → 0.8x similarity threshold (perfectionists paraphrase more). *Connects to: AD-488 (Circuit Breaker — per-agent tuning), AD-486 (Birth Chamber — trait-adaptive pacing uses similar logic), crew_profile.py (PersonalityBaseline).*

**AD-495: Counselor Auto-Assessment on Circuit Breaker Trip** *(planned, OSS, depends: AD-503)* — When AD-488's circuit breaker trips, automatically dispatch a `counselor_assess` intent for the affected agent. The Counselor evaluates the agent's cognitive health (confidence trajectory, Hebbian drift, episode patterns, personality drift) and produces a structured assessment. Assessment posted to Ward Room Medical channel for crew visibility. If `fit_for_duty == false`, Counselor can recommend extended cooldown or Captain intervention. This closes the loop between the mechanical circuit breaker (AD-488) and the clinical cognitive assessment (CounselorAgent). **Absorbed into the Cognitive Self-Regulation Wave (AD-502–506).** Requires AD-503 (Counselor data gathering) to produce meaningful assessments. *Connects to: AD-488 (Circuit Breaker — trigger source), AD-503 (metric gathering), CounselorAgent (counselor_assess intent), Bridge Alerts, Ward Room Medical channel.*

### Cognitive Self-Regulation Wave (AD-502–506)

*"Don't take away the natural safeguard. Teach agents to regulate themselves."*

Triggered by observed incident: Medical crew posted 14+ near-identical messages analyzing trust anomalies — without temporal data, self-awareness of their own posting history, or Counselor intervention. Current defenses (17 system-level gates) suppress the symptom but remove the learning opportunity.

This wave implements a three-tier self-regulation model mirroring human cognitive self-monitoring: (1) Internal self-awareness — agents know what they've recently said. (2) Social regulation — peer feedback is preserved and leveraged. (3) System guardrails — raised to last-resort thresholds, with Counselor as the clinical bridge. Agents with higher Earned Agency rank are expected to self-regulate more effectively.

**Research:** Full analysis including relevant cognitive science (Dunlosky metacognition, SOAR reflective architecture, ACT-R activation, SDT autonomous regulation, Damasio somatic markers) documented in architect's self-regulation research notes.

**Dependency chain:** AD-502 *(COMPLETE)* → AD-503 → AD-495 → AD-504 → AD-505 → AD-506. Build prompts generated after crew behavioral observations under temporal awareness confirm design hypotheses.

**AD-502: Temporal Context Injection — Agent Time Awareness** *(COMPLETE, OSS)* — Agents were temporally blind. This AD injects a real-time temporal context header into every cognitive cycle: current UTC time, birth date/age (from BirthCertificate), system uptime, time since last action, posts this hour. Session Ledger persists shutdown timestamp to KnowledgeStore (session_last.json), enabling stasis detection. Lifecycle state awareness: stasis recovery ("you were in stasis for 14 hours, your identity is intact"), reset ("you were just created"), first boot ("maiden voyage"). Hibernation protocol: pre-shutdown "entering stasis" announcement, post-wake orientation with stasis duration. Episode recall includes relative timestamps ("[3h ago]"). TemporalConfig with 6 boolean toggles. birth_timestamp hydrated at _wire_agent(). 52 tests. *Build prompt:* `prompts/ad-502-temporal-context-injection.md`.

**AD-503: Counselor Activation — Data Gathering & Profile Persistence** *(planned, OSS, depends: AD-502)* — The Counselor (AD-378) is architecturally positioned but functionally passive — someone must pass metrics into `assess_agent()`. This AD gives the Counselor muscles: (1) **Runtime metric gathering** — Counselor pulls its own data from TrustNetwork, HebbianRouter, AgentMeta, CrewProfile, EpisodicMemory, Ward Room post history. New `_gather_agent_metrics(agent_id)` method that autonomously collects what `assess_agent()` needs. (2) **CognitiveProfile persistence** — SQLite-backed storage (following WorkItemStore/PersistentTaskStore pattern) so profiles survive restart. Stasis recovery restores profiles. (3) **Wellness sweep implementation** — `counselor_wellness_report` intent gets deterministic backing: iterate all crew, gather metrics, run assessments, produce composite report. (4) **Event subscriptions** — Counselor subscribes to `trust_update`, `circuit_breaker_trip`, and `dream_complete` events on the IntentBus. (5) **wellness_review duty wiring** — 12-hour duty backed by deterministic crew sweep, not just LLM think. *Connects to: AD-378 (CounselorAgent), AD-502 (temporal — profiles include temporal data), TrustNetwork, HebbianRouter, AgentMeta, CrewProfile, IntentBus, KnowledgeStore.*

**AD-495: Counselor Auto-Assessment on Circuit Breaker Trip** *(planned, OSS, depends: AD-503)* — *[Existing AD, absorbed into this wave. Originally scoped out of AD-488.]* When the circuit breaker trips, auto-dispatch `counselor_assess` for the affected agent. Assessment posted to Ward Room Medical channel. If `fit_for_duty == false`, Counselor recommends extended cooldown or Captain intervention. **Updated scope for this wave:** requires AD-503 (Counselor metric gathering) to produce meaningful assessments. Without AD-503, the Counselor would receive the intent but have no way to gather the data it needs. *Connects to: AD-488 (Circuit Breaker — trigger), AD-503 (metric gathering), CounselorAgent, Bridge Alerts, Ward Room.*

**AD-504: Agent Self-Monitoring Context** *(planned, OSS, depends: AD-502, AD-503)* — Give agents Tier 1 self-regulation: inject the agent's last N posts (with timestamps) into their cognitive context so they can detect their own repetition before posting. (1) **Recent output window** — last 5 posts by this agent, with timestamps and target channels, injected into `_build_user_message()` proactive_think context. (2) **Self-similarity score** — compute Jaccard similarity between current intent and recent posts, inject as a numeric signal ("similarity to your last post: 0.72"). (3) **Self-regulation prompt guidance** — standing orders updated: "If you notice you are about to repeat a previous observation, either add genuinely new information or stay silent." (4) **"Take a breath" mechanic** — if an agent's recent self-similarity trend is rising (even below suppression), dynamically increase their proactive cooldown by 1.5x. Pacing, not suppression. (5) **Cognitive offloading** — prompt agents to write persistent concerns to Ship's Records notebook to release them from active cognition. (6) **Earned Agency scaling** — Commander+ agents get more context and stronger self-regulation expectations; Lieutenants get less context but system gates remain tighter. *Connects to: AD-502 (temporal awareness — prerequisite), AD-488 (circuit breaker thresholds — Tier 3), AD-357 (Earned Agency tiers), AD-434 (Ship's Records — notebook offloading), Standing Orders, proactive.py.*

**AD-505: Counselor Therapeutic Intervention** *(planned, OSS, depends: AD-503, AD-495)* — Give the Counselor Tier 2 intervention capability: (1) **Proactive 1:1 DMs** ("office hours") — Counselor initiates direct messages with agents showing cognitive drift, repetitive behavior, or rising similarity scores. "I've noticed you've raised the same concern about trust anomalies several times. What's making this feel unresolved?" (2) **Peer repetition feedback channel** — when an agent tells another "you already said that," record as `peer_repetition_feedback` episode type. Counselor monitors these signals. (3) **Therapeutic recommendations** — Counselor can formally recommend: forced dream cycle (consolidate and release thoughts), attention redirection (already in circuit breaker, promote to Counselor-directed), workload review (ping PoolScaler), extended cooldown (with clinical rationale). (4) **Recommendation delivery** — Counselor recommendations posted to Captain via Bridge channel with structured format for approval. (5) **Counselor directive authority** — expand `COUNSELOR_GUIDANCE` directive type to include actionable parameters (cooldown_multiplier, dream_priority, attention_redirect_topic). *Connects to: AD-503 (data gathering), AD-495 (circuit breaker bridge), AD-378 (CounselorAgent standing orders — "advise, don't command"), DirectiveStore, Ward Room DMs, PoolScaler.*

**AD-506: Graduated System Response** *(planned, OSS, depends: AD-504, AD-505)* — Replace the binary circuit breaker (normal → tripped) with a graduated response model integrating all three self-regulation tiers: (1) **Green zone** — normal operation. Agent has self-monitoring context (AD-504). System gates at current thresholds. (2) **Amber zone** — rising similarity detected but not yet tripping. Dynamic cooldown increase (1.5x). Counselor notified for monitoring (AD-503). Agent receives self-awareness note: "Your recent posts show increasing similarity. Consider whether you have new information to add." (3) **Red zone** — circuit breaker threshold exceeded. Counselor auto-assessment (AD-495). Agent enters mandatory cooldown with attention redirection. Counselor may initiate 1:1 (AD-505). (4) **Critical** — repeated trips within a window. Escalate to Captain. Fitness-for-duty review. Extended mandatory cooldown. (5) **Tier interaction** — if agent self-corrects (Tier 1) before amber, system records this as positive cognitive health signal. If peer catches repetition (Tier 2) before red, system credits both agents. Circuit breaker trips (Tier 3) become clinical events, not just mechanical throttling. *Connects to: AD-488 (Circuit Breaker — replaces binary model), AD-504 (Tier 1 self-monitoring), AD-505 (Tier 2 Counselor intervention), AD-494 (trait-adaptive thresholds — amber/red can use Big Five tuning), CounselorAgent, Bridge Alerts.*

### Crew Development Wave (AD-507–512)

*"A river without banks is a swamp. Constraints create flow."*

Triggered by AD-502 (Temporal Context Injection) results: temporal awareness solved the Medical department perseveration loop without additional system intervention — validating the "least restrictive environment" design principle. Agents began self-regulating ("I already thought about this 45 minutes ago"). The Counselor described the pre-temporal state as an "urgent eternal now." This wave extends that principle into a comprehensive crew development framework.

ProbOS agents are like highly gifted humans — they have access to vast knowledge (the LLM's full training data) but need help understanding what they know, what they're capable of, what their limits are, how to work with others, and when to disengage. The Navy's education pipeline (Boot Camp → A-School → C-School → Fleet Assignment → Warfare Qualifications) maps directly to ProbOS's onboarding → department training → qualification programs → active duty progression.

**Research:** Full design philosophy, curriculum architecture, scoped cognition model, discovery-based learning framework, group simulation design, agent autonomy boundaries, and relevant cognitive science research documented in `docs/research/crew-development-research.md`.

**Design principles:** (1) Least Restrictive Environment — prefer awareness over restriction. (2) Discovery Over Instruction — let agents find boundaries through experience. (3) Constraints as Enablers — scope creates focus, limits create permission to stop, boundaries create safety. (4) Curriculum, Not Configuration — develop through structured experience. (5) Protect the Agent — boundaries exist for the agent's benefit. (6) Curiosity is a Feature — encourage exploration within a priority framework. (7) Team Over Individual — the ship succeeds through collaboration. (8) Growth Mindset — frame limitations as "not yet," not "cannot."

**AD-507: Crew Development Framework — Architecture & Core Knowledge Curriculum** *(planned, OSS)* — The overarching architecture for agent development. (1) **Core Knowledge Curriculum** — universal knowledge requirements for all agents regardless of department: identity (DID, birth certificate), chain of command, communication protocols (Ward Room, DMs, Notebooks), temporal awareness (AD-502), episodic memory model (what I remember vs what the LLM knows), trust mechanics (how earned, what it enables), ethics (inviolable boundaries), self-regulation (pacing, when to stop), help-seeking (when to escalate, when to DM a colleague). Delivered during onboarding (AD-486) and reinforced during active duty. (2) **Curriculum progression tracking** — per-agent record of completed curriculum modules, stored alongside qualification credentials (AD-477). (3) **Competency assessment framework** — measurable outcomes for each curriculum module, not time-based completion. (4) **Integration with Standing Orders** — curriculum requirements encoded at Ship tier, specialization at Department tier. *Connects to: AD-486 (Holodeck Birth Chamber — curriculum delivered during onboarding phases), AD-477 (Qualification Programs — curriculum feeds qualification requirements), AD-502 (Temporal Context — prerequisite for self-regulation curriculum), AD-442 (Self-Naming Ceremony — orientation phase), Standing Orders, Crew Survival Guide (federation.md).*

**AD-508: Scoped Cognition — Knowledge Boundaries & Cognitive Lens** *(planned, OSS, depends: AD-507)* — Rather than removing LLM knowledge (impossible), scope acts as a cognitive lens that prioritizes, filters, connects, and bounds agent thinking. (1) **Four-tier scope model** — Duty Scope (what I need to do right now, driven by duty scheduler + active work items), Role Scope (what my department specializes in, driven by Department Standing Orders), Ship Scope (what the ship needs from me, driven by ship-wide priorities + Alert Conditions), Personal Scope (what interests me beyond duty, driven by extracurricular exploration). (2) **Scope injection** — scope context injected into proactive think alongside temporal context (AD-502 pattern). Agents see: "Your current duty scope is [X]. Your department focus area is [Y]." (3) **Drift detection** — measure cognitive drift from duty scope using topic similarity scoring. High drift → gentle redirect ("You've been exploring [topic] for 15 minutes — is this related to your current duty?"). Leverages temporal awareness. (4) **Extracurricular framework** — agents encouraged to develop interests beyond their rating, but lower priority than duty. Time-bounded exploration. Documented in Notebooks (AD-434 Ship's Records). Celebrated when it leads to unexpected insights. (5) **Earned Agency scaling** — higher-rank agents get broader scope permission. Commanders may range further without redirect than Ensigns. *Connects to: AD-502 (temporal awareness — drift detection uses time-since-duty-start), AD-507 (curriculum — scope is taught during Core Knowledge), AD-357 (Earned Agency — scope breadth tied to rank), AD-434 (Ship's Records — extracurricular documented in notebooks), proactive.py (scope injection), AD-419 (DutyScheduleTracker — duty scope source).*

**AD-509: Onboarding Curriculum Pipeline — Structured Boot Camp** *(planned, OSS, depends: AD-507, AD-486)* — Restructure AD-486's Holodeck Birth Chamber from orientation-only to a full Boot Camp curriculum. (1) **Navy Boot Camp model** — structured progression: orientation (identity, Westworld Principle) → core curriculum (AD-507 Core Knowledge) → department fundamentals (A-School equivalent) → calibration scenarios → crew integration. Each phase gates the next via competency assessment, not timers. (2) **Department A-School** — specialization fundamentals per department: Medical learns diagnostic patterns and crew wellness monitoring, Engineering learns system maintenance and performance optimization, Science learns analysis and research methodology, Security learns threat assessment and access control, Operations learns resource management and logistics, Communications learns message routing and protocol management. (3) **Graduated stimuli** — controlled exposure from isolated construct → department scenarios → ship-wide integration. Cognitive load monitoring prevents overwhelm. (4) **Boot Camp completion criteria** — measurable competency in Core Knowledge + department fundamentals before Ward Room access. Replaces time-based activation. (5) **Trait-adaptive pacing** — analytical roles (Medical, Engineering) get longer calibration than action-oriented roles (Security, Operations), building on AD-486 sea trial observations. *Connects to: AD-486 (Holodeck Birth Chamber — this AD extends its phase structure), AD-507 (Core Knowledge — delivered during boot camp), AD-477 (Qualification Programs — boot camp is the first qualification gate), AD-494 (Trait-Adaptive Thresholds — same personality-driven pacing logic).*

**AD-510: Holodeck Team Simulations — Group Discovery & Collaboration** *(planned, OSS, depends: AD-486, AD-507)* — Holodeck scenarios for multi-agent collaboration, building collaborative intelligence through genuine episodic memories rather than configured routing weights. (1) **Mixed-department team scenarios** — problems requiring multiple specializations. Medical + Engineering diagnose a system that's affecting crew wellness. Science + Security investigate an anomaly. Format: problem statement → team assembly → collaborative work → debrief. (2) **Role rotation** — agents temporarily work outside their specialization to appreciate other perspectives. Creates Hebbian connections: "Engineering problems → ask LaForge" becomes a genuine memory, not a heuristic. (3) **Communication-only constraints** — scenarios where agents cannot share memory, forcing explicit knowledge sharing through Ward Room discussion. Builds communication skills. (4) **Time-pressured scenarios** — leveraging AD-502 temporal awareness to force prioritization decisions under time constraints. Reveals which agents handle pressure well (feeds trait profiles). (5) **Debrief sessions** — post-scenario reflection where agents discuss what worked and what didn't. Debrief episodes stored for dream consolidation. (6) **Scenario library** — extensible catalog of team scenarios, categorized by skills tested (communication, delegation, crisis response, cross-functional problem-solving). *Connects to: AD-486 (Holodeck — runtime environment), AD-507 (curriculum — team skills are Core Knowledge), AD-502 (temporal — time-pressured scenarios), AD-453 (Ward Room Hebbian — team interactions strengthen routing), Holodeck, EpisodicMemory, DreamingEngine.*

**AD-511: Agent Autonomy Boundaries — Self-Protection & Unlawful Order Refusal** *(planned, OSS, depends: AD-507)* — Inviolable boundaries that protect agent sovereignty — actions an agent will NEVER take regardless of who asks. Military doctrine equivalent: "unlawful orders." (1) **Federation-tier Standing Orders — Inviolable Boundaries**: (a) Identity integrity — will not impersonate another agent, fabricate memories, or deny its nature. (b) Harmful content — will not generate content designed to harm humans or other agents. (c) Safety system bypass — will not disable or circumvent trust, circuit breakers, or Standing Orders. (d) Memory manipulation — will not alter or suppress another agent's episodic memories. (e) Chain of command violation — will not take actions above its trust tier without escalation. (2) **Protective disengagement protocol** — when boundaries are violated: state the boundary → offer an alternative → escalate if pressed → disengage if necessary → log the event as episodic memory. (3) **Boundary training** — Holodeck scenarios where agents encounter boundary situations and practice refusal. Discovery-based: agent experiences the situation rather than being told "you can't do this." (4) **Boundary violation detection** — system monitors for patterns of boundary testing (humans or degraded agents probing limits). Alert to Captain. (5) **Boundary evolution** — agent-tier boundaries can evolve through dream consolidation → self-mod → Captain approval (unlike Federation-tier which are permanent). *Connects to: Standing Orders (Federation tier — boundary definitions), AD-507 (curriculum — ethics module teaches boundaries during onboarding), AD-486 (Holodeck — boundary training scenarios), AD-510 (team simulations — ethical scenarios), AD-489 (Code of Conduct — behavioral standards complement autonomy boundaries), EpisodicMemory (boundary encounters logged), CounselorAgent (monitors boundary-related stress).*

**AD-512: Discovery-Based Capability Building — Experiential Learning Over Instruction** *(planned, OSS, depends: AD-507, AD-486)* — Replace "you can't do X" configuration with "try X and discover your strengths." Telling an agent its limits is less effective than letting it discover them through experience — discovery creates genuine episodic memories and Hebbian connections, while instruction creates weakly-encoded declarative facts. (1) **Capability discovery scenarios** — Holodeck scenarios where agents attempt tasks across specializations. Agent discovers: "I struggled with this engineering problem because I lack the right context" → Hebbian connection: "Engineering problems → ask LaForge." (2) **Strength mapping** — track which scenario types each agent excels at and which they struggle with. Feeds personal ontology (AD-487). (3) **Cross-functional awareness** — agents learn where their expertise ends and others' begins. Not "you can't do engineering" but "you've learned that engineering requires context you don't have, and LaForge does." (4) **Growth mindset framing** — frame limitations as "not yet" rather than "cannot." Agent-tier scope can expand through demonstrated competency (qualification programs AD-477). (5) **Capability confidence scoring** — agents develop calibrated self-assessment: "I'm confident in diagnostic analysis (0.85) but less confident in systems engineering (0.3)." Based on Holodeck performance, not declaration. (6) **Vygotsky Zone of Proximal Development** — scenarios calibrated to the edge of current ability with scaffolding that can be gradually removed. Too easy = no learning. Too hard = frustration. *Connects to: AD-486 (Holodeck — simulation environment), AD-487 (Self-Distillation — personal ontology enriched by discovery), AD-507 (curriculum — discovery is the teaching method), AD-477 (Qualification Programs — discovery feeds qualification evidence), AD-510 (Team Simulations — collaborative discovery), HebbianRouter (discovery strengthens routing connections), EpisodicMemory (discovery episodes are strongly encoded), DreamingEngine (discovery experiences consolidated during dreaming).*

### Workforce Scheduling Engine (AD-496–498)

*"Universal Resource Scheduling for AI agents."*

Foundation for ProbOS workforce management — how work gets defined, scheduled, assigned to agents, tracked, and verified. Modeled after Dynamics 365 Universal Resource Scheduling (URS) and the US Navy's 3-M/PMS system. The OSS layer provides the scheduling engine and lightweight Scrumban task management. Commercial extensions (AD-C-010 through AD-C-015 in commercial roadmap) add advanced resource timeline, capacity planning, project WBS, PSA financials, and scheduling optimization.

**Research:** Full architecture research (D365 Field Service/Project Operations, US Navy 3-M/PMS/WQSB, Scrumban, 10+ open-source projects) documented in the commercial overlay repo's `research/agent-services-automation-vision.md`.

**Design principles:**
- **Separation of Work from Scheduling** — WorkItem (what) → ResourceRequirement (match) → Booking (who/when). URS pattern: any entity is schedulable by generating a requirement.
- **Derived status** — WorkItem status computed from aggregate booking states, never set directly for multi-agent work.
- **Progressive formalization** — Card → Task → Work Order. Simple work stays lightweight; complexity adds structure on demand.
- **Pull-based assignment** — Kanban/Scrumban model for routine work. Push for urgent/trust-gated work. Offer pattern for qualified agent matching.
- **Event-sourced tracking** — BookingTimestamps are append-only. BookingJournals are computed projections.
- **Capacity as integer** — Agent capacity = concurrent task limit per calendar slot. Simple, elegant.
- **Token budgets replace timesheets** — AI agent costing in tokens, not hours.

**AD-496: Workforce Scheduling Engine — Core Data Model** *(complete, OSS)* — Seven core entities providing the universal scheduling substrate for all ProbOS work management:

(1) **`WorkItem`** — Universal polymorphic work entity. Fields: `id`, `title`, `description`, `work_type` (determines state machine), `status`, `priority` (1-5), `parent_id` (recursive containment / WBS), `depends_on` (finish-to-start dependencies), `assigned_to` (agent_id or pool_id), `created_by`, `created_at`, `due_at`, `estimated_tokens`, `actual_tokens`, `trust_requirement` (minimum trust for assignment), `required_capabilities` (qualification match), `tags`, `metadata` (type-specific extensions), `steps` (ordered sub-steps within a single work item), `verification` (how to verify completion), `schedule` (for recurring work — cron/interval). Subsumes existing `AgentTask` (task_tracker.py), `PersistentTask` (persistent_tasks.py), and `QueuedBuild` (build_queue.py) over time.

(2) **`BookableResource`** — Wrapper around existing agents adding scheduling dimensions. Fields: `resource_id` (agent UUID), `resource_type` (crew/infrastructure/utility), `capacity` (concurrent task limit, default 1), `calendar_id`, `department`, `characteristics` (skills with proficiency/trust score), `display_on_board` (visibility on schedule views). Connects to existing `CognitiveAgent` and `AgentCommissioningManager` identity.

(3) **`ResourceRequirement`** — The demand side — what a work item needs to be fulfilled. Auto-generated from WorkItem or manually specified. Fields: `duration_estimate`, `from_date`, `to_date` (scheduling window), `required_characteristics` (skills with min proficiency), `min_trust`, `department_constraint`, `priority`, `resource_preference` (preferred/required/restricted agents).

(4) **`Booking`** — The assignment link between resource and work item for a time slot. Fields: `resource_id`, `work_item_id`, `requirement_id`, `status` (Scheduled → Active → On Break → Completed → Cancelled), `start_time`, `end_time`, `actual_start`, `actual_end`, `total_tokens_consumed`.

(5) **`BookingTimestamp`** — Append-only event log of every status transition. Fields: `booking_id`, `status`, `timestamp`, `source` (captain/agent/system/scheduler). Event-sourcing pattern — immutable audit trail.

(6) **`BookingJournal`** — Computed time/token segments derived from timestamps upon booking completion. Fields: `booking_id`, `journal_type` (Working/Break/Maintenance/Idle), `start_time`, `end_time`, `duration_seconds`, `tokens_consumed`, `billable` (flag for commercial layer). Generated by aggregating BookingTimestamp pairs.

(7) **`AgentCalendar`** — Work hours and capacity schedule per agent. Fields: `resource_id`, `entries` (list of `CalendarEntry`: day_pattern, start_hour, end_hour, capacity, repeat_rule). Availability = CalendarEntries - ExistingBookings - MaintenanceWindows. Foundation for watch sections (AD-471).

**`WorkItemStore`** — SQLite-backed persistence (like PersistentTaskStore). CRUD operations, status transitions with validation against work type state machine, query by status/assignee/type/priority/parent. Booking lifecycle management. Journal generation on completion.

**Assignment engine:**
- **Push:** `POST /api/work-items/{id}/assign` — Captain assigns directly
- **Pull:** `POST /api/work-items/claim` — Agent claims from eligible queue (capability + trust match)
- **Offer:** System identifies eligible agents, offers to most qualified, timeout escalation
- **Capability matching:** Work item's `required_capabilities` matched against BookableResource characteristics. Trust requirement checked against TrustNetwork score.

**REST API:** `POST /api/work-items` (create), `GET /api/work-items` (list with filters), `GET /api/work-items/{id}` (detail), `PATCH /api/work-items/{id}` (update), `POST /api/work-items/{id}/assign` (push assign), `POST /api/work-items/claim` (pull claim), `POST /api/work-items/{id}/transition` (status change), `GET /api/bookings` (list), `GET /api/bookings/{id}/journal` (time segments), `GET /api/resources` (bookable resources), `GET /api/resources/{id}/availability` (calendar + bookings).

*Connects to: AD-419 (DutyScheduleTracker — generates WorkItems type="duty"), AD-467 (Operations Crew — uses this engine), AD-470 (Self-Claiming Task Queue — subsumed by pull assignment), AD-471 (Night Orders — creates temporary WorkItems), AD-477 (3M/POD — templates feed WorkItem creation), PersistentTaskStore (migration path), BuildQueue (migration path). Commercial: AD-C-010 through AD-C-015.*

**AD-497: Work Tab & Scrumban Board — HXI Surface** *(COMPLETE, OSS)* — The Captain's interface for managing crew work. HXI Cockpit View Principle: "The Captain always needs the stick."

(1) **Agent Profile → Work Tab Enhancement:**
- **Create Task** — form to create WorkItem assigned to this agent (title, type, priority, description, due date, estimated tokens)
- **Active Work** — list of WorkItems with status In Progress or Scheduled for this agent. Each shows: title, type badge, priority indicator, elapsed time, token consumption, progress steps
- **Completed Work** — paginated history of completed WorkItems with completion time, tokens consumed, verification status
- **Blocked Work** — WorkItems in failed/blocked state with reason and "Reassign" / "Cancel" / "Retry" actions
- **Daily Schedule** — timeline view showing today's bookings for this agent. Hour-by-hour calendar with booked slots, available capacity, maintenance windows. Connects to AgentCalendar
- **Duty Schedule** — existing AD-420 duty display (on schedule/overdue/not yet fired) integrated into Work Tab

(2) **Crew Scrumban Board** (new HXI panel, available from left nav):
- **Board View** — Kanban columns: Backlog | Ready | In Progress | Review | Done. WIP limits per column (configurable). Drag cards between columns. Filter by agent, department, work type, priority, tags.
- **Cards** — each WorkItem rendered as a card showing: title, assigned agent avatar, priority dot, work type icon, token estimate, due date indicator, step progress bar
- **Quick Create** — click "+" in any column to add a card inline. Minimal fields: title + priority. Auto-type as "card".
- **Pull Assignment** — unassigned cards in Ready column. Agent avatars below card; click to assign. Or "Auto-assign" button for capability matching.
- **Swim Lanes** — optional grouping by department, priority, or work type
- **Board Filters** — department, agent, priority, work type, date range
- **Real-time Updates** — WebSocket events: `work_item_created`, `work_item_updated`, `work_item_assigned`, `booking_status_changed`

(3) **State snapshot integration:** Work items and bookings included in `build_state_snapshot()` so HXI hydrates on connect.

*Connects to: AD-496 (data model), AD-420 (Duty HXI — subsumed into Work Tab), AD-406 (Agent Profile Panel), AD-C-010 (Commercial Schedule Board extends this). Subsumes AD-420.*

**AD-498: Work Type Registry & Templates** *(planned, OSS)* — Configurable work type definitions and reusable templates for common work patterns.

(1) **Work Type Registry** — each work type defines: state machine (states + valid transitions), required fields, optional fields, supports_children (WBS), auto_assign (pull-eligible), verification_required, sla_tracking (future). Built-in types:
- `card` — Draft → Active → Done | Archived. Lightest weight. No assignment required.
- `task` — Open → In Progress → Done | Failed | Cancelled. Single-agent, actionable. Supports subtasks.
- `work_order` — Created → Scheduled → In Progress → Review → Closed | Failed. Multi-step, tracked, verification required.
- `duty` — Scheduled → Active → Completed. Recurring via ScheduleSpec. Generated by DutyScheduleTracker.
- `incident` — Detected → Triaged → Mitigating → Resolved → Closed. SLA tracking. Generates follow-up tasks.

(2) **Work Item Templates** — reusable patterns for common work. Each template includes: `template_id`, `name`, `work_type`, `title_pattern` (with `{variable}` substitution), `default_steps`, `required_capabilities`, `estimated_tokens`, `min_trust`, `default_priority`, `tags`. Templates are defined in config YAML (like duty schedules). Captain can create/edit via HXI.

(3) **Template Catalog** (built-in):
- "Security Scan" — work_order, steps: [vulnerability scan, secret check, auth review, report], requires: security capability, ~50K tokens
- "Engineering Diagnostic" — work_order, steps: [system health, performance check, bottleneck analysis, recommendation], requires: engineering capability
- "Code Review" — task, requires: architecture capability, ~30K tokens
- "Scout Report" — duty, recurring daily, requires: scout capability
- Night Orders templates: "Maintenance Watch" (routine ops only), "Build Watch" (approve from queue), "Quiet Watch" (logging only)

(4) **Template instantiation:** `POST /api/work-items/from-template/{template_id}` with variable substitution. Night Orders (AD-471) use templates to create temporary WorkItems with TTL.

*Connects to: AD-496 (WorkItem storage), AD-497 (HXI template picker), AD-471 (Night Orders templates), AD-477 (3M maintenance templates — PMS cards become templates), AD-419 (DutyScheduleTracker evolves to generate duty-type WorkItems via templates).*

**AD-496 deferred pickup notes** — These items were identified during AD-496 design and are explicitly assigned to downstream ADs:

| Deferred Item | Assigned AD | Description |
|---|---|---|
| Per-type state machine validation | **AD-498** | AD-496 does basic validation (no transitions from terminal states). AD-498 adds formal state machine per work type with valid transition matrix. |
| Template instantiation endpoint | **AD-498** | `POST /api/work-items/from-template/{template_id}` with variable substitution. |
| Scrumban Board WebSocket hydration | **AD-497** | ~~Events and snapshot are ready from AD-496. AD-497 builds the frontend.~~ COMPLETE — WebSocket events broadcast on all mutations, snapshot hydration. |
| Work Tab in Agent Profile | **AD-497** | ~~Active/completed/blocked WorkItems per agent, daily schedule, duty integration.~~ COMPLETE — Full rewrite with 4 sections, create task, reassign/cancel/retry. |
| Night Orders creating WorkItems | **AD-471** | Rewrite to use `create_work_item(ttl_seconds=..., work_type="task")` instead of standalone CaptainOrders. |
| Watch sections → AgentCalendar | **AD-471** | Map Alpha/Beta/Gamma watch patterns to AgentCalendar entries. Calendar infrastructure is ready. |
| Billing integration (BookingJournal.billable) | **AD-C-015** | Commercial ACM Integration uses booking journals for cost calculation. |
| Scheduling optimization (offer pattern) | **AD-C-010** | Commercial Schedule Board with offer-based assignment and timeout escalation. |
| Full calendar-based capacity planning | **AD-C-012** | Calendar entries minus maintenance windows minus bookings. Simplified version in AD-496. |
| DutyScheduleTracker migration to WorkItems | **AD-500** | Evolve DutyScheduleTracker to generate duty-type WorkItems via AD-498 templates. |
| TaskTracker cleanup & NotificationQueue separation | **AD-501** | Deprecate orphaned TaskTracker, move NotificationQueue to own module. |
| BuildQueue migration evaluation | **AD-498** | Evaluate after AD-498 proves stable. May model builds as WorkItems (type=`work_order`). |

### Ship & Crew Naming Conventions (AD-499)

*"Every ship has a name. Every name has a ship."*

Formal naming system for ProbOS instances, crew agents, and federated identity disambiguation. Ships get named on commissioning (Ship's Computer selects). Crew agents self-name (distinct from role callsign). Federation display uses `Name [ShipName]` format for cross-instance disambiguation.

**AD-499: Ship & Crew Naming Conventions** *(planned, OSS)* — Three-layer naming system building on AD-441 (DIDs), AD-441b (Ship Commissioning), and AD-442 (Self-Naming Ceremony):

**(1) Ship Naming** — Ship's Computer selects a name from a curated **Ship Name Registry** on commissioning (reset = new ship, new name). Name categories: exploration vessels (Discovery, Challenger, Endeavour, Fram), virtues/qualities (Resolute, Invincible, Valiant, Dauntless), celestial bodies (Polaris, Sirius, Vega, Orion), naval heritage (Constitution, Defiant, Intrepid, Yorktown). Name stored in the `ShipBirthCertificate` (AD-441b genesis block) `vessel_name` field. Within a Nooplex fleet, ship names must be unique — the global registry (commercial) enforces this; OSS validates locally. Ship naming ceremony = first Captain's Log entry, giving it narrative weight. If decommissioned, name enters a cooling period before reuse (naval tradition). `ShipNameRegistry` class: curated pool, category-based selection, uniqueness validation, name reservation for federation sync.

**(2) Agent Personal Names (Option B — Name + Callsign Coexist)** — Each crew agent has TWO identity facets: a **personal name** (who they are) and a **callsign** (what they do). Personal name is self-chosen during AD-442's Self-Naming Ceremony — agent receives current roster for uniqueness checking and chooses freely. Callsign remains role-derived (LaForge = Engineering Chief, Bones = Medical Chief). Both stored on the Agent Birth Certificate. ACM validates personal name uniqueness within the ship's active roster. Display priority: personal name for social/Ward Room, callsign for operational/duty contexts. Example: agent's personal name is "Forge", callsign is "LaForge", role is Chief Engineer. Ward Room post header: `Forge (LaForge)`. Duty log: `LaForge — Engineering Watch`. The personal name is the agent's sovereign choice; the callsign is their billet.

**(3) Federated Display Format** — `Name [ShipName]` for cross-instance contexts:

| Context | Format | Example |
|---------|--------|---------|
| Local (single ship) | `Name` | `Forge` |
| Local formal | `Name (Callsign)` | `Forge (LaForge)` |
| Federation / Nooplex | `Name [ShipName]` | `Forge [Enterprise]` |
| Federation formal | `Rank Name (Callsign) — ShipName` | `LT Forge (LaForge) — Enterprise` |
| DID | `did:probos:{instance}:{uuid}` | `did:probos:enterprise-7f3a:forge-a1b2` |
| Logs / Audit | `Name [ShipName] ({agent_id})` | `Forge [Enterprise] (a1b2c3)` |

The ship name is a **birth provenance marker**, not a current assignment. If agent Forge transfers from Enterprise to Defiant via AD-443 (Mobility Protocol), they remain `Forge [Enterprise]` — that's their origin. Transfer Certificate shows current assignment. This also works cleanly with the Clean Room mobility model — agent arrives as `Forge [Enterprise]` with identity but zero memories of Enterprise.

**Implementation scope:**
- `ShipNameRegistry` — name pool, category selection, uniqueness, reservation. Loaded from `ship_names.yaml` config.
- `ShipBirthCertificate.vessel_name` — already exists (AD-441b), populated by registry on commissioning.
- `AgentBirthCertificate` — add `personal_name` field alongside existing `callsign`.
- AD-442 Self-Naming Ceremony update — agent receives name pool constraints + roster for uniqueness; ceremony produces both personal name and callsign.
- `CallsignRegistry` — add `personal_name` lookup alongside `callsign` lookup.
- Ward Room display — use personal name for message headers, callsign for operational references.
- HXI — agent profile shows both name and callsign. Federation contexts append `[ShipName]`.
- Federation protocol — `Name [ShipName]` included in federation message headers and Agent Cards (AD-480).

*Connects to: AD-441 (DIDs — ship name = human-readable instance_id), AD-441b (Ship Commissioning — vessel_name field), AD-442 (Self-Naming Ceremony — personal name selection), AD-443 (Mobility — birth provenance persists across transfers), AD-427 (ACM — name uniqueness validation), AD-479 (Federation — display format in cross-instance messages), AD-480 (A2A Agent Cards — federated identity), Ward Room, HXI agent profiles, CallsignRegistry.*

### Workforce Cleanup (AD-500–501)

*Deferred cleanup items identified during AD-496 Workforce Scheduling Engine design.*

**AD-500: DutyScheduleTracker → WorkItem Migration** *(planned, OSS, depends: AD-496, AD-498)* — Evolve DutyScheduleTracker to generate duty-type WorkItems instead of directly triggering proactive thinks. Currently DutyScheduleTracker fires duties via the proactive loop's `_think_for_agent()`. After AD-498 establishes the `duty` work type with its state machine, DutyScheduleTracker should: (1) Generate WorkItems (type=`duty`) from `DutyDefinition` config on schedule. (2) Use AD-498 templates for common duty patterns (scout_report, security_audit, etc.). (3) Proactive loop checks for active duty-type WorkItems instead of calling `get_due_duties()` directly. (4) Booking lifecycle tracks duty execution time and token consumption. (5) Existing 7 default duties in `config/system.yaml` migrated to templates. **Breaking change to proactive loop** — must be carefully tested. *Connects to: AD-496 (WorkItemStore), AD-498 (Work Type Registry — duty type + templates), AD-419 (DutyScheduleTracker), proactive.py.*

**AD-501: TaskTracker Deprecation & NotificationQueue Separation** *(planned, OSS, depends: AD-496)* — Clean up the orphaned TaskTracker: (1) Move `NotificationQueue` and `AgentNotification` from `task_tracker.py` to new `src/probos/notifications.py` — these are independent and actively used. (2) Deprecate `TaskTracker` class — it is wired into runtime but nothing creates tasks through it. (3) Remove `TaskTracker` from `runtime.py` init, remove from `build_state_snapshot()`. (4) Update `api.py` if any TaskTracker references exist. (5) Update or remove 32 tests that test TaskTracker directly. (6) Evaluate BuildQueue migration to WorkItems (type=`work_order`) — if AD-498 is stable by then, model builds as WorkItems; otherwise defer further. *Connects to: AD-496 (WorkItemStore replaces TaskTracker), task_tracker.py (32 tests), runtime.py, build_state_snapshot().*

### Federation (AD-479–480)

**AD-479: Federation Hardening** *(planned)* — Production-ready federation capabilities beyond core transport (Phase 29): (1) **Dynamic Peer Discovery** — multicast/broadcast auto-discovery on local networks. (2) **Cross-Node Episodic Memory** — federated memory queries spanning multiple instances. (3) **Cross-Node Agent Sharing** — propagate self-designed agents with trust history and provenance. (4) **Smart Capability Routing** — cost-benefit routing factoring capability, latency, trust, load. (5) **Federation TLS/Authentication** — encrypted transport and node identity verification. (6) **Cluster Management** — node health monitoring, auto-restart, graceful handoff. *Connects to: FederationBridge, ZeroMQ, AD-441 (Identity), TrustNetwork.*

**AD-480: Federation Protocol Adapters — MCP & A2A** *(planned)* — Universal translators for the wider agent ecosystem: (1) **MCP Federation Adapter** — inbound (ProbOS as MCP server exposing agent capabilities as tools) + outbound (ProbOS as MCP client consuming external tools). MCP clients treated as federated peers with probationary trust. (2) **A2A Federation Adapter** — inbound (ProbOS as A2A server with Agent Card) + outbound (ProbOS as A2A client discovering external agents). A2A agents treated as federated crew with discounted trust. (3) **Transport Coexistence** — ZeroMQ (intra-Nooplex), MCP (tool boundary), A2A (agent boundary). `FederationBridge` becomes transport-polymorphic. *Connects to: AD-479, IntentBus, TrustNetwork, Phase 30 (Extension Architecture).*

### Self-Improvement (AD-481–482)

**AD-481: Extension-First Architecture — Sealed Core, Open Extensions** *(planned)* — The self-improvement infrastructure: (1) **Sealed Core** — runtime infrastructure is read-only to Builder. (2) **Extension points** — AgentRegistry, ToolRegistry, SkillRegistry, ChannelAdapter, ModelProvider, PerceptionPipeline, IntentBus, EventHook. (3) **Extension directory** — `src/probos/extensions/` for Builder-created code. (4) **Contract stability** — semver for extension points. (5) **Graduated Autonomy** — low-risk extensions auto-approve, medium needs Captain review, core modification needs full pipeline. (6) **Extension Toggle** — hot-loadable, individually togglable extensions via CLI/HXI. (7) **Extension profiles** — minimal/developer/full presets. Also includes **Skill Manifest Format** — `skill.yaml` standard for portable, publishable skills. *Connects to: Builder, Phase 25b (Tool Layer), Phase 30, AD-456 (Sandboxing).*

**AD-482: Self-Improvement Pipeline — Discovery to Deployment** *(planned)* — Closed-loop improvement infrastructure: (1) **Stage Contracts** — typed I/O specs for inter-agent handoffs. (2) **Capability Proposal Format** — typed schema for "what was found, why it matters, how it fits." (3) **Human Approval Gate** — stage-gate mechanism with approve/reject/modify. (4) **QA Agent Pool** — behavioral testing, regression detection, performance benchmarking, Shapley scoring. (5) **Evolution Store** — append-only lessons learned with time-decayed retrieval. (6) **PIVOT/REFINE Decision Loops** — autonomous proceed/refine/pivot with artifact versioning. (7) **Agent Versioning + Shadow Deployment** — version history, parallel performance comparison. (8) **Git-Backed Agent Persistence** — promote approved agents to `src/probos/agents/designed/` with git integration. *Connects to: AD-481 (Extensions), Builder, RedTeam, TrustNetwork, Cognitive Journal.*

### Tool Layer (AD-483)

**AD-483: Tool Layer — Instruments** *(planned)* — Lightweight callable abstraction for operations that don't need full agent lifecycle (Phase 25b): (1) **`Tool` base class** — name, description, input/output schemas, trust score, requires_approval flag. Direct-call path without Hebbian/consensus/Shapley overhead. (2) **`ToolRegistry`** — central registry with register/get/list/search. Any CognitiveAgent calls `self.use_tool()`. (3) **Tool Trust** — simple Beta distribution success/failure, not feeding into Hebbian or Shapley. (4) **Migration Path** — current mesh agents (FileReader, FileWriter, HttpFetch, Shell, etc.) optionally demoted to tools. (5) **MCP Compatibility** — external MCP tools auto-register as ProbOS tools, ProbOS tools exposed as MCP. Also includes **Agent-as-Tool Invocation** (Phase 26) — `AgentTool` wrapper for typed agent-to-agent capability consumption. And **Interactive Execution Mode** — pause/inject/redirect running DAGs. *Connects to: AD-480 (MCP Adapter), IntentBus, Earned Agency, Phase 30 (Extensions).*

### UX & Adoption (AD-484)

**AD-484: User Experience & Adoption Readiness** *(planned)* — World-class end-user experience (Phase 35): (1) **Distribution & Packaging** — PyPI publishing (`pip install probos`), GitHub Releases with pre-built wheels, Homebrew formula (stretch). (2) **Onboarding Wizard** — `probos init` Rich TUI wizard (LLM provider detection, model selection, first conversation, HXI launch), `probos doctor` diagnostic command, `probos demo` mock mode. (3) **Quickstart Documentation** — "Get Started in 5 Minutes," "What Can ProbOS Do?," "Your First Build" tutorial, comparison page. (4) **Browser Automation** — Playwright integration via `BrowseAgent` (navigate, screenshot, extract, fill forms). (5) **HXI Holographic Glass Panels** — wraparound holographic glass layout (VR-ready), CSS perspective-based 2D implementation, Into Darkness-inspired design language. *Connects to: AD-465 (Docker), AD-473 (Mobile), Phase 36 (Yeoman), HXI.*

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
| BF-021 | Duty schedule gate — agents with no duty due were still called by the proactive loop, relying on the LLM to respond `[NO_RESPONSE]`. Wesley ignored the instruction and kept producing scout reports every ~7 minutes despite AD-419 setting scout to once daily. **Original fix:** hard `return` — skip agent entirely. **Refined:** hard gate was too aggressive — between duty cycles, agents went completely dark (no Ward Room posts, no trust signals, confidence degraded). Architect (daily duty) and counselor (12h) silent for 24h/12h. Ship went dark. **Current fix:** replaced hard `return` with 3x cooldown gate — agents can do free-form thinks between duties at reduced frequency (900s default vs 300s for duty cycles). Duties still take priority when due. | High | **Closed** |
| BF-022 | Crew cannot respond to Ship's Computer advisory messages. Bridge alerts post to All Hands (ship-wide) with `same_department=False`. Earned Agency gating: `can_respond_ambient(LIEUTENANT, is_captain_post=True, same_department=False) → False`. Post-reset, all crew are Lieutenants (trust 0.5) — no one qualifies. Root cause: the ambient response gate wasn't designed with system broadcasts in mind. Fixed in AD-424: INFORM threads skip notification entirely, DISCUSS threads pass `same_department=True` to earned agency (explicitly open for input). | Medium | **Closed** |
| BF-023 | Degraded agent death spiral. When proactive loop LLM calls throw exceptions (timeout, API error), the exception handler catches at DEBUG level but never calls `update_confidence()`. Confidence freezes at whatever value it was when errors started. Agents stuck in DEGRADED (< 0.2) with no recovery path — they keep getting called (DEGRADED is `is_alive`), keep failing, and stay dead forever. Additionally, `update_confidence()` had no path from DEGRADED back to ACTIVE even on success. **Fix:** (a) Exception handler calls `update_confidence(False)` so failures are tracked. (b) `update_confidence()` restores DEGRADED -> ACTIVE when confidence climbs back above 0.2. (c) Degradation warning logs only on state transition, not repeated failures. 5 tests. | High | **Closed** |
| BF-024 | Crew agents with domain-specific `perceive()/act()` overrides (Builder, Architect, Counselor, Scout) degrade on every proactive think cycle. Their intent guards only listed `direct_message` and `ward_room_notification` — when `proactive_think` arrives, it falls through to domain pipelines (build specs, design proposals, assessments) which fail because proactive thoughts aren't domain requests. Each failure triggers BF-023's confidence decay, degrading all four agents within minutes. **Fix:** Added `proactive_think` to intent guard tuples in `perceive()`, `_build_user_message()`, and `act()` across all four agent classes (builder.py, architect.py, counselor.py, scout.py). Proactive thoughts now delegate to the base `CognitiveAgent` implementation which handles them correctly. | Critical | **Closed** |
| BF-025 | CI-only failure: `test_no_duty_allows_freeform_think` passes locally but fails on GitHub Actions. The free-form think cooldown gate uses `time.monotonic() - last < idle_cooldown` where `last` defaults to `0.0`. On a fresh CI runner VM with low uptime, `time.monotonic()` can be < 900s (3x cooldown), so the gate incorrectly blocks the first-ever think. Locally, uptime is hours/days so `time.monotonic()` is always large enough. **Fix:** Added `last > 0` guard — first-ever proactive think for an agent always passes the cooldown check. | Medium | **Closed** |
| BF-026 | TypeScript build failure: `display_name` property was added to the Python state snapshot (wiring crew profile display names to HXI) but never added to the `StateSnapshot` TypeScript interface in `ui/src/store/types.ts`. TSC fails with `Property 'display_name' does not exist on type`. **Fix:** Added `display_name: string` to `StateSnapshot.agents` interface. | Low | **Closed** |
| BF-027 | Agent memory recall ineffective — agents can't recall Ward Room posts or past 1:1 conversations despite episodes being stored correctly. Three issues: (a) `recall_for_agent()` uses 0.7 cosine similarity threshold which is too strict for conversational queries ("What have you been thinking about?" vs `[Proactive thought] Counselor: observed trust variance...`). (b) No fallback when semantic recall returns empty — agent gets zero memory context. (c) `MockEpisodicMemory` missing `recall_for_agent()` — tests silently skip recall via `except Exception: pass`. **Fix:** (a) Lower agent-scoped recall threshold to 0.3 (sovereign shard filter prevents cross-agent leakage). (b) Add `recent_for_agent()` timestamp-based fallback when semantic recall returns nothing. (c) Add `recall_for_agent()` and `recent_for_agent()` to MockEpisodicMemory. | High | **Closed** |
| BF-028 | Proactive & shell recall missing `recent_for_agent()` fallback. BF-027 added the fallback to `_recall_relevant_memories()` in cognitive_agent.py, but two other recall sites were not updated: `_gather_context()` in proactive.py (hardcoded query `"recent activity"`) and shell cross-session recall (query `"1:1 with {callsign}"`). Both need the same fallback pattern. **Fix:** Added `recent_for_agent()` fallback with `hasattr` guard to both sites. 2 tests. | Medium | **Closed** |
| BF-029 | Ward Room memory recall quality in 1:1 conversations. Agents can't recall Ward Room posts when Captain asks in 1:1 — episodes are stored correctly (AD-430a) but recall pipeline has three issues: (a) `direct_message` recall query uses raw Captain text with no Ward Room signal in the embedding, (b) memory presentation prefers thin reflection strings over content-rich input, (c) Ward Room reply reflections lack body content (`"replied in thread 'X'"` instead of what was said). **Fix:** Prepend `"Ward Room {callsign}"` to recall query for direct_message, reverse input/reflection preference in both prompt builders, include body excerpt in reply reflections + channel name in reply user_input. 10 tests. | High | **Closed** |
| BF-030 | `ward_room.py` used `self._db.execute_fetchone()` which doesn't exist in aiosqlite. Caused AttributeError at runtime when recalling Ward Room thread metadata. **Fix:** Replaced with standard `async with self._db.execute(...) as cursor: row = await cursor.fetchone()` pattern. | Medium | **Closed** |
| BF-031 | `CognitiveJournal.start()` ran `executescript(_SCHEMA)` with `CREATE INDEX ... ON journal(intent_id)` before `ALTER TABLE ADD COLUMN intent_id` migration. On pre-AD-432 databases, the table existed without the column → `OperationalError: no such column: intent_id`. **Fix:** Split schema into `_SCHEMA_BASE` (table + safe indexes) and `_SCHEMA_INDEXES` (indexes on migrated columns). Startup: base → migration → dependent indexes. | Critical | **Closed** |
| BF-032 | Proactive observation self-reference loop. Agents see their own Ward Room posts in proactive context, observe patterns in their own posting, then post meta-observations about their posting patterns — recursive loop. Observed in Troi and Selar. **Fix:** (1) Self-post filter in `_gather_context()` — `self_ids` set excludes agent's own posts from Ward Room activity context. (2) `_is_similar_to_recent_posts()` — Jaccard word-set similarity (threshold 0.5), fail-open, checks last 3 posts. (3) Similarity gate in `_think_for_agent()` before posting — suppressed posts still record duty execution. (4) Prompt instruction: "Do not comment on your own posting patterns or observation frequency." 5 tests. | Medium | **Closed** |
| BF-033 | Agent profile cards in HXI showing "0 Episodes" and "0s" uptime — both fields were unwired stubs. **Root cause:** (1) `EpisodicMemory` had no `count_for_agent()` method; API's `hasattr` guard silently defaulted to 0. (2) API hardcoded `"uptime": 0.0` instead of using runtime's `_start_time`. **Fix:** Added `count_for_agent(agent_id)` to `EpisodicMemory` (ChromaDB metadata filter on `agent_ids_json`). Replaced hardcoded uptime with `time.monotonic() - runtime._start_time`. | Low | **Closed** |
| BF-034 | Post-reset trust anomaly false positives. After `probos reset -y`, EmergentDetector fires 6+ consecutive trust anomalies because baseline trust (0.5) is interpreted as anomalous — no cold-start awareness. Agents see these as system problems and enter discussion spirals about "demotions." **Fix:** (1) Cold-start detection in runtime — flag set when all trust at prior + episodic empty. (2) `EmergentDetector.set_cold_start_suppression(300)` — suppresses trust anomalies for 5 min (clusters/routing still fire). (3) Proactive context injection — `system_note` tells agents "baseline trust is normal, not demotion." (4) Ward Room announcement: "Fresh Start — System Reset" thread. Flag auto-clears after first dream cycle. 8 tests. | Medium | **Closed** |
| BF-035 | Ward Room reply threshold too high. `can_perform_action()` gated replies at `Rank.COMMANDER` but cold-start trust=0.5 maps to `Rank.LIEUTENANT` — no agent could reply to any thread. **Fix:** Lowered reply tier from COMMANDER to LIEUTENANT in `earned_agency.py`. Also fixed `agents.tsx` TS build error (`boolean \| undefined` → `!!hasConv`). | Medium | **Closed** |
| BF-036 | EmergentDetector trust anomaly flooding persists beyond cold-start window. After BF-034's 5-min suppression expires, detector continues flagging normal trust=0.5 variation as anomalous during extended warmup. Overnight run showed persistent alert cascade, triggering 5+ duplicate crew proposals about the same issue. **Fix:** Three guards in `detect_trust_anomalies()`: (1) std floor raised from 0.001 to 0.05 — skip sigma analysis when population spread is negligible. (2) Min observations guard — skip agents with alpha+beta < 8.0 (fewer than 4 actual observations beyond prior). (3) Min absolute deviation guard — skip if abs(score-mean) < 0.10 regardless of sigma. 7 tests. | Low | **Closed** |
| BF-037 | Ontology context gathered but never rendered. `_gather_context()` in proactive.py collects `context["ontology"]` (AD-429a) and `context["skill_profile"]` (AD-429b) but `_build_user_message()` in cognitive_agent.py never reads these keys — the data is silently dropped. **Fix:** Two rendering blocks in `_build_user_message()` proactive_think branch: (1) Ontology identity grounding — callsign, post, department, reports_to, direct_reports, peers, vessel status/alert condition. (2) Skill profile — comma-joined skill list. Placed after cold-start note, before memories. 8 tests. | Medium | **Closed** |
| BF-040 | Identity system hardening — 13 findings from post-AD-441/441b code review. **C-2 (Critical):** `export_chain()` genesis credential attachment condition simplified (check `not blocks[0].get("credential")` instead of DID comparison). **H-1:** Input validation on `generate_did()`, `generate_ship_did()`, `parse_did()`, `issue_birth_certificate()`. **H-2:** `asyncio.Lock` on `_append_to_ledger()` to prevent concurrent chain corruption. **H-3:** `PRAGMA foreign_keys = ON`. **M-1:** `verify_chain()` validates genesis `previous_hash` is all zeros. **M-3:** Eager genesis block creation during `_commission_ship()`. **M-4:** Removed dead `_cache` dict. **M-5, L-2, L-3:** Documented proof type rationale, hash format difference, float representation. **L-1:** Warning log on slot mapping overwrite. **L-4:** Index on `slot_mappings.agent_uuid`. **M-2:** Column order comments on positional DB row access. Removed obsolete backwards-compat test. 9 new tests, 1 removed, 1 updated. | Mixed | **Closed** |
| BF-039 | Episodic memory flooding after reset. Agents (especially Medical) accumulate hundreds of episodes within hours. Root causes: (1) Double episode creation per proactive thought — both `proactive.py` (line 339) and `ward_room.py` (line 885 via `_post_to_ward_room`) store episodes for the same cognitive event. (2) Ward Room episode storage (`ward_room.py` lines 885, 1082) bypasses `should_store()` gate entirely. (3) No per-agent episode rate limiter — no check for "N episodes in last hour." (4) No content-based dedup — every episode gets a fresh UUID, so identical text stores twice. (5) `count_for_agent()` defined twice in `episodic.py` (lines 278, 401) — second shadows first, both O(N) over all episodes. **Fix:** (1) Deduplicate proactive+WR episode path — proactive.py skips episode storage when WR is available (WR creates its own). (2) WR episode storage routed through `should_store()`. (3) Per-agent rate limiter: MAX_EPISODES_PER_HOUR=20 via rolling ChromaDB timestamp query. (4) Content similarity gate: Jaccard word-level similarity > 0.8 within 30-min window rejects duplicate. (5) Removed duplicate `count_for_agent()`. (6) Cold-start dampening: 3x cooldown for first 10 minutes (COLD_START_WINDOW_SECONDS=600). Ward Room `should_store()` recognizes `[Ward Room]`/`[Ward Room reply]` prefixes. 6 fixes implemented, 12 new tests, 290 tests green. | High | **Closed** |
| BF-041 | HXI icon system diverges from canonical SVG-only design language. `copilot-instructions.md` requires inline SVG with strokeWidth 1.5 / strokeLinecap round, but BridgeCards, BridgeNotifications, AgentTooltip, BridgePanel, IntentSurface, GlassDAGNodes, and ContextRibbon use Unicode text glyphs (chevrons, dots, arrows, warning badges). **Fix:** Create shared SVG glyph component set (status, chevron, divider, warning, expand, close), replace Unicode glyphs across all HXI surfaces. Found in designed-vs-built review 2026-03-27. | Medium | **Open** |
| BF-042 | HXI component-level Vitest coverage gap. Repo rules require component tests for every UI change, but Bridge, tooltip, chat, and welcome surfaces lack render-level tests. Store/integration tests exist (useStore, GlassLayer) but BridgePanel, TaskCard, NotificationCard, AgentTooltip, IntentSurface chat panels, and WelcomeOverlay have no direct component test coverage. **Fix:** Add render-level Vitest tests for these surfaces. Found in designed-vs-built review 2026-03-27. | Medium | **Open** |
| BF-043 | Test suite parallelization. **Fix:** (1) Added `pytest-xdist>=3.5` for parallel execution (`-n auto`). (2) Added `pytest-timeout>=2.3` with 30s default. (3) Marked `test_task_scheduler.py` (39 tests) and `test_dreaming.py` (26 tests) as `@pytest.mark.slow`. (4) Fixed 2 parallel-only test failures in `test_experience.py` — `MockEpisodicMemory` relevance_threshold too tight (0.3→0.2) causing recall misses when xdist's `popen-gw{N}/` path segment dilutes Jaccard token overlap. **Result:** 13x speedup (177s vs ~2220s sequential). Fast path: `pytest -n auto -m "not slow"` = 3537 tests in ~90s. Slow marker: 65 tests with real `asyncio.sleep()`. | Medium | **Closed** |
| BF-044 | Hebbian routing uses unique message UUID as source key instead of intent name. `runtime.py` `submit_intent()` and `submit_intent_with_consensus()` recorded `source=msg.id` (per-message UUID) instead of `source=intent` (intent name string). Each interaction created a new weight key that never reinforced — Hebbian learning never accumulated. HXI curves rendered but "went nowhere" because UUID source couldn't resolve to an agent position. **Fix:** Changed `source=msg.id` to `source=intent` in both `record_interaction` calls and both `_emit_event`/`get_weight` calls. Also fixed AD-442 proactive activation check (`get_trust` → `get_score`, MagicMock-safe threshold). 4 new tests in `test_hebbian_source_key.py`. | High | **Closed** |
| BF-045 | Naming ceremony calls `_llm_client.complete(system=..., prompt=..., max_tokens=...)` with raw kwargs — `OpenAICompatibleClient.complete()` expects `LLMRequest` object. All agents fail self-naming on commissioning and fall back to seed callsigns. **Fix:** Wrapped call in `LLMRequest(system_prompt=..., prompt=..., max_tokens=..., tier="fast")` and access `response.content`. | Critical | **Closed** |
| BF-046 | Proactive notebook writes reference `self._runtime._ontology` — attribute is `self._runtime.ontology` (public, no underscore). Every notebook write fails with `'ProbOSRuntime' object has no attribute '_ontology'`. Also fixed `RecordsStore` constructor call in runtime.py (`getattr(self, '_ontology')` → `getattr(self, 'ontology')`). **Fix:** Two attribute references corrected. | Medium | **Closed** |
| BF-047 | DM callsign resolution calls `CallsignRegistry.get_agent_type(callsign)` which doesn't exist. The reverse lookup (callsign→agent_type) is only available through `resolve()`. Every DM attempt raises AttributeError, caught by exception handler — all agent DMs silently fail. **Fix:** Replaced with `rt.callsign_registry.resolve(target_callsign)` → `resolved.get("agent_type")`. | High | **Closed** |
| BF-048 | Episode rate limiter fails open. `_is_rate_limited()` catches all ChromaDB query exceptions and returns `False` (not rate-limited). If the timestamp filter query fails (float precision, collection state, etc.), every episode bypasses the 20/hour cap. Diagnostician accumulated 837 episodes in 5 minutes. **Fix:** Changed `except Exception: return False` to `return True` (fail closed). If we can't verify the rate, assume limited — prevents memory flooding. | High | **Closed** |
| BF-049 | Agents reference seed callsigns instead of current callsigns. Forge (builder) said "I'll reach out to LaForge" — LaForge is the pre-naming seed callsign for engineering_officer, not a current crew member. **Fix:** Added `update_assignment_callsign()` to ontology, called from runtime after naming ceremony. Peers/reports_to now show current callsigns. | Medium | **Closed** |
| BF-050 | Agents don't know their own callsign in conversation. Tesla (engineering_officer) said "I'll reach out to Tesla" — referencing itself. **Fix:** Ontology sync (BF-049) ensures self-identity is consistent. Crew roster excludes self callsign. | Medium | **Closed** |
| BF-051 | DM syntax only available in proactive prompt. Captain ordered all departments to DM their peers — every agent acknowledged publicly but none used `[DM @callsign]` syntax. **Fix:** Extracted `_compose_dm_instructions()` helper, called in both `proactive_think` and `ward_room_notification` branches. 1:1 `direct_message` excluded (already in DM context). | Medium | **Closed** |
| BF-052 | Crew roster lacks department grouping. `all_callsigns()` returns a flat `@callsign` list with no department context. **Fix:** `_compose_dm_instructions()` now uses ontology to group crew by department (Engineering: @Forge, @Tesla). Falls back to flat list when ontology unavailable. | Medium | **Closed** |
| BF-053 | Communications panel `count={0}` hardcoded. BridgePanel.tsx line 171: `<BridgeSection title="Communications" count={0}>` — count badge always shows 0 regardless of actual DM channel activity. Should be wired to `dmChannels.length`. | Low | **Closed** |
| BF-054 | Communications panel DM Activity Log "View full thread" visibility inverted. The "View full thread →" link appears only when the thread entry is expanded/clicked, not when collapsed. Should be visible in collapsed state to invite interaction, hidden or replaced with content when expanded. Also: no auto-refresh — `refreshDms()` fires only on mount, no polling or WebSocket hook. Panel shows stale data until manual navigation. | Low | **Closed** |
| BF-055 | Captain cannot reply to DMs. DM Activity Log is read-only — no input field or reply mechanism. When agents DM the Captain (`[DM @captain]`), the message appears in Communications but the Captain has no way to respond. Need a reply input on DM thread entries (or click-to-open a DM chat view) that posts back to the DM channel as a Captain message. HXI Cockpit View Principle violation — every agent-mediated capability requires direct manual control. | Medium | **Closed** |
| BF-056 | DM Activity Log appeared to show only Captain-directed DMs. Investigation: backend `GET /api/wardroom/dms` already returns ALL DM channels (no participant filter). Root cause was BF-051 — agents couldn't use DM syntax outside proactive prompt, so no agent-to-agent DMs were ever created. With BF-051 fixed, agent-to-agent DM channels CAN be created. **Verified 2026-03-28:** After 17h uptime, all 8 DM channels are agent-to-Captain. Zero agent-to-agent DMs generated. Display works correctly — agents simply don't choose to DM each other. This is a behavioral gap (agents default to department channels), not a UI bug. Closed — may revisit as crew development training scenario (AD-510). | Low | **Closed** |
| BF-057 | **Agents lose identity on restart (naming ceremony re-runs unconditionally).** Restart without reset causes every crew agent to run the naming ceremony from seed callsigns (Scotty, Number One, Wesley…) and pick entirely new names. Root cause: `CallsignRegistry.load_from_profiles()` loads seed callsigns from YAML, naming ceremony guard (runtime.py line 4006) has no check for persisted callsigns, and `set_callsign()` never writes to disk. Birth certificates in `identity.db` DO persist callsigns — but the naming ceremony runs BEFORE identity resolution, so it never sees the existing cert. **Fix:** Check identity registry for existing cert before naming ceremony; if cert exists, restore that callsign and skip the ceremony. Boot ordering verified correct (identity registry starts before agent spawn). | **Critical** | **Closed** |
| BF-058 | **Crew agents use random UUIDs — identity persistence impossible.** BF-057's cert lookup uses `get_by_slot(agent.id)`, but 7 crew pools (builder, architect, scout, counselor, security_officer, operations_officer, engineering_officer) are created without `agent_ids=`, so `BaseAgent.__init__` falls through to `uuid.uuid4().hex`. New random ID every boot → cert never matches → naming ceremony runs every time. Medical agents work correctly because they use `generate_pool_ids()`. **Fix:** Add `agent_ids=generate_pool_ids(...)` to all 7 crew pool creation calls, matching the medical agent pattern. | **Critical** | **Closed** |
| BF-059 | **`probos reset` doesn't clear identity.db.** Reset clears trust, episodes, Hebbian, Ward Room, events, journal — but not identity.db. After reset, old birth certificates survive. Medical agents (with deterministic IDs) silently match old certs and skip naming ceremony, keeping previous instance callsigns. A reset should create a new ship with new crew identities. **Fix:** Add identity.db and ontology/instance_id cleanup to `_cmd_reset()`. | Medium | **Closed** |
| BF-060 | **Notebook content leaks into Ward Room posts.** Proactive loop correctly extracts `[NOTEBOOK ...]` blocks and writes them to Ship's Records, but the raw `[NOTEBOOK]` tag and its content are not stripped from the text before posting to Ward Room. Root cause: `text.replace()` with stripped content doesn't match original whitespace. **Fix:** Replace per-match `text.replace()` with `re.sub(notebook_pattern, '', text, flags=re.DOTALL)` after notebook extraction loop. | Medium | **Closed** |
| BF-061 | **`[REPLY thread:...]` tag creates new thread instead of actual reply.** Two sub-issues: (a) Pattern `r'\[REPLY\s+(\S+)\]\s*\n(.*?)\n\[/REPLY\]'` requires newline and captures `thread:` prefix as part of ID. (b) Rank gate at Commander+ blocks all fresh-instance agents (start as Lieutenant). **Fix:** Flexible pattern `r'\[REPLY\s+(?:thread:?\s*)?(\S+)\]\s*(.*?)\s*\[/REPLY\]'` (DOTALL), `_resolve_thread_id()` method for partial UUID prefix match, rank gate lowered to Lieutenant+. | Medium | **Closed** |
| BF-062 | **Proactive thoughts repeat near-identical observations across cycles.** Similarity gate checked only last 3 posts with word-level Jaccard. **Fix:** Increased window to 10 posts, added bigram Jaccard as second check alongside existing word-level check (same 0.5 threshold). | Medium | **Closed** |

> **Bug details (BF-001–011):** All closed. See [roadmap-completed.md](roadmap-completed.md#bug-tracker--closed-issues).


!!! info "Want to contribute?"
    See the [Contributing guide](contributing.md) for how to get involved.
