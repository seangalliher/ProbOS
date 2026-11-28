"""AD-738g (#1662) S1: the resident Kokoro worker. ProbOS starts it; it is not part of the ProbOS process.

Run by ``VoiceSynthesisService`` (``src/probos/audio/tts/resident.py``) as
``<tools/kokoro/venv python> -I scripts/kokoro_worker.py --model M --voices V --threads N --default-voice D``.
``-I`` keeps ``PYTHON*`` variables, the user site, this directory and the working directory
off ``sys.path``. It cannot import ``probos`` because ``tools/kokoro/venv`` does not contain it
(``scripts/kokoro-fetch.ps1`` checks this), not because of ``-I``.

Protocol (Piper's ``--json-input``): one ASCII JSON object per stdin line,
``{"text", "output_file", "voice", "speed"}``. For each line the worker writes a 16-bit mono
WAV at the engine's rate (24 kHz) to ``output_file`` and prints that path on stdout. A request
it cannot speak (an engine error: no phonemes, a speed out of range) is answered with the path
and no file, and the worker keeps serving. A line it cannot read ends the worker (exit 3). A
model it cannot load, or a default voice the voices file lacks, ends it before it reads a line
(exit 2). Logs go to stderr, which the service sends to a file; library prints go there too.

AD-738g S3a: when the model reports durations (kokoro-onnx's ``has_timings``: the
``model-files-v1.1`` export), the worker asks for the phoneme timings with no added pauses and,
before it prints the path, writes ``<output_file>.timing.json`` (``write_timing``):
``{"v": 1, "rate": R, "samples": N, "timings": [{"p": symbol, "s": start, "e": end}, ...]}``, the
times in seconds from the start of the WAV. No timings, no file; a file it cannot write is logged
and the audio stands. Any other engine is called exactly as in S1. The line protocol is unchanged.

License posture: this file imports only the standard library and numpy at module level, and
``onnxruntime`` and ``kokoro_onnx`` (both MIT) inside ``load_engine``. kokoro-onnx loads
phonemizer and espeak-ng (GPL-3.0-or-later) into this process, which the operator installs
into ``tools/kokoro/venv`` (``scripts/kokoro-fetch.ps1``) and which exchanges only text, a
voice id and a speed in and a WAV path out with ProbOS, plus the timing file beside the WAV,
which is data (THIRD_PARTY_LICENSES.md, "License policy").
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import wave
from pathlib import Path
from typing import IO, Any, Callable, Protocol

import numpy as np

#: Exit codes; the service's log shows them as ``exit=N``.
EXIT_CANNOT_START = 2
EXIT_UNREADABLE_LINE = 3
#: AD-738g S3a: the timing file's name after the WAV's (``probos.audio.tts.resident.TIMING_SUFFIX``) and its format version
#: (``probos.avatars.phoneme_visemes.TIMING_VERSION``); this process cannot import probos, so tests pin them equal.
TIMING_SUFFIX = ".timing.json"
TIMING_VERSION = 1


class Engine(Protocol):
    """The part of ``kokoro_onnx.Kokoro`` the worker uses.

    AD-738g S3a: ``has_timings`` is kokoro-onnx 0.6.1's own flag, True when the model has a
    ``duration`` output; ``create_timed`` returns the audio, the rate and one timing per spoken
    symbol, each with ``phoneme``, ``start`` and ``end`` (seconds).
    """

    has_timings: bool

    def get_voices(self) -> list[str]: ...

    def create(self, text: str, voice: str, speed: float, lang: str) -> tuple[Any, int]: ...

    def create_timed(
        self, text: str, voice: str, speed: float, lang: str, sentence_pause: float, clause_pause: float,
    ) -> tuple[Any, int, list[Any]]: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ProbOS resident Kokoro worker (AD-738g)")
    parser.add_argument("--model", required=True)
    parser.add_argument("--voices", required=True)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--default-voice", required=True)
    return parser


def lang_for(voice: str) -> str:
    """kokoro-onnx's language for a voice id: ``b?_`` voices are British English, the rest American."""
    return "en-gb" if voice.startswith("b") else "en-us"


