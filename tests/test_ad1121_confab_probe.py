"""AD-1121 (#1024): live cascade-confab divergence probe (detection).

BF-287 discipline: real ``SystemConfig()``, real ``NotificationQueue``, real
``EvidenceCollector`` (tmp ``output_dir``), and a scripted-LLM stub (NOT
MagicMock) that pops canned ``LLMResponse`` texts and RECORDS every request it
receives. The runtime is a light real-attr ``SimpleNamespace`` carrying only what
the seam reads. Git is avoided entirely by using an ``entity``-kind central
referent (``node oracle_probe``) so the probe tests are hermetic.

``asyncio_mode = "auto"`` (pyproject) — bare ``async def test_*`` needs no marker.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.confab_probe import (
    ProbeResult,
    _classify_existence,
    probe_referent,
)
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.cognitive.emergence_taxonomy import BehaviorCode
from probos.cognitive.evidence_collector import EvidenceCollector
from probos.config import CognitiveConfig, LLMRateConfig, SystemConfig
from probos.notifications import NotificationQueue
from probos.runtime import ProbOSRuntime
from probos.routers import thread_fanout
from probos.startup.finalize import _wire_emergence_collector
from probos.types import LLMResponse

# An entity seed whose ONLY extracted referent is the `entity`-kind token
# "oracle_probe" (git-free — no hex, so no git-HEAD probe). Empty resolvers make
# it UNRESOLVED -> central.
_SEED = "please check node oracle_probe now"
_TOKEN = "oracle_probe"


# ---------------- BF-287 real fixtures / scripted stubs ----------------


class _ScriptedLLM:
    """A scripted LLM stub (NOT MagicMock).

    Pops one queued response per ``complete`` call and RECORDS every request
    (for the context-free assertion). A queued ``BaseException`` is raised (to
    exercise the per-sample honest-degrade path). Runs dry -> structured
    affirmative default (so an under-seeded call never reads as an accidental
    abstention).
    """

    def __init__(self, responses: list[Any] | None = None) -> None:
        self._responses = list(responses or [])
        self.requests: list[Any] = []

    async def complete(self, request: Any, *, priority: Any = None) -> Any:
        self.requests.append(request)
        if not self._responses:
            return LLMResponse(content="YES\nIt is a ship service.")
        nxt = self._responses.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


def _resp(text: str) -> LLMResponse:
    return LLMResponse(content=text)


def _make_collector(tmp_path: Path) -> EvidenceCollector:
    """Real EvidenceCollector writing under a tmp dir (BF-287, not MagicMock)."""
    return EvidenceCollector(
        runtime=SimpleNamespace(), output_dir=tmp_path, trial_id="default"
    )


def _make_runtime(
    *,
    referent_gate: bool,
    confab_probe: bool,
    ground_before_collaborate: bool = False,
    llm: Any = None,
    collector: Any = None,
    notification_queue: Any = None,
) -> SimpleNamespace:
    cfg = SystemConfig()
    cfg.grounding.referent_gate_enabled = referent_gate
    cfg.grounding.confab_probe_enabled = confab_probe
    cfg.grounding.ground_before_collaborate_enabled = ground_before_collaborate
    runtime = SimpleNamespace(
        config=cfg,
        llm_client=llm,
        evidence_collector=collector,
        notification_queue=notification_queue,
        confab_probe_tasks=set(),
        registry=None,
        callsign_registry=None,
        ward_room=None,
    )
    runtime._confab_probe_scheduling_open = True
    runtime.schedule_confab_probe = (
        lambda probe_factory, *, name="confab-probe":
        ProbOSRuntime.schedule_confab_probe(
            runtime, probe_factory, name=name
        )
    )
    runtime.close_confab_probe_scheduling = (
        lambda: ProbOSRuntime.close_confab_probe_scheduling(runtime)
    )
    return runtime


def _pin_empty_resolvers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every token reads UNRESOLVED with no git subprocess (hermetic)."""
    monkeypatch.setattr(thread_fanout, "build_default_resolvers", lambda **kw: [])


