# AD-711 build report — claude-bootstrap-derived `probos init` security defaults

**Prompt:** `prompts/claude-bootstrap-init-defaults-v1.md`
**Builder:** Wave 130 builder (continuous mode)
**Date:** 2026-05-08
**Status:** SHIPPED
**Issue closed:** #495
**Wave:** 130 (1 of 10)

## Files Changed

- `src/probos/config.py` — new `PermissionsConfig` model; extended existing `SecurityConfig` (AD-455) additively with `profile: Literal["strict","relaxed"]` and `permissions: PermissionsConfig`.
- `src/probos/__main__.py` — `_cmd_init` security-profile resolution + strict/relaxed block append; new `--security-profile` argparse flag; new doctor "Check 6" (security profile sanity).
- `tests/test_claude_bootstrap_init_defaults.py` — 11 new tests (init x4, pydantic x3, doctor x4).
- `DECISIONS.md` — AD-711 entry appended.

## Sections Implemented

- **D1.** `_cmd_init` security-profile resolution + strict/relaxed YAML block — implemented in `__main__.py` after `home` resolution and at the end of the `config_content` template assembly.
- **D2.** `--security-profile` argparse flag — implemented at the init subparser registration site.
- **D3.** `probos doctor` security check — implemented as Check 6 inside `_cmd_doctor`.
- **D4.** `PermissionsConfig` + extended `SecurityConfig` — implemented in `config.py`. `Literal` was already imported (config.py:7); no additional imports needed.
- **D5.** Tests — 11 cases written and all passing.

## Post-Build Section Audit

All five `###`/`D*` sections from the prompt have corresponding code changes. No omissions.

## AD-numbering deviation (architect-relevant)

The prompt cited **AD-709** in code comments, doctor failure strings, and YAML template comments. Pre-flight grep against `docs/development/roadmap.md` showed AD-709 already reserved for **MemoryForge** (#485). Builder reassigned the AD per the standing "never reuse AD numbers" convention:

- claude-bootstrap → **AD-711** (next free above wave-129 ceiling AD-710).
- Forward marker AD-712 (runtime enforcement) → **AD-711-1** (sub-AD), so Memvid-QP can take AD-712 in this wave.
- Forward markers AD-709-1, AD-709-2 → **AD-711-2, AD-711-3**.

All in-code, in-test, and DECISIONS references updated to AD-711 / AD-711-1.

## Test Results

```
.\.venv\Scripts\pytest.exe tests/test_claude_bootstrap_init_defaults.py -v -n 0
11 passed in 13.60s
```

Broader related-area gate (security/doctor/init keyword filter): **380 passed**.

Full gate:
```
.\.venv\Scripts\pytest.exe tests/ -q -n 8 --dist=loadfile
12782 passed, 16 skipped, 175 warnings in 475.96s
```

Baseline pre-AD-711: 12771 passed → +11 = 12782 passed. Test count non-decreasing.

## Verify-First Findings

- ✅ `_cmd_init` at `__main__.py:599` matches prompt cite.
- ✅ Init subparser at `__main__.py:1270` matches prompt cite.
- ✅ `_cmd_doctor` failure-accumulation pattern matches prompt cite.
- ⚠️ **`SecurityConfig` already exists** (AD-455 — Security Team config) at `config.py:1762`. Builder extended the existing class additively rather than introducing a name collision. Doctor check uses `cfg.security.profile` and `cfg.security.permissions.deny` exactly as the prompt specifies; behaviorally equivalent. Existing AD-455 fields untouched.
- ✅ `Literal` already imported at `config.py:7` — no additional import needed (prompt's verify-first instruction covered this).

## Hard Constraints Honored

- ✅ No runtime enforcement of deny-list (deferred to AD-711-1).
- ✅ No interactive weakening prompt; `--security-profile relaxed` is the only weakening path.
- ✅ No absorption of TDD hooks, agent-team scaffolding, mnemos/iCPG, skills registry, `CLAUDE.md` `@include` model.
- ✅ No verbatim text from claude-bootstrap.
- ✅ `_cmd_init` defaults preserved; security block is additive.

## Pre-Commit Deletion Check

`git diff --cached --numstat` top-5 — no file shows >200 deletions. Clean.

## Engineering Principles Compliance

- ✅ SOLID: `PermissionsConfig` is a single-responsibility model; `SecurityConfig` extended additively without violating SRP.
- ✅ Type annotations: all new public fields/parameters have full annotations (`Literal["strict","relaxed"]`, `list[str]`).
- ✅ No `print()` calls; uses `console.print` (existing pattern).
- ✅ Log/console messages include context (what failed + remediation hint).
- ✅ No fire-and-forget tasks introduced.
- ✅ Boundary tests: happy path (strict + relaxed), error case (invalid profile, unknown literal), edge case (default omitted, empty deny list, missing security section).
- ✅ Test isolation: each test creates own tmp_path-scoped fixtures, no shared mutable state.
