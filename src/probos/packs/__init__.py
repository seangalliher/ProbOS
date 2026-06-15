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
from probos.packs.scanner import (
    PackComponent,
    PackContents,
    PackEntry,
    describe_pack_contents,
    describe_scan,
    preview_pack,
    scan_packs,
)

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
    "PackComponent",
    "PackContents",
    "describe_scan",
    "describe_pack_contents",
    "preview_pack",
    "scan_packs",
]
