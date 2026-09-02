"""AD-1256: store declarations owned by the tool layer.

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
        id="tools.action-approvals",
        title="Standing action approvals",
        owner_module="probos.tools.action_approvals",
        owner_symbol="ActionApprovalStore",
        canonical_path="action_approvals.db",
        criticality=StoreCriticality.OPTIONAL,
        lifecycle_owner="probos.tools.action_approvals.ActionApprovalStore",
        retention=StoreRetention.UNBOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "No DELETE FROM: revocation flips a row's state rather than "
            "removing it, so a revoked approval stays on the record. That is "
            "correct for a governance artifact -- knowing an approval was "
            "issued and later revoked is the point -- and the growth rate is "
            "bounded in practice by how often a human grants standing "
            "approval, not by machine throughput."
        ),
        notes=(
            "The reference shape for a NEW store: ConnectionFactory injected "
            "through the constructor, db_path defaulting to '' for cache-only "
            "operation, WAL with busy_timeout=5000 and synchronous=NORMAL, and "
            "a module-level _SCHEMA constant. Copy this constructor rather "
            "than calling sqlite3.connect or aiosqlite.connect directly -- a "
            "new direct connect under src/ fails the architecture gate as a "
            "NEW VIOLATION."
        ),
    ),
)
