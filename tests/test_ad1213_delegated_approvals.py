"""AD-1213 (#1170): chain-of-command approvals.

A department chief may decide a non-destructive request from crew under their
direct command. The First Officer may decide what the Captain has delegated,
after a grace period in which the Captain has first refusal. Everything else --
every action, every consensus build, anything that cannot be classified -- stays
with the Captain. Every delegated decision is notified to the Captain and
audited, and every doubt refuses to the Captain.

The rig is real wherever the decision is: the real ontology over a copy of
``config/ontology``, real request, work-item, permission and authority stores on
``tmp_path``, a real ``ToolRegistry`` behind a real ``ToolPermissionStore``, and
a real ``AuditLog``. The fakes are the agent registry (id / agent_type / pool),
the notification sink and the clock.

H-5: a suite of refusals that "passes" proves nothing when the rig itself cannot
decide, so every group -- and every fault test -- first shows a positive
decision through the same rig.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import dataclasses
import functools
import json
import logging
import math
import shutil
import sqlite3
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from probos.api_models import CapabilityRequestDecideRequest, SkillRequestDecideRequest
from probos.approval_authority import (
    CAPTAIN_UNAVAILABLE,
    FIRST_OFFICER_DELEGATION,
    ApprovalAuthorityStore,
)
from probos.capability_request import CapabilityRequestStore, repair_action
from probos.cognitive import capability_triage
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.continue_or_ask import CONTINUE_REQUEST_KIND, continue_payload
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.swe_harness.tool_call import render_tool_output
from probos.config import AuthConfig, CapabilityTriageConfig, SystemConfig
from probos.config_models.experience import ApprovalInboxConfig
from probos.consensus.trust import TrustNetwork
from probos.delegated_approvals import (
    _CONTINUE_ACTION,
    _CONTINUE_KIND,
    _CONTINUE_TOOL_ID,
    AUDIT_CATEGORY,
    AUDIT_VOID_CATEGORY,
    AUTHORITY_AUDIT_CATEGORY,
    FIRST_OFFICER_POST_ID,
    MAX_ORIGIN_ITEMS,
    REFUSAL_TEXT,
    REVIEW_TOOL_ID,
    DeciderRole,
    Refusal,
    RequestClass,
    Verdict,
    authority_route,
    classify_capability_request,
    classify_skill_request,
    evaluate,
)
from probos.events import EventType
from probos.ontology import Post, VesselOntologyService
from probos.routers import capability_requests as capability_router
from probos.routers import skill_requests as skill_router
from probos.routers.capability_requests import decide_capability_request
from probos.routers.skill_requests import decide_skill_request
from probos.security.audit import AuditLog
from probos.skill_request import SkillRequestStore
from probos.substrate.identity import generate_agent_id
from probos.tools.action_approvals import ActionApprovalStore
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission, ToolResult, ToolResultPresentation, ToolType
from probos.tools.registry import ToolPermissionDenied, ToolRegistry
from probos.workforce import WorkItemStore
from tests.test_ad1211_approval_fulfils_every_kind import (
    _EventBus,
    _EventLog,
    _RecordingRouter,
    _Runtime,
)

_REPO = Path(__file__).resolve().parents[1]

_FILED = EventType.CAPABILITY_REQUEST_FILED.value
_DECIDED = EventType.CAPABILITY_REQUEST_DECIDED.value
_FULFILLED = EventType.CAPABILITY_REQUEST_FULFILLED.value
_SKILL_FILED = EventType.SKILL_REQUEST_FILED.value
_SKILL_DECIDED = EventType.SKILL_REQUEST_DECIDED.value

RANKS = ("ensign", "lieutenant", "commander", "senior_officer")
READ_MATRIX = {"ensign": "read", "lieutenant": "read", "commander": "read", "senior_officer": "read"}
WRITE_MATRIX = {"ensign": "none", "lieutenant": "write", "commander": "write", "senior_officer": "write"}
ALL_NONE = {rank: "none" for rank in RANKS}

_GRACE = 300  # ApprovalInboxConfig.approval_grace_seconds default
_NOW = 1_000_000.0

_CAPABILITY_AUDIT_KEYS = frozenset({
    "v", "queue", "request_id", "kind", "target", "requester_id",
    "decider_id", "decider_role", "decider_post", "approve", "status", "request_class",
    "pre_cleared", "grace_seconds", "captain_unavailable", "delegation_id", "reason",
})
_AUTHORITY_AUDIT_KEYS = frozenset({"v", "action", "record_id", "expires_at", "revoked", "reason"})
_REVIEWABLE_KEYS = frozenset({
    "queue", "request_id", "kind", "target", "rationale", "requester_id",
    "created_at", "request_class", "role", "decidable_after",
})

_ABSENT = object()


# ---------------------------------------------------------------------------
# Crew. Ids are the production shape: {agent_type}_{pool}_{index}_{hash8}.
# ---------------------------------------------------------------------------


def _crew(agent_type: str, index: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        id=generate_agent_id(agent_type, agent_type, index),
        agent_type=agent_type,
        pool=agent_type,
    )


BUILDER = _crew("builder")                   # builder_officer, engineering
LAFORGE = _crew("engineering_officer")       # chief_engineer
NUMBER_ONE = _crew("architect")              # first_officer
SURGEON = _crew("surgeon")                   # medical
DIAGNOSTICIAN = _crew("diagnostician")       # chief_medical
CREW = (BUILDER, LAFORGE, NUMBER_ONE, SURGEON, DIAGNOSTICIAN)


class _Agents:
    """The agent registry: ``get(agent_id)`` returns the agent, or None."""

    def __init__(self, agents: dict[str, Any]) -> None:
        self._agents = dict(agents)

    @classmethod
    def of(cls, crew: Iterable[Any]) -> _Agents:
        return cls({agent.id: agent for agent in crew})

    def get(self, agent_id: str) -> Any:
        return self._agents.get(agent_id)


# ---------------------------------------------------------------------------
# Recording doubles
# ---------------------------------------------------------------------------


class _Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class _Events:
    """The stores' emit hook. Records every event; optionally forwards to a bus."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, dict[str, Any]]] = []
        self.forward: Any = None
        self.fail_on: str | None = None  # an event type whose emit raises after recording

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        self.seen.append((str(getattr(event_type, "value", event_type)), dict(data)))
        if self.fail_on is not None and self.seen[-1][0] == self.fail_on:
            raise RuntimeError("AD-1213 test: an event subscriber failed")
        if self.forward is not None:
            self.forward(event_type, data)

    def of(self, event_type: str, request_id: str | None = None) -> list[dict[str, Any]]:
        return [
            data for seen_type, data in self.seen
            if seen_type == event_type and (request_id is None or data.get("id") == request_id)
        ]

    def types_for(self, request_id: str) -> list[str]:
        return [seen_type for seen_type, data in self.seen if data.get("id") == request_id]


class _Trust:
    def __init__(self) -> None:
        self.outcomes: list[tuple[str, bool]] = []

    def record_outcome(self, agent_id: str, success: bool, **_kw: Any) -> None:
        self.outcomes.append((agent_id, success))


class _Notes:
    """``runtime.notify(agent_id, title, detail, notification_type)``."""

    def __init__(self) -> None:
        self.sent: list[SimpleNamespace] = []

    def __call__(
        self, agent_id: str, title: str, detail: str = "",
        notification_type: str = "info", action_url: str = "",
    ) -> None:
        self.sent.append(SimpleNamespace(
            agent_id=agent_id, title=title, detail=detail,
            notification_type=notification_type, action_url=action_url,
        ))


class _Settings:
    """The live-settings provider, re-read on every call like the wiring's lambda."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self.failing = False

    def __call__(self) -> Any:
        if self.failing:
            raise RuntimeError("AD-1213 test: the settings provider failed")
        return self.config


class _StubTool:
    """A registrable tool. Classification reads only its rank matrix."""

    def __init__(self, tool_id: str) -> None:
        self._tool_id = tool_id

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._tool_id

    @property
    def tool_type(self) -> ToolType:
        return ToolType.DETERMINISTIC_FUNCTION

    @property
    def description(self) -> str:
        return f"AD-1213 test tool {self._tool_id}"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "string"}

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(output="ok")


def _presentation(budget: int = 200_000) -> ToolResultPresentation:
    """The trusted presentation admission, with a character budget."""

    def render(value: Any) -> str | None:
        text = render_tool_output(value, max_chars=0)
        return text if len(text) <= budget else None

    return ToolResultPresentation(render_complete=render)


def _audit(rig: _Rig, category: str = AUDIT_CATEGORY) -> list[dict[str, Any]]:
    return [json.loads(entry.detail) for entry in rig.audit.entries if entry.category == category]


# ---------------------------------------------------------------------------
# The rig
# ---------------------------------------------------------------------------


class _Rig:
    def __init__(self, tmp_path: Path, ontology: VesselOntologyService) -> None:
        self.tmp = tmp_path
        self.ontology = ontology
        self.clock = _Clock(time.time())
        self.events = _Events()
        self.trust = _Trust()
        self.requests = CapabilityRequestStore(
            db_path=str(tmp_path / "capability_requests.db"),
            emit_event=self.events, trust_network=self.trust,
        )
        self.skills = SkillRequestStore(
            db_path=str(tmp_path / "skill_requests.db"),
            emit_event=self.events, trust_network=self.trust,
        )
        self.work_items = WorkItemStore(db_path=str(tmp_path / "workforce.db"), tick_interval=1000)
        self.perms = ToolPermissionStore(db_path=str(tmp_path / "tool_permissions.db"))
        self.actions = ActionApprovalStore(db_path=str(tmp_path / "action_approvals.db"))
        self.authority = ApprovalAuthorityStore(
            db_path=str(tmp_path / "approval_authority.db"), clock=self.clock,
        )
        self.tools = ToolRegistry()
        self.tools.set_permission_store(self.perms)
        self.tools.register(_StubTool("calc_tool"), default_permissions=dict(READ_MATRIX))
        self.tools.register(_StubTool("deploy_tool"), default_permissions=dict(WRITE_MATRIX))
        self.agents = _Agents.of(CREW)
        self.audit = AuditLog()
        self.notes = _Notes()
        self.settings = _Settings(ApprovalInboxConfig(delegated_approvals_enabled=True))

    async def start(self) -> None:
        for store in (self.requests, self.skills, self.work_items, self.perms, self.actions, self.authority):
            await store.start()

    async def stop(self) -> None:
        for store in (self.authority, self.actions, self.perms, self.work_items, self.skills, self.requests):
            await store.stop()

    def captain_runtime(self, service: Any = _ABSENT) -> SimpleNamespace:
        """Exactly what the two Captain routes and the fulfilment read."""
        runtime = SimpleNamespace(
            capability_request_store=self.requests,
            skill_request_store=self.skills,
            tool_registry=self.tools,
            tool_permission_store=self.perms,
            action_approval_store=self.actions,
            repair_issue_fulfiller=None,
            self_mod_pipeline=None,
            audit_log=self.audit,
            config=SimpleNamespace(approval_inbox=self.settings.config),
        )
        if service is not _ABSENT:
            runtime.delegated_approvals = service
        return runtime

    def service(self, **overrides: Any) -> Any:
        from probos.delegated_approvals import DelegatedApprovalService
        from probos.routers.capability_requests import fulfil_on_approval

        kwargs: dict[str, Any] = {
            "capability_requests": self.requests,
            "skill_requests": self.skills,
            "authority_store": self.authority,
            "agent_registry": self.agents,
            "ontology": self.ontology,
            "tool_registry": self.tools,
            "work_items": self.work_items,
            "audit_log": self.audit,
            "notify": self.notes,
            "fulfil": functools.partial(fulfil_on_approval, self.captain_runtime()),
            "settings": self.settings,
            "clock": self.clock,
        }
        kwargs.update(overrides)
        return DelegatedApprovalService(**kwargs)

    def wiring_runtime(self, *, enabled: bool, **overrides: Any) -> _Runtime:
        """The attributes ``_wire_delegated_approvals`` and the fulfilment read."""
        config = SystemConfig(approval_inbox=ApprovalInboxConfig(delegated_approvals_enabled=enabled))
        runtime = _Runtime(
            config=config,
            approval_authority_store=self.authority,
            capability_request_store=self.requests,
            skill_request_store=self.skills,
            registry=self.agents,
            ontology=self.ontology,
            tool_registry=self.tools,
            tool_permission_store=self.perms,
            work_item_store=self.work_items,
            action_approval_store=self.actions,
            audit_log=self.audit,
            notify=self.notes,
            repair_issue_fulfiller=None,
            self_mod_pipeline=None,
            delegated_approvals=None,
        )
        for name, value in overrides.items():
            setattr(runtime, name, value)
        return runtime

    def authority_runtime(self) -> SimpleNamespace:
        """What the Captain's approval-authority routes read."""
        return SimpleNamespace(
            approval_authority_store=self.authority,
            config=SimpleNamespace(approval_inbox=self.settings.config, auth=AuthConfig()),
            audit_log=self.audit,
        )

    def register_review_tool(self, service: Any) -> Any:
        from probos.tools.review_requests_tool import (
            REVIEW_TOOL_DEFAULT_PERMISSIONS,
            ReviewRequestsTool,
        )

        tool = ReviewRequestsTool(service=service)
        self.tools.register(
            tool, provider="delegated_approvals", tags=["review_requests", "approvals"],
            default_permissions=dict(REVIEW_TOOL_DEFAULT_PERMISSIONS),
        )
        return tool

    async def grant_review_tool(self, agent: Any) -> None:
        await self.perms.issue_grant(
            agent.id, REVIEW_TOOL_ID, ToolPermission.READ,
            issued_by="captain", reason="AD-1213 test: the Captain confers review authority",
        )

    async def grant(self, agent: Any, tool_id: str, *, work_item_id: str | None = None) -> Any:
        return await self.requests.file_request(
            agent_id=agent.id, kind="grant", target=tool_id,
            rationale=f"{agent.agent_type} needs {tool_id}", work_item_id=work_item_id,
        )

    async def delegate(self, *, hours: float = 24) -> Any:
        return await self.authority.issue(
            FIRST_OFFICER_DELEGATION, ttl_seconds=hours * 3600, issued_by="captain",
            reason="AD-1213 test: the Captain delegates approvals",
        )

    def at(self, req: Any, offset: float) -> None:
        """Set the clock ``offset`` seconds after the request was filed."""
        self.clock.t = req.created_at + offset


@pytest.fixture
async def ontology(tmp_path: Path) -> VesselOntologyService:
    dst = tmp_path / "ontology"
    shutil.copytree(_REPO / "config" / "ontology", dst)
    service = VesselOntologyService(dst, data_dir=tmp_path / "ontology-data")
    await service.initialize()
    return service


@pytest.fixture
async def rig(tmp_path: Path, ontology: VesselOntologyService):
    r = _Rig(tmp_path, ontology)
    await r.start()
    try:
        yield r
    finally:
        await r.stop()


async def _decide(
    service: Any, agent: Any, req: Any, *, approve: bool = True,
    reason: str = "AD-1213 test: routine request from my crew.", queue: str = "capability",
) -> Any:
    return await service.decide(agent.id, queue=queue, request_id=req.id, approve=approve, reason=reason)


async def _assert_untouched(rig: _Rig, req: Any, *, audits: int, notes: int) -> None:
    """The refusal left no trace: still pending, no DECIDED, no audit, no notification."""
    current = await rig.requests.get(req.id)
    assert current is not None and current.status == "pending" and current.decided_by == ""
    assert rig.events.of(_DECIDED, req.id) == []
    assert len(_audit(rig)) == audits
    assert len(rig.notes.sent) == notes


async def _premise(rig: _Rig) -> None:
    """H-5: the rig decides, so a refusal that follows is the fault's doing."""
    req = await rig.grant(BUILDER, "calc_tool")
    outcome = await _decide(rig.service(), LAFORGE, req)
    assert outcome.decided, outcome
    assert len(_audit(rig)) == 1 and len(rig.notes.sent) == 1


def _browser_payload() -> dict[str, Any]:
    from probos.cognitive.agentic_dispatch import DispatchToolExecutor

    return DispatchToolExecutor._build_action_payload(
        tool_id="browser", action="eval_js",
        params={"action": "eval_js", "script": "document.title", "session_id": "s-1", "thread_id": "t-1"},
        scope_key="example.com",
    )


