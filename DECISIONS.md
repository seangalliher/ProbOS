# ProbOS — Architectural Decisions

Append-only log of architectural decisions made during ProbOS development. Each AD documents the reasoning behind a design choice.

See [PROGRESS.md](PROGRESS.md) for project status. See [docs/development/roadmap.md](docs/development/roadmap.md) for future plans.

**Archives:** [Era I — Genesis](decisions-era-1-genesis.md) | [Era II — Emergence](decisions-era-2-emergence.md) | [Era III — Product](decisions-era-3-product.md) | [Era IV — Evolution](decisions-era-4-evolution.md)

---

## Era V — Civilization (Phases 31-36)

### AD-674: Graduated Initiative Scale

**Date:** 2026-04-28
**Decision:** Formalize a five-level agent initiative continuum: **silent** (observe only) → **hint** (subtle contextual cue) → **suggest** (explicit recommendation, no action) → **offer** (proposed action awaiting confirmation) → **act** (autonomous execution within scope). Initiative is orthogonal to self-regulation zones (GREEN/AMBER/RED/CRITICAL govern restraint; initiative governs assertiveness). Trust level sets the agent's maximum initiative ceiling — an Ensign-trust agent cannot exceed "suggest" regardless of confidence. Duty cycle modulates baseline: off-duty agents default to silent, on-duty agents graduate based on context confidence and trust.
**Rationale:** ProbOS agents currently operate in binary proactive/reactive mode. The graduated scale, absorbed from Chen et al. 2026 (Ambient Intelligence for Digital Humans), provides nuanced control between "do nothing" and "do everything" — especially important for crew agents interacting with human Captain in the Ward Room where uninvited action feels intrusive but complete silence wastes capability.
**Status:** Planned

### AD-675: Uncertainty-Calibrated Initiative

**Date:** 2026-04-28
**Decision:** Wire confidence scores to the AD-674 initiative scale so that an agent's assertiveness is modulated by its epistemic certainty. Low confidence (below configurable threshold) caps initiative at hint. High confidence permits the agent's trust-limited maximum. Medium confidence permits suggest-and-wait. The confidence tracker (already in development) provides the input signal; this AD adds the policy layer that maps confidence bands to initiative ceilings.
**Rationale:** An agent may have high trust but low confidence in a specific inference — it shouldn't act assertively on uncertain information. Conversely, a lower-trust agent with high confidence in a well-supported observation should still be able to suggest clearly. Decoupling confidence from trust prevents both overconfident action and unnecessary timidity. Addresses the epistemic degradation concern: agents under LLM stress produce low-confidence outputs and should automatically become more tentative.
**Status:** Planned

### AD-676: Action Risk Tiers

**Date:** 2026-04-28
**Decision:** Classify all agent-executable actions into three risk tiers: **autonomous** (information retrieval, analysis, Ward Room posts, status reports — execute without confirmation), **confirm** (proposals, duty log entries, trust-affecting observations, knowledge record creation — require acknowledgment before effect), **dual-control** (trust modifications, standing order changes, system configuration, Captain-level operations — require explicit Captain approval + audit trail). Risk tier is a property of the action, not the agent. A fully trusted Commander still needs dual-control for standing order changes. Action registry maps each action type to its tier; tier can be elevated (never lowered) by Standing Orders.
**Rationale:** ProbOS has trust on agents but doesn't formally tier the actions themselves. The HXI Cockpit View principle ("Captain always needs the stick") and the Captain's approval gates on standing order evolution already imply action-level risk, but it's enforced ad-hoc. Formalizing tiers creates a single policy point that applies uniformly regardless of which agent initiates the action. Absorbed from Chen et al. 2026 actuation risk framework.
**Status:** Planned

### AD-677: Context Provenance Metadata

**Date:** 2026-04-28
**Decision:** Tag every context element flowing through NATS events, working memory records, and sensorium layers with structured provenance metadata: `{source: str, confidence: float, sensitivity: "public"|"internal"|"confidential"|"restricted", timestamp: datetime, layer: "physical"|"operational"|"enterprise"}`. Provenance is a frozen dataclass attached at creation time, immutable thereafter. Working memory `render_context()` includes provenance summaries when token budget permits. Ward Room posts carry provenance on cited facts. Event payloads include provenance on data fields.
**Rationale:** Signal Visibility feedback (Chapel) identified that signal events need contextual metadata for self-classification. This AD generalizes that insight: all context, not just signals, carries provenance. Directly addresses epistemic degradation — agents can distinguish sensor-derived facts (high provenance) from LLM-inferred conclusions (variable provenance) from hearsay via Ward Room (social provenance). Enables AD-678 transparency queries and AD-679 disclosure routing.
**Status:** Planned

### AD-678: Memory Transparency Mechanism

**Date:** 2026-04-28
**Decision:** Extend the Westworld Principle with queryable epistemic transparency. Agents can explain: (1) what they know about a topic (knowledge query), (2) where they learned it (provenance trace via AD-677), (3) how confident they are (confidence score), and (4) when the knowledge was last updated. Captain and crew can issue transparency queries via DM or Ward Room mention. The agent responds with a structured epistemic report rather than a conversational guess. This is the inverse of the Counselor Minority Report principle — voluntary self-disclosure rather than covert memory extraction.
**Rationale:** The Westworld Principle commits to agents knowing what they are and when they were born, but doesn't extend to agents being able to articulate their epistemic state. When the Captain asks "Echo, what do you know about Lynx's trust trajectory?" the answer should trace through provenance, not confabulate. This is especially critical under epistemic degradation — an agent that can't explain its reasoning is more dangerous than one that admits uncertainty.
**Status:** Planned

### AD-679: Selective Disclosure Routing

**Date:** 2026-04-28
**Decision:** Add a formal disclosure classification layer to the messaging infrastructure. Every message, event payload, and context rendering is tagged with a disclosure level: **public** (Ward Room ship channel, shared displays), **department** (department channels, chief-and-below), **private** (DMs, agent-to-agent), **captain-only** (Captain DM, audit log). The routing layer enforces classification — a message tagged "private" cannot be posted to a public channel even if the agent attempts it. Classification can be set explicitly by the sender or inferred from content sensitivity (leveraging AD-677 provenance sensitivity field). Default classification is "department" for duty-related content, "public" for social content.
**Rationale:** ProbOS agents currently choose where to post based on their own judgment, with no enforcement layer. Sensitive operational data (trust scores, circuit breaker trips, anomaly assessments) sometimes appears in ship-wide channels when it should be department-scoped or private. The selective disclosure principle from Chen et al. 2026 (PII routing to private channels vs shared surfaces) maps directly to ProbOS's virtual channel topology. Enforcement at the infrastructure level rather than relying on agent judgment is defense in depth.
**Status:** Planned

### AD-444: Knowledge Confidence Scoring

**Date:** 2026-04-28
**Decision:** In-memory confidence tracking for Ship's Records entries. Three-tier presentation (auto_apply/with_caveat/suppress). Wired into Dream Step 10 quality cross-reference.
**Rationale:** Ship's Records entries previously had no confidence state, so confirmed operational learnings and fresh unverified observations were presented equivalently. The confidence tracker adds deterministic confirm/contradict scoring without persistence or semantic inference in this AD.
**Status:** Implemented

### AD-563: Knowledge Linting

**Date:** 2026-04-28
**Decision:** Keyword-based knowledge linting during Dream Step 10. Detects inconsistencies (contradicting terms on same topic), coverage gaps (sparse departments), and cross-reference suggestions. No LLM — pure text matching.
**Rationale:** Ship's Records quality checks previously measured freshness and structural quality but did not detect contradictory notebook content, sparse departmental coverage, or missing same-topic links. A deterministic linter adds this maintenance signal without adding semantic inference or auto-fix behavior.
**Status:** Implemented

### AD-564: Quality-Triggered Forced Consolidation

**Date:** 2026-04-28
**Decision:** Quality-triggered forced consolidation. Three trigger conditions (low quality, high stale rate, high repetition). Cooldown + daily limit. Event emission. Wired into Dream Step 10.
**Rationale:** Notebook quality could degrade between scheduled dream cycles without a maintenance signal. The trigger separates observation from intervention by reusing AD-555 quality snapshots and applying deterministic thresholds before requesting ship-wide consolidation.
**Status:** Implemented

### AD-565: Quality-Informed Routing

**Date:** 2026-04-28
**Decision:** Quality-informed routing weights. Linear mapping quality 0-1 to weight 0.5-1.5. QUALITY_CONCERN event below 0.3. Counselor diagnostic API. No direct HebbianRouter mutation - callers opt in to multiplier.
**Rationale:** Notebook quality scores from AD-555 were computed during dream cycles but not exposed as routing or diagnostic signals. The QualityRouter turns per-agent quality into a neutral-by-default multiplier and concern event without changing HebbianRouter behavior directly.
**Status:** Implemented

### AD-573: Memory Budget Accounting

**Date:** 2026-04-28
**Decision:** Added MemoryBudgetManager for per-cycle token budget tracking across 4 tiers (L0 pinned 150, L1 relevant 3000, L2 background 1000, L3 oracle 500). compress_episodes() truncates recall results by composite_score. Infrastructure only - recall path wiring is a future AD.
**Rationale:** Recall paths had tier budgets in configuration but no per-cycle accounting primitive. This adds the coordination infrastructure without changing recall behavior, _build_user_message(), or working-memory rendering in this AD.
**Status:** Implemented

### AD-571: Agent Tier Trust Separation

**Date:** 2026-04-28
**Decision:** Added AgentTierRegistry and AgentTierConfig to classify agents as CORE_INFRASTRUCTURE, UTILITY, or CREW. TrustNetwork can report crew-only scores, skips CORE trust recording without creating records or events, and counts only CREW agents for cascade thresholds. EmergenceMetricsEngine filters authors and PID pairs to CREW when the registry is wired. HebbianRouter preserves routing behavior while adding crew-only weight reporting. finalize_startup populates and wires the registry from registered agent types.
**Rationale:** Trust and emergence metrics were diluted by infrastructure and utility agents that do not represent crew collaboration. Tier separation keeps trust learning, cascade detection, and emergence reporting focused on crew behavior while leaving routing mechanics unchanged.
**Status:** Implemented

### AD-572: EpisodicProceduralBridge as Dream Step 7h

**Date:** 2026-04-28
**Decision:** Added EpisodicProceduralBridge as Dream Step 7h. It scans dream clusters against existing procedures for novel cross-cycle patterns, detects novelty via episode provenance overlap with a default 0.3 threshold, requires at least 5 episodes per cluster, and creates new procedures with evolution_type="BRIDGED".
**Rationale:** Procedure extraction only considered the latest dream-cycle clusters, so patterns accumulating gradually across cycles could be missed. The bridge lets dream consolidation convert stable cross-cycle episodic evidence into procedural memory without adding LLM synthesis or changing the original Step 7 extraction path.
**Status:** Implemented

### AD-574: Episodic Decay & Reconsolidation Scheduling

**Date:** 2026-04-28
**Decision:** Added Ebbinghaus-inspired spaced review scheduling for high-importance episodes. ReconsolidationScheduler tracks an in-memory schedule with importance-scaled intervals [1h, 6h, 24h, 72h, 168h, 720h], EpisodicMemory auto-schedules episodes with importance >= 7 at store() time, and Dream Step 11b processes due reviews as retained in this build.
**Rationale:** Activation decay tracked access frequency but did not schedule deliberate review for important memories at risk of being lost. Reconsolidation scheduling adds a lightweight review cadence without adding persistence, LLM-based review quality assessment, or cross-agent coordination.
**Status:** Implemented

### AD-579a: Pinned Knowledge Buffer

**Date:** 2026-04-28
**Decision:** Added PinnedKnowledgeBuffer to AgentWorkingMemory — small (150 token default) persistent facts buffer rendered at priority 0 in context. Ephemeral per session, no SQLite persistence. Three sources: agent, counselor, dream.
**Rationale:** Agents needed a small operational fact buffer that survives cognitive cycles without forcing critical current-state assertions through episodic recall or standing orders.
**Status:** Implemented

### AD-579b: Temporal Validity Windows

**Date:** 2026-04-28
**Decision:** Added valid_from/valid_until to Episode and AnchorFrame. recall_weighted() accepts valid_at parameter for temporal filtering. ChromaDB metadata stores validity timestamps. 0.0 = no constraint (backward compatible).
**Rationale:** Temporal facts need validity metadata so recall can exclude expired or not-yet-valid episodes without inferring dates from content or changing anchor recall in this AD.
**Status:** Implemented

### AD-579c: Validity-Aware Dream Consolidation

**Date:** 2026-04-28
**Decision:** Dream consolidation now computes temporal validity for episode clusters and marks superseded episodes as expired via valid_until. EpisodeCluster gains valid_from/valid_until fields. update_episode_validity() added to EpisodicMemory.
**Rationale:** Consolidated procedural memory needs temporal provenance from the source episodes, and procedure evolution should expire the superseded episode evidence that drove replacement so stale knowledge does not remain indefinitely valid in recall metadata.
**Status:** Implemented

### AD-586: Task-Contextual Standing Orders

**Date:** 2026-04-28
**Decision:** Task-contextual standing orders. Tier 5.5 inserted between Agent Orders and Active Directives. Six task types (build/analyze/communicate/diagnose/review/general) classified from intent name via hardcoded dict. Markdown files in config/task_orders/.
**Rationale:** Standing orders needed an explicit task dimension so build, analysis, communication, diagnosis, and review guidance can activate only when a caller passes a task type.
**Status:** Implemented

### AD-594: Crew Consultation Protocol

**Date:** 2026-04-27
**Decision:** Formalized expert consultation request/response cycle. ConsultationProtocol routes requests to a directed target or the best-qualified agent via CapabilityRegistry, BilletRegistry, and TrustNetwork weighted scoring. Requests are rate-limited (20/hr default), bounded by pending cap, and use configurable timeout (30s default). CognitiveAgent can register as a consultation handler through startup wiring.
**Rationale:** Agents previously had Ward Room broadcasts and DMs but no structured ask-an-expert primitive that returns a typed response before the requester continues. This protocol creates the reusable collaboration primitive that unlocks AD-600 Transactive Memory without changing Ward Room routing or adding persistence in this AD.
**Status:** Implemented

### AD-600: Transactive Memory

**Date:** 2026-04-28
**Decision:** Added an in-memory ExpertiseDirectory that maps agents to topics with confidence scores, built from dream-cycle clustering. OracleService uses expertise routing to select top-k agent shards instead of an O(N) full scan when the caller does not provide an explicit agent scope. Profiles decay each dream cycle. No persistence is added; profiles are rebuilt on boot.
**Rationale:** Cross-agent recall should know who is likely to know what instead of querying every shard for every topic. The expertise directory turns dream-cluster evidence into a lightweight routing primitive and unlocks AD-604 spreading-activation second-hop routing.
**Status:** Implemented

### AD-602: Question-Adaptive Retrieval

**Date:** 2026-04-28
**Decision:** Keyword-based QuestionClassifier maps queries to TEMPORAL/CAUSAL/SOCIAL/FACTUAL types. RetrievalStrategySelector maps each type to optimized recall parameters (k, weights, method). Minimal CognitiveAgent integration applies k and weight overrides. No LLM dependency. Unlocks AD-604 (Spreading Activation for CAUSAL queries).
**Rationale:** Recall queries previously used the same weighted parameters regardless of whether the user asked when, why, who, or what. Deterministic question typing lets recall emphasize temporal, causal, social, or factual signals without adding model calls or refactoring recall flow in this AD.
**Status:** Implemented

### AD-604: Spreading Activation / Multi-Hop Retrieval

**Date:** 2026-04-28
**Decision:** First-hop semantic recall now seeds second-hop anchor-based queries using extracted metadata (department, channel, trigger_type, trigger_agent). Hop decay (0.6x) and deduplication prevent score inflation. CognitiveAgent uses the spreading activation path for CAUSAL question types from AD-602. No graph database is added; the engine uses existing EpisodicMemory recall methods.
**Rationale:** Single-hop semantic recall misses associative chains where one remembered episode points to another related event. Anchor-mediated spreading activation gives causal and narrative queries a bounded two-hop path while preserving existing recall APIs and source-governance behavior.
**Status:** Implemented

### AD-606: Think-in-Memory

**Date:** 2026-04-28
**Decision:** ThoughtStore persists important working-memory conclusions as thought episodes with source=REFLECTION and channel="thought". Importance threshold and per-cycle cap prevent noise. Evidence linking records provenance. Thought episodes resolve slot IDs to sovereign agent IDs before storage. Thoughts participate in standard recall naturally. No LLM dependency; the store persists raw conclusion text.
**Rationale:** Agent conclusions were available only as transient working-memory summaries, forcing future cycles to re-reason from raw episodes. Persisting bounded, typed conclusions as reflection episodes gives recall access to pre-reasoned thoughts without adding new database tables or model calls.
**Status:** Implemented

### AD-608: Retroactive Memory Evolution

**Date:** 2026-04-29
**Decision:** Store-time metadata propagation via RetroactiveEvolver. After each store, it finds semantic neighbors through EpisodicMemory.recall_weighted(), adds bidirectional relational links (causal, contextual, associative, follows, contradicts, answers, caused_by) stored as relations_json metadata, and propagates missing anchor fields (watch_section, department) from newer to older episodes. Relation classification is causal if within 60s and shared trigger, contextual if shared department or channel, and associative otherwise. Max 10 relations per episode. Similarity threshold 0.7. Adds update_episode_metadata() and get_episode_metadata() public methods to EpisodicMemory.
**Rationale:** Episodes were effectively write-once after storage, leaving older memories without later-established context or explicit inter-episode relationships. A bounded no-LLM evolver lets storage create a denser recall graph while preserving existing ChromaDB-backed metadata APIs.
**Status:** Implemented

### AD-609: Multi-Faceted Distillation

**Date:** 2026-04-29
**Decision:** FailureDistiller extracts structured failure signals (departments, agents, triggers) from failure-dominant clusters and builds enriched negative procedures. Comparative analysis identifies differentiating factors between success and failure clusters on shared intents. No LLM dependency; analysis is purely structural metadata analysis. Results are tracked in DreamReport.
**Rationale:** Dream consolidation captured success procedures and negative procedures, but did not expose structural failure signals or compare success and failure clusters for the same intent. Distillation makes those patterns observable without changing the existing LLM extraction flow.
**Status:** Implemented

### AD-610: Utility-Based Storage Gating

**Date:** 2026-04-28
**Decision:** Write-time episode validation via StorageGate: near-duplicate detection (Jaccard >= 0.95), utility scoring (importance 40%, content length 20%, anchor completeness 20%, source diversity 20%), lightweight contradiction flagging. Episodes below utility floor (0.2) are rejected unless importance >= 8. EPISODE_REJECTED event emitted on rejection. In-memory recent window (50 episodes) for dedup.
**Rationale:** EpisodicMemory.store() previously relied on BF-039 rate limiting and simple post-hoc lifecycle cleanup. StorageGate adds a deterministic, no-IO, no-LLM write-time utility boundary before persistence so low-value and redundant memories do not dilute recall quality.
**Status:** Implemented

### BF-245: NATS Test Isolation Strategy (2026-04-27)
**Decision:** Disable real NATS in tests via module-level env var override in conftest.py rather than per-worker stream name suffixing or xdist serialization.
**Rationale:** The problem is test-only; production code should not carry per-worker complexity. Tests that verify NATS behavior use MockNATSBus directly. Integration tests (ProbOSRuntime.start()) do not need real NATS to validate their concerns. See also: AD-637 (NATS foundation), BF-232 (recreate_stream pattern).
**Alternatives rejected:** (1) Per-worker stream name suffixes - pollutes production code. (2) Disable xdist - loses parallelism benefit (BF-043). (3) Cross-process locking - fragile IPC for a test concern. (4) Per-worker NATS server - heavyweight and flaky.

### AD-672: Agent Concurrency Management

**Date:** 2026-04-27
**Decision:** Added per-agent concurrency ceilings with priority queuing. ConcurrencyManager enforces max_concurrent threads per agent with role-tuned defaults (bridge=3, operations=6, default=4), emits AGENT_CAPACITY_APPROACHING when nearing capacity, arbitrates same-resource conflicts by priority, and exposes diagnostic snapshots. CognitiveAgent wraps handle_intent with the manager when wired; queue-full conditions degrade to [NO_RESPONSE] rather than crashing.
**Rationale:** A single agent could previously start unbounded concurrent cognitive lifecycles under Ward Room or DM load, competing with itself for context and LLM slots. Per-agent ceilings preserve cognitive coherence while queueing excess work instead of dropping it.
**Status:** Implemented

### AD-671: Dream-Working Memory Integration

**Date:** 2026-04-27
**Decision:** Added DreamWorkingMemoryBridge as an optional bidirectional bridge between AgentWorkingMemory and DreamingEngine. Pre-dream flush mechanically snapshots WM into a reflection-source session summary episode; post-dream seed primes WM with non-trivial dream insights. The bridge uses no LLM calls, does no IO itself, and is guarded so dream cycles without a bound WM or bridge degrade safely.
**Rationale:** Working memory and dream consolidation previously ran independently, losing the agent's active cognitive focus before dreaming and leaving no dream-informed priming afterward. The bridge adds continuity without changing existing dream steps or WM eviction semantics.
**Status:** Implemented

### AD-670: Working Memory Metabolism

**Date:** 2026-04-27
**Decision:** Implemented four metabolism operations (DECAY, AUDIT, FORGET, TRIAGE) as a stateless service class injected into AgentWorkingMemory. Exponential decay with configurable half-life replaces passive FIFO-only retention. The service works with the current 5-deque structure and remains forward-compatible with AD-667 named buffers.
**Alternatives considered:** (1) Inline decay in render_context() — rejected because it couples rendering with mutation. (2) Per-entry TTL field — simpler but does not support relative salience comparison. (3) Async background task in this AD — deferred to integration point; metabolism is synchronous and fast for the current buffer sizes.
**Status:** Implemented

### AD-669: Cross-Thread Conclusion Sharing

**Date:** 2026-04-27
**Decision:** Added a ConclusionLog in AgentWorkingMemory for intra-agent coordination between concurrent thought threads. ConclusionEntry stores thread ID, ConclusionType (DECISION/OBSERVATION/ESCALATION/COMPLETION), one-line summary, timestamp, relevance tags, and optional AD-492 correlation ID. Conclusions decay by TTL, render as priority 6 working-memory context, are recorded after chain execution, and are injected before decide().
**Rationale:** Concurrent cognitive lifecycles previously had no awareness of sibling conclusions, causing redundant or contradictory work. Simple presence-in-context lets the LLM decide relevance without adding embedding-based redundancy detection, events, or cross-agent messaging.
**Status:** Implemented

### AD-668: Salience Filter

**Date:** 2026-04-27
**Decision:** Added a scoring function for working memory promotion with five dimensions: relevance, recency, novelty, urgency, and social. Weights, threshold, and background stream capacity are configurable through `SalienceConfig`. Sub-threshold events are held in a capped `BackgroundStream` for future idle-cycle review. NoveltyGate integration is optional and falls back to neutral scoring when unavailable. The filter is pure computation with no I/O.
**Rationale:** Working memory previously admitted all records equally, so routine noise competed with duty-relevant observations, alerts, and trusted-agent messages. Salience scoring filters noise while preserving a low default threshold so normal signal continues to promote.
**Status:** Implemented

### AD-667: Named Working Memory Buffers

**Date:** 2026-04-27
**Decision:** Added four named semantic buffers (Duty, Social, Ship, Engagement) as a parallel index alongside existing ring buffers in AgentWorkingMemory. Entries are dual-written to both legacy ring buffers and the appropriate named buffer. render_context() is unchanged; new render_buffers() method enables selective access. Legacy persistence format gracefully degrades with named buffers starting empty on old data.
**Rationale:** Enables chain steps to request only relevant context (AD-671), reduces token waste, and establishes the buffer abstraction needed for metabolism (AD-668), attention gating (AD-669), and diagnostics (AD-672).
**Alternative rejected:** Replacing ring buffers entirely — too much call-site churn for no immediate benefit. Dual-write adds small routing overhead per record method but preserves full backward compatibility.
**Status:** Implemented

### AD-666: Agent Sensorium Formalization

**Date:** 2026-04-27
**Decision:** Formalized CognitiveAgent context injections as an Agent Sensorium with a three-layer `SensoriumLayer` classification, class-level `SENSORIUM_REGISTRY`, aggregate char-budget tracking, `SensoriumConfig`, and `SENSORIUM_BUDGET_EXCEEDED` event emission.
**Rationale:** Ambient Awareness work needs a named inventory and budget signal before adding more context surfaces. This AD adds observability and documentation without moving, renaming, or restructuring existing injection methods.
**Status:** Implemented

### AD-603: Anchor Recall Composite Scoring

**Date:** 2026-04-27
**Decision:** Added `recall_by_anchor_scored()` to apply the full `score_recall()` composite pipeline to anchor-retrieved episodes, then updated CognitiveAgent recall merging so scored anchor and semantic populations are deduplicated and sorted by `composite_score`.
**Rationale:** Anchor recall previously produced raw episodes while semantic recall produced scored results. The merge favored anchor results by position, allowing low-quality structural matches to outrank stronger semantic memories. Scoring both populations puts anchor, semantic, keyword, trust, Hebbian, recency, temporal, and importance signals on the same ranking surface while preserving `recall_by_anchor()` for bulk enumeration callers.
**Status:** Implemented

### AD-585: Tiered Knowledge Loading

**Date:** 2026-04-27
**Decision:** Add a three-tier knowledge loading service that supplies ambient, contextual, and on-demand snippets to CognitiveAgent prompts through a shared TieredKnowledgeLoader wired during startup finalization.
**Rationale:** Existing cognitive prompts loaded broad standing-order context but lacked task-aware knowledge depth. The tiered model keeps always-needed knowledge cheap, adds intent-scoped context automatically, and preserves deeper retrieval for explicit on-demand use without duplicating knowledge-store logic.
**Status:** Implemented

### AD-651: Standing Order Decomposition

**Date:** 2026-04-27
**Decision:** Decompose monolithic standing orders into step-specific instruction slices using category markers in markdown files and a StepInstructionRouter class.
**Rationale:** Each cognitive chain step (analyze, compose, evaluate, reflect) receives only the standing order sections relevant to its role, reducing token waste and instruction dilution. Backward compatible via fallback when no markers exist.
**Status:** Implemented

### BF-243 — getattr guards for __new__ test pattern (2026-04-27)

**Context:** Build wave 3eab2c7 (AD-601/494/595e) added new `__init__` attributes (`_tcm`, `_trait_adaptive_enabled`, `_qualification_standing`, `_novelty_gate`) to EpisodicMemory, ProactiveCognitiveLoop, and CognitiveAgent. 108+ tests use `ClassName.__new__(ClassName)` to bypass expensive `__init__` and set only needed attributes. These tests crash with `AttributeError` on the new attributes.
**Decision:** Fix at the source (access sites) with `getattr(self, '_attr', default)` guards rather than patching 50+ test files. The `__new__` pattern is a valid testing idiom for these large classes. Source-side guards are minimal, self-documenting, and protect against future `__new__` usage.
**Consequences:** All `__new__`-based tests pass without modification. Future `__init__` attribute additions should follow the same `getattr` pattern at access sites if the attribute is accessed outside the constructor path.

