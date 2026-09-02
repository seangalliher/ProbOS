"""AD-1270a: capability declarations owned by the tool layer.

Data only — no import of the subsystems declared here. See the cognitive-layer
declaration module for the reasoning.
"""

from __future__ import annotations

from probos.maturity.model import ALWAYS_CONFIGURED, CapabilityDeclaration

MATURITY_DECLARATIONS: tuple[CapabilityDeclaration, ...] = (
    CapabilityDeclaration(
        id="tools.code-execution",
        title="Governed code execution",
        owner_module="probos.tools.code_execution_tool",
        owner_symbol="CodeExecutionTool",
        configured_when=ALWAYS_CONFIGURED,
        catalog_axis="tools",
        catalog_id="run_python",
        notes=(
            "Catalog-bound: the advertised axis resolves this against the live "
            "capability catalog rather than against its own declaration."
        ),
    ),
    CapabilityDeclaration(
        id="tools.governed-invocation",
        title="Governed tool invocation",
        owner_module="probos.tools.registry",
        owner_symbol="ToolRegistry",
        configured_when=ALWAYS_CONFIGURED,
        seam_ids=("TA-P0-002-tool-fault-repair",),
        notes=(
            "The ship-wide tool asset catalog and the permission surface every "
            "governed invocation passes through."
        ),
    ),
)
