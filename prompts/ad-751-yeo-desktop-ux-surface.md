# AD-751 - Desktop UX Surface (Tray, Notifications, Hotkey, Mini-Mode, Autostart)

Status: drafted (planning slate only)
Issue: #697
Parent: #486
Related: #484

## Objective
Define the desktop interaction surface required for Yeo to operate as the primary assistant front door in OSS.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- Tray affordance and status indicator behavior.
- Global hotkey invocation and mini-mode launch.
- Actionable desktop notifications and autostart policy.
- Stream/merge UX convention for concise status updates.

## Out of Scope
- Replacing mobile/PADD delivery scope in #484.
- Enterprise endpoint-management packaging.

## File Targets
- `ui/src/components/`
- `ui/src/store/`
- `ui/src/App.tsx`
- `src/probos/routers/system.py`
- `src/probos/notifications.py`

## Pre-Flight Anchors
- Verify existing Ward Room surfaces in `ui/src/components/wardroom/`.
- Verify notification services in `src/probos/notifications.py` and API routes.
- Verify startup/runtime settings in `src/probos/config.py`.

## Acceptance Criteria
- Desktop surfaces remain optional and degrade gracefully by platform.
- Notification ergonomics include low-noise rules and user controls.
- Delegation visibility from Yeo to specialist agents is explicit.
- Captain invariant appears in acceptance checks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
