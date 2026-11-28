"""AD-738g (#1662) S3a: lip-sync frames from the synthesizer's timings, behind lipsync.backend "synthesizer".

Real table, check, route, store, config and registry. The route cases run the real
``scripts/kokoro_worker.py`` loop with the stand-in engine of ``tests/fixtures/fake_kokoro_worker.py``
as a real ``python -I`` subprocess under the real ``VoiceSynthesisService``; a record file named
``*.timed.jsonl`` is a model that reports durations. Rhubarb is a stub that records each call.
No assertion reads a clock.
"""

from __future__ import annotations

import ast
import io
import json
import logging
import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.audio.tts import kokoro_backend, resident
from probos.audio.tts.resident import VoiceSynthesisService
from probos.avatars import phoneme_visemes
from probos.avatars.phoneme_visemes import PHONEME_VISEMES, frames_from_timing
from probos.avatars.rhubarb_backend import OculusViseme, VisemeFrame
from probos.config import AttachmentsConfig, KokoroTTSConfig, LipSyncConfig, TTSConfig
from probos.routers import avatars as avatars_router_mod
from probos.routers import chat as chat_router_mod
from probos.routers.deps import get_runtime
from probos.settings.section_registry import get_section
from tests.fixtures.fake_kokoro_worker import load_worker

_REPO = Path(__file__).resolve().parents[1]
FAKE_WORKER = _REPO / "tests" / "fixtures" / "fake_kokoro_worker.py"
RATE = 24000
_RHUBARB = [{"time": 0.0, "duration": 0.1, "viseme": "aa"}]

#: kokoro-onnx 0.6.1's vocabulary (kokoro_onnx/config.json, "vocab", in file order).
VOCAB = (
    ";:,.!?\u2014\u2026\"()\u201c\u201d \u0303\u02a3\u02a5\u02a6\u02a8\u1d5d\uab67AIOQSTWY\u1d4a"
    "abcdefhijklmnopqrstuvwxyz"
    "\u0251\u0250\u0252\u00e6\u03b2\u0254\u0255\u00e7\u0256\u00f0\u02a4\u0259\u025a\u025b\u025c\u025f\u0261\u0265"
    "\u0268\u026a\u029d\u026f\u0270\u014b\u0273\u0272\u0274\u00f8\u0278\u03b8\u0153\u0279\u027e\u027b\u0281\u027d"
    "\u0282\u0283\u0288\u02a7\u028a\u028b\u028c\u0263\u0264\u03c7\u028e\u0292\u0294\u02c8\u02cc\u02d0\u02b0\u02b2"
    "\u2193\u2192\u2197\u2198\u1d7b"
)

#: The key each symbol must have, written per symbol in VOCAB's order (None: takes the key before it).
EXPECTED: dict[str, str | None] = {
    ";": "sil", ":": "sil", ",": "sil", ".": "sil", "!": "sil", "?": "sil", "\u2014": "sil", "\u2026": "sil",
    '"': "sil", "(": "sil", ")": "sil", "\u201c": "sil", "\u201d": "sil", " ": "sil",
    "\u0303": None, "\u02a3": "SS", "\u02a5": "CH", "\u02a6": "SS", "\u02a8": "CH", "\u1d5d": None, "\uab67": "RR",
    "A": "E", "I": "aa", "O": "oh", "Q": "oh", "S": "SS", "T": "DD", "W": "aa", "Y": "oh", "\u1d4a": "E",
    "a": "aa", "b": "PP", "c": "kk", "d": "DD", "e": "E", "f": "FF", "h": "kk", "i": "ih", "j": "ih",
    "k": "kk", "l": "nn", "m": "PP", "n": "nn", "o": "oh", "p": "PP", "q": "kk", "r": "RR", "s": "SS",
    "t": "DD", "u": "ou", "v": "FF", "w": "ou", "x": "kk", "y": "ou", "z": "SS",
    "\u0251": "aa", "\u0250": "aa", "\u0252": "oh", "\u00e6": "aa", "\u03b2": "PP", "\u0254": "oh", "\u0255": "CH",
    "\u00e7": "kk", "\u0256": "DD", "\u00f0": "TH", "\u02a4": "CH", "\u0259": "E", "\u025a": "RR", "\u025b": "E",
    "\u025c": "E", "\u025f": "kk", "\u0261": "kk", "\u0265": "ou", "\u0268": "ih", "\u026a": "ih", "\u029d": "CH",
    "\u026f": "ih", "\u0270": "kk", "\u014b": "nn", "\u0273": "nn", "\u0272": "nn", "\u0274": "nn", "\u00f8": "oh",
    "\u0278": "PP", "\u03b8": "TH", "\u0153": "oh", "\u0279": "RR", "\u027e": "DD", "\u027b": "RR", "\u0281": "kk",
    "\u027d": "RR", "\u0282": "CH", "\u0283": "CH", "\u0288": "DD", "\u02a7": "CH", "\u028a": "ou", "\u028b": "FF",
    "\u028c": "aa", "\u0263": "kk", "\u0264": "oh", "\u03c7": "kk", "\u028e": "nn", "\u0292": "CH", "\u0294": "DD",
    "\u02c8": None, "\u02cc": None, "\u02d0": None, "\u02b0": None, "\u02b2": None,
    "\u2193": None, "\u2192": None, "\u2197": None, "\u2198": None, "\u1d7b": "ih",
}


