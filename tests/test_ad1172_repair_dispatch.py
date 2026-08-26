"""AD-1172: a repair brief, and a target the Captain chooses.

ArchitectAgent and BuilderAgent are fully built and work well, and have always
been reachable only by the Captain typing `/design`. No system signal could
summon them.

The deliverable is deliberately NOT "dispatch to the Architect". The Captain's
constraint was explicit: *"I could decide to have a different harness do the
work. I could decide to use GitHub Copilot for example."* So the artifact is a
harness-neutral brief, and the internal crew is one target in the same list as
any external one.
"""

from __future__ import annotations

import pytest

from probos.cognitive.repair_brief import (
    TARGET_ARCHITECT,
    RepairBrief,
    build_repair_brief,
    is_internal_target,
    resolve_targets,
)
from probos.cognitive.repair_dispatch import (
    REPAIR_ACTION,
    REPAIR_TOOL_ID,
    RepairDispatcher,
    wire_repair_dispatcher,
)
from probos.config import RepairConfig, SystemConfig
from probos.fault_report import FaultReportStore


# ── fakes ─────────────────────────────────────────────────────────


class _Fault:
    def __init__(self, **kw) -> None:
        self.id = kw.get("id", "f1")
        self.tool_id = kw.get("tool_id", "browser")
        self.signature = kw.get("signature", "a" * 64)
        self.error_text = kw.get("error_text", "unknown browser action: 'key_type'")
        self.occurrences = kw.get("occurrences", 2)
        self.attempted = kw.get("attempted", "type Hello into the document")
        self.agent_id = kw.get("agent_id", "counselor-ezri")
        self.thread_id = kw.get("thread_id", "thread-1")
        self.tool_trace_ref = kw.get("tool_trace_ref", "")


class _Requests:
    def __init__(self, fail: bool = False) -> None:
        self.filed: list[dict] = []
        self.fail = fail

    async def file_action_request(self, *, agent_id, payload, rationale="", **_kw):
        if self.fail:
            raise RuntimeError("store down")
        record = {"agent_id": agent_id, "payload": payload, "rationale": rationale}
        self.filed.append(record)
        return type("R", (), {"id": f"req{len(self.filed)}"})()


class _Faults:
    def __init__(self, fault=None) -> None:
        self.fault = fault

    def get(self, _sig):
        return self.fault


class _Runtime:
    def __init__(self) -> None:
        self.attachment_store = None
        self.listeners: list = []

    def add_event_listener(self, fn, event_types=None):
        self.listeners.append((fn, tuple(event_types or ())))


def _dispatcher(*, enabled=True, targets=None, requests=None, fault=None, **cfg):
    return RepairDispatcher(
        runtime=_Runtime(),
        fault_report_store=_Faults(fault if fault is not None else _Fault()),
        capability_request_store=requests if requests is not None else _Requests(),
        config=RepairConfig(
            enabled=enabled,
            targets=targets if targets is not None else ["architect"],
            **cfg,
        ),
    )


def _event(kind="fault_reported", **data):
    base = {"signature": "a" * 64, "occurrences": 2, "tool_id": "browser"}
    base.update(data)
    return {"type": kind, "data": base}


# ── the brief is harness-neutral ──────────────────────────────────


def test_the_brief_is_a_portable_artifact() -> None:
    """THE AD-1172 headline: the same text serves the Architect and Copilot."""
    brief = build_repair_brief(_Fault(), trace_summary="4 of 6 calls failed.")
    md = brief.render_markdown()

    assert "browser" in md
    assert "key_type" in md
    assert "type Hello into the document" in md
    assert "4 of 6 calls failed." in md
    assert "Done means" in md
    assert brief.fault_id in md
    # No ProbOS-internal object references leak into the artifact.
    assert "object at 0x" not in md


def test_the_brief_leads_with_the_fault_not_provenance() -> None:
    md = build_repair_brief(_Fault()).render_markdown()
    assert md.index("What is wrong") < md.index("Provenance")


def test_the_brief_says_the_trace_outranks_the_narration() -> None:
    """The BF-701 lesson, stated in the artifact so a harness inherits it."""
    md = build_repair_brief(_Fault(), trace_summary="x").render_markdown()
    assert "not its narration" in md


