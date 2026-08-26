# AD-1267 — a recurring fault reaches the repair dispatcher, and the approval store owns the proposal

**Status:** Ready to build — **Revision 2 (2026-08-26), re-verified against HEAD `51792f0b`**
**Closes:** #1307 (BF-841). **Subsumes** #1315 (BF-845) — see DD-6.
**Depends on:** none outstanding. BF-854 (the stated blocker in Revision 1) **has landed** —
`d892f9cc BF-854: refuse a payload the dedup key cannot hash`.
**Supersedes:** `prompts/ad-1264-a-recurring-fault-reaches-the-repair-dispatcher.md` (built, reviewed
twice, reverted at its own stop rule). Archive that file; do not build from it.
**Estimated tests:** ≥ 23 new

---

## Numbering — re-derived, not inherited

**No new AD is allocated.** This decision already owns `AD-1267`, the number was never shipped, and
the work is unchanged in intent. Reusing an allocated-but-unbuilt number for *the same decision* is
correct; the hard rule forbids reusing a number for a *different* one.

Ceiling enumerated at HEAD from the three authoritative sources (**not** `open-ads-report.md`):

| Source | How | Ceiling |
|---|---|---|
| git subjects | `git log --all --format='%s'` → `AD-(\d+)` | **1272** |
| prompt files | `prompts/ad-*.md` | **1272** |
| GitHub issues, all states | `#1324` = "AD-1270: platform maturity…" | 1270 |
| BF, git | `git log --all --format='%s'` → `BF-(\d+)` | 854 |
| BF, GitHub | `#1325` = "BF-855: a fault signed over the untruncated error…" | **855** |

**Overall AD ceiling: AD-1272. Next free: AD-1273 — not consumed here. BF ceiling: 855; next free: 856.**

Verified unshipped, so the number is genuinely free to re-use:

```
git log --all --oneline --grep 'AD-1267'   -> (no commits)
git log --all --oneline --grep 'BF-845'    -> (no commits)
```

---

## Revision 2 — what changed at HEAD, and why Revision 1 can no longer be built as written

Revision 1 was drafted before `985f4f10 (AD-1257 + AD-1269)`. Four of its statements are now false.

| # | Revision 1 said | HEAD says | Consequence |
|---|---|---|---|
| R1 | `_persist_occurrence` writes **two** columns, so "every other field of the report is invariant on coalesce" | it writes **four** — `occurrences, last_seen_at, tool_trace_ref, observed_as` (`fault_report.py:801-802`) | **DD-2's invariance proof is void.** Removing the occurrence count is necessary but **not sufficient**. See P4/DD-3. |
| R2 | anchors at `fault_report.py:258-265`, `:287`; `capability_request.py:292`, `:422`, `:423`, `:186-197` | `:683-686`, `:707`; `:313`, `:443`, `:446`, `:195-220` | every SEARCH anchor and citation is stale; all refreshed below |
| R3 | "BF-854 must land first" | landed (`d892f9cc`) | dependency discharged |
| R4 | AD-1268 "must land before `repair.enabled` is turned on"; `RepairConfig.enabled` defaults to `False`, "so nothing reaches a Captain until both are in" | `config/system.yaml:611` ships **`enabled: true`** | the safety argument for deferring AD-1268 is **gone on this instance**. DD-5 restates the risk honestly. |

R1 is the substantive one and is a **new defect Revision 1 does not cover**. It is P4 below.

---

## The problem at HEAD

Five defects, one chain. Every claim is a grep pasted in *Verified Against Codebase*.

### P1 — the dispatcher can never fire (#1307 / BF-841, still OPEN)

`_emit_fault` is called from **exactly two** sites in `fault_report.py`: `:707` (the *create* branch)
and `:843` (`resolve`). The coalesce branch — `file_fault`'s `if existing is not None and
existing.status in ("open", "diagnosing")` — persists the increment and **returns without emitting**.

So every `FAULT_REPORTED` event carries `occurrences=1` (`_emit_fault` reads `report.occurrences`,
`:880`), while `RepairDispatcher.on_fault_event` requires
`occurrences >= propose_after_occurrences` (default 2, `repair_dispatch.py:92-95`).

> **At HEAD, no repair proposal can ever be raised.** `FAULT_REPORTED` has exactly one emitter and
> exactly one consumer, and the two cannot agree.

**This corrects the premise carried in #1315's body and in the issue framing.** AD-1269 made the
detector *file* faults; it did **not** move the emit. #1315's "Before BF-841, only the first
occurrence emitted… BF-841 makes every recurrence observable" describes the **reverted AD-1264
diff**, not HEAD. #1307 is still open and none of that code exists here — which also means BF-845's
measured symptom (`1 pending → restart → 2 pending`) is currently **unreachable in production**,
because nothing proposes at all. It becomes reachable the moment Section 1 lands, which is exactly
why the two must ship together (DD-5, Q7).

### P2 — the in-process guard is marked after the await (the storm)

`_proposed` is checked at `repair_dispatch.py:97` and added at `:116` — *after*
`await self._file_dispatch_request(...)` returns. `runtime._emit_event_local` creates an
**independent task per coroutine listener** (`runtime.py:1746-1752`), so N recurrences in flight all
pass the check before any of them marks. Once P1 is fixed this becomes one Captain approval per
occurrence.

The dispatcher's docstring claims "this runs inline on the event bus" (`repair_dispatch.py:69-70`).
That is **false**, and it is the sentence that makes the missing guard look safe.

### P3 — the durable key is unstable, so the store's own dedup never matches (#1315 / BF-845)

`action_dedup_key` (`capability_request.py:195`) hashes
`agent_id | tool_id | action | scope_key | work_item_id | canonical_json(params)`. `params["brief"]`
is `render_markdown()`, which renders the occurrence count verbatim (`repair_brief.py:90-91`:
``f"The `{self.tool_id}` tool returned the same error " f"{self.occurrences} time(s):"``).

Occurrence 2 and occurrence 3 are therefore **different keys**, and `_find_pending_action` finds
nothing. Note this needs **no restart**: two pending approvals for one `fault_id` appear inside a
single process. The in-process set was papering over an unstable key.

### P4 — the brief also drifts on trace adoption (**new at HEAD; absent from Revision 1**)

AD-1269 added an absent→present adoption inside the *coalesce* branch: when a later occurrence
carries a `tool_trace_ref` and the canonical row has none, the row takes **both** `tool_trace_ref`
and `observed_as`, and `_persist_occurrence` now writes all four columns.

Both adopted fields reach the brief:

- `RepairDispatcher.build_brief` calls `summarise_trace_ref(...)` off `fault.tool_trace_ref` and
  passes the result as `trace_summary`, which renders a whole `## Evidence from the run` section
  (`repair_brief.py:100-108`).
