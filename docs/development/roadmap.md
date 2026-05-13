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
| AD-718f | Per-agent volume control surface | [#527](https://github.com/seangalliher/ProbOS/issues/527) | 4 |
| AD-721a | Captain's avatar editor UI | [#528](https://github.com/seangalliher/ProbOS/issues/528) | 3 |
| AD-721b | Phoneme-accurate lip-sync v1 (heuristic 5-vowel viseme driver, multi-mesh) — **SHIPPED Wave 138** | [#529](https://github.com/seangalliher/ProbOS/issues/529) | 3 |
| AD-721b-1 | Server-side rhubarb-lip-sync backend (replaces heuristic phoneme schedule) | [#559](https://github.com/seangalliher/ProbOS/issues/559) | 3 |
| AD-721b-2 | Browser-side real-audio capture via `MediaStreamDestination` | [#560](https://github.com/seangalliher/ProbOS/issues/560) | 3 |
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
| AD-721d-4 | Persist avatar proposal history across runtime restarts | [#623](https://github.com/seangalliher/ProbOS/issues/623) | 4 |
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
| AD-722c | Avatar telemetry history for analytics | (forward marker, filed Wave 140) | 4 |
| AD-722d | Auto-write telemetry summaries to Ship's Records (RecordsStore) | (forward marker, filed Wave 140) | 4 |
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
| AD-733a | Real-time vision tier (`llm_model_vision_fast` for sub-1s per-frame inference + `llm_model_vision_deep` for occasional narrative summaries) + agent visual working memory (last-N-frames hot buffer) | (sub-marker under AD-733) | 4 |
| AD-733b | ObserverAgent + proactive event surfacing (graduated initiative for visual events; AD-674/AD-675 calibration extended from text to perceptual triggers) | (sub-marker under AD-733) | 4 |

**Wave 154 — DM hardening + multimodal small wins + HXI polish:**

| AD | Title | Issue | Priority |
|----|-------|-------|----------|
| AD-719c | @-picker keyboard navigation (↑/↓ cycle, Tab confirms, scroll-into-view) — **SHIPPED Wave 154** (+4 Vitest tests) | [#548](https://github.com/seangalliher/ProbOS/issues/548) | 3 |
| AD-718d-1 | Voice modulation activity indicator (`ModulationIndicator` SVG dim-pulse next to per-agent Speak toggle) — **SHIPPED Wave 154** (+2 Vitest tests) | [#553](https://github.com/seangalliher/ProbOS/issues/553) | 3 |
| AD-730-1-1 | WardRoomThreadDetail drag/drop + paste image — **SHIPPED Wave 154** (+3 Vitest tests; #647 closed as duplicate pre-flight) | [#646](https://github.com/seangalliher/ProbOS/issues/646) | 3 |

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
