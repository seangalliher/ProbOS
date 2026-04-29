# Builder Execution Plan — 2026-04-29 Sweep

**Date:** 2026-04-29
**Author:** Architect
**Mode:** Continuous build (no inter-prompt pause)
**Active prompts:** 3 (BF-247, BF-246, AD-680)
**Estimated tests added:** ~17 (4 + 9 + 4)

---

## Inputs

Read these in full **before** writing any code:

1. `.github/copilot-instructions.md` — engineering principles, testing standards,
   logging standards, type-annotation rules. Every commit must comply.
2. `prompts/Reviews/README-2026-04-29-third-pass.md` — verdict and build order context.
3. The three prompt files (in build order):
   - `prompts/bf-247-tiered-knowledge-dag-summary-type.md`
   - `prompts/bf-246-llm-tier-recovery-deadlock.md`
   - `prompts/ad-680-expose-runtime-public-properties.md`
4. The corresponding per-prompt review files in `prompts/Reviews/` — they call out
   nits and edge cases the prompts themselves don't repeat.

---

## Pre-flight Checklist

Run these once before starting:

```pwsh
# Working tree clean (no tracked-file modifications). Untracked runtime artifacts
# (data/, *.log, etc.) are OK.
git status --short

# Full test gate is currently green
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n auto
```

If either check fails, stop and surface the failure. Do **not** proceed onto a dirty
working tree or a red baseline.

Record the baseline test count from the pytest summary line — you'll compare against
it after each prompt.

---

## Build Order and Per-Prompt Workflow

Execute in this order. **Do not skip ahead.** Each prompt produces exactly one commit.

### Wave A

#### 1. BF-247 — TieredKnowledgeLoader Tests

- **Risk:** Lowest. Test-only follow-up; production fix already landed in `8be47d5`.
- **Files touched:** `tests/test_ad585_tiered_knowledge.py`, `PROGRESS.md`,
  `docs/development/roadmap.md`.
- **Procedure:**
  1. Read `tests/test_ad585_tiered_knowledge.py` to understand the existing
     `_FakeEpisode` and `_FakeKnowledgeSource` fixtures.
  2. Add the 4 tests listed in the prompt.
  3. Run `pytest tests/test_ad585_tiered_knowledge.py -v -n 0` — verify all 32+4 pass.
  4. Run `pytest tests/ -q -n auto` — verify the gate is green.
  5. Update PROGRESS.md and roadmap.md per the Tracking section.
  6. Write build report `prompts/build-reports/bf-247-tiered-knowledge-build.md`.
  7. Commit: `BF-247: TieredKnowledgeLoader dag_summary tests`.

#### 2. BF-246 — LLM Health Probe

- **Risk:** Medium. New background async loop; touches startup wiring.
- **Files touched:** `src/probos/cognitive/llm_client.py`,
  `src/probos/config.py`, `src/probos/startup/finalize.py`,
  `tests/test_bf246_llm_health_probe.py`, PROGRESS.md, roadmap.md.
- **Procedure:**
  1. Read each section of the prompt in order. The Steps in Section 1 are sequential
     (1a → 1e). Apply them one at a time, not all at once.
  2. **Critical:** initialize `_health_probe_task` and `_health_probe_emit` in
     `__init__` (Step 1a). Do not initialize them inside `start_health_probe`.
  3. Use `runtime.emit_event` (public method) in Section 3, not `runtime._emit_event`.
  4. The `field_validator` in Section 2 must reject values < 5.0.
  5. Test 9 instantiates `SystemConfig` — match the existing pattern in
     `tests/test_config.py` (minimal valid config, not bare `SystemConfig()`).
  6. Run `pytest tests/test_bf246_llm_health_probe.py -v -n 0` — all 9 pass.
  7. Run `pytest tests/ -q -n auto` — gate green.
  8. Update PROGRESS.md, roadmap.md per Tracking.
  9. Build report, commit: `BF-246: LLM tier recovery health probe`.

### Wave B

#### 3. AD-680 — Public Runtime API Promotion

- **Risk:** Highest blast radius. Migration touches ~8 files and ~70 call sites.
- **Files touched:** `src/probos/runtime.py`, `src/probos/protocols.py`, plus the 8
  files in Section 3 and the 4 files in Section 4 of the prompt, plus
  `tests/test_ad680_public_runtime_api.py`, PROGRESS.md, roadmap.md, DECISIONS.md.
