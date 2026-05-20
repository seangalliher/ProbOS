# AD-755 - Office Document Skills + SharePoint Routing + Templates

Status: drafted (planning slate only)
Issue: #701
Parent: #486
Depends on: AD-749 (#695)
Related: #480

## Objective
Define office-document capability completeness for Yeo and all crew agents.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- Skill contracts for office document summarize/create/revise workflows.
- SharePoint-aware routing and source provenance tagging.
- Reusable template registry for recurring office tasks.

## Out of Scope
- Vendor-specific premium document processing services.
- Re-implementing generic channel adapter backlog in #480.

## File Targets
- `src/probos/skill_framework.py`
- `src/probos/agents/`
- `src/probos/integrations/`
- `src/probos/routers/`
- `src/probos/ward_room/`

## Pre-Flight Anchors
- Verify existing skill agent interfaces in `src/probos/skill_framework.py`.
- Verify integration seams in `src/probos/integrations/` and channel adapters.
- Verify delivery/reporting paths in ward-room services.

## Acceptance Criteria
- Document skills are typed, bounded, and source-aware.
- SharePoint routing honors auth and permission constraints.
- Template behaviors are deterministic and testable.
- Captain invariant appears in acceptance checks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
