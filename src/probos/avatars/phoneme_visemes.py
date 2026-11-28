"""AD-738g (#1662) S3a: lip-sync frames from the Kokoro worker's phoneme timings.

The worker (``scripts/kokoro_worker.py``) writes ``<wav>.timing.json`` when its model reports
durations (the kokoro-onnx ``model-files-v1.1`` export): one entry per spoken symbol,
``{"p": symbol, "s": start, "e": end}`` in seconds from the start of the WAV. kokoro-onnx 0.6.1
rescales the model's durations to the real audio and moves them with the head trim, so the spans
follow the audio. The symbols are espeak-ng IPA filtered to the package's 114-symbol vocabulary
(``kokoro_onnx/config.json``), so a diphthong is already two symbols.

``frames_from_timing`` checks the file against the WAV and maps it to the Oculus 15-set
(``rhubarb_backend.OculusViseme``). A file that fails a check gives ``None`` after one WARNING,
and the route serves that sentence as ``rhubarb``. Never raises.

License posture: standard library only, plus ``VisemeFrame``. The timing file is data (symbols
and numbers); nothing from the worker's venv is imported.
"""

from __future__ import annotations

import io
import json
import logging
import math
import struct
import wave
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from probos.avatars.rhubarb_backend import VisemeFrame

logger = logging.getLogger(__name__)

#: The timing file's format version (``scripts/kokoro_worker.py`` ``TIMING_VERSION``).
TIMING_VERSION = 1
#: At most this many timed symbols in one file (about eight 510-symbol batches); a longer file is refused.
MAX_TIMINGS = 4096
#: One Kokoro duration frame (600 samples at 24 kHz); a time may run at most one frame past the audio.
FRAME_SAMPLES = 600
#: Seconds added to every frame's start. Zero until measurement D4 of the S3a contract tunes it once.
TIMING_OFFSET_SECONDS = 0.0
#: A gap up to this long between spans (the worker rounds times to 6 decimals) is closed, not shown as sil.
MIN_GAP_SECONDS = 0.001

# Oculus key -> the vocabulary symbols shown with it; None: the symbol takes the key before it (stress,
# length, aspiration, palatalisation, nasalisation and intonation marks). The renderer weights only the
# vowels aa, ih, ou, E and oh (rhubarb_backend.py); the consonant rows are for completeness. The misaki
# letters A I O Q S T W Y are in the vocabulary but espeak never emits them; each has its nearest key.
_GROUPS: tuple[tuple[str | None, str], ...] = (
    ("sil", ";:,.!?\u2014\u2026\"()\u201c\u201d "),
    (None, "\u02c8\u02cc\u02d0\u02b0\u02b2\u0303\u2193\u2192\u2197\u2198\u1d5d"),
    ("PP", "pbm\u03b2\u0278"),
    ("FF", "fv\u028b"),
    ("TH", "\u03b8\u00f0"),
    ("DD", "td\u0256\u0288\u027e\u0294T"),
    ("kk", "kc\u0261\u025fqx\u0263\u03c7\u0281\u0270h\u00e7"),
    ("CH", "\u0283\u0292\u02a7\u02a4\u02a8\u02a5\u0255\u029d\u0282"),
    ("SS", "sz\u02a6\u02a3S"),
    ("nn", "nl\u014b\u0272\u0273\u0274\u028e"),
    ("RR", "r\u0279\u027b\u027d\u025a\uab67"),
    ("aa", "a\u0251\u0250\u00e6\u028cIW"),
    ("E", "e\u025b\u0259\u1d4a\u025cA"),
    ("ih", "i\u026a\u0268\u1d7b\u026fj"),
    ("oh", "o\u0254\u0252\u0264\u00f8\u0153OQY"),
    ("ou", "u\u028aw\u0265y"),
)

#: Every vocabulary symbol to its Oculus key, or ``None`` for a mark that takes the key before it.
PHONEME_VISEMES: Mapping[str, str | None] = MappingProxyType(
    {symbol: key for key, symbols in _GROUPS for symbol in symbols}
)


