# Wave 32 — AD-660 v1 Agent Causal Reasoning Framework (TEMPLATE + JOURNAL + INTEGRATION POINT)

**Closes:** #319. Standalone wave. Depends on AD-504 SelfMonitoringConcernEvent surface (events.py:127/672, counselor.py:677/889/979 — all shipped) and AD-557 emergence metrics (shipped, not consumed in v1).

**Hard limit:** v1 ships **template + journal + ONE opt-in integration point ONLY**. NO causal-inference engine. The LLM fills a four-step structured template; ProbOS persists the artifact. Out of the box, `CausalReasoningConfig.enabled=False` makes the entire framework a no-op. AD-557 emergence-event integration, automatic invocation, hypothesis ranking, and action execution are all explicitly deferred to AD-660b/c.

**Prompt:** `prompts/ad-660-causal-reasoning-v1.md`

## Standing rules

- Test gate command: `pytest tests/ -q -n 4 --dist=loadfile`. Triage failures at `-n 0` if parallel-only.
- One AD = one commit. Commit message footer: `Closes #319`.
- Hard-stop on phantom-API in implementation (not just tests). Pre-check ran clean — see "Phantom-API Pre-Check" below.
- Do NOT extend scope to: causal-inference engine, automatic invocation across all concern paths, hypothesis ranking, action execution, AD-557 emergence-event hook, API router, HXI surface, EventType emission, ChromaDB persistence, retroactive backfill, periodic background loop, optimizer-template join. All explicitly listed under "What This Does NOT Change."
- Tests min 7, target 8. Builder reports actual delta in PROGRESS.md entry.
- **Wave 31 baseline test count: 10935.** Expected post-build: 10942 (+7) to 10943 (+8).

## Per-section quality gates

- **Section 2** (`cognitive/causal_reasoning.py` NEW): `CausalReasoningTemplate` is **frozen** dataclass — distinct from AD-659's mutable `OptimizationProposal`. Mutating `confidence` MUST raise. `CausalReasoner.analyze()` and `analyze_concern()` are async, NEVER raise — degrade to `_empty_template()` (or None for missing agent_id) on every failure path. JSON parse via `extract_json` with `(ValueError, TypeError)` catch — same pattern as `sub_tasks/evaluate.py:661`. List fields capped at `_MAX_LIST_LEN=8` items; per-item chars at `_MAX_FIELD_CHARS=500`.
- **Section 3** (journal extend): `_SCHEMA_CAUSAL_TEMPLATES` adjacent to `_SCHEMA_CHAIN_TRACES`. Schema executescript added in `start()` after the AD-658 line. Prune extension covers BOTH age-based and row-cap branches. New methods INSERT OR IGNORE + fire-and-forget try/except (mirrors `record_chain_trace` exactly). `triggered_at` stored as Unix-epoch float via `template.triggered_at.timestamp()`. List fields JSON-serialized in/out.
- **Section 4** (config): `CausalReasoningConfig` adjacent to `ChainOptimizerConfig` at config.py:336. `SystemConfig.causal_reasoning` field IMMEDIATELY AFTER `chain_optimizer` at config.py:2019. `enabled: bool = False` per Wave 10 transitional-flag lesson.
- **Section 5** (wirer): mirrors `_wire_chain_optimizer` shape exactly (finalize.py:214–237). Sets `runtime.causal_reasoner` public attribute. Invocation block at finalize.py:517 — Builder must read the actual surrounding 5 lines before SEARCH/REPLACE; the prompt's Section 5b is approximate (the file shape may have minor variations). Mirror the `_wire_chain_optimizer` invocation block exactly.
- **Section 6** (counselor hook): ONE block inserted after `_save_profile_and_assessment` at counselor.py:~1010, BEFORE the trailing comment block. Wrapped in try/except → `logger.debug` so it CANNOT raise into the existing flow. Uses `getattr(self._runtime, "causal_reasoner", None)` AND `getattr(self._runtime, "cognitive_journal", None)` — neither attribute is required, both must be defensively checked.
- **Section 7** (tests): 8 tests in `tests/test_ad660_causal_reasoning.py`. Real `CognitiveJournal` + `tmp_path` for journal round-trip (Tests 4–5). `SimpleNamespace` + `AsyncMock` for LLM stubs (Tests 2, 3, 6, 8). Test 7 verifies wirer no-op with default config; Test 8 verifies wirer creates `runtime.causal_reasoner` and analyze_concern returns a real (degraded) template.

