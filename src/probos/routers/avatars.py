"""AD-721b-1 — Avatar pipeline endpoints.

Currently exposes ``POST /api/avatars/lipsync``: takes a sha256
attachment_id pointing at a previously-uploaded audio blob and returns
a viseme schedule produced by rhubarb-lip-sync. Honest-degrade when the
backend is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/avatars", tags=["avatars"])


@router.post("/lipsync")
async def generate_lipsync(
    req: Request,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Generate a viseme schedule for an audio blob already in AttachmentStore.

    Body: ``{"attachment_id": "<sha256-hex>"}``. The audio blob must have
    been uploaded via ``POST /api/chat/attachments`` or
    ``POST /api/chat/attachments/multipart`` first (AD-720 / AD-720a).

    Returns: ``{"backend": "rhubarb"|"heuristic"|"disabled", "frames": [...]}``.
    Empty ``frames`` means the backend was unavailable AND the client should
    fall back to its own heuristic path (AD-721b-2).
    """
    cfg = getattr(runtime.config, "lipsync", None)
    if cfg is None or not cfg.enabled:
        return {"backend": "disabled", "frames": []}

    payload = await req.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_body")
    attachment_id = payload.get("attachment_id")
    if not (
        isinstance(attachment_id, str)
        and len(attachment_id) == 64
        and all(c in "0123456789abcdef" for c in attachment_id)
    ):
        raise HTTPException(status_code=400, detail="invalid_attachment_id")

    # AD-720: reuse the existing chat-router store accessor; never instantiate
    # a second AttachmentStore (Cloud-Ready Storage seam invariant).
    from probos.routers.chat import _get_attachment_store
    store = _get_attachment_store(runtime)
    if not await store.exists(attachment_id):
        raise HTTPException(status_code=404, detail="attachment_not_found")

    if cfg.backend == "heuristic":
        # Backend set to heuristic — caller does the work client-side. Return
        # empty frames; the AD-721b v1 buildHeuristicTrack path on the client
        # handles the rendering. This branch lets the client query the server
        # for the configured backend without reading config separately.
        return {"backend": "heuristic", "frames": []}

    # backend == "rhubarb"
    from probos.avatars.rhubarb_backend import generate_visemes
    audio_path = await store.get_path(attachment_id)
    frames = await generate_visemes(
        audio_path,
        binary_path=cfg.binary_path,
        timeout_seconds=cfg.timeout_seconds,
    )
    if not frames:
        # generate_visemes already log-and-degraded; tell the client.
        return {"backend": "heuristic", "frames": []}
    return {
        "backend": "rhubarb",
        "frames": [
            {"time": f.time, "duration": f.duration, "viseme": f.viseme}
            for f in frames
        ],
    }