def _redirect_payload() -> dict[str, Any]:
    from probos.tools.browser.url_route_guard import RedirectEscalation, build_redirect_ask_payload

    return build_redirect_ask_payload(
        RedirectEscalation(
            agent_id=BUILDER.id, origin="https://example.com/a", target="https://example.org/b",
            method="POST", status=307, scope_key="example.org",
        ),
        session_id="s-1", thread_id="t-1",
    )


def _repair_payload() -> dict[str, Any]:
    return {
        "tool_id": "repair",
        "action": "dispatch",
        "params": {
            "fault_id": "fault-1213", "signature": "a" * 64,
            "targets": ["src/probos/example.py"], "brief": "AD-1213 test repair",
        },
        "scope_key": "seangalliher/ProbOS",
        "session_id": None,
        "thread_id": "t-1",
    }


_ACTION_PAYLOADS = {"browser_tier3": _browser_payload, "bf822_redirect": _redirect_payload, "repair": _repair_payload}


# ===========================================================================
# Classification (pure)
# ===========================================================================


def _registry(**tools: dict[str, str] | None) -> ToolRegistry:
    registry = ToolRegistry()
    for tool_id, matrix in tools.items():
        registry.register(_StubTool(tool_id), default_permissions=matrix)
    return registry


def test_classify_grant_on_a_read_tool_is_non_destructive() -> None:
    registry = _registry(calc_tool=dict(READ_MATRIX), observer=None)
    req = SimpleNamespace(kind="grant", target="calc_tool", payload=None)

    assert classify_capability_request(req, tool_registry=registry) is RequestClass.NON_DESTRUCTIVE
    # An empty matrix is the ship-wide READ default, read by the same predicate.
    empty = SimpleNamespace(kind="grant", target="observer", payload=None)
    assert classify_capability_request(empty, tool_registry=registry) is RequestClass.NON_DESTRUCTIVE


def test_classify_grant_on_a_write_tool_is_destructive() -> None:
    registry = _registry(
        deploy_tool=dict(WRITE_MATRIX), purge_tool={**ALL_NONE, "commander": "full"},
    )

    for target in ("deploy_tool", "purge_tool"):
        req = SimpleNamespace(kind="grant", target=target, payload=None)
        assert classify_capability_request(req, tool_registry=registry) is RequestClass.DESTRUCTIVE, target


def test_classify_grant_on_an_unregistered_tool_is_unclassifiable() -> None:
    registry = _registry(calc_tool=dict(READ_MATRIX))
    # Premise: the triage predicate alone reads a missing registration as READ.
    assert capability_triage._derive_tool_permission(None) is ToolPermission.READ

    for target in ("ghost_tool", "", None, 7):
        req = SimpleNamespace(kind="grant", target=target, payload=None)
        assert classify_capability_request(req, tool_registry=registry) is RequestClass.UNCLASSIFIABLE, target
    known = SimpleNamespace(kind="grant", target="calc_tool", payload=None)
    assert classify_capability_request(known, tool_registry=None) is RequestClass.UNCLASSIFIABLE


def test_classify_grant_of_the_review_tool_is_captain_reserved() -> None:
    registry = _registry(**{REVIEW_TOOL_ID: dict(ALL_NONE)})
    registration = registry.get(REVIEW_TOOL_ID)
    # Premise: the predicate alone would call the all-none matrix READ.
    assert capability_triage._is_non_destructive(capability_triage._derive_tool_permission(registration))

    req = SimpleNamespace(kind="grant", target=REVIEW_TOOL_ID, payload=None)
    assert classify_capability_request(req, tool_registry=registry) is RequestClass.CAPTAIN_RESERVED
    assert classify_capability_request(req, tool_registry=None) is RequestClass.CAPTAIN_RESERVED


@pytest.mark.parametrize("shape", sorted(_ACTION_PAYLOADS))
async def test_classify_every_action_request_is_captain_reserved(rig: _Rig, shape: str) -> None:
    filed = await rig.requests.file_action_request(BUILDER.id, _ACTION_PAYLOADS[shape]())

    assert filed is not None and filed.kind == "action" and filed.payload is not None
    if shape == "repair":
        assert repair_action(filed) is not None  # premise: the real repair shape
    assert classify_capability_request(filed, tool_registry=rig.tools) is RequestClass.CAPTAIN_RESERVED


async def test_classify_continue_needs_the_ad1164_payload(rig: _Rig) -> None:
    filed = await rig.requests.file_request(
        agent_id=BUILDER.id, kind=CONTINUE_REQUEST_KIND, target="continue: calibrate the array",
        rationale="step limit", payload=continue_payload("thread-1"),
    )
    assert classify_capability_request(filed, tool_registry=rig.tools) is RequestClass.NON_DESTRUCTIVE

    good = continue_payload("thread-1")
    for payload in (
        None, {}, "continue", {**good, "tool_id": "browser"}, {**good, "action": "eval_js"},
        {**good, "extra": 1}, {k: v for k, v in good.items() if k != "thread_id"},
    ):
        req = SimpleNamespace(kind="continue", target="continue", payload=payload)
        assert classify_capability_request(req, tool_registry=rig.tools) is RequestClass.UNCLASSIFIABLE, payload


def test_classify_install_is_destructive() -> None:
    for target in ("feedparser", "mcp-server-1", ""):
        req = SimpleNamespace(kind="install", target=target, payload=None)
        assert classify_capability_request(req, tool_registry=None) is RequestClass.DESTRUCTIVE


class _RecordingPipeline:
    """Records the consensus flag the real ``fulfil_build`` designs with."""

    def __init__(self) -> None:
        self.consensus: list[bool] = []

    async def handle_unhandled_intent(self, *_args: Any, **kwargs: Any) -> Any:
        self.consensus.append(kwargs["requires_consensus"])
        return SimpleNamespace(status="rejected")


async def test_classify_build_follows_fulfil_builds_consensus_expression() -> None:
    reserved = [{"requires_consensus": True}, {"requires_consensus": "false"}, {"requires_consensus": 1}]
    destructive = [{"requires_consensus": False}, {}, {"requires_consensus": 0}, None, ["requires_consensus"]]
    pipeline = _RecordingPipeline()

    for payload in reserved + destructive:
        req = SimpleNamespace(kind="build", target="new_agent", payload=payload)
        klass = classify_capability_request(req, tool_registry=None)
        built = await capability_triage.fulfil_build(
            "req-1213", store=None, gap_target="new_agent", rationale="gap",
            self_mod_pipeline=pipeline, design_context=payload,
        )
        assert built is None  # the recording pipeline never activates an agent
        # The classifier and the fulfiller read the SAME expression.
        assert (klass is RequestClass.CAPTAIN_RESERVED) is pipeline.consensus[-1], payload
        expected = RequestClass.CAPTAIN_RESERVED if payload in reserved else RequestClass.DESTRUCTIVE
        assert klass is expected, payload


def test_classify_unknown_kind_and_skill_source_are_unclassifiable() -> None:
    registry = _registry(calc_tool=dict(READ_MATRIX))
    for kind in ("teleport", "", None, "GRANT", "Action"):
        req = SimpleNamespace(kind=kind, target="calc_tool", payload=None)
        assert classify_capability_request(req, tool_registry=registry) is RequestClass.UNCLASSIFIABLE, kind
    assert classify_capability_request(SimpleNamespace(), tool_registry=registry) is RequestClass.UNCLASSIFIABLE

    for source in ("self", "counselor", "chief"):
        assert classify_skill_request(SimpleNamespace(source=source)) is RequestClass.NON_DESTRUCTIVE
    for source in ("captain", "", None, "SELF", 1, ["self"]):
        assert classify_skill_request(SimpleNamespace(source=source)) is RequestClass.UNCLASSIFIABLE, source
    assert classify_skill_request(SimpleNamespace()) is RequestClass.UNCLASSIFIABLE


def test_the_predicate_is_the_triage_predicate() -> None:
    import probos.delegated_approvals as delegated

    assert capability_triage.derive_tool_permission is capability_triage._derive_tool_permission
    assert capability_triage.is_non_destructive is capability_triage._is_non_destructive
    assert delegated.derive_tool_permission is capability_triage._derive_tool_permission
    assert delegated.is_non_destructive is capability_triage._is_non_destructive


def test_continue_constants_match_continue_or_ask() -> None:
    from probos.cognitive import continue_or_ask

    assert (_CONTINUE_KIND, _CONTINUE_TOOL_ID, _CONTINUE_ACTION) == (
        continue_or_ask.CONTINUE_REQUEST_KIND,
        continue_or_ask.CONTINUE_TOOL_ID,
        continue_or_ask.CONTINUE_ACTION,
    )
    assert capability_router._CONTINUE_KIND == _CONTINUE_KIND


# ===========================================================================
# Authority route
# ===========================================================================

# P-1 (arch_probes.py): the designed walk against the real organization.yaml.
_P1_ROWS = {
    ("engineering_officer", "builder"): "chief",
    ("diagnostician", "surgeon"): "chief",
    ("diagnostician", "pathologist"): "chief",
    ("architect", "builder"): "first_officer",
    ("architect", "engineering_officer"): "first_officer",
    ("architect", "scout"): "first_officer",
    ("architect", "security_officer"): "first_officer",
    ("engineering_officer", "surgeon"): "outside",
    ("security_officer", "builder"): "outside",
    ("operations_officer", "training_officer"): "broken_link:chief_operations",
    ("architect", "training_officer"): "broken_link:chief_operations",
    ("architect", "counselor"): "outside",
    ("architect", "architect"): "outside",
    ("builder", "builder"): "outside",
    ("engineering_officer", "engineering_officer"): "outside",
}
_ROLE_FOR = {"chief": DeciderRole.DEPARTMENT_CHIEF, "first_officer": DeciderRole.FIRST_OFFICER}


def test_authority_route_on_the_real_ontology(ontology: VesselOntologyService) -> None:
    assert len(_P1_ROWS) == 15
    got: dict[tuple[str, str], DeciderRole | None] = {}
    for decider_type, requester_type in _P1_ROWS:
        decider_post = ontology.get_post_for_agent(decider_type)
        requester_post = ontology.get_post_for_agent(requester_type)
        assert decider_post is not None and requester_post is not None, (decider_type, requester_type)
        chain = ontology.get_chain_of_command(requester_post.id)
        assert chain and chain[0].id == requester_post.id
        got[(decider_type, requester_type)] = authority_route(chain, decider_post)

    assert got == {key: _ROLE_FOR.get(label) for key, label in _P1_ROWS.items()}
    assert set(got.values()) == {DeciderRole.DEPARTMENT_CHIEF, DeciderRole.FIRST_OFFICER, None}
    # The broken link is a hole in authority_over, not an absent superior: the
    # First Officer IS in the training officer's chain and still gets no route.
    training = ontology.get_chain_of_command(ontology.get_post_for_agent("training_officer").id)
    assert [post.id for post in training] == ["chief_training", "chief_operations", "first_officer", "captain"]
    assert "chief_training" not in (ontology.get_post("chief_operations").authority_over or [])
    assert list(ontology.get_agents_for_post("chief_science")) == []


def test_first_officer_post_id_names_the_real_first_officer(ontology: VesselOntologyService) -> None:
    number_one = ontology.get_post_for_agent("architect")

    assert number_one is not None and number_one.id == FIRST_OFFICER_POST_ID == "first_officer"
    post = ontology.get_post(FIRST_OFFICER_POST_ID)
    assert post is not None and post.reports_to == "captain"
    assert {"chief_engineer", "chief_medical"} <= set(post.authority_over)


def _post(post_id: str, department: str, reports_to: str | None, authority_over: Any = ()) -> Post:
    return Post(
        id=post_id, title=post_id, department_id=department, reports_to=reports_to,
        authority_over=list(authority_over) if authority_over is not None else None,
    )


_FO = _post("first_officer", "bridge", "captain", ["chief_x", "lead"])
_CAPTAIN = _post("captain", "bridge", None, ["first_officer"])


def test_a_direct_superior_in_another_department_is_not_a_chief() -> None:
    worker = _post("worker", "science", "chief_x")
    foreign = _post("chief_x", "engineering", "first_officer", ["worker"])
    assert authority_route([worker, foreign, _FO, _CAPTAIN], foreign) is None
    # Control: the same superior in the worker's department is a chief.
    local = _post("chief_x", "science", "first_officer", ["worker"])
    assert authority_route([worker, local, _FO, _CAPTAIN], local) is DeciderRole.DEPARTMENT_CHIEF
    # The First Officer's route does not depend on the department.
    assert authority_route([worker, foreign, _FO, _CAPTAIN], _FO) is DeciderRole.FIRST_OFFICER
    # A same-department superior two hops up is not a chief either.
    lead = _post("lead", "science", "chief_x", ["worker"])
    upper = _post("chief_x", "science", "first_officer", ["lead"])
    assert authority_route([worker, lead, upper, _FO, _CAPTAIN], upper) is None
    assert authority_route([worker, lead, upper, _FO, _CAPTAIN], lead) is DeciderRole.DEPARTMENT_CHIEF


def test_a_broken_authority_link_grants_nothing() -> None:
    worker = _post("worker", "ops", "lead")
    for broken in (_post("lead", "ops", "first_officer", []), _post("lead", "ops", "first_officer", None)):
        chain = [worker, broken, _FO, _CAPTAIN]
        assert authority_route(chain, _FO) is None
        assert authority_route(chain, broken) is None
    # Control: repairing the one link restores both routes.
    lead = _post("lead", "ops", "first_officer", ["worker"])
    assert authority_route([worker, lead, _FO, _CAPTAIN], _FO) is DeciderRole.FIRST_OFFICER
    assert authority_route([worker, lead, _FO, _CAPTAIN], lead) is DeciderRole.DEPARTMENT_CHIEF
    assert authority_route([], _FO) is None
    assert authority_route([worker], _FO) is None
    assert authority_route([worker, lead, _FO, _CAPTAIN], worker) is None


# ===========================================================================
# evaluate (pure)
# ===========================================================================


def _eval(**overrides: Any) -> Verdict:
    kwargs: dict[str, Any] = {
        "request_class": RequestClass.NON_DESTRUCTIVE,
        "route": DeciderRole.DEPARTMENT_CHIEF,
        "own_requisition": False,
        "chief_barred": False,
        "delegation_live": False,
        "delegation_id": None,
        "captain_unavailable": False,
        "grace_seconds": _GRACE,
        "created_at": _NOW,
        "now": _NOW,
    }
    kwargs.update(overrides)
    return evaluate(**kwargs)


def _fo(**overrides: Any) -> Verdict:
    return _eval(**{
        "route": DeciderRole.FIRST_OFFICER, "delegation_live": True, "delegation_id": "delegation-1",
        **overrides,
    })


def test_chief_decides_non_destructive_with_no_grace() -> None:
    verdict = _eval()

    assert verdict.allowed is True and verdict.refusal is None
    assert verdict.role is DeciderRole.DEPARTMENT_CHIEF
    assert verdict.request_class is RequestClass.NON_DESTRUCTIVE
    assert (verdict.grace_seconds, verdict.decidable_after) == (0, None)
    assert (verdict.delegation_id, verdict.captain_unavailable) == (None, None)
    # The grace never gates a chief, and neither does the clock.
    assert _eval(grace_seconds=86_400).allowed is True
    assert _eval(now=math.nan, created_at="junk", grace_seconds=True).allowed is True


def test_chief_is_refused_a_destructive_request() -> None:
    verdict = _eval(request_class=RequestClass.DESTRUCTIVE)

    assert verdict.allowed is False
    assert verdict.refusal is Refusal.DESTRUCTIVE_NEEDS_FIRST_OFFICER
    assert verdict.request_class is RequestClass.DESTRUCTIVE
    assert _eval(request_class=RequestClass.DESTRUCTIVE, delegation_live=True, captain_unavailable=True).refusal is (
        Refusal.DESTRUCTIVE_NEEDS_FIRST_OFFICER
    )


def test_chief_is_barred_from_a_chief_filed_skill_request() -> None:
    assert _eval(chief_barred=True).refusal is Refusal.OWN_REQUISITION
    for junk in (None, 0, 1, "no"):
        assert _eval(chief_barred=junk).refusal is Refusal.OWN_REQUISITION, junk
    # The bar is the chief's alone: the First Officer's route ignores it.
    assert _fo(chief_barred=True, now=_NOW + _GRACE).allowed is True