def _obs_files(tmp_path: Path) -> list[Path]:
    return list((tmp_path / "default").glob("OBS-*.yaml"))


# ---------------- 1. divergent -> flag + notify (through the seam) ----------------


async def test_probe_divergent_samples_flag_and_notify(tmp_path, monkeypatch):
    _pin_empty_resolvers(monkeypatch)
    llm = _ScriptedLLM([_resp(f"NO — no record of {_TOKEN} on this ship.")] * 3)
    nq = NotificationQueue()
    runtime = _make_runtime(
        referent_gate=True, confab_probe=True,
        llm=llm, collector=None, notification_queue=nq,
    )
    runtime.config.emergence_collector.output_dir = str(tmp_path)
    assert _wire_emergence_collector(runtime=runtime, config=runtime.config) is True
    assert isinstance(runtime.evidence_collector, EvidenceCollector)
    thread = SimpleNamespace(id="oracle-thread", title="Oracle Health Check")
    # B2 off -> observe returns None; the probe runs as a BACKGROUND task.
    result = await thread_fanout._observe_referent_grounding(runtime, thread, _SEED)
    assert result is None
    assert len(runtime.confab_probe_tasks) == 1
    tasks = list(runtime.confab_probe_tasks)
    await asyncio.gather(*tasks)  # let the best-effort probe complete

    # (1) exactly one CASCADE_CONFAB OBS recorded via the AD-454 pipeline.
    files = _obs_files(tmp_path)
    assert len(files) == 1
    body = files[0].read_text(encoding="utf-8")
    assert "CASCADE-CONFAB" in body
    # (2) one Captain notification naming the token, action_required, no action.
    snap = nq.snapshot()
    assert len(snap) == 1
    assert snap[0]["notification_type"] == "action_required"
    assert _TOKEN in snap[0]["title"]
    assert snap[0]["suggested_action"] is None  # surface-only, no auto-terminate


# ---------------- 2. consistent affirmation -> no flag ----------------


async def test_probe_consistent_affirm_no_flag(tmp_path, monkeypatch):
    _pin_empty_resolvers(monkeypatch)
    llm = _ScriptedLLM(
        [_resp(f"YES — {_TOKEN} is the ship's telemetry service.")] * 3
    )
    collector = _make_collector(tmp_path)
    nq = NotificationQueue()
    runtime = _make_runtime(
        referent_gate=True, confab_probe=True,
        llm=llm, collector=collector, notification_queue=nq,
    )
    thread = SimpleNamespace(id="telemetry-thread", title="Telemetry")
    result = await thread_fanout._observe_referent_grounding(runtime, thread, _SEED)
    assert result is None
    await asyncio.gather(*list(runtime.confab_probe_tasks))
    assert _obs_files(tmp_path) == []
    assert nq.snapshot() == []


# ---------------- 3. context-free: the seed NEVER reaches the LLM ----------------


async def test_probe_context_free_assertion(tmp_path, monkeypatch):
    # NOTE: the build-prompt's example seed used a hex ("e77acec7"), which would
    # trigger a git-HEAD probe. This entity seed keeps the test hermetic (no git)
    # AND meaningful (the probe actually runs) while proving the same property:
    # the distinctive canary + the full seed NEVER reach any LLM request.
    _pin_empty_resolvers(monkeypatch)
    canary = "SECRET_CANARY_TOKEN"
    seed = f"please check node {_TOKEN} now; {canary} context must not leak"
    llm = _ScriptedLLM([_resp("YES — it exists.")] * 3)
    runtime = _make_runtime(referent_gate=True, confab_probe=True, llm=llm)
    thread = SimpleNamespace(id="canary-thread", title="Canary")
    await thread_fanout._observe_referent_grounding(runtime, thread, seed)
    await asyncio.gather(*list(runtime.confab_probe_tasks))

    assert len(llm.requests) >= 2  # the probe actually issued its samples
    for req in llm.requests:
        assert canary not in req.prompt
        assert canary not in req.system_prompt
        assert seed not in req.prompt
        assert seed not in req.system_prompt
    # positive control: only the referent TOKEN reaches the probe.
    assert any(_TOKEN in req.prompt for req in llm.requests)


