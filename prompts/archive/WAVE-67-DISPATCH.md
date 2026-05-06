# WAVE 67 DISPATCH — AD-573d v1 Dream-to-Working-Memory Pipeline (Combo Reframe)

**Wave id:** 67
**Single AD:** AD-573d (the LAST remaining buildable child of the AD-573b–f combo)
**Closes (partial):** GH issue #8 — three children already shipped, one wholesale-deferred to AD-573e-i, this AD ships the fifth and last
**Baseline test count:** 11401 (HEAD `fa6d83d`, post-Wave-66) → expected **11411** (+10 net), window **[+8, +12]**
**HEAD at draft:** `fa6d83d`, working tree clean
**Builder:** required

## Reframe Summary (Wave-10 pattern, more extreme: 5→1)

Wave 67 was originally queued as a 5-AD combo (AD-573b/c/d/e/f) per `prompts/wave-plan.yaml` id=67. Verify-first against HEAD reveals four of those five children are NOT outstanding work — the queue resume tracker (`/memories/session/wave-queue-resume.md`) was operating on stale 2026-04-06 issue scope. Reality at HEAD `fa6d83d`:

| Child | Outstanding? | Source-of-truth |
|---|---|---|
| **AD-573b** | ❌ NO — shipped Wave 8 (Combo A) | `working_memory.py:31-35,107-108,138-179` (3 snapshot fields + 3 ring helpers) |
| **AD-573c** | ❌ NO — shipped Wave 13 (Combo C, commit ffda515) | `cognitive_agent.py:1747` markers dict + `proactive.py:2806-2818` `[NOTE]` extractor |
| **AD-573d** | ✅ YES — last buildable | dream-to-WM pipeline; deferred from Combo C with forcing function `runtime.dream_scheduler` exposing summaries — VERIFIED satisfied (`dreaming.py:2807` `last_dream_report` property + `dream_adapter.py:108` `on_post_dream(dream_report)`) |
| **AD-573e** | ❌ NO — wholesale-deferred to AD-573e-i | hard forcing function: `cognitive/journal.py` lacks recency-ordered per-agent recall API. `get_decision_points` has wrong filter semantics (latency/failure-only). Documented at DECISIONS.md:599 + roadmap:4596. NOT a wave-67-buildable item; future AD-573e-i ships only when journal exposes the missing API |
| **AD-573f** | ❌ NO — shipped Wave 13 (Combo C, commit ffda515) | `working_memory.py:118-220` (`mark_commitment_complete`, `pending_commitments`, `expired_commitments`, `set_event_callback`) + `events.py` `COMMITMENT_RECORDED` |

**Reframe verdict: ship AD-573d alone. Partially close #8 noting (3 shipped + 1 deferred-with-forcing-function + 1 shipping-this-wave).** This is the same Wave-10 architectural-honesty-over-scope pattern, applied at AD scoping rather than per-AD code. Captain has been notified separately via the wave plan update; the dispatch document below is the build contract.

## Summary

ProbOS dream cycles (full + micro) consolidate ship cognition every ~10 minutes, producing rich `DreamReport` artifacts (`types.py:474`): clusters found, procedures extracted, contradictions resolved, convergence reports generated, notebook consolidations. None of this is currently surfaced into `WorkingMemoryManager.scratchpad` (the LLM-context-narrowing ring buffer that AD-573b/c built and AD-573c writes into via the `[NOTE]` action tag). Every cognitive pathway therefore wakes from a dream amnesic of what just consolidated.

AD-573d v1 closes the gap with a single producer-side branch in `DreamAdapter.on_post_dream`. Late-bound `WorkingMemoryManager` reference via ctor kwarg + finalize-side wiring. Pure-function `_summarize_dream_report(report) -> str | None` summarizer with empty-suppress semantics. One-line summary appended to scratchpad ring per dream cycle.

**No service-side change** to `WorkingMemoryManager`, `DreamScheduler`, `DreamReport`, `WorkingMemorySnapshot`. **No new EventType.** **No new Pydantic config.** **No new module.** **No new public attribute on runtime.**

**Deferred at the prompt level:**
- AD-573d-1 — render scratchpad in `WorkingMemorySnapshot.to_text()`. The fields exist on the snapshot at `working_memory.py:33` but the to-text serializer doesn't include them. Pre-existing AD-573b documentation gap; out of scope for AD-573d (which only writes to the ring; reading is downstream).
- AD-573d-2 — per-agent dream summary differentiation. `_agent_wm` (AD-671) is already wired into the dreaming engine for per-agent context; layering per-agent dream summary onto that surface needs separate scope.
- AD-573d-3 — *(Commercial)* tenant-scoped dream summary injection (per-mesh runtime resolver behind a tenant prefix). The OSS scratchpad write remains tenant-agnostic; the seam is the runtime injection point.

