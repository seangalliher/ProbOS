"""AD-733: PerceptionConfig validation tests (BF-287: real Pydantic)."""
from __future__ import annotations

import pytest

from probos.config import CameraStreamConfig, PerceptionConfig


def test_perception_config_default_off() -> None:
    cfg = PerceptionConfig()
    assert cfg.enabled is False
    assert cfg.camera.enabled is False
    assert cfg.camera.default_fps == 1
    assert cfg.camera_max_fps_server == 4
    assert cfg.frame_max_size_bytes == 512 * 1024


def test_perception_config_rejects_excessive_client_fps() -> None:
    with pytest.raises(Exception):
        PerceptionConfig(camera=CameraStreamConfig(default_fps=99))


def test_perception_config_rejects_excessive_server_fps_cap() -> None:
    with pytest.raises(Exception):
        PerceptionConfig(camera_max_fps_server=99)
