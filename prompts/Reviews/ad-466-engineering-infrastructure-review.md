# Review: AD-466 — Engineering Infrastructure (Backup + StorageBackend ABC)

**Reviewer:** Architect (verify-first review of own draft)
**Date:** 2026-05-01
**Verdict:** ✅ **Approved** — narrow v1 scope (3 of 5 capabilities deferred); cleanly extends existing storage primitives without modifying them; ASCII-only comments; anchor-chain fallback complete. One Nit on line-number drift in the footer.

Smallest, lowest-risk Wave 7 prompt. Dispatch's pre-flagged drafting decision (CI/CD descope) is sound — `.github/workflows/{ci.yml, docs.yml}` exist and AD-466 explicitly does NOT touch them.

---

## Required (must fix before building)

None.

---

## Recommended

### 1. Footer line drift on `runtime.emit_event`

The footer claims `runtime.emit_event` is at `runtime.py:775`. Verified — actual line is 785:

```
grep -n "def emit_event" src/probos/runtime.py
  785: def emit_event(self, event: BaseEvent | str | EventType, ...
```

Off by 10 lines. Per review-criteria #6 line numbers are "approximate"; not a Required finding but the Builder may grep and find drift confusing. Update the footer.

### 2. `BackupService` doesn't read `backup_root.exists()` before `mkdir(parents=True, exist_ok=True)` in finalize

Section 6 finalize wiring:

```python
backup_root = runtime.data_dir / config.infrastructure.backup_subdir
backup_root.mkdir(parents=True, exist_ok=True)
```

If `runtime.data_dir` is a symlink or read-only mount, `mkdir` raises `OSError`. The wiring block should wrap the mkdir in try/except and fall back to setting `runtime.backup_service = None` with a `logger.warning` per the three-tier exception handling rule. Otherwise startup fails on any data-dir permission issue.

### 3. `BackupService._fail` returns a `BackupResult` that the caller may discard

`snapshot()`'s outer try wraps the inner loop. If `mkdir` fails at line 87-88 (`return self._fail(...)`), the result is returned with `succeeded=False` — that's fine. But if the `_backup_one` loop fails partway through (e.g., a single `.db` file is locked), `files_copied` records partial progress and the surrounding `except Exception` returns a fresh `BackupResult` that loses the partial-progress info.

Recommend: track partial progress in a result-builder pattern. Not blocking for v1; documenting for AD-466b polish.

### 4. `SQLiteStorageBackend.connection_factory()` returns a singleton — ensure tests don't share state

The default `SQLiteConnectionFactory()` instance from `storage/sqlite_factory.py:28` is a module-level singleton (`default_factory = SQLiteConnectionFactory()`). Multiple `SQLiteStorageBackend()` instances all return the same factory.

This is fine for production (one runtime, one factory), but tests that exercise connection lifecycle should be aware that the factory is shared. Document in `test_storage_backend_sqlite_returns_factory` test description.

---

## Nits

### 1. `BackupResult.bytes_copied` initialization

```python
bytes_copied: int = 0
```

The dataclass is frozen. The runtime code does `bytes_copied += dest.stat().st_size` then constructs the result — that works because the variable is local, not the dataclass field. Just confirming the pattern.

### 2. Section 1 `__init__.py` re-exports `BackupResult`

The `__init__.py` re-exports `BackupResult` but the only real consumers (`finalize.py`, tests) construct it indirectly via `BackupService.snapshot()`. The re-export is fine; flagging that it's there mostly for type-annotation consumers.

### 3. Section 2 docstring mentions Vopson; AD-466 isn't related to AD-491

Cross-prompt cosmetic — the prompt body is clean.

### 4. `BackupService._fail` doesn't call `_emit_failed` if `_emit_event is None`

Verified — the guard `if not self._emit_event: return` short-circuits cleanly. ✅

---

## Verified

### Public-attribute wiring (Wave-5 convention #1) — ✅ Applied

`runtime.storage_backend = SQLiteStorageBackend()` and `runtime.backup_service = BackupService(...)` — both public.

### stdlib-only persistence (Wave-5 convention #2) — ✅ Applied

`sqlite3.Connection.backup` (stdlib), `shutil.copyfile` (stdlib), `pathlib.Path` (stdlib). No new pyproject deps.

### Coordinator-then-dispatch (Wave-5 convention #3) — ✅ Applied

v1 `BackupService.snapshot()` is caller-driven (operator schedules calls). Background scheduler is deferred. `StorageBackend` ABC is the seam; PostgreSQL implementation deferred to AD-466b.

### Superset-filter discipline (Wave-5 convention #4) — ✅ Applied

`BackupService` doesn't intercept any existing flow. `StorageBackend` ABC ships alongside (not replacing) `ConnectionFactory` Protocol; existing modules continue unchanged.

### `init_<phase>` startup signatures (Wave-5 convention #5) — ✅ Applied

Section 6 places wiring in `startup/finalize.py` which receives `runtime` directly.