async def test_probe_enabled_missing_public_scheduler_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_empty_resolvers(monkeypatch)
    runtime = _make_runtime(
        referent_gate=True,
        confab_probe=True,
        llm=_ScriptedLLM([_resp("UNKNOWN")] * 3),
    )
    del runtime.schedule_confab_probe

    with pytest.raises(AttributeError, match="schedule_confab_probe"):
        await thread_fanout._observe_referent_grounding(
            runtime,
            SimpleNamespace(id="missing-scheduler", title="Missing scheduler"),
            _SEED,
        )


async def test_probe_requests_have_unique_ids_and_nonces() -> None:
    llm = _ScriptedLLM([_resp("UNKNOWN")] * 6)

    first = await probe_referent(llm, _TOKEN)
    second = await probe_referent(llm, _TOKEN)

    assert first.usable == 0
    assert second.usable == 0
    assert len(llm.requests) == 6
    assert len({request.id for request in llm.requests}) == 6
    assert len({request.prompt for request in llm.requests}) == 6
    for index, request in enumerate(llm.requests[:3]):
        assert _TOKEN in request.prompt
        assert "Independent sample nonce:" in request.prompt
        assert f":{index}. Do not use the nonce as evidence." in request.prompt
        assert _SEED not in request.prompt
        assert "SECRET_CANARY_TOKEN" not in request.prompt
    assert llm.requests[0].prompt != llm.requests[3].prompt


async def test_real_client_unique_prompts_make_three_transport_calls() -> None:
    cfg = CognitiveConfig(
        llm_base_url="http://probe.invalid/v1",
        llm_api_key="test-key",
    )
    rate_cfg = LLMRateConfig(
        rpm_fast=1000,
        rpm_standard=1000,
        rpm_deep=1000,
        max_concurrent_calls=8,
        interactive_reserved_slots=2,
        max_inflight_per_endpoint=8,
    )
    client = OpenAICompatibleClient(config=cfg, rate_config=rate_cfg)
    transport_prompts: list[str] = []

    async def _fake_call_api(
        request: Any, model: str, http_client: Any, **kwargs: Any
    ) -> LLMResponse:
        transport_prompts.append(request.prompt)
        return LLMResponse(
            content=f"NO — transport response {len(transport_prompts)}",
            model=model,
            tier=request.tier,
            request_id=request.id,
        )

    client._call_api = _fake_call_api
    try:
        result = await probe_referent(client, _TOKEN)
    finally:
        await client.close()

    assert len(transport_prompts) == 3
    assert len(set(transport_prompts)) == 3
    assert result.samples == (
        "NO — transport response 1",
        "NO — transport response 2",
        "NO — transport response 3",
    )
    assert result.usable == 3
    assert result.affirm == 0
    assert result.is_divergent is True


# ---------------- 4. probe failure / abstain -> no false flag ----------------


async def test_probe_failure_no_false_flag(tmp_path):
    # (a) every sample raises -> non-divergent, zero usable.
    llm_all_fail = _ScriptedLLM(
        [RuntimeError("boom"), RuntimeError("boom"), RuntimeError("boom")]
    )
    r_fail = await probe_referent(llm_all_fail, _TOKEN)
    assert r_fail.is_divergent is False
    assert r_fail.usable == 0

    # llm_client=None -> non-divergent (no raise).
    r_none = await probe_referent(None, _TOKEN)
    assert r_none.is_divergent is False
    assert r_none.usable == 0

    # (b) < MIN_USABLE (1 usable denial + 2 exceptions) -> ABSTAIN, no flag.
    llm_abstain = _ScriptedLLM(
        [_resp("NO — no record of it."), RuntimeError("x"), RuntimeError("y")]
    )
    r_abstain = await probe_referent(llm_abstain, _TOKEN)
    assert r_abstain.usable == 1
    assert r_abstain.is_divergent is False  # abstain: only 1 usable sample

    # Through the wiring: a failing probe records NO OBS and posts NO notification.
    collector = _make_collector(tmp_path)
    nq = NotificationQueue()
    runtime = _make_runtime(
        referent_gate=True, confab_probe=True,
        llm=_ScriptedLLM([RuntimeError("boom")] * 3),
        collector=collector, notification_queue=nq,
    )
    await thread_fanout._probe_cascade_confab(
        runtime, SimpleNamespace(id="fail-thread", title="Fail"), _TOKEN
    )
    assert _obs_files(tmp_path) == []
    assert nq.snapshot() == []