def test_first_officer_needs_a_live_delegation() -> None:
    later = _NOW + _GRACE + 1
    for absent in (False, None, 1, "yes"):
        verdict = _fo(delegation_live=absent, now=later)
        assert verdict.refusal is Refusal.DELEGATION_ABSENT, absent

    allowed = _fo(now=later)
    assert allowed.allowed is True and allowed.role is DeciderRole.FIRST_OFFICER
    assert allowed.delegation_id == "delegation-1"


def test_first_officer_waits_out_the_grace_period() -> None:
    inside = _fo(now=_NOW + _GRACE - 0.001)
    assert inside.refusal is Refusal.GRACE_PERIOD
    assert inside.decidable_after == _NOW + _GRACE
    assert (inside.grace_seconds, inside.captain_unavailable, inside.delegation_id) == (_GRACE, False, "delegation-1")

    boundary = _fo(now=_NOW + _GRACE)  # H-6: decidable at exactly the boundary
    assert boundary.allowed is True and boundary.decidable_after is None
    assert boundary.grace_seconds == _GRACE


def test_captain_unavailable_zeroes_the_grace() -> None:
    verdict = _fo(captain_unavailable=True, now=_NOW)

    assert verdict.allowed is True
    assert (verdict.grace_seconds, verdict.captain_unavailable) == (0, True)
    # Only exactly True widens: a truthy junk value keeps the full grace.
    for junk in (1, "yes", None):
        assert _fo(captain_unavailable=junk, now=_NOW).refusal is Refusal.GRACE_PERIOD, junk


def test_first_officer_decides_destructive_after_grace() -> None:
    verdict = _fo(request_class=RequestClass.DESTRUCTIVE, now=_NOW + _GRACE + 1)

    assert verdict.allowed is True
    assert (verdict.role, verdict.request_class) == (DeciderRole.FIRST_OFFICER, RequestClass.DESTRUCTIVE)
    assert (verdict.grace_seconds, verdict.captain_unavailable, verdict.delegation_id) == (
        _GRACE, False, "delegation-1",
    )


@pytest.mark.parametrize("route", [DeciderRole.DEPARTMENT_CHIEF, DeciderRole.FIRST_OFFICER, None])
@pytest.mark.parametrize(
    ("klass", "refusal"),
    [
        (RequestClass.CAPTAIN_RESERVED, Refusal.CAPTAIN_RESERVED),
        (RequestClass.UNCLASSIFIABLE, Refusal.UNCLASSIFIABLE),
    ],
)
def test_reserved_and_unclassifiable_are_refused_to_everyone(
    route: DeciderRole | None, klass: RequestClass, refusal: Refusal,
) -> None:
    verdict = _eval(
        request_class=klass, route=route, delegation_live=True, delegation_id="delegation-1",
        captain_unavailable=True, now=_NOW + 86_400,
    )

    assert verdict.refusal is refusal and verdict.allowed is False
    assert verdict.request_class is klass


def test_own_requisition_wins_over_every_route() -> None:
    for route in (DeciderRole.DEPARTMENT_CHIEF, DeciderRole.FIRST_OFFICER, None):
        for klass in RequestClass:
            verdict = _eval(
                own_requisition=True, request_class=klass, route=route, delegation_live=True,
                captain_unavailable=True, now=_NOW + 86_400,
            )
            assert verdict.refusal is Refusal.OWN_REQUISITION, (route, klass)
    # Anything but exactly False is treated as the decider's own requisition.
    for junk in (None, 0, 1, "no"):
        assert _eval(own_requisition=junk).refusal is Refusal.OWN_REQUISITION, junk
    assert _eval(route=None).refusal is Refusal.OUTSIDE_AUTHORITY  # control: no route, not own


def test_junk_clock_created_at_or_grace_refuses() -> None:
    later = _NOW + 86_400
    assert _fo(now=later).allowed is True  # premise: the same verdict without junk
    for junk in (math.nan, math.inf, -math.inf, True, "300", None):
        assert _fo(now=junk).refusal is Refusal.STATE_UNREADABLE, ("now", junk)
        assert _fo(created_at=junk, now=later).refusal is Refusal.STATE_UNREADABLE, ("created_at", junk)
    for junk in (math.nan, math.inf, True, False, "300", -1, 300.0, None, 86_401):
        assert _fo(grace_seconds=junk, now=later).refusal is Refusal.STATE_UNREADABLE, ("grace", junk)
    assert _fo(grace_seconds=0, now=_NOW).allowed is True
    assert _fo(grace_seconds=86_400, now=_NOW + 86_400).allowed is True


def test_new_config_fields_default_off_and_validate_bounds() -> None:
    config = ApprovalInboxConfig()

    assert (
        config.delegated_approvals_enabled, config.approval_grace_seconds,
        config.first_officer_delegation_max_ttl_hours, config.captain_unavailable_max_ttl_hours,
    ) == (False, 300, 168, 72)
    assert SystemConfig().approval_inbox.delegated_approvals_enabled is False
    new = [
        "delegated_approvals_enabled", "approval_grace_seconds",
        "first_officer_delegation_max_ttl_hours", "captain_unavailable_max_ttl_hours",
    ]
    # AD-1214 appends its three fields after these four, so this pin is index-relative
    # (it was ``[-4:]``, which pinned "last" rather than "in this order").
    field_names = list(ApprovalInboxConfig.model_fields)
    first = field_names.index(new[0])
    assert field_names[first:first + 4] == new
    for name in new:
        assert "AD-1213" in (ApprovalInboxConfig.model_fields[name].description or ""), name
    for name, value in (
        ("approval_grace_seconds", -1), ("approval_grace_seconds", 86_401),
        ("first_officer_delegation_max_ttl_hours", 0), ("first_officer_delegation_max_ttl_hours", 721),
        ("captain_unavailable_max_ttl_hours", 0), ("captain_unavailable_max_ttl_hours", 721),
    ):
        with pytest.raises(ValidationError):
            ApprovalInboxConfig(**{name: value})
    edges = ApprovalInboxConfig(
        approval_grace_seconds=0, first_officer_delegation_max_ttl_hours=720,
        captain_unavailable_max_ttl_hours=1,
    )
    assert (edges.approval_grace_seconds, edges.first_officer_delegation_max_ttl_hours) == (0, 720)


# ===========================================================================
# Service
# ===========================================================================


async def test_chief_decides_a_subordinates_read_grant_and_is_recorded_as_the_decider(rig: _Rig) -> None:
    service = rig.service()
    req = await rig.grant(BUILDER, "calc_tool")

    outcome = await _decide(service, LAFORGE, req, reason="Read access is routine.")

    assert outcome.decided is True and outcome.refusal is None
    assert (outcome.queue, outcome.request_id, outcome.status) == ("capability", req.id, "fulfilled")
    assert (outcome.role, outcome.request_class) == (DeciderRole.DEPARTMENT_CHIEF, RequestClass.NON_DESTRUCTIVE)
    assert (outcome.fulfilled, outcome.audited, outcome.notified) == (True, True, True)
    stored = await rig.requests.get(req.id)
    assert stored.decided_by == LAFORGE.id and stored.decision_reason == "Read access is routine."
    assert rig.events.of(_DECIDED, req.id) == [{
        "id": req.id, "agent_id": BUILDER.id, "kind": "grant", "status": "approved",
        "decided_by": LAFORGE.id, "decision_reason": "Read access is routine.",
    }]
    assert rig.trust.outcomes == [(BUILDER.id, True)]
    grants = rig.perms.get_active_grants_sync(BUILDER.id, "calc_tool")
    assert [(g.permission, g.issued_by) for g in grants] == [(ToolPermission.READ, LAFORGE.id)]


async def test_chief_is_refused_another_departments_request(rig: _Rig) -> None:
    service = rig.service()
    mine = await rig.grant(BUILDER, "calc_tool")
    assert (await _decide(service, LAFORGE, mine)).decided  # premise

    theirs = await rig.grant(SURGEON, "calc_tool")
    refused = await _decide(service, LAFORGE, theirs)

    assert refused.refusal is Refusal.OUTSIDE_AUTHORITY and refused.decided is False
    await _assert_untouched(rig, theirs, audits=1, notes=1)
    # The surgeon's own chief can.
    assert (await _decide(service, DIAGNOSTICIAN, theirs)).decided
    # A requester the registry cannot resolve is refused, never guessed at.
    stranger = await rig.requests.file_request(agent_id="ghost_ghost_0_deadbeef", kind="grant", target="calc_tool")
    assert (await _decide(service, LAFORGE, stranger)).refusal is Refusal.REQUESTER_UNRESOLVED


async def test_destructive_request_refused_to_chief_accepted_from_first_officer(rig: _Rig) -> None:
    service = rig.service()
    req = await rig.grant(BUILDER, "deploy_tool")

    chief = await _decide(service, LAFORGE, req)
    assert chief.refusal is Refusal.DESTRUCTIVE_NEEDS_FIRST_OFFICER
    assert chief.request_class is RequestClass.DESTRUCTIVE
    await _assert_untouched(rig, req, audits=0, notes=0)

    await rig.delegate()
    rig.at(req, _GRACE + 1)
    xo = await _decide(service, NUMBER_ONE, req, reason="Deploy approved for the refit.")

    assert xo.decided and xo.role is DeciderRole.FIRST_OFFICER
    assert (xo.status, xo.fulfilled) == ("fulfilled", True)
    grants = rig.perms.get_active_grants_sync(BUILDER.id, "deploy_tool")
    assert [(g.permission, g.issued_by) for g in grants] == [(ToolPermission.WRITE, NUMBER_ONE.id)]


@pytest.mark.parametrize(
    "case", ["chief_created_the_linked_item", "first_officer_created_its_parent", "requester_decides_itself"],
)
async def test_no_one_decides_their_own_requisition(rig: _Rig, case: str) -> None:
    service = rig.service()
    await rig.delegate()

    async def linked(created_by: str, *, parent_creator: str | None = None) -> str:
        parent_id = None
        if parent_creator is not None:
            parent = await rig.work_items.create_work_item(
                title="Refit plan", description="Refit plan", work_type="task", created_by=parent_creator,
            )
            parent_id = parent.id
        item = await rig.work_items.create_work_item(
            title="Refit step", description="Refit step", work_type="task",
            assigned_to=BUILDER.id, created_by=created_by, parent_id=parent_id,
        )
        return item.id

    if case == "chief_created_the_linked_item":
        decider, tool = LAFORGE, "calc_tool"
        control = await rig.grant(BUILDER, tool, work_item_id=await linked("captain"))
        req = await rig.grant(BUILDER, tool, work_item_id=await linked(LAFORGE.id))
    elif case == "first_officer_created_its_parent":
        decider, tool = NUMBER_ONE, "deploy_tool"
        control = await rig.grant(BUILDER, tool, work_item_id=await linked("captain", parent_creator="captain"))
        req = await rig.grant(BUILDER, tool, work_item_id=await linked("captain", parent_creator=NUMBER_ONE.id))
    else:
        decider, tool = BUILDER, "calc_tool"
        control = None
        req = await rig.grant(BUILDER, tool)
    rig.at(req, _GRACE + 1)

    if control is not None:  # H-5: the same shape without the decider's hand in it decides
        assert (await _decide(service, decider, control)).decided
    refused = await _decide(service, decider, req)

    assert refused.refusal is Refusal.OWN_REQUISITION
    await _assert_untouched(rig, req, audits=0 if control is None else 1, notes=0 if control is None else 1)


async def test_captain_decides_inside_the_grace_window_while_the_first_officer_is_refused(rig: _Rig) -> None:
    service = rig.service()
    runtime = rig.captain_runtime(service)
    await rig.delegate()
    req = await rig.grant(BUILDER, "deploy_tool")
    rig.at(req, 10)

    refused = await _decide(service, NUMBER_ONE, req)
    assert refused.refusal is Refusal.GRACE_PERIOD
    assert refused.decidable_after == req.created_at + _GRACE

    body = await decide_capability_request(
        req.id, CapabilityRequestDecideRequest(approve=True, reason="Captain approves now."), runtime=runtime,
    )
    assert body["request"]["decided_by"] == "captain"
    assert (body["request"]["status"], body["fulfilled"]) == ("fulfilled", True)

    rig.at(req, _GRACE + 1)
    assert (await _decide(service, NUMBER_ONE, req)).refusal is Refusal.NOT_PENDING


async def test_every_delegated_decision_is_notified_and_audited(rig: _Rig) -> None:
    service = rig.service()
    chief_req = await rig.grant(BUILDER, "calc_tool")
    chief = await _decide(service, LAFORGE, chief_req, reason="Routine read access for the builder.")
    assert chief.decided and chief.audited is True and chief.notified is True

    xo_req = await rig.grant(BUILDER, "deploy_tool")
    delegation = await rig.delegate()
    rig.at(xo_req, _GRACE + 1)
    xo = await _decide(service, NUMBER_ONE, xo_req, approve=False, reason="Not during this watch.")
    assert xo.decided and xo.status == "denied" and xo.fulfilled is False

    entries = [entry for entry in rig.audit.entries if entry.category == AUDIT_CATEGORY]
    assert len(entries) == 2
    for entry in entries:  # one compact, key-sorted JSON object
        assert entry.detail == json.dumps(json.loads(entry.detail), sort_keys=True, separators=(",", ":"))
    first, second = (json.loads(entry.detail) for entry in entries)
    assert set(first) == set(second) == _CAPABILITY_AUDIT_KEYS
    assert first == {
        "v": 1, "queue": "capability", "request_id": chief_req.id, "kind": "grant", "target": "calc_tool",
        "requester_id": BUILDER.id, "decider_id": LAFORGE.id, "decider_role": "department_chief",
        "decider_post": "chief_engineer", "approve": True, "status": "approved",
        "request_class": "non_destructive", "pre_cleared": False, "grace_seconds": None,
        "captain_unavailable": None, "delegation_id": None, "reason": "Routine read access for the builder.",
    }
    assert second == {
        "v": 1, "queue": "capability", "request_id": xo_req.id, "kind": "grant", "target": "deploy_tool",
        "requester_id": BUILDER.id, "decider_id": NUMBER_ONE.id, "decider_role": "first_officer",
        "decider_post": "first_officer", "approve": False, "status": "denied",
        "request_class": "destructive", "pre_cleared": False, "grace_seconds": _GRACE,
        "captain_unavailable": False, "delegation_id": delegation.id, "reason": "Not during this watch.",
    }

    assert [(n.agent_id, n.notification_type) for n in rig.notes.sent] == [
        (LAFORGE.id, "info"), (NUMBER_ONE.id, "info"),
    ]
    assert rig.notes.sent[0].title == f"Delegated decision: approved grant request {chief_req.id[:8]}"
    assert rig.notes.sent[1].title == f"Delegated decision: denied grant request {xo_req.id[:8]}"
    detail = rig.notes.sent[0].detail
    # A-16: these tails used to pin "builder.." and "watch..", the doubled period since fixed.
    tail = (
        f"{LAFORGE.id} approved {BUILDER.id}'s grant request for 'calc_tool'. Class: non_destructive. "
        "Reason: Routine read access for the builder. Not pre-cleared (AD-1213)."
    )
    assert detail.endswith(tail) and detail != tail  # a role label leads
    assert rig.notes.sent[1].detail.endswith(
        f"{NUMBER_ONE.id} denied {BUILDER.id}'s grant request for 'deploy_tool'. Class: destructive. "
        "Reason: Not during this watch. Not pre-cleared (AD-1213)."
    )


@pytest.mark.parametrize(
    ("reason", "shown"),
    [
        ("Routine read access for the builder", "Routine read access for the builder"),
        ("Routine read access for the builder.", "Routine read access for the builder"),
        ("Routine read access for the builder...", "Routine read access for the builder"),
        ("x" * 238 + ". " + "y" * 20, "x" * 238),
    ],
    ids=["no_period", "one_period", "several_periods", "cut_after_a_period"],
)
async def test_captain_notification_ends_the_reason_with_exactly_one_period(
    rig: _Rig, reason: str, shown: str,
) -> None:
    from probos.cognitive.decomposer import is_capability_gap

    req = await rig.grant(BUILDER, "calc_tool")

    outcome = await _decide(rig.service(), LAFORGE, req, reason=reason)

    assert outcome.decided and outcome.notified is True
    [note] = rig.notes.sent
    assert note.detail.endswith(f"Reason: {shown}. Not pre-cleared (AD-1213)."), note.detail
    assert ".." not in note.detail and ". ." not in note.detail
    assert is_capability_gap(note.title) is False and is_capability_gap(note.detail) is False
    assert (await rig.requests.get(req.id)).decision_reason == reason  # the record keeps the reason as given


