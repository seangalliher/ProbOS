"""AD-1356 S4 (#1722): the Captain's per-tier "who decides" setting, with critical fixed at the Captain.

The whole-path tests reuse ``tests/test_ad1356_s3_chain_of_command.py``'s chain on the AD-1347 rig; the boundary test
posts to the real ``/api/config`` route. On the base this file fails at import
(``probos.tools.effect_tiers.direct_tool_ids``).
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from probos.agent_work_runner import APPROVAL_USE_PREFIX
from probos.capability_request import requests_for_work_item
from probos.config_models.experience import ApprovalInboxConfig
from probos.delegated_approvals import DeciderRole, Refusal
from probos.tools.effect_tiers import (
    DECIDER_CAPTAIN,
    ELEVATED_TOOL_IDS,
    ROUTINE_TOOL_IDS,
    TIER_CRITICAL,
    direct_tool_ids,
    routine_tool_ids,
    tier_decider,
    tool_tier,
)
from tests.test_ad1347_s3_execution import ANSWER, WINDOW, _call, _final, _pump, _rig, _seen
from tests.test_ad1356_s2_tool_effect_table import _native, _notes, _self_task
from tests.test_ad1356_s3_chain_of_command import _captain_approves, _chain, _decide, _finished, _parked_on
from tests.test_ad741_config_api import _build_runtime, _client

SETTINGS = ("auto", "chief", "captain")
STOP_ORDERS = [_call("event_log_query", WINDOW, "c1"), _final("Waiting."), _call("event_log_query", WINDOW, "c2"), _final(ANSWER)]


# WD1
async def test_with_elevated_set_to_auto_list_files_runs_with_nothing_filed(tmp_path: Path) -> None:
    """Elevated auto: list_files is in the run's direct set, so it runs, nothing is filed and the item is done."""
    notes = _notes(tmp_path)
    script = [_call("list_files", {"pattern": "*.txt", "path": str(notes.parent)}, "c1"), _final(ANSWER)]
    async with _rig(tmp_path, script) as rig:
        store = await _native(rig, tmp_path, read_roots=[notes.parent])
        try:
            async with _chain(rig, agent_work_elevated_decider="auto"):
                item_id = await _self_task(rig, "List the relay notes")
                await _finished(rig, item_id)
                assert requests_for_work_item(rig.requests, item_id) == [] and _seen(rig, "notes.txt")
        finally:
            await store.stop()


# WD2
async def test_with_routine_and_elevated_set_to_captain_a_routine_call_is_filed_and_only_the_captain_decides(
    tmp_path: Path,
) -> None:
    """The confinement's set is empty, so forge-1's routine event_log_query is filed; LaForge is refused as
    Captain-reserved, and the Captain's approval resumes the item, whose run uses that approval."""
    async with _rig(tmp_path, STOP_ORDERS) as rig:
        async with _chain(rig, agent_work_routine_decider="captain", agent_work_elevated_decider="captain") as (
            service, _audit, _told,
        ):
            item_id = await _self_task(rig, "Read the stop orders")
            request = await _parked_on(rig, item_id)
            assert request.payload["tool_id"] == "event_log_query"
            assert (await _decide(service, "laforge-1", request.id)).refusal is Refusal.CAPTAIN_RESERVED
            await _captain_approves(rig, request.id)
            await _finished(rig, item_id)
            assert not await rig.store.claim_work_notice(item_id, "forge-1", APPROVAL_USE_PREFIX + request.id, 0.0)


# WD3
async def test_with_routine_set_to_chief_a_routine_call_is_filed_and_the_chief_decides_it(tmp_path: Path) -> None:
    """Routine chief: forge-1's event_log_query is filed, LaForge approves it, and the resumed run uses the approval."""
    async with _rig(tmp_path, STOP_ORDERS) as rig:
        async with _chain(rig, agent_work_routine_decider="chief") as (service, _audit, _told):
            item_id = await _self_task(rig, "Read the stop orders")
            request = await _parked_on(rig, item_id)
            outcome = await _decide(service, "laforge-1", request.id)
            assert (outcome.refusal, outcome.role, outcome.fulfilled) == (None, DeciderRole.DEPARTMENT_CHIEF, True)
            await _pump(rig)
            await _finished(rig, item_id)
            assert not await rig.store.claim_work_notice(item_id, "forge-1", APPROVAL_USE_PREFIX + request.id, 0.0)


# WD4
def test_critical_is_the_captains_under_every_setting_and_no_config_value_moves_it(tmp_path: Path) -> None:
    """Boundary: agent_work_critical_decider accepts only captain, in the model and through POST /api/config, which
    persists a valid setting for the next start and nothing for a refused one. Under every setting and read policy a
    critical tier is the Captain's and no critical tool is in a run's direct set."""
    defaults = ApprovalInboxConfig()
    assert (defaults.agent_work_routine_decider, defaults.agent_work_elevated_decider) == ("auto", "chief")
    assert defaults.agent_work_critical_decider == "captain"
    for value in ("chief", "auto", "Captain", "", None, 1):
        with pytest.raises(ValidationError):
            ApprovalInboxConfig(agent_work_critical_decider=value)
    for field in ("agent_work_routine_decider", "agent_work_elevated_decider"):
        with pytest.raises(ValidationError):
            ApprovalInboxConfig(**{field: "self"})
    for routine, elevated, confined in itertools.product(SETTINGS, SETTINGS, (True, False)):
        assert tier_decider(TIER_CRITICAL, routine=routine, elevated=elevated) == DECIDER_CAPTAIN
        direct = direct_tool_ids(reads_confined=confined, routine=routine, elevated=elevated)
        assert direct <= ROUTINE_TOOL_IDS | ELEVATED_TOOL_IDS
        assert all(tool_tier(tool_id, reads_confined=confined) != TIER_CRITICAL for tool_id in direct)
    for confined in (True, False):
        assert direct_tool_ids(reads_confined=confined, routine="auto", elevated="chief") == routine_tool_ids(
            reads_confined=confined,
        )
    runtime = _build_runtime(tmp_path)
    client = _client(runtime)
    path = Path(runtime.config_path)

    def post(patch: dict[str, str]) -> object:
        csrf = client.get("/api/config").json()["csrf_token"]
        return client.post("/api/config", json={"patch": {"approval_inbox": patch}}, headers={"X-Probos-CSRF": csrf})

    ok = post({"agent_work_elevated_decider": "captain"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["restart_required"] is True
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["approval_inbox"]["agent_work_elevated_decider"] == "captain"
    written = path.read_bytes()
    for patch in ({"agent_work_critical_decider": "chief"}, {"agent_work_routine_decider": "self"}):
        refused = post(patch)
        assert refused.status_code == 422 and refused.json()["error"] == "validation_failed"
        assert path.read_bytes() == written
