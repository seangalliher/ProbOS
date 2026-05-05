# Wave 50 Dispatch — AD-686b v1

## Builder execution context

- **Branch:** `main` (continuous-build wave; no separate feature branch).
- **Single AD:** AD-686b. Single commit per the standing convention.
- **Wave plan id:** `50` (`prompts/wave-plan.yaml`). State file `prompts/wave-orchestrator-state.json` is at Wave 50 already after the Wave 49 archive.
- **Test gate:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile`. Test-count baseline 11158 (Wave 49). Expected after build: 11170 (+12).
- **Branch protection:** EMU 403 still blocks GH issue close from the agent — leave #414 open with a close comment, user closes manually.

## Prompt to apply

`prompts/ad-686b-oracle-semantic-write-path-v1.md`

## Issues to close

- `#414` — Oracle should own end-to-end SemanticKnowledgeLayer (write-path migration).

## Constraints (highest-risk, repeated for redundancy)

1. **`write_semantic(kind, /, **fields) -> bool`** is the ONE public method. Five kinds: `"agent"` / `"skill"` / `"workflow"` / `"qa_report"` / `"event"`. Do NOT add per-kind helper methods (e.g. `Oracle.index_agent`). Dispatch is keyword-driven on `kind`.
2. **SemanticKnowledgeLayer is unchanged.** Five `async def index_*` methods stay exactly as they are. The dispatcher resolves them via `getattr(layer, f"index_{kind}", None)` — renaming any of them breaks the contract.
3. **Drop the `if self._semantic_layer:` guard + inline try/except at every migrated site.** Oracle handles None and exceptions internally. Test #12 statically locks the migration: zero `_semantic_layer.index_*(` references in `runtime.py`, `self_mod_manager.py`, `routers/chat.py` after build.
4. **`runtime._semantic_layer` attribute STAYS** (DLog #3). `agents/introspect.py:764` read-path fallback and `runtime.py:2973-2974` stats-panel call both still consume it. Do not delete the field, do not rename to `_internal_semantic_layer`, do not move it to `runtime.oracle._semantic_layer`. AD-686c will revisit.
5. **`self_mod_manager.py` keeps the `semantic_layer` ctor kwarg + `self._semantic_layer` field.** Migration only changes the call site at line 142. The ctor surface is AD-686c territory.
6. **Migration sites use `runtime.oracle` first**, with `getattr(rt, "oracle", None) or getattr(rt, "_oracle_service", None)` chain in `self_mod_manager.py` (Section 4) and `routers/chat.py` (Section 5) where the code holds a runtime reference (not `self`) and may receive a stub in tests. The two `runtime.py` sites use `self.oracle` directly — `self.oracle` is set unconditionally at `runtime.py:1344` so no fallback needed there.
7. **`routers/chat.py` `semantic_indexed` flag is fed by the bool return of `write_semantic`.** Do not add an inner try/except — the dispatcher already swallows; bool is the signal.
8. **Test #12 is a static migration lock.** It opens the three migrated source files and asserts zero direct `_semantic_layer.index_*(` writes. If a Builder pass leaves any in place, this test fails — that's the point.
9. **`index_workflow` / `index_event` ship in the dispatcher with no migration site.** Tests #4 and #6 exercise them directly via Oracle. Do NOT search for callers to migrate — none exist at HEAD (only `reindex_from_store` invokes them internally on `self`, which is out of scope).
10. **No deletion of `runtime.oracle` or any read-path tier.** AD-686 v1 read-path tests must continue to pass unchanged. AD-688 / AD-695 / AD-692 tier wiring is untouched.

## Pre-flight checklist

1. `git status` clean (no unstaged changes other than Builder's incoming work).
2. `git pull` to confirm HEAD = `d0f2eab` (Wave 49) or later.
3. Run `pytest tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5` for the baseline. Confirm 11158 passing.
4. Apply prompt sections 0–6 in order. Section 0 is a single SEARCH/REPLACE in `oracle_service.py`. Sections 1–5 are five SEARCH/REPLACE blocks (3 in `runtime.py`, 1 in `self_mod_manager.py`, 1 in `routers/chat.py`) — bundle into a single `multi_replace_string_in_file` per the Wave 31/33/45/49 pattern. Section 6 creates the new test file.
5. Run the new test file in isolation: `pytest tests/test_ad686b_oracle_write_semantic.py -v -n 0`. Must show 12 passing.
6. Run the AD-686 read-path back-compat tests: `pytest tests/test_ad686_oracle_semantic_tier.py -v -n 0`. Must remain green unchanged.
7. Run the full gate at `-n 8 --dist=loadfile`. Expected 11170 ± xdist variance.

## Hard-stop conditions

- **Architectural change required.** If migration of any of the 5 sites needs a contract change on `OracleService` beyond `write_semantic` (new method, new ctor kwarg, new public attribute) — STOP. Surface to architect.
- **A test in `tests/test_ad686_oracle_semantic_tier.py` regresses.** That's the AD-686 v1 read-path lock; it must stay green. STOP if any test there fails post-migration.
- **`reindex_from_store` semantic test (if any exists) regresses.** Internal `self.index_*` calls must keep working.
- **`runtime.py:2973-2974` `_semantic_layer.stats()` access broken.** That call site is intentionally NOT migrated (DLog #3); if a Builder pass deletes `runtime._semantic_layer`, the system-status panel breaks. STOP.

## Tracker updates after build

PROGRESS.md prepend the new CLOSED entry above the AD-647c paragraph (Wave 49 entry). Roadmap.md flip AD-686b status to Complete. DECISIONS.md prepend the AD-686b entry above `### AD-686` (or above the latest Era V header per Wave 49 prepend pattern).

## Build report

Standard one-liner build report at end-of-build:
- AD-686b v1 shipped clean.
- Test count delta: 11158 → 11170 (+12).
- Drift-fixes: list any deviations during build (expected: 0).
- Single commit message: `Wave 50 build: AD-686b v1 Oracle write-path migration (#414)`
- Push origin/main.
- GH issue close: BLOCKED by EMU 403. User closes #414 manually.
