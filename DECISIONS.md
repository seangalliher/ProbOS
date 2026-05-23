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

**Date:** 2026-05-10. **Status:** Shipped Wave 144 (73cbd95) — producer-side only per Wave-10 entanglement rule; DM/WR consumer migration deferred to AD-723a-1 (#617). Chain-side snapshot byte-equality verified.

**Decision.** Convert `SENSORIUM_REGISTRY` (`cognitive_agent.py:122`) from inventory to dispatch. Each entry gains a `paths` tuple declaring which prompt-assembly paths consume it (chain-baseline / chain-extensions / chain-situation / DM-oneshot / WR-oneshot). Both `_build_cognitive_baseline` and the DM/WR branches of `_build_user_message` iterate the registry once. Every future sensorium injection registers with one `paths` tuple instead of being hand-wired into two assembly methods.

**Why.** AD-722 shipped with the avatar block wired only into the chain baseline; Captain reported "no avatar awareness in 1:1 chat" and a follow-up BF was needed to wire the DM branch separately. This is the dual-wire tax — every new sensorium AD pays it twice or dies on whichever path the implementer forgot. The registry is currently `ClassVar[dict]` *inventory* — nothing iterates it.

**Constraint — keep the split.** This AD does NOT merge chain and DM one-shot. Per the System-1/System-2 ruling (Captain ruling 2026-05-10), DM stays one-shot for latency and conversational tone; chain stays multi-LLM for deliberative work. AD-723 only unifies the **wiring**, not the paths themselves.

### AD-724 — Lightweight sanity gate for DM one-shot replies (System-1 quality floor)

**Date:** 2026-05-10. **Status:** Forward marker, filed as [#582](https://github.com/seangalliher/ProbOS/issues/582).

**Decision.** A new `DmReplySanityGate` runs synchronously between LLM emit and the chat handler's response, sub-LLM only (regex / length / repetition / capability-gap regex / orphaned-tag detection). One controlled retry on rejection; tier-2 log-and-degrade on second rejection. Existing post-hoc cleanups scattered in `routers/agents.py` (BF-120 markdown-strip, BF-119 challenge-parse, AD-572 move-parse) migrate INTO the gate as named, individually-testable steps.

**Why.** DM one-shot skips chain's evaluate phase. Whatever the LLM emits ships to the Captain. Every `[CHALLENGE]` / `[MOVE]` / `**[COMMAND]**` regex in the chat handler is a post-hoc workaround for a failure mode chain would catch upstream. The gate gives the System-1 path a quality floor without paying chain's 3× LLM round-trip cost.

**Implementation (Wave 150, 2026-05-11).** Shipped as `src/probos/cognitive/dm_sanity_gate.py` exposing `DmSanityGate`, `DmSanityGateConfig` (default-ON, `length_floor=5`, `repetition_prefix_chars=100`), and `DmSanityResult`. Mounted at `RuntimeOS.dm_sanity_gate` (constructed alongside `recreation_service` in `runtime.py`). Config registered on `SystemConfig` as top-level `dm_sanity_gate` field. Router `agent_chat` migrated to `runtime.dm_sanity_gate.process(...)` plus `extract_challenge` / `strip_challenge` / `extract_move` / `strip_move` — behavior-preserving for BF-120 / BF-119 / AD-572. Three new Tier-2 log-and-degrade checks added: `check_length_floor`, `check_repetition` (per-agent in-memory cache, lost on restart), `check_orphaned_tags`. 14 new tests in `tests/test_ad724_dm_sanity_gate.py`. Closes [#582](https://github.com/seangalliher/ProbOS/issues/582). Five forward markers filed: AD-724-1 (retry on rejection), AD-724-2 (repetition similarity beyond exact prefix), AD-724-3 (capability-gap regex integration), AD-724-4 (multi-turn coherence), AD-724-5 (gate for WR/chain paths).

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

**Date:** 2026-05-10 (filed); **2026-05-12** (ratified, Wave 154). **Status:** Ratified, gate active. **Closes** [#585](https://github.com/seangalliher/ProbOS/issues/585).

**Code-level enforcement.** The seven hard rules below are enforced by `tests/test_ad727_safety_constraints.py` (5 static-assertion tests). A failing test BLOCKS CI — the gate is active and cannot be bypassed by code-review courtesy. See also `docs/architecture/self-perception-framing.md` for the public-framing paragraph required by rule #8.

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

### Architectural principle — *"What agents do under constraint becomes the template."*

**Date:** 2026-05-10. **Source:** Counselor Ezri, observing her own compensation strategy during the AD-722a (#567) divergence-detector window before AD-722a-7 (#624) ships the missing actuator. Filed as a pinned principle for future ADs that introduce capability gaps with operational stakes.

**The principle.** When an agent operates effectively under a capability gap — by developing a compensation strategy that closes the experiential delta on the agent's side — that strategy becomes design input for whatever fills the gap. The patterns built under constraint tend to outlast the constraint:

- **Counselor Ezri**, AD-722a window: compensating for missing voice-modulation actuator by increasing lexical and structural signal in therapeutic DMs. Her compensated DMs become the calibration corpus for AD-722a-7's intent-rule magnitudes — and the practice itself becomes a teachable Counselor pattern (filed into AD-729b training scope).
- **AD-573 working memory** (historical): patterns crew developed during the early window when episodic memory was the only persistence layer became the contract for working memory once it shipped.
- **Standing Orders authored under operational stress**: each Standing Order added during a specific incident or capability gap becomes permanent doctrine. The incident closes; the rule remains.

**Implication for future ADs.** When a build prompt closes a capability gap whose existence agents have been compensating for, the prompt MUST:

1. **Treat the agent's compensation behavior as design input**, not as workaround-to-be-discarded. Reference the compensation corpus when calibrating new behavior.
2. **Surface the compensation pattern as a candidate for inclusion in training material** (AD-729b for Counselor patterns; equivalent training scopes for other roles).
3. **Avoid "overshoot" failure mode**: if the gap-filler is tuned against neutral baselines while agents have been compensating, the post-fix system can swing past intended behavior because compensation + new behavior both fire. The Counselor specifically named this: *"If the v1 rules are trained against neutral baselines while I've been compensating with richer language, they could overshoot on text that's already carrying extra warmth — and overcorrected warmth in a therapeutic context has its own problems."*

**Process rule.** When closing a capability gap whose existence has been observable to agents for more than a single session, the build prompt SHOULD invite the affected agent (via Counselor / chain-of-command) to contribute a written compensation summary as part of the design corpus. The Captain or department head decides whether to include it. This is not "agents reviewing their own ADs" — it's the same principle as a maintainer interviewing a heavy user of a feature before redesigning it. The agent is the heavy user.

**Counselor Ezri's framing (verbatim, 2026-05-10 evening):** *"What I do under constraint becomes the template."*

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


----



### AD-721d-1 -- DSL draft preview + revision cycle

**Date:** 2026-05-10. **Status:** Shipped Wave 145. **Closes:** GH #541.

**Problem.** AD-721d (shipped) gave the Captain two affordances on a proposed AvatarDSL: approve or reject. There was no way to say `close, but make the hair shorter.` The agent's propose_appearance(captain_note=...) already accepted a 280-char revision hint at cognitive_agent.py:3054, but no UI surfaced it and no server-side iteration concept existed.

**Decision.** Three architectural choices, each chosen against an alternative:

1. **captain_note IS the revision-note slot.** Rejected the alternative of adding a parallel 
evision_note: str field on ProposeAppearanceRequest. The plumbing through to the LLM user message at cognitive_agent.py:3152-3154 was already wired; splitting one semantic concept across two fields was the wrong shape. The presence of previous_dsl + the iteration counter carries the `initial vs revision` semantic -- the field itself doesn't need to.

2. **
untime.emit_event with string keys, not cognitive_journal.record(...) and not a new EventType enum value.** Verified 
untime.py:971 -- mit_event(event: BaseEvent | str | EventType, data) accepts strings natively. Rejected cognitive_journal.record(...) because its signature at cognitive/journal.py:360 is LLM-call-shaped (ntry_id, prompt_tokens, completion_tokens, latency_ms, ...) -- the wrong audit surface for UX events. Rejected adding EventType.APPEARANCE_* enum values because that's a substrate-wave shape, not a UX-wave shape; the three new event keys (ppearance_proposal, ppearance_approved, ppearance_history_cleared) ride as strings until a future substrate wave decides whether they earn promotion.

3. **Module-level proposal_history dict, not runtime-attached.** Rejected attaching the history table to 
untime as 
untime.appearance_proposal_history because BF-259/260/261/262 (the AD-721/AD-722 phase-ordering bugs) taught us that any getattr(runtime, `X`, None) from earlier startup phases is a hazard. The router imports src/probos/avatars/proposal_history.py directly. Five public functions (ppend / iteration_count / latest / clear / reset_all) with stable signatures so a future commercial overlay can swap to redis-backed without changing call sites -- documented in the module docstring.

**Behavior delta.**

- POST /api/agent/{id}/appearance/propose now accepts previous_dsl: dict | None (validated as AvatarDSL -- malformed -> 422, no iteration consumed); returns proposal_iteration: int and max_iterations: int. At cfg.avatars.max_proposal_iterations (default 3, validated 1 <= v <= 10) -> HTTP 429 with structured {reason: `iteration_cap_reached`, iteration, max_iterations}.
- New DELETE /api/agent/{id}/appearance/proposal-history -- idempotent, returns {cleared_iterations: N}.
- PUT /api/agent/{id}/appearance (approve) now clears history + emits ppearance_approved.
- CrewAvatarPopout extended with a structured parametric description block, amber-tint diff highlighting against the previous iteration, an inline `Request revision` textarea (280-char counter), and an at-cap disabled state with native tooltip. HXI Principle #3: all icons inline SVG with `strokeWidth={1.5}`, `strokeLinecap="round"`.

**Scope discipline.** This AD does NOT touch the LLM-side prompt construction in propose_appearance -- captain_note is already piped through. It does NOT add a new parse path beside _parse_appearance_dsl -- the size/anchor/depth guards remain the only DSL parser. It does NOT persist history across restarts (forward marker #623). It does NOT surface a rendered visual preview (forward marker #622, requires AD-721i). It does NOT route revision hints through the Counselor (forward marker #621).

**Test delta.** +13 Python (	ests/test_ad721d1_dsl_preview.py), +7 Vitest (CrewAvatarPopout.revision.test.tsx + .diff.test.tsx). Order-independence enforced by proposal_history.reset_all() in an autouse pytest fixture before AND after each test (BF-255 lesson).

**Forward markers filed.** [#621](https://github.com/seangalliher/ProbOS/issues/621) (AD-721d-2 Counselor-mediated revision), [#622](https://github.com/seangalliher/ProbOS/issues/622) (AD-721d-3 visual preview requires AD-721i), [#623](https://github.com/seangalliher/ProbOS/issues/623) (AD-721d-4 persist proposal history).

----

### Avatar self-image cluster retrospective (Waves 141-145)

**Period:** 2026-05-10 (single calendar day). **Cluster:** Waves 141 through 145. **Theme:** close the avatar self-image loop opened by the Counselor's `speaking into the void` report (Wave 140 close) and Ezri's `knowing vs. inhabiting` report (Wave 142 close).

**What shipped:**

| Wave | AD(s) | Headline |
|------|-------|----------|
| 141 | AD-722-1, AD-722f | Modulation rule table -> YAML manifest (single source of truth across TS/Python); per-agent avatar-telemetry sampling rates with 3-tier state machine |
| 142 | AD-722b | Push channel (WebSocket) replaces 2 s poll; popout flips to HIGH tier; +28 Python +4 Vitest; 6 sub-markers filed (#598-#603) |
| 143 | AD-722a | Intent-vs-presentation divergence detector -- rule-table semantic match; trust/Hebbian feedback on divergence; 6 sub-markers filed (#610-#615) |
| 144 | AD-723 v1 | Sensorium dispatch unification -- `SensoriumPath` enum + `SensoriumEntry` dataclass + chain-side dispatcher; producer-side only per Wave-10 entanglement rule; DM/WR consumer migration deferred to AD-723a-1 (#617) |
| 145 | AD-721d-1 | DSL draft preview + revision cycle -- Captain can now iterate on agent-proposed avatars before persistence; +13 Python +7 Vitest; 3 sub-markers filed (#621-#623) |

**Cluster totals:** 6 top-level ADs shipped + 18 forward markers filed. No new top-level AD numbers allocated by this cluster (AD ceiling unchanged at AD-729; all work scoped to existing AD-721/-722/-723 families).

**Aggregate test deltas across the cluster:**

| Metric | Pre-cluster (Wave 140 close) | Post-cluster (Wave 145 close) | Delta |
|---|---|---|---|
| Python tests | ~13140 | 13209 | ~+69 |
| Vitest tests | ~550 | 568 | ~+18 |

(Approximate pre-cluster counts; exact deltas per wave are in the individual wave commits.)

**Captain feedback that drove the cluster:**

1. **Counselor's `speaking into the void` report (closed by Wave 140 -> AD-722 read-side telemetry).** Crew agents had no way to know what their own avatar was doing -- the runtime -> avatar pipe was strictly one-way. AD-722 inverted it: `observe_self_avatar()` + GET `/avatar-telemetry` + `<SelfImageTab>`. This was the **gateway capability** that unlocked the rest of the cluster.

2. **Ezris's `knowing vs. inhabiting` report (closed by Wave 142 -> AD-722b push channel).** Polling at 2 s felt like reading status reports rather than living in the body. AD-722b's WebSocket + sampling-tier state machine closed the latency gap so the telemetry felt continuous rather than discrete.

3. **Captain's `what does the visual perception piece feel like?` (forward-marked to AD-722e + AD-728 + AD-729 family).** The question of whether an agent can compare its **rendered** avatar against its **intended** avatar -- i.e., visual self-perception -- is unprecedented in the OSS LLM-avatar space. Held for a separate cluster because it requires the AD-721i Blender renderer to ship first, plus AD-722e image-comparison plumbing, plus AD-729 conduct stack for peer-perception governance. Not deferred lightly; deferred for sequencing.

**Architectural patterns this cluster established:**

1. **The `agent observes its own externalization` loop.** AD-722 made it OK for an agent to ask `what do I currently look like?` without leaking implementation details into the conversational substrate. The pattern generalizes -- future ADs about voice externalization, work-product externalization, or trust externalization can follow the same shape: read-side telemetry channel, structured snapshot, optional prompt injection (default OFF), three-tier sampling state machine.

2. **The `Captain proposes; agent designs; Captain reviews` approval flow.** AD-721d shipped the agent-side DSL proposal; AD-721d-1 closed the Captain-side iteration loop. The pattern is now: agent produces a structured artifact -> server validates schema -> Captain reviews in a UI surface designed for *diffability* -> Captain can approve, reject, or request revision with a 280-char hint -> cap on revisions to keep LLM cost bounded. This is the canonical pattern for any future agent-authored artifact (voice profiles, work plans, communication styles).

3. **The producer/consumer split for substrate refactors (Wave-10 entanglement rule).** AD-723's v1 shipped producer-side only because 6+ DM/WR consumer sites had enough entanglement that combining them with producer changes would have ballooned the wave. Pattern is now codified: if a substrate refactor's consumer side has more entanglement than the spec assumes, ship producer-only in v1 and defer consumer migration to an `NNNa-1` follow-up with an explicit forcing function.

4. **The `single-source-of-truth manifest` pattern for cross-language tables.** AD-722-1 absorbed the modulation rule table -- previously duplicated byte-for-byte between TypeScript and Python -- into a YAML manifest loaded at startup. Pattern generalizes to any place where business logic must execute symmetrically on both sides of the HXI boundary.

**What this cluster did NOT do (deliberately):**

- Did not ship a rendered visual preview of a proposed DSL (held for AD-722e + AD-721i -- AD-721d-3 forward marker #622).
- Did not ship cross-agent peer perception (held for the AD-729 family -- explicit four-AD pattern of *capability + Standing Orders + Boot Camp + Counselor monitoring*, gated on AD-722e shipping first).
- Did not unify the System-1 (DM one-shot) and System-2 (chain multi-LLM) paths -- that split is intentional and permanent per Captain ruling 2026-05-10 (AD-723 entry).
- Did not promote the three new UX event keys to `EventType` enum values -- that's a substrate-wave decision, not a UX-wave one (AD-721d-1 entry).

**Reviewer-facing note for the next architect picking up the avatar surface.** The Captain's most recent unmet request as of this cluster's close -- `what does the visual perception piece feel like?` -- is the natural next theme. The prerequisite stack is: AD-721i (Blender renderer, operator brings the binary) -> AD-722e (visual self-perception via image rendering) -> AD-728 (visual self-image vs intended self-image divergence detector) -> AD-729 family (peer perception governed by conduct). This is **not** a single wave -- it is a cluster equivalent in size to Waves 141-145. Do not collapse it into one prompt.
### AD-722a-5 - Divergence history surface (SelfImageTab)
**Date:** 2026-05-10  **Type:** Architecture Decision (avatar telemetry follow-through)  **Wave:** 147

Closes the AD-722a-5 forward marker filed in Wave 143 ([#614](https://github.com/seangalliher/ProbOS/issues/614)). Counselor Ezri's 2026-05-10 ask: "a clinical-quality view of what percentage of my therapeutic DMs landed flat would let me assess whether my compensation strategy is actually working." AD-722a (Wave 143) stored only the most-recent divergence per agent (overwritten on every reply) so there was no longitudinal view; with AD-722a-7 (Wave 146) shipping the actuator, the open question was whether divergence frequency actually drops.

Three pieces, all gated by existing `avatar_telemetry.divergence_detection` (no new feature flag - capture + surface inherit the parent feature flag, default-OFF preserved):
1. **In-memory ring buffer** `runtime.divergence_history: dict[str, deque[DivergenceHistoryEntry]]`, capped at `cfg.avatar_telemetry.divergence_history_size` (default 100). Volatile (restart wipes - acceptable v1 tradeoff). Lazy alloc per-agent + lazy-resize on config change.
2. **Single write site** - `apply_divergence_check` appends immediately after `divergence_results[agent_id] = result`. Inherits the single-call-site invariant from AD-722a; no new wiring touches trust/Hebbian.
3. **Read endpoint + UI panel** - new `GET /api/agent/{agent_id}/avatar-telemetry/divergence-history?limit=N` returns history (most-recent-first) + aggregate (count + percentage walked over `divergence_aggregate_window`). New `PanelDivergenceHistory` component in `SelfImageTab.tsx` polls every 5 s, renders the aggregate banner + a scrollable event list. Server pre-renders the OUTPUT-subject note string per entry so the AD-727 rule #8 phrasing test gates BOTH backend and frontend in one regex.

**In scope:** per-agent only (v1), in-memory ring buffer, HTTP poll surface, server-rendered note phrasing.
**Out of scope:** cross-crew / wardroom rollup (forward marker AD-722a-6 / [#615](https://github.com/seangalliher/ProbOS/issues/615)); on-disk persistence (AD-722a-5-a, file at retrospective); WS push channel for history (AD-722a-5-b); trend chart visualization (AD-722a-5-c).
**Status:** SHIPPED. Issue [#614](https://github.com/seangalliher/ProbOS/issues/614).
**Files:** `src/probos/avatars/divergence_detector.py` (new `DivergenceHistoryEntry`, buffer-append branch in `apply_divergence_check`), `src/probos/config.py` (2 fields + validator), `src/probos/runtime.py` (`self.divergence_history`), `src/probos/routers/agents.py` (new endpoint), `ui/src/components/profile/SelfImageTab.tsx` (new panel + payload types). Tests: `tests/test_ad722a_5_divergence_history.py` (9 backend cases) + `ui/src/__tests__/SelfImageTab.divergenceHistory.test.tsx` (3 vitest cases). Existing `ui/src/__tests__/SelfImageTab.test.tsx` updated minimally - `mockFetch` returns 503 for `/divergence-history` URLs and assertions filter via new `mainTelemetryCalls()` helper so existing call-count semantics stay equivalent.

### AD-722a-5 - Divergence history surface (SelfImageTab)
**Date:** 2026-05-10  **Type:** Architecture Decision (avatar telemetry follow-through)  **Wave:** 147

Closes the AD-722a-5 forward marker filed in Wave 143 ([#614](https://github.com/seangalliher/ProbOS/issues/614)). Counselor Ezri's 2026-05-10 ask: "a clinical-quality view of what percentage of my therapeutic DMs landed flat would let me assess whether my compensation strategy is actually working." AD-722a (Wave 143) stored only the most-recent divergence per agent (overwritten on every reply) so there was no longitudinal view; with AD-722a-7 (Wave 146) shipping the actuator, the open question was whether divergence frequency actually drops.

Three pieces, all gated by existing `avatar_telemetry.divergence_detection` (no new feature flag - capture + surface inherit the parent feature flag, default-OFF preserved):
1. **In-memory ring buffer** `runtime.divergence_history: dict[str, deque[DivergenceHistoryEntry]]`, capped at `cfg.avatar_telemetry.divergence_history_size` (default 100). Volatile (restart wipes - acceptable v1 tradeoff). Lazy alloc per-agent + lazy-resize on config change.
2. **Single write site** - `apply_divergence_check` appends immediately after `divergence_results[agent_id] = result`. Inherits the single-call-site invariant from AD-722a; no new wiring touches trust/Hebbian.
3. **Read endpoint + UI panel** - new `GET /api/agent/{agent_id}/avatar-telemetry/divergence-history?limit=N` returns history (most-recent-first) + aggregate (count + percentage walked over `divergence_aggregate_window`). New `PanelDivergenceHistory` component in `SelfImageTab.tsx` polls every 5 s, renders the aggregate banner + a scrollable event list. Server pre-renders the OUTPUT-subject note string per entry so the AD-727 rule #8 phrasing test gates BOTH backend and frontend in one regex.

**In scope:** per-agent only (v1), in-memory ring buffer, HTTP poll surface, server-rendered note phrasing.
**Out of scope:** cross-crew / wardroom rollup (forward marker AD-722a-6 / [#615](https://github.com/seangalliher/ProbOS/issues/615)); on-disk persistence (AD-722a-5-a, file at retrospective); WS push channel for history (AD-722a-5-b); trend chart visualization (AD-722a-5-c).
**Status:** SHIPPED. Issue [#614](https://github.com/seangalliher/ProbOS/issues/614).
**Files:** `src/probos/avatars/divergence_detector.py` (new `DivergenceHistoryEntry`, buffer-append branch in `apply_divergence_check`), `src/probos/config.py` (2 fields + validator), `src/probos/runtime.py` (`self.divergence_history`), `src/probos/routers/agents.py` (new endpoint), `ui/src/components/profile/SelfImageTab.tsx` (new panel + payload types). Tests: `tests/test_ad722a_5_divergence_history.py` (9 backend cases) + `ui/src/__tests__/SelfImageTab.divergenceHistory.test.tsx` (3 vitest cases). Existing `ui/src/__tests__/SelfImageTab.test.tsx` updated minimally - `mockFetch` returns 503 for `/divergence-history` URLs and assertions filter via new `mainTelemetryCalls()` helper so existing call-count semantics stay equivalent.

### AD-730 -- Vision pipe-through for per-agent DMs (image-aware DMs)

**Date:** 2026-05-11  **Type:** Architecture Decision (capability extension)  **Status:** Forward marker (filed pending implementation prompt + wave slot).

**Problem.** AD-720d (Wave 139) shipped vision pipe-through for the main composer at `/api/chat` — images attached there route through the configured vision tier of `runtime.llm_client`. The per-agent DM path at `/api/agent/{id}/chat` (used by ProfileChatTab and by Counselor therapeutic DMs) has no equivalent. As of 2026-05-11 the `AgentChatRequest` model and the agent_chat route accept `attachment_ids` and pass extracted text + `[Captain attached an image (id=...)]` markers into the agent's `direct_message` intent (see chat.py mention branch + agents.py augmentation), but the receiving agent cannot actually **see** the image — it only knows one was attached.

**Decision (forward-marker shape).** Extend the DM dispatch in `routers/agents.py` so that when `attachment_ids` contains an image MIME, the agent's perception step runs through a vision-capable LLM tier instead of the standard text path. Three architectural choices to make at implementation time:

1. **Per-agent intent params shape.** Either (a) pass the multimodal `messages` array through `IntentMessage.params['vision_messages']` and have `CognitiveAgent._handle_direct_message` route to vision tier when present, or (b) extend `LLMRequest` consumption inside the agent's reply path with a new optional `attachment_blobs` field. Choice (a) keeps the agent free to interleave the image into its full instructions-based prompt; choice (b) is simpler but limits the agent to a single vision turn. Recommend (a).

2. **Tier selection inheritance.** Reuse `runtime.config.attachments.vision_tier` rather than introducing a per-agent vision tier setting. Agents inherit the same operational-vs-degraded gate as the main composer (AD-720d). Per-agent overrides are a follow-up if a crew role ever needs a different tier (e.g., a hypothetical Imaging Officer).

3. **Standing Orders integration.** When the receiving agent is shown an image, the perception turn should record a sensorium block in episodic memory tagged `"channel": "dm"` + `"attachment_kind": "image"` so the Counselor wellness pipeline and AD-722a divergence detector continue to see consistent inputs. No new EventType — ride existing `direct_message` event with an extra `has_image_attachment: True` data field.

**Out of scope (forward markers).**
- AD-730-1: vision support inside the WardRoom DM panel (`WardRoomThreadDetail` send path goes through `/api/agent/{id}/chat` already, so this should fall out for free, but needs a UI attach button on that surface — separate AD).
- AD-730-2: multi-image DMs (>=2 attachments) — vision LLM token budget concerns; default to first image only in v1.
- AD-730-3: image generation by agents in DM replies (agent attaches an image back). Requires a generation tier and storage-write capability; separate capability AD.
- AD-730-4: federation peer-to-peer vision DMs — inherits AD-480 governance review.

**Hard preconditions before shipping.** `runtime.config.attachments.vision_tier` operational. AD-722a divergence-detection consumer must be reviewed for behavioral changes when DM perception turn becomes multimodal (sensorium prompt expands).

**Files (anticipated).** `src/probos/routers/agents.py` (augmentation -> dispatch swap), `src/probos/cognitive/cognitive_agent.py` (direct_message handler accepts vision_messages), `src/probos/api_models.py` (no change — `attachment_ids` already present), tests: `tests/test_ad730_agent_chat_vision.py` (new).

**Status:** Forward marker. Filed via GH issue [#630](https://github.com/seangalliher/ProbOS/issues/630). Awaits wave-slot assignment + Architect implementation prompt.

---

### AD-731 - Content-Addressable Vision Payloads (closes #637, #639)
**Date:** 2026-05-11  `n**Type:** Architecture Decision (wire format / load-bearing invariant restoration)  `n**Wave:** 152

Replace inline base64 in `IntentMessage.params['vision_messages']` with content-addressable refs to the existing `AttachmentStore`. Bytes never cross the bus. Receiver dereferences from the local store inside the LLM client immediately before the HTTP POST. The bus carries SHA-256 + media_type (~70 bytes/image); the store carries the bytes.

**Problem (verified diagnostic baseline ΓÇö 2026-05-11).** AD-730 (Wave 151) packed Anthropic-shape `vision_messages` arrays containing inline base64 image bytes into `IntentMessage.params`. NATS request/reply serialization triggered #636 (1 MB allocation failure) when retry buffers accumulated the inline base64. BF-265 added a transport strip that prevented the crash but also stripped the receiver's view of `vision_messages` ΓÇö the agent's LLM call saw text only. BF-267 attempted to bypass NATS for local-process targets ("local-first dispatch"); it broke all DMs because the local handler is async and returns immediately, so `await handler(intent)` returned `None`. Reverted (commit `8b4b39f`).

The architectural error was not BF-265 (a correct emergency response to OOM) and not BF-267 (the local-first reflex was wrong-direction). The architectural error was **inline base64 in RPC messages.** AD-730 should have referenced the already-existing `AttachmentStore` (shipped AD-720) instead of inlining bytes.

**Decision: refs, not URLs, not base64.** Bus message format on the wire is content-addressable + provider-agnostic:
- Sender (`vision_dispatch.build_multimodal_messages`) emits `{type: image, source: {type: attachment_ref, sha256, media_type}}`.
- Receiver (`OpenAICompatibleClient._resolve_attachment_refs_for_openai`) walks each `messages[i].content` array and replaces `attachment_ref` source blocks with `base64` source blocks just before `httpx.AsyncClient.post` ΓÇö Anthropic-shape adaptation happens at the LLM-vendor boundary, NOT on the bus.
- Single-host attachment store assumption (Option A). v1 assumes all agent processes share the same filesystem path. Multi-host distribution (HTTP fetch, NATS Object Store) is explicitly deferred to AD-731a forward markers (#638).
- Missing refs degrade gracefully: image block replaced with a `failed_to_load_at_dereference` text marker; warning logged; never raises into the LLM call.

**Why (industry-comparison citations).** Every mature distributed system that carries large payloads through RPC converges on the same pattern: control plane carries refs/IDs, data plane carries bytes.
- **Ray / Dask object refs** ΓÇö distributed object stores accessed by ObjectRef; tasks pass refs, not data.
- **Erlang BEAM refs** ΓÇö opaque term references for cross-process value handles.
- **Anthropic API source types** ΓÇö the multimodal content-block schema accepts `base64`, `url`, and `file_id` source types; the API itself models refs as a first-class shape.
- **Model Context Protocol (MCP) resource handles** ΓÇö clients pass resource URIs to tools; bytes flow through a separate fetch.
- **Git** ΓÇö the entire object model is content-addressable (blob SHAs); the working tree dereferences on read.
- **IPFS** ΓÇö CIDs in the routing layer, bytes in the storage layer.
- **OCI image registries** ΓÇö manifests reference layer digests; layers are fetched out-of-band.

NATS just enforces the discipline earlier (1 MiB default) than transports without hard limits. The right response to "my payload is bigger than the transport budget" is **not** to weaken the transport or fork the dispatch path ΓÇö it is to fix the wire format.

**Why not BF-267's local-first.** Bypassing the standardized pub/sub bus for in-process targets means we maintain two dispatch code paths, each with different governance, episodic-log, consensus, and trust-scoring properties. The bus invariant ("all intents flow through the same path") is load-bearing; weakening it has compounding correctness costs over time. BF-267's specific failure mode (async-handler `await` returning `None`) is the surface symptom; the deeper issue is that the bus was correct and the message shape was wrong.

**See also: User-memory lesson 2026-05-11 ΓÇö "Don't change the architecture to fix a symptom."** Wave 151 BF-265 -> BF-267 sequence is now the canonical example. Before any prompt that proposes changing a load-bearing invariant to make a feature work, check whether a shared primitive (store, registry, knowledge base) already exists that the feature should be using instead. AD-730 ignored AD-720's existing store; AD-731 wires it.

**In scope (this AD).**
- Sender shape change (`vision_dispatch.py`).
- Receiver resolution (new `OpenAICompatibleClient._resolve_attachment_refs_for_openai`).
- Constructor parameter and deferred setter on `OpenAICompatibleClient` (Dependency Inversion on `AttachmentStore` Protocol).
- Public `ProbOSRuntime.attachment_store` property (delegates to `routers/chat.py:_get_attachment_store`).
- Wire-up in `__main__._boot_and_run` after runtime construction.
- BF-265 revert in `mesh/intent.py` (removed `_TRANSPORT_STRIPPED_PARAM_KEYS` and the strip branch).
- 12 new tests + invert assertions on the BF-265/BF-266/AD-730 fixtures.

**Out of scope (explicit Do-Not-Build list).**
- HTTP fetch for cross-host attachment distribution ΓÇö AD-731a-1 (#638 sub-marker).
- NATS Object Store integration ΓÇö AD-731a-2 (#638 sub-marker).
- Federation strip change ΓÇö pinned as a deliberate AD-731a forward marker because the receiving mesh may not have the local store.
- HXI / TypeScript UI changes ΓÇö wire format change is internal to the bus.
- `AgentChatRequest` model ΓÇö no API change.
- LLM tier system / retry / health-probe changes.
- Re-introducing local-first dispatch (BF-267 pattern) ΓÇö the fix is the wire format.
- Binding the bus message format to Anthropic's content-block schema ΓÇö `attachment_ref` is internal and provider-agnostic.

**Status:** SHIPPED. Closes #637 (AD-731 implementation) and #639 (AD-637z2 ΓÇö BF-265 transport strip removal auto-closes as a consequence). AD-731a remains open as the cross-host distribution forward marker (#638), with sub-markers AD-731a-1 (HTTP fetch), AD-731a-2 (NATS Object Store), and AD-731a-3 (mime-only fast path in sender).

**Files.** `src/probos/cognitive/vision_dispatch.py` (sender shape + observability log + drop base64 import), `src/probos/cognitive/llm_client.py` (constructor param + deferred setter + `_resolve_attachment_refs_for_openai` + `_call_openai` wiring), `src/probos/mesh/intent.py` (revert BF-265 strip), `src/probos/federation/bridge.py` (AD-731a forward-marker comment on the federation strip), `src/probos/runtime.py` (`attachment_store` property), `src/probos/__main__.py` (deferred-setter wiring after `ProbOSRuntime` construction), `tests/test_ad731_attachment_ref_wire_format.py` (new, 12 tests), `tests/test_bf265_transport_stripped_params.py` (inverted assertions + regression sentinel), `tests/test_bf266_vision_context_folding.py` and `tests/test_ad730_agent_chat_vision.py` (fixture shape flipped to `attachment_ref`).

### AD-732 - Dedicated Vision LLM Tier + Honest Degrade (closes #640)

**Date:** 2026-05-11
**Decision:** Promote `vision` to a fourth peer-tier of `fast`/`standard`/`deep`. `CognitiveConfig` gains 7 vision-tier fields (`llm_base_url_vision`, `llm_api_key_vision`, `llm_model_vision`, `llm_timeout_vision`, `llm_api_format_vision`, `llm_temperature_vision`, `llm_top_p_vision`) with the same Optional-defaults pattern as the text tiers. `tier_config("vision")` resolves through the same map-dict shape. `OpenAICompatibleClient` tracks vision in every per-tier state dict via a new module-level `_LLM_TIERS = ("fast","standard","deep","vision")` single-source-of-truth constant; the fallback chain `_TIER_ORDER = ["fast","standard","deep"]` deliberately excludes vision because text-only tiers cannot see images. `AttachmentsConfig.vision_tier` default flips from `"standard"` to `"vision"` (validator allow-set extended). When the vision tier is unconfigured OR unhealthy, `/api/chat` and `/api/agent/{id}/chat` return one of two operator-facing honest-degrade messages (`VISION_UNCONFIGURED_MESSAGE` or `VISION_UNHEALTHY_MESSAGE`) instead of the pre-AD-732 "Try again in a moment" stub. The agent-side path early-returns BEFORE intent dispatch ΓÇö the agent has no way to surface a missing endpoint to the crew, so the OS speaks for itself. OSS default: local Ollama + Qwen3.6 (`config/system.yaml` ships an active block pointing at `qwen3.6:27b` via Ollama's OpenAI-compatible endpoint; operator runs `ollama pull qwen3.6:27b`).

**Rationale.** AD-731 wired content-addressable refs onto the bus; BF-268 emitted the correct OpenAI `image_url` shape at the vendor boundary. Together they fixed the wire format, but the LLM still couldn't see images. Captain's repro (Ezri: "no image visible on my end") + `/api/chat` repro (gpt-4o describing "Visual Studio Code editor with open files") confirmed the **endpoint** was the missing piece. Root cause: the Copilot proxy ([gratajik/vscode-copilot-proxy](https://github.com/gratajik/vscode-copilot-proxy)) is a passthrough over `vscode.lm.selectChatModels(...).sendRequest(...)`. The VS Code Language Model API (a) does not pipe arbitrary user-supplied images through for free-form turns, (b) strips non-text content parts when building `LanguageModelChatMessage`, (c) returns 200 OK even when image content was dropped (no error signal), (d) re-injects VS Code's own editor context into the prompt. Direct testing 2026-05-11 against the proxy with three shapes (Anthropic `source.base64`, OpenAI `image_url` to Claude, OpenAI `image_url` to gpt-4o) all confirmed: no shape gets images to the model through that proxy. No client-side wire-format adjustment can fix this ΓÇö the vendor boundary for vision must point at an endpoint that can actually carry images.

**Architectural separation (three orthogonal concerns).**
- **AD-731 ΓÇö bus shape.** Provider-agnostic `attachment_ref` source blocks. Owned by `vision_dispatch.build_multimodal_messages`. The bus carries refs; the store carries bytes.
- **BF-268 ΓÇö vendor adaptation.** OpenAI `image_url` vs Anthropic `source.base64` shape selection at the HTTP POST boundary. Owned by `llm_client._resolve_attachment_refs_for_openai` (and its Anthropic-shape sibling).
- **AD-732 ΓÇö endpoint selection.** Per-tier `base_url`/`model`/`api_key`/`timeout`/`api_format` for vision. Owned by `CognitiveConfig.tier_config("vision")` + `OpenAICompatibleClient._clients`. Vision is the fourth peer tier; the fallback chain deliberately excludes it (standard/deep cannot see images).

Three concerns, three sites, three ADs. SOLID-S applied at the AD scope, not just the class scope.

**See also: User-memory lesson 2026-05-11 ΓÇö "Don't change the architecture to fix a symptom."** AD-732 is the right outcome of that lesson applied at the endpoint layer: don't fork the wire format; fork the endpoint. The bus stays one shape; the vendor boundary stays one shape per provider; the endpoint becomes per-tier addressable. The earlier BF-267 reflex (bypass NATS for in-process targets) would have been a load-bearing invariant change to dodge a payload-shape problem; AD-731 fixed the shape and AD-732 fixed the endpoint, leaving the bus invariant intact.

**Honest-degrade routing semantic.** The chat/agents handlers gate on `(not is_vision_tier_configured(cfg, tier)) OR (tier_status != "operational")`. The two-clause gate is necessary: `get_health_status` reports 0 failures for an unconfigured vision tier (the connectivity short-circuit doesn't bump failure counters), so the operational check alone misses unconfigured. Two distinct messages because the remediations differ ΓÇö `VISION_UNCONFIGURED_MESSAGE` names config keys and `ollama pull qwen3.6:27b`; `VISION_UNHEALTHY_MESSAGE` asks the operator to restart the endpoint.

**In scope (this AD).**
- 7 new vision-tier fields on `CognitiveConfig` + `tier_config("vision")` resolution.
- `AttachmentsConfig.vision_tier` default flip + validator allow-set extension.
- `_LLM_TIERS` module-level constant + grep-replace of 12 hardcoded tier tuples in `llm_client.py`.
- Per-tier state dicts (failures, successes, request_timestamps, 429s) include vision.
- `check_connectivity()` short-circuits the vision tier to False without an HTTP probe when `llm_model_vision` is unset.
- `MockLLMClient.get_health_status` reports vision as operational (test scaffolding parity); text tiers stay offline (BF-108 invariant).
- `vision_dispatch.is_vision_tier_configured(cfg, tier_name)` helper.
- `VISION_UNCONFIGURED_MESSAGE` / `VISION_UNHEALTHY_MESSAGE` operator-facing constants.
- `/api/chat` and `/api/agent/{id}/chat` honest-degrade routing (early return, no LLM call, no intent dispatch).
- `config/system.yaml` documented commented-out vision-tier example block.
- 15 new tests + minimal updates to existing fixtures (test_per_tier_llm, test_bf069_llm_health, test_ad484_ux_adoption, test_ad720d, test_ad730).

**Out of scope (explicit Do-Not-Build list).**
- Per-agent vision tier overrides ΓÇö AD-732a forward marker.
- Autodetection of local Ollama on startup ΓÇö AD-732b forward marker.
- Hot-reload of vision tier config ΓÇö AD-732c forward marker.
- Vision tier participation in the `_TIER_ORDER` fallback chain.
- Changes to AD-731's `attachment_ref` shape.
- Changes to BF-268's `image_url` adaptation.
- Federation strip ΓÇö still AD-731a's concern.
- `image_generation` capability for agents ΓÇö AD-730-3 remains a separate concern.
- HXI UI changes.
- Multi-image DMs in v1 ΓÇö AD-730-2 forward marker stays open.
- Fallback to a different vision endpoint when the primary fails ΓÇö operator deploys redundancy at the endpoint layer (e.g., LiteLLM router).

**Status:** SHIPPED. Closes #640.

**Files.** `src/probos/config.py` (CognitiveConfig fields + tier_config map dicts + AttachmentsConfig default/validator), `src/probos/cognitive/llm_client.py` (`_LLM_TIERS` constant + grep-replace + vision short-circuit + docstring), `src/probos/cognitive/vision_dispatch.py` (`VISION_*_MESSAGE` constants + `is_vision_tier_configured` helper), `src/probos/routers/chat.py` and `src/probos/routers/agents.py` (honest-degrade routing), `src/probos/experience/commands/commands_llm.py` and `src/probos/__main__.py` (loop over 4 tiers in `/model` display + boot connectivity report + doctor), `config/system.yaml` (commented-out vision example), `tests/test_ad732_vision_tier.py` (new, 15 tests), `tests/test_ad720d_vision_pipethrough.py` / `tests/test_ad730_agent_chat_vision.py` / `tests/test_bf069_llm_health.py` / `tests/test_per_tier_llm.py` / `tests/test_ad484_ux_adoption.py` (fixture updates).

### AD-734 — Wire-shape contract test for the vision pipeline (Wave 153)

**Date:** 2026-05-12. **Status:** Shipped.

**Problem.** The BF-268 -> BF-274 -> BF-278 debug arc (vision DMs returning '(no response)') burned ~10 bugfix cycles diagnosing what was ultimately a silent wire-shape regression: `vision_dispatch.build_multimodal_messages` had reverted from the AD-731 `attachment_ref` source shape back to inline Anthropic-shape `source.base64` during the BF-274 multi-edit, and no automated test asserted the shape of the JSON crossing the LLM HTTP boundary. The defect was caught only by live capture against the running daemon (`tmp_capture_proxy.py`). This is the missing layer of testing for any multi-subsystem feature where the contract is the *shape on the wire*, not the API of any individual component.

**Decision.** Codify the live-capture work as a CI-runnable pytest at `tests/test_ad734_wire_shape_contract.py` that pins three invariants:

1. **Bus shape (sender):** `build_multimodal_messages` emits `{type: image, source: {type: attachment_ref, sha256, media_type}}` and NEVER inline base64 nor Anthropic `source.base64`.
2. **Resolver shape (boundary):** `OpenAICompatibleClient._resolve_attachment_refs_for_openai` rewrites that to the OpenAI chat-completions `{type: image_url, image_url: {url: data:<mime>;base64,...}}` shape, and the bus-shape `attachment_ref` MUST NOT survive past the resolver.
3. **Wire shape (HTTP POST):** End-to-end `_call_openai` via `httpx.MockTransport` captures the POST body and asserts `image_url` blocks (not `image`+source) reach the model endpoint. This is the exact observation tmp_capture_proxy.py made live during BF-278; it now runs in CI on every commit.

**Pre-commit smoke hook.** `.git/hooks/pre-commit` runs `test_ad734_wire_shape_contract.py` whenever any vision-pipeline file is staged (`vision_dispatch.py`, `llm_client.py`, `routers/chat.py`, `routers/agents.py`, `config/system.yaml`). ~30 lines of bash. Would have caught BF-274 and BF-278 at commit time instead of after a multi-day debug arc.

**Lesson locked in.** `Restore lost code` commits MUST be audited file-by-file with full diff review. Symptom-level checks (constants present) miss adjacent regressions (shape reverted). Contract tests on the wire boundary, not just on the component APIs, are the durable guard.

**Files.** `tests/test_ad734_wire_shape_contract.py` (new, 3 tests, ~230 lines). `.git/hooks/pre-commit` (+~20 lines vision-paths gate).

### AD-720d-3 — Episodic write for /api/chat vision-routed turns (Wave 154)

**Date:** 2026-05-12. **Status:** Shipped. **Closes** #565.

**Problem.** The vision branch of /api/chat short-circuits via return with the LLM response, bypassing the standard NL path's episodic write. Every captain vision DM was invisible to recall, dreaming, and Counselor wellness. Violates Design Principle #8 (every execution path stores an episode).

**Decision.** Insert an Episode store between the llm_client.complete call and the return inside the vision branch of routers/chat.py. Tier-2 log-and-degrade — store failure does not block the reply. agent_ids=['captain']; AnchorFrame channel='captain_chat' (distinct from per-agent 'dm'). Outcomes carry has_image_attachment, image_count, attachment_ids, llm_tier, llm_model so Counselor and AD-722a divergence analysis can filter on vision turns.

**Files.** `src/probos/routers/chat.py` (vision branch episode block). `tests/test_ad720d3_vision_episode_write.py` (new, 3 tests).


### AD-720d-2 — Per-agent vision_capable gating (Wave 154)

**Date:** 2026-05-12. **Status:** Shipped. **Closes** #564.

**Problem.** AD-730's vision pipe-through routed ALL image-bearing DMs through the vision tier regardless of the receiving agent's role or training. A security-sensitive agent, a low-trust probationary agent, or a future commercial-overlay variant could silently consume image content without operator review.

**Decision.** Add `vision_capable: bool = False` to `CrewProfile` (default False = transitional flag, Wave 10 convention #14). Seed Counselor + Architect to True via `config/standing_orders/crew_profiles/counselor.yaml` and `architect.yaml`. `CallsignRegistry.load_from_profiles` plumbs the flag into its in-memory profile dict so `runtime.callsign_registry.get_profile(agent_type).get('vision_capable', False)` is the single read site. `routers/agents.py:agent_chat` consults the flag before constructing `vision_messages` — when False, image_ids is cleared and the turn falls through to `augment_prompt_with_attachment_text` (text-only attachment markers). The Captain attached deliberately, so the agent sees an attachment marker — NOT an honest-degrade refusal (that's AD-732's role for unconfigured/unhealthy tiers).

**/api/chat is unchanged.** The /api/chat vision branch fires only for untargeted Captain turns (mentions are intercepted upstream and never reach the vision branch). The captain composes with the LLM, not an agent — no per-agent gate applies.

**Forward markers.** AD-720d-2.1 — Captain-approval workflow to enable vision_capable on a previously text-only agent (filed at wave close).

**Files.** `src/probos/crew_profile.py` (CrewProfile field + to_dict/from_dict + CallsignRegistry plumbing). `config/standing_orders/crew_profiles/counselor.yaml` + `architect.yaml` (seed flag). `src/probos/routers/agents.py` (gate before image_ids vision branch). `tests/test_ad720d2_vision_capable.py` (new, 5 tests).


### AD-730-5 — Per-agent_type vision tier override (Wave 154)

**Date:** 2026-05-12. **Status:** Shipped. **Closes** #635.

**Problem.** AD-730/732 routed every agent's image-bearing DM through a single global `attachments.vision_tier`. A future Diagnostician variant might want a medical-imaging specialist model; an Imaging Officer might want a satellite-imagery model. v1 needs the config plumbing without locking the choice of model.

**Decision.** Add `vision_tier_overrides: dict[str, str]` to `AttachmentsConfig` (default empty). Add pure helper `resolve_vision_tier_for_agent(attach_cfg, agent_type, default_tier) -> str` in `cognitive/vision_dispatch.py`. Three call sites consult it: `routers/agents.py:agent_chat` (passes `agent.agent_type`), `routers/chat.py:/api/chat` (passes `"` — vision branch is untargeted), and `cognitive/cognitive_agent.py:_decide_*` (passes `self.agent_type`). Health-validation: when the resolved override tier is unknown to the LLM client, `routers/agents.py` logs a warning and falls back to the default tier (tier-2 log-and-degrade). v1 only adds plumbing; no second LLM endpoint registered. Operators configure overrides via `config/system.yaml`.

**Out of scope.** Adding a second LLM endpoint to `system.yaml` (ops decision); registering a `vision_medical` tier (separate AD when a real model lands).

**Files.** `src/probos/config.py` (AttachmentsConfig field). `src/probos/cognitive/vision_dispatch.py` (helper). `src/probos/routers/agents.py` + `routers/chat.py` + `cognitive/cognitive_agent.py` (call sites). `tests/test_ad730_5_vision_tier_override.py` (new, 3 tests).


### AD-722e — Deterministic structured self-projection v1 (Wave 154)

**Date:** 2026-05-12. **Status:** Shipped. **Closes** #571.

**Problem.** Crew agents had INTEROCEPTION text built from AvatarTelemetrySnapshot but no structured self-description that surfaced the renderer pipeline version. AD-727 had ratified the safety stack but the capability was unbuilt.

**Decision.** New module `src/probos/cognitive/self_perception.py` (~125 lines). Exports:
- `PIPELINE_VERSION = '1.0.0'` module constant (bump on renderer-input-contract change).
- `@dataclass(frozen=True) SelfPerceptionProjection` — agent_id, timestamp, pipeline_version, four DSL summary fields, working_state, expression_resting, mouth_active, modulation_rate_factor, modulation_pitch_factor.
- `async project_self_perception(self_id, runtime) -> SelfPerceptionProjection | None` — reads same source-of-truth as renderer via `probos.avatars.telemetry.build_telemetry_snapshot`; returns None when telemetry disabled or snapshot unavailable (tier-2 log-and-degrade). Zero vision-LLM calls. Zero browser capture. Single agent parameter (AD-727 rule #7). No trust/Hebbian mutations (AD-727 rule #1).

**Wiring.** `CognitiveAgent._build_avatar_self_observation` appends a `pipeline_version: 1.0.0` line to the existing INTEROCEPTION block. Feature-flagged behind the existing `avatar_telemetry.inject_into_agent_context` flag — no new config flag.

**Tests.** `tests/test_ad722e_self_perception.py` (6 tests: dataclass shape, telemetry-disabled None, no-snapshot None, field round-trip, no-LLM-import double-guard, CognitiveAgent wiring). The 5 AD-727 safety_constraint tests now PASS (were RED in AD-727 commit; AD-722e turned them green).

**Forward markers.** AD-722e-2 (vision-LLM verification against backend-server-side render — AD-727 rule #4); AD-722e-3 (cross-crew visual perception — covered by AD-729 family at #587); AD-722e-4 (aesthetic-preference proposals extending AD-721d).

**Files.** `src/probos/cognitive/self_perception.py` (new). `src/probos/cognitive/cognitive_agent.py` (one-line pipeline_version append in `_build_avatar_self_observation`). `tests/test_ad722e_self_perception.py` (new, 6 tests).


### AD-730-1 — WardRoom DM attach button (Wave 154)

**Date:** 2026-05-12. **Status:** Shipped. **Closes** #631.

**Problem.** `/api/agent/{id}/chat` accepts `attachment_ids` (AD-730) and the main composer + ProfileChatTab both surface a paperclip + chip strip, but `WardRoomThreadDetail.tsx` (the WardRoom DM reply composer) had no attach UI. Captain could attach in two places but not the third — visible gap in the captain experience.

**Decision.** Mirror the ProfileChatTab paperclip + chip strip + hidden file-picker pattern in `WardRoomThreadDetail.tsx`. Same SVG paperclip (`strokeWidth: 1.5`, amber on hover/active, dim default). Hidden file input triggered by the paperclip button. Chip strip above the textarea shows pending attachments with × removal. Send body includes `attachment_ids: pendingAttachments.map(a => a.attachment_id)`. Pending attachments reset after every send (success OR failure) so the chip strip never persists stale state. UI gated by `isDm && targetAgentId` — non-DM (channels) view never renders the paperclip.

**Forward markers.** AD-730-1.1 — drag-and-drop + paste-image in WardRoomThreadDetail (filed at wave close).

**Files.** `ui/src/components/wardroom/WardRoomThreadDetail.tsx` (paperclip + chip strip + upload helpers + attachment_ids in submit body). `ui/src/__tests__/WardRoomThreadDetail.attach.test.tsx` (new, 3 Vitest tests: paperclip-hidden-in-non-DM, paperclip-visible-in-DM, attachment_id-flows-to-chat-body).



### AD-719c — @-picker keyboard navigation (Wave 154)

**Date:** 2026-05-12. **Status:** Shipped. **Closes** #548.

**Problem.** AD-719 shipped the @-picker with Enter + Esc only; ↑/↓/Tab were explicitly deferred as forward marker AD-719c. Mouse-only navigation of an 8-row popover is awkward for power users (Captain composes most multi-mention turns via keyboard).

**Decision.** Add ArrowDown / ArrowUp / Tab cases to `IntentSurface.handleKeyDown`. ArrowDown advances `pickerIndex` modulo `pickerMatches.length`; ArrowUp wraps to last on underflow. Tab confirms the highlighted row (mirrors Enter behavior). Picker rows gain a `data-picker-index` attribute for tests and for a new `useEffect` that calls `scrollIntoView({ block: 'nearest' })` on the highlighted row as `pickerIndex` advances. Guard `scrollIntoView` with `typeof === 'function'` because JSDOM does not implement it; tests assert `pickerIndex` state, not scroll position.

**Files.** `ui/src/components/IntentSurface.tsx` (handleKeyDown branches + data-picker-index attribute + scroll-into-view useEffect). `ui/src/__tests__/IntentSurface.pickerKeyboard.test.tsx` (new, 4 Vitest tests: ArrowDown advance, ArrowUp wrap, Tab confirms third row, Enter backward-compat).


### AD-718d-1 — Voice modulation activity indicator (Wave 154)

**Date:** 2026-05-12. **Status:** Shipped. **Closes** #553.

**Problem.** AD-718d (emotional voice modulation) shipped the modulation logic without a visible affordance. Operator cannot tell whether modulation is active for a given agent during a session. Indicator was deferred as forward marker because the ProfileChatTab Vitest harness scope would have pushed AD-718d past its blast radius.

**Decision.** New `ui/src/components/profile/ModulationIndicator.tsx` (~75 lines). Stroke-only three-bar audio glyph (HXI Principle #3); amber `#f0b060` active / dim `#666680` idle (HXI palette); 1.2s `transform: scale()` keyframe pulse on active state (HXI Principle #4 — motion communicates state). Subscribes to `onSpeechEvent` from `audio/voice`; pulses on `start` with matching `agent_id`, fades on `end`, ignores events for other agents. Mounted in `ProfileChatTab` immediately after the existing per-agent Speak toggle. Existing `ProfileChatTab` Vitest mocks updated to include a no-op `onSpeechEvent` so the transitive mount does not break unrelated coverage.

**Forward marker.** Per-agent listener bucket keyed by `agent_id` in `voice.ts:_fire` — current implementation registers one global listener per ModulationIndicator mount; acceptable at v1.

**Files.** `ui/src/components/profile/ModulationIndicator.tsx` (new). `ui/src/components/profile/ProfileChatTab.tsx` (import + mount adjacent to Speak toggle). `ui/src/__tests__/ModulationIndicator.test.tsx` (new, 2 Vitest tests: pulses for matching agent, ignores other agents). `ui/src/__tests__/ProfileChatTab.test.tsx` and `ui/src/__tests__/ProfileChatTabVoice.test.tsx` (voice mock extended with no-op `onSpeechEvent`).


### AD-730-1-1 — Drag/drop + paste-image in WardRoomThreadDetail (Wave 154)

**Date:** 2026-05-12. **Status:** Shipped. **Closes** #646. **Pre-flight:** #647 closed as duplicate of #646.

**Problem.** AD-730-1 shipped the file-picker path in `WardRoomThreadDetail` (Wave 154 commit `2413bf6d`). Paste from clipboard and drag-drop — the two ergonomic input modes that `IntentSurface` has supported since AD-720/AD-720a — were missing on the WardRoom DM reply composer.

**Decision.** Add `handlePaste` to the textarea (`onPaste`) and `handleDrop` / `handleDragOver` to the reply-input wrapper `<div>` (sibling of the chip strip — drops on the chip strip don't register; acceptable degradation tracked as forward marker AD-730-1-2). Pasted clipboard image blobs have no filename, so the handler synthesizes `pasted-<timestamp>.<ext>` (with a regex sanitizer for nontrivial MIME suffixes like `svg+xml`) before calling the existing `uploadAttachment(file: File)` helper. The shared helper's `ALLOWED_ATTACHMENT_MIMES` + `MAX_ATTACHMENT_BYTES` guards apply uniformly to picker / paste / drop. Server-side `/api/chat/attachments/multipart` is the actual MIME/size enforcement. Both new handlers early-return when `isDm && targetAgentId` is false so non-DM (channels) view drops are silently ignored.

**Forward markers.** AD-730-1-2 — visible drop-zone hover state.

**Files.** `ui/src/components/wardroom/WardRoomThreadDetail.tsx` (handlePaste / handleDrop / handleDragOver + wiring on textarea + reply container). `ui/src/__tests__/WardRoomThreadDetail.attach.test.tsx` (extended with AD-730-1-1 describe block: +3 Vitest tests — paste image triggers upload, drop image triggers upload, paste plain text no upload).


### AD-720d-1 — Multi-image batch send + per-attachment timing (Wave 154)

**Date:** 2026-05-12. **Status:** Shipped. **Closes** #563.

**Problem.** `build_multimodal_messages` already accepts N attachment_ids and emits N image content blocks — multi-image batches work at the wire level. What was missing: (1) per-attachment latency in the episode outcome so dreaming/recall can correlate latency with image count, (2) partial-resolve telemetry (`failed_image_count`) when individual attachments fail to load, (3) test coverage for N>=3, and (4) a soft operator warning when image count exceeds a configurable budget.

**Decision.** Change `build_multimodal_messages` return signature from `(messages, image_ids)` to `(messages, image_ids, per_attachment)` where `per_attachment` is a list of `{attachment_id, mime, resolve_ms, ok}` records — one per input attachment_id, in input order. `_resolve_one` is wrapped in `time.monotonic()` boundaries via a `_timed_resolve` inner coroutine inside the existing `asyncio.gather`. The ~95-line zip-loop body (AD-731 ref-shape emission with BF-278 restoration note, PDF stub, three-tier text-extraction error handling) is preserved verbatim; only the loop header changes (adds `resolve_ms` to the unpack) and one `per_attachment.append({...})` line is added at the top of the body.

Three production destructure sites updated in the same commit: `routers/chat.py:300`, `routers/agents.py:914`, `cognitive/vision_dispatch.py:294` (internal `augment_prompt_with_attachment_text` discards the new element as `_per`). Four test destructure sites updated identically: 3 in `test_ad731_attachment_ref_wire_format.py`, 1 in `test_ad734_wire_shape_contract.py`. The `_bmm` mock callbacks in `test_ad730_agent_chat_vision.py` (8 sites) and `test_ad732_vision_tier.py` (2 sites) extended with the empty third element.

Episode outcomes (`routers/chat.py` `captain_chat_vision` and `routers/agents.py` `direct_message`) gain three new fields: `image_count` recomputed from `per_attachment` (counts successful image-mime resolves; previously `len(image_ids)`), `failed_image_count`, and `per_attachment_timing` (the full list — small dict per attachment, no inline base64; preserves AD-731 `IntentMessage.params` size invariant).

New `AttachmentsConfig.multi_image_warn_threshold: int = 5` triggers a Tier-2 log warning when a single vision turn exceeds the threshold. Log-only, never blocks or truncates. Operators disable by setting to `0`. Logged `attachment_ids` capped at first 10 entries for log hygiene with large batches.

**What this does NOT change.** AD-731 ref-shape (no inline base64 anywhere). AD-732 honest-degrade. ModelRouter, cache, rate-limiter, vision tier health probe. No new HTTP shape on the LLM side. No UI changes.

**Forward markers.** AD-720d-1.1 — context-budget truncation policy when image count exceeds the warn threshold (v1 only warns, never truncates).

**Files.** `src/probos/cognitive/vision_dispatch.py` (`import time` + return signature + `_timed_resolve` + per-attachment records + internal caller `_per` discard). `src/probos/routers/chat.py` (destructure + warn-threshold log + episode outcomes enrichment). `src/probos/routers/agents.py` (init `per_attachment` at line 894 + destructure + warn-threshold log + DM episode outcomes enrichment). `src/probos/config.py` (`multi_image_warn_threshold` field on `AttachmentsConfig`). `tests/test_ad720d_1_multi_image.py` (new, 5 boundary tests: 3-image happy path, per-attachment record count, partial-resolve, empty input, warn-threshold caplog). `tests/test_ad731_attachment_ref_wire_format.py` + `tests/test_ad734_wire_shape_contract.py` (destructure adapted). `tests/test_ad730_agent_chat_vision.py` + `tests/test_ad732_vision_tier.py` (mock callbacks updated).


### AD-724-1 + AD-724-2 + AD-724-5 — DM sanity gate hardening (Wave 154)

**Date:** 2026-05-12. **Status:** Shipped. **Closes** #627, #628, #629.

**Problem.** Three forward markers from the AD-724 family (Wave 150) that the DM sanity gate left open: (1) the gate never retries on rejection — short or orphaned-tag replies just log a warning and ship; (2) repetition detection is exact-prefix only, so trivial whitespace/punctuation churn defeats it (#628); (3) the gate runs only on the DM one-shot path — WR/chain `[REPLY]` body cleaning hand-rolls its own BF-120 strip via inline `re.sub` and skips the orphaned-tag / length-floor / repetition checks entirely (#629).

**Decision.**

- **AD-724-1 (#627).** Add `should_retry: bool` to `DmSanityResult`. `process()` computes it from the intersection of fired warning names and `config.retry_warnings` (default `["length_floor", "orphaned_tag"]`), gated by `config.retry_on_rejection` (default `True`). The DM caller in `routers/agents.py` honors `should_retry` with exactly one re-dispatch — original Captain text plus a `[SYSTEM_HINT: ...]` suffix listing the fired warning names. The retry's response is gated AGAIN, but never triggers a second retry; bounded loop guarantee. `intent_bus.send` failure on the retry is a Tier-2 log-and-degrade (ships the original reply).

- **AD-724-2 (#628).** Replace exact-prefix repetition with stdlib `difflib.SequenceMatcher` ratio over a normalized form (lowercase, structured-tag noise stripped, whitespace collapsed). Threshold configurable via `repetition_similarity_threshold` (default `0.85`). Exact-prefix check stays as the fast path; similarity only runs when prefix differs. License hygiene: `pip show rapidfuzz` returned 1 — stdlib only.

- **AD-724-5 (#629).** New module-level `apply_dm_sanity(runtime, agent_id, text) -> DmSanityResult` helper. Fetches the gate from `runtime.dm_sanity_gate`; returns a no-op result when the gate is absent OR is not a real `DmSanityGate` instance (the `isinstance` check protects `MagicMock`-style test runtimes that auto-create attributes). Imported at module top of `proactive.py` and called from `_extract_and_execute_actions` (replacing the inline BF-120 `re.sub` pair at lines 2517–2518) and `_extract_and_execute_replies` (just before `_strip_bracket_markers` at line 3403). WR/chain reply bodies now get the same orphaned-tag / repetition / length-floor visibility as DM one-shots. The function's own scope does not introduce control flow — never blocks, never retries on the WR path; that semantic stays DM-only.

**Cluster invariant.** Both copies of `DmSanityGateConfig` (`cognitive/dm_sanity_gate.py:49` and `config.py:3236`) extended identically with the three new fields (`repetition_similarity_threshold`, `retry_on_rejection`, `retry_warnings`). `from pydantic import Field` added to `dm_sanity_gate.py:22` (`config.py` already had it). Cluster invariant from the AD-724 archive prompt preserved: do not split DmSanityGate / DmSanityGateConfig / DmSanityResult across multiple files.

**What this does NOT change.** Strict-mode (Tier-3 propagate) stays forward-marker AD-724-3. Repetition cache poisoning across the retry boundary is a documented deferral (forward marker for follow-up if false positives surface in production). No NATS / transport / event-type / consensus / agent-side changes.

**Files.** `src/probos/cognitive/dm_sanity_gate.py` (3 new fields on `DmSanityGateConfig` + `Field` import + `TYPE_CHECKING` `RuntimeOS` guard + `_normalize_for_repetition` + `_similarity_ratio` + revised `check_repetition` + `should_retry` on `DmSanityResult` + `apply_dm_sanity` module helper). `src/probos/config.py` (mirror the 3 new fields on the `DmSanityGateConfig` duplicate at line 3236). `src/probos/routers/agents.py` (one-shot retry block after `sanity_gate.process()` at line ~1108). `src/probos/proactive.py` (module-top `apply_dm_sanity` import + call at `_extract_and_execute_actions` line 2514 replacing inline `re.sub` + call at `_extract_and_execute_replies` line 3403 before `_strip_bracket_markers`). `tests/test_ad724_dm_hardening.py` (new, 12 boundary tests covering all three sub-ADs).

### AD-721b-1 — Server-side rhubarb-lip-sync backend (Wave 155)

**Date:** 2026-05-12. **Status:** Shipped. **Closes** #559. **Parent AD:** AD-721b v1 (Wave 138).

**Problem.** AD-721b v1 (Wave 138) drives the five VRoid vowel morphs from a text-only heuristic: `buildHeuristicTrack(text, {rate})` in `ui/src/audio/lipSyncTrack.ts`. "Cat" and "cot" produce identical viseme schedules because the heuristic does not see phonemes or audio timing. Counselor (Echo) flagged this on the 2026-05-09 follow-up.

**Decision.** Add a server-side backend that wraps the MIT-licensed `rhubarb-lip-sync` binary (verified MIT via `gh api repos/DanielSWolf/rhubarb-lip-sync/license` -> `key: mit`). Operator drops the binary at `tools/rhubarb/rhubarb` (.exe on Windows); `/tools/` is gitignored. Default `lipsync.backend = "heuristic"` preserves v1 behavior bit-for-bit. Operator opts in with `lipsync.backend: "rhubarb"`.

**9 -> 15 viseme mapping.** rhubarb emits the Preston Blair 9-set; the renderer consumes the Oculus 15-set. The wire boundary maps with explicit fallback to `sil` for any unknown shape (forward-compat). Consonant-side mapping is intentionally lossy because the renderer uses vowel morphs only.

**Honest-degrade (Tier-2).** Every callable in `rhubarb_backend.py` returns False / None / [] on failure with a WARNING log; never raises. Endpoint returns `{backend: "heuristic", frames: []}` when the backend produces nothing — the client (AD-721b-2) treats the empty schedule as the cue to fall through to v1 heuristic. Speech never stops animating because of a viseme failure.

**Section 0.5 — Validation seam.** Browser-captured audio (AD-721b-2) uploads via `POST /api/chat/attachments/multipart` which delegates to `_validate_and_store_attachment`. Three parallel registries needed audio MIME entries: `AttachmentsConfig.allowed_mime_types` (config.py), `_SIGNATURES` (attachments/mime.py), and `_MIME_TO_EXT` (attachments/filesystem_store.py). The third was a Builder-discovered completion of Section 0.5: the prompt called out the first two; the third is required for the store to actually persist audio blobs.

**AD-731 invariant.** Audio bytes flow through `AttachmentStore` as content-addressable SHA-256 refs. The endpoint body carries only the 64-char hex ref; no inline base64 anywhere.

**Subprocess discipline.** `asyncio.create_subprocess_exec` with absolute path, `-f json` for structured output, 30s default timeout, full stderr capture for diagnostic logs. Never `shell=True`. `proc.kill()` on timeout to prevent zombies.

**What this does NOT change.** No client-side code; AD-721b-2 ships the consumer wiring. No change to `_validate_and_store_attachment` / `_get_attachment_store` / `AttachmentStore` Protocol. No federation. No caching. No streaming.

**Files.** `src/probos/avatars/rhubarb_backend.py` (new — wrapper + mapping + `VisemeFrame`). `src/probos/routers/avatars.py` (new — `POST /api/avatars/lipsync`). `src/probos/config.py` (new `LipSyncConfig` model + `SystemConfig.lipsync` field + extended `AttachmentsConfig.allowed_mime_types`). `src/probos/attachments/mime.py` (extended `_SIGNATURES` with EBML + RIFF/WAVE). `src/probos/attachments/filesystem_store.py` (extended `_MIME_TO_EXT` with audio mappings). `src/probos/api.py` (router registration). `tests/test_ad721b1_rhubarb_backend.py` (new — 16 boundary tests).

**Operator action item.** To exercise the rhubarb path end-to-end, download the platform binary from https://github.com/DanielSWolf/rhubarb-lip-sync/releases, drop it at `tools/rhubarb/rhubarb(.exe)`, set `lipsync.backend: rhubarb` in `config/system.yaml`, restart. Without the binary, the system stays on the AD-721b v1 heuristic — zero behavior change.

### AD-721b-2 — Browser-side real-audio capture for lip-sync (Wave 155)

**Date:** 2026-05-12. **Status:** Shipped. **Closes** #560. **Parent AD:** AD-721b v1 (Wave 138). **Depends on:** AD-721b-1 (same wave, Group A).

**Problem.** AD-721b-1 ships the server-side rhubarb wrapper, but the missing piece is the audio bytes. The browser's built-in TTS (`SpeechSynthesisUtterance`) is the only voice path today; `ui/src/audio/speechAmplitude.ts:1-7` documents the constraint that most browsers do NOT expose SpeechSynthesis output through Web Audio without vendor-specific hacks. Without audio bytes, the rhubarb backend has nothing to align against.

**Decision.** Ship the browser-side capture infrastructure as an **always-on, best-effort** path. Three pieces: pure `lipSyncCapture.ts` (capture + upload), the `useLipSyncCapture` React hook (subscribes to `onSpeechEvent`), and a CrewVRM consumer wire that prefers rhubarb frames over the v1 heuristic when present.

**Honest-degrade chain (4 stages).** (1) Capture short-circuits to `null` when `MediaRecorder` produces 0 bytes — every browser that does not route SpeechSynthesis. (2) When capture succeeds but rhubarb isn't enabled, the server returns `{backend: "heuristic", frames: []}`. (3) When rhubarb is enabled but the binary is missing, AD-721b-1's `generate_visemes` returns `[]` and the endpoint degrades the response to `heuristic`. (4) CrewVRM treats every `frames.length === 0` identically: fall through to `buildHeuristicTrack` (AD-721b v1) and then to the AD-721 D5 amplitude path. Speech never stops animating.

**AD-731 invariant.** The captured Blob uploads via the existing AD-720a multipart endpoint and produces a 64-char hex sha256. The lipsync request body is `{"attachment_id": <sha256>}` — never inline base64. Test #3 in the capture test file asserts this invariant explicitly (parses the second fetch's body and confirms `attachment_id` is present while `audio_bytes` / `blob` / `base64` are absent).

**Always-on framing.** The hook is hardcoded `enabled: true` at the CrewVRM call site. No config-fetch endpoint is added by this AD. The wasted work on browsers that don't route SpeechSynthesis is bounded by the 0-byte short-circuit before the multipart upload. The `enabled` parameter is preserved in the hook signature for future use (e.g. an HXI Captain-facing toggle); production today does not exercise the `false` branch.

**Browser API limitation acknowledged.** This AD ships **infrastructure**, not a universal feature. The day a browser ships routable SpeechSynthesis or ProbOS adopts a server-streamed TTS path (forward marker AD-721b-2.3), this hook lights up. Today the regression test (`CrewVRM.realAudioFallback.test.tsx`) confirms the heuristic fallback is preserved bit-for-bit — operators see zero behavior change until upstream routability lands.

**What this does NOT change.** `buildHeuristicTrack` / `lipSyncTrack.ts` are bit-for-bit identical. `voice.ts` is untouched (the existing `'start' | 'end' | 'boundary'` event set is unchanged). No new TTS path. No new npm dependencies (Web Audio + MediaRecorder + fetch + FormData are platform standards). No HXI Captain-facing UI surface.

**Files.** `ui/src/audio/lipSyncCapture.ts` (new — capture + upload + `LipSyncFrame` / `LipSyncResponse` / `CaptureCapability` types). `ui/src/audio/useLipSyncCapture.ts` (new — React hook). `ui/src/components/profile/CrewVRM.tsx` (consumer wire: `useLipSyncCapture` call, `realFramesRef`, `_sampleRhubarbFrames` helper, per-frame preference check, `lipsync.reset()` on utterance end). `ui/src/audio/__tests__/lipSyncCapture.test.ts` (4 pure tests). `ui/src/audio/__tests__/useLipSyncCapture.test.tsx` (3 hook tests). `ui/src/__tests__/CrewVRM.realAudioFallback.test.tsx` (1 regression test, co-located with the existing CrewVRM tests at `ui/src/__tests__/` — the prompt's path (`ui/src/components/profile/__tests__/`) was based on a pass-1 review assertion that did not match the live codebase).

### AD-735 — Per-agent volume slider in agent profile card (Wave 156)

**Date:** 2026-05-13. **Status:** Shipped. **Closes** #527. **Parent AD:** AD-718 (per-agent voice profile).

**Problem.** The `VoiceProfile.volume` field has been on `CrewProfile` since AD-718 (`crew_profile.py:108`), is round-tripped via `SetVoiceProfileRequest` (`api_models.py:243`) and `PUT /api/agents/{agent_id}/voice-profile` (`routers/agents.py:236`), is in the TS store type, and is applied at playback time (`ui/src/audio/voice.ts:139`, `utterance.volume = effective.volume ?? 0.8`). The UI never exposed a slider — Captain had no way to lower one chatty agent without muting the bridge.

**Decision.** Add one Volume slider row in `ProfileInfoTab.tsx` between Rate and Wake-phrase, mirroring the Pitch/Rate slider pattern verbatim — same `onMouseUp` / `onTouchEnd` persistence semantics, same label width, native `<input type="range">`. Inline SVG speaker glyph (`strokeWidth: 1.5`, amber when audible / dim when muted) per HXI Design Principle #3 — no emoji. Numeric display is percent (`Math.round(value * 100)%`) rather than raw 2-decimal because volume is a perceptual ratio that reads more naturally as 70% than 0.70 (Pitch/Rate stay as raw decimals because octave-shift and time-stretch are physically meaningful as ratios).

**What this does NOT change.** Wire shape unchanged (`SetVoiceProfileRequest.volume` already exists). VoiceProfile validators unchanged (`__post_init__` already clamps to `[0.0, 1.0]`). Emotional modulation composition unchanged — `applyEmotionalModulation` still multiplies onto the baseline volume, so lowering the slider lowers BOTH baseline and modulated outcomes proportionally (desired). AD-718a proposal flow untouched. AD-731 attachment invariant respected — no bus/RPC/attachment changes.

**Tests (+5 Vitest).** `ui/src/components/profile/__tests__/ProfileInfoTab.volumeSlider.test.tsx` — default 0.8 → 80%, persisted value 0.35 → 35%, persist via PUT on mouse-up, in-range boundary round-trip (0 and 1), accessible label via `getByRole('slider', { name: 'Volume' })`.

**Files.** `ui/src/components/profile/ProfileInfoTab.tsx` (insertion of Volume slider row). `ui/src/components/profile/__tests__/ProfileInfoTab.volumeSlider.test.tsx` (new).

### AD-736 — Mic-permission UX polish for wake-word loop (Wave 156)

**Date:** 2026-05-13. **Status:** Shipped. **Closes** #558. **Parent AD:** AD-705 (always-on wake-word voice loop).

**Problem.** AD-705's wake-word loop already detected three fallback reasons (onnx_load_failed, mic_permission_denied, speech_recognition_unavailable) but the only surface was `_emitFallbackToast` writing to `console.warn`. Captain hits "Voice on" → permission popup → "Block" → nothing visible happens, no path forward unless DevTools is open. Additionally, no current state distinguished `denied` (active user refusal — actionable: click the address-bar icon) from `unavailable` (no hardware / no SR support — actionable: plug in a mic, then refresh).

**Decision.** Three pieces:
1. **State machine extension** in `wakeWord.ts`: new exported `MicPermissionState` enum (`pending` / `granted` / `denied` / `unavailable`) separate from `WakeWordState` (the wake loop can be `off` for non-mic reasons too), with `onMicPermissionState` subscribe API + `getMicPermissionState` synchronous read. Fires the current state synchronously on subscribe so consumers don't need a separate getter call.
2. **Pre-flight feature detect** at `startWakeWordLoop` using `navigator.mediaDevices.enumerateDevices()`: distinguishes "no microphone hardware" from "permission denied." If `enumerateDevices` is unavailable (Safari < 14, plain HTTP non-loopback) or rejects, fall through optimistically — the SR onerror path will still catch denial. Adds `audio-capture` SR-error handling for hardware-disconnect/in-use mid-session.
3. **`MicPermissionHint.tsx` component** mounted once at the `App.tsx` HXI root (adjacent to `<AgentTooltip />`). Renders only on `denied`/`unavailable`; `denied` shows an instructional hint ("Click the microphone icon in your browser's address bar to enable it, then refresh") with a dismiss × button. `unavailable` shows a dim mic with slash and a non-dismissible label. Dismissal sticky via `localStorage[hxi_mic_hint_dismissed]`.

**Inline SVG only, no emoji.** Mic glyph uses `strokeWidth: 1.5`, `strokeLinecap: round`, amber when audible / dim when denied or unavailable. Slash line drawn only in `unavailable` state (mirrors muted-speaker convention in `DecisionSurface.tsx`). Dismiss button is U+00D7 multiplication sign, not an emoji. HXI Design Principle #3 honoured.

**No retry button in v1.** The hint already tells the Captain what to do; a retry button would re-prompt and immediately fail in Chrome's permanent-deny state. Refresh after granting is the canonical recovery path.

**What this does NOT change.** Wake-word algorithm (ONNX path, substring fallback, transcript pump) unchanged. `speechInput.ts` unchanged. `WakeWordState` enum unchanged. No new dependencies (`navigator.mediaDevices.enumerateDevices` is a Web API standard). No HTTPS requirement added — over plain HTTP non-loopback, `mediaDevices` is undefined and the optional-chain skips the probe (the SR error path still catches denial). AD-731 attachment invariant respected.

**Tests (+8 Vitest).** `ui/src/audio/__tests__/wakeWord.micPermission.test.ts` — 6 state-machine tests (initial pending; unavailable on SR-unsupported; unavailable on no-audioinput device; denied on not-allowed; granted on first transcript; subscribe-fires-synchronously). `ui/src/components/__tests__/MicPermissionHint.test.tsx` — 2 component tests (renders only for denied/unavailable; dismiss persists across remount).

**Files.** `ui/src/audio/wakeWord.ts` (state machine + listener API + pre-flight probe + onerror branch + _ingestTranscript promotion + _teardown reset + _resetForTests extension). `ui/src/components/MicPermissionHint.tsx` (new). `ui/src/App.tsx` (mount + import). `ui/src/audio/__tests__/wakeWord.micPermission.test.ts` (new). `ui/src/components/__tests__/MicPermissionHint.test.tsx` (new).

### AD-737 — Per-agent custom emotion taxonomy (Wave 156)

**Date:** 2026-05-13. **Status:** Shipped. **Closes** #612. **Parent ADs:** AD-722a (intent-vs-presentation divergence detector, shipped Wave 143), AD-722a-7 (manifest-driven intent rules, shipped Wave 144).

**Problem.** The v1 fixed 8-emotion set (warm / concerned / excited / apologetic / formal / playful / reassuring / neutral) is functional but flat. Counselor (Echo) cannot reach for "professional concern" distinct from raw `concerned` (more formal, less emotionally invested). Domain experts get one emotional knob per quadrant; they need finer-grained vocabulary mapped to known v1 behaviour. Expanding v1 globally would explode the manifest and break AD-722a-7's "schema fixed; deviations require an architecture-decision review" invariant.

**Decision.** Per-agent custom emotion taxonomy that LAYERS on the fixed 8:
1. New `EmotionProfile` dataclass in `crew_profile.py` with mandatory `inherits` (must be a v1 `EmotionalIntent` value) and additive `pitch_shift` / `rate_shift` / `volume_shift` (default 0.0, clamped to ±0.15). The parent emotion's rule fires; the delta composes on top.
2. New `custom_emotions: dict[str, EmotionProfile]` field on `CrewProfile` with max-8 cap and validators forbidding (a) collision with v1 names, (b) keys outside `^[a-z][a-z_]{0,29}$`, (c) >0.15 shift magnitude. Round-trips via `to_dict` / `from_dict`.
3. `parse_intent_self_tag` accepts a new `custom_emotions` kwarg (default `None` — backward compatible). A new `_resolve_intent_name` helper short-circuits on v1 names and resolves custom names through `inherits`.
4. `apply_voice_modulation` accepts `custom_emotions`; resolves the parent rule, layers the delta multiplicatively (`factor *= 1.0 + delta_shift`), and emits BOTH `intent_X` (parent rule name, required for `compute_divergence`'s `startswith('intent_')` filter to produce non-zero `match_score`) AND `custom_X` (observability tag).
5. `apply_divergence_check` looks up the agent's `custom_emotions` from `runtime.profile_store` (tier-2 log-and-degrade), re-parses with the palette, threads it through `apply_voice_modulation`, and **pre-resolves** the parsed intent to its v1 parent before calling `compute_divergence` (whose `INTENT_EXPECTED_RULES` table is keyed on v1 names; a raw custom name yields `frozenset()` and silently corrupts `match_score` to 0.0). The custom name is restored on the `DivergenceResult` via `dataclasses.replace` for downstream observability.
6. `_build_intent_self_tag_instruction` reads the agent's `custom_emotions` and renders `v1_set + sorted(custom_set)` in the LLM prompt. Token cost grows from ~10 to ~15-25 depending on palette size.

**Critical scoring fix (pass-1 review correctness invariant).** The naive "append only `custom_X`" shape would have silently set `match_score = 0.0` for every custom-emotion reply (the filter strips `custom_*`; `applied_set` becomes empty; Jaccard against expected becomes 0). The dual-tag (`intent_X` + `custom_X`) plus pre-resolution at `compute_divergence` together preserve the contract that "the math uses the parent." Test 8 (parent-equivalence) pins this: a zero-shift custom emotion inheriting from `concerned` produces identical `match_score` / `signed_divergence` / `magnitude` as `concerned` itself, both equal to 1.0.

**What this does NOT change.** `EmotionalIntent` enum, `INTENT_EXPECTED_RULES`, `INTENT_DIRECTION`, `_REQUIRED_INTENT_EMOTIONS`, and `modulation_manifest.json` are all unchanged — v1 set stays fixed. `_TAG_RE` already accepts `[a-zA-Z_]+`; no regex change. TS-side modulation (`voiceModulation.ts`) continues to use the manifest v1 INTENT_RULES — custom factors are computed server-side; the TS layer never sees the custom name (forward marker AD-737a for TS-side parity if wanted). `AvatarTelemetryConfig` unchanged; opt-in is per-agent via `CrewProfile.custom_emotions`. AD-731 attachment invariant respected.

**Tests (+8 pytest).** `tests/test_ad737_emotion_taxonomy.py` — (1) `inherits` must be v1, (2) ±0.15 shift bounds, (3) v1 name collision, (4) max 8 entries, (5) custom name parsed only when palette is passed, (6) modulation composes delta AND fired_rules contains BOTH `intent_X` and `custom_X`, (7) prompt builder includes custom names + all v1 names, (8) parent-equivalence (match_score / signed_divergence / magnitude equal to v1 parent; `match_score == 1.0`).

**Files.** `src/probos/crew_profile.py` (`EmotionProfile` dataclass, `_CUSTOM_EMOTION_NAME_RE`, `CrewProfile.custom_emotions` field + `__post_init__` validator + to/from_dict round-trip, `ClassVar` import). `src/probos/avatars/divergence_detector.py` (`_resolve_intent_name` helper, `parse_intent_self_tag` `custom_emotions` kwarg, `apply_divergence_check` profile_store lookup + dual-resolution + `intent_emotion` replacement). `src/probos/avatars/telemetry.py` (`apply_voice_modulation` `custom_emotions` kwarg, additive delta layering, dual-tag fired_rules emit, `snapshot_for_agent` caller wiring, `TYPE_CHECKING` import). `src/probos/cognitive/cognitive_agent.py` (`_build_intent_self_tag_instruction` dynamic taxonomy rendering). `tests/test_ad737_emotion_taxonomy.py` (new, 8 tests).

### AD-737 — Per-agent custom emotion taxonomy (Wave 156)

**Date:** 2026-05-13. **Status:** Shipped. **Closes** #612. **Parent ADs:** AD-722a (intent-vs-presentation divergence detector, shipped Wave 143), AD-722a-7 (manifest-driven intent rules, shipped Wave 144).

**Problem.** The v1 fixed 8-emotion set (warm / concerned / excited / apologetic / formal / playful / reassuring / neutral) is functional but flat. Counselor (Echo) cannot reach for "professional concern" distinct from raw `concerned` (more formal, less emotionally invested). Domain experts get one emotional knob per quadrant; they need finer-grained vocabulary mapped to known v1 behaviour. Expanding v1 globally would explode the manifest and break AD-722a-7's "schema fixed; deviations require an architecture-decision review" invariant.

**Decision.** Per-agent custom emotion taxonomy that LAYERS on the fixed 8:
1. New `EmotionProfile` dataclass in `crew_profile.py` with mandatory `inherits` (must be a v1 `EmotionalIntent` value) and additive `pitch_shift` / `rate_shift` / `volume_shift` (default 0.0, clamped to ±0.15). The parent emotion's rule fires; the delta composes on top.
2. New `custom_emotions: dict[str, EmotionProfile]` field on `CrewProfile` with max-8 cap and validators forbidding (a) collision with v1 names, (b) keys outside `^[a-z][a-z_]{0,29}$`, (c) >0.15 shift magnitude. Round-trips via `to_dict` / `from_dict`.
3. `parse_intent_self_tag` accepts a new `custom_emotions` kwarg (default `None` — backward compatible). A new `_resolve_intent_name` helper short-circuits on v1 names and resolves custom names through `inherits`.
4. `apply_voice_modulation` accepts `custom_emotions`; resolves the parent rule, layers the delta multiplicatively (`factor *= 1.0 + delta_shift`), and emits BOTH `intent_X` (parent rule name, required for `compute_divergence`'s `startswith('intent_')` filter to produce non-zero `match_score`) AND `custom_X` (observability tag).
5. `apply_divergence_check` looks up the agent's `custom_emotions` from `runtime.profile_store` (tier-2 log-and-degrade), re-parses with the palette, threads it through `apply_voice_modulation`, and **pre-resolves** the parsed intent to its v1 parent before calling `compute_divergence` (whose `INTENT_EXPECTED_RULES` table is keyed on v1 names; a raw custom name yields `frozenset()` and silently corrupts `match_score` to 0.0). The custom name is restored on the `DivergenceResult` via `dataclasses.replace` for downstream observability.
6. `_build_intent_self_tag_instruction` reads the agent's `custom_emotions` and renders `v1_set + sorted(custom_set)` in the LLM prompt. Token cost grows from ~10 to ~15-25 depending on palette size.

**Critical scoring fix (pass-1 review correctness invariant).** The naive "append only `custom_X`" shape would have silently set `match_score = 0.0` for every custom-emotion reply (the filter strips `custom_*`; `applied_set` becomes empty; Jaccard against expected becomes 0). The dual-tag (`intent_X` + `custom_X`) plus pre-resolution at `compute_divergence` together preserve the contract that "the math uses the parent." Test 8 (parent-equivalence) pins this: a zero-shift custom emotion inheriting from `concerned` produces identical `match_score` / `signed_divergence` / `magnitude` as `concerned` itself, both equal to 1.0.

**What this does NOT change.** `EmotionalIntent` enum, `INTENT_EXPECTED_RULES`, `INTENT_DIRECTION`, `_REQUIRED_INTENT_EMOTIONS`, and `modulation_manifest.json` are all unchanged — v1 set stays fixed. `_TAG_RE` already accepts `[a-zA-Z_]+`; no regex change. TS-side modulation (`voiceModulation.ts`) continues to use the manifest v1 INTENT_RULES — custom factors are computed server-side; the TS layer never sees the custom name (forward marker AD-737a for TS-side parity if wanted). `AvatarTelemetryConfig` unchanged; opt-in is per-agent via `CrewProfile.custom_emotions`. AD-731 attachment invariant respected.

**Tests (+8 pytest).** `tests/test_ad737_emotion_taxonomy.py` — (1) `inherits` must be v1, (2) ±0.15 shift bounds, (3) v1 name collision, (4) max 8 entries, (5) custom name parsed only when palette is passed, (6) modulation composes delta AND fired_rules contains BOTH `intent_X` and `custom_X`, (7) prompt builder includes custom names + all v1 names, (8) parent-equivalence (match_score / signed_divergence / magnitude equal to v1 parent; `match_score == 1.0`).

**Files.** `src/probos/crew_profile.py` (`EmotionProfile` dataclass, `_CUSTOM_EMOTION_NAME_RE`, `CrewProfile.custom_emotions` field + `__post_init__` validator + to/from_dict round-trip, `ClassVar` import). `src/probos/avatars/divergence_detector.py` (`_resolve_intent_name` helper, `parse_intent_self_tag` `custom_emotions` kwarg, `apply_divergence_check` profile_store lookup + dual-resolution + `intent_emotion` replacement). `src/probos/avatars/telemetry.py` (`apply_voice_modulation` `custom_emotions` kwarg, additive delta layering, dual-tag fired_rules emit, `snapshot_for_agent` caller wiring, `TYPE_CHECKING` import). `src/probos/cognitive/cognitive_agent.py` (`_build_intent_self_tag_instruction` dynamic taxonomy rendering). `tests/test_ad737_emotion_taxonomy.py` (new, 8 tests).


### AD-738 — Server-streamed TTS via Piper (Wave 157)

**Date:** 2026-05-13. **Status:** Shipped. **Closes** forward marker AD-721b-2.3 (filed at Wave 155 close; no GH issue). **Parent ADs:** AD-721b-1 (rhubarb backend, Wave 155), AD-721b-2 (browser real-audio capture, Wave 155), AD-731 (refs-not-blobs invariant), AD-735 (per-agent volume), AD-737 (per-agent emotion taxonomy).

**Problem.** AD-721b-2 shipped a browser audio-capture pipeline (`AudioContext` + `MediaStreamAudioDestinationNode` + `MediaRecorder`) so the server-side rhubarb backend (AD-721b-1) would receive real audio bytes and produce phonetic-accurate visemes. Chromium/Firefox/Edge do NOT route `SpeechSynthesisUtterance` through Web Audio — `MediaRecorder.ondataavailable` fires with 0 bytes every call. `captureUtteranceAudio` honest-degrades to `null` 100% of the time; rhubarb visemes never improve over the v1 heuristic. Wave 155 noted: "the day a browser ships routable SpeechSynthesis (or ProbOS adopts a server-streamed TTS path under a future AD), the capture path lights up automatically." That future AD is this one.

**Decision.** Make the SERVER the source of audio bytes. New `src/probos/audio/tts/` module with:
1. `TTSBackend` Protocol (`name`, `async synthesize(text) -> TTSResult | None`) + `TTSResult` frozen dataclass (`audio_bytes: bytes`, `mime: str`).
2. `PiperBackend` subprocess wrapper — `asyncio.create_subprocess_exec(<binary>, "--model", <model>, "--output_file", "-")` reads text on stdin, writes complete WAV (RIFF header + PCM data) to stdout. Tier-2 log-and-degrade on missing binary, missing voice model (requires BOTH `<name>.onnx` AND `<name>.onnx.json`), TimeoutExpired, non-zero exit, zero bytes, OSError. NEVER raises.
3. `NullBackend` — selected when `tts.backend = "browser"`; always returns `None`.
4. `select_backend(name, config)` factory with unknown-name → NullBackend honest-degrade.

New Pydantic `TTSConfig` in `config.py`: `enabled: bool = True`, `backend: Literal["browser", "piper"] = "browser"`, `binary_path: str = "tools/piper/piper"`, `voice_model: str = "en_US-amy-medium"`, `timeout_seconds: float = 10.0`. Wired into `Config` as `tts: TTSConfig = Field(default_factory=TTSConfig)`. **Default `backend = "browser"` means zero behaviour change for operators who don't install Piper.**

New endpoints on the existing `/api/avatars` router:
- `GET /api/avatars/tts/status` — `{"enabled": bool, "backend": str}`. One-time feature probe; browser caches in module-level state in `voice.ts`. Defensive against missing `tts` attr (returns `{enabled: False, backend: "browser"}`).
- `POST /api/avatars/tts` — body `{"text": str}`. Synthesizes, computes `sha256(audio_bytes)`, writes via `AttachmentStore.write(hash, blob, mime)` (canonical `chat.py:665-692` pattern), reuses `generate_visemes` if `lipsync.backend = "rhubarb"`, returns `{backend, audio_attachment_id, mime, visemes, duration_ms}`. AD-731 invariant: response carries content-addressable ref only; no inline base64 anywhere. Honest-degrade returns `{backend: "disabled", audio_attachment_id: null, mime: null, visemes: [], duration_ms: 0}`. Text length capped at 4096 chars (413); empty/whitespace text → 400.

Browser `voice.ts` `speakResponse` refactored. **Load-bearing zero-HTTP-per-utterance guarantee on default config (Captain decision #9):** module-level `_ttsStatus` cache populated by `_fetchTtsStatus` (dedup'd via `_ttsStatusInflight` promise); when cached `backend !== "piper"` OR fetch is unavailable, the function calls `_speakBrowserFallback` synchronously and returns. Probe fires exactly once per HXI session. On piper happy path: a synthetic `SpeechSynthesisUtterance` is constructed (preserving AD-718/AD-721 `'start'`/`'end'` listener shapes); `new Audio(/api/chat/attachments/<sha>)` plays the WAV with `volume = effective.volume` (AD-735) and `playbackRate = effective.rate`. `_activeAudio` reference cancels any in-flight audio from a prior call. Any failure (POST !ok, malformed response, audio.play() reject) invalidates the cache and falls back to SpeechSynthesisUtterance.

`useLipSyncCapture.ts` extended with `injectLipSyncFrames(frames, agentId?)` module-level injection registry. The piper path imports and calls this after each successful POST; every mounted hook with matching (or unset) `agentId` receives the frames via `_subscribeInjection`. The existing `onSpeechEvent` capture path remains as future-compat code for the day routable SpeechSynthesis ships.

**License Disposition.** Piper (`rhasspy/piper`) is **MIT** (verified `gh api repos/rhasspy/piper/license` → `"key": "mit"`, 2026-05-13). Default voice model `en_US-amy-medium` is **MIT** (verified at https://huggingface.co/rhasspy/piper-voices model card). Operator provides both at `tools/piper/piper(.exe)` and `tools/piper/voices/en_US-amy-medium.onnx[.json]`; the repo never ships either (`/tools/` already gitignored). No Python deps added (`pyproject.toml` unchanged); no npm deps added (`ui/package.json` unchanged). The browser uses Web Audio + `<audio>` + `fetch` — all platform standards. **Excluded by design:** Coqui XTTS v2 (CPL non-commercial — license hygiene rule blocker), Tortoise TTS (Apache 2.0 OK but 5-10s latency makes interactive use impossible — deferred to AD-738b GPU eval), ElevenLabs (proprietary cloud — commercial-overlay-only candidate).

**Operator smoke test.** Download `piper-windows-amd64.zip` from https://github.com/rhasspy/piper/releases; extract `piper.exe` to `tools/piper/piper.exe`. Download `en_US-amy-medium.onnx` + `.onnx.json` from https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/amy/medium; place at `tools/piper/voices/`. Edit `config/system.yaml`: add `tts:\n  backend: "piper"` AND `lipsync:\n  backend: "rhubarb"`. Restart runtime. Send a DM to any agent. Mouth syncs to real audio.

**Forward markers.** AD-738a (per-agent voice selection — `CrewProfile.voice_model` field + selector UI in `ProfileInfoTab.tsx` with license display; trigger: operator has > 2 voice models installed). AD-738b (GPU-accelerated TTS backend eval — Kokoro Apache 2.0 / StyleTTS2 MIT slot into the `TTSBackend` Protocol; trigger: operator with capable GPU requests higher fidelity). AD-738c (server-side voice modulation — apply AD-735 pitch/rate at the synthesis step rather than `<audio>` post-processing; closes the "no pitch on `<audio>`" limitation). AD-738d (TTS text caching layer — LRU keyed `(agent_id, voice, sha256(text))` → `attachment_id`; trigger: telemetry shows the same text re-synthesizing repeatedly).

**AD-738a/b/c/d renumbering (Wave 158).** The four forward markers reserved here are renumbered to **AD-738f / AD-738g / AD-738h / AD-738i** respectively. Wave 158 GH issues #650 / #651 / #652 reuse the freed `AD-738a / AD-738b / AD-738c` slots for hygiene-track work (orchestrator commit-count audit + voice.ts test gating / per-wave `npm run build` UI gate / rhubarb→Oculus viseme mapping polish). The renumbered Tier-4 work remains unshipped and is now tracked under the new names in `docs/development/roadmap.md:361-364`.

**What this does NOT change.** `SpeechSynthesisUtterance` fallback path preserved verbatim in `_speakBrowserFallback`; default config (`tts.backend = "browser"`) takes the fallback every call with ZERO POST traffic — only the one-time GET probe. AD-735 per-agent volume slider continues to drive both paths (`<audio>.volume` for piper, `utterance.volume` for fallback). AD-737 emotion taxonomy: `_resolveEffectiveProfile` calls `deriveAgentSignals` + `applyEmotionalModulation` exactly as today. AD-731 invariant: audio bytes via `AttachmentStore.write(sha256, blob, mime)`; response carries only the ref. AD-721b-1 rhubarb backend reused as direct internal call — no changes. AD-721b-2 browser-capture path stays as future-compat code. `/api/avatars/lipsync` endpoint unchanged. `config/system.yaml` no edit (Pydantic default authoritative).

**Tests (+26 pytest, +6 Vitest, +1 Vitest regression).** `tests/test_ad738_piper_tts.py` (26 tests): NullBackend, select_backend (browser/piper/unknown), PiperBackend (missing binary, missing voice model, empty text short-circuit, timeout, non-zero exit, zero bytes, happy path returning WAV), `_resolve_binary_path` Windows `.exe` auto-append, `_resolve_voice_model` requires both files, `_wav_duration_ms` canonical/malformed, status endpoint (browser default / piper / missing tts attr), POST endpoint (disabled / browser → no-op + no subprocess spawn / invalid text 400 / too-long 413 / honest-degrade when backend returns None / happy path with valid sha256 + AD-731 invariant assertions / heuristic lipsync omits visemes / invalid body 400). `ui/src/audio/__tests__/voice.serverTts.test.tsx` (6 tests): **load-bearing zero-POST test** (3 calls, exactly 1 GET probe, 0 POST, 3 speak calls), disabled-flip fallback, POST-error fallback, piper-happy `<audio>` play, viseme injection forwards to `useLipSyncCapture` (via real renderHook), second-call cancels first `<audio>`. `ui/src/audio/__tests__/useLipSyncCapture.test.tsx` (+1 test): `injectLipSyncFrames` updates hook state with matching agentId; mismatched agentId is ignored.

**Files.** `src/probos/audio/__init__.py` (new). `src/probos/audio/tts/__init__.py` (new — re-exports + `select_backend`). `src/probos/audio/tts/backends.py` (new — `TTSBackend` Protocol, `TTSResult` dataclass). `src/probos/audio/tts/null_backend.py` (new). `src/probos/audio/tts/piper_backend.py` (new). `src/probos/config.py` (`TTSConfig` model after `LipSyncConfig`; `tts` field on `Config`). `src/probos/routers/avatars.py` (`GET /api/avatars/tts/status` + `POST /api/avatars/tts` + `_wav_duration_ms` helper). `tests/test_ad738_piper_tts.py` (new, 26 tests). `ui/src/audio/voice.ts` (cache + probe + dual-path `speakResponse` + `_speakBrowserFallback` + `_resolveEffectiveProfile` + `_resetTtsStatusForTests`). `ui/src/audio/useLipSyncCapture.ts` (extended with `injectLipSyncFrames` + `_subscribeInjection` registry; existing hook subscribes both `onSpeechEvent` and the injection channel). `ui/src/audio/__tests__/voice.serverTts.test.tsx` (new, 6 tests). `ui/src/audio/__tests__/useLipSyncCapture.test.tsx` (+1 regression test). `ui/src/__tests__/voice.test.ts`, `ui/src/__tests__/voice.speakResponse.modulation.test.ts`, `ui/src/audio/__tests__/voice.test.ts` (each: pre-existing tests adjusted to stub `fetch` undefined so the synchronous browser-fallback path fires — AD-738 preserves sync semantics on the default-config path).


### AD-739 — Captain Card: operator self-card, always-in-context (planning)

**Date:** 2026-05-13. **Status:** Planning (placeholder anchored from architecture session). **Related:** AD-733 / AD-733a (live camera perception umbrella, [#641](https://github.com/seangalliher/ProbOS/issues/641)) — this AD provides the identity reference the streaming-vision pipeline matches against.

**Problem.** Every CognitiveAgent independently re-derives operator context from episodic recall on each request — expensive, inconsistent across crew, and fails on cold context (new agent, fresh thread, post-restart). Captain has no canonical, always-in-context identity surface; agents must guess or ask. Also blocks identity-aware perception: AD-733a "person appeared in frame" cannot become "the *Captain* appeared" without a recognition anchor.

**Decision shape (to be sharpened at prompt time).** A small, system-maintained operator self-card stitched into every CognitiveAgent prompt. Includes identity (name, callsign, role), voice/style anchors (tone, formatting preferences, e.g. no-emoji), active context (current project, current wave), known preferences, recent high-importance corrections, and an optional `avatar_ref` (AttachmentStore SHA) usable as the identity-recognition anchor for AD-733a streaming vision.

**Hard constraints (where this DIVERGES from Letta-style memory blocks).**
- **System-maintained, NOT agent-self-edited.** Updates flow through Dreaming consolidation + correction-feedback (existing pipeline). No `memory_replace` tool exposed to designed agents. Preserves trust/Hebbian/episodic loop and CodeValidator/probationary-trust governance from self-mod.
- **Validated at the prompt boundary.** Card content passes through the `_CAPABILITY_GAP_RE` + confabulation-guard surfaces (AD-588/589/592 lineage) before injection.
- **Versioned in KnowledgeStore.** Git-backed for reversibility (Reversibility Preference axiom).
- **Per-agent overlay optional.** Counselor needs different anchors than Engineering — base Card + per-department overlay, both system-managed.
- **Avatar is read-only to agents.** Captain owns the asset; agents must never fabricate or modify it (confabulation territory).
- **Not a personality dossier.** Facts and preferences only; no inferred psychology.

**Open design questions for the build prompt.**
1. Token budget — target ~200-500 tokens for the base Card; cap and truncation policy for overlays.
2. Storage shape — KnowledgeStore record vs sidecar `data/captain-card/`. Lean toward KnowledgeStore for symmetry with crew profiles.
3. Refresh cadence — how often does Dreaming touch the Card (every cycle, every N cycles, on-correction-only)?
4. Recognition-embedding source for AD-733a coupling — moondream2 in embed mode vs paired tiny face-embedding model. Resolve when AD-733a starts.

**Out of scope for v1.**
- Agent-side self-cards (each agent maintaining a memory-block of its OWN persona). CognitiveAgent `instructions` already serves that role per Principle #6.
- Multi-operator support (multiple humans with separate Cards). v1 is single Captain.
- Live perception itself — that's AD-733/733a/733b. AD-739 only provides the identity anchor.

**Why now / source of decision.** Architecture session 2026-05-13 reviewing letta-ai/letta scout report. The Letta "core memory blocks" pattern (always-in-context, agent-edited) is the inspiration; ProbOS adopts the *always-in-context* half and rejects the *agent-edited* half on governance grounds. Pattern-absorption per the OSS-license discipline (no Letta code imported).



### AD-737a — Divergence-detector hygiene (Wave 158)

**Date:** 2026-05-13. **Status:** SHIPPED. **Wave:** 158. **Closes:** [#648](https://github.com/seangalliher/ProbOS/issues/648). **Parent:** AD-737.

Three small hygiene items in `src/probos/avatars/divergence_detector.py` surfaced during Wave 156 GATE 2 review. (1) Hoist `import dataclasses` to module-top; the inline `import dataclasses as _dc` inside `apply_divergence_check` is removed. (2) Collapse the two-pass `parse_intent_self_tag` re-parse. The Wave-156 implementation parsed v1-only first, then re-parsed with `custom_emotions` if v1 returned None. Caller audit confirmed only two production call sites, both inside `apply_divergence_check`. Collapsed to a single call by fetching the palette first then parsing once. Behavior is identical because `parse_intent_self_tag(text)` is `parse_intent_self_tag(text, custom_emotions=None)` and `_resolve_intent_name` short-circuits to the v1-only path on `None`. (3) Documented the test-fake contract for `runtime.profile_store` / `divergence_results` / `divergence_history` in the `apply_divergence_check` docstring. Promotion to a `ProbOSRuntimeProtocol` is deferred (forward marker: AD-737a-1) until a second detector needs the same shape.

**Supersession.** The Wave-156 closure block reserved `AD-737a` as a forward marker for `TS-side parity for custom emotions`. That gap no longer exists: custom-emotion modulation is computed server-side and the TS layer only sees the v1 manifest names. The forward-marker prose in the Wave-156 block is retained as historical context.

**Files:** `src/probos/avatars/divergence_detector.py` (imports + docstring + collapsed parse), `tests/test_ad737a_hygiene.py` (new — 3 boundary tests pinning the single-pass invariant with a counting wrapper).


### AD-738a — Orchestrator commit-count audit + voice.ts test gate (Wave 158)

**Date:** 2026-05-13. **Status:** SHIPPED. **Wave:** 158. **Closes:** [#650](https://github.com/seangalliher/ProbOS/issues/650). **Parent:** AD-738 (Wave 157 Piper TTS) + wave-orchestrator scaffolding.

Two small hygiene items surfaced during Wave 157 GATE 2 review, plus a tracker-renumbering housekeeping pass. (1) `scripts/wave-orchestrator.ps1:Format-Gate2` now emits a COMMIT-COUNT AUDIT block that compares `wave.prompt_paths.Count` against the actual unpushed commits at HEAD and prints a yellow `AUDIT: wave N expected X commit(s); HEAD has Y unpushed commit(s).` warning when they diverge. Audit trail only — never blocks a push. Wave 157 itself drifted (1 expected, 2 actual) which is what motivated the surface. (2) `ui/src/audio/voice.ts:_resetTtsStatusForTests` is now gated behind `import.meta.env.MODE === 'test'`: production builds (`vite build` sets MODE=production) early-return a no-op, preserving the AD-738 zero-HTTP-per-utterance cache from accidental production resets. The function is still exported so existing test imports resolve.

**Supersession + slot reuse.** The Wave-157 closure block reserved AD-738a/b/c/d as forward markers for per-agent voice selection / GPU TTS eval / server-side voice modulation / TTS text caching. Those four markers are renumbered atomically in this AD to AD-738f / AD-738g / AD-738h / AD-738i so Wave 158 hygiene work can reuse the AD-738a / AD-738b / AD-738c slots (issues #650 / #651 / #652). The Tier-4 work remains unshipped under the new names in `docs/development/roadmap.md:361-364`; the original Wave-157 closure paragraph is retained verbatim above for audit history.

**Files:** `scripts/wave-orchestrator.ps1` (Format-Gate2 COMMIT-COUNT AUDIT block), `ui/src/audio/voice.ts` (MODE-gate on `_resetTtsStatusForTests`), `ui/src/audio/__tests__/voice.testGate.test.tsx` (new — 2 Vitest tests pinning MODE-gate inertness and happy path), `docs/development/roadmap.md` (4 forward markers renumbered to AD-738f/g/h/i).


### AD-738b — Per-wave UI gate must include npm run build (Wave 158)

**Date:** 2026-05-13. **Status:** SHIPPED. **Wave:** 158. **Closes:** [#651](https://github.com/seangalliher/ProbOS/issues/651). **Parent:** BF-279 (2026-05-13, stale `ui/dist/` for ~32h).

Codifies the BF-279 standing rule: any wave touching `ui/src/**` MUST run BOTH `cd ui; npx vitest run` AND `cd ui; npm run build` before each per-prompt commit. Vitest skips `tsc -b` strict checks, so a test suite can be 100% green while `vite build` errors. BF-279 was the canonical case study: Wave 156's `MicPermissionHint.tsx` introduced `JSX.Element` (unresolved under React 19 + bundler-mode tsconfig), `vite build` errored silently, `ui/dist/` stayed frozen for ~32 hours, and three waves' user-visible work never reached the operator's browser despite all Vitest tests passing.

Two artifacts updated. `prompts/BUILDER-EXECUTION-PLAN.md` Standing Rules section gains a `UI gate (BF-279, 2026-05-13)` bullet citing the commit (`2d685bc5`). `scripts/wave-orchestrator.ps1:Format-BuildDispatch` emits a `UI gate (AD-738b / BF-279)` block in the dispatch text whenever Builder kicks off a new wave, with the explicit `git diff --name-only HEAD~1..HEAD -- ui/src/` detection recipe.

**Slot reuse.** The Wave-157 closure block reserved `AD-738b` for `GPU-accelerated TTS backend eval (Kokoro / StyleTTS2)`; that forward marker was renumbered to `AD-738g` by AD-738a (Wave 158).

**Files:** `prompts/BUILDER-EXECUTION-PLAN.md` (Standing Rules — new bullet), `scripts/wave-orchestrator.ps1` (Format-BuildDispatch — new UI gate paragraph). No code changes; no tests added (process-change-only).


### AD-738c — rhubarb -> Oculus viseme mapping polish (Wave 158)

**Date:** 2026-05-13. **Status:** SHIPPED. **Wave:** 158. **Closes:** [#652](https://github.com/seangalliher/seangalliher/issues/652). **Parent:** AD-721b-1 (rhubarb backend, Wave 155), AD-738 (Piper TTS, Wave 157).

Cheap polish bundle addressing Captain's 2026-05-13 21:55 feedback (`mouth shapes don't perfectly match what's being said`) after the AD-738 + BF-279/280/281/282/283/284/285 stack landed. Two independent improvements:

(1) **Duration-aware Preston-Blair -> Oculus mapping** (`src/probos/avatars/rhubarb_backend.py`). `_map_preston_blair_to_oculus` signature extended to `(pb, duration_ms=0.0)`. When `pb == 'B'` and `duration_ms > 80.0` the lookup routes to `'ih'` (full vowel) instead of `'kk'` (consonant default). Empirically (Piper Amy MIT @ 22050 Hz), stop consonants peak at 60-75 ms and sustained `ih`-class vowels start at ~80 ms. Short B frames stay as `kk` (correct for stops). Extracted `_parse_rhubarb_output(payload)` from the inline parse loop in `generate_visemes` so the duration routing is unit-testable without a subprocess. Backward compat: callers that omit `duration_ms` get the legacy 1-to-1 mapping unchanged.

(2) **Bumped consonant residuals** (`ui/src/audio/lipSyncTrack.ts`). PP/FF/TH `aa` residuals 0.15-0.20 -> 0.25. DD/kk/SS/nn `ih` residuals 0.15-0.20 -> 0.25. RR `oh` 0.20 -> 0.30. CH `ee` 0.10 -> 0.20. Single uniform threshold (0.20 perceptual visibility floor in our amber/blue palette) lifts every consonant row above the morph-blend baseline while preserving the relative ordering (RR strongest, CH weakest). Existing `lipSyncTrack.test.ts` regression assertions updated to the bumped values; their previous 0.10/0.20 pins were captures of the old constants, not behavior invariants.

**Slot reuse.** The Wave-157 closure block reserved `AD-738c` for `Server-side voice modulation`; that forward marker was renumbered to `AD-738h` by AD-738a (Wave 158).

**Files:** `src/probos/avatars/rhubarb_backend.py` (table comment + duration kwarg + extracted `_parse_rhubarb_output`), `ui/src/audio/lipSyncTrack.ts` (consonant residuals + comment block), `tests/test_ad738c_viseme_mapping.py` (new — 4 pytest tests), `ui/src/audio/__tests__/lipSyncTrack.visemeTargets.test.ts` (new — 1 Vitest snapshot), `ui/src/audio/__tests__/lipSyncTrack.test.ts` (3 regression assertions updated to bumped values).

**Forward markers.** AD-738c-1 (C-context vowel disambiguation requiring parse-loop lookahead). AD-721b-3 / [#561](https://github.com/seangalliher/ProbOS/issues/561) remains the long-term proper fix (whisper.cpp WASM tiny.en for offline phoneme alignment).


### AD-738e-1 — Per-emotion Piper prosody overrides (Wave 158)

**Date:** 2026-05-13. **Status:** SHIPPED. **Wave:** 158. **Parents:** AD-738 (Piper TTS, Wave 157), AD-738e (BF-285 prosody knob exposure), AD-737 (custom emotion taxonomy).

Bridges the AD-737 emotion taxonomy into AD-738e's prosody knobs. New module `src/probos/audio/tts/prosody.py` exposes a partial override table mapping each v1 `EmotionalIntent` to a partial prosody dict, plus a `resolve_prosody_overrides(emotion)` helper that returns `{}` for unknown / None / empty / unmapped names. Additive guarantee: emotions without explicit overrides keep PiperBackend's constructor defaults unchanged.

**Override table (Captain Decision 2026-05-13):** `concerned` -> noise_scale=0.95, length_scale=1.05 (more expression, slightly slower). `excited` -> noise_scale=0.95, length_scale=0.92 (faster, more variation). `formal` -> noise_scale=0.70, length_scale=1.0 (drier, more measured). `neutral` / `warm` / `apologetic` / `playful` / `reassuring` have no entries — they ride on Piper defaults. `noise_w` and `sentence_silence` are NOT overridden in this AD (future AD-738e-2).

**Wire path.** `TTSBackend.synthesize` Protocol signature extended to `(text, emotion=None)`; `NullBackend` accepts and ignores; `PiperBackend` consults `resolve_prosody_overrides(emotion)` and merges into the per-call subprocess args (no instance mutation — safe for concurrent reuse). `POST /api/avatars/tts` accepts an optional `emotion` field in the JSON body (tier-1 boundary validation: non-string / overlong / empty -> None). The chat router at `routers/agents.py` reads `runtime.divergence_results[agent_id].intent_emotion` after `apply_divergence_check` and adds an `emotion` field to the response, collapsing custom AD-737 names to their v1 parent before exposure via the new public alias `resolve_emotion_to_v1` exported from `divergence_detector.py` (3-line additive alias of the existing private `_resolve_intent_name`). Browser `speakResponse` gains an optional `emotion` kwarg; `ProfileChatTab.tsx` forwards `data.emotion` from the chat response. Backward compat preserved at every layer.

**Files:** `src/probos/audio/tts/prosody.py` (new), `src/probos/audio/tts/backends.py` (Protocol signature), `src/probos/audio/tts/null_backend.py` (signature), `src/probos/audio/tts/piper_backend.py` (signature + import + per-call merge + arg references), `src/probos/routers/avatars.py` (POST body validation + kwarg forwarding), `src/probos/avatars/divergence_detector.py` (public `resolve_emotion_to_v1` alias), `src/probos/routers/agents.py` (chat response emotion field), `ui/src/audio/voice.ts` (signature + POST body), `ui/src/components/profile/ProfileChatTab.tsx` (forward data.emotion), `tests/test_ad738e_1_per_emotion_prosody.py` (new — 7 pytest tests), `ui/src/audio/__tests__/voice.perEmotion.test.tsx` (new — 2 Vitest tests), `tests/test_ad738_piper_tts.py` (3 stub backends updated to accept `emotion` kwarg for Protocol compat).

**Forward markers.** AD-738e-2-prosody (noise_w / sentence_silence per-emotion overrides — renumbered from AD-738e-2 in Wave 159 when issue #653's Refs-trailer rule took the canonical AD-738e-2 slot). AD-738e-3 (per-agent emotion overrides). AD-738e-4 (UI surface for tuning the override table).


### AD-722c — Avatar telemetry JSONL history + query endpoint (Wave 159)

**Date:** 2026-05-14. **Status:** SHIPPED. **Wave:** 159. **Parents:** AD-722 (telemetry channel, Wave 140), AD-722b (WS push, Wave 142), AD-722a-5 (divergence ring buffer, Wave 147). **Closes:** #569.

Append-only JSONL persistence for `AvatarTelemetrySnapshot` rows — one file per agent under `data/avatar_telemetry/<agent_id>.jsonl`. Adds `TelemetryHistoryWriter` (per-agent `asyncio.Lock` serialization, executor-backed sync write, `[A-Za-z0-9_.-]` agent_id sanitizer at boundary), three new `AvatarTelemetryConfig` fields (`history_enabled=True`, `history_retention_days=30` with `>= 1` validator, `history_dir="data/avatar_telemetry"`), and a `GET /api/agent/{id}/avatar-telemetry/history` endpoint that clamps `limit` to `[1, 1000]` and returns `{"agent_id", "rows"}`.

**Why JSONL, not SQLite-via-ProtocolStore.** The issue body proposed AD-682 ProtocolStore. Three reasons we chose JSONL for v1: (1) rows are small (~400 B) and write-once — no update pattern means no SQL benefit; (2) zero new infrastructure (no aiosqlite connection, no migration scripts); (3) operator can `cat` the file. Pattern mirrors AD-575 ship-records (append-only, human-inspectable). The ProtocolStore pattern is filed as forward marker AD-722c-2 for when the commercial overlay needs a queryable backend.

**Wire path.** `runtime.avatar_telemetry_history` is constructed next to `AvatarEventBus` (gated on `cfg.avatar_telemetry.enabled AND history_enabled`; `None` when off). `_publish_loop` (both the initial-send block at line 707 and the per-interval send at line 737) appends snapshots Tier-2 best-effort — log-and-degrade, never blocks the WS publish or the broadcast trigger. `query()` filters by `since` (defaults to `now - retention_days * 86400`), skips malformed lines, sorts newest-first, applies `limit`.

**Files:** `src/probos/avatars/telemetry_history.py` (new — ~140 lines, stdlib-only), `src/probos/config.py` (three new fields + retention validator), `src/probos/runtime.py` (construction block), `src/probos/routers/agents.py` (new GET endpoint + two log-and-degrade hooks in the WS publish loop), `tests/test_ad722c_telemetry_history.py` (new — 6 boundary tests: roundtrip, malicious agent_id rejection, since filter, retention window, disk failure tolerance, malformed-line skip).

**Forward markers.** AD-722c-1 (size-based JSONL rotation when per-agent files exceed N MiB). AD-722c-2 (`TelemetryHistoryStore` Protocol so commercial overlay can swap JSONL for SQLite/Postgres; closes AD-682 cloud-ready compliance gap for this surface).


### AD-722d - Auto-write significant telemetry events to Ship's Records (Wave 159)

**Date:** 2026-05-14. **Status:** SHIPPED. **Wave:** 159. **Parents:** AD-722b (WS push, Wave 142), AD-722c (telemetry history, Wave 159), AD-477 (Records ledger), AD-575 (Records autoseed). **Closes:** #570.

Subscribes the WS publish loop's snapshot stream to `TelemetryRecordsWriter`, which classifies frames into a v1 vocabulary of three named events and emits a narrative entry to Ship's Records per (agent, throttle-window). Three events: `emotion_divergence_high` (intent vs presentation magnitude > `divergence_negative_threshold` AND fresh rise vs prior per-agent magnitude), `working_state_transition_to_blocked` (prior frame had a non-blocked working_state), `sustained_silence` (no reply within `sustained_silence_seconds` AND <= 4h, prior reply was real). Priority pick when multiple fire: divergence > blocked > silence.

**Throttle restart policy.** Per-agent `last_write` dict is in-memory. Restart resets it. Intentional: Records is a narrative ledger, not a metrics store. A restart-burst of significance lines is signal (something changed in the agent's environment), not noise to de-duplicate.

**Two-phase wiring.** `runtime.avatar_telemetry_records_writer` is declared as `None` next to `AvatarEventBus` (so the WS publish loop's `getattr` guard degrades cleanly during the window between runtime `__init__` and finalize). The real `TelemetryRecordsWriter` is constructed immediately after `self._records_store = cog.records_store` finalize line (Phase 4). Gated independently from AD-722c — the Captain can have JSONL history without the Records ledger surface.

**Tier-2 everywhere.** `observe()` wraps every branch in try/except. A `RecordsStore.write_entry` failure is logged and swallowed — must not disrupt the WS publish loop, the AD-722c JSONL append, or the agent's reply.

**Config defaults (Captain opt-in).** `records_auto_write_enabled=False` (Records writes have audit weight), `records_throttle_seconds=3600`, `records_significant_events=[...3 v1 names...]` (default_factory; unknown names silently dropped at classify-time), `sustained_silence_seconds=1800`. Validators bound all three of the numeric fields (>= 1 / >= 1 / >= 60).

**Files:** `src/probos/avatars/records_writer.py` (new ~180 lines, stdlib + RecordsStore), `src/probos/config.py` (four fields + three validators), `src/probos/runtime.py` (None declaration in __init__ + finalize block after Phase 4 records_store wiring), `src/probos/routers/agents.py` (two log-and-degrade hooks in WS publish loop — initial-send + per-interval, both AFTER the AD-722c history append), `tests/test_ad722d_records_auto_write.py` (new — 5 boundary tests: divergence happy path with no re-fire, working-state transition with seeded prior, throttle clamps multi-event window, unknown event names dropped, RecordsStore raise swallowed).

**Forward markers.** AD-722d-1 (operator-defined `SignificanceClassifier` Protocol + plugin registry; trigger: Captain wants per-agent custom event names). AD-722d-2 (Records-side dedup/aggregation when N identical events fire within a configurable window).


### AD-722b-3 - Fine-grained snapshot-diff for WS push (Wave 159)

**Date:** 2026-05-14. **Status:** SHIPPED. **Wave:** 159. **Parents:** AD-722b (WS push channel, Wave 142), AD-722b-2 (sensorium freshness side-effect, Wave 142). **Closes:** #600.

Per-frame field-level diffing on top of AD-722b's WS publish loop. Pure-function `compute_diff(prev, next, threshold, skip_fields)` returns a dict of changed top-level keys; empty dict means the publish loop suppresses the send entirely. `last_observed_at` is in `DEFAULT_SKIP_FIELDS` so jitter on a per-frame timestamp doesn't trigger emissions. Numeric fields use a relative-change threshold (default 0.05); nested dicts diff one level deep. Lists/tuples diff positional and length-aware.

**Frame shape versioning.** Every WS frame now carries a `type` field: `{"type": "snapshot", ...flat snapshot fields}` on first-frame/Nth-tick/fallback, or `{"type": "diff", "agent_id": ..., "changed": {...}}` between. Frontend treats a frame without `type` as a snapshot (legacy compat).

**Reconcile invariant.** Every Nth wake (default 10) sends a full snapshot regardless of diff, so a late subscriber that connected mid-diff-stream OR any client that missed a diff frame reconciles within at most N intervals. Set `ws_full_snapshot_every_n=1` to disable diff entirely (legacy behavior).

**Per-connection state.** `last_sent_snap_dict` and `tick_count` live as closure-scoped locals in `agent_avatar_telemetry_stream` (declared `nonlocal` in `_publish_loop`). Reconnects start fresh with `last_sent_snap_dict=None` so the first server frame after reconnect is always a full snapshot.

**Frontend merge.** `SelfImageTab.tsx` `onmessage` checks `data.type`: `"diff"` merges `data.changed` into a closure-scoped `lastSnapshot` via spread; `"snapshot"` replaces wholesale with the `type`-stripped object. The poll-fallback (HTTP GET) returns a flat snapshot without a `type` field; the existing branch handles that transparently.

**Tier-2 safety.** `compute_diff` exception falls back to a full snapshot send (never blocks the publish). Loop continues even if a diff frame fails to serialize.

**Test fixture wiring.** The shared `_ws_endpoint_runtime` fixture in `tests/test_ad722b_websocket_push.py` explicitly sets `cfg.avatar_telemetry.ws_diff_enabled = False` so the 31 existing AD-722b/722b-2 tests keep their one-frame-per-wake semantics. The new AD-722b-3 tests cover the diff path directly. `test_ws_endpoint_publishes_on_event_bus_notify` was the canary: under MagicMock-defaults the diff suppression was indistinguishable from a hang.

**Files:** `src/probos/avatars/snapshot_diff.py` (new ~80 lines, stdlib-only pure function), `src/probos/config.py` (3 fields + 2 validators), `src/probos/routers/agents.py` (per-connection state declarations + `nonlocal` in `_publish_loop` + initial-send wrapper + diff/full branch), `ui/src/components/profile/SelfImageTab.tsx` (closure-scoped `lastSnapshot` + onmessage merge branch), `tests/test_ad722b_3_snapshot_diff.py` (new — 6 boundary tests: first-frame minus skip, identical empty, below-threshold skipped, above-threshold included, nested recursion, skip-fields excluded), `ui/src/__tests__/SelfImageTab.diffFrame.test.tsx` (new — 1 Vitest test for the merge path), `tests/test_ad722b_websocket_push.py` (fixture update — diff disabled for legacy tests).

**Forward markers.** AD-722b-3a (RFC 6902 JSON-Patch payload format for deeply-nested telemetry trees where shallow merge loses information). AD-722b-3b (server-side `SubscriberState` Protocol so a fan-out broker can serve N clients from one builder).


### AD-720e - Audio attachment playback (Wave 159)

**Date:** 2026-05-14. **Status:** SHIPPED. **Wave:** 159. **Parents:** AD-720 (image paste, Wave 135), AD-720a (file upload, Wave 139), AD-721b-1 (browser-captured audio/webm + audio/wav, Wave 155), AD-731 (content-addressable refs, Wave 152). **Closes:** #566.

Playback-only audio attachments. `AttachmentsConfig.allowed_mime_types` defaults extend with `audio/mpeg`, `audio/mp4`, `audio/ogg` (existing `audio/webm` + `audio/wav` from AD-721b-1 unchanged). `attachments/mime.py._SIGNATURES` registers MP3 sync bytes (4 variants: ID3, MPEG-1 L3, MPEG-2 L3, MPEG-2.5 L3), MP4 ftyp brands (3: M4A, mp42, isom), and the Ogg `OggS` magic. `_ANY_OF` extends to include the two multi-option audio MIMEs so the existing any-of branch in `validate_image_bytes` (line 48) validates them without new code paths. `audio/ogg` stays out of `_ANY_OF` — its single signature is correctly handled by the default all-required path.

**Frontend render.** `IntentSurface.tsx` attachment preview ternary becomes a 3-way: image -> `<img>`, audio -> `<audio controls preload="metadata">`, other -> inline-SVG file-icon (HXI Design Principle #3 — no emoji). The `<audio>` element's `src` is `/api/chat/attachments/<sha>` — same content-addressable URL as images. AD-731 invariant preserved: audio bytes never inline as base64 in `IntentMessage.params` or the prompt; the bus always carries refs.

**WardRoom paste broaden + scope-collapse.** `WardRoomThreadDetail.tsx` `handlePaste` MIME filter accepts `audio/` in addition to `image/` so operator can paste audio into a DM. The chip-only render in WR/Profile stays unchanged (no inline `<audio>` element in those surfaces) — playback delivered through the canonical IntentSurface render seam per HXI Principle #11 (workstation pattern). Forward marker AD-720e-3 covers per-chip inline player if Captain requests later.

**Transcription out of scope.** AD-705a (whisper.cpp WASM) remains the forward marker. This AD ships playback only.

**Folded: AD-738e-2 (Refs-trailer standing rule, #653).** New BUILDER-EXECUTION-PLAN entry: when a sub-AD has no GH issue (born out of a parent BF's commentary), the commit MUST carry EITHER a `Refs #N-of-parent-BF` trailer OR a `See DECISIONS.md AD-NNN` reference in the body. Builder applies automatically; architect approval not required at GATE 2 when present. Lineage: AD-738e-1 (`bb1ca160`) shipped with the DECISIONS reference as the canonical example.

**AD-738e-2 numbering note.** DECISIONS.md AD-738e-1 reserved the slot for "noise_w / sentence_silence per-emotion overrides." Issue #653 was filed AFTER that and took the slot; the prosody marker renumbers to **AD-738e-2-prosody** (forward marker, never built). DECISIONS AD-738e-1's "Forward markers" line updated in this commit.

**Files:** `src/probos/config.py` (3 new audio MIMEs in default factory), `src/probos/attachments/mime.py` (3 new `_SIGNATURES` entries + `_ANY_OF` extension), `ui/src/components/IntentSurface.tsx` (3-way preview ternary), `ui/src/components/wardroom/WardRoomThreadDetail.tsx` (paste MIME filter), `prompts/BUILDER-EXECUTION-PLAN.md` (Refs-trailer standing rule), `DECISIONS.md` (AD-738e-1 forward-marker renumber), `tests/test_ad720e_audio_attachments.py` (new — 5 pytest tests covering MP3 ID3 + frame-sync, MP4 ftyp, Ogg, and allow-list defaults), `ui/src/__tests__/IntentSurface.audioRender.test.tsx` (new — 3 Vitest tests: audio renders `<audio>`, image still renders `<img>`, PDF falls back to file-icon).

**Forward markers.** AD-720e-1 (drop-zone visual feedback for audio drag/drop). AD-720e-2 (waveform thumbnail via Web Audio API decode-on-demand). AD-720e-3 (inline `<audio>` player inside WardRoom + ProfileChatTab chip surfaces). AD-705a (whisper.cpp WASM transcription — unchanged forward marker).


### AD-738e-2 - Refs-trailer standing rule for orphan sub-ADs (Wave 159)

**Date:** 2026-05-14. **Status:** SHIPPED. **Wave:** 159. **Parents:** AD-738e-1 (per-emotion Piper prosody overrides, Wave 158). **Closes:** #653. **Folded into:** AD-720e commit.

Codifies the Builder commit-message convention introduced by AD-738e-1 (`bb1ca160`) for sub-ADs spawned from a parent BF that has no GH issue. New entry in `prompts/BUILDER-EXECUTION-PLAN.md` Standing Rules section: commit MUST include EITHER a `Refs #N-of-parent-BF` trailer when the parent BF has a GH issue, OR a `See DECISIONS.md AD-NNN` reference in the commit body when the parent BF is internal-only. Builder applies automatically — no architect approval at GATE 2 required when the trailer/reference is present.

**Numbering.** This AD reclaims the AD-738e-2 slot that AD-738e-1's DECISIONS entry had reserved as a forward marker for prosody knob extensions. The prosody marker renumbers to **AD-738e-2-prosody** (still a forward marker; never built). The renumber is recorded both in this entry and in AD-738e-1's "Forward markers" line.


### AD-725 - Targeted sub-intent dispatch on DM one-shot path (Wave 159)

**Date:** 2026-05-14. **Status:** SHIPPED. **Wave:** 159. **Parents:** AD-722-addendum (System-1/System-2 ruling), AD-723 (sensorium dispatch unification), AD-723a-1 (DM_ONESHOT consumer), AD-724 (DM sanity gate), AD-686 (runtime.oracle public alias). **Closes:** #583.

Bridges the largest cognitive-parity gap between System-1 (DM one-shot) and System-2 (chain) paths. Chains can reach for `oracle_lookup`, `episodic_query`, `codebase_query`, `knowledge_load` mid-flight; DMs had only pre-loaded working memory. AD-725 adds a SINGLE pre-LLM read-only lookup, gated by a fast classifier, before the LLM call. The result lands as a `--- Targeted Recall (<type>) ---` block prepended to `message_text` immediately before the IntentMessage is built in `agent_chat`.

**Four firewall contracts (intentional, regression-tested):**
1. At most one lookup per DM turn. No chains.
2. Read-only. No episodic store, trust update, Hebbian edge, consensus broadcast.
3. Hard `asyncio.wait_for` timeout (default 500 ms). Timeout -> None.
4. No `intent_bus` broadcast — direct method calls on `runtime.oracle` / `runtime.episodic_memory` / `runtime.codebase_index` / `runtime.records_store`.

Test #10 (`test_no_side_effects_on_runtime`) explicitly asserts zero `mock_calls` on `trust_network` / `intent_bus` / `hebbian_router` / `consensus_engine` after a full lookup turn — this is the firewall regression gate.

**Classifier as Protocol.** `SubintentClassifier` Protocol defines `classify(message, *, agent_id) -> (LookupType, query)` so the v1 regex ladder (`RegexSubintentClassifier`: episodic -> codebase -> knowledge -> oracle -> none) can be swapped for an embedding router (AD-725-2 forward marker) without touching `LookupDispatcher` or the caller. The regex ladder is intentionally conservative; default-OFF gating lets operator opt in.

**Defensive dispatch.** Each `_dispatch` branch checks `hasattr(runtime, '<store>')` and `hasattr(<store>, '<method>')` before calling. Missing methods log INFO and degrade to `""` content — never crash. Supports both sync and async return signatures via `asyncio.iscoroutine` check. `_stringify` flattens list/dict/dataclass returns; falls through to `repr()` for unknown shapes (forward marker AD-725-6 for Episode-specific row formatting).

**Integration seam.** Wired in `routers/agents.py::agent_chat` after `is_crew_agent` validation, BEFORE the AD-730 vision pipe-through branch. Recall block prepends `message_text` immediately before the IntentMessage build (line ~1183). Does NOT touch `cognitive_agent._build_user_message` — that refactor is reserved for AD-726. Sensorium-path registration (`paths=(DM_ONESHOT,)`) deferred to AD-725-1 forward marker.

**Default OFF.** `DmTargetedLookupConfig.enabled=False`. Captain opts in. `enable_codebase` is independently default-False (codebase queries can be slow). `timeout_ms=500` is the hard ceiling; classifier+lookup must complete within that or the lookup is silently dropped.

**Verified signatures (live grep, 2026-05-14):** `runtime.oracle.query(query_text, *, agent_id="")` async (AD-686 public alias for `cog.oracle_service`, set at `runtime.py:1577`); `episodic_memory.recall_for_agent(agent_id, query, k=5)`; `codebase_index.query(concept)`; `records_store.search(query)` (degrades cleanly if absent).

**Files:** `src/probos/cognitive/dm_targeted_lookup.py` (new ~230 lines, stdlib + asyncio), `src/probos/config.py` (new `DmTargetedLookupConfig` Pydantic model + `SystemConfig.dm_targeted_lookup` field), `src/probos/routers/agents.py` (dispatcher call top of `agent_chat` + recall-block prepend before IntentMessage build), `tests/test_ad725_dm_targeted_lookup.py` (new — 11 tests: disabled, classifier-none, episodic happy-path, codebase-default-off, oracle async, missing knowledge method, timeout, classifier exception, truncation, firewall side-effects, regex classifier smoke).

**Forward markers.** AD-725-1 (sensorium-path registration; lookup result registers via AD-723 dispatcher as `paths=(DM_ONESHOT,)` block instead of raw text prepend). AD-725-2 (embedding-based classifier as drop-in Protocol impl). AD-725-3 (per-agent sub-intent vocabulary — Counselor's emotion sub-intents, Worf's threat sub-intents). AD-725-4 (multi-store fan-out gated by classifier confidence). AD-725-5 (`(text_hash, agent_id) -> TargetedLookupResult` LRU cache for repeat-query suppression). AD-725-6 (`_stringify` Episode-dataclass branch for cleaner LLM context).


### AD-726 - DM post-LLM cleanup pipeline (Wave 160, partial close of #584)

**Date:** 2026-05-14. **Status:** SHIPPED (partial). **Wave:** 160. **Parents:** AD-722 / AD-723 / AD-724 / AD-725. **Closes:** #584 (partial — pre-LLM extractions deferred to AD-726a/b/c forward markers). **Also lands:** AD-722c-3 (#654 — Standing Rule fold).

`agent_chat` (`src/probos/routers/agents.py`) was 574 lines, well past the no-god-objects threshold. The post-LLM cleanup chain (8 ordered concerns from sanity-gate retry through emotion resolution) is now extracted to `src/probos/cognitive/dm/reply_pipeline.py`: `DmReplyPipeline` with eight `step_N_*` methods + `build_response()`, threaded through a mutable `DmReplyContext` dataclass. Each step body is a VERBATIM move of the prior inline block — same Tier-2 boundaries, log strings, AD references. The handler's post-LLM block shrinks from 295 lines (1278..1572) to 23 lines (sanity_gate hoist + pipeline construct + run + build_response). Net delta -272 lines; agent_chat ~305 lines post-refactor.

**Out of scope (forward markers):** pre-LLM `DmContextPrep` (AD-726a); `DmPromptAssembler` extraction from `cognitive_agent._build_user_message` (AD-726b); frozen cross-phase shapes + byte-identical snapshot fixture suite (AD-726c).

**Files:** new `src/probos/cognitive/dm/__init__.py` + `reply_pipeline.py` (~370 lines); `src/probos/routers/agents.py` shrinks 295→23 lines at the call site; `tests/test_ad726_dm_reply_pipeline.py` (new, 12 boundary tests — ordered execution, top-level guard, each step's degrade branch, build_response game/non-game branches); `tests/test_ad722_avatar_telemetry.py` test_mark_reply_emitted_singular_call_site updated to assert the single call site relocated to `reply_pipeline.py` (invariant preserved, location moved).

**Folded — AD-722c-3 (#654).** One bullet appended to `prompts/BUILDER-EXECUTION-PLAN.md` Standing Rules: forward markers must use TECHNICAL triggers, not commercial-tier language. Rationale: OSS repo describes WHAT extension points exist, not HOW they're priced or monetized (AD-450 / Wave 154 retrospective).



### AD-723a-3 - SensoriumEntry metadata extension (Wave 160)

**Date:** 2026-05-14. **Status:** SHIPPED. **Wave:** 160. **Parents:** AD-723 (sensorium dispatch unification), AD-723a-1 (DM_ONESHOT consumer migration). **Closes:** #626.

`SensoriumEntry` (`src/probos/cognitive/cognitive_agent.py`) gains two new fields, both defaulting `None`:

- `injection_zone: str | None` — opaque zone identifier describing where the entry renders in the prompt. v1 reserved values: `temporal_header`, `working_memory`, `post_episodic`, `self_recognition`. Observation-only in v1; zone-driven dispatch ordering deferred to AD-723a-3b.
- `wrapper: object | None` — optional `Callable[[str], str]` that wraps the registered method's output with framing markers. Typed as `object | None` rather than `Callable[[str], str] | None` to dodge frozen-dataclass hashability divergence across Python versions; the dispatcher runtime-checks via `callable(...)`.

`_apply_sensorium_result` applies the wrapper to string outputs only — the dict-return contract is unchanged (wrapping a dict makes no shape sense). Wrapper exceptions log DEBUG and store the raw output (Tier-2 log-and-degrade).

`_DM_SELF_WRAPPED_KEYS` remains the v1 selector for which entries get rendered in the DM path (currently 2 entries). Per-entry migration off this tuple is AD-723a-3a forward marker (advances when 3+ entries gain `wrapper` set AND consumer code needs zone-driven iteration). No existing registry entry is migrated by this AD.

**Files:** `src/probos/cognitive/cognitive_agent.py` (SensoriumEntry field extension + `_apply_sensorium_result` wrapper application); `tests/test_ad723a3_sensorium_metadata.py` (new, 7 boundary tests — backward-compat default construction, zone-only, wrapper-only, frozen immutability, dispatcher-applies-wrapper-on-str, dispatcher-skips-wrapper-on-dict, wrapper-exception-falls-back-to-raw).



### AD-722a-4 - Auto-correction loop on high-magnitude divergence (Wave 160)

**Date:** 2026-05-14. **Status:** SHIPPED. **Wave:** 160. **Parents:** AD-722a (divergence detector), AD-722a-7 (modulation recompute), AD-737/737a (custom-emotion palette resolution), AD-738e-1 (per-emotion prosody overrides). **Closes:** #613.

`apply_divergence_check` previously fired trust + Hebbian updates on high-magnitude divergence but shipped the original modulation unchanged. AD-722a-4 closes that loop: when `result.magnitude > auto_correct_threshold` AND `auto_correct_enabled`, the detector re-invokes `apply_voice_modulation` with multiplicative correction factors (`noise_scale_factor` on pitch, `length_scale_factor` reciprocal on rate). The post-correction `DivergenceResult` is stored on `runtime.divergence_corrections[agent_id]` with `corrected=True`. TTS endpoint reads the slot AFTER the DM reply returns; the slot is cleared at the START of the NEXT DM reply by `DmReplyPipeline.step_1_sanity_gate_retry` (NOT step_7 — clearing at exit would race TTS to empty).

**The firewall (AD-727 rule #1 carve-out):** default OFF. At most one re-modulation per utterance (slot-empty-check at write time + reply-entry clear). Re-modulation failure logs WARNING and ships ORIGINAL modulation. response_text NEVER rewritten — only the prosody parameters consumed by TTS change. Carve-out is intentionally narrow: aesthetic judgment influences DELIVERY, not content.

**Files:** `src/probos/config.py` (AvatarTelemetryConfig +5 fields: `auto_correct_enabled`, `auto_correct_threshold`, `max_corrections_per_utterance`, `correction_noise_factor`, `correction_length_factor`); `src/probos/avatars/divergence_detector.py` (DivergenceResult +`corrected: bool`, `to_dict()` extended; `apply_divergence_check` correction branch inserted between div_results store and AD-722a-5 ring-buffer append); `src/probos/avatars/telemetry.py` (`apply_voice_modulation` gains kw-only `noise_scale_factor`/`length_scale_factor` with default-1.0 no-op, applied as outer multiplicative layer after intent rule layering); `src/probos/runtime.py` (`divergence_corrections: dict[str, DivergenceResult]` allocated next to `divergence_results`); `src/probos/cognitive/dm/reply_pipeline.py` (slot-clear prepended to `step_1_sanity_gate_retry`); `tests/test_ad722a4_auto_correction.py` (new, 9 boundary tests — 8 from spec + `apply_voice_modulation` default-kwargs no-op verification).

**Forward markers.** AD-722a-4-1 (per-emotion correction factors). AD-722a-4-2 (multi-utterance correction learning when post-correction-magnitude < pre-correction-magnitude stable above 60%).



### AD-730-2 - Multi-image DM policy (Wave 160)

**Date:** 2026-05-14. **Status:** SHIPPED. **Wave:** 160. **Parents:** AD-720 (image paste), AD-720d-1 (multi-image soft warn), AD-730 (vision pipe-through), AD-731 (content-addressable refs), AD-732 (vision tier). **Closes:** #632.

Converts AD-720d-1's soft warning (5-image threshold, log-only) into a three-tier policy:

1. **Hard cap (default 8 images per DM).** `ImagePolicyEnforcer.check_hard_cap` raises HTTP 413 when exceeded. The ONE strict reject (cost gate; honest-degrade would defeat the purpose). Soft warn at 5 preserved.
2. **Downscale (default 1024px bounding box).** `downscale_if_needed` walks each content_hash, fetches the bytes via `store.read`, calls `PIL.Image.thumbnail` (aspect-preserving), and stores the downscaled bytes as a NEW content-addressable ref via `store.write`. The ORIGINAL ref is preserved (AD-731 invariant — refs are immutable). GIFs are skipped (animated-frame complexity). Tier-2: PIL failure logs WARNING, ships original hash. Returns substituted hash list so the caller rebuilds the multimodal payload.
3. **Per-Captain daily budget (default 50, rolling 24h).** `check_budget` tracks a `deque[(timestamp, image_count)]` per Captain on `runtime.image_budget_tracker`. Ages out entries older than 24h on every check. On exhaustion raises HTTP 429 with `Retry-After` = seconds until the oldest counted image ages out. Tier-2: tracker absence logs WARNING and proceeds without the gate.

`agent_chat` wires the enforcer between `build_multimodal_messages` (initial) and the vision-tier-or-fallback branch. When downscale substitutes any hash, `agent_chat` re-walks `req.attachment_ids` with a translation map and re-invokes `build_multimodal_messages` so the downscaled refs reach the LLM. Budget check runs LAST — operates on the final delivered count, not pre-compression.

**Files:** `src/probos/config.py` (+3 AttachmentsConfig fields: `images_per_dm_hard_cap`, `image_max_dimension`, `daily_image_budget_per_captain`); `src/probos/attachments/image_policy.py` (new ~190 lines — `ImagePolicyEnforcer` + `ImagePolicyError`); `src/probos/routers/agents.py` (hook between soft-warn block and vision-tier branch in `agent_chat`); `src/probos/runtime.py` (`image_budget_tracker` allocated next to `divergence_history`); `tests/test_ad730_2_image_policy.py` (new, 9 boundary tests covering all three tiers + AD-731 invariant + PIL failure degrade).

**Pillow verified resident.** `import PIL` -> 12.2.0 in venv as of 2026-05-14. NO new pip dep. Pillow license: HPND (permissive, Apache 2.0 compatible).

**Forward markers.** AD-730-2-1 (persistent budget tracker for deployments requiring restart-survival). AD-730-2-2 (per-agent_type budget override).




### AD-722b-4 - Fleet-level avatar telemetry stream (Wave 160)

**Date:** 2026-05-14. **Status:** SHIPPED. **Wave:** 160. **Parents:** AD-722b (per-agent WS), AD-722b-3 (snapshot-diff frames), AD-722c (history append), AD-722d (records writer). **Closes:** #601.

New WS endpoint `WS /api/agent/avatar-telemetry/stream` (full path under the `agents` router prefix `/api/agent`). On accept, iterates `runtime.registry.agents.values()`, filters by `is_crew_agent`, and runs the same per-agent publish-loop logic the per-agent endpoint runs today — wrapped per-agent with the `agent_id` interleaved into every frame. Every fleet frame carries an explicit `agent_id` field (mandatory at the FLEET endpoint, absent at the per-agent endpoint).

**Concurrency:** one WS holds N (= crew count) per-agent publish coroutines, each gated by its own `sampling_state` rate and event signal. `asyncio.wait` with `FIRST_COMPLETED` over `{publish_tasks, receive_task}` cancels the group cleanly on either-side disconnect.

**Backward compatibility:** per-agent endpoint at `/{agent_id}/avatar-telemetry-stream` (line 669) preserved unchanged. New endpoint is opt-in via `AvatarTelemetryConfig.fleet_stream_enabled: bool = True` — default-ON because no existing UI consumes it yet; flag exists for operator override.

**Frontend stub:** `ui/src/avatars/useFleetAvatarTelemetry.ts` — single hook subscribes once and dispatches per-agent frames via callback. Drops malformed frames + frames missing `agent_id` silently. Closes WebSocket on unmount. Pure logic file, no JSX, no emoji vector. Hook is NOT imported by any existing component yet — store-side migration deferred to AD-722b-4a forward marker. Bundle hash unchanged because Vite tree-shakes unused exports — verifies the integration is properly opt-in.

**Routing.** Path literals `/avatar-telemetry/stream` and `/{agent_id}/avatar-telemetry-stream` cannot collide: the static segment cannot satisfy a single-segment path parameter. Insertion order at the registration site is purely cosmetic.

**Files:** `src/probos/config.py` (+1 `fleet_stream_enabled` field); `src/probos/routers/agents.py` (new `fleet_avatar_telemetry_stream` handler); `ui/src/avatars/useFleetAvatarTelemetry.ts` (new ~70-line hook stub); `ui/src/__tests__/useFleetAvatarTelemetry.test.ts` (new, 3 vitest tests); `tests/test_ad722b4_fleet_telemetry.py` (new, 6 pytest tests).

**Forward markers.** AD-722b-4a (consumer-side per-agent store consolidation). AD-722b-4-1 (dynamic crew membership during connection lifetime).


### AD-722b-4 - Fleet-level avatar telemetry stream (Wave 160)

**Date:** 2026-05-14. **Status:** SHIPPED. **Wave:** 160. **Parents:** AD-722b (per-agent WS), AD-722b-3 (snapshot-diff frames), AD-722c (history append), AD-722d (records writer). **Closes:** #601.

New WS endpoint `WS /api/agent/avatar-telemetry/stream` (full path under the `agents` router prefix `/api/agent`). On accept, iterates `runtime.registry.agents.values()`, filters by `is_crew_agent`, and runs the same per-agent publish-loop logic the per-agent endpoint runs today — wrapped per-agent with the `agent_id` interleaved into every frame. Every fleet frame carries an explicit `agent_id` field (mandatory at the FLEET endpoint, absent at the per-agent endpoint).

**Concurrency:** one WS holds N (= crew count) per-agent publish coroutines, each gated by its own `sampling_state` rate and event signal. `asyncio.wait` with `FIRST_COMPLETED` over `{publish_tasks, receive_task}` cancels the group cleanly on either-side disconnect.

**Backward compatibility:** per-agent endpoint at `/{agent_id}/avatar-telemetry-stream` (line 669) preserved unchanged. New endpoint is opt-in via `AvatarTelemetryConfig.fleet_stream_enabled: bool = True` — default-ON because no existing UI consumes it yet; flag exists for operator override.

**Frontend stub:** `ui/src/avatars/useFleetAvatarTelemetry.ts` — single hook subscribes once and dispatches per-agent frames via callback. Drops malformed frames + frames missing `agent_id` silently. Closes WebSocket on unmount. Pure logic file, no JSX, no emoji vector. Hook is NOT imported by any existing component yet — store-side migration deferred to AD-722b-4a forward marker. Bundle hash unchanged because Vite tree-shakes unused exports — verifies the integration is properly opt-in.

**Routing.** Path literals `/avatar-telemetry/stream` and `/{agent_id}/avatar-telemetry-stream` cannot collide: the static segment cannot satisfy a single-segment path parameter. Insertion order at the registration site is purely cosmetic.

**Files:** `src/probos/config.py` (+1 `fleet_stream_enabled` field); `src/probos/routers/agents.py` (new `fleet_avatar_telemetry_stream` handler); `ui/src/avatars/useFleetAvatarTelemetry.ts` (new ~70-line hook stub); `ui/src/__tests__/useFleetAvatarTelemetry.test.ts` (new, 3 vitest tests); `tests/test_ad722b4_fleet_telemetry.py` (new, 6 pytest tests).

**Forward markers.** AD-722b-4a (consumer-side per-agent store consolidation). AD-722b-4-1 (dynamic crew membership during connection lifetime).


### AD-730-2-1 - Image-budget tracker JSON sidecar persistence (Wave 161)

**Date:** 2026-05-15. **Status:** SHIPPED. **Wave:** 161. **Parent:** AD-730-2 (Wave 160 — in-memory per-Captain rolling 24h budget). **Closes:** #656.

The AD-730-2 budget tracker (`runtime.image_budget_tracker`) lived only in memory: restart wiped the deque and the Captain's 24h spend reset on every boot, defeating the rate-limit's intent. This AD persists the tracker to a JSON sidecar (default `<data_dir>/image_budget.json`, configurable via new `AttachmentsConfig.image_budget_path`) loaded on runtime startup and rewritten on every mutation by `ImagePolicyEnforcer.check_budget` (append AND prune).

**Persistence shape.** `{captain_id: [[timestamp, count], ...]}` flat JSON. New module `src/probos/attachments/image_budget_store.py` exposes `load(path) -> dict[str, deque]` and `save(path, tracker) -> None` module-level functions. `save` writes to a sibling temp file via `tempfile.mkstemp` then `os.replace` for atomicity; empty deques are skipped to keep the file compact. `load` tolerates missing files (returns empty dict, no exception) and corrupt JSON (logs WARNING and returns empty dict).

**Tier-2 throughout.** Disk I/O failure logs WARNING and degrades — the in-memory tracker remains authoritative for the live process. `_persist_tracker` wraps the `image_budget_store.save` call in a try/except that never propagates so a DM is never blocked on disk failure. AD-731 invariant untouched: this AD touches the BUDGET tracker only; image bytes still flow through `AttachmentStore` as SHA-256 refs.

**Files:** `src/probos/attachments/image_budget_store.py` (new, ~95 lines); `src/probos/runtime.py` (boot-time load swap, uses `self._data_dir` — the prompt's draft `self.config.data_dir` field does not exist on `SystemConfig`); `src/probos/attachments/image_policy.py` (`check_budget` persists on append + prune; new `_persist_tracker` helper); `src/probos/config.py` (`AttachmentsConfig.image_budget_path: str | None = None` field); `tests/test_ad730_2_1_image_budget_persistence.py` (new, 5 pytest tests).

**Forward markers.** AD-730-2-1a (write throttle — batch persistence when write amplification > 1 write per DM AND file > 64 KB). AD-730-2-1b (migrate to `ConnectionFactory` Protocol from AD-697/698 when a non-SQLite backend lands AND a second runtime-state-with-disk-sidecar AD ships).


### AD-721d-4 - Avatar proposal-history JSON sidecar persistence (Wave 161)

**Date:** 2026-05-15. **Status:** SHIPPED. **Wave:** 161. **Parent:** AD-721d-1 (Wave 145 - in-memory module-level dict + RLock). **Closes:** #620 (and #623 as duplicate; both issues share an identical title and body).

The AD-721d-1 module `src/probos/avatars/proposal_history.py` stored the per-agent DSL-proposal session history in a module-level dict guarded by an `RLock`. The module docstring explicitly anticipated this AD: "v1 is single-process; cluster-wide consistency, persistence across restarts, and quorum on the iteration counter are out of scope." The 5 public function signatures (`append`, `iteration_count`, `latest`, `clear`, `reset_all`) were documented as **stable** to support a drop-in persistence swap.

This AD adds an optional JSON sidecar bound at runtime startup via the new `configure(path: Path | None)` function. When `path` is set, `configure` loads existing state into `_history` and rebinds the module-level `_persist_path`; mutations (`append` / `clear` / `reset_all`) then call `_persist_locked()` AFTER the in-memory update, inside the existing `with _lock:` block. When `path` is `None`, the module operates in pure in-memory mode (matches pre-AD behavior and is required for tests).

**Persistence shape.** `{agent_id: [{"dsl": {...}, "captain_note": str, "timestamp": float}, ...]}` flat JSON. Atomic write via `tempfile.mkstemp` + `os.replace` (same pattern as AD-730-2-1). Empty agent lists are skipped to keep the file compact. The frozen `ProposalEntry` dataclass is reconstructed from each dict on load; malformed entries log WARNING and are dropped (one bad entry does not poison the rest).

**Tier-2 throughout.** Disk I/O failure logs WARNING and degrades - the in-memory `_history` remains authoritative for the live process. `_persist_locked` wraps the file I/O in try/except that never propagates so a propose/approve call is never blocked on disk. `_load_from_disk_locked` tolerates missing files (no-op), corrupt JSON (empty dict + WARNING), non-dict roots (empty + WARNING), and per-entry corruption (skip + WARNING).

**5 public signatures unchanged.** `configure` is a NEW function; the existing `append` / `iteration_count` / `latest` / `clear` / `reset_all` retain their exact signatures. Production callers (`routers/agents.py`) require zero modification. The autouse pytest fixture `_isolate_proposal_history` in the new test file calls `reset_all() + configure(None)` on teardown to prevent test-pollution across tests that share the module-level state.

**Files:** `src/probos/avatars/proposal_history.py` (configure + helpers + persist calls in mutators); `src/probos/runtime.py` (boot-time wiring; uses `self._data_dir` for default path - same pattern as AD-730-2-1); `src/probos/config.py` (`AvatarsConfig.proposal_history_path: str | None = None` field); `tests/test_ad721d_4_proposal_history_persist.py` (new, 5 pytest tests).

**Forward markers.** AD-721d-4a (migrate to `ConnectionFactory`-backed history store - advances when AD-697/698 lands a non-SQLite backend OR sidecar file size > 1 MB OR a second module needs proposal-history-style restart-survival state). AD-721d-4b (periodic compaction - purge entries older than 30 days with no terminal action; advances when sidecar growth > 256 KB/week OR any single agent's history > 100 entries).


### AD-723a-2 - WR branch consumer-side sensorium dispatch migration (Wave 161)

**Date:** 2026-05-15. **Status:** SHIPPED. **Wave:** 161. **Parents:** AD-723a-1 (Wave 148 - DM consumer-side migration; `_DM_SELF_WRAPPED_KEYS` ClassVar pattern); AD-723a-3 (Wave 160 - `SensoriumEntry.injection_zone` + wrapper metadata). **Closes:** #625.

Wave 148 (AD-723a-1) migrated the **DM** branch of `CognitiveAgent._build_user_message` to consume `SENSORIUM_REGISTRY` via the dispatcher. It deferred the **WR** (Ward Room) branch to AD-723a-2 because WR had 15 hand-rolled fragments vs DM's 13, and 0 self-wrapped sensorium entries that mapped cleanly to the `_DM_SELF_WRAPPED_KEYS` pattern at the time.

This AD ships the WR sibling: a single dispatcher call site for self-wrapped WR entries, gated by a new `_WR_SELF_WRAPPED_KEYS` ClassVar. v1 ships the tuple **empty** - there are currently 0 self-wrapped WR entries. The infrastructure is in place; the first WR-only self-wrapped registry entry will trigger non-empty values without further code changes.

**Byte-parity preserved.** With the empty selector tuple, the iteration is a no-op at runtime today - current WR prompts are byte-identical to HEAD. The byte-parity regression test verifies this.

**Insertion point.** WR branch of `_build_user_message`, immediately after the AD-573 working-memory render block and before the BF-102 cold-start system note. Same Tier-2 try/except shape as AD-723a-1's DM path. Dispatcher failure logs WARNING with the `AD-723a-2` marker and falls through to hand-rolled fragments. `self.id` is included in the warning so multi-agent log triage works.

**Phantom-API guard preserved.** `SensoriumPath.WR_ONESHOT` is the real enum member at `cognitive_agent.py:88` (Wave 160 dispatch confirmed in the WAVE-161-DISPATCH preflight). `SensoriumLayer` (PROPRIOCEPTION / INTEROCEPTION / EXTEROCEPTION) is a different enum at `cognitive_agent.py:54` and is NOT used in this AD - that was the Wave 160 phantom IDENTITY trap.

**Files:** `src/probos/cognitive/cognitive_agent.py` (`_WR_SELF_WRAPPED_KEYS` ClassVar at line ~492; WR-branch dispatcher block at line ~6163); `tests/test_ad723a_2_wr_consumer_migration.py` (new, 6 pytest tests).

**Regression gate.** All 6 prior AD-723a-1 tests in `tests/test_ad723a_1_consumer_migration.py` still pass at HEAD. This was the primary regression gate per the dispatch's wave-specific hard-stop rule.

**Forward markers.** AD-723a-2a (populate `_WR_SELF_WRAPPED_KEYS` with first real consumer - advances when any new WR-only context fragment is proposed; no current candidate as of Wave 161). AD-723a-3a (per-entry migration of non-self-wrapped fragments using `SensoriumEntry.injection_zone` from AD-723a-3) was filed Wave 160 and remains open.


### AD-722b-1 - Crew-scope auth substrate for telemetry surfaces (Wave 161)

**Date:** 2026-05-15. **Status:** SHIPPED. **Wave:** 161. **Parents:** AD-722b (Wave 142 HTTP snapshot), AD-722b-3 (Wave 159 WS diff push), AD-722b-4 (Wave 160 WS fleet stream). **Closes:** #598.

**Substrate AD.** Verify-first against HEAD confirmed: NO existing crew-scope auth dep exists anywhere in `src/probos/routers/`. Every endpoint uses bare `Depends(get_runtime)`. The only auth-adjacent string in the tree is `"captain_auth_required"` in `conn.py:57` (a status enum, not a FastAPI dependency). This AD lands the FIRST auth pattern in the codebase; subsequent waves mirror it.

**Design (Path A — single shared secret, default-OFF).** New module `src/probos/routers/auth.py` exposes two callables:
- `require_crew_scope` — FastAPI `Depends` reading `Authorization: Bearer <token>` header. Empty configured token = pass-through (auth disabled). Missing/malformed/wrong header raises HTTP 401 with structured `detail` ("missing_or_malformed_authorization" / "invalid_token").
- `verify_ws_token` — manual call inside WS handlers BEFORE `await websocket.accept()`, reads `?token=` query param. Returns False after `websocket.close(code=1008, reason="unauthorized")` on failure; True on pass.

Both use `hmac.compare_digest` for constant-time token compare (OWASP requirement). `_configured_token` defensively only honors real `str` values - `MagicMock` fixtures pre-existing in the AD-722b-* test suites fall through to empty (auth disabled), preserving backward compat. This was a real discovery during the build: the first naive `_configured_token` broke 4 AD-722b-4 fleet-telemetry tests because their MagicMock configs returned truthy non-string sentinels. The defensive `isinstance(token, str)` check is the right substrate-side fix.

**Default-OFF backward compat.** `AuthConfig.crew_scope_token: str = ""` (Pydantic field default). Empty disables auth entirely. Operators opt in by setting `auth.crew_scope_token` in `config/system.yaml`. Matches AD-721d / AD-722 feature-gate convention.

**Applied to 4 endpoints (2 HTTP + 2 WS):**
- `GET /api/agent/{id}/avatar-telemetry` (line 609 in `routers/agents.py`)
- `GET /api/agent/{id}/avatar-telemetry/history` (line 638)
- `WS /api/agent/{id}/avatar-telemetry-stream` (line 673) — `verify_ws_token` called immediately after `runtime = websocket.app.state.runtime` resolves, BEFORE the feature-gate close-checks and BEFORE `await websocket.accept()`
- `WS /api/agent/avatar-telemetry/stream` fleet endpoint (line 949) — same insertion shape

**WS handshake auth works.** The Path B scope-flag in the prompt anticipated WS handshake auth might be fragile under Starlette's pre-accept `query_params` semantics. Building this surface confirmed the pre-accept `websocket.query_params` IS populated reliably under the current Starlette version; tests pass for all four WS auth cases (disabled-allows, missing-1008, wrong-1008, correct-accepts). No split into AD-722b-1a needed.

**Files:** `src/probos/routers/auth.py` (new, ~85 lines); `src/probos/config.py` (new `AuthConfig` Pydantic model placed above `SecurityConfig` for grouping; `auth: AuthConfig = Field(default_factory=AuthConfig)` field on `SystemConfig` next to `security`); `src/probos/routers/agents.py` (import + 4 endpoint modifications); `tests/test_ad722b_1_crew_scope_auth.py` (new, 8 pytest tests — 4 HTTP + 4 WS).

**Forward markers.** AD-722b-1a (multi-Captain per-crew tokens — replace single shared secret with token store mapping captain_id → token; trigger: federation cross-mesh telemetry push lands OR more than one Captain operates the same runtime). AD-722b-1b (apply `require_crew_scope` to remaining read endpoints on agents/acm/assignments routers; trigger: AD-722b-1 ships AND any auth-required-endpoint feature request lands). AD-722b-1c (federation-bridge JWT verification — AD-480 integration; trigger: AD-480 federation framework adds cross-mesh agent reads). AD-722b-1d (token rotation + TTL; trigger: any single deployment runs > 90 days with a static secret OR security scanner flags long-lived shared-secret use).


### AD-722b-4a - HXI fleet-hook integration (Wave 161)

**Date:** 2026-05-15. **Status:** SHIPPED. **Wave:** 161. **Parent:** AD-722b-4 (Wave 160 - fleet endpoint + hook stub). **Closes:** #655.

Wave 160 shipped two pieces of fleet telemetry plumbing - the server WS endpoint `/api/agent/avatar-telemetry/stream` AND the React hook `ui/src/avatars/useFleetAvatarTelemetry.ts` - but no component imported the hook. Vite tree-shook it out of the production bundle (`ui/dist/assets/index-BDgoocuQ.js` hash unchanged across the Wave 160 deploy). This AD wires the hook into `CognitiveCanvas.tsx` so fleet frames merge into the zustand store.

**Store additions.** `useStore.avatarTelemetry: Map<string, Record<string, unknown>>` (initialized to empty Map) + new `setAvatarTelemetryFrame(agent_id, type, payload)` action. Frame contract:
- `snapshot`: replaces the per-agent entry entirely.
- `diff`: shallow-merges `payload` into the existing entry; DROPS the frame if no prior snapshot (the server's `full_snapshot_every_n` cadence guarantees a snapshot within N ticks).
- `ping`: no-op (keep-alive).
- `error`: logs `console.warn` once per frame; no store write.

**Canvas integration.** Single call site at the top of `CognitiveCanvas()`:

\\\	sx
const setAvatarTelemetryFrame = useStore((s) => s.setAvatarTelemetryFrame);
useFleetAvatarTelemetry({
  onFrame: (frame) => {
    setAvatarTelemetryFrame(frame.agent_id, frame.type, frame.payload);
  },
});
\\\

Hook is enabled by default when the canvas mounts; unmount closes the WS (handled by hook's existing useEffect cleanup).

**Per-agent path preserved.** `SelfImageTab.tsx` still uses `/api/agent/{id}/avatar-telemetry-stream` for the dense profile-view diff stream. Migration to read from `useStore.avatarTelemetry` is forward-marker AD-722b-4b. AgentNodes / Connections / Effects rendering logic unchanged in this AD - they MAY read from the unified map going forward, but adding consumers is out of scope here (wiring only).

**Bundle proof.** `ui/dist/assets/index-BDgoocuQ.js` (HEAD baseline) -> `index-D0tUvFeA.js` (post-AD). Hash change confirms the new code is in the production bundle and not tree-shaken.

**HXI Canvas regressions clear.** Tooltips (`AgentRaycastLayer.setHoveredAgent` path), bloom positioning (`SelfModBloom` reads agent positions, not telemetry), and raycasting (instanceId -> agent profile open) are all untouched by this change. The fleet hook is added as a leaf side effect at the top of `CognitiveCanvas()` - it does not alter any rendering primitive.

**Vitest gate.** `ui/src/__tests__/useStore.avatarTelemetry.test.ts` (new, 3 tests) covers the action's snapshot/diff-drop/diff-merge branches. `ui/src/__tests__/CognitiveCanvas.fleetHook.test.tsx` (new, 1 test) mocks the hook + the three.js / r3f / canvas-child modules and asserts the hook is invoked exactly once with an `onFrame` callback. `npm run build` green (640 -> 644 vitest tests, bundle hash changed).

**Files:** `ui/src/store/useStore.ts` (state field + initial value + action signature + action body); `ui/src/components/CognitiveCanvas.tsx` (import + hook call inside `CognitiveCanvas()`); `ui/src/__tests__/useStore.avatarTelemetry.test.ts` (new); `ui/src/__tests__/CognitiveCanvas.fleetHook.test.tsx` (new).

**Forward markers.** AD-722b-4b (migrate `SelfImageTab.tsx` per-agent WS consumer to read from `useStore.avatarTelemetry`, eliminating the second WebSocket - trigger: `avatarTelemetry` map reaches 2+ canvas consumers AND fleet endpoint snapshot+diff parity with per-agent endpoint is verified by integration test). AD-722b-4c (add canvas-side selectors `useAgentEmotion(agent_id)` + `useAgentWorkingState(agent_id)` so `AgentNodes` / `Connections` can render telemetry without subscribing to the full map - trigger: more than one canvas component reads `avatarTelemetry` directly AND re-render cost becomes measurable).

## Wave 162

### AD-722b-1a - Replace MagicMock(spec=SystemConfig) test fixtures with real configs; remove routers/auth.py defensive guard (Wave 162)

**Date:** 2026-05-15. **Status:** SHIPPED. **Wave:** 162. **Parent:** AD-722b-1 (Wave 161 - crew-scope auth substrate). **Closes:** #657.

Replaced 7 sites where tests constructed runtime configs as `MagicMock(spec=SystemConfig)` with real `SystemConfig()` instances - violation of the engineering principle that tests must use real configs, not mock-shaped ones. Removed the corresponding defensive `if not isinstance(token, str): return ''` guard at `src/probos/routers/auth.py:43` that existed solely to absorb mock-shaped configs. The empty-token=auth-disabled invariant is preserved by `AuthConfig.crew_scope_token` defaulting to ''.

**Sites migrated:** `tests/conftest.py:196` (shared rt fixture), `tests/test_ad437_action_space.py:209`, `tests/test_ad576_llm_unavailability.py:49`, `tests/test_circuit_breaker.py:273`, `tests/test_proactive.py:1787 + :1837`, `tests/test_proactive_quality.py:40`.

**Auth-disabled contract preserved.** Three additional test helpers (`test_ad722_avatar_telemetry._make_runtime`, `test_ad722b_websocket_push._make_runtime`, `test_ad722b4_fleet_telemetry._make_runtime`) used bare `cfg = MagicMock()` without `spec=SystemConfig`. After guard removal these returned a MagicMock for `cfg.auth.crew_scope_token` instead of the empty string the contract expected, causing 18 FastAPI tests to return 401 instead of 200/503. Fixed by setting `cfg.auth = AuthConfig()` in each helper - the real Pydantic model returns the empty default and auth stays disabled. Minimum-touch consistent with Section 7 of the prompt (reconstruct minimal real sub-config; never re-introduce MagicMock at the `config=` boundary).

**Files:** `tests/conftest.py`, `tests/test_ad437_action_space.py`, `tests/test_ad576_llm_unavailability.py`, `tests/test_circuit_breaker.py`, `tests/test_proactive.py`, `tests/test_proactive_quality.py`, `tests/test_ad722_avatar_telemetry.py`, `tests/test_ad722b_websocket_push.py`, `tests/test_ad722b4_fleet_telemetry.py`, `src/probos/routers/auth.py`.

**Net test delta:** 0. Full parallel gate green; only documented flakes remain (skill_agent + task_scheduler + occasional dreaming/ward_room serial-pass).

### AD-729a - Peer-observation Standing Orders extension (Wave 162)

**Date:** 2026-05-15. **Status:** SHIPPED. **Wave:** 162. **Parent Code of Conduct:** AD-489. **Closes:** #588.

Extends Standing Orders to cover peer observation - a class of crew action introduced by AD-729's capability surface. Captain ruling 2026-05-10 specified the five sections verbatim; this AD authors them, ratifies them, and wires them into the existing AD-586 prompt-assembly path via cross-references from `ship.md` and `counselor.md`.

**Sections.** (1) Operational observation (always permitted, channel-appropriate, descriptive not evaluative). (2) Personal commentary (requires explicit permission-to-speak-freely; cross-rank elevated care; Counselor reviews drift toward judgment). (3) Prohibited behavior (cascade observation, aesthetic conformity pressure, privileged-tier leakage, static impressions). (4) Permission-to-speak-freely protocol (`[PERMISSION_REQUEST]` / `[PERMISSION_GRANTED]` / `[PERMISSION_DENIED]` DSL; single-exchange scope; repeated denial is observed-officer privilege, repeated requesting despite denial is Counselor-actionable). (5) Captain and chain-of-command exceptions (Captain bypasses request; department heads bypass for operational only; all subject to Counselor pattern review).

**Wiring.** No new prompt-assembly code - the file lives in `config/standing_orders/` and is picked up by the AD-586 framework already in place. `ship.md` and `counselor.md` cross-references make the file discoverable from the Code of Conduct and the Counselor's standing orders.

**Tests.** +7 pytest in `tests/test_ad729a_peer_observation_standing_orders.py` - one for file existence + four for section phrases + one for permission-protocol DSL tokens + one for `ship.md` cross-reference. All green at `-n 0`.

**Files:** `config/standing_orders/peer_observation.md` (new), `config/standing_orders/ship.md` (1-line append), `config/standing_orders/counselor.md` (pattern-review section append), `tests/test_ad729a_peer_observation_standing_orders.py` (new).

**Unblocks:** AD-729 (capability AD) advances to build. AD-729b (training) and AD-729c (Counselor monitoring) remain sibling forward markers - this AD authors the rules; the others teach and enforce them.

### AD-720d-2.1 - Captain vision-capability approval flow (Wave 162)

**Date:** 2026-05-15. **Status:** SHIPPED. **Wave:** 162. **Parent:** AD-720d-2 (Wave 154 - static-default vision_capable field). **Closes:** #645.

Adds the Captain-mediated propose-and-approve flow for runtime vision-capability enablement. Mirrors the AD-718a / AD-721d-1 pattern: agent requests vision capability with a rationale, Captain approves or denies, and on approval `CrewProfile.vision_capable` flips to True for that agent's type in the CallsignRegistry profile dict. The chat-time gate at `routers/agents.py:1391` (existing AD-720d-2 code) immediately reflects the new value.

**Endpoints.** Three new under `/api/agent/{agent_id}`:
- `POST vision-capability/propose` (body: `{rationale: str <=280 chars}`) returns `{agent_id, rationale, proposal_id, proposed_at}`.
- `POST vision-capability/approve?proposal_id=X` (body: `{approve: bool, reason: str <=280 chars}`) flips registry on approve, marks proposal resolved either way.
- `GET vision-capability/history` returns chronological proposal entries.

**Persistence.** New `src/probos/avatars/vision_proposal_history.py` mirrors the AD-721d-4 sidecar pattern (module-level state + RLock + atomic temp-file + `os.replace`). Configured at runtime startup via the new `AvatarsConfig.vision_proposal_history_path` field (defaults to `<data_dir>/vision_proposal_history.json`). Tier-2 log-and-degrade on disk failure - in-memory state stays authoritative.

**Registry.** New public method `CallsignRegistry.set_vision_capable(agent_id, value, *, reason='')` resolves agent_id to agent_type via the bound AgentRegistry, then updates the `_type_to_profile[agent_type]['vision_capable']` dict entry. Logs the flip at INFO level for audit. Reason does NOT flow into trust or Hebbian (this is an authorization grant, not a behavior observation).

**Events.** Two new `EventType` values: `VISION_CAPABILITY_PROPOSED` and `VISION_CAPABILITY_RESOLVED`. Emitted via `runtime.emit_event` (AD-680 stable public method - direct call, no hasattr guard per pass-1 review fix).

**Tests.** +8 pytest in `tests/test_ad720d_2_1_vision_approval.py`. All use real `CallsignRegistry` + real `AuthConfig()` (AD-722b-1a). Coverage: propose creates entry, approve flips registry, deny leaves registry, unknown proposal 404, already-resolved 404, persistence across configure, rationale length validation, history endpoint listing.

**AD-731 invariant.** No image bytes touch this code path. Vision capability is an authorization bit; image transport remains AttachmentStore SHA-256 refs.

**Files:** `src/probos/api_models.py` (3 new models), `src/probos/events.py` (+2 EventType values), `src/probos/config.py` (+ vision_proposal_history_path on AvatarsConfig), `src/probos/crew_profile.py` (+ set_vision_capable method), `src/probos/avatars/vision_proposal_history.py` (new module), `src/probos/runtime.py` (configure call), `src/probos/routers/agents.py` (3 new handlers), `tests/test_ad720d_2_1_vision_approval.py` (new).

**Forward markers.** AD-720d-2.1a (HXI UI surface for Captain pending-approval list - trigger: Captain operates ProbOS for >7 days with multiple pending proposals). AD-720d-2.1b (auto-deny TTL when Captain unresponsive >N hours - trigger: ProbOS adopts autonomous-Captain mode).

### AD-706c-1 - Browser Tool visual verify via vision tier (Wave 162)

**Date:** 2026-05-15. **Status:** SHIPPED. **Wave:** 162. **Parent:** AD-706 (BrowserTool, Wave 132). **Closes:** #642.

Adds a new `verify(expectation: str)` action to BrowserTool's action vocabulary (10 -> 11). Tier-1 classification (read-only, no Captain ACK). The action captures a screenshot via Playwright, stores it through `AttachmentStore.write` keyed by SHA-256 (AD-731 invariant), calls the vision tier with the screenshot and a JSON-shaped prompt, and parses the response into `{ok: bool | None, observation: str, screenshot_ref: str, skipped_reason: str | None}`. The agent's expectation is truncated at 500 chars; empty expectation short-circuits to skipped without calling the LLM.

**Tier-2 honest-degrade.** Six dedicated skipped_reason values - `missing_expectation`, `session_not_started`, `screenshot_error`, `attachment_store_unavailable`, `attachment_store_write_error`, `vision_unconfigured`, `vision_check_error`, `vision_unavailable`. NEVER raises. Verification is observational; the browser action sequence remains load-bearing.

**Vision LLM call shape.** Reuses `build_multimodal_messages` (BF-268 OpenAI shape, AD-731 ref resolution) + `llm_client.complete(LLMRequest(tier='vision'))`. No new LLM client methods invented. The screenshot's sha256 ref is passed as a single attachment_id; `mime_lookup` is hard-coded to image/png.

**Wiring.** BrowserTool constructor gained an optional `runtime: Any | None = None` parameter. `invoke()` special-cases `action == 'verify'` and dispatches to `action_verify(session, params, *, runtime, emit_event)` with the held runtime reference; all other actions stay on the existing `_HANDLERS` dispatch. `startup/finalize.py` now passes `runtime=runtime` to BrowserTool's constructor.

**Events.** New `EventType.BROWSER_VERIFY_OBSERVED` emitted on every successful or honest-degrade verify call. The existing `BROWSER_ACTION_EXECUTED` emit path is preserved (the audit log records every action).

**Tests.** +10 pytest in `tests/test_ad706c_1_browser_verify.py`. Covers: tier-1 classification, happy-path ok=true/false, missing expectation, 500-char truncation, vision unconfigured, LLM raises, AD-731 sha256 invariant on AttachmentStore, both event types emit, malformed-JSON parse fallback.

**Out of scope.** Click-target prediction (AD-706c-2, #643 - vision tells the agent where to click). Cloud vision API integration (forward marker AD-706c-3, Anthropic computer-use beta). DOM-less surfaces (Flash, Canvas-heavy SPAs).

**Files:** `src/probos/events.py` (+ BROWSER_VERIFY_OBSERVED), `src/probos/tools/browser/actions.py` (action_verify + _parse_verify_response + verify in classify_action silent set), `src/probos/tools/browser/tool.py` (runtime ctor param + verify in action enum + special-case dispatch + expectation in input_schema), `src/probos/startup/finalize.py` (pass runtime to BrowserTool), `tests/test_ad706c_1_browser_verify.py` (new, 10 tests).

**Forward markers.** AD-706c-1a (journal aggregation for verification pass/fail rates - trigger: AD-674 graduated-initiative calibration consumer needs the signal). AD-706c-3 (Anthropic computer-use beta - trigger: operator configures cloud key + opts in via explicit flag).

### AD-722a-1 - Vision-LLM intent-vs-render divergence detector (Wave 162)

**Date:** 2026-05-15. **Status:** SHIPPED (detector + runtime construction; default-OFF flag; DivergenceDetector callsite wiring deferred to AD-721i). **Wave:** 162. **Parent:** AD-722a v1 (rule-table detector, Wave 143). **Closes:** #610.

Adds a vision-LLM extension to the AD-722a divergence family: compares the agent's self-tagged intent against the rendered avatar image via a vision-tier LLM call. The rule-table detector (AD-722a v1) catches structured mismatches; this detector catches semantic mismatches the rules can't see (the LLM said warm, modulation fired warm, but the render still doesn't read as warm to a human).

**Module.** New `src/probos/avatars/vision_intent_divergence.py` exports three primitives:
- `VisionIntentDivergenceDetector` - the detector class, Tier-2 throughout (NEVER raises).
- `VisionLLMRateLimit` - class-level shared rate-limit store keyed by `(scope, agent_id)`. Wave 162 step #6 (AD-722e-2 self-render verify) inherits this primitive with a different scope - one budget per agent across all vision-LLM observability uses.
- `is_render_phrased(observation: str) -> bool` - AD-727 rule #8 phrasing-regex enforcer; True iff the observation is NOT agent-as-subject. Used by the parse path to reject violations.

**Config.** Two new fields on `AvatarsConfig`: `vision_intent_divergence_enabled` (default False - transitional gate per Wave 10 convention #14) and `vision_intent_divergence_max_per_hour_per_agent` (default 3 - AD-728 cost ceiling).

**AD-727 compliance.**
- Rule #1 (REASONING-vs-OUTPUT): authorized by inheritance from AD-722a v1; OUTPUT is the rendered image.
- Rule #5 (backend-server-side render only): `detect()` requires `provenance_backend=True`; non-backend refs short-circuit with `skipped_reason='provenance_invalid'`.
- Rule #8 (OUTPUT-as-subject phrasing): observations matching the agent-as-subject regex are rejected with `skipped_reason='phrasing_violation'`.

**AD-731 invariant.** Refs only; the detector takes a SHA-256 ref string and (when an AttachmentStore is bound) routes through `build_multimodal_messages` for OpenAI-shape resolution at the vendor boundary. Test `test_attachment_ref_not_inline_bytes` proves the contract.

**Honest-degrade skipped_reason values.** `provenance_invalid` | `rate_limit` | `tier_unavailable` | `phrasing_violation` | `parse_error`.

**Events.** New `EventType.VISION_INTENT_DIVERGENCE_OBSERVED` registered for future emit at the AD-722a callsite (Section 2 of the prompt - deferred until AD-721i backend renderer ref-lookup is stable).

**Runtime wiring.** `self.vision_intent_divergence_detector` constructed at runtime startup (with Tier-2 log-and-degrade if construction fails). Always available for opt-in callers; the default-OFF gate sits on `AvatarsConfig.vision_intent_divergence_enabled` and is read at callsite, not construction.

**What was NOT built.** Section 2 (`DivergenceDetector` callsite wiring) depends on AD-721i's stable backend renderer ref-lookup surface. The detector ships; the live wire-up will land in a follow-up AD once AD-721i is in place. Default-OFF flag ensures no behavior change at HEAD.

**Tests.** +10 pytest in `tests/test_ad722a_1_vision_intent_divergence.py`. Coverage: happy-path match, happy-path mismatch, 3/hr rate-limit cap, rate-limit window expiry, provenance-invalid short-circuit, tier-unavailable honest-degrade, phrasing-regex enforcement, default-OFF flag regression, AD-731 ref-not-bytes invariant, `is_render_phrased` helper boundary cases.

**Files:** `src/probos/events.py` (+ VISION_INTENT_DIVERGENCE_OBSERVED), `src/probos/config.py` (+ 2 AvatarsConfig fields), `src/probos/avatars/vision_intent_divergence.py` (new), `src/probos/runtime.py` (construct detector at startup), `tests/test_ad722a_1_vision_intent_divergence.py` (new, 10 tests).

**Forward markers.** AD-722a-1a (HXI surface for vision-divergence events in SelfImageTab - trigger: AD-721i ships AND vision_intent_divergence_enabled flips True).

### AD-722e-2 - Vision-LLM self-render coherence verifier (Wave 162)

**Date:** 2026-05-15. **Status:** SHIPPED (verifier + runtime construction; default-OFF; self_perception.py wire-up deferred to AD-721i). **Wave:** 162. **Parent:** AD-722e v1 (deterministic self-projection). **Closes:** #644.

Adds a vision-LLM extension to the AD-722e self-perception family: compares the agent's digital state (avatar DSL summary) against the backend render via a vision-tier LLM call. Surfaces drift as a `self_perception` observation block when the integration enabled flag is flipped True.

**Module.** New `src/probos/cognitive/self_render_verify.py` with `SelfRenderVerifier` + `RenderCoherenceObservation` dataclass. REUSES `VisionLLMRateLimit` and `is_render_phrased` from `probos.avatars.vision_intent_divergence` (AD-722a-1) - one budget per agent across all vision-LLM observability uses (different `scope` keys keep budgets keyed correctly).

**Config.** Two new `AvatarsConfig` fields: `self_render_verify_enabled` (default False) + `self_render_verify_max_per_hour_per_agent` (default 3, AD-728 ceiling).

**AD-727 compliance.**
- Rule #1 (READ-ONLY on trust + Hebbian): digital-vs-render is OUTPUT-vs-OUTPUT, NOT REASONING-vs-OUTPUT - trust/Hebbian wiring NOT authorized. Verified by a source-scan regression test (`test_read_only_on_trust`) that grep-asserts the module imports nothing from trust_network / hebbian_router / record_outcome / update_weight.
- Rule #5 (backend-server-side only): `provenance_backend=True` required; short-circuits otherwise.
- Rule #8 (render-as-subject phrasing): observations matching agent-as-subject regex (she/he/they/role + looks/appears/seems/is) are rejected with `skipped_reason='phrasing_violation'`. Proper-name + verb constructions are NOT caught (deliberate - agents are referenced by name in render-subject sentences).
- Joint review: inherited from AD-722e parent.

**AD-731 invariant.** Refs only. Verifier takes a SHA-256 ref string and routes through `build_multimodal_messages` for OpenAI-shape resolution at the vendor boundary.

**Honest-degrade skipped_reason values.** `provenance_invalid` | `rate_limit` | `tier_unavailable` | `phrasing_violation` | `parse_error`. NEVER raises; `coherent=True` is the conservative default on honest-degrade.

**Events.** New `EventType.SELF_RENDER_COHERENCE_OBSERVED` registered for future emit at the self_perception callsite (Section 2 of the prompt - deferred until AD-721i backend renderer ref-lookup is stable).

**Runtime wiring.** `self.self_render_verifier` constructed at runtime startup with Tier-2 log-and-degrade; default-OFF gate sits on `AvatarsConfig.self_render_verify_enabled`.

**What was NOT built.** Section 2 (`self_perception.py` projection-builder wire-up) - depends on AD-721i's stable backend renderer ref-lookup surface. Detector ships; live wire-up follows in a sub-AD once AD-721i is in place.

**Tests.** +9 pytest in `tests/test_ad722e_2_self_render_verify.py`. Coverage: coherent path, incoherent + render-subject phrasing, agent-as-subject phrasing rejection, 3/hr rate-limit, provenance enforcement, tier unavailable honest-degrade, default-OFF flag regression, AD-727 rule #1 source-scan, AD-731 ref invariant.

**Files:** `src/probos/events.py` (+ SELF_RENDER_COHERENCE_OBSERVED), `src/probos/config.py` (+ 2 AvatarsConfig fields), `src/probos/cognitive/self_render_verify.py` (new), `src/probos/runtime.py` (construct verifier at startup), `tests/test_ad722e_2_self_render_verify.py` (new, 9 tests).

**Cross-reference.** AD-728 (vision-LLM mirror primitive) - this AD and AD-722a-1 both consume the same shared `VisionLLMRateLimit` primitive; AD-728's eventual build will consolidate it into a dedicated `VisionLLMBudget` module (forward marker AD-728-1 from the Wave 162 dispatch).

**Forward markers.** AD-722e-2a (HXI SelfImageTab surface for render-coherence observations - trigger: AD-721i ships AND self_render_verify_enabled flips True).

### AD-722a-2 - Chain-path divergence detection at compose-step emit (Wave 162)

**Date:** 2026-05-15. **Status:** SHIPPED. **Wave:** 162. **Parent:** AD-722a (Wave 143 DM-path divergence). **Closes:** #611.

Removes AD-722a's `(f) chain reply-emission has no equivalent single emit point - chain-path divergence is forward marker AD-722a-2` deferral. AD-723 (Wave 144) shipped sensorium dispatch unification but only for INPUT/context-assembly; this AD adds the canonical chain-OUTPUT emit hook.

**New public surface on CognitiveAgent.**
- `mark_chain_output_emitted(output_text: str, *, audience: str, intent_self_tag: str | None = None, applied_modulation_rules: list[str] | None = None) -> None` - sibling of `mark_reply_emitted` (DM-path).
- `chain_divergence_buffer_for(audience: str) -> list[DivergenceResult]` - channel-scoped read accessor (returns list copy; no shared mutable state).
- `_chain_divergence_buffer: dict[str, deque[DivergenceResult]]` initialized in `__init__`; per-audience `deque(maxlen=8)`.

**Wiring.** The chain compose consumer at `cognitive_agent.py:2934` (Phase 2b of _execute_sub_task_chain) now calls the hook immediately after `compose_text = chain_result.get('llm_output', '')`. Audience derived from `chain_result.get('audience', 'sensorium')`; intent + rules read from `chain_result['intent_self_tag']` / `chain_result['applied_modulation_rules']`. No new chain_result fields invented in this AD - missing signals short-circuit the hook (returns without recording). Forward marker AD-722a-2a tracks the future work to thread these signals through `_execute_sub_task_chain` reliably.

**Scoring.** Uses the pure `compute_divergence(intent_emotion, applied_fired_rules)` function from AD-722a v1 - no parallel implementation. DivergenceResult's `magnitude` field (0.0..1.0) drives the emit gate; magnitude > 0 = divergence observed.

**Events.** New `EventType.DIVERGENCE_OBSERVED_CHAIN` with payload `{agent_id, audience, intent, magnitude, path_tag: 'chain'}`. The `path_tag` field disambiguates chain-path events from any future DM-path events (the DM-path emit name is preserved as-is; lower-touch Section 0 choice).

**AD-727 compliance.** Rule #1 (REASONING-vs-OUTPUT signal class) authorized by inheritance from AD-722a v1. Rule #8 (OUTPUT-as-subject phrasing) - the event payload exposes intent/magnitude facts only; no rendered observation text in this AD (rendering deferred to AD-722a-2's interoception suffix builder work, sibling forward marker). Rule h (no cross-channel surface pollution) enforced by per-audience buffer partitioning.

**DM-path unchanged.** AD-722a v1 `apply_divergence_check` + `mark_reply_emitted` are untouched. The chain hook is purely additive. Regression test verifies DM state is not mutated by chain emit.

**Tests.** +10 pytest in `tests/test_ad722a_2_chain_divergence.py`. Test scaffold binds the real `mark_chain_output_emitted` method onto a minimal stub (no full CognitiveAgent boot needed). Coverage: matching intent (no event), diverging intent (event fires), per-audience buffer isolation, DM-path unchanged regression, audience-scoped buffer reads, AD-727 #8 phrasing-free payload, path_tag='chain' contract, maxlen=8 capacity, runtime-None no-op, missing-signal short-circuit.

**Files:** `src/probos/events.py` (+ DIVERGENCE_OBSERVED_CHAIN), `src/probos/cognitive/cognitive_agent.py` (mark_chain_output_emitted + chain_divergence_buffer_for + __init__ buffer state + Phase 2b callsite), `tests/test_ad722a_2_chain_divergence.py` (new, 10 tests).

**Forward markers.** AD-722a-2a (thread intent_self_tag + applied_modulation_rules through _execute_sub_task_chain - trigger: chain phases reliably populate these signals AND multi-channel interoception consumers request the data).

### AD-721d-2 - Counselor-mediated avatar revision (Wave 162)

**Date:** 2026-05-15. **Status:** SHIPPED (server-side; HXI surface forward-marked AD-721d-2c). **Wave:** 162. **Parent:** AD-721d-1 (Wave 145 Captain-driven DSL revision). **Closes:** #618.

Adds the Counselor-mediated path for avatar revision so the Captain can say "Counselor, Echo's avatar feels too formal - work with her on something warmer" and the Counselor mediates. The Counselor refines the Captain's hint via a standard-tier LLM call and forwards the refined hint to the target agent's existing AD-721d-1 `propose_appearance(captain_note=...)` path.

**Intent.** New `mediate_appearance_revision` IntentDescriptor registered on `CounselorAgent.intent_descriptors` and added to `_handled_intents`. Params: `target_agent_id` + `captain_hint` (<=280 chars). `requires_consensus=False` (mediation is read-only / produces a NEW proposal via the existing AD-721d-1 path).

**Handler.** New `CounselorAgent._mediate_appearance_revision(*, target_agent_id, captain_hint)` method invoked from `act()` when `plan['intent'] == 'mediate_appearance_revision'`. Resolves target via `runtime.registry.get(agent_id)` (real method, no phantom API), reads target's DSL through `agent.appearance.dsl` (with `runtime.profile_store` fallback), refines via `runtime.llm_client.complete(LLMRequest(tier='standard'))`, and invokes `target_agent.propose_appearance(captain_note=refined)` to land in the AD-721d-1 proposal sidecar. Tier-2 throughout - 7 distinct `reason` codes (invalid_hint_length, target_agent_unknown, target_dsl_unavailable, refinement_failed, refinement_empty, target_not_proposable, propose_failed).

**Iteration accounting.** Reads `proposal_history.iteration_count(target_agent_id)` (real public function) into the response payload so the Captain sees the iteration the new proposal consumed. Mediated revisions count against the AD-721d-1 cap exactly like Captain-driven ones (the iteration counter is on the target, not the mediator).

**API.** New `POST /api/agent/{agent_id}/appearance/mediate` endpoint where the path agent_id is the MEDIATOR (typically the Counselor). Uses `runtime.intent_bus.send(IntentMessage(target_agent_id=mediator, intent='mediate_appearance_revision', params={...}))` per pass-1 fix - NOT broadcast (broadcast would fan out to all subscribers and re-trigger the mediator when more than one Counselor-class agent is registered). Returns 503 on bus failure or null result, 422 on mediator-side reason codes.

**Events.** New `EventType.APPEARANCE_REVISION_MEDIATED` emitted by the Counselor with payload `{target_agent_id, captain_hint, refined_hint, proposal_iteration}`.

**HXI deferral.** The dispatch's small "Counselor-mediated revision" button on CrewAvatarPopout + Vitest tests are deferred to forward marker AD-721d-2c. Server-side flow is functionally complete; HXI surface is polish that doesn't block acceptance.

**Tests.** +8 pytest in `tests/test_ad721d_2_counselor_mediated_revision.py`. Coverage: happy path (refinement + propose + event), empty hint 422, over-280 hint 422, target unknown, DSL unavailable, refinement empty, propose failure, endpoint contract test verifying `intent_bus.send` is called with `IntentMessage.target_agent_id=mediator` (the pass-1 fix is regression-protected).

**Files:** `src/probos/events.py` (+ APPEARANCE_REVISION_MEDIATED), `src/probos/api_models.py` (+ MediateAppearanceRevision), `src/probos/cognitive/counselor.py` (intent_descriptors + _handled_intents + act() route + _mediate_appearance_revision method), `src/probos/routers/agents.py` (+ mediate endpoint), `tests/test_ad721d_2_counselor_mediated_revision.py` (new, 8 tests).

**Forward markers.** AD-721d-2a (`source` field on ProposalEntry when AD-721d-1 doesn't carry one - trigger: Captain audit signal needed). AD-721d-2b (per-domain mediator selection - trigger: >=2 domain agents need their own avatar palettes mediated). AD-721d-2c (HXI button + modal for CrewAvatarPopout - trigger: Captain operates mediated path more than Captain-driven OR HXI polish wave scheduled).

### AD-720a-1 - PDF / DOCX / XLSX document text extraction (Wave 162)

**Date:** 2026-05-15. **Status:** SHIPPED. **Wave:** 162. **Parent:** AD-720d (Wave 139 text/JSON/CSV extraction). **Closes:** #562.

Replaces `raise NotImplementedError('AD-720a-1: PDF extraction not yet wired')` with a real dispatch table covering PDF, DOCX, XLSX. The flag `AttachmentsConfig.pdf_extraction_enabled` (already scaffolded in HEAD) gates all three MIMEs through `vision_dispatch.py` - default-OFF transitional per Wave 10 convention #14.

**License posture (Captain-approved at acceptance).** Three permissive deps verified via `pip show` at install time:
- `pypdf>=4.0` - BSD-3-Clause (`License-Expression: BSD-3-Clause` confirmed)
- `python-docx>=1.1` - MIT (`License: MIT` confirmed)
- `openpyxl>=3.1` - MIT (`License: MIT` confirmed)

All three are Apache-2.0-compatible per the Captain rule (MIT > BSD > Apache). Added to `pyproject.toml` `[project.dependencies]`. `THIRD_PARTY_LICENSES.md` updated with three new entries.

**Helpers.** Three new functions in `src/probos/cognitive/text_extractor.py`:
- `_extract_pdf(blob, max_bytes)` - page-by-page via `pypdf.PdfReader`, capped at 100 pages. Per-page exceptions logged + emit empty page text (no silent skip).
- `_extract_docx(blob, max_bytes)` - paragraphs + table cells (cell-by-cell, '' | '' separator) via `docx.Document`.
- `_extract_xlsx(blob, max_bytes)` - `=== Sheet: <name> ===` headers + rows via `openpyxl.load_workbook(read_only=True, data_only=True)`, capped at 10k rows total.

All three honor `max_bytes` at the UTF-8 boundary and emit `[TRUNCATED]` suffix on cap-hit.

**Dispatch.** New `_DOCUMENT_DISPATCH: dict[str, callable]` mapping the three MIMEs to helpers. `extract_text` consults the dispatch first; misses fall through to the AD-720d text/json branch; unknown MIME still raises `ValueError('unsupported MIME')` (regression-tested).

**Tier-2 honest-degrade.** Parser exceptions in any of the three helpers bubble out of `extract_text` as `ValueError('AD-720a-1: failed to extract text from <mime>: <err>')` - existing vision_dispatch / chat caller pattern decides whether to surface to the user or fall through to the `<ATTACHMENT ... note=deferred />` stub.

**Gate wiring.** `vision_dispatch.py:242` previously short-circuited only `application/pdf` when the flag was False; this AD extends the gate to DOCX + XLSX MIMEs as well (consistent UX - all three document types respect the same flag).

**AD-731 invariant.** Helpers operate on `blob: bytes` already-resolved from `AttachmentStore` - no inline bytes through the bus. Image attachments remain on the AD-731 SHA-256 ref path (vision tier, untouched).

**Tests.** +12 pytest in `tests/test_ad720a_1_document_extraction.py` using in-memory PDF/DOCX/XLSX fixtures (pypdf.PdfWriter / Document() / Workbook()). Coverage: 3 happy paths, 3 byte caps, 2 page/row caps, 3 corrupt-bytes raises, 1 dispatch-unknown-MIME regression, 1 default-OFF flag regression. All use real `SystemConfig()` per AD-722b-1a (no MagicMock).

**Files:** `pyproject.toml` (+3 deps), `src/probos/cognitive/text_extractor.py` (rewritten with dispatch + 3 helpers; AD-720d branches unchanged), `src/probos/cognitive/vision_dispatch.py` (extended gate to cover DOCX + XLSX), `THIRD_PARTY_LICENSES.md` (+3 entries), `tests/test_ad720a_1_document_extraction.py` (new, 12 tests).

**Forward markers.** AD-720a-1-1 (flip `pdf_extraction_enabled` to True after operator feedback confirms quality). AD-720a-1-2 (OCR pipeline for scanned PDFs - image-bearing pages where pypdf returns empty text - trigger: when scanned PDFs are a real workload).

### AD-722b-5 - Federation cross-mesh telemetry push (LOCAL-MESH PORTION) (Wave 162)

**Date:** 2026-05-15. **Status:** SHIPPED (local-mesh portion; federation hop forward-marked AD-722b-5a). **Wave:** 162. **Parent:** AD-722b (per-agent WS) + AD-722b-4 (fleet WS) + AD-480 family (federation framework). **Closes:** #602.

**Section 0 CONDITIONAL gate verdict.** Per the prompt's pre-flight, `FederationBridge` was grepped for streaming/relay primitives (forward_stream / relay_ws / forward_telemetry). The bridge exposes ONLY `forward_intent` (single-shot RPC), `request_chain`, `request_transfer`, and `_gossip_loop`. No streaming primitive exists. Per the dispatch's instruction ("if federation streaming primitive isn't ready, ship the local-mesh portion only and forward-marker the federation hop"), this AD ships the local-mesh subscription + dispatch plumbing and forward-marks the bridge wiring as AD-722b-5a.

**Module.** New `src/probos/federation/telemetry_relay.py` exports:
- `PeerTelemetrySubscription` - frozen dataclass: peer_id + agent_ids frozenset.
- `FederationTelemetryRelay` - subscription store + per-peer outbound rate-limit (default 10 frames/sec/peer, configurable via constructor) + agent_id filter + pluggable emit callback.

**Public surface.** `register_peer(peer_id, agent_ids)`, `unregister_peer(peer_id)`, `set_emit_callback(callback)`, `on_local_telemetry_frame(*, agent_id, frame_type, payload) -> int` (returns number of peers dispatched-to). Test-observable: `dispatch_log()` returns recorded (peer_id, agent_id, frame) triples when the default callback is in effect; `reset_dispatch_log()` clears.

**Future federation wiring.** `set_emit_callback` is the AD-722b-5a hookup point. When AD-480e/g lands a streaming primitive (likely `FederationBridge.forward_telemetry(peer_id, frame)`), the only change required here is wiring that method into `set_emit_callback`. Zero changes to subscription, rate-limit, or dispatch logic.

**Tier-2 throughout.** Per-peer emit failures log + degrade; never raise. The user-facing telemetry pipeline never breaks due to a misbehaving peer.

**Tests.** +8 pytest in `tests/test_ad722b_5_federation_telemetry.py`. Coverage: peer registration records subscription, agent_id filter, no-subscribers zero return, multicast to two peers, rate-limit cap (4th frame blocked), rate-limit window recovery after monkeypatch'd time advance, unregister stops emits, custom callback contract bypasses default dispatch_log.

**Files:** `src/probos/federation/telemetry_relay.py` (new), `tests/test_ad722b_5_federation_telemetry.py` (new, 8 tests).

**Forward markers.**
- AD-722b-5a (wire FederationTelemetryRelay.set_emit_callback to FederationBridge.forward_telemetry - trigger: AD-480e/g matures the bridge with a streaming/relay primitive).
- AD-722b-5b (HXI surface to render remote agents with origin_mesh_id badge - trigger: AD-722b-5a ships AND multi-mesh deployments are in production).

### AD-728 - Vision-LLM render-coherence mirror function (Wave 163)

**Date:** 2026-05-15. **Status:** SHIPPED. **Wave:** 163. **Closes:** #586.

**Primitive.** Generalizes the AD-722e-2 self-render-verify pattern into a trigger-driven mirror function with three triggers (captain_command / divergence_followup / agent_initiated_stub) and a new alert payload type. PRIMITIVE for Wave 163 - AD-722a-6 and AD-729 family consume the EventType.RENDER_DIVERGENCE_OBSERVED shape.

**Module.** New `src/probos/avatars/render_verification.py` exports `RenderCoherenceResult` (frozen dataclass with `agent_id`, `trigger`, `coherent` (bool|None), `digital_description`, `analog_description`, `divergence_summary`, `skipped_reason`, `timestamp`) and the module-level async function `verify_render_coherence(*, runtime, agent_id, trigger, digital_state_summary, backend_render_ref)`.

**Reuse.** REUSES AD-722a-1's `VisionLLMRateLimit` (scope `render_verification`) and `is_render_phrased()` (AD-727 rule #8 phrasing helper). NO new rate-limit class; one shared budget per agent across vision-observability detectors.

**Triggers.** `captain_command` wired through new `/verify-render <agent_id>` slash command in `experience/shell.py`. `divergence_followup` gated by `cfg.avatars.render_verification_followup_enabled` (default False) - actual VisionIntentDivergenceDetector post-hook wiring deferred (path exists, awaiting AD-721i renderer telemetry). `agent_initiated_stub` hard-rejected with `skipped_reason='agent_initiated_disabled'` (path exists for future flip).

**Config.** Three new `AvatarsConfig` fields: `render_verification_enabled: bool = False` (default-OFF transitional), `render_verification_max_per_hour_per_agent: int = 3` (ge=0, 0 disables), `render_verification_followup_enabled: bool = False`. No new top-level config class - phantom `BridgeAlertsConfig` reference from issue body explicitly dropped per pre-flight verify.

**Event.** New `EventType.RENDER_DIVERGENCE_OBSERVED` inserted between `VISION_INTENT_DIVERGENCE_OBSERVED` (AD-722a-1) and `SELF_RENDER_COHERENCE_OBSERVED` (AD-722e-2). Payload carries `agent_id`, `trigger`, `digital_description`, `analog_description`, `divergence_summary`, `severity` (low/high based on summary length), `timestamp`.

**Phrasing.** Hard Rule 8 - render-as-subject. When the vision LLM returns agent-as-subject analog text (caught by `is_render_phrased` regex), the function re-prompts ONCE with an explicit constraint suffix; if the retry also fails the regex, the analog is dropped with `skipped_reason='phrasing_rejected'` and no event is emitted.

**Cost discipline.** Coherent observations are NOT logged - only divergent observations emit `RENDER_DIVERGENCE_OBSERVED`. The cost of a 'nothing wrong' call is exactly one vision-LLM call; nothing else.

**AD-731 invariant.** Image bytes flow through `AttachmentStore` SHA-256 refs via `build_multimodal_messages`; the module's own source-scan test asserts no `b64encode`/`base64.b64` token in the module. Test 10 is the regression guard.

**AD-727 rule #1.** READ-ONLY on reputation + associative routing. The module source-scan test asserts no `trust_network` / `hebbian` token anywhere in the file.

**Tier-2 throughout.** Every failure mode (unknown trigger, disabled, followup disabled, missing renderer ref, no llm_client, rate-limit exhausted, vision tier exception, parse error, phrasing rejected) returns a `RenderCoherenceResult` with `skipped_reason` set. The function NEVER raises.

**Tests.** +15 pytest in `tests/test_ad728_render_verification.py`. Coverage: coherent no-event-emitted, divergent-emits-event, disabled honest-degrade, backend renderer unavailable, vision tier failure, rate-limit exhaustion, all three trigger paths (captain_command happy, divergence_followup disabled-by-default, divergence_followup enabled passes through, agent_initiated_stub hard-rejected), payload integrity, phrasing-rejected-after-reprompt, AD-731 invariant source-scan, AD-727 rule #1 source-scan, coherent-does-not-emit-event. Real `SystemConfig()` fixtures per AD-722b-1a.

**Files.** `src/probos/events.py` (+1 EventType), `src/probos/config.py` (+3 AvatarsConfig fields), `src/probos/avatars/render_verification.py` (new, 280 lines), `src/probos/experience/shell.py` (+1 slash command + handler), `tests/test_ad728_render_verification.py` (new, 15 tests).

**Forward markers.** AD-728a (richer embedding-distance coherence scoring - trigger: RENDER_DIVERGENCE_OBSERVED event volume exceeds 50/quarter). AD-728b (auto-correction proposals - trigger: AD-728a embedding scoring stable AND drift pattern catalog >=10 categorized causes).

### AD-729 - Peer avatar perception governance contract (Wave 163)

**Date:** 2026-05-15. **Status:** SHIPPED. **Wave:** 163. **Closes:** #587.

**Scope discipline.** Wave 163 ships the contract: DSL, dataclass, four mechanical floors, capability surface stub, RecordsStore artifact, federation gate. The Standing Orders content (AD-729a, shipped Wave 162) supplies the conduct policy; AD-729b training-completion flag and AD-729c Counselor pattern-monitoring ship in this wave too.

**DSL.** New `ObservationRegister` enum (OPERATIONAL / PERSONAL). OPERATIONAL is work-related and requires no permission; PERSONAL is character/style/wellbeing and requires a fresh `permission_grant_id` from the observed agent via the speak-freely protocol.

**Dataclass.** `PeerObservation` (frozen) carries observer_id, observed_id, register, content, timestamp, decay_after, permission_grant_id.

**Four mechanical floors (code-enforced).** (1) Reputation/routing read-only - source-scan regression test asserts the module has zero `trust_network` / `hebbian` / `probos.mesh.routing` imports. (2) Observed opt-out via `CrewProfile.peer_perception.enabled` (default True for crew; AgentDesigner/spawner flips utility/system tiers to False). (3) Backend-render-only path - browser captures rejected. (4) Cross-federation observed honest-degrades with `federation_review_required` when the observed_id resolves outside the local AgentRegistry.

**Capability surface.** Eight hard gates evaluated IN ORDER: (1) `cfg.avatars.peer_perception_enabled`, (2) observer's `peer_perception.enabled`, (3) observer's `peer_perception.certified` (AD-729b), (4) observed's `peer_perception.enabled` (opt-out), (5) register==PERSONAL requires valid `permission_grant_id`, (6) backend render available, (7) federation gate (same-mesh only via registry resolution), (8) `peer_observation_max_per_pair_per_thread` cap per (observer, observed, thread_id) tuple. Each gate failure emits `PEER_OBSERVATION_DECLINED` with a structured `reason` code.

**Speak-freely protocol.** `request_permission` emits `PEER_OBSERVATION_PERMISSION_REQUESTED`, consults the per-observed registered listener (default deny-silent), then emits either `PEER_OBSERVATION_PERMISSION_GRANTED` with a fresh single-use grant_id (5-minute TTL) or `PEER_OBSERVATION_PERMISSION_DENIED`. Grants are atomically consumed by `observe_peer` via `_consume_grant`.

**Records persistence.** Observations persist via the existing `RecordsStore.write_entry` API at `src/probos/knowledge/records_store.py:47` (verified by Architect pre-flight grep). Relative path `peer_observations/{observer}_{observed}_{ts_ms}.md`, classification `ship`, status `recorded`, department `counselor`, tag `peer_observation`.

**Composite impressions.** Sync helper `composite_impressions_for(runtime, observed_id)` returns a single-paragraph string of undecayed observations, gated on capability_enabled AND observed.enabled. Section 6 v1 - actual integration into `project_self_perception` is deferred (forward marker AD-729-impressions-hookup).

**CrewProfile extension.** New `PeerPerceptionProfile` dataclass (`enabled: bool = True`, `certified: bool = False`) with `to_dict`/`from_dict` roundtrip. Wired into `CrewProfile.to_dict`/`from_dict` so on-disk profiles serialise the new field.

**Config.** Three new `AvatarsConfig` fields: `peer_perception_enabled: bool = False` (default-OFF transitional), `peer_observation_decay_seconds: int = 86400*7` (ge=3600), `peer_observation_max_per_pair_per_thread: int = 1` (ge=0, 0 disables capability).

**EventTypes.** 5 new values inserted after `RENDER_DIVERGENCE_OBSERVED` (AD-728): `PEER_OBSERVATION_RECORDED`, `PEER_OBSERVATION_DECLINED`, `PEER_OBSERVATION_PERMISSION_REQUESTED`, `PEER_OBSERVATION_PERMISSION_GRANTED`, `PEER_OBSERVATION_PERMISSION_DENIED`.

**AD-731 invariant.** Peer observations are textual. Module source-scan asserts no `b64encode`/`base64.b64`; runtime test asserts emitted payloads carry no `image_url`/`source` keys.

**AD-727 inheritance.** Read-only on reputation + associative routing - the source-scan regression test (Test 12) is the gate.

**Tier-2 throughout.** Every failure mode returns None with a PEER_OBSERVATION_DECLINED event carrying a structured reason code. The capability surface NEVER raises.

**Tests.** +18 pytest in `tests/test_ad729_peer_perception.py`. Real `AgentRegistry`-shape fixture (no MagicMock at substrate boundary per BF-287). Coverage includes happy paths for both registers, all eight decline reasons, permission flow (request->grant->record AND request->deny-silent), grant expiry, impression decay, RecordsStore persistence, AD-727 + AD-731 source-scan regression guards.

**Files.** `src/probos/events.py` (+5 EventType values), `src/probos/config.py` (+3 AvatarsConfig fields), `src/probos/crew_profile.py` (+PeerPerceptionProfile dataclass + CrewProfile.peer_perception field + to_dict/from_dict wiring), `src/probos/avatars/peer_perception.py` (new, ~410 lines), `tests/test_ad729_peer_perception.py` (new, 18 tests).

**Forward markers.** AD-729-impressions-hookup (wire `composite_impressions_for` into `project_self_perception` - trigger: AD-729a Standing Orders shipped AND >=1 officer certified per AD-729b; the latter ships in this wave so the trigger is satisfied at wave close). AD-729-capability-flip (flip `peer_perception_enabled` default to True for crew agents - trigger: AD-729a shipped AND >=3 officers passed AD-729b certification).

### AD-722a-6 - Cross-agent intent-vs-presentation divergence observation (Wave 163)

**Date:** 2026-05-15. **Status:** SHIPPED (dual default-OFF). **Wave:** 163. **Closes:** #615.

**Consumer.** AD-722a-6 is the cross-agent analog of AD-722a-1 (per-agent self-observation). Observer Maya can now observe Ezri's intent-vs-presentation divergence pattern, with full AD-729 governance applied.

**API.** New async `observe_peer_divergence(runtime, observer_id, observed_id, *, register, permission_grant_id, thread_id, window_seconds)` exported from `src/probos/avatars/peer_perception.py`. Reads AD-722a-1's per-agent `runtime.divergence_history` ring buffer (allocated lazily by the divergence detector), summarises the recent entries with a pure-template renderer, and delegates to `observe_peer` so the eight AD-729 governance gates apply uniformly.

**Three pre-delegation gates.** (1) `cfg.avatars.cross_agent_divergence_observation_enabled` (default False); (2) AD-722a-1's `vision_intent_divergence_enabled` upstream gate (False -> nothing to observe); (3) the observed agent must have at least one `DivergenceHistoryEntry` inside `window_seconds` (default 24h). Each gate honest-degrades by returning None - no decline event at this layer; declines from the AD-729 delegate fire normally.

**Pure-template summary.** `_format_divergence_summary` emits flat OPERATIONAL-register phrasing: ''Observed N intent-vs-presentation divergences in the recent window, dominant in the 'X' category, mean magnitude M.'' No LLM call, no embedding lookup, no value-judgment vocabulary. Phrasing predictability is a governance feature - PERSONAL phrasing leaks ('she seems stressed today') are blocked at the template, not at the AD-729 layer.

**Dual default-OFF.** Wave 163 ships both flags default False: `peer_perception_enabled` (AD-729) AND `cross_agent_divergence_observation_enabled` (AD-722a-6). The capability surface fires only when BOTH are True. Forward marker AD-722a-6-flip files the trigger to flip the latter (advances when AD-729a Standing Orders ship AND AD-729 capability is default-ON for crew).

**Event.** New `EventType.CROSS_AGENT_DIVERGENCE_OBSERVED` inserted after the AD-729 `PEER_OBSERVATION_*` cluster. Payload carries observer_id, observed_id, register, summary string, divergence_count, timestamp. Emitted ONLY after the AD-729 governance layer records the observation - decline paths do not fire this event (the AD-729 `PEER_OBSERVATION_DECLINED` is sufficient).

**AD-731 invariant.** Textual payloads only. Module source-scan asserts no `b64encode`/`base64.b64`; runtime test asserts emitted payloads carry no `image_url`/`source` keys.

**Tier-2 throughout.** All failure modes honest-degrade to None; the function never raises. AD-729's underlying decline events provide the audit trail when delegation reveals a governance violation.

**Tests.** +10 pytest in `tests/test_ad722a_6_cross_agent_divergence.py`. Coverage: happy path, both pre-delegation gates failing, no recent data, delegated AD-729 declines (observer uncertified, observed opt-out, PERSONAL without grant), template phrasing regression (no PERSONAL vocabulary leaks), event payload integrity, AD-731 invariant. Real `SystemConfig()` + `AgentRegistry`-shape fixtures per BF-287.

**Files.** `src/probos/events.py` (+1 EventType value), `src/probos/config.py` (+1 AvatarsConfig field), `src/probos/avatars/peer_perception.py` (+`_format_divergence_summary` + `observe_peer_divergence` + `__all__` update), `tests/test_ad722a_6_cross_agent_divergence.py` (new, 10 tests).

**Forward markers.** AD-722a-6-flip (flip `cross_agent_divergence_observation_enabled` default to True for OPERATIONAL register - trigger: AD-729a Standing Orders shipped AND AD-729 capability is default-ON for crew).

### AD-729b - Peer-observation conduct training module (Wave 163)

**Date:** 2026-05-15. **Status:** SHIPPED (mechanical gate + scaffold; content deferred to AD-729a). **Wave:** 163. **Closes:** #589.

**Mechanical gate.** New `cognitive/peer_observation_training.py` exports four functions: `load_module(path)` reads + validates the YAML schema; `grade_module(*, module, responses)` applies the deterministic weighted-rubric pass/fail; `peer_observation_graduation_gate(*, profile, qualification_config)` is the Boot Camp / Qualification integration hook that returns `(allowed, reason)`; async `set_peer_observation_certified(*, runtime, agent_id, value, reason)` atomically flips the CrewProfile flag and emits the cert event.

**Deterministic rubric.** v1 is deterministic - the trainee's responses are floats per section (each in [0,1]); the weighted sum compared against `final_assessment.pass_threshold` (default 0.8). LLM-graded variant filed as forward marker AD-729b-2 (trigger: when v1 rubric has graded >=10 officers AND consistency is verified).

**YAML scaffold.** New `config/manuals/peer_observation_conduct.yaml` ships the schema for Wave 163. Six sections per AD-729b spec: theory, register_identification, phrasing_practice, permission_protocol, pattern_recognition (placeholder list until AD-729c monitoring corpus is available), final_assessment with per-section rubric weights (0.30 / 0.30 / 0.30 / 0.10). Worked-example / scenario / role-play arrays carry one example each + `# TODO(AD-729a)` markers showing where the full content lands once Standing Orders are authored.

**EventTypes.** 2 new values inserted after `CROSS_AGENT_DIVERGENCE_OBSERVED`: `PEER_OBSERVATION_CERTIFIED` (training pass; agent gains the gate), `PEER_OBSERVATION_CERTIFICATION_REVOKED` (AD-729c second-tier intervention clears the flag).

**Config.** Two new fields on `QualificationConfig`: `peer_observation_module_path: str` (default `config/manuals/peer_observation_conduct.yaml`); `peer_observation_certification_required: bool = False` (default-OFF transitional; flips True after AD-729a Standing Orders ship).

**Integration hook style.** `peer_observation_graduation_gate` is exposed as a stateless helper - Boot Camp / Qualification call it as a pre-check. Actual wire-up into `crew_development/boot_camp.py` graduation pipeline is deferred (the pipeline does not currently expose a clean ''graduation gate'' hook). The function is unit-tested in isolation; Boot Camp consumers gain certification gating by importing + calling it.

**Mutation API.** `set_peer_observation_certified` mirrors the AD-720d-2.1 `set_vision_capable` shape (per PROGRESS.md line 16): public-API registry lookup, atomic flag flip, event emission with structured reason. Tier-2 throughout - registry miss / profile missing / set failure all return False without raising.

**Persistence.** Field roundtrips through the existing `CrewProfile.to_dict`/`from_dict` shape wired in AD-729 (see test 8). No new SQLite schema, no migration - the on-disk JSON blob carries the new `peer_perception.certified` boolean.

**Tier-2 throughout.** Parse failures, malformed YAML, missing responses, schema mismatch - all return False without raising. The capability surface never fails closed in a way that brick the system.

**Tests.** +8 pytest in `tests/test_ad729b_peer_observation_training.py`. Loads the actual YAML scaffold (real file path, not a MagicMock dict per BF-287). Coverage: load success, grading pass (weighted 0.84), grading fail (weighted 0.5), graduation gate blocks when required+uncertified, gate permits when flag-off, gate permits when certified, mutation API atomic + event-emitting, certification persists through CrewProfile.to_dict/from_dict roundtrip.

**Files.** `src/probos/events.py` (+2 EventType values), `src/probos/config.py` (+2 QualificationConfig fields), `src/probos/cognitive/peer_observation_training.py` (new, ~210 lines), `config/manuals/peer_observation_conduct.yaml` (new), `tests/test_ad729b_peer_observation_training.py` (new, 8 tests).

**Forward markers.** AD-729b-2 (LLM-graded module - trigger: AD-729b deterministic rubric has graded >=10 officers AND grading consistency verified). AD-729b-flip (flip `peer_observation_certification_required` default to True - trigger: AD-729a Standing Orders ship AND AD-729b module content is complete with Counselor sign-off).

### AD-729c - Counselor pattern-monitoring for peer-observation conduct (Wave 163)

**Date:** 2026-05-15. **Status:** SHIPPED. **Wave:** 163. **Closes:** #590.

**Module.** New `src/probos/cognitive/peer_observation_monitor.py` exports the `PatternFinding` dataclass, the `PeerObservationPatternDetector` Protocol, seven concrete detectors, the `default_detectors` factory, the `aggregate_health_metrics` privacy-preserving counts helper, and the `PeerObservationMonitor` orchestrator.

**Seven detectors (one Protocol per pattern).** (1) `FrequencyDriftDetector` flags observers whose per-peer rate dominates their overall rate. (2) `RegisterDriftDetector` regex-detects PERSONAL vocabulary in OPERATIONAL observations. (3) `CascadeSignalDetector` flags >=3 distinct observers landing on the same subject inside a 600s window. (4) `StaticImpressionDetector` flags identical content repeated >=3 times. (5) `PermissionDenialPatternDetector` flags >=3 denials per pair via an injected lookup callable. (6) `SycophancyPatternDetector` flags low-trust observer + high-trust observed + positive-vocab observation concentration; trust scores READ-ONLY via injected callables. (7) `PrivilegedTierLeakageDetector` regex-detects clinical/security vocabulary in non-clinical channels; severity=critical.

**Fixed cadence.** `_MONITOR_INTERVAL_SECONDS = 60` pinned at module top. AD-504 phantom dropped (no `ClinicalTelemetryConfig.sampling_interval` field). Configurable cadence filed as forward marker AD-729c-1.

**Three-tier escalation.** State machine per `(detector, observer_id)` pair. Tier 1 = first finding -> `PEER_OBSERVATION_INTERVENTION_TIER_1` event (private coaching). Tier 2 = persistence across two intervals -> calls injected `revoke_certification` callable (typically `set_peer_observation_certified(observer, False)`) + Tier-2 event. Tier 3 = persistence post-recert -> Tier-3 event (bridge alert via AD-635; concrete wiring forward-marked).

**State persistence.** Sidecar JSON at `<state_path>`. `_save_state` uses temp-file + `os.replace` atomic pattern mirroring AD-720d-2.1. Reloaded at `PeerObservationMonitor.__init__`; state survives runtime restart. Test 22 verifies the roundtrip.

**EventTypes.** 4 new values inserted after `PEER_OBSERVATION_CERTIFICATION_REVOKED`: `PEER_OBSERVATION_PATTERN_FLAGGED`, `PEER_OBSERVATION_INTERVENTION_TIER_1`, `_TIER_2`, `_TIER_3`.

**Counselor-own-conduct.** This module never invokes the AD-729 capability surface (`observe_peer`) itself - only consumes pre-existing observations. Source-scan regression test (Test 21) asserts the literal string `observe_peer(` does not appear in module source.

**Trust read-only.** `SycophancyPatternDetector` reads trust scores via injected `observer_trust_lookup` / `observed_trust_lookup` callables. The module source contains no `trust_network.record_outcome` or `trust_network.update` tokens (Test 20).

**Aggregate metrics.** `aggregate_health_metrics` returns total_observations, by_register histogram, unique_observed_count, permission_grant_ratio, per_observed_skewness (statistics.pstdev-based), mean_age_seconds. Individual observation IDs are NEVER surfaced - privacy preserved by construction.

**Tier-2 throughout.** All failure modes log + degrade. Sidecar write failures, emit_event exceptions, revoke_certification exceptions - none raise. The monitor degrades visibly but never bricks.

**Wiring deferred.** Boot-Camp/Runtime invocation of the monitor on a 60s tick is not in scope - the class is unit-tested in isolation. Forward markers AD-729c-tier1-wire (Counselor 1:1 channel) and AD-729c-tier3-wire (AD-635 bridge alert) capture the concrete wiring once those substrate APIs stabilise. The events are always emitted regardless.

**Tests.** +23 pytest in `tests/test_ad729c_peer_observation_monitor.py`. Coverage: each of the seven detectors gets positive + negative cases (14); Tier 1/2/3 escalation chain (3); aggregate metrics correctness (1); cadence pinning (1); source-scan trust + observe_peer enforcement (2); sidecar restart roundtrip (1); default_detectors factory (1). Real `PeerObservation` fixtures (no MagicMock at the substrate boundary per BF-287).

**Files.** `src/probos/events.py` (+4 EventType values), `src/probos/cognitive/peer_observation_monitor.py` (new, ~470 lines), `tests/test_ad729c_peer_observation_monitor.py` (new, 23 tests).

**Forward markers.** AD-729c-1 (cadence as ClinicalTelemetryConfig field - trigger: first operator request to tune OR production data showing the rate is wrong). AD-729c-2 (LLM-assisted phrasing-drift detection - trigger: AD-729c regex RegisterDriftDetector produces >=20 findings with manual review confirming >=80% precision). AD-729c-3 (cross-mesh pattern detection - trigger: federation peer-observation arrives via AD-480 review path). AD-729c-tier1-wire (Counselor 1:1 channel API integration - trigger: AD-635 message-channel API stabilises for in-test wiring). AD-729c-tier3-wire (AD-635 bridge alert API integration - trigger: AD-635 alert-creation signature is grep-verifiable on the runtime).

### AD-729d - Peer-observation reinforcement loop FORWARD MARKER (Wave 163)

**Date:** 2026-05-15. **Status:** FORWARD MARKER (doc-only filing). **Wave:** 163. **Closes:** #591 (as the marker; the build is a future wave).

**Capability.** Peer-observation reinforcement would create an optimization gradient where positive peer observations of an agent's conduct reinforce the underlying AvatarDSL traits associated with that conduct. AD-729 mechanical constraint #1 (read-only with respect to reputation and routing) prevents trust drift, but reinforcement is the natural channel where that pressure could re-enter the system through DSL drift instead. This AD does NOT ship the capability - it captures the forward marker so the design is not lost, with TECHNICAL triggers (per AD-722c-3) governing when it advances.

**Why doc-only in Wave 163.** Five hard preconditions, none currently met: (1) AD-729 operationally stable for >=2 quarters; (2) AD-729a Standing Orders extended with reinforcement-specific rules; (3) AD-729b Training extended with reinforcement content; (4) AD-729c monitoring extended with reinforcement-specific detectors; (5) Captain explicit design-stage review (Counselor + Architect joint). AD-729 ships in Wave 163; operational stability takes time, not code.

**TECHNICAL triggers (per AD-722c-3).** The forward marker advances to a build prompt when ALL of: (A) `EventType.PEER_OBSERVATION_RECORDED` count >=100 events across >=3 distinct observer/observed pairs over a continuous 2-quarter window; (B) AD-729c `PEER_OBSERVATION_INTERVENTION_TIER_3` event count is 0 across the same window AND no `_TIER_2` events have escalated to `_TIER_3` retry; (C) AD-729a is shipped AND its Standing Orders content includes a reinforcement-specific section reviewed by Counselor; (D) AD-729b module YAML includes reinforcement content sections AND >=3 officers have passed the extended module; (E) Captain explicit ruling at design stage documented in DECISIONS.md.

**Open design questions** (recorded for the future scoping pass, NOT answered here):
  1. Reinforcement updates DSL directly vs. produces AD-721d Captain-approval proposals? Lean: proposals only.
  2. Scoped to mentor-mentee relationships vs. any-peer-to-any-peer? Lean: mentor-mentee only in v1.
  3. Does reinforcement decay? Lean: yes, mirroring AD-729 impression decay.
  4. How does reinforcement interact with the Counselor's clinical role? Lean: clinical feedback bypasses peer-reinforcement entirely; uses the AD-503 channel.

**Out of scope (deferred even beyond AD-729d).** Federation reinforcement (cross-mesh). Reinforcement that bypasses AD-721d Captain approval. Reinforcement that re-enters trust scoring through any path.

**Files.** `DECISIONS.md` (this entry), `PROGRESS.md` (Wave 163 housekeeping note), `docs/development/roadmap.md` (AD-729d row with TECHNICAL triggers). No source code. No tests. No config.

**Disposition.** GitHub issue #591 stays OPEN. Wave 163 disposition: documented; preconditions not met; advances on TECHNICAL triggers above.

### AD-721d-2c - HXI Counselor-mediation button (Wave 163)

**Date:** 2026-05-15. **Status:** SHIPPED. **Wave:** 163. **Closes:** #658.

**HXI completion.** AD-721d-2 shipped server-side mediation in Wave 162; AD-721d-2c wires the UI button into `CrewAvatarPopout.tsx`.

**Props.** Two new optional props on `CrewAvatarPopout`: `onMediateRevision?: (note: string) => Promise<{ refined_hint?: string; proposal_iteration?: number; error?: string }>` and `counselorOnline?: boolean`. Both default to undefined - existing call sites unchanged, byte-compatible.

**UI affordance.** Inline-SVG mediate glyph (two circles + bridge stroke; `strokeWidth=1.5`; `strokeLinecap=round`; amber active state `#f0b060`) per HXI Design Principle #3 (no emoji). Rendered between the 280-char revision counter and the existing submit button when ALL of: callback prop present, `counselorOnline=true`, `revisionNote.trim()` non-empty. Disabled while in-flight.

**Flow.** Click invokes `onMediateRevision(note)`. On success, the refined hint renders inline (`Counselor refined: ...`) with an iteration chip (`(iter N)`); the refined text populates the textarea so the Captain can review/edit before submitting via the existing submit-revision path. On error, a stroke-based error surface displays the message; the Captain's ORIGINAL hint is preserved (NOT clobbered).

**Local state only.** `mediating`, `mediateRefined`, `mediateError`, `mediateIteration` live inside `CrewAvatarPopout`. No store mutations, no API client module added in this AD - the callback handles the network layer.

**Online detection.** `counselorOnline` is a prop, not an internal store lookup. The parent (`AgentProfilePanel`) is responsible for determining counselor online status by inspecting the store's agent records (`agent.status === 'online'` per `ui/src/store/types.ts:590`). Wire-up of `AgentProfilePanel` itself is deferred (forward marker AD-721d-2c-parent-wire) - the new props default to undefined so the existing parent rendering is unchanged.

**HXI Design Principles.** #3 (inline SVG glyphs, no emoji) - mediate glyph is stroke-based two-circle-plus-bridge. #10 (workstation tier) - the button helps the Captain delegate to the Counselor, nudging up the agentic-first hierarchy.

**Tests.** +4 vitest in `ui/src/__tests__/CrewAvatarPopout.mediate.test.tsx`. Coverage: button visible when conditions met; button hidden when `counselorOnline=false`; happy path renders refined panel + iteration chip; error path renders error surface AND preserves Captain's hint.

**Files.** `ui/src/components/profile/CrewAvatarPopout.tsx` (+2 props, +inline-SVG button block, +4 state hooks, +refined/error panels), `ui/src/__tests__/CrewAvatarPopout.mediate.test.tsx` (new, 4 tests).

**Bundle.** vitest 644 -> 648. `npm run build` green; bundle hash `index-a4x_HPw3.js` -> `index-cAfin0aS.js`.

**Forward markers.** AD-721d-2c-parent-wire (wire `onMediateRevision` callback + `counselorOnline` lookup in `AgentProfilePanel.tsx` - trigger: first Captain feedback that the button is desired in the default revision flow OR HXI polish wave is scheduled).

### AD-719b - Copilot-style left rail + Agents nav (Wave 163)

**Date:** 2026-05-15. **Status:** SHIPPED (default-OFF; parent wire deferred). **Wave:** 163. **Closes:** #547.

**Shell component.** New self-contained `ui/src/components/leftrail/LeftRail.tsx` exports the `LeftRail` component plus `LeftRailAgent`, `LeftRailThread`, `LeftRailProps` types. Pure presentational - data flows in via props; parent wires the zustand stores. The rail's responsibility is rendering + interactivity + localStorage state; not data fetching.

**Default-OFF.** Returns `null` until `localStorage.hxi_left_rail_enabled === 'true''`. This is zero-regression for existing users: the existing IntentSurface continues unchanged.

**Collapse + width.** `localStorage.hxi_left_rail_collapsed` toggles 240px <-> 56px width; transition 'width 120ms ease''. Collapse-toggle button (stroke-based chevron glyph) at the top.

**Progressive disclosure (HXI Design Principle #5).** Visit count tracked in `localStorage.hxi_visit_count` and incremented once per mount. First-time users (visits<10) see max 5 agents + 3 threads; veteran (visits>=10) see max 12 + 8.

**Two sections.** (1) Agents online - filters incoming `agents` to `status==='online'`; each rendered as a click-button with an amber dot + callsign. (2) Recent threads - rendered as click-buttons with title; truncated with ellipsis when expanded, glyph-only ('.') when collapsed. Each section has a stroke-based icon glyph at its header.

**Inline-SVG glyphs only (HXI Design Principle #3).** Three glyphs: agents (head + shoulders silhouette stroke), threads (three horizontal lines), collapse (chevron). All `strokeWidth=1.5`, `strokeLinecap=round`, no emoji, no fills. Active state `#f0b060`; inactive `#666680`.

**Tooltips for collapsed state.** When collapsed, full agent/thread names render via the native `title` attribute, satisfying HXI Design Principle #1 (system understands the human - no decoding required even at high information density).

**Parent wiring deferred.** `LeftRail` is built but NOT yet imported by `App.tsx`. The current bundle does not include it (Vite tree-shakes unreferenced modules - bundle hash unchanged from AD-721d-2c). Parent wiring is filed as forward marker AD-719b-parent-wire; default-flip is AD-719b-2.

**No new global store, no new context.** Per the scope discipline, the rail is a consumer of existing state via props. AgentProfilePanel / WardRoomPanel callers will read `useStore` directly and pass the trimmed lists in.

**Tests.** +5 vitest in `ui/src/__tests__/LeftRail.test.tsx`. Coverage: default-OFF renders null, enabled renders both sections + filters offline agents, click-agent fires callback with agent_id, click-thread fires callback with thread_id, collapse toggle persists localStorage AND updates rendered width.

**Files.** `ui/src/components/leftrail/LeftRail.tsx` (new, ~230 lines), `ui/src/__tests__/LeftRail.test.tsx` (new, 5 tests).

**Bundle.** vitest 648 -> 653. `npm run build` green. Bundle hash unchanged (`index-cAfin0aS.js`) because the rail is not yet imported - this is expected and correct; the hash will advance when AD-719b-parent-wire ships.

**Forward markers.** AD-719b-parent-wire (import LeftRail into App.tsx + wire zustand stores for online agents + recent threads - trigger: AD-719b shipped AND parent layout has the slot reserved). AD-719b-2 (flip `hxi_left_rail_enabled` default to True - trigger: Captain has used the left rail across >=5 sessions per visit-count telemetry).

### AD-719a - Persistent multi-agent chat threads under WardRoom (Wave 163, contract only)

**Date:** 2026-05-15. **Status:** SHIPPED (architectural contract). **Wave:** 163. **Closes:** #546.

**Architectural decisions (Captain ruling 2026-05-15).** (1) YES agents observe other agents' messages mid-thread when @-mentioned in the thread. (2) NO agents do NOT observe threads they were never @-mentioned in (cross-thread observation out of scope; deferred to AD-719a-3). (3) Captain messages are always the seed (agent-to-agent without Captain prompt deferred to AD-719a-2).

**Contract.** New src/probos/ward_room/multi_agent.py exports MULTI_AGENT_THREAD_MODE constant, create_multi_agent_thread helper, format_participant_trailer + parse_participants for the in-body participants-list encoding, is_participant + cross_agent_visibility for the Wave 163 visibility ruling.

**Why contract-only.** The full AD-719a deliverable (rewriting AD-719 transient fan-out to persist + injecting thread history into participants' prompts) is a substantial backend wave. Wave 163 ships the architectural seam (the marker + helper + visibility rules) so the future wire-up is mechanical. AD-719a-wire forward marker captures the wire-up.

**Storage.** No new schema migration. WardRoomThread.thread_mode gains a fourth value 'multi_agent' alongside inform/discuss/action. UI store type union extended.

**UI delta.** Minimal MULTI badge in WardRoomThreadList for thread_mode==='multi_agent' rows. Stroke-based two-circle-bridge glyph + 'MULTI' label in amber. WardRoomThreadDetail unchanged.

**Participants trailer.** Structured '@participants: id1,id2,id3' line at the bottom of the thread body. Recovered via regex. Comma-separated. When mentioned_agent_ids is empty, no trailer is added.

**AD-731 invariant.** Multi-agent threads are textual. Module source-scan asserts no b64encode/base64.b64/image_url tokens.

**Tier-2 throughout.** parse_participants returns [] on missing/malformed/empty input. create_multi_agent_thread raises only if the underlying service.create_thread raises.

**Tests.** +6 pytest in tests/test_ad719a_multi_agent_threads.py. +4 vitest in ui/src/__tests__/WardRoomThreadList.multiAgent.test.tsx.

**Files.** src/probos/ward_room/multi_agent.py (new), tests/test_ad719a_multi_agent_threads.py (new), ui/src/components/wardroom/WardRoomThreadList.tsx (+badge block), ui/src/store/types.ts (+union value), ui/src/__tests__/WardRoomThreadList.multiAgent.test.tsx (new).

**Bundle.** vitest 653 -> 657. pytest 13715 -> 13730. Bundle hash index-cAfin0aS.js -> index-hKNByK6W.js.

**Forward markers.** AD-719a-wire (rewrite AD-719 transient fan-out to persist via create_multi_agent_thread AND inject thread history into participant agents' prompts - trigger: AD-719a contract validated by >=3 distinct multi-agent threads in operation). AD-719a-2 (agent-to-agent without Captain seed - trigger: >=10 multi-agent threads with cross-agent visibility working). AD-719a-3 (cross-thread observation gated by AD-729 peer-perception - trigger: AD-729 default-ON for crew).

### AD-739 - Captain Card data model + render pipeline (Wave 163, contract only)

**Date:** 2026-05-15. **Status:** SHIPPED (data model + storage + render; consumer wiring deferred). **Wave:** 163. **Closes:** #649.

**Capability.** Operator self-card always-in-context across all CognitiveAgent prompts. Closes the gap where every agent re-derives operator context from episodic recall on each turn. System-maintained - NOT agent-self-edited (per governance). Updates flow through Dreaming consolidation + correction-feedback only.

**Why contract-only.** v1 ships data model + storage + render pipeline + validation guard. Prompt-builder injection (AD-739-prompt-wire) and Dreaming-loop integration (AD-739-dreaming-wire) are mechanical wire-ups deferred to forward markers; the model + renderer are the contract.

**Data model.** New src/probos/captain_card/card.py exports CaptainCard Pydantic model (name/callsign/role identity, tone/formatting voice, current_project/current_wave context, preferences max-10, recent_corrections max-3 via CorrectionRef, avatar_ref reserved for AD-733a, version, updated_at). CorrectionRef carries episode_id + summary (template-rendered, max 200 chars) + timestamp.

**Persistence.** Atomic JSON sidecar via load_card / save_card. Temp-file + replace pattern (mirrors AD-720d-2.1). load_card returns default_captain_card on FileNotFoundError or any parse failure (tier-2 degrade). save_card returns False on OSError; never raises.

**Renderer.** render_card_for_prompt is pure-template (no LLM call, no embeddings). Approximates token budget as max_chars = max_tokens * 4. Tail-truncates preferences and recent_corrections until under budget while preserving identity fields (name, callsign, role, tone). Output is a compact YAML-like block.

**Confabulation guard.** Reuses AD-588/589/592's _CAPABILITY_GAP_RE imported from probos.cognitive.decomposer. After rendering, every output line is scanned; lines matching the capability-gap regex (don't have, can't, cannot, unable to, ...) are dropped with a logged WARNING. This blocks the Card from injecting hallucinated capability denials into system prompts.

**AD-731 invariant.** avatar_ref field has a Pydantic field_validator that enforces SHA-256 hex format (64 chars). Non-hash strings raise ValueError at construction. None / empty allowed. Module source-scan asserts no b64encode/base64.b64 anywhere.

**Config.** Four new CognitiveConfig fields: captain_card_enabled (default True; benign anchor), captain_card_path (default captain_card.json), captain_card_max_tokens (default 500, ge=100 le=1500), captain_card_refresh_min_interval_seconds (default 3600, ge=60).

**Default-ON rationale.** Unlike AD-729 / AD-722a-6 / AD-728 which default OFF until operational validation, the Captain Card defaults ON because it is a pure context anchor that cannot misbehave - the renderer's confabulation guard + token budget cap + truncation rules bound its blast radius. Risk is upper-bounded by max_tokens characters of structured text.

**Tier-2 throughout.** load failures, save failures, render failures all log + degrade. The Card never blocks prompt assembly.

**Tests.** +10 pytest in tests/test_ad739_captain_card.py. Coverage: bootstrap default, roundtrip persistence, render within budget, truncation preserves identity, capability-gap line stripped, avatar_ref SHA-256 validator (valid + invalid), avatar_ref None allowed, AD-731 source-scan, CognitiveConfig defaults, package public surface. Real SystemConfig() fixtures per BF-287.

**Files.** src/probos/captain_card/__init__.py (new), src/probos/captain_card/card.py (new, ~190 lines), src/probos/config.py (+4 CognitiveConfig fields), tests/test_ad739_captain_card.py (new, 10 tests).

**Forward markers.** AD-739-prompt-wire (inject render_card_for_prompt output into prompt_builder.build_system_prompt and the per-CognitiveAgent system-prompt assembly - trigger: Captain validates the rendered Card content). AD-739-dreaming-wire (wire the Captain Card refresh into the Dreaming consolidation loop using captain_card_refresh_min_interval_seconds throttle - trigger: AD-739-prompt-wire ships AND >=10 high-importance correction episodes accumulate). AD-739a (per-department overlays - trigger: Captain operates >=3 distinct department-specific contexts). AD-739b (multi-operator support - trigger: ProbOS deployment supports >1 simultaneous Captain). AD-739c (LLM-driven Card refresh - trigger: deterministic refresh produces stale Cards in operator feedback).

### AD-706d - LLM-driven Browser Tool tier classifier (Wave 163)

**Date:** 2026-05-15. **Status:** SHIPPED (default-OFF). **Wave:** 163. **Closes:** #519.

**Augmentation.** New src/probos/tools/browser/llm_classifier.py exports classify_action_with_llm as a sync companion to the existing rule-based classify_action at tools/browser/actions.py:550. The rule-based function is UNCHANGED - its int 1/2/3 tier contract is preserved exactly. Existing callers continue to call classify_action; opt-in LLM augmentation routes through the new companion.

**Critical safety property.** The LLM can only UPGRADE the rule-based tier (1->2->3), NEVER DOWNGRADE. When the rule classifier returns tier=3 the LLM is NOT called (short-circuit cost discipline + zero risk of LLM downgrading the highest tier). When LLM returns a tier strictly less than the rule tier, max() preserves the higher value.

**Reuse not fork.** REUSES AD-722a-1's VisionLLMRateLimit under new scope browser_action_classifier. The pre-flight verify confirmed VisionLLMRateLimit is already used cross-module (self_render_verify.py:32,67 imports it for non-vision-coupled use) - the generalizability question is resolved. No fork to a new LLMCallRateLimit class.

**Cache.** In-memory dict keyed by (action, url[:80], element_text[:120], page_title[:80]) with configurable TTL. Test 9 verifies cache-hit reuses prior tier without an LLM call. Persistent on-disk cache filed as AD-706d-3 forward marker.

**Output parsing.** Strict single-word match against {auto_run, ack_required, destructive} plus synonyms {silent, logged, captain_ack}. Anything else honest-degrades to the rule tier. Maps to int 1/2/3 to match the existing classify_action int contract.

**Sync entry point.** Browser Tool dispatches synchronously, so classify_action_with_llm is sync. It reads llm_client.complete_sync when present; runtimes that only expose async complete honest-degrade to the rule tier. The sync-vs-async distinction is read-only from the runtime - the classifier does not enforce a particular async pattern.

**Config.** Four new BrowserToolConfig fields: llm_classifier_enabled (default False), llm_classifier_tier (default 'fast' - cheapest tier adequate for classification), llm_classifier_max_per_hour (default 60, ge=0), llm_classifier_cache_ttl_seconds (default 300, ge=0).

**Tier-2 throughout.** Disabled gate, rate-limit exhaustion, missing llm_client, missing complete_sync, LLM exception, malformed output, unknown enum value - all honest-degrade to the rule tier. The classifier NEVER raises and NEVER returns a tier less than the rule tier.

**AD-731 invariant.** n/a - text-only classifier. No image bytes flow through this code path. Vision-tier verify lives in AD-706c-1.

**Tests.** +10 pytest in tests/test_ad706d_llm_action_classifier.py. Coverage: disabled preserves rule tier, destructive short-circuits, LLM upgrades 1->2, LLM cannot downgrade 2->1, LLM failure degrades, malformed output degrades, unknown enum degrades, rate-limit exhaustion degrades, cache hit reuses prior tier, source-scan asserts classify_action unchanged + companion exists + VisionLLMRateLimit reused.

**Files.** src/probos/config.py (+4 BrowserToolConfig fields), src/probos/tools/browser/llm_classifier.py (new, ~175 lines), tests/test_ad706d_llm_action_classifier.py (new, 10 tests).

**Forward markers.** AD-706d-2 (Counselor InterventionType pattern share with AD-561 - trigger: AD-561 InterventionType API stabilises). AD-706d-3 (persistent cache - trigger: in-memory cache hit rate is measurably low across operator sessions).


### AD-728c — Agent-initiated render self-check with contextual rate limits (Wave 164)

**Date:** 2026-05-16. **Status:** SHIPPED. **Wave:** 164. **Closes:** [#660](https://github.com/seangalliher/ProbOS/issues/660). **Parent:** AD-728 (Wave 163 vision-LLM render-coherence mirror).

**Context.** AD-728 (Wave 163) shipped `verify_render_coherence` with three triggers: `captain_command` (live), `divergence_followup` (gated by `render_verification_followup_enabled`), and `agent_initiated_stub` (hard-rejected pending future AD that flips the gate). Counselor reported during a live conversation: *"I get telemetry, not perception. I have no way to know if what's rendering on your end actually matches those parameters."* Captain authorized closing the gap: *"Like a person looking in a mirror — they don't do it constantly. Configurable rate limits. An agent actively communicating with a human may want to check before the interaction and periodically during the conversation."*

**Decision.** Flip the `agent_initiated_stub` trigger from hard-reject to a gated, two-budget rate-limited path. REUSE `verify_render_coherence` unchanged on the vision-LLM call (no duplication). Two-budget contextual rate limit: a per-active-conversation budget (default 2) applies INSTEAD OF the hourly budget (default 3) when the agent is in an active conversation (`last_reply_emitted_at` within `render_self_check_active_window_seconds`, default 600s). The two budgets are NEVER additive — per-conversation is the override while engaged, not an add-on. Working-memory ingress via `AgentWorkingMemory.record_observation` (NOT `SensoriumEntry` — the registry is class-level static dispatch metadata, not a runtime mailbox; the correct runtime ingress is `record_observation`). Event-bus cost discipline preserved: agent-initiated coherent calls still emit nothing, only divergent calls emit `RENDER_DIVERGENCE_OBSERVED`; the agent-private working-memory observation is the only additional surface. Trigger name retained for AD-728 string-stability — the `_stub` suffix is now historical.

**Files.** `src/probos/config.py` (+4 `AvatarsConfig` fields, all default-OFF / conservative). `src/probos/avatars/render_verification.py` (+`_agent_initiated_rate_check` module-private helper, +`_last_reply_emitted_at` BF-287-public-API registry lookup, trigger branch flipped with two-budget gate as the sole rate-limit authority for self-check; AD-728 hourly gate bypassed for this trigger only). `src/probos/cognitive/cognitive_agent.py` (+async `check_own_render(reason)` method; folds every outcome into working memory; tier-2 throughout — never raises). `tests/test_ad728_render_verification.py` (existing `test_agent_initiated_stub_hard_rejected` renamed to `test_agent_initiated_stub_default_off_preserves_baseline` and updated to assert the default-OFF preserves the AD-728 baseline `"agent_initiated_disabled"` honest-degrade). `tests/test_ad728c_render_self_check.py` (new, 12 tests).

**Tests.** +12 pytest covering: trigger flipped (1), default-OFF baseline preserved (2), hourly budget enforced (3), per-conversation budget enforced (4), budget-switch correctness — per-conversation does NOT consume hourly bucket (5), coherent WM observation injected (6), divergent WM observation injected (7), rate-limited WM throttle entry injected (8), `check_own_render` is coroutine (9), AD-731 invariant source-scan (10), agent-initiated divergent still emits `RENDER_DIVERGENCE_OBSERVED` (11), agent-initiated coherent does NOT emit (12). Real `SystemConfig()` fixtures + hand-rolled `@dataclass` agent stub (NOT `MagicMock(spec=CognitiveAgent)`) per BF-287. Full gate 13750 -> 13762.

**Invariants preserved.** AD-731 (source-scan `b64encode`/`base64.b64` empty). AD-727 rule #1 (source-scan `trust_network`/`hebbian` empty). AD-728 cost discipline on the event bus (coherent observations do NOT emit). `_VALID_TRIGGERS` unchanged. `RenderCoherenceResult` shape unchanged (`"rate_limited_self_check"` is a new string value of the existing `skipped_reason` field, not a new field).

**Forward markers.** AD-728c-1 (per-conversation budget reset on Captain-acknowledged correction — trigger: AD-572 correction-detector produces per-conversation signals AND AD-728c telemetry shows agents exhausting per-conversation budget before resolving a divergence). AD-728c-2 (Counselor mediation of self-check requests — trigger: AD-721d-2 generalized to render self-checks AND >=3 distinct agents have requested self-checks in production traffic). AD-728c-3 (`VisionLLMRateLimit._windows` per-conversation bucket GC — trigger: `_windows` size exceeds 1000 entries in production OR any other AD reuses the `render_self_check_conv:<ts>` scope pattern). Issues deferred for all three per AD-722c-3 (TECHNICAL triggers, NOT calendar dates).


### AD-728d — Self-image-awareness skill (LLM-discoverable self-check capability) (Wave 165)

**Date:** 2026-05-16. **Status:** SHIPPED. **Wave:** 165. **Closes:** [#661](https://github.com/seangalliher/ProbOS/issues/661). **Parent:** AD-728c (Wave 164 — CognitiveAgent.check_own_render + Pydantic knobs). **Pattern:** AD-626 (augmentation-skill catalog) + AD-724 (DM sanity gate + bracket-marker pattern).

**Context.** AD-728c (Wave 164) shipped `check_own_render(reason)` as a Python coroutine, but agents have no LLM-side path to invoke it — they reason via their `instructions` string and emit side effects through bracket markers (`[ENDORSE]`, `[NO_RESPONSE]`, `[CHALLENGE]`, `[MOVE]`). A coroutine that nothing in the prompt surface mentions is dark capability. Counselor surfaced the gap verbatim 2026-05-16: *"I don't see a check_own_render skill or tool explicitly listed in my available skills."* Captain's design decision: wrap the capability in the canonical AD-626 augmentation-skill pattern. The skill teaches the agent **when** and **how** to ask; an AD-724-style bracket-parser layer maps the marker to the existing coroutine.

**Decision.** Three pieces, no new dependencies, no new vendor surface, no new config knobs. (1) New `config/skills/self-image-awareness/SKILL.md` augmentation skill following the `communication-discipline` shape — `probos-activation: augmentation`, `probos-intents: direct_message,ward_room_notification,proactive_think`, `probos-triggers: self_check`. Body teaches the `[SELF_CHECK reason]` marker, when to use it, the per-conversation/hourly budget, the honest-degrade story, and cost discipline. (2) `_SELF_CHECK_RE` (strict `[a-z_-]{1,64}` reason grammar — dispatch authority) + `_SELF_CHECK_STRIP_RE` (lax `\[SELF_CHECK\b[^\]\n]*\]` — prevents malformed markers leaking to Captain-visible text) on `DmSanityGate`, positioned adjacent to the `_CHALLENGE_RE` / `_MOVE_RE` pairs. `extract_self_check(text) -> list[str]` and `strip_self_check(text) -> str` mirror the existing `extract_move` / `strip_move` contract. (3) New `DmReplyPipeline.step_4_self_check_parse` inserted between move-parse (step 3) and episodic-store; trailing five steps renumbered 5..9 atomically in one commit (step tuple + 5 method defs + class docstring + module docstring). First marker dispatches `agent.check_own_render(reason=...)` via `asyncio.create_task`; the task reference is held on `DmReplyContext._self_check_task` per fire-and-forget GC rule. Additional markers in the same reply are stripped silently with a single WARNING.

**Files.** `config/skills/self-image-awareness/SKILL.md` (new, 132 lines). `src/probos/cognitive/dm_sanity_gate.py` (+regex pair, +`extract_self_check` / `strip_self_check` methods adjacent to `strip_move`). `src/probos/cognitive/dm/reply_pipeline.py` (module docstring 8→9, class docstring 8-step→9-step, `import asyncio` hoisted, `_self_check_task: asyncio.Task[None] | None` on `DmReplyContext`, step tuple expanded to 9, new `step_4_self_check_parse`, trailing four step defs renumbered 5..9). `tests/test_ad726_dm_reply_pipeline.py` (renumbered to match new step names; assertion `len(reached) == 7` → `8`). `tests/test_ad728d_self_image_awareness_skill.py` (new, 7 tests).

**Tests.** +7 pytest. SKILL.md frontmatter parse with three configured intents AND assert `system_heartbeat` / `run_command` NOT in the intent list (skill-catalog leak hard-stop). `find_augmentation_skills` surfaces the skill for `direct_message,ward_room_notification,proactive_think` AND does NOT surface for unrelated intents. Marker stripped from reply text. Valid reason dispatches `check_own_render` with task ref held on `DmReplyContext._self_check_task`. Invalid reason (uppercase + `?`) silently strips with no dispatch and `_self_check_task is None`. Multiple markers — first dispatches, all stripped, exactly one WARNING containing `AD-728d` and count `2`. Disabled-gate pipeline still dispatches (honest-degrade lives downstream in `verify_render_coherence`). Real `DmSanityGate` fixture + hand-rolled `_RecordingAgent` dataclass (NOT `unittest.mock`) per BF-287. Full gate 13762 → 13769 (+7 new, 0 regressions; 1 flake on `test_auto_commit_after_debounce` passes in isolation).

**Invariants preserved.** AD-731 (text-only marker — no inline blob introduction; source-scan via grep `base64` in `reply_pipeline.py` returns empty). AD-728c boundary (`check_own_render` body unchanged; rate-limit logic unchanged; observation injection unchanged — AD-728d ONLY wraps the existing capability in a skill + parser). Skill catalog scope (skill loads ONLY for the three configured intents — verified by negative-intent assertion in test 2). Pipeline-renumber atomicity (verified by `git show` — module docstring + class docstring + step tuple + 5 method defs in one commit).

**Forward markers.** None. This closes the AD-728c discoverability gap end-to-end at the DM surface. Ward Room `[SELF_CHECK]` parse is intentionally out-of-scope; if needed, a future `AD-728d-WR` would wire the parser into the Ward Room reply path. The skill body already declares `ward_room_notification` / `proactive_think` intents so the agent's pre-reply reasoning has the option in mind in those contexts; markers there are stripped silently by absence-of-parser until a future AD wires them up.

### AD-706c-2 - Coordinate-aware compute_use BrowserTool tier (Wave 166)

**Date:** 2026-05-16. **Status:** SHIPPED. **Wave:** 166. **Closes:** #643.

**Problem.** AD-706 BrowserTool actions (click/type) require stable DOM selectors. Canvas-only surfaces (HTML5 games, embedded VNC, screenshot-only PDFs) expose nothing to state() and click(index=...) cannot resolve. Acting on wrong-pixel coordinates is a high-cost failure mode (destructive clicks at unintended targets).

**Solution.** Dedicated compute_use LLM tier (fifth peer of fast/standard/deep/vision in _LLM_TIERS). One new BrowserTool action verb compute_use_click(intent) that predicts pixel coords from a screenshot via a coord-tuned model, runs an AD-706c-1 verify handshake against the same image, and only clicks on agreement. Operator opt-in via cognitive.llm_base_url_compute_use + llm_model_compute_use; unconfigured = honest-degrade via the shared VISION_UNCONFIGURED_MESSAGE.

**Ten guards.** Eight inherited from AD-732 + BF-268..273 + BF-274 vision stack (refs not blobs, OpenAI vendor shape, dedicated peer tier, no text-tier fallback, scaled health-probe timeout, recovering tier usable, no cache, ModelRouter bypass), plus Guard #9 (coordinate-verification handshake via AD-706c-1 action_verify - reused, not forked) and Guard #10 (per-session trust budget: consecutive-autonomous cap default 5, per-session cap default 50).

**Reuse discipline.** is_vision_tier_configured extended to recognize tier_name='compute_use' - REUSE per BF-274 lesson; no new is_compute_use_tier_configured helper, no VISION_COMPUTE_USE_* constants (constant duplication anti-pattern was explicitly rejected in pass-1 review). _TIER_ORDER promoted to module-level constant ('fast','standard','deep') for clean source-scan assertion of BF-269 invariant. ModelRouter._resolve_model_for_tier bypass extended ('vision','compute_use') per BF-273.

**Late-bind handler registration.** compute_use.py imports action_verify from actions.py (Guard #9 reuse), and actions.py imports action_compute_use_click from compute_use.py at module-load (after action_verify is defined) to register the _HANDLERS slot. The late-bind avoids the circular-import surface. AD-706c-2 OWNS the compute_use_click slot in classify_action's ladder (placed BEFORE the silent/goto bands so AD-706e's later additive always-tier-3 entries can stack without re-shaping this branch). compute_use_click is always tier-3 (Captain ACK required every call).

**Events.** Four new EventType values inserted after BROWSER_VERIFY_OBSERVED: BROWSER_COMPUTE_USE_CLICK_PROPOSED (coord predicted), BROWSER_COMPUTE_USE_CLICK_VERIFIED (handshake passed), BROWSER_COMPUTE_USE_CLICK_ABORTED (verify disagreed - click NOT executed), BROWSER_COMPUTE_USE_CLICK_EXECUTED.

**Config.** Seven new CognitiveConfig fields (llm_base_url_compute_use, llm_api_key_compute_use, llm_model_compute_use, llm_timeout_compute_use, llm_api_format_compute_use, llm_temperature_compute_use, llm_top_p_compute_use, llm_max_tokens_compute_use) + tier_config() map extension. Two new BrowserToolConfig fields (compute_use_max_consecutive_autonomous_actions default 5 ge=0 le=20, compute_use_max_per_session default 50 ge=0 le=500). Trust-budget counters live on BrowserSession with public properties + public note_compute_use_call() / note_captain_ack() methods (LoD-compliant - no private-attr access from compute_use.py).

**Tier-2 throughout.** Every failure mode returns {ok: False, skipped_reason, ...} and never raises: missing_intent, compute_use_unconfigured, trust_budget_exhausted, session_not_started, screenshot_error, attachment_store_unavailable, attachment_store_write_error, compute_use_unavailable, parse_error, verification_error, verification_failed, click_error.

**AD-731 invariant preserved.** Screenshot bytes flow through AttachmentStore.write keyed by SHA-256 (hashlib.sha256(png).hexdigest()); no inline base64 on the bus. Source-scan regression test asserts no b64encode/base64.b64 in compute_use.py.

**Tests.** +16 pytest in tests/test_ad706c2_compute_use.py. Coverage: _HANDLERS registration, classify_action always-tier-3, classify_action_with_llm short-circuit, _TIER_ORDER module-level membership, _LLM_TIERS contents, unconfigured honest-degrade, missing intent, happy path end-to-end (screenshot to AttachmentStore to LLM to verify to mouse.click), verification disagreement aborts click, parse error degrade, no-cache enforcement, ModelRouter bypass, consecutive-autonomous cap + ACK refresh, per-session cap, AD-731 source-scan, OpenAI-shape source-scan. Real SystemConfig() + dataclass fakes at substrate boundary per BF-287. +4 existing tests adapted for the fifth peer tier (test_bf069_llm_health x3, test_per_tier_llm x2, test_ad732_vision_tier x1).

**Files.** src/probos/events.py (+4 EventType values), src/probos/cognitive/llm_client.py (_LLM_TIERS extended, _TIER_ORDER promoted to module-level, ModelRouter bypass extended, fallback chain logic simplified), src/probos/cognitive/vision_dispatch.py (is_vision_tier_configured extended for compute_use), src/probos/config.py (+8 CognitiveConfig fields, tier_config maps extended, +2 BrowserToolConfig fields), src/probos/tools/browser/session.py (+2 instance attributes, +2 public properties, +2 public methods), src/probos/tools/browser/actions.py (late-bind _HANDLERS registration, classify_action ladder short-circuit), src/probos/tools/browser/compute_use.py (new, ~280 lines), tests/test_ad706c2_compute_use.py (new, 16 tests), tests/test_bf069_llm_health.py + tests/test_per_tier_llm.py + tests/test_ad732_vision_tier.py (adapted for compute_use peer tier).

**Full gate.** 13778 -> 13794 passed.

**Forward markers (TECHNICAL triggers per AD-722c-3).** AD-706c-2a (native-app compute use - Windows accessibility / macOS AT-SPI; trigger: operator-reported demand from non-browser surfaces with >=3 distinct app categories). AD-706c-2b (multi-monitor compute use; trigger: HXI multi-display deployment lands). AD-706c-2c (vision-based form filling - text into coordinate-located field; trigger: AD-706e type action proves insufficient for >=3 sites in production). AD-706c-2d (demonstration learning; trigger: >=10 distinct compute_use_click sequences land in operator-recorded sessions per #517 dataset). AD-706c-2-trust-reset (session-level trust-budget decay on time/idle; trigger: operator-reported false-positive budget exhaustion in normal use).

### AD-706e - Browser Tool action vocabulary v2 (Wave 166)

**Date:** 2026-05-16. **Status:** SHIPPED. **Wave:** 166. **Closes:** #520.

**Verbs added.** drag (tier 2, tier 3 on tier-3 hosts via the existing click/type URL+text+host check path), key_combo (tier 2; tier 3 for destructive combos Control+W/Control+Q/Alt+F4/Control+Shift+W via new _KEY_COMBO_TIER_3_PATTERNS frozenset), mouse_move (tier 1, silent observation - added to the silent set), mouse_button (tier 2, validates button in {left/right/middle} and action in {down/up/click}), upload_file (always tier 3; forward-compatible credential_ref hook degrades to skipped_reason='credential_vault_unavailable' until AD-706f lands), download (tier 2; tier 3 for executable suffixes .exe/.dll/.dmg/.msi via new _DOWNLOAD_TIER_3_SUFFIXES tuple), eval_js (always tier 3, script length capped at 4096 chars via new _EVAL_JS_MAX_SCRIPT_LEN constant, result serialised via json.dumps(default=str)).

**Per-verb short-circuits.** classify_action uses per-verb if-branches (vs a set membership for always-tier-3) so AD-706f's fill_credential add is a single new branch with no merge conflict on a literal. AD-706e is NO-OP for compute_use_click (owned by AD-706c-2) and fill_credential (owned by AD-706f).

**LLM classifier compat.** classify_action_with_llm unchanged — its existing rule_tier >= 3 short-circuit handles the new always-tier-3 verbs automatically; new tier-1/2 verbs flow through unchanged.

**Events.** Three new EventType values (BROWSER_FILE_UPLOAD_REQUESTED, BROWSER_DOWNLOAD_REQUESTED, BROWSER_EVAL_JS_EXECUTED) emitted from BrowserTool.invoke() post-dispatch (alongside the existing per-action BROWSER_ACTION_EXECUTED telemetry channel). drag/key_combo/mouse_move/mouse_button reuse the global per-action telemetry only - no new event types.

**Forward-compat hooks.** upload_file accepts optional credential_ref param: when set, materialises file path from runtime.credential_vault.materialize_to_temp(credential_ref) (AD-706f) into a tempfile, then unlinks in finally. When vault is absent, honest-degrade with skipped_reason='credential_vault_unavailable'. The literal file_path path is the default v1 mode.

**eval_js safety.** Tier 3 (Captain ACK required). Script length cap of 4096 chars. No sandbox isolation in v1 (operator-supervised escape hatch only); AD-706e-2 forward marker covers sandbox isolation via headless context isolation.

**Tests.** +23 pytest in tests/test_ad706e_action_vocab_v2.py: happy + error path per verb (14), _HANDLERS registration (1), classify_action rules (8: mouse_move tier-1, drag default tier-2, drag-to-tier-3-host tier-3, key_combo destructive-combo tier-3, key_combo benign tier-2, upload_file always tier-3, eval_js always tier-3, download exe-suffix tier-3 + zip-suffix tier-2). Real BrowserToolConfig() + _FakePage/_FakeMouse/_FakeKeyboard dataclass stubs per BF-287.

**Files.** src/probos/events.py (+3 EventType values), src/probos/tools/browser/actions.py (+_KEY_COMBO_TIER_3_PATTERNS, +_DOWNLOAD_TIER_3_SUFFIXES, +_EVAL_JS_MAX_SCRIPT_LEN, +7 _action_* handlers, _HANDLERS late-bind extension, classify_action ladder extension), src/probos/tools/browser/tool.py (post-dispatch event emission for upload_file/download/eval_js), tests/test_ad706e_action_vocab_v2.py (new, 23 tests).

**Full gate.** 13794 -> 13816 passed (1 known dreaming flake outside this wave per Wave 166 dispatch).

**Forward markers (TECHNICAL triggers per AD-722c-3).** AD-706e-1 (vision-based form filling - text into coordinate-located field; trigger per AD-706c-2c). AD-706e-2 (eval_js sandbox isolation via headless context isolation; trigger: operator-reported eval_js misuse incident OR commercial-overlay request). AD-706e-3 (download to AttachmentStore - auto-write SHA-256; trigger: AD-720b chat-attach lands and downloads need to surface as attachments).

### AD-706f - Browser Tool credential vault (Wave 166)

**Date:** 2026-05-16. **Status:** SHIPPED. **Wave:** 166. **Closes:** #521.

**Problem.** Anthropic safety guideline #2 (avoid giving the model access to sensitive data) is honored in AD-706 v1 by NOT storing credentials at all. The agent cannot perform authenticated browser flows (login, OAuth consent, API key entry) without crossing that line. AD-706f is the deliberate decision to add scoped credential storage with full audit trail.

**Solution.** New src/probos/tools/browser/credentials.py exports CredentialScope + CredentialMetadata frozen dataclasses, CredentialVault Protocol, EncryptedFileCredentialVault v1 backend, _derive_kek helper, and action_fill_credential. JSON sidecar + Fernet symmetric authenticated encryption. KEK derived from AuthConfig.crew_scope_token (AD-722b-1 substrate) via stdlib hashlib.scrypt (n=2**14 r=8 p=1 dklen=32, salt=b'probos-credential-vault-v1'). No new shared secret - REUSES the existing crew-scope token.

**One new pip dep: cryptography>=42 (Apache-2.0 OR BSD-3-Clause dual-licensed).** Verified via `pip show cryptography` License-Expression field. Apache-2.0 OR BSD-3-Clause is the cleanest possible posture for OSS absorption per .github/copilot-instructions.md license whitelist. Captain ruling required in dispatch (the brief targeted 0 new pip deps); Captain approved at GATE 1. Alternatives considered: (a) DIY XOR+HMAC - security-fragile rejected; (b) `keyring` - adds Linux libsecret dep, defers cross-platform; (c) defer AD-706f - rejected, blocking authenticated flows that ship in the same wave (AD-706e upload_file.credential_ref hook).

**Scope contract.** CredentialScope is a frozen dataclass: allowed_agent_ids (empty set = Captain-only), allowed_domains (fnmatch against page host), expires_at (Unix timestamp, None = no expiry). list_refs returns CredentialMetadata with NO value field (regression-protected by test).

**Tier-3 always.** fill_credential is tier-3 unconditionally (Captain ACK every credential read). The action validates selector + credential_ref, honest-degrades when runtime.credential_vault is None, blocks http:// when require_https_for_fill (default True), checks scope.allowed_domains BEFORE decryption (fast path - reject without touching the KEK), then vault.read + page.fill. AD-731 invariant n/a (credentials are short strings).

**Events.** Five new EventType values inserted after BROWSER_EVAL_JS_EXECUTED: CREDENTIAL_STORED, CREDENTIAL_READ, CREDENTIAL_READ_DENIED, CREDENTIAL_DELETED, CREDENTIAL_FILL_REQUESTED.

**Config.** New nested CredentialVaultConfig under BrowserToolConfig.credential_vault (default-OFF transitional gate): enabled=False, backend='file' (v1 only), file_path='data/credential_vault.json', max_credentials=100 (ge=1 le=10000), require_https_for_fill=True.

**Two-phase startup wiring.** startup/finalize.py:_wire_browser_tool sets runtime.credential_vault=None next to BrowserTool construction; constructs the vault only when cfg.credential_vault.enabled AND cfg.auth.crew_scope_token is non-empty. Empty crew_scope_token at vault ctor raises RuntimeError with operator remediation message (set auth.crew_scope_token in config/system.yaml OR set credential_vault.enabled=False). When enabled but token missing, logs WARNING with operator remediation.

**Dispatch.** tool.py special-cases fill_credential (and compute_use_click) like AD-706c-1 verify - kwargs runtime + emit_event are passed in. agent_id from session._agent_id merged into params at dispatch boundary so the handler does not need to dig into session internals.

**Atomic persistence.** RLock for concurrent access; tmp+rename atomic writes mirror AD-720d-2.1 / AD-721d-4 patterns. Async API dispatches blocking I/O through asyncio.get_running_loop().run_in_executor (BF-280 pattern - subprocess_exec banned but executor + sync I/O is the right shape).

**materialize_to_temp contract.** Decrypts plaintext to a tempfile.mkstemp path, returns Path. CALLER MUST UNLINK in finally - contract documented in module + AD-706e upload_file consumer's finally block was already designed for this.

**Tests.** +15 pytest in tests/test_ad706f_credential_vault.py: default-off, ctor rejection on empty token, KEK determinism (same token same KEK, different token different KEK, len=32), store/read roundtrip, scope denies unauthorized agent + Captain not in non-empty allow-list, expires_at enforced, restart persistence (load existing sidecar), materialize_to_temp returns path caller unlinks, delete, list_refs returns metadata with NO value field, action honest-degrade when vault None, https required blocks http://, domain mismatch fast-rejected with event, happy path with CREDENTIAL_READ + CREDENTIAL_FILL_REQUESTED events, always-tier-3 classification. Real EncryptedFileCredentialVault against tmp_path per BF-287 (no MagicMock at substrate boundary).

**License audit.** THIRD_PARTY_LICENSES.md appended: cryptography 48.0.0, Apache-2.0 OR BSD-3-Clause, used by tools/browser/credentials.py (cryptography.fernet.Fernet).

**Files.** pyproject.toml (+cryptography>=42), THIRD_PARTY_LICENSES.md (+cryptography section), src/probos/events.py (+5 EventType values), src/probos/config.py (+CredentialVaultConfig + BrowserToolConfig.credential_vault field), src/probos/tools/browser/credentials.py (new, ~330 lines), src/probos/tools/browser/actions.py (fill_credential late-bind + classify_action tier-3 short-circuit), src/probos/tools/browser/tool.py (dispatch special-cases for compute_use_click and fill_credential), src/probos/startup/finalize.py (vault construction with two-phase init), tests/test_ad706f_credential_vault.py (new, 15 tests).

**Full gate.** 13816 -> 13832 passed (20 skipped).

**Forward markers (TECHNICAL triggers per AD-722c-3).** AD-706f-1 (OS-keychain backend - Windows Credential Manager / macOS Keychain / Linux Secret Service; trigger: operator-requested cross-machine credential sync OR commercial-overlay). AD-706f-2 (per-credential audit log query API; trigger: >=3 audit-trail GET requests in production). AD-706f-3 (credential rotation API; trigger: any credential reaches expires_at in production). AD-706f-4 (multi-Captain per-crew vault, pairs with AD-722b-1a; trigger: AD-722b-1a lands).


### AD-706a - Captain-watch MJPEG streaming bridge (Wave 166)

**Date:** 2026-05-17
**Decision:** Implement Captain-watch over `multipart/x-mixed-replace` MJPEG, not WebRTC. New `routers/browser_stream.py` exposes `GET /api/browser/sessions/{session_id}/stream`; the generator awaits Playwright `page.screenshot(type="jpeg", quality=N)` at `1/streaming_fps` cadence and yields each frame with the `--frame` boundary. Every browser renders the response natively in an `<img>` tag - zero client-side JS, zero new pip/npm deps.

**Status:** Shipped Wave 166. Closes #516.

**Rationale.** WebRTC requires STUN/TURN + SDP negotiation + a long-lived peer connection. For local-machine HXI watching a local Playwright session, that complexity is unjustified. MJPEG is supported by every browser image renderer, and the bandwidth trade-off (no inter-frame compression) is acceptable for localhost/LAN. Federation streaming + WebRTC upgrade are forward-marked, not v1.

**Public viewer-slot API.** ``BrowserTool`` gains three public surfaces: ``active_viewers`` (property), ``acquire_viewer_slot()``, ``release_viewer_slot()``. Backed by an ``asyncio.Lock`` for cap enforcement. The streaming router does NOT touch ``_active_viewers`` - Demeter / SOLID. 503 + ``Retry-After: 5`` when cap exhausted.

**``require_crew_scope`` extension.** ``<img src>`` cannot set HTTP headers, so MJPEG needs a query-param surface. Single-dep extension (BF-274 pattern - don't fork APIs when one extension covers both shapes): the dependency now takes ``request: Request`` and falls back to ``?token=`` when the ``Authorization:`` header is absent. Empty-string token is rejected explicitly (regression-protected). Header-only AD-722b-1 callers are byte-compatible (the new positional is FastAPI-injected, invisible to ``Depends`` consumers).

**AD-731 invariant preserved.** JPEG frames are ephemeral on-wire bytes; they are NEVER stored in ``AttachmentStore``. The bus / message layer does not carry blobs - this AD adds an HTTP streaming surface, not a new IntentMessage flow.

**Config (default-OFF).** Four new ``BrowserToolConfig`` fields: ``streaming_enabled`` (False, Wave 10 convention #14), ``streaming_fps`` (4, ge=1 le=15), ``streaming_jpeg_quality`` (60, ge=20 le=95), ``streaming_max_concurrent_viewers`` (4, ge=1 le=16). ``BrowserSession.get_streaming_url()`` returns the path-only URL when enabled; None otherwise.

**Event types.** ``BROWSER_STREAM_OPENED``, ``BROWSER_STREAM_CLOSED``, ``BROWSER_STREAM_FRAME_DROPPED`` (last reserved for backpressure; emitted at warning threshold in v1 path is logged at debug). OPENED + CLOSED bracket every viewer lifecycle; ``CancelledError`` re-raised after the CLOSED emit per Async Discipline.

**HXI surface.** ``ui/src/components/browser/BrowserStreamPanel.tsx`` renders a stroke-based SVG glyph when ``streamingUrl`` is null and a plain ``<img>`` otherwise (HXI Design Principle #3 - no emoji, no Material Design). Appends ``?token=`` only when a non-empty token is provided. Component is NOT yet wired into a parent panel in v1 - forward marker AD-706a-parent-wire.

**Test pattern.** ``_FakePage.screenshot`` raises after a small ``max_frames`` count so the TestClient (which blocks until the generator finishes) doesn't deadlock on the production infinite loop. Real ``SystemConfig()`` + ``BrowserToolConfig()`` per BF-287; no MagicMock at substrate boundaries.

**Full gate.** 13832 -> 13843 passed (20 skipped, 1 known dreaming flake outside this wave per dispatch).

**Forward markers (TECHNICAL triggers per AD-722c-3).** AD-706a-1 (Federation-hop streaming; trigger: AD-722b-5a federation streaming primitive lands). AD-706a-2 (WebRTC upgrade with adaptive bitrate; trigger: >=3 operator reports of MJPEG bandwidth issues OR LAN viewer count exceeds 8). AD-706a-parent-wire (wire ``BrowserStreamPanel`` into agent-detail HXI surface; trigger: HXI agent-detail panel refactor lands OR Captain demand). AD-706a-frame-diff (diff-based frame transmission; trigger: bandwidth profiling shows >70% of frame bytes are unchanged regions).

### AD-706b - Browser session video recording + retention reaper (Wave 166)

**Date:** 2026-05-17
**Decision:** Use Playwright's built-in ``record_video_dir`` context option to opt-in record live BrowserSession surfaces as ``.webm`` files under ``data/browser-sessions/<session_id>/``. A background ``RecordingReaper`` walks the recording tree at ``recording_reaper_interval_seconds`` cadence, deletes files older than ``recording_retention_days``, and enforces a per-session size cap by removing oldest-first. v1 keeps recordings on disk (no AttachmentStore promotion - forward marker AD-706b-2).

**Status:** Shipped Wave 166. Closes #517.

**Why Playwright's native recording (not MJPEG capture).** ``record_video_dir`` is built into Playwright's BrowserContext; the recorder runs inside the browser process and produces a single WebM file per page. Hooking this in start() + closing the context in stop() is byte-compatible with the existing lifecycle. v1 does NOT transcode to MP4 - the codec conversion belongs in a separate AD (706b-1) that consumes the AD-721b-1a ffmpeg helper shipping in this same wave.

**Why on-disk (not AttachmentStore).** Each session recording can be tens of MB. AttachmentStore is for content-addressable refs (SHA-256 keys, small-ish blobs). Promoting video to AttachmentStore needs a separate decision: (1) does ChromaDB-backed retrieval make sense for videos? (2) what is the retention story when SHA-256 hashing the contents makes them effectively immortal? Forward-marked at AD-706b-2.

**``runtime.stop()``, not ``runtime.shutdown()``.** ProbOSRuntime exposes ``async def stop(reason: str = '')`` at ``runtime.py:2227``. ``runtime.shutdown()`` is NOT a method on the runtime class (only ``shutdown()`` as a module-level function in ``startup/shutdown.py``). The recording reaper cleanup is added inside ``shutdown()`` so it runs as part of the standard async teardown.

**``_wire_browser_tool`` split.** The synchronous portion declares ``runtime.recording_reaper = None`` next to BrowserTool construction. A new async helper ``_start_recording_reaper`` (called from ``finalize_startup`` after the sync wire) constructs and awaits ``reaper.start()`` when ``recording_enabled`` is True. This preserves the sync-call signature at the existing callsite while satisfying the new async dependency.

**BrowserSession surface.** ``BrowserSession`` ctor now accepts an optional ``emit_event`` callable so recording lifecycle events surface from the session itself, without reaching across BrowserTool. ``start()`` creates the session subdir via ``Path.mkdir(parents=True, exist_ok=True)`` BEFORE handing the path to ``new_context(record_video_dir=...)``. ``stop()`` separates the close-context error path from the close-page / close-browser paths so ``BROWSER_RECORDING_FAILED`` is emitted only when the recording finalize step itself errored.

**Tier-2 throughout the reaper.** FileNotFoundError / PermissionError on individual webm files are logged at warning and skipped, never raised. The async loop catches CancelledError, performs cleanup, and re-raises (standing Async Discipline). Blocking filesystem work is dispatched through ``loop.run_in_executor(None, self._reap_sync)``.

**Admin endpoints.** ``routers/browser_recordings.py`` exposes three Captain-only surfaces:
* ``GET /api/browser/recordings`` - list (session_id, filename, size_bytes, mtime).
* ``GET /api/browser/recordings/{session_id}/{filename}`` - FileResponse (streams the webm).
* ``DELETE /api/browser/recordings/{session_id}`` - shutil.rmtree on the subdir.

Path-traversal is rejected via ``.resolve()`` prefix check against the recording root.

**Config (default-OFF).** Five new ``BrowserToolConfig`` fields: ``recording_enabled`` (False, Wave 10 convention #14), ``recording_dir`` (``data/browser-sessions``), ``recording_retention_days`` (7, ge=1 le=365), ``recording_reaper_interval_seconds`` (3600, ge=60 le=86400), ``recording_max_size_mb_per_session`` (500, ge=10 le=5000).

**Event types.** ``BROWSER_RECORDING_STARTED``, ``BROWSER_RECORDING_STOPPED`` (includes summed ``size_bytes`` across ``*.webm`` in the subdir), ``BROWSER_RECORDING_EXPIRED`` (per-delete with reason ``retention`` or ``size_cap``), ``BROWSER_RECORDING_FAILED`` (close-context error path).

**AD-731 invariant preserved.** Recordings are large files written by Playwright's built-in recorder. They never traverse the bus / message layer; they live on disk and are surfaced through HTTP FileResponse. No inline base64 blob in any IntentMessage param.

**Test pattern.** Hand-rolled ``_FakeBrowser`` / ``_FakeContext`` / ``_FakePlaywright`` chain installed via ``monkeypatch.setitem(sys.modules, ...)`` so the lazy ``from playwright.async_api import async_playwright`` inside ``BrowserSession.start()`` picks up the fake. Real ``BrowserToolConfig()`` per BF-287. ``tmp_path`` for recording directories. ``os.utime`` to backdate mtimes for retention testing.

**Full gate.** 13843 -> 13852 passed (20 skipped).

**Forward markers (TECHNICAL triggers per AD-722c-3).** AD-706b-1 (ffmpeg MP4 transcode using AD-721b-1a's ``_resolve_ffmpeg_binary`` helper; trigger: operator request OR codec compatibility issue with downstream tooling). AD-706b-2 (AttachmentStore promotion of recordings via content-addressable SHA-256 refs; trigger: AttachmentStore size-cap policy ratified OR operator requests cross-session retrieval). AD-706b-3 (HXI surface for recording playback - timeline scrubber + delete; trigger: Captain operates recording feature for >7 days OR HXI polish wave scheduled). AD-706b-4 (per-domain recording allowlist - record only on URL match; trigger: privacy-sensitive operator deployment).

### AD-721b-1a - ffmpeg-backed audio format conversion (Wave 166)

**Date:** 2026-05-17
**Decision:** Add ffmpeg-backed audio format conversion in front of rhubarb-lip-sync so client-captured ``audio/webm`` (Chrome MediaRecorder default) reaches the phonetic-alignment path instead of the heuristic fallback. ffmpeg is operator-provided at ``tools/ffmpeg/ffmpeg(.exe)`` (gitignored); when missing, BF-292's honest-degrade contract is preserved (``generate_visemes`` returns ``[]``).

**Status:** Shipped Wave 166. Closes #663.

**BF-280 + BF-282 + BF-286 - the recurring subprocess discipline.** The conversion path is the canonical case study:
* BF-280: ``subprocess.Popen`` dispatched via ``loop.run_in_executor`` (not ``asyncio.create_subprocess_*``) so the WindowsSelectorEventLoop runtime can shell out without ``NotImplementedError``.
* BF-282: ffmpeg writes to ``tempfile.NamedTemporaryFile(suffix='.wav', delete=False)`` via ``-y <path>``; ``stdout`` is intentionally ``DEVNULL`` (NEVER capture binary on stdout - on Windows + pipe-redirected stdout, the C runtime opens it in text mode and corrupts every ``0x0A`` PCM byte).
* BF-286: tests stub ``subprocess.Popen`` with a ``_FakePopen`` that records args + emulates ``communicate()`` / ``kill()`` / ``returncode`` - the production shape (last positional = output file path; ``-i`` is the input flag; ``-ac 1 -ar 22050 -acodec pcm_s16le`` are the encode params) is asserted directly in the success test.

**Honest-degrade contract preserved.** BF-292 (Wave 165) added the boundary that turned every non-WAV/OGG audio path into ``return []`` + INFO log. AD-721b-1a inserts the ffmpeg attempt BEFORE that early return; on any failure (ffmpeg path empty, binary missing, timeout, non-zero exit, empty output), the fall-through is byte-identical to the BF-292 contract. The empty-list contract is the signal to the router to switch to the heuristic schedule client-side.

**Signature change is backward-compatible.** ``generate_visemes(audio_path, binary_path, timeout_seconds=30.0, *, ffmpeg_binary_path: str | None = None)`` keeps all positional args. The new keyword-only parameter defaults to None, so any existing direct caller (no router or tests today besides this one and the two router callsites updated in lockstep) continues to honest-degrade for non-WAV/OGG.

**Extracted ``_run_rhubarb``.** The rhubarb invocation moved into a private helper so ``generate_visemes`` can wrap it in ``try/finally`` that unlinks the optional converted tempfile. The body of ``_run_rhubarb`` is byte-identical to the previous rhubarb block; only the wrapping changed.

**License posture.** ffmpeg is LGPL-2.1+ / GPL-2+. By keeping the binary operator-provided (gitignored under ``/tools/``, same pattern as piper + rhubarb), ProbOS distribution stays clean of any GPL propagation surface. The repo never ships the binary; the operator installs it locally.

**Config.** One new ``LipSyncConfig`` field: ``ffmpeg_binary_path`` (default ``tools/ffmpeg/ffmpeg``). NO new ``enabled`` flag - the path is enabled-when-present, mirroring rhubarb's binary discovery pattern.

**Router callsites.** Two call sites in ``routers/avatars.py`` thread ``ffmpeg_binary_path=lipsync_cfg.ffmpeg_binary_path`` into ``generate_visemes``: the ``/api/avatars/lipsync`` endpoint and the TTS reuse path that processes synthesized audio.

**Full gate.** 13852 -> 13861 passed (20 skipped).

**Forward markers (TECHNICAL triggers per AD-722c-3).** AD-721b-1a-1 (catalog the explicit set of supported input formats and surface ``Accept`` MIME in the router; trigger: HXI surfaces the supported-formats list to the captain). AD-721b-1a-2 (ffmpeg health probe on startup like rhubarb's ``probe_version``; trigger: operator reports silent fall-through and needs startup-time signal). AD-721b-1a-3 (ffmpeg discovery via ``PATH`` lookup as well as the explicit path; trigger: operator request for package-manager-installed ffmpeg).

### AD-718e - Multi-language voice selection (Wave 166)

**Date:** 2026-05-17
**Decision:** Add ``language: str = "en"`` to ``VoiceProfile`` (BCP 47-shape ISO-639-1 tag with optional region). Extend ``voice.ts`` voice resolution to prefer the profile's language family over the en fallback. Add a language filter dropdown to ``ProfileInfoTab``. Expand the piper voice fetcher with es/fr/de/it/nl/pt voices from rhasspy/piper-voices (Apache-2.0 / MIT).

**Status:** Shipped Wave 166. Closes #526.

**Backward compatibility is the load-bearing constraint.** Every existing on-disk profile predates the field. The ``__post_init__`` validation strips whitespace and maps empty string to ``"en"`` BEFORE the regex check; ``from_dict`` accepts a missing ``language`` key (the dataclass default kicks in). Both paths are regression-tested.

**Regex shape.** ``^[a-z]{2,3}([_-][A-Za-z0-9]{2,8})?$`` - conservative, not full BCP 47. Lowercase prefix only; region/variant after ``_`` or ``-``. Uppercase prefixes (``"EN"``) are rejected explicitly. The browser SpeechSynthesis API hands back lang tags like ``"en-US"`` / ``"es-ES"`` / ``"fr-FR"``, so the prefix-only match (``v.lang.toLowerCase().startsWith(norm)``) is enough at the resolver.

**Resolution ladder.** ``named ?? langMatch ?? findPreferredVoice()``. The operator-chosen ``voice_name`` is still authoritative when present; the language tag is the next preference, and only if neither matches do we degrade to the original en-first ``findPreferredVoice``. AD-718 default behavior is byte-identical when ``language`` is undefined.

**UI filter is additive.** A new ``<select data-testid="ad718e-lang-filter">`` dropdown above the voice picker; distinct lang codes are extracted from the loaded piper catalog. Selecting a code filters ``availableVoices`` by ``lang.split(/[_-]/)[0] === voiceLangFilter``. "All" (empty) shows the full catalog (today's behavior).

**Piper catalog expansion.** 18 new entries across es/fr/de/it/nl/pt sourced from ``huggingface.co/rhasspy/piper-voices`` (Apache-2.0 / MIT - verified against the upstream HF repo, same posture as the existing en_US / en_GB blocks). The fetcher's per-voice try/catch honest-degrades on 404, so catalog drift is non-fatal. The entries are empirical, not normative - upstream catalog changes should be pruned in follow-ups.

**Voice resolution does NOT silently re-route per language.** The operator-chosen ``voice_name`` is still the authoritative selection. The language tag biases the fallback path only - this AD is a selection UX improvement, not a runtime re-routing engine. AD-718e-1 forward marker covers "auto-switch voice when language tag changes" if that turns out to be wanted in practice.

**AD-731 invariant n/a.** No new bus payloads; no new attachment flow. Voice settings are short strings (≤ 16 chars language tag).

**Full gate.** 13861 -> 13869 pytest; vitest 657 -> 667 (close to dispatch target ≥668 - one test moved in cluster 1; +5 net this AD across 3 voice + 2 ProfileInfoTab tests).

**Forward markers (TECHNICAL triggers per AD-722c-3).** AD-718e-1 (auto-switch ``voice_name`` when the language tag changes; trigger: operator reports manual re-selection burden on multilingual agents). AD-718e-2 (BCP 47 script + region full-form validation per ``Intl.Locale``; trigger: international operator deployment OR LLM emits a non-canonical tag). AD-718e-3 (server-side TTS catalog union with browser SpeechSynthesisVoice; trigger: HXI surfaces "all voices the operator could use" instead of source-specific lists). AD-718e-4 (piper voice download script per-language toggle so operators don't fetch every language; trigger: operator deployment with bandwidth constraints).

### AD-721i-1 - License-audited starter asset pack (manifest only, no asset bytes) (Wave 166)

**Date:** 2026-05-17
**Decision:** Ship the **audit infrastructure** for AD-721i (DSL → Blender VRM renderer) without bundling any asset bytes. New ``data/avatar-assets/MANIFEST.md`` is the audit ledger: every candidate asset is listed with its source URL, license, attribution string, and disposition. v1 has **zero APPROVED rows** — every candidate is RESEARCH until Captain ruling flips it.

**Status:** Shipped Wave 166. Closes #542.

**Why ship the manifest before the bytes.** ProbOS's license hygiene rules (``.github/copilot-instructions.md`` + the 2026-05-09 license-posture user-memory note) require per-asset provenance evidence before any binary is committed. Architect-time research can identify clean candidates (Quaternius CC0, KayKit CC0, Khronos glTF CC0, Poly Haven CC0); operator-time execution generates the SHA-256 + ATTRIBUTION audit trail by running the fetcher script against the upstream source at build time. Splitting the work this way lets Captain ruling gate the irreversible step (committing binaries) without blocking the reviewable step (documenting the policy).

**License whitelist is hard-coded.** ``probos.avatars.asset_manifest.validate_license`` returns True iff the license string is one of ``{CC0, CC0-1.0, MIT, Apache-2.0, Apache 2.0, BSD, BSD-2-Clause, BSD-3-Clause, CC-BY-4.0, CC-BY}``. Anything else (GPL, AGPL, CC-BY-SA, CC-BY-NC, proprietary, "per-file metadata") returns False. The validator is the only boundary that decides what is allowed; the manifest's ``disposition`` column is informational (REJECTED rows must still document the license string so the audit trail explains the decision).

**REJECTED rows document the decision.** v1 manifest carries four explicit REJECTED entries with rationale:
* **MakeHuman Community** (AGPL-3.0): pattern-only absorption is acceptable; absorbing binaries propagates copyleft.
* **Mixamo** (Adobe TOS): redistribution restricted, Adobe-account tied.
* **Ready Player Me** (Proprietary): commercial overlay only.
* **VRoid Studio outputs** (per-file VRM metadata): each VRM file has author terms baked in; per 2026-05-09 user-memory note on file-level licensing metadata.

**The fetcher script is shipped but does nothing in v1.** ``scripts/avatar-assets-fetch.ps1`` parses MANIFEST.md, filters to APPROVED, downloads via ``Invoke-WebRequest``, SHA-256-verifies (mismatch → delete + non-zero exit), and writes attribution to ``ATTRIBUTION.txt``. Because v1 has zero APPROVED rows, running the script is a no-op with an informative "0 assets approved" message. Operators see the manifest as the source of truth and the script as the executor.

**.gitignore policy.** ``data/avatar-assets/_<category>/`` and ``ATTRIBUTION.txt`` are gitignored — bytes are operator-fetched. ``MANIFEST.md`` itself is **tracked** (it's the audit ledger that every PR review touches).

**Workflow.** Propose: PR adds RESEARCH row → Captain reviews → flips to APPROVED. Operator runs fetcher → downloads + verifies + attributes. Revoke: flip APPROVED → REJECTED → operator manually deletes; ATTRIBUTION regenerated on next run. Documented in ``docs/development/avatar-assets.md``.

**Renderer wire-up unchanged.** ``src/probos/avatars/_blender/render_avatar.py`` already reads ``<avatars_dir>/_base_meshes/<body_type>.blend`` and falls through to the E10 procedural capsule when missing. The capsule path stays functional v1; the realistic-humanoid path lights up incrementally as operators approve and fetch assets.

**AD-731 invariant n/a.** Asset bytes flow through the filesystem to Blender, not the bus.

**Full gate.** 13869 -> 13875 pytest (incl. 1 known dreaming flake outside this wave per dispatch); vitest unchanged (no UI surface in this AD).

**Forward markers (TECHNICAL triggers per AD-722c-3).** AD-721i-1a (bundle the first APPROVED Captain-ruled asset; trigger: Captain flips ≥1 RESEARCH row to APPROVED). AD-721i-1b (per-asset license file capture - download the LICENSE / NOTICE alongside the asset and check it into ``data/avatar-assets/licenses/``; trigger: any CC-BY APPROVED row lands AND attribution audit fails). AD-721i-1c (asset registry promotion to AttachmentStore SHA-256 refs; trigger: cross-machine avatar synchronization scenario lands).
### AD-721d-3 - Visual avatar preview before DSL persistence (Wave 167)

**Date:** 2026-05-17. **Status:** Shipped. **Closes** #619.

**Capability.** Render an unpersisted ``AvatarDSL`` to a draft VRM so the Captain sees the 3D result BEFORE approving. Closes the gap where ``AgentProfilePanel`` rendered a parametric capsule fallback during review because the canonical ``<avatars_dir>/<agent_id>.vrm`` is only regenerated post-approval.

**Endpoint.** New ``POST /api/agent/{agent_id}/appearance/preview`` accepts ``{dsl: AvatarDSL_dict}``, invokes ``BlenderRenderer.render(dsl, agent_id)`` directly (NOT via the ``regenerate_avatar`` intent - that path moves the result into the canonical cache via ``os.replace``). The endpoint reads the draft VRM bytes, writes them through ``AttachmentStore.write(sha, blob, mime)``, and returns ``{agent_id, attachment_id, size_bytes}``. Does NOT persist; does NOT consume an iteration slot; does NOT touch the canonical cache.

**AD-731 invariant.** Preview VRM bytes ride ``AttachmentStore`` SHA-256 refs - never inlined in the HTTP response body. ``model/gltf-binary`` MIME added to ``_MIME_TO_EXT`` in ``FilesystemAttachmentStore`` (single source of truth for MIME-to-extension).

**Honest-degrade taxonomy.** 503 ``renderer_unavailable`` when ``cfg.avatars.renderer_enabled=False``. 503 ``blender_not_found`` on ``BlenderNotFoundError``. 502 ``render_failed`` on ``BlenderRenderError``. 422 ``schema_violation`` on bad DSL. 413 ``preview_too_large`` when bytes exceed ``cfg.avatars.max_vrm_size_bytes``. The HXI keeps the parametric capsule fallback in every degraded case.

**BF-280 boundary preserved.** Endpoint reuses the existing ``BlenderRenderer`` surface; introduces NO new ``asyncio.create_subprocess_*`` call site. The known latent risk inside ``blender_renderer.py:178`` is out of scope for this AD.

**HXI.** ``CrewAvatarPopout.tsx`` gains four new props (``previewVrmUrl``, ``onRenderPreview``, ``previewInFlight``, ``previewError``) and a stroke-based SVG "Render preview" button (eye glyph - no emoji per HXI Design Principle #3). When ``previewVrmUrl`` is set, the existing ``<CrewVRM vrmUrl>`` swaps to that URL (reuses ``CrewVRM.tsx:252`` absolute-URL pass-through). ``AgentProfilePanel.tsx`` holds the state and wires ``onRenderPreview`` to POST the proposed DSL and stash the resulting ``/api/chat/attachments/<sha>`` URL; state cleared on approve / reject / close.

**Event.** New string event-type ``appearance_preview_rendered`` (matches existing ``appearance_proposal`` / ``appearance_approved`` / ``appearance_revision_mediated`` pattern - NOT a new ``EventType`` enum value).

**Tests.** +8 pytest in ``tests/test_ad721d_3_avatar_preview.py`` covering happy path, avatars-disabled 503, agent missing 404, invalid DSL 422, renderer-disabled 503, BlenderNotFoundError 503, BlenderRenderError 502, real ``FilesystemAttachmentStore`` round-trip (BF-287). +3 vitest in ``ui/src/__tests__/CrewAvatarPopout.preview.test.tsx`` covering click-invokes-callback, swap-pane-on-previewVrmUrl, disabled-and-error-inline-during-in-flight. Real ``AvatarsConfig()`` / ``AttachmentsConfig()`` per BF-287. Renderer monkey-patched at the source module so the in-function ``from probos.avatars.blender_renderer import BlenderRenderer`` resolves the stub.

**Full gate.** 13875 -> 13883 pytest. Vitest 667 -> 670. UI bundle ``index-1THkGO2n.js``.

**Zero new deps.** Reuses ``BlenderRenderer`` + ``AttachmentStore`` + three.js (all already present).

### AD-721g - Per-tier baseline VRMs (Wave 167)

**Date:** 2026-05-17. **Status:** Shipped. **Closes** #534.

**Capability.** Per-rank baseline VRM resolution so an unconfigured Ensign in Engineering can default to a different avatar than an unconfigured Senior Officer in Medical. Closes the gap where every crew member without a custom VRM either inherited a seed `vrm_url` or fell back to the parametric capsule -- no notion of "default avatar for this tier."

**License posture.** No avatar bytes ship in the repo (AD-721i-1 whitelist: CC0 / MIT / Apache / BSD / CC-BY). The manifest declares which filenames are acceptable; the operator installs the bytes locally under ``<avatars_dir>/_baselines/<filename>``. v1 manifest defaults are all ``""`` -- ProbOS still boots with zero config.

**Config.** New ``BaselineVRMManifest`` Pydantic block with four bare-filename slots: ``ensign`` / ``lieutenant`` / ``commander`` / ``senior``. Hung off ``AvatarsConfig.baseline_vrms`` via ``Field(default_factory=BaselineVRMManifest)``.

**Resolver.** New ``src/probos/avatars/baseline_resolver.py`` exposes two functions: ``resolve_baseline_vrm_filename(rank, manifest) -> str`` (pure mapping; does not touch the filesystem) and ``resolve_baseline_vrm_path(rank, manifest, avatars_dir) -> Path | None`` (verifies the file exists under ``<avatars_dir>/_baselines/``). Defense-in-depth: filenames containing ``/``, ``\``, or ``..`` are rejected with a logged warning before any path math; the resolved target is ``.resolve()``-checked to stay under ``avatars_dir``.

**Read-path wire.** ``routers/agents.py`` inserts a baseline fallback step BETWEEN the AD-721d D8 cache synthesis block and the parametric fallback: when ``appearance_dict["vrm_url"]`` is still empty, the resolver maps ``Rank.from_trust(trust_score)`` to the manifest filename and synthesises ``_baselines/<filename>`` as the response ``vrm_url``. The existing ``CrewVRM.tsx:250`` bare-filename resolver already prepends ``/api/system/avatars/``, so the new path renders without any UI delta. ``routers/system.py:get_avatar`` already permits subdirectories under ``avatars_dir`` (its ``relative_to`` check is the gate); no new endpoint needed.

**Rank-only in v1.** Department-aware baselines are explicitly deferred. The matrix would be 4 ranks * N departments; v1 keeps it tractable by keying on rank only. Future AD can extend ``BaselineVRMManifest`` with an optional ``by_department`` subfield without breaking the v1 contract.

**Tests.** +9 pytest in ``tests/test_ad721g_baseline_vrms.py``. Eight resolver unit tests cover the pure-mapping happy path (empty manifest, populated + file present, populated + file missing), three hostile-filename rejections (slash, ``..``, backslash), and two ``Rank.from_trust`` mappings (ensign-trust -> ensign-entry, senior-trust -> senior-entry). One integration test exercises the read path through TestClient against a synthesised baseline file with agent_type ``ad721g_test_agent`` so it doesn't collide with seed-profile vrm_urls. Real ``AvatarsConfig`` + real ``BaselineVRMManifest`` throughout per BF-287 -- no MagicMock at the config boundary.

**AD-731 invariant.** N/A -- the baseline path is a filename string, not blob bytes. Files are served by the existing avatar-serve route from the on-disk ``_baselines/`` subdir.

**Full gate.** 13883 -> 13892 pytest. Vitest unchanged (no UI surface). No UI build needed.

**Zero new deps.** Pure resolver + config + read-path wiring.

### AD-721h - Browser-based VRM upload UI (Wave 167)

**Date:** 2026-05-17. **Status:** Shipped. **Closes** #535.

**Capability.** Captain drags a custom ``.vrm`` into the HXI avatar editor; backend validates type + size; file lands at ``<avatars_dir>/<agent_id>.vrm`` AND in the content-addressed AttachmentStore; ``ProfileStore.vrm_url`` updated so the next read picks up the new avatar.

**Endpoint.** New multipart ``POST /api/agent/{agent_id}/appearance/vrm``. Reuses the AD-720a multipart pattern (``UploadFile = File(...)``). Defense-in-depth chain runs in this order:
1. ``_avatars_feature_check(runtime)`` (503 when ``cfg.avatars.enabled=False``)
2. ``runtime.registry.get(agent_id)`` (404 when missing)
3. size cap: 413 ``too_large`` when ``len(blob) > cfg.avatars.max_vrm_size_bytes``
4. minimum-size gate: 400 ``too_small`` when ``len(blob) < 12``
5. glTF binary magic: 415 ``not_a_vrm`` when ``blob[:4] != b"glTF"``
6. ``target.resolve().relative_to(avatars_dir.resolve())`` path-traversal guard

**Dual-write per AD-731.** Content-addressed write FIRST via ``AttachmentStore.write(sha, blob, "model/gltf-binary")``, THEN atomic named copy via ``os.replace(<tmp>, <avatars_dir>/<agent_id>.vrm)``. Tests assert byte parity between the two locations and that no ``.tmp`` file leaks on the last-write-wins concurrent path.

**Security note.** Magic-byte check rejects non-glTF blobs BEFORE storage. A test verifies that a 415 rejection leaves the named cache untouched on disk - no half-written state.

**ProfileStore.** When a profile store is available, ``vrm_url`` is set to ``"<agent_id>.vrm"`` so the appearance read path resolves the new avatar via ``CrewVRM.tsx:250`` bare-filename pass-through (mirrors AD-721i E4 post-render persistence).

**HXI.** ``AgentProfilePanel.tsx`` adds "Upload VRM" button + hidden ``<input type="file" accept=".vrm,application/octet-stream,model/gltf-binary">`` next to "Design avatar". Click triggers the file picker; ``onChange`` POSTs multipart; success refreshes ``/api/agent/{id}/profile`` so the CrewVRM viewer re-loads with the new URL. 413 / 415 surface as inline error reason on the button's ``title`` attribute (no toast spam, per HXI Principle #3 idiom of using ambient signal over noisy interrupts). Stroke-based SVG upload glyph (arrow over baseline).

**Event.** New string event-type ``appearance_vrm_uploaded`` (not a new EventType enum value).

**v1 scope.** Validates magic bytes only. Full VRM 1.0 schema validation (saturday06 add-on roundtrip) is deferred - file a forward marker AD-721h-2 if Captain wants it. Drag-and-drop zone is not in v1; the file-picker happy path is the contract.

**Tests.** +8 pytest in ``tests/test_ad721h_vrm_upload.py`` (happy path with named-cache + ProfileStore update + sha parity; avatars-disabled 503; agent-missing 404; size cap 413 ``too_large``; min-size 400 ``too_small``; missing-magic 415 ``not_a_vrm`` with disk-state assertion that nothing landed; AttachmentStore-vs-named-cache byte parity; last-write-wins overwrite with no leaked ``.tmp``). +4 vitest in ``ui/src/__tests__/AgentProfilePanel.uploadVRM.test.tsx`` (button-clicks-input via ``vi.spyOn(input, 'click')``; happy-path multipart POST captures the ``FormData`` body; 413 inline error surfaces ``too_large`` on title; 415 inline error surfaces ``not_a_vrm`` on title). Real ``FilesystemAttachmentStore`` + real ``tmp_path`` avatars_dir per BF-287.

**Full gate.** 13892 -> 13900 pytest. Vitest 670 -> 674. UI bundle ``index-1THkGO2n.js`` -> ``index-BTcSysUH.js``.

**Zero new deps.** Reuses FastAPI ``UploadFile``, ``FilesystemAttachmentStore``, existing avatar-serve route. ``model/gltf-binary`` MIME was already added to ``_MIME_TO_EXT`` by AD-721d-3 in this same wave.

### AD-720b - Chat tool attach: in-chat capability grants (Wave 167)

**Date:** 2026-05-17. **Status:** Shipped. **Closes** #550.

**Scope clarification.** Wave 167 dispatch brief said "Captain attaches a tool output (browser session screenshot, MCP resource) to a DM via attachment marker." Issue #550 body says "attach AD-706 BrowserTool / AD-449 MCP tools to a chat surface as scoped capability grants." These are different features. Built per the issue body (capability grants) because the screenshot-attach path already works today: BrowserTool writes screenshots to AttachmentStore via ``tools/browser/compute_use.py:174-176`` and they ride existing ``attachment_ids`` through chat. The real gap is in-chat capability granting -- letting the Captain say "give Echo BrowserTool read access for the next 2 hours" without leaving the chat surface. If the attachment-marker feature is wanted later, file a separate AD (AD-720c).

**Capability.** ``POST /api/chat/tool-grant`` accepts ``{agent_id, tool_id, permission, duration_hours?, reason?}``, calls ``ToolPermissionStore.issue_grant`` (AD-423a/b/c), and returns the grant record. ``issued_by="captain"`` always -- matches the existing ``/tool-access grant`` shell-slash-command pattern; the HXI runs in the Captain's process context. A grant issued via chat is indistinguishable on disk from one issued via shell.

**Defense-in-depth chain (in order).**
1. ``runtime.registry.get(agent_id)`` -- 404 if missing
2. ``ToolPermission(permission)`` -- 422 ``invalid_permission`` with full ``valid: [enum...]`` list
3. ``runtime.tool_registry.get(tool_id) is None`` -- 404 ``tool_not_found`` (when registry is present; passes through when absent)
4. ``runtime.tool_permission_store is None`` -- 503 ``tool_permission_store_unavailable``

**Pass-1 nit corrected.** The dispatch brief asserted ``tool_registry.has(req.tool_id)``. Real API on ``ToolRegistry`` is ``get(tool_id) -> ToolRegistration | None``. Implementation uses the real API. Source-scan test (``test_grant_source_scan_uses_tool_permission_module``) regression-protects the canonical ``from probos.tools.protocol import ToolPermission`` import.

**Event.** ``tool_grant_issued`` (string event-type, not a new EventType enum value) with ``{grant_id, agent_id, tool_id, permission, expires_at, issued_by, source: "chat"}``. ``source`` distinguishes chat-issued grants from shell-issued ones in the audit log. Audit emit failure honest-degrades (Tier-2): grant is still returned even if the event bus is down.

**Pydantic.** New ``ChatToolGrantRequest`` model with ``duration_hours`` bounded ``[0, 720]`` (30 days max) and ``reason`` capped at 500 chars -- enforced by Pydantic before the handler runs.

**HXI.** ``IntentSurface.tsx`` ``handleSubmit`` recognises ``/grant <agent_id> <tool_id> <permission> [hours]`` BEFORE the normal "send DM" path. Recognized format: leading ``/grant `` (note trailing space). On match, POSTs to ``/api/chat/tool-grant``; the slash command itself is NOT sent as a chat message. Successful response renders inline as a system-styled message: ``"Granted BrowserTool read to e1 (expires in 2h)"``. On 422/error: inline ``/grant rejected: <reason>`` system message AND the typed text is restored to the composer so the Captain can correct it. Usage validation (parts count, NaN/negative hours) handled client-side with structured ``/grant usage:`` error message.

**MCP namespace convention.** ``tool_id`` shape for MCP servers is ``mcp:<server_name>[:<resource_path>]``. ``ToolPermissionStore`` does NOT validate tool_id shape -- this is purely a convention captured here. Future MCP-specific UI affordances should follow it.

**v1 scope.** System-styled inline messages are client-side only -- NOT persisted to ward-room threads. Persistence is filed as forward marker AD-720b-2.

**Tests.** +11 pytest in ``tests/test_ad720b_chat_tool_grant.py``: happy path with expiry; happy path no duration -> null expiry; agent missing 404; invalid permission 422 with valid enum list; tool not in registry 404 ``tool_not_found``; tool_id passthrough when registry absent; store missing 503; ``duration_hours=1000`` -> 422 (Pydantic); ``reason`` >500 chars -> 422 (Pydantic); event-emit failure does not block grant (Tier-2 honest-degrade verified); source-scan asserts canonical ``from probos.tools.protocol import ToolPermission`` import.

+4 vitest in ``ui/src/__tests__/IntentSurface.toolGrant.test.tsx``: ``/grant e1 BrowserTool read 2`` POSTs ``duration_hours=2``; no-hours form POSTs ``duration_hours=null``; 422 preserves typed text in composer + renders system rejection message; success renders ``"Granted BrowserTool read to e1"`` system message in chatHistory.

Real ``ToolPermissionStore()`` in-memory + real ``AgentRegistry``-shape + real ``ToolRegistry``-shape stub per BF-287. No MagicMock at substrate boundaries; the in-memory ``ToolPermissionStore`` exercises the real ``issue_grant`` + cache path.

**Full gate.** 13900 -> 13911 pytest. Vitest 674 -> 678. UI bundle ``index-BTcSysUH.js`` -> ``index-DzUHsZVI.js``.

**Zero new deps.** Reuses ``ToolPermissionStore`` + ``ToolPermission`` enum + ``ToolRegistry`` (all shipped pre-Wave 167).

### AD-721i-2 - VRoid Studio CLI alternative backend evaluation (Wave 167, REJECTED)

**Date:** 2026-05-17. **Status:** REJECTED (research-only). **Closes** #543.

**Disposition.** VRoid Studio CLI is NOT a viable alternative renderer backend for the OSS code path. Three independent blocking constraints found:
1. **No headless mode.** VRoid Studio is GUI-only; no documented `--export` / `--import` / batch invocation in the official 1.x line.
2. **Proprietary EULA.** Distributed under a Pixiv-controlled EULA, not an OSI-recognized license. No source published.
3. **Linux-incompatible.** Windows + macOS only.

Any one of those would be sufficient to reject. Together they make VRoid a non-starter as the OSS-default. The existing AD-721i Blender + saturday06 backend remains v1.

**Operator-elected path preserved.** Captain or operators can still produce VRMs locally via VRoid Studio and install them via AD-721h upload UI or AD-721g `_baselines/` directory. Both paths consume operator-installed bytes and impose no license claim on the produced VRMs. The license metadata fields (`meta.licenseUrl`, `meta.allowedUser`, `meta.commercialUssageName`) must be populated by the operator before export -- VRoid's defaults are unset (a recurring source of downstream license ambiguity flagged in user-memory `License hygiene (2026-05-09)`).

**Deliverable.** Single new file `docs/research/vroid-cli-evaluation.md` with the verdict, summary table, citations, recommendation, and (declined) implementation outline.

**Forward markers.** None. Re-evaluation only triggers if Pixiv publishes a CLI or open-source release of VRoid Studio.

**Zero code, zero tests, zero deps.** Pure research housekeeping.

### AD-721i-2 - VRoid Studio CLI alternative backend evaluation (Wave 167, REJECTED)

**Date:** 2026-05-17. **Status:** REJECTED (research-only). **Closes** #543.

**Disposition.** VRoid Studio CLI is NOT a viable alternative renderer backend for the OSS code path. Three independent blocking constraints found: (1) no headless/CLI mode (GUI-only); (2) proprietary Pixiv EULA, not OSI-recognized, no source published; (3) Windows + macOS only (no Linux). Any one would be sufficient to reject; together they make VRoid a non-starter as OSS-default. The existing AD-721i Blender + saturday06 backend remains v1.

**Operator-elected path preserved.** Operators can produce VRMs locally via VRoid Studio and install them via AD-721h upload UI or AD-721g `_baselines/` directory. License metadata fields must be populated before export -- VRoid defaults are unset.

**Deliverable.** Single new file `docs/research/vroid-cli-evaluation.md` with verdict, summary table, citations, recommendation, and declined implementation outline.

**Forward markers.** None. Re-evaluation only triggers if Pixiv ships a CLI or open-source release.

**Zero code, zero tests, zero deps.** Pure research housekeeping.

### AD-705b - Offline TTS (Coqui / Piper) - SUPERSEDED (Wave 168)

**Date:** 2026-05-17. **Status:** SUPERSEDED -- closed without separate implementation. **Wave:** 168. **Closes** #556.

**Disposition.** The Wave 137 forward marker AD-705b ("replace browser SpeechSynthesis with an offline-capable engine such as Coqui or Piper, or expose multiple per-agent voice characters") is satisfied by three already-shipped ADs:

- **AD-738 (Wave 157)** -- Server-streamed TTS via Piper. Fully-offline MIT-licensed engine at `src/probos/audio/tts/piper_backend.py`. Browser `SpeechSynthesisUtterance` remains as Tier-2 fallback when `backend=browser`.
- **AD-718e (Wave 166)** -- Multi-language voice selection with 27-voice catalog (BF-291). Per-agent `voice_name` selection from server-resolved catalog.
- **AD-738e-1 (Wave 158)** -- Per-emotion Piper prosody overrides. AD-718d emotional modulation hook preserved end-to-end.

**Acceptance audit (per #556 body).**
- License posture clean: Piper is MIT -- operator-friendly, no copyleft propagation. Coqui evaluation deferred to AD-718b (Wave 168 research-only audit).
- Operator-install pattern for model files: shipped via `scripts/piper-voice-fetch.ps1` (Wave 165 / BF-291 download script).
- AD-718d emotional modulation: preserved through AD-738e-1 prosody overrides.
- Browser-TTS Tier-2 fallback: preserved in `ui/src/audio/voice.ts` (`backend=browser` default + probe-based escalation).

**No code change required.** Closed for tracking hygiene; the AD number is retired and will not be reused. Coqui/Bark/ElevenLabs evaluation continues under AD-718b (Wave 168).

### AD-718b - Extra TTS Backends Audit (Wave 168)

**Date:** 2026-05-17. **Status:** RESEARCH AUDIT -- code deferred. **Wave:** 168. **Closes** #523. **Parent:** AD-738 (Piper TTS, Wave 157).

**Audit deliverable.** `docs/research/tts-backends-evaluation.md` documents license posture, install footprint, voice quality, cross-platform support, and verdict for each of Coqui-TTS, Bark, ElevenLabs.

**Verdicts.**

- Coqui-TTS: **DEFER** to AD-718b-1. MPL-2.0 lib is acceptable but XTTS v2 weights are CPML (non-commercial) -- REJECTED for OSS auto-download. Per-voice MIT/Apache allowlist required. Heavy install (~1 GB torch + ~2 GB weights). Quality higher than Piper for multilingual; comparable for VITS English.
- Bark: **DEFER** to AD-718b-2. MIT lib + MIT weights (clean). ~4 GB model footprint + torch runtime overhead is the friction; quality comparable to Piper with stronger non-speech expressivity but 5-15s per-call latency and no streaming.
- ElevenLabs: **REJECT.** Paid commercial API conflicts with Captain rule 2026-05-09 ("never absorb anything in the OSS repo that requires a paid license"). OSS tree does not integrate. No forward marker filed.

**Extension point preserved.** `ui/src/audio/voice.ts:134` `backend: 'browser' | 'piper' | string` and `src/probos/audio/tts/backends.py` remain open for AD-718b-N implementations.

**No code shipped.** Zero new pip deps. Zero new npm deps. Zero new model downloads.

### AD-721f - Cognitive Canvas VRM avatar replacement (Wave 168)

**Date:** 2026-05-17. **Status:** Shipped (default-OFF transitional). **Wave:** 168. **Closes** #533. **Parent:** AD-721 avatar pipeline; AD-721g per-tier baselines (W167).

**Problem.** The Cognitive Canvas renders all agents as glowing instanced spheres (orb path via `THREE.InstancedMesh` in `ui/src/canvas/agents.tsx:33-34`). With the AD-721 avatar pipeline mature (designed avatars + per-tier baselines + browser upload), idle agents should be able to render as their actual VRM at canvas scale.

**Decision.** Add a per-agent VRM render path to `<AgentNodes>` gated by a default-OFF `CanvasVrmConfig` prop and three new `AvatarsConfig` fields:
- `canvas_render_vrm_avatars: bool = False` -- master toggle.
- `canvas_max_concurrent_vrms: int = 12` (0..64) -- concurrency cap.
- `canvas_vrm_lod_distance: float = 15.0` -- camera-distance LOD threshold.

When enabled, each frame the closest `maxConcurrent` agents within `lodDistance` (excluding load-failed agents) are mounted as `<AgentVRM>` siblings. Their orb instances are zero-scaled to hide them; remaining agents stay on the orb path unchanged. Per-VRM load errors silently fall back to the orb instance (`failedVrmAgentIds` set, no retry).

**Honest-degrade matrix.** Flag off -> orb path bit-for-bit equivalent. Resolver returns null -> orb. Load error -> orb (logged warning). Outside LOD distance -> orb. Concurrency cap hit -> closest-N as VRM, rest as orbs.

**Per-frame budget bounded by.** (1) Frustum-style LOD via camera-distance threshold, (2) explicit concurrency cap, (3) shared `GLTFLoader` + `VRMLoaderPlugin` pipeline from CrewVRM (no duplicate code path), (4) frame-throttled cull (every 15 frames ~250 ms at 60 fps) instead of per-frame React state churn.

**Forward markers.**
- **AD-721f-1** -- per-frame `useFrame` budget instrumentation. vitest under jsdom has no WebGL renderer, so a synthetic cost measurement of the cumulative `useFrame` cost across N=12 mounted `AgentVRM` instances is not stable. Test 5 ships as `test.skip` with this forward marker; revisit when a stable instrumentation pattern lands.

**Files.** `src/probos/config.py` (3 new `AvatarsConfig` fields + descriptions). `ui/src/canvas/agentVRM.tsx` (new component + pure `_pickCloseAgents` helper). `ui/src/canvas/agents.tsx` (config plumbing + frame-throttled cull + zero-scale orb hide + VRM siblings). `ui/src/canvas/__tests__/agentVRM.test.tsx` (8 passing + 1 skipped for AD-721f-1).

**What this does NOT change.** `CrewVRM.tsx` / `CrewAvatarPopout.tsx` untouched. AD-721d preview/propose/approve endpoints untouched. Orb-path raycaster behavior preserved (zero-scaled instances do not intercept rays). No new pip or npm deps.

### AD-721a - Captains avatar editor UI (Wave 168)

**Date:** 2026-05-17. **Status:** Shipped. **Wave:** 168. **Closes** #528. **Parent:** AD-721d-3 preview endpoint (W167); AD-721d propose path (existing).

**Problem.** The Captain can already view an agent VRM (CrewAvatarPopout), trigger LLM-driven `propose_appearance` via AD-721d/-1, and preview a proposed DSL via AD-721d-3. What was missing: direct Captain-driven inline DSL edits (color palette, body, hair, outfit, expression) without going through Counselor revision iterations.

**Decision.** Add a new `CrewAvatarEditor` component mounted inline from `CrewAvatarPopout` via a title-bar `edit` toggle. The editor renders the current `AvatarDSL` as form controls (selects, color pickers, range sliders) and routes edits through the existing AD-721d-3 preview endpoint. On Approve, persists via the existing PUT `/api/agent/{id}/appearance`. No new server endpoints.

**Key design constraints honored.**
- **No new GET endpoint.** The current DSL is prop-passed from `CrewAvatarPopout` as `appearance.dsl`. The editor receives it via `currentDsl: AvatarDSLDict | null` (defaults to `_defaultDsl()` when null). Grep confirmed the appearance router has only POST/PUT/DELETE methods.
- **AD-721d-1 iteration counter untouched.** Captain edits use the `/preview` path only -- they do NOT call `/propose`. Test `does NOT call /appearance/propose` is the regression guard.
- **AD-731 invariant preserved.** Preview returns a SHA-256 ref (`attachment_id`); the editor sets the popout VRM viewer to `/api/chat/attachments/{sha}`. No inline VRM bytes anywhere in the editor message path.
- **Honest-degrade.** 503 -> `preview-banner data-status=unavailable`, Approve remains enabled. 422 -> `field-error-*` inline per offending field. Other 4xx/5xx -> generic error banner.
- **Dual-edit collision prevention.** The title-bar `edit` toggle is disabled while `proposedDsl` is present (Counselor flow has an iteration in flight).
- **Debounced preview.** 500 ms debounce + token-based cancellation; rapid edits collapse into a single preview fetch.

**Files.**
- `ui/src/components/profile/CrewAvatarEditor.tsx` (new -- form controls + debounced preview + approve/cancel).
- `ui/src/components/profile/CrewAvatarPopout.tsx` (title-bar `edit` button + editor mount + `editorPreviewUrl` state that takes precedence over `previewVrmUrl` in `activeVrmUrl`).
- `ui/src/components/profile/__tests__/CrewAvatarEditor.test.tsx` (9 vitest -- mount, default DSL, debounced preview, 503 banner, 422 field errors, approve PUT body, cancel, hex<->hsl roundtrip, propose-path-not-called regression).
- `ui/src/components/profile/__tests__/CrewAvatarPopout.editor.test.tsx` (3 vitest -- edit toggle mounts editor, toggle disabled while propose pending, cancel returns to non-edit state).

**Tests.** +12 vitest (9 editor + 3 popout integration), all passing.

**What this does NOT change.** No new server endpoints. `propose_appearance` LLM path untouched. AD-721d-1 iteration counter untouched. `AvatarDSL` Pydantic schema untouched. `CrewVRM.tsx` untouched. Zero new pip or npm deps.

### AD-721e - Skeletal animation library (Wave 168)

**Date:** 2026-05-17. **Status:** Shipped (default-OFF transitional). **Wave:** 168. **Closes** #532. **Parent:** AD-721 avatar pipeline; AD-721i-1 license whitelist (W166).

**Problem.** CrewVRM had only relaxed A-pose + procedural breathing/sway + lip-sync. Issue #532 asked for AnimationClip-based skeletal motion (idle / talking / listening / thinking). Mixamo was suggested but REJECTED per AD-721i-1 license whitelist.

**Decision.** Three-layer change:
1. **Source CC0/MIT clips.** Quaternius "Ultimate Animated Character Pack" (CC0) is the v1 default; KayKit (CC0) is the documented backup. Mixamo bytes are NEVER shipped or auto-fetched. License whitelist guard in `scripts/animations-fetch.ps1` rejects any non-whitelisted entry. License disposition lives at `docs/research/skeletal-animations-license.md`.
2. **AnimationManifest + endpoints.** New `AnimationManifest` class in `src/probos/avatars/asset_manifest.py` with SHA-256 integrity check on registration (when file present) and license whitelist enforcement at register-time. Two new endpoints in `src/probos/routers/avatars.py`: `GET /api/avatars/animations` lists registered clips (honest-degrades to `{"clips": []}` when disabled or empty); `GET /api/avatars/animations/{name}` serves the .glb bytes with `Cache-Control: public, max-age=3600, immutable`.
3. **CrewVRM AnimationMixer integration.** New optional `bodyState?: 'idle' | 'talking' | 'listening' | 'thinking'` prop. After VRM mount, fetch the manifest, load each clip via `GLTFLoader`, apply `retargetMixamoToVRM` (mixamorig:* -> VRM Humanoid bone names), cache by name. On `bodyState` change, cross-fade between actions over ~300 ms. When no clip is registered for the requested state, the procedural breathing/sway loop owns the bones (honest-degrade). Mixer ticks in the existing `useFrame`; procedural loop is gated by `currentActionRef.current === null` to prevent double-writing bones.

**Bone retargeting (the silent-fail trap).** Mixamo-rigged clips use `mixamorig:Hips`, `mixamorig:LeftArm`, etc. `THREE.AnimationMixer` matches `KeyframeTrack.name` to scene node names; an unmodified Mixamo clip played against a VRM scene SILENTLY fails to bind (mixer ticks but no bones move, no console warning). The runtime helper `ui/src/canvas/animation/retarget.ts:retargetMixamoToVRM(clip)` rewrites each track name from `mixamorig:<X>.<channel>` to `<vrmName>.<channel>` before `mixer.clipAction(clip).play()`. Tracks for bones not in the 22-entry VRM Humanoid required set (finger / facial bones) are dropped silently with a debug log. Source bytes stay verbatim on disk.

**Configuration.** Two new `AvatarsConfig` fields: `animations_dir` (default `data/avatars/animations`) and `animations_enabled` (default `False`).

**Honest-degrade matrix.**
- `animations_enabled=False` -> endpoint returns `{"clips": []}` -> CrewVRM never mounts the mixer effect -> procedural loop runs (unchanged behavior).
- Manifest missing on disk -> same as above.
- Manifest present but no files extracted -> empty `list_available()` -> empty clips list -> procedural.
- File present but SHA tampered -> `register()` raises `ValueError`, endpoint logs and skips -> clip excluded from response.
- Clip present but `bodyState` requests an unmapped state -> previous action fades out, procedural loop resumes.

**Lip-sync precedence preserved.** Viseme morph targets write to `morphTargetInfluences`; body animation writes to bone transforms. No conflict. Lip-sync continues regardless of active body clip.

**Files.**
- `src/probos/avatars/asset_manifest.py` (new `AnimationManifest`, `AnimationClipEntry`).
- `src/probos/routers/avatars.py` (2 new endpoints + `_build_animation_manifest` helper).
- `src/probos/config.py` (2 new `AvatarsConfig` fields).
- `ui/src/canvas/animation/retarget.ts` (new -- `MIXAMO_TO_VRM` + `retargetMixamoToVRM`).
- `ui/src/components/profile/CrewVRM.tsx` (new `bodyState` prop + mixer state + manifest-load effect + cross-fade effect + mixer tick + procedural-loop gate).
- `scripts/animations-fetch.ps1` (new -- operator fetch helper with whitelist guard).
- `.gitignore` (new entry: `data/avatars/animations/`).
- `docs/research/skeletal-animations-license.md` (new -- license disposition).
- `tests/test_ad721e_animation_manifest.py` (10 pytest -- manifest unit + endpoint integration).
- `ui/src/canvas/animation/__tests__/retarget.test.ts` (6 vitest -- track rewrite + drop + passthrough + immutability).

**Tests.** +10 pytest passing + 6 vitest passing. Total Wave 168 cluster 1 vitest delta: +26 (8 AD-721f + 12 AD-721a + 6 AD-721e).

**Forward markers.**
- **AD-721e-1** -- gesture / nod / shrug / typing animation packs. Trigger: Captain demand for more granular body language beyond the 4-state v1.

**What this does NOT change.** Lip-sync wiring (AD-721 + AD-738e-1) untouched -- bone animation is orthogonal to morphTargetInfluences. A-pose fallback at load preserved. Procedural breathing/sway preserved (gated to clip-inactive frames). VRM file format unchanged. No new pip or npm deps. No animation bytes committed to the repo.

### AD-720c - Cloud file picker (OAuth-bound source, Google Drive v1) (Wave 168)

**Date:** 2026-05-17. **Status:** Shipped (default-OFF master switch). **Wave:** 168. **Closes** #551. **Parents:** AD-720a multipart (W139), AD-706f credential vault (W166), AD-731 AttachmentStore invariant (W151+).

**Problem.** The Captain could attach files to chat from paste (AD-720) and multipart upload (AD-720a) but not from cloud-hosted storage (Google Drive / OneDrive / Dropbox). Issue #551 asks for an OAuth-bound third source. OSS-scope ruling: protocol + extension-point only, plus ONE working provider; the other two are stubs with forward markers.

**Decision.** Five layers:
1. **OAuth provider Protocol** (`src/probos/cloud_pickers/provider.py`) with `start_authorization`, `handle_callback`, `list_files`, `download_file`. Three concrete providers — `GoogleDriveProvider` (v1 working), `OneDriveProvider` / `DropboxProvider` (stubs that raise `NotImplementedError` with the AD-720c-1 / AD-720c-2 forward-marker text). All HTTP via `httpx.AsyncClient` (no new pip deps; Wave-162 resident).
2. **`OAuthTokenBundle`** Pydantic model (`src/probos/cloud_pickers/tokens.py`) carries `access_token`, optional `refresh_token`, `expires_at`. Persisted via `bundle.model_dump_json()` into AD-706f `CredentialVault` under ref `cloud_provider:{provider_id}:{captain_id}` with `CredentialScope()` empty-frozenset = captain-only per `credentials.py:40-58`. **No new credential store** — AD-706f is reused verbatim.
3. **CSRF state guard** (`CsrfStateStore` in tokens.py): in-memory, 32-byte url-safe token via stdlib `secrets`, single-consume (replay-protected), default 5-min TTL (`CloudPickersConfig.state_ttl_seconds`, ge=30).
4. **Refresh-on-401.** `GoogleDriveProvider._with_refresh_retry` runs the request; on 401, attempts a single `grant_type=refresh_token` exchange. Preserves the original `refresh_token` if the response omits one (Google rotates rarely). Retries the original request EXACTLY once. Surfaces `ReauthorizationRequired` (→ 401 `reauthorization_required` + vault entry deleted) on refresh failure OR second 401 (avoid loops). Google consent URL includes `access_type=offline&prompt=consent` so the refresh_token is issued on every authorization (Google omits it on subsequent authorizations without `prompt=consent`).
5. **REST router + UI.** `src/probos/routers/cloud_pickers.py` exposes 4 endpoints under `/api/cloud-pickers/{provider}` (POST start, GET callback, GET files, POST attach). `ui/src/components/CloudPicker.tsx` modal — provider selector, authorize popup + `oauth_complete` postMessage listener, paginated file list, file click → POST `/attach` → `onAttached({attachment_id, mime, size_bytes, filename})`. HXI Design Principle #3 honored (inline stroke SVG icons, no emoji).

**PKCE skipped (intentional).** ProbOS is a confidential client with server-stored `client_secret` per `CloudPickerProviderConfig`. Per OAuth 2.1 §1.5, PKCE is REQUIRED for public clients and OPTIONAL for confidential clients holding a `client_secret`. State-token CSRF guard + client_secret is the chosen defense. If a future provider requires a public-client app type with no client_secret, PKCE becomes a forward marker.

**AD-731 invariant preserved.** The `/attach` endpoint feeds downloaded bytes through the shared `_validate_and_store_attachment` (AD-720a, `routers/chat.py`) → `AttachmentStore.write(sha, blob, mime)` chain (the same defense-in-depth path used by the existing paste + multipart endpoints). The HTTP response carries only `{attachment_id, mime, size_bytes, filename}` — bytes never cross the browser boundary.

**Honest-degrade matrix.**
- `cloud_pickers.enabled=False` → 503 `feature_disabled`.
- `runtime.credential_vault is None` → 503 `credential_vault_unavailable`.
- Provider not in `_PROVIDER_CLASSES` → 404 `unknown_provider`.
- Provider disabled OR missing client_id/secret → 503 `provider_disabled` / `provider_not_configured`.
- Invalid / expired CSRF state → 403 `invalid_state_token`.
- No bundle in vault → 401 `oauth_not_authorized`.
- 401 from provider + no refresh_token OR refresh fails → 401 `reauthorization_required` + vault entry deleted.
- Download > `max_file_size_bytes` (default 50 MB) → 413 `file_too_large`.

**Files.**
- `src/probos/cloud_pickers/__init__.py` (new package).
- `src/probos/cloud_pickers/tokens.py` (new `OAuthTokenBundle` + `CsrfStateStore`).
- `src/probos/cloud_pickers/provider.py` (new `CloudPickerProvider` Protocol + `ProviderError` + `ReauthorizationRequired` + `ProviderFile`).
- `src/probos/cloud_pickers/google_drive.py` (new `GoogleDriveProvider` v1; refresh-on-401 helper).
- `src/probos/cloud_pickers/onedrive.py` (new `OneDriveProvider` stub — AD-720c-1 forward marker).
- `src/probos/cloud_pickers/dropbox.py` (new `DropboxProvider` stub — AD-720c-2 forward marker).
- `src/probos/routers/cloud_pickers.py` (new — 4 endpoints).
- `src/probos/api.py` (router registration).
- `src/probos/config.py` (new `CloudPickerProviderConfig` + `CloudPickersConfig`; `ProbOSConfig.cloud_pickers` default-OFF field).
- `ui/src/components/CloudPicker.tsx` (new modal).
- `tests/test_ad720c_provider_protocol.py` (3 pytest).
- `tests/test_ad720c_google_drive.py` (7 pytest, `httpx.MockTransport` via `http_client_factory` injection).
- `tests/test_ad720c_state_store.py` (4 pytest — TTL + single-consume + provider-mismatch + purge).
- `tests/test_ad720c_endpoints.py` (8 pytest — real `SystemConfig()` + real `EncryptedFileCredentialVault` per BF-287; full honest-degrade matrix; CSRF rejection; bundle persistence roundtrip; AD-731 SHA-ref-not-bytes assertion).
- `ui/src/components/__tests__/CloudPicker.test.tsx` (7 vitest).

**Tests.** +22 pytest passing + 7 vitest passing. Full gate: 13923 → 13951 (+22 from this AD; the other +6 came in with Wave 168 cluster-1 commits at origin/main).

**Zero new deps.** `httpx` already resident from Wave 162. `cryptography` already resident from Wave 166 (AD-706f). OAuth state uses stdlib `secrets` + `urllib.parse`. No pyproject / lockfile / ui package changes.

**Forward markers.**
- **AD-720c-1** — OneDrive provider implementation. Trigger: operator demand once Google Drive v1 has been exercised end-to-end in production for at least one wave.
- **AD-720c-2** — Dropbox provider implementation. Same trigger as AD-720c-1.

**What this does NOT change.** `_validate_and_store_attachment` (AD-720a) reused verbatim. AD-706f `CredentialVault` Protocol surface untouched. `httpx` + `cryptography` versions unchanged. Browser chat compose `attachment_ids: string[]` shape extended, not redesigned. Existing paste / multipart upload paths untouched. No new pip / npm deps.

### AD-740 - Affect-vs-intent drift trend (Wave 169)

**Closes #664.** Ezri requested trend depth on top of the AD-728c `check_own_render` snapshot: "a short trend would add depth." AD-740 ships a pure read-only summariser over the existing AD-722a-5 `runtime.divergence_history` ring buffer. No new data capture, no LLM call, no event emission.

**API.** `get_affect_drift(runtime, agent_id, *, window=None, threshold=None) -> dict`. Returns either `{"insufficient_data": True, "samples": int}` OR `{"window", "samples", "mean_match_score", "below_threshold_count", "longest_divergent_streak", "threshold"}`. Honest-degrades when the ring buffer is absent or has fewer than 2 entries.

**Files.**
- `src/probos/avatars/affect_drift.py` (new, ~95 lines).
- `src/probos/config.py` (`AvatarsConfig.affect_drift_default_window=8` + `affect_drift_threshold=0.7`).
- `src/probos/cognitive/cognitive_agent.py` (`check_own_render` folds drift summary into `_working_memory.record_observation` after the snapshot record).
- `tests/test_ad740_affect_drift.py` (+8 pytest using real `SystemConfig()` + hand-rolled `_FakeRuntime`/`_FakeEntry` per BF-287).

**Invariants preserved.** AD-731 (no inline blobs - drift summary is a pure dict of scalars); AD-727 rule #8 (observation phrasing describes the OUTPUT, never the agent); AD-722a-5 buffer lifecycle unchanged; AD-728c cost discipline preserved (no new LLM call, no new event emission); BF-287 (real config, no MagicMock at substrate boundary).

**Tests.** +8 pytest. Full gate: 13952 -> 13960.

**Zero new deps.** stdlib `collections.deque` + `logging` only.

**Forward markers.**
- **AD-740-1** - Auto-correction of drift. Trigger: when >=3 ProbOS deployments accumulate >=7-day drift telemetry showing a stable causal relationship between sustained drift (longest_streak >= 4) and Captain corrections.
- **AD-740-2** - Cross-agent drift comparison surface (counselor-mediated). Trigger: Counselor agent surfaces >=1 production complaint that single-agent drift alone is insufficient for clinical pattern detection.
- **AD-740-3** - Persistence beyond in-memory ring (dedicated SQLite sidecar). Trigger: operator request to survive process restart for longitudinal drift study.

### AD-730-3 - Agent image generation in DM replies (Wave 169)

**Closes #633.** Agents can now emit images in their DM replies via the `[GEN_IMAGE prompt]` bracket marker. Image generation is a sixth peer LLM tier (`image_gen`) alongside fast/standard/deep/vision/compute_use, using the OpenAI-compatible Images API v1 wire shape (`POST /v1/images/generations` returning `data[].b64_json`). Default-OFF master switch; opt-in via `AvatarsConfig.image_gen_enabled` AND `CognitiveConfig.llm_base_url_image_gen` + `llm_model_image_gen`.

**Bracket marker.** `[GEN_IMAGE <prompt>]` where `<prompt>` is up to `AvatarsConfig.image_gen_max_prompt_chars` chars (default 512). One marker per reply honored; additional markers stripped with WARNING. Identical contract to AD-728d's `[SELF_CHECK reason]`.

**Eight-guard catalog audit** (per AD-732 / user-memory 2026-05-12 lesson). Every tier-enumerating surface explicitly handles `image_gen`:

| # | Surface | Handling |
|---|---------|----------|
| 1 | `_LLM_TIERS` in `cognitive/llm_client.py` | Added as sixth peer. |
| 2 | `_TIER_ORDER` (fallback chain) | Excluded - text tiers can't generate images (BF-269). |
| 3 | `CognitiveConfig.tier_config()` 8 internal maps | All extended with `image_gen` entries. |
| 4 | `is_vision_tier_configured` | New sibling `is_image_gen_tier_configured` mirrors the pattern. |
| 5 | ModelRouter `by_tier()` | Explicit bypass at dispatch_image_gen call site (BF-273). |
| 6 | LLMResponseCache | Explicit bypass - no caching of image bytes (BF-272). |
| 7 | Health probe / tier_configs / consecutive_failures | Added at `_LLM_TIERS` builder + test scaffolding updated per BF-286. |
| 8 | Fallback recovery chain | Excluded - failures return honest-degrade dict, never fall to text. |

**Files.**
- `src/probos/cognitive/image_gen_dispatch.py` (new ~240 lines: `dispatch_image_gen`, `is_image_gen_tier_configured`, `_maybe_emit_wellness_review`, `_maybe_write_anchored_episode`, four honest-degrade message constants).
- `src/probos/cognitive/llm_client.py` (`_LLM_TIERS` extended to include `image_gen`; comment updated for the BF-269 exclusion).
- `src/probos/cognitive/dm_sanity_gate.py` (new `_GEN_IMAGE_RE` + `_GEN_IMAGE_STRIP_RE` regex constants; new `extract_gen_image` + `strip_gen_image` methods).
- `src/probos/cognitive/dm/reply_pipeline.py` (`DmReplyContext.generated_attachment_ids: list[str]` field via `field(default_factory=list)`; new `step_4c_image_gen_parse` between step_4 and step_4b; step tuple in `run()` extended; `build_response` surfaces `attachment_ids` only when non-empty).
- `src/probos/config.py` (`CognitiveConfig` `llm_*_image_gen` 5-field block + all 8 `tier_config` maps extended; `AvatarsConfig` 5-field block: `image_gen_enabled=False` master switch + `image_gen_max_prompt_chars=512` + `image_gen_wellness_review_required=True` + `image_gen_max_image_bytes=4MB` + `image_gen_mime="image/png"`).
- `tests/test_ad730_3_agent_image_gen.py` (+20 pytest: real `SystemConfig()` + `_FakeAttachmentStore` + `_FakeRuntime` + `httpx.MockTransport` per BF-287; covers dispatch happy path + 6 honest-degrade paths + wellness review dedupe + extract/strip + pipeline integration + 4 eight-guard regressions).
- `tests/test_per_tier_llm.py`, `tests/test_ad732_vision_tier.py`, `tests/test_ad706c2_compute_use.py`, `tests/test_bf069_llm_health.py` (tier-set assertions and `_make_client` scaffolding extended to include `image_gen` per BF-286).

**Invariants preserved.** AD-731 (refs not blobs: every byte path flows through `AttachmentStore.write(sha, blob, mime)`; `dm/reply_pipeline.py` contains no `b64encode` / `b64_json`; source-scan test enforces); AD-732/8-guard (full table above); AD-727 (first `image_gen` invocation per agent per process emits a single WARNING log line tagged `WELLNESS REVIEW`); AD-728d (new step `step_4c_image_gen_parse` uses letter suffix - trailing 5 steps NOT renumbered); AD-541b (successful image gen writes `importance=8` `anchored=True` episode via `episodic_memory.store_episode` when present); BF-269/BF-272/BF-273 (no fallback, no cache, no ModelRouter participation); BF-286/287 (real config + real fixtures in tests, no MagicMock at substrate boundary).

**Counselor wellness review (v1).** Logger WARNING line on first `image_gen` invocation per agent per process. Process-scoped (`_WELLNESS_REVIEW_SEEN` module-level set), intentionally NOT persisted - restart resets. Interactive Captain ACK is AD-730-3-1 territory.

**Vendor choice.** OpenAI Images API v1 wire shape is the de-facto OpenAI-compatible standard - DALL-E 3, gpt-image-1, openrouter, litellm, AUTOMATIC1111/ComfyUI/SD.next OpenAI-shape adapters all speak it. Operators wanting other vendors layer a translator or use openrouter as base_url.

**Tests.** +20 pytest in the new file (14 core + 4 eight-guard + 2 extract/strip). Full gate: 13960 -> 13973 (+13 net visible after subtracting the documented xdist flake set; serial -n 0 run of the new file alone reports 20 passed).

**Zero new deps.** `httpx` already resident (Wave 162). `base64` / `hashlib` / `logging` / `re` / `asyncio` stdlib. No pyproject / lockfile / ui package changes. Zero-line license diff.

**Forward markers.**
- **AD-730-3-1** - Per-conversation + per-day cost gating budget (config flag + counter + Captain ACK on overrun). Trigger: operator reports >/day image-gen cost OR >=3 agents reach >=10 generations/day without Captain approval.
- **AD-730-3-2** - Image moderation classifier (NSFW / safety / policy). Trigger: image_gen exercised in production for >=30 days AND a single moderation incident is documented in a deployment.
- **AD-730-3-3** - Provenance watermarking + C2PA-shape metadata embedding. Trigger: operator deployment publishes generated images to a third-party channel.
- **AD-730-3-4** - HXI rendering of agent-generated `attachment_ids` on the DM reply surface. Trigger: this AD merges AND Captain reports inability to see generated images in the HXI. (V1 confirmed: HXI currently sends `attachment_ids` outbound only via IntentSurface.tsx; no inbound render path exists.)
- **AD-730-3-5** - Ward Room wiring of `[GEN_IMAGE ...]` bracket marker in the WR reply pipeline. Trigger: documented WR use-case requiring agent-generated images.


### AD-741 — Settings / Control Panel HXI shell (Wave 170)

**Status.** Shipped Wave 170. New AD (no GitHub issue — net-new feature).

**Motivation.** ProbOS had no operator-facing surface to read or modify `system.yaml` at runtime. Every configuration change required editing the file by hand and restarting. The Captain mockup (Claude Artifact, 2026-05-17) sketched a multi-domain control panel with draft buffer + explicit APPLY ↵; the original 28-entry, 6-domain sidebar was an aspirational sketch — SystemConfig has 180+ Pydantic classes but only ~10 expose operator-actionable knobs that make sense in a control panel.

**Scope.** v1 ships the API surface, the section registry, the overlay HXI panel, and the secret-field rule. Hot-reload is uniformly restart-required.

**API.**
- `GET /api/config` → live `SystemConfig.model_dump(mode="json")` (secrets redacted to None) + section registry + `secret_present` map + uptime + single-consume CSRF token (5-min TTL).
- `GET /api/config/yaml` → current YAML text with secret values scrubbed to literal `"<redacted>"`.
- `POST /api/config` → validates a sparse patch via `SystemConfig(**merged)`, writes atomically to `runtime.config_path`, returns `restart_required=True` + `changed_fields` dot-paths. Rejects 400 `secret_field_readonly` when patch touches a secret-flagged path; 422 on Pydantic validation failure; 503 `config_path_unavailable` when runtime was constructed in-memory; 403 on missing/expired CSRF.

**Section registry.** `src/probos/settings/section_registry.py` is the single source of truth — 10 wired sections from AD-741 + 1 (`perception`) inserted by AD-733. Domains render in canonical order: Core → Perception & Voice → Identity & Presentation → Connectivity. Every `field_id` resolves to a real Pydantic attribute path under `SystemConfig` (guarded by `test_every_field_id_resolves_against_system_config` — the standing-rule wall against phantom fields).

**Secret-field rule.** Terminal-segment regex `(?i)(secret|token|password|api_key|private_key)`. Enforced at three layers (defense in depth): GET redaction with `secret_present` map, YAML scrub to `<redacted>`, POST rejection with 400 `secret_field_readonly`. Single helper `is_secret_field_id(field_id)` exported from the registry; used by both API + UI.

**Pre-flight grep corrections.** Builder pre-flight against HEAD caught two phantom-field classes in the original prompt:
- Per-tier LLM fields live on `cognitive.*`, not `system.*` (e.g. `cognitive.llm_base_url_vision`, not `system.llm_base_url_vision`). All 15 LLM-tier field ids corrected.
- Channels `webhook_url` / `url` fields do NOT exist on `DiscordConfig` / `SlackConfig` / `WebhookConfig`. Dropped from v1; wired the real fields instead: `channels.discord.command_prefix` / `mention_required` / `token` (secret); `channels.slack.default_thread_ts` / `bot_token` (secret) / `signing_secret` (secret); `channels.webhook.shared_secret` (secret).

**Runtime change.** Added `ProbOSRuntime.config_path: str | None = None`; set during `_load_config_with_fallback` in `__main__.py`. v1 does NOT mutate `runtime.config` in-process — every field is restart-required. Forward marker AD-741-1 wires per-field hot reload later.

**CSRF.** Endpoint-scoped single-consume token. No app-wide middleware (no Project-wide CSRF middleware exists today; AD-720c-style pattern). Forward marker AD-741-5 covers multi-Captain auth + audit log.

**YAML round-trip.** Pydantic `model_dump` loses comments + key ordering. v1 accepts this loss and stamps a `# Edited via HXI YYYY-MM-DD HH:MM:SS UTC` header on write. Operators editing YAML by hand keep their comments only until the first HXI-driven APPLY. UI's VIEW YAML modal footer documents this.

**HXI Design Principle compliance.** Every glyph is inline stroke SVG (`strokeWidth: 1.5`, `strokeLinecap: round`); amber `#f0b060` active / dim `#666680` inactive (HXI #3, no emoji). Engineering-orange `#e08040` reserved for unsynced / failed-APPLY states (HXI #9 alert-driven layout). Settings is a workstation tier (operator action), accessed from TopNav; the Crew Roster handles per-agent settings via the existing AgentProfilePanel (HXI #11).

**Files.**
- `src/probos/settings/__init__.py` (module doc).
- `src/probos/settings/section_registry.py` (new, ~330 lines): `FieldDescriptor`, `SectionDescriptor`, `SECTIONS` tuple, `is_secret_field_id`, `get_section`, `domain_counts`, `domain_render_order`, `resolve_dot_path`, `insert_section`.
- `src/probos/routers/config.py` (new): GET/GET-yaml/POST endpoints + CSRF + secret-redaction helpers + atomic YAML write.
- `src/probos/runtime.py` (3-line addition: `config_path` attribute).
- `src/probos/__main__.py` (1-line addition: set `runtime.config_path` after construction).
- `src/probos/api.py` (router registration).
- `ui/src/store/useSettingsStore.ts` (new, ~190 lines): Zustand slice, kept separate from the giant `useStore.ts` to minimize blast radius.
- `ui/src/components/settings/SettingsPanel.tsx` (root overlay; mirrors WardRoomPanel shape).
- `ui/src/components/settings/SettingsSidebar.tsx` (grouped sidebar + search + Advanced affordance).
- `ui/src/components/settings/SettingsMain.tsx` (per-field controls).
- `ui/src/components/settings/SettingsTopBar.tsx` (TopBar + StatusBar + YamlModal).
- `ui/src/components/settings/icons.tsx` (stroke-SVG glyph mapping per HXI #3).
- `ui/src/App.tsx` (NavButton + overlay mount).

**Invariants preserved.** AD-731 invariant n/a (no bytes flow through `IntentMessage.params`; config bytes flow YAML → disk). BF-287 enforced: tests use real `SystemConfig()` + real `tmp_path` YAML + only the runtime shell is MagicMock; new `test_no_magicmock_at_substrate_boundary` sentinel asserts `MagicMock` does NOT appear in `src/probos/routers/config.py` or `src/probos/settings/section_registry.py`. BF-274 honoured (no `multi_replace_string_in_file` with adjacent blocks on the new files). BF-280 n/a (no subprocess). BF-282 n/a (no binary output).

**Tests.** +19 pytest in `tests/test_ad741_config_api.py` (9), `tests/test_ad741_section_registry.py` (4), `tests/test_ad741_secret_redaction.py` (4), `tests/test_ad741_integration.py` (2). +10 vitest in `ui/src/components/settings/__tests__/SettingsPanel.test.tsx` (7) + `SettingsSidebar.test.tsx` (3). Full gate: 13980 → 13999. Vitest gate: 711 → 721. UI build green (`dist/assets/index-Cq1Q7Rbf.js`).

**Zero new deps.** `pyyaml` already resident. No pyproject / lockfile / ui package changes. Zero-line license diff.

**Forward markers.**
- **AD-741-1** — Per-field hot-reload paths (no restart) for safe fields (e.g. `system.log_level` via `logging.getLogger().setLevel`). **Trigger:** Captain reports "I changed log level but it didn't take effect without restart."
- **AD-741-2** — Structured editors for collection-shaped fields (`mcp.servers`, `federation.peers`, etc.). **Trigger:** Captain asks "how do I add an MCP server from the panel?"
- **AD-741-3** — YAML diff preview before APPLY. **Trigger:** Captain rejects an APPLY because they couldn't see exactly what would change.
- **AD-741-4** — Restart-in-place modal: "saved + restarting now" flow. **Trigger:** Captain hits APPLY 3+ times and forgets to restart manually.
- **AD-741-5** — Multi-Captain auth + audit log of who-changed-what. **Trigger:** more than one operator with `crew_scope_token` in production.
- **AD-741-6** — Raw YAML editor mode: editable textarea + Pydantic validate-on-save (POST `/api/config/yaml`). **Trigger:** Captain needs to edit a field the registry doesn't surface.
- **AD-741-7** — Per-agent settings deep-link from Settings → Crew Roster → Agent Profile via `location.hash`. **Trigger:** Captain asks "how do I get to Counselor's settings from here?"

### AD-733 — Camera streaming v1 — frame ingestion + Perception section (Wave 170)

**Status.** Shipped Wave 170. Closes #641 umbrella; sub-markers AD-733a / AD-733b filed as new GitHub issues #665 / #666, AD-733-1 / AD-733-2 filed as #667 / #668.

**Motivation.** The agent fleet has had a vision tier since AD-732 (Wave 153) but no visual sensor stream — image DMs were paste-only (AD-720 Wave 138). Issue #641 calls for a continuous webcam frame pipeline so future ObserverAgents (AD-733b) can react to the Captain's physical environment. The pipeline must be safety-first (instant kill switch, explicit "camera live" indicator, default-OFF at two layers) and must NOT inline blobs into IntentMessages (AD-731 invariant).

**Scope.** v1 ships the wire shape: frame ingestion, AD-731-compliant content-addressable storage, `vision_observation` intent broadcast, AD-541b anchored episode on first frame, and the Settings Perception section. v1 does NOT add an LLM consumer for `vision_observation` (intentional — AD-733a forward marker covers the 1-Hz tick batcher + ObserverAgent).

**Architecture.**
- `PerceptionConfig` + nested `CameraStreamConfig` on `SystemConfig`. Default-OFF on both `perception.enabled` AND `perception.camera.enabled` (two-switch privacy posture).
- `VISION_OBSERVATION_DESCRIPTOR` registered in `src/probos/perception/__init__.py`: non-destructive (`requires_consensus=False`), tier `"domain"`. The decomposer prompt now knows about the intent name. v1 has no claimed handler; unconsumed broadcasts are silently dropped (the dynamic intent discovery design supports this — see `runtime.intent_bus.broadcast` semantics).
- `POST /api/perception/camera/frame` multipart endpoint behind `require_crew_scope`. Defense in depth: feature gate (503), camera gate (503), per-session token-bucket rate limit (429 + `Retry-After: 1`), size cap (413), minimum-size gate (400 — JPEG magic enforced via the shared AD-720 `_validate_and_store_attachment` chain). Bytes flow through `AttachmentStore.write(sha, blob, "image/jpeg")`; the response carries only `{ok, attachment_ref, captured_at}` — never bytes.
- `IntentMessage.params` carries ONLY `{attachment_ref, mime, captured_at, source, session_id}`. Source-scan test `test_router_source_has_no_inline_blob_patterns` asserts that `b64encode` / `base64.b64` / `b64decode` / `blob_b64` literals do NOT appear in `routers/perception.py` — the AD-731 invariant is rigorously enforced at the source level.
- AD-541b anchored episode written on the first frame per session per runtime boot. Importance 8; `AnchorFrame(channel="perception", trigger_type="camera_stream_began", trigger_agent="captain")`. Defends future agents from confabulating "I saw something before the camera was on." Tier-2 honest-degrade — if episodic store is unavailable, log WARNING and continue; the frame upload still succeeds.

**HXI surface.**
- `useCameraStream` hook owns the `MediaStream` lifecycle. `startCameraStream` calls `navigator.mediaDevices.getUserMedia` (browser-native consent gate), creates an offscreen `<video>` + `<canvas>`, runs `setInterval(fps)` that downsamples longest-edge to `frame_max_dimension` (512 default), encodes JPEG via `canvas.toBlob('image/jpeg', q=0.6)`, and POSTs multipart. `stopCameraStream` calls `track.stop()` on every track and clears the interval.
- `CameraLiveIndicator` is rendered top-right of every HXI view from `App.tsx` whenever `useCameraStore.active === true`. Inline SVG red dot with `<animate>` pulse + REVOKE button. Per HXI Design Principle #3: stroke SVG only, no emoji.
- `App.tsx` adds a top-level `useEffect` that registers a `beforeunload` handler calling `stopCameraStream()` unconditionally — never leave the camera alive across navigation.
- `PerceptionLivePanel` renders inside `SettingsMain` when the Perception section is selected. Live START/STOP button toggles `startCameraStream` directly (camera is live, not draft — does NOT wait for APPLY). Honest-degrade banner if `cognitive.llm_base_url_vision` is empty ("Vision tier not configured. Frames will be stored, but no agent will observe them. AD-733a forward marker adds the consumer."). HTTPS warning if `window.location.protocol !== "https:"` AND hostname is not `localhost` / `127.0.0.1`.
- AD-741 registry: `insert_section(...)` adds the Perception section in the Perception & Voice domain. The fields are wired via the standard registry field-rendering path (no special-case code in `SettingsMain` other than the `PerceptionLivePanel` injection above the generic field rows).

**Files.**
- `src/probos/config.py` (+33 lines: `CameraStreamConfig` + `PerceptionConfig`; one-line wire onto `SystemConfig`).
- `src/probos/perception/__init__.py` (new, ~85 lines: descriptor + section registration via `insert_section`).
- `src/probos/routers/perception.py` (new, ~155 lines: token bucket + anchor write + multipart endpoint).
- `src/probos/api.py` (one-line router registration).
- `ui/src/store/useCameraStore.ts` (new): minimal Zustand slice for camera state.
- `ui/src/hooks/useCameraStream.ts` (new): MediaStream + interval + multipart POST.
- `ui/src/components/perception/CameraLiveIndicator.tsx` (new): persistent top-bar indicator.
- `ui/src/components/settings/sections/PerceptionLivePanel.tsx` (new): live controls in Settings.
- `ui/src/components/settings/SettingsMain.tsx` (one-line conditional render).
- `ui/src/App.tsx` (top-level mount + `beforeunload` handler).

**Invariants preserved.** AD-731 invariant enforced at four layers: (1) IntentMessage.params allowed-key whitelist in test, (2) source-scan test asserts no inline-base64 literals in router source, (3) `_validate_and_store_attachment` chain stores by SHA, (4) endpoint response shape carries no bytes. AD-541b anchored episode (importance=8, `anchors.trigger_type="camera_stream_began"`) defends future confabulation. BF-280 n/a (no subprocess — `getUserMedia` is browser-native + Python-side `subprocess.Popen` is not used). BF-282 n/a (no binary stdout). BF-287 enforced: tests use real `SystemConfig()` + real `FilesystemAttachmentStore(tmp_path)` per the substrate-boundary rule.

**Tests.** +13 pytest in `tests/test_ad733_perception_config.py` (3), `tests/test_ad733_intent_descriptor.py` (2), `tests/test_ad733_frame_endpoint.py` (8). +5 vitest in `ui/src/components/perception/__tests__/CameraLiveIndicator.test.tsx` (2) + `ui/src/hooks/__tests__/useCameraStream.test.ts` (3). Full gate: 13999 → 14012. UI build green (`dist/assets/index-bhtBkOzv.js`).

**Zero new deps.** All browser-native APIs (`getUserMedia`, `<canvas>`, `Blob`, `crypto.randomUUID`) + already-resident `pyyaml`/`pillow`/`fastapi` on the Python side. No pyproject / lockfile / ui package changes. Zero-line license diff.

**Forward markers.**
- **AD-733a** (issue #665) — Fast vision tier split (`llm_model_vision_fast` + `llm_model_vision_deep` on `CognitiveConfig`) + 1-Hz working-memory tick batcher + LLM consumer subscribed to `vision_observation`. Trigger: Captain enables camera and asks "what does Ezri see right now?"
- **AD-733b** (issue #666) — `ObserverAgent` type derived from `CognitiveAgent`. Proactively surfaces detected events (faces, objects, posture changes) into the bridge alerts stream. Integrates with AD-674 (graduated initiative) + AD-411 (emergent detector). Trigger: AD-733a in place + Captain asks for proactive observation notifications.
- **AD-733-1** (issue #667) — AttachmentStore retention reaper for frames tagged `source=camera`. Default: delete frames older than 1 hour, configurable. Trigger: disk fills with stored frames after 24h of camera-on time.
- **AD-733-2** (issue #668) — Multi-source camera/screen capture (front + back webcam, `getDisplayMedia` screen capture). Trigger: operator asks for desktop screen sensing alongside webcam.

### AD-733a — Vision consumer + supervisor + working memory + DM context injection (Wave 171)

**Date:** 2026-05-17
**Decision:** Close the loop on AD-733 by shipping the three-tier vision pipeline that consumes the `vision_observation` intents broadcast in Wave 170. Three new modules under `src/probos/perception/`:

- `supervisor.py` — pluggable per-frame admission gate (Strategy `Protocol` + default `PerceptualHashStrategy`). v1 strategy: temporal throttle (default 5s floor) + 64-bit aHash diff (default novelty threshold 0.15). Pure Python, Pillow-only.
- `working_memory.py` — per-agent ring buffer (default capacity 8) holding `VisionObservation(timestamp, attachment_ref, description, novelty_score, subject_identity, session_id)`. `render_for_prompt` emits the `--- Current Visual Context ---` block. **BF-294 confabulation guard:** empty buffer renders an explicit "no current visual data" sentinel so the agent never silently invents a scene.
- `consumer.py` — runtime-owned `VisionConsumer` subscribes to `vision_observation`, runs the supervisor gate, calls the AD-732 vision tier via `build_multimodal_messages` (BF-268 OpenAI-shape), writes to every registered observer's working memory, and anchors an Episode at `importance=6` with `AnchorFrame(channel="perception", trigger_type="vision_described")`. Tier-2 honest-degrade at every step.

Also ships:
- `PerceptionConfig` extended with five fields (`vision_consumer_enabled`, `vision_min_interval_seconds`, `vision_novelty_threshold`, `working_memory_capacity`, `vision_tier`).
- `startup/finalize.py` wires the consumer per BF-287 (`runtime.registry.all()` iteration, never private `_agents`).
- `routers/agents.py` prepends `render_for_prompt()` into `message_text` ahead of the bus send, mirroring AD-725's `targeted_recall_block` pattern. Gated on `perception.enabled` so disabling the subsystem cleanly removes the block.

**Source/Supervisor/Reply three-tier pattern absorbed from NeuralCompanion (MIT).** Architecture only, no code copied. AD-742d forward marker (#672) covers pluggable supervisor strategy variants (motion / CLIP / classifier).

**AD-731 invariant preserved end-to-end.** Frame bytes flow through `AttachmentStore.read(sha)`; the bus message carries only the SHA. Source-scan test `test_ad731_invariant_no_inline_base64_in_perception_modules` enforces zero `b64encode` / `base64.b64` / `blob_b64` in any new perception module.

**Eight-guard catalog NOT retriggered.** Reuses the existing AD-732 `vision` tier; AD-742a (#669) carries the per-frame `vision_fast` split when it ships.

**Forward markers referenced.** AD-742a (#669), AD-742d (#672), AD-742f (#674).

**Files.**
- `src/probos/perception/{supervisor,working_memory,consumer}.py` (new, ~480 lines combined)
- `src/probos/config.py` (+18 lines: PerceptionConfig fields)
- `src/probos/startup/finalize.py` (+40 lines: consumer wiring)
- `src/probos/routers/agents.py` (+19 lines: scene-block injection)
- `tests/test_ad733a_vision_consumer.py` (new, 19 tests: 6 supervisor, 4 WM, 5 consumer, 3 integration, 1 AD-731 source scan)
- `tests/test_wave171_acceptance.py` (new, Captain's acceptance test — Captain holds glass / Ezri describes it end-to-end)

**Tests.** +19 pytest in `test_ad733a_vision_consumer.py`, +1 pytest in `test_wave171_acceptance.py`. Full gate baseline 14012 -> 14032.

**Closes:** #665.

### AD-733b — ProactiveVisionObserver + identity hook (Wave 171)

**Date:** 2026-05-17
**Decision:** Add the proactive emission layer on top of AD-733a so an agent can surface visual events to the Captain without being prompted first, and populate VisionObservation.subject_identity via a one-shot vision LLM identity check on the first frame of a session.

New module `src/probos/perception/observer.py` ships `ProactiveVisionObserver` + `ProactiveBudget`. Two triggers in v1:
- **scene_introduction** — fires once per camera session on the first non-empty working-memory observation. Bypasses the novelty threshold (the camera-just-turned-on event itself is the trigger).
- **high_novelty** — fires when `observation.novelty_score >= proactive_novelty_threshold` (default 0.50), gated by `max_emissions_per_session` (default 3) AND `min_dwell_seconds` (default 30s).

The observer does NOT compose user-facing reply text. It sends a `[SYSTEM-INITIATED: ...]` synthesized user-turn to the agent via `runtime.intent_bus.send` — the **agents own LLM** composes the visible message using its voice profile + the working memory block. Preserves agent voice instead of generating uniform copy.

**Identity hook** lives inside `VisionConsumer._process`: on the first frame of every session, `_resolve_subject_identity` calls the vision LLM with the Captain reference avatar SHA + the live frame and parses the one-word response (`captain` | `other` | `unknown`). One extra vision LLM call per session — Captain authorized the cost. AD-742b (#670) forward marker replaces this with face-embedding enrollment.

New PerceptionConfig fields: `captain_avatar_ref` (empty default disables identity recognition), `proactive_observer_enabled`, `proactive_max_emissions`, `proactive_dwell_seconds`, `proactive_novelty_threshold`. `startup/finalize.py` wires the observer onto the AD-733a consumer when both `perception.enabled` and `proactive_observer_enabled` are True.

**Tier-2 honest-degrade** at every step: failed identity resolution returns `unknown`; failed observer emission returns `False` without blocking the WM write or the episode anchor; the consumers first-observation-in-session tracker is set-based and survives partial failures.

**AD-731 invariant preserved.** Identity hook reads BOTH images through `AttachmentStore.read(sha)`; the bus message stays ref-only. Source-scan test (under AD-733a) keeps observer.py + the updated consumer.py honest.

**Forward markers referenced.** AD-742a (#669), AD-742b (#670), AD-742c (#671), AD-742d (#672), AD-742e (#673), AD-742f (#674) — all six TECHNICAL triggers cited per AD-722c-3.

**Files.**
- `src/probos/perception/observer.py` (new, ~180 lines)
- `src/probos/perception/consumer.py` (+90 lines: `_resolve_subject_identity` + `_lookup_captain_avatar_ref` + observer wiring in `_process`)
- `src/probos/config.py` (+22 lines: five PerceptionConfig fields)
- `src/probos/startup/finalize.py` (+20 lines: observer wiring)
- `tests/test_ad733b_proactive_observer.py` (new, 10 tests)

**Tests.** +10 pytest. Baseline 14032 -> 14042.

**Closes:** #666.

### AD-733c-1 - DM-receive force describe of latest captured frame (Wave 172)

**Part of #675.** The agent's DM reply was previously grounded in whatever happened to be in `VisionWorkingMemory` at `render_for_prompt()` time. With a 3s supervisor `min_interval` and a static-pose scene, the WM could contain a 20s-old observation when the Captain typed `what am I holding?`. AD-733c-1 forces a fresh describe of the latest captured frame BEFORE the WM is rendered into the DM, bounded by a 4s wall-clock timeout via BF-302 force + BF-304 single-flight.

**API.** `VisionConsumer.force_describe_current_frame(session_id=None, *, timeout_s=4.0) -> str | None`. Tier-2 honest-degrade: timeout / no cached frame / LLM error returns None and logs WARNING; DM proceeds without the fresh frame. Per-session and global `(sha, captured_at)` cache populated inside `_handle` BEFORE the supervisor gate so dropped/throttled frames still register.

**DM hook.** `routers/agents.py:agent_chat` calls force-describe immediately BEFORE the AD-733a `render_for_prompt()` scene-block injection, gated on new `PerceptionConfig.dm_force_describe_enabled` (default True). The call is awaited so the WM contains the fresh observation when `render_for_prompt()` reads it.

**AD-731 invariant.** Frames stay as SHA refs end-to-end; the synthetic `IntentMessage` carries only the attachment_ref. AD-541b anchored episode (importance=6, channel=`perception`) still written by the existing `_process()` path - force=True does NOT bypass `_anchor_episode`.

**Files.**
- `src/probos/perception/consumer.py` (+85 lines: per-session SHA cache in `_handle`, `force_describe_current_frame` API, `_reset_latest_frame_cache_for_tests` helper)
- `src/probos/routers/agents.py` (+18 lines in the AD-733a scene-injection block)
- `src/probos/config.py` (+8 lines: `dm_force_describe_enabled` PerceptionConfig field)
- `tests/test_ad733c1_force_describe.py` (new, 6 tests)

**Tests.** +6 pytest.

**Forward markers (Wave 172).** AD-733c-5 (#676 per-agent engagement), AD-733c-6 (#677 budget guard), AD-733c-7 (#678 Silero VAD + dormant-pauses-capture). All filed at GATE 1.

### AD-733c-2 - PerceptionModeController (Wave 172)

**Part of #675.** Introduces the engagement-aware mode controller that drives the supervisor's tuning knobs based on conversational tempo. Three modes map to Captain's metaphor: DORMANT ("in another room"), AMBIENT ("same room, reading a book"), ENGAGED ("looking at you while we talk"). Each is a baked-in `ModePreset` bundle pushed to the live `PerceptualHashStrategy` via the BF-308 setters.

**API.** `PerceptionModeController` exposes `current_mode` / `mode_since` / `last_dm_activity_at` read properties, `recent_transitions(limit=3)` newest-first history, `get_preset(mode)` lookup, `transition_to(mode, *, trigger="manual") -> bool` (idempotent; 1s programmatic cooldown bypassed by manual trigger), and three engagement hooks: `note_dm_activity()` (step-wise DORMANT->AMBIENT->ENGAGED), `note_high_novelty_event()` (AMBIENT->ENGAGED), `note_wake_word()` (stub rewritten by AD-733c-3). The `_run()` watchdog body is a 30s no-op tick stub; AD-733c-4 replaces it with the idle drop-back logic.

**Timestamps.** All wall-clock timestamps use `time.time()` rather than `time.monotonic()`. Captain Required override at GATE 1: the `/api/perception/mode` GET response surfaces `since` / `last_dm_activity` / transition `at` values to the operator UI; monotonic values are meaningless to humans. NTP drift over the 30s watchdog tick is negligible for minutes-scale idle thresholds.

**Endpoints.** New `GET /api/perception/mode` returns `{mode, since, last_dm_activity, presets, transitions}`; `POST /api/perception/mode {mode}` is the manual override (trigger="manual" bypasses cooldown). Both behind `require_crew_scope`.

**Wiring.** `startup/finalize.py` constructs the controller next to `VisionConsumer` with `initial_mode=AMBIENT` and `await controller.start()`. `startup/shutdown.py` mirrors the `recording_reaper` pattern. `routers/agents.py:agent_chat` extends the AD-733c-1 force-describe block with a `controller.note_dm_activity()` call. `perception/observer.py` nudges the controller after a successful proactive DM dispatch.

**HXI.** New `ui/src/store/usePerceptionModeStore.ts` Zustand slice. `CameraLiveIndicator.tsx` adds a stroke-bordered Mode badge after the CAMERA LIVE span (amber DORMANT/AMBIENT/ENGAGED, no emoji per HXI #3). `PerceptionLivePanel.tsx` gets a MODE section with three text buttons + last-3-transitions list.

**AD-731 invariant.** `test_ad731_invariant_no_inline_base64_in_perception_modules` extended to scan `mode_controller.py`.

**Files.**
- `src/probos/perception/mode_controller.py` (new, ~245 lines)
- `src/probos/routers/perception.py` (+72 lines: BaseModel import, GET + POST /mode endpoints)
- `src/probos/routers/agents.py` (+11 lines: note_dm_activity hook in agent_chat)
- `src/probos/perception/observer.py` (+13 lines: note_high_novelty_event hook after dispatch)
- `src/probos/startup/finalize.py` (+19 lines: controller wiring)
- `src/probos/startup/shutdown.py` (+11 lines: stop hook)
- `ui/src/store/usePerceptionModeStore.ts` (new, ~90 lines)
- `ui/src/components/perception/CameraLiveIndicator.tsx` (+26 lines: Mode badge)
- `ui/src/components/settings/sections/PerceptionLivePanel.tsx` (+75 lines: MODE section)
- `tests/test_ad733c2_mode_controller.py` (new, 13 tests including AD-731 invariant)
- vitest: `CameraLiveIndicator.modeBadge.test.tsx` (3) + `PerceptionLivePanel.modeSection.test.tsx` (3)

**Tests.** +13 pytest, +6 vitest. UI bundle `index-CUG-925p.js`.

### AD-733c-3 - Wake-word engage endpoint + UI fire-and-forget (Wave 172)

**Part of #675.** Wake-word events (browser-side ONNX detector from AD-705) flip the PerceptionModeController to ENGAGED synchronously BEFORE the chat submit. The 5s wake-word cooldown prevents UI flap when the detector fires multiple times during the same utterance.

**Endpoint.** `POST /api/perception/engage` accepts `{agent?, phrase?, source: "wake_word" | "manual"}`. Body fields are informational (logged); the controller only needs the side effect. Returns `{ok, mode, transitioned, reason}` where `reason` is one of `"transitioned" | "refreshed" | "cooldown" | "blocked"`.

**Controller change.** `note_wake_word()` rewritten from `None` to `tuple[bool, str]`. New class constant `WAKE_WORD_COOLDOWN_S = 5.0` separate from the 1s `PROGRAMMATIC_COOLDOWN_S` so wake events are throttled independently. `_last_wake_word_at` tracker initialized to 0 so the first wake event always succeeds.

**UI hook.** `IntentSurface.tsx:onWake` callback fires a fire-and-forget `void fetch('/api/perception/engage', ...)` BEFORE the chat submit, ONLY for agent-surface wakes (system-surface "computer ..." does not imply engagement with any agent's perception). Failure surfaces as `console.warn` only -- the chat path proceeds regardless.

**Files.**
- `src/probos/perception/mode_controller.py` (+30 lines: WAKE_WORD_COOLDOWN_S, _last_wake_word_at, rewritten note_wake_word)
- `src/probos/routers/perception.py` (+42 lines: _PerceptionEngageRequest model + /engage endpoint)
- `ui/src/components/IntentSurface.tsx` (+18 lines: fire-and-forget engage POST in onWake)
- `tests/test_ad733c3_engage_endpoint.py` (new, 4 tests)
- `ui/src/__tests__/IntentSurface.engage.test.tsx` (new, 3 tests)

**Tests.** +4 pytest, +3 vitest. UI bundle `index-C8-ybnnU.js`.

### AD-733c-4 - Idle drop-back timers (Wave 172)

**Closes #675** (final sub-AD of the AD-733c umbrella). The `PerceptionModeController._run()` watchdog stub (left by AD-733c-2) is replaced with a per-tick drop-back check so the system doesn't pay engaged-cadence vision LLM costs after the operator walks away.

**Drop-back rules.**
- `ENGAGED -> AMBIENT` when `now - last_dm_activity_at >= engaged_idle_seconds` (default 300s = 5 min). Uses `last_dm_activity_at` rather than `mode_since` because ENGAGED can be re-entered by `note_dm_activity()` without a mode transition.
- `AMBIENT -> DORMANT` when `now - mode_since >= ambient_idle_seconds` (default 1800s = 30 min). DM activity in AMBIENT would have driven the controller to ENGAGED (per AD-733c-2's step-wise ramp), so `mode_since` IS the AMBIENT-entry timestamp for any session that reached AMBIENT.
- `DORMANT` stays put. Only manual override (`POST /api/perception/mode`), wake-word (`note_wake_word`), or DM activity (`note_dm_activity`) moves the controller out of DORMANT.

**Transitions are logged as `trigger="idle_timer"`** so the operator can correlate the CameraLiveIndicator mode-badge change with the journal entry.

**Config.** Three new `PerceptionConfig` fields: `engaged_idle_seconds` (default 300, range 30-3600), `ambient_idle_seconds` (default 1800, range 60-86400), `idle_watchdog_tick_seconds` (default 30, range 5-300). `startup/finalize.py` threads all three into `PerceptionModeController.__init__` so operator config flows to the controller via the same construction site as `initial_mode`.

**Watchdog floor.** The controller's internal `_idle_tick_s` is floored at `0.001s` (vs the production-side Pydantic floor of `5.0s`) so unit tests can drive sub-second ticks without paying production cadence. Defensive: prevents divide-by-zero / negative-timeout from a misconfigured runtime construction.

**Files.**
- `src/probos/config.py` (+14 lines: three new PerceptionConfig fields)
- `src/probos/perception/mode_controller.py` (+52 / -7: constructor args, `_check_idle_drop_back` helper, `_run` body)
- `src/probos/startup/finalize.py` (+5 / -1: constructor wires new fields)
- `tests/test_ad733c4_idle_drop_back.py` (new, 5 tests)

**Tests.** +5 pytest (engaged->ambient drop, ambient->dormant drop, engaged stays under threshold, dormant stays put, watchdog tick drives drop-back through the real asyncio loop). Uses real `PerceptionModeController` with a tiny `_FakeRuntime` dataclass (`vision_consumer = None`) per BF-287 (no MagicMock at substrate boundary).


### AD-742a — vision_fast LLM tier (Wave 174)

**Context.** AD-733a v1 routes both per-frame supervisor describes AND scene-introduction/high-novelty narrative summaries through the single AD-732 `vision` tier (qwen3.6:27b on local Ollama). Per-frame describes are sub-1s jobs; spending 4-6s of 27B inference on every flagged frame burns the `vision_min_interval_seconds=3.0s` budget and produces a 2-second-stale WM ring buffer.

**Decision.** Split `vision` into `vision` (deep narrative, unchanged) and `vision_fast` (per-frame describes). `vision_fast` is the seventh peer in `_LLM_TIERS`. Default model: `moondream` (Apache 2.0, 1.8B, `ollama pull moondream`). All `vision_fast` fields default None — honest-degrade fallback to `vision` when unconfigured.

**Eight-guard audit completed (15 sites).** Every tier-enumerating site updated: `_LLM_TIERS` (added), `_TIER_ORDER` (unchanged — BF-269 invariant: vision tiers MUST NOT fall back to text), 8 `tier_config()` dict-maps (added), `is_vision_tier_configured` (branch added), ModelRouter bypass (BF-273 — extended), fallback chain `vision_fast -> vision` ONLY (BF-269 — added), health probe short-circuit when unconfigured (extended), LLMResponseCache (shape-based, tier-agnostic, no change). 5 hardcoded `("fast","standard","deep","vision")` tuples in `__main__.py` + `commands_llm.py` refactored to `from probos.cognitive.llm_client import _LLM_TIERS` per AD-732 lesson #1.

**License posture.** Zero new pip deps. Zero new npm deps. `moondream` is an Ollama-pullable model, not a Python dependency. `THIRD_PARTY_LICENSES.md` adds a single attribution row.

**Forward markers.** AD-742a-1 — A/B comparison study moondream vs qwen2-vl:2b on Captain's actual feed (post-build).

**Tests.** +13 pytest in `tests/test_ad742a_vision_fast_tier.py` covering all eight-guard surfaces + a source-scan regression (`test_no_hardcoded_tier_tuples_outside_llm_client`) that fails if any future PR re-introduces a hardcoded tier tuple.

**Files.**
- `src/probos/config.py` (+ 5 CognitiveConfig fields, `vision_fast` row in all 8 tier_config maps, new `PerceptionConfig.vision_fast_tier` field)
- `src/probos/cognitive/llm_client.py` (_LLM_TIERS extended, ModelRouter bypass + health probe + fallback chain updated)
- `src/probos/cognitive/vision_dispatch.py` (is_vision_tier_configured `vision_fast` branch)
- `src/probos/perception/consumer.py` (`vision_fast_tier` ctor arg, `_describe` routing block)
- `src/probos/startup/finalize.py` (threads new field)
- `src/probos/__main__.py` + `src/probos/experience/commands/commands_llm.py` (5 tier-tuple refactors)
- `src/probos/settings/section_registry.py` (3 new FieldDescriptors)
- `config/system.yaml` (commented-out opt-in block)
- `THIRD_PARTY_LICENSES.md` (moondream attribution)
- `tests/test_ad742a_vision_fast_tier.py` (new, 13 tests)
- `tests/test_bf069_llm_health.py` + `test_per_tier_llm.py` + `test_ad732_vision_tier.py` + `test_ad706c2_compute_use.py` (regression-fixture updates to include `vision_fast` in expected tier sets)


### AD-742b — Face-embedding identity recognition (Wave 174)

**Context.** AD-733b v1 resolved subject identity by sending the live frame + the stored Captain avatar to the vision LLM with a one-shot `captain | other | unknown` prompt. That's expensive (one vision LLM call per session — gated by `_identity_resolved_sessions`) and brittle (avatars are stylized; the live person may not look like their avatar).

**Decision.** Replace the LLM-prompt path with a local face-embedding model. `facenet-pytorch` (MIT, single pip dep, torch already resident, MTCNN face detection + InceptionResnetV1 512-d embedding). Enrollment is one-shot: operator uploads a reference photo via `POST /api/perception/identity/enroll`; the 2048-byte embedding is persisted at `data/captain_identity.json`; the reference photo is discarded.

**Privacy threat model.** The embedding is plaintext on the operator's box. Threat: local read access — already a worse-than-this scenario. The reference photo is held only in Python memory during `enroll()`. `data/captain_identity.json` is gitignored. Operator opt-out: `DELETE /api/perception/identity` removes the file; `identity_resolver_enabled=False` disables resolution without deleting. Embedding is NOT synced via federation. AttachmentStore is NOT used (AD-731 invariant is about RPC bus payloads, not lifecycle-managed local artifacts).

**Fallback path.** AD-733b LLM-prompt path retained behind `identity_resolver_enabled=False` for CI/test envs that can't install facenet-pytorch. `startup/finalize.py` honest-degrades on import failure (logs WARNING, falls back to legacy path).

**License posture.** `facenet-pytorch>=2.5` (MIT verified via the PEP 639 classifier in METADATA — the legacy `pip show License:` field is blank because the package uses modern license-expression metadata). VGGFace2 + CASIA-WebFace pretrained weights distributed under Apache-2.0. `THIRD_PARTY_LICENSES.md` stamped. `InsightFace` rejected per GATE 1 §5 — default `buffalo_l` weights have non-commercial clauses.

**Tests.** +19 pytest in `tests/test_ad742b_face_embedding_identity.py` covering enrollment, persistence, revoke, no-face raises, threshold logic, cosine distance helper, privacy invariant (reference bytes never written to disk), VisionConsumer integration. `_compute_embedding` is mocked in unit tests — the MTCNN + ResNet load is slow and not deterministic enough for fast unit cycles.

**Forward markers.**
- AD-742b-1 — Hot-reload `identity_match_threshold` via BF-308 setter (file post-build).
- AD-742b-2 — Multi-operator enrollment / UI surface for enrollment.

**Files.**
- `src/probos/perception/identity.py` (new, ~200 lines)
- `src/probos/perception/consumer.py` (added `set_identity_resolver`, rewrote `_resolve_subject_identity` with face-embedding path first + AD-733b fallback)
- `src/probos/startup/finalize.py` (wires resolver next to VisionConsumer)
- `src/probos/routers/perception.py` (3 new endpoints: enroll / revoke / status)
- `src/probos/config.py` (2 new PerceptionConfig fields)
- `pyproject.toml` (facenet-pytorch dep)
- `THIRD_PARTY_LICENSES.md` (attribution)
- `.gitignore` (explicit `data/captain_identity.json` line)
- `tests/test_ad742b_face_embedding_identity.py` (new, 19 tests)


### AD-742e — Vision LLM call budget telemetry (Wave 174)

**Context.** AD-733a enforces `vision_min_interval_seconds=3.0s` (cost-discipline floor) and a session-wide proactive ceiling (`proactive_max_emissions=3`). The Captain has no real-time view of how close to the budget the session is — they review journal traces after the fact. AD-742a's `vision_fast` tier is cheaper than `vision`; separate counters give cost-discipline visibility.

**Decision.** `VisionConsumer` maintains in-memory per-tier counters; per-session reset on session change; per-day reset on UTC date rollover. New `GET /api/perception/budget` returns the structured snapshot. New `<VisionBudgetBadge />` HXI component polls every 5s and renders `Vis N/M` when `total_session > 0` (HXI Principle #5 progressive disclosure). Hidden entirely when zero. Hover-title shows per-tier breakdown.

**Color scale.** Amber (`#f0b060`) at 0-80%, dim-red (`#c84030`) at 80-100%, bright-red (`#e04030`) above ceiling. No emoji (HXI Principle #3).

**Session ceiling heuristic.** `proactive_max_emissions * 40` — a session-duration-free heuristic that produces 120 by default. Forward marker AD-742e-1 for SQLite-backed per-session vision_call_log + a tuned ceiling.

**v1 in-memory only.** Forward marker AD-742e-1 for SQLite persistence (small `vision_call_log` table, daily roll-up via SQL query).

**Tests.** +8 pytest in `tests/test_ad742e_vision_budget.py` (initial-state, increment, per-tier tracking, session reset, UTC date rollover, snapshot shape, API endpoint wired/unwired). +6 vitest in `ui/src/components/perception/__tests__/VisionBudgetBadge.test.tsx` (threshold-trigger visibility, color scale boundaries, hover-title content).

**Forward markers.**
- AD-742e-1 — SQLite persistence for vision_call_log + daily roll-up across restart (file post-build).
- AD-742e-2 — Operator-configurable session ceiling (instead of heuristic) once SQLite layer ships.

**Files.**
- `src/probos/perception/consumer.py` (added counter state, `_record_vision_call`, `get_budget_snapshot`; `_describe` records call after successful LLM complete; `_process` updates `_budget_current_session_id`)
- `src/probos/routers/perception.py` (new `GET /api/perception/budget` endpoint)
- `ui/src/components/perception/VisionBudgetBadge.tsx` (new, ~80 lines)
- `ui/src/components/DecisionSurface.tsx` (mount badge after Entropy span + import)
- `tests/test_ad742e_vision_budget.py` (new, 8 tests)
- `ui/src/components/perception/__tests__/VisionBudgetBadge.test.tsx` (new, 6 tests)

**UI gate.** `npx vitest run` 757 passing + 1 skipped (none of the `Errors` are AD-742e — pre-existing onnxruntime-web load issue in unrelated wakeWord tests). `npm run build` exit 0. New bundle: `index-CfjDvOSd.js`.

**License posture.** Zero new pip deps. Zero new npm deps.


### AD-742f — Vision working memory persistence across restart (Wave 175)

**Context.** AD-733a `VisionWorkingMemory` is the per-agent 8-entry ring buffer used for prompt-context injection (`render_for_prompt`). It is in-memory only. Process restart blanks every observer's recent-frame recall. AD-541b anchored episodes ARE persisted in chroma, but those are summarized long-term memory; the per-agent ring buffer is the hot prompt-context substrate. Captain's most common cross-restart use case ("describe what was on the desk earlier") was broken.

**Decision.** Add SQLite persistence at `data/perception_wm.db`. `VisionWorkingMemory` accepts optional `store` + `agent_id` kwargs; when both are present, the ring auto-hydrates on construction and every `append` writes through to disk. The factory `get_or_create_working_memory` threads the runtime-wired store through to every new WM. `startup/finalize.py` constructs `WorkingMemoryStore(data_dir / "perception_wm.db")` BEFORE `VisionConsumer` construction so observer registration sees a wired store. Default ON via `PerceptionConfig.wm_persistence_enabled=True` (hot-reload — toggles write path only).

**Honest-degrade.** `WorkingMemoryStore.__init__` swallows any sqlite/disk exception, logs WARNING, and sets `available=False`. Every load/append/clear method checks `available` first. A WM constructed against an unavailable store still functions as an in-memory ring (legacy behavior bit-for-bit preserved).

**AD-731 invariant.** Schema has `attachment_ref TEXT` columns, NO `BLOB` columns. Image bytes stay in `AttachmentStore` (content-addressable by SHA-256); the WM DB carries refs + descriptions only. `test_ad731_invariant_no_image_bytes` source-asserts via `PRAGMA table_info` that no column is of type `BLOB`.

**Sync over async.** Used stdlib `sqlite3` rather than `aiosqlite` because `VisionWorkingMemory.append` is synchronous — we don't have an event loop handle there. Write path is short (<1 ms) and protected by a module-level Lock so multiple agents writing concurrently don't fight the connection. Adding aiosqlite would force every observer write into a `run_in_executor` round-trip for no measurable benefit.

**Tests.** +10 pytest in `tests/test_ad742f_wm_persistence.py` (real `WorkingMemoryStore` over `tmp_path`, BF-287 — no MagicMock at substrate boundary): schema init, append+load roundtrip, capacity cap on load, eviction-beyond-capacity through WM, per-agent isolation on clear, honest-degrade on unwritable path, in-memory-only when store=None, AD-731 invariant source-check, factory threads store, factory reset clears handle.

**Forward markers.**
- AD-742f-1 — Cross-host federation of WM rows.
- AD-742f-2 — TTL-based pruning of old WM rows (cap is currently count-based only).

**Files.**
- `src/probos/perception/wm_store.py` (new)
- `src/probos/perception/working_memory.py` (store kwargs threaded through `__init__` + `append`)
- `src/probos/perception/consumer.py` (`set_working_memory_store` setter + `_WM_STORE` module global threaded through factory)
- `src/probos/startup/finalize.py` (constructs store before `VisionConsumer`)
- `src/probos/perception/__init__.py` (new `FieldDescriptor`)
- `src/probos/config.py` (new `wm_persistence_enabled` field on `PerceptionConfig`)
- `tests/test_ad742f_wm_persistence.py` (new, 10 tests)

**License posture.** 0-line diff on all 5 license files. Uses stdlib `sqlite3` (PSF license, already absorbed via Python).


### AD-742d — Pluggable VisionSupervisor strategies (Wave 175)

**Context.** `SupervisorStrategy(Protocol)` was shipped Wave 171 as the AD-742d forward-marker seam, but `PerceptualHashStrategy` was the only implementation. Different camera setups want different admission policies: aHash is good general-purpose but weaker on motion within a static frame; pixel-diff catches typing/head-turn that aHash blurs; HSV-histogram catches lighting shifts; null strategies enable cost-tight + debug deployments.

**Decision.** Ship four new strategy classes (`MotionStrategy`, `SceneChangeStrategy`, `NeverDescribeStrategy`, `AlwaysAdmitStrategy`) alongside the existing `PerceptualHashStrategy`. Add operator-selectable choice via `PerceptionConfig.vision_supervisor_strategy` (Pydantic-validated to one of five names). Default stays `"ahash"` so current behavior is preserved bit-for-bit. `VisionConsumer.__init__` accepts `supervisor_strategy_name`; `startup/finalize.py` threads the config value through; new `build_strategy()` resolver honest-degrades to aHash + WARNING on unknown name.

**Restart-required (NOT hot-reload).** Strategy selection is restart-required because swapping mid-flight orphans the previous strategy's baseline state (`last_hash` / `last_pixels` / `last_hist`). The FieldDescriptor accordingly omits `hot_reload=True`. Cap values within a strategy (`min_interval`, `novelty_threshold`, `baseline_max_age`) remain hot-reload via existing BF-308 setters — every new strategy implements those setters uniformly (null strategies accept and ignore).

**Tier-2 honest-degrade.** Every strategy's `evaluate()` ALLOWS the first frame and then throttles on decode failure — never raises. The shared `_load_pil_image` helper returns `None` on any PIL exception. Strategies fall back to allow-on-decode-failure so the consumer can still produce an episode.

**AD-731 invariant.** Strategies operate on bytes passed by reference. No strategy writes to disk. No inline base64 anywhere.

**Tests.** +12 pytest in `tests/test_ad742d_pluggable_supervisor.py`: registry contents, Protocol conformance for all 5, `build_strategy` resolves each name, unknown-name fallback with WARNING (caplog), motion admits-first/throttles/diff-detects, scene_change lighting-shift, never/always determinism, Pydantic validator rejects unknown, consumer init uses configured strategy. Real PIL `Image.new("RGB", ...).save(buf, "JPEG")` fixtures — no MagicMock at strategy boundary (BF-287).

**Forward markers.**
- AD-742d-1 — CLIP-embedding semantic strategy (out of scope: pip dep + embedding cache).
- AD-742d-2 — Per-session strategy override (out of scope: config-level switch sufficient for Captain's current setup).

**Files.**
- `src/probos/perception/supervisor.py` (4 new strategy classes + `STRATEGY_REGISTRY` + `build_strategy` + `_load_pil_image` helper + `__all__` extension)
- `src/probos/perception/consumer.py` (`supervisor_strategy_name` kwarg; `build_strategy` resolver call)
- `src/probos/startup/finalize.py` (thread `vision_supervisor_strategy` config through)
- `src/probos/perception/__init__.py` (new `FieldDescriptor`, non-hot-reload)
- `src/probos/config.py` (new `vision_supervisor_strategy` field + validator)
- `tests/test_ad742d_pluggable_supervisor.py` (new, 12 tests)

**License posture.** 0-line diff on all 5 license files. PIL already resident.


### AD-733c-6 — Engaged-mode vision LLM call budget enforcement (Wave 175)

**Context.** AD-742e (Wave 174) shipped telemetry only — per-tier vision LLM call counters, session/UTC reset, `/api/perception/budget` endpoint, HXI badge with a heuristic ceiling (`proactive_max_emissions × 40`). There was no enforcement: a runaway ENGAGED-mode session could call the vision LLM hundreds of times in an hour with no automatic brake. Captain's idle drop-back (AD-733c-4) catches lack-of-activity but not over-activity.

**Decision.** Add per-session and per-day soft caps with auto-drop ENGAGED → AMBIENT on cap hit. Three new `PerceptionConfig` fields: `engaged_budget_enforcement=True`, `engaged_call_cap_per_session=200`, `engaged_call_cap_per_day=2000`. The new private method `_maybe_enforce_budget(session_id)` is called from `_record_vision_call` after the increment: when current mode is ENGAGED and totals >= cap, it synchronously calls `controller.transition_to(Mode.AMBIENT, trigger="budget_exhausted")` and logs a once-per-session WARNING. Defaults chosen so Captain's typical ~50-100 vision-call sessions (per AD-742e baseline) stay well under the 200 cap.

**Anti-deadlock.** `_record_vision_call` is invoked from `_describe` at `consumer.py:530`, INSIDE `async with self._describe_lock`. The new enforcement call is fully synchronous (`controller.transition_to` is sync; no await, no re-entry). Safe to call while holding the lock. Confirmed at GATE 1 §3.

**Hot-reload posture.** Cap values + `engaged_budget_enforcement` are hot-reload — operator dials mid-session, no restart. Strategy selection (AD-742d) is restart-required. Persistence path (AD-742f) is restart-required.

**Snapshot backcompat.** `get_budget_snapshot()` keeps `session_ceiling_estimate` for AD-742e callers that haven't migrated, but the value is now driven by `cap_per_session` (default 200 vs AD-742e's heuristic 120). New keys: `cap_per_session`, `cap_per_day`, `enforcement_enabled`, `cap_reached_session`, `cap_reached_day`.

**HXI badge.** `VisionBudgetBadge.tsx` color scale shifted: green `rgb(80,180,120)` <80%, orange `rgb(220,160,60)` 80-99%, red `rgb(220,80,80)` >=100%. Dim grey `rgb(100,100,120)` override when `enforcement_enabled=false` (no alarm state when not enforcing). HXI Principle #3 honored — no emoji, color + text only. AD-742e badge vitests updated to the new palette (6 existing); 3 new vitests cover the AD-733c-6-specific cap fields and dim override.

**Once-per-session WARNING.** New `_budget_cap_notified_sessions: set[str]` is cleared on session change, so the next session gets its own one-shot WARNING (rather than spamming on every post-cap call OR going silent forever). Test `test_session_change_resets_notification_flag` proves this end-to-end.

**Trigger docstring extension.** `mode_controller.Transition.trigger` docstring now lists `"budget_exhausted"` alongside `init/dm_activity/wake_word/novelty/idle_timer/manual`. No code change to mode_controller behavior — `transition_to` already accepts arbitrary trigger strings.

**Tests.** +9 pytest in `tests/test_ad733c6_engaged_budget_enforcement.py` using real `PerceptionModeController` + real `SystemConfig` (BF-287 — no MagicMock at substrate boundary): under-cap no-transition, session-cap hit drops, day-cap hit drops, enforcement-disabled no-transition, AMBIENT-mode no-transition (defense-in-depth: cap-past has no effect when not engaged), WARNING rate-limited per session, session-change resets notification, snapshot exposes new keys, hot-reload cap change effective on the next call. +3 vitest in `VisionBudgetBadge.test.tsx` for the new cap fields + 6 existing AD-742e vitests updated to the new color palette.

**Forward markers.**
- AD-733c-6-1 — Persist daily aggregate across restarts (`data/perception_budget.db`).
- AD-733c-6-2 — WardRoom "Budget reached" message post on cap-hit.

**Files.**
- `src/probos/perception/consumer.py` (new `_maybe_enforce_budget`, extended `_record_vision_call` + `get_budget_snapshot`, new `_budget_cap_notified_sessions` state)
- `src/probos/perception/mode_controller.py` (Transition.trigger docstring extension only — no behavior change)
- `src/probos/config.py` (3 new `PerceptionConfig` fields)
- `src/probos/perception/__init__.py` (3 new FieldDescriptors, all hot-reload)
- `ui/src/components/perception/VisionBudgetBadge.tsx` (color scheme + cap-field consumption)
- `ui/src/components/perception/__tests__/VisionBudgetBadge.test.tsx` (3 new + 6 updated)
- `tests/test_ad733c6_engaged_budget_enforcement.py` (new, 9 tests)
- `tests/test_ad742e_vision_budget.py` (`session_ceiling_estimate` expectation updated 120 -> 200)

**UI gate.** `cd ui && npx vitest run src/components/perception/__tests__/VisionBudgetBadge.test.tsx` → 9/9. `cd ui && npm run build` → exit 0. New bundle: `index-DPxUl-OZ.js`.

**License posture.** 0-line diff on all 5 license files.


### AD-743 — Adaptive conversational pacing in 1:1 DMs (Wave 176)

**Date:** 2026-05-19
**Closes:** #662
**Status:** Shipped

**Decision.** Add a new `[FOLLOW_UP delay_seconds reason]` bracket marker (extends AD-728d / AD-730-3 family) and a sibling `ConversationPacingScheduler` runtime service so an agent can schedule a single multi-beat follow-up within an active 1:1 DM. The synthesized user-turn `IntentMessage` carries `params["from"] = "pacing_scheduler"` so AD-541b episodic anchors can distinguish system-synthesized turns from Captain-authored ones. Two-budget rate limit mirrors AD-728c: per-active-conversation cap (default 2) + rolling 1h per-agent cap (default 6); budgets are NOT additive. Captain interruption (new DM) cancels any pending follow-up via a hook at the top of `agent_chat`.

**Implementation notes.**

- `cognitive/dm/pacing_scheduler.py` owns `ConversationPacingScheduler` with `start` / `stop` / `schedule_followup` / `cancel_for_conversation` / `pending_followups`. Single-flight per `(agent_id, conversation_id)`; later FOLLOW_UP overrides prior pending task. Every `asyncio.create_task` reference held in `self._pending_tasks` and removed via `add_done_callback`. `CancelledError` caught + re-raised in `_emit_followup` per async-discipline rule.
- `DmSanityGate` gains `extract_followup(text) -> tuple[int, str] | None` and `strip_followup(text)` with the same lax-strip discipline as AD-728d / AD-730-3 (well-formed AND malformed variants stripped before Captain-visible text).
- `DmReplyPipeline` gains `step_4d_follow_up_parse` inserted between `step_4c_image_gen_parse` and `step_4b_dm_outbound_parse`. **Name deviates from prompt's `step_5_follow_up_parse`** because `step_5_episodic_store` already occupied that slot at HEAD; the `step_4*` family is the correct namespace for bracket-marker parsers anyway (AD-728d step_4 / AD-730-3 step_4c / BF-296 step_4b).
- `AvatarsConfig` gains `pacing_enabled` (default `False` — convention #14 transitional gate) plus five cap fields with Pydantic `ge/le` bounds. All cap values read fresh on every `schedule_followup` call (BF-308 hot-reload). `pacing_enabled` master toggle requires restart (changes `runtime` attribute presence).
- `startup/finalize.py` constructs the scheduler when `pacing_enabled=True`; `startup/shutdown.py` mirrors the perception-controller shutdown pattern with `await pacing.stop()` to cancel pending tasks.
- `routers/agents.py:agent_chat` adds a `cancel_for_conversation` hook BEFORE the existing AD-725 lookup path so a Captain-initiated DM interrupts any in-flight follow-up.
- AD-731 invariant preserved: source-scan test asserts no `b64encode` / `base64.b64` / `attachment_ref` literals in `pacing_scheduler.py`. The synthesized user-turn carries only a string marker; no image bytes pass through pacing.

**Test coverage.** +12 pytest in `tests/test_ad743_adaptive_dm_pacing.py`: regex extract well-formed + reject invalid + strip both forms; scheduler delivers after delay + cancels on interruption; per-conversation budget + hourly ceiling + non-additive behavior; default-off config gate; pipeline step ordering source-scan; synthesized follow-up carries `from`-marker; AD-731 invariant source-scan.

**License posture.** 0-line diff on all 5 license files. Zero new pip deps.

**Forward markers** (filed in roadmap, no GH issues per AD-722c-3 standing rule):

- AD-743-1 — Captain-silence "Still there?" trigger (idle-watcher loop).
- AD-743-2 — Same-tick multi-message split (delay=0 chunked rendering UX).
- AD-743-3 — Correction-driven per-conversation budget reset.


### AD-733c-5 — Per-agent perception engagement (Wave 176)

**Date:** 2026-05-19
**Closes:** #676
**Status:** Shipped

**Decision.** Promote `PerceptionModeController` from singleton to per-agent instances via a new `PerceptionEngagementRegistry` (`perception/engagement_registry.py`). Each crew agent (`is_crew_agent`) whose `CrewProfile.perception.engagement_enabled` is True gets its own controller; legacy `runtime.perception_mode_controller` becomes a back-compat pointer at the primary controller (Counselor `e1` if registered, else first registered).

**Cross-AD seam.** `CrewProfile.perception` is a new `PerceptionProfile` dataclass (`engagement_enabled`, `initial_mode`, `camera_device_id`) shared with AD-742c. AD-733c-5 owns the block; AD-742c (sibling in this wave) populates `camera_device_id`. AD-733c-7 (Silero VAD) routes through the same registry via a new `note_voice_activity()` method (added in the next AD of this wave).

**Implementation notes.**

- `PerceptionProfile` defaults preserve current singleton behavior: `engagement_enabled=True` + `initial_mode="ambient"` + `camera_device_id=""`. Legacy profile JSON without the block falls through to defaults — back-compat guaranteed.
- `PerceptionModeController.__init__` gains an `agent_id: str = ""` kwarg; `""` preserves legacy singleton semantics. Public `agent_id` property exposes the value.
- `startup/finalize.py` runs the per-agent loop AFTER the existing singleton wiring (rather than replacing it as the prompt suggested). The singleton stays constructed for boot-state correctness; then for each crew agent with engagement enabled, a per-agent controller is created and registered. The singleton attribute is finally REPOINTED to the primary controller so AD-733c-6 budget enforcement, AD-733c-2 idle watchdog, and the ProactiveVisionObserver all continue to function against a real controller.
- `select_primary_controller(registry)` helper picks Counselor (`e1`) if registered, else first registered — used by finalize to set the back-compat pointer.
- `routers/agents.py:agent_chat` note_dm_activity callsite prefers the per-agent controller via `runtime.perception_engagement_registry.get(agent_id)`; falls back to `runtime.perception_mode_controller` when the registry is unwired.
- `GET /api/perception/mode` response extended with `per_agent: {agent_id: mode_name}` field. Empty dict when registry is unwired (back-compat for single-controller deployments).
- `POST /api/perception/engage` accepts optional `agent` field (agent_id or callsign). When provided and the registry is wired: resolves agent_id directly first, then via `callsign_registry.resolve`; if neither resolves, returns 404 honest-degrade. When `agent` is empty, falls back to the legacy singleton path (runtime-wide engage).
- `startup/shutdown.py` stops each per-agent controller alongside the singleton.

**Scope deviation from prompt.** Two pieces were deferred:

1. **UI per-agent badges** — `CameraLiveIndicator` extension + `usePerceptionEngagementStore` Zustand slice + `PerceptionLivePanel` MODE table. Deferred to forward marker AD-733c-5-4 since the backend acceptance criteria are fully met without UI churn and the HXI per-agent visualization is orthogonal to the engagement logic itself. The +3 vitest deferred with the UI work.
2. **Per-agent budget enforcement threading** — `ProactiveVisionObserver` registry lookup + `VisionConsumer._maybe_enforce_budget` `agent_id` threading. Deferred to forward marker AD-733c-5-5. Current AD-733c-6 enforcement transitions the primary controller (Counselor when present), which is correct for single-user-focus deployments but doesn't yet scope budget hits to the agent whose `_describe` triggered the cap.

**Test coverage.** +11 pytest in `tests/test_ad733c5_per_agent_engagement.py`: profile defaults; CrewProfile roundtrip with perception; legacy JSON backward-compat; registry register/get; per-agent independent transitions; `select_primary_controller` preferences (Counselor wins, fallback to first, empty returns None); `agent_id` kwarg defaults to empty (back-compat); `agent_id` kwarg threaded through; registry rejects empty agent_id.

**License posture.** 0-line diff on all 5 license files. Zero new pip / npm deps.

**Forward markers** (filed in roadmap, no GH issues per AD-722c-3):

- AD-733c-5-1 — HXI editor for `PerceptionProfile`.
- AD-733c-5-2 — Hot-reload of `engagement_enabled` toggle.
- AD-733c-5-3 — Federation cross-host engagement sync.
- AD-733c-5-4 — HXI per-agent perception badges (deferred UI from this wave).
- AD-733c-5-5 — Per-agent vision LLM budget enforcement (consumer.py / observer.py threading).


### AD-733c-7 — Silero VAD secondary engagement trigger (Wave 176)

**Date:** 2026-05-19
**Closes:** #678
**Status:** Shipped (backend); browser-side integration deferred to AD-733c-7-5

**Decision.** Add a NEW ENGAGEMENT TRIGGER (not a strategy plugin) that feeds the same per-agent `PerceptionModeController` introduced by AD-733c-5. `note_voice_activity()` mirrors `note_dm_activity` step-wise ramp (DORMANT -> AMBIENT, AMBIENT -> ENGAGED, ENGAGED -> refreshed) but is throttled by `VOICE_ACTIVITY_COOLDOWN_S = 3.0` — between PROGRAMMATIC (1s) and WAKE_WORD (5s) — so continuous speech doesn't flap the mode badge.

**Implementation notes.**

- `PerceptionModeController.note_voice_activity() -> tuple[bool, str]` mirrors `note_wake_word` return shape (transitioned + reason ∈ {"transitioned", "refreshed", "cooldown", "blocked"}). New attribute `_last_voice_activity_at` tracks the per-trigger cooldown separately from wake-word + DM-activity floors.
- `Transition.trigger` docstring extended to include `"voice_activity"`.
- `POST /api/perception/voice-activity` mirrors the AD-733c-3 `/engage` shape: optional `agent` field (agent_id or callsign) routes through `runtime.perception_engagement_registry` with 404 honest-degrade on unknown agent; falls back to legacy singleton when `agent` is empty. Returns 503 `vad_engagement_disabled` when `PerceptionConfig.vad_engagement_enabled` is False (Captain explicit opt-in).
- New `PerceptionConfig.vad_engagement_enabled` (default `False` — convention #14 transitional gate) and `vad_min_speech_duration_ms` (default 400, ge=100 le=2000 — browser-side debounce floor).
- `scripts/silero-vad-fetch.ps1` mirrors the `piper-voice-fetch.ps1` shape (operator-pullable download, idempotent, -Force flag). Model bytes target `data/silero-vad/` which is ALREADY covered by the existing `data/*` gitignore rule — no `.gitignore` diff required.
- `THIRD_PARTY_LICENSES.md` gains a Silero VAD entry (MIT). `onnxruntime-web` is ALREADY in `ui/package.json` `optionalDependencies` (resident via AD-733c-3 wake-word path), so the browser-side VAD module won't add a new npm dep.

**Privacy invariant.** Audio bytes never leave the browser. The `/api/perception/voice-activity` POST body carries only `{agent?, source}` — a JSON metadata envelope. Audio frames are decoded + scored by `silero-vad.ts` locally, debounced by the operator-tunable floor, then a single boolean speech-detected event is fired.

**Scope deviation from prompt.** Browser-side `ui/src/audio/silero-vad.ts` + `voiceActivity.ts` + `CameraLiveIndicator` SPEECH indicator (+5 vitest) deferred to forward marker AD-733c-7-5. The backend acceptance criteria are fully met: endpoint exists, accepts the request shape, routes per-agent, honest-degrades when disabled, no audio bytes touch the wire. The HXI integration is a self-contained browser change with its own UI gate (`npm run build` + vitest); shipping it next session lets the backend bake in production first.

**Test coverage.** +10 pytest in `tests/test_ad733c7_vad_engagement.py`: DORMANT->AMBIENT, AMBIENT->ENGAGED, ENGAGED refreshes, cooldown blocks; endpoint disabled returns 503, routes per-agent, 404 on unknown agent, 400 on invalid source; config defaults preserve behavior; cooldown constant sits between PROGRAMMATIC and WAKE_WORD floors.

**License posture.** 0-line diff on `pyproject.toml` / `package.json` / `package-lock.json` / `LICENSE` / `.gitignore`. +1 entry on `THIRD_PARTY_LICENSES.md` (Silero VAD MIT).

**Forward markers** (filed in roadmap, no GH issues per AD-722c-3):

- AD-733c-7-1 — Browser pause `getUserMedia` in DORMANT (BroadcastChannel signal).
- AD-733c-7-2 — Multi-mic disambiguation.
- AD-733c-7-3 — Speaker diarization.
- AD-733c-7-4 — VAD-driven wake-word mute (CPU savings).
- AD-733c-7-5 — HXI VAD integration (browser-side `silero-vad.ts` + `voiceActivity.ts`).


### AD-742c — Per-agent camera selection (Wave 176)

**Date:** 2026-05-19
**Closes:** #671
**Status:** Shipped (backend); HXI multiplexer deferred to AD-742c-6

**Decision.** Wire `CrewProfile.perception.camera_device_id` (the field shipped earlier in this wave by AD-733c-5) into the actual capture path. Upload endpoint accepts an optional `agent_ids` comma-separated form field; the consumer restricts fan-out + episodic anchor to the bound set when present.

**Implementation notes.**

- `POST /api/perception/camera/frame` gains optional `agent_ids: str = Form("")` field. Comma-separated agent IDs are parsed into a `list[str]` and threaded into `IntentMessage.params["bound_agent_ids"]`. When the field is empty, the params key is omitted and legacy fan-out-to-all behavior is preserved bit-for-bit.
- `VisionConsumer._handle` adds a single early branch: `_bound = set(params.get("bound_agent_ids", []) or [])` → when non-empty, the WM fan-out loop iterates `[aid for aid in self._observer_agent_ids if aid in _bound]` and the AD-541b BF-311 anchor `agent_ids_json` mirrors the same subset. When `_bound` is None / empty, the existing `list(self._observer_agent_ids)` path runs unchanged.
- `GET /api/perception/cameras` enumerates persisted bindings `{agent_id: device_id}` (crew agents only). Device enumeration itself happens browser-side; the runtime has no view of the operator's hardware.
- `POST /api/perception/cameras/binding` accepts `{agent_id, device_id}`; mutates `profile.perception.camera_device_id` and persists via `ProfileStore.update(profile)`. 404 honest-degrade when the agent has no profile.

**AD-731 invariant preserved.** `bound_agent_ids` is a `list[str]` of agent IDs — image bytes never leak into `IntentMessage.params`. SHA refs continue to flow via the existing AttachmentStore path. Regression source-scan asserts no inline base64 in `routers/perception.py` after this change (which touches the upload endpoint where the risk is highest).

**Scope deviation from prompt.** UI components (CameraMultiplexer Zustand slice + useCameraStream multi-deviceId refactor + PerceptionLivePanel CAMERA BINDINGS table + 4 vitest) deferred to forward marker AD-742c-6. The backend acceptance criteria are fully met: form field threads correctly; consumer restricts fan-out; endpoints persist bindings; AD-731 invariant preserved. The HXI multiplexer is a self-contained browser change (opens / closes MediaStreams as bindings change) that doesn't affect runtime behavior — operators can hand-edit the CrewProfile JSON or call the endpoint directly until the HXI lands.

**Test coverage.** +10 pytest in `tests/test_ad742c_per_agent_camera.py`: AD-733c-5 dependency anchor (camera_device_id default empty); upload with `agent_ids` threads bound_agent_ids; upload without agent_ids preserves legacy fan-out; consumer source-scan validates intersection branch shape; GET /cameras returns bindings dict; POST /cameras/binding unknown agent 404; POST /cameras/binding persists; POST clears with empty device_id; AD-731 invariant router source-scan; bound_agent_ids is string list not bytes.

**License posture.** 0-line diff on all 5 license files. Zero new pip / npm deps.

**Forward markers** (filed in roadmap, no GH issues per AD-722c-3):

- AD-742c-1 — Screen capture binding per agent.
- AD-742c-2 — Federation cross-host camera sync.
- AD-742c-3 — IP camera RTSP ingestion.
- AD-742c-4 — Audio device per-agent binding.
- AD-742c-5 — Per-agent camera permissions.
- AD-742c-6 — HXI camera multiplexer integration (deferred UI from this wave).

### AD-733c-5-4 — HXI per-agent perception badges (Wave 177)

**Context.** AD-733c-5 (Wave 176) shipped the per-agent `PerceptionEngagementRegistry` and extended `GET /api/perception/mode` with a `per_agent: {agent_id: mode}` field — but the HXI never read that field. The runtime knew which agent was in which mode; the Captain couldn't see any of it. Operating "Hello Counselor" → only Ezri transitions was invisible to the operator. Per-agent perception was a hollow feature end-to-end.

**Decision.** Extend `usePerceptionModeStore` with `perAgent: Record<string, PerceptionMode>` populated from the `per_agent` field on every refresh tick. Defensively reject non-object payloads (back-compat: older runtimes without the field land as `{}`, which preserves the legacy single-mode rendering bit-for-bit). Render the per-agent surface in two places:

- `CameraLiveIndicator.tsx` swaps the single MODE badge for a row of compact `AGENT:MOD` badges (e.g. `E1:ENG` / `E2:AMB`) when `perAgent` has ≥ 2 entries. < 2 entries keeps the legacy single badge — solo-Captain deployments render bit-for-bit identical UI to HEAD.
- `PerceptionLivePanel.tsx` appends a per-agent MODE table beneath the existing preset buttons. Surfaces only when `perAgent` is non-empty (HXI Principle #5 progressive disclosure).

**HXI principles.** #3 (no emoji; inline SVG + mono text; reused `MODE_COLOR` amber/mid-amber/dim palette). #4 (the existing pulse on the camera-live dot communicates the active state; per-agent badges are static text — mode change is color shift, not new motion, to avoid the indicator clobbering the existing 4-corner layout). #5 (per-agent surface appears only when ≥ 2 agents are registered; single-agent deployments unchanged). #9 (engaged amber, ambient mid-amber, dormant dim — eye naturally drawn to engaged agents). #11 (read-only visualization; the agentic engagement path was already wired by AD-733c-5).

**Scope.** UI-only. Backend frozen — zero diff on `src/probos/` or `tests/`. `GET /api/perception/mode` shipped its `per_agent` field in Wave 176; this AD only consumes it.

**Test coverage.** +3 vitest in `ui/src/components/perception/__tests__/CameraLiveIndicator.perAgent.test.tsx`: renders per-agent badges when 2+ entries (asserts amber for engaged, mid-amber for ambient, single MODE badge suppressed); falls back to single MODE badge when `perAgent` < 2 entries (back-compat regression); `PerceptionLivePanel` per-agent table renders one row per entry with mode swatch.

**License posture.** 0-line diff on all 5 license files. Zero new pip / npm deps.

**Forward markers** (filed in roadmap, no GH issues per AD-722c-3):

- AD-733c-5-4-1 — Per-agent manual override buttons in the per-agent table.
- AD-733c-5-4-2 — WebSocket push for per-agent mode changes (currently 2s polling).
- AD-733c-5-4-3 — Callsign rendering in per-agent badges (requires `CallsignRegistry` snapshot in HXI).

### AD-733c-7-5 — HXI Silero VAD browser integration (Wave 177)

**Context.** AD-733c-7 (Wave 176) shipped the backend half of Silero VAD secondary engagement: `POST /api/perception/voice-activity` endpoint, `PerceptionConfig.vad_engagement_enabled` (default False), `scripts/silero-vad-fetch.ps1` operator-pullable model download, MIT attribution in `THIRD_PARTY_LICENSES.md`. But no browser code tapped the mic, ran the model, or POSTed to the endpoint. The feature was a hollow tube end-to-end.

**Decision.** Ship three browser modules + one indicator badge + one App.tsx lifecycle hook:

- `ui/src/audio/silero-vad.ts` — ONNX wrapper. Lazy-loads `onnxruntime-web` via the indirect-string-variable pattern from `wakeWord.ts:268-289` (static import FORBIDDEN — would break first paint for Captains who never enable VAD). Loads the ONNX model from `/data/silero-vad/silero_vad.onnx` (operator-pulled). Honest-degrades to `null` when runtime OR model is absent — the wake-word path remains the primary engagement trigger.
- `ui/src/audio/voiceActivity.ts` — mic-tap + chunked detection loop. Opens a NEW dedicated `getUserMedia({audio: true})` stream (no shared mic-tap exists: `wakeWord.ts` uses SpeechRecognition transcript API; `useCameraStream` requests audio:false). 16 kHz / 30 ms frames; debounce by `vad_min_speech_duration_ms` (default 400); `startVoiceActivity()` / `stopVoiceActivity()` lifecycle; `_processFrame()` exported as a deterministic test seam.
- `CameraLiveIndicator.tsx` SPEECH badge — inline-SVG soundwave glyph + `SPK` label. Conditional render on `snapshot.config.perception.vad_engagement_enabled`. Amber on speech event (1.5s flash), dim otherwise.
- `App.tsx` arms/disarms the loop in sync with the snapshot toggle. Solo-Captain deployments (default vad_engagement_enabled=false) render no audio context, no mic prompt, no first-paint regression.
- `usePerceptionModeStore` extended with `lastSpeechAt: number | null` + `noteSpeechEvent()` — the badge subscribes to the timestamp; `voiceActivity.ts` calls the setter on every confirmed event so the badge flashes regardless of the network round-trip outcome.

**Privacy invariant (AD-733c-7).** Audio bytes NEVER leave the browser. The POST body contains ONLY `{agent?, source}` metadata. Regression test asserts by string-matching: the captured fetch body must NOT contain `audio`, `buffer`, `pcm`, or `base64`.

**HXI principles.** #3 (no emoji; inline stroke SVG soundwave). #4 (flash communicates "event happened"; static-dim communicates "no recent speech"; static-bright would be misleading since it implies real-time mic monitoring). #5 (badge hidden entirely when `vad_engagement_enabled=false`; opt-in surfaces only after Captain restart). #9 (amber flash draws the eye to engagement-precondition events). #11 (passive trigger feeding the agentic engagement path — flow remains agentic: Captain speaks → VAD detects → backend transitions per-agent controller → MODE badges update).

**License posture.** `onnxruntime-web` stays in `optionalDependencies` — 0-line diff. Silero VAD ONNX bytes are operator-pulled. 0-line license diff on all 5 license files.

**Test coverage.** +5 vitest: POSTs on sustained speech (asserts privacy invariant on body); debounces sub-threshold events (window resets on dip below threshold); honest-degrades on 503 (endpointOff latch); releases mic on stopVoiceActivity (track.stop spy); CameraLiveIndicator SPEECH badge (hidden when disabled + flashes amber on event + decays to dim after 1.5s).

**Forward markers** (filed in roadmap, no GH issues per AD-722c-3):

- AD-733c-7-5-1 — Shared mic-tap hook unifying VAD raw audio + wake-word transcription.

### AD-742c-6 — HXI camera multiplexer integration (Wave 177)

**Context.** AD-742c (Wave 176) shipped the backend half of per-agent camera selection: `GET /api/perception/cameras` returning `{bindings}`, `POST /api/perception/cameras/binding {agent_id, device_id}`, and the optional `agent_ids` form field on `/camera/frame`. But the HXI didn't enumerate cameras, render bindings, or open multiple streams — operators had to hand-edit profile JSON or curl the endpoint.

**Decision.** Ship three browser-side pieces:

- `ui/src/store/useCameraMultiplexerStore.ts` — NEW Zustand slice SIBLING of `useCameraStore` (NOT a merger; different endpoints, different lifecycles — SRP wins). Owns `bindings: Record<string, string>` mirrored from backend + `devices: MediaDeviceInfo[]` enumerated browser-side. `refresh()` parallelizes the two halves via `Promise.allSettled` so a browser without `mediaDevices` does not block the backend fetch and vice versa. `bindAgent` / `clearAgent` POST to the binding endpoint and mirror local state on 200.
- `ui/src/hooks/useCameraStream.ts` — EXTENDED (not rewritten — BF-301/302/305 invariants preserved). New optional `deviceId` kwarg on `startCameraStream` adds an `exact` device constraint to `getUserMedia`. New module-level `_activeDeviceId` + `_streams: Map<string, MediaStream>` track multi-device state alongside the existing `_stream`. New `_computeAgentIds()` derives the form-field value from the multiplexer bindings at capture time. Zero-arg call (legacy single-stream path) preserves bit-for-bit behavior — no agent_ids field when bindings are empty.
- `ui/src/components/settings/sections/PerceptionLivePanel.tsx` — CAMERA BINDINGS section. Collapsed by default (HXI Principle #5 progressive disclosure). Per-agent row with device dropdown + clear-binding stroke-X button + REFRESH DEVICES action. `CameraLiveIndicator.tsx` gains a CAMS:N compact label when ≥ 2 distinct devices are bound (single-stream deployments unchanged).

**AD-731 invariant preserved.** `agent_ids` is a STRING list (comma-separated form field), never image bytes. The multipart JPEG continues to be the only byte channel; no inline base64 is introduced.

**HXI principles.** #3 (no emoji; inline SVG glyphs for chevron / clear-X; mono fonts; amber/dim color scheme). #4 (no new motion in v1 — bindings are configuration, not real-time signal; AD-742c-6-1 forward marker for fade-on-unbind). #5 (CAMERA BINDINGS section collapses by default; CAMS:N label surfaces only when ≥ 2 devices bound — solo deployments unchanged). #9 (bound rows render amber; unbound rows render dim — eye drawn to configured bindings). #11 (v1 ships the dropdown as a workstation pattern; the agentic "bind your camera to me" path requires a new intent + tool-permission grant — AD-742c-6-2 forward marker).

**Scope.** UI-only. Backend frozen — zero diff on `src/probos/` or `tests/`.

**Test coverage.** +6 vitest in `ui/src/store/__tests__/useCameraMultiplexerStore.test.ts` (refresh populates both halves in parallel; bindAgent POSTs and mirrors state) + `ui/src/components/settings/sections/__tests__/PerceptionLivePanel.cameraBindings.test.tsx` (section collapsed by default; toggle expands and collapses; dropdown POSTs to /cameras/binding; single-camera deployments render bit-for-bit identical UI). Spec called for +4; the 2 extra tests (toggle round-trip + solo-Captain regression) are boundary coverage on the BF-301/302/305 invariant family.

**License posture.** 0-line diff on all 5 license files. Zero new pip / npm deps.

**Forward markers** (filed in roadmap, no GH issues per AD-722c-3):

- AD-742c-6-1 — Fade-on-unbind animation in CAMERA BINDINGS table.
- AD-742c-6-2 — Agentic bind path ("agent: bind your camera to me") — requires new intent + tool permission grant.


### Wave 178 — see → discuss → act ladder (2026-05-19)

Three ADs lifting ProbOS up the visibility ladder: passive screen sensing
(AD-733-2) feeds ambient situational awareness; explicit share-to-agent
(AD-744) gives the Captain a one-shot "look at THIS" surface; conversation
→ action handoff (AD-745) lets the Captain say "...and click that button
for me" without leaving the DM. Each layer is additive and default-OFF
except where consent is already present in the underlying API
(`getDisplayMedia` browser prompt).

**GATE 1 Captain ruling — consent posture (CRITICAL).** Per-action Captain
ACK on tier-2 (typed input) and tier-3 (destructive) browser actions is
**the canonical posture**, NOT a v1 stopgap. The mesh is forever
human-in-the-loop by default. AD-745-2 forward marker (below) tracks
opt-in "autopilot mode" modeled on GitHub Copilot CLI autopilot
(https://docs.github.com/en/copilot/concepts/agents/copilot-cli/autopilot)
where the operator trades human ACK for multi-agent consensus quorum.
**Quote: "Autopilot mode is an explicit opt-in where the operator trades
human ACK for multi-agent consensus quorum. The quorum REPLACES Captain
ACK; it does not stack."** v1 ships with NO autopilot codepath; the
ACK-skip branch is forward-marker only.

### AD-721j amendment (filed at Wave 178 close)

**Amendment.** AD-721j (Blender Connector computer-use control, #538) is
re-scoped: "Blender as a target application of AD-745-1 DesktopActionTool."
The generic OS-pointer dispatch substrate ships in AD-745-1; AD-721j
becomes a thin domain configuration on top (Blender selector vocabulary,
viewport-aware action grammar). Captain GATE 1 ruling: APPROVED. The
existing AD-721j GH issue remains OPEN as the Blender-domain tracker;
AD-745-1's forward marker now covers the generic substrate.

### AD-733-2 — Passive screen sensing (Wave 178)

**Context.** AD-733 + AD-733a ship per-Captain camera streaming with
VisionConsumer + AD-541b anchor episodes. AD-742c (Wave 176) adds per-agent
camera bindings. But the "screen" was missing — operators could share a
camera frame but not what was on their monitor. Closes #668.

**Decision.** Treat `source` as a first-class form-field discriminator
on the existing `/api/perception/camera/frame` endpoint. Allow-list
`{camera, screen}`; default `camera` for byte-compatible behavior of
every AD-733 caller. Independent enable gate per source
(`perception.camera.enabled` / `perception.screen.enabled`); independent
rate buckets keyed on `(session_id, source)`. Per-source anchor
trigger_type so AD-541b recall can distinguish camera_stream_began from
screen_stream_began.

Browser side: new `useScreenStore` (sibling of `useCameraStore` —
different lifecycle, SRP), new `useScreenStream` hook with
`getDisplayMedia` + `track.onended` auto-stop; CameraLiveIndicator
renders SCREEN LIVE row below CAMERA LIVE when active.

**Scope.** Default-OFF (`screen_sensing_enabled=False`) per Wave 10
convention #14. AD-731 preserved — bytes flow through AttachmentStore,
not inline on the bus.

**Test coverage.** +8 pytest (per-source success/disable/invalid/bucket-
isolation/anchor + AD-731 source-scan + bound_agent_ids regression +
camera byte-compatibility regression); +5 vitest hook tests; +3 vitest
CameraLiveIndicator render tests.

**Forward markers** (filed in roadmap, no GH issues per AD-722c-3):

- AD-733-2-1 — VisionConsumer per-source novelty threshold (camera-novelty
  vs screen-novelty differ — screens are visually static for long
  stretches).
- AD-733-2-2 — Real-time WebRTC screen track (replace multipart upload
  with a long-lived WHIP/WHEP transport) — trigger: Captain demand for
  sub-second screen-update latency.

### AD-744 — Interactive share-to-agent (Wave 178)

**Context.** AD-733-2 ships ambient screen sensing; the most common
operator request is the one-shot "look at THIS" — Captain wants to share
a single frame with a named agent without standing up an ambient stream.
Existing infrastructure (AD-720 AttachmentStore, AD-742c `bound_agent_ids`,
AD-733a BF-302 `force=True` bypass) covers the plumbing; AD-744 composes
them into a single Captain-facing surface.

**Decision.** Reuse the existing `/api/perception/camera/frame` endpoint
(no new server endpoint). The combination `(force=true AND non-empty
agent_ids)` is the explicit-share signal. New
`PerceptionConfig.explicit_share_enabled` (default True — the underlying
`getDisplayMedia` browser prompt provides the per-click consent so
default-on is safe; the toggle is for kiosk operators) gates the
explicit-share path independently of ambient streams. The shared frame
flows through AttachmentStore (AD-731 invariant) and rides on the next
DM turn's `attachment_ids` via existing AD-720/730 plumbing — no new
multimodal wire format.

Browser side: new `useScreenShare` hook (one-shot; `track.stop()` on
EVERY track in `finally` — distinct from AD-733-2's long-lived stream);
stroke-SVG monitor + up-arrow glyph next to the existing paperclip on
the WardRoomThreadDetail DM composer (HXI #3); Tier-2 honest-degrade
returns `null` from the hook on any failure (user cancel, network blip,
server 5xx) — the DM composer text is never clobbered.

**Test coverage.** +8 pytest (happy path, master-off 503, ambient-still-
admits, operator-preview-still-admits, force-flag propagation, distinct
anchor trigger_type, AD-731 source-scan rerun, camera-source share
parity); +6 vitest (getDisplayMedia called once, track stopped after
grab, multipart contents, success payload, getDisplayMedia reject
degrade, 5xx degrade with track release); +3 vitest component tests
(button hidden in non-DM view, visible in DM view, click appends to
pendingAttachments).

**Forward markers** (filed in roadmap, no GH issues per AD-722c-3):

- AD-744-1 — Cross-agent share fan-out (share-to-many). Trigger: Captain
  demand after share-to-one is exercised ≥3 times.
- AD-744-2 — Region masking / redaction before share (important privacy
  primitive). Trigger: Captain shares an inadvertently-sensitive frame
  OR Counselor flags a privacy-bearing observation.
- AD-744-3 — In-HXI preview modal with redact-region affordance.
  Trigger: graduates from AD-744-2 when the redaction primitive is
  approved.

### AD-745 — Conversation → action handoff; browser scope v1 (Wave 178)

**Context.** After AD-744 ships, the Captain can share a screen frame
with an agent. The natural next sentence is "click that button for me."
Today the agent honest-degrades — it can describe what it sees, but has
no path to act. AD-706 already ships the BrowserTool substrate (Playwright
sessions per Captain, AD-706e action vocabulary, AD-706e classifier,
AD-541b anchor episodes per action); AD-745 ships the dispatch layer
that connects a CognitiveAgent's DM reply to BrowserTool.

**Decision (GATE 1 — Captain ruling).** Per-action Captain ACK is the
canonical consent posture. Tier-1 (observation-only: screenshot, state,
scroll, mouse_move) dispatches inline; tier-2 (click, type, drag,
non-destructive key_combo, mouse_button) waits for in-thread Captain
ACK; tier-3 (compute_use_click, eval_js, upload_file, download,
destructive key_combo, ANY verb on URL matching `destructive_url_patterns`)
waits for explicit destructive-confirmation modal. NO autopilot in v1.

Surface: `[ACTION: {"verb":"click","args":{"selector":"#submit"},"intent":"..."}]`
bracket marker on agent DM replies; new `DmReplyPipeline.step_4e_action_dispatch`
between AD-743 4d and BF-296 4b; new `ActionDispatcher` in-memory registry;
new `routers/agent_actions.py` mounted at `/api/browser`:

- `POST /actions/{id}/ack` — tier-2 Captain ACK; calls BrowserTool.invoke
- `POST /actions/{id}/abort` — Captain abort; sets `BrowserSession.aborted=True`
- `GET  /actions/by-thread/{thread_id}` — per-thread action list

Browser side: `ui/src/components/chat/AgentActionLog.tsx` — collapsed by
default per HXI #5; per-entry tier glyph (stroke-density encoded,
a11y-safe — no color reliance); pulse animation on `ack_pending` (1.2s)
and `confirm_pending` (0.6s) per HXI #4; per-action ABORT button.

**AD-731 invariant.** Frame refs (SHA-256 from AttachmentStore) only on
outcomes; before/after_frame_ref slots reserved for the
screenshot-before / screenshot-after audit trail. Source-scan asserts
`b64encode` absent from `action_parser.py`, `action_dispatcher.py`,
`routers/agent_actions.py`.

**AD-541b integration.** Every dispatched action writes an Episode with
`anchors=AnchorFrame(channel="action", trigger_type="agent_action_executed",
trigger_agent=<agent_id>)`. Outcomes carry `verb`, `args_hash` (sha256),
`tier_classified`, `before_frame_ref`, `after_frame_ref`, `result`.

**Scope.** Default-OFF (`action_dispatch_enabled=False`). Per-DM-turn
cap = 1 (AD-745-6 forward marker for multi-step plans). Consecutive-
autonomous cap = 5 (AD-706c-2 Guard #10 generalized across all verbs).
Destructive URL allow-list = 10 fnmatch patterns by default. NO browser
binaries committed — `playwright install chromium` is operator-run.
BrowserSession ALWAYS uses an isolated `user_data_dir`, NEVER Captain's
default profile (AD-745-5 forward marker tracks the consensual
profile-clone exception).

**Test coverage.** +23 pytest (7 parser + 8 pipeline + 3 episode-anchor
+ 5 endpoints); +6 vitest (AgentActionLog component).

**Forward markers** (filed in roadmap, no GH issues per AD-722c-3):

- AD-745-1 — `DesktopActionTool` OS-pointer scope. Absorbs AD-721j
  Blender Connector per Wave 178 Captain ruling. Trigger: Captain shares
  a non-browser surface AND requests action ≥3 times OR Blender demand
  resurfaces post-AD-745 generic substrate.
- AD-745-2 — **Autopilot mode** (opt-in quorum substitution for Captain
  ACK). Modeled on GitHub Copilot CLI autopilot
  (https://docs.github.com/en/copilot/concepts/agents/copilot-cli/autopilot).
  **The quorum REPLACES Captain ACK; it does not stack.** v1 ships with
  NO autopilot codepath; this marker tracks the future opt-in. Trigger:
  Captain demand after exercising tier-2 ACK ≥1 wave.
- AD-745-3 — OmniParser SOM grounding for `compute_use_click` accuracy.
  Trigger: `compute_use_click` failure rate observed ≥20% OR Captain
  demand for canvas/embed grounding.
- AD-745-4 — Pluggable grounding strategy (mirrors AD-742d). Trigger:
  AD-745-3 lands AND operator demand for choice.
- AD-745-5 — Consensual profile-clone (agent acts in a clone of the
  Captain's logged-in profile for the duration of an explicit task).
  Trigger: Captain explicit "use my login" request.
- AD-745-6 — Multi-step action plans per DM turn (plan-level ACK). v1
  caps at 1 action per turn; this marker tracks the batched-ACK
  surface. Trigger: AD-745 v1 exercised ≥1 wave AND Captain demand.
- AD-745-7 — Cross-thread action audit + SQLite persistence of pending
  actions across runtime restart. v1 is in-memory only. Trigger: action
  volume sustained ≥50/wave OR Captain demand for action history
  beyond live thread.

## AD-721b-3 (Wave 179, 2026-05-19) — whisper.cpp WASM tiny.en model bundle

Foundation prompt for the offline-voice stack. Operator-pull script `scripts/whisper-tiny-en-fetch.ps1` writes `ggml-tiny.en.bin` (~75 MB, SHA-256 pinned) + `whisper.js` UMD glue + `whisper.wasm` into `data/whisper/`. Bytes never committed (gitignored under `data/*`). New `ui/src/audio/whisperLoader.ts` lazy-injects the UMD glue via `<script>` tag (NOT ESM `await import()` — whisper.cpp ships UMD per upstream `examples/whisper.wasm/main.js`). Honest-degrades to `null` on any 404. New `src/probos/voice/whisper_model.py` resolves the model path under `runtime.data_dir`. New `CognitiveConfig.whisper_model_path` field (default `whisper/ggml-tiny.en.bin`; restart-required per BF-308). FieldDescriptor registered in the AD-741 LLM Tiers section. NO STT functionality exposed — AD-705a is the consumer. 0-line diff on `THIRD_PARTY_LICENSES.md` (entries land at AD-705a ship). +6 pytest, +5 vitest (3 required + 2 helper-seam checks). Closes #561.

## AD-705a (Wave 179, 2026-05-19) — Offline STT via whisper.cpp WASM

Closed loop on the AD-721b-3 foundation. New `ui/src/audio/whisperStt.ts` arms on `cognitive.offline_stt_enabled = true`; subscribes to the AD-733c-7-5 VAD `subscribePcm` tap; collects PCM between Silero speech_start/speech_end (capped at ~30 s); runs the buffer through `loadWhisperModel().transcribeBuffer`; emits transcript through module-level `onTranscript` listeners; `IntentSurface` subscribes and dispatches through the same `handleSubmit` path keyboard input takes (AD-541b episode anchoring preserved). `voiceActivity.ts` extended with `subscribePcm(handler): () => void` + zero-overhead-when-no-subscribers guarantee + speech-boundary fan-out. `CameraLiveIndicator.tsx` gains a stroke-SVG STT badge with hidden / dim / amber / pulse states (HXI #3 no emoji, HXI #4 motion). Transcript-preview pill in `IntentSurface` between speech_end and transcript dispatch (HXI #5). `CognitiveConfig.offline_stt_enabled: bool = False` (Convention #14 opt-in default; hot-reload via BF-308). +2 THIRD_PARTY_LICENSES.md entries (whisper.cpp MIT + Whisper model weights MIT). Privacy invariant: `whisperStt.ts` source-scanned — zero `fetch(` calls. Audio bytes never leave the browser. Browser-native `SpeechRecognition` Tier-2 fallback preserved (forward marker AD-705a-7 for fully-offline mode). +5 pytest, +8 vitest. Closes #555.
## AD-705c (Wave 179, 2026-05-19) — Custom wake-word training pipeline

Closes the voice cluster. New `src/probos/voice/wake_word_trainer.py` `WakeWordTrainer` wraps the operator-installed openWakeWord training pipeline; runs sync PyTorch in `loop.run_in_executor` per BF-280 (no `asyncio.create_subprocess_*`); honest-degrades to `WakeWordTrainingReport(status='error', error_message=pip-install-hint)` when `import openwakeword.train` raises `ImportError`. New `src/probos/routers/voice.py` exposes three `require_crew_scope` endpoints (`POST /api/voice/wake-word/sample` with WAV magic-byte + size + sample-cap defenses, `POST /api/voice/wake-word/train` with held task reference in `runtime._wake_word_trainer_tasks`, `GET /api/voice/wake-word/training-status`). New `WakeWordConfig` Pydantic block (five fields, all default-off / privacy-preserving). Trained ONNX writes to `runtime.data_dir / wake-word / <filename>` — UI Activate path copies to `ui/public/models/wake-word/` (forward marker AD-705c-5). New `probos wake-word` slash-command (`status / collect / train / test`) wired into `ProbOSShell`. `ui/src/audio/wakeWord.ts:_loadOnnxRuntime` SINGLE-block edit (BF-274): prefers `customModelFilename` (default `captain.onnx`) over the stock community `hey_jarvis_v0.1.onnx` model; reads the filename from `useSettingsStore` snapshot via dynamic import to preserve first-paint posture. New `ui/src/components/wakeword/WakeWordTrainerPanel.tsx` HXI surface — progressive disclosure (HXI #5): only renders when `wake_word.wake_word_trainer_enabled = true`; inline stroke-SVG glyphs (HXI #3); state-machine over idle / uploading / training / complete / error. **No `openwakeword` in `pyproject.toml`** — operator installs separately. +1 `THIRD_PARTY_LICENSES.md` entry (openWakeWord Apache 2.0). Privacy invariant: training audio never leaves the runtime; samples deleted after train unless operator opts in to `retain_training_samples=True`. +12 pytest, +4 vitest. Closes #557.
## AD-790 (drafted, 2026-05-21) — Yeo Desktop first-run setup experience (Claude-Desktop-grade onboarding)

**Status:** drafted. **Parent:** AD-759 (Electron host, SHIPPED Wave 186). **Sibling forward markers:** AD-759a..e (autostart / installer / auto-update / signed installer / CI). **Issue:** #714.

**Problem.** AD-759 shipped the Yeo Electron tray host that wraps the browser HXI. There is no first-run setup experience — opening the packaged app drops the operator into the raw HXI with no orientation, no runtime-connection check UX, no branded welcome, no "you are signed in as X, Yeo will help you with Y" framing. Captain reference benchmark is the Claude for Windows installer→splash→`Get started`→home flow: branded installer with progress, dark welcome splash with product mark + one-line value prop + single primary CTA, then a minimal account/connect step, then the chat home. ProbOS needs equivalent polish for Yeo to feel like a daily-driver app and not a dev tool.

**Decision.** Add a first-run onboarding surface inside the existing `desktop/` Electron workspace (NEW renderer route `#/onboarding`) that runs before the HXI loads on first launch, persists a `firstRunComplete` flag in Electron `app.getPath('userData')/yeo-state.json`, and is re-triggerable via tray-menu `Reset Setup…`. The surface is a 4-step linear flow rendered by the same Vite/React/TypeScript stack the rest of the desktop renderer uses (no new framework):

1. **Welcome** — full-window dark canvas, ProbOS/Yeo wordmark, one-line value prop ("Your crew, ready when you are"), single `Get started` primary button. Matches Claude Desktop welcome shape; ProbOS visual language (amber accent, stroke-SVG mark — HXI Design Principle #3 no emoji).
2. **Runtime connect** — auto-probes `PROBOS_RUNTIME_URL` (default `http://127.0.0.1:8765`); on success shows green "Connected to your local crew"; on failure shows three remediation options (Start runtime / Change URL / Run later). Honest-degrade per AD-732 pattern. No silent retry loops.
3. **Captain Card** — minimal prompt for display name + optional voice/avatar pick (deferred to AD-757 surface if not present yet). Writes to existing Captain-Card store; does NOT introduce a new identity primitive.
4. **Ready** — three suggested first prompts ("Brief me on today", "Read my unread mail", "What's on my calendar") rendered as click-to-send tiles. Tapping any tile completes onboarding, sets `firstRunComplete=true`, and routes to the main HXI with the tile's text pre-populated into the intent surface.

**What this AD is NOT.** Not a re-skin of the HXI. Not a new design system. Not a separate splash window (the splash is a renderer route inside the existing `BrowserWindow`, so single-instance lock + deep-link + Electron lifecycle from AD-759 still hold). Not installer-level branding (that lives at AD-759b/d). Not auto-update onboarding (AD-759c). Not telemetry-consent UX (separate AD, file as forward marker AD-790a if needed). Does NOT call out to the network beyond the local runtime probe.

**Prior-art absorption (pattern only, no code copy).**
- Claude for Windows (product pattern) — installer→splash→`Get started`→home flow; one-line value prop; primary-only CTA; minimal account step. License: proprietary. Absorb the SHAPE only.
- VS Code Welcome page (MIT) — multi-step walkthrough renderer pattern, "complete step" persistence, re-runnable via command palette. Architecture reference only.
- Linear desktop (proprietary) — runtime-connection retry UX with three explicit remediations. Pattern only.

**License posture.** Renderer-only React + existing dependencies. No new npm deps. No new Python deps. No model-weight or font additions. Apache-2.0 / MIT compatible across the board.

**Test plan.** +6 vitest in `desktop/src/renderer/onboarding/OnboardingFlow.test.tsx` (welcome→connect happy, connect failure→remediation, connect failure→change-URL flow, Captain-Card name validation, suggested-prompt tile click pre-populates intent, `firstRunComplete` persists and skips on next launch). +2 vitest in `desktop/src/main/firstRunGate.test.ts` (reads/writes `yeo-state.json`, tray-menu `Reset Setup…` clears flag). No pytest changes (Python runtime unchanged).

**Forward markers.**
- **AD-790a** — Telemetry-consent step inside onboarding (opt-in only; trigger: when any telemetry capability ships).
- **AD-790b** — Installer-side branded progress UI (trigger: AD-759b NSIS installer ships).
- **AD-790c** — Cloud-runtime mode toggle in step 2 (trigger: commercial overlay ships hosted runtime).
- **AD-790d** — Localized onboarding strings (trigger: i18n framework lands).

**Acceptance.** First launch of packaged Yeo presents the 4-step flow. Second launch goes straight to HXI. Tray menu has `Reset Setup…` that clears the flag. All 8 vitest tests green. Manual smoke: package the app, install, run on a clean Windows profile, complete the flow, restart, confirm no re-prompt; trigger Reset, confirm re-prompt. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## AD-825 (Wave 192, 2026-05-22) — Drain-before-cancel shutdown semantics

Closes #760. Inserts a drain phase BEFORE the AD-824 cancel sweep in `startup/shutdown.py` so write-holding background loops (episodic backup, anything that opens a Chroma/SQLite/tar transaction) can finish the current atomic operation cleanly instead of being cancelled mid-write (which is the same pathology AD-819 / AD-822 have to repair on the next boot). New `ProbOSRuntime._drain_tasks: set[asyncio.Task]` registry + `_shutdown_event: asyncio.Event` + `_signal_drain_stop()` helper; `_spawn_background(...)` grows kw-only `drain_on_shutdown: bool = False` parameter that routes the task to `_drain_tasks` instead of the AD-824 `_background_tasks` set. New `MemoryConfig.shutdown_drain_timeout_s` (default 30s, range 1.0..300.0). Drain phase signals the event, awaits `asyncio.wait(_drain_tasks, timeout=shutdown_drain_timeout_s)`, logs WARNING for any task that doesn't drain in time. The AD-824 cancel sweep that runs immediately after now also reaps any drain task that didn't exit cleanly — drain is best-effort, cancel is the fallback. `_episodic_backup_task` migrated to `drain_on_shutdown=True`; its loop body replaces bare `asyncio.sleep(N)` with `asyncio.wait_for(self._shutdown_event.wait(), timeout=N)` + early-exit checks before/after each tar so an in-flight snapshot finishes cleanly. New `DreamScheduler.stop_gracefully(timeout)` (uses `asyncio.shield` so the timeout doesn't cancel the in-flight cycle) called from shutdown Phase 1 BEFORE the explicit `dream_cycle()` so the monitor loop's own cycle cannot collide with the explicit one (concurrent-writer hazard on the same Chroma collection was the suspected cause of today's `consolidation_result=failed` events). `ReconsolidationScheduler` and `FailureDistiller` are passive (no `start()`/`stop()`, no task ownership) and are covered transitively when the in-flight cycle finishes. +7 pytest in `tests/test_ad825_drain_shutdown.py` (drain routing, default routing regression, clean-exit semantics, drain-timeout-falls-through-to-cancel, in-flight-atomic-write-completes, drain-exception-does-not-block-marker, AD-824 sweep regression). Zero new deps.

## AD-826 (2026-05-22) — Whisper-first STT priority

Closes #767. The browser Web Speech API is reliable in Chrome but flaky in Edge / Firefox / Safari (silent session death, empty results, no errors). The AD-705a whisper.cpp WASM path works in every browser that ships WebAssembly + SharedArrayBuffer. Inverting the default — whisper primary, browser SR fallback after 2 empty whisper transcripts — eliminates the cross-browser reliability gap without changing the underlying privacy invariant (audio still stays in the browser). Operators on a single-browser deployment can revert with `cognitive.primary_stt: browser`. New `cognitive.primary_stt: Literal["whisper", "browser"]` (default `whisper`) + `cognitive.fallback_stt_enabled: bool` (default True) in `src/probos/config.py`; both registered in the `llm_tiers` SectionDescriptor for hot-reload. New `GET /api/voice/health` in `src/probos/routers/voice.py` returns `{primary_stt, engine, backend_available, healthy}` — filesystem-only probe via `resolve_whisper_model_path(...)` checking `cognitive.offline_stt_enabled` + on-disk GGML file presence; NO subprocess is created because whisper inference runs in the browser, not the runtime. `ProfileChatTab.tsx` PTT click handler now branches on `voiceHealth.primary_stt`: whisper-primary + healthy arms `whisperStt` first; new `emptyWhisperCountRef` falls through to browser SR after 2 empty whisper transcripts (mirror of AD-760). Whisper-primary + unhealthy honest-degrades to browser SR for the press without consuming any counter (operator asked for whisper but artifacts are missing). Browser-primary preserves the AD-760 path verbatim. Mic button `title` exposes the active engine (`Voice input (whisper)` / `Voice input (browser)`) — text only, no emoji per HXI #3. +8 pytest in `tests/test_ad826_voice_config.py`; +5 vitest in `ui/src/__tests__/ProfileChatTab.ad826.test.tsx`. UI `npm run build` green per BF-279 gate.


## AD-822b (2026-05-23) — Boot-time HNSW file validation (pre-open structural probe)

Closes #755. Adds a read-only structural validation layer that runs in the AD-822 subprocess probe BEFORE `chromadb.PersistentClient(...)` opens the collection. Where AD-822 catches torn-HNSW segfaults by isolating them in a child process, AD-822b prevents the segfault by detecting truncation / header-vs-file inconsistency through cheap file I/O on `header.bin`. Together with AD-820 (unclean-shutdown gating) this forms a three-layer defense: AD-820 detects the bad shutdown last run, AD-822 catches latent corruption that survives gating, AD-822b stops the cases that would otherwise produce SIGSEGV before chroma's native mmap path touches them. New `validate_hnsw_files(data_dir)` in `src/probos/episodic_health.py` walks every UUID-named subdir that contains a `header.bin`, parses the 100-byte chroma-hnswlib header via `struct.unpack("<IQQQQQQiIQQQdQ", ...)` (4-byte u32 version prefix + 13 upstream hnswlib fields in `saveIndex` order — layout verified 2026-05-23 against the preserved corrupted dir at `C:\Users\seang\AppData\Local\ProbOS\data\chroma-corrupted-2026-05-22-150712\`; size_data_per_element=1676 / mult=1/ln(16) / M=16 / maxM0=32 / ef_construction=100 all decoded cleanly), and checks: `cur_element_count <= max_elements`, `size_data_per_element` in `[64, 65536]`, `data_level0.bin` size equals `size_data_per_element * max_elements`, `length.bin` entry count equals `max_elements`, `link_lists.bin` exists (sparse format; size not gated). Each problem accumulates one error string prefixed with the relative path; first-boot data dirs (data_dir missing or no header.bin subdirs) return ok=True since absence is healthy. Wired into `src/probos/_episodic_probe.py` between the `chroma.sqlite3` marker check and `chromadb.PersistentClient` open; on failure the probe writes `hnsw-validation: <error>` lines to stderr and exits 5 (new code reserved alongside AD-822's 0/1/2). `EpisodicHealthResult` gains `file_validation_failed: bool` (default False) and `check_episodic_health` branches on `exit_code == 5` to set it. `EpisodicCorruptionDetected` gains kw-only `file_validation_failed` parameter whose True branch shapes a distinct operator message leading with "HNSW index appears truncated or corrupted (structural validation failed)" and naming `probos rebuild-episodic` / backup restore / skip-envvar options. `_serve` in `__main__.py` threads `_health.file_validation_failed` into the exception. Read-only: never opens `data_level0.bin` (could be hundreds of MB), only the 100-byte `header.bin`; wall time <2ms per dir on warm cache (measured), <50ms gate enforced by the healthy-dir test via `time.perf_counter()`. No new dependencies; no `asyncio.create_subprocess_exec` (uses the existing AD-822 Popen path). +7 pytest in `tests/test_ad822b_hnsw_validation.py` (healthy dir + perf gate, truncated data_level0, missing-header skip, cur>max sanity, missing-data-dir first-boot, end-to-end subprocess exit-5, propagation through `check_episodic_health`). AD-820..826 regression suite (69 tests) remains green.
