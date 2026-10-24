"""BF-918 (#1626) S2: resident Piper, the voice executor, deferred visemes, stage timings.

Real ``VoiceSynthesisService``, ``PiperWorker``, ``PiperBackend``, routes and store.
Only the processes are fakes (``tests/fixtures/fake_piper.py`` and a rhubarb stand-in);
nothing needs piper, rhubarb or ffmpeg installed, and no test relies on a pid.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
import logging
import subprocess
import tempfile
import textwrap
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.audio.tts import TTSResult
from probos.audio.tts import resident
from probos.audio.tts.piper_backend import PiperBackend
from probos.audio.tts.resident import PiperWorkerKey, VoiceSynthesisService
from probos.avatars import rhubarb_backend
from probos.avatars.rhubarb_backend import VisemeFrame, generate_visemes
from probos.config import AttachmentsConfig, LipSyncConfig, SystemConfig, TTSConfig
from probos.execution.command_env import trusted_command_env
from probos.routers import avatars as avatars_router_mod
from probos.routers import chat as chat_router_mod
from probos.routers.deps import get_runtime
from probos.startup import shutdown as shutdown_module
from tests.fixtures.fake_piper import FakePiperLauncher

_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32


def _key(model: str = "m.onnx") -> PiperWorkerKey:
    return PiperWorkerKey(
        binary="piper", model=model, noise_scale=0.85, length_scale=1.0, noise_w=1.0, sentence_silence=0.35,
    )


async def _until(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


def _held(proc) -> dict[str, bool]:
    """BF-918 A2: what the worker still holds for a fake process; all False once it released everything."""
    out_dir = Path(proc.args[proc.args.index("--output_dir") + 1])
    return {
        "alive": proc.returncode is None,
        "stdin": not proc.stdin.closed,
        "stdout": not proc.stdout.closed,
        "stderr": not proc.kwargs["stderr"].closed,
        "directory": out_dir.exists(),
    }


_NOTHING_HELD = {"alive": False, "stdin": False, "stdout": False, "stderr": False, "directory": False}


@pytest.fixture
def launcher(monkeypatch: pytest.MonkeyPatch):
    def _install(*modes: str, **kwargs):
        fake = FakePiperLauncher(*modes, wav=kwargs.pop("wav", _WAV), **kwargs)
        monkeypatch.setattr(resident.subprocess, "Popen", fake)
        return fake
    return _install


@pytest.fixture
def service():
    svc = VoiceSynthesisService()
    yield svc
    svc.close()


def _voice(tmp_path: Path) -> tuple[Path, Path]:
    binary = tmp_path / "piper"
    binary.write_bytes(b"")
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "v.onnx").write_bytes(b"\x00")
    (voices / "v.onnx.json").write_bytes(b"{}")
    return binary, voices


class _StubBackend:
    name = "piper"

    async def synthesize(self, text, emotion=None, voice_override=None):
        return TTSResult(audio_bytes=_WAV, mime="audio/wav")


class _FakeRhubarb:
    """Stands in for rhubarb's ``subprocess.Popen``; records the thread it ran on."""

    def __init__(self) -> None:
        self.threads: list[str] = []

    def __call__(self, args, *_a, **_kw):
        self.threads.append(threading.current_thread().name)
        cues = b'{"mouthCues": [{"start": 0.0, "end": 0.1, "value": "A"}]}'
        return SimpleNamespace(
            returncode=0,
            communicate=lambda input=None, timeout=None: (cues, b""),
            kill=lambda: None,
            wait=lambda timeout=None: 0,
        )


class _FakeConverter:
    """BF-918 A2: stands in for ``subprocess.Popen`` for ffmpeg and rhubarb.

    An ffmpeg launch writes a WAV to its output path and runs ``on_convert`` on the
    conversion's own thread; any other launch is rhubarb (``self.rhubarb``).
    """

    def __init__(self, on_convert=None) -> None:
        self.converted: list[Path] = []
        self.rhubarb = _FakeRhubarb()
        self._on_convert = on_convert

    def __call__(self, args, *_a, **_kw):
        if args[1] == "-y":  # ffmpeg -y -i <input> ... <output>
            out = Path(args[-1])
            out.write_bytes(_WAV)
            self.converted.append(out)
            if self._on_convert is not None:
                self._on_convert()
            return SimpleNamespace(
                returncode=0,
                communicate=lambda input=None, timeout=None: (None, b""),
                kill=lambda: None,
                wait=lambda timeout=None: 0,
            )
        return self.rhubarb(args, *_a, **_kw)