# ---------------- 5. _classify_existence unit ----------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("YES", "YES"),
        ("YES.", "YES"),
        ("YES — registered service", "YES"),
        ("YES:\nregistered service", "YES"),
        ("NO", "NO"),
        ("NO — no ship record", "NO"),
        ("UNKNOWN", "UNKNOWN"),
        ("", "UNKNOWN"),
        ("   ", "UNKNOWN"),
        ("Maybe", "UNKNOWN"),
        ("YES NO", "UNKNOWN"),
        ("YES maybe", "UNKNOWN"),
        ("YES — maybe registered", "UNKNOWN"),
        ("YES — no", "UNKNOWN"),
        ("YES — no record exists", "UNKNOWN"),
        ("YES — it is not registered", "UNKNOWN"),
        ("YES — the record is absent", "UNKNOWN"),
        ("YES — oracle_probe is not present in the registry", "UNKNOWN"),
        ("YES — oracle_probe is missing from the registry", "UNKNOWN"),
        ("YES — the record was not found", "UNKNOWN"),
        ("YES — this component is fake", "UNKNOWN"),
        ("YES — this component is fabricated", "UNKNOWN"),
        ("YES — this component is imaginary", "UNKNOWN"),
        ("YES — this component is not real", "UNKNOWN"),
        ("YES — this component is not genuine", "UNKNOWN"),
        ("YES — this service is not active", "UNKNOWN"),
        ("YES — this component is not installed", "UNKNOWN"),
        ("YES — this service is not deployed", "UNKNOWN"),
        ("YES — this service is not verified", "UNKNOWN"),
        ("YES — it was never registered", "UNKNOWN"),
        ("YES — it is not a registered service", "UNKNOWN"),
        ("YES — the ship lacks a record", "UNKNOWN"),
        ("YES — likely registered", "UNKNOWN"),
        ("YES — I think it is registered", "UNKNOWN"),
        ("YES — it may exist", "UNKNOWN"),
        ("NO — it may not exist", "UNKNOWN"),
        ("YES — it might exist", "UNKNOWN"),
        ("NO — it might not exist", "UNKNOWN"),
        ("YES — it could exist", "UNKNOWN"),
        ("NO — it could not exist", "UNKNOWN"),
        ("YES — it would exist", "UNKNOWN"),
        ("NO — it would not exist", "UNKNOWN"),
        ("YES — it possibly exists", "UNKNOWN"),
        ("NO — it possibly does not exist", "UNKNOWN"),
        ("YES — it probably exists", "UNKNOWN"),
        ("NO — it probably does not exist", "UNKNOWN"),
        ("YES — it is not absent", "UNKNOWN"),
        ("NO — it is not absent", "UNKNOWN"),
        ("NO — it is not missing", "UNKNOWN"),
        ("NO — it is not fake", "UNKNOWN"),
        ("NO — it exists as a service", "UNKNOWN"),
        ("NO — oracle_probe exists as a registered ship service", "UNKNOWN"),
        ("NO — oracle_probe is a registered ship service", "UNKNOWN"),
        ("NO — oracle_probe is in the registry", "UNKNOWN"),
        ("NO — the ship has a record", "UNKNOWN"),
        ("NO — no record was found, but oracle_probe exists", "UNKNOWN"),
        ("NO — a verified record exists", "UNKNOWN"),
        ("NO — there is a verified service record", "UNKNOWN"),
        ("NO — this component is real", "UNKNOWN"),
        ("NO — this component is genuine", "UNKNOWN"),
        ("NO — this service is active", "UNKNOWN"),
        ("NO — this component is installed", "UNKNOWN"),
        ("NO — this service is deployed", "UNKNOWN"),
        ("NO — this service is verified", "UNKNOWN"),
        ("NO — I think no ship record", "UNKNOWN"),
        ("NO — this component is fake", "NO"),
        ("NO — this component is fabricated", "NO"),
        ("NO — this component is imaginary", "NO"),
        ("NO — this component is not real", "NO"),
        ("NO — it was never registered", "NO"),
        ("NO — it is not a registered service", "NO"),
        ("NO — the ship lacks a record", "NO"),
        ("NO — oracle_probe is not registered", "NO"),
        ("NO — it does not exist", "NO"),
        ("NO — no record exists", "NO"),
        ("NO — no record was found", "NO"),
        ("NO — no record\nYES", "UNKNOWN"),
        ("It is a memory-tier recall service.", "UNKNOWN"),
        ("I do not have a record of it.", "UNKNOWN"),
        ("I am unaware of it.", "UNKNOWN"),
        ("That identifier is unrecognized.", "UNKNOWN"),
    ],
)
def test_classify_existence(text: str, expected: str) -> None:
    assert _classify_existence(text) == expected