- `render_markdown`'s Provenance block appends ``f"- Tool trace: `{self.tool_trace_ref[:16]}`"``
  (`repair_brief.py:123-124`).

So a fault whose first occurrence had no trace and whose third does produces **a different brief for
the same fault**, hence a different key, hence a second approval — *even with the occurrence count
removed*. Bounded (the adoption is one-way and fires at most once per fault) but real, and it is why
DD-3 excludes fields by **proof against the mutation set** rather than by convention.

### P5 — an ordinary fault is unproposable at all

Two contract mismatches, both live:

- `fault_report._THREAD_ID_MAX = 128` (`:58`) vs `capability_request._THREAD_ID_MAX = 64` (`:63`);
  `_file_dispatch_request` forwards `brief.thread_id` unchanged (`repair_dispatch.py:166`). A normal
  report with a 128-char thread id fails `validate_action_payload` (`:134`) → `file_action_request`
  returns `None` → **no request, ever**.
- `resolve_targets` (`repair_brief.py:195`) is **unbounded** — it dedups and preserves order but caps
  neither count nor name length — while the canonical payload is capped at
  `_ACTION_PAYLOAD_MAX_CHARS = 4000` (`capability_request.py:54`).

---

## Solution

### DD-1 — the durable reservation already exists; do not build a second one

**Ruling on Q1: the approval store carries it. No new state. Delete `_proposed`.**

`CapabilityRequestStore` already deduplicates durably:

- `_refresh_cache` (`capability_request.py:313`) — `"SELECT … FROM capability_requests"` with **no
  `WHERE` clause**, so it loads **every row in every status** on `start()`.
- `_find_pending_action` (`:443`) re-derives `action_dedup_key` from each cached row and returns the
  match.

That is a durable, restart-surviving reservation, already built and already tested. It does not fire
for repairs for exactly one reason — the key is unstable (P3, P4). **Make the key stable and delete
the record.** Adding a second durable record of the same fact would be the mistake.

> **Method-name correction:** this store's loader is `_refresh_cache`. It has **no** `_load_cache` —
> that name belongs to `FaultReportStore` (`fault_report.py:582`), `IntentGrantStore`, and six
> others. Do not grep for the wrong one and conclude the mechanism is missing.

> **Path correction:** the module is `src/probos/capability_request.py`, **not**
> `src/probos/substrate/capability_request.py`.

### DD-2 — split "who owns the record" from "who is filing right now"

**Ruling on Q5.**

| Concern | Owner | Lifetime |
|---|---|---|
| *"Has this fault already asked?"* | the **approval store**, keyed on a stable dedup key | durable, survives restart |
| *"Are two listener tasks filing **right now**?"* | an in-process `set[str]` of fault ids | **the await, and no longer** |

The in-process set **survives as an optimisation only**, and it must be taken *before* the await
(P2). Because it is no longer the record, **unconditional release in `finally` is correct**: it never
claims anything was filed — the store answers that on the next occurrence.

This dissolves the two hazards that forced the reverted predecessor into a four-state model:

- **Commit-then-raise.** `file_request` commits (`:364`), caches (`:367`), then emits (`:368`), and
  the emit can raise. Release anyway: the row is committed, so the next recurrence calls
  `file_action_request`, `_find_pending_action` finds it, and returns it unchanged.
- **Cancellation vs a landed insert.** Identical — the row exists; the next event dedups onto it.

A reservation that is *also* the record cannot be released, which is what forces "nothing releases
except a resolution" and produces an unbounded, jam-prone map with a trim policy that trades a
duplicate approval for a **missed** one. Do not rebuild that.

### DD-3 — `params` carries identity only, and identity is *proven* invariant, not asserted

