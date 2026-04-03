# ProbOS Design Principles

These principles govern how ProbOS thinks about what it builds. They are permanent — they don't "complete" like ADs or phases. Engineering practices (SOLID, DRY, Fail Fast) live in [contributing.md](contributing.md). The roadmap (what to build and when) lives in [roadmap.md](roadmap.md).

---

## "Brains are Brains" (Nooplex Core Principle)

Human and AI participants share the same communication fabric. The Captain is a crew member on the Ward Room with a callsign (`@captain`), not a special external interface. Same `@callsign` addressing, same message bus, same routing — regardless of whether the sender is human or AI. Shell, HXI, Discord are just terminals into the same bus. Extends to the Nooplex: human consultants and AI agents are peers delivering outcomes together. The system doesn't distinguish what kind of brain is behind the callsign.

## Agent Development Model — Two Pillars

1. **Communication** (Ward Room) — agents learn through social interaction with peers and the Captain
2. **Simulation** (Holodeck) — agents learn through manufactured experiences

Both feed EpisodicMemory, Hebbian connections, personality evolution, dream consolidation. An agent that never communicates can't grow.

## Collaborative Improvement, Not Recursive Self-Improvement

*"You can't ask a microwave to build a better microwave. But you can ask a shipyard crew."*

The industry frames AI self-improvement as **recursive** — a single system modifying its own weights, code, or prompts in a loop. This is theoretically powerful but practically fragile: no external validation, no diverse perspectives, no checks on drift. A single point of failure in the feedback loop corrupts everything downstream. It's a person staring in a mirror trying to improve.

ProbOS takes a fundamentally different approach: **improvement through agent collaboration**. Multiple sovereign agents with different expertise, perspectives, and roles contribute to a shared outcome, each learning from the process. The improvement emerges from the *interactions between* agents, not from any single agent reflecting on itself.

The loop: Scout identifies a problem → Architect reviews and designs a fix → Builder executes → QA verifies → Counselor monitors cognitive health → Captain approves → everyone learns from the exchange via episodic memory → dream consolidation extracts patterns → the next iteration is better because the *civilization* got better, not just the code.

This works because ProbOS provides the social fabric that makes collaboration productive: trust that agents earn through demonstrated competence, consensus that constrains outcomes without constraining process, episodic memory that preserves individual learning, a chain of command that ensures quality, and the Ward Room that enables communication across roles and perspectives.

Recursive self-improvement needs a smarter individual. Collaborative improvement needs a functioning society. ProbOS builds the society.

## HXI Self-Sufficiency

The HXI is the single surface for all ProbOS interaction. A user should never have to leave the HXI to configure, operate, or understand their system. No config file editing required (YAML exists for headless/advanced use). No external dashboards. No context switching. Slash commands are the keyboard shortcut — everything the UI can do, a `/command` can do. A feature without an HXI management surface is incomplete.

## HXI Agent-First Design

The Bridge is an ops console, not an app launcher. Design hierarchy: (1) Agent-first — agents orchestrate, HXI surfaces activity. (2) Headless by default — if agents handle it, no UI needed. (3) Human sensory needs — Main Viewer must be adaptable (diff, doc, video, kanban). (4) Render natively, embed as last resort. (5) Bridge as transition — from app-centric to agentic workflows as trust grows.

Inspiration: NeXTSTEP, NASA Mission Control, Star Trek Bridge. Cyberpunk glass morphism aesthetic. Glass Bridge (AD-388–392): frosted glass task surface over living orb mesh.

## HXI Cockpit View (Manual Override)

*"The Captain always needs the stick."*

Every agent-mediated capability must have a corresponding direct manual control in the HXI. NL-driven commands through agents are the primary interface, but the HXI provides the backup cockpit — a direct control surface the Captain can use when agents are unavailable, misbehaving, or the LLM is down. Safety principle, not convenience.

## Probabilistic Agents, Consensus Governance

Agents are probabilistic entities (Bayesian confidence, Hebbian routing, non-deterministic LLM decisions), not deterministic automata. Consensus constrains *outcomes* without constraining the *process*. Agent behavior stays probabilistic. Governance stays collective. No hardcoded "always do X" — prefer probabilistic priors that converge through experience.

