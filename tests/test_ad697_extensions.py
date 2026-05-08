"""AD-697: tests for the commercial overlay extension-point registry."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from probos.extensions import overlay as ext


@pytest.fixture(autouse=True)
def _reset_registry():
    ext.reset_for_tests()
    yield
    ext.reset_for_tests()


def test_register_finalize_hook_records_name_and_provider() -> None:
    def hook(_runtime: Any, _config: Any) -> None:
        return None

    ext.register_finalize_hook("rbac", hook, provider="third-party-overlay")
    assert ext.is_commercial_loaded() is True
    assert ext.loaded_providers() == ("third-party-overlay",)
    assert ext.registered_hook_names() == ("rbac",)


def test_register_finalize_hook_rejects_empty_name() -> None:
    with pytest.raises(ValueError):
        ext.register_finalize_hook("", lambda r, c: None)


@pytest.mark.asyncio
async def test_run_finalize_hooks_invokes_sync_and_async() -> None:
    calls: list[str] = []

    def sync_hook(runtime: Any, config: Any) -> None:
        calls.append(f"sync:{runtime}:{config}")

    async def async_hook(runtime: Any, config: Any) -> None:
        await asyncio.sleep(0)
        calls.append(f"async:{runtime}:{config}")

    ext.register_finalize_hook("a", sync_hook, provider="p1")
    ext.register_finalize_hook("b", async_hook, provider="p1")

    await ext.run_finalize_hooks(runtime="R", config="C")
    assert calls == ["sync:R:C", "async:R:C"]


@pytest.mark.asyncio
async def test_failing_hook_is_logged_and_does_not_propagate() -> None:
    calls: list[str] = []

    def boom(_runtime: Any, _config: Any) -> None:
        raise RuntimeError("nope")

    def works(_runtime: Any, _config: Any) -> None:
        calls.append("ok")

    ext.register_finalize_hook("boom", boom, provider="p1")
    ext.register_finalize_hook("works", works, provider="p1")
    # Must not raise; second hook still runs.
    await ext.run_finalize_hooks(runtime=None, config=None)
    assert calls == ["ok"]


def test_is_commercial_loaded_false_by_default() -> None:
    assert ext.is_commercial_loaded() is False
    assert ext.loaded_providers() == ()


def test_is_commercial_loaded_true_after_registration() -> None:
    ext.register_finalize_hook("x", lambda r, c: None, provider="third-party-overlay")
    assert ext.is_commercial_loaded() is True


def test_register_without_provider_does_not_count_as_commercial() -> None:
    """A hook registered with provider="" should not flip the predicate."""
    ext.register_finalize_hook("x", lambda r, c: None)
    assert ext.is_commercial_loaded() is False


def test_discover_extensions_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _StubEP:
        name = "ad697-stub"

        def load(self):
            def _register():
                calls.append("called")
                ext.register_finalize_hook("x", lambda r, c: None, provider="stub")
            return _register

    def _fake_entry_points(group: str = ""):
        if group == ext.ENTRY_POINT_GROUP:
            return [_StubEP()]
        return []

    monkeypatch.setattr(ext.importlib.metadata, "entry_points", _fake_entry_points)
    ext.discover_extensions()
    ext.discover_extensions()  # second call must be a no-op
    assert calls == ["called"]
    assert ext.loaded_providers() == ("stub",)


def test_discover_extensions_swallows_broken_entry_point(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _BrokenEP:
        name = "broken"

        def load(self):
            raise ImportError("no such module")

    class _GoodEP:
        name = "good"

        def load(self):
            def _register():
                ext.register_finalize_hook("x", lambda r, c: None, provider="good")
            return _register

    def _fake_entry_points(group: str = ""):
        if group == ext.ENTRY_POINT_GROUP:
            return [_BrokenEP(), _GoodEP()]
        return []

    monkeypatch.setattr(ext.importlib.metadata, "entry_points", _fake_entry_points)
    import logging
    with caplog.at_level(logging.WARNING):
        ext.discover_extensions()
    # Good EP still registered
    assert ext.is_commercial_loaded() is True
    assert "good" in ext.loaded_providers()
    # Broken EP logged a warning
    assert any("broken" in rec.getMessage() for rec in caplog.records)


def test_discover_extensions_swallows_register_error(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    class _RaisingEP:
        name = "raises-on-call"

        def load(self):
            def _bad_register():
                raise RuntimeError("registration boom")
            return _bad_register

    def _fake_entry_points(group: str = ""):
        return [_RaisingEP()] if group == ext.ENTRY_POINT_GROUP else []

    monkeypatch.setattr(ext.importlib.metadata, "entry_points", _fake_entry_points)
    # Must not raise
    ext.discover_extensions()
    assert ext.is_commercial_loaded() is False


@pytest.mark.asyncio
async def test_run_finalize_hooks_passes_runtime_and_config() -> None:
    received: list[tuple[Any, Any]] = []

    def hook(runtime: Any, config: Any) -> None:
        received.append((runtime, config))

    runtime = SimpleNamespace(name="r1")
    config = SimpleNamespace(name="c1")
    ext.register_finalize_hook("x", hook, provider="p")
    await ext.run_finalize_hooks(runtime, config)
    assert received == [(runtime, config)]
