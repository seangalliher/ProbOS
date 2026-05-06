# WAVE 68 DISPATCH — AD-572b-e Captain Engagement Extensions (No-Build Close, 4→0 Reframe)

**Wave id:** 68
**ADs in scope:** AD-572b, AD-572c, AD-572d, AD-572e
**Closes:** GH issue #109 (partial — three children shipped earlier; one wholesale-deferred to AD-572d-i)
**Baseline test count:** 11411 (HEAD `266391c`, post-Wave-67) → expected **11411** (+0; no code changes)
**HEAD at draft:** `266391c`, working tree clean
**Builder:** **NOT required** — every child of the AD-572 family is already resolved at HEAD

## Reframe Summary (Wave-10 pattern, more extreme: 4→0)

Wave 68 was queued as a 4-AD combo (AD-572b/c/d/e) per `prompts/wave-plan.yaml` id=68. Verify-first against HEAD `266391c` reveals **none of the four are outstanding work** — the queue resume tracker (`/memories/session/wave-queue-resume.md`) was operating on stale 2026-04-06 issue scope, identical to Wave 67's situation. Reality at HEAD `266391c`:

| Child | Outstanding? | Source-of-truth | Shipped |
|---|---|---|---|
| **AD-572b** | ❌ NO — shipped Wave 8 (Combo A) | `captain_engagement.py:23` `CaptainEngagementProvider`; wired in `startup/finalize.py:1655-1662` | commit `16c4ea4` |
| **AD-572c** | ❌ NO — shipped Wave 13 (Combo C) | `captain_engagement.py:118` `wardroom_activity_summary()` async helper; injected at `proactive.py:1196-1206` | commit `ffda515` |
| **AD-572d** | ❌ NO — wholesale-deferred to AD-572d-i | hard forcing function: `proactive.py` `_think_loop` (line 477) uses bare `asyncio.sleep(self._interval)` at lines 482 and 489; zero `asyncio.Event`/`asyncio.wait_for` anywhere in `proactive.py`. Adding interruptible-wait is architectural surgery on the BF-211-hardened think loop. Documented at `DECISIONS.md:597` and `docs/development/roadmap.md:4582` | NOT a Wave-68-buildable item |
| **AD-572e** | ❌ NO — shipped Wave 18 | `captain_engagement.py:163` `task_awareness(agent_id)` async helper; injected at `proactive.py:1207-1215`; 12 tests in `tests/test_ad572e_task_awareness.py` | commit `9ff7fed` |

**Reframe verdict: ship nothing. Partially close #109** with a summary table listing (3 shipped + 1 deferred-with-forcing-function). Same Wave-10 architectural-honesty-over-scope pattern Wave 67 applied 5→1; Wave 68 takes it 4→0 because every shippable child landed in earlier waves and the only remaining child is hard-blocked on a sibling forcing function.

## What this dispatch does

This is a **doc-and-orchestration-only** wave. There is no source code to write, no test to add, no migration to run. The wave's deliverables are:

1. Update `prompts/wave-plan.yaml` id=68: `status: done`, `builder_required: false`, drop the never-drafted `prompts/ad-572b-e-captain-engagement-combo.md` from `prompt_paths`, add a `notes:` block documenting the 4→0 reframe.
2. Archive this dispatch (`git mv prompts/WAVE-68-DISPATCH.md prompts/archive/WAVE-68-DISPATCH.md`) once committed.
3. Close GH issue #109 with the partial-completion summary in the close comment.
4. Append a CLOSED paragraph to `PROGRESS.md` referencing the reframe and the still-deferred AD-572d-i.

## Architect calls (Decision Log)

- **DLog #1 — No new AD entries.** AD-572b/c/e already have DECISIONS.md entries shipped via their respective waves. AD-572d already has a `→ AD-572d-i` deferral entry at `DECISIONS.md:597` (Combo C). Wave 68 adds no AD because Wave 68 ships no code. PROGRESS.md gets a CLOSED paragraph naming Wave 68 as the explicit issue-closure event; that is the only durable architectural record produced by this wave.

- **DLog #2 — Issue #109 closes partial, not full.** AD-572d is still listed in the issue body but is genuinely deferred-with-forcing-function, not abandoned. The close comment must say so explicitly: "3 of 4 children shipped (AD-572b/c/e); AD-572d is wholesale-deferred to AD-572d-i pending interruptible-wait infra on `_think_loop`." This preserves the audit trail for the future AD-572d-i shipment.

