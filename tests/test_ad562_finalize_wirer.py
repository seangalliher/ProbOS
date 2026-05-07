"""AD-562: Tests for _wire_knowledge_browser."""
from __future__ import annotations

import logging

from unittest.mock import MagicMock

from probos.config import KnowledgeBrowserConfig
from probos.knowledge.backlinks import KnowledgeBrowserService
from probos.startup.finalize import _wire_knowledge_browser


def _make_config(*, enabled: bool) -> MagicMock:
    cfg = MagicMock()
    cfg.knowledge_browser = KnowledgeBrowserConfig(enabled=enabled)
    return cfg


def test_wire_knowledge_browser_skips_when_disabled() -> None:
    rt = MagicMock(spec=[])
    cfg = _make_config(enabled=False)
    assert _wire_knowledge_browser(runtime=rt, config=cfg) is False
    assert not hasattr(rt, "knowledge_browser") or rt.knowledge_browser is None or isinstance(rt.knowledge_browser, MagicMock)


def test_wire_knowledge_browser_constructs_service_when_enabled() -> None:
    rt = MagicMock(spec=["_records_store", "_notebook_quality_engine", "knowledge_browser"])
    rt._records_store = MagicMock()
    rt._notebook_quality_engine = MagicMock()
    cfg = _make_config(enabled=True)
    assert _wire_knowledge_browser(runtime=rt, config=cfg) is True
    assert isinstance(rt.knowledge_browser, KnowledgeBrowserService)


def test_wire_knowledge_browser_logs_warning_when_records_store_missing(caplog) -> None:
    rt = MagicMock(spec=[])
    cfg = _make_config(enabled=True)
    with caplog.at_level(logging.WARNING):
        result = _wire_knowledge_browser(runtime=rt, config=cfg)
    assert result is False
    assert any("knowledge_browser enabled" in rec.message for rec in caplog.records)