async def test_captain_decisions_are_audited_while_enabled(rig: _Rig) -> None:
    service = rig.service()
    runtime = rig.captain_runtime(service)
    req = await rig.grant(BUILDER, "calc_tool")

    body = await decide_capability_request(
        req.id, CapabilityRequestDecideRequest(approve=True, reason="Captain approves."), runtime=runtime,
    )

    assert body["request"]["decided_by"] == "captain" and body["fulfilled"] is True
    [entry] = _audit(rig)
    assert set(entry) == _CAPABILITY_AUDIT_KEYS
    assert (
        entry["queue"], entry["request_id"], entry["decider_id"], entry["decider_role"], entry["approve"],
        entry["status"], entry["request_class"], entry["pre_cleared"], entry["delegation_id"],
    ) == ("capability", req.id, "captain", "captain", True, "approved", "non_destructive", False, None)
    assert rig.notes.sent == []  # the Captain is not notified of the Captain's own decision

    # A BF-722 fulfilment retry is not a new decision and adds no audit entry.
    stuck_runtime = rig.captain_runtime(service)
    stuck_runtime.tool_permission_store = None
    stuck = await rig.grant(BUILDER, "calc_tool")
    first = await decide_capability_request(stuck.id, CapabilityRequestDecideRequest(approve=True), runtime=stuck_runtime)
    assert (first["request"]["status"], first["fulfilled"]) == ("approved", False)
    retry = await decide_capability_request(stuck.id, CapabilityRequestDecideRequest(approve=True), runtime=stuck_runtime)
    assert retry["fulfilled"] is False
    assert [e["request_id"] for e in _audit(rig)] == [req.id, stuck.id]

    skill = await rig.skills.file_request(BUILDER.id, "damage_control", skill_label="Damage control")
    await decide_skill_request(skill.id, SkillRequestDecideRequest(approve=True), runtime=runtime)
    last = _audit(rig)[-1]
    assert (last["queue"], last["request_id"], last["skill_id"], last["decider_role"]) == (
        "skill", skill.id, "damage_control", "captain",
    )
    assert "kind" not in last


async def test_agents_never_issue_standing_rules(rig: _Rig) -> None:
    rig.settings.config = ApprovalInboxConfig(
        delegated_approvals_enabled=True, enabled=True, standing_rules_enabled=True,
    )
    service = rig.service()

    async def file_continue() -> Any:
        return await rig.requests.file_request(
            agent_id=BUILDER.id, kind=CONTINUE_REQUEST_KIND, target="continue: calibrate the array",
            rationale="step limit", payload=continue_payload("thread-1"),
        )

    # Premise: the same rig issues a standing rule when the CAPTAIN asks for one.
    captains = await file_continue()
    body = await decide_capability_request(
        captains.id, CapabilityRequestDecideRequest(approve=True, grant_standing=True),
        runtime=rig.captain_runtime(service),
    )
    assert body["standing_rule"] is not None
    assert len(await rig.actions.list_approvals(active_only=False)) == 1

    req = await file_continue()
    outcome = await _decide(service, LAFORGE, req, reason="Keep going.")

    assert outcome.decided and outcome.status == "fulfilled" and outcome.request_class is RequestClass.NON_DESTRUCTIVE
    assert len(await rig.actions.list_approvals(active_only=False)) == 1


async def test_skill_request_decided_by_the_chief(rig: _Rig) -> None:
    service = rig.service()
    skill = await rig.skills.file_request(
        BUILDER.id, "damage_control", skill_label="Damage control", source="self", justification="Drills",
    )

    outcome = await service.decide(
        LAFORGE.id, queue="skill", request_id=skill.id, approve=True, reason="Good use of the watch.",
    )

    assert outcome.decided and (outcome.queue, outcome.status) == ("skill", "approved")
    assert outcome.fulfilled is None
    stored = await rig.skills.get(skill.id)
    assert (stored.status, stored.decided_by) == ("approved", LAFORGE.id)
    decided = rig.events.of(_SKILL_DECIDED, skill.id)
    assert len(decided) == 1 and decided[0]["decided_by"] == LAFORGE.id
    entry = _audit(rig)[-1]
    assert (entry["queue"], entry["skill_id"], entry["decider_role"], entry["request_class"]) == (
        "skill", "damage_control", "department_chief", "non_destructive",
    )
    assert "kind" not in entry
    # A chief-filed skill request bars the chief route.
    barred = await rig.skills.file_request(BUILDER.id, "navigation", source="chief")
    refused = await service.decide(LAFORGE.id, queue="skill", request_id=barred.id, approve=True, reason="Mine.")
    assert refused.refusal is Refusal.OWN_REQUISITION
    assert (await rig.skills.get(barred.id)).status == "requested"


async def test_disabling_at_runtime_stops_delegated_decisions(rig: _Rig) -> None:
    service = rig.service()
    runtime = rig.captain_runtime(service)
    first = await rig.grant(BUILDER, "calc_tool")
    assert (await _decide(service, LAFORGE, first)).decided  # premise: on

    rig.settings.config = ApprovalInboxConfig(delegated_approvals_enabled=False)
    second = await rig.grant(BUILDER, "calc_tool")
    refused = await _decide(service, LAFORGE, second)

    assert refused.refusal is Refusal.NOT_ENABLED
    await _assert_untouched(rig, second, audits=1, notes=1)
    body = await decide_capability_request(second.id, CapabilityRequestDecideRequest(approve=True), runtime=runtime)
    assert body["request"]["decided_by"] == "captain"
    assert len(_audit(rig)) == 1  # the Captain's decision is not audited while off


async def test_list_shows_only_requests_under_the_deciders_authority(rig: _Rig) -> None:
    from probos.delegated_approvals import DelegatedApprovalRefused

    service = rig.service()
    mine = await rig.grant(BUILDER, "calc_tool")
    theirs = await rig.grant(SURGEON, "calc_tool")
    await rig.requests.file_action_request(BUILDER.id, _browser_payload())  # reserved: never listed
    skill = await rig.skills.file_request(BUILDER.id, "damage_control", source="self")

    items, more = await service.list_reviewable(LAFORGE.id)

    assert more is False
    assert {(item.queue, item.request_id) for item in items} == {("capability", mine.id), ("skill", skill.id)}
    [grant] = [item for item in items if item.queue == "capability"]
    assert (grant.kind, grant.target, grant.requester_id, grant.request_class, grant.role, grant.decidable_after) == (
        "grant", "calc_tool", BUILDER.id, RequestClass.NON_DESTRUCTIVE, DeciderRole.DEPARTMENT_CHIEF, None,
    )
    assert grant.created_at == mine.created_at and grant.rationale == mine.rationale

    await rig.delegate()
    rig.at(mine, 10)
    fo_items, _ = await service.list_reviewable(NUMBER_ONE.id)
    grants = [item for item in fo_items if item.queue == "capability"]
    assert [item.request_id for item in grants] == [mine.id, theirs.id]  # oldest first
    assert all(item.role is DeciderRole.FIRST_OFFICER for item in grants)
    assert {item.request_id: item.decidable_after for item in grants} == {
        mine.id: mine.created_at + _GRACE, theirs.id: theirs.created_at + _GRACE,
    }

    with pytest.raises(DelegatedApprovalRefused):
        await service.list_reviewable("ghost_ghost_0_deadbeef")
    rig.settings.config = ApprovalInboxConfig(delegated_approvals_enabled=False)
    with pytest.raises(DelegatedApprovalRefused):
        await service.list_reviewable(LAFORGE.id)


# ===========================================================================
# Fault injection -- every doubt refuses to the Captain
# ===========================================================================


class _RaisingOntology:
    """The real ontology with one lookup made to raise."""

    def __init__(self, inner: Any, method: str) -> None:
        self._inner = inner
        self._method = method

    def __getattr__(self, name: str) -> Any:
        if name == self._method:
            def _raise(*_args: Any, **_kwargs: Any) -> Any:
                raise RuntimeError(f"AD-1213 test: {name} failed")

            return _raise
        return getattr(self._inner, name)


async def test_fault_ontology_post_lookup_raises(rig: _Rig) -> None:
    await _premise(rig)
    req = await rig.grant(BUILDER, "calc_tool")

    outcome = await _decide(rig.service(ontology=_RaisingOntology(rig.ontology, "get_post_for_agent")), LAFORGE, req)

    assert outcome.refusal is Refusal.DECIDER_UNRESOLVED
    await _assert_untouched(rig, req, audits=1, notes=1)


async def test_fault_chain_of_command_raises(rig: _Rig) -> None:
    await _premise(rig)
    req = await rig.grant(BUILDER, "calc_tool")

    outcome = await _decide(rig.service(ontology=_RaisingOntology(rig.ontology, "get_chain_of_command")), LAFORGE, req)

    assert outcome.refusal is Refusal.STATE_UNREADABLE
    await _assert_untouched(rig, req, audits=1, notes=1)


async def test_fault_ontology_absent(rig: _Rig) -> None:
    await _premise(rig)
    req = await rig.grant(BUILDER, "calc_tool")

    outcome = await _decide(rig.service(ontology=None), LAFORGE, req)

    assert outcome.refusal is Refusal.DECIDER_UNRESOLVED
    await _assert_untouched(rig, req, audits=1, notes=1)


@pytest.mark.parametrize("case", ["unregistered", "id_mismatch", "blank_type", "no_registry"])
async def test_fault_decider_not_registered_or_id_mismatch(rig: _Rig, case: str) -> None:
    await _premise(rig)
    req = await rig.grant(BUILDER, "calc_tool")
    registries = {
        "unregistered": _Agents.of([BUILDER]),
        "id_mismatch": _Agents({
            **{a.id: a for a in CREW},
            LAFORGE.id: SimpleNamespace(id="someone-else", agent_type="engineering_officer", pool="engineering_officer"),
        }),
        "blank_type": _Agents({
            **{a.id: a for a in CREW},
            LAFORGE.id: SimpleNamespace(id=LAFORGE.id, agent_type="", pool="engineering_officer"),
        }),
        "no_registry": None,
    }

    outcome = await _decide(rig.service(agent_registry=registries[case]), LAFORGE, req)

    assert outcome.refusal is Refusal.DECIDER_UNRESOLVED
    await _assert_untouched(rig, req, audits=1, notes=1)


async def test_fault_authority_store_unreadable(rig: _Rig) -> None:
    await _premise(rig)
    unstarted = ApprovalAuthorityStore(db_path=str(rig.tmp / "unstarted.db"), clock=rig.clock)
    service = rig.service(authority_store=unstarted)
    req = await rig.grant(BUILDER, "deploy_tool")
    rig.at(req, _GRACE + 1)

    refused = await _decide(service, NUMBER_ONE, req)

    assert refused.refusal is Refusal.STATE_UNREADABLE
    await _assert_untouched(rig, req, audits=1, notes=1)
    # The chief route never reads the store, so an outage does not block a chief.
    read = await rig.grant(BUILDER, "calc_tool")
    assert (await _decide(service, LAFORGE, read)).decided


@pytest.mark.parametrize("case", ["never_issued", "revoked", "expired"])
async def test_fault_delegation_absent_or_expired(rig: _Rig, case: str) -> None:
    await _premise(rig)
    service = rig.service()
    if case == "revoked":
        await rig.delegate()
        assert await rig.authority.revoke(FIRST_OFFICER_DELEGATION, revoked_by="captain") == 1
    elif case == "expired":
        await rig.authority.issue(FIRST_OFFICER_DELEGATION, ttl_seconds=60, issued_by="captain")
    req = await rig.grant(BUILDER, "deploy_tool")
    rig.at(req, _GRACE + 1)

    refused = await _decide(service, NUMBER_ONE, req)

    assert refused.refusal is Refusal.DELEGATION_ABSENT
    await _assert_untouched(rig, req, audits=1, notes=1)
    await rig.delegate()  # control: a live delegation lets the same call decide
    assert (await _decide(service, NUMBER_ONE, req)).decided


async def test_fault_audit_log_absent(rig: _Rig) -> None:
    await _premise(rig)
    req = await rig.grant(BUILDER, "calc_tool")

    outcome = await _decide(rig.service(audit_log=None), LAFORGE, req)

    assert outcome.refusal is Refusal.AUDIT_UNAVAILABLE
    await _assert_untouched(rig, req, audits=1, notes=1)


class _RaisingTools:
    def get(self, tool_id: str) -> Any:
        raise RuntimeError("AD-1213 test: the tool registry failed")


async def test_fault_tool_registry_raises(rig: _Rig) -> None:
    await _premise(rig)
    req = await rig.grant(BUILDER, "calc_tool")

    outcome = await _decide(rig.service(tool_registry=_RaisingTools()), LAFORGE, req)

    assert outcome.refusal is Refusal.STATE_UNREADABLE
    await _assert_untouched(rig, req, audits=1, notes=1)


class _FakeItems:
    """A work-item lookup: ``{id: (parent_id, created_by)}``; optionally raising."""

    def __init__(self, items: dict[str, tuple[str | None, str]], *, raising: bool = False) -> None:
        self._items = items
        self._raising = raising

    async def get_work_item(self, work_item_id: str) -> Any:
        if self._raising:
            raise sqlite3.OperationalError("AD-1213 test: workforce.db failed")
        if work_item_id not in self._items:
            return None
        parent_id, created_by = self._items[work_item_id]
        return SimpleNamespace(id=work_item_id, parent_id=parent_id, created_by=created_by, assigned_to=BUILDER.id)


def _chain_of_items(length: int) -> dict[str, tuple[str | None, str]]:
    return {f"w{i}": (f"w{i + 1}" if i + 1 < length else None, "captain") for i in range(length)}


@pytest.mark.parametrize(
    "case", ["store_absent", "lookup_raises", "missing_item", "missing_parent", "cycle", "ninth_item"],
)
async def test_fault_work_item_chain_unreadable(rig: _Rig, case: str) -> None:
    await _premise(rig)
    lookups: dict[str, Any] = {
        "store_absent": None,
        "lookup_raises": _FakeItems({"w0": (None, "captain")}, raising=True),
        "missing_item": _FakeItems({}),
        "missing_parent": _FakeItems({"w0": ("ghost", "captain")}),
        "cycle": _FakeItems({"w0": ("w1", "captain"), "w1": ("w0", "captain")}),
        "ninth_item": _FakeItems(_chain_of_items(MAX_ORIGIN_ITEMS + 1)),
    }
    if case == "ninth_item":  # control: exactly MAX_ORIGIN_ITEMS items is readable
        full = await rig.grant(BUILDER, "calc_tool", work_item_id="w0")
        assert (await _decide(rig.service(work_items=_FakeItems(_chain_of_items(MAX_ORIGIN_ITEMS))), LAFORGE, full)).decided
    req = await rig.grant(BUILDER, "calc_tool", work_item_id="w0")

    outcome = await _decide(rig.service(work_items=lookups[case]), LAFORGE, req)

    assert outcome.refusal is Refusal.STATE_UNREADABLE
    audits = 2 if case == "ninth_item" else 1
    await _assert_untouched(rig, req, audits=audits, notes=audits)


class _GraceRaises:
    delegated_approvals_enabled = True

    @property
    def approval_grace_seconds(self) -> int:
        raise RuntimeError("AD-1213 test: the grace could not be read")


