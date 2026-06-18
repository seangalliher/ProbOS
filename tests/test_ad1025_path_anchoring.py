"""AD-1025: anchor operator-asset + runtime-artifact paths to the ProbOS
install root (and the absolute runtime data dir), NEVER the process CWD.

Headline regression (2026-06-17 incident): launching ``probos serve`` from a
sibling folder made the CWD-relative Piper binary/voice paths and the
rejection-cache DB path miss their installed assets, silently degrading TTS to
the browser and skipping Step-7i relationship inference. These tests pin the
anchored contract with real ``tmp_path`` fixtures (BF-287 — no MagicMock at
the boundary; the only stubs are ``SimpleNamespace`` runtime/config shells and
a fake ``subprocess.Popen`` that mirrors the BF-282 ``--output_file`` shape).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.audio.tts import piper_backend
from probos.audio.tts.piper_backend import (
    PiperBackend,
    _anchor_path,
    _probos_root,
    _resolve_binary_path,
    _resolve_voice_model,
)
from probos.startup.finalize import _wire_relationship_inference


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_voice(voices_dir: Path, name: str = "v") -> None:
    """Lay down a valid Piper voice pair (<name>.onnx + .onnx.json)."""
    voices_dir.mkdir(parents=True, exist_ok=True)
    (voices_dir / f"{name}.onnx").write_bytes(b"\x00")
    (voices_dir / f"{name}.onnx.json").write_bytes(b"{}")


class _FakePopen:
    """Minimal subprocess.Popen stand-in (mirrors the BF-280 sync shape)."""

    returncode = 0

    def communicate(
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes, bytes]:
        return b"", b""

    def kill(self) -> None:  # pragma: no cover - never reached on happy path
        pass

    def wait(self, timeout: float | None = None) -> int:
        return 0


def _capturing_popen(seen: dict[str, str]):
    """Factory that captures the ``--model`` arg and writes non-empty bytes to
    the ``--output_file`` path so the production reader returns a TTSResult."""

    def _factory(args, *_pos, **_kwargs) -> _FakePopen:
        a = list(args)
        if "--model" in a:
            seen["model"] = a[a.index("--model") + 1]
        if "--output_file" in a:
            ofp = a[a.index("--output_file") + 1]
            try:
                Path(ofp).write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
            except OSError:
                pass
        return _FakePopen()

    return _factory


# ---------------------------------------------------------------------------
# Depth lock (count, don't assume — AD-458 lesson)
# ---------------------------------------------------------------------------


def test_probos_root_points_at_repo_root() -> None:
    """``parents[4]`` must land on the repo root that holds this very module
    under ``src/probos/audio/tts/``. Locks the depth against future drift."""
    root = _probos_root()
    assert (
        root / "src" / "probos" / "audio" / "tts" / "piper_backend.py"
    ).is_file()


# ---------------------------------------------------------------------------
# Binary anchoring (headline regression)
# ---------------------------------------------------------------------------


def test_relative_binary_anchors_to_root_not_cwd(monkeypatch, tmp_path) -> None:
    """THE incident: a RELATIVE binary_path resolves against the ProbOS root
    even when the CWD is an unrelated directory."""
    root = tmp_path / "probos_root"
    bindir = root / "tools" / "piper"
    bindir.mkdir(parents=True)
    binary = bindir / "piper"
    binary.write_bytes(b"")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(piper_backend, "_probos_root", lambda: root)
    monkeypatch.chdir(elsewhere)

    resolved = _resolve_binary_path("tools/piper/piper")

    assert resolved is not None
    assert resolved == binary.resolve()


def test_absolute_binary_used_as_is(monkeypatch, tmp_path) -> None:
    """An ABSOLUTE binary_path is used verbatim — the anchor is a no-op even
    when ``_probos_root`` points elsewhere."""
    root = tmp_path / "probos_root"
    root.mkdir()
    monkeypatch.setattr(piper_backend, "_probos_root", lambda: root)
    binary = tmp_path / "custom" / "piper"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")

    resolved = _resolve_binary_path(str(binary))

    assert resolved == binary.resolve()


def test_missing_relative_binary_returns_none(monkeypatch, tmp_path) -> None:
    """A relative path that does not exist under the root returns None."""
    root = tmp_path / "probos_root"
    root.mkdir()
    monkeypatch.setattr(piper_backend, "_probos_root", lambda: root)
    monkeypatch.chdir(tmp_path)

    assert _resolve_binary_path("tools/piper/piper") is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows .exe auto-append")
def test_windows_exe_append_on_anchored_path(monkeypatch, tmp_path) -> None:
    """The ``.exe`` auto-append works on the anchored (relative) path."""
    root = tmp_path / "probos_root"
    bindir = root / "tools" / "piper"
    bindir.mkdir(parents=True)
    (bindir / "piper.exe").write_bytes(b"")
    monkeypatch.setattr(piper_backend, "_probos_root", lambda: root)
    monkeypatch.chdir(tmp_path)

    resolved = _resolve_binary_path("tools/piper/piper")

    assert resolved is not None
    assert resolved.name == "piper.exe"
    assert resolved == (bindir / "piper.exe").resolve()


# ---------------------------------------------------------------------------
# _anchor_path + voices_dir / voice_override anchoring
# ---------------------------------------------------------------------------


def test_anchor_path_relative_vs_absolute(monkeypatch, tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(piper_backend, "_probos_root", lambda: root)

    assert _anchor_path("tools/piper/voices") == (
        root / "tools" / "piper" / "voices"
    ).resolve()
    abs_in = tmp_path / "abs" / "voices"
    assert _anchor_path(str(abs_in)) == abs_in.resolve()


def test_resolve_voice_model_under_explicit_base(tmp_path) -> None:
    """_resolve_voice_model takes the already-anchored base (both files req)."""
    base = tmp_path / "voices"
    base.mkdir()
    (base / "amy.onnx").write_bytes(b"")
    assert _resolve_voice_model("amy", base) is None  # no .onnx.json yet
    (base / "amy.onnx.json").write_bytes(b"{}")
    resolved = _resolve_voice_model("amy", base)
    assert resolved == (base / "amy.onnx")


@pytest.mark.asyncio
async def test_relative_voices_dir_and_override_anchor_to_root(
    monkeypatch, tmp_path
) -> None:
    """A relative ``voices_dir`` AND the BF-291 ``voice_override`` both resolve
    under the ProbOS root, independent of CWD (end-to-end through synthesize)."""
    root = tmp_path / "probos_root"
    binary = root / "tools" / "piper" / "piper"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    voices = root / "tools" / "piper" / "voices"
    _write_voice(voices, "amy")   # configured default
    _write_voice(voices, "ryan")  # per-call override
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(piper_backend, "_probos_root", lambda: root)
    monkeypatch.chdir(elsewhere)
    seen: dict[str, str] = {}
    monkeypatch.setattr("subprocess.Popen", _capturing_popen(seen))

    backend = PiperBackend(
        binary_path="tools/piper/piper",
        voice_model="amy",
        voices_dir="tools/piper/voices",
    )
    result = await backend.synthesize("hi", voice_override="ryan")

    assert result is not None
    # The override voice resolved under the ROOT-anchored base, not the CWD.
    assert seen["model"] == str((voices / "ryan.onnx").resolve())


@pytest.mark.asyncio
async def test_absolute_voices_dir_used_as_is(monkeypatch, tmp_path) -> None:
    """An ABSOLUTE ``voices_dir`` is used verbatim regardless of the anchor."""
    root = tmp_path / "probos_root"
    root.mkdir()
    monkeypatch.setattr(piper_backend, "_probos_root", lambda: root)
    binary = tmp_path / "bin" / "piper"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    voices = tmp_path / "custom_voices"
    _write_voice(voices, "amy")
    seen: dict[str, str] = {}
    monkeypatch.setattr("subprocess.Popen", _capturing_popen(seen))

    backend = PiperBackend(
        binary_path=str(binary),
        voice_model="amy",
        voices_dir=str(voices),
    )
    result = await backend.synthesize("hi")

    assert result is not None
    assert seen["model"] == str((voices / "amy.onnx").resolve())


# ---------------------------------------------------------------------------
# DD-4: actionable degrade WARNINGs include the resolved candidate path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_degrade_warning_includes_resolved_binary_path(
    monkeypatch, tmp_path, caplog
) -> None:
    root = tmp_path / "probos_root"
    root.mkdir()
    monkeypatch.setattr(piper_backend, "_probos_root", lambda: root)
    monkeypatch.chdir(tmp_path)
    caplog.set_level("WARNING", logger="probos.audio.tts.piper_backend")

    backend = PiperBackend(
        binary_path="tools/piper/missing",
        voice_model="amy",
        voices_dir="tools/piper/voices",
    )
    assert await backend.synthesize("hi") is None

    resolved = (root / "tools" / "piper" / "missing").resolve()
    assert "piper binary not found" in caplog.text
    assert str(resolved) in caplog.text


@pytest.mark.asyncio
async def test_degrade_warning_includes_resolved_voices_base(
    monkeypatch, tmp_path, caplog
) -> None:
    root = tmp_path / "probos_root"
    binary = root / "tools" / "piper" / "piper"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    monkeypatch.setattr(piper_backend, "_probos_root", lambda: root)
    monkeypatch.chdir(tmp_path)
    caplog.set_level("WARNING", logger="probos.audio.tts.piper_backend")

    backend = PiperBackend(
        binary_path="tools/piper/piper",
        voice_model="amy",  # voices dir is empty → model missing
        voices_dir="tools/piper/voices",
    )
    assert await backend.synthesize("hi") is None

    voices_base = (root / "tools" / "piper" / "voices").resolve()
    assert "piper voice model" in caplog.text
    assert str(voices_base) in caplog.text


# ---------------------------------------------------------------------------
# DD-3: rejection cache writes under the absolute runtime.data_dir
# ---------------------------------------------------------------------------


def _make_runtime(data_dir: Path, calls: dict[str, object]) -> SimpleNamespace:
    dreaming_engine = SimpleNamespace(
        set_knowledge_edges=lambda e: calls.__setitem__("ke", e),
        set_rejection_cache=lambda c: calls.__setitem__("rc", c),
    )
    return SimpleNamespace(
        data_dir=data_dir,                # AD-468 public property (absolute)
        knowledge_edges=object(),         # non-None sentinel
        dreaming_engine=dreaming_engine,
        rejection_cache=None,             # set by the wirer on success
    )


def _ri_config() -> SimpleNamespace:
    return SimpleNamespace(
        dreaming=SimpleNamespace(relationship_inference_enabled=True),
    )


@pytest.mark.asyncio
async def test_rejection_cache_uses_absolute_runtime_data_dir(
    monkeypatch, tmp_path
) -> None:
    """The rejection-cache DB is created under the ABSOLUTE runtime data dir,
    independent of the CWD (reproduces the AD-690 boot-log false negative)."""
    data_dir = tmp_path / "data_dir"
    data_dir.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    calls: dict[str, object] = {}
    runtime = _make_runtime(data_dir, calls)

    ok = await _wire_relationship_inference(runtime=runtime, config=_ri_config())

    expected_db = data_dir / "rejection_cache.sqlite"
    try:
        assert ok is True
        assert expected_db.is_absolute()
        # start() bootstrapped the DB under the absolute data dir, NOT under
        # ``elsewhere/data`` (the old CWD-relative behavior).
        assert expected_db.is_file()
        assert not (elsewhere / "data" / "rejection_cache.sqlite").exists()
        assert runtime.rejection_cache is not None
        assert calls["rc"] is runtime.rejection_cache
    finally:
        if runtime.rejection_cache is not None:
            await runtime.rejection_cache.stop()


@pytest.mark.asyncio
async def test_rejection_cache_honest_degrade_on_bad_dir(
    monkeypatch, tmp_path, caplog
) -> None:
    """The honest-degrade try/except is unchanged: an unopenable DB path
    returns False (Step 7i skipped) without raising."""
    bad_file = tmp_path / "not_a_dir"
    bad_file.write_bytes(b"")  # a FILE where a directory is expected
    monkeypatch.chdir(tmp_path)
    caplog.set_level("WARNING", logger="probos.startup.finalize")
    calls: dict[str, object] = {}
    runtime = _make_runtime(bad_file, calls)

    ok = await _wire_relationship_inference(runtime=runtime, config=_ri_config())

    assert ok is False
    assert runtime.rejection_cache is None
    assert "rejection cache failed to start" in caplog.text
