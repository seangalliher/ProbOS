"""AD-1270a: capability declarations owned by the agent layer.

Data only — no import of the subsystems declared here. See the cognitive-layer
declaration module for the reasoning.
"""

from __future__ import annotations

from probos.maturity.model import ALWAYS_CONFIGURED, CapabilityDeclaration

MATURITY_DECLARATIONS: tuple[CapabilityDeclaration, ...] = (
    CapabilityDeclaration(
        id="agents.http-fetch",
        title="Mesh HTTP fetch",
        owner_module="probos.agents.http_fetch",
        owner_symbol="HttpFetchAgent",
        configured_when=ALWAYS_CONFIGURED,
        catalog_axis="mesh_intents",
        catalog_id="http_fetch",
        notes=(
            "Catalog-bound on the mesh-intent axis. Designed agents route HTTP "
            "through this intent so governance and per-domain rate limiting "
            "apply; a row advertised nowhere means that route is unreachable."
        ),
    ),
)
