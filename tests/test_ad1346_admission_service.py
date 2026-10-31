"""AD-1346 M3a (epic #1601, #1604): the shadow admission decision, over real registries and a real stop record.

``probos.admission`` decides once per unit of work and blocks nothing: ``decide`` resolves the principal through the
``IdentityService`` facade and runs two checks in ``CHECK_ORDER`` (the principal, then the Captain's stop), and
``shadow`` counts each verdict in memory and returns None. These tests drive it over a real ``AgentIdentityRegistry``,
a real ``CallsignRegistry`` and a real ``AgentStopService``, all under ``tmp_path``, and pin its structure:

- T1  the vocabularies: the seams are the stop's ``SEAMS`` plus the effect seams, the stop's reason code is imported,
      every reason code fits the AD-1316 stable-code syntax.
- T2  ``CHECK_ORDER`` and ``DEFERRED_CHECKS``, and ``decide`` calls the checks in that order.
- T3  ``WorkRequest``: exact ``str`` fields from closed sets; frozen.
- T4  ``AdmissionVerdict`` v1: ``VERDICT_KEYS``, the field order, ``to_dict`` embedding ``IdentityRef.to_dict()``, the
      JSON round trip and the record's own checks.
- T5  a certificate principal is admitted and keyed on its slot in each form the facade resolves.
- T6  an asset principal is admitted as an asset.
- T7  an unresolved principal is a would-refuse ``identity_unresolved`` keyed on the presented id.
- T8  the system-principal allowlist, for an id the facade does not resolve; a ``system:`` id it resolves is that slot's.
- T9  a Captain's stop: ``agent_stopped`` with the order's id, read without counting a refusal, and a cause that carries
      no part of the Captain's reason.
- T10 the constructor and ``decide`` refuse the wrong types.
- T11 ``shadow`` returns None and counts each verdict and its latency bucket.
- T12 ``shadow`` counts and logs a malformed request and a raising facade and returns None; ``decide`` propagates.
- T13 the service's inputs: no configuration field and no dependency beyond the facade, the stop record, an
      optional recorder (AD-1346 M3b), an optional ticket registry (AD-1346 M3d2) and an optional event loop (AD-1346
      M3d3a).
- T14 the decision files await nothing and, among them, only ``shadow``, ``hold`` and ``_check_ticket`` log; every file
      of the package imports only its allowlist (AD-1346 M3b's persistence files have allowlists of their own and may
      await).
- T15 the seam census: the package calls none of the stop's guard functions and starts no agent work.
- T16 outside the package the service is named only by ``runtime.py``, ``startup/shutdown.py``, ``startup/finalize.py``
      (which hands it to the Ward Room router and the crew session finalizer) and twelve shadowed-site files, which read
      it from a runtime or take it in a constructor; the package is imported only by ``runtime.py``, the fourteen
      shadowed-site files and, from AD-1346 M3d3a, the model gateway's module ``cognitive/llm_client.py``; the only
      routers that do either are the three whose routes AD-1346 M3c2 shadows, and none of them serves a route #1604
      property 11 keeps ungated.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

import probos
import probos.admission as admission_package
from probos import agent_stop
from probos.admission import VERDICT_KEYS, AdmissionService, AdmissionVerdict, WorkRequest, taxonomy
from probos.agent_stop import AgentStopService
from probos.config import SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.execution import authority
from probos.identity import AgentBirthCertificate, AgentIdentityRegistry
from probos.identity_service import IDENTITY_REF_KEYS, IdentityRef, IdentityService
from probos.substrate.registry import AgentRegistry
from tests.fixtures.ad1343_seam_census import GUARD_CALLEES, calls, census, first_line, function, is_agent_work_call

INSTANCE_ID = "ad1346-m3a-ship"
VESSEL_NAME = "Ad1346m3a"
SURGEON_SLOT = "surgeon_medical_surgeon_0_b2321292"
COUNSELOR_SLOT = "counselor_counselor_0_67c601cb"
TOOL_SLOT = "calculator_calculator_0_5f3a9c1e"
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
CANARY = "CANARY-ad1346-m3a: the Captain's private reason"

_SRC = Path(probos.__file__).resolve().parent
_PACKAGE = _SRC / "admission"
_ALLOWED_IMPORTS: dict[str, set[str]] = {
    "__init__.py": {"probos.admission.record", "probos.admission.service"},
    "taxonomy.py": {"__future__", "typing", "probos.agent_stop"},
    "record.py": {"__future__", "dataclasses", "typing", "probos.admission.taxonomy", "probos.identity_service"},
    "checks.py": {
        "__future__", "dataclasses", "typing", "probos.admission.taxonomy", "probos.agent_stop", "probos.identity_service",
    },
    "service.py": {
        "__future__", "asyncio", "collections.abc", "logging", "time", "typing", "probos.admission.carrier", "probos.admission.checks",
        "probos.admission.record", "probos.admission.recorder", "probos.admission.taxonomy", "probos.admission.tickets",
        "probos.agent_stop", "probos.identity_service",
    },
    # AD-1346 M3c: the helpers a site calls (M3d2 added ``hold_at``); held to the decision files' rules (no await, lock, file or connection).
    "seam.py": {"__future__", "probos.admission.carrier", "probos.admission.service", "probos.admission.taxonomy"},
    # AD-1346 M3d2: the work-ticket carrier; held to the decision files' rules, and it does not log.
    "carrier.py": {"__future__", "contextvars", "dataclasses", "typing", "probos.admission.tickets"},
    # AD-1346 M3d1: the work-ticket library; held to the decision files' rules, and it does not log.
    "tickets.py": {
        "__future__", "collections", "collections.abc", "dataclasses", "secrets", "time", "typing",
        "probos.admission.taxonomy", "probos.agent_stop",
    },
}
#: AD-1346 M3b: the persistence files. T14 holds each to its imports; they may await, open the store and log.
_PERSISTENCE_IMPORTS: dict[str, set[str]] = {
    "recorder.py": {
        "__future__", "asyncio", "collections.abc", "dataclasses", "logging", "time", "typing", "uuid",
        "probos.admission.record", "probos.admission.store", "probos.admission.taxonomy", "probos.admission.tickets",
    },
    "report.py": {
        "__future__", "collections.abc", "pathlib", "types", "typing", "probos.protocols",
        "probos.storage.sqlite_factory",
    },
    "storage_declarations.py": {"__future__", "probos.storage.declarations"},
    "store.py": {
        "__future__", "dataclasses", "datetime", "hashlib", "json", "logging", "pathlib", "re", "typing",
        "probos.admission.record", "probos.admission.tickets", "probos.protocols", "probos.storage.sqlite_factory",
    },
}
_FORBIDDEN_CALLS = frozenset({
    "open", "print", "input", "exec", "eval", "__import__", "sleep", "Lock", "RLock", "Semaphore", "Condition",
    "acquire", "connect", "execute", "create_task", "run_in_executor",
})


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def registry(tmp_path: Path) -> AsyncIterator[AgentIdentityRegistry]:
    """A real identity registry in ``tmp_path``, started and commissioned as tests/test_ad1346_identity_service.py does."""
    reg = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await reg.start()
        await reg.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        yield reg
    finally:
        await reg.stop()


@pytest.fixture
def identities(tmp_path: Path, registry: AgentIdentityRegistry) -> IdentityService:
    """The real facade over the registry and a real ``CallsignRegistry`` bound to an empty ``AgentRegistry``."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "surgeon.yaml").write_text("callsign: Meridian\n", encoding="utf-8")
    callsigns = CallsignRegistry()
    callsigns.load_from_profiles(str(profiles))
    callsigns.bind_registry(AgentRegistry())
    return IdentityService(registry, callsigns)


