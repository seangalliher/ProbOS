"""AD-738g (#1662) S2: the resident Kokoro worker is warmed once, in the background, after boot.

The worker loop is the real ``scripts/kokoro_worker.py`` with the stand-in engine of
``tests/fixtures/fake_kokoro_worker.py``, run as a real ``python -I`` subprocess under the real
``VoiceSynthesisService``. The engine appends one JSON line per call (text, voice, speed, pid) to the
file the key names as its model. The texts ``CRASH``, ``HANG`` and ``SLOW`` make it exit, hang or take
half a second. The only clock read is the bound of ``_until``, which fails a hang, never a slow run.
Nothing here needs kokoro-onnx.

- P1  the warm-up is one real request; the first reply reuses its process; nothing is left behind
- P2  the warm-up and every reply use one worker key; the warm-up's text, voice, speed and timeout
- P3  without an install or a service: degraded, nothing starts
- P4  a failure below the backend never leaves the task
- P5  a worker that dies during the warm-up is retired; the first reply starts a new one
- P6  a warm-up that times out is killed; the first reply starts a new one
- P7  shutdown cancels a running warm-up; no worker process is left; no speech activity
- P8  the warm-up waits its delay; a shutdown during the delay starts nothing
- P9  a reply that arrives during the warm-up waits for it and shares its process
- P10 no warm-up unless speech is on, the backend is kokoro, the switch is on and the service is real
- P11 startup starts the warm-up and returns before the worker answers
- P12 finalize starts it, and shutdown cancels it before the voice service closes (the wiring)
- P13 the switch is on by default and can be turned off
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import logging
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.audio.tts import KokoroBackend, kokoro_backend
from probos.audio.tts.resident import PiperOutcome, VoiceSynthesisService
from probos.config import KokoroTTSConfig, TTSConfig
from probos.startup import finalize as finalize_module
from probos.startup import shutdown as shutdown_module

_REPO = Path(__file__).resolve().parents[1]
FAKE_WORKER = _REPO / "tests" / "fixtures" / "fake_kokoro_worker.py"
_TASK_ATTR = "voice_prewarm_task"
_LABEL = "AD-738g S2 Kokoro prewarm"


def _installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **update: Any) -> tuple[KokoroTTSConfig, Path]:
    """A config naming the fake worker. Its "model" is the engine's record file."""
    record = tmp_path / "engine-calls.jsonl"
    record.write_text("", encoding="utf-8")
    voices = tmp_path / "voices.bin"
    voices.write_bytes(b"")
    monkeypatch.setattr(kokoro_backend, "WORKER_SCRIPT", str(FAKE_WORKER))
    fields: dict[str, Any] = {"python_path": sys.executable, "model_path": str(record), "voices_path": str(voices)}
    cfg = KokoroTTSConfig(**{**fields, **update})
    return cfg, record


def _calls(record: Path) -> list[dict]:
    return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines() if line]


async def _until(predicate: Any, seconds: float = 20.0) -> None:
    """Wait for the fake worker; the bound fails a hang only."""
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "the fake worker did not get there"
        await asyncio.sleep(0.02)


def _prewarm_lines(caplog: pytest.LogCaptureFixture, result: str) -> list[str]:
    return [
        r.getMessage() for r in caplog.records
        if r.getMessage().startswith(f"AD-738g S2: kokoro prewarm result={result} ")
    ]


class _DreamScheduler:
    def __init__(self) -> None:
        self.speech = 0

    def record_speech_activity(self, now: float | None = None) -> bool:
        self.speech += 1
        return True


def _runtime(tts: Any, service: Any) -> SimpleNamespace:
    return SimpleNamespace(config=SimpleNamespace(tts=tts), voice_synthesis=service, dream_scheduler=_DreamScheduler())


async def _stop_task(runtime: SimpleNamespace) -> None:
    await shutdown_module._stop_held_start_service(
        runtime, service_attr=None, start_task_attr=_TASK_ATTR, label=_LABEL,
    )


