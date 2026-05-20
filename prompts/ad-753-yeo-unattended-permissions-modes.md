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

## OSS vs Commercial Split

**OSS (Personal Desktop):**
- `autoApproveReadOnly` mode for personal assistant on personal data.
- Manual approval cards in Ward Room for unattended decisions.
- Tenant policy hook as abstract interface (no impl).

**Commercial Extension Point:**
- Tenant policy engine with org rule sets and audit reporting.
- Advanced permission scopes (team data, sensitive projects, regulatory).
- Policy audit log for SOC/compliance teams.
- Escalation routing to org approvers for edge cases.

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
