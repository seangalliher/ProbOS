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


def test_perception_section_appears_in_sections_list(tmp_path: Path) -> None:
    """BF-297: routers/config.py must read live section_registry.SECTIONS,
    not the stale tuple captured at from-import time. AD-733's perception
    section is inserted at module-import of probos.perception; if config.py
    captured SECTIONS before that import ran, the Settings UI silently
    drops the Perception section.
    """
    runtime = _runtime(tmp_path)
    client = TestClient(create_app(runtime))

    payload = client.get("/api/config").json()
    section_ids = [s["section_id"] for s in payload["sections"]]
    assert "perception" in section_ids, (
        f"perception section missing from /api/config response; "
        f"got {section_ids}. Likely stale from-import capture of SECTIONS."
    )
    assert payload["section_count"] == len(section_ids)


def test_perception_enable_toggle_is_hot_reload_no_restart(tmp_path: Path) -> None:
    """BF-299: flipping perception.enabled or perception.camera.enabled must
    NOT require restart — the gates are read live on every frame upload, and
    forcing Captain to restart between each toggle is hostile UX.
    """
    runtime = _runtime(tmp_path)
    assert runtime.config.perception.enabled is False
    assert runtime.config.perception.camera.enabled is False

    client = TestClient(create_app(runtime))
    csrf = client.get("/api/config").json()["csrf_token"]

    resp = client.post(
        "/api/config",
        json={"patch": {"perception": {"enabled": True, "camera": {"enabled": True}}}},
        headers={"X-Probos-CSRF": csrf},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["restart_required"] is False, body
    assert set(body["changed_fields"]) == {
        "perception.enabled",
        "perception.camera.enabled",
    }

    # Runtime config mutated live.
    assert runtime.config.perception.enabled is True
    assert runtime.config.perception.camera.enabled is True


def test_mixed_hot_reload_and_restart_field_still_requires_restart(tmp_path: Path) -> None:
    """If ANY changed field is not hot-reload-eligible, the whole APPLY
    requires restart (no partial-apply confusion)."""
    runtime = _runtime(tmp_path)
    client = TestClient(create_app(runtime))
    csrf = client.get("/api/config").json()["csrf_token"]

    resp = client.post(
        "/api/config",
        json={
            "patch": {
                "perception": {"enabled": True},
                "system": {"log_level": "DEBUG"},
            }
        },
        headers={"X-Probos-CSRF": csrf},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["restart_required"] is True, body
    # Runtime NOT mutated because mixed-mode requires restart.
    assert runtime.config.perception.enabled is False


def test_bf308_perception_threshold_hot_reload(tmp_path: Path) -> None:
    """BF-308: tuning perception.vision_novelty_threshold via /api/config
    propagates LIVE into the in-flight VisionConsumer's supervisor
    strategy (no restart needed)."""
    from probos.perception.consumer import VisionConsumer

    runtime = _runtime(tmp_path)
    consumer = VisionConsumer(runtime, min_interval_seconds=5.0, novelty_threshold=0.15)
    runtime.vision_consumer = consumer

    client = TestClient(create_app(runtime))
    csrf = client.get("/api/config").json()["csrf_token"]

    resp = client.post(
        "/api/config",
        json={"patch": {"perception": {
            "vision_novelty_threshold": 0.05,
            "vision_min_interval_seconds": 2.0,
        }}},
        headers={"X-Probos-CSRF": csrf},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["restart_required"] is False

    # Runtime config mutated AND in-flight supervisor received the new values.
    assert runtime.config.perception.vision_novelty_threshold == 0.05
    assert runtime.config.perception.vision_min_interval_seconds == 2.0
    assert consumer._supervisor._strategy._threshold == 0.05
    assert consumer._supervisor._strategy._min_interval == 2.0
