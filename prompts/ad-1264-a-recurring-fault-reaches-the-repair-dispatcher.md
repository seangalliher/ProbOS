# AD-1264 — a recurring fault reaches the repair dispatcher, and one recurrence raises one approval

**Status:** Ready to build
**Closes:** #1307 (BF-841)
**Dependencies:** none at HEAD. #1307's body says "depends on AD-1257 landing first" — that is about *volume* (AD-1257 is what will start producing fault reports on the ordinary DM path), not about correctness. The defect and its fix are independent of AD-1257 and can land first.
**Estimated tests:** ≥ 26 new

---

## AD number

| Source | AD | BF |
|---|---|---|
| Ledger (`docs/development/open-ads-report.md`) | "next free **AD-1251**" — **STALE** | "next free **BF-837**" — **STALE** |
| GitHub, all states (authoritative) | **AD-1261** filed (#1311) | **BF-845** filed (#1315) |
| Untracked in-flight prompts | **AD-1250 … AD-1263** claimed (`prompts/ad-125{0..5,7}-*.md`, `ad-1258…1263-*.md`) | — |

The ledger's issue layer cannot see the untracked prompts, so its "next free" is wrong by fourteen.
`prompts/ad-1263-shapley-duplicate-participant-key.md:22` records "Next free AD after this one: **AD-1264**".

- **This work is AD-1264.** Next free AD after this one: **AD-1265**.

---

## Problem

### The defect, in one line

`FaultReportStore.file_fault` emits `FAULT_REPORTED` only on the branch that **creates** a report, so every
event carries `occurrences=1`, and `RepairDispatcher.on_fault_event` requires
`occurrences >= propose_after_occurrences` (default 2). **No repair proposal can ever be raised.**

`src/probos/fault_report.py:258-265` — the coalesce branch returns without emitting:

```python
        if existing is not None and existing.status in ("open", "diagnosing"):
            existing.occurrences += 1
            existing.last_seen_at = now
            await self._persist_occurrence(existing)
            return existing            # <- no emit
```

`src/probos/fault_report.py:287` — the create branch is the only emitter, and its report is always
`occurrences=1` (`:281`).

`src/probos/cognitive/repair_dispatch.py:93-95` — the consumer's gate:

```python
            if int(data.get("occurrences") or 0) < threshold:
                return
```

Measured against the real store — five faults, one signature:

```
call 1: occurrences=1 ... call 5: occurrences=5
events emitted: 1   ->  FAULT_REPORTED occurrences=1
max occurrences ever EMITTED = 1     (threshold = 2)
```

### Both of #1307's "not yet verified" items are settled

**Is the event the only path into the dispatcher?** Yes — this is fully blocking, not latent.
`RepairDispatcher.propose()` is called from exactly one site, inside `on_fault_event`
(`repair_dispatch.py:100`), and `on_fault_event` is reached only through the listener
`wire_repair_dispatcher` registers (`repair_dispatch.py:213`, wired at `startup/finalize.py:2829`,
called at `:4770`). There is no periodic scan of `fault_reports.db`.

**Should the emit or the threshold move?** The emit. `_DEFECT_MIN_OCCURRENCES` /
`DEFAULT_PATTERN_THRESHOLD` / `REPEAT_THRESHOLD` / `propose_after_occurrences` are pinned equal to each
other transitively by `tests/test_ad1172_repair_dispatch.py:308`, so lowering one is a four-subsystem
decision. Emitting on coalesce keeps "once is a transient, twice is the tool" intact.

### Why the one-line fix cannot ship alone

Emitting on every recurrence exercises `RepairDispatcher`'s proposal path for the first time. Six
defects sit in that consumer. Every one below was measured by execution, not by reading.

| # | Defect | Measured |
|---|---|---|
| 1 | **Approval storm.** `_proposed` is checked at `:97` but added at `:116` — after `file_action_request` returns — while `runtime._emit_event_local` creates an independent listener task per event (`runtime.py:1751`). | 12 faults, one signature → **11 Captain approvals** |
| 2 | **Cancellation vs a landed insert.** `aiosqlite`'s worker can complete the insert after the awaiting task is cancelled, so "cancelled ⇒ nothing filed" is false. | 2 pending rows for one signature |
| 3 | **Commit-then-raise.** `CapabilityRequestStore.file_request` commits (`capability_request.py:345`), caches (`:346`), **then** calls `self._emit(...)` (`:347`), which can raise. So "exception ⇒ nothing filed" is also false. | 1 pending request with an empty reservation, then 2 requests on the next occurrence |
| 4 | **`thread_id` contract mismatch.** `fault_report._THREAD_ID_MAX = 128` (`:58`); `capability_request._THREAD_ID_MAX = 64` (`:63`); the dispatcher forwards unchanged (`repair_dispatch.py:167`). | 3 recurrences, 3 attempts, **0 requests** — permanently unproposable |
| 5 | **Payload envelope.** `params` must fit a 4,000-char **canonical JSON** bound (`capability_request.py:141`). The dispatcher budgets the brief in Python characters (`repair_dispatch.py:162`) and does not bound `RepairConfig.targets` at all. | see the measurement below |
| 6 | **Resolution race.** `fault_resolved` clears the reservation (`:85`); an older in-flight `propose()` then re-adds it (`:116`): reserved 1 → resolved 0 → settled 1, and a new fault with that signature files nothing. Latent today — `FaultReportStore.resolve()` has exactly one caller, `repair_verification.verify_and_close` (`repair_verification.py:192`), which itself has **zero** callers in `src/`. | latent, reachable the moment AD-1173 is wired |

**Measured against the real `validate_action_payload`** (a maximal-but-entirely-valid fault report:
`error_text` 2,000, `attempted` 1,000, `tool_id` 128, `agent_id` 128, `thread_id` 128,
`tool_trace_ref` 128; bound = 4,000):

| Case | canonical JSON | valid |
|---|---|---|
| A: default single target, `thread_id` 128 | 1,700 | **False** — `thread_id` is 128 > 64 |
| D: same, `thread_id` narrowed to 64 | 1,636 | True |
| B: one 4,500-char target | **6,127** | False |
| C: 12 targets × ~210 chars | **4,158** | False |

Two things follow, and they change the shape of the fix from what #1307 assumed:

- **Defect 4 bites on an *ordinary* fault.** Case A is a perfectly normal report and it is rejected
  outright. `thread_id` is the blocker, not size.
- **The overflow driver is `targets`, not the brief.** The brief is already clipped at 1,200 Python
  characters; an unbounded config list is what blows the envelope.

### The two rounds this has already cost

A previous attempt fixed 1, 2 and 4 by reserving before the await and keeping the filing alive in an
owned, shielded task whose done-callback released the reservation on a settled `None`. Adversarial
review then found 3, 5 and 6 — **all inside the release protocol that fix invented** — plus one of the
attempt's own tests was vacuous (`create_task()` then an immediate `cancel()` with no yield, so the
coroutine never ran and the assertion could not fail). That is three rounds of findings clustered at one
seam, which is the BF-788 → BF-839 → BF-840 signature, so the attempt was reverted rather than ground
through a fourth round.

