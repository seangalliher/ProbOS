"""AD-594a v1: Consultation workspace primitives.

Session-scoped shared workspace in Ship's Records for multi-agent advisory
consultations. See ``ConsultationWorkspace`` and ``WorkspaceRegistry``.

This module is the substrate; the consultation primitive (AD-594b), parallel
execution dispatch (AD-594c), and delivery pipeline (AD-594d) are tracked under
separate GH issues (#161, #162, #163) and are NOT in v1 scope.
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

__all__ = [
    "ArtifactType",
    "ConsultationWorkspace",
    "ConsultationWorkspaceSummary",
    "InputProcessor",
    "PassthroughTextProcessor",
    "TEMPLATES",
    "WorkspaceLifecycleState",
    "WorkspaceRef",
    "WorkspaceRegistry",
    "build_input_processor",
    "parse_workspace_refs",
    "render_advisory_report",
    "render_decision_record",
    "render_plan_document",
    "render_supporting_data",
    "render_work_item_spec",
    "render_workspace_refs_md",
]
