"""AD-1194 (#1131): every capability-gap producer files through the AD-854 ladder.

Before AD-1194 two capability-gap paths existed and only one was triaged. AD-855's
work-item gaps went through ``capability_triage.triage_and_file``; the ordinary NL
path jumped from "no agent handles this" straight to the self-modification
pipeline, whose approval gate passes when no console callback is wired -- a serve
vessel until its first HXI slash command, which wires a stdin prompt nobody
answers (premise probe P3 in the build contract: ``require_user_approval=True``
and no callback designed and registered an agent).

With ``capability_triage.unified_ladder_enabled`` the gap walks
``grant -> discover -> install -> forge -> build``, the verdict of every rung is
recorded on the request, and no gap is designed without a recorded approval the
approval policy admits: the Captain's, or a delegate's for a build that requires
no consensus (A-1). OFF, every producer is byte-identical to HEAD.

Two defects surfaced while verifying the premise are pinned here as well:

* F1 -- a build's BF-744 design context was decoded as an ACTION payload on read,
  so it was dropped on every restart; an approve-later build then designed with
  ``requires_consensus=False`` and delegated approval classified it DESTRUCTIVE
  rather than Captain-reserved. Fixed unconditionally (it was latent at HEAD: no
  producer filed a build payload yet).
* F2 -- the HXI Build Agent button never passed ``requires_consensus``. Fixed
  under the flag: the click approves the request filed at proposal time and
  designs with the governance that request recorded server-side.
* A-1 -- joining the card pending for an NL gap could leave it weaker than the
  gap, the ladder's pre-approval followed the flag rather than the approval on
  record, and two concurrent filings of one gap filed two cards.

Every chain test crosses the seam end to end -- producer -> ladder -> durable
request -> (restart) -> Captain approval -> fulfiller -> pipeline -> FULFILLED ->
resume -- because a test that stops at "the fulfiller was called" is how this
repository's dominant defect shape survives.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import logging
import sqlite3
import typing
from collections.abc import AsyncIterator
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos import capability_request as capability_request_mod
from probos.api_models import CapabilityRequestDecideRequest, SelfModRequest
from probos.capability_request import (
    TRIAGE_GAP_CLASSES,
    TRIAGE_OUTCOMES,
    TRIAGE_RUNGS,
    CapabilityRequestStore,
    validate_build_payload,
    validate_triage_record,
)
from probos.cognitive import capability_triage, nl_gap_triage
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.capability_triage import (
    LADDER_ORDER,
    GapClass,
    LadderRung,
    RungOutcome,
    RungVerdict,
    _build_payload,
    evaluate_ladder,
    fulfil_build,
    triage,
    triage_and_file,
    unified_ladder_enabled,
)
from probos.cognitive.self_mod import SelfModificationPipeline
from probos.config import CapabilityTriageConfig, SystemConfig
from probos.delegated_approvals import (
    DeciderRole,
    Refusal,
    RequestClass,
    classify_capability_request,
    evaluate,
)
from probos.events import EventType
from probos.routers import capability_requests as router_mod
from probos.routers.capability_requests import _serialize, decide_capability_request
from probos.runtime import ProbOSRuntime, file_dependency_install_requests
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission
from probos.workforce import WorkItemStore
from tests.test_ad1211_approval_fulfils_every_kind import (
    _EventBus,
    _RecordingRouter,
    _registration,
    _Runtime,
    _ToolRegistry,
)
from tests.test_ad1213_delegated_approvals import (  # noqa: F401 -- ontology and rig are fixtures
    _GRACE,
    BUILDER,
    NUMBER_ONE,
    _Rig,
    ontology,
    rig,
)
from tests.test_ad1220_install_requests_reach_the_captain import _Resolver
from tests.test_ad1220_install_requests_reach_the_captain import _runtime as _dependency_runtime

_BOOLS = [(r, p, s) for r in (False, True) for p in (False, True) for s in (False, True)]
_DESIGN = {
    "intent_description": "delete the files in a directory",
    "parameters": {"path": "the directory"},
    "requires_consensus": True,
    "execution_context": "Prior user request: 'ls'",
}
_META = {
    "name": "wipe_disk",
    "description": "wipe a disk",
    "parameters": {"device": "which disk"},
    "requires_consensus": True,
}


def _on() -> SimpleNamespace:
    return SimpleNamespace(
        capability_triage=CapabilityTriageConfig(unified_ladder_enabled=True)
    )


class _Pipeline:
    """Records what the self-mod pipeline was asked to design."""

    def __init__(self, status: str = "active") -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self._status = status

    async def handle_unhandled_intent(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        return SimpleNamespace(
            status=self._status, agent_type="designed", intent_name="designed",
            class_name="DesignedAgent", strategy="new_agent", source_code="",
            error="" if self._status == "active" else "not built",
        )


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[CapabilityRequestStore]:
    requests = CapabilityRequestStore(db_path=str(tmp_path / "cap.db"))
    await requests.start()
    try:
        yield requests
    finally:
        await requests.stop()


@pytest.fixture
async def perms(tmp_path: Path) -> AsyncIterator[ToolPermissionStore]:
    permissions = ToolPermissionStore(db_path=str(tmp_path / "perms.db"))
    await permissions.start()
    try:
        yield permissions
    finally:
        await permissions.stop()


async def _reopen(requests: CapabilityRequestStore) -> CapabilityRequestStore:
    await requests.stop()
    fresh = CapabilityRequestStore(db_path=requests.db_path)
    try:
        await fresh.start()
    except BaseException:
        # A connection opened by a failed start() keeps a non-daemon thread alive
        # and hangs the process at exit, so close it before re-raising.
        await fresh.stop()
        raise
    return fresh


def _columns(db_path: str) -> list[str]:
    connection = sqlite3.connect(db_path)
    try:
        return [row[1] for row in connection.execute("PRAGMA table_info(capability_requests)")]
    finally:
        connection.close()


# ══ 1. The pure ladder ═════════════════════════════════════════════════════


@pytest.mark.parametrize(("registered", "permitted", "known"), _BOOLS)
def test_evaluate_ladder_tool_gap_selects_exactly_what_triage_selects(
    registered: bool, permitted: bool, known: bool,
) -> None:
    """Routing AD-855 through the ladder must not change the rung it files."""
    record = evaluate_ladder(
        gap_class="tool",
        tool_registered=registered,
        agent_has_permission=permitted,
        skill_known=known,
    )

    assert record.selected == triage(
        tool_registered=registered, agent_has_permission=permitted, skill_known=known,
    )


@pytest.mark.parametrize("gap_class", ["tool", "intent", "package"])
@pytest.mark.parametrize("discovery", [None, [], ["a [agent] via own", "b [mcp] via https://x"]])
def test_every_record_names_every_rung_once_in_order_with_one_selected(
    gap_class: str, discovery: list[str] | None,
) -> None:
    for registered, permitted, known in _BOOLS:
        record = evaluate_ladder(
            gap_class=gap_class,  # type: ignore[arg-type]
            tool_registered=registered,
            agent_has_permission=permitted,
            skill_known=known,
            discovery=discovery,
        )

        assert tuple(verdict.rung for verdict in record.rungs) == LADDER_ORDER
        assert [v.rung for v in record.rungs if v.outcome == "selected"] == [record.selected]
        assert all(verdict.reason for verdict in record.rungs)
        # What the producer writes is exactly what the store accepts and re-reads.
        assert validate_triage_record(record.to_dict()) == record.to_dict()


def test_an_intent_gap_builds_and_records_why_nothing_cheaper_applies() -> None:
    record = evaluate_ladder(gap_class="intent")

    assert record.selected == "build"
    assert {v.rung: v.outcome for v in record.rungs} == {
        "grant": "not_applicable",
        "discover": "not_run",
        "install": "not_applicable",
        "forge": "not_applicable",
        "build": "selected",
    }


def test_a_package_gap_installs_and_never_consults_a_catalog() -> None:
    record = evaluate_ladder(gap_class="package", discovery=["would be ignored"])

    assert record.selected == "install"
    assert {v.rung: v.outcome for v in record.rungs} == {
        "grant": "not_applicable",
        "discover": "not_applicable",
        "install": "selected",
        "forge": "not_run",
        "build": "not_run",
    }
    assert all(not verdict.candidates for verdict in record.rungs)


def test_discovery_candidates_are_recorded_but_never_selected() -> None:
    """AD-1049's rule: discovery surfaces a candidate, it never adopts one."""
    record = evaluate_ladder(gap_class="intent", discovery=["urn:x [mcp] via own"])

    discover = record.rungs[1]
    assert (discover.rung, discover.outcome) == ("discover", "escalated")
    assert discover.candidates == ("urn:x [mcp] via own",)
    assert record.selected == "build"


def test_a_discovery_that_ran_and_found_nothing_is_not_recorded_as_not_run() -> None:
    discover = evaluate_ladder(gap_class="intent", discovery=[]).rungs[1]

    assert (discover.outcome, discover.candidates) == ("escalated", ())
    assert "no catalog resource" in discover.reason


def test_a_selected_grant_leaves_every_later_rung_not_run() -> None:
    record = evaluate_ladder(
        gap_class="tool", tool_registered=True, agent_has_permission=False, discovery=["x"],
    )

    assert record.selected == "grant"
    assert [v.outcome for v in record.rungs] == ["selected"] + ["not_run"] * 4
    assert record.rungs[1].candidates == ()


def test_the_ladder_vocabulary_is_the_one_the_store_validates() -> None:
    assert set(typing.get_args(GapClass)) == TRIAGE_GAP_CLASSES
    assert typing.get_args(LadderRung) == TRIAGE_RUNGS == LADDER_ORDER
    assert set(typing.get_args(RungOutcome)) == TRIAGE_OUTCOMES


def test_a_rung_verdict_is_bounded_and_storable() -> None:
    long = RungVerdict(
        "discover", "escalated", "r" * 500, tuple(f"c{i}" * 100 for i in range(9)),
    ).to_dict()
    lone = RungVerdict("discover", "escalated", "bad \ud800 text", ("x\udfff",)).to_dict()

    assert len(long["reason"]) == 200
    assert len(long["candidates"]) == 5
    assert all(len(candidate) <= 120 for candidate in long["candidates"])
    # A lone surrogate is a legal str that SQLite cannot bind (BF-854).
    lone["reason"].encode("utf-8")
    lone["candidates"][0].encode("utf-8")


# ══ 2. The flag ════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        (None, False),
        (SimpleNamespace(), False),
        (SimpleNamespace(capability_triage=None), False),
        (SimpleNamespace(capability_triage=SimpleNamespace(unified_ladder_enabled=1)), False),
        (MagicMock(), False),
        (SystemConfig(), False),
        (SystemConfig(capability_triage=CapabilityTriageConfig(unified_ladder_enabled=True)), True),
        (_on(), True),
    ],
)
def test_unified_ladder_enabled_accepts_only_a_real_true(config: Any, expected: bool) -> None:
    """A MagicMock config -- common in this repository's tests -- must read OFF."""
    assert unified_ladder_enabled(config) is expected


# ══ 3. The store: F1 and the triage column ═════════════════════════════════


@pytest.mark.asyncio
async def test_a_build_design_context_survives_a_restart(store: CapabilityRequestStore) -> None:
    """F1. Read back as an ACTION payload it came back ``None``, so an approve-later
    build lost its consensus gate and delegated approval stopped reserving it."""
    request = await store.file_request("agent-1", "build", "delete_files", payload=dict(_DESIGN))
    before = classify_capability_request(request, tool_registry=None)

    reopened = await _reopen(store)
    try:
        loaded = await reopened.get(request.id)
        after = classify_capability_request(loaded, tool_registry=None)
    finally:
        await reopened.stop()

    assert loaded is not None and loaded.payload == _DESIGN
    assert before is after is RequestClass.CAPTAIN_RESERVED


@pytest.mark.parametrize(
    "payload",
    [
        {"requires_consensus": "yes"},
        {"intent_description": 7},
        {"parameters": {"a": 1}},
        {"parameters": ["a"]},
        {"smuggled": "x"},
        {"intent_description": "x" * 4001},
        {"parameters": {f"k{i}": "v" for i in range(21)}},
        # An action-shaped payload on a build row read back WHOLE at HEAD.
        {"tool_id": "browser", "action": "navigate", "params": {}, "scope_key": "",
         "session_id": None, "thread_id": ""},
    ],
)
@pytest.mark.asyncio
async def test_a_malformed_build_payload_loads_as_none_after_a_restart(
    store: CapabilityRequestStore, payload: dict[str, Any],
) -> None:
    request = await store.file_request("agent-1", "build", "target", payload=payload)

    reopened = await _reopen(store)
    try:
        loaded = await reopened.get(request.id)
    finally:
        await reopened.stop()

    assert loaded is not None and loaded.payload is None
    assert loaded.status == "pending"


@pytest.mark.parametrize(
    ("payload", "valid"),
    [
        ({}, True),
        (dict(_DESIGN), True),
        ({"requires_consensus": False}, True),
        (None, False),
        ("x", False),
        ([], False),
        ({"requires_consensus": 1}, False),
        ({"execution_context": None}, False),
        ({"parameters": {"k": "v" * 501}}, False),
        ({"intent_description": "\ud800"}, False),
    ],
)
def test_validate_build_payload_boundaries(payload: Any, valid: bool) -> None:
    assert (validate_build_payload(payload) is not None) is valid


@pytest.mark.parametrize(
    "context",
    [
        None,
        {},
        "not a dict",
        {"unrelated": 1},
        dict(_DESIGN),
        {"intent_description": None, "requires_consensus": "false", "parameters": {"n": 3, 4: "x"}},
        {
            "intent_description": "d" * 9000,
            "execution_context": "e\ud800",
            "parameters": {f"k{i}": "v" * 900 for i in range(30)},
        },
        {"parameters": "not a dict", "requires_consensus": 0},
    ],
)
def test_the_build_payload_normaliser_writes_only_what_survives_a_restart(context: Any) -> None:
    payload = _build_payload(context)

    assert payload is None or validate_build_payload(payload) == payload


def test_the_normaliser_keeps_fulfil_builds_truthiness_for_consensus() -> None:
    """A model that answers "false" as a string asked for consensus at HEAD too."""
    assert _build_payload({"requires_consensus": "false"}) == {"requires_consensus": True}
    assert _build_payload({"requires_consensus": 0}) == {"requires_consensus": False}


