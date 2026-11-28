"""AD-738g (#1662) S3a: the Kokoro worker's phoneme-timing file and the voice service that carries it.

The worker loop is the real ``scripts/kokoro_worker.py``; only its engine is a stand-in
(``tests/fixtures/fake_kokoro_worker.py``), in process or as a real ``python -I`` subprocess under
the real ``VoiceSynthesisService``. A record file named ``*.timed.jsonl`` makes the subprocess's
engine report timings, as the ``model-files-v1.1`` export does. Nothing here needs kokoro-onnx.
No assertion reads a clock.
"""

from __future__ import annotations

import dataclasses
import io
import json
import logging
import os
import sys
import wave
from pathlib import Path

import pytest

from probos.audio.tts import KokoroBackend, TTSResult, kokoro_backend, resident
from probos.audio.tts.resident import (
    TIMING_MAX_BYTES,
    TIMING_SUFFIX,
    KokoroWorkerKey,
    PiperOutcome,
    PiperWorker,
    PiperWorkerKey,
    VoiceSynthesisService,
)
from probos.config import KokoroTTSConfig
from tests.fixtures.fake_kokoro_worker import FAKE_PHONEMES, VOICES, FakeEngine, load_worker
from tests.fixtures.fake_piper import FakePiperLauncher

_REPO = Path(__file__).resolve().parents[1]
FAKE_WORKER = _REPO / "tests" / "fixtures" / "fake_kokoro_worker.py"
_FIELDS = {"voice": "af_heart", "speed": 1.0}
_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
worker = load_worker()


def _line(request: dict) -> bytes:
    return json.dumps(request).encode("ascii") + b"\n"


def _nframes(data: bytes) -> int:
    with wave.open(io.BytesIO(data), "rb") as handle:
        return handle.getnframes()


def _key(tmp_path: Path, *, timed: bool) -> tuple[KokoroWorkerKey, Path]:
    record = tmp_path / ("engine-calls.timed.jsonl" if timed else "engine-calls.jsonl")
    record.write_text("", encoding="utf-8")
    voices = tmp_path / "voices.bin"
    voices.write_bytes(b"")
    key = KokoroWorkerKey(
        python=sys.executable, script=str(FAKE_WORKER), model=str(record), voices=str(voices),
        threads=1, default_voice="af_heart",
    )
    return key, record


def _calls(record: Path) -> list[dict]:
    return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines() if line]


def _installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> KokoroTTSConfig:
    model = tmp_path / "model.onnx"
    model.write_bytes(b"\x00")
    voices = tmp_path / "voices.bin"
    voices.write_bytes(b"\x00")
    monkeypatch.setattr(kokoro_backend, "WORKER_SCRIPT", str(FAKE_WORKER))
    return KokoroTTSConfig(python_path=sys.executable, model_path=str(model), voices_path=str(voices))


@pytest.fixture
def service():
    svc = VoiceSynthesisService()
    yield svc
    svc.close()


# --- the worker, in process -------------------------------------------------------------------


def test_w10_a_timed_engine_gets_no_added_pauses_and_the_timing_file_lands_beside_the_wav(tmp_path: Path) -> None:
    engine = FakeEngine(timed=True)
    out = tmp_path / "out.wav"
    stdout = io.BytesIO()
    request = {"text": "Hello.", "output_file": str(out), "voice": "af_heart", "speed": 1.0}

    code = worker.serve(engine, io.BytesIO(_line(request)), stdout, default_voice="af_heart", log=io.StringIO())

    assert code == 0
    assert stdout.getvalue() == str(out).encode("utf-8") + b"\n"
    assert engine.calls == [{
        "text": "Hello.", "voice": "af_heart", "speed": 1.0, "lang": "en-us", "pid": os.getpid(),
        "method": "create_timed", "sentence_pause": 0.0, "clause_pause": 0.0,
    }]
    timing = json.loads((tmp_path / ("out.wav" + TIMING_SUFFIX)).read_text(encoding="ascii"))
    assert list(timing) == ["v", "rate", "samples", "timings"]
    assert (timing["v"], timing["rate"], timing["samples"]) == (1, 24000, _nframes(out.read_bytes()))
    assert [entry["p"] for entry in timing["timings"]] == list(FAKE_PHONEMES)
    assert all(list(entry) == ["p", "s", "e"] for entry in timing["timings"])
    assert timing["timings"][-1]["e"] == pytest.approx(timing["samples"] / 24000)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.wav", "out.wav" + TIMING_SUFFIX]


def test_w11_an_engine_without_timings_is_called_exactly_as_in_s1_and_writes_no_timing_file(tmp_path: Path) -> None:
    engine = FakeEngine()
    out = tmp_path / "out.wav"
    request = {"text": "Hello.", "output_file": str(out), "voice": "af_heart", "speed": 1.0}

    worker.serve(engine, io.BytesIO(_line(request)), io.BytesIO(), default_voice="af_heart", log=io.StringIO())

    assert engine.calls == [{"text": "Hello.", "voice": "af_heart", "speed": 1.0, "lang": "en-us", "pid": os.getpid()}]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.wav"]


def test_w12_a_timed_engine_that_returns_no_timings_writes_no_timing_file(tmp_path: Path) -> None:
    engine = FakeEngine(timed=True)
    out = tmp_path / "out.wav"
    log = io.StringIO()

    assert worker.speak(engine, frozenset(VOICES), "af_heart", {"text": "NOTIMINGS", "output_file": str(out)}, log)

    assert [(c.get("method"), c.get("sentence_pause"), c.get("clause_pause")) for c in engine.calls] == [("create_timed", 0.0, 0.0)]

    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.wav"]
    assert log.getvalue() == ""