@pytest_asyncio.fixture
async def stops(tmp_path: Path) -> AsyncIterator[AgentStopService]:
    """A real Captain's stop record over ``tmp_path``."""
    record = AgentStopService(data_dir=tmp_path / "stops")
    await record.start()
    try:
        yield record
    finally:
        await record.stop()


@pytest.fixture
def gate(identities: IdentityService, stops: AgentStopService) -> AdmissionService:
    return AdmissionService(identities, stops)


async def _certify(
    reg: AgentIdentityRegistry, slot_id: str = SURGEON_SLOT, agent_type: str = "surgeon", department: str = "medical",
) -> AgentBirthCertificate:
    return await reg.resolve_or_issue(
        slot_id=slot_id, agent_type=agent_type, callsign=agent_type.title(), instance_id=INSTANCE_ID,
        vessel_name=VESSEL_NAME, department=department, post_id=agent_type, baseline_version="v1",
    )


def _request(
    presented_id: str, *, work_kind: str = "intent", seam: str = "intent", origin: str = "captain",
    origin_id: str = "captain",
) -> WorkRequest:
    return WorkRequest(presented_id, work_kind, seam, origin, origin_id)


def _shadow(gate: AdmissionService, presented_id: str, **fields: str) -> None:
    values = {"work_kind": "intent", "seam": "intent", "origin": "captain", "origin_id": "captain", **fields}
    return gate.shadow(presented_id=presented_id, **values)


def _module_names(nodes: list[Any]) -> set[str]:
    names: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def _within(node: ast.AST, scope: ast.AST) -> bool:
    return scope.lineno <= node.lineno <= (scope.end_lineno or scope.lineno)


class _Str(str):
    """A ``str`` subclass, which is not an exact ``str``."""


# ---------------------------------------------------------------------------
# T1 to T4: the vocabularies and the records
# ---------------------------------------------------------------------------


