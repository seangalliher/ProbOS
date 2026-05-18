"""AD-741: /api/config endpoint tests.

BF-287: use real ``SystemConfig()`` and real ``runtime.config_path``.
``runtime`` itself is a MagicMock with the few attributes the router
reads (``config``, ``_start_time``, ``config_path``).
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from fastapi.testclient import TestClient

from probos.api import create_app
from probos.config import SystemConfig


def _build_runtime(tmp_path: Path, *, write_yaml: bool = True) -> MagicMock:
    cfg_path = tmp_path / "system.yaml"
    if write_yaml:
        cfg_path.write_text(yaml.safe_dump({}), encoding="utf-8")
    runtime = MagicMock()
    runtime.config = SystemConfig()
    runtime.config_path = str(cfg_path) if write_yaml else None
    runtime._start_time = 0.0
    return runtime


def _client(runtime: MagicMock) -> TestClient:
    app = create_app(runtime)
    return TestClient(app)


def test_get_config_returns_sections_and_csrf(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    client = _client(runtime)

    resp = client.get("/api/config")

    assert resp.status_code == 200
    body = resp.json()
    assert "config" in body
    assert "sections" in body
    assert "csrf_token" in body and body["csrf_token"]
    assert body["uptime_seconds"] >= 0
    assert body["section_count"] == len(body["sections"])
    assert body["domain_order"] == [
        "Core",
        "Perception & Voice",
        "Identity & Presentation",
        "Connectivity",
    ]


def test_get_config_yaml_round_trips(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    client = _client(runtime)

    resp = client.get("/api/config/yaml")

    assert resp.status_code == 200
    parsed = yaml.safe_load(resp.text)
    assert isinstance(parsed, dict)
    assert "system" in parsed
    assert parsed["system"]["name"] == "ProbOS"


def test_post_config_without_csrf_returns_403(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    client = _client(runtime)

    resp = client.post(
        "/api/config",
        json={"patch": {"system": {"log_level": "DEBUG"}}},
    )

    assert resp.status_code == 403
    assert resp.json()["error"] == "invalid_csrf"


def test_post_config_valid_patch_writes_file_and_marks_restart(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    client = _client(runtime)

    csrf = client.get("/api/config").json()["csrf_token"]
    resp = client.post(
        "/api/config",
        json={"patch": {"system": {"log_level": "DEBUG"}}},
        headers={"X-Probos-CSRF": csrf},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["restart_required"] is True
    assert body["changed_fields"] == ["system.log_level"]

    on_disk = yaml.safe_load(Path(runtime.config_path).read_text(encoding="utf-8"))
    assert on_disk["system"]["log_level"] == "DEBUG"


def test_post_config_invalid_value_returns_422(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    client = _client(runtime)

    csrf = client.get("/api/config").json()["csrf_token"]
    resp = client.post(
        "/api/config",
        json={"patch": {"memory": {"max_episodes": "not-an-int"}}},
        headers={"X-Probos-CSRF": csrf},
    )

    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "validation_failed"
    assert any(err["loc"] and err["loc"][0] == "memory" for err in body["errors"])


def test_post_config_without_config_path_returns_503(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path, write_yaml=False)
    client = _client(runtime)

    csrf = client.get("/api/config").json()["csrf_token"]
    resp = client.post(
        "/api/config",
        json={"patch": {"system": {"log_level": "DEBUG"}}},
        headers={"X-Probos-CSRF": csrf},
    )

    assert resp.status_code == 503
    assert resp.json()["error"] == "config_path_unavailable"


def test_csrf_token_is_single_consume(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    client = _client(runtime)

    csrf = client.get("/api/config").json()["csrf_token"]
    first = client.post(
        "/api/config",
        json={"patch": {"system": {"log_level": "DEBUG"}}},
        headers={"X-Probos-CSRF": csrf},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/config",
        json={"patch": {"system": {"log_level": "INFO"}}},
        headers={"X-Probos-CSRF": csrf},
    )
    assert second.status_code == 403
    assert second.json()["error"] == "invalid_csrf"


def test_section_registry_shape(tmp_path: Path) -> None:
    """Sidebar groupings and counts come from the live registry, never hardcoded."""
    runtime = _build_runtime(tmp_path)
    client = _client(runtime)

    body = client.get("/api/config").json()
    assert set(body["domain_counts"].keys()) <= {
        "Core",
        "Perception & Voice",
        "Identity & Presentation",
        "Connectivity",
    }
    section_ids = [s["section_id"] for s in body["sections"]]
    # AD-741 ships 10; AD-733 adds perception in the same wave.
    assert "system" in section_ids
    assert section_ids[0] == "system"
    assert body["sections"][0]["fields"][0]["field_id"] == "system.name"


def test_no_magicmock_at_substrate_boundary() -> None:
    """BF-287 sentinel: AD-741 production code must not import MagicMock."""
    src = Path("src/probos/routers/config.py").read_text(encoding="utf-8")
    src += Path("src/probos/settings/section_registry.py").read_text(encoding="utf-8")
    assert "MagicMock" not in src
    assert not re.search(r"\bmock\.\w+", src)
