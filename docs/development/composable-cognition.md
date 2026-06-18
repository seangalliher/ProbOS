# Composable Cognition — Cognitive Organs, the Spine, and the Two-Scale Nervous System

**Status:** Foundational concept (proposed). **Date:** 2026-06-18.
**Pilot:** the Attention organ — epic #975, [attention-architecture.md](attention-architecture.md), [attention-research.md](attention-research.md).
**AD ceiling at authoring:** AD-1026 landed; AD-1027 reserved (#973); AD-1028..1032 filed (#976–#980). New ADs here open at **AD-1033**.

> **Thesis.** A ProbOS cognitive agent is an **organism**: a **spine** plus a set of
> **cognitive organs**. The spine is the agent's *central nervous system*
> (synchronous, integrated, private). The **mesh** is the *ship's nervous system*
> (asynchronous, governed, federated). The same pattern — a connective substrate
> linking cognitive units — appears at both scales with **scale-appropriate
> properties**. Society of Mind on the inside; the Nooplex on the outside; the same
> fractal at every level.

---

## 1. Why this concept

ProbOS began with agents that were *services for the OS*. It now runs a **crew — a
civilization of independent brains.** The open question is no longer "what services
does the OS offer?" but **"how is a brain composed?"** Today a `CognitiveAgent` is a
monolith with helpers and a fixed prompt-assembly pipeline. The recall arc
(BF-630→632) and the attention work (#975) showed the cost of that: capabilities
that should be distinct faculties (attention, memory, perception, valuation) are
tangled into one method with no contract, no composition, and no introspection.

The proposal: make **Cognitive Organ** a first-class concept and compose brains from
organs connected by a spine. This is not a rewrite — ProbOS already has *latent*
organs (see §5); we are **naming an emergent structure** and giving it a contract.

## 2. The model

### 2.1 Cognitive Organ — a child component, not an agent

A **Cognitive Organ** is a bounded cognitive faculty that a `CognitiveAgent` is
*composed of*. It is **not** a mesh agent. The five-part test (a capability is an
organ only if it has *all* of these — otherwise it's a plain module/helper):

1. **A distinct cognitive function** — it does one identifiable thing a mind does
   (attend, remember, perceive, value/feel, monitor-self, narrate, reflect).
2. **Persistent state across cognitive cycles** — it carries state between turns
   (not a pure function).
3. **The `perceive → decide → act` cognitive-cycle shape.**
4. **1:1 ownership** — intrinsic to *one* agent (personal), not a shared service.
5. **Introspectability** — its contribution to behavior is auditable.

**Identity & lifecycle (the load-bearing discipline):**
- **Child, not peer.** Identity is *derived* and namespaced under the parent (e.g.
  `{parent_id}.attention`). An organ is **not** in the agent registry, **not**
  addressable on the mesh, and has **no independent trust score, vote, or consensus
  standing.** It exists only as part of its parent.
- **Born with the parent, dies with the parent.** Constructed inside the parent's
  birth; torn down inside the parent's teardown. No independent spawn or death.
- **Shape, not classification.** It shares the agent *shape* (and the Society-of-Mind
  lineage, where "organs" and "agents" are the same thing), but ProbOS keeps the
  vocabulary crisp: **organs are components; agents are mesh peers.** We do *not*
  register an `AttentionAgent`; we compose an `AttentionFaculty` organ. This avoids
  the confusion other agent harnesses invite by overloading "agent."
- **Deterministic by default.** Most organs run every cognitive cycle, before the
  expensive LLM call; their work is arithmetic/structural, not reasoning. (Some
  organs — reflection, narration — may invoke the LLM; that is the exception, not the
  rule.)

### 2.2 The Spine — the agent's central nervous system

The **spine** is the in-process connective backbone the agent provides. It does three
things:
- **Composition** — holds the organ registry ("which organs compose this brain") and
  attaches/detaches organs at birth/death.
- **Cycle** — drives the `perceive → decide → act` cognitive cycle across the organs.
- **Signaling** — an in-process channel by which organs influence one another (the
  valuation organ raises arousal → the attention organ narrows; the attention organ
  selects memories → the narration organ phrases them).

The spine is **synchronous, in-process, ungoverned, and private.** You do not hold a
quorum vote between your own thalamus and hippocampus, and you do not put a network
round-trip between two of your own organs.

### 2.3 The Mesh — the ship's nervous system

The **mesh** (the intent bus + gossip + routing) is the *ship's* nervous system: it
connects **brains** (cognitive agents). It is **asynchronous, governed
(consensus/trust), and federated** (sovereign peers).

### 2.4 Same pattern, scale-appropriate properties

The fractal is real, but each scale gets its own substrate. **Conflating them is the
failure mode** (a synchronous unified mesh becomes a central scheduler; an async
governed spine puts a network hop + consensus inside a single mind).

| | **Spine** (agent NS) | **Mesh** (ship NS) |
|---|---|---|
| Coupling | **Synchronous, in-process** | **Asynchronous** (pub/sub, gossip) |
| Governance | **None** (organs aren't sovereign) | **Consensus / trust / quorum** |
| Topology | **Integrated — one self** | **Federated — sovereign peers** |
| Boundary | private to the agent | the ship-wide fabric |
| Biology | **central** nervous system | **social/peripheral** signaling between organisms |

### 2.5 The single governed boundary (sovereignty preserved)

An agent's nervous system connects to the ship's nervous system through **one
controlled gateway** — the agent's existing mesh interface. Organs do **not**
independently chatter on the mesh; the agent mediates. Exogenous signals (mentions,
alerts, camera-change, gossip) enter as an **owned inlet** that updates organ state
between turns. The CNS reaches the world through defined pathways, not every neuron
wired to the outside — same discipline, and it is how **AD-397 sovereignty** is kept.

### 2.6 The self (Minsky's "no central self," answered)

A society of organs needs something that makes it *one* mind rather than a swarm. That
is the **spine plus the agent's `instructions`** (its constitution). Not a homunculus
— a connective backbone and an identity. "Who's in charge?" — *nobody and the spine,
simultaneously.*

### 2.7 Brains within brains (recursion — allow, don't require)

An organ may itself be a composed brain (its own sub-spine + sub-organs) — e.g. a
"memory organ" composed of episodic + working + consolidation sub-organs. The
architecture **permits** this recursion but **keeps it shallow** (1–2 levels) to
start. Most organs are leaves; earn depth where a faculty genuinely is a sub-society.

## 3. The body plan (brain-region map) — and ProbOS's latent organs

The organs aren't arbitrary; they map to a real cognitive architecture, and ProbOS
already has seeds of most of them:

| Organ | Brain analogue | ProbOS today (proto-organ) |
|---|---|---|
| **Deliberation** | cortex | the LLM call (System-2) — the one expensive reasoning core organs surround |
| **Attention / gating** | thalamus | AttentionFaculty (#977, being built) |
| **Memory** | hippocampus | working memory (AD-573) + the episodic shard |
| **Valuation / affect** | amygdala | cognitive zones / arousal (AD-588) + affective salience (#908) |
| **Metacognition / self-monitoring** | prefrontal | self-monitoring (AD-504), confab guard (AD-592), source attribution (AD-568) |
| **Interoception / body sense** | insula | avatar self-observation (AD-722) |
| **Consolidation / reflection** | default-mode network | dreaming (today a shared runtime service — a "personal vs shared" candidate) |
| **Perception** | sensory cortices | the **sensorium** taxonomy (PROPRIO / INTERO / EXTERO) — already organ-flavored |

The sensorium layering is the strongest tell that ProbOS has been drifting toward
organ composition without naming it.

## 4. Prior art absorbed

The closest precedents are *academic cognitive architectures* and a few
*implementations*. None does ProbOS's exact synthesis (deterministic organs as
lifecycle-bound child components of an LLM agent, connected by a synchronous spine,
inside an async governed mesh of such agents) — so this is a **novel synthesis on
well-established shoulders.** Patterns absorbed; no code vendoring (license-clean).

**Cognitive science / architectures (the canon):**
- **Society of Mind** (Minsky, 1986) — mind = society of agents in agencies; no central
  self. The conceptual root.
- **Modularity of Mind** (Fodor, 1983) — encapsulated, domain-specific modules + a
  central system. → organ boundaries should be crisp; the spine is the central system.
- **ACT-R** (Anderson) — *the strongest precedent.* A mind composed of **modules**
  (declarative, procedural, goal, perceptual-motor), each exposing a **buffer**,
  coordinated by a central production system. → organ = module, spine = coordinator,
  the organ's output = its buffer/bid.
- **Soar** (Laird, Newell, Rosenbloom) — working memory + productions; impasse-driven
  subgoaling. → deliberate attention shifts on impasse.
- **Common Model of Cognition / Standard Model of the Mind** (Laird, Lebiere,
  Rosenbloom, 2017) — a *consensus* modular "body plan." → an agent type composes a
  canonical organ set; differentiation is compositional.
- **LIDA** (Franklin) — computational Global Workspace: attention codelets compete each
  cognitive cycle to bring coalitions into the workspace, then broadcast. → the cycle
  model for the spine + attention organ.
- **CoALA — Cognitive Architectures for Language Agents** (Sumers, Yao, Narasimhan,
  Griffiths; TMLR 2024; arXiv:2309.02427) — *the modern bridge.* Frames an LLM agent
  as modular memory components + a structured action space + a generalized
  decision procedure. → exactly our organs + spine with the LLM as the deliberation
  core; validates the approach in the LLM era.
- **Generative Agents** (Park et al., 2023) — memory/reflection/planning modules;
  retrieval = recency + importance + relevance. → feeds the salience organ.

**Implementations (GitHub — patterns absorbed, no vendoring):**
- **ROS 2** (`ros2/ros2`, Apache-2.0; "a meta operating system for robots") — nodes +
  topics *are* a robot's nervous system: many small components coordinated by a
  pub/sub graph. The canonical "nervous system = pub/sub graph of components." → our
  **mesh** is the ROS-graph at the ship scale; we keep the **spine** synchronous (a
  robot's reflex arcs aren't all on the async bus). Validates the metaphor.
- **OpenCog AtomSpace / Hyperon** (`opencog/atomspace`) — "several dozen modules" /
  MindAgents operating over a shared in-RAM hypergraph; described as "kind-of-like an
  OS kernel." The *cognitive-synergy* precedent: specialized processes (organs) over a
  shared substrate. → organs cooperate via shared state (working memory / the spine's
  signal channel); the substrate-as-kernel framing.
- **Letta (formerly MemGPT)** (`letta-ai/letta`, Apache-2.0) — stateful agents with
  self-editing memory ("memory blocks") and OS-style virtual context management. The
  *memory-organ* precedent: a persistent, self-managing memory faculty. → the memory
  organ owns and edits its own state.

## 5. Mapping onto ProbOS (you're naming a latent structure)

- `CognitiveAgent._run_cognitive_lifecycle` (perceive→decide→act) **is the proto-spine
  today** — it already drives the cycle and calls the faculties. Formalizing the spine
  makes *organ attachment* (composition) and *intra-organ signaling* explicit.
- The **intent bus is the mesh** (ship nervous system) — already exists.
- The **sensorium registry** (PROPRIO/INTERO/EXTERO) is the proto-organ catalog; the
  AttentionBid catalog (#976) generalizes it.
- **Working memory** (AD-573) is the clearest existing personal organ; the **episodic
  store** is a *shared* faculty with per-agent shards — the canonical "personal organ
  over a shared substrate."

## 6. Personal organ ⇄ shared ship faculty (a first-class design axis)

A capability can be provided as a **personal organ** (paired, sovereign, intimate,
synchronous) or a **shared ship faculty** (mesh service, governed, single-source):
- **Personal organs:** attention, working memory, valuation/affect, self-monitoring,
  interoception, narration.
- **Shared faculties:** the Git knowledge base, event log, consensus, trust network,
  the episodic *store* (with per-agent shards), the model router.
- **Rule:** personal when it's intimate to one mind's identity/sovereignty and needs
  private synchronous access; shared when it's ship-level truth, needs governance, or
  benefits from a single source. Some capabilities are *both* (a personal
  working-memory organ over a shared episodic store). **Open revisit:** dreaming and
  consolidation are currently shared runtime services — candidates to become personal
  organs.

## 7. Realization (the attention organ is the pilot — and it carries the foundation)

The epic #975 is scoped so the attention organ **establishes the whole pattern.**
Build order (dependency, not AD-number order):

1. **AD-1028 (#976)** — ContextAssembler seam + `AttentionBid` + global token budget
   (behavior-preserving, default-OFF). *Context mechanics.*
2. **AD-1033 (new)** — `CognitiveOrgan` protocol: the five-part contract + base class +
   the child-identity / born-with-parent / dies-with-parent lifecycle helpers. *Pure
   interface; the foundation.*
3. **AD-1034 (new)** — `CognitiveSpine` (thin): organ registry/composition + the
   cognitive-cycle driver + the in-process intra-organ signal channel + the single
   governed mesh boundary. Behavior-preserving (byte-identical with zero organs
   registered); the `CognitiveAgent` lifecycle is refactored to host it. *The backbone.*
4. **AD-1029 (#977)** — `AttentionFaculty`: the **first organ**, conforming to the
   AD-1033 contract, attached to the AD-1034 spine, driving the AD-1028 assembler. *The
   pilot that proves the pattern.*
5. **AD-1030 (#978)** — salience scoring · **AD-1031 (#979)** — camera as a bid (closes
   #973) · **AD-1032 (#980)** — exogenous interrupts & arousal.

## 8. Non-goals & guardrails

- **Not a rewrite.** Concept + seam + pilot + *retroactive classification* of the
  proto-organs (name them without rewriting) + *opportunistic* migration. Strangler-fig.
- **Don't metastasize.** The five-part test gates what becomes an organ; helpers stay
  helpers. Resist "everything is now an organ."
- **Don't network the spine.** The spine is synchronous, in-process, ungoverned.
- **Behavior-preserving foundations.** AD-1033/1034 ship byte-identical (default-OFF /
  zero-organ); adaptivity comes later and gated.
- **Deterministic-by-default organs** — no consensus/trust/LLM for internal calls.

## 9. Open decisions (for the Captain)

1. **Design-Principle elevation.** Should "cognitive agents are organisms — a spine
   plus organs" become a principle in `.github/copilot-instructions.md`?
   *Recommendation: prove it with the attention pilot, then elevate — concept first,
   principle once it's load-bearing.*
2. **Personal vs shared revisits.** Should dreaming/consolidation (currently shared)
   become personal organs?
3. **Recursion depth.** Keep at 1–2 levels until a real composite organ earns more.
