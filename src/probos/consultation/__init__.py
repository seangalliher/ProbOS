"""Consultation workspace primitives.

Session-scoped shared workspace in Ship's Records for multi-agent advisory
consultations.

* AD-594a (Wave 44): substrate — ``ConsultationWorkspace`` + ``WorkspaceRegistry``.
* AD-594d (Wave 79): delivery pipeline — ``DeliveryPipeline`` + adapters.
* AD-594c (Wave 80): parallel execution dispatch — ``ParallelDispatcher`` +
  ``MarkdownPlanDecomposer`` + ``ConflictDetector``.

The consultation primitive (AD-594b, GH #161) is tracked under a separate
issue and is NOT shipped here.
"""
from __future__ import annotations

from probos.consultation.inputs import (
    InputProcessor,
    PassthroughTextProcessor,
    build_input_processor,
)
from probos.consultation.refs import (
    WorkspaceRef,
    parse_workspace_refs,
    render_workspace_refs_md,
)
from probos.consultation.templates import (
    ArtifactType,
    TEMPLATES,
    render_advisory_report,
    render_decision_record,
    render_plan_document,
    render_supporting_data,
    render_work_item_spec,
)
from probos.consultation.workspace import (
    ConsultationWorkspace,
    ConsultationWorkspaceSummary,
    WorkspaceLifecycleState,
    WorkspaceRegistry,
)
from probos.consultation.delivery import (
    AdapterResult,
    DeliveryAdapter,
    DeliveryArtifact,
    DeliveryPipeline,
    DeliveryReceipt,
    DeliveryRequest,
    FormatTransformer,
    GitHubAdapter,
    JSONToMarkdownTransformer,
    LocalFileAdapter,
    MarkdownToHTMLTransformer,
    PassthroughTransformer,
    build_format_transformer,
)
from probos.consultation.dispatch import (
    BlockerReport,
    ConflictDetector,
    ConflictPair,
    DispatchReceipt,
    MarkdownPlanDecomposer,
    ParallelDispatcher,
    PlanDecomposer,
    ProgressSnapshot,
    WorkItemSpec,
)
from probos.consultation.llm_decomposer import LLMPlanDecomposer

__all__ = [
    "AdapterResult",
    "ArtifactType",
    "BlockerReport",
    "ConflictDetector",
    "ConflictPair",
    "ConsultationWorkspace",
    "ConsultationWorkspaceSummary",
    "DeliveryAdapter",
    "DeliveryArtifact",
    "DeliveryPipeline",
    "DeliveryReceipt",
    "DeliveryRequest",
    "DispatchReceipt",
    "FormatTransformer",
    "GitHubAdapter",
    "InputProcessor",
    "JSONToMarkdownTransformer",
    "LLMPlanDecomposer",
    "LocalFileAdapter",
    "MarkdownPlanDecomposer",
    "MarkdownToHTMLTransformer",
    "ParallelDispatcher",
    "PassthroughTextProcessor",
    "PassthroughTransformer",
    "PlanDecomposer",
    "ProgressSnapshot",
    "TEMPLATES",
    "WorkItemSpec",
    "WorkspaceLifecycleState",
    "WorkspaceRef",
    "WorkspaceRegistry",
    "build_format_transformer",
    "build_input_processor",
    "parse_workspace_refs",
    "render_advisory_report",
    "render_decision_record",
    "render_plan_document",
    "render_supporting_data",
    "render_work_item_spec",
    "render_workspace_refs_md",
]
