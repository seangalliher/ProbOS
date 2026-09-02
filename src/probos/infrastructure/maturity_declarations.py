"""AD-1270a: capability declarations owned by infrastructure.

Data only — no import of the subsystems declared here. See the cognitive-layer
declaration module for the reasoning.
"""

from __future__ import annotations

from probos.maturity.model import CapabilityDeclaration

MATURITY_DECLARATIONS: tuple[CapabilityDeclaration, ...] = (
    CapabilityDeclaration(
        id="infrastructure.snapshot-manifest",
        title="Snapshot manifest",
        owner_module="probos.infrastructure.snapshot_manifest",
        owner_symbol="SnapshotManifest",
        configured_when="ship_state_snapshot.enabled",
        seam_ids=("TA-P0-006-snapshot-restore-read",),
        notes=(
            "Attests what a snapshot contains. A snapshot whose manifest is "
            "absent is not restorable, which is why this is declared rather "
            "than assumed from the presence of the backup service."
        ),
    ),
)
