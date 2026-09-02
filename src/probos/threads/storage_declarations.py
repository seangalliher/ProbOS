"""AD-1256: store declarations owned by the threads layer.

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
        id="threads.chat-threads",
        title="Captain chat threads, messages and projects",
        owner_module="probos.threads",
        owner_symbol="ChatThreadStore",
        canonical_path="chat_threads.db",
        criticality=StoreCriticality.REQUIRED,
        lifecycle_owner="probos.runtime.ProbOSRuntime",
        retention=StoreRetention.BOUNDED,
        backup="included",
        restore="point-in-time",
        notes=(
            "Constructed unconditionally by the runtime, so a vessel does not "
            "boot to a usable conversation surface without it. Deletion is "
            "tombstoned rather than immediate (chat_thread_tombstones). "
            "Separately locked from workforce.db ON PURPOSE: see the "
            "workforce.work-items declaration for the BF-826/#1290 escape path "
            "that depends on these being two files with two locks."
        ),
    ),
)
