"""AD-1256: store declarations owned by the cognitive layer.

Data only — no import of the stores declared here. See
``probos.storage.declarations`` for why these fields are inert.
"""

from __future__ import annotations

from probos.storage.declarations import (
    StoreCriticality,
    StoreDeclaration,
    StoreRetention,
)

STORE_DECLARATIONS: tuple[StoreDeclaration, ...] = (
    StoreDeclaration(
        id="cognitive.activation-tracker",
        title="ACT-R episode activation log",
        owner_module="probos.cognitive.activation_tracker",
        owner_symbol="ActivationTracker",
        canonical_path="activation_tracker.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="probos.startup.cognitive_services.init_cognitive_services",
        retention=StoreRetention.BOUNDED,
        backup="excluded",
        restore="reconstructed",
        retention_note=(
            "180-day self-retention plus a prune pass, and the bound "
            "demonstrably does not hold: activation_tracker.py caps each pass "
            "at max_prune_fraction=0.10 of total episodes, so a store that "
            "gains rows faster than 10% per pass never catches up. Measured at "
            "1.03 GB across 6,820,292 rows in its sole table "
            "(backup_inventory.py). This store is the reason retention is a "
            "declared field rather than an assumed property."
        ),
        reconstruction=(
            "None. The table repopulates organically as ACT-R logs episode "
            "accesses against episodes that live in ChromaDB, which AD-823 "
            "snapshots separately. Losing it degrades activation ranking and "
            "destroys nothing, which is why AD-1265 excludes it from backup."
        ),
        notes=(
            "Gated on config.dreaming.activation_enabled. The single largest "
            "backup decision in AD-1265 by bytes."
        ),
    ),
    StoreDeclaration(
        id="cognitive.eviction-audit",
        title="Working-memory eviction audit trail",
        owner_module="probos.cognitive.eviction_audit",
        owner_symbol="EvictionAuditLog",
        canonical_path="eviction_audit.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="probos.startup.cognitive_services.init_cognitive_services",
        retention=StoreRetention.UNBOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "Deliberately unbounded: the module contains no DELETE FROM, and "
            "an audit trail that deletes its own history is not an audit "
            "trail. 140.1 MB across 323,066 rows at AD-1265's measurement. "
            "AD-1265 considered and rejected excluding it from backup for "
            "exactly this reason -- an audit trail is by definition not "
            "reconstructible."
        ),
        notes="Verified unbounded: git grep 'DELETE FROM' finds nothing here.",
    ),
    StoreDeclaration(
        id="cognitive.journal",
        title="Cognitive journal",
        owner_module="probos.cognitive.journal",
        owner_symbol="CognitiveJournal",
        canonical_path="cognitive_journal.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="probos.startup.communication.init_communication_services",
        retention=StoreRetention.BOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "A prune loop runs beside the store "
            "(startup/communication.py names the cognitive-journal-prune-loop "
            "task). 152.3 MB across 350,567 rows at AD-1265's measurement, so "
            "the bound is loose; AD-1265/1266's size census is what would turn "
            "'has a delete path' into evidence that it works."
        ),
        notes=(
            "Gated on config.cognitive_journal.enabled. AD-1265 rejected "
            "excluding it from backup: the journal IS the record, and there is "
            "no upstream to replay it from."
        ),
    ),
    StoreDeclaration(
        id="cognitive.episode-fts",
        title="Episode full-text search sidecar",
        owner_module="probos.cognitive.episodic",
        owner_symbol="EpisodicMemory",
        canonical_path="episode_fts.db",
        criticality=StoreCriticality.OPTIONAL,
        lifecycle_owner="probos.cognitive.episodic.EpisodicMemory",
        retention=StoreRetention.EXTERNAL,
        backup="included",
        restore="unknown",
        retention_note=(
            "Rows expire only when the episodes they index expire; this "
            "FTS5 sidecar (AD-567b) has no retention of its own."
        ),
        notes=(
            "Restore is 'unknown' rather than 'reconstructed' on purpose. It "
            "is derived data, so reconstruction looks obvious, but AD-1265 "
            "measured that the only repopulation path is EpisodicMemory's "
            "internal seed and there is no rebuild entry point -- so "
            "reconstructibility is not operationally established, and claiming "
            "it would be the kind of assumed-derived reasoning that loses "
            "data. Promotion condition: AD-1266 demonstrates a rebuild."
        ),
    ),
)