def test_an_oversized_context_sheds_detail_first_and_never_the_consensus_requirement(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Per-field bounds do not bound escaped JSON: a control character is six."""
    trimmed = _build_payload({
        "intent_description": "keep me",
        "execution_context": "\x01" * 2500,
        "parameters": {"path": "the directory"},
        "requires_consensus": True,
    })
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.capability_triage"):
        shed = _build_payload({
            "intent_description": "\x01" * 4000,
            "execution_context": "\x01" * 4000,
            "parameters": {f"k{i}": "\x01" * 500 for i in range(20)},
            "requires_consensus": True,
        })

    assert trimmed == {
        "intent_description": "keep me", "parameters": {"path": "the directory"},
        "requires_consensus": True,
    }
    assert shed == {"requires_consensus": True}
    order = [caplog.text.index(f"dropping {field}")
             for field in ("execution_context", "parameters", "intent_description")]
    assert order == sorted(order)


@pytest.mark.asyncio
async def test_a_triage_record_round_trips_through_a_restart(store: CapabilityRequestStore) -> None:
    record = evaluate_ladder(gap_class="intent", discovery=["urn:x [agent] via own"]).to_dict()
    request = await store.file_request("system", "build", "count_words", triage=record)

    reopened = await _reopen(store)
    try:
        loaded = await reopened.get(request.id)
    finally:
        await reopened.stop()

    assert request.triage == record
    assert loaded is not None and loaded.triage == record


@pytest.mark.asyncio
async def test_an_invalid_triage_record_is_dropped_not_the_request(
    store: CapabilityRequestStore, caplog: pytest.LogCaptureFixture,
) -> None:
    """Evidence, not authority: losing the record must not cost the Captain the ask."""
    bad = evaluate_ladder(gap_class="intent").to_dict()
    bad["selected"] = "discover"

    with caplog.at_level(logging.WARNING, logger="probos.capability_request"):
        request = await store.file_request("system", "build", "count_words", triage=bad)

    assert (request.status, request.triage) == ("pending", None)
    assert "invalid triage record" in caplog.text
    reopened = await _reopen(store)
    try:
        loaded = await reopened.get(request.id)
    finally:
        await reopened.stop()
    assert loaded is not None and loaded.triage is None


@pytest.mark.parametrize(
    "raw",
    ["{not json", '"a string"', "[]", json.dumps({"version": 2}), json.dumps({"rungs": None})],
)
@pytest.mark.asyncio
async def test_a_corrupt_triage_column_loads_the_request_without_it(
    store: CapabilityRequestStore, raw: str,
) -> None:
    request = await store.file_request("system", "build", "count_words")
    await store.stop()
    connection = sqlite3.connect(store.db_path)
    try:
        connection.execute(
            "UPDATE capability_requests SET triage=? WHERE id=?", (raw, request.id),
        )
        connection.commit()
    finally:
        connection.close()

    await store.start()
    loaded = await store.get(request.id)

    assert loaded is not None and loaded.triage is None
    assert loaded.status == "pending"


def _good_record() -> dict[str, Any]:
    return evaluate_ladder(gap_class="tool").to_dict()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(version=True),
        lambda r: r.update(version=2),
        lambda r: r.update(gap_class=["tool"]),
        lambda r: r.update(selected="discover"),
        lambda r: r.update(selected=["build"]),
        lambda r: r.update(extra=1),
        lambda r: r["rungs"].reverse(),
        lambda r: r["rungs"].pop(),
        lambda r: r["rungs"][0].update(extra=1),
        lambda r: r["rungs"][0].update(outcome="maybe"),
        lambda r: r["rungs"][0].update(reason="x" * 201),
        lambda r: r["rungs"][0].update(outcome="selected"),
        lambda r: r["rungs"][1].update(candidates=["c"] * 6),
        lambda r: r["rungs"][1].update(candidates=[3]),
        lambda r: r["rungs"][1].update(candidates=["c" * 121]),
        lambda r: r["rungs"][1].update(reason="\ud800"),
    ],
)
def test_validate_triage_record_rejects_a_malformed_record(mutate: Any) -> None:
    record = _good_record()
    assert validate_triage_record(record) == record, "premise: the unmutated record is valid"
    mutate(record)

    assert validate_triage_record(record) is None


@pytest.mark.parametrize("value", [None, "x", [], 3])
def test_validate_triage_record_rejects_a_non_record(value: Any) -> None:
    assert validate_triage_record(value) is None


_POST_AD1154_SCHEMA = """
CREATE TABLE capability_requests (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    work_item_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    decided_at REAL,
    decided_by TEXT NOT NULL DEFAULT '',
    decision_reason TEXT NOT NULL DEFAULT '',
    payload TEXT
);
"""


@pytest.mark.asyncio
async def test_a_twelve_column_table_gains_triage_once_and_keeps_its_rows(tmp_path: Path) -> None:
    db = str(tmp_path / "v12.db")
    connection = sqlite3.connect(db)
    try:
        connection.executescript(_POST_AD1154_SCHEMA)
        connection.execute(
            "INSERT INTO capability_requests VALUES "
            "('old', 'agent-z', 'build', 'delete_files', 'r', NULL, 'pending', 1.0, "
            "NULL, '', '', ?)",
            (json.dumps({"requires_consensus": True}),),
        )
        connection.commit()
    finally:
        connection.close()

    for _restart in range(2):
        requests = CapabilityRequestStore(db_path=db)
        try:
            await requests.start()
            old = await requests.get("old")
        finally:
            await requests.stop()
        columns = _columns(db)

        assert columns[-2:] == ["payload", "triage"] and columns.count("triage") == 1
        assert old is not None and old.triage is None
        assert old.payload == {"requires_consensus": True}


@pytest.mark.asyncio
async def test_serialize_adds_triage_only_to_a_request_filed_through_the_ladder(
    store: CapabilityRequestStore,
) -> None:
    """OFF, the wire shape of every request is exactly the HEAD shape."""
    plain = await store.file_request("agent-1", "grant", "tool")
    laddered = await store.file_request(
        "agent-1", "grant", "tool",
        triage=evaluate_ladder(gap_class="tool", tool_registered=True).to_dict(),
    )

    assert list(_serialize(plain)) == [
        "id", "agent_id", "kind", "target", "rationale", "work_item_id", "status",
        "created_at", "decided_at", "decided_by", "decision_reason", "payload",
    ]
    assert _serialize(laddered)["triage"] == laddered.triage


# ══ 4. triage_and_file(unified=...) ════════════════════════════════════════


@pytest.mark.asyncio
async def test_unified_false_ignores_the_ad1194_parameters(tmp_path: Path) -> None:
    """OFF is the HEAD body: the file-time build still runs, nothing is recorded,
    and the discover rung is never called."""
    seen: list[str] = []

    async def discover(target: str) -> list[str]:
        seen.append(target)
        return ["x"]

    outcomes = []
    for index, extra in enumerate(
        ({}, {"gap_class": "intent", "unified": False, "discover_candidates": discover})
    ):
        requests = CapabilityRequestStore(db_path=str(tmp_path / f"off{index}.db"))
        await requests.start()
        pipe = _Pipeline()
        try:
            request = await triage_and_file(
                gap_target="count_words", agent_id="agent-1", store=requests,
                rationale="gap", self_mod_pipeline=pipe,
                design_context={"requires_consensus": True}, **extra,
            )
            outcomes.append(
                (request.kind, request.status, request.payload, request.triage,
                 [kwargs for _args, kwargs in pipe.calls])
            )
        finally:
            await requests.stop()

    assert outcomes[0] == outcomes[1]
    assert outcomes[0][:2] == ("build", "fulfilled") and outcomes[0][3] is None
    assert seen == []


@pytest.mark.asyncio
async def test_a_unified_tool_gap_files_a_grant_with_its_record_and_skips_discovery(
    store: CapabilityRequestStore, perms: ToolPermissionStore,
) -> None:
    seen: list[str] = []

    async def discover(target: str) -> list[str]:
        seen.append(target)
        return ["x"]

    request = await triage_and_file(
        gap_target="reader", agent_id="agent-1", store=store,
        tool_registry=_ToolRegistry({"reader": _registration({"ensign": "read"})}),
        permission_store=perms, unified=True, discover_candidates=discover,
    )

    assert (request.kind, request.status) == ("grant", "pending")
    assert request.triage is not None and request.triage["selected"] == "grant"
    assert [v["outcome"] for v in request.triage["rungs"]] == ["selected"] + ["not_run"] * 4
    assert seen == []


@pytest.mark.asyncio
async def test_the_grant_fast_path_is_still_the_only_file_time_fulfilment(
    store: CapabilityRequestStore, perms: ToolPermissionStore,
) -> None:
    await perms.issue_grant("peer-1", "reader", ToolPermission.READ, reason="peer", issued_by="captain")

    request = await triage_and_file(
        gap_target="reader", agent_id="agent-1", store=store,
        tool_registry=_ToolRegistry({"reader": _registration({"ensign": "read"})}),
        permission_store=perms,
        ontology=SimpleNamespace(get_agent_department=lambda _agent: "science"),
        trust_network=SimpleNamespace(get_score=lambda _agent: 0.99),
        config=CapabilityTriageConfig(grant_fast_path_enabled=True, grant_trust_floor=0.5),
        unified=True,
    )

    assert (request.kind, request.status) == ("grant", "fulfilled")
    assert perms.get_active_grants_sync("agent-1", "reader")


@pytest.mark.asyncio
async def test_a_unified_build_is_left_pending_and_never_designed_at_file_time(
    store: CapabilityRequestStore,
) -> None:
    """The file-time build ran the pipeline, whose gate passes with no callback."""
    pipe = _Pipeline()
    seen: list[str] = []

    async def discover(target: str) -> list[str]:
        seen.append(target)
        return ["weather [mcp] via own"]

    request = await triage_and_file(
        gap_target="weather", agent_id="agent-1", store=store, rationale="needs weather",
        tool_registry=_ToolRegistry({}), self_mod_pipeline=pipe,
        design_context={"requires_consensus": True}, unified=True, discover_candidates=discover,
    )

    assert (request.kind, request.status) == ("build", "pending")
    assert pipe.calls == []
    assert request.payload == {"requires_consensus": True}
    assert seen == ["weather"]
    rungs = {verdict["rung"]: verdict for verdict in request.triage["rungs"]}
    assert rungs["discover"]["candidates"] == ["weather [mcp] via own"]
    assert rungs["grant"]["outcome"] == rungs["install"]["outcome"] == "escalated"
    assert rungs["forge"]["outcome"] == "not_applicable"


@pytest.mark.asyncio
async def test_a_unified_tool_gap_installs_a_disabled_mcp_server(store: CapabilityRequestStore) -> None:
    servers = SimpleNamespace(
        list_sync=lambda: [SimpleNamespace(id="srv-1", name="weather", enabled=False)],
    )

    request = await triage_and_file(
        gap_target="weather", agent_id="agent-1", store=store,
        mcp_server_store=servers, unified=True,
    )

    assert (request.kind, request.status) == ("install", "pending")
    assert request.payload == {"install_kind": "mcp", "mcp_server_id": "srv-1"}
    assert request.triage["selected"] == "install"


@pytest.mark.asyncio
async def test_a_unified_package_gap_files_a_python_install_without_discovery(
    store: CapabilityRequestStore,
) -> None:
    seen: list[str] = []

    async def discover(target: str) -> list[str]:
        seen.append(target)
        return ["x"]

    request = await triage_and_file(
        gap_target="feedparser", agent_id="agent-1", store=store, rationale="needs it",
        gap_class="package", unified=True, discover_candidates=discover,
    )

    assert (request.kind, request.status) == ("install", "pending")
    assert request.payload == {"install_kind": "python"}
    assert request.triage["gap_class"] == "package"
    assert seen == []


@pytest.mark.asyncio
async def test_a_failing_discover_rung_is_recorded_as_not_run_and_filing_proceeds(
    store: CapabilityRequestStore,
) -> None:
    async def boom(_target: str) -> list[str]:
        raise RuntimeError("catalog down")

    request = await triage_and_file(
        gap_target="count_words", agent_id="system", store=store,
        gap_class="intent", unified=True, discover_candidates=boom,
    )

    assert (request.kind, request.status) == ("build", "pending")
    assert request.triage["rungs"][1]["outcome"] == "not_run"


@pytest.mark.asyncio
async def test_the_ard_discoverer_runs_only_when_discovery_before_design_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_surface(_runtime: Any, meta: dict[str, Any]) -> list[dict[str, Any]]:
        calls.append(meta)
        return [{"identifier": "urn:x", "type": "mcp", "source": "own"}]

    monkeypatch.setattr(
        "probos.federation.ard.adoption.surface_discovery_candidates", fake_surface,
    )

    def runtime(flag: Any) -> SimpleNamespace:
        return SimpleNamespace(
            config=SimpleNamespace(
                federation=SimpleNamespace(ard=SimpleNamespace(discovery_before_design=flag))
            )
        )

    assert await capability_triage.ard_discoverer(runtime(False), "d")("gap") is None
    assert await capability_triage.ard_discoverer(runtime(MagicMock()), "d")("gap") is None
    assert await capability_triage.ard_discoverer(MagicMock(), "d")("gap") is None
    assert calls == []
    assert await capability_triage.ard_discoverer(runtime(True), "d")("gap") == [
        "urn:x [mcp] via own"
    ]
    assert calls == [{"name": "gap", "description": "d"}]


# ══ 5. pre_approved: the route's approval is the design approval ═══════════


@pytest.mark.parametrize("pre_approved", [False, True])
@pytest.mark.asyncio
async def test_fulfil_build_forwards_pre_approved_only_when_true(pre_approved: bool) -> None:
    pipe = _Pipeline()
    requests = SimpleNamespace(mark_fulfilled=AsyncMock(return_value=SimpleNamespace(status="fulfilled")))

    await fulfil_build(
        "req-1", store=requests, gap_target="t", rationale="r",
        self_mod_pipeline=pipe, pre_approved=pre_approved,
    )

    _args, kwargs = pipe.calls[0]
    assert ("pre_approved" in kwargs) is pre_approved
    assert kwargs.get("pre_approved", True) is True


def _real_pipeline(approval: Any) -> SelfModificationPipeline:
    designer = MagicMock()
    designer.design_agent = AsyncMock(return_value="class X: pass")
    designer._build_class_name = MagicMock(return_value="X")
    designer._build_agent_type = MagicMock(return_value="x")
    validator = MagicMock()
    validator.validate = MagicMock(return_value=[])
    sandbox = MagicMock()
    sandbox.test_agent = AsyncMock(
        return_value=SimpleNamespace(success=True, agent_class=object, execution_time_ms=1.0, error="")
    )
    return SelfModificationPipeline(
        designer=designer, validator=validator, sandbox=sandbox, monitor=MagicMock(),
        config=SimpleNamespace(
            max_designed_agents=5, require_user_approval=True,
            research_enabled=False, allowed_imports=[],
        ),
        register_fn=AsyncMock(), create_pool_fn=AsyncMock(), set_trust_fn=AsyncMock(),
        user_approval_fn=approval,
    )


@pytest.mark.asyncio
async def test_a_pre_approved_design_is_not_asked_again_but_any_other_still_is() -> None:
    approval = AsyncMock(return_value=False)
    pipe = _real_pipeline(approval)

    params = {"text": "the text to count"}
    declined = await pipe.handle_unhandled_intent("count_words", "count words", params)
    approved = await pipe.handle_unhandled_intent(
        "count_words", "count words", params, pre_approved=True,
    )

    assert declined is not None and declined.status == "rejected_by_user"
    assert approval.await_count == 1
    assert approved is not None and approved.status == "active"


@pytest.mark.parametrize(
    ("config", "decided_by", "consensus", "pre_approved"),
    [
        (SimpleNamespace(), "captain", True, False),
        (SimpleNamespace(), "architect_0", True, False),
        (_on(), "captain", True, True),
        (_on(), "captain", False, True),
        (_on(), "architect_0", False, True),
        (_on(), "architect_0", True, None),
        (_on(), "", False, None),
        (_on(), "  ", False, None),
    ],
)
@pytest.mark.asyncio
async def test_the_build_route_designs_only_what_the_recorded_approval_admits(
    monkeypatch: pytest.MonkeyPatch, config: Any, decided_by: str, consensus: bool,
    pre_approved: bool | None,
) -> None:
    """A-1 H2: under the ladder the design follows the approval on record, not the
    flag. The Captain's approval admits any build; a delegate's -- AD-1213 records
    the deciding agent's id -- admits only a build the policy lets a delegate
    decide, one that requires no consensus; an approval naming no decider admits
    none. ``None`` means nothing is designed. OFF, the route is HEAD's."""
    seen: list[dict[str, Any]] = []

    async def spy(_request_id: str, **kwargs: Any) -> None:
        seen.append(kwargs)
        return None

    monkeypatch.setattr(router_mod, "fulfil_build", spy)
    decided = SimpleNamespace(
        id="r1", kind="build", target="t", rationale="r", decided_by=decided_by,
        status="approved", payload={"requires_consensus": consensus},
    )
    # A-2: under the ladder the fulfiller re-reads the approval as committed.
    committed = SimpleNamespace(db_path="", get=AsyncMock(return_value=decided))

    await router_mod._fulfil_build_request(
        SimpleNamespace(config=config, self_mod_pipeline=_Pipeline()), committed, decided,
    )

    if pre_approved is None:
        assert seen == []
    else:
        [call] = seen
        assert call["pre_approved"] is pre_approved
        assert call["design_context"] == {"requires_consensus": consensus}


@pytest.mark.asyncio
async def test_a_delegated_approval_designs_a_ladder_build_only_where_the_policy_admits_it(
    rig: _Rig,
) -> None:
    """A-1 H2 through the real delegated-approval service, the real Captain route and
    a restarted real store. A First Officer's approval designs a build that requires
    no consensus (AD-1213 delegates exactly that); a build that requires consensus is
    refused to the First Officer and designed on the Captain's approval; and an
    approval recorded under a delegate's name any other way designs nothing."""
    await rig.delegate()
    filed: dict[str, Any] = {}
    for target, context in (
        ("weather_api", None),
        ("purge_api", {"requires_consensus": True}),
        ("scrub_api", {"requires_consensus": True}),
    ):
        filed[target] = await triage_and_file(
            gap_target=target, agent_id=BUILDER.id, store=rig.requests, rationale=f"{target} gap",
            tool_registry=rig.tools, permission_store=rig.perms, design_context=context,
            gap_class="tool", unified=True,
        )
    assert {request.kind for request in filed.values()} == {"build"}, "premise: unregistered tools build"
    await rig.requests.stop()
    rig.requests = CapabilityRequestStore(
        db_path=rig.requests.db_path, emit_event=rig.events, trust_network=rig.trust,
    )
    await rig.requests.start()
    pipe = _Pipeline()
    runtime = rig.captain_runtime()
    runtime.self_mod_pipeline = pipe
    runtime.config = SimpleNamespace(
        approval_inbox=rig.settings.config,
        capability_triage=CapabilityTriageConfig(unified_ladder_enabled=True),
    )
    service = rig.service(fulfil=functools.partial(router_mod.fulfil_on_approval, runtime))
    runtime.delegated_approvals = service
    rig.at(max(filed.values(), key=lambda request: request.created_at), _GRACE + 1)

    delegated = await service.decide(
        NUMBER_ONE.id, queue="capability", request_id=filed["weather_api"].id, approve=True,
        reason="A-1 test: a routine build under the Captain's delegation.",
    )
    refused = await service.decide(
        NUMBER_ONE.id, queue="capability", request_id=filed["purge_api"].id, approve=True,
        reason="A-1 test: a build that requires consensus.",
    )
    by_captain = await decide_capability_request(
        filed["purge_api"].id,
        CapabilityRequestDecideRequest(approve=True, reason="The Captain approves."),
        runtime=runtime,
    )
    store_refusal = await rig.requests.decide(
        filed["scrub_api"].id, True, reason="not through the policy", decided_by=NUMBER_ONE.id,
    )
    # A-2: the store refuses that on the committed row, so only a write that bypassed
    # the store can record it -- and the fulfiller still designs nothing on it.
    with contextlib.closing(sqlite3.connect(rig.requests.db_path)) as other:
        other.execute(
            "UPDATE capability_requests SET status = 'approved', decided_by = ? WHERE id = ?",
            (NUMBER_ONE.id, filed["scrub_api"].id),
        )
        other.commit()
    recorded = await rig.requests.get(filed["scrub_api"].id, durable=True)
    designed_anyway = await router_mod.fulfil_on_approval(runtime, rig.requests, recorded, approve=True)

    assert (delegated.refusal, delegated.fulfilled) == (None, True), "premise: the rig decides and designs"
    assert refused.refusal is Refusal.CAPTAIN_RESERVED
    assert by_captain["fulfilled"] is True
    assert store_refusal is None
    assert recorded is not None and (recorded.status, recorded.decided_by) == ("approved", NUMBER_ONE.id)
    assert designed_anyway is False
    designs = {args[0]: kwargs for args, kwargs in pipe.calls}
    assert sorted(designs) == ["purge_api", "weather_api"]
    assert (designs["weather_api"]["requires_consensus"], designs["weather_api"]["pre_approved"]) == (False, True)
    assert (designs["purge_api"]["requires_consensus"], designs["purge_api"]["pre_approved"]) == (True, True)
    final = {target: await rig.requests.get(request.id, durable=True) for target, request in filed.items()}
    assert {target: (request.status, request.decided_by) for target, request in final.items()} == {
        "weather_api": ("fulfilled", NUMBER_ONE.id),
        "purge_api": ("fulfilled", "captain"),
        "scrub_api": ("approved", NUMBER_ONE.id),
    }


@pytest.mark.asyncio
async def test_a_first_officer_cannot_decide_an_nl_gap_card(rig: _Rig) -> None:
    """A-1: the delegated service refuses every NL card, whatever its class, because
    its requester (``system``) holds no post. So no delegated verdict is ever taken on
    a card the consensus raise changes, and the raise needs only the store's lock."""
    await rig.delegate()
    runtime = SimpleNamespace(capability_request_store=rig.requests, config=_on(), self_mod_manager=None)
    weak = await nl_gap_triage.file_nl_gap(runtime, dict(_META, requires_consensus=False))
    assert weak is not None and _fo_refusal(weak) is None, "premise: its class alone is delegable"
    rig.at(weak, _GRACE + 1)

    outcome = await rig.service().decide(
        NUMBER_ONE.id, queue="capability", request_id=weak.id, approve=True,
        reason="A-1 test: an NL gap's card.",
    )

    assert outcome.refusal is Refusal.REQUESTER_UNRESOLVED
    current = await rig.requests.get(weak.id)
    assert current is not None and (current.status, current.decided_by) == ("pending", "")


# ══ 6. The NL adapter ══════════════════════════════════════════════════════


def _nl_runtime(requests: Any) -> SimpleNamespace:
    return SimpleNamespace(capability_request_store=requests, config=_on(), self_mod_manager=None)


@pytest.mark.asyncio
async def test_one_pending_nl_build_per_intent(store: CapabilityRequestStore) -> None:
    """A scheduled task hitting the same gap every run files one card, not one per run."""
    runtime = _nl_runtime(store)

    first = await nl_gap_triage.file_nl_gap(runtime, _META)
    second = await nl_gap_triage.file_nl_gap(runtime, dict(_META, description="other words"))

    assert first is not None and second is not None and first.id == second.id
    assert (first.kind, first.agent_id, first.status) == ("build", "system", "pending")
    assert first.payload["requires_consensus"] is True
    assert (first.triage["gap_class"], first.triage["selected"]) == ("intent", "build")
    assert len(await store.list_pending()) == 1


@pytest.mark.asyncio
async def test_file_nl_gap_degrades_to_none_without_a_store_or_an_intent_name(
    store: CapabilityRequestStore,
) -> None:
    assert await nl_gap_triage.file_nl_gap(SimpleNamespace(capability_request_store=None), _META) is None
    assert await nl_gap_triage.file_nl_gap(_nl_runtime(store), {"name": "  "}) is None
    assert await store.list_pending() == []


@pytest.mark.asyncio
async def test_file_nl_gap_logs_and_returns_none_when_filing_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken = SimpleNamespace(
        list_pending=AsyncMock(side_effect=RuntimeError("db gone")), gap_filing_lock=asyncio.Lock(),
    )

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.nl_gap_triage"):
        filed = await nl_gap_triage.file_nl_gap(SimpleNamespace(capability_request_store=broken), _META)

    assert broken.list_pending.await_count == 1, "premise: the failure is the lookup's"
    assert filed is None
    assert "failed" in caplog.text
    assert not broken.gap_filing_lock.locked()


@pytest.mark.asyncio
async def test_decide_nl_gap_records_a_captain_approval_under_the_route_guard(
    store: CapabilityRequestStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _nl_runtime(store)
    guarded: list[tuple[Any, str]] = []
    audited: list[tuple[Any, str, Any]] = []

    real_guard = nl_gap_triage.captain_decision_guard

    def guard(rt: Any, queue: str) -> Any:
        guarded.append((rt, queue))
        return real_guard(rt, queue)

    monkeypatch.setattr(nl_gap_triage, "captain_decision_guard", guard)
    monkeypatch.setattr(
        nl_gap_triage, "audit_captain_decision",
        lambda rt, queue, decided: audited.append((rt, queue, decided)),
    )
    filed = await nl_gap_triage.file_nl_gap(runtime, _META)

    approved = await nl_gap_triage.decide_nl_gap(runtime, filed, approve=True, reason="ok")

    assert approved is not None
    assert (approved.status, approved.decided_by, approved.decision_reason) == ("approved", "captain", "ok")
    assert nl_gap_triage.requires_consensus_of(approved) is True
    assert guarded == [(runtime, "capability")]
    assert audited == [(runtime, "capability", approved)]


@pytest.mark.asyncio
async def test_decide_nl_gap_denial_returns_none_and_records_it(store: CapabilityRequestStore) -> None:
    runtime = _nl_runtime(store)
    filed = await nl_gap_triage.file_nl_gap(runtime, _META)

    result = await nl_gap_triage.decide_nl_gap(runtime, filed, approve=False, reason="no")

    stored = await store.get(filed.id)
    assert result is None
    assert stored is not None and (stored.status, stored.decided_by) == ("denied", "captain")


@pytest.mark.asyncio
async def test_decide_nl_gap_returns_only_the_approval_it_committed(store: CapabilityRequestStore) -> None:
    """A-2: an approval taken elsewhere first designs on that surface's own path. Before
    A-2 this returned the inbox's approval, and the shell designed the agent a second
    time on it; now the attended surface records nothing and designs nothing."""
    runtime = _nl_runtime(store)
    approved_first = await nl_gap_triage.file_nl_gap(runtime, _META)
    await store.decide(approved_first.id, True, reason="inbox", decided_by="captain")
    denied_first = await nl_gap_triage.file_nl_gap(runtime, dict(_META, name="format_disk"))
    await store.decide(denied_first.id, False, reason="inbox no", decided_by="captain")
    assert _rows(store.db_path)[approved_first.id] == ("approved", "captain"), "premise"

    again = await nl_gap_triage.decide_nl_gap(runtime, approved_first, approve=True, reason="click")
    overruled = await nl_gap_triage.decide_nl_gap(runtime, denied_first, approve=True, reason="click")

    assert again is None
    assert overruled is None
    assert (await store.get(approved_first.id)).decision_reason == "inbox"
    assert (await store.get(denied_first.id)).status == "denied"


# ── A-1: joining an NL gap's card keeps the gap's governance ─────────────


def _fo_refusal(request: Any) -> Refusal | None:
    """AD-1213's verdict on the request's class for a First Officer (live delegation,
    grace spent). By class alone: the service also refuses an NL card outright, since
    its requester (``system``) holds no post."""
    return evaluate(
        request_class=classify_capability_request(request, tool_registry=None),
        route=DeciderRole.FIRST_OFFICER, own_requisition=False, chief_barred=False,
        delegation_live=True, delegation_id="delegation-1", captain_unavailable=True,
        grace_seconds=0, created_at=request.created_at, now=request.created_at,
    ).refusal


def _without_consensus(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "requires_consensus"}


def _stored_payload(db_path: str, request_id: str) -> Any:
    """The payload column as written, read on a connection of its own."""
    with contextlib.closing(sqlite3.connect(db_path)) as db:
        (raw,) = db.execute("SELECT payload FROM capability_requests WHERE id = ?", (request_id,)).fetchone()
    return json.loads(raw)


class _PausedWrites:
    """The store's writer connection, paused at its first statement that starts with ``prefix``."""

    def __init__(self, inner: Any, prefix: str) -> None:
        self.inner = inner
        self.prefix = prefix
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def execute(self, sql: str, *args: Any) -> Any:
        if sql.startswith(self.prefix) and not self.entered.is_set():
            self.entered.set()
            await self.release.wait()
        return await self.inner.execute(sql, *args)


@pytest.mark.asyncio
async def test_a_consensus_gap_raises_the_pending_nl_build_it_joins(store: CapabilityRequestStore) -> None:
    """A-1 H1, the reviewer's probe: one intent is sighted without a consensus
    requirement, then with one. Before A-1 the second sighting joined the weak card
    as it stood -- classified DESTRUCTIVE, a class the policy delegates -- and the
    Captain's approval designed the agent without the gate. Now the join raises the
    card durably, a restarted store keeps it Captain-reserved, and the approval
    designs it with the gate."""
    runtime = _nl_runtime(store)
    weak = await nl_gap_triage.file_nl_gap(runtime, dict(_META, requires_consensus=False))
    assert weak is not None and _fo_refusal(weak) is None, "premise: the weak card's class is delegable"

    joined = await nl_gap_triage.file_nl_gap(runtime, _META)

    assert joined is not None and joined.id == weak.id
    assert [request.id for request in await store.list_pending()] == [weak.id]
    reopened = await _reopen(store)
    pipe = _Pipeline()
    try:
        durable = await reopened.get(weak.id)
        assert durable is not None and durable.payload["requires_consensus"] is True
        assert _without_consensus(durable.payload) == _without_consensus(weak.payload)
        assert durable.triage == weak.triage
        assert classify_capability_request(durable, tool_registry=None) is RequestClass.CAPTAIN_RESERVED
        assert _fo_refusal(durable) is Refusal.CAPTAIN_RESERVED
        response = await decide_capability_request(
            weak.id, CapabilityRequestDecideRequest(approve=True, reason="ok"),
            runtime=SimpleNamespace(capability_request_store=reopened, config=_on(), self_mod_pipeline=pipe),
        )
    finally:
        await reopened.stop()

    [(_args, kwargs)] = pipe.calls
    assert (kwargs["requires_consensus"], kwargs["pre_approved"]) == (True, True)
    assert response["fulfilled"] is True


@pytest.mark.asyncio
async def test_a_gap_without_consensus_never_weakens_the_pending_build_it_joins(
    store: CapabilityRequestStore,
) -> None:
    """A-1 H1, the reverse order: the card requires consensus and a later sighting
    says it does not. The join returns the card as it stands -- governance joins
    upward only."""
    runtime = _nl_runtime(store)
    strong = await nl_gap_triage.file_nl_gap(runtime, _META)
    assert strong is not None and _fo_refusal(strong) is Refusal.CAPTAIN_RESERVED, "premise"

    joined = await nl_gap_triage.file_nl_gap(runtime, dict(_META, requires_consensus=False))

    assert joined is not None and joined.id == strong.id
    reopened = await _reopen(store)
    try:
        durable = await reopened.get(strong.id)
    finally:
        await reopened.stop()
    assert durable is not None and durable.payload == strong.payload
    assert _fo_refusal(durable) is Refusal.CAPTAIN_RESERVED


@pytest.mark.parametrize("when", ["before_the_lookup", "between_the_lookup_and_the_raise"])
@pytest.mark.asyncio
async def test_a_consensus_gap_whose_card_was_decided_first_is_filed_anew(
    store: CapabilityRequestStore, monkeypatch: pytest.MonkeyPatch, when: str,
) -> None:
    """A-1 H1: a decided request is never re-governed. The weak card approved first
    stays as approved; the consensus sighting gets a Captain-reserved card of its own."""
    runtime = _nl_runtime(store)
    weak = await nl_gap_triage.file_nl_gap(runtime, dict(_META, requires_consensus=False))
    if when == "before_the_lookup":
        await store.decide(weak.id, True, reason="inbox")
    else:
        real_raise = store.require_build_consensus

        async def decided_first(request_id: str) -> Any:
            await store.decide(request_id, True, reason="inbox")
            return await real_raise(request_id)

        monkeypatch.setattr(store, "require_build_consensus", decided_first)

    own = await nl_gap_triage.file_nl_gap(runtime, _META)

    kept = await store.get(weak.id)
    assert kept is not None and (kept.status, kept.payload["requires_consensus"]) == ("approved", False)
    assert own is not None and own.id != weak.id
    assert (own.status, own.payload["requires_consensus"]) == ("pending", True)
    assert _fo_refusal(own) is Refusal.CAPTAIN_RESERVED


@pytest.mark.parametrize("case", ["unknown", "not_a_build", "decided"])
@pytest.mark.asyncio
async def test_the_consensus_raise_touches_only_a_pending_build(case: str) -> None:
    """A-1: checked on the cache, so a store with no database pins the checks alone."""
    requests = CapabilityRequestStore()
    kind = "grant" if case == "not_a_build" else "build"
    filed = await requests.file_request(
        "system", kind, "wipe_disk", payload=None if kind == "grant" else dict(_DESIGN, requires_consensus=False),
    )
    if case == "decided":
        await requests.decide(filed.id, True, reason="inbox")
    before = await requests.get(filed.id)

    raised = await requests.require_build_consensus("no-such-request" if case == "unknown" else filed.id)

    assert raised is None
    assert await requests.get(filed.id) == before


@pytest.mark.asyncio
async def test_the_consensus_raise_is_monotone_and_keeps_the_design_context() -> None:
    requests = CapabilityRequestStore()
    weak = await requests.file_request("system", "build", "a", payload=dict(_DESIGN, requires_consensus=False))
    strong = await requests.file_request("system", "build", "b", payload=dict(_DESIGN))
    bare = await requests.file_request("system", "build", "c")

    raised = await requests.require_build_consensus(weak.id)
    unchanged = await requests.require_build_consensus(strong.id)
    from_nothing = await requests.require_build_consensus(bare.id)

    assert raised is not None and raised.payload == dict(_DESIGN) and raised.status == "pending"
    assert unchanged is strong
    assert from_nothing is not None and from_nothing.payload == {"requires_consensus": True}
    assert validate_build_payload(from_nothing.payload) == {"requires_consensus": True}
    assert [await requests.get(r.id) for r in (weak, strong, bare)] == [raised, strong, from_nothing]


@pytest.mark.asyncio
async def test_the_consensus_raise_refuses_a_payload_that_would_not_survive_a_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-1: a raise that grew the payload past its bound would load as ``None`` --
    no consensus requirement and no design context -- so it is refused instead."""
    requests = CapabilityRequestStore()
    base = {"intent_description": "wipe a disk", "parameters": {}}
    bound = len(capability_request_mod._canonical_json(base)) + 10
    monkeypatch.setattr(capability_request_mod, "_BUILD_PAYLOAD_MAX_CHARS", bound)
    assert validate_build_payload(base) == base, "premise: the stored payload is valid"
    assert validate_build_payload(dict(base, requires_consensus=True)) is None, "premise: the raised one is not"
    filed = await requests.file_request("system", "build", "wipe_disk", payload=dict(base))

    raised = await requests.require_build_consensus(filed.id)

    assert raised is None
    assert (await requests.get(filed.id)).payload == base


@pytest.mark.asyncio
async def test_the_consensus_raise_writes_only_a_row_that_is_still_pending(
    store: CapabilityRequestStore, caplog: pytest.LogCaptureFixture,
) -> None:
    """A-1: the raise is a compare-and-set on the row as well as the cache. A row
    another writer decided (here, a connection of the test's own) is never raised."""
    runtime = _nl_runtime(store)
    weak = await nl_gap_triage.file_nl_gap(runtime, dict(_META, requires_consensus=False))
    with contextlib.closing(sqlite3.connect(store.db_path)) as other:
        other.execute(
            "UPDATE capability_requests SET status = 'approved', decided_by = 'captain' WHERE id = ?",
            (weak.id,),
        )
        other.commit()
    assert (await store.get(weak.id)).status == "pending", "premise: the cache has not seen it"

    with caplog.at_level(logging.WARNING, logger="probos.capability_request"):
        raised = await store.require_build_consensus(weak.id)

    assert raised is None
    assert "not raised" in caplog.text
    assert (await store.get(weak.id)).payload["requires_consensus"] is False
    assert _stored_payload(store.db_path, weak.id)["requires_consensus"] is False


@pytest.mark.asyncio
async def test_a_decision_on_a_card_being_raised_waits_for_the_raise(store: CapabilityRequestStore) -> None:
    """A-1 H1: a decision and a raise on one pending build hold the store's lock. The
    raise is paused mid-write; a Captain decision arriving then waits, and is taken --
    and designed -- on the raised card. No delegated-approval service is wired, so the
    route's guard is a no-op and only the store's lock stands between them."""
    runtime = _nl_runtime(store)
    weak = await nl_gap_triage.file_nl_gap(runtime, dict(_META, requires_consensus=False))
    pipe = _Pipeline()
    route_runtime = SimpleNamespace(capability_request_store=store, config=_on(), self_mod_pipeline=pipe)
    paused = _PausedWrites(store._db, "UPDATE capability_requests SET payload")
    store._db = paused  # fault injection at the store's own writer connection
    raising = asyncio.create_task(nl_gap_triage.file_nl_gap(runtime, _META))
    deciding: asyncio.Task[Any] | None = None
    try:
        await asyncio.wait_for(paused.entered.wait(), 5)
        deciding = asyncio.create_task(decide_capability_request(
            weak.id, CapabilityRequestDecideRequest(approve=True, reason="ok"), runtime=route_runtime,
        ))
        finished, _ = await asyncio.wait({deciding}, timeout=0.3)
        assert not finished, "a decision was taken while the raise was mid-write"
        assert (await store.get(weak.id)).status == "pending", "a decision landed mid-raise"
        paused.release.set()
        joined = await asyncio.wait_for(raising, 5)
        response = await asyncio.wait_for(deciding, 5)
    finally:
        paused.release.set()
        await asyncio.gather(*(t for t in (raising, deciding) if t is not None), return_exceptions=True)
        store._db = paused.inner

    assert joined is not None and joined.id == weak.id
    [(_args, kwargs)] = pipe.calls
    assert kwargs["requires_consensus"] is True
    assert response["fulfilled"] is True
    assert _stored_payload(store.db_path, weak.id)["requires_consensus"] is True


@pytest.mark.asyncio
async def test_a_raise_on_a_card_being_decided_waits_and_files_its_own(tmp_path: Path) -> None:
    """A-1 H1, the other order: the decision is paused mid-write. A consensus sighting
    arriving then waits for it, finds the card decided -- so never re-governs it --
    and files a Captain-reserved card of its own. A-2: a ladder filing is decided on a
    connection of its own, so the pause is injected through the store's connection
    factory (the cross-store case is ``test_a_raise_waits_for_a_decision_held_mid_transaction``)."""
    factory = _PausingFactory("UPDATE capability_requests SET status")
    async with _store_at(str(tmp_path / "cap.db"), connection_factory=factory) as store:
        runtime = _nl_runtime(store)
        weak = await nl_gap_triage.file_nl_gap(runtime, dict(_META, requires_consensus=False))
        deciding = asyncio.create_task(store.decide(weak.id, True, reason="inbox"))
        raising: asyncio.Task[Any] | None = None
        try:
            await asyncio.wait_for(factory.entered.wait(), 5)
            raising = asyncio.create_task(nl_gap_triage.file_nl_gap(runtime, _META))
            finished, _ = await asyncio.wait({raising}, timeout=0.3)
            assert not finished, "the raise ran while the decision was mid-write"
            assert (await store.get(weak.id)).payload["requires_consensus"] is False, "raised mid-decision"
            factory.release.set()
            decided = await asyncio.wait_for(deciding, 5)
            own = await asyncio.wait_for(raising, 5)
        finally:
            factory.release.set()
            await asyncio.gather(*(t for t in (deciding, raising) if t is not None), return_exceptions=True)

        assert decided is not None and (decided.status, decided.payload["requires_consensus"]) == ("approved", False)
        assert own is not None and own.id != weak.id
        assert (own.status, own.payload["requires_consensus"]) == ("pending", True)
        assert _stored_payload(store.db_path, weak.id)["requires_consensus"] is False


@pytest.mark.asyncio
async def test_two_concurrent_filings_of_one_nl_gap_file_one_request(store: CapabilityRequestStore) -> None:
    """A-1 M1: the lookup and the filing hold the store's ``gap_filing_lock``. The
    control arm files the same way without it and gets two cards, so it is the lock,
    not the scheduling, that makes one."""
    runtime = _nl_runtime(store)

    async def unlocked(name: str) -> Any:
        if await nl_gap_triage.find_pending_nl_build(store, name) is not None:
            return None
        return await triage_and_file(
            gap_target=name, agent_id=nl_gap_triage.NL_GAP_REQUESTER, store=store,
            design_context={"requires_consensus": False}, gap_class="intent", unified=True,
        )

    control = await asyncio.gather(unlocked("format_disk"), unlocked("format_disk"))
    assert None not in control and len({request.id for request in control}) == 2, "premise: the race files two"

    weak, strong = await asyncio.gather(
        nl_gap_triage.file_nl_gap(runtime, dict(_META, requires_consensus=False)),
        nl_gap_triage.file_nl_gap(runtime, _META),
    )

    assert weak is not None and strong is not None and weak.id == strong.id
    [pending] = [request for request in await store.list_pending() if request.target == "wipe_disk"]
    assert pending.id == weak.id and pending.payload["requires_consensus"] is True


@pytest.mark.asyncio
async def test_the_hxi_click_approves_only_the_request_it_names_and_never_files_one(
    store: CapabilityRequestStore,
) -> None:
    """A-1: the click carries no consensus requirement, so a request it filed would
    record none. A-2: it approves the request its proposal names, by id, only while
    that request is pending and only with the design it records."""
    runtime = _nl_runtime(store)
    proposal = await nl_gap_triage.file_nl_gap(runtime, _META)
    assert proposal is not None, "premise"
    shown = nl_gap_triage.recorded_design(proposal)

    def click(request_id: str, rt: Any = runtime, **overrides: Any) -> Any:
        fields = {
            "intent_name": "wipe_disk", "description": shown["intent_description"],
            "parameters": shown["parameters"], "reason": "click", **overrides,
        }
        return nl_gap_triage.approve_nl_gap(rt, request_id, **fields)

    nothing = await click("  ")
    renamed = await click(proposal.id, intent_name="  ")
    unwired = await click(proposal.id, rt=SimpleNamespace())
    approved = await click(proposal.id)
    again = await click(proposal.id, reason="second click")

    assert (nothing.request, nothing.refusal) == (
        None, "the proposal names no build request; ask again to file one",
    )
    assert (renamed.request, renamed.refusal) == (None, "the request named is not this gap's build request")
    assert (unwired.request, unwired.refusal) == (None, "no capability-request store is wired")
    assert approved.request is not None and approved.request.id == proposal.id
    assert (approved.request.status, approved.request.decided_by) == ("approved", "captain")
    assert nl_gap_triage.requires_consensus_of(approved.request) is True
    assert (again.request, again.refusal) == (None, "the build request is already approved")
    assert _rows(store.db_path) == {proposal.id: ("approved", "captain")}


@pytest.mark.asyncio
async def test_the_unattended_result_is_a_pending_request_never_a_design(
    store: CapabilityRequestStore,
) -> None:
    result = await nl_gap_triage.pending_nl_gap_result(_nl_runtime(store), _META)
    failed = await nl_gap_triage.pending_nl_gap_result(
        SimpleNamespace(capability_request_store=None, self_mod_manager=None), _META,
    )

    [request] = await store.list_pending()
    assert result == {
        "status": "pending_approval", "intent": "wipe_disk", "capability_request_id": request.id,
    }
    assert (failed["status"], failed["intent"]) == ("failed", "wipe_disk")


def test_successful_execution_context_carries_only_a_successful_run() -> None:
    def manager(ok: bool) -> SimpleNamespace:
        return SimpleNamespace(
            was_last_execution_successful=lambda: ok,
            format_execution_context=lambda: "Prior user request: 'ls'",
        )

    assert nl_gap_triage.successful_execution_context(
        SimpleNamespace(self_mod_manager=manager(True))
    ) == "Prior user request: 'ls'"
    assert nl_gap_triage.successful_execution_context(SimpleNamespace(self_mod_manager=manager(False))) == ""
    assert nl_gap_triage.successful_execution_context(SimpleNamespace(self_mod_manager=None)) == ""


# ══ 7. Producers ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_ensure_dependency_files_its_package_ask_through_the_ladder_when_unified(
    store: CapabilityRequestStore,
) -> None:
    """AD-1220's producer, through the real ensure_dependency."""
    runtime = _dependency_runtime(store, _Resolver(["matplotlib"]))
    runtime.config.capability_triage = CapabilityTriageConfig(unified_ladder_enabled=True)

    result = await ProbOSRuntime.ensure_dependency(runtime, "matplotlib", requested_by="counselor_0")

    [request] = await store.list_pending()
    assert result.declined == ["matplotlib"]
    assert (request.kind, request.target, request.agent_id) == ("install", "matplotlib", "counselor_0")
    assert request.payload == {"install_kind": "python"}
    assert request.triage is not None and request.triage["gap_class"] == "package"


@pytest.mark.asyncio
async def test_package_asks_keep_their_dedup_and_head_shape(store: CapabilityRequestStore) -> None:
    first = await file_dependency_install_requests(store, ["feedparser"], "agent-1", unified=True)
    again = await file_dependency_install_requests(store, ["feedparser"], "agent-1", unified=True)
    off = await file_dependency_install_requests(store, ["numpy"], "agent-1")

    pending = {request.target: request for request in await store.list_pending()}
    assert (first, again, off) == (["feedparser"], [], ["numpy"])
    assert pending["feedparser"].triage is not None
    assert pending["numpy"].triage is None


@pytest.fixture
async def ladder_loop(tmp_path: Path) -> AsyncIterator[SimpleNamespace]:
    """AD-855 wired the way startup wires it -- real stores, a real bus, the route."""
    work_items = WorkItemStore(db_path=str(tmp_path / "wis.db"), tick_interval=1000)
    await work_items.start()
    perms = ToolPermissionStore(db_path=str(tmp_path / "perms.db"))
    await perms.start()
    bus = _EventBus()
    requests = CapabilityRequestStore(db_path=str(tmp_path / "cap.db"), emit_event=bus.emit)
    await requests.start()
    pipe = _Pipeline()
    runtime = _Runtime(
        work_item_router=_RecordingRouter(),
        work_item_store=work_items,
        capability_request_store=requests,
        tool_permission_store=perms,
        trust_network=MagicMock(),
        tool_registry=_ToolRegistry({}),
        self_mod_pipeline=pipe,
        mcp_server_store=None,
        config=_on(),
    )
    driver = CapabilityGapDriver(
        runtime=runtime, work_item_store=work_items, capability_request_store=requests,
    )
    bus.add_event_listener(driver.on_capability_event)
    loop = SimpleNamespace(
        runtime=runtime, driver=driver, bus=bus, work_items=work_items,
        requests=requests, perms=perms, pipe=pipe,
    )
    try:
        yield loop
    finally:
        await bus.drain()
        await loop.requests.stop()
        await perms.stop()
        await work_items.stop()


@pytest.mark.asyncio
async def test_crossing_a_work_item_gap_waits_for_the_captain_then_builds_and_resumes(
    ladder_loop: SimpleNamespace,
) -> None:
    """AD-855 under the ladder, end to end, across a restart of the request store:
    gap -> recorded pending build (nothing designed, item blocked) -> restart ->
    Captain approves on the route -> pre-approved design -> FULFILLED -> resumed."""
    loop = ladder_loop
    item = await loop.work_items.create_work_item(
        title="Forecast", description="Forecast", work_type="task",
        assigned_to="agent-1", created_by="captain",
    )
    await loop.work_items.transition_work_item(item.id, "in_progress", source="agent-1")

    request = await loop.driver.on_capability_gap(
        work_item_id=item.id, gap_target="weather_api", agent_id="agent-1",
    )
    await loop.bus.drain()

    assert request is not None and (request.kind, request.status) == ("build", "pending")
    assert request.triage is not None and request.triage["selected"] == "build"
    assert loop.pipe.calls == []
    assert (await loop.work_items.get_work_item(item.id)).status == "blocked"

    # Restart the request store and rewire it -- a fresh bus and driver -- the way
    # a reboot would, so nothing below can lean on the pre-restart cache.
    await loop.requests.stop()
    bus = _EventBus()
    loop.requests = CapabilityRequestStore(db_path=loop.requests.db_path, emit_event=bus.emit)
    await loop.requests.start()
    loop.runtime.capability_request_store = loop.requests
    driver = CapabilityGapDriver(
        runtime=loop.runtime, work_item_store=loop.work_items, capability_request_store=loop.requests,
    )
    bus.add_event_listener(driver.on_capability_event)
    reloaded = await loop.requests.get(request.id)
    assert reloaded is not None and reloaded.triage == request.triage

    response = await decide_capability_request(
        request.id, CapabilityRequestDecideRequest(approve=True, reason=""), runtime=loop.runtime,
    )
    await bus.drain()

    [(args, kwargs)] = loop.pipe.calls
    assert args[0] == "weather_api"
    assert kwargs["pre_approved"] is True
    assert response["fulfilled"] is True
    assert (await loop.requests.get(request.id)).status == "fulfilled"
    assert EventType.CAPABILITY_REQUEST_FULFILLED.value in bus.emitted
    assert (await loop.work_items.get_work_item(item.id)).status == "in_progress"
    assert len(loop.runtime.work_item_router.dispatched) == 1


@pytest.mark.asyncio
async def test_off_the_work_item_gap_driver_passes_triage_exactly_what_head_passed(
    ladder_loop: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []

    async def spy(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return SimpleNamespace(id="req-1")

    monkeypatch.setattr("probos.cognitive.capability_gap_driver.triage_and_file", spy)
    loop = ladder_loop
    loop.runtime.config = SimpleNamespace()

    await loop.driver.on_capability_gap(work_item_id="missing", gap_target="t", agent_id="agent-1")

    assert set(seen[0]) == {
        "gap_target", "agent_id", "store", "rationale", "work_item_id", "tool_registry",
        "permission_store", "mcp_server_store", "ontology", "trust_network",
        "self_mod_pipeline", "config",
    }


# ── The NL producers, through a real runtime ─────────────────────────────


def _gap_dag(text: str) -> Any:
    from probos.types import TaskDAG

    return TaskDAG(nodes=[], source_text=text, response="I don't have that capability yet.", capability_gap=True)


@pytest.fixture
async def booted(tmp_path: Path) -> AsyncIterator[Any]:
    from probos.cognitive.llm_client import MockLLMClient
    from probos.config import SelfModConfig

    config = SystemConfig(
        self_mod=SelfModConfig(enabled=True, require_user_approval=True),
        capability_triage=CapabilityTriageConfig(unified_ladder_enabled=True),
    )
    runtime = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await runtime.start()
    try:
        yield runtime
    finally:
        await runtime.stop()


def _arm_gap(runtime: Any, monkeypatch: pytest.MonkeyPatch, pipe: _Pipeline) -> None:
    monkeypatch.setattr(runtime.decomposer, "decompose", AsyncMock(side_effect=lambda text, **_kw: _gap_dag(text)))
    monkeypatch.setattr(runtime, "_extract_unhandled_intent", AsyncMock(return_value=dict(_META)))
    monkeypatch.setattr(runtime.self_mod_pipeline, "handle_unhandled_intent", pipe.handle_unhandled_intent)


@pytest.mark.asyncio
async def test_crossing_an_unattended_nl_gap_is_filed_then_designed_only_on_approval(
    booted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1 end to end: the auto-design branch files a pending build, designs nothing;
    after a restart of the request store the Captain approves it on the route and
    the design keeps the gap's consensus requirement (F1 + BF-744)."""
    pipe = _Pipeline()
    _arm_gap(booted, monkeypatch, pipe)

    result = await booted.process_natural_language("please wipe the spare disk")

    assert result["self_mod"]["status"] == "pending_approval"
    assert pipe.calls == []
    request_id = result["self_mod"]["capability_request_id"]
    old = booted.capability_request_store
    await old.stop()
    fresh = CapabilityRequestStore(db_path=old.db_path)
    booted.capability_request_store = fresh  # before start(), so teardown stops it either way
    await fresh.start()
    reloaded = await fresh.get(request_id)
    assert reloaded is not None and reloaded.payload["requires_consensus"] is True
    assert classify_capability_request(reloaded, tool_registry=None) is RequestClass.CAPTAIN_RESERVED

    response = await decide_capability_request(
        request_id, CapabilityRequestDecideRequest(approve=True, reason=""), runtime=booted,
    )

    [(args, kwargs)] = pipe.calls
    assert args[0] == "wipe_disk"
    assert (kwargs["requires_consensus"], kwargs["pre_approved"]) == (True, True)
    assert response["fulfilled"] is True


@pytest.mark.asyncio
async def test_off_the_unattended_nl_gap_designs_directly_as_at_head(
    booted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipe = _Pipeline(status="rejected")
    _arm_gap(booted, monkeypatch, pipe)
    booted.config.capability_triage.unified_ladder_enabled = False

    result = await booted.process_natural_language("please wipe the spare disk")

    [(_args, kwargs)] = pipe.calls
    assert kwargs["requires_consensus"] is True and "pre_approved" not in kwargs
    assert result["self_mod"]["status"] == "rejected"
    assert await booted.capability_request_store.list_pending() == []


@pytest.mark.asyncio
async def test_crossing_the_hxi_build_button_designs_with_the_recorded_consensus_gate(
    booted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F2 end to end: /api/chat proposes AND files; the click approves that request
    and designs with requires_consensus from the server record -- the client sends
    none -- then fulfils it."""
    from httpx import ASGITransport, AsyncClient

    from probos.api import create_app
    from probos.routers.chat import _run_selfmod

    pipe = _Pipeline()
    _arm_gap(booted, monkeypatch, pipe)
    monkeypatch.setattr(ProbOSRuntime, "llm_is_mock", property(lambda _self: False))
    monkeypatch.setattr(booted, "_system_qa", None)
    app = create_app(booted)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reply = await client.post("/api/chat", json={"message": "please wipe the spare disk"})

    proposal = reply.json()["self_mod_proposal"]
    request_id = proposal["capability_request_id"]
    pending = await booted.capability_request_store.get(request_id)
    assert pending is not None and pending.status == "pending"
    assert pending.payload["requires_consensus"] is True
    assert pipe.calls == []

    active = SimpleNamespace(
        status="active", agent_type="wipe_disk", intent_name="wipe_disk", class_name="WipeDiskAgent",
        strategy="new_agent", source_code="class WipeDiskAgent:\n    pass\n", agent_id="wipe-1",
    )
    pipe_active = AsyncMock(return_value=active)
    monkeypatch.setattr(booted.self_mod_pipeline, "handle_unhandled_intent", pipe_active)
    await _run_selfmod(
        SelfModRequest(
            intent_name=proposal["intent_name"],
            intent_description=proposal["intent_description"],
            parameters=proposal["parameters"],
            original_message="",
            capability_request_id=request_id,
        ),
        booted,
    )

    kwargs = pipe_active.await_args.kwargs
    assert kwargs["requires_consensus"] is True
    design = nl_gap_triage.recorded_design(pending)
    assert {key: kwargs[key] for key in design} == design
    done = await booted.capability_request_store.get(request_id)
    assert done is not None and (done.status, done.decided_by) == ("fulfilled", "captain")


@pytest.mark.parametrize("failure", ["no_store", "store_raises", "approved_elsewhere"])
@pytest.mark.asyncio
async def test_the_hxi_click_designs_nothing_when_its_request_cannot_be_recorded(
    booted: Any, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    """On the HXI path the recorded request is the only source of the gap's consensus
    requirement -- the client sends none -- so a click with no pending request to
    approve designs nothing rather than build without the consensus gate."""
    from probos.routers.chat import _run_selfmod

    pipe = _Pipeline()
    _arm_gap(booted, monkeypatch, pipe)
    events: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(booted, "emit_event", lambda kind, data: events.append((kind, data)))
    store = booted.capability_request_store
    card = await nl_gap_triage.file_nl_gap(booted, _META)
    assert card is not None, "premise"
    shown = nl_gap_triage.recorded_design(card)
    if failure == "no_store":
        monkeypatch.setattr(booted, "capability_request_store", None)
    elif failure == "store_raises":
        monkeypatch.setattr(store, "decide", AsyncMock(side_effect=RuntimeError("store unavailable")))
    else:
        # A-1: the inbox approved the gap's card first. Before A-1 the click then filed
        # a NEW request from its own metadata -- no consensus requirement -- approved
        # it, and designed the agent without the gate.
        await store.decide(card.id, True, reason="inbox")

    await _run_selfmod(
        SelfModRequest(
            intent_name="wipe_disk", intent_description=shown["intent_description"],
            parameters=shown["parameters"], original_message="", capability_request_id=card.id,
        ),
        booted,
    )

    assert pipe.calls == []
    failures = [data for kind, data in events if kind == EventType.SELF_MOD_FAILURE]
    assert [data.get("error") for data in failures] == ["capability request not recorded"]
    kept = await store.get(card.id)
    expected = ("approved", "inbox") if failure == "approved_elsewhere" else ("pending", "")
    assert kept is not None and (kept.status, kept.decision_reason) == expected
    assert _rows(store.db_path)[card.id] == (kept.status, "captain" if kept.decided_by else "")


@pytest.mark.parametrize(("answer", "expected"), [("y", "fulfilled"), ("n", "denied")])
@pytest.mark.asyncio
async def test_crossing_the_shell_prompt_decides_the_filed_request(
    booted: Any, monkeypatch: pytest.MonkeyPatch, answer: str, expected: str,
) -> None:
    """P4: the gap is filed before the prompt; the y/n is the Captain's decision on it."""
    from rich.console import Console

    from probos.cognitive.strategy import StrategyOption
    from probos.experience import renderer as renderer_mod

    pipe = _Pipeline()
    _arm_gap(booted, monkeypatch, pipe)
    single = StrategyOption(strategy="new_agent", label="Create WipeDiskAgent", reason="new", confidence=0.9)
    monkeypatch.setattr(
        renderer_mod, "StrategyRecommender",
        lambda **_kw: SimpleNamespace(propose=lambda **_k: SimpleNamespace(options=[single])),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": answer)
    filed: list[Any] = []
    real_file = nl_gap_triage.file_nl_gap

    async def recording_file(*args: Any, **kwargs: Any) -> Any:
        filed.append(await real_file(*args, **kwargs))
        return filed[-1]

    monkeypatch.setattr(nl_gap_triage, "file_nl_gap", recording_file)
    renderer = renderer_mod.ExecutionRenderer(
        Console(file=StringIO(), force_terminal=True, width=120), booted, debug=False,
    )

    await renderer.process_with_feedback("please wipe the spare disk")

    [before] = filed
    assert before is not None and before.status == "pending", "premise: filed before the prompt"
    request = await booted.capability_request_store.get(before.id)
    assert request is not None and (request.status, request.decided_by) == (expected, "captain")
    assert request.triage is not None and request.triage["gap_class"] == "intent"
    assert len(pipe.calls) == (1 if answer == "y" else 0)


def _one_option_shell(monkeypatch: pytest.MonkeyPatch, answer: str) -> Any:
    from probos.cognitive.strategy import StrategyOption
    from probos.experience import renderer as renderer_mod

    single = StrategyOption(strategy="new_agent", label="Create WipeDiskAgent", reason="new", confidence=0.9)
    monkeypatch.setattr(
        renderer_mod, "StrategyRecommender",
        lambda **_kw: SimpleNamespace(propose=lambda **_k: SimpleNamespace(options=[single])),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": answer)
    return renderer_mod


@pytest.mark.parametrize("failure", ["store_fails", "denied_elsewhere", "approved_elsewhere"])
@pytest.mark.asyncio
async def test_the_shell_designs_nothing_without_a_recorded_approval(
    booted: Any, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    """A-1: under the ladder a shell ``y`` designs only on the approval it recorded.
    Before A-1 it designed anyway -- with the request left pending when the store
    failed (R12), or denied when the inbox denied it while the prompt was open. A-2:
    nor on an approval the inbox took while the prompt was open, which designs on its
    own path; before A-2 the shell designed the agent a second time on it."""
    from rich.console import Console

    pipe = _Pipeline()
    _arm_gap(booted, monkeypatch, pipe)
    renderer_mod = _one_option_shell(monkeypatch, "y")
    store = booted.capability_request_store
    filed: list[Any] = []
    real_file = nl_gap_triage.file_nl_gap

    async def file_then_interfere(*args: Any, **kwargs: Any) -> Any:
        filed.append(await real_file(*args, **kwargs))
        if failure in ("denied_elsewhere", "approved_elsewhere"):
            await store.decide(filed[-1].id, failure == "approved_elsewhere", reason="decided in the inbox")
        else:
            monkeypatch.setattr(store, "decide", AsyncMock(side_effect=RuntimeError("store unavailable")))
        return filed[-1]

    monkeypatch.setattr(nl_gap_triage, "file_nl_gap", file_then_interfere)
    out = StringIO()
    renderer = renderer_mod.ExecutionRenderer(
        Console(file=out, force_terminal=True, width=120), booted, debug=False,
    )

    await renderer.process_with_feedback("please wipe the spare disk")

    [before] = filed
    assert before is not None, "premise: the gap was filed before the prompt"
    assert pipe.calls == []
    assert "Not designed" in out.getvalue()
    current = await store.get(before.id)
    expected = {"store_fails": "pending", "denied_elsewhere": "denied", "approved_elsewhere": "approved"}[failure]
    assert current is not None and current.status == expected


@pytest.mark.asyncio
async def test_the_shell_designs_with_the_stronger_of_its_sighting_and_the_card(
    booted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-1 H1 at the shell: the gap's card already requires consensus (an earlier
    sighting said so) and this sighting says it does not. The shell joins the card
    without weakening it, and designs -- then runs the new intent -- with the gate."""
    from rich.console import Console

    pipe = _Pipeline()
    _arm_gap(booted, monkeypatch, pipe)
    monkeypatch.setattr(
        booted, "_extract_unhandled_intent", AsyncMock(return_value=dict(_META, requires_consensus=False)),
    )
    earlier = await nl_gap_triage.file_nl_gap(booted, _META)
    assert earlier is not None and nl_gap_triage.requires_consensus_of(earlier), "premise"
    renderer_mod = _one_option_shell(monkeypatch, "y")
    executed: list[Any] = []
    real_execute = booted.dag_executor.execute

    async def recording_execute(dag: Any, **kwargs: Any) -> Any:
        executed.append(dag)
        return await real_execute(dag, **kwargs)

    monkeypatch.setattr(booted.dag_executor, "execute", recording_execute)
    renderer = renderer_mod.ExecutionRenderer(
        Console(file=StringIO(), force_terminal=True, width=120), booted, debug=False,
    )

    await renderer.process_with_feedback("please wipe the spare disk")

    [(_args, kwargs)] = pipe.calls
    assert kwargs["requires_consensus"] is True
    ran = [dag for dag in executed if dag.source_text == "please wipe the spare disk"]
    assert [[node.use_consensus for node in dag.nodes] for dag in ran] == [[True]]
    done = await booted.capability_request_store.get(earlier.id)
    assert done is not None and (done.status, done.decided_by) == ("fulfilled", "captain")


# ══ 8. A-2: a design follows the approval as committed ═════════════════════


def _rows(db_path: str) -> dict[str, tuple[str, str]]:
    """Every request's committed ``(status, decided_by)``, read on a connection of its own."""
    with contextlib.closing(sqlite3.connect(db_path)) as db:
        return {
            row[0]: (row[1], row[2])
            for row in db.execute("SELECT id, status, decided_by FROM capability_requests")
        }


@contextlib.asynccontextmanager
async def _store_at(db_path: str, **kwargs: Any) -> AsyncIterator[CapabilityRequestStore]:
    """A started store on ``db_path``; several may share one database, as two processes do."""
    requests = CapabilityRequestStore(db_path=db_path, **kwargs)
    try:
        await requests.start()
        yield requests
    finally:
        await requests.stop()


class _PausingFactory:
    """The default connection factory, whose connections pause -- or fail -- once, at
    the first statement that starts with ``prefix``. A-2 decides a ladder filing on a
    connection of its own, so this is how a test holds that decision mid-transaction."""

    def __init__(self, prefix: str, *, fail: bool = False) -> None:
        self.prefix = prefix
        self.fail = fail
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.opened = 0

    async def connect(self, db_path: str) -> Any:
        from probos.storage.sqlite_factory import default_factory

        self.opened += 1
        return _PausingConnection(await default_factory.connect(db_path), self)


class _PausingConnection:
    def __init__(self, inner: Any, factory: _PausingFactory) -> None:
        self.inner = inner
        self.factory = factory

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def execute(self, sql: str, *args: Any) -> Any:
        factory = self.factory
        if not sql.startswith(factory.prefix) or factory.entered.is_set():
            return self.inner.execute(sql, *args)

        async def paused() -> Any:
            factory.entered.set()
            if factory.fail:
                raise sqlite3.OperationalError("injected failure")
            await factory.release.wait()
            return await self.inner.execute(sql, *args)

        return paused()


class _ChatPipeline(_Pipeline):
    """``_Pipeline`` with the approval hooks ``_run_selfmod`` swaps."""

    _import_approval_fn = None
    _user_approval_fn = None


def _chat_runtime(
    requests: Any, pipe: Any, events: list[Any], *, config: Any = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        capability_request_store=requests, config=_on() if config is None else config,
        self_mod_pipeline=pipe, self_mod_manager=None, _last_execution=None,
        _knowledge_store=None, oracle=None, _oracle_service=None, _system_qa=None,
        delegated_approvals=None, emit_event=lambda kind, data: events.append((kind, data)),
    )


def _route_runtime(requests: Any, pipe: Any) -> SimpleNamespace:
    return SimpleNamespace(capability_request_store=requests, config=_on(), self_mod_pipeline=pipe)


_APPROVE = CapabilityRequestDecideRequest(approve=True, reason="The Captain approves.")


@pytest.mark.asyncio
async def test_a_stale_store_approving_on_the_route_designs_the_committed_consensus_gate(
    tmp_path: Path,
) -> None:
    """A-2 H3, the reviewer's probe: two stores share one database. B caches the gap's
    weak card, A raises it to require consensus, and the Captain approves on B. Before
    A-2, B decided and designed from its stale cache: ``requires_consensus`` False,
    ``pre_approved`` True. The decision is now taken on the committed row, the store
    publishes that row, and the design carries the gate."""
    db_path = str(tmp_path / "cap.db")
    pipe = _Pipeline()
    async with _store_at(db_path) as a:
        weak = await nl_gap_triage.file_nl_gap(_nl_runtime(a), dict(_META, requires_consensus=False))
        async with _store_at(db_path) as b:
            assert (await b.get(weak.id)).payload["requires_consensus"] is False, "premise: B caches it"
            raised = await a.require_build_consensus(weak.id)
            assert raised is not None and raised.payload["requires_consensus"] is True, "premise: A raised it"
            assert (await b.get(weak.id)).payload["requires_consensus"] is False, "premise: B is stale"

            response = await decide_capability_request(weak.id, _APPROVE, runtime=_route_runtime(b, pipe))

            published = await b.get(weak.id)
    [(_args, kwargs)] = pipe.calls
    assert (kwargs["requires_consensus"], kwargs["pre_approved"]) == (True, True)
    assert response["fulfilled"] is True
    assert published is not None and published.payload["requires_consensus"] is True
    assert _rows(db_path)[weak.id] == ("fulfilled", "captain")


@pytest.mark.parametrize("first", ["denied", "fulfilled"])
@pytest.mark.asyncio
async def test_a_stale_store_cannot_overturn_a_decision_another_store_committed(
    tmp_path: Path, first: str,
) -> None:
    """A-2 H3: A decides the card first; B, whose cache still says pending, is asked to
    approve it. Before A-2, B overwrote A's denial with an approval and designed it. Now
    B's store refuses on the committed row, its cache learns that row, and the route
    answers 400 as though it had read it first."""
    from fastapi import HTTPException

    db_path = str(tmp_path / "cap.db")
    pipe = _Pipeline()
    async with _store_at(db_path) as a:
        card = await nl_gap_triage.file_nl_gap(_nl_runtime(a), _META)
        async with _store_at(db_path) as b:
            if first == "denied":
                await a.decide(card.id, False, reason="denied in A")
            else:
                await decide_capability_request(card.id, _APPROVE, runtime=_route_runtime(a, _Pipeline()))
            assert _rows(db_path)[card.id] == (first, "captain"), "premise: A's decision is committed"
            assert (await b.get(card.id)).status == "pending", "premise: B is stale"

            with pytest.raises(HTTPException) as refused:
                await decide_capability_request(card.id, _APPROVE, runtime=_route_runtime(b, pipe))

            published = await b.get(card.id)
    assert (refused.value.status_code, refused.value.detail) == (
        400, f"capability request already decided (status={first})",
    )
    assert pipe.calls == []
    assert published is not None and published.status == first
    assert _rows(db_path)[card.id] == (first, "captain")


@pytest.mark.asyncio
async def test_the_store_refuses_a_delegate_on_a_build_whose_committed_row_requires_consensus(
    tmp_path: Path,
) -> None:
    """A-2 H3: the delegate's decision reached the store through a stale cache that
    still classed the card delegable. The store now reads the committed row, finds it
    Captain-reserved, records nothing, and its cache learns the raise."""
    db_path = str(tmp_path / "cap.db")
    async with _store_at(db_path) as a:
        weak = await nl_gap_triage.file_nl_gap(_nl_runtime(a), dict(_META, requires_consensus=False))
        async with _store_at(db_path) as b:
            await a.require_build_consensus(weak.id)
            stale = await b.get(weak.id)
            assert stale is not None and _fo_refusal(stale) is None, "premise: B's copy is delegable"

            refused = await b.decide(weak.id, True, reason="delegate", decided_by="architect_0")

            published = await b.get(weak.id)
    assert refused is None
    assert _rows(db_path)[weak.id] == ("pending", "")
    assert published is not None and published.payload["requires_consensus"] is True
    assert _fo_refusal(published) is Refusal.CAPTAIN_RESERVED


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"requires_consensus": False}, {"requires_consensus": True}, dict(_DESIGN)],
)
@pytest.mark.asyncio
async def test_the_store_refuses_a_delegate_exactly_where_the_policy_reserves_the_build(
    payload: Any,
) -> None:
    """A-2: the store's rule and AD-1213's classification are one predicate. A store
    with no database decides on its cache, and still applies it."""
    requests = CapabilityRequestStore()
    card = await requests.file_request(
        "system", "build", "wipe_disk", payload=payload,
        triage=evaluate_ladder(gap_class="intent").to_dict(),
    )
    reserved = classify_capability_request(card, tool_registry=None) is RequestClass.CAPTAIN_RESERVED

    by_delegate = await requests.decide(card.id, True, reason="delegate", decided_by="architect_0")

    assert (by_delegate is None) is reserved
    assert (await requests.get(card.id)).status == ("pending" if reserved else "approved")
    if reserved:
        by_captain = await requests.decide(card.id, True, reason="captain")
        assert by_captain is not None and by_captain.status == "approved"


@pytest.mark.asyncio
async def test_a_retry_through_a_stale_store_never_designs_a_build_another_store_fulfilled(
    tmp_path: Path,
) -> None:
    """A-2: B approves, its design fails, so the approval stands unfulfilled (BF-722).
    A retries and fulfils it. The Captain retries again on B, whose cache still says
    approved: the fulfiller reads the committed row -- fulfilled -- and designs nothing."""
    db_path = str(tmp_path / "cap.db")
    again = _Pipeline()
    async with _store_at(db_path) as b:
        card = await nl_gap_triage.file_nl_gap(_nl_runtime(b), _META)
        failing = _Pipeline(status="rejected")
        first = await decide_capability_request(card.id, _APPROVE, runtime=_route_runtime(b, failing))
        assert (first["fulfilled"], len(failing.calls)) == (False, 1), "premise: approved, unfulfilled"
        async with _store_at(db_path) as a:
            retried = await decide_capability_request(card.id, _APPROVE, runtime=_route_runtime(a, _Pipeline()))
        assert retried["fulfilled"] is True, "premise: A's retry fulfilled it"
        assert (await b.get(card.id)).status == "approved", "premise: B is stale"

        response = await decide_capability_request(card.id, _APPROVE, runtime=_route_runtime(b, again))

    assert again.calls == []
    assert response["fulfilled"] is False
    assert _rows(db_path)[card.id] == ("fulfilled", "captain")


@pytest.mark.parametrize(
    ("handed", "committed", "designs"),
    [
        ({"status": "approved", "consensus": False}, {"status": "approved", "consensus": True}, True),
        ({"status": "approved", "consensus": False}, {"status": "fulfilled", "consensus": False}, None),
        ({"status": "approved", "consensus": False}, None, None),
        (
            {"status": "approved", "consensus": False},
            {"status": "approved", "consensus": True, "decided_by": "architect_0"},
            None,
        ),
    ],
)
@pytest.mark.asyncio
async def test_the_build_route_designs_the_approval_as_committed_not_as_handed(
    monkeypatch: pytest.MonkeyPatch, handed: dict[str, Any], committed: dict[str, Any] | None,
    designs: bool | None,
) -> None:
    """A-2: under the ladder the fulfiller re-reads the approval as committed. ``None``
    means nothing is designed; otherwise the design carries the committed context."""
    seen: list[dict[str, Any]] = []

    async def spy(_request_id: str, **kwargs: Any) -> None:
        seen.append(kwargs)

    def request(fields: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(
            id="r1", kind="build", target="t", rationale="r", status=fields["status"],
            decided_by=fields.get("decided_by", "captain"),
            payload={"requires_consensus": fields["consensus"]},
        )

    monkeypatch.setattr(router_mod, "fulfil_build", spy)
    store = SimpleNamespace(
        db_path="", get=AsyncMock(return_value=None if committed is None else request(committed)),
    )

    await router_mod._fulfil_build_request(
        SimpleNamespace(config=_on(), self_mod_pipeline=_Pipeline()), store, request(handed),
    )

    assert store.get.await_args.args == ("r1",)
    if designs is None:
        assert seen == []
    else:
        [call] = seen
        assert call["design_context"] == {"requires_consensus": designs}


@pytest.mark.parametrize("raiser", ["this_store", "another_store"])
@pytest.mark.asyncio
async def test_a_raise_waits_for_a_decision_held_mid_transaction(tmp_path: Path, raiser: str) -> None:
    """A-2: the ladder decision is paused inside its transaction, after reading the
    committed row. A consensus sighting arriving then -- through this store, which its
    lock holds back, or through another store on the database, which only the
    transaction's write lock holds back -- waits, finds the card decided, so never
    re-governs it, and files a Captain-reserved card of its own."""
    factory = _PausingFactory("UPDATE capability_requests SET status")
    db_path = str(tmp_path / "cap.db")
    async with contextlib.AsyncExitStack() as stack:
        deciding = await stack.enter_async_context(_store_at(db_path, connection_factory=factory))
        weak = await nl_gap_triage.file_nl_gap(_nl_runtime(deciding), dict(_META, requires_consensus=False))
        raising = deciding
        if raiser == "another_store":
            raising = await stack.enter_async_context(_store_at(db_path))
        assert (await raising.get(weak.id)).status == "pending", "premise: the raiser sees it pending"
        decision = asyncio.create_task(deciding.decide(weak.id, True, reason="inbox"))
        raise_task: asyncio.Task[Any] | None = None
        try:
            await asyncio.wait_for(factory.entered.wait(), 5)
            raise_task = asyncio.create_task(nl_gap_triage.file_nl_gap(_nl_runtime(raising), _META))
            finished, _ = await asyncio.wait({raise_task}, timeout=0.3)
            assert not finished, "the raise ran while the decision was mid-transaction"
            assert _stored_payload(db_path, weak.id)["requires_consensus"] is False, "raised mid-decision"
            factory.release.set()
            decided = await asyncio.wait_for(decision, 5)
            own = await asyncio.wait_for(raise_task, 10)
        finally:
            factory.release.set()
            await asyncio.gather(*(t for t in (decision, raise_task) if t is not None), return_exceptions=True)

    assert decided is not None and (decided.status, decided.payload["requires_consensus"]) == ("approved", False)
    assert own is not None and own.id != weak.id
    assert (own.status, own.payload["requires_consensus"]) == ("pending", True)
    assert _stored_payload(db_path, weak.id)["requires_consensus"] is False
    assert _rows(db_path)[weak.id] == ("approved", "captain")


@pytest.mark.asyncio
async def test_a_ladder_decision_that_fails_mid_transaction_records_nothing(tmp_path: Path) -> None:
    """A-2: BF-722's contract on the committed path -- the failure propagates, the row
    and the cache stay pending, and the transaction is gone, so the next decision lands."""
    factory = _PausingFactory("UPDATE capability_requests SET status", fail=True)
    db_path = str(tmp_path / "cap.db")
    async with _store_at(db_path, connection_factory=factory) as requests:
        card = await nl_gap_triage.file_nl_gap(_nl_runtime(requests), _META)
        with pytest.raises(sqlite3.OperationalError, match="injected failure"):
            await requests.decide(card.id, True, reason="first")
        assert factory.entered.is_set(), "premise: the failure is the decision's own write"
        cached = await requests.get(card.id)
        committed = _rows(db_path)[card.id]

        decided = await asyncio.wait_for(requests.decide(card.id, True, reason="second"), 10)

    assert cached is not None and cached.status == "pending"
    assert committed == ("pending", "")
    assert decided is not None and (decided.status, decided.decision_reason) == ("approved", "second")


@pytest.mark.asyncio
async def test_off_a_request_filed_without_the_ladder_is_decided_as_at_head(tmp_path: Path) -> None:
    """OFF parity: a request filed without the ladder (no triage record) is decided on
    the store's own connection as at HEAD -- no connection of its own, no committed
    read, and a second decision overwrites the first."""
    counting = _PausingFactory("\x00 never")
    db_path = str(tmp_path / "cap.db")
    async with _store_at(db_path, connection_factory=counting) as requests:
        legacy = await requests.file_request("agent-1", "build", "wipe_disk", payload=dict(_DESIGN))
        assert legacy.triage is None and legacy.payload["requires_consensus"] is True, "premise"
        opened = counting.opened

        by_delegate = await requests.decide(legacy.id, True, reason="delegate", decided_by="architect_0")
        overwritten = await requests.decide(legacy.id, False, reason="again")

        assert counting.opened == opened, "a HEAD-shaped decision opened a connection of its own"
    assert by_delegate is not None and by_delegate.decided_by == "architect_0"
    assert overwritten is not None and overwritten.status == "denied"
    assert _rows(db_path)[legacy.id] == ("denied", "captain")


@pytest.mark.asyncio
async def test_the_grant_fast_path_grants_nothing_on_a_row_decided_first(
    store: CapabilityRequestStore, perms: ToolPermissionStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-2: the fast path's own decision is taken on the committed row. When another
    writer decided the grant first, that decision stands and no grant is issued."""
    await perms.issue_grant("peer-1", "reader", ToolPermission.READ, reason="peer", issued_by="captain")
    real_decide = store.decide
    calls: list[str] = []

    async def denied_first(request_id: str, *args: Any, **kwargs: Any) -> Any:
        calls.append(request_id)
        with contextlib.closing(sqlite3.connect(store.db_path)) as other:
            other.execute(
                "UPDATE capability_requests SET status = 'denied', decided_by = 'captain' WHERE id = ?",
                (request_id,),
            )
            other.commit()
        return await real_decide(request_id, *args, **kwargs)

    monkeypatch.setattr(store, "decide", denied_first)

    request = await triage_and_file(
        gap_target="reader", agent_id="agent-1", store=store,
        tool_registry=_ToolRegistry({"reader": _registration({"ensign": "read"})}),
        permission_store=perms,
        ontology=SimpleNamespace(get_agent_department=lambda _agent: "science"),
        trust_network=SimpleNamespace(get_score=lambda _agent: 0.99),
        config=CapabilityTriageConfig(grant_fast_path_enabled=True, grant_trust_floor=0.5),
        unified=True,
    )

    assert len(calls) == 1, "premise: the fast path decided"
    assert (request.kind, request.status, request.decided_by) == ("grant", "denied", "captain")
    assert not perms.get_active_grants_sync("agent-1", "reader")
    assert _rows(store.db_path)[request.id] == ("denied", "captain")


@pytest.mark.asyncio
async def test_every_surface_designs_the_one_derivation_of_the_record(store: CapabilityRequestStore) -> None:
    """A-2: the route's fulfiller, the HXI click and the shell design one derivation of
    the record, so what the Captain approves is what is designed, wherever he approves it."""
    card = await nl_gap_triage.file_nl_gap(_nl_runtime(store), _META, execution_context="Prior run: ls")
    pipe = _Pipeline()

    await fulfil_build(
        card.id, store=store, gap_target=card.target, rationale=card.rationale,
        self_mod_pipeline=pipe, design_context=card.payload,
    )

    design = nl_gap_triage.recorded_design(card)
    assert design == capability_triage.design_of(card.target, card.rationale, card.payload)
    assert design["execution_context"] == "Prior run: ls"
    [(args, kwargs)] = pipe.calls
    assert args == (design["intent_name"], design["intent_description"], design["parameters"])
    assert kwargs == {
        "requires_consensus": design["requires_consensus"],
        "execution_context": design["execution_context"],
    }


@pytest.mark.parametrize(
    "case",
    [
        "old_card", "other_gap", "agent_filed", "edited_description", "edited_parameters",
        "no_id", "unknown_id",
    ],
)
@pytest.mark.asyncio
async def test_an_hxi_click_approves_only_the_card_it_names_with_the_design_it_showed(
    store: CapabilityRequestStore, case: str,
) -> None:
    """A-2 H4: the click names its card by id and carries the design the card showed.
    Before A-2 it approved whichever card was pending for the intent's name and designed
    the client's own description, so an old proposal's click approved a newer card and
    designed the old task. Every mismatch approves nothing, designs nothing, files nothing."""
    from probos.routers.chat import _run_selfmod

    pipe, events = _ChatPipeline(), []
    runtime = _chat_runtime(store, pipe, events)
    card = await nl_gap_triage.file_nl_gap(runtime, _META)
    assert card is not None, "premise"
    shown = nl_gap_triage.recorded_design(card)
    click: dict[str, Any] = {
        "intent_name": "wipe_disk", "intent_description": shown["intent_description"],
        "parameters": shown["parameters"], "original_message": "", "capability_request_id": card.id,
    }
    if case == "old_card":
        await store.decide(card.id, False, reason="denied", decided_by="captain")
        newer = await nl_gap_triage.file_nl_gap(runtime, dict(_META, description="new task"))
        assert newer is not None and newer.id != card.id, "premise: a newer card for the gap"
    elif case == "other_gap":
        other = await nl_gap_triage.file_nl_gap(runtime, dict(_META, name="format_disk"))
        assert nl_gap_triage.recorded_design(other)["intent_description"] == shown["intent_description"]
        click["capability_request_id"] = other.id
    elif case == "agent_filed":
        other = await triage_and_file(
            gap_target="wipe_disk", agent_id="agent-1", store=store, rationale=card.rationale,
            design_context=dict(card.payload), gap_class="intent", unified=True,
        )
        assert nl_gap_triage.recorded_design(other) == shown, "premise: one design, another requester"
        click["capability_request_id"] = other.id
    elif case == "edited_description":
        click["intent_description"] = shown["intent_description"] + ", carefully"
    elif case == "edited_parameters":
        click["parameters"] = {"device": "the system disk"}
    elif case == "no_id":
        click["capability_request_id"] = ""
    else:
        click["capability_request_id"] = "no-such-request"
    before = _rows(store.db_path)

    await _run_selfmod(SelfModRequest(**click), runtime)

    assert pipe.calls == []
    failures = [data for kind, data in events if kind == EventType.SELF_MOD_FAILURE]
    assert [data["error"] for data in failures] == ["capability request not recorded"]
    assert _rows(store.db_path) == before


@pytest.mark.asyncio
async def test_an_hxi_click_designs_exactly_what_its_card_records_once(store: CapabilityRequestStore) -> None:
    """A-2 H4: the design comes from the approval as committed -- including the
    execution context recorded when the card was filed, which the click cannot see --
    and a second click on the same card approves nothing."""
    from probos.routers.chat import _run_selfmod

    pipe, events = _ChatPipeline(), []
    runtime = _chat_runtime(store, pipe, events)
    card = await nl_gap_triage.file_nl_gap(runtime, _META, execution_context="Prior run: ls")
    shown = nl_gap_triage.recorded_design(card)
    assert shown["execution_context"] == "Prior run: ls", "premise: a context the click does not carry"
    click = SelfModRequest(
        intent_name="wipe_disk", intent_description=shown["intent_description"],
        parameters=shown["parameters"], original_message="", capability_request_id=card.id,
    )

    await _run_selfmod(click, runtime)
    await _run_selfmod(click, runtime)

    [(args, kwargs)] = pipe.calls
    assert args == ()
    assert {key: kwargs[key] for key in shown} == shown
    assert kwargs["requires_consensus"] is True
    assert _rows(store.db_path)[card.id] == ("fulfilled", "captain")
    failures = [data["message"] for kind, data in events if kind == EventType.SELF_MOD_FAILURE]
    assert failures == ["Agent design not started: the build request is already fulfilled."]


@pytest.mark.asyncio
async def test_off_the_hxi_click_ignores_the_request_id_and_designs_as_at_head(
    store: CapabilityRequestStore,
) -> None:
    from probos.routers.chat import _run_selfmod

    pipe, events = _ChatPipeline(), []
    runtime = _chat_runtime(store, pipe, events, config=SimpleNamespace())

    await _run_selfmod(
        SelfModRequest(
            intent_name="wipe_disk", intent_description="as typed", parameters={"device": "sdb"},
            original_message="", capability_request_id="no-such-request",
        ),
        runtime,
    )

    [(args, kwargs)] = pipe.calls
    assert args == ()
    assert set(kwargs) == {"intent_name", "intent_description", "parameters", "execution_context", "on_progress"}
    assert (kwargs["intent_description"], kwargs["parameters"], kwargs["execution_context"]) == (
        "as typed", {"device": "sdb"}, "",
    )
    assert [kind for kind, _data in events if kind == EventType.SELF_MOD_FAILURE] == []
    assert _rows(store.db_path) == {}


def test_the_click_names_its_request_within_a_bound() -> None:
    """A-2: additive and bounded; a body without it parses as before."""
    from pydantic import ValidationError

    plain = SelfModRequest(intent_name="a", intent_description="b")
    assert plain.capability_request_id == ""
    assert SelfModRequest(intent_name="a", intent_description="b", capability_request_id="r" * 64)
    with pytest.raises(ValidationError):
        SelfModRequest(intent_name="a", intent_description="b", capability_request_id="r" * 65)


@pytest.mark.asyncio
async def test_a_stale_attended_surface_records_nothing_on_a_card_decided_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-2: the shell's and the click's decision, through a store whose cache predates
    another store's approval, is refused on the committed row: nothing is recorded or
    audited, and the surface designs nothing."""
    audited: list[Any] = []
    monkeypatch.setattr(nl_gap_triage, "audit_captain_decision", lambda *args: audited.append(args))
    db_path = str(tmp_path / "cap.db")
    async with _store_at(db_path) as a:
        card = await nl_gap_triage.file_nl_gap(_nl_runtime(a), _META)
        async with _store_at(db_path) as b:
            await a.decide(card.id, True, reason="inbox")
            assert (await b.get(card.id)).status == "pending", "premise: B is stale"

            result = await nl_gap_triage.decide_nl_gap(_nl_runtime(b), card, approve=True, reason="shell y")

            published = await b.get(card.id)
    assert result is None
    assert audited == []
    assert published is not None and (published.status, published.decision_reason) == ("approved", "inbox")


@pytest.mark.asyncio
async def test_crossing_an_hxi_proposal_that_joins_a_card_shows_and_designs_that_card(
    booted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-2 H4 end to end: the gap already has a card, recorded with other words. The
    chat's sighting joins it, so the proposal shows the card's design and names it,
    and the click designs exactly that -- not the sighting's words."""
    from httpx import ASGITransport, AsyncClient

    from probos.api import create_app
    from probos.routers.chat import _run_selfmod

    earlier = await nl_gap_triage.file_nl_gap(
        booted, dict(_META, description="recorded task", parameters={"device": "the spare disk"}),
    )
    assert earlier is not None, "premise"
    pipe = _Pipeline()
    _arm_gap(booted, monkeypatch, pipe)
    monkeypatch.setattr(ProbOSRuntime, "llm_is_mock", property(lambda _self: False))
    monkeypatch.setattr(booted, "_system_qa", None)
    app = create_app(booted)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reply = await client.post("/api/chat", json={"message": "please wipe the spare disk"})
    proposal = reply.json()["self_mod_proposal"]
    assert proposal["capability_request_id"] == earlier.id
    assert (proposal["intent_description"], proposal["parameters"]) == (
        "recorded task", {"device": "the spare disk"},
    )
    active = SimpleNamespace(
        status="active", agent_type="wipe_disk", intent_name="wipe_disk", class_name="WipeDiskAgent",
        strategy="new_agent", source_code="", agent_id="wipe-1",
    )
    pipe_active = AsyncMock(return_value=active)
    monkeypatch.setattr(booted.self_mod_pipeline, "handle_unhandled_intent", pipe_active)

    await _run_selfmod(
        SelfModRequest(
            intent_name=proposal["intent_name"], intent_description=proposal["intent_description"],
            parameters=proposal["parameters"], original_message="",
            capability_request_id=proposal["capability_request_id"],
        ),
        booted,
    )

    kwargs = pipe_active.await_args.kwargs
    assert (kwargs["intent_description"], kwargs["parameters"]) == ("recorded task", {"device": "the spare disk"})
    assert kwargs["requires_consensus"] is True
    done = await booted.capability_request_store.get(earlier.id)
    assert done is not None and (done.status, done.decided_by) == ("fulfilled", "captain")


@pytest.mark.asyncio
async def test_the_shell_shows_and_designs_the_card_its_sighting_joins(
    booted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-2 H4 at the shell: the sighting joins a card recorded with other words, and
    the prompt shows -- and ``y`` designs -- the card's design, not the sighting's."""
    import re

    from rich.console import Console

    earlier = await nl_gap_triage.file_nl_gap(
        booted, dict(_META, description="recorded task", parameters={"device": "the spare disk"}),
        execution_context="Prior run: ls",
    )
    assert earlier is not None, "premise"
    pipe = _Pipeline()
    _arm_gap(booted, monkeypatch, pipe)
    renderer_mod = _one_option_shell(monkeypatch, "y")
    out = StringIO()
    renderer = renderer_mod.ExecutionRenderer(
        Console(file=out, force_terminal=True, width=120), booted, debug=False,
    )

    await renderer.process_with_feedback("please wipe the spare disk")

    text = re.sub(r"\x1b\[[0-9;]*m", "", out.getvalue())
    assert "Purpose: recorded task" in text
    assert _META["description"] not in text
    [(_args, kwargs)] = pipe.calls
    design = nl_gap_triage.recorded_design(earlier)
    assert {key: kwargs[key] for key in design} == design
    done = await booted.capability_request_store.get(earlier.id)
    assert done is not None and (done.status, done.decided_by) == ("fulfilled", "captain")


# ══ 9. A-3: under the ladder the shell designs no skill ═══════════════════════════════════


class _SkillPipeline(_Pipeline):
    """Also records ``handle_add_skill``, which attaches a skill to an existing agent and
    carries no consensus requirement (its descriptor defaults to ``requires_consensus=False``)."""

    def __init__(self) -> None:
        super().__init__()
        self.skill_calls: list[dict[str, Any]] = []

    async def handle_add_skill(self, **kwargs: Any) -> Any:
        self.skill_calls.append(kwargs)
        return SimpleNamespace(
            status="active", agent_type="skill_agent", intent_name=kwargs.get("intent_name", ""),
            class_name="SkillAgent", strategy="add_skill", source_code="", error="",
        )


def _skill_first_shell(monkeypatch: pytest.MonkeyPatch, proposed: list[list[str]]) -> Any:
    """The recommender proposes a skill first and a new agent second, as it does for an
    intent that overlaps an existing agent's; ``proposed`` records each proposal as the
    recommender returned it, before the shell filters it."""
    from probos.cognitive.strategy import StrategyOption
    from probos.experience import renderer as renderer_mod

    def recommender(**_kw: Any) -> Any:
        def propose(**_kwargs: Any) -> Any:
            options = [
                StrategyOption(
                    strategy="add_skill", label="Add skill to existing agent", reason="overlap",
                    confidence=0.9, target_agent_type="skill_agent", is_recommended=True,
                ),
                StrategyOption(strategy="new_agent", label="Create WipeDiskAgent", reason="new", confidence=0.6),
            ]
            proposed.append([option.strategy for option in options])
            return SimpleNamespace(options=options)

        return SimpleNamespace(propose=propose)

    monkeypatch.setattr(renderer_mod, "StrategyRecommender", recommender)
    return renderer_mod


def _skill_runtime(
    booted: Any, monkeypatch: pytest.MonkeyPatch, *, requires_consensus: bool = True,
) -> _SkillPipeline:
    """Arm the gap with a sighting whose consensus requirement is ``requires_consensus``."""
    pipe = _SkillPipeline()
    _arm_gap(booted, monkeypatch, pipe)
    monkeypatch.setattr(booted.self_mod_pipeline, "handle_add_skill", pipe.handle_add_skill)
    monkeypatch.setattr(
        booted, "_extract_unhandled_intent",
        AsyncMock(return_value=dict(_META, requires_consensus=requires_consensus)),
    )
    return pipe


def _captain_takes_the_skill(prompt: str = "") -> str:
    """The Captain takes the skill whenever the prompt offers one -- it is the first option
    of the menu -- and otherwise approves the one option offered."""
    return "1" if "Choose strategy" in prompt else "y"


def _recording(filed: list[Any], real_file: Any) -> Any:
    """``real_file``, recording each request it files or joins in ``filed``."""

    async def recording(*args: Any, **kwargs: Any) -> Any:
        filed.append(await real_file(*args, **kwargs))
        return filed[-1]

    return recording


@pytest.mark.parametrize("requires_consensus", [True, False])
@pytest.mark.asyncio
async def test_under_the_ladder_the_shell_offers_no_skill(
    booted: Any, monkeypatch: pytest.MonkeyPatch, requires_consensus: bool,
) -> None:
    """Round-3 review (High): choosing ``add_skill`` for a card that requires consensus
    attached a skill -- which carries no consensus requirement -- and marked the build
    fulfilled. Under the ladder the shell offers no skill for any card, since no other
    surface fulfils a build request with one: the new agent is the one option, and the
    Captain's "y" designs it with the requirement the card records."""
    from rich.console import Console

    pipe = _skill_runtime(booted, monkeypatch, requires_consensus=requires_consensus)
    proposed: list[list[str]] = []
    renderer_mod = _skill_first_shell(monkeypatch, proposed)
    monkeypatch.setattr("builtins.input", _captain_takes_the_skill)
    filed: list[Any] = []
    monkeypatch.setattr(nl_gap_triage, "file_nl_gap", _recording(filed, nl_gap_triage.file_nl_gap))
    out = StringIO()
    renderer = renderer_mod.ExecutionRenderer(
        Console(file=out, force_terminal=True, width=120), booted, debug=False,
    )

    await renderer.process_with_feedback("please wipe the spare disk")

    shown = out.getvalue()
    assert proposed == [["add_skill", "new_agent"]], "premise: the recommender proposed a skill"
    [card] = filed
    assert card is not None, "premise: the gap was filed"
    assert nl_gap_triage.requires_consensus_of(card) is requires_consensus, "premise: the card's requirement"
    assert "Add skill to existing agent" not in shown and "Create WipeDiskAgent" in shown
    assert "A skill is not offered" in shown
    assert pipe.skill_calls == []
    [(_args, kwargs)] = pipe.calls
    assert kwargs["requires_consensus"] is requires_consensus
    done = await booted.capability_request_store.get(card.id)
    assert done is not None and (done.status, done.decided_by) == ("fulfilled", "captain")


@pytest.mark.asyncio
async def test_the_shell_designs_the_gate_a_sighting_adds_while_its_prompt_is_open(
    booted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This sighting needs no consensus; while the prompt is open another sighting of the gap
    requires it and raises the pending card (A-1's monotone join). The Captain's "y" approves
    the raised card, and the new agent is designed with the consensus requirement the
    committed approval records, not this sighting's weaker one (A-2); no skill is offered."""
    from rich.console import Console

    pipe = _skill_runtime(booted, monkeypatch, requires_consensus=False)
    proposed: list[list[str]] = []
    renderer_mod = _skill_first_shell(monkeypatch, proposed)
    real_file = nl_gap_triage.file_nl_gap
    filed: list[Any] = []
    raised: list[Any] = []
    loop = asyncio.get_running_loop()

    def raise_then_answer(prompt: str = "") -> str:
        # The shell reads its answer on an executor thread, so the event loop is free to
        # run the other sighting's filing -- which joins, and raises, the pending card.
        raised.append(asyncio.run_coroutine_threadsafe(real_file(booted, dict(_META)), loop).result(timeout=30))
        return _captain_takes_the_skill(prompt)

    monkeypatch.setattr(nl_gap_triage, "file_nl_gap", _recording(filed, real_file))
    monkeypatch.setattr("builtins.input", raise_then_answer)
    out = StringIO()
    renderer = renderer_mod.ExecutionRenderer(
        Console(file=out, force_terminal=True, width=120), booted, debug=False,
    )

    await renderer.process_with_feedback("please wipe the spare disk")

    shown = out.getvalue()
    [card] = filed
    assert card is not None and not nl_gap_triage.requires_consensus_of(card), (
        "premise: the card required no consensus when the prompt was built"
    )
    assert [request.id for request in raised] == [card.id], "premise: the other sighting raised this card"
    assert "Add skill to existing agent" not in shown
    assert pipe.skill_calls == []
    [(_args, kwargs)] = pipe.calls
    assert kwargs["requires_consensus"] is True
    done = await booted.capability_request_store.get(card.id)
    assert done is not None and (done.status, done.decided_by) == ("fulfilled", "captain")
    assert nl_gap_triage.requires_consensus_of(done) is True


@pytest.mark.asyncio
async def test_a_sighting_after_the_decision_files_a_new_card_and_no_skill_is_attached(
    booted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round-4 review (High): the Captain approved a card that required no consensus, and a
    sighting that requires it arrived before the design. A decided card is not raised, so
    that sighting files a new card (R13) -- and the shell, which had offered the skill for
    the weaker card, attached it and fulfilled that card. Now no skill is offered: the
    weaker approval designs the new agent it records, and approving the new card designs
    the intent again, with the consensus requirement."""
    from rich.console import Console

    pipe = _skill_runtime(booted, monkeypatch, requires_consensus=False)
    proposed: list[list[str]] = []
    renderer_mod = _skill_first_shell(monkeypatch, proposed)
    monkeypatch.setattr("builtins.input", _captain_takes_the_skill)
    store = booted.capability_request_store
    real_file = nl_gap_triage.file_nl_gap
    real_decide = nl_gap_triage.decide_nl_gap
    filed: list[Any] = []
    later: list[Any] = []

    async def decide_then_a_stronger_sighting(*args: Any, **kwargs: Any) -> Any:
        decided = await real_decide(*args, **kwargs)
        if kwargs.get("approve"):
            later.append(await real_file(booted, dict(_META)))
        return decided

    monkeypatch.setattr(nl_gap_triage, "file_nl_gap", _recording(filed, real_file))
    monkeypatch.setattr(nl_gap_triage, "decide_nl_gap", decide_then_a_stronger_sighting)
    out = StringIO()
    renderer = renderer_mod.ExecutionRenderer(
        Console(file=out, force_terminal=True, width=120), booted, debug=False,
    )

    await renderer.process_with_feedback("please wipe the spare disk")

    shown = out.getvalue()
    [weaker] = filed
    [stronger] = later
    assert weaker is not None and not nl_gap_triage.requires_consensus_of(weaker), (
        "premise: the approved card required no consensus"
    )
    assert stronger is not None and stronger.id != weaker.id, (
        "premise: the decided card was not raised; the stronger sighting filed a new one"
    )
    assert nl_gap_triage.requires_consensus_of(stronger) is True
    assert "Add skill to existing agent" not in shown
    assert pipe.skill_calls == []
    [(_args, kwargs)] = pipe.calls
    assert kwargs["requires_consensus"] is False
    done = await store.get(weaker.id)
    assert done is not None and (done.status, done.decided_by) == ("fulfilled", "captain")
    pending = await store.get(stronger.id)
    assert pending is not None and pending.status == "pending"

    # R13: approving the new card designs the intent again, with the consensus requirement.
    response = await decide_capability_request(
        stronger.id, CapabilityRequestDecideRequest(approve=True, reason=""), runtime=booted,
    )
    assert response["fulfilled"] is True
    assert pipe.skill_calls == []
    [_first, (args, kwargs)] = pipe.calls
    assert args[0] == "wipe_disk"
    assert (kwargs["requires_consensus"], kwargs["pre_approved"]) == (True, True)


@pytest.mark.asyncio
async def test_with_the_ladder_off_the_shell_still_offers_and_designs_a_skill(
    booted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OFF parity for A-3: without the ladder nothing is filed or withdrawn, and "1" attaches
    the skill as at HEAD. (That HEAD skill carries no consensus requirement is residual R11;
    A-3 changes only the ladder's path.)"""
    from rich.console import Console

    monkeypatch.setattr(booted.config.capability_triage, "unified_ladder_enabled", False)
    pipe = _skill_runtime(booted, monkeypatch)
    proposed: list[list[str]] = []
    renderer_mod = _skill_first_shell(monkeypatch, proposed)
    monkeypatch.setattr("builtins.input", _captain_takes_the_skill)
    out = StringIO()
    renderer = renderer_mod.ExecutionRenderer(
        Console(file=out, force_terminal=True, width=120), booted, debug=False,
    )

    await renderer.process_with_feedback("please wipe the spare disk")

    shown = out.getvalue()
    assert proposed == [["add_skill", "new_agent"]]
    assert "Add skill to existing agent" in shown and "A skill is not offered" not in shown
    assert [call["intent_name"] for call in pipe.skill_calls] == ["wipe_disk"]
    assert pipe.calls == []
    assert await booted.capability_request_store.list_pending() == []


@pytest.mark.asyncio
async def test_approving_the_stronger_card_routes_the_intent_to_consensus_through_the_real_pipeline(
    booted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round-5 review: R13's second design was shown only by a recording pipeline. Through the
    real self-mod pipeline and the runtime's registration -- only the LLM designer, validator
    and sandbox are stubbed -- the weaker approval's design serves the intent without a
    consensus requirement; approving the stronger card designs the intent again, that design
    becomes the intent's registered template, and from then on the decomposer routes the
    intent to consensus. Consensus for a designed agent is the declared default,
    ``execute_then_vote`` -- the agents act, then vote, as at HEAD -- and the pipeline reuses
    the designed pool, so the first design's instances keep serving: residual R13."""
    from probos.cognitive.cognitive_agent import CognitiveAgent
    from probos.types import IntentDescriptor

    def designed(consensus: bool) -> type:
        class WipeDiskAgent(CognitiveAgent):
            agent_type = "wipe_disk"
            _handled_intents = {"wipe_disk"}
            instructions = "You wipe the disk the Captain names."
            intent_descriptors = [
                IntentDescriptor(
                    name="wipe_disk", params={"device": "which disk"}, description="wipe a disk",
                    requires_consensus=consensus, requires_reflect=True, tier="domain",
                )
            ]

            async def act(self, decision: dict) -> dict:
                return {"success": True, "result": "wiped"}

        return WipeDiskAgent

    pipe = booted.self_mod_pipeline
    designed_with: list[bool] = []

    async def design_agent(**kwargs: Any) -> str:
        designed_with.append(kwargs["requires_consensus"])
        return "# designed"

    async def test_agent(_source: str, _intent: str, test_params: Any = None) -> Any:
        return SimpleNamespace(
            success=True, agent_class=designed(designed_with[-1]), execution_time_ms=1.0, error="",
        )

    monkeypatch.setattr(pipe, "_designer", SimpleNamespace(
        design_agent=design_agent, _build_class_name=lambda _name: "WipeDiskAgent",
        _build_agent_type=lambda name: name,
    ))
    monkeypatch.setattr(pipe, "_validator", SimpleNamespace(validate=lambda *_args, **_kwargs: []))
    monkeypatch.setattr(pipe, "_sandbox", SimpleNamespace(test_agent=test_agent))
    monkeypatch.setattr(pipe, "_dependency_resolver", None, raising=False)
    store = booted.capability_request_store

    weaker = await nl_gap_triage.file_nl_gap(booted, dict(_META, requires_consensus=False))
    assert weaker is not None, "premise: the weaker sighting filed a card"
    approved = await nl_gap_triage.decide_nl_gap(booted, weaker, approve=True, reason="Captain approved")
    assert approved is not None, "premise: the Captain approved the weaker card"
    stronger = await nl_gap_triage.file_nl_gap(booted, dict(_META))
    assert stronger is not None and stronger.id != weaker.id, (
        "premise: a decided card is not raised; the stronger sighting filed a new one"
    )
    assert nl_gap_triage.requires_consensus_of(stronger) is True

    first = await decide_capability_request(
        weaker.id, CapabilityRequestDecideRequest(approve=True, reason=""), runtime=booted,
    )
    assert first["fulfilled"] is True and designed_with == [False]
    assert booted.decomposer._consensus_for("wipe_disk", False) is False, (
        "premise: the weaker design serves the intent without a consensus requirement"
    )
    assert "designed_wipe_disk" not in booted._find_consensus_pools()

    second = await decide_capability_request(
        stronger.id, CapabilityRequestDecideRequest(approve=True, reason=""), runtime=booted,
    )

    assert second["fulfilled"] is True and designed_with == [False, True]
    [descriptor] = [d for d in booted._collect_intent_descriptors() if d.name == "wipe_disk"]
    assert descriptor.requires_consensus is True
    assert booted.decomposer._consensus_for("wipe_disk", False) is True
    assert "designed_wipe_disk" in booted._find_consensus_pools()
    assert booted.consensus_mode_for("wipe_disk") == "execute_then_vote"
    done = await store.get(stronger.id)
    assert done is not None and done.status == "fulfilled"
