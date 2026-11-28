"""AD-738g (#1662): the real Kokoro worker loop with a stand-in engine, for tests.

Run exactly as the service runs the real worker: ``python -I <this file> --model M --voices V
--threads N --default-voice D``. Only the engine is fake: ``scripts/kokoro_worker.py``'s own
``main`` parses the arguments, moves library prints off stdout, reads each JSON line, picks
the voice and language, writes the WAV and prints the path. The fake engine has no model, so
``--model`` names a file where it appends one JSON line per call (text, voice, speed, lang and
this process's pid). Nothing here needs kokoro-onnx; numpy is a ProbOS dependency.

AD-738g S3a: a ``--model`` file whose name ends ``.timed.jsonl`` makes the engine report timings
(``has_timings``), as the ``model-files-v1.1`` export does: ``FAKE_PHONEMES`` spread evenly over
the audio. Its calls also record ``method``, ``sentence_pause`` and ``clause_pause``. The text
``NOTIMINGS`` returns no timings, and ``BADTIMING`` ends the last one a second past the audio.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

WORKER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "kokoro_worker.py"
VOICES: tuple[str, ...] = ("af_heart", "af_bella", "bf_emma", "bm_fable", "am_liam")
RATE = 24000
#: The symbols a timed fake speaks for any text: espeak-style IPA for "hello" (frames kk, E, nn, oh, ou).
FAKE_PHONEMES = "h\u0259l\u02c8o\u028a"


def load_worker() -> Any:
    """``scripts/kokoro_worker.py`` as a module, loaded by path (``-I`` puts no script directory on ``sys.path``)."""
    spec = importlib.util.spec_from_file_location("kokoro_worker", WORKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class FakeTiming:
    """kokoro-onnx 0.6.1's ``Timing`` (``sliding.py``): one spoken symbol and its span in seconds."""

    phoneme: str
    start: float
    end: float


class FakeEngine:
    """kokoro-onnx 0.6.1's checks, measured 2026-11-27: an unknown voice, a speed outside [0.5, 2.0]
    and a text with no phonemes raise ``ValueError``. A voice's audio is 0.05 s per catalogue
    position (``af_heart`` 0.05 s, ``bm_fable`` 0.2 s), so a WAV's length shows which voice spoke."""

    def __init__(self, record: Path | None = None, voices: tuple[str, ...] = VOICES, timed: bool = False) -> None:
        self.record = record
        self.voices = voices
        self.calls: list[dict[str, Any]] = []
        self.has_timings = timed

    def get_voices(self) -> list[str]:
        return list(self.voices)

    def create(self, text: str, voice: str, speed: float, lang: str) -> tuple[Any, int]:
        return self._speak(text, voice, speed, lang)

    def create_timed(
        self, text: str, voice: str, speed: float, lang: str, sentence_pause: float = 0.25, clause_pause: float = 0.1,
    ) -> tuple[Any, int, list[FakeTiming]]:
        samples, rate = self._speak(
            text, voice, speed, lang,
            method="create_timed", sentence_pause=sentence_pause, clause_pause=clause_pause,
        )
        if text == "NOTIMINGS":
            return samples, rate, []
        seconds = len(samples) / rate
        step = seconds / len(FAKE_PHONEMES)
        timings = [FakeTiming(p, i * step, (i + 1) * step) for i, p in enumerate(FAKE_PHONEMES)]
        if text == "BADTIMING":
            timings[-1] = FakeTiming(timings[-1].phoneme, timings[-1].start, seconds + 1.0)
        return samples, rate, timings

    def _speak(self, text: str, voice: str, speed: float, lang: str, **extra: Any) -> tuple[Any, int]:
        call = {"text": text, "voice": voice, "speed": speed, "lang": lang, "pid": os.getpid(), **extra}
        self.calls.append(call)
        if self.record is not None:
            with self.record.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(call) + "\n")
        if voice not in self.voices:
            raise ValueError(f"Voice {voice} not found in available voices")
        if not 0.5 <= speed <= 2.0:
            raise ValueError(f"Speed should be between 0.5 and 2.0, got {speed}")
        if not text.strip():
            raise ValueError(f"Nothing to synthesize, {text!r} produced no phonemes")
        if text == "CHATTER":
            print("library chatter on stdout")
        frames = int(RATE * 0.05 * (1 + self.voices.index(voice)))
        return np.full(frames, 0.25, dtype=np.float32), RATE


if __name__ == "__main__":
    worker = load_worker()
    sys.exit(worker.main(
        engine_factory=lambda args: FakeEngine(Path(args.model), timed=Path(args.model).name.endswith(".timed.jsonl")),
    ))