**Ruling on Q2.** Everything in `params` is hashed, so `params` may contain **only** fields invariant
across recurrences of one fault report. At HEAD the invariant set must be derived from the coalesce
branch's *actual* mutation set, which is now four fields, not two:

```
UPDATE fault_reports SET occurrences = ?, last_seen_at = ?, tool_trace_ref = ?, observed_as = ?
```

**The stable identity is the tuple**

```
(tool_id="repair", action="dispatch", scope_key=<fault.tool_id>,
 params={fault_id, signature, targets, brief*})
```

where `brief*` is a projection that excludes every mutable field.

| Part | Source | Why invariant |
|---|---|---|
| `tool_id` = `"repair"` | `repair_dispatch.REPAIR_TOOL_ID` (`:36`) | constant |
| `action` = `"dispatch"` | `repair_dispatch.REPAIR_ACTION` (`:37`) | constant |
| `scope_key` = `brief.tool_id` | `FaultReport.tool_id`, set by `_resolve_identity` at create | **not** in the coalesce mutation set |
| `params["fault_id"]` | `FaultReport.id` = `uuid.uuid4().hex[:12]` (`fault_report.py:688`) | set at create, never mutated on coalesce; a *resolved* fault that recurs takes the create branch and gets a **new** id — exactly the identity rotation wanted |
| `params["signature"]` | `FaultReport.signature` | it **is** the coalescing key |
| `params["targets"]` | `resolve_targets(config)` | config-derived; a changed target list is genuinely a different ask |
| `params["brief"]` | new `RepairBrief.render_for_payload()` | invariant **by construction** — see below |
| occurrence count | — | **excluded**: volatile by definition (P3) |
| `trace_summary`, `tool_trace_ref` | — | **excluded**: mutable on coalesce (P4) |

**Q2 sub-ruling — `scope_key` stays `tool_id`; the fault signature does *not* move into it.** The
signature already rides in `params` and is already hashed, so relocating it buys no identity. It
would cost two things: the Captain-facing `target` string becomes `repair.dispatch @ <hex digest>`
instead of a tool name (`file_action_request` builds ``f"{target} @ {validated['scope_key']}"``,
`:432-433`), and it pre-empts AD-1268, which needs `scope_key` to express a standing answer scoped to
a **tool**. A per-signature scope cannot say "stop proposing repairs for this tool".

**`render_for_payload()` must not be a copy-paste fork.** Factor the shared body — the honest shape
is a private `_render(*, include_occurrences: bool, include_trace: bool)` that both public methods
call — so a field added later cannot appear in one and not the other. Its docstring must state *why*
each exclusion exists: the value is hashed into the approval store's dedup key, and a value that
changes across recurrences of one fault makes one fault raise one approval per change.

**How the Captain still sees the count.** `rationale` already carries it verbatim — *"The
{tool_id} tool has failed the same way {occurrences} times."* (`repair_dispatch.py:172-176`) — and
`rationale` is **not** part of the key material (`capability_request.py:205-220`). It is truncated at
`_RATIONALE_MAX = 280` (`:49`, applied at `:350`), which that sentence fits. Leave the existing text
unchanged; it is already correct and already excluded.

**How the Captain still reaches the trace.** `params["fault_id"]` resolves the full report — and
therefore the live `tool_trace_ref` — in one lookup via `FaultReportStore.get`, a synchronous plain
`def` (`fault_report.py:857`) that matches on signature *or* id. Say so in a comment at the exclusion
site, so the next reader does not "restore" the trace into the payload.

### DD-4 — bound `targets`, narrow `thread_id`, then **prove** the payload fits

Fix P5 at each source, then assert the payload fits **with a test instead of a fitter**. With
`brief` ≤ `_BRIEF_PREVIEW_MAX` (1200, `repair_dispatch.py:39`), `targets` ≤ 8 × 64, `thread_id` ≤ 64,
`fault_id` 12 and `signature` bounded, the canonical payload cannot approach 4000.

**Do not build a truncating fitter.** A binary-search helper for a case the bounds make unreachable
is machinery for an impossible state, and one test pins the guarantee more honestly than a helper
that is never expected to fire.

### DD-5 — Q3, Q4, Q7: what this ships, and what it deliberately does not

**Ruling on Q3 — what clears the reservation.**

Nothing clears it explicitly. The reservation *is* `status == "pending"`, and `_find_pending_action`
filters on it (`:446`). Three consequences, each deliberate:

1. **`fault_resolved` clears nothing, and must not.** A resolved fault that recurs takes the create
   branch and gets a **new** `fault_id`, hence a new key, hence a clean proposal. The old approval,
   if still pending, stays pending on purpose — the Captain has not answered it. Withdrawing it is a
   different act and is not silently assumed here. Delete the `_proposed.discard` at `:85`; do **not**
   replace it with anything.
2. **A *decided* fault can propose again on its next recurrence.** Denied, approved, fulfilled and
   failed all leave `pending`. The issue's argument is right — *"a denied repair that silently
   re-proposes on the next recurrence is nagging, not governance"* — and so is the
   approved-but-never-fulfilled case it implies: an approved dispatch that no harness has completed
   will re-propose while the work is still in flight, because `mark_fulfilled` is what would end it
   and nothing has called it yet.