**The lesson that shapes this spec:** the shield, the owned task and the done-callback existed *only* so
the outcome could be learned in order to release the reservation. Remove the release and the entire
protocol disappears. That is the design below.

---

## Solution

Four decisions. Each is stated with what it guarantees, and — where the guarantee is weaker than it
might read — what it does not.

### DD-1 — The proposal state model: nothing releases except a resolution

State is keyed on **`fault_id`**, not on the signature, and lives in
`RepairDispatcher._proposals: dict[str, _Proposal]`.

| State | Meaning | Written by | The next occurrence |
|---|---|---|---|
| *absent* | never attempted | — | attempts |
| `proposing` | a filing is in flight | `on_fault_event`, **before** the await | holds |
| `proposed` | a request was filed and its id is known | the filing returned a request | holds |
| `refused` | the approval surface **definitely** filed nothing | the filing returned `None` | holds |
| `unknown` | the outcome could not be determined | the filing raised, or the caller was cancelled | holds |

**Only a `fault_resolved` event removes an entry.** Nothing releases itself.

**Why `refused` and `unknown` both hold, when the brief asked for `not filed` to release.**
The distinction is preserved — the states are distinct, the logs differ, and #1315 will need to tell them
apart — but neither drives a retry:

- `refused` is **deterministic**. The payload that `validate_action_payload` rejected once will be
  rejected identically on every recurrence, because `params` is a function of the fault. Retrying files
  nothing and logs forever; that is exactly defect 5's measured shape ("rejected on every recurrence").
- The one provable "nothing was filed" case that *is* worth releasing — **no approval surface at all** —
  is checked *before* the reservation is taken, so it never becomes a state and needs no release path.
  `self._requests is None` or a store lacking `file_action_request` returns early, synchronously, having
  provably written nothing.
- `unknown` cannot be released by construction: releasing on an outcome you do not know is precisely
  defect 2 and defect 3.

**The guarantee, stated plainly.** *At most one repair approval is filed per fault report, per process.*
It is **not** "at least one." If a filing's outcome is unknown, the dispatcher holds and does not retry,
so a proposal that in fact failed after commit-or-not will not raise a second attempt in this process.
What is not lost: the fault stays `open`, `FaultReportStore.list_open()` still shows it, every recurrence
still emits `FAULT_REPORTED`, and one `WARNING` names the signature and the uncertainty. What *is* lost
is the automatic second attempt. On restart the map is empty and the next occurrence proposes again, so
`unknown` self-heals across a restart for free.

**No timer, no bounded hold, no escalation.** A bounded wait that expires indistinguishably from success
is the BF-840 defect; it would be built here for a case whose entire cost is "one fault report does not
raise an approval until restart, while remaining fully visible." That does not pay for the machinery.

