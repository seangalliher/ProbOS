"""AD-481c: ExtensionDiscovery — scan extensions/ subdirs, validate manifests."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from probos.extensions.protocol import (
    EXTENSION_API_VERSION,
    ExtensionManifest,
)

logger = logging.getLogger(__name__)


_SUBDIR_TO_TYPE: dict[str, str] = {
    "agents": "agent",
    "tools": "tool",
    "skills": "skill",
    "channels": "channel_adapter",
    "hooks": "event_hook",
}


class ExtensionDiscovery:
    """Filesystem scanner for extension manifests.

    Walks the configured extensions_dir and reads per-extension extension.yaml
    files. Validates against ExtensionManifest, then checks contract-version
    semver compatibility against EXTENSION_API_VERSION.
    """

    def __init__(self, extensions_dir: Path) -> None:
        self._root = Path(extensions_dir)

    def scan(self) -> list[ExtensionManifest]:
        """Walk the extensions/ tree, validate every extension.yaml found.

        Returns the list of valid, version-compatible manifests. Logs warnings
        for invalid or incompatible manifests but does not raise.
        """
        manifests: list[ExtensionManifest] = []
        if not self._root.exists():
            logger.debug("ExtensionDiscovery: extensions_dir %s does not exist", self._root)
            return manifests

        for subdir_name in _SUBDIR_TO_TYPE:
            subdir = self._root / subdir_name
            if not subdir.exists():
                continue
            for manifest_path in subdir.rglob("extension.yaml"):
                m = self._load_one(manifest_path)
                if m is not None:
                    manifests.append(m)
        return manifests

    def _load_one(self, manifest_path: Path) -> ExtensionManifest | None:
        try:
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as exc:
            logger.warning("ExtensionDiscovery: cannot read %s — %s", manifest_path, exc)
            return None

        if not isinstance(raw, dict):
            logger.warning(
                "ExtensionDiscovery: %s did not parse to a mapping; skipping", manifest_path,
            )
            return None

        try:
            manifest = ExtensionManifest(**raw)
        except ValidationError as exc:
            logger.warning(
                "ExtensionDiscovery: %s failed manifest validation — %s", manifest_path, exc,
            )
            return None

        if not self._is_compatible(manifest):
            logger.warning(
                "ExtensionDiscovery: %s declares required_api_version=%s; "
                "current EXTENSION_API_VERSION=%s (major mismatch); skipping",
                manifest_path, manifest.required_api_version, EXTENSION_API_VERSION,
            )
            return None

        return manifest

    @staticmethod
    def _is_compatible(manifest: ExtensionManifest) -> bool:
        """Check semver major-version compatibility.

        Manifests targeting major version N work on runtime major version N
        regardless of minor / patch. Major version mismatch → incompatible.
        """
        manifest_major = manifest.required_api_version.split(".")[0]
        runtime_major = EXTENSION_API_VERSION.split(".")[0]
        return manifest_major == runtime_major
