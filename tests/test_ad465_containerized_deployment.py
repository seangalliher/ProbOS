from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from probos.config import CognitiveConfig


ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_exists() -> None:
    dockerfile = ROOT / "Dockerfile"

    content = dockerfile.read_text(encoding="utf-8")

    assert dockerfile.exists()
    assert "FROM python:3.12-slim" in content
    assert "EXPOSE 18900" in content
    assert 'ENTRYPOINT ["probos"]' in content
    assert 'CMD ["serve", "--host", "0.0.0.0", "--port", "18900", "--data-dir", "/data"]' in content


def test_docker_compose_valid() -> None:
    compose = ROOT / "docker-compose.yml"

    content = compose.read_text(encoding="utf-8")
    parsed: dict[str, Any] = yaml.safe_load(content)

    assert compose.exists()
    assert parsed["services"]["probos"]["ports"] == ["18900:18900"]
    assert parsed["services"]["nats"]["image"] == "nats:2-alpine"
    assert "--jetstream" in parsed["services"]["nats"]["command"]


def test_cognitive_config_env_override(monkeypatch) -> None:
    monkeypatch.setenv("PROBOS_LLM_URL", "http://test:1234/v1")

    config = CognitiveConfig()

    assert config.llm_base_url == "http://test:1234/v1"
    assert config.tier_config("fast")["base_url"] == "http://test:1234/v1"
