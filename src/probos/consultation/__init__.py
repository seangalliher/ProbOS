"""AD-594a v1: Consultation workspace primitives.

Session-scoped shared workspace in Ship's Records for multi-agent advisory
consultations. See ``ConsultationWorkspace`` and ``WorkspaceRegistry``.

This module is the substrate; the consultation primitive (AD-594b) and parallel
execution dispatch (AD-594c) are tracked under separate GH issues (#161, #162)
and are NOT in v1 scope.
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

__all__ = [
    "AdapterResult",
    "ArtifactType",
    "ConsultationWorkspace",
    "ConsultationWorkspaceSummary",
    "DeliveryAdapter",
    "DeliveryArtifact",
    "DeliveryPipeline",
    "DeliveryReceipt",
    "DeliveryRequest",
    "FormatTransformer",
    "GitHubAdapter",
    "InputProcessor",
    "JSONToMarkdownTransformer",
    "LocalFileAdapter",
    "MarkdownToHTMLTransformer",
    "PassthroughTextProcessor",
    "PassthroughTransformer",
    "TEMPLATES",
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
