"""AD-597: _wire_mcp_app_host finalize tests."""

from __future__ import annotations

from types import SimpleNamespace

from probos.config import MCPAppHostConfig, SystemConfig
from probos.startup.finalize import _wire_mcp_app_host


class _FakeRecreation:
    def get_available_games(self):
        return ["tictactoe"]

    @property
    def default_game(self):
        return "tictactoe"


def _runtime():
    emitted = []
    return SimpleNamespace(
        emit_event=lambda *a, **kw: emitted.append((a, kw)),
        recreation_service=_FakeRecreation(),
        mcp_bridge=None,
        mcp_app_registry=None,
        _mcp_app_external_discovery_task=None,
    )


def test_wire_skipped_when_disabled():
    cfg = SystemConfig()
    cfg.mcp_app_host = MCPAppHostConfig(enabled=False)
    rt = _runtime()
    result = _wire_mcp_app_host(runtime=rt, config=cfg)
    assert result is False
    assert rt.mcp_app_registry is None


def test_wire_installs_registry_when_enabled():
    cfg = SystemConfig()
    cfg.mcp_app_host = MCPAppHostConfig(enabled=True, serve_internal_games=True)
    rt = _runtime()
    result = _wire_mcp_app_host(runtime=rt, config=cfg)
    assert result is True
    assert rt.mcp_app_registry is not None
    # game-* tools registered
    names = {t["name"] for t in rt.mcp_app_registry.list_tools()}
    assert "game-move" in names
    assert "game-tictactoe-challenge" in names
