"""AD-481a: Extension protocol substrate.

AD-1215 (#1172) reduced this module to the one symbol with a live consumer.
``ExtensionRegistry`` and its vocabulary — ``Extension``, ``ExtensionManifest``,
``ExtensionType``, ``ExtensionRiskLevel``, ``ExtensionState``, and a duplicate
``ExtensionsConfig`` — were removed together with the registry itself: nothing
in ``src/`` ever assigned ``runtime.extension_registry``, so that model existed
only in test setups while Packs, the ``overlay`` entry point and MCP carried the
real admission paths. The live config block is ``probos.config.ExtensionsConfig``.
"""

from __future__ import annotations


EXTENSION_API_VERSION: str = "1.0.0"
"""Semantic version of the extension contract surface.

Read only by ``skill_manifest.SkillManifest.required_api_version`` as its default.
"""

__all__ = ["EXTENSION_API_VERSION"]
