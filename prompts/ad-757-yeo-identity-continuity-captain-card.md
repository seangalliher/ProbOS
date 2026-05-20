# AD-757 - Identity and Continuity (Captain Card + Voice/Avatar Profile Continuity)

Status: drafted (planning slate only)
Issue: #703
Parent: #486
Depends on: AD-756 (#702)

## Objective
Ensure Yeo continuity across restart and context transitions, grounded in Captain Card and persisted profile state.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- Captain Card context bootstrap for Yeo front-door behavior.
- Session continuity contract for active delegated tasks.
- Voice/avatar/profile continuity linkage for Yeo identity over restart.

## Out of Scope
- New 3D avatar rendering architectures.
- Non-OSS identity provider productization.

## File Targets
- `src/probos/captain_card/`
- `src/probos/identity.py`
- `src/probos/crew_profile.py`
- `src/probos/service_profile.py`
- `ui/src/components/`

## Pre-Flight Anchors
- Verify captain-card API in `src/probos/captain_card/card.py`.
- Verify identity and onboarding continuity paths in `src/probos/agent_onboarding.py` and `src/probos/identity.py`.
- Verify voice/profile APIs in `src/probos/api_models.py` and related routers.

## Acceptance Criteria
- Yeo continuity survives restart without identity drift.
- Delegated-task continuity is recoverable and auditable.
- Voice/avatar continuity hooks are additive and optional.
- Captain invariant appears in acceptance checks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