def _wav(samples: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(b"\x00\x00" * samples)
    return buffer.getvalue()


def _timing(spans, samples: int, **override) -> bytes:
    body = {"v": 1, "rate": RATE, "samples": samples, "timings": [{"p": p, "s": s, "e": e} for p, s, e in spans]}
    body.update(override)
    return json.dumps(body).encode("ascii")


def _shape(frames) -> list[tuple[str, float, float]]:
    return [(f.viseme, round(f.time, 4), round(f.duration, 4)) for f in frames]


_GOOD = [("m", 0.0, 0.1), ("\u0251", 0.1, 0.5)]
_HALF = _wav(12000)  # 0.5 s


# --- the table --------------------------------------------------------------------------------


def test_v1_the_table_covers_exactly_the_114_symbol_vocabulary_once() -> None:
    assert len(VOCAB) == len(set(VOCAB)) == 114
    assert set(PHONEME_VISEMES) == set(VOCAB)
    assert sum(len(symbols) for _key, symbols in phoneme_visemes._GROUPS) == 114  # no symbol in two groups


@pytest.mark.parametrize("symbol", list(VOCAB), ids=[f"U+{ord(c):04X}" for c in VOCAB])
def test_v2_each_vocabulary_symbol_has_its_key(symbol: str) -> None:
    assert PHONEME_VISEMES[symbol] == EXPECTED[symbol]
    assert EXPECTED[symbol] is None or EXPECTED[symbol] in get_args(OculusViseme)


def test_v3_no_module_under_audio_imports_the_avatar_package() -> None:
    # Decision 3: avatars/rhubarb_backend.py imports probos.audio.tts.resident; the reverse edge would be a cycle.
    offenders = []
    for path in sorted((_REPO / "src" / "probos" / "audio").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_bytes())):
            names = (
                [alias.name for alias in node.names] if isinstance(node, ast.Import)
                else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            )
            if any(name == "probos.avatars" or name.startswith("probos.avatars.") for name in names):
                offenders.append(path.relative_to(_REPO).as_posix())
    assert offenders == []


def test_w14_the_worker_and_probos_agree_on_the_file_name_and_version() -> None:
    worker = load_worker()
    assert worker.TIMING_SUFFIX == resident.TIMING_SUFFIX == ".timing.json"
    assert worker.TIMING_VERSION == phoneme_visemes.TIMING_VERSION == 1


# --- the frames -------------------------------------------------------------------------------


def test_f1_gaps_and_space_are_sil_equal_neighbours_merge_and_the_frames_reach_the_end() -> None:
    spans = [("h", 0.1, 0.2), ("\u0251", 0.2, 0.25), ("a", 0.25, 0.3), (" ", 0.3, 0.35), ("m", 0.35, 0.4)]

    frames = frames_from_timing(_timing(spans, 12000), _HALF)

    assert _shape(frames) == [
        ("sil", 0.0, 0.1), ("kk", 0.1, 0.1), ("aa", 0.2, 0.1), ("sil", 0.3, 0.05), ("PP", 0.35, 0.05), ("sil", 0.4, 0.1),
    ]
    assert phoneme_visemes.TIMING_OFFSET_SECONDS == 0.0


