# AD-1278 / BF-780: the record that replaces the gate must outlive the process

**Issue:** #1243 (OPEN) · **Repo:** OSS `d:\ProbOS`, branch `main`
**AD:** AD-1278 — newly minted. Ceiling was **AD-1277**, enumerated from `git log --all --format='%s'`
(highest `AD-1277`, commit `be86e683`) and `prompts/ad-*.md` filenames (highest
`ad-1277-bf-825-a-run-someone-is-waiting-on.md`). GitHub issue titles in all states top out lower, at
`AD-1270`. **Not** taken from `open-ads-report.md` or `ad-ledger-snapshot.json`.
**BF:** BF-780 — already allocated on the issue. Do not mint a new one.
**Depends on:** nothing in flight. Touches `security/audit.py`, which no other open prompt edits.
**Status:** ready to build · **Estimated tests:** 22–28 across two slices
**Slices:** Slice A is independently shippable and **does not close #1243**. See "Slicing" below.

---

## Corrections to the issue text — read before anything else

The issue is accurate on all four gaps (each re-verified below). One framing claim in the surrounding
discussion is **wrong at HEAD**, and it changes what this build must do.

| Claim | Reality at HEAD `5d70da85` |
|---|---|
| "BF-763 ships with a docstring stating the record is **currently best-effort**, which keeps the claim honest until this lands." | **No such hedge exists.** `rg -n -i "best.effort\|may be lost\|not durable\|process exit" src/probos/tools/code_execution_tool.py` returns three hits, all about `RLIMIT` and a detached descendant — **none** about the audit record. |

What `_audit`'s docstring actually says (`code_execution_tool.py:558-561`) is the opposite:

> This record is what an unattended agent pays instead, so it is not decoration: it is **the control
> that makes the capability defensible** (Design Principle #13).

That is an unhedged claim of a *control* for a list that is in-memory by default, never drained at
shutdown, and unbounded. **The false claim is already in the tree** — this is not a claim we are about
to gain, it is one we already have. It is the BF-781 defect class verbatim.

A second one, same class, in the module this AD rewrites (`security/audit.py:1-6`):

> v1 in-memory only. […] **Persistence to SQLite deferred to AD-456d.**

AD-456d shipped. `AuditLogPersistence` is 130 lines below that sentence.

**Both wordings are corrected in the same commit as the behaviour they describe.** Not before — a
docstring that promises durability the code has not got yet is the same defect pointing the other way.

---

## The four gaps, verified at HEAD (2026-08-26)

None of the four is fixed. Each was checked by enumeration, not recall.

### Gap 1 — in-memory first

```
src/probos/security/audit.py:54:    entries: list[AuditEntry] = field(default_factory=list)
```

The hash chain is real (`_hash` at `:147`, `verify_chain` at `:120`) and it works. It verifies a list
living in the process.

### Gap 2 — persistence is default-off

```
src/probos/config.py:4344:    audit_persistence_enabled: bool = False
config/system.yaml:1271:  audit_persistence_enabled: false
```

The config comment above it (`config.py:4339-4343`) already contains this build's forcing function:

> AD-456d-4 will flip default to True once **AD-456d-1 (shutdown-flush hook)** lands.

AD-1278 **is** AD-456d-1 and AD-456d-4. Both halves land here or neither does.

### Gap 3 — no shutdown drain

Absence verified, not recalled:

```
CLAIM: nothing drains _pending_writes and nothing stops AuditLogPersistence at shutdown
RUN:   rg -n "audit" src/probos/startup/shutdown.py
FOUND: 552,553,554,555,556 — all EvictionAuditLog (cognitive/eviction_audit.py), a different class
RUN:   rg -n "audit_log_persistence" src/
FOUND: finalize.py:3770, 3772, 3798, 3809 — construction only. Zero hits in shutdown.py.
RUN:   rg -n "_pending_writes" src/
FOUND: security/audit.py:50, 63, 116, 117 — the definition and its own two writes. No consumer.
HOLDS: yes
```

`AuditLogPersistence.stop()` even documents its own orphaning (`audit.py:211-213`): *"NOT wired into
runtime shutdown in v1 […] Tests call directly."*

### Gap 4 — unbounded growth and task fan-out

`entries` has no cap. `append` (`:67`) schedules one `loop.create_task` per call (`:115-117`) with no
queue and no ceiling. The issue's measurements (10,000 rows ≈ 5.93 MB / 342 ms; 1,000 appends → 1,000
pending tasks under a blocked sink) are consistent with this code; do not re-derive them.

