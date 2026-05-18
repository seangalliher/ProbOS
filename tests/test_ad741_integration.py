"""AD-741: End-to-end integration — GET → POST → re-GET round-trip."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import yaml
from fastapi.testclient import TestClient

from probos.api import create_app
from probos.config import SystemConfig


def _runtime(tmp_path: Path) -> MagicMock:
    cfg_path = tmp_path / "system.yaml"
    cfg_path.write_text(yaml.safe_dump({}), encoding="utf-8")
    runtime = MagicMock()
    runtime.config = SystemConfig()
    runtime.config_path = str(cfg_path)
    runtime._start_time = 0.0
    return runtime


def test_round_trip_log_level_get_post_reget(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    client = TestClient(create_app(runtime))

    initial = client.get("/api/config").json()
    assert initial["config"]["system"]["log_level"] == "INFO"
    csrf = initial["csrf_token"]

    resp = client.post(
        "/api/config",
        json={"patch": {"system": {"log_level": "DEBUG"}}},
        headers={"X-Probos-CSRF": csrf},
    )
    assert resp.status_code == 200, resp.text

    on_disk = yaml.safe_load(Path(runtime.config_path).read_text(encoding="utf-8"))
    assert on_disk["system"]["log_level"] == "DEBUG"

    # Re-GET reflects the *runtime* config, which is unchanged in v1
    # (restart_required). The disk file holds the new value.
    again = client.get("/api/config").json()
    assert again["config"]["system"]["log_level"] == "INFO"


def test_yaml_modal_never_leaks_secret(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.config.cloud_pickers.google_drive.client_secret = "leak-me-not"
    client = TestClient(create_app(runtime))

    text = client.get("/api/config/yaml").text
    assert "leak-me-not" not in text
    assert "<redacted>" in text
