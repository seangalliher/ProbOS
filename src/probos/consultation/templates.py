"""AD-594a v1: Standardized artifact-type render helpers + consultation templates.

Five artifact types (``ArtifactType``) each have a pure render function returning
a markdown skeleton string. Three consultation templates (security_review,
technical_design, incident_response) are exposed via the ``TEMPLATES`` dict;
each renders an initial ``plan_v1.md`` skeleton when a workspace is created
with ``template=<name>``.
"""
from __future__ import annotations

from enum import Enum
from typing import Callable


class ArtifactType(str, Enum):
    """v1 standardized artifact types.

    Storage layout: each type lives under a dedicated workspace subdirectory
    (advisory/, plan/, workitems/, artifacts/, outputs/). The enum values are
    the canonical short names used in journal entries and (future) HXI
    rendering.
    """
    ADVISORY_REPORT = "advisory_report"
    PLAN_DOCUMENT = "plan_document"
    WORK_ITEM_SPEC = "work_item_spec"
    SUPPORTING_DATA = "supporting_data"
    DECISION_RECORD = "decision_record"


def render_advisory_report(*, agent_id: str, summary: str, body: str) -> str:
    """Render an ADVISORY_REPORT markdown skeleton."""
    return (
        f"# Advisory Report — {agent_id}\n\n"
        f"## Summary\n\n{summary.strip()}\n\n"
        f"## Detail\n\n{body.strip()}\n"
    )


def render_plan_document(*, title: str, sections: list[tuple[str, str]]) -> str:
    """Render a PLAN_DOCUMENT markdown skeleton from (heading, body) sections."""
    lines = [f"# Plan — {title}\n"]
    for heading, body in sections:
        lines.append(f"## {heading.strip()}\n\n{body.strip()}\n")
    return "\n".join(lines)


def render_work_item_spec(*, work_item_id: str, summary: str, body: str) -> str:
    """Render a WORK_ITEM_SPEC markdown preamble (the YAML payload is separate)."""
    return (
        f"# Work Item — {work_item_id}\n\n"
        f"**Summary:** {summary.strip()}\n\n"
        f"## Details\n\n{body.strip()}\n"
    )


def render_supporting_data(*, title: str, body: str) -> str:
    """Render a SUPPORTING_DATA markdown skeleton."""
    return f"# Supporting Data — {title}\n\n{body.strip()}\n"


def render_decision_record(*, decision: str, rationale: str, dissent: str = "") -> str:
    """Render a DECISION_RECORD markdown skeleton."""
    out = (
        f"# Decision Record\n\n"
        f"## Decision\n\n{decision.strip()}\n\n"
        f"## Rationale\n\n{rationale.strip()}\n"
    )
    if dissent.strip():
        out += f"\n## Dissent\n\n{dissent.strip()}\n"
    return out


def _security_review() -> str:
    return (
        "# Security Review — Consultation Plan\n\n"
        "## Threat Model\n\n_TBD by advisor_\n\n"
        "## Attack Surface\n\n_TBD by advisor_\n\n"
        "## Controls\n\n_TBD by advisor_\n\n"
        "## Open Questions\n\n_TBD by advisor_\n"
    )


def _technical_design() -> str:
    return (
        "# Technical Design — Consultation Plan\n\n"
        "## Problem Statement\n\n_TBD by advisor_\n\n"
        "## Proposed Architecture\n\n_TBD by advisor_\n\n"
        "## Trade-offs\n\n_TBD by advisor_\n\n"
        "## Validation Plan\n\n_TBD by advisor_\n"
    )


def _incident_response() -> str:
    return (
        "# Incident Response — Consultation Plan\n\n"
        "## Incident Summary\n\n_TBD by advisor_\n\n"
        "## Containment Steps\n\n_TBD by advisor_\n\n"
        "## Root Cause Analysis\n\n_TBD by advisor_\n\n"
        "## Remediation\n\n_TBD by advisor_\n"
    )


TEMPLATES: dict[str, Callable[[], str]] = {
    "security_review": _security_review,
    "technical_design": _technical_design,
    "incident_response": _incident_response,
}