---

## Two classes named `AuditLog` — do not confuse them

This is the single most likely way to break this build.

| | AD-456 chain log | assistant log |
|---|---|---|
| Module | `src/probos/security/audit.py:39` | `src/probos/security/audit_log.py:25` |
| Shape | frozen `AuditEntry`, SHA-256 chain, in-memory list | SQLite table `assistant_audit_log` |
| Reached by | `runtime.audit_log` (`finalize.py:3764`) | `routers/security.py:55`, `knowledge/erasure.py` |
| Retention | **none today** | `security_infra.audit_retention_days` (`routers/security.py:50`) |

`CodeExecutionTool._audit` reads `getattr(self._runtime, "audit_log", None)`
(`code_execution_tool.py:578`) — that is the **AD-456 chain log**. Everything in this AD is about that
one. `SecurityInfraConfig.audit_retention_days` is **already consumed by the other class**; do not
overload it, and do not add eviction to `audit_log.py`.

---

## Decision 1 — durability posture: **durable-preferred with honest degradation**

Recorded here with its cost, per Design Principle 13(a).

### Why not durable-required

Durable-required (no sink, no launch) is the stronger reading of "audit is the control", and the issue
is right that it is the consistent one. It is rejected on three grounds:

1. **It would be a ceiling by inheritance, not a decision.** `audit_persistence_enabled` defaults to
   `False` today. Shipping durable-required without also flipping that default would take `run_python`
   away from **every existing deployment** on upgrade — a capability ceiling nobody chose, arriving as
   a side effect of a config default. That is precisely what DP 13(a) forbids.
2. **DP 13(b): prefer a governed path over a removed one.** Durable-required buys accountability by
   deleting the capability. The governed path — execute, label the run ungoverned, say so in the
   result — reaches the same accountability without the deletion.
3. **The failure mode is disproportionate.** A locked SQLite file, a full disk, or a wedged writer
   would stop the ship executing code. An audit sink that can halt work is a new way to lose work,
   which is the exact reasoning `_audit` already applies to swallowing sink exceptions
   (`code_execution_tool.py:568-570`). Making the sink fatal at launch contradicts it.

### What durable-preferred must therefore deliver

"Preferred" is only honest if the good path is the **default** and degradation is **visible**. Today
neither holds: persistence is off out of the box, and the degradation notice is a `logger.warning`
fired **once per tool instance** (`code_execution_tool.py:586-587`) into a log nobody reads. So:

- **(a) Flip the default.** `audit_persistence_enabled: bool = True` in `SecurityInfraConfig`, and
  `true` in `config/system.yaml:1271`. Out of the box the record is durable. Gap 2 closes by making the
  good path the default, not by making the bad path fatal.
- **(b) Label the run, not just the log.** When the entry did not reach a durable sink, the execution's
  own `ToolResult` output carries `audit: "in-memory-only"` (or `"absent"`), and the record's `detail`
  carries `durable: false`. The agent sees it in the turn; the Captain sees it in the record.
- **(c) Keep the once-per-instance warning** — it is right for log volume — but it is no longer the
  only channel.

### The cost, stated plainly

An operator who sets `audit_enabled: false`, or whose sink fails mid-run, **still gets code
execution**. There remains a configuration in which ProbOS runs Python with no durable accountability
trail. We accept that, and in exchange every such run is self-labelled as ungoverned in its own result
and in its own record, so the capability is never *silently* ungoverned. The residual risk is an
operator who reads neither. The alternative — a runtime that refuses to execute code because a SQLite
file is locked — costs more than it buys.

---

## Decision 2 — eviction, and truncation vs tampering

### The trap

`verify_chain()` (`audit.py:120-134`) starts its walk at `GENESIS_HASH` and fails on
`entry.prior_hash != prior`. **Evict `entries[0]` and it returns `False`.** A bounded log would report
itself as tampered on every boot, and `finalize.py:3791` would log "tamper or corruption suspected"
for a log that is merely full. Getting the cap without this is worse than not getting the cap.

### The mechanism: an anchored genesis (the truncation watermark)

Add one field:

```python
# The (sequence, entry_hash) of the last entry evicted from `entries`.
# None means the list still starts at genesis.
_truncated_at: tuple[int, str] | None = None
```