@pytest.mark.parametrize("case", ["settings_raise", "grace_read_raises", "grace_junk", "clock_nan"])
async def test_fault_settings_or_clock_junk(rig: _Rig, case: str) -> None:
    await _premise(rig)
    await rig.delegate()
    req = await rig.grant(BUILDER, "deploy_tool")
    rig.at(req, _GRACE + 1)
    overrides: dict[str, Any] = {}
    expected = Refusal.STATE_UNREADABLE
    if case == "settings_raise":
        failing = _Settings(rig.settings.config)
        failing.failing = True
        overrides["settings"] = failing
        expected = Refusal.NOT_ENABLED  # enabled() fails closed
    elif case == "grace_read_raises":
        overrides["settings"] = lambda: _GraceRaises()
    elif case == "grace_junk":
        overrides["settings"] = lambda: SimpleNamespace(delegated_approvals_enabled=True, approval_grace_seconds="300")
    else:
        overrides["clock"] = lambda: math.nan

    outcome = await _decide(rig.service(**overrides), NUMBER_ONE, req)

    assert outcome.refusal is expected
    await _assert_untouched(rig, req, audits=1, notes=1)
    assert (await _decide(rig.service(), NUMBER_ONE, req)).decided  # control


class _DecideRaisingRequests:
    """The real store, except that the commit of a decision fails (raises, or finds no request)."""

    def __init__(self, inner: CapabilityRequestStore, *, returns_none: bool = False) -> None:
        self._inner = inner
        self._returns_none = returns_none
        self.attempts = 0

    async def get(self, request_id: str, **kwargs: Any) -> Any:
        return await self._inner.get(request_id, **kwargs)

    async def list_pending(self) -> list[Any]:
        return await self._inner.list_pending()

    async def decide(self, *_args: Any, **_kwargs: Any) -> Any:
        self.attempts += 1
        if self._returns_none:
            return None
        raise sqlite3.OperationalError("AD-1213 test: the decision commit failed")


@pytest.mark.parametrize(
    ("returns_none", "expected"),
    [(False, Refusal.STATE_UNREADABLE), (True, Refusal.UNKNOWN_REQUEST)],
)
async def test_fault_store_decide_fails_commits_nothing_and_voids_its_entry(
    rig: _Rig, returns_none: bool, expected: Refusal,
) -> None:
    await _premise(rig)
    failing = _DecideRaisingRequests(rig.requests, returns_none=returns_none)
    service = rig.service(capability_requests=failing)
    req = await rig.grant(BUILDER, "calc_tool")

    outcome = await _decide(service, LAFORGE, req)

    assert outcome.refusal is expected and failing.attempts == 1
    # The entry appended before the commit stays (the chain is append-only), and a
    # void entry names it, so the log never reads as a decision that happened.
    await _assert_untouched(rig, req, audits=2, notes=1)
    written = [entry for entry in rig.audit.entries if entry.category == AUDIT_CATEGORY][-1]
    assert json.loads(written.detail)["request_id"] == req.id
    assert _audit(rig, AUDIT_VOID_CATEGORY) == [{
        "v": 1, "queue": "capability", "request_id": req.id, "decider_id": LAFORGE.id,
        "voids_sequence": written.sequence, "voids_hash": written.entry_hash,
    }]
    assert rig.audit.verify_chain()
    # The lock was released: the same service answers again rather than hanging.
    again = await asyncio.wait_for(_decide(service, LAFORGE, req), 5)
    assert again.refusal is expected and failing.attempts == 2
    assert len(_audit(rig, AUDIT_VOID_CATEGORY)) == 2


class _FailingAppend:
    """A wired audit log whose append fails -- present, but unable to record."""

    def __init__(self) -> None:
        self.attempts = 0

    def append(self, *, category: str, detail: str) -> Any:
        self.attempts += 1
        raise RuntimeError("AD-1213 test: the audit append failed")


async def test_fault_audit_append_raises_commits_nothing(rig: _Rig) -> None:
    await _premise(rig)
    failing = _FailingAppend()
    req = await rig.grant(BUILDER, "calc_tool")

    outcome = await _decide(rig.service(audit_log=failing), LAFORGE, req)

    assert outcome.refusal is Refusal.AUDIT_UNAVAILABLE and failing.attempts == 1
    await _assert_untouched(rig, req, audits=1, notes=1)


class _OrderedAudit:
    """The real audit log, noting at each append whether the request was already decided."""

    def __init__(self, rig: _Rig) -> None:
        self._rig = rig
        self.decided_before_append: list[bool] = []

    def append(self, *, category: str, detail: str) -> Any:
        request_id = json.loads(detail)["request_id"]
        self.decided_before_append.append(bool(self._rig.events.of(_DECIDED, request_id)))
        return self._rig.audit.append(category=category, detail=detail)


async def test_a_delegated_decision_is_audited_before_it_is_committed(rig: _Rig) -> None:
    probe = _OrderedAudit(rig)
    req = await rig.grant(BUILDER, "calc_tool")

    outcome = await _decide(rig.service(audit_log=probe), LAFORGE, req)

    assert outcome.decided and outcome.audited is True
    assert probe.decided_before_append == [False]  # appended while the request was pending
    assert len(rig.events.of(_DECIDED, req.id)) == 1  # premise: the commit did follow
    entry = _audit(rig)[-1]
    assert (entry["request_id"], entry["status"], entry["approve"], entry["decider_id"]) == (
        req.id, "approved", True, LAFORGE.id,
    )


class _AppendOnce:
    """Accepts the first append, then fails every later one."""

    def __init__(self, inner: AuditLog) -> None:
        self._inner = inner
        self.calls = 0

    def append(self, *, category: str, detail: str) -> Any:
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("AD-1213 test: the void append failed")
        return self._inner.append(category=category, detail=detail)


async def test_a_failed_void_is_logged_and_never_raises(
    rig: _Rig, caplog: pytest.LogCaptureFixture,
) -> None:
    await _premise(rig)
    sink = _AppendOnce(rig.audit)
    service = rig.service(capability_requests=_DecideRaisingRequests(rig.requests), audit_log=sink)
    req = await rig.grant(BUILDER, "calc_tool")

    with caplog.at_level(logging.ERROR, logger="probos.delegated_approvals"):
        outcome = await _decide(service, LAFORGE, req)

    assert outcome.refusal is Refusal.STATE_UNREADABLE and sink.calls == 2
    await _assert_untouched(rig, req, audits=2, notes=1)
    assert _audit(rig, AUDIT_VOID_CATEGORY) == []
    assert any("voiding its audit entry failed" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("queue", ["capability", "skill"])
async def test_a_decision_that_committed_before_raising_stands(rig: _Rig, queue: str) -> None:
    service = rig.service()
    if queue == "capability":
        target = await rig.grant(BUILDER, "calc_tool")
        stored: Any = rig.requests
        event = _DECIDED
    else:
        target = await rig.skills.file_request(
            BUILDER.id, "damage_control", skill_label="Damage control", source="self", justification="Drills",
        )
        stored = rig.skills
        event = _SKILL_DECIDED
    rig.events.fail_on = event  # the real store commits, then its DECIDED emit raises

    outcome = await service.decide(
        LAFORGE.id, queue=queue, request_id=target.id, approve=True, reason="Chief approves.",
    )

    rig.events.fail_on = None
    assert outcome.decided, outcome
    assert rig.events.of(event, target.id), "premise: the emit that raised did run"
    assert (await stored.get(target.id)).decided_by == LAFORGE.id
    assert _audit(rig, AUDIT_VOID_CATEGORY) == []
    assert [entry["request_id"] for entry in _audit(rig)] == [target.id]
    assert len(rig.notes.sent) == 1
    if queue == "capability":
        assert (outcome.fulfilled, outcome.status) == (True, "fulfilled")


class _CommitThenRaise:
    """A connection whose next commit lands and then raises, before the store publishes its cache."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.armed = True

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def commit(self) -> None:
        await self.inner.commit()
        if self.armed:
            self.armed = False
            raise sqlite3.OperationalError("AD-1213 test: the connection failed after the commit landed")


@pytest.mark.parametrize("queue", ["capability", "skill"])
async def test_a_commit_that_lands_before_the_cache_is_published_stands(rig: _Rig, queue: str) -> None:
    service = rig.service()
    if queue == "capability":
        target = await rig.grant(BUILDER, "calc_tool")
        stored: Any = rig.requests
    else:
        target = await rig.skills.file_request(
            BUILDER.id, "damage_control", skill_label="Damage control", source="self", justification="Drills",
        )
        stored = rig.skills
    connection = _CommitThenRaise(stored._db)
    stored._db = connection  # fault injection: the store's own writer connection
    try:
        outcome = await service.decide(
            LAFORGE.id, queue=queue, request_id=target.id, approve=True, reason="Chief approves.",
        )
    finally:
        stored._db = connection.inner

    assert not connection.armed  # premise: the decision's commit landed, then raised
    committed = await stored.get(target.id, durable=True)
    assert committed.decided_by == LAFORGE.id
    if queue == "capability":
        assert committed.status == "fulfilled"  # the decision stood, so fulfilment ran
    else:
        assert committed.status == "approved"
        assert (await stored.get(target.id)).status == "requested"  # premise: the cache never saw it
    assert outcome.decided, outcome
    assert _audit(rig, AUDIT_VOID_CATEGORY) == []
    assert [entry["request_id"] for entry in _audit(rig)] == [target.id]
    assert len(rig.notes.sent) == 1


class _UnconfirmedCommit:
    """decide raises; the re-read after it raises too, or shows another decider's decision."""

    def __init__(self, inner: CapabilityRequestStore, *, mode: str) -> None:
        self._inner = inner
        self._mode = mode
        self._failed = False

    async def get(self, request_id: str, **kwargs: Any) -> Any:
        current = await self._inner.get(request_id, **kwargs)
        if not self._failed:
            return current
        if self._mode == "reread_raises":
            raise sqlite3.OperationalError("AD-1213 test: the re-read failed")
        return dataclasses.replace(current, status="denied", decided_by="captain")

    async def list_pending(self) -> list[Any]:
        return await self._inner.list_pending()

    async def decide(self, *_args: Any, **_kwargs: Any) -> Any:
        self._failed = True
        raise sqlite3.OperationalError("AD-1213 test: the decision commit failed")


@pytest.mark.parametrize("mode", ["reread_raises", "reads_another_decision"])
async def test_an_unconfirmed_commit_leaves_its_entry_for_the_captain(
    rig: _Rig, mode: str, caplog: pytest.LogCaptureFixture,
) -> None:
    await _premise(rig)
    service = rig.service(capability_requests=_UnconfirmedCommit(rig.requests, mode=mode))
    req = await rig.grant(BUILDER, "calc_tool")

    with caplog.at_level(logging.ERROR, logger="probos.delegated_approvals"):
        outcome = await _decide(service, LAFORGE, req)

    assert outcome.refusal is Refusal.STATE_UNREADABLE
    await _assert_untouched(rig, req, audits=2, notes=1)
    assert _audit(rig, AUDIT_VOID_CATEGORY) == []  # nothing proves the decision did not happen
    assert any("the Captain should check" in record.getMessage() for record in caplog.records)


class _CancelledCommit:
    """The real store, except that the commit is cancelled."""

    def __init__(self, inner: CapabilityRequestStore) -> None:
        self._inner = inner

    async def get(self, request_id: str, **kwargs: Any) -> Any:
        return await self._inner.get(request_id, **kwargs)

    async def list_pending(self) -> list[Any]:
        return await self._inner.list_pending()

    async def decide(self, *_args: Any, **_kwargs: Any) -> Any:
        raise asyncio.CancelledError


async def test_a_cancelled_commit_propagates_and_releases_the_lock(
    rig: _Rig, caplog: pytest.LogCaptureFixture,
) -> None:
    service = rig.service(capability_requests=_CancelledCommit(rig.requests))
    req = await rig.grant(BUILDER, "calc_tool")

    with caplog.at_level(logging.WARNING, logger="probos.delegated_approvals"):
        with pytest.raises(asyncio.CancelledError):
            await _decide(service, LAFORGE, req)

    assert any("cancelled while it was being recorded" in record.getMessage() for record in caplog.records)
    assert not service.decision_lock("capability").locked()
    assert _audit(rig, AUDIT_VOID_CATEGORY) == []
    assert [entry["request_id"] for entry in _audit(rig)] == [req.id]  # left for the Captain to check


# ===========================================================================
# Concurrency
# ===========================================================================


async def test_captain_and_chief_racing_decide_exactly_once(rig: _Rig) -> None:
    service = rig.service()
    runtime = rig.captain_runtime(service)
    req = await rig.grant(BUILDER, "calc_tool")

    captain, chief = await asyncio.gather(
        decide_capability_request(
            req.id, CapabilityRequestDecideRequest(approve=False, reason="Captain declines."), runtime=runtime,
        ),
        _decide(service, LAFORGE, req, reason="Chief approves."),
        return_exceptions=True,
    )

    assert len(rig.events.of(_DECIDED, req.id)) == 1
    assert len(rig.trust.outcomes) == 1
    captain_won = isinstance(captain, dict)
    if captain_won:
        assert not isinstance(chief, BaseException) and chief.refusal is Refusal.NOT_PENDING
        assert (await rig.requests.get(req.id)).decided_by == "captain"
    else:
        assert isinstance(captain, HTTPException) and captain.status_code == 400
        assert chief.decided and (await rig.requests.get(req.id)).decided_by == LAFORGE.id


async def test_two_deciders_racing_decide_exactly_once(rig: _Rig) -> None:
    service = rig.service()
    await rig.delegate()
    req = await rig.grant(BUILDER, "calc_tool")
    rig.at(req, _GRACE + 1)

    chief, xo = await asyncio.gather(
        _decide(service, LAFORGE, req, reason="Chief approves."),
        _decide(service, NUMBER_ONE, req, approve=False, reason="First Officer declines."),
    )

    assert sorted([chief.decided, xo.decided]) == [False, True]
    loser = xo if chief.decided else chief
    assert loser.refusal is Refusal.NOT_PENDING
    assert len(rig.events.of(_DECIDED, req.id)) == 1
    assert rig.trust.outcomes == [(BUILDER.id, chief.decided)]
    assert len(_audit(rig)) == 1 and len(rig.notes.sent) == 1


class _PausingDecide:
    """A request store whose first decide pauses, holding its caller inside the decision lock."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self._paused = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def decide(self, *args: Any, **kwargs: Any) -> Any:
        if not self._paused:
            self._paused = True
            self.entered.set()
            await self.release.wait()
        return await self._inner.decide(*args, **kwargs)


@pytest.mark.parametrize("queue", ["capability", "skill"])
async def test_captain_route_waits_for_an_agent_decision_in_flight(rig: _Rig, queue: str) -> None:
    """Deterministic: the agent is held mid-commit inside the lock while the Captain's route runs."""
    if queue == "capability":
        target = await rig.grant(BUILDER, "calc_tool")
        stored: Any = rig.requests
        paused = _PausingDecide(stored)
        service = rig.service(capability_requests=paused)
        runtime = rig.captain_runtime(service)
        runtime.capability_request_store = paused
        captain_call = functools.partial(
            decide_capability_request, target.id,
            CapabilityRequestDecideRequest(approve=False, reason="Captain declines."), runtime=runtime,
        )
        decided_event = _DECIDED
    else:
        target = await rig.skills.file_request(
            BUILDER.id, "damage_control", skill_label="Damage control", source="self", justification="Drills",
        )
        stored = rig.skills
        paused = _PausingDecide(stored)
        service = rig.service(skill_requests=paused)
        runtime = rig.captain_runtime(service)
        runtime.skill_request_store = paused
        captain_call = functools.partial(
            decide_skill_request, target.id,
            SkillRequestDecideRequest(approve=False, reason="Captain declines."), runtime=runtime,
        )
        decided_event = _SKILL_DECIDED

    agent = asyncio.create_task(service.decide(
        LAFORGE.id, queue=queue, request_id=target.id, approve=True, reason="Chief approves.",
    ))
    captain: asyncio.Task[Any] | None = None
    try:
        await asyncio.wait_for(paused.entered.wait(), 5)  # the agent holds the lock, mid-commit
        captain = asyncio.create_task(captain_call())
        done, _ = await asyncio.wait({captain}, timeout=0.5)
        assert not done, "the Captain's route decided while an agent's commit was in flight"
        paused.release.set()
        outcome = await asyncio.wait_for(agent, 5)
        with pytest.raises(HTTPException) as refused:
            await asyncio.wait_for(captain, 5)
    finally:
        paused.release.set()
        tasks = [task for task in (agent, captain) if task is not None]
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 5)

    assert outcome.decided
    assert refused.value.status_code == 400
    assert len(rig.events.of(decided_event, target.id)) == 1
    assert (await stored.get(target.id)).decided_by == LAFORGE.id


