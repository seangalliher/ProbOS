from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_oss_scope_verification_gate() -> None:
    m365_text = _read(ROOT / "src" / "probos" / "integrations" / "m365_token_manager.py").lower()
    assert "multi_tenant" not in m365_text

    policy_text = _read(ROOT / "src" / "probos" / "governance" / "policy_engine.py")
    assert "class TenantPolicyEngine" in policy_text
    assert "class NullPolicyEngine" in policy_text

    crypto_text = _read(ROOT / "src" / "probos" / "security" / "credential_encryption.py").lower()
    assert "hsm" not in crypto_text
    assert "key vault" not in crypto_text
    assert "byok" not in crypto_text

    lifecycle_text = _read(ROOT / "src" / "probos" / "experience" / "desktop" / "lifecycle.py").lower()
    assert "fleet" not in lifecycle_text

    registry_text = _read(ROOT / "src" / "probos" / "integrations" / "template_registry.py").lower()
    assert "org_library" not in registry_text
    assert "sharepoint_library" not in registry_text
