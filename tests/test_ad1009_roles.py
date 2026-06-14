"""AD-1009: role templates read surface + apply-role.

Roles are the loadout the Captain applies as a starting template (skills → tools
via the AD-889 commission engine), then overrides per agent (AD-1007/1008). This
covers the GET /api/crew/roles view, the POST apply-role action (own role +
explicit role_id + override-preservation), and the AD-889 commission guard fix
(re-apply never clobbers a per-agent decision).

BF-287: real route handlers + real SimpleNamespace ontology/registry + a real
recording ACM stub — no MagicMock at the substrate boundary.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from probos.api_models import ApplyRole
from probos.routers.crew import (
    _build_role_views,
    _served_intents_by_type,
    apply_role,
    list_roles,
)


# ---------------------------------------------------------------------------
# fixtures (BF-287 — real objects, no mocks)
# ---------------------------------------------------------------------------


def _intent(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def _agent(agent_id: str, agent_type: str, intents: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        id=agent_id, agent_type=agent_type,
        intent_descriptors=[_intent(n) for n in intents],
    )


class _Registry:
    def __init__(self, agents: list[SimpleNamespace]) -> None:
        self._agents = {a.id: a for a in agents}

    def get(self, agent_id: str):
        return self._agents.get(agent_id)

    def all(self):
        return list(self._agents.values())


class _Ontology:
    """Minimal real ontology: two roles (counselor + yeoman)."""

    def __init__(self) -> None:
        self._assignments = [
            SimpleNamespace(agent_type="counselor", post_id="post.counselor", callsign="Ezri"),
            SimpleNamespace(agent_type="yeoman", post_id="post.yeoman", callsign="Yeo"),
        ]
        self._posts = {
            "post.counselor": SimpleNamespace(title="Ship's Counselor", department_id="counseling"),
            "post.yeoman": SimpleNamespace(title="Yeoman", department_id="operations"),
        }
        self._templates = {
            "post.counselor": SimpleNamespace(required_skills=[
                SimpleNamespace(skill_id="active-listening", min_proficiency=5),
            ]),
            "post.yeoman": SimpleNamespace(required_skills=[]),
        }

    def get_all_assignments(self):
        return list(self._assignments)

    def get_post(self, post_id):
        return self._posts.get(post_id)

    def get_role_template(self, post_id):
        return self._templates.get(post_id)

    def get_agents_for_post(self, post_id):
        return [a for a in self._assignments if a.post_id == post_id]


class _RecordingACM:
    """Records commission calls; returns a fixed summary (BF-287 — real stub)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def commission(self, agent_id, agent_type, runtime):
        self.calls.append((agent_id, agent_type))
        return {"skills_acquired": ["active-listening"], "tools_granted": ["read_file"]}


def _runtime(*, acm=None, ontology=None, agents=None) -> SimpleNamespace:
    return SimpleNamespace(
        registry=_Registry(agents or []),
        ontology=ontology,
        acm=acm,
        skill_registry=None,   # -> tools resolve to [] (honest-degrade)
        tool_registry=None,
    )


# ---------------------------------------------------------------------------
# served-intent map
# ---------------------------------------------------------------------------


def test_served_intents_by_type_groups_by_agent_type():
    rt = _runtime(agents=[
        _agent("ezri", "counselor", ["counselor_assess", "counselor_wellness_report"]),
        _agent("yeo", "yeoman", []),
    ])
    served = _served_intents_by_type(rt)
    assert served["counselor"] == ["counselor_assess", "counselor_wellness_report"]
    assert served.get("yeoman", []) == []


def test_served_intents_no_registry_degrades():
    assert _served_intents_by_type(SimpleNamespace(registry=None)) == {}


# ---------------------------------------------------------------------------
# GET /api/crew/roles
# ---------------------------------------------------------------------------


async def test_list_roles_builds_views():
    rt = _runtime(
        ontology=_Ontology(),
        agents=[_agent("ezri", "counselor", ["counselor_wellness_report"])],
    )
    body = await list_roles(rt)
    roles = {r["role_id"]: r for r in body["roles"]}
    assert set(roles) == {"post.counselor", "post.yeoman"}
    counselor = roles["post.counselor"]
    assert counselor["agent_type"] == "counselor"
    assert counselor["callsign"] == "Ezri"
    assert counselor["title"] == "Ship's Counselor"
    assert counselor["department"] == "counseling"
    assert counselor["skills"] == [{"id": "active-listening", "min_proficiency": 5}]
    # served capability surfaces from the live counselor agent
    assert counselor["capabilities"] == ["counselor_wellness_report"]
    # no skill/tool registry wired -> tools honest-degrade to []
    assert counselor["tools"] == []


async def test_list_roles_no_ontology_degrades():
    body = await list_roles(_runtime(ontology=None))
    assert body == {"roles": []}


def test_build_role_views_sorted_by_dept_title():
    rt = _runtime(ontology=_Ontology(), agents=[])
    views = _build_role_views(rt)
    # counseling < operations alphabetically
    assert [v["role_id"] for v in views] == ["post.counselor", "post.yeoman"]


# ---------------------------------------------------------------------------
# POST /api/crew/{id}/apply-role
# ---------------------------------------------------------------------------


async def test_apply_role_own_role_recommissions():
    acm = _RecordingACM()
    rt = _runtime(acm=acm, ontology=_Ontology(),
                  agents=[_agent("ezri", "counselor", [])])
    out = await apply_role("ezri", ApplyRole(), rt)
    assert acm.calls == [("ezri", "counselor")]   # own role
    assert out["agent_type"] == "counselor"
    assert out["tools_granted"] == ["read_file"]


async def test_apply_role_explicit_role_id_resolves_agent_type():
    acm = _RecordingACM()
    rt = _runtime(acm=acm, ontology=_Ontology(),
                  agents=[_agent("yeo", "yeoman", [])])
    # apply the Counselor template to the Yeoman ("use as a template to start with")
    out = await apply_role("yeo", ApplyRole(role_id="post.counselor"), rt)
    assert acm.calls == [("yeo", "counselor")]
    assert out["applied_role"] == "post.counselor"
    assert out["agent_type"] == "counselor"


async def test_apply_role_unknown_role_404():
    rt = _runtime(acm=_RecordingACM(), ontology=_Ontology(),
                  agents=[_agent("ezri", "counselor", [])])
    with pytest.raises(HTTPException) as exc:
        await apply_role("ezri", ApplyRole(role_id="post.nope"), rt)
    assert exc.value.status_code == 404


async def test_apply_role_unknown_agent_404():
    rt = _runtime(acm=_RecordingACM(), ontology=_Ontology(), agents=[])
    with pytest.raises(HTTPException) as exc:
        await apply_role("ghost", ApplyRole(), rt)
    assert exc.value.status_code == 404


async def test_apply_role_no_acm_503():
    rt = _runtime(acm=None, ontology=_Ontology(),
                  agents=[_agent("ezri", "counselor", [])])
    with pytest.raises(HTTPException) as exc:
        await apply_role("ezri", ApplyRole(), rt)
    assert exc.value.status_code == 503
