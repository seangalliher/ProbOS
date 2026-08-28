# AD-1278 / BF-780: the record that replaces the gate must outlive the process

**Issue:** #1243 (OPEN) · **Repo:** OSS `d:\ProbOS`, branch `main`
**AD:** AD-1278 — **already allocated to this issue; do NOT mint a new number.** See "Numbering" below.
**BF:** BF-780 — already allocated on the issue. Do not mint a new one.
**Depends on:** nothing in flight.
**Status:** ready to build · **Estimated tests:** 40–46 (28 already staged: keep 24, change 4, add 12–18)
**Revision:** 3 (2026-08-28).

> **Revision 3 exists because revision 2 was BUILT and REJECTED by adversarial review.** The build is
> **staged and uncommitted**. Two Criticals, one High, one Low — and one review round found the *same
> invariant broken in two places*, which is the signature of a wrong shape rather than an unfixed bug.
>
> Revision 3 does **not** start over. Most of revision 2 was confirmed sound and is preserved verbatim
> below. It replaces exactly three things — the **durability model**, the **labelling model**, and the
> **drain placement** — plus one stale comment. Those are **Decisions A–D**, which **supersede** the
> correspondingly-marked parts of Decisions 1–4. Where a revision-2 section is not marked superseded,
> build it as written.
>
> **Anchors are verified against the STAGED TREE, not HEAD.** `git rev-parse --short HEAD` =
> `5c3f0028`, and `git diff --stat` over the AD-1278 source files is **empty**, so worktree == index
> and the line numbers cited below are the ones the reviewer read.

---

## Numbering — why this is not AD-1283

Enumerated at HEAD `7edf309e`, per the hard rule. Not taken from `open-ads-report.md` or
`ad-ledger-snapshot.json`.

| Source | Highest AD |
|---|---|
| `git log --all --format='%s'` subjects | **1282** (`7edf309e`, AD-1282 / BF-782) |
| `prompts/ad-*.md` filenames | **1282** |
| GitHub issue titles, **all** states (1330 scanned) | 1276 |

**Ceiling = AD-1282. Next free = AD-1283.** It stays free.