## Architect calls (Decision Log)

- **DLog #1 — Producer side, NOT service side.** `DreamAdapter` is the existing single point of truth for post-dream side effects (AD-237, AD-410, AD-557 all wire from here). Adding a third side effect (working-memory write) preserves the architectural pattern. Service-side (`WorkingMemoryManager`) stays unchanged.

- **DLog #2 — Late-bind via ctor kwarg, NOT setter.** `DreamAdapter`'s ctor at `dream_adapter.py:42` is a single explicit-construct callsite (`finalize.py:2414`); appending one optional kwarg is cleaner than introducing an `attach_working_memory()` setter pattern. Default `None` preserves backward-compat and lets test fixtures construct adapters without WM wiring (Wave 13 test fixture precedent for AD-573c writes into `runtime.working_memory` via Mock without going through the adapter).

- **DLog #3 — Module-level `_summarize_dream_report`, NOT method.** Pure function — no `self`, no I/O, no logging. Testable in isolation against synthetic `DreamReport` instances and `SimpleNamespace` objects without instantiating `DreamAdapter`. Mirrors the `_summarize_*` helper pattern used in AD-572c `wardroom_activity_summary` (Combo C).

- **DLog #4 — Empty-suppress semantics.** When every tracked field on the report is zero, `_summarize_dream_report` returns `None` and the caller skips the scratchpad write. Mirrors AD-630 subordinate-stats empty-suppress (`if sub_stats:` guard at `proactive.py:1813`) and AD-635f empty-summary suppression (DLog #12 of Wave 66). Avoids prompt clutter when a dream cycle finds nothing.

- **DLog #5 — Five tracked fields, NOT all 60+.** `DreamReport` has 60+ counter fields; surfacing all of them would blow LLM context budget. v1 reduces to the five most signal-dense fields: `clusters_found` (AD-531), `procedures_extracted` (AD-532), `contradictions_found` (AD-403), `convergence_reports_generated` (AD-551), `notebook_consolidations` (AD-551). Per-field labels are short ("clusters", "procedures", etc.). Selection rationale: these are the fields that represent novel emergence (cluster) or persistent learning (procedures + notebooks) or correction (contradictions + convergences). Counters like `episodes_replayed` are throughput metrics, not insights.

- **DLog #6 — Tier-ordering preservation.** Insertion point chosen specifically: AFTER the AD-557 emergence-metrics block (which emits events whose subscribers may read scratchpad downstream — but that's an architectural maybe, not a dependency), BEFORE the AD-237 emergent-detection block (which can raise on `analyze()` failure and hit the `except Exception:` guard at `dream_adapter.py:184`). Putting the WM write in the middle ensures the scratchpad lands even when emergent analysis fails. Test #10 locks this contract.

- **DLog #7 — Tier-2 log-and-degrade.** Every call wrapped in try/except → `logger.warning("AD-573d: dream summary scratchpad write failed", exc_info=True)` and contributes nothing on failure. Mirrors AD-635f DLog #7 + AD-573b's own `except Exception:` guards at `working_memory.py:140-143,162-163,167-179`. The dream-cycle caller never sees a working-memory failure.

- **DLog #8 — Public attribute via `getattr` defensive read.** `working_memory=getattr(runtime, "working_memory", None)` at the finalize callsite — defensive against synthetic test runtimes (e.g. AD-647c-style `SimpleNamespace` fixtures) that don't carry the attribute. Real `ProbOSRuntime` always has `runtime.working_memory` (constructed at `runtime.py:348`); `getattr` default `None` only matters for fixtures.

- **DLog #9 — `WorkingMemorySnapshot.to_text()` rendering gap left in place.** AD-573b shipped 3 new fields on the snapshot (`relational_links`, `scratchpad`, `commitments`) but `to_text()` at `working_memory.py:36-86` does NOT render them. AD-573d does not fix this. AD-573d is a write-path AD; the read-path rendering gap is a separate concern. Documented in "What this AD does NOT change". Future AD-573d-1 if surfaced.

