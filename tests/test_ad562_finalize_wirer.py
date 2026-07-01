"""AD-562: Tests for _wire_knowledge_browser."""
from __future__ import annotations

import logging

from types import SimpleNamespace
from unittest.mock import MagicMock

from probos.config import KnowledgeBrowserConfig, SystemConfig
from probos.knowledge.backlinks import KnowledgeBrowserService
from probos.startup.finalize import _wire_knowledge_browser


def _make_config(*, enabled: bool) -> SystemConfig:
    return SystemConfig(knowledge_browser=KnowledgeBrowserConfig(enabled=enabled))


def test_wire_knowledge_browser_skips_when_disabled() -> None:
    rt = SimpleNamespace()
    cfg = _make_config(enabled=False)
    assert _wire_knowledge_browser(runtime=rt, config=cfg) is False
    assert not hasattr(rt, "knowledge_browser")


def test_wire_knowledge_browser_constructs_service_when_enabled() -> None:
    rt = SimpleNamespace(_records_store=MagicMock(), _notebook_quality_engine=None)
    cfg = _make_config(enabled=True)
    assert _wire_knowledge_browser(runtime=rt, config=cfg) is True
    assert isinstance(rt.knowledge_browser, KnowledgeBrowserService)


def test_wire_knowledge_browser_logs_warning_when_records_store_missing(caplog) -> None:
    rt = SimpleNamespace()
    cfg = _make_config(enabled=True)
    with caplog.at_level(logging.WARNING):
        result = _wire_knowledge_browser(runtime=rt, config=cfg)
    assert result is False
    assert any("knowledge_browser enabled" in rec.message for rec in caplog.records)
