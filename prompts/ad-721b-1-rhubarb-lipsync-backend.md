# AD-721b-1 — Server-side rhubarb-lip-sync backend

**Status:** Ready for Builder
**GH issue:** [#559](https://github.com/seangalliher/com/seangalliher/ProbOS/issues/559) (closes)
**Parent AD:** AD-721b v1 (heuristic 5-vowel viseme driver, shipped Wave 138). Replaces the heuristic phoneme schedule with real visemes derived from real audio.
**Sibling:** AD-721b-2 (browser real-audio capture; Wave 155 — depends on the `POST /api/avatars/lipsync` endpoint shipped by THIS prompt).
**Wave:** 155
**Estimated tests:** ≥ 16 new in `tests/test_ad721b1_rhubarb_backend.py` (14 backend + 2 mime allow-list regression)

---

## Captain decisions baked in

1. **Operator-provided binary, MIT-licensed.** rhubarb-lip-sync (https://github.com/DanielSWolf/rhubarb-lip-sync) is **MIT** — verified `gh api repos/DanielSWolf/rhubarb-lip-sync/license` returns `"key": "mit"`. Top of the permissive preference list per Captain License hygiene rule. ProbOS provides the wrapper; operator drops the platform-specific binary at `tools/rhubarb/rhubarb.exe` (Windows) or `tools/rhubarb/rhubarb` (Linux/macOS). Binary is **never shipped** in the repo — `tools/` is already covered by `.gitignore` line 3 (`/tools/`).
2. **Honest-degrade default.** Config default `lipsync.backend = "heuristic"` (existing AD-721b v1 path). Operator opts in by setting `lipsync.backend: "rhubarb"` AND providing the binary. If the binary is missing OR a probe fails OR a subprocess fails, the system logs WARNING and falls back to the heuristic path — speech must NEVER stop animating because of a viseme failure (mirrors the AD-721b v1 Tier-2 contract at `ui/src/audio/lipSyncTrack.ts:15-20`).
3. **9 → 15 viseme map.** rhubarb emits the Preston Blair 9-set (A/B/C/D/E/F/G/H/X). The renderer (`ui/src/audio/lipSyncTrack.ts:25-27`) consumes the Oculus 15-set (`sil`/`PP`/`FF`/`TH`/`DD`/`kk`/`CH`/`SS`/`nn`/`RR`/`aa`/`E`/`ih`/`oh`/`ou`). Backend produces the 9-set; mapping to the renderer's 15-set lives at the wire boundary (Section 3).
4. **Subprocess discipline.** `asyncio.create_subprocess_exec` with absolute path to the binary, `-f json` for structured output, 30s default timeout, full stderr capture for diagnostic logs. Never `shell=True`. The audio path passed to rhubarb is always an `AttachmentStore.get_path()` result (already `resolve()`-d, sandboxed under `_platform_data_dir()`).
5. **No Python dep added.** rhubarb is a binary tool, not a Python package. Do NOT add anything to `pyproject.toml`. The wrapper uses `asyncio.subprocess` from the standard library only.

---

## Problem (verified diagnostic baseline — 2026-05-12)

AD-721b v1 (`ui/src/audio/lipSyncTrack.ts`, shipped Wave 138) drives the five VRoid vowel morphs from a **text-only heuristic**: each character maps to a viseme, each viseme dwells for 80 ms scaled by `SpeechSynthesisUtterance.rate`. Two limitations Counselor (Echo) flagged on 2026-05-09 follow-up:

- **No phonetic alignment.** "Cat" and "cot" produce identical viseme schedules because the heuristic doesn't know phonemes.
- **No audio-derived timing.** Word stress, silences, breath pauses are invisible — the mouth dwells uniformly.

The real-time path is:

```
text → buildHeuristicTrack() → VisemeSegment[] → CrewVRM useFrame samples → VRM morph weights
```

After AD-721b-1, the path becomes:

```
audio bytes (AttachmentStore ref)
  → POST /api/avatars/lipsync
  → rhubarb subprocess (-f json -r phonetic)
  → 9-viseme PrestonBlairFrame[] parsed in rhubarb_backend.py
  → mapped to 15-viseme VisemeFrame[]
  → JSON response → CrewVRM consumes (Prompt 2 wires the consumer)
```

This prompt ships the **server side only**: the wrapper, the config, the endpoint, the mapping. Prompt 2 (AD-721b-2) ships the browser-side audio capture and consumer wiring.

---

## Solution

Three pieces:

1. New module `src/probos/avatars/rhubarb_backend.py` with the subprocess wrapper, version probe, and 9→15 viseme mapping. Honest-degrade is the load-bearing invariant.
2. New `LipSyncConfig` Pydantic model in `src/probos/config.py` with `enabled`, `backend`, `binary_path`, `timeout_seconds`. Default `backend = "heuristic"` so existing operators see zero behavior change.
3. New endpoint `POST /api/avatars/lipsync` in a NEW router file `src/probos/routers/avatars.py` (no `routers/avatars.py` exists today — verified). The endpoint takes an `attachment_id` (sha256 ref to a previously-uploaded audio blob via the existing `_validate_and_store_attachment` chain, AD-720), runs rhubarb, returns the viseme schedule.

---

## Section 0 — Files touched

| File | Change |
|---|---|
| `src/probos/avatars/__init__.py` | NEW (empty `"""AD-721b avatar pipeline."""` docstring) |
| `src/probos/avatars/rhubarb_backend.py` | NEW — `VisemeFrame` dataclass, `is_available()`, `probe_version()`, `generate_visemes()`, `_map_preston_blair_to_oculus()` |
| `src/probos/config.py` | (a) Extend `AttachmentsConfig.allowed_mime_types` default with `audio/webm` + `audio/wav`. (b) Add `LipSyncConfig` Pydantic model after `AttachmentsConfig`. (c) Add `lipsync: LipSyncConfig = Field(default_factory=LipSyncConfig)` to `Config`. |
| `src/probos/attachments/mime.py` | Extend `_SIGNATURES` with `audio/webm` (EBML magic) and `audio/wav` (RIFF/WAVE magic) so `validate_attachment_bytes` accepts the audio mimes that AD-721b-2 captures. |
| `src/probos/routers/avatars.py` | NEW — `POST /api/avatars/lipsync` endpoint |
| `src/probos/api.py` | Wire the new router into the existing tuple-iteration block at lines 191-209 (add `avatars` to BOTH the import tuple and the iteration tuple). |
| `tests/test_ad721b1_rhubarb_backend.py` | NEW — ≥ 16 tests (14 backend + 2 mime allow-list regression) |
| `PROGRESS.md` | Wave 155 entry; +tests count delta |
| `DECISIONS.md` | Append AD-721b-1 closure block |
| `docs/development/roadmap.md` | Mark AD-721b-1 shipped Wave 155; close [#559](https://github.com/seangalliher/ProbOS/issues/559) |
| `.gitignore` | **VERIFY only** — `/tools/` is already on line 3. No edit needed. |

**Do NOT touch:**
- `ui/src/audio/lipSyncTrack.ts` (heuristic path stays as the fallback; Prompt 2 wires the rhubarb consumer)
- `ui/src/components/profile/CrewVRM.tsx` (Prompt 2 territory)
- `ui/src/audio/voice.ts` (Prompt 2 territory)
- `_validate_and_store_attachment` / `_get_attachment_store` in `routers/chat.py` (reused as-is — only the allow-list default and the magic-byte signature table are extended; the validation chain itself is untouched)
- `src/probos/runtime.py` (router wiring lives in `src/probos/api.py`, NOT runtime.py — verified zero `include_router` calls in runtime.py)
- `pyproject.toml` (no Python dep added)
- AD-720/AD-731 attachment ref shape

---

## Section 0.5 — Mime allow-list extension (cross-prompt seam owner)

AD-721b-2 captures browser audio as `audio/webm` (or `audio/wav` fallback when the operator's `MediaRecorder` build doesn't support WebM) and uploads via the existing `POST /api/chat/attachments/multipart` endpoint. That endpoint delegates to `_validate_and_store_attachment` ([src/probos/routers/chat.py:614](src/probos/routers/chat.py#L614)), which enforces TWO gates the audio mimes must pass:

1. **Allow-list membership** ([src/probos/config.py:1124-1135](src/probos/config.py#L1124-L1135)) — `AttachmentsConfig.allowed_mime_types` default lists 9 image/text/PDF MIMEs. Audio MIMEs are absent. **A browser capture upload would 415 today.**
2. **Magic-byte sniff** ([src/probos/attachments/mime.py:74-90](src/probos/attachments/mime.py#L74-L90)) — `validate_attachment_bytes` only accepts MIMEs registered in `_SIGNATURES` (4 image MIMEs) or `_NON_IMAGE_MIMES` (5 text/PDF/JSON/CSV MIMEs). Even after extending the allow-list, an audio upload would fail with `unknown_declared_mime`.

This prompt OWNS the validation seam (Cloud-Ready Storage invariant: AD-721b-2 must not reach into the validator). Both extensions are surgical and verified-magic-byte.

### 0.5a. Extend `AttachmentsConfig.allowed_mime_types` default

In [src/probos/config.py](src/probos/config.py#L1124-L1135), the existing default factory list:

```python
SEARCH:
    allowed_mime_types: list[str] = Field(
        default_factory=lambda: [
            "image/png",
            "image/jpeg",
            "image/webp",
            "image/gif",
            "application/pdf",
            "text/plain",
            "text/markdown",
            "application/json",
            "text/csv",
        ],
    )
REPLACE:
    allowed_mime_types: list[str] = Field(
        default_factory=lambda: [
            "image/png",
            "image/jpeg",
            "image/webp",
            "image/gif",
            "application/pdf",
            "text/plain",
            "text/markdown",
            "application/json",
            "text/csv",
            # AD-721b-1 (Wave 155): browser-captured utterance audio for the
            # rhubarb-lip-sync backend. Both mimes have unambiguous magic
            # bytes registered in attachments/mime.py._SIGNATURES; magic-byte
            # sniffing remains the primary correctness signal.
            "audio/webm",
            "audio/wav",
        ],
    )
END REPLACE
```

No `system.yaml` edit required: there is no `attachments:` block in `config/system.yaml` (verified — zero matches for `attachments|allowed_mime|lipsync`), so the Pydantic default is authoritative.

### 0.5b. Extend `_SIGNATURES` in `attachments/mime.py`

In [src/probos/attachments/mime.py](src/probos/attachments/mime.py#L15-L22), the existing signature table:

```python
SEARCH:
# Magic-byte signatures for the four allowed MIMEs.
# Each entry: list of (offset, signature_bytes) tuples — ALL must match.
_SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
    "image/png":  [(0, b"\x89PNG\r\n\x1a\n")],
    "image/jpeg": [(0, b"\xff\xd8\xff")],
    "image/gif":  [(0, b"GIF87a"), (0, b"GIF89a")],   # either alternative
    "image/webp": [(0, b"RIFF"), (8, b"WEBP")],       # both required
}

# MIMEs whose sigs are alternatives (any-of) instead of conjunctions (all-of).
_ANY_OF: frozenset[str] = frozenset({"image/gif"})
REPLACE:
# Magic-byte signatures for the allowed binary MIMEs.
# Each entry: list of (offset, signature_bytes) tuples — ALL must match
# unless the MIME is in ``_ANY_OF`` (any-of alternative match).
_SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
    "image/png":  [(0, b"\x89PNG\r\n\x1a\n")],
    "image/jpeg": [(0, b"\xff\xd8\xff")],
    "image/gif":  [(0, b"GIF87a"), (0, b"GIF89a")],   # either alternative
    "image/webp": [(0, b"RIFF"), (8, b"WEBP")],       # both required
    # AD-721b-1 (Wave 155): browser-captured utterance audio for the
    # rhubarb-lip-sync backend. WebM containers begin with the EBML magic
    # (\x1a\x45\xdf\xa3); WAV files share RIFF with WebP but with WAVE at
    # offset 8 (rhubarb-lip-sync supports WAV natively).
    "audio/webm": [(0, b"\x1a\x45\xdf\xa3")],
    "audio/wav":  [(0, b"RIFF"), (8, b"WAVE")],       # both required
}

# MIMEs whose sigs are alternatives (any-of) instead of conjunctions (all-of).
_ANY_OF: frozenset[str] = frozenset({"image/gif"})
END REPLACE
```

The image-validator entry point `validate_image_bytes` is intentionally narrow (its name reflects that). The general entry point `validate_attachment_bytes` already short-circuits to `_SIGNATURES`-driven validation when `declared_mime in _SIGNATURES` (line 87-88), so the audio MIMEs flow through the conjunction-match logic identically to `image/webp`. No further change to `validate_attachment_bytes`, no new branches, no `_NON_IMAGE_MIMES` extension required.

### 0.5c. No `system.yaml` edit

Verified: `grep -n "attachments:" config/system.yaml` returns zero hits. The Pydantic default is the operator-visible truth. Operators who currently pin `attachments.allowed_mime_types` in their YAML can opt-in by appending the two audio mimes themselves; the operator-facing doc note in Section 1c records the change.

---

## Section 1 — Config

### 1a. `LipSyncConfig` Pydantic model

Add to `src/probos/config.py` immediately after `AttachmentsConfig` (verify location — search for `class AttachmentsConfig` in config.py):

```python
class LipSyncConfig(BaseModel):
    """AD-721b-1 — Server-side lip-sync backend selection.

    Default: ``heuristic`` — the AD-721b v1 text→viseme driver in
    ``ui/src/audio/lipSyncTrack.ts``. Operator opts in to ``rhubarb``
    by setting ``backend: "rhubarb"`` AND providing the binary at
    ``binary_path``. If the binary is missing or a probe fails, the
    system logs WARNING and degrades to the heuristic path — speech
    must NEVER stop animating because of a viseme failure.
    """

    enabled: bool = True
    """Master switch for the lip-sync pipeline. ``False`` disables both
    backends — CrewVRM falls back to the AD-721 D5 amplitude path."""

    backend: Literal["heuristic", "rhubarb"] = "heuristic"
    """``heuristic``: AD-721b v1 text→viseme. ``rhubarb``: subprocess to
    rhubarb-lip-sync for phonetic alignment of real audio."""

    binary_path: str = "tools/rhubarb/rhubarb"
    """Path (relative to repo root or absolute) to the rhubarb binary.
    On Windows the wrapper auto-appends ``.exe`` if the literal path
    does not exist. Operator places the binary themselves; the repo
    never ships it (gitignored under ``/tools/``)."""

    timeout_seconds: float = 30.0
    """Subprocess timeout. rhubarb on a 5-10s utterance typically takes
    1-3s; the default leaves ample headroom for cold disk reads. Tier-2
    log-and-degrade on TimeoutExpired — falls back to heuristic."""
```

`Literal` import: verify whether `from typing import Literal` is already imported at the top of `config.py`. If not, add it. Do NOT use a `str` field with a manual validator — `Literal` gives Pydantic the validation for free.

### 1b. Wire into `Config`

Find the top-level `Config` class in `config.py` (search for `class Config(BaseModel):` or similar). Add the `lipsync` field next to the existing `attachments: AttachmentsConfig = Field(default_factory=AttachmentsConfig)` line:

```python
lipsync: LipSyncConfig = Field(default_factory=LipSyncConfig)
```

### 1c. `config/system.yaml` — no edit

Verified: `config/system.yaml` has no `attachments:` or `lipsync:` block (zero matches for `attachments|allowed_mime|lipsync`). Pydantic defaults are authoritative for both `AttachmentsConfig` (already extended in Section 0.5a) and `LipSyncConfig` (defaults to `backend = "heuristic"`). Operator opt-in for rhubarb is documented at the call site only — Section 5 documentation update covers the operator-facing instructions in `docs/`. **Do NOT add a commented-out example block to `system.yaml`.**

---

## Section 2 — `rhubarb_backend.py`

Create `src/probos/avatars/__init__.py`:

```python
"""AD-721b avatar pipeline — server-side viseme generation."""
```

Create `src/probos/avatars/rhubarb_backend.py`. Full module body:

```python
"""AD-721b-1 — rhubarb-lip-sync subprocess wrapper.

License posture: rhubarb-lip-sync is MIT (verified 2026-05-12 via
``gh api repos/DanielSWolf/rhubarb-lip-sync/license``). ProbOS provides
this wrapper; the operator provides the binary at ``lipsync.binary_path``.
The repo never ships the binary — ``/tools/`` is gitignored.

Tier-2 log-and-degrade: every callable in this module returns either
None or an empty list on failure; ``CrewVRM`` (Prompt 2) treats either
as the signal to fall back to the AD-721b v1 heuristic path.
"""

from __future__ import annotations

import asyncio
import json
import logging
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

_PRESTON_BLAIR_TO_OCULUS: dict[str, str] = {
    "A": "PP",   # closed mouth — m/b/p
    "B": "kk",   # slightly open — k/g/n/t/d/s/z
    "C": "E",    # open mouth — e (as in "bed")
    "D": "aa",   # wide open — a (as in "father")
    "E": "oh",   # rounded — o (as in "go")
    "F": "ou",   # narrow — u (as in "you")
    "G": "FF",   # f/v
    "H": "RR",   # l/r
    "X": "sil",  # rest / silence
}


@dataclass(frozen=True)
class VisemeFrame:
    """One viseme segment in the schedule.

    ``time`` and ``duration`` are seconds (rhubarb's native unit).
    ``viseme`` is the Oculus 15-set key consumed by the renderer.
    """

    time: float
    duration: float
    viseme: str


def _map_preston_blair_to_oculus(pb: str) -> str:
    """Lookup with fallback to ``sil`` for any unknown shape (forward-compat
    if rhubarb adds a viseme — log-and-degrade rather than crash)."""
    mapped = _PRESTON_BLAIR_TO_OCULUS.get(pb)
    if mapped is None:
        logger.warning(
            "AD-721b-1: unknown Preston Blair viseme %r; degrading to sil", pb
        )
        return "sil"
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
        proc = await asyncio.create_subprocess_exec(
            str(binary_path),
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning(
                "AD-721b-1: rhubarb --version timed out after %ss", timeout_seconds
            )
            return None
        if proc.returncode != 0:
            logger.warning(
                "AD-721b-1: rhubarb --version returned %s", proc.returncode
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
        proc = await asyncio.create_subprocess_exec(
            str(resolved_binary),
            "-f", "json",
            str(audio_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning(
                "AD-721b-1: rhubarb timed out after %ss on %s; degrading",
                timeout_seconds, audio_path.name,
            )
            return []
        if proc.returncode != 0:
            logger.warning(
                "AD-721b-1: rhubarb exit=%s on %s; stderr=%s",
                proc.returncode, audio_path.name,
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
        frames.append(
            VisemeFrame(
                time=float(start),
                duration=float(end - start),
                viseme=_map_preston_blair_to_oculus(value),
            )
        )
    return frames
```

**Notes:**
- The subprocess invocation deliberately omits `--machineReadable`. rhubarb uses that flag to suppress the human-readable progress bar from stderr, but the wrapper already discards stderr (it's only logged on non-zero exit). Removing the flag eliminates a version-coupling risk for newer/older rhubarb releases.
- The 9-viseme mapping is intentionally lossy on the consonant side. The renderer's vowel-only morph weights mean the Oculus consonants (PP/FF/TH/DD/kk/CH/SS/nn/RR) all collapse to a slightly-open mouth at the renderer level anyway (`ui/src/audio/lipSyncTrack.ts:78-92`).

---

## Section 3 — `POST /api/avatars/lipsync` endpoint

Create `src/probos/routers/avatars.py`. Full body:

```python
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

    Returns: ``{"backend": "rhubarb"|"heuristic", "frames": [{"time", "duration", "viseme"}]}``
    where an empty ``frames`` list means the backend was unavailable AND the
    client should fall back to its own heuristic path (Prompt 2).
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
        # Backend is set to heuristic — caller does the work client-side.
        # Return empty frames; the existing AD-721b v1 buildHeuristicTrack
        # path on the client handles the rendering. This branch lets the
        # client query the server for the configured backend without having
        # to read config separately.
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
```

### 3a. Wire the router into the FastAPI app (in `src/probos/api.py`, NOT `runtime.py`)

Verified 2026-05-12: `src/probos/runtime.py` contains **zero** `include_router` calls. The FastAPI `app` object is constructed in [src/probos/api.py:121](src/probos/api.py#L121) and routers are registered in a single tuple-iteration block at [src/probos/api.py:191-209](src/probos/api.py#L191-L209). Two surgical edits — one to the import tuple, one to the iteration tuple — both inside the same block.

```python
SEARCH:
    # ── Router registrations (AD-516) ─────────────────────────────────
    from probos.routers import (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        clinical, counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic, diagnostic_context, nl_graph_query,
    )
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        clinical, counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic, diagnostic_context, nl_graph_query,
    ):
        app.include_router(r.router)
REPLACE:
    # ── Router registrations (AD-516) ─────────────────────────────────
    from probos.routers import (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        clinical, counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic, diagnostic_context, nl_graph_query,
        avatars,  # AD-721b-1 (Wave 155): /api/avatars/lipsync
    )
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        clinical, counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic, diagnostic_context, nl_graph_query,
        avatars,
    ):
        app.include_router(r.router)
END REPLACE
```

Do NOT introduce a `from probos.routers.avatars import router as avatars_router` aliased import — the existing block uses module-level import + `r.router` attribute access. Match the prevailing pattern verbatim.

---

## Section 4 — Tests (≥ 16 in `tests/test_ad721b1_rhubarb_backend.py`)

Each test = one behavior. Use `pytest-asyncio`. Mirror the `_Fake*` stub style of `tests/test_ad732_vision_tier.py`.

### Backend availability + version probe (3 tests)

1. **`test_is_available_false_when_binary_missing`** — `await is_available("/nonexistent/rhubarb")` returns `False`. No exception raised. WARNING logged.
2. **`test_is_available_false_when_version_probe_times_out`** — Cross-platform: monkeypatch `asyncio.create_subprocess_exec` to return a stub process whose `communicate()` hangs (`asyncio.sleep(60)`). Mirror the stub-process pattern from test #4. `await is_available(..., timeout_seconds=0.2)` returns `False`. WARNING logged. NO `pytest.mark.skipif` — the monkeypatch removes the platform dependency entirely.
3. **`test_resolve_binary_path_appends_exe_on_windows`** — Unit test on `_resolve_binary_path` directly. Use `monkeypatch.setattr(sys, "platform", "win32")` and `tmp_path` with a fake `.exe` file. Assert the resolved path ends in `.exe` even when the configured path does not.

### Subprocess + JSON parsing (4 tests)

4. **`test_generate_visemes_subprocess_timeout_returns_empty`** — Stub `asyncio.create_subprocess_exec` to return a process whose `communicate()` hangs. Assert `await generate_visemes(...)` returns `[]` and a WARNING was logged.
5. **`test_generate_visemes_malformed_json_returns_empty`** — Stub the subprocess to write `"not json {{"` to stdout. Assert `[]` returned, WARNING logged.
6. **`test_generate_visemes_missing_mouthCues_returns_empty`** — Stub stdout to `'{"metadata": {}}'` (valid JSON, no `mouthCues`). Assert `[]` returned, WARNING logged.
7. **`test_generate_visemes_happy_path_maps_visemes`** — Stub stdout to a realistic rhubarb JSON: `{"mouthCues": [{"start": 0.0, "end": 0.12, "value": "X"}, {"start": 0.12, "end": 0.30, "value": "D"}, {"start": 0.30, "end": 0.45, "value": "A"}]}`. Assert returned list has 3 `VisemeFrame`s with monotonic `time`, correct mapped visemes (`sil`, `aa`, `PP`).

### Viseme mapping (1 test)

8. **`test_map_preston_blair_to_oculus_covers_all_9_shapes`** — Iterate `["A","B","C","D","E","F","G","H","X"]` and assert each maps to a known `OculusViseme`. Plus assert `_map_preston_blair_to_oculus("Z")` returns `"sil"` (forward-compat fallback) and a WARNING was logged.

### Endpoint integration (3 tests)

9. **`test_endpoint_returns_disabled_when_lipsync_disabled`** — Build a runtime fixture with `Config(lipsync=LipSyncConfig(enabled=False))`. POST to `/api/avatars/lipsync` with a valid attachment_id. Assert response `{"backend": "disabled", "frames": []}`.
10. **`test_endpoint_returns_heuristic_when_backend_configured_heuristic`** — Default config. Upload a small audio attachment via `_validate_and_store_attachment`, POST the resulting hash. Assert `{"backend": "heuristic", "frames": []}`. Confirm the rhubarb subprocess was NOT invoked (monkeypatch `generate_visemes` to raise if called).
11. **`test_endpoint_invalid_attachment_id_returns_400`** — POST `{"attachment_id": "not-hex"}`. Assert HTTP 400 with `detail == "invalid_attachment_id"`.
12. **`test_endpoint_unknown_attachment_id_returns_404`** — POST a valid-format but unstored hash. Assert HTTP 404 with `detail == "attachment_not_found"`.

### Boundary tests (2 tests)

13. **`test_generate_visemes_empty_audio_file_returns_empty`** — Pass an empty 0-byte file. Subprocess stub returns exit code 1 (rhubarb refuses empty input). Assert `[]` returned, WARNING logged with stderr in the message.
14. **`test_generate_visemes_filters_inverted_time_ranges`** — Stub a JSON cue where `end < start`. Assert that cue is skipped (defensive against rhubarb edge cases) and the rest of the cues are still parsed.

### Mime allow-list regression — Section 0.5 (2 tests)

15. **`test_attachments_default_allows_audio_webm_and_wav`** — Construct a fresh `Config()` and assert `"audio/webm" in cfg.attachments.allowed_mime_types` AND `"audio/wav" in cfg.attachments.allowed_mime_types`. Defends against accidental allow-list regression.
16. **`test_validate_attachment_bytes_accepts_audio_mime_magic_bytes`** — Two sub-assertions in one test: (a) `validate_attachment_bytes(b"\x1a\x45\xdf\xa3rest...", "audio/webm")` returns `(True, "audio/webm")`. (b) `validate_attachment_bytes(b"RIFF\x00\x00\x00\x00WAVErest...", "audio/wav")` returns `(True, "audio/wav")`. Plus negative: `validate_attachment_bytes(b"not-a-webm", "audio/webm")` returns `(False, "header_mismatch")`.

### Test gates

After Section 0.5 (mime allow-list): `pytest tests/test_ad721b1_rhubarb_backend.py::test_attachments_default_allows_audio_webm_and_wav tests/test_ad721b1_rhubarb_backend.py::test_validate_attachment_bytes_accepts_audio_mime_magic_bytes tests/ -k "attachments or mime" -q -n 0`.
After Section 1 (config): `pytest tests/test_ad721b1_rhubarb_backend.py::test_*config* tests/test_config*.py -q`.
After Section 2 (backend module): `pytest tests/test_ad721b1_rhubarb_backend.py -v -n 0`.
After Section 3 (router): full focused suite + grep that the avatars router is wired in `api.py`: `grep -n "avatars" src/probos/api.py` should show 2 hits inside the lines 191-209 block (one in the `from probos.routers import (...)` tuple, one in the `for r in (...)` tuple). `grep -n "include_router" src/probos/runtime.py` MUST stay at zero hits.

Final gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`.

---

## Section 5 — Documentation

- **`DECISIONS.md`** — Append AD-721b-1 closure block. Cite: (a) MIT license verification command + result, (b) the 9→15 viseme mapping rationale (consonant-side is for completeness; renderer uses vowels only), (c) the honest-degrade contract (binary missing → `[]` → client falls back to heuristic). Reference the parent AD-721b v1 entry (decisions-era-4-evolution.md:5170 and DECISIONS.md:1592).
- **`PROGRESS.md`** — Wave 155 entry. AD-721b-1 shipped. Test count delta. Highest AD line stays at AD-734 (this is a sub-AD of an existing parent).
- **`docs/development/roadmap.md`** — Mark AD-721b-1 shipped Wave 155. Close [#559](https://github.com/seangalliher/ProbOS/issues/559).

---

## Section 6 — License Disposition

| Item | License | Posture |
|---|---|---|
| `rhubarb-lip-sync` (DanielSWolf) | **MIT** (verified 2026-05-12 via `gh api repos/DanielSWolf/rhubarb-lip-sync/license` → `"key": "mit"`) | **Operator-provided binary.** ProbOS ships only the wrapper module + endpoint. The repo never ships the binary itself. `/tools/` is already on `.gitignore` line 3, so the binary at `tools/rhubarb/rhubarb` will be ignored automatically. |
| Python deps added | None | This prompt adds zero entries to `pyproject.toml`. The wrapper uses only `asyncio.subprocess` from the standard library. |
| ProbOS code added | Apache 2.0 (matches repo) | New files under `src/probos/avatars/` carry the same license posture as the rest of the repo. |

The MIT license requires attribution; the wrapper module's docstring carries the upstream attribution. No NOTICE file change required for MIT.

---

## Engineering Principles compliance

- **Single Responsibility**: `rhubarb_backend.py` does one thing — wrap the subprocess. Mapping, config, endpoint each in their own location.
- **Open/Closed**: New backend extends via `LipSyncConfig.backend = Literal[..., "rhubarb"]`. Adding a future backend (e.g. `"whisper-cpp"` for AD-721b-3) is a one-line `Literal` extension + a new module.
- **Dependency Inversion**: The router depends on `_get_attachment_store(runtime)` (existing seam), not on a concrete store class.
- **Fail Fast / Log-and-Degrade**: Every failure path returns `[]` or `False` with a WARNING. NEVER raises.
- **Cloud-Ready Storage**: Audio blobs go through the existing AttachmentStore Protocol. Wrapper gets a `Path` from `store.get_path()` — no direct filesystem access.
- **Type annotations**: All public functions fully typed. `VisemeFrame` is a frozen dataclass.
- **Logging quality**: Every WARNING log line names what failed, includes the file/timeout context, and the implicit recovery (heuristic fallback).
- **Async hygiene**: All subprocess I/O is async with explicit `asyncio.wait_for(...)` timeouts. `proc.kill()` on timeout to prevent zombie processes.

---

## What this does NOT change

- **No client-side code.** `ui/src/audio/lipSyncTrack.ts`, `ui/src/components/profile/CrewVRM.tsx`, `ui/src/audio/voice.ts` are untouched. Prompt 2 (AD-721b-2) wires the consumer.
- **No change to `_validate_and_store_attachment`, `_get_attachment_store`, or `AttachmentStore` Protocol.** Reused as-is.
- **No change to AD-721b v1 heuristic path.** It stays as the fallback. `lipsync.backend = "heuristic"` (the default) is bit-for-bit equivalent to today's behavior.
- **No federation / cross-mesh dispatch.** Lip-sync runs locally on the node serving the HXI.
- **No caching.** Each request runs rhubarb. Caching would be a forward marker if measurement showed it was needed; today's 1-3s subprocess time on a typical utterance is acceptable.
- **No streaming.** The endpoint is request/response over a single audio blob. Streaming visemes during long-form TTS is out of scope.
- **No `.gitignore` edit.** `/tools/` is already line 3; no change needed.

---

## Forward markers

- **AD-721b-3** — whisper.cpp WASM tiny.en for offline phoneme alignment ([#561](https://github.com/seangalliher/ProbOS/issues/561), already filed). When this lands, the `LipSyncConfig.backend` Literal extends to `"whisper-cpp"` and a new `src/probos/avatars/whisper_cpp_backend.py` module joins.
- **AD-721b-4** (potential) — rhubarb-lip-sync WASM port for in-browser execution. Would eliminate the round-trip and the binary-distribution problem, but no maintained WASM port exists today (verify before filing). If filed, `lipsync.backend = "rhubarb-wasm"` joins the Literal.
- **AD-721b-5** (potential) — viseme cache keyed by `audio_sha256`. Cheap memory-only cache; defer until profiling shows need.

---

## Acceptance criteria

- ✅ `AttachmentsConfig.allowed_mime_types` default includes `audio/webm` AND `audio/wav` (Section 0.5a).
- ✅ `attachments/mime.py._SIGNATURES` includes `audio/webm` (EBML magic) and `audio/wav` (RIFF/WAVE magic) (Section 0.5b).
- ✅ `LipSyncConfig` exposes `enabled`, `backend`, `binary_path`, `timeout_seconds` with the Literal validator on `backend`.
- ✅ `Config` has `lipsync: LipSyncConfig = Field(default_factory=LipSyncConfig)`.
- ✅ `src/probos/avatars/rhubarb_backend.py` exposes `VisemeFrame`, `is_available`, `probe_version`, `generate_visemes`, all log-and-degrade.
- ✅ `POST /api/avatars/lipsync` returns `{"backend": ..., "frames": [...]}`. Honest-degrade: `disabled` / `heuristic` / `rhubarb`.
- ✅ Endpoint reuses `_get_attachment_store(runtime)` and `store.exists/get_path` — no second AttachmentStore instantiation.
- ✅ Router is wired in `src/probos/api.py` lines 191-209 (NOT `runtime.py`) — `grep -n "include_router" src/probos/runtime.py` returns zero.
- ✅ All ≥ 16 new tests in `tests/test_ad721b1_rhubarb_backend.py` pass.
- ✅ Existing test suite green: `pytest tests/ -q -n 4 --dist=loadfile` minus the documented HEAD-flake tests (test_callsign_routing × 3, test_ad719_chat_fanout × 1, plus the 2 dreaming tests flagged in the Wave 154 close).
- ✅ `DECISIONS.md` AD-721b-1 entry includes the MIT license verification, mapping rationale, and the parent reference.
- ✅ `PROGRESS.md` Wave 155 entry shows AD-721b-1 closed + test count delta. AD-734 remains the highest-AD line.
- ✅ `roadmap.md` AD-721b-1 row marked shipped Wave 155 with `Closes #559`.
- ✅ `tools/` remains gitignored — verify line 3 of `.gitignore` says `/tools/`.
- ✅ Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-12)

```
grep -n "buildHeuristicTrack" ui/src/audio/lipSyncTrack.ts
  205: export function buildHeuristicTrack(

grep -n "VisemeKey" ui/src/audio/lipSyncTrack.ts
  25-27: export type VisemeKey = 'sil' | 'PP' | 'FF' | 'TH' | 'DD' | 'kk'
                | 'CH' | 'SS' | 'nn' | 'RR' | 'aa' | 'E' | 'ih' | 'oh' | 'ou';

grep -n "class AttachmentsConfig" src/probos/config.py
  (use grep at build time — surrounding location for the new LipSyncConfig)

grep -n "_get_attachment_store\|_validate_and_store_attachment" src/probos/routers/chat.py
  599: def _get_attachment_store(runtime: Any) -> Any:
  614: async def _validate_and_store_attachment(

grep -n "include_router" src/probos/runtime.py
  (zero hits — confirmed 2026-05-12; runtime.py does NOT host the FastAPI app)

grep -n "include_router\|FastAPI(" src/probos/api.py
  121: app = FastAPI(title="ProbOS", version="0.1.0", lifespan=_lifespan)
  191: from probos.routers import (
  198: for r in (
  205:     app.include_router(r.router)
  (router-registration block lives at api.py:191-209 — Section 3a target)

grep -n "allowed_mime_types\|class AttachmentsConfig" src/probos/config.py
  1112: class AttachmentsConfig(BaseModel):
  1124:     allowed_mime_types: list[str] = Field(
  (current default lists 9 image/text/PDF MIMEs; no audio mimes — Section 0.5a target)

grep -n "_SIGNATURES\|_NON_IMAGE_MIMES\|validate_attachment_bytes" src/probos/attachments/mime.py
  17: _SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
  26: _ANY_OF: frozenset[str] = frozenset({"image/gif"})
  62: _NON_IMAGE_MIMES: frozenset[str] = frozenset({
  72: def validate_attachment_bytes(
  87:     if declared_mime in _SIGNATURES:
  88:         return validate_image_bytes(blob, declared_mime)
  (validate_attachment_bytes short-circuits to _SIGNATURES when MIME is registered there — Section 0.5b target)

grep -n "attachments:\|allowed_mime\|lipsync" config/system.yaml
  (zero hits — Pydantic defaults are authoritative; no system.yaml edit needed)

grep -n "tools/" .gitignore
  3:/tools/

grep -nE "^### AD-7[3-9][0-9]" DECISIONS.md
  Highest: AD-734 — Wire-shape contract test for the vision pipeline (Wave 153)
  (AD-730-5, AD-730-1, AD-730-1-1 are sub-ADs of AD-730; not the highest top-level number)

grep -n "AD-721b-1\|AD-721b-2\|AD-721b-3" docs/development/roadmap.md
  355: | AD-721b | ... — SHIPPED Wave 138 |
  356: | AD-721b-1 | Server-side rhubarb-lip-sync backend ... | #559 | 3 |
  357: | AD-721b-2 | Browser-side real-audio capture via MediaStreamDestination | #560 | 3 |
  358: | AD-721b-3 | whisper.cpp WASM tiny.en ... | #561 | 4 |

License verification:
  gh api repos/DanielSWolf/rhubarb-lip-sync/license  →  "key": "mit"
```


---

## Revision (2026-05-12) — pass-1 review fold-in

Applied Required findings R1 + R2 from prompts/Reviews/ad-721b-1-rhubarb-lipsync-backend-review.md and Recommended #2/#3/#4 + Nit #3.

| Finding | Severity | Resolution |
|---|---|---|
| **R1 — wrong-file router wiring** | Required (build-blocker) | Section 3a rewritten with explicit SEARCH/REPLACE against the verified tuple-iteration block at `src/probos/api.py:191-209`. Both the import tuple and the iteration tuple receive `avatars` in a single edit. `runtime.py` removed from the Files-touched table; explicit "do NOT touch `runtime.py`" added. |
| **R2 — audio mime allow-list** | Required (wave-killer) | New **Section 0.5** owns the validation seam. Two surgical extensions: (a) `AttachmentsConfig.allowed_mime_types` default extended with `audio/webm` + `audio/wav` (Section 0.5a); (b) `attachments/mime.py._SIGNATURES` extended with EBML (WebM) and RIFF/WAVE magic-byte signatures (Section 0.5b). `validate_attachment_bytes` already short-circuits to `_SIGNATURES`-driven validation when the declared MIME is registered there, so no new branches needed. `config/system.yaml` requires no edit (verified zero `attachments:` block). 2 new regression tests #15/#16 cover both gates. |
| **Rec #2 — test count framing** | Recommended | Header changed from "≥ 10" to "≥ 16" (14 backend + 2 mime regression). Section 4 title updated. |
| **Rec #3 — conditional `system.yaml` edit** | Recommended | Section 1c locked to "no edit" with verification grep. The conditional/optional language is removed. |
| **Rec #4 — `--machineReadable` deferred verification** | Recommended | Flag dropped from the subprocess invocation. Justification updated in the Notes block: stderr is already discarded except on non-zero exit, so the flag is not load-bearing. Eliminates a version-coupling risk. |
| **Nit #3 — `.exe.exe` concatenation bug** | Nit | `_resolve_binary_path` rewritten to use `p.parent / (p.name + ".exe")` and gated on `p.suffix.lower() != ".exe"` to guard against operator-supplied paths that already end in `.exe`. |
| **Test #2 platform skip** | Recommended | Replaced the `pytest.mark.skipif(sys.platform == "win32", ...)` shell-script fixture with a cross-platform monkeypatch on `asyncio.create_subprocess_exec` (mirrors test #4's pattern). Removes the platform skip entirely. |

The Verified Against Codebase section was extended with grep evidence for `api.py`'s router-registration block, `runtime.py`'s zero `include_router` hits, the existing allow-list shape, the `_SIGNATURES` short-circuit in `validate_attachment_bytes`, and the `system.yaml` zero-hit confirmation.

No scope expansion: every change addresses an explicitly-flagged finding. `LipSyncConfig`, `rhubarb_backend.py`, and the endpoint contract are unchanged.