def test_the_vocabularies_are_closed_and_share_the_stop_codes() -> None:
    """T1: the seams extend the stop's, the stop's code is imported, every code fits AD-1316's syntax (kills M1, M2)."""
    assert taxonomy.STOP_SEAMS is agent_stop.SEAMS
    assert taxonomy.EFFECT_SEAMS == frozenset({"model_call"})
    assert taxonomy.SEAMS == agent_stop.SEAMS | taxonomy.EFFECT_SEAMS
    assert agent_stop.SEAMS < taxonomy.SEAMS and not agent_stop.SEAMS & taxonomy.EFFECT_SEAMS
    tree = ast.parse((_PACKAGE / "taxonomy.py").read_text(encoding="utf-8"))
    imported = {
        alias.name for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "probos.agent_stop" for alias in node.names
    }
    assert imported == {"SEAMS", "STOP_REASON_CODE"}, "the stop's names are imported, not restated"
    assert taxonomy.REASON_AGENT_STOPPED == agent_stop.STOP_REASON_CODE == "agent_stopped"
    assert taxonomy.REASON_CODES == ("admitted", "agent_stopped", "identity_unresolved", "system_principal_unlisted")
    assert authority._REASON_CODE_RE.pattern == r"[a-z][a-z0-9_]{0,127}\Z", "premise: the AD-1316 syntax shared (D8)"
    for code in taxonomy.REASON_CODES:
        assert authority._REASON_CODE_RE.fullmatch(code), code
    assert taxonomy.ORIGINS == ("captain", "agent", "system", "federation_peer")
    assert taxonomy.PRINCIPAL_KINDS == ("certificate", "asset", "system", "unresolved")
    assert taxonomy.OUTCOMES == ("admit", "would_refuse")
    assert taxonomy.WORK_KINDS == (
        "intent", "consultation", "proactive_cycle", "ward_room_notice", "direct_message", "group_turn",
        "browser_action", "agentic_run", "delegated_task", "tool_call", "model_call",
        "agent_work",  # AD-1346 M3c3: appended; the vocabulary is persisted, so it grows only at its end
    )
    for vocabulary in (
        taxonomy.REASON_CODES, taxonomy.ORIGINS, taxonomy.PRINCIPAL_KINDS, taxonomy.OUTCOMES, taxonomy.WORK_KINDS,
    ):
        assert len(set(vocabulary)) == len(vocabulary), vocabulary


def test_the_check_order_and_the_deferred_checks_are_pinned() -> None:
    """T2: two checks in ``CHECK_ORDER``, the deferred ones with their owners, and ``decide`` calls them in order."""
    assert taxonomy.CHECK_ORDER == ("principal", "agent_stop")
    assert taxonomy.DEFERRED_CHECKS == (
        ("vessel_stop", "AD-1343 S3, built in AD-1346 M4"),
        ("lifecycle_acm", "AD-1346 M3f"),
        ("earned_agency", "AD-1346 M3f"),
        ("scope_clearance", "AD-1346 M3f"),
        ("budget_reservation", "AD-1346 M3f"),
        ("pre_intent_hooks", "AD-698, AD-1346 M3f"),
    )
    assert not {name for name, _ in taxonomy.DEFERRED_CHECKS} & set(taxonomy.CHECK_ORDER)
    decide = function("src/probos/admission/service.py", "AdmissionService.decide")
    resolved = first_line(decide, calls("resolve_principal"))
    assert resolved < first_line(decide, calls("check_principal")) < first_line(decide, calls("check_agent_stop"))


