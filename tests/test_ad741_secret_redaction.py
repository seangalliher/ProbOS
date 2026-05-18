"""AD-741: Secret-field rule — three-layer defense in depth."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import yaml
from fastapi.testclient import TestClient

from probos.api import create_app
from probos.config import SystemConfig
from probos.settings.section_registry import is_secret_field_id


def _runtime_with_secret(tmp_path: Path) -> MagicMock:
    cfg_path = tmp_path / "system.yaml"
    cfg_path.write_text(yaml.safe_dump({}), encoding="utf-8")
    runtime = MagicMock()
    runtime.config = SystemConfig()
    runtime.config.cloud_pickers.google_drive.client_secret = "xyz-secret"
    runtime.config_path = str(cfg_path)
    runtime._start_time = 0.0
    return runtime


def test_is_secret_field_id_matches_terminal_segment_only() -> None:
    # Layer 0 — the regex is the single source of truth for the rule.
    assert is_secret_field_id("cloud_pickers.google_drive.client_secret") is True
    assert is_secret_field_id("auth.crew_scope_token") is True
    assert is_secret_field_id("channels.discord.token") is True
    assert is_secret_field_id("channels.slack.bot_token") is True
    assert is_secret_field_id("channels.webhook.shared_secret") is True
    assert is_secret_field_id("system.log_level") is False
    assert is_secret_field_id("memory.embedding_model") is False
    # "tokenize" inside the middle of a different word — terminal segment
    # only, so tokenizer fields don't get redacted by mistake.
    assert is_secret_field_id("memory.fts_keyword_semantic_floor") is False


def test_get_config_redacts_secrets_and_emits_presence_map(tmp_path: Path) -> None:
    # Layer 1 — GET redaction.
    runtime = _runtime_with_secret(tmp_path)
    client = TestClient(create_app(runtime))

    body = client.get("/api/config").json()

    cp = body["config"]["cloud_pickers"]["google_drive"]["client_secret"]
    assert cp is None, "secret value must NEVER appear in GET response"
    assert body["secret_present"]["cloud_pickers.google_drive.client_secret"] is True


def test_yaml_render_replaces_secrets_with_redacted_literal(tmp_path: Path) -> None:
    # Layer 2 — YAML view scrubs secrets to ``"<redacted>"``.
    runtime = _runtime_with_secret(tmp_path)
    client = TestClient(create_app(runtime))

    resp = client.get("/api/config/yaml")
    assert resp.status_code == 200
    text = resp.text
    assert "<redacted>" in text
    assert "xyz-secret" not in text


def test_post_config_rejects_secret_field_paths(tmp_path: Path) -> None:
    # Layer 3 — POST that touches a secret-flagged path is rejected and
    # the underlying YAML on disk is unchanged.
    runtime = _runtime_with_secret(tmp_path)
    client = TestClient(create_app(runtime))

    csrf = client.get("/api/config").json()["csrf_token"]
    before = Path(runtime.config_path).read_text(encoding="utf-8")

    resp = client.post(
        "/api/config",
        json={
            "patch": {
                "cloud_pickers": {
                    "google_drive": {"client_secret": "new-secret"},
                },
            },
        },
        headers={"X-Probos-CSRF": csrf},
    )

    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "secret_field_readonly"
    assert body["blocked"] == ["cloud_pickers.google_drive.client_secret"]
    assert Path(runtime.config_path).read_text(encoding="utf-8") == before