### Verify-first for anchors (Wave-5 convention #6) — ✅ Applied (line drift Nit only)

Every concrete claim has grep evidence in the footer. One Nit on line-number drift; the symbols are correct.

### No-theater discipline (Wave-5 convention #7) — ✅ Applied

v1 ships 2 real-work primitives:
- `BackupService` snapshots actual SQLite files via `sqlite3.Connection.backup` — real work.
- `StorageBackend` ABC + `SQLiteStorageBackend` is a typed seam, but it produces a real `ConnectionFactory` consumers can use today.

3 of 5 capabilities deferred wholesale (CI/CD, observability, runbook) — no v1 stubs for these. ✅

### TYPE_CHECKING cross-layer imports (Wave-6 note) — ✅ Applied

Section 3 `storage_backend.py` uses `TYPE_CHECKING` guard for `ConnectionFactory` and `DatabaseConnection` imports from `protocols.py`. ✅

### ASCII-only source comments (Wave-6 note) — ✅ Applied

Verified — no `←`, `→`, em-dash characters in any source-file comments. Uses `--`, `<-`, `->`. ✅

### Anchor-chain fallback (Wave-6 note) — ✅ Applied

Section 5 anchor chain terminates at `orders: OrdersConfig = OrdersConfig()  # AD-440` (config.py:1593).

### Section 0 EventTypes — ✅ Clean

`BACKUP_COMPLETE`, `BACKUP_FAILED` — verified absent in `events.py`. No collision with other Wave 7 prompts.

### Directory ownership — ✅ Documented

AD-466 explicitly owns `src/probos/infrastructure/__init__.py` creation. Mirrors AD-455 (security/), AD-457 (agents/engineering/), AD-459 (degradation/).

### CI/CD descope — ✅ Sound

`.github/workflows/` contents verified: `ci.yml` (python-tests + ui-tests jobs) and `docs.yml`. AD-466 explicitly does NOT modify these. Documented in "What This Does NOT Change."

### Distinct from `substrate/telemetry.py` `TelemetryService` — ✅ Verified at line 71

```
grep -n "class TelemetryService" src/probos/substrate/telemetry.py
  71: class TelemetryService:
```

AD-466 does NOT modify this. Observability deliverable deferred to AD-466c. ✅

### v1 viability — ✅ Substantive

`BackupService` solves a real problem (no current snapshot mechanism for SQLite databases under `data_dir`). `StorageBackend` ABC prepares the PostgreSQL seam without committing to it.

The dispatch's high-priority verification check ("v1 actually justifies a separate AD vs being absorbed into infrastructure-as-it-exists") — verified. No existing infrastructure module covers backup or storage abstraction.

### Test plan — ✅ Comprehensive

12 tests cover happy path + error cases (empty data_dir, unwritable backup_root, corrupted source DB) + boundary cases (online-backup vs file-copy fallback). ✅

---

## Verdict Summary

**No blocking issues.**

**4 Recommended findings:** all polish / robustness improvements. None block Builder execution.

**4 Nits:** cosmetic.

**Wave-5/6 conventions:** all 7 + 3 applied. ✅

**Build-readiness:** ~5 minutes architect time for footer line-drift cleanup; otherwise ready to ship.

**Recommended build order:** AD-466 first in Wave 7 (smallest blast radius, owns directory creation, no cross-AD dependencies).

---

## Second-Pass Review (2026-05-01)

**Verdict:** ✅ **Approved** — all Recommended polish applied; no Required findings to begin with; no new issues introduced.

### Resolution Audit

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| (none) | N/A | Pass-1 verdict was ✅ Approved |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| rec#1: footer line drift | ✅ Applied | Footer line corrected: `runtime.emit_event` 775 → 785 (verified at `runtime.py:785`). |
| rec#2: backup_root mkdir defensive guard | ✅ Applied | Revision Section 6 update wraps `backup_root.mkdir(...)` in `try/except OSError` with `runtime.backup_service = None` fallback and `logger.warning`. Three-tier exception handling (tier-2 log-and-degrade) correctly applied. |
| rec#3: BackupService partial-progress | 📦 Deferred | Documented; AD-466b polish. Acceptable. |
| rec#4: SQLiteStorageBackend singleton test note | 📦 Deferred | Documentation polish; Builder will document at write-time. |

| Pass-1 Nits | Status | Notes |
|---|---|---|
| nit#1, #2, #3, #4 | ✅ N/A or applied | Cosmetic; no edits needed. |

### New Findings (introduced during revision)

None.

### Verified Against Revised Codebase Claims

- `runtime.emit_event` at `runtime.py:785` — confirmed.
- Three-tier exception handling (tier-2 log-and-degrade for non-critical backup failure) consistent with copilot-instructions.md.
- `runtime.data_dir` public property at `runtime.py:934` (verified).

### Verdict

**✅ Approved.** No further architect rework required. Build-ready as AD-466 first in Wave 7.

---

## Second-Pass Review (2026-05-01)