def test_a_work_request_takes_exact_strings_from_the_closed_sets() -> None:
    """T3: exact ``str`` fields, each closed set enforced, frozen (kills M1, M4, M5, M6, M7)."""
    assert [f.name for f in dataclasses.fields(WorkRequest)] == ["presented_id", "work_kind", "seam", "origin", "origin_id"]
    for seam in sorted(taxonomy.SEAMS):
        assert _request("x", seam=seam).seam == seam
    for kind in taxonomy.WORK_KINDS:
        assert _request("x", work_kind=kind).work_kind == kind
    for origin in taxonomy.ORIGINS:
        assert _request("x", origin=origin).origin == origin
    assert _request("").presented_id == ""  # accepted: the decision refuses it (T7)
    with pytest.raises(ValueError, match="work kind"):
        _request("x", work_kind="holodeck")
    with pytest.raises(ValueError, match="seam"):
        _request("x", seam="subprocess")
    with pytest.raises(ValueError, match="origin"):
        _request("x", origin="peer")
    with pytest.raises(TypeError, match="presented_id"):
        _request(_Str("x"))  # a str subclass is not a str (kills M4)
    with pytest.raises(TypeError, match="origin_id"):
        WorkRequest("x", "intent", "intent", "captain", None)  # type: ignore[arg-type]
    request = _request("x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.seam = "tool"  # type: ignore[misc]


async def test_the_verdict_v1_is_frozen(registry: AgentIdentityRegistry, gate: AdmissionService) -> None:
    """T4: ``VERDICT_KEYS``, the field order, the embedded ref, the JSON round trip, the record's checks (kills M8 to M10)."""
    await _certify(registry)
    assert VERDICT_KEYS == (
        "outcome", "reason_code", "check", "cause", "key", "principal_kind", "principal",
        "presented_id", "work_kind", "seam", "origin", "origin_id", "stop_id",
    )
    assert tuple(f.name for f in dataclasses.fields(AdmissionVerdict)) == VERDICT_KEYS
    verdict = gate.decide(_request(SURGEON_SLOT, work_kind="tool_call", seam="tool", origin="agent", origin_id="x"))
    body = verdict.to_dict()
    assert tuple(body) == VERDICT_KEYS
    assert isinstance(verdict.principal, IdentityRef)
    assert body["principal"] == verdict.principal.to_dict() and tuple(body["principal"]) == IDENTITY_REF_KEYS
    assert json.loads(json.dumps(body)) == body
    assert (body["work_kind"], body["seam"], body["origin"], body["origin_id"]) == ("tool_call", "tool", "agent", "x")
    refused = gate.decide(_request("nobody")).to_dict()
    assert refused["principal"] is None and json.loads(json.dumps(refused)) == refused
    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.outcome = "would_refuse"  # type: ignore[misc]
    fields = {name: getattr(verdict, name) for name in VERDICT_KEYS}
    with pytest.raises(ValueError):
        AdmissionVerdict(**{**fields, "reason_code": "agent_stopped"})  # an admit carrying a refusal code (kills M8)
    with pytest.raises(ValueError):
        AdmissionVerdict(**{**fields, "outcome": "would_refuse"})  # a refusal carrying admitted
    with pytest.raises(ValueError):
        AdmissionVerdict(**{**fields, "outcome": "refuse", "reason_code": "agent_stopped"})  # kills M9
    with pytest.raises(ValueError):
        AdmissionVerdict(**{**fields, "principal_kind": "crew"})


# ---------------------------------------------------------------------------
# T5 to T10: decide
# ---------------------------------------------------------------------------


async def test_a_certificate_principal_is_admitted_and_keyed_on_its_slot(
    registry: AgentIdentityRegistry, gate: AdmissionService,
) -> None:
    """T5: the slot, the certificate UUID and the DID give one admit keyed on the slot (kills M12, M24)."""
    cert = await _certify(registry)
    verdicts = [gate.decide(_request(key)) for key in (SURGEON_SLOT, cert.agent_uuid, cert.did)]
    for verdict in verdicts:
        assert (verdict.outcome, verdict.reason_code, verdict.check, verdict.stop_id) == ("admit", "admitted", "", "")
        assert verdict.key == SURGEON_SLOT
        assert verdict.principal_kind == "certificate"
        assert verdict.principal is not None and verdict.principal.slot_id == SURGEON_SLOT
        assert verdict.principal.did == cert.did
    assert [v.presented_id for v in verdicts] == [SURGEON_SLOT, cert.agent_uuid, cert.did]
    bodies = [{k: v for k, v in verdict.to_dict().items() if k != "presented_id"} for verdict in verdicts]
    assert bodies[0] == bodies[1] == bodies[2]


async def test_an_asset_principal_is_admitted_as_an_asset(registry: AgentIdentityRegistry, gate: AdmissionService) -> None:
    """T6: an asset slot and its tag UUID are admitted with kind ``asset`` and no DID (kills M11)."""
    tag = await registry.resolve_or_issue_asset_tag(TOOL_SLOT, "calculator", "calculator")
    for key in (TOOL_SLOT, tag.asset_uuid):
        verdict = gate.decide(_request(key, work_kind="tool_call", seam="tool", origin="agent", origin_id=SURGEON_SLOT))
        assert (verdict.outcome, verdict.reason_code, verdict.principal_kind, verdict.key) == (
            "admit", "admitted", "asset", TOOL_SLOT,
        ), key
        assert verdict.principal is not None and verdict.principal.did == ""


async def test_an_unresolved_principal_would_be_refused_and_keyed_on_the_presented_id(
    registry: AgentIdentityRegistry, gate: AdmissionService,
) -> None:
    """T7: an id the facade does not resolve, a callsign included, is a would-refuse (kills M14, M21, M23)."""
    await _certify(registry)
    for presented in ("", "nobody_0_00000000", "Surgeon", UNKNOWN_UUID):
        verdict = gate.decide(_request(presented))
        assert (verdict.outcome, verdict.reason_code, verdict.check) == (
            "would_refuse", "identity_unresolved", "principal",
        ), presented
        assert verdict.key == presented and verdict.presented_id == presented
        assert verdict.principal_kind == "unresolved" and verdict.principal is None and verdict.stop_id == ""
        assert repr(presented) in verdict.cause


async def test_the_system_allowlist_applies_to_an_id_the_facade_does_not_resolve(
    registry: AgentIdentityRegistry, gate: AdmissionService,
) -> None:
    """T8: unresolved, ``system:ship_computer`` is admitted and ``system:dream_scheduler`` is not; registered as an asset
    slot, ``system:dream_scheduler`` and its tag UUID resolve through the facade first and are admitted as an asset (D22,
    D37; kills M3, M13, M15, M21, M37, M38). Not covered: a certificate slot with the prefix, or a stop on one."""
    assert taxonomy.SYSTEM_PRINCIPAL_PREFIX == "system:"
    assert taxonomy.SYSTEM_PRINCIPALS == frozenset({"system:ship_computer"})
    listed = gate.decide(_request("system:ship_computer", origin="system", origin_id="system:ship_computer"))
    assert (listed.outcome, listed.reason_code, listed.check, listed.principal_kind, listed.key) == (
        "admit", "admitted", "", "system", "system:ship_computer",
    )
    assert listed.principal is None
    unlisted = gate.decide(_request("system:dream_scheduler", origin="system", origin_id="system:dream_scheduler"))
    assert (unlisted.outcome, unlisted.reason_code, unlisted.check, unlisted.principal_kind, unlisted.key) == (
        "would_refuse", "system_principal_unlisted", "principal", "system", "system:dream_scheduler",
    )
    assert "'system:dream_scheduler'" in unlisted.cause
    tag = await registry.resolve_or_issue_asset_tag("system:dream_scheduler", "dream_scheduler", "dream_scheduler")
    for key in ("system:dream_scheduler", tag.asset_uuid):
        resolved = gate.decide(_request(key, origin="system", origin_id="system:dream_scheduler"))
        assert (resolved.outcome, resolved.reason_code, resolved.check, resolved.principal_kind, resolved.key) == (
            "admit", "admitted", "", "asset", "system:dream_scheduler",
        ), key
        assert resolved.principal is not None and resolved.principal.slot_id == "system:dream_scheduler"
        assert resolved.principal.did == ""


async def test_a_captains_stop_is_read_without_counting_and_its_reason_stays_out(
    registry: AgentIdentityRegistry, stops: AgentStopService, gate: AdmissionService,
) -> None:
    """T9: a stop on the slot is seen through every form, counts no refusal and leaks no reason (kills M2, M12, M16, M17, M22, M24, M25)."""
    cert = await _certify(registry)
    await _certify(registry, COUNSELOR_SLOT, "counselor", "medical")
    issued = await stops.issue_stop(SURGEON_SLOT, reason=CANARY)
    stop_id = issued.record.stop_id
    for key in (SURGEON_SLOT, cert.agent_uuid, cert.did):  # D5: a DID presented for a stopped slot is caught (BF-907 class)
        verdict = gate.decide(_request(key))
        assert (verdict.outcome, verdict.reason_code, verdict.check) == ("would_refuse", "agent_stopped", "agent_stop"), key
        assert verdict.stop_id == stop_id and verdict.key == SURGEON_SLOT
        assert stop_id in verdict.cause and SURGEON_SLOT in verdict.cause
        assert "CANARY" not in json.dumps(verdict.to_dict())
    assert _shadow(gate, cert.did) is None
    assert stops.refused_counts(stop_id) == {}, "a shadow decision must count no refusal (AD-1343 S1 constraint)"
    assert gate.decide(_request(COUNSELOR_SLOT)).outcome == "admit", "a stop on one slot does not touch another"
    await stops.lift_stop(SURGEON_SLOT, reason="lifted by the test")
    assert gate.decide(_request(SURGEON_SLOT)).outcome == "admit", "a lift is read at the next decision"


async def test_the_service_takes_only_the_real_facade_and_stop_record(
    identities: IdentityService, stops: AgentStopService, gate: AdmissionService,
) -> None:
    """T10: the constructor refuses an object that is not an instance of the two types, and ``decide`` one whose type is not ``WorkRequest`` (kills M18 to M20)."""
    with pytest.raises(TypeError, match="IdentityService"):
        AdmissionService(None, stops)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="AgentStopService"):
        AdmissionService(identities, None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="AgentStopService"):
        AdmissionService(identities, SimpleNamespace(stop_for=lambda agent_id: None))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="WorkRequest"):
        gate.decide({"presented_id": SURGEON_SLOT})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# T11 to T13: shadow