AD-1278 is already allocated to **this issue** (#1243 / BF-780) and is **unbuilt**: `27f76ea9` is a
prompt-only commit, and `grep "AD-1278" src/probos/security/audit.py src/probos/startup/shutdown.py`
returns nothing. Minting AD-1283 for the same issue would leave AD-1278 permanently dangling in the
ledger — allocated, prompted, never built, never explained. The "never reuse" rule forbids giving one
number to two *different* changes; this is the *same* change, revised **twice**. **Keep AD-1278.**

---

## What revision 2 got wrong — the root cause, confirmed and amended

### One scalar standing in for a set that can have holes

The reading that *"the design PREDICTS durability instead of CONFIRMING it"* is **confirmed**, with one
amendment that materially changes the fix.

Both Criticals are the same defect wearing two faces, and the difference between the faces matters:

* **Critical 2 is a forward prediction.** `next_append_is_durable()` (`security/audit.py:156`) answers
  from pre-append conditions — sink present, writer open, queue not full — and the caller writes that
  answer down as though it were an outcome. A forecast, recorded as a fact.
* **Critical 1 is a backward over-generalisation.** `mark_persisted_through(max(confirmed))`
  (`security/audit.py:425`) takes a **point** observation — *this batch committed* — and infers a
  **range** property — *everything at or below this sequence is on disk*. That inference is valid only
  if the confirmed stream has no holes, and nothing anywhere enforces that.

**The amendment — and it is the part that decides the fix: the same holes corrupt the on-disk chain,
not merely the watermark.** `AuditEntry.prior_hash` chains each row to its predecessor. A sequence
that never reaches SQLite leaves the *next* persisted row's `prior_hash` pointing at a row that is not
there, so the rehydrated chain is **`broken`** — permanently, at every future boot. The reproduction
is the proof, and its second line is the one that matters:

```
db_sequences  [0, 3]          <- sequences 1 and 2 never reached the sink
mem_sequences [2, 3]          <- eviction took 0 and 1
dropped       2
in-memory   verify True   state ('truncated', 2, 2)
rehydrated  verify False  state ('broken',    0, 0)      <- the durable artefact is poisoned
```

So any fix that only teaches the **watermark** to be careful leaves a durable chain that one transient
queue-full ruins forever. **Revision 3 therefore closes the holes at source rather than accounting for
them downstream.** Everything in Decision A follows from that.

### The four findings, each re-verified in the staged tree

| # | Finding | Anchor (staged) | Fixed by |
|---|---|---|---|
| **C1** | Eviction deletes entries the sink never took | `security/audit.py:425`; `:427-454` (gate at `:436`) | **Decision A** |
| **C2** | A run is labelled `durable` before any confirmation | `execution/audit.py:182-183`, written `:188`, returned `:232`; writer-side swallow at `security/audit.py:411-422` | **Decision B** |
| **H3** | The drain runs ~138 lines too early, and closes registration | `shutdown.py:984` vs pools at `:1122`; `security/audit.py:283` | **Decision C** |
| **L4** | Stale comment claims `len(self.entries)`-based sequencing | `security/audit.py:466` | **Decision D** |

### Confirmed SOUND by review — do not redesign these

Re-opening any of these is scope creep; each was examined and passed.

1. `drain()` is genuinely bounded and correctly uses `asyncio.wait`, **not** `asyncio.wait_for`
   (`security/audit.py:294-306`). The trap revision 2 documented was avoided.
2. A **tampered** truncated chain still reports `broken`, not `truncated`
   (`chain_state`, `security/audit.py:200-215`).
3. Startup degrades safely when the sink fails (`finalize.py:3914-3950`).
4. Both execution paths **do** surface a label when the auditor returns non-durable
   (`code_runner.py:301-302`, `code_execution_tool.py:770-771`). The suppress-the-healthy-path shape is
   right; only the suppressed **value** changes.
5. `mark_truncated` is forward-only and raises rather than degrading (`security/audit.py:217-232`).
6. `verify_chain() -> bool` keeps its signature; `chain_state()` carries the richer answer.

---

## Decision A — durability model: **close the holes; never infer a range**

> **Supersedes Decision 2's eviction bullet and Decision 3's `QueueFull` bullet.**

### The three candidates, and what each costs

| | **(i) per-sequence set** | **(ii) contiguous-from-head only** | **(iii) never evict unconfirmed** |
|---|---|---|---|
| **Queue overflow** | Correct, but the set must be seeded from the DB at boot or rehydrated rows can never be evicted — so its memory is proportional to the **database**, not the log. Unbounded by design. | The watermark stalls at the hole **forever** (dropped entries are never retried), so eviction is permanently disabled for the process lifetime. Safe; one hiccup ends the memory bound. | Same stall. Already built (`:437-453`) and correct **as far as it goes**. |
| **Restart** | Set is empty; needs a full sequence scan to rebuild. | Correct — a contiguous prefix rehydrates cleanly. | Correct. |
| **Persistence disabled** | Set stays empty; nothing is ever evictable. | Watermark stays `-1`; same. | Same — **the memory bound is silently defeated in the most common configuration.** |
| **On-disk chain** | **Still poisoned.** | **Still poisoned.** | **Still poisoned.** |

The last row decides it. **None of the three fixes the chain**, because all three are downstream
bookkeeping about a stream that already has a hole in it. Choosing among them alone would have
produced a fourth review round on the same invariant.

### The decision — four parts, all required

#### A1 — Queue overflow must not drop; it spills

`_schedule_persist` (`security/audit.py:349-386`) increments `_dropped` and returns on `QueueFull`
(`:372`). Replace that with an overflow `collections.deque` the writer drains **ahead of** the queue,
preserving FIFO.

The cost is near zero, and that is why this is the right answer rather than merely a nicer one: **the
spill holds references to `AuditEntry` objects `entries` is already retaining**, because an unconfirmed
entry is not evictable. Roughly a pointer per entry. Memory stays bounded by the same thing that
already bounds `entries`, and the existing cap-pressure warning (`:440-452`) is already the reporting
surface. Recovery is automatic once the sink catches up.

Keep `_dropped` and `_queue_full_warned` but repurpose them to count and report **spill**, and reword
both — they no longer describe a loss.

#### A2 — A failed batch is retried, never skipped

`_writer_loop` (`security/audit.py:396-425`) swallows a failed commit (`:411-422`) and proceeds to the
next batch. `persist_entries` is all-or-nothing (`return []` on failure), so the *next* successful
batch confirms a higher range and `max(confirmed)` steps straight over the failed one. **This is a
second, independent hole source with identical consequences to A1**, and it survives even a perfect
queue.

Return the failed batch to the head of the spill and retry with bounded backoff. After
`audit_write_max_retries` consecutive failures on the same batch, **terminate the durable stream**:

* set `_stream_broken_at = batch[0].sequence`;
* stop enqueueing anything further — no more rows are written, so the on-disk chain **never gains a
  hole**, it simply ends, which rehydrates cleanly;
* log once at `ERROR` naming the sequence and the cause;
* `durable_stream_open()` returns `False` from that moment, so every later run self-labels (Decision B).

New field: `SecurityInfraConfig.audit_write_max_retries: int = 3`, alongside the others at
`config.py:4362-4371`.

Terminating rather than limping is deliberate, and the comment must say so: a durable chain with a
hole is worth **less** than one that stops — the first lies about its own integrity at every future
boot; the second says plainly where it ended.

#### A3 — Contiguity is an enforced precondition, not an argument

With A1 and A2 confirmations *are* contiguous by construction — spill and queue are FIFO, batches are
contiguous runs drawn from them, nothing is skipped, and the stream terminates rather than jumping.
`max(confirmed)` would now be correct.

**Do not rely on that.** Make `mark_persisted_through` (`security/audit.py:234-242`) reject a
non-contiguous advance outright — return without moving, and log at `ERROR`:

```python
seq = int(sequence)
if seq <= self._persisted_through:
    return
if self._persisted_through >= 0 and seq != self._persisted_through + 1:
    # A jump means the confirmed stream has a hole, and one integer cannot
    # represent one. Refusing keeps eviction honest; accepting it is how the
    # only copy of an unpersisted entry gets deleted.
    logger.error(...)
    return
```

and change the writer's call at `:425` to advance **one sequence at a time over the sorted confirmed
run, stopping at the first gap**. The first advance from `-1` seeds against `entries[0].sequence` /
`_truncated_at`, so a bounded rehydrate is not mistaken for a hole — `finalize.py:3937`
(`mark_persisted_through(loaded[-1].sequence)`) must keep working, and there is a test for it at
`tests/test_ad1278_audit_durability.py:602`.

**A3 is not optional even though A1 and A2 make it theoretically unreachable.** "Unreachable by
construction" is exactly what the 17-mutant matrix already believed. One comparison converts a design
argument into a runtime invariant, and it is the check that would have caught this defect.

#### A4 — Split the cap policy by whether durability was ever promised

The built policy (`_enforce_cap`, `:427-454`) refuses to evict anything unconfirmed and warns. Right
when a sink exists and is behind; **wrong when persistence is switched off** — and that is the source
of the "memory bound defeated in the common configuration" cost above. With `_persistence is None`,
`_persisted_through` stays `-1` forever, nothing is evictable, and `audit_max_entries` is decorative.

| Condition | Policy | Why |
|---|---|---|
| `self._persistence is None` — persistence off **by configuration** | Evict FIFO normally, advancing `_truncated_at`. | Nobody was promised a durable copy. The log is a ring buffer **by the operator's choice**, and the truncation watermark keeps it verifiable. There is no "only copy on disk" to protect. |
| Persistence attached, writer behind or stream broken | Do not evict above the watermark; warn once. **Existing `:440-452` branch, unchanged.** | An entry the operator was told would be durable, and which is not yet durable, is the one thing eviction must never touch. |

Keep the existing warning text for the second row — it is good and it already names both remedies.

### The cost of Decision A, stated plainly

* A sink that fails `audit_write_max_retries` times consecutively **permanently ends** durable
  recording for that process. Every later run is labelled `in-memory-only`, the ERROR names the
  sequence, and recovery needs a restart. Accepted: the alternative is a durable artefact that reports
  itself `broken` forever, which is worse than one that ends cleanly.
* With persistence attached but behind, `entries` may exceed `audit_max_entries`. Bounded by the sink
  catching up; reported by the cap-pressure warning. Unchanged from revision 2 and correct.
* One deque, and roughly a pointer per in-flight entry.

---

## Decision B — labelling model: **never claim disk from a synchronous call**

> **Supersedes Decision 1(b).** The posture (durable-**preferred**) is unchanged; what "preferred"
> obliges is corrected.

### The constraint, stated first

`ExecutionAuditor.record` is **synchronous** and returns before the writer has touched SQLite.
Confirmation is inherently later. Three resolutions exist; two are wrong.

* **Wait for confirmation.** Blocks every execution on a commit, couples run latency to disk, and
  contradicts a decision already reasoned out and shipped at `execution/audit.py:131` — *"an audit
  write that could fail an execution would turn the accountability trail into a new way to lose
  work."* **Rejected.**
* **Amend the label later.** The `ToolResult` / `IntentResult` has already been returned; there is
  nowhere to put the amendment. **Rejected as a mechanism** — though note the chain *is* the
  amendment: `AUDIT_PERSISTED` and `chain_state()` tell a reader what actually landed.
* **Report what is actually known.** Adopted.

### The decision

**`record()` reports stream admission, which it can observe, and never durability, which it cannot.**

| Label | Meaning | Surfaced to the Captain? |
|---|---|---|
| `"queued"` | Accepted into an open durable stream. Disk confirmation not yet observed. | **No** — suppressed; this is the healthy path. |
| `"in-memory-only"` | No durable stream: persistence off, stream broken (A2), or writer closed. This record dies at process exit. | Yes |
| `"absent"` | No audit sink at all (`audit_enabled: false`). | Yes |
| `"unconfirmed"` | The `append` itself raised; the sink may or may not hold it. | Yes |

**`"durable"` is removed from the vocabulary entirely.** Nothing synchronous can honestly return it.

Four mechanical consequences, all required:

1. **Rename the predicate.** `next_append_is_durable()` → `durable_stream_open()`
   (`security/audit.py:156`). The old name cannot be read any way except *"this will be on disk"*,
   which is the false claim. Its docstring (`:157-164`) currently says the answer is *"synchronous and
   exact… without the answer changing underneath it"* — **that sentence is Critical 2 written in prose
   and must go.** Replace with: exact about **admission**, silent about **commitment**, and the caller
   must not label a run durable on the strength of it. Add `_stream_broken_at is None` to its
   conditions (A2).
2. **Change the returned label** at `execution/audit.py:232` to
   `return "queued" if stream_open else "in-memory-only"`, renaming the local at `:182-183` from
   `durable` to `stream_open`.
3. **Change the field written into the record.** `detail["durable"]` (`:188`) becomes
   `detail["stream"] = "queued" | "memory-only"` — the same fact the caller gets, not a stronger one.
   Swap `"durable"` → `"stream"` in `AUDIT_DETAIL_ALLOWLIST` (`execution/audit.py:52-70`) and rewrite
   the comment above it, which claims the field records *"whether THIS record reached a durable
   sink"* — it does not and cannot know that. A record cannot attest its own durability; the presence
   of its row in SQLite is the evidence, and that lives in the DB.
4. **Change the suppression comparison on BOTH paths.** `code_runner.py:301` and
   `code_execution_tool.py:770` both read `if audit_outcome and audit_outcome != "durable"`. Both
   become `!= "queued"`. **Miss one and that path emits a label on every healthy run** — noise that
   trains the Captain to ignore the field, which fails exactly as completely as never labelling.
   Revision 1 already shipped a one-path change once; treat this pair as one atomic edit.

### What the Captain actually sees

Nothing, on a healthy run — that is the point. The moment the stream is unavailable or breaks, every
subsequent run carries `audit: "in-memory-only"` in its own result, and the transition is visible
because the field appears where it previously did not.

A run that was `"queued"` and then died in a finally-abandoned batch is **not** retroactively
corrected. What covers it is that the stream terminates (A2) and the ERROR names its sequence. That is
the residual cost of not waiting, and it is the right trade: a per-run disk wait would tax every
execution to sharpen one label.

---

## Decision C — drain placement: **two phases, and only the second closes registration**

> **Supersedes Decision 4's insertion point.** Its bound, its `asyncio.wait` shape, and its
> cancellation semantics are unchanged and confirmed sound.

### The constraint the review raised

`drain()` sets `_writer_closed = True` (`security/audit.py:283`), and `_schedule_persist` then
short-circuits (`:351-357`). **Whatever runs after the drain can only append in memory.** Today the
drain is at `shutdown.py:984` and all of this still runs afterwards:

```
shutdown.py:1073   pool_scaler.stop()
shutdown.py:1122   _stop_pools_and_drain_intent_bus(...)     <- pools + intent bus
shutdown.py:1126   knowledge store persistence
shutdown.py:1151   gossip / signal / hebbian / trust .stop()
shutdown.py:1208   _semantic_layer.stop()
```

Every one can produce an audit-worthy event, and that window is the **most** failure-prone stretch of
the run — which is where a durability control is least allowed to be absent.

### The decision

Split the single call into two phases. This is not a compromise between the two options; each phase
does a different job and both are needed.

**Phase 1 — bounded flush, registration stays OPEN.** At the existing `shutdown.py:984` site, replace
`_drain_audit_log(runtime)` with `_flush_audit_log(runtime)`: a **bounded** `flush()` that does **not**
touch `_writer_closed` and does **not** stop the persistence handle. It gets the bulk of the trail onto
disk while the system is fully alive, so phase 2 spends its budget on a small tail. On expiry it logs
and proceeds — phase 2 tries again.

> **`flush()` is currently unbounded.** `security/audit.py:256-267` ends in a bare `await queue.join()`
> with no timeout. Inside a 10-second whole-teardown budget (`__main__.py:653`, `:938`) that is a hang
> waiting to happen. Bound it with the same `asyncio.wait({joiner}, timeout=...)` shape `drain()`
> already uses correctly. **Do not use `asyncio.wait_for`** — for the reason Decision 4 documents and
> the build got right.

**Phase 2 — authoritative drain, registration closes.** Insert **after** `shutdown.py:1208`
(`_semantic_layer.stop()`) and **before** `shutdown.py:1211` (`runtime._started = False`). That is the
last point at which anything can append. Phase 2 is the existing `_drain_audit_log` unchanged in
behaviour: `drain()`, then `persistence.stop()`, then `runtime.audit_log_persistence = None`.

The placement sits above the `deferred_shutdown_cancellation` re-raise at `shutdown.py:1213-1214`, so
a deferred cancellation cannot skip the drain.

**Budget.** Keep the single field `audit_drain_timeout_s: float = 2.0` (`config.py:4367`) and split it:
phase 1 gets **half**, phase 2 gets the **full** value. Worst case 3.0 s inside the 10 s teardown.
Do **not** add a second config field; document the split in `_flush_audit_log`'s docstring.

### The cost

An append after `shutdown.py:1211` is still in-memory-only. That window now holds nothing but a
`logger.info` and the return, so the residual is a genuine end-of-life record rather than the whole
pool and mesh teardown. Unavoidable without leaving registration open past the point where anything
could flush it.

---

## Decision D — the stale schema comment (L4)

`security/audit.py:466` still reads:

> `sequence` is the natural primary key (already monotonic per `len(self.entries)`-based assignment in
> `AuditLog.append`)

False since this same build introduced `_next_sequence()` (`security/audit.py:335-343`), whose own
comment says *"NOT `len(self.entries)`: eviction breaks that identity."* The schema comment now
contradicts code sitting 130 lines above it. Rewrite it to describe `_next_sequence()` semantics:
monotonic, never rewound, **not** derived from list length. Same commit as the behaviour, per the
standing rule below.

---

## What revision 1 got wrong — historical, retained for the anchor-drift record

### Material scope error: the mesh path IS audited now

Revision 1's "What this does NOT change" said:

> No change to the mesh `CodeRunnerAgent` path, **which is not audited and says so** (BF-787).

**False at HEAD.** AD-1280 / BF-787 (`2f19e458`, 2026-08-26) gave it the same record. There are now
**two** `ExecutionAuditor` instances, each with its own `_absence_warned` flag:

```
src/probos/tools/code_execution_tool.py:314:        self._auditor = ExecutionAuditor(runtime)
src/probos/agents/code_runner.py:152:        self._auditor = ExecutionAuditor(self._runtime)
```

This is not a line-number nit. **Decision 1(b) below — labelling the run, not just the log — must now
cover both paths**, and they return different types (`ToolResult` vs `IntentResult`). Building
revision 1 as written would label one path and silently leave the other unlabelled, which is exactly
the defect shape this AD exists to close.

### The audit body moved files

AD-1280 moved `_audit`'s body out of the tool into a shared builder. `code_execution_tool.py:525` is
now a thin delegate with an unchanged signature. **All docstring-correction work targets
`execution/audit.py`, not `code_execution_tool.py`.**

### Anchor drift table

| Anchor | Revision 1 | **Current (HEAD `7edf309e`)** | |
|---|---|---|---|
| `entries: list[AuditEntry]` | `audit.py:54` | `audit.py:54` | stable |
| `GENESIS_HASH` | `audit.py:65` | `audit.py:65` | stable |
| `append` | `audit.py:67` | `audit.py:67` | stable |
| `verify_chain` | `audit.py:120` | `audit.py:120` | stable |
| `_hash` | `audit.py:147` | `audit.py:147` | stable |
| `_pending_writes` | `audit.py:50,63,116,117` | `audit.py:50,63,116,117` | stable |
| `AuditLogPersistence` | `audit.py:174` | `audit.py:174` | stable |
| `stop()` "NOT wired" | `audit.py:211-213` | `audit.py:183`, `audit.py:211-213` | stable |
| `audit_persistence_enabled` | `config.py:4344` | **`config.py:4350`** | **+6** |
| `audit_persistence_filename` | — | `config.py:4351` | |
| `audit_retention_days` | `config.py:4346` | **`config.py:4352`** | **+6** |
| `audit_persistence_enabled` (YAML) | `system.yaml:1271` | `system.yaml:1271` | stable |
| `runtime.audit_log = AuditLog(...)` | `finalize.py:3764` | **`finalize.py:3896`** | **+132** |
| `audit_enabled` gate | — | `finalize.py:3894`; model at `config.py:4305` | |
| persistence construction | `finalize.py:3770,3772` | **`finalize.py:3904,3910,3912`** | **moved** |
| `load_entries()` | — | **`finalize.py:3920`** | |
| `entries.extend(loaded)` | `finalize.py:3790` | **`finalize.py:3922`** | **+132** |
| `verify_chain()` at boot | `finalize.py:3791` | **`finalize.py:3923`** | **+132** |
| `attach_persistence` | `finalize.py:3798` | **`finalize.py:3929`** | **moved** |
| `audit_log_persistence = persistence` | `finalize.py:3809` | **`finalize.py:3930`, `:3941`** | **moved** |
| "the control that makes…" docstring | `code_execution_tool.py:558-561` | **`execution/audit.py:120`** | **file moved** |
| sink `getattr(..., "audit_log", None)` | `code_execution_tool.py:578` | **`execution/audit.py:140`** | **file moved** |
| swallow-`Exception` rationale | `code_execution_tool.py:568-570` | **`execution/audit.py:131`** | **file moved** |
| once-per-instance warning | `code_execution_tool.py:586-587` | **`execution/audit.py:149`** | **file moved** |
| `def _audit` (tool) | `code_execution_tool.py:558` | **`code_execution_tool.py:525`** (delegate) | **−33** |
| browser `_audit_log.append` | `browser/tool.py:1187` | `browser/tool.py:1187` (`def` at `:1158`) | stable |
| approval-gate appends | `approval_gate.py:120,152` | `approval_gate.py:120,152` | stable |
| `shutdown.py` "5s timeout" comment | `:251` | `:251` | stable |
| `__main__.py` outer stop budget | `:653`, `:938` | `:653`, `:938` (`timeout=10`) | stable |
| `drain_pending_tasks` | `mesh/intent.py:321-347` | `mesh/intent.py:322` | stable |
| store-teardown insertion block | `shutdown.py:912,917,922` | `shutdown.py:912,917,922` | stable |

`security/audit.py` did **not** move at all. Everything that moved is in `config.py`, `finalize.py`,
and the AD-1280 file split.

---

## The four gaps, re-verified at HEAD `7edf309e`

None is fixed.

### Gap 1 — in-memory first

```
src/probos/security/audit.py:54:    entries: list[AuditEntry] = field(default_factory=list)
```

The hash chain is real (`_hash` at `:147`, `verify_chain` at `:120`) and it works. It verifies a list
living in the process.

### Gap 2 — persistence is default-off

```
src/probos/config.py:4350:    audit_persistence_enabled: bool = False
config/system.yaml:1271:  audit_persistence_enabled: false
```

The comment above it (`config.py:4345-4349`) already contains this build's forcing function:

> AD-456d-4 will flip default to True once **AD-456d-1 (shutdown-flush hook)** lands.

AD-1278 **is** AD-456d-1 and AD-456d-4. Both halves land here or neither does.

Note the contrast that makes this a live defect rather than a stylistic one: `system.yaml:2119` ships
`audit_persistence_enabled: true` for **clinical telemetry**. The security audit chain — the one
holding the accountability record for arbitrary code execution — is the one shipped off.

### Gap 3 — no shutdown drain

**Absence verified by enumeration, reaching where the drain would live:**

```
CLAIM: nothing drains _pending_writes and nothing stops AuditLogPersistence at shutdown

RUN:   grep "audit_log_persistence|AuditLogPersistence" src/
FOUND: security/audit.py:46,58,137,138,174,209             (definition only)
       startup/finalize.py:3902,3904,3910,3912,3930,3941   (construction only)
       ZERO hits in startup/shutdown.py

RUN:   grep "audit_log_persistence|audit_log" src/probos/startup/**
FOUND: finalize.py only — 12 hits. shutdown.py: none.

RUN:   read src/probos/startup/shutdown.py:139-162   (_stop_runtime_sqlite_sidecars)
       — EXACTLY where such a drain would live: "runtime-owned SQLite services
         without another lifecycle owner". Its tuple is:
           capability_request_store, fault_report_store, knowledge_edges,
           personal_ontology_prober, rejection_cache
       audit_log_persistence is NOT in it.

RUN:   grep "_pending_writes" src/
FOUND: security/audit.py:50,63,116,117 — the definition and its own two writes.
       NO consumer anywhere in src/.

HOLDS: YES. No drain exists, and the one natural home for it does not contain it.
```

`AuditLogPersistence` documents its own orphaning twice, at `audit.py:183` and `audit.py:211-213`:
*"NOT wired into runtime shutdown in v1 […] Tests call `stop()` directly."*

### Gap 4 — unbounded growth and task fan-out

`entries` has no cap. `append` (`:67`) schedules one `loop.create_task` per call (`:115-117`) with no
queue and no ceiling. The issue's measurements (10,000 rows ≈ 5.93 MB / 342 ms; 1,000 appends → 1,000
pending tasks under a blocked sink) are consistent with this code. **Do not re-derive them.**

