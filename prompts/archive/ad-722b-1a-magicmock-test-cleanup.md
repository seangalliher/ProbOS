# AD-722b-1a — Replace MagicMock-shaped configs with real `SystemConfig()` in legacy AD-722b-4 tests, then remove the `isinstance(token, str)` defensive guard

**Wave:** 162
**Closes:** #657
**Status:** ready to build
**Dependencies:** AD-722b-1 (Wave 161 — auth dependency shipped).
**Estimated tests:** 0 net (refactor existing fixtures; no new test files).
**Scope tag:** Hygiene / anti-pattern fix. Server-only. No new pip/npm deps. Apache 2.0.

---

## Problem

Wave 161 / AD-722b-1 added a defensive guard at [src/probos/routers/auth.py](src/probos/routers/auth.py#L43):

```python
token = getattr(auth_cfg, "crew_scope_token", "")
if not isinstance(token, str):
    return ""
```

The guard exists solely to absorb `MagicMock`-shaped `runtime.config` objects that legacy AD-722b-4 test fixtures return. Per `.github/copilot-instructions.md` engineering principles, tests must construct **real** `SystemConfig()` instances (or scoped sub-configs) rather than `MagicMock(spec=SystemConfig)`. The guard is an anti-pattern review flag (defensive shape-check at the production boundary for a test-only failure mode).

The eight existing MagicMock sites are:

| File | Line | Pattern |
|------|------|---------|
| `tests/conftest.py` | 196 | `rt.config = MagicMock(spec=SystemConfig)` |
| `tests/test_ad437_action_space.py` | 209 | `runtime.config = MagicMock(spec=SystemConfig)` |
| `tests/test_ad576_llm_unavailability.py` | 49 | `rt.config = MagicMock(spec=SystemConfig)` |
| `tests/test_circuit_breaker.py` | 273 | `rt.config = MagicMock(spec=SystemConfig)` |
| `tests/test_proactive.py` | 1787 | `config=MagicMock(spec=SystemConfig, ward_room=MagicMock())` |
| `tests/test_proactive.py` | 1837 | same shape |
| `tests/test_proactive_quality.py` | 40 | `rt.config = MagicMock(spec=SystemConfig)` |

(The shared `conftest.py` fixture at line 196 is the canonical entry; many other tests inherit from it transitively.)

---

## Solution overview

1. Replace each MagicMock site with a real `SystemConfig()` construction. Where a test needs a specific sub-config attribute (e.g. `ward_room`), construct only the **named sub-config** in a real form and leave the rest as `SystemConfig` defaults.
2. After all eight sites pass `pytest -n 0` with real configs, remove the `isinstance(token, str)` block from `routers/auth.py:43-44` and the corresponding docstring sentence.
3. Verify the full parallel gate stays green.

### What this does NOT change

- `AuthConfig.crew_scope_token` schema or default.
- `require_crew_scope` / `verify_ws_token` behavior (functional contract unchanged).
- The empty-token = auth-disabled invariant.
- Any non-`config`-attribute MagicMock usage in the same test files (this AD targets ONLY the `config=MagicMock(spec=SystemConfig)` pattern).

---

## Section 1 — Migrate `tests/conftest.py` (the shared fixture)

The fixture at `tests/conftest.py:196` is the highest-leverage site. Replace the MagicMock with a real `SystemConfig` using `model_construct(_recursive=True)` or `SystemConfig()` directly, whichever satisfies the existing fixture's downstream callers without forcing unrelated changes.

Single `replace_string_in_file` call (BF-274 — adjacent edits forbidden via multi-replace).

After the change, run:

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/conftest.py tests/test_routers_auth.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile
```

If any test that previously consumed the MagicMock fixture now needs a specific attribute path (e.g., `ward_room.proactive_enabled`), reconstruct the minimal real sub-config with `WardRoomConfig(proactive_enabled=False)` (or whatever the real default is) — never re-introduce a MagicMock at the `config=` boundary.

---

## Sections 2-7 — Migrate each remaining site

One section per file. Each section is a single `replace_string_in_file` (BF-274). Run the file's tests at `-n 0` after each migration. Do not batch.

Order:
1. `tests/test_proactive.py` (two sites, two separate replaces).
2. `tests/test_proactive_quality.py`.
3. `tests/test_ad437_action_space.py`.
4. `tests/test_ad576_llm_unavailability.py`.
5. `tests/test_circuit_breaker.py`.

For each: read 5 lines of context around the MagicMock line, replace ONLY the `config=` boundary, keep all other MagicMock usage in the test untouched.

---

## Section 8 — Remove the defensive guard

After all eight migrations land and the full parallel gate is green, edit `src/probos/routers/auth.py` `_configured_token`:

**Before:**
```python
auth_cfg = getattr(cfg, "auth", None)
if auth_cfg is None:
    return ""
token = getattr(auth_cfg, "crew_scope_token", "")
if not isinstance(token, str):
    return ""
return token
```

**After:**
```python
auth_cfg = getattr(cfg, "auth", None)
if auth_cfg is None:
    return ""
return auth_cfg.crew_scope_token
```

Also remove the "Defensive: only honors a real ``str`` value..." paragraph from the docstring (lines ~32-36).

Re-run the focused auth tests and the full parallel gate.

---

## Tests

No new tests. Existing AD-722b-1 tests (`tests/test_routers_auth.py`, `tests/test_ad722b1_auth.py` if present) must stay green at `-n 0` AND under the parallel gate.

Acceptance: total test count unchanged ± 0. Net test delta is `0`. If any test that previously relied on the MagicMock's missing-attribute behavior now fails, the test is depending on undefined behavior — fix the test, do not re-introduce MagicMock.

---

## Tracking

- `PROGRESS.md` — append Wave 162 bullet referencing this AD + #657.
- `docs/development/roadmap.md` — flip the AD-722b-1a row from forward marker to SHIPPED Wave 162.
- `DECISIONS.md` — append an entry under Wave 162: "AD-722b-1a (#657): replaced eight MagicMock(spec=SystemConfig) sites with real configs; removed isinstance(token, str) guard at routers/auth.py:43."

---

## Acceptance criteria

- All eight MagicMock(spec=SystemConfig) sites in tests/ replaced with real `SystemConfig()` constructions.
- `routers/auth.py:43-44` `isinstance(token, str)` guard removed.
- Docstring updated (no "MagicMock" mention).
- Full parallel gate: `pytest tests/ -q -n 4 --dist=loadfile` green.
- No new dependencies. `pyproject.toml` untouched.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-15)

- `routers/auth.py:43` — `if not isinstance(token, str):` confirmed.
- `routers/auth.py:10` — out-of-scope comment lists AD-722b-1a as a forward marker. This AD closes that marker.
- 8 MagicMock(spec=SystemConfig) call sites confirmed in tests/ via repository grep.
- `AuthConfig` and `SystemConfig` constructable with zero args (Pydantic models with all defaults present — see `config.py`).