# ---------------------------------------------------------------------------


async def test_shadow_returns_none_and_counts_each_verdict_and_its_latency(
    registry: AgentIdentityRegistry, identities: IdentityService, stops: AgentStopService,
) -> None:
    """T11: None for every call, the tally by (seam, kind, code), one latency bucket per call (kills M26 to M29)."""
    await _certify(registry)
    ticks = iter([100, 105, 200, 200, 300, 300 + 2**45])
    gate = AdmissionService(identities, stops, clock=lambda: next(ticks))
    assert gate.tally() == {} and gate.latency_histogram() == (0,) * taxonomy.LATENCY_BUCKETS and gate.failures == 0
    assert _shadow(gate, SURGEON_SLOT) is None
    assert _shadow(gate, "nobody", work_kind="tool_call", seam="tool", origin="agent", origin_id=SURGEON_SLOT) is None
    assert _shadow(gate, SURGEON_SLOT) is None
    assert gate.tally() == {("intent", "intent", "admitted"): 2, ("tool", "tool_call", "identity_unresolved"): 1}
    assert taxonomy.LATENCY_BUCKETS == 40
    histogram = gate.latency_histogram()
    assert histogram[3] == 1, histogram  # 5 ns: bit_length 3
    assert histogram[0] == 1, histogram  # 0 ns
    assert histogram[39] == 1, histogram  # 2**45 ns: past the last bucket, counted in it
    assert sum(histogram) == 3 and gate.failures == 0
    copy = gate.tally()
    copy.clear()
    assert gate.tally() != {}, "tally() returns a copy"