---

## Two classes named `AuditLog` — do not confuse them

Still the single most likely way to break this build.

| | AD-456 chain log | assistant log |
|---|---|---|
| Module | `src/probos/security/audit.py:39` | `src/probos/security/audit_log.py:25` |
| Shape | frozen `AuditEntry`, SHA-256 chain, in-memory list | SQLite table `assistant_audit_log` |
| Reached by | `runtime.audit_log` (`finalize.py:3896`) | `routers/security.py:46` |
| Retention | **none today** | `audit_retention_days` (`routers/security.py:50`) |

`ExecutionAuditor` reads `getattr(self._runtime, "audit_log", None)` (`execution/audit.py:140`) — the
**AD-456 chain log**. Everything in this AD is about that one. `audit_retention_days` is **already
consumed by the other class**; do not overload it, and do not add eviction to `audit_log.py`.

---

## Decision 1 — durability posture: **durable-preferred with honest degradation**

Recorded here with its cost, per Design Principle 13(a). This confirms revision 1's conclusion but
**replaces its reasoning**, which leaned on a principle that does not apply.

### The counter-argument, taken seriously first

The case for **durable-required** is real and must not be waved away. BF-763 removed a quorum gate on
the explicit argument that the audit record *is* the substitute control. If the record can be absent,
the substitution failed and the gate was removed for nothing. And DP 13(a) — a capability ceiling must
be a decision, not an inheritance — **cuts both ways here**: durable-required, chosen deliberately and
shipped with the default already flipped on, would be a *decision*, not an inheritance. So 13(a) does
**not** by itself rule it out. Any argument claiming it does is too quick.

