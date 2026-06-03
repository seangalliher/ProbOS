"""BF-598: idempotent shutdown() + non-regressive AD-820 marker write.

Covers two defects behind the recurring AD-820 boot refusal (3rd cluster,
~4-day Windows sleep/wake cadence):

- **D1** — ``shutdown()`` was not idempotent. ``runtime._started = False`` is
  set only at the very end, so a *second* ``shutdown()`` (duplicate SIGTERM on
  sleep/wake, or a retried ``stop()``) re-entered, found the cognitive
  subsystems torn down, skipped consolidation, and reached the marker write.
  Fix: a dedicated ``_shutdown_started`` re-entrancy flag set at the TOP, before
  the marker is ever written. Tested against the **real** ``shutdown()`` entry,
  since that is the defect locus.
- **D2** — the marker write was unconditionally regressive: a ``skipped``
  consolidation result overwrote a perfectly clean marker with ``partial``,
  blocking the next boot. Fix: a ``skipped`` result (the cognitive subsystems
  were absent, so nothing was written to the HNSW index — it cannot be torn)
  never DOWNGRADES an existing ``clean``/``rebuilt`` marker. ``partial`` /
  ``failed`` still block (real torn-index risk; non-regression is ``skipped``-only).

Per the no-MagicMock-at-substrate-boundary rule, these use a real ``tmp_path``
data dir, the real ``shutdown_integrity`` helpers, and a minimal real-attribute
fake runtime — never ``MagicMock`` for the substrate surface ``shutdown()`` reads.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from probos.runtime import ProbOSRuntime
from probos.shutdown_integrity import (
    ConsolidationResult,
    UncleanShutdownDetected,
    check_previous_shutdown,
    mark_clean_shutdown,
    mark_dirty_shutdown,
    read_shutdown_status,
)
from probos.startup.shutdown import shutdown


# --------------------------------------------------------------------------- #
# Minimal real-attribute fake runtime (no MagicMock at the substrate boundary).
# Only the attributes ``shutdown()`` reads up to the ``_started`` short-circuit
# are populated; with ``_started=False`` the body returns right after the
# session-record write, exercising the real D1 guard without the heavy teardown.
# --------------------------------------------------------------------------- #
class _FakeRegistry:
    """Real object with a real ``all()`` — never a MagicMock auto-attribute."""

    def all(self) -> list:
        return []


class _FakeRuntime:
    def __init__(
        self,
        *,
        data_dir: Path,
        started: bool = False,
        shutdown_started: bool = False,
    ) -> None:
        self._data_dir = data_dir
        self._started = started
        self._shutdown_started = shutdown_started
        self._session_id = "bf598-test-session"
        self._start_time_wall = 0.0
        self._start_time = 0.0
        self.registry = _FakeRegistry()
        self.ontology = None
        self.dream_scheduler = None
        self.episodic_memory = None
        self.config = None


# --------------------------------------------------------------------------- #
# Mirror of the D2 marker-write decision in src/probos/startup/shutdown.py.
# Kept verbatim so tests 3–5 exercise the exact branch logic; a source-literal
# assertion (test 8) guards against the mirror drifting from production.
# --------------------------------------------------------------------------- #
def _decide_and_write_marker(
    data_dir: Path,
    consolidation_result: ConsolidationResult,
    phase1_elapsed: float = 2.0,
) -> None:
    if consolidation_result == "full":
        mark_clean_shutdown(
            data_dir, consolidation_result="full", note="phase1_ok"
        )
    elif consolidation_result == "skipped":
        _existing = read_shutdown_status(data_dir)
        if _existing.get("status") == "clean" or _existing.get(
            "consolidation_result"
        ) in ("full", "rebuilt"):
            # preserve — a skip cannot tear the index
            return
        mark_dirty_shutdown(
            data_dir,
            consolidation_result="skipped",
            note=f"phase1_elapsed={phase1_elapsed:.1f}s",
        )
    else:
        mark_dirty_shutdown(
            data_dir,
            consolidation_result=consolidation_result,
            note=f"phase1_elapsed={phase1_elapsed:.1f}s",
        )


# --------------------------- D1: idempotency ------------------------------- #


async def test_reentrant_shutdown_returns_early_and_preserves_marker(tmp_path):
    """A second shutdown() (flag already True) returns immediately and never
    rewrites the AD-820 marker — the root-cause fix for the boot refusal."""
    mark_clean_shutdown(tmp_path, consolidation_result="full", note="phase1_ok")
    before = read_shutdown_status(tmp_path)
    assert before["status"] == "clean"

    runtime = _FakeRuntime(data_dir=tmp_path, shutdown_started=True)
    await shutdown(runtime, reason="duplicate SIGTERM")

    after = read_shutdown_status(tmp_path)
    assert after["status"] == "clean"
    # Unchanged timestamp proves no marker write occurred on re-entry.
    assert after["last_shutdown_at"] == before["last_shutdown_at"]


async def test_first_shutdown_sets_shutdown_started_flag(tmp_path):
    """The first invocation sets _shutdown_started=True at the top so a later
    duplicate returns early. With _started=False the body short-circuits right
    after the session-record write — the flag must already be set."""
    runtime = _FakeRuntime(data_dir=tmp_path, started=False, shutdown_started=False)
    assert runtime._shutdown_started is False

    await shutdown(runtime, reason="first stop")

    assert runtime._shutdown_started is True
    # Session record was written before the _started short-circuit (BF-137).
    assert (tmp_path / "session_last.json").exists()


# ------------------------- D2: non-regressive marker ----------------------- #


def test_skipped_does_not_downgrade_clean_marker(tmp_path):
    """A skipped result must PRESERVE an existing clean marker (nothing was
    written to the HNSW index, so it cannot be torn)."""
    mark_clean_shutdown(tmp_path, consolidation_result="full", note="phase1_ok")
    before = read_shutdown_status(tmp_path)

    _decide_and_write_marker(tmp_path, "skipped")

    after = read_shutdown_status(tmp_path)
    assert after["status"] == "clean"
    assert after["consolidation_result"] == "full"
    assert after["last_shutdown_at"] == before["last_shutdown_at"]


def test_skipped_with_no_prior_marker_writes_partial(tmp_path):
    """First-boot honesty preserved: with no prior marker, a skip surfaces as
    a partial/skipped marker rather than being silently swallowed."""
    assert read_shutdown_status(tmp_path) == {}

    _decide_and_write_marker(tmp_path, "skipped")

    after = read_shutdown_status(tmp_path)
    assert after["status"] == "partial"
    assert after["consolidation_result"] == "skipped"


def test_failed_still_downgrades_and_blocks(tmp_path):
    """Non-regression is skipped-ONLY: a genuine failure (torn-index risk) must
    still downgrade a clean marker so the next boot refuses."""
    mark_clean_shutdown(tmp_path, consolidation_result="full", note="phase1_ok")

    _decide_and_write_marker(tmp_path, "failed")

    after = read_shutdown_status(tmp_path)
    assert after["status"] == "partial"
    assert after["consolidation_result"] == "failed"


# --------------------------- D2: end-to-end boot --------------------------- #


def test_check_previous_shutdown_boots_after_preserved_clean_marker(tmp_path):
    """End-to-end: after a skip preserves the clean marker, the boot gate must
    permit start (the whole point of the fix)."""
    mark_clean_shutdown(tmp_path, consolidation_result="full", note="phase1_ok")
    _decide_and_write_marker(tmp_path, "skipped")  # preserves clean

    # Must not raise.
    check_previous_shutdown(tmp_path, is_first_boot=False)


def test_failed_marker_blocks_boot(tmp_path):
    """Counterpart to the preserve case: a downgraded failed marker still
    raises, proving non-regression did not weaken the gate."""
    mark_clean_shutdown(tmp_path, consolidation_result="full", note="phase1_ok")
    _decide_and_write_marker(tmp_path, "failed")

    with pytest.raises(UncleanShutdownDetected):
        check_previous_shutdown(tmp_path)


# ------------------------------ runtime init ------------------------------- #


def test_runtime_init_shutdown_started_defaults_false(tmp_path):
    """ProbOSRuntime._shutdown_started must initialise False so the first
    shutdown() never early-returns."""
    rt = ProbOSRuntime(data_dir=tmp_path / "data")
    assert rt._shutdown_started is False


# ------------------------- drift guard for the mirror ---------------------- #


def test_shutdown_source_contains_nonregressive_skip_branch():
    """Guard against the test mirror drifting from production: the real
    shutdown() source must contain the skipped-preserve decision (read the
    existing marker, preserve clean/rebuilt) and the D1 idempotency guard."""
    src = inspect.getsource(shutdown)
    # D1 guard
    assert "_shutdown_started" in src
    assert "getattr(runtime, \"_shutdown_started\", False)" in src
    # D2 non-regressive skip branch
    assert "read_shutdown_status" in src
    assert '"rebuilt"' in src or "'rebuilt'" in src
    assert "skipped" in src
