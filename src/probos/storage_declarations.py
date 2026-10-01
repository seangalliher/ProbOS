"""AD-1256: store declarations owned by the top-level ``probos`` modules.

This module exists because ``probos/workforce.py`` is a module rather than a
package, so it has no directory of its own to declare into. Its declaration
lives beside it here.

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
        id="workforce.work-items",
        title="Workforce scheduling engine store",
        owner_module="probos.workforce",
        owner_symbol="WorkItemStore",
        canonical_path="workforce.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="probos.startup.communication.init_communication_services",
        retention=StoreRetention.UNBOUNDED,
        retention_note=(
            "AD-1192 owned-step operation receipts, immutable evidence, "
            "proposal/observation records, retired-child lineage and "
            "effect-attempt claims in workforce.db are retained indefinitely. "
            "Deleting or compacting these identities could replay execution, "
            "forget retired membership or lose an uncertain effect. Control, "
            "proposal manifests/acknowledgements and individual journal records "
            "are bounded to 2 MiB; raw repair evidence is retained separately "
            "without a lifetime operation-count quota."
        ),
        backup="included",
        restore="point-in-time",
        notes=(
            "Gated on config.workforce.enabled (AD-496). Separately locked "
            "from chat_threads.db ON PURPOSE and load-bearing: AD-1274's "
            "turn_promotion._post_report writes a report that chat_threads.db "
            "refused into promoted_report_outbox here, and startup/finalize.py "
            "states the reason -- 'a different file behind a different lock'. "
            "Merging these two databases would make that escape path "
            "impossible, because SQLite takes one writer per file. Any future "
            "consolidation proposal must answer this note first."
        ),
    ),
    StoreDeclaration(
        id="fault.issue-filings",
        title="Fault issue-filing duplicate-suppression journal",
        owner_module="probos.fault_issue_filings",
        owner_symbol="FaultIssueFilings",
        canonical_path="fault_reports.db",
        criticality=StoreCriticality.REQUIRED,
        lifecycle_owner="probos.fault_report.FaultReportStore",
        retention=StoreRetention.UNBOUNDED,
        retention_note=(
            "Retain signature rows indefinitely for durable duplicate "
            "suppression across restarts."
        ),
        backup="included",
        restore="unknown",
        reconstruction="",
        notes=(
            "Companion table co-located with fault_reports in fault_reports.db, "
            "sharing FaultReportStore's connection and persistence lock. "
            "FaultReportStore start/stop own lifecycle; no independent companion "
            "lifecycle. Retention describes journal only. Backup inclusion is "
            "conditional on enabled snapshots; restore behavior is unverified."
        ),
    ),
    StoreDeclaration(
        id="approvals.approval-authority",
        title="Captain approval-authority records (AD-1213)",
        owner_module="probos.approval_authority",
        owner_symbol="ApprovalAuthorityStore",
        canonical_path="approval_authority.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="probos.approval_authority.ApprovalAuthorityStore",
        retention=StoreRetention.UNBOUNDED,
        retention_note=(
            "No DELETE FROM: revoking or superseding a record flips its "
            "revoked flag, so every delegation and unavailability mark stays "
            "on the record. Growth is bounded by how often the Captain acts."
        ),
        backup="included",
        restore="point-in-time",
        notes=(
            "Constructed only when approval_inbox.delegated_approvals_enabled. "
            "expires_at is NOT NULL: neither a First Officer delegation nor a "
            "Captain-unavailable mark can be issued without an expiry."
        ),
    ),
    StoreDeclaration(
        id="approvals.decision-pre-clearances",
        title="Captain decision pre-clearances (AD-1214)",
        owner_module="probos.decision_pre_clearance",
        owner_symbol="DecisionPreClearanceStore",
        canonical_path="decision_pre_clearances.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="probos.decision_pre_clearance.DecisionPreClearanceStore",
        retention=StoreRetention.UNBOUNDED,
        retention_note=(
            "No DELETE FROM: revoking or superseding a pre-clearance flips its "
            "revoked flag, so every pre-clearance stays on the record. Growth is "
            "bounded by how often the Captain acts."
        ),
        backup="included",
        restore="point-in-time",
        notes=(
            "Constructed only when approval_inbox.delegated_approvals_enabled "
            "and decision_pre_clearance_enabled. expires_at and every key column "
            "are NOT NULL and CHECK-bounded, so no pre-clearance exists without "
            "an expiry or with a wildcard. It stops a notification; it confers "
            "no authority. Offers are in memory only."
        ),
    ),
    StoreDeclaration(
        id="identity.key-binding",
        title="Ship DID key events and certificate signatures (AD-1196)",
        owner_module="probos.identity_key_binding",
        owner_symbol="IdentityKeyBinding",
        canonical_path="identity.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="probos.identity.AgentIdentityRegistry",
        retention=StoreRetention.UNBOUNDED,
        retention_note=(
            "Append-only: one row per key event and per signed certificate, never deleted. "
            "Growth is bounded by births, transfers and the Captain's key actions."
        ),
        backup="included",
        restore="unknown",
        reconstruction="",
        notes=(
            "Companion tables co-located with the AD-441 identity ledger in identity.db, sharing "
            "AgentIdentityRegistry's connection and ledger lock; created only when "
            "federation.identity_keys_enabled. Public keys, key events and signatures only: private "
            "keys never enter this database (OS keyring, or the explicit plaintext_dev directory)."
        ),
    ),
    StoreDeclaration(
        id="federation.envelope-replay",
        title="Federation envelope key holds and replay windows (AD-1197)",
        owner_module="probos.federation_envelope_store",
        owner_symbol="EnvelopeStore",
        canonical_path="federation_envelopes.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="probos.federation.envelope.EnvelopeGuard",
        retention=StoreRetention.UNBOUNDED,
        retention_note=(
            "No DELETE FROM: one row per sender ever held (at most 256), with at most 4,096 key ids each, at most "
            "two replay windows per sender and one send-epoch row, updated in place and only ever forward."
        ),
        backup="included",
        restore="unknown",
        reconstruction="",
        notes=(
            "Constructed only when federation.envelope_signing_enabled. Public key-event histories, key ids, counters "
            "and 64-bit window masks only: no private key, envelope signature or message body. Restoring an older copy "
            "rolls replay windows back (envelopes recorded after the backup are accepted once more); deleting "
            "it forgets every hold and every recorded key id (the next envelope from each sender is a first contact), "
            "and a sender that lost its own copy restarts at epoch 1 until it rotates its key."
        ),
    ),
)
