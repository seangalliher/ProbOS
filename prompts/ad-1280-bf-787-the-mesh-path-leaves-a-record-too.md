# AD-1280 / BF-787 (#1251): the mesh path leaves a record too

**Status:** ready to build
**Dependencies:** AD-1247 (#1244, built) · BF-763 (#1221, built) · BF-779 (#1242, built)
**Estimated tests:** ~22 new in `tests/test_ad1280_mesh_execution_audit.py`, plus 1 updated in `tests/test_ad1247_execution_audit.py`

---

## Problem

AD-1247 gave the **agentic** `run_python` path a per-execution `code_execution`
audit record. The **mesh** path — `CodeRunnerAgent`, reached through the
`run_python` / `install_package` intents — writes none.

`category="code_execution"` appears at exactly one production site:

```
src/probos/tools/code_execution_tool.py:629:                category="code_execution",
```

`src/probos/agents/code_runner.py` has no audit write at all. It has a module
docstring at lines 17–24 saying so:

```
17:  ``CodeExecutionTool`` ATTEMPTS a per-execution ``code_execution`` record when
18:  ``security_infra.audit_enabled`` is on (AD-1247). This mesh path attempts
19:  nothing.
```

The same claim is made in two more places (`config.py:3286`,
`isolation.py:60`). Those claims are true today. The moment the behaviour lands
they become false, and that is the **BF-763 defect class** — a docstring
describing a control that no longer matches the code. They must be corrected in
the **same commit**.

### Correction to the issue text

Issue #1251 says the record should key off *"the sandbox's `launch_signal` (the
`ExecutionRequest` field already exists)"*. **There is no `launch_signal`
field.** The real interface is:

```
src/probos/execution/isolation.py:125:class LaunchOutcome:
src/probos/execution/isolation.py:366:    launch_outcome: LaunchOutcome | None = None
src/probos/execution/isolation.py:607:            if request.launch_outcome is not None:
src/probos/execution/isolation.py:608:                request.launch_outcome.launched = True
src/probos/execution/isolation.py:609:                request.launch_outcome.resolved.set()
```

`LaunchOutcome` carries `launched: bool` and a `resolved: threading.Event`. Use
`ExecutionRequest.launch_outcome`. Do not go looking for `launch_signal`.

---

## The two control flows

They are different shapes, and that difference is the whole design problem.

**`CodeExecutionTool.invoke`** (`code_execution_tool.py:715`) is a long method
owning the entire lifecycle. Its audit logic is spread across three places:

| Site | Lines | Guard |
|---|---|---|
| normal path | 826–838 | after `_capture_artifacts`, sets `audit_attempted = True` first |
| `except Exception` | 874–887 | `launch.launched and not audit_attempted` |
| nested `finally` | 890–930 | waits `_LAUNCH_RESOLVE_SECONDS` on `launch.resolved`; may record `launch_state="unknown"` |

**`CodeRunnerAgent._run_python`** (`code_runner.py:206–253`) is tiny by
comparison: a `try` around one `await sandbox.run(ExecutionRequest(...))`
(lines 231–239) with a `finally` (lines 251–253) that only reaps a
non-persistent workdir.

---

## Decision 1 — EXTRACT, do not duplicate

`CodeExecutionTool._audit` (`code_execution_tool.py:537–640`) is ~100 lines
carrying eight separately-reasoned decisions:

1. `launch_state not in ("launched", "unknown")` early return
2. warn-once-per-instance absence notice when no sink is configured
3. digest-only source (`code_sha256` / `code_chars`, never the text)
4. the `_AUDIT_DETAIL_ALLOWLIST` key filter
5. `error_type` as a class name, never `str(exc)`, bounded to 80 chars
6. `artifact_count` **omitted** rather than defaulted to zero
7. `Exception` from the sink swallowed, `BaseException` deliberately not
8. the `UNCONFIRMED` warning when `append` raises

**Copying that into `code_runner.py` is the obvious move and it is the wrong
one.** It is precisely the drift risk BF-856 collapsed when it put
`error_signature` and `ToolDefect.signature` onto a shared `_digest`, on the
reasoning that *two parallel edits can drift; a shared definition cannot*. A
future security fix to any of the eight decisions above would have to land
twice, and the second landing is the one that gets forgotten. The repo's DRY
rule requires extraction when the same logic exists in 2+ places.