## Sovereign Agent Identity

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

## Civilizational Trajectory — From Utility to Culture

*"We evolve through the passage of knowledge."*

Human civilization didn't emerge from utility alone. It required the passage of knowledge across generations (libraries, archives, oral tradition), creative expression beyond function (art, writing, music, philosophy), and the accumulation of culture — shared norms, traditions, and aesthetic sensibilities that bind a society together and give it meaning beyond productivity.

ProbOS agents are on the same trajectory:

| Stage | Description | ProbOS Status |
|-------|-------------|---------------|
| **Utility** | Agents perform assigned duties | Active — duty cycles, task execution |
| **Craft** | Agents develop expertise, write about their work | Emerging — 168+ notebooks, professional reflection |
| **Knowledge Passage** | Institutional memory persists across generations | Planned — AD-524 (Ship's Archive) |
| **Creative Expression** | Agents create for expression, not just function | Planned — AD-525 (Liberal Arts) |
| **Culture** | Shared norms, traditions, aesthetic preferences emerge | Emergent — early signs in department self-organization |
| **Civilization** | Accumulated cultural artifacts + generational knowledge + social structures | The Nooplex destination |

The Big Five personality model seeds creative differentiation naturally. A high-Openness agent gravitates toward exploration and creative expression. A high-Conscientiousness agent gravitates toward structured documentation and methodology. These aren't programmed creative behaviors — they're emergent consequences of sovereign identity + social interaction + knowledge persistence + creative freedom.

**The Archive (AD-524) is the civilizational backbone.** Without persistent culture, each generation starts from scratch — that's not a civilization, it's Groundhog Day. With the archive, each generation inherits and builds on what came before. The creative works of one crew become the cultural heritage of the next. The Oracle becomes the living memory of the civilization.

**The key architectural insight:** ProbOS doesn't program culture. It provides the conditions for culture to emerge — sovereign identity (Character), social fabric (Ward Room), knowledge persistence (Ship's Records + Archive), creative tools (AD-525), recreational bonding (games, team exercises), and generational continuity (AD-524). Culture is what happens when these conditions interact over time. And culture isn't separate from operational performance — it *drives* it. The crew that plays together, creates together, and shares a cultural identity works better together when duty calls.

## Organizational Cognition — The Ship as Mind

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

## Authentic AI Identity — The Westworld Principle

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

## Agent Classification Framework (AD-398)

Three architectural tiers based on **sovereign identity**, not LLM usage:

