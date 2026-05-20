# AD-758 - Yeo Feature-Complete Integration Gate

Status: drafted (planning slate only)
Issue: #704
Parent: #486
Depends on: AD-749 through AD-757
Dedupe refs: #480, #484, #538

## Objective
Define completion rubric and integration gate for the Yeo OSS feature-complete program.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- Program-level checklist across AD-749..AD-757.
- Cross-crew capability exposure verification.
- Delegation-policy conformance verification.
- "For free" learning upgrades surfaced explicitly in each child AD acceptance criteria.
- No-duplicate gate against existing open issues and shipped waves.

## Out of Scope
- Production implementation work.
- DECISIONS.md architectural logging updates.

## OSS vs Commercial Split

**OSS (Personal Desktop) Completeness Gate:**
- All AD-749..AD-757 child prompts include OSS scopes fully realized.
- No production code depends on commercial-only extension points.
- Every personal-workflow scenario has a "works today" implementation.

**Commercial Extension Points Documented (Not Implemented):**
- Multi-tenant auth/provisioning.
- Org policy engine and compliance reporting.
- Fleet management and cross-device sync.
- DLP and advanced security controls.
- Team-level features and analytics.

## File Targets
- `prompts/ad-749-*.md` through `prompts/ad-757-*.md`
- `docs/development/roadmap.md`
- `PROGRESS.md`
- `prompts/wave-plan.yaml`

## Pre-Flight Anchors
- Verify umbrella and existing issue set in roadmap/open issues.
- Verify wave 175-180 shipped scope already covers voice/perception stacks.
- Verify dedupe references to #480, #484, #538 and #486.

## Acceptance Criteria
- Completion rubric is objective, testable, and ordered by dependency.
- Every child AD includes Captain invariant text.
- Program gate explicitly blocks duplicate scope against existing issues.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