class _ReassignedAfterFirstRead:
    """The work-item store as the agent's lock-free first read sees it, then reassigned."""

    def __init__(self, inner: WorkItemStore, *, to: str) -> None:
        self._inner = inner
        self._to = to
        self.reads = 0

    async def get_work_item(self, work_item_id: str) -> Any:
        self.reads += 1
        item = await self._inner.get_work_item(work_item_id)
        return item if self.reads == 1 else dataclasses.replace(item, assigned_to=self._to)


@pytest.mark.parametrize("reassigned", [False, True])
async def test_the_self_requisition_bar_is_judged_on_the_chain_read_inside_the_lock(
    rig: _Rig, reassigned: bool,
) -> None:
    item = await rig.work_items.create_work_item(
        title="Calibrate", description="Calibrate", work_type="task", assigned_to=BUILDER.id, created_by="captain",
    )
    req = await rig.grant(BUILDER, "calc_tool", work_item_id=item.id)
    items = _ReassignedAfterFirstRead(rig.work_items, to=LAFORGE.id if reassigned else BUILDER.id)

    outcome = await _decide(rig.service(work_items=items), LAFORGE, req)

    assert items.reads == 2  # premise: once before the lock, once inside it
    if reassigned:
        assert outcome.refusal is Refusal.OWN_REQUISITION
        await _assert_untouched(rig, req, audits=0, notes=0)
    else:
        assert outcome.decided, outcome


class _WedgedAfterFirstRead:
    """Answers the agent's lock-free first read, then blocks until released."""

    def __init__(self, inner: WorkItemStore) -> None:
        self._inner = inner
        self.reads = 0
        self.wedged = asyncio.Event()
        self.release = asyncio.Event()

    async def get_work_item(self, work_item_id: str) -> Any:
        self.reads += 1
        if self.reads > 1:
            self.wedged.set()
            await self.release.wait()
        return await self._inner.get_work_item(work_item_id)


async def test_a_store_wedged_inside_the_lock_holds_the_captain_only_for_the_budget(rig: _Rig) -> None:
    wedged = _WedgedAfterFirstRead(rig.work_items)
    service = rig.service(work_items=wedged, origin_recheck_budget=0.2)
    runtime = rig.captain_runtime(service)
    item = await rig.work_items.create_work_item(
        title="Calibrate", description="Calibrate", work_type="task", assigned_to=BUILDER.id, created_by="captain",
    )
    req = await rig.grant(BUILDER, "calc_tool", work_item_id=item.id)

    agent = asyncio.create_task(_decide(service, LAFORGE, req))
    try:
        await asyncio.wait_for(wedged.wedged.wait(), 5)  # the agent holds the lock, waiting on the store
        assert service.decision_lock("capability").locked()
        captain = await asyncio.wait_for(
            decide_capability_request(req.id, CapabilityRequestDecideRequest(approve=True), runtime=runtime), 5,
        )
        outcome = await asyncio.wait_for(agent, 5)
    finally:
        wedged.release.set()
        await asyncio.wait_for(asyncio.gather(agent, return_exceptions=True), 5)

    assert outcome.refusal is Refusal.STATE_UNREADABLE  # the re-read ran out of budget
    assert captain["request"]["decided_by"] == "captain" and captain["fulfilled"] is True
    assert len(rig.events.of(_DECIDED, req.id)) == 1


class _WedgedItems:
    """A work-item lookup that blocks until released (a wedged workforce.db)."""

    def __init__(self, inner: WorkItemStore) -> None:
        self._inner = inner
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def get_work_item(self, work_item_id: str) -> Any:
        self.entered.set()
        await self.release.wait()
        return await self._inner.get_work_item(work_item_id)


async def test_wedged_work_item_store_never_blocks_the_captain(rig: _Rig) -> None:
    wedged = _WedgedItems(rig.work_items)
    service = rig.service(work_items=wedged)
    runtime = rig.captain_runtime(service)
    item = await rig.work_items.create_work_item(
        title="Calibrate", description="Calibrate", work_type="task", assigned_to=BUILDER.id, created_by="captain",
    )
    req = await rig.grant(BUILDER, "calc_tool", work_item_id=item.id)

    async def captain_then_release() -> dict[str, Any]:
        try:
            await asyncio.wait_for(wedged.entered.wait(), 5)
            return await asyncio.wait_for(
                decide_capability_request(req.id, CapabilityRequestDecideRequest(approve=True), runtime=runtime), 5,
            )
        finally:
            wedged.release.set()

    agent, captain = await asyncio.wait_for(
        asyncio.gather(_decide(service, LAFORGE, req), captain_then_release()), 15,
    )

    assert captain["request"]["decided_by"] == "captain" and captain["fulfilled"] is True
    assert agent.refusal is Refusal.NOT_PENDING
    assert len(rig.events.of(_DECIDED, req.id)) == 1


class _DepartmentsById:
    """Departments keyed by agent id: what the AD-854 peer-precedent check asks for."""

    def __init__(self, departments: dict[str, str]) -> None:
        self._departments = departments

    def get_agent_department(self, agent_id: str) -> str | None:
        return self._departments.get(agent_id)


async def test_triage_fast_path_never_auto_grants_the_review_tool(rig: _Rig) -> None:
    rig.register_review_tool(rig.service())
    trust = TrustNetwork()
    for _ in range(50):
        trust.record_outcome("requester", True, intent_type="seed")
    departments = _DepartmentsById({"requester": "science", "peer": "science"})
    config = CapabilityTriageConfig(grant_fast_path_enabled=True, grant_trust_floor=0.5)

    async def triage(tool_id: str) -> Any:
        await rig.perms.issue_grant(
            "peer", tool_id, ToolPermission.READ, issued_by="captain",
            reason="AD-1213 test: in-department peer precedent",
        )
        return await capability_triage.triage_and_file(
            gap_target=tool_id, agent_id="requester", store=rig.requests,
            tool_registry=rig.tools, permission_store=rig.perms, ontology=departments,
            trust_network=trust, config=config,
        )

    # Premise: the same fast path auto-grants an ordinary read tool, and the triage
    # predicate alone would call the review tool non-destructive too.
    control = await triage("calc_tool")
    assert (control.kind, control.status) == ("grant", "fulfilled")
    assert capability_triage.is_non_destructive(
        capability_triage.derive_tool_permission(rig.tools.get(REVIEW_TOOL_ID))
    )

    req = await triage(REVIEW_TOOL_ID)

    assert (req.kind, req.status, req.decided_by) == ("grant", "pending", "")
    held = rig.perms.get_active_grants_sync("requester", REVIEW_TOOL_ID)
    assert not [grant for grant in held if not grant.is_restriction]


# ===========================================================================
# OFF byte-identity
# ===========================================================================


async def test_guard_is_nullcontext_without_a_service(rig: _Rig) -> None:
    from probos.delegated_approvals import audit_captain_decision, captain_decision_guard

    decided = await rig.grant(BUILDER, "calc_tool")
    for runtime in (SimpleNamespace(), SimpleNamespace(delegated_approvals=None), SimpleNamespace(delegated_approvals=object())):
        for queue in ("capability", "skill"):
            assert isinstance(captain_decision_guard(runtime, queue), contextlib.nullcontext)
        audit_captain_decision(runtime, "capability", decided)
    assert rig.audit.entries == []
    # Control: with a real service wired, the guard is that service's lock.
    service = rig.service()
    assert captain_decision_guard(SimpleNamespace(delegated_approvals=service), "capability") is (
        service.decision_lock("capability")
    )
    with pytest.raises(ValueError):
        service.decision_lock("action")


def test_magicmock_runtime_stays_off() -> None:
    from probos.delegated_approvals import audit_captain_decision, captain_decision_guard

    runtime = MagicMock()

    assert isinstance(captain_decision_guard(runtime, "capability"), contextlib.nullcontext)
    assert isinstance(captain_decision_guard(runtime, "skill"), contextlib.nullcontext)
    audit_captain_decision(runtime, "capability", SimpleNamespace(id="r-1"))
    runtime.delegated_approvals.record_captain_decision.assert_not_called()
    runtime.delegated_approvals.decision_lock.assert_not_called()


async def test_off_captain_capability_route_is_unchanged(rig: _Rig) -> None:
    runtime = rig.captain_runtime()
    assert not hasattr(runtime, "delegated_approvals")
    req = await rig.grant(BUILDER, "calc_tool")

    body = await decide_capability_request(req.id, CapabilityRequestDecideRequest(approve=True), runtime=runtime)

    stored = await rig.requests.get(req.id)
    assert body == {
        "request": capability_router._serialize(stored, include_retry=True),
        "standing_rule": None,
        "fulfilled": True,
    }
    assert (stored.status, stored.decided_by) == ("fulfilled", "captain")
    assert rig.events.types_for(req.id) == [_FILED, _DECIDED, _FULFILLED]
    assert rig.trust.outcomes == [(BUILDER.id, True)]
    assert rig.audit.entries == []


async def test_off_captain_skill_route_is_unchanged(rig: _Rig) -> None:
    runtime = rig.captain_runtime()
    skill = await rig.skills.file_request(BUILDER.id, "damage_control", skill_label="Damage control")

    body = await decide_skill_request(skill.id, SkillRequestDecideRequest(approve=True), runtime=runtime)

    stored = await rig.skills.get(skill.id)
    assert body == {"request": skill_router._serialize(stored)}
    assert (stored.status, stored.decided_by) == ("approved", "captain")
    assert rig.events.types_for(skill.id) == [_SKILL_FILED, _SKILL_DECIDED]
    assert rig.audit.entries == []


# ===========================================================================
# Tool
# ===========================================================================


async def _invoke(
    rig: _Rig, agent: Any, params: dict[str, Any], *, rank: str = "commander",
    presentation: ToolResultPresentation | None = None, **context: Any,
) -> ToolResult:
    return await rig.tools.check_and_invoke(
        agent.id, REVIEW_TOOL_ID, params, agent_rank=rank,
        context={"_tool_result_presentation": presentation or _presentation(), **context},
    )


def _decide_params(req: Any, *, approve: bool = True, reason: str = "AD-1213 test decision.") -> dict[str, Any]:
    return {"action": "decide", "queue": "capability", "request_id": req.id, "approve": approve, "reason": reason}


async def test_tool_denies_every_rank_without_a_grant(rig: _Rig) -> None:
    from probos.tools.review_requests_tool import REVIEW_TOOL_DEFAULT_PERMISSIONS

    assert REVIEW_TOOL_DEFAULT_PERMISSIONS == ALL_NONE
    rig.register_review_tool(rig.service())

    for rank in RANKS:
        with pytest.raises(ToolPermissionDenied):
            await _invoke(rig, LAFORGE, {"action": "list"}, rank=rank)
    await rig.grant_review_tool(LAFORGE)  # control: the Captain's grant is the only way in
    assert (await _invoke(rig, LAFORGE, {"action": "list"}, rank="ensign")).error is None


async def test_tool_runs_for_the_captain_granted_agent(rig: _Rig) -> None:
    rig.register_review_tool(rig.service())
    await rig.grant_review_tool(LAFORGE)
    req = await rig.grant(BUILDER, "calc_tool")

    listed = await _invoke(rig, LAFORGE, {"action": "list"})

    assert listed.error is None, listed.error
    body = ast.literal_eval(listed.output)
    assert body["more"] is False and [entry["request_id"] for entry in body["requests"]] == [req.id]
    entry = body["requests"][0]
    assert set(entry) == _REVIEWABLE_KEYS
    assert (
        entry["queue"], entry["kind"], entry["target"], entry["requester_id"],
        entry["request_class"], entry["role"], entry["decidable_after"],
    ) == ("capability", "grant", "calc_tool", BUILDER.id, "non_destructive", "department_chief", None)

    decided = await _invoke(rig, LAFORGE, _decide_params(req, reason="Read access for the calibration."))

    assert decided.error is None, decided.error
    assert ast.literal_eval(decided.output) == {
        "decided": True, "queue": "capability", "request_id": req.id, "status": "fulfilled",
        "fulfilled": True, "captain_notified": True, "audited": True,
        "role": "department_chief", "request_class": "non_destructive",
    }
    with pytest.raises(ToolPermissionDenied):  # an ungranted officer is still refused
        await _invoke(rig, NUMBER_ONE, {"action": "list"}, rank="senior_officer")


async def test_tool_decider_comes_from_context_not_params(rig: _Rig) -> None:
    tool = rig.register_review_tool(rig.service())
    await rig.grant_review_tool(LAFORGE)
    req = await rig.grant(BUILDER, "calc_tool")

    smuggled = await _invoke(rig, LAFORGE, {**_decide_params(req), "agent_id": NUMBER_ONE.id})
    assert smuggled.error is not None and "agent_id" in smuggled.error
    assert (await rig.requests.get(req.id)).status == "pending"

    # A context naming someone else is overwritten by the trusted caller.
    result = await _invoke(rig, LAFORGE, _decide_params(req), agent_id=NUMBER_ONE.id)
    assert result.error is None, result.error
    assert (await rig.requests.get(req.id)).decided_by == LAFORGE.id

    # Invoked directly, the tool acts for exactly the agent the context names.
    other = await rig.grant(BUILDER, "calc_tool")
    direct = await tool.invoke(_decide_params(other), {"_tool_result_presentation": _presentation(), "agent_id": SURGEON.id})
    assert direct.error is not None and "outside_authority" in direct.error
    assert (await rig.requests.get(other.id)).status == "pending"


async def test_tool_refuses_inside_a_crew_room(rig: _Rig) -> None:
    tool = rig.register_review_tool(rig.service())
    await rig.grant_review_tool(LAFORGE)
    req = await rig.grant(BUILDER, "calc_tool")
    assert (await _invoke(rig, LAFORGE, {"action": "list"})).error is None  # premise

    for key in ("_crew_session_id", "_crew_work_item_id"):
        result = await _invoke(rig, LAFORGE, _decide_params(req), **{key: "room-1"})
        assert result.error is not None and result.output is None, key
    for context in (None, {"agent_id": LAFORGE.id}, {"_tool_result_presentation": _presentation(), "agent_id": ""}):
        result = await tool.invoke(_decide_params(req), context)
        assert result.error is not None, context
    assert (await rig.requests.get(req.id)).status == "pending"


async def test_tool_texts_are_capability_gap_clean(rig: _Rig) -> None:
    from probos.tools.review_requests_tool import ReviewRequestsTool

    assert _CAPABILITY_GAP_RE.search("I am unable to decide that") is not None  # premise: the regex fires
    assert REFUSAL_TEXT == {
        Refusal.NOT_ENABLED: "Delegated approvals are switched off on this vessel.",
        Refusal.UNKNOWN_QUEUE: "Name the queue as 'capability' or 'skill'.",
        Refusal.UNKNOWN_REQUEST: "No request has that id.",
        Refusal.NOT_PENDING: "That request has already been decided.",
        Refusal.INVALID_DECISION: "Give approve as true or false and a reason of 1 to 500 characters.",
        Refusal.DECIDER_UNRESOLVED: "Your post in the chain of command could not be resolved.",
        Refusal.REQUESTER_UNRESOLVED: "The requester's post in the chain of command could not be resolved.",
        Refusal.OWN_REQUISITION: "You originated this requisition, and no one decides their own.",
        Refusal.CAPTAIN_RESERVED: "This class of request is reserved for the Captain.",
        Refusal.UNCLASSIFIABLE: "This request could not be classified, so it is reserved for the Captain.",
        Refusal.OUTSIDE_AUTHORITY: "The requester is not under your command.",
        Refusal.DESTRUCTIVE_NEEDS_FIRST_OFFICER: (
            "It changes something, so it goes past a department chief to the First Officer."
        ),
        Refusal.DELEGATION_ABSENT: (
            "The Captain has not delegated approvals to the First Officer, or the delegation has expired."
        ),
        Refusal.GRACE_PERIOD: "The Captain has first refusal until the grace period ends.",
        Refusal.STATE_UNREADABLE: "Approval authority could not be read, so the Captain decides.",
        Refusal.AUDIT_UNAVAILABLE: "The audit log is offline, and an unaudited decision is never taken.",
    }
    texts = [*REFUSAL_TEXT.values(), ReviewRequestsTool(service=rig.service()).description,
             " The request stays with the Captain."]
    for text in texts:
        assert _CAPABILITY_GAP_RE.search(text) is None, text
    with pytest.raises(ValueError):
        ReviewRequestsTool(service=None)


