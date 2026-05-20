# AD-749 - Yeo M365 Auth + Core Connector Agents

Status: drafted (planning slate only)
Issue: #695
Parent: #486 (AD-710 umbrella)
Related: #480 (AD-704 channel adapters)

## Objective
Define OSS-ready foundation for Microsoft 365 assistant capabilities through connector boundaries that all crew agents can use.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- M365 auth boundary (device-code/OAuth lifecycle contracts).
- Connector agent interfaces for Outlook, Teams, Calendar, SharePoint, OneDrive.
- Adapter boundary pattern for channels/plugins (pattern absorption from AionUi only).
- Pairing/authorization entry controls for remote channel activation.

## Out of Scope
- Re-implementing Telegram/WhatsApp/Matrix/Teams adapters from #480.
- Enterprise-only tenant provisioning workflows (extension-point only).

## OSS vs Commercial Split

**OSS (Personal Desktop):**
- Single-user OAuth device-flow auth with local token caching.
- Connector agents for personal M365 account (Outlook, Teams, Calendar, SharePoint, OneDrive read).
- Local BYOL credential storage (operator brings own API keys).

**Commercial Extension Point:**
- Multi-tenant enterprise provisioning (SSO, SCIM, token broker).
- Tenant policy connectors and conditional-access compatibility.
- Compliance-scoped credential management (key vault integration).
- Audit logging for enterprise SOC teams.

## File Targets
- `src/probos/channels/`
- `src/probos/integrations/`
- `src/probos/config.py`
- `src/probos/runtime.py`
- `src/probos/routers/` (auth + management surfaces)

## Pre-Flight Anchors
- Verify current channel adapter baseline in `src/probos/channels/`.
- Verify auth and config extension points in `src/probos/config.py` and `src/probos/routers/auth.py`.
- Verify runtime wiring seam in `src/probos/runtime.py`.

## Acceptance Criteria
- Explicit connector contracts are bounded and testable.
- Auth/token lifecycle has honest-degrade behavior and no secrets in logs.
- Captain invariant text appears in final prompt acceptance checks.
- Issue references #486 and #480 and avoids duplicate implementation scope.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