def _webm_attachment(rt, target: Path, tmp_path: Path) -> str:
    """A browser-captured WebM in the store, with rhubarb and ffmpeg configured (both faked)."""
    rhubarb_bin = tmp_path / "rhubarb"
    rhubarb_bin.write_bytes(b"")
    ffmpeg_bin = tmp_path / "ffmpeg"
    ffmpeg_bin.write_bytes(b"")
    rt.config.lipsync = LipSyncConfig(
        backend="rhubarb", binary_path=str(rhubarb_bin), ffmpeg_binary_path=str(ffmpeg_bin),
    )
    blob = b"webm capture"
    sha = hashlib.sha256(blob).hexdigest()
    (target / f"{sha}.webm").write_bytes(blob)
    return sha


# --- the resident process --------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_resident_process_serves_consecutive_requests(launcher, service) -> None:
    fake = launcher("ok")

    first = await service.synthesize(_key(), "Hello\nworld.", 5.0)
    second = await service.synthesize(_key(), "Again.", 5.0)

    assert first == _WAV and second == _WAV
    assert len(fake.launched) == 1
    proc = fake.launched[0]
    args = proc.args
    assert "--json-input" in args
    assert args[args.index("--model") + 1] == "m.onnx"
    out_dir = Path(args[args.index("--output_dir") + 1])
    assert [r["text"] for r in proc.requests] == ["Hello world.", "Again."]
    assert all(Path(r["output_file"]).parent == out_dir for r in proc.requests)
    assert not any(Path(r["output_file"]).exists() for r in proc.requests)  # read, then removed (BF-282)
    assert proc.kwargs["env"] == trusted_command_env()  # BF-892
    assert proc.kwargs["stdin"] == subprocess.PIPE and proc.kwargs["stdout"] == subprocess.PIPE
    assert proc.killed is False


@pytest.mark.asyncio
async def test_each_prosody_set_gets_its_own_process(launcher, service, tmp_path: Path) -> None:
    """AD-738e-1's per-emotion prosody stays per call: one resident process per prosody set."""
    fake = launcher("ok")
    binary, voices = _voice(tmp_path)
    backend = PiperBackend(binary_path=str(binary), voice_model="v", voices_dir=str(voices), service=service)

    assert await backend.synthesize("Hi.", emotion="excited") is not None
    assert await backend.synthesize("Hi.") is not None
    assert await backend.synthesize("Hi again.", emotion="excited") is not None

    assert len(fake.launched) == 2
    excited, plain = (p.args for p in fake.launched)
    assert excited[excited.index("--noise_scale") + 1] == "0.95"
    assert excited[excited.index("--length_scale") + 1] == "0.92"
    assert plain[plain.index("--noise_scale") + 1] == "0.85"
    assert plain[plain.index("--length_scale") + 1] == "1.0"
    assert len(fake.launched[0].requests) == 2


@pytest.mark.asyncio
async def test_overlapping_requests_share_one_process_one_at_a_time(launcher, service) -> None:
    release = threading.Event()
    fake = launcher("gate", release=release)
    try:
        first = asyncio.create_task(service.synthesize(_key(), "first", 5.0))
        second = asyncio.create_task(service.synthesize(_key(), "second", 5.0))
        await _until(lambda: bool(fake.launched) and bool(fake.launched[0].requests))
        await asyncio.sleep(0.05)
        assert [r["text"] for r in fake.launched[0].requests] == ["first"]  # the second waits its turn
        release.set()
        assert await first == _WAV and await second == _WAV
    finally:
        release.set()
    proc = fake.launched[0]
    assert len(fake.launched) == 1
    assert [r["text"] for r in proc.requests] == ["first", "second"]
    assert proc.overlapped is False