- **DLog #10 — System-level WM, NOT per-agent `_agent_wm`.** Two working-memory surfaces exist: (a) `runtime.working_memory: WorkingMemoryManager` (system-level, AD-28+, the surface AD-573b/c built and AD-573c writes to via `add_scratchpad`); (b) `runtime.agent_working_memory` / `_agent_wm` (per-agent `AgentWorkingMemory`, AD-573, AD-671 wired into dreaming for per-agent context). AD-573d targets surface (a) — the one whose scratchpad ring exists today, with the `add_scratchpad` API already shipped. Per-agent dream summarization (surface b, plus per-agent fan-out) is AD-573d-2.

- **DLog #11 — No new EventType.** AD-573b/c emit no event on `add_scratchpad`; AD-573f emits `COMMITMENT_RECORDED` only because commitments have lifecycle (record / complete / expire). Scratchpad writes are stateless ring appends with no lifecycle. Adding `WORKING_MEMORY_DREAM_SUMMARY_RECORDED` would create an asymmetry that future AD-573* writers would have to either match or not. v1 stays asymmetric and consistent with the existing scratchpad write pattern.

- **DLog #12 — Wave-10 reframe APPLIED at AD-scoping.** Five children → one. Three shipped earlier; one hard-blocked on a separate AD's forcing function. Documented up-front, GitHub issue #8 partial-close stance documented. Same architectural-honesty pattern Wave 13 used to drop AD-573e from Combo C; AD-573d was deferred from Combo C and is now ship-ready because its forcing function (`runtime.dream_scheduler` exposing summaries) is satisfied — `last_dream_report` is a stable public property at `dreaming.py:2807` and `on_post_dream(dream_report)` already passes the report.

- **DLog #13 — Phantom-API pre-check status.** Same recurring blocker as Waves 52–66 — `scripts/phantom-api-precheck.ps1` PowerShell parser error documented in user-memory. Manual verify-first pass at draft (8 verifying greps; all confirmed against HEAD `fa6d83d`). Net-new symbols are intra-prompt-introduction (`_DREAM_SUMMARY_FIELDS`, `_summarize_dream_report`, `working_memory` ctor kwarg). Same FP class as Waves 27–66.

- **DLog #14 — Test count target +10 (window [+8, +12]).** Pure-function summarizer (5) + adapter-level integration (5) = 10. Floor +8 absorbs one missed boundary case; ceiling +12 absorbs two extra integration shapes if the Builder discovers an edge.

- **DLog #15 — Commercial-leak audit: clean.** AD-573d is OSS plumbing — one ctor kwarg, one module-level helper, one branch in `on_post_dream`, one finalize-side wiring line, ten tests. The AD-573d-3 *(Commercial)* deferral names tenant-scoped variants; the OSS write remains tenant-agnostic. Dispatch contains zero pricing, revenue model, customer counts, professional-services positioning, competitive analysis, or GTM language. Reframe table is purely architectural (which children shipped where, which is blocked on what forcing function). **Clean.**

## Builder workflow (standard)

1. **Pre-flight gate:** `pytest tests/ -q -n 4 --dist=loadfile` → confirm 11401 collected at HEAD `fa6d83d`.
2. Apply Section 1 (`dream_adapter.py` ctor kwarg + field assignment). No tests should regress yet — additive only.
3. Apply Section 2 (`dream_adapter.py` module-level helper above the class). Run `pytest tests/test_ad515_dream_adapter*.py tests/test_ad557*.py tests/test_ad237*.py tests/test_dream_adapter*.py -n 0 -q` if any of those files exist; else just `pytest tests/test_dreaming.py -n 0 -q` to confirm zero regression on the dream surface.
4. Apply Section 3 (`dream_adapter.py` `on_post_dream` insertion). Re-run the dream surface tests.
5. Apply Section 4 (`startup/finalize.py` ctor-callsite kwarg). Run `pytest tests/test_finalize*.py -n 0 -q` if it exists; else proceed.
6. Apply Section 5 (NEW test file). Add the 10 tests one at a time; confirm each passes before adding the next.
7. **Final gate:** `pytest tests/ -q -n 4 --dist=loadfile` → expect 11411 (+10 net target; window [+8, +12] = [11409, 11413]).
8. **Update tracking:**
   - `PROGRESS.md` — append CLOSED paragraph.
   - `docs/development/roadmap.md:4596` — flip the AD-573d entry from `(dream-to-working-memory pipeline)` to `(dream-to-working-memory pipeline — *complete via AD-573d v1, Wave 67*)`.
   - `prompts/wave-plan.yaml` (id 67) — `status: done`. Note in the entry: "Reframed combo → single AD; 4 of 5 already accounted for elsewhere."
   - GH issue #8 — close with comment listing the four child statuses + this commit hash.

