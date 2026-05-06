# WAVE 83 DISPATCH — AD-482 v1 Self-Improvement Pipeline (8 sub-ADs in one build)

**Wave id:** 83
**Umbrella AD:** AD-482 (Self-Improvement Pipeline — Discovery to Deployment)
**OSS sub-ADs in scope (concrete build):** AD-482a (Stage Contracts), AD-482b (Capability Proposal Format), AD-482c (Human Approval Gate), AD-482d (Evolution Store), AD-482e (PIVOT/REFINE Decision Loops), AD-482f (QA Agent Pool + Shapley scoring), AD-482g (Agent Versioning), AD-482h (Git-Backed Agent Persistence — `LocalDiskPersistence` default impl)
**OSS sub-ADs in scope (Protocol seam only):** AD-482i (Shadow Deployment — `ShadowDeploymentPolicy` Protocol + `NoOpShadowDeploymentPolicy` default)
**OSS sub-ADs hard-deferred:** none. Captain rule honored — every sub-AD with a consumer at HEAD ships concretely or as a Protocol seam.
**Closes:** GH issue #76
**HEAD at draft:** `ccd1008` (post-Wave-82)
**Baseline test count:** 11614 → expected **≥ 11654** pytest (Δ ≥ +40)
**Builder required:** true (one focused build prompt)
**AD numbering:** Highest stem in trackers at draft is **AD-696** (Wave 72). AD-482 is the umbrella AD pre-allocated at GH #76 creation; sub-ADs 482a–i are pre-allocated by the roadmap entries at `docs/development/roadmap.md:3665-3732`. **No new AD number is minted by this wave.**

## Verdict

Verify-first against HEAD `ccd1008` confirms the substrate AD-482 v1 needs is in place:

- **`SelfModificationPipeline` (AD-265, AD-368):** `src/probos/cognitive/self_mod.py:42` `class SelfModificationPipeline`; `:27` `@dataclass DesignedAgentRecord` (status field has `active|removed|failed_validation|rejected_by_user`); `:69` `user_approval_fn: Callable[[str], Awaitable[bool]] | None`; `:74` `dependency_resolver` ctor kwarg. ApprovalGate v1 wraps/replaces this hook for the proposal queue surface; designed-agent flow remains the v1 consumer, with capability proposals as the broader audience.
- **`SystemQAAgent` (AD-156):** `src/probos/agents/system_qa.py:1` smoke-tests newly designed agents post-self-mod. Already a single-instance utility agent registered as a pool template in `runtime.py:619`. v1's `QAAgentPool` reuses the existing template and adds Shapley contribution scoring; no behavioral test infra is rewritten.
- **Shapley scoring:** `src/probos/consensus/shapley.py:37` `compute_shapley_values(votes, approval_threshold, use_confidence_weights)` — used by quorum today. v1's QA-pool aggregator constructs synthetic `Vote` records (one per QA agent) keyed on `outcome_pass_count` to feed the same function. No new Shapley implementation.
- **`EpisodicMemory` ChromaDB pattern:** `src/probos/cognitive/episodic.py:651` `class EpisodicMemory`; `:732` `chromadb.PersistentClient(path=...)` + `get_or_create_collection(name="episodes", embedding_function=ef, metadata={"hnsw:space": "cosine"})`. v1's `EvolutionStore` mirrors this construction shape on a `lessons` collection with a `time-decay` ranking on top of cosine similarity. Same `chromadb` dependency; no new vector DB.
- **`ArchitectProposal` (AD-306):** `src/probos/cognitive/architect.py:30` `@dataclass ArchitectProposal(title, summary, rationale, build_spec, roadmap_ref, priority, dependencies, risks)`. v1's `CapabilityProposal` is a typed sibling — same dataclass shape, different schema (source/relevance/fit/effort/license fields per roadmap line 3672). The two never replace each other; ArchitectProposal stays for Architect's BuildSpec output, CapabilityProposal serves discovered-capability flow.
- **`RecordsStore` workspace files (AD-594a):** `src/probos/knowledge/records_store.py` `write_workspace_file` / `read_workspace_file` / `append_workspace_file` (Wave 44). v1's `LocalDiskPersistence` writes promoted agent source to `src/probos/agents/designed/{agent_type}_v{version}.py` directly (NOT through workspace files — designed agents are runtime imports, not workspace artifacts). Sidecar metadata file `{agent_type}_v{version}.meta.yaml` carries provenance.
- **`runtime._chroma_client`:** verified present via Wave 36/49 episodic + semantic plumbing. v1's `EvolutionStore` opens its own collection on the shared client (no new persistent path).
- **No `src/probos/agents/designed/` directory at HEAD:** `Test-Path` returns False — v1 creates the directory lazily in `LocalDiskPersistence.promote(record)`. No existing files conflict.
- **No `src/probos/cognitive/self_improvement/` package at HEAD:** `Test-Path` returns False — collision-free greenfield package.
- **No EventTypes named `CAPABILITY_PROPOSAL_*`, `PIVOT_REFINE_*`, `EVOLUTION_LESSON_*`, `AGENT_VERSION_*` at HEAD:** verified via `grep`. v1 introduces 6 new event types adjacent to the AD-633 prediction events at `src/probos/events.py:67-70`.
- **Architect already has `ArchitectProposal` shape;** v1 does NOT route through Architect for capability proposals. Capability proposals come from any agent that finds an external capability (research agent, code reviewer, scout) and feeds them via `runtime.proposal_store.submit(proposal)`. ApprovalGate decouples acceptance from designer wiring.

