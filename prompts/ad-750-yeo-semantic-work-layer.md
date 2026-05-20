# AD-750 - WorkIQ-Style Semantic Work Layer

Status: drafted (planning slate only)
Issue: #696
Parent: #486
Depends on: AD-749 (#695)

## Objective
Create a shared semantic work layer so Yeo and all crew agents reason over commitments, context, and artifacts consistently.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- Semantic entity model for tasks, meetings, docs, threads, commitments.
- Query/retrieval APIs for delegation and daily planning flows.
- Session continuity model (AionUi session-manager pattern, architecture only).
- Mapping from existing task/journal data to new semantic layer.

## Out of Scope
- Commercial analytics/scoring/reporting overlays.
- Replacing episodic memory primitives wholesale.

## OSS vs Commercial Split

**OSS (Personal Desktop):**
- Semantic entity model for personal tasks, meetings, docs, commitments.
- Query/retrieval for personal daily planning and delegation.
- Session continuity for active assistant sessions.

**Commercial Extension Point:**
- Org-wide entity indexing and cross-user query surfaces.
- Team/org-level commitment tracking and project analytics.
- Compliance-grade retention and audit for work semantics.

## File Targets
- `src/probos/knowledge/`
- `src/probos/ontology/`
- `src/probos/cognitive/`
- `src/probos/routers/` (query APIs)
- `src/probos/types.py`

## Pre-Flight Anchors
- Verify existing semantic hooks in `src/probos/cognitive/oracle_service.py`.
- Verify ontology services in `src/probos/ontology/service.py`.
- Verify current records/query surfaces in `src/probos/routers/records.py` and `src/probos/knowledge/`.

## Acceptance Criteria
- New semantic contracts are additive and backward compatible.
- Delegation flows can consume semantic context without per-agent duplication.
- Includes migration and fallback behavior for pre-existing data.
- Captain invariant appears in acceptance checks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