- **Procedure:**
  1. **Section 1 first** — widen the `emit_event` type hint on both `runtime.py` and
     `protocols.py`. Run the gate before continuing — this should be a no-op
     behaviorally.
  2. **Section 2 next** — add the `emergence_metrics_engine` property. Run the gate.
  3. **Section 3 — call-site migration.** Before editing, run the grep yourself:

     ```pwsh
     # Find all external _emit_event accesses
     d:/ProbOS/.venv/Scripts/python.exe -c "import re,pathlib; [print(f'{p}:{i+1}: {l.rstrip()}') for p in pathlib.Path('src/probos').rglob('*.py') if p.name != 'runtime.py' for i,l in enumerate(p.read_text(encoding='utf-8').splitlines()) if re.search(r'(runtime|rt|self\._runtime)\._emit_event', l)]"
     ```

     Confirm the file count and approximate counts match the prompt. Migrate
     **one file at a time**, running the relevant test file after each. Use
     `multi_replace_string_in_file` only within a single file, not across files.

     **Critical disambiguation:** the prompt's "Do NOT touch" subsection is
     binding. `self._emit_event` on `TrustNetwork`, `CognitiveQueue`,
     `WardRoomService`, etc. are unrelated callback attributes. They must NOT be
     migrated. The grep above includes the `runtime|rt|self\._runtime` prefix
     specifically to avoid those false positives — preserve that prefix when
     matching.

  4. **Section 4 — `_emergence_metrics_engine` migration.** 8 sites in 4 files.
     Keep the `getattr(..., None)` pattern; only the attribute name changes.
  5. Add the 4 tests in `tests/test_ad680_public_runtime_api.py`. Test 4 is the
     regression guard — it scans `src/probos/` (excluding `runtime.py`) for
     `runtime\._emit_event|rt\._emit_event|self\._runtime\._emit_event` and asserts
     zero matches. After Section 3 is complete, this should pass.
  6. Run `pytest tests/test_ad680_public_runtime_api.py -v -n 0` — all 4 pass.
  7. Run `pytest tests/ -q -n auto` — gate green. This is the test that proves the
     bulk migration didn't break anything.
  8. Update PROGRESS.md, roadmap.md, **and DECISIONS.md** (record the
     "no deprecation warning, one-shot migration" precedent per the prompt's
     Tracking section).
  9. Build report, commit: `AD-680: Promote runtime emit_event and emergence_metrics_engine to public API`.

---

## Per-Commit Quality Gates

Every commit must pass these checks before you advance to the next prompt:

- `pytest tests/ -q -n auto` exits 0 (apply standard xdist worker-crash triage rule
  from the user-memory: re-run any failing files in serial with `-n 0`; only real
  failures block the gate).
- Test count is **non-decreasing** vs the baseline you recorded.
- No new files created outside what the prompt specifies.
- No `print()` calls added (use `logger`).
- All new public methods have type annotations.
- All new log messages have context (what failed + what next).
- `git status` shows only the files the prompt's Files Changed section anticipates.

If any of these fail, **stop**, fix, re-run the gate, then commit. Do not move on
with a dirty gate.

---

## Hard-Stop Conditions

Stop the continuous build and report back to the architect immediately if any of
these occur:

1. **Phantom API in implementation** — the prompt asserts a method exists, but grep
   shows it does not. Do not invent the method. Stop and surface.
2. **Architectural change required** — the work cannot be completed without
   modifying `BaseAgent`, `IntentMessage`, `RuntimeProtocol`, or any public
   protocol contract beyond what the prompt explicitly specifies.
3. **Test gate goes red and the failure is not in your changed files.** This means
   a flaky test or environmental issue — re-run once in serial; if it persists,
   stop.
4. **Working tree contains tracked-file modifications you didn't make** — do not
   `git stash` or `git reset --hard` to "clean up." Stop and surface.
5. **Existing test assertions need to change in a way the prompt didn't anticipate.**
   This is a sign the prompt's "What This Does NOT Change" section is wrong. Stop.

The user-memory captures the lesson: phantom APIs and architectural changes are
the two real hard-stop categories. Anything else is normal build friction — work
through it.

---

## Anti-Patterns to Avoid

Per `prompts/Reviews/` cross-cutting findings:

- **Defensive `getattr(obj, "method", None)` for APIs defined in the same prompt.**
  If you just defined the method, call it directly.
- **`else: # Only for unit tests` fallback branches in constructors.** Tests pass
  real `Config()` instances. No fallback.
- **Bare mutable defaults in Pydantic models.** Use `Field(default_factory=...)`.
- **Frozen dataclass field ordering.** Defaulted fields must come after non-defaulted.
- **Private-attr access in wiring code.** AD-680 is in this batch specifically to
  eliminate this pattern. Don't reintroduce it elsewhere.

---

## Build Reports

After each commit, write a build report at
`prompts/build-reports/<prompt-stem>-build.md` matching the existing format in
`prompts/build-reports/archive/`:

- Title, prompt path, builder identity, date, status
- Files Changed
- Sections Implemented (one bullet per `###` section in the prompt)
- Post-Build Section Audit
- Test results (commands run, pass/fail counts)
- Any deviations from the prompt and why

These reports are read by the architect to verify the prompt was implemented
faithfully.

---

## Post-Sweep

After all three prompts are committed:

1. Run the full gate one more time: `pytest tests/ -q -n auto`.
2. Confirm the test count grew by ~17 (4 + 9 + 4 — exact may vary).
3. Move all three completed prompts to `prompts/archive/` (matching the convention
   used for prior closed prompts).
4. Move the per-prompt review files from `prompts/Reviews/` to
   `prompts/Reviews/archive/`.
5. Surface a final summary message: which commits landed, final test count, any
   deferred nits from the per-prompt reviews.

---

## Reference: User-Memory Lessons Applied to This Sweep

- "Continuous build mode (one AD = one commit, no inter-AD pause) works for batches
  of ~20 ADs." → 3 prompts is well under 20; continuous mode is appropriate.
- "Don't use `-x` with xdist — a single artifact kills the whole gate signal." →
  Use `-n auto` for full gate, `-n 0` only for triaging individual failing files.
- "Worker-crash failures from concurrent heavy-fixture boots are normal noise —
  re-run failing files in serial to triage." → Apply this rule when interpreting
  the gate.
- "Pre-flight every prompt against the actual codebase before the final approval
  pass." → All three prompts have a "Verified Against Codebase" section. Trust
  it but run your own grep for Section 3 of AD-680 (the largest migration).
