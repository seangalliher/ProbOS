"""AD-1315 store declarations owned by the execution layer."""

from __future__ import annotations

from probos.storage.declarations import (
    StoreCriticality,
    StoreDeclaration,
    StoreRetention,
)

STORE_DECLARATIONS: tuple[StoreDeclaration, ...] = (
    StoreDeclaration(
        id="execution.protected-authority",
        title="Protected execution authority and governed effect witness",
        owner_module="probos.execution.authority",
        owner_symbol="ProtectedExecutionAuthority",
        canonical_path="execution_authority.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="probos.execution.authority.ProtectedExecutionAuthority",
        retention=StoreRetention.UNBOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "No DELETE statements: admissions, grants, effect operations, attempts, "
            "and transitions are governance evidence."
        ),
    ),
)
