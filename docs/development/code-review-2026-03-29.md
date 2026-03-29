# ProbOS Comprehensive Code Review — 2026-03-29

**Scope:** Full codebase audit across 5 dimensions: code quality, architecture, test coverage, security, and missed considerations.

**Codebase:** 126 Python source files, 173 test files (3,899 tests), 55 TSX/TS frontend files (10 test files, ~149 tests).

---

## Executive Summary

The codebase is functionally strong with excellent test coverage in core systems (trust, Ward Room, workforce, dreaming, self-mod). The main structural risk is the **God Object pattern** in `runtime.py` (5,306 lines) and `api.py` (3,094 lines), which concentrates all responsibilities and creates fragile initialization ordering. Security is appropriate for a local-first application (no auth needed for localhost), but path traversal in Ship's Records and unbounded database growth are real operational risks. The project has remarkably few TODOs (just 1) and no stub implementations, indicating disciplined delivery.

### Severity Distribution

| Severity | Count | Summary |
|----------|-------|---------|
| **Critical** | 4 | God Object, swallowed exceptions, events.db unbounded growth, no API auth (see note) |
| **High** | 8 | 980-line start(), 95 Any types, private member access, path traversal, os._exit, shell=True, sandbox exec, duplicate code |
| **Medium** | 12 | Missing DB indexes, hasattr patterns, config drift, race conditions, encoding issues, deprecated async, schema migration pattern |
| **Low** | 10 | SIF placeholders, fire-and-forget tasks, abbreviation clarity, config version stale, lru_cache invalidation |

> **Note on API auth:** ProbOS is a local-first application running on localhost. The lack of API authentication is a known design choice, not an oversight. This becomes a real issue only when network-exposed (federation, remote HXI). Listed as Critical for awareness, not immediate action.

---

## 1. Architecture

### 1.1 God Object: `ProbOSRuntime` — CRITICAL

`runtime.py` is 5,306 lines with 60+ methods and 50+ instance attributes. The `start()` method alone is **980 lines** (lines 799-1779) performing 36 sequential initialization steps. The `__init__` spans 285 lines.

**Impact:** Impossible to test in isolation, fragile initialization ordering, every change risks side effects.

**Recommendation:** Extract a `ServiceRegistry` or builder pattern. Group the 36 init steps into focused initializer classes (InfrastructureInitializer, CognitiveInitializer, CommunicationsInitializer, etc.).

### 1.2 God Function: `api.py:create_app()` — HIGH

3,094 lines inside a single closure containing ~80+ REST endpoints. Business logic for self-modification (200+ lines), build execution, and knowledge store writes lives in the API layer instead of services.

**Recommendation:** Extract endpoint groups into FastAPI routers (`APIRouter`). Move business logic to service methods on the runtime.

### 1.3 Private Member Access Across Boundaries — HIGH

15+ instances of `obj._private_attr = value` post-construction:

| Location | Pattern |
|----------|---------|
| `runtime.py:1792` | `self.ward_room._db` — raw SQL against Ward Room's private DB |
| `runtime.py:1212` | `self.self_mod_pipeline._validator`, `._sandbox` |
| `runtime.py:1077` | `self.escalation_manager._surge_fn` |
| `runtime.py:1116` | `self.intent_bus._federation_fn` |
| `runtime.py:1371-1373` | `self.dream_scheduler._post_dream_fn` (3 patches) |
| `runtime.py:1689` | `self.ward_room._ontology` |
| `assignment.py:378,416` | `self._ward_room._db.execute(...)` — direct DB manipulation |
| `sif.py:191,241` | `._weights`, `._subscribers` |

**Root cause:** Services are constructed before their dependencies exist, then patched afterward. A dependency injection or builder pattern would eliminate this.

### 1.4 Layer Violations

| Violation | Assessment |
|-----------|-----------|
| `cognitive/` imports from `consensus/` and `mesh/` | Documented as "AD-399 allowed edges" but real coupling |
| `experience/shell.py` accesses 30+ runtime attributes | Treats runtime as a bag of services |
| `api.py` accesses `runtime._records_store`, `._emit_event`, `._knowledge_store` | API reaches into private internals |
| `assignment.py` writes SQL to Ward Room's DB | Completely bypasses service API |

### 1.5 Event System — Not Formalized

- Events are plain dicts with string type fields. No schema, no event type registry, no typed event classes.
- `_emit_event` is synchronous but triggers async WebSocket broadcasts — works but fragile.
- Event types (`"self_mod_started"`, `"trust_update"`, etc.) are string literals scattered across files.

---

## 2. Code Quality

### 2.1 Swallowed Exceptions — CRITICAL

40+ occurrences of `except Exception: pass` silently discarding errors:

| Location | Impact |
|----------|--------|
| `runtime.py:448` | `_emit_event` — all event emission failures invisible |
| `runtime.py:1255` | Lifecycle detection eats corrupted session records |
| `ward_room.py:226-236` | Schema migration failures masked — could hide data corruption |
| `ward_room.py:971,1151,1171,1208` | Post creation flow — 4 silent swallow points |
| `discord_adapter.py:174-196` | 4 consecutive silent exception swallows |
| `proactive.py:131` | Cooldown restoration failure silently ignored |

**Recommendation:** Define an error handling policy with three categories: "swallow" (truly non-critical), "log-and-degrade", and "propagate". Audit each `except Exception: pass` against this policy.

### 2.2 Duplicated Code — HIGH

- `_format_duration()` — identical implementation in 3 files (`runtime.py:110`, `proactive.py:58`, `cognitive_agent.py:487`)
- `import time as _time` pattern — 9 occurrences across 5 files (workaround for local vars shadowing `time` module)
- Dry-run / confirmation prompt Rich tables — near-identical construction in `__main__.py`
- `to_dict()` — repetitive manual field-by-field serialization in 8 workforce dataclasses
- Ward Room thread construction from SQL rows — 5 identical 15-field extraction blocks

### 2.3 Type Safety — HIGH

95 occurrences of `: Any` across 30 files. Most impactful in `runtime.py` (lines 230-328) where all conditionally-initialized services are typed `Any | None` instead of their concrete types.

`api.py:273` — `runtime: Any` — the primary dependency of the entire API has no type constraint.

### 2.4 hasattr Instead of Proper Init — MEDIUM

30+ uses of `hasattr(self, ...)` to check if attributes exist (14 in `runtime.py` alone). Indicates attributes set outside `__init__`, creating unpredictable class shape.

### 2.5 `os._exit(0)` — HIGH

3 occurrences (`api.py:415`, `__main__.py:340,451`) bypassing `finally` blocks, `atexit` handlers, and buffer flushing. Intentional (BF-068 hang fix) but aggressive.

---

## 3. Security

### 3.1 No API Authentication — CRITICAL (context-dependent)

All ~80+ API endpoints are fully open. Critical unauthenticated endpoints:
- `POST /api/system/shutdown` — system shutdown
- `POST /api/chat` — command execution
- `POST /api/build/submit` — code generation pipeline
- `POST /api/selfmod/approve` — self-modification approval

> **Context:** ProbOS runs on localhost with CORS restricted to `localhost:5173/18900`. No auth is reasonable for local-first. Becomes critical when network-exposed (federation, remote HXI).

### 3.2 Path Traversal in Ship's Records — MEDIUM

`records_store.py` has no path sanitization:

| Line | Method | Risk |
|------|--------|------|
| 119 | `write_entry()` | `../../etc` in callsign could write outside repo |
| 203 | `read_entry()` | `../../etc/passwd` could read outside repo |
| 236 | `list_entries()` | Directory parameter unsanitized |

Flows from API endpoints `POST /api/records/notebooks/{callsign}` and `GET /api/records/documents/{path:path}`.

**Fix:** Add `.resolve()` + `is_relative_to()` validation.

### 3.3 Shell Command Execution — MEDIUM

