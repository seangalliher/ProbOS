# EPIC — The Cognitive Mesh as a shared knowledge fabric (Σ)

**Repo: OSS (`d:\ProbOS`). AD ceiling at drafting: AD-1133 shipped (`DECISIONS.md`); AD-1134–1137 assigned to backlog issues #1053–#1056. This epic claims AD-1138 → AD-1143. BF ceiling: `PROGRESS.md` says BF-673, but **BF-674 is already claimed by uncommitted in-flight work** (`tests/test_bf674_llm_endpoint_cooldown.py`) — verified next free top-level = **BF-675**, which is the prerequisite fix. GitHub: epic #1057, children #1058–#1064.**

Give ProbOS crew a shared, classified, semantically searchable knowledge commons that agents can both consult and contribute to — without weakening sovereign per-agent memory, and without any Σ content reaching an agent unframed.

---

## The one-sentence outcome

> ProbOS crew agents stop starting from zero every session — each keeps its own sovereign private mind, but publishes what it learns into a classified, semantically searchable ship-wide commons and consults that commons mid-task, so a finding from last month's session shows up in today's work, and an ablation harness proves the collaboration is what made the difference.

## Why this is the right next investment

The Nooplex defines a Cognitive Mesh as `M = ⟨A, Σ, K, E, Φ, Ω, Ψ⟩` (§3.1). **A** is the autonomous agent "maintaining its own internal state" — that is sovereignty (AD-397). **Σ** is the shared memory fabric, "accessible to all agents," explicitly contrasted with "message-passing architectures where information is ephemeral."

Teilhard's three conditions for a noosphere (§3) are complexity of units, connectivity between them, and a reflective layer. **ProbOS has invested heavily in units and reflection and under-built connectivity.** Sovereignty was correctly applied to **A** and then over-applied, starving **Σ**.

Concretely, the crew execution path added by AD-1124→1133 is the exact pattern §3.1 defines itself against: children receive `task_text` and run in `asyncio.Semaphore` isolation (`src/probos/cognitive/crew_executor.py:890`, `:482`), with the finalizer as the sole convergence point. Child results are written to the shared room (`:1383`) but children never read anything shared.

## Current state → after state

| Dimension | Current | After this epic |
|---|---|---|
| Σ discoverability | Keyword overlap only — `sum(1 for w in query_words if w in raw_lower)` (`records_store.py:837`) | Embedding retrieval with classification-scoped filtering |
| Agent access to Σ | Passive injection only, `Rank.SENIOR` only, only during `perceive` (`cognitive_agent.py:9296`, `earned_agency.py:62`) | Any crew agent can query Σ deliberately, mid-task, through a governed tool |
| Agent contribution to Σ | None. `write_semantic` (AD-686b) is for system artifacts | `publish_finding` writes a classified, provenance-stamped record |
| Crew children | No `records_store`, no Oracle in their tool set | Consult the commons before working; publish findings after |
| Cross-session learning | None — every session starts cold | Prior findings are retrievable by any authorised agent |
| Long-goal ceiling | 25 iterations, no compaction, full history reflattened each turn (`agentic_loop.py:138`) | Compaction extends the horizon; durable trace preserved |
| Evidence of value | Assertion | Measured with/without-Σ ablation (§8.3) |

## What already exists (reuse, do not rebuild)

- **Ship's Records (AD-434) is Σ**, with the noosphere publication model already implemented: `_CLASSIFICATION_LEVELS = {"private":0,"department":1,"ship":2,"fleet":3}` (`records_store.py:27`); `read_entry` enforces it (`:706`); `publish()` promotes scope (`:797`); `search(query, scope)` filters by level (`:841`); AD-554 already scans other agents' notebooks for convergence (`:495`).
- **The Oracle (AD-462e) is the federated query layer** over seven tiers — episodic, records, operational, archive, semantic, graph, health. It is §3.2's `q_F` implemented one level down (across tiers rather than across meshes), and the `tiers` parameter is structurally the `2^ℳ` subset selector.
- **Governed-tool pattern**: `_register_event_log_query_tool` with `allowed_departments` + per-rank `default_permissions` (`startup/communication.py:40`), offered via `registry.check_permission(...)` (`agentic_dispatch.py:882`).
- **Shared classification vocabulary** spans `records_store`, `knowledge/edges.py`, `knowledge/edge_classification.py`, `security/classification.py`, `config.py:5688`, and `federation_recall_agent.py:151`. **Reuse it; do not invent a new scoping model.**
- **Commons curation** already exists: `knowledge_linter`, `notebook_quality`, AD-551 dreaming consolidation.

---

## Pinned epic decisions

