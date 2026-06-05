# Wave: Memory Epistemics + Forge Observability (AD-871 · AD-872 · AD-873)

**Status:** Draft for Architect verify-first review. Builder executes one AD = one commit with a full gate between each.
**Goal (Captain):** Close ProbOS's two memory-layer gaps relative to `framerslab/agentos` — no first-class *provenance* on episodes and no episode-level *forgetting* — and add cheap self-mod forge telemetry. All three are additive/defaulted: zero-config boot stays byte-identical and the governance fabric (Shapley, trust, anchor recall, consensus) is untouched.
**Research basis:** AgentOS (Apache-2.0) cognitive-memory + emergent-capabilities docs. Pattern-absorption only (TypeScript → Python); AgentOS cited as research, no code copied. License disposition: clean MIT/Apache-tier, no copyleft, no model weights.

**Tracking issues (close via commit `closes #NNN`):** AD-871 → [#843](https://github.com/seangalliher/ProbOS/issues/843) · AD-872 → [#844](https://github.com/seangalliher/ProbOS/issues/844) · AD-873 → [#845](https://github.com/seangalliher/ProbOS/issues/845).

---

## AD numbering — hard rule honored

- **Current highest committed AD = AD-870** (PROGRESS.md, Wave 219). State this in any review response.
- **New ADs in this wave: AD-871, AD-872, AD-873** (assigned sequentially from 870; formally reserved by issues #843/#844/#845).
- **Supersedes the non-binding AD-871/872/873 forward markers** in `prompts/ad-869-yeo-lightweight-delegation-wave.md` (trust-weighted specialist selection / rung-of-ladder signaling / kanban auto-refresh). Those were never committed; the issues above are the formal reservation. The three Yeo follow-up ideas get fresh numbers if/when built.

## Repo boundary

OSS only (`d:\ProbOS`). The memory-mechanism and forge-telemetry work is "how the product works" → public. The AgentOS *personality* (HEXACO) feature and any *benchmark-as-positioning* framing are commercial-overlay concerns — **do NOT** add personality fields, emotional-congruence signals, or competitive/benchmark language to OSS code or docs.

---

## What ALREADY EXISTS (verified against HEAD — do not rebuild)

| Capability | Where (verified) |
|---|---|
| Episode record | `Episode` dataclass [types.py:469](../src/probos/types.py) — fields: `id, timestamp, user_input, dag_summary, outcomes, reflection, agent_ids, duration_ms, embedding, shapley_values, trust_deltas, source(="direct"), anchors(AnchorFrame\|None), importance(int=5), correlation_id, valid_from, valid_until`. **No** `confidence`, `verification_count`, `contradicted_by`, `source_type`, or `strength`/`stability` fields. |
| Coarse provenance | `Episode.source` is a single `MemorySource` value (AD-541), an origin tag — NOT a graded-belief envelope. |
| Store | `EpisodicMemory.store(episode) -> None` [episodic.py:1186](../src/probos/cognitive/episodic.py) — eviction + AD-610 utility gate + AD-607h injection gate + BF-039 rate-limit/dedup. **The ChromaDB metadata dict is assembled in `_episode_to_metadata` [episodic.py:2292] (write seam), NOT inline in store.** ⚠️ `store()` ALSO re-stamps importance via an explicit `Episode(...)` field-by-field reconstruction at **episodic.py:1258-1276** — see AD-871 Required correction (must become `dataclasses.replace`). |
| Recall→Episode rebuild | `_metadata_to_episode(doc_id, document, metadata)` [episodic.py:2426](../src/probos/cognitive/episodic.py) — the single canonical metadata→Episode builder (14 recall-path call sites), reads each field via `metadata.get(...)`. **This is the read seam for AD-871/873 round-trip.** New reads use `metadata.get("<key>", <default>)` with `int()`/`float()` coercion (ChromaDB metadata is str/int/float/bool only). |
| Default recall | `EpisodicMemory.recall(query, k=5) -> list[Episode]` [episodic.py:1778](../src/probos/cognitive/episodic.py) — ranks purely by `similarity = 1.0 - cosine_distance`, filtered by `relevance_threshold`. Queries `n_results = min(k*3, count)` but **breaks the loop at `len(episodes) >= k`** (matters for AD-873 — see Rec). **No** recency/importance/decay weighting. |
| Composite-scorer precedent | `recall_by_anchor_scored(...) -> list[RecallScore]` [episodic.py:1885](../src/probos/cognitive/episodic.py) (AD-603) already blends anchors + semantic + temporal + Hebbian. Use as the idiom for AD-873; do NOT modify it. |
| Consolidation | `DreamingEngine.dream_cycle() -> DreamReport` [dreaming.py:292](../src/probos/cognitive/dreaming.py) — **Step 7f** (`dreaming.py:724`) decays **procedures** via `_procedure_store.decay_stale_procedures()` (AD-538). AD-567d activation reinforcement is `self._activation_tracker.record_batch_access(...)` [dreaming.py:259]. **No** episode-level decay sweep. (Prompt-internal "step 16/18" numbering is wrong — use these real anchors.) |
| Content hash | `compute_episode_hash` [episodic.py:680] uses an **explicit field allowlist** (NOT `asdict`) — the new AD-871/873 fields are excluded, so dedup / `_hash_v` integrity are **unaffected. Do NOT bump `_hash_v`; no migration needed.** |
| Self-mod orchestrator | `SelfModificationPipeline` [self_mod.py:42](../src/probos/cognitive/self_mod.py); pipeline = `handle_unhandled_intent(intent_name, intent_description, parameters, requires_consensus=False, execution_context="", on_progress=None) -> DesignedAgentRecord \| None` [self_mod.py:96]. Records accumulate in `pipeline._records` [self_mod.py:94]. Top of `handle_unhandled_intent` (`active_count = sum(...)`) is a clean early-return point for the AD-872 shape gate. |
| Designed-agent record | `DesignedAgentRecord` [self_mod.py:27](../src/probos/cognitive/self_mod.py) — `intent_name, agent_type, class_name, source_code, created_at, sandbox_time_ms, pool_name, status(="active"), strategy, error`. **Full `status` value set emitted at HEAD:** `active, max_limit, rejected_by_user, failed_design, failed_validation, dependencies_declined, dependencies_failed, failed_sandbox, failed_registration` (+ `removed`). No stats aggregation, no per-unique-tool rate. |
| Agent designer | `AgentDesigner.design_agent(...) -> str` [agent_designer.py:251](../src/probos/cognitive/agent_designer.py) — returns raw Python source. No pre-design shape gate. |
| Code validator | `CodeValidator.validate(source_code: str) -> list[str]` [code_validator.py:40](../src/probos/cognitive/code_validator.py) — returns error strings (empty = pass). |
| Events | `EventType(str, Enum)` [events.py:20](../src/probos/events.py). Cognitive modules emit via an injected `event_log`/`emit_event` callback (no new bus). Adding a new member is trivial/safe. |
| Frozen-dataclass rule | Mutate `RecallScore`/`AnchorFrame`/`Episode`-derived via `dataclasses.replace(...)`. Non-defaulted fields MUST precede defaulted (repo memory). |

---

## AD-871 — Provenance-aware memory envelope + per-source confidence

**Problem.** Confabulation is fought with *guards* (anchor recall AD-567, reconsolidation AD-541b, confabulation guard AD-588/589/592, BF-599) because ProbOS has no first-class representation of *why it believes a memory*. `source` is a one-word origin tag; there is no graded belief, no verification count, no contradiction link.

**Approach (additive fields + store/recall round-trip; no ranking change):**

1. **New `Episode` fields** in [types.py:469](../src/probos/types.py), **all defaulted, appended AFTER existing fields** (non-defaulted-precede-defaulted is satisfied — every existing field is already defaulted):
   - `source_type: str = ""` — graded provenance: one of `user_statement | tool_result | observation | agent_inference | reflection | external`. Empty = fall back to `source` semantics.
   - `confidence: float = 1.0` — store-time belief strength derived from `source_type`.
   - `verification_count: int = 0` — corroboration counter.
   - `contradicted_by: list[str] = field(default_factory=list)` — contradicting episode ids (feeds the existing AD-403 contradiction pass in `dream_cycle`; this AD only adds the field + population helper, not new dream logic).
2. **A pure module-level mapping** `source_type → default confidence` (e.g. `user_statement`/`tool_result` → 1.0; `observation`/`external` → ~0.8; `agent_inference`/`reflection` → ~0.5) and a `source → source_type` back-fill map (legacy `"direct"` → a sane default). Keep as small typed module constants; no config unless trivially defaulted.
3. **Write seam — `_episode_to_metadata` [episodic.py:2292]:** stamp `source_type`/`confidence` when unset (back-filling from `source`) and write all four new fields into the metadata dict (`source_type`, `confidence`, `verification_count`, `contradicted_by_json`). **Read seam — `_metadata_to_episode` [episodic.py:2426]:** rebuild them onto the `Episode` via `metadata.get("<key>", <default>)` with `int()`/`float()` coercion.
4. **⚠️ REQUIRED — fix the field-dropping reconstruction at episodic.py:1258-1276.** `store()` re-stamps AD-598 importance by reconstructing the frozen `Episode(...)` with an explicit field-by-field keyword list (a *common* path: fires whenever `importance == 5` and the computed score differs). That hand-written constructor will silently reset any caller-provided new field to its default. **Replace the whole `episode = Episode(id=…, …, valid_until=…)` block with `episode = dataclasses.replace(episode, importance=_importance)`** — future-proof against all field appends. (Same fix is shared with AD-873.)
5. **`recall()`** must carry `confidence` (and the other fields) on returned `Episode`s — automatic once `_metadata_to_episode` rebuilds them. **No reranking in this AD** — provenance is *carried* here, *used* in AD-873.
6. Optional thin helper to append to `contradicted_by` via `dataclasses.replace` (frozen-safe). No new event types required; if added, follow the injected-`event_log` pattern. **No `_hash_v` bump** — `compute_episode_hash` (episodic.py:680) uses an explicit allowlist that excludes the new fields.

**Acceptance criteria.**
- `tests/test_ad871_provenance_envelope.py` (≥7, **real** `MockEpisodicMemory`/`EpisodicMemory` fixture — NO MagicMock at the substrate boundary, BF-287): field defaults; store→recall round-trip of all four fields through ChromaDB metadata; `source`→`source_type` back-fill for a legacy `"direct"` episode; confidence-by-source-type mapping; `contradicted_by` population via the helper; malformed/absent metadata → honest-degrade to defaults (no raise); a pre-AD-871 episode (no new keys in metadata) recalls with defaults.
- **Regression guard for the episodic.py:1258 fix (REQUIRED test):** construct an `Episode` with `importance=5` AND `confidence=0.4` (the importance=5 path triggers the AD-598 reconstruction), `store()`, `recall()`, assert `confidence == 0.4` (proves `dataclasses.replace` preserved the new field instead of the old field-by-field constructor dropping it).
- All existing `tests/test_episodic.py` pass unchanged.
- "Store raw, never derived" honored — persist `source_type` + `confidence`, never a single collapsed score.
- Verify compliance with Engineering Principles in `.github/copilot-instructions.md`.

**Do NOT build:** any reranking/decay (AD-873); new dream-cycle contradiction logic (the AD-403 pass already exists — only feed it the field); personality/emotional fields; config beyond trivially-defaulted constants; changes to `recall_by_anchor_scored`.

---

## AD-872 — Forge observability for the self-modification pipeline

**Problem.** The self-mod forge is a black box: only a `status` string + scattered logs. No pre-design shape gate, no rejection bucketing, no throughput stats — so designer-quality drift is invisible.

**Approach (new module of pure, fully-typed units + read-only wiring):**

New module `src/probos/cognitive/forge_observability.py`:
1. **`validate_forge_shape(intent_name: str, intent_description: str, parameters: dict[str, str]) -> list[str]`** — cheap pre-design gate (empty/degenerate intent name, empty description, obviously-missing params). Returns error strings (empty = proceed), same contract shape as `CodeValidator.validate`. Pure, no side effects.
2. **`classify_forge_rejection(record: DesignedAgentRecord, validator_errors: list[str] | None = None) -> str`** — deterministic bucket: `syntax_error | forbidden_import | schema_nonconformance | judge_correctness | dependency_declined | dependency_failed | user_rejected | max_limit | design_failed | failed_sandbox | failed_registration | shape_rejected | other`. Must map **every** `DesignedAgentRecord.status` value actually emitted at HEAD — `active, removed, max_limit, rejected_by_user, failed_design, failed_validation, dependencies_declined, dependencies_failed, failed_sandbox, failed_registration` — plus representative `CodeValidator` error substrings; an explicit `else → "other"` ("unknown") fallback so a future/unseen status never crashes the aggregator.
3. **`ForgeStatsAggregator`** — consumes a `list[DesignedAgentRecord]` and reports both `attempt_approval_rate` and `unique_intent_approval_rate` (the key insight: a 3-retry recovery on one intent ≠ 3 distinct successes), plus `rejection_histogram: dict[str, int]`, `total_unique_intents: int`, `total_attempts: int`. Pure aggregation over the records list.

Wiring (read-only, honest-degrade — `tests/test_self_mod.py` must stay green):
- `SelfModificationPipeline` gains `forge_stats() -> ForgeStatsAggregator` (or returns its summary dict) built over `self._records`.
- Call `validate_forge_shape(...)` at the very top of `handle_unhandled_intent`; on a non-empty error list, record a `DesignedAgentRecord(status="shape_rejected", error=<joined>)` into `_records` and return `None` (skip the expensive design call). Wrap in Tier-2 honest-degrade — a shape-gate failure must never raise.
- Optional `EventType.FORGE_SHAPE_REJECTED` via the existing injected-`event_log` pattern (only if it slots cleanly).

**Acceptance criteria.**
- `tests/test_ad872_forge_observability.py` (≥8, real `DesignedAgentRecord` fixtures — no MagicMock at the boundary, BF-287): `validate_forge_shape` rejects ≥3 malformed-request shapes and passes a well-formed one; `classify_forge_rejection` maps every `status` value + representative validator errors, with `other` fallback; `ForgeStatsAggregator` separates unique-intent rate from attempt rate on a retried+distinct fixture; histogram correctness; `shape_rejected` short-circuits `handle_unhandled_intent` without a design call (assert the designer is not invoked); honest-degrade when the shape gate raises.
- All public signatures fully type-annotated; module has no import-time side effects.
- `tests/test_self_mod.py` + `tests/test_ad838_office_create_wiring.py` stay green.
- Verify Engineering-Principles compliance.

**Do NOT build:** any change to the actual design/validate/sandbox logic; new LLM calls; memory-layer changes; persistence of stats (in-memory aggregation over `_records` only).

---

## AD-873 — Ebbinghaus episode decay + composite retrieval reranking

**Problem.** `recall()` ranks by raw semantic similarity over an ever-growing store; a stale one-off ranks the same as a frequently-reinforced, high-importance memory. ProbOS has the signals (importance, timestamp, AD-567d reinforcement) but applies no decay or composite score on the default path.

**Approach (additive Episode fields + decay sweep in dreaming + config-gated rerank):**

1. **New `Episode` fields** (defaulted, appended): `strength: float = 1.0`, `stability: float = <sane default>` (the Ebbinghaus stability constant; grows on retrieval/replay). Both round-tripped through ChromaDB metadata via `_episode_to_metadata` [episodic.py:2292] / `_metadata_to_episode` [episodic.py:2426] like AD-871's fields. **Same episodic.py:1258 `dataclasses.replace` fix applies** (shared with AD-871 — if AD-871 already landed it, this is a no-op). No `_hash_v` bump.
2. **Decay model** — a pure helper `decayed_strength(strength, stability, delta_seconds) -> float` implementing `S(t) = S₀ · e^(−Δt / stability)`. A retrieval/replay grows `stability` (spaced-repetition) so reinforced memories decay slower. Reuse the AD-567d `_activation_tracker` reinforcement signal — do NOT add a second tracker.
3. **Decay sweep in `dream_cycle()`** — add an episode-decay pass **after Step 7f procedure decay (`dreaming.py:724`, before Step 7g notebook consolidation, ~`dreaming.py:753`)**. Reuse the AD-567d reinforcement signal `self._activation_tracker.record_batch_access(...)` [dreaming.py:259] — do NOT add a second tracker. Honest-degrade: a decay failure logs Tier-2 and never aborts the dream cycle. Idle-time only; never on the hot path.
4. **Composite rerank on `recall()`** — config-gated. Rerank the semantic candidate set by `strength · similarity · recency · importance` (each normalized to [0,1]). **⚠️ recall() currently `break`s the candidate loop at `len(episodes) >= k`** (episodic.py:1778) — when the rerank is enabled, collect the FULL `min(k*3, count)` candidate pool (skip that early break), score all, then truncate to `k`; otherwise the rerank only re-sorts `k` items and is a no-op. Keep the `relevance_threshold` floor. **Explicitly DROP AgentOS's emotional-congruence signal** (personality = commercial overlay). Follow the `recall_by_anchor_scored` blending idiom; weights in a defaulted dict surfaced via Pydantic config with defaults that, when neutral, reproduce **today's semantic-only ordering** (regression-safe). If AD-871 has shipped, `confidence` MAY be an optional additional factor behind a presence check — but AD-873 must not hard-depend on AD-871.

**Acceptance criteria.**
- `tests/test_ad873_episode_decay.py` (≥8, real episodic fixture — no MagicMock at the boundary, BF-287): `decayed_strength` reduces strength over Δt and is monotonic; retrieval/replay grows `stability` → slower decay; composite rerank reorders vs semantic-only on a constructed set; importance and recency each measurably contribute; neutralized-weights config reproduces semantic-only ordering (regression); decay sweep honest-degrades on failure without aborting `dream_cycle`; new fields round-trip through metadata and default cleanly on pre-AD-873 episodes.
- Zero-config boot byte-identical (decay/rerank no-op until enabled or with neutral defaults).
- `tests/test_episodic.py` + `tests/test_dreaming.py` stay green.
- Verify Engineering-Principles compliance.

**Do NOT build:** provenance envelope (AD-871); emotional/personality signal; changes to `recall_by_anchor_scored`; decay on the hot path; a second activation tracker.

---

## Suggested sequence & gates (Builder)

1. **AD-871** (provenance envelope) → `test_ad871_*` + `test_episodic.py` green → full gate → commit (`closes #843`) → **stop, review**.
2. **AD-872** (forge observability) → `test_ad872_*` + `test_self_mod.py` green → full gate → commit (`closes #844`) → **stop, review**.
3. **AD-873** (decay + rerank) → `test_ad873_*` + `test_episodic.py` + `test_dreaming.py` green → full gate → commit (`closes #845`) → **stop, review**.

After all three: a single push. Each AD updates PROGRESS.md (newest-first banner + Wave number) + DECISIONS.md (newest-first entry under Era V) in its own commit. One AD = one commit.

**Test invocation (CWD hazard — always `Set-Location -LiteralPath d:\ProbOS` first):**
`d:/ProbOS/.venv/Scripts/pytest.exe d:/ProbOS/tests/test_ad871_provenance_envelope.py --rootdir d:/ProbOS -q -n 0 -p no:cacheprovider`
Full gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n auto` (serial `-n 0` triggers environmental runtime-boot timeouts; trust the "passed" count, re-triage xdist worker crashes individually). Known stale pre-existing failures (Wave 205): the two `test_bf207_shutdown_episodic_integrity.py` 2s-timeout assertions — NOT this wave's regressions.

## Verify-first reminders for the Architect

- Re-grep every file/line reference above against HEAD before final approval (subagent reports are leads, not ground truth — the AD-858..862 epic returned a NO-GO on every AD for missing connective tissue).
- Confirm the exact path that **reconstructs `Episode` from ChromaDB metadata on recall** (so AD-871/873 round-trip lands in the right place) — find the metadata→Episode builder in `episodic.py` and cite its line.
- Confirm `Episode` field ordering tolerates appended defaulted fields (it does — all current fields are defaulted).
- Confirm `dream_cycle` step 16 (AD-538 procedure decay) is the right insertion point and that `_activation_tracker` exposes a usable reinforcement signal.
- Confirm `SelfModificationPipeline._records` is the live list and `handle_unhandled_intent`'s top is a safe shape-gate insertion point.
- Confirm whether a Pydantic config section is needed for AD-873 weights or whether defaulted module constants suffice (prefer the lighter option that keeps zero-config boot byte-identical).

## Forward markers (do NOT build now)
- Feed `contradicted_by` from the AD-403 contradiction pass automatically (AD-871 only adds the field + helper).
- Surface `confidence`/`strength` in the HXI memory views.
- Let the confabulation guard (AD-588/589/592) consult `confidence` as a gate input.
