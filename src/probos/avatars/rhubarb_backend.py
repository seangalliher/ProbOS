"""AD-721b-1 — rhubarb-lip-sync subprocess wrapper.

License posture: rhubarb-lip-sync is MIT (verified 2026-05-12 via
``gh api repos/DanielSWolf/rhubarb-lip-sync/license``). ProbOS provides
this wrapper; the operator provides the binary at ``lipsync.binary_path``.
The repo never ships the binary — ``/tools/`` is gitignored.

Tier-2 log-and-degrade: every callable in this module returns False,
None, or an empty list on failure; ``CrewVRM`` (AD-721b-2) treats any
of those signals as the cue to fall back to the AD-721b v1 heuristic
path. None of these callables raise.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# AD-721b-1: rhubarb's Preston Blair 9-set → AD-721b v1 Oculus 15-set.
# rhubarb returns the 9 mouth shapes (A-H, X). The renderer in
# ``ui/src/audio/lipSyncTrack.ts:25-27`` consumes the Oculus 15-set.
# Mapping is intentional and lossy — multiple Oculus visemes collapse
# onto each Preston Blair shape on the way out, but the renderer uses
# only the vowel-set (aa/ih/ou/E/oh) for the morph weights anyway, so
# the consonant mapping is for completeness.
PrestonBlairViseme = Literal["A", "B", "C", "D", "E", "F", "G", "H", "X"]

OculusViseme = Literal[
    "sil", "PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR",
    "aa", "E", "ih", "oh", "ou",
]

# AD-738c (Wave 158): base 1-to-1 mapping. The actual lookup function
# `_map_preston_blair_to_oculus` adds a duration-aware variant for the
# `B` shape — when a `B` frame exceeds 80 ms it almost always renders
# a short vowel sound (rhubarb misclassifies sustained "ih"/"uh" as
# `B`-shaped mouth). Short `B` frames keep the `kk` mapping because
# they really are stop consonants.
_PRESTON_BLAIR_TO_OCULUS: dict[str, str] = {
    "A": "PP",   # closed mouth — m/b/p
    "B": "kk",   # slightly open — k/g/n/t/d/s/z (DEFAULT — overridden for long frames; see _map_preston_blair_to_oculus)
    "C": "E",    # open mouth — e (as in "bed")
    "D": "aa",   # wide open — a (as in "father")
    "E": "oh",   # rounded — o (as in "go")
    "F": "ou",   # narrow — u (as in "you")
    "G": "FF",   # f/v
    "H": "RR",   # l/r
    "X": "sil",  # rest / silence
}

# AD-738c: duration threshold (milliseconds) above which a `B` frame is
# routed to a full vowel (`ih`) instead of the consonant default (`kk`).
# Empirical: 80 ms is the floor for sustained "ih"-class vowels in
# Piper Amy MIT @ 22050 Hz; stop consonants in the same voice peak
# at 60-75 ms.
_B_LONG_DURATION_MS: float = 80.0


@dataclass(frozen=True)
class VisemeFrame:
    """One viseme segment in the schedule.

    ``time`` and ``duration`` are seconds (rhubarb's native unit).
    ``viseme`` is the Oculus 15-set key consumed by the renderer.
    """

    time: float
    duration: float
    viseme: str


def _map_preston_blair_to_oculus(pb: str, duration_ms: float = 0.0) -> str:
    """Lookup with duration-aware override for ``B`` (AD-738c).

    Falls back to ``sil`` for any unknown shape (forward-compat if rhubarb
    adds a viseme — log-and-degrade rather than crash).

    When ``pb == "B"`` and ``duration_ms > _B_LONG_DURATION_MS`` (default
    80 ms), routes to ``"ih"`` (full vowel) instead of ``"kk"`` (consonant
    default). Rationale: rhubarb's ``B`` covers both short stop consonants
    AND short unstressed vowels that fall below the wider C/D/E shapes.
    Long B frames are almost always vowel-class sounds.

    Backward compat: callers that pass ``duration_ms=0.0`` (or omit the
    kwarg) get the legacy 1-to-1 mapping unchanged.
    """
    mapped = _PRESTON_BLAIR_TO_OCULUS.get(pb)
    if mapped is None:
        logger.warning(
            "AD-721b-1: unknown Preston Blair viseme %r; degrading to sil", pb
        )
        return "sil"
    if pb == "B" and duration_ms > _B_LONG_DURATION_MS:
        return "ih"
    return mapped


def _resolve_binary_path(configured: str) -> Path | None:
    """Resolve the configured binary path, auto-appending ``.exe`` on Windows
    if the literal path does not exist. Returns None if the binary cannot
    be located. NEVER raises."""
    p = Path(configured).resolve()
    if p.is_file():
        return p
    if sys.platform == "win32" and p.suffix.lower() != ".exe":
        # Append .exe alongside the existing name to avoid clobbering an
        # existing suffix (e.g. "rhubarb.bin" → "rhubarb.bin.exe", not
        # "rhubarb.exe"). Path.with_suffix would replace the suffix.
        with_exe = p.parent / (p.name + ".exe")
        if with_exe.is_file():
            return with_exe
    return None


async def is_available(binary_path: str, timeout_seconds: float = 5.0) -> bool:
    """Check rhubarb is present at ``binary_path`` AND responds to ``--version``.

    Tier-2 log-and-degrade: any failure returns False. NEVER raises.
    """
    resolved = _resolve_binary_path(binary_path)
    if resolved is None:
        logger.info(
            "AD-721b-1: rhubarb binary not found at %s; degrading to heuristic",
            binary_path,
        )
        return False
    version = await probe_version(resolved, timeout_seconds=timeout_seconds)
    return version is not None


async def probe_version(
    binary_path: Path, timeout_seconds: float = 5.0
) -> str | None:
    """Run ``rhubarb --version`` and return the version string, or None on any
    failure. NEVER raises."""
    try:
        # BF-280 (2026-05-13): subprocess.Popen in thread executor to support
        # WindowsSelectorEventLoop (which lacks create_subprocess_*).
        def _probe_sync() -> tuple[int, bytes, bytes]:
            proc = subprocess.Popen(
                [str(binary_path), "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                out, err = proc.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise
            return proc.returncode or 0, out, err

        loop = asyncio.get_running_loop()
        try:
            returncode, stdout, _stderr = await loop.run_in_executor(None, _probe_sync)
        except subprocess.TimeoutExpired:
            logger.warning(
                "AD-721b-1: rhubarb --version timed out after %ss", timeout_seconds
            )
            return None
        if returncode != 0:
            logger.warning(
                "AD-721b-1: rhubarb --version returned %s", returncode
            )
            return None
        return stdout.decode("utf-8", errors="replace").strip()
    except (OSError, ValueError) as e:
        logger.warning(
            "AD-721b-1: rhubarb --version failed: %s: %s", type(e).__name__, e
        )
        return None


async def generate_visemes(
    audio_path: Path,
    binary_path: str,
    timeout_seconds: float = 30.0,
) -> list[VisemeFrame]:
    """Run rhubarb on ``audio_path``, return Oculus-mapped viseme schedule.

    Returns ``[]`` on ANY failure (binary missing, subprocess error, malformed
    JSON, timeout). The empty-list contract is the signal to the caller
    (router) to fall through to the heuristic path. NEVER raises.

    The wav file at ``audio_path`` MUST be a path resolved through
    ``AttachmentStore.get_path()`` so it's already sandboxed under the
    platform data dir (AD-720 path-traversal guard).
    """
    if not audio_path.is_file():
        logger.warning("AD-721b-1: audio path missing: %s", audio_path)
        return []
    resolved_binary = _resolve_binary_path(binary_path)
    if resolved_binary is None:
        logger.warning(
            "AD-721b-1: rhubarb binary not found at %s; returning empty schedule",
            binary_path,
        )
        return []
    try:
        # BF-280 (2026-05-13): subprocess.Popen in thread executor.
        # BF-284 (2026-05-13): use --recognizer phonetic instead of the default
        # pocketSphinx. PocketSphinx is ~2.5x slower because it runs a full
        # English ASR pass with language modeling; phonetic is purely acoustic
        # and language-agnostic. Our pipeline collapses rhubarb's output to the
        # Preston Blair 9-set anyway (rhubarb_backend.py:41) and the renderer
        # further collapses to 5 vowel axes, so the consonant-distinction loss
        # from phonetic is invisible at the rendered-mouth level. --threads 0
        # lets rhubarb use all available cores.
        def _run_sync() -> tuple[int, bytes, bytes]:
            proc = subprocess.Popen(
                [
                    str(resolved_binary),
                    "-r", "phonetic",
                    "--threads", "0",
                    "-f", "json",
                    str(audio_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                out, err = proc.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise
            return proc.returncode or 0, out, err

        loop = asyncio.get_running_loop()
        try:
            returncode, stdout_bytes, stderr_bytes = await loop.run_in_executor(
                None, _run_sync,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "AD-721b-1: rhubarb timed out after %ss on %s; degrading",
                timeout_seconds, audio_path.name,
            )
            return []
        if returncode != 0:
            logger.warning(
                "AD-721b-1: rhubarb exit=%s on %s; stderr=%s",
                returncode, audio_path.name,
                stderr_bytes.decode("utf-8", errors="replace")[:500],
            )
            return []
    except (OSError, ValueError) as e:
        logger.warning(
            "AD-721b-1: rhubarb subprocess failed on %s: %s: %s",
            audio_path.name, type(e).__name__, e,
        )
        return []

    try:
        payload = json.loads(stdout_bytes.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        logger.warning(
            "AD-721b-1: rhubarb returned malformed JSON on %s: %s",
            audio_path.name, e,
        )
        return []

    cues = payload.get("mouthCues") if isinstance(payload, dict) else None
    if not isinstance(cues, list):
        logger.warning(
            "AD-721b-1: rhubarb JSON missing mouthCues on %s", audio_path.name
        )
        return []

    return _parse_rhubarb_output(payload)


def _parse_rhubarb_output(payload: dict) -> list[VisemeFrame]:
    """Convert a parsed rhubarb JSON payload into VisemeFrame list.

    AD-738c (Wave 158): extracted so the duration-aware Preston-Blair
    mapping is unit-testable without a subprocess. Silently skips malformed
    cues (defense in depth — rhubarb output has been observed to drop
    fields under rare conditions).
    """
    cues = payload.get("mouthCues") if isinstance(payload, dict) else None
    if not isinstance(cues, list):
        return []
    frames: list[VisemeFrame] = []
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        start = cue.get("start")
        end = cue.get("end")
        value = cue.get("value")
        if not (isinstance(start, (int, float)) and isinstance(end, (int, float))):
            continue
        if not isinstance(value, str):
            continue
        if end < start:
            continue
        duration_s = float(end - start)
        frames.append(
            VisemeFrame(
                time=float(start),
                duration=duration_s,
                viseme=_map_preston_blair_to_oculus(value, duration_ms=duration_s * 1000.0),
            )
        )
    return frames