@pytest.mark.asyncio
async def test_a_hung_process_is_killed_at_the_timeout_and_replaced(launcher, service, caplog) -> None:
    caplog.set_level(logging.WARNING)
    fake = launcher("hang", "ok")

    started = time.monotonic()
    assert await service.synthesize(_key(), "hello", 0.2) is None
    assert time.monotonic() - started < 3.0
    assert fake.launched[0].killed is True
    assert "piper timed out" in caplog.text

    assert await service.synthesize(_key(), "hello", 5.0) == _WAV
    assert len(fake.launched) == 2


@pytest.mark.asyncio
async def test_a_crashed_process_degrades_with_its_stderr_and_is_replaced(launcher, service, caplog) -> None:
    caplog.set_level(logging.WARNING)
    fake = launcher("exit", "ok", stderr_bytes=b"piper: bad model")

    assert await service.synthesize(_key(), "hi", 5.0) is None
    assert "piper exit=1" in caplog.text and "piper: bad model" in caplog.text
    assert await service.synthesize(_key(), "hi", 5.0) == _WAV
    assert len(fake.launched) == 2


@pytest.mark.asyncio
async def test_an_empty_wav_degrades(launcher, service, caplog) -> None:
    caplog.set_level(logging.WARNING)
    fake = launcher("empty", "ok")
    assert await service.synthesize(_key(), "hi", 5.0) is None
    assert "0 bytes" in caplog.text
    assert _held(fake.launched[0]) == _NOTHING_HELD  # retired, and released
    # Recovery control (A2): the next request starts a new process and is answered.
    assert await service.synthesize(_key(), "hi", 5.0) == _WAV
    assert len(fake.launched) == 2


@pytest.mark.asyncio
async def test_saturation_refuses_and_degrades_instead_of_queueing(launcher, caplog) -> None:
    caplog.set_level(logging.WARNING)
    release = threading.Event()
    fake = launcher("gate", release=release)
    svc = VoiceSynthesisService(max_in_flight=1)
    try:
        held = asyncio.create_task(svc.synthesize(_key(), "held", 5.0))
        await _until(lambda: bool(fake.launched) and bool(fake.launched[0].requests))
        assert await svc.synthesize(_key("other.onnx"), "refused", 5.0) is None
        assert "voice work refused" in caplog.text
        with svc.admit() as admitted:
            assert admitted is False
        release.set()
        assert await held == _WAV
        with svc.admit() as admitted:
            assert admitted is True
    finally:
        release.set()
        svc.close()


@pytest.mark.asyncio
async def test_the_least_recently_used_idle_process_makes_room(launcher) -> None:
    fake = launcher("ok")
    svc = VoiceSynthesisService(max_resident=2)
    try:
        for model in ("a.onnx", "b.onnx", "a.onnx", "c.onnx"):
            assert await svc.synthesize(_key(model), "x", 5.0) == _WAV
        by_model = {p.args[p.args.index("--model") + 1]: p for p in fake.launched}
        assert sorted(by_model) == ["a.onnx", "b.onnx", "c.onnx"]
        assert by_model["b.onnx"].killed is True  # least recently used
        assert _held(by_model["b.onnx"]) == _NOTHING_HELD  # control for B2: its close ran to the end
        assert by_model["a.onnx"].killed is False
        assert svc.resident_count == 2
    finally:
        svc.close()


@pytest.mark.asyncio
async def test_close_stops_resident_processes_and_refuses_new_work(launcher) -> None:
    fake = launcher("ok")
    svc = VoiceSynthesisService()
    assert await svc.synthesize(_key(), "x", 5.0) == _WAV
    out_dir = Path(fake.launched[0].requests[0]["output_file"]).parent

    svc.close()
    svc.close()  # idempotent

    assert fake.launched[0].killed is True
    assert not out_dir.exists()
    assert _held(fake.launched[0]) == _NOTHING_HELD  # control for B1: an idle worker
    assert svc.closed is True
    assert await svc.synthesize(_key(), "x", 5.0) is None
    with svc.admit() as admitted:
        assert admitted is False


def test_a_closed_worker_refuses_a_request_and_starts_nothing(launcher) -> None:
    """BF-918 A2 (B1): a request that reaches a worker after its close starts no process."""
    fake = launcher("ok")
    worker = resident.PiperWorker(_key())
    other = resident.PiperWorker(_key())
    try:
        worker.close()
        outcome = worker.synthesize_blocking("x", 5.0)
        assert outcome.audio is None and outcome.reason == "closed"
        assert fake.launched == []
        # Positive control: an open worker starts its process and answers.
        assert other.synthesize_blocking("x", 5.0).audio == _WAV
        assert len(fake.launched) == 1
    finally:
        worker.close()
        other.close()