def test_f2_a_mark_takes_the_key_before_it_and_a_leading_mark_is_sil() -> None:
    assert _shape(frames_from_timing(_timing([("\u0251", 0.0, 0.2), ("\u02d0", 0.2, 0.5)], 12000), _HALF)) == [("aa", 0.0, 0.5)]
    assert _shape(frames_from_timing(_timing([("\u02c8", 0.0, 0.1), ("m", 0.1, 0.5)], 12000), _HALF)) == [
        ("sil", 0.0, 0.1), ("PP", 0.1, 0.4),
    ]


def test_f3_a_zero_length_span_is_dropped() -> None:
    frames = frames_from_timing(_timing([("m", 0.0, 0.0), ("\u0251", 0.0, 0.5)], 12000), _HALF)

    assert _shape(frames) == [("aa", 0.0, 0.5)]


def test_f4_an_unknown_symbol_is_sil_and_counted_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="probos.avatars.phoneme_visemes")
    assert "g" not in PHONEME_VISEMES  # ASCII g is not in the vocabulary (U+0261 is)

    frames = frames_from_timing(_timing([("m", 0.0, 0.2), ("g", 0.2, 0.3), ("g", 0.3, 0.5)], 12000), _HALF)

    assert _shape(frames) == [("PP", 0.0, 0.2), ("sil", 0.2, 0.3)]
    assert [r.getMessage() for r in caplog.records] == [
        "AD-738g: 2 timed symbol(s) outside the viseme table were shown as sil",
    ]


def test_f5_frames_tile_the_audio_without_gaps_or_overlaps() -> None:
    step = 0.5 / 6
    spans = [(p, i * step, (i + 1) * step) for i, p in enumerate("h\u0259l\u02c8o\u028a")]

    frames = frames_from_timing(_timing(spans, 12000), _HALF)

    assert [f.viseme for f in frames] == ["kk", "E", "nn", "oh", "ou"]
    assert frames[0].time == 0.0
    for before, after in zip(frames, frames[1:]):
        assert after.time == pytest.approx(before.time + before.duration, abs=2e-4)
    assert frames[-1].time + frames[-1].duration == pytest.approx(0.5, abs=2e-4)


def test_f6_a_rounding_gap_is_closed_not_shown_as_sil() -> None:
    spans = [("m", 0.0, 0.1000004), ("ɑ", 0.1000009, 0.4999996)]

    assert _shape(frames_from_timing(_timing(spans, 12000), _HALF)) == [("PP", 0.0, 0.1), ("aa", 0.1, 0.4)]


# --- the check --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("timing", "wav"),
    [
        (b"\xff", _HALF),
        (b"{", _HALF),
        (b"[1]", _HALF),
        (_timing(_GOOD, 12000), b"RIFF"),
        (_timing(_GOOD, 12000, v=2), _HALF),
        (_timing(_GOOD, 12000, rate=22050), _HALF),
        (_timing(_GOOD, 12000, rate=True), _HALF),
        (_timing(_GOOD, 11999), _HALF),
        (_timing(_GOOD, 12000.0), _HALF),
        (_timing([], 12000), _HALF),
        (_timing([("m", 0.0, 0.0)] * 4097, 12000), _HALF),
        (_timing(_GOOD, 12000, timings="x"), _HALF),
        (_timing(_GOOD, 12000, timings=[1]), _HALF),
        (_timing([("mm", 0.0, 0.1)], 12000), _HALF),
        (_timing(_GOOD, 12000, timings=[{"p": 1, "s": 0.0, "e": 0.1}]), _HALF),
        (_timing([("m", 0.2, 0.1)], 12000), _HALF),
        (_timing([("m", -0.1, 0.1)], 12000), _HALF),
        (_timing([("m", 0.0, 0.526)], 12000), _HALF),
        (_timing([("m", 0.2, 0.3), ("a", 0.1, 0.4)], 12000), _HALF),
        (_timing([("m", True, 0.1)], 12000), _HALF),
        (_timing([("m", "0", 0.1)], 12000), _HALF),
        (_timing([("m", float("nan"), 0.1)], 12000), _HALF),
    ],
    ids=[
        "not-utf8", "truncated-json", "not-an-object", "not-a-wav", "version-2", "rate-22050", "rate-bool",
        "samples-11999", "samples-float", "no-timings", "4097-timings", "timings-not-a-list", "entry-not-an-object",
        "symbol-two-chars", "symbol-not-a-string", "end-before-start", "negative-start", "past-the-audio",
        "start-goes-back", "time-bool", "time-string", "time-nan",
    ],
)
def test_x1_a_file_that_fails_a_check_is_refused_with_one_warning(
    timing: bytes, wav: bytes, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)

    assert frames_from_timing(timing, wav) is None

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].startswith("AD-738g: the synthesizer's timings were refused (")