def frames_from_timing(timing: bytes, wav: bytes) -> tuple[VisemeFrame, ...] | None:
    """Frames covering the whole WAV from its timing file, or ``None`` after one WARNING. Never raises.

    Gaps between spans (the lead-in, the tail, long end pauses) and space and punctuation are ``sil``;
    zero-length spans are dropped; an unknown symbol is ``sil`` and counted in one INFO line; equal
    neighbours merge.
    """
    checked = _checked_spans(timing, wav)
    if checked is None:
        return None
    spans, end_of_audio = checked
    frames: list[VisemeFrame] = []
    previous, cursor, unknown = "sil", 0.0, 0
    for symbol, start, end in spans:
        start = max(start, cursor)
        if end <= start:
            continue  # zero length: the head trim clips a span to nothing (kokoro_onnx __init__.py)
        if symbol in PHONEME_VISEMES:
            mapped = PHONEME_VISEMES[symbol]
            key = previous if mapped is None else mapped
        else:
            key, unknown = "sil", unknown + 1
        if start - cursor > MIN_GAP_SECONDS:
            _add(frames, cursor, start, "sil")
        else:
            start = cursor  # a rounding gap: the frames stay contiguous
        _add(frames, start, end, key)
        previous, cursor = key, end
    if end_of_audio - cursor > MIN_GAP_SECONDS:
        _add(frames, cursor, end_of_audio, "sil")
    elif frames and end_of_audio > cursor:
        frames[-1] = VisemeFrame(frames[-1].time, end_of_audio - frames[-1].time, frames[-1].viseme)
    if unknown:
        logger.info("AD-738g: %d timed symbol(s) outside the viseme table were shown as sil", unknown)
    return tuple(
        VisemeFrame(round(max(0.0, f.time + TIMING_OFFSET_SECONDS), 4), round(f.duration, 4), f.viseme)
        for f in frames
    )


def _add(frames: list[VisemeFrame], start: float, end: float, key: str) -> None:
    """Append ``[start, end)`` as ``key``, merging it into the frame before when that has the same key."""
    if frames and frames[-1].viseme == key:
        frames[-1] = VisemeFrame(frames[-1].time, end - frames[-1].time, key)
    else:
        frames.append(VisemeFrame(start, end - start, key))


def _checked_spans(timing: bytes, wav: bytes) -> tuple[list[tuple[str, float, float]], float] | None:
    """The file's spans and the WAV's length in seconds, or ``None`` after one WARNING naming the failed check."""
    try:
        body = json.loads(timing.decode("ascii"))
        with wave.open(io.BytesIO(wav), "rb") as handle:
            rate, samples = handle.getframerate(), handle.getnframes()
    except (ValueError, EOFError, wave.Error, struct.error, RecursionError) as exc:  # RecursionError: nested too deep
        return _refused(f"unreadable: {type(exc).__name__}")
    if not isinstance(body, dict) or body.get("v") != TIMING_VERSION:
        return _refused("not a version-1 timing object")
    if not _is_int(body.get("rate")) or rate <= 0 or body["rate"] != rate:
        return _refused(f"rate {body.get('rate')!r} is not the WAV's {rate}")
    if not _is_int(body.get("samples")) or body["samples"] != samples:
        return _refused(f"samples {body.get('samples')!r} is not the WAV's {samples}")
    entries = body.get("timings")
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_TIMINGS:
        return _refused(f"timings is not a list of 1 to {MAX_TIMINGS} entries")
    limit = (samples + FRAME_SAMPLES) / rate
    spans: list[tuple[str, float, float]] = []
    last_start = 0.0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            return _refused(f"entry {index} is not an object")
        symbol, start, end = entry.get("p"), entry.get("s"), entry.get("e")
        if not (isinstance(symbol, str) and len(symbol) == 1 and _is_number(start) and _is_number(end)):
            return _refused(f"entry {index} is not one symbol with two finite numbers")
        if not 0.0 <= start <= end <= limit:
            return _refused(f"entry {index} spans {start}..{end}, outside 0..{limit:.3f} s")
        if start < last_start:
            return _refused(f"entry {index} starts before entry {index - 1}")
        spans.append((symbol, float(start), float(end)))
        last_start = start
    return spans, samples / rate


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    """A JSON int or float with a finite float value; an int past float range has none (``OverflowError``)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _refused(reason: str) -> None:
    logger.warning("AD-738g: the synthesizer's timings were refused (%s); this sentence's lip-sync uses rhubarb", reason)
    return None