- **DLog #3 — No per-AD prompt file.** `prompts/ad-572b-e-captain-engagement-combo.md` was never drafted (`prompts_already_drafted: false` in id=68). Nothing to archive on that path. The wave-plan entry is updated to remove the dead reference rather than create-and-archive an empty document.

- **DLog #4 — Builder gate skipped, not failed.** `builder_required: false` is the orchestrator's designed escape hatch (already used by id=8.5 the AD-641 split meta-wave). The orchestrator will not invoke the Builder for Wave 68; the doc/orchestration tasks listed under "What this dispatch does" are Captain-side commits.

- **DLog #5 — AD-572d-i forcing function unchanged.** Verified at HEAD `266391c`:
  - `proactive.py:477` — `async def _think_loop(self) -> None:`
  - `proactive.py:482` — `await asyncio.sleep(self._interval)` (think-loop body)
  - `proactive.py:489` — `await asyncio.sleep(self._interval)` (think-loop body)
  - `proactive.py:591` — `await asyncio.sleep(stagger_delay)` (stagger, not interruption point)
  - `proactive.py:798` — `await asyncio.sleep(_backoff)` (backoff, not interruption point)
  - Zero `asyncio.Event` / `asyncio.wait_for` constructs anywhere in `proactive.py`.

  Combo C documented the same architectural state at `DECISIONS.md:597` (under different line numbers from a prior HEAD; semantically unchanged). AD-572d-i remains correctly deferred. A future AD that introduces `asyncio.Event` / `asyncio.wait_for` on `_think_loop` will unblock AD-572d-i mechanically.

- **DLog #6 — Test count delta = 0.** No code changes, no test changes. Pre-flight `pytest tests/ -q -n 4 --dist=loadfile` should still report 11411. If it doesn't, the regression is not from Wave 68; investigate as a separate baseline-rot triage.

- **DLog #7 — Roadmap entry already accurate.** `docs/development/roadmap.md:4582` already documents the complete state of AD-572b/c/e as `*complete*` with shipping-wave provenance, and AD-572d as `*still deferred to AD-572d-i*` with the forcing function. No roadmap edit required for Wave 68; the file was kept current by Wave 13 (AD-572c entry edit) and Wave 18 (AD-572e entry edit). Verified by grep against `roadmap.md:4582` — the line carries `*complete via Combo A*`, `*complete via Combo C*`, `*complete*` (for 572e), and `*still deferred to AD-572d-i*` (for 572d).

- **DLog #8 — Wave-10 reframe APPLIED at AD-scoping, second consecutive instance.** Wave 67 reframed 5→1 last cycle on the AD-573 family. Wave 68 reframes 4→0 on the AD-572 family. The pattern is now reflexive on combo waves whose parent ADs were partial-closed in earlier waves: verify each child's HEAD status before assuming the queue is honest. The session memory tracker `/memories/session/wave-queue-resume.md` is the staleness source; it was authored 2026-04-06 and has not been refreshed against post-Wave-13 / post-Wave-18 reality. Future combo waves (id=69 AD-574b-c, id=70 AD-526c-h) must verify-first the same way.

- **DLog #9 — Commercial-leak audit: clean.** Wave 68 ships zero code and adds zero new AD entries. The dispatch document contains:
  - One reframe table (architectural status per child).
  - A description of the deferred AD-572d-i forcing function (`_think_loop` lacks `asyncio.Event`/`wait_for`).
  - A list of doc/orchestration tasks (yaml edit, archive, issue close, PROGRESS.md append).
  - Zero pricing, revenue model, customer counts, professional-services positioning, competitive analysis, GTM language, or `*(Commercial)*` deferral entries.

  Verified clean against the boundary rule from `.github/copilot-instructions.md` ("Repository Boundary — OSS vs Commercial").

- **DLog #10 — Phantom-API pre-check N/A.** Wave 68 ships no code. No symbols to pre-check. The recurring `scripts/phantom-api-precheck.ps1` parser FP that has trailed Waves 52–67 is irrelevant here.

## Captain workflow (no Builder)

1. **Pre-flight verification.** Run `pytest tests/ -q -n 4 --dist=loadfile` and confirm 11411 collected at HEAD `266391c`. If the count drifts, investigate baseline rot before proceeding (the rot is not from Wave 68).