def test_x2_the_boundaries_are_accepted() -> None:
    assert frames_from_timing(_timing([("m", 0.0, 0.525)], 12000), _HALF) is not None  # one frame past the audio
    assert frames_from_timing(_timing([("m", 0, 0.1)], 12000), _HALF) is not None  # integers are numbers
    assert _shape(frames_from_timing(_timing([("m", 0.0, 0.0)] * 4096, 12000), _HALF)) == [("sil", 0.0, 0.5)]


# --- config and registry ----------------------------------------------------------------------


def test_c5_synthesizer_is_an_opt_in_backend_and_the_registry_offers_it() -> None:
    assert LipSyncConfig().backend == "heuristic"
    assert LipSyncConfig(backend="synthesizer").backend == "synthesizer"
    section = get_section("voice")
    assert section is not None
    field = next(f for f in section.fields if f.field_id == "lipsync.backend")
    assert field.enum_values == get_args(LipSyncConfig.model_fields["backend"].annotation) == (
        "heuristic", "rhubarb", "synthesizer",
    )


def test_c6_the_default_model_is_still_s1s_export_and_the_timed_one_is_an_opt_in() -> None:
    # S3a changes no default: the duration-reporting export is fetched only by kokoro-fetch.ps1 -TimedModel, and an
    # operator who has not fetched it must keep his S1 voice after a pull. Flipping this is its own slice (contract 10).
    assert KokoroTTSConfig().model_path == "tools/kokoro/kokoro-v1.0.onnx"
    assert TTSConfig().kokoro.model_path == "tools/kokoro/kokoro-v1.0.onnx"


# --- the route, through the real worker loop --------------------------------------------------


@pytest.fixture
def service():
    svc = VoiceSynthesisService()
    yield svc
    svc.close()


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, service):
    target = tmp_path / "attachments"
    target.mkdir()
    monkeypatch.setattr("probos.attachments.store._resolve_attachments_dir", lambda configured: target)
    rt = SimpleNamespace(
        config=SimpleNamespace(attachments=AttachmentsConfig(attachments_dir=str(target)), lipsync=LipSyncConfig(), tts=TTSConfig()),
        voice_synthesis=service,
    )
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
    app = FastAPI()
    app.include_router(avatars_router_mod.router)
    app.dependency_overrides[get_runtime] = lambda: rt
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http, rt
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


def _kokoro(rt, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, timed: bool, lipsync: str | None) -> Path:
    record = tmp_path / ("calls.timed.jsonl" if timed else "calls.jsonl")
    record.write_text("", encoding="utf-8")
    voices = tmp_path / "voices.bin"
    voices.write_bytes(b"")
    monkeypatch.setattr(kokoro_backend, "WORKER_SCRIPT", str(FAKE_WORKER))
    rt.config.tts = TTSConfig(
        backend="kokoro",
        kokoro=KokoroTTSConfig(python_path=sys.executable, model_path=str(record), voices_path=str(voices)),
    )
    rt.config.lipsync = LipSyncConfig() if lipsync is None else LipSyncConfig(backend=lipsync)
    return record


def _stub_rhubarb(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []

    async def _visemes(audio_path, **_kw):
        calls.append(Path(audio_path))
        return [VisemeFrame(time=0.0, duration=0.1, viseme="aa")]

    monkeypatch.setattr("probos.avatars.rhubarb_backend.generate_visemes", _visemes)
    return calls


def _records(record: Path) -> list[dict]:
    return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines() if line]