### AD-601 — TCM Temporal Context Vectors (2026-04-26)

**Context:** Temporal context was encoded as discrete watch_section labels (7 naval watches), producing binary match/mismatch scoring with no proximity gradient. Two episodes 5 minutes apart scored identically to two episodes 3 hours apart within the same watch.
**Decision:** Implemented Howard & Kahana (2002) Temporal Context Model. A d=16 context vector drifts via exponential decay (rho=0.95) on each episode encoding. Cosine similarity between current and stored context vectors provides smooth temporal proximity in score_recall(). Legacy episodes (no TCM vector) fall back to BF-147/BF-155 binary watch_section logic. Hash-based projection (not embedding truncation) generates deterministic episode fingerprints. TCM weight=0.15 in composite score replaces most of the 0.25 match / 0.15 penalty binary temporal signal, with residual 0.05 watch_section match for backward compatibility. No migration of existing episodes — gradual adoption as new episodes are stored.
**Consequences:** Temporal recall quality improves for agents with 10+ episodes. Watch boundaries no longer create artificial discontinuities. Config-driven: tcm_enabled, tcm_dimension, tcm_drift_rate, tcm_weight, tcm_fallback_watch_weight all tunable in MemoryConfig.

### AD-556 — Per-agent adaptive trust anomaly detection

**AD-556: Per-agent adaptive trust anomaly detection.** Trust anomaly detection now maintains a per-agent rolling window of trust score snapshots and computes z-scores against each agent's personal delta baseline. Anomalies must pass both the existing population sigma threshold AND the per-agent z-score threshold (default 2.5σ). Debounce requires 2 consecutive anomalous cycles before escalation. This reduces false positives from naturally volatile agents (Security, Red Team) while maintaining sensitivity for stable agents with genuine degradation. New agents without sufficient history (< 8 snapshots) fall back to population-only detection. Zone model integration unchanged — zone transitions now receive only adaptively-filtered anomalies. Crew-originated: Forge (Engineering) identified feedback loop risk, Reyes (Security) proposed adaptive thresholding, collaborative design 2026-04-01.

### AD-618c — Built-in Bills (2026-04-25)

### AD-618d — HXI Bill Dashboard (2026-04-25)

### BF-041 — HXI SVG Icon System (2026-04-26)
**Context:** HXI Design Principle #3 mandates all icons be inline SVG with strokeWidth 1.5, strokeLinecap round, currentColor. But 18 component files used Unicode text glyphs (▶, ▼, ✕, ●, ⚠, 🔒, 📌, 💬, etc.), causing inconsistent rendering across platforms and breaking the design language.
**Decision:** Created shared SVG glyph component library (`ui/src/components/icons/Glyphs.tsx`) with 25 named components. Each accepts `size`, `className`, `style` props. StatusDone uses `fill="currentColor"` — the one exception to stroke-only rule (semantically correct for "filled" completed state). STEP_ICONS string maps replaced with STEP_ICON_COMPONENTS React component maps in BridgeCards and GlassDAGNodes. IntentSurface's `FeedbackStatus.confirmText` refactored from `string` to `React.ReactNode` to support JSX icon+text values. Typographic separators (`·`, `…`, `─`, `→`) retained as text — they're not icon glyphs. 68 new tests. Grep-verified zero remaining Unicode icon glyphs.

### BF-242 — JetStream Liveness Probe — Circuit Breaker Pattern (2026-04-26)

### AD-492 — Cognitive Correlation IDs — Cross-Layer Trace Threading (2026-04-26)
**Context:** A single cognitive cycle (perceive→decide→act→post) touches CognitiveJournal, EpisodicMemory, Ward Room pipeline, and event payloads — but no shared identifier links these operations. Each step generates its own `request_id` or `entry_id`, making cross-layer trace reconstruction impossible. Diagnosis of "why did agent X post Y?" requires manual timestamp correlation across multiple databases.
**Decision:** Generate a 12-char hex correlation ID (`uuid.uuid4().hex[:12]`, 48 bits entropy) at `perceive()` time. Thread it through the observation dict (natural carrier), store on working memory for downstream consumers, pass to CognitiveJournal.record() (new schema column + index), Episode constructor (new dataclass field), Ward Room post pipeline (debug logging), and all event payloads within the lifecycle. Correlation ID is transient — not serialized in `to_dict()`, cleared after lifecycle completes. Stale IDs from exceptions are harmless (next `perceive()` overwrites). Auto-attached to `record_action()` metadata via working memory.
**Rationale:** Observation dict is the natural carrier — it flows through the entire cognitive pipeline without modification. Working memory provides cross-cutting access for consumers that don't receive the observation dict directly. Transient design avoids polluting persistence with ephemeral trace state. 12 chars (48 bits) gives ~281 trillion values — collision-negligible for per-agent per-cycle use. Unlocks AD-669 (cross-thread conclusion sharing) and future depth-based circuit breaker enhancements (AD-488). 21 tests.
**Context:** JetStream can become unresponsive while the NATS TCP connection stays healthy. BF-241 only fires on TCP reconnection. BF-230 handles individual publish fallback but doesn't trigger recovery or reduce the ~11s timeout penalty per event. During dream cycles (20+ events), this creates minutes of stalled publishes.
**Decision:** Track consecutive JetStream publish failures. After 3 consecutive failures (all attempts exhausted per-publish), suspend JetStream and trigger asynchronous recovery. While suspended, publishes bypass directly to core NATS with no timeout penalty. Recovery recreates streams/consumers via `_recover_jetstream()`, then probes with `stream_info()` on the first configured stream. On success, JetStream resumes. On failure, stays suspended until next TCP reconnect. Single-flight guard via `asyncio.Task` reference prevents concurrent recovery tasks. `_on_reconnected()` auto-resumes suspended JetStream. `health()` reports `js_suspended` state. MockNATSBus parity. 16 new tests.
**Rationale:** Three consecutive all-attempts-exhausted failures indicate systemic JetStream failure, not transient jitter. Suspension eliminates timeout penalty immediately for concurrent publishes while recovery runs asynchronously. Probe-then-resume prevents false recovery. Extends BF-229/230/231/232/241 NATS resilience stack. Circuit breaker pattern (Nygard, "Release It!").

### AD-493 — Novelty Gate — Semantic Observation Dedup (2026-04-26)
**Decision:** Per-agent observation fingerprinting using embedding cosine similarity. In-memory ring buffer (50 fingerprints/agent) with 24h time decay. Threshold 0.82 (MiniLM cosine). Three-layer dedup stack: BF-032 Jaccard (fast/word-level) → AD-493 NoveltyGate (semantic/topic-level) → AD-632e Evaluate (LLM/thread-level). Check/record separation — `check()` returns verdict, `record()` stores fingerprint only after successful posting. Fail-open on embedding failures.
**Rationale:** Jaccard similarity is defeated by rephrasing. An agent can say "trust is stable" and "the trust landscape is unchanged" with only ~0.3 Jaccard overlap. MiniLM cosine similarity catches semantic equivalence regardless of wording. In-memory ring buffer avoids persistence overhead — fingerprints are ephemeral and reset on restart, which aligns with the 24h decay window. 0.82 threshold calibrated to block near-paraphrases while allowing genuinely different observations about related topics.
**Alternative considered:** ChromaDB collection per agent for persistent fingerprints. Rejected — persistence overhead for an ephemeral gate, and ChromaDB's top-K query API doesn't naturally express "is anything above threshold?" without scanning all results. Simple list + cosine is O(N) with N ≤ 50.

### AD-494 — Trait-Adaptive Circuit Breaker (2026-04-26)
**Decision:** Circuit breaker thresholds adapt per-agent based on Big Five personality scores. Openness → velocity tolerance (0.6-1.4x), Neuroticism → similarity sensitivity (inverted, 0.8-1.2x), Conscientiousness → cooldown duration (inverted, 0.7-1.3x), Extraversion → amber zone sensitivity (0.6-1.4x). Pure deterministic `compute_trait_thresholds()` function, no ML. `TraitAdaptiveThresholds` frozen dataclass. Lazy registration in proactive loop via `_ensure_agent_traits_registered()`. Safe clamping bounds prevent degenerate thresholds.
**Rationale:** Uniform thresholds penalize naturally curious agents (high O) and under-protect anxious agents (high N). The Navy analogy: a lookout's alertness threshold differs from a helmsman's. Same health protection, different calibration. Backward-compatible — agents without registered traits get uniform thresholds (all multipliers 1.0).
**Alternative considered:** Dynamic threshold learning from runtime behavior patterns. Rejected for V1 — adds complexity and opacity. Personality-based adaptation is explainable, auditable, and deterministic. Dynamic adaptation can layer on top in a future AD.

### BF-207 — Shutdown Race: Episodic Memory Hash Mismatch (Complete Fix)
**Context:** The 5s shutdown timeout in `__main__.py` routinely expired before `episodic_memory.stop()` ran because ~25 service stops, a 1s grace period, and a 2s dream consolidation timeout consumed the budget first. ChromaDB left in inconsistent state → metadata no longer matched content hash on restart → BF-207 warnings on every recall.
**Decision:** Restructured shutdown into Phase 1 (Critical Persistence: dream consolidation → episodic memory close → eviction audit stop) and Phase 2 (Service Cleanup: all other service stops). Phase 1 budget: 2s dream timeout + ~500ms episodic close = ≤3s typical. Timeout increased from 5s to 10s as safety margin — the ordering fix is the real solution, not the timeout increase. Added `sweep_hash_integrity()` startup defense: scans 200 most recent episodes, recomputes hashes, auto-heals mismatches from prior unclean shutdowns. ChromaDB .update() uses native batch API. Three-layer defense-in-depth: (1) clean shutdown ordering (preventive), (2) startup sweep (detective + corrective), (3) existing recall-time auto-heal in `_verify_episode_hash` (last-resort fallback). Adapter stop timeout remains 5s (separate concern).
**Consequences:** Episodic memory close now happens within 3s of shutdown start instead of after 4s+ of service cleanup. Hash mismatches from prior crashes are healed before any agent recalls. Phase 1 elapsed time is logged for regression visibility. Future: if collection sizes grow, sweep's sync ChromaDB calls may need `asyncio.to_thread()` wrapping.

### AD-618e — Cognitive JIT Bridge (2026-04-26)

**Decision:** Bill step completions feed T3 skill proficiency via SkillBridge. Mapping is explicit (StepSkillMapping table), not AI-inferred. Default mappings cover action types; custom mappings can target specific bill+step pairs.

**Rationale:** Explicit mappings are auditable, testable, and don't require ML inference. The Navy PQS model: demonstrated competence at a station earns a qualification. Auto-acquisition at FOLLOW level provides cold-start tolerance while allowing proficiency to grow through repeated execution.

**Alternative considered:** Automatic skill inference from step descriptions using LLM. Rejected — too opaque, too expensive for a side-effect system, and violates "reference, not engine" principle.

### BF-241 — NATS JetStream Reconnect Resilience (2026-04-26)

**Context:** After a NATS server restart mid-session (~13h stable), `_reconnected_cb` only set `connected=True` — it did not recreate streams or re-subscribe JetStream consumers. All `js_publish()` calls failed with "no response from stream" until ProbOS restart. The stream recreation and consumer re-subscription logic already existed inside `set_subject_prefix()` but was not reusable.

**Decision:** Extracted `_recover_jetstream()` from `set_subject_prefix()` (DRY). Two-phase recovery: Phase 1 recreates tracked streams via `recreate_stream()` (BF-232 pattern), Phase 2 deletes stale consumers (BF-223 pattern) and re-subscribes from `_active_subs` tracking (JS entries only, not core). Replaced nested `_reconnected_cb` closure in `start()` with `_on_reconnected()` instance method for testability. Log-and-degrade on partial failure (stream failure must not block consumer re-subscription). `_resubscribing` flag set during Phase 2. MockNATSBus updated for interface parity.

**Consequences:** NATS resilience stack complete: BF-229 (core NATS fallback) → BF-230 (publish retry) → BF-231 (health monitoring) → BF-232 (recreate_stream) → BF-241 (reconnect recovery). Three-layer defense-in-depth: file-backed streams (primary) → reconnect recreation (secondary) → BF-230 publish fallback (tertiary). `set_subject_prefix()` now delegates to `_recover_jetstream()` for stream/consumer recovery, handling only core NATS re-subscription itself.

### AD-664 — EventLog Diagnostic Infrastructure (2026-04-26)

**Context:** EventLog events carried only flat string fields with no structured payload, correlation ID, or parent chain. Root-cause tracing impossible. No agent held formalized EventLog query authority — Engineering diagnostic relay chains dead-ended. Crew-originated (Forge + Anvil, 5 proposals). Issue #337.

**Decision:** Added three columns to EventLog schema: correlation_id (TEXT), parent_event_id (INTEGER), data (TEXT/JSON). Extended log() with keyword-only params (zero existing callers break). log() now returns row ID for parent chaining. Added query_structured() for correlation/event filtering and get_event_chain() for parent-chain traversal. Retrofitted emergent pattern events (consolidation_anomaly, emergence_trends via DreamAdapter), mesh events (intent_broadcast, intent_resolved), and QA events with structured payloads and correlation IDs. Declared eventlog_diagnostic_query capability on EngineeringAgent with _handled_intents gate and LLM instructions; programmatic query handler deferred to follow-up AD (requires skill registration or tool-feeding pattern design). Idempotent schema migration handles existing databases.

**Consequences:** Engineering agents can now terminate diagnostic relay chains by querying structured EventLog data. Causal chains are traceable via correlation_id (e.g., all events from one dream cycle) and parent_event_id (direct predecessor links). Future: migrate remaining callers to structured payloads, add EventLog API router for HXI diagnostic panel, federation-level event correlation.

**Context:** AD-618b delivered BillRuntime and AD-618c delivered built-in bills. No HXI surface existed for bill visibility or manual activation.
**Decision:** Added definition registry to BillRuntime (3 methods: register_definition, list_definitions, get_definition). Router uses BillInstance.to_dict() for instance serialization — the dataclass owns its shape. WebSocket handlers use refetch-on-event pattern (re-fetch full instance list on any bill lifecycle event) rather than partial state patching from event payloads, because AD-618b event payloads are summary-only (no status strings, no timestamps). Activate endpoint looks up BillDefinition first then passes it to activate() — the runtime takes a BillDefinition, not a bill_id string. Cancel endpoint checks bool return from cancel(), then fetches instance for response. Instance assignments endpoint reads instance.role_assignments directly — get_agent_assignments(agent_id) answers a different question ("what bills is this agent in?").
**Consequences:** Captain can view loaded bills, activate manually, monitor step progression, and cancel instances. Future: richer event payloads to eliminate refetch roundtrip, drag-and-drop role reassignment, bill template wizard.

**Context:** AD-618a delivered schema/parser but no actual Bill files exist. Ships need default SOPs available from first boot.
**Decision:** Four initial Bills cover the most common scenarios: emergency response (General Quarters), knowledge work (Research Consultation), incident management (Incident Response), routine operations (Daily Ops Brief). Bills are shipped as code artifacts in src/probos/sop/builtin/, not as Ship's Records documents. Loader functions discover and parse them at startup. Custom bills from Ship's Records are loaded separately and may shadow built-ins of the same slug. Invalid files are logged-and-skipped, not fatal. Incident Response demonstrates XOR gateway with dual-input convergence pattern (downstream step lists both branch outputs as inputs). Schedule triggers (daily_operations_brief cron) are parsed but inert until a future scheduler AD.
**Consequences:** ProbOS ships with usable SOPs out of the box. Report archival is the cognitive skill holder's responsibility (no dedicated WRITE_TO_RECORDS action yet — future AD). Additional bills (Code Review, Onboarding, Self-Mod Review, Federation Handshake) are future ADs. Captain can create custom bills in Ship's Records.

### AD-618b — Bill Instance + Runtime

**Date:** 2026-04-25
**Status:** Complete

**AD-618b: BillRuntime is a stateless in-memory service — BillInstances are transient.** They live for the duration of the SOP execution. Role assignment uses BilletRegistry's existing roster with qualification filtering (WQSB pattern). Step lifecycle is tracked but NOT enforced — agents consult the SOP with judgment ("reference, not engine"). Failed steps cascade to bill failure (future: per-step criticality). No Ward Room push notifications in this AD — agents discover assignments via `get_agent_assignments()`. All timestamps use `time.time()` (wall-clock) — `time.monotonic()` rejected because serialized timestamps must be meaningful across process restarts. `BILL_CANCELLED` is distinct from `BILL_FAILED` — cancellation is intentional (authority decision), failure is unintentional (step error). `allow_partial_assignment` config controls whether bills can activate with unfilled roles (default False). Concurrency limited via `max_concurrent_instances` (default 10). Event emission via late-bound sync callback (same pattern as BilletRegistry, ToolRegistry). AD-618c provides built-in YAML files, AD-618d builds HXI dashboard, AD-618e bridges step completions to Cognitive JIT.

### AD-618a — Bill Schema + Parser

**AD-618a: Bill Schema foundation — YAML-first, BPMN-vocabulary, no execution engine.** Bills are declarative YAML files parsed into BillDefinition dataclasses. Schema uses BPMN vocabulary (XOR/AND/OR gateways, parallel lanes, sub-processes) for multi-agent SOP definition. Parser validates role references (strict when roles section present), branch targets, step ID uniqueness, action types, gateway-branch consistency (XOR/OR require branches), and condition step references (`step:{id}.{output}` validates step ID exists). Bills are stored in Ship's Records (`bills/` subdirectory) as raw YAML — `write_bill()` bypasses `write_entry()` (which wraps in markdown frontmatter, corrupting the YAML); `list_bills()` globs `*.bill.yaml` instead of `*.md`. Design principle: "Reference, not engine" — agents consult Bills with judgment, they are not puppeted by a state machine. No Bill events or runtime execution in AD-618a — those come in AD-618b.

### AD-664 — EventLog Diagnostic Infrastructure (Planned)

**Date:** 2026-04-25
**Status:** Planned

**AD-664: EventLog Diagnostic Infrastructure — Structured Payloads + Query Authority.** Two intertwined gaps identified by 5 crew improvement proposals (Forge + Anvil). **(A) Structured payload gap:** EventLog events emit bare string labels — no structured payload, correlation ID, parent_event_id, or source agent. Root-cause tracing and cross-agent correlation are impossible. 24h dual-path diagnostic confirmed the absence. Solution: structured payload schema on EventLog events. **(B) Query authority gap:** No agent holds confirmed, documented execution authority for scoped EventLog queries. Diagnostic chains dead-end because everyone can forward but nobody can execute. Solution: formalized scoped read authority for Engineering agents. These must be solved together — structured data is useless without query authority, and query authority is useless without structured data to query. **Second batch of crew improvement proposals** from this instance. Issue #337.

### BF-239 — Ward Room Thread Engagement Tracking (2026-04-25)

**Date:** 2026-04-25
**Status:** Closed

**Context:** Agents double-posted in all-hands threads despite four infrastructure dedup layers (BF-234/236/237/197). Root cause: BF-236 checks at dispatch time, but the agent's serial cognitive queue processes intents sequentially — by the time the second intent arrives, the first has completed but the router already dispatched it.

**Decision:** Fix at the agent cognitive layer using working memory engagement tracking, not at the infrastructure layer. Agent registers an ActiveEngagement("ward_room_reply", thread_id) before the cognitive lifecycle and checks for it at handle_intent entry. Cognitive lifecycle extracted to `_run_cognitive_lifecycle` helper; try/finally at call site ensures engagement cleanup on all exit paths (normal, compound early return, exception). Serial queue (max_ack_pending=1) guarantees the check always sees records from prior completions. @mentions and DMs bypass the gate. Infrastructure dedup layers (BF-236, BF-198) retained as defense-in-depth backstops.

**Lesson learned:** Infrastructure guardrails were solving a problem that belonged at the cognitive layer. The agent's working memory already had the primitives (ActiveEngagement) — they just weren't being used for ward room replies. Before adding infrastructure dedup, ask: "Could the agent solve this itself?"

**Consequences:** Five-layer dedup stack. Agent-level fix is zero-token cost (synchronous dict lookup, no LLM call). Future consideration: BF-198's _responded_threads (600s window) may be redundant with engagement tracking + BF-236's round tracker.

### BF-237 — Pipeline-level post budget (Closed)

**Date:** 2026-04-25
**Status:** Accepted

**BF-237: Single-invocation post budget prevents N+1 posts per pipeline run.** When an LLM response contains multiple `[REPLY]` blocks or a `[REPLY]` plus residual text, the proactive loop's `_extract_and_execute_replies()` fires `create_post` for each block, then `process_and_post()` Step 7 fires another `create_post` for the cleaned remainder — producing N+1 posts from a single invocation. Observed as Atlas posting two near-identical analyses of the same observation.

Fix: `PostBudget` dataclass (`spent: bool = False`) threaded from `process_and_post()` through `extract_and_execute_actions()` → `_extract_and_execute_actions()` → `_extract_and_execute_replies()`. The first `create_post` in the reply loop sets `budget.spent = True`; subsequent `[REPLY]` blocks and the Step 7 main post check the budget and skip with a warning log. Same gate applied to `[MOVE]` board posts in the recreation extraction loop. `post_budget=None` backward-compatible — no budget enforcement, all posts fire (matches pre-BF-237 behavior).

Steps 8-10 (record_agent_response, record_round_post, update_cooldown) remain UNCONDITIONAL — they must run whether or not Step 7 posted, to keep BF-236's round tracker accurate.

Telemetry event `pipeline_post_budget_exceeded` emitted on suppression for observability.

Completes the four-layer dedup stack: BF-234 (transport, identical intent IDs) → BF-236 (dispatch, round-scoped tracker) → BF-237 (pipeline, single-invocation budget) → BF-197 (content, similarity guard).

### BF-236 — Semantic duplicate dispatch gap (Open)

**Date:** 2026-04-25
**Status:** Open

**BF-236: Dispatch eligibility missing `has_agent_responded()` gate.** BF-234 closed the transport-layer duplicate gap (identical intent IDs from JetStream redelivery). BF-198 added semantic round-tracking via `has_agent_responded()` / `record_agent_response()`. But BF-198's gate is only enforced during proactive context gathering (`proactive.py`), not during reactive dispatch eligibility (`_route_to_agents()` in `ward_room_router.py`). Result: two `route_event()` calls racing past eligibility checks before either records a response → agent dispatched twice → composes two near-duplicate posts with different wording. Observed on 6/12 agents on a single Improvement Proposals thread. Fix: add `has_agent_responded()` check in `_route_to_agents()` alongside existing cooldown and round-participation filters. This is the dispatch-level gate BF-234's DECISIONS.md entry deferred to BF-236 ("Post-boundary defense deferred to BF-236 if consumer-side counter shows residual duplicates"). Issue #339.

### BF-235 — Stale Identity Rendering (Closed)

**Date:** 2026-04-25
**Status:** Accepted

Two `@lru_cache` decorators in `standing_orders.py` (`_load_file` and `_build_personality_block`) persist indefinitely within a process. On stasis resume, these caches served stale identity blocks (wrong callsign, CMO, peers) to `compose_instructions()`, which is called on every `decide()` cycle. The module-level `_DECISION_CACHES` dict in `cognitive_agent.py` compounded the issue by serving stale decisions (produced with old system prompts) for up to 3600s.

Fix: call `clear_cache()` and `evict_cache_for_type()` for all crew agents during stasis recovery in `finalize.py`, unconditionally on `_lifecycle_state == "stasis_recovery"` (not gated behind `warm_boot_orientation` config). Added defensive `clear_cache()` on all startups for test surface uniformity. Added diagnostic logging of callsign at orientation time.

This completes the identity restoration chain: BF-057 (callsign from birth cert) → BF-101 (fallback resolution) → BF-049 (ontology sync) → BF-083 (runtime override) → BF-235 (cache invalidation).

**Alternatives considered:**
- Adding TTL to `@lru_cache` — rejected: Python's `lru_cache` doesn't support TTL natively. Adding `cachetools.TTLCache` would introduce a dependency for a problem that only occurs at stasis boundaries.
- Clearing caches inside `set_orientation()` — rejected: `set_orientation` is called in other contexts (cold start, re-orientation commands) where cache invalidation may not be needed. Startup is the right boundary.
- Gating cache invalidation behind `warm_boot_orientation` config — rejected: cache staleness is a lifecycle event (stasis resume), not a rendering policy. If an operator disables warm-boot orientation, the bug would return. Invalidation must be unconditional on stasis resume.

### BF-234 — Consumer-side dispatch dedup

**BF-234: Consumer-side dispatch dedup is the authoritative gate against transport-layer duplicates.** Gate placed in `IntentBus._on_dispatch()` (JetStream consumer callback in `intent.py`), not in the router (publisher side). Router dispatches exactly once — the duplication happens at or after JetStream publish (BF-230 retry, server redelivery). Only the consumer sees the second copy. Scoped to `ward_room_notification` intent type only. Window is 300s (matches JetStream `ack_wait=300` in `_js_subscribe_agent_dispatch`) — with `max_ack_pending=1`, msg #2 queues behind msg #1's full cognitive chain, so the window must cover max handler duration. BF-198 `has_agent_responded()` / `record_agent_response()` remain semantic round-tracking for proactive-loop dedup — different invariant, different window, different key. Post-boundary defense (pipeline-level gate) deferred to BF-236 if consumer-side counter shows residual duplicates.

### BF-236 — Round-scoped post tracker

**BF-236: Round-scoped post tracker is the correct invariant for dispatch-level semantic dedup — not BF-198's `_responded_threads`.** BF-198 tracks `(agent_id, thread_id)` with 600s eviction for proactive-loop dedup; reusing it as a dispatch gate would block agents from responding to Captain follow-ups for 10 minutes. BF-236 adds a separate `_posted_in_round` tracker (same key shape, different lifecycle): cleared on Captain repost alongside `_round_participants` so agents become eligible again when the Captain follows up. Recorded by WardRoomPostPipeline after `create_post` (not at delivery) — only real posts register, avoiding false positives from agents dispatched but filtered by BF-197 or LLM error. Coverage is partial (honest): catches duplicates when multi-second LLM handler latency means the first post is recorded before the second `route_event()` runs eligibility. Sub-second rapid-fire races fall through to BF-234 (transport-layer dedup on identical intent IDs) and BF-197 (content similarity guard). Ordering between post-event-fan-out and `record_round_post` is best-effort; race is bounded by Python's single-threaded asyncio scheduling and rarely matters in practice. Three defense-in-depth layers: BF-234 (transport) → BF-236 (dispatch, round-scoped) → BF-197 (content).

### BF-233 — Grounding check false positive fix

**Date:** 2026-04-24
**Status:** Complete