2. **Update `prompts/wave-plan.yaml`** entry id=68 (replace the existing block):

   ```yaml
     - id: "68"
       title: "AD-572b-e Combo Captain Engagement Extensions (no-build close, 4→0 reframe)"
       kind: combo
       depends_on: ["67"]
       dispatch_prompt: "prompts/WAVE-68-DISPATCH.md"
       prompts_already_drafted: true
       prompt_paths: []
       builder_required: false
       issues_to_close: [109]
       status: done
       notes: |
         Wave-10 reframe applied at AD scoping (4→0). Every child of the
         AD-572 family is already resolved at HEAD 266391c:
           - AD-572b shipped Wave 8 (Combo A, commit 16c4ea4)
           - AD-572c shipped Wave 13 (Combo C, commit ffda515)
           - AD-572d wholesale-deferred to AD-572d-i (forcing function:
             interruptible-wait infra on proactive.py _think_loop at line
             477; verified zero asyncio.Event/wait_for in proactive.py at
             HEAD; documented at DECISIONS.md:597 and roadmap.md:4582)
           - AD-572e shipped Wave 18 (commit 9ff7fed)
         No code shipped this wave. Issue #109 closes via partial-completion
         summary in the close comment. The per-AD combo prompt
         (prompts/ad-572b-e-captain-engagement-combo.md) was never drafted
         and is intentionally absent from prompt_paths.
   ```

3. **Append to `PROGRESS.md`** a CLOSED paragraph in the same shape used by Wave 67's close. Suggested text:

   > **Wave 68 (AD-572b-e Captain Engagement Extensions): CLOSED via 4→0 reframe.** Verify-first at HEAD `266391c` confirmed all four children resolved earlier: AD-572b (Wave 8, `16c4ea4`), AD-572c (Wave 13, `ffda515`), AD-572e (Wave 18, `9ff7fed`); AD-572d wholesale-deferred to AD-572d-i pending interruptible-wait infra on `proactive.py _think_loop` (forcing function documented at `DECISIONS.md:597`). No code shipped. Test count unchanged at 11411. Issue #109 closed with partial-completion summary.

4. **Commit and push** the wave-plan edit + PROGRESS.md append:

   ```
   git add prompts/wave-plan.yaml PROGRESS.md
   git commit -m "Wave 68 close: AD-572b-e combo (4→0 reframe; no-build) (#109)"
   git push
   ```

5. **Archive this dispatch:**

   ```
   git mv prompts/WAVE-68-DISPATCH.md prompts/archive/WAVE-68-DISPATCH.md
   git add -A
   git commit -m "Wave 68 archive: WAVE-68-DISPATCH (no-build close)"
   git push
   ```

6. **Close issue #109** with the suggested comment:

   > Closed by Wave 68 (no-build, 4→0 reframe). HEAD `266391c`. Verify-first against HEAD revealed every child of the AD-572b-e combo is already resolved:
   >
   > | Child | Status | Where |
   > |---|---|---|
   > | AD-572b | ✅ Shipped Wave 8 (Combo A) | commit `16c4ea4` — `captain_engagement.py:23` + `finalize.py:1655` |
   > | AD-572c | ✅ Shipped Wave 13 (Combo C) | commit `ffda515` — `captain_engagement.py:118` + `proactive.py:1196` |
   > | AD-572d | 🟡 Wholesale-deferred to AD-572d-i | forcing function: interruptible-wait infra on `proactive.py _think_loop` (`DECISIONS.md:597`) |
   > | AD-572e | ✅ Shipped Wave 18 | commit `9ff7fed` — `captain_engagement.py:163` + `proactive.py:1207` + `tests/test_ad572e_task_awareness.py` (12 tests) |
   >
   > AD-572d-i ships only when a separate AD introduces `asyncio.Event` / `asyncio.wait_for` interruptible-wait on the BF-211-hardened think loop. Until then, AD-572d remains correctly deferred.

## What this AD wave does NOT change

