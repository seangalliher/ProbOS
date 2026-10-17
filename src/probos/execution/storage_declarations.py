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
    StoreDeclaration(
        id="execution.command-approvals",
        title="Command policy approvals and the runs they admitted (AD-1328)",
        owner_module="probos.execution.command_approvals",
        owner_symbol="SqliteCommandApprovalStore",
        canonical_path="command_approvals.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="probos.execution.command_approvals.SqliteCommandApprovalStore",
        retention=StoreRetention.UNBOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "No DELETE statements: each approval or denial and every run it admitted is "
            "governance evidence. Growth is one row per decided escalation and one per run."
        ),
        notes=(
            "Constructed only when execution.command_policy has rules. Rows are written only "
            "from a Captain decision on a run_command action request; a run is recorded "
            "before the command starts."
        ),
    ),
)
