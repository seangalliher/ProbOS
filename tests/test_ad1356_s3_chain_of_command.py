"""AD-1356 S3 (#1722): the chain of command decides a filed elevated agent-work call; a critical one stays with the Captain.

Each test starts from a work item making the call, in the rig of ``tests/test_ad1347_s3_execution.py`` (the real
ontology, crew, stores, executor, AD-855 driver and Captain route), with AD-1213's ``DelegatedApprovalService`` built
from the same stores as ``startup/finalize.py`` builds it, and ends at the item resuming and finishing. On the base this
file fails at import (``probos.tools.effect_tiers.filed_call_tier``).
"""

from __future__ import annotations

import contextlib
import functools
import json
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from probos.agent_work import AgentWorkCreated, AgentWorkOrigin
from probos.api_models import CapabilityRequestDecideRequest
from probos.approval_authority import ApprovalAuthorityStore
from probos.capability_request import requests_for_work_item
from probos.cognitive.agentic_dispatch import _McpTool
from probos.delegated_approvals import AUDIT_CATEGORY, DeciderRole, DelegatedApprovalService, Refusal, RequestClass
from probos.routers.capability_requests import decide_capability_request, fulfil_on_approval
from probos.security.audit import AuditLog
from probos.tools.effect_tiers import TIER_CRITICAL, filed_call_tier
from tests.test_ad1347_s1_agent_work import RANKS, REASON
from tests.test_ad1347_s3_execution import ANSWER, _call, _final, _pump, _rig, _seen, _thread_in
from tests.test_ad1356_s2_tool_effect_table import NOTES, _native, _notes, _self_task

FILED = "That call needs approval before it runs."
BLOCKED = "waiting for a decision on a tool call this work filed for approval"
DOCS = "Relay docs: the drift budget is 0.5 mm."


class _Notes:
    """``runtime.notify``'s shape: what the Captain was told."""

    def __init__(self) -> None:
        self.sent: list[SimpleNamespace] = []

    def __call__(
        self, agent_id: str, title: str, detail: str = "", notification_type: str = "info", action_url: str = "",
    ) -> None:
        self.sent.append(SimpleNamespace(agent_id=agent_id, title=title, detail=detail))


class _Bridge:
    """``MCPBridge.invoke``'s shape: records what it is asked and answers with the docs text."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str, dict[str, Any]]] = []

    async def invoke(self, server_url: str, tool_name: str, args: dict[str, Any]) -> str:
        self.asked.append((server_url, tool_name, args))
        return DOCS


@contextlib.asynccontextmanager
async def _chain(
    rig: Any, *, enabled: bool = True, **deciders: str,
) -> AsyncIterator[tuple[DelegatedApprovalService, AuditLog, _Notes]]:
    """``approval_inbox`` with ``enabled`` and ``deciders``, and the service ``finalize._wire_delegated_approvals``
    builds over the rig's stores."""
    inbox = rig.runtime.config.approval_inbox.model_copy(update={"delegated_approvals_enabled": enabled, **deciders})
    rig.runtime.config = rig.runtime.config.model_copy(update={"approval_inbox": inbox})
    authority = ApprovalAuthorityStore(db_path="")
    await authority.start()
    audit, notes = AuditLog(), _Notes()
    service = DelegatedApprovalService(
        capability_requests=rig.requests, skill_requests=None, authority_store=authority,
        agent_registry=rig.runtime.registry, ontology=rig.runtime.ontology, tool_registry=rig.tools,
        work_items=rig.store, audit_log=audit, notify=notes,
        fulfil=functools.partial(fulfil_on_approval, rig.runtime),
        settings=lambda: rig.runtime.config.approval_inbox,
    )
    try:
        yield service, audit, notes
    finally:
        await authority.stop()


async def _decide(service: DelegatedApprovalService, agent_id: str, request_id: str) -> Any:
    return await service.decide(
        agent_id, queue="capability", request_id=request_id, approve=True, reason="Within the department's work.",
    )


async def _captain_approves(rig: Any, request_id: str) -> None:
    decided = await decide_capability_request(
        request_id, CapabilityRequestDecideRequest(approve=True),
        runtime=SimpleNamespace(capability_request_store=rig.requests),
    )
    assert decided["fulfilled"] is True
    await _pump(rig)


async def _parked_on(rig: Any, item_id: str) -> Any:
    item = await rig.store.get_work_item(item_id)
    assert item is not None and item.status == "blocked"
    [request] = requests_for_work_item(rig.requests, item_id)
    assert request.status == "pending"
    return request


async def _finished(rig: Any, item_id: str) -> None:
    item = await rig.store.get_work_item(item_id)
    assert item is not None and item.status == "done"


