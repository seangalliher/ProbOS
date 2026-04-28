# Build Report: AD-603 Anchor Recall Composite Scoring

**Prompt:** prompts/ad-603-anchor-recall-composite-scoring.md  
**Builder:** 2026-04-27, GitHub Copilot  
**Status:** Complete with waived xdist timing failure

## Files Changed
- src/probos/cognitive/episodic.py
- src/probos/cognitive/cognitive_agent.py
- tests/test_ad603_anchor_recall_composite_scoring.py
- PROGRESS.md
- DECISIONS.md
- docs/development/roadmap.md
- prompts/build-reports/ad-603-anchor-recall-composite-scoring-build.md

## Sections Implemented
- Section 1: Added `recall_by_anchor_scored()` to EpisodicMemory.
- Section 2a: Updated `_try_anchor_recall()` to prefer scored anchor recall and fall back to `recall_by_anchor()`.
- Section 2b: Updated CognitiveAgent merge logic to combine scored anchor and semantic results by `composite_score` while preserving legacy unscored fallback.
- Section 3: Added 18 AD-603 tests covering scored anchor recall signals and merge behavior.

## Tests
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad603_anchor_recall_composite_scoring.py -v -x -n 0`: 18 passed
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad567b_anchor_recall.py -v -x -n 0`: 30 passed, 1 warning
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_cognitive_agent.py::TestMemoryRecall -v -x -n 0`: 5 passed
- `git diff --check -- src/probos/cognitive/episodic.py src/probos/cognitive/cognitive_agent.py tests/test_ad603_anchor_recall_composite_scoring.py`: passed with no output
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`: stopped at 1 failed, 4249 passed, 292 warnings
- Serial classification rerun: `tests/test_ad580_alert_feedback.py::TestAlertResolve::test_resolve_refires_after_clean_period -v -x -n 0`: 1 passed

## Full-Suite Classification
The full-suite failure was unrelated to AD-603 touched files:

```text
FAILED tests/test_ad580_alert_feedback.py::TestAlertResolve::test_resolve_refires_after_clean_period
AssertionError: assert True is False
```

The failing test uses a 0.02s clean period and `time.sleep(0.03)` under an xdist worker. It passed immediately when rerun serially, so it is classified as waived xdist timing/load behavior under the user's 2026-04-27 instruction to ignore the NATS/xdist collision class for the rest of the sweep.

## Deviations from Prompt
- Preserved the newer `RecallScore.tcm_similarity` field when rebuilding boosted scores.
- The prompt sample used `if _is_scored and scored_results`; the implementation handles scored anchor-only results too, matching the prompt's Test 18 expectation.
- The tests use deterministic `_FakeCollection` and `AsyncMock` recall hooks instead of a real ChromaDB ephemeral client to avoid embedding/ONNX flakiness while covering the specified scoring and merge behavior.

## Trackers Updated
- PROGRESS.md: marked AD-603 COMPLETE.
- DECISIONS.md: added AD-603 decision entry.
- docs/development/roadmap.md: updated AD-603 from planned to complete.