"""AD-1270a: capability declarations owned by the cognitive layer.

Data only. This module deliberately does **not** import the subsystems it
declares — a declaration is data *about* an owner, not a use of one, and keeping
it import-free is what makes reading the inventory cheap and side-effect-free.
A test AST-scans this file to enforce it.
"""

from __future__ import annotations

from probos.maturity.model import ALWAYS_CONFIGURED, CapabilityDeclaration

MATURITY_DECLARATIONS: tuple[CapabilityDeclaration, ...] = (
    CapabilityDeclaration(
        id="cognitive.intent-decomposition",
        title="Intent decomposition",
        owner_module="probos.cognitive.decomposer",
        owner_symbol="IntentDecomposer",
        configured_when=ALWAYS_CONFIGURED,
        seam_ids=("TA-P0-001-turn-act-evidence",),
        notes=(
            "Turns natural language into a TaskDAG of typed intents. On the "
            "request path for every cognitive turn."
        ),
    ),
    CapabilityDeclaration(
        id="cognitive.episodic-memory",
        title="Episodic memory",
        owner_module="probos.cognitive.episodic",
        owner_symbol="EpisodicMemory",
        configured_when=ALWAYS_CONFIGURED,
        notes=(
            "Semantic recall over past executions. An execution path that "
            "stores no episode breaks the learning loop silently."
        ),
    ),
    CapabilityDeclaration(
        id="cognitive.self-modification",
        title="Self-modification pipeline",
        owner_module="probos.cognitive.self_mod",
        owner_symbol="SelfModificationPipeline",
        configured_when="self_mod.enabled",
        notes=(
            "Capability-gap driven agent and skill design. Ships default-OFF, "
            "so a shipped-but-disabled row here is correct rather than a defect."
        ),
    ),
    CapabilityDeclaration(
        id="cognitive.crew-session",
        title="Crew session orchestration",
        owner_module="probos.cognitive.crew_orchestrator",
        owner_symbol="CrewOrchestrator",
        configured_when="workforce.enabled",
        seam_ids=("TA-P0-007-crew-outcome-trust",),
        notes=(
            "Owns durable workflow time for crew work: admission bounds, "
            "compare-and-set transitions, crash recovery, cancellation."
        ),
    ),
)
