# Wave 141 — Dispatch (Builder-facing)

**Date:** 2026-05-10
**Theme:** Avatar self-image cluster — manifest single-source-of-truth + adaptive sampling rate
**Cluster plan:** [prompts/BUILDER-EXECUTION-PLAN-avatar-cluster.md](BUILDER-EXECUTION-PLAN-avatar-cluster.md)
**ADs in this wave:** AD-722-1 (#572), AD-722f (#580)
**Mode:** Continuous build, two commits, agent-driven gates between them
**Architect approval:** clean (3 review passes documented in §6 below)

---

## 1. Context

Wave 140 shipped AD-722 v1: agents can now `observe_self_avatar()` and read a structured snapshot of their own avatar state (modulation, DSL identity, working state, mouth_active, trust_delta). Two follow-ups are needed before the rest of the avatar self-image cluster (Waves 142-145) can land cleanly:

1. **AD-722-1** retires the TS↔Python byte-parity duplication in the modulation rule table by extracting the constants to a JSON manifest. Pure refactor; no behaviour change. Drift becomes structurally impossible (one file, two readers).
2. **AD-722f** adds per-agent adaptive sampling rates (HIGH 250 ms during DMs / NORMAL 2000 ms during chain reasoning / LOW 10000 ms idle). Captain ruling: *"humans are more self-aware in public than alone."* The state machine lives on `runtime.avatar_sampling_state`; trigger surfaces are the existing DM-handler observe/mark sites and the chain caller in `cognitive_agent.decide()`.

Both ADs preserve AD-722's read-only contract on the snapshot side. AD-722f's writes are confined to `runtime.avatar_sampling_state` (volatile by design).

---

## 2. Build order (one prompt = one commit)

Build group A — sequential, no parallelism:

| # | Prompt | Commit message |
|---|---|---|
| 1 | [`prompts/ad-722-1-modulation-manifest.md`](ad-722-1-modulation-manifest.md) | `AD-722-1: extract modulation rule table to JSON manifest` |
| 2 | [`prompts/ad-722f-adaptive-sampling.md`](ad-722f-adaptive-sampling.md) | `AD-722f: per-agent adaptive avatar-telemetry sampling rate` |

**Why this order:** AD-722-1 is the smaller, lower-risk change and is purely additive (no public API changes). Landing it first establishes the manifest pattern and shrinks the diff surface for AD-722f's review. AD-722f does not depend on the manifest at the code level, but the conceptual lineage (config-extension shape, structural-vs-behavioural separation) makes the order natural.

Each prompt commits independently. Run the focused per-prompt test gate after each commit before proceeding.

---

## 3. Pre-flight checklist (before starting Wave 141)

```pwsh
# 1. Working tree must be clean (or only untracked runtime artifacts).
git status --short

# 2. Establish baselines.
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
# Record: pre-Wave-141 Python test count (= Wave 140 baseline).

cd ui; npx vitest run 2>&1 | Select-Object -Last 5; cd ..
# Record: pre-Wave-141 Vitest count. AD-722-1 must NOT change this; AD-722f must NOT change this.

# 3. Confirm no pending tracked changes from prior session.
git diff --stat
# Should print no output. If anything shows, surface to architect — DO NOT git stash, DO NOT git reset.
```

If the baseline pytest gate is red (tests failing pre-Wave-141), STOP. Surface to architect. Do not begin Wave 141 on a red baseline.

---

## 4. Per-commit workflow

### Commit 1: AD-722-1

1. Read [`prompts/ad-722-1-modulation-manifest.md`](ad-722-1-modulation-manifest.md) end-to-end before editing.
2. Apply deliverables D1 through D4 in order. D1 (manifest file) and D2 (Python loader) are tightly coupled — write both before running any test. D3 (TS loader) is independent. D4 (test rewrite) replaces one test with three.
3. After all deliverables are applied, run focused gate:
   ```pwsh
   d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad722_avatar_telemetry.py -v -n 0
   ```
   Expect: every existing case still passes; the 3 new tests pass; the deleted `test_modulation_byte_parity_with_ts` is gone (net delta +2).
4. Run the TS side:
   ```pwsh
   cd ui; npx vitest run; cd ..
   ```
   Expect: Vitest count unchanged. Any drift is a real failure — investigate.
5. Run the full parallel gate:
   ```pwsh
   d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
   ```
   Expect: Python test count = baseline + 2.
6. `git diff --cached --stat` — sanity-check the commit's deletion footprint. Anything that deletes more than ~20 lines in a file you didn't intentionally edit is a red flag.
7. Commit: `git commit -m "AD-722-1: extract modulation rule table to JSON manifest"`.

### Commit 2: AD-722f

1. Read [`prompts/ad-722f-adaptive-sampling.md`](ad-722f-adaptive-sampling.md) end-to-end.
2. Apply deliverables in dependency order: D1 (config) → D2 (state machine module) → D3 (runtime init) → D4 (snapshot extension) → D5 (router wiring) → D6 (cognitive_agent wiring) → D7 (tests). Order matters: D3 imports from D2; D4 reads from D3-bound runtime attribute; D5/D6 use the same; tests cover all of them.
3. Pay special attention to **D4** — `build_telemetry_snapshot` has multiple `return AvatarTelemetrySnapshot(...)` sites. Each one needs the new kwargs. Read the function body at HEAD before editing; missing a site causes silent test failure on the existing AD-722 cases (which pin the snapshot fields exactly).
4. After deliverables are applied:
   ```pwsh
   d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad722_avatar_telemetry.py tests/test_ad722f_adaptive_sampling.py -v -n 0
   ```
   Expect: AD-722 cases pass (now with `sampling_rate_ms`/`sampling_tier` populated); AD-722f cases all pass (≥ 14 new).
5. Full gate:
   ```pwsh
   d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
   ```
   Expect: Python test count = post-AD-722-1 baseline + ≥ 14.
6. Vitest baseline must be unchanged from start of wave — AD-722f does not touch UI.
7. `git diff --cached --stat` sanity check.
8. Commit: `git commit -m "AD-722f: per-agent adaptive avatar-telemetry sampling rate"`.

---

## 5. Test gates

| Gate | Command | When |
|---|---|---|
| Full parallel | `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile` | Pre-flight, after each commit, post-wave |
| Focused per-prompt | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad722*.py -v -n 0` | After each commit, before pushing the parallel gate |
| Vitest | `cd ui && npx vitest run` | Pre-flight, after AD-722-1 (must not change), end-of-wave (must not change) |

**`-n auto` is forbidden** until AD-682 lands. Use `-n 8` (verified ceiling on this codebase).

**Per-commit gate failure interpretation:** failures under the parallel gate that do NOT reproduce under `-n 0` are environmental — document and continue. Real failures that reproduce serially in files you changed are blockers.

---

## 6. Architect review status

Three review passes were run against `prompts/review-criteria.md` and `.github/copilot-instructions.md`. Findings:

**Pass 1 (verify-first):**
- ✅ Every API reference, import path, function signature, and line number in both prompts grep-confirmed against HEAD (2026-05-10).
- ✅ License check: zero new Python or JS deps. Apache 2.0 boundary preserved.
- ✅ Path-coherence: AD-722f's WR path correctly NOT wired (per AD-722 addendum (h)). State machine intentionally has no `enter_wr`/`exit_wr` methods; a phantom-API guard test asserts their absence.
- ✅ Phase-ordering audit: AD-722f's `runtime.avatar_sampling_state` initializes in `runtime.__init__()` adjacent to `self.profile_store` (line 408 region), NOT in `finalize.py`. Avoids the BF-259/260/261/262 trap.

**Pass 2 (revisions):**
- Refined the AD-722-1 Python loader to require schema-completeness (extra-keys rejection) so future drift via "TS adds a key, Python doesn't" is caught at import.
- Refined the AD-722f chain wiring to bracket at the **caller** (around `cognitive_agent.py:1394`), not inside `_execute_chain_with_intent_routing`, so fall-through to `_decide_via_llm()` correctly does not count as chain reasoning.
- Added the AD-722f spurious-exit clamp + WARNING log so an exception path between enter and exit cannot leak refcounts permanently.
- Added a try/finally around the chain call so an exception inside `_execute_chain_with_intent_routing` cannot leak the chain refcount.
- Added the snapshot-side tier-2 degrade helper `_resolve_sampling()` so unit tests with `MagicMock(spec=[])` runtimes do not break.

**Pass 3 (confirmation):**
- ✅ All Pass-2 revisions verified against codebase one more time (`grep` re-run on every changed reference).
- ✅ Engineering Principles compliance line present in both prompts.
- ✅ "Out of scope" tables explicit and forward-marker-tagged.
- ✅ No emoji in either prompt or in proposed code.
- ✅ Three-tier exception model honored — every new guard either swallows-with-justification, logs-and-degrades, or propagates appropriately.
- ✅ AD-numbering: highest AD at HEAD = **AD-729** (verified via `grep '^### AD-' DECISIONS.md` 2026-05-10 — AD-729 family is the most recent forward-marker entry). PROGRESS.md still cites AD-722 as highest, which is stale by 7 forward markers (AD-723 through AD-729); both ADs in this wave already have GH issues filed (#572, #580), so no new AD numbers are minted.
- Pass 3 found nothing new. Prompts are READY FOR BUILDER.

---

## 7. Hard-stop conditions

Surface to architect immediately if any of the following occur:

1. **Tracked-file modifications you didn't make** in `git status` before or during the wave. Do NOT `git stash`. Do NOT `git reset --hard`.
2. **Phantom API surface** — a method/attribute/import the prompt asserts exists but doesn't. Re-grep, then surface.
3. **Architectural change required** — the prompt cannot be built without modifying a base contract (BaseAgent / IntentMessage / AvatarTelemetrySnapshot in ways the prompt doesn't sanction).
4. **Vitest count changes for AD-722-1** — that AD must be a transparent refactor on the TS side. Any drift means the import path or bundling didn't work as architecturally specified; investigate before committing.
5. **Existing AD-722 boundary tests fail in AD-722f** — likely cause is a missed `AvatarTelemetrySnapshot(...)` construction site in `build_telemetry_snapshot` (D4). Re-read the function body at HEAD and confirm every return site has the two new kwargs.

---

## 8. Standing rules (carry forward from `.github/copilot-instructions.md`)

- **AD-numbering hard rule:** if any unforeseen need for a new AD/BF arises during the wave, read DECISIONS.md (PROGRESS.md is stale — current highest is **AD-729** per `grep '^### AD-' DECISIONS.md`), state the highest explicitly in your response, then assign sequentially. Never guess.
- **Forward markers must have GH issues:** AD-722-1 = #572 (already filed). AD-722f = #580 (already filed). No new forward markers are spawned by these prompts.
- **Pre-commit `git diff --cached --stat` deletion sanity check** — flagged in the Wave-10 lessons (user memory). Anything that wipes >200 lines you didn't author is a stop-the-line.
- **Three-tier exception handling** — both prompts use log-and-degrade for missing optional state (avatar_sampling_state) and propagate for required state (manifest absent → import fails).
- **Cloud-ready storage** — neither prompt adds DB access. State machine is in-memory by design.

---

## 9. Post-wave checklist

After both commits land and gates are green:

```pwsh
git log --oneline -5             # Confirm both commits present.
git diff HEAD~2 --stat           # Cluster-level diff sanity.
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
cd ui; npx vitest run 2>&1 | Select-Object -Last 5; cd ..
```

Update `PROGRESS.md`, `docs/development/roadmap.md`, and `DECISIONS.md` per each prompt's tracking table. Close GH issues #572 and #580 with a "shipped in Wave 141 (AD-722-1 + AD-722f)" comment, citing commit SHAs.

If anything is unclear or any pre-flight gate fails, STOP and surface to architect before proceeding.
