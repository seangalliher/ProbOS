# Attention & Context Governance — Research & Findings

**Status:** Reference. Companion to [attention-architecture.md](attention-architecture.md).
**Date:** 2026-06-18. **Tracking:** epic (Agent Attention & Context Governance), AD-1028+.

This document captures (1) how ProbOS manages agent attention and context-window
assembly **today**, and (2) a survey of **prior art** for managing attention
across cognitive science, neuroscience, AI, and adjacent disciplines. It is the
evidence base for the architecture proposed in the companion design doc.

---

## Part 1 — How ProbOS manages attention today

### Summary diagnosis

ProbOS has **all the parts of an attention system but no conductor.** Context is
assembled **push-style**: every signal source self-injects into a fixed-order
prepend chain, each with its own local budget. There is no central arbiter that,
given the current moment (goal + state), decides *what earns a place in the
limited context window* and *in what order*. BF-632 (the visual scene block
unconditionally prepended onto every 1:1 DM, even hijacking the recall query) was
a symptom of this missing arbiter, not a camera bug.

### Mechanism map

| Mechanism | File(s) | State | Notes |
|---|---|---|---|
| **Attention scoring** | `cognitive/attention.py` (`AttentionManager`) | **Dead code** | `score = urgency × relevance × deadline × dependency × bg_factor`. Sound formula, **never invoked** during request processing or context assembly. |
| **Prompt assembly** | `cognitive/cognitive_agent.py` `_build_user_message` | **Hardcoded** | ~14-step fixed order (DM) / ~12-step (Ward Room). No adaptive reordering, no query relevance. |
| **Global token budget** | — | **Missing** | Per-section caps exist; nothing enforces "don't exceed the model window," nothing reallocates space across sources. |
| **Working memory** | `cognitive/agent_working_memory.py` (AD-573/645) | **Semi-adaptive** | Fixed 8-tier render priority (pinned → engagements → actions → reasoning → conversations → observations → conclusions → cognitive state → events); proportional eviction at a 4000-token budget; optional salience filter (AD-668). |
| **Sensorium registry** | `cognitive/cognitive_agent.py` (AD-666/723) | **Dispatch-driven** | `SensoriumEntry{layer, paths, priority, output_key, injection_zone, wrapper}`; entries declare which prompt paths consume them; priority=10 extensions override priority=0 baseline by key. Registry itself is static. |
| **Cognitive zones** | AD-588 (`get_cognitive_zone`) | **State-driven** | green/yellow/red; set externally; injected into prompt when != green. An unused arousal lever. |
| **Perception / camera** | `perception/` (AD-733a/b/c) | **Semi-adaptive** | AMBIENT↔ENGAGED mode is event-driven; but the visual scene is **always** injected (router prepend), with no salience gating or change detection. |
| **Episodic recall depth** | `earned_agency.py` + `episodic.py` (AD-620) | **Static per-agent** | Tier (basic/enhanced/full/oracle) set at agent birth by rank; not adaptive per-query. Recall query now uses the raw Captain message (BF-632) with echo-filtering (BF-631) and hybrid dense+sparse (BF-630/AD-979c/981c). |
| **Concurrency priority** | AD-672 `_classify_concurrency_priority` | **Static** | captain/mention=10, dm=8, ward_room=5, proactive=2 — fixed tier map, gates dispatch slots only. |
| **Spreading activation** | `cognitive/spreading_activation.py` (AD-604) | **Wired, unused** | Multi-hop semantic linking; field exists on the agent but is not in the prompt path. |
| **Memory metabolism** | `cognitive/memory_metabolism.py` (AD-670) | **Optional** | Per-entry triage/aging/eviction lifecycle. |

### The five hardcoded / fixed-order seams (what an attention layer would govern)

