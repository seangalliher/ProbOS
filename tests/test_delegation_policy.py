from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _prompt(name: str) -> str:
    # Closed-issue prompts are archived to prompts/archive/ (383dde25).
    p = ROOT / "prompts" / name
    if not p.exists():
        p = ROOT / "prompts" / "archive" / name
    return _read(p)


def test_delegation_policy_conformance_gate() -> None:
    connector_text = _read(ROOT / "src" / "probos" / "integrations" / "m365_connector.py")
    descriptor_count = connector_text.count("IntentDescriptor(")
    description_count = connector_text.count("description=")
    assert descriptor_count > 0
    assert description_count >= descriptor_count

    runtime_text = _read(ROOT / "src" / "probos" / "runtime.py")
    assert "intent_bus" in runtime_text

    ad756_text = _prompt("ad-756-yeo-conversational-front-door-ux.md")
    assert "delegation_reason" in ad756_text
    assert "/dag/{dag_id}/delegation-trace" in ad756_text