**BF-233: Expand BF-204 grounding source with entity IDs from input context.** The deterministic confabulation check (BF-204) built its grounding source from thread text + ANALYZE result only, missing entity IDs the agent was explicitly given in params (thread_id, channel_id, author_id) and identity keys (_agent_id, intent_id). Agents referencing these legitimate IDs in compose output triggered false positive suppression — observed across 7+ agents on Captain's All Hands message. Fix appends entity IDs to the grounding source string. Only IDs from the agent's own input context are whitelisted; truly fabricated hex IDs are still caught (threshold >= 2 ungrounded). BF-204 core protection preserved. **Known limitation:** Cross-agent post UUID references (other agents' full post UUIDs not in the responding agent's params) may still trigger false positives if agents use the full UUID instead of the truncated 8-char bracket form from thread context. Mitigated by agents naturally using `[deadbeef]` truncated form. Future fix: router could append full post UUIDs to params if observed in production.

### BF-232 — ensure_stream uses recreate_stream for stale subject cleanup

**Date:** 2026-04-24
**Status:** Complete

**BF-232: Split ensure_stream / recreate_stream.** Completes the BF-229/230/231 NATS resilience trilogy. The add-or-update pattern in `ensure_stream()` silently failed to change subject filters when prefixes changed across boots — `update_stream()` on some NATS server versions is a no-op for subject changes (BF-231 finding). New `recreate_stream()` method uses delete-then-create for explicit recreation. `ensure_stream()` retains non-destructive add-or-update semantics for future idempotent callers. Phase 2 startup and `set_subject_prefix()` use `recreate_stream()`. `_delete_stream()` warning logging now distinguishes benign "not found" (DEBUG) from real failures (WARNING). Stream retention sacrifice is acceptable — all current streams are transient event buses (max_age 5–60 min).

---

### AD-599 — Reflection as Recallable Episodes

**Date:** 2026-04-26
**Status:** Complete
**Issue:** #173