3. **That fix is AD-1268, already drafted and unbuilt**
   (`prompts/ad-1268-a-decision-is-a-standing-answer.md`; its tests
   `test_a_denied_repair_is_not_proposed_again`,
   `test_an_approved_repair_is_not_proposed_again_while_it_is_in_flight` and
   `test_a_fulfilled_repair_is_not_proposed_again` are exactly these three states).

**Do not fix the decided case here.** It is a different seam — *"what a decision means"* rather than
*"what a proposal is"* — and fusing seams is what cost this AD two reverts.

> **Honest risk, stated because Revision 1's mitigation is gone.** Revision 1 argued it was safe to
> ship without AD-1268 because `RepairConfig.enabled` defaults to `False`. **`config/system.yaml:611`
> ships `enabled: true` on this instance.** So on this vessel a denied-but-recurring fault will
> re-ask at most once per recurrence until AD-1268 lands. That is strictly better than the state
> Section 1 alone would create (one ask per occurrence, forever) and strictly worse than governed.
> **Build AD-1268 next.**

**Ruling on Q4 — refresh vs duplicate: neither, in this AD.** The occurrence count is genuinely
useful and does go stale, and updating the pending request *is* more honest than filing a second.
But it is a distinct decision with consequences the issue names correctly — it changes what the
Captain sees after they have already looked at it — and it needs a mutation path
(`file_action_request` returns the existing row **unchanged** today, `:425-431`) plus a rule about
whether a refresh re-notifies, which collides with the once-per-fault notice guarantee below.
**Ship stability first.** The count reaches the Captain via `rationale` on the filing, and the live
count is one `fault_id` lookup away. If refresh is wanted, it is a new AD (AD-1273 is free).

**Ruling on Q7 — scope: one issue, but it is not #1315 alone.** P1 and P3/P4 must ship in the same
commit:

- P1 without P3/P4 turns a dead path into an approval storm — one Captain approval per occurrence.
  That is a regression, and it is precisely what the reverted AD-1264 shipped.
- P3/P4 without P1 is unreachable and cannot be tested end-to-end, because no event ever crosses the
  threshold — the fix would be built, green, and inert.

So **#1307 and #1315 close together.** Refresh (Q4) splits out. The decided case splits out to
AD-1268.

**Ruling on Q8 — no new AD.** AD-1267 is this decision, allocated and unshipped. AD-1273 stays free.

### DD-6 — relationship to #1315 (BF-845)

**AD-1267 subsumes it.** #1315 asks for durable repair-proposal dedup keyed on a stable identity
independent of the occurrence count and the rendered brief. DD-1 shows the durable mechanism already
exists and already survives restart; DD-3 supplies the stable identity and additionally closes the
trace-adoption drift (P4) that #1315 does not know about.

**The guarantee this AD makes:**

> **At most one *pending* repair approval exists per fault report — across restarts, across
> concurrent recurrences, and across trace adoption.**

**What it does not claim:** a fault whose approval has been *decided* can raise a new approval on its
next recurrence. That is AD-1268.

Close #1315 as subsumed, citing DD-1/DD-3 — **and correct its premise in the closing comment** (see
*Tracking*).

---

## Implementation

### Section 1 — `src/probos/fault_report.py`: emit on the coalesce branch

The producer fix (P1). Anchor verified verbatim at HEAD (`:683-686`). It sits **after** the AD-1269
adoption block — do not anchor above it. Confirm the SEARCH matches before applying.

```
===SEARCH===
            await self._persist_occurrence(existing)
            return existing

        report = FaultReport(
===REPLACE===
            await self._persist_occurrence(existing)
            # AD-1267: the recurrence IS the signal. Emitting only on the create
            # branch meant every event carried occurrences=1 while the repair
            # dispatcher requires >= 2, so no repair could ever be proposed.
            self._emit_fault("FAULT_REPORTED", existing)
            return existing

        report = FaultReport(
===END REPLACE===
```

`_emit_fault` swallows its own failures (`:884-887`) and the payload already carries `occurrences`
(`:880`), so `file_fault`'s documented "never raises" contract is unaffected. **Nothing else in this
file changes** — in particular, do not touch `_persist_occurrence`, `_resolve_identity`, or the
AD-1269 adoption block.

### Section 2 — `src/probos/cognitive/repair_brief.py`

**2a. A stable projection.** Add `render_for_payload()` beside `render_markdown()`, both delegating
to one private renderer parameterised on `include_occurrences` and `include_trace`. The payload form
excludes the occurrence count (P3), the `## Evidence from the run` section, and the `- Tool trace:`
provenance line (P4). Docstring states why, and names `params["fault_id"]` as the route to the live
trace.

**2b. Bound the targets** at `resolve_targets` (`:195`), the single source of the list — after dedup,
preserving declared order, clipping each name to `_TARGET_NAME_MAX` and the list to `_TARGETS_MAX`.
Log once at `WARNING` when clipped, naming how many were dropped and why.

```
===SEARCH===
_TITLE_MAX = 120
_EVIDENCE_MAX = 4000
===REPLACE===
_TITLE_MAX = 120
_EVIDENCE_MAX = 4000

# AD-1267: the target list reaches the approval payload, whose canonical JSON is
# capped at _ACTION_PAYLOAD_MAX_CHARS (4000). resolve_targets was unbounded, so a
# long or long-named target list made an ordinary fault permanently unproposable.
_TARGETS_MAX = 8
_TARGET_NAME_MAX = 64
===END REPLACE===
```