def test_acceptance_criteria_are_checkable() -> None:
    """AD-1173 verifies by re-running, so these must be checkable not judged."""
    brief = build_repair_brief(_Fault())
    joined = " ".join(brief.acceptance)
    assert "no longer returns" in joined
    assert "succeeds when retried" in joined
    assert "regression test" in joined
    assert "Engineering Principles" in joined


def test_a_malformed_fault_still_yields_a_brief() -> None:
    brief = build_repair_brief(object())
    assert isinstance(brief, RepairBrief)
    assert brief.render_markdown()


def test_the_title_is_bounded() -> None:
    brief = build_repair_brief(_Fault(error_text="x" * 900))
    assert len(brief.title) <= 120


def test_the_brief_round_trips_to_a_dict() -> None:
    data = build_repair_brief(_Fault()).to_dict()
    assert data["tool_id"] == "browser"
    assert data["occurrences"] == 2
    assert isinstance(data["acceptance"], list)


# ── targets are config-declared ───────────────────────────────────


def test_targets_default_to_the_internal_crew() -> None:
    assert resolve_targets(RepairConfig()) == ("architect",)


def test_an_external_harness_needs_no_code() -> None:
    """Adding a name to the list IS the integration."""
    targets = resolve_targets(RepairConfig(targets=["architect", "copilot"]))
    assert targets == ("architect", "copilot")
    assert is_internal_target("architect") is True
    assert is_internal_target("copilot") is False


def test_declared_order_is_preserved_and_deduped() -> None:
    assert resolve_targets(
        RepairConfig(targets=["copilot", "architect", "copilot"])
    ) == ("copilot", "architect")


@pytest.mark.parametrize("bad", [None, [], object()], ids=["none", "empty", "junk"])
def test_a_missing_target_list_falls_back_to_the_internal_crew(bad) -> None:
    assert resolve_targets(type("C", (), {"targets": bad})()) == (TARGET_ARCHITECT,)


# ── gate 1: propose, never act ────────────────────────────────────


async def test_a_repeated_fault_proposes_one_decision() -> None:
    requests = _Requests()
    d = _dispatcher(requests=requests, targets=["architect", "copilot"])

    await d.on_fault_event(_event())

    assert len(requests.filed) == 1
    payload = requests.filed[0]["payload"]
    assert payload["tool_id"] == REPAIR_TOOL_ID
    assert payload["action"] == REPAIR_ACTION
    assert payload["params"]["targets"] == "architect,copilot"
    assert "key_type" in payload["params"]["brief"]
    assert "choose" in requests.filed[0]["rationale"]


async def test_a_recurring_fault_does_not_re_ask() -> None:
    """One decision per fault, however many times it recurs.

    AD-1267: this asserted ``len(requests.filed) == 1`` against ``_Requests``, a
    double that never deduplicates — so what it actually pinned was the
    dispatcher's in-process ``_proposed`` set being THE record of what had
    already been proposed. That record was wrong twice over: it did not survive
    a restart, and it was marked AFTER the await, so concurrent recurrences all
    passed the check before any of them marked it. AD-1267 deletes it and leaves
    the durable approval store to answer "has this fault already asked?". The
    guarantee is unchanged — only its owner moved — so this now asserts it
    against a surface that deduplicates the way the real one does.
    """
    from probos.capability_request import CapabilityRequestStore

    # No db_path: cache-only, but `file_action_request` -> `action_dedup_key`
    # -> `_find_pending_action` is the real code path.
    requests = CapabilityRequestStore()
    fault = _Fault(occurrences=2)
    d = _dispatcher(requests=requests, fault=fault)
    for occurrence in range(2, 7):
        # The renderer reads the REPORT, not the event, so the report's own
        # count has to move or a count-sensitive brief would still produce one
        # stable key and this would pass against the defect it exists to catch.
        # Review measured exactly that: the fake pinned occurrences=2 forever.
        fault.occurrences = occurrence
        await d.on_fault_event(_event(occurrences=occurrence))

    pending = [r for r in await requests.list_pending() if r.kind == "action"]
    assert len(pending) == 1
    assert pending[0].payload is not None
    assert pending[0].payload["tool_id"] == REPAIR_TOOL_ID