def write_wav(path: Path, samples: Any, rate: int) -> int:
    """Write ``samples`` (floats in -1..1) as a 16-bit mono WAV; the file appears whole or not at all.

    Returns the number of samples written (AD-738g S3a: the timing file records it).
    """
    pcm = np.nan_to_num(np.asarray(samples, dtype=np.float32).reshape(-1), nan=0.0)
    if pcm.size == 0:
        raise ValueError("the engine returned no samples")
    frames = (np.clip(pcm, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    part = path.with_name(path.name + ".part")
    try:
        with wave.open(str(part), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(int(rate))
            out.writeframes(frames)
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)
    return int(pcm.size)


def write_timing(path: Path, timings: list[Any], rate: int, samples: int) -> None:
    """AD-738g S3a: write ``timings`` beside the WAV at ``path`` as ASCII JSON; the file appears whole or not at all."""
    body = {
        "v": TIMING_VERSION,
        "rate": int(rate),
        "samples": int(samples),
        "timings": [
            {"p": str(t.phoneme), "s": round(float(t.start), 6), "e": round(float(t.end), 6)} for t in timings
        ],
    }
    target = path.with_name(path.name + TIMING_SUFFIX)
    part = target.with_name(target.name + ".part")
    try:
        part.write_bytes(json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("ascii"))
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)


def read_request(raw: bytes) -> dict[str, Any]:
    """One request line. Raises ``ValueError`` unless it is a JSON object with string ``text`` and ``output_file``."""
    request = json.loads(raw.decode("ascii"))
    if (
        not isinstance(request, dict)
        or not isinstance(request.get("text"), str)
        or not isinstance(request.get("output_file"), str)
        or not request["output_file"]
    ):
        raise ValueError("a request needs a string text and a non-empty string output_file")
    return request


def speak(engine: Engine, voices: frozenset[str], default_voice: str, request: dict[str, Any], log: IO[str]) -> bool:
    """Synthesize one request into its output file. True when a file was written; never raises."""
    text: str = request["text"]
    voice = request.get("voice")
    if not isinstance(voice, str) or voice not in voices:
        if voice is not None:
            _log(log, f"AD-738g: voice {voice!r} is not in the voices file; speaking {default_voice}")
        voice = default_voice
    out = Path(request["output_file"])
    timings: list[Any] = []
    try:
        speed = float(request.get("speed", 1.0))
        if engine.has_timings:
            # AD-738g S3a: no added pauses, so the pacing is S1's for a one-batch request (contract decision 5).
            samples, rate, timings = engine.create_timed(
                text, voice=voice, speed=speed, lang=lang_for(voice), sentence_pause=0.0, clause_pause=0.0,
            )
        else:
            samples, rate = engine.create(text, voice=voice, speed=speed, lang=lang_for(voice))
        written = write_wav(out, samples, rate)
    except Exception as exc:  # one request: answer with the path and no file, keep serving (contract D2)
        _log(log, f"AD-738g: no audio for {len(text)} chars in {voice}: {type(exc).__name__}: {exc}")
        return False
    if timings:
        try:
            write_timing(out, timings, rate, written)
        except Exception as exc:  # the audio stands; this sentence's lip-sync takes the rhubarb path
            _log(log, f"AD-738g: no timing file for {len(text)} chars in {voice}: {type(exc).__name__}: {exc}")
    return True


def serve(engine: Engine, stdin: IO[bytes], stdout: IO[bytes], *, default_voice: str, log: IO[str]) -> int:
    """Answer request lines until end of input (0), an unreadable line (3) or a missing default voice (2)."""
    voices = frozenset(engine.get_voices())
    if default_voice not in voices:
        _log(log, f"AD-738g: default voice {default_voice!r} is not in the voices file; refusing to start")
        return EXIT_CANNOT_START
    _log(log, f"AD-738g: kokoro worker ready ({len(voices)} voices, default {default_voice})")
    while True:
        raw = stdin.readline()
        if not raw:
            return 0
        if not raw.strip():
            continue
        try:
            request = read_request(raw)
        except ValueError as exc:  # JSONDecodeError and UnicodeDecodeError are ValueErrors
            _log(log, f"AD-738g: unreadable request line; exiting: {exc}")
            return EXIT_UNREADABLE_LINE
        speak(engine, voices, default_voice, request, log)
        stdout.write(request["output_file"].encode("utf-8") + b"\n")
        stdout.flush()


def load_engine(args: argparse.Namespace) -> Engine:
    """kokoro-onnx on the CPU with ``args.threads`` intra-op threads (measured RTF 0.314 at 4 on a 7950X3D)."""
    import onnxruntime as ort
    from kokoro_onnx import Kokoro

    options = ort.SessionOptions()
    options.intra_op_num_threads = args.threads
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(args.model, sess_options=options, providers=["CPUExecutionProvider"])
    return Kokoro.from_session(session, args.voices)


def main(
    argv: list[str] | None = None,
    *,
    engine_factory: Callable[[argparse.Namespace], Engine] = load_engine,
) -> int:
    args = build_parser().parse_args(argv)
    protocol = sys.stdout.buffer
    log = sys.stderr
    sys.stdout = sys.stderr  # a library print can never reach the protocol pipe
    try:
        engine = engine_factory(args)
    except Exception as exc:
        _log(log, f"AD-738g: cannot load the Kokoro model: {type(exc).__name__}: {exc}")
        return EXIT_CANNOT_START
    return serve(engine, sys.stdin.buffer, protocol, default_voice=args.default_voice, log=log)


def _log(log: IO[str], message: str) -> None:
    print(message, file=log, flush=True)


if __name__ == "__main__":
    sys.exit(main())