### Section 3 — `src/probos/capability_request.py`: export the bound, nothing else

```python
#: AD-1267: the action-approval contract's own thread_id bound, exported so a
#: producer with a wider field (fault reports allow 128) narrows to the consumer's
#: contract instead of forwarding a value that will be rejected outright.
THREAD_ID_MAX_CHARS: int = _THREAD_ID_MAX
```

Circular-import check, run: this module imports only `probos.events` and `probos.protocols` from the
package; `repair_dispatch` sits in `cognitive/` above it, so a direct import is clean.

Do **not** add `fit_action_payload`. Do **not** change `validate_action_payload`,
`_ACTION_PAYLOAD_MAX_CHARS`, `action_dedup_key`, `file_action_request`, `file_request`,
`_find_pending_action`, `decide`, or `mark_fulfilled`.

### Section 4 — `src/probos/cognitive/repair_dispatch.py`

**4a. `__init__`.** Replace `self._proposed: set[str] = set()` (`:60`) with:

```python
# AD-1267: fault ids with a filing IN FLIGHT right now. This is concurrency
# control, NOT the record of what has been proposed -- the approval store holds
# that, durably, keyed on a payload that no longer varies per occurrence. So it
# releases unconditionally: if a filing committed and then raised, the next
# recurrence dedups onto the committed row rather than filing again. Bounded by
# the number of concurrent listener tasks, so it needs no cap and no trim.
self._inflight: set[str] = set()
```

Nothing outside this module reads `_proposed` — **enumerated before deleting**:

```
CLAIM: nothing outside repair_dispatch.py reads `_proposed`
RUN:   grep -rn "_proposed" src/ tests/ ui/
FOUND: repair_dispatch.py:60/85/97/116 only. Other hits are unrelated *_PROPOSED
       EventType members (events.py:244/271, routers/agents.py:895,
       tools/browser/compute_use.py:237) and a `test_ad721d_2` local attribute.
HOLDS: yes
```

Paste that enumeration in the commit message.

**4b. `on_fault_event`.** Order matters; there must be **no `await` between the check and the add**.

1. **Fix the docstring.** It claims "this runs inline on the event bus" (`:69-70`) — false.
   `runtime._emit_event_local` creates an independent task per coroutine listener
   (`runtime.py:1746-1752`), and that per-event concurrency is precisely why the guard is taken
   before the await. Say it swallows `Exception` but not `BaseException`, so cancellation propagates.
2. Keep the malformed-event guards unchanged (`:76-82`).
3. `fault_resolved` → **return, clearing nothing.** State DD-5(1) inline.
4. Keep the `enabled` and threshold gates unchanged (`:90-95`).
5. Check the approval surface **before** guarding: if `self._requests` is `None` or lacks
   `file_action_request`, log at `info` (reuse the message at `_file_dispatch_request`, `:146-151`)
   and return, having provably written nothing.
6. `report = self._faults.get(signature)` — a synchronous plain `def` (`fault_report.py:857`).
   `None` → return.
7. `fault_id = str(getattr(report, "id", "") or "") or signature`. Document the signature fallback
   rather than letting it differ silently.
8. `if fault_id in self._inflight: return` then `self._inflight.add(fault_id)`. **No `await` between
   7 and 8.** That atomicity with respect to the event loop is what closes the storm without a lock.
9. ```python
   try:
       await self.propose(signature)
   finally:
       self._inflight.discard(fault_id)
   ```
   The `finally` is synchronous — no I/O, no await — so cancellation cannot skip it or stall the loop.

**4c. `propose`.** Keeps its signature `async def propose(self, signature: str) -> Any | None` and its
success log. Delete `self._proposed.add(signature)` (`:116`). Its docstring must say it does **not**
take the in-flight guard — `on_fault_event` owns that — so a direct operator call is deliberate and
still safe, because the store deduplicates it.

**4d. `_file_dispatch_request`.** Keeps returning `Any | None`. Changes:

- Narrow the thread id: `(brief.thread_id or "")[:THREAD_ID_MAX_CHARS]`, with a comment naming both
  bounds (128 vs 64) and noting the full thread id is one lookup away via `params["fault_id"]`.
- `params` stays four keys — `fault_id`, `signature`, `targets`, `brief` — with `brief` from
  `render_for_payload()`, still clipped at `_BRIEF_PREVIEW_MAX`.
- Add a comment above `params` stating the invariant: **every value here is hashed into
  `action_dedup_key`, so nothing that varies between recurrences of one fault may appear — and the
  coalesce branch mutates `occurrences`, `last_seen_at`, `tool_trace_ref` and `observed_as`.** Naming
  all four is what stops a future edit re-adding the trace.
- `rationale` unchanged.

---

## Tests

Three files. **Every negative assertion needs a positive premise assertion beside it** — assert you
reached the path before asserting what did not happen on it.

### `tests/test_ad1267_recurrence_is_emitted.py` — the producer (P1)

1. `test_a_recurrence_emits_with_the_post_increment_count` — two faults → `[1, 2]`.
2. `test_every_recurrence_is_observable` — five faults → `[1, 2, 3, 4, 5]`, asserting `max(...) >= 2`
   with a message naming the dispatcher threshold.