def _listing(tmp_path: Path) -> tuple[Path, list[Any]]:
    notes = _notes(tmp_path)
    listing = {"pattern": "*.txt", "path": str(notes.parent)}
    return notes, [_call("list_files", listing, "c1"), _final("Waiting."), _call("list_files", listing, "c2"), _final(ANSWER)]


# CC1
async def test_a_department_chief_approves_an_elevated_call_and_the_item_resumes_and_runs_it(tmp_path: Path) -> None:
    """forge-1's list_files is elevated: filed, the item parks, and the model is told the call needs approval. LaForge,
    forge-1's chief in Engineering, approves it; the decision is audited and the Captain notified once; the item
    resumes and the call runs."""
    notes, script = _listing(tmp_path)
    async with _rig(tmp_path, script) as rig:
        store = await _native(rig, tmp_path, read_roots=[notes.parent])
        try:
            async with _chain(rig) as (service, audit, told):
                item_id = await _self_task(rig, "List the relay notes")
                request = await _parked_on(rig, item_id)
                parked = await rig.store.get_work_item(item_id)
                assert parked is not None and parked.metadata["blocked_reason"] == BLOCKED
                assert request.rationale == f"agent work {item_id[:8]} called list_files, a call that needs approval"
                assert _seen(rig, FILED) and not _seen(rig, "notes.txt")
                outcome = await _decide(service, "laforge-1", request.id)
                assert (outcome.refusal, outcome.role, outcome.request_class, outcome.fulfilled) == (
                    None, DeciderRole.DEPARTMENT_CHIEF, RequestClass.NON_DESTRUCTIVE, True,
                )
                [entry] = [json.loads(e.detail) for e in audit.entries if e.category == AUDIT_CATEGORY]
                assert (entry["decider_id"], entry["decider_role"], entry["request_class"], entry["approve"]) == (
                    "laforge-1", "department_chief", "non_destructive", True,
                )
                assert entry["target"].startswith("list_files.agent_work_call")
                [note] = told.sent
                assert note.detail.startswith("Department chief laforge-1 approved forge-1's action request")
                await _pump(rig)
                await _finished(rig, item_id)
                assert _seen(rig, "notes.txt")
        finally:
            await store.stop()


# CC2
async def test_a_chiefs_own_elevated_call_and_another_departments_chief_leave_it_with_the_captain(
    tmp_path: Path,
) -> None:
    """LaForge's own list_files is his requisition, and Bones (Medical) has no authority over Engineering: both are
    refused, LaForge's list does not offer it, and it waits for the Captain, whose approval resumes the item."""
    notes, script = _listing(tmp_path)
    async with _rig(tmp_path, script) as rig:
        store = await _native(rig, tmp_path, read_roots=[notes.parent])
        try:
            async with _chain(rig) as (service, _audit, _told):
                origin = await _thread_in(rig, "engineering", "forge-1")
                created = await rig.service.create_self_task(
                    "laforge-1", title="List the relay notes", description="", reason=REASON,
                    origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
                )
                assert isinstance(created, AgentWorkCreated), created
                await _pump(rig)
                item_id = created.work_item.id
                request = await _parked_on(rig, item_id)
                assert (await _decide(service, "laforge-1", request.id)).refusal is Refusal.OWN_REQUISITION
                assert (await _decide(service, "bones-1", request.id)).refusal is Refusal.OUTSIDE_AUTHORITY
                assert (await service.list_reviewable("laforge-1"))[0] == []
                assert (await rig.requests.get(request.id)).status == "pending"
                await _captain_approves(rig, request.id)
                await _finished(rig, item_id)
                assert _seen(rig, "notes.txt")
        finally:
            await store.stop()


# CC3
async def test_a_critical_call_stays_with_the_captain_under_the_most_permissive_settings(tmp_path: Path) -> None:
    """hull_survey is not in the table, so critical: with routine and elevated both auto, LaForge is refused as
    Captain-reserved and his list does not offer it; the Captain's approval runs it once."""
    script = [_call("hull_survey", {}, "c1"), _final("Waiting."), _call("hull_survey", {}, "c2"), _final(ANSWER)]
    async with _rig(tmp_path, script) as rig:
        async with _chain(rig, agent_work_routine_decider="auto", agent_work_elevated_decider="auto") as (
            service, _audit, _told,
        ):
            item_id = await _self_task(rig, "Survey the hull")
            request = await _parked_on(rig, item_id)
            outcome = await _decide(service, "laforge-1", request.id)
            assert (outcome.refusal, outcome.request_class) == (Refusal.CAPTAIN_RESERVED, RequestClass.CAPTAIN_RESERVED)
            assert (await service.list_reviewable("laforge-1"))[0] == [] and rig.survey.calls == 0
            await _captain_approves(rig, request.id)
            await _finished(rig, item_id)
            assert rig.survey.calls == 1


