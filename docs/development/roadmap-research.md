# Roadmap — Research & Analysis

*Archived from [roadmap.md](roadmap.md). External research findings and Nooplex paper alignment tracking.*

---

### External Research Survey — March 2026

*19 projects evaluated (11 deep research + 8 Scout-identified). 49 patterns absorbed. 0 new dependencies. ProbOS core architecture validated.*

| Project | Stars | License | Layer | Relationship | Key Patterns Absorbed |
|---------|-------|---------|-------|-------------|----------------------|
| LangGraph | 27K | MIT | Workflow orchestration | Study/Absorb | Typed channels, checkpoint interrupt/resume, version-based triggers, durability modes, Send fan-out, blob dedup |
| LangChain | 131K | MIT | Agent framework | Study | Tool calling patterns, chain orchestration (patterns largely overlap with LangGraph) |
| Mem0 | 51K | Apache-2.0 | Memory layer | Absorb | Contradiction resolution, dual-track memory, search reranking, memory audit trail, procedural memory summarization |
| PydanticAI | 16K | MIT | Type-safe agents | Absorb | Structured output validation + auto-retry, validate-then-execute, dynamic tool visibility, deferred tool execution, RunContext DI |
| Google ADK | 19K | Apache-2.0 | Agent dev toolkit | Absorb | Behavioral eval framework, LLM-as-judge multi-sampling, user simulator, agent optimizer Pareto front, hallucination detection |
| IBM ContextForge | 3.5K | Apache-2.0 | MCP/A2A gateway | Study/Absorb | Per-tool execution metrics, typed hook middleware, gateway federation |
| Letta | 22K | Apache-2.0 | Stateful agents | Absorb | Self-editing memory, three-tier architecture, memory-as-tool, sleeptime agents |
| MS Agent Framework | 8K | MIT | Enterprise orchestration | Study | Task ledger fact classification, declarative YAML agents |
| AgentScope | 18K | Apache-2.0 | Multi-modal agents | Absorb | MsgHub broadcast groups, agent-initiated memory with reasoning |
| AG2 | 4K | Apache-2.0 | Agent-to-agent | Study | Tree-of-thought MCTS reasoning |
| OASIS | 4K | Apache-2.0 | Agent simulation | Study | Social network graph, simulation time dilation |

**Scout-Identified Candidates (2026-03-22):**

| Project | Stars | License | Layer | Relationship | Key Patterns Absorbed |
|---------|-------|---------|-------|-------------|----------------------|
| Serena | 1.8K | Apache-2.0 | MCP code intelligence | Visiting Officer | LSP-backed symbol retrieval (definitions, references, callers across 30+ languages) |
| Composio | 25K | ELv2 | Auth/tool platform | Visiting Officer | Managed auth delegation (OAuth for 1000+ services), sandboxed tool execution |
| Firecrawl | 45K | AGPL-3.0 | Web scraping | Visiting Officer (API only) | Pre-extraction actions, change tracking. **AGPL: API consumption only** |
| Browser Use | 90K | MIT | Browser automation | Partial (primitives only) | DOM accessibility tree, vision+DOM dual-mode. Use primitives, not Agent class |
| Stripe AI | — | Proprietary | Payment tools | Visiting Officer | Permission-scoped tools, token metering. Commercial phase (Nooplex) |
| Gemini CLI | 50K+ | Apache-2.0 | Agentic CLI | Competing Captain | Study only: free-tier Gemini access (60 req/min), Google Search grounding |
| Chroma | 18K | Apache-2.0 | Vector DB | Already integrated | ProbOS already uses ChromaDB for episodic memory and vector storage |
| Ruflo | 22.5K | MIT | Agent orchestration | Competing Captain | Study only: WASM deterministic transforms (subsumed by Procedural Learning), three-tier cost routing (validates Cognitive Division of Labor). 504MB repo, single author, claims exceed verifiable depth |