@router.get("/tts/status")
async def tts_status(
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-738 — One-time feature probe for the browser.

    The browser caches this response in module-level state in ``voice.ts``
    and skips ``POST /api/avatars/tts`` entirely when ``backend != "piper"``.
    This preserves the Wave 156 zero-HTTP-per-utterance behaviour for
    operators who haven't opted in to server-side TTS (the default).
    """
    cfg = getattr(runtime.config, "tts", None)
    if cfg is None:
        return {"enabled": False, "backend": "browser"}
    return {
        "enabled": bool(cfg.enabled),
        "backend": str(cfg.backend),
    }


@router.get("/tts/voices")
async def tts_voices(
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """BF-291 / AD-738f — Enumerate locally-installed Piper voice models.

    Returns the voice catalog under ``tools/piper/voices/`` keyed by the
    paired ``<name>.onnx`` + ``<name>.onnx.json`` files (both must exist
    for the runtime to accept the voice). The HXI voice picker reads this
    list when the TTS backend is ``piper`` and falls back to
    ``speechSynthesis.getVoices()`` when the backend is ``browser``.

    Voice names follow the Piper convention
    ``<lang_country>-<voice>-<quality>`` (e.g. ``en_US-amy-medium``).
    """
    cfg = getattr(runtime.config, "tts", None)
    backend = str(getattr(cfg, "backend", "browser")) if cfg is not None else "browser"
    current = str(getattr(cfg, "voice_model", "")) if cfg is not None else ""

    voices: list[dict[str, Any]] = []
    try:
        from pathlib import Path

        base = Path("tools/piper/voices").resolve()
        if base.is_dir():
            for onnx in sorted(base.glob("*.onnx")):
                if not onnx.is_file():
                    continue
                cfg_path = onnx.with_suffix(".onnx.json")
                if not cfg_path.is_file():
                    continue
                name = onnx.stem  # strips .onnx -> "en_US-amy-medium"
                # Parse "<lang>-<voice>-<quality>" with a best-effort split.
                parts = name.split("-", 2)
                lang = parts[0] if len(parts) >= 1 else ""
                voice_id = parts[1] if len(parts) >= 2 else ""
                quality = parts[2] if len(parts) >= 3 else ""
                voices.append({
                    "name": name,
                    "lang": lang,
                    "voice": voice_id,
                    "quality": quality,
                    "size_mb": round(onnx.stat().st_size / (1024 * 1024), 1),
                })
    except Exception:
        # Tier-2 log-and-degrade — never raise here; the picker will fall
        # back to its browser-voices source.
        logger.warning("BF-291: tts_voices enumeration failed", exc_info=True)

    return {
        "backend": backend,
        "current": current,
        "voices": voices,
    }


@router.post("/tts")
async def synthesize_tts(
    req: Request,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-738 — Server-side TTS + lip-sync in a single round-trip.

    Body: ``{"text": "<utterance>"}``.

    Synthesizes ``text`` via the configured TTS backend, stores the audio
    bytes in AttachmentStore (AD-731 ref-shape invariant), runs rhubarb on
    the resulting file (reuses AD-721b-1 ``generate_visemes``), and returns
    audio + visemes together so the browser plays them in lockstep.

    Returns:
        - Best path: ``{"backend": "piper", "audio_attachment_id": "<sha256>",
          "mime": "audio/wav", "visemes": [...], "duration_ms": <int>}``
        - Honest-degrade: ``{"backend": "disabled", "audio_attachment_id": null,
          "mime": null, "visemes": [], "duration_ms": 0}`` — browser falls
          back to ``SpeechSynthesisUtterance``.
    """
    try:
        return await _synthesize_tts_impl(req, runtime)
    except HTTPException:
        raise
    except Exception:
        # BF-280: surface the actual error. Until the AD-738 endpoint's failure
        # modes are mapped, a bare 500 from FastAPI's default handler leaves no
        # log entry — operators only see "everything still sounds the same"
        # because the browser silently falls back to SpeechSynthesis. Logging
        # at exception level here gives diagnostic visibility without changing
        # the user-visible response shape.
        logger.exception("AD-738: /api/avatars/tts crashed")
        raise


async def _synthesize_tts_impl(req: Request, runtime: Any) -> dict[str, Any]:
    cfg = getattr(runtime.config, "tts", None)
    if cfg is None or not cfg.enabled or cfg.backend == "browser":
        return {
            "backend": "disabled",
            "audio_attachment_id": None,
            "mime": None,
            "visemes": [],
            "duration_ms": 0,
        }

    payload = await req.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_body")
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="invalid_text")
    if len(text) > 4096:
        # Defense-in-depth: cap text length at the boundary. Piper handles
        # long input but a runaway prompt shouldn't tie up the subprocess.
        raise HTTPException(status_code=413, detail="text_too_long")

    # AD-738e-1: optional ``emotion`` is a v1 EmotionalIntent name.
    # Tier-1 boundary validation: non-string / overlong values are
    # silently treated as None (no override). PiperBackend itself
    # validates the name against the override table.
    emotion = payload.get("emotion")
    if not isinstance(emotion, str) or len(emotion) > 64 or not emotion.strip():
        emotion = None

    # BF-291 / AD-738f: optional per-call ``voice_name`` (Piper voice model
    # name e.g. ``en_US-ryan-medium``). Tier-1 boundary validation; bad
    # values fall back to the configured ``tts.voice_model`` silently.
    # Backend only honors this when its underlying engine supports per-call
    # voice overrides (Piper does; null does not).
    voice_name = payload.get("voice_name")
    if not isinstance(voice_name, str) or len(voice_name) > 128 or not voice_name.strip():
        voice_name = None
    elif "/" in voice_name or "\\" in voice_name or ".." in voice_name:
        # Defense-in-depth: voice_name is used to resolve a path under
        # tools/piper/voices/. Reject path-traversal characters at the
        # boundary even though _resolve_voice_model also validates.
        voice_name = None

    from probos.audio.tts import select_backend
    backend = select_backend(cfg.backend, cfg)
    result = await backend.synthesize(text, emotion=emotion, voice_override=voice_name)
    if result is None:
        return {
            "backend": "disabled",
            "audio_attachment_id": None,
            "mime": None,
            "visemes": [],
            "duration_ms": 0,
        }

    # AD-731 invariant: audio bytes flow through AttachmentStore as
    # content-addressable SHA-256 refs. The response carries only the ref.
    # Canonical pattern from src/probos/routers/chat.py:665-692:
    #     actual_hash = hashlib.sha256(blob).hexdigest()
    #     await store.write(actual_hash, blob, declared_mime)
    import hashlib
    from probos.routers.chat import _get_attachment_store
    store = _get_attachment_store(runtime)
    attachment_id = hashlib.sha256(result.audio_bytes).hexdigest()
    await store.write(attachment_id, result.audio_bytes, result.mime)

    # Reuse AD-721b-1 rhubarb backend by direct internal call. lipsync.backend
    # may be "heuristic" (default) — in that case skip rhubarb and let the
    # browser fall back to its heuristic schedule for THIS audio.
    visemes_payload: list[dict[str, Any]] = []
    lipsync_cfg = getattr(runtime.config, "lipsync", None)
    if lipsync_cfg is not None and lipsync_cfg.enabled and lipsync_cfg.backend == "rhubarb":
        from probos.avatars.rhubarb_backend import generate_visemes
        audio_path = await store.get_path(attachment_id)
        frames = await generate_visemes(
            audio_path,
            binary_path=lipsync_cfg.binary_path,
            timeout_seconds=lipsync_cfg.timeout_seconds,
        )
        visemes_payload = [
            {"time": f.time, "duration": f.duration, "viseme": f.viseme}
            for f in frames
        ]

    # Duration: parse from WAV header. Cheap and self-contained.
    duration_ms = _wav_duration_ms(result.audio_bytes)

    return {
        "backend": backend.name,
        "audio_attachment_id": attachment_id,
        "mime": result.mime,
        "visemes": visemes_payload,
        "duration_ms": duration_ms,
    }