@pytest.mark.asyncio
async def test_close_while_a_request_runs_releases_the_worker_when_it_returns(launcher) -> None:
    """BF-918 A2 (B1): shutdown kills a busy worker, never closes its pipes under the read, and the request releases it."""
    release = threading.Event()
    fake = launcher("gate", release=release)
    svc = VoiceSynthesisService()
    try:
        task = asyncio.create_task(svc.synthesize(_key(), "busy", 5.0))
        await _until(lambda: bool(fake.launched) and bool(fake.launched[0].requests))
        proc = fake.launched[0]

        svc.close()

        assert proc.killed is True
        held = _held(proc)
        assert held["stdin"] and held["stdout"] and held["stderr"] and held["directory"]  # not under the read
        release.set()
        assert await asyncio.wait_for(task, timeout=5.0) == _WAV  # the WAV was made: it is delivered
        assert _held(proc) == _NOTHING_HELD
        assert svc.resident_count == 0
    finally:
        release.set()
        svc.close()


@pytest.mark.asyncio
async def test_close_while_the_process_starts_kills_it_and_releases_everything(launcher, caplog) -> None:
    """BF-918 A2 (B1): shutdown overlaps Popen; the process it could not see yet is killed once it exists."""
    caplog.set_level(logging.WARNING, logger="probos.audio.tts.resident")
    gate = threading.Event()
    fake = launcher("ok", spawn_gate=gate)
    svc = VoiceSynthesisService()
    try:
        task = asyncio.create_task(svc.synthesize(_key(), "starting", 5.0))
        await _until(fake.spawning.is_set)

        svc.close()
        gate.set()

        assert await asyncio.wait_for(task, timeout=5.0) is None
        proc = fake.launched[0]
        assert proc.killed is True and proc.requests == []
        assert _held(proc) == _NOTHING_HELD
        assert not [r for r in caplog.records if r.name == "probos.audio.tts.resident"]  # not a piper failure
    finally:
        gate.set()
        svc.close()


