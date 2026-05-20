"""AD-705c (Wave 179) — Wake-word training API tests."""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.config import SystemConfig
from probos.routers import voice as voice_router


def _install_openwakeword_stub() -> None:
    pkg = types.ModuleType("openwakeword")
    train_mod = types.ModuleType("openwakeword.train")

    def fake_train(**kwargs) -> None:
        out = Path(kwargs["output_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"FAKE-ONNX")

    train_mod.train = fake_train  # type: ignore[attr-defined]
    sys.modules["openwakeword"] = pkg
    sys.modules["openwakeword.train"] = train_mod


def _uninstall_openwakeword_stub() -> None:
    sys.modules.pop("openwakeword.train", None)
    sys.modules.pop("openwakeword", None)


class _FakeRuntime:
    """Minimal real-shape runtime stand-in (BF-287 — not MagicMock)."""

    def __init__(self, data_dir: Path, *, enabled: bool = True) -> None:
        self.config = SystemConfig()
        self.config.wake_word.wake_word_trainer_enabled = enabled
        self.data_dir = data_dir
        self._wake_word_trainer_jobs: dict[str, dict[str, Any]] = {}
        self._wake_word_trainer_tasks: set[asyncio.Task[Any]] = set()


def _make_client(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(voice_router.router)
    app.dependency_overrides[voice_router.get_runtime] = lambda: runtime
    app.dependency_overrides[voice_router.require_crew_scope] = lambda: None
    return TestClient(app)


def _wav_bytes(payload: bytes = b"\x00") -> bytes:
    return b"RIFF" + (len(payload) + 36).to_bytes(4, "little") + b"WAVEfmt " + payload


def test_post_sample_writes_wav_to_disk(tmp_path: Path) -> None:
    runtime = _FakeRuntime(tmp_path)
    client = _make_client(runtime)
    resp = client.post(
        "/api/voice/wake-word/sample",
        files={"audio": ("u1.wav", _wav_bytes(), "audio/wav")},
        data={"phrase": "Computer"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["stored"] is True
    assert body["samples_count"] == 1
    positive = tmp_path / "wake-word" / "training-samples" / "positive"
    assert len(list(positive.glob("*.wav"))) == 1


def test_post_sample_503_when_trainer_disabled(tmp_path: Path) -> None:
    runtime = _FakeRuntime(tmp_path, enabled=False)
    client = _make_client(runtime)
    resp = client.post(
        "/api/voice/wake-word/sample",
        files={"audio": ("u1.wav", _wav_bytes(), "audio/wav")},
    )
    assert resp.status_code == 503


def test_post_sample_413_when_oversize(tmp_path: Path) -> None:
    runtime = _FakeRuntime(tmp_path)
    runtime.config.wake_word.training_audio_max_bytes = 8
    client = _make_client(runtime)
    resp = client.post(
        "/api/voice/wake-word/sample",
        files={"audio": ("u1.wav", _wav_bytes(b"\x00" * 32), "audio/wav")},
    )
    assert resp.status_code == 413


def test_post_sample_400_when_not_wav(tmp_path: Path) -> None:
    runtime = _FakeRuntime(tmp_path)
    client = _make_client(runtime)
    resp = client.post(
        "/api/voice/wake-word/sample",
        files={"audio": ("u1.wav", b"not-a-wav-file", "audio/wav")},
    )
    assert resp.status_code == 400


def test_post_train_spawns_background_task(tmp_path: Path) -> None:
    _install_openwakeword_stub()
    try:
        runtime = _FakeRuntime(tmp_path)
        # Seed a sample so train doesn't bail early.
        positive = tmp_path / "wake-word" / "training-samples" / "positive"
        positive.mkdir(parents=True)
        (positive / "s1.wav").write_bytes(_wav_bytes())
        client = _make_client(runtime)
        resp = client.post("/api/voice/wake-word/train", json={"label": "Computer", "epochs": 1})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "started"
        assert body["job_id"]
        # Job entry registered.
        assert body["job_id"] in runtime._wake_word_trainer_jobs
    finally:
        _uninstall_openwakeword_stub()


def test_get_training_status_returns_progress(tmp_path: Path) -> None:
    runtime = _FakeRuntime(tmp_path)
    runtime._wake_word_trainer_jobs["job-1"] = {
        "status": "running",
        "progress": 0.5,
        "label": "Computer",
    }
    client = _make_client(runtime)
    resp = client.get("/api/voice/wake-word/training-status?job_id=job-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["progress"] == 0.5
    # 404 path.
    resp404 = client.get("/api/voice/wake-word/training-status?job_id=missing")
    assert resp404.status_code == 404
