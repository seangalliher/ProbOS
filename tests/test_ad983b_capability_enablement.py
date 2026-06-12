"""AD-983b: per-agent capability enablement — SkillGrantStore + catalog overlay + API.

The "each crew agent independently enables different tools and skills" piece of
the AD-983 epic. Tools already had per-agent grants (ToolPermissionStore);
this adds the skill counterpart (SkillGrantStore) + the catalog overlay that
layers per-agent grants/restrictions on the dept/rank defaults, and the unified
GET/POST /api/agent/{id}/capabilities surface.

BF-287: real SkillGrantStore + real CognitiveSkillCatalog (on-disk SKILL.md);
the runtime is a SimpleNamespace holding the real stores. No MagicMock at the
store boundary.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.cognitive.skill_catalog import CognitiveSkillCatalog
from probos.cognitive.skill_grants import SkillGrantStore
from probos.config import AuthConfig


_SCIENCE_SKILL = """\
---
name: science-skill
description: A science department skill.
metadata:
  probos-department: science
  probos-min-rank: ensign
  probos-intents: "do_science"
---
# Science Skill
Body.
"""

_ENG_SKILL = """\
---
name: eng-skill
description: An engineering department skill.
metadata:
  probos-department: engineering
  probos-min-rank: ensign
  probos-intents: "do_engineering"
---
# Eng Skill
Body.
"""


def _write_skills(root: Path) -> None:
    sci = root / "science-skill"
    sci.mkdir(parents=True)
    (sci / "SKILL.md").write_text(_SCIENCE_SKILL, encoding="utf-8")
    eng = root / "eng-skill"
    eng.mkdir(parents=True)
    (eng / "SKILL.md").write_text(_ENG_SKILL, encoding="utf-8")


async def _make_catalog(tmp_path: Path, *, with_grants: bool = True):
    skills_dir = tmp_path / "skills"
    _write_skills(skills_dir)
    catalog = CognitiveSkillCatalog(
        skills_dir=skills_dir, db_path=str(tmp_path / "cat.db"),
    )
    await catalog.start()
    store = None
    if with_grants:
        store = SkillGrantStore(db_path=str(tmp_path / "grants.db"))
        await store.start()
        catalog.set_grant_store(store)
    return catalog, store


# ===================== SkillGrantStore (mirror of ToolPermissionStore) =====

def test_grant_store_issue_and_sync_read(tmp_path: Path) -> None:
    async def _run() -> None:
        store = SkillGrantStore(db_path=str(tmp_path / "g.db"))
        await store.start()
        await store.issue_grant("a1", "science-skill", reason="captain")
        grants = store.get_active_grants_sync("a1")
        assert len(grants) == 1
        assert grants[0].skill_name == "science-skill"
        assert grants[0].is_restriction is False
        # other agent unaffected
        assert store.get_active_grants_sync("a2") == []
        await store.stop()

    asyncio.run(_run())


def test_grant_store_restriction_and_revoke(tmp_path: Path) -> None:
    async def _run() -> None:
        store = SkillGrantStore(db_path=str(tmp_path / "g.db"))
        await store.start()
        g = await store.issue_grant("a1", "eng-skill", is_restriction=True)
        assert store.get_active_grants_sync("a1")[0].is_restriction is True
        assert await store.revoke_grant(g.id) is True
        assert store.get_active_grants_sync("a1") == []
        # revoking an unknown id is False
        assert await store.revoke_grant("nope") is False
        await store.stop()

    asyncio.run(_run())


def test_grant_store_persists_across_restart(tmp_path: Path) -> None:
    async def _run() -> None:
        path = str(tmp_path / "g.db")
        store = SkillGrantStore(db_path=path)
        await store.start()
        await store.issue_grant("a1", "science-skill")
        await store.stop()
        # reopen
        store2 = SkillGrantStore(db_path=path)
        await store2.start()
        assert store2.get_active_grants_sync("a1")[0].skill_name == "science-skill"
        await store2.stop()

    asyncio.run(_run())


# ===================== catalog overlay: per-agent independence =============

def test_effective_skills_default_dept_rank(tmp_path: Path) -> None:
    async def _run() -> None:
        catalog, store = await _make_catalog(tmp_path)
        # A science agent sees the science skill by department default.
        names = {e.name for e in catalog.effective_entries_for_agent(
            "sci-1", department="science", min_rank="ensign",
        )}
        assert "science-skill" in names
        assert "eng-skill" not in names
        await store.stop()

    asyncio.run(_run())


def test_grant_gives_one_agent_a_skill_not_its_dept_peer(tmp_path: Path) -> None:
    """THE headline AC: a skill granted to agent A is in A's effective set and
    NOT in a same-department peer B's."""
    async def _run() -> None:
        catalog, store = await _make_catalog(tmp_path)
        # Grant the engineering skill to ONE science agent.
        await store.issue_grant("sci-1", "eng-skill", reason="captain")

        a = {e.name for e in catalog.effective_entries_for_agent(
            "sci-1", department="science", min_rank="ensign")}
        b = {e.name for e in catalog.effective_entries_for_agent(
            "sci-2", department="science", min_rank="ensign")}

        assert "eng-skill" in a   # granted agent holds it
        assert "eng-skill" not in b  # same-dept peer does NOT
        await store.stop()

    asyncio.run(_run())


