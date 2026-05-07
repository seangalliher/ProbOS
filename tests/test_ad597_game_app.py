"""AD-597b: ProbOS Game MCP Server (game_app.py) tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from probos.mcp_apps.game_app import register_game_resources, register_game_tools
from probos.mcp_apps.registry import MCPAppRegistry


_VALID_CSP = "default-src 'self'"


def _registry() -> MCPAppRegistry:
    return MCPAppRegistry(
        internal_default_csp=_VALID_CSP,
        external_default_csp=_VALID_CSP,
    )


class _FakeRecreation:
    def __init__(self):
        self.calls = []
        self._active_games = {"g1": {"status": "in_progress"}}
        self.default_game = "tictactoe"

    def get_available_games(self):
        return ["tictactoe", "chess"]

    async def create_game(self, gt, ch, op, tid):
        self.calls.append(("create", gt, ch, op, tid))
        return {"game_id": "g1", "game_type": gt}

    async def make_move(self, gid, player, move):
        self.calls.append(("move", gid, player, move))
        return {"status": "in_progress"}

    async def forfeit_game(self, gid, player):
        self.calls.append(("forfeit", gid, player))

    def get_valid_moves(self, gid):
        return ["a1b2"]


def test_register_game_tools_registers_5_generic_plus_per_game_challenge():
    r = _registry()
    rs = _FakeRecreation()
    register_game_tools(r, rs)
    names = {t["name"] for t in r.list_tools()}
    assert "game-move" in names
    assert "game-state" in names
    assert "game-forfeit" in names
    assert "game-valid-moves" in names
    assert "game-tictactoe-challenge" in names
    assert "game-chess-challenge" in names


@pytest.mark.asyncio
async def test_game_move_tool_routes_to_recreation_service():
    r = _registry()
    rs = _FakeRecreation()
    register_game_tools(r, rs)
    res = await r.call_tool("game-move", {"game_id": "g1", "player": "p", "move": "a1b2"})
    assert res["isError"] is False
    assert ("move", "g1", "p", "a1b2") in rs.calls


@pytest.mark.asyncio
async def test_game_state_unknown_game_id_returns_error():
    r = _registry()
    rs = _FakeRecreation()
    register_game_tools(r, rs)
    res = await r.call_tool("game-state", {"game_id": "missing"})
    assert res["isError"] is True


@pytest.mark.asyncio
async def test_game_state_known_game_id_happy_path():
    r = _registry()
    rs = _FakeRecreation()
    register_game_tools(r, rs)
    res = await r.call_tool("game-state", {"game_id": "g1"})
    assert res["isError"] is False
    payload = json.loads(res["content"][0]["text"])
    assert payload["status"] == "in_progress"


@pytest.mark.asyncio
async def test_game_forfeit_routes_to_service():
    r = _registry()
    rs = _FakeRecreation()
    register_game_tools(r, rs)
    res = await r.call_tool("game-forfeit", {"game_id": "g1", "player": "p"})
    assert res["isError"] is False
    assert ("forfeit", "g1", "p") in rs.calls


@pytest.mark.asyncio
async def test_game_valid_moves_returns_list():
    r = _registry()
    rs = _FakeRecreation()
    register_game_tools(r, rs)
    res = await r.call_tool("game-valid-moves", {"game_id": "g1"})
    assert res["isError"] is False
    moves = json.loads(res["content"][0]["text"])
    assert moves == ["a1b2"]


@pytest.mark.asyncio
async def test_game_challenge_routes_to_create_game():
    r = _registry()
    rs = _FakeRecreation()
    register_game_tools(r, rs)
    res = await r.call_tool(
        "game-tictactoe-challenge",
        {"challenger": "a", "opponent": "b", "thread_id": "t1"},
    )
    assert res["isError"] is False
    assert ("create", "tictactoe", "a", "b", "t1") in rs.calls


def test_challenge_tool_carries_correct_resource_uri():
    r = _registry()
    rs = _FakeRecreation()
    register_game_tools(r, rs)
    by_name = {t["name"]: t for t in r.list_tools()}
    assert by_name["game-chess-challenge"]["_meta"]["ui"]["resourceUri"] == (
        "ui://probos/games/chess/index.html"
    )


def test_register_game_resources_reads_bundle_files(tmp_path: Path):
    r = _registry()
    bundles = tmp_path / "bundles"
    chess = bundles / "chess"
    chess.mkdir(parents=True)
    (chess / "index.html").write_bytes(b"<html>chess</html>")
    register_game_resources(r, bundles)
    assert r.get_resource_mime("ui://probos/games/chess/index.html") == "text/html"


def test_register_game_resources_missing_dir_log_and_degrade(tmp_path: Path, caplog):
    r = _registry()
    missing = tmp_path / "no-such-dir"
    with caplog.at_level("WARNING"):
        register_game_resources(r, missing)
    assert any("bundles dir missing" in m for m in caplog.messages)


def test_register_game_resources_missing_index_skips(tmp_path: Path, caplog):
    r = _registry()
    bundles = tmp_path / "bundles"
    (bundles / "broken").mkdir(parents=True)
    with caplog.at_level("WARNING"):
        register_game_resources(r, bundles)
    assert any("missing index.html" in m for m in caplog.messages)