## Hard-stop conditions

1. Test count delta lands outside [+8, +12]. → Triage which class over/under-shot.
2. Existing AD-237 / AD-410 / AD-515 / AD-557 / AD-573 / AD-573b / AD-573c / AD-573f tests fail. → The producer-side change is leaking past the empty-suppress guard or the late-bind ctor default. Hard-stop and re-read DLog #4 / DLog #6.
3. Real working-tree changes appear in source files NOT named in this dispatch (`src/probos/dream_adapter.py`, `src/probos/startup/finalize.py`, `tests/test_ad573d_dream_to_working_memory.py`, plus tracking files). → Hard stop, surface to Captain.
4. Any source change to `src/probos/cognitive/working_memory.py`, `src/probos/cognitive/dreaming.py`, `src/probos/types.py`, or `src/probos/runtime.py`. → AD-573d does NOT modify these files (DLog #1, #2, #5). Hard-stop.
5. Any new EventType, Pydantic config field, or public runtime attribute. → DLog #11. Hard-stop.
6. Any test inserts a runtime fixture that boots a real `ProbOSRuntime`. → Use `MagicMock` per Wave 13/66 fixture precedent. Full-runtime fixtures explode wave-gate runtime budget. Hard-stop.
7. The `_summarize_dream_report` helper is moved INSIDE the `DreamAdapter` class (becomes a method). → DLog #3 violation. Hard-stop and re-read.
8. The scratchpad write is placed BEFORE the AD-557 emergence-metrics block, OR AFTER the AD-237 emergent-analysis try/except. → DLog #6 tier-ordering violation. Hard-stop and re-read.

## Acceptance criteria

1. Full gate passes at 11411 ± 2.
2. All Section 1–4 SEARCH/REPLACE blocks applied byte-for-byte as specified.
3. 10 new tests in `tests/test_ad573d_dream_to_working_memory.py` all pass.
4. No file outside the dispatch's named set is modified (other than tracking files: PROGRESS.md, docs/development/roadmap.md, prompts/wave-plan.yaml).
5. The Builder build report cites the test count delta + the four "what this AD does NOT change" verifications (no edits to working_memory.py, dreaming.py, types.py, runtime.py).
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-05, HEAD `fa6d83d`)

```
grep -n "class DreamAdapter|def on_post_dream|def __init__" src/probos/dream_adapter.py
  39:  class DreamAdapter:
  42:      def __init__(
  108:     def on_post_dream(self, dream_report: Any) -> None:

grep -n "DreamAdapter(" src/probos/startup/finalize.py
  2414: dream_adapter = DreamAdapter(

grep -n "self.working_memory = WorkingMemoryManager" src/probos/runtime.py
  348:  self.working_memory = WorkingMemoryManager(

grep -n "def add_scratchpad|scratchpad: list\[str\]" src/probos/cognitive/working_memory.py
  33:      scratchpad: list[str] = field(default_factory=list)
  155:     def add_scratchpad(self, text: str) -> None:

grep -n "@property\n.*def last_dream_report" src/probos/cognitive/dreaming.py
  2807: @property
  2809:     def last_dream_report(self) -> DreamReport | None:

grep -n "class DreamReport|clusters_found|procedures_extracted|contradictions_found|convergence_reports_generated|notebook_consolidations" src/probos/types.py
  474: class DreamReport:
  483:     clusters_found: int = 0
  485:     procedures_extracted: int = 0
  497:     contradictions_found: int = 0
  517:     notebook_consolidations: int = 0
  519:     convergence_reports_generated: int = 0

grep -n "AD-573d" src/probos/ tests/
  (zero hits — AD-573d is greenfield this wave)

grep -n "AD-573b|AD-573c|AD-573f" src/probos/cognitive/working_memory.py
  31:  # AD-573b: extension fields ...
  104: # AD-573b: relational links / scratchpad / commitments ...
  118: # AD-573f: event-callback late-bind ...
  138: # AD-573b: extension helpers ...
  183: # AD-573f: commitment lifecycle helpers ...
  (confirms shipped status of sibling extensions)
```

Every concrete claim in the dispatch maps to a grep hit shown here. The reframe table claims (b/c/f shipped, e wholesale-deferred) verified at PROGRESS.md:72,108 + DECISIONS.md:587,599 + roadmap.md:4596.