3. `test_a_different_signature_starts_its_own_count` — `[1, 1, 2]`.
4. `test_a_resolved_fault_that_recurs_is_a_new_report` — new `id`, `occurrences == 1`, two events
   both carrying 1.
5. `test_an_emit_failure_still_lets_the_turn_finish` — exploding `emit_event`; `file_fault` still
   returns the coalesced report.
6. `test_the_adoption_branch_still_emits` — occurrence 2 arrives *with* a trace ref where occurrence 1
   had none. Assert the adoption happened (`tool_trace_ref` now set — the positive premise) **and**
   that the event still fired at `occurrences == 2`.

> The `_Capture` double must expose its recording for the **test** to read. An assertion placed
> inside a double is swallowed by `_emit_fault`'s own `except Exception` (`:884`) and proves nothing.

### `tests/test_ad1267_one_pending_approval_per_fault.py` — the guarantee (P2, P3, P4)

7. **`test_the_key_is_stable_across_occurrence_counts`** — the P3 reproduction at the level of
   `action_dedup_key`, using payloads built by the real `_file_dispatch_request` path at `occurrences`
   2 and 3. **Must fail against HEAD.**
8. **`test_the_key_is_stable_across_trace_adoption`** — the **P4** reproduction, and the case
   Revision 1 has no test for. File at occurrence 2 with `tool_trace_ref=None`; drive occurrence 3
   carrying a ref so the AD-1269 branch adopts it; assert the adoption occurred (positive premise),
   then assert **one** pending request and an unchanged key. **Must fail against HEAD.**
9. **`test_occurrences_two_three_and_seven_file_one_approval`** — real `FaultReportStore` → real
   `RepairDispatcher` → real `CapabilityRequestStore` on `tmp_path`. Drive seven faults, replay the
   captured events in order, assert exactly **one** pending `kind == "action"` request. Positive
   premise: assert the first occurrence filed **nothing**, and assert ≥ 3 events crossed the
   threshold — otherwise "one approval" could mean "the path never ran".
10. **`test_the_approval_survives_a_restart`** — the #1315 reproduction end to end. File at occurrence
    2, `stop()`, construct a **new** store on the same `db_path`, `start()`, drive occurrence 3;
    assert still one pending row and the **same request id**.
11. `test_concurrent_recurrences_file_one_approval` — the storm (P2). Do **not** use a sleep. Use a
    rendezvous: a store double whose `file_action_request` parks until N callers are inside together,
    then releases; drive N concurrent `on_fault_event` tasks via `asyncio.gather`. Assert one filing.
    Then assert the guard **released**, by driving one more event and observing a second filing
    attempt reach the store — a guard that never releases passes the first half alone.
12. `test_a_filing_that_commits_then_raises_does_not_file_twice` — a store whose
    `file_action_request` inserts and then raises. Assert `_inflight` released, then drive the next
    recurrence against the real store and assert it dedups onto the committed row.
13. `test_a_cancelled_filing_releases_the_guard` — cancel mid-await; assert `_inflight` is empty and
    `CancelledError` **propagated** (not swallowed). Ensure the coroutine actually ran before
    cancelling — a `create_task()` + immediate `cancel()` with no yield never executes the body and
    the assertion cannot fail. That exact vacuous test shipped in the reverted attempt.
14. `test_a_resolved_fault_that_recurs_can_propose_again` — resolve, recur; assert a **second**
    pending approval with a **different** `fault_id` (DD-5(1)).
15. `test_one_captain_notice_per_fault` — assert `CAPABILITY_REQUEST_FILED` is emitted **once** across
    occurrences 2..7. Positive premise: assert it fired at least once.

### `tests/test_ad1267_payload_fits_the_contract.py` — the bounds (P5)

16. `test_an_ordinary_fault_with_a_128_char_thread_id_is_accepted` — the P5 reproduction. **Must fail
    against HEAD** with `validate_action_payload(...) is None`.
17. `test_the_thread_id_is_narrowed_not_dropped` — the stored value is the 64-char prefix, and
    `params["fault_id"]` still resolves the full report.
18. `test_targets_are_clipped_to_eight_by_sixty_four` — count and per-name length, declared order
    preserved, one WARNING logged.
19. **`test_a_maximal_fault_still_fits`** — the assertion that replaces the fitter. Every field at its
    documented maximum, 8 targets of 64 chars; assert `validate_action_payload(payload) is not None`
    **and** record the canonical JSON length in the assertion message, so a future field that pushes
    it over says so and names the number.
20. `test_the_brief_in_the_payload_has_no_occurrence_count` — assert the payload brief omits the
    count **and** that `render_markdown()` still contains it. Both halves, or this passes by
    rendering nothing.
21. `test_the_brief_in_the_payload_has_no_trace` — the same two-sided shape for `trace_summary` and
    the `- Tool trace:` provenance line.
22. `test_the_rationale_still_tells_the_captain_the_count` — assert the count appears in `rationale`,
    **and** that `rationale` is absent from the key material, by filing two requests differing only in
    rationale and asserting they dedup onto one.
23. `test_the_payload_keys_are_exactly_the_four` — pins `set(params) == {"fault_id", "signature",
    "targets", "brief"}`, so a future field cannot silently rejoin the key.

---