def test_restriction_removes_a_default_skill(tmp_path: Path) -> None:
    async def _run() -> None:
        catalog, store = await _make_catalog(tmp_path)
        # Restrict the science skill for a science agent that would otherwise hold it.
        await store.issue_grant("sci-1", "science-skill", is_restriction=True)
        names = {e.name for e in catalog.effective_entries_for_agent(
            "sci-1", department="science", min_rank="ensign")}
        assert "science-skill" not in names
        await store.stop()

    asyncio.run(_run())


def test_no_grant_store_is_backcompat_defaults(tmp_path: Path) -> None:
    async def _run() -> None:
        catalog, _ = await _make_catalog(tmp_path, with_grants=False)
        # Without a grant store, effective == list_entries(dept, rank).
        eff = {e.name for e in catalog.effective_entries_for_agent(
            "sci-1", department="science", min_rank="ensign")}
        default = {e.name for e in catalog.list_entries(
            department="science", min_rank="ensign")}
        assert eff == default

    asyncio.run(_run())


# ===================== unified /capabilities API ===========================

def _api_runtime(tmp_path: Path, *, seed_skill_grant: str | None = None):
    """A runtime holding REAL tool + skill stores + catalog for the API tests.

    The stores are constructed DB-LESS (``db_path=""``/``None``): ``issue_grant``
    still populates the in-memory cache and ``get_active_grants_sync`` /
    ``effective_entries_for_agent`` read from it, so the full grant/restrict
    path is exercised without binding an aiosqlite connection to a setup loop
    that the sync ``TestClient`` would later cross (avoids 'Event loop is
    closed'). Persistence has its own coverage in the store tests above.
    """
    from probos.tools.permissions import ToolPermissionStore

    skills_dir = tmp_path / "skills"
    _write_skills(skills_dir)

    async def _setup():
        catalog = CognitiveSkillCatalog(skills_dir=skills_dir, db_path=None)
        await catalog.start()
        skill_store = SkillGrantStore(db_path="")
        await skill_store.start()
        catalog.set_grant_store(skill_store)
        tool_store = ToolPermissionStore(db_path="")
        await tool_store.start()
        if seed_skill_grant:
            await skill_store.issue_grant("sci-1", seed_skill_grant, reason="captain")
        return catalog, skill_store, tool_store

    catalog, skill_store, tool_store = asyncio.run(_setup())

    agent = SimpleNamespace(id="sci-1", agent_type="scientist", pool="science")
    runtime = MagicMock()
    runtime.registry = MagicMock()
    runtime.registry.get = MagicMock(return_value=agent)
    runtime.tool_permission_store = tool_store
    runtime.tool_registry = None
    runtime.cognitive_skill_catalog = catalog
    runtime.skill_grant_store = skill_store
    runtime.ontology = None
    runtime.trust_network = None
    runtime.emit_event = MagicMock()
    cfg = MagicMock()
    cfg.auth = AuthConfig()
    runtime.config = cfg
    return runtime, agent


def test_get_capabilities_returns_tools_and_skills(tmp_path: Path) -> None:
    runtime, _ = _api_runtime(tmp_path, seed_skill_grant="eng-skill")
    from probos.api import create_app
    client = TestClient(create_app(runtime))
    resp = client.get("/api/agent/sci-1/capabilities")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "tools" in body and "skills" in body
    skill_names = {s["id"] for s in body["skills"]}
    # eng-skill is an explicit grant; sources are tagged.
    assert "eng-skill" in skill_names
    eng = next(s for s in body["skills"] if s["id"] == "eng-skill")
    assert eng["granted"] is True
    assert eng["source"] == "grant"


def test_post_set_skill_grant_then_restrict(tmp_path: Path) -> None:
    runtime, _ = _api_runtime(tmp_path)
    from probos.api import create_app
    client = TestClient(create_app(runtime))
    # Enable the eng skill on sci-1.
    r1 = client.post(
        "/api/agent/sci-1/capabilities/set",
        json={"kind": "skill", "id": "eng-skill", "enabled": True, "reason": "x"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["enabled"] is True
    assert runtime.skill_grant_store.get_active_grants_sync("sci-1")[0].skill_name == "eng-skill"
    # Disable (restrict) the science skill.
    r2 = client.post(
        "/api/agent/sci-1/capabilities/set",
        json={"kind": "skill", "id": "science-skill", "enabled": False},
    )
    assert r2.status_code == 200, r2.text
    restr = [g for g in runtime.skill_grant_store.get_active_grants_sync("sci-1") if g.is_restriction]
    assert any(g.skill_name == "science-skill" for g in restr)


def test_post_set_unknown_agent_404(tmp_path: Path) -> None:
    runtime, _ = _api_runtime(tmp_path)
    runtime.registry.get = MagicMock(return_value=None)
    from probos.api import create_app
    client = TestClient(create_app(runtime))
    resp = client.post(
        "/api/agent/ghost/capabilities/set",
        json={"kind": "skill", "id": "eng-skill", "enabled": True},
    )
    assert resp.status_code == 404


def test_post_set_unknown_skill_404(tmp_path: Path) -> None:
    runtime, _ = _api_runtime(tmp_path)
    from probos.api import create_app
    client = TestClient(create_app(runtime))
    resp = client.post(
        "/api/agent/sci-1/capabilities/set",
        json={"kind": "skill", "id": "nonexistent-skill", "enabled": True},
    )
    assert resp.status_code == 404


def test_post_set_invalid_kind_422(tmp_path: Path) -> None:
    runtime, _ = _api_runtime(tmp_path)
    from probos.api import create_app
    client = TestClient(create_app(runtime))
    resp = client.post(
        "/api/agent/sci-1/capabilities/set",
        json={"kind": "widget", "id": "x", "enabled": True},
    )
    assert resp.status_code == 422
