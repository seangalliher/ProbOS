"""Tests for AD-893 — Standing Orders read surface.

The public tier reader ``standing_orders.get_order_tiers`` is exercised against
a ``tmp_path`` orders directory so the present/absent flags are deterministic
(no coupling to the repo's real ``config/standing_orders`` files). The HTTP
endpoint is exercised with the REAL ``AgentRegistry`` (substrate boundary,
BF-287) and lightweight agent stubs — it only reads ``runtime.registry``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.cognitive import standing_orders
from probos.routers.crew import router
from probos.routers.deps import get_runtime
from probos.substrate.registry import AgentRegistry


@dataclass
class _Agent:
    id: str
    agent_type: str
    pool: str = "crew"
    callsign: str = ""


class _Runtime:
    def __init__(self) -> None:
        self.registry = AgentRegistry()


async def _register(rt: _Runtime) -> None:
    # "architect" maps to the "science" department in _AGENT_DEPARTMENTS.
    await rt.registry.register(_Agent("agent-arch", "architect", callsign="ARCH"))


def _build_runtime() -> _Runtime:
    rt = _Runtime()
    asyncio.run(_register(rt))
    return rt


def _client_for(runtime: _Runtime) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


# ----------------------------------------------------------------------
# get_order_tiers — public tier reader
# ----------------------------------------------------------------------


def test_get_order_tiers_returns_four_named_tiers(tmp_path: Path) -> None:
    (tmp_path / "federation.md").write_text("fed text", encoding="utf-8")
    (tmp_path / "ship.md").write_text("ship text", encoding="utf-8")
    (tmp_path / "science.md").write_text("science dept text", encoding="utf-8")
    # No architect.md -> agent tier absent.

    tiers = standing_orders.get_order_tiers("architect", orders_dir=tmp_path)

    assert [t["tier"] for t in tiers] == ["federation", "ship", "department", "agent"]
    by_tier = {t["tier"]: t for t in tiers}
    assert by_tier["federation"]["present"] is True
    assert by_tier["federation"]["text"] == "fed text"
    assert by_tier["ship"]["present"] is True
    assert by_tier["department"]["present"] is True
    assert by_tier["department"]["source_file"] == "science.md"
    assert by_tier["department"]["text"] == "science dept text"


def test_get_order_tiers_missing_agent_file_present_false(tmp_path: Path) -> None:
    (tmp_path / "federation.md").write_text("fed", encoding="utf-8")
    (tmp_path / "ship.md").write_text("ship", encoding="utf-8")
    (tmp_path / "science.md").write_text("sci", encoding="utf-8")

    tiers = standing_orders.get_order_tiers("architect", orders_dir=tmp_path)
    agent_tier = next(t for t in tiers if t["tier"] == "agent")

    assert agent_tier["present"] is False
    assert agent_tier["text"] == ""
    assert agent_tier["source_file"] == "architect.md"


def test_get_order_tiers_department_none_when_unmapped(tmp_path: Path) -> None:
    # "ghost" has no entry in _AGENT_DEPARTMENTS -> no department file.
    (tmp_path / "federation.md").write_text("fed", encoding="utf-8")
    (tmp_path / "ship.md").write_text("ship", encoding="utf-8")

    tiers = standing_orders.get_order_tiers("ghost", orders_dir=tmp_path)
    dept_tier = next(t for t in tiers if t["tier"] == "department")

    assert dept_tier["source_file"] is None
    assert dept_tier["present"] is False
    assert dept_tier["text"] == ""


def test_get_order_tiers_all_absent_present_false(tmp_path: Path) -> None:
    # Empty directory -> every tier absent, but the four-tier shape is preserved.
    tiers = standing_orders.get_order_tiers("architect", orders_dir=tmp_path)

    assert len(tiers) == 4
    assert all(t["present"] is False for t in tiers)
    assert all(t["text"] == "" for t in tiers)


# ----------------------------------------------------------------------
# GET /api/crew/{agent_id}/standing-orders
# ----------------------------------------------------------------------


def test_endpoint_returns_four_tiers_for_known_agent() -> None:
    client = _client_for(_build_runtime())
    body = client.get("/api/crew/agent-arch/standing-orders").json()

    assert body["agent_id"] == "agent-arch"
    assert body["agent_type"] == "architect"
    assert [t["tier"] for t in body["tiers"]] == [
        "federation", "ship", "department", "agent",
    ]
    for tier in body["tiers"]:
        assert set(tier) == {"tier", "source_file", "present", "text"}
        assert isinstance(tier["present"], bool)


def test_endpoint_unknown_agent_returns_404() -> None:
    client = _client_for(_build_runtime())
    resp = client.get("/api/crew/agent-missing/standing-orders")
    assert resp.status_code == 404