def _wav_duration_ms(wav_bytes: bytes) -> int:
    """Parse WAV header to extract duration in milliseconds.

    Tier-2 log-and-degrade: any parse failure returns ``0``. The browser
    treats ``0`` as "unknown duration"; the ``<audio>`` element knows
    its own duration once metadata loads.
    """
    import struct

    try:
        if len(wav_bytes) < 44 or wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
            return 0
        sample_rate = struct.unpack_from("<I", wav_bytes, 24)[0]
        bits_per_sample = struct.unpack_from("<H", wav_bytes, 34)[0]
        num_channels = struct.unpack_from("<H", wav_bytes, 22)[0]
        # Find the data chunk (may not be at offset 36 if fmt has extras).
        idx = 12
        while idx < len(wav_bytes) - 8:
            chunk_id = wav_bytes[idx:idx + 4]
            chunk_size = struct.unpack_from("<I", wav_bytes, idx + 4)[0]
            if chunk_id == b"data":
                bytes_per_sample = (bits_per_sample // 8) * num_channels
                if bytes_per_sample == 0 or sample_rate == 0:
                    return 0
                num_samples = chunk_size // bytes_per_sample
                return int((num_samples / sample_rate) * 1000)
            idx += 8 + chunk_size
        return 0
    except (struct.error, IndexError, ZeroDivisionError):
        return 0