## Wave 32 reminders

- AD-659 (Wave 31) just landed at HEAD. The wave plan was already pushed planning Waves 32–35. Builder's first action is `git pull` to confirm clean working tree.
- The chain_traces persistence pattern from AD-658 is the canonical mirror for AD-660's causal_templates table. **Do not deviate** — same INSERT OR IGNORE shape, same fire-and-forget try/except, same prune policy.
- `extract_json` is at `probos.utils.json_extract:17` and handles markdown fences, `<think>` blocks, preamble/trailing text, brace-depth string-aware matching. The reasoner already imports it correctly.
- The integration point is **deliberately narrow**. v1 wires ONE call-site (counselor amber-zone). The architect chose this because:
  1. AD-504 self-monitoring concern is the well-tested entry point (counselor.py:889 dispatch is shipped).
  2. The hook is fire-and-forget guarded — even if the reasoner raises, counselor's existing flow is intact.
  3. AD-557 emergence-event hook (groupthink/fragmentation) requires reading multi-agent context which crosses department boundaries — that surface is AD-660b.
- The `SelfMonitoringConcernEvent` shape (events.py:672–676) provides: `agent_id`, `agent_callsign`, `zone`, `similarity_ratio`, `velocity_ratio`. The reasoner's `analyze_concern()` consumes exactly these — verified at draft time.
- Tests use `SimpleNamespace` + `AsyncMock` for runtime stubs (matches existing AD-657/AD-659/AD-683 fixture style).
- Counselor's `self._runtime` reference: grep confirms it exists at counselor.py (the file imports `from probos.runtime import ProbOSRuntime` and uses `self._runtime` throughout). If the actual line at HEAD uses `self.runtime`, fix in the SEARCH/REPLACE before applying.

## Builder workflow

1. `git pull` — confirm clean working tree.
2. Implement Sections 2–7 in order. Section 2 first (introduces `CausalReasoner` + `CausalReasoningTemplate` that subsequent sections wire). Section 3 is the largest mechanical edit (journal extend) — bundle the four sub-edits (3a/3b/3c/3d) carefully; verify with `pylance` that the schema constant lands before the class.
3. Run focused gate: `pytest tests/test_ad660_causal_reasoning.py -v -n 0`.
4. Run full gate: `pytest tests/ -q -n 4 --dist=loadfile`. Verify delta is `+7` to `+8` over the 10935 baseline.
5. Commit single change. Title: `AD-660 v1: Agent Causal Reasoning Framework (template + journal + integration point)`. Footer: `Closes #319`.
6. Update PROGRESS.md with closure entry; update roadmap.md with AD-660 status flip + AD-660b/c/d forward-refs; push.

## Hard-stop conditions

- Builder tempted to add a causal-inference engine (do-calculus, structural equation models, counterfactual graph) → **HARD STOP**. v1 is template-fill only. The LLM provides the reasoning; ProbOS provides the storage. Inference engine is permanent out-of-scope (AD-660 is a metacognitive scaffold, not a causal-discovery system).
- Builder tempted to wire AD-557 emergence-event hook (groupthink_warning, fragmentation_warning) → **HARD STOP**. Deferred to AD-660b. v1 has exactly ONE integration point (counselor amber-zone).
- Builder tempted to add `/api/causal-templates` router → **HARD STOP**. Read access is journal-only in v1. API is AD-660b.
- Builder tempted to emit a new EventType `CAUSAL_TEMPLATE_RECORDED` → **HARD STOP**. v1 emits no events.
- Builder tempted to make the counselor hook unconditional (drop the `enabled` gate, or invoke even with `enabled=False`) → **HARD STOP**. The default-False flag is the v1 safety net.
- Builder finds that counselor uses `self.runtime` (no underscore) at HEAD → fix in the SEARCH/REPLACE; this is a verify-first correction, not an architectural change.
- Builder finds that finalize.py:517 invocation block has additional logic beyond `if _wire_chain_optimizer(...): pass` → mirror that exact logic in the AD-660 invocation. Not a hard stop.
- Test count delta is < 7 or > 8 → check whether Test 1 frozen-check pytest collected as collapsed (sometimes parametrized as a single test); flag in build report. Acceptable range is +7 to +9.
- Real architectural change required (e.g., `CausalReasoner` needs a new `BaseAgent` protocol method, or counselor must change its event-subscription tuple) → hard stop, surface to architect. The prompt's design avoids this.

