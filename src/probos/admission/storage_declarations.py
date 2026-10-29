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
        lifecycle_owner="probos.runtime.ProbOSRuntime.start",
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
            "Started in ProbOSRuntime.start before the shadow AdmissionService, inside a try: a store or "
            "recorder that does not start is logged, the service is built without a recorder and the boot "
            "continues. Stopped in startup/shutdown.py after the recorder's last flush, before the identity "
            "registry. Opened through the ConnectionFactory. Tables: schema_version, shadow_aggregates, "
            "shadow_samples and shadow_markers. start opens a file whose schema_version holds exactly "
            "one row of SCHEMA_VERSION, writes that row to a file with no row, and refuses a file with "
            "any other rows without writing to it; there is no migration. Written by "
            "probos.admission.recorder.ShadowRecorder and read by probos.admission.report. No probos reset "
            "tier deletes it."
        ),
    ),
)
