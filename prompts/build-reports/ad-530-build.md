# AD-530 v1 — Build Report

**Wave:** 19 (single-prompt)
**Date:** 2026-05-03
**Risk:** medium
**Status:** SHIPPED

## Test gate

- Baseline (pre-build): 10755 passed, 15 skipped
- Post-build: 10775 passed, 15 skipped (+20)
- Focused gate (`tests/test_ad530_classification_gate.py -v -n 0`): 21/21 passed in 0.30s
- Pre-existing flake observed: `test_trust_dampening.py::TestDampeningIntegration::test_full_cascade_scenario` — passes serially in 0.25s; xdist worker-crash noise per Wave-8/14/16 history; unrelated to AD-530.

## Hard-stop checks

- ✅ Direction: `dst_lvl > src_lvl` → BLOCK (NOT inverted). Verified by Tests #6, #7, #7b.
- ✅ Hierarchy keys match records_store.py:27: `private`/`department`/`ship`/`fleet`. Imported from `probos.knowledge.records_store._CLASSIFICATION_LEVELS` (read-only).
- ✅ `api_key_like` NOT in `_DEFAULT_SENSITIVE_PATTERNS`. Verified by Test #9 + opt-in path Test #9b.
- ✅ Observational only: gate returns `DisclosureDecision`; no message mutation. NO integration with `WardRoomService.create_post` or `LLMClient` prompt builder. Confirmed via `grep -rn "classification_gate" src/probos/` returns wiring-only hits.
- ✅ Privacy invariant: event payload includes `content_length` (NOT content); `blocked_phrases` lists pattern NAMES (NOT matched substrings). Verified by Tests #14 + #15.

Hard-stops triggered: **0**.

## Section audit

- ✅ Section 0 — `events.py`: added `CLASSIFICATION_DISCLOSURE_BLOCKED`.
- ✅ Section 1 — `DisclosureDecision` frozen dataclass + `DisclosureReason` Literal.
- ✅ Section 2 — `ClassificationGate` class with `check_disclosure`, `register_pattern`, `_emit_blocked`, `patterns` / `pattern_count` properties.
- ✅ Section 3 — `ClassificationGateConfig` + `SystemConfig.classification_gate` field.
- ✅ Section 4 — `_wire_classification_gate` in finalize.py + invocation in `finalize_startup`.

## Files touched

- `src/probos/security/classification.py` (new, +210 lines)
- `tests/test_ad530_classification_gate.py` (new, +278 lines)
- `src/probos/events.py` (+1 line)
- `src/probos/config.py` (+8 lines)
- `src/probos/startup/finalize.py` (+19 lines)
- `PROGRESS.md` (prepended AD-530 v1 entry)
- `DECISIONS.md` (prepended AD-530 v1 entry under Era V)
- `docs/development/roadmap.md` (1-line status flip)

## Direction confirmation

```python
# records_store.py:27
_CLASSIFICATION_LEVELS = {"private": 0, "department": 1, "ship": 2, "fleet": 3}
# higher index = BROADER access

# classification.py:check_disclosure
src_lvl = _CLASSIFICATION_LEVELS.get(source_classification, _CLASSIFICATION_LEVELS["private"])  # default = MOST RESTRICTIVE
dst_lvl = _CLASSIFICATION_LEVELS.get(destination_clearance, _CLASSIFICATION_LEVELS["ship"])     # default = BROADEST
if dst_lvl > src_lvl:  # destination has broader reach than source permits → BLOCK
    ...
```

Safety pairs:
- `private(0) → ship(2)`: `2 > 0` → **BLOCK** ✅
- `ship(2) → department(1)`: `1 > 2` → False → **ALLOW** ✅
- `department(1) → private(0)`: `0 > 1` → False → **ALLOW** ✅

## Pre-commit deletion sanity check

Run before commit: `git diff --cached --stat` — no unintended deletions expected.