## Phantom-API Pre-Check

Ran `./scripts/phantom-api-precheck.ps1 prompts/ad-660-causal-reasoning-v1.md` against HEAD post-Wave-31. Result: **13 phantom candidates flagged, all false positives. 0 NEW phantoms in implementation surface.**

**Raw precheck output:**
```
=== prompts/ad-660-causal-reasoning-v1.md ===
  13 phantom symbol(s):
    - [<Class>(...)] class:SimpleNamespace
    - [<Class>(...)] class:CausalReasoningConfig
    - [kwarg_mismatch] analyze(trigger=...)
    - [kwarg_mismatch] analyze(agent_id=...)
    - [kwarg_mismatch] analyze(context=...)
    - [kwarg_mismatch] analyze(source_event_ref=...)
    - [kwarg_mismatch] analyze(trigger=...)
    - [kwarg_mismatch] analyze(agent_id=...)
    - [method_phantom] CognitiveJournal.get_recent_causal_templates(...)
    - [method_phantom] CognitiveJournal.record_causal_template(...)
    - [method_phantom] CognitiveJournal.get_recent_causal_templates(...)
    - [method_phantom] CognitiveJournal.record_causal_template(...)
    - [method_phantom] CognitiveJournal.get_recent_causal_templates(...)
  Skipped (unresolved class):
    ~ [no_class_resolution] runtime.causal_reasoner.analyze_concern(...)
```

**All 13 are false positives:**
- `SimpleNamespace` — Python stdlib `types.SimpleNamespace` (test fixture). Same FP class as Wave 30.
- `CausalReasoningConfig` — Pydantic class introduced by Section 4 of THIS prompt; pre-check class index does not see not-yet-shipped types.
- `analyze(trigger=...)`, `analyze(agent_id=...)`, `analyze(context=...)`, `analyze(source_event_ref=...)` (×2 each) — `CausalReasoner.analyze()` is introduced by Section 2 of THIS prompt with signature `analyze(self, *, trigger, agent_id, context=None, source_event_ref=None)`. Same "introduced-in-prompt-not-in-index" FP class as Waves 27/28/29/31.
- `CognitiveJournal.get_recent_causal_templates(...)` / `CognitiveJournal.record_causal_template(...)` — both introduced by Section 3d of this prompt. The pre-check correctly identifies them as new methods on an existing class. Same FP class as AD-658 chain_traces methods at draft time (Wave 28).
- `runtime.causal_reasoner.analyze_concern(...)` — `analyze_concern` is introduced by Section 2 of this prompt; the pre-check skips with `[no_class_resolution]` because `runtime.causal_reasoner` is not yet wired. Documented FP.

**Symbols introduced by this prompt (not flagged but called out for transparency):**
- `CausalReasoningTemplate`, `CausalReasoner`, `_empty_template`, `_coerce_list`, `_coerce_confidence`, `_SYSTEM_PROMPT` — Section 2
- `_SCHEMA_CAUSAL_TEMPLATES`, `record_causal_template`, `get_recent_causal_templates` — Section 3
- `CausalReasoningConfig` — Section 4
- `_wire_causal_reasoner` — Section 5
- AD-660 hook block in `_on_self_monitoring_concern` — Section 6

**0 NEW phantoms** in implementation surface. All 13 hits are introductions or stdlib aliases. Verified against HEAD post-Wave-31.
