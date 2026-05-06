"""AD-482 v1: Self-Improvement Pipeline package.

Stage Contracts (482a), Capability Proposals + PIVOT/REFINE (482b + 482e),
Approval Gate (482c), Evolution Store (482d), QA Agent Pool + Shapley (482f),
Agent Versioning + LocalDiskPersistence + Shadow Deployment seam (482g + 482h + 482i).

Forcing-function follow-ons:
- AD-482h-1: Git PR creation layer (subprocess git + GitHub MCP wiring).
- AD-482i-1: Concrete `ShadowDeploymentPolicy` impl (parallel-pool comparator with
  scaler-aware shadow workers -- needs AD-280 territory).
"""

from probos.cognitive.self_improvement.approval_gate import ApprovalGate
from probos.cognitive.self_improvement.evolution_store import (
    EvolutionStore,
    Lesson,
)
from probos.cognitive.self_improvement.proposal import (
    CapabilityProposal,
    IterationGuard,
    PivotRefineDecision,
    ProposalState,
    ProposalStore,
)
from probos.cognitive.self_improvement.qa_pool import QAAgentPool, QAEvaluation
from probos.cognitive.self_improvement.stage_contract import StageContract
from probos.cognitive.self_improvement.versioning import (
    AgentPersistence,
    AgentVersion,
    AgentVersionStore,
    LocalDiskPersistence,
    NoOpShadowDeploymentPolicy,
    ShadowComparisonResult,
    ShadowDeploymentPolicy,
)

__all__ = [
    "AgentPersistence",
    "AgentVersion",
    "AgentVersionStore",
    "ApprovalGate",
    "CapabilityProposal",
    "EvolutionStore",
    "IterationGuard",
    "Lesson",
    "LocalDiskPersistence",
    "NoOpShadowDeploymentPolicy",
    "PivotRefineDecision",
    "ProposalState",
    "ProposalStore",
    "QAAgentPool",
    "QAEvaluation",
    "ShadowComparisonResult",
    "ShadowDeploymentPolicy",
    "StageContract",
]