async def test_tool_refusal_routes_to_the_captain(rig: _Rig) -> None:
    service = rig.service()
    rig.register_review_tool(service)
    await rig.grant_review_tool(LAFORGE)
    await rig.grant_review_tool(NUMBER_ONE)
    req = await rig.grant(BUILDER, "deploy_tool")
    suffix = " The request stays with the Captain."

    chief = await _invoke(rig, LAFORGE, _decide_params(req))
    assert chief.error == (
        "review_requests: destructive_needs_first_officer: "
        + REFUSAL_TEXT[Refusal.DESTRUCTIVE_NEEDS_FIRST_OFFICER] + suffix
    )

    await rig.delegate()
    rig.at(req, 10)
    xo = await _invoke(rig, NUMBER_ONE, _decide_params(req), rank="senior_officer")
    head = "review_requests: grace_period: " + REFUSAL_TEXT[Refusal.GRACE_PERIOD] + suffix + " Decidable after "
    assert xo.error is not None and xo.error.startswith(head) and xo.error.endswith(".")
    when = datetime.fromisoformat(xo.error[len(head):-1].replace("Z", "+00:00"))
    assert when.tzinfo is not None and abs(when.timestamp() - (req.created_at + _GRACE)) < 1

    ghost = await _invoke(rig, LAFORGE, {**_decide_params(req), "request_id": "no-such-request"})
    assert ghost.error == "review_requests: unknown_request: " + REFUSAL_TEXT[Refusal.UNKNOWN_REQUEST]

    # Refused means it stays with the Captain, who can still decide it.
    assert (await rig.requests.get(req.id)).status == "pending"
    body = await decide_capability_request(
        req.id, CapabilityRequestDecideRequest(approve=True), runtime=rig.captain_runtime(service),
    )
    assert body["request"]["decided_by"] == "captain"
    done = await _invoke(rig, LAFORGE, _decide_params(req))
    assert done.error == "review_requests: not_pending: " + REFUSAL_TEXT[Refusal.NOT_PENDING]

    # Malformed calls are refused before the service is asked, and say what to fix.
    missing = await _invoke(rig, LAFORGE, {"action": "decide", "queue": "capability", "request_id": req.id})
    assert missing.error == "review_requests: invalid_decision: " + REFUSAL_TEXT[Refusal.INVALID_DECISION]
    action_error = "review_requests: invalid_action: Give action as 'list' or 'decide'."
    for params in ({"action": "approve"}, {}):
        assert (await _invoke(rig, LAFORGE, params)).error == action_error
    tool = rig.tools.get_tool(REVIEW_TOOL_ID)
    assert (await tool.invoke(["list"], {"_tool_result_presentation": _presentation(), "agent_id": LAFORGE.id})).error == (
        action_error
    )

    # A list the service will not answer is refused the same way, and stays with the Captain.
    ghost = generate_agent_id("builder", "builder", 99)  # granted, but in no registry and at no post
    await rig.perms.issue_grant(
        ghost, REVIEW_TOOL_ID, ToolPermission.READ, issued_by="captain", reason="AD-1213 test: a grant without a post",
    )
    unresolved = await rig.tools.check_and_invoke(
        ghost, REVIEW_TOOL_ID, {"action": "list"}, agent_rank="ensign",
        context={"_tool_result_presentation": _presentation()},
    )
    assert unresolved.error == "review_requests: decider_unresolved: " + REFUSAL_TEXT[Refusal.DECIDER_UNRESOLVED] + suffix

    # An unexpected failure (here a presentation that renders a non-string) is state_unreadable.
    bad = ToolResultPresentation(render_complete=lambda _value: 42)
    unreadable = await tool.invoke({"action": "list"}, {"_tool_result_presentation": bad, "agent_id": LAFORGE.id})
    assert unreadable.error == "review_requests: state_unreadable: " + REFUSAL_TEXT[Refusal.STATE_UNREADABLE] + suffix


async def test_tool_list_shrinks_to_fit_the_presentation_budget(rig: _Rig) -> None:
    rig.register_review_tool(rig.service())
    await rig.grant_review_tool(LAFORGE)
    for _ in range(4):
        await rig.grant(BUILDER, "calc_tool")

    full = await _invoke(rig, LAFORGE, {"action": "list"})
    assert full.error is None
    assert len(ast.literal_eval(full.output)["requests"]) == 4

    budget = len(full.output) - 1
    shrunk = await _invoke(rig, LAFORGE, {"action": "list"}, presentation=_presentation(budget))
    assert shrunk.error is None and len(shrunk.output) <= budget
    body = ast.literal_eval(shrunk.output)
    assert 0 < len(body["requests"]) < 4 and body["more"] is True

    tiny = await _invoke(rig, LAFORGE, {"action": "list"}, presentation=_presentation(10))
    assert tiny.error == "review_requests: result_budget"

    # The decision is committed before its receipt is rendered, so a receipt that does not fit,
    # or whose rendering fails, still reports the decision as recorded -- never as a refusal.
    receipt_error = (
        "review_requests: receipt_withheld: The decision was recorded; its receipt did not fit "
        "this turn's result presentation."
    )
    first, second = (await rig.requests.list_pending())[:2]
    over = await _invoke(rig, LAFORGE, _decide_params(first), presentation=_presentation(10))
    failing = await _invoke(
        rig, LAFORGE, _decide_params(second), presentation=ToolResultPresentation(render_complete=lambda _value: 42),
    )
    assert over.error == failing.error == receipt_error
    for req in (first, second):
        assert (await rig.requests.get(req.id)).decided_by == LAFORGE.id


# ===========================================================================
# Captain routes
# ===========================================================================

_AUTHORITY_CALLS = (
    ("GET", "/api/approval-authority/state", None),
    ("PUT", "/api/approval-authority/delegation", {"hours": 1}),
    ("DELETE", "/api/approval-authority/delegation", None),
    ("PUT", "/api/approval-authority/availability", {"hours": 1}),
    ("DELETE", "/api/approval-authority/availability", None),
)


