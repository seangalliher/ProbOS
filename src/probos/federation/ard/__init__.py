"""AD-1040: ARD (Agentic Resource Discovery) envelope package.

DD-8 layer discipline: this package imports NOTHING from the rest of
``probos``. The sibling modules (``catalog``, ``urn``, ``media_types``) are
pure stdlib; this ``__init__`` only re-exports from those siblings. That
non-import is the byte-identical proof that AD-1040 ships types + taxonomy
only — nothing in the runtime imports this package yet.
"""

from .catalog import (
    AiCatalog,
    Attestation,
    CatalogEntry,
    HostInfo,
    ProvenanceLink,
    TrustManifest,
)
from .media_types import (
    MT_A2A_AGENT,
    MT_AI_CATALOG,
    MT_AI_REGISTRY,
    MT_AI_SKILL,
    MT_MCP_SERVER,
    MT_PROBOS_TOOL,
    PROBOS_AXIS_TO_MEDIA_TYPE,
)
from .urn import build_urn, parse_urn, publisher_domain

__all__ = [
    # catalog envelope
    "AiCatalog",
    "Attestation",
    "CatalogEntry",
    "HostInfo",
    "ProvenanceLink",
    "TrustManifest",
    # media-type taxonomy
    "MT_PROBOS_TOOL",
    "MT_MCP_SERVER",
    "MT_AI_SKILL",
    "MT_A2A_AGENT",
    "MT_AI_CATALOG",
    "MT_AI_REGISTRY",
    "PROBOS_AXIS_TO_MEDIA_TYPE",
    # urn helpers
    "build_urn",
    "parse_urn",
    "publisher_domain",
]
