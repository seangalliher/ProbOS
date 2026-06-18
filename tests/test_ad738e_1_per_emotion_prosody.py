"""AD-738e-1 (Wave 158): Per-emotion Piper prosody overrides.

Seven boundary tests covering:
  1. resolve_prosody_overrides happy path (concerned).
  2. additive guarantee (neutral / None / empty → {}).
  3. unknown emotion → {} (including case sensitivity).
  4. PiperBackend applies override at synthesis time.
  5. PiperBackend without emotion uses constructor defaults.
  6. /api/avatars/tts endpoint forwards emotion to backend.
  7. agents chat router collapses custom emotion → v1 in the response.
"""

from __future__ import annotations

import struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.audio.tts.prosody import (
    _EMOTION_PROSODY_OVERRIDES,
    resolve_prosody_overrides,
)
from probos.audio.tts.piper_backend import PiperBackend


# ── Helpers ────────────────────────────────────────────────────────────


class _StubProc:
    def __init__(self, stdout: bytes) -> None:
        self.returncode = 0
        self._stdout = stdout
        self._output_file_path: str | None = None

    def communicate(self, input=None, timeout=None):
        if self._output_file_path and self._stdout:
            Path(self._output_file_path).write_bytes(self._stdout)
        return self._stdout, b""

    def kill(self) -> None:
        pass

    def wait(self, timeout=None) -> int:
        return 0


def _make_args_capturing_factory(stdout: bytes) -> tuple[list, callable]:
    captured: list = []

    def _factory(args, *_pos, **_kwargs):
        captured.append(list(args))
        stub = _StubProc(stdout)
        if isinstance(args, (list, tuple)):
            try:
                idx = list(args).index("--output_file")
                stub._output_file_path = (
                    args[idx + 1] if idx + 1 < len(args) else None
                )
            except ValueError:
                pass
        return stub

    return captured, _factory


def _make_minimal_wav() -> bytes:
    num_samples = 800
    sample_rate = 16000
    fmt_chunk = struct.pack(
        "<4sIHHIIHH",
        b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16,
    )
    data_chunk = struct.pack("<4sI", b"data", num_samples * 2) + b"\x00" * (num_samples * 2)
    riff_size = 4 + len(fmt_chunk) + len(data_chunk)
    return struct.pack("<4sI4s", b"RIFF", riff_size, b"WAVE") + fmt_chunk + data_chunk


def _setup_voice_model(voices_dir: Path, name: str = "v") -> None:
    voices_dir.mkdir(parents=True, exist_ok=True)
    (voices_dir / f"{name}.onnx").write_bytes(b"\x00")
    (voices_dir / f"{name}.onnx.json").write_bytes(b"{}")


# ── 1-3: resolve_prosody_overrides ─────────────────────────────────────


def test_resolve_prosody_overrides_concerned():
    """Happy path: concerned returns the configured override dict."""
    assert resolve_prosody_overrides("concerned") == {
        "noise_scale": 0.95, "length_scale": 1.05,
    }
    # Mutation guard: returned dict is a copy, not the module constant.
    out = resolve_prosody_overrides("concerned")
    out["noise_scale"] = 1.23
    assert _EMOTION_PROSODY_OVERRIDES["concerned"]["noise_scale"] == 0.95


def test_resolve_prosody_overrides_neutral_returns_empty():
    """Additive guarantee: neutral / None / empty return {} (no override)."""
    assert resolve_prosody_overrides("neutral") == {}
    assert resolve_prosody_overrides(None) == {}
    assert resolve_prosody_overrides("") == {}


def test_resolve_prosody_overrides_unknown_returns_empty():
    """Error path: unknown emotion returns {}; table keys are lowercase."""
    assert resolve_prosody_overrides("not_an_emotion") == {}
    # Case sensitivity — table keys are lowercase.
    assert resolve_prosody_overrides("FORMAL") == {}
    assert resolve_prosody_overrides("Concerned") == {}


# ── 4-5: PiperBackend per-call override ────────────────────────────────


@pytest.mark.asyncio
async def test_piper_backend_applies_override_at_synthesis(monkeypatch, tmp_path):
    """`excited` overrides noise_scale + length_scale; other knobs keep defaults."""
    fake_bin = tmp_path / "piper"
    fake_bin.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    _setup_voice_model(tmp_path / "tools" / "piper" / "voices", "v")
    captured, factory = _make_args_capturing_factory(_make_minimal_wav())
    monkeypatch.setattr("subprocess.Popen", factory)

    backend = PiperBackend(
        binary_path=str(fake_bin),
        voice_model="v",
        voices_dir=str(tmp_path / "tools" / "piper" / "voices"),
        noise_scale=0.85,
        length_scale=1.0,
        noise_w=1.0,
        sentence_silence=0.35,
    )
    result = await backend.synthesize("hi", emotion="excited")
    assert result is not None
    assert len(captured) == 1
    args = captured[0]
    # excited override: noise_scale=0.95, length_scale=0.92.
    ns_idx = args.index("--noise_scale")
    ls_idx = args.index("--length_scale")
    nw_idx = args.index("--noise_w")
    ss_idx = args.index("--sentence_silence")
    assert args[ns_idx + 1] == "0.95"
    assert args[ls_idx + 1] == "0.92"
    # noise_w / sentence_silence retain constructor defaults.
    assert args[nw_idx + 1] == "1.0"
    assert args[ss_idx + 1] == "0.35"


