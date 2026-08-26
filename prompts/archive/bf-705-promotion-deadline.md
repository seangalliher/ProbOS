# BF-705: the promotion budget and the chat TTL are measured from different origins

**Repo:** OSS (`d:\ProbOS`), branch `main`, HEAD `fc64394f`
**Type:** BF. Code + tests ONLY — no `PROGRESS.md` / `DECISIONS.md` / roadmap edits.
**This prompt stays UNTRACKED** (matches BF-690/693/694/706). Do not `git add` it.
**Issue:** #1108

---

## Problem

AD-1165 promotes a long conversational turn to a background work item so the chat TTL cannot
kill it. The budget and the TTL start from **different clocks**, and nothing relates them.

- The TTL clock starts at dispatch: `ttl_seconds=60.0` (`routers/agents.py:3097`), enforced by
  `IntentBus` as `asyncio.wait_for(handler(intent), timeout=intent.ttl_seconds)`
  (`mesh/intent.py:769`, and identically on the NATS branch at `:783` — there is **no**
  path-dependent deadline).
- The promotion clock starts when `run_with_promotion` is reached, ~1,600 lines deep in the
  handler (`cognitive_agent.py:3833`).

Everything between is unbudgeted: perceive, sensorium assembly, episodic recall, browser session
binding, and contention with background cognition. The invariant that actually governs is:

```
preamble + promote_to_task_after_seconds < ttl_seconds
```

Nothing checks it.

### Evidence (log lines 60473 / 60478, five apart — same turn)

| time | event |
|---|---|
| 21:39:00 | DM dispatched, 60s TTL starts |
| 21:39:29 | agentic turn starts — **~29s preamble**, concurrent with a dream cycle scoring 2,547 notebook entries and routing 16 agents |
| 21:40:00 | TTL expires → the Captain sees `(error: Agent did not respond in time.)` |
| 21:40:04 | acknowledgement arrives, **4s too late** |

The work completed correctly and reported into the thread afterwards. Only the acknowledgement
was late. 7 of 8 promotions that day had no timeout near them — the preamble is variable, so
this fails intermittently under load.

### Two things that made this hard to see (do not repeat them)

1. **A superseded diagnosis.** This was first blamed on a 30s NATS request timeout. That was
   wrong: `NatsConfig` has no `request_timeout_seconds` (the field is on `MCPConfig`), and both
   transport branches use `intent.ttl_seconds`.
2. **The log line reports the configured value, not measured elapsed.**
   `"promoted ... after %.1fs"` prints `promote_after_seconds`, so every line read `35.0`
   because the config said 35.0. **It is not timing evidence.** Fixing this is part of the BF.

---

## Decision

Propagate the intent deadline into the promotion decision, and make the log line report a real
measurement.

### 1. Carry the deadline on the observation

`IntentMessage` already has both fields (`types.py:65,67`):

