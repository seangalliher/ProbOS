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
        retention=StoreRetention.BOUNDED,
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
)
