# Attention & Context Governance — Architecture

**Status:** Proposed (epic). **Date:** 2026-06-18.
**AD ceiling at authoring:** AD-1026 landed; **AD-1027 reserved** (#973). This epic opens at **AD-1028**.
**Evidence base:** [attention-research.md](attention-research.md) (current-state map + prior-art survey).

> One-line thesis: ProbOS has all the parts of an attention system but no
> conductor. Replace the fixed, push-style prepend chain with a **per-agent,
> deterministic Attention Faculty** that runs a Global-Workspace cycle —
> collecting *bids* from every context source, scoring them by salience, and
> selecting/ordering the winners under a global token budget.

---

## 1. Problem

Today the agent's context window is assembled **push-style**: each source
(episodic recall, working memory, visual scene, group activity, telemetry,
oracle, session history, sensorium blocks) injects itself into a **fixed ~14-step
prepend chain**, each with its own local budget. There is **no arbiter** that, in
the moment, decides what *earns* a place in the limited window and in what order.

Consequences (see the research doc for the full map):
- `cognitive/attention.py` exists but is **dead code** — never called.
- **No global token budget** — a busy DM can silently overflow the model window.
- The **camera scene is unconditional** — prepended every turn regardless of
  relevance. BF-632 (the scene hijacking the recall query) and #973 (agents
  over-narrating the scene) are both symptoms of this.
- Recall depth is **static per-agent**, not adaptive to the question.
- System-1 (one-shot DM) and System-2 (full lifecycle) **share no attention layer.**

## 2. Design principles

