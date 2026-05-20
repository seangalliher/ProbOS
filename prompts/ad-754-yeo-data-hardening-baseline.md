# AD-754 - Yeo Data Hardening Baseline

Status: drafted (planning slate only)
Issue: #700
Parent: #486
Depends on: AD-749 (#695)

## Objective
Define OSS personal-assistant hardening baseline for data safety and user trust.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- Encryption-at-rest boundary for sensitive assistant/session material.
- PII redaction rules for logs, traces, and memory artifacts.
- Assistant audit log records for delegated actions.
- "Forget this" deletion path for user-requested erasure.
- Credential-encryption utility pattern (AionUi-inspired pattern only).

## Out of Scope
- Commercial DLP/compliance SKU features.
- New external paid encryption services.

## OSS vs Commercial Split

**OSS (Personal Desktop):**
- Encryption at rest for local tokens and session material (system keyring or DPAPI/Keychain).
- PII redaction in diagnostic logs (email/phone/doc-URL masking).
- Assistant audit log for personal traceability.
- "Forget this" deletion path for explicit erasure.

**Commercial Extension Point:**
- DLP policy engine (sensitivity-label aware, pattern-based).
- Key management services (BYOK, HSM, Azure Key Vault).
- Retention policies and legal hold for org compliance.
- Encrypted transport and TLS pinning for regulated environments.

## File Targets
- `src/probos/security/`
- `src/probos/attachments/`
- `src/probos/knowledge/`
- `src/probos/routers/`
- `src/probos/config.py`

## Pre-Flight Anchors
- Verify existing audit infrastructure in `src/probos/security/audit.py`.
- Verify attachment and retention flows in `src/probos/attachments/`.
- Verify memory/record deletion seams in `src/probos/knowledge/` and routers.

## Acceptance Criteria
- Data-classification and redaction policies are explicit and test-covered.
- Erasure workflow has auditable completion states.
- Secrets/tokens are never logged in plaintext.
- Captain invariant appears in acceptance checks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
