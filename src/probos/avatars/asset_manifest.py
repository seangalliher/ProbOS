"""AD-721i-1: avatar asset manifest parser + license whitelist.

The manifest at ``data/avatar-assets/MANIFEST.md`` is the audit ledger for
every asset bundled into the Blender renderer. License hygiene is strict:
CC0 / MIT / Apache-2.0 / BSD / CC-BY only. Anything else is rejected at the
validator boundary.

This module is read-only - parsing + filtering. The fetcher script
(``scripts/avatar-assets-fetch.ps1``) is the operator-side consumer.
"""

from __future__ import annotations

import logging
import re
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