**Why `fault_id` keying dissolves defect 6.** `FaultReport.id` is a fresh `uuid4().hex[:12]` set at
creation (`fault_report.py:269`) and is never changed on coalesce. A resolved fault that recurs takes the
create branch and gets a **new** id (`file_fault:258-260`). So the sequence `reserve(old_id)` →
`fault_resolved` pops `old_id` → the in-flight filing writes `proposed` under `old_id` leaves a stale
entry that nothing will ever look up again, and the new report proposes cleanly. No generation counter is
needed; the redundant `self._proposed.add()` inside `propose()` is removed by construction, because
`propose()` no longer touches state at all.

The key is resolved synchronously via `self._faults.get(signature)` — `FaultReportStore.get` is a plain
`def` (`fault_report.py:379`), so there is no await between the presence check and the reservation, and
the reservation is therefore atomic with respect to the event loop. That is what closes defect 1 without
a lock. If the lookup yields a report with no id, fall back to the signature; that degenerate path keeps
today's behaviour and is documented, not silently different.

### DD-2 — Budget against the consumer's own serialiser, and bound `targets`

**`targets`** is bounded in `resolve_targets` (`repair_brief.py:195`), the single source of the list, so
the bound reaches the payload, the rationale and the log together: at most `_TARGETS_MAX = 8` names, each
clipped to `_TARGET_NAME_MAX = 64`. Measured headroom with those bounds against the maximal fault above:
8×64 → 2,146 chars, valid; 8×128 → 2,658, valid; 12×64 → 2,406, valid. `resolve_targets` already
log-and-degrades malformed input, so bounding there matches its existing stance. Log once when the list
is clipped.

**`thread_id`** is narrowed to the approval contract's own bound at the dispatcher. Import the bound
rather than hard-coding 64. A 64-char prefix of a thread id is still highly identifying, and the *full*
thread id remains one lookup away via `params["fault_id"]` — say that in the comment.

**The brief** is fitted against the consumer's serialiser, not the producer's units. New public helper in
`capability_request.py`, next to the validator and the bound it enforces:

```python
def fit_action_payload(
    payload: dict[str, Any], *, shrink_key: str
) -> dict[str, Any] | None:
```

It truncates `payload["params"][shrink_key]` until `validate_action_payload` accepts the **final
artifact**, and returns `None` when even an empty value will not fit. Requirements:

- Try the untruncated payload first; if it validates, return it unchanged.
- Otherwise binary-search the largest prefix length `L < len(text)` for which
  `text[:L] + _TRUNCATION_MARKER` validates. That candidate family is monotone in `L`, so the search is
  exact. (The untruncated case is a discontinuity — it has no marker — which is why it is tested first
  and excluded from the search range.)
- The decision at every probe is `validate_action_payload(candidate) is not None`. Do not re-implement
  the length arithmetic; the point of this helper is that the producer stops guessing what the consumer
  charges.
- Never mutate the input. Copy `params`.
- Return `None` when `L = 0` still fails, so the caller can classify `refused` honestly.

With `targets` bounded, the fit loop is **not expected to fire** — the arithmetic above leaves roughly
1,850 characters of headroom, and even a pathological 1,200-character all-newline brief expands to about
2,400. It exists so the guarantee holds without depending on that arithmetic staying true as fields are
added. Say that in the docstring rather than implying it is load-bearing today.

### DD-3 — A discriminated filing outcome

`_file_dispatch_request` stops returning `Any | None`, because that single `None` is what collapsed
"validation refused" (provably nothing filed) into "the call raised" (may have committed) — defect 3.

```python
@dataclass(frozen=True)
class _Proposal:
    state: str
    signature: str = ""
    request_id: str = ""
```

with module constants `_PROPOSING`, `_PROPOSED`, `_REFUSED`, `_UNKNOWN`.

The classification is load-bearing and rests on one verified fact:
**`file_action_request` returns `None` only from its validation branch**, which precedes every await and
every write (`capability_request.py:390-398`; the only other returns are an existing pending request at
`:409` or `await self.file_request(...)` at `:413`, and `file_request` returns a request or raises).
So:

| Path | Outcome |
|---|---|
| returns a request | `_PROPOSED` |
| returns `None` | `_REFUSED` — definite |
| raises `Exception` | `_UNKNOWN` — may or may not have committed |
| the caller is cancelled | `_UNKNOWN` |

`propose()` keeps its public contract (`-> Any | None`, returning the request) and delegates.

**Anything that escapes is `_UNKNOWN`.** A `build_brief` failure provably files nothing, but classifying
it separately buys no behaviour — both states hold — and costs a branch. One rule: *if we cannot prove
nothing was filed, we hold.*

### DD-4 — No shield, no owned task, no done-callback

Because nothing releases, the filing does not need to outlive its caller. `on_fault_event` awaits
`propose()` inline. A cancellation propagates (deliberately: the caller asked to stop), and a
synchronous `finally` records `_UNKNOWN` on the way out. No `asyncio.shield`, no `_inflight` set, no
`add_done_callback`. The `finally` performs no I/O and no await, so it cannot stall the loop or be
skipped by the cancellation that triggered it.

---

## Implementation

### Section 1 — `src/probos/fault_report.py`: emit on the coalesce branch