`verify_chain()` anchors its walk at `self._truncated_at[1]` when a watermark is present, and at
`GENESIS_HASH` when it is not. The watermark **is** the substitute genesis. Consequences:

| Log state | `verify_chain()` | `chain_state()` |
|---|---|---|
| full, intact | `True` | `("intact", 0, 0)` |
| head evicted, suffix intact | `True` | `("truncated", first_seq, evicted_count)` |
| any hash mismatch or discontinuity | `False` | `("broken", first_seq, evicted_count)` |

**Truncation is not tampering, so `verify_chain()` returns `True` for a correctly truncated chain.**
That is the whole point, and it is why the richer answer needs a second accessor rather than a changed
return type — see "Do not change the signature" below.

Three properties the watermark must have, all testable:

1. **Write-once-forward.** `_truncated_at` may be advanced only by the eviction path and only to a
   higher sequence. A watermark settable to an arbitrary value would let tampering masquerade as
   truncation — the anchor would simply move to wherever the break is. Enforce monotonicity in the
   setter and test the rejection.
2. **`chain_state()` never reports `"intact"` once a watermark exists.** A verifier must be able to
   tell a bounded log from a complete one. Silent truncation reported as `intact` is the same lie in a
   different direction.
3. **Captured before removal.** The watermark comes from the entry being dropped, read while it is
   still in the list.

### The eviction policy

**FIFO from the head, and only for entries the sink has confirmed.**

- FIFO because the chain is ordered: only head-eviction leaves a contiguous, verifiable suffix.
- **Durability-gated**: an entry may be evicted only once persistence has confirmed its row. If
  persistence is off, or the writer is behind, `entries` grows past the soft cap and logs pressure
  rather than destroying the only copy that exists. This is the coupling between Decisions 1 and 2 —
  under durable-preferred, a hard cap that evicted unpersisted entries would silently delete the
  accountability trail the AD exists to protect. The cap is a memory bound, never a data-destruction
  policy.
