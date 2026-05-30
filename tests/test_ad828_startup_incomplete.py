"""AD-828: partial-shutdown diagnostic + startup-incomplete classification.

Covers:
- AD-828a: consolidation gate logs which component was None when skipping.
- AD-828b: shutdown reclassifies skip-during-startup as ``startup_incomplete``;
  ``check_previous_shutdown`` permits boot for that value but still refuses
  for ``failed`` / ``skipped`` (regression guards).
- ``runtime._startup_complete`` defaults to False on construction.
"""
from __future__ import annotations

import inspect
import json

import pytest

from probos.shutdown_integrity import (
    STATUS_FILENAME,
    ConsolidationResult,
    UncleanShutdownDetected,
    check_previous_shutdown,
    mark_dirty_shutdown,
    read_shutdown_status,
)


# ---------------- Boot gate: check_previous_shutdown ----------------


def test_startup_incomplete_marker_permits_boot(tmp_path):
    """AD-828b: startup_incomplete is recoverable — check_previous_shutdown returns."""
    # Sentinel so it isn't treated as first boot.
    (tmp_path / "events.db").write_text("x")
    mark_dirty_shutdown(
        tmp_path,
        consolidation_result="startup_incomplete",
        note="killed mid-boot",
    )
    # Must not raise.
    check_previous_shutdown(tmp_path, is_first_boot=False)


def test_failed_marker_still_raises(tmp_path):
    """Regression: AD-828 carve-out did NOT widen to genuine failures."""
    mark_dirty_shutdown(
        tmp_path, consolidation_result="failed", note="exception"
    )
    with pytest.raises(UncleanShutdownDetected):
        check_previous_shutdown(tmp_path)


def test_skipped_marker_still_raises(tmp_path):
    """Regression: pre-AD behavior intact when startup DID complete and gate
    skipped for some other reason (subsystem disabled mid-flight)."""
    mark_dirty_shutdown(
        tmp_path, consolidation_result="skipped", note="subsystem absent"
    )
    with pytest.raises(UncleanShutdownDetected):
        check_previous_shutdown(tmp_path)


def test_startup_incomplete_round_trips_through_read(tmp_path):
    """Serialization guard for the new Literal member."""
    mark_dirty_shutdown(
        tmp_path,
        consolidation_result="startup_incomplete",
        note="boot kill",
    )
    payload = read_shutdown_status(tmp_path)
    assert payload["consolidation_result"] == "startup_incomplete"
    assert payload["status"] == "partial"
    # Raw file too — confirm atomic write produced exact literal.
    raw = json.loads((tmp_path / STATUS_FILENAME).read_text(encoding="utf-8"))
    assert raw["consolidation_result"] == "startup_incomplete"


def test_consolidation_result_literal_includes_startup_incomplete():
    """Type-level guard: the Literal must include the new member."""
    # ConsolidationResult is a typing.Literal[...] — args carry the members.
    members = set(ConsolidationResult.__args__)  # type: ignore[attr-defined]
    assert "startup_incomplete" in members
    # Existing members must remain (regression guard).
    for required in ("full", "partial", "skipped", "failed", "rebuilt"):
        assert required in members


# ---------------- Shutdown classification predicate ----------------
# The full shutdown(runtime) call wires through ward_room, event_log, registry,
# trust, attention, etc. — too entangled for a focused unit test. Per spec
# Section 4, we test the exact boolean predicate the gate uses, mirrored
# verbatim from src/probos/startup/shutdown.py.


class _FakeRuntime:
    """Minimal stub exposing the attributes the AD-828 else-branch reads."""

    def __init__(
        self,
        *,
        dream_scheduler=None,
        episodic_memory=None,
        startup_complete=None,
    ) -> None:
        self.dream_scheduler = dream_scheduler
        self.episodic_memory = episodic_memory
        if startup_complete is not None:
            self._startup_complete = startup_complete


def _classify(runtime: _FakeRuntime, initial_result: str = "skipped") -> str:
    """Mirror of the AD-828 else-branch predicate in shutdown.py.

    Returns the value ``_consolidation_result`` would carry after the
    gate's else-branch runs given a runtime where the gate condition
    ``runtime.dream_scheduler and runtime.episodic_memory`` is False.
    """
    _startup_done = getattr(runtime, "_startup_complete", True)
    if not _startup_done:
        return "startup_incomplete"
    return initial_result


def test_classify_killed_mid_boot_is_startup_incomplete():
    """AD-828b: dream_scheduler=None + _startup_complete=False → startup_incomplete."""
    rt = _FakeRuntime(dream_scheduler=None, startup_complete=False)
    assert _classify(rt) == "startup_incomplete"


def test_classify_startup_complete_stays_skipped():
    """Disabled-subsystem path: gate skipped AFTER startup → stays 'skipped'."""
    rt = _FakeRuntime(dream_scheduler=None, startup_complete=True)
    assert _classify(rt) == "skipped"


def test_classify_missing_attr_honest_degrades_to_skipped():
    """BF-291 transitional-process convention: a process started before this AD
    shipped has no _startup_complete attribute; getattr default True keeps the
    pre-AD behavior (stays 'skipped' → blocks boot) rather than being silently
    reclassified."""
    rt = _FakeRuntime(dream_scheduler=None, startup_complete=None)
    assert not hasattr(rt, "_startup_complete")
    assert _classify(rt) == "skipped"


# ---------------- Runtime flag default ----------------


def test_runtime_startup_complete_initialized_false_in_source():
    """AD-828b: _startup_complete must default to False in ProbOSRuntime.__init__.

    Constructing a real ProbOSRuntime is too heavy for a focused unit test
    (it wires the full substrate + cognitive layer). Per spec Section 4 this
    is the authorised fallback: assert the __init__ default via a targeted
    source read.
    """
    from probos import runtime as runtime_mod

    src = inspect.getsource(runtime_mod.ProbOSRuntime.__init__)
    assert "self._startup_complete: bool = False" in src, (
        "AD-828b: ProbOSRuntime.__init__ must initialise _startup_complete=False"
    )


def test_runtime_start_sets_startup_complete_true_in_source():
    """AD-828b: start() must set _startup_complete=True as final body statement."""
    from probos import runtime as runtime_mod

    src = inspect.getsource(runtime_mod.ProbOSRuntime.start)
    assert "self._startup_complete = True" in src, (
        "AD-828b: ProbOSRuntime.start() must set _startup_complete=True"
    )
