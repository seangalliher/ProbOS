"""AD-1003a: Capability Packs — cross-tool agent-plugin format (parse/validate).
AD-1003b: read-only pack scanner (installed-pack inventory)."""

from probos.packs.manifest import (
    PackAuthor,
    PackManifest,
    PackParseError,
    PackSummary,
    describe_pack,
    find_manifest,
    load_manifest,
    parse_manifest,
)
from probos.packs.scanner import PackEntry, describe_scan, scan_packs

__all__ = [
    "PackAuthor",
    "PackManifest",
    "PackParseError",
    "PackSummary",
    "describe_pack",
    "find_manifest",
    "load_manifest",
    "parse_manifest",
    "PackEntry",
    "describe_scan",
    "scan_packs",
]