async def test_shadow_counts_and_logs_an_exception_and_returns_none(
    identities: IdentityService, gate: AdmissionService, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """T12: with healthy logging, a malformed request and a raising facade are counted, logged and answered with None (kills M30 to M32)."""
    caplog.set_level(logging.DEBUG, logger="probos.admission.service")
    assert _shadow(gate, SURGEON_SLOT, seam="subprocess") is None
    assert gate.failures == 1 and gate.tally() == {}

    def boom(key: str) -> None:
        raise RuntimeError("INJECTED resolver failure")

    monkeypatch.setattr(identities, "resolve", boom)
    assert _shadow(gate, SURGEON_SLOT) is None
    assert gate.failures == 2 and gate.tally() == {} and sum(gate.latency_histogram()) == 0
    with pytest.raises(RuntimeError, match="INJECTED"):
        gate.decide(_request(SURGEON_SLOT))  # decide propagates the facade's exception
    records = [r for r in caplog.records if r.name == "probos.admission.service"]
    assert [r.levelno for r in records] == [logging.WARNING, logging.DEBUG]
    assert all(r.exc_info for r in records)


async def test_the_service_reads_no_configuration_and_holds_only_its_two_dependencies_and_three_optional_parts(
    gate: AdmissionService,
) -> None:
    """T13: no configuration field; the facade, the stop record, a clock, an optional recorder, an optional ticket
    registry, an optional event loop and its counters are all it holds. AD-1346 M3b renamed this test when it added the
    keyword-only ``recorder`` (None in this fixture). AD-1346 M3c added ``today_outcome`` (default None) and the
    ``_closed`` flag. AD-1346 M3d2 added the keyword-only ``tickets`` (None in this fixture) and renamed this test again.
    AD-1346 M3d3a added the keyword-only ``loop`` (None in this fixture) and the ``_off_loop`` counts, and renamed it a
    third time. The service's source still names no configuration (``SystemConfig``, ``shadow_enabled``)."""
    source = (_PACKAGE / "service.py").read_text(encoding="utf-8")
    assert "SystemConfig" not in source and "shadow_enabled" not in source
    init = inspect.signature(AdmissionService.__init__).parameters
    assert list(init) == ["self", "identity_service", "stop_service", "clock", "recorder", "tickets", "loop"]
    assert init["clock"].kind is inspect.Parameter.KEYWORD_ONLY
    assert init["recorder"].kind is inspect.Parameter.KEYWORD_ONLY and init["recorder"].default is None
    assert init["tickets"].kind is inspect.Parameter.KEYWORD_ONLY and init["tickets"].default is None
    assert init["loop"].kind is inspect.Parameter.KEYWORD_ONLY and init["loop"].default is None
    shadow = inspect.signature(AdmissionService.shadow).parameters
    assert list(shadow) == ["self", "presented_id", "work_kind", "seam", "origin", "origin_id", "today_outcome"]
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for name, p in shadow.items() if name != "self")
    assert shadow["today_outcome"].default is None
    assert set(vars(gate)) == {
        "_identities", "_stops", "_clock", "_recorder", "_tickets", "_loop", "_off_loop", "_closed", "_tally", "_latency",
        "_failures",
    }
    assert vars(gate)["_recorder"] is None and vars(gate)["_tickets"] is None and vars(gate)["_closed"] is False
    assert vars(gate)["_loop"] is None and vars(gate)["_off_loop"] == {}


# ---------------------------------------------------------------------------
# T14 to T16: structure
# ---------------------------------------------------------------------------