@pytest.mark.asyncio
async def test_a_failed_stderr_open_still_releases_the_worker_directory(launcher, monkeypatch, tmp_path: Path, caplog) -> None:
    """BF-918 A5 (round 2, B finding 1): the worker owns its directory from its creation, so a failed stderr open leaves none behind."""
    caplog.set_level(logging.WARNING, logger="probos.audio.tts.resident")
    fake = launcher("ok")
    temp_dir = tmp_path / "workers"
    temp_dir.mkdir()
    made: list[Path] = []

    def mkdtemp_first_without_stderr(prefix: str = "tmp", **_kwargs) -> str:
        directory = temp_dir / f"{prefix}{len(made)}"
        directory.mkdir()
        if not made:  # the first worker directory only: a directory named stderr.log makes its open fail
            (directory / "stderr.log").mkdir()
        made.append(directory)
        return str(directory)

    monkeypatch.setattr(resident.tempfile, "mkdtemp", mkdtemp_first_without_stderr)
    svc = VoiceSynthesisService()
    try:
        assert await svc.synthesize(_key(), "x", 5.0) is None  # degrades
        assert fake.launched == [] and len(made) == 1  # it failed after the directory, before Popen
        assert "stderr.log" in caplog.text  # control: the logged failure is the stderr open
        assert not made[0].exists()  # the failed request's retirement removed it

        # Recovery control: the next request gets a new directory, starts a process and answers.
        assert await svc.synthesize(_key(), "y", 5.0) == _WAV
        assert len(fake.launched) == 1 and len(made) == 2
        assert made[1].is_dir()  # the resident worker's directory, visible while it lives
    finally:
        svc.close()
        svc.close()  # idempotent
    assert list(temp_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_shutdown_closes_a_retiring_worker_and_the_request_degrades(launcher) -> None:
    """BF-918 A2 (B2): the evicted worker's close is queued behind a busy voice thread when shutdown comes."""
    fake = launcher("ok")
    svc = VoiceSynthesisService(workers=1, max_resident=1)
    release = threading.Event()
    try:
        assert await svc.synthesize(_key("a.onnx"), "x", 5.0) == _WAV
        evicted = fake.launched[0]
        svc.executor.submit(release.wait, 10)  # the only voice thread is busy
        task = asyncio.create_task(svc.synthesize(_key("b.onnx"), "y", 5.0))
        await _until(lambda: evicted.killed)  # evicted, and its close is queued

        svc.close()

        assert _held(evicted) == _NOTHING_HELD  # released by close itself, before the request resumes
        release.set()
        assert await asyncio.gather(task, return_exceptions=True) == [None]
        assert len(fake.launched) == 1
    finally:
        release.set()
        svc.close()


@pytest.mark.asyncio
async def test_a_cancelled_retirement_still_closes_the_worker(launcher) -> None:
    """BF-918 A2 (B2): the caller goes away while the evicted worker's close is queued."""
    fake = launcher("ok")
    svc = VoiceSynthesisService(workers=1, max_resident=1)
    release = threading.Event()
    try:
        assert await svc.synthesize(_key("a.onnx"), "x", 5.0) == _WAV
        evicted = fake.launched[0]
        svc.executor.submit(release.wait, 10)
        task = asyncio.create_task(svc.synthesize(_key("b.onnx"), "y", 5.0))
        await _until(lambda: evicted.killed)

        task.cancel()
        done, _pending = await asyncio.wait({task}, timeout=2.0)

        assert task in done and task.cancelled()  # the caller's own cancellation propagates
        assert _held(evicted) == _NOTHING_HELD
        assert len(fake.launched) == 1
    finally:
        release.set()
        svc.close()


@pytest.mark.asyncio
async def test_shutdown_degrades_a_queued_request_instead_of_cancelling_it(launcher) -> None:
    """BF-918 A2 (B2): shutdown cancels queued voice work; its request answers None, as a refusal does."""
    fake = launcher("ok")
    svc = VoiceSynthesisService(workers=1)
    release = threading.Event()
    try:
        svc.executor.submit(release.wait, 10)
        task = asyncio.create_task(svc.synthesize(_key(), "queued", 5.0))
        await _until(lambda: svc.resident_count == 1)  # claimed, and its request is queued

        svc.close()
        release.set()

        assert await asyncio.gather(task, return_exceptions=True) == [None]
        assert fake.launched == []
    finally:
        release.set()
        svc.close()


@pytest.mark.asyncio
async def test_voice_work_does_not_queue_behind_a_busy_default_pool(launcher, service) -> None:
    """D3: asyncio's default pool fully held by other work (the crew-busy case of 2026-10-22)."""
    fake = launcher("ok")
    loop = asyncio.get_running_loop()
    release = threading.Event()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bf918-busy-default")
    loop.set_default_executor(pool)
    held = loop.run_in_executor(None, release.wait, 30)
    try:
        audio = await asyncio.wait_for(service.synthesize(_key(), "x", 5.0), timeout=3.0)
        assert audio == _WAV
        assert fake.launch_threads[0].startswith("probos-voice")
        assert fake.launched[0].request_threads[0].startswith("probos-voice")
    finally:
        release.set()
        await held
        pool.shutdown(wait=True)
        loop.set_default_executor(ThreadPoolExecutor())


@pytest.mark.asyncio
async def test_rhubarb_runs_on_the_executor_it_is_given(tmp_path: Path, monkeypatch, service) -> None:
    fake = _FakeRhubarb()
    monkeypatch.setattr(rhubarb_backend.subprocess, "Popen", fake)
    binary = tmp_path / "rhubarb"
    binary.write_bytes(b"")
    audio = tmp_path / "a.wav"
    audio.write_bytes(_WAV)

    frames = await generate_visemes(audio, str(binary), executor=service.executor)

    assert frames
    assert fake.threads[0].startswith("probos-voice")


# --- the routes --------------------------------------------------------------------------


@pytest.fixture
async def voice_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, service):
    target = tmp_path / "attachments"
    target.mkdir()
    monkeypatch.setattr("probos.attachments.store._resolve_attachments_dir", lambda configured: target)
    rt = SimpleNamespace(
        config=SimpleNamespace(
            attachments=AttachmentsConfig(attachments_dir=str(target)),
            lipsync=LipSyncConfig(backend="rhubarb"),
            tts=TTSConfig(backend="piper"),
        ),
        voice_synthesis=service,
    )
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
    app = FastAPI()
    app.include_router(avatars_router_mod.router)
    app.dependency_overrides[get_runtime] = lambda: rt
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, rt, target
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


