# Roadmap

ProbOS is organized as a starship crew — specialized teams of agents working together to keep the system operational, secure, and evolving. Each team is a dedicated agent pool with distinct responsibilities. The Captain (human operator) approves major decisions through a stage gate.

ProbOS doesn't just orchestrate agents — it gives them a civilization to come together. Trust they earn, consensus they participate in, memory they share, relationships that strengthen through learning, a federation they can grow into. Other frameworks dispatch tasks. ProbOS provides the social fabric that makes cooperation emerge naturally.

> **Status tags (BF #465 reconciliation, 2026-05-07):** AD entries below are tagged
> `(planned, OSS)` for unbuilt work or `(SHIPPED, OSS)` once delivered. PROGRESS.md
> remains the authoritative source — this file lags. The 2026-05-07 reconciliation
> pass flipped 27 entries that had drifted (AD-486, 510, 512, 520, 526, 543-549, 562,
> 566, 567, 569, 571, 595, 597, 599, 601, 604, 607).

## Design Principles

See [Design Principles](design-principles.md) for the full design philosophy — architectural and philosophical principles that govern how ProbOS thinks about what it builds. Engineering practices (SOLID, DRY, Fail Fast) live in [contributing.md](contributing.md).

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
| **Science** | Science Lab (Spock) | Research, discovery, architectural analysis, codebase knowledge, intelligence gathering, telemetry analysis, emergence studies | Built (Architect, CodebaseIndex, Scout, Data Analyst, Systems Analyst, Research Specialist — AD-560 complete) |
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
| Ship departments | Agent pools (crew teams) | Built |
| Chain of Command | Rank structure — Fleet Admiral → Captain → Bridge → Chiefs → Crew | Built (AD-398/440/477/595/674) |
| Ship's computer / LCARS | Runtime + CodebaseIndex + Knowledge Store + Cognitive Journal | Built |
| Internal sensors | Ship's Telemetry — LLM timing, token metering, pipeline comparison | Built (AD-461) |
| Alert Conditions (Red/Yellow/Green) | Ship-wide operational modes — resource/consensus/dream behavior changes | Built (AD-503/506/695) |
| EPS (Power Distribution) | Token/compute budget allocation across departments | Built (AD-469) |
| Structural Integrity Field | Proactive runtime invariant enforcement | Roadmap ([#475 AD-699](https://github.com/seangalliher/ProbOS/issues/475)) |
| Multi-Level Diagnostics (L1–L5) | Formalized diagnostic depth for Medical team | Roadmap ([#476 AD-700](https://github.com/seangalliher/ProbOS/issues/476)) |
| Damage Control Teams | Engineering rapid-response automated recovery | Built (AD-457) |
| Navigational Deflector | Pre-flight validation before expensive operations | Built (AD-458) |
| Saucer Separation | Graceful degradation when critical systems fail | Built (AD-459) |
| Transporter | Transporter Pattern — parallel code generation (AD-330–336) | **Complete** |
| Federation | Federated ProbOS instances | Built (Phase 29) |
| Visiting officers | External AI tools (Claude Code, Copilot, etc.) | Partial (MCP bridge AD-449 ✅; formal registration [#477 AD-701](https://github.com/seangalliher/ProbOS/issues/477)) |
| Diplomatic relations | Trust transitivity between nodes | Roadmap ([#478 AD-702](https://github.com/seangalliher/ProbOS/issues/478)) |
| Shared intelligence | Knowledge federation + Model of Models | Partial (AD-687 Knowledge Edge Store ✅; cross-instance sync AD-693 *(Commercial)*) |
| Prime Directive | Safety constraints, boundary rules, human gate | Built |
| Starfleet Command | Fleet Admiral (creator) — fleet-wide policy across all instances | Long Horizon ([#479 AD-703](https://github.com/seangalliher/ProbOS/issues/479)) |
| Universal Translator | Channel adapters — Discord, Slack, Telegram, WhatsApp, Matrix, Teams | Partial (Discord/Slack/Webhook ✅ AD-472; remaining 4 in [#480 AD-704](https://github.com/seangalliher/ProbOS/issues/480)) |
| Subspace Communications | Voice interaction — STT, TTS, wake word, continuous talk | Partial (substrate ✅ AD-474; backends in [#481 AD-705](https://github.com/seangalliher/ProbOS/issues/481)) |
| PADD (Personal Access Display Device) | Mobile companion — PWA, push notifications, responsive HXI | Partial (PWA + push ✅ AD-473; responsive HXI + mDNS in [#484 AD-708](https://github.com/seangalliher/ProbOS/issues/484)) |
| Browser Tool (Computer Use) | Agent-driven Chromium via Playwright — 10-action vocabulary, indexed-element state, XGA screenshots, tier-3 Captain-ACK gate | Built ([#482 AD-706](https://github.com/seangalliher/ProbOS/issues/482)) ✅ |
| Holodeck Simulations | Agent training environments — scenario simulation, promotion tests, skill acquisition | Built (AD-486/510/539b) |
| MemoryForge | Ship's Computer service — implanted birth memories, memory transfer, curated memory banks | Long Horizon ([#485 AD-709](https://github.com/seangalliher/ProbOS/issues/485)) |
| Cognitive Evolution | Transfer learning, proactive initiative, service modeling, trend analysis, gap prediction | Built (AD-507/509/628/660/666/668-672) |
| Workflow Templates | Reusable multi-step pipelines — cron, webhooks, workflow API | Partial (WorkflowCache ✅ AD-580; triggers in [#483 AD-707](https://github.com/seangalliher/ProbOS/issues/483)) |
| Drydock | Distribution — PyPI, Docker, onboarding wizard, quickstart | Built (AD-465/484) |
| Modular Construction | Extension-first architecture — sealed core, plugin extensions, graduated autonomy | Built (AD-481) |
| Ready Room | Captain's strategic planning — idea capture, multi-agent sessions, architecture hierarchy | Built (AD-475) |
| Utopia Planitia | Specialized builders — backend, frontend, test, infra, data | Built (AD-476) |
| Captain's Yeoman | Personal AI assistant — conversational front door, crew delegation, personalization | Roadmap ([#486 AD-710](https://github.com/seangalliher/ProbOS/issues/486)) |
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


---

## Currently Pending (OSS)

For full historical context (team details, completed phases, AD descriptions
for shipped work), see [roadmap-era-5-completed.md](roadmap-era-5-completed.md).

### Backlog (queued, awaiting wave-plan slot)

**From the original AD backlog:**

| AD | Title | Issue |
|----|-------|-------|
| AD-495 | Counselor Auto-Assessment on Circuit Breaker Trip | [#474](https://github.com/seangalliher/ProbOS/issues/474) |
| AD-581 | Hybrid Dispatch — Chain-of-Command Direct Tasking (parent) | [#468](https://github.com/seangalliher/ProbOS/issues/468) |
| AD-581a | DepartmentDispatcher — routing decision layer | [#469](https://github.com/seangalliher/ProbOS/issues/469) |
| AD-581b | Agent Order Protocol — accept/decline/refuse semantics | [#470](https://github.com/seangalliher/ProbOS/issues/470) |
| AD-581d | Routing Confidence Threshold | [#471](https://github.com/seangalliher/ProbOS/issues/471) |
| AD-594b | Crew Consultation Primitive — `consult(question, context)` | [#472](https://github.com/seangalliher/ProbOS/issues/472) |
| AD-594d | Delivery Pipeline — markdown→PDF, structured→reports | [#473](https://github.com/seangalliher/ProbOS/issues/473) |

**From the 2026-05-08 Federation table audit:**

| AD | Title | Issue | Priority |
|----|-------|-------|----------|
| AD-699 | Structural Integrity Field (SIF) | [#475](https://github.com/seangalliher/ProbOS/issues/475) | 2 |
| AD-700 | Multi-Level Diagnostics (L1–L5) | [#476](https://github.com/seangalliher/ProbOS/issues/476) | 3 |
| AD-701 | Visiting Officers — formal external-participant Ward Room registration | [#477](https://github.com/seangalliher/ProbOS/issues/477) | 2 |
| AD-702 | Diplomatic Relations — trust-transitivity computation | [#478](https://github.com/seangalliher/ProbOS/issues/478) | 3 |
| AD-703 | Starfleet Command — fleet-wide policy distribution | [#479](https://github.com/seangalliher/ProbOS/issues/479) | 4 (Long Horizon) |
| AD-704 | Universal Translator — Telegram/WhatsApp/Matrix/Teams adapters | [#480](https://github.com/seangalliher/ProbOS/issues/480) | 3 |
| AD-705 | Voice Stack Backends — Whisper/Deepgram/Coqui/Porcupine | [#481](https://github.com/seangalliher/ProbOS/issues/481) | 3 |
| AD-707 | Workflow Triggers — cron + webhook + workflow API | [#483](https://github.com/seangalliher/ProbOS/issues/483) | 3 |
| AD-708 | PADD — responsive HXI + mDNS auto-discovery | [#484](https://github.com/seangalliher/ProbOS/issues/484) | 4 |
| AD-709 | MemoryForge — implanted birth memories | [#485](https://github.com/seangalliher/ProbOS/issues/485) | 5 (Long Horizon) |
| AD-710 | Captain's Yeoman — personal AI assistant | [#486](https://github.com/seangalliher/ProbOS/issues/486) | 4 |

**From the 2026-05-08 chat-experience enhancements (Captain's request):**

| AD | Title | Issue | Priority |
|----|-------|-------|----------|
| AD-718 | Voice in 1:1 crew profile chat (parity with Ship's Computer chat) | [#512](https://github.com/seangalliher/ProbOS/issues/512) | 2 |
| AD-719 | Multi-agent chat surface (M365 Copilot pattern, @-mention + agent picker) | [#513](https://github.com/seangalliher/ProbOS/issues/513) | 2 |
| AD-720 | Chat attachments — file uploads + image paste + tool attach (v2) | [#514](https://github.com/seangalliher/ProbOS/issues/514) | 3 |
| AD-721 | 3D crew avatars on profile cards (popout, expressions, body language) | [#515](https://github.com/seangalliher/ProbOS/issues/515) | 3 |

**From Wave 132 deferred forward markers (AD-706 Browser Tool follow-ups):**

| AD | Title | Issue | Priority |
|----|-------|-------|----------|
| AD-706a | Captain-watch streaming bridge — live browser session in HXI | [#516](https://github.com/seangalliher/ProbOS/issues/516) | 2 |
| AD-706b | Browser session video recording + retention policy | [#517](https://github.com/seangalliher/ProbOS/issues/517) | 3 |
| AD-706c | OmniParser-style vision extraction — **SPLIT 2026-05-12** into AD-706c-1 + AD-706c-2 after AD-732 + BF-268..273 made prerequisites concrete | (closed-as-superseded [#518](https://github.com/seangalliher/ProbOS/issues/518)) | — |
| AD-706c-1 | Visual verification of Browser Tool actions using existing local vision tier (qwen3.6:27b). Read-only "did the expected outcome appear?" flow. Builds on already-shipped AD-731/BF-268/AD-732 primitives. **Demo value**: agent narrates its own work | [#642](https://github.com/seangalliher/ProbOS/issues/642) | 2 |
| AD-706c-2 | Coordinate-aware `compute_use` tier for DOM-less surfaces (Anthropic computer-use / OpenAI Operator-style). Click-target prediction with the eight-guard vision stack + two new guards (coordinate verification + cross-action trust budget extending AD-676). Operator opt-in: local coord-tuned model OR cloud API key, never both silently | [#643](https://github.com/seangalliher/ProbOS/issues/643) | 4 |
| AD-706d | LLM-driven tier classifier for Browser Tool actions — should plug into AD-732's `_LLM_TIERS` shape (fast/standard/deep/vision + future compute_use) | [#519](https://github.com/seangalliher/ProbOS/issues/519) | 3 |
| AD-706e | Browser Tool action vocabulary v2 — drag, key_combo, mouse, upload, download, eval_js. `eval_js` requires dual-control consensus per AD-676 | [#520](https://github.com/seangalliher/ProbOS/issues/520) | 3 |
| AD-706f | Browser Tool credential vault integration for authenticated flows | [#521](https://github.com/seangalliher/ProbOS/issues/521) | 3 |

**From Wave 133 deferred forward markers (AD-718 voice + AD-721 avatars follow-ups):**

| AD | Title | Issue | Priority |
|----|-------|-------|----------|
| AD-718a | Agent-authored voice profile | [#522](https://github.com/seangalliher/ProbOS/issues/522) | 3 |
| AD-718b | Coqui/ElevenLabs/Bark TTS backend via AD-705 | [#523](https://github.com/seangalliher/ProbOS/issues/523) | 3 |
| AD-718c | Per-agent wake-word | [#524](https://github.com/seangalliher/ProbOS/issues/524) | 4 |
| AD-718d | Emotional voice modulation (synergy with AD-721) | [#525](https://github.com/seangalliher/ProbOS/issues/525) | 3 |
| AD-718e | Multi-language voice selection | [#526](https://github.com/seangalliher/ProbOS/issues/526) | 4 |
| AD-718f / AD-735 | Per-agent volume control surface — **SHIPPED Wave 156** (UI slider; backend chain shipped under AD-718) | [#527](https://github.com/seangalliher/ProbOS/issues/527) | 4 |
| AD-705d / AD-736 | Mic-permission UX polish (4-state machine + `MicPermissionHint` overlay) — **SHIPPED Wave 156** | [#558](https://github.com/seangalliher/ProbOS/issues/558) | 4 |
| AD-722a-3 / AD-737 | Per-agent custom emotion taxonomy (v2 — beyond fixed 8) — **SHIPPED Wave 156** | [#612](https://github.com/seangalliher/ProbOS/issues/612) | 3 |
| AD-721a | Captain's avatar editor UI | [#528](https://github.com/seangalliher/ProbOS/issues/528) | 3 |
| AD-721b | Phoneme-accurate lip-sync v1 (heuristic 5-vowel viseme driver, multi-mesh) — **SHIPPED Wave 138** | [#529](https://github.com/seangalliher/ProbOS/issues/529) | 3 |
| AD-721b-1 | Server-side rhubarb-lip-sync backend (replaces heuristic phoneme schedule) — **SHIPPED Wave 155** | [#559](https://github.com/seangalliher/ProbOS/issues/559) | 3 |
| AD-721b-2 | Browser-side real-audio capture via `MediaStreamDestination` — **SHIPPED Wave 155** | [#560](https://github.com/seangalliher/ProbOS/issues/560) | 3 |
| AD-721b-2.3 / AD-738 | Server-streamed TTS via Piper (closes the lip-sync loop — server is the source of audio bytes so rhubarb runs on real WAV) — **SHIPPED Wave 157** | none (was forward marker) | 3 |
| AD-738f | Per-agent voice selection (CrewProfile.voice_model + UI selector with license display) — renumbered from AD-738a (Wave 158) | none | 4 |
| AD-738g | GPU-accelerated TTS backend eval (Kokoro Apache 2.0 / StyleTTS2 MIT slot into TTSBackend Protocol) — renumbered from AD-738b (Wave 158) | none | 4 |
| AD-738h | Server-side voice modulation (apply AD-735 pitch/rate at Piper synthesis, not `<audio>` post-processing) — renumbered from AD-738c (Wave 158) | none | 4 |
| AD-738i | TTS text caching layer (LRU keyed `(agent_id, voice, sha256(text))` → `attachment_id`) — renumbered from AD-738d (Wave 158) | none | 4 |
| AD-721b-3 | whisper.cpp WASM tiny.en for offline phoneme alignment (~75 MB model) | [#561](https://github.com/seangalliher/ProbOS/issues/561) | 4 |
| AD-721c | VR / spatial-scene avatar mode | [#530](https://github.com/seangalliher/ProbOS/issues/530) | 4 |
| AD-721d | Agent-authored appearance pipeline | [#531](https://github.com/seangalliher/ProbOS/issues/531) | 3 |
| AD-721e | Skeletal animation library (Mixamo) | [#532](https://github.com/seangalliher/ProbOS/issues/532) | 4 |
| AD-721f | Cognitive-canvas avatar replacement | [#533](https://github.com/seangalliher/ProbOS/issues/533) | 4 |
| AD-721g | Per-tier baseline VRMs | [#534](https://github.com/seangalliher/ProbOS/issues/534) | 4 |
| AD-721h | Browser-based VRM upload UI | [#535](https://github.com/seangalliher/ProbOS/issues/535) | 3 |

**From 2026-05-09 agent-authored avatar pipeline (Captain decision; AD-721d refined; pair with AD-721i in Wave 134):**

| AD | Title | Issue | Priority |
|----|-------|-------|----------|
| AD-721d (refined) | Agent-side appearance reflection cycle → DSL proposal | [#531](https://github.com/seangalliher/ProbOS/issues/531) | 2 |
| AD-721d-1 | DSL draft preview + revision cycle (Captain "request revision" + iteration cap + parametric diff highlights) — **SHIPPED Wave 145** (POST /appearance/propose extended with `previous_dsl` + iteration counter; new DELETE /appearance/proposal-history; CrewAvatarPopout request-revision affordance + amber-tint diff highlights; +13 Python tests, +7 Vitest tests, zero new deps) | [#541](https://github.com/seangalliher/ProbOS/issues/541) | 2 |
| AD-721d-2 | Counselor-mediated avatar revision (vs Captain-driven hint) | [#621](https://github.com/seangalliher/ProbOS/issues/621) | 4 |
| AD-721d-3 | Visual avatar preview before DSL persistence (requires AD-721i renderer) | [#622](https://github.com/seangalliher/ProbOS/issues/622) | 4 |
| AD-721d-4 | Persist avatar proposal history across runtime restarts — **SHIPPED Wave 161** (`proposal_history.configure(path)` loads + binds on-disk sidecar; mutations `append`/`clear`/`reset_all` persist atomically under existing `_lock`; `AvatarsConfig.proposal_history_path` defaults to `<data_dir>/proposal_history.json`; 5 public signatures unchanged; AD-721d-1 module-level dict + RLock unchanged) | [#620](https://github.com/seangalliher/ProbOS/issues/620), [#623](https://github.com/seangalliher/ProbOS/issues/623) (dup) | 3 |
| AD-721d-4a | Migrate to `ConnectionFactory`-backed history store (advances when AD-697/698 lands a non-SQLite backend OR sidecar file > 1 MB OR a second module needs proposal-history-style restart-survival state) | (forward marker, filed Wave 161) | 4 |
| AD-721d-4b | Periodic compaction (purge entries older than 30 days with no terminal action) (advances when sidecar growth > 256 KB/week OR any single agent's history > 100 entries) | (forward marker, filed Wave 161) | 4 |
| AD-721i | DSL → Blender VRM renderer (headless backend) | [#537](https://github.com/seangalliher/ProbOS/issues/537) | 2 |
| AD-721j | Blender Connector — Computer Use control (Anthropic-style; commercial overlay extension exists in private repo) | [#538](https://github.com/seangalliher/ProbOS/issues/538) | 3 |

**From 2026-05-09 Counselor feedback (avatar feedback loop) — novel territory:**

Prior-art scan (issue [#545](https://github.com/seangalliher/ProbOS/issues/545)) found no public OSS project where an AI agent monitors its own avatar's render state. Open-LLM-VTuber (7.6k★), kimjammer/Neuro (1.9k★), and super-agent-party (2.2k★) all run the same one-way LLM→avatar pattern. The standard framing is *"does the human perceive the avatar as natural?"* — AD-722 inverts it: *"does the agent know what it looks like right now?"* Functional self-presence awareness for embodied agents — pattern absorption only (VTube Studio plugin shape + A2F-3D blendshape stream), no code import.

| AD | Title | Issue | Priority |
|----|-------|-------|----------|
| AD-722 | Agent-observable avatar telemetry feedback loop (UI → agent state channel) — **SHIPPED Wave 140** (read-side v1; observe_self_avatar() + GET /api/agent/{id}/avatar-telemetry + <SelfImageTab>; feature-gated prompt injection default OFF) | [#545](https://github.com/seangalliher/ProbOS/issues/545) | 3 |
| AD-722a | Intent-vs-presentation divergence detector (intended tone vs rendered weights → trust/Hebbian) — **unprecedented in OSS LLM-avatar space** | (forward marker, filed Wave 140) | 4 |
| AD-722a-5 | Divergence history surface in SelfImageTab — per-agent in-memory ring buffer + new `/avatar-telemetry/divergence-history` endpoint + `PanelDivergenceHistory` (aggregate %, event list). Server pre-renders OUTPUT-subject note so AD-727 #8 regex gates frontend too. **SHIPPED Wave 147** | [#614](https://github.com/seangalliher/ProbOS/issues/614) | 3 |
| AD-722b | Push channel (WebSocket) replacing 2s poll — **SHIPPED Wave 142** (WS /api/agent/{id}/avatar-telemetry-stream; popout flips sampling tier to HIGH via AvatarSamplingStateMachine.enter_popout/exit_popout; UI WS-first with 5 s open-timeout poll fallback; +28 Python tests, +4 Vitest tests, zero new deps) | [#568](https://github.com/seangalliher/ProbOS/issues/568) | 3 |
| AD-722b-3 | Fine-grained snapshot-diff for WS push — **SHIPPED Wave 159** (`compute_diff` pure-function diffing with `last_observed_at` skipped, default-on, every-Nth-tick full reconcile, frame `type:"snapshot"`/`"diff"` versioning, frontend merge in `SelfImageTab.tsx`, forward markers AD-722b-3a RFC 6902 JSON-Patch + AD-722b-3b fan-out broker) | [#600](https://github.com/seangalliher/ProbOS/issues/600) | 3 |
| AD-722c | Avatar telemetry history for analytics — **SHIPPED Wave 159** (append-only JSONL under `data/avatar_telemetry/<agent_id>.jsonl`; `TelemetryHistoryWriter` writes from `_publish_loop` initial + interval branches, log-and-degrade; new `GET /api/agent/{id}/avatar-telemetry/history?limit=&since=`; forward markers AD-722c-1 size-based rotation + AD-722c-2 `TelemetryHistoryStore` Protocol for commercial overlay) | [#569](https://github.com/seangalliher/ProbOS/issues/569) | 3 |
| AD-722d | Auto-write telemetry summaries to Ship's Records (RecordsStore) — **SHIPPED Wave 159** (3 v1 events: `emotion_divergence_high`, `working_state_transition_to_blocked`, `sustained_silence`; per-agent throttle default 3600 s; Captain opt-in via `records_auto_write_enabled`; Tier-2 log-and-degrade; two-phase wiring in `runtime.py`; forward markers AD-722d-1 operator-defined classifiers + AD-722d-2 Records dedup/aggregation) | [#570](https://github.com/seangalliher/ProbOS/issues/570) | 3 |
| AD-722c-3 | Architect forward markers must use TECHNICAL triggers (NOT commercial-tier language) — **SHIPPED Wave 160** (one bullet added to `prompts/BUILDER-EXECUTION-PLAN.md` Standing Rules; folded into AD-726 commit) | [#654](https://github.com/seangalliher/ProbOS/issues/654) | 3 |
| AD-723a-3 | `SensoriumEntry` gains `injection_zone` + `wrapper` metadata — **SHIPPED Wave 160** (backward-compatible — both fields default None; dispatcher applies wrapper to string outputs only; `_DM_SELF_WRAPPED_KEYS` still v1 selector; forward markers AD-723a-3a per-entry migration + AD-723a-3b zone-driven ordering) | [#626](https://github.com/seangalliher/ProbOS/issues/626) | 3 |
| AD-723a-2 | WR branch consumer-side sensorium dispatch migration — **SHIPPED Wave 161** (new `_WR_SELF_WRAPPED_KEYS: ClassVar[tuple[str, ...]] = ()`; WR branch of `_build_user_message` invokes `_dispatch_sensorium_async(SensoriumPath.WR_ONESHOT, ...)` inside Tier-2 try/except; byte-parity preserved with empty selector; AD-723a-1 DM-branch tests still green) | [#625](https://github.com/seangalliher/ProbOS/issues/625) | 3 |
| AD-723a-2a | Populate `_WR_SELF_WRAPPED_KEYS` with first real consumer (advances when any new WR-only context fragment is proposed) | (forward marker, filed Wave 161) | 4 |
| AD-723a-3a | Per-entry migration off `_DM_SELF_WRAPPED_KEYS` (advances when 3+ entries gain `wrapper` set AND consumer code needs zone-driven iteration) | (forward marker, filed Wave 160) | 3 |
| AD-723a-3b | Zone-driven ordering (dispatcher iterates by `injection_zone` when consumer requests deterministic ordering across DM/WR paths) | (forward marker, filed Wave 160) | 3 |
| AD-722a-4 | Auto-correction loop on high-magnitude divergence — **SHIPPED Wave 160** (default OFF; re-modulates prosody only; per-utterance budget; DivergenceResult gains `corrected: bool`; `runtime.divergence_corrections` cleared at reply-entry; `apply_voice_modulation` gains kw-only `noise_scale_factor`/`length_scale_factor` default-1.0 no-op) | [#613](https://github.com/seangalliher/ProbOS/issues/613) | 3 |
| AD-722a-4-1 | Per-emotion correction factors (advances when divergence-history analytics show emotions need different correction strengths) | (forward marker, filed Wave 160) | 4 |
| AD-722a-4-2 | Multi-utterance correction learning (advances when correction success rate stable above 60% for 100+ corrections OR adaptive baselines required) | (forward marker, filed Wave 160) | 4 |
| AD-730-2 | Multi-image DM policy — **SHIPPED Wave 160** (hard cap 8 → HTTP 413; PIL downscale to 1024px box, AD-731 invariant preserved via NEW refs; per-Captain rolling 24h budget 50 → HTTP 429 with Retry-After; no new pip deps) | [#632](https://github.com/seangalliher/ProbOS/issues/632) | 2 |
| AD-730-2-1 | Persistent budget tracker — **SHIPPED Wave 161** (JSON sidecar at `<data_dir>/image_budget.json`, configurable via `AttachmentsConfig.image_budget_path`, atomic temp-file + `os.replace`, persisted on append AND prune, Tier-2 throughout) | [#656](https://github.com/seangalliher/ProbOS/issues/656) | 3 |
| AD-730-2-1a | Throttle persistence writes (advances when observed write amplification on a heavy-image session exceeds 1 write per DM AND total file size > 64 KB) | (forward marker, filed Wave 161) | 4 |
| AD-730-2-1b | Migrate to `ConnectionFactory`-backed sidecar storage (advances when AD-697/698 Protocol lands a non-SQLite backend AND a second runtime-state-with-disk-sidecar AD also ships) | (forward marker, filed Wave 161) | 4 |
| AD-730-2-2 | Per-agent_type budget override (advances when analytics workloads need higher budgets than dialogue agents) | (forward marker, filed Wave 160) | 4 |
| AD-722b-4 | Fleet-level avatar telemetry stream (one WS, fan-out by agent_id) — **SHIPPED Wave 160** (new endpoint `/api/agent/avatar-telemetry/stream`; per-agent endpoint preserved; every frame carries `agent_id`; `fleet_stream_enabled` default-ON; HXI hook stub `useFleetAvatarTelemetry`; per-agent store migration deferred to AD-722b-4a) | [#601](https://github.com/seangalliher/ProbOS/issues/601) | 3 |
| AD-722b-1 | Crew-scope auth substrate for telemetry surfaces — **SHIPPED Wave 161** (new `src/probos/routers/auth.py` with `require_crew_scope` HTTP `Depends` and `verify_ws_token` pre-accept WS gate; `hmac.compare_digest` constant-time compare; new `AuthConfig.crew_scope_token: str = ""` default-OFF; applied to 4 endpoints — 2 HTTP + 2 WS; first auth substrate in the codebase) | [#598](https://github.com/seangalliher/ProbOS/issues/598) | 3 |
| AD-722b-1a | MagicMock(spec=SystemConfig) test fixture cleanup; remove routers/auth.py defensive guard — **SHIPPED Wave 162** (7 sites migrated to real `SystemConfig()`; `isinstance(token, str)` guard removed from `_configured_token`; 3 additional test helpers got `cfg.auth = AuthConfig()` to preserve empty-token=auth-disabled contract; net test delta 0) | [#657](https://github.com/seangalliher/ProbOS/issues/657) | 3 |
| AD-729a | Peer-observation Standing Orders extension — **SHIPPED Wave 162** (new `config/standing_orders/peer_observation.md` with 5 sections verbatim from Captain ruling; cross-references from `ship.md` and `counselor.md`; +7 pytest tests; unblocks AD-729 capability AD) | [#588](https://github.com/seangalliher/ProbOS/issues/588) | 3 |
| AD-720d-2.1 | Captain vision-capability approval flow — **SHIPPED Wave 162** (3 new endpoints `vision-capability/{propose,approve,history}`; new `CallsignRegistry.set_vision_capable`; new `avatars/vision_proposal_history.py` sidecar; 2 new EventType values; +8 pytest tests; AD-731 invariant preserved) | [#645](https://github.com/seangalliher/ProbOS/issues/645) | 3 |
| AD-720d-2.1a | HXI UI surface for Captain pending-approval list (advances when AD-720d-2.1 ships AND Captain operates ProbOS for >7 days with multiple pending vision-capability proposals queued) | (forward marker, filed Wave 162) | 4 |
| AD-720d-2.1b | Auto-deny TTL when Captain unresponsive for >N hours (advances when ProbOS adopts an autonomous-Captain mode) | (forward marker, filed Wave 162) | 4 |
| AD-706c-1 | Browser Tool visual verify via vision tier — **SHIPPED Wave 162** (new `verify(expectation)` action on BrowserTool, tier-1; screenshot via `AttachmentStore.write` SHA-256 ref; vision LLM call returns `{ok, observation}`; honest-degrade when vision tier unconfigured/unavailable; new `EventType.BROWSER_VERIFY_OBSERVED`; +10 pytest tests; AD-731 invariant preserved) | [#642](https://github.com/seangalliher/ProbOS/issues/642) | 3 |
| AD-706c-1a | Journal aggregation for verification pass/fail rates (advances when AD-674 graduated-initiative calibration needs the signal) | (forward marker, filed Wave 162) | 4 |
| AD-706c-3 | Cloud vision API integration — Anthropic computer-use beta (advances when an operator configures a cloud key AND opts in via explicit flag) | (forward marker, filed Wave 162) | 4 |
| AD-722a-1 | Vision-LLM intent-vs-render divergence detector — **SHIPPED Wave 162** (new `avatars/vision_intent_divergence.py` with detector + `VisionLLMRateLimit` shared with AD-722e-2 + `is_render_phrased` AD-727 #8 enforcer; default-OFF flag; 3/hr/agent cap; runtime-constructed; `DivergenceDetector` callsite wiring deferred until AD-721i ships) | [#610](https://github.com/seangalliher/ProbOS/issues/610) | 3 |
| AD-722a-1a | HXI surface for vision-divergence events in SelfImageTab (advances when AD-721i backend renderer ref lookup is stable AND vision_intent_divergence_enabled flips True) | (forward marker, filed Wave 162) | 4 |
| AD-722e-2 | Vision-LLM self-render coherence verifier — **SHIPPED Wave 162** (new `cognitive/self_render_verify.py` REUSING AD-722a-1's VisionLLMRateLimit + is_render_phrased; default-OFF; 3/hr/agent cap; AD-727 rule #1 read-only-on-trust verified by source-scan test; AD-731 invariant preserved; self_perception.py wire-up deferred until AD-721i ships) | [#644](https://github.com/seangalliher/ProbOS/issues/644) | 3 |
| AD-722e-2a | HXI SelfImageTab surface for render-coherence observations (advances when AD-721i ships AND self_render_verify_enabled flips True) | (forward marker, filed Wave 162) | 4 |
| AD-722a-2 | Chain-path divergence detection at compose-step emit — **SHIPPED Wave 162** (new canonical `CognitiveAgent.mark_chain_output_emitted` hook + `chain_divergence_buffer_for` accessor; per-audience ring buffer maxlen=8; wired from chain compose consumer at `cognitive_agent.py:2934`; new `EventType.DIVERGENCE_OBSERVED_CHAIN` with `path_tag="chain"`; +10 pytest tests; AD-722a DM-path unchanged) | [#611](https://github.com/seangalliher/ProbOS/issues/611) | 3 |
| AD-722a-2a | Thread `intent_self_tag` and `applied_modulation_rules` through `_execute_sub_task_chain` (advances when chain phases reliably populate these signals) | (forward marker, filed Wave 162) | 4 |
| AD-721d-2 | Counselor-mediated avatar revision — **SHIPPED Wave 162** (new `mediate_appearance_revision` intent on CounselorAgent + `_mediate_appearance_revision` handler; new `POST /api/agent/{id}/appearance/mediate` endpoint using `intent_bus.send(IntentMessage(target_agent_id=...))`; new `EventType.APPEARANCE_REVISION_MEDIATED`; +8 pytest tests) | [#618](https://github.com/seangalliher/ProbOS/issues/618) | 3 |
| AD-721d-2a | `source` field on ProposalEntry when AD-721d-1 doesn't carry one (advances when Captain audit signal is needed) | (forward marker, filed Wave 162) | 4 |
| AD-721d-2b | Per-domain mediator selection (Engineering officer mediates engineering avatars) (advances when >=2 domain agents need their own avatar palettes mediated) | (forward marker, filed Wave 162) | 4 |
| AD-721d-2c | HXI button + modal for Counselor-mediated revision in CrewAvatarPopout (advances when Captain operates mediated revision more than the Captain-driven one OR HXI polish wave is scheduled) | (forward marker, filed Wave 162) | 4 |
| AD-720a-1 | PDF / DOCX / XLSX document text extraction — **SHIPPED Wave 162** (3 new permissive deps pypdf BSD-3 + python-docx MIT + openpyxl MIT; dispatch table in `text_extractor.py`; page/row/byte caps; Tier-2 parser-exception bubbling; `vision_dispatch.py` PDF gate extended to DOCX/XLSX; default-OFF flag `AttachmentsConfig.pdf_extraction_enabled`; +12 pytest tests; AD-731 invariant preserved) | [#562](https://github.com/seangalliher/ProbOS/issues/562) | 3 |
| AD-720a-1-1 | Flip `pdf_extraction_enabled` to True after operator feedback confirms extraction quality | (forward marker, filed Wave 162) | 4 |
| AD-720a-1-2 | OCR pipeline for scanned PDFs (image-bearing pages) | (forward marker, filed Wave 162) | 4 |
| AD-728 | Vision-LLM render-coherence mirror function — **SHIPPED Wave 163** (new `avatars/render_verification.py` with `RenderCoherenceResult` + module-level `verify_render_coherence(runtime, agent_id, trigger, ...)` REUSING AD-722a-1's `VisionLLMRateLimit` scope `render_verification` + `is_render_phrased`; three triggers — `captain_command` slash `/verify-render`, `divergence_followup` gated by new `render_verification_followup_enabled` flag, `agent_initiated_stub` hard-rejected; default-OFF `render_verification_enabled`; 3/hr/agent cap; phrasing re-prompt-then-drop; cost-discipline coherent observations not logged; new `EventType.RENDER_DIVERGENCE_OBSERVED`; AD-731 + AD-727#1 source-scan tests; +15 pytest tests) | [#586](https://github.com/seangalliher/ProbOS/issues/586) | 3 |
| AD-728a | Richer coherence scoring — replace string-compare baseline with embedding-distance scoring (advances when `RENDER_DIVERGENCE_OBSERVED` event volume exceeds 50 events/quarter) | (forward marker, filed Wave 163) | 4 |
| AD-728b | Auto-correction proposals for render divergence (advances when AD-728a embedding scoring is stable AND drift pattern catalog has ≥10 distinct categorized causes) | (forward marker, filed Wave 163) | 4 |
| AD-729 | Peer avatar perception governance contract — **SHIPPED Wave 163** (new `avatars/peer_perception.py` exports `ObservationRegister`/`PeerObservation`/async `observe_peer`/async `request_permission`/`composite_impressions_for`; four mechanical floors — reputation/routing read-only, observed opt-out via `CrewProfile.peer_perception.enabled`, backend-render-only, cross-federation `federation_review_required` honest-degrade; new `PeerPerceptionProfile` dataclass on `CrewProfile`; 5 new EventType values; 3 new `AvatarsConfig` fields default-OFF; persistence via `records_store.write_entry` artifact `peer_observation`; permission grants single-use 5-min TTL deny-silent default; +18 pytest tests with real `AgentRegistry`-shape fixture per BF-287; AD-731 invariant preserved) | [#587](https://github.com/seangalliher/ProbOS/issues/587) | 3 |
| AD-729-impressions-hookup | Wire `composite_impressions_for` into `project_self_perception` (advances when AD-729a Standing Orders ship AND ≥1 officer certified per AD-729b) | (forward marker, filed Wave 163) | 4 |
| AD-729-capability-flip | Flip `peer_perception_enabled` default to True for crew agents (advances when AD-729a ships AND ≥3 officers passed AD-729b certification) | (forward marker, filed Wave 163) | 4 |
| AD-722a-6 | Cross-agent intent-vs-presentation divergence observation — **SHIPPED Wave 163** (new async `observe_peer_divergence` in `avatars/peer_perception.py` consuming AD-722a-1 `runtime.divergence_history` and delegating to AD-729 `observe_peer` for governance; pure-template `_format_divergence_summary`; three pre-delegation gates + AD-729's eight; dual default-OFF flags `cross_agent_divergence_observation_enabled` AND `peer_perception_enabled`; new `EventType.CROSS_AGENT_DIVERGENCE_OBSERVED`; +10 pytest tests; AD-731 invariant preserved) | [#615](https://github.com/seangalliher/ProbOS/issues/615) | 3 |
| AD-722a-6-flip | Flip `cross_agent_divergence_observation_enabled` default to True for OPERATIONAL register (advances when AD-729a Standing Orders ship AND AD-729 capability is default-ON for crew) | (forward marker, filed Wave 163) | 4 |
| AD-722b-5 | Federation cross-mesh telemetry push — **SHIPPED Wave 162 (LOCAL-MESH PORTION ONLY)** (new `federation/telemetry_relay.py` with FederationTelemetryRelay + PeerTelemetrySubscription; subscription registration + per-peer outbound rate-limit + agent_id filter + pluggable emit callback; +8 pytest tests; federation hop forward-marked AD-722b-5a) | [#602](https://github.com/seangalliher/ProbOS/issues/602) | 3 |
| AD-722b-5a | Wire `FederationTelemetryRelay.set_emit_callback` to `FederationBridge.forward_telemetry` (advances when AD-480e/g matures the bridge with a streaming/relay primitive — the bridge today exposes only `forward_intent` single-shot RPC) | (forward marker, filed Wave 162) | 4 |
| AD-722b-5b | HXI surface to render remote agents with `origin_mesh_id` badge (advances when AD-722b-5a ships AND multi-mesh deployments are in production) | (forward marker, filed Wave 162) | 4 |
| AD-722b-1b | Apply `require_crew_scope` to remaining read endpoints (chat history, agent profile, etc.) (advances when AD-722b-1 ships AND any auth-required-endpoint feature request lands) | (forward marker, filed Wave 161) | 4 |
| AD-722b-1c | Federation-bridge JWT verification (advances when AD-480 federation framework adds cross-mesh agent reads) | (forward marker, filed Wave 161) | 4 |
| AD-722b-1d | Token rotation + TTL (advances when any single deployment runs > 90 days with a static secret OR security scanner flags long-lived shared-secret use) | (forward marker, filed Wave 161) | 4 |
| AD-722b-4a | HXI fleet-hook integration — **SHIPPED Wave 161** (`useFleetAvatarTelemetry` wired into `CognitiveCanvas.tsx`; new `useStore.avatarTelemetry` Map + `setAvatarTelemetryFrame` action; snapshot/diff/ping/error frame handling; per-agent `SelfImageTab` WS unchanged; bundle hash changed `index-BDgoocuQ.js` → `index-D0tUvFeA.js` proving new code ships) | [#655](https://github.com/seangalliher/ProbOS/issues/655) | 4 |
| AD-722b-4b | Migrate `SelfImageTab.tsx` per-agent WS consumer to read from `useStore.avatarTelemetry` (advances when `avatarTelemetry` map reaches 2+ canvas consumers AND fleet endpoint snapshot+diff parity with per-agent endpoint is verified by integration test) | (forward marker, filed Wave 161) | 4 |
| AD-722b-4c | Canvas-side selectors `useAgentEmotion(agent_id)` + `useAgentWorkingState(agent_id)` (advances when more than one canvas component reads `avatarTelemetry` directly AND re-render cost becomes measurable) | (forward marker, filed Wave 161) | 4 |
| AD-722b-4-1 | Dynamic crew membership during fleet-stream lifetime (advances when crew spawn/despawn during stream is observed in production) | (forward marker, filed Wave 160) | 4 |
| AD-726 | DM post-LLM cleanup chain extracted into `DmReplyPipeline` (8 ordered steps; `agent_chat` shrinks 574→~305 lines) — **SHIPPED Wave 160 (partial close of #584)** (pre-LLM `DmContextPrep` → AD-726a, `DmPromptAssembler` → AD-726b, frozen cross-phase shapes + snapshot fixture suite → AD-726c) | [#584](https://github.com/seangalliher/ProbOS/issues/584) | 3 |
| AD-726a | Pre-LLM `DmContextPrep` extraction (AD-725 targeted-recall, AD-730 vision-message build, AD-720d text augmentation, AD-722 self-observation refresh) | (forward marker, filed Wave 160) | 3 |
| AD-726b | `DmPromptAssembler` extraction from `cognitive_agent.py:_build_user_message` DM branch | (forward marker, filed Wave 160) | 3 |
| AD-726c | Frozen cross-phase shapes (`DmObservation`, `DmReply`) + byte-identical snapshot fixture suite | (forward marker, filed Wave 160; advances when AD-726a + AD-726b have both landed) | 3 |
| AD-722e | Visual self-perception via image rendering (agent compares rendered avatar vs intent) | (forward marker, filed Wave 140) | 4 |
| AD-722-1 | Modulation rule table → YAML/JSON manifest (TS + Python single source of truth; closes byte-parity duplication) | (forward marker, filed Wave 140) | 4 |
| AD-723 | Ship as persistent shared virtual space — co-presence protocol, agent-position state, multi-agent extension of AD-722 telemetry (extension point) | (filed after AD-722) | 4 |
| AD-723-C *(Commercial)* | Polished multi-user 3D ship-interior UI, world layout, room semantics, meeting surfaces, operator controls — builds on AD-723 protocol | (commercial overlay) | — |
| AD-724 | Away-mission protocol — agent embodiment in external virtual worlds (VRChat / open metaverse), episodic memory of places | (filed after AD-723) | 4 |

**Wave 151 / Wave 152 — vision DM payload chain:**

| AD | Title | Issue | Priority |
|----|-------|-------|----------|
| AD-730 | Vision pipe-through for per-agent DMs — **SHIPPED Wave 151**, partial regression resolved by AD-731 (Wave 152) | [#630](https://github.com/seangalliher/ProbOS/issues/630) | 2 |
| AD-731 | Content-addressable vision payloads (refs not bytes on the bus; receiver dereferences from AttachmentStore just before HTTP POST) — **SHIPPED Wave 152** (12 new tests + BF-265/BF-266/AD-730 fixture assertions inverted; +13 net) | [#637](https://github.com/seangalliher/ProbOS/issues/637) | 1 |
| AD-637z2 | Remove BF-265 transport strip after AD-731 lands — **CLOSED-AS-PART-OF-AD-731 (Wave 152)** | [#639](https://github.com/seangalliher/ProbOS/issues/639) | 1 |
| AD-731a | Cross-host attachment distribution (parent forward marker; single-host store assumption deferred from AD-731) | [#638](https://github.com/seangalliher/ProbOS/issues/638) | 3 |
| AD-731a-1 | HTTP fetch for cross-host single-tenant attachment retrieval | (sub-marker under AD-731a) | 3 |
| AD-731a-2 | NATS Object Store integration for cross-mesh attachment distribution; retires federation/bridge.py vision_messages strip | (sub-marker under AD-731a) | 3 |
| AD-731a-3 | Mime-only fast path in sender (skip blob read for image attachments) | (sub-marker under AD-731a, optional) | 4 |
| AD-732 | Dedicated vision LLM tier + honest degrade (`vision` is the fourth peer of `fast`/`standard`/`deep`; `AttachmentsConfig.vision_tier` default flips to `"vision"`; unconfigured OR unhealthy returns `VISION_UNCONFIGURED_MESSAGE`/`VISION_UNHEALTHY_MESSAGE`) — **SHIPPED Wave 153** (15 new tests; +15 net) | [#640](https://github.com/seangalliher/ProbOS/issues/640) | 1 |
| AD-732a | Per-agent vision tier override (`agent.vision_tier` config — different model for an Imaging Officer than the rest of the crew) | (forward marker) | 4 |
| AD-732b | Vision tier autodetect on startup (probe localhost:11434 and auto-uncomment qwen3.6:27b if available — zero-config OSS magic) | (forward marker) | 4 |
| AD-732c | Vision tier hot-reload on config change (operator edits system.yaml; vision tier reloads without restart) | (forward marker) | 4 |
| AD-733 | Live camera stream perception (umbrella). HXI samples webcam frames → AttachmentStore → `vision_observation` intent on the bus → ObserverAgent maintains visual working memory + emits configured visual events. Same wire format / vendor adaptation as AD-731/BF-268; the new layer is cadence and proactive policy. **Demo-grade capability** — paired with AD-721 avatar this is what makes the mesh feel alive. | [#641](https://github.com/seangalliher/ProbOS/issues/641) | 4 |
| AD-733a | Real-time vision tier (`llm_model_vision_fast` for sub-1s per-frame inference + `llm_model_vision_deep` for occasional narrative summaries) + agent visual working memory (last-N-frames hot buffer). **Identity matching** against the Captain Card avatar (AD-739) — "person in frame" → "the Captain in frame" when avatar_ref matches. | (sub-marker under AD-733) | 4 |
| AD-733b | ObserverAgent + proactive event surfacing (graduated initiative for visual events; AD-674/AD-675 calibration extended from text to perceptual triggers) | (sub-marker under AD-733) | 4 |
| AD-739 | Captain Card — operator self-card always-in-context across all CognitiveAgent prompts (identity, voice/style anchors, active context, optional `avatar_ref` for AD-733a recognition coupling). System-maintained via Dreaming + correction-feedback (NOT agent-self-edited per governance); KnowledgeStore-versioned. Closes the "every agent re-derives operator context from episodic recall" gap. **Pattern-absorbed from letta-ai/letta core memory blocks** (always-in-context half adopted; agent-edited half rejected on governance grounds). | [#649](https://github.com/seangalliher/ProbOS/issues/649) | 3 |

**Wave 154 — DM hardening + multimodal small wins + HXI polish:**

| AD | Title | Issue | Priority |
|----|-------|-------|----------|
| AD-719c | @-picker keyboard navigation (↑/↓ cycle, Tab confirms, scroll-into-view) — **SHIPPED Wave 154** (+4 Vitest tests) | [#548](https://github.com/seangalliher/ProbOS/issues/548) | 3 |
| AD-718d-1 | Voice modulation activity indicator (`ModulationIndicator` SVG dim-pulse next to per-agent Speak toggle) — **SHIPPED Wave 154** (+2 Vitest tests) | [#553](https://github.com/seangalliher/ProbOS/issues/553) | 3 |
| AD-730-1-1 | WardRoomThreadDetail drag/drop + paste image — **SHIPPED Wave 154** (+3 Vitest tests; #647 closed as duplicate pre-flight) | [#646](https://github.com/seangalliher/ProbOS/issues/646) | 3 |
| AD-720d-1 | Multi-image batch send + per-attachment timing in episode outcomes + `multi_image_warn_threshold` soft warning — **SHIPPED Wave 154** (+5 pytest tests; 3 production destructure sites + 4 test destructure sites updated) | [#563](https://github.com/seangalliher/ProbOS/issues/563) | 3 |
| AD-720e | Audio attachment playback (mpeg/mp4/ogg + existing webm/wav) — **SHIPPED Wave 159** (+5 pytest + 3 Vitest tests; allow-list + magic-byte signatures + `<audio controls>` render in IntentSurface; WardRoom paste accepts audio chip-only; AD-731 SHA-ref invariant preserved; AD-705a forward marker for transcription; AD-720e-1/-2/-3 forward markers filed) | [#566](https://github.com/seangalliher/ProbOS/issues/566) | 3 |
| AD-738e-2 | Refs-trailer standing rule for orphan sub-ADs — **SHIPPED Wave 159** (BUILDER-EXECUTION-PLAN standing rule; DECISIONS AD-738e-1's prosody forward marker renumbered to AD-738e-2-prosody to free the AD-738e-2 slot for #653) | [#653](https://github.com/seangalliher/ProbOS/issues/653) | 3 |
| AD-725 | Targeted sub-intent dispatch on DM one-shot path — **SHIPPED Wave 159** (LookupDispatcher + SubintentClassifier Protocol + regex v1 ladder; DmTargetedLookupConfig default OFF; 4 firewall contracts: one-lookup-per-turn, read-only, hard timeout, no intent_bus; prepends recall block into message_text in `agent_chat`; AD-725-1/-2/-3/-4/-5/-6 forward markers filed) | [#583](https://github.com/seangalliher/ProbOS/issues/583) | 3 |
| AD-724-1 | DM sanity gate one-shot retry on rejection — **SHIPPED Wave 154** (+ shared with -2/-5 boundary tests) | [#627](https://github.com/seangalliher/ProbOS/issues/627) | 3 |
| AD-724-2 | DM repetition similarity beyond exact-prefix (stdlib `difflib.SequenceMatcher`) — **SHIPPED Wave 154** | [#628](https://github.com/seangalliher/ProbOS/issues/628) | 3 |
| AD-724-5 | DM sanity gate lifted into WR/chain reply paths via shared `apply_dm_sanity` helper — **SHIPPED Wave 154** (+12 pytest tests across -1/-2/-5) | [#629](https://github.com/seangalliher/ProbOS/issues/629) | 3 |

### Forcing-function deferrals

(Forward dependencies satisfied; build when need surfaces.)

| AD | Forcing function |
|----|------------------|
| AD-574c-ii | DM conversation convergence (full ProfileChatTab refactor — substrate ready) |
| AD-641g-1-1 | Flip `SubTaskExecutor` to `await` ANALYZE results from NATS subjects |

### Commercial-tagged items

(Live in private commercial repo; OSS surface is the extension point only.)

| AD | Title |
|----|-------|
| AD-693 | Federation Knowledge Sync (cross-instance edge synchronization) |
| AD-694 | Kùzu Migration (graph-DB upgrade path for `knowledge_edges`) |

----

## Bug Tracker

OSS bugs are tracked as GitHub issues with the `bug` label:
<https://github.com/seangalliher/ProbOS/issues?q=is%3Aopen+label%3Abug>.

Closed bug-fix history (BF-001 through BF-247) is preserved in
[roadmap-era-5-completed.md](roadmap-era-5-completed.md#bug-tracker).

----

## Era History

- **Era I — Genesis**: bootstrap, agent registry, intent bus, episodic memory ([progress-era-1-genesis.md](../../progress-era-1-genesis.md))
- **Era II — Emergence**: Hebbian routing, dreaming, self-modification, federation transport ([progress-era-2-emergence.md](../../progress-era-2-emergence.md))
- **Era III — Product**: HXI, Ward Room, Captain identity, alert conditions ([progress-era-3-product.md](../../progress-era-3-product.md))
- **Era IV — Evolution**: ontology, billet registry, qualification programs, naval discipline ([progress-era-4-evolution.md](../../progress-era-4-evolution.md))
- **Era V — Unification**: Oracle absorption, knowledge graph, brain-enhancement (AD-641 family), commercial-overlay seam ([progress-era-5-unification.md](../../progress-era-5-unification.md))