@pytest.mark.asyncio
async def test_t4_the_default_heuristic_ignores_the_timings_and_runs_no_rhubarb(client, monkeypatch, tmp_path) -> None:
    http, rt = client
    _kokoro(rt, monkeypatch, tmp_path, timed=True, lipsync=None)
    calls = _stub_rhubarb(monkeypatch)

    for defer in (False, True):
        body = (await http.post("/api/avatars/tts", json={"text": "Hello.", "defer_visemes": defer})).json()
        assert body["backend"] == "kokoro"
        assert body["visemes"] == [] and body["visemes_deferred"] is False

    assert calls == []


@pytest.mark.asyncio
async def test_t5_rhubarb_is_unchanged_when_the_worker_sends_timings(client, monkeypatch, tmp_path) -> None:
    http, rt = client
    _kokoro(rt, monkeypatch, tmp_path, timed=True, lipsync="rhubarb")
    calls = _stub_rhubarb(monkeypatch)

    inline = (await http.post("/api/avatars/tts", json={"text": "Hello."})).json()
    deferred = (await http.post("/api/avatars/tts", json={"text": "Hello.", "defer_visemes": True})).json()

    assert inline["visemes"] == _RHUBARB and inline["visemes_deferred"] is False
    assert deferred["visemes"] == [] and deferred["visemes_deferred"] is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_t6_synthesizer_sends_the_timed_frames_inline_and_runs_no_rhubarb(
    client, monkeypatch, tmp_path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="probos.routers.avatars")  # as tests/test_bf918_tts_latency.py:605
    http, rt = client
    record = _kokoro(rt, monkeypatch, tmp_path, timed=True, lipsync="synthesizer")
    calls = _stub_rhubarb(monkeypatch)

    for defer in (False, True):
        body = (await http.post("/api/avatars/tts", json={"text": "Hello.", "defer_visemes": defer})).json()
        assert body["visemes_deferred"] is False
        assert [f["viseme"] for f in body["visemes"]] == ["kk", "E", "nn", "oh", "ou"]
        assert body["visemes"][0]["time"] == 0.0
        last = body["visemes"][-1]
        assert last["time"] + last["duration"] == pytest.approx(body["duration_ms"] / 1000, abs=1e-3)

    assert calls == []
    assert all(r["sentence_pause"] == 0.0 and r["clause_pause"] == 0.0 for r in _records(record))
    assert "visemes=synthesizer" in caplog.text


@pytest.mark.asyncio
async def test_t7_synthesizer_on_a_model_without_timings_is_served_as_rhubarb_deferred_path_included(
    client, monkeypatch, tmp_path,
) -> None:
    http, rt = client
    record = _kokoro(rt, monkeypatch, tmp_path, timed=False, lipsync="synthesizer")
    calls = _stub_rhubarb(monkeypatch)

    deferred = (await http.post("/api/avatars/tts", json={"text": "Hello.", "defer_visemes": True})).json()
    fetched = (await http.post("/api/avatars/lipsync", json={"attachment_id": deferred["audio_attachment_id"]})).json()
    inline = (await http.post("/api/avatars/tts", json={"text": "Hello."})).json()

    assert deferred["visemes"] == [] and deferred["visemes_deferred"] is True
    assert fetched == {"backend": "rhubarb", "frames": _RHUBARB}  # voice.ts accepts only backend "rhubarb"
    assert inline["visemes"] == _RHUBARB and inline["visemes_deferred"] is False
    assert len(calls) == 2
    assert all("method" not in r for r in _records(record))  # S1's create, S1's pauses


@pytest.mark.asyncio
async def test_t8_refused_timings_fall_back_to_rhubarb_with_one_warning(
    client, monkeypatch, tmp_path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    http, rt = client
    _kokoro(rt, monkeypatch, tmp_path, timed=True, lipsync="synthesizer")
    calls = _stub_rhubarb(monkeypatch)

    body = (await http.post("/api/avatars/tts", json={"text": "BADTIMING"})).json()

    assert body["visemes"] == _RHUBARB and body["visemes_deferred"] is False
    assert len(calls) == 1
    refused = [r for r in caplog.records if "the synthesizer's timings were refused" in r.getMessage()]
    assert len(refused) == 1 and refused[0].levelno == logging.WARNING
