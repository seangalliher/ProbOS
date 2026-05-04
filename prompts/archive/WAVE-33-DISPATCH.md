# WAVE 33 — Builder Dispatch

**Wave kind:** main
**Builder mode:** continuous (single-AD wave; one commit)
**Pre-flight gate:** `pytest tests/ -q -n 8 --dist=loadfile` (baseline 10942, post-Wave-32 commit `4787c9d`)
**Target test count:** 10950 (+8)

---

## Build group 1 — AD-661 v1 (single-prompt)

| AD | Title | Issue | Prompt | Tests | Risk |
|---|---|---|---|---|---|
| AD-661 v1 | Full Diagnostic Context for Agent Self-Improvement (Pull-Based) | #320 | `prompts/ad-661-diagnostic-context-v1.md` | 8 | low |

### Scope summary

Pull-based, token-budgeted assembly of raw diagnostic artifacts (AD-658 chain
traces + AD-657 procedure exemplars + episodic snippets) into a single
`DiagnosticBundle`. Read-only aggregator over already-shipped surfaces. No
automatic invocation, no continuous stream, no semantic search, no summary
fallback. New module `src/probos/cognitive/diagnostic_context.py` + new router
`src/probos/routers/diagnostic_context.py` + `DiagnosticContextConfig` on
`SystemConfig` + wirer + public `runtime.diagnostic_context_service`.

### Allocation strategy chosen

| Section | Ratio | Source |
|---|---|---|
| chain_traces | 40 % | AD-658 `CognitiveJournal.get_recent_chain_traces(*, limit, agent_id, since)` |
| procedures + inline exemplars | 30 % | `runtime.procedure_store.list_active()` → `.get(id)` → `EpisodicMemory.get_by_ids(p.trace_exemplars)` (AD-657) |
| episodes (deduped exemplars) | 30 % | The same episodes pulled in §2, deduped by ID across procedures, keyword-filtered against `text` |

Ratios validated by `field_validator` (each in `[0.0, 1.0]`) and
`model_validator(mode="after")` (sum to `1.0 ± 0.01`). Filling order:
chain_traces → procedures → episodes; **no remainder redistribution** in v1
(deferred AD-661c). Token estimator: `len(text) // 4` heuristic — same
precedent as `agent_working_memory.py:35` `CHARS_PER_TOKEN = 4`. NO `tiktoken`
dependency.

### Default rationale (deviation from Wave-10 convention)

`DiagnosticContextConfig.enabled: bool = True` because v1 is a **read-only
aggregator** invisible at runtime until a caller invokes `assemble()`. The
Wave-10 transitional-flag convention (`enabled=False`) targets features that
change agent behavior on first commit; this one does not. Deviation
documented in the config docstring and prompt.

### Verified anchors (against HEAD `4787c9d`)

- `journal.py:297` — `record_chain_trace`
- `journal.py:335` — `get_recent_chain_traces(*, limit, agent_id, since)` (AD-658)
- `journal.py:57` — `chain_traces` table schema
- `procedures.py:97` — `Procedure.trace_exemplars: list[str]` (AD-657)
- `episodic.py:1132` — `EpisodicMemory.get_by_ids(episode_ids: list[str]) -> list[Episode]` (AD-657)
- `procedure_store.py:451` — `async def get(self, procedure_id) -> "Any | None"`
- `procedure_store.py:471` — `async def list_active(...) -> list[dict[str, Any]]`
- `creative/output_writer.py:61` — `runtime.records_store` (AD-434, NOT consumed in v1)
- `agent_working_memory.py:35` — `CHARS_PER_TOKEN = 4` (token-estimator precedent)
- `startup/finalize.py:214` — `_wire_chain_optimizer` (sibling shape for `_wire_diagnostic_context`)
- `api.py:195+203` — router import + for-loop tuple (twin-block insertion target)

All 11 prompt-asserted symbols verified live. **0 NEW phantoms.**

### Phantom-API pre-check

Run from repo root:
```
pwsh scripts\phantom-api-precheck.ps1 -PromptPath prompts\ad-661-diagnostic-context-v1.md
```

**Expected FP classes** (intro-not-in-index — same FP class as Waves 27/28/29/31/32):
- `DiagnosticBundle`, `DiagnosticContextService`, `DiagnosticContextConfig`,
  `_wire_diagnostic_context`, `_estimate_tokens`, `_extract_keywords`,
  `_matches`, `_collect_chain_traces`, `_collect_procedures`,
  `_collect_episodes`, `runtime.diagnostic_context_service` — all introduced
  by this prompt.
