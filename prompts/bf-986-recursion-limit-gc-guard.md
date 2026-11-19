# BF-986 (#1754, GATE-F1): a test that runs to the recursion limit asks for a guard that collects garbage first and keeps the collector off while it runs; the confirmed loop leaker closes its loop

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-19

**Status:** build-ready. Issue #1754 (it stays open for its other items), item GATE-F1 (found by wave #1760). One BF number. The orchestrator enumerated BF-986 as the next free number at 03:01Z (BF-985 is in flight on a branch) and re-verifies it before the first commit (P3). The number appears only in REPLACE text, new-file text, paths of new files and tracker text, never in a SEARCH.

**Base:** `origin/main` `7ca49126` (2026-11-19). BF-985 builds first. It may touch `tests/conftest.py`, `PROGRESS.md` and `DECISIONS.md`. This contract's anchors in those files are each a single line that an insertion leaves in place; P3 checks this.

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks are LF. Match and write each file with its own line endings, and write new files LF.

**Milestones:**
- M1: the guard, its tests and its three uses (tests only, tier LOW: no `src/` line).
- M2: the confirmed leaker (one test file).
- M3: trackers.

Each milestone is one Builder delegation and one local commit, in order. After M3, run one broad gate: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-986-1754 --receipt logs/gates/bf-986-1754.receipt.json`.

**Captain:** nothing here meets a Captain condition. Tests and test fixtures only; no control is weakened.

---

## 0. Premise: what is present on this tree

| Fact | Where |
|---|---|
| The victim test builds a body 600 deep and needs `canonicalize` to raise `RecursionError` on it | `tests/test_ad1197_signed_envelopes.py:2032-2050`, `:2060-2063` |
| `canonicalize` is recursive Python and allocates a generator at each level, so collections fire inside the recursion | `src/probos/federation/ard/jcs.py:53`, `:76`, `:91`, `:112` |
| The code under test catches that `RecursionError` on both the outbound and the inbound path, so the test overflows the stack again inside the call | `src/probos/federation/envelope.py:677`, `:942`, `:948` |
| pytest's hook formats the unraisable inside `try`. On failure it appends the exception and re-raises. `collect_unraisable` (trylast in setup, call and teardown) raises `RuntimeError("Failed to process unraisable exception")` | `.venv/Lib/site-packages/_pytest/unraisableexception.py:102-140`, `:47-79`, `:151-163` |
| pytest's only own collections run at session cleanup (5 x `gc.collect()`) | same file `:31-33`, `:86-99` |
| No `src/` code calls `gc.collect/disable/enable/freeze/set_threshold` or sets `sys.unraisablehook`. Tests only call `gc.collect()`, always on a healthy stack | section AV2 |
| No `filterwarnings` in `pyproject.toml`; `asyncio_mode = "auto"`; `addopts = "-n 16 --dist=loadfile"`; markers are not strict | `pyproject.toml:180-199` |
| `tests/conftest.py` already imports a hook from `tests/fixtures/` | `tests/conftest.py:30-31` |
| The precedent for running a real pytest in a subprocess | `tests/test_timeout_timer_release.py:38-54` |
| The confirmed leaker | `tests/test_ad721h_vrm_upload.py:211` |
| CI runs CPython 3.12 on Linux with no coverage tracer | `.github/workflows/ci.yml:47`, `:110`, `:139`; section AV2 |

## 1. Problem

A collection runs the finalisers of whatever it frees on the stack of the code that triggered it. An unclosed event loop that an earlier test left in a reference cycle stays pending until a collection of its generation. If that collection lands in the last 2 to 4 frames below the recursion limit, three things follow:
1. `BaseEventLoop.__del__` raises `RecursionError`.
2. pytest's unraisable hook overflows while formatting it.
3. pytest fails the test that happened to be running.

`test_an_inbound_signed_body_too_deep_for_rfc8785_is_rejected` was that test in two gates (#1754 `issuecomment-6996601594`; log `gate-ad1361-red.log:794-921`, `object=<function BaseEventLoop.__del__>`).

The orchestrator's probe (`auto_probe2.py`, no pytest, no ProbOS) reproduces it whether the collection is explicit or automatic, with `left` 2, 3 or 4, once the probe has asserted that the loop is still alive at the limit.

A census of 29 files finds one test-code leaker (`test_ad721h_vrm_upload.py:211`) and one loop still open at session finish (`test_bf908_crew_scope_token.py:397`, cause not examined).

## 2. Solution overview

1. **A guard fixture**, `gc_quiet_at_recursion_limit`, in `tests/fixtures/recursion_limit_gc.py`, imported into `tests/conftest.py`. It runs three steps:
   - it records whether the collector is enabled;
   - it runs `gc.collect()` on a healthy stack;
   - it runs `gc.disable()`, and in teardown restores the recorded state whatever the test did, including a test that fails.
2. **Opt-in per test function** with `@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")`, on every test whose passing path overflows the **Python** stack (section 3 D3). On this tree that is three functions, 11 nodes.
3. **The confirmed leaker closes its loop** (M2).
4. **The census runs once, after the merge**, with the orchestrator's existing plugin over the whole suite. It is recorded on #1754 and ships no code (section 8.4).

Heavier designs rejected (one line each):
- An autouse collect-and-disable for every test: about 54k collections per run, to cover 11 nodes.
- Hooking or disabling pytest's unraisable plugin (`-p no:unraisableexception`): it hides every real unraisable error suite-wide, and the order forbids private hooks.
- Raising the recursion limit in the deep tests: it moves the window without removing it, and the tests exist to reach the limit.
- Running the deep part in a thread with a large stack: the Python recursion limit is per interpreter, so the window moves with it.
- Fixing only the leakers: the census is partial, and any future leaker would re-arm the hazard.
- A shipped census plugin: it patches `asyncio.base_events.BaseEventLoop.__init__/__del__` and would need its own tests, while a one-off run answers the question.

## 3. Decisions

- **D1 (where).** A helper module, `tests/fixtures/recursion_limit_gc.py`. `tests/conftest.py` imports the fixture by name, the same pattern as `timeout_timer_release` at `:31`. A nested pytest can load the module with `-p`, which the doubles need.
- **D2 (how a test asks).** An explicit `@pytest.mark.usefixtures(...)` on the test function: public, needs no marker registration, and can be found with grep. Not module-level (`test_ad1197` has hundreds of tests) and not autouse (cost).
- **D3 (which tests).** Only a test whose passing path raises `RecursionError` **through Python frames** (on purpose, or in the code it drives). An overflow by C code alone (the `json` C scanner or encoder with no Python callback on the input) is not guarded. CPython 3.12 runs the collector only at eval-breaker checks (gh-97922), so no Python finaliser runs inside a pure-C recursion; P2 asserts this. If P2 fails on the build host, the C-only rows in the table below get the guard too, with no other change.
  - Candidates: `rg -n "RecursionError|getrecursionlimit" tests -g "!test_bf986_*"`, plus `rg -n -i "too deep|deeply nested|deep nesting|recursion limit" tests`.
  - Guarded set: `rg -n 'usefixtures\("gc_quiet_at_recursion_limit"\)' tests`.