def test_the_decision_files_await_nothing_and_every_file_imports_only_its_allowlist() -> None:
    """T14: in the decision files no await, lock, file or connection call; logging only in ``shadow``, from AD-1346
    M3d2 ``hold`` and from AD-1346 M3d3a ``_check_ticket``, and in ``service.py`` the clock only in ``shadow``
    (``tickets.py``, added by AD-1346 M3d1, reads its registry's injected clock); the import allowlist per file of the
    package. AD-1346 M3b renamed this test and added the persistence files' allowlists when the package gained files that
    await and open a store. AD-1346 M3d3a added ``asyncio`` to ``service.py``'s allowlist, for ``get_running_loop`` and
    ``call_soon_threadsafe``, neither of which awaits. AD-1346 M3d3b added ``hashlib``, ``re`` and
    ``probos.admission.tickets`` to ``store.py``'s, and AD-1346 M3d3b2 ``dataclasses`` and ``probos.admission.tickets``
    to ``recorder.py``'s."""
    assert admission_package.__all__ == ["VERDICT_KEYS", "AdmissionService", "AdmissionVerdict", "WorkRequest"]
    assert sorted(p.name for p in _PACKAGE.glob("*.py")) == sorted(_ALLOWED_IMPORTS | _PERSISTENCE_IMPORTS), (
        "premise: the package's files"
    )
    for name, allowed in _PERSISTENCE_IMPORTS.items():
        tree = ast.parse((_PACKAGE / name).read_text(encoding="utf-8"), filename=name)
        top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        guarded = [
            s for n in tree.body
            if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "TYPE_CHECKING" for s in n.body
        ]
        every = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        assert len(every) == len(top) + len(guarded), f"{name}: an import outside the module body or its TYPE_CHECKING block"
        assert _module_names(every) == allowed, name
    for name, allowed in _ALLOWED_IMPORTS.items():
        tree = ast.parse((_PACKAGE / name).read_text(encoding="utf-8"), filename=name)
        top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        guarded = [
            s for n in tree.body
            if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "TYPE_CHECKING" for s in n.body
        ]
        every = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        assert len(every) == len(top) + len(guarded), f"{name}: an import outside the module body or its TYPE_CHECKING block"
        assert _module_names(every) == allowed, name
        for node in ast.walk(tree):
            assert not isinstance(node, (ast.Await, ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith)), (name, node.lineno)
            if isinstance(node, ast.Call):
                func = node.func
                callee = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
                assert callee not in _FORBIDDEN_CALLS, (name, node.lineno, callee)
        if name != "service.py":
            assert not any(isinstance(n, ast.Name) and n.id == "logger" for n in ast.walk(tree)), name
    tree = ast.parse((_PACKAGE / "service.py").read_text(encoding="utf-8"))
    shadow = function("src/probos/admission/service.py", "AdmissionService.shadow")
    init = function("src/probos/admission/service.py", "AdmissionService.__init__")
    hold = function("src/probos/admission/service.py", "AdmissionService.hold")
    sink = function("src/probos/admission/service.py", "AdmissionService._check_ticket")
    loggers = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "logger" and isinstance(n.ctx, ast.Load)]
    assert loggers and all(_within(n, shadow) or _within(n, hold) or _within(n, sink) for n in loggers), (
        "only shadow(), hold() and _check_ticket() log"
    )
    assert any(_within(n, hold) for n in loggers), "premise: hold() logs its failure"
    assert any(_within(n, sink) for n in loggers), "premise: _check_ticket() logs its failure"
    clocks = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "_clock"]
    assert all(_within(n, shadow) or (_within(n, init) and isinstance(n.ctx, ast.Store)) for n in clocks), (
        "only shadow() reads the clock"
    )
    assert sum(_within(n, shadow) for n in clocks) == 2, "premise: shadow() reads the clock twice"


def test_the_package_calls_no_stop_guard_and_starts_no_agent_work() -> None:
    """T15: the seam census over the package: no guard callee, no agent-work call, the stop read with ``stop_for`` (kills M16)."""
    assert {"active_stop", "refusal", "tool_refusal", "refuse_new_run", "standing_stop"} <= GUARD_CALLEES  # premise
    found = [c for c in census() if c.file.startswith("src/probos/admission/")]
    assert ("src/probos/admission/service.py", "AdmissionService.shadow", "decide", "self") in {
        (c.file, c.function, c.callee, c.receiver) for c in found
    }, "premise: the census scanned the package"
    assert [c for c in found if c.callee in GUARD_CALLEES] == []
    assert [c for c in found if is_agent_work_call(c)] == []
    assert first_line(function("src/probos/admission/checks.py", "check_agent_stop"), calls("stop_for")) > 0