def test_w13_a_timing_file_that_cannot_be_written_keeps_the_audio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _disk_full(path, timings, rate, samples):
        raise OSError("disk full")

    monkeypatch.setattr(worker, "write_timing", _disk_full)
    out = tmp_path / "out.wav"
    log = io.StringIO()

    assert worker.speak(FakeEngine(timed=True), frozenset(VOICES), "af_heart", {"text": "Hello.", "output_file": str(out)}, log) is True

    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.wav"]
    assert "AD-738g: no timing file for 6 chars in af_heart: OSError: disk full" in log.getvalue()


def test_w15_an_interrupted_timing_write_leaves_neither_the_file_nor_a_part_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_write_bytes = Path.write_bytes

    def _half(self, data):
        real_write_bytes(self, data[: len(data) // 2])
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_bytes", _half)
    timings = [dataclasses.make_dataclass("T", ["phoneme", "start", "end"])("m", 0.0, 0.05)]

    with pytest.raises(OSError, match="disk full"):
        worker.write_timing(tmp_path / "out.wav", timings, 24000, 1200)

    assert list(tmp_path.iterdir()) == []


# --- the resident service ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r8_the_service_returns_a_timed_workers_file_with_its_wav_and_leaves_neither(service, tmp_path: Path) -> None:
    key, record = _key(tmp_path, timed=True)

    outcome = await service.synthesize_outcome(key, "Good evening, Captain.", 30.0, fields=_FIELDS)

    assert outcome is not None and outcome.reason == "ok" and outcome.audio is not None
    assert outcome.timing is not None
    timing = json.loads(outcome.timing.decode("ascii"))
    assert timing["samples"] == _nframes(outcome.audio)
    assert [entry["p"] for entry in timing["timings"]] == list(FAKE_PHONEMES)
    assert _calls(record)[0]["method"] == "create_timed"
    # The worker's private directory holds only its stderr log once the request returns.
    directory = service._resident[key]._dir
    assert directory is not None and sorted(p.name for p in directory.iterdir()) == ["stderr.log"]


@pytest.mark.asyncio
async def test_r9_an_untimed_worker_gives_no_timing_and_synthesize_still_returns_bytes(service, tmp_path: Path) -> None:
    key, record = _key(tmp_path, timed=False)

    outcome = await service.synthesize_outcome(key, "Hello.", 30.0, fields=_FIELDS)
    wav = await service.synthesize(key, "Hello.", 30.0, fields=_FIELDS)

    assert outcome is not None and outcome.timing is None
    assert isinstance(wav, bytes) and wav[:4] == b"RIFF"
    assert all("method" not in call for call in _calls(record))


def test_r10_the_timing_file_is_read_up_to_its_cap(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    wav = tmp_path / "a.wav"
    beside = tmp_path / ("a.wav" + TIMING_SUFFIX)

    assert PiperWorker._read_timing(wav) is None
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []

    beside.write_bytes(b"x" * TIMING_MAX_BYTES)
    assert PiperWorker._read_timing(wav) == b"x" * TIMING_MAX_BYTES

    beside.write_bytes(b"x" * (TIMING_MAX_BYTES + 1))
    assert PiperWorker._read_timing(wav) is None
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


@pytest.mark.asyncio
async def test_r11_only_a_kokoro_key_carries_timings_and_piper_never_reads_a_file(
    service, monkeypatch: pytest.MonkeyPatch,
) -> None:
    piper = PiperWorkerKey(binary="piper", model="m.onnx", noise_scale=0.85, length_scale=1.0, noise_w=1.0, sentence_silence=0.35)
    kokoro = KokoroWorkerKey(python="py", script="w.py", model="m.onnx", voices="v.bin", threads=4, default_voice="af_heart")
    assert piper.timing_sidecar is False
    assert kokoro.timing_sidecar is True

    reads: list[Path] = []
    monkeypatch.setattr(PiperWorker, "_read_timing", staticmethod(lambda wav: reads.append(wav)))
    monkeypatch.setattr(resident.subprocess, "Popen", FakePiperLauncher("ok", wav=_WAV))

    assert await service.synthesize(piper, "Hello.", 5.0) == _WAV
    assert reads == []


# --- the backend ------------------------------------------------------------------------------


class _TimedService:
    def __init__(self, timing: bytes | None) -> None:
        self.timing = timing

    async def synthesize_outcome(self, key, text, timeout, *, fields=None):
        return PiperOutcome(b"RIFF", "ok", timing=self.timing)


@pytest.mark.asyncio
async def test_b9_the_backend_hands_the_outcomes_timing_to_its_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _installed(tmp_path, monkeypatch)

    timed = await KokoroBackend(cfg, service=_TimedService(b'{"v":1}')).synthesize("Hello.")
    plain = await KokoroBackend(cfg, service=_TimedService(None)).synthesize("Hello.")

    assert timed == TTSResult(audio_bytes=b"RIFF", mime="audio/wav", timing=b'{"v":1}')
    assert plain == TTSResult(audio_bytes=b"RIFF", mime="audio/wav")


def test_b10_tts_result_gains_one_trailing_optional_field() -> None:
    assert [field.name for field in dataclasses.fields(TTSResult)] == ["audio_bytes", "mime", "timing"]
    assert TTSResult(b"x", "audio/wav").timing is None
    assert [field.name for field in dataclasses.fields(PiperOutcome)][-1] == "timing"
    assert PiperOutcome(b"x", "ok").timing is None