1. **DM prompt assembly order** — `_build_user_message` ~14-step sequence; all sections render if data exists; no reordering by relevance.
2. **Ward Room prompt assembly order** — ~12-step sequence; no thread-relevance scoring.
3. **Working-memory rendering** — fixed 8-tier order; eviction is proportional, not salience-driven per entry.
4. **Episodic recall tier** — chosen at agent creation, not per-query ("this question needs deeper memory").
5. **Sensorium dispatch** — registry iterated in declaration order; no query-driven entry filtering.

### Highest-impact gaps

- **Attention module is dead code** — the scoring exists but nothing calls it.
- **No global token budget** — a busy DM (visual + project + recall + working memory + episodic + session history) can silently overflow the model window; nothing arbitrates.
- **Camera is unconditional** — the scene is prepended every turn regardless of relevance (BF-632 class; #973).
- **Recall depth is not query-adaptive.**
- **System-1 (one-shot DM) and System-2 (full lifecycle) share no attention layer.**

---

## Part 2 — Prior art survey

The disciplines converge on a strikingly consistent design: a **limited-capacity
workspace** plus a **controller** that runs a cycle to **select and order**
content by **salience** under a **budget**, with separate handling for
**goal-driven** vs **stimulus-driven** input, modulated by **arousal**.

### 2.1 Cognitive science & neuroscience

- **Global Workspace Theory** — Baars (1988); neuronal global workspace, Dehaene & Changeux. Specialized unconscious processors *compete* for access to a limited-capacity workspace; the winner is *broadcast* ("ignition") to the whole system. **The context window is the global workspace.** Adopt as the central metaphor.
- **Biased competition** — Desimone & Duncan (1995). Stimuli compete; top-down *goals* bias the competition. → the current goal/query should bias which signals win context space.
- **Endogenous vs exogenous attention** — Posner (1980). Voluntary/goal-driven vs reflexive/stimulus-driven. → a question is endogenous (drives retrieval); a camera change, alert, or @mention is exogenous (may interrupt). Different handling.
- **Attention networks** — Posner & Petersen (1990); Petersen & Posner (2012). Three systems: *alerting* (arousal), *orienting* (selection), *executive control* (conflict). → separable concerns: arousal=zone, selection=bid competition, conflict=budget arbitration.
- **Working memory** — Baddeley & Hitch (1974); episodic buffer, Baddeley (2000); capacity ~4 chunks, Cowan (2001); 7±2, Miller (1956). A central executive arbitrating small slave buffers. → the window is a capacity-limited working memory needing an executive.
- **Supervisory Attentional System / contention scheduling** — Norman & Shallice (1986). Routine selection is automatic; novelty/conflict engages deliberate supervisory control. → ProbOS System-1 (one-shot) vs System-2 (lifecycle); both need a shared attention layer.
- **Feature Integration Theory & saliency maps** — Treisman & Gelade (1980); Itti & Koch (2000). Bottom-up salience computed per-feature into a saliency map guiding attention. → bottom-up salience signal for non-goal stimuli.
- **Yerkes-Dodson law** (1908) & attentional narrowing — Easterbrook (1959). Arousal follows an inverted-U; high arousal narrows attentional breadth. → cognitive zones are arousal states; RED narrows attention to the threat.
- **Default Mode vs Task-Positive networks** — Raichle (2001). Self-referential/rest vs externally-directed task. → AMBIENT (idle/reflective) vs ENGAGED (task) perception modes.
- **Predictive processing / active inference** — Friston (2010); Feldman & Friston (2010). Attention = precision-weighting of prediction errors; *surprise* draws attention. → a camera frame that didn't change carries ~0 information and should lose the competition (the #973 lever). Salience ≈ surprise.
- **Inhibition of return; change blindness; attentional blink.** Attention has refractory/cost dynamics; recently-attended items are suppressed; unattended changes go unnoticed. → don't re-surface identical content every turn (cf. BF-631 echo filter); switching has a cost.

### 2.2 AI / ML / cognitive architectures

- **Transformer attention** — Vaswani et al. (2017). QKV: a query weights values via keys. **Within-model.** Useful framing (goal=query, signals=keys, content=values) but it operates inside the LLM; we govern the *text* that becomes the window. Don't conflate the two.
- **Generative Agents** — Park et al., Stanford (2023). Memory stream; retrieval score = **recency** (exponential decay) + **importance** (LLM-rated) + **relevance** (embedding similarity); periodic reflection synthesizes higher-level memories. A ready-made salience function. ProbOS is most aligned here (AD-979c hybrid, AD-981a FoK, AD-598 importance).
- **MemGPT / Letta** — Packer et al. (2023). OS-inspired **virtual context management**: the LLM pages content between a fixed main context and external storage via function calls ("self-editing memory"). → "agent-native OS" makes attention a memory-management/paging subsystem; the agent can participate in managing its own window.
- **ACT-R** — Anderson (1996+). Declarative memory **activation** = base-level (recency+frequency) + **spreading activation** from the current goal + partial matching + noise; a retrieval threshold gates. The canonical computational salience equation. ProbOS has spreading-activation (AD-604) wired-but-unused — this is its home.
- **Soar** — Laird, Newell, Rosenbloom (1987). Working memory + production system; impasses trigger subgoaling. → deliberate attention shifts on impasse.
- **LIDA** — Franklin et al. A *computational* GWT: "attention codelets" compete each cognitive cycle to bring content coalitions into the workspace, which is then broadcast. **The closest existing blueprint for a per-agent attention controller running a cognitive cycle.**
- **Subsumption architecture** — Brooks (1986). Layered behaviors; higher-priority layers suppress lower ones. → priority layering for interrupts; HXI Design Principle #9 (LCARS alert-driven) is subsumption for the human surface.
- **BDI** — Bratman (1987); Rao & Georgeff (1995). Intentions are commitments that filter what's considered. → current intention as a top-down attention bias.
- **Context engineering practice (2023–2025)** — RAG, context compression, recency-vs-relevance trade-offs, and "lost in the middle" (Liu et al. 2023: LLMs underweight mid-context content). → **ordering matters as much as selection**; place the most salient content at the edges (primacy/recency).

### 2.3 Related disciplines

- **Operating systems — interrupts & scheduling.** Priority interrupts, interrupt masking, preemptive scheduling, the run queue. ProbOS *is* an OS: attention = scheduling the scarce context window; exogenous events = interrupts with priorities and masking.
- **HCI — interruptibility & attention economics.** Horvitz et al.; Gloria Mark. Cost-of-interruption models; defer/batch low-value notifications. → not every exogenous signal deserves to interrupt; weigh interruption cost vs value.
- **Aviation / ATC — alerting hierarchies.** Graded alerts (advisory/caution/warning); never everything at once; escalate by severity. → graded exogenous interrupts mapped to zones; the LCARS pattern.
- **Journalism — inverted pyramid.** Most important first. → prompt ordering for primacy.

---

## Part 3 — Convergent implications for ProbOS

1. **A limited-capacity workspace + a cycle-based controller** that selects and orders content by salience under a budget (GWT + LIDA + biased competition).
2. **Salience = relevance(goal) × recency × importance + surprise/exogenous** (Generative Agents + ACT-R + active inference).
3. **Endogenous (goal) vs exogenous (interrupt)** handled distinctly (Posner + OS interrupts + subsumption).
4. **Arousal/zone modulates breadth** (Yerkes-Dodson): RED narrows; GREEN admits ambient awareness.
5. **Ordering matters as much as selection** ("lost in the middle"): most-salient at the edges.
6. **Per-agent locality** (sovereignty / AD-397) with **mesh-mediated exogenous salience** (gossip), never a central scheduler.
7. **The camera is a bid, not a constant** — it wins context space only when salient (referenced, materially changed, or task-relevant). Fixes the BF-632 class and #973.

These implications are realized in [attention-architecture.md](attention-architecture.md).