async def test_a_resolved_fault_can_be_proposed_again() -> None:
    """A repair that did not hold must be able to raise a new decision."""
    requests = _Requests()
    d = _dispatcher(requests=requests)
    await d.on_fault_event(_event())
    await d.on_fault_event(_event(kind="fault_resolved"))
    await d.on_fault_event(_event())
    assert len(requests.filed) == 2


async def test_disabled_proposes_nothing() -> None:
    requests = _Requests()
    d = _dispatcher(enabled=False, requests=requests)
    await d.on_fault_event(_event(occurrences=99))
    assert requests.filed == []


async def test_a_single_occurrence_is_below_the_bar() -> None:
    requests = _Requests()
    d = _dispatcher(requests=requests)
    await d.on_fault_event(_event(occurrences=1))
    assert requests.filed == []


async def test_the_threshold_is_configurable() -> None:
    requests = _Requests()
    d = _dispatcher(requests=requests, propose_after_occurrences=5)
    await d.on_fault_event(_event(occurrences=4))
    assert requests.filed == []
    await d.on_fault_event(_event(occurrences=5))
    assert len(requests.filed) == 1


@pytest.mark.parametrize(
    "event",
    [None, {}, {"type": "fault_reported"}, {"type": "x", "data": {}},
     {"type": "fault_reported", "data": {"signature": ""}}],
    ids=["none", "empty", "no-data", "wrong-type", "no-signature"],
)
async def test_a_malformed_event_is_ignored(event) -> None:
    requests = _Requests()
    d = _dispatcher(requests=requests)
    await d.on_fault_event(event)
    assert requests.filed == []


async def test_a_failing_approval_store_does_not_raise() -> None:
    d = _dispatcher(requests=_Requests(fail=True))
    await d.on_fault_event(_event())  # must not raise


async def test_no_approval_surface_degrades_quietly() -> None:
    d = _dispatcher(requests=None)
    d._requests = None
    await d.on_fault_event(_event())  # must not raise


async def test_an_unknown_signature_proposes_nothing() -> None:
    requests = _Requests()
    d = RepairDispatcher(
        runtime=_Runtime(),
        fault_report_store=_Faults(None),
        capability_request_store=requests,
        config=RepairConfig(enabled=True),
    )
    assert await d.propose("nope") is None
    assert requests.filed == []


# ── wiring ────────────────────────────────────────────────────────


def test_wiring_subscribes_to_both_fault_events() -> None:
    runtime = _Runtime()
    runtime.fault_report_store = FaultReportStore()
    runtime.capability_request_store = _Requests()

    dispatcher = wire_repair_dispatcher(runtime, SystemConfig())

    assert dispatcher is not None
    assert len(runtime.listeners) == 1
    _fn, types = runtime.listeners[0]
    assert set(types) == {"fault_reported", "fault_resolved"}


def test_wiring_without_a_fault_store_stays_off() -> None:
    runtime = _Runtime()
    runtime.fault_report_store = None
    assert wire_repair_dispatcher(runtime, SystemConfig()) is None


def test_the_config_defaults_off_with_the_internal_crew() -> None:
    cfg = SystemConfig().repair
    assert cfg.enabled is False
    assert cfg.targets == ["architect"]
    assert cfg.propose_after_occurrences == 2


def test_the_threshold_matches_its_siblings() -> None:
    from probos.cognitive.continue_or_ask import _DEFECT_MIN_OCCURRENCES
    from probos.cognitive.trace_analysis import REPEAT_THRESHOLD

    assert (
        SystemConfig().repair.propose_after_occurrences
        == _DEFECT_MIN_OCCURRENCES
        == REPEAT_THRESHOLD
    )


async def test_the_payload_satisfies_the_ad1154_contract() -> None:
    """The approval payload is bound-checked by validate_action_payload; a
    shape that fails it would be silently dropped to payload=None."""
    from probos.capability_request import validate_action_payload

    requests = _Requests()
    await _dispatcher(requests=requests).on_fault_event(_event())
    assert validate_action_payload(requests.filed[0]["payload"]) is not None