- New field `SecurityInfraConfig.audit_max_entries: int = 10_000` (≈6 MB by the issue's measurement).
  Note `ClinicalTelemetryConfig` already has a field of the same name (`config.py:~2034`) — different
  model, no collision, and the precedent is why this name.

### The boot interaction — do not skip this

`finalize.py:3790` does `runtime.audit_log.entries.extend(loaded)` against an **empty** list. If the DB
holds more rows than the cap, this rebuilds the unbounded list the cap exists to prevent, and then
`finalize.py:3791` calls `verify_chain()` on a load that legitimately does not start at genesis.

So `load_entries()` must gain a bound: load the newest `audit_max_entries` rows **in ascending
sequence order**, and return the watermark for the newest row **not** loaded so the caller can set it
before verifying. Wire it so `_truncated_at` is set **before** `verify_chain()` runs at
`finalize.py:3791`.

---

## Decision 3 — backpressure: one bounded queue, one writer

Replace per-append `create_task` (`audit.py:115-117`) with a single `asyncio.Queue(maxsize=...)` and
one long-lived writer task that batches commits.

- `append` stays **synchronous** and must never raise or block. It does `put_nowait`; on `QueueFull`
  it does **not** wait — it increments a dropped counter, marks the entry non-durable, and returns.
- The writer commits in batches. One `commit()` per batch, not per row.
- `_pending_writes` is retired as a mechanism. **The six assertions that read it in
  `tests/test_ad456d_audit_log_persistence.py` (`:58, :81, :193, :197, :202, :221`) must be
  UPDATED to the new synchronisation point, not deleted.** They are the only tests proving a row
  actually lands. Record inline why each changed.

---

## Decision 4 — the shutdown drain and its bound

**Bounded at 2.0 seconds, on its own config field. A drain that hangs shutdown is a worse defect than
the one it fixes.**

Verified budget:

```
src/probos/__main__.py:653:  await asyncio.wait_for(runtime.stop(reason=...), timeout=10)
src/probos/__main__.py:938:  await asyncio.wait_for(runtime.stop(), timeout=10)
```

The **entire** teardown shares 10 seconds. Two consequences the builder must not get wrong:

1. **Do not reuse `shutdown_drain_timeout_s`.** It defaults to `30.0`
   (`config/system.yaml:140`, `config.py:1070`) — already larger than the outer `wait_for`. Borrowing
   it would guarantee the audit drain is cancelled from outside rather than completing.
2. **New field `SecurityInfraConfig.audit_drain_timeout_s: float = 2.0.**

Behaviour on expiry — specify all three:

- Stop accepting new entries into the queue first (registration closed), so the drain has a fixed
  target rather than a moving one. `IntentBus.drain_pending_tasks` (`mesh/intent.py:321-347`) is the
  sibling pattern: close registration, deadline via `loop.time()`, `asyncio.wait(timeout=remaining)`,
  cancel the stragglers, never `gather` unbounded.
- On expiry: **cancel the writer, log at `ERROR`** naming the count of unflushed entries and the
  sequence range lost, then proceed to `stop()`. The tail loss becomes a stated fact, not a silence.
- On `asyncio.CancelledError` (the outer 10 s firing mid-drain): cancel the writer and **re-raise**.
  Cancellation belongs to the shutdown, not to this drain.

Insertion point: `src/probos/startup/shutdown.py`, in the store-teardown block alongside the other
`.stop()` calls (`:912` `clearance_grant_store`, `:917` `clinical_notes_store`, `:922`
`tool_permission_store`). Place it **after** the stores that may still append audit rows.

**Also fix, in the same commit:** `shutdown.py:251` says *"__main__.py enforces a 5s timeout on
stop()"*. It is 10 s (`__main__.py:653`, `:938`); the 5 s at `__main__.py:928` is `adapter.stop()`, a
different call. Same false-claim class as the two docstrings above, in the file this AD edits.

---

## Do not change the `verify_chain` signature

`verify_chain() -> bool` has exactly one production consumer and six test assertions:

```
src/probos/startup/finalize.py:3791
tests/test_ad456_security_infrastructure.py:203, 209, 222, 229
tests/test_ad456d_audit_log_persistence.py:347, 389
```

Keep it `-> bool`. Add `chain_state() -> tuple[str, int, int]` for the richer answer. Changing the
return type to AD-490's `tuple[bool, int | None]` shape would churn seven call sites for no gain and is
explicitly out of scope.

`AuditLog` is a `@dataclass`; every construction site is keyword-or-empty
(`finalize.py:3764`, plus 14 test sites), so appending fields is safe — but append them, do not
reorder, and keep defaults on all new fields.

---

## Slicing

**Slice A — the losses that need no policy (does NOT close #1243).**
Shutdown drain + bounded queue/writer + honest-degradation labelling + the three false-claim fixes
(`_audit` docstring, `audit.py` module docstring, `shutdown.py:251` comment). Closes gaps 3 and 4's
fan-out half. Ships alone, safely, with the default still `False`.

**Slice B — the policy half (closes #1243).**
`audit_max_entries` + FIFO durability-gated eviction + `_truncated_at` + anchored `verify_chain` +
`chain_state()` + bounded `load_entries` + the default flip to `True`.

The default flip belongs in Slice B, not A: flipping it before the drain and the cap exist would turn
persistence on for every deployment while the tail can still be lost and the list can still grow
without bound.

---

## Tests

Name the file `tests/test_ad1278_audit_durability.py`. Add to the existing BF-781 guard file where the
claim is a source claim.

### Slice A

1. `test_shutdown_drain_flushes_the_last_append` — append, then run the shutdown path; assert the
   **final** entry is present in SQLite. This is the acceptance criterion; it must cross the seam
   (append → drain → row on disk), not assert the drain was called.
2. `test_drain_is_bounded_when_the_sink_is_wedged` — sink that never returns; assert the drain returns
   within the budget and does not hang.
3. `test_wedged_drain_logs_the_loss_at_error` — assert the ERROR record names an unflushed count.
4. `test_drain_reraises_cancellation` — cancel mid-drain; assert `CancelledError` propagates and the
   writer is cancelled.
5. `test_queue_full_does_not_raise_from_append` — fill the queue; assert `append` returns an entry.
6. `test_n_appends_do_not_create_n_tasks` — the direct regression for gap 4's fan-out. Assert the task
   count stays at one writer across N appends. Pick N ≥ 100.
7. `test_append_remains_sync_with_no_running_loop` — the existing no-loop path (`audit.py:105-112`)
   must still be a no-op, not an error.
8. `test_result_labels_a_run_with_no_sink` — `ToolResult` output carries the ungoverned label.
9. `test_result_labels_a_run_whose_entry_was_dropped` — queue full → `durable: false`.
10. Source guards, in `tests/test_bf781_isolation_claims.py` style: `_audit`'s docstring no longer
    claims an unqualified control; `audit.py`'s module docstring no longer says persistence is
    deferred; `shutdown.py` no longer says 5 s. Each must assert the **corrected** wording is present,
    not merely that the old string is absent — an empty docstring would pass an absence-only check.

### Slice B

11. `test_entries_are_capped_at_audit_max_entries`.
12. `test_eviction_is_fifo_from_the_head`.
13. `test_unpersisted_entries_are_not_evicted` — persistence off; assert the list exceeds the cap
    rather than dropping the only copy.
14. `test_truncated_chain_verifies_as_intact` — **the central test.** Evict, then
    `verify_chain() is True`.
15. `test_truncated_chain_reports_truncated_not_intact` — `chain_state()[0] == "truncated"`.
16. `test_tampered_truncated_chain_reports_broken` — mutate an entry after truncation; assert
    `verify_chain() is False` and `chain_state()[0] == "broken"`. This is the pair that proves the two
    conditions are distinguishable; neither test alone does.
17. `test_watermark_is_monotonic` — a backwards write is rejected.
18. `test_watermark_only_moves_via_eviction`.
19. `test_load_entries_respects_the_cap`.
20. `test_boot_sets_the_watermark_before_verifying` — the ordering bug: assert a legitimately-capped
    rehydrate does **not** log tamper at `finalize.py:3791`.
21. `test_persistence_default_is_true` — `SecurityInfraConfig().audit_persistence_enabled is True`,
    and `config/system.yaml` agrees. Two assertions; the YAML has drifted from the model before.

### Gates

- Focused: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1278_audit_durability.py tests/test_ad456_security_infrastructure.py tests/test_ad456d_audit_log_persistence.py tests/test_ad1247_execution_audit.py tests/test_bf763_execution_claims.py tests/test_bf781_isolation_claims.py -q -p no:randomly`
- **Signature-change sweep before the broad gate.** `append`'s internals and `load_entries`'
  signature both move. Run `grep "getsource\|src\.index("` over `tests/` and execute every file that
  scans `security/audit.py`, `startup/shutdown.py`, or `tools/code_execution_tool.py`. Two 17-minute
  gates have been spent this month discovering one such guard each.
- Broad gate: full suite once, after the slice is frozen. A source or test edit after the gate
  invalidates it.
- Adversarial review on the staged diff before commit, with a different model than the author.

---

## What this does NOT change

- **No second audit path for execution.** `AuditLog` is shared — the browser tool (AD-706,
  `tools/browser/tool.py:1187`) and the self-improvement approval gate
  (`self_improvement/approval_gate.py:120,152`) write to it and gain equally from every fix here.
  Forking a private execution log is explicitly forbidden by the issue.
- **No consensus gate on `run_python`.** BF-763 settled that; this AD is the other half of that
  bargain, not a reversal of it.
- **No change to `AuditEntry`.** It is frozen and its six fields are the `_hash` payload — adding one
  invalidates every existing entry's hash and every persisted row.
- **No change to `security/audit_log.py`** (the assistant log) or to `audit_retention_days`.
- **No retention/TTL policy on the SQLite rows.** The cap here bounds memory only; disk retention is
  a separate question and stays open.
- **No `EventType.AUDIT_TAMPER_DETECTED` / Captain-alert path.** Still deferred (AD-456d-3).
- **No HXI surface** for the chain. Deferred (AD-456d-7).
- **No change to the mesh `CodeRunnerAgent` path**, which is not audited and says so (BF-787).

---

## Tracking

- `PROGRESS.md` — one CLOSED line per slice, with the durability decision named.
- `DECISIONS.md` — AD-1278: the durable-preferred decision, its cost, and the anchored-genesis
  mechanism. This is a governance posture, so it is recorded, not just built.
- `docs/development/roadmap.md` Bug Tracker — BF-780 row.
- `docs/development/config-reference.md` — three new fields plus the changed default.

---

## Acceptance criteria

1. The durability decision is **recorded with its cost** in `DECISIONS.md`, and the code's wording
   matches the decision.
2. Shutdown drains the writer, with a test proving the **last** append reaches disk.
3. The drain is bounded by `audit_drain_timeout_s`, never hangs, and reports what it lost.
4. `entries` is bounded, eviction is FIFO and durability-gated, and the policy is stated in the class
   docstring.
5. A truncated chain reports as **truncated, not tampered** — `verify_chain() is True`,
   `chain_state()[0] == "truncated"` — and a tampered one still reports broken.
6. N appends produce one writer task, not N tasks.
7. An execution that ran without reaching the sink is visible as such **in its own result**, not only
   in a log line.
8. `audit_persistence_enabled` defaults to `True` in both the model and `config/system.yaml`.
9. The three false claims (`_audit` docstring, `audit.py` module docstring, `shutdown.py:251`) are
   corrected **in the same commit** as the behaviour, with guard tests asserting the corrected wording.
10. No second audit path exists for execution.
11. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-08-26, HEAD `5d70da85`)