The one-line producer fix. Insert after the persist, before the return.

```
===SEARCH===
        existing = self._cache.get(signature)
        # A repaired fault that recurs is a NEW fault: the repair did not hold,
        # and silently incrementing the old row would hide a regression.
        if existing is not None and existing.status in ("open", "diagnosing"):
            existing.occurrences += 1
            existing.last_seen_at = now
            await self._persist_occurrence(existing)
            return existing
===REPLACE===
        existing = self._cache.get(signature)
        # A repaired fault that recurs is a NEW fault: the repair did not hold,
        # and silently incrementing the old row would hide a regression.
        if existing is not None and existing.status in ("open", "diagnosing"):
            existing.occurrences += 1
            existing.last_seen_at = now
            await self._persist_occurrence(existing)
            # AD-1264: a recurrence is the whole point. Emitting only on the
            # create branch meant every event carried ``occurrences=1`` while
            # the repair dispatcher requires >= 2, so no repair could ever be
            # proposed. Measured before this: five faults with one signature
            # drove the store to occurrences=5 and emitted one event, at 1.
            self._emit_fault("FAULT_REPORTED", existing)
            return existing
===END REPLACE===
```

`_emit_fault` already swallows its own failures (`:405`) and the payload already carries `occurrences`
(`:402`), so `file_fault`'s "never raises" contract is unaffected. Nothing else in this file changes.

### Section 2 — `src/probos/capability_request.py`: expose the bound, add the fitter

**2a.** Add a public alias beside `_THREAD_ID_MAX` (`:63`) so the dispatcher does not hard-code 64:

```python
#: AD-1264: the action-approval contract's own thread_id bound, exported so a
#: producer with a wider field (fault reports allow 128) narrows to the
#: consumer's contract instead of forwarding a value that will be rejected.
THREAD_ID_MAX_CHARS: int = _THREAD_ID_MAX
```

**2b.** Add `fit_action_payload` immediately after `validate_action_payload` (which ends at `:143`), plus
a module constant `_TRUNCATION_MARKER: str = "\n\n[truncated]"`. Behaviour is specified in DD-2. The
docstring must state (i) that it validates the final artifact with the real validator rather than
computing a length, and (ii) that returning `None` means the payload cannot be recorded at all.

Do **not** change `validate_action_payload`, `_ACTION_PAYLOAD_MAX_CHARS`, `action_dedup_key`,
`file_action_request` or `file_request`. The commit-then-raise ordering in `file_request` is a real
hazard and is handled by DD-1 in the consumer; reordering the emit is a change to a store with many
other callers and is out of scope here.

### Section 3 — `src/probos/cognitive/repair_brief.py`: bound the targets