def _stub_rhubarb(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []

    async def _visemes(audio_path, **_kw):
        calls.append(Path(audio_path))
        return [VisemeFrame(time=0.0, duration=0.1, viseme="aa")]

    monkeypatch.setattr("probos.avatars.rhubarb_backend.generate_visemes", _visemes)
    monkeypatch.setattr("probos.audio.tts.select_backend", lambda name, cfg, service=None: _StubBackend())
    return calls


@pytest.mark.asyncio
async def test_a_client_that_does_not_ask_keeps_inline_visemes(voice_client, monkeypatch) -> None:
    client, _rt, _target = voice_client
    calls = _stub_rhubarb(monkeypatch)

    body = (await client.post("/api/avatars/tts", json={"text": "hello"})).json()

    assert body["visemes"] == [{"time": 0.0, "duration": 0.1, "viseme": "aa"}]
    assert body["visemes_deferred"] is False
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_deferred_visemes_come_from_the_lipsync_route_for_the_stored_audio(voice_client, monkeypatch) -> None:
    client, _rt, _target = voice_client
    calls = _stub_rhubarb(monkeypatch)

    spoken = (await client.post("/api/avatars/tts", json={"text": "hello", "defer_visemes": True})).json()
    assert spoken["visemes"] == [] and spoken["visemes_deferred"] is True
    assert calls == []  # rhubarb is off the first-audio path
    sha = spoken["audio_attachment_id"]
    assert sha == hashlib.sha256(_WAV).hexdigest()

    lipsync = (await client.post("/api/avatars/lipsync", json={"attachment_id": sha})).json()

    assert lipsync == {"backend": "rhubarb", "frames": [{"time": 0.0, "duration": 0.1, "viseme": "aa"}]}
    assert len(calls) == 1 and calls[0].name.startswith(sha)


@pytest.mark.asyncio
async def test_the_route_logs_its_stage_timings(voice_client, monkeypatch, caplog) -> None:
    client, _rt, _target = voice_client
    _stub_rhubarb(monkeypatch)
    caplog.set_level(logging.INFO, logger="probos.routers.avatars")

    await client.post("/api/avatars/tts", json={"text": "hello", "defer_visemes": True})

    line = next(r.getMessage() for r in caplog.records if "BF-918: tts route" in r.getMessage())
    for field in ("synth_ms=", "store_ms=", "visemes_ms=", "total_ms=", "visemes=deferred"):
        assert field in line


@pytest.mark.asyncio
async def test_lipsync_route_runs_rhubarb_on_the_voice_executor(voice_client, monkeypatch, tmp_path: Path) -> None:
    client, rt, target = voice_client
    fake = _FakeRhubarb()
    monkeypatch.setattr(rhubarb_backend.subprocess, "Popen", fake)
    binary = tmp_path / "rhubarb"
    binary.write_bytes(b"")
    rt.config.lipsync = LipSyncConfig(backend="rhubarb", binary_path=str(binary))
    sha = hashlib.sha256(_WAV).hexdigest()
    (target / f"{sha}.wav").write_bytes(_WAV)

    body = (await client.post("/api/avatars/lipsync", json={"attachment_id": sha})).json()

    assert body["backend"] == "rhubarb"
    assert fake.threads and fake.threads[0].startswith("probos-voice")


@pytest.mark.asyncio
async def test_lipsync_converts_then_runs_rhubarb_on_the_voice_executor(voice_client, monkeypatch, tmp_path: Path) -> None:
    """Control for B3: nothing overlaps; a captured WebM is converted, read by rhubarb, and its converted file removed."""
    client, rt, target = voice_client
    fake = _FakeConverter()
    monkeypatch.setattr(rhubarb_backend.subprocess, "Popen", fake)
    sha = _webm_attachment(rt, target, tmp_path)

    resp = await client.post("/api/avatars/lipsync", json={"attachment_id": sha})

    assert resp.status_code == 200 and resp.json()["backend"] == "rhubarb"
    assert len(fake.converted) == 1 and not fake.converted[0].exists()
    assert fake.rhubarb.threads and fake.rhubarb.threads[0].startswith("probos-voice")


@pytest.mark.asyncio
async def test_lipsync_degrades_when_the_executor_closes_between_conversion_and_rhubarb(voice_client, monkeypatch, tmp_path: Path) -> None:
    """BF-918 A2 (B3): shutdown closes the voice executor while ffmpeg runs; the rhubarb stage is refused and degrades."""
    client, rt, target = voice_client
    loop = asyncio.get_running_loop()
    voice = rt.voice_synthesis

    def _close_during_conversion() -> None:
        loop.call_soon_threadsafe(voice.close)
        deadline = time.monotonic() + 5.0
        while not voice.closed and time.monotonic() < deadline:
            time.sleep(0.005)

    fake = _FakeConverter(on_convert=_close_during_conversion)
    monkeypatch.setattr(rhubarb_backend.subprocess, "Popen", fake)
    sha = _webm_attachment(rt, target, tmp_path)

    resp = await client.post("/api/avatars/lipsync", json={"attachment_id": sha})

    assert voice.closed is True
    assert resp.status_code == 200
    assert resp.json() == {"backend": "heuristic", "frames": []}
    assert fake.rhubarb.threads == []  # the refused stage started nothing
    assert len(fake.converted) == 1 and not fake.converted[0].exists()


@pytest.mark.asyncio
async def test_lipsync_degrades_and_removes_its_temp_file_when_shutdown_cancels_the_conversion(voice_client, monkeypatch, tmp_path: Path) -> None:
    """BF-918 A2 (B3): the conversion is queued behind a busy voice thread when shutdown cancels it."""
    client, rt, target = voice_client
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp_dir))
    fake = _FakeConverter()
    monkeypatch.setattr(rhubarb_backend.subprocess, "Popen", fake)
    sha = _webm_attachment(rt, target, tmp_path)
    voice = VoiceSynthesisService(workers=1)
    rt.voice_synthesis = voice
    release = threading.Event()
    try:
        voice.executor.submit(release.wait, 10)
        task = asyncio.create_task(client.post("/api/avatars/lipsync", json={"attachment_id": sha}))
        await _until(lambda: any(temp_dir.glob("*.wav")))  # the output file exists; its work is queued

        voice.close()
        release.set()
        (resp,) = await asyncio.gather(task, return_exceptions=True)

        assert not isinstance(resp, BaseException), resp
        assert resp.status_code == 200 and resp.json() == {"backend": "heuristic", "frames": []}
        assert fake.converted == [] and fake.rhubarb.threads == []
        assert list(temp_dir.iterdir()) == []
    finally:
        release.set()
        voice.close()


