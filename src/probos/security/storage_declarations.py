"""AD-1256: store declarations owned by the security layer.

Data only — no import of the stores declared here.
"""

from __future__ import annotations

from probos.storage.declarations import (
    StoreCriticality,
    StoreDeclaration,
    StoreRetention,
)

STORE_DECLARATIONS: tuple[StoreDeclaration, ...] = (
    StoreDeclaration(
        id="security.assistant-audit-log",
        title="Assistant audit log",
        owner_module="probos.security.audit_log",
        owner_symbol="AuditLog",
        canonical_path="assistant_audit.db",
        criticality=StoreCriticality.OPTIONAL,
        lifecycle_owner="probos.routers.security",
        retention=StoreRetention.BOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "retention_days=90 by default, enforced by a DELETE FROM "
            "assistant_audit_log on a timestamp cutoff."
        ),
        notes=(
            "One of the modules that builds its schema inline at the execute() "
            "call rather than binding a module-level constant, so the "
            "exists->declared checker sees it only through the "
            "execute-argument rule."
        ),
    ),
)