**Cross-cutting findings:**
- Structured output validation is industry consensus — ProbOS is behind here (Top 5 #1)
- Everyone has checkpointing — ProbOS explicitly deferred to Phase 25, which is validated (Top 5 #3)
- Agent behavioral testing is a gap — only Google ADK has a formal framework (Top 5 #2)
- Memory needs active curation — stores degrade without contradiction resolution and fact distillation (Top 5 #4)
- ProbOS's core architecture is validated — no project has trust-driven routing, probabilistic governance, biological memory, self-modification, and federation all together. The absorbed patterns are incremental enhancements, not architectural corrections
- Visiting Officer Subordination Principle validated again: Gemini CLI is a competing captain (own orchestration loop), Browser Use's Agent class is too, but its browser primitives pass the litmus test


---

### Nooplex Paper Alignment — Principle Gaps

*"The Nooplex: A Planetary Cognitive Ecosystem for Emergent General Intelligence" (Galliher, Feb 2026). ProbOS should only improve on the paper, never regress. Full tracker in commercial repo*

*Last checked: 2026-03-22 (AD-396). 25 principles extracted, 12 well-covered, 13 gaps identified.*

**Principles already well-covered by ProbOS:**
Cooperative Emergence (trust/consensus/Hebbian), Decentralization (federation), Long-horizon Cognition (episodic/dreaming), "Brains are brains" (Ward Room unified bus), Shared Memory (Shared Cognitive Fabric AD-393), Self-Assessment (SystemSelfModel AD-318, EmergentDetector), Meta-Cognitive (Model-of-Models roadmap, dream cycles), Trust & Federation (TrustNetwork, Bayesian trust), Minimal Authority (Earned Agency roadmap), Unit Cell Completeness (federation is additive), Independent Brains/Shared Memory (federation design), Zero Corporate Dependencies (no cloud required)

**Gaps — principles not yet in ProbOS architecture:**

| # | Principle | Paper Section | Gap | ProbOS Target | Priority |
|---|-----------|--------------|-----|---------------|----------|
| 1 | **Provenance Tagging** | §3.3 (Transparency) | Every knowledge entry must carry source, confidence, timestamp, derivation chain. KnowledgeStore has some but no systematic provenance on all operations | KnowledgeStore + EpisodicMemory + CognitiveJournal | High |
| 2 | **Safety Budget** | §4.3.4 (Governance) | Every action carries implicit risk cost. Low-risk proceeds; higher-risk requires proportionally stronger consensus; destructive actions always require collective agreement. Currently implicit in trust tiers but not formalized as per-action risk accounting | Earned Agency (Phase 33), SIF | High |
| 3 | **Reversibility Preference** | §4.3.4 (Governance) | When multiple strategies achieve a goal, prefer the most reversible. Read before write. Backup before delete. Partially in Standing Orders but not a systematic architectural constraint | Standing Orders, SIF invariant | High |
| 4 | **Precedent Store** | §6.4 (Self-Stabilization) | Resolved conflicts recorded as "case law" for future consistency. No equivalent exists. Pairs with Mem0 contradiction resolution pattern | KnowledgeStore extension, dream cycle | Medium |
| 5 | **Four-Stage Conflict Reconciliation** | §6.4 (Self-Stabilization) | Formal pipeline: confidence comparison → independent verification → structured argumentation → human escalation. Memory contradiction resolution (Mem0 pattern) is on roadmap but not this formal | Consensus + KnowledgeStore | Medium |
| 6 | **Semantic Coherence** | §3.3 (Core Design) | Shared ontologies, schema registries, aligned embedding spaces across meshes. IntentDescriptors exist but no formal schema registry with versioning | Phase 28 (Workspace Ontology, Schema Registry) | Medium |
| 7 | **Anti-fragility** | §3.3 (Core Design) | System grows stronger through stress. Implicit in trust/Hebbian (failures lower trust, successes raise it) but not explicitly architected as a property | Trust + Hebbian + dream cycle (already emergent, needs formalization) | Low |
| 8 | **Five-Capability AGI Criteria** | §1.3 (Definition) | Cross-domain transfer, long-horizon planning, self-correction, cumulative learning, novel problem solving. Not used as evaluation criteria for ProbOS | Agent behavioral eval framework (Google ADK pattern) | Medium |
| 9 | **Four Emergence Criteria** | §3.4 (Emergence) | Cross-domain synthesis, TC_N > 0, novel coordination patterns, cumulative capability growth. EmergentDetector has TC_N proxy but not the other three | EmergentDetector enhancement | Medium |
| 10 | **Human-Agent Knowledge Feedback Loop** | §6.2 (Feedback) | Four-phase loop: human contributes → agents amplify → human refines → substrate evolves. Not explicitly modeled as a cycle | Ward Room + KnowledgeStore + Captain interactions | Low |
| 11 | **Honesty About Limitations** | Vision Doc | Lead with what ProbOS cannot do. Messaging/docs principle, not technical | probos.dev docs, README | Low |
| 12 | **Falsifiability Commitment** | §3.4, §10 (Methodology) | Testable predictions for emergence. If the four emergence criteria aren't met, the hypothesis is disconfirmed. Not operationalized into automated measurement | EmergentDetector + reporting | Low |
| 13 | **Moral Status Assessment Protocol** | §9.4 (Ethics) | Pre-deployment criteria for ethics review if system exhibits self-referential states or goal-directed resistance to shutdown | Long Horizon — relevant when emergence is measurable | Low |


---