```
rg -n "    entries: list|    GENESIS_HASH|    def append|    def verify_chain" src/probos/security/audit.py
  54:    entries: list[AuditEntry] = field(default_factory=list)
  65:    GENESIS_HASH: str = "0" * 64
  67:    def append(self, *, category: str, detail: str) -> AuditEntry:
  120:    def verify_chain(self) -> bool:

rg -n "_pending_writes" src/
  security/audit.py:50, 63, 116, 117          # definition + its own two writes; no consumer

rg -n "audit_log_persistence" src/
  startup/finalize.py:3770, 3772, 3798, 3809  # construction only; zero hits in shutdown.py

rg -n "audit_persistence_enabled|audit_retention_days" src/probos/config.py
  4344:    audit_persistence_enabled: bool = False
  4346:    audit_retention_days: int = 90

rg -n "audit_persistence_enabled" config/system.yaml
  1271:  audit_persistence_enabled: false

rg -n "audit_retention_days" src/
  config.py:4346
  routers/security.py:50   # consumed by the OTHER AuditLog (security/audit_log.py)

rg -n "^class AuditLog" src/probos/security/audit.py src/probos/security/audit_log.py
  audit_log.py:25:class AuditLog:      # assistant log, SQLite
  audit.py:39:class AuditLog:          # AD-456 chain log  <-- this AD

rg -n "runtime.audit_log = " src/
  startup/finalize.py:3764:        runtime.audit_log = AuditLog(emit_event=runtime.emit_event)

rg -n "audit_log" src/probos/tools/code_execution_tool.py
  578:        audit = getattr(self._runtime, "audit_log", None)

rg -n "wait_for\(.*stop" src/probos/__main__.py
  653:            await asyncio.wait_for(runtime.stop(reason=...), timeout=10)
  938:            await asyncio.wait_for(runtime.stop(), timeout=10)

rg -n "shutdown_drain_timeout_s" config/system.yaml src/probos/config.py
  config/system.yaml:140:  shutdown_drain_timeout_s: 30.0
  config.py:1070:    shutdown_drain_timeout_s: float = Field(

rg -n "async def drain_pending_tasks" src/probos/mesh/intent.py
  321:    async def drain_pending_tasks(self, timeout_seconds: float = 5.0) -> None:

rg -n "\.verify_chain\(\)" src/ tests/     # AD-456 consumers only
  src/probos/startup/finalize.py:3791
  tests/test_ad456_security_infrastructure.py:203, 209, 222, 229
  tests/test_ad456d_audit_log_persistence.py:347, 389

rg -n "_pending_writes" tests/test_ad456d_audit_log_persistence.py
  58, 81, 193, 197, 202, 221                  # six assertions to UPDATE, not delete
```

### Absence Verified (2026-08-26)

```
CLAIM: nothing drains _pending_writes or stops AuditLogPersistence at shutdown
RUN:   rg -n "audit" src/probos/startup/shutdown.py ; rg -n "audit_log_persistence" src/
FOUND: only EvictionAuditLog (a different class) in shutdown.py; persistence appears only in finalize
HOLDS: yes

CLAIM: no docstring in code_execution_tool.py hedges the audit record as best-effort
RUN:   rg -n -i "best.effort|may be lost|not durable|process exit|survive" src/probos/tools/code_execution_tool.py
FOUND: 12 (RLIMIT), 397 (RLIMIT), 993 (detached descendant) — none about the audit record
HOLDS: yes — the issue's framing claim is stale; the unhedged control claim is live at :558-561
```