Add the two constants beside `_TITLE_MAX` / `_EVIDENCE_MAX` (`:46-47`) and apply them inside
`resolve_targets` (`:195`), after dedup, preserving declared order. Log once at `WARNING` when the list
is clipped, naming how many were dropped and why (the approval payload's canonical-JSON bound).

```
===SEARCH===
_TITLE_MAX = 120
_EVIDENCE_MAX = 4000
===REPLACE===
_TITLE_MAX = 120
_EVIDENCE_MAX = 4000

# AD-1264: the target list reaches the approval payload, whose canonical JSON
# is capped at 4,000 chars. Measured against the real validator with a maximal
# fault report: one 4,500-char target serialised to 6,127 and 12 targets of
# ~210 chars to 4,158 -- both rejected, so the fault became unproposable.
# 8 x 64 measures 2,146 and leaves comfortable headroom.
_TARGETS_MAX = 8
_TARGET_NAME_MAX = 64
===END REPLACE===
```

### Section 4 — `src/probos/cognitive/repair_dispatch.py`: the state model

This is the bulk of the change. Structure it as follows; the exact text is yours, the contracts are not.

**4a. Module header.** Amend the docstring to say plainly that "one approval" holds *within a process*,
because `_proposals` is in-process state — a fault recurring after a restart can be proposed again while
the earlier approval is still pending. Durable dedup is #1315.

**4b. Imports and constants.** Add `from dataclasses import dataclass`; add
`from probos.capability_request import THREAD_ID_MAX_CHARS, fit_action_payload`.

> Circular-import check, run: `capability_request.py:41-42` imports `probos.events` and
> `probos.protocols` and nothing else from the package. `repair_dispatch` sits in `cognitive/` above it,
> so the direct import is clean. If that ever changes, use a function-local import and say why inline —
> do **not** re-declare the bound.

Add `_PROPOSALS_MAX: int = 512`, the four state constants, and the frozen `_Proposal` dataclass.

**4c. `__init__`.** Replace `self._proposed: set[str] = set()` with
`self._proposals: dict[str, _Proposal] = {}`. Nothing outside this module reads `_proposed` (enumerated:
`grep -rn "_proposed" src/ tests/ ui/` returns four hits, all in this file, plus unrelated
`*_PROPOSED` EventType members and a `test_ad721d_2` local attribute).

**4d. `on_fault_event`.** Rewrite the body:

1. Correct the docstring. It currently claims "this runs inline on the event bus". That is false —
   `runtime._emit_event_local` creates a task per coroutine listener (`runtime.py:1751`), and that
   per-event concurrency is exactly why the reservation is taken before the await. Say that it swallows
   `Exception` but not `BaseException`, so a cancellation propagates.
2. Keep the existing malformed-event guards unchanged.
3. `fault_resolved` → resolve the key (see 4f) and `self._proposals.pop(key, None)`; return.
4. Keep the `enabled` and threshold gates unchanged.
5. **Check the approval surface before reserving.** `store = self._requests`; if it is `None` or lacks
   `file_action_request`, log at `info` (reuse the existing message from `_file_dispatch_request:147`)
   and return without reserving.
6. Resolve the report synchronously: `report = self._faults.get(signature)`. If `None`, return —
   there is nothing to propose and `propose()` would return `None` anyway.
7. `key = self._proposal_key(report, signature)`; if `key in self._proposals`, return.
8. `self._proposals[key] = _Proposal(_PROPOSING, signature=signature)` — **no await between 7 and 8.**
9. ```python
   outcome = _Proposal(_UNKNOWN, signature=signature)
   try:
       outcome = await self._file_for(signature)
   finally:
       self._proposals[key] = outcome
       self._trim_proposals()
   ```
   The `finally` is synchronous. On cancellation or on an escaping exception the initial `_UNKNOWN`
   stands, which is the honest answer.

**4e. `propose`.** Keep the public signature `async def propose(self, signature: str) -> Any | None`.
Its body becomes the delegation plus the existing success log. Its docstring must say it does **not**
record proposal state — `on_fault_event` owns that — so a direct operator call is an explicit action that
bypasses dedup by design.

**4f. New private helpers.**

- `_proposal_key(report, signature) -> str` — `str(getattr(report, "id", "") or "") or signature`.
- `_trim_proposals()` — while `len(self._proposals) > _PROPOSALS_MAX`, drop the oldest key
  (`next(iter(...))`; dicts preserve insertion order). Document the consequence: a process that has seen
  more than 512 distinct fault reports may re-propose the oldest. Bounded and visible, versus a map that
  grows for the life of the vessel.
- `_file_for(signature) -> _Proposal` — look the fault up, build the brief, file, return the outcome.
  A missing fault is `_REFUSED` (nothing to propose, nothing filed).

**4g. `_file_dispatch_request`.** Return `_Proposal` instead of `Any | None`, per DD-3. Inside:

- Narrow `thread_id`: `(brief.thread_id or "")[:THREAD_ID_MAX_CHARS]`, with a comment naming the two
  bounds (128 vs 64) and noting that the full thread id is reachable via `params["fault_id"]`.
- Build the payload as today, then `fitted = fit_action_payload(payload, shrink_key="brief")`. If
  `fitted is None`, log at `warning` (naming the fault, and that no further proposal will be made for it)
  and return `_Proposal(_REFUSED, ...)`.
- `await store.file_action_request(agent_id=..., payload=fitted, rationale=...)`.
- Classify per the DD-3 table. The `_UNKNOWN` log must say the store *may or may not* have committed —
  do not write a message that asserts failure.

The `rationale` keeps the occurrence count (`brief.occurrences`) unchanged. It is not part of
`action_dedup_key` (`capability_request.py:187-197`), so it costs nothing.

---

## Tests

Three new files. Every negative assertion needs a positive premise assertion beside it — assert you
reached the path before asserting what did not happen on it.

### `tests/test_ad1264_recurrence_reaches_the_dispatcher.py` — the producer, and the seam

Carry these forward from the reverted attempt (`.git/BF841_tests.py`); they were sound.

1. `test_a_recurrence_emits_with_the_post_increment_count` — two faults → `occurrences == [1, 2]`.
2. `test_every_recurrence_is_observable` — five faults → `[1, 2, 3, 4, 5]`, and
   `max(...) >= 2` with the message naming the dispatcher threshold.
3. `test_a_different_signature_starts_its_own_count` — `[1, 1, 2]`.
4. `test_a_resolved_fault_that_recurs_is_still_a_new_report` — guards the neighbouring branch: a new
   `id`, `occurrences == 1`, and two `FAULT_REPORTED` events both carrying 1.
5. `test_an_emit_failure_still_lets_the_turn_finish` — an exploding `emit_event`; `file_fault` must
   still return the coalesced report.
6. **The crossing test.** A real `FaultReportStore` feeding a real `RepairDispatcher` feeding a real
   `CapabilityRequestStore` on `tmp_path`. File the same fault twice, drain the captured events into
   `on_fault_event` in order, and assert `len(await requests.list_pending()) == 1` with
   `kind == "action"`. Assert the *first* occurrence filed nothing (one is a transient). State the
   honest limit in the docstring: this crosses the store → dispatcher → approval-store payload boundary
   but replays events serially, so the runtime's per-event task scheduling is covered separately.

The `_Capture` double must expose its recording for the **test** to read. An assertion placed inside a
double is swallowed by `_emit_fault`'s own `except Exception` (`fault_report.py:405`) and proves nothing.

### `tests/test_ad1264_proposal_state.py` — the state model

Use a barrier double, not a sleep:

```python
class _BarrierRequests:
    def __init__(self) -> None:
        self.entered = asyncio.Event()   # set when a filing has actually STARTED
        self.release = asyncio.Event()   # the test decides when it settles
        self.filed: list[dict] = []
        self.calls = 0

    async def file_action_request(self, *, agent_id, payload, rationale="", **_kw):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        self.filed.append(payload)
        return type("R", (), {"id": f"req{len(self.filed)}"})()
```

7. `test_twelve_concurrent_recurrences_raise_one_approval` — 12 concurrent `on_fault_event` tasks over a
   barrier store. `requests.calls == 1` (the premise: one filing was reached) and
   `len(requests.filed) == 1`. Reproduces the measured 12 → 11.
8. `test_a_cancelled_caller_leaves_the_outcome_unknown_and_holds` — `create_task`, then
   **`await requests.entered.wait()`** so the filing provably started, then `cancel()`, then
   `pytest.raises(asyncio.CancelledError)`. Assert the recorded state is `_UNKNOWN`; release the
   barrier; drive the next recurrence; assert `requests.calls == 1`.
   **A test that calls `create_task()` and then `cancel()` without awaiting a barrier is vacuous** — the
   coroutine never starts and the assertion cannot fail. That exact shape shipped in the reverted attempt.
   Do not reproduce it.
9. `test_a_store_that_commits_then_raises_does_not_produce_a_second_approval` — a double that appends the
   payload and *then* raises (the `file_request` commit → cache → emit ordering). Premise:
   `len(store.filed) == 1` — it did land. Then assert the state is `_UNKNOWN`, drive a recurrence, and
   assert `len(store.filed) == 1`. **This is the test that would have caught defect 3.**
10. `test_a_refused_payload_is_not_retried_on_every_recurrence` — a double returning `None`. Three
    recurrences → `calls == 1`, state `_REFUSED`, and exactly one `WARNING`. Read log records with
    `record.getMessage()`.
11. `test_a_resolution_lets_a_new_report_with_the_same_signature_propose` — the defect-6 test. Real
    `FaultReportStore` so ids rotate. Start a filing over the barrier; deliver `fault_resolved` for that
    signature; release and let the in-flight settle (it writes a terminal state under the **old** id);
    file a fresh fault with the same signature (new id); drive `on_fault_event`; assert a **second**
    approval is filed.
12. `test_no_approval_surface_is_checked_before_anything_is_reserved` — `self._requests = None`; assert
    no entry is recorded, and that attaching a working store and re-driving the same event files one.
13. `test_the_proposal_map_is_bounded` — more than `_PROPOSALS_MAX` distinct fault ids; assert
    `len(dispatcher._proposals) <= _PROPOSALS_MAX`.
14. `test_propose_records_no_state` — call `propose()` directly; assert `_proposals` is untouched, and
    that the returned value is the request (public contract preserved).

### `tests/test_ad1264_payload_fits_the_contract.py` — the envelope

15. `test_a_maximal_fault_produces_a_payload_the_real_validator_accepts` — the one asked for by name.
    Build a maximal-but-valid report (`error_text` 2,000, `attempted` 1,000, `tool_id` 128,
    `agent_id` 128, `thread_id` 128, `tool_trace_ref` 128), configure 12 targets of 200 characters, drive
    the dispatcher against a capturing store, and assert
    `validate_action_payload(captured["payload"]) is not None` — the **real** function, on the **final**
    artifact. Assert the premise (`captured` is non-empty) first.
16. `test_a_long_thread_id_does_not_make_a_fault_unproposable` — carry forward, repointed to
    `THREAD_ID_MAX_CHARS`. This is case A: an ordinary fault, rejected today.
17. `test_the_target_list_is_bounded_in_count_and_length` — `resolve_targets` with 20 names of 300
    characters → ≤ 8 entries, each ≤ 64, declared order preserved, one `WARNING`.
18. `test_the_brief_survives_the_fit` — a normal fault's brief is present and readable in the fitted
    payload (the fitter must not be an unconditional truncator).
19-23. `fit_action_payload` units, in the capability-request suite or this file:
    fits an oversized value and the result validates · returns the input unchanged when it already fits ·
    returns `None` when the non-shrinkable remainder alone exceeds the bound · does not mutate its input ·
    a value of 1,200 newlines (worst-case JSON escaping) still produces a valid payload.
24-26. Regression pins: the four thresholds still agree (existing
    `test_the_threshold_matches_its_siblings` must stay green) · `RepairConfig` defaults unchanged ·
    the AD-1154 payload key set is still exactly six.

### Existing suites

`tests/test_ad1172_repair_dispatch.py` is **expected to pass unchanged**: its `_Faults` double returns a
constant fault whose `id` is `"f1"`, so `fault_id` keying behaves exactly as signature keying did for
that fixture — including `test_a_resolved_fault_can_be_proposed_again`, where the resolve pops `"f1"` and
the next event re-reserves it. **This is a prediction, not a verified fact.** If any node needs
repointing, update the assertion and record why inline — never delete it, and never shape a test to
whatever the new code happens to do.

Also run: `tests/test_ad1169_*`, `tests/test_ad1173_repair_verification.py`,
`tests/test_ad1154_*` and any file touching `capability_request` or `fault_report`.

---

## What this does NOT change — do not build

- **Durable / restart dedup. That is #1315 (BF-845) and must not be folded in.** `_proposals` is
  in-process by design here; say so in the module docstring and stop.
- **Do not make `params` occurrence-invariant.** Recorded for #1315, because it is that issue's central
  design question, not a side fix: `action_dedup_key` hashes `canonical_json(params)`
  (`capability_request.py:187`), and `params["brief"]` embeds the occurrence count via
  `render_markdown` ("returned the same error {occurrences} time(s)", `repair_brief.py:91`). So the
  approval store's own content-addressed dedup — which *is* durable, because `_refresh_cache` reloads
  every row at `start()` — cannot currently collapse recurrences onto one pending request. Removing the
  count would change what the Captain reads when deciding, and choosing the dedup key's shape is exactly
  what #1315 has to settle.
- **Do not change the four pinned thresholds** (`_DEFECT_MIN_OCCURRENCES`, `DEFAULT_PATTERN_THRESHOLD`,
  `REPEAT_THRESHOLD`, `propose_after_occurrences`). Moving the emit is the whole point.
- **Do not add a retry, timer, bounded hold, or escalation for `_UNKNOWN`.** DD-1 states why.
- **Do not add `asyncio.shield`, an `_inflight` task set, or a done-callback.** They existed only to
  support a release path that no longer exists. Reintroducing them reopens the seam that produced three
  rounds of findings.
- **Do not add a periodic scan of `fault_reports.db`,** and do not add a second path into
  `RepairDispatcher.propose()`.
- **Do not wire a production caller for `FaultReportStore.resolve()`** and do not touch
  `repair_verification.py`. `verify_and_close` having no caller is a real gap; it is not this AD.
- **Do not reorder `CapabilityRequestStore.file_request`'s commit → cache → emit.** The ambiguity it
  creates is handled in the consumer. Reordering a store with many callers is its own change.
- **Do not add a config field.** `_TARGETS_MAX`, `_TARGET_NAME_MAX` and `_PROPOSALS_MAX` are derived from
  a contract, not policy, so they are module constants. Consequently `scripts/gen_config_reference.py`
  does **not** need running.
- **Do not touch the HXI.** The approval renders through the existing capability-request surface.

---

## Tracking

| File | Update |
|---|---|
| `PROGRESS.md` | One shipped line: the defect, the measured before/after, and the honest at-most-once guarantee. |
| `docs/development/roadmap.md` | Bug Tracker row for BF-841 → closed by AD-1264. |
| `DECISIONS.md` | `AD-1264` entry recording DD-1 through DD-4, in particular why `refused` and `unknown` both hold and what the resulting guarantee is and is not. |

`prompts/*.md` is never staged.

---

## Acceptance criteria

1. `FaultReportStore.file_fault` emits `FAULT_REPORTED` on the coalesce branch with the post-increment
   count; five faults with one signature produce five events carrying 1..5.
2. Twelve concurrent recurrences of one signature file **exactly one** approval, proven with a barrier
   double that records it was reached.
3. A cancelled caller records `_UNKNOWN` and the next recurrence files nothing — proven by a test that
   waits on a barrier before cancelling, so the filing provably started.
4. A store that commits and then raises records `_UNKNOWN`; the next recurrence files nothing, and the
   Captain ends with exactly one pending request.
5. A refused payload is not retried on subsequent recurrences and logs once.
6. A resolution followed by a new report with the same signature proposes again.
7. A maximal-but-valid fault, with 12 configured 200-character targets and a 128-character `thread_id`,
   produces a payload that the **real** `validate_action_payload` accepts.
8. `fit_action_payload` validates the final artifact rather than computing a length, returns `None` when
   no value fits, and does not mutate its input.
9. One end-to-end crossing test runs a real `FaultReportStore` → real `RepairDispatcher` → real
   `CapabilityRequestStore` and asserts exactly one pending `kind="action"` row after two occurrences.
10. No test uses `create_task()` followed by an immediate `cancel()` without a barrier proving the
    coroutine started.
11. `tests/test_ad1172_repair_dispatch.py` passes; any repoint is recorded inline with its reason.
12. Focused gate green, then the consolidated gate:
    `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile`. Reconcile
    `baseline_nodes + new_tests == this_run_nodes` before reading any log; triage any failure at `-n 0`.
13. Run the `Diff Reviewer` subagent on the staged diff with a different model than wrote the code, and
    address its findings before committing. **If three review rounds land findings inside the same seam,
    stop and hand the state model back to Architect rather than opening a fourth.**
14. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified against codebase (2026-08-24)

```
grep -n "_emit_fault|return existing" src/probos/fault_report.py
   58: _THREAD_ID_MAX = 128
  262:             existing.occurrences += 1
  265:             return existing                       # <- the missing emit
  281:             occurrences=1,
  287:         self._emit_fault("FAULT_REPORTED", report)
  379:     def get(self, signature_or_id) -> FaultReport | None:   # SYNCHRONOUS
  387:     def _emit_fault(self, event_name, report) -> None:
  402:                 "occurrences": report.occurrences,          # already carried
  405:         except Exception:                                   # swallows its own failures

grep -n "_THREAD_ID_MAX|_ACTION_PAYLOAD_MAX_CHARS|def validate_action_payload|def action_dedup_key" src/probos/capability_request.py
   54: _ACTION_PAYLOAD_MAX_CHARS = 4000
   63: _THREAD_ID_MAX = 64                                 # vs 128 on the fault report
   99: def validate_action_payload(payload) -> dict | None
  141:     if len(encoded) > _ACTION_PAYLOAD_MAX_CHARS:    # CANONICAL JSON, not Python chars
  174: def action_dedup_key(*, agent_id, payload, work_item_id)
  187:     canonical_params = _canonical_json(payload.get("params"))   # brief is IN the key
  345:             await self._db.commit()                 # commit ...
  346:         self._cache[req.id] = req                   # ... cache ...
  347:         self._emit(EventType.CAPABILITY_REQUEST_FILED, {   # ... THEN a callback that can raise
  360:     async def file_action_request(...)
  390:         validated = validate_action_payload(payload)
  398:             return None                             # the ONLY None, before any await/write
  409:             return existing                         # a pending dedup hit
  413:         return await self.file_request(             # request or raise -- never None

grep -n "_proposed|propose|thread_id" src/probos/cognitive/repair_dispatch.py
   60:         self._proposed: set[str] = set()
   85:                 self._proposed.discard(signature)   # defect 6 clear
   97:             if signature in self._proposed:         # defect 1 check ...
  100:             await self.propose(signature)
  116:             self._proposed.add(signature)           # ... defect 1 mark, after the await
  162:                         "brief": brief.render_markdown()[:_BRIEF_PREVIEW_MAX],   # Python chars
  167:                     "thread_id": brief.thread_id,   # defect 4: forwarded at 128

grep -n "occurrences|_TITLE_MAX|def resolve_targets" src/probos/cognitive/repair_brief.py
   46: _TITLE_MAX = 120
   47: _EVIDENCE_MAX = 4000
   91:             f"{self.occurrences} time(s):",         # why params vary per occurrence
  195: def resolve_targets(config) -> tuple[str, ...]     # unbounded today

grep -n "create_task|_event_listeners" src/probos/runtime.py
 1751:                     task = asyncio.create_task(fn(event))   # a task PER LISTENER PER EVENT
```

**Absence verified (each run, not recalled):**

```
CLAIM: the FAULT_REPORTED listener is the only path into RepairDispatcher.propose()
RUN:   grep -rn "\.propose\(|def propose|wire_repair_dispatcher" src/
FOUND: repair_dispatch.py:100 (inside on_fault_event), :107 (def), :183 (wiring);
       finalize.py:2811/2827/2829/4770 (the sole wiring call).
       Every other `propose` hit is an unrelated symbol
       (cognitive_agent.propose_appearance/propose_voice_profile, strategy.propose,
       runtime.propose, priority4_cleanup.propose_boundary_evolution, three router handlers).
HOLDS: yes -- one call site, reached only via the registered listener. No DB scan.

CLAIM: FaultReportStore.resolve() has no production caller, so defect 6 is latent
RUN:   grep -rn "fault_report_store|fault_store|verify_and_close" src/
FOUND: repair_verification.py:192 is the sole `store.resolve(...)`, inside verify_and_close;
       grep -rn "verify_and_close" src/  ->  ONE hit: its own def at repair_verification.py:177.
HOLDS: yes -- latent today, reachable the moment AD-1173 is wired.

CLAIM: nothing outside repair_dispatch.py reads `_proposed`
RUN:   grep -rn "_proposed" src/ tests/ ui/
FOUND: repair_dispatch.py:60/85/97/116 only. Other hits are *_PROPOSED EventType members
       (events.py, agents.py, compute_use.py), test function NAMES, and an unrelated
       local attribute in test_ad721d_2.
HOLDS: yes -- safe to replace.

CLAIM: AD-1264 is free
RUN:   gh issue list --state all --limit 300 --jq 'max AD number'   ->  1261
       grep -rn "AD-126[4-9]" prompts/
FOUND: one hit -- ad-1263-*.md:22 "Next free AD after this one: AD-1264".
HOLDS: yes. Highest BF, all states: BF-845 (#1315).
```

**Payload measurements** were taken by running the dispatcher's own payload construction through the
real `validate_action_payload` / `_canonical_json`; the four cases and the target-bound sizing are in the
Problem and DD-2 tables above. They differ in magnitude from the numbers in #1307's comment thread
(6,940 / 5,280) but confirm the same two defects; the figures quoted here are the ones measured for this
prompt.
