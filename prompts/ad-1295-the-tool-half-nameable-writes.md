# AD-1295 — a successful tool write must be nameable: carry a tool-success set out of the agentic loop

**Status:** BLOCKED — do not start. See "Unblocking" below.
**Closes:** #1087 (BF-687) — the tool half. Closes #1338 item 1.
**Depends on:** AD-1285 (shipped, `133ceb2f`). Composes with AD-1293; neither requires the other to land first.
**Estimated tests:** 14–18 new.
**Files:** `src/probos/cognitive/agentic_dispatch.py`, `src/probos/cognitive/cognitive_agent.py`, `src/probos/cognitive/dm/write_ledger.py`, `src/probos/cognitive/dm/reply_pipeline.py`.

---

## Blocked, and by what exactly

Two of the four target files were foreign-modified and uncommitted at
`c75428bb`, by an in-flight `RedirectEscalation` change belonging to another
session:

```
 M src/probos/cognitive/agentic_dispatch.py     <- BLOCKED
 M src/probos/cognitive/cognitive_agent.py      <- BLOCKED
```

`write_ledger.py` and `reply_pipeline.py` are **clean** and could be edited
today, but a ledger key with no producer is an inert marker — the exact defect
class this cluster exists to remove (#1172, #1282). So the whole AD waits.

### Unblocking

Before starting, confirm both files are clean:

```powershell
git status --porcelain -- src/probos/cognitive/agentic_dispatch.py src/probos/cognitive/cognitive_agent.py
```

Empty output ⇒ proceed. **Any output ⇒ stop and surface it.** Do not stash, do
not revert, do not "work around" foreign in-progress work. Re-verify every line
anchor in this prompt against the file as it then stands: the in-flight change
touches both files and the numbers below will have moved.

---

## Problem

#1087's originally-reported turn: an agent stated *"I wrote the finding and it's
saved to my notebook under the slug `ward-room-escalation-decision`"* on a
healthy turn. No such entry existed, `publish_finding` never appeared in the
log, and she reasoned forward from the false premise for several turns.

AD-1285 shipped the **marker** half — a `[NOTEBOOK]` write that ran and produced
nothing now discloses. The reported turn carried **no marker**, so
`assess_write_claim` abstains by design (`write_ledger.py:94-108`,
`ledger.evaluated` is `False`). That abstention is correct and must not be
weakened. What is missing is the other channel: the AD-1065 tool loop runs
upstream of the reply pipeline and writes without telling it.

`write_ledger.py:15-19` states the gap in-repo:

> This ledger sees the **marker** channels only. The AD-1065 tool loop runs
> upstream of the pipeline and writes without telling it, so a ``wrote`` set
> that is empty means "no marker channel wrote", never "this turn wrote
> nothing". … Closing that half needs a name-addressable tool-success set
> carried out of ``WorkItemAgenticOutcome``; see #1087.

Three verified reasons the record does not exist today.

### 1. The agentic loop's own record dies at the outcome boundary

`cognitive_agent.py:118-122` (the BF-793 trap, stated in-repo):

> AD-1170 only ever ran on an exhausted turn, and only ever on a
> ``WorkItemAgenticOutcome``, which carries neither ``tool_calls`` nor
> ``tool_results`` — so (BF-793) it never ran at all.

`AgenticResult.tool_calls` / `tool_results` exist inside the loop and are not
projected onto `WorkItemAgenticOutcome` (`agentic_dispatch.py:1486`).

### 2. `ToolFailures` cannot substitute — successes are structurally anonymous

- A success stores `""` as its entry value — a *tombstone*, not a name
  (`dm_reply.py:223`).
- The tool name is **hashed into** `call_signature(name, arguments)`
  (`dm_reply.py:165`), so the key is a digest, not a name.
- `to_wire()` (`dm_reply.py:393`) **drops success tombstones** — stated at
  `:400`. What reaches the reply pipeline is failures-only.

So even a fully-populated `ToolFailures` cannot answer "did `publish_finding`
succeed on this turn?".

### 3. Text matching is not available as a fallback

AD-1285 built a text-reading branch and deleted it. `publish_finding` is a
**tool**, not a marker, and is enabled live — so a *genuine* save reached the
guard with an empty ledger, and the branch contradicted **truthful** replies.
**Do not reintroduce text matching as a verdict.** The verdict stays structural.

---

## Why this composes with AD-1293 rather than duplicating it

`WriteLedger` is keyed by channel **name**, deliberately, so a new channel adds
a key rather than reshaping the value (`write_ledger.py:38-44`). This AD adds
`WRITE_CHANNEL_FINDING` and populates it from the tool loop. Everything
downstream — `assess_write_claim`, the disclosure, and AD-1293's episode marker
and recall exclusion — then covers tool writes with **no further change**.

That is the shared primitive the cluster was triaged against, and it is the
reason to build these as one design: three independent fixes would have produced
three verdict mechanisms that do not compose.

---

## Solution

Project a name-addressable tool-success set out of the agentic loop, carry it on
`IntentResult.metadata`, and fold it into the existing ledger.

---

### Section 1 — project tool successes onto `WorkItemAgenticOutcome`

`src/probos/cognitive/agentic_dispatch.py`, `WorkItemAgenticOutcome` (`:1486`).

Add one field:

```python
    #: AD-1295 (#1087): tool NAMES that returned success on this turn, sorted
    #: and de-duplicated. Names, not signatures -- ``call_signature`` hashes the
    #: name in (``dm_reply.py:165``), which is what makes ToolFailures unable to
    #: answer "did publish_finding succeed?". A frozenset would not survive the
    #: JSON metadata hop; a sorted tuple does and is order-stable.
    tool_successes: tuple[str, ...] = ()
```

Populate it where `AgenticResult` is projected into the outcome, from
`tool_results` — success only, name only, sorted, de-duplicated.

**Bound it.** BF-797's lesson on `ToolFailures` is that an unbounded per-turn
collection accumulates. A turn can call one tool many times. De-duplicate by
name first (that alone bounds the set at the number of distinct tools), then cap
at a module constant with a documented value. Do not carry arguments, results,
or payloads — **names only**. This must never become an inline blob on a wire
message; the AD-731 lesson stands.

**Do not carry failures here.** `ToolFailures` owns failures and is already
wired. Two sources of truth for the same fact is how the AD-732 tuple
duplication happened.

### Section 2 — carry it onto `IntentResult.metadata`

`src/probos/cognitive/cognitive_agent.py`, `_build_result_metadata` (`:193`).

Its docstring names it as the right site:

> Reconciled at the SINGLE ``IntentResult`` construction site rather than
> relying on every ``act()`` override to forward private keys. ``act()`` is
> overridden by ``CounselorAgent`` and by generated agents, and those overrides
> copy only ``llm_output`` -- so a chain that depends on them silently drops the
> disclosure for the very agents that do most of the Captain's DMs.

That paragraph is the reason this must land at `:193` and **not** in any `act()`
override. Add the key alongside the existing `_PER_RUN_PROVENANCE_KEYS`
(`:54`) handling, following whatever shape that constant already enforces —
re-read it, it may have moved.

Emit the key **only when the agentic loop ran.** An absent key and an empty
tuple must stay distinguishable, for the AD-1269 reason the ledger already
encodes: a verdict of *nothing happened* must never be reachable from a field
nobody set. A turn with no tool loop must produce **no key**, not `()`.

### Section 3 — a third write channel

`src/probos/cognitive/dm/write_ledger.py`.

```python
#: AD-1295 (#1087): the AD-1065 tool-loop durable-write channel.
WRITE_CHANNEL_FINDING = "finding"
```

Add it to `__all__`. **Change nothing else in this file** — not `WriteLedger`,
not `assess_write_claim`, not `_DISCLOSURES`. The whole point of the
name-keyed design is that a new channel needs no change to the value or the
verdict. If you find yourself editing `assess_write_claim`, stop: the design has
drifted and the diff needs review before you continue.

Define the durable-write tool set as a module constant, not a literal at the
call site:

```python
#: Tools whose success constitutes a durable write for ledger purposes.
_DURABLE_WRITE_TOOLS: frozenset[str] = frozenset({"publish_finding"})
```

Start with `publish_finding` **only**. Adding a tool here changes what the guard
asserts, so each addition needs its own evidence that the tool's success means a
durable record exists.

### Section 4 — populate the ledger from the metadata

`src/probos/cognitive/dm/reply_pipeline.py`.

Where the agentic result's metadata is available and **before**
`step_4m_write_claim_guard` (`_full_steps()` index 216 at `c75428bb`), record
the channel using the existing mutator:

```python
                # AD-1295 (#1087): the tool loop is a durable-write channel and
                # must declare itself, or an empty `wrote` set keeps meaning
                # "no marker channel wrote" rather than "this turn wrote
                # nothing" (write_ledger.py:15-19).
                self.ctx.write_ledger = self.ctx.write_ledger.consulted_with(
                    WRITE_CHANNEL_FINDING,
                    wrote=bool(successes & _DURABLE_WRITE_TOOLS),
                )
```

**The admission condition is the hard part, and it is the whole AD.** Record the
channel as *consulted* only when a durable-write tool was **attempted** on this
turn — not on every turn that ran any tool. Getting this wrong in either
direction is a shipped defect:

- Too broad — consult on every tool-loop turn — and every turn that called a
  read-only tool and never intended to write reports `wrote_nothing={finding}`
  and appends a disclosure to a **truthful** reply. That is exactly the
  false-positive class AD-1285 deleted a branch to avoid.
- Too narrow — consult only on success — and the ledger can never record a
  failed write, which is the entire purpose.

The attempt signal must come from the tool loop's own record. If
`WorkItemAgenticOutcome` cannot distinguish *attempted* from *succeeded* for a
given tool, **Section 1 must also project attempted names** — and if it cannot,
say so and stop rather than approximating. State in the build report which field
carries the attempt signal and paste the line that proves it.

---

## Tests

New file `tests/test_ad1295_tool_success_ledger.py`.

**Projection (Section 1)**
1. Successful tool call → name appears in `tool_successes`.
2. Failed tool call → name absent.
3. Same tool succeeding twice → one entry (de-duplicated).
4. Result is sorted and stable across call order.
5. Cap enforced at the documented constant.
6. No arguments/results/payloads leak into the field.

**Metadata hop (Section 2)**
7. Agentic loop ran → key present on `IntentResult.metadata`.
8. Agentic loop did **not** run → key **absent**, not `()`.
9. Loop ran and no tool succeeded → key present and empty. Tests 8 and 9 are the
   AD-1269 distinction; if they can both pass with the same implementation, the
   distinction is not encoded.
10. Survives an `act()` override that copies only `llm_output` — construct a
    subclass that does exactly that. This is the `:193` docstring's stated
    hazard and the reason the field is built there.

**Ledger + verdict (Sections 3–4)**
11. `publish_finding` succeeded → `wrote` contains `finding`, verdict `ABSTAIN`,
    reply **unchanged**. A truthful save must be byte-identical.
12. `publish_finding` attempted and failed → `wrote_nothing` contains `finding`,
    verdict `MARKER_WROTE_NOTHING`, disclosure appended.
13. Read-only tools only, no durable-write tool attempted → channel **not
    consulted**, verdict `ABSTAIN`, reply byte-identical. This is the
    false-positive guard; it is the most important test in the file.
14. Notebook marker wrote, finding tool failed → `wrote_nothing == {finding}`
    only. Per-channel granularity must not be masked by a ledger-wide
    `if self.wrote` (`write_ledger.py:76-83`).
15. Both channels wrote → `ABSTAIN`.
16. The #1087 turn, reconstructed end-to-end: agentic loop runs, no
    `publish_finding` attempt, `[NOTEBOOK]` marker absent → still `ABSTAIN`.
    **The original turn stays undetectable, and that is correct** — nothing
    durable was attempted, so nothing structural contradicts the claim. This
    test exists to stop a future reader "fixing" the abstention with text
    matching. Assert it and comment why.

**Composition with AD-1293** (only if AD-1293 has landed)
17. A finding-channel failure marks the stored episode's
    `self_contradicted_channels` as `["finding"]` with **no change to AD-1293's
    code** — the name-keyed design proving itself.

**Cross-seam requirement.** At least one test must run
projection → metadata → ledger → verdict → reply in a single pass. Three tests
that each stop at a boundary is the exact evidence shape that let BF-793 ship: a
producer firing proves the producer, not the chain.

**Assert every probe reached its branch.** A test asserting "no disclosure"
passes trivially if the guard never ran. Assert the positive case with the same
fixture shape first.

---

## What this does NOT change

- No text matching, in any form, for any verdict.
- `assess_write_claim`, `ClaimVerdict`, `_DISCLOSURES`, `WriteLedger` — unchanged
  (Section 3).
- `ToolFailures`, `call_signature`, `to_wire` — unchanged. This adds a parallel
  success record; it does not reshape the failure record.
- #1338 items 2–5 (fenced-tag admission, malformed-tag bypass, partial
  persistence, the proactive/group forward markers) — separate work, still open.