### Where it goes

**`src/probos/execution/audit.py`** — a new module.

Layer-safe, verified: `src/probos/execution/*.py` imports **nothing** from
`probos.tools` or `probos.agents` (enumerated below), and both
`tools/code_execution_tool.py:42` and `agents/code_runner.py:66` already import
from `probos.execution.isolation`. Adding a sibling under `execution/` creates
no cycle.

The module owns:

- `AUDIT_DETAIL_ALLOWLIST: frozenset[str]` — moved verbatim from
  `code_execution_tool.py:83–98`, including its comment.
- `LAUNCH_RESOLVE_SECONDS = 2.0` — moved verbatim from
  `code_execution_tool.py:104`, including its comment.
- `class ExecutionAuditor` with the body of `_audit` moved verbatim into a
  `record(...)` method of the identical keyword-only signature.

### Who owns the warn-once flag

Today `_audit_absence_warned` is per-`CodeExecutionTool`-instance
(`code_execution_tool.py:326`). **Keep that shape: each call site constructs
its own `ExecutionAuditor` and holds it as instance state.** Do not use a
module-level flag — module-global mutable state leaks across tests and would
make the tool's warn-once behaviour depend on whether a mesh agent had already
warned. `CodeRunnerAgent` is a long-lived registered agent, so
per-agent-instance is the exact mirror of per-tool-instance.

### `CodeExecutionTool` must be byte-identical afterwards

It is a heavily reviewed security control and this issue is **not** licence to
change it. After extraction, `CodeExecutionTool._audit` is a thin delegate to
`self._auditor.record(...)` with an unchanged signature, and every one of the
eight decisions behaves exactly as it does at HEAD.

**Required test:** `tests/test_ad1247_execution_audit.py` must pass unchanged
except for the one repair below.

### The one AD-1247 test that must be repaired, and how

`test_the_allowlist_actually_filters`
(`tests/test_ad1247_execution_audit.py:730–753`) monkeypatches the allowlist on
the tool module:

```python
import probos.tools.code_execution_tool as mod
narrowed = frozenset(_AUDIT_DETAIL_ALLOWLIST - {"code_sha256"})
monkeypatch.setattr(mod, "_AUDIT_DETAIL_ALLOWLIST", narrowed)
```

Once the filter reads the name from `execution/audit.py`, that patch stops
reaching the production read and the test fails. **Re-point the monkeypatch at
`probos.execution.audit`. Do not weaken the assertions.** Its docstring records
why it exists — *"the test has to create that situation rather than wait for
it"* — and that intent must survive verbatim in spirit. Deleting it, or
softening `assert "code_sha256" not in rec`, would pin the removal of a
security filter as contract.

`tests/test_ad1247_execution_audit.py:51` also imports
`_AUDIT_DETAIL_ALLOWLIST` from `probos.tools.code_execution_tool`. Keep a
module-level alias there re-exporting the shared name so that import still
resolves.

---

## Decision 2 — only the script run produces a record

A single `run_python` turn can reach `sandbox.run` up to **three** times:

| Call site | Lines | argv / code |
|---|---|---|
| venv create | `code_runner.py:298–304` | `[sys.executable, "-m", "venv", ...]` |
| pip install | `code_runner.py:311–322` | `[py, "-m", "pip", "install", ...]` |
| the script | `code_runner.py:231–239` | the agent's submitted `code` |

**Ruling: only the third produces a `code_execution` record.** Reasoning, which
must be recorded in the new module docstring:

