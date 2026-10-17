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
    StoreDeclaration(
        id="cognitive.standing-interests",
        title="Agent standing interests (AD-1228)",
        owner_module="probos.cognitive.standing_interest_store",
        owner_symbol="StandingInterestStore",
        canonical_path="standing_interests.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="probos.cognitive.standing_interest_store.StandingInterestStore",
        retention=StoreRetention.BOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "Live rows only: at most max_per_agent per agent, each with a NOT NULL expires_at "
            "at most the TTL ceiling. Revoke, expiry and a delivered one-shot delete the row; "
            "expired rows are deleted at start and by every register that writes, and no read "
            "returns one. Agent-authored, so unlike AD-1213/1214 nothing is kept soft-revoked "
            "(BF-735)."
        ),
        notes=(
            "Constructed only when proactive_cognitive.enabled, standing_interests_enabled, a "
            "Ward Room and a tool registry exist. Pending notices and edge/debounce state are in "
            "memory; resume() re-queues work-item notices after a restart."
        ),
    ),
    StoreDeclaration(
        id="cognitive.elastic-teams",
        title="Elastic team specs, slots and worker attempts (AD-1286)",
        owner_module="probos.cognitive.elastic_team_store",
        owner_symbol="ElasticTeamStore",
        canonical_path="elastic_teams.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="probos.cognitive.elastic_team_store.ElasticTeamStore",
        retention=StoreRetention.UNBOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "Insert-only by design: team specs, slots, attempts and outcomes are provenance, and "
            "twelve triggers abort every UPDATE, every DELETE and every INSERT that would replace "
            "an existing row (REPLACE / INSERT OR REPLACE, including through a secondary unique "
            "key); the tables are WITHOUT ROWID, so no implicit rowid exists to replace a row "
            "through, and the module has no delete path. Growth is "
            "bounded per session by each slot's budget.max_attempts (at most 1,024) and by the "
            "number of spec revisions authored. Retention and teardown policy belongs to the "
            "AD-1288/AD-1290 lifecycle, which may add an archival path; this AD adds none."
        ),
        notes=(
            "Constructed only when agentic_dispatch.orchestrator_enabled wires CrewSessionService "
            "(startup/finalize.py). Inert until AD-1288 commissions attempts; a default runtime "
            "never creates the file."
        ),
    ),
    StoreDeclaration(
        id="cognitive.repair-evidence",
        title="First trusted digest per repair evidence reference (AD-1299 S1b)",
        owner_module="probos.cognitive.repair_evidence_store",
        owner_symbol="RepairEvidenceLinkStore",
        canonical_path="repair_evidence.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="unowned",
        retention=StoreRetention.UNBOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "Insert-only by design: six triggers abort every UPDATE, every DELETE and every replacing "
            "INSERT on both WITHOUT ROWID tables, and the module has no delete path. Growth is at most "
            "two rows per evidence reference (the first trusted digest and the first different digest), "
            "and references are created per candidate per gate run or review round. Archival belongs to "
            "the S4 release lifecycle; this slice adds none."
        ),
        notes=(
            "Not wired: nothing constructs or starts the store in production until AD-1299 S2 admission, "
            "so a default runtime never creates the file (lifecycle_owner is the 'unowned' sentinel). "
            "Detection only: a writer with ProbOS's OS identity can delete the file, which resets the "
            "first trusted digests (D-B2)."
        ),
    ),
    StoreDeclaration(
        id="cognitive.profile-qualifications",
        title="Execution profiles, evaluation evidence and invalidations (AD-1287 S1)",
        owner_module="probos.cognitive.profile_qualification_store",
        owner_symbol="ProfileQualificationStore",
        canonical_path="profile_qualifications.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="unowned",
        retention=StoreRetention.UNBOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "Insert-only by design: twelve triggers abort every UPDATE, every DELETE and every replacing "
            "INSERT on the four WITHOUT ROWID tables, and the module has no delete path. Growth is one row "
            "per registered profile, one per evaluation run, one per invalidation and one per learned attempt "
            "outcome (S3); no retention or lifecycle cap bounds evaluation runs or learned outcomes per profile "
            "(only the 2**53 - 1 sequence limit does). Archival belongs to a "
            "later lifecycle slice; S1 and S3 add none."
        ),
        notes=(
            "Not wired: nothing constructs or starts the store in production until AD-1288 commission "
            "admission calls admit_current_qualified_attempt, so a default runtime never creates the file "
            "(lifecycle_owner is the 'unowned' sentinel). start() accepts an empty file, exactly the S1 layout "
            "(to which it adds the S3 outcome table and triggers in the same transaction) or exactly the S1+S3 "
            "layout, refuses any other file and issues no schema or data write to it; the S1 code refuses a file "
            "the S3 code has started. Each row the store uses to decide or return a result is re-verified and one that "
            "does not verify is refused, except that a learned attempt whose stored profile differs from the one "
            "named is refused as a conflict without verifying that row; a missing row, or a store stamp rewritten "
            "within range, is not detected, and evaluators are not authenticated."
        ),
    ),
    StoreDeclaration(
        id="cognitive.procedure-challenges",
        title="Procedure challengers and their head-to-head evidence (AD-1326)",
        owner_module="probos.cognitive.procedure_challenges",
        owner_symbol="ProcedureChallengeLedger",
        canonical_path="procedures/procedures_challenges.db",
        criticality=StoreCriticality.OPTIONAL,
        lifecycle_owner="probos.cognitive.procedure_store.ProcedureStore",
        retention=StoreRetention.UNBOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "Nothing is deleted: a retired challenger keeps its evidence (#1510). Growth is one "
            "challenge row per FIX evolution, at most dreaming.procedure_challenger_max_pending_per_champion "
            "pending per champion; at most dreaming.procedure_challenger_max_judge_calls_per_cycle / 2 "
            "comparison rows per dream cycle; and one cycle row per dream cycle that judged, deferred or "
            "decided something. Archival belongs to a later lifecycle slice; this one adds none."
        ),
        notes=(
            "Opened and closed by ProcedureStore.start/stop beside procedures.db through the store's "
            "ConnectionFactory, on its own connection, so its writes never share procedures.db's "
            "transactions. ProcedureStore holds that connection as a direct attribute, which BF-882's "
            "last-resort close reaches when the store's stop() fails in a startup rollback. A ledger that fails to open leaves ProcedureStore running and FIX evolution on "
            "its legacy handling. The two files are copied separately; the backup copies in sorted path "
            "order, so this file (named to sort after procedures.db) is copied second and, when both "
            "online backups succeed, a restored ledger is never older than procedures.db; the raw-copy "
            "fallback can copy an older image. While this ledger is open and readable, "
            "ProcedureStore.find_matching refuses any challenger it holds retired, and any it holds "
            "pending unless procedures.db already holds that challenger's completed promotion (its "
            "champion inactive and superseded by it), so no undecided challenger routes; with the ledger "
            "closed or unreadable, procedures.db alone decides (fail-open). When the challenger service "
            "is enabled (dreaming.procedure_challenger_enabled) and a dream reaches its step, a pair from "
            "different moments is reconciled: the step records a promotion procedures.db already holds "
            "(restored_promotion), deactivates any other routable pending challenger and retires orphans "
            "with their evidence (challenger_missing, champion_inactive); with the service disabled the "
            "ledger is left as restored and routing still follows the rule above. A ledger newer than "
            "procedures.db leaves the older routing in place."
        ),
    ),
    StoreDeclaration(
        id="cognitive.episode-archive",
        title="Episode archive: evicted episodes kept out of recall (AD-1340)",
        owner_module="probos.cognitive.episode_archive",
        owner_symbol="EpisodeArchive",
        canonical_path="episode_archive.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="probos.cognitive.episodic.EpisodicMemory",
        retention=StoreRetention.UNBOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "Unbounded by design (AD-1340): dream pruning and capacity eviction move episodes here "
            "instead of deleting them, and nothing in the loop drops archived content. Rows leave only "
            "by the Captain's erasure (AD-754), which overwrites them (PRAGMA secure_delete=ON), and by "
            "a Tier 2 reset, which deletes the file. A retention window is the Captain's policy (AD-1340 "
            "S5) and the default is none. Estimated at about 150 MB compressed if every episode pruned to "
            "date had been archived (an estimate, not a measurement); S3 surfaces the real size."
        ),
        notes=(
            "Opened and closed by EpisodicMemory.start/stop beside episode_fts.db, through an injected "
            "ConnectionFactory. Gated on memory.eviction_disposition: in 'delete' mode the file is "
            "opened only if it already exists (so erasure can clear it) and is never created. Backed up "
            "as INCLUDED; erased content persists in earlier snapshots until they age out, as ChromaDB's "
            "does. Never read by default recall."
        ),
    ),
)