- `oracle_service.py`, `crew_executor.py` — AD-1294.
- `episodic.py`, `types.py` — AD-1293.
- `continue_or_ask.py`, `repair_verification.py`, `fault_report.py`,
  `tools/browser/url_route_guard.py` — read-only.
- `README.md`, `docs/architecture/federation.md`, `docs/development/roadmap.md`.

---

## Test gate — read this before running anything

**The tree could not run the full Python suite at `c75428bb`.**
`src/probos/tools/browser/session.py` imported `RedirectEscalation`, removed by
the same in-flight work that blocks this AD; roughly **423 tests failed** on
collection. If that work has landed by the time you start, re-check whether a
worktree is still needed — if the main tree collects cleanly, gate there.

If it is still broken, gate in a **linked worktree**:

```powershell
git worktree add d:\probos-gate1295 HEAD
cd d:\probos-gate1295
$env:PYTHONPATH='d:\probos-gate1295\src'
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q
```

`PYTHONPATH` shadows the editable install. Prove it took:
`python -c "import probos; print(probos.__file__)"` must print the worktree path.

Known worktree artefact: **3 `test_phantom_api_precheck_*` tests fail in a linked
worktree and pass in the main tree.** Verify, then count as passes.

Focused gate while iterating:

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1295_tool_success_ledger.py tests/test_ad1285_write_claim_guard.py -q -p no:randomly
```

Reconcile `before + new == after`. Never end a `replace_string_in_file`
`oldString` on a `def`/`class` line you are not reproducing verbatim — that
silently swallowed a whole test in this repo on 2026-08-29, and only the count
caught it.

---

## Acceptance criteria

- A successful `publish_finding` is nameable from `IntentResult.metadata`.
- Key absent when the loop did not run; present-and-empty when it ran and
  nothing succeeded.
- A truthful save is byte-identical — no disclosure, no reply mutation.
- A turn with only read-only tools does not consult the channel.
- `write_ledger.py` gains a constant and nothing else.
- One test spans projection → metadata → ledger → verdict → reply.
- The build report names the field carrying the *attempt* signal and pastes the
  line proving it.
- Run the `Diff Reviewer` subagent on the staged diff **with a different model
  than the one that wrote the code**; repair Critical/High findings before
  committing. Given both target files are shared-contract and were recently
  foreign-modified, trace every changed contract to all production consumers,
  not just the immediate caller.
- Verify all changes comply with the Engineering Principles in
  `.github/copilot-instructions.md`.

---

## Tracking

- `PROGRESS.md` — AD-1295 entry.
- Close **#1087**. Close **#1338 item 1**; leave items 2–5 open with a comment
  naming what remains.
- `DECISIONS.md` — record that the tool loop is a declared write channel and
  that the ledger's channel-name keying absorbed it without a value change,
  which was the design's stated purpose (`write_ledger.py:38-44`).

---

## Verified Against Codebase (2026-08-29, `c75428bb`) — RE-VERIFY BEFORE BUILDING

Both blocked files were mid-edit when these were taken. Treat every anchor as
stale until re-checked.

```
agentic_dispatch.py:1486   class WorkItemAgenticOutcome
agentic_dispatch.py:1491   result with provenance. ``tool_trace_ref`` is a content-addressable SHA ref