### Where the appeal to 13(c) fails

13(c) — *"Authority routes capability; it does not ration it… a refusal that ends the work is a
capability ceiling wearing a governance costume"* — reads like it settles this. It does not.

13(c) is about the **chain of command**: an agent whose rank or department cannot authorise something
**escalates to one that can**, rather than refusing. Its remedy is *routing*. A locked SQLite file has
nobody to escalate to; there is no authority anywhere on the ship that can authorise a full disk into
working. **13(c) is off-point and must not be cited as the reason.** Revision 1 leaned on it, and that
was the weakest link in its argument.

### What actually decides it

Two arguments, in order of force.

**1. Durable-required does not deliver what it promises.** A sink check happens at **launch**. The four
gaps are about a record being lost *after* a successful `append` — an undrained tail at shutdown, an
eviction, a queue overflow, a crash. A launch-time check proves the sink existed at t=0 and proves
**nothing** about whether *this* record survives. Durable-required would buy the *appearance* of
guaranteed accountability at a real availability cost, while leaving gaps 3 and 4 exactly where they
are. It is the more rigorous-sounding option and the less rigorous one.

**2. DP 13(b): prefer a governed path over a removed one.** Durable-required buys accountability by
deleting the capability. The governed path — execute, label the run ungoverned in its own result, say
so in the record — reaches the same accountability without the deletion. It would also reverse a
decision already shipped and reasoned about in this very file: `execution/audit.py:131` swallows sink
exceptions precisely because *"an audit write that could fail an execution would turn the
accountability trail into a new way to lose work."* Making the sink fatal at launch contradicts that
without re-arguing it.

### The answer to "then the gate was removed for nothing"

It was not removed for nothing — it was removed **in exchange for a record**. The way to honour that
exchange is to make the record **actually survive**: gaps 2, 3 and 4. That is what this AD builds.

After it lands, the ungoverned configuration is one an operator must *choose* (set
`audit_enabled: false`); out of the box the trail is durable; and every run that misses the sink is
self-labelled in its own result. **That is a decision, not an inheritance — 13(a) satisfied** —
without the availability coupling.

### What "preferred" therefore obliges

"Preferred" is only honest if the good path is the **default** and degradation is **visible**. Today
neither holds: persistence is off out of the box, and the degradation notice is a `logger.warning`
fired once per auditor instance (`execution/audit.py:149`) into a log nobody reads. So:

- **(a) Flip the default.** `audit_persistence_enabled: bool = True` in `SecurityInfraConfig`
  (`config.py:4350`) and `true` in `config/system.yaml:1271`. Gap 2 closes by making the good path the
  default, **not** by making the bad path fatal.
- **(b) Label the run, not just the log — on BOTH execution paths.** **SUPERSEDED BY DECISION B — do
  not build this bullet as written.** Its obligation (both paths self-label) is right and stands; its
  *vocabulary* is the Critical 2 defect. Revision 2 built exactly what this bullet says, and what it
  says is `durable: false` in the record and `"durable"` as the healthy label — a claim about disk
  made by a synchronous call that cannot observe disk. Decision B replaces `durable` with `stream`
  and `"durable"` with `"queued"`. Everything else here — return the fact and let each caller shape
  it, never reach into either caller's result type — is unchanged and correct.
- **(c) Keep the once-per-instance warning.** It is right for log volume, and AD-1280's comment at
  `execution/audit.py:105-117` explains why it is deliberately per-auditor rather than per-process.
  **Do not collapse the two auditors onto a shared sentinel** — that comment is a standing decision,
  and two untrailed paths is two facts.

### Sequencing constraint — the flip is not free-standing

**The default flip must not land before the drain and the cap exist.** Flipping it first turns on
SQLite writes fleet-wide while the tail can still be lost and the list can still grow without bound.
It belongs in Slice B. This is why the slicing below is not merely a convenience.

### The cost, stated plainly

An operator who sets `audit_enabled: false`, or whose sink fails mid-run, **still gets code
execution**. There remains a configuration in which ProbOS runs Python with no durable accountability
trail. We accept that, and in exchange every such run is self-labelled as ungoverned in its own result
and in its own record, on **both** execution paths, so the capability is never *silently* ungoverned.
The residual risk is an operator who reads neither. The alternative — a runtime that refuses to
execute code because a SQLite file is locked — costs more than it buys, and would not have saved the
record anyway.

---

## Decision 2 — eviction, and truncation vs tampering

### The trap

`verify_chain()` (`audit.py:120-134`) starts its walk at `GENESIS_HASH` and fails on
`entry.prior_hash != prior`. **Evict `entries[0]` and it returns `False`.** A bounded log would report
itself as tampered on every boot, and `finalize.py:3923-3928` would log *"tamper or corruption
suspected"* for a log that is merely full. **Getting the cap without this is worse than not getting
the cap** — it would make the control lie in the most damaging direction, crying tamper until nobody
believes it.

### The mechanism: an anchored genesis (the truncation watermark)

Add one field to `AuditLog`:

```python
# The (sequence, entry_hash) of the last entry evicted from `entries`.
# None means the list still starts at genesis.
_truncated_at: tuple[int, str] | None = None
```

`verify_chain()` anchors its walk at `self._truncated_at[1]` when a watermark is present, and at
`GENESIS_HASH` when it is not. The watermark **is** the substitute genesis.

| Log state | `verify_chain()` | `chain_state()` |
|---|---|---|
| full, intact | `True` | `("intact", 0, 0)` |
| head evicted, suffix intact | `True` | `("truncated", first_seq, evicted_count)` |
| any hash mismatch or discontinuity | `False` | `("broken", first_seq, evicted_count)` |

**Truncation is not tampering, so `verify_chain()` returns `True` for a correctly truncated chain.**
That is the whole point of acceptance criterion 4, and it is why the richer answer needs a second
accessor rather than a changed return type.

Three properties the watermark must have, all separately testable:

1. **Write-once-forward.** `_truncated_at` may be advanced only by the eviction path and only to a
   **higher** sequence. A freely-settable watermark would let tampering masquerade as truncation — the
   anchor would simply move to wherever the break is, and `verify_chain()` would return `True` for a
   mutated chain. Enforce monotonicity and test the rejection.
2. **`chain_state()` never reports `"intact"` once a watermark exists.** A verifier must be able to
   tell a bounded log from a complete one. Silent truncation reported as `intact` is the same lie in
   the other direction.
3. **Captured before removal.** The watermark comes from the entry being dropped, read while it is
   still in the list.

### The eviction policy

**FIFO from the head, and only for entries the sink has confirmed.**

- **FIFO** because the chain is ordered: only head-eviction leaves a contiguous, verifiable suffix.
- **Durability-gated**: **SUPERSEDED BY DECISION A4 — do not build this bullet as written.** Its
  instinct is right and its second half is the reason the cap exists, but it is undifferentiated: it
  refuses eviction even when persistence is off **by configuration**, which silently defeats the
  memory bound in the commonest deployment. A4 splits it — evict normally when no durable copy was
  ever promised; refuse only when one was. The sentence that stands is the last one: **the cap is a
  memory bound, never a data-destruction policy.** And note the gate is only sound once Decision A3
  makes the watermark contiguous — a durability gate reading a watermark that jumps holes deletes
  precisely the entries it exists to protect, which is Critical 1.
