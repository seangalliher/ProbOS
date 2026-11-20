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
    ("tests.test_bf940_s2_dump_frontmatter", "test_a_mapping_nested_too_deeply_is_a_value_error_not_a_recursion_error"),
    ("tests.test_bf952_records_keyword_search", "test_a_frontmatter_nesting_64_collections_or_more_is_unparsed_in_both_readings"),
    ("tests.test_bf952_records_keyword_search", "test_a_deeply_nested_record_is_unparsed_in_every_reader"),
    ("tests.test_bf952_records_keyword_search", "test_parse_document_never_raises_recursion_error_for_nesting"),
    ("tests.test_bf970_frontmatter_reading", "test_a_search_over_a_corpus_holding_a_block_nested_400_deep_returns_the_other_records"),
    ("tests.test_bf970_frontmatter_reading", "test_the_nesting_check_answers_from_a_nearly_exhausted_stack_and_stops_at_the_limit"),
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
    ("module", "name"),
    _GUARDED,
    ids=[
        "ad1197-outbound", "ad1197-inbound", "bf904b-unreadable-policy",
        "bf940-s2-dump-too-deep", "bf952-both-readings", "bf952-every-reader", "bf952-parse-document",
        "bf970-search-400-deep", "bf970-exhausted-stack",
    ],
)
def test_every_test_that_overflows_the_python_stack_asks_for_the_guard(module: str, name: str) -> None:
    function = getattr(importlib.import_module(module), name)
    marks = [mark for mark in getattr(function, "pytestmark", []) if mark.name == "usefixtures"]
    assert any(guard.GUARD_FIXTURE in mark.args for mark in marks), f"{module}::{name} runs to the recursion limit without the guard"