cognitive_agent.py:54      _PER_RUN_PROVENANCE_KEYS = ("_dm_tool_failures", "_tool_trace_ref")
cognitive_agent.py:120     ``WorkItemAgenticOutcome``, which carries neither ``tool_calls`` nor
cognitive_agent.py:121     ``tool_results`` -- so (BF-793) it never ran at all.
cognitive_agent.py:193     def _build_result_metadata(
cognitive_agent.py:196-199 Reconciled at the SINGLE ``IntentResult`` construction site ...
                           ``act()`` is overridden by ``CounselorAgent`` and by generated agents,
                           and those overrides copy only ``llm_output``

dm_reply.py:165            def call_signature(name: str, arguments: Any) -> str:
dm_reply.py:212            class ToolFailures:
dm_reply.py:223            merge-open carries ``""`` success tombstones and supports the full
dm_reply.py:295-297        BF-797: this bounds FAILING entries only. Success tombstones are not
                           counted and can accumulate freely in memory
dm_reply.py:393            def to_wire(self) -> dict[str, Any] | None:
dm_reply.py:400            Success tombstones are dropped here. That is safe only because no

write_ledger.py:15-19      This ledger sees the **marker** channels only. ... Closing that half
                           needs a name-addressable tool-success set carried out of
                           ``WorkItemAgenticOutcome``; see #1087.
write_ledger.py:38-44      The ledger is keyed by channel NAME rather than by a fixed set of
                           fields so a later slice can add ``publish_finding`` without changing
                           the value's shape.
write_ledger.py:94         def assess_write_claim(ledger: WriteLedger) -> ClaimVerdict:

reply_pipeline.py:216              self.step_4m_write_claim_guard,  # AD-1285 (#1087)
reply_pipeline.py:217              self.step_5_episodic_store,
```

### Blocked-state evidence

```
RUN:   git status --porcelain -- <each target>
clean     src/probos/cognitive/dm/reply_pipeline.py
clean     src/probos/cognitive/dm/write_ledger.py
BLOCKED   src/probos/cognitive/agentic_dispatch.py
BLOCKED   src/probos/cognitive/cognitive_agent.py
```
