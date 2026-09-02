"""AD-1256: store declarations owned by the ward room.

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
        id="ward-room.threads",
        title="Ward Room threads, posts and endorsements",
        owner_module="probos.ward_room.threads",
        owner_symbol="ThreadManager",
        canonical_path="ward_room.db",
        criticality=StoreCriticality.OPTIONAL,
        lifecycle_owner="probos.ward_room.threads.ThreadManager",
        retention=StoreRetention.BOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "Real, tiered and self-owned: retention_days=7 for regular posts, "
            "30 for endorsed, and 0 (never) for Captain posts, applied by "
            "ThreadManager.start_prune_loop."
        ),
        notes=(
            "The prune loop archives to dated ``archives/ward_room_*.db`` "
            "sidecars, which AD-1265 treats as immutable-but-included. Those "
            "sidecars have no retention of their own and no declared "
            "lifecycle -- they are the store's undeclared tail, and the honest "
            "record of that is this note rather than a field, because nothing "
            "in this slice measures or prunes them."
        ),
    ),
)