- **No code touched.** `src/probos/cognitive/captain_engagement.py`, `src/probos/proactive.py`, `src/probos/startup/finalize.py`, and `tests/test_ad572e_task_awareness.py` are unchanged.
- **No new tests.** Test count stays at 11411.
- **No new EventType.** No new Pydantic config field. No new public attribute. No schema migration.
- **No DECISIONS.md edit.** The architectural record for AD-572b/c/e/d-i is already complete in earlier waves.
- **No roadmap edit.** `docs/development/roadmap.md:4582` already reflects the complete state.
- **AD-572d-i is NOT shipped.** Its forcing function (interruptible-wait on `_think_loop`) is not satisfied at HEAD `266391c`. Future AD that introduces `asyncio.Event`/`wait_for` on the proactive think-loop unblocks AD-572d-i; until then it stays deferred.

## Acceptance criteria

- `prompts/wave-plan.yaml` id=68 entry updated with `status: done`, `builder_required: false`, empty `prompt_paths`, and the reframe `notes:` block.
- `PROGRESS.md` carries a CLOSED paragraph for Wave 68.
- This dispatch is archived to `prompts/archive/WAVE-68-DISPATCH.md`.
- GH issue #109 is closed with the partial-completion summary.
- Pre-flight and post-edit `pytest tests/ -q -n 4 --dist=loadfile` both report 11411 collected (delta = 0).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-05, HEAD 266391c)

```
grep -n "class CaptainEngagementProvider" src/probos/cognitive/captain_engagement.py
  23: class CaptainEngagementProvider:

grep -n "wardroom_activity_summary" src/probos/cognitive/captain_engagement.py
  118:     async def wardroom_activity_summary(self) -> dict[str, Any]:
  134:                 "wardroom_activity_summary returns empty dict",
  180:         ``wardroom_activity_summary()`` error handling).

grep -n "task_awareness" src/probos/cognitive/captain_engagement.py
  163:     async def task_awareness(self, agent_id: str) -> dict[str, Any]:

grep -n "wardroom_activity_summary\|task_awareness" src/probos/proactive.py
  1196:             if hasattr(engagement_provider, "wardroom_activity_summary"):
  1198:                     summary = await engagement_provider.wardroom_activity_summary()
  1200:                         context["captain_engagement"]["wardroom_activity_summary"] = summary
  1203:                         "AD-572c: wardroom_activity_summary failed", exc_info=True,
  1207:             if hasattr(engagement_provider, "task_awareness"):
  1209:                     task_summary = await engagement_provider.task_awareness(agent.id)
  1211:                         context["captain_engagement"]["task_awareness"] = task_summary
  1214:                         "AD-572e: task_awareness injection failed", exc_info=True,

grep -n "CaptainEngagementProvider" src/probos/startup/finalize.py
  1655:         from probos.cognitive.captain_engagement import CaptainEngagementProvider
  1656:         runtime.captain_engagement_provider = CaptainEngagementProvider(

grep -nE "asyncio\.sleep|_think_loop|asyncio\.Event|asyncio\.wait_for" src/probos/proactive.py
  465:         self._task = asyncio.create_task(self._think_loop())
  477:     async def _think_loop(self) -> None:
  482:                 await asyncio.sleep(self._interval)
  489:                 await asyncio.sleep(self._interval)
  591:                 await asyncio.sleep(stagger_delay)
  798:             await asyncio.sleep(_backoff)
  (zero hits for asyncio.Event or asyncio.wait_for — AD-572d-i forcing function unmet)

git log --oneline -- src/probos/cognitive/captain_engagement.py tests/test_ad572e_task_awareness.py
  9ff7fed AD-572e: Task awareness in Captain DM context (final AD-572 child; 572d-i still deferred)
  ffda515 Combo C: AD-526d/572c/573c/573f/575c trivial extensions (572d + 573e wholesale-deferred)
  16c4ea4 Combo A: AD-538b/572b/573b/576b/526c/655/656 trivial extensions

ls tests/test_ad572e_task_awareness.py
  (file exists; 12 test functions)

grep -n "AD-572d" DECISIONS.md
  597:   - **AD-572d → AD-572d-i.** Captain DM intake should signal a wakeup to `_think_loop`. ...

grep -n "AD-572[a-z]" docs/development/roadmap.md
  4582: AD-572b ... *complete via Combo A*
  4582: AD-572c ... *complete via Combo C*
  4582: AD-572e ... *complete*
  4582: AD-572d ... *still deferred to AD-572d-i*
```

All claims in this dispatch grep-verify clean against HEAD `266391c`.