- New field `SecurityInfraConfig.audit_max_entries: int = 10_000` (≈6 MB by the issue's measurement).
  `ClinicalTelemetryConfig` already has a field of the same name (YAML at `system.yaml:2118`) —
  different model, no collision, and that precedent is why this name.

### The boot interaction — do not skip this

`finalize.py:3922` does `runtime.audit_log.entries.extend(loaded)` against an **empty** list, and
`finalize.py:3923` then calls `verify_chain()`. If the DB holds more rows than the cap, this rebuilds
the unbounded list the cap exists to prevent, *and* verifies a load that legitimately does not start
at genesis.

So `load_entries()` must gain a bound: load the newest `audit_max_entries` rows **in ascending
sequence order**, and return (or otherwise expose) the watermark for the newest row **not** loaded, so
the caller can set it **before** verifying. Wire the watermark set **between** `finalize.py:3922` and
`:3923`.

---

## Decision 3 — backpressure: one bounded queue, one writer

Replace per-append `create_task` (`audit.py:115-117`) with a single `asyncio.Queue(maxsize=...)` and
one long-lived writer task that batches commits.

- `append` stays **synchronous** and must never raise or block. It does `put_nowait`; on `QueueFull`
  it does **not** wait. **SUPERSEDED BY DECISION A1 for what happens next:** it must **spill**, not
  drop. Dropping is the hole that poisons the on-disk chain (Critical 1's root cause). The
  synchronous, never-raising, never-blocking contract is unchanged and correct.
- The writer commits in **batches**. One `commit()` per batch, not per row (`persist_entry` currently
  commits per row).
- Preserve the existing no-running-loop behaviour (`audit.py:105-112`): sync test paths must remain a
  debug-logged no-op, not an error.
- `_pending_writes` is retired as a mechanism. **The nine assertions that read it in
  `tests/test_ad456d_audit_log_persistence.py` (`:58, :81, :193, :197, :202, :221, :234, :331, :369`)
  must be UPDATED to the new synchronisation point, not deleted.** They are the only tests proving a
  row actually lands. Record inline why each changed.

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

1. **Do not reuse `shutdown_drain_timeout_s`.** It defaults to `30.0` — already larger than the outer
   `wait_for`. Borrowing it would guarantee the audit drain is cancelled from outside rather than
   completing.
2. **New field `SecurityInfraConfig.audit_drain_timeout_s: float = 2.0`.**

Behaviour — specify all three:

- **Close registration first.** Stop accepting new entries into the queue before draining, so the
  drain has a fixed target rather than a moving one. `IntentBus.drain_pending_tasks`
  (`mesh/intent.py:322`) is the sibling pattern: close registration, deadline via `loop.time()`,
  `asyncio.wait(timeout=remaining)`, cancel stragglers, never `gather` unbounded.
- **On expiry:** cancel the writer, **log at `ERROR`** naming the count of unflushed entries and the
  sequence range lost, then proceed to `stop()`. The tail loss becomes a stated fact, not a silence.
- **On `asyncio.CancelledError`** (the outer 10 s firing mid-drain): cancel the writer and **re-raise**.
  Cancellation belongs to the shutdown, not to this drain.

> **Async trap — do NOT use `asyncio.wait_for` to bound the writer.** On timeout `wait_for` cancels the
> inner task and then **awaits it unbounded**. A writer that catches `CancelledError` to finish its
> final commit would hang shutdown forever, and a bounded wait placed *after* the `wait_for` is never
> reached. Use `asyncio.wait({task}, timeout=...)`, which neither cancels nor raises; then cancel
> explicitly, `wait` again with a second bound, and abandon loudly if still not done.

**Insertion point: SUPERSEDED BY DECISION C.** Revision 2 read "after the stores that may still append"
and landed at `shutdown.py:984` — which is *before* the pool scaler (`:1073`), the pools and intent bus
(`:1122`), the knowledge store (`:1126`), the mesh services (`:1151`) and the semantic layer (`:1208`).
Because `drain()` closes registration, every one of those teardown steps could then only append in
memory. Build the two-phase placement in Decision C instead. The bound, the `asyncio.wait` shape and
the cancellation semantics described in this section are unchanged and confirmed sound.

**Also fix in the same commit:** `shutdown.py:251` says *"__main__.py enforces a 5s timeout on
stop()"*. It is **10 s** (`__main__.py:653`, `:938`); the 5 s at `__main__.py:928` is
`adapter.stop()`, a different call.

---

## The false claims, corrected in the same commit as the behaviour

Three unhedged claims are **already in the tree** — this is not a claim we are about to gain.

1. **`execution/audit.py:120`** — *"it is the control that makes the capability defensible (Design
   Principle #13)."* Verified unhedged: `grep "best.effort|may be lost|not durable|process exit|
   in-memory" src/probos/execution/audit.py` returns **zero hits**. The AD-1247 warning at `:146-155`
   is honest about the sink being **absent**, but says nothing about a present sink being
   **non-durable**.
2. **`security/audit.py:1-6`** — *"v1 in-memory only. […] Persistence to SQLite deferred to AD-456d."*
   AD-456d shipped; `AuditLogPersistence` is 130 lines below that sentence.
3. **`shutdown.py:251`** — the 5 s/10 s error above.

**Correct all three in the same commit as the behaviour they describe.** Not before — a docstring
promising durability the code has not got yet is the same defect pointing the other way.

---

## Do not change the `verify_chain` signature

`verify_chain() -> bool` has one production consumer and six test assertions:

```
src/probos/startup/finalize.py:3923
tests/test_ad456_security_infrastructure.py:203, 209, 222, 229
tests/test_ad456d_audit_log_persistence.py:347, 389
```

Keep it `-> bool`. Add `chain_state() -> tuple[str, int, int]` for the richer answer. Changing the
return type would churn seven call sites for no gain and is **out of scope**.

`AuditLog` is a `@dataclass`; every construction site is keyword-or-empty (`finalize.py:3896` plus
test sites), so appending fields is safe — but **append them, do not reorder**, and keep defaults on
all new fields.

---

## Slicing

**Slice A — the losses that need no policy (does NOT close #1243).**
Shutdown drain + bounded queue/single writer + honest-degradation labelling **on both execution paths**
+ the three false-claim corrections. Closes gap 3 and gap 4's fan-out half. Ships alone, safely, with
the default still `False`.

**Slice B — the policy half (closes #1243).**
`audit_max_entries` + FIFO durability-gated eviction + `_truncated_at` + anchored `verify_chain` +
`chain_state()` + bounded `load_entries` + **the default flip to `True`**.

The flip belongs in B per the sequencing constraint in Decision 1.

---

## Tests — revision 3

**28 tests are already written and staged** in `tests/test_ad1278_audit_durability.py`. Most survive.
Be precise about which do not. The Slice A / Slice B lists further down are revision 2's original
specification, retained because items 1–23 map onto those 28; **build the KEEP / CHANGE / ADD plan
here**, and read the older lists only for the rationale behind a test you are keeping.

### KEEP unchanged (24)

Everything except the four below. In particular keep all six drain tests (`:143`, `:177`, `:187`,
`:215`, `:233`, `:258`) — the drain **mechanism** was confirmed sound; only its **placement** changes.

### CHANGE (4) — and record inline why each changed

> **This is the highest-risk part of the build.** Three of these four currently assert the *defective*
> behaviour as the contract. A test that pins a defect passes forever, and that is how this class of
> bug survives review — four instances in one week in this repo (BF-707, BF-710, BF-717, BF-720).
> **Update the assertion and leave a one-line comment naming AD-1278 revision 3 and what the old
> assertion believed. Never delete one to make a build green.**

| Test | Line | Currently believes | Must now assert |
|---|---|---|---|
| `test_a_durable_run_carries_no_label` | `:380` | The suppressed label is `"durable"`. | The suppressed label is `"queued"`. Rename to `test_a_queued_run_carries_no_label`. |
| `test_result_labels_a_run_whose_entry_was_dropped` | `:431` | Queue-full **drops** the entry. | Queue-full **spills** (A1). The run may still label `in-memory-only` while the queue is full — that half is right — but the entry **must be present in the DB afterwards**. Rename to `…_whose_entry_was_spilled`. |
| `test_unpersisted_entries_are_not_evicted` | `:484` | Undifferentiated refusal to evict. | Persistence **attached** and behind → refuses (unchanged). The persistence-**off** case moves to ADD-7. |
| `test_shutdown_calls_the_audit_drain` | `:177` | One call site. | **Two** phases, asserted by **order relative to pool teardown**: phase 1 before `_stop_pools_and_drain_intent_bus`, phase 2 after `_semantic_layer.stop()`. |

### ADD (12–18)

**Decision A — the non-contiguous case. The absence of these is what let both Criticals ship.**

1. `test_queue_overflow_leaves_no_hole_in_the_persisted_stream` — force `QueueFull`, let the writer
   catch up, assert the DB sequence set is **contiguous** and equals the appended set.
   *Headline test; it fails against the staged build.*
2. `test_watermark_refuses_a_non_contiguous_advance` — call `mark_persisted_through` across a gap
   directly; assert `_persisted_through` does **not** move and an ERROR is logged.
3. `test_eviction_never_drops_an_entry_absent_from_the_sink` — the reproduction, asserted: drive a
   **real SQLite sink** through overflow, then compare the DB sequence set against everything evicted.
   **Nothing evicted may be missing from the DB.**
4. `test_rehydrated_chain_is_intact_after_overflow` — the chain half of the same scenario. Restart
   against the same DB; assert `verify_chain()` is `True` and `chain_state()[0] != "broken"`.
   *This is the test that proves the amendment to the root cause is closed.*
5. `test_failed_batch_is_retried_not_skipped` — sink fails once then succeeds; assert every sequence
   lands and the watermark stayed contiguous.
6. `test_exhausted_retries_terminate_the_stream` — sink fails `audit_write_max_retries + 1` times;
   assert `durable_stream_open()` is `False`, nothing further is written, and the DB chain **ends**
   cleanly rather than gaining a hole.
7. `test_cap_evicts_normally_when_persistence_is_off` (A4) — no sink attached; assert `entries` is
   bounded by `audit_max_entries` **and** `chain_state()[0] == "truncated"`.

**Decision B — labelling.**

8. `test_record_never_returns_durable` — `"durable"` is not in the returned vocabulary on either path.
9. `test_record_detail_carries_stream_not_durable` — assert `detail["stream"]`, assert `"durable"` is
   absent from the detail, assert `"durable" not in AUDIT_DETAIL_ALLOWLIST`.
10. `test_both_paths_suppress_queued_and_surface_in_memory_only` — **one test covering `ToolResult`
    and `IntentResult` together**, so a one-path fix cannot pass it.
11. `test_durable_stream_open_is_false_after_stream_breaks`.

**Decision C — drain placement.**

12. `test_phase_one_flush_leaves_registration_open` — after phase 1, an append still reaches the queue.
13. `test_an_append_during_pool_teardown_reaches_disk` — **the seam test.** Drive the real `shutdown()`
    with an appender wired into a component that stops between `:984` and `:1211`; assert the entry is
    in SQLite afterwards. Tests 12 and the existing drain tests each prove one half; **only this one
    crosses the seam**, and half-chain evidence is this repo's dominant defect shape.

**Decision D.**

14. `test_schema_comment_does_not_claim_len_based_sequencing` — or extend an existing BF-781 guard.
    Assert the **corrected** wording is present, not merely that the old string is absent.

---

## Mutation requirements — and why the last matrix passed while both Criticals shipped

Revision 2's build ran **17 mutants, all KILLED, with a surviving null control.** That matrix was
methodologically clean and still missed both Criticals.

**Why: every mutant perturbed the contiguous path. Not one constructed a stream with a hole in it.**
A mutation matrix measures the tests against the failure modes enumerated when the matrix was written;
it is silent on the ones that were not. *17/17 KILLED* means "the listed behaviours are pinned" — it
never means "the design is sound", and must not be reported as though it does.

**Standing rule this build adds:** for any code that infers a **range** property from a **point**
observation — a watermark, a high-water counter, an "everything below this is done" flag — **at least
one mutant must construct the discontinuous input.** If no mutant produces a hole, the matrix has not
tested the invariant that matters.

Required for revision 3, in addition to re-running the original 17:

| # | Mutation | Must be |
|---|---|---|
| M1 | Delete the contiguity guard in `mark_persisted_through` (accept any forward jump) | **KILLED** by ADD-2, ADD-3 |
| M2 | Weaken the guard from `!= _persisted_through + 1` to `< _persisted_through + 1` | **KILLED** by ADD-2 |
| M3 | Restore drop-on-`QueueFull` in place of the spill | **KILLED** by ADD-1, ADD-4 |
| M4 | Advance on `max(confirmed)` instead of the contiguous run | **KILLED** by ADD-3 |
| M5 | Make a failed batch skip instead of retry | **KILLED** by ADD-5 |
| M6 | Let the stream keep writing after retries are exhausted | **KILLED** by ADD-6 |
| M7 | Flip `_enforce_cap`'s `>` at `:436` to `>=` | **KILLED** by the changed `:484` test |
| M8 | Invert the A4 branch (evict when attached / refuse when off) | **KILLED** by ADD-7 and `:484` |
| M9 | Revert **one** suppression comparison to `"durable"` — one path only | **KILLED** by ADD-10 |
| M10 | Move phase 2 back above `_stop_pools_and_drain_intent_bus` | **KILLED** by ADD-13 |
| N | Null control: comment-only edit | **SURVIVED** |

Method reminders that cost time last run: run the unmutated baseline **first** and abort if it is
already red or every mutant looks killed; mutate **in place** with a `.mutbak` sibling and restore in
`finally`; **single-line anchors only** — this is a CRLF tree and a multi-line anchor silently matches
nothing, producing an **INERT** mutant, which is not a killed one; classify a timeout banner as
**INVALID, never SURVIVED**. Before concluding a surviving mutant means a weak test, check the mutant
actually reaches the behaviour it claims to break.

---

## Revision 2's original test specification (retained for rationale)

New file: `tests/test_ad1278_audit_durability.py`. Source-claim guards go in the existing BF-781 guard
files.

### Slice A

1. `test_shutdown_drain_flushes_the_last_append` — append, then run the **real shutdown path**; assert
   the **final** entry is present in SQLite. **This must cross the seam** (append → drain → row on
   disk). Asserting the drain was *called* does not count.
2. `test_drain_is_bounded_when_the_sink_is_wedged` — sink that never returns; assert the drain returns
   within budget and does not hang. Bound the test itself so a regression fails rather than hangs CI.
3. `test_wedged_drain_logs_the_loss_at_error` — assert the ERROR record names an unflushed count.
4. `test_drain_reraises_cancellation` — cancel mid-drain; assert `CancelledError` propagates **and**
   the writer task is cancelled.
5. `test_queue_full_does_not_raise_from_append` — fill the queue; assert `append` still returns an
   `AuditEntry`.
6. `test_n_appends_do_not_create_n_tasks` — the direct regression for gap 4. Assert the task count
   stays at one writer across N appends. N ≥ 100.
7. `test_append_remains_sync_with_no_running_loop` — the no-loop path (`audit.py:105-112`) stays a
   no-op.
8. `test_tool_result_labels_a_run_with_no_sink` — `ToolResult` carries the ungoverned label.
9. `test_intent_result_labels_a_run_with_no_sink` — **the `CodeRunnerAgent` mesh path**
   (`agents/code_runner.py:152`). This is the test revision 1 would have omitted.
10. `test_both_auditors_warn_independently` — locks AD-1280's per-auditor sentinel; a shared
    process-wide flag must fail this.
11. `test_result_labels_a_run_whose_entry_was_dropped` — queue full → `durable: false`.
12. Source guards (BF-781 style, in `tests/test_bf781_execution_tool_claims.py` /
    `tests/test_bf781_isolation_claims.py`): each must assert the **corrected wording is present**, not
    merely that the old string is absent — an empty docstring would pass an absence-only check.

### Slice B

13. `test_entries_are_capped_at_audit_max_entries`
14. `test_eviction_is_fifo_from_the_head`
15. `test_unpersisted_entries_are_not_evicted` — persistence off; assert the list exceeds the cap
    rather than dropping the only copy.
16. `test_truncated_chain_verifies_as_intact` — **the central test.** Evict, then
    `verify_chain() is True`.
17. `test_truncated_chain_reports_truncated_not_intact` — `chain_state()[0] == "truncated"`.
18. `test_tampered_truncated_chain_reports_broken` — mutate an entry **after** truncation; assert
    `verify_chain() is False` **and** `chain_state()[0] == "broken"`. **Tests 16 and 18 are a pair** —
    they prove the two conditions are distinguishable, and neither alone does. This is acceptance
    criterion 4.
19. `test_watermark_is_monotonic` — a backwards write is rejected.
20. `test_watermark_only_moves_via_eviction`.
21. `test_load_entries_respects_the_cap`.
22. `test_boot_sets_the_watermark_before_verifying` — the ordering bug: a legitimately-capped rehydrate
    must **not** log tamper at `finalize.py:3923`.
23. `test_persistence_default_is_true` — `SecurityInfraConfig().audit_persistence_enabled is True`
    **and** `config/system.yaml:1271` agrees. Two assertions; the YAML has drifted from the model
    before.

### Gates

- **Focused:**
  `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1278_audit_durability.py tests/test_ad456_security_infrastructure.py tests/test_ad456d_audit_log_persistence.py tests/test_ad1247_execution_audit.py tests/test_ad1280_mesh_execution_audit.py tests/test_bf763_execution_claims.py tests/test_bf781_execution_tool_claims.py tests/test_bf781_isolation_claims.py -q -p no:randomly`- **Signature-change sweep before the broad gate.** `append`'s internals and `load_entries`' signature
  both move. Run `grep "getsource|src\.index\(|\?raw"` over `tests/` and execute every file that scans
  `security/audit.py`, `startup/shutdown.py`, `execution/audit.py`, or `tools/code_execution_tool.py`.
  A `?raw` guard that pins the *current* wording will fail on the corrected wording — that is the test
  doing its job; update it and record why inline. **Never delete such a test.**
- **Broad gate:** full suite **once**, after the slice is frozen. Any source or test edit after the
  gate invalidates it. Expect ~15–19 min; it sits at `[ 99%]` for several of those. Run it
  synchronously; do not poll.
- **Adversarial review** on the staged diff before commit, with a **different model than the author**.

---

## What this does NOT change — "Do not build"

- **Do NOT fork a second audit path for execution.** `AuditLog` is shared and every consumer gains
  from the fixes here. Verified consumers of the AD-456 chain log:
  `execution/audit.py:190` (both execution paths), `tools/browser/tool.py:1187` (AD-706),
  `cognitive/self_improvement/approval_gate.py:120,152`. Explicitly forbidden by the issue.
- **Do NOT add a consensus gate to `run_python`.** BF-763 settled that; this AD is the other half of
  that bargain, not a reversal.
- **Do NOT change `AuditEntry`.** It is frozen and its six fields are the `_hash` payload — adding one
  invalidates every existing entry's hash and every persisted row.
- **Do NOT change `verify_chain()`'s signature.** Add `chain_state()` instead.
- **Do NOT touch `security/audit_log.py`** (the assistant log) or `audit_retention_days`, which that
  other class already consumes (`routers/security.py:50`).
- **Do NOT add retention/TTL on the SQLite rows.** The cap bounds **memory** only. Disk retention is a
  separate question and stays open.
- **Do NOT collapse the two `ExecutionAuditor` sentinels** onto a shared process-wide flag. AD-1280
  decided this deliberately (`execution/audit.py:105-117`).
- **Do NOT add `EventType.AUDIT_TAMPER_DETECTED` or a Captain-alert path.** Deferred (AD-456d-3).
- **Do NOT build an HXI surface** for the chain. Deferred (AD-456d-7).
- **Do NOT reuse `shutdown_drain_timeout_s`** for the audit drain.
- **Do NOT refactor `finalize.py`'s audit block** beyond inserting the watermark set and bounding the
  load. It is ~50 lines inside a broad `try/except`; leave its shape alone.
- **Do NOT make `record()` async, or have it await confirmation.** Decision B rejected that explicitly:
  it would couple execution latency to disk and contradict `execution/audit.py:131`.
- **Do NOT "fix" Critical 1 by only hardening the watermark.** Options (i)–(iii) all leave the on-disk
  chain poisoned. Close the holes (A1, A2) as well as guarding the watermark (A3).
- **Do NOT touch** `README.md`, `docs/architecture/federation.md`, or `docs/development/roadmap.md` —
  they carry another session's uncommitted edits. **Do NOT touch `config/system.yaml`** beyond the
  single already-staged `audit_persistence_enabled` line: it is `skip-worktree` and holds the
  Captain's local overrides.

---

## Tracking

- `PROGRESS.md` — one CLOSED line per slice, naming the durability decision. The AD-1278 entry is
  **already staged**; update it rather than adding a second.
- `DECISIONS.md` — AD-1278: the durable-preferred decision, **its cost**, why 13(c) does not apply,
  and the anchored-genesis mechanism. This is a governance posture, so it is recorded, not just built.
  **The staged AD-1278 entry describes the REJECTED design and must be rewritten**, not appended to:
  it currently records `max(confirmed)` eviction, a pre-append durability claim, and a single-phase
  drain. Replace those three with Decisions A, B and C.
- `docs/development/roadmap.md` **Bug Tracker table only** — BF-780 row. **That file is unstaged and
  protected in this session; do not edit it. Report the pending row to the Captain instead.**
- `docs/development/config-reference.md` — three new fields plus the changed default.

---

## Acceptance criteria

**Revision 3 — these are the ones the rejected build failed. All are required.**

R1. No queue-full and no failed-batch condition can produce a gap in the persisted sequence stream
    (ADD-1, ADD-5).
R2. `mark_persisted_through` refuses a non-contiguous advance and logs it at ERROR (ADD-2).
R3. While persistence is attached, nothing is ever evicted from `entries` that is absent from the sink
    (ADD-3).
R4. A restart after an overflow rehydrates a chain that is **not** `broken` (ADD-4).
R5. With persistence off by configuration, `audit_max_entries` is a real bound **and** the chain still
    verifies (ADD-7).
R6. `record()` never returns `"durable"`; the record carries `stream`, not `durable`; **both**
    execution paths suppress `"queued"` and surface everything else (ADD-8, ADD-9, ADD-10).
R7. An audit append occurring during pool/mesh teardown reaches SQLite (ADD-13).
R8. `flush()` is bounded; `drain()` still uses `asyncio.wait`, never `asyncio.wait_for`.
R9. Every changed test carries an inline note naming AD-1278 revision 3 and what the prior assertion
    believed. No test deleted to make the build green.
R10. The mutation matrix runs with the null control **SURVIVING** and M1–M10 **KILLED**.
R11. Adversarial review on the staged diff, by a **different model than the author**, with every
     Critical and High finding resolved **before** commit. This build was rejected once; it is
     reviewed again before it is committed.

**Carried forward from revision 2 — still required.**

1. The durability decision is **recorded with its cost** in `DECISIONS.md`, and the code's wording
   matches the decision.
2. Shutdown drains the writer, with a test proving the **last** append reaches disk (seam-crossing).
3. `entries` is bounded; eviction is FIFO and durability-gated; the policy is stated in the class
   docstring.
4. A truncated chain reports as **truncated, not tampered** — `verify_chain() is True`,
   `chain_state()[0] == "truncated"` — **and** a tampered-after-truncation chain still reports broken.
5. The drain is bounded by `audit_drain_timeout_s`, never hangs, and reports what it lost.
6. N appends produce **one** writer task, not N.
7. An execution that ran without reaching the sink is visible as such **in its own result**, on
   **both** the tool path and the mesh `CodeRunnerAgent` path — not only in a log line.
   *(Vocabulary per Decision B: `"in-memory-only"`, never `"durable"`.)*
8. `audit_persistence_enabled` defaults to `True` in **both** the model and `config/system.yaml`, and
   lands **no earlier than** the drain and the cap.
9. The three false claims (`execution/audit.py:120`, `security/audit.py:1-6`, `shutdown.py:251`) are
   corrected **in the same commit** as the behaviour, with guards asserting the **corrected** wording.
10. No second audit path exists for execution.
11. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against the STAGED TREE (2026-08-28) — revision 3 anchors

Revision 3's findings come from a review of **staged code**, so they were re-verified against the
index, not HEAD. `git rev-parse --short HEAD` → `5c3f0028`, and:

```
git diff --stat -- src/probos/security/audit.py src/probos/execution/audit.py \
                   src/probos/startup/shutdown.py src/probos/agents/code_runner.py \
                   src/probos/tools/code_execution_tool.py
  (empty)
```

Worktree == index for every file cited, so these are the lines the reviewer read.

```
src/probos/security/audit.py:105:  _persisted_through: int = -1
src/probos/security/audit.py:114:  def append(self, *, category: str, detail: str) -> AuditEntry:
src/probos/security/audit.py:156:  def next_append_is_durable(self) -> bool:          <- C2, renamed by B1
src/probos/security/audit.py:177:  def verify_chain(self) -> bool:
src/probos/security/audit.py:200:  def chain_state(self) -> tuple[str, int, int]:
src/probos/security/audit.py:217:  def mark_truncated(self, sequence: int, entry_hash: str) -> None:
src/probos/security/audit.py:234:  def mark_persisted_through(self, sequence: int) -> None:   <- A3 guard goes here
src/probos/security/audit.py:256:  async def flush(self) -> None:
src/probos/security/audit.py:267:      await queue.join()                             <- UNBOUNDED (Decision C)
src/probos/security/audit.py:269:  async def drain(self, *, timeout_seconds: float = 2.0) -> int:
src/probos/security/audit.py:283:      self._writer_closed = True                     <- H3: closes registration
src/probos/security/audit.py:335:  def _next_sequence(self) -> int:                   <- contradicts :466
src/probos/security/audit.py:349:  def _schedule_persist(self, entry: AuditEntry) -> None:
src/probos/security/audit.py:372:          self._dropped += 1                         <- A1: hole source #1
src/probos/security/audit.py:396:  async def _writer_loop(self) -> None:
src/probos/security/audit.py:416:      "AD-1278: the audit writer's batch of %d did not commit; "   <- A2: hole source #2
src/probos/security/audit.py:425:      self.mark_persisted_through(max(confirmed))    <- C1
src/probos/security/audit.py:427:  def _enforce_cap(self) -> None:
src/probos/security/audit.py:436:      if entry.sequence > self._persisted_through:   <- the durability gate
src/probos/security/audit.py:466:  # key (already monotonic per ``len(self.entries)``-based assignment in   <- L4

src/probos/execution/audit.py:52:   AUDIT_DETAIL_ALLOWLIST: frozenset[str] = frozenset({   (contains "durable")
src/probos/execution/audit.py:182:  predicate = getattr(audit, "next_append_is_durable", None)   <- C2
src/probos/execution/audit.py:183:  durable = bool(predicate()) if callable(predicate) else False
src/probos/execution/audit.py:188:      "durable": durable,
src/probos/execution/audit.py:232:  return "durable" if durable else "in-memory-only"

src/probos/startup/shutdown.py:75:    async def _drain_audit_log(runtime: Any) -> None:
src/probos/startup/shutdown.py:984:   await _drain_audit_log(runtime)               <- H3: too early
src/probos/startup/shutdown.py:1122:  deferred_shutdown_cancellation = await _stop_pools_and_drain_intent_bus(
src/probos/startup/shutdown.py:1208:  await runtime._semantic_layer.stop()
src/probos/startup/shutdown.py:1211:  runtime._started = False                     <- phase 2 goes above this
src/probos/startup/shutdown.py:1213:  if deferred_shutdown_cancellation is not None:

src/probos/agents/code_runner.py:301:        if audit_outcome and audit_outcome != "durable":   <- B4, path 1 of 2
src/probos/tools/code_execution_tool.py:770:  if audit_outcome and audit_outcome != "durable":   <- B4, path 2 of 2

src/probos/config.py:4354: audit_persistence_enabled: bool = True     (the flip is ALREADY staged)
src/probos/config.py:4362: audit_max_entries: int = 10_000
src/probos/config.py:4367: audit_drain_timeout_s: float = 2.0
src/probos/config.py:4371: audit_write_queue_maxsize: int = 1000

src/probos/startup/finalize.py:3937: runtime.audit_log.mark_persisted_through(loaded[-1].sequence)
src/probos/startup/finalize.py:3938: if not runtime.audit_log.verify_chain():
```

### Absence Verified against the staged tree (2026-08-28)

```
CLAIM: nothing enforces contiguity of the confirmed sequence stream
RUN:   Select-String src/probos/security/audit.py -Pattern 'mark_persisted_through|_persisted_through'
FOUND: :105 (field)  :234-242 (setter, MONOTONIC ONLY)  :323 (drain log)
       :425 (max(confirmed))  :436 (cap gate)  + finalize.py:3937
HOLDS: YES — the setter's only precondition is `> self._persisted_through`. No gap check exists
       anywhere, so a jump across a hole is accepted by construction. This is Critical 1.

CLAIM: the persist path has no retry
RUN:   Select-String src/probos/security/audit.py -Pattern 'retry|backoff|attempt'
FOUND: zero hits
HOLDS: YES — `_writer_loop` (:396-425) logs a failed batch and proceeds to the next one, so the
       next success confirms a HIGHER range than the failure. Hole source #2.

CLAIM: nothing appends to the audit log after shutdown.py:1211
RUN:   read src/probos/startup/shutdown.py:1205-1214
FOUND: `_semantic_layer.stop()` (:1208), `_started = False` (:1211), a logger.info (:1212), and the
       deferred-cancellation re-raise (:1213-1214). No store, pool, agent or mesh teardown remains.
HOLDS: YES — :1211 is the last point at which an append is possible, which is why phase 2 goes there.

CLAIM: the sink itself never returns a partial batch (so holes come from the caller, not the sink)
RUN:   read `AuditLogPersistence.persist_entries`
FOUND: one `executemany` + one `commit()`; `return []` on ANY exception; otherwise every sequence.
HOLDS: YES — confirmation is all-or-nothing per batch. Non-contiguity is created upstream, by the
       drop at :372 and the skip at :416, never by the sink. This is what makes A1+A2 sufficient.
```

---

## Verified Against Codebase (2026-08-28, HEAD `7edf309e`) — revision 2's pre-build verification

Retained as the record of what the tree looked like before the rejected build. **Where it disagrees
with the staged-tree block above, the staged-tree block is authoritative.**

```
grep "entries: list\[AuditEntry\]|def append|def verify_chain|def _hash|class AuditLog|NOT wired into" src/probos/security/audit.py
  39:  class AuditLog:
  54:      entries: list[AuditEntry] = field(default_factory=list)
  67:      def append(self, *, category: str, detail: str) -> AuditEntry:
  120:     def verify_chain(self) -> bool:
  147:     def _hash(self, payload: dict[str, Any]) -> str:
  174: class AuditLogPersistence:
  183:     ``stop()`` method is defined but NOT wired into runtime shutdown in
  201:     async def start(self) -> None:
  211:     async def stop(self) -> None:
  212:     """Close the connection. NOT wired into runtime shutdown in v1

grep "_pending_writes" src/
  security/audit.py:50, 63, 116, 117      # definition + its own two writes; NO consumer

grep "audit_log_persistence|AuditLogPersistence" src/
  security/audit.py:46,58,137,138,174,209
  startup/finalize.py:3902,3904,3910,3912,3930,3941    # construction only
  ZERO hits in startup/shutdown.py                      # <-- gap 3

read src/probos/startup/shutdown.py:139-162   # _stop_runtime_sqlite_sidecars
  tuple = capability_request_store, fault_report_store, knowledge_edges,
          personal_ontology_prober, rejection_cache
  audit_log_persistence ABSENT from the one place it would belong

config.py 4340-4352 (printed verbatim):
  4343:     credential_tier_enforcement: bool = False
  4350:     audit_persistence_enabled: bool = False
  4351:     audit_persistence_filename: str = "audit_log.db"
  4352:     audit_retention_days: int = 90
  4305:     audit_enabled: bool = True

config/system.yaml 1265-1273 (printed verbatim):
  1265:   audit_enabled: true
  1271:   audit_persistence_enabled: false
  1272:   audit_persistence_filename: audit_log.db
  1273:   audit_retention_days: 90
  2118:   audit_max_entries: 1000                # clinical_telemetry — a DIFFERENT model
  2119:   audit_persistence_enabled: true        # clinical_telemetry — a DIFFERENT model

grep "audit_enabled|AuditLog\(|tamper|load_entries|attach_persistence" src/probos/startup/finalize.py
  3894: if config.security_infra.audit_enabled:
  3896:     runtime.audit_log = AuditLog(emit_event=runtime.emit_event)
  3920:     loaded = await persistence.load_entries()
  3922:     runtime.audit_log.entries.extend(loaded)
  3923:     if not runtime.audit_log.verify_chain():
  3926:         "rehydrate (tamper or corruption suspected; "
  3929:     runtime.audit_log.attach_persistence(persistence)

grep "ExecutionAuditor\(|class CodeRunnerAgent" src/probos/
  agents/code_runner.py:98:      class CodeRunnerAgent(BaseAgent):
  agents/code_runner.py:152:         self._auditor = ExecutionAuditor(self._runtime)
  tools/code_execution_tool.py:314:  self._auditor = ExecutionAuditor(runtime)
  -> TWO auditors. Revision 1's "mesh path is not audited" is FALSE at HEAD.

grep "control that makes|Swallows ``Exception``|class ExecutionAuditor|_absence_warned = True" src/probos/execution/audit.py
  76:   class ExecutionAuditor:
  120:      decoration: it is the control that makes the capability defensible
  131:      Swallows ``Exception`` from the sink -- an audit write that could fail
  140:      audit = getattr(self._runtime, "audit_log", None)
  149:          self._absence_warned = True
  190:      audit.append(

grep "best.effort|may be lost|not durable|process exit|in-memory" src/probos/execution/audit.py
  (zero hits)   # the control claim at :120 is UNHEDGED

grep "audit_log\.append|audit\.append\(" src/probos/     # shared-log consumers
  execution/audit.py:190                      # BOTH execution paths
  tools/browser/tool.py:1187                  # AD-706 browser tool
  cognitive/self_improvement/approval_gate.py:120, 152
  (counselor.py:411,485 and clinical_telemetry.py:391 are the OTHER log / other rings)

grep "5s timeout on stop|timeout=10|def drain_pending_tasks|clearance_grant_store.stop" src/probos/
  __main__.py:653:  await asyncio.wait_for(runtime.stop(reason=...), timeout=10)
  __main__.py:938:  await asyncio.wait_for(runtime.stop(), timeout=10)
  mesh/intent.py:322:  async def drain_pending_tasks(self, timeout_seconds: float = 5.0)
  shutdown.py:251:  # __main__.py enforces a 5s timeout on stop().   <-- FALSE, it is 10s
  shutdown.py:912:  await runtime.clearance_grant_store.stop()
```

### Absence Verified (2026-08-28)

```
CLAIM: nothing drains _pending_writes and nothing stops AuditLogPersistence at shutdown
RUN:   grep "audit_log_persistence|audit_log" src/probos/startup/**
       grep "audit_log_persistence|AuditLogPersistence" src/
       grep "_pending_writes" src/
       read src/probos/startup/shutdown.py:139-162   (_stop_runtime_sqlite_sidecars)
FOUND: persistence appears ONLY in finalize.py (construction). Zero hits in shutdown.py.
       _pending_writes has no consumer in src/. The sidecar-teardown tuple — the one
       place such a drain belongs — does not list it.
HOLDS: YES

CLAIM: no docstring hedges the audit record as best-effort at HEAD
RUN:   grep "best.effort|may be lost|not durable|process exit|in-memory" src/probos/execution/audit.py
FOUND: zero hits
HOLDS: YES — the issue's framing ("BF-763 ships with the docstring stating the record is
       currently best-effort") is STALE. The unhedged control claim is live at
       execution/audit.py:120, having moved there from code_execution_tool.py in AD-1280.

CLAIM: AD-1278 is allocated to this issue and unbuilt
RUN:   git log --all --format='%h %s' | grep 'AD-1278'   -> 27f76ea9 "build prompt for BF-780"
       grep "AD-1278" src/probos/security/audit.py src/probos/startup/shutdown.py -> zero hits
HOLDS: YES — prompt-only commit, no build. Number retained rather than re-minted.
```
