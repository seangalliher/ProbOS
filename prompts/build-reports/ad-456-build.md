# AD-456 Build Report

**Date:** 2026-05-01
**Builder:** Wave 7 continuous-build (2 of 5)

## Sections Implemented

| Section | File | Status |
|---|---|---|
| Section 0+4: EventTypes | `src/probos/events.py` | ✅ Added `SECRET_ROTATED`, `EGRESS_BLOCKED`, `AUDIT_RECORDED` after AD-466 events |
| Section 1: CredentialStore ctor extension | `src/probos/credential_store.py` | ✅ Added kw-only `store_path`/`emit_event` kwargs; added `json`/`pathlib.Path` imports |
| Section 2: CredentialStore methods + `_resolve` step | `src/probos/credential_store.py` | ✅ Added `_load_store`, `_resolve_from_store`, `rotate`, `_emit_rotated`; inserted JSON-store step in `_resolve` between env aliases and CLI |
| Section 3: EgressPolicy | `src/probos/security/egress.py` (new) | ✅ `deny_by_default=True`, allowlist `127.0.0.1`/`localhost`/`::1`, emits `EGRESS_BLOCKED` |
| Section 3 (audit): AuditLog | `src/probos/security/audit.py` (new) | ✅ SHA-256 hash chain + `verify_chain()` + emits `AUDIT_RECORDED` |
| Section 5: SecurityInfraConfig | `src/probos/config.py` | ✅ Added Pydantic class + field on `SystemConfig` |
| Section 6: finalize.py wiring | `src/probos/startup/finalize.py` | ✅ Reconfigure existing `runtime.credential_store`; wire `runtime.egress_policy` + `runtime.audit_log` (always-wired with `None` when disabled) |
| Tests | `tests/test_ad456_security_infrastructure.py` (new) | ✅ 16/16 pass at `-n 0` (15 in spec + 1 extra `allow_by_default` parity test) |
| Tracking | `PROGRESS.md`, `docs/development/roadmap.md:4142` | ✅ Updated |

## Test Results

- Focused gate: `pytest tests/test_ad456_security_infrastructure.py -v -n 0` → **16/16 passed in 0.26s**
- Full parallel gate: **10,420 passed (+16 vs AD-466 baseline 10,404), 14 skipped, 151 warnings in 341.57s**

## Notes / Decisions

- Wave 7 revision-section direction respected: NO new `SecretsManager` class, NO `runtime.secrets_manager` attribute. AD-456 EXTENDS existing `CredentialStore` (AD-395) with persistence + rotation.
- `EgressPolicy.deny_by_default=True` is the v1 default per Wave 7 cross-cutting fix #6 — produces real `EGRESS_BLOCKED` signal today (no theater).
- IPv6 `::1` included in default allowlist per Wave 7 review.
- `AuditLog` is in-memory only in v1; SQLite persistence deferred to AD-456d (no theater discipline).
- `RuntimeSandbox` (process isolation) wholesale-deferred to AD-456b — nothing shipped under that capability name.
- `agents/http_fetch.py` and `agents/red_team.py` unchanged — `EgressPolicy` is consultation-only in v1; consumer wiring deferred to AD-456b.
- Test file imports `AuditEntry_replace` helper to mutate frozen dataclass entries (mid-chain + genesis tamper tests). The 16th test (`test_egress_policy_allow_by_default_permits_unknown`) is an explicit parity check that `deny_by_default=False` mode allows unknown hosts and emits no events.

## Pre-Commit Sanity Check

8 files changed, ~470 insertions, 4 deletions (1 line trackers + 3 lines from CredentialStore class-docstring/`__init__`/`register` rewrap during section 1+2 edits). Max per-file deletion: 3 lines. Well under 200-line threshold.