| Test (file:line) | What overflows | Stack | Exposed | Here |
|---|---|---|---|---|
| `test_ad1197...:2054` `test_a_body_too_deep_for_rfc8785_is_never_signed[sign, require]` | `_too_deep_body` -> `canonicalize`, then the outbound seal (`envelope.py:677`) | Python | yes | **M1** |
| `test_ad1197...:2060` `test_an_inbound_signed_body_too_deep_for_rfc8785_is_rejected` | the same, plus the inbound check (`envelope.py:942`, `:948`) | Python | yes (the failure) | **M1** |
| `test_bf904b...:379` `test_a_policy_that_cannot_be_read_observes_nothing_and_the_build_commits` (8 parameters; only `deep-nesting` overflows) | `yaml.safe_load` (`extensions/sealed_core.py:35`), PyYAML's pure-Python composer, depth = the recursion limit (`:389-391`) | Python | yes | **M1** (whole function, 8 collections) |
| `test_bf940_s2...:89` `test_a_mapping_nested_too_deeply_is_a_value_error_not_a_recursion_error` (the `_nested(600)` write at `:92`; `frontmatter.py:56` turns the `RecursionError` into `ValueError`); `test_bf940_s3...:228`; `test_bf940_s4...:301` via `_frontier` `:240`; `test_bf952...:652`, `:676`, `:762`, `:777-792`, `:802` | PyYAML's representer under the S2 writer; YAML readers driven to the frontier, binary searches whose high end raises | Python | yes until B5; after B5, where a test still raises (S2 most likely not: per B5's contract, its writer refuses a mapping holding 64 open collections before PyYAML recurses) | **B5** (section 3 D7, section 8.3) |
| `test_ad1198_transfer_recheck.py:689`, `:726` | `json.loads` of 50,000 `[` (`:179`) | C scanner | no | -- |
| `test_ad1299_s1a_repair_candidate.py:786` | `json.loads` deep (the comment at `:784` says "C scanner") | C | no | -- |
| `test_bf805_reply_metadata_degrade.py:152`, `:577`, `:619` | `json.dumps` of a list 20,000 deep (`:46`); `IntentBus._encoded` is plain `json.dumps` (`mesh/intent.py:2185`) | C encoder | no | -- |
| `test_ad1270f_duration_scheduler.py:724` (`duration_scheduler.py:239`); `test_bf875...:809`; `test_bf876...:359`, `:887` | `json.loads` of `"[" * 100_000`; its hooks fire on objects, constants and floats, none of which the input has (`mcp_server.py:176`) | C | no | -- |
| `test_ad1340_s2b_restore_route.py:826` | an iterative walk over 10,000 levels; it overflows only if the code regresses | none on the passing path | no | -- |
| `test_ad1357_context_manifest.py:809` | depth is bounded at 8 on this tree | none | no | -- |
| `test_ad1203...:292`, `test_ad1270f_gen_file_durations.py:741`, `test_ad1346_admission_shadow_parity.py:333`, `test_bf898...:642`, `test_ad1341_s5...:317` | a synthetic `RecursionError(...)` or a comment | none | no | -- |

- **D4 (what it cannot stop; stated in the module docstring):**
  - a finaliser fired by a reference count reaching zero inside the deep frames;
  - an explicit `gc.collect()` in the deep frames that finds garbage the test itself made after the guard ran (none today: section AV2);
  - a test that overflows without asking for the guard (R-1);
  - a C-only overflow (D3, P2).

  A collection that another thread triggers runs its finalisers on **that thread's** stack, so it is outside this window. `gc.disable()` is process-wide anyway, so it also stops automatic collections there.
