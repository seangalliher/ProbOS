"""AD-705c (Wave 179) — WakeWordTrainer service-layer tests.

Tests use a real ``SystemConfig`` (BF-287) + ``tmp_path`` for data dir.
The ``openwakeword.train`` module is stubbed via ``sys.modules`` since
the package is operator-installed and absent in CI.
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

from probos.config import SystemConfig
from probos.voice.wake_word_trainer import WakeWordTrainer


def _make_wav(path: Path, body: bytes = b"\x00\x00") -> None:
    path.write_bytes(b"RIFF" + (4).to_bytes(4, "little") + b"WAVEfmt " + body)


def _install_openwakeword_stub(success: bool) -> None:
    """Install a stub ``openwakeword.train`` module."""
    pkg = types.ModuleType("openwakeword")
    train_mod = types.ModuleType("openwakeword.train")

    def fake_train(**kwargs) -> None:
        if not success:
            raise RuntimeError("synthetic upstream failure")
        out = Path(kwargs["output_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"FAKE-ONNX")

    def fake_test(**kwargs) -> dict[str, float]:
        return {"tpr": 0.98, "far": 0.02}

    train_mod.train = fake_train  # type: ignore[attr-defined]
    train_mod.test = fake_test  # type: ignore[attr-defined]
    sys.modules["openwakeword"] = pkg
    sys.modules["openwakeword.train"] = train_mod


def _uninstall_openwakeword_stub() -> None:
    sys.modules.pop("openwakeword.train", None)
    sys.modules.pop("openwakeword", None)


@pytest.mark.asyncio
async def test_train_returns_report_when_openwakeword_installed(tmp_path: Path) -> None:
    _install_openwakeword_stub(success=True)
    try:
        config = SystemConfig()
        trainer = WakeWordTrainer(config, tmp_path)
        positive = tmp_path / "wake-word" / "training-samples" / "positive"
        positive.mkdir(parents=True)
        _make_wav(positive / "s1.wav")
        _make_wav(positive / "s2.wav")
        output = tmp_path / "captain.onnx"
        report = await trainer.train(
            label="Computer",
            positive_samples_dir=positive,
            output_path=output,
        )
        assert report.status == "ok"
        assert report.label == "Computer"
        assert report.output_path == str(output)
        assert report.samples_used == 2
        assert output.exists()
    finally:
        _uninstall_openwakeword_stub()


@pytest.mark.asyncio
async def test_train_honest_degrades_when_openwakeword_missing(tmp_path: Path) -> None:
    _uninstall_openwakeword_stub()
    config = SystemConfig()
    trainer = WakeWordTrainer(config, tmp_path)
    positive = tmp_path / "wake-word" / "training-samples" / "positive"
    positive.mkdir(parents=True)
    _make_wav(positive / "s1.wav")
    report = await trainer.train(label="Computer", positive_samples_dir=positive)
    assert report.status == "error"
    assert "pip install openwakeword" in (report.error_message or "")


@pytest.mark.asyncio
async def test_train_writes_onnx_to_output_path(tmp_path: Path) -> None:
    _install_openwakeword_stub(success=True)
    try:
        config = SystemConfig()
        trainer = WakeWordTrainer(config, tmp_path)
        positive = tmp_path / "wake-word" / "training-samples" / "positive"
        positive.mkdir(parents=True)
        _make_wav(positive / "s1.wav")
        custom = tmp_path / "custom" / "model.onnx"
        report = await trainer.train(
            label="Computer",
            positive_samples_dir=positive,
            output_path=custom,
        )
        assert report.status == "ok"
        assert custom.exists()
    finally:
        _uninstall_openwakeword_stub()


@pytest.mark.asyncio
async def test_test_returns_metrics_for_held_out_samples(tmp_path: Path) -> None:
    _install_openwakeword_stub(success=True)
    try:
        config = SystemConfig()
        trainer = WakeWordTrainer(config, tmp_path)
        samples = tmp_path / "held"
        samples.mkdir()
        _make_wav(samples / "s1.wav")
        report = await trainer.test(
            model_path=tmp_path / "captain.onnx",
            samples_dir=samples,
        )
        assert report.status == "ok"
        assert report.samples_used == 1
        assert report.true_positive_rate == 0.98
        assert report.false_accept_rate == 0.02
    finally:
        _uninstall_openwakeword_stub()


@pytest.mark.asyncio
async def test_delete_samples_after_train_when_retain_false(tmp_path: Path) -> None:
    _install_openwakeword_stub(success=True)
    try:
        config = SystemConfig()
        config.wake_word.retain_training_samples = False
        trainer = WakeWordTrainer(config, tmp_path)
        positive = tmp_path / "wake-word" / "training-samples" / "positive"
        positive.mkdir(parents=True)
        _make_wav(positive / "s1.wav")
        _make_wav(positive / "s2.wav")
        report = await trainer.train(
            label="Computer",
            positive_samples_dir=positive,
            output_path=tmp_path / "captain.onnx",
        )
        assert report.status == "ok"
        # Directory is recreated empty after deletion.
        assert positive.exists()
        assert list(positive.glob("*.wav")) == []
    finally:
        _uninstall_openwakeword_stub()


@pytest.mark.asyncio
async def test_keep_samples_when_retain_true(tmp_path: Path) -> None:
    _install_openwakeword_stub(success=True)
    try:
        config = SystemConfig()
        config.wake_word.retain_training_samples = True
        trainer = WakeWordTrainer(config, tmp_path)
        positive = tmp_path / "wake-word" / "training-samples" / "positive"
        positive.mkdir(parents=True)
        _make_wav(positive / "s1.wav")
        report = await trainer.train(
            label="Computer",
            positive_samples_dir=positive,
            output_path=tmp_path / "captain.onnx",
        )
        assert report.status == "ok"
        assert (positive / "s1.wav").exists()
    finally:
        _uninstall_openwakeword_stub()