- `SimpleNamespace`, `AsyncMock`, `MagicMock`, `TestClient`, `FastAPI`,
  `APIRouter`, `Depends`, `HTTPException`, `field_validator`,
  `model_validator` — stdlib / third-party.

0 NEW phantoms expected.

### Hard-stop conditions (Builder must surface)

1. Test count delta diverges from +8 (≤ +6 or ≥ +10) — surface for triage.
2. Pre-flight gate fails on baseline 10942 — surface; do NOT begin build.
3. Any `tests/test_ad660_*.py` or `tests/test_ad658_*.py` test starts failing
   — surface; AD-661 is read-only over those surfaces and must not regress them.
4. `field_validator`/`model_validator` not already imported in `config.py`
   header — Builder may add the import to the existing pydantic import
   block; if pydantic version mismatch surfaces (AD-661 expects v2 syntax),
   surface to architect.

### Wave-specific reminders

- **Twin-block SEARCH/REPLACE in `api.py`**: import tuple + for-loop tuple
  bundled into one combined block. Pattern from Wave 31 / AD-659.
- **`_cognitive_journal` collision (AD-660 retrospective)**: not relevant
  here — `DiagnosticContextService` does NOT subclass `CognitiveAgent`.
  Just a reminder for future consumers.
- **Default-True deviation from Wave-10 convention**: confirm rationale
  documented in config docstring AND prompt body. Reviewer should not flag
  as Required.
- **No `EpisodicMemory.recall()` call**: any stray call to `recall()` is a
  scope violation (semantic search out-of-scope per user spec).
- **AD-434 Ship's Records**: `runtime.records_store` MUST NOT be referenced
  by `diagnostic_context.py` in v1. Deferred to AD-661b.

### Per-commit quality gates

Before commit:
1. `pytest tests/test_ad661_diagnostic_context.py -v -n 0` (focused) → 8/8 pass.
2. `pytest tests/ -q -n 8 --dist=loadfile` (full gate) → 10950 passed (15 skipped baseline).
3. Phantom-API pre-check clean (FPs only).
4. Verify `runtime.diagnostic_context_service` constructed under default config
   via a one-shot Python REPL boot (optional — skip if `_wire_diagnostic_context`
   covered by tests).

### Commit message

```
AD-661 v1: DiagnosticContextService — pull-based diagnostic bundle assembly (#320)

- New src/probos/cognitive/diagnostic_context.py — DiagnosticBundle frozen
  dataclass + DiagnosticContextService aggregator over AD-658 chain traces
  + AD-657 procedure exemplars + deduped episode bodies. Token-budgeted
  (40/30/30 split, configurable). Keyword filter only — NO semantic search.
- New src/probos/routers/diagnostic_context.py — GET /api/diagnostic-context.
- DiagnosticContextConfig added to SystemConfig (default-enabled; deviation
  from Wave-10 convention rationale: read-only aggregator invisible until
  called).
- _wire_diagnostic_context in startup/finalize.py mirroring
  _wire_chain_optimizer sibling shape.
- Public attribute runtime.diagnostic_context_service.
- 8 tests at tests/test_ad661_diagnostic_context.py (exceeds 7 floor).

Closes #320.
```

### Trackers to update

- `PROGRESS.md`: add `AD-661 v1 CLOSED` paragraph at top of Wave-32 archive
  section (immediately above the AD-660 paragraph).
- `docs/development/roadmap.md`: flip AD-661 entry to ✅ (or insert if not
  yet listed under the "AD-66x cognitive scaffolding" cluster).
- `DECISIONS.md`: NO new entry (single-AD wave; covered by #320).
- `prompts/wave-plan.yaml`: id `"33"` → `status: complete`.
- `prompts/build-reports/`: add `wave-33-build.md` per Wave-32 precedent.

### GH issue close

```
gh issue close 320 --comment "AD-661 v1 closed in Wave 33 (commit <SHA>).
DiagnosticContextService shipped at src/probos/cognitive/diagnostic_context.py
— pull-based, token-budgeted (40/30/30) assembly of AD-658 chain traces +
AD-657 procedure exemplars + deduped episodes. Keyword filter only (no
semantic search). New router at /api/diagnostic-context.
runtime.diagnostic_context_service public attribute. +8 tests.
Deferred: AD-661b (Ship's Records integration), AD-661c (remainder
redistribution), AD-661d (semantic search), AD-661e (summary fallback),
AD-661f (department/tier filters)." --reason completed
```

---

## Post-sweep

- Update session memory `/memories/session/wave-14-pass-2.md` with Wave-33
  build entry.
- No BF entries expected.
- Wave 34 (AD-647) is next per `wave-plan.yaml`.