AD-482 v1 (eight concrete sub-ADs + one Protocol seam + zero hard-deferrals) is **fully buildable in one wave**. Captain rule "don't defer unless no choice" is honored: every sub-AD with a consumer at HEAD ships concretely; Shadow Deployment ships as a Protocol seam because the consumer (parallel pool comparator with scaler-aware shadow workers) is non-trivial standalone infra (its own AD, AD-482i-1).

| GH #76 sub-AD | Wave 83 action |
|---|---|
| AD-482a Stage Contracts (typed I/O for handoffs) | **BUILD.** New `src/probos/cognitive/self_improvement/stage_contract.py`. Frozen `StageContract(name, inputs, outputs, definition_of_done, error_codes, max_retries)` dataclass + `validate_input(payload) -> tuple[bool, str]` / `validate_output(payload) -> tuple[bool, str]` shape-only validators (no runtime type coercion — AD-685c-style structural check). Pure data; no I/O. |
| AD-482b Capability Proposal Format | **BUILD.** New `proposal.py`. Frozen `CapabilityProposal(id, source, source_url, summary, relevance, fit_assessment, integration_effort_hours, dependencies, license, submitted_at, submitter_agent_id)` + `ProposalStore` in-memory append-only registry with `submit(proposal) -> str`, `get(id) -> CapabilityProposal \| None`, `list_pending() -> list[CapabilityProposal]`, `update_state(id, decision, rationale) -> bool`. Persists to ChromaDB-backed evolution store on terminal decisions (lessons learned). |
| AD-482c Human Approval Gate | **BUILD.** New `approval_gate.py`. `ApprovalGate(*, proposal_store, event_emit_fn, clock=time.time)` exposes `enqueue(proposal) -> str`, `pending_count() -> int`, `approve(proposal_id, *, approver, modifications=None) -> bool`, `reject(proposal_id, *, approver, reason) -> bool`. Emits `CAPABILITY_PROPOSAL_APPROVED` / `CAPABILITY_PROPOSAL_REJECTED` events with full audit trail. Wraps the existing `SelfModificationPipeline._user_approval_fn` shape — designed-agent flow can keep its bool callback OR route through ApprovalGate (operator choice via config). |
| AD-482d Evolution Store (append-only lessons) | **BUILD.** New `evolution_store.py`. `EvolutionStore(*, chroma_client, collection_name="self_improvement_lessons", clock=time.time, half_life_seconds=2592000.0)` (30-day half-life default). Public API: `record_lesson(category, summary, source_proposal_id, outcome, payload) -> str`, `recall(query, *, top_k=5, now=None) -> list[Lesson]` with time-decay weighting `weight = similarity * 0.5 ** ((now - lesson.timestamp) / half_life)`. Mirrors `EpisodicMemory.__init__` ChromaDB construction shape. Tier-2 log-and-degrade on chroma absence. Emits `EVOLUTION_LESSON_RECORDED`. |
| AD-482e PIVOT/REFINE Decision Loops | **BUILD (in `proposal.py`).** `PivotRefineDecision(str, Enum)` with values `PROCEED`/`REFINE`/`PIVOT`. Frozen `IterationGuard(max_iterations: int, decisions: list[tuple[float, PivotRefineDecision]])` dataclass with `register(decision) -> bool` (returns False when cap exceeded; never raises) and `record_artifact(artifact_id, content_hash) -> str` for revision provenance. `ProposalStore.transition(id, decision)` enforces `IterationGuard.max_iterations` and emits `PIVOT_REFINE_DECIDED`. |
| AD-482f QA Agent Pool + Shapley scoring | **BUILD.** New `qa_pool.py`. `QAAgentPool(*, qa_template, pool_factory, shapley_fn=compute_shapley_values, target_pool_size=3)` constructs N `SystemQAAgent` instances behind a thin coordinator. `evaluate_proposal(proposal, *, candidate_record) -> QAEvaluation` runs all QA agents on the candidate, computes per-agent contribution via `compute_shapley_values` over their pass/fail votes (synthetic `Vote` records keyed on `outcome_pass_count` and `confidence`), and emits behavioral + regression + performance fields. Default `target_pool_size=3` = small pool (Shapley exact under MAX_EXACT_SHAPLEY=8). |
| AD-482g Agent Versioning | **BUILD.** New `versioning.py`. Frozen `AgentVersion(version: int, parent_version: int \| None, designed_at: float, designer: str, trust_alpha_at_promotion: float, trust_beta_at_promotion: float, source_hash: str, persisted_path: str \| None)` dataclass. `AgentVersionStore(records_store=None)` in-memory dict keyed on `agent_type` with `register_version(agent_type, version) -> int`, `latest(agent_type) -> AgentVersion \| None`, `history(agent_type) -> list[AgentVersion]`. Optional `RecordsStore` write-through for persistence (workspace file `agent_versions/{agent_type}.yaml`). Emits `AGENT_VERSION_PROMOTED`. |
| AD-482h Git-Backed Agent Persistence — `LocalDiskPersistence` | **BUILD.** In `versioning.py` (companion class). `AgentPersistence` Protocol with one method `async def promote(record: DesignedAgentRecord, version: AgentVersion) -> str` (returns persisted path or empty string on degrade). `LocalDiskPersistence(*, root_dir="src/probos/agents/designed", clock=time.time)` writes `{agent_type}_v{version}.py` (clean source) plus `{agent_type}_v{version}.meta.yaml` sidecar (designer/trust/source_hash/parent_version). Tier-2 log-and-degrade on FileExistsError / OSError → returns `""`. Git PR creation is the AD-482h-1 follow-on (Builder + GitHub MCP integration is its own AD; v1 ships disk write only). |
| AD-482i Shadow Deployment | **PROTOCOL SEAM.** `versioning.py` adds `ShadowDeploymentPolicy` Protocol (`async def shadow_compare(*, baseline_version, candidate_version, runtime) -> ShadowComparisonResult \| None`) + `NoOpShadowDeploymentPolicy` (always returns `None`). Stable dispatch entry point `runtime.shadow_deployment_policy.shadow_compare(...)` for AD-482i-1 follow-on. Forcing function: parallel pool comparator with scaler-aware shadow workers needs its own AD; v1 ships the seam so versioning can call it without breaking when concrete impl arrives. |
| Pydantic config | **BUILD.** `SelfImprovementConfig` Pydantic model + field on `SystemConfig`. **Default-False** (operator opt-in — QA pool spawns real agents, evolution store opens a chroma collection, persistence writes new files; AD-633 / AD-695 default-False precedent applies). |
| Finalize wirer | **BUILD.** `_wire_self_improvement(*, runtime, config) -> bool` invoked immediately after `_wire_predictive_branching` (AD-633). Gated on `runtime._chroma_client` AND `runtime.spawner`; records_store optional (degrades VersionStore to in-memory only). Sets `runtime.proposal_store`, `runtime.approval_gate`, `runtime.evolution_store`, `runtime.qa_agent_pool`, `runtime.agent_version_store`, `runtime.agent_persistence`, `runtime.shadow_deployment_policy` as public typed attributes (Wave 5 conv #1). Tier-2 log-and-degrade. |

## Reframe decision (Captain rule applied)

**Eight concrete + one Protocol seam + zero hard-deferrals.** Strictest application of "don't defer unless no choice" the wave queue has seen since Wave 82.

Three things that LOOK like deferrals but aren't:

1. **AD-482h Git-Backed Persistence ships as concrete `LocalDiskPersistence`.** The roadmap's full vision (write-to-disk + git branch + PR + Co-Authored-By tag) is a workflow, not a single class. v1 ships the disk-write half (`src/probos/agents/designed/{agent_type}_v{version}.py` + sidecar) which is the foundational consumer for everything else. Git PR creation needs a working `subprocess git` integration AND a GitHub MCP wiring; both have viable implementations at HEAD but together exceed the 40-test budget. AD-482h-1 follow-on closes git/PR; v1 emits `AGENT_VERSION_PROMOTED` events the Git layer will subscribe to. Captain rule honored — disk write is real, not a stub.

2. **AD-482i Shadow Deployment ships as Protocol seam.** Concrete shadow deployment requires running two pool versions in parallel, capturing per-intent Shapley contributions, and a comparator that statistically distinguishes "candidate is better" from "candidate is noise." That is a scaler-aware pool refactor (AD-280 territory) plus a comparator AD. Shipping the comparator without scaler integration ships unreachable code (the comparator can never see two versions running). Same Protocol-seam pattern Wave 82 used for `IdleSpeculationPolicy` and `PreplayHook`. NoOp default + stable dispatch entry point + AD-482i-1 forcing function in module docstring.

3. **AD-482f QA Agent Pool reuses `SystemQAAgent`.** Roadmap calls for "automated validation agents that go beyond pytest" — `SystemQAAgent` ALREADY does behavioral testing, regression detection, and performance benchmarking (`src/probos/agents/system_qa.py`). What was missing was a *pool* and a *Shapley aggregator*. v1 wraps the existing template into a 3-agent pool and adds the Shapley layer. No new QA agent class.

GH #76 closure note: "Closed by Wave 83 (eight concrete OSS sub-ADs 482a/b/c/d/e/f/g/h + one Protocol seam 482i). No premium-feature specs (umbrella is fully OSS — Stage Contracts, Capability Proposals, Approval Gate, Evolution Store, PIVOT/REFINE, QA Pool, Versioning, LocalDiskPersistence all ship as runtime primitives). AD-482h-1 (Git PR creation) and AD-482i-1 (parallel-pool shadow comparator) are forcing-function follow-ons. Captain rule honored — zero hard-deferrals."

## Commercial-leak audit (pre-commit hook safety)

**Banned token sweep on draft** (`prompts/WAVE-83-DISPATCH.md` + `prompts/ad-482-self-improvement-pipeline-v1.md`):

- Banned phrase #1 (the e-word + tier) — **0 hits.**
- Banned phrase #2 (the private commercial repo path token) — **0 hits.**
- `pricing` / `revenue` / `Great Artists Steal` — **0 hits.**
- AD-482 sub-AD scope is fully described in the public roadmap at `docs/development/roadmap.md:3665-3732` (no `*(Commercial)*` tags on any sub-AD letter). Public-OSS framing safe to inline.
- "Premium-feature specs" / "private commercial repo" used only in the closure-note paragraph of GH #76 (no architectural detail) — the GH issue body itself is public, but the wording avoids the banned phrases.

**Verdict:** clean. Pre-commit hook will not trip on this wave's artifacts.

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  ccd1008

# Highest AD stem at HEAD (no new AD minted by this wave):
PROGRESS.md / progress-era-4-evolution.md
  AD-696 (Wave 72 Oracle agentic retrieval — last assigned)
  AD-695 (Wave 73 default-False precedent)

# AD-482 sub-AD letters pre-allocated by roadmap (verify-first quote):
docs/development/roadmap.md:3665    "Stage Contracts (Typed Agent Handoffs) (AD-482)"
docs/development/roadmap.md:3671    "Capability Proposal Format (AD-482)"
docs/development/roadmap.md:3677    "Human Approval Gate (AD-482)"
docs/development/roadmap.md:3684    "QA Agent Pool (AD-482)"
docs/development/roadmap.md:3692    "Evolution Store (AD-482)"
docs/development/roadmap.md:3699    "PIVOT/REFINE Decision Loops (AD-482)"
docs/development/roadmap.md:3720    "Agent Versioning + Shadow Deployment (deferred from Phase 14c) (AD-482)"
docs/development/roadmap.md:3732    "Git-Backed Agent Persistence (AD-482)"

# Existing self-mod substrate (verified shipped):
src/probos/cognitive/self_mod.py:27       # @dataclass DesignedAgentRecord
src/probos/cognitive/self_mod.py:42       # class SelfModificationPipeline
src/probos/cognitive/self_mod.py:69       # user_approval_fn: Callable[[str], Awaitable[bool]] | None

# Existing QA + Shapley (verified shipped):
src/probos/agents/system_qa.py:1          # SystemQAAgent — smoke-tests new agents
src/probos/runtime.py:619                 # spawner.register_template("system_qa", SystemQAAgent)
src/probos/consensus/shapley.py:37        # def compute_shapley_values(votes, approval_threshold, use_confidence_weights)

# Existing ChromaDB pattern (verified shipped):
src/probos/cognitive/episodic.py:651      # class EpisodicMemory
src/probos/cognitive/episodic.py:732      # chromadb.PersistentClient(path=...)
src/probos/cognitive/episodic.py:735      # get_or_create_collection(name="episodes", embedding_function=ef, metadata={"hnsw:space": "cosine"})

# Existing Architect proposal shape (sibling, NOT replaced):
src/probos/cognitive/architect.py:30      # @dataclass ArchitectProposal

# Wirer insertion site (immediately after AD-633 wiring):
src/probos/startup/finalize.py:2521       # _wire_predictive_branching(runtime=runtime, config=config)

# Pydantic config insertion site (adjacent to AD-633 config):
src/probos/config.py:1061                 # class PredictiveBranchingConfig(BaseModel)

# EventType insertion site (adjacent to AD-633 prediction events):
src/probos/events.py                      # PREDICTION_HIT/MISS/FLUSHED/ERROR_RECORDED block

# Greenfield (verified absent — no collision):
src/probos/cognitive/self_improvement/    # NOT PRESENT
src/probos/agents/designed/               # NOT PRESENT
runtime.proposal_store / runtime.approval_gate / runtime.evolution_store / runtime.qa_agent_pool /
runtime.agent_version_store / runtime.agent_persistence / runtime.shadow_deployment_policy
                                          # 0 grep hits at HEAD
```

## In-scope vs already-shipped delta

| Sub-AD | What ships in this wave | What was already shipped (NOT re-implemented) |
|---|---|---|
| 482a Stage Contracts | New frozen dataclass + shape validators | None — greenfield |
| 482b Capability Proposal Format | New `CapabilityProposal` + `ProposalStore` | `ArchitectProposal` (sibling, different schema, kept); `BuildSpec` (Architect/Builder hand-off, kept) |
| 482c Human Approval Gate | New queue surface with persistence | `SelfModificationPipeline._user_approval_fn` (kept; ApprovalGate is wrapper, not replacement) |
| 482d Evolution Store | New ChromaDB-backed lessons store w/ time-decay | None — greenfield (separate collection from `episodes`) |
| 482e PIVOT/REFINE Loops | New enum + `IterationGuard` + transition method | None — greenfield |
| 482f QA Agent Pool + Shapley | New pool wrapper + Shapley aggregator | `SystemQAAgent` template (reused as-is); `compute_shapley_values` (reused as-is) |
| 482g Agent Versioning | New `AgentVersion` + `AgentVersionStore` | `DesignedAgentRecord.status` field (kept; versioning is parallel layer) |
| 482h `LocalDiskPersistence` | New disk-write impl writing to `src/probos/agents/designed/` | Git PR layer is AD-482h-1 follow-on (out of scope) |
| 482i Shadow Deployment | Protocol seam + NoOp default | Concrete impl is AD-482i-1 (parallel-pool comparator AD) |
| Pydantic + wirer + EventTypes | `SelfImprovementConfig` + `_wire_self_improvement` + 6 EventTypes | None — greenfield |

## Gate 1 concerns (architect's attention before Builder runs)

1. **EvolutionStore embedding model collision.** `episodic.py:732` opens collection `"episodes"`; v1 opens `"self_improvement_lessons"` on the same client. Both use `get_embedding_function()` from `probos.knowledge.embeddings`. Verify the embedding-function-mismatch handler at `episodic.py:746-762` doesn't trip when both collections coexist (the conflict guard is per-collection, so it should be safe — but Builder must run a 1-test integration check that opens both and verifies neither flips to `__ef_conflict__` mode).

2. **`SystemQAAgent` pool sizing.** Existing template registers a single instance via `spawner.register_template("system_qa", SystemQAAgent)` at `runtime.py:619`. v1's `QAAgentPool(target_pool_size=3)` requests 3 instances. Builder must confirm the spawner/scaler can produce 3 instances of a utility-tier template OR the pool falls back to size 1 and emits a WARNING (degraded — but Shapley with N=1 is `{agent: 1.0}`, still valid). Pre-flight test should assert both paths.

3. **`runtime._chroma_client` access pattern.** Wirer reads `getattr(runtime, "_chroma_client", None)`. Verify-first against HEAD: this attribute IS set during cognitive bootstrap (Wave 36/49 plumbing). Tier-2 log-and-degrade if absent — `EvolutionStore` skips ChromaDB and stores lessons in an in-memory list (degraded mode). Single test asserts both paths.

4. **`AgentPersistence` Protocol vs the `Callable` register/create pool functions.** `SelfModificationPipeline` already takes `register_fn` / `create_pool_fn` / `set_trust_fn` as `Callable` (not Protocols). New `AgentPersistence` introduces a Protocol shape. This is intentional — the pipeline's existing callbacks predate the Protocol pattern; new abstractions use Protocols per Engineering Principles "Interface Segregation." Do NOT refactor `SelfModificationPipeline`'s ctor signature in this wave.

5. **`ShadowDeploymentPolicy.shadow_compare` is async.** Other Protocol seams in this codebase (`IdleSpeculationPolicy`, `PreplayHook`) are sync. v1's shadow comparator must be async because future concrete impls await `runtime.spawner` / `runtime.pools` / `runtime.event_log` reads. NoOp default is `async def shadow_compare(...): return None`. Verify the Builder doesn't accidentally make it sync.

6. **`docs/development/roadmap.md:3720` mentions "deferred from Phase 14c"** for Versioning + Shadow Deployment. AD-177 (persistent agent identity) is referenced as a dependency in roadmap; verify-first against HEAD shows AD-177 IS shipped (DesignedAgentRecord persists across restart per Wave 1). No further dependency check needed.

## Files

| Path | Action |
|---|---|
| `prompts/WAVE-83-DISPATCH.md` | NEW (this file) |
| `prompts/ad-482-self-improvement-pipeline-v1.md` | NEW |
| `prompts/wave-plan.yaml` | APPEND wave 83 entry |
| `src/probos/cognitive/self_improvement/__init__.py` | NEW |
| `src/probos/cognitive/self_improvement/stage_contract.py` | NEW (482a) |
| `src/probos/cognitive/self_improvement/proposal.py` | NEW (482b + 482e) |
| `src/probos/cognitive/self_improvement/approval_gate.py` | NEW (482c) |
| `src/probos/cognitive/self_improvement/evolution_store.py` | NEW (482d) |
| `src/probos/cognitive/self_improvement/qa_pool.py` | NEW (482f) |
| `src/probos/cognitive/self_improvement/versioning.py` | NEW (482g + 482h + 482i) |
| `src/probos/events.py` | MODIFY (+6 EventTypes) |
| `src/probos/config.py` | MODIFY (+`SelfImprovementConfig`, +`SystemConfig.self_improvement` field) |
| `src/probos/startup/finalize.py` | MODIFY (+`_wire_self_improvement`, +invocation after AD-633 wiring) |
| `src/probos/runtime.py` | MODIFY (+7 public typed attribute declarations) |
| `tests/test_ad482_self_improvement.py` | NEW (~42 tests across 9 classes) |

## Expected delta

- **Pytest baseline:** 11614 → ≥ 11654 (+40 floor; 42 tests planned).
- **No vitest delta** (HXI surface deferred).
- **No new agent template** (QAAgentPool reuses `SystemQAAgent` template at `runtime.py:619`).
- **No new Intent** (capability proposals are submitted via direct `runtime.proposal_store.submit(...)` API; no decomposer integration in v1 — that's AD-482-HXI follow-on).
- **No router** (no `/api/proposals` endpoint in v1; HXI surface follow-on).
- **No LLM call inside any v1 module** (Stage validation is shape-only; QA pool delegates to existing `SystemQAAgent`; EvolutionStore uses ChromaDB embedding function only).
- **6 new EventTypes:** `CAPABILITY_PROPOSAL_CREATED`, `CAPABILITY_PROPOSAL_APPROVED`, `CAPABILITY_PROPOSAL_REJECTED`, `PIVOT_REFINE_DECIDED`, `EVOLUTION_LESSON_RECORDED`, `AGENT_VERSION_PROMOTED`.

## Review passes (this dispatch)

### Pass 1 — Verify-first sweep

- [x] Highest AD-696 confirmed via grep on PROGRESS.md + era files. No new number minted.
- [x] AD-482 sub-AD letters a-h sourced from roadmap.md:3665-3732 (no commercial tags on any sub-AD letter).
- [x] HEAD `ccd1008` matches user-provided value.
- [x] Baseline 11614 matches user-provided value.
- [x] All claimed source anchors (self_mod.py:27/42/69, system_qa.py:1, runtime.py:619, shapley.py:37, episodic.py:651/732/735, architect.py:30, finalize.py:2521, config.py:1061) verified by direct file reads or grep.
- [x] Greenfield collision-checks for `self_improvement/` package, `agents/designed/` directory, and 7 runtime attribute names — all 0 hits at HEAD.

### Pass 2 — Anti-pattern sweep

- [x] No `getattr(obj, "method", None)` for APIs introduced by this prompt (all new APIs are Protocols or concrete classes; consumers depend on the Protocol shape).
- [x] No `else: # Only for unit tests` fallback branches in any new ctor.
- [x] No bare mutable defaults — all `dict`/`list` fields use `Field(default_factory=...)` (Pydantic) or `field(default_factory=...)` (dataclass).
- [x] No frozen dataclass field-ordering errors — all defaulted fields come AFTER non-defaulted in `StageContract`, `CapabilityProposal`, `AgentVersion`.
- [x] No private-attribute access across module boundaries — wirer reads `runtime._chroma_client` (existing convention, AD-686) and `runtime.spawner` (public). All new attributes (`runtime.proposal_store` etc.) are public per Wave 5 conv #1.
- [x] No phantom APIs — every claimed method on existing classes (`compute_shapley_values`, `chromadb.PersistentClient`, `get_or_create_collection`, `SystemQAAgent`, `runtime.spawner`, `EpisodicMemory`) verified at the cited line numbers.
- [x] `requires_consensus=True` is N/A — no new IntentDescriptors in this wave.
- [x] Trust storing raw (alpha, beta) is N/A — `AgentVersion.trust_alpha_at_promotion` / `trust_beta_at_promotion` store raw Beta params, not derived means. Conformant.
- [x] Layer discipline — `self_improvement/` package lives in `cognitive/` and may import from `consensus/` (Shapley) and `knowledge/` (records_store, chromadb embeddings). No imports from `experience/` (HXI surface deferred). Conformant.
- [x] Episodic completeness — every transition emits an EventType so the journal captures the proposal lifecycle. Conformant.
- [x] Async hygiene — `ShadowDeploymentPolicy.shadow_compare` is async (called from async wirer / async runtime); no fire-and-forget `create_task()` in new code.

### Pass 3 — Reframe vs Captain rule

- [x] Eight sub-ADs ship concretely (a/b/c/d/e/f/g/h). One ships as Protocol seam (i). Zero hard-deferrals.
- [x] AD-482h reframe (LocalDiskPersistence concrete; Git PR follow-on AD-482h-1) is justified by 40-test budget plus need for working `subprocess git` + GitHub MCP wiring as separate AD. Disk write is real consumer-ready code, not a stub.
- [x] AD-482i Protocol seam justified by parallel-pool comparator + scaler-aware shadow workers being a standalone AD (AD-280 territory). NoOp default + stable dispatch entry point + AD-482i-1 forcing function in module docstring.
- [x] AD-482f scope respects "QA pool" intent — wraps existing `SystemQAAgent` (which already does behavioral/regression/performance) and adds Shapley aggregator. No new QA implementation.
- [x] AD-482b respects "capability proposal" distinct from `ArchitectProposal` — different schemas, different submitters. Both kept.
- [x] AD-482c respects "approval gate" beyond existing `_user_approval_fn` — adds queue, audit trail, modifications support, terminal-decision lesson recording. Wraps not replaces.

### Pass 4 — Commercial-leak audit

- [x] Banned phrase #1 (e-word + tier) — 0 hits in dispatch + prompt (pre-commit safe).
- [x] Banned phrase #2 (private commercial repo path token) — 0 hits in dispatch + prompt (pre-commit safe).
- [x] AD-482 has zero `*(Commercial)*` tags on any sub-AD in the roadmap — full umbrella is OSS.
- [x] Closure note for GH #76 uses "premium-feature specs" / "private commercial repo" wording (architect-mode rule), not the trip-wire phrases.
- [x] No pricing/revenue/migration-vertical/Great-Artists-Steal text introduced.

**Wave 83 dispatch approved by architect for Builder execution.**
