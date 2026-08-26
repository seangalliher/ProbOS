# AD-1204: approving a `continue` must actually resume the work

**Issue:** #1149 · **Repo:** OSS `d:\ProbOS`, branch `main`

---

## The measured defect

On the live vessel, 2026-08-04:

```
work_items
  9c54186cfb32  [in_progress]  created 22:02:27  updated 22:02:27   idle 15m
  0dd61757522b  [in_progress]  created 20:01:06  updated 20:01:09   idle 136m

capability_requests
  [approved] continue  filed 22:05:34  decided 22:05:42 by captain
  [approved] continue  filed 20:02:37  decided 20:23:27 by captain
  [approved] continue  filed 21:46:40  decided 21:40:12 by captain
  [approved] continue  filed 21:40:55  decided 21:40:11 by captain
```

**Four approvals. Zero resumptions. Two work items stranded `in_progress` permanently.**
On the last one the Captain approved **eight seconds** after filing; the item had not been
touched since before the request existed.

AD-1164 states the intent: *"the step limit becomes a checkpoint that asks instead of a cliff
that truncates."* Measured, it is a cliff.

## Two premises in the issue are WRONG — read this before designing

**1. `blocked` already exists.** The issue (quoting BF-704) says there is no paused status and
that "inventing one is a larger change than the defect warrants." Verified false:

```python
class WorkItemStatus(str, Enum):          # workforce.py
    DRAFT, OPEN, SCHEDULED, IN_PROGRESS, REVIEW, DONE, FAILED, CANCELLED, BLOCKED
```

`WorkItemStatus.BLOCKED` exists and AD-855 already uses it. **No state-machine change is needed.**

**2. The resume machinery already exists and works.** `cognitive/capability_gap_driver.py`
implements the whole BLOCKED → request → approve → resume loop:

- `on_capability_event` (L121) — subscribed to `CAPABILITY_REQUEST_FULFILLED` and
  `CAPABILITY_REQUEST_DECIDED`, wired at `startup/finalize.py:2542`. Idempotent (acts only while
  the item is `blocked`), never raises.
- `_resume` — transitions `blocked → in_progress` and **re-dispatches via
  `runtime.work_item_router`**.
- `_cancel` — on `denied`.

So this AD is **not** "build a resume path." It is "connect the continue path to the resume path
that is already running."

## The three missing links

**1. The request is not linked to its work item.**
`continue_or_ask.py:491` passes `work_item_id=None`. So `on_capability_event` recovers
`req.work_item_id`, finds `None`, logs *"no linked work item; nothing to resume"* and returns.
This single argument is the root cause.

**2. The work item is never marked `blocked`.**
It stays `in_progress`, so even a linked event would hit the idempotency guard
(`if item.status != "blocked": return`) — and it is why an agent asked later reports the task as
still running.

**3. Approval never becomes FULFILLED.**
`on_capability_event` resumes on `CAPABILITY_REQUEST_FULFILLED` only; `DECIDED`+approved is
explicitly a no-op (*"resume fires on the FULFILLED event"*). `mark_fulfilled()` exists
(`capability_request.py:522`) and emits the event, but **nothing calls it for `kind="continue"`**.

For a `continue` request there is no separate fulfiller — **the Captain's approval IS the
fulfilment.**

## What to build

Close those three links, in this order.

**Link 1 — carry the work item id to the continue site.**
`file_continue_request` must receive the promoted item's id and pass it to `file_request`.
The plumbing question you must solve: `run_with_promotion` (`cognitive/turn_promotion.py`)
creates the work item, and `resolve_exhausted_turn` runs inside the promoted turn. Find how the
id reaches the exhausted-turn path. **Report the route you chose and why.** If a turn was NOT
promoted (finished under the budget) there is no item — pass `None` and behave exactly as today.

**Link 2 — mark the item blocked when the request is filed.**
Only when there is a linked item, and only for the exhausted-turn path. Record the request id in
metadata the way AD-855 does (`blocked_reason` + `capability_request_id`, see
`capability_gap_driver.py:106`).

**Link 3 — approval of a `continue` fulfils it.**
On approving `kind="continue"`, call `mark_fulfilled()` so the existing driver resumes and
re-dispatches. Keep the existing standing-rule behaviour (`continue` is already in
`_STANDING_RULE_KINDS`) — this is additive.

## Constraints

- **Resume is Captain-gated and never automatic.** A turn may only re-enter on an explicit
  approval. Do not resume on a standing rule, a timer, or a retry.
- **Do not modify `WorkItemStatus`.** `BLOCKED` exists; use it.
- **Do not fork `capability_gap_driver`.** Reuse `on_capability_event` / `_resume` / `_cancel`.
  If they need to accept a continue-shaped request, extend them — do not copy them.
- **Denial must be honest.** A denied `continue` must not leave the item `blocked` forever.
  AD-855's `_cancel` already handles this; make sure it is reached.
- **A non-promoted turn is untouched.** Byte-identical behaviour when there is no work item.
- **Do not change `max_iterations`, `continue_or_ask_max_passes`, or any budget.** That is
  AD-1208 (#1154) and out of scope.
- **Do not fix BF-717** (#1156, telling the Captain in the chat). Separate issue, separate build.
- **str-replace end-anchor trap:** `file_request(...)` and `file_continue_request(...)` are runs
  of near-identical keyword arguments. Whatever appears at either END of `oldString` must reappear
  in `newString`. Verify neighbours survived.
- Do not stage `config/system.yaml` (skip-worktree) or this prompt.

## Tests

Minimum:

1. A promoted turn that exhausts its budget files a request **linked** to its work item.
2. That work item transitions to `blocked`, carrying the request id in metadata.
3. Approving the request marks it fulfilled, and the item returns to `in_progress`.
4. **The regression that matters:** the item is actually **re-dispatched** — assert the router was
   called. A status flip without a dispatch is the same dead end with a nicer label.
5. Denying cancels the item rather than stranding it `blocked`.
6. A turn that was NOT promoted behaves exactly as today (no item, no block, no crash).
7. Idempotency: a second FULFILLED for the same request does not re-dispatch twice.

## Gate

ONE full Python gate, **SYNCHRONOUS — do not background it and return.**

```powershell
$env:PROBOS_DATA_DIR="$env:TEMP\ad1204_$(Get-Random)"; $env:PROBOS_EMBEDDINGS='local'
& d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/ -q -n 16 --dist=loadfile --timeout=600 2>&1 | Tee-Object -FilePath d:\ProbOS\logs\ad1204-gate.log
```

**Pipe through `Tee-Object` and NOTHING after it** — a filter after the tee buffers the stream and
the harness backgrounds a healthy run.

**Baseline: 22,656 NODES** (22,622 passed + 34 skipped + 0 failed). Carry NODES, not passed;
skip counts drift between identical runs. Known flakes: BF-712 (`test_ad580_alert_feedback`,
10 ms margin) and BF-713 (`test_ad484` doctor, live LLM proxy). Any *other* failure is yours.

## Do not commit

Leave staged. Report:

1. How the work item id reaches `file_continue_request`, and why that route.
2. The diff at `continue_or_ask.py:491`.
3. Test 4 verbatim (the re-dispatch proof).
4. What a **denied** continue does to the item.
5. Gate numbers with reconciliation arithmetic.
6. Anything in this spec you disagreed with or found to be wrong.
