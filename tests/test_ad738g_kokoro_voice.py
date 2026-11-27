"""AD-738g (#1662) S1: a local Kokoro voice behind the TTS backend seam.

Real ``VoiceSynthesisService``, ``KokoroBackend``, routes, store and config. The worker
loop is the real ``scripts/kokoro_worker.py``; only its engine is a stand-in
(``tests/fixtures/fake_kokoro_worker.py``), run as a real ``python -I`` subprocess where a
case says so. Nothing here needs kokoro-onnx. No assertion reads a clock.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import logging
import struct
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.audio.tts import KokoroBackend, PiperBackend, TTSResult, select_backend
from probos.audio.tts import kokoro_backend, resident
from probos.audio.tts.kokoro_backend import KOKORO_VOICES, kokoro_speed
from probos.audio.tts.resident import KokoroWorkerKey, PiperWorkerKey, VoiceSynthesisService
from probos.config import AttachmentsConfig, KokoroTTSConfig, LipSyncConfig, TTSConfig
from probos.execution.command_env import trusted_command_env
from probos.routers import avatars as avatars_router_mod
from probos.routers import chat as chat_router_mod
from probos.routers.deps import get_runtime
from probos.settings.section_registry import get_section
from tests.fixtures.fake_kokoro_worker import FakeEngine, load_worker
from tests.fixtures.fake_piper import FakePiperLauncher

_REPO = Path(__file__).resolve().parents[1]
FAKE_WORKER = _REPO / "tests" / "fixtures" / "fake_kokoro_worker.py"
_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
_FIELDS = {"voice": "bf_emma", "speed": 1.0}
worker = load_worker()


def _piper_key() -> PiperWorkerKey:
    return PiperWorkerKey(binary="piper", model="m.onnx", noise_scale=0.85, length_scale=1.0, noise_w=1.0, sentence_silence=0.35)


def _kokoro_key() -> KokoroWorkerKey:
    return KokoroWorkerKey(python="py", script="w.py", model="m.onnx", voices="v.bin", threads=4, default_voice="af_heart")


def _line(request: dict) -> bytes:
    return json.dumps(request).encode("ascii") + b"\n"


def _wav(data: bytes) -> tuple[int, int, int, bytes]:
    with wave.open(io.BytesIO(data), "rb") as handle:
        return handle.getnchannels(), handle.getsampwidth(), handle.getframerate(), handle.readframes(handle.getnframes())


def _real_key(tmp_path: Path, default_voice: str = "af_heart") -> tuple[KokoroWorkerKey, Path]:
    """A key that runs the real worker loop with the fake engine; the engine logs its calls to ``record``."""
    record = tmp_path / "engine-calls.jsonl"
    record.write_text("", encoding="utf-8")
    voices = tmp_path / "voices.bin"
    voices.write_bytes(b"")
    key = KokoroWorkerKey(
        python=sys.executable, script=str(FAKE_WORKER), model=str(record), voices=str(voices),
        threads=1, default_voice=default_voice,
    )
    return key, record


def _calls(record: Path) -> list[dict]:
    return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture
def launcher(monkeypatch: pytest.MonkeyPatch):
    def _install(*modes: str):
        fake = FakePiperLauncher(*modes, wav=_WAV)
        monkeypatch.setattr(resident.subprocess, "Popen", fake)
        return fake
    return _install


@pytest.fixture
def service():
    svc = VoiceSynthesisService()
    yield svc
    svc.close()


class _RecordingService:
    """Stands in for the service where a case asks only what the backend sends."""

    def __init__(self, wav: bytes | None = b"RIFF") -> None:
        self.wav = wav
        self.calls: list[tuple] = []

    async def synthesize(self, key, text, timeout, *, fields=None):
        self.calls.append((key, text, timeout, dict(fields or {})))
        return self.wav


def _installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides) -> KokoroTTSConfig:
    model = tmp_path / "model.onnx"
    model.write_bytes(b"\x00")
    voices = tmp_path / "voices.bin"
    voices.write_bytes(b"\x00")
    monkeypatch.setattr(kokoro_backend, "WORKER_SCRIPT", str(FAKE_WORKER))
    values = {"python_path": sys.executable, "model_path": str(model), "voices_path": str(voices)}
    values.update(overrides)
    return KokoroTTSConfig(**values)


# --- the resident service: request fields, and a Kokoro worker that stays resident ---------


@pytest.mark.asyncio
async def test_r1_a_piper_line_without_fields_has_exactly_text_and_output_file(launcher, service) -> None:
    fake = launcher("ok")

    assert await service.synthesize(_piper_key(), "Hello\nthere", 5.0) == _WAV

    request = fake.launched[0].requests[0]
    assert list(request) == ["text", "output_file"]
    assert request["text"] == "Hello there"


@pytest.mark.asyncio
async def test_r2_fields_follow_the_line_and_never_replace_text_or_output_file(launcher, service) -> None:
    fake = launcher("ok")

    await service.synthesize(
        _kokoro_key(), "Hi.", 5.0,
        fields={"text": "evil", "output_file": "x", "voice": "bf_emma", "speed": 1.25},
    )

    request = fake.launched[0].requests[0]
    assert list(request) == ["text", "output_file", "voice", "speed"]
    assert request["text"] == "Hi."
    assert request["output_file"] != "x"
    assert request["voice"] == "bf_emma"
    assert request["speed"] == 1.25


@pytest.mark.asyncio
async def test_r3_a_kokoro_worker_that_answers_without_audio_stays_resident(
    launcher, service, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    fake = launcher("empty")

    assert await service.synthesize(_kokoro_key(), "Hi.", 5.0, fields=_FIELDS) is None
    assert await service.synthesize(_kokoro_key(), "Hi.", 5.0, fields=_FIELDS) is None

    assert len(fake.launched) == 1
    assert fake.launched[0].returncode is None
    assert service.resident_count == 1
    assert "kokoro produced 0 bytes" in caplog.text


@pytest.mark.asyncio
async def test_r4_a_kokoro_key_launches_the_isolated_worker_with_the_trusted_environment(
    launcher, service, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="probos.audio.tts")
    fake = launcher("ok")

    await service.synthesize(_kokoro_key(), "Hi.", 5.0, fields=_FIELDS)

    assert len(fake.launched) == 1
    proc = fake.launched[0]
    assert proc.args == [
        "py", "-I", "w.py", "--model", "m.onnx", "--voices", "v.bin", "--threads", "4", "--default-voice", "af_heart",
    ]
    assert proc.kwargs["env"] == trusted_command_env()
    assert "BF-918: resident kokoro started (voice=m)" in caplog.text


# --- the worker loop in process ---------------------------------------------------------------


def test_w1_the_worker_writes_a_24khz_mono_16bit_wav_and_prints_its_path(tmp_path: Path) -> None:
    import numpy

    class _ToneEngine:
        def get_voices(self) -> list[str]:
            return ["af_heart"]

        def create(self, text, voice, speed=1.0, lang="en-us", **_kwargs):
            return numpy.array([0.5, 1.5, -1.5], dtype=numpy.float32), 24000

    out = tmp_path / "out.wav"
    stdout = io.BytesIO()
    request = {"text": "Hi.", "output_file": str(out), "voice": "af_heart", "speed": 1.0}

    code = worker.serve(_ToneEngine(), io.BytesIO(_line(request)), stdout, default_voice="af_heart", log=io.StringIO())

    assert code == 0
    assert stdout.getvalue() == str(out).encode("utf-8") + b"\n"
    channels, width, rate, frames = _wav(out.read_bytes())
    assert (channels, width, rate) == (1, 2, 24000)
    # 0.5 truncates to 16383; samples beyond +-1.0 clip to +-32767
    assert struct.unpack("<3h", frames) == (16383, 32767, -32767)
    assert not (tmp_path / (out.name + ".part")).exists()


def test_w9_an_interrupted_write_leaves_neither_the_output_nor_a_part_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "out.wav"
    real_writeframes = wave.Wave_write.writeframes

    def _disk_full(self, data):
        real_writeframes(self, data[:2])  # one frame reaches the disk, then the write fails
        raise OSError("disk full")

    monkeypatch.setattr(wave.Wave_write, "writeframes", _disk_full)

    with pytest.raises(OSError, match="disk full"):
        worker.write_wav(out, [0.5, -0.5, 0.25], 24000)

    # The service reads output_file once the path comes back: it must never hold a partial WAV.
    assert not out.exists()
    assert not (tmp_path / (out.name + ".part")).exists()


def test_w2_the_language_follows_the_voice_prefix(tmp_path: Path) -> None:
    engine = FakeEngine()
    lines = b"".join(
        _line({"text": "Hello.", "output_file": str(tmp_path / f"{voice}.wav"), "voice": voice, "speed": 1.0})
        for voice in ("bf_emma", "af_heart")
    )

    code = worker.serve(engine, io.BytesIO(lines), io.BytesIO(), default_voice="af_heart", log=io.StringIO())

    assert code == 0
    assert [c["lang"] for c in engine.calls] == ["en-gb", "en-us"]


def test_w3_a_voice_the_file_lacks_is_spoken_in_the_default_voice(tmp_path: Path) -> None:
    engine = FakeEngine()
    out = tmp_path / "out.wav"
    log = io.StringIO()
    request = {"text": "Hello.", "output_file": str(out), "voice": "zz_nobody", "speed": 1.0}

    code = worker.serve(engine, io.BytesIO(_line(request)), io.BytesIO(), default_voice="af_heart", log=log)

    assert code == 0
    assert engine.calls[0]["voice"] == "af_heart"
    assert out.is_file()
    assert "'zz_nobody' is not in the voices file" in log.getvalue()


def test_w4_an_engine_error_is_answered_with_the_path_and_no_file_and_the_loop_continues(tmp_path: Path) -> None:
    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    lines = (
        _line({"text": "   ", "output_file": str(first), "voice": "af_heart", "speed": 1.0})
        + _line({"text": "Hello.", "output_file": str(second), "voice": "af_heart", "speed": 1.0})
    )
    stdout = io.BytesIO()
    log = io.StringIO()

    code = worker.serve(FakeEngine(), io.BytesIO(lines), stdout, default_voice="af_heart", log=log)

    assert code == 0
    assert stdout.getvalue() == str(first).encode("utf-8") + b"\n" + str(second).encode("utf-8") + b"\n"
    assert not first.exists()
    assert second.exists()
    assert "no audio for 3 chars" in log.getvalue()


def test_w5_a_default_voice_the_file_lacks_refuses_to_start(tmp_path: Path) -> None:
    engine = FakeEngine(voices=("af_bella",))
    stdout = io.BytesIO()
    log = io.StringIO()
    request = {"text": "Hello.", "output_file": str(tmp_path / "out.wav"), "voice": "af_bella", "speed": 1.0}

    code = worker.serve(engine, io.BytesIO(_line(request)), stdout, default_voice="af_heart", log=log)

    assert code == 2
    assert stdout.getvalue() == b""
    assert engine.calls == []
    assert "refusing to start" in log.getvalue()


def test_w6_an_unreadable_line_ends_the_worker(tmp_path: Path) -> None:
    engine = FakeEngine()
    stdout = io.BytesIO()
    valid = _line({"text": "Hello.", "output_file": str(tmp_path / "out.wav"), "voice": "af_heart", "speed": 1.0})

    code = worker.serve(engine, io.BytesIO(b"not json\n" + valid), stdout, default_voice="af_heart", log=io.StringIO())

    assert code == 3
    assert stdout.getvalue() == b""
    assert engine.calls == []


def test_w7_main_keeps_library_prints_off_the_protocol_pipe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "out.wav"
    request = {"text": "CHATTER", "output_file": str(out), "voice": "af_heart"}
    stdin = io.TextIOWrapper(io.BytesIO(_line(request)), encoding="ascii")
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    code = worker.main(
        ["--model", "m", "--voices", "v", "--default-voice", "af_heart"],
        engine_factory=lambda args: FakeEngine(),
    )

    assert code == 0
    assert stdout.buffer.getvalue() == str(out).encode("utf-8") + b"\n"
    assert "library chatter on stdout" in stderr.getvalue()


def test_w8_the_worker_imports_only_the_stdlib_and_numpy_at_module_level_and_src_never_imports_the_engine() -> None:
    def imported(node: ast.AST) -> list[str]:
        names: list[str] = []
        for child in ast.walk(node):
            if isinstance(child, ast.Import):
                names.extend(alias.name.split(".")[0] for alias in child.names)
            elif isinstance(child, ast.ImportFrom) and child.level == 0 and child.module:
                names.append(child.module.split(".")[0])
        return names

    tree = ast.parse((_REPO / "scripts" / "kokoro_worker.py").read_bytes())
    loaders = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "load_engine"]
    assert len(loaders) == 1
    module_level = {
        name
        for statement in tree.body
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        for name in imported(statement)
    }
    assert module_level
    assert module_level <= {"__future__", "argparse", "json", "os", "sys", "wave", "pathlib", "typing", "numpy"}

    engine = {"kokoro_onnx", "onnxruntime"}
    in_file = sorted(name for name in imported(tree) if name in engine)
    in_loader = sorted(name for name in imported(loaders[0]) if name in engine)
    assert "kokoro_onnx" in in_loader
    assert in_file == in_loader

    banned = {"kokoro_onnx", "onnxruntime", "phonemizer", "espeakng_loader"}
    sources = sorted((_REPO / "src" / "probos").rglob("*.py"))
    assert _REPO / "src" / "probos" / "audio" / "tts" / "resident.py" in sources
    offenders = [
        path.relative_to(_REPO).as_posix()
        for path in sources
        if banned & set(imported(ast.parse(path.read_bytes())))
    ]
    assert offenders == []


# --- the real worker loop, run as a subprocess of the resident service -------------------------


@pytest.mark.asyncio
async def test_r5_the_real_worker_loop_answers_the_resident_service_and_stays_one_process(
    service, tmp_path: Path,
) -> None:
    key, record = _real_key(tmp_path)

    first = await service.synthesize(key, "Good evening, Captain.", 30.0, fields={"voice": "bf_emma", "speed": 1.0})
    second = await service.synthesize(key, "Status report.", 30.0, fields={"voice": "am_liam", "speed": 0.9})

    assert first is not None and second is not None
    assert _wav(first)[:3] == (1, 2, 24000)
    assert _wav(second)[:3] == (1, 2, 24000)
    calls = _calls(record)
    assert [(c["text"], c["voice"], c["lang"], c["speed"]) for c in calls] == [
        ("Good evening, Captain.", "bf_emma", "en-gb", 1.0),
        ("Status report.", "am_liam", "en-us", 0.9),
    ]
    assert calls[0]["pid"] == calls[1]["pid"]


@pytest.mark.asyncio
async def test_r6_a_sentence_with_no_phonemes_degrades_and_the_process_stays(service, tmp_path: Path) -> None:
    key, record = _real_key(tmp_path)

    assert await service.synthesize(key, "   ", 30.0, fields=_FIELDS) is None
    spoken = await service.synthesize(key, "Hello.", 30.0, fields=_FIELDS)

    assert spoken is not None
    assert _wav(spoken)[:3] == (1, 2, 24000)
    calls = _calls(record)
    assert len(calls) == 2
    assert calls[0]["pid"] == calls[1]["pid"]


@pytest.mark.asyncio
async def test_r7_a_worker_that_refuses_to_start_degrades(
    service, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    key, record = _real_key(tmp_path, default_voice="zz_nobody")

    assert await service.synthesize(key, "Hello.", 30.0, fields=_FIELDS) is None

    assert _calls(record) == []
    # The worker may exit before or after the service writes the line; either way one WARNING names kokoro.
    assert any(r.levelno == logging.WARNING and "kokoro" in r.getMessage() for r in caplog.records)


# --- the backend ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b1_the_backend_sends_the_configured_voice_and_speed_and_logs_the_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="probos.audio.tts")
    cfg = _installed(tmp_path, monkeypatch)
    svc = _RecordingService()

    result = await KokoroBackend(cfg, service=svc).synthesize("Hello.")

    assert result == TTSResult(audio_bytes=b"RIFF", mime="audio/wav")
    assert len(svc.calls) == 1
    key, _text, timeout, fields = svc.calls[0]
    assert key == KokoroWorkerKey(
        python=str(Path(sys.executable).resolve()),
        script=str(FAKE_WORKER.resolve()),
        model=str((tmp_path / "model.onnx").resolve()),
        voices=str((tmp_path / "voices.bin").resolve()),
        threads=4,
        default_voice="af_heart",
    )
    assert timeout == 30.0
    assert fields == {"voice": "af_heart", "speed": 1.0}
    assert "AD-738g: kokoro voice=af_heart speed=1.00 chars=6" in caplog.text
    assert "result=ok" in caplog.text


@pytest.mark.asyncio
async def test_b2_a_catalogue_override_wins_and_a_foreign_name_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _installed(tmp_path, monkeypatch, voice="am_liam")
    svc = _RecordingService()
    backend = KokoroBackend(cfg, service=svc)

    await backend.synthesize("Hi.", voice_override="bf_emma")
    await backend.synthesize("Hi.", voice_override="en_US-ryan-medium")
    await backend.synthesize("Hi.", voice_override=None)

    assert [call[3]["voice"] for call in svc.calls] == ["bf_emma", "am_liam", "am_liam"]


@pytest.mark.asyncio
async def test_b3_emotion_scales_the_speed_within_kokoros_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert kokoro_speed(1.0, None) == 1.0
    assert kokoro_speed(1.0, "concerned") == pytest.approx(1 / 1.05)
    assert kokoro_speed(2.0, "excited") == 2.0
    assert kokoro_speed(0.5, "concerned") == 0.5

    cfg = _installed(tmp_path, monkeypatch, speed=2.0)
    svc = _RecordingService()

    await KokoroBackend(cfg, service=svc).synthesize("Hi.", emotion="excited")

    assert svc.calls[0][3]["speed"] == 2.0


@pytest.mark.asyncio
async def test_b4_a_missing_install_degrades_without_calling_the_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    svc = _RecordingService()

    cfg = _installed(tmp_path, monkeypatch, python_path=str(tmp_path / "absent"))
    assert await KokoroBackend(cfg, service=svc).synthesize("Hi.") is None
    assert svc.calls == []
    assert "kokoro is not installed" in caplog.text
    assert "scripts/kokoro-fetch.ps1" in caplog.text

    cfg = _installed(tmp_path, monkeypatch, model_path=str(tmp_path / "absent.onnx"))
    assert await KokoroBackend(cfg, service=svc).synthesize("Hi.") is None
    assert svc.calls == []


@pytest.mark.asyncio
async def test_b5_blank_text_and_a_missing_service_degrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="probos.audio.tts")
    cfg = _installed(tmp_path, monkeypatch)
    svc = _RecordingService()

    assert await KokoroBackend(cfg, service=svc).synthesize("   ") is None
    assert svc.calls == []

    assert await KokoroBackend(cfg, service=None).synthesize("Hi.") is None
    assert "no voice synthesis service" in caplog.text


def test_b6_the_catalogue_is_the_28_english_voices() -> None:
    import re

    assert KOKORO_VOICES == {
        "af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica", "af_kore", "af_nicole",
        "af_nova", "af_river", "af_sarah", "af_sky",
        "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael", "am_onyx",
        "am_puck", "am_santa",
        "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
        "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
    }
    assert len(KOKORO_VOICES) == 28
    assert all(re.fullmatch(r"[ab][fm]_[a-z]+", voice) for voice in KOKORO_VOICES)


@pytest.mark.asyncio
async def test_b7_every_attempt_logs_one_result_line_even_when_it_degrades_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="probos.audio.tts")
    svc = _RecordingService()

    missing = _installed(tmp_path, monkeypatch, model_path=str(tmp_path / "absent.onnx"))
    assert await KokoroBackend(missing, service=svc).synthesize("Hi.") is None
    assert await KokoroBackend(_installed(tmp_path, monkeypatch), service=None).synthesize("Hi.") is None
    assert await KokoroBackend(_installed(tmp_path, monkeypatch), service=svc).synthesize("   ") is None

    lines = [
        record.getMessage() for record in caplog.records
        if record.levelno == logging.INFO and record.getMessage().startswith("AD-738g: kokoro voice=")
    ]
    assert len(lines) == 2  # one per attempt (D10); blank text is not an attempt
    for line in lines:
        assert "voice=af_heart speed=1.00 chars=3" in line
        assert "result=degraded role=-" in line
    assert svc.calls == []


@pytest.mark.asyncio
async def test_b8_a_path_that_cannot_be_resolved_degrades_and_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="probos.audio.tts")
    svc = _RecordingService()
    installed = _installed(tmp_path, monkeypatch)

    # C4: the config refuses a NUL; model_copy skips validation, as a config built in code can.
    for name in ("python_path", "model_path", "voices_path"):
        cfg = installed.model_copy(update={name: "tools/kokoro/a\x00b"})
        assert await KokoroBackend(cfg, service=svc).synthesize("Hi.") is None
    assert svc.calls == []
    assert caplog.text.count("result=degraded") == 3

    def _unrepresentable(configured: str) -> Path:
        raise OSError(22, "The filename, directory name, or volume label syntax is incorrect")

    monkeypatch.setattr(kokoro_backend, "anchor_install_path", _unrepresentable)
    assert await KokoroBackend(installed, service=svc).synthesize("Hi.") is None
    assert svc.calls == []
    assert "a tts.kokoro path cannot be resolved (OSError" in caplog.text
    assert caplog.text.count("result=degraded") == 4


# --- config, registry, selection --------------------------------------------------------------


def test_c1_defaults_stay_browser_and_kokoro_defaults_are_the_measured_ones() -> None:
    assert TTSConfig().backend == "browser"
    assert TTSConfig().kokoro == KokoroTTSConfig()

    cfg = KokoroTTSConfig()
    assert cfg.voice == "af_heart"
    assert cfg.speed == 1.0
    assert cfg.threads == 4
    assert cfg.timeout_seconds == 30.0
    assert cfg.python_path == "tools/kokoro/venv/Scripts/python"
    assert cfg.model_path == "tools/kokoro/kokoro-v1.0.onnx"
    assert cfg.voices_path == "tools/kokoro/voices-v1.0.bin"


def test_c2_kokoro_config_rejects_values_the_engine_cannot_take() -> None:
    rejected = (
        {"speed": 0.49}, {"speed": 2.01}, {"threads": 0}, {"threads": 17},
        {"timeout_seconds": 0.0}, {"voice": "zz_nobody"}, {"voice": "jf_alpha"},
    )
    for values in rejected:
        with pytest.raises(ValueError):
            KokoroTTSConfig(**values)

    assert KokoroTTSConfig(speed=0.5).speed == 0.5
    assert KokoroTTSConfig(speed=2.0).speed == 2.0
    assert KokoroTTSConfig(threads=1).threads == 1
    assert KokoroTTSConfig(threads=16).threads == 16


def test_c3_the_settings_registry_offers_kokoro() -> None:
    section = get_section("voice")
    assert section is not None

    backend = next(field for field in section.fields if field.field_id == "tts.backend")

    assert backend.enum_values == ("browser", "piper", "kokoro")


def test_c4_a_timeout_the_timer_cannot_take_and_a_path_no_file_can_have_are_refused() -> None:
    import threading

    # threading.Timer raises OverflowError past TIMEOUT_MAX (4294967.0 on Windows) inside its
    # own thread, so the deadline would silently never fire; infinity and NaN never fire either.
    assert 600.0 <= threading.TIMEOUT_MAX
    for value in (float("inf"), float("nan"), 600.01, 4294968.0, 1e30):
        with pytest.raises(ValueError):
            KokoroTTSConfig(timeout_seconds=value)
    assert KokoroTTSConfig(timeout_seconds=600.0).timeout_seconds == 600.0

    for name in ("python_path", "model_path", "voices_path"):
        for value in ("tools/kokoro/a\x00b", "", "   "):
            with pytest.raises(ValueError):
                KokoroTTSConfig(**{name: value})


@pytest.mark.asyncio
async def test_s1_select_backend_builds_kokoro_with_the_runtime_service(
    service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = select_backend("kokoro", TTSConfig(backend="kokoro"), service=service)

    assert isinstance(backend, KokoroBackend)
    assert backend.name == "kokoro"
    assert isinstance(select_backend("piper", TTSConfig(backend="piper")), PiperBackend)
    # A1: the backend speaks through the service it was given (a dropped injection degrades).
    recording = _RecordingService()
    built = select_backend(
        "kokoro", TTSConfig(backend="kokoro", kokoro=_installed(tmp_path, monkeypatch)), service=recording,
    )
    assert await built.synthesize("Hi.") == TTSResult(audio_bytes=b"RIFF", mime="audio/wav")
    assert len(recording.calls) == 1


# --- the route --------------------------------------------------------------------------------


@pytest.fixture
async def kokoro_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, service):
    target = tmp_path / "attachments"
    target.mkdir()
    monkeypatch.setattr("probos.attachments.store._resolve_attachments_dir", lambda configured: target)
    rt = SimpleNamespace(
        config=SimpleNamespace(
            attachments=AttachmentsConfig(attachments_dir=str(target)),
            lipsync=LipSyncConfig(),
            tts=TTSConfig(),
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


@pytest.mark.asyncio
async def test_t1_post_tts_speaks_kokoro_through_the_real_worker_loop(
    kokoro_client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    client, rt, _target = kokoro_client
    key, record = _real_key(tmp_path)
    monkeypatch.setattr(kokoro_backend, "WORKER_SCRIPT", str(FAKE_WORKER))
    rt.config.tts = TTSConfig(
        backend="kokoro",
        kokoro=KokoroTTSConfig(
            python_path=sys.executable, model_path=key.model, voices_path=key.voices, voice="bm_fable",
        ),
    )

    response = await client.post(
        "/api/avatars/tts",
        json={"text": "Good evening, Captain.", "emotion": "concerned", "defer_visemes": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "kokoro"
    assert body["mime"] == "audio/wav"
    assert body["duration_ms"] == 200  # bm_fable is the fake's 4th voice: 4800 frames at 24 kHz
    stored = await chat_router_mod._get_attachment_store(rt).get_path(body["audio_attachment_id"])
    data = Path(stored).read_bytes()
    assert hashlib.sha256(data).hexdigest() == body["audio_attachment_id"]
    assert _wav(data)[:3] == (1, 2, 24000)
    calls = _calls(record)
    assert len(calls) == 1
    assert calls[0]["voice"] == "bm_fable"
    assert calls[0]["lang"] == "en-gb"
    assert calls[0]["speed"] == pytest.approx(1 / 1.05)


@pytest.mark.asyncio
async def test_t2_the_default_config_speaks_in_the_browser_and_starts_no_process(kokoro_client, launcher) -> None:
    client, _rt, _target = kokoro_client
    fake = launcher("ok")

    body = (await client.post("/api/avatars/tts", json={"text": "Hello.", "defer_visemes": True})).json()

    assert body["backend"] == "disabled"
    assert body["audio_attachment_id"] is None
    assert fake.launched == []


@pytest.mark.asyncio
async def test_t3_tts_status_reports_kokoro(kokoro_client) -> None:
    client, rt, _target = kokoro_client
    rt.config.tts = TTSConfig(backend="kokoro", sentence_pipelining_enabled=True)

    response = await client.get("/api/avatars/tts/status")

    assert response.status_code == 200
    assert response.json() == {"enabled": True, "backend": "kokoro", "sentence_pipelining_enabled": True}