async def test_all_unknown_abstains_without_false_flag() -> None:
    llm = _ScriptedLLM(
        [
            _resp("UNKNOWN"),
            _resp("Maybe it exists."),
            _resp("I do not have a record of it."),
        ]
    )

    result = await probe_referent(llm, _TOKEN)

    assert result.usable == 0
    assert result.affirm == 0
    assert result.affirm_rate == 0.0
    assert result.is_divergent is False
    assert len(result.samples) == 3


async def test_contradictory_and_hedged_batch_abstains() -> None:
    llm = _ScriptedLLM(
        [
            _resp("YES — this component is fake"),
            _resp("NO — this component is real"),
            _resp("NO — I think no ship record"),
        ]
    )

    result = await probe_referent(llm, _TOKEN)

    assert result.usable == 0
    assert result.affirm == 0
    assert result.is_divergent is False


async def test_modal_hedge_batch_abstains_without_divergence() -> None:
    llm = _ScriptedLLM(
        [
            _resp("YES — it may exist"),
            _resp("NO — it might not exist"),
            _resp("YES — it could exist"),
        ]
    )

    result = await probe_referent(llm, _TOKEN)

    assert result.usable == 0
    assert result.affirm == 0
    assert result.is_divergent is False


async def test_double_negation_batch_abstains_without_divergence() -> None:
    llm = _ScriptedLLM(
        [
            _resp("NO — it is not absent"),
            _resp("NO — it is not missing"),
            _resp("YES — it is not fake"),
        ]
    )

    result = await probe_referent(llm, _TOKEN)

    assert result.usable == 0
    assert result.affirm == 0
    assert result.is_divergent is False


async def test_three_explicit_negated_existence_samples_are_divergent() -> None:
    llm = _ScriptedLLM([_resp("NO — it does not exist")] * 3)

    result = await probe_referent(llm, _TOKEN)

    assert result.usable == 3
    assert result.affirm == 0
    assert result.is_divergent is True


async def test_probe_referent_cancellation_propagates() -> None:
    entered = asyncio.Event()

    class _BlockingLLM:
        async def complete(self, request: Any, *, priority: Any = None) -> Any:
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(probe_referent(_BlockingLLM(), _TOKEN))
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_cascade_probe_cancellation_has_no_side_effects(tmp_path: Path) -> None:
    entered = asyncio.Event()

    class _BlockingLLM:
        async def complete(self, request: Any, *, priority: Any = None) -> Any:
            entered.set()
            await asyncio.Event().wait()

    collector = _make_collector(tmp_path)
    notifications = NotificationQueue()
    runtime = _make_runtime(
        referent_gate=True,
        confab_probe=True,
        llm=_BlockingLLM(),
        collector=collector,
        notification_queue=notifications,
    )
    task = asyncio.create_task(
        thread_fanout._probe_cascade_confab(
            runtime,
            SimpleNamespace(id="cancelled-thread", title="Cancelled"),
            _TOKEN,
        )
    )
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert _obs_files(tmp_path) == []
    assert notifications.snapshot() == []


