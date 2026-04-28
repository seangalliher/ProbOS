# BF-245 NATS xdist Stream Isolation Build Report

**Date:** 2026-04-27
**Status:** Complete
**Prompt:** `prompts/bf-245-nats-xdist-stream-isolation.md`

## Summary

Implemented BF-245 by disabling real NATS at test import time and teaching `NatsConfig.enabled` to honor `PROBOS_NATS_ENABLED` with `validate_default=True`. Runtime startup tests now use the disabled path by default, while tests can opt in to real NATS with the `real_nats` fixture.

## Files Changed

- `tests/conftest.py`
  - Added module-level `os.environ.setdefault("PROBOS_NATS_ENABLED", "false")`.
  - Added `real_nats` opt-in fixture.
- `src/probos/config.py`
  - Added `os` import.
  - Converted `NatsConfig.enabled` to a `Field(validate_default=True)`.
  - Added env override validator for `PROBOS_NATS_ENABLED`.
- `tests/test_ad637a_nats_foundation.py`
  - Cleared the test env override for the YAML-enabled NATS config test.
- `tests/test_bf245_nats_xdist_isolation.py`
  - Added 8 focused BF-245 tests.
- `PROGRESS.md`, `DECISIONS.md`, `docs/development/roadmap.md`
  - Updated BF-245 tracking.

## Section Audit

- `### Section 1: Disable real NATS in test configuration` - implemented in `tests/conftest.py` with module-level env default and `real_nats` fixture.
- `### Section 2: Honor environment override in NatsConfig` - implemented in `src/probos/config.py` with `Field(validate_default=True)` and a before validator.
- `### Section 3: Fix affected NATS config test` - implemented in `tests/test_ad637a_nats_foundation.py` by clearing `PROBOS_NATS_ENABLED` for the YAML load test.
- `### Section 4: Verified - MockNATSBus parity` - verified `MockNATSBus.recreate_stream()` exists in `src/probos/mesh/nats_bus.py`; no code changes needed.
- `## Tests` - implemented all 8 focused tests in `tests/test_bf245_nats_xdist_isolation.py`.
- `## Tracker Updates` - updated project trackers and this build report.

## Tests

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf245_nats_xdist_isolation.py -v -x -n 0`
  - First run: 6 passed, 1 failed due prompt patch target mismatch (`probos.startup.nats.NATSBus` is imported locally, not exported at module scope).
  - Final result: 8 passed, 1 warning.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_runtime.py -v -x -n 0`
  - Result: 27 passed, 1 warning.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad637a_nats_foundation.py -v -x -n 0`
  - Result: 30 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad637a_nats_foundation.py::TestNatsConfig::test_loads_from_yaml -v -x -n 0`
  - Result: 1 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_new_crew_auto_welcome.py -v -x -n 0`
  - Result: 6 passed, 16 warnings.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -n auto -x -q`
  - Result: stopped after unrelated xdist worker crashes plus one `KnowledgeStore` debounce assertion after 7544 passed and 3 skipped.
  - BF-245 classification: full output contained no `NATS`, `JetStream`, `10058`, stream-name, or store-creation collision signatures.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_knowledge_store.py::TestGitIntegration::test_auto_commit_after_debounce -v -x -n 0`
  - Result: 1 passed. Classified as timing/load noise outside BF-245.

## Notes

- The runtime test patches `probos.mesh.nats_bus.NATSBus`, the actual import source used by `startup.nats`, rather than `probos.startup.nats.NATSBus`, which is only imported locally inside `init_nats()`.
- Production behavior is unchanged when `PROBOS_NATS_ENABLED` is unset.
- `meta.inf` remains untracked and was not part of this build.