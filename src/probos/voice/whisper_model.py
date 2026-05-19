"""AD-721b-3 — Resolve the operator-pulled Whisper tiny.en model path.

The whisper.cpp WASM glue + GGML model weights are operator-pulled via
``scripts/whisper-tiny-en-fetch.ps1`` into ``data/whisper/``. The runtime
never serves the file directly — the browser fetches it from the same
``/data/...`` static route AD-733c-7 already exposes for the Silero VAD
model. This helper exists for consumers that need on-disk access to the
weights (AD-705c wake-word training uses Whisper-synthesized negatives
in a future iteration; v1 reserves the seam without using it).

Hot path: never imported by the runtime startup or the request loop.
Honest-degrades by returning ``None`` when the file is absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import SystemConfig


def resolve_whisper_model_path(
    config: "SystemConfig",
    data_dir: Path,
) -> Path | None:
    """Return the absolute path to the Whisper model file, or ``None``.

    The ``cognitive.whisper_model_path`` field is interpreted as:

    * Absolute path → used as-is.
    * Relative path → resolved against ``data_dir`` (the runtime's
      ``runtime.data_dir`` value).

    Returns ``None`` when the resolved file does not exist. Callers MUST
    treat ``None`` as honest degrade — no whisper functionality
    available; fall through to the next tier.
    """
    raw = config.cognitive.whisper_model_path
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = data_dir / candidate
    if not candidate.exists():
        return None
    return candidate
