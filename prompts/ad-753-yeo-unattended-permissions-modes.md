# AD-753 - Unattended Permission Modes (`autoApproveReadOnly`, Permission Cards, Tenant Policy Hook)

Status: drafted (planning slate only)
Issue: #699
Parent: #486
Depends on: AD-749 (#695)

## Objective
Add explicit unattended-permission controls that preserve safety while enabling useful automation.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- `autoApproveReadOnly` mode with clear constraints.
- Permission cards for approval/reject/review.
- Tenant policy hook extension-point for custom policy engines.
- Manual/auto/autopilot mode taxonomy pattern (AionUi-inspired, pattern only).

## Out of Scope
- Unbounded YOLO bypass modes.
- Enterprise policy engine implementation details.

## File Targets
- `src/probos/security/`
- `src/probos/governance/`
- `src/probos/consensus/`
- `src/probos/config.py`
- `ui/src/components/wardroom/`

## Pre-Flight Anchors
- Verify current approvals/quorum paths in `src/probos/consensus/quorum.py` and escalation flow.
- Verify tool/permission infrastructure in `src/probos/tools/` and `src/probos/security/`.
- Verify DM approval surfaces in ward-room UI components.

## Acceptance Criteria
- Read-only auto-approve behavior is policy-constrained and observable.
- Permission cards include clear scope, expiry, and audit metadata.
- Destructive operations still require explicit guardrails.
- Captain invariant appears in acceptance checks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