# CC4
async def test_a_filed_path_read_stays_with_the_captain_after_read_roots_are_set(tmp_path: Path) -> None:
    """With read_roots unset, forge-1's read_file is filed. Setting the roots afterwards does not let LaForge decide
    it. The Captain approves; the resumed run reads under the roots and finishes."""
    notes = _notes(tmp_path)
    read = {"path": str(notes)}
    script = [_call("read_file", read, "c1"), _final("Waiting."), _call("read_file", read, "c2"), _final(ANSWER)]
    async with _rig(tmp_path, script) as rig:
        store = await _native(rig, tmp_path, read_roots=[])
        try:
            async with _chain(rig) as (service, _audit, _told):
                item_id = await _self_task(rig, "Read the relay notes")
                request = await _parked_on(rig, item_id)
                security = rig.runtime.config.security_infra.model_copy(update={"read_roots": [str(notes.parent)]})
                rig.runtime.config = rig.runtime.config.model_copy(update={"security_infra": security})
                assert (await _decide(service, "laforge-1", request.id)).refusal is Refusal.CAPTAIN_RESERVED
                assert not _seen(rig, NOTES)
                await _captain_approves(rig, request.id)
                await _finished(rig, item_id)
                assert _seen(rig, NOTES)
        finally:
            await store.stop()


# CC5
@pytest.mark.parametrize("case", ["open", "confirm", "reaped"])
async def test_an_mcp_call_takes_its_tier_from_its_ad1019b_risk(tmp_path: Path, case: str) -> None:
    """An OPEN MCP tool is elevated: LaForge approves forge-1's call and it runs. A CONFIRM tool is critical, and so is
    an OPEN tool no longer registered when its call is decided: LaForge is refused, and after the Captain's approval
    the item finishes with the bridge never asked."""
    bridge = _Bridge()
    tool = _McpTool(
        bridge=bridge, server_url="docs", server_name="docs", server_id="srv-docs", tool_name="search", name="search",
        description="Search the relay docs.", input_schema={"type": "object"},
        server_default_risk="confirm" if case == "confirm" else "open", risk_store=None,
        consensus_invoke=AsyncMock(), authorize=lambda agent_id: True,
    )
    query = {"query": "drift budget"}
    script = [_call(tool.tool_id, query, "c1"), _final("Waiting."), _call(tool.tool_id, query, "c2"), _final(ANSWER)]
    async with _rig(tmp_path, script) as rig:
        rig.tools.register(
            tool, provider="AD-1019c", tags=[tool.tool_id, "mcp"], default_permissions=dict.fromkeys(RANKS, "read"),
        )
        async with _chain(rig) as (service, _audit, _told):
            item_id = await _self_task(rig, "Look up the drift budget")
            request = await _parked_on(rig, item_id)
            if case == "reaped":
                assert rig.tools.unregister(tool.tool_id)
            outcome = await _decide(service, "laforge-1", request.id)
            if case == "open":
                assert (outcome.refusal, outcome.role, outcome.fulfilled) == (None, DeciderRole.DEPARTMENT_CHIEF, True)
                await _pump(rig)
                await _finished(rig, item_id)
                assert bridge.asked == [("docs", "search", query)] and _seen(rig, DOCS)
            else:
                assert outcome.refusal is Refusal.CAPTAIN_RESERVED
                await _captain_approves(rig, request.id)
                await _finished(rig, item_id)
                assert bridge.asked == []
    assert filed_call_tier(tool.tool_id, tool_registry=None) == TIER_CRITICAL


# CC6
async def test_with_delegated_approvals_off_a_filed_elevated_call_waits_for_the_captain(tmp_path: Path) -> None:
    """Off: LaForge's decision is refused as switched off, nothing is audited or notified, and the elevated call stays
    pending with the item parked; the Captain's approval resumes the item and the call runs."""
    notes, script = _listing(tmp_path)
    async with _rig(tmp_path, script) as rig:
        store = await _native(rig, tmp_path, read_roots=[notes.parent])
        try:
            async with _chain(rig, enabled=False) as (service, audit, told):
                item_id = await _self_task(rig, "List the relay notes")
                request = await _parked_on(rig, item_id)
                assert (await _decide(service, "laforge-1", request.id)).refusal is Refusal.NOT_ENABLED
                assert [e for e in audit.entries if e.category == AUDIT_CATEGORY] == [] and told.sent == []
                await _parked_on(rig, item_id)
                await _captain_approves(rig, request.id)
                await _finished(rig, item_id)
                assert _seen(rig, "notes.txt")
        finally:
            await store.stop()