- `shell_command.py:222` — `shell=True` with LLM-generated commands (by design — it's a shell agent)
- `red_team.py:384` — `shell=True` for verification commands
- `sandbox.py:79-100` — `importlib` exec of LLM-generated Python. Static analysis guard (`CodeValidator`) uses regex patterns, bypassable via `getattr()` indirection

### 3.4 SQL Safety — MOSTLY SAFE

All user-value SQL uses parameterized queries. Two dynamic column name patterns:
- `workforce.py:1089,1121` — `SET {key} = ?` from kwargs dict keys (no whitelist)
- `ward_room.py:1333` — `target_type` in table name selection (constrained by calling code but no SQL-layer validation)

### 3.5 Race Conditions — LOW

Only 3 `asyncio.Lock` instances in entire codebase (identity, records, registry). No locking on:
- `_ws_clients` list (api.py:301) — concurrent WebSocket connect/disconnect
- `_pending_failures` / `_pending_designs` dicts (api.py:31,304)
- Ward Room endorsement voting (TOCTOU in read-modify-write sequence)

### 3.6 Positive Security Findings

- No hardcoded secrets. Proper `CredentialStore` with resolution chain + TTL caching.
- `.env` files are gitignored.
- No `pickle`, no unsafe `yaml.load`. All YAML uses `yaml.safe_load()`.
- No `eval` except one calculator agent with strict regex guard.
- Pre-commit hook guards against commercial content leaking to OSS.
- No dependency lockfile (`poetry.lock` or pinned requirements) — builds not reproducible.

---

## 4. Test Coverage

### 4.1 Overall Assessment

**Python:** 3,899 tests across 173 files. Strong coverage of core systems.

**Frontend:** 149 vitest tests across 10 files. **All store-level only** — zero component rendering tests. ~40+ React components untested.

### 4.2 Well-Tested Modules (Thorough)

| Module | Tests | Files |
|--------|-------|-------|
| Ward Room | 137 | 3 test files |
| Builder | 231 | 3 test files |
| Knowledge Store | 117 | 1 test file |
| Workforce | 114 | 1 test file |
| Decomposer | 107 | 1 test file |
| Self-Mod | 93 | 3 test files |
| Proactive | 92 | 2 test files |
| Ontology | 91 | 5 test files |
| Architect | 77 | 2 test files |
| Emergent Detector | 67 | 1 test file |

### 4.3 Coverage Gaps — Modules Without Dedicated Tests

| Module | Risk |
|--------|------|
| `cognitive/self_model.py` | No tests |
| `cognitive/code_validator.py` | No tests (security-critical) |
| `cognitive/sandbox.py` | No tests (security-critical) |
| `cognitive/skill_designer.py` | No tests |
| `cognitive/skill_validator.py` | No tests |
| `agents/shell_command.py` | No tests |
| `agents/http_fetch.py` | No tests (only regression coverage) |
| `utils/response_formatter.py` | No tests |
| `experience/shell.py` | 15 tests — formatting helpers only. **64% coverage.** No REPL, command dispatch, or error handling tests. |

### 4.4 Critical Untested Paths

1. **Full reset cycle** — No test creates state, resets, then verifies cleanup vs. preservation with actual files
2. **Agent lifecycle integration** — ACM state changes not tested for runtime behavioral impact (suspended agent stops receiving work)
3. **Full episodic pipeline** — No test covers: request → execution → episode storage → dream → Hebbian strengthening
4. **Trust recovery trajectory** — No test verifies recovery from near-zero back to healthy
5. **`code_validator.py` and `sandbox.py`** — Security-critical modules with zero dedicated tests

### 4.5 Regression Test Gaps

| Bug Fix | Regression Test? |
|---------|-----------------|
| BF-065 (Stasis lifecycle) | YES — `test_temporal_context.py` |
| BF-066 (DM extraction) | **MISSING** |
| BF-067 (Ward Room link) | **MISSING** (UI-only) |
| BF-068 (Shutdown exit) | **MISSING** (arguably untestable — `os._exit`) |
| BF-070 (Tiered Reset) | YES — `test_distribution.py`, `test_proactive.py` |

### 4.6 Test Quality Concerns

**Mock overuse:** 1,548 mock invocations across 87 files. Worst offenders:
- `test_proactive.py` — 163 mocks + 36 assert_called
- `test_builder_agent.py` — 117 mocks
- `test_escalation.py` — 81 mocks

**Flaky risk:** `test_dreaming.py` has 10+ `asyncio.sleep()` calls. Two tests have **10-second sleeps** (`test_builder_agent.py:654`, `test_decomposer.py:586`).

**Frontend:** All 149 vitest tests are Zustand store state tests. Zero `@testing-library/react` component rendering tests. No DOM assertions, no user interaction tests. ~40+ React components completely untested.

---

## 5. Missed Considerations

### 5.1 Unbounded Database Growth — CRITICAL

| Database | Table | Cleanup? | Risk |
|----------|-------|----------|------|
| `events.db` | `events` | **None** | Append-only, every heartbeat/spawn/intent logged. Grows indefinitely. |
| `journal.db` | `journal` | Reset only | LLM trace log, append-only during operation. |
| `workforce.db` | `work_items`, `bookings` | **None** | No cleanup mechanism found. |

**`events.db` is the most urgent** — every system event appended with no eviction, rotation, or size cap. Could reach hundreds of MB over weeks.

### 5.2 Foreign Keys Not Enforced — MEDIUM

SQLite requires `PRAGMA foreign_keys = ON` per connection. This pragma is **never executed** anywhere in the codebase. Foreign keys in `ward_room.db` (threads→channels, posts→threads) are purely documentary.

### 5.3 Missing Database Indexes — MEDIUM

| Database | Column | Query Pattern |
|----------|--------|---------------|
| `ward_room.db` threads | `channel_id` | `WHERE channel_id = ?` (frequent) |
| `ward_room.db` posts | `thread_id` | `WHERE thread_id = ?` (frequent) |
| `ward_room.db` posts | `author_id` | Author-based lookups |
| `persistent_tasks.db` | `status`, `webhook_name` | WHERE filters |
| `assignments.db` | `status` | WHERE filters |

### 5.4 Configuration Drift — MEDIUM

| Issue | Location |
|-------|----------|
| `pools.spawn_cooldown_ms` defined, never read | `config.py:17` |
| `dreaming.dream_interval_seconds` defined, never read | `config.py:165` |
| `scaling.idle_scale_down_seconds` defined, never read | `config.py:186` |
| `scaling.observation_window_seconds` defined, never read | `config.py:185` |
| Config version `0.1.0` vs actual `v0.4.0-phase29c` | `config.py:423` |
| Default model names stale (`gpt-4o-mini`, `claude-sonnet-4`) | `config.py:54-56` |
| `EarnedAgencyConfig` exists but no code reads it | `config.py` |

### 5.5 `open()` Without Encoding (Windows) — MEDIUM

| File | Line | Risk |
|------|------|------|
| `crew_profile.py` | 328 | `open(yaml_file, "r")` — no encoding, will fail on non-ASCII |
| `crew_profile.py` | 409 | Same |
| `config.py` | 464 | Config loader — same risk |

### 5.6 Deprecated Async Patterns — MEDIUM

- `asyncio.ensure_future()` used in 10 locations (should be `asyncio.create_task()`)
- `asyncio.get_event_loop()` in `records_store.py:403` (deprecated since Python 3.10)

### 5.7 SIF Placeholder Methods — LOW

`sif.py:273-294` — Three check methods are no-ops returning empty lists:
- `check_config_validity`
- `check_index_consistency`
- `check_memory_integrity`

Registered in the check pipeline but perform no validation. Creates false sense of completeness.

### 5.8 Stale lru_cache — LOW

`standing_orders.py:79-89` — `@lru_cache(maxsize=32)` on `_load_file(path)`. If standing orders files change on disk, cache serves stale content with no invalidation mechanism.

### 5.9 Only 1 TODO in Entire Codebase

`api.py:2802` — `escalation_hook=None,  # TODO(Phase-33): wire to ChainOfCommand`

This is impressively clean. No stub implementations (`NotImplementedError`) exist anywhere.

---

## 6. Recommended Priority Actions

### Immediate (Before Next Feature Wave)

1. **Add `events.db` retention/rotation** — Append-only with no eviction is a ticking time bomb. Add a `max_events` or `max_age_days` config with periodic cleanup.
2. **Fix path traversal in `records_store.py`** — Add `Path.resolve()` + `is_relative_to()` checks. 3 endpoints affected.
3. **Add missing DB indexes** — Ward Room `channel_id` and `thread_id` indexes will prevent degradation as data grows.

### Short-Term (Next 1-2 Sprints)

4. **Establish error handling policy** — Audit 40+ swallowed exceptions. Define which are acceptable (truly non-critical, best-effort) vs. which need logging.
5. **Extract `_format_duration()` to shared utility** — 3 identical copies. Classic DRY fix.
6. **Add `encoding="utf-8"` to `open()` calls** — 3 locations in `crew_profile.py` and `config.py`.
7. **Replace `asyncio.ensure_future()` with `create_task()`** — 10 locations. Modern pattern, prevents GC issues.
8. **Add `PRAGMA foreign_keys = ON`** to SQLite connection initialization.

### Medium-Term (Architecture Health)

9. **Decompose `ProbOSRuntime`** — Extract initialization into focused initializer classes. Replace private-attribute patching with dependency injection or builder pattern.
10. **Extract `api.py` into FastAPI routers** — Group the 80+ endpoints into `APIRouter` instances by domain.
11. **Replace 95 `Any` annotations with concrete types** — Start with `runtime.py` service attributes.
12. **Add public APIs for cross-object access** — Eliminate the 15+ private member accesses, especially `assignment.py` writing SQL to Ward Room's DB.
13. **Formalize event system** — Create an event type registry or typed event classes instead of scattered string literals.

### Long-Term (Test Quality)

14. **Add security tests for `code_validator.py` and `sandbox.py`** — These are security-critical with zero dedicated tests.
15. **Add integration tests for full reset cycle** — Create state → reset → verify.
16. **Add frontend component rendering tests** — Zero DOM/interaction tests currently. At least cover critical flows (chat, Ward Room, agent profile).
17. **Reduce mock density** in `test_proactive.py` (163 mocks) and `test_builder_agent.py` (117 mocks).
18. **Replace 10-second sleeps** in `test_builder_agent.py:654` and `test_decomposer.py:586`.

---

## Appendix: Files Scanned

**Source:** 126 Python files in `src/probos/`
**Tests:** 173 test files in `tests/`
**Frontend:** 55 TSX/TS files in `ui/src/`, 10 test files in `ui/src/__tests__/`
**Config/Docs:** PROGRESS.md, DECISIONS.md, roadmap.md, pyproject.toml, .gitignore

**Review agents:** 5 parallel exploration agents covering code quality, architecture, test coverage, security, and missed considerations. Each agent independently read 30-90+ files.