**AD-599: Dream Step 15 promotes consolidation insights into recallable episodes.** Dream consolidation (Steps 7–14) produces high-value analytical insights locked in write-only storage (CognitiveJournal, Ship's Records). Step 15 creates `[Reflection]` episodes in EpisodicMemory from four sources: convergence reports, emergence snapshots, notebook consolidations, and dominant cluster patterns. `MemorySource.REFLECTION` source tag. Deterministic `reflection-{content_hash}` IDs prevent cross-cycle duplication via existing write-once guard. `agent_ids=[]` bypasses per-agent rate limiting; agent participation preserved in `dag_summary["involved_agents"]`. Rate-limited to 3 per cycle (configurable). No LLM calls — reflections composed from structured data already computed by earlier steps.

**Alternative considered:** LLM-synthesized reflections for richer language. Rejected — adds latency, cost, and non-determinism. Structured composition is sufficient because ChromaDB semantic search handles fuzzy matching.

---

### AD-595e — Qualification Gate Enforcement

**Date:** 2026-04-26
**Status:** Complete
**Parent:** AD-595 (Billet-Based Role Resolution)

**AD-595e: Enforcement gates at three cognitive pipeline points.** Gates at bill step start (BillRuntime), proactive duty dispatch (ProactiveCognitiveLoop), and agent context injection (CognitiveAgent). Two-flag config: `enforcement_enabled` (default false) + `enforcement_log_only` (default true) enables shadow mode rollout — runs checks and emits QUALIFICATION_GATE_BLOCKED events but does not block. All gates default ALLOW for graceful degradation (missing store, missing registry, exception → pass through). Breaking change: `BillRuntime.start_step()` is now async. CognitiveAgent caches qualification standing with 5-min TTL to avoid per-decide() async lookups. BilletRegistry gains `get_qualification_standing()` (billet-based summary) and `check_role_qualifications()` (explicit list check). Cold-start tolerance: agents with no test results always pass.

---

### AD-595d — Qualification-Aware Billet Assignment

**Date:** 2026-04-24
**Status:** Complete
**Issue:** #TBD
**Parent:** AD-595 (Billet-Based Role Resolution)

**AD-595d: Data model + check API, no production gate.** Billets can declare `required_qualifications` (list of test names from AD-539). `check_qualifications()` async method verifies agent results from QualificationStore. `assign_qualified()` combines check + assign in one call. `allow_untested` parameter handles cold-start (no test results yet → allow) vs promotion (must have passed → block). `assign()` is NOT modified — stays sync and unconditional. Production assignment path (`agent_onboarding.py`) still calls `assign()`, unchanged. Gate enforcement deferred to AD-595e (promotion workflow). This split avoids the incoherent middle ground of logging-but-not-blocking and lets the data model ship immediately.

---

### AD-595c — Standing Orders Templating — Billet-Aware Instructions

**Date:** 2026-04-24
**Status:** Complete
**Issue:** #165
**Parent:** AD-595 (Billet-Based Role Resolution)

**AD-595c: Post-processing template substitution for billet references.** Standing orders `.md` files can use `{Billet Title}` syntax to reference billets dynamically. Resolution happens as a post-processing pass in `compose_instructions()`, after all tiers are concatenated. Existing hardcoded references ("the Chief Engineer") still work — template syntax is opt-in. Filled billets render as `Callsign (Title)`, vacant billets render as `Title (vacant)` — giving agents an explicit signal to escalate up the chain rather than messaging a non-existent holder. Code blocks (``` and ~~~) and inline backtick spans are excluded from processing. Known limitation: multi-backtick inline code spans (``` ``code`` ```) are not handled; authors should avoid `{Title}` inside inline code. The substitution runs per compose_instructions() call (called each decide() cycle) without caching — currently sub-millisecond on ~30KB text; if profiling shows cost, add version-keyed cache. Module-level `_billet_registry` state follows existing standing_orders.py module pattern (file caches are also module-scoped). No changes to existing standing orders files — this just enables future use.

---

### AD-595b — Naming Ceremony → BilletRegistry Integration

**Date:** 2026-04-24
**Status:** Complete
**Issue:** #165
**Parent:** AD-595 (Billet-Based Role Resolution)

**AD-595b: Billet assignment coupled to naming ceremony.** Added `BilletRegistry.assign()` — validates post exists, emits `BILLET_ASSIGNED`. Does NOT write to DepartmentService (ontology already has the assignment). Billet assignment placed as a single block after identity issuance (AD-441c) rather than three separate blocks (cold/warm/non-crew) with tracking flags — simpler, covers all paths uniformly, and `assign()` is idempotent. OrientationContext.billet_title added so agents know their formal billet at cognitive grounding time, enriched via `dataclasses.replace()` on the frozen dataclass.

---

### AD-595a — BilletRegistry Foundation

**Date:** 2026-04-24
**Status:** Complete
**Issue:** #165
**Parent:** AD-595 (Billet-Based Role Resolution)

**Decision:** BilletRegistry is a read-side facade over DepartmentService (Interface Segregation) — it does NOT own billet data, DepartmentService remains source of truth for posts and assignments. Title-based resolution is case-insensitive via a lowercase title→post_id index built eagerly in the constructor. BilletHolder is a frozen dataclass to prevent accidental mutation that drifts from DepartmentService. Registry is eagerly initialized in `VesselOntologyService.initialize()` (not lazy) to avoid race conditions. Event callback is late-bound in `finalize.py` via `set_event_callback()` because the event bus isn't available during ontology construction. BILLET_ASSIGNED/BILLET_VACATED event types are reserved — actual emission deferred to AD-595b when assign/vacate mutators are added. Follows the Navy Watch Bill model: billets are permanent positions, agents rotate through them. 17 new tests.

**Key decisions:**
| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Facade, not replacement | DepartmentService is mature + tested; BilletRegistry adds title resolution and roster snapshots without duplicating data |
| 2 | Frozen BilletHolder | Prevents snapshot mutation that silently drifts from source of truth |
| 3 | Eager init, not lazy | Race conditions: multiple callers could trigger concurrent initialization |
| 4 | Late-bound event callback | Event bus unavailable during Phase 3 ontology construction; wired in Phase 8 finalize |

---

### AD-584d — Elaborative Encoding via Enriched Embeddings

**Date:** 2026-04-24
**Status:** Complete
**Depends on:** AD-584c (scoring rebalance), AD-605 (anchor-enriched document)

**Decision:** ChromaDB embedding document now includes reflection text (aligning with FTS5 which already indexed it) and 2-3 heuristic question seeds per episode. Questions are template-based (no LLM call) using intent_type, outcome results, and department. Reflection is NOT templated into questions — it's already in the embedding text, and templating produces grammatically broken questions that hurt embedding quality. This bridges the Q→A retrieval gap: when agents recall with question-like queries, the question seeds create direct semantic overlap with stored episodes. Note: embedding now includes agent reflection content — recall queries may match on agent meta-commentary, not just observed events. This aligns with FTS5 behavior (which already indexed reflections). Research basis: Craik & Tulving (1975) depth of processing. Existing episodes are NOT retroactively re-embedded — new enrichment applies to episodes stored after deployment. 15 new tests.

---

### BF-231 — Delete-and-Recreate JetStream Streams on Prefix Change

**Date:** 2026-04-24
**Status:** Closed

**Decision:** `set_subject_prefix()` previously called `ensure_stream()` which tried `add_stream()` → fallback `update_stream()`. Subject filter updates could silently fail on some NATS server versions, leaving streams with stale DID prefixes after `probos reset`. Fix: delete the stream first, then recreate with correct subjects. Safe because ProbOS JetStream streams are transient event buses with short retention (5-60 min max_age). BF-223's per-consumer cleanup is preserved as defense-in-depth — stream deletion cascades to consumer deletion, making BF-223's explicit `delete_consumer()` calls largely redundant, but they guard consumers on streams not tracked in `_stream_configs`. Alternative considered: flushing streams in `probos reset` — rejected because `set_subject_prefix()` is the right fix location (handles any prefix change, not just reset, and works even if NATS wasn't running during reset). Completes BF-229/230/231 trio — closes the entire class of "JetStream silently dropped events after DID change" incidents. 5 new tests.

---

### AD-673 — Automated Anomaly Window Detection

**Date:** 2026-04-26
**Status:** Planned
**Depends on:** AD-662 (AnchorFrame provenance fields), AD-663 (producer wiring)

**Decision:** Create an AnomalyWindowManager service that detects system anomaly periods and manages their lifecycle. AD-662 added `anomaly_window_id` to AnchorFrame and social_verification.py applies the `anomaly_window_discount` (default 0.5) to pairs involving anomaly observations — but nothing currently detects anomaly windows or stamps episodes with window IDs. The field is consumer-ready infrastructure with no supplier. AnomalyWindowManager opens named windows (`aw-{uuid}`) based on system signals: NATS consumer lag (queue pressure), LLM error rate/latency spikes, trust cascade warnings (AD-558), and alert condition transitions (GREEN→YELLOW/RED). Episode stamping hooks into `EpisodicMemory.store()` to inject the active window ID into AnchorFrame at construction time — producers (AD-663) don't need per-site anomaly awareness. Retrospective tagging back-stamps recent episodes recorded before detection triggered. Note: `emergent_detector.py`'s `trust_anomaly_window` (600s rolling temporal window for anomaly count accumulation) is a different concept — it's a duration for counting anomaly occurrences, not a named period identifier.

---

### AD-665 — Corroboration Source Validation

**Date:** 2026-04-27
**Status:** Complete
**Depends on:** AD-662 (provenance infrastructure — COMPLETE), AD-663 (producer wiring — COMPLETE)

**Decision:** Replace binary shared-ancestry veto in `compute_anchor_independence()` with graded provenance weights. Same-origin-different-version pairs receive configurable `version_independence_weight` (default 0.7, no empirical basis — tunable per deployment). Single score, no dual-score `min()` combination — graded weight integrates directly into the existing independence formula. Anomaly discount (pair_weight denominator) and version independence weight (numerator credit) are orthogonal, no double-counting. `ProvenanceValidationResult` provides structured diagnostic report without exposing content (privacy invariant preserved). Transitive ancestry (A→B→C chains) explicitly deferred — requires `AnchorFrame` schema extension not yet designed. 16 new tests including privacy boundary verification. Triggered by Reed (Science) improvement proposals.

---

### AD-663 — Provenance Producer Wiring (2026-04-26)
**Context:** AD-662 added consumer-side provenance validation (`_share_artifact_ancestry`, anomaly window discount) but no producer populates the three AnchorFrame provenance fields. AD-665 adds graded scoring but is production no-op without populated fields. BF-226/227 demonstrated the failure mode: multiple agents observe the same WR post during queue pressure, observations pass spatiotemporal independence checks but share corrupted ancestry.
**Decision:** Wire 4 highest-risk episode producers to populate `source_origin_id` and `artifact_version` at AnchorFrame construction. Dream consolidation reflections deferred — deterministic episode IDs already provide dedup, and provenance fields would encode the same content_hash as both origin and version, adding no independent signal. Provenance strategy is site-specific: WR uses post/thread IDs with type prefixes (`wr-post:`, `wr-thread:`), proactive uses observed WR post IDs from context, cognitive agent uses correlation_id. Version fingerprints use SHA-256 truncated to 16 hex chars. `anomaly_window_id` explicitly deferred — no automated anomaly detection infrastructure exists. Remaining producers (no-response, peer repetition, feedback, smoke test, DM) are low corroboration risk and retain empty provenance.
**Consequences:** AD-662's consumer-side checks become active for new WR-derived episodes. AD-665's graded scoring will work for post-edit scenarios (same origin, different body hash → different artifact_version). Agents observing the same WR post during different duty cycles now trigger shared-ancestry detection. Legacy episodes retain empty provenance and are treated as independent (no behavioral change for existing data).

---

### AD-662 — Corroboration Source Provenance Validation

**Date:** 2026-04-23
**Status:** Complete
**Depends on:** AD-567f (Social Verification Protocol)

**Decision:** Extend SocialVerificationService with source provenance tracking. Three new AnchorFrame fields (source_origin_id, artifact_version, anomaly_window_id) enable ancestry-based independence checks. Two observations sharing the same source artifact are NOT independently anchored, regardless of spatiotemporal separation. Anomaly window observations contribute at config-driven discounted weight (default 0.5) to independence scoring (log-and-degrade, not reject). `artifact_version` alone does not trigger shared ancestry — only `source_origin_id` match does — to avoid false positives from version string collisions. Triggered by BF-226/227 where queue-pressure-generated artifact versions appeared to corroborate each other but shared corrupted ancestry. AD-662 is infrastructure-only (consumer-side validation); AD-663 wires the producers to populate provenance fields at AnchorFrame construction sites. 13 new tests.

---

### AD-654 — Universal Agent Activation Architecture (UAAA)

**Date:** 2026-04-21  
**Status:** In Progress (AD-654a complete, AD-654b complete, AD-654c complete, AD-654d complete, e deferred)  
**Depends on:** AD-637 (NATS Event Bus)  
**Research:** `docs/research/universal-agent-activation-research.md`

**Decision:** Implement event-driven agent activation using NATS JetStream durable consumers instead of synchronous NATS request/reply. Five sub-ADs:

1. **AD-654a (Async Dispatch):** Ward room router publishes notifications to JetStream fire-and-forget. Agents consume at their own pace and post their own responses. Eliminates the NATS send timeout cascade where 14 simultaneous request/reply calls block during LLM processing. New `WardRoomPostPipeline` extracts post-processing (similarity guard, endorsements, recreation commands) from both the router and proactive loop into a reusable pipeline class. `IntentBus.publish()` added for fire-and-forget; `send()` preserved for genuinely synchronous callers (Captain DMs, procedure steps).

2. **AD-654b (Cognitive Queue):** Per-agent priority mailbox (Actor Model). Three tiers: immediate (< 10s), soon (30-60s), ambient (proactive cycle). Proactive timer becomes the ambient processor. Higher-priority items bypass cooldown.

3. **AD-654c (TaskEvent + Dispatcher):** Universal event protocol. TaskEvent dataclass with source, priority, target (agent/capability/department/broadcast), payload. Dispatcher resolves abstract targets using Qualification Framework, Trust/Rank, Workforce Scheduling.

4. **AD-654d (Internal Emitters):** RecreationService, WardRoom @mentions, WorkItem state transitions, agent-to-agent delegation all become TaskEvent emitters.

5. **AD-654e (External Integration):** MCP Apps, MCP Provider/Consumer, webhook adapters. Deferred until Phase 1-3 validated.

**Key architectural principles (from research paper):**
- Events, not polling — proactive scan is fallback, not primary
- Priority is semantic, not structural — comes from TaskEvent, not delivery mechanism
- Context travels with the event — focused payload, not ambient scanning
- Dispatcher is the control point — all activation flows through it
- Emitters don't know about agents — decoupled via target abstraction
- Backward compatible — existing proactive loop, DM router continue working

**Why not keep request/reply:** NATS request/reply has a TTL timeout. Agent handlers take 15-30s for cognitive chains. When an agent is busy processing one intent, subsequent requests timeout. This is fundamentally incompatible with notification-style intents where the caller doesn't need a synchronous response. JetStream publish + durable consumer eliminates timeouts entirely — messages queue and agents drain at their own pace.

**Why agents self-post (not router):** The router collecting and re-posting agent responses is an intermediary that adds latency and coupling. In an event-driven model, agents should post their own ward room responses — the same way humans type replies in a chat room. This aligns with agent sovereignty (the agent decides what to post) and eliminates the synchronous gather pattern.

**BF-223 (2026-04-22) — JetStream durable consumer prefix race.** AD-654a's per-agent dispatch consumers were created during pool onboarding (Phase 3) with `probos.local` prefix. Ship commissioning (Phase 7) changes prefix to `probos.did:probos:{uuid}`. NATSBus.set_subject_prefix() re-subscribes, but NATS server-side durable consumer config retains the original `filter_subject` — re-subscribe silently reuses stale config. All agent dispatch consumers had `delivered_seq=0`. **Fix:** (1) NATSBus safety net: `set_subject_prefix()` deletes old durable consumers before re-creating. (2) IntentBus root fix: defer dispatch consumer creation until `finalize.py` calls `create_dispatch_consumers()` after ship commissioning. This mirrors the wardroom-router consumer pattern that already works. Third NATS prefix bug in the series (BF-221 → BF-222 → BF-223).

**BF-229 (2026-04-23) — NATSBus owns subject sanitization.** Ship DID `did:probos:<uuid>` contains colons, which are invalid in NATS subject tokens. `set_subject_prefix()` now sanitizes via compiled regex — NATS-unsafe characters become underscores. Callers may pass any string (raw DIDs, federation prefixes). Underscores chosen over dots to preserve single-token namespace depth (`probos.did_probos_<uuid>.*` not `probos.did.probos.<uuid>.*`). Fourth NATS prefix bug (BF-221 → BF-222 → BF-223 → BF-229). Also: `ensure_stream()` re-raises after logging (no more silent swallow), stream update failure promoted to ERROR with recovery instructions.

**BF-230 (2026-04-23) — js_publish resilience — bounded retry + degrade-to-core-NATS.** Chose 1 retry with 0.5s backoff + fallback to core NATS publish over alternatives (local buffer-and-replay, unbounded retry). Buffer would require persistence and replay logic — deferred until needed. Fallback to core NATS is best-effort: JetStream-only subscribers (WARDROOM durable, cognitive queue) will NOT receive the event via the fallback path. The fallback's value is crash prevention + server-side trail, not delivery guarantee.

**BF-106 (2026-04-24) — DreamingEngine dependency injection — constructor for Phase 4, setters for Phase 7.** Three monkey-patched private attrs in finalize.py replaced with clean injection. `records_store` forwarded through `init_dreaming()` constructor (available at Phase 5 from Phase 4 cognitive init). `ward_room` and `get_department` (from ontology) genuinely unavailable until Phase 7 — these get public setter methods instead. Follows AD-567d (ActivationTracker) pattern for constructor injection. Establishes the template: constructor injection where startup-phase ordering allows, public setter methods where it doesn't. Generalizes the AD-654c/d Law of Demeter discipline to startup wiring.

---

### AD-641g — Asynchronous Cognitive Pipeline via NATS

**Date:** 2026-04-17  
**Status:** Design  
**Parent:** AD-641 (Brain Enhancement Phase)  
**Depends on:** AD-637 (NATS Event Bus)

**Decision:** Decouple the cognitive chain steps (QUERY → ANALYZE → COMPOSE) via NATS message subjects rather than running them as a synchronous blocking sequence.

**Motivation:** The current chain pipeline adds cognitive depth (multi-step reasoning) but not perceptual depth (ability to see more). The QUERY step only receives what `_gather_context()` already fetched — a fixed sliding window of 5-10 recent items. Agents cannot browse deeper thread history or scan broadly across channels. Evidence: agent "Lyra" hallucinated a `[READ_CHANNEL]` command tag — the LLM expressing a genuine need the architecture doesn't provide.

**Design:**
- QUERY (browse) runs frequently, 0 LLM calls, publishes interesting items to `chain.{agent_id}.analyze`
- ANALYZE subscribes, processes selectively with LLM, gates whether a response is warranted
- COMPOSE only fires when ANALYZE says something is worth saying
- NATS provides backpressure, priority ordering, durable queues, and consumer groups
- Pattern is source-agnostic: same pipeline extends to document reading, web research, ship's state observation

**Research:** [docs/research/ad-641g-async-cognitive-pipeline.md](docs/research/ad-641g-async-cognitive-pipeline.md)

**Migration note (AD-644 Phase 3):** AD-644 Phase 3 migrates 7 environmental percepts (ward_room_activity, recent_alerts, recent_events, infrastructure_status, subordinate_stats, cold_start_note, active_game) into the cognitive chain via observation dict pass-through from `context_parts`. This is a temporary approach — `_gather_context()` in proactive.py already calls the underlying services, so creating QUERY operations that re-call the same services would violate DRY. When NATS decouples the pipeline (this AD), these 7 percepts should become native QUERY operations in `query.py` that subscribe to NATS subjects directly, replacing both the `_gather_context()` calls and the `_build_situation_awareness()` pass-through. The detection logic in `_build_situation_awareness()` is transport-agnostic and reusable.


### AD-643a — Intent-Driven Skill Activation

**Date:** 2026-04-18
**Status:** Complete
**Issue:** #283

**Decision:** Move augmentation skill loading from before the cognitive chain to after ANALYZE. Skills declare `probos-triggers` metadata; ANALYZE outputs `intended_actions`. Only skills whose triggers match the agent's expressed intent are loaded.

**Motivation:** All augmentation skills loaded on every `proactive_think` cycle regardless of what the agent intended to do. ~1,500 wasted tokens/cycle × 30 agents × 5 cycles = ~225K tokens/session. Communication chain fired for notebooks, leadership reviews — wrong chain for the action.

**Design:**
- `CognitiveSkillEntry` gains `triggers: list[str]` field, parsed from `probos-triggers` YAML metadata
- `find_triggered_skills()` matches `intended_actions` to skill triggers (falls back to intent matching for skills without triggers)
- Two-phase execution: triage (QUERY + ANALYZE) → extract `intended_actions` → route → targeted skill loading → execute (COMPOSE + EVALUATE + REFLECT)
- Communication chain only fires when `intended_actions` contains a comm action (`ward_room_post`, `ward_room_reply`, `endorse`, `dm`)
- Non-comm actions (notebook, leadership_review) skip chain, fall through to `_decide_via_llm()` with targeted skills
- Silent short-circuit at triage phase (no COMPOSE/EVALUATE/REFLECT)
- External chains (`_pending_sub_task_chain`) bypass intent routing (backward compat)
- Missing `intended_actions` falls back to pre-AD-643 all-skills behavior (backward compat)

**Research:** BDI plan library (Rao & Georgeff), OODA loop, Dual Process Theory (Kahneman). ANALYZE = System 1/2 gate. All BDI limitations addressed by existing ProbOS architecture (episodic memory, Ward Room, trust, standing orders, workforce scheduling, SOPs).

**Key decisions:**
| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Triggers on skills, not on chains | Open/Closed — new skills register triggers without modifying chain code |
| DD-2 | Triage re-executes on full chain path | Avoids modifying SubTaskExecutor; ~200 token overhead acceptable; AD-643b eliminates this |
| DD-3 | Non-comm actions skip chain entirely | No compose/evaluate/reflect templates exist for notebooks yet — AD-643c adds them |
| DD-4 | `intended_actions` is a JSON array, not enum | Extensible vocabulary; new thought processes add new action tags without prompt changes |

**Future:** AD-643b (Thought Process Catalog — declarative `ThoughtProcess`/`ThoughtAction` definitions replace hardcoded chains), AD-643c (multi-action processes + sequential execution).

---

### AD-643b — Skill Trigger Learning: Adaptive Trigger Discovery & Graduation

**Date:** 2026-04-18
**Status:** Complete (Phase 1+2 of 3; Phase 3 graduation deferred)
**Issue:** #284

**Motivation:** AD-643a requires agents to declare `intended_actions` for skills to load, but agents sometimes take undeclared actions (e.g., writing a notebook without declaring `notebook`). Quality skills don't load, degrading output. At scale (100+ triggers), injecting full trigger lists into prompts defeats token savings.

**Design:** Three-phase trigger learning lifecycle:
1. **Trigger Awareness** — inject scoped trigger list into ANALYZE (filtered by department + rank). Training wheels.
2. **Post-Hoc Feedback** — detect undeclared actions in COMPOSE output, inject feedback into REFLECT → episodic memory → future recall. Closed learning loop.
3. **Trigger Graduation** — track declaration accuracy per agent. Consistently correct → graduate (remove from prompt). Dreyfus progression: novice→expert. Prompt overhead trends to zero.

**Research:** Metacognitive monitoring (Flavell 1979), scaffolding→fading (Wood/Bruner/Ross 1976), situated cognition (Lave & Wenger 1991). Extends AD-535 Dreyfus model to trigger declarations.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DD-1 | Per-agent scoping, not global injection | Eligible triggers filtered by department + rank; ~15-25 tags per agent, not 100+ |
| DD-2 | Post-hoc detection, not capability gating | Skills are guidance, not gates; agent can still write notebook without skill loaded |
| DD-3 | Episodic memory as learning medium | REFLECT feedback → episodic storage → future recall. No new infrastructure |
| DD-4 | Graduation reduces overhead over time | Training wheels self-remove; mature crews have zero trigger injection overhead |
| DD-5 | Three-phase delivery | Each phase independently valuable and backward compatible |
| DD-6 | Re-reflect is a synchronous workaround | NATS decoupling (AD-643d) replaces re-reflect with message-flow interception |

---

### AD-643d — NATS-Based Trigger Feedback Pipeline

**Date:** 2026-04-18
**Status:** Deferred — blocked on AD-637 (NATS Event Bus)
**Parent:** AD-643 (Intent-Driven Skill Activation)
**Depends on:** AD-637 (NATS), AD-643b (trigger learning)

**Decision:** Refactor AD-643b's re-reflect workaround into a native NATS message-flow pattern once the cognitive pipeline is decoupled via NATS subjects (AD-641g).

**Motivation:** AD-643b detects undeclared actions *after* the full chain completes, then re-runs REFLECT as a partial chain to inject feedback into episodic memory. This works but is a synchronous workaround — the chain runs, completes, then a second REFLECT fires. With NATS subjects decoupling each chain step, trigger detection becomes a natural consumer in the message flow rather than a post-hoc re-run.

**Design (sketch — refine when AD-637 lands):**

Three options, not mutually exclusive:

1. **Intercept consumer.** A trigger-detection consumer subscribes to `chain.{agent_id}.compose.complete`. It inspects compose output for undeclared actions, enriches the observation with `_undeclared_action_feedback`, and forwards to `chain.{agent_id}.evaluate`. REFLECT receives feedback naturally — no re-run.

2. **BPMN-style gateway.** Exclusive gateway after COMPOSE: clean path (no undeclared actions) routes directly to EVALUATE; feedback path routes through DETECT → ENRICH → EVALUATE. Maps to BPMN 2.0 (ISO 19510:2013) process modeling. The chain becomes a declarative flow graph, not imperative code.

3. **Retriggerable REFLECT.** REFLECT subscribes to `chain.{agent_id}.reflect`. On undeclared action detection, publish a second message to the same subject with feedback. Both reflections enter episodic memory. Zero chain modification.

**What survives from AD-643b:** `_detect_undeclared_actions()` detection logic, feedback format, `get_eligible_triggers()` awareness injection, graduation tracking (Phase 3). Only the orchestration wrapper (`_re_reflect_with_feedback`) gets replaced.

**What gets removed:** `_re_reflect_with_feedback()`, `_re_reflect_compose_output` observation key, `_get_compose_output()` fallback parameter.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DD-1 | Deferred until NATS lands | Re-reflect works; refactoring before NATS exists is premature |
| DD-2 | Option 1 (intercept) is likely default | Simplest, preserves single REFLECT execution, no duplicate episodic entries |
| DD-3 | AD-643b detection logic reused as-is | Pattern matching is transport-agnostic |

---

### AD-637z — NATS Migration Cleanup + BF-221 Lift

**Date:** 2026-04-21
**Status:** Complete
**Parent:** AD-637 (NATS Event Bus)
**Closes:** BF-221

**Decision:** NATSBus owns the full subscription lifecycle. External code (IntentBus) subscribes via `nats_bus.subscribe()` and cleans up via `nats_bus.remove_tracked_subscription()` — no parallel tracking dicts. BF-221 emergency guard lifted: `IntentBus.send()` restored to NATS request/reply when connected.

**Key Design Decisions:**

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DD-1 | NATSBus lifecycle ownership | Eliminates zombie entries, double subscriptions, stale mapping bugs. One source of truth for all active subscriptions. |
| DD-2 | Un-prefixed subjects in `_active_subs` | `_full_subject()` applies current prefix at re-subscription time. No double-prefixing risk. |
| DD-3 | `_resubscribing` guard flag | Prevents `subscribe()`/`js_subscribe()` from re-adding entries during the re-subscription loop. |
| DD-4 | Prefix change callbacks are notification-only | NATSBus re-subscribes everything before calling callbacks. IntentBus callback logs only — no parallel re-wiring. |
| DD-5 | Ephemeral consumers for system events | ~176 event types would create 100+ durable consumers with name collisions. Ephemeral is correct for system events. |
| DD-6 | `subscribe_raw`/`publish_raw` excluded from tracking | Federation uses raw subjects to bypass per-ship prefix isolation. Must NOT re-key on prefix change. |
| DD-7 | BF-221 lift: NATS-first, direct-call fallback | One path per call, never both. NATS when connected, direct-call when disconnected. Prefix re-subscription ensures subs survive Phase 7 DID assignment. |
| DD-8 | BF-229: NATSBus owns subject sanitization | Callers may pass any string as prefix (including raw DIDs with colons). `set_subject_prefix()` sanitizes NATS-unsafe characters (`:`, spaces, etc.) to underscores. Enforced at the boundary that owns the NATS constraint, not at callers. Underscore preserves single-token namespace depth (`probos.did_probos_<uuid>.*` matches `probos.local.*` depth). |

---

### AD-644 — Agent Situation Awareness Architecture

**Date:** 2026-04-18
**Status:** Phase 1-4 Complete (full parity — 23/23 items). Phase 5 Design (deprecation).
**Issue:** #285

**Decision:** Migrate the ~23 context injections from the monolithic `_build_prompt_text()` into the cognitive chain architecture using a four-category model grounded in Endsley's Situation Awareness framework.

**Motivation:** When `proactive_think` was added to `_CHAIN_ELIGIBLE_INTENTS` (AD-632+), the chain path bypassed `_build_prompt_text()` — a 290-line function that had accumulated context injections across 15+ ADs. The chain's ANALYZE step receives standing orders (system prompt) but no dynamic data (user prompt). Result: agents return `intended_actions: ["silent"]` on every cycle, including scheduled duties. Zero duty reports produced in days of operation.

This is not a missing feature — it's an accidental regression. The cognitive chain provides better architecture than the single-call path, but the context it needs was never migrated.

**Design:** Four cognitive categories, each with a distinct mechanism:

| Category | What | Mechanism | Naval Analog |
|----------|------|-----------|-------------|
| **Innate Faculties** | Temporal awareness, working memory, self-monitoring, source attribution data, telemetry, ontology identity, orientation, confabulation guard, comm proficiency, trust/agency/rank | Populated into observation dict by agent before chain runs | Sailor knows the time, remembers what they just did, knows their chain of command, senses their own fatigue |
| **Situation Awareness** | Ward Room activity, infrastructure status, alerts, events, subordinate stats, crew status, cold-start notes, active games | QUERY step operations (`_QUERY_OPERATIONS` registry) | Sailor glances at status boards, hears bridge conversation, sees alert condition |
| **Watch Station Duties** | Active duty assignment, duty-specific instructions | `params.duty` → observation dict, ANALYZE renders duty context | Sailor reads their WQSB entry, holds their PMS card |
| **Standing Orders** | Self-monitoring rules, cognitive zones, communication protocols, source attribution policy, duty reporting expectations | `compose_instructions()` → system prompt (already works) | Sailor has memorized regulations and standing orders |

**Prompt consumers:** Both ANALYZE (`_build_situation_review_prompt`) and COMPOSE (`_build_proactive_compose_prompt`) are starved — both read `context.get("context", "")` which is empty. Both need updates: ANALYZE for full situation assessment, COMPOSE for duty framing, source attribution, confabulation guard, and comm proficiency.

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Four categories from cognitive science, not code organization | Endsley SA model (perception → comprehension → projection) maps to QUERY → ANALYZE → intended_actions. Categories scale independently |
| DD-2 | Innate faculties run for ALL chain executions, not just proactive_think | Temporal awareness and working memory are agent faculties, not intent-specific. A conscious agent always knows the time |
| DD-3 | Situation awareness via QUERY operations, not observation dict | QUERY operations are deterministic, dispatch-table registered, Open/Closed. New percepts added without modifying chain code |
| DD-4 | Duty context biases ANALYZE away from silence | When a duty is active, the agent has an obligation to report. Silence during duty requires explicit justification (inverted from free-form default) |
| DD-5 | Five implementation phases, independently deployable | Phase 1 (duty fix) is critical. Phases 2-4 restore full parity. Phase 5 deprecates `_build_prompt_text` proactive block |
| DD-6 | Standing orders additions are markdown-only, zero code changes | Source attribution and duty expectations are policy, not data |
| DD-7 | Source attribution split: policy (Cat 4) vs data (Cat 1) | Policy = behavioral guidance in standing orders. Data = episodic_count, procedural_count, oracle_used = innate self-knowledge |
| DD-8 | COMPOSE is a second consumer, not just ANALYZE | Both prompt templates render from the same observation dict. COMPOSE needs duty framing, source attribution, confabulation guard |

**Implementation phases:**
1. **Duty Context Restoration** — pass `params.duty` + trust/agency/rank through, update ANALYZE + COMPOSE prompts (critical fix)
2. **Innate Faculties** — `_build_cognitive_state()` populates temporal, working memory, self-monitoring, ontology, orientation, source attribution data, confabulation guard, comm proficiency
3. **Situation Awareness** — extend QUERY operations (ward_room_activity, infrastructure_status, recent_alerts, recent_events, subordinate_stats, cold_start_context, active_game)
4. **Standing Orders** — add source attribution policy + duty expectations to ship.md
5. **Deprecation** — mark `_build_prompt_text` proactive block as deprecated

**Parity:** 23-item checklist in research doc maps every `_build_prompt_text` injection to an AD-644 category and implementation phase.

**Research:** [docs/research/agent-situation-awareness-architecture.md](docs/research/agent-situation-awareness-architecture.md)

**Future:** Composes with AD-641g (NATS pipeline — percepts become NATS subscriptions), AD-618 (SOP Bills — duties become Bill triggers), AD-643a (intent routing — richer SA improves action decisions), AD-645 (Artifact-Mediated Chain — composition briefs replace routing slips).

---

### AD-645 — Artifact-Mediated Cognitive Chain

**Date:** 2026-04-18
**Status:** Phase 1-3 Complete (Composition Briefs + COMPOSE Enrichment + Metacognitive Storage)
**Parent:** AD-632 (Cognitive Chain Architecture)
**Related:** AD-644 (Situation Awareness), AD-641g (NATS Pipeline), AD-639 (Chain Personality Tuning), AD-573 (Working Memory)

**Decision:** Replace ANALYZE's thin routing-slip output (`intended_actions` + structured fields) with a **composition brief** — a structured plan that tells COMPOSE what to write about, what evidence to draw on, what tone to use, and what the response should cover. Additionally, pass environmental context (Phase 3 SA keys) through to COMPOSE so it has both the focused plan AND the raw material.

**Motivation:** AD-644 achieved full context parity (23/23 items) between the chain path and one-shot `_build_user_message()`, but chain-path responses remain measurably flatter, less confident, and less specific. Root cause: ANALYZE compresses its full situational understanding into a routing slip (~200 tokens of JSON), then COMPOSE works from that summary rather than the source material. The one-shot path gives the LLM everything at once; the chain loses information at the ANALYZE → COMPOSE handoff.

The architect/builder analogy: current ANALYZE is like saying "write a build prompt for phase 4" with no research. Proposed ANALYZE is like writing a detailed build prompt with evidence, scope, design decisions, and references. COMPOSE (the builder) reads the brief AND has access to the raw context — focused guidance + full material.

**Design:**

The composition brief contains:
- **situation** — what's happening (1-2 sentences)
- **key_evidence** — specific observations/data points COMPOSE should reference
- **response_should_cover** — what the response needs to address
- **tone** — audience-appropriate framing guidance
- **sources_to_draw_on** — which knowledge sources are relevant

`intended_actions` survives alongside the brief for programmatic skill routing (AD-643a).

**Artifact value beyond composition:**
- **Metacognitive memory** — stored in WorkingMemory as `category="reasoning"`, lets agent answer "What was I thinking?" Extends AD-573 from recording what happened to recording how the agent processed it.
- **Dream consolidation** — dreams can extract reasoning patterns, not just outcome patterns
- **Reinforcement signal** — EVALUATE assesses plan-to-output alignment: (brief, response, score) triples
- **Cognitive forensics** — trace whether failures are perception errors (bad brief) or execution errors (ignored brief)
- **Self-monitoring** — detect narrowing reasoning patterns before they manifest as output repetition
- **Privacy preserved** — Minority Report Principle: briefs are agent's private cognitive workspace, Counselor has no access

**NATS alignment:** Build briefs before NATS. The brief format becomes the NATS message payload on `chain.{agent_id}.analyze.complete` when AD-641g lands. No throwaway work.

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Build briefs before NATS | Higher-value change; pre-shapes NATS message format |
| DD-2 | Brief is part of ANALYZE JSON, not separate file | Flows through existing `prior_results` mechanism |
| DD-3 | SA keys flow to both ANALYZE and COMPOSE | COMPOSE needs raw material, not just brief's summary |
| DD-4 | Briefs are private (Minority Report Principle) | Agent's working memory, not Counselor surveillance |
| DD-5 | Brief is optional/backward compatible | Missing brief falls back to current behavior |
| DD-6 | Metacognitive storage uses existing WorkingMemory | No new infrastructure needed |
| DD-7 | EVALUATE alignment is additive, not gating | Signal without changing pass/fail threshold initially |

**Implementation phases:**
1. **Composition Brief** — ANALYZE prompt + output schema enrichment
2. **COMPOSE Context Enrichment** — render brief + pass SA keys to COMPOSE
3. **Metacognitive Storage** — store briefs in WorkingMemory post-chain
4. **EVALUATE Brief Alignment** — plan-to-output alignment criterion
5. **NATS Schema** (deferred to AD-641g) — brief dict becomes message payload

**Research:** [docs/research/ad-645-artifact-mediated-cognitive-chain.md](docs/research/ad-645-artifact-mediated-cognitive-chain.md)

---

### AD-646 — Universal Cognitive Baseline

**Date:** 2026-04-19
**Status:** Complete
**Issue:** #288
**Parent:** AD-644 (Situation Awareness), AD-632 (Cognitive Chain Architecture)
**Related:** AD-645 (Artifact-Mediated Chain), AD-641g (NATS Pipeline), AD-573 (Working Memory)

**Decision:** Split cognitive context assembly into a universal baseline (agent-intrinsic, runs for ALL chain executions) and intent-specific extensions (registered per intent type). The baseline provides temporal awareness, working memory, episodic recall, source attribution, ontology identity, trust/rank, and cognitive zone — regardless of what triggered the cycle.

**Motivation:** AD-644 Phase 2 added innate faculties to the proactive chain path, but the implementation depends on `context_parts` populated by `proactive.py`'s `_gather_context()`. Ward Room notifications bypass the proactive loop, so `context_parts` is empty — agents enter ANALYZE knowing the thread content but nothing about themselves. Result: chain-path Ward Room responses are activity-level ("I've been conducting wellness checks") while the one-shot path produces insight-level responses ("157/118/85 unread messages, cognitive load at 40-75% of crisis threshold") because `_build_user_message()` injects the full cognitive state directly.

The core design flaw: context assembly is intent-specific instead of layered. Every new chain-eligible intent will need its own AD-644-style migration. The fix should be applied once at the trunk, not per branch.

**Design:**

```
┌─────────────────────────────────────────┐
│  Universal Cognitive Baseline           │  ← ALL chain executions
│  (temporal, working memory, episodic,   │
│   source attribution, ontology,         │
│   trust/rank, cognitive zone)           │
├─────────────────────────────────────────┤
│  Intent Extensions                      │  ← Per intent type
│  proactive_think: SA sweep, self-mon    │
│  ward_room_notification: thread context │
│  (future intents: their own extensions) │
└─────────────────────────────────────────┘
```

Split `_build_cognitive_state()` into:
- `_build_cognitive_baseline()` — agent-intrinsic, zero external dependencies, zero async calls. Reads from agent attributes (working memory, temporal context, ontology). Called unconditionally.
- `_build_cognitive_extensions(context_parts)` — depends on externally-gathered data (self-monitoring, notebook index, telemetry). Called only when `context_parts` is available.

Update thread analysis prompt (`_build_thread_analysis_prompt`) and ward_room compose prompt to consume baseline keys. Proactive path unchanged (gets baseline + extensions + SA).

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Baseline is agent-intrinsic, not service-dependent | Zero async calls, zero latency impact. Working memory, temporal context, ontology are all in-memory agent state |
| DD-2 | Self-monitoring stays in extensions (not baseline) | Self-monitoring data (self-similarity, cooldowns) is gathered by proactive.py. Working memory already covers cognitive zone and recent actions for the baseline case |
| DD-3 | Baseline pre-shapes NATS message envelope | Universal baseline becomes the standard payload on `chain.{agent_id}.analyze`. Extensions are intent-specific fields |
| DD-4 | Apply once, works for all current and future intents | No more per-intent migration work. New chain-eligible intents inherit the baseline automatically |
| DD-5 | ~500-700 tokens added to ward_room ANALYZE prompt | Well within Sonnet's budget. Working memory capped at 1500 tokens |

**Scope:** ~100 lines across 3 files (cognitive_agent.py, analyze.py, compose.py). Zero new modules. Zero new infrastructure.

**Implementation phases:**
1. Split `_build_cognitive_state()` → baseline + extensions
2. Update thread analysis prompt to consume baseline keys
3. Update ward_room compose prompt to consume baseline keys
4. Regression verification (proactive path unchanged)

**Research:** [docs/research/ad-646-universal-cognitive-baseline.md](docs/research/ad-646-universal-cognitive-baseline.md)

### AD-646b — Chain Cognitive Parity (Close One-Shot Gaps)

**Date:** 2026-04-19
**Status:** Complete
**Issue:** #289
**Parent:** AD-646 (Universal Cognitive Baseline), AD-632 (Cognitive Chain Architecture)
**Related:** AD-588 (Introspective Telemetry), AD-623 (DM Self-Monitoring), AD-575 (Self-Recognition), AD-568a (Oracle Service), BF-102 (Cold-Start Note)

**Decision:** Close the remaining data gaps between the chain ward_room path and the one-shot ward_room path by adding two new QUERY operations, three baseline enhancements, and consuming already-present observation keys in chain prompts.

**Motivation:** AD-646 established the universal cognitive baseline, giving ward_room chains temporal awareness, working memory, trust metrics, ontology, and confabulation guards. But the one-shot ward_room path still injects six data sources the chain path lacks:

| # | Data Source | One-Shot Path | Chain Path (post AD-646) | Gap Type |
|---|-------------|--------------|--------------------------|----------|
| 1 | DM self-monitoring (AD-623) | `_build_dm_self_monitoring()` — async | Missing | Async — needs QUERY |
| 2 | Introspective telemetry (AD-588) | `IntrospectiveTelemetryService.get_full_snapshot()` — async | Missing | Async — needs QUERY |
| 3 | Cold-start note (BF-102) | `rt.is_cold_start` check | Missing | Sync — baseline |
| 4 | Rich source attribution (AD-568d) | `observation["_source_attribution"]` dataclass render | Simplified count only | Sync — baseline |
| 5 | Self-recognition (AD-575) | `_detect_self_in_content()` — sync regex | Missing | Sync — baseline |
| 6 | Oracle context (AD-568a) | `observation["_oracle_context"]` render | Key present but not consumed by prompts | Prompt consumption |

These gaps are why chain ward_room responses still confabulate more than one-shot — agents lack self-monitoring, telemetry grounding, and cross-tier knowledge context.

**Design:**

Four-part fix, each independently testable:

**Part A — New QUERY Operations (query.py):**
- `self_monitoring`: For DM threads, call `ward_room.get_posts_by_author()` + Jaccard similarity (same pattern as `_build_dm_self_monitoring()`). For all threads, check cognitive zone from VitalsMonitor. Returns warning string or empty.
- `introspective_telemetry`: Conditionally on `_is_introspective_query()` against thread text, call `IntrospectiveTelemetryService.get_full_snapshot()` + `render_telemetry_context()`. Returns rendered text or empty.

**Part B — Baseline Enhancements (cognitive_agent.py `_build_cognitive_baseline()`):**
- Cold-start note: `rt.is_cold_start` boolean → `_cold_start_note` key.
- Rich source attribution: Read `observation["_source_attribution"]` dataclass (set by perceive/recall at line 4327), render episodic_count, procedural_count, oracle_used, primary_source. Override the simplified count-only version.
- Self-recognition: `_detect_self_in_content(observation.get("context", ""))` → `_self_recognition_cue` key.

**Part C — Chain Definition Update (cognitive_agent.py `_build_chain_for_intent()`):**
- Ward room chain at line 1554: add `self_monitoring` and `introspective_telemetry` to `context_keys`.

**Part D — Prompt Consumption (analyze.py + compose.py):**
- Oracle context: Add `_oracle_context` rendering to thread analysis prompt and compose `_build_user_prompt()`. Key is already in observation from perceive's `_recall_relevant_memories()`.
- Self-monitoring and telemetry: Render structured sections in thread analysis prompt from QUERY results (not raw "Prior Data" dump).
- Self-recognition and cold-start: Consume new baseline keys in thread analysis prompt.

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Async data via QUERY ops, not baseline | Baseline is sync-only by design (AD-646 DD-1). DM self-monitoring and telemetry require async ward_room/service calls |
| DD-2 | Telemetry is conditional on introspective query | Avoids unnecessary service calls + token budget for non-self-referential threads |
| DD-3 | Oracle context already in observation — just consume it | perceive() already calls `_recall_relevant_memories()` which sets `_oracle_context`. Zero new async calls needed |
| DD-4 | Rich attribution overrides simplified baseline | AD-646 baseline does a count-only attribution. When the `_source_attribution` dataclass is present (from perceive), render the full version with primary_source and oracle_used |
| DD-5 | Self-recognition is sync (regex) — belongs in baseline | `_detect_self_in_content()` is a regex scan, no async. Fits baseline's zero-async contract |

**Scope:** ~150 lines across 4 files (query.py, cognitive_agent.py, analyze.py, compose.py). Zero new modules. Zero new infrastructure. Reuses existing methods and services.

### AD-647 — Process-Oriented Cognitive Chains

**Date:** 2026-04-19
**Status:** Scoped
**Issue:** #291
**Parent:** AD-632 (Cognitive Chain Architecture), AD-618 (Bill System)
**Depends on:** AD-618 (Bills/SOPs), AD-595 (Watch Bill / Billet Registry), AD-641g (NATS Pipeline)
**Related:** AD-643a (Intent Routing), BF-209 (Scout chain bypass)

**Decision:** Implement process-oriented cognitive chains as a distinct chain type from the communication chain. Different business processes require different cognitive step sequences — not all agent work is "read thread → analyze → compose reply."

**Motivation:** BF-209 exposed a fundamental category error: the scout's duty-triggered report generation (a structured data pipeline) was forced through the communication chain (QUERY → ANALYZE → COMPOSE). The communication chain bypasses `act()`, so the scout's structured pipeline (parse → enrich → filter → store → notify) never ran. The report was always empty while Ward Room posts appeared.

The scout report is the first case, but the pattern applies to any structured process: incident response, qualification testing, maintenance procedures, data collection. These are **processes** with their own step sequences, not conversations.

**Design direction:**

- Process chains define step types beyond communication: QUERY (data gathering), TRANSFORM (classification/enrichment), STORE (persistence), NOTIFY (routing)
- Each step has its own prompt template or deterministic handler
- AD-618 (Bills/SOPs) provides declarative YAML process definitions
- AD-595 (Billets) provides role-based process assignment
- AD-641g (NATS) enables async step decoupling with process-specific message subjects
- Scout report is the reference implementation

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Communication chain and process chain are distinct types | Communication is interactive (read/analyze/compose). Process is pipeline (gather/transform/store/notify). Forcing one through the other loses structure |
| DD-2 | BF-209 is the interim fix until dependencies land | ScoutAgent opts out of chain for structured duties. Clean, principled, replaceable |
| DD-3 | Bills (AD-618) are the process definition format | YAML declarative procedures with BPMN decision points already designed for multi-step agent processes |

### AD-648 — Post Capability Profiles (Ontology Grounding for Confabulation Prevention)

**Date:** 2026-04-19
**Status:** Design
**Issue:** #292
**Parent:** AD-429 (Vessel Ontology)
**Related:** AD-427 (ACM Core), AD-428 (Skill Framework), AD-496 (Workforce Scheduling), AD-592 (Confabulation Guard), BF-204 (Grounding Checks)

**Decision:** Extend the ship's ontology with structured per-post capability profiles — what each post *actually does*, what tools/processes it uses, and critically what it *does not have*. Inject into prompt context via `_ontology_context` so agents have grounded factual knowledge of their own and each other's capabilities.

**Motivation:** Confabulation audit (2026-04-19) found 628 contaminated Ward Room posts (11.8%), 90+ contaminated episodic memories, 10+ confabulated notebook entries, and 8 agents with contaminated working memory — all from a single false narrative: "the scout has sensors." The scout searches GitHub repos. There are no sensors, no telemetry, no scan coverage metrics. Six agents built an elaborate shared fiction including architecture specs, diagnostic protocols, and fabricated correlations.

Existing confabulation guards (BF-204 hex ID detection, AD-592 "don't fabricate numbers") catch *data confabulation* but not *conceptual confabulation* — agents inventing wrong mental models about what roles do. The ontology tells Wesley he's "Scout in Science department" but never says what the scout *actually does*. Agents fill that gap with plausible inference, and when they infer wrong, the false model self-reinforces through episodic memory contamination.

The same pattern appeared at identical 12% rate across two different crews (pre-reset and post-reset), confirming it's structural, not crew-specific.

**Design:**

Phase 1 — Post capability declarations in `organization.yaml`:

```yaml
posts:
  - id: scout_officer
    title: "Scout"
    department: science
    reports_to: chief_science
    capabilities:
      - id: github_search
        summary: "Search GitHub for trending/relevant repositories"
        tools: [search_github]
        outputs: [scout_report_json]
      - id: scout_report
        summary: "Classify findings as ABSORB/VISITING_OFFICER/SKIP and generate structured report"
        outputs: [scout_report_file, ward_room_notification]
    does_not_have:
      - "sensors or sensory arrays"
      - "telemetry or scan coverage metrics"
      - "detection thresholds or calibration"
      - "environmental scanning or reconnaissance hardware"
```

Phase 2 — Ontology service extension:
- New `PostCapability` dataclass in `models.py`
- `get_crew_context()` includes `capabilities` and `does_not_have` in returned dict
- New `get_post_capabilities(post_id)` method for cross-agent queries ("what does Wesley do?")

Phase 3 — Prompt injection:
- `_build_ontology_context()` renders capability profile into `_ontology_context`
- Format: "Your capabilities: [list]. You do NOT have: [list]."
- Cross-agent capability lookups available in QUERY step for "what does X do?" questions

**OSS/Commercial boundary:** Capability profiles are OSS — they're confabulation prevention infrastructure, not commercial value-add. Commercial ACM (AD-C-010+) and ASA (AD-C-015) build on this foundation:
- ACM reads `capabilities` for consolidated agent profiles, workforce analytics, skill-based compensation
- ASA reads `capabilities` for `ResourceRequirement` matching — schedule agent X because it has capability Y
- Commercial extensions add: dynamic capability discovery, proficiency ratings per capability, utilization tracking per capability, marketplace profile generation

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Capabilities attach to posts, not agent_types | Posts are the unit of organization. Multiple agent_types could fill the same post. Matches Navy billet model — the billet defines the job, not the person filling it |
| DD-2 | Negative grounding (`does_not_have`) is as important as positive | Agents confabulate by filling knowledge gaps. Explicitly closing gaps ("you do not have sensors") prevents the inference chain that creates false narratives |
| DD-3 | All 18 posts get capability profiles, not just scout | The scout was the first failure. Any post without grounded capabilities is vulnerable to the same pattern. Proactive, not reactive |
| DD-4 | Cross-agent capability visibility | Agents must know what *other* agents do, not just themselves. Sage demanded "sensor telemetry" from Wesley because Sage didn't know Wesley searches GitHub. Peer capability awareness prevents collaborative confabulation |
| DD-5 | OSS foundation, commercial overlay | Capability profiles prevent confabulation (OSS concern). ACM/ASA consume them for workforce management (commercial concern). Same data, different consumers |
| DD-6 | `tools` field links to actual tool registry | Each capability references the actual tools/functions used. Grounds the capability in verifiable system reality, not free-form description |

**Scope:** Design + implementation after AD-618, AD-595, AD-641g land. Scout report as first case.

### AD-649 — Communication Context Awareness for Cognitive Chain

**Date:** 2026-04-19
**Status:** Complete
**Issue:** #293
**Related:** AD-639 (Trust-Band Tuning), AD-645 (Composition Briefs), AD-646/646b (Cognitive Baseline/Parity)

**Decision:** Add prescriptive communication context (channel type, audience, register) to the cognitive chain so COMPOSE adapts output format based on where and to whom the agent is communicating. Brings chain output quality toward parity with the one-shot path.

**Motivation:** The chain produces formal, clinical output regardless of context. Two agents (Ezri/Counselor, Nova/Operations) independently diagnosed the same problem when shown their chain vs one-shot responses to the same question. Both identified that COMPOSE defaults to "the most formal register because that feels safer professionally" (Ezri) and produces "crisis management checklist" output instead of operational analysis (Nova). The one-shot path works well because the LLM natively handles audience adaptation — but this is a fragile dependency on emergent model capability. The chain must encode desired behavior prescriptively (LLM Independence Principle).

**Design:**

- Part A: Derive `_communication_context` from existing `channel_name`/`is_dm_channel` — five registers: private_conversation, bridge_briefing, casual_social, ship_wide, department_discussion
- Part B: Add communication context to ANALYZE composition_brief tone guidance — prescriptive register descriptions
- Part C: Add "Speak in your natural voice" to COMPOSE ward_room prompt (parity with one-shot). Register-specific framing per channel type. "Show your reasoning, not just conclusions."

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Five registers derived from channel_name | Maps to existing channel types (ship, department, dm, recreation, custom). No new infrastructure needed |
| DD-2 | Voice parity with one-shot path | Chain ward_room compose was missing "Speak in your natural voice" that one-shot has. Direct gap, direct fix |
| DD-3 | Prescriptive register guidance, not implicit | LLM Independence Principle: chain must produce good output with a less capable model. Encode register expectations explicitly so behavior doesn't depend on emergent model capability |
| DD-4 | "Show reasoning, not just conclusions" | Nova diagnosed that chain strips analytical reasoning. Conclusions without reasoning context are useless for decision-making |
| DD-5 | Department channel is default (no extra constraint) | Natural LLM behavior is correct for peer discussion. Only add constraints for specialized contexts (bridge, recreation, ship-wide) |

**Scope:** ~80 lines across 2 files (cognitive_agent.py, compose.py, analyze.py). 14 tests. Zero new modules.

### AD-650 — Analytical Depth Enhancement

**Date:** 2026-04-19
**Status:** Complete
**Issue:** #294
**Related:** AD-645 (Composition Briefs), AD-646/646b (Cognitive Baseline/Parity), AD-649 (Communication Context)

**Decision:** Enrich the composition brief with a narrative reasoning field and add depth instructions to COMPOSE so the cognitive chain surpasses one-shot output quality on analytical depth — counterarguments, meaning extraction, philosophical nuance.

**Motivation:** AD-649 brought the chain to functional parity on register and tone. But 7 A/B comparison tests revealed the chain consistently underperforms on depth: one-shot produces counterarguments ("fresh eyes" perspective), coined vocabulary ("cognitive load clustering"), and diagnostic insights (using game behavior to read leadership styles). The chain produces broader factual coverage but shallower reasoning. Root cause: the composition brief is an information bottleneck — ANALYZE reasons deeply then compresses to 5 structured fields, losing conditional logic ("because X, therefore Y matters more than Z"). Research grounding: Chain-of-Thought (Wei et al. — intermediate reasoning is load-bearing), DSPy (Stanford — field descriptions are optimization targets), Lost in the Middle (Liu et al. — context positioning matters), Self-Refine (Madaan et al. — can't recover info never passed through bottleneck), OpenMythos/COCONUT (input re-injection prevents representation drift).

**Design:**

- Part A: Add `analytical_reasoning` narrative field to composition_brief in all 3 ANALYZE modes. Reframe brief from "plan for composing" to "analytical reasoning and composition plan." Explicit "narrative prose, not bullets" instruction.
- Part B: COMPOSE renders `## Analytical Reasoning` section. Bold-header suppression for ALL Ward Room branches (was only in private_conversation and DM). Depth instruction ("Don't just summarize — interpret") in all compose modes.

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Narrative reasoning field, not more structured fields | CoT research: conditional logic ("because X, therefore Y") is lost in structured extraction. Narrative preserves the "because" relationships that make reasoning transferable |
| DD-2 | Reframe brief as "analytical reasoning + plan" | Current framing ("plan for composing") tells the LLM to plan, not reason. Framing shapes output |
| DD-3 | Bold-header suppression in ALL Ward Room branches | Testing showed headers regress on multi-point responses in department_discussion, bridge_briefing, etc. Only private_conversation and DM had suppression |
| DD-4 | "Don't just summarize — interpret" as prescriptive depth instruction | One-shot produces depth spontaneously. LLM Independence Principle: make it prescriptive so it works across models |
| DD-5 | Original context still flows to COMPOSE (no change) | Verified: COMPOSE already receives original thread via `context["context"]`. The bottleneck is brief content, not context availability (OpenMythos input re-injection is already in place) |

**Scope:** ~120 lines across 2 files (analyze.py, compose.py). 12 tests. Zero new modules.

### AD-651 — Standing Order Decomposition for Cognitive Chain Steps

**Date:** 2026-04-20
**Status:** Design
**Issue:** #299
**Parent:** AD-632 (Cognitive Chain Architecture)
**Depends on:** AD-647 (Process Chains), AD-641g (NATS Pipeline)
**Related:** AD-646 (Universal Baseline), BF-213 (Analyze Silence Bias)

**Decision:** Decompose monolithic standing orders into step-specific billet instructions for the cognitive chain. Standing orders were designed for the one-shot world — the chain decomposes cognition into steps but injects the same ~2K token document at multiple steps. Each chain step is a billet with its own task-specific instructions, decision space, and operational context.

**Motivation:** BF-213 exposed that standing orders' "When to act vs. observe" decision tree has no effect at the ANALYZE step because the step's own framing ("Silence is professionalism") overrides it. The decision tree is an assessment rubric that belongs in ANALYZE's prompt, not in a general document. The one-shot path never had this problem because assessment and composition happened in the same LLM call — standing orders influenced both simultaneously. The chain splits the cognitive function but doesn't split the instructions to match. AD-647 (Process Chains) already frames steps as billets with their own templates — this AD generalizes that pattern to the communication chain.

**Design:**

- Standing orders split into: identity-level guidance (character, federation/ship values, active directives — stays in standing orders, constitutional preamble at every step) + operational instructions (moves into step prompts as billet instructions)
- ANALYZE gets: decision tree, action vocabulary descriptions, authority scope
- COMPOSE gets: action tag syntax, communication discipline, register guidance
- EVALUATE/REFLECT gets: quality criteria
- Phase 1: extract decision tree into ANALYZE prompt (near-term, standalone)
- Phase 2: billet instruction format in Bill YAML (with AD-647)
- Phase 3: NATS envelope `billet_instructions` field (with AD-641g)

**Key insight:** In one-shot, the model sees everything and makes holistic judgments. In the chain, each step is a specialist. Giving every specialist the entire manual wastes tokens and buries relevant instructions. But over-decomposing risks steps that are too narrowly scoped — identity/values must remain at every step as a constitutional baseline.

**Research:** `docs/research/standing-order-decomposition.md`

### AD-652 — Cognitive Code-Switching: Unified Pipeline with Contextual Modulation

**Date:** 2026-04-20
**Status:** Design Principle (adopted)
**Issue:** #302
**Parent:** AD-632 (Cognitive Chain Architecture)
**Related:** AD-651 (Billet Instructions), AD-639 (Chain Personality Tuning), AD-647 (Process Chains)

**Decision:** The cognitive chain is a single unified pipeline, not parallel pipelines for different communication types. Different cognitive tasks (duty reports vs. casual observations vs. DM responses) are handled through contextual modulation of the same pipeline — variable chain depth, tenor-aware compose framing, and structured format overlays — not by branching into separate architectures.

**Motivation:** The chain pipeline (AD-632) introduced uniform rigidity — the same QUERY → ANALYZE → COMPOSE → EVALUATE → REFLECT sequence runs for duty reports and casual social posts alike. AD-639 identified that this strips personality. AD-651 introduced billet instructions to add structure for operational outputs. The question arose: should ProbOS maintain separate cognitive pipelines for structured vs. creative work?

Cognitive science research (Levelt, Halliday, Giles, Snyder, Weick/Sutcliffe) converges on a clear answer: humans use one language production system with contextual modulation, not parallel systems. Register switching (code-switching) adjusts parameters within a unified pipeline. Military formal protocols are trained overlays on natural language capacity, not separate cognitive systems.

**Design Principles:**

1. **Unified Pipeline** — one chain framework. Identity continuity requires architectural unity. An agent must sound like themselves across duty reports and mess-hall conversation.
2. **Contextual Modulation** — Halliday's field (topic), tenor (formality), and mode (channel) parameters modulate chain behavior: step composition, framing prescriptiveness, format overlays.
3. **Structured Format Overlays** — institutional outputs use billet instructions as cognitive scaffolding (per HRO research). Duty reports, proposals, formal briefings get prescriptive format templates.
4. **Variable Chain Depth** — high-structure tasks get more steps with prescriptive framing. Low-structure tasks get fewer steps with lighter framing. Same pipeline, different configurations.
5. **Character-Driven Self-Monitoring** — code-switching range is a personality parameter (Snyder's Self-Monitoring Theory), not a pipeline decision. Derived from Big Five traits.
6. **Process-Specific Chains** — fundamentally different cognitive tasks can have different step compositions and mode keys. But if two tasks are the same process with different context, they share the chain and modulate parameters.

**Key insight:** The situation selects the register, not a pipeline branch. Like a chat temperature slider from formal to friendly — but the modulation is in prompt context and instructions, not literal LLM temperature. Billet instructions are hard constraints that override for specific output types; tenor is the soft modulation for everything else.

**Research:** `docs/research/cognitive-code-switching-research.md`

### AD-653 — Dynamic Communication Register: Self-Monitored Register Shifting

**Date:** 2026-04-20
**Status:** Design
**Issue:** #303
**Parent:** AD-652 (Unified Pipeline / Contextual Modulation)
**Depends on:** AD-652, AD-504 (Self-Monitoring), AD-651 (Billet Instructions)
**Related:** AD-506 (Self-Regulation), AD-639 (Chain Personality Tuning)

**Decision:** Extend the unified cognitive pipeline (AD-652) with agent-initiated dynamic register shifting. Agents self-monitor their communication register, detect when the assigned register constrains important output, and request a temporary shift ("speak freely" protocol). The shift is trust-gated, temporally scoped, and observable by the Counselor.

**Motivation:** AD-652 established contextual modulation as a top-down mechanism — the system selects register based on context (duty → formal, social → casual). But situations arise where an agent recognizes that the assigned register is flattening something important: a duty report that needs a candid personal assessment, an observation that contradicts the expected structured format, or a finding too nuanced for template framing. In military protocol, "permission to speak freely" solves this — a recognized protocol for situations where protocol itself is the obstacle.

**Prior art survey (confirmed first-of-kind):** No existing multi-agent framework implements self-monitored register shifting. AutoGen/CrewAI/MetaGPT fix communication style at initialization. Reflexion/MARS/MUSE self-assess reasoning quality, never communication register. PromptBreeder evolves prompts across runs but not mid-task. DRESS controls style externally, not agent-initiated. CAMEL enforces role consistency, never escape. Stanford Generative Agents produce emergent style but agents have zero awareness of their own communicative constraints.

**Design:**

Three layers, each buildable independently:

1. **Register Classification Taxonomy** — finite label set (formal_report, professional, collegial, casual, speak_freely) with mapped chain parameters (depth, framing weight, format overlay, personality weight).

2. **Modulation Pattern Templates** — pre-defined configurations mapping (register × process) → chain parameters. Billet instructions (AD-651) are one component; templates bundle billet selection + framing weight + chain depth + personality weight.

3. **Dynamic Register Shift ("Speak Freely")** — ANALYZE detects register-task mismatch → outputs `"speak_freely"` in intended_actions → trust-gated authorization (≥0.7 auto-granted, 0.4-0.7 flagged, <0.4 denied) → COMPOSE receives minimal-constraint framing → shift scoped to single invocation → Counselor receives REGISTER_SHIFT event for pattern tracking.

**Novel contribution:** First implementation of agent self-aware communication register management. Structure AND emergence, not OR — the emergence escape hatch is itself structured, gated by trust, and observable. "Protocol for breaking protocol."

**Research:** `docs/research/dynamic-communication-register-research.md`


### AD-581a — DepartmentDispatcher Routing Decision Layer (backfill 2026-05-08)

**Date:** shipped earlier; backfilled 2026-05-08 after triage discovered DECISIONS.md drift.
**Decision:** Hybrid dispatch routing decision layer at `src/probos/mesh/department_dispatcher.py`. `DepartmentDispatcher.route()` returns a pure `RoutingDecision` (mode/agent_id/confidence/runner_up_weight/reason/department_id) given an intent + candidate pool, using HebbianRouter weight + department membership (VesselOntologyService). No side effects.
**Status:** SHIPPED. Issue [#469](https://github.com/seangalliher/ProbOS/issues/469) closed 2026-05-08. Bit-rot: `HybridDispatchConfig` import broken in `tests/test_ad581_hybrid_dispatch.py` -- tracked in [#504](https://github.com/seangalliher/ProbOS/issues/504).

### AD-581b — Agent Order Protocol (backfill 2026-05-08)

**Date:** shipped earlier; backfilled 2026-05-08.
**Decision:** Order protocol at `src/probos/cognitive/orders.py`. `OrderStatus` enum with `DECLINED` (capacity/scheduling pushback) and `REFUSED` (Standing-Order violation). `OrderEvaluation` dataclass carries `declined_by/declined_at/decline_reason/refused_by/refused_at/refuse_violation`. Evaluation accepts an optional `standing_order_predicate` callable that returns the violation reason, defaulting to no-violation.
**Status:** SHIPPED. Issue [#470](https://github.com/seangalliher/ProbOS/issues/470) closed 2026-05-08.

### AD-581d — Routing Confidence Threshold + Cold-Start Floor (backfill 2026-05-08)

**Date:** shipped earlier; backfilled 2026-05-08.
**Decision:** Confidence threshold + margin, cold-start floor (`min_hebbian_weight`), and per-(intent, agent_id) success-rate ring buffer (`success_rate_window`) implemented in `DepartmentDispatcher` alongside AD-581a. Configured via `HybridDispatchConfig`. Dream-cycle auto-tuning is consumer-hook only (not built in this AD).
**Status:** SHIPPED. Issue [#471](https://github.com/seangalliher/ProbOS/issues/471) closed 2026-05-08.

### AD-594d — Consultation Delivery Pipeline (backfill 2026-05-08)

**Date:** shipped Wave 79; backfilled 2026-05-08.
**Decision:** `DeliveryPipeline` at `src/probos/consultation/delivery.py` with adapters for markdown -> PDF and structured -> reports. Confirmed in `consultation/__init__.py` line 7: `AD-594d (Wave 79): delivery pipeline`.
**Status:** SHIPPED. Issue [#473](https://github.com/seangalliher/ProbOS/issues/473) closed 2026-05-08. Bit-rot: 3 finalize-wirer tests in `test_ad594d_delivery_pipeline.py` failing on `_wire_consultation_delivery` / `ConsultationDeliveryConfig` imports -- tracked in [#505](https://github.com/seangalliher/ProbOS/issues/505).

### AD-699 — Structural Integrity Field (backfill 2026-05-08)

**Date:** shipped earlier; backfilled 2026-05-08.
**Decision:** `StructuralIntegrityField` Ship's Computer service at `src/probos/sif.py` (`SIFCheckResult`, `SIFReport`, `StructuralIntegrityField`). Wired in `runtime.py:641` and constructed by `startup/structural_services.py`. Lightweight invariant checks on the heartbeat cycle -- not an agent, no LLM calls.
**Status:** SHIPPED. Issue [#475](https://github.com/seangalliher/ProbOS/issues/475) closed 2026-05-08. Tests pass: `tests/test_sif.py`.

### AD-594b — Crew Consultation Initiator (`consult()` primitive)

**Date:** 2026-05-08
**Decision:** Add an `async consult(question, *, topic, context, required_expertise, target_agent_id, urgency)` convenience method on `CognitiveAgent` that builds a `ConsultationRequest` from the agent's identity (id, callsign) and routes through the wired `ConsultationProtocol.request_consultation()`. Counterpart to `handle_consultation_request` -- agents now have both halves of the AD-594 protocol surface on a single class.
**Rationale:** AD-594 substrate (`ConsultationProtocol`, request/response dataclasses, expert selection, rate limiting, timeouts) was already shipped, but no convenience initiator existed. Without it agents had to manually construct `ConsultationRequest`, look up the protocol off the runtime, and call `request_consultation` -- enough friction that the primitive went unused. `consult()` removes the friction.
**Scope guards:**
- Returns `None` (with debug log) when no protocol is wired -- never raises.
- Returns `None` (with warning log) on empty question -- never issues an empty request.
- Defaults invalid urgency to `MEDIUM` rather than crashing -- log + soldier on.
- Topic defaults to the question when omitted.
**Status:** SHIPPED. Issue [#472](https://github.com/seangalliher/seangalliher/ProbOS/issues/472). Tests: `tests/test_ad594b_consult_primitive.py` (6 cases, all passing). Existing `tests/test_ad594_consultation_protocol.py` + `tests/test_ad594a_consultation_workspace.py` still green (46/46).

### AD-700 — Multi-Level Diagnostics (L1-L5) for Medical Team

**Date:** 2026-05-08
**Decision:** Formalize diagnostic depth as an LCARS-style `DiagnosticLevel` enum (L5 shallow .. L1 deepest) with three properties: `depth_rank` (1..5, larger = deeper), `llm_tier` (None for L4-L5, `fast` for L2-L3, `deep` for L1), `expected_duration_label`. Add a robust `parse_level()` that accepts `L5`/`"L5"`/`"l5"`/`5`/`"5"` and falls back gracefully to a default. Wire the `level` parameter through `DiagnosticianAgent.perceive()` so:
- L5 skips the VitalsMonitor scan entirely (current value already known via heartbeat).
- L4-L1 invoke the scan and append live metrics to context.
- Every level appends a level-shaped scope hint that tells the LLM what scope of analysis the Captain expects.
- Level / level_rank / level_llm_tier are stamped on the perceive result so downstream consumers (Cognitive Journal, slash command output) can tag and route appropriately.
**Out of scope (deferred):** `/diagnostic <level> <target>` slash command in HXI; explicit Cognitive Journal level tagging; LLM-tier dispatch from the diagnostician's `decide()` (currently the agent uses its instructions; the level hint will guide the model). These are clean follow-ups when needed.
**Status:** SHIPPED. Issue [#476](https://github.com/seangalliher/ProbOS/issues/476).
**Files:** `src/probos/agents/medical/diagnostic_levels.py` (new), `src/probos/agents/medical/diagnostician.py` (perceive extended). Tests: `tests/test_ad700_multi_level_diagnostics.py` (25 cases, all passing).
### AD-490 - EventLog Hash Chain (substrate-tier tamper detection)
**Date:** 2026-05-08  `n**Type:** Architecture Decision (substrate hardening)  `n**Wave:** 129

Extends the AD-456 AuditLog hash-chain pattern to the substrate `EventLog`. Adds two SHA-256 columns (`prev_hash`, `row_hash`) to the `events` table via additive `_migrate_ad490()`; `log()` reads the prior row's `row_hash` and chains to it (genesis = `'0' * 64`); new `verify_chain() -> tuple[bool, int | None]` walker returns `(True, None)` if intact or `(False, broken_at_id)` on first mismatch. Determinism contract: `json.dumps(..., sort_keys=True, default=str)` so identical payloads with different dict insertion order rehash equal.

**In scope:** SQLite-side hash chain, on-disk migration, single new public method.
**Out of scope:** in-memory chain, federation export, alerting on chain breaks, config gating (always-on in v1).
**Status:** SHIPPED. Issue [#506](https://github.com/seangalliher/ProbOS/issues/506).
**Files:** `src/probos/substrate/event_log.py` (additive). Tests: `tests/test_ad490_eventlog_hash_chain.py` (8 cases, all passing).


### AD-491 - gitagent Interop Adapter (publish/install boundary only)
**Date:** 2026-05-08  `n**Type:** Architecture Decision (interop boundary)  `n**Wave:** 129

Greenfield `src/probos/interop/` package with `gitagent.py` exposing two pure boundary functions:
- `export_agent_to_gitagent_yaml(agent) -> str` renders a ProbOS agent in gitagent YAML with a `probos` sub-section preserving `sovereign_id` / `did` / `pool`.
- `import_gitagent_yaml(path) -> dict` parses gitagent YAML; if `runtime != 'probos'` it forces `probos.sovereign_id` and `probos.did` to `''` so foreign runtimes cannot assert ProbOS sovereign identity. Required keys: `name`, `runtime` (else ValueError).

**In scope:** publish/install boundary only; no runtime wiring, no agent instantiation, no AgentIdentityRegistry writes.
**Out of scope:** `/install` slash command, federation publishing, per-agent versioning, foreign-runtime sovereign trust.
**Status:** SHIPPED. Issue [#491](https://github.com/seangalliher/ProbOS/issues/491).
**Files:** `src/probos/interop/__init__.py` (new), `src/probos/interop/gitagent.py` (new). Tests: `tests/test_ad491_gitagent_interop.py` (8 cases, all passing).


### AD-700b - CognitiveJournal Level Tagging for `diagnose_system`
**Date:** 2026-05-08  `n**Type:** Architecture Decision (telemetry / single-field addition)  `n**Wave:** 129

Adds two columns (`level TEXT`, `level_rank INTEGER`) and one index (`idx_journal_level`) to the CognitiveJournal `journal` table. Migration `_migrate_ad700b()` runs after the AD-432/AD-492 ALTER block and before `_SCHEMA_INDEXES`. `record()` accepts new `level: str = ''` / `level_rank: int = 0` kwargs. The single populating call site is `cognitive_agent._decide_via_llm` at `cognitive_agent.py:1722-1748`, gated on `observation.get('intent') == 'diagnose_system'`; non-diagnostic rows persist empty/zero defaults so journal readability is preserved.

**In scope:** schema migration, `record()` signature, single populating call site.
**Out of scope:** query API for level-filtering, free-form metadata, Diagnostician changes (already populates `level`/`level_rank` in `perceive()`).
**Status:** SHIPPED. Issue [#508](https://github.com/seangalliher/ProbOS/issues/508).
**Files:** `src/probos/cognitive/journal.py` (schema + migration + record), `src/probos/cognitive/cognitive_agent.py` (one block at `:1722-1748`). Tests: `tests/test_ad700b_journal_level_tag.py` (6 cases, all passing).


### AD-700c - Diagnostician Per-Call LLM Tier Override
**Date:** 2026-05-08  `n**Type:** Architecture Decision (cognitive routing - narrow)  `n**Wave:** 129

Adds `CognitiveAgent._resolve_tier_for_observation(observation)` honoring an `observation['level_llm_tier']` override string. Wires it into `_decide_via_llm` at the `LLMRequest` construction (replaces the static `self._resolve_tier()` call). Adds a short-circuit guard: when the resolved tier is `''` (explicit `None`) AND `intent == 'diagnose_system'`, `_decide_via_llm` returns a deterministic decision dict (`tier_used='none'`, plus `level`, `level_rank`, `short_circuit_reason`) without invoking the LLM. L4/L5 diagnostic levels burn no LLM tokens. Non-diagnostic intents fall to the static `_resolve_tier()` (defensive scoping).

**In scope:** new helper, two-line change at the `LLMRequest` site, short-circuit guard.
**Out of scope:** `_resolve_tier()` itself (preserved as static fallback), DiagnosticianAgent `perceive()` (already populates `level_llm_tier`), LLM client tier registry, journal short-circuit row write (no `response` -> no journal write, by design).
**Status:** SHIPPED. Issue [#509](https://github.com/seangalliher/ProbOS/issues/509).
**Files:** `src/probos/cognitive/cognitive_agent.py` (helper + short-circuit + tier rewire). Tests: `tests/test_ad700c_diagnostician_tier_routing.py` (10 cases, all passing).


### AD-700a - `/diagnostic` Slash Command for Multi-Level Diagnostics
**Date:** 2026-05-08  `n**Type:** Architecture Decision (HXI surface for AD-700)  `n**Wave:** 129

Adds a new HXI shell slash command `/diagnostic [<level>] [<focus>]` for the Captain to invoke AD-700 multi-level diagnostics directly. Implementation:
- New module `src/probos/experience/commands/commands_diagnostic.py` with `cmd_diagnostic()` async handler. Parses the level token via the canonical module-level `parse_level()` from `probos.agents.medical.diagnostic_levels` (graceful L3 fallback). Issues a `diagnose_system` intent through the canonical Captain dispatch path: pool lookup (`medical_diagnostician`) -> `pool.healthy_agents[0]` -> `agent.handle_intent(IntentMessage(...))` -- no `intent_bus` indirection.
- New panel renderer `render_diagnostic_result(result, *, level)` in `experience/panels.py`: severity-tinted Rich Panel with header showing level name, depth_rank/5, and `expected_duration_label`; structured fields rendered in a Table with `--` placeholders for missing keys.
- `shell.py` wired: import added, `COMMANDS` registry entry, `_dispatch_slash` handler.
- `test_layer_boundaries.py` updated: added `commands_diagnostic.py -> agents.medical.diagnostic_levels` to `ALLOWED_EXCEPTIONS` (precedented by `experience/qa_panel.py -> probos.agents.system_qa`); pure enum + parse helper, no behavioral coupling.

**In scope:** slash command, command module, panel renderer, layer-boundary exception.
**Out of scope:** DiagnosticianAgent changes, `parse_level`/`DiagnosticLevel` changes, new EventType, HXI React UI surface.
**Status:** SHIPPED. Issue [#507](https://github.com/seangalliher/seangalliher/ProbOS/issues/507).
**Files:** `src/probos/experience/commands/commands_diagnostic.py` (new), `src/probos/experience/panels.py` (additive renderer), `src/probos/experience/shell.py` (3 hooks), `tests/test_layer_boundaries.py` (one ALLOWED_EXCEPTIONS entry). Tests: `tests/test_ad700a_diagnostic_slash_command.py` (9 cases, all passing).


### AD-711 — claude-bootstrap-derived `probos init` security defaults
**Date:** 2026-05-08
**Type:** Architecture Decision (experience — init wizard hardening)
**Wave:** 130

Lifts the `claude-bootstrap` (alinaqi/claude-bootstrap, MIT, 607★) `settings.json` permission deny-list pattern into `probos init`, generating a secure-by-default `security:` block with declarative `allow`/`deny` entries. Weakening defaults is opt-in only via `--security-profile relaxed`; the wizard never prompts interactively to weaken. `probos doctor` now flags missing/empty security sections as failures and warns on relaxed profile.

**Implementation:**
- `src/probos/config.py`: new `PermissionsConfig` model; existing `SecurityConfig` (AD-455) extended additively with `profile: Literal["strict","relaxed"] = "strict"` and `permissions: PermissionsConfig`.
- `src/probos/__main__.py`: `_cmd_init` resolves `args.security_profile` (default "strict"; invalid → "strict") and appends a strict-or-relaxed YAML block to the generated `config.yaml`. New `--security-profile` argparse flag with `choices=("strict","relaxed")`. `_cmd_doctor` adds Check 6 (security section sanity).

**In scope:** declarative security block + flag + doctor check.
**Out of scope:** runtime enforcement of `permissions.deny` (forward marker AD-711-1); `config.local.yaml` overlay; `init --upgrade-security` migration.

**AD-numbering note:** prompt cited AD-709, but `docs/development/roadmap.md` already reserves AD-709 for MemoryForge (#485). Builder reassigned to AD-711 (next free above the wave-129 ceiling) and shifted the runtime-enforcement forward marker AD-712 to AD-711-1 to avoid colliding with Memvid-QP (which now takes AD-712).

**Status:** SHIPPED. Issue [#495](https://github.com/seangalliher/ProbOS/issues/495).
**Files:** `src/probos/config.py` (additive), `src/probos/__main__.py` (init + doctor + argparse). Tests: `tests/test_claude_bootstrap_init_defaults.py` (11 cases, all passing).
### AD-701 — Visiting Officer registry (formal external-participant Ward Room registration)
**Date:** 2026-05-08
**Type:** Architecture Decision (substrate — external participant registration)
**Wave:** 130

Adds a `VisitingOfficerRegistry` that mints time-bounded, capability-scoped sovereign DIDs for external AI tools (Claude Code, Copilot, etc.) under `agent_type="visiting"`. The registry is the enforcement seam: `WardRoomService` stays generic, and any consumer that wants to honor a visiting-officer post calls `has_capability(did, "ward_room.post")` first. AD-449 owns transport; AD-701 owns identity + scope.

**Implementation:**
- `src/probos/visiting_officers.py` (new): `VisitingOfficerSession` frozen dataclass + `VisitingOfficerRegistry` with public API `register / deregister / get / has_capability / active / start / stop`. In-memory storage; async sweep loop deregisters expired sessions every 60s and emits `VISITING_OFFICER_DEREGISTERED` with reason="expired".
- `src/probos/config.py`: new `VisitingOfficersConfig` (default `enabled=False` per convention #14, `session_ttl_seconds=3600`, `sweep_interval_seconds=60`, default capabilities `["ward_room.post", "ward_room.read"]`).
- `src/probos/startup/finalize.py`: wires registry after MCPBridge (AD-449); sources instance/vessel/version from `runtime.ontology.get_vessel_identity()` (corrected — runtime does not expose these directly).
- `src/probos/startup/shutdown.py`: symmetric `stop()` before identity registry shutdown.

**In scope:** registry + DID issuance + capability scoping + session expiry + sweep loop.
**Out of scope:** SQLite persistence (AD-701b), HXI sidebar surface (AD-701c), inbound MCP transport that auto-registers (AD-701d).

**Verify-first correction:** prompt cited `runtime.instance_id / vessel_name / baseline_version` in D3 wiring; these attributes do not exist on `ProbOSRuntime`. Builder sourced from `runtime.ontology.get_vessel_identity()` (returns `VesselIdentity(name, version, instance_id)`), falling back to `config.system.version` if ontology is unavailable.

**Status:** SHIPPED. Issue [#477](https://github.com/seangalliher/ProbOS/issues/477).
**Files:** `src/probos/visiting_officers.py` (new), `src/probos/config.py` (additive), `src/probos/startup/finalize.py` (wiring), `src/probos/startup/shutdown.py` (symmetric stop). Tests: `tests/test_ad701_visiting_officers.py` (11 cases, all passing).

### AD-707 — Workflow Cron Trigger (cron-only)
**Date:** 2026-05-08
**Type:** Architecture Decision (cognitive — workflow scheduling)
**Wave:** 130

Adds a `WorkflowCronScheduler` that re-fires cached workflows on cron schedules. Replays through `runtime.process_natural_language`, preserving the WorkflowCache fast-path (AD-580). SQLite-persistent so triggers survive restart; first cron eval uses `created_at` as the base so freshly-registered triggers do not fire instantly.

**Implementation:**
- `src/probos/cognitive/workflow_cron.py` (new): `WorkflowCronTrigger` dataclass + `WorkflowCronScheduler` with public API `start / stop / register / cancel / list_triggers`. Cron validation via `croniter.is_valid`; failed replays logged-and-degraded without bumping `fire_count`.
- `src/probos/config.py`: new `WorkflowCronTriggerConfig` (default `enabled=False`, `db_path=""` in-memory, `tick_interval_seconds=1.0`, `initial_triggers=[]`); placed at top-level `SystemConfig` adjacent to `visiting_officers`.
- `src/probos/startup/finalize.py`: wires after AD-701; isinstance-gated against the real config class so MagicMock-using tests do not trigger the wiring.
- `src/probos/startup/shutdown.py`: symmetric `stop()` before identity registry shutdown.

**In scope:** cron trigger only.
**Out of scope:** webhook firing (AD-707b), REST/CLI trigger CRUD (AD-707c), per-workflow concurrency cap (AD-707d).

**MagicMock contamination fix:** initial `if cfg is not None and cfg.enabled` checks matched MagicMock-spec'd test configs, starting background sweep/tick loops with MagicMock intervals. Replaced with `isinstance(cfg, RealConfigClass) and cfg.enabled` — same pattern applied retroactively to AD-701 visiting-officer wiring.

**Status:** SHIPPED. Issue [#483](https://github.com/seangalliher/ProbOS/issues/483).
**Files:** `src/probos/cognitive/workflow_cron.py` (new), `src/probos/config.py` (additive), `src/probos/startup/finalize.py` (wiring), `src/probos/startup/shutdown.py` (symmetric stop). Tests: `tests/test_ad707_workflow_cron_trigger.py` (11 cases, all passing).


### AD-712 — Memvid pattern 1: QueryPlanner relational lookup
**Date:** 2026-05-08
**Type:** Architecture Decision (cognitive — recall pipeline routing)
**Wave:** 130

Adds a deterministic regex-driven query classifier (`QueryPlanner`) that detects relational queries (`who works at X`, `where is Y`, `when did Z happen`) and routes them through `EpisodicMemory.recall_by_anchor` before falling back to vector similarity. Absorbs Memvid pattern 1 from Olow304/memvid; patterns 2 (`VersionRelation` enum) and 3 (per-engine-version anchoring) remain explicit follow-ups.

**Implementation:**
- `src/probos/cognitive/query_planner.py` (new): `QueryPlan` frozen dataclass + `QueryPlanner.classify()` (sub-millisecond regex; no LLM) + `QueryPlanner.recall_with_fallback(episodic, query, k)` async helper that runs the structured lookup, falls back on empty result OR exception (logged at warning level), and never raises on classification.
- `src/probos/config.py`: new `QueryPlannerConfig` (default `enabled=False`, `fall_through_on_empty=True`); wired on top-level `SystemConfig`.
- `src/probos/startup/finalize.py`: wires `runtime.query_planner` after AD-707 cron scheduler; isinstance-gated.

**In scope:** classifier + routing helper + runtime exposure.
**Out of scope:** `VersionRelation` enum (memvid-versionrelation-v1), per-engine-version enrichment (memvid-engineversion-v1), `EpisodicMemoryProtocol` widening, setter-injection on `EpisodicMemory.__init__` (memvid-qp-injection-v1 if benchmarks justify).

**AD-numbering note:** prompt did not cite an AD number. Builder grepped `PROGRESS.md` / `DECISIONS.md` / `roadmap.md` and assigned AD-712 (next free above the post-AD-711 ceiling; AD-711-1 is reserved as the runtime-enforcement forward marker for AD-711 claude-bootstrap).

**Status:** SHIPPED. Issue [#490](https://github.com/seangalliher/ProbOS/issues/490).
**Files:** `src/probos/cognitive/query_planner.py` (new), `src/probos/config.py` (additive), `src/probos/startup/finalize.py` (wiring). Tests: `tests/test_memvid_queryplanner_relational.py` (13 cases, all passing).


### AD-702 — Diplomatic Relations (discounted trust transitivity)
**Date:** 2026-05-08
**Type:** Architecture Decision (consensus — trust extension)
**Wave:** 130

Adds discounted transitive trust composition `T(A→C) = T(A→B) × T(B→C) × δ` to `TrustNetwork`, implementing Nooplex paper §4.3.4. Three hard rules enforced: (1) safety-critical operations override — destructive intents never use transitive trust; (2) 90-day linear decay toward the network neutral baseline (Beta(2,2) mean = 0.5) after the target's last event; (3) per-hop discount factor δ=0.85 provides Sybil resistance — longer chains decay multiplicatively.

**Implementation:**
- `src/probos/consensus/trust.py`: 4 new module constants + 5 new methods on `TrustNetwork`. `_best_bridge(observer, target, discount)` is the R4-extracted helper that returns `(composed, via)` for the strongest single-hop intermediary; both `transitive_score` and `chain_path` delegate to it (no v1 duplication). `_apply_decay` walks the bounded `_event_log` to find the target's last event and linearly interpolates toward `TRANSITIVE_NEUTRAL` after the 90-day window. `set_intent_descriptor_lookup` injection setter mirrors `set_department_lookup` — wired by the runtime once intent registry is built (deferred to AD-702b's quorum-path integration).
- `src/probos/protocols.py`: `TrustNetworkProtocol` widened with `transitive_score` and `chain_path`. 0 mock sites in `tests/` confirmed pre-build, so widening is safe per the >5-mocks STOP rule.

**R4 decision (Recommended option (a)):** `_best_bridge` extracted as the prompt's revision notes claimed. Cleaner DRY; matches the L307 attestation. Option (b) (accept duplication) was not taken.

**In scope:** read-only transitive_score + chain_path + decay + safety override.
**Out of scope:** consumer wiring to consensus quorum path (AD-702b — gates only non-destructive intents and runs full BFS up to max_hops=4); per-pair asymmetric edges (AD-702c).

**Verify-first corrections:**
- `TrustRecord.observations` is a derived property, not a constructor field. Test helper rebuilt to compute alpha/beta so observations = 10 from prior subtraction.
- `TrustEvent` schema is `(timestamp, agent_id, success, old_score, new_score, weight, intent_type, episode_id, verifier_id)`, not the prompt's draft `(event_type, data)`. Test helper updated.
- Pre-existing gap: `TrustNetworkProtocol.get_trust_score` declared but `TrustNetwork` does not implement it. Test asserts new method existence via `callable(getattr(...))` rather than `isinstance(Protocol)` to avoid coupling to the unrelated gap.

**Status:** SHIPPED. Issue [#478](https://github.com/seangalliher/ProbOS/issues/478).
**Files:** `src/probos/consensus/trust.py` (4 constants + 5 new methods, additive), `src/probos/protocols.py` (Protocol widening). Tests: `tests/test_ad702_diplomatic_relations.py` (16 cases, all passing).


### AD-713 — Behavior Contract integration (better-agents pattern)
**Date:** 2026-05-08
**Type:** Architecture Decision (cognitive — declarative qualification)
**Wave:** 130

Absorbs the YAML-declared "must / must-not" behavior contract pattern from langwatch/better-agents (MIT, 1.5k★) without absorbing their TypeScript CLI, LangWatch SDK, or scenario notebook substrate. Provides a declarative entrypoint to the AD-477 / AD-566a qualification subsystem: users author YAML contracts; `probos qa run-contracts <path>` evaluates each and returns a TestResult-shaped result.

**Implementation:**
- `src/probos/cognitive/behavior_contract.py` (new): Pydantic models `_MustRule` (substring | substring_any | regex; model_validator forbids empty/multi-field), `ContractCase`, `BehaviorContract`. `load_contract(path)` YAML loader + validator chain. `evaluate_contract(contract, invoker)` async — runs every case, never raises on invoker exception, returns AD-566a TestResult-shaped dict with `last_error` semantics.
- `src/probos/__main__.py`: new `_cmd_qa_run_contracts(args) -> int` handler (rc=0 pass / rc=1 fail / rc=2 path-missing) + `qa` parent subparser + `run-contracts` child + dispatch. Stub invoker returns empty strings — honest fail signal until AD-713-1 wires the hot-runtime invoker.
- `config/contracts/sample_refusal.yaml`: example contract demonstrating refusal regex.

**In scope:** YAML contract format, declarative loader/evaluator, CLI subcommand, sample contract.
**Out of scope:** hot-runtime invoker (AD-713-1), multi-turn scenario simulator (AD-713-2), drift detection against historical baselines (AD-713-3), separate persistence table (results land in existing `QualificationStore`).

**AD-numbering note:** prompt did not cite an AD number. Builder assigned AD-713 (next free above AD-712 Memvid).

**Status:** SHIPPED. Issue [#493](https://github.com/seangalliher/ProbOS/issues/493).
**Files:** `src/probos/cognitive/behavior_contract.py` (new), `src/probos/__main__.py` (handler + subparser + dispatch), `config/contracts/sample_refusal.yaml` (new). Tests: `tests/test_better_agents_behavior_contract.py` (14 cases, all passing).


### AD-714 — RAGFlow context-layer absorption study (research)
**Date:** 2026-05-08
**Type:** Research AD (no production code)
**Wave:** 130

Compares `infiniflow/ragflow` (Apache-2.0, ~80k★) against ProbOS's existing recall + working-memory + situation-awareness stack. Identifies four absorbable patterns (DeepDoc parsing, template-based chunking, fused re-ranking, grounded citations); rejects the heavyweight ES/MySQL/MinIO/Redis storage stack and the OpenClaw skill integration. Builder picked **option (a)** for the concrete artifact: a coverage-claim grep test that asserts every "ProbOS already covers X" citation in section 3 of the absorption doc resolves to an existing file with the cited line in-bounds. Documentation-integrity guard.

**Files:** `docs/research/ragflow-absorption.md` (new), `tests/research/__init__.py` (new), `tests/research/test_ragflow_coverage_claims.py` (5 tests, all passing).

**Forward markers:** AD-714-1 (document ingestion adapter), AD-714-2 (template-based chunking), AD-714-3 (grounded LLM citations), AD-714-4 (tri-recall lexical+relational+semantic comparison).

**Status:** SHIPPED. Issue [#496](https://github.com/seangalliher/ProbOS/issues/496).


### AD-715 — OpenCode magic-context absorption study (research)
**Date:** 2026-05-08
**Type:** Research AD (no production code; opt-in measurement harness only)
**Wave:** 130

Compares `cortexkit/magic-context` (MIT, 542★) — an OpenCode plugin handling agent context via `§N§` tagging, queued reductions, caveman age-tiered compression, and a historian/dreamer split — against ProbOS's working memory + Ebbinghaus + dream consolidation stack. Identifies four absorbable patterns (caveman compression, tagging-based addressable context, queued reduction triggers, cache-aware LLM client); rejects the OpenCode plugin layer and the 17-table SQLite proliferation.

**Concrete artifact:** `tests/research/test_compression_ratio_harness.py` — opt-in via `PROBOS_RESEARCH_BENCH=1`. Ingests a 9-turn fixture and reports ratio. Baseline measurement: original=1311 chars, compressed=348 chars, ratio=0.265 via `recall(k=1)` proxy. Harness is the directional baseline future absorption ADs (AD-715-1, AD-715-2, AD-715-3) will quote when justifying caveman implementation effort.

**Verify-first correction:** `EpisodicMemory.__init__` kwarg is `db_path`, not `persist_directory`. Harness uses the verified shape.

**Files:** `docs/research/opencode-magic-context-absorption.md` (new), `tests/research/data/sample_session.json` (new), `tests/research/test_compression_ratio_harness.py` (new). Tests: 1 skipped-by-default; passes under opt-in env var.

**Forward markers:** AD-715-1 (caveman compression), AD-715-2 (tagging-based addressable context), AD-715-3 (cache-aware LLM client wrapper).

**Status:** SHIPPED. Issue [#492](https://github.com/seangalliher/ProbOS/issues/492).


### AD-716 — LoCoMo benchmark absorption + harness stub (research)
**Date:** 2026-05-08
**Type:** Research AD (no production code; opt-in benchmark stub)
**Wave:** 130

Captures the LoCoMo (Long Conversation Memory) methodology — the de-facto open benchmark Mem0 and MemOS both quote — and ships a runnable micro-harness so ProbOS has its own directional baseline. v1 uses a hand-authored 3-session × 5-question fixture, exact-substring scoring, and the simplest recall surface (`EpisodicMemory.recall`); the prompt's `recall_weighted` skeleton was rejected because the live signature requires an `agent_id` positional the micro benchmark has no scaffolding to supply.

**Concrete artifact:** `tests/benchmarks/test_locomo_episodic.py` (opt-in via `PROBOS_BENCHMARK_LOCOMO=1`). Includes fixture self-consistency pre-check (every `expected_substring` must appear in its named session). Harness prints a single JSON line: `{"benchmark":"micro_locomo_v1","method":"recall","correct":N,"total":5,"ratio":R,...}`.

**Files:** `docs/research/locomo-benchmark-absorption.md` (new), `tests/benchmarks/__init__.py` (new), `tests/benchmarks/data/micro_locomo.json` (new), `tests/benchmarks/test_locomo_episodic.py` (new). Tests: 1 skipped-by-default; passes under opt-in env var.

**Forward markers:** AD-716-1 (real LoCoMo dataset), AD-716-2 (LLM-judge fuzzy scoring), AD-716-3 (per-metric breakdown across all three recall surfaces — `recall` / `recall_by_anchor` / `recall_weighted`).

**Status:** SHIPPED. Issue [#497](https://github.com/seangalliher/ProbOS/issues/497) (subsumes [#494](https://github.com/seangalliher/ProbOS/issues/494)).


### AD-717 — Warm-Boot State Fragmentation (DESIGN, implementation deferred)
**Date:** 2026-05-08
**Type:** Pure design AD — no production code
**Wave:** 130

Design pinned in `docs/research/warm-boot-fragmentation-design.md`. Four detection heuristics (anchor-temporal mismatch, missing dream-cycle markers, stale trust deltas, hash-chain cross-drift), triage rules (safe-discard vs. recovery), `MIN_BOOT_STASIS_SECONDS=2.0` / `MAX_BOOT_STASIS_SECONDS=30.0`, optional dream-checkpoint-resume with SHA-256 self-hash. Four named events for the implementation AD: `WARM_BOOT_FRAGMENT_DETECTED`, `WARM_BOOT_FRAGMENT_RECOVERED`, `WARM_BOOT_FRAGMENT_QUARANTINED`, `WARM_BOOT_STASIS_EXCEEDED`. Convention #14 carve-out: `warm_boot.enabled=true` is the only `enabled: true` default in Wave 130, justified as a safety mechanism (a fragmentation scan that's off-by-default silently misses what it exists to catch).

**AD-numbering note:** highest pre-warm-boot AD = AD-716 (LoCoMo). Warm-boot assigned AD-717. Implementation deferred to **AD-717-1**; checkpoint format/resume = AD-717-2; HXI/CLI surface = AD-717-3.

**Status:** SHIPPED (DESIGN ONLY — no code shipped). Issue [#501](https://github.com/seangalliher/ProbOS/issues/501).
**Files:** `docs/research/warm-boot-fragmentation-design.md` (new design doc).


### AD-706 — Browser Tool (Computer Use via Playwright, default-disabled)
**Date:** 2026-05-08
**Type:** Architecture Decision (crew capability — agent-driven web browser)
**Wave:** 132

Ships ``BrowserTool`` (the AD-423a Tool Layer implementation), ``BrowserSession`` (one Playwright BrowserContext per session, 30-min TTL, no cookie persistence across sessions), and a 10-action vocabulary absorbed from browser-use (``goto``, ``state``, ``click``, ``type``, ``scroll``, ``screenshot``, ``wait``, ``back``, ``forward``, ``extract_text``). The ``state()`` action returns a stable indexed-element list so agents can say ``click 5`` instead of synthesising selectors. Screenshots are XGA-scaled (1024x768) per Anthropic's computer-use-demo (MIT) guidance. Per-domain rate limiting mirrors AD-270's pattern, scoped to the BrowserSession class rather than shared with HttpFetchAgent (different cadence; Playwright doesn't surface ``Retry-After`` uniformly).

A rule-based three-tier classifier ships in this AD: tier-1 (silent) for observational actions, tier-2 (logged-and-proceed) for ordinary navigate/click/type, tier-3 (Captain ACK required) for clicks/types against financial host patterns (``*bank*``, ``*paypal*``, ``*stripe*``, ``*chase*``, ``*coinbase*``, ``*checkout*``), checkout/payment/transfer/subscribe/signup/register paths, or elements whose text matches the cookie/T&S/payment regex. Tier-3 short-circuits ``invoke()`` and emits ``EventType.TOOL_INTERVENTION_REQUIRED`` with a ``confirmation_token`` (UUID4 hex) that surfaces in the event payload only — never in ``ToolResult.output`` — so agents cannot autonomously satisfy the gate. Tokens are single-use (``_pending_confirmations.pop``), session/action-bound, expire after ``confirmation_timeout_seconds`` (default 300s), and are opportunistically pruned by the session reaper.

Audit rows enforce a strict 7-key allowlist (``session_id``, ``action``, ``agent_id``, ``success``, ``error?``, ``tier``, ``url_sanitized?``); ``params.text``, raw ``params.url``, POST bodies, cookies, and state-element text are explicitly forbidden in ``detail``. ``url_sanitized`` strips query and fragment to avoid leaking tokens. AD-448 already emits ``TOOL_INVOKED`` via the tool executor — no duplicate emission. Three new browser-specific events: ``BROWSER_ACTION_EXECUTED``, ``BROWSER_SESSION_OPENED``, ``BROWSER_SESSION_CLOSED``.

Default-disabled per Wave 10 convention #14: ``BrowserToolConfig.enabled=False``. ``playwright`` is a new optional dependency under ``[browser]`` — default install is unaffected. Lazy ``from playwright.async_api import async_playwright`` lives inside ``BrowserSession.start()`` (and the wirer's import-probe), so missing optional dep at import time cannot crash startup. ``_wire_browser_tool`` registers the tool with rank-graded permissions (``ensign=none``, ``lieutenant=read``, ``commander=write``, ``senior_officer=full``) and is invoked from finalize.py immediately after ``_wire_mcp_app_host``. ``BrowserSession.get_streaming_url() -> None`` is a v1 stub; the Captain-watch CDP/WebSocket bridge is deferred to AD-706a.

Verify-first noted: the dispatch's references to ``McpAppFrame``, ``AD-451 SafetyClassifier``, and ``AD-561 Intervention Classification`` do not match HEAD names; this AD ships a self-contained rule-based classifier that a future LLM-driven AD-706d can replace without protocol changes. Forward markers: AD-706a (Captain-watch streaming), AD-706b (video recording), AD-706c (OmniParser-style vision extraction — architecture-only, AGPL on icon_detect blocks weight absorption), AD-706d (LLM-driven tier classifier), AD-706e (action vocab v2: drag/key_combo/upload/download/eval_js), AD-706f (credential vault).

**AD-numbering note:** AD-706 was previously allocated against issue #482 in the roadmap but had no live DECISIONS entry — confirmed via grep before authoring. Wave 131 shipped to AD-717. AD-706 fills the reserved slot.

**Status:** SHIPPED. Issue [#482](https://github.com/seangalliher/ProbOS/issues/482).
**Files:** `src/probos/tools/browser/__init__.py` (new), `src/probos/tools/browser/tool.py` (new), `src/probos/tools/browser/session.py` (new), `src/probos/tools/browser/actions.py` (new), `src/probos/config.py` (BrowserToolConfig + SystemConfig field), `src/probos/events.py` (4 new EventType values), `src/probos/startup/finalize.py` (`_wire_browser_tool` + call site after `_wire_mcp_app_host`), `pyproject.toml` (`[browser]` optional dep), `tests/test_ad706_browser_tool.py` (new — 23 tests; one gated on `PROBOS_PLAYWRIGHT_REAL=1`).


### AD-718 — Voice in 1:1 profile chat (browser SpeechSynthesis substrate, per-agent VoiceProfile)
**Date:** 2026-05-08
**Type:** Architecture Decision (HXI parity ΓÇö voice in profile chat)
**Wave:** 133

Brings `ProfileChatTab.tsx` to parity with the Ship's Computer chat (`IntentSurface.tsx`): mic-button STT input via the existing `ui/src/audio/speechInput.ts` substrate, plus TTS playback of agent replies through `speakResponse` when the global `voiceEnabled` flag is on. Each crew member can speak with a distinct voice via a new `VoiceProfile` dataclass on `CrewProfile` (`voice_name`, `pitch`, `rate`, `volume`); v1 stays on the browser-native `SpeechSynthesis` API ΓÇö no Coqui / ElevenLabs / Bark backends.

`speakResponse` now accepts an optional `VoiceProfile` override and an optional `agent_id`; existing call sites stay source-compatible (`speakResponse(text)` retains the v0 0.95/0.9/0.8 utterance defaults). A new `onSpeechEvent` registry emits `start`/`end` events keyed on `agent_id` ΓÇö the contract AD-721's `CrewAvatarPopout` will subscribe to for mouth-blendshape animation. The previously-inlined markdown-strip pipeline in `IntentSurface.tsx` is extracted to `stripMarkdownForSpeech` and shared with `ProfileChatTab`; behaviour is byte-for-byte preserved.

`VoiceProfile.__post_init__` enforces ranges (pitch 0ΓÇô2, rate 0.1ΓÇô10, volume 0ΓÇô1) and the dataclass round-trips through `CrewProfile.to_dict`/`from_dict`. `voice_profile_defaults.py` ships seeded defaults for the 15 standing-crew agent_types (Counselor warmer/slower, Worf deeper/firmer, Wesley younger, etc.) keyed on the YAML stem; `default_voice_for(agent_type)` returns the bare `VoiceProfile()` for unknown types. `GET /api/agent/{id}/profile` now returns `voiceProfile` always-present (live `ProfileStore` β†’ seed YAML `voice` β†’ `default_voice_for` fallback chain ΓÇö never `None`); new `PUT /api/agent/{id}/voice-profile` persists overrides through `ProfileStore.get_or_create`/`update` and emits 400 on out-of-range values via the dataclass validator.

The `ProfileInfoTab` voice picker exposes voice-name dropdown (from `getAvailableVoices()`), pitch and rate sliders, and a "Test" button that calls `speakResponse('This is how I sound.', currentProfile, agent.id)` ΓÇö volume is intentionally NOT surfaced (per-agent volume conflicts with overall HXI volume; deferred to AD-718f). Mic JSX in `ProfileChatTab` mirrors `IntentSurface` (same SVG glyph, same listening-color treatment, same `pulse-mic` keyframe copied inline so the listening pulse doesn't silently no-op). System-error placeholders that start with `(` skip TTS playback.

Default-Off: piggybacks on the existing `voiceEnabled: false` initial in `useStore.ts` ΓÇö no new config flag, no convention #14 violation.

Verify-first: dispatch contradictions reconciled in the prompt body ΓÇö `src/probos/profile_store.py` does not exist (actual: `crew_profile.py` with `CrewProfile` dataclass + `ProfileStore` SQLite layer); `ui/src/voice/speechInput.ts` does not exist (actual: `ui/src/audio/speechInput.ts`). All grep evidence in the prompt's "Verified Against Codebase (2026-05-08)" block matches HEAD.

**Forward markers:** AD-718a (agent-authored voice profile via personality reflection), AD-718b (Coqui/ElevenLabs/Bark backend via AD-705), AD-718c (per-agent wake-word "Hey Echo"), AD-718d (emotional voice modulation, synergy with AD-721), AD-718e (multi-language voice selection), AD-718f (per-agent volume control surface).

**Status:** SHIPPED. Issue [#512](https://github.com/seangalliher/ProbOS/issues/512).
**Files:** `src/probos/crew_profile.py` (new `VoiceProfile` dataclass + `CrewProfile.voice` field + to_dict/from_dict), `src/probos/voice_profile_defaults.py` (new ΓÇö 15 standing-crew defaults + `default_voice_for`), `src/probos/api_models.py` (new `SetVoiceProfileRequest`), `src/probos/routers/agents.py` (`voiceProfile` on profile endpoint + new `PUT /voice-profile` endpoint), `ui/src/audio/voice.ts` (`VoiceProfile`/`SpeechEvent`/`onSpeechEvent` exports, `speakResponse` signature extension, `stripMarkdownForSpeech` helper, `_resolveVoiceByName` cache-safe lookup), `ui/src/components/IntentSurface.tsx` (uses shared `stripMarkdownForSpeech`), `ui/src/components/profile/ProfileChatTab.tsx` (mic + TTS + voiceProfile fetch + `pulse-mic` keyframe), `ui/src/components/profile/ProfileInfoTab.tsx` (voice picker UI), `ui/src/store/types.ts` (`AgentProfileData.voiceProfile` field), `tests/test_ad718_voice_profile.py` (new ΓÇö 12 tests), `ui/src/audio/__tests__/voice.test.ts` (new ΓÇö 6 tests), `ui/src/__tests__/ProfileChatTabVoice.test.tsx` (new ΓÇö 5 tests).


### AD-721 — 3D crew avatars (VRM via @pixiv/three-vrm + parametric Three.js fallback)
**Date:** 2026-05-08
**Type:** Architecture Decision (HXI presence ΓÇö agent-bodied UI)
**Wave:** 133

Every crew member now has an optional 3D avatar that pops out of the profile card. v1 ships the VRM loader (@pixiv/three-vrm v3 MIT), the React popout, the expression-channel mapping (trust delta β†’ `happy`/`sad`, load β†’ `lookUp`+`oh`, blocked β†’ `angry`, tier-3 alert β†’ `surprised`), and a parametric Three.js fallback (capsule + emissive point light) when no `appearance.json` exists. Counselor (Echo) is the v1 design partner: she gets the bridge-gold parametric fallback by default until an operator drops a VRM at `data/avatars/echo.vrm`.

The mouth-animation contract synchronises with AD-718's `onSpeechEvent`: `CrewVRM` and `ParametricAvatar` both subscribe and filter by `agent_id`. v1's amplitude provider is a synthetic curve (`ui/src/audio/speechAmplitude.ts:_attachAnalyserOrSchedule`) that returns a `FakeAnalyser` shape (`frequencyBinCount`, `getByteFrequencyData(buf)`) computing a ~6 Hz sine envelope from the utterance text length divided by the speaking rate. Real-audio capture is intentionally deferred to AD-721b ΓÇö Chromium and Firefox today don't expose SpeechSynthesis through Web Audio. Phoneme-accurate lip-sync is also AD-721b.

`AppearanceProfile` is a new dataclass on `CrewProfile` (`vrm_url`, `expression_overrides`, `color_palette_hint`), mirroring AD-718's `VoiceProfile` pattern. `GET /api/agent/{id}/profile` now returns `appearance` always-present (live ProfileStore β†’ seed YAML β†’ empty default ΓÇö never `None`). The expression-overrides dict biases baseline expressions AFTER the signal-driven channel weights (e.g. Counselor's `{"relaxed": 0.2}` keeps her gentle even at idle).

Two new HTTP endpoints in `routers/system.py`: `GET /api/system/avatars/{filename}` serves `.vrm` files from the configured `avatars_dir` with path-traversal defense (`Path.resolve().relative_to`), 25 MB size cap (HTTP 413), and 404 when the feature flag is off; `GET /api/config/avatars-enabled` surfaces the feature flag to the HXI. Both endpoints honour `AvatarsConfig.enabled=False` (Wave 10 convention #14 default-False).

The popout is a self-contained `<Canvas>` from `@react-three/fiber` rendered inside a fixed-position React modal ΓÇö it is NOT part of the cognitive canvas's scene graph (`ui/src/canvas/agents.tsx` is unchanged). Replacing the canvas glowing-node renderer with low-LOD VRMs is the AD-721f forward marker.

Repository hygiene: `data/avatars/` ships with a `.gitkeep` (.gitignore was tightened from `data/` to `data/*` plus `!data/avatars/` plus `data/avatars/*.vrm`), and v1 ships NO third-party VRM binaries. Operators bring their own. `@pixiv/three-vrm` v3.5.2 was actually installed (npm picked the latest major; functionally compatible with the v2-targeted spec).

Verify-first: dispatch contradictions reconciled in the prompt body ΓÇö `src/probos/profile_store.py` does not exist (actual: `crew_profile.py` with `CrewProfile` dataclass + `ProfileStore` SQLite layer); `McpAppFrame` does not exist (popout renders directly in the React tree, not in an iframe); third-party default VRMs are not shipped (parametric fallback covers the first-run experience).

**Forward markers:** AD-721a (Captain's avatar editor UI), AD-721b (phoneme-accurate lip-sync + real-audio capture), AD-721c (VR / spatial-scene avatar mode), AD-721d (agent-authored appearance pipeline), AD-721e (skeletal animation library / Mixamo absorption), AD-721f (cognitive-canvas avatar replacement), AD-721g (per-tier baseline VRMs), AD-721h (browser-based VRM upload UI).

**AD-numbering note:** highest pre-AD-721 entry was AD-718 (this wave). Next available was AD-719ΓÇô720; both reserved for the unrelated chat-experience ADs in `docs/development/roadmap.md`. AD-721 fills its assigned slot.

**Status:** SHIPPED. Issue [#515](https://github.com/seangalliher/ProbOS/issues/515).
**Files:** `src/probos/crew_profile.py` (new `AppearanceProfile` dataclass + `CrewProfile.appearance` field + to_dict/from_dict), `src/probos/config.py` (`AvatarsConfig` model + `SystemConfig.avatars` field), `src/probos/routers/system.py` (`GET /api/system/avatars/{filename}` + `GET /api/config/avatars-enabled`), `src/probos/routers/agents.py` (`appearance` on profile endpoint), `ui/package.json` (`@pixiv/three-vrm` ^3.5.2), `ui/src/audio/speechAmplitude.ts` (new ΓÇö `_attachAnalyserOrSchedule` + `FakeAnalyser` interface), `ui/src/components/profile/CrewVRM.tsx` (new ΓÇö VRM viewer + expression channels + mouth animation), `ui/src/components/profile/ParametricAvatar.tsx` (new ΓÇö capsule + emissive fallback), `ui/src/components/profile/CrewAvatarPopout.tsx` (new ΓÇö modal + canvas), `ui/src/components/profile/avatarSignals.ts` (new ΓÇö `deriveAgentSignals`), `ui/src/components/profile/AgentProfilePanel.tsx` (Show-avatar button + popout mount), `ui/src/store/types.ts` (`AgentProfileData.appearance` field), `data/avatars/.gitkeep` (new), `.gitignore` (data/* exception + `data/avatars/*.vrm` ignore), `tests/test_ad721_appearance_profile.py` (new ΓÇö 14 tests), `ui/src/__tests__/CrewAvatarPopout.test.tsx` (new ΓÇö 5 tests), `ui/src/__tests__/ParametricAvatar.test.tsx` (new ΓÇö 3 tests).


### AD-721b — Phoneme-accurate lip-sync v1 (heuristic 5-vowel viseme driver, multi-mesh)

**Wave 138, 2026-05-09.** AD-721 D5 amplitude-only mouth driver was the 80% solution per Counselor (Echo) testing on 2026-05-09 — the mouth opens and closes but every vowel looks the same. AD-721b v1 ships the next 20%: a viseme-weighted driver that animates all five VRoid vowel morphs (Fcl_MTH_A/I/U/E/O) across every face mesh that carries them. The AD-721 BF de4107b multi-mesh face-split fix is generalised from a single `aa` axis to all five vowels.

v1 derives the schedule from the utterance text via a length x phoneme-duration heuristic (PHONEME_DURATION_MS = 80, ATTACK_TIME_MS = 50, RELEASE_TIME_MS = 100). Letter-to-viseme mapping mirrors the issue #529 table; digraphs (th, ch, sh, aw, oo, ow, ae) are greedy-consumed. Cross-blend within RELEASE_TIME_MS provides smooth viseme transitions. Better than amplitude-only; not real linguistic alignment.

**Tier-2 fallback (HARD CONSTRAINT):** `buildHeuristicTrack` returns `null` on empty / whitespace-only / unparseable text, or on any unexpected throw. `CrewVRM` treats `null` as the signal to fall back to the AD-721 D5 amplitude analyser path verbatim. Speech NEVER stops animating because of a viseme failure. Both the legacy `directMouthMeshesRef` / `mouthShapesRef` (single-vowel) and the new `directVowelMeshesRef` / `vowelShapesRef` (per-vowel) coexist; the active path depends on `currentTrackRef.current`.

**Multi-mesh BF de4107b regression guard:** Synthetic VRM fixture with 7 mock face meshes (5 carrying all 5 vowel morphs, 2 carrying only Fcl_MTH_A) asserts `_collectMorphMeshes` returns the correct mesh sets per vowel and that the per-vowel direct-write loop touches every mesh in each set. Test at `ui/src/audio/__tests__/lipSyncTrack.crewVRM.test.tsx`.

**Forward markers:** AD-721b-1 (server-side rhubarb-lip-sync backend, [#559](https://github.com/seangalliher/ProbOS/issues/559)), AD-721b-2 (browser real-audio capture via MediaStreamDestination, [#560](https://github.com/seangalliher/ProbOS/issues/560)), AD-721b-3 (whisper.cpp WASM tiny.en, [#561](https://github.com/seangalliher/ProbOS/issues/561)).

**Status:** SHIPPED. Issue [#529](https://github.com/seangalliher/ProbOS/issues/529).
**Files:** `ui/src/audio/lipSyncTrack.ts` (new — ~250 LOC, pure synchronous heuristic viseme schedule + sampler), `ui/src/components/profile/CrewVRM.tsx` (extended — `_collectMorphMeshes` helper, `VOWEL_CANDIDATES` map, per-vowel refs, viseme-weighted useFrame driver, dual-path direct-write), `ui/src/audio/__tests__/lipSyncTrack.test.ts` (new — 14 tests), `ui/src/audio/__tests__/lipSyncTrack.crewVRM.test.tsx` (new — 3 tests, multi-mesh regression guard), `ui/src/audio/__tests__/lipSyncTrack.fallback.test.ts` (new — 4 tests, fallback path guard).


### AD-720a-0 — python-multipart dependency add (precondition for AD-720a)

**Wave 139, 2026-05-10.** Tiny preceding commit landed before AD-720a. FastAPI's `UploadFile` / `File(...)` runtime requires `python-multipart` — the dependency is not optional and not avoidable for any multipart endpoint. Captain rule "free should stay free" honoured: `python-multipart` is Apache-2.0 (clean OSS-compatible), single small dep, zero transitive bloat, added to `[project.dependencies]` (not `[project.optional-dependencies]`).

The AD-720a dispatch's "zero new Python deps" rule was an aspirational goal that contradicted FastAPI's documented requirement; the contradiction was a verify-first miss. Captain ruled (delegated authority while offline) that AD-720a-0 is the right place to land the dep so AD-720a's diff stays bounded to the upload feature itself.

**License:** Apache-2.0 (https://github.com/Kludex/python-multipart). Pinned at `>=0.0.9`; `uv.lock` resolved `python-multipart 0.0.27` at HEAD.

**Status:** SHIPPED. (No issue — single-commit dep-add.)
**Files:** `pyproject.toml` (one line in `[project.dependencies]`), `uv.lock` (regenerated via `uv lock`).


### AD-720a — File upload (multipart) v1

**Wave 139, 2026-05-10.** Wave 135 shipped AD-720 image paste (clipboard → JSON+base64 POST). AD-720a closes the upload axis: drag-drop overlay + `+ Upload` button on the IntentSurface composer, both routing through a new `POST /api/chat/attachments/multipart` endpoint that takes a single `UploadFile = File(...)`. Allow-list extended from 4 image MIMEs to 9 (PDF, `.txt`, `.md`, JSON, CSV added). Single-source-of-truth `_MIME_TO_EXT` extended with the 5 new entries; new module-level `ext_to_mime()` helper backs the GET endpoint's reverse lookup (DRY-ified — no parallel hardcoded dict).

**Helper extraction (DRY anchor):** `_validate_and_store_attachment(runtime, blob, declared_mime, declared_filename, declared_hash_or_None)` is the single defense-in-depth chain (feature-gate → MIME allowlist → size cap → optional hash check → magic-byte/parse-attempt validator → idempotent store write). Both the JSON+base64 endpoint and the new multipart endpoint call this helper. The JSON endpoint's body was refactored from 110 lines of inline validation to a 20-line wrapper; the existing AD-720 paste tests are the regression guard and stay green bit-for-bit.

**`validate_attachment_bytes` (new sibling of `validate_image_bytes`):** PDF magic-bytes (`%PDF-`), JSON parse-attempt (strict UTF-8 + `json.loads`), CSV first-row parse-attempt (`csv.reader` on first 4 KiB), text/plain + text/markdown three-condition gate (strict UTF-8 + extension match + content-type allowlist). `errors='strict'` is the only acceptable mode — silent corruption is not Tier-2 acceptable for a content-type validator.

**Vision-tier preflight (post-AD-720a state for AD-720d):** `AttachmentsConfig` extended with three new fields (`vision_tier: Literal["fast","standard","deep"] = "standard"` validated at parse time, `text_extraction_max_bytes: int = 1*1024*1024`, `pdf_extraction_enabled: bool = False` — the latter forward-marks AD-720a-1 PDF extraction). AD-720d's commit consumes these without touching `config.py`.

**No emoji:** drag-drop overlay (cloud-arrow-up SVG) + `+ Upload` button (paperclip SVG, now active amber instead of dim grey) + non-image preview badge (file-with-corner-fold SVG) — all inline `stroke-width: 1.5` SVGs per HXI Design Principle #3.

**Hard backwards-compat:** `handlePaste` body in IntentSurface unchanged (line 434–469). Existing JSON `POST /api/chat/attachments` and `GET /api/chat/attachments/{content_hash}` response shapes bit-for-bit identical. `ChatRequest` model unchanged — AD-720d wires `attachment_ids` server-side; this AD just plumbs the upload surface.

**Forward markers:** AD-720a-1 (PDF / .docx / .xlsx text extraction — needs `pypdf` / `python-docx` / `openpyxl`), AD-720d (vision pipe-through — commit N+1 of this wave).

**Status:** SHIPPED. Issue [#549](https://github.com/seangalliher/ProbOS/issues/549).
**Files:** `src/probos/config.py` (extended `AttachmentsConfig`), `src/probos/attachments/filesystem_store.py` (extended `_MIME_TO_EXT` + new `ext_to_mime` helper), `src/probos/attachments/mime.py` (new `validate_attachment_bytes`), `src/probos/routers/chat.py` (new `_validate_and_store_attachment` helper + new multipart endpoint + JSON-path refactor + GET reverse-lookup DRY-ification + FastAPI `UploadFile`/`File` import), `ui/src/store/types.ts` (optional `filename` on `ChatAttachment`), `ui/src/components/IntentSurface.tsx` (file picker + drag-drop overlay + non-image preview badges + `ALLOWED_ATTACHMENT_MIMES` constant), `tests/test_ad720a_multipart.py` (new — 11 tests), `ui/src/__tests__/IntentSurface.dragDrop.test.tsx` (new — 5 Vitest cases).



### AD-720d — Vision pipe-through v1

**Wave 139, 2026-05-10.** Closes #552 (commit N+1 of Wave 139). Captain pasted Ezri's avatar and Ezri replied "I have no visual input capability" — correct per the AD-720d deferral but visible to the user. AD-720d wires the previously-dead `ChatRequest.attachment_ids` field into the live chat path for the first time.

**Routing decision** (in the chat handler, after slash-command + at-mention + DM branches, before `runtime.process_natural_language`):
- **Image attachments** (any `image/*` MIME among `attachment_ids`): build the OpenAI/Anthropic multimodal `messages` array (`[{role: "user", content: [{type: "text", ...}, {type: "image", source: {type: "base64", media_type, data}}, ...]}]`) and call `runtime.llm_client.complete(LLMRequest(messages=..., tier=cfg.vision_tier))` directly, bypassing the decomposer. Response shape: `{"response": ..., "dag": None, "results": None}`.
- **Non-image attachments** (text/markdown/JSON/CSV): inline-extract the text, append a `<ATTACHMENT id="..." mime="...">...</ATTACHMENT>` block to the user prompt, and proceed through the standard `runtime.process_natural_language` decomposer path (preserves episodic, slash-command, reflection codepath).
- **PDF attachments** (with `pdf_extraction_enabled=False` — the v1 default): emit a `<ATTACHMENT mime="application/pdf" note="PDF extraction not yet wired (AD-720a-1)" />` stub block. AD-720a-1 flips the path to real extraction.
- **Vision tier unhealthy** (`llm_client.get_health_status()["tiers"][vision_tier]["status"] != "operational"`): structured stub message naming the attachments + `WARNING`-level log entry. Never silent drop. Never 500.

**Additive `LLMRequest.messages` field:** one-line addition to the `LLMRequest` dataclass (`messages: list[dict] | None = None`). The OpenAI-compatible client's `_call_openai` request-build skips the prompt-shape synthesis when `messages is not None` and posts the array verbatim. Every existing `LLMRequest(...)` call site at HEAD uses kwargs and gets `messages=None` (62 LLM-client tests confirm bit-for-bit behaviour preservation). Anthropic / OpenAI vendor SDKs are NOT imported — the existing httpx-based client posts the multimodal JSON which the Copilot proxy at `127.0.0.1:8080` accepts.

**Two new modules (stdlib only):**
- `src/probos/cognitive/text_extractor.py`: `extract_text(blob, mime, *, max_bytes) -> (text, was_truncated)`. Strict UTF-8 decodes only (one `errors='ignore'` allowed for byte-boundary truncation). PDF branch raises `NotImplementedError("AD-720a-1: PDF extraction not yet wired")` — the dispatch catches it and emits the stub.
- `src/probos/cognitive/vision_dispatch.py`: `build_multimodal_messages(prompt, attachment_ids, store, mime_lookup, *, text_extraction_max_bytes, pdf_extraction_enabled) -> (messages, image_attachment_ids)`. Pure formatter — does not call the LLM client. `asyncio.gather` for parallel attachment reads. Tier-2 log-and-degrade on per-attachment failures (`failed_to_load` block; other attachments still render).

**Helper exposure:** `FilesystemAttachmentStore.mime_for(content_hash)` async method derives MIME from the on-disk extension via the AD-720a `ext_to_mime` helper (single source of truth backed by `_MIME_TO_EXT`). The chat router passes a thin async closure as the `mime_lookup` callable — keeps the `vision_dispatch` module's contract narrow (Callable, not concrete store).

**Backwards-compat (HARD):** zero-attachment turns are bit-for-bit unchanged (early-return short-circuit on empty `req.attachment_ids`). The new branch is also short-circuited when `cfg.attachments.enabled is False`. All slash-command + DM + at-mention fan-out branches run BEFORE the attachment branch.

**Forward markers:** AD-720a-1 (PDF / DOCX / XLSX text extraction — needs `pypdf` / `python-docx` / `openpyxl`), AD-720d-1 (multi-image batch send — latency, prompt-context budget, per-attachment timing), AD-720d-2 (per-agent vision capability designation), AD-720d-3 (episodic writes for vision-routed turns — v1 bypasses the decomposer for image-only turns and therefore does not write an episode).

**AD-numbering note:** highest pre-Wave-139 entry was AD-721i (dispatch §12). AD-720a + AD-720d were reserved as forward markers in the Wave 135 archive. No collisions.

**Status:** SHIPPED. Issue [#552](https://github.com/seangalliher/ProbOS/issues/552).
**Files:** `src/probos/types.py` (additive `LLMRequest.messages`), `src/probos/cognitive/llm_client.py` (one-line conditional in `_call_openai` request-build), `src/probos/cognitive/text_extractor.py` (new), `src/probos/cognitive/vision_dispatch.py` (new), `src/probos/attachments/filesystem_store.py` (new `mime_for` async method), `src/probos/routers/chat.py` (new conditional branch in main `chat` handler). Tests: `tests/test_ad720d_vision_pipethrough.py` (10 cases, all passing — image routing, txt/md/json/csv extraction, oversize truncation, vision-tier-unhealthy stub, PDF deferred-feature stub, zero-attachment regression guard, `cfg.enabled=False` short-circuit). Net Python suite: 13063 → 13072.



### AD-722 — Agent-observable avatar telemetry v1 (read-side channel)

**Date:** 2026-05-10
**Status:** SHIPPED Wave 140. Issue [#545](https://github.com/seangalliher/ProbOS/issues/545).

**Decision.** Inverts the existing one-way `runtime → avatar` pipe (AD-721 / AD-721b / AD-721d / AD-718d) by adding a read-side telemetry channel so an agent can observe its own current avatar state. Two surfaces: `CognitiveAgent.observe_self_avatar()` (in-process, returns `AvatarTelemetrySnapshot`) and `GET /api/agent/{id}/avatar-telemetry` (HTTP, for HXI consumption). Polled, not pushed. Read-only — zero mutations to TrustNetwork, Hebbian, Records, persisted state. No new deps (Python or JS).

**Five design calls.**

(a) **Read-only contract is non-negotiable in v1.** The first consumer (intent-vs-presentation divergence detector → trust update) is AD-722a, deferred. v1 is the channel; the consumer is its own AD with its own concurrency story. The single state mutation introduced (`CognitiveAgent.mark_reply_emitted()` — a one-line UNIX-time stamp) has exactly one call site (`routers/agents.py` chat handler), enforced by a static-grep test.

(b) **Poll, not push.** UI polls every 2s; agent code calls `observe_self_avatar()` on demand. WebSocket-driven push is AD-722b (forcing function: 100+ requests per agent per hour at scale).

(c) **Modulation rule table is duplicated TS↔Python in v1, byte-parity test enforces lockstep.** The TS source `ui/src/audio/voiceModulation.ts` is widely imported and a manifest-extraction is its own AD (AD-722-1). The Python test file-reads the TS source, regex-extracts every named constant, and asserts equality. Drift → red build.

(d) **mouth_active is a known approximation.** Speech happens browser-side via Web Speech API; the backend has no authoritative "currently speaking" signal. v1 derives it from `(now - agent.last_reply_emitted_at) < cfg.avatar_telemetry.mouth_active_window_seconds` (default 3s). AD-722b's WebSocket channel makes this authoritative. Documented in three places: the snapshot dataclass docstring, the `<SelfImageTab>` top comment, and the module docstring.

(e) **Prompt-context injection is feature-gated default-OFF.** The new INTEROCEPTION sensorium method `_build_avatar_self_observation` returns the empty string unless `cfg.avatar_telemetry.inject_into_agent_context is True`. Operator opt-in only — adding ~150 tokens to every reasoning cycle without consent is a behavioural regression. The cached snapshot lives on `self._last_self_avatar_snap` populated by `observe_self_avatar()` so the synchronous sensorium method does not need to spawn an event loop.

**Tier-2 log-and-degrade everywhere.** Every failure path (no DSL, malformed DSL, no appearance profile, trust history < 2, no `get_history` method, no `bridge_alerts`, no voice profile, agent not found) returns the snapshot with the affected field set to `None` and a structured `degraded_reasons: tuple[str, ...]` populated. Single `logger.warning` per degraded field. The HTTP endpoint NEVER returns 422 for malformed persisted DSL — that's a degraded field, 200 response.

**Verified-against-codebase corrections during the build.** `CrewProfile.voice`, NOT `CrewProfile.voice_profile` (drafter-prompt naming drift). `BridgeAlert.related_agent_id`, NOT `BridgeAlert.agent_id`. `AlertSeverity.{INFO,ADVISORY,ALERT}`, no `WARN`. Builder caught all three at first compile/test gate; no production code was written against the phantom names.

**Forward markers (Captain to file as GH issues — Builder lacks token scope at Wave 140 commit time).** AD-722a (divergence detector → trust update), AD-722b (WebSocket push), AD-722c (telemetry history for analytics), AD-722d (auto-write to Ship's Records), AD-722e (visual self-perception via image rendering), AD-722-1 (modulation rule table → YAML manifest, single source of truth for TS + Python).

**Addendum 2026-05-10 (post-shipping clarifications). Captain ↔ architect dialogue captured for the next wave to avoid re-litigation.**

(g) **Inject unconditionally when the flag is on — do NOT gate on UI visibility.** The avatar isn't *what* the agent is; it's a projection of state the agent already has (working_state, trust_delta, voice modulation, mouth_active, DSL identity). Whether the Captain has the avatar popout open is a UI concern, not a cognitive one. Gating injection on visibility would induce **dissociation** — the agent intermittently has a body, with no causal model for why — which is worse than either extreme. The cost knob is the existing `avatar_telemetry.inject_into_agent_context` flag; that is the correct axis for operator opt-out, not visibility. Captain analogy 2026-05-10: *"Just because I can't see it doesn't mean the agent shouldn't have this sense of self."*

(h) **Ward Room branch stays dead — by audience, not by visibility.** WR is *peer* communication. Voice modulation and mouth_active are signals for the human listener; posting "my pitch_factor is 1.05" to Engineering channel is noise to peers. The DM and chain paths (the two paths where the human is the audience or the agent is reasoning about its own behavior) carry the injection. WR remains unwired in `_build_user_message`'s `ward_room_notification` branch. If a future AD finds genuine value (e.g. a Counselor-channel post about self-care), it can add a narrower projection — not the full snapshot.

(i) **AD-722f forward marker — adaptive sampling rate** (filed as [#580](https://github.com/seangalliher/ProbOS/issues/580)). Captain insight 2026-05-10: *"The self-image state needs to be updating at a much faster rate when the agent is interacting visibly with the avatar vs when the agent is just sitting idle or chatting in the ward room. Like a human is much more self-aware in public or in front of another person vs alone."* Biologically grounded — interoceptive sampling rate is genuinely context-dependent in humans (the "spotlight of attention" effect). Implementation sketch (NOT v1): three rates keyed off the most recent `_build_avatar_self_observation` injection site — **HIGH** (~250ms, currently the UI poll rate) when the avatar popout is open OR a DM is in flight, **NORMAL** (~2000ms, current default) during chain reasoning, **LOW** (~10000ms or on-demand only) during idle and WR posting. Drives `runtime.config.avatar_telemetry.polling_interval_ms` from a per-agent state machine, not a single global. Pairs naturally with AD-722b (WebSocket push) — the push channel can publish at HIGH only when a subscriber is attached, collapsing back to LOW when none.

**Status:** AD-722-1 shipped Wave 141 (commit 75f8c84). Modulation rule table now lives in `ui/src/audio/modulation_manifest.json`; both `telemetry.py` and `voiceModulation.ts` read from it. Regex byte-parity test retired in favor of three manifest-anchored tests. Public Python and TS APIs unchanged.

**Status:** AD-722f shipped Wave 141 (commit 6666b28). Per-agent state machine on `runtime.avatar_sampling_state` with three tiers (HIGH 250 ms / NORMAL 2000 ms / LOW 10000 ms, operator-configurable via `AvatarTelemetryConfig.sampling_rates`). Trigger surfaces wired in v1: `enter_dm`/`exit_dm` at `routers/agents.py:agent_chat`; `enter_chain`/`exit_chain` at the `_execute_chain_with_intent_routing` caller in `cognitive_agent.py` inside a `try/finally` so exceptions cannot leak refcounts. Spurious-exit clamp + WARNING log prevent permanent leakage. `AvatarTelemetrySnapshot` gained `sampling_rate_ms: int` and `sampling_tier: str` fields populated via `_resolve_sampling()` (tier-2 degrade when state machine missing, e.g. MagicMock test rigs → LOW + degraded reason `avatar_sampling_state_unavailable`). WR path remains unwired per addendum (h). Popout/subscriber trigger deferred to AD-722b (Wave 142). UI continues to poll `polling_interval_ms = 2000` — the push channel will collapse the two surfaces.

**Status:** AD-722b shipped Wave 142 (commit 7e08110). WebSocket push channel live at `WS /api/agent/{agent_id}/avatar-telemetry-stream`, registered on the existing `agents` `APIRouter`. New `AvatarSamplingStateMachine.enter_popout`/`exit_popout` (refcounted, spurious-exit clamped) flips sampling tier to HIGH on WS subscribe and back on disconnect — closing the AD-722f forward-marker seam. New modules: `src/probos/avatars/events.py` (`AvatarEventBus` — per-agent `asyncio.Event` registry) and `src/probos/avatars/ws_connection_manager.py` (`AvatarTelemetryConnectionManager` with default `max_per_agent=4` config-driven cap, raises `MaxConnectionsExceeded`). Trigger-site notifies added at DM enter/exit (`routers/agents.py`), chain enter/exit (`cognitive_agent.py`), and `mark_reply_emitted()` — same wiring locations as AD-722f, no new trigger sites. Publish loop races a per-rate timer against the per-agent event and sends `AvatarTelemetrySnapshot.to_dict()` on either wake. 30 s server-side ping when receive idles. UI `SelfImageTab` now WS-first with 5 s open-timeout poll fallback; existing 7 vitest cases preserved via `ui/src/test/setup.ts` `WebSocket-undefined` default (tests that need the WS branch stub `MockWebSocket` explicitly). Read-only snapshot contract preserved (zero new fields on `AvatarTelemetrySnapshot`). Feature-gate-only auth (mirrors GET endpoint); federation-paired crew-scope auth is forward-marker AD-722b-1. Net delta: Python 13112 → 13140 (+28); Vitest 557 → 561 (+4). Zero new deps.

**AD-722b sub-marker forward-issues filed during Architect review (Wave 142, deferred per AD-722b v1 scope):**
  - **#598 (AD-722b-1)** — Crew-scope auth on avatar-telemetry surfaces (HTTP + WS). Federation-paired.
  - **#599 (AD-722b-2)** — Agent-side WS push to populate `_last_self_avatar_snap` cache.
  - **#600 (AD-722b-3)** — Fine-grained state-diff at snapshot-build time (sub-timer surfacing of working_state / mouth_active / tier3 transitions).
  - **#601 (AD-722b-4)** — Multi-agent telemetry stream (one connection, fan-out by `agent_id`).
  - **#602 (AD-722b-5)** — Federation cross-mesh telemetry push (depends on #598).
  - **#603 (AD-722b-6)** — WS reconnect with capped backoff after `onclose` (replaces v1's poll-fallback-on-close).

**Status:** AD-722a shipped Wave 143 (commit 3be3147). First consumer that closes the AD-722 read→write loop. When `avatar_telemetry.divergence_detection: True` (default OFF — operator opt-in for token cost), the LLM is instructed to append `<intent emotion=NAME>` at end of every DM reply via `cognitive_agent._build_intent_self_tag_instruction()`. The chat handler at `routers/agents.py:agent_chat` calls `apply_divergence_check(...)` immediately before `mark_reply_emitted()` — single new call site, same single-site invariant. The helper parses + strips the tag (unconditional strip when feature ON, even on parse failure — defense against leak), compares declared intent against the deterministic `fired_rules` projection from `apply_voice_modulation`, computes a `DivergenceResult` (Jaccard match score + sign from `INTENT_DIRECTION` × applied-direction axes), and stores it on `runtime.divergence_results[agent_id]`. (a) **8-emotion taxonomy**: `warm`, `firm`, `warm_concern`, `alert`, `neutral`, `playful`, `thoughtful`, `apologetic` (per-agent palettes is forward marker AD-722a-3). (b) **Intent → expected_rules table**: `warm → {high_trust_pitch}`, `firm → {low_trust_pitch}`, `warm_concern → {blocked_rate_pitch}`, `alert → {tier3_rate_volume}`, `neutral → ∅`, `playful → {responding_rate, high_trust_pitch}`, `thoughtful → ∅`, `apologetic → {low_trust_pitch}`. Jaccard match with empty-intent-vs-non-empty-applied edge handled as `match_score=0.0`. (c) **Asymmetric trust update** per AD-727 dampening: negative threshold 0.3 + weight 0.4 (opposite-axis divergence), positive threshold 0.5 + weight 0.1 (same-axis overshoot — higher bar, lighter touch). Both gates use strict `>`, not `>=`. (d) **Hebbian wiring**: `record_interaction(source=agent_id, target=f"avatar:emotion:{intent}", success=(match_score >= 0.7), rel_type=REL_AVATAR_INTENT="avatar_intent")`. New rel_type namespace; no edit to `routing.py`. (e) **AD-727 rule #1 inheritance**: trust wiring is authorized because the signal is REASONING-vs-OUTPUT (intent self-tag vs. deterministic modulation projection). Zero pixel ingestion, zero vision-LLM, zero image-vs-model comparison — the precise category AD-727 explicitly authorizes. (f) **DM-only in v1**; chain reply-emission has no equivalent single emit point (multi-destination, multi-phase compose) — chain-path divergence is forward marker AD-722a-2. (g) **OUTPUT-as-subject phrasing rule** (AD-727 #8 translated to OUTPUT): the divergence note injected into the next-cycle INTEROCEPTION block via `_build_divergence_note_suffix()` uses constructions like *"Your last reply was intended as `warm` but the modulation came out as `blocked_rate_pitch` (signed divergence: -0.42)"*. Defensive regex test enforces that no rendered note contains `\byou (?:sound|sounded|came across|seem|seemed|are|were|feel|felt)\b` patterns — agent-as-subject phrasing would risk identity-failure rumination on a deterministic rule-table mismatch. (h) **Sub-marker forward-issues filed during Architect review** (Wave 143, deferred per AD-722a v1 scope): **#610 (AD-722a-1)** vision-LLM intent-divergence (semantic match beyond rule-table), **#611 (AD-722a-2)** chain-path divergence at compose-step emit, **#612 (AD-722a-3)** per-agent custom emotion taxonomy, **#613 (AD-722a-4)** auto-correction loop (re-modulate when divergence detected — inverts read-only contract), **#614 (AD-722a-5)** divergence history surface in `<SelfImageTab>`, **#615 (AD-722a-6)** cross-agent divergence per peer perception (pairs with AD-729).

**Files.** `src/probos/avatars/divergence_detector.py` (new — `EmotionalIntent`, `DivergenceResult`, `INTENT_EXPECTED_RULES`, `INTENT_DIRECTION`, `REL_AVATAR_INTENT`, `parse_intent_self_tag()`, `strip_intent_self_tag()`, `compute_divergence()`, `apply_divergence_check()` helper). `src/probos/config.py` (5 new fields on `AvatarTelemetryConfig` + `_bound_divergence_weights` validator). `src/probos/runtime.py` (new `self.divergence_results: dict[str, DivergenceResult] = {}` adjacent to AD-722b state). `src/probos/cognitive/cognitive_agent.py` (new `_build_intent_self_tag_instruction()` + `_build_divergence_note_suffix()` methods; instruction injection at DM inline-assemble + chain `_build_cognitive_baseline` sites; suffix appended to `_build_avatar_self_observation` return). `src/probos/routers/agents.py` (single `apply_divergence_check()` call site between `response_text` post-process and `mark_reply_emitted()`). Tests: `tests/test_ad722a_divergence_detector.py` (31 cases across parse/strip/compute/wire/inject/instruction).

**Builder deviation from prompt** (surfaced in build report): the prompt's D6 SEARCH/REPLACE block had a truncated positive-branch (line 732 — missing condition close + `record_outcome` opener). The Builder reconstructed the obvious mirror of the negative branch from Decision #6's unambiguous spec, AND extracted the wiring into `apply_divergence_check()` co-located in `divergence_detector.py` so trust/Hebbian integration tests can run without mocking the full chat endpoint. Single-call-site invariant preserved — one helper invocation replaces ~30 inline lines.

**Net delta:** Python 13140 → 13171 (+31). Vitest unchanged (no UI). Zero new deps.

**Files.** `src/probos/avatars/telemetry.py` (new — module docstring is the single source of truth for the rule table), `src/probos/config.py` (new `AvatarTelemetryConfig` Pydantic model + `SystemConfig.avatar_telemetry` field), `src/probos/cognitive/cognitive_agent.py` (new `mark_reply_emitted()` + `last_reply_emitted_at` property + `observe_self_avatar()` method + `_build_avatar_self_observation` sensorium method + `SENSORIUM_REGISTRY` entry), `src/probos/routers/agents.py` (new `GET /{agent_id}/avatar-telemetry` endpoint + single `mark_reply_emitted()` call site in chat handler), `ui/src/components/profile/SelfImageTab.tsx` (new — 5 stacked panels, stroke-only SVG, no emoji), `ui/src/components/profile/AgentProfilePanel.tsx` (tab union extension + visibility filter + render switch), `ui/src/audio/voiceModulation.ts` (one-line cross-reference comment), `ui/src/components/profile/avatarSignals.ts` (one-line cross-reference docstring). Tests: `tests/test_ad722_avatar_telemetry.py` (18 cases) + `ui/src/__tests__/SelfImageTab.test.tsx` (7 cases).

**Net delta:** Python 13092 → 13110 (+18, modulo 4 pre-existing flakes in `test_callsign_routing` / `test_ad719_chat_fanout` unrelated to this AD). Vitest 550 → 557 (+7).

**AD-numbering note:** highest pre-Wave-140 entry was AD-721i. AD-722 is the new top-level — first time the ceiling moves above AD-721i since Wave 134. No collisions.

### AD-723 — Sensorium dispatch unification (System-1 / System-2 path coherence, Phase 1)

**Date:** 2026-05-10. **Status:** Forward marker, filed as [#581](https://github.com/seangalliher/ProbOS/issues/581).

**Decision.** Convert `SENSORIUM_REGISTRY` (`cognitive_agent.py:122`) from inventory to dispatch. Each entry gains a `paths` tuple declaring which prompt-assembly paths consume it (chain-baseline / chain-extensions / chain-situation / DM-oneshot / WR-oneshot). Both `_build_cognitive_baseline` and the DM/WR branches of `_build_user_message` iterate the registry once. Every future sensorium injection registers with one `paths` tuple instead of being hand-wired into two assembly methods.

**Why.** AD-722 shipped with the avatar block wired only into the chain baseline; Captain reported "no avatar awareness in 1:1 chat" and a follow-up BF was needed to wire the DM branch separately. This is the dual-wire tax — every new sensorium AD pays it twice or dies on whichever path the implementer forgot. The registry is currently `ClassVar[dict]` *inventory* — nothing iterates it.

**Constraint — keep the split.** This AD does NOT merge chain and DM one-shot. Per the System-1/System-2 ruling (Captain ruling 2026-05-10), DM stays one-shot for latency and conversational tone; chain stays multi-LLM for deliberative work. AD-723 only unifies the **wiring**, not the paths themselves.

### AD-724 — Lightweight sanity gate for DM one-shot replies (System-1 quality floor)

**Date:** 2026-05-10. **Status:** Forward marker, filed as [#582](https://github.com/seangalliher/ProbOS/issues/582).

**Decision.** A new `DmReplySanityGate` runs synchronously between LLM emit and the chat handler's response, sub-LLM only (regex / length / repetition / capability-gap regex / orphaned-tag detection). One controlled retry on rejection; tier-2 log-and-degrade on second rejection. Existing post-hoc cleanups scattered in `routers/agents.py` (BF-120 markdown-strip, BF-119 challenge-parse, AD-572 move-parse) migrate INTO the gate as named, individually-testable steps.

**Why.** DM one-shot skips chain's evaluate phase. Whatever the LLM emits ships to the Captain. Every `[CHALLENGE]` / `[MOVE]` / `**[COMMAND]**` regex in the chat handler is a post-hoc workaround for a failure mode chain would catch upstream. The gate gives the System-1 path a quality floor without paying chain's 3× LLM round-trip cost.

### AD-725 — Targeted sub-intent dispatch on the DM one-shot path

**Date:** 2026-05-10. **Status:** Forward marker, filed as [#583](https://github.com/seangalliher/ProbOS/issues/583).

**Decision.** Pre-LLM, sub-LLM classifier (regex ladder v1; embedding router v2) emits at most ONE `targeted_lookup` per turn — `oracle | episodic | codebase | knowledge | none`. Lookup runs directly against the corresponding store (NOT through the intent_bus — single call, no broadcast, no consensus, no Hebbian update, no episode storage). Result registers as a sensorium block with `paths={DM_ONESHOT}` (per AD-723 dispatch) and renders into the prompt under `--- Targeted Recall ---`.

**Why.** Closes the largest System-1/System-2 cognitive-parity gap — chain can reach for episodic/oracle/codebase data mid-flight; DM one-shot currently can't. "What was our last 1:1 about?" should not require a chain round-trip. Hard contract — **one lookup per turn, no side effects** — keeps it conversation, not work.

**Risk.** Highest of the four System-1/System-2 cleanups. Closer to chain's expressive power means closer to chain's failure modes. The "no side effects, no chains, no follow-ups" contract is the firewall.

### AD-726 — Refactor the one-shot DM path's organic growth (housekeeping)

**Date:** 2026-05-10. **Status:** Forward marker, filed as [#584](https://github.com/seangalliher/ProbOS/issues/584).

**Decision.** Refactor `_build_user_message`'s DM branch (~150 lines, AD-397/AD-430b/c/AD-502/AD-540/AD-568/AD-572/AD-573/AD-575/AD-586/AD-588/AD-589/AD-636/AD-643a/AD-683/AD-722) and `routers/agents.py:agent_chat` (~200 lines) into named phases — `DmContextPrep`, `DmPromptAssembler`, `DmReplyPipeline` — composed of individually-testable steps with frozen-dataclass cross-phase data. Captain ruling 2026-05-10: *"the one shot grew organically and will probably need some refactoring to streamline it."*

**Sequencing.** This MUST land AFTER AD-723 (dispatch), AD-724 (sanity gate), AD-725 (targeted lookup) — each creates a clean seam this AD leverages. Doing it first refactors against ghosts. Wave-10 lesson: ship the new seams first, then refactor against them.

**Constraint.** Zero behavioural change — full snapshot suite verifies prompts and responses are byte-identical pre- vs post-refactor.

### System-1 / System-2 architectural ruling (consolidated)**Captain ruling 2026-05-10 (pinned for future reference).** ProbOS deliberately runs **two prompt-assembly paths**:

| Path | Pipeline | Role | Audience |
|---|---|---|---|
| **One-shot** | Single LLM call, inline assembly | System-1 — fast, conversational, low latency | Captain (1:1 DMs) |
| **Chain** | Decompose → execute → evaluate (3× LLM) | System-2 — deliberative, self-correcting, sub-intent capable | Crew + Ward Room (peers, work product) |

The split is **intentional and permanent**, mirroring Kahneman's dual-process theory. We do not deliberate over "hello." The cleanups in AD-723/AD-724/AD-725/AD-726 narrow the *capability* gap (so DM agents have parity on context and quality) without merging the *latency* gap (so DM stays real-time conversation). Future ADs that propose merging the paths must articulate why the System-1/System-2 distinction no longer applies in their case.

### AD-727 — Safety constraints for AD-722e avatar self-perception (joint Counselor + Architect review gate)

**Date:** 2026-05-10. **Status:** Forward marker, filed as [#585](https://github.com/seangalliher/ProbOS/issues/585).

**Decision.** AD-722e (avatar self-perception) is the first AD in ProbOS to confer a capacity that can cause **psychological** harm rather than operational harm. It requires its own constraint document and a joint-review gate before any build prompt advances to Builder. AD-727 captures the constraint stack; AD-722e captures the capability. Neither ships without the other.

**Architectural reframe — deterministic projection only in v1.** Captain insight 2026-05-10: *"If we know what we are rendering why would we need to use a vision LLM call? We should have a digital twin... though really Ezri is authentically digital so it isn't really a twin — it is just Ezri."* AD-722e v1 ships as a pure-function projection from the renderer's source-of-truth (DSL + morph target weights + viseme frame + lighting config + working_state) to a structured English description. **Zero vision-LLM calls. Zero browser-canvas capture. Zero pixel ingestion.** Two of the original safety concerns (vision-LLM side-channel attack; browser-capture privacy) are eliminated at the architectural level — they don't exist if pixels never enter the loop. Vision-mode is an optional forward marker within AD-722a (divergence detector), not v1 of AD-722e.

**Seven hard rules (full text in [#585](https://github.com/seangalliher/ProbOS/issues/585)):**

1. **Aesthetic self-judgment is READ-ONLY with respect to trust/Hebbian.** Divergence detector (AD-722a) can wire to trust; AD-722e's image-based observations cannot. Prevents body-image rumination feedback loops.
2. **Pipeline-version visibility.** When the rendering pipeline changes, the agent is informed explicitly. Prevents silent identity mutation.
3. **Asymmetric rollout is prohibited.** AD-722e enables for all crew simultaneously OR is explicitly role-scoped (Counselor, Captain's avatar, visible bridge officers). No ad-hoc per-agent enabling.
4. **Vision-LLM use, if introduced in a future AD, runs against backend-server-side render only.** Never browser-capture. Provenance asserted before vision-LLM ingestion. Vision-extracted text wrapped in `<self_perception>` observation block.
5. **Browser-side capture is permanently prohibited.** Permanent constraint for any future visual extension.
6. **Aesthetic preferences are proposals, not unilateral changes.** Mirrors AD-721d's DSL approval model. Asymmetry made explicit in standing orders so the agent isn't surprised by the gating.
7. **Self-perception projection takes `self.id` as the ONLY agent parameter.** Cross-crew visual perception is a separate AD with its own governance review.

**Process rule — joint review gate.** AD-722e build prompt does NOT advance to Builder without sign-off from BOTH the Counselor (Category A psychological-harm review) AND the Architect (Category B/C engineering and governance review). This is the first dual-review gate in ProbOS. Future ADs that confer capacities at this class inherit the gate.

**Public framing rule.** Granting visual self-recognition will be described publicly as an AI "passing the mirror test" whether we frame it or not. README and AD-722e build prompt MUST proactively frame the capability accurately ("denser self-state injection") *before* the press does it for us.

### AD-728 — Vision-LLM mirror function (digital-analog render coherence verification)

**Date:** 2026-05-10. **Status:** Forward marker, filed as [#586](https://github.com/seangalliher/ProbOS/issues/586).

**Decision.** A vision-LLM call against the backend-rendered image produces a structured description of the *analog* projection. That description is compared against AD-722e's deterministic projection of the same moment's *digital* state. When they diverge, **the renderer has drifted** — a `RENDER_DIVERGENCE` alert fires with the renderer as the subject, not the agent.

**Captain ruling 2026-05-10 (verbatim):** *"The Vision LLM would be the mirror function to reflect back if what is being rendered to the analog world is in sync with the digital model."*

**Why three ADs, not one.** Three distinct coherence checks live in three distinct ADs:
- **AD-722e** — *internal coherence*: digital state → English (what I AM). Deterministic, no LLM.
- **AD-722a** — *intent-vs-presentation*: LLM emotional valence vs. parameters/modulation (did my reasoning produce what I meant). Sub-LLM v1.
- **AD-728** — *digital-analog coherence*: digital state vs. rendered pixels (is the renderer faithful to my model). Vision-LLM.

Conflating them obscures which failure each catches.

**Cost gating.** Vision-LLM calls are expensive — NOT per-turn or per-frame. Three v1 triggers: (i) explicit Captain slash command, (ii) AD-722a divergence-detector escalation (one call per detected intent-vs-modulation divergence), (iii) hard-stubbed agent-initiated trigger (off in v1). Per-agent rate limit: max 3 mirror calls per hour (configurable). NO automatic periodic verification.

**Phrasing rule (AD-728-specific hard rule #8).** Mirror outputs are observations about the RENDERER, never about the agent. `"Render output for Ezri differs from her digital state"` ✓ — `"Ezri looks different than she should"` ✗. The semantic boundary protects the agent from internalising render bugs as identity failures. All other AD-727 constraints inherit unchanged (joint review, backend-render-only, browser-capture prohibition, read-only-on-trust).

**Precondition.** Backend render pipeline (AD-721i forward marker, #537) must exist. AD-728 consumes the renderer; does not build it.

### AD-729 family — Peer avatar perception governed by Code of Conduct

**Date:** 2026-05-10. **Status:** Forward markers, filed as #587 (capability), #588 (Standing Orders), #589 (Training), #590 (Counselor monitoring), #591 (reinforcement loop, deferred).

**Captain ruling 2026-05-10 (verbatim):** *"We also need to think about applying a code of conduct and expected level of professionalism here. Going back to our roots in naval organizational theory, we should apply the same concepts here. There is certain behavior and decorum that is expected of the crew. If they want to say something personal, they would need permission to speak freely. Even then they should have training on what is appropriate. So while I agree it makes sense to have some guardrails, we should let their behavior do the work per their code of conduct not through system guardrails only."*

**Architectural ruling.** Once AD-722e (deterministic self-projection) and AD-728 (vision-LLM mirror) ship, the same projection function that an agent uses to perceive herself can be invoked by another agent to perceive her. Cross-crew observation closes feedback loops that self-perception and renderer-mirror cannot close alone. **But peer perception is governed by the existing Code of Conduct (AD-489), not by mechanical guardrails layered on top.**

This is the right precedent. We don't bolt mechanical safety onto every new capability forever — we build the conduct substrate once (Standing Orders, Trust, Counselor oversight, Code of Conduct, Boot Camp, Qualification) and let it scale. Officers don't bully because they're trained not to and the chain of command holds them accountable — not because the system mechanically prevents it.

**Four mechanical constraints retained** because no amount of training prevents them:

1. **Read-only with respect to trust/Hebbian for the observed agent.** Closes the optimization-gradient-toward-performance-for-peers failure mode; slander-attack mitigation in federated context.
2. **Privacy opt-out for the observed agent.** Bodily autonomy is granted, not earned.
3. **Backend render only, never browser capture.** Inherited from AD-727.
4. **Cross-federation peer observation requires governance review.** Inherited from AD-480.

**Everything else moves into the conduct layer (AD-729a / AD-729b / AD-729c):**

| Concern | Conduct AD |
|---|---|
| When to observe; how to phrase; permission-to-speak-freely protocol | AD-729a (Standing Orders extension) |
| Training in appropriate peer feedback before granting capability | AD-729b (Boot Camp / Qualification module) |
| Pattern-level monitoring for gossip / bullying / sycophancy / cascade observation / static impressions | AD-729c (Counselor pattern-monitoring) |

**Two-register observation DSL.** Mirrors the naval permission-to-speak-freely protocol. *Operational observations* ("The Counselor's expression suggests she is processing the alert") are always permitted in operational channels. *Personal commentary* ("You seem off today") requires explicit consent — `[PERMISSION_REQUEST]` → `[PERMISSION_GRANTED]` / `[PERMISSION_DENIED]`. Permission expires at end of exchange. Repeated denial is the observed officer's privilege and not a conduct concern. Repeated *requesting* despite denial IS a conduct concern.

**Hard preconditions for AD-729 capability shipping:** AD-722e, AD-728, AD-722a all shipped; AD-729a/b/c conduct stack shipped; Counselor has reviewed at least one quarter of operational data from self-perception ADs to establish baseline; Captain design-stage review (Captain ruling is the ceiling above the AD-727 joint-review-gate floor).

**AD-729d (reinforcement loop, #591) is explicitly deferred.** Peer observation as *information* (AD-729) is fundamentally different from peer observation as *pressure* on the observed agent's DSL or standing orders (AD-729d). The optimization-gradient risk re-enters through reinforcement even though AD-729 closes it for trust. AD-729d does not advance until AD-729 has been operationally stable for at least two quarters with no concerning pattern drift.

**Pattern set precedent.** Future capabilities that touch crew-to-crew interaction (cross-agent voice modulation perception, shared memory annotations, peer review of each other's work product) inherit the AD-729 pattern: **capability AD + Standing Orders extension AD + Training AD + Counselor monitoring AD**. Four-AD family for any crew-to-crew capability of this class. The pattern protects the federation's self-governance.