- **D5 (both lines kept).** Either line alone would have stopped the observed occurrence: the loop was pending before the test, and nothing collects explicitly. Collect-first is the only line that stops an explicit collection at the limit from finalising garbage that earlier tests left. Disable is the only line that stops an automatic collection at the limit from finalising garbage made during the test (before or at the overflow). The cost is one collection; the disable is free.
- **D6 (leakers).** M2 closes `test_ad721h_vrm_upload.py:211`, using the same `try/finally: loop.close()` shape as the other hand-made loops (`test_ad1044_ard_search.py:103`, `test_ad721d_3_avatar_preview.py:270`). `test_bf908...:397`: the census found its loop held open until session finish, which means it was referenced, not pending garbage, during tests. The section 8.4 run classifies it, and a defect it shows becomes a follow-up item on #1754.
- **D7 (B5, #1801).** This contract does not edit the BF-940 or BF-952 files. After B5, every test function in them whose passing path still raises a Python-frame `RecursionError` must ask for the guard. A binary search for the limit does so by construction at its high end; moving the asserted depths 40 frames away does not remove it. The orchestrator amends B5's contract before building it:
  - add the `usefixtures` line to each such function;
  - append each to `_GUARDED` in `tests/test_bf986_recursion_limit_gc_guard.py`.
- **D8 (census).** A one-off run after the merge (section 8.4), recorded on #1754. A test leaker becomes a follow-up item on #1754; a production leaker gets its own issue.

## 4. Milestones and focused gates

Run each focused gate with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`. Stage explicit paths only; never `git add -A`. Write M1's test file first and run it on the base: every case errors at import (`tests.fixtures.recursion_limit_gc` is absent). Then add the guard, rerun, and run the section 10 rows. If a test outside these lists fails, stop and report it. Never delete or loosen a test.

| M | Files (section 7) | Focused gate |
|---|---|---|
| **M1** | 7.1 new `tests/fixtures/recursion_limit_gc.py`; 7.2 `tests/conftest.py`; 7.3 `tests/test_ad1197_signed_envelopes.py`; 7.4 `tests/test_bf904b_sealed_core_observation.py`; 7.5 new `tests/test_bf986_recursion_limit_gc_guard.py` | `tests/test_bf986_recursion_limit_gc_guard.py tests/test_ad1197_signed_envelopes.py tests/test_bf904b_sealed_core_observation.py tests/test_timeout_timer_release.py tests/test_ad1185_config_profiles.py tests/test_ad1270f_duration_scheduler.py` (the last three read `tests/conftest.py`: AV9) |
| **M2** | 7.6 `tests/test_ad721h_vrm_upload.py` | `tests/test_ad721h_vrm_upload.py`, then P5 |
| **M3** | 7.7 `PROGRESS.md`, 7.8 `DECISIONS.md`, 7.9 the ledger pair | `tests/test_ad1184_ad_ledger.py`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` |

**Expected counts** (the orchestrator measures each base and corrects):
- M1 = base + **10**: T1 to T7, plus T8 x 3. The guarded tests keep their number.
- M2 and M3 = base.
- No new skips.

**Commit messages** (each ends with `Refs #1754.` and the attribution lines):
- M1: `BF-986 M1: a test that runs to the recursion limit asks for a guard that collects first and keeps the collector off while it runs (#1754 GATE-F1)`
- M2: `BF-986 M2: the AD-721h dual-write test closes the event loop it creates (#1754 GATE-F1)`
- M3: `BF-986 M3: trackers (#1754)`

## 5. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| Fixture `gc_quiet_at_recursion_limit` | The 3 functions in section 3 D3 (11 nodes); the nested sessions in 7.5 (loaded with `-p`) | 11 full collections per run (tens to hundreds of ms each). The collector is off during those 11 nodes only |
| `tests/conftest.py` namespace (+1 name) | pytest's fixture discovery; `test_ad1185` parses `setdefault` calls only (`:1052`); `test_ad1270f_duration_scheduler.py:1090` filters hook impls by file | One more fixture; no hook added |
| The `usefixtures` marks | pytest; T8 reads `pytestmark` | -- |
| `test_ad721h...` loop | The test only | The loop is closed in the test that made it; no later test finalises it |
| New test file | The duration scheduler (no recorded duration, so it gets the mean estimate: `conftest.py:314-316`) | -- |

## 6. Tests

New file `tests/test_bf986_recursion_limit_gc_guard.py`. T1 to T6 run a **real pytest in a subprocess** (the precedent is `tests/test_timeout_timer_release.py:38-54`). The guard module is loaded with `-p`, and `-W error::pytest.PytestUnraisableExceptionWarning` is set, so a finaliser error at the limit fails its test whether or not pytest's hook managed to format it.

Each dive measures its start depth, descends with no tracked allocation (an integer countdown, so no collection is scheduled on the way down), and at the bottom asserts its own premises: its depth is `LIMIT - left`, and the loop is still alive. The loop is in a reference cycle (`loop.cycle = loop`). The dives use `left` in (2, 3, 4), the measured window.

| # | Test | Proves | On the base | Its own failing mutant |
|---|---|---|---|---|
| T1 | `test_without_the_guard_an_explicit_collection_at_the_limit_fails_the_test_on_an_earlier_tests_loop` | **Control (explicit mode).** The nested session runs with the collector off throughout (nested conftest). Test `a` leaks a loop; test `b` (unguarded) reaches the limit, asserts the loop is alive and calls `gc.collect()`. Each unguarded dive reports depth OK, alive and gone, and at least one fails with `RecursionError` | Errors at import | None: a control. It fails with "control:" if CPython no longer shows the mechanism |
| T2 | `test_the_guard_finalises_an_earlier_tests_loop_before_the_test_runs` | The same pairs, guarded. At the bottom the loop is already gone (collected in the guard's setup, on a healthy stack), and every guarded dive passes | Errors at import | G-1 (no collect-first): alive at the bottom, and the explicit collection fails the test |
| T3 | `test_without_the_guard_an_automatic_collection_at_the_limit_fails_the_test` | **Control (automatic mode)**, collector on. The dive collects (so every generation count starts at 0), makes and **holds** a loop, descends, and drops it at the bottom. It then allocates 50,000 lists, enough for about 70 young and 7 middle-generation collections. Each unguarded dive reports depth OK, alive and gone, and at least one fails with `RecursionError` | Errors at import | None: a control |
| T4 | `test_the_guard_runs_no_automatic_collection_during_the_test` | The same dives, guarded. At the bottom the loop is alive and is **not** gone after the allocation, and every guarded dive passes | Errors at import | G-2 (no disable): the automatic collection fails the test |
| T5 | `test_the_guard_restores_an_enabled_collector_after_a_failing_test` | Collector on before. A guarded test records `GC_DURING`, turns the collector off and fails. The next test records `GC_AFTER`. Expected: `GC_DURING=False`, `GC_AFTER=True`, and the guarded test failed (premise) | Errors at import | G-2, G-3, G-6 |
| T6 | `test_the_guard_restores_a_disabled_collector_after_a_failing_test` | Collector off before (nested conftest). The guarded test turns it **on** and fails. Expected: `GC_AFTER=False` | Errors at import | G-4, G-5, G-6 |
| T7 | `test_conftest_offers_the_guard_to_every_test` | `tests.conftest.gc_quiet_at_recursion_limit is recursion_limit_gc.gc_quiet_at_recursion_limit` | Errors at import | W-1 |
| T8 | `test_every_test_that_overflows_the_python_stack_asks_for_the_guard[ad1197-outbound, ad1197-inbound, bf904b-unreadable-policy]` | Each function in `_GUARDED` carries a `usefixtures` mark that names the guard | Errors at import | A-1, A-2, A-3 |

The automatic mode is why the descent and the counts matter. A loop promoted to the oldest generation during the descent would survive the young and middle collections at the bottom, and the control would not reproduce. The `gc.collect()` at the dive's start, plus a descent with no allocation, keeps the loop at most one generation old. T3's premise assertions catch any drift with a "control premise" message rather than passing silently.

## 7. The contract

### 7.1 New file: `tests/fixtures/recursion_limit_gc.py` (M1)

```python
"""BF-986 (#1754, GATE-F1): no garbage collection inside a test that runs to the recursion limit.

A collection runs the finalisers of everything it frees on the stack of the code that triggered it. In the last few
frames below the recursion limit there is no room for them. An unclosed event loop that an earlier test left in a
reference cycle raised ``RecursionError`` from ``BaseEventLoop.__del__``, pytest's unraisable hook overflowed while
formatting it, and pytest failed whichever test was running with ``Failed to process unraisable exception``.

A test whose passing path overflows the Python stack (it raises ``RecursionError`` through Python frames, on purpose
or in the code it drives) asks for this fixture with ``@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")``.
Each use costs one full collection.

What it does not stop: a finaliser fired by a reference count reaching zero inside the deep frames; an explicit
``gc.collect()`` in the deep frames that finds garbage the test itself made; a test that overflows without asking for
the fixture. A collection another thread triggers runs on that thread's stack, outside this window. An overflow by C
code alone (the ``json`` scanner or encoder) needs no guard on CPython 3.12: the collector runs only at the
interpreter's eval-breaker checks, which a pure-C recursion reaches only after it has unwound.
"""

from __future__ import annotations

import gc
from collections.abc import Iterator

import pytest

GUARD_FIXTURE = "gc_quiet_at_recursion_limit"


@pytest.fixture
def gc_quiet_at_recursion_limit() -> Iterator[None]:
    """Collect on a healthy stack, run the test with automatic collection off, then restore the collector's state."""
    was_enabled = gc.isenabled()
    gc.collect()  # on a healthy stack: finalise what earlier tests left, an unclosed event loop in a cycle among it
    gc.disable()  # and start no automatic collection while the test runs to the limit
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()
        else:
            gc.disable()  # the test may have turned it on
```

### 7.2 `tests/conftest.py` (M1)

SEARCH:
```python
from tests.fixtures.timeout_timer_release import pytest_runtest_protocol  # noqa: F401  (pytest hook)
```
REPLACE:
```python
from tests.fixtures.timeout_timer_release import pytest_runtest_protocol  # noqa: F401  (pytest hook)
from tests.fixtures.recursion_limit_gc import gc_quiet_at_recursion_limit  # noqa: F401  (fixture; BF-986, #1754)
```

### 7.3 `tests/test_ad1197_signed_envelopes.py` (M1)

SEARCH:
```python
@pytest.mark.parametrize("policy", [POLICY_SIGN, POLICY_REQUIRE])
async def test_a_body_too_deep_for_rfc8785_is_never_signed(
```
REPLACE:
```python
@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")  # BF-986 (#1754): _too_deep_body and the outbound seal overflow the Python stack
@pytest.mark.parametrize("policy", [POLICY_SIGN, POLICY_REQUIRE])
async def test_a_body_too_deep_for_rfc8785_is_never_signed(
```

SEARCH:
```python
async def test_an_inbound_signed_body_too_deep_for_rfc8785_is_rejected(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
```
REPLACE:
```python
@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")  # BF-986 (#1754): _too_deep_body and the inbound check overflow the Python stack
async def test_an_inbound_signed_body_too_deep_for_rfc8785_is_rejected(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
```

### 7.4 `tests/test_bf904b_sealed_core_observation.py` (M1)

SEARCH:
```python
@needs_git
@pytest.mark.parametrize(("kind", "text", "raised"), _UNREADABLE, ids=[case[0] for case in _UNREADABLE])
async def test_a_policy_that_cannot_be_read_observes_nothing_and_the_build_commits(
```
REPLACE:
```python
@needs_git
@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")  # BF-986 (#1754): the deep-nesting case overflows the Python stack in PyYAML
@pytest.mark.parametrize(("kind", "text", "raised"), _UNREADABLE, ids=[case[0] for case in _UNREADABLE])
async def test_a_policy_that_cannot_be_read_observes_nothing_and_the_build_commits(
```

### 7.5 New file: `tests/test_bf986_recursion_limit_gc_guard.py` (M1)

```python
"""BF-986 (#1754, GATE-F1): a test that runs to the recursion limit sees no garbage collection.

The doubles run a real pytest in a subprocess, with the guard module loaded by ``-p``. Each dive measures its start
depth and descends to ``LIMIT - left`` frames with no tracked allocation, so no collection is scheduled on the way
down. At the bottom it records its own premises (the depth, and whether the loop is still alive), because a
collection that fires early in the descent finalises the loop with a full stack and proves nothing.

- Explicit mode: automatic collection is off for the whole nested session, so a loop leaked by one test is still
  pending when the next test calls ``gc.collect()`` at the limit. Only the guard's collect-first stops that.
- Automatic mode: the dive holds its loop until the bottom, drops it there and allocates until the collector runs.
  Only the guard's disable stops that.
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from tests.fixtures import recursion_limit_gc as guard

REPO_ROOT = Path(__file__).resolve().parent.parent
_LEFTS = (2, 3, 4)  # frames left below the limit at the bottom: the window the GATE-F1 probe measured
_DIVE = re.compile(r"DIVE (\w+) (\d+) depth_ok=(\w+) alive=(\w+) gone=(\w+)")

_COMMON = '''
import asyncio
import gc
import sys
import weakref

import pytest

LIMIT = sys.getrecursionlimit()
GUARD = "gc_quiet_at_recursion_limit"
WEAK = {}
HELD = []


def _frames():
    count, frame = 0, sys._getframe()
    while frame is not None:
        count, frame = count + 1, frame.f_back
    return count


def _depth_of_caller():
    # The caller's depth (outermost frame = 1), found by sys._getframe, which builds one frame object per probe.
    low, high = 1, LIMIT + 100
    while low < high:
        mid = (low + high + 1) // 2
        try:
            sys._getframe(mid)
        except ValueError:
            high = mid - 1
        else:
            low = mid
    return low


def _descend(levels, at_bottom):
    # No tracked allocation per level, so no collection is scheduled on the way down.
    if levels > 0:
        return _descend(levels - 1, at_bottom)
    return at_bottom()


def _leak():
    loop = asyncio.new_event_loop()
    loop.cycle = loop  # only a collection frees it, and its __del__ runs wherever that collection runs
    return loop
'''

_EXPLICIT_PAIR = '''

def test_{tag}_{left}_a_leak():
    WEAK[("{tag}", {left})] = weakref.ref(_leak())


{decorator}
def test_{tag}_{left}_b_dive():
    ref = WEAK[("{tag}", {left})]
    start = _frames() - 1
    state = {{}}

    def at_bottom():
        state["depth"] = _depth_of_caller()
        state["alive"] = ref() is not None
        gc.collect()
        state["gone"] = ref() is None

    _descend(LIMIT - {left} - start - 2, at_bottom)
    print("\\nDIVE {tag} {left} depth_ok=%s alive=%s gone=%s" % (state["depth"] == LIMIT - {left}, state["alive"], state["gone"]), flush=True)
'''

_AUTOMATIC_DIVE = '''

{decorator}
def test_{tag}_{left}_dive():
    start = _frames() - 1
    gc.collect()  # every generation count starts at zero, so the loop below is at most one generation old at the bottom
    HELD.append(_leak())
    ref = weakref.ref(HELD[0])
    state = {{}}

    def at_bottom():
        state["depth"] = _depth_of_caller()
        state["alive"] = ref() is not None
        HELD.clear()  # garbage from here on
        keep = []
        for _ in range(50_000):  # about 70 young and 7 middle-generation collections when the collector is on
            keep.append([])
        state["gone"] = ref() is None

    _descend(LIMIT - {left} - start - 2, at_bottom)
    HELD.clear()
    print("\\nDIVE {tag} {left} depth_ok=%s alive=%s gone=%s" % (state["depth"] == LIMIT - {left}, state["alive"], state["gone"]), flush=True)
'''

_RESTORE = '''
import gc

import pytest


@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")
def test_1_guarded_toggles_the_collector_and_fails():
    print("\\nGC_DURING=%s" % gc.isenabled(), flush=True)
    {toggle}
    assert False, "fails on purpose: the guard restores the collector after a failing test too"


def test_2_after():
    print("\\nGC_AFTER=%s" % gc.isenabled(), flush=True)
'''

_GUARDED = (  # every test function whose passing path overflows the Python stack (contract section 3 D3; B5 appends its own)
    ("tests.test_ad1197_signed_envelopes", "test_a_body_too_deep_for_rfc8785_is_never_signed"),
    ("tests.test_ad1197_signed_envelopes", "test_an_inbound_signed_body_too_deep_for_rfc8785_is_rejected"),
    ("tests.test_bf904b_sealed_core_observation", "test_a_policy_that_cannot_be_read_observes_nothing_and_the_build_commits"),
)


def _run(tmp: Path, source: str, *, collector_off: bool) -> tuple[str, dict[str, Any]]:
    (tmp / "test_nested.py").write_text(source, encoding="utf-8")
    if collector_off:
        (tmp / "conftest.py").write_text("import gc\n\ngc.disable()  # nothing collects between tests\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_XDIST", "PYTEST_CURRENT"))}
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT), env.get("PYTHONPATH", "")])
    report = tmp / "report.xml"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "test_nested.py", "-q", "-s", "-n", "0", "-p", "no:cacheprovider",
         "-p", "no:randomly", "-o", "addopts=", "-o", "timeout=120", "-o", "timeout_method=thread",
         "-p", "tests.fixtures.recursion_limit_gc", "-W", "error::pytest.PytestUnraisableExceptionWarning",
         "--junitxml", str(report), "--rootdir", str(tmp)],
        cwd=tmp, env=env, capture_output=True, text=True, timeout=300, check=False,
    )
    output = completed.stdout + completed.stderr
    assert report.exists(), output
    cases = {case.get("name"): case for case in ET.parse(report).getroot().iter("testcase")}
    return output, cases


def _failure(case: Any) -> str | None:
    for child in case:
        if child.tag in ("failure", "error"):
            return (child.get("message") or "") + "\n" + (child.text or "")
    return None


def _dives(output: str) -> dict[tuple[str, int], dict[str, bool]]:
    return {
        (tag, int(left)): {"depth_ok": depth_ok == "True", "alive": alive == "True", "gone": gone == "True"}
        for tag, left, depth_ok, alive, gone in _DIVE.findall(output)
    }


def _source(template: str) -> str:
    return _COMMON + "".join(
        template.format(tag=tag, left=left, decorator=decorator)
        for tag, decorator in (("control", ""), ("guarded", "@pytest.mark.usefixtures(GUARD)"))
        for left in _LEFTS
    )


@pytest.fixture(scope="module")
def explicit_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, dict[str, Any]]:
    return _run(tmp_path_factory.mktemp("explicit"), _source(_EXPLICIT_PAIR), collector_off=True)


@pytest.fixture(scope="module")
def automatic_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, dict[str, Any]]:
    return _run(tmp_path_factory.mktemp("automatic"), _source(_AUTOMATIC_DIVE), collector_off=False)


def _assert_control(output: str, cases: dict[str, Any], dive_name: str) -> None:
    dives = _dives(output)
    for left in _LEFTS:
        assert dives.get(("control", left)) == {"depth_ok": True, "alive": True, "gone": True}, (
            f"control premise at {left} frames from the limit: {dives.get(('control', left))}\n{output}"
        )
    failures = [_failure(cases[dive_name.format(left=left)]) for left in _LEFTS]
    assert any(failure and "RecursionError" in failure for failure in failures), (
        "control: no collection at the limit failed its test, so the guard has nothing left to prevent\n" + output
    )


def test_without_the_guard_an_explicit_collection_at_the_limit_fails_the_test_on_an_earlier_tests_loop(
    explicit_run: tuple[str, dict[str, Any]],
) -> None:
    _assert_control(*explicit_run, "test_control_{left}_b_dive")


def test_the_guard_finalises_an_earlier_tests_loop_before_the_test_runs(explicit_run: tuple[str, dict[str, Any]]) -> None:
    output, cases = explicit_run
    dives = _dives(output)
    for left in _LEFTS:
        assert dives.get(("guarded", left)) == {"depth_ok": True, "alive": False, "gone": True}, (
            f"the guard must collect the earlier test's loop before the dive ({left} frames): {dives.get(('guarded', left))}\n{output}"
        )
        assert _failure(cases[f"test_guarded_{left}_b_dive"]) is None, output


def test_without_the_guard_an_automatic_collection_at_the_limit_fails_the_test(
    automatic_run: tuple[str, dict[str, Any]],
) -> None:
    _assert_control(*automatic_run, "test_control_{left}_dive")


def test_the_guard_runs_no_automatic_collection_during_the_test(automatic_run: tuple[str, dict[str, Any]]) -> None:
    output, cases = automatic_run
    dives = _dives(output)
    for left in _LEFTS:
        assert dives.get(("guarded", left)) == {"depth_ok": True, "alive": True, "gone": False}, (
            f"no automatic collection may run at the limit under the guard ({left} frames): {dives.get(('guarded', left))}\n{output}"
        )
        assert _failure(cases[f"test_guarded_{left}_dive"]) is None, output


def _restore(tmp: Path, *, prior_enabled: bool) -> tuple[str, dict[str, Any], list[str], list[str]]:
    toggle = "gc.disable()" if prior_enabled else "gc.enable()"
    output, cases = _run(tmp, _RESTORE.format(toggle=toggle), collector_off=not prior_enabled)
    return output, cases, re.findall(r"GC_DURING=(\w+)", output), re.findall(r"GC_AFTER=(\w+)", output)


def test_the_guard_restores_an_enabled_collector_after_a_failing_test(tmp_path: Path) -> None:
    output, cases, during, after = _restore(tmp_path, prior_enabled=True)
    assert _failure(cases["test_1_guarded_toggles_the_collector_and_fails"]) is not None, "premise: it failed\n" + output
    assert during == ["False"], output
    assert after == ["True"], output


def test_the_guard_restores_a_disabled_collector_after_a_failing_test(tmp_path: Path) -> None:
    output, cases, during, after = _restore(tmp_path, prior_enabled=False)
    assert _failure(cases["test_1_guarded_toggles_the_collector_and_fails"]) is not None, "premise: it failed\n" + output
    assert during == ["False"], output
    assert after == ["False"], output


def test_conftest_offers_the_guard_to_every_test() -> None:
    from tests import conftest

    assert conftest.gc_quiet_at_recursion_limit is guard.gc_quiet_at_recursion_limit


@pytest.mark.parametrize(
    ("module", "name"), _GUARDED, ids=["ad1197-outbound", "ad1197-inbound", "bf904b-unreadable-policy"],
)
def test_every_test_that_overflows_the_python_stack_asks_for_the_guard(module: str, name: str) -> None:
    function = getattr(importlib.import_module(module), name)
    marks = [mark for mark in getattr(function, "pytestmark", []) if mark.name == "usefixtures"]
    assert any(guard.GUARD_FIXTURE in mark.args for mark in marks), f"{module}::{name} runs to the recursion limit without the guard"
```

### 7.6 `tests/test_ad721h_vrm_upload.py` (M2)

SEARCH:
```python
    store = _chat._get_attachment_store(runtime)
    stored = asyncio.new_event_loop().run_until_complete(store.read(sha))
    named = (tmp_path / "avatars" / "agent-007.vrm").read_bytes()
```
REPLACE:
```python
    store = _chat._get_attachment_store(runtime)
    loop = asyncio.new_event_loop()  # BF-986 (#1754): closed here; left open, a later test finalised it
    try:
        stored = loop.run_until_complete(store.read(sha))
    finally:
        loop.close()
    named = (tmp_path / "avatars" / "agent-007.vrm").read_bytes()
```

### 7.7 `PROGRESS.md` (M3)

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-986 (DATE), #1754 GATE-F1 -- a test that runs to the recursion limit asks for a guard that collects garbage first and keeps the collector off while it runs.** A collection that landed in the last 2 to 4 frames below the recursion limit finalised an unclosed event loop that an earlier test had left in a reference cycle. `BaseEventLoop.__del__` raised `RecursionError`, pytest's unraisable hook overflowed while formatting it, and pytest failed the running test (`test_an_inbound_signed_body_too_deep_for_rfc8785_is_rejected`, two gates). New fixture `gc_quiet_at_recursion_limit` (`tests/fixtures/recursion_limit_gc.py`, imported by `tests/conftest.py`): it collects on a healthy stack, disables automatic collection and restores the prior state in teardown. Three test functions whose passing path overflows the Python stack ask for it with `usefixtures`: the two `_too_deep_body` tests in `test_ad1197_signed_envelopes.py` and the unreadable-policy test in `test_bf904b_sealed_core_observation.py`. Tests in the BF-940 and BF-952 files also overflow through Python frames today (the S2 too-deep mapping, the S3 and S4 frontier tests and the BF-952 binary searches); they stay unguarded until B5 (#1801) edits those files and guards each that still overflows. These lists came from a grep, which cannot see a test whose overflow the code under test converts into another error; a one-off census after the merge records every Python-frame `RecursionError` near the limit, and its list on #1754 decides any further guard. Overflows in C code alone (the `json` scanner and encoder) are not guarded, because CPython 3.12 collects only at eval-breaker checks. `test_ad721h_vrm_upload.py` now closes the loop it creates. New `tests/test_bf986_recursion_limit_gc_guard.py` runs real nested pytest sessions: two controls reproduce the failure (an explicit and an automatic collection at the limit), and four doubles between them kill the removal of every guard line. Contract `prompts/bf-986-recursion-limit-gc-guard.md`.
```

### 7.8 `DECISIONS.md` (M3)

SEARCH:
```markdown
### BF-983 -- #1676: an AD-594 consultation reaches the LLM, the AD-1152 golden's refresh rule, a config reference section per path (2026-11-18, #1676)
```
REPLACE:
```markdown
### BF-986 -- #1754 GATE-F1: a test at the recursion limit runs with the collector quiet; the census of loop leakers runs once (DATE, #1754)

- *The guard.* An explicit fixture, `gc_quiet_at_recursion_limit`, requested with `usefixtures` by each test whose passing path raises `RecursionError` through Python frames. It collects first, then disables automatic collection, then restores the prior state. Collect-first is the only line that stops an explicit collection at the limit from finalising garbage that earlier tests left, and disable is the only line that stops an automatic collection there from finalising garbage made during the test. Rejected: autouse for every test (about 54k collections a run, for 11 nodes); hooking or disabling pytest's unraisable plugin (it hides real errors); raising the recursion limit (moves the window); fixing only the leakers (the census is partial).
- *Selection.* A test asks for the guard when its passing path raises `RecursionError` through Python frames. Overflows in C code alone are not guarded: CPython 3.12 runs the collector only at eval-breaker checks, which a pure-C recursion reaches only after unwinding (gh-97922). Revisit on an interpreter change. Deferred: the tests in the BF-940 and BF-952 files that overflow through Python frames today, among them `test_bf940_s2_dump_frontmatter.py`'s too-deep mapping (found in review), stay unguarded until B5 (#1801), which edits those files and guards each that still overflows. The first inventory came from a grep, which misses a test whose overflow the code under test converts into another error; the post-merge census adds a `sys.monitoring` record of every Python-frame `RecursionError` near the limit, and its list on #1754 is the inventory of record.
- *Census.* One whole-suite run after the merge, with the orchestrator's loop-census plugin and a RAISE census of Python-frame recursion overflows, recorded on #1754. No plugin ships. A test leaker becomes a follow-up item on #1754; a production leaker gets its own issue.
- *Reading the next occurrence.* In a guarded test: a finaliser the guard cannot stop (garbage made inside the test, or a reference-count drop); the log's `object=` names it. In an unguarded test: that test overflows and needs the guard. With no deep test in the run: a different mechanism, filed as a new item.
- *Reversal.* Revert the commits: the three tests run with the collector on, and the AD-721h test leaks its loop again.

### BF-983 -- #1676: an AD-594 consultation reaches the LLM, the AD-1152 golden's refresh rule, a config reference section per path (2026-11-18, #1676)
```

### 7.9 Generated: the ledger pair (M3)

After 7.7 and 7.8, run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`. It regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`, which go in M3's commit; do not paste them. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`. Set DATE to the commit date. **`roadmap.md`:** no row, because the Bug Tracker lists only bugs deliberately not fixed.

## 8. Issue closure (the orchestrator posts these; nothing here edits GitHub)

### 8.1 Tick on #1754 (after section 8.4 is posted)
In #1754's body, change `- [ ] [#1760] **GATE-F1` to `- [x] [#1760] **GATE-F1`, and append to the end of that item:
` **Fixed (BF-986, PR #...):** guard \`gc_quiet_at_recursion_limit\` (collect, collector off, restore) on the three test functions found before the census (the BF-940 and BF-952 tests follow with B5, and census rows with their follow-up items); \`test_ad721h_vrm_upload.py:211\` closes its loop; whole-suite loop census recorded (comment linked).`

### 8.2 Comment on #1754 (at merge)
> GATE-F1 fixed by BF-986 (PR #...). The mechanism: a collection in the last 2 to 4 frames below the recursion limit finalised an unclosed event loop that an earlier test left in a cycle; `BaseEventLoop.__del__` raised `RecursionError`, and pytest's hook overflowed formatting it. Tests that sit at the limit now ask for `gc_quiet_at_recursion_limit`, which collects on a healthy stack and keeps the collector off for the test (11 nodes today; the BF-940 and BF-952 tests join when B5 lands, and any other test the census finds joins through a follow-up item). The confirmed leaker, `test_ad721h_vrm_upload.py:211`, closes its loop. Evidence before the merge: the standalone probe, and nested-pytest doubles that reproduce both the explicit and the automatic collection at the limit and show that each guard line stops its own case. Only gates show the absence of recurrence. A recurrence in a guarded test, in an unguarded one, or with no deep test in the run means three different things (DECISIONS, BF-986).

### 8.3 B5 amendment (orchestrator, before building #1801)
Input: the section 8.4 RAISE census rows for the BF-940 and BF-952 files, among them `test_bf940_s2_dump_frontmatter.py::test_a_mapping_nested_too_deeply_is_a_value_error_not_a_recursion_error` (found in BF-986 review round 1; B5's change to that test most likely ends its overflow). On B5's built tree, rerun the RAISE census over the BF-940 and BF-952 files alone. Add `@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")` to every test function it still records, append each to `_GUARDED` in `tests/test_bf986_recursion_limit_gc_guard.py` with an id, and update the T8 pins to the new function and node counts. A census row outside the BF-940 and BF-952 files is not B5's: it becomes a follow-up item on #1754.

### 8.4 The census (one-off, after the merge)
Run the orchestrator's `census_plugin.py` over the whole suite once (canonical flags, `-p census_plugin`, `CENSUS_OUT` set, an empty redirected home), and post the leak records on #1754. For each record, give the creating test, the test running when the loop was finalised, and the phase. Classify `test_bf908...:397` from the run: a loop that stays referenced until session finish is not pending garbage during tests.

In the same run, record every `RecursionError` that passes through Python frames near the limit. Register a `sys.monitoring` RAISE callback on a free tool id. When the raised exception is a `RecursionError`, the callback counts the Python frames of the current stack (iteratively, with no allocation beyond a counter) and keeps, per pytest node id, the deepest count and `sys.getrecursionlimit()`. A row is a node whose deepest count is within 50 of the limit; a C-only overflow surfaces at a shallow Python frame and is not a row. Write the rows per xdist worker, with the same output convention as the loop records. Post the rows on #1754 with the guarded set (`rg -n 'usefixtures\("gc_quiet_at_recursion_limit"\)' tests`) beside them. Every row is either guarded, a BF-940 or BF-952 test (section 8.3), or a follow-up item on #1754. No plugin ships, and the census is not a gate.

## 9. What this does NOT change

- No `src/` file. No config field, `EventType`, route, table or flag.
- pytest's unraisable plugin, `pyproject.toml` (`addopts`, markers, no `filterwarnings`), the recursion limit, the duration scheduler and `scripts/ci_shards.py`.
- The bodies of the three guarded tests, and every other test in their files.
- The BF-940 and BF-952 test files (B5 owns them, section 8.3). The C-only overflow tests (section 3 D3).
- `test_bf908_crew_scope_token.py` (section 8.4).

## 10. Mutation rows (one campaign on the M1 tree; restore between rows; run only the listed killers)

The killers in `tests/test_bf986_recursion_limit_gc_guard.py` start nested sessions that import the mutated module from this checkout.

| # | M | File | Line (stripped, once in its file after section 7) | Mutate to | Killed by |
|---|---|---|---|---|---|
| G-1 | M1 | `tests/fixtures/recursion_limit_gc.py` | `gc.collect()  # on a healthy stack: finalise what earlier tests left, an unclosed event loop in a cycle among it` | `pass` | T2 |
| G-2 | M1 | same | `gc.disable()  # and start no automatic collection while the test runs to the limit` | `pass` | T4, T5 |
| G-3 | M1 | same | `was_enabled = gc.isenabled()` | `was_enabled = False` | T5 |
| G-4 | M1 | same | `if was_enabled:` | `if True:` | T6 |
| G-5 | M1 | same | `gc.disable()  # the test may have turned it on` | `pass` | T6 |
| G-6 | M1 | same | `finally:` (and its four-line body) | `pass` (no restore) | T5, T6 |
| W-1 | M1 | `tests/conftest.py` | `from tests.fixtures.recursion_limit_gc import gc_quiet_at_recursion_limit  # noqa: F401  (fixture; BF-986, #1754)` | delete | T7 (and the 11 guarded nodes error: fixture not found) |
| A-1 | M1 | `tests/test_ad1197_signed_envelopes.py` | `@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")  # BF-986 (#1754): _too_deep_body and the outbound seal overflow the Python stack` | delete | T8[ad1197-outbound] |
| A-2 | M1 | same | `@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")  # BF-986 (#1754): _too_deep_body and the inbound check overflow the Python stack` | delete | T8[ad1197-inbound] |
| A-3 | M1 | `tests/test_bf904b_sealed_core_observation.py` | `@pytest.mark.usefixtures("gc_quiet_at_recursion_limit")  # BF-986 (#1754): the deep-nesting case overflows the Python stack in PyYAML` | delete | T8[bf904b-unreadable-policy] |

G-6 for clarity: replace `try:` ... `gc.disable()  # the test may have turned it on` with a bare `yield`. No row for M2's `loop.close()`. Its evidence is P5, the census plugin on that file: one leak before M2, none after. T1 and T3 are controls; their failure means CPython no longer shows the mechanism, not that a guard line is missing.

## 11. Verified Against Codebase (2026-11-19, `7ca49126`)

```
grep -n "_DEEP = 600|def _too_deep_body|canonicalize(body)|except RecursionError" tests/test_ad1197_signed_envelopes.py
  2032: _DEEP = 600
  2035: def _too_deep_body() -> dict[str, Any]:
  2047:     canonicalize(body)
  2048:     except RecursionError:
grep -n "parametrize(\"policy\", \[POLICY_SIGN, POLICY_REQUIRE\])" tests/test_ad1197_signed_envelopes.py
  2053: @pytest.mark.parametrize("policy", [POLICY_SIGN, POLICY_REQUIRE])
  2054: async def test_a_body_too_deep_for_rfc8785_is_never_signed(
  2060: async def test_an_inbound_signed_body_too_deep_for_rfc8785_is_rejected(
  52: from probos.federation.ard.jcs import canonicalize
grep -n "def canonicalize|def _serialize|_serialize(item) for|_serialize(v)" src/probos/federation/ard/jcs.py
  53, 76, 91, 112
grep -n "except (ValueError, RecursionError)" src/probos/federation/envelope.py
  677, 942, 948
grep -n "needs_git|parametrize((\"kind\"|deep-nesting|getrecursionlimit" tests/test_bf904b_sealed_core_observation.py
  45: needs_git = pytest.mark.skipif(...)
  363: ("deep-nesting", b"", "RecursionError"),
  377-379: @needs_git / @pytest.mark.parametrize(("kind", "text", "raised"), _UNREADABLE, ...) / async def test_a_policy_that_cannot_be_read_...
  390: depth = sys.getrecursionlimit()
grep -n "import yaml|yaml.safe_load" src/probos/extensions/sealed_core.py
  15: import yaml
  35: raw = yaml.safe_load(target.read_text(encoding="utf-8"))
grep -n "new_event_loop|_get_attachment_store(runtime)" tests/test_ad721h_vrm_upload.py
  210: store = _chat._get_attachment_store(runtime)
  211: stored = asyncio.new_event_loop().run_until_complete(store.read(sha))
grep -n "async def test_keyring_step_a_keyring_that_does_not_answer" tests/test_bf908_crew_scope_token.py
  397
grep -n "^from tests.fixtures" tests/conftest.py
  30: from tests.fixtures.abortive_self_pipe import install_abortive_self_pipe
  31: from tests.fixtures.timeout_timer_release import pytest_runtest_protocol  # noqa: F401  (pytest hook)
grep -n "asyncio_mode|addopts|markers|filterwarnings" pyproject.toml
  181: asyncio_mode = "auto"   196: addopts = "-n 16 --dist=loadfile"   197: markers = [   (no filterwarnings)
grep -n "def unraisable_hook|def collect_unraisable|trylast|gc_collect_harder" .venv/Lib/site-packages/_pytest/unraisableexception.py
  31, 47, 94, 102, 151, 156, 161
grep -n "subprocess.run|-o\", \"addopts=" tests/test_timeout_timer_release.py
  45-49
grep -n "^# ProbOS Progress" PROGRESS.md            1
grep -n "^### BF-983 -- #1676" DECISIONS.md         1703
C-only rows: test_ad1198_transfer_recheck.py:179, :689-690, :726-727; test_ad1299_s1a_repair_candidate.py:784-787;
  test_bf805_reply_metadata_degrade.py:46, :149-154, :577; src/probos/mesh/intent.py:2185 (json.dumps(payload));
  test_ad1270f_duration_scheduler.py:724; tests/fixtures/duration_scheduler.py:232-240; src/probos/federation/mcp_server.py:176;
  test_bf875_mcp_inbound_auth.py:809, :970; test_bf876_a2a_inbound_auth.py:359, :887
No-overflow rows: test_ad1340_s2b_restore_route.py:823-832; test_ad1357_context_manifest.py:809-820
B5 rows: test_bf940_s3_route_serialisation.py:228-231; test_bf940_s4_unparsed_frontmatter.py:240, :256, :301;
  test_bf952_records_keyword_search.py:652, :676, :762, :777-785, :792, :802
CI: .github/workflows/ci.yml:47, :110, :139 python-version '3.12'
```

## Absence Verified (2026-11-19)

| Claim | Run | Found | Holds |
|---|---|---|---|
| AV1. No guard module or test file exists yet | Glob `tests/{fixtures/recursion_limit_gc.py,test_bf986*.py}` | nothing | yes |
| AV2. Nothing in `src/` or `tests/` disables, enables, freezes or tunes the collector, or sets `sys.unraisablehook`; tests only call `gc.collect()` | `rg -n "gc\.(collect\|disable\|enable\|freeze\|set_threshold)\(\|unraisablehook" src tests` | 25 `gc.collect()` hits, all in `tests/` (e.g. `test_ad1198_fork_resolution.py:1480`); none in `src/` | yes |
| AV3. No coverage tracer in CI (a tracer would allocate during the descent) | `rg -- "--cov\|coverage run\|PYTHONTRACEMALLOC\|-X dev" .github/workflows` | nothing | yes |
| AV4. No BF-985+ number in git subjects or prompt files on this tree; no issue titled BF-986 | `git log --all -i --grep="BF-98[4-9]"`; Glob `prompts/**/bf-98[4-9]*`; `gh issue list --state all --search "BF-986 in:title"` | nothing; nothing; `[]` (BF-985 is on the orchestrator's branch) | yes |
| AV5. No `filterwarnings` setting | `rg -n filterwarnings pyproject.toml` | nothing | yes |
| AV6. The candidate enumeration for D3 | `rg -n "RecursionError" tests` plus the deep-nesting grep | the rows of section 3 D3. Amended (A3): this is a candidate list, not an inventory. The grep finds only tests that name `RecursionError` or the phrases. It missed `test_bf940_s2_dump_frontmatter.py:89` (found in review round 1), whose overflow `frontmatter.py:56` converts into `ValueError`. About 30 `except` clauses in `src/` catch `RecursionError` (`rg -n RecursionError src`), so other tests may reach the limit the same way unseen. The section 8.4 RAISE census is the enumeration of record | grep: yes; completeness: no |
| AV7. No other hand-made loop in the vrm file | `rg -n "new_event_loop" tests/test_ad721h_vrm_upload.py` | `:211` only | yes |
| AV8. `tests/__init__.py` and `tests/fixtures/__init__.py` are empty (the nested `-p tests.fixtures...` import is light) | `wc -c` | 0, 0 | yes |
| AV9. Tests that read `tests/conftest.py` | `rg -n "conftest.py" tests` | `test_ad1185_config_profiles.py:182`, `:1052`, `:1147`; `test_ad1270f_duration_scheduler.py:48`, `:1090` (others write their own) | yes |

## 12. Deterministic checks, resolved up front

| Check | Result |
|---|---|
| SRP | One fixture with one job; the test file holds only doubles and pins |
| Layer | No `src/` import in the guard; the test imports `tests.fixtures` and two test modules (T8) |
| Phantom precheck | New names: `GUARD_FIXTURE`, `gc_quiet_at_recursion_limit`, `_LEFTS`, `_DIVE`, `_COMMON`, `_EXPLICIT_PAIR`, `_AUTOMATIC_DIVE`, `_RESTORE`, `_GUARDED`, `_run`, `_failure`, `_dives`, `_source`, `_assert_control`, `_restore`, `explicit_run`, `automatic_run`, T1 to T8. Every other name is in section 11 |
| API check | Public only: `gc.isenabled/collect/enable/disable`, `pytest.fixture`, `pytest.mark.usefixtures`, `-p`, `-W`, `--junitxml`, `sys._getframe` (inside the nested doubles only) |
| Hidden pins | AV9 readers (no hook added, no `setdefault` changed); BF-326 janitor unaffected; `install_abortive_self_pipe` is not loaded in the nested sessions (their conftest is the nested one) |
| Unowned tasks, config, store, event | None |

## 13. Prior art and blind spots

- **External:**
  - CPython gh-97922: from 3.12 the collector runs only at eval-breaker checks. Adopted as the basis of D3 and verified by P2 ([checkin](https://www.python.org/pipermail/python-checkins/2022-October/179329.html)).
  - pytest's unraisable plugin collects 5 times at session cleanup, a constant from Trio ("a single collection doesn't necessarily collect everything"). Considered for the guard and rejected: one collection frees a loop's cycle, and the doubles prove it (T2).
  - pytest's own `test_unraisableexception.py` forces "Failed to process unraisable exception" by making `format_exception` fail, which confirms the signature's source ([source](https://sources.debian.org/src/pytest/9.0.2-2/testing/test_unraisableexception.py)).
- **Internal:** BF-985's I1-I3 nested-pytest doubles, and `tests/test_timeout_timer_release.py:38-54` (adopted). `docs/research/reference-projects.md` was not consulted: this is test-harness plumbing whose prior art is CPython and pytest themselves.
- **Blind spots found:**
  1. The probe caution (an early collection in the descent invalidates a double): the doubles descend with no allocation and assert their premises (section 6).
  2. A guard that collects but does not disable misses garbage made during the test; one that disables but does not collect misses an explicit collection. Hence D5, with one double per line.
  3. Generation promotion can make an automatic double vacuous: the dive collects first and allocates 50,000 lists.
  4. Restore after a **failing** test, from either prior state (T5, T6).
  5. B5's binary searches overflow by construction (D7, section 8.3).
  6. C-only overflows look exposed but are not on 3.12 (D3, P2, R-2).
  7. Another thread's collection is outside the window (D4).

## 14. Diff Reviewer: properties to verify

1. The fixture records `gc.isenabled()` before anything else, then calls `gc.collect()`, then `gc.disable()`, then yields. On teardown it restores exactly the recorded state, whether the test passed, failed or toggled the collector.
2. The fixture uses only public `gc` and pytest APIs. Nothing touches `sys.unraisablehook`, `_pytest` internals or the warnings filters.
3. `tests/conftest.py` gains exactly one import line and no hook; no autouse fixture is added.
4. The `usefixtures` lines sit on exactly the three functions of section 3 D3, and each one's passing path raises a Python-frame `RecursionError`. No BF-940 or BF-952 file is touched.
5. Each nested dive asserts its depth and the loop's liveness at the bottom, and its descent allocates nothing tracked. Each control (T1, T3) asserts at least one `RecursionError` failure and all premises, and fails loudly ("control:") otherwise.
6. T2 kills G-1 and T4 kills G-2 by the mechanism, not by an incidental assertion. T5 and T6 cover both prior states with a failing guarded test.
7. Every guarded dive passes, and no guarded dive's outcome depends on the test order beyond the stated pairs.
8. The nested sessions use `-o addopts=`, `-n 0`, an environment without `PYTEST_XDIST*`, and a `PYTHONPATH` led by this checkout.
9. M2 changes only the loop's lifetime in one test (create, use, close in `finally`); its assertion is unchanged.
10. Trackers: one PROGRESS entry and one DECISIONS entry, plus the ledger pair regenerated by script.

## 15. Acceptance criteria

1. With the guard, a test at the limit sees neither an explicit nor an automatic collection of a loop pending from an earlier test (T2, T4; G-1, G-2).
2. The collector's prior state is restored after a failing guarded test, from either state (T5, T6; G-3 to G-6).
3. The three exposed test functions ask for the guard, and the fixture reaches every test through conftest (T7, T8; W-1, A-1 to A-3).
4. The controls reproduce the GATE-F1 failure in a real nested pytest (T1, T3).
5. `test_ad721h_vrm_upload.py` leaks no loop (P5).
6. The section 8 texts are posted; GATE-F1 is ticked after the section 8.4 census comment.
7. Every section 10 row is killed by its named tests. One broad gate and one PR.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1523)

**R-1.** No check run with the suite detects a new test that overflows the Python stack without asking for the guard. Selection rests on review (section 14 property 4), on B5's amendment (section 8.3), and on the one-off RAISE census of section 8.4, which replaced the grep-based inventory after review round 1 found a test the grep could not see (A3). A detector run with every suite (for example the same `sys.monitoring` RAISE callback in CI) would cost every test; it is considered and deferred.

**R-2.** C-only overflows are unguarded on the premise that CPython 3.12 collects only at eval-breaker checks (P2). Re-check on an interpreter upgrade.

**R-3.** `test_bf908_crew_scope_token.py:397` left a loop open until session finish; cause not examined (section 8.4).

### Premises to verify first-hand before building (each with its probe)

| P | Premise | Probe (assert it) |
|---|---|---|
| P1 | The mechanism reproduces on the build host | Run `.adq/gatef1/auto_probe2.py`: `left` 2, 3 and 4 show HOOK-OVERFLOW for both `explicit` and `automatic`; 5 and above show nothing; every row says "alive at the limit" |
| P2 | A C-only overflow finalises nothing at depth | Plain Python, 20 trials: set a hook that records `(exc_type, object)`; `gc.collect(); gc.disable()`; leak a loop in a cycle; `gc.enable()`; `json.loads("[" * 100_000)` inside `try/except RecursionError` (assert it raised); then `gc.collect()`. Assert that no trial recorded a `RecursionError` from `BaseEventLoop.__del__` and that the loop is gone. Repeat with `json.dumps` of a list 20,000 deep. If any trial records one, guard the C-only rows (section 3 D3) |
| P3 | BF-986 is free, and after merging BF-985 each SEARCH matches exactly once | Re-run the BF enumeration; `rg -c` each SEARCH's first line in its file after the merge (conftest `:31` line, `# ProbOS Progress`, the BF-983 DECISIONS heading) |
| P4 | The controls reproduce under nested pytest on Windows, and on Linux in the PR's CI | T1 and T3 green on the build host before the guard lines are mutated; the CI run of the PR green. If a control fails on Linux, stop and report; do not loosen it |
| P5 | M2 closes the only leak in its file | `census_plugin.py` over `tests/test_ad721h_vrm_upload.py -n 0`: one `leak` record on M1, zero on M2 |
| P6 | The guarded tests still pass, at bounded cost | The M1 focused gate; `--durations=0` on the 11 nodes before and after M1 (expect less than 1 s added per node) |

## 16. Orchestrator amendment A1 (2026-11-19, before the build)

The orchestrator froze this contract after checking its premises first-hand. Two changes to the Architect's text; neither changes a code block, a test or a SEARCH:
- **ASCII.** Characters outside ASCII in prose became ASCII (for example a section sign became the word "section", a multiplication sign `x`, an ellipsis three dots, an arrow `->`, an em dash `--`). The one section sign inside a code block, the comment of `_GUARDED` in section 7.5, became the word "section"; that comment is the only code line this changes.
- **Three sentences about what each guard line is for (D5, and the PROGRESS and DECISIONS texts of 7.7 and 7.8).** They said that each line is "the only line" that stops garbage made during the test from being collected, and that "four doubles each kill one guard line". The mutation rows of section 10 say otherwise: T5 and T6 each kill three guard lines (G-2, G-3, G-6 and G-4, G-5, G-6), and `disable` does not stop an explicit collection of garbage the test made inside the deep frames (D4). The sentences now say: collect-first is the only line that stops an explicit collection at the limit from finalising garbage that earlier tests left; disable is the only line that stops an automatic collection at the limit from finalising garbage made during the test; the four doubles between them kill the removal of every guard line.

## 17. Orchestrator amendment A2 (2026-11-19, before the build)

BF-985 merged first (PR #1834, `53170fc2`), and the base of this build is `origin/main` `53170fc2`. The verification of section 11 was made on `7ca49126` and stands: BF-985 touched `scripts/_ci_shard_pytest_plugin.py`, `.github/workflows/ci.yml`, `tests/test_ci_shard_pytest_plugin.py`, `tests/test_ci_shards.py`, `PROGRESS.md`, `DECISIONS.md`, `docs/development/test-suite-optimization-plan.md`, the ledger pair and its own contract, and no file that M1 or M2 edits. P3 is done on a fresh scratch tree at `53170fc2`: every SEARCH of M1 to M3 occurs exactly once (the `# ProbOS Progress` heading and the `### BF-983 --` heading are both still single lines); the six code and test blobs equal those of the oracle built on `7ca49126`; only `PROGRESS.md`, `DECISIONS.md` and the ledger pair differ from it; the focused list gives 431 passed (421 on the base plus the 10 new cases). The ledger's own row (`docs/development/open-ads-report.md:32`) gives BF-985 as the highest and BF-986 as the next free BF number, and BF-986 occurs in no other tracked file. BF-987 is reserved by the orchestrator for the repair of item bf-985 F4 of #1820 (the `drain` helper that stalled BF-985's own CI run); this contract does not touch it. No code block, test or SEARCH changes.

## 18. Orchestrator amendment A3 (2026-11-19, after review round 1)

Review round 1 finding F1: `test_bf940_s2_dump_frontmatter.py:89` overflows PyYAML's representer through Python frames on its passing path (`_nested(600)` at `:92`; `frontmatter.py:56` converts the `RecursionError` into `ValueError`), and no list in this contract named it. The cause is AV6: its grep finds only tests that name `RecursionError`, and code that converts the error hides the rest. The Architect's decision: no guard now (the test is in a BF-940 file, which B5 owns and edits, so D7 covers it), and the inventory becomes a tool result. Changed: the D3 B5 row, AV6, R-1, sections 8.1 to 8.4, and the PROGRESS and DECISIONS texts of 7.7 and 7.8. No code block, test or SEARCH changes; the six code and test blobs stay equal to the oracle.