```python
ttl_seconds: float = 60.0
created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

`perceive()` copies neither. Add them in **BOTH** branches of `perceive`
(`cognitive_agent.py:2159`):

- The `isinstance(intent, IntentMessage)` branch — add unconditionally.
- **The dict fallback — follow the BF-698 pattern exactly.** Add each key ONLY when the source
  dict carries it (`if "ttl_seconds" in _as_dict:`). Roughly fifteen agents reach that branch via
  `self.perceive(intent.__dict__)`; a hand-built dict has neither key and must stay untouched.
  Read the BF-698 comment already in that branch before editing — it explains the contract.

### 2. A pure deadline helper

Add a module-level pure function alongside `_coerce_promotion_budget` (`:306`). Mirror its
defensiveness: every synthetic-runtime test builds the observation as a plain dict or a
MagicMock, so an exact `type` check is the boundary (a MagicMock attribute compares as another
MagicMock, not a bool — see that function's docstring).

Signature shape:

```python
def _effective_promotion_budget(
    configured: float, observation: dict, *, now: datetime | None = None
) -> float:
```

Rules, all of which need a test:

- Missing / malformed `ttl_seconds` or `created_at` → return `configured` unchanged. **This is
  the byte-identical degrade path** and covers every non-DM caller and older producers.
- `remaining = ttl_seconds - (now - created_at).total_seconds()`
- `budget = min(configured, remaining - _PROMOTION_MARGIN_SECONDS)`
- **Clamp to a positive floor.** `run_with_promotion` treats `promote_after_seconds <= 0.0` as
  *"do not promote, await inline"* — the exact opposite of what a blown deadline needs. Never
  return `<= 0`; clamp to `_MIN_PROMOTION_BUDGET_SECONDS`. Assert this in a test with a
  deliberately expired deadline.
- Never return more than `configured`. Shrinking only.

Two module constants with justifying comments: `_PROMOTION_MARGIN_SECONDS` (headroom for the
work-item write, the reporter spawn and the reply's trip back — start at `5.0`) and
`_MIN_PROMOTION_BUDGET_SECONDS` (`1.0`).

`created_at` is wall-clock and so is `now`; note in the docstring that a clock adjustment mid-turn
can skew this, and that the degrade is a shorter budget, which is the safe direction.

### 3. Use it at the call site

At `cognitive_agent.py:3822`, after `_coerce_promotion_budget`, pass the result through
`_effective_promotion_budget(promote_after, observation)`. The `promote_after <= 0.0` early-out
(inline await, no import) must keep working exactly as it does now.

### 4. Report measured elapsed

In `turn_promotion.py::run_with_promotion`, measure with `time.monotonic()` around the
`asyncio.wait` and log the **actual** elapsed alongside the budget. Both numbers: the budget
explains the decision, the measurement is the evidence. Keep the existing message's other fields.

---

## Target files

| File | Change |
|---|---|
| `src/probos/cognitive/cognitive_agent.py` | Both `perceive` branches; `_effective_promotion_budget` + 2 constants; call site at `:3822`. |
| `src/probos/cognitive/turn_promotion.py` | Measured elapsed in the promotion log line. |
| `tests/test_bf705_promotion_deadline.py` | NEW. |

---

## Acceptance criteria

1. **Byte-identical degrade** — observation with no deadline keys returns `configured` exactly.
   Test the absent case, the `None` case, a string, and a MagicMock attribute.
2. **A slow preamble shrinks the budget.** `created_at` 29s ago, `ttl_seconds=60`,
   `configured=20` → budget is `min(20, 60-29-5) = 20`… choose numbers that actually exercise
   the shrink (e.g. `configured=35` → `26`). Assert the arithmetic, not just "smaller".
3. **An ample deadline leaves the budget untouched** — fresh `created_at` → `configured`.
4. **An expired deadline clamps to the positive floor**, never `<= 0`. This is the test that
   proves promotion is not silently disabled at the moment it is most needed.
5. **Never exceeds `configured`** — huge TTL still returns `configured`.
6. **`perceive` carries the fields** — one test for the `IntentMessage` branch, one for the dict
   fallback WITH the keys, and one for a hand-built dict WITHOUT them (asserting the keys stay
   absent, per BF-698).
7. **The log line reports measured elapsed** — drive a promoted turn with a stubbed slow work
   callable and assert the logged elapsed reflects real time, not the configured budget. Use
   `caplog` and `record.getMessage()` (`record.message % record.args` raises here).
8. **End-to-end**: a turn whose preamble consumed most of the TTL still returns its
   acknowledgement before the deadline.

Expected: **14–18 new tests.**

### Gates

```powershell
$env:PROBOS_DATA_DIR="$env:TEMP\bf705_$(Get-Random)"; $env:PROBOS_EMBEDDINGS='local'
& d:/ProbOS/.venv/Scripts/python.exe -m pytest `
  tests/test_bf705_promotion_deadline.py `
  tests/test_ad1165_turn_promotion.py `
  tests/test_bf704_promoted_stop_reason.py `
  tests/test_bf698_thread_provenance.py `
  tests/test_cognitive_journal.py `
  tests/test_ad1164_continue_or_ask.py `
  -q -n 0
```

`test_cognitive_journal.py::TestPerceiveIntentId` pins the AD-432 contract that the dict fallback
does not invent keys it was not given — it is the guard for requirement 6 and must stay green.

Then ONE full gate. **Baseline is 22,467 NODES** (AD-1180's gate: 22,466 passed + 1 environmental
failure). Reconcile `22,467 + <new tests> == passed + failed` and show the arithmetic. Expect ~1
rotating environmental flake (`test_auto_commit_after_debounce`, `test_doctor_returns_zero_on_clean_setup`);
re-run any failure `-n 0` before reporting it as real.

---

## Do NOT build

- **Do not** add a config field. The margin and floor are module constants; a knob here is a
  second thing to leave misconfigured, which is the bug.
- **Do not** change `promote_to_task_after_seconds`, `ttl_seconds`, or any config default.
- **Do not** add a parse-time validator relating the two. AD-1151: `POST /config` does a
  dump/revalidate round trip that would materialise a bad value into `system.yaml` and brick the
  boot. Resolve time only.
- **Do not** touch `IntentBus`, the NATS path, or `mesh/intent.py`.
- **Do not** change `run_with_promotion`'s promotion semantics — only its logging.
- **Do not** edit `PROGRESS.md`, `DECISIONS.md`, or the roadmap.
- **Do not** stage `config/system.yaml` (skip-worktree) or this prompt.

## Notes

- Stage your files before the full gate — `test_ad1123_bounded_federation_relay.py` inspects
  *unstaged* `git diff --name-only`.
- The str-replace end-anchor trap: whatever appears at either END of `oldString` must reappear in
  `newString`. This deleted a YAML section header earlier today. `perceive` has two adjacent
  dict literals — read both fully before editing either.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
