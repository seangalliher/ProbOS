"""AD-573d: Dream-to-WorkingMemory pipeline tests."""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.dream_adapter import DreamAdapter, _summarize_dream_report
from probos.types import DreamReport


def _build_adapter(*, working_memory=None, emergent_detector=None):
    return DreamAdapter(
        dream_scheduler=None,
        emergent_detector=emergent_detector,
        episodic_memory=None,
        knowledge_store=None,
        hebbian_router=MagicMock(),
        trust_network=MagicMock(),
        event_emitter=lambda et, data: None,
        self_mod_pipeline=None,
        bridge_alerts=None,
        ward_room=None,
        registry=MagicMock(),
        event_log=None,
        config=MagicMock(),
        pools={},
        working_memory=working_memory,
    )


def test_summarize_full_report_renders_all_fields():
    report = DreamReport(
        clusters_found=3,
        procedures_extracted=2,
        contradictions_found=1,
        convergence_reports_generated=4,
        notebook_consolidations=5,
    )
    result = _summarize_dream_report(report)
    assert result is not None
    assert "3 clusters" in result
    assert "2 procedures" in result
    assert "1 contradictions" in result
    assert "4 convergences" in result
    assert "5 notebooks" in result
    assert result.startswith("Dream consolidation:")


def test_summarize_partial_report_omits_zeros():
    report = DreamReport(clusters_found=2)
    assert _summarize_dream_report(report) == "Dream consolidation: 2 clusters"


def test_summarize_empty_report_returns_none():
    assert _summarize_dream_report(DreamReport()) is None


def test_summarize_none_report_returns_none():
    assert _summarize_dream_report(None) is None


def test_summarize_uses_getattr_default_on_missing_attr():
    report = SimpleNamespace(clusters_found=2)
    assert _summarize_dream_report(report) == "Dream consolidation: 2 clusters"


def test_on_post_dream_writes_scratchpad_when_wm_present():
    wm = MagicMock()
    adapter = _build_adapter(working_memory=wm)
    report = DreamReport(clusters_found=3, procedures_extracted=2)
    adapter.on_post_dream(report)
    wm.add_scratchpad.assert_called_once()
    arg = wm.add_scratchpad.call_args[0][0]
    assert "3 clusters" in arg
    assert "2 procedures" in arg


def test_on_post_dream_skips_scratchpad_when_summary_empty():
    wm = MagicMock()
    adapter = _build_adapter(working_memory=wm)
    adapter.on_post_dream(DreamReport())
    wm.add_scratchpad.assert_not_called()


def test_on_post_dream_tolerates_working_memory_none():
    adapter = _build_adapter(working_memory=None)
    report = DreamReport(clusters_found=1)
    # Must not raise
    adapter.on_post_dream(report)


def test_on_post_dream_log_and_degrades_on_scratchpad_failure(caplog):
    wm = MagicMock()
    wm.add_scratchpad.side_effect = RuntimeError("disk full")
    adapter = _build_adapter(working_memory=wm)
    report = DreamReport(clusters_found=1)
    with caplog.at_level(logging.WARNING):
        adapter.on_post_dream(report)
    assert any("AD-573d" in rec.message for rec in caplog.records)


def test_on_post_dream_runs_summary_before_emergent_analyze():
    wm = MagicMock()
    detector = MagicMock()
    detector.analyze.side_effect = RuntimeError("boom")
    adapter = _build_adapter(working_memory=wm, emergent_detector=detector)
    report = DreamReport(clusters_found=1)
    adapter.on_post_dream(report)
    wm.add_scratchpad.assert_called_once()
