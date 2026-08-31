"""AD-481: Extension substrate — Sealed Core, Open Extensions.

AD-1215 (#1172) retired ``ExtensionRegistry`` as a model. It was never assigned
on any runtime — ``registry.py``, ``discovery.py`` and ``state_store.py`` were
constructed only by tests — so ProbOS was carrying two overlapping extension
models. The one that is wired stays; the one that only existed in test setups is
gone. Third-party capability arrives as a Pack, in-process runtime extension
through the ``overlay`` entry point, and out-of-process capability over MCP.

The modules that remain:

- overlay.py       — the AD-697/698 entry-point seam: extension discovery,
                     finalize hooks and the pre-intent authorization hook
                     registry. Load-bearing; imported by ``mesh.pre_intent_auth``
                     on a fail-closed path.
- protocol.py      — EXTENSION_API_VERSION, the one surviving contract constant
- skill_manifest.py — SkillManifest Pydantic + load_skill_from_manifest adapter
                     to the existing SkillDefinition
- sealed_core.py   — is_sealed_path helper + load_sealed_globs
- profiles.py      — ExtensionProfile Pydantic + apply_profile (preset loader).
                     Not re-exported here: ``apply_profile`` has no production
                     caller after AD-1215, and an exported dead surface invites
                     new coupling back to the model this AD removed. Import it
                     from ``probos.extensions.profiles`` if a caller ever lands.

Per docs/development/roadmap.md:3478 + :3595, commercial features (Agent
Marketplace, centralized extension distribution / CDN, hosted extension trust
scoring + revocation registry, paid catalog + billing surface) are tracked in
the private commercial-repo path token. This package is fully OSS substrate.
"""

from probos.extensions.protocol import EXTENSION_API_VERSION
from probos.extensions.skill_manifest import SkillManifest, load_skill_from_manifest
from probos.extensions.sealed_core import is_sealed_path, load_sealed_globs
from probos.extensions.profiles import ExtensionProfile

__all__ = [
    "EXTENSION_API_VERSION",
    "ExtensionProfile",
    "SkillManifest",
    "is_sealed_path",
    "load_sealed_globs",
    "load_skill_from_manifest",
]
