"""BF-305: /data/<class>/* static mounts for browser-side model artifacts.

Browser-side STT/VAD (Silero VAD ONNX, whisper.cpp WASM + ggml weights) must
be reachable at same-origin URLs under ``/data/<class>/...``. Prior to BF-305
the runtime had no static mount serving operator-pulled model artifacts —
``ui/src/audio/silero-vad.ts`` fetched ``/data/silero-vad/silero_vad.onnx``
and got an HTML 404 from the SPA catch-all, silently disabling voice activity.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient


def _make_client(tmp_path: Path) -> TestClient:
    from probos.api import create_app
    runtime = MagicMock()
    runtime._data_dir = tmp_path
    runtime.data_dir = tmp_path
    return TestClient(create_app(runtime))


def test_silero_mount_serves_existing_file(tmp_path: Path) -> None:
    """A placed silero_vad.onnx must be reachable at the expected URL."""
    silero_dir = tmp_path / "silero-vad"
    silero_dir.mkdir()
    (silero_dir / "silero_vad.onnx").write_bytes(b"\x00\x01\x02ONNX-stub")

    client = _make_client(tmp_path)
    resp = client.get("/data/silero-vad/silero_vad.onnx")
    assert resp.status_code == 200, resp.text
    assert resp.content == b"\x00\x01\x02ONNX-stub"


def test_silero_mount_404s_when_file_missing(tmp_path: Path) -> None:
    """Missing model file returns 404 cleanly (no 500, no SPA HTML)."""
    client = _make_client(tmp_path)
    resp = client.get("/data/silero-vad/silero_vad.onnx")
    assert resp.status_code == 404


def test_whisper_mount_serves_existing_file(tmp_path: Path) -> None:
    """Whisper artifacts served from /data/whisper/*."""
    whisper_dir = tmp_path / "whisper"
    whisper_dir.mkdir()
    (whisper_dir / "ggml-tiny.en.bin").write_bytes(b"GGMLstub")

    client = _make_client(tmp_path)
    resp = client.get("/data/whisper/ggml-tiny.en.bin")
    assert resp.status_code == 200
    assert resp.content == b"GGMLstub"


def test_data_mount_does_NOT_leak_sensitive_files(tmp_path: Path) -> None:
    """Security invariant: SQLite stores at the data dir root must NOT be
    reachable via ``/data/*``. Only whitelisted subdirs are mounted."""
    (tmp_path / "trust.db").write_bytes(b"SQLite-private-data")
    (tmp_path / "events.db").write_bytes(b"SQLite-private-data")
    (tmp_path / "shutdown_status.json").write_text('{"status": "clean"}')

    client = _make_client(tmp_path)
    for sensitive in ("trust.db", "events.db", "shutdown_status.json"):
        resp = client.get(f"/data/{sensitive}")
        assert resp.content != b"SQLite-private-data", (
            f"BF-305 security: /data/{sensitive} leaked sensitive bytes!"
        )


def test_silero_mount_directory_autocreated(tmp_path: Path) -> None:
    """Mount creates the model subdir if absent so the route is always alive
    (operator can drop the file in later without restarting the runtime)."""
    assert not (tmp_path / "silero-vad").exists()
    _make_client(tmp_path)
    assert (tmp_path / "silero-vad").is_dir()