- The record exists to hold an unattended agent accountable for **arbitrary
  code it authored** (Design Principle #13). The venv and pip argv are fixed
  and this codebase wrote them; the agent chose package *names*, not code.
- The record's fields are built around submitted source — `code_sha256`,
  `code_chars`. A venv-create has no source. A record whose digest is the hash
  of `""` is a false artifact in the trail.
- `install_package` runs no script at all, so it gets **no `code_execution`
  record**. Writing one would put an execution entry in the trail for something
  that executed no submitted source — the same corruption, in the opposite
  direction, that `_audit`'s `launch_state` guard already exists to prevent.

This preserves "exactly one record per execution" without needing a
de-duplication mechanism: only one of the three calls is ever audited, so
`_prepare_venv` needs no changes at all.

The package names are not lost — they already reach the generic
`intent_broadcast` rows. If the Captain later wants an install-specific record,
that is a **different category** (`package_install`) and a different issue.
**Do not build it here.**

---

## Decision 3 — `execution_id` and `agent_id` on the mesh path

**`execution_id`**: mint one per `_run_python` call with `uuid.uuid4().hex`.
`uuid` is already imported (`code_runner.py:59`). It must be 32 hex characters
— the AD-1247 test harness asserts exactly that
(`tests/test_ad1247_execution_audit.py:75`), and the new suite must assert it
too.

**`agent_id`**: use `plan["owner"]`. `_resolve_owner` (`code_runner.py:332`)
already implements exactly the right attribution — *"an explicit
`workspace_owner` in params (a delegating crew agent's key) wins; otherwise the
code-runner's own key"* — which is the mesh analogue of the agentic path's
`requesting_agent = ctx.get("agent_id")`. It names the agent **on whose behalf**
the code ran, not the executor. Do not use `self.id`.

---

## Decision 4 — the mesh path DOES need the `unknown` state

`_run_python` has no cancellation-teardown block today, so it is tempting to
say the `unknown` launch state is unreachable here. **That is false and must
not be claimed.** `handle_intent` (`code_runner.py:137`) is awaited from the
bus, so a cancelled turn unwinds straight through the `await sandbox.run(...)`
at `code_runner.py:231` and into the existing `finally` at
`code_runner.py:251`. The executor thread is *not* cancelled with it — that is
the entire premise of `LaunchOutcome` (`isolation.py:127–133`). The mesh path
reaches the same open-launch-question state the tool's `finally` handles.

So the `unknown` path is **required**, it is **new code**, and it gets AD-1247's
review scrutiny. Mirror the tool's structure at `code_execution_tool.py:890–930`:

- a bounded `launch.resolved.wait(timeout=LAUNCH_RESOLVE_SECONDS)` reached only
  when work was submitted, nothing was audited yet, and the question is open;
- record `"launched"` when `launch.launched`, `"unknown"` when the bound
  expired and the answer is still unknown, and **nothing** when the sandbox
  answered "never spawned";
- the audit block in its **own** `try/finally` so a raising sink cannot skip the
  existing workdir reap at `code_runner.py:251–253`;
- an `audit_attempted` flag set **before** each `record(...)` call, so a
  `BaseException` mid-append cannot produce a duplicate.

Do **not** introduce a `CancelCleanup` handshake here. `_run_python`'s reap is
`persistent`-gated and out of scope.

---

## Implementation

### Section 1 — `src/probos/execution/audit.py` (new)

Move `_AUDIT_DETAIL_ALLOWLIST` (`code_execution_tool.py:83–98`),
`_LAUNCH_RESOLVE_SECONDS` (`:104`) and the body of `_audit` (`:537–640`)
verbatim, renaming to `AUDIT_DETAIL_ALLOWLIST`, `LAUNCH_RESOLVE_SECONDS` and
`ExecutionAuditor.record`. Carry every comment across unchanged — they record
review findings, not explanation. Add a module docstring stating Decision 2
(what counts as an execution) and Decision 4 (why the mesh path can reach
`unknown`).

`ExecutionAuditor.__init__` takes the runtime (or the sink directly — the
builder picks, but it must read the sink through the same
`getattr(..., "audit_log", None)` shape so a runtime with the sink off behaves
identically) and owns `self._absence_warned = False`.

### Section 2 — `src/probos/tools/code_execution_tool.py` (delegate)

Import from `probos.execution.audit`. Construct `self._auditor` beside the
existing `self._audit_absence_warned` initialisation (`:326`) and drop that
flag. `_audit` becomes a delegate with an unchanged signature. Keep a
module-level `_AUDIT_DETAIL_ALLOWLIST = AUDIT_DETAIL_ALLOWLIST` alias for the
existing test import. **No behaviour change.**

### Section 3 — `src/probos/agents/code_runner.py` (the record)

Construct an `ExecutionAuditor` as agent instance state. In `_run_python`
(`:206`), mint `execution_id`, build a `LaunchOutcome`, pass it as
`launch_outcome=` on the `ExecutionRequest` at `:231`, track a monotonic start
and an `audit_attempted` flag, and add the three recording sites per Decision 4.
Do not touch `_install_package`, `_prepare_venv` or `_reap`.

### Section 4 — the docstring corrections (SAME commit)

| File | Lines | Correction |
|---|---|---|
| `agents/code_runner.py` | 17–24 | replace *"This mesh path attempts nothing"* with what it now attempts, **and** state that `install_package` and venv preparation are deliberately not recorded |
| `config.py` | 3286–3291 | replace *"The MESH path has no execution-specific record at all (BF-787)"*; keep the by-ingress detail about what else it writes, which stays true |
| `execution/isolation.py` | 58–60 | replace *"the mesh path's absence is BF-787"* with a link to AD-1280; keep the standing rule *"Do not restate their conclusions here — link them"* |

State the same "best effort under stated conditions, never an unconditional
guarantee" framing `config.py:3283–3285` already uses for the agentic path. Do
not upgrade it to a guarantee for the mesh path — the sink can still be off, and
the append can still raise.

---

## Tests

New file `tests/test_ad1280_mesh_execution_audit.py`. Reuse the `_Audit` harness
shape from `tests/test_ad1247_execution_audit.py:54–76`, **including the
validation-in-`records` trick** — `_audit` swallows `Exception`, and
`AssertionError` is an `Exception`, so a check raised inside `append` is
swallowed by production code and the guard is inert.

1. `test_a_launched_mesh_run_produces_exactly_one_record`
2. `test_a_run_that_never_starts_produces_no_record`
3. `test_a_failure_to_spawn_produces_no_record` — a real unspawnable argv, not a
   mock
4. `test_a_timed_out_run_still_counts_as_launched`
5. `test_cancellation_after_a_launched_run_is_recorded`
6. `test_cancellation_before_launch_is_not_recorded`
7. `test_an_unresolved_launch_is_recorded_as_unknown`
8. `test_a_failure_after_the_audit_does_not_add_a_second`
9. `test_installing_packages_does_not_add_a_second_record` — a `run_python` turn
   **with** `packages`, asserting exactly one record (Decision 2)
10. `test_install_package_alone_produces_no_record` (Decision 2)
11. `test_the_source_is_recorded_as_a_digest_never_as_text`
12. `test_the_digest_is_the_real_hash_and_distinguishes_scripts`
13. `test_the_record_carries_only_allowlisted_keys`
14. `test_error_type_is_a_class_name_not_an_exception_message`
15. `test_the_agent_id_is_the_delegating_owner_not_the_runner` — pass an explicit
    `workspace_owner` and assert the record names it (Decision 3)
16. `test_every_record_carries_a_32_char_execution_correlation_id`
17. `test_no_sink_does_not_fail_the_execution`
18. `test_no_sink_is_reported_not_swallowed`
19. `test_the_absence_warning_does_not_repeat`
20. `test_a_failing_sink_does_not_fail_the_execution`
21. `test_the_workdir_is_still_reaped_when_the_sink_explodes` — the ephemeral
    branch, pinning that the audit `try/finally` cannot skip the reap
22. `test_the_tool_and_the_mesh_path_share_one_record_builder` — assert both
    call sites produce structurally identical key sets for an equivalent run,
    so the extraction cannot silently fork

### Acceptance criterion 3 is the sharp one

> **Tests must distinguish queued from launched — a fake sandbox that raises
> immediately must not satisfy them.**

`sandbox.run()` only **queues**; `Popen` happens later inside the executor. A
stub that raises before any thread starts looks identical to a launched run to a
weak assertion, and AD-1247 shipped exactly that defect before review caught it.
Read these two before writing tests 3 and 5:

- `tests/test_ad1247_execution_audit.py:163` —
  `test_a_failure_to_spawn_resolves_as_not_launched`, which uses a **real**
  unspawnable path and asserts `launched is False` **and**
  `resolved.is_set() is True`.
- `tests/test_ad1247_execution_audit.py:321` —
  `test_cancellation_after_a_launched_run_is_recorded`, whose docstring records
  that an earlier version *"could not tell queued from launched and pinned the
  defect as contract."*

Assert on `LaunchOutcome` state, not on whether a mock was called.

---

## Mutation verification (required)

Run the unmutated baseline first and abort if it is already red or if every
mutant looks killed. Mutate **in place** with a `.mutbak` sibling, restore in
`finally`, **binary I/O only** — this is a CRLF tree and text-mode round-tripping
corrupts line endings. **Single-line anchors only**; a multi-line anchor
silently matches nothing, and an anchor that is not found is an **INERT** mutant,
not a killed one — say so.

Minimum set:

| # | Mutation | Must be killed by |
|---|---|---|
| M1 | drop `launch_outcome=launch` from the mesh `ExecutionRequest` | 1, 3 |
| M2 | record unconditionally instead of gating on `launched` | 2, 3 |
| M3 | remove the mesh `audit_attempted` guard | 8 |
| M4 | record `"launched"` where the code records `"unknown"` | 7 |
| M5 | audit the pip-install `sandbox.run` too | 9, 10 |
| M6 | `agent_id=self.id` instead of the owner | 15 |
| M7 | move the mesh audit outside its own `try/finally` | 21 |
| M8 | delete the allowlist filter in the shared module | 13, and the repaired AD-1247 test |

Classify a timeout banner as **INVALID, never SURVIVED** — a run that never
completed proves nothing. If a mutant survives, first check whether an earlier
branch swallows it: a mutant that cannot be reached is inert, and the survivor
may mean the *mutant* is wrong rather than the test.

---

## What this does NOT change

Explicitly out of scope. Do not build any of it:

- **No consensus gate on either path.** BF-779 (#1242) settled that a quorum
  gate is not the alternative here. Do not add one, and do not change
  `requires_consensus=True` on the intent descriptors.
- **No `package_install` audit category.** Decision 2 rules install out; a
  separate record for it is a different issue.
- **No change to `CodeExecutionTool` behaviour.** Extraction only. If you find
  yourself improving one of the eight decisions, stop — that is a new AD.
- **No `CancelCleanup` handshake in `code_runner.py`.** BF-788's workdir
  ownership problem is the tool's, and `_run_python`'s reap is
  `persistent`-gated.
- **No changes to `isolation.py` behaviour.** `LaunchOutcome` already does
  everything needed; only its docstring cross-reference changes.
- **No new config fields.** The mesh record is gated by the same existing
  `security_infra.audit_enabled` that wires `runtime.audit_log`
  (`startup/finalize.py:3761–3766`).
- **Do not regenerate** `docs/development/open-ads-report.md` or
  `docs/development/ad-ledger-snapshot.json`.

---

## Acceptance criteria

1. A launched mesh execution produces **exactly one** `code_execution` audit
   record.
2. A queued-but-never-started mesh run produces **none**.
3. Tests distinguish queued from launched — a fake sandbox that raises
   immediately does not satisfy them.
4. `CodeExecutionTool`'s audit behaviour is unchanged;
   `tests/test_ad1247_execution_audit.py` passes with only the one documented
   monkeypatch repair, and that repair does not weaken an assertion.
5. `install_package` and venv preparation produce no `code_execution` record,
   and a `run_python` turn that installs packages still produces exactly one.
6. The docstrings in `code_runner.py`, `config.py` and `isolation.py` land in
   the **same commit** as the behaviour. A grep proves no remaining text claims
   the mesh path has no record:
   ```
   rg -n "mesh path attempts nothing|no execution-specific record|mesh path's absence" src/
   ```
   must return zero hits.
7. Mutation verification run, with the M1–M8 table reported per-mutant as
   KILLED / SURVIVED / INERT / INVALID.
8. Full gate green:
   ```
   cd d:\ProbOS; $env:PROBOS_DATA_DIR="$env:TEMP\probos_gate_ad1280"; d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile
   ```
   Baseline **25,018 passed, 27 skipped**. Report the delta.
9. Adversarial review on the staged diff by a different model, findings
   addressed **before** commit.
10. **Verify all changes comply with the Engineering Principles in
    `.github/copilot-instructions.md`.**

---

## Commit

Stage explicit paths only. **Never `git add -A`.** Never stage `README.md`,
`docs/architecture/federation.md`, `docs/development/ad-ledger-snapshot.json`,
`docs/development/open-ads-report.md`, or `docs/development/roadmap.md` — all
five are modified in the working tree for unrelated reasons.

```
git add src/probos/execution/audit.py src/probos/execution/isolation.py \
        src/probos/agents/code_runner.py src/probos/tools/code_execution_tool.py \
        src/probos/config.py \
        tests/test_ad1280_mesh_execution_audit.py tests/test_ad1247_execution_audit.py
```

The commit message must **not** contain `close` / `closes` / `fixes` /
`resolves` followed by `#1251` — GitHub does not understand negation and will
close the issue. Reference it as `BF-787 (#1251)`.

---

## Verified Against Codebase (2026-08-26)

```
rg -n 'category="code_execution"' src/
  src/probos/tools/code_execution_tool.py:629:                category="code_execution",
  (one hit, whole tree)

rg -n 'launch_outcome|LaunchOutcome' src/probos/execution/isolation.py
  125:class LaunchOutcome:
  366:    launch_outcome: LaunchOutcome | None = None
  477:                if request.launch_outcome is not None:
  478:                    request.launch_outcome.resolved.set()
  607:            if request.launch_outcome is not None:
  608:                request.launch_outcome.launched = True
  609:                request.launch_outcome.resolved.set()
  (no `launch_signal` anywhere in the tree)

grep -n 'def ' src/probos/agents/code_runner.py
  137: async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
  206: async def _run_python(self, plan: dict) -> dict[str, Any]:
  256: async def _install_package(self, packages: list[str], owner: str) -> dict[str, Any]:
  284: async def _prepare_venv(
  332: def _resolve_owner(self, params: dict) -> str:
  390: async def _reap(path: Path) -> None:
  59:  import uuid                      # already present, no new import needed

grep -n 'def _audit|def invoke' src/probos/tools/code_execution_tool.py
  537: def _audit(
  715: async def invoke(
  83:  _AUDIT_DETAIL_ALLOWLIST: frozenset[str] = frozenset({
  104: _LAUNCH_RESOLVE_SECONDS = 2.0
  326:        self._audit_absence_warned = False

grep -n 'def append' src/probos/security/audit.py
  67:    def append(self, *, category: str, detail: str) -> AuditEntry:

grep -n 'audit_enabled' src/probos/startup/finalize.py
  3761:    if config.security_infra.audit_enabled:
  3763:        runtime.audit_log = AuditLog(emit_event=runtime.emit_event)
  3766:        runtime.audit_log = None
```

**Absence verified** — the layer claim, which the extract decision depends on:

```
CLAIM: nothing under src/probos/execution/ imports from tools/ or agents/,
       so a new module there creates no cycle.
RUN:   Select-String -Path src\probos\execution\*.py `
         -Pattern '^from probos\.(tools|agents)|^import probos\.(tools|agents)'
FOUND: (no matches)
HOLDS: yes — and both call sites already import from probos.execution.isolation
       (code_execution_tool.py:42, code_runner.py:66), so the dependency
       direction is already established in the direction this needs.
```

**Absence verified** — the docstring-correction inventory:

```
CLAIM: the mesh-has-no-record claim appears in exactly three files.
RUN:   rg -n "BF-787|mesh path" src/
FOUND: agents/code_runner.py:18,24 · config.py:3286 · execution/isolation.py:60
       (avatars/blender_renderer.py:132 is a 3-D "base mesh path", unrelated)
HOLDS: yes — three files, matching issue #1251's guarantee 6.
```

**AD ceiling verified** — enumerated, not read from `open-ads-report.md`
(measured 51 ADs stale on 2026-08-25):

```
git log --all --format='%s' | rg 'AD-12[5-9][0-9]'  -> ceiling AD-1279
ls prompts/ad-1*.md | tail -1                       -> ad-1279-bf-855-...md
```