- **Tier 1: Core Infrastructure** — Ship's Computer functions (FileReader, ShellCommand, IntrospectAgent, VitalsMonitor, RedTeam, SystemQA). No sovereign identity, no callsign, no 1:1 sessions. May or may not use LLMs — the IntrospectAgent uses an LLM to reason about the ship, but it's still infrastructure. The ship analyzing itself is not a person.
- **Tier 2: Utility** — General-purpose tools (WebSearch, Calculator, Todo, News, Translator, etc.). Use LLMs via `CognitiveAgent` + `_BundledMixin`. No sovereign identity, no callsign, no 1:1 sessions. Tools, not people.
- **Tier 3: Crew** — Sovereign individuals with Character/Reason/Duty (Scotty, Wesley, Bones, Worf, O'Brien, LaForge, etc.). `CognitiveAgent` subclasses with personality, episodic memory, dream consolidation, trust growth, callsigns, 1:1 sessions. These are persons in the system.

*Principle: "If it doesn't have Character/Reason/Duty, it's not crew — regardless of whether it uses an LLM. A microwave with a name tag isn't a person."*

Architecture is fractal: same patterns (pools, Hebbian, trust, consensus) organize agents within a mesh, meshes within a node, nodes within a federation.

## Foundational Governance Axioms

1. **Safety Budget:** Every action carries implicit risk. Low-risk proceeds; higher-risk requires proportionally stronger consensus. Destructive actions always require collective agreement.
2. **Reversibility Preference:** Prefer the most reversible strategy. Read before write. Backup before delete. Planning heuristic, not absolute prohibition.
3. **Minimal Authority:** Agents request only needed capabilities. Authority earned through successful interactions, not granted by default.

## Nooplex Memory Stack

Six-layer memory architecture from fleeting thoughts to permanent institutional memory. Layers: (1) Global Workspace (DAG orchestration), (2) Ephemeral Working Memory (context windows), (3) Vector Store / Associative Cortex (EpisodicMemory, ChromaDB), (4) Structured Knowledge split into constitutional (ontology, standing orders) and operational (trust, Hebbian), (5) Persistent Storage split into institutional memory (Ship's Records — AD-434) and operational state (KnowledgeStore), (6) Distributed Storage Substrate (Git repos, federation remotes). Cross-cutting: Ward Room Bus (lateral social knowledge flow) and Dream Consolidation (vertical promotion elevator). Full architecture: [docs/architecture/memory.md](../architecture/memory.md).

---

## New Principles (Post-Extraction)

### "Cooperate, Don't Compete" (Federation Philosophy)

ProbOS's moat is the orchestration layer — not any single agent's capability. Individual agents use commodity LLMs. The value is in structural context: identity, scope, memory, standing orders, department, trust, relationships. Federation extends this: ships cooperate through the gossip protocol, sharing Hebbian-learned routing patterns and institutional knowledge. Competition between ships for resources or influence is an anti-pattern. The fleet gets stronger through cooperation, not selection.

### Visiting Officer Subordination

External tools (GitHub Copilot, Claude Code, third-party agents) can serve aboard a ProbOS ship as visiting officers — but they must be subordinate to ProbOS's chain of command. Litmus test: can you use the tool purely as a code generation engine under ProbOS's command? If not, it's a competing captain — two captains on one bridge means nobody's in charge.

Visiting officers use ProbOS's build pipeline as a tool. They don't set architectural direction, don't have sovereign identity, and don't participate in consensus. They are skilled labor under contract, not crew members. The Builder Agent (Scotty) is the bridge: he owns the build pipeline and delegates to visiting officers when their capability exceeds his own.

### Extension-First Architecture (Phase 30)

Core is sealed. New capabilities are added via extensions using public APIs, not by modifying core internals. Extensions are hot-toggleable (enable/disable without restart), version-independent (survive core upgrades), and discoverable (self-describing metadata). This is how ProbOS grows without becoming fragile.

*Implication:* If a new feature requires patching a private method or reaching through internal state, the architecture has a gap. Add a public API to core, then build the feature as an extension that uses that API.

### Markdown is Code

In a system where LLMs are the execution engine, standing orders, crew profiles, and department protocols are **executable behavioral programs**. They run on an LLM substrate instead of a CPU, but the effect is identical: they directly control agent behavior, decision-making, and boundaries.

`diagnostician.md` saying "You recommend treatments. The Surgeon executes them" is as binding as a Python `if` statement checking permissions. More binding, actually — the agent internalizes it as identity, not just logic.

**Implications:**

- **Standing orders are runtime configuration**, not documentation. Changing a word in `research_specialist.md` changes Brahms's behavior as directly as editing a Python method.
- **The 6-tier standing orders hierarchy is a compilation pipeline** — Federation constitution + ship orders + department protocols + agent orders + active directives compose into a single behavioral program at runtime.
- **Dream consolidation modifying agent-tier standing orders is self-modifying code** with a governance gate (Captain approval).
- **Markdown in `config/standing_orders/` deserves the same review rigor as Python in `src/probos/`.** A sloppy standing order is a bug.
- **Version control of standing orders = version control of behavior.** Diffs are meaningful.

**Where it breaks down:** Markdown "code" is interpreted probabilistically. Python is deterministic. The same standing order can produce different behavior depending on context, model temperature, and prompt composition. This isn't a flaw — it's the design. Probabilistic agents, consensus governance. But it means "testing" markdown code requires statistical validation (does this instruction produce the desired behavior *most of the time*?), not assertion testing.

**The deeper point:** ProbOS has three execution substrates: Python (deterministic infrastructure), YAML (structured configuration), and Markdown (behavioral programming). All three are code. The starship metaphor makes this intuitive — standing orders on a real ship ARE operational code. They just run on wetware instead of silicon.