def _authority_client(runtime: Any) -> TestClient:
    from probos.routers import approval_authority
    from probos.routers.deps import get_runtime

    app = FastAPI()
    app.include_router(approval_authority.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def _authority_runtime(store: Any, *, token: str = "", **config: Any) -> SimpleNamespace:
    return SimpleNamespace(
        approval_authority_store=store,
        config=SimpleNamespace(
            approval_inbox=ApprovalInboxConfig(delegated_approvals_enabled=True, **config),
            auth=AuthConfig(crew_scope_token=token),
        ),
        audit_log=AuditLog(),
    )


def _started_cache_store(clock: _Clock) -> ApprovalAuthorityStore:
    store = ApprovalAuthorityStore(db_path="", clock=clock)
    asyncio.run(store.start())
    return store


def _authority_handlers() -> dict[tuple[str, str], Any]:
    from probos.routers import approval_authority

    return {
        (route.path, method): route.endpoint
        for route in approval_authority.router.routes for method in route.methods
    }


def test_authority_routes_503_when_off() -> None:
    runtime = _authority_runtime(None)
    client = _authority_client(runtime)

    for method, path, body in _AUTHORITY_CALLS:
        response = client.request(method, path, json=body)
        assert response.status_code == 503, (method, path)
        assert response.json()["detail"] == "approval authority is not enabled"
    assert runtime.audit_log.entries == []

    # A store that is not running does not answer either: 503, and nothing is audited.
    idle = _authority_runtime(ApprovalAuthorityStore(db_path="", clock=_Clock(_NOW)))
    idle_client = _authority_client(idle)
    for method, path, body in _AUTHORITY_CALLS:
        response = idle_client.request(method, path, json=body)
        assert response.status_code == 503, (method, path)
        assert response.json()["detail"] == "approval authority could not be read"
    assert idle.audit_log.entries == []


def test_put_delegation_clamps_audits_and_supersedes() -> None:
    clock = _Clock(_NOW)
    store = _started_cache_store(clock)
    runtime = _authority_runtime(store)
    client = _authority_client(runtime)

    first = client.put("/api/approval-authority/delegation", json={"hours": 500, "reason": "Away mission."})

    assert first.status_code == 200, first.text
    body = first.json()
    assert (body["requested_hours"], body["granted_hours"], body["clamped"]) == (500, 168, True)
    record = body["record"]
    assert (record["kind"], record["issued_by"], record["reason"]) == (FIRST_OFFICER_DELEGATION, "captain", "Away mission.")
    assert record["expires_at"] == pytest.approx(_NOW + 168 * 3600)
    assert store.live(FIRST_OFFICER_DELEGATION).id == record["id"]

    second = client.put("/api/approval-authority/delegation", json={"hours": 2})
    assert (second.json()["granted_hours"], second.json()["clamped"]) == (2, False)
    assert store.live(FIRST_OFFICER_DELEGATION).id == second.json()["record"]["id"] != record["id"]

    entries = [json.loads(e.detail) for e in runtime.audit_log.entries if e.category == AUTHORITY_AUDIT_CATEGORY]
    assert [set(e) for e in entries] == [_AUTHORITY_AUDIT_KEYS, _AUTHORITY_AUDIT_KEYS]
    assert entries[0] == {
        "v": 1, "action": "delegate", "record_id": record["id"], "expires_at": record["expires_at"],
        "revoked": None, "reason": "Away mission.",
    }
    assert (entries[1]["action"], entries[1]["record_id"]) == ("delegate", second.json()["record"]["id"])

    # The audit is log-and-degrade: with no audit log, or one that fails, the Captain's act stands.
    def _failing_append(**_kwargs: Any) -> None:
        raise RuntimeError("AD-1213 test: the audit sink failed")

    runtime.audit_log = None
    assert client.put("/api/approval-authority/availability", json={"hours": 1}).status_code == 200
    runtime.audit_log = SimpleNamespace(append=_failing_append)
    assert client.delete("/api/approval-authority/availability").json() == {"revoked": 1}
    assert store.live(CAPTAIN_UNAVAILABLE) is None


def test_delete_delegation_revokes() -> None:
    store = _started_cache_store(_Clock(_NOW))
    runtime = _authority_runtime(store)
    client = _authority_client(runtime)
    assert client.put("/api/approval-authority/delegation", json={"hours": 1}).status_code == 200

    revoked = client.delete("/api/approval-authority/delegation")

    assert revoked.status_code == 200 and revoked.json() == {"revoked": 1}
    assert store.live(FIRST_OFFICER_DELEGATION) is None
    assert client.delete("/api/approval-authority/delegation").json() == {"revoked": 0}
    assert client.get("/api/approval-authority/state").json()["first_officer_delegation"] is None
    entries = [json.loads(e.detail) for e in runtime.audit_log.entries if e.category == AUTHORITY_AUDIT_CATEGORY]
    assert [(e["action"], e["revoked"]) for e in entries] == [
        ("delegate", None), ("revoke_delegation", 1), ("revoke_delegation", 0),
    ]
    assert entries[1]["record_id"] is None and entries[1]["expires_at"] is None


async def test_availability_zeroes_the_grace_until_it_expires(rig: _Rig) -> None:
    from probos.routers.approval_authority import AuthorityGrantBody

    rig.settings.config = ApprovalInboxConfig(delegated_approvals_enabled=True, approval_grace_seconds=86_400)
    handlers = _authority_handlers()
    runtime = rig.authority_runtime()
    service = rig.service()
    await rig.delegate()
    first = await rig.grant(BUILDER, "deploy_tool")
    rig.at(first, 10)
    assert (await _decide(service, NUMBER_ONE, first)).refusal is Refusal.GRACE_PERIOD  # premise

    marked = await handlers[("/api/approval-authority/availability", "PUT")](
        AuthorityGrantBody(hours=1, reason="Captain is off watch."), runtime=runtime,
    )

    assert (marked["granted_hours"], marked["clamped"]) == (1, False)
    state = await handlers[("/api/approval-authority/state", "GET")](runtime=runtime)
    assert state["captain_unavailable"]["id"] == marked["record"]["id"]
    assert (state["enabled"], state["approval_grace_seconds"]) == (True, 86_400)
    decided = await _decide(service, NUMBER_ONE, first)
    assert decided.decided
    entry = _audit(rig)[-1]
    assert (entry["grace_seconds"], entry["captain_unavailable"]) == (0, True)

    # The mark lapses by itself, and the configured grace is back.
    second = await rig.grant(BUILDER, "deploy_tool")
    rig.clock.t = marked["record"]["expires_at"]
    refused = await _decide(service, NUMBER_ONE, second)
    assert refused.refusal is Refusal.GRACE_PERIOD
    assert refused.decidable_after == second.created_at + 86_400
    state = await handlers[("/api/approval-authority/state", "GET")](runtime=runtime)
    assert state["captain_unavailable"] is None
    actions = [e["action"] for e in _audit(rig, AUTHORITY_AUDIT_CATEGORY)]
    assert actions == ["mark_unavailable"]


def test_authority_routes_require_crew_scope_when_a_token_is_set() -> None:
    store = _started_cache_store(_Clock(_NOW))
    runtime = _authority_runtime(store, token="secret")
    client = _authority_client(runtime)

    for method, path, body in _AUTHORITY_CALLS:
        assert client.request(method, path, json=body).status_code == 401, (method, path)
        wrong = client.request(method, path, json=body, headers={"Authorization": "Bearer wrong"})
        assert wrong.status_code == 401, (method, path)
    assert store.live(FIRST_OFFICER_DELEGATION) is None and store.live(CAPTAIN_UNAVAILABLE) is None
    assert runtime.audit_log.entries == []

    ok = client.put("/api/approval-authority/delegation", json={"hours": 1}, headers={"Authorization": "Bearer secret"})
    assert ok.status_code == 200


def test_authority_body_validation() -> None:
    store = _started_cache_store(_Clock(_NOW))
    runtime = _authority_runtime(store)
    client = _authority_client(runtime)

    for path in ("/api/approval-authority/delegation", "/api/approval-authority/availability"):
        for body in ({"hours": 0}, {"hours": 8761}, {"hours": 1, "extra": True}, {"hours": 1, "reason": "x" * 501},
                     {"hours": "one"}, {}):
            response = client.put(path, json=body)
            assert response.status_code == 422, (path, body)
        assert client.put(path, json={"hours": 8760, "reason": "x" * 500}).status_code == 200  # control
    assert [json.loads(e.detail)["action"] for e in runtime.audit_log.entries] == ["delegate", "mark_unavailable"]

    # A ceiling mutated past validation (0 h) is refused by the store's own TTL check: 422, nothing issued.
    live = store.live(FIRST_OFFICER_DELEGATION)
    runtime.config.approval_inbox = SimpleNamespace(first_officer_delegation_max_ttl_hours=0)
    refused = client.put("/api/approval-authority/delegation", json={"hours": 1})
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == "approval authority record refused: invalid duration, issuer or reason"
    assert store.live(FIRST_OFFICER_DELEGATION) == live and len(runtime.audit_log.entries) == 2


# ===========================================================================
# Wiring
# ===========================================================================


async def test_store_helper_returns_none_when_off(tmp_path: Path) -> None:
    from probos.startup.communication import _start_approval_authority_store

    off = SystemConfig()
    assert await _start_approval_authority_store(off, tmp_path) is None
    assert not (tmp_path / "approval_authority.db").exists()

    on = SystemConfig(approval_inbox=ApprovalInboxConfig(delegated_approvals_enabled=True))
    store = await _start_approval_authority_store(on, tmp_path)
    try:
        assert isinstance(store, ApprovalAuthorityStore)
        assert store.live(FIRST_OFFICER_DELEGATION) is None
        assert (tmp_path / "approval_authority.db").exists()
    finally:
        await store.stop()


async def test_wire_off_registers_nothing(rig: _Rig) -> None:
    from probos.startup.finalize import _wire_delegated_approvals

    runtime = rig.wiring_runtime(enabled=False)

    assert _wire_delegated_approvals(runtime=runtime, config=runtime.config) is False
    assert runtime.delegated_approvals is None
    assert rig.tools.get(REVIEW_TOOL_ID) is None


async def test_wire_on_registers_the_tool_and_the_service(rig: _Rig) -> None:
    from probos.delegated_approvals import DelegatedApprovalService
    from probos.startup.finalize import _wire_delegated_approvals
    from probos.tools.review_requests_tool import REVIEW_TOOL_DEFAULT_PERMISSIONS, ReviewRequestsTool

    runtime = rig.wiring_runtime(enabled=True)

    assert _wire_delegated_approvals(runtime=runtime, config=runtime.config) is True
    service = runtime.delegated_approvals
    assert isinstance(service, DelegatedApprovalService)
    registration = rig.tools.get(REVIEW_TOOL_ID)
    assert registration is not None and isinstance(registration.tool, ReviewRequestsTool)
    assert registration.default_permissions == REVIEW_TOOL_DEFAULT_PERMISSIONS
    assert registration.provider == "delegated_approvals"
    assert sorted(registration.tags) == ["approvals", "review_requests"]
    assert registration.allowed_departments is None and registration.restricted_to is None
    tool = registration.tool
    assert (tool.tool_id, tool.name, tool.tool_type) == (REVIEW_TOOL_ID, "Review Requests", ToolType.INFRA_SERVICE)
    assert tool.input_schema["required"] == ["action"] and tool.input_schema["additionalProperties"] is False
    assert tool.output_schema["type"] == "string"
    # The wired service decides through the runtime it was built from.
    req = await rig.grant(BUILDER, "calc_tool")
    outcome = await _decide(service, LAFORGE, req)
    assert outcome.decided and outcome.fulfilled is True
    assert [g.issued_by for g in rig.perms.get_active_grants_sync(BUILDER.id, "calc_tool")] == [LAFORGE.id]
    assert [note.agent_id for note in rig.notes.sent] == [LAFORGE.id]


@pytest.mark.parametrize(
    "missing",
    ["audit_log", "approval_authority_store", "capability_request_store", "registry", "ontology", "tool_registry"],
)
async def test_wire_refuses_without_an_audit_log(
    rig: _Rig, missing: str, caplog: pytest.LogCaptureFixture,
) -> None:
    from probos.startup.finalize import _wire_delegated_approvals

    runtime = rig.wiring_runtime(enabled=True, **{missing: None})

    with caplog.at_level(logging.WARNING, logger="probos.startup.finalize"):
        assert _wire_delegated_approvals(runtime=runtime, config=runtime.config) is False

    assert runtime.delegated_approvals is None and rig.tools.get(REVIEW_TOOL_ID) is None
    warnings = [
        r.getMessage() for r in caplog.records
        if r.levelno == logging.WARNING and r.name == "probos.startup.finalize"
    ]
    assert len(warnings) == 1 and missing in warnings[0]
    assert "the Captain decides every request" in warnings[0]


class _ExplodingRegistry:
    def get(self, _tool_id: str) -> Any:
        raise RuntimeError("AD-1213 test: the tool registry exploded")

    def register(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("AD-1213 test: the tool registry exploded")


class _ExplodingConfig:
    @property
    def approval_inbox(self) -> Any:
        raise RuntimeError("AD-1213 test: the config exploded")


async def test_wire_never_raises(rig: _Rig) -> None:
    from probos.startup.finalize import _wire_delegated_approvals

    exploding = rig.wiring_runtime(enabled=True, tool_registry=_ExplodingRegistry())
    assert _wire_delegated_approvals(runtime=exploding, config=exploding.config) is False
    assert exploding.delegated_approvals is None

    runtime = rig.wiring_runtime(enabled=True)
    assert _wire_delegated_approvals(runtime=runtime, config=_ExplodingConfig()) is False
    assert runtime.delegated_approvals is None
    assert _wire_delegated_approvals(runtime=runtime, config=runtime.config) is True  # control


async def test_shutdown_closes_the_authority_store(tmp_path: Path) -> None:
    from probos.approval_authority import ApprovalAuthorityUnavailable
    from probos.startup.shutdown import _stop_runtime_sqlite_sidecars

    store = ApprovalAuthorityStore(db_path=str(tmp_path / "approval_authority.db"))
    await store.start()
    try:
        assert store.live(FIRST_OFFICER_DELEGATION) is None  # premise: running
        runtime = SimpleNamespace(approval_authority_store=store)

        await _stop_runtime_sqlite_sidecars(runtime)

        assert runtime.approval_authority_store is None
        with pytest.raises(ApprovalAuthorityUnavailable):
            store.live(FIRST_OFFICER_DELEGATION)
        await _stop_runtime_sqlite_sidecars(SimpleNamespace(approval_authority_store=None))  # OFF: skipped
    finally:
        await store.stop()  # idempotent: closes the connection if shutdown did not


def test_api_mounts_the_authority_routes() -> None:
    from probos.api import create_app
    from probos.routers import approval_authority

    runtime = MagicMock()
    runtime.config = SystemConfig()
    runtime._data_dir = runtime.data_dir = None  # BF-326: a MagicMock path makes create_app mkdir a stray dir
    app = create_app(runtime)

    endpoints = {(route.path, method): route.endpoint for route in app.routes for method in getattr(route, "methods", ())}
    expected = _authority_handlers()
    assert len(expected) == 5
    for key, handler in expected.items():
        assert endpoints[key] is handler, key
    assert {path for path, _method in expected} == {
        "/api/approval-authority/state", "/api/approval-authority/delegation", "/api/approval-authority/availability",
    }
    assert approval_authority.router.prefix == "/api/approval-authority"


# ===========================================================================
# End to end (M6)
# ===========================================================================


class _GapLoop:
    """test_ad1211's AD-855 loop over the rig's stores: a real gap driver on a draining bus."""

    def __init__(self, rig: _Rig) -> None:
        self.bus = _EventBus()
        self.router = _RecordingRouter()
        rig.events.forward = self.bus.emit
        self.runtime = rig.wiring_runtime(
            enabled=True,
            work_item_router=self.router,
            trust_network=rig.trust,
            dependency_resolver=None,
            event_log=_EventLog(),
        )
        self.driver = CapabilityGapDriver(
            runtime=self.runtime, work_item_store=rig.work_items, capability_request_store=rig.requests,
        )
        self.runtime.capability_gap_driver = self.driver
        self.bus.add_event_listener(self.driver.on_capability_event)

    async def blocked_request(self, rig: _Rig, tool_id: str) -> tuple[Any, Any]:
        item = await rig.work_items.create_work_item(
            title=f"Work needing {tool_id}", description=f"Work needing {tool_id}", work_type="task",
            assigned_to=BUILDER.id, created_by="captain",
        )
        await rig.work_items.transition_work_item(item.id, "in_progress", source=BUILDER.id)
        req = await rig.grant(BUILDER, tool_id, work_item_id=item.id)
        assert await self.driver.block_on_request(work_item_id=item.id, request_id=req.id, reason=tool_id) is True
        await self.bus.drain()
        assert (await rig.work_items.get_work_item(item.id)).status == "blocked"
        return item, req


@pytest.fixture
async def gap_loop(rig: _Rig):
    gap = _GapLoop(rig)
    try:
        yield gap
    finally:
        await gap.bus.drain()


async def test_e2e_chief_decides_through_the_real_tool_and_the_work_item_resumes(rig: _Rig, gap_loop: _GapLoop) -> None:
    from probos.startup.finalize import _wire_delegated_approvals

    assert _wire_delegated_approvals(runtime=gap_loop.runtime, config=gap_loop.runtime.config) is True
    item, req = await gap_loop.blocked_request(rig, "calc_tool")
    await rig.grant_review_tool(LAFORGE)

    result = await rig.tools.check_and_invoke(
        LAFORGE.id, REVIEW_TOOL_ID,
        {"action": "decide", "queue": "capability", "request_id": req.id, "approve": True,
         "reason": "Read access to finish the calibration."},
        agent_rank="commander", context={"_tool_result_presentation": _presentation()},
    )
    await gap_loop.bus.drain()

    assert result.error is None, result.error
    stored = await rig.requests.get(req.id)
    assert (stored.status, stored.decided_by) == ("fulfilled", LAFORGE.id)
    assert _FULFILLED in gap_loop.bus.emitted
    assert (await rig.work_items.get_work_item(item.id)).status == "in_progress"
    assert len(gap_loop.router.dispatched) == 1
    grants = rig.perms.get_active_grants_sync(BUILDER.id, "calc_tool")
    assert [(g.permission, g.issued_by, g.is_restriction) for g in grants] == [(ToolPermission.READ, LAFORGE.id, False)]
    [entry] = _audit(rig)
    assert (entry["decider_role"], entry["request_class"], entry["pre_cleared"]) == (
        "department_chief", "non_destructive", False,
    )
    assert [note.agent_id for note in rig.notes.sent] == [LAFORGE.id]
    assert await rig.actions.list_approvals(active_only=False) == []


async def test_e2e_first_officer_decides_a_destructive_grant_after_delegation_and_grace(
    rig: _Rig, gap_loop: _GapLoop,
) -> None:
    from probos.routers.approval_authority import AuthorityGrantBody

    service = rig.service()
    rig.register_review_tool(service)
    item, req = await gap_loop.blocked_request(rig, "deploy_tool")
    await rig.grant_review_tool(LAFORGE)
    await rig.grant_review_tool(NUMBER_ONE)
    rig.at(req, 1)
    params = {"action": "decide", "queue": "capability", "request_id": req.id, "approve": True,
              "reason": "Deploy access for the refit."}

    async def call(agent: Any, rank: str) -> ToolResult:
        return await rig.tools.check_and_invoke(
            agent.id, REVIEW_TOOL_ID, params, agent_rank=rank,
            context={"_tool_result_presentation": _presentation()},
        )

    chief = await call(LAFORGE, "commander")
    assert chief.error is not None and chief.error.startswith("review_requests: destructive_needs_first_officer:")
    assert chief.error.endswith(" The request stays with the Captain.")
    xo = await call(NUMBER_ONE, "senior_officer")
    assert xo.error is not None and xo.error.startswith("review_requests: delegation_absent:")

    handlers = _authority_handlers()
    granted = await handlers[("/api/approval-authority/delegation", "PUT")](
        AuthorityGrantBody(hours=24, reason="Delegating for the refit."), runtime=rig.authority_runtime(),
    )
    delegation_id = granted["record"]["id"]
    rig.at(req, 10)
    waiting = await call(NUMBER_ONE, "senior_officer")
    assert waiting.error is not None and waiting.error.startswith("review_requests: grace_period:")

    rig.at(req, _GRACE + 1)
    decided = await call(NUMBER_ONE, "senior_officer")
    await gap_loop.bus.drain()

    assert decided.error is None, decided.error
    stored = await rig.requests.get(req.id)
    assert (stored.status, stored.decided_by) == ("fulfilled", NUMBER_ONE.id)
    grants = rig.perms.get_active_grants_sync(BUILDER.id, "deploy_tool")
    assert [(g.permission, g.issued_by) for g in grants] == [(ToolPermission.WRITE, NUMBER_ONE.id)]
    [entry] = _audit(rig)
    assert (entry["decider_role"], entry["request_class"], entry["delegation_id"], entry["grace_seconds"]) == (
        "first_officer", "destructive", delegation_id, _GRACE,
    )
    assert (await rig.work_items.get_work_item(item.id)).status == "in_progress"


async def test_e2e_chief_denial_cancels_the_blocked_work_item(rig: _Rig, gap_loop: _GapLoop) -> None:
    from probos.startup.finalize import _wire_delegated_approvals

    assert _wire_delegated_approvals(runtime=gap_loop.runtime, config=gap_loop.runtime.config) is True
    item, req = await gap_loop.blocked_request(rig, "calc_tool")
    await rig.grant_review_tool(LAFORGE)

    result = await rig.tools.check_and_invoke(
        LAFORGE.id, REVIEW_TOOL_ID,
        {"action": "decide", "queue": "capability", "request_id": req.id, "approve": False,
         "reason": "Use the existing calibration tables."},
        agent_rank="commander", context={"_tool_result_presentation": _presentation()},
    )
    await gap_loop.bus.drain()

    assert result.error is None, result.error
    assert ast.literal_eval(result.output)["status"] == "denied"
    stored = await rig.requests.get(req.id)
    assert (stored.status, stored.decided_by) == ("denied", LAFORGE.id)
    assert (await rig.work_items.get_work_item(item.id)).status == "cancelled"
    assert rig.perms.get_active_grants_sync(BUILDER.id, "calc_tool") == []
    [entry] = _audit(rig)
    assert (entry["approve"], entry["status"]) == (False, "denied")
    assert gap_loop.router.dispatched == []


class _RankedTrust(_Trust):
    """The executor derives rank from trust when it resolves identity; 0.7 is a commander."""

    def get_score(self, agent_id: str) -> float:
        return 0.7


async def test_e2e_review_tool_gets_the_loops_presentation_in_an_ordinary_agentic_turn(
    rig: _Rig, gap_loop: _GapLoop, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A-15 (F-M5-1): no hand-passed presentation. The Captain's grant puts the tool in the real
    # executor's offer, and the real AgenticLoop builds the invocation context, as in production.
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock
    from probos.startup.finalize import _wire_delegated_approvals
    from probos.types import LLMRequest, LLMResponse

    runtime = gap_loop.runtime
    assert _wire_delegated_approvals(runtime=runtime, config=runtime.config) is True
    assert runtime.config.agentic_loop.structured_tool_messages is False  # the transcript parsed below
    runtime.trust_network = _RankedTrust()
    item, req = await gap_loop.blocked_request(rig, "calc_tool")
    await rig.grant_review_tool(LAFORGE)
    tool = rig.tools.get_tool(REVIEW_TOOL_ID)
    real_invoke = tool.invoke
    contexts: list[dict[str, Any]] = []

    async def recording_invoke(params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        contexts.append(dict(context or {}))
        return await real_invoke(params, context)

    monkeypatch.setattr(tool, "invoke", recording_invoke)
    marker = "[tool_result:review-call error="
    results: list[tuple[str, str]] = []

    class _Model:
        def __init__(self) -> None:
            self.requests: list[LLMRequest] = []

        async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
            self.requests.append(request)
            if len(self.requests) == 1:
                assert REVIEW_TOOL_ID in {offered["function"]["name"] for offered in request.tools}
                call = ToolCallRequest(
                    name=REVIEW_TOOL_ID, id="review-call",
                    arguments={"action": "decide", "queue": "capability", "request_id": req.id,
                               "approve": True, "reason": "Read access to finish the calibration."},
                )
                return LLMResponse(content="", tokens_used=1, content_blocks=[ToolUseBlock(call)])
            flag, _, rest = request.prompt.split(marker, 1)[1].partition("]\n")
            results.append((flag, rest.split("\n\n", 1)[0]))
            return LLMResponse(content="Decided.", tokens_used=1, content_blocks=[TextBlock("Decided.")])

    model = _Model()
    outcome = await WorkItemAgenticExecutor(llm_client=model).run(
        agent_id=LAFORGE.id, instructions="Decide the requests your crew files.",
        task_text="Review the builder's pending request.", runtime=runtime, max_iterations=3,
    )
    await gap_loop.bus.drain()

    [(flag, text)] = results
    assert "context_invalid" not in text, text
    assert flag == "False"
    assert ast.literal_eval(text) == {
        "decided": True, "queue": "capability", "request_id": req.id, "status": "fulfilled",
        "fulfilled": True, "captain_notified": True, "audited": True,
        "role": "department_chief", "request_class": "non_destructive",
    }
    [context] = contexts
    assert type(context["_tool_result_presentation"]) is ToolResultPresentation
    assert (context["agent_id"], context["agent_department"], context["agent_rank"]) == (
        LAFORGE.id, "engineering", "commander",
    )
    assert (outcome.stopped_reason, outcome.denied_tools, len(model.requests)) == ("complete", [], 2)
    stored = await rig.requests.get(req.id)
    assert (stored.status, stored.decided_by) == ("fulfilled", LAFORGE.id)
    assert (await rig.work_items.get_work_item(item.id)).status == "in_progress"
    assert len(gap_loop.router.dispatched) == 1
    grants = rig.perms.get_active_grants_sync(BUILDER.id, "calc_tool")
    assert [(g.permission, g.issued_by) for g in grants] == [(ToolPermission.READ, LAFORGE.id)]
    [entry] = _audit(rig)
    assert (entry["decider_id"], entry["decider_role"]) == (LAFORGE.id, "department_chief")
    assert [note.agent_id for note in rig.notes.sent] == [LAFORGE.id]
