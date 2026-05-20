"""AD-753 tenant policy hook extension point."""

from __future__ import annotations

from typing import Protocol

from probos.security.permission_card import PermissionCard


class TenantPolicyEngine(Protocol):
    """Extension point for tenant-level permission policy evaluation."""

    async def evaluate_permission(self, card: PermissionCard) -> bool:
        """Return whether the policy allows this card."""

    async def audit_log(self, card: PermissionCard, decision: str) -> None:
        """Record policy decision metadata."""


class NullPolicyEngine:
    """OSS default policy engine (Captain remains the policy authority)."""

    async def evaluate_permission(self, card: PermissionCard) -> bool:
        return True

    async def audit_log(self, card: PermissionCard, decision: str) -> None:
        return None