1. **Pull, not push.** A controller *selects* context; sources *bid* for it.
2. **The budget is the forcing function.** Enforce a global token budget; arbitrate scarcity explicitly. (This alone is the single highest-value fix.)
3. **Per-agent locality.** Attention is intrinsically local and sovereign (AD-397). The mesh *biases* attention; it never centralizes the decision.
4. **Deterministic and fast on the hot path.** No LLM call, no mesh round-trip to decide what goes in the prompt. Arbitration is arithmetic.
5. **Behavior-preserving first.** The seam ships byte-identical (fixed priorities = today's order), then becomes adaptive behind default-OFF flags.
6. **Auditable.** Every turn's bid competition is introspectable — "why did the agent attend to X?" is answerable from a trace.
7. **Agent-native.** Modeled as a deterministic paired faculty with the `perceive → decide → act` shape and an identity — not a hidden helper, not a chatty mesh peer.

## 3. The decision: a per-agent deterministic Attention Faculty (paired cognitive organ)

### 3.1 Options considered

- **A — Mesh-level attention service.** *Rejected.* It is a **central scheduler** — the exact anti-pattern ProbOS's Design Principle #1 forbids ("no central scheduler"). It would need every agent's private working set to decide their focus, breaching **sovereignty/shard isolation (AD-397)**, and would be a throughput bottleneck and single point of failure.
- **B — In-process helper class.** Workable and fast, but it's "just a class": no identity, no audit trail, doesn't honor the agent-native principle, and tends to accrete hidden state.
- **C — A deterministic Attention Faculty modeled as a paired agent.** *Chosen.* In-process and synchronous (fast, intimate access), **no LLM**, with an **identity** and an **audit trail**; **subscribes to the mesh** for exogenous salience between turns. Honors "every component is an agent" without the overhead of making it a chatty mesh peer.

### 3.2 Why per-agent, not mesh-level

- **Attention is intrinsically local.** What *this* agent should focus on depends on *its* goal, *its* working memory, *its* conversation. There is no global "correct" focus.
- **A mesh service is a central scheduler** — rejected by Design Principle #1.
- **Sovereignty (AD-397).** An agent's working set is private to its shard; a central service would have to breach that isolation.
- **Coordination still happens — through the mesh, as bias not control.** Per-agent faculties *subscribe* to mesh signals (an @mention, "the Captain addressed the whole room," a bridge alert, peer gossip). Those arrive as a **top-down bias** on the *local* competition — biased competition with a mesh-sourced signal — without centralizing the decision. This is the right shape: the mesh shapes attention; the agent owns it.

### 3.3 Answering the Captain's question: "could the controller be a deterministic agent each cognitive agent is paired with?"

**Yes — and it should be — with one crucial nuance about *how* it's an agent.**

- **It aligns with the architecture.** Modeling it as a deterministic agent honors Design Principle #1. It implements the `perceive → decide → act` lifecycle shape (perceive = gather bids + pending exogenous signals; decide = score/select/order under budget; act = emit the assembled context and any arousal/zone change), carries an identity, is introspectable, and could *learn* its salience weights over time (start deterministic; earn adaptivity).
- **Deterministic is the correct cost profile.** It runs *every cognitive cycle, before the expensive LLM call.* Salience arbitration is arithmetic, not reasoning — a deterministic (Core-tier-style) agent, never an LLM call.
- **The neuroscience backs the pairing.** The brain has dedicated attention circuitry — the thalamic reticular nucleus and fronto-parietal control networks — *distinct from* the cortical processors, gating and biasing them. A deterministic attention organ paired **1:1** with each cognitive agent is the computational analogue: a separate, fast gating subsystem, not part of the "reasoning cortex."

**The nuance — a paired *faculty*, not a chatty mesh peer:**

- The **per-turn arbitration is a synchronous, in-process call** on the hot path. Do **not** route it through the intent bus per turn — a NATS round-trip inside prompt assembly is a latency tax on *every* reply.
- The faculty **is** reached by the mesh **asynchronously**: exogenous events (alerts, mentions, camera-change, gossip) arrive as **intents between turns** and update the faculty's pending-bid state. So the mesh influences attention via pub/sub; the decision stays **local and synchronous.**
- **Pairing & lifecycle:** spawned alongside its cognitive agent by the pool/spawner, owned by it, sharing the agent's identity namespace. It is a **new ProbOS pattern — a *paired faculty*** (1:1, intrinsic, deterministic, meta-cognitive) — distinct from today's *pooled/shared* agents. This is worth naming explicitly in the agent-classification framework.

> **Recommendation:** build it as `AttentionFaculty` — a deterministic, paired,
> meta-cognitive agent. In-process + synchronous for arbitration; a mesh
> subscriber for exogenous salience; identity + cognitive-journal audit trail.
> Per-agent, definitively **not** a mesh-level service.

## 4. The model: AttentionBid + Global-Workspace cycle

Every candidate piece of context becomes an **AttentionBid**:

```text
AttentionBid:
  source       # episodic | working_memory | visual_scene | group_activity |
               #   telemetry | oracle | session_history | sensorium:<key>
  render       # the content, or a lazy renderer (only realized if it wins)
  modality     # endogenous (goal-driven) | exogenous (stimulus-driven)
  salience     # relevance(goal) × recency × importance  + surprise/interrupt
  token_cost   # estimated size, for budget arbitration
  zone_floor   # min cognitive zone at which this bid is eligible (arousal gate)
  pin          # optional: always-include (e.g., safety, identity grounding)
```

The **AttentionFaculty** runs once per cognitive cycle (a GWT "ignition"):

1. **Collect** bids from all registered sources + pending exogenous signals.
2. **Score** by biased competition: the goal (the raw Captain message — the
   BF-632 lesson, now first-class) biases relevance; bottom-up *surprise* (a
   materially changed frame, an @mention, an alert) adds exogenous salience.
3. **Select & order** the winners that fit the **global token budget**,
   compressing or dropping losers (not blind truncation). Order for
   primacy/recency ("lost in the middle"): most-salient at the edges.
4. **Modulate by arousal/zone** (Yerkes-Dodson): RED narrows to the threat;
   GREEN admits broad ambient awareness (where the camera usually lives).
5. **Broadcast:** the selected, ordered set becomes the prompt; emit any
   zone/arousal change and an audit trace.

**The camera becomes a bid, not a constant** — it wins context space only when
salient (referenced by the Captain, materially changed per an active-inference
"did it change?" gate, or the task is visual). This single change fixes the
BF-632 class, closes #973, and stops agents over-narrating the scene.

## 5. Mapping onto existing ProbOS (reuse, don't reinvent)

- **Repurpose `attention.py`** — extend `AttentionManager` from scoring *tasks* to scoring *context bids*; the formula generalizes directly.
- **Extend the sensorium registry into the bid catalog** — `SensoriumEntry` already declares `layer`/`paths`/`priority`/`injection_zone`; add `salience_fn` + `token_cost`. Each entry becomes a bid source.
- **Evolve working-memory eviction** — proportional eviction → salience-driven selection; fold in the optional salience filter (AD-668) and memory metabolism (AD-670).
- **Fold perception modes in** — AMBIENT/ENGAGED become *outputs* of the faculty's arousal state, not bespoke logic.
- **Activate spreading activation (AD-604)** — the relevance signal it was built for.
- **Cognitive zones (AD-588)** — become the arousal lever the faculty reads and writes.

## 6. Phased rollout (ADs)

Each phase ships behind a default-OFF flag, with tests, independently revertible.

| AD | Title | Closes / builds on |
|---|---|---|
| **AD-1028** | **ContextAssembler seam + `AttentionBid` + global token budget.** Route `_build_user_message` through a bid-based assembler with **fixed priorities equal to today's order** → byte-identical output, plus the *first* global token-budget enforcement. Pure refactor, default-OFF. | foundation |
| **AD-1029** | **`AttentionFaculty` (paired deterministic agent).** The organ that drives the assembler: `perceive`(collect bids)→`decide`(score/select under budget)→`act`(emit context + zone). In-process/synchronous; mesh-subscriber for exogenous salience; audit trace to the cognitive journal (AD-431). | AD-1028 |
| **AD-1030** | **Salience scoring.** Generative-Agents-style `relevance × recency × importance` to select/order episodic + working-memory bids; activate AD-604 spreading activation as the relevance signal. | AD-979c/981a, AD-598, AD-604 |
| **AD-1031** | **Camera/visual scene as a salience-gated bid.** Active-inference "did it materially change?" gate; scene competes instead of always-prepending. | **closes #973**, fixes BF-632 class |
| **AD-1032** | **Exogenous interrupts & arousal.** Mentions/alerts/material scene-changes raise the cognitive zone and reconfigure the bid competition — the cognitive-layer counterpart of HXI Design Principle #9 (LCARS Red Alert). | AD-588, HXI #9 |
| **AD-1033** *(later)* | Query-adaptive recall depth + cross-source budget reallocation. | AD-620 |

## 7. Non-goals & risks

- **Don't over-engineer the scorer.** Start with a transparent *linear* salience function; earn complexity. No learned model in v1.
- **Don't put the mesh in the hot path.** Per-turn arbitration is synchronous and local; the bus is only for asynchronous exogenous signals.
- **Behavior-preserving AD-1028 or bust.** With the flag off, output must be byte-identical, or we'll spend weeks chasing prompt regressions.
- **The token budget is worth doing even alone.** Today nothing prevents context-window overflow; AD-1028's budget is the highest-value single change.
- **Paired-faculty is a new pattern.** Spawning/owning a 1:1 deterministic faculty per cognitive agent touches the pool/spawner and the agent-classification framework — call it out and keep it minimal.

## 8. Alignment

- **Nooplex.** GWT is the mesh made momentarily conscious at the agent level; the faculty is the agent's local *ignition*. The mesh biases that ignition through gossip — cooperation without a central scheduler.
- **HXI Design Principle #9 (LCARS alert-driven).** AD-1032 is its cognitive-layer mirror: attention reconfigures around what matters *right now*.
- **A unifying substrate.** This sits *under* #973 (camera cadence), #908 (affective-salience retrieval axis), #900/#902 (recall gaps), and #882 (Natural Conversation) — one architecture instead of patching each symptom.
