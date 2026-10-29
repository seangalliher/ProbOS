"""AD-1346 M3b (#1604): the store declaration of the admission package (AD-1256).

Data only: no import of the store declared here.
"""

from __future__ import annotations

from probos.storage.declarations import (
    StoreCriticality,
    StoreDeclaration,
    StoreRetention,
)

STORE_DECLARATIONS: tuple[StoreDeclaration, ...] = (
    StoreDeclaration(
        id="admission.shadow-decisions",
        title="The shadow admission decision's counts, would-refuse samples and markers (AD-1346 M3b)",
        owner_module="probos.admission.store",
        owner_symbol="AdmissionShadowStore",
        canonical_path="admission_shadow.db",
        criticality=StoreCriticality.OPTIONAL,
        lifecycle_owner="unowned",
        retention=StoreRetention.BOUNDED,
        retention_note=(
            "Bounded by the constants of probos.admission.store: prune keeps AGGREGATE_RETENTION_DAYS UTC "
            "days of aggregates and at most AGGREGATE_ROW_LIMIT rows (whole older days first, never the "
            "current day), and MARKER_RETENTION_DAYS days of markers and at most MARKER_ROW_LIMIT rows "
            "(oldest hours first); each write_batch that adds samples keeps the newest SAMPLE_RING_SIZE."
        ),
        backup="included",
        restore="unknown",
        notes=(
            "Opened through the ConnectionFactory. Tables: schema_version, shadow_aggregates, "
            "shadow_samples and shadow_markers. start opens a file whose schema_version holds exactly "
            "one row of SCHEMA_VERSION, writes that row to a file with no row, and refuses a file with "
            "any other rows without writing to it; there is no migration."
        ),
    ),
)
