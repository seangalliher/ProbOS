"""AD-1040/AD-1041/AD-1043: ARD (Agentic Resource Discovery) envelope package.

The sibling **type** modules (``catalog``, ``urn``, ``media_types``) remain
pure stdlib (AD-1040 purity invariant — zero ``probos`` imports). AD-1041/1043
add two BEHAVIOR modules — ``catalog_projector`` (projects the live capability
surface) and ``representative_queries`` (mines example NL queries) — which MAY
import ``probos``, but do so LAZILY (in-function), so importing this package
never triggers a router/runtime import at module-load time (no import cycle).
This ``__init__`` re-exports the public surface of all five modules.
"""

from .access import (
    ard_access_for_agent,
    ard_resource_tool_id,
    ard_tool_tool_id,
    resolve_ard_access,
)
from .catalog import (
    AiCatalog,
    Attestation,
    CatalogEntry,
    HostInfo,
    ProvenanceLink,
    TrustManifest,
)
from .catalog_parse import catalog_from_dict, entry_from_dict
from .catalog_projector import get_cached_catalog, project_catalog, reset_catalog_cache
from .client import ArdClient, DiscoveredCatalog
from .media_types import (
    MT_A2A_AGENT,
    MT_AI_CATALOG,
    MT_AI_REGISTRY,
    MT_AI_SKILL,
    MT_MCP_SERVER,
    MT_PROBOS_TOOL,
    PROBOS_AXIS_TO_MEDIA_TYPE,
)
from .registry_query import facet_entries, search_entries
from .representative_queries import mine_representative_queries
from .trust_verifier import VerificationReport, seed_trust_prior, verify_entry
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
    # AD-1041/1043 projection + mining
    "project_catalog",
    "mine_representative_queries",
    # AD-1044/1045 query engine + projection cache
    "get_cached_catalog",
    "reset_catalog_cache",
    "search_entries",
    "facet_entries",
    # AD-1046 consume side: catalog parse + discovery client
    "catalog_from_dict",
    "entry_from_dict",
    "ArdClient",
    "DiscoveredCatalog",
    # AD-1047 trust verification (verify-only)
    "verify_entry",
    "seed_trust_prior",
    "VerificationReport",
    # AD-1048 per-agent ARD access resolution (deny-default)
    "resolve_ard_access",
    "ard_access_for_agent",
    "ard_resource_tool_id",
    "ard_tool_tool_id",
]