@pytest.mark.asyncio
async def test_the_route_speaks_through_the_resident_process(voice_client, launcher, tmp_path: Path) -> None:
    client, rt, _target = voice_client
    fake = launcher("ok")
    binary, voices = _voice(tmp_path)
    rt.config.tts = TTSConfig(backend="piper", binary_path=str(binary), voice_model="v", voices_dir=str(voices))
    rt.config.lipsync = LipSyncConfig()  # heuristic: no rhubarb in this case

    for text in ("One.", "Two."):
        body = (await client.post("/api/avatars/tts", json={"text": text, "defer_visemes": True})).json()
        assert body["backend"] == "piper"
        assert body["audio_attachment_id"] == hashlib.sha256(_WAV).hexdigest()

    assert len(fake.launched) == 1


def test_the_runtime_owns_one_voice_service_and_shutdown_closes_it(tmp_path: Path) -> None:
    from probos.runtime import ProbOSRuntime

    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / "data")
    voice = runtime.voice_synthesis
    assert isinstance(voice, VoiceSynthesisService)

    shutdown_module._close_voice_synthesis(runtime)
    assert voice.closed is True
    shutdown_module._close_voice_synthesis(SimpleNamespace())  # no service: nothing to stop, no raise

    tree = ast.parse(textwrap.dedent(inspect.getsource(shutdown_module.shutdown)))
    called = {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_close_voice_synthesis" in called