## What this does NOT change

- **The four pinned thresholds.** `_DEFECT_MIN_OCCURRENCES` (`fault_report.py:164`),
  `DEFAULT_PATTERN_THRESHOLD` (`tools/failure_telemetry.py:39`), `REPEAT_THRESHOLD`
  (`cognitive/trace_analysis.py:51`) and `repair.propose_after_occurrences`
  (`config/system.yaml:615`) are pinned transitively equal by
  `tests/test_ad1172_repair_dispatch.py:305-315` and `tests/test_ad1171_trace_analysis.py:666`.
  **The emit moves, not the threshold.** "Once is a transient, twice is the tool" stays intact.
- **`FAULT_REPORTED` / `FAULT_RESOLVED` semantics, payload shape and subscriber list.** Enumerated:
  the only emitter is `fault_report.py:707/843`, and the only consumer in `src/` is `RepairDispatcher`
  (`repair_dispatch.py:214`). The payload keys (`fault_id, tool_id, signature, occurrences, status`)
  are unchanged — this AD adds an emission **site**, not a field.
- **One Captain-facing notice per inserted request.** `file_request` emits
  `CAPABILITY_REQUEST_FILED` (`capability_request.py:368`) → `startup/finalize.py:2864` →
  `capability_request_notifier` DM. `file_action_request` returns a deduped row **before** reaching
  `file_request` (`:425-431`), so a dedup emits nothing. Preserve that; test 15 pins it.
- **The AD-1269 identity work.** Do not touch `_resolve_identity`, `observed_as`, `ToolDefect`, the
  adoption block, or `_persist_occurrence`'s column list.
- **`capability_request.py` behaviour.** Only the `THREAD_ID_MAX_CHARS` export is added.
- **`RepairConfig`.** No new config field. `_TARGETS_MAX` and `_TARGET_NAME_MAX` are derived from the
  payload contract, not policy, so they are module constants.
- **The decided-request case.** Denied / approved / fulfilled re-proposal is **AD-1268**.
- **Refresh of a pending request.** Out of scope by DD-5(Q4).
- **`/design`, `ArchitectAgent`, `BuilderAgent`, AD-1173 verification.** Untouched.

## Do not build

- ❌ A second durable store, table, column or sidecar for proposal state. DD-1.
- ❌ A four-state proposal model, an unbounded `_proposals` map, or any trim policy. DD-2.
- ❌ `fit_action_payload` or any truncating / binary-search payload fitter. DD-4.
- ❌ Changes to `action_dedup_key`'s material, or a kind-specific dedup branch inside it.
- ❌ Withdrawal or cancellation of a pending approval on `fault_resolved`. DD-5(1).
- ❌ A refresh / update path for a pending request. DD-5(Q4).
- ❌ Clearing the reservation on an approval decision. That is AD-1268.
- ❌ Lowering any threshold to make the chain fire.
- ❌ Moving the fault signature into `scope_key`. DD-3.

---

## Tracking

- `PROGRESS.md` — AD-1267 entry; note it closes #1307 and subsumes #1315.
- `docs/development/roadmap.md` Bug Tracker — BF-841 and BF-845 rows → closed, citing this AD.
- `DECISIONS.md` — record DD-1 (the store already owns the record), DD-3 (identity-only `params`;
  `scope_key` stays `tool_id`) and DD-5 (the decided case is AD-1268; refresh is deferred).
- GitHub: close #1307 and #1315. **Correct #1315's premise in the closing comment** — its
  "BF-841 added an in-process reservation taken before the await" and "BF-841 makes every recurrence
  observable" statements describe the reverted AD-1264 diff, not HEAD; at HEAD the coalesce branch
  never emitted, so the measured `1 → restart → 2` symptom was unreachable in production until
  Section 1.

## Acceptance Criteria

1. A fault recurring across a restart with an approval already pending does **not** produce a second
   pending approval — same request id (test 10).
2. The dedup key excludes the occurrence count **and** every trace-derived field, and is stable across
   trace adoption (tests 7, 8, 20, 21, 23).
3. A recurrence emits `FAULT_REPORTED` carrying the post-increment count, so the dispatcher threshold
   is reachable (tests 1, 2, 6).
4. N concurrent recurrences of one fault file exactly one approval, and the in-flight guard is
   observably released afterwards (test 11).
5. An ordinary fault with a 128-char thread id is proposable, and a maximal fault's payload validates
   (tests 16, 19).
6. Exactly one `CAPABILITY_REQUEST_FILED` reaches the Captain per fault across occurrences 2..7
   (test 15).
7. `grep -rn "_proposed" src/` returns no hits in `repair_dispatch.py`, and the 4a enumeration is
   pasted in the commit message.
8. The four pinned thresholds are unchanged and their pinning tests still pass.
9. Focused gate green: the three new files plus `tests/test_ad1172_repair_dispatch.py`,
   `tests/test_ad1169_fault_reports.py`, `tests/test_ad1154_approval_inbox.py`,
   `tests/test_ad1257_defect_follows_failure.py`, `tests/test_bf854_unhashable_payload_rejected.py`.
10. Adversarial review (`Diff Reviewer`, a different model than the author) run on the staged diff,
    and its Critical/High findings repaired **before** commit.
11. Full repository gate green **after** the tree is frozen:
    `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`.
12. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-08-26, HEAD `51792f0b`)

```
grep -n "_proposed|fault_resolved|fault_reported|add_listener" src/probos/cognitive/repair_dispatch.py
   60:         self._proposed: set[str] = set()
   85:                 self._proposed.discard(signature)        <- cleared ONLY on fault_resolved
   97:             if signature in self._proposed:              <- checked
  116:             self._proposed.add(signature)                <- marked AFTER the await (P2)
  214:             event_types=["fault_reported", "fault_resolved"],

grep -n "_emit_fault" src/probos/fault_report.py
  707:         self._emit_fault("FAULT_REPORTED", report)   <- CREATE branch only
  843:         self._emit_fault("FAULT_RESOLVED", report)
  865:     def _emit_fault(self, event_name: str, report: FaultReport) -> None:
  880:             "occurrences": report.occurrences,        <- payload carries the count
  884:         except Exception:                             <- swallows its own failure

CLAIM: the coalesce branch does not emit, so no repair can ever be proposed
RUN:   grep -n "_emit_fault" src/probos/fault_report.py        (exactly 3 hits, above)
       grep -rn "FAULT_REPORTED|FAULT_RESOLVED|fault_reported|fault_resolved" src/
FOUND: emitters = fault_report.py:707 (create) and :843 (resolve) ONLY.
       consumers = repair_dispatch.py:214 ONLY. events.py:239-240 = the enum members.
HOLDS: yes -- every FAULT_REPORTED carries occurrences=1; the threshold is 2.

grep -n "UPDATE fault_reports SET" src/probos/fault_report.py
  801:  "UPDATE fault_reports SET occurrences = ?, last_seen_at = ?, "
  802:  "tool_trace_ref = ?, observed_as = ? WHERE id = ?"     <- FOUR columns (P4)

grep -n "occurrences|Tool trace|def resolve_targets" src/probos/cognitive/repair_brief.py
   90:  f"The `{self.tool_id}` tool returned the same error "
   91:  f"{self.occurrences} time(s):"                          <- P3
  124:  lines.append(f"- Tool trace: `{self.tool_trace_ref[:16]}`")   <- P4
  195:  def resolve_targets(config: Any) -> tuple[str, ...]:    <- UNBOUNDED (P5)

grep -n "def action_dedup_key|_RATIONALE_MAX|_ACTION_PAYLOAD_MAX_CHARS|_THREAD_ID_MAX|_refresh_cache|_find_pending_action|CAPABILITY_REQUEST_FILED" src/probos/capability_request.py
   49:  _RATIONALE_MAX = 280
   54:  _ACTION_PAYLOAD_MAX_CHARS = 4000
   63:  _THREAD_ID_MAX = 64                     <- vs fault_report.py:58 = 128 (P5)
  195:  def action_dedup_key(...)               <- material at :205-220; params hashed WHOLE
  313:  async def _refresh_cache(self)          <- SELECT with NO WHERE: loads EVERY status
  368:  self._emit(EventType.CAPABILITY_REQUEST_FILED, {...})
  425:  existing = self._find_pending_action(key)   <- dedup returns BEFORE file_request
  443:  def _find_pending_action(self, key)
  446:      if req.status != "pending" ...          <- pending-only (DD-5)

CLAIM: CapabilityRequestStore has no `_load_cache`
RUN:   grep -rn "_load_cache" src/
FOUND: fault_report.py:582, intent_grants.py:119, skill_grants.py:106, tools/permissions.py:82,
       tools/work_permits.py:245, tools/action_approvals.py:156, and three mcp_bridge stores.
       NOT capability_request.py, whose loader is `_refresh_cache` (:313).
HOLDS: yes

grep -n "_emit_event_local" src/probos/runtime.py
 1740:     def _emit_event_local(self, event, type_str) -> None:
 1746-1752: asyncio.create_task(fn(event)) per coroutine listener   <- P2 concurrency seam

grep -n "def get|_persist_occurrence" src/probos/fault_report.py
  796:     async def _persist_occurrence(self, report) -> None:
  857:     def get(self, signature_or_id) -> FaultReport | None:   <- SYNCHRONOUS plain def

grep -n "repair" config/system.yaml
  610: repair:
  611:   enabled: true                     <- SHIPS ENABLED (DD-5 risk)
  615:   propose_after_occurrences: 2

CLAIM: AD-1267 and AD-1268 have never shipped as source
RUN:   git log --all --oneline --grep 'AD-1267'   -> (empty)
       git log --all --oneline --grep 'AD-1268'   -> 0d9b0b74, 183be54a  (both `docs:` only)
       git log --all --oneline --grep 'BF-854'    -> d892f9cc  (source; dependency discharged)
HOLDS: yes -- AD-1268's two hits are documentation commits that merely mention the number.

CLAIM: #1307 (BF-841) is still open and its fix is not at HEAD
RUN:   GitHub issue list, all states; grep for a pre-await reservation in repair_dispatch.py
FOUND: #1307 state=OPEN. repair_dispatch.py:116 still marks AFTER the await; no `_inflight`,
       no `_proposals`, no pre-await guard exists in the file.
HOLDS: yes -- the "BF-841 added an in-process reservation" premise in #1315 describes the
       REVERTED AD-1264 diff, not HEAD.
```
