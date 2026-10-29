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
        title="The shadow admission decision's counts, would-refuse samples, markers, parity counts and disagreement samples (AD-1346 M3b, M3c)",
        owner_module="probos.admission.store",
        owner_symbol="AdmissionShadowStore",
        canonical_path="admission_shadow.db",
        criticality=StoreCriticality.OPTIONAL,
        lifecycle_owner="probos.runtime.ProbOSRuntime.start",
        retention=StoreRetention.BOUNDED,
        retention_note=(
            "Bounded by the constants of probos.admission.store: prune deletes the aggregates of days "
            "before the last AGGREGATE_RETENTION_DAYS UTC days, then, while more than AGGREGATE_ROW_LIMIT "
            "rows remain, the oldest whole day before the current one. It never deletes a row of the "
            "current day or of a later one (a later day exists after the wall clock steps back), so more "
            "than AGGREGATE_ROW_LIMIT rows remain only when every one is of such a day. It deletes the "
            "markers of days before the last MARKER_RETENTION_DAYS, then the oldest hours while more than "
            "MARKER_ROW_LIMIT rows remain; each write_batch that adds samples keeps the newest SAMPLE_RING_SIZE. "
            "AD-1346 M3c: prune deletes the parity counts of days before the last AGGREGATE_RETENTION_DAYS UTC "
            "days, and each write_batch that adds disagreement samples keeps the newest DISAGREEMENT_RING_SIZE."
        ),
        backup="included",
        restore="unknown",
        notes=(
            "Started in ProbOSRuntime.start, only while admission.shadow_enabled is true (AD-1346 M3c), before "
            "the shadow AdmissionService, inside a try: a store or "
            "recorder whose start raises an Exception is logged, the service is built without a recorder "
            "and the boot continues. Stopped in startup/shutdown.py after the service is closed and the "
            "recorder's last flush, before the identity "
            "registry. Opened through the ConnectionFactory. Tables: schema_version, shadow_aggregates, "
            "shadow_samples, shadow_markers and, from AD-1346 M3c, shadow_parity and shadow_disagreements. "
            "start opens a file whose schema_version holds exactly "
            "one row of SCHEMA_VERSION, writes that row to a file with no row, and refuses a file with "
            "any other rows without writing to it; there is no migration, and M3c's two tables are "
            "additive under version 1 (start creates them on any version-1 file). Written by "
            "probos.admission.recorder.ShadowRecorder and read by probos.admission.report. No probos reset "
            "tier deletes it."
        ),
    ),
)