def test_only_the_wiring_the_shadowed_seams_and_the_sinks_name_the_service_or_import_the_package() -> None:
    """T16: the consumer census (#1604, property 11). Outside the package the runtime builds the service and shutdown
    closes and releases it. Each site AD-1346 M3c1 to M3c3 shadow reaches it the way it reaches its stop gate: ten files
    read ``admission_service`` from a runtime (``cognitive_agent.py``, ``agentic_dispatch.py``, ``proactive.py``,
    ``cognitive/dm/reply_pipeline.py``, ``tools/delegate_task_tool.py``, ``crew_synth.py``, ``crew_verifier.py``, which
    also hands it to a correction's projected registry, and three routers); ``tools/registry.py`` is handed it by
    ``set_admission``; ``ward_room_router.py`` and ``crew_finalizer.py`` take it in their constructors from
    ``startup/finalize.py``; and ``agent_work.py`` takes it in its constructor from ``runtime.py``. Each of those fourteen
    imports ``probos.admission``. From AD-1346 M3d3a the model gateway's module, ``cognitive/llm_client.py``, imports it
    too, and ``runtime.py`` hands ``OpenAICompatibleClient`` the service through its own ``set_admission``. AD-1346 M3d3a
    renamed this test. From AD-1346 M3e1 the five subprocess sinks' modules (``agents/shell_command.py``,
    ``agents/red_team.py``, ``agents/code_search.py``, ``cognitive/scout.py``, ``cognitive/swe_harness/tools.py``) read
    ``admission_service`` from their runtime and import ``probos.admission``, and AD-1346 M3e1 renamed this test again.
    From AD-1346 M3e2a ``agents/code_runner.py`` and ``tools/code_execution_tool.py`` read it from their runtime and hand
    it to ``SubprocessSandbox``, whose module ``execution/isolation.py`` names it and imports ``probos.admission``;
    ``runtime.py`` hands it to ``DependencyResolver`` through ``set_admission``, and ``cognitive/dependency_resolver.py``
    imports the package.
    The only routers that name the service or import the package are the three whose routes M3c2
    shadows, and none of them is a module of #1604 property 11's routes, which are never admission-gated."""
    # #1604 property 11: the Captain's stop and lift (``routers/agent_stop.py``, ``/api/stops``), and health and status
    # (``routers/system.py``: ``/api/health``, ``/api/status``; ``routers/voice.py``: ``/api/voice/health``;
    # ``routers/desktop.py``: ``/api/desktop/status``); ``api.py`` builds the app.
    never_gated = {
        "probos/api.py", "probos/routers/agent_stop.py", "probos/routers/desktop.py", "probos/routers/system.py",
        "probos/routers/voice.py",
    }
    named: set[str] = set()
    importers: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC.parent).as_posix()
        if rel.startswith("probos/admission/"):
            continue
        text = path.read_text(encoding="utf-8")
        if "admission_service" in text:
            named.add(rel)
        if "admission" not in text:
            continue
        for node in ast.walk(ast.parse(text, filename=rel)):
            if any(m == "probos.admission" or m.startswith("probos.admission.") for m in _module_names([node])):
                importers.add(rel)
            if isinstance(node, ast.ImportFrom) and node.module == "probos" and any(a.name == "admission" for a in node.names):
                importers.add(rel)
    assert named == {
        "probos/agent_work.py", "probos/cognitive/agentic_dispatch.py", "probos/cognitive/cognitive_agent.py",
        "probos/cognitive/crew_finalizer.py", "probos/cognitive/crew_synth.py", "probos/cognitive/crew_verifier.py",
        "probos/cognitive/dm/reply_pipeline.py", "probos/proactive.py", "probos/routers/agent_actions.py",
        "probos/routers/agents.py", "probos/routers/thread_fanout.py", "probos/runtime.py", "probos/startup/finalize.py",
        "probos/startup/shutdown.py", "probos/tools/delegate_task_tool.py",
        "probos/agents/code_search.py", "probos/agents/red_team.py", "probos/agents/shell_command.py",
        "probos/cognitive/scout.py", "probos/cognitive/swe_harness/tools.py",  # AD-1346 M3e1: the subprocess sinks
        "probos/agents/code_runner.py", "probos/execution/isolation.py", "probos/tools/code_execution_tool.py",  # AD-1346 M3e2a
    }, sorted(named)
    assert importers == {
        "probos/agent_work.py", "probos/cognitive/agentic_dispatch.py", "probos/cognitive/cognitive_agent.py",
        "probos/cognitive/crew_finalizer.py", "probos/cognitive/crew_synth.py", "probos/cognitive/crew_verifier.py",
        "probos/cognitive/dm/reply_pipeline.py", "probos/proactive.py", "probos/routers/agent_actions.py",
        "probos/routers/agents.py", "probos/routers/thread_fanout.py", "probos/runtime.py", "probos/tools/delegate_task_tool.py",
        "probos/tools/registry.py", "probos/ward_room_router.py", "probos/cognitive/llm_client.py",
        "probos/agents/code_search.py", "probos/agents/red_team.py", "probos/agents/shell_command.py",
        "probos/cognitive/scout.py", "probos/cognitive/swe_harness/tools.py",  # AD-1346 M3e1: the subprocess sinks
        "probos/cognitive/dependency_resolver.py", "probos/execution/isolation.py",  # AD-1346 M3e2a
    }, sorted(importers)
    routes = {rel for rel in named | importers if rel.startswith("probos/routers/") or rel == "probos/api.py"}
    assert routes == {"probos/routers/agent_actions.py", "probos/routers/agents.py", "probos/routers/thread_fanout.py"}, sorted(routes)
    assert not routes & never_gated, sorted(routes & never_gated)
