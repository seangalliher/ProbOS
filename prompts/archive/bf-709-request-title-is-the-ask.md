# BF-709: a capability request's title is the assembled prompt, not the ask

**Issue:** #1115 · **Repo:** OSS `d:\ProbOS`, branch `main` · **Follows:** AD-1201 (#1141)

---

## The defect

Seven capability requests are pending on the reference vessel right now. Every one
of them has a title like this:

```
counselor_co wants continue
'continue: --- Current Visual Context --- Camera not active or no frames
 described yet. Do NOT describe what you cannot see. --- E…'
```

That is the AD-1055 visual-context block and the BF-294 confabulation guard —
prompt scaffolding the runtime injected. It is not what the Captain asked for and
it is not what the agent is asking permission to do. AD-1201 just put these
requests in the Bridge where the Captain will actually see them, so the titles
now matter.

## The real shape of the bug — read this before editing

The obvious fix is wrong. `base_task_text` is **not** simply a display string; it
has two jobs, and they want opposite things:

| Job | Site | Wants |
|---|---|---|
| **Re-invocation** | `continue_or_ask.py:552` — `reinvoke(base_task_text + block)` | the FULL assembled prompt |
| **Display** | `continue_or_ask.py:452` — `_task_excerpt(base_task_text)` → card title | the Captain's RAW message |

Changing `base_task_text` at the call site (`cognitive_agent.py:3930`) to the raw
message would fix the title **and silently break continuation**, because the
re-invoked pass would lose working memory, episodic recall and session history.
That is a far worse bug than the one being fixed, and it would not show up in a
title assertion.

**So: `base_task_text` stays exactly as it is.** The fix is to stop conflating
the two jobs — thread a separate display text alongside it.

## The precedent — already in the file, 37 lines below

`cognitive_agent.py:3967` already does this correctly for the AD-1165 promotion
path:

```python
request_text=_promotion_request_text(observation, user_message),
```

`_promotion_request_text` (`cognitive_agent.py:428`) prefers
`params["captain_message"]` → `params["text"]` → `observation["captain_message"]`,
falling back to the assembled `user_message`. Its docstring says exactly why:
*"the board row should read as what was asked."*

The AD-1164 continue path (line 3930) and the AD-1165 promotion path (line 3967)
sit 37 lines apart in the same function. One reads as the ask; the other reads as
scaffolding. **This is the same drift shape as BF-701 / BF-706 / AD-1177** — a
helper exists and is correct, and a sibling path does not use it.

## What to build

**1. Thread a display text through, keep `base_task_text` intact.**

Add a keyword-only display parameter to `resolve_exhausted_turn` and
`file_continue_request` in `cognitive/continue_or_ask.py`. Default it so that
when it is absent or empty the behaviour is **byte-identical to today** — fall
back to `base_task_text`. An older caller must not change behaviour.

Use it at the two Captain-facing sites only:
- `file_continue_request` → `excerpt = _task_excerpt(<display>)` (line ~452)
- `file_fault_from_turn(attempted=...)` (line ~604) — also Captain-facing

Do **not** use it at line 552. `reinvoke` keeps the full assembled prompt.

**2. Pass the raw message from the arming site.**

At `cognitive_agent.py:3930`, pass `_promotion_request_text(observation, user_message)`
as the new display argument, leaving `base_task_text=user_message` unchanged. Both
paths then agree, and the helper has one more caller instead of a second copy.

**3. Do not add a second excerpt helper.** `_task_excerpt` already collapses
whitespace and bounds length with an ellipsis. Reuse it.

## Constraints

- **`base_task_text` at `cognitive_agent.py:3930` does not change.** If your diff
  modifies that line's value, you have introduced the worse bug. Re-read this
  spec.
- **Default-preserving.** Absent/empty display text ⇒ current behaviour exactly.
  Prove it with a test that omits the argument.
- **Do not reuse `_promotion_request_text` by importing it into
  `continue_or_ask.py`** — that would invert the dependency (`continue_or_ask` is
  imported lazily *by* `cognitive_agent`). Resolve the text at the arming site and
  pass it down.
- **Do not touch** the AD-1154 payload shape, `validate_action_payload`,
  `CONTINUE_REQUEST_KIND`, or the AD-1201 UI. This is a backend text fix.
- **Do not retitle the seven live pending requests** by migration. They are live
  test data on the reference vessel. New requests get the new shape.
- **str-replace end-anchor trap:** whatever appears at either END of `oldString`
  must reappear in `newString`. These are runs of near-identical keyword
  arguments. Read the whole call before editing and verify neighbours survived.

## Tests

Add to the existing `continue_or_ask` test module (find it; do not create a
parallel one).

Minimum:
1. Display text supplied ⇒ card `target` is the raw ask, **not** the scaffolding.
2. Display text omitted ⇒ `target` identical to today's assembled-prompt excerpt.
3. Display text empty/whitespace ⇒ falls back, does not produce `"continue: "`.
4. **The regression that matters:** `reinvoke` still receives the FULL assembled
   prompt when a display text is supplied. This is the test that would have caught
   the wrong fix.
5. Fault path: `attempted` carries the raw ask.
6. A `_promotion_request_text` case proving both paths now derive the same string
   from one observation.

## Gates

Full Python gate, run **SYNCHRONOUSLY — do not background it and return.** Pipe
through `Tee-Object -FilePath <log>`; **never `Select-Object`** (a buffering pipe
silences the stream and the harness backgrounds a healthy run — this has cost two
gates already).

```powershell
$env:PROBOS_DATA_DIR="$env:TEMP\bf709_$(Get-Random)"; $env:PROBOS_EMBEDDINGS='local'
& d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/ -q -n 16 --dist=loadfile --timeout=600 2>&1 | Tee-Object -FilePath d:\ProbOS\logs\bf709-gate.log
```

**Baseline: 22,548 NODES** (carry NODES, not passed). Report new total and the
arithmetic.

## Do not commit

Leave the work staged. Report back with:

1. The new parameter's name and default, and why the default preserves behaviour.
2. The diff at `cognitive_agent.py:3930` — showing `base_task_text` **unchanged**.
3. Test 4 verbatim (the `reinvoke` regression guard).
4. Gate numbers with reconciliation.
5. Anything you disagreed with or could not do as written.