class _KeyService:
    """Records each request; answers with audio."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, str, float, dict]] = []

    async def synthesize_outcome(self, key, text, timeout, *, fields=None):
        self.calls.append((key, text, timeout, dict(fields or {})))
        return PiperOutcome(b"RIFF", "ok")


class _RaisingService:
    async def synthesize_outcome(self, key, text, timeout, *, fields=None):
        raise RuntimeError("a defect below the backend")


@pytest.fixture
def service():
    svc = VoiceSynthesisService()
    yield svc
    svc.close()


# --- the backend's warm-up --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p1_the_warm_up_is_one_real_request_and_the_first_reply_reuses_its_process(
    service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    cfg, record = _installed(tmp_path, monkeypatch)
    backend = KokoroBackend(cfg, service=service)

    assert await backend.prewarm() is True

    (warm,) = _calls(record)
    assert (warm["text"], warm["voice"], warm["speed"]) == (kokoro_backend.PREWARM_TEXT, "af_heart", 1.0)
    assert service.resident_count == 1
    # Nothing is left behind: the service deleted the WAV, so the worker's directory holds only its stderr log.
    directory = next(iter(service._resident.values()))._dir
    assert directory is not None and sorted(p.name for p in directory.iterdir()) == ["stderr.log"]
    assert len(_prewarm_lines(caplog, "ok")) == 1
    # The warm-up is not a reply: it does not log the per-sentence line the Captain reads.
    assert not any(r.getMessage().startswith("AD-738g: kokoro voice=") for r in caplog.records)

    reply = await backend.synthesize("Hello.")

    assert reply is not None and reply.audio_bytes[:4] == b"RIFF"
    calls = _calls(record)
    assert [call["text"] for call in calls] == [kokoro_backend.PREWARM_TEXT, "Hello."]
    assert calls[0]["pid"] == calls[1]["pid"]
    assert service.resident_count == 1


@pytest.mark.asyncio
async def test_p2_the_warm_up_and_every_reply_use_one_worker_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg, _record = _installed(tmp_path, monkeypatch, voice="af_bella", speed=1.5, timeout_seconds=12.0)
    recorder = _KeyService()
    backend = KokoroBackend(cfg, service=recorder)

    assert await backend.prewarm() is True
    await backend.synthesize("Hello.")
    await backend.synthesize("Hello.", agent_type="pathologist")

    (warm_key, warm_text, warm_timeout, warm_fields), *replies = recorder.calls
    assert [key for key, *_rest in replies] == [warm_key, warm_key]
    assert warm_text == kokoro_backend.PREWARM_TEXT
    assert warm_timeout == 12.0
    assert warm_fields == {"voice": "af_bella", "speed": 1.0}


@pytest.mark.asyncio
async def test_p3_without_an_install_or_a_service_the_warm_up_is_degraded_and_starts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    cfg, _record = _installed(tmp_path, monkeypatch, python_path=str(tmp_path / "no-such-python"))
    recorder = _KeyService()

    assert await KokoroBackend(cfg, service=recorder).prewarm() is False
    assert await KokoroBackend(cfg, service=None).prewarm() is False

    assert recorder.calls == []
    assert len(_prewarm_lines(caplog, "degraded")) == 2


@pytest.mark.asyncio
async def test_p4_a_failure_below_the_backend_never_leaves_the_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    cfg, _record = _installed(tmp_path, monkeypatch)

    assert await KokoroBackend(cfg, service=_RaisingService()).prewarm() is False

    failed = [r for r in caplog.records if r.levelno == logging.WARNING and "kokoro prewarm failed" in r.getMessage()]
    assert len(failed) == 1
    assert len(_prewarm_lines(caplog, "degraded")) == 1


@pytest.mark.asyncio
async def test_p5_a_worker_that_dies_during_the_warm_up_is_retired_and_the_first_reply_starts_a_new_one(
    service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, record = _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(kokoro_backend, "PREWARM_TEXT", "CRASH")
    backend = KokoroBackend(cfg, service=service)

    assert await backend.prewarm() is False
    assert service.resident_count == 0

    reply = await backend.synthesize("Hello.")

    assert reply is not None
    calls = _calls(record)
    assert [call["text"] for call in calls] == ["CRASH", "Hello."]
    assert calls[0]["pid"] != calls[1]["pid"]
    assert service.resident_count == 1


@pytest.mark.asyncio
async def test_p6_a_warm_up_that_times_out_is_killed_and_the_first_reply_starts_a_new_worker(
    service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, record = _installed(tmp_path, monkeypatch, timeout_seconds=1.0)
    monkeypatch.setattr(kokoro_backend, "PREWARM_TEXT", "HANG")

    assert await KokoroBackend(cfg, service=service).prewarm() is False
    assert service.resident_count == 0

    # The timeout is per request, not part of the key, so a 30 s reply uses the same key.
    reply = await KokoroBackend(cfg.model_copy(update={"timeout_seconds": 30.0}), service=service).synthesize("Hello.")

    assert reply is not None
    texts = [call["text"] for call in _calls(record)]
    # A loaded machine may time the warm-up out before the worker read its line, so HANG may be absent.
    assert texts[-1] == "Hello." and set(texts[:-1]) <= {"HANG"}
    assert service.resident_count == 1


# --- startup and shutdown ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p7_shutdown_cancels_a_running_warm_up_and_no_worker_process_is_left(
    service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, record = _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(kokoro_backend, "PREWARM_TEXT", "HANG")
    rt = _runtime(TTSConfig(backend="kokoro", kokoro=cfg), service)

    finalize_module._start_voice_prewarm(runtime=rt, config=rt.config, delay_seconds=0.0)
    task = rt.voice_prewarm_task
    await _until(lambda: bool(_calls(record)))
    proc = next(iter(service._resident.values()))._proc
    assert proc is not None and proc.poll() is None

    await _stop_task(rt)
    shutdown_module._close_voice_synthesis(rt)

    assert task.cancelled() and rt.voice_prewarm_task is None
    assert proc.wait(timeout=10) is not None
    assert service.closed and service.resident_count == 0
    assert rt.dream_scheduler.speech == 0


@pytest.mark.asyncio
async def test_p8_the_warm_up_waits_its_delay_and_a_shutdown_during_the_delay_starts_nothing(
    service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert kokoro_backend.PREWARM_DELAY_SECONDS == 5.0
    cfg, record = _installed(tmp_path, monkeypatch)
    rt = _runtime(TTSConfig(backend="kokoro", kokoro=cfg), service)

    finalize_module._start_voice_prewarm(runtime=rt, config=rt.config)
    task = rt.voice_prewarm_task
    for _ in range(5):
        await asyncio.sleep(0)
    # Without the delay the request would hold a resident worker by now (it is made before the first await).
    assert service.resident_count == 0 and not task.done()

    await _stop_task(rt)

    assert task.cancelled() and rt.voice_prewarm_task is None
    assert service.resident_count == 0 and _calls(record) == []


@pytest.mark.asyncio
async def test_p9_a_reply_that_arrives_during_the_warm_up_waits_for_it_and_shares_its_process(
    service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, record = _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(kokoro_backend, "PREWARM_TEXT", "SLOW")
    backend = KokoroBackend(cfg, service=service)
    warm = asyncio.create_task(backend.prewarm())
    try:
        await _until(lambda: bool(_calls(record)))
        reply = await backend.synthesize("Hello.")
        assert (await warm) is True
    finally:
        warm.cancel()  # a no-op once it has finished

    assert reply is not None
    calls = _calls(record)
    assert [call["text"] for call in calls] == ["SLOW", "Hello."]
    assert calls[0]["pid"] == calls[1]["pid"]
    assert service.resident_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["speech off", "browser", "piper", "switch off", "no tts section", "no service", "not the service"],
)
async def test_p10_no_warm_up_unless_speech_is_on_the_backend_is_kokoro_the_switch_is_on_and_the_service_is_real(
    case: str, service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, record = _installed(tmp_path, monkeypatch)
    tts = {
        "speech off": TTSConfig(enabled=False, backend="kokoro", kokoro=cfg),
        "browser": TTSConfig(backend="browser", kokoro=cfg),
        "piper": TTSConfig(backend="piper", kokoro=cfg),
        "switch off": TTSConfig(backend="kokoro", kokoro=cfg.model_copy(update={"prewarm": False})),
    }.get(case, TTSConfig(backend="kokoro", kokoro=cfg))
    voice = {"no service": None, "not the service": MagicMock()}.get(case, service)
    rt = _runtime(tts, voice)
    if case == "no tts section":
        rt.config = SimpleNamespace()

    finalize_module._start_voice_prewarm(runtime=rt, config=rt.config, delay_seconds=0.0)
    for _ in range(5):
        await asyncio.sleep(0)

    assert rt.voice_prewarm_task is None
    assert service.resident_count == 0 and _calls(record) == []


@pytest.mark.asyncio
async def test_p11_startup_starts_the_warm_up_and_returns_before_the_worker_answers(
    service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert not inspect.iscoroutinefunction(finalize_module._start_voice_prewarm)
    cfg, record = _installed(tmp_path, monkeypatch)
    rt = _runtime(TTSConfig(backend="kokoro", kokoro=cfg), service)

    finalize_module._start_voice_prewarm(runtime=rt, config=rt.config, delay_seconds=0.0)

    task = rt.voice_prewarm_task
    assert isinstance(task, asyncio.Task) and not task.done()
    assert task.get_name() == "ad738g-s2-kokoro-prewarm"
    assert _calls(record) == [] and service.resident_count == 0
    assert (await task) is True
    assert service.resident_count == 1 and rt.dream_scheduler.speech == 0


def _calls_by_name(fn: Any) -> list[ast.Call]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]


def test_p12_finalize_starts_the_warm_up_and_shutdown_cancels_it_before_the_voice_service_closes() -> None:
    # Source scans, as test_bf918_tts_latency.py's shutdown check: the wiring is the property here.
    # P7 to P11 drive the two helpers themselves.
    assert [c.func.id for c in _calls_by_name(finalize_module.finalize_startup)].count("_start_voice_prewarm") == 1

    tree = ast.parse(textwrap.dedent(inspect.getsource(shutdown_module.shutdown)))
    rows = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Tuple)
        and any(isinstance(e, ast.Constant) and e.value == _TASK_ATTR for e in node.elts)
    ]
    assert len(rows) == 1
    assert [e.value for e in rows[0].elts if isinstance(e, ast.Constant)] == [None, _TASK_ATTR, _LABEL]
    closes = [c.lineno for c in _calls_by_name(shutdown_module.shutdown) if c.func.id == "_close_voice_synthesis"]
    assert len(closes) == 1 and rows[0].lineno < closes[0]


# --- config -----------------------------------------------------------------------------------


def test_p13_the_switch_is_on_by_default_and_can_be_turned_off() -> None:
    assert KokoroTTSConfig().prewarm is True
    assert TTSConfig().backend == "browser"  # on by default, and inert on the default backend
    assert TTSConfig.model_validate({"backend": "kokoro", "kokoro": {"prewarm": False}}).kokoro.prewarm is False
    assert list(KokoroTTSConfig().model_dump())[-1] == "prewarm"
