"""Engineering Infrastructure -- backup, storage abstraction (AD-466 / AD-1265)."""

from probos.infrastructure.backup import (
    BackupResult,
    BackupService,
    PruneResult,
    is_promoted_snapshot_name,
    parse_snapshot_timestamp,
)
from probos.infrastructure.backup_inventory import (
    EXCLUDED_DATABASES,
    BackupRoot,
    BackupTier,
    DiscoveredDatabase,
    build_default_roots,
    discover,
)
from probos.infrastructure.snapshot_manifest import (
    ManifestEntry,
    SnapshotManifest,
    read_manifest,
    write_manifest,
)
from probos.infrastructure.storage_backend import (
    SQLiteStorageBackend,
    StorageBackend,
)

__all__ = [
    "EXCLUDED_DATABASES",
    "BackupResult",
    "BackupRoot",
    "BackupService",
    "BackupTier",
    "DiscoveredDatabase",
    "ManifestEntry",
    "PruneResult",
    "SQLiteStorageBackend",
    "SnapshotManifest",
    "StorageBackend",
    "build_default_roots",
    "discover",
    "is_promoted_snapshot_name",
    "parse_snapshot_timestamp",
    "read_manifest",
    "write_manifest",
]