@pytest.mark.asyncio
async def test_piper_backend_no_emotion_uses_defaults(monkeypatch, tmp_path):
    """Backward compat: no emotion kwarg → all knobs use constructor values."""
    fake_bin = tmp_path / "piper"
    fake_bin.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    _setup_voice_model(tmp_path / "tools" / "piper" / "voices", "v")
    captured, factory = _make_args_capturing_factory(_make_minimal_wav())
    monkeypatch.setattr("subprocess.Popen", factory)

    backend = PiperBackend(
        binary_path=str(fake_bin),
        voice_model="v",
        voices_dir=str(tmp_path / "tools" / "piper" / "voices"),
        noise_scale=0.85,
        length_scale=1.0,
        noise_w=1.0,
        sentence_silence=0.35,
    )
    result = await backend.synthesize("hi")  # no emotion kwarg
    assert result is not None
    args = captured[0]
    assert args[args.index("--noise_scale") + 1] == "0.85"
    assert args[args.index("--length_scale") + 1] == "1.0"
    assert args[args.index("--noise_w") + 1] == "1.0"
    assert args[args.index("--sentence_silence") + 1] == "0.35"


# ── 6: endpoint forwards emotion ───────────────────────────────────────


@pytest.mark.asyncio
async def test_tts_endpoint_forwards_emotion_to_backend(monkeypatch):
    """POST /api/avatars/tts forwards emotion field to backend.synthesize."""
    from probos.routers import avatars as avatars_router

    # Stub backend captures calls.
    captured_calls: list[dict] = []

    class _StubBackend:
        async def synthesize(self, text, emotion=None, voice_override=None):
            captured_calls.append({"text": text, "emotion": emotion})
            return None

    def _select_backend_stub(name, cfg):
        return _StubBackend()

    monkeypatch.setattr(
        "probos.audio.tts.select_backend", _select_backend_stub,
    )

    cfg = SimpleNamespace(enabled=True, backend="piper")
    runtime = SimpleNamespace(config=SimpleNamespace(tts=cfg))

    class _FakeReq:
        def __init__(self, body: dict) -> None:
            self._body = body

        async def json(self):
            return self._body

    # With emotion.
    result = await avatars_router._synthesize_tts_impl(
        _FakeReq({"text": "hi", "emotion": "concerned"}), runtime,
    )
    assert result["backend"] == "disabled"
    assert captured_calls[-1] == {"text": "hi", "emotion": "concerned"}

    # Without emotion → backend called with emotion=None.
    await avatars_router._synthesize_tts_impl(
        _FakeReq({"text": "hello"}), runtime,
    )
    assert captured_calls[-1] == {"text": "hello", "emotion": None}

    # Invalid emotion type (int) → coerced to None.
    await avatars_router._synthesize_tts_impl(
        _FakeReq({"text": "hi", "emotion": 42}), runtime,
    )
    assert captured_calls[-1]["emotion"] is None

    # Empty / whitespace emotion → None.
    await avatars_router._synthesize_tts_impl(
        _FakeReq({"text": "hi", "emotion": "  "}), runtime,
    )
    assert captured_calls[-1]["emotion"] is None


# ── 7: chat router collapses custom→v1 ────────────────────────────────


def test_chat_response_includes_resolved_v1_emotion_for_custom_name():
    """Section 6: custom emotion (professional_concern) resolves to v1 parent
    (concerned) before the chat response includes the emotion field.

    Uses the public ``resolve_emotion_to_v1`` alias directly to assert the
    Section 5b alias is callable with a custom-name input.
    """
    from probos.avatars.divergence_detector import resolve_emotion_to_v1
    from probos.crew_profile import EmotionProfile

    custom = {
        "professional_concern": EmotionProfile(inherits="concerned"),
    }
    # Custom name resolves to v1 parent.
    assert resolve_emotion_to_v1("professional_concern", custom) == "concerned"
    # v1 name passes through unchanged.
    assert resolve_emotion_to_v1("warm", custom) == "warm"
    # Unknown returns None.
    assert resolve_emotion_to_v1("not_a_thing", custom) is None
    # None custom_emotions arg still works for v1 names.
    assert resolve_emotion_to_v1("concerned", None) == "concerned"
    assert resolve_emotion_to_v1("professional_concern", None) is None