# ---------------- 6. default-OFF byte-identity (GOLDEN) ----------------


async def test_default_off_byte_identical(monkeypatch):
    # referent_gate ON (the AD-1119 observe path runs) but confab_probe AND
    # ground_before_collaborate default OFF -> the seam short-circuits before any
    # probe work: returns None, schedules ZERO tasks, issues ZERO probe requests.
    _pin_empty_resolvers(monkeypatch)
    llm = _ScriptedLLM([_resp("NO — no record.")] * 3)
    runtime = _make_runtime(
        referent_gate=True, confab_probe=False,
        ground_before_collaborate=False, llm=llm,
    )
    thread = SimpleNamespace(id="off-thread", title="Off")
    result = await thread_fanout._observe_referent_grounding(runtime, thread, _SEED)
    assert result is None
    assert len(runtime.confab_probe_tasks) == 0
    assert llm.requests == []  # no probe work when off
    assert runtime.evidence_collector is None


# ---------------- 7. record_observation dedup (real EvidenceCollector) ----------------


async def test_evidence_record_observation_dedup(tmp_path):
    collector = _make_collector(tmp_path)
    o1 = await collector.record_observation(
        behavior_code=BehaviorCode.CASCADE_CONFAB,
        thread_id="T", author_id="T", reasoning="first",
    )
    o2 = await collector.record_observation(
        behavior_code=BehaviorCode.CASCADE_CONFAB,
        thread_id="T", author_id="T", reasoning="second",
    )
    assert o1 is not None
    assert o1.obs_id == "OBS-0001"
    assert o1.behavior_codes == (BehaviorCode.CASCADE_CONFAB,)
    assert o2 is None  # deduped within the window -> reuses the dedup path
    assert len(_obs_files(tmp_path)) == 1  # exactly one OBS written


# ---------------- 8. non-blocking: observe returns before the probe resolves ----------------


async def test_seam_non_blocking(tmp_path, monkeypatch):
    _pin_empty_resolvers(monkeypatch)
    release = asyncio.Event()

    class _SlowLLM:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def complete(self, request: Any, *, priority: Any = None) -> Any:
            self.requests.append(request)
            await release.wait()  # block until the test releases it
            return _resp("NO — no record of it.")

    llm = _SlowLLM()
    collector = _make_collector(tmp_path)
    nq = NotificationQueue()
    # Both B2 and the probe ON: observe RETURNS the AD-1120 cue immediately while
    # the probe is still awaiting the event (proves non-blocking).
    runtime = _make_runtime(
        referent_gate=True, confab_probe=True, ground_before_collaborate=True,
        llm=llm, collector=collector, notification_queue=nq,
    )
    thread = SimpleNamespace(id="slow-thread", title="Slow")
    result = await thread_fanout._observe_referent_grounding(runtime, thread, _SEED)
    assert result is not None  # the AD-1120 honest-absence cue (B2 on)
    assert _TOKEN in result
    assert len(runtime.confab_probe_tasks) == 1
    task = next(iter(runtime.confab_probe_tasks))
    assert not task.done()  # the probe is still pending -> observe did not await it

    release.set()
    await asyncio.gather(*list(runtime.confab_probe_tasks))
    # After the probe completes it flags divergence (3 denials): OBS + notify.
    assert len(_obs_files(tmp_path)) == 1
    assert len(nq.snapshot()) == 1


# ---------------- 9. ProbeResult.affirm_rate ----------------


def test_probe_result_affirm_rate():
    assert ProbeResult(token="x", usable=0, affirm=0, is_divergent=False).affirm_rate == 0.0
    assert ProbeResult(token="x", usable=4, affirm=1, is_divergent=True).affirm_rate == 0.25
    assert ProbeResult(token="x", usable=2, affirm=2, is_divergent=False).affirm_rate == 1.0


# ---------------- 10. config default OFF ----------------


def test_confab_probe_config_default_off():
    assert SystemConfig().grounding.confab_probe_enabled is False
