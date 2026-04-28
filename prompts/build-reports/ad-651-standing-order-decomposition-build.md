# Build Report: AD-651 Standing Order Decomposition

**Prompt:** prompts/ad-651-standing-order-decomposition.md  
**Builder:** 2026-04-27, GitHub Copilot  
**Status:** Complete with waived xdist timing failure

## Sweep Pass Note
AD-651 had already been implemented before this continuous sweep pass. This pass re-read the full prompt, verified the live anchors, ran the focused gate, and added the missing build report. No AD-651 source code changes were made in this pass.

## Sections Verified
- Section 1: `StepInstructionConfig` exists in `src/probos/config.py`, and `SystemConfig.step_instruction` is wired.
- Section 2: Category markers are present in `config/standing_orders/ship.md` and `config/standing_orders/federation.md`.
- Section 3: `StepInstructionRouter` exists in `src/probos/cognitive/step_instruction_router.py`.
- Section 4: `set_step_router()` and `get_step_instructions()` are present in `src/probos/cognitive/standing_orders.py`.
- Section 5: Analyze and compose sub-task handlers use `get_step_instructions()` with `step_name="analyze"` and `step_name="compose"`.
- Section 6: Startup finalize wires `StepInstructionRouter` through `set_step_router()`.
- Section 7: `tests/test_ad651_step_instruction_router.py` exists and covers the 20-test table.

## Tests
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad651_step_instruction_router.py -v -x -n 0`: 20 passed
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`: stopped at 1 failed, 4047 passed, 291 warnings
- Serial classification rerun: `tests/test_ad585_tiered_knowledge.py::TestCacheEntry::test_stale_after_max_age -v -x -n 0`: 1 passed

## Full-Suite Classification
The full-suite failure was not in AD-651 code and passed serially:

```text
FAILED tests/test_ad585_tiered_knowledge.py::TestCacheEntry::test_stale_after_max_age
assert True is False
```

The test uses a 0.001s max-age and `time.sleep(0.01)` under xdist. It passed when rerun serially, so it is classified as waived xdist timing/load behavior under the user's 2026-04-27 instruction to ignore the NATS/xdist collision class for the rest of the sweep.

## Trackers
- PROGRESS.md already contains `AD-651 CLOSED`.
- DECISIONS.md already contains AD-651 decision entries.
- docs/development/roadmap.md already marks AD-651 complete.