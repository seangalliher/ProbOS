"""AD-721i-1: avatar asset manifest parser + license whitelist.

The manifest at ``data/avatar-assets/MANIFEST.md`` is the audit ledger for
every asset bundled into the Blender renderer. License hygiene is strict:
CC0 / MIT / Apache-2.0 / BSD / CC-BY only. Anything else is rejected at the
validator boundary.

This module is read-only - parsing + filtering. The fetcher script
(``scripts/avatar-assets-fetch.ps1``) is the operator-side consumer.

AD-721e (Wave 168): adds ``AnimationManifest`` for skeletal animation clips
fetched via ``scripts/animations-fetch.ps1``. The same license whitelist
applies to clips; SHA-256 integrity-checked on registration.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)


# AD-721i-1: hard license whitelist. Anything not in this set is REJECTED.
_ALLOWED_LICENSES = frozenset({
    "CC0", "CC0-1.0",
    "MIT",
    "Apache-2.0", "Apache 2.0",
    "BSD", "BSD-2-Clause", "BSD-3-Clause",
    "CC-BY-4.0", "CC-BY",  # attribution required; operator MUST preserve it
})

_VALID_DISPOSITIONS = frozenset({"APPROVED", "RESEARCH", "REJECTED"})

# Section heading shape: ``## Base meshes (body_type)``, ``## Hair styles``.
_SECTION_TO_CATEGORY = {
    "base meshes": "base_mesh",
    "hair styles": "hair",
    "outfits": "outfit",
    "materials": "material",
    "materials / textures": "material",
}


class AssetManifestEntry(NamedTuple):
    """One row of the manifest."""
    category: str
    name: str
    source_url: str
    license: str
    version: str
    sha256: str
    attribution: str
    disposition: str


def validate_license(value: str) -> bool:
    """Return True iff the license string is on the AD-721i-1 whitelist."""
    if not isinstance(value, str):
        return False
    return value.strip() in _ALLOWED_LICENSES


class AssetManifest:
    """Parsed view over ``data/avatar-assets/MANIFEST.md``."""

    def __init__(self, entries: list[AssetManifestEntry]) -> None:
        self._entries = list(entries)

    @classmethod
    def load(cls, path: Path) -> "AssetManifest":
        """Parse the markdown manifest. NEVER raises on malformed rows;
        skips with a warning. Returns an empty manifest when the file is
        missing (honest-degrade)."""
        if not path.is_file():
            logger.warning("AD-721i-1: manifest not found at %s", path)
            return cls([])
        text = path.read_text(encoding="utf-8")
        entries: list[AssetManifestEntry] = []
        current_category: str | None = None
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            # Section header: ``## Base meshes (body_type)``.
            if line.startswith("## "):
                heading = line[3:].lower()
                # Strip parenthetical suffix.
                heading = re.sub(r"\s*\(.*\)\s*$", "", heading).strip()
                current_category = _SECTION_TO_CATEGORY.get(heading)
                continue
            # Table row: ``| name | url | license | ... |``.
            if not line.startswith("|") or current_category is None:
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) != 7:
                continue
            # Skip the header / separator rows.
            if cells[0].lower() in ("name", "------") or cells[0].startswith("---"):
                continue
            disposition = cells[6]
            if disposition not in _VALID_DISPOSITIONS:
                logger.warning(
                    "AD-721i-1: skipping row with invalid disposition %r",
                    disposition,
                )
                continue
            entries.append(
                AssetManifestEntry(
                    category=current_category,
                    name=cells[0],
                    source_url=cells[1],
                    license=cells[2],
                    version=cells[3],
                    sha256=cells[4],
                    attribution=cells[5],
                    disposition=disposition,
                )
            )
        return cls(entries)

    @property
    def entries(self) -> list[AssetManifestEntry]:
        return list(self._entries)

    def approved(self, category: str | None = None) -> list[AssetManifestEntry]:
        """Return APPROVED rows, optionally filtered to a single category."""
        out = [e for e in self._entries if e.disposition == "APPROVED"]
        if category is not None:
            out = [e for e in out if e.category == category]
        return out

    def by_disposition(self, disposition: str) -> list[AssetManifestEntry]:
        if disposition not in _VALID_DISPOSITIONS:
            return []
        return [e for e in self._entries if e.disposition == disposition]


# ==============================================================================
# AD-721e (Wave 168): Skeletal animation clip manifest.
# ==============================================================================


@dataclass(frozen=True)
class AnimationClipEntry:
    """One registered skeletal animation clip.

    ``file_path`` is the operator-local path under ``animations_dir`` (gitignored).
    ``sha256`` is integrity-verified on registration when the file exists.
    ``license`` is enforced against the AD-721i-1 whitelist.
    """
    name: str
    file_path: Path
    sha256: str
    license: str
    source_url: str
    duration_s: float


class AnimationManifest:
    """AD-721e: registry of skeletal animation clips available to CrewVRM.

    Operator-managed via ``scripts/animations-fetch.ps1``. Manifest entries
    are integrity-checked on registration (SHA-256 match when the file is
    present). License field is enforced against the AD-721i-1 whitelist.
    """

    def __init__(self) -> None:
        self._entries: dict[str, AnimationClipEntry] = {}

    def register(self, entry: AnimationClipEntry) -> None:
        """Register one clip. Raises ``ValueError`` on license/integrity
        violations; logs at warning and skips on missing files (honest-degrade
        when the operator has not yet fetched the asset)."""
        if not validate_license(entry.license):
            raise ValueError(
                f"AD-721i-1: animation clip {entry.name!r} license "
                f"{entry.license!r} is not on the whitelist"
            )
        # Integrity check only when the file exists -- a missing file is a
        # legitimate honest-degrade state (operator hasn't run the fetch
        # script). Tampered bytes when present are a hard reject.
        if entry.file_path.is_file():
            actual = self._sha256_of(entry.file_path)
            if actual.lower() != entry.sha256.lower():
                raise ValueError(
                    f"AD-721e: animation clip {entry.name!r} SHA-256 mismatch "
                    f"at {entry.file_path} (expected {entry.sha256[:8]}..., "
                    f"got {actual[:8]}...)"
                )
        else:
            logger.warning(
                "AD-721e: animation clip %r registered but file missing at %s "
                "(operator-fetched? procedural fallback will be used)",
                entry.name, entry.file_path,
            )
        self._entries[entry.name] = entry

    def get(self, name: str) -> AnimationClipEntry | None:
        """Return the registered entry by name, or None when unknown."""
        return self._entries.get(name)

    def list_available(self) -> list[str]:
        """Return the sorted list of registered clip names whose files exist
        on disk. Excludes entries whose underlying file is missing -- those
        cannot be served and should not surface to clients."""
        return sorted(
            name for name, e in self._entries.items() if e.file_path.is_file()
        )

    @staticmethod
    def _sha256_of(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(64 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