### DD-1 — Sovereignty is enforced structurally and is NOT relaxed by this epic
Agent-initiated Oracle calls pass the agent's own id, routing to `recall_weighted` → `recall_for_agent_scored`, which hard-filters on both retrieval axes (`episodic.py:3714`, `:3892`). `_filter_by_access_policy` states the boundary: *"Non-episodic results (records, semantic, graph, health) pass through unchanged because they are not associated with a sovereign shard"* (`oracle_service.py:596`). **Tier 1 = A. Tiers 2–7 = Σ.** Enriching Σ therefore carries no sovereignty risk — private memory lives on a different tier behind a different filter. Nothing in this epic touches the Tier 1 filters or the `access_policy` default.

### DD-2 — Framing is mandatory: no Σ content reaches an agent unframed (LOAD-BEARING)
Past live testing showed agents finding Oracle content jarring — it "just appeared" with no explanation. Deliberate work fixed that, and this epic must not regress it.

The existing wrapper is applied at the **consumer**, not at the Oracle (`cognitive/sub_tasks/analyze.py:128`, `compose.py:495`):
```
## Cross-Tier Knowledge (Ship's Records)

These are NOT your personal experiences. They are from the ship's shared
knowledge stores. Treat as reference material, not memory.
```
Supporting machinery: `compute_source_framing` → authority-calibrated header + instruction (`source_governance.py:225`, AD-568c); `ProvenanceEnvelope.render()` → `[source:records confidence:0.82 age:3m]` (`provenance.py`, AD-677); `query_with_provenance()` is the ready-made helper.

**The trap:** `AgenticLoop` has no such wrapper — it renders `f"[{m['role']}] {m['content']}"` (`agentic_loop.py:138`). A naive tool would deliver raw Σ text straight into a crew child. **Therefore every Σ surface introduced by this epic carries its own framing inline**, using `ProvenanceEnvelope` for per-item provenance plus a short disposition preamble modelled on `_VISUAL_DISPOSITION` (`perception/working_memory.py:28`, AD-1059):
> *"(This visual feed is BACKGROUND context. Do not narrate it by default. Mention what you see only when it is genuinely novel or unusual, when it is directly relevant to the task, or when the Captain asks — a brief, natural acknowledgement when a call first opens is welcome.)"*

Σ framing must state: where it came from, that it is **not** the agent's own memory, how much to trust it, and that citing it is expected while narrating it is not.

**Wording constraint:** all injected/teaching text must not match `_CAPABILITY_GAP_RE` (`decomposer.py:33`) — no "can't", "cannot", "unable to", "don't have", "not available/supported/possible", "outside scope". Use "do not" (with a space). Every prompt in this epic asserts a gap-regex-safe test.

**Budget constraint:** `SensoriumConfig.warning_chars = 10000` (`config.py:3735`). Σ injection must be bounded per turn and counted against that budget; AD-1122 telemetry already reports overages.

### DD-3 — BF-675 fix shape: exclude at the source, relabel as defence-in-depth
Relabelling alone is insufficient because `_filter_by_access_policy` returns early under the default `permissive` policy (`oracle_service.py:607`, `config.py:1021`). See `prompts/bf-675-oracle-tier5-sovereign-bypass.md`.

### DD-4 — Publish default classification is `ship`
`write_notebook` defaults to `department` (`records_store.py:256`), but the closer precedent is `CreativeExpressionConfig.default_classification = "ship"` (`config.py:5688`) — agent-authored output already defaults to ship. Crew sessions are deliberately cross-department (six departments: engineering, science, medical, security, operations, bridge — `standing_orders.py:40`), and AD-554 convergence already requires `min_convergence_departments: 2`. A `department` default would make a science finding invisible to engineering and defeat the purpose. Agents may override to `department` or `private`; config-driven, mirroring `CreativeExpressionConfig`.

### DD-5 — Σ tool grant: all six departments, `ensign: read`, Σ tiers only
The tool hard-codes the Σ tier list (records, semantic, graph, archive, operational, health) and **never queries Tier 1 episodic**. Consequences: no sovereignty surface, so rank gating protects nothing sensitive; the tool is strictly weaker than the existing passive ORACLE-tier injection, so it is not a privilege escalation; and it composes with BF-675 so "Σ tiers only" is genuinely episode-free.

Copying `event_log_query`'s `("engineering","science","security")` grant would exclude bridge (where the Counselor and Yeoman live), medical, and operations — a commons that excludes half the ship is not a commons, and it would silently corrupt the AD-1143 ablation by measuring "some agents had Σ" instead of "Σ vs no Σ".

### DD-6 — Three crew contracts that MUST NOT change
Verified at HEAD. Any prompt in this epic that touches the crew path restates these as explicit constraints:

1. **`crew_execution` evidence is an exact 14-key set** — `set(execution) != {...}` raises `crew_execution_evidence_invalid` (`crew_executor.py:622`). Adding a key breaks recovery on every restart. Σ publications are recorded in Ship's Records, **not** in crew evidence.
2. **`SubtaskResult`'s field set is frozen by finalizer recovery** — exact 12-key check then `SubtaskResult(**result_values)` (`crew_finalizer.py:1909`). **Do not add fields to `SubtaskResult`.**
3. **`description` is inside the plan-identity hash** — the plan projection includes `"description"` (`crew_session.py:1006`), `plan_seed_hash = sha256(projection_bytes)` (`:1174`), re-verified on recovery (`:1574`); and `task_text = active_child.description or active_child.title` (`crew_executor.py:890`).

> **Design rule:** Σ context enters as a **runtime prompt injection**, never as persisted spec/evidence/result state. The seam is `extra_context={...}` at `crew_executor.py:898`.

### DD-7 — Capture the ablation baseline BEFORE Σ reaches the crew loop
AD-1143's control arm is today's isolated-children behaviour. Once AD-1141 merges it is unrecoverable. A minimal baseline-capture harness runs ahead of AD-1141 rather than blocking on the full eval.

---

## Sub-ADs

| AD | Deliverable | Nooplex |
|----|-------------|---------|
| **BF-675** | Close the Tier 5 sovereign bypass | prerequisite |
| **AD-1138** | Semantic index over Ship's Records — `records` collection in `SemanticKnowledgeLayer.COLLECTIONS`, `index_record`, classification carried in metadata, Oracle Tier 2 retrieval with a classification-filtered `where` clause | Σ discoverable (§3.1) |
| **AD-1139** | Governed `oracle_query` tool for the AgenticLoop — Σ tiers only, all six departments, `ensign: read`, **framed + provenance-tagged output per DD-2** | Σ reachable |
| **AD-1140** | `publish_finding` — classified, provenance-stamped write through `RecordsStore`, `ship` default, rank-gated | Σ writable (§6.2) |
| **AD-1141** | Crew loop wired to Σ — consult before, publish after, via `extra_context`; **no persisted spec change (DD-6)** | §3.1 Emergent Coordination |
| **AD-1142** | Crew-child compaction + token budget through `_loop_kwargs` (`agentic_dispatch.py:913`); durable trace preserved via `_persist_tool_trace` | §3.3 long-horizon |
| **AD-1143** | With/without-Σ ablation harness + LLM judge | §8.3, §8.5, §8.6 |

**Order:** BF-675 → AD-1138 → AD-1139 → *[baseline capture]* → AD-1140 → AD-1141 + AD-1142 → AD-1143.

## Epic acceptance

- Sovereignty preserved: a test proves an agent cannot obtain another agent's episode content through **any** Oracle tier under the default policy.
- No unframed Σ: every Σ surface has a test asserting provenance + disposition framing is present, and that the text is `_CAPABILITY_GAP_RE`-safe.
- Crew contracts intact: AD-1124→1133 suites green unchanged; the 14-key evidence set, `SubtaskResult` fields, and plan-identity hash are byte-identical.
- Each sub-AD default-OFF and byte-identical when off (BF-675 excepted — it is a fix).
- AD-1143 reports a with-Σ vs without-Σ comparison on a fixed goal set.
- Σ injection bounded and counted against `SensoriumConfig.warning_chars`.

## Do NOT build in this epic

❌ Changing the `access_policy` default away from `permissive` — separate Captain decision. ❌ Any change to the Tier 1 sovereign filters. ❌ Inter-mesh federated Σ (an eighth Oracle tier — forward). ❌ Structured argumentation and the §6.4 four-stage reconciliation (unclaimed — mint a fresh AD when scoped; AD-1144 is now the JCS/JWS standards adoption). ❌ Adaptive re-planning and mid-flight Captain steering (deferred; see the session plan). ❌ Asynchronous crew-child spawning. ❌ Episode-level publication via `OWN_SHARD_PLUS_PUBLIC` — the enum anticipates it (`memory_security.py:31`) but it is out of scope here. ❌ Editing `config/system.yaml` (skip-worktree `S`, Captain-local).

## Open items to resolve at build

- Confirm the AD-1124 metadata CAS admits a **new sibling key** on `WorkItem.metadata` (the evidence validator reads specific keys and does not assert the whole metadata key set, and AD-1124 shallow-merges — but `_plan_metadata(..., reject_reserved=True)` at `crew_session.py:1013` shows reserved-key logic exists nearby).
- Decide whether AD-1138's classification filter uses a ChromaDB `where` clause or post-filtering; `where` is preferred for correctness under `limit`, and ChromaDB 1.5.8 multi-predicate filters require a single top-level `$and` operator.
