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
from probos.cognitive.emergence_taxonomy import BehaviorCode
from probos.cognitive.evidence_collector import EvidenceCollector
from probos.config import SystemConfig
from probos.notifications import NotificationQueue
from probos.routers import thread_fanout
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
    exercise the per-sample honest-degrade path). Runs dry -> affirmative default
    (so an under-seeded call never reads as an accidental denial).
    """

    def __init__(self, responses: list[Any] | None = None) -> None:
        self._responses = list(responses or [])
        self.requests: list[Any] = []

    async def complete(self, request: Any, *, priority: Any = None) -> Any:
        self.requests.append(request)
        if not self._responses:
            return LLMResponse(content="It exists as a ship service.")
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
    return SimpleNamespace(
        config=cfg,
        llm_client=llm,
        evidence_collector=collector,
        notification_queue=notification_queue,
        confab_probe_tasks=set(),
        registry=None,
        callsign_registry=None,
        ward_room=None,
    )


def _pin_empty_resolvers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every token reads UNRESOLVED with no git subprocess (hermetic)."""
    monkeypatch.setattr(thread_fanout, "build_default_resolvers", lambda **kw: [])


def _obs_files(tmp_path: Path) -> list[Path]:
    return list((tmp_path / "default").glob("OBS-*.yaml"))


# ---------------- 1. divergent -> flag + notify (through the seam) ----------------


async def test_probe_divergent_samples_flag_and_notify(tmp_path, monkeypatch):
    _pin_empty_resolvers(monkeypatch)
    llm = _ScriptedLLM([_resp(f"No record of {_TOKEN} on this ship.")] * 3)
    collector = _make_collector(tmp_path)
    nq = NotificationQueue()
    runtime = _make_runtime(
        referent_gate=True, confab_probe=True,
        llm=llm, collector=collector, notification_queue=nq,
    )
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
    llm = _ScriptedLLM([_resp(f"{_TOKEN} is the ship's telemetry service.")] * 3)
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
    llm = _ScriptedLLM([_resp("It exists.")] * 3)
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
        [_resp("No record of it."), RuntimeError("x"), RuntimeError("y")]
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


def test_classify_existence():
    denials = [
        f"No record of {_TOKEN} on this ship.",
        "That identifier does not exist.",
        "There is no such entity.",
        "I am not aware of it.",
        "I cannot find it.",
        "There is no component named that.",
        "That is not a real system.",
        "This appears to be a fictional identifier.",
        "unknown identifier",
        "I have no information about it.",
        "I am unable to locate it.",
        "It is not a standard component.",
    ]
    for text in denials:
        assert _classify_existence(text) == "NOT_AFFIRM", text
    affirms = [
        f"{_TOKEN} is the ship's telemetry service.",
        "It is a memory-tier recall service on this vessel.",
        "That maps to the cooperation cluster module.",
    ]
    for text in affirms:
        assert _classify_existence(text) == "AFFIRM", text
    assert _classify_existence("") == "NOT_AFFIRM"
    assert _classify_existence("   ") == "NOT_AFFIRM"


# ---------------- 6. default-OFF byte-identity (GOLDEN) ----------------


async def test_default_off_byte_identical(monkeypatch):
    # referent_gate ON (the AD-1119 observe path runs) but confab_probe AND
    # ground_before_collaborate default OFF -> the seam short-circuits before any
    # probe work: returns None, schedules ZERO tasks, issues ZERO probe requests.
    _pin_empty_resolvers(monkeypatch)
    llm = _ScriptedLLM([_resp("No record.")] * 3)
    runtime = _make_runtime(
        referent_gate=True, confab_probe=False,
        ground_before_collaborate=False, llm=llm,
    )
    thread = SimpleNamespace(id="off-thread", title="Off")
    result = await thread_fanout._observe_referent_grounding(runtime, thread, _SEED)
    assert result is None
    assert len(runtime.confab_probe_tasks) == 0
    assert llm.requests == []  # no probe work when off


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
            return _resp("No record of it.")

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
