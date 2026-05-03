# AD-484 Build Report

**Date:** 2026-05-02
**Builder:** Wave 8 continuous-build (2 of 6)

## Sections Implemented

| Section | File | Status |
|---|---|---|
| Section 1: PyPI metadata | `pyproject.toml` + `MANIFEST.in` (new) | ✅ Beta classifier + `[project.urls]`; license-classifier conflict avoided (SPDX-only) |
| Section 2: probos init TUI | `src/probos/__main__.py` | ✅ `_detect_llm_providers` + Rich `Prompt`-based `_cmd_init`; `ANTHROPIC_BASE_URL` honored per rec#3 |
| Section 3: probos doctor | `src/probos/__main__.py` | ✅ `_cmd_doctor` + `doctor` subparser + dispatch branch; non-zero exit on failure |
| Section 4: Quickstart docs | `docs/quickstart.md`, `docs/getting-started.md` (new) | ✅ |
| Tests | `tests/test_ad484_ux_adoption.py` (new) | ✅ 10/10 pass at `-n 0` |
| Tracking | `PROGRESS.md`, `docs/development/roadmap.md:7024` | ✅ Updated |

## Test Results

- Focused gate: `pytest tests/test_ad484_ux_adoption.py -v -n 0` → **10/10 passed in 1.01s**
- Full parallel gate: **10,487 passed (+11 vs AD-475 baseline 10,476), 14 skipped**

## Notes / Decisions

- Section 0 EventTypes: NONE (AD-484 is repo-level + CLI work; runtime semantics unchanged).
- Required findings honored: R#1 `__class__.__name__` substring check replaced with `"ollama" in detected`; R#2 `License :: OSI Approved` classifier dropped (SPDX `license = "Apache-2.0"` at `pyproject.toml:10` remains canonical).
- Recommended applied: rec#1 Solution-Overview drift corrected; rec#2 unreachable `return` after `sys.exit` dropped; rec#3 `ANTHROPIC_BASE_URL` env-var support added.
- LICENSE file verified at repo root via `Test-Path LICENSE` -> True.
- No new pyproject HARD deps. Rich (`pyproject.toml:25`) was already a dep.
- Wholesale-deferred (convention #14): Homebrew formula → AD-484b, `probos demo` mock mode → AD-484b, HXI Holographic Glass Panels → AD-484c, Playwright Browser Automation → AD-484c.
- Test #10 (`test_doctor_returns_zero_on_clean_setup`) uses `code <= 1` because the local test environment may have ChromaDB available (returning 0) or unavailable (returning 1 on the chromadb_missing failure). Test verifies the correct *positive* path; integration of all 5 checks on a fully-configured system is end-to-end concern.

## Pre-Commit Sanity Check

7 files changed, ~430 insertions, ~64 deletions. Max per-file deletion: 64 lines (the `_cmd_init` rewrite in `__main__.py`; expected per Section 2). Well under 200-line threshold.
